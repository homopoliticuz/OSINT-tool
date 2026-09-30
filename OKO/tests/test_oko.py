"""Тесты серверной части ОКО. Запуск: python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIX = os.path.join(ROOT, "tests", "fixtures", "upstream")

from okolib import feedparse, htmlmeta  # noqa: E402
from okolib.lexicon import Languages, Lexicon, build_plan  # noqa: E402
from okolib.net import FetchError, FixtureTransport, HttpClient, check_public_host  # noqa: E402
from okolib.providers import gdelt, gnews  # noqa: E402
from okolib.registry import Registry  # noqa: E402
from okolib.util import TermMatcher, canonical_url, detect_lang, norm_text, parse_date  # noqa: E402


class TestText(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm_text("  Ўзбекистон  Республикаси "), "узбекистон республикаси")
        self.assertEqual(norm_text("Oʻzbekiston"), "o'zbekiston")
        self.assertEqual(norm_text("Özbekistan’ın"), "ozbekistan'in")
        self.assertEqual(norm_text("وأوزبكستان"), "واوزبكستان")
        self.assertEqual(norm_text("ازبکستان"), norm_text("ازبكستان"))
        self.assertEqual(norm_text("Мирзиёев"), norm_text("Мирзиеев"))

    def test_matcher(self):
        m = TermMatcher(["Узбекистан", "ШОС", "Хива", "أوزبكستان", "乌兹别克斯坦", "Özbekistan", "אוזבקיסטן"])
        self.assertEqual(m.find("В Узбекистане прошли выборы"), "узбекистан")
        self.assertIsNone(m.find("шоссе в Ташкенте"))            # «ШОС» — только целым словом
        self.assertEqual(m.find("саммит ШОС в Тяньцзине"), "шос")
        self.assertIsNone(m.find("из архива МИД"))                # «Хива» не внутри слова
        self.assertEqual(m.find("وزير خارجية وأوزبكستان"), "اوزبكستان")  # слитная приставка «و»
        self.assertEqual(m.find("中国与乌兹别克斯坦签署协议"), "乌兹别克斯坦")
        self.assertEqual(m.find("Özbekistan'ın dış ticareti"), "ozbekistan")
        self.assertEqual(m.find("שר החוץ באוזבקיסטן"), "אוזבקיסטן")    # приставка «ב»
        self.assertIsNone(TermMatcher(["uzbek"]).find("the kuzbekov family"))

    def test_dates(self):
        self.assertEqual(parse_date("Mon, 29 Sep 2026 10:00:00 GMT"), 1790676000)
        self.assertEqual(parse_date("2026-09-29T15:00:00+05:00"), 1790676000)
        self.assertEqual(parse_date("2026-09-29T10:00:00Z"), 1790676000)
        self.assertEqual(parse_date("20260929T100000Z"), 1790676000)
        self.assertEqual(parse_date("2026-09-29"), 1790640000)
        self.assertEqual(parse_date("Mon, 29 Sep 2026 13:00:00 +0300 (MSK)"), 1790676000)
        self.assertIsNone(parse_date("вчера"))

    def test_canonical(self):
        self.assertEqual(canonical_url("https://www.example.com/a/b/?utm_source=x&id=5#frag"), "https://example.com/a/b?id=5")
        self.assertEqual(canonical_url("http://m.example.com/news/amp/"), "https://example.com/news")

    def test_lang(self):
        self.assertEqual(detect_lang("Мирзиёев подписал указ", "uz"), "ru")
        self.assertEqual(detect_lang("Ўзбекистон Республикаси", "ru"), "uz")
        self.assertEqual(detect_lang("سفر وزیر خارجه ازبکستان به تهران"), "fa")
        self.assertEqual(detect_lang("ازبکستان اور پاکستان کے درمیان"), "ur")
        self.assertEqual(detect_lang("أوزبكستان توقع اتفاقية"), "ar")
        self.assertEqual(detect_lang("우즈베키스탄 대통령"), "ko")
        self.assertEqual(detect_lang("ウズベキスタン大統領"), "ja")
        self.assertEqual(detect_lang("Le président de l'Ouzbékistan et la France"), "fr")


class TestFeeds(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(FIX, name), "rb") as f:
            return FixtureTransport(FIX)._subst(f.read())

    def test_rss_cp1251(self):
        d = feedparse.parse_feed(self.read("kommersant.xml"), "https://www.kommersant.ru/RSS/news.xml")
        self.assertEqual(d["items"][0]["title"], "Узбекистан увеличит поставки газа в Китай")
        self.assertEqual(d["items"][0]["authors"], ["Кирилл Кривошеев"])
        self.assertTrue(d["items"][0]["ts"])

    def test_rdf_shift_jis(self):
        d = feedparse.parse_feed(self.read("asahi.rdf"), "https://www.asahi.com/")
        self.assertEqual(d["items"][0]["title"], "ウズベキスタンと経済協力協定に署名")

    def test_atom(self):
        d = feedparse.parse_feed(self.read("conversation.atom"), "https://theconversation.com/")
        it = d["items"][0]
        self.assertIn("cotton", it["title"])
        self.assertEqual(it["authors"], ["Dr. Farida Karimova"])
        self.assertEqual(it["link"], "https://theconversation.com/uzbekistans-cotton-sector-300001")

    def test_malformed(self):
        d = feedparse.parse_feed(self.read("gazeta.xml"), "https://www.gazeta.uz/")
        self.assertEqual(d["items"][0]["title"], "Ташкент примет саммит ОТГ в ноябре")
        broken = b"<rss><channel><item><title>A <b>broken</title><link>https://x.org/1</link></item><item><title>Second</title>"
        d2 = feedparse.parse_feed(broken, "https://x.org/")
        self.assertTrue(d2["items"])
        self.assertEqual(feedparse.parse_feed(b"<html><body>no</body></html>")["kind"], "html")

    def test_google_items(self):
        d = feedparse.parse_feed(self.read("gn_en.xml"), "https://news.google.com/")
        first = gnews.convert(d["items"][0], "en", "US:en")
        self.assertEqual(first["title"], "Uzbekistan and US sign critical minerals agreement")
        self.assertEqual(first["src_name"], "Reuters")
        self.assertEqual(first["domain"], "reuters.com")
        # ссылка старого формата раскрыта без сети, исходная ссылка Google сохранена
        self.assertFalse(first["gn"])
        self.assertTrue(first["url"].startswith("https://www.reuters.com/world/"))
        self.assertIn("news.google.com/rss/articles/", first["extra"]["gn_url"])
        self.assertEqual(len(first["related"]), 1)  # Bloomberg; сам Reuters исключён


class TestHtml(unittest.TestCase):
    def page(self, name):
        with open(os.path.join(FIX, name), "rb") as f:
            return FixtureTransport(FIX)._subst(f.read()).decode("utf-8")

    def test_meta_reuters(self):
        m = htmlmeta.extract_meta(self.page("page_reuters.html"), "https://www.reuters.com/world/x/")
        self.assertEqual(m["authors"], ["Olzhas Auyezov"])
        self.assertEqual(m["publisher"], "Reuters")
        self.assertIs(m["paywall"], False)
        self.assertEqual(m["credits"][0]["name"], "Reuters")

    def test_meta_syndication(self):
        m = htmlmeta.extract_meta(self.page("page_yahoo.html"), "https://www.yahoo.com/news/x.html")
        self.assertEqual(m["canonical_domain"], "reuters.com")

    def test_meta_dateline_ru_and_generic_author(self):
        m = htmlmeta.extract_meta(self.page("page_lenta.html"), "https://lenta.ru/news/x/")
        self.assertEqual(m["credits"][0]["name"], "ТАСС")
        self.assertEqual(m["authors"], [])  # «Редакция» — не автор

    def test_paywall_and_reprint_marker(self):
        html_text = """<html><head><script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","headline":"H",
        "isAccessibleForFree":"False","author":{"@type":"Person","name":"A. Author"}}]}</script></head><body><article>
        <p>This article was originally published by Foreign Affairs and is republished with permission here today.</p>
        <p>Second paragraph with enough text to be considered a real paragraph of the article body.</p></article></body></html>"""
        m = htmlmeta.extract_meta(html_text, "https://x.org/a")
        self.assertIs(m["paywall"], True)
        self.assertEqual(m["authors"], ["A. Author"])
        self.assertIn("originally published", m["reprint_marker"])

    def test_discover(self):
        html_text = """<html><head><link rel="alternate" type="application/rss+xml" href="/feed/">
        <link rel="alternate" type="application/rss+xml" href="/comments/feed/">
        <link rel="https://api.w.org/" href="https://x.org/wp-json/"></head><body></body></html>"""
        d = htmlmeta.discover(html_text, "https://x.org/")
        self.assertEqual(d["feeds"], ["https://x.org/feed/"])
        self.assertEqual(d["wp_api"], "https://x.org/wp-json/")
        self.assertTrue(d["wordpress"])

    def test_readable(self):
        r = htmlmeta.extract_readable(self.page("page_kommersant.html"), "https://www.kommersant.ru/doc/1")
        self.assertEqual(len(r["blocks"]), 2)
        self.assertEqual(r["meta"]["authors"], ["Кирилл Кривошеев"])


class TestProviders(unittest.TestCase):
    def test_gnews_query(self):
        q = gnews.build_query(["Uzbekistan", "Central Asia"], ["gas"], ["football"], 1790640000, 1790726400,
                              ["csis.org", "rand.org"])
        self.assertEqual(q, '(Uzbekistan OR "Central Asia") gas -football (site:csis.org OR site:rand.org) '
                            'after:2026-09-28 before:2026-10-01')

    def test_batchexecute(self):
        with open(os.path.join(FIX, "batchexecute.txt"), encoding="utf-8") as f:
            self.assertEqual(gnews.parse_batchexecute(f.read()), "https://www.ng.ru/cis/2026-09-29/5_uzbek.html")

    def test_gdelt_convert(self):
        it = gdelt.convert({"url": "https://www.isna.ir/x", "title": "T", "seendate": "20260929T100000Z",
                            "domain": "isna.ir", "language": "Persian", "sourcecountry": "Iran"}, None)
        self.assertEqual((it["lang"], it["country"], it["ts"]), ("fa", "IR", 1790676000))


class TestLexicon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(os.path.join(ROOT, "data", "lexicon.json"), HttpClient(None), lambda: {})
        cls.langs = Languages(os.path.join(ROOT, "data", "languages.json"))

    def test_entity_forms(self):
        for q in ("Узбекистан", "узбекистана", "Uzbekistan", "O'zbekiston", "ウズベキスタン", "أوزبكستان"):
            self.assertEqual(self.lex.find_entity(q)["id"], "uzbekistan", q)
        self.assertEqual(self.lex.find_entity("Мирзиеев")["id"], "mirziyoyev")

    def test_expand_offline(self):
        core = [l["code"] for l in self.langs.items if l["core"]]
        self.assertEqual(len(core), 12)
        e = self.lex.expand("Узбекистан", core, related=True, allow_network=False)
        self.assertEqual(e["langs"]["fr"]["q"][0], "Ouzbékistan")
        self.assertIn("Ташкент", e["langs"]["ru"]["q"])
        for code in core:
            self.assertTrue(e["langs"][code]["q"], code)
            self.assertEqual(e["langs"][code]["src"], "lexicon", code)
        plan = build_plan([e], [], [], core)
        self.assertIn("zh-Hant", plan)
        self.assertEqual(plan["zh-Hant"]["q"][0], "烏茲別克")

    def test_every_lexicon_entity_is_valid(self):
        codes = set(self.langs.by_code) | {"zh-Hant"}
        for ent in self.lex.entities:
            self.assertTrue(set(ent["terms"]) <= codes, ent["id"])
            for code, terms in ent["terms"].items():
                self.assertTrue(all(t.strip() for t in terms), (ent["id"], code))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = Registry(os.path.join(ROOT, "data", "sources.json"), os.path.join(self.tmp, "u.json"),
                            os.path.join(self.tmp, "d.json"), HttpClient(None))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lookup(self):
        self.assertEqual(self.reg.lookup("https://www.bbc.com/russian/articles/x")["id"], "bbc_russian")
        self.assertEqual(self.reg.lookup("https://www.bbc.com/news/world-1")["id"], "bbc")
        self.assertEqual(self.reg.lookup("https://en.yna.co.kr/view/1")["id"], "yonhap")
        self.assertEqual(self.reg.lookup("https://studies.aljazeera.net/en/x")["id"], "ajcs")
        self.assertEqual(self.reg.lookup("https://www.aljazeera.net/news")["id"], "aljazeera")
        self.assertIsNone(self.reg.lookup("https://unknown.example/x"))

    def test_registry_integrity(self):
        ids, domains = set(), set()
        for s in self.reg.sources:
            self.assertNotIn(s["id"], ids)
            ids.add(s["id"])
            self.assertIn(s["tier"], (1, 2, 3))
            self.assertTrue(s["lang"] and s["country"] and s["name"])
            for d in s["domains"]:
                self.assertNotIn(d, domains)
                self.assertFalse(d.startswith(("http", "www.")))
                domains.add(d)
        self.assertGreaterEqual(sum(1 for s in self.reg.sources if s.get("bm")), 270)

    def test_user_overrides(self):
        self.reg.save_user({"overrides": {"idsa": {"tier": 1}},
                            "added": [{"id": "user_x", "name": "X", "domains": ["x.org"], "country": "UZ",
                                       "lang": ["ru"], "type": "think_tank", "tier": 2}]})
        self.assertEqual(self.reg.by_id["idsa"]["tier"], 1)
        self.assertEqual(self.reg.lookup("https://x.org/a")["id"], "user_x")


class TestNet(unittest.TestCase):
    def test_ssrf_guard(self):
        for h in ("localhost", "127.0.0.1", "10.1.2.3", "192.168.0.1", "169.254.169.254", "::1", "router.local"):
            with self.assertRaises(FetchError, msg=h):
                check_public_host(h)
        check_public_host("8.8.8.8")

    def test_fixture_bytes_substitution(self):
        raw = FixtureTransport(FIX)._subst("<a>{{RFC822:-1h}} Узбекистан</a>".encode("cp1251"))
        self.assertNotIn(b"{{", raw)
        self.assertIn("Узбекистан", raw.decode("cp1251"))


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestServerIntegration(unittest.TestCase):
    """Полный цикл: сервер на фикстурах → расширение запроса → поиск (поток событий) → статья."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.tmp, "cache"))
        with open(os.path.join(cls.tmp, "cache", "discovery.json"), "w") as f:
            json.dump({"atlanticcouncil": {"ts": int(time.time()), "feeds_ok": [], "status": "ok",
                                           "wp_api": "https://www.atlanticcouncil.org/wp-json/"}}, f)
        cls.port = _free_port()
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "oko.py"), "--no-browser", "--port",
                                     str(cls.port), "--data", cls.tmp, "--fixtures", FIX],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        cls.base = "http://127.0.0.1:%d" % cls.port
        for _ in range(50):
            try:
                html_text = urllib.request.urlopen(cls.base + "/", timeout=2).read().decode()
                break
            except OSError:
                time.sleep(0.2)
        cls.token = html_text.split('name="oko-token" content="')[1].split('"')[0]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        if cls.proc.stdout:
            cls.proc.stdout.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, path, body=None, token=True):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("X-OKO-Token", self.token)
        return urllib.request.urlopen(req, timeout=30)

    def test_forbidden_without_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("/api/bootstrap", token=False)
        self.assertEqual(cm.exception.code, 403)

    def test_search_flow(self):
        langs = ["ru", "en", "fr", "de", "es", "it", "ko", "ja", "zh", "fa", "ar", "ur", "tr", "uz"]
        exp = json.load(self.call("/api/expand", {"topics": ["Узбекистан"], "context": [], "exclude": [],
                                                  "langs": langs, "related": True}))
        now = int(time.time())
        params = {"topics": ["Узбекистан"], "langs": langs, "plan": exp["plan"], "t_from": now - 7 * 86400,
                  "t_to": now, "tz_offset": 300}
        resp = self.call("/api/search", params)
        items, done = {}, None
        for block in resp.read().decode("utf-8").split("\n\n"):
            ev = data = None
            for line in block.split("\n"):
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:])
            if ev == "items":
                for it in data:
                    items[it["id"]] = it
            elif ev == "done":
                done = data
        self.assertIsNotNone(done)
        self.assertGreaterEqual(len(items), 30)
        titles = {it["title"] for it in items.values()}
        self.assertIn("What Uzbekistan’s elections mean for the region", titles)   # WordPress API
        self.assertIn("ウズベキスタンと経済協力協定に署名", titles)                     # RDF Shift_JIS
        self.assertNotIn("Uzbekistan cotton harvest begins", titles)                 # вне периода
        langs_found = {it["lang"] for it in items.values()}
        self.assertTrue({"ru", "en", "zh", "ja", "ar", "fa", "ur", "tr", "ko", "de"} <= langs_found, langs_found)
        merged = [it for it in items.values() if len(it["prov"]) > 1]
        self.assertTrue(merged, "дубли из разных каналов должны склеиваться")
        self.assertTrue(done.get("report"))
        rep = json.load(self.call("/api/reports/" + urllib.request.quote(done["report"])))
        self.assertEqual(len(rep["items"]), len(items))

    def test_article_deep_check(self):
        url = urllib.request.quote("https://www.yahoo.com/news/uzbekistan-us-sign-critical-minerals-1.html", safe="")
        m = json.load(self.call("/api/article?url=" + url))
        self.assertTrue(m["ok"])
        self.assertEqual(m["canonical_domain"], "reuters.com")
        self.assertEqual(m["canonical_source"], "reuters")


