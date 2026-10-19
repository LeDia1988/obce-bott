#!/usr/bin/env python3
"""
Obce-bot: denne prejde weby obcí (Košický + Prešovský kraj), nájde úradnú tabuľu,
oznamy, zastupiteľstvo, uznesenia a rozpočet, porovná so včerajškom a nové
dokumenty s témami (ihriská, športoviská, workout, oplotenie, mobiliár,
zastávky, dotácie) zapíše do data/latest.json a data/daily/YYYY-MM-DD.json.

Spustenie:  python bot.py            (bežný denný beh)
            python bot.py --rediscover  (nanovo nájde podstránky všetkých obcí)
"""
import csv, json, os, re, sys, subprocess, tempfile, time, unicodedata, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SOURCES = os.path.join(DATA, "sources.json")   # obec -> zoznam sledovaných podstránok
SEEN = os.path.join(DATA, "seen.json")         # obec -> už videné odkazy
WORKERS = 24
TIMEOUT = 20
MAX_DOC_BYTES = 15 * 1024 * 1024
MAX_DOCS_PER_OBEC = 15
REDISCOVER_DAYS = 7
UA = "Mozilla/5.0 (compatible; obce-bot/1.0; sledovanie uradnych tabul)"

# ---------------------------------------------------------------- slová
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()

# podstránky, ktoré sa oplatí sledovať (hľadá sa v texte a URL odkazu)
SECTION_WORDS = [
    "uradna tabula", "uradna-tabula", "uradnatabula", "oznam", "aktualit", "zastupitel",
    "uznesen", "zapisnic", "pozvank", "rozpocet", "rozpoct", "zasadnut", "samosprav",
    "dokument", "zverejnovan", "verejne obstaravan", "verejne-obstaravan", "zakazk",
    "vyzv", "dotaci", "projekt", "novinky", "spravy",
]

# témy, ktoré vieme zabezpečiť  ->  (názov, regex nad normalizovaným textom)
TOPICS = [
    ("Detské ihrisko", r"\bihrisk\w*|\bdetsk\w* (hrac|ihr)\w*|hracie prvk\w*|hraci\w* prv\w*"),
    ("Športovisko", r"\bsportovisk\w*|\bmultifunkcn\w*|\bsportov\w* (are|plo|zari|infra|park)\w*|\bpumptrack\w*|\bskatepark\w*"),
    ("Workout / fitness", r"\bworkout\w*|\bfitnes\w*|\bstreet ?workout|\bposilnov\w* (pod|pri|vonk)\w*|\bvonkajs\w* posil\w*"),
    ("Oplotenie", r"\boploten\w*|\bplot(u|y|om|ov|e)?\b|\bpletiv\w*|\b3d panel\w*"),
    ("Mobiliár", r"\bmobiliar\w*|\blavic\w*|\bodpadkov\w* kos\w*|\bstojan\w* na bicyk\w*|\baltan\w*|\bpergol\w*"),
    ("Zastávka", r"\bzastavk\w*|\bautobusov\w* zastav\w*|\bprist\w*resk\w*"),
    ("Park / oddych", r"\boddychov\w* (zon|are|park)\w*|\bverejn\w* priestranstv\w*|\brevitaliz\w*|\bvolnocas\w*"),
    ("Dotácia / výzva", r"\bihrisko pre kazde dieta\b|\benvirofond\w*|\bregionaln\w* prispev\w*|\bmirri\b|"
                        r"\bnenavratn\w* financn\w* prispev\w*|\bziadost\w* o (dotaci|nfp|poskytnut)\w*|\bfond na podporu sportu\b|"
                        r"\bprogram obnovy dediny\b|\bdotaci\w* (ksk|psk|z kosick|z presov)\w*|\bspolufinancovan\w*"),
]
TOPIC_RE = [(n, re.compile(p)) for n, p in TOPICS]

