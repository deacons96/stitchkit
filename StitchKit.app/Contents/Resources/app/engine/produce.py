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
    smaller: Callable = None           # letter sets: the next smaller size, if this one doesn't fit


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
        extra = {}
        objs, notes = plan_design(art, o, extra)
        _label_design_steps(objs)
        st = stepmod.stitch_objects(objs, log)
        return Result(st, extra.get('fabric', []), notes, 'design')
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


# ---------------------------------------------------------------- bag tags (built-in shapes)

def _fit_in_region(content, region_poly, log, status=None):
    """Stitch the content as big as it may be inside region_poly and move it there."""
    from . import region as regmod
    notes = []
    if getattr(content, 'fixed', False):
        # arranged by hand: keep it exactly where you put it
        res = content.render(1.0)
        if not region_poly.buffer(1.0).contains(stepmod.coverage(res.steps)):
            notes.append('Part of your arrangement runs past the space inside: check the preview.')
        return res, notes
    k, x, y, ok = regmod.best_fit(region_poly, content.cov, content.scale)
    if status:
        status('stitching the design')
    res = content.render(k if content.scale != 'none' else 1.0)
    if content.scale != 'none':
        real = stepmod.coverage(res.steps)
        k2, x2, y2, ok2 = regmod.best_fit(region_poly, real, 'shrink')
        if k2 < 0.99:
            res = content.render(k * k2 * 0.995)
            real = stepmod.coverage(res.steps)
            k3, x, y, ok = regmod.best_fit(region_poly, real, 'none')
        else:
            x, y, ok = x2, y2, ok2
    res = regmod.place_result(res, 1.0, x, y)
    if not ok:
        notes.append('Your design is bigger than the space inside, so it overlaps the edge: check the preview, '
                     'or choose a bigger size.')
    elif content.scale == 'shrink' and k < 0.98:
        notes.append('The design was set at %d%% so it fits inside.' % round(100 * k))
    return res, notes


def _design_or_smaller(content, region_poly, log, status=None):
    """Monogram letter sets come in fixed sizes: use the biggest that fits."""
    from . import region as regmod
    c = content
    while c is not None:
        k, x, y, ok = regmod.best_fit(region_poly, c.cov, 'none')
        nxt = getattr(c, 'smaller', None)
        if ok or nxt is None:
            return _fit_in_region(c, region_poly, log, status)
        c = nxt()
    return _fit_in_region(content, region_poly, log, status)


def make_tag_piece(content, opts, target_mm, log, status=None):
    from . import tags
    target_mm = target_mm or 4 * 25.4
    if status:
        status('shaping the bag tag')
    lay = tags.layout(opts.tag_shape, target_mm, opts.tag_hole, max(1.5, opts.gap_mm), opts.tag_sideways,
                      opts.border_mm)
    notes = []
    design = Result([], [], [], 'design')
    if content is not None:
        design, notes = _design_or_smaller(content, lay.region, log, status)
    colour = opts.border_colour or (border_colour_for(design, opts) if design.steps else '#1b2a4a')
    pre, post, fabric = tags.objects(lay, opts, colour, opts.pull())
    if status:
        status('stitching the tag edge and keyring hole')
    st = stepmod.stitch_objects(pre + post, log)
    n_pre = _count_pre(st, pre)
    body = list(design.steps)
    from dataclasses import replace
    if body:
        body[-1] = replace(body[-1], stop_after=True)      # stop: turn the hoop over for the foam
    else:
        st[n_pre - 1] = replace(st[n_pre - 1], stop_after=True)
    steps = st[:n_pre] + body + st[n_pre:]
    w = lay.outer.bounds
    notes = notes + design.notes + [
        'Bag tag %.2f x %.2f in with a %s keyring hole: dense %.1f mm satin edge in %s.'
        % ((w[2] - w[0]) / 25.4, (w[3] - w[1]) / 25.4, tags.HOLE_LABELS.get(opts.tag_hole, ''), lay.border, colour),
        'Stops: after the placement line (front cotton), after the design (turn the hoop over: foam and back '
        'cotton), and after the tackdown (trim).']
    out = Result(steps, fabric, notes, 'tag', lay.outer, tags.guide(opts.tag_hole, opts.tag_material, bool(body)))
    return out


# ---------------------------------------------------------------- your own frame and tag files

