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

Fixture dates are RELATIVE to today (see BASE): the script runs against the real clock,
so fixed dates would drift out of report_overlaps() and the 18-month prune and start
failing on their own — and a failing test blocks the data update in the workflow.
"""

import contextlib, importlib.util, io, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timedelta

HERE     = os.path.dirname(os.path.abspath(__file__))
REPO     = os.path.abspath(os.path.join(HERE, '..', '..'))
SCRIPT   = os.path.join(HERE, 'update_history.py')
# Last commit before the four-feed change. FULL sha on purpose: a short one can go
# ambiguous as the repo grows, and `git show` would then fail for a reason that has
# nothing to do with the code under test.
OLD_REF  = '012b5df1e12d6f56b60a098bc1d2904c776a4677'

# All fixture stays sit ~2 months ahead of whenever the suite runs: future for
# report_overlaps(), inside the 18-month prune, and "seen today" is never stale.
TODAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
BASE  = TODAY + timedelta(days=60)

FAILURES = []
SKIPPED  = []


def d(n):
    """iCal DATE value n days after BASE."""
    return (BASE + timedelta(days=n)).strftime('%Y%m%d')


def iso(n):
    """history.json date n days after BASE."""
    return (BASE + timedelta(days=n)).strftime('%Y-%m-%d')


def ago(n):
    """history.json date n days before today (for firstSeen / lastSeen seeds)."""
    return (TODAY - timedelta(days=n)).strftime('%Y-%m-%d')


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (f'  — {detail}' if detail and not cond else ''))
    if not cond:
        FAILURES.append(name)


def skip(name, why):
    """Not a failure — the check could not run in THIS environment.

    Only ever for environment-dependent checks (see old_script_source). A skip must
    never hide a real regression in the code, so it is loud in the log and listed in
    the summary — but it does not fail the run.
    """
    print(f'  skip {name}  — {why}')
    SKIPPED.append(name)


def old_script_source():
    """The pre-four-feed version of update_history.py, or None if it is out of reach.

    The Action checks the repo out SHALLOW (depth 1), so OLD_REF is not in the runner's
    object store and `git show` fails with "invalid object name". That is a property of
    the checkout, not a regression — treating it as a test failure took the whole
    workflow down (and with it the data update) from 2026-08-13 on. So: try to fetch the
    one missing commit, and if even that fails, give up and let the caller skip.
    """
    def show():
        return subprocess.run(['git', 'show', f'{OLD_REF}:.github/scripts/update_history.py'],
                              cwd=REPO, capture_output=True, text=True)

    r = show()
    if r.returncode == 0:
        return r.stdout, None

    subprocess.run(['git', 'fetch', '--depth=1', 'origin', OLD_REF],
                   cwd=REPO, capture_output=True, text=True)
    r = show()
    if r.returncode == 0:
        return r.stdout, None
    return None, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'git show failed'


def load_module():
    """Import update_history.py for unit-level checks — without leaving a __pycache__."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('update_history', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def vevent(uid, summary, start, end):
    return (f'BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\n'
            f'DTSTART;VALUE=DATE:{start}\r\nDTEND;VALUE=DATE:{end}\r\n'
            f'DTSTAMP:20260813T090000Z\r\nSTATUS:CONFIRMED\r\nEND:VEVENT\r\n')


def calendar(*events):
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n' + ''.join(events) + 'END:VCALENDAR\r\n'


def workdir(history=None):
    """A throwaway repo-shaped dir with data/ in it."""
    d_ = tempfile.mkdtemp(prefix='vr-test-')
    os.makedirs(os.path.join(d_, 'data'))
    with open(os.path.join(d_, 'data', 'history.json'), 'w') as f:
        json.dump(history or [], f)
    return d_


