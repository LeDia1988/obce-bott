# Obce-bot

Každé ráno prejde úradné tabule, oznamy, zastupiteľstvo a rozpočty 1 126 obcí a miest
Košického a Prešovského kraja a zapíše nové dokumenty s témami
(ihriská, športoviská, workout, oplotenie, mobiliár, zastávky, dotácie) do `data/latest.json`.
Denný e-mailový sumár z neho robí naplánovaná úloha v Claude.

- `obce.csv` – zoznam obcí (kód, názov, okres, kraj, web)
- `bot.py` – skript; `python bot.py --rediscover` nanovo nájde podstránky
- `data/sources.json` – nájdené podstránky každej obce
- `data/seen.json` – už videné odkazy (porovnanie so včerajškom)
- `data/daily/` – archív denných výsledkov

## Modul 2 – `zdroje.py`
- obstarávania: ÚVO, Josephine, TED (EÚ) – len Košický a Prešovský kraj, len naše témy
- zmluvy: CRZ podľa predmetu zmluvy + všetky zmluvy firiem z `firmy.csv`
- prepojenia: `data/prepojenia.csv` – kto (projektant/konkurencia) robil pre ktorú obec
- výzvy: weby z `vyzvy.csv` (ministerstvá, fondy, kraje, nadácie)

Doplnenie projektanta alebo konkurenta: pridať riadok do `firmy.csv`
(`hladat` = časť názvu, ako je v CRZ).
