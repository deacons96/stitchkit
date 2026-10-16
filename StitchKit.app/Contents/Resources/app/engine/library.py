"""Your own stitch files used as building blocks: frames, bag tags and monogram letter sets.

Frames and tags
    Documents/StitchKit/Frames      any stitch files (VP3, PES, DST...). Sizes in the file name are
                                    grouped ("TAG-23_3.5_INCH", "TAG-23_4.0_INCH" become one frame,
                                    TAG-23, in three sizes). Files named ..._left / ..._right (or L / R)
                                    are the halves of one frame and go either side of your design.
    Documents/StitchKit/Bag Tags    the same, listed under Bag tag (files in Frames with "tag" in the
                                    name are listed there too)

Monogram letter sets
    Documents/StitchKit/Monogram Fonts, plus any folders you add in Settings. Any folder holding letter
    files (A.vp3 ... Z.vp3, or names ending in the letter like Blair_13QA.vp3) is a set. The folder name
    gives the font and the size: WesternShadow1 = 1 in, WesternShadow1H = 1.5 in, WesternShadow2H = 2.5 in,
    Script 38mm = 38 mm. Sets of the same font in different sizes are grouped.
"""
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .existing import STITCH_EXTS, is_stitch_file

DOCS = Path.home() / 'Documents' / 'StitchKit'
FRAMES_DIR = DOCS / 'Frames'
TAGS_DIR = DOCS / 'Bag Tags'
MONO_DIR = DOCS / 'Monogram Fonts'
CACHE = Path.home() / '.stitchkit' / 'cache'

# ---------------------------------------------------------------- names

_SIZE_PATTERNS = [
    (re.compile(r'(?:^|[ _\-.])(\d+(?:[._]\d+)?)[\s_\-]*(?:in|inch|inches|")(?=$|[ _\-.])', re.I), 'in'),
    (re.compile(r'(?:^|[ _\-.])(\d+(?:[._]\d+)?)[\s_\-]*mm(?=$|[ _\-.])', re.I), 'mm'),
    (re.compile(r'(?:^|[ _\-.])(\d+)\s*x\s*(\d+)(?=$|[ _\-.])', re.I), 'hoop'),
]
_PART = re.compile(r'(?:^|[ _\-.])(left|right|top|bottom|centre|center|middle|l|r)$', re.I)


def size_token(stem):
    """('4.0_INCH' style size in the name) -> (rest of the name, size in mm or None, label)."""
    for rx, unit in _SIZE_PATTERNS:
        m = rx.search(stem)
        if not m:
            continue
        rest = (stem[:m.start()] + ' ' + stem[m.end():]).strip(' _-.')
        if unit == 'hoop':
            a, b = float(m.group(1)), float(m.group(2))
            mm = max(a, b) * (25.4 if max(a, b) < 20 else 1)
            return rest, mm, '%sx%s' % (m.group(1), m.group(2))
        v = float(m.group(1).replace('_', '.'))
        mm = v * 25.4 if unit == 'in' else v
        lab = ('%g"' % v) if unit == 'in' else ('%g mm' % v)
        return rest, mm, lab
    return stem, None, ''


def part_token(stem):
    m = _PART.search(stem)
    if not m:
        return stem, ''
    w = m.group(1).lower()
    part = {'l': 'left', 'r': 'right', 'centre': 'center', 'middle': 'center'}.get(w, w)
    return stem[:m.start()].strip(' _-.'), part


def pretty(name):
    s = re.sub(r'[_]+', ' ', name).strip()
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)          # WesternShadow -> Western Shadow
    return re.sub(r'\s+', ' ', s).strip() or 'Frame'


