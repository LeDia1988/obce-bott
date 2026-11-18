#!/usr/bin/env python3
"""
Kontakty obcí: z webu každej obce (titulka + stránka „Kontakt“) vytiahne e-mail
a telefón obecného/mestského úradu a zapíše ich do data/kontakty.csv.
Ranný report z nich dopĺňa stĺpec „kontakt“ v registri zámerov.

Spustenie:  python tools/kontakty.py
"""
import csv, os, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot  # get, soup_of, links_of, same_site, norm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "kontakty.csv")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(?:sk|com|eu|cz|net|org)\b")
PHONE_RE = re.compile(r"(?:\+421|00421|\b0)\s?\(?\d{1,3}\)?(?:[\s/.-]{0,2}\d{2,3}){2,4}\b")
JUNK_MAIL = re.compile(r"example|domena|wix|sentry|webmaster@|noreply|no-reply|@(?:e-obce|webex|dobraobec|mojaobec|antik|tvorba|obce\.info)", re.I)
PREFER_MAIL = re.compile(r"^(?:obec|mesto|ocu|obecnyurad|urad|podatelna|info|sekretariat|starost|primator|msu|mu)", re.I)


def kontakt_page(s, base):
    for l in bot.links_of(s, base):
        key = bot.norm(l["text"] + " " + l["url"])
        if bot.same_site(l["url"], base) and re.search(r"kontakt|obecny urad|mestsky urad|\burad\b", key):
            return l["url"]
    return None


def mailto(s):
    out = []
    for a in s.find_all("a", href=True):
        h = a["href"]
        if h.lower().startswith("mailto:"):
            out.append(h[7:].split("?")[0].strip())
    return out


def phones(text):
    out = []
    for m in PHONE_RE.finditer(text):
        p = re.sub(r"[^\d+]", "", m.group(0))
        if p.startswith("00421"):
            p = "+" + p[2:]
        elif p.startswith("0"):
            p = "+421" + p[1:]
        if 12 <= len(p) <= 13 and p not in out:
            out.append(p)
    return out


def one(o):
    row = {"kod": o["kod"], "nazov": o["nazov"], "okres": o["okres"], "kraj": o["kraj"],
           "email": "", "telefon": "", "zdroj": "", "stav": ""}
    if not o.get("web"):
        row["stav"] = "bez webu"
        return row
    mails, tels, zdroj = [], [], []
    try:
        r = bot.get(o["web"])
        s = bot.soup_of(r)
        pages = [(r.url, s)]
        k = kontakt_page(s, r.url)
        if k and k != r.url:
            try:
                rk = bot.get(k)
                pages.insert(0, (rk.url, bot.soup_of(rk)))
            except Exception:
                pass
        for url, sp in pages:
            text = sp.get_text(" ", strip=True)
            m = [x for x in mailto(sp) + EMAIL_RE.findall(text) if not JUNK_MAIL.search(x)]
            t = phones(text)
            if m or t:
                zdroj.append(url)
            mails += [x.lower() for x in m if x.lower() not in mails]
            tels += [x for x in t if x not in tels]
        mails.sort(key=lambda x: (not PREFER_MAIL.search(x), len(x)))
        row.update(email=", ".join(dict.fromkeys(mails[:3])), telefon=", ".join(tels[:3]),
                   zdroj=zdroj[0] if zdroj else r.url, stav="ok" if (mails or tels) else "nenájdené")
    except Exception as e:
        row["stav"] = f"web nedostupný: {type(e).__name__}"
    return row


def main():
    obce = list(csv.DictReader(open(os.path.join(ROOT, "obce.csv"), encoding="utf-8")))
    rows = []
    with ThreadPoolExecutor(16) as ex:
        for f in as_completed([ex.submit(one, o) for o in obce]):
            rows.append(f.result())
    rows.sort(key=lambda r: (r["kraj"], r["okres"], r["nazov"]))
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    ok = sum(1 for r in rows if r["stav"] == "ok")
    print(f"Kontakty: {ok}/{len(rows)} obcí s e-mailom alebo telefónom")


if __name__ == "__main__":
    main()
