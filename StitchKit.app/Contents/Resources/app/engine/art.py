"""Read artwork (SVG or bitmap) into flat colour regions.

Result: Artwork(width, height, layers) where layers is a list of (rgb_hex, shapely geometry) in stitch
order (bottom first), already knocked out so no two colours overlap, in the artwork's own units.
"""
from dataclasses import dataclass, field
import math
import re

import numpy as np
from shapely.geometry import Polygon, LineString, MultiPolygon, GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid


@dataclass
class Artwork:
    width: float
    height: float
    layers: list            # [(hex, geometry)]
    notes: list = field(default_factory=list)


def polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    if g.geom_type in ('MultiPolygon', 'GeometryCollection'):
        out = []
        for p in g.geoms:
            out += polys(p)
        return out
    return []


def clean(g):
    if g is None or g.is_empty:
        return Polygon()
    return unary_union(polys(make_valid(g)))


def rings_to_geom(rings, rule='evenodd'):
    """Build a filled area from closed point lists. Even-odd handles holes in compound paths."""
    shapes = []
    for pts in rings:
        if len(pts) >= 3:
            p = clean(Polygon(pts))
            if not p.is_empty:
                shapes.append(p)
    if not shapes:
        return Polygon()
    if rule == 'nonzero' and len(shapes) == 1:
        return shapes[0]
    shapes.sort(key=lambda s: -s.area)
    out = Polygon()
    for s in shapes:
        out = out.symmetric_difference(s)
    return clean(out)


def hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(c):
    return '#%02x%02x%02x' % tuple(int(v) for v in c[:3])


