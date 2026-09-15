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
  v plnou barvu. Tooltip vypíše všechny dotčené pobyty.
- **Banner** nad kalendářem — souhrn s odkazem, který skočí na dotčený měsíc.
- **Jen jedna úroveň.** Oba pobyty živé ve `feed.ics` = červeně „dvojitá rezervace".
  Nic jiného se nehlásí — druhá, oranžová úroveň („❓ překryv se starým záznamem")
  je od 2026-09 zrušená, viz níž.

### Nepotvrzené záznamy se nezobrazují vůbec (2026-09-09)

Majitel: *„najedu na termín, je tam napsané dvě rezervace a booking není ve feedu — vždycky
se hrozně leknu, že mám dvojitou rezervaci. Potřebuju, aby tam fakt nebylo, co není
potvrzené."* Šrafování už bylo pryč (viz níž), ale záznam zůstával v tooltipu, v banneru,
v obsazenosti a v owner tabulce — takže strašil dál.

Rozhodovadlo je **`isGhost(b, today)` = `b.stale && b.end > today`**, a filtruje se **jednou**,
na začátku `renderCalendar()`. Všechno pod tím (mřížka, tooltip, obsazenost, banner, přehled
úklidů, owner tabulka, KPI, tržby, CSV) pak počítá jen s tím, co platí.

⚠️ **`stale` NENÍ „neexistuje".** Feed nese jen dnešek a budoucnost, takže **každý proběhlý
pobyt zestárne na `stale` sám od sebe** — k 2026-09-09 je takových 21 z 30. Plošné skrytí
všeho `stale` by z kalendáře i z tržeb smazalo celou historii. Proto ta podmínka `end > today`:
duch je jen pobyt, který **má teprve proběhnout** a přesto ve feedu není (propadlá
předrezervace, storno). Archiv se kreslí dál světle (`.ghost`).

Skryté se neztrácí — hub je ztrátový a platná rezervace z něj vypadnout může:
- `index.html` → panel „Správa uložené historie", záznam označený „není ve feedu, v kalendáři skryto";
- `owner.html` → sekce „🗂 Nepotvrzené záznamy mimo kalendář" pod tabulkou;
- `data/history.json` se nemění vůbec.

Při té příležitosti opravena chyba v `owner.html`: `fetchAndMergeRemoteHistory()` **zahazoval
příznak `stale`**, takže na majitelské stránce byl každý archivní záznam „živý" a překryv s ním
svítil **červeně** jako skutečná dvojitá rezervace (23 buněk, 36 šrafovaných půldnů k 2026-09-09).

Stav k 2026-09-09, ověřeno v Chromiu proti živým datům na obou stránkách: **0 šrafovaných
půldnů, 0 červených buněk, banner skrytý, 0 JS chyb**, 25 měsíců se renderuje, 9 nepotvrzených
záznamů skryto a vypsáno v panelu, archiv (1.–6. 9. 2026) se pořád kreslí světle, obsazenost
srpna 2027 spadla z 22/31 na 15/31. Podvrženými daty ověřené i všechny čtyři větve:
živá×živá → 5 červených buněk + 8 šraf + banner + oddělovač `#7B241C`; živá×duch → čistý pobyt;
duch×duch → prázdno; archiv → světle.

**⏭️ Stejná falešná hláška je pořád ve dvou dalších místech** (obojí v repu `villa-rudolf-site`),
protože ani jedno `stale` nefiltruje: `/sprava/` (`sprava.js`, `detectConflictsClient`) a
hlídač `n8n/VrConflictWatch` — ten navíc posílá e-maily. Viz tamní `STAV.md`.

### Šrafuje se JEN skutečná dvojitá rezervace (2026-08-13)

Majitel 5. 8.: *„je to těžko pochopitelný, uklízečky se v tom ztratí."* Měl pravdu a data
mu dala za pravdu dvakrát: k 2026-08-13 bylo v kalendáři **15 šrafovaných buněk a ani jedna
nebyla skutečný konflikt** — všech 5 překryvů mělo aspoň jednu stranu mrtvou. Pro úklid je to
navíc informace k ničemu: den odjezdu je den úklidu bez ohledu na kolizi v archivu.

Rozhodovadlem je nová funkce **`shown(list)`** — co se z půldne opravdu kreslí:

| v půldni sedí | kreslí se | šrafa | rámeček |
|---|---|---|---|
| ≥2 **živé** rezervace | obě, pruhy | ✅ ano | červený `.conflict` |
| živá + mrtvá (`stale`) | jen ta živá | ne | žádný |
| jen mrtvá / víc mrtvých | první mrtvá, světle (`.ghost`) | ne | žádný |

**Mrtvý záznam sám v půldni se schválně kreslí dál.** Hub je ztrátový — když z feedu vypadne
platná rezervace, archiv je jediný doklad, že tam pobyt je. Prázdná buňka by tvrdila „volno"
a to je horší chyba než šrafa. Skrývá se jen tam, kde je stejně překrytý živou rezervací
(přeuložený pobyt dostane nové UID a ten starý osiří — to byl zdroj falešných poplachů).

Oranžový čárkovaný rámeček + „?" (`.conflict-soft`) je **pryč z obou stránek**. Překryv se
starým záznamem zůstává v tooltipu a v banneru nad kalendářem — v jednom místě místo
rozmazaný přes 15 buněk.

`isGhost()` / `getDayHalves()` / `shown()` / `halfStyle()` / `findOverlaps()` / `renderConflictBanner()` jsou
v `index.html` i `owner.html` **duplicitně a musí zůstat identické** — obě stránky
jsou samostatné, sdílený JS soubor tu není.

Stav k 2026-08-13: ověřeno v Chromiu proti živým datům — **15 šrafovaných buněk → 0**,
0 červených rámečků, 0 JS chyb, 25 měsíců se renderuje. Vizuálně potvrzeno na květnu
a červnu 2027 (dřív nejhorší chuchvalec, teď čistý blok platformy).
**Červená větev ověřená podvrženými daty** (dvě živé rezervace přes sebe → 6 šrafovaných
půldnů + 4 červené buňky, oddělovač `#7B241C` na místě), a taky obě negativní větve
(živá×mrtvá i mrtvá×mrtvá → 0 šraf, buňka zůstane obarvená). První ostrý červený případ
si pořád zaslouží pohledem zkontrolovat. Obsazenost v owner KPI se nemění (počítá se
po nocích přes sjednocení dní, ne přes barvy).

## Předrezervace a přímý prodej (kód HOTOV 2026-09-09, čeká na migraci v Supabase)

Pobyt prodaný **napřímo** není v žádném feedu, takže pro tenhle repo — a přes `history.json`
i pro veřejnou dostupnost na villarudolf.com — do teď neexistoval. Přesně tak zmizel termín
**14.–21. 8. 2027**: majitel vystavil zálohovou fakturu, ta byla uhrazená, peníze dorazily
do banky — a protože platba prošla bez povšimnutí, do systému se nedostalo nic. V kalendáři
po tom týdnu zůstal jen mrtvý blok z Airbnb (`3f05fcf7c453a6b3`, ve feedu byl **jediný běh**
29. 8. 2026 v 16:43, commit `80e7c62`, a hned zase zmizel).

**Spouštěčem není platba, ale VYSTAVENÍ ZÁLOHOVÉ FAKTURY.** Tím vzniká předrezervace, která
termín drží; platba jen rozhoduje, jestli přežije.

```
PŘEDREZERVACE ── uhrazeno do splatnosti ──▶ REZERVACE
              ── neuhrazeno do hold_until ─▶ propadlá (termín se uvolní)
```

Zdroj pravdy je `/sprava/` (Supabase, `vr_holds`); Action tenhle repo krmí jedním RPC dotazem
navíc — `vr_public_holds()`, který vrací **jen** `{uidh,start,end,kind,holdUntil}`. Detaily,
včetně proč to má vlastní tabulku a proč propadnutí nepotřebuje cron, jsou
v [`docs/CLAUDE-HANDOFF.md`](docs/CLAUDE-HANDOFF.md) → „Předrezervace a přímý prodej".

Co je na tom v tomhle repu podstatné:

- **Pátá platforma `Přímá`** (fialová `#8E44AD` / `#F4ECF7`) v `COL`/`LIGHT` obou stránek
  i v `PLATFORMS` v `update_history.py`.
- **`kind`** v `history.json`: `hold` (předrezervace) / `direct` (potvrzená přímá rezervace).
  U záznamů z feedu pole není.
- **Vzhled předrezervace** = světlá výplň + **čárkovaný fialový obrys** (`.half-*.pre`).
  Ne stejný jako archivní záznam (tečkovaně) — dvě různé věci ve stejném vzhledu byla
  ta past ze srpna.
- **Předrezervace NENÍ duch.** `isGhost()` skrývá záznam, který z feedu *vypadl*;
  předrezervace ve feedu ze své podstaty nikdy nebyla a přitom platí. Proto jí
  `historyToEvents()` nikdy nenastaví `stale` (`!h.stale && !h.kind`) a filtrem
  na začátku `renderCalendar()` projde. Skrýt ji by znamenalo nabízet obsazený
  termín jako volný — přesně ta chyba, kvůli které modul vznikl.
- **Předrezervace není úklid.** `getDayHalves()` vrací nově `isCleaning`; u holdu se
  nekreslí „↑10", nepočítá se do přehledu úklidů ani do majitelských KPI.
- **Předrezervace se nepočítá ani do obsazenosti a tržeb** (doplněno 2026-09-15, viz níž):
  chip v záhlaví měsíce na obou stránkách i `buildMonthly()` drží stejnou hranici jako
  `computeKPIs()`. Cenu jí tabulka zadat dovolí — majitel ji zná dřív, než je uhrazená —
  ale do čísel vstoupí až po potvrzení.
- **Cache v prohlížeči se srovnává proti snapshotu.** `mergeHistory()` umí jen přidat
  a přepsat; `dropVanishedDirectSales()` (v obou stránkách, **identická**) po úspěšném
  načtení `history.json` smaže z `localStorage` záznamy přímého prodeje, které v něm
  nejsou. Bez toho propadlý hold přežije v prohlížeči až do prune a — protože nikdy
  nezestárne na ducha — dělá i falešnou dvojitou rezervaci proti blokaci z feedu.
  Na feedové a ruční záznamy se nesahá. **Prázdné pole je platná odpověď** (archiv
  opravdu nic nedrží) a cache se podle něj srovná taky; vynechá se jen to podezřelé —
  rozbitý fetch, nevalidní JSON, nebo pole, ze kterého neprošel ani jeden řádek.
  ⚠️ **Cena pobytu se při tom stěhuje.** Přímý prodej zablokovaný na platformě se vrátí
  feedem pod **jiným `uidh`**, takže původní záznam zmizí a `pruneOrphanPrices()` by
  ručně zadanou cenu zahodila jako osiřelou. `migrateDirectSalePrices()` (jen
  `owner.html`, ceny jinde nejsou) ji proto v `load()` **před** prune přesune na náhradu
  se shodným `(start, end)` — a nikdy nepřepíše cenu, kterou náhrada už má.
  Dědic musí být **živá událost z feedu** (`!stale && !kind`): archivní duch na stejný
  termín kalendář stejně skrývá, takže cena na něm je ztracená.
  Proto taky `owner.html` snapshot **použije až na úspěšné větvi `load()`, celý najednou**
  (`pendingSnapshot`): smazat zrušený přímý prodej a přidat jeho náhradu patří k sobě.
  Po půlkách to nejde ani jedním směrem — smazat dřív znamená přijít o migraci ceny, když
  feed spadne; přidat dřív znamená mít chvíli v cache pobyt i jeho blokaci, a to je
  falešná dvojitá rezervace. `index.html` ceny nemá a maže rovnou.
  Když cena v tu chvíli není po ruce (žije jen ve vzdáleném `prices.json` a ten se
  nestáhl), zapamatuje se dvojice `starý klíč → dědic` (`villa_cal_price_heirs_v1`, TTL
  90 dní) a stěhování se dokončí, až cena dorazí. **Zastavit kvůli ceníku celé srovnání
  cache by bylo horší:** poškozený `prices.json` by ho zablokoval napořád.
- **Do `feed.ics` se přímý prodej nepíše.** Ten soubor je zrcadlo platforem; publikovat
  vlastní rezervace ven je samostatný krok (viz „Cíl dál" níž).
- **Hold se shodným termínem jako živá událost z feedu se nepublikuje** — to je vlastní
  blokace na platformě, ne druhá rezervace.
- **Když RPC selže, holdy v archivu zůstanou** a běh pokračuje (na rozdíl od selhaného feedu).
  Totéž platí, když odpověď **přijde, ale neprojde z ní ani jeden řádek**: `valid_holds()`
  vrátí `None` (nedostupné), ne prázdný seznam. Prázdný seznam je pro `apply_holds()`
  rozkaz „žádné předrezervace neexistují" a smazal by z archivu všechen přímý prodej —
  prodané termíny by se začaly nabízet jako volné.

`isHold()` / `holdNote()` / `fmtISO()` jsou v `index.html` i `owner.html`
**duplicitně a musí zůstat identické**, stejně jako zbytek půldenní logiky
(`getDayHalves` / `isGhost` / `shown` / `halfStyle` / `findOverlaps`).

Ověřeno 2026-09-09 v Chromiu proti živým datům + podvrženým holdům: 25 měsíců, 0 JS chyb;
předrezervace se kreslí čárkovaně, den odjezdu holdu **nemá** „↑10" a v přehledu úklidů
chybí, potvrzená přímá rezervace se chová jako běžný pobyt, a hold, který částečně koliduje
s živou rezervací z Booking.com, správně vyvolá červený rámeček i banner. Offline testy
skriptu: `python3 .github/scripts/test_update_history.py` (hub mód pořád bajtově shodný).

⚠️ **Než Pavel spustí migraci `20260909_vr_holds.sql` v Supabase**, vrací RPC 404, skript to
zaloguje jako `::warning::` a jede dál v původním chování. Nasadit se to tedy dá v libovolném
pořadí.

Chybu v `owner.html`, kde `fetchAndMergeRemoteHistory()` zahazoval příznak `stale`, mezitím
opravila stejná změna, která zavedla `isGhost` — obě session na ni narazily nezávisle.

## Čtyři feedy místo jednoho hubu (kód HOTOV 2026-08-13, čeká na 3 secrety)

Dřív se četl **jen** e-chalupy feed. E-chalupy fungují jako hub — mají cross-iCal na Airbnb,
Booking i FeWo — a svůj souhrn posílají dál. Tím vznikaly oba problémy najednou:

- **duplicity** — jeden pobyt se vrací zpátky jako blok z cizí platformy;
- **ztráty** — e-chalupy odmítají uložit rezervaci překrývající existující, takže platná
  rezervace z druhého kanálu se do feedu vůbec nedostane (3.–10. 7. 2027, Booking.com).

`update_history.py` teď umí číst **čtyři feedy zvlášť** a filtrovat každý na vlastní
rezervace kanálu. Přepíná se sám podle toho, co je nastavené:

| | |
|---|---|
| **HUB MODE** | nastavený jen e-chalupy feed → chová se **přesně** jako dřív, platforma se bere z UID |
| **MULTI MODE** | dva a víc feedů → platforma = **kanál, ze kterého feed přišel**, cizí bloky se filtrují |

URL feedů se čtou z prostředí, **nikdy z repa**: `ICAL_URL_AIRBNB`, `ICAL_URL_BOOKING`,
`ICAL_URL_FEWO`, `ICAL_URL_ECHALUPY` (workflow je bere ze secrets). Nenastavený secret =
prázdný řetězec = feed se přeskočí. **Dokud Pavel secrety nepřidá, běží to v hub módu
a nezmění se vůbec nic** — ověřeno testem, který pouští starou i novou verzi nad stejným
feedem a diffuje `history.json` i `feed.ics` (bajtová shoda).

### Tři věci, kterými to stojí a padá

1. **Filtr vlastních rezervací.** Cizí blok se pozná podle UID (platforma nerazítkuje cizí
   systém na vlastní rezervaci) a podle značek v SUMMARY. **Asymetrie je schválná:** blok se
   zahodí, jen když je jeho domovský kanál sám nakonfigurovaný — tedy když ten pobyt jistě
   přijde z vlastního feedu. Jinak se **nechá** (duplicita je menší zlo než ztracená
   rezervace) a zaloguje se. Každý zahozený záznam je v logu i s důvodem; feed, ze kterého
   neprojde nic, křičí `::warning::`.
2. **Pojistka proti falešnému poplachu.** Kdyby filtr někdy pustil zrcadlo dál, ten samý
   pobyt by byl ve dvou feedech, oba živé → **červená dvojitá rezervace**, přesně ten šum,
   co jsme právě odstranili z UI. Proto se slučují události se **shodným** `(start, end)`
   napříč kanály (zrcadlo sedí den na den; skutečná kolize skoro nikdy) a každé sloučení
   se hlásí `::warning::`. Kolize uvnitř jednoho kanálu se nesluší nikdy.
3. **Kontinuita `uidh`.** Tenhle pobyt má v hub feedu **jiné UID** než ve feedu svého kanálu,
   takže naivní přepnutí by dalo každé živé rezervaci nový `uidh`: staré záznamy by osiřely
   na duchy a — hlavně — `/sprava/` na villarudolf.com se na kalendář váže právě přes tenhle
   klíč (`vr_bookings.uidh`). Skript proto při shodě `(start, end, platform)` **převezme
   archivní `uidh`** místo založení nového. Každé převzetí je v logu, jeden archivní klíč
   se převezme nejvýš jednou za běh.

Navíc: když **kterýkoli** feed selže (výpadek, přihlašovací stránka místo iCal), skript
skončí chybou a **archiv nepřepíše** — jinak by feed bez rezervací vypadal jako feed, kde
všechny rezervace zmizely, a nechal by je zestárnout do `stale`.

Testy: `python3 .github/scripts/test_update_history.py` (bez závislostí, bez sítě, pouští je
i workflow před ostrým během). `--dry-run` spočítá vše a nic nezapíše, `--fixtures <dir>`
čte `<dir>/<kanál>.ics` místo sítě.

**⏭️ Zbývá:** přidat do repo secrets `ICAL_URL_AIRBNB`, `ICAL_URL_BOOKING`, `ICAL_URL_FEWO`
(a ideálně `ICAL_URL_ECHALUPY`, viz níž) a pak pustit workflow ručně s `--dry-run`, než se
nechá zapisovat. Filtrovací pravidla jsou navržená podle toho, jak vypadá **hub** feed —
ostré feedy jednotlivých kanálů zatím nikdo neviděl, takže první běh je potřeba přečíst
v logu a pravidla případně doladit. Proto ten hlasitý log a proto `--dry-run`.

⚠️ **Legacy e-chalupy URL i s klíčem je pořád v `update_history.py`** jako fallback, aby
Action nepřestala běžet. V repu bylo odjakživa, takže je stejně prozrazené — ale patří pryč:
nastav `ICAL_URL_ECHALUPY` jako secret a konstantu `LEGACY_HUB_URL` smaž.

Cíl dál: vlastní feed publikovat **ven** a nechat platformy odebírat jeho, ne e-chalupy.

**Jména hostů z feedů nejdou** (ověřeno 2026-08-04 na živém feedu, 34 událostí):
Booking posílá `SUMMARY: CLOSED - Not available`, Airbnb `Reserved` — bez jména.
Jméno dává jen FeWo (křestní) a e-chalupy (volný text majitele). Slučovat podle jmen tedy
nelze a veřejná data zůstávají anonymizovaná.

Channel manager (Lodgify ap.) je **zamítnutý**: vyžaduje jednotnou měnu napříč kanály,
CZK nepodporuje → Booking by musel prodávat v EUR, výplata by přišla v CZK a majitel by
platil dvojí konverzi.

## Ikona na ploše iPhonu (hotovo 2026-09-10)

Obě stránky jdou přidat na plochu (Safari → **Sdílet → Přidat na plochu**) a spustí se
jako appka bez adresního řádku:

| stránka | ikona | název pod ikonou | manifest |
|---|---|---|---|
| `index.html` (úklid) | **modrá** `icons/icon-*.png` | Kalendář | `manifest.webmanifest` |
| `owner.html` (majitel) | **zlatá** `icons/owner-icon-*.png` | Majitel | `owner.webmanifest` |

Dvě barvy schválně — obě stránky sedí na ploše vedle sebe a jinak by se nedaly rozeznat.

- **PNG se commitují**, nekreslí se za běhu. Zdroj je `icons/mkicons.py` (Pillow, vektorová
  kresba do 4× plátna a zmenšení). Při změně barev pusť skript znovu, PNG přepíše na místě.
  iOS bere pro `apple-touch-icon` **jen PNG** — SVG neumí, proto ta cesta přes generátor.
- **Standalone nemá reload** prohlížeče. Data se tedy obnovují jen tlačítkem 🔄 Obnovit
  v hlavičce stránky — to tam musí zůstat, jinak by na ploše šla dostat zaseknutá cache.
- **Okraj stránky drží proměnná `--pad`**, media queries mění jen ji; `body` k ní přičítá
  `env(safe-area-inset-*)`, aby obsah nelezl pod výřez a domovský indikátor. Nevracej
  `body { padding: … }` zpátky do media queries.
- ⚠️ **`owner.html` se po každém studeném startu zeptá na token.** Je to schválně:
  token se drží jen v paměti stránky (`sessionToken`), nikde se neukládá a z URL se maže.
  Ikona na ploše na tom nic nemění — ušetří jen hledání odkazu, ne přihlášení.

## Provozní pravidla (DŮLEŽITÉ)

1. **Nikdy needitovat HTML přes GitHub web editor** — CM6 korumpuje backticky (`` ` `` → `f`).
   Nasazuj `git push` z tohoto klonu, nebo `gh api --method PUT .../contents/<path>` s base64.
2. `data/*` píše GitHub Action — ruční změny `history.json` / `feed.ics` příští běh přepíše.
   **Jediná výjimka je smazání mrtvého (`stale`) záznamu.** Záznam může vzniknout jen
   z feedu nebo z předchozího `history.json` (`load_history()`), takže co v obou chybí,
   se nevrátí. Přidání záznamu nebo změna hodnot se naopak přepíše vždy.
   ⚠️ Záznam, který ve `feed.ics` **pořád je**, mazat nemá smysl: příští běh ho založí
   znovu. `uidh` zůstane stejný (je to `sha256(UID)[:16]`, takže z téhož feedu vyjde
   pořád stejně) a vazba na `/sprava/` se neutrhne — ztratí se ale **`firstSeen`**,
   protože se dopočítá jako dnešek.
3. Repo je **veřejné**. Do klientských HTML nikdy: e-chalupy feed URL/klíč, owner token, ceny v plaintextu.
4. Veřejná data jsou **anonymizovaná** (od 2026-07): `history.json` =
   `{uidh,start,end,platform,firstSeen,lastSeen,stale}`, žádná jména hostů.
   Sanitizace u zdroje v `.github/scripts/update_history.py`.
   `stale:true` = záznam už není v aktuálním `feed.ics` (v archivu zůstává schválně).
5. `gh` token nemá **`workflow` scope** — úpravy `.github/workflows/*` přes `gh api` selžou,
   dokud Pavel nespustí `gh auth refresh -h github.com -s workflow`. **Přes `git push`
   z klonu ale workflow soubory měnit jdou** (ověřeno 2026-08-13) — omezení je na `gh` tokenu,
   ne na gitových přihlašovacích údajích.
6. Po nasazení ověřuj přes `gh api .../contents/<file>` (raw.githubusercontent má ~5 min cache;
   Pages ~10 min). **Z cloudové session `pavelkubiznak.github.io` nestáhneš** — blokuje ji
   síťová politika prostředí (403 / `EGRESS_BLOCKED`, `curl` i fetch nástroje). Nasazení se
   pak ověřuje nepřímo: úspěšný běh workflow „pages build and deployment" **nad daným
   commitem** + obsah `origin/main`. Ostrý pohled do prohlížeče zůstává na majiteli.

## Nedávné změny

- 2026-07: anonymizace veřejných dat (jména pryč, UID → hash).
- 2026-07: okno kalendáře = aktuální měsíc **+24 měsíců** (vždy ≥2 roky dopředu).
- 2026-08: v záhlaví měsíce chip **obsazené noci / dny · %** (počítáno po nocích).
- 2026-08: **překryvy rezervací se zobrazují** (šrafování + banner) místo tichého přepsání;
  `history.json` dostal `firstSeen` / `lastSeen` / `stale`.
- 2026-08-13: **šrafuje se jen skutečná dvojitá rezervace** (viz výš) — 15 matoucích
  šrafovaných buněk pryč, `.conflict-soft` zrušen.
- 2026-09-09: **nepotvrzené záznamy se v kalendáři nezobrazují** (`isGhost`, viz výš) —
  a v `owner.html` opraveno zahazování příznaku `stale` (archiv tam svítil červeně).
- 2026-08-13: **čtení čtyř feedů** v `update_history.py` (hub/multi mode, filtr vlastních
  rezervací, kontinuita `uidh`, offline testy). Čeká na 3 secrety, zatím běží hub mode.
- 2026-09-10: **ikona na plochu iPhonu** pro obě stránky (viz výš) — apple-touch-icon,
  manifest, standalone režim a respektování safe-area.
- 2026-09-15: **nálezy Codexu na #9** — cache v prohlížeči neztrácela zrušený hold
  (`dropVanishedDirectSales`), `Přímá` chyběla v rozpadu platforem i v `LIGHT` v `owner.html`,
  oceněná předrezervace lezla do měsíčních tržeb a do obsazenosti v záhlaví měsíce,
  `valid_holds()` spadla na řádku, který není objekt.
- 2026-09-09: **předrezervace a přímý prodej** (viz výš) — pátá platforma `Přímá`,
  `kind` v `history.json`, čtení `vr_public_holds()` ze Supabase.
- 2026-09-04: ručně smazán osiřelý duch `3d35fe03b6a04aef` (Airbnb, 17.–19. 9. 2026).
  V `feed.ics` nikdy nebyl, `firstSeen`/`lastSeen` obojí `null`, v repu už v prvním commitu
  (2026-08-07) — původ se z dat určit nedá. **Co ten pobyt byl, ověřené není** (feedy jména
  neposílají); sedí propadlá předrezervace i přeuložený pobyt, protože navazuje den na den
  na živou Airbnb rezervaci 19.–26. 9. Jistotu dá jen Airbnb extranet. Smazání bylo
  rozhodnutí majitele; prune (`end >= dnes−18 měsíců`) by ho jinak držel do března 2028.
  Že smazání drží, viz výjimku v provozním pravidle 2.

## Kontext

Majitel Pavel Kubizňák. Úklid se řídí `index.html` (den odjezdu = den úklidu, mezi 10:00 a 15:00).
Ceny nejsou v iCal — majitel je zadává ručně v `owner.html`, ukládají se šifrovaně.
