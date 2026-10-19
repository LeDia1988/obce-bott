#!/usr/bin/env python3
"""
Obce-bot, modul 2: obstarávania, výzvy, zmluvy a prepojenia projektantov.

Zdroje:
  - ÚVO (vyhľadávanie zákaziek podľa názvu)        -> obstarávania
  - Josephine (zoznam verejných obstarávaní)        -> obstarávania
  - TED (EÚ vestník, API, CPV kódy, Košický+Prešovský kraj)
  - CRZ (Centrálny register zmlúv: predmet zmluvy + sledované firmy) -> zmluvy, prepojenia
  - výzvy ministerstiev, fondov, krajov a nadácií (vyzvy.csv)       -> výzvy

Výstup: data/zdroje_latest.json, data/zdroje/YYYY-MM-DD.json, data/prepojenia.csv
"""
import csv, json, os, re, sys, datetime, time
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from bot import norm, TOPIC_RE, session, save, load, ROOT, DATA

TODAY = datetime.date.today()
SEEN = os.path.join(DATA, "zdroje_seen.json")
PREP = os.path.join(DATA, "prepojenia.csv")

# ----------------------------------------------------------------- kľúčové slová
# hľadané výrazy pre vyhľadávače (ÚVO, CRZ)
QUERIES = ["ihrisk", "ihrisko", "športovisk", "workout", "fitnes", "oplotenie", "mobiliár", "lavič",
           "zastávk", "prístrešok", "altán", "park", "oddychov", "revitaliz", "náučn", "turistick",
           "cyklo", "rozhľad", "edukačn", "pumptrack", "skatepark", "multifunkčn", "verejného priestranstva",
           "dopadov", "hracie prvky", "hracích prvkov"]
# relevantnosť názvu zákazky/zmluvy (normalizovaný text)
REL = re.compile(
    r"ihrisk|sportovisk|workout|fitnes|oploten|\bplot(u|y|om)?\b|mobiliar|lavic|zastavk|pristres|altan|"
    r"\bpark|oddychov|revitaliz|nauc\w* chodnik|turistick|cyklotras|cyklochodnik|rozhladn|edukacn\w* tabul|"
    r"pumptrack|skatepark|multifunkcn|verejn\w* priestranstv|hraci\w* prv|dopadov\w* ploch|detsk\w* (kut|hrac)|"
    r"exterierov\w* ucebn|vonkajs\w* ucebn|sportov\w* (are|plo|zari|infra|park)|vychodisk\w* (ihr|hrac)")
PROJECT = re.compile(r"projekt|stud(ia|ie|iu|ii)|dokumentaci|architekt|urbanist|dizajn|navrh")
# kraje
EAST = re.compile(r"kosick|presovsk|sk04|kosice|presov")
GRANT = re.compile(r"vyzv|dotaci|grant|prispev|nenavratn|podpor|program|schema|fond|nfp|zoznam schvalen|vysledk", re.I)

# CPV kódy pre TED
CPV = ["37535200", "37535000", "37530000", "37400000", "37440000", "45236000", "45236100", "45236110",
       "45236200", "45212140", "45342000", "44313000", "34928400", "34928480", "39113600", "39113000",
       "45233161", "45112711", "45112720", "71220000", "71222000", "71420000", "45213316"]


def obce_names():
    """Normalizované názvy obcí/miest v sledovaných krajoch (na filter objednávateľa)."""
    names = {}
    for o in csv.DictReader(open(os.path.join(ROOT, "obce.csv"), encoding="utf-8")):
        n = norm(o["nazov"]).replace(" - ", "-").strip()
        names[n] = o
    return names


OBCE = obce_names()


def match_obec(text):
    """Nájde obec/mesto z našich krajov v názve obstarávateľa/objednávateľa."""
    t = norm(text).replace(" - ", "-")
    t = re.sub(r"\b(obec|mesto|mestska cast|obecny urad|mestsky urad|statutarne mesto)\b", " ", t)
    t = " ".join(t.replace(",", " ").split())
    if t in OBCE:
        return OBCE[t]
    # najdlhší názov obce, ktorý je celý v texte
    best = None
    for n, o in OBCE.items():
        if len(n) >= 4 and re.search(r"(^|\s)" + re.escape(n) + r"(\s|$)", t):
            if not best or len(n) > len(norm(best["nazov"])):
                best = o
    return best


