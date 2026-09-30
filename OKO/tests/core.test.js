// Тесты ядра классификации ОКО. Запуск: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const C = require('../web/assets/oko-core.js');

const sources = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', 'sources.json'), 'utf8')).sources;
const reg = new C.Registry(sources);

function item(o) {
  return Object.assign({ id: 'x' + Math.random().toString(16).slice(2), title: '', snippet: '', ts: 1790676000, lang: 'en',
    src_name: '', src_url: '', domain: '', prov: ['gnews'], via: [], authors: [], related: [], extra: {}, kind: 'news', hit: 'title' }, o);
}
function run(items) {
  items.forEach((it) => C.classify(it, reg));
  C.cluster(items, ['uzbek', 'узбеки']);
  items.forEach((it) => C.classify(it, reg));
  return items;
}

test('реестр: домены, поддомены, разделы сайтов', () => {
  assert.strictEqual(reg.lookup('https://www.bbc.com/russian/x').id, 'bbc_russian');
  assert.strictEqual(reg.lookup('https://www.bbc.com/news/x').id, 'bbc');
  assert.strictEqual(reg.lookup('https://en.kremlin.ru/events/1').id, 'kremlin');
  assert.strictEqual(reg.lookup('carnegieendowment.org').tier, 1);
  assert.strictEqual(reg.lookup('https://nowhere.example/'), null);
});

test('официальные и международные домены распознаются без реестра', () => {
  const [a, b, c] = run([item({ domain: 'mfa.gov.kz', title: 'Kazakhstan and Uzbekistan statement' }),
    item({ domain: 'unhabitat.int', title: 'Report on Uzbekistan housing' }),
    item({ domain: 'blog.example', title: 'Uzbekistan travel notes' })]);
  assert.deepStrictEqual([a.type, a.tier, a.origin.status], ['official', 1, 'primary']);
  assert.deepStrictEqual([b.type, b.tier], ['intl_org', 1]);
  assert.deepStrictEqual([c.tier, c.inRegistry], [4, false]);
});

test('агрегатор всегда перепубликация', () => {
  const [y] = run([item({ domain: 'yahoo.com', src_name: 'Yahoo News', title: 'Uzbekistan signs deal', gn: true })]);
  assert.strictEqual(y.origin.status, 'reprint');
  assert.strictEqual(y.origin.confidence, 'high');
});

test('ссылки на агентства в разных языках', () => {
  const cases = [
    ['ru', 'Газета.uz', 'gazeta.uz', 'Узбекистан нарастит экспорт газа, сообщает Reuters', 'Reuters'],
    ['ru', 'Podrobno.uz', 'podrobno.uz', 'Мирзиёев встретился с Путиным, передает ТАСС', 'ТАСС'],
    ['en', 'Dawn', 'dawn.com', 'Uzbekistan, Pakistan sign rail deal (AFP)', 'AFP'],
    ['ja', '47NEWS', '47news.jp', 'ウズベキスタン大統領が来日へ（共同）', 'Kyodo'],
    ['zh', '观察者网', 'guancha.cn', '据新华社报道，乌兹别克斯坦总统将访华', 'Синьхуа'],
    ['ar', 'Al Khaleej', 'alkhaleej.ae', 'أوزبكستان توقع اتفاقية، نقلا عن رويترز', 'Reuters'],
    ['ko', 'KBS', 'kbs.co.kr', '우즈베키스탄 대통령 방한, 연합뉴스 보도에 따르면', 'Yonhap'],
  ];
  for (const [lang, name, domain, title, expected] of cases) {
    const [it] = run([item({ lang, src_name: name, domain, title })]);
    assert.strictEqual(it.origin.status, 'reprint', title);
    assert.strictEqual(it.origin.credited.label, expected, title);
  }
});

test('собственная пометка агентства не считается перепубликацией', () => {
  const [r] = run([item({ domain: 'reuters.com', src_name: 'Reuters', title: 'Uzbekistan and US sign deal', snippet: 'TASHKENT, Sept 30 (Reuters) - Uzbekistan and the US...' })]);
  assert.strictEqual(r.origin.status, 'primary');
});

