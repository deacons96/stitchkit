"""Stitched text.

Two kinds of font:
  * embroidery fonts: hand-digitized satin lettering from the Ink/Stitch font library (best quality)
  * computer fonts: any TrueType/OpenType font on the Mac, turned into stitches automatically

Each line is stitched on its own (its own font, size, arch and spacing), then the lines, and
optionally an artwork, are stacked into one design.
"""
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pystitch
from pystitch import STITCH, JUMP, TRIM
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from shapely import affinity

from .art import polys, clean, rings_to_geom
from .build import HERE, write_svg, run_inkstitch, fix_long, max_satin_width
from .existing import blocks, assemble, thread_hex
from .plan import Obj, Options, fill_params, thicken, nearest_order
from .satin import satin_edge

FONT_ROOT = HERE.parent / 'inkstitch_engine' / 'fonts' / 'src'
USER_FONT_ROOT = Path.home() / '.stitchkit' / 'embroidery-fonts'
SYSTEM_FONT_DIRS = ['/System/Library/Fonts', '/System/Library/Fonts/Supplemental', '/Library/Fonts',
                    str(Path.home() / 'Library' / 'Fonts'), '/usr/share/fonts']


@dataclass
class Line:
    text: str
    font: str                       # 'emb:<folder>' or 'sys:<path>#<index>'
    height_mm: float = 12.0         # height of capital letters
    arch: float = 0.0               # -100 .. 100: + arches up like a rainbow, - curves down like a smile
    spacing_mm: float = 0.0         # extra space between letters
    colour: str = '#151011'
    position: str = 'above'         # above / below the artwork, when there is one
    notes: list = field(default_factory=list)


# ------------------------------------------------------------------ font lists

def embroidery_fonts():
    out = []
    roots = [FONT_ROOT, USER_FONT_ROOT / 'src']
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            j = d / 'font.json'
            if not j.exists() or d.name in seen:
                continue
            try:
                meta = json.loads(j.read_text())
            except Exception:
                continue
            kw = meta.get('keywords', [])
            if 'latin' not in kw or any(k in kw for k in ('crossstitch', 'multicolor', 'applique')):
                continue
            size = float(meta.get('size') or 20)
            out.append(dict(id='emb:' + d.name, name=meta.get('name', d.name), folder=str(d),
                            min_mm=round(size * float(meta.get('min_scale', 1)), 1),
                            max_mm=round(size * float(meta.get('max_scale', 1)), 1),
                            size_mm=size, style=_style(kw), preview=str(d / 'preview.png')))
            seen.add(d.name)
    out.sort(key=lambda f: (f['style'], f['name'].lower()))
    return out


def _style(kw):
    if 'handwriting' in kw or 'italic' in kw:
        return 'Script'
    if 'serif' in kw:
        return 'Serif'
    if 'display' in kw or 'monogram' in kw:
        return 'Display'
    return 'Sans'


def system_fonts():
    """Computer fonts (TrueType/OpenType), cached because reading hundreds of fonts takes a moment."""
    cache = Path.home() / '.stitchkit' / 'system_fonts.json'
    files = []
    for d in SYSTEM_FONT_DIRS:
        if os.path.isdir(d):
            for dp, _, fs in os.walk(d):
                files += [os.path.join(dp, f) for f in fs if f.lower().endswith(('.ttf', '.otf', '.ttc'))]
    key = len(files), sum(int(os.path.getmtime(f)) for f in files) if files else 0
    try:
        c = json.loads(cache.read_text())
        if c.get('key') == list(key):
            return c['fonts']
    except Exception:
        pass
    from fontTools.ttLib import TTFont, TTCollection
    fonts = []
    for f in files:
        try:
            if f.lower().endswith('.ttc'):
                faces = TTCollection(f, lazy=True).fonts
            else:
                faces = [TTFont(f, lazy=True)]
            for i, tt in enumerate(faces):
                if 'glyf' not in tt and 'CFF ' not in tt:
                    continue
                name = tt['name'].getBestFullName() or Path(f).stem
                if name.startswith('.'):
                    continue
                fonts.append(dict(id='sys:%s#%d' % (f, i), name=name))
        except Exception:
            continue
    uniq = {}
    for f in fonts:
        uniq.setdefault(f['name'], f)
    fonts = sorted(uniq.values(), key=lambda f: f['name'].lower())
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(dict(key=list(key), fonts=fonts)))
    except Exception:
        pass
    return fonts


