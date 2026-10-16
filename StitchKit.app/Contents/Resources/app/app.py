"""StitchKit: a small local app for digitizing artwork and making patches and appliqué frames.

Runs on your own Mac. Open it with "Open StitchKit.command"; it shows up in your web browser at
http://127.0.0.1:5077 but nothing leaves your computer.

Your own things live in Documents/StitchKit (made files, Frames, Projects, My threads.txt,
settings.json). Updating StitchKit only replaces the StitchKit app folder, never that.
"""
import io
import json
import os
import re
import shutil
import sys
import threading
import tempfile
import time
import traceback
import uuid
import webbrowser
import zipfile
from pathlib import Path

from flask import Flask, request, jsonify, send_file, abort, Response

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from engine import art as artmod, existing, shapes, text as textmod, render  # noqa: E402
from engine import produce, output, hoops, threads, container, steps as stepmod, fabrics  # noqa: E402
from engine import library, tags as tagmod, shapeedit                              # noqa: E402
from dataclasses import replace                                                     # noqa: E402
from engine.plan import Options                                                  # noqa: E402

VERSION = (ROOT / 'VERSION').read_text().strip() if (ROOT / 'VERSION').exists() else '1.1 beta'
PORT = 5077
HOME_OUT = Path.home() / 'Documents' / 'StitchKit'
PROJECTS = HOME_OUT / 'Projects'
SETTINGS = HOME_OUT / 'settings.json'
WORK = Path.home() / '.stitchkit'
FORMATS = ['vp3', 'vip', 'pes', 'dst', 'jef', 'exp']
app = Flask(__name__)
app.json.sort_keys = False
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024
JOBS = {}
UPLOADS = {}
LOCK = threading.Lock()
SIZES = [('S', 1.5), ('M', 2.5), ('L', 3.5), ('XL', 5.0), ('XXL', 7.0)]
DEFAULT_SETTINGS = dict(units='in', margin_mm=hoops.DEFAULT_MARGIN, brand='polyx40', hoop='small', ask_hoop=True,
                        monogram_folders=[], frame_folders=[], grid=True)


def safe_name(s):
    s = re.sub(r'[^A-Za-z0-9_-]+', '_', s or '').strip('_')
    return s[:40] or 'design'


def load_settings():
    try:
        s = json.loads(SETTINGS.read_text())
        return {**DEFAULT_SETTINGS, **{k: v for k, v in s.items() if k in DEFAULT_SETTINGS}}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def num(data, k, default=0.0, lo=None, hi=None):
    try:
        v = float(data.get(k))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


# ---------------------------------------------------------------- small endpoints

@app.get('/api/version')
def version():
    notes = (ROOT / 'WHATS_NEW.txt').read_text() if (ROOT / 'WHATS_NEW.txt').exists() else ''
    return jsonify(version=VERSION, whats_new=notes)


@app.get('/api/settings')
def get_settings():
    s = load_settings()
    s['hoops'] = hoops.HOOPS
    s['brands'] = [dict(key=k, name=v[0], mine=k.startswith(('user:', 'mine'))) for k, v in threads.brands().items()]
    s['my_threads'] = len(threads.chart('mine'))
    s['fabrics'] = {k: dict(v) for k, v in fabrics.load().items()}
    s['vectorcraft'] = vectorcraft_app() is not None
    return jsonify(s)


@app.post('/api/threads/import')
def thread_import():
    """Add a thread brand from a chart (file upload or pasted text)."""
    name = (request.form.get('name') or '').strip()
    text = request.form.get('text') or ''
    f = request.files.get('file')
    if f and f.filename:
        raw = f.read()
        if f.filename.lower().endswith(('.xlsx', '.xls', '.pdf', '.png', '.jpg', '.jpeg')):
            return jsonify(error='StitchKit reads charts saved as text: .txt, .csv or .gpl. Send the PDF, '
                                 'spreadsheet or photo to Claude and it will make the text chart for you.'), 400
        text = raw.decode('utf-8', errors='replace')
        name = name or Path(f.filename).stem
    if not text.strip():
        return jsonify(error='Choose a chart file or paste the chart.'), 400
    try:
        key, n = threads.import_chart(name or 'My brand', text)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    s = load_settings()
    s['brand'] = key
    SETTINGS.write_text(json.dumps(s, indent=2))
    return jsonify(key=key, count=n)


@app.post('/api/fabrics')
def fabric_save():
    data = request.get_json(force=True)
    if data.get('key') not in fabrics.FABRICS:
        return jsonify(error='Unknown fabric.'), 400
    fabrics.save_user(data['key'], data)
    return jsonify(fabrics.load()[data['key']])


def vectorcraft_app():
    if sys.platform != 'darwin':
        return None
    for p in (Path('/Applications/VectorCraft.app'), Path.home() / 'Applications' / 'VectorCraft.app',
              Path('/Applications/ArtCraft/VectorCraft.app')):
        if p.exists():
            return p
    try:
        import subprocess
        r = subprocess.run(['mdfind', 'kMDItemCFBundleIdentifier == "*vectorcraft*"c || kMDItemFSName == "VectorCraft.app"'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.endswith('.app'):
                return Path(line)
    except Exception:
        pass
    return None


@app.post('/api/vectorcraft/open')
def vectorcraft_open():
    """Open the artwork in VectorCraft. Save it there (same file) and press Reload in StitchKit."""
    data = request.get_json(force=True)
    up = UPLOADS.get(data.get('id'))
    if not up or up.get('stitch'):
        return jsonify(error='Add an SVG artwork first.'), 400
    a = vectorcraft_app()
    if not a:
        return jsonify(error='VectorCraft was not found in your Applications folder.'), 400
    import subprocess
    subprocess.Popen(['open', '-a', str(a), str(up['path'])])
    up['mtime'] = Path(up['path']).stat().st_mtime
    return jsonify(ok=True, path=str(up['path']))


@app.post('/api/vectorcraft/reload')
def vectorcraft_reload():
    data = request.get_json(force=True)
    up = UPLOADS.get(data.get('id'))
    if not up:
        return jsonify(error='Upload the file again.'), 400
    up.pop('art', None)
    changed = Path(up['path']).stat().st_mtime != up.get('mtime')
    return jsonify(ok=True, changed=changed)


RECENT = HOME_OUT / 'recent.json'


def remember_recent(uid):
    up = UPLOADS.get(uid)
    if not up:
        return
    try:
        rec = json.loads(RECENT.read_text())
    except Exception:
        rec = []
    rec = [r for r in rec if r.get('filename') != up.get('filename') or r.get('stitch') != up['stitch']]
    rec.insert(0, dict(id=uid, name=up['name'], filename=up.get('filename', ''), stitch=up['stitch'],
                       path=str(up['path']), time=time.time()))
    try:
        HOME_OUT.mkdir(parents=True, exist_ok=True)
        RECENT.write_text(json.dumps(rec[:15], indent=1))
    except OSError:
        pass


@app.get('/api/recent')
def recent_list():
    try:
        rec = json.loads(RECENT.read_text())
    except Exception:
        rec = []
    out = []
    for r in rec:
        if Path(r['path']).exists():
            r['when'] = time.strftime('%b %d, %I:%M %p', time.localtime(r['time']))
            out.append(r)
    return jsonify(out)


@app.post('/api/recent/open')
def recent_open():
    data = request.get_json(force=True)
    try:
        rec = json.loads(RECENT.read_text())
    except Exception:
        rec = []
    r = next((x for x in rec if x['id'] == data.get('id')), None)
    if not r or not Path(r['path']).exists():
        return jsonify(error='That file is no longer available.'), 404
    uid = r['id']
    UPLOADS[uid] = dict(path=Path(r['path']), name=r['name'], stitch=r['stitch'], filename=r['filename'])
    out = dict(id=uid, name=r['name'], filename=r['filename'], stitch=r['stitch'],
               bitmap=not r['stitch'] and not r['path'].lower().endswith('.svg'))
    if r['stitch']:
        out.update(stitch_info(uid))
    remember_recent(uid)
    return jsonify(out)


@app.post('/api/settings')
def set_settings():
    data = request.get_json(force=True)
    s = load_settings()
    for k in DEFAULT_SETTINGS:
        if k in data:
            s[k] = data[k]
    s['margin_mm'] = max(0.0, min(30.0, float(s['margin_mm'])))
    for k in ('monogram_folders', 'frame_folders'):
        s[k] = [str(x) for x in (s.get(k) or []) if isinstance(x, str)][:20]
    HOME_OUT.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2))
    return jsonify(s)


