#!/usr/bin/env python3
"""Fetch the villa iCal feed(s) and update data/history.json — GitHub Action, every ~3 h.

PRIVACY MODEL (important):
The public files data/history.json and data/feed.ics are SANITIZED before writing —
they carry NO guest names and NO contact details. The reservation UID (which encodes
the platform reservation number) is replaced by

    uidh = first 16 hex chars of sha256(uid)      # utf-8 bytes, lowercase hex

`uidh` is a deterministic, one-way key: it merges the same reservation across the
feed, the archive and the clients' localStorage, yet cannot be reversed to the
platform reservation number. The exact same hashing is implemented in index.html and
owner.html (JS) — keep the three in lock-step. It is ALSO the join key used by
/sprava/ on villarudolf.com (vr_bookings.uidh) — see UID CONTINUITY below.

history.json entries:  { "uidh", "start", "end", "platform",
                         "firstSeen", "lastSeen", "stale" }      (sorted by start)
feed.ics VEVENTs:      SUMMARY = platform, UID = uidh, only DTSTART/DTEND/DTSTAMP/STATUS
                        (Description / Attendee / Organizer / any name-bearing field dropped)

STALE / "GHOST" TRACKING (added 2026-08):
The archive is upsert-only — an entry is never deleted just because it vanished from the
feed, it is only pruned 18 months after its `end`. That is deliberate (the upstream hub is
lossy, see below), but it means expired holds, cancelled bookings and reservations that were
edited (edit => new UID => old entry orphaned) linger and show up as phantom overlaps.

So instead of deleting we MARK:
    firstSeen  first run date this uidh appeared in the feed
    lastSeen   last run date it appeared   (None = never seen since tracking began)
    stale      True once lastSeen is older than STALE_AFTER_DAYS (or unknown)

Why not just drop stale entries: e-chalupy (the hub feed) REFUSES to store a reservation that
overlaps one it already has, so a genuine double booking is silently missing from the feed —
the archived copy is then the only evidence it exists. Dropping stale entries would delete
exactly the records worth looking at. Hence: keep, flag, and let the UI show them differently.

================================================================================
FOUR FEEDS INSTEAD OF ONE HUB (2026-08-13)
================================================================================
Historically this script read ONE feed: e-chalupy, which acts as a hub (it holds
cross-iCal links to Airbnb, Booking and FeWo and republishes a combined calendar).
That single source caused both failure modes at once:

  * duplicates — one stay comes back as a foreign-platform block, and
  * LOSSES     — e-chalupy refuses to store a reservation overlapping an existing one,
                 so a valid booking from another channel never reaches the feed at all
                 (documented: 3.–10. 7. 2027, Booking.com).

The fix is to read each channel's OWN feed and keep only that channel's own
reservations. Then "two feeds claim the same nights" means a real double booking,
with no heuristics. Cross-iCal between the platforms stays as it is — it still
blocks availability, we simply stop treating those mirrored blocks as bookings.

MODES (chosen automatically, so nothing changes until the secrets exist):
  HUB MODE    — only the e-chalupy feed is configured. Behaves exactly as before:
                the platform is derived from the UID of each event.
  MULTI MODE  — two or more feeds configured. The platform is the CHANNEL THE FEED
                BELONGS TO, and each feed is filtered down to its own reservations.

Feed URLs come from the environment (they are private keys — never commit them):
    ICAL_URL_AIRBNB · ICAL_URL_BOOKING · ICAL_URL_FEWO · ICAL_URL_ECHALUPY

--------------------------------------------------------------------------------
OWN-BOOKING FILTER — the part that must not silently eat a real reservation
--------------------------------------------------------------------------------
A channel's feed contains its own reservations AND blocks mirrored in from the other
channels. Two signals separate them:

  1. UID origin. Platforms stamp the originating system into the UID and do NOT stamp
     a foreign system onto their own reservations. So an event carrying @booking.com
     inside the Airbnb feed is a mirrored Booking block — dropping it is safe.
     IMPORTANT ASYMMETRY: we only drop when the implied channel is ITSELF CONFIGURED,
     i.e. when we are certain to pick that stay up from its own feed. If the implied
     channel is not configured, the event is KEPT (a duplicate is a lesser evil than
     a lost booking) and logged.
  2. SUMMARY markers. Known block texts per channel (e.g. Airbnb's "Airbnb (Not
     available)", which it writes for every blocked day).

Every dropped event is logged with its dates and the reason, and a feed that yields
zero own bookings out of a non-empty calendar raises a warning — a wrong rule shows up
in the run log instead of quietly deleting a stay. Run with --dry-run to inspect
without writing anything.

--------------------------------------------------------------------------------
UID CONTINUITY — why this script rewrites uidh instead of minting new ones
--------------------------------------------------------------------------------
The same real stay has a DIFFERENT UID in the hub feed than in its home channel's
feed, so a naive switch would give every current booking a brand-new uidh. The old
entries would orphan into ghosts and — much worse — /sprava/ on villarudolf.com joins
its guest records to the calendar through exactly this key (vr_bookings.uidh). A fresh
uidh silently breaks that link for every live reservation.

So when a newly-seen event exactly matches an archived entry on (start, end, platform),
this script ADOPTS the archived uidh instead of inserting a new record. Each adoption is
logged. One archived uidh can be adopted at most once per run.
"""

