"""Click-a-shape changes to digitized artwork.

Every separate shape in the artwork has an id, "layer:index" (layer = colour in stitch order). Changes:
    colour     '#rrggbb'  sew it in another thread (joins that colour's shapes)
    merge      'i:j'      join it to another shape: it takes that shape's colour and settings
    stitch     'fill' | 'contour' | 'meander' | 'outline' | 'none'
    angle      degrees    direction of the fill rows
    applique   True       make it a piece of fabric: placement, tackdown, then a satin or blanket edge
    edge       'satin' | 'blanket'
    edge_colour '#rrggbb' thread for the appliqué edge (default: the darkest colour in the art)
"""
from shapely.ops import unary_union
from shapely import affinity

from .art import Artwork, polys, clean


def shapes(art):
    out = []
    for i, (c, g) in enumerate(art.layers):
        for j, p in enumerate(polys(g)):
            out.append(('%d:%d' % (i, j), c, p))
    return out


def svg_paths(art, size_mm=100.0):
    """Shapes for the click-to-edit preview: [{id, colour, d}] in millimetres at size_mm (longest side)."""
    from .plan import scaled_layers
    s = size_mm / max(art.width, art.height)
    minx = min(g.bounds[0] for _, g in art.layers)
    miny = min(g.bounds[1] for _, g in art.layers)
    out = []
    for sid, c, p in shapes(art):
        q = affinity.scale(affinity.translate(p, -minx, -miny), s, s, origin=(0, 0))
        d = []
        for ring in [q.exterior] + list(q.interiors):
            d.append('M' + ' L'.join('%.2f,%.2f' % xy for xy in list(ring.coords)[:-1]) + 'Z')
        out.append(dict(id=sid, colour=c, d=' '.join(d), area=round(q.area, 1)))
    return out


def apply(art: Artwork, edits):
    """New Artwork with colour/merge/hide changes made, plus the special shapes:
    [dict(kind='params'|'outline'|'applique', geom, colour, ...)] in the artwork's own units."""
    if not edits:
        return art, []
    items = {sid: dict(colour=c, geom=p, layer=int(sid.split(':')[0])) for sid, c, p in shapes(art)}
    # merges: follow chains to the shape that survives
    def root(sid, seen=()):
        e = edits.get(sid) or {}
        t = e.get('merge')
        if t and t in items and t not in seen and t != sid:
            return root(t, seen + (sid,))
        return sid
    merged = {}
    for sid in items:
        r = root(sid)
        merged.setdefault(r, []).append(sid)
    specials = []
    keep = []                                   # (layer order key, colour, geom)
    order = [c for c, _ in art.layers]
    for r, members in merged.items():
        e = dict(edits.get(r) or {})
        g = clean(unary_union([items[m]['geom'] for m in members]))
        # close hairline seams between merged neighbours
        if len(members) > 1:
            g = clean(g.buffer(0.01).buffer(-0.01))
        colour = e.get('colour') or items[r]['colour']
        layer = items[r]['layer']
        if colour not in order:
            order.append(colour)
        stitch = e.get('stitch') or 'fill'
        if e.get('applique'):
            specials.append(dict(kind='applique', geom=g, colour=colour, edge=e.get('edge') or 'satin',
                                 edge_colour=e.get('edge_colour') or '', layer=layer, id=r))
            continue
        if stitch == 'none':
            continue
        if stitch == 'outline':
            specials.append(dict(kind='outline', geom=g, colour=colour, layer=layer, id=r))
            continue
        if stitch in ('contour', 'meander') or e.get('angle') not in (None, ''):
            specials.append(dict(kind='params', geom=g, colour=colour, style=stitch if stitch != 'fill' else None,
                                 angle=e.get('angle'), id=r))
        keep.append((order.index(colour), colour, g))
    layers = []
    for c in order:
        gs = [g for _, cc, g in keep if cc == c]
        if gs:
            layers.append((c, clean(unary_union(gs))))
    new = Artwork(art.width, art.height, layers, list(art.notes))
    # keep the artwork's own position: shapes taken out (appliqué, outlines) must not shift the rest
    allg = [g for _, g in art.layers]
    b = unary_union(allg).bounds
    new.origin = (b[0], b[1])
    return new, specials