# typ dokumentu
DOCTYPES = [
    ("Pozvánka na zastupiteľstvo", r"pozvank\w*|zasadnut\w* (obecn|mestsk)\w* zastup|program (rokovan|zasadnut)\w*|zvolava\w*"),
    ("Rozpočet / zmena rozpočtu", r"rozpoc\w*|rozpoctov\w* opatren\w*"),
    ("Uznesenie / zápisnica", r"uznesen\w*|zapisnic\w*"),
    ("Verejné obstarávanie", r"verejn\w* obstarav\w*|vyzv\w* na predloz\w*|prieskum trhu|zakazk\w*|vyzv\w* na predkladan\w* ponuk"),
    ("Návrh VZN / zámer", r"\bvzn\b|zamer\w*|navrh\w*"),
]
DOCTYPE_RE = [(n, re.compile(p)) for n, p in DOCTYPES]

DOC_EXT = (".pdf", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx")
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".rar", ".mp4", ".mp3")
# typické odkazy, ktoré sú na každej stránke a nie sú oznamom
NOISE = re.compile(r"facebook|instagram|youtube|twitter|google\.|mailto:|tel:|javascript:|#$|cookie|gdpr|"
                   r"vyhlasenie-o-pristupnosti|mapa-stranky|sitemap|login|prihlas", re.I)


# ---------------------------------------------------------------- HTTP
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "sk,cs;q=0.8"})


def get(url, stream=False):
    r = session.get(url, timeout=TIMEOUT, allow_redirects=True, stream=stream)
    r.raise_for_status()
    return r


def soup_of(resp):
    resp.encoding = resp.apparent_encoding if not resp.encoding or resp.encoding.lower() == "iso-8859-1" else resp.encoding
    return BeautifulSoup(resp.text, "lxml")


def same_site(a, b):
    ha, hb = urlparse(a).netloc.lower().removeprefix("www."), urlparse(b).netloc.lower().removeprefix("www.")
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def links_of(soup, base):
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if NOISE.search(href):
            continue
        url = urljoin(base, href).split("#")[0]
        if not url.startswith("http"):
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        if not text:
            text = a.get("title", "") or os.path.basename(urlparse(url).path)
        # kontext: nadpis/riadok, v ktorom odkaz je (dátum, popis)
        parent = a.find_parent(["li", "tr", "article", "p", "div"])
        ctx = " ".join(parent.get_text(" ", strip=True).split())[:400] if parent else ""
        out.append({"url": url, "text": text[:300], "ctx": ctx})
    return out


# ---------------------------------------------------------------- discovery
def discover(obec):
    """Nájde na webe obce podstránky úradnej tabule, oznamov, zastupiteľstva..."""
    web = obec["web"]
    if not web:
        return {"status": "bez webu", "pages": []}
    try:
        r = get(web)
    except Exception as e:
        return {"status": f"web nedostupný: {type(e).__name__}", "pages": []}
    base = r.url
    s = soup_of(r)
    cand = {}
    for l in links_of(s, base):
        u = l["url"]
        if not same_site(u, base) and "e-obce" not in u and "obce.info" not in u and "egov" not in u:
            continue
        if u.lower().endswith(DOC_EXT + SKIP_EXT):
            continue
        key = norm(l["text"] + " " + urlparse(u).path.replace("-", " ").replace("_", " "))
        score = sum(1 for w in SECTION_WORDS if w in key)
        if "uradna tabula" in key or "uradnatabula" in key:
            score += 5
        if "zastupitel" in key or "uznesen" in key or "pozvank" in key:
            score += 3
        if "rozpoc" in key:
            score += 2
        if score:
            cand[u] = max(cand.get(u, 0), score)
    pages = [u for u, _ in sorted(cand.items(), key=lambda x: -x[1])[:8]]
    if base not in pages:
        pages.append(base)  # aj titulka (aktuality bývajú tam)
    return {"status": "ok", "pages": pages, "base": base,
            "discovered": datetime.date.today().isoformat()}


