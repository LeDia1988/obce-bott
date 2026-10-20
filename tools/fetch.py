"""Stiahne stránku, nájde PDF odkazy s kľúčovými slovami a uloží ich text (jednorazová pomôcka)."""
import sys, os, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import get, soup_of, links_of, norm
out = "fetch_out"; os.makedirs(out, exist_ok=True)
pages = sys.argv[1].split(",")
pat = re.compile(sys.argv[2]) if len(sys.argv) > 2 else re.compile(".")
n = 0
for p in pages:
    try:
        r = get(p)
    except Exception as e:
        open(f"{out}/_err.txt", "a").write(f"{p} {e}\n"); continue
    s = soup_of(r)
    open(f"{out}/page_{n}.txt", "w").write(p + "\n\n" + s.get_text("\n", strip=True))
    for l in links_of(s, r.url):
        if pat.search(norm(l["text"] + " " + l["url"])):
            n += 1
            try:
                d = get(l["url"]).content
                fn = f"{out}/doc_{n}.pdf"; open(fn, "wb").write(d)
                t = subprocess.run(["pdftotext", "-layout", fn, "-"], capture_output=True).stdout.decode("utf-8", "ignore")
                open(f"{out}/doc_{n}.txt", "w").write(l["text"] + "\n" + l["url"] + "\n\n" + t)
            except Exception as e:
                open(f"{out}/_err.txt", "a").write(f"{l['url']} {e}\n")
    n += 1
