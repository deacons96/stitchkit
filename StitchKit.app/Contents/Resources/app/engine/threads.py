"""Match design colours to real threads.

Brands come from three places:
  * the thread charts that come with Ink/Stitch (Poly X40, Isacord, Madeira, Sulky, Robison-Anton ...)
  * your own charts in Documents/StitchKit/Threads (one file per brand: .txt, .csv or .gpl)
  * Documents/StitchKit/My threads.txt (kept from 1.1)

A chart line needs a colour (#rrggbb, or red green blue numbers) and usually a number and a name, e.g.
    1001, White, #ffffff        or        1001  White  255 255 255
"""
import json
import math
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PALETTES = HERE.parent / 'inkstitch_engine' / 'palettes'
USER_DIR = Path.home() / 'Documents' / 'StitchKit' / 'Threads'
MY_THREADS = Path.home() / 'Documents' / 'StitchKit' / 'My threads.txt'
STASH_FILE = Path.home() / 'Documents' / 'StitchKit' / 'Thread stash.json'

FAR = 12.0          # colour distance where a stash thread stops looking like the design colour

MY_THREADS_HELP = """# My threads: your own thread list (for Exquisite, or any brand).
# One thread per line:  number, name, #rrggbb
# The colour code is the closest screen colour; match it by eye against your thread or a printed chart.
# Lines starting with # are ignored. Save this file, then make your stitch files again.
#
# Examples (replace with your own):
# 1001, White, #ffffff
# 1147, Wine, #6d1f2c
"""

_cache = {}


def brands():
    """{key: (display name, path)} — your own charts first, then the built-in ones."""
    out = {}
    if USER_DIR.exists():
        for f in sorted(USER_DIR.iterdir()):
            if f.suffix.lower() in ('.txt', '.csv', '.gpl') and not f.name.startswith('.'):
                out['user:' + f.stem] = (f.stem, f)
    if MY_THREADS.exists() and _parse(MY_THREADS):
        out['mine'] = ('My threads', MY_THREADS)
    out['polyx40'] = ('Poly X40', PALETTES / 'InkStitch Poly X40.gpl')
    for f in sorted(PALETTES.glob('*.gpl')):
        name = f.stem.replace('InkStitch ', '')
        key = 'gpl:' + name
        if name != 'Poly X40':
            out[key] = (name, f)
    out['none'] = ('No thread matching', None)
    return out


class _Brands(dict):
    """Old code reads BRANDS[key][0] for the display name."""
    def __getitem__(self, k):
        return brands().get(k, ('', None))

    def get(self, k, d=None):
        return brands().get(k, d)

    def items(self):
        return brands().items()


BRANDS = _Brands()


def ensure_my_threads():
    try:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        if not MY_THREADS.exists():
            MY_THREADS.write_text(MY_THREADS_HELP)
    except OSError:
        pass


def _parse(path):
    path = Path(path)
    text = path.read_text(errors='replace')
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.lower().startswith(('gimp palette', 'name:', 'columns:')):
            continue
        hx = None
        rest = line
        m = re.search(r'#([0-9a-fA-F]{6})\b', line) or re.search(r'(?<![0-9A-Za-z])([0-9a-fA-F]{6})(?![0-9A-Za-z])', line)
        if m and (m.group(0).startswith('#') or re.search('[a-fA-F]', m.group(1))):
            hx = '#' + m.group(1).lower()
            rest = (line[:m.start()] + ' ' + line[m.end():]).strip()
        else:
            m = re.search(r'(?<!\d)(\d{1,3})[\s,;]+(\d{1,3})[\s,;]+(\d{1,3})(?!\d)', line)
            if m and all(int(v) <= 255 for v in m.groups()):
                hx = '#%02x%02x%02x' % tuple(int(v) for v in m.groups())
                rest = (line[:m.start()] + ' ' + line[m.end():]).strip()
        if not hx:
            continue
        fields = [f.strip() for f in re.split(r'[,;\t]|\s{2,}', rest) if f.strip()]
        if len(fields) == 1 and ' ' in fields[0]:
            fields = fields[0].rsplit(None, 1) if path.suffix.lower() == '.gpl' else fields[0].split(None, 1)
        num, name = '', ''
        if path.suffix.lower() == '.gpl' and fields:
            # Ink/Stitch charts: "Name   Number"
            if len(fields) >= 2 and any(ch.isdigit() for ch in fields[-1]):
                num, name = fields[-1], ' '.join(fields[:-1])
            else:
                name = ' '.join(fields)
        else:
            for f in fields:
                if not num and re.fullmatch(r'[A-Za-z]{0,3}[-\s]?\d[\w.-]{0,8}', f):
                    num = f
                else:
                    name = (name + ' ' + f).strip()
        out.append(dict(number=num, name=name, hex=hx))
    return out


