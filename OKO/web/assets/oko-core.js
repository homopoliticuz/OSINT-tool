/* ОКО — ядро классификации (браузер и Node.js).
 *
 * Уровень авторитетности, тип и страна источника, статус «первоисточник / перепубликация»,
 * группировка сюжетов и дублей, релевантность. Функции normText и TermMatcher повторяют
 * okolib/util.py — правила должны совпадать (это проверяют тесты).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.OKOCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ------------------------------------------------------------ нормализация текста
  const APOS = /[ʻʼ‘’`´′ʹ]/g;
  const AR_MARKS = /[ؐ-ًؚ-ٰٟۖ-ۭـ]/g;
  const HE_MARKS = /[֑-ׇ]/g;
  const COMBINING = /[̀-ͯ]/g;
  const ZW = /[​-‏⁠﻿]/g;
  const AR_MAP = {
    'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا',
    'ى': 'ي', 'ی': 'ي', 'ئ': 'ي', 'ک': 'ك',
    'ہ': 'ه', 'ھ': 'ه', 'ە': 'ه', 'ة': 'ه', 'ۃ': 'ه',
    'ؤ': 'و', 'ı': 'i'
  };
  const AR_RE = /[أإآٱىیئکہھەةۃؤı]/g;

  function normText(s) {
    if (!s) return '';
    s = String(s).normalize('NFKC').toLowerCase().replace(/ß/g, 'ss').replace(/ς/g, 'σ');
    s = s.replace(ZW, '').replace(APOS, "'").replace(AR_MARKS, '').replace(HE_MARKS, '').replace(/़/g, '');
    s = s.replace(AR_RE, (c) => AR_MAP[c]);
    s = s.normalize('NFD').replace(COMBINING, '').normalize('NFC');
    return s.replace(/\s+/g, ' ').trim();
  }

  const WORD_CHAR = /[\p{L}\p{M}\p{N}']/u;
  function isWordChar(ch) { return !!ch && WORD_CHAR.test(ch); }
  function isCJK(ch) {
    const o = ch.codePointAt(0);
    return (o >= 0x3040 && o <= 0x30ff) || (o >= 0x3400 && o <= 0x4dbf) || (o >= 0x4e00 && o <= 0x9fff) ||
      (o >= 0xf900 && o <= 0xfaff) || (o >= 0x20000 && o <= 0x2ffff);
  }
  const AR_PREFIXES = ['وال', 'بال', 'فال', 'كال', 'لل', 'ال', 'و', 'ب', 'ل', 'ف', 'ك'];
  const HE_PREFIXES = ['וה', 'שה', 'וב', 'ול', 'ומ', 'מה', 'ה', 'ו', 'ב', 'ל', 'מ', 'ש', 'כ'];

  function matchTerm(text, term) {
    const cjk = isCJK(term[0]);
    const whole = [...term].length <= 4 && !cjk;
    let start = 0;
    for (;;) {
      const i = text.indexOf(term, start);
      if (i < 0) return false;
      start = i + 1;
      if (cjk) return true;
      const end = i + term.length;
      if (whole && end < text.length && isWordChar(text[end])) continue;
      if (i === 0 || !isWordChar(text[i - 1])) return true;
      const c0 = term.charCodeAt(0);
      const prefixes = (c0 >= 0x600 && c0 <= 0x6ff) ? AR_PREFIXES : ((c0 >= 0x590 && c0 <= 0x5ff) ? HE_PREFIXES : []);
      for (const p of prefixes) {
        const j = i - p.length;
        if (j >= 0 && text.slice(j, i) === p && (j === 0 || !isWordChar(text[j - 1]))) return true;
      }
    }
  }

  class TermMatcher {
    constructor(terms) {
      const seen = new Set();
      this.terms = [];
      for (const t of terms || []) {
        const n = normText(t);
        if (n && !seen.has(n)) { seen.add(n); this.terms.push(n); }
      }
      this.terms.sort((a, b) => b.length - a.length);
    }
    find(text, normalized) {
      if (!this.terms.length || !text) return null;
      const t = normalized ? text : normText(text);
      for (const term of this.terms) if (matchTerm(t, term)) return term;
      return null;
    }
  }

  // ------------------------------------------------------------ справочники
  const TIERS = {
    1: { code: 'A', label: 'A — высший', stars: 3,
      desc: 'Ведущие аналитические центры мира, международные организации, официальные источники, мировые агентства и издания' },
    2: { code: 'B', label: 'B — высокий', stars: 2,
      desc: 'Ведущие национальные аналитические центры и качественные издания, национальные агентства, профильные издания по региону' },
    3: { code: 'C', label: 'C — базовый', stars: 1, desc: 'Прочие известные СМИ и издания' },
    4: { code: 'D', label: 'D — вне реестра', stars: 0, desc: 'Источник не классифицирован (найден в широком поиске)' }
  };
  const TYPE_LABELS = {
    think_tank: 'Аналитический центр', intl_org: 'Международная организация', official: 'Официальный источник',
    agency: 'Информационное агентство', media_global: 'Издание мирового уровня', media_national: 'Национальное издание',
    media_analytic: 'Аналитическое издание', media_regional: 'СМИ Центральной Азии', academic: 'Научное / академическое',
    ratings: 'Рейтинги и индексы', ngo: 'НКО / правозащита', unknown: 'Не классифицирован'
  };
  const ANALYTIC = new Set(['think_tank', 'intl_org', 'official', 'media_analytic', 'academic', 'ratings', 'ngo']);
  const PRIMARY_TYPES = new Set(['think_tank', 'intl_org', 'official', 'academic', 'ratings', 'ngo']);
  const PAYWALL_LABELS = { hard: 'Платный доступ', metered: 'Лимит бесплатных статей', partial: 'Частично платный',
    confirmed: 'Платный (подтверждено страницей)' };

  const AGGREGATORS = ['msn.com', 'yahoo.com', 'yahoo.co.jp', 'dzen.ru', 'news.mail.ru', 'marketscreener.com',
    'investing.com', 'tradingview.com', 'menafn.com', 'zawya.com', 'bignewsnetwork.com', 'devdiscourse.com',
    'newsnow.co.uk', 'pressreader.com', 'inkl.com', 'ground.news', 'flipboard.com', 'headtopics.com',
    'newsbreak.com', 'news.google.com', 'news.rambler.ru', 'smi2.ru', 'latestly.com', 'newsnow.com',
    'ghanaweb.com', 'plus.lesechos.fr', 'aol.com', 'newsweek.com.aggregator'];

  const TLD_COUNTRY = {
    uz: 'UZ', ru: 'RU', kz: 'KZ', kg: 'KG', tj: 'TJ', tm: 'TM', af: 'AF', cn: 'CN', jp: 'JP', kr: 'KR', in: 'IN',
    pk: 'PK', ir: 'IR', tr: 'TR', de: 'DE', fr: 'FR', it: 'IT', es: 'ES', uk: 'GB', il: 'IL', ae: 'AE', sa: 'SA',
    qa: 'QA', eg: 'EG', az: 'AZ', ge: 'GE', am: 'AM', ua: 'UA', by: 'BY', pl: 'PL', ch: 'CH', at: 'AT', be: 'BE',
    nl: 'NL', se: 'SE', no: 'NO', dk: 'DK', fi: 'FI', cz: 'CZ', hu: 'HU', ro: 'RO', bg: 'BG', rs: 'RS', gr: 'GR',
    pt: 'PT', ie: 'IE', ca: 'CA', au: 'AU', nz: 'NZ', br: 'BR', mx: 'MX', ar: 'AR', cl: 'CL', co: 'CO', sg: 'SG',
    my: 'MY', id: 'ID', th: 'TH', vn: 'VN', ph: 'PH', bd: 'BD', lk: 'LK', np: 'NP', hk: 'HK', tw: 'TW', mn: 'MN',
    lv: 'LV', lt: 'LT', ee: 'EE', md: 'MD', iq: 'IQ', sy: 'SY', lb: 'LB', jo: 'JO', kw: 'KW', bh: 'BH', om: 'OM',
    ma: 'MA', dz: 'DZ', tn: 'TN', ng: 'NG', ke: 'KE', za: 'ZA', sk: 'SK', si: 'SI', hr: 'HR', cy: 'CY', lu: 'LU'
  };

  // Издания и агентства, на которые ссылаются перепубликации. reg — идентификаторы реестра (префиксы).
  const OUTLETS = [
    { id: 'reuters', label: 'Reuters', reg: ['reuters'], names: ['reuters', 'рейтер', 'рейтерс', 'ロイター', '路透社', '路透', '로이터', 'رويترز', 'رویترز', 'روئٹرز'] },
    { id: 'ap', label: 'Associated Press', reg: ['ap'], names: ['associated press', 'ассошиэйтед пресс', '美联社', '美聯社', 'ap通信', 'ap통신', 'أسوشيتد برس', 'آسوشیتدپرس'], short: ['ap'] },
    { id: 'afp', label: 'AFP', reg: ['afp'], names: ['agence france-presse', 'agence france presse', 'франс пресс', 'франс-пресс', '法新社', 'afp通信', 'afp통신', 'فرانس برس', 'خبرگزاری فرانسه'], short: ['afp'] },
    { id: 'bloomberg', label: 'Bloomberg', reg: ['bloomberg'], names: ['bloomberg', 'блумберг', '彭博社', '彭博', 'ブルームバーグ', '블룸버그', 'بلومبرغ', 'بلومبرگ'] },
    { id: 'tass', label: 'ТАСС', reg: ['tass'], names: ['тасс', 'tass', '塔斯社', 'タス通信', '타스', 'تاس'] },
    { id: 'ria', label: 'РИА Новости', reg: ['ria'], names: ['риа новости', 'ria novosti'] },
    { id: 'interfax', label: 'Интерфакс', reg: ['interfax'], names: ['интерфакс', 'interfax'] },
    { id: 'xinhua', label: 'Синьхуа', reg: ['xinhua'], names: ['xinhua', 'синьхуа', '新华社', '新華社', '신화통신', 'شينخوا', 'شینهوا'] },
    { id: 'kyodo', label: 'Kyodo', reg: ['kyodo'], names: ['kyodo', 'киодо', '共同通信', '共同社', '교도통신'], short: ['共同'] },
    { id: 'jiji', label: 'Jiji Press', reg: ['jiji'], names: ['jiji press', '時事通信', 'дзидзи'], short: ['時事'] },
    { id: 'yonhap', label: 'Yonhap', reg: ['yonhap'], names: ['yonhap', 'ёнхап', '联合通讯社', '聯合通訊社', '연합뉴스'] },
    { id: 'dpa', label: 'dpa', reg: ['dpa'], names: ['deutsche presse-agentur'], short: ['dpa'] },
    { id: 'efe', label: 'EFE', reg: ['efe'], names: ['agencia efe'], short: ['efe'] },
    { id: 'ansa', label: 'ANSA', reg: ['ansa'], names: [], short: ['ansa'] },
    { id: 'aa', label: 'Anadolu', reg: ['aa'], names: ['anadolu ajansi', 'anadolu agency', 'анадолу', 'الأناضول', 'آناتولی'] },
    { id: 'irna', label: 'IRNA', reg: ['irna'], names: ['ирна', 'ایرنا', 'إرنا'], short: ['irna'] },
    { id: 'tasnim', label: 'Tasnim', reg: ['tasnim'], names: ['tasnim', 'тасним', 'تسنیم'] },
    { id: 'fars', label: 'Fars', reg: ['fars'], names: ['fars news', 'خبرگزاری فارس'] },
    { id: 'mehr', label: 'Mehr', reg: ['mehr'], names: ['mehr news', 'خبرگزاری مهر'] },
    { id: 'wam', label: 'WAM', reg: ['wam'], names: ['emirates news agency', 'وكالة أنباء الإمارات'], short: ['wam'] },
    { id: 'spa', label: 'SPA', reg: ['spa'], names: ['saudi press agency', 'وكالة الأنباء السعودية'] },
    { id: 'app_pk', label: 'APP', reg: ['app_pk'], names: ['associated press of pakistan'] },
    { id: 'pti', label: 'PTI', reg: ['pti'], names: ['press trust of india'], short: ['pti'] },
    { id: 'uza', label: 'УзА', reg: ['uza'], names: ['национальное информационное агентство узбекистана', 'national news agency of uzbekistan'], short: ['уза', 'uza', 'ўза'] },
    { id: 'dunyo', label: 'ИА «Дунё»', reg: ['dunyo'], names: ['дунё', 'dunyo'] },
    { id: 'kun_uz', label: 'Kun.uz', reg: ['kun_uz'], names: ['kun.uz', 'кун.уз'] },
    { id: 'gazeta_uz', label: 'Газета.uz', reg: ['gazeta_uz'], names: ['gazeta.uz', 'газета.uz'] },
    { id: 'daryo', label: 'Daryo', reg: ['daryo'], names: ['daryo.uz', 'дарё'] },
    { id: 'podrobno', label: 'Podrobno.uz', reg: ['podrobno'], names: ['podrobno.uz', 'подробно.уз'] },
    { id: 'sputnik', label: 'Sputnik', reg: ['sputnik'], names: ['sputnik', 'спутник узбекистан', 'sputnik узбекистан'] },
    { id: 'rt', label: 'RT', reg: ['rt'], names: ['russia today'], short: ['rt'] },
    { id: 'bbc', label: 'BBC', reg: ['bbc'], names: ['би-би-си', 'bbc news'], short: ['bbc'] },
    { id: 'dw', label: 'Deutsche Welle', reg: ['dw'], names: ['deutsche welle', 'дойче велле'], short: ['dw'] },
    { id: 'rferl', label: 'RFE/RL', reg: ['rferl', 'ozodlik', 'svoboda', 'currenttime', 'azattyq', 'azattyk', 'ozodi', 'azathabar', 'radiofarda'], names: ['radio free europe', 'радио свобода', 'radio liberty', 'rfe/rl', 'озодлик', 'ozodlik', 'азаттык'] },
    { id: 'voa', label: 'VOA', reg: ['voa', 'amerikaovozi', 'golosameriki', 'urduvoa', 'voachinese'], names: ['voice of america', 'голос америки', 'amerika ovozi'], short: ['voa'] },
    { id: 'cnn', label: 'CNN', reg: ['cnn'], names: [], short: ['cnn'] },
    { id: 'ft', label: 'Financial Times', reg: ['ft', 'ftchinese'], names: ['financial times', 'файнэншл таймс', 'файненшл таймс', 'ft中文网'], short: ['ft'] },
    { id: 'wsj', label: 'Wall Street Journal', reg: ['wsj'], names: ['wall street journal', 'уолл-стрит джорнал'], short: ['wsj'] },
    { id: 'nytimes', label: 'New York Times', reg: ['nytimes'], names: ['new york times', 'нью-йорк таймс'], short: ['nyt'] },
    { id: 'washingtonpost', label: 'Washington Post', reg: ['washingtonpost'], names: ['washington post', 'вашингтон пост'] },
    { id: 'economist', label: 'The Economist', reg: ['economist'], names: ['the economist'] },
    { id: 'guardian', label: 'The Guardian', reg: ['guardian'], names: ['the guardian', 'гардиан'] },
    { id: 'nikkei', label: 'Nikkei', reg: ['nikkei'], names: ['nikkei', 'никкэй', '日本経済新聞', '日経'] },
    { id: 'scmp', label: 'South China Morning Post', reg: ['scmp'], names: ['south china morning post', '南华早报', '南華早報'] },
    { id: 'globaltimes', label: 'Global Times', reg: ['globaltimes'], names: ['global times', '环球时报', '環球時報', 'глобал таймс'] },
    { id: 'cgtn', label: 'CGTN', reg: ['cgtn'], names: [], short: ['cgtn'] },
    { id: 'aljazeera', label: 'Al Jazeera', reg: ['aljazeera'], names: ['al jazeera', 'аль-джазира', 'الجزيرة'] },
    { id: 'kommersant', label: 'Коммерсантъ', reg: ['kommersant'], names: ['коммерсант', 'kommersant'] },
    { id: 'vedomosti', label: 'Ведомости', reg: ['vedomosti'], names: ['ведомост', 'vedomosti'] },
    { id: 'rbc', label: 'РБК', reg: ['rbc'], names: [], short: ['рбк', 'rbc'] },
    { id: 'izvestia', label: 'Известия', reg: ['izvestia'], names: ['izvestia', 'газета «известия»', 'газета известия'] },
    { id: 'eurasianet', label: 'Eurasianet', reg: ['eurasianet'], names: ['eurasianet', 'евразианет'] },
    { id: 'fergana', label: 'Фергана', reg: ['fergana'], names: ['fergana.news', 'fergana.agency', 'фергана.ру', 'ia fergana', 'иа «фергана»', 'агентство «фергана»'] },
    { id: 'akipress', label: 'AKIpress', reg: ['akipress'], names: ['akipress', 'акипресс'] },
    { id: 'kazinform', label: 'Kazinform', reg: ['kazinform'], names: ['kazinform', 'казинформ'] },
    { id: 'trend', label: 'Trend', reg: ['trend_az'], names: ['trend news agency', 'агентство trend'] },
    { id: 'projectsyndicate', label: 'Project Syndicate', reg: ['projectsyndicate'], names: ['project syndicate'] }
  ];

  const CUES = [
    // en
    'according to', 'reported', 'reports', 'reporting by', 'via', 'citing', 'cited by', 'told', 'as reported by',
    'quoted by', 'wrote', 'writes', 'source:', 'said in', 'reuters reported', 'first reported',
    // ru
    'сообща', 'переда', 'по данным', 'со ссылкой на', 'ссылаясь на', 'пишет', 'пишут', 'источник:', 'по информации',
    'как сообщ', 'цитирует', 'отмечает', 'агентств', 'рассказал', 'заявил', 'опубликовал',
    // fr / de / es / it / pt
    'selon', 'rapporte', "d'apres", 'source :', 'a indique', 'cite par', 'berichtet', 'laut', 'meldet', 'zufolge',
    'quelle:', 'unter berufung auf', 'segun', 'informa', 'informo', 'fuente:', 'citado por', 'de acuerdo con',
    'secondo', 'riporta', 'fonte:', 'riferisce', 'citato da', 'segundo',
    // tr / uz
    'gore', 'bildirdi', 'aktardi', 'kaynak:', 'haberine gore', 'xabar ber', "ma'lum qil", 'manba', "xabariga ko'ra",
    'хабар бер', 'маълум қил',
    // ja / ko / zh
    'によると', 'によれば', '報じた', '伝えた', '出典', '에 따르면', '보도했다', '전했다', '출처', '据', '據', '报道', '報導',
    '援引', '来源', '來源', '消息', '电', '電',
    // ar / fa / ur / he
    'وفقا', 'بحسب', 'نقلا عن', 'ذكرت', 'افادت', 'المصدر', 'حسب', 'اوردت', 'به گزارش', 'به نقل از', 'منبع', 'گزارش داد',
    'کے مطابق', 'رپورٹ', 'ذرائع', 'לפי', 'על פי', 'דיווח', 'מקור'
  ].map(normText);
  const CJK_CUES = new Set(['据', '據', '报道', '報導', '援引', '来源', '來源', '消息', '电', '電', 'によると', 'によれば',
    '報じた', '伝えた', '出典', '에 따르면', '보도했다', '전했다', '출처'].map(normText));

  // ------------------------------------------------------------ реестр
  class Registry {
    constructor(sources) {
      this.sources = sources || [];
      this.byId = new Map();
      this.index = new Map();
      for (const s of this.sources) {
        this.byId.set(s.id, s);
        for (const d of s.domains || []) {
          const k = d.toLowerCase();
          const slash = k.indexOf('/');
          const host = slash < 0 ? k : k.slice(0, slash);
          const path = slash < 0 ? '' : k.slice(slash);
          if (!this.index.has(host)) this.index.set(host, []);
          this.index.get(host).push([path, s]);
        }
      }
      for (const lst of this.index.values()) lst.sort((a, b) => b[0].length - a[0].length);
    }
    lookup(urlOrHost) {
      if (!urlOrHost) return null;
      let host = urlOrHost, path = '/';
      if (urlOrHost.includes('://')) {
        try { const u = new URL(urlOrHost); host = u.hostname; path = u.pathname || '/'; } catch (e) { return null; }
      }
      host = host.toLowerCase(); path = path.toLowerCase();
      const parts = host.split('.');
      for (let i = 0; i < parts.length - 1; i++) {
        const h = parts.slice(i).join('.');
        const lst = this.index.get(h);
        if (!lst) continue;
        for (const [pfx, s] of lst) if (!pfx || path.startsWith(pfx)) return s;
      }
      return null;
    }
  }

  function hostOf(url) {
    try { let h = new URL(url).hostname.toLowerCase(); return h.startsWith('www.') ? h.slice(4) : h; } catch (e) { return ''; }
  }
  function sameSite(a, b) {
    if (!a || !b) return false;
    const strip = (h) => h.replace(/^(www|m|amp|mobile|en|ru|uz)\./, '');
    a = strip(a); b = strip(b);
    return a === b || a.endsWith('.' + b) || b.endsWith('.' + a);
  }
  function tldCountry(domain) {
    if (!domain) return null;
    const parts = domain.split('.');
    return TLD_COUNTRY[parts[parts.length - 1]] || null;
  }
  function isAggregator(domain) {
    if (!domain) return false;
    return AGGREGATORS.some((a) => domain === a || domain.endsWith('.' + a));
  }

  function inferSource(domain) {
    if (!domain) return null;
    if (/\.(gov|mil)(\.[a-z]{2})?$/.test(domain) || /\.(gouv|gob|go|govt|gv|gub)\.[a-z]{2}$/.test(domain) ||
        /(^|\.)gov\.[a-z]{2}$/.test(domain) || /\.gouv\.fr$/.test(domain) || /\.admin\.ch$/.test(domain) ||
        /\.bund\.de$/.test(domain) || /\.europa\.eu$/.test(domain)) {
      return { id: '', name: domain, type: 'official', tier: 1, inferred: true };
    }
    if (/\.int$/.test(domain)) return { id: '', name: domain, type: 'intl_org', tier: 1, inferred: true };
    if (/\.(edu|ac\.[a-z]{2}|edu\.[a-z]{2})$/.test(domain)) return { id: '', name: domain, type: 'academic', tier: 3, inferred: true };
    return null;
  }

  const TOP_VENUES = /central asian survey|europe-asia studies|post-soviet affairs|problems of post-communism|central asian affairs|journal of eurasian studies|eurasian geography and economics|international affairs|^survival|foreign affairs|security dialogue|journal of democracy|world development|china quarterly|asian survey|nationalities papers|caucasus survey|communist and post-communist studies|demokratizatsiya|russian politics|slavic review|water international|energy policy|nature|science$/i;
  const MAJOR_PUBLISHERS = /elsevier|springer|taylor|francis|routledge|wiley|sage|oxford university|cambridge university|brill|de gruyter|emerald|university of chicago|mit press|johns hopkins|palgrave|nature portfolio|american association/i;

  function academicTier(item) {
    const venue = item.src_name || '';
    const pub = (item.extra && item.extra.publisher) || '';
    if (TOP_VENUES.test(venue)) return 1;
    if (MAJOR_PUBLISHERS.test(pub)) return 2;
    return 3;
  }

  // ------------------------------------------------------------ ссылки на другие издания
  function outletIsSelf(o, item, src) {
    const sid = (src && src.id) || item.source_id || '';
    if (sid && o.reg.some((r) => sid === r || sid.startsWith(r + '_'))) return true;
    const sn = normText(item.src_name || (src && src.name) || '');
    if (sn && (o.names.concat(o.short || [])).some((n) => sn === normText(n) || sn.startsWith(normText(n) + ' '))) return true;
    return false;
  }

  let _outletPatterns = null;
  function outletPatterns() {
    if (_outletPatterns) return _outletPatterns;
    _outletPatterns = OUTLETS.map((o) => ({
      o,
      names: o.names.map(normText).filter(Boolean),
      short: (o.short || []).map(normText).filter(Boolean)
    }));
    return _outletPatterns;
  }

  function findAll(text, term) {
    const out = [];
    let start = 0;
    for (;;) {
      const i = text.indexOf(term, start);
      if (i < 0) break;
      start = i + 1;
      const cjk = isCJK(term[0]);
      if (!cjk) {
        if (i > 0 && isWordChar(text[i - 1])) continue;
        const end = i + term.length;
        if ([...term].length <= 4 && end < text.length && isWordChar(text[end])) continue;
      }
      out.push(i);
    }
    return out;
  }

  function hasWordStart(hay, needle) {
    let start = 0;
    for (;;) {
      const i = hay.indexOf(needle, start);
      if (i < 0) return false;
      if (i === 0 || !isWordChar(hay[i - 1])) return true;
      start = i + 1;
    }
  }

  function hasCue(text, i, len, tight) {
    const before = text.slice(Math.max(0, i - (tight ? 18 : 48)), i);
    const after = text.slice(i + len, i + len + (tight ? 14 : 28));
    for (const c of CUES) {
      if (CJK_CUES.has(c)) {
        // иероглифические маркеры — только вплотную к названию («据新华社», «新华社…电»)
        if (before.slice(-3).includes(c) || after.slice(0, 14).includes(c)) return c;
        continue;
      }
      if (hasWordStart(before, c) || hasWordStart(after, c)) return c;
    }
    return null;
  }

  function detectCredits(title, snippet, item, src) {
    const parts = [[normText(title || ''), 'title'], [normText(snippet || ''), 'snippet']];
    for (const { o, names, short } of outletPatterns()) {
      if (outletIsSelf(o, item, src)) continue;
      for (const [text, where] of parts) {
        if (!text) continue;
        for (const [list, isShort] of [[names, false], [short, true]]) {
          for (const n of list) {
            for (const i of findAll(text, n)) {
              const prev = text.slice(Math.max(0, i - 3), i);
              const next = text.slice(i + n.length, i + n.length + 3);
              const dateline = /[([（【]\s*$/.test(prev) && /^\s*[)\]）】]/.test(next);
              const suffix = where === 'title' && i + n.length >= text.length - 1 && /(\s[-|–—]\s|:)\s*$/.test(text.slice(Math.max(0, i - 4), i));
              if (dateline || suffix) {
                return { id: o.id, label: o.label, strength: 'strong', where,
                  evidence: dateline ? 'агентская пометка «(' + o.label + ')»' : 'указание источника в заголовке' };
              }
              const cue = hasCue(text, i, n.length, isShort);
              if (cue) {
                const s = Math.max(0, i - 40);
                return { id: o.id, label: o.label, strength: 'cue', where,
                  evidence: '«…' + text.slice(s, Math.min(text.length, i + n.length + 30)).trim() + '…»' };
              }
            }
          }
        }
      }
    }
    return null;
  }

  // ------------------------------------------------------------ классификация
  function classify(item, reg, opts) {
    opts = opts || {};
    let src = (item.source_id && reg.byId.get(item.source_id)) || null;
    if (!src && item.url && !item.gn) src = reg.lookup(item.url);
    if (!src && item.src_url) src = reg.lookup(item.src_url);
    if (!src && item.domain) src = reg.lookup(item.domain);
    let inferred = null;
    if (!src) inferred = inferSource(item.domain);
    const s = src || inferred;
    item.source_id = src ? src.id : (item.source_id || '');
    let tier = s ? (s.tier || 3) : 4;
    let type = s ? s.type : 'unknown';
    if (item.kind === 'paper' && !src) { type = 'academic'; tier = academicTier(item); }
    item.tier = tier;
    item.type = type;
    item.inRegistry = !!src;
    item.srcName = (src && src.name) || item.src_name || item.domain || '—';
    item.country = (src && src.country) || item.country || tldCountry(item.domain) || null;
    item.state = src ? (src.state || '') : '';
    item.ca = !!(src && src.ca);
    item.bm = src ? (src.bm || '') : '';
    let pw = src ? (src.paywall || '') : '';
    if (item.meta && item.meta.paywall === true) pw = 'confirmed';
    else if (item.meta && item.meta.paywall === false && pw !== 'hard') pw = pw ? pw : '';
    item.paywall = pw;
    item.origin = origin(item, src, s, reg);
    return item;
  }

  function origin(item, src, s, reg) {
    const m = item.meta && item.meta.ok ? item.meta : null;
    const selfDomain = item.domain;
    // 1. признаки со страницы (глубокая проверка)
    if (m) {
      const cd = m.canonical_domain;
      if (cd && !sameSite(cd, selfDomain) && !sameSite(cd, hostOf(m.final_url || item.url || ''))) {
        const cs = reg.lookup(m.canonical || cd);
        if (!cs || !src || cs.id !== src.id) {
          return { status: 'reprint', confidence: 'high', checked: true,
            reason: 'Каноническая ссылка страницы (rel=canonical) указывает на ' + cd,
            credited: { label: cs ? cs.name : cd, domain: cd, url: m.canonical } };
        }
      }
      const orig = m.original_source || m.based_on;
      if (orig && !sameSite(hostOf(orig), selfDomain)) {
        const os = reg.lookup(orig);
        return { status: 'reprint', confidence: 'high', checked: true,
          reason: 'Метаданные страницы указывают первоисточник (original-source / isBasedOn)',
          credited: { label: os ? os.name : hostOf(orig), domain: hostOf(orig), url: orig } };
      }
      if (m.credits && m.credits.length) {
        const c = m.credits[0];
        const o = OUTLETS.find((x) => x.names.concat(x.short || []).some((n) => normText(n) === normText(c.name)) ||
          normText(x.label) === normText(c.name));
        if (!o || !outletIsSelf(o, item, src)) {
          return { status: 'reprint', confidence: 'high', checked: true, reason: 'В тексте — ' + c.evidence,
            credited: { label: o ? o.label : c.name } };
        }
      }
      if (m.reprint_marker) {
        return { status: 'reprint', confidence: 'medium', checked: true,
          reason: 'В тексте есть пометка о перепечатке: «' + m.reprint_marker.slice(0, 160) + '»', credited: null };
      }
    }
    // 2. агрегаторы и площадки переводов
    if ((src && src.agg) || isAggregator(selfDomain)) {
      const op = item.extra && item.extra.original_publisher;
      return { status: 'reprint', confidence: 'high', checked: !!m,
        reason: src && src.agg ? (src.note || 'Агрегатор: публикует материалы других изданий') : 'Агрегатор новостей: перепубликует материалы других изданий',
        credited: op ? { label: op, domain: item.extra.original_domain || '' } : null };
    }
    // 3. ссылка на другое издание в заголовке или аннотации
    const type = item.type;
    const cr = detectCredits(item.title, item.snippet, item, src);
    // аналитика и официальные материалы цитируют агентства — это не перепубликация
    const citing = !!(cr && cr.strength !== 'strong' && (PRIMARY_TYPES.has(type) || type === 'media_analytic'));
    if (cr && !citing) {
      return { status: 'reprint', confidence: cr.strength === 'strong' ? 'high' : 'medium', checked: !!m,
        reason: (cr.strength === 'strong' ? 'Материал агентства ' + cr.label + ': ' : 'Ссылается на ' + cr.label + ': ') + cr.evidence,
        credited: { label: cr.label, id: cr.id } };
    }
    const cite = citing ? '; в тексте цитируется ' + cr.label : '';
    // 4. дубль более ранней публикации (почти совпадающий заголовок)
    if (item.dupOf) {
      return { status: 'reprint', confidence: 'medium', checked: !!m,
        reason: 'Заголовок практически совпадает с более ранней публикацией: ' + (item.dupOfName || '') +
          (item.dupOfTime ? ' (' + item.dupOfTime + ')' : ''),
        credited: { label: item.dupOfName || '', ref: item.dupOf } };
    }
    // 5. признаки первичности
    if (item.kind === 'paper') {
      return { status: 'primary', confidence: 'high', checked: !!m, reason: 'Научная публикация (первичное исследование)' };
    }
    const byline = m && m.authors && m.authors.length ? '; автор: ' + m.authors.slice(0, 3).join(', ') : '';
    if (PRIMARY_TYPES.has(type)) {
      return { status: 'primary', confidence: s && s.inferred && !m ? 'medium' : 'high', checked: !!m,
        reason: 'Собственная публикация организации: ' + (TYPE_LABELS[type] || type).toLowerCase() + byline + cite };
    }
    if (type === 'agency') {
      return { status: 'primary', confidence: m ? 'high' : 'medium', checked: !!m,
        reason: 'Информационное агентство — первичный источник новостей' + byline +
          (m ? '; страница проверена, ссылок на другие издания нет' : '; ссылок на другие издания не обнаружено') };
    }
    if (m && m.authors && m.authors.length) {
      return { status: 'primary', confidence: 'medium', checked: true,
        reason: 'Авторский материал: ' + m.authors.slice(0, 3).join(', ') + '; ссылок на другие издания не обнаружено' + cite };
    }
    if (item.dupFirst) {
      return { status: 'primary', confidence: 'medium', checked: !!m,
        reason: 'Самая ранняя публикация среди ' + item.dupSize + ' совпадающих материалов' + cite };
    }
    if (item.authors && item.authors.length && src) {
      return { status: 'primary', confidence: 'low', checked: !!m,
        reason: 'Материал с авторской подписью (' + item.authors.slice(0, 2).join(', ') + '); ссылок на другие издания не обнаружено' + cite };
    }
    if (type === 'media_analytic') {
      return { status: 'primary', confidence: 'low', checked: !!m,
        reason: 'Аналитическое издание; признаков перепубликации не обнаружено' + cite };
    }
    if (src && (src.tier || 3) <= 2 && (type === 'media_global' || type === 'media_national' || type === 'media_regional')) {
      return { status: 'primary', confidence: 'low', checked: !!m,
        reason: 'Материал крупного издания; признаков перепубликации не обнаружено (рекомендуется проверка)' };
    }
    return { status: 'unknown', confidence: 'low', checked: !!m,
      reason: m ? 'Страница проверена: явных признаков перепубликации нет, но и подписи автора нет'
        : 'Недостаточно признаков. Нажмите «Проверить первоисточник» — ОКО изучит страницу (canonical, авторы, агентские пометки)' };
  }

  // ------------------------------------------------------------ сюжеты и дубли
  const STOP = new Set(('the a an of in on for to and with at by from as is are was were be has have after over new ' +
    'и в на с по для о об из к что как не за от до при это его её их также ' +
    'le la les des du de et a en un une pour dans sur au aux par ' +
    'der die das und mit von zu den dem im auf für ein eine ist ' +
    'el los las del y en con por para una un se al ' +
    'il lo gli di e che per un una nel sul della delle ' +
    've bir ile için bu da de ' + 'va bilan uchun bu').split(/\s+/));

  function titleCore(title) {
    return String(title || '').replace(/\s+[-|–—]\s+[^-|–—]{2,40}$/, '').trim();
  }

  function tokens(title, stopTerms) {
    const t = normText(titleCore(title));
    const out = new Set();
    const words = t.split(/[^\p{L}\p{N}']+/u).filter(Boolean);
    for (let w of words) {
      w = w.replace(/^'+|'+$/g, '');
      if (!w || STOP.has(w)) continue;
      if (stopTerms && stopTerms.some((st) => w.startsWith(st))) continue;
      const chars = [...w];
      if (chars.some((c) => isCJK(c))) {
        for (let i = 0; i < chars.length - 1; i++) out.add(chars[i] + chars[i + 1]);
        continue;
      }
      if (chars.length >= 2) out.add(chars.length > 6 ? chars.slice(0, 6).join('') : w);
    }
    return out;
  }

  function langGroup(item) {
    return (item.lang || 'xx').slice(0, 2);
  }

  function cluster(items, stopTerms) {
    const n = items.length;
    const toks = items.map((it) => tokens(it.title, stopTerms));
    const norm = items.map((it) => normText(titleCore(it.title)));
    const inv = new Map();
    toks.forEach((ts, i) => ts.forEach((t) => {
      if (!inv.has(t)) inv.set(t, []);
      inv.get(t).push(i);
    }));
    const storyP = Array.from({ length: n }, (_, i) => i);
    const dupP = Array.from({ length: n }, (_, i) => i);
    const find = (p, x) => { while (p[x] !== x) { p[x] = p[p[x]]; x = p[x]; } return x; };
    const union = (p, a, b) => { a = find(p, a); b = find(p, b); if (a !== b) p[Math.max(a, b)] = Math.min(a, b); };
    const maxDf = Math.max(8, n * 0.25);
    for (let i = 0; i < n; i++) {
      const counts = new Map();
      for (const t of toks[i]) {
        const lst = inv.get(t);
        if (!lst || lst.length > maxDf) continue;
        for (const j of lst) if (j > i) counts.set(j, (counts.get(j) || 0) + 1);
      }
      for (const [j, c] of counts) {
        if (langGroup(items[i]) !== langGroup(items[j])) continue;
        if (items[i].ts && items[j].ts && Math.abs(items[i].ts - items[j].ts) > 72 * 3600) continue;
        const a = toks[i].size, b = toks[j].size;
        const inter = c, uni = a + b - c;
        const jac = uni ? inter / uni : 0;
        const ov = Math.min(a, b) ? inter / Math.min(a, b) : 0;
        if ((norm[i] && norm[i] === norm[j]) || (jac >= 0.72 && Math.min(a, b) >= 4)) {
          union(dupP, i, j); union(storyP, i, j);
        } else if (ov >= 0.6 && inter >= 3) {
          union(storyP, i, j);
        }
      }
    }
    // точные совпадения заголовков (без учёта частотных слов)
    const byNorm = new Map();
    norm.forEach((t, i) => {
      if (!t || t.length < 12) return;
      if (byNorm.has(t)) { union(dupP, byNorm.get(t), i); union(storyP, byNorm.get(t), i); } else byNorm.set(t, i);
    });
    const groups = (p) => {
      const g = new Map();
      for (let i = 0; i < n; i++) {
        const r = find(p, i);
        if (!g.has(r)) g.set(r, []);
        g.get(r).push(i);
      }
      return g;
    };
    for (const it of items) { delete it.dupOf; delete it.dupFirst; delete it.dupOfName; delete it.dupOfTime; it.dupSize = 1; it.story = ''; it.storySize = 1; }
    for (const [, members] of groups(storyP)) {
      if (members.length < 2) continue;
      const sid = 's' + items[members[0]].id;
      for (const i of members) { items[i].story = sid; items[i].storySize = members.length; }
    }
    for (const [, members] of groups(dupP)) {
      if (members.length < 2) continue;
      members.sort((x, y) => (items[x].ts || 9e12) - (items[y].ts || 9e12) || (items[x].tier || 4) - (items[y].tier || 4));
      const first = items[members[0]];
      first.dupFirst = true;
      first.dupSize = members.length;
      for (const i of members.slice(1)) {
        const it = items[i];
        if (it.domain && first.domain && sameSite(it.domain, first.domain)) continue;
        it.dupOf = first.id;
        it.dupOfName = first.srcName || first.src_name || first.domain;
        it.dupOfTime = first.ts ? new Date(first.ts * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '';
        it.dupSize = members.length;
      }
    }
    return items;
  }

  // ------------------------------------------------------------ релевантность и сортировка
  const HIT_W = { title: 20, text: 10, engine: 5 };
  const ORIGIN_RANK = { primary: 0, unknown: 1, reprint: 2 };

  function score(item, tFrom, tTo) {
    let s = { 1: 40, 2: 28, 3: 16, 4: 6 }[item.tier] || 6;
    s += HIT_W[item.hit] || 5;
    if (item.ca) s += 6;
    if (ANALYTIC.has(item.type)) s += 10;
    if (item.origin) s += item.origin.status === 'primary' ? 8 : (item.origin.status === 'reprint' ? -8 : 0);
    if (item.storySize > 1) s += Math.min(10, item.storySize * 2);
    if (tTo > tFrom && item.ts) s += 6 * Math.max(0, Math.min(1, (item.ts - tFrom) / (tTo - tFrom)));
    return Math.round(s * 10) / 10;
  }

  function sortItems(items, mode) {
    const hitRank = { title: 0, text: 1, engine: 2 };
    const byDate = (a, b) => (b.ts || 0) - (a.ts || 0);
    if (mode === 'date') return items.sort(byDate);
    if (mode === 'relevance') return items.sort((a, b) => (b.score || 0) - (a.score || 0) || byDate(a, b));
    return items.sort((a, b) => (a.tier || 4) - (b.tier || 4) ||
      (ORIGIN_RANK[a.origin && a.origin.status] || 1) - (ORIGIN_RANK[b.origin && b.origin.status] || 1) ||
      (hitRank[a.hit] || 2) - (hitRank[b.hit] || 2) || byDate(a, b));
  }

  function citation(item, now) {
    // библиографическая ссылка (по мотивам ГОСТ Р 7.0.5-2008)
    const authors = (item.authors && item.authors.length ? item.authors : (item.meta && item.meta.authors) || []);
    const d = item.ts ? new Date(item.ts * 1000) : null;
    const dd = d ? String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + d.getFullYear() : '';
    const acc = now || new Date();
    const ad = String(acc.getDate()).padStart(2, '0') + '.' + String(acc.getMonth() + 1).padStart(2, '0') + '.' + acc.getFullYear();
    const url = (item.meta && item.meta.final_url) || item.url;
    return (authors.length ? authors.slice(0, 3).join(', ') + '. ' : '') + item.title + ' // ' + (item.srcName || item.src_name) +
      (dd ? '. — ' + dd : '') + '. — URL: ' + url + ' (дата обращения: ' + ad + ').';
  }

  return {
    normText, TermMatcher, Registry, classify, cluster, score, sortItems, detectCredits, citation, hostOf, sameSite,
    tldCountry, isAggregator, inferSource, TIERS, TYPE_LABELS, PAYWALL_LABELS, ANALYTIC, OUTLETS, titleCore, tokens
  };
});
