"""Everything StitchKit makes is a list of labelled stitch *steps* (placement line, tackdown, background,
design colour 1, border ...). Keeping the steps apart until the very end is what lets us add stops,
lay out several copies colour by colour, add a basting box and print a thread sheet.

Coordinates are in tenths of a millimetre (machine units), y pointing down.
"""
import math
import pickle
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pystitch
from pystitch import STITCH, JUMP, TRIM, COLOR_CHANGE, STOP, END
from shapely import affinity

STOP_PREFIX = 'Stop: '


@dataclass
class Step:
    label: str
    colour: str                      # '#rrggbb'
    stitches: list                   # [[x, y, cmd]] cmd is STITCH, JUMP or TRIM
    name: str = ''                   # thread name shown on the machine, when it should say something special
    stop_after: bool = False         # machine pauses after this step (lay fabric, trim, your own stop)
    user_stop: bool = False          # ...because you asked for it


@dataclass
class Result:
    steps: list
    fabric: list = field(default_factory=list)     # [(polygon in mm, '#rrggbb')] appliqué pieces
    notes: list = field(default_factory=list)
    kind: str = 'design'
    outline: object = None                          # outer cut line of a patch/frame (mm), if any

    def bounds_mm(self):
        xs, ys = [], []
        for s in self.steps:
            for x, y, c in s.stitches:
                if c == STITCH:
                    xs.append(x)
                    ys.append(y)
        for poly, _ in self.fabric:
            b = poly.bounds
            xs += [b[0] * 10, b[2] * 10]
            ys += [b[1] * 10, b[3] * 10]
        return min(xs) / 10, min(ys) / 10, max(xs) / 10, max(ys) / 10

    def size_mm(self):
        x0, y0, x1, y1 = self.bounds_mm()
        return x1 - x0, y1 - y0

    def translate(self, dx_mm, dy_mm):
        dx, dy = dx_mm * 10, dy_mm * 10
        steps = [Step(s.label, s.colour, [[x + dx, y + dy, c] for x, y, c in s.stitches], s.name, s.stop_after) for s in self.steps]
        fab = [(affinity.translate(p, dx_mm, dy_mm), c) for p, c in self.fabric]
        ol = affinity.translate(self.outline, dx_mm, dy_mm) if self.outline is not None else None
        return Result(steps, fab, list(self.notes), self.kind, ol)

    def rotate90(self):
        """Quarter turn clockwise (for fitting a hoop the other way round)."""
        steps = [Step(s.label, s.colour, [[-y, x, c] for x, y, c in s.stitches], s.name, s.stop_after) for s in self.steps]
        m = [0, -1, 1, 0, 0, 0]
        fab = [(affinity.affine_transform(p, m), c) for p, c in self.fabric]
        ol = affinity.affine_transform(self.outline, m) if self.outline is not None else None
        return Result(steps, fab, list(self.notes), self.kind, ol)

    def scaled(self, k):
        steps = [Step(s.label, s.colour, [[x * k, y * k, c] for x, y, c in s.stitches], s.name, s.stop_after) for s in self.steps]
        fab = [(affinity.scale(p, k, k, origin=(0, 0)), c) for p, c in self.fabric]
        ol = affinity.scale(self.outline, k, k, origin=(0, 0)) if self.outline is not None else None
        return Result(steps, fab, list(self.notes), self.kind, ol)

    def centred(self):
        x0, y0, x1, y1 = self.bounds_mm()
        return self.translate(-(x0 + x1) / 2, -(y0 + y1) / 2)

    def save(self, path):
        with open(path, 'wb') as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path):
        with open(path, 'rb') as f:
            return pickle.load(f)


def hexcol(t):
    return '#%02x%02x%02x' % (t.get_red(), t.get_green(), t.get_blue())


def steps_from_pattern(p, label='Design'):
    """Colour blocks of an existing pattern become steps (machine coordinates kept as they are)."""
    out = []
    n = 0
    for stitches, thread in p.get_as_colorblocks():
        st = [[s[0], s[1], s[2] & 0xFF] for s in stitches if s[2] & 0xFF in (STITCH, JUMP, TRIM)]
        if any(c == STITCH for _, _, c in st):
            n += 1
            out.append(Step(label, hexcol(thread), st))
    if len(out) > 1:
        for i, s in enumerate(out):
            s.label = '%s, colour %d' % (label, i + 1)
    return out


