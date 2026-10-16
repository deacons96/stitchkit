"""What goes *around* the design: a patch, a ring frame or a piece frame.

  patch         a patch shape with a faux-merrow satin border (fabric hooped, appliquéd, or a stitched
                background)
  ring frame    an outer outline and a parallel (or drawn) inner outline; the band between them is
                appliqué fabric, a fill, or left as the base fabric ("No fill or applique")
  piece frame   separate pieces (Greek key bars, bamboo poles), each outlined in satin; the pieces are
                appliqué, fill or left plain

Everything here is geometry in millimetres plus plan objects; steps.stitch_objects turns the objects into
stitches. Content (the design, text, stitch files) is described only by the area it covers.
"""
import math
from dataclasses import dataclass, field

from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .art import polys, clean
from .plan import Obj, Options, fill_params, nearest_order, satin_spacing, DENSITY
from .satin import satin_edge, run_along
from .satin2 import satin_objs, soften
from . import shapes, frames as framemod

BAND_CHOICES = {'applique': 'Appliqué', 'fill': 'Fill', 'none': 'No fill or applique'}


@dataclass
class Layout:
    kind: str                         # 'patch' | 'ring' | 'pieces'
    outer: object                     # overall outline (the cut line of the finished piece)
    inner: object = None              # area kept for the design (frames)
    pieces: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    widths: dict = field(default_factory=dict)

    def longest(self):
        b = self.outer.bounds
        return max(b[2] - b[0], b[3] - b[1])


# ---------------------------------------------------------------- sizes

def widths(opts: Options, longest_mm, kind):
    L = longest_mm
    if kind == 'patch':
        return dict(border=opts.border_mm or (3.0 if L < 64 else (4.0 if L < 115 else 5.0)))
    w = dict(border=opts.border_mm or (3.0 if L < 64 else (3.5 if L < 115 else 4.5)),
             band=opts.frame_band_mm or max(5.0, min(14.0, L * 0.085)),
             inner=opts.frame_inner_mm or (1.6 if L < 64 else 2.0))
    if kind == 'pieces':
        w['outline'] = opts.frame_inner_mm or (1.2 if L < 80 else (1.5 if L < 150 else 1.8))
    return w


_TEMPLATES = {}


def template(key):
    """Frame template for a key ('greek_key', 'user_Wreath', ...), or None for a patch shape."""
    if key.startswith('shape:') or not key:
        return None
    if key not in _TEMPLATES or key.startswith('user_'):
        _TEMPLATES.update(framemod.all_frames())
    return _TEMPLATES.get(key)


def frame_kind(opts):
    if not opts.frame:
        return 'patch'
    t = template(opts.frame_key)
    return 'ring' if t is None or t.kind == 'ring' else 'pieces'


def _map(tpl_outer, fitted, g):
    """Carry geometry drawn with a template onto the fitted copy of the template (uniform scale + move)."""
    tb, fb = tpl_outer.bounds, fitted.bounds
    s = (fb[2] - fb[0]) / (tb[2] - tb[0])
    g = affinity.scale(g, s, s, origin=(0, 0))
    return affinity.translate(g, fb[0] - tb[0] * s, fb[1] - tb[1] * s)


# ---------------------------------------------------------------- geometry

def _layout_once(cov, opts, extra, L):
    kind = frame_kind(opts)
    w = widths(opts, L, kind)
    gap = opts.gap_mm
    if kind == 'patch':
        S = shapes.fit(opts.patch_shape, cov, w['border'] + gap + extra, w['border'])
        return Layout('patch', clean(S), widths=w)
    tpl = template(opts.frame_key)
    if kind == 'ring':
        margin = w['border'] + w['band'] + w['inner'] + gap + extra
        if tpl is None:
            shape_key = opts.frame_key.split(':', 1)[1] if opts.frame_key.startswith('shape:') else opts.patch_shape
            S = shapes.fit(shape_key if shape_key != 'outline' else 'rounded', cov, margin, w['border'])
            I = None
        else:
            if tpl.inner is not None:
                # a drawn inner line: fit so the design sits inside it
                k = _fit_scale_inside(tpl.inner, cov.buffer(gap + w['inner'] + extra, join_style=1))
                S = _place(tpl.outer, k, cov)
                I = _place(tpl.inner, k, cov)
                return Layout('ring', clean(S), clean(I), widths=w)
            S = shapes.fit_poly(tpl.outer, cov.buffer(margin, join_style=1), 'fixed')
            I = None
        S = clean(S)
        if I is None:
            I = clean(S.buffer(-(w['border'] + w['band']), join_style=1))
            I = max(polys(I), key=lambda p: p.area) if not I.is_empty else I
        return Layout('ring', S, clean(I), widths=w)
    # pieces: scale the whole template until its design area holds the content
    k = _fit_scale_inside(tpl.inner, cov.buffer(gap + extra, join_style=1))
    S = _place(tpl.outer, k, cov)
    if not opts.frame_inner_mm:
        # keep the satin outline in proportion to the pieces so the fabric or fill still shows
        w['outline'] = round(max(0.9, min(w['outline'], 0.2 * tpl.band * k)), 2)
    return Layout('pieces', clean(S), clean(_place(tpl.inner, k, cov)),
                  [clean(_place(p, k, cov)) for p in tpl.parts], [clean(_place(n, k, cov)) for n in tpl.nodes], w)