test('аналитический центр, цитирующий агентство, остаётся первоисточником', () => {
  const [a] = run([item({ domain: 'brookings.edu', src_name: 'Brookings', title: 'Uzbekistan’s reforms', snippet: 'According to Reuters, the reform agenda has slowed.' })]);
  assert.strictEqual(a.origin.status, 'primary');
  assert.match(a.origin.reason, /цитируется Reuters/);
});

test('совпадающие заголовки: ранняя публикация — первоисточник, поздняя — перепубликация', () => {
  const [t, l] = run([
    item({ id: 't', lang: 'ru', domain: 'tass.ru', src_name: 'ТАСС', title: 'Мирзиёев провел переговоры с Путиным в Москве', ts: 1790600000 }),
    item({ id: 'l', lang: 'ru', domain: 'lenta.ru', src_name: 'Лента.ру', title: 'Мирзиёев провел переговоры с Путиным в Москве', ts: 1790607200 })]);
  assert.strictEqual(t.origin.status, 'primary');
  assert.strictEqual(l.origin.status, 'reprint');
  assert.strictEqual(l.dupOf, 't');
  assert.strictEqual(t.storySize, 2);
});

test('похожие, но разные заголовки объединяются в сюжет без пометки дубля', () => {
  const items = run([
    item({ id: 'a', title: 'Uzbekistan and US sign critical minerals agreement in Tashkent', domain: 'reuters.com', src_name: 'Reuters' }),
    item({ id: 'b', title: 'US and Uzbekistan agree critical minerals deal during Tashkent visit', domain: 'apnews.com', src_name: 'AP' }),
    item({ id: 'c', title: 'Cotton harvest begins in Fergana valley', domain: 'kun.uz', src_name: 'Kun.uz' })]);
  assert.strictEqual(items[0].story, items[1].story);
  assert.notStrictEqual(items[0].story, '');
  assert.strictEqual(items[1].dupOf, undefined);
  assert.strictEqual(items[2].storySize, 1);
});

test('глубокая проверка: canonical на другое издание', () => {
  const [it] = run([item({ domain: 'msn-like.example', src_name: 'Portal', title: 'Uzbekistan deal',
    meta: { ok: true, canonical: 'https://www.reuters.com/world/x', canonical_domain: 'reuters.com', final_url: 'https://msn-like.example/a', authors: [], credits: [] } })]);
  assert.strictEqual(it.origin.status, 'reprint');
  assert.strictEqual(it.origin.credited.label, 'Reuters');
});

test('научные публикации: уровень по журналу', () => {
  const [a, b] = run([item({ kind: 'paper', src_name: 'Central Asian Survey', domain: 'tandfonline.com', title: 'Water in Uzbekistan' }),
    item({ kind: 'paper', src_name: 'Some Journal', domain: 'journal.example', title: 'Uzbekistan study', extra: { publisher: 'Unknown Press' } })]);
  assert.deepStrictEqual([a.tier, a.type, a.origin.status], [1, 'academic', 'primary']);
  assert.strictEqual(b.tier, 3);
});

test('сортировка по авторитетности', () => {
  const items = run([item({ id: '1', domain: 'blog.example', title: 'Uzbekistan 1' }), item({ id: '2', domain: 'csis.org', title: 'Uzbekistan 2' }),
    item({ id: '3', domain: 'kun.uz', title: 'Uzbekistan 3' })]);
  C.sortItems(items, 'authority');
  assert.deepStrictEqual(items.map((x) => x.id), ['2', '3', '1']);
});

test('библиографическая ссылка', () => {
  const [it] = run([item({ domain: 'csis.org', title: 'Uzbekistan outlook', authors: ['A. Author'], url: 'https://www.csis.org/a', ts: 1790676000 })]);
  const c = C.citation(it, new Date(2026, 8, 30));
  assert.match(c, /^A\. Author\. Uzbekistan outlook \/\/ Center for Strategic and International Studies/);
  assert.match(c, /дата обращения: 30\.09\.2026/);
});
