"""Bag tags: a stiff little tag with a satin keyring hole, made in the hoop.

Layers, front to back: quilting cotton, the stabilizer, foam (3 mm embroidery foam or Peltex I 71F),
quilting cotton. Sewing order:
    1 placement line                      stop: lay the front cotton
    2 tack line (front cotton)
    3 the design
                                          stop: hoop off, turn over, foam + back cotton, hoop back on
    4 tackdown through every layer        stop: trim the front and back cotton close
    5 dense satin edge, then the hole ring
The dense satin cuts through the foam so the tag pops out; the hole is punched after.
"""
import math

from shapely import affinity
from shapely.geometry import Point, Polygon, box, LineString
from shapely.ops import unary_union

from .art import polys, clean
from . import shapes as shapemod


def _r(g, r):
    return clean(g.buffer(-r, join_style=1).buffer(r, join_style=1))


def _classic(w=0.62, top=0.42):
    """The luggage-tag shape: straight sides, clipped top corners."""
    g = Polygon([(-w, 1), (w, 1), (w, -1 + top), (w - top * 0.85, -1), (-w + top * 0.85, -1), (-w, -1 + top)])
    return _r(g, 0.06)


def _bracket(w=0.6, r=0.17):
    g = box(-w, -1, w, 1)
    cut = unary_union([Point(x, y).buffer(r, quad_segs=24) for x in (-w, w) for y in (-1, 1)])
    return clean(g.difference(cut))


def _tab_square(s=0.86, tab=0.24):
    body = box(-s, -1 + 2 * tab * 0.9, s, 1)
    body = _r(body, 0.08)
    t = Point(0, -1 + tab).buffer(tab, quad_segs=24)
    neck = box(-tab * 0.62, -1 + tab, tab * 0.62, -1 + 2 * tab * 0.9 + 0.05)
    return clean(unary_union([body, t, neck]).buffer(0.03, join_style=1).buffer(-0.03, join_style=1))


def _tab_circle(tab=0.22):
    body = Point(0, 0.12).buffer(0.88, quad_segs=48)
    t = Point(0, -1 + tab).buffer(tab, quad_segs=24)
    neck = box(-tab * 0.6, -1 + tab, tab * 0.6, -0.6)
    return clean(unary_union([body, t, neck]).buffer(0.04, join_style=1).buffer(-0.04, join_style=1))


def _capsule(w=0.56):
    return LineString([(0, -1 + w), (0, 1 - w)]).buffer(w, quad_segs=32)


def _arch(w=0.62):
    pts = [(-w, 1), (w, 1), (w, -1 + w)]
    for i in range(1, 32):
        a = math.pi * i / 32
        pts.append((w * math.cos(a), -1 + w - w * math.sin(a)))
    pts.append((-w, -1 + w))
    return _r(Polygon(pts), 0.05)


def _scallop_top(w=0.62, n=3):
    body = box(-w, -0.78, w, 1)
    r = w / n
    bumps = [Point(-w + r + 2 * r * i, -0.78).buffer(r, quad_segs=20) for i in range(n)]
    return _r(clean(unary_union([body] + bumps)), 0.05)


def _hexagon_tall(w=0.7):
    return _r(Polygon([(0, -1), (w, -0.58), (w, 0.58), (0, 1), (-w, 0.58), (-w, -0.58)]), 0.06)


def _cushion(w=0.86, n=3.2):
    pts = []
    for i in range(240):
        a = 2 * math.pi * i / 240
        c, s = math.cos(a), math.sin(a)
        pts.append((w * math.copysign(abs(c) ** (2 / n), c), math.copysign(abs(s) ** (2 / n), s)))
    return Polygon(pts)


def _diamond_wide():
    return _r(Polygon([(0, -0.58), (1, 0), (0, 0.58), (-1, 0)]), 0.05)


def _norm(g):
    """Scale so the longest side is 2, centred on 0."""
    b = g.bounds
    s = 2.0 / max(b[2] - b[0], b[3] - b[1])
    return affinity.scale(affinity.translate(g, -(b[0] + b[2]) / 2, -(b[1] + b[3]) / 2), s, s, origin=(0, 0))


