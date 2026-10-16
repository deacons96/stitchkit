"""Fitting a design into a free area: the inside of a frame file, a bag tag below its hole, the gap
between the two halves of a split frame."""
import math

from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union, polylabel

from .art import polys, clean


def _centre(g):
    b = g.bounds
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def fits(region, cov, k, x, y):
    cx, cy = _centre(cov)
    g = affinity.translate(affinity.scale(cov, k, k, origin=(cx, cy)), x - cx, y - cy)
    return region.contains(g)


def best_fit(region, cov, scale='both', max_k=8.0):
    """Biggest scale (and where) the design fits inside `region`.

    scale: 'both' grow or shrink to fill the area, 'shrink' only shrink, 'none' keep the size.
    Returns (k, x, y, fits) where x, y is where the centre of the design's bounds goes."""
    region = clean(region)
    if region.is_empty or cov.is_empty:
        c = region.centroid if not region.is_empty else Point(0, 0)
        return 1.0, c.x, c.y, False
    big = max(polys(region), key=lambda p: p.area)
    cands = []
    try:
        pl = polylabel(big, tolerance=0.2)
        cands.append((pl.x, pl.y))
    except Exception:
        pass
    c = big.centroid
    cands.append((c.x, c.y))
    b = big.bounds
    cands.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    # a few spots up and down the middle (tags: below the hole) and side to side
    bx, by = cands[-1]
    for f in (-0.18, -0.09, 0.09, 0.18):
        cands.append((bx, by + f * (b[3] - b[1])))
        cands.append((bx + f * (b[2] - b[0]), by))
    cands = [(x, y) for x, y in cands if big.contains(Point(x, y))] or [(c.x, c.y)]
    hi_k = max_k if scale == 'both' else 1.0
    best = None
    for x, y in cands:
        if scale == 'none':
            if fits(region, cov, 1.0, x, y):
                return 1.0, x, y, True
            continue
        if not fits(region, cov, 0.02, x, y):
            continue
        lo, hi = 0.02, hi_k
        if fits(region, cov, hi, x, y):
            lo = hi
        else:
            for _ in range(24):
                mid = (lo + hi) / 2
                if fits(region, cov, mid, x, y):
                    lo = mid
                else:
                    hi = mid
        if best is None or lo > best[0] + 1e-6:
            best = (lo, x, y)
    if scale == 'none':
        x, y = cands[0]
        return 1.0, x, y, False
    if best is None:
        x, y = cands[0]
        return 0.02, x, y, False
    return best[0], best[1], best[2], True


def place_result(res, k_done, x, y):
    """Move a stitched design (already at its final scale) so the centre of its bounds is at x, y."""
    x0, y0, x1, y1 = res.bounds_mm()
    return res.translate(x - (x0 + x1) / 2, y - (y0 + y1) / 2)


def inner_region(cov, gap=2.0):
    """The free area inside stitching that encloses it (a frame's middle). None if nothing encloses."""
    holes = []
    for p in polys(cov):
        for ring in p.interiors:
            h = Polygon(ring)
            if h.area > 50:
                holes.append(h)
    if not holes:
        return None
    h = max(holes, key=lambda g: g.area)
    # anything stitched inside the middle (a keyring ring, a motif) stays clear too
    inside = clean(cov.intersection(h))
    free = clean(h.difference(inside.buffer(gap, join_style=1)) if not inside.is_empty else h)
    free = clean(free.buffer(-gap, join_style=1))
    return max(polys(free), key=lambda g: g.area) if not free.is_empty else None


def between_region(cov, gap=2.0):
    """For frames that don't close (left and right halves of a wreath): the space between the parts."""
    hull = cov.convex_hull
    free = clean(hull.difference(cov.buffer(gap, join_style=1)))
    if free.is_empty:
        return None
    c = hull.centroid
    ps = polys(free.buffer(-0.01))
    best = None
    for p in ps:
        score = p.area - 50 * p.distance(c)
        if best is None or score > best[0]:
            best = (score, p)
    return best[1] if best else None
