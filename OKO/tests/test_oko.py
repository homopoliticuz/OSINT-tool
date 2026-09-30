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

from okolib import feedparse, htmlmeta, relevance  # noqa: E402
from okolib.health import Health, classify  # noqa: E402
from okolib.lexicon import Languages, Lexicon, build_plan, plan_origins  # noqa: E402
from okolib.search import sanitize_origins  # noqa: E402
from okolib.net import FetchError, FixtureTransport, HttpClient, check_public_host  # noqa: E402
from okolib.providers import gdelt, gnews, reports, social  # noqa: E402
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


class TestSocial(unittest.TestCase):
    def test_parse_telegram(self):
        with open(os.path.join(FIX, "tg_kunuz.html"), "rb") as f:
            raw = FixtureTransport(FIX)._subst(f.read()).decode("utf-8")
        msgs = social.parse_tg(raw, "kunuzofficial")
        self.assertEqual(len(msgs), 4)
        m0, m1 = msgs[0], msgs[1]
        self.assertEqual(m0["url"], "https://t.me/kunuzofficial/90001")
        self.assertTrue(m0["text"].startswith("O'zbekiston va Qozog'iston"))
        self.assertIn("\n", m0["text"])
        self.assertEqual(m0["views"], "24.1K")
        self.assertEqual(m1["fwd"]["name"], "Prezident matbuot xizmati")
        self.assertEqual(m1["fwd"]["url"], "https://t.me/prezidentpress/5555")
        self.assertTrue(all(m["ts"] for m in msgs))

    def test_channels_and_catalogs(self):
        reg = Registry(os.path.join(ROOT, "data", "sources.json"), os.path.join(tempfile.mkdtemp(), "u.json"),
                       os.path.join(tempfile.mkdtemp(), "d.json"), HttpClient(None))
        for ch in social.data()["telegram_channels"]:
            self.assertEqual(social.clean_channel(ch["id"]), ch["id"])
            if ch.get("source"):
                self.assertIn(ch["source"], reg.by_id, ch)
        self.assertEqual(social.clean_channel("https://t.me/s/kunuzofficial?q=x"), "kunuzofficial")
        self.assertEqual(social.clean_channel("@gazetauz"), "gazetauz")
        self.assertEqual(social.clean_channel("t.me/+invite"), "")
        chans = social.telegram_channels({"tg_channels_add": [{"id": "@newchannel_uz", "lang": "ru"}],
                                          "tg_channels_off": ["kunuzofficial"]})
        ids = [c["id"] for c in chans]
        self.assertIn("newchannel_uz", ids)
        self.assertNotIn("kunuzofficial", ids)
        rm = reports.ReportMatcher()
        self.assertEqual(rm.find("UNDP launches Human Development Report 2026"), "hdr")
        self.assertTrue(rm.reportish("New Global Peace Index shows decline"))
        for r in reports.catalog()["reports"]:
            self.assertIn(r["src"], reg.by_id, r["id"])
        links = social.search_links("Узбекистан")
        self.assertEqual({x["id"] for x in links}, set(social.platforms()))
        self.assertTrue(all("%D0%A3" in x["url"] for x in links))


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

    def test_term_origins(self):
        core = [l["code"] for l in self.langs.items if l["core"]]
        e = self.lex.expand("Узбекистан", core, related=True, allow_network=False)
        ctx = self.lex.expand("газ", ["ru"], related=False, allow_network=False)
        o = plan_origins([e], [ctx])
        self.assertEqual(o[norm_text("Uzbekistan")]["kw"], "Узбекистан")
        self.assertEqual(o[norm_text("Uzbekistan")]["role"], "main")
        self.assertIn("en", o[norm_text("Uzbekistan")]["langs"])
        self.assertEqual(o[norm_text("Ташкент")]["role"], "related")
        self.assertEqual(o[norm_text("Tashkent")]["of"], "Ташкент")
        self.assertEqual(o[norm_text("узбек")]["role"], "form")
        self.assertEqual(o[norm_text("самарканд")]["role"], "related")
        self.assertEqual(o[norm_text("газ")]["role"], "ctx")
        plan = build_plan([e], [ctx], [], core)
        plan["en"]["q"].append("Uzbek economy")        # добавлено вручную в «Термины»
        full = sanitize_origins(o, plan, ["Узбекистан"], ["газ"])
        self.assertEqual(full[norm_text("Uzbek economy")]["role"], "manual")
        bare = sanitize_origins(None, plan, ["Узбекистан"], [])   # клиент без карты происхождения
        self.assertEqual(bare[norm_text("Tashkent")]["kw"], "Узбекистан")

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