@app.post('/api/mythreads/open')
def open_my_threads():
    threads.ensure_my_threads()
    if sys.platform == 'darwin':
        os.system('open -t "%s"' % threads.MY_THREADS)
    return jsonify(path=str(threads.MY_THREADS))


@app.post('/api/upload')
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify(error='No file received.'), 400
    ext = Path(f.filename).suffix.lower()
    is_stitch = existing.is_stitch_file(f.filename)
    if ext not in ('.svg', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff') and not is_stitch:
        return jsonify(error='Use an SVG, PNG or JPG, or a stitch file like VP3, PES, DST or JEF.'), 400
    uid = uuid.uuid4().hex[:10]
    d = WORK / 'uploads' / uid
    d.mkdir(parents=True, exist_ok=True)
    path = d / ('art' + ext)
    f.save(path)
    UPLOADS[uid] = dict(path=path, name=safe_name(Path(f.filename).stem), stitch=is_stitch, filename=f.filename)
    remember_recent(uid)
    out = dict(id=uid, name=UPLOADS[uid]['name'], filename=f.filename, bitmap=ext != '.svg' and not is_stitch,
               stitch=is_stitch)
    if is_stitch:
        try:
            out.update(stitch_info(uid))
        except Exception as e:
            return jsonify(error='Could not read that stitch file: %s' % e), 400
    return jsonify(out)


def stitch_info(uid):
    up = UPLOADS[uid]
    if 'result' not in up:
        up['result'] = produce.stitch_file_result(up['path'], 'Design')
    res = up['result']
    x0, y0, x1, y1 = res.bounds_mm()
    return dict(w_mm=round(x1 - x0, 1), h_mm=round(y1 - y0, 1),
                stitches=sum(sum(1 for p in s.stitches if p[2] == 0) for s in res.steps),
                colours=[s.colour for s in res.steps])


@app.get('/api/stitchpreview')
def stitch_preview():
    """A see-through picture of an uploaded stitch file, for the arrange canvas."""
    uid = request.args.get('id', '')
    up = UPLOADS.get(uid)
    if not up or not up['stitch']:
        abort(404)
    png = Path(up['path']).with_name('preview.png')
    if not png.exists():
        p = existing.clean_pattern(up['path'])
        render.render(p, str(png), ppmm=8, thread_mm=0.4, pad_mm=0)
        from PIL import Image
        im = Image.open(png).convert('RGBA')
        px = im.load()
        bg = (120, 150, 165)
        for y in range(im.height):
            for x in range(im.width):
                if px[x, y][:3] == bg:
                    px[x, y] = (0, 0, 0, 0)
        im.save(png)
    return send_file(png)


@app.post('/api/inspect')
def inspect():
    data = request.get_json(force=True)
    up = UPLOADS.get(data.get('id'))
    if not up:
        return jsonify(error='Upload the file again.'), 400
    if up.get('stitch'):
        return jsonify(stitch=True, **stitch_info(data.get('id')))
    try:
        art = artmod.load(up['path'], int(data.get('colours') or 3))
    except Exception as e:
        return jsonify(error=str(e)), 400
    up['art'] = art
    up['art_colours'] = int(data.get('colours') or 3)
    total = sum(g.area for _, g in art.layers) or 1
    reduced = None
    if getattr(art, 'reduced', None) is not None:
        im = art.reduced.copy()
        im.thumbnail((520, 520))
        rp = Path(up['path']).with_name('reduced_%d.png' % up['art_colours'])
        im.save(rp)
        reduced = '/api/reduced?id=%s&n=%d&t=%d' % (data.get('id'), up['art_colours'], int(time.time()))
    return jsonify(colours=[dict(hex=c, share=round(100 * g.area / total)) for c, g in art.layers],
                   aspect=art.width / art.height, notes=art.notes, reduced=reduced)


@app.get('/api/reduced')
def reduced_preview():
    up = UPLOADS.get(request.args.get('id', ''))
    if not up:
        abort(404)
    p = Path(up['path']).with_name('reduced_%d.png' % int(request.args.get('n', 3)))
    if not p.exists():
        abort(404)
    return send_file(p)


@app.get('/api/shapes')
def shape_list():
    return jsonify([dict(key=k, label=lab, d=d) for k, (lab, d) in shapes.catalogue().items()])


@app.get('/api/frames')
def frame_list():
    return jsonify([dict(key=k, label=lab, kind=kind, d=d, user=k.startswith('user_'))
                    for k, (lab, kind, d) in container.frame_catalogue().items()])


@app.post('/api/frameoutline')
def frame_outline():
    """The patch/frame at a fixed size, centred on 0,0 (for arranging files inside it)."""
    data = request.get_json(force=True)
    opts = make_options(data, 3.5)
    size = num(data, 'patch_in', 4.0, 0.5, 14) * 25.4
    if data.get('kind') == 'tag' and not str(data.get('tag_shape', '')).startswith('file:'):
        lay = tagmod.layout(opts.tag_shape, size, opts.tag_hole, max(1.5, opts.gap_mm), opts.tag_sideways, opts.border_mm)
        b = lay.outer.bounds
        dx, dy = -(b[0] + b[2]) / 2, -(b[1] + b[3]) / 2
        from shapely import affinity as _aff
        mv = lambda g: _aff.translate(g, dx, dy)
        return jsonify(outer=_path(mv(lay.outer)), inner=_path(mv(lay.region)), pieces=[_path(mv(lay.ring()))],
                       bounds=mv(lay.outer).bounds)
    lay = fixed_layout(opts, size)

    def path(g):
        d = []
        for p in getattr(g, 'geoms', [g]):
            if p.is_empty or p.geom_type != 'Polygon':
                continue
            for ring in [p.exterior] + list(p.interiors):
                d.append('M' + ' L'.join('%.2f,%.2f' % c for c in list(ring.coords)[:-1]) + ' Z')
        return ' '.join(d)
    out = dict(outer=path(lay.outer), inner=path(lay.inner) if lay.inner is not None else '',
               pieces=[path(p) for p in lay.pieces], bounds=lay.outer.bounds)
    return jsonify(out)


def fixed_layout(opts, size_mm):
    from shapely.geometry import Point
    o = opts
    if not o.frame and o.patch_shape == 'outline':
        o = Options(**{**o.__dict__, 'patch_shape': 'rounded'})
    return container.grow_to(Point(0, 0).buffer(0.5), o, size_mm)


@app.get('/api/fonts')
def font_list():
    emb = [dict(id=f['id'], name=f['name'].strip(), style=f['style'],
                min_in=round(f['min_mm'] / 25.4, 2), max_in=round(f['max_mm'] / 25.4, 2))
           for f in textmod.embroidery_fonts()]
    try:
        sysf = textmod.system_fonts()
    except Exception:
        sysf = []
    return jsonify(emb=emb, sys=sysf)


@app.get('/api/fontpreview')
def font_preview():
    fid = request.args.get('id', '')
    for f in textmod.embroidery_fonts():
        if f['id'] == fid and Path(f['preview']).exists():
            return send_file(f['preview'])
    abort(404)


@app.get('/api/fontfile')
def font_file():
    fid = request.args.get('id', '')
    if not fid.startswith('sys:'):
        abort(404)
    path, _, idx = fid[4:].rpartition('#')
    if not any(f['id'] == fid for f in textmod.system_fonts()) or path.lower().endswith('.ttc'):
        abort(404)
    return send_file(path)


# ---------------------------------------------------------------- making things

KIND_WORD = {'design': 'Design', 'patch': 'Patch', 'frame': 'Frame', 'tag': 'Bag tag'}
TAG_SIZES = [3.0, 3.5, 4.0, 4.5, 5.0]


def make_options(data, size_in):
    kind = data.get('kind', 'design')            # design | patch | frame | tag
    fab = data.get('fabric', 'hoop')
    band = data.get('frame_band') if data.get('frame_band') in ('applique', 'fill', 'none') else 'applique'
    edits = data.get('shape_edits') if isinstance(data.get('shape_edits'), dict) else {}
    return Options(
        mode='patch' if kind in ('patch', 'frame', 'tag') else 'design',
        size_in=size_in, density=data.get('density', 'normal'),
        satin_outline=bool(data.get('satin_outline')), detect_borders=bool(data.get('detect_borders', True)),
        patch_shape=data.get('shape', 'outline'), border_mm=num(data, 'border_mm', 0, 0, 8),
        border_colour=data.get('border_colour') or None,
        background=(data.get('background_colour') or '#2b4a6f') if (fab == 'stitched' and kind == 'patch') else None,
        fabric_method='applique' if fab == 'applique' else 'hoop',
        gap_mm=num(data, 'gap_mm', 1.5, 0, 40), patch_in=num(data, 'patch_in', 0, 0, 14),
        frame=kind == 'frame', frame_key=data.get('frame_key') or 'notched', frame_band=band,
        frame_band_colour=data.get('frame_band_colour') or '#c9d8f0',
        frame_band_mm=num(data, 'frame_band_mm', 0, 0, 40), frame_inner_mm=num(data, 'frame_inner_mm', 0, 0, 6),
        frame_center='fill' if data.get('frame_center') == 'fill' else 'fabric',
        frame_center_colour=data.get('frame_center_colour') or '#ffffff',
        fabric=data.get('material') if data.get('material') in fabrics.FABRICS else 'twill',
        knockdown=None if data.get('knockdown') in (None, '', 'auto') else bool(data.get('knockdown') in (True, 'on', 'true')),
        knockdown_colour=data.get('knockdown_colour') or '',
        edge_style='blanket' if data.get('edge_style') == 'blanket' else 'satin',
        fill_style=data.get('fill_style') if data.get('fill_style') in ('tatami', 'contour', 'meander') else 'tatami',
        tag=kind == 'tag', tag_shape=data.get('tag_shape') or 'classic',
        tag_hole=data.get('tag_hole') if data.get('tag_hole') in tagmod.HOLES else 'medium',
        tag_material='peltex' if data.get('tag_material') == 'peltex' else 'foam',
        tag_sideways=bool(data.get('tag_sideways')),
        design_order=data.get('design_order') if data.get('design_order') in ('first', 'last') else 'auto',
        part_gap_mm=num(data, 'part_gap_mm', 0, 0, 80), shape_edits=edits)


def file_frame_for(data, kind):
    """Your own frame/tag file chosen for this piece, or None."""
    key = data.get('tag_shape') if kind == 'tag' else (data.get('frame_key') if kind == 'frame' else '')
    if not key or not str(key).startswith('file:'):
        return None
    return library.find_frame(key, load_settings().get('frame_folders') or [])


def parse_lines(data, k=1.0):
    out = []
    for l in data.get('lines') or []:
        t = (l.get('text') or '').strip()
        if not t or not l.get('font'):
            continue
        try:
            out.append(textmod.Line(
                text=t, font=l['font'], height_mm=max(2.0, float(l.get('height_in') or 0.5) * 25.4 * k),
                arch=max(-100.0, min(100.0, float(l.get('arch') or 0))),
                spacing_mm=float(l.get('spacing_mm') or 0), colour=l.get('colour') or '#151011',
                position='below' if l.get('position') == 'below' else 'above'))
        except (TypeError, ValueError):
            continue
    return out


def variants_for(data, src, kind):
    """What to make: sizes in inches, or size labels of your own frame/tag file."""
    ff = file_frame_for(data, kind)
    if ff is not None:
        labels = [s for s in (data.get('file_sizes') or []) if s in ff.sizes]
        return labels or [ff.size_list()[0]['label']], ff
    if src == 'art' or kind == 'tag':
        sizes = []
        for s in data.get('sizes', []):
            try:
                if float(s) > 0.3:
                    sizes.append(float(s))
            except (TypeError, ValueError):
                pass
        for part in re.split(r'[,\s]+', str(data.get('custom') or '')):
            try:
                v = float(part.replace('"', ''))
            except ValueError:
                continue
            if 0.5 <= v <= 14 and v not in sizes:
                sizes.append(v)
        return sizes, None
    return [0.0], None


def check_request(data):
    src = data.get('source', 'art')
    kind = data.get('kind', 'design')
    up = UPLOADS.get(data.get('id')) if data.get('id') else None
    if src in ('art', 'stitch') and not up:
        return 'Add your file first (or upload it again).'
    if src == 'text' and not parse_lines(data):
        return 'Type at least one line of text.'
    if src == 'monogram':
        m = data.get('monogram') or {}
        if not ''.join((m.get(k) or '') for k in ('first', 'middle', 'last')).strip():
            return 'Type at least one initial.'
    if src == 'arrange' and not [i for i in data.get('items') or [] if i.get('id') in UPLOADS]:
        return 'Add the files, words or monograms you want to arrange.'
    if src == 'none' and kind not in ('tag', 'frame'):
        return 'Choose something to stitch.'
    if src == 'none' and kind == 'frame' and file_frame_for(data, kind) is None:
        return 'Choose one of your own frame files, or something to put in the frame.'
    sizes, ff = variants_for(data, src, kind)
    if not sizes:
        return 'Pick at least one size.'
    if ff is None and any(isinstance(s, float) and s > 14 for s in sizes):
        return 'Largest size is 14 inches.'
    return None


@app.post('/api/start')
def start():
    data = request.get_json(force=True)
    err = check_request(data)
    if err:
        return jsonify(error=err), 400
    src, kind = data.get('source', 'art'), data.get('kind', 'design')
    up = UPLOADS.get(data.get('id')) if data.get('id') else None
    lines = parse_lines(data)
    sizes, _ff = variants_for(data, src, kind)
    formats = [f for f in data.get('formats', []) if f in FORMATS] or ['vp3']
    jid = uuid.uuid4().hex[:10]
    default = (up['name'] if up else (lines[0].text if lines else
                                      ('Monogram' if src == 'monogram' else ('Bag_tag' if kind == 'tag' else 'design'))))
    name = safe_name(data.get('name') or default)
    out = HOME_OUT / ('%s_%s' % (name, time.strftime('%Y-%m-%d_%H%M%S')))
    JOBS[jid] = dict(status='queued', done=0, total=len(sizes), results=[], error=None, out=str(out), log=[])
    threading.Thread(target=run_job, args=(jid, up, data, sizes, formats, name, out), daemon=True).start()
    return jsonify(job=jid)


def size_label(inches):
    if isinstance(inches, str):
        return inches.replace('"', 'in')
    for lab, v in SIZES:
        if abs(v - inches) < 1e-6:
            return lab
    return ('%gin' % round(inches, 2)).replace('.', '-')


def supplies_for(data, kind, piece):
    if kind == 'tag':
        return tagmod.supplies(data.get('tag_material') or 'foam')
    return fabrics.supplies(data.get('material') or 'twill', kind, applique=bool(piece.fabric),
                            stitched_background=(kind == 'patch' and data.get('fabric') == 'stitched'),
                            satin_edges=kind != 'design')


def run_job(jid, up, data, sizes, formats, name, out):
    job = JOBS[jid]
    try:
        with LOCK:
            settings = load_settings()
            src = data.get('source', 'art')
            kind = data.get('kind', 'design')
            copies = int(num(data, 'copies', 1, 1, 200))
            basting = bool(data.get('basting'))
            brand = settings['brand']
            margin = float(settings['margin_mm'])
            fit_hoop = next((h for h in hoops.HOOPS if h['key'] == data.get('fit_hoop')), None)
            order = sorted(sizes) if all(isinstance(s, float) for s in sizes) else sizes
            for idx, inches in enumerate(order):
                scale = 1.0
                if isinstance(data.get('resize'), dict):
                    scale = float(data['resize'].get(str(inches), 1.0))
                for attempt in range(4):
                    piece, label, base, size_text = build_piece(job, up, data, src, kind, inches, scale, name)
                    w, h = piece.size_mm()
                    if not fit_hoop or copies > 1 or hoops.fits(w, h, fit_hoop, margin):
                        break
                    f = hoops.shrink_to_fit(w, h, fit_hoop, margin)
                    scale *= f * (0.995 if attempt < 2 else 0.97)
                    job['status'] = 'resizing to fit the %s hoop' % fit_hoop['name']
                if scale != 1.0 and fit_hoop:
                    piece.notes.append('Resized to %d%% to fit the %s hoop.' % (round(100 * scale), fit_hoop['name']))
                job['status'] = 'writing files for %s' % label
                r = output.finish(piece, out, base, formats, copies, basting, [], brand, margin,
                                  title=name.replace('_', ' ') + ('' if label in KIND_WORD.values() else ' ' + label),
                                  size_text=size_text, supplies=supplies_for(data, kind, piece))
                r.update(label=label, base=base, inches=inches, scale=scale, kind=piece.kind)
                job['results'].append(r)
                job['done'] = idx + 1
            write_readme(out, job['results'])
            job['status'] = 'finished'
    except Exception as e:
        job['error'] = str(e) or e.__class__.__name__
        job['trace'] = traceback.format_exc()
        job['status'] = 'failed'
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / 'last_error.txt').write_text(job['trace'] + '\n\n' + '\n'.join(job['log'][-5:]))