# key: (label, shape, where the hole goes as (x, y) in the normalised shape)
_SHAPES = [
    ('classic', 'Classic tag', lambda: _classic(), (0, -0.74)),
    ('classic_wide', 'Wide classic tag', lambda: _classic(0.78, 0.46), (0, -0.74)),
    ('rect', 'Rectangle', lambda: _r(box(-0.6, -1, 0.6, 1), 0.08), (0, -0.8)),
    ('bracket', 'Bracket corners', lambda: _bracket(), (0, -0.78)),
    ('arch', 'Arch top', lambda: _arch(), (0, -0.74)),
    ('capsule', 'Capsule', lambda: _capsule(), (0, -0.72)),
    ('scallop_top', 'Scalloped top', lambda: _scallop_top(), (0, -0.78)),
    ('oval', 'Oval', lambda: affinity.scale(Point(0, 0).buffer(1, quad_segs=64), 0.72, 1.0, origin=(0, 0)), (0, -0.72)),
    ('circle', 'Circle', lambda: Point(0, 0).buffer(1, quad_segs=64), (0, -0.72)),
    ('circle_tab', 'Circle with tab', lambda: _tab_circle(), (0, -0.78)),
    ('square_tab', 'Square with tab', lambda: _tab_square(), (0, -0.76)),
    ('cushion', 'Cushion', lambda: _cushion(), (0, -0.72)),
    ('hexagon', 'Hexagon', lambda: _hexagon_tall(), (0, -0.66)),
    ('scalloped', 'Scalloped circle', lambda: shapemod.SHAPES['scalloped'][1], (0, -0.7)),
    ('heart', 'Heart', lambda: shapemod.SHAPES['heart'][1], (-0.47, -0.5)),
    ('star', 'Star', lambda: shapemod.SHAPES['star'][1], (0, -0.5)),
    ('diamond', 'Diamond', lambda: _diamond_wide(), (0, -0.3)),
]

TAG_SHAPES = {k: (lab, f, hole) for k, lab, f, hole in _SHAPES}
_CACHE = {}

HOLES = {'small': 4.8, 'medium': 6.35, 'large': 8.0}       # punch sizes: 3/16, 1/4, 5/16 in
HOLE_LABELS = {'small': '3/16 in punch', 'medium': '1/4 in punch', 'large': '5/16 in punch'}
SATIN_SPACING = 0.30      # dense: the satin has to cut through the foam so the tag pops out


def shape(key):
    if key not in _CACHE:
        lab, f, hole = TAG_SHAPES.get(key, TAG_SHAPES['classic'])
        g = f()
        b = g.bounds
        s = 2.0 / max(b[2] - b[0], b[3] - b[1])
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        g = affinity.scale(affinity.translate(g, -cx, -cy), s, s, origin=(0, 0))
        # the hole spot was given for the shape as drawn
        hx, hy = (hole[0] - cx) * s, (hole[1] - cy) * s
        _CACHE[key] = (g, (hx, hy))
    return _CACHE[key]


def border_width(longest_mm):
    return 3.0 if longest_mm < 83 else (3.2 if longest_mm < 108 else 3.5)


class TagLayout:
    def __init__(self, outer, hole_c, hole_d, ring_w, border, region):
        self.outer = outer            # the finished tag outline (mm)
        self.hole_c = hole_c          # centre of the keyring hole
        self.hole_d = hole_d          # punch size
        self.ring_w = ring_w          # satin ring width
        self.border = border
        self.region = region          # where the design may go

    @property
    def ring_inner_r(self):
        return self.hole_d / 2 + 0.6

    @property
    def ring_outer_r(self):
        return self.ring_inner_r + self.ring_w

    def ring(self):
        return Point(*self.hole_c).buffer(self.ring_outer_r, quad_segs=32)


def layout(key, longest_mm, hole='medium', gap_mm=2.0, sideways=False, border_mm=0.0):
    g, (hx, hy) = shape(key)
    if sideways:
        g = affinity.rotate(g, -90, origin=(0, 0))
        hx, hy = hy, -hx
    k = longest_mm / 2.0
    S = clean(affinity.scale(g, k, k, origin=(0, 0)))
    bw = border_mm or border_width(longest_mm)
    hd = HOLES.get(hole, HOLES['medium'])
    ring_w = 2.6 if longest_mm >= 70 else 2.2
    lay = TagLayout(S, (hx * k, hy * k), hd, ring_w, bw, None)
    # keep the ring clear of the border satin: slide the hole in toward the middle until it fits
    keep = clean(S.buffer(-(bw + lay.ring_outer_r + 0.6), join_style=1))
    x, y = lay.hole_c
    if not keep.is_empty and not keep.contains(Point(x, y)):
        target = keep.centroid
        for i in range(1, 200):
            t = i / 200
            px, py = x + (target.x - x) * t, y + (target.y - y) * t
            if keep.contains(Point(px, py)):
                x, y = px, py
                break
    lay.hole_c = (x, y)
    inside = clean(S.buffer(-(bw + gap_mm), join_style=1))
    region = clean(inside.difference(lay.ring().buffer(gap_mm + 0.5)))
    lay.region = max(polys(region), key=lambda p: p.area) if not region.is_empty else inside
    return lay


