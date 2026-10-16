"""1.3 checks: bag tags, your own frame/tag files, monogram letter sets, shape editing, bamboo frames,
the live preview. Runs in a throw-away home folder (about two minutes)."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = tempfile.mkdtemp()
os.environ['HOME'] = HOME
sys.path.insert(0, str(ROOT))
import pystitch                                                     # noqa: E402
from engine import (produce, output, tags, library, text, art, shapeedit, stitchparts, region, steps as sm,   # noqa: E402
                    existing, bamboo)
from engine.plan import Options                                     # noqa: E402

log = []
out = Path(HOME) / 'out'
ok = []


def check(name, cond, info=''):
    print(('ok   ' if cond else 'FAIL ') + name + ('  ' + str(info) if info else ''))
    ok.append(bool(cond))


# ---- names
check('size token', library.size_token('TAG-23_4.0_INCH')[1:] == (101.6, '4"'))
check('part token', library.part_token('Leaf_Left') == ('Leaf', 'left'))
check('set size 1H', library.set_size('WesternShadow1H')[2] == '1.5"')
check('set size 2H', library.set_size('WesternShadow2H')[2] == '2.5"')

# ---- built-in bag tags, every shape, no design
for key in tags.TAG_SHAPES:
    lay = tags.layout(key, 101.6)
    ring_ok = lay.outer.buffer(-(lay.border + 0.5)).contains(lay.ring())
    check('tag layout %s' % key, ring_ok and lay.region.area > 400, round(lay.region.area))
word, _ = produce.text_content([text.Line('Kit', 'emb:barstitch_bold', height_mm=14)], None, Options(), 3, 'center', log)
t = produce.make_tag_piece(word, Options(mode='patch', tag=True, tag_shape='classic'), 101.6, log)
r = output.finish(t, out, 'tag', ['vp3'], supplies=tags.supplies())
names = [b['name'] for b in r['blocks']]
check('tag stops', [s.label for s in t.steps if s.stop_after][:3] == ['Placement line', 'Text "Kit"', 'Tackdown'],
      [s.label for s in t.steps if s.stop_after])
check('tag satin and ring in one block', names.count('Trim cotton, then dense satin') == 1, names)
check('tag guide', len(t.guide) >= 10 and 'punch' in ' '.join(t.guide).lower())
check('tag cricut', any(f.endswith('_cricut.svg') for f in r['files']))
sheet = (out / 'tag_thread_sheet.html').read_text()

# ---- a tag file of our own making, read back as one of "your" tag files
blank = produce.make_tag_piece(None, Options(mode='patch', tag=True, tag_shape='scalloped'), 4 * 25.4, log)
tdir = library.TAGS_DIR
tdir.mkdir(parents=True, exist_ok=True)
pat, _ = sm.assemble([s for s in blank.steps if s.label != 'Tack front cotton'])
pystitch.write(pat, str(tdir / 'Scallop_4in.vp3'))
pystitch.write(pat, str(tdir / 'Scallop_5in.vp3'))
ff = library.frame_files()
f = next(iter(ff.values()))
check('tag file grouped by size', [s['label'] for s in f.size_list()] == ['4"', '5"'], f.size_list())
steps = sm.steps_from_pattern(existing.read_stitch_file(tdir / 'Scallop_4in.vp3'))
st2, info = stitchparts.roles(steps)
check('tag file parts', len(info['outlines']) == 2, info)
p = produce.make_file_frame_piece(word, f, '4"', Options(mode='patch', frame=True), log, tag=True)
labels = [s.label for s in p.steps]
check('tag file order', labels.index('Tack front cotton') < labels.index('Text "Kit"') < labels.index('Tackdown'), labels)

# ---- split frame: left and right files around the design
fdir = library.FRAMES_DIR / 'Wreath'
fdir.mkdir(parents=True, exist_ok=True)
a = art.load(ROOT / 'samples' / 'Silhouette.svg')
half = produce.art_content(a, Options(size_in=1.5), 1.5, log).render(1.0).centred()
pat, _ = sm.assemble(half.steps)
pystitch.write(pat, str(fdir / 'Wreath_L.vp3'))
pystitch.write(pat, str(fdir / 'Wreath_R.vp3'))
wr = [x for x in library.frame_files().values() if x.name == 'Wreath'][0]
p = produce.make_file_frame_piece(word, wr, 'as is', Options(mode='patch', frame=True), log)
w, h = p.size_mm()
check('split frame placed round the design', w > 2 * half.size_mm()[0] + word.render(1).size_mm()[0], (round(w), round(h)))

# ---- monogram letter sets
mdir = library.MONO_DIR / 'Tester' / 'Tester1'
mdir2 = library.MONO_DIR / 'Tester' / 'Tester1H'
for d, hmm in ((mdir, 20), (mdir2, 30)):
    d.mkdir(parents=True, exist_ok=True)
    for L in 'ABCMK':
        pystitch.write(text.emb_line(text.Line(L, 'emb:barstitch_bold', height_mm=hmm)), str(d / ('Fancy_%s.vp3' % L)))
fonts = library.fonts()
check('letter sets grouped', fonts and fonts[0]['font'] == 'Tester' and len(fonts[0]['sets']) == 2, fonts)
sets = list(library.letter_sets().values())
small = min(sets, key=lambda s: s.size_mm)
big = max(sets, key=lambda s: s.size_mm)
mono = produce.letters_result(small, ('A', 'K', 'M'), 'classic', 1.5, big_set=big)
check('classic monogram from files', len(mono.steps) == 3 and mono.size_mm()[1] > 25, mono.size_mm())
check('letter preview', library.preview_png(big.letters['M']).exists())

# ---- click-a-shape changes
hat = art.load(ROOT / 'samples' / 'TopHat.svg')
sh = sorted(shapeedit.shapes(hat), key=lambda x: -x[2].area)
edits = {sh[0][0]: {'applique': True, 'edge': 'blanket'}, sh[1][0]: {'angle': 0}, sh[2][0]: {'stitch': 'outline'}}
res = produce.art_content(hat, Options(size_in=3, shape_edits=edits), 3, log).render(1.0)
check('appliqué shape has fabric', len(res.fabric) == 1)
check('appliqué stops', [s.label for s in res.steps if s.stop_after] == ['Placement line', 'Tackdown'],
      [s.label for s in res.steps if s.stop_after])

# ---- bamboo frames all build
for k in bamboo.ALL:
    d = bamboo.ALL[k]()
    check('bamboo %s' % k, d['inner'] is not None and d['inner'].area > 0.5 and d['cells'], round(d['inner'].area, 2))
o = Options(mode='patch', frame=True, frame_key='bamboo_oval', frame_band='fill', patch_in=4)
bp = produce.make_piece(word, o, 101.6, log)
check('bamboo oval stitches', len(bp.steps) >= 3, [s.label for s in bp.steps])

# ---- region fitting
from shapely.geometry import box, Point
k, x, y, fits = region.best_fit(Point(0, 0).buffer(30), box(0, 0, 20, 10), 'both')
check('fit grows into a circle', fits and 2.3 < k < 2.8, round(k, 2))

# ---- live preview through the app
import threading                                                    # noqa: E402
import app as A                                                     # noqa: E402
threading.Thread(target=A._preview_worker, daemon=True).start()
c = A.app.test_client()
g = c.post('/api/preview', json={'source': 'text', 'kind': 'tag', 'tag_shape': 'heart', 'sizes': [3.5],
                                 'lines': [{'text': 'Hi', 'font': 'emb:barstitch_bold', 'height_in': 0.5}]}).get_json()['gen']
for _ in range(120):
    rr = c.get('/api/preview/%d' % g).get_json()
    if rr['status'] != 'working':
        break
    time.sleep(0.5)
check('preview', rr['status'] == 'done' and rr['guide'] and c.get(rr['png']).status_code == 200, rr.get('error'))
lib = c.get('/api/library').get_json()
check('library api', len(lib['frames']) == 2 and lib['monograms'], [f['name'] for f in lib['frames']])
print('\n%d of %d checks passed' % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
