"""Stitch-count check against the usual patch guideline (about 1,500 stitches per covered square inch)."""
GUIDE_PER_SQ_IN = 1500


def density_report(pattern, stitches):
    from .existing import coverage
    cov = coverage(pattern)
    sq_in = cov.area / 645.16
    guide = GUIDE_PER_SQ_IN * sq_in
    ratio = stitches / guide if guide else 0
    if ratio > 1.3:
        verdict = 'dense'
        text = ('About %d%% over the usual guide. Fine for heavy fabric; if your machine struggles, use Light.'
                % round(100 * (ratio - 1)))
    elif ratio < 0.7:
        verdict = 'light'
        text = 'Lighter than the usual guide. Fine on patches and smooth fabric; on fleece or towels try Normal or Dense.'
    else:
        verdict = 'typical'
        text = 'Right in the usual range.'
    return dict(covered_sq_in=round(sq_in, 2), per_sq_in=round(stitches / sq_in) if sq_in else 0,
                guide=round(guide, -2), verdict=verdict, text=text)


WARN_PER_MM2 = 8.0     # needle points per square mm (averaged over 2 x 2 mm)
DANGER_PER_MM2 = 12.0


def density_grid(pattern, cell=1.0):
    """Needle points per square mm on a 1 mm grid, smoothed over 2 x 2 mm. Returns (grid, x0, y0)."""
    import numpy as np
    pts = np.array([(s[0] / 10.0, s[1] / 10.0) for s in pattern.stitches if s[2] & 0xFF == 0])
    if not len(pts):
        return None, 0, 0
    x0, y0 = pts.min(0) - 2
    ij = ((pts - [x0, y0]) // cell).astype(int)
    H, W = ij[:, 1].max() + 3, ij[:, 0].max() + 3
    g = np.zeros((H, W))
    np.add.at(g, (ij[:, 1], ij[:, 0]), 1)
    s = g.copy()
    s[:-1, :] += g[1:, :]
    s[:, :-1] += g[:, 1:]
    s[:-1, :-1] += g[1:, 1:]
    return s / 4.0 / (cell * cell), x0, y0


def hotspots(pattern):
    g, _, _ = density_grid(pattern)
    if g is None:
        return dict(warn=0, danger=0, peak=0)
    return dict(warn=int((g >= WARN_PER_MM2).sum()), danger=int((g >= DANGER_PER_MM2).sum()), peak=round(float(g.max()), 1))


def density_map(pattern, out_png, ppmm=10):
    """The design faded, with dense spots marked: orange is dense, red is very dense."""
    import numpy as np
    from PIL import Image, ImageDraw
    from . import render
    g, gx0, gy0 = density_grid(pattern)
    tmp = str(out_png) + '.base.png'
    render.render(pattern, tmp, ppmm=ppmm, thread_mm=0.35, pad_mm=3)
    base = Image.open(tmp).convert('RGB')
    import os
    os.remove(tmp)
    bl = render.blocks(pattern)
    xs = [p[0] for _, pts in bl for p in pts]
    ys = [p[1] for _, pts in bl for p in pts]
    rx0, ry0 = min(xs) - 3, min(ys) - 3
    faded = Image.blend(base, Image.new('RGB', base.size, (235, 235, 235)), 0.6)
    over = Image.new('RGBA', base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for (r, c), v in np.ndenumerate(g):
        if v < WARN_PER_MM2:
            continue
        x, y = (gx0 + c - rx0) * ppmm, (gy0 + r - ry0) * ppmm
        col = (220, 30, 30, 200) if v >= DANGER_PER_MM2 else (245, 150, 20, 170)
        d.rectangle([x, y, x + ppmm * 1.5, y + ppmm * 1.5], fill=col)
    faded.paste(over, (0, 0), over)
    faded.save(out_png)
