"""Jednorazovo: všetky zmluvy sledovaných firiem (firmy.csv) v CRZ od 2021."""
import csv, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zdroje import crz_rows, match_obec, firmy, DATA
rows = []
for f in firmy():
    got = crz_rows({"art_zs2": f["hladat"], "art_datum_zverejnene_od": "01.01.2021"}, pages=40)
    print(f["nazov"], len(got), flush=True)
    for z in got:
        o = match_obec(z["objednavatel"])
        rows.append({"firma": f["nazov"], "typ": f["typ"], "dodavatel_v_crz": z["dodavatel"], "obec": o["nazov"] if o else "",
                     "okres": o["okres"] if o else "", "kraj": o["kraj"] if o else "mimo KE/PO alebo neobec",
                     "objednavatel": z["objednavatel"], "nazov": z["nazov"], "suma": z["suma"], "datum": z["datum"], "url": z["url"]})
    time.sleep(1)
cols = list(rows[0].keys()) if rows else ["firma"]
with open(os.path.join(DATA, "historia_firmy.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
print("spolu", len(rows))
