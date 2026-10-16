"""Patch shapes: each is a template polygon that gets fitted around the artwork.

'stretch' shapes follow the art's proportions (an oval round a wide logo is wide);
'fixed' shapes keep their own proportions (a circle stays a circle).
Corners are rounded to suit a wide satin border, the way real merrowed patches are.
"""
import math

from shapely.geometry import Polygon, Point, box
from shapely import affinity

from .art import polys, clean


def _reg(n, rot=0.0):
    return Polygon([(math.cos(rot + 2 * math.pi * i / n), math.sin(rot + 2 * math.pi * i / n)) for i in range(n)])


def _rounded_box(r):
    return box(-1, -1, 1, 1).buffer(-r, join_style=1).buffer(r, join_style=1)


def _point_bottom(y0):
    """Right half of a pointed bottom: from (1, y0) curving to the point (0, 1)."""
    pts = []
    for i in range(1, 31):
        t = i / 30
        # quadratic curve, control point straight below the corner: full sides, crisp point
        x = (1 - t) ** 2 * 1 + 2 * (1 - t) * t * 1 + t * t * 0
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * (y0 + (1 - y0) * 0.62) + t * t * 1
        pts.append((x, y))
    return pts


def _shield():
    right = [(1, -1), (1, -0.05)] + _point_bottom(-0.05)
    left = [(-x, y) for x, y in reversed(right[:-1])]
    return Polygon([(-1, -1)] + right + left[:-1])


def _crest():
    top = []
    for i in range(25):
        a = math.pi + math.pi * i / 24
        top.append((math.cos(a), -0.6 + 0.4 * math.sin(a)))
    right = [(1, 0.05)] + _point_bottom(0.05)
    left = [(-x, y) for x, y in reversed(right[:-1])]
    return Polygon(top + right + left)


def _heart():
    """Two round lobes and straight sides down to the point, with a crisp V where the lobes meet."""
    from shapely.ops import unary_union
    c, r = 0.47, 0.53
    lobes = [Point(x, -0.38).buffer(r, quad_segs=48) for x in (-c, c)]
    # sides: tangent from each lobe down to the point
    px, py = 0.0, 1.0
    side = []
    for sx in (-1, 1):
        cx, cy = sx * c, -0.38
        d = math.hypot(px - cx, py - cy)
        a = math.atan2(py - cy, px - cx)
        b = math.acos(r / d)
        t = a - sx * b
        side.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    body = Polygon([(-c, -0.38), side[0], (px, py), side[1], (c, -0.38)])
    return unary_union(lobes + [body])


def _star(n=5, inner=0.5):
    pts = []
    for i in range(2 * n):
        r = 1 if i % 2 == 0 else inner
        a = -math.pi / 2 + math.pi * i / n
        pts.append((r * math.cos(a), r * math.sin(a)))
    return Polygon(pts)


def _scalloped(n=18, depth=0.07):
    pts = []
    for i in range(720):
        a = 2 * math.pi * i / 720
        r = 1 - depth + depth * abs(math.cos(n * a / 2))
        pts.append((r * math.cos(a), r * math.sin(a)))
    return Polygon(pts)


def _tombstone():
    pts = [(-1, 1), (1, 1), (1, -0.2)]
    for i in range(1, 32):
        a = math.pi * i / 32
        pts.append((math.cos(a), -0.2 - 0.8 * math.sin(a)))
    pts.append((-1, -0.2))
    return Polygon(pts)


def _pennant():
    return Polygon([(-1, -1), (1, -1), (0, 1)])


def _tall(t, ratio=0.78):
    return affinity.scale(t, ratio, 1.0, origin=(0, 0))


def _wide(t, ratio=0.78):
    return affinity.scale(t, 1.0, ratio, origin=(0, 0))


def _round_poly(t, r):
    return t.buffer(-r, join_style=1).buffer(r, join_style=1)


SHAPES = {
    # key: (label, template, mode, corner rounding as a fraction of border width)
    'outline':   ('Follow the design', None, 'outline', 0),
    # the classic dozen
    'square':    ('Square', box(-1, -1, 1, 1), 'fixed', 0.6),
    'rounded_square': ('Rounded square', _rounded_box(0.35), 'fixed', 0.9),
    'rectangle': ('Rectangle', box(-1, -1, 1, 1), 'stretch', 0.6),
    'rounded':   ('Rounded rectangle', _rounded_box(0.35), 'stretch', 0.9),
    'oval_tall': ('Tall oval', _tall(Point(0, 0).buffer(1, quad_segs=64)), 'fixed', 0),
    'triangle':  ('Triangle', _reg(3, -math.pi / 2), 'fixed', 0.9),
    'diamond':   ('Diamond', _tall(_reg(4)), 'fixed', 0.7),
    'rounded_diamond': ('Rounded diamond', _round_poly(_tall(_reg(4)), 0.18), 'fixed', 0.9),
    'heart':     ('Heart', _heart(), 'fixed', 0.9),   # V kept sharp: see SHARP_NOTCH
    'shield':    ('Shield', _shield(), 'stretch', 0.9),
    'oval_wide': ('Wide oval', _wide(Point(0, 0).buffer(1, quad_segs=64)), 'fixed', 0),
    'circle':    ('Circle', Point(0, 0).buffer(1, quad_segs=64), 'fixed', 0),
    # more
    'oval':      ('Oval (fits design)', Point(0, 0).buffer(1, quad_segs=64), 'stretch', 0),
    'pill':      ('Pill', None, 'pill', 0),
    'hexagon':   ('Hexagon', _reg(6, math.pi / 6), 'fixed', 0.9),
    'hexagon_flat': ('Hexagon (flat top)', _reg(6), 'fixed', 0.9),
    'octagon':   ('Octagon', _reg(8, math.pi / 8), 'fixed', 0.9),
    'diamond_fit': ('Diamond (fits design)', _reg(4), 'stretch', 0.9),
    'crest':     ('Crest', _crest(), 'stretch', 0.9),
    'arch':      ('Arch top', _tombstone(), 'stretch', 0.9),
    'pennant':   ('Pennant', _pennant(), 'stretch', 0.9),
    'star':      ('Star', _star(), 'fixed', 0.9),
    'scalloped': ('Scalloped circle', _scalloped(), 'fixed', 0),
}