import json, os, re, sys, hashlib
from datetime import datetime, timedelta
from urllib.request import urlopen, Request

HISTORY_FILE = 'data/history.json'
FEED_FILE    = 'data/feed.ics'

PLATFORMS = ('Airbnb', 'Booking.com', 'E-chalupy', 'Fewo-direkt')

# The Action runs every ~3 h. Two days of grace means a transient outage (or a few
# failed runs in a row) never flips a live booking to "stale" by accident.
STALE_AFTER_DAYS = 2

# Feed roster. `env` holds the URL; the channel name IS the platform in MULTI MODE.
# There is deliberately NO hardcoded fallback: a feed URL carries a private key and
# this repo is public. An unset secret means the feed is skipped, and with no feed at
# all the run aborts without touching the archive (see main()).
FEEDS = (
    {'channel': 'Airbnb',      'env': 'ICAL_URL_AIRBNB'},
    {'channel': 'Booking.com', 'env': 'ICAL_URL_BOOKING'},
    {'channel': 'Fewo-direkt', 'env': 'ICAL_URL_FEWO'},
    {'channel': 'E-chalupy',   'env': 'ICAL_URL_ECHALUPY'},
)

# SUMMARY texts that mark a blocked/mirrored day rather than a reservation of this
# channel's own. Matched case-insensitively against the whole (stripped) SUMMARY.
BLOCK_SUMMARIES = {
    'Airbnb': ('airbnb (not available)', 'not available'),
    # Booking and FeWo label their own reservations with these same generic texts,
    # so no SUMMARY-based rule may be applied to them — UID origin is the only signal.
    'Booking.com': (),
    'Fewo-direkt': (),
    'E-chalupy': (),
}


def uid_hash(uid):
    """Stable, unlinkable merge key: first 16 hex chars of sha256(uid).
    MUST match the JS uidHash() in index.html / owner.html byte-for-byte
    (utf-8 input, lowercase hex output, first 16 chars)."""
    return hashlib.sha256(uid.encode('utf-8')).hexdigest()[:16]


def ics_to_date(s):
    s = re.sub(r'[TZ].*', '', s)
    if len(s) < 8: return None
    try:    return datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except: return None


def uid_channel(uid):
    """Which system minted this UID. Same rules the hub feed has always used."""
    if '@airbnb.com'   in uid: return 'Airbnb'
    if '@booking.com'  in uid: return 'Booking.com'
    if '@'         not in uid: return 'Fewo-direkt'
    return 'E-chalupy'


# Kept under the old name: HUB MODE derives the platform exactly as it always did.
get_platform = uid_channel


