#!/usr/bin/env python3
"""
CUET-bot: prejde Centrálnu úradnú elektronickú tabuľu (cuet.slovensko.sk),
vyberie dokumenty obcí a miest z obce.csv (Košický + Prešovský kraj),
otvorí ich prílohy (PDF/DOC) a zapíše tie s našimi témami do data/cuet_latest.json.

Prečo: veľa obcí zverejňuje pozvánky, programy OZ a uznesenia na CUET v jednotnom
tvare – aj tie, ktorých web je nedostupný alebo má program len v PDF prílohe.

Spustenie:  python cuet.py              (bežný denný beh, posledné ~3 dni)
            python cuet.py --dni 7      (dlhšie obdobie)
"""
import csv, json, os, re, sys, time, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import bot  # zdieľané: get, soup_of, doc_text, classify, snippets, money, norm, TOPIC_RE, FIRMY, PROJ_RE

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
BASE = "https://cuet.slovensko.sk"
LIST_URL = BASE + "/en?page={}"   # strana 1 = BASE + "/en" (s ?page=1 vracia chybu)
RSS_URLS = [BASE + "/en/Rss", BASE + "/sk/Rss"]
RSS_DEBUG = os.path.join(DATA, "cuet_rss_debug.xml")
SEEN = os.path.join(DATA, "cuet_seen.json")
OUT = os.path.join(DATA, "cuet_latest.json")
DEBUG = os.path.join(DATA, "cuet_debug.html")
MAX_PAGES = 80
# fulltextové hľadanie v dokumentoch CUET (nájde aj prílohy – rozpočty, zápisnice, výzvy)
FULLTEXT = ["ihrisko", "ihriska", "workout", "multifunkčné", "oplotenie", "mobiliár", "lavičky", "zastávka",
            "revitalizácia", "oddychová zóna", "náučný chodník", "pumptrack", "stavebný zámer", "dopadová plocha"]
MAX_ATTACH = 3
PAUSE = 0.7

# popisky polí v anglickej verzii CUET (poradie podľa stránky)
LABELS = {
    "institucia": r"Published on official board",
    "od": r"Published from",
    "znacka": r"Registry symbol",
    "autor": r"Documents? author",
    "do": r"Published to",
    "spis": r"Registry case",
    "nazov": r"Name of official document",
    "abstrakt": r"Document abstract",
}
LABEL_ANY = "|".join(LABELS.values()) + r"|Display|Zobraziť"


def field(text, key):
    m = re.search(r"(?:%s)\s*:?\s*(.*?)\s*(?=(?:%s)\s*:?|$)" % (LABELS[key], LABEL_ANY), text, re.S | re.I)
    return " ".join(m.group(1).split()) if m else ""


def parse_date(s):
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def inst_key(name):
    """'Obec Nižný Hrušov (OVM)' -> 'nizny hrusov'; 'Mestská časť Košice-Juh' -> 'kosice juh'."""
    n = bot.norm(name)
    n = re.sub(r"\(.*?\)", " ", n)
    # CUET píše aj „Obec X - Zverejňovanie na CUET“ alebo „Zverejňovanie na CUET - obec X“
    n = re.sub(r"zverejnovanie\s+na\s+cuet|uradna\s+tabula|elektronicka\s+uradna\s+tabula", " ", n)
    n = re.sub(r"^[\s\-–,:]+|[\s\-–,:]+$", "", n)
    n = re.sub(r"^\s*(obecny urad|mestsky urad|miestny urad|statutarne mesto|obec|mesto|mestska cast)\s+", "", n)
    n = re.sub(r"[-–,]", " ", n)
    return " ".join(n.split())


def load_obce():
    obce = list(csv.DictReader(open(os.path.join(ROOT, "obce.csv"), encoding="utf-8")))
    idx, dup = {}, {}
    for o in obce:
        k = inst_key(o["nazov"])
        if k in idx:
            dup.setdefault(k, [idx[k]["okres"]]).append(o["okres"])
        else:
            idx[k] = o
    return idx, dup


def list_items(html):
    """Z jednej stránky zoznamu vráti položky {uuid, url, text}."""
    s = BeautifulSoup(html, "lxml")
    items = []
    for a in s.find_all("a", href=True):
        m = re.search(r"/dokument/([0-9a-f-]{36})", a["href"])
        if not m:
            continue
        # najmenší predok, ktorý obsahuje práve tento jeden odkaz na dokument
        box = a
        for p in a.parents:
            if p.name in ("body", "html"):
                break
            if len({x["href"] for x in p.find_all("a", href=re.compile(r"/dokument/"))}) > 1:
                break
            box = p
        text = box.get_text("\n", strip=True)
        items.append({"uuid": m.group(1), "url": urljoin(BASE, a["href"]), "text": text})
    return list({i["uuid"]: i for i in items}.values())


