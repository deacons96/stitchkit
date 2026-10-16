"""Reading the parts of a stitch file you made or bought: which colour blocks are placement lines,
tackdowns and the finishing satin.

Frame and bag-tag files are usually built the same way:
    placement line   a single running-stitch outline (stop: lay the fabric)
    tackdown         the same outline again, holding the fabric (stop: trim)
    satin            the finishing edge, often with a keyring-hole ring on tags
Some programs put the tackdown and the satin in one colour block with no stop between them; StitchKit
splits those so it can stop for trimming and slip your design in at the right moment.
"""
import math
from dataclasses import replace

from .steps import Step, STITCH, JUMP, TRIM


def _pts(stitches):
    return [(x / 10.0, y / 10.0) for x, y, c in stitches if c == STITCH]


def runs(stitches):
    """Stretches of sewing between jumps/trims: [(start index, end index)] into `stitches`."""
    out, start = [], None
    for i, (x, y, c) in enumerate(stitches):
        if c == STITCH:
            if start is None:
                start = i
        else:
            if start is not None and i - start > 1:
                out.append((start, i))
            start = None
    if start is not None and len(stitches) - start > 1:
        out.append((start, len(stitches)))
    return out


def _reversals(P):
    """1 where the needle turns back on itself (satin, fill), 0 where it carries on (running stitch)."""
    r = []
    for a, b, c in zip(P, P[1:], P[2:]):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        r.append(1 if v1[0] * v2[0] + v1[1] * v2[1] < 0 else 0)
    return r


def _spread(P, res=0.25, width_mm=1.0):
    """Area the path covers drawn 1 mm wide, divided by (length x 1 mm): about 1 for a running stitch that
    never comes back on itself, much less for fill rows or satin packed side by side."""
    from PIL import Image, ImageDraw
    L = sum(math.dist(a, b) for a, b in zip(P, P[1:]))
    if L < 1:
        return 1.0
    xs = [p[0] for p in P]
    ys = [p[1] for p in P]
    x0, y0 = min(xs) - 2, min(ys) - 2
    W, H = int((max(xs) - x0 + 2) / res) + 1, int((max(ys) - y0 + 2) / res) + 1
    if W * H > 9e6:
        return 1.0
    im = Image.new('1', (W, H), 0)
    ImageDraw.Draw(im).line([((x - x0) / res, (y - y0) / res) for x, y in P], fill=1, width=int(width_mm / res))
    import numpy as np
    area = float(np.asarray(im, dtype=np.uint8).sum()) * res * res
    return area / (L * width_mm)


def kind_of(P):
    """'run' or 'dense' (satin or fill) for a stretch of points (mm)."""
    if len(P) < 3:
        return 'run'
    r = _reversals(P)
    if sum(r) / len(r) > 0.45:
        return 'dense'
    # a running stitch sewn there and back covers half as much; fill rows and satin far less
    return 'dense' if _spread(P) < 0.4 else 'run'


def is_loop(P, tol=2.5):
    if len(P) < 10:
        return False
    L = sum(math.dist(a, b) for a, b in zip(P, P[1:]))
    return math.dist(P[0], P[-1]) <= tol and L > 30


def step_kind(step):
    """'outline' (only running-stitch loops), 'run', or 'dense'."""
    kinds, loops = [], 0
    for a, b in runs(step.stitches):
        P = _pts(step.stitches[a:b])
        k = kind_of(P)
        kinds.append(k)
        if k == 'run' and is_loop(P):
            loops += 1
    if not kinds:
        return 'run'
    if all(k == 'run' for k in kinds):
        return 'outline' if loops else 'run'
    return 'dense'


def split_leading_loop(step):
    """A block that starts with a running-stitch loop (the tackdown) and goes straight on into satin.
    Returns (tackdown step, rest) or None."""
    st = step.stitches
    rr = runs(st)
    if not rr:
        return None
    a, b = rr[0]
    P = _pts(st[a:b])
    if len(P) < 30:
        return None
    rev = _reversals(P)
    # where sustained back-and-forth (satin) begins
    w = 20
    start_dense = None
    for i in range(0, len(rev) - w):
        if sum(rev[i:i + w]) / w > 0.6:
            start_dense = i
            break
    if start_dense is None or start_dense < 20:
        return None
    # inside the running part, the first time the needle comes back to where it started
    L = 0.0
    xs = [p[0] for p in P]
    ys = [p[1] for p in P]
    perim = 2 * ((max(xs) - min(xs)) + (max(ys) - min(ys)))
    close = None
    for j in range(1, start_dense + 1):
        L += math.dist(P[j - 1], P[j])
        if L > 0.45 * perim and math.dist(P[j], P[0]) < 2.5:
            close = j
            break
    if close is None:
        return None
    cut = a + close + 1
    tack = replace(step, stitches=[list(s) for s in st[:cut]], label='Tackdown', name='', stop_after=True, hint='Tackdown')
    rest = replace(step, stitches=[[st[cut - 1][0], st[cut - 1][1], JUMP]] + [list(s) for s in st[cut:]])
    return tack, rest


def roles(steps):
    """Label the parts of a frame or tag file.

    Returns (steps, info): steps with tackdowns split off where needed, and
        info['outlines']  indices of the outline passes before the first satin (placement, tack, tackdown)
        info['first_dense'] index of the first satin/fill block (len(steps) if none)
    """
    steps = list(steps)
    kinds = [step_kind(s) for s in steps]
    # tackdown sewn straight into the satin with no stop: split it off
    i = 0
    while i < len(steps):
        if kinds[i] == 'dense' and i > 0 and kinds[i - 1] == 'outline':
            sp = split_leading_loop(steps[i])
            if sp:
                steps[i:i + 1] = list(sp)
                kinds[i:i + 1] = ['outline', 'dense']
                i += 1
        i += 1
    first_dense = next((k for k, kd in enumerate(kinds) if kd == 'dense'), len(steps))
    outlines = [k for k in range(first_dense) if kinds[k] == 'outline']
    return steps, dict(outlines=outlines, first_dense=first_dense, kinds=kinds)


def name_parts(steps, info, tag=False):
    """Give the outline passes the names the machine will show, and stops."""
    out = [replace(s) for s in steps]
    o = info['outlines']
    names = []
    if len(o) == 1:
        names = [('Placement line', 'Placement - lay fabric')]
    elif len(o) == 2:
        names = [('Placement line', 'Placement - lay fabric'), ('Tackdown', 'Tackdown - then trim')]
    elif len(o) >= 3:
        names = [('Placement line', 'Placement - lay fabric'), ('Tack front fabric', 'Tack fabric')] + \
                [('Tackdown', 'Tackdown - then trim')] * (len(o) - 2)
    for k, (lab, nm) in zip(o, names):
        out[k] = replace(out[k], label=lab, name=nm, stop_after=True)
    for k in range(info['first_dense'], len(out)):
        if not out[k].label or out[k].label.startswith('Design'):
            out[k] = replace(out[k], label='Frame satin')
    return out
