import requests, os, re, json
U = """https://www.uvo.gov.sk/vestnik-a-registre/vestnik
https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek
https://www.eks.sk/
https://josephine.proebiz.com/sk/
https://evo.gov.sk/
https://datahub.ekosystem.slovensko.digital/
https://www.crz.gov.sk/
https://www.crz.gov.sk/export/
https://www.mirri.gov.sk/
https://www.envirofond.sk/
https://www.employment.gov.sk/sk/
https://www.fnps.sk/
https://www.mincrs.sk/
https://www.minedu.sk/
https://www.minv.sk/
https://www.vlada.gov.sk/
https://www.eurofondy.gov.sk/
https://www.apa.sk/
https://www.vucke.sk/
https://web.vucke.sk/
https://www.po-kraj.sk/
https://www.nadaciaspp.sk/
https://www.nadaciapontis.sk/
https://www.ekopolis.sk/
https://www.grantexpert.sk/
https://www.kosice.sk/
https://www.mckvp.sk/
https://www.kosice-dh.sk/""".split()
os.makedirs("probe", exist_ok=True)
res = {}
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (compatible; obce-bot/1.0)"
for u in U:
    try:
        r = s.get(u, timeout=25)
        res[u] = [r.status_code, r.url, len(r.text)]
        fn = re.sub(r"\W+", "_", u)[:80] + ".html"
        open("probe/" + fn, "w", encoding="utf-8").write(r.text[:400000])
    except Exception as e:
        res[u] = ["ERR", type(e).__name__]
try:
    r = s.post("https://api.ted.europa.eu/v3/notices/search", json={"query": "classification-cpv IN (37535200) AND place-of-performance IN (SVK)", "fields": ["notice-title","publication-date","buyer-name"], "limit": 5}, timeout=30)
    res["TED"] = [r.status_code, r.text[:1500]]
except Exception as e:
    res["TED"] = ["ERR", str(e)]
json.dump(res, open("probe/_vysledok.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
