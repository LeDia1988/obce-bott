"""Pre obce so schváleným IPKD 2025/2026: zmluvy v CRZ od 2025 s predmetom ihrisko/hracie prvky → dodávateľ."""
import csv, os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zdroje import crz_rows, norm, DATA
REL = re.compile(r"ihrisk|hraci|herne prvk|inkluz|detsk")
rows = []
for o in csv.DictReader(open(os.path.join(DATA, "ipkd_schvalene.csv"), encoding="utf-8")):
    found = []
    for zs in (f"Obec {o['nazov']}", f"Mesto {o['nazov']}", o["nazov"]):
        got = crz_rows({"art_zs1": zs, "art_datum_zverejnene_od": "01.01.2025"}, pages=5)
        got = [z for z in got if REL.search(norm(z["nazov"])) and norm(o["nazov"]) in norm(z["objednavatel"] + " " + z["dodavatel"])]
        if got:
            found = got
            break
        time.sleep(0.5)
    if not found:
        rows.append({**o, "dodavatel": "", "zmluva": "", "suma_zmluvy": "", "datum": "", "url": ""})
    for z in found:
        rows.append({**o, "dodavatel": z["dodavatel"], "zmluva": z["nazov"], "suma_zmluvy": z["suma"], "datum": z["datum"], "url": z["url"]})
    print(o["nazov"], len(found), flush=True)
cols = list(rows[0].keys())
with open(os.path.join(DATA, "ipkd_crz.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
