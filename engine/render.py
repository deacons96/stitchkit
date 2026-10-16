"""Draw a stitch file as thread on fabric, and report its statistics."""
import math
import sys
import pystitch
from pystitch import STITCH, JUMP, TRIM, COLOR_CHANGE, END, STOP
from PIL import Image, ImageDraw


def blocks(pattern):
    """Yield (rgb, [polyline of sewn points]) keeping jumps out of the picture."""
    ti = 0
    threads = pattern.threadlist
    cur = []
    out = []

    def colour():
        t = threads[min(ti, len(threads) - 1)] if threads else None
        return (t.get_red(), t.get_green(), t.get_blue()) if t else (0, 0, 0)

    for x, y, cmd in pattern.stitches:
        cmd &= 0xFF
        if cmd == STITCH:
            cur.append((x / 10.0, y / 10.0))
        else:
            if len(cur) > 1:
                out.append((colour(), cur))
            cur = []
            if cmd in (COLOR_CHANGE, STOP):
                ti += 1
    if len(cur) > 1:
        out.append((colour(), cur))
    return out


def stats(pattern):
    st = [s for s in pattern.stitches if s[2] & 0xFF == STITCH]
    xs = [s[0] for s in st]
    ys = [s[1] for s in st]
    longest = 0.0
    shortest_count = 0
    for colour, pts in blocks(pattern):
        for a, b in zip(pts, pts[1:]):
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            longest = max(longest, d)
            if d < 0.3:
                shortest_count += 1
    return dict(stitches=len(st),
                width_mm=(max(xs) - min(xs)) / 10.0, height_mm=(max(ys) - min(ys)) / 10.0,
                colour_changes=sum(1 for s in pattern.stitches if s[2] & 0xFF in (COLOR_CHANGE, STOP)),
                trims=sum(1 for s in pattern.stitches if s[2] & 0xFF == TRIM),
                jumps=sum(1 for s in pattern.stitches if s[2] & 0xFF == JUMP),
                longest_stitch_mm=round(longest, 2), tiny_stitches=shortest_count,
                threads=['#%02x%02x%02x' % (t.get_red(), t.get_green(), t.get_blue()) for t in pattern.threadlist])


def render(pattern, out_png, ppmm=24, fabric=(120, 150, 165), thread_mm=0.36, pad_mm=3, underlays=None):
    """underlays: [(shapely polygon in mm, '#rrggbb')] drawn under the thread, e.g. appliqué fabric."""
    bl = blocks(pattern)
    xs = [p[0] for _, pts in bl for p in pts]
    ys = [p[1] for _, pts in bl for p in pts]
    x0, y0 = min(xs) - pad_mm, min(ys) - pad_mm
    W = int((max(xs) - x0 + pad_mm) * ppmm)
    H = int((max(ys) - y0 + pad_mm) * ppmm)
    img = Image.new('RGB', (W, H), fabric)
    d = ImageDraw.Draw(img)
    tw = max(1, int(round(thread_mm * ppmm)))
    for poly, hx in (underlays or []):
        col = tuple(int(hx.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
        for part in getattr(poly, 'geoms', [poly]):
            if part.is_empty or part.geom_type != 'Polygon':
                continue
            ring = lambda c: [((x - x0) * ppmm, (y - y0) * ppmm) for x, y in c.coords]
            d.polygon(ring(part.exterior), fill=col)
            for hole in part.interiors:
                d.polygon(ring(hole), fill=fabric)
    for (r, g, b), pts in bl:
        dark = (int(r * .62), int(g * .62), int(b * .62))
        lite = (min(255, int(r * 1.0 + 38)), min(255, int(g * 1.0 + 38)), min(255, int(b * 1.0 + 38)))
        for a, c in zip(pts, pts[1:]):
            A = ((a[0] - x0) * ppmm, (a[1] - y0) * ppmm)
            C = ((c[0] - x0) * ppmm, (c[1] - y0) * ppmm)
            d.line([A, C], fill=dark, width=tw)
            d.line([A, C], fill=(r, g, b), width=max(1, tw - 2))
            if tw >= 5:
                d.line([A, C], fill=lite, width=max(1, tw // 4))
    img.save(out_png)
    return W, H


if __name__ == '__main__':
    p = pystitch.read(sys.argv[1])
    print(stats(p))
    if len(sys.argv) > 2:
        print(render(p, sys.argv[2], ppmm=float(sys.argv[3]) if len(sys.argv) > 3 else 24))
