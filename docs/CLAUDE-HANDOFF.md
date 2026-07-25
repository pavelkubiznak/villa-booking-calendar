# Villa Rudolf — Booking Calendar: technický handoff pro AI agenty

> Tento dokument je určen pro Claude Code (nebo jiného agenta), který pracuje na stránkách
> čerpajících data z tohoto kalendáře. Obsahuje vše podstatné o architektuře, datech a pravidlech.
> Udržuje ho session „villa-booking-calendar"; při změně architektury aktualizovat i tento soubor.

## Co to je

Statický HTML/JS kalendář rezervací vily Rudolf (bez backendu), repo
**`pavelkubiznak/villa-booking-calendar`** (public), hostováno na GitHub Pages z větve `main`.
UI česky. Dvě stránky nad společnými daty:

| Stránka | URL | Účel |
|---|---|---|
| Úklidový kalendář | `https://pavelkubiznak.github.io/villa-booking-calendar/` | pro úklidový personál — pohled od aktuálního měsíce do +24 měsíců (vždy ≥2 roky dopředu), půldenní buňky, BEZ cen |
| Majitelský dashboard | `.../owner.html` | tržby/obsazenost/KPI — **chráněno tokenem** (token má jen Pavel, není nikde v repu) |

## Datové endpointy (veřejné, použitelné z jakékoli stránky)

GitHub Pages posílá `Access-Control-Allow-Origin: *` — endpointy lze fetchovat **cross-origin z libovolného webu**.

| Endpoint | Formát | Obsah | Čerstvost |
|---|---|---|---|
| `https://pavelkubiznak.github.io/villa-booking-calendar/data/feed.ics` | iCal | **anonymizovaný** snapshot rezervací (`SUMMARY`=platforma, `UID`=uidh; bez Description/jmen/kontaktů) | snapshot každé ~3 h |
| `https://pavelkubiznak.github.io/villa-booking-calendar/data/history.json` | JSON | **anonymizovaný** archiv `{uidh,start,end,platform}` (i rezervace, co vypadly z feedu) | každé ~3 h při změně |
| `.../data/prices.json` | JSON (AES-GCM šifrovaný) | ceny pobytů — **může neexistovat (404)**; bez tokenu nečitelné | při exportu majitelem |

**Pro nové stránky používej tyto same-origin/Pages URL, NIKDY přímý e-chalupy feed** — jeho URL
obsahuje privátní klíč a záměrně bylo odstraněno ze všech klientských HTML (žije jen
v `.github/scripts/update_history.py`).

## Schéma history.json  ⚠️ ANONYMIZOVÁNO (od 2026-07)

Pole objektů, řazeno dle `start`. **Žádná jména hostů, žádné kontakty.**

```json
{ "uidh": "4b10223bc51a8e91", "start": "2026-04-25", "end": "2026-05-02",
  "platform": "E-chalupy" }
```

Sémantika:
- `start` = check-in (příjezd ~15:00), `end` = check-out (odjezd ~10:00) — **`end` je den odjezdu,
  noc z `end-1` na `end` je poslední obsazená**; počet nocí = `end − start` ve dnech.