# ---------------------------------------------------------------- Ink/Stitch with step markers

def stitch_objects(objs, log, fix_long_mm=None):
    """Stitch plan objects with Ink/Stitch and return steps in the plan's own millimetre frame.

    Ink/Stitch centres its output and merges neighbouring objects of the same colour, so we slip tiny
    marker objects (with colours nobody uses) between groups: the first one pins down the coordinate
    shift, the others mark where one labelled step ends and the next begins."""
    from .build import write_svg, HERE
    from .plan import Obj
    real = [o for o in objs if o.kind in ('fill', 'manual', 'run', 'zigzag', 'satin')]
    if not real:
        return []
    xs, ys = [], []
    for o in real:
        if o.poly is not None:
            b = o.poly.bounds
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        for s in o.seqs:
            if o.kind == 'satin':
                s = [p for sub in s[:2] for p in sub]
            xs += [p[0] for p in s]
            ys += [p[1] for p in s]
        for l in o.lines:
            b = l.bounds
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
    ax, ay = min(xs) - 8, min(ys) - 8
    bx, by = max(xs) + 8, max(ys) + 8

    def marker(i):
        return Obj('manual', '#0102%02x' % (i % 250 + 3), seqs=[[(ax, ay), (bx, by)]], label='__marker__')

    groups = []
    for o in real:
        label = o.label or {'fill': 'Fill', 'manual': 'Satin', 'satin': 'Satin', 'run': 'Running stitch', 'zigzag': 'Zigzag'}[o.kind]
        key = (label, o.name)
        if groups and groups[-1][0] == key and not groups[-1][2]:
            groups[-1][1].append(o)
            groups[-1][2] = o.stop_after
        else:
            groups.append([key, [o], o.stop_after])
    seq, marks = [], set()
    for i, (_key, g, _stop) in enumerate(groups):
        m = marker(i)
        marks.add(m.colour)
        seq.append(m)
        seq += g
    with tempfile.TemporaryDirectory() as tmp:
        svg = Path(tmp) / 'plan.svg'
        write_svg(seq, svg, no_lock_colours=tuple(marks))
        raw = Path(tmp) / 'raw.vp3'
        cmd = [sys.executable, str(HERE / 'run_inkstitch.py'), '--extension=output', '--format=vp3', str(svg)]
        with open(raw, 'wb') as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=1800)
        if r.stderr:
            log.append(r.stderr.decode(errors='replace')[-3000:])
        if raw.stat().st_size < 50:
            raise RuntimeError('The stitch engine did not produce a file.\n' + r.stderr.decode(errors='replace')[-800:])
        p = pystitch.read(str(raw))
    names = {}
    for o in real:
        names.update(o.params.get('_names', {}))
    blocks = []
    for stitches, thread in p.get_as_colorblocks():
        st = [[s[0], s[1], s[2] & 0xFF] for s in stitches if s[2] & 0xFF in (STITCH, JUMP, TRIM)]
        if any(c == STITCH for _, _, c in st):
            blocks.append((hexcol(thread), st))
    if not blocks or blocks[0][0] not in marks:
        raise RuntimeError('Could not line up the stitches with the plan.')
    first = next(s for s in blocks[0][1] if s[2] == STITCH)
    dx, dy = ax * 10 - first[0], ay * 10 - first[1]
    steps, gi = [], -1
    for colour, st in blocks:
        if colour in marks:
            gi += 1
            if steps and gi > 0 and groups[gi - 1][2]:
                steps[-1].stop_after = True
            continue
        (label, name), _, _ = groups[gi]
        st = [[x + dx, y + dy, c] for x, y, c in st]
        steps.append(Step(label, colour, st, name or names.get(colour, '')))
    if steps and groups[-1][2]:
        steps[-1].stop_after = True
    limit = fix_long_mm or _travel_limit(real)
    for s in steps:
        s.stitches = tidy_jumps(fix_long(s.stitches, limit * 10))
    return steps