# ---------------------------------------------------------------- dokumenty
def doc_text(url):
    """Stiahne PDF/DOC a vráti text (prvých ~60 tis. znakov)."""
    try:
        r = get(url, stream=True)
        ln = int(r.headers.get("content-length") or 0)
        if ln > MAX_DOC_BYTES:
            return ""
        buf = b""
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > MAX_DOC_BYTES:
                return ""
        ctype = r.headers.get("content-type", "").lower()
        path = urlparse(r.url).path.lower()
        with tempfile.TemporaryDirectory() as td:
            if "pdf" in ctype or path.endswith(".pdf") or buf[:4] == b"%PDF":
                f = os.path.join(td, "d.pdf")
                open(f, "wb").write(buf)
                out = subprocess.run(["pdftotext", "-l", "40", "-layout", f, "-"], capture_output=True, timeout=60)
                return out.stdout.decode("utf-8", "ignore")[:60000]
            if path.endswith((".docx", ".odt")) or buf[:2] == b"PK":
                import zipfile, io
                try:
                    z = zipfile.ZipFile(io.BytesIO(buf))
                    name = "word/document.xml" if "word/document.xml" in z.namelist() else "content.xml"
                    xml = z.read(name).decode("utf-8", "ignore")
                    return re.sub(r"<[^>]+>", " ", xml)[:60000]
                except Exception:
                    return ""
            if "html" in ctype:
                return BeautifulSoup(buf, "lxml").get_text(" ", strip=True)[:60000]
            return buf.decode("cp1250", "ignore")[:20000]  # .doc / .rtf – hrubý text
    except Exception:
        return ""


def snippets(text, rx, n=3):
    t = " ".join(text.split())
    nt = norm(t)
    out = []
    for m in rx.finditer(nt):
        a, b = max(0, m.start() - 140), min(len(t), m.end() + 160)
        out.append("…" + t[a:b] + "…")
        if len(out) >= n:
            break
    return out


def money(text):
    m = re.findall(r"(\d{1,3}(?:[ . ]\d{3})+(?:,\d{2})?|\d{4,7}(?:,\d{2})?)\s?(?:€|eur\b|eur\.)", text, re.I)
    vals = []
    for x in m[:30]:
        try:
            v = float(re.sub(r"[ . ]", "", x).replace(",", "."))
            if 1000 <= v <= 5_000_000:
                vals.append(v)
        except ValueError:
            pass
    return sorted(set(vals), reverse=True)[:5]


def classify(text):
    nt = norm(text)
    topics = [n for n, rx in TOPIC_RE if rx.search(nt)]
    types = [n for n, rx in DOCTYPE_RE if rx.search(nt)]
    return topics, types


# ---------------------------------------------------------------- jedna obec
def check(obec, src, seen_urls, baseline):
    new_items = []
    all_urls = set()
    for page in src.get("pages", []):
        try:
            r = get(page)
        except Exception:
            continue
        s = soup_of(r)
        for l in links_of(s, r.url):
            u = l["url"]
            if u.lower().endswith(SKIP_EXT):
                continue
            all_urls.add(u)
            if u in seen_urls or baseline:
                continue
            # nové len to, čo vyzerá ako oznam/dokument (nie menu)
            head = l["text"] + " " + l["ctx"]
            is_doc = urlparse(u).path.lower().endswith(DOC_EXT) or "download" in u.lower() or "subor" in u.lower()
            if not is_doc and not same_site(u, src.get("base", obec["web"])):
                continue
            new_items.append({"url": u, "title": l["text"], "ctx": l["ctx"], "page": page, "is_doc": is_doc})
    # vyhodnotenie nových
    findings = []
    checked = 0
    for it in new_items:
        head = it["title"] + " " + it["ctx"]
        topics, types = classify(head)
        body = ""
        # do dokumentu sa pozrieme, ak je to dokument zastupiteľstva/rozpočtu/oznam, alebo už nadpis trafil tému
        if checked < MAX_DOCS_PER_OBEC and (it["is_doc"] or topics or types):
            body = doc_text(it["url"])
            checked += 1
            if body:
                t2, ty2 = classify(body)
                topics = sorted(set(topics) | set(t2), key=[n for n, _ in TOPICS].index)
                types = sorted(set(types) | set(ty2), key=[n for n, _ in DOCTYPES].index)
        if not topics:
            continue
        sn = []
        for n, rx in TOPIC_RE:
            if n in topics:
                sn += snippets(body or head, rx, 2)
        findings.append({
            "obec": obec["nazov"], "statut": obec["statut"], "okres": obec["okres"], "kraj": obec["kraj"],
            "kod": obec["kod"], "title": it["title"], "url": it["url"], "zdroj": it["page"],
            "temy": topics, "typ": types, "sumy_eur": money(body) if body else [],
            "ukazky": list(dict.fromkeys(sn))[:5],
        })
    return findings, all_urls