def run(cwd, *args, script=SCRIPT, env=None):
    return subprocess.run([sys.executable, script, *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


def read(cwd, name):
    p = os.path.join(cwd, 'data', name)
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        return f.read()


# ── The hub feed as it really looks: own e-chalupy stays, mirrored foreign blocks,
#    and Airbnb's one-day "not available" noise on every free day. ─────────────────
HUB = calendar(
    vevent('abc123@airbnb.com',      'Reserved',                d(0),  d(4)),
    vevent('xyz789@booking.com',     'CLOSED - Not available',  d(9),  d(13)),
    vevent('res-4471',               'Reserved - Petra',        d(19), d(22)),
    vevent('booking-9931@e-chalupy.cz', 'Rezervace',            d(31), d(38)),
    vevent('noise1@airbnb.com',      'Airbnb (Not available)',  d(61), d(62)),
)


def test_hub_mode_unchanged():
    print('\nHUB MODE — beze změny proti předchozí verzi')
    old_src, err = old_script_source()
    if old_src is None:
        skip('hub mode vs. previous version', f'{OLD_REF[:7]} not in this checkout ({err})')
        return

    feed_path = os.path.join(tempfile.mkdtemp(prefix='vr-feed-'), 'hub.ics')
    with open(feed_path, 'w', encoding='utf-8') as f:
        f.write(HUB)

    # Point the old script at the fixture via file:// (urlopen speaks it natively).
    # Matched by CONSTANT NAME, not by the old URL literal: that URL carries the feed
    # key and this repo is public, so it must not be pasted back in here just to make
    # a test pass. `count=1` keeps the rewrite to the definition line.
    old_path = os.path.join(os.path.dirname(feed_path), 'old_update_history.py')
    patched = re.sub(r"(?m)^ICAL_URL\s*=\s*.*$",
                     f"ICAL_URL = 'file://{feed_path}'", old_src, count=1)
    with open(old_path, 'w', encoding='utf-8') as f:
        f.write(patched)
    check('previous script patched to read the fixture', 'file://' in patched)

    # An old, finished stay: stale in both versions, still inside the 18-month prune.
    seed = [{'uidh': 'deadbeefdeadbeef', 'start': iso(-153), 'end': iso(-150),
             'platform': 'Airbnb', 'firstSeen': iso(-153), 'lastSeen': iso(-153),
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
    check('Airbnb noise still filtered', all(e['start'] != iso(61) for e in hist))
    # read() opens in text mode, so the file's CRLF arrives as '\n' here.
    check('hub mode keeps writing bare DATE values (byte-identical to the old script)',
          f'DTSTART:{d(0)}\n' in (read(b, 'feed.ics') or ''))


def multi_fixtures():
    """Four channel feeds. Each carries its own stays plus mirrors of the others."""
    d_ = tempfile.mkdtemp(prefix='vr-multi-')
    w = lambda n, c: open(os.path.join(d_, n), 'w', encoding='utf-8').write(c)
    w('Airbnb.ics', calendar(
        vevent('air-1@airbnb.com',  'Reserved',               d(0),  d(4)),
        vevent('xyz789@booking.com','CLOSED - Not available', d(9),  d(13)),  # mirror
        vevent('blk@airbnb.com',    'Airbnb (Not available)', d(61), d(62)),  # noise
    ))
    w('Booking.com.ics', calendar(
        vevent('bk-1@booking.com',  'CLOSED - Not available', d(9),  d(13)),
        vevent('air-1@airbnb.com',  'Reserved',               d(0),  d(4)),   # mirror
    ))
    w('Fewo-direkt.ics', calendar(
        vevent('res-4471',          'Reserved - Petra',       d(19), d(22)),
    ))
    w('E-chalupy.ics', calendar(
        vevent('ech-1@e-chalupy.cz','Rezervace',              d(31), d(38)),
        vevent('res-4471',          'Reserved - Petra',       d(19), d(22)),  # mirror
    ))
    return d_


def test_multi_mode():
    print('\nMULTI MODE — čtyři feedy, filtr vlastních rezervací')
    d_ = multi_fixtures()
    cwd = workdir()
    r = run(cwd, '--fixtures', d_)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    check('multi mode detected', 'Mode: MULTI' in r.stdout)

    hist = json.loads(read(cwd, 'history.json') or '[]')
    got = sorted((e['start'], e['platform']) for e in hist)
    want = sorted([(iso(0), 'Airbnb'), (iso(9), 'Booking.com'),
                   (iso(19), 'Fewo-direkt'), (iso(31), 'E-chalupy')])
    check('every stay kept exactly once, under its own channel', got == want, str(got))
    check('no stay lost', len(hist) == 4, f'{len(hist)} entries')
    check('mirrors filtered, not collapsed after the fact',
          'mirrored from' in r.stdout)
    check('platform comes from the channel, not the UID',
          all(e['platform'] in ('Airbnb', 'Booking.com', 'Fewo-direkt', 'E-chalupy') for e in hist))
    check('no false double booking reported', 'REAL double booking' not in r.stdout, r.stdout[-400:])
    feed = read(cwd, 'feed.ics') or ''
    check('multi mode writes all-day values with ;VALUE=DATE (RFC 5545)',   # text-mode read: CRLF → '\n'
          f'DTSTART;VALUE=DATE:{d(0)}\nDTEND;VALUE=DATE:{d(4)}\n' in feed, feed[:300])


def test_partial_multi_mode():
    print('\nČÁSTEČNÝ MULTI MODE — jen Booking.com + hub: cizí pobyt si nechá platformu z UID')
    d_ = tempfile.mkdtemp(prefix='vr-part-')
    w = lambda n, c: open(os.path.join(d_, n), 'w', encoding='utf-8').write(c)
    w('Booking.com.ics', calendar(
        vevent('bk-1@booking.com',       'CLOSED - Not available', d(9), d(13)),
        vevent('air-mirror@airbnb.com',  'Reserved',               d(0), d(4)),   # Airbnb feed NOT configured
    ))
    w('E-chalupy.ics', HUB)      # the hub exactly as it is today, noise included
    # The archive knows the Airbnb stay under the key /sprava/ joins on.
    seed = [{'uidh': 'aaaaaaaaaaaaaaaa', 'start': iso(0), 'end': iso(4),
             'platform': 'Airbnb', 'firstSeen': ago(40), 'lastSeen': ago(1),
             'stale': False}]
    cwd = workdir(seed)
    r = run(cwd, '--fixtures', d_)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    check('multi mode detected', 'Mode: MULTI' in r.stdout)

    hist = json.loads(read(cwd, 'history.json') or '[]')
    got = sorted((e['start'], e['platform']) for e in hist)
    want = sorted([(iso(0), 'Airbnb'), (iso(9), 'Booking.com'),
                   (iso(19), 'Fewo-direkt'), (iso(31), 'E-chalupy')])
    check('kept foreign stays carry the platform their UID implies (as hub mode would)',
          got == want, str(got))
    check('Airbnb auto-block noise dropped although the Airbnb feed is not configured',
          all(e['start'] != iso(61) for e in hist))
    air = next((e for e in hist if e['start'] == iso(0)), None)
    check('archived uidh (the /sprava/ key) adopted, not replaced',
          air is not None and air['uidh'] == 'aaaaaaaaaaaaaaaa', str(air))
    check('one live Airbnb stay, not one per feed',
          sum(1 for e in hist if e['start'] == iso(0)) == 1, str(hist))
    check('no false double booking', 'REAL double booking' not in r.stdout, r.stdout[-400:])
    check('the KEPT branch was taken and says so', 'KEPT as Airbnb' in r.stdout)
    check('the two copies of the Airbnb stay were collapsed as a mirror, loudly',
          'same nights' in r.stdout and 'Booking.com + E-chalupy' in r.stdout, r.stdout[-600:])


def test_real_double_booking_survives():
    print('\nMULTI MODE — skutečná dvojitá rezervace se NESMÍ spolknout')
    d_ = tempfile.mkdtemp(prefix='vr-dbl-')
    w = lambda n, c: open(os.path.join(d_, n), 'w', encoding='utf-8').write(c)
    # Two different channels, genuinely overlapping but NOT the same span.
    w('Airbnb.ics',      calendar(vevent('a1@airbnb.com',  'Reserved',              d(0), d(7))))
    w('Booking.com.ics', calendar(vevent('b1@booking.com', 'CLOSED - Not available', d(4), d(9))))
    cwd = workdir()
    r = run(cwd, '--fixtures', d_)
    hist = json.loads(read(cwd, 'history.json') or '[]')
    check('both stays kept', len(hist) == 2, str(hist))
    check('flagged as a REAL double booking', 'REAL double booking' in r.stdout, r.stdout[-400:])


def test_same_feed_clash_survives_collapse():
    print('\nMULTI MODE — dva pobyty na stejné noci v JEDNOM feedu přežijí sloučení zrcadla (Codex na #11)')
    d_ = tempfile.mkdtemp(prefix='vr-clash-')
    w = lambda n, c: open(os.path.join(d_, n), 'w', encoding='utf-8').write(c)
    # Airbnb holds TWO bookings on the same span (a real clash); Booking mirrors the span
    # as its own closed block. Before the fix the whole group collapsed to one event.
    w('Airbnb.ics', calendar(
        vevent('a1@airbnb.com', 'Reserved', d(0), d(4)),
        vevent('a2@airbnb.com', 'Reserved', d(0), d(4)),
    ))
    w('Booking.com.ics', calendar(vevent('b-mirror@booking.com', 'CLOSED - Not available', d(0), d(4))))
    cwd = workdir()
    r = run(cwd, '--fixtures', d_)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    hist = json.loads(read(cwd, 'history.json') or '[]')
    air = [e for e in hist if e['platform'] == 'Airbnb']
    check('both Airbnb bookings kept', len(air) == 2, str(hist))
    # Která z těch dvou je zrcadlem té z Bookingu, se poznat nedá — nic se proto nezahodí.
    check('nothing collapsed when one feed holds the same nights twice', len(hist) == 3, str(hist))
    check('and the log says why', 'MORE THAN ONCE in one feed' in r.stdout, r.stdout[-600:])
    check('the same-feed clash is reported as a REAL double booking',
          'REAL double booking' in r.stdout, r.stdout[-600:])


def test_clash_in_non_owner_feed_survives():
    print('\nMULTI MODE — kolize ve feedu, který NENÍ vlastníkem termínu, se taky nesmí ztratit (Codex na #12)')
    d_ = tempfile.mkdtemp(prefix='vr-clash2-')
    w = lambda n, c: open(os.path.join(d_, n), 'w', encoding='utf-8').write(c)
    # Airbnb feed: jeden vlastní pobyt. Booking feed: DVA vlastní na stejných nocích.
    # Dřív rozhodlo pořadí čtení — vyhrál Airbnb a obě rezervace z Bookingu zmizely.
    w('Airbnb.ics', calendar(vevent('a1@airbnb.com', 'Reserved', d(0), d(4))))
    w('Booking.com.ics', calendar(
        vevent('b1@booking.com', 'CLOSED - Not available', d(0), d(4)),
        vevent('b2@booking.com', 'CLOSED - Not available', d(0), d(4)),
    ))
    cwd = workdir()
    r = run(cwd, '--fixtures', d_)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    hist = json.loads(read(cwd, 'history.json') or '[]')
    check('both Booking bookings kept',
          sum(1 for e in hist if e['platform'] == 'Booking.com') == 2, str(hist))
    check('and the Airbnb stay too', any(e['platform'] == 'Airbnb' for e in hist), str(hist))
    check('nothing was collapsed', 'treated the rest as a mirror' not in r.stdout, r.stdout[-600:])
    check('a double booking is reported', 'REAL double booking' in r.stdout, r.stdout[-600:])


def test_uidh_continuity():
    print('\nUID CONTINUITY — /sprava/ nesmí ztratit vazbu')
    d_ = tempfile.mkdtemp(prefix='vr-uid-')
    open(os.path.join(d_, 'Airbnb.ics'), 'w', encoding='utf-8').write(
        calendar(vevent('air-new-uid@airbnb.com', 'Reserved', d(0), d(4))))
    open(os.path.join(d_, 'Booking.com.ics'), 'w', encoding='utf-8').write(
        calendar(vevent('bk-1@booking.com', 'CLOSED - Not available', d(9), d(13))))
    # The archive holds the SAME stay under the hub's uidh — the key /sprava/ joins on.
    # It was live in the previous run (lastSeen yesterday), as it is during the switch.
    seed = [{'uidh': 'aaaabbbbccccdddd', 'start': iso(0), 'end': iso(4),
             'platform': 'Airbnb', 'firstSeen': ago(120), 'lastSeen': ago(1),
             'stale': False}]
    cwd = workdir(seed)
    r = run(cwd, '--fixtures', d_)
    hist = json.loads(read(cwd, 'history.json') or '[]')
    keys = {e['uidh'] for e in hist}
    check('archived uidh preserved', 'aaaabbbbccccdddd' in keys, str(keys))
    check('adoption logged', 'uidh continuity' in r.stdout)
    entry = next((e for e in hist if e['uidh'] == 'aaaabbbbccccdddd'), None)
    check('stay is live, not a ghost', entry is not None and entry['stale'] is False, str(entry))
    check('firstSeen kept from the archive', entry and entry['firstSeen'] == ago(120), str(entry))
    check('no orphan duplicate of the same stay',
          sum(1 for e in hist if e['start'] == iso(0)) == 1, str(hist))
    feed = read(cwd, 'feed.ics') or ''
    check('feed.ics uses the same adopted uidh', 'aaaabbbbccccdddd' in feed)


def test_stale_archive_never_adopted():
    print('\nUID CONTINUITY — mrtvý (stale) záznam se nepřevezme: nový host nesmí zdědit vazbu starého')
    d_ = tempfile.mkdtemp(prefix='vr-stale-')
    # Hub mode on purpose: adoption runs in every mode, so must this rule.
    open(os.path.join(d_, 'E-chalupy.ics'), 'w', encoding='utf-8').write(
        calendar(vevent('NEWGUEST-777@airbnb.com', 'Reserved', d(0), d(4))))
    # A cancelled stay on the very same nights: dropped out of the feed a month ago.
    seed = [{'uidh': '0ldgue5t0ldgue5t', 'start': iso(0), 'end': iso(4),
             'platform': 'Airbnb', 'firstSeen': ago(90), 'lastSeen': ago(30),
             'stale': True}]
    cwd = workdir(seed)
    r = run(cwd, '--fixtures', d_)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    hist = json.loads(read(cwd, 'history.json') or '[]')
    live = [e for e in hist if not e['stale']]
    check('the new stay got a key of its own',
          len(live) == 1 and live[0]['uidh'] != '0ldgue5t0ldgue5t', str(hist))
    check('the cancelled stay stays in the archive, stale, untouched',
          any(e['uidh'] == '0ldgue5t0ldgue5t' and e['stale'] and e['lastSeen'] == ago(30) for e in hist), str(hist))
    check('not logged as an adoption', 'kept archived key' not in r.stdout, r.stdout[-400:])
    check('refusal reported so the owner can re-link by hand', 'STALE archived 0ldgue5t0ldgue5t' in r.stdout,
          r.stdout[-400:])

    uh = load_module()
    # Adopt at most once: two new stays for one archived key → the second gets its own.
    hist_map = {'aaaabbbbccccdddd': {'uidh': 'aaaabbbbccccdddd', 'start': iso(0), 'end': iso(4),
                                     'platform': 'Airbnb', 'firstSeen': ago(9), 'lastSeen': ago(1)}}
    ev = [{'uidh': 'new1', 'start': iso(0), 'end': iso(4), 'platform': 'Airbnb'},
          {'uidh': 'new2', 'start': iso(0), 'end': iso(4), 'platform': 'Airbnb'}]
    adopted, refused = uh.adopt_existing_uidh(ev, hist_map, TODAY)
    check('one archived key is adopted at most once per run',
          [e['uidh'] for e in ev] == ['aaaabbbbccccdddd', 'new2'] and len(adopted) == 1 and not refused,
          str((ev, adopted, refused)))


def test_failed_feed_aborts():
    print('\nBEZPEČNOST — rozbitý feed nesmí přepsat archiv')
    d_ = tempfile.mkdtemp(prefix='vr-bad-')
    open(os.path.join(d_, 'Airbnb.ics'), 'w', encoding='utf-8').write(
        calendar(vevent('a1@airbnb.com', 'Reserved', d(0), d(4))))
    open(os.path.join(d_, 'Booking.com.ics'), 'w', encoding='utf-8').write('<html>login page</html>')
    seed = [{'uidh': 'aaaabbbbccccdddd', 'start': iso(0), 'end': iso(4),
             'platform': 'Airbnb', 'firstSeen': ago(120), 'lastSeen': ago(1),
             'stale': False}]
    cwd = workdir(seed)
    before = read(cwd, 'history.json')
    r = run(cwd, '--fixtures', d_)
    check('exits non-zero', r.returncode != 0, str(r.returncode))
    check('archive left untouched', read(cwd, 'history.json') == before)
    check('says why', 'refusing to rewrite' in r.stderr, r.stderr[-300:])


def test_missing_hub_feed_aborts():
    print('\nBEZPEČNOST — chybějící e-chalupy feed nesmí přepsat archiv z části světa')
    # Regression: once LEGACY_HUB_URL was deleted, ICAL_URL_ECHALUPY could be unset while
    # another secret was set. resolve_feeds() then returned a nonempty list, the emptiness
    # check in main() did not fire, and the archive was rewritten from that partial view —
    # every hub-owned stay stopped being refreshed and aged into `stale` in two days.
    seed = [{'uidh': 'aaaabbbbccccdddd', 'start': iso(40), 'end': iso(47),
             'platform': 'E-chalupy', 'firstSeen': ago(120), 'lastSeen': ago(1),
             'stale': False}]
    env = {k: v for k, v in os.environ.items() if not k.startswith('ICAL_URL_')}
    env['ICAL_URL_AIRBNB'] = 'https://www.example.invalid/airbnb.ics'   # never fetched
    cwd = workdir(seed)
    before = read(cwd, 'history.json')
    r = run(cwd, env=env)
    check('exits non-zero', r.returncode != 0, str(r.returncode))
    check('archive left untouched', read(cwd, 'history.json') == before)
    check('no feed.ics written', read(cwd, 'feed.ics') is None)
    check('names the missing feed', 'E-chalupy' in r.stderr and 'ICAL_URL_ECHALUPY' in r.stderr,
          r.stderr[-300:])
    check('says why', 'refusing to rewrite' in r.stderr, r.stderr[-300:])
    # The discriminating assertion. Without the guard the run gets as far as printing
    # its mode and then rewrites the archive; above, `archive left untouched` would
    # only have held because example.invalid happens not to resolve.
    check('never reached the feed', 'Mode:' not in r.stdout, r.stdout[-300:])

    # Unit level, so the rule is pinned independently of how a run happens to fail.
    uh = load_module()
    keep = {k: os.environ.get(k) for k in ('ICAL_URL_ECHALUPY',)}
    try:
        os.environ.pop('ICAL_URL_ECHALUPY', None)
        names = lambda: [f['channel'] for f in uh.missing_required_feeds()]
        check('unset hub secret is reported missing', names() == ['E-chalupy'], str(names()))
        check('--fixtures is exempt: it exists to run channel subsets offline',
              uh.missing_required_feeds('/tmp/whatever') == [])
        os.environ['ICAL_URL_ECHALUPY'] = 'https://www.example.invalid/hub.ics'
        check('set hub secret leaves nothing missing', names() == [])
        os.environ['ICAL_URL_ECHALUPY'] = '   '
        check('whitespace-only secret still counts as missing', names() == ['E-chalupy'])
    finally:
        for k, v in keep.items():
            if v is None: os.environ.pop(k, None)
            else:         os.environ[k] = v


def test_fetch_error_never_leaks_url():
    print('\nBEZPEČNOST — chyba stahování nesmí do (veřejného) logu vypsat URL feedu')
    key = 'SECRETKEY6C517e26'
    cases = (
        # A secret pasted without the scheme: urllib's ValueError quotes the whole URL.
        ('no scheme',         f'www.example.invalid/api/calendar/18852/{key}/default.ics'),
        # A stray space inside: http.client.InvalidURL quotes the path, key included.
        ('control character', f'https://www.example.invalid/api/calendar/18852/{key} x/default.ics'),
    )
    for label, url in cases:
        env = {k: v for k, v in os.environ.items() if not k.startswith('ICAL_URL_')}
        env['ICAL_URL_ECHALUPY'] = url           # hub mode, one broken feed
        cwd = workdir()
        r = run(cwd, '--dry-run', env=env)
        out = r.stdout + r.stderr
        check(f'{label}: exits non-zero', r.returncode != 0, str(r.returncode))
        check(f'{label}: neither the key nor the host reaches the log',
              key not in out and 'example.invalid' not in out, out[-400:])
        check(f'{label}: no traceback', 'Traceback' not in out, out[-400:])
        check(f'{label}: the failure is still named',
              '::error::E-chalupy: fetch failed' in r.stderr and 'refusing to rewrite' in r.stderr,
              r.stderr[-400:])


def test_parser_edges():
    print('\nPARSER — okraje RFC 5545 (DTEND chybí, UTC čas, VALUE=DATE)')
    uh = load_module()

    def one(body):
        text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + body + 'END:VCALENDAR\r\n'
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            ev = uh.parse_ics(text)
        return ev, log.getvalue()

    ev, _ = one(f'BEGIN:VEVENT\r\nUID:x1@airbnb.com\r\nSUMMARY:Reserved\r\n'
                f'DTSTART;VALUE=DATE:{d(0)}\r\nDURATION:P4D\r\nEND:VEVENT\r\n')
    check('no DTEND + DURATION:P4D → end = start + 4 days',
          len(ev) == 1 and ev[0]['end'] == iso(4) and ev[0]['dtend'] == d(4), str(ev))

    ev, _ = one(f'BEGIN:VEVENT\r\nUID:x2@airbnb.com\r\nSUMMARY:Reserved\r\n'
                f'DTSTART;VALUE=DATE:{d(0)}\r\nDURATION:P1W2D\r\nEND:VEVENT\r\n')
    check('DURATION:P1W2D → 9 days', len(ev) == 1 and ev[0]['end'] == iso(9), str(ev))

    ev, _ = one(f'BEGIN:VEVENT\r\nUID:x3@airbnb.com\r\nSUMMARY:Reserved\r\n'
                f'DTSTART;VALUE=DATE:{d(0)}\r\nEND:VEVENT\r\n')
    check('no DTEND, DATE-only start → one day', len(ev) == 1 and ev[0]['end'] == iso(1), str(ev))

    ev, log = one(f'BEGIN:VEVENT\r\nUID:x4@airbnb.com\r\nSUMMARY:Reserved\r\n'
                  f'DTSTART:{d(0)}T140000\r\nEND:VEVENT\r\n')
    check('no DTEND, DATE-TIME start → skipped (zero length) and logged without the UID',
          ev == [] and 'skipped VEVENT' in log and 'x4@airbnb.com' not in log, log)

    ev, _ = one(f'BEGIN:VEVENT\r\nUID:x5@airbnb.com\r\nSUMMARY:Reserved\r\n'
                f'DTSTART:{d(0)}T140000\r\nDURATION:P3D\r\nEND:VEVENT\r\n')
    check('DATE-TIME start + DURATION keeps the time of day on the implied DTEND',
          len(ev) == 1 and ev[0]['dtend'] == d(3) + 'T140000' and ev[0]['end'] == iso(3), str(ev))

    if uh.LOCAL_TZ is None:
        skip('UTC → Europe/Prague', 'no tz database on this machine')
    else:
        check('22:00Z in summer = Prague midnight next day',
              uh.ics_to_date('20261001T220000Z') == datetime(2026, 10, 2))
        check('23:00Z in winter = Prague midnight next day',
              uh.ics_to_date('20261201T230000Z') == datetime(2026, 12, 2))
        check('20:00Z in summer stays the same day',
              uh.ics_to_date('20261001T200000Z') == datetime(2026, 10, 1))
    check('floating DATE-TIME (the hub) still cut to its own date',
          uh.ics_to_date('20260911T140000') == datetime(2026, 9, 11))
    check('DATE still parsed as written', uh.ics_to_date('20261001') == datetime(2026, 10, 1))

    ev, _ = one(vevent('x6@airbnb.com', 'Reserved', d(0), d(4)))
    for e in ev:
        e['platform'] = 'Airbnb'
    hub_feed   = uh.build_feed(ev)
    multi_feed = uh.build_feed(ev, rfc_dates=True)
    check('build_feed default (hub mode) writes DATE values bare, as always',
          f'DTSTART:{d(0)}\r\nDTEND:{d(4)}\r\n' in hub_feed, hub_feed)
    check('build_feed with rfc_dates writes ;VALUE=DATE for all-day values',
          f'DTSTART;VALUE=DATE:{d(0)}\r\nDTEND;VALUE=DATE:{d(4)}\r\n' in multi_feed, multi_feed)
    ev[0]['dtstart'], ev[0]['dtend'] = d(0) + 'T140000', d(4) + 'T100000'
    check('build_feed with rfc_dates leaves DATE-TIME values alone',
          f'DTSTART:{d(0)}T140000\r\nDTEND:{d(4)}T100000\r\n' in uh.build_feed(ev, rfc_dates=True))

    # Codex na #11: DURATION se počítá celé, i s časovou částí
    ev, _ = one(f'BEGIN:VEVENT\r\nUID:x7@airbnb.com\r\nSUMMARY:Reserved\r\n'
                f'DTSTART:{d(0)}T100000\r\nDURATION:P1DT12H\r\nEND:VEVENT\r\n')
    check('DATE-TIME start + DURATION:P1DT12H → 36 h later, not one day',
          len(ev) == 1 and ev[0]['dtend'] == d(1) + 'T220000', str(ev))
    ev, log = one(f'BEGIN:VEVENT\r\nUID:x8@airbnb.com\r\nSUMMARY:Reserved\r\n'
                  f'DTSTART;VALUE=DATE:{d(0)}\r\nDURATION:P1DT12H\r\nEND:VEVENT\r\n')
    check('DATE start + DURATION with a time part is invalid (RFC 5545 §3.8.2.5) → skipped, logged',
          ev == [] and 'skipped VEVENT' in log, log)

    # Codex na #11: hodnota v UTC se publikuje jako pražské DATE, ať feed.ics a history.json
    # jmenují stejný den (klient by jinak ořízl čas a vrátil pobyt o den zpět)
    if uh.LOCAL_TZ is None:
        skip('UTC value published as the Prague date', 'no tz database on this machine')
    else:
        ev, _ = one('BEGIN:VEVENT\r\nUID:x9@airbnb.com\r\nSUMMARY:Reserved\r\n'
                    'DTSTART:20261001T220000Z\r\nDTEND:20261004T220000Z\r\nEND:VEVENT\r\n')
        check('history date and published DTSTART agree on the Prague day',
              len(ev) == 1 and ev[0]['start'] == '2026-10-02' and ev[0]['dtstart'] == '20261002'
              and ev[0]['end'] == '2026-10-05' and ev[0]['dtend'] == '20261005', str(ev))
        ev[0]['platform'] = 'Airbnb'
        check('build_feed (multi) writes the converted day as ;VALUE=DATE',
              'DTSTART;VALUE=DATE:20261002\r\nDTEND;VALUE=DATE:20261005\r\n' in uh.build_feed(ev, rfc_dates=True))
        check('floating DATE-TIME is still published as written',
              uh.published_value('20260911T140000', datetime(2026, 9, 11)) == '20260911T140000')


def test_cli():
    print('\nCLI — argumenty')
    cwd = workdir()
    r = run(cwd, '--fixtures')
    check('--fixtures without a directory: clean usage error, no traceback',
          r.returncode == 2 and 'Traceback' not in r.stderr and 'usage' in r.stderr, r.stderr[-300:])
    r = run(cwd, '--help')
    check('--help works', r.returncode == 0 and '--dry-run' in r.stdout and '--fixtures' in r.stdout)
def test_direct_sales():
    """Přímý prodej ze Supabase — to, co v žádném feedu není.

    Tady se hlídají obě strany: že se předrezervace do veřejného archivu opravdu
    dostane (jinak ji web pořád nabízí jako volnou), a že se NEdostane tam, kde už
    ten termín drží blok z platformy (jinak by z jednoho pobytu byla červená dvojitá
    rezervace)."""
    print('\nPŘÍMÝ PRODEJ — předrezervace a přímé rezervace ze Supabase')
    d = tempfile.mkdtemp(prefix='vr-direct-')
    open(os.path.join(d, 'E-chalupy.ics'), 'w', encoding='utf-8').write(calendar(
        vevent('booking-1@e-chalupy.cz', 'Rezervace', '20270701', '20270708'),
        # tenhle blok si majitel udělal sám kvůli přímé rezervaci níž
        vevent('booking-2@e-chalupy.cz', 'Rezervace', '20270814', '20270821'),
    ))
    json.dump([
        {'uidh': '1111111111111111', 'start': '2027-08-14', 'end': '2027-08-21',
         'kind': 'direct', 'holdUntil': None},
        {'uidh': '2222222222222222', 'start': '2027-09-04', 'end': '2027-09-11',
         'kind': 'hold', 'holdUntil': '2026-10-01'},
        {'uidh': 'nonsense', 'start': '2027-09-04', 'end': '2027-09-11',
         'kind': 'hold', 'holdUntil': None},
    ], open(os.path.join(d, 'holds.json'), 'w'))

    cwd = workdir()
    r = run(cwd, '--fixtures', d)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    hist = json.loads(read(cwd, 'history.json'))
    by = {e['uidh']: e for e in hist}

    check('předrezervace je v archivu', '2222222222222222' in by)
    hold = by.get('2222222222222222', {})
    check('platforma je Přímá', hold.get('platform') == 'Přímá', str(hold.get('platform')))
    check('nese kind=hold', hold.get('kind') == 'hold', str(hold.get('kind')))
    check('nese holdUntil', hold.get('holdUntil') == '2026-10-01', str(hold.get('holdUntil')))
    check('není duch', hold.get('stale') is False, str(hold.get('stale')))

    check('termín krytý blokem z platformy se nepublikuje', '1111111111111111' not in by)
    check('a je to vidět v logu', 'already blocked on a platform' in r.stdout)
    check('rozbitý uidh neprojde', 'malformed uidh' in r.stdout)

    check('do feed.ics se přímý prodej nepíše', '2222222222222222' not in (read(cwd, 'feed.ics') or ''))
    check('žádná falešná dvojitá rezervace', 'REAL double booking' not in r.stdout, r.stdout[-400:])


def test_direct_sales_source_unavailable():
    """Výpadek databáze nesmí uvolnit držené termíny."""
    print('\nPŘÍMÝ PRODEJ — nedostupný zdroj drží archiv beze změny')
    d = tempfile.mkdtemp(prefix='vr-direct-none-')
    open(os.path.join(d, 'E-chalupy.ics'), 'w', encoding='utf-8').write(calendar(
        vevent('booking-1@e-chalupy.cz', 'Rezervace', '20270701', '20270708')))
    # ŽÁDNÝ holds.json → zdroj se v tomhle běhu nepřečetl
    seed = [{'uidh': '2222222222222222', 'start': '2027-09-04', 'end': '2027-09-11',
             'platform': 'Přímá', 'kind': 'hold', 'holdUntil': '2026-10-01',
             'firstSeen': '2026-09-01', 'lastSeen': '2026-09-01', 'stale': False}]
    cwd = workdir(seed)
    r = run(cwd, '--fixtures', d)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    by = {e['uidh']: e for e in json.loads(read(cwd, 'history.json'))}
    kept = by.get('2222222222222222', {})
    check('předrezervace zůstala', bool(kept))
    check('pořád drží termín (není duch)', kept.get('stale') is False, str(kept.get('stale')))
    check('kind i holdUntil přežily', kept.get('kind') == 'hold' and kept.get('holdUntil') == '2026-10-01', str(kept))
    check('firstSeen se nepřepsal', kept.get('firstSeen') == '2026-09-01', str(kept.get('firstSeen')))
    check('log to říká', 'left untouched' in r.stdout)


def test_direct_sales_expiry_frees_the_term():
    """Propadlá předrezervace mizí sama — databáze ji přestane vracet, nic víc."""
    print('\nPŘÍMÝ PRODEJ — propadlý hold uvolní termín')
    d = tempfile.mkdtemp(prefix='vr-direct-gone-')
    open(os.path.join(d, 'E-chalupy.ics'), 'w', encoding='utf-8').write(calendar(
        vevent('booking-1@e-chalupy.cz', 'Rezervace', '20270701', '20270708')))
    json.dump([], open(os.path.join(d, 'holds.json'), 'w'))
    seed = [{'uidh': '2222222222222222', 'start': '2027-09-04', 'end': '2027-09-11',
             'platform': 'Přímá', 'kind': 'hold', 'holdUntil': '2026-10-01',
             'firstSeen': '2026-09-01', 'lastSeen': '2026-09-01', 'stale': False}]
    cwd = workdir(seed)
    r = run(cwd, '--fixtures', d)
    check('ran', r.returncode == 0, r.stderr.strip()[:300])
    by = {e['uidh']: e for e in json.loads(read(cwd, 'history.json'))}
    check('termín je zase volný', '2222222222222222' not in by)
    check('a nezůstal po něm duch', all(e.get('platform') != 'Přímá' for e in by.values()))


def test_dry_run_writes_nothing():
    print('\n--dry-run')
    d_ = multi_fixtures()
    cwd = workdir()
    before = read(cwd, 'history.json')
    r = run(cwd, '--fixtures', d_, '--dry-run')
    check('ran', r.returncode == 0, r.stderr.strip()[:200])
    check('nothing written', read(cwd, 'history.json') == before)
    check('no feed.ics created', read(cwd, 'feed.ics') is None)
    check('still reports what it would do', 'DRY RUN' in r.stdout)


if __name__ == '__main__':
    test_hub_mode_unchanged()
    test_multi_mode()
    test_partial_multi_mode()
    test_real_double_booking_survives()
    test_same_feed_clash_survives_collapse()
    test_clash_in_non_owner_feed_survives()
    test_uidh_continuity()
    test_stale_archive_never_adopted()
    test_failed_feed_aborts()
    test_missing_hub_feed_aborts()
    test_fetch_error_never_leaks_url()
    test_parser_edges()
    test_cli()
    test_direct_sales()
    test_direct_sales_source_unavailable()
    test_direct_sales_expiry_frees_the_term()
    test_dry_run_writes_nothing()
    if SKIPPED:
        print('\nPŘESKOČENO (neselhalo, jen se v tomhle prostředí nedalo spustit): '
              + ', '.join(SKIPPED))
    print('\n' + ('FAILED: ' + ', '.join(FAILURES) if FAILURES else 'Vše prošlo.'))
    sys.exit(1 if FAILURES else 0)
