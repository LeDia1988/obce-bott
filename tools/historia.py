"""Jednorazovo: CRZ od 2022 – kto (projektant / dodávateľ) robil ihriská a športoviská pre obce KE+PO."""
import csv, os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zdroje import crz_rows, match_obec, REL, NEG, PROJECT, PROJ_FIRM, norm, DATA

Q = ["ihrisk", "športovisk", "workout", "multifunkčn", "hracie prvky", "hracích prvkov", "fitnes", "pumptrack",
     "skatepark", "oddychov", "náučn", "mobiliár", "dopadov"]
rows, seen = [], set()
for q in Q:
    for year in range(2022, 2027):
        got = crz_rows({"art_predmet": q, "art_datum_zverejnene_od": f"01.01.{year}",
                        "art_datum_zverejnene_do": f"31.12.{year}"}, pages=60)
        print(q, year, len(got), flush=True)
        for z in got:
            if z["url"] in seen:
                continue
            seen.add(z["url"])
            o = match_obec(z["objednavatel"])
            n = norm(z["nazov"])
            if not o or not REL.search(n) or NEG.search(n):
                continue
            proj = bool(PROJECT.search(n) or PROJ_FIRM.search(norm(z["dodavatel"])))
            rows.append({"typ": "projektant" if proj else "dodávateľ / iné", "firma": z["dodavatel"], "obec": o["nazov"],
                         "okres": o["okres"], "kraj": o["kraj"], "objednavatel": z["objednavatel"], "nazov": z["nazov"],
                         "suma": z["suma"], "datum": z["datum"], "url": z["url"]})
        time.sleep(0.5)
cols = ["typ", "firma", "obec", "okres", "kraj", "objednavatel", "nazov", "suma", "datum", "url"]
with open(os.path.join(DATA, "historia_crz.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print("spolu", len(rows))
