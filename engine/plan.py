"""Decide what gets stitched, how, and in what order.

Two modes:
  design  - the artwork itself (fills with underlay, underlap between colours, optional crisp satin edge,
            outer border rings in the art become satin columns)
  patch   - the artwork inside a patch shape with a faux-merrow satin border (optionally on a placed
            piece of fabric with placement/tackdown lines and stops, optionally with a filled background)
"""
from dataclasses import dataclass, field
from typing import Optional
import math

from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union
from shapely import affinity
import shapely

from .art import Artwork, polys, clean, hex_rgb
from .satin import satin_edge, run_along
from . import shapes

MM_PER_IN = 25.4

# Tuned against the usual patch guideline of roughly 1,500 stitches per square inch of covered
# area (all stitches: underlay, fills, satins and border). Normal lands close to it.
DENSITY = {
    'light':  dict(row=0.32, underlay_row=2.2, max_len=3.8, satin=1.12),
    'normal': dict(row=0.27, underlay_row=2.0, max_len=3.5, satin=1.0),
    'dense':  dict(row=0.23, underlay_row=1.8, max_len=3.2, satin=0.92),
}


@dataclass
class Options:
    mode: str = 'design'                # 'design' | 'patch'
    size_in: float = 3.5                # longest side of the finished piece
    density: str = 'normal'             # light | normal | dense
    satin_outline: bool = False         # crisp satin edge round the design (design mode)
    detect_borders: bool = True         # turn outer border rings in the art into satin
    # patch options
    patch_shape: str = 'outline'        # outline | circle | oval | rectangle
    border_mm: float = 0.0              # 0 = automatic
    patch_in: float = 0.0               # existing stitch files: overall patch size, 0 = as small as fits
    border_colour: Optional[str] = None  # None = darkest colour in the art
    background: Optional[str] = None    # None = fabric shows; '#rrggbb' = stitched background
    fabric_method: str = 'hoop'         # 'hoop' (cut out after) | 'applique' (placement + tackdown, trim)
    gap_mm: float = 1.5                 # space between art and the border
    # appliqué frame (patch mode): outer satin, band, inner satin, design in the middle
    frame: bool = False
    frame_key: str = ''                 # decorative frame key, or 'shape:<patch shape>'
    frame_band: str = 'applique'        # 'applique' | 'fill' | 'none'
    frame_band_colour: str = '#c9d8f0'
    frame_band_mm: float = 0.0          # 0 = automatic
    frame_inner_mm: float = 0.0         # inner satin width, 0 = automatic
    frame_center: str = 'fabric'        # 'fabric' | 'fill'
    frame_center_colour: str = '#ffffff'
    # 1.2
    fabric: str = 'twill'               # fabric preset key (see fabrics.py)
    pull_mm: float = -1.0               # pull compensation; -1 = from the fabric preset
    knockdown: Optional[bool] = None    # None = from the fabric preset
    knockdown_colour: str = ''          # '' = the first design colour
    edge_style: str = 'satin'           # appliqué edges: 'satin' | 'blanket'
    fill_style: str = 'tatami'          # 'tatami' | 'contour' | 'meander'

    def pull(self):
        if self.pull_mm >= 0:
            return self.pull_mm
        from .fabrics import FABRICS
        return FABRICS.get(self.fabric, FABRICS['twill'])['pull_mm']

    def wants_knockdown(self):
        if self.knockdown is not None:
            return self.knockdown
        from .fabrics import FABRICS
        return FABRICS.get(self.fabric, FABRICS['twill'])['knockdown']


@dataclass
class Obj:
    kind: str                           # fill | manual | run | zigzag
    colour: str
    poly: object = None
    seqs: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    stop_after: bool = False
    label: str = ''
    name: str = ''                      # what the machine shows for this step (e.g. 'Placement - lay fabric')


def thicken(g, m):
    """Fatten any feature thinner than m so the needle can actually form it."""
    opened = g.buffer(-m / 2, join_style=1).buffer(m / 2, join_style=1)
    thin = [p for p in polys(clean(g.difference(opened))) if p.area > 0.08]
    if not thin:
        return g
    return clean(unary_union([g] + [p.buffer(m / 2 - 0.05, join_style=1) for p in thin]))