def _mono_sets(m):
    """Your letter files for a monogram: (small set, big set, [smaller alternatives]) or None."""
    font = m.get('font') or ''
    if not font.startswith('set:'):
        return None
    folders = load_settings().get('monogram_folders') or []
    fonts = library.fonts(folders)
    fam = next((f for f in fonts if f['font'] == font[4:]), None)
    if not fam:
        raise ValueError('The monogram letters "%s" are no longer in your monogram folders.' % font[4:])
    sets = [library.find_set(s['key'], folders) for s in fam['sets']]
    sets = [s for s in sets if s is not None]
    want = m.get('set') or 'auto'
    if want != 'auto':
        chosen = [s for s in sets if s.key == want] or sets[-1:]
        sets_order = chosen
    else:
        sets_order = list(reversed(sets))           # biggest first
    return sets, sets_order


def _small_for(sets, big):
    """The set to use for the side letters of a classic monogram: about 60-70% of the big one."""
    smaller = [s for s in sets if s.size_mm and big.size_mm and s.size_mm < big.size_mm * 0.9]
    if not smaller:
        return big
    return min(smaller, key=lambda s: abs(s.size_mm / big.size_mm - 0.65))


def make_content(up, data, src, kind, inches, scale, opts, log, status):
    """The design part of a piece as a produce.Content (None for "just the tag/frame")."""
    lines = parse_lines(data, scale)
    gap = num(data, 'line_gap_mm', 3, 0, 40)
    align = data.get('align', 'center')
    if src == 'none':
        return None
    if src == 'art':
        colours = int(data.get('colours') or 3)
        art = up.get('art') if up.get('art_colours') == colours else None
        art = art or artmod.load(up['path'], colours)
        up['art'], up['art_colours'] = art, colours
        size_in = inches * scale if (kind in ('design', 'patch', 'frame') and isinstance(inches, float) and inches) else 3.0
        if kind == 'tag' or isinstance(inches, str):
            size_in = 2.0
        if lines:
            mid = produce.art_content(art, opts, size_in, log).render(1.0)
            content, _ = produce.text_content(lines, mid, opts, gap, align, log, status)
            if kind in ('tag',) or isinstance(inches, str):
                content.scale = 'both'
            return content
        return produce.art_content(art, opts, size_in if kind == 'design' else size_in * 0.75, log)
    if src == 'stitch':
        res = up.get('result') or produce.stitch_file_result(up['path'])
        up['result'] = res
        if abs(scale - 1) > 1e-6:
            res = res.scaled(scale)
            res.notes.append('Your stitch file was scaled to %d%%. Stitch a test: density changes when a stitch file is '
                             'resized.' % round(100 * scale))
        if lines:
            content, _ = produce.text_content(lines, res, opts, gap, align, log, status)
            content.scale = 'none'
            return content
        return produce.result_content(res, 'none')
    if src == 'text':
        content, _ = produce.text_content(lines, None, opts, gap, align, log, status)
        return content
    if src == 'monogram':
        m = data.get('monogram') or {}
        letters = (m.get('first'), m.get('middle'), m.get('last'))
        layout = m.get('layout') or 'classic'
        spacing = num(m, 'spacing_mm', 2, -10, 30)
        sets = _mono_sets(m)
        if sets:
            allsets, order = sets
            colour = m.get('colour') if m.get('recolour') else None
            status('placing your monogram letters')

            def content_for(i):
                big = order[i]
                small = _small_for(allsets, big) if layout == 'classic' else big
                res = produce.letters_result(small, letters, layout, spacing, colour, big_set=big)
                c = produce.result_content(res, 'none', 'Monogram')
                if i + 1 < len(order):
                    c.smaller = lambda: content_for(i + 1)
                return c
            if kind == 'design' or (kind in ('patch', 'frame') and not opts.patch_in):
                return content_for(0)
            if kind in ('patch', 'frame') and opts.patch_in and file_frame_for(data, kind) is None:
                # the biggest letters that still fit the patch or frame size you asked for
                target = opts.patch_in * 25.4
                for i in range(len(order)):
                    c = content_for(i)
                    _k, lay, _n = container.fit(c.cov, opts, target, 'none')
                    if lay.longest() <= target + 0.5 or i == len(order) - 1:
                        return c
            return content_for(0)
        h = num(m, 'height_in', 1.5, 0.2, 10) * 25.4 * scale
        args = (letters, m.get('font') or 'emb:barstitch_bold', layout if layout != 'single' else 'row',
                m.get('colour') or '#151011', spacing)
        if layout == 'single':
            args = ((m.get('first') or m.get('last') or m.get('middle'), '', ''),) + args[1:]
        status('stitching the monogram')
        first = produce.monogram_result(args[0], args[1], h, args[2], args[3], args[4], opts, log)
        cache = {1.0: first}

        def render_mono(k):
            k = round(k, 3)
            if k not in cache:
                status('resizing the monogram to fit')
                cache[k] = produce.monogram_result(args[0], args[1], h * k, args[2], args[3], args[4], opts, log)
            return cache[k]
        return produce.Content(stepmod.coverage(first.steps), render_mono, 'shrink', 'Monogram')
    # arrange / combine: everything placed by hand
    items = []
    for it in data.get('items') or []:
        u = UPLOADS.get(it.get('id'))
        if not u:
            continue
        res = u.get('result') or produce.stitch_file_result(u['path'])
        u['result'] = res
        k = max(0.5, min(1.5, float(it.get('scale') or 1)))
        items.append((res, float(it.get('x') or 0) * scale, float(it.get('y') or 0) * scale, k * scale))
    placed = stepmod.Result(_label_arranged(items), [], [], 'design')
    for res, x, y, k in items:
        c = res.centred()
        if abs(k - 1) > 1e-6:
            c = c.scaled(k)
        placed.fabric += c.translate(x, y).fabric
    if any(abs(k - 1) > 0.03 and not getattr(r, 'made', False) for r, _, _, k in items):
        placed.notes.append('Some files were resized. Stitch files keep their stitch count when resized, so '
                            'density changes: stay within about 80 to 120%.')
    c = produce.result_content(placed, 'none')
    c.fixed = True
    return c


