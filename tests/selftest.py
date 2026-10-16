"""Quick check that StitchKit works on this computer (about a minute)."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import art, produce, output, text     # noqa: E402
from engine.plan import Options                     # noqa: E402

with tempfile.TemporaryDirectory() as d:
    log = []
    a = art.load(ROOT / 'samples' / 'Silhouette.svg')
    o = Options(mode='design', size_in=1.5)
    r = output.finish(produce.art_content(a, o, 1.5, log).render(1.0), d, 'design', ['vp3', 'vip'])
    assert r['stats']['stitches'] > 500, r['stats']
    o = Options(mode='patch', frame=True, frame_key='notched', frame_band='applique')
    content, _ = produce.text_content([text.Line('Hi', 'emb:barstitch_bold', height_mm=14)], None, o, 3, 'center', log)
    r2 = output.finish(produce.make_piece(content, o, 0, log), d, 'frame', ['vp3'])
    assert r2['stats']['stitches'] > 500 and any(f.endswith('.svg') for f in r2['files']), r2['files']
    print('Self-test passed: design %d stitches, framed text %d stitches.'
          % (r['stats']['stitches'], r2['stats']['stitches']))
