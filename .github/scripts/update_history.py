#!/usr/bin/env python3
"""Fetch villa iCal and update data/history.json — runs as GitHub Action every ~3h.

PRIVACY MODEL (important):
The public files data/history.json and data/feed.ics are SANITIZED before writing —
they carry NO guest names and NO contact details. The reservation UID (which encodes
the platform reservation number) is replaced by

    uidh = first 16 hex chars of sha256(uid)      # utf-8 bytes, lowercase hex

`uidh` is a deterministic, one-way key: it merges the same reservation across the
feed, the archive and the clients' localStorage, yet cannot be reversed to the
platform reservation number. The exact same hashing is implemented in index.html and
owner.html (JS) — keep the three in lock-step.

history.json entries:  { "uidh", "start", "end", "platform" }   (sorted by start)
feed.ics VEVENTs:      SUMMARY = platform, UID = uidh, only DTSTART/DTEND/DTSTAMP/STATUS
                        (Description / Attendee / Organizer / any name-bearing field dropped)
"""

import json, re, sys, hashlib
from datetime import datetime
from urllib.request import urlopen, Request

ICAL_URL     = 'https://www.e-chalupy.cz/api/calendar/18852/6C517e26581B794/default.ics'
HISTORY_FILE = 'data/history.json'
FEED_FILE    = 'data/feed.ics'

PLATFORMS = ('Airbnb', 'Booking.com', 'E-chalupy', 'Fewo-direkt')


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


def get_platform(uid):
    if '@airbnb.com'   in uid: return 'Airbnb'
    if '@booking.com'  in uid: return 'Booking.com'
    if '@'         not in uid: return 'Fewo-direkt'
    return 'E-chalupy'


def parse_ics(text):
    """Parse the raw feed into SANITIZED events.

    Returns dicts: {uidh, start, end, platform, dtstart, dtend, dtstamp}.
    The SUMMARY/guest text is read ONLY to filter Airbnb auto-block noise and
    never leaves this function — nothing name-bearing is propagated out."""
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
        # Airbnb fills every free day with a 1-day "Airbnb (Not available)" event.
        # These are NOT real bookings — filter them out (guest text used here only).
        if summary == 'Airbnb (Not available)': continue
        events.append({
            'uidh':     uid_hash(uid),
            'start':    start.strftime('%Y-%m-%d'),
            'end':      end.strftime('%Y-%m-%d'),
            'platform': get_platform(uid),
            'dtstart':  dtstart,
            'dtend':    dtend,
            'dtstamp':  dtstamp,
        })
    return events


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


def load_history():
    """Read the existing history.json, accepting BOTH schemas:
      - new: {uidh, start, end, platform}
      - old: {uid, guest, start, end, platform}  → migrated (uid hashed, guest dropped)
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
        history[uidh] = {'uidh': uidh, 'start': e['start'], 'end': e['end'], 'platform': plat}
    return history


def main():
    history = load_history()
    print(f'Loaded {len(history)} existing entries (normalized to uidh, guest dropped)')

    print('Fetching iCal feed')   # NB: never print ICAL_URL — it holds the private feed key
    try:
        req = Request(ICAL_URL, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; villa-calendar-bot/1.0)'
        })
        with urlopen(req, timeout=30) as r:
            text = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'ERROR: {e}', file=sys.stderr); sys.exit(1)

    if 'BEGIN:VCALENDAR' not in text:
        print('ERROR: not a valid iCal', file=sys.stderr); sys.exit(1)

    events = parse_ics(text)
    print(f'Parsed {len(events)} real booking events (Airbnb noise excluded)')

    # Sanitized feed snapshot (public pages read it same-origin from GitHub Pages)
    with open(FEED_FILE, 'w', encoding='utf-8') as f:
        f.write(build_feed(events))
    print(f'Sanitized feed snapshot written to {FEED_FILE}')

    new = sum(1 for e in events if e['uidh'] not in history)
    for e in events:
        history[e['uidh']] = {'uidh': e['uidh'], 'start': e['start'],
                              'end': e['end'], 'platform': e['platform']}
    print(f'New: {new}, total: {len(history)}')

    # Prune older than 18 months
    now = datetime.now()
    m, y = now.month - 18, now.year
    while m <= 0: m += 12; y -= 1
    cutoff = f'{y:04d}-{m:02d}-01'
    history = {k: e for k, e in history.items() if e['end'] >= cutoff}
    print(f'After 18-month prune (cutoff {cutoff}): {len(history)} entries')

    output = sorted(history.values(), key=lambda e: e['start'])
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f'Written {len(output)} entries to {HISTORY_FILE}')


if __name__ == '__main__':
    main()
