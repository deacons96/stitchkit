"""Satin columns that hug an edge: borders, crisp outlines and faux-merrow patch edges.

Each ring of the region gets: a travel/underlay walk, edge-contour underlay and zig-zag underlay for
wide columns, then the satin itself. The outer edge follows the shape exactly (nudged out for pull);
the inner edge is `width` in, clamped where the shape is too narrow so the two sides meet instead of
crossing.
"""
import math
from shapely.geometry import LineString, Point
from shapely.prepared import prep

from .art import polys


def _frame(ls, L, d, win):
    a = ls.interpolate((d - win) % L)
    b = ls.interpolate((d + win) % L)
    c = ls.interpolate(d % L)
    tx, ty = b.x - a.x, b.y - a.y
    tl = math.hypot(tx, ty) or 1.0
    return c, -ty / tl, tx / tl


def satin_edge(region, width, spacing=None, pull=0.12, outer_offset=0.0, holes=True, min_ring=4.0, only_holes=False):
    """Returns a list of needle-point sequences, one per ring, longest first."""
    width = min(width, 7.0)
    if spacing is None:
        spacing = 0.30 if width < 2 else (0.36 if width < 4 else 0.40)
    bnd = region.boundary
    inside = prep(region)
    out = []
    for p in polys(region):
        rings = list(p.interiors) if only_holes else [p.exterior] + (list(p.interiors) if holes else [])
        for ring in rings:
            ls = LineString(ring.coords)
            L = ls.length
            if L < min_ring:
                continue
            n = max(12, int(L / spacing))
            win = max(0.4, width / 3)
            samples, flip = [], None
            for i in range(n):
                c, nx, ny = _frame(ls, L, L * i / n, win)
                if flip is None or i % 25 == 0:
                    flip = not inside.contains(Point(c.x + nx * 0.15, c.y + ny * 0.15))
                if flip:
                    nx, ny = -nx, -ny
                reach = width - outer_offset
                ray = LineString([(c.x + nx * 0.05, c.y + ny * 0.05),
                                  (c.x + nx * 2.2 * reach, c.y + ny * 2.2 * reach)])
                hit = ray.intersection(bnd)
                across = 2.2 * reach
                if not hit.is_empty:
                    across = min(Point(c.x, c.y).distance(h) for h in getattr(hit, 'geoms', [hit]))
                depth = min(reach, max(0.3, 0.55 * across))
                samples.append((c.x, c.y, nx, ny, depth))

            def at(sm, t):
                """point t mm inward from the edge (negative = outward)"""
                x, y, nx, ny, _ = sm
                return (x + nx * t, y + ny * t)

            oo = outer_offset
            seq = []
            step = max(1, int(1.8 / spacing))
            # 1. walk round the middle of the column (anchors the fabric and doubles as travel)
            walk = [at(sm, (sm[4] - oo) / 2) for sm in samples[::step]]
            seq += walk + [walk[0]]
            if width >= 2.4:
                # 2. contour underlay just inside both edges, out along the inner one and back along the outer
                inner_c = [at(sm, sm[4] - 0.4) for sm in samples[::step]]
                outer_c = [at(sm, 0.4 - oo) for sm in samples[::step]]
                seq += inner_c + [inner_c[0]] + outer_c[::-1] + [outer_c[-1]]
            if width >= 3.5:
                # 3. open zig-zag underlay across the column
                zz = max(1, int(2.0 / spacing))
                for k, sm in enumerate(samples[::zz]):
                    seq.append(at(sm, (0.5 - oo) if k % 2 else (sm[4] - 0.5)))
            # 4. the satin, from the outside edge (nudged out for pull) to the inner edge
            # short stitches: where the inner ends bunch up (outside corners, points of hearts and
            # diamonds) every other stitch stops part way, so the needle isn't hammering one spot
            inner = [at(sm, sm[4]) for sm in samples]
            short = [False] * n
            flip_s = False
            for i in range(n):
                a, b = inner[i - 1], inner[i]
                if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.5 * spacing:
                    flip_s = not flip_s
                    short[i] = flip_s
                else:
                    flip_s = False
            for i in range(n + 1):
                sm = samples[i % n]
                d = sm[4] * (0.55 if short[i % n] else 1.0)
                seq += [at(sm, -(pull + oo)), at(sm, d)]
            out.append(seq)
    out.sort(key=lambda s: -len(s))
    return out


def run_along(region, inset=0.0, step=2.0):
    """Plain running stitch round each ring (placement / tackdown lines)."""
    g = region.buffer(-inset, join_style=1) if inset else region
    lines = []
    for p in polys(g):
        for ring in [p.exterior] + list(p.interiors):
            ls = LineString(ring.coords)
            if ls.length > 2:
                lines.append(ls)
    return lines