def parse_ics(text):
    """Parse a raw feed into SANITIZED events.

    Returns dicts: {uidh, uid_ch, summary_is_block, start, end, dtstart, dtend, dtstamp}.
    The SUMMARY text is read ONLY to recognise block markers and is never propagated
    out — `summary_is_block` is a bool, the text itself is dropped here."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\n[ \t]', '', text)   # unfold
    events = []
    for block in text.split('BEGIN:VEVENT')[1:]:
        def get(key):
            m = re.search(r'^' + key + r'[^:]*:(.+)$', block, re.MULTILINE)
            return m.group(1).strip() if m else ''
        uid     = get('UID')
        summary = get('SUMMARY')
        dtstart, dtend, status = get('DTSTART'), get('DTEND'), get('STATUS')
        dtstamp = get('DTSTAMP')
        if not uid or not dtstart or not dtend: continue
        if status and status != 'CONFIRMED':    continue
        start, end = ics_to_date(dtstart), ics_to_date(dtend)
        if not start or not end:                continue
        events.append({
            'uidh':    uid_hash(uid),
            'uid_ch':  uid_channel(uid),
            'summary': summary.strip().lower(),   # consumed by own_bookings(), never emitted
            'start':   start.strftime('%Y-%m-%d'),
            'end':     end.strftime('%Y-%m-%d'),
            'dtstart': dtstart,
            'dtend':   dtend,
            'dtstamp': dtstamp,
        })
    return events


def own_bookings(events, channel, configured):
    """Keep only the reservations this channel actually owns.

    `configured` is the set of channels we read a feed for. A foreign-looking event is
    dropped only when its home channel is in that set — otherwise we would lose the
    stay entirely, and a duplicate is the lesser evil. Returns (kept, dropped_log)."""
    kept, dropped = [], []
    blockers = BLOCK_SUMMARIES.get(channel, ())
    for e in events:
        if blockers and any(b in e['summary'] for b in blockers):
            dropped.append((e, 'block marker in SUMMARY'))
            continue
        if e['uid_ch'] != channel:
            if e['uid_ch'] in configured:
                dropped.append((e, f"mirrored from {e['uid_ch']} (read separately)"))
                continue
            dropped.append((e, f"looks like {e['uid_ch']} but that feed is not "
                               f"configured — KEPT to avoid losing it"))
            kept.append(e)          # deliberately kept; the log line says so
            continue
        kept.append(e)
    return kept, dropped


def collapse_cross_feed_duplicates(events):
    """Safety net for a wrong own-booking rule.

    If the filter lets a mirrored block through, the same stay appears in two feeds and
    — both being live — would render as a RED double booking. That false alarm is the
    exact thing the calendar UI was just cleaned up to avoid, so collapse events that
    share an IDENTICAL (start, end) across DIFFERENT channels, keeping the one whose UID
    says it is the owner. Identical dates on two platforms is what a mirror looks like;
    a genuine double booking almost never lines up to the same day on both sides — and
    every collapse is logged loudly so a real one cannot pass unnoticed.

    Same-channel duplicates are left alone: those are a real same-platform clash and
    report_overlaps() must see them."""
    by_span = {}
    for e in events:
        by_span.setdefault((e['start'], e['end']), []).append(e)
    kept, collapsed = [], []
    for span, group in by_span.items():
        if len(group) < 2 or len({e['platform'] for e in group}) < 2:
            kept.extend(group)
            continue
        owner = next((e for e in group if e['uid_ch'] == e['platform']), group[0])
        kept.append(owner)
        collapsed.append((span, [e['platform'] for e in group], owner['platform']))
    return kept, collapsed


def build_feed(events):
    """Serialize a SANITIZED iCal snapshot from parsed events.
    SUMMARY = platform, UID = uidh; no Description / Attendee / Organizer / contact
    fields are ever emitted. Deterministic order → no spurious commits."""
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//villa-rudolf//sanitized booking feed//CZ',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
    ]
    for e in sorted(events, key=lambda x: (x['dtstart'], x['uidh'])):
        lines.append('BEGIN:VEVENT')
        lines.append('DTSTART:' + e['dtstart'])
        lines.append('DTEND:'   + e['dtend'])
        if e['dtstamp']:
            lines.append('DTSTAMP:' + e['dtstamp'])
        lines.append('SUMMARY:' + e['platform'])
        lines.append('UID:'     + e['uidh'])
        lines.append('STATUS:CONFIRMED')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'


def is_stale(last_seen, today):
    """An entry is stale once the feed stopped listing it (or never did).
    last_seen is None for entries that predate stale-tracking and are not in the
    current feed — we genuinely do not know when they were last real, so: stale."""
    if not last_seen:
        return True
    d = ics_to_date(last_seen.replace('-', ''))
    if not d:
        return True
    return (today - d).days > STALE_AFTER_DAYS


def load_history():
    """Read the existing history.json, accepting BOTH schemas:
      - new: {uidh, start, end, platform, firstSeen, lastSeen, stale}
      - old: {uid, guest, start, end, platform}  → migrated (uid hashed, guest dropped)
    firstSeen/lastSeen are preserved when present; absent lastSeen stays absent so the
    first run after this change honestly reports "never seen since tracking began".
    Returns a dict keyed by uidh."""
    try:
        with open(HISTORY_FILE) as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    history = {}
    for e in raw:
        if e.get('uidh'):
            uidh = e['uidh']
        elif e.get('uid'):
            # legacy entry — drop old Airbnb noise, then migrate
            if e.get('guest') == 'Airbnb (Not available)':
                continue
            uidh = uid_hash(e['uid'])
        else:
            continue
        if not e.get('start') or not e.get('end'):
            continue
        plat = e.get('platform')
        if plat not in PLATFORMS:
            plat = 'E-chalupy'
        history[uidh] = {'uidh': uidh, 'start': e['start'], 'end': e['end'], 'platform': plat,
                         'firstSeen': e.get('firstSeen'), 'lastSeen': e.get('lastSeen')}
    return history


def adopt_existing_uidh(events, history, today_s):
    """Carry archived uidh over to the same stay arriving under a new UID.

    Switching a stay from the hub feed to its home channel's feed changes its UID, hence
    its uidh. Left alone that orphans the archived entry into a ghost AND breaks the
    vr_bookings.uidh join used by /sprava/. So an event that is new to us but matches an
    archived entry on (start, end, platform) inherits that entry's uidh.

    Only archived entries not already claimed in this run are eligible, and each is
    adopted at most once. Returns a log of (old_uidh, new_uidh, start, end, platform)."""
    seen_now = {e['uidh'] for e in events}
    by_key = {}
    for h in history.values():
        if h['uidh'] in seen_now:
            continue                      # still arriving under its own uidh — leave it
        by_key.setdefault((h['start'], h['end'], h['platform']), []).append(h)
    adopted = []
    for e in events:
        if e['uidh'] in history:
            continue                      # already known under this uidh
        bucket = by_key.get((e['start'], e['end'], e['platform']))
        if not bucket:
            continue
        old = bucket.pop(0)
        adopted.append((old['uidh'], e['uidh'], e['start'], e['end'], e['platform']))
        e['uidh'] = old['uidh']
    return adopted


def report_overlaps(entries, today_s):
    """Log overlapping stays so the Action run itself flags double bookings.

    Stays are half-open [start, end) — `end` is the checkout day, so two stays only
    really clash when one starts before the other ends. Only stays that have not
    finished yet are worth reporting.

    A pair of LIVE entries is a genuine double booking. A pair where either side is
    stale is most likely archive residue — but not always: a real booking can be
    missing from the feed because the hub refused to import it over an existing
    overlap, which is precisely why these are surfaced rather than hidden.
    """
    fut = [e for e in entries if e['end'] >= today_s]
    real, suspect = [], []
    for i, a in enumerate(fut):
        for b in fut[i + 1:]:
            if a['start'] < b['end'] and b['start'] < a['end']:
                (real if not (a['stale'] or b['stale']) else suspect).append((a, b))

    def line(a, b):
        f = lambda e: (f"{e['start']}→{e['end']} {e['platform']}"
                       f"{' [stale]' if e['stale'] else ''}")
        return f'    {f(a)}  ×  {f(b)}'

    if real:
        print(f'::warning::{len(real)} REAL double booking(s) — both sides live in the feed')
        for a, b in real: print(line(a, b))
    if suspect:
        print(f'{len(suspect)} overlap(s) involving a stale entry (verify in the extranet):')
        for a, b in suspect: print(line(a, b))
    if not real and not suspect:
        print('No overlapping future stays.')


def resolve_feeds(fixtures=None):
    """Which feeds we read this run. With --fixtures, read <dir>/<channel>.ics instead
    of the network so the whole pipeline can be exercised offline."""
    out = []
    for f in FEEDS:
        if fixtures:
            path = os.path.join(fixtures, f['channel'] + '.ics')
            if os.path.exists(path):
                out.append({'channel': f['channel'], 'path': path})
            continue
        url = os.environ.get(f['env'], '').strip()
        if url:
            out.append({'channel': f['channel'], 'url': url})
    return out


def fetch(feed):
    """Read one feed. NB: never print the URL — it holds the private feed key."""
    if 'path' in feed:
        with open(feed['path'], encoding='utf-8') as fh:
            return fh.read()
    req = Request(feed['url'], headers={
        'User-Agent': 'Mozilla/5.0 (compatible; villa-calendar-bot/1.0)'
    })
    with urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='replace')


def collect_events(feeds, multi):
    """Fetch and filter every configured feed. Returns (events, ok) — ok is False when a
    feed failed, so the caller can refuse to rewrite the archive from partial data."""
    configured = {f['channel'] for f in feeds}
    events, ok = [], True
    for feed in feeds:
        ch = feed['channel']
        try:
            text = fetch(feed)
        except Exception as e:
            print(f'::error::{ch}: fetch failed: {e}', file=sys.stderr)
            ok = False
            continue
        if 'BEGIN:VCALENDAR' not in text:
            print(f'::error::{ch}: not a valid iCal', file=sys.stderr)
            ok = False
            continue
        parsed = parse_ics(text)

        if not multi:
            # HUB MODE — unchanged behaviour: the UID decides the platform, and the only
            # filter is Airbnb's "not available" auto-block noise.
            kept = [e for e in parsed if e['summary'] != 'airbnb (not available)']
            for e in kept:
                e['platform'] = e['uid_ch']
            print(f'{ch}: {len(parsed)} events → {len(kept)} bookings (hub mode)')
            events.extend(kept)
            continue

        kept, dropped = own_bookings(parsed, ch, configured)
        for e in kept:
            e['platform'] = ch          # the channel owns it — no UID guessing
        print(f'{ch}: {len(parsed)} events → {len(kept)} own bookings, {len(dropped)} filtered')
        for e, why in dropped:
            print(f"    - {e['start']}→{e['end']}: {why}")
        if parsed and not kept:
            print(f'::warning::{ch}: feed has {len(parsed)} events but NONE were kept as '
                  f'own bookings — the filter rule for this channel is probably wrong')
        events.extend(kept)
    return events, ok


def main():
    dry_run  = '--dry-run' in sys.argv
    fixtures = None
    if '--fixtures' in sys.argv:
        fixtures = sys.argv[sys.argv.index('--fixtures') + 1]

    feeds = resolve_feeds(fixtures)
    if not feeds:
        print('ERROR: no feed configured (set ICAL_URL_*)', file=sys.stderr); sys.exit(1)
    multi = len(feeds) > 1
    print(f"Mode: {'MULTI' if multi else 'HUB'} — reading "
          f"{', '.join(f['channel'] for f in feeds)}")

    history = load_history()
    print(f'Loaded {len(history)} existing entries (normalized to uidh, guest dropped)')

    events, ok = collect_events(feeds, multi)
    if not ok:
        # A feed that failed to load looks exactly like a feed with no bookings, and
        # rewriting the archive from that would age every stay it owned into `stale`.
        print('ERROR: at least one feed failed — refusing to rewrite the archive '
              'from partial data', file=sys.stderr)
        sys.exit(1)

    if multi:
        events, collapsed = collapse_cross_feed_duplicates(events)
        for span, plats, winner in collapsed:
            print(f'::warning::same nights {span[0]}→{span[1]} came from '
                  f'{" + ".join(plats)} — kept {winner}, treated the rest as a mirror. '
                  f'If these are genuinely two different stays, it is a DOUBLE BOOKING.')

    print(f'Parsed {len(events)} real booking events')

    now   = datetime.now()
    today = datetime(now.year, now.month, now.day)
    today_s = today.strftime('%Y-%m-%d')

    adopted = adopt_existing_uidh(events, history, today_s)
    for old, new, s, e_, p in adopted:
        print(f'uidh continuity: {s}→{e_} {p} kept archived key {old} (feed now says {new})')
    if adopted:
        print(f'{len(adopted)} stay(s) kept their archived uidh — /sprava/ links preserved')

    # Sanitized feed snapshot (public pages read it same-origin from GitHub Pages).
    # Written AFTER adoption so feed.ics and history.json agree on every uidh.
    feed_text = build_feed(events)

    # Anything in this run's feed is alive NOW: stamp lastSeen, keep the original firstSeen.
    # Anything absent keeps its old stamps and ages into `stale` on its own.
    new = sum(1 for e in events if e['uidh'] not in history)
    for e in events:
        prev = history.get(e['uidh'], {})
        history[e['uidh']] = {
            'uidh':      e['uidh'],
            'start':     e['start'],
            'end':       e['end'],
            'platform':  e['platform'],
            'firstSeen': prev.get('firstSeen') or today_s,
            'lastSeen':  today_s,
        }
    print(f'New: {new}, total: {len(history)}')

    # Prune older than 18 months
    m, y = now.month - 18, now.year
    while m <= 0: m += 12; y -= 1
    cutoff = f'{y:04d}-{m:02d}-01'
    history = {k: e for k, e in history.items() if e['end'] >= cutoff}
    print(f'After 18-month prune (cutoff {cutoff}): {len(history)} entries')

    for e in history.values():
        e['stale'] = is_stale(e.get('lastSeen'), today)

    output = sorted(history.values(), key=lambda e: e['start'])

    if dry_run:
        stale_n = sum(1 for e in output if e['stale'])
        print(f'DRY RUN — nothing written. Would write {len(output)} entries '
              f'({len(output) - stale_n} live, {stale_n} stale)')
        report_overlaps(output, today_s)
        return

    with open(FEED_FILE, 'w', encoding='utf-8') as f:
        f.write(feed_text)
    print(f'Sanitized feed snapshot written to {FEED_FILE}')

    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    stale_n = sum(1 for e in output if e['stale'])
    print(f'Written {len(output)} entries to {HISTORY_FILE} '
          f'({len(output) - stale_n} live, {stale_n} stale)')
    report_overlaps(output, today_s)


if __name__ == '__main__':
    main()
