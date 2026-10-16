"""Make one finished piece (design, patch or frame) as a steps.Result.

Content comes from artwork, an existing stitch file, lines of text, a monogram or a hand-arranged
merge of several stitch files. A container (patch, frame) is fitted round what the content covers,
stitched, and the steps are put in sewing order: container prep (placement, tackdown, background,
band fill), the content, then the container's satin lines.
"""
from dataclasses import dataclass
from typing import Callable

from shapely import affinity
from shapely.geometry import LineString
from shapely.ops import unary_union

from .art import clean
from .plan import Options, plan_design, scaled_layers, lightness, MM_PER_IN
from . import steps as stepmod
from .steps import Result, Step
from . import container


@dataclass
class Content:
    cov: object                        # area covered at scale 1 (mm)
    render: Callable                   # render(k) -> Result at scale k (same coordinate frame, scaled about 0,0)
    scale: str = 'none'                # 'both' | 'shrink' | 'none' (see container.fit)
    label: str = 'Design'


# ---------------------------------------------------------------- content producers

def _label_design_steps(objs):
    order = []
    for o in objs:
        if not o.label and o.kind == 'fill':
            if o.colour not in order:
                order.append(o.colour)
            o.label = 'Design colour %d' % (order.index(o.colour) + 1)
        elif o.label in ('satin border', 'satin edge'):
            o.label = 'Design ' + o.label


def art_content(art, opts: Options, size_in, log):
    """Artwork at size_in (longest side); may grow or shrink."""
    s = size_in * MM_PER_IN / max(art.width, art.height)
    cov = clean(unary_union([g for _, g in scaled_layers(art, s)]))

    def render(k):
        o = Options(**{**opts.__dict__, 'mode': 'design', 'size_in': size_in * k})
        objs, notes = plan_design(art, o)
        _label_design_steps(objs)
        st = stepmod.stitch_objects(objs, log)
        return Result(st, [], notes, 'design')
    return Content(cov, render, 'both', 'Design')


def result_content(res: Result, scale='none', label='Design'):
    cov = stepmod.coverage(res.steps)
    return Content(cov, lambda k: res if abs(k - 1) < 1e-6 else res.scaled(k), scale, label)


def stitch_file_result(path, label='Design'):
    from .existing import read_stitch_file
    p = read_stitch_file(path)
    res = Result(stepmod.steps_from_pattern(p, label), [], [], 'design')
    pieces = find_applique(res.steps)
    if pieces:
        res.fabric = [(g, '#e8dcc4') for g in pieces]
        res.notes.append('Found %d appliqué piece%s in this design (a placement line followed by a tackdown); '
                         'they are in the Cricut cut file.' % (len(pieces), '' if len(pieces) == 1 else 's'))
    return res


def _runs(step):
    run = []
    for x, y, c in step.stitches:
        if c == stepmod.STITCH:
            run.append((x / 10.0, y / 10.0))
        else:
            if len(run) > 2:
                yield run
            run = []
    if len(run) > 2:
        yield run


def _line_mask(step, res=0.5, width_mm=3.2):
    """Where a step's stitching runs, on a 0.5 mm grid, thickened to width_mm (fast tackdown matching)."""
    import numpy as np
    from PIL import Image, ImageDraw
    pts = [(x / 10.0, y / 10.0) for x, y, c in step.stitches if c == stepmod.STITCH]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0 = min(xs) - 3, min(ys) - 3
    W, H = int((max(xs) - x0 + 3) / res) + 1, int((max(ys) - y0 + 3) / res) + 1
    im = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(im)
    for run in _runs(step):
        d.line([((x - x0) / res, (y - y0) / res) for x, y in run], fill=255, width=max(1, int(width_mm / res)))
    return np.asarray(im) > 0, x0, y0, res


def find_applique(steps):
    """Placement lines in an existing design: a closed loop of running stitches, with a later step
    (the tackdown) sewing along the same line. Returns the fabric shapes (mm)."""
    import math
    from shapely.geometry import Polygon
    from .art import polys
    found = []
    masks = {}

    def mask(k):
        if k not in masks:
            masks[k] = _line_mask(steps[k])
        return masks[k]

    for i, s in enumerate(steps[:-1]):
        for run in _runs(s):
            n = len(run)
            length = sum(math.dist(a, b) for a, b in zip(run, run[1:]))
            if n < 12 or length / n < 1.0 or math.dist(run[0], run[-1]) > 2.0:
                continue
            g = clean(Polygon(run).buffer(0))
            if g.is_empty or g.area < 80:
                continue
            g = max(polys(g), key=lambda p: p.area)
            # the tackdown: one of the next two steps follows the same line
            for k in range(i + 1, min(i + 3, len(steps))):
                m = mask(k)
                if m is None:
                    continue
                arr, x0, y0, res = m
                H, W = arr.shape
                hits = 0
                for x, y in run:
                    c, r = int((x - x0) / res), int((y - y0) / res)
                    if 0 <= r < H and 0 <= c < W and arr[r, c]:
                        hits += 1
                if hits >= 0.8 * n:
                    found.append((i, Polygon(g.exterior)))
                    break
    # loops inside loops of the same placement step are holes (a frame band, a letter's middle)
    shaped = []
    for i, g in found:
        inner = [h for j, h in found if j == i and h is not g and g.contains(h)]
        outer = [h for j, h in found if j == i and h is not g and h.contains(g)]
        if len(outer) % 2 == 1:
            continue                     # this loop is itself a hole
        for h in inner:
            if not any(o.contains(h) and g.contains(o) and o is not h for o in inner):
                g = g.difference(h)
        shaped.append(clean(g))
    out = []
    for g in shaped:
        if not any(g.symmetric_difference(o).area < 0.2 * g.area for o in out):
            out.append(g)
    return out