def firmy():
    p = os.path.join(ROOT, "firmy.csv")
    if not os.path.exists(p):
        return []
    return [f for f in csv.DictReader(open(p, encoding="utf-8")) if f.get("hladat")]


def table_rows(html, base):
    s = BeautifulSoup(html, "lxml")
    t = s.find("table")
    out = []
    if not t:
        return out
    for tr in t.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        cells = [" ".join(td.get_text(" ", strip=True).split()) for td in tds]
        links = [urljoin(base, a["href"]) for a in tr.find_all("a", href=True)]
        out.append((cells, links))
    return out


def safe_get(url, **kw):
    try:
        r = session.get(url, timeout=30, **kw)
        r.raise_for_status()
        return r
    except Exception as e:
        print("  !", url, type(e).__name__)
        return None


# ----------------------------------------------------------------- ÚVO
def uvo(seen):
    found = []
    for q in QUERIES:
        r = safe_get("https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek",
                     params={"nazovZakazky": q, "sort": "datumAktualizacie", "sort-dir": "DESC"})
        if not r:
            continue
        for cells, links in table_rows(r.text, r.url)[:40]:
            if len(cells) < 5 or not links:
                continue
            nazov, obst, cpv, nuts, akt = cells[:5]
            uid = "uvo:" + re.sub(r"\?.*", "", links[0])
            if uid in seen:
                continue
            seen.add(uid)
            o = match_obec(obst)
            if not (EAST.search(norm(nuts)) or o):
                continue
            if not REL.search(norm(nazov)):
                continue
            try:
                d = datetime.datetime.strptime(akt[:10], "%d.%m.%Y").date()
                if (TODAY - d).days > 14:
                    continue
            except ValueError:
                pass
            found.append({"zdroj": "ÚVO", "nazov": nazov, "obstaravatel": obst, "obec": o["nazov"] if o else "",
                          "okres": o["okres"] if o else "", "cpv": cpv, "nuts": nuts, "datum": akt, "url": links[0],
                          "projekcia": bool(PROJECT.search(norm(nazov)))})
        time.sleep(1)
    return found


# ----------------------------------------------------------------- Josephine
def josephine(seen):
    found = []
    for page in range(1, 9):
        r = safe_get("https://josephine.proebiz.com/sk/public-tenders/list", params={"page": page})
        if not r:
            break
        rows = table_rows(r.text, r.url)
        new_on_page = 0
        for cells, links in rows:
            links = [l for l in links if "/tender/" in l]
            if len(cells) < 6 or not links:
                continue
            uid = "jos:" + links[0]
            if uid in seen:
                continue
            new_on_page += 1
            seen.add(uid)
            nazov, obst = cells[2], cells[4]
            o = match_obec(re.sub(r"\s+SK\w*$", "", obst))
            if not (EAST.search(norm(obst)) or o):
                continue
            if not REL.search(norm(nazov)):
                continue
            found.append({"zdroj": "Josephine", "nazov": nazov, "obstaravatel": obst, "obec": o["nazov"] if o else "",
                          "okres": o["okres"] if o else "", "hodnota": cells[5], "lehota": cells[6] if len(cells) > 6 else "",
                          "url": links[0], "projekcia": bool(PROJECT.search(norm(nazov)))})
        if not new_on_page:
            break
        time.sleep(1)
    return found


