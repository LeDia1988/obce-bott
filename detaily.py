#!/usr/bin/env python3
"""
Detaily: pre dnešné nálezy (weby obcí, CUET, obstarávania, zmluvy) stiahne zdrojovú stránku
a súvisiace dokumenty (PDF/DOC) a uloží ich text do data/detaily/<dátum>/.
Ranná úloha v Claude potom overuje nálezy z týchto textov – nemusí nič otvárať na webe.

Výstup:
  data/detaily/<YYYY-MM-DD>/<id>.txt   – text stránky + príloh (hlavička: URL, obec, názov)
  data/detaily_latest.json             – index: id, zdroj, obec, názov, url, súbory, chyby, kľúčové údaje

Spustenie:  python detaily.py            (po bot.py, zdroje.py, cuet.py)
            python detaily.py --max 150
"""
import hashlib, json, os, re, shutil, sys, time, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import bot

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUTDIR = os.path.join(DATA, "detaily")
INDEX = os.path.join(DATA, "detaily_latest.json")
KEEP_DAYS = 14
MAX_ITEMS = 120
MAX_LINKED = 3
MAX_CHARS = 90000
WORKERS = 8

# odkazy na stránke, ktoré stojí za to otvoriť (normalizovaný text odkazu/URL)
LINK_RX = re.compile(r"vyzv|vyzva|zakazk|obstarav|prieskum|zapisnic|uznesen|pozvank|program|rozpoc|"
                     r"ihrisk|sportov|workout|oploten|mobiliar|lavic|zastavk|revitaliz|park|oddych|"
                     r"stavebn\w* zamer|zacat\w* konani|oznamen|studi|projekt|dotaci|zmluv|sutazn|podklad|vykaz|"
                     r"opis predmetu|technick\w* specifik|priloh")
# kľúčové údaje, ktoré vytiahneme do indexu (aby ich Claude videl hneď)
KEY_RX = [
    ("lehota", re.compile(r"(lehot\w* (na )?(predkladan|predlozen)\w* ponuk\w*|termin (na )?predlozen\w* ponuk\w*|ponuky (je potrebne )?(doruc|predloz)\w*)[^\n]{0,140}", re.I)),
    ("hodnota", re.compile(r"(predpokladan\w* hodnot\w*|phz)[^\n]{0,120}", re.I)),
    ("kontakt", re.compile(r"(kontaktn\w* osob\w*|e-?mail|tel\.?(efon)?)\s*:?[^\n]{0,100}", re.I)),
    ("financovanie", re.compile(r"(financovan\w*|nenavratn\w* financn\w* prispev\w*|dotaci\w*)[^\n]{0,140}", re.I)),
    ("stavebny_zamer", re.compile(r"(stavebn\w* zamer\w*|zacat\w* konani\w*)[^\n]{0,160}", re.I)),
    ("dodavatel", re.compile(r"(zhotovitel\w*|dodavatel\w*|uspesn\w* uchadzac\w*)\s*:?[^\n]{0,120}", re.I)),
]