# ---------------------------------------------------------------- text

def text_line_result(line, opts, log):
    from . import text as textmod
    lab = 'Text "%s"' % line.text[:24]
    if line.font.startswith('emb:'):
        p = textmod.emb_line(line)
        return Result(stepmod.steps_from_pattern(p, lab), [], list(line.notes), 'text')
    geom = textmod.sys_line_geometry(line)
    if geom.is_empty:
        raise ValueError('Nothing to stitch for "%s".' % line.text)
    objs = textmod.plan_sys_text(geom, line.colour, opts)
    for o in objs:
        o.label = lab
    return Result(stepmod.stitch_objects(objs, log), [], list(line.notes), 'text')


def text_content(lines, middle, opts, gap_mm, align, log, status=None):
    """Lines of text stacked above/below an optional middle Result (art or stitch file).
    Shrinking re-stitches the lettering smaller, so letters stay properly digitized."""
    from . import text as textmod

    def build(k):
        above, below = [], []
        for i, l in enumerate(lines):
            if status:
                status('stitching text line %d of %d' % (i + 1, len(lines)))
            l2 = textmod.Line(**{**l.__dict__, 'height_mm': l.height_mm * k, 'notes': []})
            r = text_line_result(l2, opts, log)
            (below if l.position == 'below' else above).append(r)
        mid = [middle.scaled(k) if (middle is not None and abs(k - 1) > 1e-6) else middle] if middle is not None else []
        res = stepmod.stack(above + mid + below, gap_mm * k, align)
        if abs(k - 1) > 0.02:
            res.notes.append('Text was set at %d%% of the letter heights you chose so it fits the size you asked for.'
                             % round(100 * k))
        return res
    first = build(1.0)
    cache = {1.0: first}

    def render(k):
        k = round(k, 3)
        if k not in cache:
            cache[k] = build(k)
        r = cache[k]
        return r
    return Content(stepmod.coverage(first.steps), render, 'shrink', 'Text'), first


# ---------------------------------------------------------------- monograms

MONO_LAYOUTS = {
    'classic': 'Classic (small - BIG - small)',
    'row': 'Equal letters in a row',
    'stacked': 'Stacked (one above the other)',
}


def monogram_result(letters, font, height_mm, layout, colour, spacing_mm, opts, log):
    """letters: (first, middle, last). Classic puts them first-LAST-middle with the surname initial big."""
    from . import text as textmod
    f, m, l = [(x or '').strip()[:1].upper() for x in letters]
    if layout == 'classic':
        seq = [(f, 0.62), (l, 1.0), (m, 0.62)]
    else:
        seq = [(f, 1.0), (m, 1.0), (l, 1.0)]
    seq = [(c, s) for c, s in seq if c]
    if not seq:
        raise ValueError('Type at least one initial.')
    notes = []
    if font.startswith('emb:'):
        # embroidery fonts only stretch so far: keep the classic proportions inside the font's range
        meta = next((f for f in textmod.embroidery_fonts() if f['id'] == font), None)
        if meta:
            big = min(height_mm, meta['max_mm'])
            if layout == 'classic' and 0.62 * big < meta['min_mm']:
                big = min(meta['max_mm'], meta['min_mm'] / 0.62)
            big = max(big, meta['min_mm'])
            if abs(big - height_mm) > 0.5:
                notes.append('%s works between %.0f and %.0f mm, so the big letter is %.0f mm.'
                             % (meta['name'].strip(), meta['min_mm'], meta['max_mm'], big))
            height_mm = big
    parts = []
    for c, s in seq:
        line = textmod.Line(text=c if layout != 'classic' or s == 1.0 else c, font=font, height_mm=height_mm * s,
                            colour=colour)
        r = text_line_result(line, opts, log)
        notes += [n for n in line.notes if n not in notes]
        parts.append(r)
    if layout == 'stacked':
        res = stepmod.stack(parts, gap_mm=max(1.0, spacing_mm), align='center')
    else:
        # side by side, centred on each other vertically
        items, x = [], 0.0
        for r in parts:
            w, h = r.size_mm()
            items.append((r, x + w / 2, 0.0, 1.0))
            x += w + max(0.5, spacing_mm)
        res = stepmod.place(items)
    for i, s in enumerate(res.steps):
        s.label = s.label.replace('Text', 'Letter')
    res.notes = notes + ['Monogram: %s.' % MONO_LAYOUTS.get(layout, layout)]
    res.kind = 'monogram'
    return res