def _load_part(path):
    from . import stitchparts
    from .existing import read_stitch_file
    steps = stepmod.steps_from_pattern(read_stitch_file(path), 'Frame')
    steps, info = stitchparts.roles(steps)
    return stitchparts.name_parts(steps, info), info


def _phases(steps, info):
    o = info['outlines']
    P = [steps[o[0]]] if o else []
    F = [steps[k] for k in o[1:-1]] if len(o) >= 3 else []
    T = [steps[o[-1]]] if len(o) >= 2 else []
    used = set(o)
    D = [s for i, s in enumerate(steps) if i not in used]
    return dict(P=P, F=F, T=T, D=D)


def _interleave(lists):
    """Several parts' steps: same position, same thread -> sewn together, fewer thread changes."""
    lists = [l for l in lists if l]
    if not lists:
        return []
    if len(lists) > 1 and len(set(len(l) for l in lists)) == 1 and \
            all([s.colour for s in l] == [s.colour for s in lists[0]] for l in lists):
        out = []
        for i in range(len(lists[0])):
            out += [l[i] for l in lists]
        return out
    return [s for l in lists for s in l]


def make_file_frame_piece(content, ff, size_label, opts, log, status=None, tag=False):
    """Your design inside one of your own frame or tag stitch files. The file's stitches are kept
    exactly as they are; StitchKit only adds stops and slips the design in at the right moment."""
    from dataclasses import replace
    from . import region as regmod, tags
    from .art import polys
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    parts = ff.sizes.get(size_label) or next(iter(ff.sizes.values()))
    if status:
        status('reading your %s file' % ('tag' if tag else 'frame'))
    loaded = []
    for part, path in parts:
        steps, info = _load_part(path)
        loaded.append([part, Result(steps, [], [], 'frame'), info])
    notes = []
    # halves saved separately (each centred on its own): set them either side of the design
    split = False
    if len(loaded) > 1:
        bs = [r.bounds_mm() for _, r, _ in loaded]
        ov = 0
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                a, b = bs[i], bs[j]
                ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
                iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
                ov = max(ov, ix * iy / max(1e-6, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))))
        split = ov > 0.3
    design = Result([], [], [], 'design')
    if split:
        design = content.render(1.0) if content is not None else design
        dw, dh = design.size_mm() if design.steps else (40.0, 40.0)
        if design.steps and not getattr(content, 'fixed', False):
            design = design.centred()
        space = opts.part_gap_mm or max(3.0, opts.gap_mm + 2.0)
        for item in loaded:
            part, r, info = item
            r = r.centred()
            w, h = r.size_mm()
            dx = {'left': -(dw / 2 + space + w / 2), 'right': dw / 2 + space + w / 2}.get(part, 0.0)
            dy = {'top': -(dh / 2 + space + h / 2), 'bottom': dh / 2 + space + h / 2}.get(part, 0.0)
            item[1] = r.translate(dx, dy)
        notes.append('The parts of the frame are set %.1f mm from your design on each side (change "Space between '
                     'the parts" to move them).' % space)
    frame_steps = [s for _, r, _ in loaded for s in r.steps]
    dense = [s for _, r, info in loaded for i, s in enumerate(r.steps) if i not in set(info['outlines'])]
    cov = stepmod.coverage(dense or frame_steps)
    if not split and content is not None:
        reg = regmod.inner_region(cov, max(1.5, opts.gap_mm)) or regmod.between_region(cov, max(1.5, opts.gap_mm))
        if reg is None:
            design = content.render(1.0).centred()
            notes.append('Could not find the open space inside this frame file, so your design is centred on it.')
        else:
            design, n2 = _design_or_smaller(content, reg, log, status)
            notes += n2
    phases = [_phases(r.steps, info) for _, r, info in loaded]
    P = _interleave([p['P'] for p in phases])
    F = _interleave([p['F'] for p in phases])
    T = _interleave([p['T'] for p in phases])
    D = _interleave([p['D'] for p in phases])
    body = list(design.steps)
    if tag:
        if P and not F:
            F = [replace(s, label='Tack front cotton', name='Lay front cotton, sew tack line', stop_after=False)
                 for s in P]
        if P and not T:
            T = [replace(s, label='Tackdown', name='Flip: foam + back cotton, tackdown', stop_after=True) for s in P]
        P = [replace(s, label='Placement line', name='Placement line', stop_after=True) for s in P]
        F = [replace(s, stop_after=False) for s in F]
        if F:
            F[0] = replace(F[0], name='Lay front cotton, sew tack line')
        T = [replace(s, label='Tackdown', name='Flip: foam + back cotton, tackdown', stop_after=False) for s in T]
        if T:
            T[-1] = replace(T[-1], stop_after=True)
        if body:
            body[-1] = replace(body[-1], stop_after=True)
        elif F:
            F[-1] = replace(F[-1], stop_after=True)
        if D:
            D[0] = replace(D[0], name='Trim cotton, then dense satin')
            D = [replace(s, name=D[0].name) if s.colour == D[0].colour else s for s in D]
        steps = P + F + body + T + D
        guide = tags.guide(None, opts.tag_material, bool(body))
        notes.append('Your tag file "%s" (%s): placement, front cotton, your design, then (after you add the foam '
                     'and back cotton) the tackdown and the dense satin.' % (ff.name, size_label))
    else:
        guide = []
        has_appli = bool(T)
        if has_appli:
            steps = P + F + T + body + D
            notes.append('Your frame file "%s" (%s) with your design sewn after its tackdown and before its satin.'
                         % (ff.name, size_label))
        elif P:
            steps = P + F + body + D
        else:
            order = opts.design_order if opts.design_order in ('first', 'last') else 'last'
            steps = (body + D) if order == 'first' else (D + body)
            notes.append('Your frame file "%s" (%s) is sewn %s your design.'
                         % (ff.name, size_label, 'after' if order == 'first' else 'before'))
    notes.append('The frame file\'s own stitches are kept exactly as they are.')
    allsteps = P + F + T + D
    fabric = [(g, '#e8dcc4') for g in find_applique(P + T)] if (P and T) else []
    outer_cov = stepmod.coverage(allsteps)
    outline = unary_union([Polygon(p.exterior) for p in polys(outer_cov)]) if not outer_cov.is_empty else None
    res = Result(steps, fabric, notes + design.notes, 'tag' if tag else 'frame', outline, guide)
    return res if tag else with_knockdown(res, opts, log)


