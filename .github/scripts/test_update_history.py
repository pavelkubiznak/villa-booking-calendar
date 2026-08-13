#!/usr/bin/env python3
"""Offline tests for update_history.py — no network, no dependencies.

    python3 .github/scripts/test_update_history.py

Two things are worth proving here:

  1. HUB MODE IS UNCHANGED. Until the per-channel secrets exist, the Action still reads
     only e-chalupy, and its output must stay byte-identical to the pre-multi-feed
     script. The regression test runs the OLD script (recovered from git) and the new
     one over the same fixture feed and diffs both output files.

  2. MULTI MODE behaves. The filtering, the cross-feed mirror collapse, the uidh
     continuity that keeps /sprava/ linked, and the refusal to rewrite the archive from
     a partially failed fetch.
"""

import json, os, shutil, subprocess, sys, tempfile

HERE     = os.path.dirname(os.path.abspath(__file__))
REPO     = os.path.abspath(os.path.join(HERE, '..', '..'))
SCRIPT   = os.path.join(HERE, 'update_history.py')
OLD_REF  = '012b5df'          # last commit before the four-feed change

FAILURES = []


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (f'  — {detail}' if detail and not cond else ''))
    if not cond:
        FAILURES.append(name)


def vevent(uid, summary, start, end):
    return (f'BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\n'
            f'DTSTART;VALUE=DATE:{start}\r\nDTEND;VALUE=DATE:{end}\r\n'
            f'DTSTAMP:20260813T090000Z\r\nSTATUS:CONFIRMED\r\nEND:VEVENT\r\n')


def calendar(*events):
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n' + ''.join(events) + 'END:VCALENDAR\r\n'


def workdir(history=None):
    """A throwaway repo-shaped dir with data/ in it."""
    d = tempfile.mkdtemp(prefix='vr-test-')
    os.makedirs(os.path.join(d, 'data'))
    with open(os.path.join(d, 'data', 'history.json'), 'w') as f:
        json.dump(history or [], f)
    return d


def run(cwd, *args, script=SCRIPT):
    return subprocess.run([sys.executable, script, *args], cwd=cwd,
                          capture_output=True, text=True)


def read(cwd, name):
    p = os.path.join(cwd, 'data', name)
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        return f.read()


# ── The hub feed as it really looks: own e-chalupy stays, mirrored foreign blocks,
#    and Airbnb's one-day "not available" noise on every free day. ─────────────────
HUB = calendar(
    vevent('abc123@airbnb.com',      'Reserved',                '20261001', '20261005'),
    vevent('xyz789@booking.com',     'CLOSED - Not available',  '20261010', '20261014'),
    vevent('res-4471',               'Reserved - Petra',        '20261020', '20261023'),
    vevent('booking-9931@e-chalupy.cz', 'Rezervace',            '20261101', '20261108'),
    vevent('noise1@airbnb.com',      'Airbnb (Not available)',  '20261201', '20261202'),
)


def test_hub_mode_unchanged():
    print('\nHUB MODE — beze změny proti předchozí verzi')
    old_src = subprocess.run(['git', 'show', f'{OLD_REF}:.github/scripts/update_history.py'],
                             cwd=REPO, capture_output=True, text=True)
    if old_src.returncode != 0:
        check('recover previous script from git', False, old_src.stderr.strip())
        return

    feed_path = os.path.join(tempfile.mkdtemp(prefix='vr-feed-'), 'hub.ics')
    with open(feed_path, 'w', encoding='utf-8') as f:
        f.write(HUB)

    # Point the old script at the fixture via file:// (urlopen speaks it natively).
    old_path = os.path.join(os.path.dirname(feed_path), 'old_update_history.py')
    patched = old_src.stdout.replace(
        "ICAL_URL     = 'https://www.e-chalupy.cz/api/calendar/18852/6C517e26581B794/default.ics'",
        f"ICAL_URL     = 'file://{feed_path}'")
    with open(old_path, 'w', encoding='utf-8') as f:
        f.write(patched)
    check('previous script patched to read the fixture', 'file://' in patched)

    seed = [{'uidh': 'deadbeefdeadbeef', 'start': '2026-05-01', 'end': '2026-05-04',
             'platform': 'Airbnb', 'firstSeen': '2026-05-01', 'lastSeen': '2026-05-01',
             'stale': True}]

    a, b = workdir(seed), workdir(seed)
    ra = run(a, script=old_path)
    # New script in HUB MODE: exactly one feed configured, same fixture.
    env_dir = tempfile.mkdtemp(prefix='vr-fix-')
    shutil.copy(feed_path, os.path.join(env_dir, 'E-chalupy.ics'))
    rb = run(b, '--fixtures', env_dir)

    check('previous script ran', ra.returncode == 0, ra.stderr.strip()[:300])
    check('new script ran', rb.returncode == 0, rb.stderr.strip()[:300])
    check('history.json identical', read(a, 'history.json') == read(b, 'history.json'))
    check('feed.ics identical', read(a, 'feed.ics') == read(b, 'feed.ics'))

    hist = json.loads(read(b, 'history.json') or '[]')
    plats = sorted({e['platform'] for e in hist if not e['stale']})
    check('platforms still derived from UID', plats == ['Airbnb', 'Booking.com', 'E-chalupy', 'Fewo-direkt'], str(plats))
    check('Airbnb noise still filtered', all(e['start'] != '2026-12-01' for e in hist))