class TestJsParity(unittest.TestCase):
    """Нормализация и сопоставление в Python и JavaScript должны совпадать."""

    def test_parity(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js не установлен")
        cases = ["Ўзбекистон", "Oʻzbekiston", "Özbekistan’ın", "وأوزبكستان", "ازبکستان", "Мирзиёев", "Straße",
                 "İstanbul", "Kırgızistan", "שר החוץ באוזבקיסטן", "उज़्बेकिस्तान", "乌兹别克斯坦", "カザフスタン"]
        terms = ["Узбекистан", "ШОС", "Хива", "أوزبكستان", "乌兹别克斯坦", "Özbekistan", "אוזבקיסטן", "uzbek"]
        texts = ["В Узбекистане", "шоссе", "саммит ШОС", "из архива", "وزير خارجية وأوزبكستان",
                 "中国与乌兹别克斯坦", "Özbekistan'ın", "באוזבקיסטן", "kuzbekov", "Uzbek-Chinese ties"]
        js = ("const C=require(%r);const a=JSON.parse(process.argv[1]);const m=new C.TermMatcher(a.terms);"
              "console.log(JSON.stringify({n:a.cases.map(C.normText),f:a.texts.map(t=>m.find(t))}))"
              % os.path.join(ROOT, "web", "assets", "oko-core.js"))
        out = subprocess.run([node, "-e", js, json.dumps({"cases": cases, "terms": terms, "texts": texts})],
                             capture_output=True, text=True, check=True).stdout
        res = json.loads(out)
        self.assertEqual(res["n"], [norm_text(c) for c in cases])
        m = TermMatcher(terms)
        self.assertEqual(res["f"], [m.find(t) for t in texts])


if __name__ == "__main__":
    unittest.main()
