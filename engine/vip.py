"""Write (and read back) Husqvarna Viking / Pfaff .VIP files.

Layout follows libembroidery's format-vip reader. The three data streams (commands, x deltas,
y deltas) use the HUS/VIP LZH container; we store them as literal-only blocks, which is a valid
stream and is what pyembroidery/libembroidery do for HUS.
"""
import struct
from pystitch import STITCH, JUMP, TRIM, COLOR_CHANGE, STOP, END
from pystitch.EmbCompress import expand

MAGIC = 0x0190FC5D
TABLE = bytes([
    0x2E, 0x82, 0xE4, 0x6F, 0x38, 0xA9, 0xDC, 0xC6, 0x7B, 0xB6, 0x28, 0xAC, 0xFD, 0xAA, 0x8A, 0x4E,
    0x76, 0x2E, 0xF0, 0xE4, 0x25, 0x1B, 0x8A, 0x68, 0x4E, 0x92, 0xB9, 0xB4, 0x95, 0xF0, 0x3E, 0xEF,
    0xF7, 0x40, 0x24, 0x18, 0x39, 0x31, 0xBB, 0xE1, 0x53, 0xA8, 0x1F, 0xB1, 0x3A, 0x07, 0xFB, 0xCB,
    0xE6, 0x00, 0x81, 0x50, 0x0E, 0x40, 0xE1, 0x2C, 0x73, 0x50, 0x0D, 0x91, 0xD6, 0x0A, 0x5D, 0xD6,
    0x8B, 0xB8, 0x62, 0xAE, 0x47, 0x00, 0x53, 0x5A, 0xB7, 0x80, 0xAA, 0x28, 0xF7, 0x5D, 0x70, 0x5E,
    0x2C, 0x0B, 0x98, 0xE3, 0xA0, 0x98, 0x60, 0x47, 0x89, 0x9B, 0x82, 0xFB, 0x40, 0xC9, 0xB4, 0x00,
    0x0E, 0x68, 0x6A, 0x1E, 0x09, 0x85, 0xC0, 0x53, 0x81, 0xD1, 0x98, 0x89, 0xAF, 0xE8, 0x85, 0x4F,
    0x40, 0x26, 0xA0, 0x88, 0xD1, 0x62, 0x6A, 0xB3, 0x50, 0x12, 0xB9, 0x9B, 0xB5, 0x83, 0x9B, 0x37])
BLOCK = 60000


def compress(data):
    out = bytearray()
    for i in range(0, len(data), BLOCK):
        chunk = data[i:i + BLOCK]
        n = len(chunk)
        out += bytes([(n >> 8) & 0xFF, n & 0xFF, 0x02, 0xA0, 0x01, 0xFE])   # block size is big-endian
        out += chunk
    return bytes(out)


def records(pattern):
    """Flatten a pattern into (cmd, dx, dy) with every delta within one signed byte."""
    recs = []
    px = py = 0
    xs = [s[0] for s in pattern.stitches if s[2] & 0xFF == STITCH]
    ys = [s[1] for s in pattern.stitches if s[2] & 0xFF == STITCH]
    cx = int(round((max(xs) + min(xs)) / 2.0))
    cy = int(round((max(ys) + min(ys)) / 2.0))
    pending_colour = False
    for x, y, cmd in pattern.stitches:
        cmd &= 0xFF
        x = int(round(x)) - cx
        y = int(round(y)) - cy
        if cmd == END:
            break
        if cmd in (COLOR_CHANGE, STOP):
            pending_colour = True
            continue
        if cmd == TRIM:
            continue                      # the move that follows is written as a jump
        dx, dy = x - px, y - py
        steps = max(1, -(-max(abs(dx), abs(dy)) // 120))
        code = 0x80 if cmd == STITCH else 0x81
        if pending_colour:
            recs.append((0x84, 0, 0))
            pending_colour = False
        bx, by = px, py
        for i in range(1, steps + 1):
            tx = x if i == steps else bx + int(round(dx * i / steps))
            ty = y if i == steps else by + int(round(dy * i / steps))
            recs.append((code if i == steps else 0x81, tx - px, ty - py))
            px, py = tx, ty
    recs.append((0x90, 0, 0))
    return recs, cx, cy


def write(pattern, filename):
    recs, cx, cy = records(pattern)
    colours = [(t.get_red(), t.get_green(), t.get_blue()) for t in pattern.threadlist]
    n_changes = sum(1 for r in recs if r[0] == 0x84)
    colours = colours[:n_changes + 1]
    n = len(colours)
    attr = bytes(r[0] for r in recs)
    xd = bytes(r[1] & 0xFF for r in recs)
    yd = bytes((-r[2]) & 0xFF for r in recs)     # file Y points up
    ca, cxs, cys = compress(attr), compress(xd), compress(yd)

    ax = ay = 0
    minx = maxx = miny = maxy = 0
    for c, dx, dy in recs:
        ax += dx
        ay += dy
        if c == 0x80:
            minx, maxx, miny, maxy = min(minx, ax), max(maxx, ax), min(miny, ay), max(maxy, ay)

    attr_off = 0x38 + 8 * n
    out = bytearray()
    out += struct.pack('<III', MAGIC, len(recs), n)
    out += struct.pack('<hhhh', maxx, -miny, minx, -maxy)
    out += struct.pack('<III', attr_off, attr_off + len(ca), attr_off + len(ca) + len(cxs))
    out += b'\x00' * 8
    out += struct.pack('<H', 0)
    out += struct.pack('<i', n * 4)
    prev = 0
    k = 0
    for r, g, b in colours:
        for v in (r, g, b, 0x01):
            prev = (v ^ TABLE[k]) ^ prev
            out.append(prev)
            k += 1
    for _ in range(n + 1):
        out += struct.pack('<i', 1)
    out += struct.pack('<I', 0)
    out += struct.pack('<h', 0)
    assert len(out) == attr_off, (len(out), attr_off)
    out += ca + cxs + cys
    with open(filename, 'wb') as f:
        f.write(out)
    return len(recs)


def read(filename):
    """Independent read-back: returns (colours, [(cmd, x, y) absolute, 0.1 mm, Y down])."""
    with open(filename, 'rb') as fh:
        d = fh.read()
    magic, count, n = struct.unpack_from('<III', d, 0)
    assert magic == MAGIC
    ext = struct.unpack_from('<hhhh', d, 12)
    a_off, x_off, y_off = struct.unpack_from('<III', d, 20)
    clen = struct.unpack_from('<i', d, 42)[0]
    assert clen == 4 * n
    colours = []
    prev = 0
    dec = []
    for i in range(4 * n):
        b = d[46 + i]
        dec.append((b ^ TABLE[i]) ^ prev)
        prev = b
    for i in range(n):
        colours.append(tuple(dec[4 * i:4 * i + 3]))
    a = expand(bytearray(d[a_off:x_off]), count)[:count]
    xs = expand(bytearray(d[x_off:y_off]), count)[:count]
    ys = expand(bytearray(d[y_off:]), count)[:count]
    assert len(a) == len(xs) == len(ys) == count, (len(a), len(xs), len(ys), count)
    out = []
    x = y = 0
    for c, dx, dy in zip(a, xs, ys):
        dx = dx - 256 if dx > 127 else dx
        dy = dy - 256 if dy > 127 else dy
        x += dx
        y -= dy
        out.append((c, x, y))
    return colours, out, ext