def colour_distance(a, b):
    a, b = hex_rgb(a), hex_rgb(b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ---------------------------------------------------------------- SVG

def _colour_of(value, svg):
    """Turn an SVG paint value into #rrggbb, or None for no paint."""
    import inkex
    if value is None:
        return None
    if isinstance(value, inkex.Color):
        return None if value is None else rgb_hex(value.to_rgb())
    if hasattr(value, 'stops'):          # gradient: use its first stop
        try:
            st = list(value.stops)
            if st:
                return rgb_hex(inkex.Color(st[0].style.get('stop-color')).to_rgb())
        except Exception:
            return None
        return None
    s = str(value).strip()
    if s in ('none', '', 'transparent'):
        return None
    try:
        return rgb_hex(inkex.Color(s).to_rgb())
    except Exception:
        return None


def load_svg(path):
    import inkex
    from inkex import bezier

    doc = inkex.load_svg(str(path))
    svg = doc.getroot()
    shapes = []
    notes = []
    tags = (inkex.PathElement, inkex.Rectangle, inkex.Circle, inkex.Ellipse, inkex.Polygon,
            inkex.Polyline, inkex.Line)
    for el in svg.descendants():
        if isinstance(el, inkex.TextElement):
            notes.append('Text found in the SVG was skipped: convert text to paths (outlines) first.')
            continue
        if isinstance(el, inkex.Image):
            notes.append('An embedded picture inside the SVG was skipped.')
            continue
        if not isinstance(el, tags):
            continue
        anc = [el] + list(el.ancestors())
        if any(isinstance(a, (inkex.Defs, inkex.ClipPath, inkex.Mask, inkex.Marker, inkex.Symbol)) or
               getattr(a, 'TAG', '') in ('defs', 'clipPath', 'mask', 'marker', 'symbol', 'pattern')
               for a in anc):
            continue
        try:
            style = el.specified_style()
        except Exception:
            style = el.style
        if str(style.get('display', '')) == 'none' or str(style.get('visibility', '')) == 'hidden':
            continue
        try:
            if float(style.get('opacity', 1) or 1) < 0.05:
                continue
        except ValueError:
            pass
        try:
            path = el.path.to_absolute().transform(el.composed_transform())
            csp = path.to_superpath()
        except Exception:
            continue
        bezier.cspsubdiv(csp, 0.05 * _scale_hint(svg))
        rings = []
        lines = []
        for sub in csp:
            pts = [(p[1][0], p[1][1]) for p in sub]
            if len(pts) >= 2:
                lines.append(pts)
                if len(pts) >= 3:
                    rings.append(pts)
        fill = _colour_of(style('fill') if callable(style) else style.get('fill', 'black'), svg)
        if 'fill' not in style and not callable(style):
            fill = '#000000'
        try:
            fo = float(style.get('fill-opacity', 1) or 1)
        except ValueError:
            fo = 1
        if fill and fo > 0.05:
            rule = 'nonzero' if str(style.get('fill-rule', 'nonzero')) == 'nonzero' else 'evenodd'
            g = rings_to_geom(rings, 'evenodd')
            if not g.is_empty:
                shapes.append((fill, g))
        stroke = _colour_of(style('stroke') if callable(style) else style.get('stroke'), svg)
        if stroke:
            try:
                sw = float(style.get('stroke-width', 1) or 1)
            except ValueError:
                sw = 1.0
            scale = math.sqrt(abs(el.composed_transform().matrix[0][0] * el.composed_transform().matrix[1][1]))
            sw *= scale or 1
            if sw > 0:
                g = clean(unary_union([LineString(l).buffer(sw / 2, join_style=1) for l in lines]))
                if not g.is_empty:
                    shapes.append((stroke, g))
    if not shapes:
        raise ValueError('No filled shapes found in the SVG. If it only has text, convert the text to paths first.')
    return _flatten_stack(shapes, notes)


def _scale_hint(svg):
    """Roughly 1/1000 of the drawing size (curve flattening tolerance). Files without a viewBox fall back to
    their width/height; never zero, which would make curve flattening run forever."""
    size = 0.0
    try:
        vb = svg.get_viewbox()
        size = max(vb[2], vb[3])
    except Exception:
        pass
    if not size or size <= 0:
        try:
            size = max(float(re.sub(r'[^0-9.]', '', svg.get('width') or '0') or 0),
                       float(re.sub(r'[^0-9.]', '', svg.get('height') or '0') or 0))
        except ValueError:
            size = 0.0
    return max(size, 100.0) / 1000.0


def _flatten_stack(shapes, notes, white_is_background=False):
    """Painter's stack -> non-overlapping colour layers in stitch order."""
    # merge near-identical colours (e.g. #fefefe and #fcfcfc)
    palette = []
    for c, _ in shapes:
        if not any(colour_distance(c, p) < 18 for p in palette):
            palette.append(c)

    def canon(c):
        return min(palette, key=lambda p: colour_distance(c, p))

    visible = []
    above = Polygon()
    for idx in range(len(shapes) - 1, -1, -1):
        c, g = shapes[idx]
        v = clean(g.difference(above)) if not above.is_empty else g
        if v.area > 0:
            visible.append((idx, canon(c), v))
        above = clean(unary_union([above, g]))
    # group by colour; order colours by the stacking position of their biggest visible piece
    groups = {}
    for idx, c, v in visible:
        groups.setdefault(c, []).append((idx, v))
    order = []
    for c, items in groups.items():
        g = clean(unary_union([v for _, v in items]))
        key = max(items, key=lambda t: t[1].area)[0]
        order.append((key, c, g))
    order.sort()
    w = max(s[1].bounds[2] for s in shapes) - min(s[1].bounds[0] for s in shapes)
    h = max(s[1].bounds[3] for s in shapes) - min(s[1].bounds[1] for s in shapes)
    layers = [(c, g) for _, c, g in order if g.area > 0]
    return Artwork(w, h, layers, sorted(set(notes)))


# ---------------------------------------------------------------- bitmaps

def load_bitmap(path, n_colours=3, max_px=1200):
    """Flat-colour artwork (PNG/JPG, e.g. exported from Procreate) -> colour regions via tracing."""
    from PIL import Image
    import potrace

    im = Image.open(path)
    im.load()
    alpha = None
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        alpha = np.array(im.split()[-1])
    rgb = im.convert('RGB')
    s = min(1.0, max_px / max(rgb.size))
    if s < 1:
        rgb = rgb.resize((int(rgb.width * s), int(rgb.height * s)), Image.LANCZOS)
        if alpha is not None:
            alpha = np.array(Image.fromarray(alpha).resize(rgb.size, Image.LANCZOS))
    arr = np.array(rgb).reshape(-1, 3)
    has_alpha = alpha is not None and (alpha < 128).sum() > 0.02 * alpha.size
    opaque = arr[(alpha.reshape(-1) >= 128)] if has_alpha else arr
    k_total = n_colours + (0 if has_alpha else 1)
    sample = opaque[np.random.default_rng(0).choice(len(opaque), min(len(opaque), 60000), replace=False)]
    sim = Image.fromarray(sample.reshape(1, -1, 3).astype('uint8'))
    k_try = k_total + 4
    pal = np.array(sim.quantize(colors=k_try, method=Image.Quantize.MEDIANCUT, kmeans=5,
                                dither=Image.Dither.NONE).getpalette()[:3 * k_try]).reshape(-1, 3)[:k_try].astype(int)

    def assign(p):
        return ((sample[:, None, :].astype(int) - p[None, :, :]) ** 2).sum(-1).argmin(1)

    # fold away thin anti-aliasing colours first, then merge the closest pair until the count fits
    while len(pal) > 1:
        counts = np.bincount(assign(pal), minlength=len(pal))
        small = counts.argmin()
        if len(pal) > k_total and counts[small] < 0.03 * len(sample):
            pal = np.delete(pal, small, 0)
            continue
        if len(pal) <= k_total:
            break
        dd = ((pal[:, None, :] - pal[None, :, :]) ** 2).sum(-1) + np.eye(len(pal), dtype=int) * (1 << 30)
        i, j = np.unravel_index(dd.argmin(), dd.shape)
        keep_i = counts[i] >= counts[j]
        pal = np.delete(pal, j if keep_i else i, 0)
    idx = ((arr[:, None, :].astype(int) - pal[None, :, :]) ** 2).sum(-1).argmin(1).reshape(rgb.height, rgb.width)
    H, W = idx.shape
    if has_alpha:
        bg_mask = alpha < 128
        bg_index = None
    else:
        border = np.concatenate([idx[0], idx[-1], idx[:, 0], idx[:, -1]])
        bg_index = int(np.bincount(border).argmax())
        # near-background shades (anti-aliased halos) count as background too
        for j in range(len(pal)):
            if j != bg_index and ((pal[j] - pal[bg_index]) ** 2).sum() < 45 ** 2:
                idx[idx == j] = bg_index
        bg_mask = _connected_to_border(idx == bg_index)
    # tidy speckle: a 3x3 majority filter on the colour index
    from PIL import ImageFilter
    idx = np.array(Image.fromarray(idx.astype('uint8')).filter(ImageFilter.ModeFilter(3))).astype(int)
    # a picture of the merged colours, so you can see what you'll get before digitizing
    view = pal.astype('uint8')[idx]
    view[bg_mask] = (255, 255, 255)
    reduced = Image.fromarray(view.astype('uint8'))
    pal = [int(v) for v in pal.reshape(-1)]
    shapes = []
    for k in np.unique(idx):
        mask = (idx == k) & ~bg_mask
        if mask.sum() < 0.003 * mask.size:
            continue
        colour = rgb_hex(pal[3 * k:3 * k + 3])
        geom = _trace(mask, potrace)
        if not geom.is_empty:
            shapes.append((colour, geom, mask.sum()))
    if not shapes:
        raise ValueError('Could not find any artwork in the picture (is it all one colour?).')
    # broad, light areas at the bottom of the stack; thin dark line work on top
    def key(t):
        c, g, _ = t
        r, gg, b = hex_rgb(c)
        light = (0.299 * r + 0.587 * gg + 0.114 * b) / 255.0
        mean_width = 2 * g.area / max(g.length, 1e-6)
        return -mean_width * (0.2 + light) ** 2
    shapes.sort(key=key)
    art = _flatten_stack([(c, g) for c, g, _ in shapes], [])
    art.notes.append('Traced from a picture with %d thread colours. Clean, flat colours trace best.' % len(art.layers))
    art.reduced = reduced
    return art


def _connected_to_border(mask):
    """Only background-coloured pixels that touch the edge count as background (keeps white teeth, eyes)."""
    from PIL import Image, ImageDraw
    im = Image.fromarray((mask * 255).astype('uint8')).copy()
    H, W = mask.shape
    seeds = [(x, 0) for x in range(0, W, 8)] + [(x, H - 1) for x in range(0, W, 8)] + \
            [(0, y) for y in range(0, H, 8)] + [(W - 1, y) for y in range(0, H, 8)]
    for sx, sy in seeds:
        if im.getpixel((sx, sy)) == 255:
            ImageDraw.floodfill(im, (sx, sy), 128)
    return np.array(im) == 128


def _trace(mask, potrace):
    padded = np.pad(mask, 2)
    plist = potrace.Bitmap(~padded).trace(turdsize=6, alphamax=1.0, opttolerance=0.2)
    rings = []
    for curve in plist:
        pts = []
        start = curve.start_point
        cur = (start.x, start.y)
        pts.append(cur)
        for seg in curve.segments:
            if seg.is_corner:
                pts.append((seg.c.x, seg.c.y))
                pts.append((seg.end_point.x, seg.end_point.y))
            else:
                p0 = cur
                for t in np.linspace(0.1, 1.0, 10):
                    mt = 1 - t
                    x = mt ** 3 * p0[0] + 3 * mt ** 2 * t * seg.c1.x + 3 * mt * t ** 2 * seg.c2.x + t ** 3 * seg.end_point.x
                    y = mt ** 3 * p0[1] + 3 * mt ** 2 * t * seg.c1.y + 3 * mt * t ** 2 * seg.c2.y + t ** 3 * seg.end_point.y
                    pts.append((x, y))
            cur = (seg.end_point.x, seg.end_point.y)
        rings.append([(x - 2, y - 2) for x, y in pts])
    g = rings_to_geom(rings)
    # drop rings that are just the image frame
    return clean(g)


def load(path, n_colours=3):
    p = str(path).lower()
    if p.endswith('.svg'):
        return load_svg(path)
    if p.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff')):
        return load_bitmap(path, n_colours)
    raise ValueError('Unsupported file type. Use SVG, PNG or JPG.')