def build_piece(job, up, data, src, kind, inches, scale, name):
    """One finished piece as a steps.Result. scale shrinks everything (used to fit a hoop)."""
    log = job['log']
    status = lambda s: job.__setitem__('status', s)
    word = KIND_WORD[kind]
    size_in = inches * scale if isinstance(inches, float) and inches else 3.5
    opts = make_options(data, size_in)
    if opts.patch_in:
        opts.patch_in *= scale
    ff = file_frame_for(data, kind)
    content = make_content(up, data, src, kind, inches, scale, opts, log, status)
    if isinstance(inches, str):
        label, base = '%s %s' % (word, inches), '%s_%s_%s' % (name, word.replace(' ', '_'), size_label(inches))
    elif (src == 'art' and kind != 'tag') or (kind == 'tag' and inches):
        label = size_label(inches) if kind == 'design' else '%s %s' % (word, size_label(inches))
        base = '%s_%s%s' % (name, '' if kind == 'design' else word.replace(' ', '_') + '_', size_label(inches))
    else:
        label, base = word, '%s%s' % (name, '' if kind == 'design' else '_' + word.replace(' ', '_'))
    if ff is not None:
        status('building your %s' % ('tag' if kind == 'tag' else 'frame'))
        piece = produce.make_file_frame_piece(content, ff, inches if isinstance(inches, str) else '', opts, log, status,
                                              tag=kind == 'tag')
        return piece, label, base, size_words(piece)
    if kind == 'tag':
        piece = produce.make_tag_piece(content, opts, (inches or 4.0) * scale * 25.4, log, status)
        return piece, label, base, size_words(piece)
    if src == 'arrange':
        placed = content.render(1.0)
        if kind == 'design':
            return produce.with_knockdown(placed, opts, log), label, base, ''
        status('building the %s round your arrangement' % word.lower())
        piece = make_fixed_piece(placed, opts, (opts.patch_in * 25.4) or 4 * 25.4 * scale, log)
        return piece, label, base, size_words(piece)
    target = (opts.patch_in or 0) * 25.4
    if src == 'art' and kind != 'design':
        target = target if parse_lines(data) else size_in * 25.4
    piece = produce.make_piece(content, opts, target, log, status)
    return piece, label, base, size_words(piece)


