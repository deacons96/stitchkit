"""Decorative frames.

Two kinds:
  ring frames   an outline shape; the frame is the band between it and a parallel inner outline
                (any patch shape can be used this way too)
  piece frames  made of separate pieces (Greek key bars, bamboo poles), each outlined in satin, with
                their own area for the design

All templates are drawn in "unit" coordinates (longest side about 2, centred on 0, y down).
Your own frames: SVG files in Documents/StitchKit/Frames (outer outline, optionally an inner one).
"""
import math
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point, Polygon, LineString, box, MultiPolygon
from shapely.ops import unary_union
from shapely import affinity

from .art import polys, clean

USER_FRAMES = Path.home() / 'Documents' / 'StitchKit' / 'Frames'


@dataclass
class FrameTemplate:
    label: str
    outer: object                     # overall outline
    kind: str = 'ring'                # 'ring' | 'pieces'
    inner: object = None              # design area (pieces frames, or user frames with their own inner line)
    parts: list = field(default_factory=list)    # pieces frames: band pieces
    nodes: list = field(default_factory=list)    # extra outlined details (bamboo joints)
    band: float = 0.0                 # pieces frames: piece thickness in unit coords (for reporting)


# ---------------------------------------------------------------- ring outlines

def _notched(r=0.32):
    sq = box(-1, -1, 1, 1)
    cut = unary_union([Point(x, y).buffer(r, quad_segs=32) for x in (-1, 1) for y in (-1, 1)])
    return clean(sq.difference(cut))


def _stepped(s=0.22):
    sq = box(-1, -1, 1, 1)
    cut = unary_union([box(x - s, y - s, x + s, y + s) for x in (-1, 1) for y in (-1, 1)])
    return clean(sq.difference(cut))


def _scallop_square(n=6, r=None):
    """A square whose edges are rows of half-circle scallops."""
    r = r or 1.0 / n
    core = box(-1 + r, -1 + r, 1 - r, 1 - r)
    bumps = []
    for i in range(n):
        t = -1 + r + i * (2 - 2 * r) / (n - 1)
        for x, y in ((t, -1 + r), (t, 1 - r), (-1 + r, t), (1 - r, t)):
            bumps.append(Point(x, y).buffer(r, quad_segs=24))
    return clean(unary_union([core] + bumps))


def _cloud(n=8, r=0.34):
    core = Point(0, 0).buffer(1 - r, quad_segs=48)
    bumps = [Point((1 - r) * math.cos(2 * math.pi * i / n), (1 - r) * math.sin(2 * math.pi * i / n)).buffer(r, quad_segs=32)
             for i in range(n)]
    return clean(unary_union([core] + bumps))


def _label_scroll(w=1.0, h=0.62):
    """The classic curvy label: bulging round ends, scooped corners and a little peak top and bottom."""
    body = box(-w * 0.86, -h, w * 0.86, h)
    ends = [Point(sx * w * 0.70, 0).buffer(h * 0.62, quad_segs=32) for sx in (-1, 1)]
    g = unary_union([body] + ends)
    scoops = [Point(sx * w * 0.86, sy * h).buffer(h * 0.30, quad_segs=32) for sx in (-1, 1) for sy in (-1, 1)]
    g = g.difference(unary_union(scoops))
    peaks = [Polygon([(-h * 0.22, sy * h), (0, sy * (h + h * 0.20)), (h * 0.22, sy * h)]) for sy in (-1, 1)]
    dips = [Point(sx * w * 0.36, sy * (h + h * 0.30)).buffer(h * 0.36, quad_segs=32) for sx in (-1, 1) for sy in (-1, 1)]
    g = unary_union([g] + peaks).difference(unary_union(dips))
    return clean(g.buffer(0.02, join_style=1).buffer(-0.02, join_style=1))


def _label_bracket(w=1.0, h=0.78):
    """Rounded square with scooped corners and a pointed top and bottom (a "bracket" frame)."""
    g = box(-w, -h, w, h).buffer(-0.12, join_style=1).buffer(0.12, join_style=1)
    scoops = [Point(sx * w, sy * h).buffer(0.24, quad_segs=32) for sx in (-1, 1) for sy in (-1, 1)]
    g = g.difference(unary_union(scoops))
    peaks = [Polygon([(-0.16, sy * h), (0, sy * (h + 0.16)), (0.16, sy * h)]) for sy in (-1, 1)]
    side = [Polygon([(sx * w, -0.14), (sx * (w + 0.12), 0), (sx * w, 0.14)]) for sx in (-1, 1)]
    return clean(unary_union([g] + peaks + side))


