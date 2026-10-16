"""Turn a plan into stitch files: Ink/Stitch does the stitching, we check and export the result."""
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import etree
import pystitch
from shapely.geometry import LineString

from . import vip, render
from .art import polys, load
from .plan import Options, plan_design

INK = 'http://inkstitch.org/namespace'
SVG = 'http://www.w3.org/2000/svg'
HERE = Path(__file__).resolve().parent

FORMATS = ['vp3', 'vip', 'pes', 'dst', 'jef', 'exp']


def ascii_name(s):
    """Machine files store thread names as plain bytes: keep them plain ASCII and short."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    return s[:60]


def _d_poly(poly):
    def ring(r):
        c = list(r.coords)
        return 'M' + ' L'.join('%.3f,%.3f' % (x, y) for x, y in c[:-1]) + ' Z'
    return ' '.join([ring(poly.exterior)] + [ring(i) for i in poly.interiors])


def _d_line(ls):
    c = list(ls.coords)
    closed = c[0] == c[-1]
    return 'M' + ' L'.join('%.3f,%.3f' % (x, y) for x, y in (c[:-1] if closed else c)) + (' Z' if closed else '')


def write_svg(objs, path, no_lock_colours=()):
    xs, ys = [], []
    for o in objs:
        if o.poly is not None:
            b = o.poly.bounds
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        for s in o.seqs:
            if o.kind == 'satin':
                s = [p for sub in s[:2] for p in sub]
            xs += [p[0] for p in s]
            ys += [p[1] for p in s]
        for l in o.lines:
            b = l.bounds
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
    x0, y0, x1, y1 = min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3
    root = etree.Element('{%s}svg' % SVG, nsmap={None: SVG, 'inkstitch': INK})
    root.set('width', '%.3fmm' % (x1 - x0))
    root.set('height', '%.3fmm' % (y1 - y0))
    root.set('viewBox', '%.3f %.3f %.3f %.3f' % (x0, y0, x1 - x0, y1 - y0))
    md = etree.SubElement(root, '{%s}metadata' % SVG)
    etree.SubElement(md, '{%s}inkstitch_svg_version' % INK).text = '4'
    # don't let the engine sew over gaps between pieces by itself (it would cross other colours);
    # StitchKit decides which hops are short enough to sew and trims the rest
    etree.SubElement(md, '{%s}collapse_len_mm' % INK).text = '0.8'
    g = etree.SubElement(root, '{%s}g' % SVG)
    g.set('id', 'layer1')
    n = 0

    def add(d, style, params, last_of_obj=True, o=None):
        nonlocal n
        n += 1
        e = etree.SubElement(g, '{%s}path' % SVG)
        e.set('id', 'o%d' % n)
        e.set('d', d)
        e.set('style', style)
        for k, v in params.items():
            if k.startswith('_'):
                continue
            e.set('{%s}%s' % (INK, k), str(v))
        if params.get('_trim', False):
            e.set('{%s}trim_after' % INK, 'True')

    for o in objs:
        if o.kind == 'fill':
            add(_d_poly(o.poly), 'fill:%s;fill-rule:evenodd;stroke:none' % o.colour, o.params, o=o)
        elif o.kind == 'manual':
            lock = {} if o.colour in no_lock_colours else {'force_lock_stitches': 'True'}
            for i, s in enumerate(o.seqs):
                add('M' + ' L'.join('%.3f,%.3f' % p for p in s), 'fill:none;stroke:%s;stroke-width:0.2' % o.colour,
                    {'stroke_method': 'manual_stitch', **lock},
                    last_of_obj=i == len(o.seqs) - 1, o=o)
        elif o.kind == 'satin':
            # real Ink/Stitch satin columns: each entry is [outer rail, inner rail, rung, rung, ...]
            for col in o.seqs:
                d = ' '.join('M' + ' L'.join('%.3f,%.3f' % tuple(p) for p in sub) for sub in col)
                add(d, 'fill:none;stroke:%s;stroke-width:0.2' % o.colour, {'satin_column': 'True', **o.params}, o=o)
        elif o.kind in ('run', 'zigzag'):
            p = dict(o.params)
            if o.kind == 'zigzag':
                p['stroke_method'] = 'zigzag_stitch'
            for i, l in enumerate(o.lines):
                add(_d_line(l), 'fill:none;stroke:%s;stroke-width:0.2' % o.colour, p,
                    last_of_obj=i == len(o.lines) - 1, o=o)
    etree.ElementTree(root).write(str(path), xml_declaration=True, encoding='utf-8')


def run_inkstitch(svg_path, out_path, log):
    cmd = [sys.executable, str(HERE / 'run_inkstitch.py'), '--extension=output', '--format=vp3', str(svg_path)]
    with open(out_path, 'wb') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=1800)
    err = r.stderr.decode(errors='replace').strip()
    if err:
        log.append(err[-3000:])
    if not Path(out_path).exists() or Path(out_path).stat().st_size < 100:
        raise RuntimeError('The stitch engine did not produce a file.\n' + err[-1500:])


def fix_long(p, limit_tenths):
    """Ink/Stitch now and then sews a long travel line inside a fill. Replace any such stitch with a
    tie-off, trim, jump and tie-in."""
    S = pystitch.STITCH
    out, n, st = [], 0, p.stitches
    for i, s in enumerate(st):
        if i and s[2] & 0xFF == S and st[i - 1][2] & 0xFF == S and \
                math.hypot(s[0] - st[i - 1][0], s[1] - st[i - 1][1]) > limit_tenths:
            a, b = st[i - 1], s
            pa = st[i - 2] if i > 1 and st[i - 2][2] & 0xFF == S else a
            nb = st[i + 1] if i + 1 < len(st) and st[i + 1][2] & 0xFF == S else b

            def toward(u, v, d=6):
                L = math.hypot(v[0] - u[0], v[1] - u[1]) or 1
                return [u[0] + (v[0] - u[0]) * min(d, L) / L, u[1] + (v[1] - u[1]) * min(d, L) / L, S]
            out += [toward(a, pa), [a[0], a[1], S], toward(a, pa), [a[0], a[1], S],
                    [a[0], a[1], pystitch.TRIM], [b[0], b[1], pystitch.JUMP],
                    [b[0], b[1], S], toward(b, nb), [b[0], b[1], S], toward(b, nb)]
            n += 1
        out.append(s)
    p.stitches = out
    return n


def fabric_underlays(objs, p):
    """Appliqué fabric for the preview. Ink/Stitch centres its output, so line the plan up with the
    stitches by their outer bounds."""
    fab = [o for o in objs if o.kind == 'fabric']
    if not fab:
        return []
    from shapely import affinity
    from shapely.ops import unary_union
    plan = unary_union([o.poly for o in objs if o.poly is not None] +
                       [LineString(s) for o in objs for s in o.seqs if len(s) > 1])
    st = [s for s in p.stitches if s[2] & 0xFF == pystitch.STITCH]
    sx = [s[0] / 10.0 for s in st]
    sy = [s[1] / 10.0 for s in st]
    pb = plan.bounds
    dx = (min(sx) + max(sx)) / 2 - (pb[0] + pb[2]) / 2
    dy = (min(sy) + max(sy)) / 2 - (pb[1] + pb[3]) / 2
    return [(affinity.translate(o.poly, dx, dy), o.colour) for o in fab]


def max_satin_width(objs):
    w = 0
    for o in objs:
        if o.kind == 'manual':
            for s in o.seqs:
                tail = s[-200:]
                for a, b in zip(tail[::2], tail[1::2]):
                    w = max(w, math.hypot(b[0] - a[0], b[1] - a[1]))
    return w


def digitize(art, opts: Options, out_dir, base_name, formats=('vp3', 'vip'), preview=True, log=None):
    log = log if log is not None else []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    objs, notes = plan_design(art, opts)
    with tempfile.TemporaryDirectory() as tmp:
        svg = Path(tmp) / 'plan.svg'
        write_svg(objs, svg)
        raw = Path(tmp) / 'raw.vp3'
        run_inkstitch(svg, raw, log)
        p = pystitch.read(str(raw))
    names = {}
    for o in objs:
        names.update(o.params.get('_names', {}))
    for t in p.threadlist:
        hx = '#%02x%02x%02x' % (t.get_red(), t.get_green(), t.get_blue())
        t.description = ascii_name(names.get(hx, hx))
        t.catalog_number = ''
    limit = max(80, int(10 * (1.6 * max_satin_width(objs) + 1.5)))
    repaired = fix_long(p, limit)
    st = render.stats(p)
    files = []
    for fmt in formats:
        f = out_dir / f'{base_name}.{fmt}'
        if fmt == 'vip':
            vip.write(p, str(f))
            cols, recs, ext = vip.read(str(f))
            got = [(x, y) for c, x, y in recs if c == 0x80]
            assert len(got) == st['stitches'], 'VIP check failed'
        else:
            pystitch.write(p, str(f))
            q = pystitch.read(str(f))
            if fmt == 'vp3':
                assert render.stats(q)['stitches'] == st['stitches'], 'VP3 check failed'
        files.append(f)
    png = None
    if preview:
        png = out_dir / f'{base_name}_preview.png'
        longest = max(st['width_mm'], st['height_mm'])
        render.render(p, str(png), ppmm=min(30, 1400 / max(longest, 1)), thread_mm=0.4,
                      underlays=fabric_underlays(objs, p))
    if repaired:
        notes.append('%d long travel stitch(es) converted to trims.' % repaired)
    from .report import density_report
    rep = density_report(p, st['stitches'])
    return dict(files=files, preview=png, stats=st, notes=notes, objects=len(objs), report=rep, pattern=p)