def multi_fixtures():
    """Four channel feeds. Each carries its own stays plus mirrors of the others."""
    d = tempfile.mkdtemp(prefix='vr-multi-')
    w = lambda n, c: open(os.path.join(d, n), 'w', encoding='utf-8').write(c)
    w('Airbnb.ics', calendar(
        vevent('air-1@airbnb.com',  'Reserved',               '20261001', '20261005'),
        vevent('xyz789@booking.com','CLOSED - Not available', '20261010', '20261014'),  # mirror
        vevent('blk@airbnb.com',    'Airbnb (Not available)', '20261201', '20261202'),  # noise
    ))
    w('Booking.com.ics', calendar(
        vevent('bk-1@booking.com',  'CLOSED - Not available', '20261010', '20261014'),
        vevent('air-1@airbnb.com',  'Reserved',               '20261001', '20261005'),  # mirror
    ))
    w('Fewo-direkt.ics', calendar(
        vevent('res-4471',          'Reserved - Petra',       '20261020', '20261023'),
    ))
    w('E-chalupy.ics', calendar(
        vevent('ech-1@e-chalupy.cz','Rezervace',              '20261101', '20261108'),
        vevent('res-4471',          'Reserved - Petra',       '20261020', '20261023'),  # mirror
    ))
    return d


def test_multi_mode():
    print('\nMULTI MODE — čtyři feedy, filtr vlastních rezervací')
    d = multi_fixtures()
    cwd = workdir()
    r = run(cwd, '--fixtures', d)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    check('multi mode detected', 'Mode: MULTI' in r.stdout)

    hist = json.loads(read(cwd, 'history.json') or '[]')
    got = sorted((e['start'], e['platform']) for e in hist)
    want = sorted([('2026-10-01', 'Airbnb'), ('2026-10-10', 'Booking.com'),
                   ('2026-10-20', 'Fewo-direkt'), ('2026-11-01', 'E-chalupy')])
    check('every stay kept exactly once, under its own channel', got == want, str(got))
    check('no stay lost', len(hist) == 4, f'{len(hist)} entries')
    check('mirrors filtered, not collapsed after the fact',
          'mirrored from' in r.stdout)
    check('platform comes from the channel, not the UID',
          all(e['platform'] in ('Airbnb', 'Booking.com', 'Fewo-direkt', 'E-chalupy') for e in hist))
    check('no false double booking reported', 'REAL double booking' not in r.stdout, r.stdout[-400:])


def test_real_double_booking_survives():
    print('\nMULTI MODE — skutečná dvojitá rezervace se NESMÍ spolknout')
    d = tempfile.mkdtemp(prefix='vr-dbl-')
    w = lambda n, c: open(os.path.join(d, n), 'w', encoding='utf-8').write(c)
    # Two different channels, genuinely overlapping but NOT the same span.
    w('Airbnb.ics',      calendar(vevent('a1@airbnb.com',  'Reserved',              '20270703', '20270710')))
    w('Booking.com.ics', calendar(vevent('b1@booking.com', 'CLOSED - Not available','20270707', '20270712')))
    cwd = workdir()
    r = run(cwd, '--fixtures', d)
    hist = json.loads(read(cwd, 'history.json') or '[]')
    check('both stays kept', len(hist) == 2, str(hist))
    check('flagged as a REAL double booking', 'REAL double booking' in r.stdout, r.stdout[-400:])