def uid(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def load(name):
    p = os.path.join(DATA, name)
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def candidates():
    """Zoznam položiek na stiahnutie, zoradený podľa dôležitosti."""
    items = []
    z = load("zdroje_latest.json")
    for o in z.get("obstaravania", []):
        items.append((0, {"zdroj": "obstarávanie " + o.get("zdroj", ""), "obec": o.get("obec") or o.get("obstaravatel", ""),
                          "okres": o.get("okres", ""), "title": o.get("nazov", ""), "url": o.get("url", ""), "ukazky": []}))
    for k in ("zmluvy", "prepojenia"):
        for o in z.get(k, []):
            items.append((1, {"zdroj": "CRZ " + k, "obec": o.get("obec") or o.get("objednavatel", ""), "okres": o.get("okres", ""),
                              "title": f'{o.get("nazov", "")} – {o.get("dodavatel", "")}', "url": o.get("url", ""), "ukazky": []}))
    important = {"Verejné obstarávanie", "Pozvánka na zastupiteľstvo", "Rozpočet / zmena rozpočtu", "Uznesenie / zápisnica"}
    core = {"Detské ihrisko", "Inkluzívne / bezbariérové", "Športovisko", "Workout / fitness", "Oplotenie",
            "Mobiliár", "Zastávka", "Turistická infraštruktúra", "Edukačné tabule"}
    for src, data in (("CUET", load("cuet_latest.json")), ("web obce", load("latest.json"))):
        for n in data.get("nalezy", []):
            temy, typ = set(n.get("temy", [])), set(n.get("typ", []))
            score = 2
            if "Verejné obstarávanie" in typ and temy & core:
                score = 0
            elif typ & important and temy & core:
                score = 1
            elif not temy & core:
                score = 4
            items.append((score, {"zdroj": src, "obec": n.get("obec", ""), "okres": n.get("okres", ""), "title": n.get("title", ""),
                                  "url": n.get("url", ""), "ukazky": n.get("ukazky", []), "prilohy": n.get("prilohy", [])}))
    seen, out = set(), []
    for _, it in sorted(items, key=lambda x: x[0]):
        if it["url"] and it["url"] not in seen:
            seen.add(it["url"])
            out.append(it)
    return out


def overlap(a, b):
    wa = set(re.findall(r"[a-z0-9]{4,}", bot.norm(a)))
    wb = set(re.findall(r"[a-z0-9]{4,}", bot.norm(b)))
    return len(wa & wb)


def fetch(it):
    """Stiahne stránku a súvisiace dokumenty -> (text, zoznam súborov, chyba)."""
    url, parts, files = it["url"], [], []
    try:
        r = bot.get(url)
    except Exception as e:
        return "", [], f"{type(e).__name__}"
    ctype = r.headers.get("content-type", "").lower()
    if "html" not in ctype:
        t = bot.doc_text(url)
        return t, [{"url": url, "typ": "dokument", "znakov": len(t)}], "" if t else "dokument bez textu"
    s = bot.soup_of(r)
    links = bot.links_of(s, r.url)
    page = full_text(s)
    parts.append(f"=== STRÁNKA {r.url}\n{page[:30000]}")
    files.append({"url": r.url, "typ": "stránka", "znakov": len(page)})
    # ktoré odkazy otvoriť: prílohy z bota + odkazy, ktorých text sa zhoduje s úryvkom nálezu / témou
    ctx = " ".join([it.get("title", "")] + it.get("ukazky", []))
    scored = []
    for l in links:
        u, low = l["url"], l["url"].lower().split("?")[0]
        if u == url or low.endswith(bot.SKIP_EXT):
            continue
        key = bot.norm(l["text"] + " " + u)
        is_doc = low.endswith(bot.DOC_EXT) or bool(bot.ATTACH_RE.search(u))
        sc = overlap(l["text"], ctx) * 3 + (2 if LINK_RX.search(key) else 0) + (1 if is_doc else 0)
        if not bot.same_site(u, r.url) and "uvo.gov.sk" not in u and "evo" not in u and "josephine" not in u:
            sc -= 3
        if sc >= 3:
            scored.append((sc, u, l["text"]))
    picked = list(dict.fromkeys(it.get("prilohy", [])))
    # ÚVO: karty Dokumenty / Oznámenia / Informácie a detail v IS EVO
    m = re.search(r"uvo\.gov\.sk/vyhladavanie/vyhladavanie-zakaziek/detail/(\d+)", r.url)
    if m:
        for l in links:
            if re.search(r"vyhladavanie-zakaziek/(dokumenty|oznamenia|informacie)/" + m.group(1), l["url"]) or "evo.isepvo.sk" in l["url"]:
                picked.append(l["url"].replace("isepvo.sk//", "isepvo.sk/"))
        picked = list(dict.fromkeys(picked))
    for _, u, _t in sorted(scored, key=lambda x: -x[0]):
        if u not in picked:
            picked.append(u)
    seen_sig = set()
    for u in picked[:MAX_LINKED + (4 if m else 0)]:
        try:
            low = u.lower().split("?")[0]
            if low.endswith(bot.DOC_EXT) or bot.ATTACH_RE.search(u):
                t = bot.doc_text(u)
            else:
                rr = bot.get(u)
                t = full_text(bot.soup_of(rr)) if "html" in rr.headers.get("content-type", "").lower() else bot.doc_text(u)
            sig = hashlib.sha1(t[:5000].encode("utf-8", "ignore")).hexdigest() if t else ""
            if t and sig not in seen_sig and t[:2000] not in page:
                seen_sig.add(sig)
                parts.append(f"=== ODKAZ {u}\n{t[:40000]}")
                files.append({"url": u, "typ": "odkaz", "znakov": len(t)})
        except Exception as e:
            files.append({"url": u, "typ": "odkaz", "chyba": type(e).__name__})
        time.sleep(0.3)
    return "\n\n".join(parts)[:MAX_CHARS], files, ""


def full_text(s):
    """Celý text stránky bez skriptov, menu a pätičky (krátke riadky ponechané – v tabuľkách bývajú lehoty a sumy)."""
    for t in s(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        t.decompose()
    lines, prev = [], None
    raw = s.get_text("\n", strip=True)
    for mark in ("Názov zákazky:", "Detail zákazky"):   # ÚVO/EVO – preskočiť dlhé menu
        if mark in raw:
            raw = raw[raw.index(mark):]
            break
    for ln in raw.split("\n"):
        ln = " ".join(ln.split())
        if ln and ln != prev:
            lines.append(ln)
        prev = ln
    return "\n".join(lines)


def key_facts(text):
    out = {}
    t = " ".join(text.split())
    nt = bot.norm(t)
    for name, rx in KEY_RX:
        vals = []
        for m in rx.finditer(nt):
            vals.append(t[m.start():m.end()].strip())
            if len(vals) >= 3:
                break
        if vals:
            out[name] = list(dict.fromkeys(vals))
    return out


def main():
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else MAX_ITEMS
    dnes = datetime.date.today().isoformat()
    day = os.path.join(OUTDIR, dnes)
    os.makedirs(day, exist_ok=True)
    # upratanie starých dní
    for d in os.listdir(OUTDIR):
        try:
            if (datetime.date.today() - datetime.date.fromisoformat(d)).days > KEEP_DAYS:
                shutil.rmtree(os.path.join(OUTDIR, d))
        except ValueError:
            pass
    cands = candidates()[:mx]
    index = []
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(fetch, it): it for it in cands}
        for f in as_completed(futs):
            it = futs[f]
            try:
                text, files, err = f.result()
            except Exception as e:
                text, files, err = "", [], type(e).__name__
            i = uid(it["url"])
            rec = {"id": i, "zdroj": it["zdroj"], "obec": it["obec"], "okres": it["okres"], "title": it["title"],
                   "url": it["url"], "subory": files, "chyba": err, "znakov": len(text)}
            if text:
                path = os.path.join(day, i + ".txt")
                open(path, "w", encoding="utf-8").write(
                    f"URL: {it['url']}\nOBEC: {it['obec']} ({it['okres']})\nNÁZOV: {it['title']}\nZDROJ: {it['zdroj']}\n\n{text}")
                rec["subor"] = os.path.relpath(path, ROOT)
                rec["kluc"] = key_facts(text)
            index.append(rec)
    index.sort(key=lambda r: (r["chyba"] != "", r["obec"]))
    out = {"datum": dnes, "vygenerovane": datetime.datetime.now().isoformat(timespec="seconds"),
           "poloziek": len(index), "stiahnutych": sum(1 for r in index if r.get("subor")),
           "chyb": sum(1 for r in index if r["chyba"]), "polozky": index}
    json.dump(out, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Detaily: {out['stiahnutych']}/{out['poloziek']} stiahnutých, chyby {out['chyb']}")


if __name__ == "__main__":
    main()