def tidy_jumps(st, short_mm=1.2):
    """Between two pieces in the same thread: a short hop is simply sewn (no trim needed, it disappears
    under the stitching), a longer one gets a trim so no thread is dragged across the fabric."""
    out = []
    i, n = 0, len(st)
    while i < n:
        s = st[i]
        if s[2] == STITCH or not out:
            out.append(s)
            i += 1
            continue
        j = i
        while j < n and st[j][2] != STITCH:
            j += 1
        if j >= n:
            break
        last = next((p for p in reversed(out) if p[2] == STITCH), None)
        nxt = st[j]
        if last is not None and math.hypot(nxt[0] - last[0], nxt[1] - last[1]) <= short_mm * 10:
            i = j                                   # sew straight on
            continue
        out.append([last[0], last[1], TRIM] if last is not None else [nxt[0], nxt[1], TRIM])
        out.append([nxt[0], nxt[1], JUMP])
        i = j
    return out


def _travel_limit(objs):
    w = 0
    for o in objs:
        if o.kind == 'satin':
            w = max(w, float(o.params.get('_width', 3)) + 1.0)
        if o.kind == 'manual':
            for s in o.seqs:
                tail = s[-200:]
                for a, b in zip(tail[::2], tail[1::2]):
                    w = max(w, math.hypot(b[0] - a[0], b[1] - a[1]))
    return max(8.0, 1.6 * w + 1.5)


def fix_long(st, limit):
    """Ink/Stitch now and then sews a long travel line inside a fill: replace it with tie-off, trim, jump, tie-in."""
    out = []
    for i, s in enumerate(st):
        if i and s[2] == STITCH and st[i - 1][2] == STITCH and math.hypot(s[0] - st[i - 1][0], s[1] - st[i - 1][1]) > limit:
            a, b = st[i - 1], s
            pa = st[i - 2] if i > 1 and st[i - 2][2] == STITCH else a
            nb = st[i + 1] if i + 1 < len(st) and st[i + 1][2] == STITCH else b

            def toward(u, v, d=6):
                L = math.hypot(v[0] - u[0], v[1] - u[1]) or 1
                return [u[0] + (v[0] - u[0]) * min(d, L) / L, u[1] + (v[1] - u[1]) * min(d, L) / L, STITCH]
            out += [toward(a, pa), [a[0], a[1], STITCH], toward(a, pa), [a[0], a[1], STITCH],
                    [a[0], a[1], TRIM], [b[0], b[1], JUMP], [b[0], b[1], STITCH], toward(b, nb),
                    [b[0], b[1], STITCH], toward(b, nb)]
        out.append(s)
    return out


# ---------------------------------------------------------------- putting it together

def assemble(steps, stops=(), thread_names=None):
    """Steps -> one machine pattern.

    Neighbouring steps in the same thread are joined (with a trim) unless a stop is wanted between them
    (step.stop_after, or the step's index in `stops`). A stop between two steps of the same thread is
    written as a thread change to that same thread, which is how a single-needle machine pauses.
    thread_names: {'#rrggbb': 'Poly X40 1234 Red'} for the machine's colour list.
    Returns (pattern, blocks): one entry per colour block for the thread sheet."""
    thread_names = thread_names or {}
    merged = []
    for i, s in enumerate(steps):
        prev = steps[i - 1] if i else None
        stop_before = bool(prev and (prev.stop_after or (i - 1) in stops))
        if merged and merged[-1]['colour'] == s.colour and not stop_before and merged[-1]['name'] == s.name:
            m = merged[-1]
            last = m['st'][-1]
            m['st'].extend([[last[0], last[1], TRIM]] + [list(x) for x in s.stitches])
            if s.label not in m['steps']:
                m['steps'].append(s.label)
        else:
            merged.append(dict(colour=s.colour, name=s.name, steps=[s.label], st=[list(x) for x in s.stitches],
                               stop=bool(stop_before and merged and merged[-1]['colour'] == s.colour),
                               user_stop=bool(prev and (prev.user_stop or (i - 1) in stops))))
    out = pystitch.EmbPattern()
    info = []
    for k, m in enumerate(merged):
        colour, st = m['colour'], m['st']
        th = pystitch.EmbThread(colour)
        thread = thread_names.get(colour, '')
        nm = m['name'] or thread or colour
        if m['user_stop'] and not m['name']:
            nm = STOP_PREFIX + nm
        th.description = _ascii(nm)
        th.catalog_number = ''
        out.add_thread(th)
        if k:
            out.add_stitch_absolute(TRIM, st[0][0], st[0][1])
            out.add_stitch_absolute(COLOR_CHANGE, st[0][0], st[0][1])
        prev = None
        for x, y, c in st:
            if prev is not None and c == STITCH and prev[2] == STITCH and (x - prev[0]) ** 2 + (y - prev[1]) ** 2 > 121 ** 2:
                out.add_stitch_absolute(TRIM, prev[0], prev[1])
                out.add_stitch_absolute(JUMP, x, y)
            out.add_stitch_absolute(c, x, y)
            prev = (x, y, c)
        info.append(dict(colour=colour, name=nm, thread=thread, steps=m['steps'],
                         stitches=sum(1 for s in st if s[2] == STITCH), stop=m['stop'],
                         trims=sum(1 for s in st if s[2] == TRIM)))
    out.add_command(END)
    return out, info