# ---------------------------------------------------------------- the whole piece

def border_colour_for(res: Result, opts: Options):
    if opts.border_colour:
        return opts.border_colour
    cols = [s.colour for s in res.steps] or ['#000000']
    return min(cols, key=lightness)


def make_piece(content: Content, opts: Options, target_mm, log, status=None):
    """Design alone, or inside a patch/frame of target_mm (0 = as small as fits)."""
    if opts.mode != 'patch':
        res = content.render(1.0)
        return with_knockdown(res, opts, log)
    if target_mm:
        # the outer satin reaches a little past the cut line (pull compensation, and further over appliqué
        # fabric), so aim the cut line that much smaller and the stitched piece comes out at the size asked
        appl = (opts.frame and opts.frame_band == 'applique') or \
            (not opts.frame and opts.fabric_method == 'applique' and not opts.background)
        target_mm -= 1.25 if appl else 0.3
    if status:
        status('fitting the %s' % ('frame' if opts.frame else 'patch'))
    k, lay, notes = container.fit(content.cov, opts, target_mm, content.scale)
    if status:
        status('stitching the design')
    res = content.render(k)
    # settle the container on what was actually stitched
    real_cov = stepmod.coverage(res.steps)
    if target_mm:
        k2, _l, _n = container.fit(real_cov, opts, target_mm, content.scale)
        if abs(k2 - 1) > 0.005 and content.scale != 'none':
            # what was stitched came out a touch off the planned size: stitch it once more
            res = content.render(k * k2)
            real_cov = stepmod.coverage(res.steps)
        _k, lay, notes2 = container.fit(real_cov, opts, target_mm, 'none')
        notes = notes2
    else:
        lay = container.layout(real_cov, opts)
    bc = border_colour_for(res, opts)
    pre, post, fabric, cnotes = container.objects(lay, real_cov, opts, bc)
    if status:
        status('stitching the %s' % ('frame' if opts.frame else 'patch border'))
    st = stepmod.stitch_objects(pre + post, log)
    n_pre = _count_pre(st, pre)
    out = Result(st[:n_pre] + res.steps + st[n_pre:], fabric, notes + res.notes + cnotes,
                 'frame' if opts.frame else 'patch', lay.outer)
    return with_knockdown(out, opts, log)


def with_knockdown(res: Result, opts: Options, log):
    """A very open fill sewn first under the whole design, so towel loops and fleece pile lie flat and
    the stitches on top don't sink in."""
    if not opts.wants_knockdown() or not res.steps:
        return res
    from .art import polys
    from .plan import Obj
    from shapely.geometry import Polygon
    cov = stepmod.coverage(res.steps)
    # in a matching thread it may reach 1 mm past the design; in a design colour it stays just inside
    grow = 1.0 if opts.knockdown_colour else -0.4
    area = clean(cov.buffer(1.5, join_style=1).buffer(-1.5 + grow, join_style=1))
    area = clean(unary_union([Polygon(p.exterior) for p in polys(area)]))
    if res.outline is not None:
        # a patch or frame: keep the knockdown inside its outline
        area = clean(area.intersection(res.outline.buffer(-0.8, join_style=1)))
    colour = opts.knockdown_colour or res.steps[0].colour
    objs = []
    for p in polys(area):
        if p.area < 4:
            continue
        objs.append(Obj('fill', colour, poly=p, label='Knockdown', name='Knockdown - thread to match the fabric',
                        params={'angle': '45', 'row_spacing_mm': '1.0', 'max_stitch_length_mm': '4.0',
                                'running_stitch_length_mm': '3.0', 'fill_underlay': 'False', 'staggers': '2',
                                'underpath': 'True', 'expand_mm': '0'}))
    if not objs:
        return res
    kd = stepmod.stitch_objects(objs, log)
    notes = list(res.notes) + [('Knockdown stitch sewn first in %s, about 1 mm past the design, to flatten the pile.' % colour)
                               if opts.knockdown_colour else
                               ('Knockdown stitch sewn first in %s (the design\'s first colour), just inside the design so '
                                'it doesn\'t show. Pick a thread matching your fabric to let it reach a little past the '
                                'edge.' % colour)]
    return Result(kd + res.steps, res.fabric, notes, res.kind, res.outline)


def _count_pre(st, pre):
    labels = {(o.label, o.name) for o in pre}
    n = 0
    for s in st:
        if (s.label, s.name) in labels or (s.label, '') in labels:
            n += 1
        else:
            break
    return n