def chart(brand):
    b = brands().get(brand)
    if not b or not b[1] or not Path(b[1]).exists():
        return []
    path = Path(b[1])
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache[key] = _parse(path)
    return _cache[key]


def import_chart(name, data_text):
    """Save a chart someone gives us as a brand in Documents/StitchKit/Threads. Returns (key, count)."""
    safe = re.sub(r'[^\w .()-]+', '', name).strip()[:40] or 'My brand'
    USER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USER_DIR / (safe + '.txt')
    tmp.write_text(data_text)
    rows = _parse(tmp)
    if not rows:
        tmp.unlink()
        raise ValueError('No thread colours found. Each line needs a colour code like #6d1f2c or three numbers like 109 31 44.')
    tmp.write_text('# %s thread chart (added to StitchKit)\n# number, name, colour\n' % safe +
                   '\n'.join('%s, %s, %s' % (r['number'], r['name'].replace(',', ' '), r['hex']) for r in rows) + '\n')
    _cache.clear()
    return 'user:' + safe, len(rows)


def _lab(hx):
    r, g, b = [int(hx.lstrip('#')[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _best(L, rows):
    return min(rows, key=lambda t: _dist(L, t))


def match(hx, brand):
    """Closest thread for a design colour.

    With a thread stash, the closest thread you own wins. If it is not close and your brand has a much
    closer thread, that one comes back as 'buy' so it can go on the shopping list."""
    L = _lab(hx)
    own = stash_active()
    if own:
        best = _best(L, own)
        d = _dist(L, best)
        out = dict(number=best['number'], name=best['name'], hex=best['hex'], brand=best['brand_name'],
                   delta=round(d, 1), in_stash=True, low=bool(best.get('low')), far=d > FAR)
        c = chart(brand) if brand != 'none' else []
        if c and d > FAR:
            b = _best(L, c)
            bd = _dist(L, b)
            if bd < d * 0.6:
                out['buy'] = dict(number=b['number'], name=b['name'], hex=b['hex'], brand=brands()[brand][0],
                                  delta=round(bd, 1))
        return out
    c = chart(brand)
    if not c:
        return None
    best = _best(L, c)
    return dict(best, brand=brands()[brand][0], delta=round(_dist(L, best), 1))


def matching_on(brand):
    return brand != 'none' or bool(stash_active())


def _dist(L, t):
    if '_lab' not in t:
        t['_lab'] = _lab(t['hex'])
    a = t['_lab']
    return math.sqrt((L[0] - a[0]) ** 2 + (L[1] - a[1]) ** 2 + (L[2] - a[2]) ** 2)


def short_brand(brand):
    return _short(brands().get(brand, ('',))[0])


def _short(n):
    return {'Poly X40': 'PolyX40'}.get(n, n.split()[0] if n else '')


def names(colours, brand):
    """{'#rrggbb': 'PolyX40 1234 Name'} for the machine's colour list."""
    out = {}
    for c in colours:
        m = match(c, brand)
        if m:
            out[c] = ('%s %s %s' % (_short(m['brand']), m['number'], m['name'])).strip()
    return out


# ---------------------------------------------------------------- thread stash
# Documents/StitchKit/Thread stash.json:
#   {"use": true, "threads": [{"id", "brand", "brand_name", "number", "name", "hex", "low"}]}
# "brand" is the chart key (gpl:Isacord 40, user:Exquisite ...) or "own" for a thread you typed in yourself.

def stash():
    try:
        d = json.loads(STASH_FILE.read_text())
        d.setdefault('use', True)
        d['threads'] = [t for t in d.get('threads', []) if isinstance(t, dict) and re.fullmatch(r'#[0-9a-f]{6}', str(t.get('hex', '')))]
        return d
    except (OSError, ValueError):
        return dict(use=True, threads=[])


def stash_save(d):
    STASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STASH_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(use=bool(d.get('use', True)), threads=d['threads']), indent=1))
    tmp.replace(STASH_FILE)


def stash_active():
    """Threads to match against, or [] when the stash is empty or switched off."""
    d = stash()
    return d['threads'] if d['use'] else []


def _num_key(n):
    n = str(n).strip().lower().replace(' ', '')
    return n.lstrip('0') or '0'


def find(brand, query, limit=40):
    """Search a brand's chart by number or name."""
    q = query.strip().lower()
    c = chart(brand)
    if not q:
        return c[:limit]
    nk = _num_key(q)
    exact = [t for t in c if _num_key(t['number']) == nk]
    starts = [t for t in c if t not in exact and _num_key(t['number']).startswith(nk)]
    named = [t for t in c if t not in exact and t not in starts and q in t['name'].lower()]
    return (exact + starts + named)[:limit]


def _new_id(d):
    return '%x%03x' % (int(time.time() * 1000), len(d['threads']))


def stash_add(brand, numbers):
    """Add threads by number ("2922 1010, 0015"). Returns (added, already, not_found)."""
    c = chart(brand)
    if not c:
        raise ValueError('Choose a thread brand first.')
    by = {}
    for t in c:
        by.setdefault(_num_key(t['number']), t)
    d = stash()
    have = {(t['brand'], _num_key(t['number'])) for t in d['threads']}
    added, already, missing = [], [], []
    for n in re.split(r'[\s,;]+', numbers.strip()):
        if not n:
            continue
        t = by.get(_num_key(n))
        if not t:
            missing.append(n)
        elif (brand, _num_key(t['number'])) in have:
            already.append(t['number'])
        else:
            d['threads'].append(dict(id=_new_id(d), brand=brand, brand_name=brands()[brand][0], number=t['number'],
                                     name=t['name'], hex=t['hex'], low=False))
            have.add((brand, _num_key(t['number'])))
            added.append(t['number'])
    stash_save(d)
    return added, already, missing


def stash_add_own(brand_name, number, name, hx):
    """A thread that is not on any chart: you give its colour."""
    hx = (hx or '').strip().lower()
    if not re.fullmatch(r'#[0-9a-f]{6}', hx):
        raise ValueError('Pick the colour that looks closest to the thread.')
    d = stash()
    d['threads'].append(dict(id=_new_id(d), brand='own', brand_name=(brand_name or 'My thread').strip()[:40],
                             number=(number or '').strip()[:20], name=(name or '').strip()[:60], hex=hx, low=False))
    stash_save(d)


def stash_update(tid, **changes):
    d = stash()
    if changes.get('remove'):
        d['threads'] = [t for t in d['threads'] if t['id'] != tid]
    else:
        for t in d['threads']:
            if t['id'] == tid and 'low' in changes:
                t['low'] = bool(changes['low'])
    stash_save(d)


def stash_use(on):
    d = stash()
    d['use'] = bool(on)
    stash_save(d)


def shopping(colours, brand):
    """Threads to buy for these design colours: better matches you don't own, and stash threads running low."""
    out, seen = [], set()
    for c in colours:
        m = match(c, brand)
        if not m:
            continue
        if m.get('buy'):
            b = m['buy']
            k = ('buy', b['brand'], b['number'])
            if k not in seen:
                seen.add(k)
                out.append(dict(b, why='closer than anything in your stash'))
        elif m.get('in_stash') and m.get('low'):
            k = ('low', m['brand'], m['number'])
            if k not in seen:
                seen.add(k)
                out.append(dict(number=m['number'], name=m['name'], hex=m['hex'], brand=m['brand'], why='running low'))
    return out
