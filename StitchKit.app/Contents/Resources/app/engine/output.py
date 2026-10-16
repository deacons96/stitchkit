"""Finish a piece: copies, basting box, stops, thread names, then write everything for it.

For each piece StitchKit writes the stitch files, a preview picture, a thread sheet, a placement
template to print at 100%, a Cricut cut file when there is appliqué fabric, and a small saved state so
your stops can be changed later without stitching everything again.
"""
import datetime
from dataclasses import replace
import html
import math
import pickle
from pathlib import Path

import pystitch
from PIL import Image, ImageDraw, ImageFont

from . import render, vip, hoops, threads
from .steps import Result, assemble, STOP_PREFIX
from .report import density_report

SPM = 650           # sewing speed used for the time estimate (stitches per minute)
CHANGE_MIN = 1.0    # minutes per thread change or stop (rethreading, laying and trimming fabric)
MAT_MM = 304.8      # Cricut 12 x 12 in mat
CUT_INSET = 0.3     # appliqué pieces are cut this much inside the placement line


def finish(single: Result, out_dir, base, formats=('vp3',), copies=1, basting=False, stops=(),
           brand='polyx40', margin=hoops.DEFAULT_MARGIN, spacing=hoops.COPY_SPACING, title='', size_text='',
           supplies=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stops = set(int(s) for s in stops)
    notes = list(single.notes)
    if copies > 1:
        res, hoop, placed, cnotes = hoops.layout_copies(single, copies, margin, spacing, stops)
        if res is None:
            raise ValueError(cnotes[0])
        notes += cnotes
        how = 'as is'
        steps = res.steps
    else:
        res = single.centred()
        steps = [s for s in res.steps]
        steps = [replace(s, stop_after=s.stop_after or i in stops, user_stop=i in stops) for i, s in enumerate(steps)]
        res = Result(steps, res.fabric, res.notes, res.kind, res.outline, list(getattr(res, 'guide', [])))
        w, h = res.size_mm()
        hoop, how = hoops.pick(w, h, margin)
        placed = 1
    if basting:
        steps = [hoops.basting_step(res, hoop, margin)] + steps
        notes.append('Basting box sewn first to hold fabric and stabilizer together; pull it out when you are done.')
    colours = []
    for s in steps:
        if s.colour not in colours:
            colours.append(s.colour)
    tnames = threads.names(colours, brand) if brand != 'none' else {}
    pattern, blocks = assemble(steps, (), tnames)
    st = render.stats(pattern)
    files = []
    for fmt in formats:
        f = out_dir / f'{base}.{fmt}'
        if fmt == 'vip':
            vip.write(pattern, str(f))
        else:
            pystitch.write(pattern, str(f))
            if fmt == 'vp3':
                assert render.stats(pystitch.read(str(f)))['stitches'] == st['stitches'], 'VP3 check failed'
        files.append(f.name)
    png = out_dir / f'{base}_preview.png'
    longest = max(st['width_mm'], st['height_mm'])
    render.render(pattern, str(png), ppmm=min(30, 1400 / max(longest, 1)), thread_mm=0.4, underlays=res.fabric)
    rep = density_report(pattern, st['stitches'])
    from .report import hotspots, density_map
    hot = hotspots(pattern)
    rep['hot'] = hot
    density_png = None
    if hot['danger'] >= 3 or hot['warn'] >= 40:
        density_png = out_dir / f'{base}_density.png'
        density_map(pattern, density_png, ppmm=min(14, 1000 / max(longest, 1)))
        if hot['danger'] >= 3:
            notes.append('About %d sq mm are very dense (12 or more needle points per sq mm), usually where satin '
                         'lines cross or sit on a fill. Open the density map to see where; if your needle '
                         'struggles there, use Light or a thinner border.' % hot['danger'])
    minutes = st['stitches'] / SPM + CHANGE_MIN * (len(blocks) - 1) + st['trims'] * 0.08
    hoop_text = (hoop['name'] + ('' if how == 'as is' else ', turned a quarter turn on the machine')) if hoop else \
        'too big for your hoops'
    matches = {c: threads.match(c, brand) for c in colours} if brand != 'none' else {}
    info = dict(title=title or base, size_text=size_text, w_mm=st['width_mm'], h_mm=st['height_mm'],
                stitches=st['stitches'], minutes=minutes, hoop=hoop_text, copies=placed, blocks=blocks,
                brand=threads.BRANDS.get(brand, ('',))[0], matches=matches, notes=notes, report=rep,
                trims=st['trims'], supplies=supplies or [])
    sheet = out_dir / f'{base}_thread_sheet.html'
    sheet.write_text(thread_sheet(info, png.name))
    files.append(sheet.name)
    tpl = out_dir / f'{base}_template.pdf'
    template_pdf(pattern, res, tpl, title or base, hoop, margin)
    files.append(tpl.name)
    cut = []
    if res.fabric:
        cut = cricut_svgs(res.fabric, out_dir, base)
        files += cut
        notes.append('Cricut cut file%s: %s. Upload to Design Space and check the size before cutting; it sometimes '
                     'resizes SVGs. Each piece is cut %.1f mm inside the placement line.'
                     % ('s' if len(cut) > 1 else '', ', '.join(cut), CUT_INSET))
    state_dir = out_dir / '.stitchkit'
    state_dir.mkdir(exist_ok=True)
    with open(state_dir / f'{base}.pkl', 'wb') as f:
        pickle.dump(dict(single=single, formats=list(formats), copies=copies, basting=basting, brand=brand,
                         margin=margin, spacing=spacing, title=title, size_text=size_text, supplies=supplies), f)
    return dict(files=files, preview=png.name, density=density_png.name if density_png else None,
                stats=st, report=rep, notes=notes, hoop=hoop_text,
                hoop_key=hoop['key'] if hoop else None, copies=placed, minutes=round(minutes),
                blocks=[dict(b, match=matches.get(b['colour'])) for b in blocks],
                steps=[dict(i=i, label=s.label, colour=s.colour, stitches=sum(1 for p in s.stitches if p[2] == 0),
                            auto_stop=s.stop_after, stop=i in stops) for i, s in enumerate(single.steps)],
                stops=sorted(stops), w_mm=round(st['width_mm'], 1), h_mm=round(st['height_mm'], 1),
                piece_mm=[round(x, 1) for x in single.size_mm()],
                capacity=hoops.capacity(*single.size_mm(), margin), supplies=supplies or [])


def refinish(out_dir, base, stops):
    """Write a piece again with different stops (no re-stitching)."""
    with open(Path(out_dir) / '.stitchkit' / f'{base}.pkl', 'rb') as f:
        s = pickle.load(f)
    return finish(s['single'], out_dir, base, s['formats'], s['copies'], s['basting'], stops, s['brand'],
                  s['margin'], s['spacing'], s['title'], s['size_text'], s.get('supplies'))


# ---------------------------------------------------------------- thread sheet

def thread_sheet(info, preview_name):
    e = html.escape
    rows = []
    for n, b in enumerate(info['blocks'], 1):
        m = info['matches'].get(b['colour'])
        thread = ('%s %s' % (m['number'], e(m['name']))) if m else ''
        stop = ''
        if n > 1 and info['blocks'][n - 2]['colour'] == b['colour']:
            stop = 'Machine stops first (same thread)'
        what = e(b['name']) if b['name'] and not b['name'].startswith('#') else ''
        rows.append('<tr><td>%d</td><td><span class="sw" style="background:%s"></span>%s</td>'
                    '<td>%s</td><td>%s</td><td>%s</td><td class="n">%s</td><td>%s</td></tr>'
                    % (n, b['colour'], b['colour'], (('<span class="sw" style="background:%s"></span>' % m['hex']) + thread) if m else '<i>—</i>',
                       e(', '.join(b['steps'])), what, '{:,}'.format(b['stitches']), stop))
    mins = info['minutes']
    t = '%d min' % round(mins) if mins < 60 else '%d h %02d min' % (mins // 60, round(mins % 60))
    notes = ''.join('<li>%s</li>' % e(n) for n in info['notes'])
    return """<!doctype html><html><head><meta charset="utf-8"><title>%(title)s thread sheet</title>
<style>
body{font:14px -apple-system,Helvetica,Arial,sans-serif;color:#222;margin:28px;max-width:900px}
h1{font-size:22px;margin:0 0 4px} .sub{color:#666;margin-bottom:16px}
.top{display:flex;gap:24px;align-items:flex-start} .top img{max-width:280px;max-height:280px;border:1px solid #ddd;border-radius:6px}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:0} dt{color:#666} dd{margin:0;font-weight:600}
table{border-collapse:collapse;width:100%%;margin-top:18px} th,td{border-bottom:1px solid #e3e3e3;padding:6px 8px;text-align:left;vertical-align:top}
th{font-size:12px;color:#666;text-transform:uppercase;letter-spacing:.04em} td.n{text-align:right}
.sw{display:inline-block;width:16px;height:16px;border-radius:3px;border:1px solid #0003;vertical-align:-3px;margin-right:6px}
ul{padding-left:18px} dl.sup{grid-template-columns:120px 1fr} dl.sup dd{font-weight:400} .foot{color:#888;font-size:12px;margin-top:20px}
@media print{body{margin:10mm}}
</style></head><body>
<h1>%(title)s</h1><div class="sub">StitchKit thread sheet, %(date)s</div>
<div class="top"><img src="%(png)s" alt="">
<dl><dt>Size</dt><dd>%(size)s</dd><dt>Hoop</dt><dd>%(hoop)s</dd><dt>Copies</dt><dd>%(copies)d</dd>
<dt>Stitches</dt><dd>%(stitches)s</dd><dt>Thread blocks</dt><dd>%(nblocks)d</dd><dt>Trims</dt><dd>%(trims)d</dd>
<dt>Sewing time</dt><dd>about %(time)s</dd><dt>Density</dt><dd>%(dens)s per covered sq in</dd>
<dt>Threads</dt><dd>%(brand)s</dd></dl></div>
<table><tr><th>#</th><th>Design colour</th><th>Closest thread</th><th>Sews</th><th>Machine shows</th><th>Stitches</th><th>Stop</th></tr>
%(rows)s</table>
%(supplies)s<h3>Notes</h3><ul>%(notes)s</ul>
<div class="foot">Time is an estimate at about %(spm)d stitches a minute plus a minute for each thread change or stop.
Closest thread is matched by screen colour: check it against your real thread.</div>
</body></html>""" % dict(title=e(info['title']), date=datetime.date.today().strftime('%B %d, %Y'), png=e(preview_name),
                         size=e('%.2f x %.2f in (%.0f x %.0f mm)' % (info['w_mm'] / 25.4, info['h_mm'] / 25.4,
                                                                    info['w_mm'], info['h_mm'])),
                         hoop=e(info['hoop']), copies=info['copies'], stitches='{:,}'.format(info['stitches']),
                         nblocks=len(info['blocks']), trims=info['trims'], time=t,
                         dens='{:,}'.format(info['report']['per_sq_in']), brand=e(info['brand'] or 'not matched'),
                         rows='\n'.join(rows), notes=notes, spm=SPM,
                         supplies=('<h3>You will need</h3><dl class="sup">' + ''.join(
                             '<dt>%s</dt><dd>%s</dd>' % (e(a), e(b)) for a, b in info['supplies']) + '</dl>')
                         if info.get('supplies') else '')


# ---------------------------------------------------------------- placement template

def _font(px):
    for name in ('/System/Library/Fonts/Helvetica.ttc', '/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def template_pdf(pattern, res: Result, path, title, hoop, margin, dpi=300):
    """Actual-size printout: the design in light grey, its outline, crosshairs through the centre (where the
    machine's needle starts) and a 1 inch / 25 mm check square. Big designs are split over several pages
    with matching marks."""
    pxmm = dpi / 25.4
    m_px = int(0.4 * dpi)
    head, foot = int(0.75 * dpi), int(1.6 * dpi)
    bl = render.blocks(pattern)
    xs = [p[0] for _, pts in bl for p in pts]
    ys = [p[1] for _, pts in bl for p in pts]
    x0, y0, x1, y1 = min(xs + [0]) - 12, min(ys + [0]) - 12, max(xs + [0]) + 12, max(ys + [0]) + 12
    W, H = (x1 - x0) * pxmm, (y1 - y0) * pxmm
    best = None
    for pw, ph in ((8.5 * dpi, 11 * dpi), (11 * dpi, 8.5 * dpi)):      # portrait or landscape letter
        aw, ah = pw - 2 * m_px, ph - 2 * m_px - head - foot
        n = max(1, math.ceil(W / aw)) * max(1, math.ceil(H / ah))
        if best is None or n < best[0]:
            best = (n, pw, ph, aw, ah)
    _, page_w, page_h, area_w, area_h = best
    cols, rows = max(1, math.ceil(W / area_w)), max(1, math.ceil(H / area_h))
    big = Image.new('L', (int(W) + 1, int(H) + 1), 255)
    d = ImageDraw.Draw(big)
    P = lambda x, y: ((x - x0) * pxmm, (y - y0) * pxmm)
    for _, pts in bl:
        d.line([P(*p) for p in pts], fill=200, width=2)
    if res.outline is not None:
        for g in getattr(res.outline, 'geoms', [res.outline]):
            for ring in [g.exterior] + list(g.interiors):
                d.line([P(*c) for c in ring.coords], fill=40, width=5)
    # crosshairs through the centre of the design (the hoop centre)
    cx, cy = P(0, 0)
    d.line([(0, cy), (big.width, cy)], fill=0, width=3)
    d.line([(cx, 0), (cx, big.height)], fill=0, width=3)
    for k in range(-400, 401, 10):
        tx, ty = P(k, 0)
        if 0 <= tx < big.width:
            d.line([(tx, cy - (24 if k % 50 == 0 else 12)), (tx, cy + (24 if k % 50 == 0 else 12))], fill=0, width=2)
        tx, ty = P(0, k)
        if 0 <= ty < big.height:
            d.line([(cx - (24 if k % 50 == 0 else 12), ty), (cx + (24 if k % 50 == 0 else 12), ty)], fill=0, width=2)
    d.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], outline=0, width=3)
    pages = []
    f_big, f_small = _font(int(0.16 * dpi)), _font(int(0.11 * dpi))
    for r in range(rows):
        for c in range(cols):
            pg = Image.new('L', (int(page_w), int(page_h)), 255)
            pd = ImageDraw.Draw(pg)
            crop = big.crop((int(c * area_w), int(r * area_h), int(min(W, (c + 1) * area_w)) + 1,
                             int(min(H, (r + 1) * area_h)) + 1))
            pg.paste(crop, (m_px, m_px + head))
            pd.text((m_px, m_px), title, fill=0, font=f_big)
            sub = 'Placement template. Print at 100% / Actual size (no "fit to page").'
            if cols * rows > 1:
                sub += '  Page %d of %d (row %d, column %d): trim and tape the pages together.' % (
                    r * cols + c + 1, cols * rows, r + 1, c + 1)
            pd.text((m_px, m_px + int(0.24 * dpi)), sub, fill=0, font=f_small)
            # check squares: 1 inch and 25 mm, along the bottom
            sy = int(page_h - m_px - foot + 0.25 * dpi)
            sx = m_px
            pd.rectangle([sx, sy, sx + dpi, sy + dpi], outline=0, width=3)
            pd.text((sx + 8, sy + 8), '1 inch', fill=0, font=f_small)
            s2 = int(sx + 1.3 * dpi)
            pd.rectangle([s2, sy, s2 + 25 * pxmm, sy + 25 * pxmm], outline=0, width=3)
            pd.text((s2 + 8, sy + 8), '25 mm', fill=0, font=f_small)
            pd.text((int(s2 + 25 * pxmm + 0.3 * dpi), sy + 8),
                    'Line up the cross with the centre marks on your hoop template.\n'
                    'Measure the squares to check the printer kept the scale.', fill=0, font=f_small)
            pages.append(pg.convert('RGB'))
    pages[0].save(str(path), 'PDF', resolution=dpi, save_all=True, append_images=pages[1:])
    return len(pages)


# ---------------------------------------------------------------- Cricut cut file

def _svg_path(g, dx, dy):
    d = []
    for p in getattr(g, 'geoms', [g]):
        if p.is_empty or p.geom_type != 'Polygon':
            continue
        for ring in [p.exterior] + list(p.interiors):
            c = list(ring.coords)[:-1]
            d.append('M' + ' L'.join('%.3f,%.3f' % (x + dx, y + dy) for x, y in c) + ' Z')
    return ' '.join(d)


def cricut_svgs(fabric, out_dir, base, gap=6.0, edge=10.0):
    """Appliqué pieces at exact size on 12 x 12 in mats (one SVG per mat), packed in rows."""
    from .art import clean
    pieces = []
    for poly, colour in fabric:
        for p in getattr(poly, 'geoms', [poly]):
            g = clean(p.buffer(-CUT_INSET, join_style=2))
            if not g.is_empty and g.area > 4:
                pieces.append((g, colour))
    pieces.sort(key=lambda pc: -(pc[0].bounds[3] - pc[0].bounds[1]))
    usable = MAT_MM - 2 * edge
    mats, cur = [], []
    x = y = row_h = 0.0
    for g, colour in pieces:
        b = g.bounds
        w, h = b[2] - b[0], b[3] - b[1]
        if w > usable or h > usable:
            raise ValueError('An appliqué piece is bigger than a 12 x 12 in Cricut mat.')
        if x + w > usable:
            x, y, row_h = 0.0, y + row_h + gap, 0.0
        if y + h > usable:
            mats.append(cur)
            cur, x, y, row_h = [], 0.0, 0.0, 0.0
        cur.append((g, colour, edge + x - b[0], edge + y - b[1]))
        x += w + gap
        row_h = max(row_h, h)
    if cur:
        mats.append(cur)
    names = []
    for i, mat in enumerate(mats, 1):
        paths = '\n'.join('  <path d="%s" fill="%s" fill-opacity="0.35" fill-rule="evenodd" stroke="#000" '
                          'stroke-width="0.2"/>' % (_svg_path(g, dx, dy), colour) for g, colour, dx, dy in mat)
        svg = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<svg xmlns="http://www.w3.org/2000/svg" width="304.8mm" height="304.8mm" viewBox="0 0 304.8 304.8">\n'
               '<!-- StitchKit appliqué pieces, actual size, 12 x 12 in mat. -->\n%s\n</svg>\n' % paths)
        name = '%s_cricut%s.svg' % (base, '' if len(mats) == 1 else '_mat%d' % i)
        (Path(out_dir) / name).write_text(svg)
        names.append(name)
    return names