def _label_arranged(items):
    out = []
    for n, (res, x, y, k) in enumerate(items, 1):
        c = res.centred()
        if abs(k - 1) > 1e-6:
            c = c.scaled(k)
        c = c.translate(x, y)
        for s in c.steps:
            lab = s.label if getattr(res, 'made', False) else s.label.replace('Design', 'File %d' % n)
            out.append(replace(s, label=lab))
    return out


def make_fixed_piece(placed, opts, size_mm, log):
    """A patch/frame of a set size centred on 0,0 with arranged content already in place."""
    lay = fixed_layout(opts, size_mm)
    cov = stepmod.coverage(placed.steps)
    bc = produce.border_colour_for(placed, opts)
    pre, post, fabric, notes = container.objects(lay, cov, opts, bc)
    st = stepmod.stitch_objects(pre + post, log)
    n = produce._count_pre(st, pre)
    if not lay.outer.buffer(0.5).contains(cov):
        notes.insert(0, 'Part of your arrangement sits outside the frame or patch: check the preview.')
    return produce.with_knockdown(stepmod.Result(st[:n] + placed.steps + st[n:], fabric + placed.fabric,
                                                 placed.notes + notes, 'frame' if opts.frame else 'patch', lay.outer),
                                  opts, log)


def size_words(piece):
    w, h = piece.size_mm()
    return '%.2f x %.2f in (%.0f x %.0f mm)' % (w / 25.4, h / 25.4, w, h)


def write_readme(out, results):
    lines = ['StitchKit %s output' % VERSION, '',
             'Each piece has its stitch files, a preview, a thread sheet (open in your browser and print),',
             'a placement template (print at 100%) and, for appliqué, a Cricut cut file.', '']
    for r in results:
        st = r['stats']
        lines.append('%s  %.2f x %.2f in  %d stitches  %d thread blocks  hoop: %s' % (
            r['base'], st['width_mm'] / 25.4, st['height_mm'] / 25.4, st['stitches'], len(r['blocks']), r['hoop']))
        for b in r['blocks']:
            m = b.get('match')
            lines.append('   %s  %s%s' % (b['colour'], ('%s %s  ' % (m['number'], m['name'])) if m else '',
                                         ', '.join(b['steps'])))
        for n in r['notes']:
            lines.append('   ' + n)
        for i, g in enumerate(r.get('guide') or [], 1):
            lines.append('   %d. %s' % (i, g))
    Path(out, 'README.txt').write_text('\n'.join(lines) + '\n')