def coverage(steps, res_mm=0.2, threshold=0.4):
    """Area (mm) the stitches really cover.

    Drawn as thread on a fine grid, then averaged over about a millimetre: fills and satins are dense and
    count, a lone travel or underlay line crossing an open space (inside a letter, between letters) is not.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    from shapely.geometry import box as _box
    from shapely.ops import unary_union
    from .art import clean
    pts = [(x / 10.0, y / 10.0) for s in steps for x, y, c in s.stitches if c == STITCH]
    if not pts:
        from shapely.geometry import Polygon
        return Polygon()
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = 2.0
    x0, y0 = min(xs) - pad, min(ys) - pad
    W = int((max(xs) - x0 + pad) / res_mm) + 1
    H = int((max(ys) - y0 + pad) / res_mm) + 1
    img = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(img)
    k = 1.0 / res_mm
    for s in steps:
        run = []
        for x, y, c in s.stitches:
            if c == STITCH:
                run.append(((x / 10.0 - x0) * k, (y / 10.0 - y0) * k))
            else:
                if len(run) > 1:
                    d.line(run, fill=255, width=2)
                run = []
        if len(run) > 1:
            d.line(run, fill=255, width=2)
    blur = img.filter(ImageFilter.BoxBlur(3))
    a = np.asarray(blur) > 255 * threshold
    boxes = []
    for r in range(H):
        row = a[r]
        if not row.any():
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        for c0, c1 in zip(edges[::2], edges[1::2]):
            boxes.append(_box(x0 + c0 * res_mm, y0 + r * res_mm, x0 + c1 * res_mm, y0 + (r + 1) * res_mm))
    g = unary_union(boxes)
    g = g.buffer(0.15, join_style=1).buffer(-0.15, join_style=1).simplify(0.08)
    return clean(g)


def _ascii(s):
    import unicodedata
    return unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()[:60]


def stack(results, gap_mm=3.0, align='center'):
    """Results top to bottom, centred (or aligned) on each other -> one Result."""
    bs = [r.bounds_mm() for r in results]
    width = max(b[2] - b[0] for b in bs)
    y = 0.0
    steps, fab, notes = [], [], []
    for r, (x0, y0, x1, y1) in zip(results, bs):
        w = x1 - x0
        dx = -x0 if align == 'left' else (width - w - x0 if align == 'right' else (width - w) / 2 - x0)
        t = r.translate(dx, y - y0)
        steps += t.steps
        fab += t.fabric
        notes += [n for n in t.notes if n not in notes]
        y += (y1 - y0) + gap_mm
    return Result(steps, fab, notes)


def place(items):
    """items: [(Result, x_mm, y_mm, scale)] where x, y is where the item's centre goes."""
    steps, fab, notes = [], [], []
    for r, x, y, k in items:
        c = r.centred()
        if abs(k - 1) > 1e-6:
            c = c.scaled(k)
        t = c.translate(x, y)
        steps += t.steps
        fab += t.fabric
        notes += [n for n in t.notes if n not in notes]
    return Result(steps, fab, notes)