# ------------------------------------------------------------------ embroidery fonts

def _emb_meta(folder):
    return json.loads((Path(folder) / 'font.json').read_text())


def _arc_path(width_mm, arch, pad=1.6):
    """An arc (in mm) long enough for the text, bending by `arch` percent of a half circle."""
    theta = abs(arch) / 100.0 * math.pi
    R = width_mm / theta
    span = min(theta * pad, 2 * math.pi * 0.95)
    pts = []
    for i in range(121):
        phi = -span / 2 + span * i / 120
        x = R * math.sin(phi)
        y = R - R * math.cos(phi)
        pts.append((x + 150, (y if arch > 0 else -y) + 150))
    return 'M' + ' L'.join('%.3f,%.3f' % p for p in pts)


def _run_batch(text, font_name, scale_pct, spacing_mm, path_d=None):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkstitch="http://inkstitch.org/namespace" '
           'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="300mm" height="300mm" '
           'viewBox="0 0 300 300"><metadata><inkstitch:inkstitch_svg_version>4</inkstitch:inkstitch_svg_version>'
           '</metadata><g id="layer1">%s</g></svg>')
    path = ''
    if path_d:
        path = ('<path id="arc" inkscape:label="batch lettering" d="%s" '
                'style="fill:none;stroke:#000000;stroke-width:0.3"/>' % path_d)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'in.svg'
        src.write_text(svg % path)
        cmd = [sys.executable, str(HERE / 'run_inkstitch.py'), '--extension=batch_lettering',
               '--text=' + text, '--font=' + font_name, '--scale=%d' % round(scale_pct),
               '--file-formats=vp3', '--text-align=center', '--trim=glyph',
               '--letter_spacing=%.2f' % spacing_mm, '--text-position=center',
               '--vertical-text-position=baseline', str(src)]
        r = subprocess.run(cmd, capture_output=True, timeout=900)
        if not r.stdout[:2] == b'PK':
            raise RuntimeError('Lettering failed: ' + r.stderr.decode(errors='replace')[-600:])
        z = zipfile.ZipFile(io.BytesIO(r.stdout))
        name = [n for n in z.namelist() if n.endswith('.vp3')][0]
        out = Path(tmp) / 'line.vp3'
        out.write_bytes(z.read(name))
        return pystitch.read(str(out))


def _width_mm(p):
    xs = [s[0] for s in p.stitches if s[2] & 0xFF == STITCH]
    return (max(xs) - min(xs)) / 10.0 if xs else 0


def emb_line(line: Line):
    folder = line.font.split(':', 1)[1]
    d = FONT_ROOT / folder
    if not d.exists():
        d = USER_FONT_ROOT / 'src' / folder
    meta = _emb_meta(d)
    size = float(meta.get('size') or 20)
    scale = line.height_mm / size
    lo, hi = float(meta.get('min_scale', 0.5)), float(meta.get('max_scale', 2))
    if scale < lo or scale > hi:
        scale = min(hi, max(lo, scale))
        line.notes.append('%s works between %.0f and %.0f mm tall, so "%s" was set at %.0f mm.'
                          % (meta.get('name'), size * lo, size * hi, line.text, size * scale))
    p = _run_batch(line.text, meta['name'], scale * 100, line.spacing_mm)
    if abs(line.arch) >= 3:
        p = arch_pattern(p, line.arch)
    return recolour(p, line.colour)