# ---------------------------------------------------------------- monograms from your letter files

def letters_result(lset, letters, layout, spacing_mm, colour=None, positions=None, big_set=None):
    """Monogram from letter stitch files. letters: (first, middle, last).
    classic: first and middle from lset (small), the last-name initial from big_set in the middle."""
    from .existing import read_stitch_file
    from . import library
    f, m, l = [(x or '').strip()[:1].upper() for x in letters]
    if layout == 'classic':
        seq = [(f, lset, 'left'), (l, big_set or lset, 'center'), (m, lset, 'right')]
    elif layout == 'single':
        seq = [((f or l or m), big_set or lset, 'center')]
    else:
        seq = [(f, lset, 'left'), (m, lset, 'center'), (l, lset, 'right')]
    seq = [(c, s, p) for c, s, p in seq if c]
    if not seq:
        raise ValueError('Type at least one initial.')
    parts, missing = [], []
    for c, s, pos in seq:
        path = library.letter_path(s, c, pos if s.positions else '')
        if not path:
            missing.append(c)
            continue
        steps = stepmod.steps_from_pattern(read_stitch_file(path), 'Letter %s' % c)
        if colour:
            steps = [type(x)(**{**x.__dict__, 'colour': colour}) for x in steps]
        parts.append(Result(steps, [], [], 'design'))
    if missing:
        raise ValueError('The %s set has no letter %s.' % (lset.font, ', '.join(missing)))
    if layout == 'stacked':
        res = stepmod.stack(parts, gap_mm=max(1.0, spacing_mm), align='center')
    else:
        items, x = [], 0.0
        for r in parts:
            w, h = r.size_mm()
            items.append((r, x + w / 2, 0.0, 1.0))
            x += w + spacing_mm
        res = stepmod.place(items)
    res.kind = 'monogram'
    res.notes.append('Monogram from your %s letter files (%s%s). Their stitches are kept exactly as they are.'
                     % (lset.font, lset.size_label or 'as saved',
                        (', big letter %s' % big_set.size_label) if big_set is not None and big_set is not lset else ''))
    return res
