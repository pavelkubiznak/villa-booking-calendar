# Villa Rudolf — Booking Calendar

> 🗺️ **Mapa celého systému Villa Rudolf:**
> [`villa-rudolf-site/MAPA-SYSTEMU.md`](https://github.com/pavelkubiznak/villa-rudolf-site/blob/main/MAPA-SYSTEMU.md)
> — kde co běží a které repo je živé. **Přečti ji dřív, než začneš.**
> Tohle repo je v systému **dodavatel dat**: publikuje `data/history.json`, ze kterého
> čte admin `/sprava/` na villarudolf.com. Změna formátu těch dat ovlivní i jeho.

**Architekturu, datové schéma a bezpečnostní model najdeš v [`docs/CLAUDE-HANDOFF.md`](docs/CLAUDE-HANDOFF.md).**
Tenhle soubor drží jen aktuální stav práce a provozní pravidla.

## Rychlý přehled

| | |
|---|---|
| Živě | https://pavelkubiznak.github.io/villa-booking-calendar/ (úklid) · `owner.html` (majitel, token-gate) |
| Stack | statické HTML/JS, bez backendu, GitHub Pages z `main` |
| Data | `data/feed.ics` + `data/history.json`, aktualizuje Action každé 3 h |
| Jazyk UI | čeština |

## Zobrazování překryvů rezervací (hotovo a NASAZENO 2026-08-04)

Dřív `getDayHalves()` držel pro každý půlden jen jednu rezervaci (`amB`/`pmB`/`midB`) —
při překryvu pozdější tu první přepsal a dvojitá rezervace vypadala jako běžný pobyt.
Teď každá polovina dne drží **pole** (`amAll` / `pmAll`) a překryv se kreslí:

- **Buňka** — šikmé šrafování barvami kolidujících platforem oddělené tmavě červenou.
  Oddělovač tam musí zůstat: bez něj překryv dvou pobytů ze STEJNÉ platformy splyne
  v plnou barvu (3 z 5 živých případů). Tooltip vypíše všechny dotčené pobyty.
- **Banner** nad kalendářem — souhrn s odkazem, který skočí na dotčený měsíc.
- **Dvě úrovně.** Oba pobyty živé ve `feed.ics` = červeně „dvojitá rezervace".
  Aspoň jedna strana jen v archivu (`stale`) = oranžově „❓ překryv se starým záznamem" —
  typicky propadlá předrezervace. Mazat se nesmí: hub odmítá import přes existující
  překryv, takže i platná rezervace může z feedu zmizet.

`getDayHalves()` / `halfStyle()` / `findOverlaps()` / `renderConflictBanner()` jsou
v `index.html` i `owner.html` **duplicitně a musí zůstat identické** — obě stránky
jsou samostatné, sdílený JS soubor tu není.

Stav k 2026-08-04: **ověřeno živě na Pages** — v datech 5 překryvů, všech 5 „se starým
záznamem" (21 šrafovaných buněk), žádný červený. Vizuálně potvrzeno na červnu 2027
(24.–27.) i červenci 2027 (3.–10.). Červená větev je ověřená jen syntetickými daty — první ostrý případ
si zaslouží pohledem zkontrolovat. Obsazenost v owner KPI překryvy řešila už dřív
(sjednocení dní, clamp 100 %), procenta se neměnila.

## ⏭️ DALŠÍ KROK (odsouhlaseno): číst čtyři feedy místo jednoho hubu

Dnes se čte **jen** e-chalupy feed (`ICAL_URL` v `update_history.py`). E-chalupy fungují jako
hub — mají cross-iCal na Airbnb, Booking i FeWo — a svůj souhrn posílají dál. Tím vznikají
oba problémy najednou:

- **duplicity** — jeden pobyt se vrací zpátky jako blok z cizí platformy;
- **ztráty** — e-chalupy odmítají uložit rezervaci překrývající existující, takže platná
  rezervace z druhého kanálu se do feedu vůbec nedostane (3.–10. 7. 2027, Booking.com).

Směr: číst Airbnb / Booking / FeWo / e-chalupy **každý zvlášť** a filtrovat na vlastní
rezervace kanálu (Airbnb značí cizí bloky `Airbnb (Not available)` — filtr už v parseru je;
FeWo `Reserved - <jméno>` vs. importované). Pak platí bez heuristik: překryv dvou různých
feedů = skutečná dvojitá rezervace. Cross-iCal mezi platformami zůstává, blokuje dostupnost.

Cíl dál: vlastní feed publikovat **ven** a nechat platformy odebírat jeho, ne e-chalupy.

**Jména hostů z feedů nejdou** (ověřeno 2026-08-04 na živém feedu, 34 událostí):
Booking posílá `SUMMARY: CLOSED - Not available`, Airbnb `Reserved` — bez jména.
Jméno dává jen FeWo (křestní) a e-chalupy (volný text majitele). Slučovat podle jmen tedy
nelze a veřejná data zůstávají anonymizovaná.

Channel manager (Lodgify ap.) je **zamítnutý**: vyžaduje jednotnou měnu napříč kanály,
CZK nepodporuje → Booking by musel prodávat v EUR, výplata by přišla v CZK a majitel by
platil dvojí konverzi.

## Provozní pravidla (DŮLEŽITÉ)

1. **Nikdy needitovat HTML přes GitHub web editor** — CM6 korumpuje backticky (`` ` `` → `f`).
   Nasazuj `git push` z tohoto klonu, nebo `gh api --method PUT .../contents/<path>` s base64.
2. `data/*` píše GitHub Action — ruční změny `history.json` / `feed.ics` příští běh přepíše.
3. Repo je **veřejné**. Do klientských HTML nikdy: e-chalupy feed URL/klíč, owner token, ceny v plaintextu.
4. Veřejná data jsou **anonymizovaná** (od 2026-07): `history.json` =
   `{uidh,start,end,platform,firstSeen,lastSeen,stale}`, žádná jména hostů.
   Sanitizace u zdroje v `.github/scripts/update_history.py`.
   `stale:true` = záznam už není v aktuálním `feed.ics` (v archivu zůstává schválně).
5. `gh` token zatím **nemá `workflow` scope** — úpravy `.github/workflows/*` selžou, dokud
   Pavel nespustí `gh auth refresh -h github.com -s workflow`. Ostatní commity fungují.
6. Po nasazení ověřuj přes `gh api .../contents/<file>` (raw.githubusercontent má ~5 min cache;
   Pages ~10 min).

## Nedávné změny

- 2026-07: anonymizace veřejných dat (jména pryč, UID → hash).
- 2026-07: okno kalendáře = aktuální měsíc **+24 měsíců** (vždy ≥2 roky dopředu).
- 2026-08: v záhlaví měsíce chip **obsazené noci / dny · %** (počítáno po nocích).
- 2026-08: **překryvy rezervací se zobrazují** (šrafování + banner) místo tichého přepsání;
  `history.json` dostal `firstSeen` / `lastSeen` / `stale`.

## Kontext

Majitel Pavel Kubizňák. Úklid se řídí `index.html` (den odjezdu = den úklidu, mezi 10:00 a 15:00).
Ceny nejsou v iCal — majitel je zadává ručně v `owner.html`, ukládají se šifrovaně.