# ----------------------------------------------------------------- TED (EÚ)
def ted(seen):
    found = []
    since = (TODAY - datetime.timedelta(days=10)).strftime("%Y%m%d")
    q = (f"classification-cpv IN ({' '.join(CPV)}) AND place-of-performance IN (SK041 SK042 SK04) "
         f"AND publication-date>={since}")
    try:
        r = session.post("https://api.ted.europa.eu/v3/notices/search", timeout=40, json={
            "query": q, "fields": ["notice-title", "publication-date", "buyer-name", "deadline-receipt-tender-date-lot",
                                   "estimated-value-glo", "classification-cpv"], "limit": 100})
        r.raise_for_status()
        data = r.json().get("notices", [])
    except Exception as e:
        print("  ! TED", e)
        return found
    for n in data:
        pid = n.get("publication-number")
        uid = "ted:" + str(pid)
        if uid in seen:
            continue
        seen.add(uid)
        title = n.get("notice-title", {})
        title = title.get("slk") or title.get("eng") or next(iter(title.values()), "") if isinstance(title, dict) else str(title)
        if isinstance(title, list):
            title = title[0]
        buyer = n.get("buyer-name", {})
        buyer = (buyer.get("slk") or next(iter(buyer.values()), [""])) if isinstance(buyer, dict) else buyer
        buyer = buyer[0] if isinstance(buyer, list) else buyer
        o = match_obec(buyer or "")
        found.append({"zdroj": "TED (EÚ)", "nazov": title, "obstaravatel": buyer, "obec": o["nazov"] if o else "",
                      "okres": o["okres"] if o else "", "datum": n.get("publication-date", "")[:10],
                      "url": f"https://ted.europa.eu/sk/notice/-/detail/{pid}", "projekcia": bool(PROJECT.search(norm(title)))})
    return found


# ----------------------------------------------------------------- CRZ
CRZ = "https://www.crz.gov.sk/2171273-sk/centralny-register-zmluv/"


def crz_rows(params, pages=3):
    out = []
    for p in range(pages):
        pr = dict(params)
        if p:
            pr["page"] = p
        r = safe_get(CRZ, params=pr)
        if not r:
            break
        rows = table_rows(r.text, r.url)
        if not rows:
            break
        for cells, links in rows:
            links = [l for l in links if "/zmluva/" in l]
            if len(cells) < 5 or not links:
                continue
            out.append({"datum": cells[0], "nazov": cells[1], "suma": cells[2], "dodavatel": cells[3],
                        "objednavatel": cells[4], "url": links[0]})
        if len(rows) < 20:
            break
        time.sleep(1)
    return out


def crz(seen):
    zmluvy, prepojenia = [], []
    od = (TODAY - datetime.timedelta(days=7)).strftime("%d.%m.%Y")
    # a) predmet zmluvy obsahuje naše témy, objednávateľ je obec z KE/PO kraja
    for q in QUERIES:
        for z in crz_rows({"art_predmet": q, "art_datum_zverejnene_od": od}, pages=2):
            uid = "crz:" + z["url"]
            if uid in seen:
                continue
            seen.add(uid)
            o = match_obec(z["objednavatel"]) or match_obec(z["dodavatel"])
            if not o or not REL.search(norm(z["nazov"])):
                continue
            z.update({"obec": o["nazov"], "okres": o["okres"], "projekcia": bool(PROJECT.search(norm(z["nazov"])))})
            zmluvy.append(z)
            if z["projekcia"]:
                prepojenia.append({**z, "typ": "projektant (z CRZ)", "firma": z["dodavatel"]})
    # b) sledované firmy (projektanti, konkurencia) – všetky ich nové zmluvy
    od30 = (TODAY - datetime.timedelta(days=30)).strftime("%d.%m.%Y")
    for f in firmy():
        for z in crz_rows({"art_zs2": f["hladat"], "art_datum_zverejnene_od": od30}, pages=2):
            uid = "crzf:" + z["url"]
            if uid in seen:
                continue
            seen.add(uid)
            o = match_obec(z["objednavatel"])
            prepojenia.append({**z, "typ": f.get("typ", ""), "firma": f["nazov"], "obec": o["nazov"] if o else "",
                               "okres": o["okres"] if o else "", "relevantne": bool(REL.search(norm(z["nazov"])))})
        time.sleep(1)
    return zmluvy, prepojenia


# ----------------------------------------------------------------- výzvy
VYZ_SRC = os.path.join(DATA, "vyzvy_sources.json")
VYZ_WORDS = re.compile(r"vyzv|dotac|grant|prispev|podpor|program|schem|eurofond|financovan|projekt", re.I)


