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
  Hlásí **jen** překryv dvou pobytů živých ve `feed.ics`, tj. skutečnou dvojitou
  rezervaci. Překryv s archivním (`stale`) záznamem se v banneru nehlásí (viz níž);
  zůstává v tooltipu buňky. Mazat archiv se nesmí: hub odmítá import přes existující
  překryv, takže i platná rezervace může z feedu zmizet.

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

Oranžový čárkovaný rámeček + „?" (`.conflict-soft`) je **pryč z obou stránek**.

### Oranžová sekce banneru zrušena taky (2026-08-27)

Zbytkem po předchozím kroku byla v banneru sekce „❓ N překryvů se starým záznamem".
Majitel se 27. 8. ptal, proč kalendář pořád hlásí překryvy, když žádný overbooking nemá —
a data mu zase dala za pravdu: **6 hlášení, 0 skutečných konfliktů.** Všech 6 mělo aspoň
jednu stranu mrtvou (dva přeuložené Booking pobyty 5/2027, zrcadlo Booking→E-chalupy
8/2027, mrtvý FeWo blok 6/2027 a tři čistí duchové v 1/2028, kde není ani jedna živá
rezervace). Ověřeno i přímo v `feed.ics`: **0 kolizí mezi 34 živými událostmi.**

`renderConflictBanner()` teď filtruje `overlaps` na `o.real` a **když nezbude nic, banner
se vůbec nezobrazí**. Informace se neztrácí — překryv s archivem je dál v tooltipu buňky
(`ghostNote()`, proto ta funkce zůstává). Mrtvé CSS `.conflict-banner h3.cb-soft`
a `.conflict-banner.soft` je smazané.

**Proč to není zametení pod koberec:** planý poplach na 6 místech způsobí, že se přehlédne
ten jeden skutečný. Banner je teď binární — červený = jednej.

`getDayHalves()` / `shown()` / `halfStyle()` / `findOverlaps()` / `renderConflictBanner()` jsou
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

## Provozní pravidla (DŮLEŽITÉ)

1. **Nikdy needitovat HTML přes GitHub web editor** — CM6 korumpuje backticky (`` ` `` → `f`).
   Nasazuj `git push` z tohoto klonu, nebo `gh api --method PUT .../contents/<path>` s base64.
2. `data/*` píše GitHub Action — ruční změny `history.json` / `feed.ics` příští běh přepíše.
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
   Pages ~10 min).

## Nedávné změny

- 2026-07: anonymizace veřejných dat (jména pryč, UID → hash).
- 2026-07: okno kalendáře = aktuální měsíc **+24 měsíců** (vždy ≥2 roky dopředu).
- 2026-08: v záhlaví měsíce chip **obsazené noci / dny · %** (počítáno po nocích).
- 2026-08: **překryvy rezervací se zobrazují** (šrafování + banner) místo tichého přepsání;
  `history.json` dostal `firstSeen` / `lastSeen` / `stale`.
- 2026-08-13: **šrafuje se jen skutečná dvojitá rezervace** (viz výš) — 15 matoucích
  šrafovaných buněk pryč, `.conflict-soft` zrušen.
- 2026-08-27: **banner hlásí jen skutečnou dvojitou rezervaci** — oranžová sekce
  „❓ překryv se starým záznamem" zrušena (6 planých hlášení, 0 konfliktů).
- 2026-08-13: **čtení čtyř feedů** v `update_history.py` (hub/multi mode, filtr vlastních
  rezervací, kontinuita `uidh`, offline testy). Čeká na 3 secrety, zatím běží hub mode.

## Kontext

Majitel Pavel Kubizňák. Úklid se řídí `index.html` (den odjezdu = den úklidu, mezi 10:00 a 15:00).
Ceny nejsou v iCal — majitel je zadává ručně v `owner.html`, ukládají se šifrovaně.