def _place(g, k, cov):
    b = cov.bounds
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return affinity.translate(affinity.scale(g, k, k, origin=(0, 0)), cx, cy)


def _fit_scale_inside(tpl_inner, content):
    """Uniform scale of a template (centred on 0) whose inner area, centred on the content, holds it."""
    b = content.bounds
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    c0 = affinity.translate(content, -cx, -cy)
    lo, hi = 1.0, 2000.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if affinity.scale(tpl_inner, mid, mid, origin=(0, 0)).contains(c0):
            hi = mid
        else:
            lo = mid
    return hi


def layout(cov, opts, extra=0.0):
    """Container round the content; widths depend on the finished size, so settle them together."""
    b = cov.bounds
    guess = max(b[2] - b[0], b[3] - b[1]) + 30
    lay = None
    for _ in range(6):
        lay = _layout_once(cov, opts, extra, guess)
        if abs(lay.longest() - guess) < 0.5:
            break
        guess = lay.longest()
    return lay


def fit(cov, opts, target_mm=0.0, scale='both'):
    """Settle the content scale and the container for a finished size.

    scale: 'both'   the content may grow or shrink to make the piece target_mm (artwork)
           'shrink' the content may only shrink; extra room is added round it to reach the size (text)
           'none'   content stays as it is; extra room is added (stitch files)
    Returns (content scale, Layout, notes)."""
    notes = []
    lay = layout(cov, opts)
    if not target_mm:
        return 1.0, lay, notes
    L = lay.longest()
    k = 1.0
    if (scale == 'both') or (scale == 'shrink' and L > target_mm + 0.3):
        lo, hi = 0.02, 8.0 if scale == 'both' else 1.0
        for _ in range(26):
            mid = (lo + hi) / 2
            if layout(affinity.scale(cov, mid, mid, origin=(0, 0)), opts).longest() <= target_mm:
                lo = mid
            else:
                hi = mid
        k = lo
        lay = layout(affinity.scale(cov, k, k, origin=(0, 0)), opts)
        L = lay.longest()
    if L > target_mm + 0.5:
        notes.append('The smallest %s that fits this design is %.2f in (%.0f mm), so it was made at that size.'
                     % ('frame' if opts.frame else 'patch', L / 25.4, L))
    elif L < target_mm - 0.5:
        lay = grow_to(affinity.scale(cov, k, k, origin=(0, 0)) if k != 1 else cov, opts, target_mm)
    return k, lay, notes


def grow_to(cov, opts, target_mm):
    lo, hi = 0.0, target_mm
    for _ in range(24):
        mid = (lo + hi) / 2
        if layout(cov, opts, mid).longest() < target_mm:
            lo = mid
        else:
            hi = mid
    return layout(cov, opts, lo)


# ---------------------------------------------------------------- objects

def _appli_objs(outer_lines, tack_lines, zig_lines, colour, what):
    place = Obj('run', colour, lines=outer_lines, params={'running_stitch_length_mm': '2.5'},
                label='Placement line', name='Placement - lay %s' % what, stop_after=True)
    tack = Obj('run', colour, lines=tack_lines, params={'running_stitch_length_mm': '2.0'},
               label='Tackdown', name='Tackdown - then trim')
    if not zig_lines:
        # blanket-stitch edges hold the fabric themselves: a plain tackdown is enough
        tack.stop_after = True
        return [place, tack]
    zig = Obj('zigzag', colour, lines=zig_lines, params={'zigzag_width_mm': '1.4', 'zigzag_spacing_mm': '1.6'},
              label='Tackdown', name='Tackdown - then trim', stop_after=True)
    return [place, tack, zig]


