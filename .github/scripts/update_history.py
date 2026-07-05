#!/usr/bin/env python3
"""Fetch villa iCal and update data/history.json — runs as GitHub Action every 6h."""

import json, re, sys
from datetime import datetime
from urllib.request import urlopen, Request

ICAL_URL     = 'https://www.e-chalupy.cz/api/calendar/18852/6C517e26581B794/default.ics'
HISTORY_FILE = 'data/history.json'
FEED_FILE    = 'data/feed.ics'

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
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\n[ \t]', '', text)   # unfold
    events = []
    for block in text.split('BEGIN:VEVENT')[1:]:
        def get(key):
            m = re.search(r'^' + key + r'[^:]*:(.+)$', block, re.MULTILINE)
            return m.group(1).strip() if m else ''
        uid, summary = get('UID'), get('SUMMARY')
        dtstart, dtend, status = get('DTSTART'), get('DTEND'), get('STATUS')
        if not uid or not dtstart or not dtend: continue
        if status and status != 'CONFIRMED':    continue
        start, end = ics_to_date(dtstart), ics_to_date(dtend)
        if not start or not end:                continue
        guest = summary or '(reserved)'
        if guest.upper() == 'RESERVED':         guest = 'Reserved'
        if guest.startswith('CLOSED'):           guest = '(Booking guest)'
        # Skip Airbnb auto-blocking noise:
        # Airbnb creates a 1-day "Airbnb (Not available)" event for every free day.
        # These are NOT real bookings — filter them out of history.json.
        if guest == 'Airbnb (Not available)':   continue
        events.append({'uid': uid,
                        'start':    start.strftime('%Y-%m-%d'),
                        'end':      end.strftime('%Y-%m-%d'),
                        'guest':    guest,
                        'platform': get_platform(uid)})
    return events

def main():
    try:
        with open(HISTORY_FILE) as f:
            raw = json.load(f)
            # Also clean up any old noise entries that were previously stored
            history = {e['uid']: e for e in raw
                       if e.get('guest') != 'Airbnb (Not available)'}
    except (FileNotFoundError, json.JSONDecodeError):
        history = {}
    print(f'Loaded {len(history)} existing entries (Airbnb noise filtered)')

    print(f'Fetching {ICAL_URL}')
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

    # Snapshot the raw feed so the public pages read it same-origin
    # (no CORS proxies, no feed key embedded in the HTML).
    with open(FEED_FILE, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'Feed snapshot written to {FEED_FILE}')

    events = parse_ics(text)
    print(f'Parsed {len(events)} real booking events (Airbnb noise excluded)')
    new = sum(1 for e in events if e['uid'] not in history)
    for e in events:
        history[e['uid']] = e
    print(f'New: {new}, total: {len(history)}')

    # Prune older than 18 months
    now = datetime.now()
    m, y = now.month - 18, now.year
    while m <= 0: m += 12; y -= 1
    cutoff = f'{y:04d}-{m:02d}-01'
    history = {uid: e for uid, e in history.items() if e['end'] >= cutoff}
    print(f'After 18-month prune (cutoff {cutoff}): {len(history)} entries')

    output = sorted(history.values(), key=lambda e: e['start'])
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f'Written {len(output)} entries to {HISTORY_FILE}')

if __name__ == '__main__':
    main()