def arch_pattern(p, arch):
    """Bend finished lettering round an arc. Each letter is moved and turned as one rigid piece, so its
    stitches stay exactly as digitized. + arches up like a rainbow, - curves down like a smile."""
    st = [list(s) for s in p.stitches]
    # chunks of sewing separated by trims/jumps
    chunks, cur = [], []
    owner = [None] * len(st)
    for i, (x, y, c) in enumerate(st):
        if c & 0xFF == STITCH:
            cur.append(i)
        elif cur and c & 0xFF in (TRIM, JUMP):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    # chunks that overlap left-to-right belong to the same letter (the dot on an i, etc.)
    spans = []
    for ch in chunks:
        xs = [st[i][0] for i in ch]
        spans.append([min(xs), max(xs), list(ch)])
    spans.sort(key=lambda s: s[0])
    letters = []
    for s in spans:
        if letters and s[0] < letters[-1][1] - 2:
            letters[-1][1] = max(letters[-1][1], s[1])
            letters[-1][2] += s[2]
        else:
            letters.append(s)
    if len(letters) < 2:
        return p
    for k, (_, _, idx) in enumerate(letters):
        for i in idx:
            owner[i] = k
    nxt = None
    for i in range(len(st) - 1, -1, -1):           # commands follow the letter that comes next
        if owner[i] is None:
            owner[i] = nxt
        else:
            nxt = owner[i]
    bottoms = sorted(max(st[i][1] for i in idx) for _, _, idx in letters)
    baseline = bottoms[len(bottoms) // 2]
    x0 = min(l[0] for l in letters)
    x1 = max(l[1] for l in letters)
    mid = (x0 + x1) / 2
    theta = abs(arch) / 100.0 * math.pi
    R = (x1 - x0) / theta
    sign = 1 if arch > 0 else -1
    frames = []
    for lo, hi, idx in letters:
        gc = (lo + hi) / 2
        phi = (gc - mid) / R
        a = sign * phi
        frames.append((gc, math.cos(a), math.sin(a), R * math.sin(phi), sign * (R - R * math.cos(phi))))
    for i, s in enumerate(st):
        k = owner[i]
        if k is None:
            continue
        gc, ca, sa, tx, ty = frames[k]
        x, y = s[0] - gc, s[1] - baseline
        s[0] = x * ca - y * sa + tx + mid
        s[1] = x * sa + y * ca + ty + baseline
    p.stitches = st
    return p


def recolour(p, colour):
    """Single-colour lettering takes the colour you picked."""
    for t in p.threadlist:
        t.set_hex_color(colour)
        t.description = colour
    return p


# ------------------------------------------------------------------ computer fonts

class _FlatPen:
    """fontTools pen that flattens outlines into point rings."""

    def __init__(self, glyphset, steps=8):
        self.rings, self.cur, self.glyphSet, self.steps = [], [], glyphset, steps

    def moveTo(self, p):
        self.cur = [p]

    def lineTo(self, p):
        self.cur.append(p)

    def qCurveTo(self, *pts):
        from fontTools.pens.basePen import decomposeQuadraticSegment
        start = self.cur[-1]
        if pts[-1] is None:      # TrueType closed contour of off-curve points only
            pts = pts[:-1]
        for c, e in decomposeQuadraticSegment(pts):
            for i in range(1, self.steps + 1):
                t = i / self.steps
                x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * c[0] + t * t * e[0]
                y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * c[1] + t * t * e[1]
                self.cur.append((x, y))
            start = e

    def curveTo(self, *pts):
        from fontTools.pens.basePen import decomposeSuperBezierSegment
        start = self.cur[-1]
        for c1, c2, e in decomposeSuperBezierSegment(pts):
            for i in range(1, self.steps + 1):
                t = i / self.steps
                mt = 1 - t
                x = mt ** 3 * start[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * e[0]
                y = mt ** 3 * start[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * e[1]
                self.cur.append((x, y))
            start = e

    def closePath(self):
        if len(self.cur) >= 3:
            self.rings.append(self.cur)
        self.cur = []

    endPath = closePath

    def addComponent(self, name, transform):
        from fontTools.pens.transformPen import TransformPen
        self.glyphSet[name].draw(TransformPen(self, transform))


def _open_font(fid):
    from fontTools.ttLib import TTFont
    path, _, idx = fid.split(':', 1)[1].rpartition('#')
    return TTFont(path, fontNumber=int(idx or 0))


def sys_line_geometry(line: Line):
    """Glyph outlines laid out (and arched) in mm, y pointing down."""
    tt = _open_font(line.font)
    gs = tt.getGlyphSet()
    cmap = tt.getBestCmap()
    upm = tt['head'].unitsPerEm
    cap = getattr(tt['OS/2'], 'sCapHeight', 0) or 0
    if not cap:
        hg = cmap.get(ord('H'))
        if hg:
            pen = _FlatPen(gs)
            gs[hg].draw(pen)
            ys = [p[1] for r in pen.rings for p in r]
            cap = max(ys) if ys else upm * 0.7
        else:
            cap = upm * 0.7
    s = line.height_mm / cap
    x = 0.0
    glyphs = []
    for ch in line.text:
        gname = cmap.get(ord(ch))
        if gname is None:
            line.notes.append('"%s" is not in this font and was skipped.' % ch)
            continue
        adv = gs[gname].width * s
        pen = _FlatPen(gs)
        gs[gname].draw(pen)
        rings = [[(x + px * s, -py * s) for px, py in r] for r in pen.rings]
        g = rings_to_geom(rings) if rings else Polygon()
        glyphs.append((g, x, adv))
        x += adv + line.spacing_mm
    total = x - line.spacing_mm if glyphs else 0
    if abs(line.arch) >= 3 and total > 0:
        theta = abs(line.arch) / 100.0 * math.pi
        R = total / theta
        out = []
        for g, gx, adv in glyphs:
            if g.is_empty:
                continue
            cx = gx + adv / 2 - total / 2
            phi = cx / R
            g = affinity.translate(g, -(gx + adv / 2), 0)              # glyph centre on the baseline at origin
            if line.arch > 0:
                g = affinity.rotate(g, math.degrees(phi), origin=(0, 0))
                g = affinity.translate(g, R * math.sin(phi), R - R * math.cos(phi))
            else:
                g = affinity.rotate(g, -math.degrees(phi), origin=(0, 0))
                g = affinity.translate(g, R * math.sin(phi), -(R - R * math.cos(phi)))
            out.append(g)
        geom = clean(unary_union(out))
    else:
        geom = clean(unary_union([g for g, _, _ in glyphs if not g.is_empty]))
    return geom


def plan_sys_text(geom, colour, opts: Options):
    """Narrow strokes: satin from both edges meeting in the middle, which reads as satin lettering.
    Wide strokes: tatami fill with a crisp satin edge."""
    geom = thicken(geom, 0.9)
    objs = []
    for p in nearest_order([p for p in polys(geom) if p.area > 0.3]):
        stroke = 2 * p.area / max(p.length, 1e-6)
        if stroke <= 2.6:
            objs.append(Obj('manual', colour, seqs=satin_edge(p, 3.5, spacing=0.36, pull=0.15)))
        else:
            ko = clean(p.difference(p.buffer(-0.6, join_style=1)))
            core = clean(p.difference(ko))
            for c in polys(core):
                if c.area > 0.6:
                    objs.append(Obj('fill', colour, poly=c, params=fill_params(colour, opts, c.area, 30)))
            objs.append(Obj('manual', colour, seqs=satin_edge(p, 1.0, spacing=0.36, pull=0.15)))
    return objs


def stitch_objects(objs, log):
    with tempfile.TemporaryDirectory() as tmp:
        svg = Path(tmp) / 'plan.svg'
        write_svg(objs, svg)
        raw = Path(tmp) / 'raw.vp3'
        run_inkstitch(svg, raw, log)
        p = pystitch.read(str(raw))
    fix_long(p, max(80, int(10 * (1.6 * max_satin_width(objs) + 1.5))))
    return p


def sys_line(line: Line, opts: Options, log):
    geom = sys_line_geometry(line)
    if geom.is_empty:
        raise ValueError('Nothing to stitch for "%s".' % line.text)
    return stitch_objects(plan_sys_text(geom, line.colour, opts), log)


def line_pattern(line: Line, opts: Options, log):
    if line.font.startswith('emb:'):
        return emb_line(line)
    return sys_line(line, opts, log)


# ------------------------------------------------------------------ layout

def _bounds(p):
    st = [s for s in p.stitches if s[2] & 0xFF == STITCH]
    xs = [s[0] for s in st]
    ys = [s[1] for s in st]
    return min(xs), min(ys), max(xs), max(ys)


def stack(items, gap_mm=3.0, align='center'):
    """items: list of patterns, top to bottom -> one pattern, lines centred (or aligned) on each other."""
    b = [_bounds(p) for p in items]
    width = max(x1 - x0 for x0, _, x1, _ in b)
    y = 0.0
    seq = []
    for p, (x0, y0, x1, y1) in zip(items, b):
        w = x1 - x0
        if align == 'left':
            dx = -x0
        elif align == 'right':
            dx = width - w - x0
        else:
            dx = (width - w) / 2 - x0
        dy = y - y0
        for t, st in blocks(p):
            seq.append((t, [[sx + dx, sy + dy, c] for sx, sy, c in st]))
        y += (y1 - y0) + gap_mm * 10
    return assemble(seq)
