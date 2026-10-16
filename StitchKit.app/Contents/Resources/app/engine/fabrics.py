"""Fabric presets: stitch settings plus the supplies to use (needle, stabilizer, topping, extras).

The supply notes are a starting point; you can change any of them in Settings and your versions are
kept in Documents/StitchKit/fabrics.json.
"""
import copy
import json
from pathlib import Path

USER_FILE = Path.home() / 'Documents' / 'StitchKit' / 'fabrics.json'

FABRICS = {
    'twill': dict(
        name='Patch twill', density='normal', pull_mm=0.20, knockdown=False,
        needle='75/11 sharp embroidery needle',
        stabilizer='Medium tear-away under the twill (cut-away for a softer patch)',
        topping='None needed',
        extras='Iron-on patch backing after stitching if you want to iron it on. Hot knife or sharp scissors to cut out.'),
    'fleece': dict(
        name='Sweatshirt fleece', density='normal', pull_mm=0.40, knockdown=True,
        needle='75/11 ballpoint embroidery needle',
        stabilizer='Medium cut-away (fusible no-show mesh on light colours)',
        topping='Water-soluble topping so stitches sit on top of the pile',
        extras='Knockdown stitch is on: it flattens the fleece under the design.'),
    'tshirt': dict(
        name='T-shirt knit', density='light', pull_mm=0.35, knockdown=False,
        needle='75/11 ballpoint embroidery needle',
        stabilizer='No-show mesh (polymesh) cut-away, fused to the back',
        topping='Optional: water-soluble topping on slub or textured knits',
        extras='Hoop gently without stretching the knit. Light density keeps the shirt soft.'),
    'cotton': dict(
        name='Bandana / quilting cotton', density='light', pull_mm=0.20, knockdown=False,
        needle='75/11 sharp embroidery needle',
        stabilizer='Medium tear-away (cut-away if it will be washed often)',
        topping='None needed',
        extras='Light density so the cotton doesn\'t pucker.'),
    'towel': dict(
        name='Towel / terry', density='normal', pull_mm=0.35, knockdown=True,
        needle='75/11 sharp, or 90/14 on thick towels',
        stabilizer='Tear-away or water-soluble on the back (sticky stabilizer if you float the towel)',
        topping='Water-soluble topping: needed so loops don\'t poke through',
        extras='Knockdown stitch is on: it flattens the loops under the design.'),
    'canvas': dict(
        name='Canvas', density='normal', pull_mm=0.20, knockdown=False,
        needle='90/14 sharp embroidery needle',
        stabilizer='Medium tear-away',
        topping='None needed',
        extras=''),
    'denim': dict(
        name='Denim', density='normal', pull_mm=0.20, knockdown=False,
        needle='90/14 denim or titanium sharp needle',
        stabilizer='Medium tear-away (cut-away on stretch denim)',
        topping='None needed',
        extras=''),
    'cap': dict(
        name='Cap', density='normal', pull_mm=0.25, knockdown=False,
        needle='75/11 or 90/14 sharp (titanium lasts longer on buckram)',
        stabilizer='Cap backing or firm tear-away. On a flat-bed machine: sticky stabilizer with a cap front, '
                   'or stitch a patch and sew it on',
        topping='None needed',
        extras='Keep cap designs about 2.25 in (57 mm) tall or less.'),
}

# extra supplies that depend on what is being made, not the fabric
PATCH_FILM = ('Heavy water-soluble film (such as Badgemaster), one or two layers. Trim, then rinse; leave a '
              'little in for a stiffer patch')
APPLIQUE_FUSE = 'HeatnBond Lite (or another light fusible) on the back of the appliqué fabric before cutting'
SATIN_TOPPING = 'Light water-soluble topping keeps satin edges crisp'


def load():
    out = copy.deepcopy(FABRICS)
    try:
        mine = json.loads(USER_FILE.read_text())
        for k, v in mine.items():
            if k in out and isinstance(v, dict):
                out[k].update({kk: vv for kk, vv in v.items() if kk in ('needle', 'stabilizer', 'topping', 'extras')})
    except Exception:
        pass
    return out


def save_user(key, fields):
    try:
        mine = json.loads(USER_FILE.read_text())
    except Exception:
        mine = {}
    mine[key] = {k: str(v)[:400] for k, v in fields.items() if k in ('needle', 'stabilizer', 'topping', 'extras')}
    USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_FILE.write_text(json.dumps(mine, indent=2))


def supplies(fabric_key, kind='design', applique=False, stitched_background=False, satin_edges=False):
    """The supplies list for one piece: [(label, text)]."""
    f = load().get(fabric_key) or load()['twill']
    rows = [('Fabric', f['name']), ('Needle', f['needle'])]
    if stitched_background:
        rows.append(('Stabilizer', PATCH_FILM))
    else:
        rows.append(('Stabilizer', f['stabilizer']))
    top = f['topping']
    if satin_edges and top.lower().startswith('none'):
        top = SATIN_TOPPING if kind in ('patch', 'frame') else top
    rows.append(('Topping', top))
    if applique:
        rows.append(('Appliqué', APPLIQUE_FUSE))
        if kind == 'patch':
            rows.append(('Base', 'Peltex I 71F (optional) under the appliqué fabric gives a firm, stiff patch'))
    if f.get('extras'):
        rows.append(('Also', f['extras']))
    return rows