def _key(*parts):
    return hashlib.sha1('|'.join(str(p) for p in parts).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- frames and tags

@dataclass
class FrameFile:
    key: str
    name: str
    folder: str
    sizes: dict = field(default_factory=dict)     # size label -> [(part, path)]
    tag: bool = False

    def size_list(self):
        out = []
        for lab, parts in self.sizes.items():
            out.append(dict(label=lab, parts=[p for p, _ in parts], mm=_label_mm(lab)))
        out.sort(key=lambda d: (d['mm'] or 0, d['label']))
        return out


def _label_mm(lab):
    m = re.match(r'([\d.]+)"', lab or '')
    if m:
        return float(m.group(1)) * 25.4
    m = re.match(r'([\d.]+) mm', lab or '')
    if m:
        return float(m.group(1))
    m = re.match(r'(\d+)x(\d+)', lab or '')
    if m:
        v = max(float(m.group(1)), float(m.group(2)))
        return v * 25.4 if v < 20 else v
    return None


def _scan_folder(root: Path, tag_folder=False):
    out = {}
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        rel = os.path.relpath(dirpath, root)
        for fn in sorted(filenames):
            if fn.startswith('.') or not is_stitch_file(fn):
                continue
            stem = Path(fn).stem
            rest, mm, lab = size_token(stem)
            rest, part = part_token(rest)
            base = rest or (Path(dirpath).name if rel != '.' else stem)
            # a file on its own in a sub-folder takes the folder's name if its own is just a size
            name = pretty(base)
            k = _key(root, rel, base.lower())
            f = out.get(k) or FrameFile(k, name, rel)
            lab = lab or 'as is'
            f.sizes.setdefault(lab, []).append((part or 'whole', str(Path(dirpath) / fn)))
            f.tag = tag_folder or 'tag' in base.lower() or 'tag' in rel.lower()
            out[k] = f
    return out


def frame_files(extra_folders=()):
    out = {}
    for k, f in _scan_folder(FRAMES_DIR).items():
        out['file:' + k] = f
    for k, f in _scan_folder(TAGS_DIR, tag_folder=True).items():
        out['file:' + k] = f
    for d in extra_folders or []:
        for k, f in _scan_folder(Path(d)).items():
            out['file:' + k] = f
    return out


def find_frame(key, extra_folders=()):
    return frame_files(extra_folders).get(key)


# ---------------------------------------------------------------- monogram letter sets

_LETTER = re.compile(r'([A-Za-z])$')
_POS = re.compile(r'(?:^|[ _\-])(left|right|center|centre|middle|l|c|m|r)$', re.I)
_SET_SIZE = [
    re.compile(r'(\d+)\s*H$', re.I),                       # 1H = 1.5 in, 2H = 2.5 in
    re.compile(r'(\d+(?:[._]\d+)?)\s*(?:in|inch|inches|")$', re.I),
    re.compile(r'(\d+(?:[._]\d+)?)\s*mm$', re.I),
    re.compile(r'(\d+(?:[._]\d+)?)$'),                     # a plain number at the end = inches
]


def set_size(folder_name):
    """'WesternShadow1H' -> ('WesternShadow', 38.1, '1.5"')."""
    n = folder_name.strip()
    for i, rx in enumerate(_SET_SIZE):
        m = rx.search(n)
        if not m:
            continue
        rest = n[:m.start()].strip(' _-')
        if not rest:
            continue
        v = float(m.group(1).replace('_', '.'))
        if i == 0:
            inches = v + 0.5
            return rest, inches * 25.4, '%g"' % inches
        if i == 2:
            return rest, v, '%g mm' % v
        if v > 20:              # a big plain number is millimetres
            return rest, v, '%g mm' % v
        return rest, v * 25.4, '%g"' % v
    return n, None, ''


@dataclass
class LetterSet:
    key: str
    font: str
    size_label: str
    size_mm: float
    folder: str
    letters: dict = field(default_factory=dict)     # 'A' -> path   (or 'A@left' -> path for position sets)
    positions: bool = False


def _letters_in(dirpath, filenames):
    found = {}
    for fn in filenames:
        if fn.startswith('.') or not is_stitch_file(fn):
            continue
        stem = Path(fn).stem.strip()
        pos = ''
        m = _POS.search(stem)
        stem2 = stem
        if m and len(stem) > len(m.group(0)) and m.group(1).lower() not in ('l', 'c', 'm', 'r'):
            pos = {'centre': 'center', 'middle': 'center'}.get(m.group(1).lower(), m.group(1).lower())
            stem2 = stem[:m.start()]
        lm = _LETTER.search(stem2.strip(' _-'))
        if not lm:
            continue
        letter = lm.group(1).upper()
        k = letter + ('@' + pos if pos else '')
        # prefer the shortest name if two files give the same letter (A.vp3 over Blair_A_copy.vp3)
        if k not in found or len(fn) < len(Path(found[k]).name):
            found[k] = str(Path(dirpath) / fn)
    return found


def letter_sets(extra_folders=()):
    roots = [MONO_DIR] + [Path(d) for d in (extra_folders or [])]
    out = {}
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            found = _letters_in(dirpath, filenames)
            # sub-folders named Left / Center / Right hold position sets
            plain = {k: v for k, v in found.items() if '@' not in k}
            if len(set(k[0] for k in found)) < 5:
                continue
            folder = Path(dirpath).name
            parent = Path(dirpath).parent.name
            font, mm, lab = set_size(folder)
            if mm is None and parent and parent != root.name:
                # size folders inside a font folder: Script/1in, Script/2in
                f2, mm2, lab2 = set_size(parent + folder) if re.match(r'^\d', folder) else (folder, None, '')
                if mm2:
                    font, mm, lab = parent, mm2, lab2
            k = _key(dirpath)
            out[k] = LetterSet(k, pretty(font), lab, mm or 0.0, str(dirpath), found,
                               positions=len(plain) < len(found))
    return out


def fonts(extra_folders=()):
    """Monogram fonts for the app: [{font, sets: [{key, label, mm, letters}]}], sizes smallest first."""
    by = {}
    for s in letter_sets(extra_folders).values():
        by.setdefault(s.font.lower(), []).append(s)
    out = []
    for _k, sets in sorted(by.items()):
        sets.sort(key=lambda s: (s.size_mm or 0))
        out.append(dict(font=sets[0].font, sets=[dict(key=s.key, label=s.size_label or 'as is', mm=s.size_mm,
                                                       letters=''.join(sorted(set(k[0] for k in s.letters))),
                                                       positions=s.positions) for s in sets]))
    return out


def find_set(key, extra_folders=()):
    return letter_sets(extra_folders).get(key)


def letter_path(lset: LetterSet, letter, position=''):
    letter = (letter or '').upper()[:1]
    if position and (letter + '@' + position) in lset.letters:
        return lset.letters[letter + '@' + position]
    return lset.letters.get(letter)


# ---------------------------------------------------------------- previews (cached pictures)

def preview_png(path, size_px=160):
    """A small see-through picture of a stitch file, cached by file and date."""
    from PIL import Image
    from . import render, existing
    path = Path(path)
    st = path.stat()
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / ('%s_%d.png' % (_key(path, st.st_mtime, st.st_size), size_px))
    if out.exists():
        return out
    p = existing.clean_pattern(path)
    tmp = out.with_suffix('.tmp.png')
    xs = [s[0] for s in p.stitches if s[2] & 0xFF == 0]
    ys = [s[1] for s in p.stitches if s[2] & 0xFF == 0]
    longest = max(max(xs) - min(xs), max(ys) - min(ys)) / 10.0 or 1
    render.render(p, str(tmp), ppmm=max(1.0, size_px / longest), thread_mm=0.45, pad_mm=1, fabric=(255, 255, 255))
    im = Image.open(tmp).convert('RGBA')
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            if px[x, y][:3] == (255, 255, 255):
                px[x, y] = (255, 255, 255, 0)
    im.thumbnail((size_px, size_px))
    im.save(out)
    tmp.unlink(missing_ok=True)
    return out