# ---------------------------------------------------------------- piece frames

def _greek_key():
    """Four bars, each ending in a squared key hook that turns inward (as in a Greek key frame)."""
    t = 0.12           # bar thickness
    a = 0.70           # where the top/bottom bars end
    e = 0.92           # bar position from centre
    k = 0.22           # hook size

    def bar_top(sign):
        y = sign * e
        pts = [(-a + k * 0.55, y + sign * -k * 0.55), (-a + k * 0.55, y + sign * -k), (-a, y + sign * -k),
               (-a, y), (a, y), (a, y + sign * -k), (a - k * 0.55, y + sign * -k), (a - k * 0.55, y + sign * -k * 0.55)]
        return LineString(pts)

    def bar_side(sign):
        x = sign * e
        pts = [(x + sign * -k * 0.55, -a + k * 0.55), (x + sign * -k, -a + k * 0.55), (x + sign * -k, -a),
               (x, -a), (x, a), (x + sign * -k, a), (x + sign * -k, a - k * 0.55), (x + sign * -k * 0.55, a - k * 0.55)]
        return LineString(pts)
    bars = [bar_top(-1), bar_top(1), bar_side(-1), bar_side(1)]
    bars_g = [clean(b.buffer(t / 2, cap_style=2, join_style=2)) for b in bars]
    # the bars cross at the corners: sew them as one interlocked piece (little square windows where they cross)
    parts = [clean(unary_union(bars_g))]
    outer = clean(unary_union(bars_g)).convex_hull
    inner = box(-e + t / 2 + k + 0.04, -e + t / 2 + 0.06, e - t / 2 - k - 0.04, e - t / 2 - 0.06)
    inner = clean(unary_union([inner, box(-e + t / 2 + 0.06, -a + k + 0.02, e - t / 2 - 0.06, a - k - 0.02)]))
    return FrameTemplate('Greek key', outer, 'pieces', inner, parts, [], t)