def _fills(region, colour, opts, angle, label):
    out = []
    lo = Options(**{**opts.__dict__, 'size_in': max(opts.size_in, 2.6)})
    for p in nearest_order([p for p in polys(region) if p.area > 0.6]):
        out.append(Obj('fill', colour, poly=p, params=fill_params(colour, lo, p.area, angle, density='normal'),
                       label=label))
    return out


def _long_angle(p):
    """Direction of a piece's long side, so fills run along a bamboo pole like grain."""
    r = p.minimum_rotated_rectangle
    c = list(r.exterior.coords)
    best, ang = 0, 0
    for a, b in zip(c, c[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d > best:
            best, ang = d, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    return round(-ang + 90, 1)


def objects(lay: Layout, cov, opts: Options, border_colour):
    """(objects sewn before the design, objects sewn after it, fabric pieces, notes)."""
    pre, post, fabric, notes = [], [], [], []
    w = lay.widths
    sat = lambda width: satin_spacing(width, opts)
    if lay.kind == 'patch':
        # every line (placement, tackdown, cut file, border) follows the same gently rounded outline
        S = soften(lay.outer, w['border'], sharp=opts.patch_shape in shapes.SHARP_NOTCH)
        appl = opts.fabric_method == 'applique' and not opts.background
        blanket = appl and opts.edge_style == 'blanket'
        if appl:
            pre += _appli_objs(run_along(S), run_along(S.buffer(-0.6, join_style=1)),
                               [] if blanket else run_along(S.buffer(-1.2, join_style=1)), border_colour, 'patch fabric')
            fabric.append((S, opts.frame_band_colour if opts.frame else '#d9cbb0'))
            notes.append('Stops after the placement line (lay your patch fabric) and after the tackdown '
                         '(trim the fabric close).')
        if opts.background:
            bg = clean(S.buffer(-0.4, join_style=1).difference(cov.buffer(-0.35, join_style=1)))
            pre += _fills(bg, opts.background, opts, 30, 'Background')
            notes.append('Background stitched in %s around the design.' % opts.background)
        oo = (0.3 if blanket else 0.5) if appl else 0.0
        post += satin_objs(S, w['border'] if not blanket else min(w['border'], 3.0), border_colour, 'Border',
                           outer_offset=oo, holes=False, spacing=sat(w['border']), pull_mm=opts.pull(),
                           sharp=opts.patch_shape in shapes.SHARP_NOTCH,
                           method='e_stitch' if blanket else 'satin_column')
        if blanket:
            notes.append('Blanket stitch round the appliqué edge in %s, sewn last.' % border_colour)
        else:
            notes.append('Faux-merrow border: %.1f mm satin in %s, sewn last.' % (w['border'], border_colour))
        if opts.background:
            notes.append('Hoop a firm stabilizer (or felt/twill as a backing), stitch, then cut out close to the border.')
        elif not appl:
            notes.append('Hoop the patch fabric (twill) with stabilizer, stitch, then cut out close to the border '
                         '(a hot knife seals polyester twill).')
        return pre, post, fabric, notes

    band = opts.frame_band if opts.frame_band in BAND_CHOICES else 'applique'
    if lay.kind == 'ring':
        sharp_k = opts.frame_key.split(':')[-1] in shapes.SHARP_NOTCH
        S = soften(lay.outer, w['border'], sharp=sharp_k)
        r_in = max(0.5, (0.28 if sharp_k else 0.4) * w['inner'])
        I = clean(lay.inner.buffer(-r_in, join_style=1).buffer(r_in, join_style=1))
        region = clean(S.difference(I))
        blanket = band == 'applique' and opts.edge_style == 'blanket'
        if band == 'applique':
            pre += _appli_objs(run_along(S) + run_along(I),
                               run_along(S.buffer(-0.6, join_style=1)) + run_along(I.buffer(0.6, join_style=1)),
                               [] if blanket else
                               run_along(S.buffer(-1.3, join_style=1)) + run_along(I.buffer(1.3, join_style=1)),
                               border_colour, 'frame fabric')
            fabric.append((region, opts.frame_band_colour))
            notes.append('Appliqué frame: stops after the placement lines (lay your fabric over the band) and after '
                         'the tackdown (trim close outside the outer line and inside the inner line).')
        elif band == 'fill':
            fill = clean(S.buffer(-(w['border'] - 0.5), join_style=1).difference(I.buffer(w['inner'] - 0.5, join_style=1)))
            pre += _fills(fill, opts.frame_band_colour, opts, 45, 'Frame fill')
            notes.append('Frame band filled in %s.' % opts.frame_band_colour)
        else:
            notes.append('Frame band left as the base fabric (no fill or appliqué).')
        _centre(I, cov, opts, pre, notes)
        oo = (0.3 if blanket else 0.5) if band == 'applique' else 0.2
        meth = 'e_stitch' if blanket else 'satin_column'
        sharp = opts.frame_key.split(':')[-1] in shapes.SHARP_NOTCH
        post += satin_objs(region, w['inner'], border_colour, 'Inner frame line', outer_offset=oo, only_holes=True,
                           spacing=0.36, pull_mm=opts.pull(), sharp=sharp, method=meth)
        post += satin_objs(S, w['border'], border_colour, 'Frame border',
                           outer_offset=(0.3 if blanket else 0.5) if band == 'applique' else 0.0, holes=False,
                           spacing=sat(w['border']),
                           pull_mm=opts.pull(), sharp=sharp, method=meth)
        if blanket:
            notes.append('Blanket stitch along both edges of the appliqué band in %s, sewn last.' % border_colour)
        else:
            notes.append('Inner line %.1f mm and outer border %.1f mm in %s, sewn last over the band edges.'
                         % (w['inner'], w['border'], border_colour))
        return pre, post, fabric, notes

    # pieces
    ow = w['outline']
    pieces = [p for p in lay.pieces if not p.is_empty]
    blanket = band == 'applique' and opts.edge_style == 'blanket'
    if band == 'applique':
        outer_l, tack_l, zig_l = [], [], []
        for p in pieces:
            outer_l += run_along(p)
            tack_l += run_along(p.buffer(-0.5, join_style=1))
            if min(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) > 6:
                zig_l += run_along(p.buffer(-1.1, join_style=1))
        pre += _appli_objs(outer_l, tack_l, [] if blanket else (zig_l or tack_l), border_colour, 'frame fabric')
        for p in pieces:
            fabric.append((p, opts.frame_band_colour))
        notes.append('Appliqué pieces: stops after the placement lines (lay your fabric over all the pieces) and '
                     'after the tackdown (trim close round each piece). The Cricut file has every piece.')
    elif band == 'fill':
        for i, p in enumerate(pieces):
            inner = clean(p.buffer(-(ow - 0.5), join_style=1))
            pre += _fills(inner, opts.frame_band_colour, opts, _long_angle(p), 'Frame fill')
        notes.append('Frame pieces filled in %s.' % opts.frame_band_colour)
    else:
        notes.append('Frame pieces left as the base fabric (no fill or appliqué), outlined in satin.')
    _centre(lay.inner, cov, opts, pre, notes)
    for p in pieces:
        post += satin_objs(p, ow, border_colour, 'Frame outlines', outer_offset=0.4 if band == 'applique' else 0.0,
                           holes=True, spacing=0.36, pull_mm=opts.pull(),
                           method='e_stitch' if blanket else 'satin_column')
    if lay.nodes:
        nseqs = []
        for n in lay.nodes:
            nseqs += satin_edge(n, 3.0, outer_offset=0.0, holes=False, spacing=0.30, min_ring=2.0)
        post.append(Obj('manual', border_colour, seqs=nseqs, label='Bamboo joints'))
    notes.append('Each frame piece outlined in a %.1f mm satin in %s, sewn last.' % (ow, border_colour))
    return pre, post, fabric, notes


def _centre(I, cov, opts, pre, notes):
    if opts.frame_center == 'fill' and I is not None:
        centre = clean(I.buffer(0.3, join_style=1).difference(cov.buffer(-0.35, join_style=1)))
        pre += _fills(centre, opts.frame_center_colour, opts, -45, 'Centre fill')
        notes.append('Centre filled in %s around the design.' % opts.frame_center_colour)


# ---------------------------------------------------------------- thumbnails for the app

def frame_catalogue():
    """{key: (label, kind, svg path)} for the decorative frames (built in, then yours)."""
    out = {}
    for k, t in framemod.all_frames().items():
        g = t.outer
        if t.kind == 'ring':
            I = t.inner if t.inner is not None else clean(g.buffer(-0.22, join_style=1))
            shape = clean(g.difference(I))
        else:
            shape = clean(unary_union(t.parts + t.nodes))
        out[k] = (t.label, t.kind, shapes.outline_path(shape))
    return out
