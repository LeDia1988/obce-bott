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

## Modul 3 – `cuet.py` (Centrálna úradná elektronická tabuľa)
Denne prejde https://cuet.slovensko.sk (posledné ~3 dni), vyberie dokumenty obcí z `obce.csv`,
otvorí ich prílohy (pozvánky, programy OZ, uznesenia v PDF) a nálezy s našimi témami zapíše
do `data/cuet_latest.json`. Ak sa zoznam nepodarí prečítať, uloží HTML do `data/cuet_debug.html`.
Obce s rovnakým názvom v oboch krajoch majú `nejednoznacny_nazov: true`.

## Modul 4 – `tools/kontakty.py`
Raz mesačne (alebo ručne cez Actions) vytiahne z webov obcí e-mail a telefón úradu do
`data/kontakty.csv` – ranný report z neho dopĺňa kontakty v registri.

## Čítanie príloh (bot.py)
Pri HTML detaile oznamu bot ignoruje menu a pätičku webu a otvorí až 3 prílohy (PDF/DOC),
takže zachytí napr. bod programu OZ „Žiadosť o dotáciu – detské inkluzívne ihrisko“.
Nová téma: „Inkluzívne / bezbariérové“.

## Register zámerov – `data/register.csv`
Trvalý zoznam projektov (ID KE-Z-xxx / PO-Z-xxx, priorita A/B/C, stav, suma, projektant,
míľnik, zdroj, kontakt, krok). Ranný report pridáva nové zámery a aktualizuje existujúce;
hlási len nové záznamy a podstatné zmeny. Stĺpec `stav_obchodu` je pre vlastné poznámky.