class TestRateLimit(unittest.TestCase):
    """Сервис отвечает «слишком часто» (429): пауза и замедление, повтор, затем пауза 10 минут."""

    def setUp(self):
        import http.server
        import threading
        from okolib import net
        self.plan = []
        test = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                code = test.plan.pop(0) if test.plan else 200
                body = b"ok" if code == 200 else b"slow down"
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/x" % self.srv.server_address[1]
        net.HOST_RULES["127.0.0.1"] = {"conc": 1, "gap": 0.05, "cool": 0.3, "maxgap": 1}
        self.addCleanup(net.HOST_RULES.pop, "127.0.0.1", None)
        self.addCleanup(self.srv.shutdown)
        self.http = HttpClient(None, allow_private=True)

    def test_cooldown_then_success(self):
        self.plan = [429]
        t0 = time.time()
        r = self.http.get(self.url, retries=2)
        self.assertEqual(r.body, b"ok")
        self.assertGreaterEqual(time.time() - t0, 0.25)            # пауза после отказа
        g = self.http._gates["127.0.0.1"]
        self.assertEqual(g.fail_streak, 0)
        self.assertTrue(self.http.recently_limited("127.0.0.1"))
        self.assertGreater(g.gap, g.base_gap)                       # темп замедлен

    def test_block_after_repeated_limits(self):
        self.plan = [429] * 10
        with self.assertRaises(FetchError) as cm:
            self.http.get(self.url, retries=2)
        self.assertEqual(cm.exception.status, 429)
        with self.assertRaises(FetchError) as cm:
            self.http.get(self.url, retries=2)
        self.assertIn("10 мин", str(cm.exception))
        left = len(self.plan)
        with self.assertRaises(FetchError):
            self.http.get(self.url, retries=2)                     # на паузе — к серверу не обращается
        self.assertEqual(len(self.plan), left)


class TestHealth(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(FetchError("HTTP 429", 429)), "limit")
        self.assertEqual(classify(FetchError("источник временно ограничил запросы", 429)), "limit")
        self.assertEqual(classify(FetchError("HTTP 403", 403)), "denied")
        self.assertEqual(classify(FetchError("HTTP 404", 404)), "gone")
        self.assertEqual(classify(FetchError("HTTP 502", 502)), "server")
        self.assertEqual(classify(FetchError("превышено время ожидания")), "network")
        self.assertEqual(classify(FetchError("ошибка проверки SSL-сертификата: x")), "ssl")
        self.assertEqual(classify(FetchError("WordPress API вернул не JSON")), "format")

    def test_backoff_and_recovery(self):
        path = os.path.join(tempfile.mkdtemp(), "health.json")
        h = Health(path)
        for _ in range(2):
            h.fail("rss:x", "network", "timeout", label="X")
        self.assertIsNone(h.skip_reason("rss:x"))
        h.fail("rss:x", "network", "timeout", label="X")
        self.assertIn("временно отключён", h.skip_reason("rss:x"))
        h.flush()
        self.assertIn("временно отключён", Health(path).skip_reason("rss:x"))    # сохраняется между запусками
        # сервис поисковой системы: сетевые сбои не отключают отдельный запрос
        for _ in range(5):
            h.fail("gn:US:en", "network", "timeout", engine=True)
        self.assertIsNone(h.skip_reason("gn:US:en"))
        for _ in range(3):
            h.fail("gn:IR:fa", "gone", "HTTP 400", engine=True)
        self.assertTrue(h.skip_reason("gn:IR:fa"))
        h.ok("rss:x")
        self.assertIsNone(h.skip_reason("rss:x"))
        self.assertEqual({x["key"] for x in h.snapshot()}, {"gn:US:en", "gn:IR:fa"})
        h.reset()
        self.assertEqual(h.snapshot(), [])