def min_feature(size_in):
    return 0.65 if size_in < 2 else (0.8 if size_in < 3 else 1.0)


def nearest_order(parts):
    if not parts:
        return []
    rest = sorted(parts, key=lambda p: -p.area)
    out = [rest.pop(0)]
    while rest:
        k = min(range(len(rest)), key=lambda i: rest[i].distance(out[-1]))
        out.append(rest.pop(k))
    return out


def lightness(c):
    r, g, b = hex_rgb(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def scaled_layers(art: Artwork, s):
    minx = min(g.bounds[0] for _, g in art.layers)
    miny = min(g.bounds[1] for _, g in art.layers)
    out = []
    for c, g in art.layers:
        g2 = affinity.translate(g, -minx, -miny)
        out.append((c, clean(affinity.scale(g2, s, s, origin=(0, 0)))))
    return out


def fill_params(colour, opts, area, angle, density=None):
    d = DENSITY[density or opts.density]
    small = opts.size_in <= 2.5
    p = {
        'angle': str(angle),
        'row_spacing_mm': '%.2f' % (d['row'] + (0.02 if small else 0)),
        'max_stitch_length_mm': '%.1f' % (min(d['max_len'], 3.0) if small else d['max_len']),
        'running_stitch_length_mm': '1.8' if small else '2.4',
        'staggers': '4',
        'fill_underlay': 'True' if area > 12 else 'False',
        'fill_underlay_angle': str(angle + 90),
        'fill_underlay_row_spacing_mm': '%.1f' % d['underlay_row'],
        'fill_underlay_max_stitch_length_mm': '3.5',
        'fill_underlay_inset_mm': '0.45',
        'underpath': 'True',
        'min_stitch_length_mm': '0.4',
        'min_jump_stitch_length_mm': '2.5',
        # fills pull in too: grow the shape a touch so it meets its neighbours and outlines
        'expand_mm': '%.2f' % min(0.35, 0.5 * opts.pull()),
        # sew extra rows where a narrow neck would otherwise leave a gap
        'gap_fill_rows': '1',
    }
    style = getattr(opts, 'fill_style', 'tatami')
    if style == 'contour' and area > 4:
        # stitches follow the outline of the shape, round and round (good for organic shapes)
        p.update({'fill_method': 'contour_fill', 'contour_strategy': '0', 'join_style': '0',
                  'avoid_self_crossing': 'True'})
    elif style == 'meander' and area > 30:
        p.update({'fill_method': 'meander_fill', 'meander_pattern': 'N3-16a', 'meander_scale_percent': '35',
                  'fill_underlay': 'False'})
    return p


def satin_spacing(width, opts):
    base = 0.34 if width < 2 else (0.38 if width < 4 else 0.42)
    return round(base * DENSITY[opts.density]['satin'], 3)


def _angles(colours):
    base = [45, -45, 0, 90, 20, -20, 70, -70]
    return {c: base[i % len(base)] for i, c in enumerate(colours)}


def plan_art(layers, opts, extra_above=None, knockout=None):
    """Fill objects for the art layers (bottom first) with underlap; returns objects and final geometry."""
    m = min_feature(opts.size_in)
    layers = [(c, thicken(clean(g.simplify(0.03)), m)) for c, g in layers]
    underlap = 0.35 if opts.size_in >= 2 else 0.3
    angles = _angles([c for c, _ in layers])
    objs = []
    for i, (c, g) in enumerate(layers):
        above = [x for _, x in layers[i + 1:]] + (extra_above or [])
        if above:
            cover = unary_union(above)
            g = clean(unary_union([g, g.buffer(underlap, join_style=1).intersection(cover)]))
        if knockout is not None:
            g = clean(g.difference(knockout))
        for p in nearest_order([p for p in polys(g) if p.area >= 0.6]):
            objs.append(Obj('fill', c, poly=p, params=fill_params(c, opts, p.area, angles[c])))
    return objs, layers


def detect_border(layers):
    """If one colour wraps the whole design as an outline band (like a sticker edge), return
    (index, band width in mm). Otherwise None."""
    if len(layers) < 2:
        return None
    sil = clean(unary_union([g for _, g in layers]))
    outer = clean(unary_union([Polygon(p.exterior) for p in polys(sil)]))
    edge = outer.boundary
    best = None
    for i, (c, g) in enumerate(layers):
        touching = edge.intersection(g.buffer(0.3)).length / max(edge.length, 1e-6)
        if touching < 0.85:
            continue
        others = unary_union([x for j, (_, x) in enumerate(layers) if j != i])
        ds = []
        for p in polys(outer):
            n = max(60, int(p.exterior.length))
            for k in range(n):
                ds.append(p.exterior.interpolate(k / n, normalized=True).distance(others))
        ds.sort()
        bw = ds[len(ds) // 2]
        band = outer.difference(outer.buffer(-max(bw, 0.4) * 1.15, join_style=1))
        share = band.intersection(g).area / max(g.area, 1e-6)
        # only a real outline band: most of this colour must be the ring itself (not line art or a big shape)
        if 0.4 <= bw <= 7.0 and share >= 0.5:
            best = (i, bw, outer)
    return best


def plan_design(art: Artwork, opts: Options):
    w, h = art.width, art.height
    s = opts.size_in * MM_PER_IN / max(w, h)
    layers = scaled_layers(art, s)
    m = min_feature(opts.size_in)
    objs = []
    border = None
    notes = []
    if opts.detect_borders:
        found = detect_border(layers)
        if found:
            i, bw, outer = found
            c = layers[i][0]
            width = max(bw, 1.3)
            from .satin2 import satin_objs
            border_objs = satin_objs(outer, width, layers[i][0], 'satin border', holes=False,
                                     spacing=satin_spacing(width, opts), pull_mm=opts.pull())
            band = outer.difference(outer.buffer(-width, join_style=1))
            rest = layers[i][1].difference(band.buffer(-0.15))
            r = max(0.25, min(0.3 * bw, 0.8))
            rest = clean(rest.buffer(-r, join_style=1).buffer(r, join_style=1))
            lost = clean(layers[i][1].difference(band).difference(rest.buffer(0.05)).intersection(outer.buffer(-0.6 * bw)))
            layers[i] = (c, rest)
            if not lost.is_empty:
                # slivers too small to stitch in this colour: let the neighbouring colour cover them
                top = max(range(len(layers)), key=lambda k: layers[k][1].area if k != i else -1)
                layers[top] = (layers[top][0], clean(unary_union([layers[top][1], lost.buffer(0.05)])))
            border = border_objs
            notes.append('Outer %s border sewn as a %.1f mm satin column, last.' % (c, width))
            layers = [(cc, g) for cc, g in layers if not g.is_empty]
            fills, layers = plan_art(layers, opts, extra_above=[band])
            objs += fills + border
    if border is None:
        ko, ow, sil = None, 0, None
        if opts.satin_outline:
            m = min_feature(opts.size_in)
            sil = clean(unary_union([thicken(clean(g.simplify(0.03)), m) for _, g in layers]))
            ow = 0.8 if opts.size_in < 2 else (1.0 if opts.size_in < 3 else 1.2)
            # the fill stops a little inside the edge satin instead of running underneath all of it
            ko = clean(sil.difference(sil.buffer(-(ow - 0.4), join_style=1)))
        fills, layers = plan_art(layers, opts, knockout=ko)
        objs += fills
        if opts.satin_outline:
            edge_colour = _edge_colour(layers, sil)
            from .satin2 import satin_objs
            objs += satin_objs(sil, ow, edge_colour, 'satin edge', spacing=max(0.42, satin_spacing(ow, opts)),
                               pull_mm=min(opts.pull(), 0.25))
            notes.append('Crisp %.1f mm satin edge sewn round the outline, last.' % ow)
    return objs, notes


def _edge_colour(layers, sil):
    edge = sil.boundary
    best, score = layers[-1][0], -1
    for c, g in layers:
        t = edge.intersection(g.buffer(0.2)).length
        if t > score:
            best, score = c, t
    return best
