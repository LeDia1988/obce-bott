import requests, os, re, json
os.makedirs("probe", exist_ok=True)
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (compatible; obce-bot/1.0)"
G = {
 "crz_predmet": ("https://www.crz.gov.sk/2171273-sk/centralny-register-zmluv/", {"art_predmet": "ihrisk", "art_datum_zverejnene_od": "01.09.2026"}),
 "crz_dodavatel": ("https://www.crz.gov.sk/2171273-sk/centralny-register-zmluv/", {"art_zs2": "Hajník"}),
 "crz_detail": ("https://www.crz.gov.sk/zmluva/12955200/", {}),
 "uvo_search": ("https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek", {"nazovZakazky": "ihrisko"}),
 "uvo_vestnik_det": ("https://www.uvo.gov.sk/vestnik-a-registre/vestnik", {}),
 "eks_list": ("https://eo.eks.sk/Prehlady/ZakazkyVerejnost", {}),
 "jos_list": ("https://josephine.proebiz.com/sk/public-tenders/list", {}),
 "mckvp_zmluvy": ("https://www.mckvp.sk/", {}),
 "grantexpert": ("https://www.grantexpert.sk/granty/", {}),
 "mincrs_dot": ("https://www.mincrs.sk/", {}),
}
res = {}
for k,(u,p) in G.items():
    try:
        r = s.get(u, params=p, timeout=30)
        res[k] = [r.status_code, r.url, len(r.text)]
        open(f"probe/{k}.html", "w", encoding="utf-8").write(r.text[:800000])
    except Exception as e:
        res[k] = ["ERR", str(e)[:200]]
json.dump(res, open("probe/_vysledok.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
