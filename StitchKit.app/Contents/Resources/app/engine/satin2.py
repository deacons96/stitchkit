"""Satin borders built as real Ink/Stitch satin columns (two rails plus rungs).

For each ring of a shape we make
  outer rail  the edge itself (pushed out a little over appliqué fabric)
  inner rail  the edge moved `width` inwards
  rungs       short lines straight across the column every couple of millimetres, so the stitches turn
              smoothly round curves and corners
Ink/Stitch then sews the satin with its own underlay, pull compensation and short stitches, which are
far better tested than anything home-made.

Inward points (where two scallops meet, the top of a heart) are rounded off very slightly first:
without that, every stitch on both sides would converge on one needle hole.
"""
import math

from shapely.geometry import LineString, Polygon, Point
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .art import polys, clean


def soften(region, width, sharp=False):
    """Round inward (reflex) corners so a satin of `width` can turn round them."""
    r = max(0.5, (0.28 if sharp else 0.4) * width)
    return clean(region.buffer(r, join_style=1, quad_segs=16).buffer(-r, join_style=1, quad_segs=16))


def _ring_rails(ring_coords, region, width, outer_offset, rung_every, inward_sign):
    """ring_coords: coordinates of one ring, oriented so the region is on its left.
    Returns (outer rail, inner rail, rungs) or None if the column can't be built."""
    ring = LineString(ring_coords)
    L = ring.length
    if L < 3 * width or L < 6:
        return None
    # inner rail: offset of this ring into the region
    poly_ring = Polygon(ring_coords)
    if inward_sign > 0:          # exterior: inward = shrink
        inner_g = clean(poly_ring.buffer(-width, join_style=1, quad_segs=16))
        outer_g = clean(poly_ring.buffer(outer_offset, join_style=1, quad_segs=16)) if outer_offset else poly_ring
    else:                        # hole: the column grows outwards from the hole into the region
        inner_g = clean(poly_ring.buffer(width, join_style=1, quad_segs=16))
        outer_g = clean(poly_ring.buffer(-outer_offset, join_style=1, quad_segs=16)) if outer_offset else poly_ring
    ip = polys(inner_g)
    op = polys(outer_g)
    if len(ip) != 1 or len(op) != 1 or ip[0].interiors or op[0].interiors:
        return None
    inner = orient(ip[0], 1.0).exterior
    outer = orient(op[0], 1.0).exterior
    if inward_sign < 0:
        inner = LineString(list(inner.coords)[::-1])
        outer = LineString(list(outer.coords)[::-1])
    inner_ls, outer_ls = LineString(inner.coords), LineString(outer.coords)
    # start both rails at matching points
    start = outer_ls.interpolate(0)
    d_in = inner_ls.project(start)

    def rotate(ls, d):
        c = list(ls.coords)[:-1]
        best = min(range(len(c)), key=lambda i: Point(c[i]).distance(ls.interpolate(d)))
        c = c[best:] + c[:best]
        return LineString(c + [c[0]])
    inner_ls = rotate(inner_ls, d_in)
    # rungs: straight across the column
    n = max(8, int(outer_ls.length / rung_every))
    rungs = []
    OL = outer_ls.length
    for k in range(n):
        d = OL * (k + 0.5) / n
        a = outer_ls.interpolate(d)
        b = inner_ls.interpolate(inner_ls.project(a))
        dx, dy = b.x - a.x, b.y - a.y
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            continue
        ux, uy = dx / ln, dy / ln
        rung = LineString([(a.x - ux * 0.4, a.y - uy * 0.4), (b.x + ux * 0.4, b.y + uy * 0.4)])
        # a rung must cross each rail once and not run into another part of the shape
        hit_o = rung.intersection(outer_ls)
        hit_i = rung.intersection(inner_ls)
        if getattr(hit_o, 'geom_type', '') != 'Point' or getattr(hit_i, 'geom_type', '') != 'Point':
            continue
        if rungs and LineString(rungs[-1]).intersects(rung):
            continue
        rungs.append(list(rung.coords))
    if len(rungs) < 4:
        return None
    return list(outer_ls.coords), list(inner_ls.coords), rungs


def satin_columns(region, width, outer_offset=0.0, holes=True, only_holes=False, rung_every=2.0, sharp=False):
    """List of satin columns, each [outer rail, inner rail, rung, rung, ...] as coordinate lists.
    Returns (columns, rings it could not build) so the caller can fall back for those."""
    region = soften(region, width, sharp)
    cols, failed = [], []
    for p in polys(region):
        p = orient(p, 1.0)
        rings = []
        if not only_holes:
            rings.append((list(p.exterior.coords), 1))
        if holes or only_holes:
            # holes of a CCW polygon are CW: reverse so the hole itself is CCW, then grow it outwards
            rings += [(list(r.coords)[::-1], -1) for r in p.interiors]
        for coords, sign in rings:
            res = _ring_rails(coords, p, width, outer_offset, rung_every, sign)
            if res is None:
                failed.append((coords, sign))
            else:
                outer, inner, rungs = res
                cols.append([outer, inner] + rungs)
    return cols, failed


def satin_objs(region, width, colour, label, outer_offset=0.0, holes=True, only_holes=False, spacing=None,
               pull_mm=0.2, sharp=False, method='satin_column', name=''):
    """Plan objects for a satin border: Ink/Stitch satin columns, falling back to the simple satin
    generator only for rings that can't be built as columns (very thin or oddly shaped ones)."""
    from .plan import Obj
    from .satin import satin_edge
    width = min(width, 7.0)
    if method == 'e_stitch':
        width = min(width, 2.4)          # blanket stitch: short teeth into the fabric
    if spacing is None:
        spacing = 0.32 if width < 2 else (0.36 if width < 4 else 0.40)
    cols, failed = satin_columns(region, width, outer_offset, holes, only_holes, sharp=sharp)
    params = {'zigzag_spacing_mm': '%.2f' % spacing, 'pull_compensation_mm': '%.2f' % pull_mm,
              'center_walk_underlay': 'True' if width < 2.2 else 'False',
              'contour_underlay': 'True' if width >= 2.2 else 'False',
              'contour_underlay_inset_mm': '0.4',
              'zigzag_underlay': 'True' if width >= 3.4 else 'False',
              'zigzag_underlay_spacing_mm': '2.5', 'zigzag_underlay_inset_mm': '0.6',
              'short_stitch_inset': '15', 'short_stitch_distance_mm': '0.2',
              'running_stitch_length_mm': '2.0', '_width': width,
              # one column after another: trim between them (short hops are sewn by steps.tidy_jumps), so no
              # travel stitch is ever dragged across an open space
              '_trim': True}
    if method != 'satin_column':
        params['satin_method'] = method
        if method == 'e_stitch':
            params['zigzag_spacing_mm'] = '2.2'
            params['contour_underlay'] = 'False'
            params['zigzag_underlay'] = 'False'
            params['center_walk_underlay'] = 'False'
    out = []
    if cols:
        out.append(Obj('satin', colour, seqs=cols, params=params, label=label, name=name))
    if failed:
        seqs = []
        for coords, sign in failed:
            ring_poly = Polygon(coords)
            if sign > 0:
                seqs += satin_edge(soften(ring_poly, width, sharp), width, spacing=spacing, outer_offset=outer_offset,
                                   holes=False)
            else:
                seqs += satin_edge(clean(ring_poly.buffer(width * 3).difference(ring_poly)), width, spacing=spacing,
                                   outer_offset=outer_offset, only_holes=True)
        out.append(Obj('manual', colour, seqs=seqs, label=label, name=name))
    return out