@unittest.skipUnless(shutil.which("openssl"), "нужна утилита openssl")
class TestTlsChain(unittest.TestCase):
    """Сайт отдаёт сертификат без промежуточного: ОКО дозагружает его по AIA, но не доверяет подделкам."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import ssl
        import threading
        cls.dir = d = tempfile.mkdtemp()
        cls.http_port, cls.tls_port = _free_port(), _free_port()

        def sh(*args, ext=None):
            if ext:
                with open(os.path.join(d, "ext.cnf"), "w") as f:
                    f.write(ext)
                args += ("-extfile", os.path.join(d, "ext.cnf"))
            subprocess.run(("openssl",) + args, cwd=d, check=True, capture_output=True)
        ca = "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n" \
             "authorityKeyIdentifier=keyid,issuer\n"
        sh("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "root.key", "-out", "root.pem", "-days", "2",
           "-subj", "/CN=OKO Test Root", "-addext", "basicConstraints=critical,CA:TRUE",
           "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        sh("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "int.key", "-out", "int.csr", "-subj", "/CN=OKO Test Int")
        sh("x509", "-req", "-in", "int.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial", "-out",
           "int.pem", "-days", "2", ext=ca)
        sh("x509", "-in", "int.pem", "-outform", "DER", "-out", "int.der")
        # поддельный «промежуточный» — самоподписанный
        sh("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "fake.key", "-out", "fake.pem", "-days", "2",
           "-subj", "/CN=OKO Test Int", "-addext", "basicConstraints=critical,CA:TRUE")
        sh("x509", "-in", "fake.pem", "-outform", "DER", "-out", "fake.der")
        # leaf — честный сайт с неполной цепочкой; leaf2 — подмена: сертификат выпущен самоподписанным
        # «удостоверяющим центром» злоумышленника, на который указывает AIA
        for name, issuer, ca_name in (("leaf", "int.der", "int"), ("leaf2", "fake.der", "fake")):
            sh("req", "-newkey", "rsa:2048", "-nodes", "-keyout", name + ".key", "-out", name + ".csr", "-subj",
               "/CN=localhost")
            sh("x509", "-req", "-in", name + ".csr", "-CA", ca_name + ".pem", "-CAkey", ca_name + ".key",
               "-CAcreateserial", "-out", name + ".pem", "-days", "2",
               ext="subjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=CA:FALSE\n"
                   "authorityKeyIdentifier=keyid,issuer\n"
                   "authorityInfoAccess=caIssuers;URI:http://127.0.0.1:%d/%s\n" % (cls.http_port, issuer))

        class Files(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=d, **kw)

            def log_message(self, *a):
                pass
        cls.srv_http = http.server.ThreadingHTTPServer(("127.0.0.1", cls.http_port), Files)
        threading.Thread(target=cls.srv_http.serve_forever, daemon=True).start()
        cls.tls = []
        for name in ("leaf", "leaf2"):
            port = cls.tls_port if name == "leaf" else _free_port()
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Files)
            sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            sctx.load_cert_chain(os.path.join(d, name + ".pem"), os.path.join(d, name + ".key"))  # без цепочки
            srv.socket = sctx.wrap_socket(srv.socket, server_side=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.tls.append((srv, port))
        with open(os.path.join(d, "ok.txt"), "w") as f:
            f.write("OK")

    @classmethod
    def tearDownClass(cls):
        cls.srv_http.shutdown()
        for srv, _ in cls.tls:
            srv.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def client(self):
        import ssl
        from okolib import net
        orig = net._ssl_context
        net._ssl_context = lambda: ssl.create_default_context(cafile=os.path.join(self.dir, "root.pem"))
        self.addCleanup(setattr, net, "_ssl_context", orig)
        return HttpClient(None, allow_private=True)

    def test_aia_completion(self):
        r = self.client().get("https://localhost:%d/ok.txt" % self.tls[0][1], retries=0, timeout=10)
        self.assertEqual(r.body, b"OK")

    def test_self_signed_issuer_rejected(self):
        with self.assertRaises(FetchError) as cm:
            self.client().get("https://localhost:%d/ok.txt" % self.tls[1][1], retries=0, timeout=10)
        self.assertIn("SSL", str(cm.exception))


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
                  "t_to": now, "tz_offset": 300, "origins": exp["origins"]}
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
        # Telegram: сообщения канала по теме, пересланное — с первоисточником; без темы и старые — нет
        tg = [it for it in items.values() if it["prov"] == ["telegram"]]
        self.assertEqual({it["url"] for it in tg}, {"https://t.me/kunuzofficial/90001", "https://t.me/kunuzofficial/90002"})
        self.assertTrue(all(it["kind"] == "social" and it["extra"]["platform"] == "telegram" for it in tg))
        fwd = [it for it in tg if it["extra"].get("fwd")]
        self.assertEqual(fwd[0]["extra"]["fwd"]["name"], "Prezident matbuot xizmati")
        # «найдено по»: ключевое слово, сработавший термин и запрос
        for it in items.values():
            self.assertEqual(it.get("kw"), "Узбекистан", it["title"])
            self.assertTrue(it.get("q"), it["title"])
        rel = [it for it in items.values() if it.get("role") == "related"]
        self.assertTrue(any("Мирзиёев" in it["of"] for it in rel), [it["title"] for it in rel])
        gn = [it for it in items.values() if any(x["t"].startswith("Google News") for x in it["q"])]
        self.assertTrue(gn and all("Uzbekistan" in x["q"] or "Узбекистан" in x["q"] or x["q"]
                                   for it in gn for x in it["q"]))
        self.assertTrue(done.get("report"))
        rep = json.load(self.call("/api/reports/" + urllib.request.quote(done["report"])))
        self.assertEqual(len(rep["items"]), len(items))

    def _stream(self, params):
        items, done = {}, None
        for block in self.call("/api/search", params).read().decode("utf-8").split("\n\n"):
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
        return items, done

    def test_reports_mode(self):
        now = int(time.time())
        items, done = self._stream({"mode": "reports", "topics": [], "langs": ["en"], "plan": {},
                                    "t_from": now - 7 * 86400, "t_to": now})
        self.assertIsNotNone(done)
        by_title = {it["title"]: it for it in items.values()}
        hdr = by_title["UNDP launches Human Development Report 2026: inequality widens"]
        self.assertEqual((hdr["kind"], hdr["extra"]["report"]), ("report", "hdr"))
        self.assertEqual(by_title["Global Peace Index 2026: Central Asia among most improved regions"]["extra"]["report"], "gpi")
        self.assertNotIn("Celebrity chef opens new restaurant in Paris", by_title)   # не доклад

    def test_social_mode(self):
        langs = ["ru", "en", "uz"]
        exp = json.load(self.call("/api/expand", {"topics": ["Узбекистан"], "langs": langs, "related": False}))
        now = int(time.time())
        items, done = self._stream({"mode": "social", "topics": ["Узбекистан"], "langs": langs, "plan": exp["plan"],
                                    "origins": exp["origins"], "providers": ["telegram", "gnews"],
                                    "t_from": now - 7 * 86400, "t_to": now})
        self.assertIsNotNone(done)
        self.assertTrue(items)
        self.assertTrue(all(it["kind"] == "social" for it in items.values()))   # только соцсети, gnews отброшен
        self.assertIn("https://t.me/kunuzofficial/90001", {it["url"] for it in items.values()})

    def test_watch_mode(self):
        now = int(time.time())
        items, done = self._stream({"mode": "watch", "topics": [], "langs": ["ru", "en", "uz"], "plan": {},
                                    "sources": ["kun_uz"], "channels": [{"platform": "telegram", "id": "kunuzofficial"}],
                                    "t_from": now - 86400, "t_to": now})
        self.assertIsNotNone(done)
        urls = {it["url"] for it in items.values()}
        self.assertIn("https://t.me/kunuzofficial/90003", urls)      # в мониторинге — все публикации, не только по теме
        self.assertTrue(any("kun.uz" in u for u in urls))
        self.assertFalse(any("reuters" in u for u in urls))          # только выбранные источники

    def test_article_mentions(self):
        # поисковик нашёл статью, где тема не видна в заголовке: проверяем упоминания на странице
        m = json.load(self.call("/api/article", {
            "url": "https://carnegieendowment.org/research/2026/09/central-asia-washington",
            "terms": ["Uzbekistan", "Tashkent", "uzbek"], "ctx": ["minerals"]}))
        self.assertTrue(m["ok"])
        mm = m["mentions"]
        self.assertEqual(mm["hits"], 2)
        self.assertEqual(mm["first"], 1)
        self.assertTrue(mm["ctx"])
        self.assertIn("Uzbekistan", mm["samples"][0])
        self.assertEqual(relevance.level({"hit": "engine"}, mm), "body")
        self.assertEqual(relevance.level({"hit": "engine"}, dict(mm, hits=1, first=3)), "passing")
        self.assertEqual(relevance.level({"hit": "engine"}, dict(mm, hits=0, first=None)), "absent")
        self.assertEqual(relevance.level({"hit": "engine"}), "unverified")
        self.assertEqual(relevance.level({"hit": "title", "role": "related"}), "rtitle")

    def test_person_profile_and_expand(self):
        c = json.load(self.call("/api/person/search?q=" + urllib.request.quote("Мирзиёев")))["candidates"]
        self.assertEqual([x["id"] for x in c], ["Q999001"])            # фамилия-«не человек» отброшена
        p = json.load(self.call("/api/person/Q999001"))
        self.assertEqual(p["positions"][0]["label"], "Президент Узбекистана")
        self.assertEqual(p["positions"][0]["from"], "2016-12-14")
        self.assertEqual(p["born"], "1957-07-24")
        self.assertEqual({x["platform"] for x in p["socials"]}, {"x", "telegram"})
        self.assertIn("Shavkat Miromonovich Mirziyoyev", p["names"]["en"])
        self.assertNotIn("Mirziyoyev", p["names"]["en"])              # одна фамилия — слишком неоднозначно
        exp = json.load(self.call("/api/expand", {"topics": ["Шавкат Мирзиёев"], "langs": ["ru", "en", "ja", "tr"],
                                                  "persons": {"Шавкат Мирзиёев": "Q999001"}}))
        self.assertEqual(exp["plan"]["ja"]["q"][0], "シャヴカト・ミルズィヨエフ")
        self.assertEqual(exp["plan"]["tr"]["q"][0], "Shavkat Mirziyoyev")  # нет турецкого — английское написание

    def test_osint(self):
        e = json.load(self.call("/api/osint", {"value": "info@example-analytics.uz"}))
        self.assertEqual(e["type"], "email")
        facts = {f["k"]: f["v"] for f in e["facts"]}
        self.assertEqual(facts["Домен зарегистрирован"], "2014-03-11")
        checks = {c["name"]: c["status"] for c in e["checks"]}
        self.assertEqual(checks["Почтовый сервер (MX)"], "ok")
        self.assertEqual(checks["Публичный профиль Gravatar"], "none")
        u = json.load(self.call("/api/osint", {"value": "@okoanalyst"}))
        st = {c["name"]: (c["status"], c["detail"]) for c in u["checks"]}
        self.assertEqual(st["GitHub"][0], "found")
        self.assertIn("Tashkent", st["GitHub"][1])
        self.assertEqual(st["Telegram"], ("found", "OKO Analyst · 1 250 subscribers"))
        self.assertEqual(st["Reddit"][0], "none")
        d = json.load(self.call("/api/osint", {"value": "example-analytics.uz"}))
        facts = {f["k"]: f["v"] for f in d["facts"]}
        self.assertEqual(facts["Регистратор"], "UZINFOCOM")
        self.assertEqual(facts["Первая копия в веб-архиве"], "2014-04-12")
        self.assertEqual(facts["Заголовок страницы"], "Центр анализа — Главная")
        ph = json.load(self.call("/api/osint", {"value": "+998 90 123-45-67"}))
        facts = {f["k"]: f["v"] for f in ph["facts"]}
        self.assertEqual(ph["type"], "phone")
        self.assertEqual(facts["Страна по коду"], "Узбекистан")
        self.assertTrue(facts["Оператор (по коду сети)"].startswith("Beeline"))

    def test_social_catalog_translate_settings(self):
        so = json.load(self.call("/api/social?q=" + urllib.request.quote("Узбекистан")))
        self.assertIn("telegram", so["platforms"])
        self.assertFalse(so["keys"]["brave"])
        self.assertEqual(len(so["links"]), len(so["platforms"]))
        cat = json.load(self.call("/api/catalog/reports"))
        self.assertGreater(len(cat["reports"]), 50)
        tr = json.load(self.call("/api/translate", {"texts": ["газ", "газ"], "to": "en"}))
        self.assertEqual(tr["texts"], ["gas", "gas"])          # фикстура переводчика всегда отвечает «gas»
        self.assertEqual(tr["engine"], "Google")
        # два заголовка — одним пакетным запросом (запасной веб-интерфейс Google)
        tr = json.load(self.call("/api/translate", {"texts": ["Uzbekistan signs deal", "Tashkent to host summit"],
                                                    "from": "en"}))
        self.assertEqual(tr["texts"], ["Узбекистан подписал соглашение", "Ташкент примет саммит"])
        # три — пакет не совпал по числу, каждый переводится отдельно
        tr = json.load(self.call("/api/translate", {"texts": ["a", "b", "c"], "from": "en"}))
        self.assertEqual(tr["texts"], ["gas", "gas", "gas"])
        self.assertEqual(tr["failed"], 0)
        art = json.load(self.call("/api/translate/article", {
            "url": "https://carnegieendowment.org/research/2026/09/central-asia-washington"}))
        self.assertTrue(art["ok"])
        self.assertTrue(all(b.get("tr") for b in art["blocks"]))
        st = json.load(self.call("/api/settings", {"brave_key": "BSA-secret-12345"}))
        self.assertEqual(st["brave_key"], "••••2345")
        self.assertTrue(st["brave_key_set"])
        st = json.load(self.call("/api/settings", {"brave_key": st["brave_key"]}))   # маска не затирает ключ
        self.assertTrue(st["brave_key_set"])
        st = json.load(self.call("/api/settings", {"brave_key": ""}))
        self.assertFalse(st["brave_key_set"])

    def test_article_deep_check(self):
        url = urllib.request.quote("https://www.yahoo.com/news/uzbekistan-us-sign-critical-minerals-1.html", safe="")
        m = json.load(self.call("/api/article?url=" + url))
        self.assertTrue(m["ok"])
        self.assertEqual(m["canonical_domain"], "reuters.com")
        self.assertEqual(m["canonical_source"], "reuters")


def _lan_ip():
    sys.path.insert(0, ROOT)
    import oko
    ips = [ip for ip in oko.lan_addresses() if not ip.startswith("127.")]
    return ips[0] if ips else None


@unittest.skipUnless(_lan_ip(), "нет сетевого интерфейса, кроме loopback")
class TestLan(unittest.TestCase):
    """Доступ с телефона: вход по паролю, защита от подмены Host, локальный доступ без пароля."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.tmp, "state"))
        with open(os.path.join(cls.tmp, "state", "settings.json"), "w") as f:
            json.dump({"lan_password": "correct horse 12"}, f)
        cls.port = _free_port()
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "oko.py"), "--no-browser", "--lan", "--port",
                                     str(cls.port), "--data", cls.tmp, "--fixtures", FIX],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        cls.ip = _lan_ip()
        cls.remote = "http://%s:%d" % (cls.ip, cls.port)
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/" % cls.port, timeout=2).read()
                break
            except OSError:
                time.sleep(0.2)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None
        cls.opener = urllib.request.build_opener(NoRedirect)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        if cls.proc.stdout:
            cls.proc.stdout.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, path, data=None, headers=None):
        r = urllib.request.Request(self.remote + path, data=data, headers=headers or {})
        try:
            resp = self.opener.open(r, timeout=10)
            return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_login_flow(self):
        st, h, _ = self.req("/")
        self.assertEqual((st, h.get("Location")), (303, "/login"))
        self.assertEqual(self.req("/api/bootstrap")[0], 401)
        self.assertEqual(self.req("/assets/oko.css")[0], 200)
        self.assertEqual(self.req("/login", b"password=wrong")[0], 401)
        st, h, _ = self.req("/login", b"password=correct+horse+12")
        self.assertEqual(st, 303)
        cookie = h["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", h["Set-Cookie"])
        st, _, body = self.req("/", headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        self.assertIn(b'name="oko-token" content="', body)
        token = body.decode().split('name="oko-token" content="')[1].split('"')[0]
        st, _, body = self.req("/api/health", headers={"Cookie": cookie, "X-OKO-Token": token})
        self.assertEqual(st, 200)
        # подмена Host (DNS rebinding) — отказ
        self.assertEqual(self.req("/", headers={"Host": "evil.example:%d" % self.port, "Cookie": cookie})[0], 421)
        # с этого же компьютера — без пароля
        body = urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=5).read()
        self.assertIn(b'name="oko-token"', body)

    def test_login_rate_limit(self):
        codes = [self.req("/login", b"password=nope%d" % i)[0] for i in range(7)]
        self.assertIn(429, codes)


