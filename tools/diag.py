"""Diagnostika zdrojov: stiahne vybrané stránky a uloží surové HTML/text do diag_out/ (na ladenie parserov)."""
import os, sys, re, subprocess, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot
out = "diag_out"; os.makedirs(out, exist_ok=True)
urls = [u for u in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if u.strip()]
log = []
for i, u in enumerate(urls):
    u = u.strip()
    try:
        r = bot.session.get(u, timeout=40, allow_redirects=True)
        info = {"i": i, "url": u, "final": r.url, "status": r.status_code, "ctype": r.headers.get("content-type", ""), "len": len(r.content)}
        if r.content[:4] == b"%PDF":
            open(f"{out}/{i}.pdf", "wb").write(r.content)
            t = subprocess.run(["pdftotext", "-layout", f"{out}/{i}.pdf", "-"], capture_output=True).stdout.decode("utf-8", "ignore")
            os.remove(f"{out}/{i}.pdf")
        else:
            open(f"{out}/{i}.html", "w", encoding="utf-8").write(r.text[:400000])
            from bs4 import BeautifulSoup
            s = BeautifulSoup(r.text, "lxml")
            t = s.get_text("\n", strip=True)
            links = [(a.get_text(" ", strip=True)[:120], a["href"]) for a in s.find_all("a", href=True)]
            open(f"{out}/{i}_links.txt", "w", encoding="utf-8").write("\n".join(f"{a} | {b}" for a, b in links))
        open(f"{out}/{i}.txt", "w", encoding="utf-8").write(u + "\n\n" + t[:200000])
    except Exception as e:
        info = {"i": i, "url": u, "error": f"{type(e).__name__}: {e}"}
    log.append(info); print(info, flush=True)
json.dump(log, open(f"{out}/_log.json", "w"), ensure_ascii=False, indent=1)
