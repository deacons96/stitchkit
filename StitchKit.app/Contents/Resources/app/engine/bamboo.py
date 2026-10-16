"""Bamboo and rattan frames, drawn after Tara's reference pictures.

Each frame is one joined-up band of canes (so nothing is stitched twice where canes meet), plus:
    cells   the separate canes, so a fill can run along each one like grain
    bars    thin satin details sewn on top: node bands across a cane, mitre lines at corners, and the
            edges where one cane passes over another
    panels  open spaces between canes (the mirror panes in the pictures): fabric shows, or a fill
The whole band is outlined in satin last, which also tidies the ends of every bar.
All in unit coordinates (longest side about 2, centred on 0, y down).
"""
import math

from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union
from shapely import affinity

from .art import polys, clean


def _area(v):
    return 0.5 * sum(v[i][0] * v[(i + 1) % len(v)][1] - v[(i + 1) % len(v)][0] * v[i][1] for i in range(len(v)))


def _offset(verts, d):
    """Offset a convex polygon's corners by d (outwards +) with mitred corners, keeping vertex order."""
    n = len(verts)
    s = 1 if _area(verts) > 0 else -1
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = verts[i], verts[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        nx, ny = (y1 - y0) / L * s, -(x1 - x0) / L * s
        lines.append(((x0 + nx * d, y0 + ny * d), (x1 - x0, y1 - y0)))
    out = []
    for i in range(n):
        (p, r), (q, t) = lines[i - 1], lines[i]
        den = r[0] * t[1] - r[1] * t[0]
        u = ((q[0] - p[0]) * t[1] - (q[1] - p[1]) * t[0]) / den
        out.append((p[0] + r[0] * u, p[1] + r[1] * u))
    return out


def _bar(p, direction, length):
    ux, uy = direction
    L = math.hypot(ux, uy) or 1
    ux, uy = ux / L, uy / L
    return LineString([(p[0] - ux * length / 2, p[1] - uy * length / 2), (p[0] + ux * length / 2, p[1] + uy * length / 2)])


class Builder:
    def __init__(self):
        self.band = []        # polygons
        self.cells = []       # polygons (fill runs along each)
        self.bars = []        # (LineString, 'node' | 'mitre')

    def ring(self, verts, t, mitres=True, nodes=(), double=0.0):
        """A ring of straight canes along a convex polygon. nodes: fractions along each side."""
        out = _offset(verts, t / 2)
        inn = _offset(verts, -t / 2)
        n = len(verts)
        for i in range(n):
            j = (i + 1) % n
            self.cells.append(clean(Polygon([inn[i], out[i], out[j], inn[j]])))
            if mitres:
                self.bars.append((LineString([inn[i], out[i]]), 'mitre'))
            a, b = verts[i], verts[j]
            dx, dy = b[0] - a[0], b[1] - a[1]
            for f in nodes:
                p = (a[0] + dx * f, a[1] + dy * f)
                self._node(p, (dx, dy), t, double)
        self.band.append(clean(Polygon(out).difference(Polygon(inn))))
        return out, inn

    def round_ring(self, rx, ry, t, nodes=0, double=0.0, phase=0.0, segs=12):
        """An oval or round ring, split into `segs` canes with node bands between some of them."""
        def pt(a, r_off=0.0):
            # point on the ellipse pushed out along the normal by r_off
            x, y = rx * math.cos(a), ry * math.sin(a)
            nx, ny = math.cos(a) / rx, math.sin(a) / ry
            L = math.hypot(nx, ny)
            return x + nx / L * r_off, y + ny / L * r_off
        N = 240
        outer = Polygon([pt(2 * math.pi * k / N, t / 2) for k in range(N)])
        inner = Polygon([pt(2 * math.pi * k / N, -t / 2) for k in range(N)])
        band = clean(outer.difference(inner))
        self.band.append(band)
        for s in range(segs):
            a0 = phase + 2 * math.pi * s / segs
            a1 = phase + 2 * math.pi * (s + 1) / segs
            ks = [a0 + (a1 - a0) * k / 16 for k in range(17)]
            cell = Polygon([pt(a, t / 2) for a in ks] + [pt(a, -t / 2) for a in reversed(ks)])
            self.cells.append(clean(cell))
        if nodes:
            for s in range(nodes):
                a = phase + 2 * math.pi * s / nodes
                x, y = pt(a)
                tx, ty = -rx * math.sin(a), ry * math.cos(a)
                self._node((x, y), (tx, ty), t, double)
        return outer, inner

    def _node(self, p, along, t, double):
        ax, ay = along
        L = math.hypot(ax, ay) or 1
        ux, uy = ax / L, ay / L
        across = (-uy, ux)
        offs = [0.0] if not double else [-double / 2, double / 2]
        for o in offs:
            q = (p[0] + ux * o, p[1] + uy * o)
            self.bars.append((_bar(q, across, t * 1.1), 'node'))

    def cane(self, p0, p1, t, nodes=(), over=None):
        """A single straight cane (a spoke or brace)."""
        g = clean(LineString([p0, p1]).buffer(t / 2, cap_style=2, join_style=2))
        self.band.append(g)
        cell = g
        if over is not None:
            cell = clean(g.difference(over))
        self.cells.append(cell)
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        for f in nodes:
            self._node((p0[0] + dx * f, p0[1] + dy * f), (dx, dy), t, 0)
        return g

    def finish(self, label, keep_cells_clear_of=None):
        band = clean(unary_union(self.band).buffer(0.004, join_style=2).buffer(-0.004, join_style=2))
        # cells must not overlap: each later cell gives way to the earlier ones
        fixed, taken = [], None
        for c in self.cells:
            c2 = clean(c.intersection(band))
            if taken is not None:
                c2 = clean(c2.difference(taken))
            if c2.area > 1e-5:
                fixed.append(c2)
                taken = c2 if taken is None else unary_union([taken, c2])
        # the design goes in the open space round the middle; other open spaces are panels
        holes = []
        for p in polys(band):
            holes += [Polygon(r) for r in p.interiors]
        outer = clean(unary_union([Polygon(p.exterior) for p in polys(band)]))
        free = clean(outer.difference(band))
        middle = None
        for f in polys(free):
            if f.contains(Point(0, 0)):
                middle = f
        if middle is None:
            middle = max(polys(free), key=lambda g: g.area)
        panels = [p for p in polys(free) if not p.equals(middle) and p.area > 1e-4]
        # bars only where there is cane under them
        bars = []
        for ln, kind in self.bars:
            seg = ln.intersection(band.buffer(0.002))
            for part in getattr(seg, 'geoms', [seg]):
                if part.geom_type == 'LineString' and part.length > 0.01:
                    bars.append((part, kind))
        return dict(label=label, outer=outer, band=band, cells=fixed, bars=bars, panels=panels, inner=middle)


def _regular(n, R, rot):
    return [(R * math.cos(rot + 2 * math.pi * i / n), R * math.sin(rot + 2 * math.pi * i / n)) for i in range(n)]


def _clipped_rect(w, h, c):
    """Rectangle with clipped corners (an elongated octagon), clockwise from top left."""
    return [(-w + c, -h), (w - c, -h), (w, -h + c), (w, h - c), (w - c, h), (-w + c, h), (-w, h - c), (-w, -h + c)]


def octagon_double():
    """Rattan octagon: two mitred cane rings with a woven panel between."""
    b = Builder()
    t = 0.12
    R1 = 1.0 - t * 0.55
    R2 = R1 * 0.66
    rot = math.pi / 8
    b.ring(_regular(8, R1 / math.cos(math.pi / 8) * math.cos(math.pi / 8), rot), t, mitres=True)
    b.ring(_regular(8, R2, rot), t * 0.85, mitres=True)
    return b.finish('Bamboo octagon, double')


def octagon_spokes():
    """Gold bamboo octagon: tall clipped rectangle, an inner one, and spokes joining their corners."""
    b = Builder()
    t = 0.11
    w, h, c = 0.76, 1.0 - t * 0.6, 0.30
    outer = _clipped_rect(w, h, c)
    d = 0.22
    inner = _clipped_rect(w - d, h - d, c * 0.72)
    nodes = (0.33, 0.66)
    b.ring(outer, t, mitres=False, nodes=nodes, double=t * 0.28)
    b.ring(inner, t, mitres=False, nodes=nodes, double=t * 0.28)
    rings = unary_union(b.band)
    for p, q in zip(outer, inner):
        b.cane(p, q, t * 0.85, nodes=(0.5,), over=rings)
    return b.finish('Bamboo octagon, spokes')


def square_caps():
    """Blue bamboo double square with square caps at the corners and braces between the squares."""
    b = Builder()
    t = 0.11
    a1, a2 = 1.0 - t * 1.0, 0.64
    sq = lambda a: [(-a, -a), (a, -a), (a, a), (-a, a)]
    b.ring(sq(a1), t, mitres=False, nodes=(0.22, 0.78), double=t * 0.3)
    b.ring(sq(a2), t, mitres=False, nodes=(0.5,), double=t * 0.3)
    rings = unary_union(b.band)
    # braces: angled legs top and bottom, straight ones at the sides
    for sy in (-1, 1):
        for sx in (-1, 1):
            b.cane((sx * 0.30, sy * a1), (sx * 0.20, sy * a2), t * 0.8, over=rings)
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.cane((sx * a1, sy * 0.30), (sx * a2, sy * 0.30), t * 0.8, over=rings)
    # corner caps: little square blocks
    caps = []
    for a, s in ((a1, t * 1.55), (a2, t * 1.45)):
        for x in (-a, a):
            for y in (-a, a):
                caps.append(box(x - s / 2, y - s / 2, x + s / 2, y + s / 2))
    for cp in caps:
        b.band.append(cp)
        for e in (LineString(list(cp.exterior.coords)[k:k + 2]) for k in range(4)):
            b.bars.append((e, 'mitre'))
    b.cells = caps + b.cells
    return b.finish('Bamboo square, corner caps')


def square_crossed():
    """Blue bamboo square: the inner canes run on to the outer ones, leaving little windows at the corners."""
    b = Builder()
    t = 0.105
    a1, a2 = 1.0 - t * 0.6, 0.68
    b.ring([(-a1, -a1), (a1, -a1), (a1, a1), (-a1, a1)], t, mitres=True, nodes=(0.32, 0.68), double=t * 0.3)
    ring = unary_union(b.band)
    for y in (-a2, a2):
        b.cane((-a1, y), (a1, y), t, nodes=(0.32, 0.68), over=ring)
    horiz = unary_union(b.band)
    for x in (-a2, a2):
        b.cane((x, -a1), (x, a1), t, nodes=(0.32, 0.68), over=horiz)
        # the horizontal canes pass over the vertical ones here
        for y in (-a2, a2):
            for e in (y - t / 2, y + t / 2):
                b.bars.append((LineString([(x - t / 2, e), (x + t / 2, e)]), 'mitre'))
    return b.finish('Bamboo square, crossed corners')


def square_spokes():
    """Blue bamboo double square, mitred, joined by diagonal spokes at the corners."""
    b = Builder()
    t = 0.105
    a1, a2 = 1.0 - t * 0.6, 0.68
    o, _ = b.ring([(-a1, -a1), (a1, -a1), (a1, a1), (-a1, a1)], t, mitres=True, nodes=(0.3, 0.5, 0.7), double=t * 0.3)
    b.ring([(-a2, -a2), (a2, -a2), (a2, a2), (-a2, a2)], t, mitres=True, nodes=(0.5,), double=t * 0.3)
    rings = unary_union(b.band)
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.cane((sx * a1, sy * a1), (sx * a2, sy * a2), t * 0.8, over=rings)
    return b.finish('Bamboo square, spokes')


def ring_single():
    b = Builder()
    t = 0.17
    r = 1.0 - t / 2
    b.round_ring(r, r, t, nodes=10, double=t * 0.22, segs=10, phase=-math.pi / 2)
    return b.finish('Bamboo ring')


def ring_double():
    b = Builder()
    t = 0.115
    r1 = 1.0 - t / 2
    r2 = r1 - t - 0.04
    b.round_ring(r1, r1, t, nodes=12, double=t * 0.3, segs=12, phase=-math.pi / 2)
    b.round_ring(r2, r2, t, nodes=12, double=t * 0.3, segs=12, phase=-math.pi / 2)
    return b.finish('Bamboo double ring')


def oval_flared(segs=14):
    """Oval of short canes, each flaring out at its ends where it meets the next."""
    b = Builder()
    rx, ry = 0.64, 1.0 - 0.07
    t0 = 0.09

    def pt(a, off):
        x, y = rx * math.cos(a), ry * math.sin(a)
        nx, ny = math.cos(a) / rx, math.sin(a) / ry
        L = math.hypot(nx, ny)
        return x + nx / L * off, y + ny / L * off
    for s in range(segs):
        a0 = -math.pi / 2 + 2 * math.pi * s / segs
        a1 = a0 + 2 * math.pi / segs
        K = 24
        ks = [a0 + (a1 - a0) * k / K for k in range(K + 1)]
        def w(k):
            e = abs(2 * k / K - 1)            # 0 in the middle, 1 at the ends
            return t0 * (1 + 0.5 * e ** 3)
        cell = Polygon([pt(a, w(k) / 2) for k, a in enumerate(ks)] + [pt(a, -w(k) / 2) for k, a in reversed(list(enumerate(ks)))])
        cell = clean(cell)
        b.band.append(cell)
        b.cells.append(cell)
        # the joint: a line across where two flared ends meet
        x, y = pt(a0, 0)
        tx, ty = -rx * math.sin(a0), ry * math.cos(a0)
        b.bars.append((_bar((x, y), (-ty, tx), t0 * 1.8), 'mitre'))
    return b.finish('Bamboo oval')


ALL = {
    'bamboo_octagon': octagon_double,
    'bamboo_octagon_spokes': octagon_spokes,
    'bamboo_square': square_caps,
    'bamboo_square_crossed': square_crossed,
    'bamboo_square_spokes': square_spokes,
    'bamboo_ring': ring_single,
    'bamboo_ring_double': ring_double,
    'bamboo_oval': oval_flared,
}
