"""Wider regression test (several minutes). Writes into the folder given (default: a temp folder)."""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pystitch                                                    # noqa: E402
from engine import art, produce, output, text, vip, hoops, threads  # noqa: E402
from engine.plan import Options                                    # noqa: E402

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
out.mkdir(parents=True, exist_ok=True)
log = []
silo = art.load(ROOT / 'samples' / 'Silhouette.svg')
hat = art.load(ROOT / 'samples' / 'TopHat.svg')
results = {}


def check(name, piece, target_mm=0, **kw):
    t = time.time()
    r = output.finish(piece, out, name, ['vp3', 'vip', 'pes'], **kw)
    st = r['stats']
    p = pystitch.read(str(out / (name + '.vp3')))
    assert sum(1 for s in p.stitches if s[2] & 0xFF == 0) == st['stitches']
    cols, recs, _ = vip.read(str(out / (name + '.vip')))
    assert sum(1 for c, x, y in recs if c == 0x80) == st['stitches'], 'VIP stitch count'
    assert st['longest_stitch_mm'] < 12.5, st['longest_stitch_mm']
    if target_mm and not kw.get('copies'):
        L = max(st['width_mm'], st['height_mm'])
        assert abs(L - target_mm) < 2.0 or any('smallest' in n for n in r['notes']), (name, L, target_mm, r['notes'])
    results[name] = r
    print('%-28s %6d stitches %5.1f x %5.1f mm  %-14s %d blocks  %.0fs' % (
        name, st['stitches'], st['width_mm'], st['height_mm'], r['hoop'][:14], len(r['blocks']), time.time() - t))
    return r


def piece(content, o, target):
    return produce.make_piece(content, o, target, log)


o = Options(mode='design', density='normal', satin_outline=True)
check('silhouette_design_3in', produce.art_content(silo, o, 3.0, log).render(1))

o = Options(mode='patch', patch_shape='circle', background='#2b4a6f')
check('tophat_circle_bg_3in', piece(produce.art_content(hat, o, 2.2, log), o, 76.2), 76.2)

o = Options(mode='patch', patch_shape='heart', fabric_method='applique')
r = check('heart_applique_x6', piece(produce.art_content(silo, o, 1.6, log), o, 63.5), copies=6, basting=True)
assert r['hoop_key'] == 'medium' and r['copies'] == 6
assert any('cricut' in f for f in r['files'])

for key, band in [('greek_key', 'applique'), ('bamboo_octagon', 'fill'), ('bamboo_square', 'none'),
                  ('label_scroll', 'applique'), ('shape:heart', 'none'), ('cloud', 'fill')]:
    o = Options(mode='patch', frame=True, frame_key=key, frame_band=band, frame_band_colour='#c8a860',
                frame_center='fill' if key == 'cloud' else 'fabric')
    c, _ = produce.text_content([text.Line('Deacs', 'emb:barstitch_bold', height_mm=14)], None, o, 3, 'center', log)
    check('frame_%s_%s' % (key.replace(':', '_'), band), piece(c, o, 100), 100)

o = Options(mode='patch', patch_shape='rounded')
mono = produce.monogram_result(('t', 'p', 's'), 'emb:barstitch_bold', 30, 'classic', '#6d1f2c', 2, o, log)
check('monogram_rounded', piece(produce.result_content(mono, 'none'), o, 0))

# stitch file in, with text below, as a patch with stops added after step 1
check('silhouette_design_3in_again', produce.result_content(
    produce.stitch_file_result(out / 'silhouette_design_3in.vp3'), 'none').render(1))
r = output.refinish(out, 'silhouette_design_3in_again', [0])
assert r['stops'] == [0]

# 1.2: fabric presets, knockdown, blanket edge, contour fill, appliqué found in a stitch file
o = Options(mode='design', fabric='towel', fill_style='contour')
r = check('towel_design_knockdown', produce.make_piece(produce.art_content(hat, o, 2.5, log), o, 0, log))
assert any(b['steps'][0] == 'Knockdown' for b in r['blocks']), r['blocks']
o = Options(mode='patch', patch_shape='circle', fabric_method='applique', edge_style='blanket')
check('circle_blanket', piece(produce.art_content(silo, o, 2.0, log), o, 76.2), 76.2)
found = produce.stitch_file_result(out / 'heart_applique_x6.vp3')
assert len(found.fabric) == 6, len(found.fabric)
assert threads.match('#6d1f2c', 'gpl:Isacord Polyester')

caps = hoops.capacity(60, 60, 8)
assert caps == {'small': 1, 'medium': 6, 'large': 10}, caps
m = threads.match('#151011', 'polyx40')
assert m and m['name'], m
print('All good. Files in', out)
