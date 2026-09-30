/* ОКО — интерфейс платформы мониторинга аналитических источников. */
(function () {
  'use strict';
  const C = window.OKOCore;
  const D = window.OKO_DATA || { sources: [], languages: [], lexicon: [] };

  // ================================================================ утилиты
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = v;
        else if (k === 'on') for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
        else if (k === 'data') for (const [dk, dv] of Object.entries(v)) n.dataset[dk] = dv;
        else if (k === 'style') n.setAttribute('style', v);
        else if (k === 'href') { const u = safeUrl(v) || (/^(\/|#)/.test(String(v)) ? v : null); if (u) n.setAttribute('href', u); }
        else if (v === true) n.setAttribute(k, '');
        else n.setAttribute(k, v);
      }
    }
    for (const k of kids.flat()) {
      if (k === null || k === undefined || k === false) continue;
      n.appendChild(typeof k === 'string' || typeof k === 'number' ? document.createTextNode(String(k)) : k);
    }
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  function safeUrl(u) {
    try { const x = new URL(u); return x.protocol === 'http:' || x.protocol === 'https:' ? x.href : null; } catch (e) { return null; }
  }
  function extLink(url, text, cls) {
    const u = safeUrl(url);
    if (!u) return el('span', { class: cls }, text);
    return el('a', { href: u, target: '_blank', rel: 'noopener noreferrer', class: cls }, text);
  }
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ICONS = {
    check: 'M3 8.5l3.2 3.2L13 4.8', repeat: 'M3 6.2h8.5L9.3 4M13 9.8H4.5l2.2 2.2', ext: 'M6.5 3H3v10h10V9.5M9 3h4v4M13 3L7.5 8.5',
    copy: 'M5.5 5.5h7.5V13H5.5zM3 10.5V3h7.5', pdf: 'M4 1.5h5.2L12.5 5v9.5H4zM9 1.5V5h3.5M6 9h4M6 11.5h4',
    lock: 'M4.8 7.2V5.1a3.2 3.2 0 016.4 0v2.1M3.6 7.2h8.8v6.6H3.6z', archive: 'M2 3h12v3H2zM3 6v7.5h10V6M6.3 9h3.4',
    translate: 'M1.8 3.4h7.4M5.5 2v1.4c0 2.9-1.6 5-3.7 6.1M3.7 6.5c1 2.1 2.9 3.6 5 4.2M8.8 14.5l3-7.3 3 7.3M9.9 12.1h3.8',
    reader: 'M2.5 3.5h11M2.5 6.5h11M2.5 9.5h7.5M2.5 12.5h9.5', shield: 'M8 1.6l5.4 2v4c0 3.5-2.4 5.9-5.4 7-3-1.1-5.4-3.5-5.4-7v-4zM5.6 8.1l1.8 1.8 3.1-3.4',
    star: 'M8 1.9l1.85 3.85 4.2.55-3.07 2.94.77 4.16L8 11.4l-3.75 2 .77-4.16L1.95 6.3l4.2-.55z', search: 'M7 12.2A5.2 5.2 0 107 1.8a5.2 5.2 0 000 10.4zM10.8 10.8l3.6 3.6',
    save: 'M2.5 2.5h9l2 2v9h-11zM5 2.5v3.5h5V2.5M5 13.5V9.5h6v4', quote: 'M3 4h4v4H4.5L3 11V4zM9 4h4v4h-2.5L9 11V4z',
    eye: 'M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8zM8 10a2 2 0 100-4 2 2 0 000 4z'
  };
  function icon(name, filled) {
    const s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('viewBox', '0 0 16 16');
    s.setAttribute('aria-hidden', 'true');
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', ICONS[name] || '');
    p.setAttribute('fill', filled ? 'currentColor' : 'none');
    p.setAttribute('stroke', 'currentColor');
    p.setAttribute('stroke-width', '1.5');
    p.setAttribute('stroke-linecap', 'round');
    p.setAttribute('stroke-linejoin', 'round');
    s.appendChild(p);
    return s;
  }
  let toastTimer = null;
  function toast(msg, err) {
    let t = $('#toast');
    if (!t) { t = el('div', { id: 'toast', class: 'toast' }); document.body.appendChild(t); }
    t.textContent = msg;
    t.className = 'toast' + (err ? ' err' : '');
    t.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add('hidden'), err ? 6000 : 3200);
  }
  const pad = (n) => String(n).padStart(2, '0');
  function fmtDate(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function fmtShort(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    const now = new Date();
    const dm = pad(d.getDate()) + '.' + pad(d.getMonth() + 1);
    return (d.getFullYear() !== now.getFullYear() ? dm + '.' + String(d.getFullYear()).slice(2) : dm) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function fmtUTC(ts) { return ts ? new Date(ts * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : ''; }
  function tzLabel() {
    const off = -new Date().getTimezoneOffset();
    const h = Math.floor(Math.abs(off) / 60), m = Math.abs(off) % 60;
    return 'UTC' + (off >= 0 ? '+' : '−') + h + (m ? ':' + pad(m) : '');
  }
  function ago(ts) {
    const s = Math.floor(Date.now() / 1000) - ts;
    if (s < 60) return 'только что';
    if (s < 3600) return Math.floor(s / 60) + ' мин назад';
    if (s < 86400) return Math.floor(s / 3600) + ' ч назад';
    return Math.floor(s / 86400) + ' дн назад';
  }
  function splitList(v) { return String(v || '').split(/[,;\n]+/).map((x) => x.trim()).filter(Boolean); }
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  const store = {
    get(k, d) { try { const v = localStorage.getItem('oko:' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('oko:' + k, JSON.stringify(v)); } catch (e) { /* хранилище недоступно */ } }
  };
  function download(name, content, type) {
    const blob = new Blob([content], { type });
    const a = el('a', { download: name });
    a.href = URL.createObjectURL(blob);
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
  }
  function copyText(t) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t).then(() => toast('Скопировано'));
    const ta = el('textarea', { style: 'position:fixed;opacity:0' });
    ta.value = t; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); toast('Скопировано'); } catch (e) { toast('Не удалось скопировать', true); }
    ta.remove();
    return Promise.resolve();
  }

  const COUNTRY = {
    US: 'США', GB: 'Великобритания', RU: 'Россия', CN: 'Китай', UZ: 'Узбекистан', KZ: 'Казахстан', KG: 'Кыргызстан',
    TJ: 'Таджикистан', TM: 'Туркменистан', AF: 'Афганистан', IR: 'Иран', PK: 'Пакистан', IN: 'Индия', TR: 'Турция',
    DE: 'Германия', FR: 'Франция', IT: 'Италия', ES: 'Испания', JP: 'Япония', KR: 'Республика Корея', KP: 'КНДР',
    SA: 'Саудовская Аравия', AE: 'ОАЭ', QA: 'Катар', IL: 'Израиль', EG: 'Египет', AZ: 'Азербайджан', GE: 'Грузия',
    AM: 'Армения', UA: 'Украина', BY: 'Беларусь', PL: 'Польша', CA: 'Канада', AU: 'Австралия', NZ: 'Новая Зеландия',
    BR: 'Бразилия', MX: 'Мексика', AR: 'Аргентина', CH: 'Швейцария', AT: 'Австрия', BE: 'Бельгия', NL: 'Нидерланды',
    SE: 'Швеция', NO: 'Норвегия', DK: 'Дания', FI: 'Финляндия', IE: 'Ирландия', PT: 'Португалия', GR: 'Греция',
    CZ: 'Чехия', HU: 'Венгрия', RO: 'Румыния', BG: 'Болгария', RS: 'Сербия', HR: 'Хорватия', LV: 'Латвия', LT: 'Литва',
    EE: 'Эстония', MD: 'Молдова', MN: 'Монголия', SG: 'Сингапур', MY: 'Малайзия', ID: 'Индонезия', TH: 'Таиланд',
    VN: 'Вьетнам', PH: 'Филиппины', BD: 'Бангладеш', LK: 'Шри-Ланка', NP: 'Непал', HK: 'Гонконг', TW: 'Тайвань',
    IQ: 'Ирак', SY: 'Сирия', LB: 'Ливан', JO: 'Иордания', KW: 'Кувейт', BH: 'Бахрейн', OM: 'Оман', YE: 'Йемен',
    MA: 'Марокко', DZ: 'Алжир', TN: 'Тунис', LY: 'Ливия', NG: 'Нигерия', KE: 'Кения', ZA: 'ЮАР', ET: 'Эфиопия',
    CL: 'Чили', CO: 'Колумбия', PE: 'Перу', VE: 'Венесуэла', CU: 'Куба', SK: 'Словакия', SI: 'Словения', CY: 'Кипр',
    LU: 'Люксембург', IS: 'Исландия', AL: 'Албания', BA: 'Босния и Герцеговина', MK: 'Северная Македония', ME: 'Черногория',
    XK: 'Косово', MM: 'Мьянма', KH: 'Камбоджа', LA: 'Лаос', INT: 'Международная организация', EU: 'Европейский союз'
  };
  const LANG_RU = {
    ru: 'Русский', en: 'Английский', fr: 'Французский', de: 'Немецкий', es: 'Испанский', it: 'Итальянский', ko: 'Корейский',
    ja: 'Японский', zh: 'Китайский', fa: 'Персидский', ar: 'Арабский', ur: 'Урду', tr: 'Турецкий', uz: 'Узбекский',
    he: 'Иврит', hi: 'Хинди', kk: 'Казахский', pt: 'Португальский', uk: 'Украинский', pl: 'Польский', nl: 'Нидерландский',
    ky: 'Киргизский', tg: 'Таджикский', tk: 'Туркменский', az: 'Азербайджанский', ka: 'Грузинский', hy: 'Армянский',
    ps: 'Пушту', bn: 'Бенгальский', id: 'Индонезийский', ms: 'Малайский', th: 'Тайский', vi: 'Вьетнамский', el: 'Греческий',
    cs: 'Чешский', hu: 'Венгерский', ro: 'Румынский', bg: 'Болгарский', sr: 'Сербский', sv: 'Шведский', fi: 'Финский',
    da: 'Датский', no: 'Норвежский', mn: 'Монгольский', 'zh-Hant': 'Китайский (трад.)'
  };
  const countryName = (cc) => (cc ? (COUNTRY[cc] || cc) : '—');
  const langName = (c) => (c ? (LANG_RU[c] || LANG_RU[c.slice(0, 2)] || c) : '—');
  const ORIGIN_LABEL = { primary: 'Первоисточник (оригинал)', reprint: 'Перепубликация', unknown: 'Не определено' };
  const CONF_LABEL = { high: 'высокая уверенность', medium: 'средняя уверенность', low: 'низкая уверенность' };
  const RTL = new Set(['ar', 'fa', 'ur', 'he']);

  // ================================================================ связь с сервером
  const TOKEN = (document.querySelector('meta[name=oko-token]') || {}).content || '';
  const SERVER = /^https?:$/.test(location.protocol) && !!TOKEN;

  async function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || 'GET', headers: { 'X-OKO-Token': TOKEN } };
    if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    if (opts.signal) init.signal = opts.signal;
    const r = await fetch(path, init);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) throw new Error((data && data.error) || ('HTTP ' + r.status));
    return data;
  }

  // ================================================================ состояние
  const S = {
    boot: null, languages: D.languages || [], langOn: new Set(), registry: new C.Registry(D.sources || []), sources: D.sources || [],
    mode: 'registry', minTier: 4, types: new Set(), providers: new Set(), preset: '7d', range: null,
    expansion: null, expKey: '', items: new Map(), meta: new Map(), jobId: null, running: false, abort: null,
    tasks: new Map(), stats: {}, notes: [], planInfo: [], started: 0, done: null,
    filters: { tier: new Set(), origin: new Set(), kw: new Set(), rel: new Set(), type: new Set(), country: new Set(), lang: new Set(), src: new Set(), access: new Set(), flag: new Set(), platform: new Set() },
    strict: true, looseHidden: [],
    text: '', sort: 'authority', view: 'list', selected: null, shown: 150, openStories: new Set(),
    dossier: new Map(), history: [], settings: {}, snapshot: null, stopTerms: [],
    deep: { queue: [], active: 0, total: 0, done: 0 }, density: 'compact', facetMore: new Set(),
    qtab: 'topic', qvals: {}, themes: new Set(), section: 'media', person: null, personCands: [], osint: null,
    wsName: 'main', wsStore: {}, watch: { sources: [], channels: [] }, trTitles: false, tr: new Map(), trFull: new Map(),
    catalog: null, social: null, openRows: new Set(), facetOpen: new Set(['tier', 'origin', 'kw', 'rel', 'platform'])
  };

  // ================================================================ период
  function dayStart(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
  function isoDate(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function presetRange(p) {
    const now = new Date();
    const today = dayStart(now);
    switch (p) {
      case 'today': return [today, now];
      case 'yesterday': { const y = new Date(today); y.setDate(y.getDate() - 1); const e = new Date(today.getTime() - 1000); return [y, e]; }
      case '24h': return [new Date(now.getTime() - 86400000), now];
      case '3d': { const s = new Date(today); s.setDate(s.getDate() - 2); return [s, now]; }
      case '30d': { const s = new Date(today); s.setDate(s.getDate() - 29); return [s, now]; }
      default: { const s = new Date(today); s.setDate(s.getDate() - 6); return [s, now]; }
    }
  }
  function setPreset(p) {
    if (p === 'custom') {
      S.preset = 'custom';
      $('#customDates').classList.remove('hidden');
      $$('#presets button').forEach((x) => x.classList.toggle('on', x.dataset.p === 'custom'));
      customRange();
      return;
    }
    S.preset = p;
    const [a, b] = presetRange(p);
    S.range = [a, b];
    $('#dFrom').value = isoDate(a);
    $('#dTo').value = isoDate(b);
    $('#customDates').classList.add('hidden');
    $$('#presets button').forEach((x) => x.classList.toggle('on', x.dataset.p === p));
    periodHint();
    store.set('preset', p);
  }
  function customRange() {
    const f = $('#dFrom').value, t = $('#dTo').value;
    if (!f || !t) return;
    const a = new Date(f + 'T00:00:00');
    let b = new Date(t + 'T23:59:59');
    if (b > new Date()) b = new Date();
    S.preset = 'custom';
    S.range = [a, b];
    $$('#presets button').forEach((x) => x.classList.toggle('on', x.dataset.p === 'custom'));
    periodHint();
  }
  function periodHint() {
    const [a, b] = S.range;
    const days = Math.max(1, Math.round((b - a) / 86400000));
    $('#periodHint').textContent = fmtDate(a / 1000).slice(0, 10) + ' — ' + fmtDate(b / 1000) + ' · ' + tzLabel() + ' · ' + days + ' дн.';
  }

  // ================================================================ языки и категории
  function renderLangChips() {
    const box = clear($('#langChips'));
    for (const l of S.languages) {
      const on = S.langOn.has(l.code);
      const chip = el('span', { class: 'chip' + (on ? ' on' : '') + (l.core ? '' : ' extra'), title: l.name + (l.core ? '' : ' (дополнительный)') + ' — ' + l.native, data: { code: l.code } },
        el('span', { class: 'code' }, l.code.toUpperCase()), el('span', { lang: l.code, dir: 'auto' }, l.native));
      chip.addEventListener('click', () => {
        if (S.langOn.has(l.code)) S.langOn.delete(l.code); else S.langOn.add(l.code);
        store.set('langs', [...S.langOn]);
        renderLangChips(); paramsSummary();
      });
      box.appendChild(chip);
    }
    const all = el('span', { class: 'chip', title: 'Выбрать все языки' }, 'все');
    all.addEventListener('click', () => { S.languages.forEach((l) => S.langOn.add(l.code)); store.set('langs', [...S.langOn]); renderLangChips(); });
    const core = el('span', { class: 'chip', title: '12 основных языков' }, '12 основных');
    core.addEventListener('click', () => { S.langOn = new Set(S.languages.filter((l) => l.core).map((l) => l.code)); store.set('langs', [...S.langOn]); renderLangChips(); });
    box.append(all, core);
  }

  function renderTypesMenu() {
    const m = clear($('#menuTypes'));
    m.appendChild(el('div', { class: 'mh' }, 'Опрашивать категории источников'));
    for (const [k, v] of Object.entries(C.TYPE_LABELS)) {
      if (k === 'unknown' || k === 'social') continue;
      const cb = el('input', { type: 'checkbox' });
      cb.checked = !S.types.size || S.types.has(k);
      cb.addEventListener('change', () => {
        const all = Object.keys(C.TYPE_LABELS).filter((t) => t !== 'unknown' && t !== 'social');
        if (!S.types.size) all.forEach((t) => S.types.add(t));
        if (cb.checked) S.types.add(k); else S.types.delete(k);
        if (S.types.size === all.length) S.types.clear();
        store.set('types', [...S.types]);
        updateTypesBtn();
      });
      m.appendChild(el('label', null, cb, v));
    }
    m.appendChild(el('hr'));
    m.appendChild(el('div', { class: 'muted', style: 'font-size:11.5px;padding:0 8px 4px' }, 'Влияет на опрос лент и сайтов источников. Поисковые системы опрашиваются всегда.'));
  }
  function updateTypesBtn() {
    $('#btnTypes').textContent = 'Категории: ' + (S.types.size ? S.types.size + ' из 11' : 'все') + ' ▾';
    if ($('#btnParams')) paramsSummary();
  }
  function renderProvMenu() {
    const m = clear($('#menuProv'));
    const provs = (S.boot && S.boot.providers) || [];
    const keys = (S.social && S.social.keys) || {};
    const need = { vk: !keys.vk, x: !keys.x, websocial: !(keys.brave || keys.gcse), youtube: !keys.youtube };
    for (const [g, gl] of [['media', 'СМИ, аналитика, организации'], ['social', 'Соцсети — отдельная выдача']]) {
      const list = provs.filter((p) => (p.group || 'media') === g);
      if (!list.length) continue;
      m.appendChild(el('div', { class: 'mh' }, gl));
      for (const p of list) {
        const cb = el('input', { type: 'checkbox' });
        cb.checked = S.providers.has(p.id);
        cb.addEventListener('change', () => {
          if (cb.checked) S.providers.add(p.id); else S.providers.delete(p.id);
          store.set('providers', [...S.providers]);
        });
        m.appendChild(el('label', null, cb, p.label, need[p.id] ? el('span', { class: 'muted', style: 'font-size:11px' }, ' — ключ не задан') : null));
      }
    }
    if (!provs.length) m.appendChild(el('div', { class: 'muted', style: 'padding:6px 8px' }, 'Автономный режим: GDELT и OpenAlex'));
    else m.appendChild(el('div', { class: 'muted', style: 'font-size:11.5px;padding:4px 8px' }, 'Ключи соцсетей — в «Настройки → Соцсети и ключи API».'));
  }
  function toggleMenu(btn, menu) {
    const open = menu.classList.contains('hidden');
    $$('.menu').forEach((x) => x.classList.add('hidden'));
    if (open) menu.classList.remove('hidden');
  }
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.dropdown')) $$('.menu').forEach((x) => x.classList.add('hidden'));
  });

  // ================================================================ расширение запроса и термины
  function themeLabels() {
    const all = (S.boot && S.boot.themes) || (D.lexicon || []).filter((e) => e.kind === 'theme').map((e) => ({ id: e.id, label: e.label }));
    return all.filter((t) => S.themes.has(t.id)).map((t) => t.label);
  }
  function queryParts() {
    const v = $('#qTopic').value;
    if (S.qtab === 'keywords') {
      const exact = $('#optExact').checked;
      return { topics: exact ? [v.trim()].filter(Boolean) : splitList(v), context: splitList($('#qCtx').value), exclude: splitList($('#qNot').value),
        related: false, translate: $('#optTranslate').checked };
    }
    if (S.qtab === 'person') {
      const p = S.person;
      return { topics: p ? [p.label] : splitList(v).slice(0, 1), context: [], exclude: [], related: false, persons: p ? { [p.label]: p.id } : {} };
    }
    if (S.qtab === 'reports') return { topics: splitList(v), context: [], exclude: [], related: false };
    return { topics: splitList(v), context: themeLabels(), exclude: [], related: $('#optRelated').checked };
  }
  async function expand(force) {
    const q = queryParts();
    const langs = [...S.langOn];
    const related = q.related;
    const key = JSON.stringify([q, langs.slice().sort()]);
    if (!force && S.expansion && S.expKey === key) return S.expansion;
    let exp;
    if (SERVER) exp = await api('/api/expand', { method: 'POST', body: Object.assign({ langs }, q) });
    else exp = localExpand(q, langs, related);
    S.expansion = exp;
    S.expKey = key;
    renderTerms();
    return exp;
  }

  function localExpand(q, langs, related) {
    const byNorm = new Map();
    for (const e of D.lexicon || []) {
      const keys = [e.label].concat(e.aliases || []);
      if (e.kind !== 'theme') Object.values(e.terms || {}).forEach((t) => keys.push(...t));
      keys.forEach((k) => { if (!byNorm.has(C.normText(k))) byNorm.set(C.normText(k), e); });
    }
    const byId = new Map((D.lexicon || []).map((e) => [e.id, e]));
    const one = (t, rel) => {
      const e = byNorm.get(C.normText(t));
      const out = { topic: t, entity: e ? { id: e.id, label: e.label, source: 'словарь ОКО' } : null, langs: {} };
      for (const code of langs.concat(langs.includes('zh') ? ['zh-Hant'] : [])) {
        if (e && e.terms[code]) {
          let qq = e.terms[code].slice(), mm = ((e.match && e.match[code]) || []).slice();
          const relMap = {};
          if (rel) for (const rid of e.related || []) {
            const r = byId.get(rid);
            if (r && r.terms[code]) { qq.push(r.terms[code][0]); relMap[r.terms[code][0]] = r.label; for (const x of (r.match && r.match[code]) || []) { mm.push(x); relMap[x] = r.label; } }
          }
          if (rel) for (const x of (e.extra_match && e.extra_match[code]) || []) { mm.push(x); if (!(x in relMap)) relMap[x] = ''; }
          out.langs[code] = { q: qq, m: mm, src: 'lexicon', note: 'словарь ОКО', rel: relMap };
        } else out.langs[code] = { q: [t], m: [], src: 'original', note: 'нет перевода (автономный режим)' };
      }
      return out;
    };
    const topics = q.topics.map((t) => one(t, related));
    const context = q.context.map((t) => one(t, false));
    const exclude = q.exclude.map((t) => one(t, false));
    const plan = {};
    for (const code of langs.concat(langs.includes('zh') ? ['zh-Hant'] : [])) {
      const col = (arr, k) => arr.flatMap((x) => ((x.langs[code] || x.langs.zh || {})[k] || []));
      plan[code] = { q: [...new Set(col(topics, 'q'))], m: [...new Set(col(topics, 'm'))], ctx: [...new Set(col(context, 'q'))], ctx_m: [], not: [...new Set(col(exclude, 'q'))] };
    }
    return { topics, context, exclude, plan, origins: termOrigins(topics, context) };
  }
  // происхождение терминов: ключевое слово → перевод / словоформа / связанный термин / контекст (как plan_origins на сервере)
  function termOrigins(topics, context) {
    const out = {};
    const put = (term, kw, role, code, src, of) => {
      const k = C.normText(term);
      if (!k) return;
      const cur = out[k];
      if (!cur) out[k] = { t: term, kw, role, of: of || '', langs: [code], src: src || '' };
      else if (cur.kw === kw && cur.role === role && !cur.langs.includes(code)) cur.langs.push(code);
    };
    const each = (list, fn) => { for (const e of list || []) for (const [code, t] of Object.entries(e.langs || {})) fn(e, code, t, t.rel || {}); };
    each(topics, (e, code, t, rel) => (t.q || []).forEach((x) => { if (!(x in rel)) put(x, e.topic, 'main', code, t.src); }));
    each(topics, (e, code, t, rel) => (t.q || []).concat(t.m || []).forEach((x) => { if (x in rel) put(x, e.topic, 'related', code, t.src, rel[x]); }));
    each(topics, (e, code, t, rel) => (t.m || []).forEach((x) => { if (!(x in rel)) put(x, e.topic, 'form', code, t.src); }));
    each(context, (e, code, t) => (t.q || []).concat(t.m || []).forEach((x) => put(x, e.topic, 'ctx', code, t.src)));
    return out;
  }

  function renderTerms() {
    const exp = S.expansion;
    const tbl = clear($('#termsTable'));
    if (!exp) return;
    const ent = exp.topics.map((t) => t.entity ? (t.entity.label + (t.entity.id && t.entity.source === 'Wikidata' ? ' · Wikidata ' + t.entity.id : ' · ' + t.entity.source) + (t.entity.description ? ' — ' + t.entity.description : '')) : null).filter(Boolean);
    $('#entityInfo').textContent = ent.length ? 'Распознано: ' + ent.join('; ') : '';
    tbl.appendChild(el('tr', null, el('th', null, 'Язык'), el('th', null, 'Термины темы (ИЛИ)'), el('th', null, 'Контекст (И)'), el('th', null, 'Исключить'), el('th', null, 'Источник')));
    const codes = Object.keys(exp.plan);
    const single = exp.topics.length === 1 ? exp.topics[0] : null;
    for (const code of codes) {
      const p = exp.plan[code];
      const info = single ? (single.langs[code] || {}) : {};
      const rtl = RTL.has(code);
      tbl.appendChild(el('tr', null,
        el('td', { class: 'lang' }, el('span', { class: 'mono' }, code.toUpperCase()), ' ', langName(code)),
        el('td', null, termEditor(p, 'q', code, rtl, single)),
        el('td', null, termEditor(p, 'ctx', code, rtl, null)),
        el('td', null, termEditor(p, 'not', code, rtl, null)),
        el('td', null, info.src ? el('span', { class: 'srcTag ' + info.src, title: info.note || '' }, { lexicon: 'словарь', wikidata: 'Wikidata', mt: 'перевод', user: 'вручную', original: 'без перевода' }[info.src] || info.src) : '')));
    }
  }
  function termEditor(p, key, code, rtl, single) {
    const box = el('div', { class: 'tchips' });
    const list = p[key] || (p[key] = []);
    const orig = (S.expansion && S.expansion.origins) || {};
    list.forEach((t, i) => {
      const rm = el('button', { title: 'Удалить' }, '×');
      rm.addEventListener('click', () => { list.splice(i, 1); saveGlossary(single, code, key, list); renderTerms(); });
      const o = orig[C.normText(t)];
      const rel = o && o.role === 'related';
      box.appendChild(el('span', { class: 'tchip' + (rel ? ' rel' : ''), lang: code === 'zh-Hant' ? 'zh-Hant' : code, dir: rtl ? 'rtl' : 'auto',
        title: o ? (rel ? 'Связанный термин' + (o.of ? ' (' + o.of + ')' : '') + ' для «' + o.kw + '»' : 'Ключевое слово «' + o.kw + '»') : 'Добавлен вручную' }, t, rm));
    });
    const inp = el('input', { class: 'tadd', placeholder: '+ термин', lang: code, dir: 'auto' });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && inp.value.trim()) {
        list.push(inp.value.trim());
        saveGlossary(single, code, key, list);
        renderTerms();
      }
    });
    box.appendChild(inp);
    return box;
  }
  function saveGlossary(single, code, key, list) {
    if (!single || key !== 'q' || !SERVER) return;
    api('/api/glossary', { method: 'POST', body: { topic: single.topic, lang: code, terms: list } })
      .then(() => toast('Термин сохранён в глоссарий'))
      .catch((e) => toast('Глоссарий: ' + e.message, true));
    if (single.langs[code]) single.langs[code].src = 'user';
  }

  // ================================================================ поиск
  // ================================================================ рабочие области: «Поиск» и «Мониторинг»
  const WS_KEYS = ['items', 'meta', 'tasks', 'stats', 'notes', 'planInfo', 'started', 'done', 'params', 'snapshot', 'selected', 'shown',
    'deep', 'jobId', 'stopTerms', 'looseHidden', 'filters', 'section', 'view', 'openStories', 'openRows'];
  function freshWs(name) {
    return { items: new Map(), meta: new Map(), tasks: new Map(), stats: {}, notes: [], planInfo: [], started: 0, done: null, params: null,
      snapshot: null, selected: null, shown: 150, deep: { queue: [], active: 0, total: 0, done: 0 }, jobId: null, stopTerms: [], looseHidden: [],
      filters: { tier: new Set(), origin: new Set(), kw: new Set(), rel: new Set(), type: new Set(), country: new Set(), lang: new Set(), src: new Set(), access: new Set(), flag: new Set(), platform: new Set() },
      section: 'media', view: name === 'watch' ? 'sources' : store.get('view', 'list'), openStories: new Set(), openRows: new Set() };
  }
  function switchWs(name) {
    if (S.wsName === name) return;
    const cur = {};
    for (const k of WS_KEYS) cur[k] = S[k];
    S.wsStore[S.wsName] = cur;
    const next = S.wsStore[name] || freshWs(name);
    for (const k of WS_KEYS) S[k] = next[k];
    S.wsName = name;
  }
  // объект состояния области: активная — сам S, фоновая — сохранённая копия
  function wsObj(name) { return name === S.wsName ? S : (S.wsStore[name] || (S.wsStore[name] = freshWs(name))); }

  function searchMode() { return S.qtab === 'reports' ? 'reports' : (S.qtab === 'person' ? 'person' : 'topic'); }

  async function runSearch() {
    if (S.running) { toast('Дождитесь завершения текущего поиска', true); return; }
    if (S.qtab === 'osint') return osintRun();
    if (S.qtab === 'person' && !S.person) return personSearch();
    const mode = searchMode();
    const q = queryParts();
    if (mode !== 'reports' && !q.topics.length) { toast('Введите тему поиска', true); $('#qTopic').focus(); return; }
    if (!S.langOn.size) { toast('Выберите хотя бы один язык', true); return; }
    if (S.preset !== 'custom') setPreset(S.preset);
    const [a, b] = S.range;
    if (b <= a) { toast('Конец периода раньше начала', true); return; }
    showView('results');
    const T = S;
    S.running = true;
    setRunningUI(true);
    S.items.clear(); S.meta.clear(); S.tasks.clear(); S.notes = []; S.stats = {}; S.selected = null; S.snapshot = null;
    S.done = null; S.shown = 150; S.deep = { queue: [], active: 0, total: 0, done: 0 }; S.openRows = new Set();
    renderBanner();
    renderDetail(null);
    renderProgress(mode === 'reports' ? 'Готовлю запросы по каталогу докладов…' : 'Подготовка терминов на ' + S.langOn.size + ' языках…');
    render();
    try {
      const exp = q.topics.length ? await expand(false) : { plan: {}, topics: [], context: [], origins: {} };
      T.stopTerms = collectStopTerms(exp.plan);
      const untranslated = untranslatedLangs(exp).filter(() => q.translate !== false);
      if (untranslated.length) {
        const msg = 'Перевод не получен для: ' + untranslated.join(', ') + ' — используется исходное написание. Проверьте «Термины».';
        T.notes.push(msg);
        toast(msg, true);
      }
      const title = mode === 'reports' ? 'Доклады' + (q.topics.length ? ': ' + q.topics.join(', ') : '') :
        (mode === 'person' ? 'Персона: ' + q.topics.join(', ') : '');
      const params = {
        mode, title, topics: q.topics, context: q.context, exclude: q.exclude, langs: [...S.langOn], plan: exp.plan,
        origins: exp.origins || termOrigins(exp.topics, exp.context),
        t_from: Math.floor(a.getTime() / 1000), t_to: Math.floor(b.getTime() / 1000), tz_offset: -new Date().getTimezoneOffset(),
        providers: [...S.providers], types: [...S.types], report_topic: mode === 'reports' && !!($('#optReportTopic') || {}).checked,
        person: mode === 'person' && S.person ? { id: S.person.id, label: S.person.label } : undefined
      };
      T.params = params;
      loadSocial(q.topics.join(' '));
      if (mode === 'topic') addHistory(params);
      T.started = Date.now();
      if (SERVER) await streamSearch(params, 'main');
      else await autonomousSearch(params);
    } catch (e) {
      if (e.name !== 'AbortError') toast('Ошибка поиска: ' + e.message, true);
    } finally {
      S.running = false;
      setRunningUI(false);
      if (S.wsName === 'main') { recompute(true); renderProgress(); if (S.items.size && SERVER) startAutoCheck(); }
    }
  }
  function untranslatedLangs(exp) {
    const out = new Set();
    for (const part of [exp.topics || [], exp.context || [], exp.exclude || []]) {
      for (const t of part) {
        const src = /[\u0400-\u04ff]/.test(t.topic) ? 'ru' : null;
        for (const [code, v] of Object.entries(t.langs || {})) {
          if (v.src === 'original' && code !== src && code !== 'zh-Hant') out.add(code.toUpperCase());
        }
      }
    }
    return [...out];
  }
  function collectStopTerms(plan) {
    const out = new Set();
    for (const p of Object.values(plan || {})) for (const t of [...(p.q || []), ...(p.m || [])]) {
      const n = C.normText(t);
      if (n && !n.includes(' ')) out.add(n.length > 6 ? n.slice(0, 6) : n);
    }
    return [...out];
  }
  function setRunningUI(on) {
    $('#btnSearch').disabled = on;
    $('#btnSearch').textContent = on ? 'ПОИСК…' : (S.qtab === 'osint' ? 'ПРОВЕРИТЬ' : 'НАЙТИ');
    $('#btnWatchRun').disabled = on;
    $('#btnWatchRun').textContent = on ? 'ОПРОС…' : 'ОБНОВИТЬ';
    $('#btnStop').classList.toggle('hidden', !on);
  }
  async function stopSearch() {
    if (S.jobId && SERVER) { try { await api('/api/search/stop', { method: 'POST', body: { job: S.jobId } }); } catch (e) { /* ignore */ } }
    if (S.abortLocal) S.abortLocal.abort();
    toast('Поиск останавливается — уже найденные материалы сохранятся');
  }

  async function streamSearch(params, wsName) {
    const ctrl = new AbortController();
    S.abort = ctrl;
    const target = wsName || S.wsName;
    const r = await fetch('/api/search', { method: 'POST', headers: { 'X-OKO-Token': TOKEN, 'Content-Type': 'application/json' }, body: JSON.stringify(params), signal: ctrl.signal });
    if (!r.ok) { let m = 'HTTP ' + r.status; try { m = (await r.json()).error || m; } catch (e) { /* */ } throw new Error(m); }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        let ev = 'message', data = '';
        for (const line of chunk.split('\n')) {
          if (line.startsWith('event:')) ev = line.slice(6).trim();
          else if (line.startsWith('data:')) data += line.slice(5).trim();
        }
        if (data) { try { onEvent(ev, JSON.parse(data), target); } catch (e) { console.error(e); } }
      }
    }
  }

  const scheduleRender = debounce(() => { recompute(false); renderProgress(); }, 450);
  function onEvent(ev, d, wsName) {
    const T = wsObj(wsName || S.wsName);
    const active = T === S;
    if (ev === 'plan') {
      T.jobId = d.job;
      S.jobId = d.job;
      T.planInfo = d.providers || [];
      for (const t of d.tasks || []) T.tasks.set(t.key, t);
      T.notes = [...new Set(T.notes.concat(d.notes || []))];
      if (active) renderProgress();
    } else if (ev === 'task') {
      T.tasks.set(d.key, d);
      if (active) scheduleRender();
    } else if (ev === 'items') {
      for (const it of d) mergeItem(it, T);
      if (active) scheduleRender();
    } else if (ev === 'done') {
      T.done = d;
      T.stats = d;
      if (d.notes) T.notes = [...new Set(T.notes.concat(d.notes))];
    } else if (ev === 'error') {
      toast(d.message || 'Ошибка', true);
      T.notes.push(d.message);
    }
  }
  function mergeItem(it, T) {
    T = T || S;
    const old = T.items.get(it.id);
    if (old) {
      for (const k of ['_checking', 'resolved']) if (old[k] !== undefined) it[k] = old[k];
      if (old.authors && old.authors.length && !(it.authors && it.authors.length)) it.authors = old.authors;
    }
    T.items.set(it.id, it);
  }

  // ================================================================ автономный режим (файл открыт без сервера)
  const GDELT_LANG = { english: 'en', russian: 'ru', french: 'fr', german: 'de', spanish: 'es', italian: 'it', korean: 'ko', japanese: 'ja', chinese: 'zh', persian: 'fa', arabic: 'ar', urdu: 'ur', turkish: 'tr', hebrew: 'he', hindi: 'hi', kazakh: 'kk', portuguese: 'pt' };
  async function autonomousSearch(params) {
    const ctrl = new AbortController();
    S.abortLocal = ctrl;
    const en = params.plan.en || { q: [] };
    const tasks = [];
    const gd = (s) => { const d = new Date(s * 1000); return d.getUTCFullYear() + pad(d.getUTCMonth() + 1) + pad(d.getUTCDate()) + pad(d.getUTCHours()) + pad(d.getUTCMinutes()) + '00'; };
    if (en.q.length && params.t_to > Date.now() / 1000 - 89 * 86400) {
      const langs = [null].concat(params.langs.filter((c) => c !== 'en'));
      for (const code of langs) {
        const L = S.languages.find((l) => l.code === code);
        if (code && (!L || !L.gdelt)) continue;
        tasks.push({ key: 'gdelt:' + (code || 'all'), provider: 'gdelt', label: 'GDELT · ' + (code ? langName(code) : 'все языки'), status: 'wait', code, gdelt: L && L.gdelt });
      }
    }
    if (en.q.length) tasks.push({ key: 'openalex', provider: 'openalex', label: 'OpenAlex · научные публикации', status: 'wait' });
    tasks.forEach((t) => S.tasks.set(t.key, t));
    renderProgress();
    const matcher = new C.TermMatcher(Object.values(params.plan).flatMap((p) => p.q.concat(p.m || [])));
    const add = (it, t) => {
      if (!it.ts || it.ts < params.t_from || it.ts > params.t_to) return;
      const hit = matcher.find(it.title);
      it.hit = hit ? 'title' : 'engine';
      it.term = hit || '';
      const o = hit ? (params.origins || {})[hit] : null;
      if (o) Object.assign(it, { kw: o.kw, role: o.role, of: o.of || '', tl: o.langs || [] });
      else if (params.topics.length === 1) Object.assign(it, { kw: params.topics[0], role: 'engine' });
      if (t) it.q = [{ t: t.label, q: t.query || '' }];
      mergeItem(it);
    };
    for (const t of tasks) {
      if (ctrl.signal.aborted) break;
      t.status = 'run'; renderProgress();
      const t0 = Date.now();
      try {
        if (t.provider === 'gdelt') {
          const terms = en.q.slice(0, 4).map((x) => (/\s/.test(x) ? '"' + x + '"' : x));
          let q = terms.length > 1 ? '(' + terms.join(' OR ') + ')' : terms[0];
          if (t.gdelt) q += ' sourcelang:' + t.gdelt;
          t.query = q;
          const url = 'https://api.gdeltproject.org/api/v2/doc/doc?' + new URLSearchParams({ query: q, mode: 'artlist', format: 'json', maxrecords: '250', sort: 'datedesc', startdatetime: gd(Math.max(params.t_from, Date.now() / 1000 - 89 * 86400)), enddatetime: gd(params.t_to) });
          const r = await fetch(url, { signal: ctrl.signal });
          const txt = await r.text();
          const arts = txt.trim().startsWith('{') ? (JSON.parse(txt).articles || []) : [];
          for (const a of arts) {
            const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(a.seendate || '');
            const ts = m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) / 1000 : null;
            add({ id: 'u' + hash(a.url), url: a.url, title: a.title || '', snippet: '', ts, lang: GDELT_LANG[(a.language || '').toLowerCase()] || t.code, src_name: a.domain, src_url: '', domain: (a.domain || '').replace(/^www\./, ''), prov: ['gdelt'], via: ['GDELT'], authors: [], related: [], extra: {}, kind: 'news' }, t);
          }
          t.n = arts.length;
          await new Promise((res) => setTimeout(res, 5300));
        } else {
          const f = new Date(params.t_from * 1000).toISOString().slice(0, 10), to = new Date(params.t_to * 1000).toISOString().slice(0, 10);
          t.query = '(' + en.q.slice(0, 3).join(' OR ') + ')';
          const url = 'https://api.openalex.org/works?' + new URLSearchParams({ search: t.query, 'per-page': '50', sort: 'publication_date:desc', filter: 'from_publication_date:' + f + ',to_publication_date:' + to });
          const data = await (await fetch(url, { signal: ctrl.signal })).json();
          for (const w of data.results || []) {
            const loc = w.primary_location || {};
            const src = loc.source || {};
            const u = loc.landing_page_url || w.doi || w.id;
            add({ id: 'u' + hash(u), url: u, title: w.display_name || '', snippet: w.type || '', ts: w.publication_date ? Date.parse(w.publication_date + 'T12:00:00Z') / 1000 : null, lang: w.language || 'en', src_name: src.display_name || '', domain: C.hostOf(u), prov: ['openalex'], via: ['OpenAlex'], authors: (w.authorships || []).map((x) => (x.author || {}).display_name).filter(Boolean), related: [], extra: { publisher: src.host_organization_name || '' }, kind: 'paper', pdf: (w.open_access || {}).oa_url || '' }, t);
          }
          t.n = (data.results || []).length;
        }
        t.status = 'ok';
      } catch (e) {
        t.status = 'error';
        t.err = e.name === 'AbortError' ? 'остановлено' : 'недоступно из браузера (' + e.message + ')';
      }
      t.ms = Date.now() - t0;
      recompute(false); renderProgress();
    }
    S.done = { unique: S.items.size, took: (Date.now() - S.started) / 1000, notes: ['Автономный режим: использованы только GDELT и OpenAlex'] };
    S.notes = S.done.notes;
  }
  function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(16); }

  // ================================================================ пересчёт: классификация, сюжеты, фильтры
  let visible = [];
  let facetCounts = {};
  function recompute(full) {
    const arr = [...S.items.values()];
    for (const it of arr) { it.meta = S.meta.get(it.id) || null; C.classify(it, S.registry); }
    C.cluster(arr, S.stopTerms);
    const [a, b] = S.params ? [S.params.t_from, S.params.t_to] : [0, 0];
    for (const it of arr) {
      C.classify(it, S.registry);
      it.rel = C.relevance(it, it.meta && it.meta.mentions ? it.meta.mentions : undefined);
      it.score = C.score(it, a, b);
      it.starred = S.dossier.has(it.id);
    }
    applyFilters();
    render();
    if (S.selected && S.items.has(S.selected) && full !== 'skip-detail') renderDetail(S.items.get(S.selected), true);
  }

  function isSocial(it) { return it.kind === 'social'; }
  function baseOk(it) {
    if (isSocial(it) !== (S.section === 'social')) return false;
    if (!isSocial(it) && S.mode === 'registry' && S.wsName !== 'watch' && !(it.inRegistry || it.type === 'official' || it.type === 'intl_org' || it.type === 'academic')) return false;
    if (!isSocial(it) && (it.tier || 4) > S.minTier) return false;
    if (S.text) {
      const hay = C.normText(it.title + ' ' + (it.srcName || '') + ' ' + (it.snippet || '') + ' ' + (it.domain || ''));
      if (!hay.includes(C.normText(S.text))) return false;
    }
    return true;
  }
  const DIM = {
    tier: (it) => String(it.tier || 4),
    origin: (it) => (it.origin ? it.origin.status : 'unknown'),
    type: (it) => it.type || 'unknown',
    country: (it) => it.country || '—',
    lang: (it) => (it.lang || '—').slice(0, 2),
    src: (it) => it.srcName || it.domain || '—',
    access: (it) => (it.paywall ? 'paid' : 'free'),
    rel: (it) => it.rel || 'unverified',
    kw: kwKey,
    platform: (it) => (it.extra && it.extra.platform) || '—'
  };
  function flagsOf(it) {
    const f = [];
    if (it.new) f.push('new');
    if (it.bm) f.push('bm');
    if (it.ca) f.push('ca');
    if (it.state === 'control') f.push('state');
    if (it.starred) f.push('star');
    return f;
  }
  function hasTopic() {
    const p = S.params;
    if (!p || p.mode === 'reports') return false;
    return Object.values(p.plan || {}).some((x) => (x.q || []).length);
  }
  function updateSectionCounts() {
    let m = 0, so = 0;
    for (const it of S.items.values()) { if (isSocial(it)) so++; else m++; }
    const a = $('#cntMedia'), b = $('#cntSocial');
    if (a) a.textContent = String(m);
    if (b) b.textContent = String(so);
  }
  function setSection(sec) {
    S.section = sec;
    $$('#sectSeg button').forEach((x) => x.classList.toggle('on', x.dataset.s === sec));
    S.shown = 150;
    applyFilters(); render();
  }
  function applyFilters() {
    const F = S.filters;
    const loose = [...S.items.values()].filter(baseOk);
    const strict = S.strict && hasTopic();
    const base = strict ? loose.filter((it) => C.REL_STRICT.has(it.rel)) : loose;
    S.looseHidden = strict ? loose.filter((it) => !C.REL_STRICT.has(it.rel)) : [];
    updateSectionCounts();
    const sc = $('.check.strict');
    if (sc) sc.classList.toggle('hidden', !hasTopic());
    facetCounts = {};
    for (const dim of Object.keys(DIM)) facetCounts[dim] = new Map();
    facetCounts.flag = new Map();
    const passDim = (it, skip) => {
      for (const [dim, fn] of Object.entries(DIM)) {
        if (dim === skip) continue;
        const sel = F[dim];
        if (sel.size && !sel.has(fn(it))) return false;
      }
      if (skip !== 'flag' && F.flag.size) {
        const fl = flagsOf(it);
        for (const x of F.flag) {
          if (x === 'nostate') { if (fl.includes('state')) return false; } else if (!fl.includes(x)) return false;
        }
      }
      return true;
    };
    for (const it of base) {
      for (const [dim, fn] of Object.entries(DIM)) {
        if (!passDim(it, dim)) continue;
        const k = fn(it);
        facetCounts[dim].set(k, (facetCounts[dim].get(k) || 0) + 1);
      }
      if (passDim(it, 'flag')) for (const x of flagsOf(it)) facetCounts.flag.set(x, (facetCounts.flag.get(x) || 0) + 1);
    }
    visible = base.filter((it) => passDim(it, null));
    C.sortItems(visible, S.sort);
  }

  // ================================================================ отрисовка ленты
  function render() {
    renderFacets();
    renderList();
    renderCount();
    if (S.trTitles) translateVisibleTitles();
  }
  function renderCount() {
    const total = S.items.size;
    const prim = visible.filter((x) => x.origin && x.origin.status === 'primary').length;
    const rep = visible.filter((x) => x.origin && x.origin.status === 'reprint').length;
    const box = clear($('#rcount'));
    box.title = 'Показано ' + visible.length + ' из ' + total + ' · первоисточников: ' + prim + ' · перепубликаций: ' + rep;
    box.append(el('b', null, String(visible.length)), ' из ', el('b', null, String(total)),
      el('span', { class: 'sep' }, '·'), el('span', { style: 'color:var(--ok)' }, '✔ ' + prim),
      el('span', { class: 'sep' }, '·'), el('span', { style: 'color:var(--warn)' }, '⟳ ' + rep));
  }

  function facetSection(title, dim, entries, labeler, limit) {
    const sec = el('details', { class: 'fsec' });
    if (S.facetOpen.has(dim) || (S.filters[dim] && S.filters[dim].size)) sec.open = true;
    sec.addEventListener('toggle', () => { if (sec.open) S.facetOpen.add(dim); else S.facetOpen.delete(dim); store.set('facetOpen', [...S.facetOpen]); });
    const reset = el('button', { title: 'Сбросить' }, S.filters[dim] && S.filters[dim].size ? 'сброс' : '');
    reset.addEventListener('click', (e) => { e.preventDefault(); S.filters[dim].clear(); applyFilters(); render(); });
    const sel = S.filters[dim] && S.filters[dim].size ? el('span', { class: 'fsel' }, String(S.filters[dim].size)) : null;
    sec.appendChild(el('summary', null, el('h4', null, title, sel, reset)));
    const max = Math.max(1, ...entries.map((e) => e[1]));
    const showAll = S.facetMore.has(dim);
    const list = limit && !showAll ? entries.slice(0, limit) : entries;
    for (const [k, n] of list) {
      const cb = el('input', { type: 'checkbox' });
      cb.checked = S.filters[dim].has(k);
      cb.addEventListener('change', () => {
        if (cb.checked) S.filters[dim].add(k); else S.filters[dim].delete(k);
        S.shown = 150;
        applyFilters(); render();
      });
      const lab = labeler(k);
      sec.appendChild(el('label', { class: 'frow', title: typeof lab === 'string' ? lab : '' }, cb, el('span', { class: 'fl' }, lab),
        el('span', { class: 'fbar' }, el('i', { style: 'width:' + Math.round((n / max) * 100) + '%' })), el('span', { class: 'fc' }, String(n))));
    }
    if (limit && entries.length > limit) {
      const mb = el('button', { class: 'fmore' }, showAll ? 'свернуть' : 'ещё ' + (entries.length - limit));
      mb.addEventListener('click', () => { if (showAll) S.facetMore.delete(dim); else S.facetMore.add(dim); renderFacets(); });
      sec.appendChild(mb);
    }
    return sec;
  }
  function sortedEntries(map, order) {
    const arr = [...map.entries()];
    if (order) return arr.sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
    return arr.sort((a, b) => b[1] - a[1]);
  }
  function renderFacets() {
    const box = clear($('#facets'));
    if (!S.items.size) {
      box.appendChild(el('div', { class: 'fsec' }, el('h4', null, 'Фильтры'), el('div', { class: 'muted', style: 'font-size:12.5px' }, 'Появятся после поиска.')));
      return;
    }
    const closeBtn = el('button', { class: 'btn small mob-only', style: 'margin:0 14px 8px' }, 'Закрыть');
    closeBtn.addEventListener('click', () => $('#facets').classList.add('closed'));
    box.appendChild(closeBtn);
    if (S.section === 'social') {
      box.appendChild(facetSection('Платформа', 'platform', sortedEntries(facetCounts.platform), (k) => ((S.social && S.social.platforms && S.social.platforms[k]) || {}).name || k));
    }
    box.appendChild(facetSection('Уровень', 'tier', sortedEntries(facetCounts.tier, ['1', '2', '3', '4']), (k) => {
      const t = C.TIERS[k];
      return el('span', null, el('span', { class: 'tier t' + k, style: 'width:18px;height:16px;font-size:10px;margin-right:6px' }, t.code), t.label.split('—')[1].trim());
    }));
    box.appendChild(facetSection('Статус информации', 'origin', sortedEntries(facetCounts.origin, ['primary', 'reprint', 'unknown']), (k) => ({ primary: '✔ Первоисточник', reprint: '⟳ Перепубликация', unknown: '? Не определено' }[k])));
    const topic = hasTopic();
    if (topic && (facetCounts.kw.size > 1 || S.filters.kw.size)) box.appendChild(facetSection('Найдено по ключевому слову', 'kw', sortedEntries(facetCounts.kw), kwLabel, 10));
    box.appendChild(facetSection('Тип источника', 'type', sortedEntries(facetCounts.type), (k) => C.TYPE_LABELS[k] || k));
    box.appendChild(facetSection('Страна издания', 'country', sortedEntries(facetCounts.country), (k) => (k === '—' ? 'не определена' : countryName(k) + ' (' + k + ')'), 12));
    box.appendChild(facetSection('Язык', 'lang', sortedEntries(facetCounts.lang), (k) => (k === '—' ? 'не определён' : langName(k)), 10));
    box.appendChild(facetSection('Издание', 'src', sortedEntries(facetCounts.src), (k) => k, 12));
    box.appendChild(facetSection('Доступ', 'access', sortedEntries(facetCounts.access, ['free', 'paid']), (k) => (k === 'paid' ? 'Платный / частично' : 'Свободный')));
    if (topic) box.appendChild(facetSection('Соответствие теме', 'rel', sortedEntries(facetCounts.rel, ['title', 'rtitle', 'text', 'rtext', 'body', 'passing', 'unverified', 'absent']), (k) => C.REL_LABELS[k] || k));
    const fl = new Map(facetCounts.flag);
    fl.set('nostate', facetCounts.flag.get('state') || 0);
    box.appendChild(facetSection('Отметки', 'flag', [...fl.entries()].filter(([k]) => ['new', 'bm', 'ca', 'star', 'nostate'].includes(k)), (k) => ({
      new: 'Новое с прошлой проверки', bm: 'Из ваших закладок', ca: 'Профиль — Центральная Азия', star: 'В досье', nostate: 'Скрыть гос. СМИ'
    }[k])));
  }

  function originBadge(o, small) {
    const st = o ? o.status : 'unknown';
    const b = el('span', { class: 'orig ' + st + (o && o.confidence === 'low' ? ' low' : ''), title: ORIGIN_LABEL[st] + (o ? ' — ' + o.reason : '') });
    if (st === 'primary') b.appendChild(icon('check'));
    else if (st === 'reprint') b.appendChild(icon('repeat'));
    else b.textContent = '?';
    if (small) b.style.cssText = 'width:18px;height:18px;font-size:11px';
    return b;
  }
  function tierBadge(t) {
    const T = C.TIERS[t] || C.TIERS[4];
    return el('span', { class: 'tier t' + (t || 4), title: 'Уровень авторитетности: ' + T.label + '. ' + T.desc }, T.code);
  }

  // ================================================================ «найдено по»: ключевое слово, термин, запрос
  const ROLE_RU = { main: 'ключевое слово', form: 'словоформа ключевого слова', related: 'связанный термин', ctx: 'контекст', manual: 'термин, добавленный вручную', engine: 'запрос к поисковой системе' };
  const TSRC_RU = { lexicon: 'словарь ОКО', wikidata: 'Wikidata', mt: 'машинный перевод', user: 'ваш глоссарий', original: 'исходное написание' };
  const HIT_RU = { title: 'в заголовке', text: 'в аннотации', engine: 'в тексте статьи (по данным поисковой системы)' };
  function explain(it) {
    const o = it.term ? (((S.params && S.params.origins) || {})[it.term] || null) : null;
    const tp = (S.params && S.params.topics) || [];
    return {
      kw: it.kw || (o && o.kw) || (tp.length === 1 ? tp[0] : ''),
      role: it.role || (o && o.role) || (it.hit === 'engine' ? 'engine' : (it.term ? 'main' : '')),
      of: it.of || (o && o.of) || '',
      langs: (it.tl && it.tl.length ? it.tl : (o && o.langs)) || [],
      src: (o && o.src) || '',
      base: (o && o.t) || ''
    };
  }
  // найти сработавший термин в исходном тексте (с учётом регистра, диакритики, «ё»/«й») → [начало, конец слова]
  function locate(text, term) {
    if (!text || !term) return null;
    const chars = Array.from(text);
    const fold = chars.map((c) => { const n = C.normText(c); return n.length === c.length ? n : c; });
    const hay = fold.join('');
    if (hay.length !== text.length) return null;
    const cjk = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(term[0]);
    let i = -1, from = 0;
    for (;;) {
      i = hay.indexOf(term, from);
      if (i < 0) return null;
      if (cjk || i === 0 || !/[\p{L}\p{M}\p{N}']/u.test(hay[i - 1]) || /^[\u0600-\u06ff\u0590-\u05ff]/.test(term)) break;
      from = i + 1;
    }
    let j = i + term.length;
    if (!cjk) while (j < text.length && /[\p{L}\p{M}\p{N}'’]/u.test(text[j])) j++;
    const poss = /['’]s?$/i.exec(text.slice(i, j));
    if (poss && j - poss[0].length > i + term.length - 1) j -= poss[0].length;
    return [i, j];
  }
  function marked(text, term, attrs, tag) {
    const pos = locate(text, term);
    const node = el(tag || 'span', attrs || null);
    if (!pos) { node.textContent = text; return node; }
    node.append(text.slice(0, pos[0]), el('mark', { class: 'hl' }, text.slice(pos[0], pos[1])), text.slice(pos[1]));
    return node;
  }
  function termShown(it) {
    for (const t of [it.title, it.snippet]) { const p = locate(t || '', it.term); if (p) return t.slice(p[0], p[1]); }
    const e = explain(it);
    return e.base || it.term || '';
  }
  function kwKey(it) {
    const e = explain(it);
    if (!e.kw && !it.term) return 'none';
    if (e.role === 'related') return 'rel:' + (e.of || termShown(it));
    if (e.role === 'manual') return 'man:' + termShown(it);
    return 'kw:' + e.kw;
  }
  function kwLabel(k) {
    if (k === 'none') return 'не определено';
    const v = k.slice(k.indexOf(':') + 1);
    if (k.startsWith('rel:')) return v ? v + ' — связанный термин' : 'связанные топонимы';
    if (k.startsWith('man:')) return '«' + v + '» — добавлен вручную';
    return v;
  }
  function roleText(it, e) {
    const langs = e.langs.length ? e.langs.slice(0, 4).map(langName).join(', ').toLowerCase() + (e.langs.length > 4 ? '…' : '') : '';
    const src = TSRC_RU[e.src] ? ' · ' + TSRC_RU[e.src] : '';
    if (e.role === 'main') return (C.normText(e.base || it.term) === C.normText(e.kw) ? 'само ключевое слово' : 'перевод / вариант ключевого слова') + (langs ? ' · ' + langs : '') + src;
    if (e.role === 'form') return 'словоформа ключевого слова (совпадение по основе «' + it.term + '…»)' + (langs ? ' · ' + langs : '');
    if (e.role === 'related') return 'связанный термин' + (e.of ? ' — ' + e.of : ' (топоним / учреждение)') + ', добавлен к ключевому слову' + (langs ? ' · ' + langs : '');
    if (e.role === 'manual') return 'термин, добавленный вручную в «Термины»' + (langs ? ' · ' + langs : '');
    if (e.role === 'ctx') return 'термин контекста';
    return ROLE_RU[e.role] || '';
  }
  function foundByText(it) {
    const e = explain(it);
    const parts = [];
    if (e.kw) parts.push('ключевое слово «' + e.kw + '»');
    if (it.term) parts.push('термин «' + termShown(it) + '» (' + (ROLE_RU[e.role] || '') + ', ' + (HIT_RU[it.hit] || '') + ')');
    else if (it.hit === 'engine') parts.push('поисковая система, совпадение в тексте статьи');
    if (it.ctx_term) parts.push('контекст «' + it.ctx_term + '»');
    return parts.join('; ');
  }
  function foundBy(it, noHeader) {
    const e = explain(it);
    const box = el('div', { class: 'foundby' });
    if (!noHeader) box.appendChild(el('div', { class: 'fb-h' }, icon('search'), 'Найдено по'));
    const row = (k, ...v) => box.appendChild(el('div', { class: 'fb-r' }, el('span', { class: 'fb-k' }, k), el('span', { class: 'fb-v' }, ...v)));
    row('Ключевое слово', e.kw ? el('b', { class: 'fb-kw' }, '«' + e.kw + '»') : el('span', { class: 'muted' }, 'не определено'));
    if (it.term) {
      row(e.role === 'related' ? 'Связанный термин' : 'Сработал термин', el('b', { class: 'fb-term', lang: (e.langs[0] || it.lang || ''), dir: 'auto' }, termShown(it)),
        el('span', { class: 'fb-where' }, ' — ' + (HIT_RU[it.hit] || '')), el('div', { class: 'fb-sub' }, roleText(it, e)));
    } else if (it.hit === 'engine') {
      row('Совпадение', el('span', null, 'термин не виден в заголовке и аннотации — поисковая система нашла его в тексте статьи'));
    }
    if (it.ctx_term) row('Контекст', el('b', null, it.ctx_term));
    const rl = it.rel || C.relevance(it);
    const relEl = el('span', { class: 'rel-' + (C.REL_STRICT.has(rl) ? 'ok' : 'weak') }, C.REL_LABELS[rl] || '');
    const mm = it.meta && it.meta.mentions;
    if (mm && mm.paras) relEl.appendChild(el('div', { class: 'fb-sub' }, 'на странице тема упоминается в ' + mm.hits + ' из ' + mm.paras + ' абзацев' + (mm.hits ? ' (впервые — в ' + (mm.first + 1) + '-м)' : '') +
      (mm.ctx === false && (S.params && S.params.context || []).length ? ' · термин контекста на странице не найден' : '')));
    else if (rl === 'unverified' && SERVER) {
      const b = el('button', { class: 'btn small', style: 'margin-top:4px' }, it._checking ? 'проверяю…' : 'Проверить упоминания на странице');
      b.addEventListener('click', (e) => { e.stopPropagation(); deepCheck(it, false); });
      relEl.appendChild(el('div', null, b));
    }
    row('Соответствие', relEl);
    if (mm && mm.samples && mm.samples.length) {
      const terms = (mm.terms || []).concat(it.term ? [it.term] : []);
      mm.samples.forEach((smp, i) => {
        const t = terms.find((x) => locate(smp, x)) || '';
        row(i ? '' : 'Цитата', marked(smp, t, { class: 'fb-quote', dir: 'auto', lang: it.lang || '' }, 'div'));
      });
    }
    const qs = it.q || [];
    qs.slice(0, 3).forEach((x, i) => row(i ? '' : (qs.length > 1 ? 'Запросы' : 'Запрос'), el('span', { class: 'fb-q' }, el('span', { class: 'muted' }, x.t + (x.q ? ': ' : ' — ')), x.q ? el('code', { dir: 'auto' }, x.q) : el('span', { class: 'muted' }, 'лента источника, отбор по терминам'))));
    if (qs.length > 3) row('', el('span', { class: 'muted' }, 'и ещё ' + (qs.length - 3)));
    return box;
  }
  function kwTag(it) {
    const e = explain(it);
    if (!it.term && !e.kw) return null;
    const txt = it.term ? termShown(it) : e.kw;
    const cls = 'tag kw' + (e.role === 'related' ? ' rel' : '') + (it.hit === 'engine' ? ' eng' : '');
    return el('span', null, el('span', { class: cls, title: 'Найдено по: ' + foundByText(it), dir: 'auto' }, '⌕ ' + txt));
  }

  const PLATFORM_CODE = { telegram: 'TG', vk: 'VK', x: 'X', linkedin: 'in', facebook: 'FB', instagram: 'IG', whatsapp: 'WA', youtube: 'YT' };
  function platformBadge(p) {
    const name = ((S.social && S.social.platforms && S.social.platforms[p]) || {}).name || p || 'соцсеть';
    return el('span', { class: 'plat p-' + (p || 'x'), title: name }, PLATFORM_CODE[p] || '•');
  }
  function reportName(rid) {
    const r = S.catalog && S.catalog.reports ? S.catalog.reports.find((x) => x.id === rid) : null;
    return r ? r.name : '';
  }
  function rowEl(it, opts) {
    opts = opts || {};
    const url = it.resolved || it.url;
    const title = extLink(url, it.title, 'ititle');
    title.setAttribute('lang', it.lang === 'zh' && /[國臺灣這們]/.test(it.title) ? 'zh-Hant' : (it.lang || ''));
    title.setAttribute('dir', 'auto');
    title.addEventListener('click', (e) => { e.stopPropagation(); select(it.id, true); });
    const social = isSocial(it);
    const plat = social && it.extra ? it.extra.platform : '';
    const meta = el('div', { class: 'imeta' },
      el('span', { class: 'src' }, it.srcName || it.domain || '—'),
      it.country && !social ? el('span', { class: 'cc', title: countryName(it.country) }, it.country) : null,
      it.lang ? el('span', { class: 'lg', title: langName(it.lang) }, it.lang.toUpperCase()) : null,
      el('time', { title: it.ts ? fmtDate(it.ts) + ' (' + tzLabel() + ') · ' + fmtUTC(it.ts) : 'дата не указана — в пределах периода по данным поисковика' }, it.ts ? fmtShort(it.ts) : 'без даты'), kwTag(it));
    if (it.rel && !C.REL_STRICT.has(it.rel) && hasTopic()) meta.appendChild(el('span', null, el('span', { class: 'tag loose', title: C.REL_LABELS[it.rel] }, it.rel === 'passing' ? 'вскользь' : it.rel === 'absent' ? 'не найдено на странице' : 'не проверено')));
    if (it.new) meta.appendChild(el('span', null, el('span', { class: 'tag new', title: 'Не встречалось в прошлых поисках' }, 'НОВОЕ')));
    if (it.paywall) meta.appendChild(el('span', null, el('span', { class: 'tag pw', title: C.PAYWALL_LABELS[it.paywall] || '' }, 'платный')));
    if (it.state) meta.appendChild(el('span', null, el('span', { class: 'tag st' + (it.state === 'public' ? ' public' : ''), title: it.state === 'control' ? 'Государственное СМИ (под контролем государства)' : 'Государственное финансирование, редакционная независимость' }, it.state === 'control' ? 'гос.' : 'гос. фин.')));
    if (it.origin && it.origin.status === 'reprint' && it.origin.credited && it.origin.credited.label) meta.appendChild(el('span', null, el('span', { class: 'tag cred', title: it.origin.reason }, '← ' + it.origin.credited.label)));
    if (it.storySize > 1 && !opts.inStory) meta.appendChild(el('span', null, el('span', { class: 'tag story', title: 'Публикаций по этому сюжету' }, '+' + (it.storySize - 1) + ' в сюжете')));
    if (it.bm) meta.appendChild(el('span', null, el('span', { class: 'tag bm', title: 'Источник из ваших закладок: ' + it.bm }, 'закладки')));
    if (it.kind === 'paper') meta.appendChild(el('span', null, el('span', { class: 'tag', title: 'Научная публикация' }, 'наука')));
    if (it.kind === 'report') {
      const rn = it.extra && it.extra.report ? reportName(it.extra.report) : '';
      meta.appendChild(el('span', null, el('span', { class: 'tag rep', title: rn ? 'Доклад из каталога: ' + rn : 'Доклад / документ' }, rn ? 'доклад: ' + rn.split('(')[0].trim().slice(0, 48) : 'доклад')));
      if (it.extra && it.extra.topic_hit) meta.appendChild(el('span', null, el('span', { class: 'tag kw', title: 'Упоминает тему' }, '⌕ ' + it.extra.topic_hit)));
    }
    if (social && it.extra && it.extra.views) meta.appendChild(el('span', { class: 'muted', title: 'Просмотры' }, '👁 ' + it.extra.views));
    const main = el('div', { class: 'imain' }, title);
    const tr = S.trTitles && it.lang && it.lang !== 'ru' ? S.tr.get(it.id) : null;
    if (tr && tr.title) main.appendChild(el('div', { class: 'itr', lang: 'ru' }, tr.title));
    main.appendChild(meta);
    const snip = it.snippet && it.snippet.length > 30 && C.normText(it.snippet) !== C.normText(it.title) ? it.snippet : '';
    const open = S.density === 'full' || S.openRows.has(it.id);
    if (snip && open) main.appendChild(el('div', { class: 'isnip', lang: it.lang || '', dir: 'auto' }, snip));
    const star = el('button', { class: 'star' + (it.starred ? ' on' : ''), title: it.starred ? 'Убрать из досье' : 'Добавить в досье (S)' }, icon('star', it.starred));
    star.addEventListener('click', (e) => { e.stopPropagation(); toggleDossier(it); });
    const side = el('div', { class: 'iside' });
    if (snip && S.density !== 'full') {
      const ex = el('button', { class: 'iexp', title: open ? 'Свернуть аннотацию' : 'Показать аннотацию' }, open ? '▾' : '▸');
      ex.addEventListener('click', (e) => {
        e.stopPropagation();
        if (S.openRows.has(it.id)) S.openRows.delete(it.id); else S.openRows.add(it.id);
        row.replaceWith(rowEl(it, opts));
      });
      side.appendChild(ex);
    }
    side.appendChild(star);
    const row = el('article', { class: 'item' + (S.selected === it.id ? ' sel' : '') + (it.origin && it.origin.status === 'reprint' ? ' dimmed' : ''), data: { id: it.id } },
      el('div', null, social ? platformBadge(plat) : tierBadge(it.tier)), el('div', null, originBadge(it.origin)), main, side);
    row.addEventListener('click', () => select(it.id));
    return row;
  }

  function socialPanel() {
    const box = el('div', { class: 'socialpanel' });
    const info = S.social;
    const q = S.params && S.params.topics ? S.params.topics.join(' ') : $('#qTopic').value;
    box.appendChild(el('div', { class: 'sp-h' }, el('b', null, 'Соцсети'), ' — публичные публикации. ',
      el('span', { class: 'muted' }, 'Telegram-каналы опрашиваются без ключей; остальные платформы — по ключам API (Настройки → Соцсети).')));
    if (info && info.keys) {
      const k = info.keys;
      const miss = [];
      if (!k.vk) miss.push('ВКонтакте — сервисный ключ VK');
      if (!k.x) miss.push('X — ключ API X (платный)');
      if (!k.brave && !k.gcse) miss.push('LinkedIn, Facebook, Instagram, WhatsApp-каналы — ключ Brave Search или Google');
      if (!k.youtube) miss.push('YouTube — ключ Google');
      if (miss.length) box.appendChild(el('div', { class: 'muted', style: 'font-size:12px;margin:4px 0' }, 'Не подключено: ' + miss.join(' · ')));
    }
    const links = el('div', { class: 'sp-links' }, el('span', { class: 'muted' }, 'Искать на платформе (откроется в браузере): '));
    for (const [pid, p] of Object.entries((info && info.platforms) || {})) {
      const u = p.search.replace('{q}', encodeURIComponent(q || ''));
      links.appendChild(extLink(u, p.name, 'btn small ghost'));
    }
    box.appendChild(links);
    return box;
  }
  function renderList() {
    const list = clear($('#list'));
    list.classList.toggle('compact', S.density !== 'full');
    if (S.section === 'social' && (S.items.size || S.params)) list.appendChild(socialPanel());
    if (!S.items.size) {
      list.appendChild(emptyState());
      return;
    }
    if (!visible.length) {
      list.appendChild(el('div', { class: 'empty' }, el('h2', null, 'Нет материалов под выбранные фильтры'),
        el('p', null, 'Ослабьте фильтры слева, переключитесь на «Широкий охват» или снизьте порог уровня.')));
      if (S.looseHidden.length) list.appendChild(looseBar());
      return;
    }
    if (S.view === 'sources') {
      const groups = new Map();
      for (const it of visible) {
        const k = it.srcName || it.domain || '—';
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(it);
      }
      const arr = [...groups.entries()].sort((a, b) => (a[1][0].tier || 4) - (b[1][0].tier || 4) || b[1].length - a[1].length);
      for (const [k, members] of arr) {
        members.sort((a, b) => (b.ts || 0) - (a.ts || 0));
        const nNew = members.filter((x) => x.new).length;
        const open = S.openStories.has('src:' + k);
        const head = el('div', { class: 'grp' }, isSocial(members[0]) ? platformBadge(members[0].extra && members[0].extra.platform) : tierBadge(members[0].tier),
          k + ' · ' + members.length, nNew ? el('span', { class: 'tag new' }, 'новых: ' + nNew) : null);
        list.appendChild(head);
        members.slice(0, open ? members.length : 5).forEach((it) => list.appendChild(rowEl(it)));
        if (members.length > 5) {
          const tg = el('button', { class: 'story-toggle', style: 'margin:0 0 6px 64px' }, open ? '▾ свернуть' : '▸ ещё ' + (members.length - 5));
          tg.addEventListener('click', () => { if (open) S.openStories.delete('src:' + k); else S.openStories.add('src:' + k); renderList(); });
          list.appendChild(tg);
        }
      }
      if (S.looseHidden.length) list.appendChild(looseBar());
      return;
    }
    if (S.view === 'tiers') {
      for (const t of [1, 2, 3, 4]) {
        const grp = visible.filter((x) => (x.tier || 4) === t);
        if (!grp.length) continue;
        list.appendChild(el('div', { class: 'grp' }, tierBadge(t), C.TIERS[t].label + ' · ' + grp.length));
        grp.slice(0, S.shown).forEach((it) => list.appendChild(rowEl(it)));
      }
    } else if (S.view === 'stories') {
      const groups = new Map();
      for (const it of visible) {
        const k = it.story || it.id;
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(it);
      }
      let n = 0;
      for (const [k, members] of groups) {
        if (n++ >= S.shown) break;
        const rep = members.slice().sort((a, b) => ((a.origin && a.origin.status === 'primary') ? 0 : 1) - ((b.origin && b.origin.status === 'primary') ? 0 : 1) || (a.tier || 4) - (b.tier || 4) || (a.ts || 0) - (b.ts || 0))[0];
        list.appendChild(rowEl(rep));
        if (members.length > 1) {
          const open = S.openStories.has(k);
          const tg = el('button', { class: 'story-toggle', style: 'margin:0 0 6px 64px' }, (open ? '▾ скрыть ' : '▸ ещё ') + (members.length - 1) + ' публикаций по сюжету');
          tg.addEventListener('click', () => { if (open) S.openStories.delete(k); else S.openStories.add(k); renderList(); });
          list.appendChild(tg);
          if (open) {
            const box = el('div', { class: 'story-members' });
            members.filter((m) => m !== rep).sort((a, b) => (a.ts || 0) - (b.ts || 0)).forEach((m) => box.appendChild(rowEl(m, { inStory: true })));
            list.appendChild(box);
          }
        }
      }
    } else {
      visible.slice(0, S.shown).forEach((it) => list.appendChild(rowEl(it)));
    }
    if (S.looseHidden.length) list.appendChild(looseBar());
    if (visible.length > S.shown && S.view !== 'stories') {
      const more = el('button', { class: 'btn more' }, 'Показать ещё ' + Math.min(150, visible.length - S.shown) + ' из ' + (visible.length - S.shown));
      more.addEventListener('click', () => { S.shown += 150; renderList(); });
      list.appendChild(more);
    }
  }

  function looseBar() {
    const n = S.looseHidden.length;
    const unver = S.looseHidden.filter((x) => x.rel === 'unverified' && !x._checking);
    const bar = el('div', { class: 'loosebar' },
      el('div', null, el('b', null, 'Скрыто ' + n + ' ' + plural(n, 'материал', 'материала', 'материалов')), ' — тема не видна в заголовке и аннотации: поисковик нашёл слово где-то в тексте (часто это упоминание вскользь или ссылка «читайте также»).'));
    const acts = el('div', { class: 'ptool', style: 'margin:8px 0 0' });
    const show = el('button', { class: 'btn small' }, 'Показать все');
    show.addEventListener('click', () => setStrict(false));
    acts.appendChild(show);
    if (SERVER && unver.length) {
      const chk = el('button', { class: 'btn small' }, 'Проверить страницы (' + Math.min(unver.length, 30) + ')');
      chk.title = 'ОКО откроет страницы, посчитает упоминания темы и вернёт в ленту материалы, где тема раскрыта по существу';
      chk.addEventListener('click', () => { queueChecks(unver.sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 30)); toast('Проверяю страницы — подходящие материалы появятся в ленте'); });
      acts.appendChild(chk);
    }
    const checked = S.looseHidden.filter((x) => x.rel === 'passing' || x.rel === 'absent').length;
    if (checked) acts.appendChild(el('span', { class: 'muted', style: 'font-size:12px' }, 'проверено: ' + checked + ' — упоминание вскользь или не найдено'));
    bar.appendChild(acts);
    return bar;
  }
  function plural(n, one, few, many) { const m10 = n % 10, m100 = n % 100; return m10 === 1 && m100 !== 11 ? one : (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many); }
  function setStrict(on) {
    S.strict = on;
    store.set('strict', on);
    const cb = $('#optStrict'); if (cb) cb.checked = on;
    S.shown = 150;
    applyFilters(); render();
  }

  function emptyState() {
    const eye = el('div', null);
    eye.appendChild(eyeSvg());
    return el('div', { class: 'empty' }, eye,
      el('h2', null, S.running ? 'Идёт поиск…' : 'ОКО готово к работе'),
      el('p', null, S.running ? 'Материалы появятся здесь по мере ответа источников.' :
        'Задайте тему (по умолчанию — «Узбекистан»), период и языки, затем нажмите «НАЙТИ». Поиск идёт параллельно на всех выбранных языках по изданиям разных стран мира, аналитическим центрам, международным организациям и официальным источникам.'),
      el('p', { class: 'muted', style: 'font-size:12px' }, 'Клавиши: / — к поиску · Enter — найти · J/K — навигация · O — открыть оригинал · S — в досье · C — проверить первоисточник · Esc — закрыть карточку'));
  }
  function eyeSvg() {
    const s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('viewBox', '0 0 68 40');
    s.setAttribute('class', 'eye-big');
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', 'M3 20C12 7 22 2 34 2s22 5 31 18c-9 13-19 18-31 18S12 33 3 20z');
    p.setAttribute('fill', 'none'); p.setAttribute('stroke', '#c9a227'); p.setAttribute('stroke-width', '1.6');
    const c1 = document.createElementNS(SVG_NS, 'circle');
    c1.setAttribute('cx', '34'); c1.setAttribute('cy', '20'); c1.setAttribute('r', '9.5'); c1.setAttribute('fill', 'none'); c1.setAttribute('stroke', '#e3bd4b'); c1.setAttribute('stroke-width', '1.6');
    const c2 = document.createElementNS(SVG_NS, 'circle');
    c2.setAttribute('cx', '34'); c2.setAttribute('cy', '20'); c2.setAttribute('r', '3.4'); c2.setAttribute('fill', '#e3bd4b');
    s.append(p, c1, c2);
    return s;
  }

  // ================================================================ карточка материала
  function select(id, fromLink) {
    S.selected = id;
    $$('#list .item').forEach((r) => r.classList.toggle('sel', r.dataset.id === id));
    const it = S.items.get(id);
    renderDetail(it);
    if (it && SERVER && !it.meta && !it._checking && !fromLink && S.settings.ui_autocheck_open !== false) deepCheck(it, true);
  }

  function dsec(title, body, open, key, extraCls) {
    const d = el('details', { class: 'dsec' + (extraCls ? ' ' + extraCls : '') });
    const k = key || title;
    const st = S.cardOpen || (S.cardOpen = store.get('cardOpen', {}));
    d.open = k in st ? st[k] : !!open;
    d.addEventListener('toggle', () => { st[k] = d.open; store.set('cardOpen', st); });
    d.appendChild(el('summary', null, typeof title === 'string' ? el('h4', null, title) : title));
    d.appendChild(body);
    return d;
  }
  function watchKeyOf(it) {
    if (isSocial(it) && it.extra && it.extra.platform === 'telegram' && it.extra.channel) return { kind: 'channel', id: it.extra.channel, name: it.srcName };
    if (it.source_id && S.registry.byId.get(it.source_id)) return { kind: 'source', id: it.source_id, name: S.registry.byId.get(it.source_id).name };
    return null;
  }
  function isWatched(w) {
    if (!w) return false;
    return w.kind === 'source' ? S.watch.sources.includes(w.id) : S.watch.channels.some((c) => c.id.toLowerCase() === w.id.toLowerCase());
  }
  function toggleWatch(w, on) {
    if (!w) return;
    const now = on === undefined ? !isWatched(w) : on;
    if (w.kind === 'source') S.watch.sources = S.watch.sources.filter((x) => x !== w.id).concat(now ? [w.id] : []);
    else S.watch.channels = S.watch.channels.filter((c) => c.id.toLowerCase() !== w.id.toLowerCase()).concat(now ? [{ platform: 'telegram', id: w.id, name: w.name || w.id, lang: w.lang || 'ru' }] : []);
    saveWatch();
    toast(now ? 'Добавлено в мониторинг: ' + (w.name || w.id) : 'Убрано из мониторинга: ' + (w.name || w.id));
  }
  const saveWatch = debounce(() => {
    store.set('watch', S.watch);
    updateWatchCount();
    if (SERVER) api('/api/state/watch', { method: 'PUT', body: S.watch }).catch(() => toast('Список мониторинга сохранён только в браузере', true));
    if (!$('#watchPanel').classList.contains('hidden')) renderWatchPanel();
  }, 300);
  function updateWatchCount() { const n = S.watch.sources.length + S.watch.channels.length; $('#watchCount').textContent = String(n); }

  async function translateItem(it, force) {
    const cur = S.tr.get(it.id);
    if (!SERVER || (cur && (cur.loading || (cur.done && !cur.titleOnly && !force)))) return;
    const m = it.meta && it.meta.ok ? it.meta : null;
    const snip = (m && (m.description || m.lead)) || it.snippet || '';
    S.tr.set(it.id, { loading: true });
    try {
      const r = await api('/api/translate', { method: 'POST', body: { texts: [it.title, snip.slice(0, 2500)], to: 'ru' } });
      S.tr.set(it.id, { title: r.texts[0] || '', snippet: snip ? r.texts[1] || '' : '', engine: r.engine, done: true });
    } catch (e) { S.tr.set(it.id, { error: e.message, done: true }); }
    if (S.selected === it.id) renderDetail(S.items.get(it.id) || it, true);
  }
  async function translateFull(it) {
    const cur = S.trFull.get(it.id);
    if (cur && cur.loading) return;
    S.trFull.set(it.id, { loading: true });
    if (S.selected === it.id) renderDetail(it, true);
    try { S.trFull.set(it.id, await api('/api/translate/article', { method: 'POST', body: { url: it.url } })); }
    catch (e) { S.trFull.set(it.id, { ok: false, error: e.message }); }
    if (S.selected === it.id) renderDetail(S.items.get(it.id) || it, true);
  }
  function translationBlock(it) {
    const box = el('div', { class: 'dtr' });
    const url = it.resolved || (it.meta && it.meta.final_url) || it.url;
    if (!SERVER) {
      box.appendChild(extLink('https://translate.google.com/translate?sl=auto&tl=ru&u=' + encodeURIComponent(url), 'Открыть перевод страницы в Google Переводчике ↗'));
      return box;
    }
    const tr = S.tr.get(it.id);
    if (!tr || (tr.titleOnly && !tr.loading)) {
      if (tr && tr.title) box.appendChild(el('div', { class: 'dtr-title', lang: 'ru' }, tr.title));
      box.appendChild(actBtn('translate', 'Перевести заголовок и аннотацию', () => translateItem(it, true)));
    } else if (tr.loading) box.appendChild(el('div', { class: 'muted' }, el('span', { class: 'spinner' }), ' перевожу заголовок и аннотацию…'));
    else if (tr.error) box.appendChild(el('div', { class: 'muted' }, 'Перевод недоступен: ' + tr.error));
    else {
      box.appendChild(el('div', { class: 'dtr-title', lang: 'ru' }, tr.title));
      if (tr.snippet) box.appendChild(el('div', { class: 'dsnip', lang: 'ru' }, tr.snippet));
      box.appendChild(el('div', { class: 'muted', style: 'font-size:11px;margin-top:4px' }, 'машинный перевод · ' + (tr.engine || '')));
    }
    const full = S.trFull.get(it.id);
    const acts = el('div', { class: 'ptool', style: 'margin:8px 0 0' });
    if (!full || (!full.loading && !full.ok)) acts.appendChild(actBtn('translate', 'Перевести полный текст', () => translateFull(it), 'Извлечь текст статьи и перевести на русский прямо здесь'));
    acts.appendChild(actBtn('reader', 'Читать в переводе', () => openReader(it, true), 'Режим чтения с переводом на русский (для печати)'));
    acts.appendChild(actBtn('pdf', 'PDF перевода', () => makePdf(it, 'reader_ru'), 'Сохранить перевод статьи в PDF'));
    box.appendChild(acts);
    if (full && full.loading) box.appendChild(el('div', { class: 'muted', style: 'margin-top:6px' }, el('span', { class: 'spinner' }), ' извлекаю и перевожу текст (до минуты)…'));
    else if (full && !full.ok) box.appendChild(el('div', { class: 'muted', style: 'margin-top:6px' }, full.error || 'не удалось'));
    else if (full && full.ok) {
      const body = el('div', { class: 'dtr-full', lang: 'ru' });
      for (const b of full.blocks) body.appendChild(el(b.k === 'h2' || b.k === 'h3' ? 'h5' : 'p', null, b.tr || b.t));
      if (full.truncated) body.appendChild(el('p', { class: 'muted' }, '… переведено начало статьи (длинный текст). Полностью — «Читать в переводе».'));
      box.appendChild(dsec('Полный текст (перевод · ' + (full.engine || '') + ')', body, true, 'trfull'));
    }
    return box;
  }

  function renderDetail(it, keepScroll) {
    const box = $('#detail');
    const scroll = box.scrollTop;
    clear(box);
    if (!it) {
      box.classList.add('closed');
      box.appendChild(el('div', { class: 'dempty' }, el('h3', null, 'Карточка материала'),
        el('p', null, 'Выберите материал в ленте — здесь появятся:'),
        el('ul', null, el('li', null, 'по какому ключевому слову найден'), el('li', null, 'заголовок, авторы, издание, уровень авторитетности'),
          el('li', null, 'первоисточник или перепубликация — с обоснованием'), el('li', null, 'перевод на русский'),
          el('li', null, 'PDF, режим чтения, веб-архив'))));
      return;
    }
    box.classList.remove('closed');
    const social = isSocial(it);
    const url = it.resolved || (it.meta && it.meta.final_url) || it.url;
    const close = el('button', { class: 'dclose', title: 'Закрыть (Esc)' }, '×');
    close.addEventListener('click', () => { S.selected = null; renderDetail(null); $$('#list .item.sel').forEach((r) => r.classList.remove('sel')); });
    const plat = social && it.extra ? (((S.social && S.social.platforms && S.social.platforms[it.extra.platform]) || {}).name || it.extra.platform) : '';
    const kicker = social ? 'Соцсети · ' + plat : (C.TYPE_LABELS[it.type] || 'Материал') + (it.kind === 'paper' ? ' · научная публикация' : '') + (it.kind === 'report' ? ' · доклад' : '');
    const head = el('div', { class: 'dhead' },
      el('div', { class: 'dkicker' }, el('span', null, kicker), close),
      marked(it.title, it.hit === 'title' ? it.term : '', { class: 'dtitle', lang: it.lang || '', dir: 'auto' }, 'h2'));
    const needTr = it.lang && it.lang !== 'ru';
    const trc = needTr ? S.tr.get(it.id) : null;
    if (trc && trc.title) head.appendChild(el('div', { class: 'dtitle-ru', lang: 'ru' }, trc.title));
    head.appendChild(el('div', { class: 'dsub' }, (it.srcName || it.domain || '') + (it.ts ? ' · ' + fmtDate(it.ts) : ' · без даты') + (it.authors && it.authors.length ? ' · ' + it.authors.slice(0, 3).join(', ') : '')));
    const acts = el('div', { class: 'dactions' });
    acts.appendChild(el('a', { class: 'btn small', href: url, target: '_blank', rel: 'noopener noreferrer', title: 'Открыть оригинал (O)' }, icon('ext'), 'Оригинал'));
    acts.appendChild(actBtn('copy', 'Ссылка', () => copyText(url)));
    acts.appendChild(actBtn('quote', 'Цитата', () => copyText(C.citation(it)), 'Библиографическая ссылка (ГОСТ Р 7.0.5)'));
    acts.appendChild(actBtn('star', it.starred ? 'В досье ✓' : 'В досье', () => toggleDossier(it), 'Избранное: сохранить материал с заметкой'));
    const w = watchKeyOf(it);
    if (w) {
      const on = isWatched(w);
      const wb = actBtn('eye', on ? 'Мониторинг ✓' : 'Следить за источником', () => { toggleWatch(w); renderDetail(it, true); },
        (on ? 'Источник в мониторинге: ' : 'Добавить в мониторинг — лента последних публикаций: ') + (w.name || w.id));
      if (on) wb.classList.add('on');
      acts.appendChild(wb);
    }
    head.appendChild(acts);
    box.appendChild(head);

    const e = explain(it);
    box.appendChild(dsec(el('h4', null, 'Найдено по', el('span', { class: 'dsum' }, e.kw ? '«' + e.kw + '»' + (it.term ? ' · ' + termShown(it) : '') : '')), foundBy(it, true), true, 'found', 'foundsec'));

    // статус
    const o = it.origin || { status: 'unknown', reason: '', confidence: 'low' };
    const sbox = el('div', { class: 'dstatus ' + o.status },
      el('div', { class: 'sline' }, originBadge(o, true), ORIGIN_LABEL[o.status], el('span', { class: 'conf' }, CONF_LABEL[o.confidence] || '')),
      el('div', { class: 'sreason', dir: 'auto' }, o.reason || ''));
    if (o.credited && o.credited.label) {
      const cr = el('div', { class: 'scred' }, 'Первоисточник: ');
      if (o.credited.ref && S.items.has(o.credited.ref)) {
        const ref = S.items.get(o.credited.ref);
        const a = el('a', { href: '#' }, o.credited.label + ' — ' + ref.title.slice(0, 90));
        a.addEventListener('click', (ev) => { ev.preventDefault(); select(ref.id); });
        cr.appendChild(a);
      } else if (o.credited.url) cr.appendChild(extLink(o.credited.url, o.credited.label));
      else cr.appendChild(el('b', null, o.credited.label));
      sbox.appendChild(cr);
    }
    if (!social) {
      const chk = el('div', { class: 'scheck' });
      if (it._checking) chk.append(el('span', { class: 'spinner' }), el('span', { class: 'muted' }, 'Изучаю страницу: canonical, авторы, агентские пометки…'));
      else {
        chk.appendChild(actBtn('shield', it.meta ? 'Проверить повторно' : 'Проверить первоисточник', () => deepCheck(it, false), 'Загрузить страницу и проверить признаки перепубликации (C)'));
        if (it.meta && !it.meta.ok) chk.appendChild(el('span', { class: 'muted', style: 'font-size:12px' }, it.meta.error || 'страница недоступна'));
        else if (it.meta) chk.appendChild(el('span', { class: 'muted', style: 'font-size:12px' }, 'страница проверена'));
      }
      sbox.appendChild(chk);
    }
    box.appendChild(sbox);

    // перевод
    if (needTr) {
      if (SERVER && !S.tr.has(it.id) && S.settings.ui_autotranslate !== false) translateItem(it);
      box.appendChild(dsec('Перевод на русский', translationBlock(it), true, 'tr'));
    }

    // сведения
    const T = C.TIERS[it.tier] || C.TIERS[4];
    const src = it.source_id ? S.registry.byId.get(it.source_id) : null;
    const m = it.meta && it.meta.ok ? it.meta : null;
    const authors = (m && m.authors && m.authors.length ? m.authors : it.authors) || [];
    const main = [
      ['Издание', el('span', null, it.srcName || '—', src && src.note ? el('span', { class: 'sub' }, src.note) : null, m && m.site_name && C.normText(m.site_name) !== C.normText(it.srcName || '') ? el('span', { class: 'sub' }, 'по данным страницы: ' + m.site_name) : null)],
      ['Авторы', authors.length ? authors.join(', ') : el('span', { class: 'muted' }, social ? '—' : (it.meta ? 'не указаны на странице' : 'не указаны в выдаче — нажмите «Проверить первоисточник»'))],
      ['Опубликовано', it.ts ? el('span', null, fmtDate(it.ts) + ' (' + tzLabel() + ')', el('span', { class: 'sub' }, fmtUTC(it.ts) + (it.prec === 'day' ? ' · точность — день' : '') + ' · ' + ago(it.ts))) : el('span', { class: 'muted' }, 'дата не указана — в пределах периода по данным поисковика')],
      social ? ['Платформа', plat + (it.extra && it.extra.channel ? ' · @' + it.extra.channel : '') + (it.extra && it.extra.views ? ' · просмотров: ' + it.extra.views : '')] :
        ['Уровень', el('span', null, tierBadge(it.tier), ' ', T.label, ' ', el('span', { class: 'stars' }, '★'.repeat(T.stars) + '☆'.repeat(3 - T.stars)), el('span', { class: 'sub' }, T.desc))]
    ];
    if (social && it.extra && it.extra.fwd) main.push(['Переслано из', it.extra.fwd.url ? extLink(it.extra.fwd.url, it.extra.fwd.name || it.extra.fwd.url) : it.extra.fwd.name]);
    if (it.kind === 'report' && it.extra && it.extra.report) {
      const r = S.catalog && S.catalog.reports.find((x) => x.id === it.extra.report);
      if (r) main.push(['Доклад', el('span', null, r.name, el('span', { class: 'sub' }, r.cadence + (r.rank ? ' · есть рейтинг стран' : '')), extLink(r.url, 'страница доклада ↗'))]);
    }
    const more = [
      ['Заголовок', el('span', { lang: it.lang || '', dir: 'auto' }, it.title)],
      ['Источник (сайт)', it.domain ? extLink('https://' + (src ? src.domains[0].split('/')[0] : it.domain), it.domain) : '—'],
      ['Тип источника', social ? 'Соцсети' : (C.TYPE_LABELS[it.type] || '—')],
      ['Страна издания', it.country ? countryName(it.country) + ' (' + it.country + ')' : '—'],
      ['Язык', langName(it.lang)],
      ['Доступ', it.paywall ? el('span', { style: 'color:#f0c36a' }, C.PAYWALL_LABELS[it.paywall] + (m && m.paywall_evidence ? ' (' + m.paywall_evidence + ')' : '')) : 'свободный (по данным реестра)'],
      ['Гос. принадлежность', it.state === 'control' ? el('span', { style: 'color:#ff9c95' }, 'государственное СМИ (под контролем государства)') : it.state === 'public' ? 'государственное финансирование, редакционная независимость' : '—'],
      ['Найдено через', (it.via || []).join('; ')]
    ];
    if (it.bm) more.push(['Ваши закладки', it.bm + '. Аналитические центры, издания']);
    if (m && m.canonical) more.push(['Каноническая ссылка', extLink(m.canonical, m.canonical)]);
    if (it.gn && url !== it.url) more.push(['Адрес статьи', extLink(url, url)]);
    if (it.pdf) more.push(['PDF документа', extLink(it.pdf, 'скачать PDF ↗')]);
    if (it.extra && it.extra.doi) more.push(['DOI', extLink(it.extra.doi, it.extra.doi)]);
    const tbl = el('table', { class: 'dtable' });
    for (const [k, v] of main) tbl.appendChild(el('tr', null, el('th', null, k), el('td', null, v)));
    const tbl2 = el('table', { class: 'dtable' });
    for (const [k, v] of more) tbl2.appendChild(el('tr', null, el('th', null, k), el('td', null, v)));
    const info = el('div', null, tbl, dsec('Все сведения', tbl2, false, 'allinfo', 'nested'));
    box.appendChild(dsec('Сведения', info, true, 'info'));

    // аннотация
    const snip = (m && (m.description || m.lead)) || it.snippet;
    if (snip && C.normText(snip) !== C.normText(it.title)) box.appendChild(dsec(social ? 'Текст публикации' : 'Аннотация', marked(snip, it.term, { class: 'dsnip', lang: it.lang || '', dir: 'auto' }, 'div'), snip.length < 500 || social, 'snip'));

    // сюжет
    if (it.storySize > 1) {
      const members = [...S.items.values()].filter((x) => x.story === it.story).sort((a, b) => (a.ts || 0) - (b.ts || 0));
      const ul = el('ul', { class: 'dlist' });
      members.forEach((x, i) => {
        const a = el('a', { href: '#', lang: x.lang || '', dir: 'auto' }, x.title);
        a.addEventListener('click', (ev) => { ev.preventDefault(); select(x.id); });
        ul.appendChild(el('li', null, originBadge(x.origin, true), el('div', null, a,
          el('div', { class: 'm' }, fmtShort(x.ts) + ' · ' + (x.srcName || x.domain) + ' · ' + (C.TIERS[x.tier] || C.TIERS[4]).code, i === 0 ? el('span', { class: 'first' }, 'первым') : null))));
      });
      box.appendChild(dsec('Сюжет · ' + members.length + ' публикаций', ul, false, 'story'));
    }
    if (it.related && it.related.length) {
      const ul = el('ul', { class: 'dlist' });
      it.related.forEach((r) => ul.appendChild(el('li', null, el('span', { class: 'muted' }, '•'), el('div', null, extLink(r.url, r.title), el('div', { class: 'm' }, r.source)))));
      box.appendChild(dsec('Связанные публикации · ' + it.related.length, ul, false, 'related'));
    }

    // действия
    const g = el('div', { class: 'dgrid' });
    if (!social) {
      g.appendChild(actBtn('pdf', 'PDF оригинала', () => makePdf(it, 'original'), 'Сохранить страницу в PDF через браузер Chrome/Edge'));
      g.appendChild(actBtn('reader', 'PDF (режим чтения)', () => makePdf(it, 'reader'), 'Чистый текст статьи с метаданными — в PDF'));
      g.appendChild(actBtn('reader', 'Режим чтения / печать', () => openReader(it), 'Открыть текст статьи в режиме чтения для печати'));
    }
    g.appendChild(actBtn('archive', 'Сохранить в веб-архив', () => window.open('https://web.archive.org/save/' + url, '_blank', 'noopener'), 'Зафиксировать копию страницы в Wayback Machine'));
    g.appendChild(actBtn('search', 'Найти в веб-архиве', () => window.open('https://web.archive.org/web/*/' + url, '_blank', 'noopener')));
    g.appendChild(actBtn('archive', 'archive.today', () => window.open('https://archive.ph/submit/?url=' + encodeURIComponent(url), '_blank', 'noopener')));
    g.appendChild(actBtn('search', 'Этот заголовок в поиске', () => window.open('https://www.google.com/search?q=' + encodeURIComponent('"' + C.titleCore(it.title).slice(0, 110) + '"'), '_blank', 'noopener'), 'Найти другие публикации с тем же заголовком'));
    box.appendChild(dsec('Действия: PDF, архив', g, false, 'actions'));

    // заметка
    const d = S.dossier.get(it.id);
    const note = el('textarea', { class: 'dnote', placeholder: 'Заметка аналитика (сохраняется в досье)…' });
    note.value = d ? d.note || '' : '';
    note.addEventListener('change', () => {
      if (!S.dossier.has(it.id)) toggleDossier(it, true);
      S.dossier.get(it.id).note = note.value;
      saveDossier();
    });
    box.appendChild(dsec('Заметка' + (d && d.note ? ' ✎' : ''), note, !!(d && d.note), 'note'));
    if (keepScroll) box.scrollTop = scroll;
  }
  function actBtn(ic, label, fn, title) {
    const b = el('button', { class: 'btn small', title: title || label }, icon(ic), label);
    b.addEventListener('click', (e) => { e.stopPropagation(); fn(); });
    return b;
  }

  async function deepCheck(it, silent) {
    if (!SERVER) { if (!silent) toast('Проверка первоисточника работает при запуске ОКО через сервер (START_OKO)', true); return; }
    if (it._checking) return;
    it._checking = true;
    if (S.selected === it.id) renderDetail(it, true);
    try {
      const vt = verifyTerms();
      const m = await api('/api/article', { method: 'POST', body: { url: it.url, terms: vt.terms, ctx: vt.ctx } });
      S.meta.set(it.id, m);
      if (m.ok) {
        if (m.final_url && it.gn) it.resolved = m.final_url;
        if (m.authors && m.authors.length && !(it.authors && it.authors.length)) it.authors = m.authors;
      }
      if (!silent) toast(m.ok ? 'Страница проверена' : (m.error || 'Страница недоступна'), !m.ok);
    } catch (e) {
      S.meta.set(it.id, { ok: false, error: e.message });
      if (!silent) toast('Проверка: ' + e.message, true);
    } finally {
      it._checking = false;
      recompute('skip-detail');
      if (S.selected === it.id) renderDetail(S.items.get(it.id), true);
    }
  }

  let vtCache = { key: null, val: null };
  function verifyTerms() {
    const plan = (S.params && S.params.plan) || {};
    const key = JSON.stringify(plan);
    if (vtCache.key === key) return vtCache.val;
    const terms = new Set(), ctx = new Set();
    for (const p of Object.values(plan)) {
      (p.q || []).concat(p.m || []).forEach((t) => terms.add(t));
      (p.ctx || []).concat(p.ctx_m || []).forEach((t) => ctx.add(t));
    }
    vtCache = { key, val: { terms: [...terms].slice(0, 400), ctx: [...ctx].slice(0, 100) } };
    return vtCache.val;
  }
  function startAutoCheck() {
    const n = Number(S.settings.ui_autocheck == null ? 25 : S.settings.ui_autocheck);
    const nv = Number(S.settings.ui_verify == null ? 40 : S.settings.ui_verify);
    const byScore = (a, b) => (b.score || 0) - (a.score || 0);
    const cands = n ? visible.filter((x) => !S.meta.has(x.id) && x.origin && (x.origin.status === 'unknown' || x.origin.confidence === 'low') && (x.tier || 4) <= 3)
      .sort(byScore).slice(0, n) : [];
    // материалы, где тема видна только поисковику: проверяем страницы (ссылки Google News — не больше 15,
    // чтобы не упереться в ограничения Google)
    let gn = 0;
    const unver = nv ? [...S.items.values()].filter((x) => x.rel === 'unverified' && !S.meta.has(x.id) && (x.tier || 4) <= 3 && baseOk(x))
      .sort(byScore).filter((x) => !x.gn || gn++ < 15).slice(0, nv) : [];
    const q = [];
    for (let i = 0; i < Math.max(cands.length, unver.length); i++) {
      if (unver[i]) q.push(unver[i]);
      if (cands[i] && !q.includes(cands[i])) q.push(cands[i]);
    }
    S.deep = { queue: [], active: 0, total: 0, done: 0 };
    queueChecks(q);
  }
  function queueChecks(list) {
    const fresh = list.filter((x) => !x._checking && !S.deep.queue.includes(x));
    S.deep.queue.push(...fresh);
    S.deep.total += fresh.length;
    const next = () => {
      while (S.deep.active < 3 && S.deep.queue.length) {
        const it = S.deep.queue.shift();
        S.deep.active++;
        deepCheck(it, true).finally(() => { S.deep.active--; S.deep.done++; renderProgress(); next(); });
      }
    };
    next();
    renderProgress();
  }

  async function makePdf(it, mode) {
    if (!SERVER) { openReader(it); return; }
    toast('Формирую PDF… (до минуты)');
    try {
      const r = await api('/api/pdf', { method: 'POST', body: { url: it.url, mode, title: it.title, source: it.srcName, date: fmtDate(it.ts), status: ORIGIN_LABEL[it.origin ? it.origin.status : 'unknown'], tier: (C.TIERS[it.tier] || C.TIERS[4]).label, authors: (it.authors || []).join(', ') } });
      if (r.ok) { window.open(r.href, '_blank', 'noopener'); toast('PDF сохранён: ' + r.path); }
      else { toast((r.error || 'PDF не создан') + ' — открываю режим чтения для печати', true); openReader(it); }
    } catch (e) { toast('PDF: ' + e.message, true); }
  }
  function openReader(it, ru) {
    if (!SERVER) { window.open(it.url, '_blank', 'noopener'); return; }
    const q = new URLSearchParams({ t: TOKEN, url: it.url, title: it.title, source: it.srcName || '', date: fmtDate(it.ts), status: ORIGIN_LABEL[it.origin ? it.origin.status : 'unknown'], tier: (C.TIERS[it.tier] || C.TIERS[4]).label, authors: (it.authors || []).join(', ') });
    if (ru) q.set('tr', 'ru');
    window.open('/reader?' + q.toString(), '_blank', 'noopener');
  }

  // ================================================================ прогресс
  function renderProgress(msg) {
    const box = $('#progress');
    const tasks = [...S.tasks.values()];
    if (!S.running && !tasks.length && !msg) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    const done = tasks.filter((t) => ['ok', 'error', 'skip'].includes(t.status)).length;
    const err = tasks.filter((t) => t.status === 'error').length;
    const skipped = tasks.filter((t) => t.status === 'skip' && (t.kind === 'limit' || t.kind === 'off')).length;
    const pct = tasks.length ? Math.round((done / tasks.length) * 100) : (S.running ? 3 : 100);
    $('#pbarFill').style.width = (S.running ? pct : 100) + '%';
    const line = clear($('#pline'));
    if (S.running) line.appendChild(el('span', { class: 'spin' }));
    if (msg) line.appendChild(el('span', null, msg));
    const prim = [...S.items.values()].filter((x) => x.origin && x.origin.status === 'primary').length;
    if (tasks.length) {
      line.append(el('span', null, 'Запросов: ', el('b', null, done + '/' + tasks.length)),
        el('span', null, 'Материалов: ', el('b', null, String(S.items.size))),
        el('span', null, 'Первоисточников: ', el('b', null, String(prim))),
        el('span', null, 'Ошибок: ', el('b', { style: err ? 'color:var(--bad)' : '' }, String(err))));
      if (skipped) line.appendChild(el('span', { class: 'muted', title: 'Пропущены: сервис временно ограничил частоту запросов или канал отключён после повторных ошибок (подробности — в «Журнале»)' }, 'пропущено: ' + skipped));
      const secs = S.done && S.done.took ? S.done.took : (S.started ? (Date.now() - S.started) / 1000 : 0);
      line.appendChild(el('span', null, 'Время: ', el('b', null, Math.round(secs) + ' с')));
      if (S.done && S.done.out_of_range) line.appendChild(el('span', { class: 'muted', title: 'Отброшены материалы вне заданного периода' }, 'вне периода: ' + S.done.out_of_range));
      if (S.deep.total) line.appendChild(el('span', null, 'Проверка первоисточников: ', el('b', null, S.deep.done + '/' + S.deep.total)));
      const lb = el('button', { class: 'btn small ghost' }, $('#plog').classList.contains('hidden') ? 'Журнал ▸' : 'Журнал ▾');
      lb.addEventListener('click', () => { $('#plog').classList.toggle('hidden'); renderProgress(); });
      line.appendChild(lb);
      if (!S.running && S.done) line.appendChild(el('span', { class: 'muted' }, S.done.report ? 'сохранено в архив' : ''));
    }
    if (!$('#plog').classList.contains('hidden')) renderLog(tasks);
    const notes = clear($('#pnotes'));
    for (const n of S.notes || []) notes.appendChild(el('div', null, '⚠ ' + n));
  }
  function errorReport(tasks) {
    const provLabel = Object.fromEntries(((S.boot && S.boot.providers) || []).map((p) => [p.id, p.label]));
    const bad = tasks.filter((t) => t.status === 'error' || (t.status === 'skip' && (t.kind === 'limit' || t.kind === 'off')));
    const q = S.params ? (S.params.topics || []).join(', ') + ' · ' + fmtDate(S.params.t_from) + ' — ' + fmtDate(S.params.t_to) : '';
    return ['ОКО — отчёт об ошибках каналов (' + fmtDate(Date.now() / 1000) + ')', q ? 'Поиск: ' + q : '', '']
      .concat(bad.map((t) => (t.status === 'error' ? '✗ ' : '– ') + (provLabel[t.provider] || t.provider) + ' · ' + t.label + ' [' + t.key + ']\n    ' + (t.err || '') +
        (t.hint ? '\n    что делать: ' + t.hint : '') + (t.url ? '\n    адрес: ' + t.url : ''))).join('\n');
  }
  function renderLog(tasks) {
    const box = clear($('#plog'));
    const provLabel = Object.fromEntries(((S.boot && S.boot.providers) || []).map((p) => [p.id, p.label]));
    const order = { error: 0, run: 1, wait: 2, skip: 3, ok: 4 };
    if (tasks.some((t) => t.status === 'error' || t.kind === 'limit' || t.kind === 'off')) {
      box.appendChild(el('div', { class: 'plog-tool' }, actBtn('copy', 'Скопировать отчёт об ошибках', () => copyText(errorReport(tasks)), 'Список ошибок с причинами и адресами — чтобы переслать разработчику'),
        el('span', { class: 'muted' }, 'Каналы, которые падают несколько поисков подряд, ОКО временно отключает само (список — в «Источники → Каналы с ошибками»).')));
    }
    const t = el('table');
    tasks.slice().sort((a, b) => (order[a.status] - order[b.status]) || a.label.localeCompare(b.label)).forEach((x) => {
      const info = el('td', { class: x.status === 'error' ? 'st-error' : 'muted', style: 'font-size:11.5px' }, x.err || x.note || '');
      if (x.hint) info.appendChild(el('div', { class: 'muted' }, 'что делать: ' + x.hint));
      if (x.url && x.status === 'error') info.appendChild(el('div', null, extLink(x.url, x.url.length > 90 ? x.url.slice(0, 90) + '…' : x.url, 'mono')));
      t.appendChild(el('tr', null,
        el('td', { class: 'st-' + x.status, style: 'width:22px' }, { ok: '✓', error: '✗', run: '…', wait: '·', skip: '–' }[x.status] || ''),
        el('td', { class: 'muted', style: 'white-space:nowrap' }, provLabel[x.provider] || x.provider),
        el('td', null, x.label), el('td', { class: 'mono', style: 'white-space:nowrap;text-align:right' }, x.n != null ? String(x.n) : ''),
        el('td', { class: 'mono muted', style: 'white-space:nowrap' }, x.ms != null ? (x.ms / 1000).toFixed(1) + ' с' : ''),
        info));
    });
    box.appendChild(t);
  }

  // ================================================================ досье
  function toggleDossier(it, force) {
    if (S.dossier.has(it.id) && !force) S.dossier.delete(it.id);
    else if (!S.dossier.has(it.id)) {
      const snap = {};
      for (const k of ['id', 'url', 'resolved', 'title', 'snippet', 'ts', 'lang', 'srcName', 'src_name', 'domain', 'country', 'tier', 'type', 'authors', 'paywall', 'state', 'origin', 'kind', 'pdf', 'via', 'gn', 'hit', 'term', 'kw', 'role', 'of', 'tl', 'q', 'ctx_term']) snap[k] = it[k];
      S.dossier.set(it.id, { item: snap, note: '', added: Math.floor(Date.now() / 1000) });
    }
    it.starred = S.dossier.has(it.id);
    saveDossier();
    updateDossierCount();
    applyFilters(); render();
    if (S.selected === it.id) renderDetail(it, true);
  }
  function updateDossierCount() { $('#dossierCount').textContent = String(S.dossier.size); }
  const saveDossier = debounce(() => {
    const data = [...S.dossier.values()];
    store.set('dossier', data);
    if (SERVER) api('/api/state/dossier', { method: 'PUT', body: data }).catch(() => toast('Досье сохранено только в браузере', true));
  }, 400);

  function renderDossier() {
    const p = clear($('#view-dossier'));
    p.appendChild(el('h2', null, 'Досье · ' + S.dossier.size));
    const tool = el('div', { class: 'ptool' });
    const items = [...S.dossier.values()].sort((a, b) => (b.item.ts || 0) - (a.item.ts || 0));
    tool.appendChild(actBtn('pdf', 'PDF-сводка досье', () => printDigest(items.map((x) => Object.assign({}, x.item, { note: x.note })), 'Досье аналитика')));
    tool.appendChild(actBtn('save', 'HTML-отчёт', () => download('OKO_dossier_' + isoDate(new Date()) + '.html', reportHtml(items.map((x) => Object.assign({}, x.item, { note: x.note })), 'Досье аналитика'), 'text/html;charset=utf-8')));
    tool.appendChild(actBtn('save', 'CSV', () => download('OKO_dossier_' + isoDate(new Date()) + '.csv', toCSV(items.map((x) => Object.assign({}, x.item, { note: x.note }))), 'text/csv;charset=utf-8')));
    p.appendChild(tool);
    if (!items.length) { p.appendChild(el('div', { class: 'card' }, el('p', null, 'Досье пусто. Отмечайте важные материалы звёздочкой в ленте или кнопкой «В досье» в карточке — они сохранятся здесь вместе с вашими заметками.'))); return; }
    const t = el('table', { class: 'tbl' });
    t.appendChild(el('tr', null, el('th', null, 'Ур.'), el('th', null, 'Ст.'), el('th', null, 'Материал'), el('th', null, 'Дата'), el('th', null, 'Заметка'), el('th', null, '')));
    for (const d of items) {
      const x = d.item;
      const ta = el('textarea', { class: 'dnote', style: 'min-height:48px' });
      ta.value = d.note || '';
      ta.addEventListener('change', () => { d.note = ta.value; saveDossier(); });
      const rm = el('button', { class: 'btn small danger' }, 'Убрать');
      rm.addEventListener('click', () => { S.dossier.delete(x.id); const it = S.items.get(x.id); if (it) it.starred = false; saveDossier(); updateDossierCount(); renderDossier(); });
      t.appendChild(el('tr', null, el('td', null, tierBadge(x.tier)), el('td', null, originBadge(x.origin)),
        el('td', null, extLink(x.resolved || x.url, x.title), el('div', { class: 'muted', style: 'font-size:12px' }, (x.srcName || x.domain) + ' · ' + (x.country || '') + ' · ' + (x.lang || '').toUpperCase() + (x.origin && x.origin.credited && x.origin.credited.label ? ' · ← ' + x.origin.credited.label : ''))),
        el('td', { class: 'num' }, fmtDate(x.ts)), el('td', { style: 'width:32%' }, ta), el('td', null, rm)));
    }
    p.appendChild(t);
  }

  // ================================================================ архив
  async function renderArchive() {
    const p = clear($('#view-archive'));
    p.appendChild(el('h2', null, 'Архив поисков'));
    if (!SERVER) { p.appendChild(el('div', { class: 'card' }, el('p', null, 'Архив ведётся сервером ОКО. Запустите START_OKO.'))); return; }
    p.appendChild(el('p', { class: 'muted' }, 'Каждый завершённый поиск сохраняется автоматически. Откройте отчёт, чтобы работать с материалами прошлых дней без повторного запроса.'));
    let reps = [];
    try { reps = (await api('/api/reports')).reports || []; } catch (e) { p.appendChild(el('div', { class: 'card' }, 'Ошибка: ' + e.message)); return; }
    if (!reps.length) { p.appendChild(el('div', { class: 'card' }, el('p', null, 'Пока нет сохранённых поисков.'))); return; }
    const t = el('table', { class: 'tbl' });
    t.appendChild(el('tr', null, el('th', null, 'Выполнен'), el('th', null, 'Тема'), el('th', null, 'Период'), el('th', null, 'Материалов'), el('th', null, 'Языки'), el('th', null, '')));
    for (const r of reps) {
      const open = el('button', { class: 'btn small' }, 'Открыть');
      open.addEventListener('click', () => openReport(r.id));
      const del = el('button', { class: 'btn small danger' }, 'Удалить');
      del.addEventListener('click', async () => { if (!confirm('Удалить отчёт «' + r.title + '»?')) return; await api('/api/reports/' + encodeURIComponent(r.id), { method: 'DELETE' }); renderArchive(); });
      const per = r.period ? r.period.map((x) => (x || '').slice(0, 16).replace('T', ' ')).join(' — ') + ' UTC' : '';
      t.appendChild(el('tr', null, el('td', { class: 'num' }, r.started ? fmtDate(r.started) : r.id.slice(0, 15)),
        el('td', null, r.title + (r.context && r.context.length ? ' + ' + r.context.join(', ') : '')), el('td', { class: 'num' }, per),
        el('td', { class: 'num' }, String(r.unique || 0)), el('td', { class: 'muted' }, (r.langs || []).join(' ').toUpperCase()), el('td', { style: 'white-space:nowrap' }, open, ' ', del)));
    }
    p.appendChild(t);
  }
  async function openReport(id) {
    try {
      const r = await api('/api/reports/' + encodeURIComponent(id));
      S.items.clear(); S.meta.clear(); S.tasks.clear(); S.selected = null; S.shown = 150;
      for (const it of r.items || []) S.items.set(it.id, it);
      for (const t of r.tasks || []) S.tasks.set(t.key, t);
      S.params = r.params;
      S.stopTerms = collectStopTerms(r.params && r.params.plan);
      S.snapshot = { id, title: r.title, period: r.period, started: r.started };
      S.done = Object.assign({}, r.stats, { took: (r.finished || 0) - (r.started || 0) });
      S.notes = r.notes || [];
      showView('results');
      renderBanner();
      recompute(true);
      renderProgress();
      renderDetail(null);
    } catch (e) { toast('Отчёт: ' + e.message, true); }
  }

  // ================================================================ источники
  let srcFilter = { q: '', country: '', type: '', tier: '', channel: '', bm: '', watch: '' };
  let userSrc = { overrides: {}, added: [] };
  async function renderSources() {
    const p = clear($('#view-sources'));
    p.appendChild(el('h2', null, 'Реестр источников · ' + S.sources.length));
    if (SERVER) {
      try {
        const [s, u] = await Promise.all([api('/api/sources'), api('/api/sources/user')]);
        S.sources = s.sources; S.registry = new C.Registry(S.sources); userSrc = u || userSrc;
        if (s.progress && s.progress.running) p.appendChild(el('div', { class: 'card' }, 'Идёт проверка каналов источников: ' + s.progress.done + ' из ' + s.progress.total));
      } catch (e) { toast('Источники: ' + e.message, true); }
    }
    if (SERVER) p.appendChild(await healthBlock());
    const tool = el('div', { class: 'ptool' });
    const q = el('input', { class: 'input', placeholder: 'Поиск по названию или сайту…', style: 'width:240px' });
    q.value = srcFilter.q;
    q.addEventListener('input', debounce(() => { srcFilter.q = q.value; drawTable(); }, 200));
    const countries = [...new Set(S.sources.map((s) => s.country))].sort((a, b) => countryName(a).localeCompare(countryName(b)));
    const selC = sel([['', 'все страны']].concat(countries.map((c) => [c, countryName(c) + ' (' + c + ')'])), 'country');
    const selT = sel([['', 'все типы']].concat(Object.entries(C.TYPE_LABELS).filter(([k]) => k !== 'unknown' && k !== 'social')), 'type');
    const selTier = sel([['', 'все уровни'], ['1', 'A'], ['2', 'B'], ['3', 'C']], 'tier');
    const selCh = sel([['', 'любой канал'], ['rss', 'есть RSS'], ['wp', 'есть поиск WordPress'], ['none', 'нет канала']], 'channel');
    const selBm = sel([['', 'все'], ['1', 'из закладок'], ['0', 'добавлены ОКО']], 'bm');
    const selW = sel([['', 'мониторинг: все'], ['1', 'в мониторинге']], 'watch');
    tool.append(q, selC, selT, selTier, selCh, selBm, selW);
    function sel(opts, key) {
      const s = el('select');
      for (const [v, l] of opts) { const o = el('option', { value: v }, l); if (srcFilter[key] === v) o.selected = true; s.appendChild(o); }
      s.addEventListener('change', () => { srcFilter[key] = s.value; drawTable(); });
      return s;
    }
    tool.appendChild(actBtn('save', 'Добавить источник', () => addSourceModal()));
    tool.appendChild(actBtn('archive', 'Импорт закладок (HTML)', () => importBookmarks()));
    if (SERVER) tool.appendChild(actBtn('shield', 'Проверить каналы', async () => { await api('/api/sources/discover', { method: 'POST', body: { only_stale: false } }); toast('Проверка каналов запущена в фоне (несколько минут)'); }));
    tool.appendChild(actBtn('save', 'Экспорт реестра', () => download('OKO_sources.json', JSON.stringify(S.sources, null, 1), 'application/json')));
    p.appendChild(tool);
    p.appendChild(el('p', { class: 'muted', style: 'font-size:12.5px' }, 'Уровень и включение источника можно изменить прямо в таблице. Источники из ваших закладок отмечены. Канал: RSS — лента новостей сайта, WP — полнотекстовый поиск по сайту (WordPress). Источники без канала находятся через поисковые системы (Google News site:, GDELT, Bing).'));
    const wrap = el('div');
    p.appendChild(wrap);
    function drawTable() {
      clear(wrap);
      const nq = C.normText(srcFilter.q);
      const rows = S.sources.filter((s) => (!nq || C.normText(s.name + ' ' + s.domains.join(' ') + ' ' + (s.note || '')).includes(nq)) &&
        (!srcFilter.country || s.country === srcFilter.country) && (!srcFilter.type || s.type === srcFilter.type) &&
        (!srcFilter.tier || String(s.tier) === srcFilter.tier) &&
        (!srcFilter.channel || (srcFilter.channel === 'none' ? !s.channel : (s.channel || '').includes(srcFilter.channel))) &&
        (!srcFilter.bm || (srcFilter.bm === '1' ? !!s.bm : !s.bm)) && (!srcFilter.watch || S.watch.sources.includes(s.id)));
      wrap.appendChild(el('div', { class: 'muted', style: 'margin-bottom:6px' }, 'Показано: ' + rows.length));
      const t = el('table', { class: 'tbl' });
      t.appendChild(el('tr', null, el('th', { title: 'Мониторинг: лента последних публикаций источника' }, 'Следить'), el('th', null, 'Вкл.'), el('th', null, 'Уровень'), el('th', null, 'Источник'), el('th', null, 'Сайт'), el('th', null, 'Страна'), el('th', null, 'Тип'), el('th', null, 'Языки'), el('th', null, 'Канал'), el('th', null, 'Закладки')));
      for (const s of rows) {
        const wOn = S.watch.sources.includes(s.id);
        const wb = el('button', { class: 'eyebtn' + (wOn ? ' on' : ''), title: wOn ? 'В мониторинге — нажмите, чтобы убрать' : 'Добавить в мониторинг' }, icon('eye', wOn));
        wb.addEventListener('click', () => { toggleWatch({ kind: 'source', id: s.id, name: s.name }); setTimeout(drawTable, 350); });
        const on = el('input', { type: 'checkbox' });
        on.checked = !s.off;
        on.addEventListener('change', () => saveOverride(s, { off: !on.checked }));
        const tierSel = el('select');
        for (const v of [1, 2, 3]) { const o = el('option', { value: String(v) }, C.TIERS[v].code); if (s.tier === v) o.selected = true; tierSel.appendChild(o); }
        tierSel.addEventListener('change', () => saveOverride(s, { tier: Number(tierSel.value) }));
        t.appendChild(el('tr', null, el('td', null, wb), el('td', null, on), el('td', null, tierSel),
          el('td', null, el('div', null, s.name), s.note ? el('div', { class: 'muted', style: 'font-size:11.5px' }, s.note) : null,
            el('div', { style: 'font-size:11px;margin-top:2px' }, s.state ? el('span', { class: 'tag st' + (s.state === 'public' ? ' public' : '') }, s.state === 'control' ? 'гос.' : 'гос. фин.') : null, ' ',
              s.paywall ? el('span', { class: 'tag pw' }, C.PAYWALL_LABELS[s.paywall]) : null, ' ', s.ca ? el('span', { class: 'tag ca' }, 'Центральная Азия') : null, ' ', s.user ? el('span', { class: 'tag' }, 'добавлен вами') : null)),
          el('td', null, extLink('https://' + s.domains[0], s.domains[0])), el('td', { class: 'num' }, s.country),
          el('td', null, C.TYPE_LABELS[s.type] || s.type), el('td', { class: 'num' }, (s.lang || []).join(' ')),
          el('td', { class: 'num', title: s.disc_status ? 'проверено ' + (s.disc_ts ? fmtDate(s.disc_ts) : '') + ': ' + s.disc_status : 'не проверялся' }, s.channel || (s.disc_status === 'unreachable' ? 'недоступен' : '—')),
          el('td', { class: 'muted', style: 'font-size:12px' }, s.bm || '')));
      }
      wrap.appendChild(t);
    }
    drawTable();
  }
  async function healthBlock() {
    let ch = [];
    try { ch = (await api('/api/sources/health')).channels || []; } catch (e) { return el('div'); }
    const off = ch.filter((c) => c.disabled).length;
    const det = el('details', { class: 'card health' });
    det.appendChild(el('summary', null, el('b', null, 'Каналы с ошибками: ' + ch.length), off ? ' · временно отключено: ' + off : '', ch.length ? '' : ' — всё работает'));
    if (!ch.length) return det;
    const t = el('table', { class: 'tbl' });
    t.appendChild(el('tr', null, el('th', null, 'Канал'), el('th', null, 'Причина и что делать'), el('th', null, 'Подряд'), el('th', null, 'Последняя'), el('th', null, 'Состояние'), el('th', null, '')));
    for (const c of ch) {
      const again = el('button', { class: 'btn small' }, 'Проверить снова');
      again.addEventListener('click', async () => { await api('/api/sources/health', { method: 'POST', body: { key: c.key } }); toast('Канал будет опрошен при следующем поиске'); renderSources(); });
      t.appendChild(el('tr', null,
        el('td', null, el('div', null, c.label || c.key), el('div', { class: 'muted mono', style: 'font-size:11px' }, c.key)),
        el('td', null, el('div', null, c.reason), el('div', { class: 'muted', style: 'font-size:11.5px' }, c.err), el('div', { class: 'muted', style: 'font-size:11.5px' }, 'что делать: ' + c.hint),
          c.url ? el('div', { style: 'font-size:11px' }, extLink(c.url, c.url.length > 80 ? c.url.slice(0, 80) + '…' : c.url, 'mono')) : null),
        el('td', { class: 'num' }, String(c.streak || 0)), el('td', { class: 'num' }, c.last ? fmtDate(c.last) : ''),
        el('td', null, c.disabled ? el('span', { style: 'color:var(--warn)' }, 'отключён до ' + fmtDate(c.until)) : el('span', { class: 'muted' }, 'опрашивается')),
        el('td', null, again)));
    }
    const all = el('button', { class: 'btn small' }, 'Сбросить все и проверить снова');
    all.addEventListener('click', async () => { await api('/api/sources/health', { method: 'POST', body: {} }); toast('Все каналы будут опрошены при следующем поиске'); renderSources(); });
    const copy = el('button', { class: 'btn small' }, 'Скопировать список');
    copy.addEventListener('click', () => copyText(ch.map((c) => (c.disabled ? '[отключён] ' : '') + (c.label || c.key) + ' [' + c.key + '] — ' + c.reason + ': ' + c.err + (c.url ? ' — ' + c.url : '')).join('\n')));
    det.append(el('p', { class: 'muted', style: 'font-size:12.5px' }, 'Канал отключается автоматически после 3 ошибок подряд (на 12 ч, затем 24–72 ч) и проверяется снова. Ленты с исчезнувшим адресом ОКО ищет заново само. Ограничения частоты запросов у Google/GDELT/Bing каналы не отключают.'),
      el('div', { class: 'ptool' }, all, copy), t);
    return det;
  }
  async function saveOverride(s, patch) {
    if (!SERVER) { toast('Изменения реестра сохраняются при работе через сервер', true); return; }
    userSrc.overrides[s.id] = Object.assign({}, userSrc.overrides[s.id] || {}, patch);
    Object.assign(s, patch);
    try { await api('/api/sources/user', { method: 'POST', body: userSrc }); S.registry = new C.Registry(S.sources); toast('Сохранено'); }
    catch (e) { toast('Не сохранено: ' + e.message, true); }
  }
  function modal(title, body, onOk, okLabel) {
    const back = el('div', { class: 'modal-back' });
    const closeM = () => back.remove();
    const ok = el('button', { class: 'btn primary' }, okLabel || 'Сохранить');
    ok.addEventListener('click', async () => { if ((await onOk()) !== false) closeM(); });
    const cancel = el('button', { class: 'btn' }, 'Отмена');
    cancel.addEventListener('click', closeM);
    const x = el('button', { class: 'dclose' }, '×');
    x.addEventListener('click', closeM);
    back.appendChild(el('div', { class: 'modal' }, el('header', null, el('h3', null, title), x), el('div', { class: 'mb' }, body), el('footer', null, cancel, ok)));
    back.addEventListener('click', (e) => { if (e.target === back) closeM(); });
    document.body.appendChild(back);
  }
  function addSourceModal() {
    const f = {};
    const inp = (k, ph) => { f[k] = el('input', { class: 'input', placeholder: ph, style: 'width:100%' }); return f[k]; };
    const typeSel = el('select');
    Object.entries(C.TYPE_LABELS).filter(([k]) => k !== 'unknown' && k !== 'social').forEach(([k, v]) => typeSel.appendChild(el('option', { value: k }, v)));
    const tierSel = el('select');
    [1, 2, 3].forEach((v) => tierSel.appendChild(el('option', { value: String(v) }, C.TIERS[v].label)));
    tierSel.value = '2';
    const body = el('div', { class: 'kv' },
      el('label', null, 'Название'), inp('name', 'Например: Институт стратегических исследований'),
      el('label', null, 'Сайт'), inp('domain', 'example.org'),
      el('label', null, 'Страна (код ISO)'), inp('country', 'UZ'),
      el('label', null, 'Языки публикаций'), inp('lang', 'ru, en'),
      el('label', null, 'Тип'), typeSel, el('label', null, 'Уровень'), tierSel,
      el('label', null, 'Лента RSS (необязательно)'), inp('feed', 'https://example.org/feed/'));
    modal('Новый источник', body, async () => {
      const domain = f.domain.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/+$/, '');
      if (!f.name.value.trim() || !domain) { toast('Укажите название и сайт', true); return false; }
      const s = { id: 'user_' + domain.replace(/[^a-z0-9]+/g, '_'), name: f.name.value.trim(), domains: [domain], country: (f.country.value.trim() || 'INT').toUpperCase(),
        lang: splitList(f.lang.value.toLowerCase()).map((x) => x.slice(0, 5)), type: typeSel.value, tier: Number(tierSel.value) };
      if (f.feed.value.trim()) s.feeds = [f.feed.value.trim()];
      return saveAdded([s]);
    });
  }
  async function saveAdded(list) {
    if (!SERVER) { toast('Добавление источников доступно при работе через сервер', true); return false; }
    const have = new Set(userSrc.added.map((x) => x.id));
    for (const s of list) if (!have.has(s.id)) userSrc.added.push(s);
    try {
      await api('/api/sources/user', { method: 'POST', body: userSrc });
      await api('/api/sources/discover', { method: 'POST', body: { ids: list.map((s) => s.id) } });
      toast('Добавлено источников: ' + list.length + '. Каналы проверяются в фоне.');
      renderSources();
      return true;
    } catch (e) { toast('Ошибка: ' + e.message, true); return false; }
  }
  const FOLDER_COUNTRY = { 'индия': 'IN', 'пакистан': 'PK', 'аравия': 'SA', 'англия': 'GB', 'великобритания': 'GB', 'германия': 'DE', 'франция': 'FR', 'сша': 'US', 'китай': 'CN', 'иран': 'IR', 'оаэ': 'AE', 'израиль': 'IL', 'турция': 'TR', 'италия': 'IT', 'корея': 'KR', 'япония': 'JP', 'россия': 'RU', 'узбекистан': 'UZ', 'казахстан': 'KZ', 'испания': 'ES', 'катар': 'QA', 'египет': 'EG' };
  const COUNTRY_LANG = { IN: ['en'], PK: ['en', 'ur'], SA: ['ar', 'en'], GB: ['en'], DE: ['de', 'en'], FR: ['fr', 'en'], US: ['en'], CN: ['zh', 'en'], IR: ['fa', 'en'], AE: ['ar', 'en'], IL: ['he', 'en'], TR: ['tr', 'en'], IT: ['it', 'en'], KR: ['ko', 'en'], JP: ['ja', 'en'], RU: ['ru'], UZ: ['uz', 'ru'], KZ: ['ru', 'kk'], ES: ['es'], QA: ['ar', 'en'], EG: ['ar'] };
  function importBookmarks() {
    const file = el('input', { type: 'file', accept: '.html,.htm' });
    file.addEventListener('change', async () => {
      const f = file.files[0];
      if (!f) return;
      const text = await f.text();
      const doc = new DOMParser().parseFromString(text, 'text/html');
      const found = [];
      const walk = (dl, path) => {
        for (const dt of Array.from(dl.children).filter((x) => x.tagName === 'DT')) {
          const h3 = dt.querySelector(':scope > h3');
          const a = dt.querySelector(':scope > a');
          if (h3) { const sub = dt.querySelector(':scope > dl'); if (sub) walk(sub, path.concat(h3.textContent.trim())); }
          else if (a) found.push({ title: a.textContent.trim(), url: a.getAttribute('href') || '', path });
        }
      };
      const root = doc.querySelector('dl');
      if (!root) { toast('Файл не похож на экспорт закладок браузера', true); return; }
      walk(root, []);
      const cands = [];
      const seen = new Set();
      for (const b of found) {
        const host = C.hostOf(b.url);
        if (!host || seen.has(host) || !/^https?:/.test(b.url)) continue;
        seen.add(host);
        const folder = b.path[b.path.length - 1] || '';
        const inReg = S.registry.lookup(b.url);
        let cc = '';
        for (const [k, v] of Object.entries(FOLDER_COUNTRY)) if (C.normText(folder).includes(k)) cc = v;
        cc = cc || C.tldCountry(host) || 'INT';
        const think = /(institut|center|centre|centro|zentrum|foundation|fondation|stiftung|fondazione|council|академ|институт|центр|研究|연구|مركز|مرکز|enstit|merkez|araştırma|vakf|policy|studies|strateg)/i.test(b.title + ' ' + host);
        cands.push({ b, host, folder, cc, inReg, type: think ? 'think_tank' : 'media_national' });
      }
      const body = el('div');
      body.appendChild(el('p', { class: 'muted' }, 'Найдено ссылок: ' + found.length + ', уникальных сайтов: ' + cands.length + '. Уже в реестре: ' + cands.filter((c) => c.inReg).length + '. Отметьте новые сайты для добавления.'));
      const t = el('table', { class: 'tbl' });
      const boxes = [];
      for (const c of cands) {
        const cb = el('input', { type: 'checkbox' });
        cb.checked = !c.inReg && /аналит|analyt|think|центр/i.test(c.b.path.join(' '));
        cb.disabled = !!c.inReg;
        boxes.push([cb, c]);
        t.appendChild(el('tr', null, el('td', null, cb), el('td', null, c.b.title.slice(0, 70), el('div', { class: 'muted', style: 'font-size:11.5px' }, c.b.path.join(' / '))),
          el('td', { class: 'num' }, c.host), el('td', { class: 'num' }, c.cc), el('td', null, c.inReg ? el('span', { class: 'muted' }, 'в реестре: ' + c.inReg.name) : C.TYPE_LABELS[c.type])));
      }
      body.appendChild(t);
      modal('Импорт закладок', body, () => {
        const list = boxes.filter(([cb]) => cb.checked && !cb.disabled).map(([, c]) => ({
          id: 'user_' + c.host.replace(/[^a-z0-9]+/g, '_'), name: c.b.title.split(/\s[|–—-]\s/)[0].slice(0, 90) || c.host, domains: [c.host],
          country: c.cc, lang: COUNTRY_LANG[c.cc] || ['en'], type: c.type, tier: 2, bm: c.folder.replace(/\.\s*Аналитические центры, издания/i, '') }));
        if (!list.length) { toast('Ничего не выбрано', true); return false; }
        return saveAdded(list);
      }, 'Импортировать');
    });
    file.click();
  }

  // ================================================================ настройки
  async function renderSettings() {
    const p = clear($('#view-settings'));
    p.appendChild(el('h2', null, 'Настройки'));
    const s = S.settings || {};
    const card = el('div', { class: 'card kv' });
    const num = (k, def, min, max) => { const i = el('input', { class: 'input', type: 'number', min: String(min), max: String(max), style: 'width:120px' }); i.value = s[k] != null ? s[k] : def; i.dataset.k = k; return i; };
    const autoN = num('ui_autocheck', 25, 0, 80);
    const verN = num('ui_verify', 40, 0, 100);
    const budget = num('gnews_budget', 120, 10, 300);
    const maxs = num('max_seconds', 300, 60, 900);
    const rw = el('input', { class: 'input', style: 'width:260px', placeholder: 'например: oko-analytics' }); rw.value = s.reliefweb_appname || '';
    const disc = el('input', { type: 'checkbox' }); disc.checked = s.auto_discovery !== false;
    const openChk = el('input', { type: 'checkbox' }); openChk.checked = s.ui_autocheck_open !== false;
    const dens = el('select'); [['full', 'подробно (с аннотациями)'], ['compact', 'компактно']].forEach(([v, l]) => { const o = el('option', { value: v }, l); if (S.density === v) o.selected = true; dens.appendChild(o); });
    card.append(
      el('label', null, 'Автопроверка первоисточников после поиска'), el('div', null, autoN, el('span', { class: 'muted' }, ' материалов (0 — выключить)')),
      el('div', { class: 'hint' }, 'ОКО откроет страницы самых значимых материалов с неясным статусом и проверит canonical, авторов и агентские пометки.'),
      el('label', null, 'Проверка упоминаний темы на страницах'), el('div', null, verN, el('span', { class: 'muted' }, ' материалов после поиска (0 — выключить)')),
      el('div', { class: 'hint' }, 'Для материалов, где тема видна только поисковику: ОКО откроет страницу и посчитает упоминания. Материалы с упоминанием по существу появятся в режиме «Строго по теме».'),
      el('label', null, 'Проверять страницу при открытии карточки'), openChk,
      el('label', null, 'Лимит запросов к Google News за поиск'), budget,
      el('div', { class: 'hint' }, 'Больше — полнее охват длинных периодов, но выше риск временной блокировки Google.'),
      el('label', null, 'Максимальная длительность поиска, с'), maxs,
      el('label', null, 'ReliefWeb: имя приложения (appname)'), rw,
      el('div', { class: 'hint' }, 'Для докладов ООН и НКО через ReliefWeb API нужно бесплатно зарегистрировать appname на apidoc.reliefweb.int.'),
      el('label', null, 'Проверять ленты источников при запуске'), disc,
      el('label', null, 'Вид ленты'), dens);
    const save = el('button', { class: 'btn primary' }, 'СОХРАНИТЬ');
    save.addEventListener('click', async () => {
      S.density = dens.value; store.set('density', S.density);
      const patch = { ui_autocheck: Number(autoN.value), ui_verify: Number(verN.value), gnews_budget: Number(budget.value), max_seconds: Number(maxs.value), reliefweb_appname: rw.value.trim(), auto_discovery: disc.checked, ui_autocheck_open: openChk.checked };
      if (SERVER) { try { S.settings = await api('/api/settings', { method: 'POST', body: patch }); toast('Настройки сохранены'); } catch (e) { toast(e.message, true); } }
      else { Object.assign(S.settings, patch); store.set('settings', S.settings); toast('Сохранено в браузере'); }
      render();
    });
    p.appendChild(card);
    if (SERVER) { p.appendChild(socialSettingsCard(s)); p.appendChild(mobileSettingsCard(s)); }
    const tools = el('div', { class: 'card' });
    tools.appendChild(el('h3', null, 'Данные'));
    if (S.boot) {
      tools.appendChild(el('p', null, 'Папка данных: ', el('code', null, S.boot.data_dir)));
      tools.appendChild(el('p', null, 'Папка PDF: ', el('code', null, S.boot.pdf_dir), S.boot.pdf_browser ? ' — браузер для PDF найден' : ' — браузер Chrome/Edge не найден: PDF через «Режим чтения → Печать»'));
    }
    const cc = el('button', { class: 'btn' }, 'Очистить кэш ответов');
    cc.addEventListener('click', async () => { if (!SERVER) return; await api('/api/cache/clear', { method: 'POST', body: {} }); toast('Кэш очищен'); });
    const hist = el('button', { class: 'btn' }, 'Очистить историю запросов');
    hist.addEventListener('click', () => { S.history = []; saveHistory(); toast('История очищена'); });
    tools.append(cc, ' ', hist);
    p.append(el('div', { style: 'margin:0 0 14px' }, save), tools);
  }

  function keyInput(s, k, ph) {
    const i = el('input', { class: 'input', type: k === 'gcse_cx' ? 'text' : 'password', placeholder: s[k + '_set'] ? 'задан (' + (s[k] || '') + ') — введите новый, чтобы заменить' : ph, style: 'width:100%;max-width:420px', autocomplete: 'off' });
    if (k === 'gcse_cx') i.value = s[k] || '';
    i.dataset.k = k;
    return i;
  }
  function socialSettingsCard(s) {
    const card = el('div', { class: 'card' });
    card.appendChild(el('h3', null, 'Соцсети и ключи API'));
    card.appendChild(el('p', { class: 'muted', style: 'font-size:12.5px' }, 'Результаты из соцсетей показываются отдельно — вкладка «Соцсети» над лентой. Без ключей работают публичные Telegram-каналы. Ключи хранятся только на этом компьютере (data/state/settings.json).'));
    // Telegram-каналы
    const chBox = el('div', { class: 'tchips', style: 'margin:6px 0' });
    const chans = (S.social && S.social.channels) || [];
    const defaults = new Set((S.social && S.social.default_channels) || []);
    for (const c of chans) {
      const rm = el('button', { title: 'Убрать канал' }, '×');
      rm.addEventListener('click', async () => {
        const patch = defaults.has(c.id) ? { tg_channels_off: (S.settings.tg_channels_off || []).concat([c.id]) }
          : { tg_channels_add: (S.settings.tg_channels_add || []).filter((x) => x.id !== c.id) };
        await saveSettings(patch); await loadSocial(''); renderSettings();
      });
      chBox.appendChild(el('span', { class: 'tchip tg', title: 't.me/' + c.id + (c.lang ? ' · ' + c.lang : '') }, (c.name || c.id) + ' @' + c.id, rm));
    }
    const chIn = el('input', { class: 'input', placeholder: '@канал или ссылка t.me/…', style: 'width:220px' });
    const chLang = el('select'); for (const l of ['ru', 'uz', 'en', 'kk', 'tg', 'ky', 'tr', 'fa', 'ar', 'zh']) chLang.appendChild(el('option', { value: l }, l.toUpperCase()));
    const chAdd = el('button', { class: 'btn small' }, 'Добавить канал');
    chAdd.addEventListener('click', async () => {
      const v = chIn.value.trim().replace(/^(https?:\/\/)?(www\.)?(t\.me|telegram\.me)\/(s\/)?/, '').replace(/^@/, '').split(/[/?]/)[0];
      if (!/^[A-Za-z][A-Za-z0-9_]{3,31}$/.test(v)) { toast('Некорректное имя канала', true); return; }
      const off = (S.settings.tg_channels_off || []).filter((x) => x.toLowerCase() !== v.toLowerCase());
      await saveSettings({ tg_channels_add: (S.settings.tg_channels_add || []).filter((x) => x.id !== v).concat([{ id: v, name: '@' + v, lang: chLang.value }]), tg_channels_off: off });
      await loadSocial(''); renderSettings();
    });
    card.append(el('div', { class: 'kv' }, el('label', null, 'Telegram-каналы (публичные)'), el('div', null, chBox, el('div', { class: 'ptool' }, chIn, chLang, chAdd),
      el('div', { class: 'muted', style: 'font-size:12px' }, 'ОКО ищет по теме внутри каждого канала через веб-версию t.me/s. Закрытые каналы и группы недоступны. Глобальный поиск по всему Telegram — только в приложении Telegram.'))));
    const kv = el('div', { class: 'kv', style: 'margin-top:12px' });
    const inputs = [];
    const add = (label, k, ph, hint) => { const i = keyInput(s, k, ph); inputs.push(i); kv.append(el('label', null, label), i); if (hint) kv.appendChild(el('div', { class: 'hint' }, hint)); };
    add('ВКонтакте: сервисный ключ', 'vk_token', 'сервисный ключ доступа приложения VK', 'dev.vk.com → «Мои приложения» → создать приложение → «Сервисный ключ доступа». Поиск по открытым записям (newsfeed.search).');
    add('X (Twitter): Bearer Token', 'x_bearer', 'Bearer Token', 'developer.x.com — поиск доступен в платных тарифах API (Basic и выше), последние 7 дней.');
    add('Brave Search API: ключ', 'brave_key', 'ключ Brave Search API', 'api-dashboard.search.brave.com — бесплатный тариф (≈2000 запросов в месяц). Ищет публичные публикации LinkedIn, Facebook, Instagram, X, VK, Telegram и WhatsApp-каналы.');
    add('Google Programmable Search: ключ', 'gcse_key', 'API key', 'Альтернатива Brave: programmablesearchengine.google.com (поисковик по всему вебу) + ключ Custom Search API в console.cloud.google.com; 100 запросов в день бесплатно.');
    add('Google Programmable Search: cx', 'gcse_cx', 'идентификатор поисковой системы (cx)', '');
    add('YouTube Data API: ключ', 'youtube_key', 'API key', 'console.cloud.google.com → YouTube Data API v3 → ключ (бесплатная квота).');
    add('DeepL: ключ (перевод)', 'deepl_key', 'ключ DeepL API (…:fx — бесплатный)', 'Необязательно: более качественный перевод статей на русский. Без ключа используется Google Переводчик.');
    card.appendChild(kv);
    const plats = el('div', { class: 'ptool' });
    const want = new Set(s.social_platforms || ['telegram', 'x', 'linkedin', 'facebook', 'instagram', 'vk', 'whatsapp']);
    const pcb = {};
    for (const [pid, pl] of Object.entries((S.social && S.social.platforms) || {})) {
      if (pid === 'youtube') continue;
      const cb = el('input', { type: 'checkbox' }); cb.checked = want.has(pid); pcb[pid] = cb;
      plats.appendChild(el('label', { class: 'check', title: pl.note || '' }, cb, ' ' + pl.name));
    }
    card.append(el('div', { class: 'muted', style: 'margin:10px 0 4px' }, 'Платформы для поиска через Brave / Google:'), plats);
    const save = el('button', { class: 'btn primary' }, 'СОХРАНИТЬ КЛЮЧИ');
    save.addEventListener('click', async () => {
      const patch = { social_platforms: Object.entries(pcb).filter(([, cb]) => cb.checked).map(([k]) => k) };
      for (const i of inputs) { if (i.value.trim() || i.dataset.k === 'gcse_cx') patch[i.dataset.k] = i.value.trim(); }
      await saveSettings(patch); await loadSocial(''); renderProvMenu(); renderSettings();
    });
    const clr = el('button', { class: 'btn small' }, 'Удалить все ключи');
    clr.addEventListener('click', async () => {
      if (!confirm('Удалить все сохранённые ключи API?')) return;
      await saveSettings({ vk_token: '', x_bearer: '', brave_key: '', gcse_key: '', gcse_cx: '', youtube_key: '', deepl_key: '' }); await loadSocial(''); renderSettings();
    });
    card.appendChild(el('div', { class: 'ptool', style: 'margin-top:10px' }, save, clr));
    return card;
  }
  function mobileSettingsCard(s) {
    const card = el('div', { class: 'card' });
    card.appendChild(el('h3', null, 'Телефон: Telegram-бот и доступ из браузера'));
    const kv = el('div', { class: 'kv' });
    const tok = keyInput(s, 'tg_bot_token', 'токен от @BotFather');
    const ids = el('input', { class: 'input', placeholder: 'ваш Telegram ID (узнать: напишите боту /start)', style: 'width:100%;max-width:420px' });
    ids.value = (s.tg_bot_allowed || []).join(', ');
    const topic = el('input', { class: 'input', style: 'width:260px' }); topic.value = s.tg_bot_topic || 'Узбекистан';
    const dig = el('input', { class: 'input', type: 'time', style: 'width:120px' });
    const d0 = (s.tg_bot_digest || [])[0]; dig.value = d0 ? d0.time : '';
    const lan = keyInput(s, 'lan_password', 'пароль для входа с телефона (не короче 8 символов)');
    kv.append(el('label', null, 'Токен Telegram-бота'), tok, el('div', { class: 'hint' }, 'Создайте бота у @BotFather, вставьте токен. Бот отвечает только разрешённым ID: присылает сводки, ищет по команде, следит за мониторингом.'),
      el('label', null, 'Разрешённые Telegram ID'), ids,
      el('label', null, 'Тема по умолчанию'), topic,
      el('label', null, 'Ежедневная сводка в'), el('div', null, dig, el('span', { class: 'muted' }, ' (пусто — не присылать)')),
      el('label', null, 'Пароль доступа с телефона'), lan, el('div', { class: 'hint' }, 'Запустите ОКО командой «python oko.py --lan» — интерфейс откроется на телефоне в той же Wi-Fi-сети по адресу, который покажет окно ОКО. Вход по паролю; можно «Добавить на главный экран».'));
    const st = el('div', { class: 'muted', style: 'font-size:12.5px;margin-top:6px' });
    api('/api/bot/status').then((b) => { st.textContent = 'Бот: ' + (b.running ? 'работает' + (b.username ? ' (@' + b.username + ')' : '') : (b.error ? 'ошибка — ' + b.error : 'не запущен')) + (b.lan ? ' · доступ с телефона: ' + b.lan : ''); }).catch(() => {});
    const save = el('button', { class: 'btn primary' }, 'СОХРАНИТЬ');
    save.addEventListener('click', async () => {
      const allowed = splitList(ids.value).map((x) => x.replace(/[^0-9-]/g, '')).filter(Boolean).map(Number);
      const patch = { tg_bot_allowed: allowed, tg_bot_topic: topic.value.trim() || 'Узбекистан', tg_bot_digest: dig.value ? [{ time: dig.value, topic: topic.value.trim() || 'Узбекистан' }] : [] };
      if (tok.value.trim()) patch.tg_bot_token = tok.value.trim();
      if (lan.value.trim()) { if (lan.value.trim().length < 8) { toast('Пароль — не короче 8 символов', true); return; } patch.lan_password = lan.value.trim(); }
      await saveSettings(patch);
      try { await api('/api/bot/restart', { method: 'POST', body: {} }); } catch (e) { /* бот может быть не настроен */ }
      renderSettings();
    });
    card.append(kv, st, el('div', { class: 'ptool', style: 'margin-top:10px' }, save));
    card.appendChild(el('p', { class: 'muted', style: 'font-size:12.5px' }, 'Отдельное APK-приложение не требуется: на Android ОКО можно запустить прямо на телефоне через Termux (см. README → «ОКО на телефоне»), либо пользоваться ботом или браузером телефона.'));
    return card;
  }
  async function saveSettings(patch) {
    if (!SERVER) { Object.assign(S.settings, patch); store.set('settings', S.settings); return; }
    try { S.settings = await api('/api/settings', { method: 'POST', body: patch }); toast('Сохранено'); }
    catch (e) { toast('Не сохранено: ' + e.message, true); }
  }

  // ================================================================ справка
  function renderHelp() {
    const p = clear($('#view-help'));
    const sec = (t, open, ...c) => { const d = el('details', { class: 'card' }); d.open = !!open; d.append(el('summary', null, el('h3', { style: 'display:inline' }, t)), ...c); return d; };
    p.appendChild(el('h2', null, 'Справка ОКО'));
    const legend = el('div', { class: 'legend' });
    for (const t of [1, 2, 3, 4]) legend.append(tierBadge(t), el('div', null, el('b', null, C.TIERS[t].label), ' — ', C.TIERS[t].desc));
    const ol = el('div', { class: 'legend' });
    ol.append(originBadge({ status: 'primary' }), el('div', null, el('b', null, 'Первоисточник (оригинал)'), ' — собственный материал издания или организации: аналитика, официальное заявление, доклад, научная публикация, агентская новость; либо самая ранняя из совпадающих публикаций.'),
      originBadge({ status: 'reprint' }), el('div', null, el('b', null, 'Перепубликация'), ' — ссылается на другое издание («по данным Reuters», «(AFP)», «сообщает ТАСС»), совпадает с более ранней публикацией, размещена агрегатором, пересланный пост в соцсетях или страница указывает первоисточник (rel=canonical).'),
      originBadge({ status: 'unknown' }), el('div', null, el('b', null, 'Не определено'), ' — признаков недостаточно; «Проверить первоисточник» изучит страницу.'));
    p.append(
      sec('Вкладки поиска', true, el('ul', null,
        el('li', null, el('b', null, 'Тематика'), ' — страна, регион, организация или явление (по умолчанию «Узбекистан»). Направления (экономика, энергетика, безопасность, внешняя политика…) сужают поиск: материал должен касаться темы и одного из направлений. Термины переводятся на все выбранные языки.'),
        el('li', null, el('b', null, 'Ключевые слова'), ' — любые слова: «и» (должно быть также), «не» (исключить), точная фраза, поиск без перевода.'),
        el('li', null, el('b', null, 'Персоны'), ' — человек из Wikidata: должности, гражданство, официальные аккаунты, имя на всех языках; затем — упоминания в СМИ и соцсетях.'),
        el('li', null, el('b', null, 'OSINT'), ' — e-mail, телефон, @имя, домен, ссылка, IP: DNS, WHOIS (RDAP), публичные профили, веб-архив, упоминания в поисковиках. Только открытые данные — без утечек и «пробива».'),
        el('li', null, el('b', null, 'Доклады'), ' — новые выпуски глобальных докладов и индексов (ООН, МВФ, Всемирный банк, ЕС, ОЭСР, ВОЗ, WEF, IEP, SIPRI, Freedom House, RIAC и др.) и календарь ожидаемых выпусков.'))),
      sec('Почему материал в выдаче', true, el('p', null, 'Над карточкой — блок «Найдено по»: исходное ключевое слово, сработавший термин (перевод, словоформа, связанный термин — столица, глава государства, город), где он найден (заголовок, аннотация, текст страницы) и запрос, которым материал найден. Термин подсвечен в заголовке. В ленте — метка ⌕.'),
        el('p', null, 'Режим «Строго по теме» (включён по умолчанию) скрывает материалы, где тема видна только поисковику — часто это упоминание вскользь или ссылка «читайте также». ОКО само открывает такие страницы, считает абзацы с упоминанием и возвращает в ленту те, где тема раскрыта; в карточке — цитата.')),
      sec('Уровни авторитетности', false, legend, el('p', { class: 'muted' }, 'Уровень задаётся реестром (' + S.sources.length + ' источников, включая все аналитические центры и издания из ваших закладок) и меняется в разделе «Источники». Официальные домены (.gov, .int и т. п.) распознаются автоматически.')),
      sec('Первоисточник или перепубликация', false, ol, el('p', { class: 'muted' }, 'Статус определяется эвристически и всегда сопровождается обоснованием и степенью уверенности.')),
      sec('Соцсети', false, el('p', null, 'Результаты из соцсетей — отдельно, переключатель «Соцсети» над лентой. Без ключей ОКО ищет по публичным Telegram-каналам (список — в Настройках, можно добавить свои). ВКонтакте, X, YouTube и поиск публичных публикаций LinkedIn, Facebook, Instagram и WhatsApp-каналов через Brave или Google подключаются ключами API в «Настройки → Соцсети и ключи API».'),
        el('p', { class: 'muted' }, 'Переписка в WhatsApp зашифрована и недоступна никому — видны только публичные каналы. Закрытые группы и личные страницы ОКО не собирает.')),
      sec('Мониторинг источников', false, el('p', null, 'Отметьте источники значком «глаз» (в «Источниках» или «Следить за источником» в карточке) или добавьте Telegram-каналы. Раздел «Мониторинг» → «Обновить» покажет свежие публикации по источникам с отметкой новых. «Досье» — избранные материалы с заметками.')),
      sec('Перевод на русский', false, el('p', null, 'Карточка материала на другом языке сразу показывает перевод заголовка и аннотации; «Перевести полный текст» переводит статью прямо в карточке, «PDF перевода» — сохраняет перевод. В меню «Вид» можно включить «Заголовки по-русски» для всей ленты. Для лучшего качества укажите ключ DeepL в настройках.')),
      sec('Ошибки каналов', false, el('p', null, 'Счётчик «Ошибок» и «Журнал» показывают, какой канал не ответил, почему и что делать; «Скопировать отчёт об ошибках» — для пересылки разработчику. Каналы, которые падают несколько поисков подряд, ОКО временно отключает и потом проверяет снова (список — «Источники → Каналы с ошибками»). Если Google, GDELT или Bing ограничили частоту запросов, оставшиеся запросы помечаются «пропущено» — повторите поиск через 10–15 минут.')),
      sec('Телефон', false, el('ul', null,
        el('li', null, el('b', null, 'Telegram-бот'), ': создайте бота у @BotFather, вставьте токен и свой Telegram ID в «Настройки → Телефон». Напишите боту тему — он пришлёт самые авторитетные материалы и HTML-сводку; /digest 08:30 — ежедневная сводка.'),
        el('li', null, el('b', null, 'Браузер телефона'), ': задайте пароль, запустите «python oko.py --lan» — адрес для телефона появится в окне ОКО; в меню браузера — «Добавить на главный экран».'),
        el('li', null, el('b', null, 'Android без компьютера'), ': ОКО запускается в Termux (см. README).'))),
      sec('PDF и сохранение', false, el('p', null, '«PDF оригинала» сохраняет страницу через Chrome/Edge (папка pdf). «PDF (режим чтения)» — чистый текст с метаданными. «Экспорт → PDF-сводка» — отчёт по ленте. «Сохранить в веб-архив» фиксирует копию страницы в Wayback Machine.')),
      sec('Ограничения', false, el('ul', null, el('li', null, 'GDELT хранит около 3 месяцев; Bing News — около месяца; поиск X — 7 дней; Google News и сайты источников — без ограничения периода.'),
        el('li', null, 'RSS-ленты содержат только свежие материалы; для прошлых периодов работают поисковые системы и поиск по сайтам.'),
        el('li', null, 'Платный контент: видны заголовок, издание, дата и ссылка; текст может быть недоступен для чтения и перевода.'))),
      sec('Клавиши', false, el('p', null, el('code', null, '/'), ' — к строке поиска · ', el('code', null, 'Enter'), ' — найти · ', el('code', null, 'J'), '/', el('code', null, 'K'), ' — следующий/предыдущий · ', el('code', null, 'O'), ' — открыть оригинал · ', el('code', null, 'S'), ' — в досье · ', el('code', null, 'C'), ' — проверить первоисточник · ', el('code', null, 'Esc'), ' — закрыть карточку')));
  }

  // ================================================================ экспорт и сводка
  function exportRows(items) {
    return items.map((it) => ({
      'Дата (местн.)': fmtDate(it.ts), 'Дата UTC': fmtUTC(it.ts), 'Уровень': (C.TIERS[it.tier] || C.TIERS[4]).code,
      'Статус': ORIGIN_LABEL[it.origin ? it.origin.status : 'unknown'], 'Основание': it.origin ? it.origin.reason : '',
      'Первоисточник': it.origin && it.origin.credited ? it.origin.credited.label || '' : '', 'Заголовок': it.title,
      'Издание': it.srcName || '', 'Сайт': it.domain || '', 'Страна': it.country || '', 'Язык': it.lang || '',
      'Тип': C.TYPE_LABELS[it.type] || '', 'Доступ': it.paywall ? C.PAYWALL_LABELS[it.paywall] : 'свободный',
      'Гос.': it.state === 'control' ? 'гос. СМИ' : (it.state === 'public' ? 'гос. финанс.' : ''), 'Авторы': (it.authors || []).join(', '),
      'Ссылка': it.resolved || it.url, 'Найдено по': foundByText(it), 'Соответствие': C.REL_LABELS[it.rel] || '', 'Найдено через': (it.via || []).join('; '), 'Заметка': it.note || ''
    }));
  }
  function toCSV(items) {
    const rows = exportRows(items);
    if (!rows.length) return '';
    const cols = Object.keys(rows[0]);
    const esc = (v) => { const s = String(v == null ? '' : v); return /[";\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    return '﻿' + [cols.join(';')].concat(rows.map((r) => cols.map((c) => esc(r[c])).join(';'))).join('\r\n');
  }
  function h(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function reportHtml(items, title) {
    const q = queryParts();
    const per = S.params ? fmtDate(S.params.t_from) + ' — ' + fmtDate(S.params.t_to) + ' (' + tzLabel() + ')' : '';
    const byTier = [1, 2, 3, 4].map((t) => items.filter((x) => (x.tier || 4) === t));
    const cnt = (st) => items.filter((x) => x.origin && x.origin.status === st).length;
    const countries = {};
    items.forEach((x) => { const k = x.country || '—'; countries[k] = (countries[k] || 0) + 1; });
    const topC = Object.entries(countries).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, n]) => h(countryName(k)) + ' — ' + n).join(' · ');
    let body = '';
    let n = 0;
    byTier.forEach((grp, i) => {
      if (!grp.length) return;
      const T = C.TIERS[i + 1];
      body += '<h2>Уровень ' + h(T.label) + ' · ' + grp.length + '</h2>';
      for (const x of grp) {
        n++;
        const st = x.origin ? x.origin.status : 'unknown';
        const mark = st === 'primary' ? '✔ Первоисточник' : st === 'reprint' ? '⟳ Перепубликация' + (x.origin.credited && x.origin.credited.label ? ' (' + h(x.origin.credited.label) + ')' : '') : '? Не определено';
        const u = safeUrl(x.resolved || x.url) || '';
        body += '<div class="it"><div class="n">' + n + '</div><div><a class="t" href="' + h(u) + '" lang="' + h(x.lang || '') + '" dir="auto">' + h(x.title) + '</a>' +
          '<div class="m">' + h(x.srcName || x.domain) + ' · ' + h(countryName(x.country)) + ' · ' + h((x.lang || '').toUpperCase()) + ' · ' + h(fmtDate(x.ts)) +
          (x.paywall ? ' · платный' : '') + (x.state === 'control' ? ' · гос. СМИ' : '') + '</div>' +
          '<div class="s ' + st + '">' + mark + '</div>' + ((x.authors || []).length ? '<div class="m">Авторы: ' + h(x.authors.join(', ')) + '</div>' : '') +
          (x.term || x.kw ? '<div class="m">Найдено по: ' + h(foundByText(x)) + '</div>' : '') +
          (x.note ? '<div class="note">Заметка: ' + h(x.note) + '</div>' : '') + '<div class="u">' +
          (/news\.google\.com\//.test(u) ? h(x.domain || '') + ' — ссылка через Google News' : h(u)) + '</div></div></div>';
      }
    });
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>' + h(title) + ' — ОКО</title>' +
      '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=Noto+Naskh+Arabic&family=Noto+Sans+SC&family=Noto+Sans+JP&family=Noto+Sans+KR&display=swap">' +
      '<style>body{font:13px/1.5 "IBM Plex Sans","Noto Naskh Arabic","Noto Sans SC","Noto Sans JP","Noto Sans KR",Arial,sans-serif;color:#111;max-width:900px;margin:24px auto;padding:0 18px}' +
      'header{border-bottom:2px solid #111;padding-bottom:10px;margin-bottom:14px}.k{letter-spacing:.3em;font-weight:600;color:#8a6d1d}h1{font-size:22px;margin:6px 0}' +
      '.sum{background:#f4f5f7;padding:10px 12px;border-radius:4px;font-size:12.5px}h2{font-size:14px;margin:22px 0 6px;border-bottom:1px solid #ccc;padding-bottom:4px}' +
      '.it{display:grid;grid-template-columns:34px 1fr;padding:7px 0;border-bottom:1px solid #eee;break-inside:avoid}.n{color:#888;font-size:12px}' +
      'a.t{color:#111;font-weight:600;text-decoration:none;unicode-bidi:plaintext}.m{color:#555;font-size:12px}.s{font-size:12px;font-weight:600}.s.primary{color:#137a53}.s.reprint{color:#a86a00}.s.unknown{color:#777}' +
      '.u{color:#1f4f8f;font-size:11px;word-break:break-all}.note{font-size:12px;background:#fff8e1;padding:3px 6px;margin-top:3px}footer{margin-top:24px;color:#777;font-size:11px}</style></head><body>' +
      '<header><div class="k">ОКО</div><h1>' + h(title) + '</h1><div>Тема: <b>' + h(q.topics.join(', ')) + '</b>' + (q.context.length ? ' · контекст: ' + h(q.context.join(', ')) : '') +
      (per ? ' · период: ' + h(per) : '') + '</div><div>Сформировано: ' + h(fmtDate(Date.now() / 1000)) + ' · языки: ' + h([...S.langOn].join(', ').toUpperCase()) + '</div></header>' +
      '<div class="sum">Материалов: <b>' + items.length + '</b> · первоисточников: <b>' + cnt('primary') + '</b> · перепубликаций: <b>' + cnt('reprint') + '</b> · не определено: <b>' + cnt('unknown') + '</b>' +
      '<br>По уровням: ' + byTier.map((g, i) => C.TIERS[i + 1].code + ' — ' + g.length).join(' · ') + (topC ? '<br>Страны изданий: ' + topC : '') + '</div>' + body +
      '<footer>Сформировано платформой ОКО. Статусы «первоисточник/перепубликация» определены автоматически с указанием оснований; проверяйте ключевые материалы по оригиналу.</footer></body></html>';
  }
  function printDigest(items, title) {
    if (!items.length) { toast('Нет материалов для сводки', true); return; }
    const w = window.open('', '_blank');
    if (!w) { toast('Разрешите всплывающие окна для печати', true); return; }
    w.document.open();
    w.document.write(reportHtml(items, title));
    w.document.close();
    setTimeout(() => { try { w.focus(); w.print(); } catch (e) { /* пользователь напечатает сам */ } }, 900);
  }
  function renderExportMenu() {
    const m = clear($('#menuExport'));
    const name = 'OKO_' + (((S.params && S.params.topics) || [])[0] || (S.params && S.params.mode) || 'monitoring').replace(/[^\p{L}\p{N}]+/gu, '_') + '_' + isoDate(new Date());
    const mi = (label, fn) => { const b = el('button', { class: 'mi' }, label); b.addEventListener('click', () => { m.classList.add('hidden'); fn(); }); return b; };
    m.append(el('div', { class: 'mh' }, 'Текущая выборка (' + visible.length + ')'),
      mi('CSV для Excel', () => download(name + '.csv', toCSV(visible), 'text/csv;charset=utf-8')),
      mi('HTML-отчёт (файл)', () => download(name + '.html', reportHtml(visible, 'Мониторинг: ' + (splitList($('#qTopic').value).join(', ') || '')), 'text/html;charset=utf-8')),
      mi('JSON (все данные)', () => download(name + '.json', JSON.stringify(visible.map((x) => { const y = Object.assign({}, x); delete y.meta; return y; }), null, 1), 'application/json')),
      el('hr'), mi('PDF-сводка (печать / сохранить в PDF)', () => printDigest(visible, (S.params && S.params.title) || ('Мониторинг: ' + ((S.params && S.params.topics) || []).join(', ')))),
      mi('Только первоисточники → CSV', () => download(name + '_primary.csv', toCSV(visible.filter((x) => x.origin && x.origin.status === 'primary')), 'text/csv;charset=utf-8')));
  }

  // ================================================================ вкладки запроса
  const TAB_PH = {
    topic: 'Страна, регион, организация или явление — например: Узбекистан',
    keywords: 'Ключевые слова через запятую (любое из них)',
    person: 'Имя и фамилия — например: Шавкат Мирзиёев',
    osint: 'e-mail, +998…, @имя, домен, ссылка или IP',
    reports: 'необязательно: тема для отбора (например, Узбекистан)'
  };
  const TAB_DEF = { topic: 'Узбекистан', keywords: '', person: '', osint: '', reports: '' };
  function switchTab(t) {
    S.qvals[S.qtab] = $('#qTopic').value;
    S.qtab = t;
    store.set('qtab', t);
    store.set('qvals', S.qvals);
    $$('#qtabs button').forEach((b) => b.classList.toggle('on', b.dataset.t === t));
    for (const k of ['topic', 'keywords', 'person', 'osint', 'reports']) $('#qx-' + k).classList.toggle('hidden', k !== t);
    const v = S.qvals[t] !== undefined ? S.qvals[t] : TAB_DEF[t];
    $('#qTopic').value = v;
    $('#qTopic').placeholder = TAB_PH[t];
    $('#btnSearch').textContent = S.running ? 'ПОИСК…' : (t === 'osint' ? 'ПРОВЕРИТЬ' : 'НАЙТИ');
    $('#qline').classList.toggle('hidden', t === 'osint');
    $('#qparams').classList.add('hidden');
    S.expansion = null;
    if (t === 'reports') renderReportsBox();
    if (t === 'person') renderPersonBox();
    paramsSummary();
  }
  function renderThemeChips() {
    const box = clear($('#themeChips'));
    const all = (S.boot && S.boot.themes) || (D.lexicon || []).filter((e) => e.kind === 'theme').map((e) => ({ id: e.id, label: e.label }));
    for (const t of all) {
      const on = S.themes.has(t.id);
      const chip = el('span', { class: 'chip theme' + (on ? ' on' : ''), title: on ? 'Убрать направление' : 'Искать только материалы по этому направлению (термины на всех языках)' }, t.label);
      chip.addEventListener('click', () => {
        if (S.themes.has(t.id)) S.themes.delete(t.id); else S.themes.add(t.id);
        store.set('themes', [...S.themes]);
        S.expansion = null;
        renderThemeChips();
      });
      box.appendChild(chip);
    }
    if (S.themes.size) {
      const clr = el('span', { class: 'chip', title: 'Все направления' }, '× сбросить');
      clr.addEventListener('click', () => { S.themes.clear(); store.set('themes', []); S.expansion = null; renderThemeChips(); });
      box.appendChild(clr);
    }
    box.appendChild(el('span', { class: 'muted', style: 'font-size:11.5px' }, S.themes.size ? 'материал должен касаться темы и одного из направлений' : 'без выбора — все направления'));
  }
  function paramsSummary() {
    const n = S.langOn.size;
    const parts = [n + ' ' + plural(n, 'язык', 'языка', 'языков'), S.mode === 'registry' ? 'аналитика и авторитетные' : 'широкий охват'];
    if (S.minTier < 4) parts.push('уровень ' + { 1: 'A', 2: 'A–B', 3: 'A–C' }[S.minTier]);
    if (S.types.size) parts.push('категорий: ' + S.types.size);
    const open = !$('#qparams').classList.contains('hidden');
    $('#btnParams').textContent = 'Параметры: ' + parts.join(' · ') + (open ? ' ▴' : ' ▾');
  }

  // ---------------------------------------------------------------- персоны
  function renderPersonBox() {
    const box = clear($('#personBox'));
    if (S.person) {
      const p = S.person;
      const card = el('div', { class: 'pcard' });
      const back = el('button', { class: 'linkbtn' }, '← другой человек');
      back.addEventListener('click', () => { S.person = null; renderPersonBox(); });
      card.appendChild(el('div', { class: 'pc-h' }, el('b', null, p.label), p.born ? el('span', { class: 'muted' }, ' · род. ' + p.born) : null, p.died ? el('span', { class: 'muted' }, ' · ум. ' + p.died) : null, ' ', back));
      if (p.description) card.appendChild(el('div', { class: 'muted' }, p.description));
      const pos = (p.positions || []).slice().reverse().slice(0, 6);
      if (pos.length) card.appendChild(el('div', { class: 'pc-row' }, el('span', { class: 'fb-k' }, 'Должности'), el('span', null, pos.map((x) => x.label + (x.from ? ' (' + x.from.slice(0, 4) + (x.to ? '–' + x.to.slice(0, 4) : '–н.в.') + ')' : '')).join('; '))));
      if ((p.citizenship || []).length) card.appendChild(el('div', { class: 'pc-row' }, el('span', { class: 'fb-k' }, 'Гражданство'), el('span', null, p.citizenship.map((x) => x.label).join(', '))));
      const links = el('span', { class: 'pc-links' });
      for (const sx of p.socials || []) links.appendChild(extLink(sx.url, sx.name + ': ' + sx.handle, 'btn small ghost'));
      for (const w of p.websites || []) links.appendChild(extLink(w, 'сайт: ' + C.hostOf(w), 'btn small ghost'));
      for (const w of p.wikipedia || []) links.appendChild(extLink(w.url, 'Википедия (' + w.lang + ')', 'btn small ghost'));
      links.appendChild(extLink(p.wikidata, 'Wikidata ' + p.id, 'btn small ghost'));
      card.appendChild(el('div', { class: 'pc-row' }, el('span', { class: 'fb-k' }, 'Аккаунты и страницы'), links));
      const names = Object.entries(p.names || {}).map(([k, v]) => k.toUpperCase() + ': ' + v[0]).slice(0, 14).join(' · ');
      card.appendChild(el('div', { class: 'pc-row' }, el('span', { class: 'fb-k' }, 'Имя на языках'), el('span', { class: 'muted' }, names)));
      const go = el('button', { class: 'btn primary small' }, 'ИСКАТЬ УПОМИНАНИЯ');
      go.addEventListener('click', () => runSearch());
      card.appendChild(el('div', { class: 'ptool', style: 'margin-top:8px' }, go, el('span', { class: 'muted', style: 'font-size:12px' }, 'СМИ и аналитика на всех выбранных языках + соцсети (вкладка «Соцсети» в результатах)')));
      box.appendChild(card);
      return;
    }
    if (S.personCands.length) {
      box.appendChild(el('div', { class: 'muted', style: 'margin-bottom:4px' }, 'Выберите человека:'));
      for (const c of S.personCands) {
        const b = el('button', { class: 'pcand' }, el('b', null, c.label), c.born ? el('span', { class: 'muted' }, ' · ' + c.born.slice(0, 4)) : null, c.description ? el('span', { class: 'muted' }, ' — ' + c.description) : null);
        b.addEventListener('click', () => selectPerson(c.id));
        box.appendChild(b);
      }
      const plain = el('button', { class: 'linkbtn' }, 'Нет в списке — искать имя как ключевое слово');
      plain.addEventListener('click', () => { S.person = { id: '', label: $('#qTopic').value.trim(), names: {} }; runSearch(); });
      box.appendChild(plain);
      return;
    }
    box.appendChild(el('span', { class: 'muted' }, 'Введите имя и нажмите «НАЙТИ» — ОКО найдёт человека в Wikidata, покажет должности и аккаунты и соберёт упоминания на всех языках. Только публичные лица и открытые данные.'));
  }
  async function personSearch() {
    const q = $('#qTopic').value.trim();
    if (q.length < 2) { toast('Введите имя', true); return; }
    if (!SERVER) { S.person = { id: '', label: q, names: {} }; return runSearch(); }
    clear($('#personBox')).appendChild(el('span', { class: 'muted' }, el('span', { class: 'spinner' }), ' ищу в Wikidata…'));
    try {
      S.personCands = (await api('/api/person/search?q=' + encodeURIComponent(q))).candidates || [];
      if (!S.personCands.length) { S.person = { id: '', label: q, names: {} }; toast('В Wikidata не найдено — ищу имя как ключевое слово'); return runSearch(); }
      if (S.personCands.length === 1) return selectPerson(S.personCands[0].id);
      renderPersonBox();
    } catch (e) { toast('Wikidata: ' + e.message, true); renderPersonBox(); }
  }
  async function selectPerson(qid) {
    clear($('#personBox')).appendChild(el('span', { class: 'muted' }, el('span', { class: 'spinner' }), ' загружаю профиль…'));
    try { S.person = await api('/api/person/' + qid); S.expansion = null; renderPersonBox(); }
    catch (e) { toast('Профиль: ' + e.message, true); renderPersonBox(); }
  }

  // ---------------------------------------------------------------- OSINT
  async function osintRun() {
    const v = $('#qTopic').value.trim();
    const box = clear($('#osintBox'));
    if (!v) { toast('Введите e-mail, телефон, @имя, домен, ссылку или IP', true); return; }
    if (!SERVER) { box.appendChild(el('span', { class: 'muted' }, 'OSINT-проверки работают при запуске ОКО через сервер (START_OKO).')); return; }
    box.appendChild(el('span', { class: 'muted' }, el('span', { class: 'spinner' }), ' проверяю по открытым источникам…'));
    let r;
    try { r = await api('/api/osint', { method: 'POST', body: { value: v } }); } catch (e) { clear(box).appendChild(el('span', { class: 'muted' }, 'Ошибка: ' + e.message)); return; }
    S.osint = r;
    renderOsint();
  }
  function renderOsint() {
    const r = S.osint;
    const box = clear($('#osintBox'));
    if (!r) return;
    const TYPE = { email: 'E-mail', phone: 'Телефон', username: 'Имя пользователя', domain: 'Домен', url: 'Ссылка', ip: 'IP-адрес' };
    box.appendChild(el('div', { class: 'oh' }, el('b', null, (TYPE[r.type] || 'Не распознано') + ': '), el('span', { class: 'mono' }, r.value)));
    if (r.facts.length) {
      const t = el('table', { class: 'dtable', style: 'margin:6px 0;width:100%' });
      for (const f of r.facts) t.appendChild(el('tr', null, el('th', null, f.k), el('td', null, f.v)));
      box.appendChild(t);
    }
    if (r.checks.length) {
      const ul = el('div', { class: 'ochecks' });
      const ST = { ok: '✓', found: '●', none: '○', warn: '!', unknown: '?' };
      for (const c of r.checks) ul.appendChild(el('div', { class: 'oc st-' + c.status }, el('span', { class: 'oc-i' }, ST[c.status] || '·'), el('b', null, c.name), ' ', c.url ? extLink(c.url, c.detail || c.url) : el('span', { class: 'muted' }, c.detail || '')));
      box.appendChild(ul);
    }
    if (r.links.length) {
      const l = el('div', { class: 'pc-links', style: 'margin-top:6px' });
      for (const x of r.links) {
        if (x.url) l.appendChild(extLink(x.url, x.name, 'btn small ghost'));
        else if (x.hint) { const b = el('button', { class: 'btn small ghost' }, x.name); b.addEventListener('click', () => { $('#qTopic').value = '@' + x.hint; osintRun(); }); l.appendChild(b); }
      }
      box.appendChild(l);
    }
    for (const n of r.notes || []) box.appendChild(el('div', { class: 'muted', style: 'font-size:12px;margin-top:6px' }, n));
    box.appendChild(el('div', { class: 'muted', style: 'font-size:11.5px;margin-top:6px' }, 'Только открытые данные. ОКО не использует утечки баз, «пробив» и сервисы раскрытия владельцев номеров.'));
  }

  // ---------------------------------------------------------------- доклады
  async function loadCatalog() {
    if (S.catalog || !SERVER) return S.catalog;
    try { S.catalog = await api('/api/catalog/reports'); } catch (e) { S.catalog = null; }
    return S.catalog;
  }
  async function renderReportsBox() {
    const box = clear($('#reportsBox'));
    box.appendChild(el('label', { class: 'check', title: 'Показывать только выпуски и новости, где упоминается тема из строки поиска' }, el('input', { type: 'checkbox', id: 'optReportTopic' }), ' только упоминающие тему'));
    const cat = await loadCatalog();
    if (!cat) { box.appendChild(el('div', { class: 'muted' }, 'Каталог докладов доступен при работе через сервер.')); return; }
    const m = new Date().getMonth() + 1, nm = m % 12 + 1;
    const MONTH = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
    const MONTH_P = ['', 'январе', 'феврале', 'марте', 'апреле', 'мае', 'июне', 'июле', 'августе', 'сентябре', 'октябре', 'ноябре', 'декабре'];
    const soon = cat.reports.filter((r) => (r.months || []).includes(m) || (r.months || []).includes(nm));
    const cal = el('div', { class: 'rcal' });
    for (const r of soon) cal.appendChild(el('span', { class: 'rchip' + (r.rank ? ' rank' : ''), title: r.cadence + (r.rank ? ' · есть рейтинг/оценка стран' : '') }, extLink(r.url, r.name)));
    cal.appendChild(el('div', { class: 'muted', style: 'font-size:11.5px' }, 'по датам прошлых выпусков; золотая рамка — доклад с рейтингом стран'));
    box.appendChild(dsec('Ожидаются в ' + MONTH_P[m] + ' — ' + MONTH_P[nm] + ' · ' + soon.length, cal, true, 'repsoon'));
    const all = el('div');
    for (const [g, label] of Object.entries(cat.groups)) {
      const list = cat.reports.filter((r) => r.group === g);
      const ul = el('div', { class: 'rlist' });
      for (const r of list) ul.appendChild(el('div', null, extLink(r.url, r.name), el('span', { class: 'muted' }, ' · ' + r.cadence + (r.months && r.months.length ? ' · обычно: ' + r.months.map((x) => MONTH[x].slice(0, 3)).join(', ') : '') + (r.rank ? ' · рейтинг' : ''))));
      all.appendChild(dsec(label + ' · ' + list.length, ul, false, 'rep_' + g));
    }
    box.appendChild(dsec('Каталог: ' + cat.reports.length + ' докладов и индексов', all, false, 'repcat'));
    box.appendChild(el('div', { class: 'muted', style: 'font-size:12px;margin-top:4px' }, '«НАЙТИ» — новые выпуски за выбранный период: новости о выходе докладов (Google News), публикации организаций-авторов на их сайтах и в лентах.'));
  }

  // ---------------------------------------------------------------- мониторинг
  function renderWatchPanel() {
    const box = clear($('#watchChips'));
    const n = S.watch.sources.length + S.watch.channels.length;
    if (!n) box.appendChild(el('span', { class: 'muted' }, 'Список пуст. Добавьте источники: кнопка ниже, значок «глаз» в разделе «Источники» или «Следить за источником» в карточке материала.'));
    for (const id of S.watch.sources) {
      const src = S.registry.byId.get(id);
      const rm = el('button', { title: 'Не следить' }, '×');
      rm.addEventListener('click', () => toggleWatch({ kind: 'source', id, name: src ? src.name : id }, false));
      box.appendChild(el('span', { class: 'tchip', title: src ? src.domains[0] : id }, src ? src.name : id, rm));
    }
    for (const c of S.watch.channels) {
      const rm = el('button', { title: 'Не следить' }, '×');
      rm.addEventListener('click', () => toggleWatch({ kind: 'channel', id: c.id, name: c.name }, false));
      box.appendChild(el('span', { class: 'tchip tg', title: 'Telegram: t.me/' + c.id }, 'TG · ' + (c.name || c.id), rm));
    }
    $$('#watchPresets button').forEach((b) => b.classList.toggle('on', b.dataset.p === (S.watchPreset || '24h')));
    const last = S.done && S.params && S.params.mode === 'watch' ? 'обновлено ' + fmtDate(Math.floor((S.started || Date.now()) / 1000)) : '';
    $('#watchHint').textContent = last;
  }
  function watchAddModal() {
    const body = el('div');
    const q = el('input', { class: 'input', placeholder: 'Название или сайт источника из реестра…', style: 'width:100%' });
    const res = el('div', { class: 'wpick' });
    const tg = el('input', { class: 'input', placeholder: '@канал или t.me/канал', style: 'width:100%' });
    body.append(el('div', { class: 'muted', style: 'margin-bottom:4px' }, 'Источник из реестра ОКО:'), q, res,
      el('div', { class: 'muted', style: 'margin:12px 0 4px' }, 'Публичный Telegram-канал:'), tg,
      el('div', { class: 'muted', style: 'font-size:12px;margin-top:8px' }, 'Нет нужного сайта в реестре? Добавьте его в разделе «Источники» → «Добавить источник», затем отметьте здесь.'));
    const draw = () => {
      clear(res);
      const nq = C.normText(q.value);
      if (nq.length < 2) return;
      S.sources.filter((sx) => C.normText(sx.name + ' ' + sx.domains.join(' ')).includes(nq)).slice(0, 12).forEach((sx) => {
        const on = S.watch.sources.includes(sx.id);
        const b = el('button', { class: 'pcand' + (on ? ' on' : '') }, (on ? '✓ ' : '+ ') + sx.name, el('span', { class: 'muted' }, ' · ' + sx.domains[0] + ' · ' + (C.TIERS[sx.tier] || C.TIERS[4]).code));
        b.addEventListener('click', () => { toggleWatch({ kind: 'source', id: sx.id, name: sx.name }); setTimeout(draw, 350); });
        res.appendChild(b);
      });
    };
    q.addEventListener('input', debounce(draw, 150));
    modal('Добавить в мониторинг', body, () => {
      const v = tg.value.trim().replace(/^(https?:\/\/)?(www\.)?(t\.me|telegram\.me)\/(s\/)?/, '').replace(/^@/, '').split(/[/?]/)[0];
      if (v) {
        if (!/^[A-Za-z][A-Za-z0-9_]{3,31}$/.test(v)) { toast('Некорректное имя канала', true); return false; }
        toggleWatch({ kind: 'channel', id: v, name: '@' + v }, true);
      }
      return true;
    }, 'Готово');
    setTimeout(() => q.focus(), 50);
  }
  async function runWatch() {
    if (S.running) { toast('Дождитесь завершения текущего поиска', true); return; }
    if (!SERVER) { toast('Мониторинг работает при запуске ОКО через сервер', true); return; }
    if (!S.watch.sources.length && !S.watch.channels.length) { watchAddModal(); return; }
    const preset = S.watchPreset || '24h';
    const [a, b] = presetRange(preset);
    const filter = splitList($('#watchFilter').value);
    S.running = true;
    setRunningUI(true);
    S.items.clear(); S.meta.clear(); S.tasks.clear(); S.notes = []; S.stats = {}; S.selected = null; S.done = null; S.shown = 150;
    renderDetail(null);
    renderProgress('Опрашиваю источники мониторинга…');
    render();
    try {
      let plan = {}, origins = {};
      if (filter.length) {
        const exp = await api('/api/expand', { method: 'POST', body: { topics: filter, context: [], exclude: [], langs: [...S.langOn], related: false } });
        plan = exp.plan; origins = exp.origins;
      }
      const params = { mode: 'watch', title: 'Мониторинг источников', topics: filter, context: [], exclude: [], langs: [...S.langOn], plan, origins,
        sources: S.watch.sources, channels: S.watch.channels, t_from: Math.floor(a.getTime() / 1000), t_to: Math.floor(b.getTime() / 1000),
        tz_offset: -new Date().getTimezoneOffset() };
      S.params = params;
      S.started = Date.now();
      await streamSearch(params, 'watch');
    } catch (e) { if (e.name !== 'AbortError') toast('Мониторинг: ' + e.message, true); }
    finally {
      S.running = false;
      setRunningUI(false);
      if (S.wsName === 'watch') { recompute(true); renderProgress(); renderWatchPanel(); }
    }
  }

  // ---------------------------------------------------------------- вид ленты, заголовки по-русски
  function renderViewMenu() {
    const m = clear($('#menuView'));
    m.appendChild(el('div', { class: 'mh' }, 'Сортировка'));
    for (const [v, l] of [['authority', 'по авторитетности'], ['date', 'по дате (новые выше)'], ['relevance', 'по релевантности']]) {
      const b = el('button', { class: 'mi' + (S.sort === v ? ' on' : '') }, (S.sort === v ? '● ' : '○ ') + l);
      b.addEventListener('click', () => { S.sort = v; store.set('sort', v); m.classList.add('hidden'); applyFilters(); render(); });
      m.appendChild(b);
    }
    m.appendChild(el('hr'));
    m.appendChild(el('div', { class: 'mh' }, 'Группировка'));
    for (const [v, l] of [['list', 'Лента'], ['stories', 'Сюжеты (кто первым)'], ['tiers', 'По уровням авторитетности'], ['sources', 'По источникам']]) {
      const b = el('button', { class: 'mi' + (S.view === v ? ' on' : '') }, (S.view === v ? '● ' : '○ ') + l);
      b.addEventListener('click', () => { S.view = v; if (S.wsName === 'main') store.set('view', v); m.classList.add('hidden'); renderList(); });
      m.appendChild(b);
    }
    m.appendChild(el('hr'));
    const d = el('input', { type: 'checkbox' }); d.checked = S.density === 'full';
    d.addEventListener('change', () => { S.density = d.checked ? 'full' : 'compact'; store.set('density', S.density); renderList(); });
    m.appendChild(el('label', null, d, 'Показывать аннотации в ленте'));
    const t = el('input', { type: 'checkbox' }); t.checked = S.trTitles; t.disabled = !SERVER;
    t.addEventListener('change', () => { S.trTitles = t.checked; store.set('trTitles', S.trTitles); renderList(); if (S.trTitles) translateVisibleTitles(); });
    m.appendChild(el('label', { title: 'Машинный перевод заголовков на русский под оригиналом' }, t, 'Заголовки по-русски'));
  }
  let trBusy = false;
  async function translateVisibleTitles() {
    if (!S.trTitles || !SERVER || trBusy) return;
    const need = visible.slice(0, S.shown).filter((x) => x.lang && x.lang !== 'ru' && !S.tr.has(x.id)).slice(0, 40);
    if (!need.length) return;
    trBusy = true;
    need.forEach((x) => S.tr.set(x.id, { loading: true }));
    try {
      const r = await api('/api/translate', { method: 'POST', body: { texts: need.map((x) => x.title), to: 'ru' } });
      need.forEach((x, i) => S.tr.set(x.id, { title: r.texts[i] || '', engine: r.engine, done: true, titleOnly: true }));
    } catch (e) { need.forEach((x) => S.tr.delete(x.id)); toast('Перевод заголовков: ' + e.message, true); trBusy = false; return; }
    trBusy = false;
    renderList();
    translateVisibleTitles();
  }

  // ================================================================ история, баннер, представления
  function addHistory(p) {
    S.history = [{ topics: p.topics, context: p.context, exclude: p.exclude, langs: p.langs, t: Date.now() }].concat(S.history.filter((x) => JSON.stringify(x.topics) !== JSON.stringify(p.topics) || JSON.stringify(x.context) !== JSON.stringify(p.context))).slice(0, 40);
    saveHistory();
  }
  function saveHistory() {
    store.set('history', S.history);
    if (SERVER) api('/api/state/history', { method: 'PUT', body: S.history }).catch(() => {});
  }
  function renderBanner() {
    const b = clear($('#banner'));
    if (!SERVER) {
      b.appendChild(el('div', { class: 'banner' }, el('b', null, 'Автономный режим. '), 'ОКО открыто как файл — доступны только GDELT и OpenAlex, без проверки первоисточников и PDF. Для полного охвата (Google News по странам и языкам, ленты и поиск по сайтам 679 источников, архив, PDF) запустите ', el('code', null, 'START_OKO'), ' (Windows) или ', el('code', null, 'python3 oko.py'), '.'));
    }
    if (S.snapshot) {
      const back = el('button', { class: 'btn small', style: 'margin-left:10px' }, 'Закрыть архивный отчёт');
      back.addEventListener('click', () => { S.snapshot = null; S.items.clear(); S.tasks.clear(); S.done = null; renderBanner(); recompute(true); renderProgress(); });
      b.appendChild(el('div', { class: 'banner', style: 'border-color:rgba(106,163,220,.5);background:var(--blue-bg);color:#cfe2f7' },
        'Просмотр архива: «' + S.snapshot.title + '», выполнен ' + fmtDate(S.snapshot.started) + '. ', back));
    }
  }
  function showView(v) {
    $$('#topnav button').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
    const main = v === 'results' || v === 'watch';
    if (main) switchWs(v === 'watch' ? 'watch' : 'main');
    $('#view-results').classList.toggle('hidden', !main);
    $('#query').classList.toggle('hidden', v !== 'results');
    $('#watchPanel').classList.toggle('hidden', v !== 'watch');
    $('#termsPanel').classList.add('hidden');
    if (!main) $('#progress').classList.add('hidden');
    for (const k of ['dossier', 'archive', 'sources', 'settings', 'help']) $('#view-' + k).classList.toggle('hidden', k !== v);
    if (main) {
      $$('#sectSeg button').forEach((x) => x.classList.toggle('on', x.dataset.s === S.section));
      renderBanner();
      recompute(true);
      renderProgress();
      if (!S.selected) renderDetail(null);
    }
    if (v === 'watch') renderWatchPanel();
    if (v === 'dossier') renderDossier();
    if (v === 'archive') renderArchive();
    if (v === 'sources') renderSources();
    if (v === 'settings') renderSettings();
    if (v === 'help') renderHelp();
    window.scrollTo(0, 0);
  }
  function renderStatus() {
    const s = clear($('#status'));
    if (SERVER && S.boot) {
      const d = S.boot.discovery || {};
      s.append(el('span', { class: 'dot on' }), el('span', null, 'сервер · ' + S.sources.length + ' источников' + (d.running ? ' · проверка каналов ' + d.done + '/' + d.total : '')));
    } else if (SERVER) s.append(el('span', { class: 'dot warn' }), el('span', null, 'сервер недоступен'));
    else s.append(el('span', { class: 'dot warn' }), el('span', null, 'автономный режим'));
  }

  // ================================================================ клавиатура
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    if (e.key === 'Enter' && ['qTopic', 'qCtx', 'qNot'].includes(e.target.id)) {
      e.preventDefault();
      if (S.qtab === 'person' && e.target.id === 'qTopic') { S.person = null; personSearch(); } else runSearch();
      return;
    }
    if (typing) return;
    if (e.key === '/') { e.preventDefault(); $('#qTopic').focus(); $('#qTopic').select(); return; }
    if (e.key === 'Escape') { S.selected = null; renderDetail(null); $$('#list .item.sel').forEach((r) => r.classList.remove('sel')); return; }
    const ids = $$('#list .item').map((r) => r.dataset.id);
    const i = ids.indexOf(S.selected);
    const it = S.selected ? S.items.get(S.selected) : null;
    if (e.key === 'j' || e.key === 'о') { const n = ids[Math.min(ids.length - 1, i + 1)]; if (n) { select(n); scrollToRow(n); } }
    else if (e.key === 'k' || e.key === 'л') { const n = ids[Math.max(0, i - 1)]; if (n) { select(n); scrollToRow(n); } }
    else if ((e.key === 'o' || e.key === 'щ') && it) window.open(it.resolved || it.url, '_blank', 'noopener');
    else if ((e.key === 's' || e.key === 'ы') && it) toggleDossier(it);
    else if ((e.key === 'c' || e.key === 'с') && it) deepCheck(it, false);
  });
  function scrollToRow(id) { const r = $('#list .item[data-id="' + CSS.escape(id) + '"]'); if (r) r.scrollIntoView({ block: 'nearest' }); }

  // ================================================================ запуск
  async function loadSocial(q) {
    if (!SERVER) return;
    try { S.social = await api('/api/social' + (q ? '?q=' + encodeURIComponent(q) : '')); } catch (e) { /* не критично */ }
  }
  async function init() {
    S.langOn = new Set(store.get('langs', null) || S.languages.filter((l) => l.core || l.default).map((l) => l.code));
    S.mode = store.get('mode', 'registry');
    S.minTier = store.get('minTier', 4);
    S.types = new Set(store.get('types', []));
    S.sort = store.get('sort', 'authority');
    S.view = store.get('view', 'list');
    S.density = store.get('density', 'compact');
    S.strict = store.get('strict', true);
    S.trTitles = store.get('trTitles', false);
    S.themes = new Set(store.get('themes', []));
    S.qvals = store.get('qvals', {});
    S.facetOpen = new Set(store.get('facetOpen', ['tier', 'origin', 'kw', 'rel', 'platform']));
    S.watch = store.get('watch', { sources: [], channels: [] });
    S.watchPreset = store.get('watchPreset', '24h');
    S.history = store.get('history', []);
    S.settings = store.get('settings', {});
    for (const d of store.get('dossier', [])) if (d && d.item) S.dossier.set(d.item.id, d);
    if (SERVER) {
      try {
        S.boot = await api('/api/bootstrap');
        S.languages = S.boot.languages;
        S.settings = Object.assign({}, S.settings, S.boot.settings);
        const src = await api('/api/sources');
        S.sources = src.sources;
        S.registry = new C.Registry(S.sources);
        const dos = await api('/api/state/dossier');
        if (Array.isArray(dos)) { S.dossier.clear(); for (const d of dos) if (d && d.item) S.dossier.set(d.item.id, d); }
        const hist = await api('/api/state/history');
        if (Array.isArray(hist) && hist.length) S.history = hist;
        const w = await api('/api/state/watch');
        if (w && Array.isArray(w.sources)) S.watch = { sources: w.sources, channels: w.channels || [] };
        loadSocial('');
        loadCatalog();
      } catch (e) { toast('Нет связи с сервером ОКО: ' + e.message, true); }
    }
    const provs = (S.boot && S.boot.providers) || [];
    const provDefault = provs.filter((p) => p.default).map((p) => p.id);
    const known = new Set(store.get('providersKnown', []));
    S.providers = new Set(store.get('providers', null) || provDefault);
    for (const p of provs) if (!known.has(p.id) && p.default) S.providers.add(p.id);  // новые каналы включаются сами
    store.set('providersKnown', provs.map((p) => p.id));
    store.set('providers', [...S.providers]);
    if (!S.langOn.size) S.langOn = new Set(S.languages.filter((l) => l.core).map((l) => l.code));
    S.wsStore.watch = freshWs('watch');
    renderStatus();
    renderBanner();
    renderLangChips();
    renderThemeChips();
    renderTypesMenu(); updateTypesBtn();
    renderProvMenu();
    setPreset(store.get('preset', '7d'));
    const lastQ = store.get('lastQuery', null);
    if (lastQ) { $('#qCtx').value = lastQ.context || ''; $('#qNot').value = lastQ.exclude || ''; }
    if (!S.qvals.topic && lastQ && lastQ.topics) S.qvals.topic = lastQ.topics;
    S.qtab = 'topic';
    $('#qTopic').value = S.qvals.topic !== undefined ? S.qvals.topic : 'Узбекистан';
    const tab0 = store.get('qtab', 'topic');
    if (tab0 !== 'topic') switchTab(tab0);
    $$('#modeSeg button').forEach((b) => b.classList.toggle('on', b.dataset.m === S.mode));
    $('#minTier').value = String(S.minTier);
    updateDossierCount();
    updateWatchCount();
    paramsSummary();

    // обработчики
    $('#btnSearch').addEventListener('click', runSearch);
    $('#btnStop').addEventListener('click', stopSearch);
    $$('#qtabs button').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.t)));
    $('#qTopic').addEventListener('input', () => { if (S.qtab === 'person' && S.person && $('#qTopic').value.trim() !== S.person.label) { S.person = null; S.personCands = []; renderPersonBox(); } });
    $$('#presets button').forEach((b) => b.addEventListener('click', () => setPreset(b.dataset.p)));
    $('#dFrom').addEventListener('change', customRange);
    $('#dTo').addEventListener('change', customRange);
    for (const id of ['qTopic', 'qCtx', 'qNot']) $('#' + id).addEventListener('change', () => {
      S.qvals[S.qtab] = $('#qTopic').value; store.set('qvals', S.qvals);
      store.set('lastQuery', { topics: S.qvals.topic || '', context: $('#qCtx').value, exclude: $('#qNot').value });
    });
    $('#btnParams').addEventListener('click', () => { $('#qparams').classList.toggle('hidden'); paramsSummary(); });
    $('#btnTerms').addEventListener('click', async () => {
      const panel = $('#termsPanel');
      if (!panel.classList.contains('hidden')) { panel.classList.add('hidden'); return; }
      panel.classList.remove('hidden');
      try { await expand(false); } catch (e) { toast('Термины: ' + e.message, true); }
    });
    $('#btnTermsClose').addEventListener('click', () => $('#termsPanel').classList.add('hidden'));
    $('#btnReExpand').addEventListener('click', async () => { try { await expand(true); toast('Термины обновлены'); } catch (e) { toast(e.message, true); } });
    $$('#modeSeg button').forEach((b) => b.addEventListener('click', () => {
      S.mode = b.dataset.m; store.set('mode', S.mode);
      $$('#modeSeg button').forEach((x) => x.classList.toggle('on', x === b));
      S.shown = 150; applyFilters(); render(); paramsSummary();
    }));
    $('#minTier').addEventListener('change', () => { S.minTier = Number($('#minTier').value); store.set('minTier', S.minTier); applyFilters(); render(); paramsSummary(); });
    $('#btnTypes').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(e.target, $('#menuTypes')); });
    $('#btnProv').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(e.target, $('#menuProv')); });
    $('#btnExport').addEventListener('click', (e) => { e.stopPropagation(); renderExportMenu(); toggleMenu(e.target, $('#menuExport')); });
    $('#btnView').addEventListener('click', (e) => { e.stopPropagation(); renderViewMenu(); toggleMenu(e.target, $('#menuView')); });
    $$('#sectSeg button').forEach((b) => b.addEventListener('click', () => setSection(b.dataset.s)));
    $('#optStrict').checked = S.strict;
    $('#optStrict').addEventListener('change', () => setStrict($('#optStrict').checked));
    $('#rFilter').addEventListener('input', debounce(() => { S.text = $('#rFilter').value.trim(); S.shown = 150; applyFilters(); render(); }, 250));
    $('#btnFacets').addEventListener('click', () => $('#facets').classList.toggle('closed'));
    $$('#topnav button').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));
    $('#btnWatchAdd').addEventListener('click', watchAddModal);
    $('#btnWatchRun').addEventListener('click', runWatch);
    $('#watchFilter').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); runWatch(); } });
    $$('#watchPresets button').forEach((b) => b.addEventListener('click', () => { S.watchPreset = b.dataset.p; store.set('watchPreset', S.watchPreset); renderWatchPanel(); }));
    const mq = window.matchMedia('(max-width: 800px)');
    if (mq.matches) $('#facets').classList.add('closed');
    if (mq.addEventListener) mq.addEventListener('change', (e) => { if (e.matches) $('#facets').classList.add('closed'); });
    render();
    renderDetail(null);
    if (SERVER) setInterval(async () => {
      try { const h = await api('/api/health'); if (S.boot) { S.boot.discovery = h.discovery; renderStatus(); } } catch (e) { S.boot = null; renderStatus(); }
    }, 15000);
  }
  init();
  window.OKO = { S, recompute, runSearch };
})();