def test_uidh_continuity():
    print('\nUID CONTINUITY — /sprava/ nesmí ztratit vazbu')
    d = tempfile.mkdtemp(prefix='vr-uid-')
    open(os.path.join(d, 'Airbnb.ics'), 'w', encoding='utf-8').write(
        calendar(vevent('air-new-uid@airbnb.com', 'Reserved', '20261001', '20261005')))
    open(os.path.join(d, 'Booking.com.ics'), 'w', encoding='utf-8').write(
        calendar(vevent('bk-1@booking.com', 'CLOSED - Not available', '20261010', '20261014')))
    # The archive holds the SAME stay under the hub's uidh — the key /sprava/ joins on.
    seed = [{'uidh': 'aaaabbbbccccdddd', 'start': '2026-10-01', 'end': '2026-10-05',
             'platform': 'Airbnb', 'firstSeen': '2026-06-01', 'lastSeen': '2026-08-12',
             'stale': False}]
    cwd = workdir(seed)
    r = run(cwd, '--fixtures', d)
    hist = json.loads(read(cwd, 'history.json') or '[]')
    keys = {e['uidh'] for e in hist}
    check('archived uidh preserved', 'aaaabbbbccccdddd' in keys, str(keys))
    check('adoption logged', 'uidh continuity' in r.stdout)
    entry = next((e for e in hist if e['uidh'] == 'aaaabbbbccccdddd'), None)
    check('stay is live, not a ghost', entry is not None and entry['stale'] is False, str(entry))
    check('firstSeen kept from the archive', entry and entry['firstSeen'] == '2026-06-01', str(entry))
    check('no orphan duplicate of the same stay',
          sum(1 for e in hist if e['start'] == '2026-10-01') == 1, str(hist))
    feed = read(cwd, 'feed.ics') or ''
    check('feed.ics uses the same adopted uidh', 'aaaabbbbccccdddd' in feed)


def test_failed_feed_aborts():
    print('\nBEZPEČNOST — rozbitý feed nesmí přepsat archiv')
    d = tempfile.mkdtemp(prefix='vr-bad-')
    open(os.path.join(d, 'Airbnb.ics'), 'w', encoding='utf-8').write(
        calendar(vevent('a1@airbnb.com', 'Reserved', '20261001', '20261005')))
    open(os.path.join(d, 'Booking.com.ics'), 'w', encoding='utf-8').write('<html>login page</html>')
    seed = [{'uidh': 'aaaabbbbccccdddd', 'start': '2026-10-01', 'end': '2026-10-05',
             'platform': 'Airbnb', 'firstSeen': '2026-06-01', 'lastSeen': '2026-08-12',
             'stale': False}]
    cwd = workdir(seed)
    before = read(cwd, 'history.json')
    r = run(cwd, '--fixtures', d)
    check('exits non-zero', r.returncode != 0, str(r.returncode))
    check('archive left untouched', read(cwd, 'history.json') == before)
    check('says why', 'refusing to rewrite' in r.stderr, r.stderr[-300:])


def test_dry_run_writes_nothing():
    print('\n--dry-run')
    d = multi_fixtures()
    cwd = workdir()
    before = read(cwd, 'history.json')
    r = run(cwd, '--fixtures', d, '--dry-run')
    check('ran', r.returncode == 0, r.stderr.strip()[:200])
    check('nothing written', read(cwd, 'history.json') == before)
    check('no feed.ics created', read(cwd, 'feed.ics') is None)
    check('still reports what it would do', 'DRY RUN' in r.stdout)


if __name__ == '__main__':
    test_hub_mode_unchanged()
    test_multi_mode()
    test_real_double_booking_survives()
    test_uidh_continuity()
    test_failed_feed_aborts()
    test_dry_run_writes_nothing()
    print('\n' + ('FAILED: ' + ', '.join(FAILURES) if FAILURES else 'Vše prošlo.'))
    sys.exit(1 if FAILURES else 0)