def objects(lay: TagLayout, opts, colour, pull_mm):
    """(objects before the design, objects after it, fabric pieces)."""
    from .plan import Obj
    from .satin import run_along
    from .satin2 import satin_objs, soften
    S = soften(lay.outer, lay.border, sharp=opts.tag_shape in shapemod.SHARP_NOTCH)
    pre = [Obj('run', colour, lines=run_along(S), params={'running_stitch_length_mm': '2.5'},
               label='Placement line', name='Placement line', stop_after=True),
           Obj('run', colour, lines=run_along(S.buffer(-0.5, join_style=1)), params={'running_stitch_length_mm': '2.5'},
               label='Tack front cotton', name='Lay front cotton, sew tack line')]
    ring_mid = Point(*lay.hole_c).buffer(lay.ring_inner_r + lay.ring_w * 0.5, quad_segs=24)
    tack = Obj('run', colour, lines=run_along(S.buffer(-0.6, join_style=1)) + run_along(ring_mid),
               params={'running_stitch_length_mm': '2.0', 'repeats': '2'},
               label='Tackdown', name='Flip: foam + back cotton, tackdown', stop_after=True)
    post = [tack]
    post += satin_objs(S, lay.border, colour, 'Dense satin edge', outer_offset=0.5, holes=False,
                       spacing=SATIN_SPACING, pull_mm=pull_mm, sharp=opts.tag_shape in shapemod.SHARP_NOTCH,
                       name='Trim cotton, then dense satin')
    post += satin_objs(lay.ring(), lay.ring_w, colour, 'Keyring hole', holes=False, spacing=SATIN_SPACING,
                       pull_mm=pull_mm, name='Trim cotton, then dense satin')
    fabric = [(S, '#f3e6d8')]
    return pre, post, fabric


def supplies(material='foam'):
    foam = ('Peltex I 71F (cut about 1 in bigger than the tag)' if material == 'peltex' else
            '3 mm embroidery foam, cut about 1 in bigger than the tag (Peltex I 71F works too)')
    return [('Stabilizer', 'Plastic water-soluble film (such as Badgemaster) or medium tear-away'),
            ('Fabric', 'Quilting cotton for the front and the back, each cut about 1 in bigger than the tag'),
            ('Middle', foam),
            ('Needle', '75/11 sharp (90/14 if the foam is thick)'),
            ('Also', 'Painter\'s tape for the back layers, a hole punch, and a lighter to tidy foam edges')]


def guide(hole='medium', material='foam', design=True):
    """The steps to make a bag tag, in order (shown in StitchKit and on the thread sheet)."""
    mid = 'Peltex I 71F' if material == 'peltex' else 'the foam'
    steps = [
        'Hoop plastic water-soluble film (such as Badgemaster) or a medium tear-away.',
        'Sew the placement line.',
        'Lay the front cotton over the outline, right side up, and sew the tack line.',
    ]
    if design:
        steps.append('Sew the design.')
    steps += [
        'Take the hoop off the machine (leave everything hooped), turn it over and lay %s over the outline, '
        'then the back cotton, right side out. Tape the corners.' % mid,
        'Put the hoop back on and sew the tackdown.',
        'Take the hoop off and trim the front cotton close to the tackdown. Turn it over and trim the back '
        'cotton close too%s.' % ('' if material == 'foam' else ' (trim the Peltex close as well)'),
        'Put the hoop back on and sew the dense satin edge and the keyring hole.',
        'Take it out of the hoop: the tag pops out. Tear away the foam and stabilizer (rinse away any film).'
        if material == 'foam' else 'Take it out of the hoop and tear or rinse away the stabilizer.',
        'Punch out the hole inside the satin ring (%s).' % HOLE_LABELS.get(hole, HOLE_LABELS['medium']),
    ]
    if material == 'foam':
        steps.append('Pass a lighter flame quickly along the edges to melt away any foam fuzz.')
    return steps


def catalogue():
    out = {}
    for k, (lab, _f, _h) in TAG_SHAPES.items():
        g, (hx, hy) = shape(k)
        hole = Point(hx, hy).buffer(0.09, quad_segs=12)
        out[k] = (lab, shapemod.outline_path(clean(g.difference(hole))))
    return out
