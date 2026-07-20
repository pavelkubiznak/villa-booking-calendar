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
| Úklidový kalendář | `https://pavelkubiznak.github.io/villa-booking-calendar/` | pro úklidový personál — 14měsíční pohled, půldenní buňky, BEZ cen |
| Majitelský dashboard | `.../owner.html` | tržby/obsazenost/KPI — **chráněno tokenem** (token má jen Pavel, není nikde v repu) |

## Datové endpointy (veřejné, použitelné z jakékoli stránky)

GitHub Pages posílá `Access-Control-Allow-Origin: *` — endpointy lze fetchovat **cross-origin z libovolného webu**.

| Endpoint | Formát | Obsah | Čerstvost |
|---|---|---|---|
| `https://pavelkubiznak.github.io/villa-booking-calendar/data/feed.ics` | iCal | živý agregovaný feed rezervací (Airbnb+Booking+e-chalupy+Fewo) | snapshot každé ~3 h |
| `https://pavelkubiznak.github.io/villa-booking-calendar/data/history.json` | JSON | archiv rezervací (i těch, co už vypadly z feedu) | každé ~3 h při změně |
| `.../data/prices.json` | JSON (AES-GCM šifrovaný) | ceny pobytů — **může neexistovat (404)**; bez tokenu nečitelné | při exportu majitelem |

**Pro nové stránky používej tyto same-origin/Pages URL, NIKDY přímý e-chalupy feed** — jeho URL
obsahuje privátní klíč a záměrně bylo odstraněno ze všech klientských HTML (žije jen
v `.github/scripts/update_history.py`).

## Schéma history.json

Pole objektů, řazeno dle `start`:

```json
{ "uid": "18852-10696411@e-chalupy.cz", "start": "2026-04-25", "end": "2026-05-02",
  "guest": "bohemia - Vrieling", "platform": "E-chalupy" }
```

Sémantika:
- `start` = check-in (příjezd ~15:00), `end` = check-out (odjezd ~10:00) — **`end` je den odjezdu,
  noc z `end-1` na `end` je poslední obsazená**; počet nocí = `end − start` ve dnech.
- `platform` ∈ `Airbnb | Booking.com | E-chalupy | Fewo-direkt` (odvozeno z UID:
  `@airbnb.com` → Airbnb, `@booking.com` → Booking.com, bez `@` → Fewo-direkt, jinak E-chalupy).
- Záznamy `guest == "Airbnb (Not available)"` jsou šum (auto-blokace) a jsou **odfiltrované**.
- Archiv se prořezává na **18 měsíců** zpět (dle `end`); UID je unikátní klíč (merge = last-write-wins).
- ⚠️ `guest` obsahuje reálná jména hostů — osobní údaje, nešířit dál do dalších veřejných míst.

## Aktualizační pipeline

- GitHub Action `.github/workflows/update-history.yml`: cron `17 */3 * * *` + `workflow_dispatch`.
- Spouští `.github/scripts/update_history.py` (čistý stdlib Python, bez secrets — GITHUB_TOKEN stačí):
  stáhne e-chalupy iCal → zapíše `data/feed.ics` (verbatim snapshot) → merge do `data/history.json`
  (filtr šumu, prořez 18 m) → commit `[skip ci]` jen při změně.
- Klientské stránky se za běhu NEspoléhají na žádnou třetí stranu (CORS proxy byly odstraněny).

## Klientská architektura (obě stránky)

- `localStorage` klíče (sdílené oběma stránkami na stejném originu — záměrně):
  `villa_cal_v2` (krátkodobá cache feedu), `villa_cal_history_v1` (persistentní archiv, merge dle UID),
  `villa_cal_prices_v1` (jen owner: ceny `{uid: {amount, currency, mtime}}`),
  `villa_cal_owner_settings_v1` (kurz EUR).
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

## Kontext provozu

- Ceny pobytů NEJSOU v iCal (platformy je nedávají) — majitel je zadává ručně v owner.html.
- Vlastník: Pavel Kubizňák (pavel.kubiznak@gmail.com). Úklid řeší personál podle index.html;
  den odjezdu = den úklidu (mezi 10:00 a 15:00).
