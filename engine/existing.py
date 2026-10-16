"""Reading existing stitch files (VP3, PES, DST, JEF, EXP, HUS, VIP ...) and joining stitch blocks.

The original stitches are always kept exactly as they are (see produce.py for patches and frames).
"""
import pystitch
from pystitch import STITCH, JUMP, TRIM, COLOR_CHANGE, END
from shapely.geometry import LineString
from shapely.ops import unary_union

from . import vip
from .art import clean
from .build import ascii_name

STITCH_EXTS = ('.vp3', '.pes', '.pec', '.dst', '.jef', '.exp', '.hus', '.vip', '.xxx', '.sew', '.u01', '.tbf',
               '.dsb', '.dsz', '.vp3', '.shv', '.10o', '.100', '.ksm', '.emd', '.phb', '.phc', '.new', '.stx', '.zhs')
ANCHOR = '#010203'
SPLIT = '#030201'


def is_stitch_file(path):
    return str(path).lower().endswith(STITCH_EXTS)


def read_stitch_file(path):
    path = str(path)
    if path.lower().endswith('.vip'):
        cols, recs, _ = vip.read(path)
        p = pystitch.EmbPattern()
        for c in cols:
            p.add_thread(pystitch.EmbThread('#%02x%02x%02x' % c))
        for cmd, x, y in recs:
            if cmd == 0x80:
                p.add_stitch_absolute(STITCH, x, y)
            elif cmd == 0x81:
                p.add_stitch_absolute(JUMP, x, y)
            elif cmd == 0x84:
                p.add_stitch_absolute(COLOR_CHANGE, x, y)
        p.add_command(END)
        return p
    p = pystitch.read(path)
    if p is None or not any(s[2] & 0xFF == STITCH for s in p.stitches):
        raise ValueError('Could not read any stitches from that file.')
    return p


def blocks(p):
    """[(thread, [[x, y, cmd], ...])] with colour-change/end commands stripped."""
    out = []
    for stitches, thread in p.get_as_colorblocks():
        st = [list(s) for s in stitches if s[2] & 0xFF in (STITCH, JUMP, TRIM)]
        if any(s[2] & 0xFF == STITCH for s in st):
            out.append((thread, st))
    return out


def coverage(p):
    """The area the design's stitches cover, in mm."""
    lines = []
    for _, st in blocks(p):
        run = []
        for x, y, c in st:
            if c & 0xFF == STITCH:
                run.append((x / 10.0, y / 10.0))
            else:
                if len(run) > 1:
                    lines.append(LineString(run))
                run = []
        if len(run) > 1:
            lines.append(LineString(run))
    # chunked unions keep this quick on big designs
    parts = []
    for i in range(0, len(lines), 400):
        parts.append(unary_union([l.buffer(0.3, quad_segs=2) for l in lines[i:i + 400]]))
    g = clean(unary_union(parts))
    return clean(g.buffer(0.6, join_style=1).buffer(-0.6, join_style=1))


def thread_hex(t):
    return '#%02x%02x%02x' % (t.get_red(), t.get_green(), t.get_blue())


def assemble(sequence, names=None):
    """Blocks [(thread, stitches)] -> one pattern; neighbouring blocks of the same thread are joined
    (with a trim) so the machine doesn't stop for nothing."""
    names = names or {}
    merged = []
    for t, st in sequence:
        if merged and thread_hex(merged[-1][0]) == thread_hex(t):
            last = merged[-1][1][-1]
            merged[-1][1].extend([[last[0], last[1], TRIM]] + st)
        else:
            merged.append((t, list(st)))
    out = pystitch.EmbPattern()
    for k, (t, st) in enumerate(merged):
        th = pystitch.EmbThread(thread_hex(t))
        th.description = ascii_name(names.get(thread_hex(t), getattr(t, 'description', None) or thread_hex(t)))
        out.add_thread(th)
        if k:
            out.add_stitch_absolute(TRIM, st[0][0], st[0][1])
            out.add_stitch_absolute(COLOR_CHANGE, st[0][0], st[0][1])
        prev = None
        for x, y, c in st:
            if prev is not None and c & 0xFF == STITCH and prev[2] & 0xFF == STITCH and \
                    ((x - prev[0]) ** 2 + (y - prev[1]) ** 2) > 121 ** 2:
                out.add_stitch_absolute(TRIM, prev[0], prev[1])
                out.add_stitch_absolute(JUMP, x, y)
            out.add_stitch_absolute(c & 0xFF, x, y)
            prev = (x, y, c)
    out.add_command(END)
    return out