# ---------------------------------------------------------------- main
def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def main():
    rediscover = "--rediscover" in sys.argv
    limit = None
    for a in sys.argv:
        if a.startswith("--limit="):
            limit = int(a.split("=")[1])
    obce = list(csv.DictReader(open(os.path.join(ROOT, "obce.csv"), encoding="utf-8")))
    if limit:
        obce = obce[:limit]
    sources = load(SOURCES, {})
    seen = load(SEEN, {})
    today = datetime.date.today()

    # 1) discovery (nové obce, alebo raz za týždeň)
    todo = []
    for o in obce:
        s = sources.get(o["kod"])
        stale = not s or rediscover or not s.get("discovered") or \
            (today - datetime.date.fromisoformat(s["discovered"])).days >= REDISCOVER_DAYS or s.get("status") != "ok"
        if stale:
            todo.append(o)
    print(f"discovery: {len(todo)} obcí", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(discover, o): o for o in todo}
        for f in as_completed(futs):
            o = futs[f]
            sources[o["kod"]] = f.result()
    save(SOURCES, sources)

    # 2) kontrola
    findings, stats = [], {"ok": 0, "chyba": 0, "baseline": 0}
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {}
        for o in obce:
            src = sources.get(o["kod"], {})
            if src.get("status") != "ok":
                stats["chyba"] += 1
                continue
            baseline = o["kod"] not in seen   # prvý beh pre obec = len zapamätať
            if baseline:
                stats["baseline"] += 1
            futs[ex.submit(check, o, src, set(seen.get(o["kod"], [])), baseline)] = o
        for f in as_completed(futs):
            o = futs[f]
            try:
                fnd, urls = f.result()
            except Exception as e:
                print("chyba", o["nazov"], e)
                stats["chyba"] += 1
                continue
            stats["ok"] += 1
            findings += fnd
            old = seen.get(o["kod"], [])
            merged = list(dict.fromkeys(list(urls) + old))[:3000]
            seen[o["kod"]] = merged
    save(SEEN, seen)

    findings.sort(key=lambda x: (x["kraj"], x["okres"], x["obec"]))
    report = {
        "datum": today.isoformat(), "vygenerovane": datetime.datetime.now().isoformat(timespec="seconds"),
        "obci_spolu": len(obce), "obci_skontrolovanych": stats["ok"], "obci_nedostupnych": stats["chyba"],
        "obci_prvy_beh": stats["baseline"], "trvanie_s": int(time.time() - t0),
        "nalezy": findings,
        "nedostupne": sorted(f'{o["nazov"]} ({o["okres"]}): {sources.get(o["kod"], {}).get("status", "?")}'
                             for o in obce if sources.get(o["kod"], {}).get("status") != "ok"),
    }
    save(os.path.join(DATA, "daily", f"{today.isoformat()}.json"), report)
    save(os.path.join(DATA, "latest.json"), report)
    print(f"hotovo: {len(findings)} nálezov, {stats}", flush=True)


if __name__ == "__main__":
    main()
