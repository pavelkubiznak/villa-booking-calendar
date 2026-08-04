# Villa Rudolf — Booking Calendar

**Architekturu, datové schéma a bezpečnostní model najdeš v [`docs/CLAUDE-HANDOFF.md`](docs/CLAUDE-HANDOFF.md).**
Tenhle soubor drží jen aktuální stav práce a provozní pravidla.

## Rychlý přehled

| | |
|---|---|
| Živě | https://pavelkubiznak.github.io/villa-booking-calendar/ (úklid) · `owner.html` (majitel, token-gate) |
| Stack | statické HTML/JS, bez backendu, GitHub Pages z `main` |
| Data | `data/feed.ics` + `data/history.json`, aktualizuje Action každé 3 h |
| Jazyk UI | čeština |

## ⚠️ AKTUÁLNÍ ÚKOL: kalendář tiše skrývá překryvy rezervací

**Problém.** `getDayHalves()` (v `index.html` i `owner.html`) drží pro každý půlden jen jednu
rezervaci (`amB` / `pmB` / `midB`). Když se dvě rezervace překrývají, pozdější v pořadí ta první
**přepíše** a v UI po ní nezůstane žádná stopa — dvojitá rezervace vypadá jako normální pobyt.

**V živých datech je k 2026-08-04 pět překryvů** (ověřeno nad `data/history.json`):

| Termín kolize | Rezervace |
|---|---|
| 2027-05-23 → 05-27 | Booking 05-22→05-29 × Booking 05-23→05-27 |
| 2027-05-27 → 05-29 | Booking 05-22→05-29 × Booking 05-27→05-29 |
| 2027-06-24 → 06-27 | Airbnb 06-23→06-27 × Fewo-direkt 06-24→06-27 |
| 2027-07-03 → 07-10 | Airbnb × Booking.com, **identické datum** |
| 2028-01-12 → 01-13 | Booking 01-02→01-16 × Booking 01-12→01-13 |

**Co je potřeba.** Překryv zviditelnit, ne skrýt. Návrh směru (k rozmyšlení, ne dogma):
1. `getDayHalves()` vrací **pole** rezervací na půlden místo jedné.
2. Kolizní buňka dostane vizuální varování (šrafování / červený rámeček) + tooltip vypíše všechny.
3. Nahoře souhrnný banner „⚠️ N překryvů" s odkazy na dotčené měsíce.
4. Stejná logika do obou stránek (sdílejí render kód — držet synchronně).

Pozn.: obsazenost v owner KPI už překryvy řeší (počítá sjednocení dní, clamp 100 %), takže
procenta jsou v pořádku; problém je čistě ve vykreslení a v absenci upozornění.

## Provozní pravidla (DŮLEŽITÉ)

1. **Nikdy needitovat HTML přes GitHub web editor** — CM6 korumpuje backticky (`` ` `` → `f`).
   Nasazuj `git push` z tohoto klonu, nebo `gh api --method PUT .../contents/<path>` s base64.
2. `data/*` píše GitHub Action — ruční změny `history.json` / `feed.ics` příští běh přepíše.
3. Repo je **veřejné**. Do klientských HTML nikdy: e-chalupy feed URL/klíč, owner token, ceny v plaintextu.
4. Veřejná data jsou **anonymizovaná** (od 2026-07): `history.json` = `{uidh,start,end,platform}`,
   žádná jména hostů. Sanitizace u zdroje v `.github/scripts/update_history.py`.
5. `gh` token zatím **nemá `workflow` scope** — úpravy `.github/workflows/*` selžou, dokud
   Pavel nespustí `gh auth refresh -h github.com -s workflow`. Ostatní commity fungují.
6. Po nasazení ověřuj přes `gh api .../contents/<file>` (raw.githubusercontent má ~5 min cache;
   Pages ~10 min).

## Nedávné změny

- 2026-07: anonymizace veřejných dat (jména pryč, UID → hash).
- 2026-07: okno kalendáře = aktuální měsíc **+24 měsíců** (vždy ≥2 roky dopředu).
- 2026-08: v záhlaví měsíce chip **obsazené noci / dny · %** (počítáno po nocích).

## Kontext

Majitel Pavel Kubizňák. Úklid se řídí `index.html` (den odjezdu = den úklidu, mezi 10:00 a 15:00).
Ceny nejsou v iCal — majitel je zadává ručně v `owner.html`, ukládají se šifrovaně.