# shapes whose inward notch should stay crisp (no rounding of inside corners)
SHARP_NOTCH = {'heart', 'star'}


def _scaled(t, sx, sy, cx, cy):
    return affinity.translate(affinity.scale(t, sx, sy, origin=(0, 0)), cx, cy)


def fit(kind, art_union, margin, border_mm, extra=None):
    """Smallest version of the shape that holds the art with `margin` mm of clearance all round."""
    kind = kind if kind in SHAPES else 'outline'
    label, tpl, mode, rnd = SHAPES[kind]
    if mode == 'outline':
        r = 4.0
        g = art_union.buffer(margin + r, join_style=1).buffer(-r, join_style=1)
        from shapely.ops import unary_union
        g = unary_union([Polygon(p.exterior) for p in polys(g)])
        if g.geom_type != 'Polygon':
            g = g.convex_hull
        return g.simplify(0.05)
    content = art_union.buffer(margin, join_style=1)
    if mode == 'pill':
        from shapely.geometry import LineString
        minx, miny, maxx, maxy = content.bounds
        w, h = maxx - minx, maxy - miny
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        r = min(w, h) / 2
        if w >= h:
            core = LineString([(minx + r, cy), (maxx - r, cy)])
        else:
            core = LineString([(cx, miny + r), (cx, maxy - r)])
        g = core.buffer(r, quad_segs=48)
        for _ in range(80):
            if g.contains(content):
                break
            r *= 1.02
            g = core.buffer(r, quad_segs=48)
        return g
    min_aspect = {'shield': 1.12, 'crest': 1.08, 'arch': 0.85}.get(kind)
    return fit_poly(tpl, content, mode, rnd * border_mm if rnd else 0, min_aspect, sharp=kind in SHARP_NOTCH)


def fit_poly(tpl, content, mode='fixed', round_mm=0.0, min_aspect=None, sharp=False):
    """Scale (and slide up/down a little) a template polygon until it just holds `content`."""
    minx, miny, maxx, maxy = content.bounds
    w, h = maxx - minx, maxy - miny
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    tb = tpl.bounds
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    if mode == 'stretch':
        sx0, sy0 = w / tw, h / th
        # some shapes only look right taller than wide (a squat shield reads as a bowl)
        if min_aspect and (th * sy0) / (tw * sx0) < min_aspect:
            sy0 = min_aspect * tw * sx0 / th
    else:
        s0 = max(w / tw, h / th)
        sx0 = sy0 = s0
    best = None
    tcx, tcy = (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2
    for off in [0, -0.08, 0.08, -0.16, 0.16, -0.24, 0.24]:
        lo, hi = 0.3, 8.0
        for _ in range(28):
            k = (lo + hi) / 2
            sx, sy = sx0 * k, sy0 * k
            g = _scaled(tpl, sx, sy, cx - tcx * sx, cy - tcy * sy + off * th * sy)
            if g.contains(content):
                hi = k
            else:
                lo = k
        k = hi
        area = k * k
        if best is None or area < best[0] - 1e-9:
            sx, sy = sx0 * k, sy0 * k
            best = (area, _scaled(tpl, sx, sy, cx - tcx * sx, cy - tcy * sy + off * th * sy))
    g = best[1]
    if round_mm:
        r = max(1.5, round_mm)
        g = clean(g.buffer(-r, join_style=1).buffer(r, join_style=1))
        # inside corners: softened so the satin can turn; 'sharp' shapes keep a crisp V
        ri = 0.8 if sharp else r * 0.6
        g = clean(g.buffer(ri, join_style=1).buffer(-ri, join_style=1))
        if not g.contains(content):
            # rounding nibbled the art's clearance: grow a touch
            g = clean(g.buffer(max(0.0, content.difference(g).area ** 0.5 * 0.5) + 0.3, join_style=1))
    return g


def outline_path(g, size=44.0, pad=2.0):
    """SVG path of a shape scaled into a size x size box (for thumbnails)."""
    minx, miny, maxx, maxy = g.bounds
    s = (size - 2 * pad) / max(maxx - minx, maxy - miny)
    ox = (size - (maxx - minx) * s) / 2
    oy = (size - (maxy - miny) * s) / 2
    d = []
    for p in polys(g):
        for ring in [p.exterior] + list(p.interiors):
            c = list(ring.coords)
            d.append('M' + ' L'.join('%.1f,%.1f' % ((x - minx) * s + ox, (y - miny) * s + oy) for x, y in c[:-1]) + ' Z')
    return ' '.join(d)


def catalogue():
    """Patch-shape thumbnails for the app: {key: (label, svg path)} fitted round a 1.3:1 box."""
    out = {}
    art = box(0, 0, 13, 10)
    for k, (label, *_r) in SHAPES.items():
        if k == 'outline':
            continue
        out[k] = (label, outline_path(fit(k, art, 1.0, 2.0)))
    return out