def detail(url):
    """Detail dokumentu -> (text detailu, zoznam príloh na stiahnutie)."""
    r = bot.get(url)
    s = bot.soup_of(r)
    atts = []
    for a in s.find_all("a", href=True):
        if "/priloha/uloz/" in a["href"]:
            u = urljoin(BASE, a["href"])
            if u not in atts:
                atts.append(u)
    for t in s(["script", "style", "nav", "header", "footer", "noscript"]):
        t.decompose()
    return " ".join(s.get_text(" ", strip=True).split())[:20000], atts


def main():
    dni = 3
    if "--dni" in sys.argv:
        dni = int(sys.argv[sys.argv.index("--dni") + 1])
    dnes = datetime.date.today()
    od = dnes - datetime.timedelta(days=dni)
    idx, dup = load_obce()
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    prvy_beh = not seen

    stats = {"strany": 0, "dokumenty": 0, "nasich": 0, "chyby": []}
    unmatched = {}
    nase = []
    for page in range(1, MAX_PAGES + 1):
        try:
            # zoznam s dátumom od (bez neho CUET ráno/cez víkend ukazuje prázdny zoznam)
            r = bot.session.get(BASE + "/en", params={"DocumentPublishedFrom": od.strftime("%d.%m.%Y"), **({"page": page} if page > 1 else {})}, timeout=40)
            if "/chyba" in r.url or "can not be displayed" in r.text:
                stats["chyby"].append(f"strana {page}: CUET vrátil chybovú stránku")
                if page == 1:
                    open(DEBUG, "w", encoding="utf-8").write(r.text)
                break
        except Exception as e:
            stats["chyby"].append(f"strana {page}: {type(e).__name__}")
            break
        items = list_items(r.text)
        stats["strany"] = page
        if not items:
            if page == 1:
                open(DEBUG, "w", encoding="utf-8").write(r.text)   # na úpravu parsera
                stats["chyby"].append("strana 1 bez položiek – HTML uložené do data/cuet_debug.html")
            break
        datumy = []
        for it in items:
            stats["dokumenty"] += 1
            d = parse_date(field(it["text"], "od"))
            if d:
                datumy.append(d)
            if it["uuid"] in seen:
                continue
            inst = field(it["text"], "institucia") or field(it["text"], "autor")
            o = idx.get(inst_key(inst))
            if not o:
                unmatched[inst] = unmatched.get(inst, 0) + 1
                continue
            it.update(obec=o, institucia=inst, datum=d, nazov=field(it["text"], "nazov"),
                      abstrakt=field(it["text"], "abstrakt"), spis=field(it["text"], "spis"))
            nase.append(it)
        if datumy and max(datumy) < od:
            break
        time.sleep(PAUSE)

    # Fulltextové vyhľadávanie v CUET podľa našich tém (celé SR, potom filter na naše obce)
    for q in FULLTEXT:
        for page in range(1, 6):
            params = {"DocumentPublishedFrom": od.strftime("%d.%m.%Y"), "FullText": q}
            if page > 1:
                params["page"] = page
            try:
                r = bot.session.get(BASE + "/en", params=params, timeout=40)
            except Exception as e:
                stats["chyby"].append(f"fulltext {q}: {type(e).__name__}")
                break
            items = list_items(r.text)
            stats["fulltext_" + q] = stats.get("fulltext_" + q, 0) + len(items)
            for it in items:
                if it["uuid"] in seen or any(x["uuid"] == it["uuid"] for x in nase):
                    continue
                inst = field(it["text"], "institucia") or field(it["text"], "autor")
                o = idx.get(inst_key(inst))
                if not o:
                    continue
                it.update(obec=o, institucia=inst, datum=parse_date(field(it["text"], "od")), nazov=field(it["text"], "nazov"),
                          abstrakt=field(it["text"], "abstrakt"), spis=field(it["text"], "spis"), fulltext=q)
                nase.append(it)
            if len(items) < 10:
                break
            time.sleep(PAUSE)

    # diagnostika: najčastejšie inštitúcie, ktoré sa nepodarilo priradiť (na doladenie párovania)
    stats["nezaradene_ukazka"] = sorted(unmatched, key=lambda k: -unmatched[k])[:25]

    # RSS ako doplnkový zdroj (ak stránkovanie nepustí ďalej ako na 1. stranu)
    for ru in RSS_URLS:
        try:
            rr = bot.get(ru)
        except Exception as e:
            stats["chyby"].append(f"RSS {ru}: {type(e).__name__}")
            continue
        if not os.path.exists(RSS_DEBUG):
            open(RSS_DEBUG, "w", encoding="utf-8").write(rr.text[:200000])   # na doladenie parsera
        rs = BeautifulSoup(rr.text, "xml")
        n = 0
        for itm in rs.find_all("item"):
            link = (itm.find("link").get_text(strip=True) if itm.find("link") else "")
            m = re.search(r"/dokument/([0-9a-f-]{36})", link)
            if not m or m.group(1) in seen or any(x["uuid"] == m.group(1) for x in nase):
                continue
            n += 1
            title = itm.find("title").get_text(" ", strip=True) if itm.find("title") else ""
            desc = BeautifulSoup(itm.find("description").get_text(" ", strip=True), "lxml").get_text(" ", strip=True) if itm.find("description") else ""
            text = title + "\n" + desc
            inst = field(text, "institucia") or field(text, "autor")
            o = idx.get(inst_key(inst)) if inst else None
            if not o:   # inštitúcia nie je v popiskoch – hľadaj „Obec/Mesto X“ v texte
                for mm in re.finditer(r"(?:Obec|Mesto|Mestská časť)\s+([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][^,;:()\n]{1,40})", text):
                    for cut in range(len(mm.group(1).split()), 0, -1):
                        cand = " ".join(mm.group(1).split()[:cut])
                        if inst_key(cand) in idx:
                            o, inst = idx[inst_key(cand)], mm.group(0)
                            break
                    if o:
                        break
            if not o:
                continue
            pd = itm.find("pubDate")
            d = parse_date(field(text, "od"))
            if not d and pd:
                try:
                    d = datetime.datetime.strptime(pd.get_text(strip=True)[:16], "%a, %d %b %Y").date()
                except ValueError:
                    d = None
            nase.append({"uuid": m.group(1), "url": link, "text": text, "obec": o, "institucia": inst, "datum": d,
                         "nazov": field(text, "nazov") or title, "abstrakt": field(text, "abstrakt") or desc[:500],
                         "spis": field(text, "spis")})
        stats["rss_" + ru.rsplit("/", 2)[-2]] = n
        break

    stats["nasich"] = len(nase)
    nalezy = []
    for it in nase:
        seen.add(it["uuid"])
        if prvy_beh and it["datum"] and it["datum"] < od:
            continue
        head = f'{it["nazov"]} {it["abstrakt"]}'
        body, atts = "", []
        try:
            body, atts = detail(it["url"])
            for u in atts[:MAX_ATTACH]:
                t = bot.doc_text(u)
                if t:
                    body += " \n [príloha] " + t[:40000]
                time.sleep(PAUSE)
        except Exception as e:
            stats["chyby"].append(f'{it["uuid"]}: {type(e).__name__}')
        topics, types = bot.classify(head + " " + body)
        full = bot.norm(head + " " + body)
        firmy = [f["nazov"] for f in bot.FIRMY if f["_rx"].search(full)]
        if not topics and not firmy:
            continue
        sn = []
        for n, rx in bot.TOPIC_RE:
            if n in topics:
                sn += bot.snippets(head + " " + body, rx, 2)
        o = it["obec"]
        nalezy.append({
            "zdroj": "CUET", "obec": o["nazov"], "statut": o["statut"],
            "okres": o["okres"] if inst_key(o["nazov"]) not in dup else "nejednoznačné: " + " / ".join(dup[inst_key(o["nazov"])]), "kraj": o["kraj"],
            "kod": o["kod"] if inst_key(o["nazov"]) not in dup else "", "institucia_cuet": it["institucia"],
            "nejednoznacny_nazov": inst_key(o["nazov"]) in dup,
            "title": it["nazov"], "url": it["url"], "prilohy": atts[:MAX_ATTACH],
            "zverejnene": it["datum"].isoformat() if it["datum"] else "", "spis": it["spis"],
            "temy": topics, "typ": types, "projekcia": bool(bot.PROJ_RE.search(full)), "firmy": firmy,
            "sumy_eur": bot.money(body), "ukazky": list(dict.fromkeys(sn))[:5],
        })
        time.sleep(PAUSE)

    out = {"datum": dnes.isoformat(), "vygenerovane": datetime.datetime.now().isoformat(timespec="seconds"),
           "obdobie_od": od.isoformat(), "prvy_beh": prvy_beh, **stats, "nalezy": nalezy}
    os.makedirs(DATA, exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sorted(seen)[-50000:], open(SEEN, "w"), ensure_ascii=False)
    print(f"CUET: {stats['strany']} strán, {stats['dokumenty']} dokumentov, {stats['nasich']} z našich obcí, "
          f"{len(nalezy)} nálezov, chyby: {len(stats['chyby'])}")


if __name__ == "__main__":
    main()