class TestTelegramBot(unittest.TestCase):
    """Бот на фикстурах: доступ только разрешённым, поиск по теме → сообщение и HTML-сводка."""

    @classmethod
    def setUpClass(cls):
        from okolib.server import App
        from okolib.tgbot import TgBot
        cls.tmp = tempfile.mkdtemp()
        cls.app = App(ROOT, data_dir=cls.tmp, fixtures=FIX, port=_free_port())
        cls.app.state.update_settings({"tg_bot_allowed": [111], "tg_bot_topic": "Узбекистан"})
        cls.bot = TgBot(cls.app)
        cls.calls = []
        cls.bot.api = lambda method, params=None, files=None, timeout=20: cls.calls.append((method, params, files))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def msg(self, uid, text):
        self.calls.clear()
        self.bot.handle({"chat": {"id": uid}, "from": {"id": uid}, "text": text})
        return [c for c in self.calls if c[0] == "sendMessage"], [c for c in self.calls if c[0] == "sendDocument"]

    def test_access_and_help(self):
        sent, _ = self.msg(999, "Узбекистан")
        self.assertIn("Доступ запрещён", sent[0][1]["text"])
        self.assertIn("999", sent[0][1]["text"])
        sent, _ = self.msg(111, "/start")
        self.assertIn("доступ разрешён", sent[0][1]["text"])

    def test_search_digest(self):
        sent, docs = self.msg(111, "Узбекистан")
        text = "\n".join(c[1]["text"] for c in sent)
        self.assertIn("ОКО · Узбекистан", text)
        self.assertIn("[A]", text)
        self.assertIn("⌕", text)                                   # по какому слову найдено
        self.assertEqual(len(docs), 1)
        name, content, ctype = docs[0][2]["document"]
        self.assertTrue(name.endswith(".html"))
        self.assertIn("Уровень A", content.decode("utf-8"))

    def test_digest_schedule(self):
        sent, _ = self.msg(111, "/digest 08:30 Центральная Азия")
        self.assertIn("08:30", sent[0][1]["text"])
        dig = self.app.state.settings()["tg_bot_digest"]
        self.assertEqual(dig[-1], {"chat": 111, "time": "08:30", "topic": "Центральная Азия"})
        self.msg(111, "/digest off")
        self.assertEqual(self.app.state.settings()["tg_bot_digest"], [])


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