- `uidh` = **prvních 16 hex znaků z sha256(uid)** (viz „Hashing" níže). Deterministický klíč
  pro merge napříč feed.ics / history.json / localStorage; **nelze zpětně dohledat** číslo
  rezervace platformy. Je to jediný unikátní klíč (merge = last-write-wins).
- `platform` ∈ `Airbnb | Booking.com | E-chalupy | Fewo-direkt` — je to **explicitní pole**
  (dřív se odvozovalo z UID; po hashování už UID platformu neprozradí, proto se posílá zvlášť
  a ve feed.ics je nese `SUMMARY`).
- **Žádné `guest` ani `uid` pole už neexistuje.** Šum `Airbnb (Not available)` je odfiltrovaný
  už ve zdroji (nikdy se nezapíše).
- Archiv se prořezává na **18 měsíců** zpět (dle `end`).
- Jméno hosta si majitel dohledá v extranetu platformy podle data + platformy.

### Hashing (MUSÍ být identický v Pythonu i JS)

```
uidh = sha256(uid_bytes_utf8).hexdigest()[:16]      # lowercase hex, prvních 16 znaků
```

- Python: `.github/scripts/update_history.py` → `uid_hash()`.
- JS: `index.html` a `owner.html` → `uidHash()` (čistá synchronní implementace `sha256hexSync`).
- Ověřeno vektory: `sha256("abc")[:16] = ba7816bf8f01cfea`;
  `sha256("18852-11157098@e-chalupy.cz")[:16] = 4223dbb99ead635a`. Python i JS dávají shodu.
- **Při jakékoli změně hashovací normalizace se rozbije merge i mapování cen** — měnit jen
  synchronně na všech třech místech.

## Aktualizační pipeline

- GitHub Action `.github/workflows/update-history.yml`: cron `17 */3 * * *` + `workflow_dispatch`.
- Spouští `.github/scripts/update_history.py` (čistý stdlib Python, bez secrets — GITHUB_TOKEN stačí):
  stáhne e-chalupy iCal → **sanitizuje** → zapíše `data/feed.ics` (anonymizovaný snapshot:
  `SUMMARY`=platforma, `UID`=uidh, bez Description/Attendee/Organizer) → merge do `data/history.json`
  jako `{uidh,start,end,platform}` (filtr šumu, prořez 18 m) → commit `[skip ci]` jen při změně.
- `load_history()` čte **oba formáty** existující history.json: nový `{uidh,…}` i starý
  `{uid,guest,…}` (starý zmigruje = uid zahashuje, guest zahodí). Migrace proběhne sama při
  prvním běhu.
- Skript **nikdy netiskne `ICAL_URL`** do logu (obsahuje privátní klíč feedu; logy public repa
  jsou veřejné). Původní `print(f'Fetching {ICAL_URL}')` byl odstraněn.
- Klientské stránky se za běhu NEspoléhají na žádnou třetí stranu (CORS proxy byly odstraněny).

## Klientská architektura (obě stránky)

- `localStorage` klíče (sdílené oběma stránkami na stejném originu — záměrně):
  `villa_cal_v3` (krátkodobá cache feedu), `villa_cal_history_v2` (persistentní archiv, merge dle `uidh`),
  `villa_cal_prices_v2` (jen owner: ceny `{uidh: {amount, currency, mtime}}`),
  `villa_cal_owner_settings_v1` (kurz EUR).
  - ⚠️ **Verze klíčů byly zvednuty** (`v2→v3`, `history v1→v2`, `prices v1→v2`) kvůli anonymizaci:
    obě stránky při startu **mažou staré klíče** `villa_cal_v2` a `villa_cal_history_v1`
    (mohly obsahovat jména z cache). Ceny se migrují (viz owner níže), starý `villa_cal_prices_v1`
    zůstává jako záloha (ceny jména neobsahují).
- Parser: 13měsíční cutoff pro čtení feedu, 18měsíční prořez historie — **stejné hodnoty v obou
  souborech**, při změně měnit synchronně.
- Render: půldenní buňky — horní půlka = dopoledne (odjezd ↑10:00 = úklid), dolní = odpoledne
  (příjezd ↓15:00); barvy platforem `#E74C3C / #2980B9 / #27AE60 / #F39C12`.

## Owner dashboard (owner.html) — bezpečnostní model

- Brána: `?key=TOKEN` nebo formulář; v souboru je jen `TOKEN_HASH` = sha256(token). Token se po
  odemčení maže z URL (`history.replaceState`). **Token nikdy nikam nezapisovat** — je zároveň
  šifrovacím klíčem; má ho jen Pavel.
- `prices.json`: AES-GCM, klíč z PBKDF2 (310 000 iterací, salt `villa-rudolf-owner-v1`),
  payload `{__enc__:1, v:1, iv:<b64>, ct:<b64>}`. Čtecí cesta **odmítá nešifrovaný obsah**
  (ochrana proti podvržení ve veřejném repu) a merguje dle `mtime` (novější vyhrává).
- **Ceny jsou nově klíčované `uidh`, ne surovým UID.** Při načtení owner.html:
  - `migratePricesOnce()` přerazí lokální ceny `villa_cal_prices_v1` → `v2` (klíče, které nejsou
    16-hex, se přehashují `uidHash()`; 16-hex se nechají). Idempotentní.
  - `fetchAndMergeRemotePrices()` po dešifrování přerazí i klíče z prices.json stejným algoritmem,
    pak merguje dle `mtime`. Při dalším exportu se `prices.json` zapíše už s `uidh` klíči.
  - Jména hostů z dashboardu zmizela (záměr) — sloupec „Host" ukazuje `Rezervace`.
- KPI sémantika: tržby a obsazenost = noci uvnitř období (night-distribution; obsazenost = sjednocení
  dní, ≤100 %); počet pobytů a průměrná délka = podle příjezdu; platformní breakdown je
  night-distributed, takže vždy souhlasí s hlavní kartou tržeb.

## Pravidla pro úpravy repa (DŮLEŽITÉ)

1. **NIKDY nepoužívat GitHub web editor** na HTML soubory — CM6 editor korumpuje backticky
   (mění `` ` `` na `f`). Nasazovat přes `gh api --method PUT /repos/.../contents/<path>`
   s base64 obsahem, nebo `git push`.
2. Do klientských HTML nikdy nevkládat: e-chalupy feed URL/klíč, owner token, plaintext ceny.
3. `data/*` commituje Action — ruční zásahy do `history.json` přepíše další běh.
4. Repo je veřejné: každý commit je vidět, žádná tajemství ani v commit messages.
5. **Veřejná data jsou anonymizovaná (od 2026-07).** Žádné jméno hosta ani kontakt se nesmí
   dostat do `data/history.json`, `data/feed.ics` ani do klientských HTML. Sanitizace se dělá
   **u zdroje** v `update_history.py` (guest se zahodí, UID → uidh). Nová stránka nad těmito daty
   nemá žádná jména k dispozici — a nemá je zobrazovat.
6. ⚠️ **Git historie stále obsahuje stará jména.** Anonymizace platí od HEAD dál; předchozí commity
   `data/history.json` a `data/feed.ics` nesou reálná jména, e-maily i telefony. **Historie NEBYLA
   přepsána** (bezpečnost > úklid). Kdo chce jména odstranit i z historie: `git filter-repo`
   (nebo smazat + znovu založit repo) — vždy **s vědomím majitele**, protože to přepíše všechny
   SHA a rozbije klony. Teď to úmyslně řešeno nebylo.

## Kontext provozu

- Ceny pobytů NEJSOU v iCal (platformy je nedávají) — majitel je zadává ručně v owner.html.
- Vlastník: Pavel Kubizňák (pavel.kubiznak@gmail.com). Úklid řeší personál podle index.html;
  den odjezdu = den úklidu (mezi 10:00 a 15:00).