# ---------------------------------------------------------------- live preview

class Cancelled(Exception):
    pass


class _PreviewJob(dict):
    """Job dict for a preview: changing the status checks whether a newer preview was asked for."""

    def __init__(self, gen):
        super().__init__(status='starting', log=[])
        self.gen = gen

    def __setitem__(self, k, v):
        if k == 'status' and PREVIEW['want'] != self.gen:
            raise Cancelled()
        dict.__setitem__(self, k, v)
        if k == 'status':
            PREVIEW['status'] = v


PREVIEW = dict(want=0, data=None, status='', results={}, event=threading.Event())


def _preview_worker():
    while True:
        PREVIEW['event'].wait()
        PREVIEW['event'].clear()
        gen, data = PREVIEW['want'], PREVIEW['data']
        if data is None:
            continue
        job = _PreviewJob(gen)
        try:
            out = _preview_once(job, data)
            out['status'] = 'done'
        except Cancelled:
            continue
        except Exception as e:
            out = dict(status='error', error=str(e) or e.__class__.__name__)
            WORK.mkdir(parents=True, exist_ok=True)
            (WORK / 'last_error.txt').write_text(traceback.format_exc())
        out['gen'] = gen
        PREVIEW['results'] = {gen: out}


def _preview_once(job, data):
    src, kind = data.get('source', 'art'), data.get('kind', 'design')
    up = UPLOADS.get(data.get('id')) if data.get('id') else None
    sizes, ff = variants_for(data, src, kind)
    want = data.get('preview_size')
    v = sizes[0] if sizes else 0.0
    if want is not None:
        v = want if isinstance(want, str) else float(want)
    with LOCK:
        piece, label, base, size_text = build_piece(job, up, data, src, kind, v, 1.0, safe_name(data.get('name') or 'preview'))
    job['status'] = 'drawing the preview'
    single = piece.centred()
    pattern, blocks = stepmod.assemble(single.steps)
    st = render.stats(pattern)
    longest = max(st['width_mm'], st['height_mm'], 1)
    d = WORK / 'preview'
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob('*.png'):
        try:
            if time.time() - old.stat().st_mtime > 120:
                old.unlink()
        except OSError:
            pass
    png = d / ('p%d.png' % job.gen)
    ppmm = min(14.0, 1100.0 / longest)
    render.render(pattern, str(png), ppmm=ppmm, thread_mm=0.4, pad_mm=3, fabric=None, underlays=single.fabric)
    bl = render.blocks(pattern)
    xs = [p[0] for _, pts in bl for p in pts]
    ys = [p[1] for _, pts in bl for p in pts]
    x0, y0 = min(xs) - 3, min(ys) - 3
    from PIL import Image
    with Image.open(png) as _im:
        W, H = _im.size
    settings = load_settings()
    margin = float(settings['margin_mm'])
    hoop, how = hoops.pick(st['width_mm'], st['height_mm'], margin)
    brand = settings['brand']
    colours = []
    for b in blocks:
        if b['colour'] not in colours:
            colours.append(b['colour'])
    matches = {c: threads.match(c, brand) for c in colours} if brand != 'none' else {}
    minutes = st['stitches'] / output.SPM + output.CHANGE_MIN * (len(blocks) - 1)
    outline = None
    if single.outline is not None:
        outline = _path(single.outline)
    return dict(png='/api/preview/png/%d' % job.gen, x0=x0, y0=y0, w=W / ppmm, h=H / ppmm,
                w_mm=round(st['width_mm'], 1), h_mm=round(st['height_mm'], 1), stitches=st['stitches'],
                minutes=round(minutes), label=label, size_text=size_text,
                hoop=hoop['key'] if hoop else None, hoop_turned=how == 'turned',
                notes=single.notes, guide=single.guide, outline=outline,
                blocks=[dict(colour=b['colour'], name=b['name'], steps=b['steps'], stitches=b['stitches'],
                             stop=b['stop'], match=matches.get(b['colour'])) for b in blocks],
                supplies=supplies_for(data, kind, piece))


def _path(g):
    d = []
    for p in getattr(g, 'geoms', [g]):
        if p.is_empty or p.geom_type != 'Polygon':
            continue
        for ring in [p.exterior] + list(p.interiors):
            d.append('M' + ' L'.join('%.2f,%.2f' % c for c in list(ring.coords)[:-1]) + ' Z')
    return ' '.join(d)


@app.post('/api/preview')
def preview_start():
    data = request.get_json(force=True)
    err = check_request(data)
    if err:
        return jsonify(error=err), 400
    PREVIEW['want'] += 1
    PREVIEW['data'] = data
    PREVIEW['status'] = 'starting'
    PREVIEW['event'].set()
    return jsonify(gen=PREVIEW['want'])


@app.get('/api/preview/<int:gen>')
def preview_get(gen):
    r = PREVIEW['results'].get(gen)
    if r:
        return jsonify(r)
    if gen < PREVIEW['want']:
        return jsonify(status='stale')
    return jsonify(status='working', message=PREVIEW.get('status') or '')


@app.get('/api/preview/png/<int:gen>')
def preview_png(gen):
    p = WORK / 'preview' / ('p%d.png' % gen)
    if not p.exists():
        abort(404)
    return send_file(p, max_age=0)


# ---------------------------------------------------------------- pieces for arranging

@app.post('/api/makeitem')
def make_item():
    """Turn words, a monogram or artwork into stitches you can drag about in Arrange."""
    data = request.get_json(force=True)
    what = data.get('what')
    job = dict(status='', log=[])
    status = lambda s: None
    opts = make_options(dict(data, kind='design'), 2.0)
    try:
        with LOCK:
            if what == 'text':
                lines = parse_lines(dict(lines=[data.get('line') or {}]))
                if not lines:
                    return jsonify(error='Type some words first.'), 400
                res = produce.text_line_result(lines[0], opts, job['log'])
                name = lines[0].text[:30]
            elif what == 'monogram':
                c = make_content(None, dict(data, source='monogram', kind='design'), 'monogram', 'design', 0.0, 1.0,
                                 opts, job['log'], status)
                res = c.render(1.0)
                m = data.get('monogram') or {}
                name = 'Monogram ' + ''.join((m.get(k) or '') for k in ('first', 'middle', 'last'))
            elif what == 'art':
                up = UPLOADS.get(data.get('id'))
                if not up or up.get('stitch'):
                    return jsonify(error='Add the artwork first.'), 400
                inches = num(data, 'size_in', 2.0, 0.4, 12)
                colours = int(data.get('colours') or 3)
                art = up.get('art') if up.get('art_colours') == colours else None
                art = art or artmod.load(up['path'], colours)
                up['art'], up['art_colours'] = art, colours
                o2 = make_options(dict(data, kind='design'), inches)
                res = produce.art_content(art, o2, inches, job['log']).render(1.0)
                name = '%s %s"' % (up['name'], ('%g' % inches))
            else:
                return jsonify(error='Unknown item.'), 400
    except Exception as e:
        return jsonify(error=str(e)), 400
    res = res.centred()
    res.made = True
    uid = uuid.uuid4().hex[:10]
    d = WORK / 'uploads' / uid
    d.mkdir(parents=True, exist_ok=True)
    pat, _ = stepmod.assemble(res.steps)
    path = d / 'item.vp3'
    import pystitch
    pystitch.write(pat, str(path))
    UPLOADS[uid] = dict(path=path, name=safe_name(name), stitch=True, filename=name, result=res)
    out = dict(id=uid, name=name, filename=name, stitch=True)
    out.update(stitch_info(uid))
    return jsonify(out)


