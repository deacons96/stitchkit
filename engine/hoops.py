"""Hoops and laying out several copies in one hooping."""
import math

from pystitch import STITCH

from .steps import Result, Step

# stitching areas (mm); the long side runs left to right in the file
HOOPS = [
    dict(key='small', name='120 x 120 mm', w=120, h=120),
    dict(key='medium', name='260 x 200 mm', w=260, h=200),
    dict(key='large', name='360 x 200 mm', w=360, h=200),
]
DEFAULT_MARGIN = 8.0
COPY_SPACING = 10.0


def usable(hoop, margin):
    return hoop['w'] - 2 * margin, hoop['h'] - 2 * margin


def fits(w, h, hoop, margin):
    """None if it doesn't fit, else 'as is' or 'turned' (the machine can turn a design 90 degrees)."""
    uw, uh = usable(hoop, margin)
    if w <= uw + 1e-6 and h <= uh + 1e-6:
        return 'as is'
    if h <= uw + 1e-6 and w <= uh + 1e-6:
        return 'turned'
    return None


def pick(w, h, margin, hoops=None):
    for hp in hoops or HOOPS:
        how = fits(w, h, hp, margin)
        if how:
            return hp, how
    return None, None


def shrink_to_fit(w, h, hoop, margin):
    """Scale factor (<= 1) that makes w x h fit the hoop, turned if that helps."""
    uw, uh = usable(hoop, margin)
    return min(1.0, max(min(uw / w, uh / h), min(uw / h, uh / w)))


def grid(pw, ph, hoop, margin, spacing=COPY_SPACING):
    """(columns, rows, turned) giving the most copies of a pw x ph piece in the hoop."""
    uw, uh = usable(hoop, margin)
    best = (0, 0, False)
    for turned in (False, True):
        w, h = (ph, pw) if turned else (pw, ph)
        cols = int((uw + spacing + 1e-6) // (w + spacing))
        rows = int((uh + spacing + 1e-6) // (h + spacing))
        if cols * rows > best[0] * best[1]:
            best = (cols, rows, turned)
    return best


def capacity(pw, ph, margin):
    return {hp['key']: (lambda g: g[0] * g[1])(grid(pw, ph, hp, margin)) for hp in HOOPS}


def layout_copies(res: Result, n, margin, spacing=COPY_SPACING, user_stops=(), hoops=None):
    """n copies of a piece, sewn colour by colour: step 1 of every copy, then step 2 of every copy...
    Returns (Result, hoop, count actually placed, notes). Stops (built-in and yours) happen once, after
    the last copy of that step."""
    notes = []
    w, h = res.size_mm()
    hp = None
    for cand in hoops or HOOPS:
        c, r, t = grid(w, h, cand, margin, spacing)
        if c * r >= n:
            hp = cand
            break
    if hp is None:
        hp = (hoops or HOOPS)[-1]
        c, r, t = grid(w, h, hp, margin, spacing)
        if c * r == 0:
            return None, None, 0, ['This piece is too big for your largest hoop.']
        notes.append('Only %d copies fit your largest hoop (%s), so the file has %d.' % (c * r, hp['name'], c * r))
        n = c * r
    cols, rows, turned = grid(w, h, hp, margin, spacing)
    piece = res.centred()
    if turned:
        piece = piece.rotate90()
        notes.append('Copies are turned a quarter turn to fit more in the hoop.')
    pw, ph = piece.size_mm()
    # use as few rows as needed, fill row by row
    use_rows = math.ceil(n / cols)
    use_cols = math.ceil(n / use_rows)          # balanced: 4 copies -> 2 x 2, not 3 + 1
    total_w = use_cols * pw + (use_cols - 1) * spacing
    total_h = use_rows * ph + (use_rows - 1) * spacing
    spots = []
    for r_ in range(use_rows):
        row = list(range(use_cols))
        if r_ % 2:
            row.reverse()        # snake from row to row: less travelling between copies
        for c_ in row:
            if len(spots) < n:
                spots.append((-total_w / 2 + pw / 2 + c_ * (pw + spacing), -total_h / 2 + ph / 2 + r_ * (ph + spacing)))
    copies = [piece.translate(x, y) for x, y in spots]
    steps, fabric = [], []
    for i in range(len(piece.steps)):
        for k, cp in enumerate(copies):
            s = cp.steps[i]
            last = k == len(copies) - 1
            steps.append(Step(s.label if len(copies) == 1 else '%s (all copies)' % s.label, s.colour, s.stitches,
                              s.name, (s.stop_after or i in user_stops) if last else False,
                              (i in user_stops) and last))
    for cp in copies:
        fabric += cp.fabric
    from shapely.ops import unary_union
    outline = unary_union([cp.outline for cp in copies if cp.outline is not None]) if piece.outline is not None else None
    out = Result(steps, fabric, list(res.notes), res.kind, outline)
    if len(copies) > 1:
        notes.append('%d copies laid out %d x %d, %g mm apart, sewn colour by colour.' % (len(copies), use_cols, use_rows, spacing))
    return out, hp, len(copies), notes


def basting_step(res: Result, hoop, margin, pad=5.0, stitch_mm=4.0):
    """A running-stitch box round everything, inside the hoop's stitching area, sewn first."""
    x0, y0, x1, y1 = res.bounds_mm()
    uw, uh = (usable(hoop, margin) if hoop else (1e9, 1e9))
    hw, hh = uw / 2 + margin / 2, uh / 2 + margin / 2
    x0, y0 = max(x0 - pad, -hw), max(y0 - pad, -hh)
    x1, y1 = min(x1 + pad, hw), min(y1 + pad, hh)
    pts = []
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for (ax, ay), (bx, by) in zip(corners, corners[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / stitch_mm))
        for i in range(n):
            pts.append([(ax + (bx - ax) * i / n) * 10, (ay + (by - ay) * i / n) * 10, STITCH])
    pts.append([x0 * 10, y0 * 10, STITCH])
    colour = res.steps[0].colour if res.steps else '#000000'
    return Step('Basting box', colour, pts, 'Basting box')