def _pole(p0, p1, t, joints, extend=0.0):
    """One bamboo pole from p0 to p1 with thickness t; joints at the given fractions along it."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    a = (x0 - ux * extend, y0 - uy * extend)
    b = (x1 + ux * extend, y1 + uy * extend)
    body = LineString([a, b]).buffer(t / 2, cap_style=2, join_style=2)
    # slightly rounded ends, like cut cane
    body = clean(body.buffer(-t * 0.18, join_style=1).buffer(t * 0.18, join_style=1))
    nodes = []
    for f in joints:
        # a joint is a ridge straight across the cane, standing a touch proud of it
        cx, cy = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        px, py = -uy, ux
        n = LineString([(cx - px * t * 0.56, cy - py * t * 0.56), (cx + px * t * 0.56, cy + py * t * 0.56)])
        nodes.append(clean(n.buffer(t * 0.085, cap_style=1)))
    return body, nodes


def _bamboo_polygon(sides, t, joints_mid, rot):
    R = 1.0 - t * 0.6
    verts = [(R * math.cos(rot + 2 * math.pi * i / sides), R * math.sin(rot + 2 * math.pi * i / sides)) for i in range(sides)]
    parts, nodes = [], []
    for i in range(sides):
        p0, p1 = verts[i], verts[(i + 1) % sides]
        js = [0.5] if joints_mid else []
        js = [t * 0.55 / math.dist(p0, p1), 1 - t * 0.55 / math.dist(p0, p1)] + js
        body, nd = _pole(p0, p1, t, js, extend=t * 0.5)
        parts.append(body)
        nodes += nd
    # each pole tucks under the next one at the corners
    fixed = []
    for i, p in enumerate(parts):
        nxt = parts[(i + 1) % sides]
        fixed.append(clean(p.difference(nxt.buffer(0.004))) if i < sides - 1 else p)
    outer = clean(unary_union(parts + nodes))
    inner_r = R - t * 0.5 - t * 0.35
    inner = Polygon([(inner_r * math.cos(rot + 2 * math.pi * (i + 0.5) / sides) / math.cos(math.pi / sides) * math.cos(math.pi / sides),
                      inner_r * math.sin(rot + 2 * math.pi * (i + 0.5) / sides) / math.cos(math.pi / sides) * math.cos(math.pi / sides))
                     for i in range(sides)])
    inner = clean(Polygon(verts).buffer(-(t * 0.5 + t * 0.35), join_style=2))
    return fixed, nodes, outer, inner


def _bamboo_octagon():
    t = 0.16
    parts, nodes, outer, inner = _bamboo_polygon(8, t, joints_mid=False, rot=math.pi / 8)
    return FrameTemplate('Bamboo octagon', outer, 'pieces', inner, parts, nodes, t)


def _bamboo_square():
    """Square bamboo frame like a coaster: each side made of three canes, joints between them."""
    t = 0.18
    e = 1.0 - t * 0.6
    parts, nodes = [], []
    sides = [((-e, -e), (e, -e)), ((e, -e), (e, e)), ((e, e), (-e, e)), ((-e, e), (-e, -e))]
    for p0, p1 in sides:
        for j in range(3):
            a = (p0[0] + (p1[0] - p0[0]) * j / 3, p0[1] + (p1[1] - p0[1]) * j / 3)
            b = (p0[0] + (p1[0] - p0[0]) * (j + 1) / 3, p0[1] + (p1[1] - p0[1]) * (j + 1) / 3)
            L = math.dist(a, b)
            body, nd = _pole(a, b, t, [t * 0.30 / L, 1 - t * 0.30 / L], extend=t * (0.5 if j in (0, 2) else 0.0))
            parts.append(body)
            nodes += nd
    fixed = []
    for i, p in enumerate(parts):
        others = unary_union(parts[i + 1:]) if i < len(parts) - 1 else None
        fixed.append(clean(p.difference(others.buffer(0.004))) if others is not None and not others.is_empty else p)
    outer = clean(unary_union(parts + nodes))
    inner = box(-e + t * 0.85, -e + t * 0.85, e - t * 0.85, e - t * 0.85)
    return FrameTemplate('Bamboo square', outer, 'pieces', inner, fixed, nodes, t)


def _normalise_template(t: FrameTemplate):
    minx, miny, maxx, maxy = t.outer.bounds
    s = 2.0 / max(maxx - minx, maxy - miny)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    def n(g):
        return None if g is None else affinity.scale(affinity.translate(g, -cx, -cy), s, s, origin=(0, 0))
    return FrameTemplate(t.label, n(t.outer), t.kind, n(t.inner), [n(p) for p in t.parts], [n(p) for p in t.nodes],
                         t.band * s)


def built_in():
    ring = {
        'notched': ('Notched corners', _notched()),
        'stepped': ('Stepped corners', _stepped()),
        'label_scroll': ('Scroll label', _label_scroll()),
        'label_bracket': ('Bracket label', _label_bracket()),
        'scallop_square': ('Scalloped square', _scallop_square()),
        'cloud': ('Cloud', _cloud()),
    }
    out = {k: _normalise_template(FrameTemplate(lab, g)) for k, (lab, g) in ring.items()}
    out['greek_key'] = _normalise_template(_greek_key())
    out['bamboo_square'] = _normalise_template(_bamboo_square())
    out['bamboo_octagon'] = _normalise_template(_bamboo_octagon())
    return out


def user_frames():
    """Frames from Documents/StitchKit/Frames/*.svg: the biggest outline is the frame; a second outline
    inside it, if there is one, becomes the inner line."""
    out = {}
    if not USER_FRAMES.exists():
        return out
    from .art import load_svg
    for f in sorted(USER_FRAMES.glob('*.svg')):
        try:
            art = load_svg(f)
        except Exception:
            continue
        rings = []
        for p in polys(clean(unary_union([g for _, g in art.layers]))):
            rings.append(Polygon(p.exterior))
            rings += [Polygon(i) for i in p.interiors]
        rings.sort(key=lambda p: -p.area)
        if not rings:
            continue
        outer = rings[0]
        inner = next((r for r in rings[1:] if outer.contains(r) and r.area > 0.25 * outer.area), None)
        out['user_' + f.stem] = _normalise_template(FrameTemplate(f.stem.replace('_', ' '), outer, 'ring', inner))
    return out


def all_frames():
    d = built_in()
    d.update(user_frames())
    return d