@app.post('/api/job/<jid>/stops')
def set_stops(jid):
    """Change the stops of one piece and write its files again (fast, no re-stitching)."""
    j = JOBS.get(jid)
    data = request.get_json(force=True)
    if not j:
        abort(404)
    i = int(data.get('index', 0))
    r = j['results'][i]
    new = output.refinish(j['out'], r['base'], data.get('stops') or [])
    new.update({k: r[k] for k in ('label', 'base', 'inches', 'scale', 'kind')})
    j['results'][i] = new
    write_readme(j['out'], j['results'])
    return jsonify(new)


@app.get('/api/job/<jid>')
def job_status(jid):
    j = JOBS.get(jid)
    if not j:
        abort(404)
    return jsonify({k: v for k, v in j.items() if k not in ('log', 'trace')})


@app.get('/api/job/<jid>/file/<name>')
def job_file(jid, name):
    j = JOBS.get(jid)
    if not j:
        abort(404)
    p = Path(j['out']) / Path(name).name
    if not p.exists():
        abort(404)
    inline = name.endswith(('.png', '.html', '.pdf', '.svg'))
    return send_file(p, as_attachment=not inline)


@app.get('/api/job/<jid>/zip')
def job_zip(jid):
    j = JOBS.get(jid)
    if not j:
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(Path(j['out']).iterdir()):
            if p.is_file():
                z.write(p, p.name)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=Path(j['out']).name + '.zip', mimetype='application/zip')


@app.post('/api/job/<jid>/reveal')
def reveal(jid):
    j = JOBS.get(jid)
    if j and sys.platform == 'darwin':
        os.system('open "%s"' % j['out'])
    return jsonify(ok=True)


# ---------------------------------------------------------------- 1.3: tags, your files, folders, shapes

@app.get('/api/tags')
def tag_list():
    return jsonify([dict(key=k, label=lab, d=d) for k, (lab, d) in tagmod.catalogue().items()])


@app.get('/api/library')
def library_list():
    s = load_settings()
    frames = []
    for k, f in library.frame_files(s.get('frame_folders') or []).items():
        frames.append(dict(key=k, name=f.name, tag=f.tag, folder=f.folder, sizes=f.size_list()))
    frames.sort(key=lambda f: f['name'].lower())
    return jsonify(frames=frames, monograms=library.fonts(s.get('monogram_folders') or []),
                   frames_dir=str(library.FRAMES_DIR), tags_dir=str(library.TAGS_DIR), mono_dir=str(library.MONO_DIR))


@app.get('/api/libpreview')
def library_preview():
    """Small picture of one of your frame files (first part of a size) or a monogram letter."""
    s = load_settings()
    size = int(num(request.args, 'px', 160, 40, 600))
    if request.args.get('frame'):
        f = library.find_frame(request.args['frame'], s.get('frame_folders') or [])
        if not f:
            abort(404)
        parts = f.sizes.get(request.args.get('size') or '') or next(iter(f.sizes.values()))
        if len(parts) > 1:
            return send_file(_parts_preview(parts, size))
        return send_file(library.preview_png(parts[0][1], size))
    if request.args.get('set'):
        ls = library.find_set(request.args['set'], s.get('monogram_folders') or [])
        if not ls:
            abort(404)
        letter = (request.args.get('letter') or 'M').upper()
        path = library.letter_path(ls, letter, 'center') or library.letter_path(ls, letter) or \
            next(iter(ls.letters.values()))
        return send_file(library.preview_png(path, size))
    abort(404)


def _parts_preview(parts, size):
    """Left and right halves side by side."""
    from PIL import Image
    ims = [Image.open(library.preview_png(p, size)) for _, p in sorted(parts, key=lambda x: {'left': 0, 'top': 0}.get(x[0], 1))]
    W = sum(i.width for i in ims) + 8 * (len(ims) - 1)
    H = max(i.height for i in ims)
    out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    x = 0
    for i in ims:
        out.paste(i, (x, (H - i.height) // 2))
        x += i.width + 8
    out.thumbnail((size, size))
    p = library.CACHE / ('parts_%s_%d.png' % (library._key(*[p for _, p in parts]), size))
    out.save(p)
    return p


def _choose_folder(prompt):
    """Ask the Mac for a folder (Finder's own chooser)."""
    if sys.platform != 'darwin':
        return None
    import subprocess
    r = subprocess.run(['osascript', '-e', 'POSIX path of (choose folder with prompt "%s")' % prompt],
                       capture_output=True, text=True, timeout=600)
    p = r.stdout.strip()
    return p or None


@app.post('/api/folders/add')
def folder_add():
    data = request.get_json(force=True)
    kind = 'monogram_folders' if data.get('kind') == 'monogram' else 'frame_folders'
    path = data.get('path') or _choose_folder('Choose the folder with your %s' % (
        'monogram letter files' if kind == 'monogram_folders' else 'frame files'))
    if not path:
        return jsonify(error='No folder chosen.'), 400
    if not Path(path).is_dir():
        return jsonify(error='That folder was not found.'), 400
    s = load_settings()
    lst = [x for x in s.get(kind) or [] if x != path] + [path]
    s[kind] = lst
    HOME_OUT.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2))
    return jsonify(s)


@app.post('/api/folders/remove')
def folder_remove():
    data = request.get_json(force=True)
    kind = 'monogram_folders' if data.get('kind') == 'monogram' else 'frame_folders'
    s = load_settings()
    s[kind] = [x for x in s.get(kind) or [] if x != data.get('path')]
    SETTINGS.write_text(json.dumps(s, indent=2))
    return jsonify(s)


@app.post('/api/folders/open')
def folder_open():
    data = request.get_json(force=True)
    p = {'frames': library.FRAMES_DIR, 'tags': library.TAGS_DIR, 'monogram': library.MONO_DIR,
         'output': HOME_OUT}.get(data.get('which'), HOME_OUT)
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
        import subprocess
        subprocess.Popen(['open', str(p)])
    return jsonify(path=str(p))


@app.post('/api/artshapes')
def art_shapes():
    """The separate shapes of the artwork, for clicking on to change them."""
    data = request.get_json(force=True)
    up = UPLOADS.get(data.get('id'))
    if not up or up.get('stitch'):
        return jsonify(error='Add your artwork first.'), 400
    colours = int(data.get('colours') or 3)
    art = up.get('art') if up.get('art_colours') == colours else None
    art = art or artmod.load(up['path'], colours)
    up['art'], up['art_colours'] = art, colours
    s = max(art.width, art.height)
    return jsonify(shapes=shapeedit.svg_paths(art, 100.0), w=100.0 * art.width / s, h=100.0 * art.height / s,
                   colours=[c for c, _ in art.layers])