def vyzvy_discover(home):
    r = safe_get(home)
    if not r:
        return [home]
    s = BeautifulSoup(r.text, "lxml")
    cand = {}
    for a in s.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#")[0]
        if not u.startswith("http") or u.lower().endswith((".pdf", ".doc", ".docx", ".jpg", ".png")):
            continue
        key = norm(" ".join(a.get_text(" ", strip=True).split()) + " " + u.replace("-", " "))
        sc = len(VYZ_WORDS.findall(key)) + (3 if "vyzv" in key else 0) + (2 if "dotac" in key or "grant" in key else 0)
        if sc:
            cand[u] = max(cand.get(u, 0), sc)
    pages = [u for u, _ in sorted(cand.items(), key=lambda x: -x[1])[:6]]
    return [r.url] + [p for p in pages if p != r.url]


def vyzvy(seen, baseline_keys):
    found = []
    srcmap = load(VYZ_SRC, {})
    p = os.path.join(ROOT, "vyzvy.csv")
    for src in csv.DictReader(open(p, encoding="utf-8")):
        home = src["url"]
        st = srcmap.get(home)
        if not st or (TODAY - datetime.date.fromisoformat(st["d"])).days >= 7:
            st = {"d": TODAY.isoformat(), "pages": vyzvy_discover(home)}
            srcmap[home] = st
        for url in st["pages"]:
            key = "vyz-src:" + url
            first = key not in seen
            seen.add(key)
            r = safe_get(url)
            if not r:
                continue
            r.encoding = r.apparent_encoding if (r.encoding or "").lower() in ("", "iso-8859-1") else r.encoding
            s = BeautifulSoup(r.text, "lxml")
            for a in s.find_all("a", href=True):
                t = " ".join(a.get_text(" ", strip=True).split())
                if len(t) < 12:
                    continue
                u = urljoin(r.url, a["href"]).split("#")[0]
                uid = "vyz:" + u
                if uid in seen:
                    continue
                seen.add(uid)
                if first:
                    continue  # prvé načítanie stránky = len zapamätať
                nt = norm(t)
                if not GRANT.search(nt):
                    continue
                topics = [n for n, rx in TOPIC_RE if rx.search(nt)]
                found.append({"zdroj": src["nazov"], "kategoria": src.get("kategoria", ""), "nazov": t[:300],
                              "url": u, "temy": topics, "zhoda_tem": bool(topics or REL.search(nt))})
            time.sleep(0.5)
    save(VYZ_SRC, srcmap)
    return found


# ----------------------------------------------------------------- main
def append_prepojenia(rows):
    new = not os.path.exists(PREP)
    cols = ["zistene", "firma", "typ", "obec", "okres", "objednavatel", "dodavatel", "nazov", "suma", "datum", "url"]
    with open(PREP, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({**r, "zistene": TODAY.isoformat()})


def main():
    seen_list = load(SEEN, [])
    baseline = not seen_list
    seen = set(seen_list)
    out = {"datum": TODAY.isoformat(), "prvy_beh": baseline}
    print("ÚVO…", flush=True);       out["obstaravania"] = uvo(seen)
    print("Josephine…", flush=True); out["obstaravania"] += josephine(seen)
    print("TED…", flush=True);       out["obstaravania"] += ted(seen)
    print("CRZ…", flush=True);       out["zmluvy"], out["prepojenia"] = crz(seen)
    print("Výzvy…", flush=True);     out["vyzvy"] = vyzvy(seen, baseline)
    if baseline:
        # pri prvom behu ukážeme len to, čo je naozaj čerstvé (posledných 7 dní z vyhľadávačov),
        # výzvy sa len zapamätajú
        out["poznamka"] = "Prvý beh: obstarávania a zmluvy za posledné dni, výzvy sa začnú hlásiť od zajtra."
    append_prepojenia(out["prepojenia"])
    save(SEEN, sorted(seen))
    save(os.path.join(DATA, "zdroje", f"{TODAY.isoformat()}.json"), out)
    save(os.path.join(DATA, "zdroje_latest.json"), out)
    print({k: len(v) for k, v in out.items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