LAST_PING = [time.time()]


@app.post('/api/ping')
def ping():
    LAST_PING[0] = time.time()
    return jsonify(ok=True)


@app.post('/api/quit')
def quit_app():
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify(ok=True)


def _watch_idle(limit=600):
    """Started by the Mac app: quit by itself once no StitchKit window has been open for a while."""
    while True:
        time.sleep(30)
        busy = any(j.get('status') not in ('finished', 'failed') for j in JOBS.values())
        if not busy and time.time() - LAST_PING[0] > limit:
            os._exit(0)


# ---------------------------------------------------------------- projects

@app.get('/api/projects')
def project_list():
    PROJECTS.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(PROJECTS.glob('*.stitchkit'), key=lambda p: -p.stat().st_mtime):
        out.append(dict(name=p.stem, saved=time.strftime('%b %d, %Y %I:%M %p', time.localtime(p.stat().st_mtime))))
    return jsonify(out)


@app.post('/api/projects/save')
def project_save():
    data = request.get_json(force=True)
    name = safe_name(data.get('name') or 'project')
    PROJECTS.mkdir(parents=True, exist_ok=True)
    path = PROJECTS / (name + '.stitchkit')
    state = data.get('state') or {}
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        files = {}
        for uid in set(data.get('uploads') or []):
            up = UPLOADS.get(uid)
            if up and Path(up['path']).exists():
                arc = 'files/%s%s' % (uid, Path(up['path']).suffix)
                z.write(up['path'], arc)
                files[uid] = dict(arc=arc, name=up['name'], stitch=up['stitch'], filename=up.get('filename', ''))
        z.writestr('project.json', json.dumps(dict(version=VERSION, state=state, files=files), indent=1))
    return jsonify(name=name, path=str(path))


@app.post('/api/projects/open')
def project_open():
    data = request.get_json(force=True)
    path = PROJECTS / (safe_name(data.get('name')) + '.stitchkit')
    if not path.exists():
        return jsonify(error='That project is not in Documents/StitchKit/Projects any more.'), 404
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read('project.json'))
        for uid, f in meta.get('files', {}).items():
            d = WORK / 'uploads' / uid
            d.mkdir(parents=True, exist_ok=True)
            dest = d / ('art' + Path(f['arc']).suffix)
            dest.write_bytes(z.read(f['arc']))
            UPLOADS[uid] = dict(path=dest, name=f['name'], stitch=f['stitch'], filename=f.get('filename', ''))
    return jsonify(meta)


@app.get('/static/<path:name>')
def static_file(name):
    p = (ROOT / 'assets' / Path(name).name)
    if not p.exists():
        abort(404)
    return send_file(p)


@app.get('/')
def index():
    return Response((ROOT / 'ui.html').read_text().replace('{{VERSION}}', VERSION), mimetype='text/html')


def port_in_use():
    import socket
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', PORT)) == 0


OLD_APP_ITEMS = ['app.py', 'engine', 'inkstitch_engine', 'ui.html', 'Install StitchKit.command', 'Open StitchKit.command',
                 'requirements.txt', 'requirements-nodeps.txt', 'samples', 'tests', 'README.txt', 'VERSION',
                 'WHATS_NEW.txt', '.venv', 'assets', 'macapp', 'design_refs']


def tidy_old_app():
    """1.2 lived in a folder you put somewhere yourself; if that was Documents/StitchKit (where your things are
    kept), move its old program files into one folder you can throw away. Nothing of yours is touched."""
    try:
        if ROOT.resolve() == HOME_OUT.resolve() or not (HOME_OUT / 'app.py').exists() or \
                not (HOME_OUT / 'inkstitch_engine').exists():
            return
        dest = HOME_OUT / 'Old StitchKit app (safe to delete)'
        dest.mkdir(exist_ok=True)
        for name in OLD_APP_ITEMS:
            src = HOME_OUT / name
            if src.exists() and not (dest / name).exists():
                shutil.move(str(src), str(dest / name))
    except Exception:
        pass


def main():
    if '--auto-quit' in sys.argv:
        tidy_old_app()
    if port_in_use():
        print('StitchKit is already running; opening it in your browser.')
        webbrowser.open('http://127.0.0.1:%d' % PORT)
        return
    WORK.mkdir(parents=True, exist_ok=True)
    HOME_OUT.mkdir(parents=True, exist_ok=True)
    PROJECTS.mkdir(exist_ok=True)
    threads.ensure_my_threads()
    frames = HOME_OUT / 'Frames'
    frames.mkdir(exist_ok=True)
    howto = frames / 'How to add frames.txt'
    if not howto.exists() or "Stitch files" not in howto.read_text():
        howto.write_text('Two kinds of frames go here:\n\n'
                         '1. Stitch files of frames you own (VP3, PES, DST...). StitchKit keeps their stitches exactly\n'
                         '   as they are and sews your design after the tackdown and before the final satin. Sizes in\n'
                         '   the name are grouped (Wreath_4in.vp3, Wreath_5in.vp3). Halves saved as two files go in\n'
                         '   a folder together, named ..._left and ..._right (or L and R).\n\n'
                         '2. Frame shapes as SVG files (outer outline, and the inner one if you like) that StitchKit\n'
                         '   digitizes itself. The file name becomes the frame name.\n\n'
                         'Reload StitchKit in your browser to see new frames.\n')
    url = 'http://127.0.0.1:%d' % PORT
    threading.Thread(target=_preview_worker, daemon=True).start()
    if '--auto-quit' in sys.argv:
        threading.Thread(target=_watch_idle, daemon=True).start()
    for d in (library.FRAMES_DIR, library.TAGS_DIR, library.MONO_DIR):
        d.mkdir(parents=True, exist_ok=True)
    mh = library.MONO_DIR / 'How to add monogram letters.txt'
    if not mh.exists():
        mh.write_text('Put each set of monogram letter files in its own folder here, one file per letter\n'
                      '(A.vp3 ... Z.vp3, or names that end in the letter, like Blair_13QA.vp3).\n'
                      'Name the folder after the font and size: WesternShadow1 = 1 inch, WesternShadow1H = 1.5 inch,\n'
                      'WesternShadow2H = 2.5 inch, Script 38mm = 38 mm. Sets of one font in different sizes are grouped.\n'
                      'Already keep your letters somewhere else? Add that folder in StitchKit Settings instead.\n')
    th = library.TAGS_DIR / 'How to add bag tags.txt'
    if not th.exists():
        th.write_text('Put your bag tag stitch files here (VP3, PES, DST...). Sizes in the name are grouped, so\n'
                      'TAG-23_3.5_INCH.vp3 and TAG-23_4.0_INCH.vp3 become one tag, TAG-23, in two sizes.\n'
                      'StitchKit finds the placement line, tackdown and satin, adds the stops, and sews your design\n'
                      'after the front fabric is tacked down and before the foam goes on.\n')
    if '--no-browser' not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print('\nStitchKit %s is running at %s\nLeave this window open while you use it. Close it to quit.\n' % (VERSION, url))
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)


if __name__ == '__main__':
    main()
