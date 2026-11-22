#!/usr/bin/env python3
"""One page of world news for Sunday 22 November 2026, drawn by hand.

This program paints a newspaper front page into memory and writes it
out as a PNG. Everything is decided up front: the words, the colours,
the boxes and the type. There is no network access, no clock and no
randomness anywhere, so running it twice gives the same bytes twice.

How the picture is built, in order: a paper-coloured sheet with a
double border; a masthead with the date and a story count; a lead
story about the COP31 talks next to a small drawn globe; thirty-eight
further stories sorted into seven regions across two columns; a band
of four big numbers; and a footer naming the sources.

The letterforms come from atlas.bin, a file of pre-rendered glyph
bitmaps that sits next to this program. The program only ever reads
that file; it never writes anything except the finished entry.png.
"""

import math
import os
import struct
import zlib

SHEET_W = 1024
SHEET_H = 1024

PAPER = (248, 243, 231)
INK = (24, 23, 20)
CRIMSON = (176, 36, 28)
OCEAN = (28, 76, 138)
PINE = (14, 110, 105)
PALE = (170, 160, 142)
SNOW = (255, 255, 255)

HEAVY = 1
PLAIN = 0


# ------------------------------------------------------------ atlas file
class Glyph:
    """One pre-rendered letter: its offset, size, advance and bitmap."""

    __slots__ = ("dx", "dy", "w", "h", "adv", "bits")

    def __init__(self, dx, dy, w, h, adv, bits):
        self.dx = dx
        self.dy = dy
        self.w = w
        self.h = h
        self.adv = adv
        self.bits = bits


class Face:
    """One weight-and-size of the typeface, with all its glyphs."""

    __slots__ = ("asc", "desc", "glyphs")

    def __init__(self, asc, desc):
        self.asc = asc
        self.desc = desc
        self.glyphs = {}


class Cursor:
    """A reading head that walks a byte string, big-endian."""

    def __init__(self, blob, pos=0):
        self.blob = blob
        self.pos = pos

    def take(self, n):
        chunk = self.blob[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self):
        (value,) = struct.unpack_from(">B", self.blob, self.pos)
        self.pos += 1
        return value

    def u16(self):
        (value,) = struct.unpack_from(">H", self.blob, self.pos)
        self.pos += 2
        return value

    def i16(self):
        (value,) = struct.unpack_from(">h", self.blob, self.pos)
        self.pos += 2
        return value

    def u32(self):
        (value,) = struct.unpack_from(">I", self.blob, self.pos)
        self.pos += 4
        return value


def load_atlas(path):
    """Decode atlas.bin into {(heavy, size): Face}."""
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:7] != b"ATLAS1\n":
        raise ValueError("atlas.bin has the wrong magic")
    cur = Cursor(blob, 7)
    faces = {}
    for _ in range(cur.u32()):
        heavy = cur.u16()
        size = cur.u8()
        asc = cur.u16()
        desc = cur.u16()
        face = Face(asc, desc)
        for _ in range(cur.u16()):
            code = cur.u32()
            dx = cur.i16()
            dy = cur.i16()
            gw = cur.u16()
            gh = cur.u16()
            adv = cur.u16()
            nbytes = cur.u32()
            face.glyphs[code] = Glyph(dx, dy, gw, gh, adv, cur.take(nbytes))
        faces[(heavy, size)] = face
    return faces


# -------------------------------------------------------------- the sheet
class Canvas:
    """An RGB picture held in memory, with a few drawing tools."""

    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.buf = bytearray(bytes(bg) * w * h)

    def dot(self, x, y, rgb):
        if 0 <= x < self.w and 0 <= y < self.h:
            at = (y * self.w + x) * 3
            self.buf[at:at + 3] = bytes(rgb)

    def fill(self, x, y, w, h, rgb):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        run = bytes(rgb) * (x1 - x0)
        for yy in range(y0, y1):
            at = (yy * self.w + x0) * 3
            self.buf[at:at + len(run)] = run

    def rule(self, x, y, length, rgb, thick=1):
        self.fill(x, y, length, thick, rgb)

    def frame(self, x, y, w, h, rgb, thick=1):
        self.fill(x, y, w, thick, rgb)
        self.fill(x, y + h - thick, w, thick, rgb)
        self.fill(x, y, thick, h, rgb)
        self.fill(x + w - thick, y, thick, h, rgb)

    def stroke(self, x0, y0, x1, y1, rgb):
        """A straight line, Bresenham's way."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.dot(x0, y0, rgb)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def filled_circle(self, cx, cy, r, rgb):
        for yy in range(cy - r, cy + r + 1):
            dy = yy - cy
            half = int(math.sqrt(max(0, r * r - dy * dy)))
            self.fill(cx - half, yy, half * 2 + 1, 1, rgb)

    def circle(self, cx, cy, r, rgb, thick=1):
        for layer in range(thick):
            rr = r - layer
            steps = max(64, int(2 * math.pi * rr))
            for i in range(steps):
                a = 2 * math.pi * i / steps
                self.dot(cx + int(rr * math.cos(a)),
                         cy + int(rr * math.sin(a)), rgb)

    def oval(self, cx, cy, a, b, rgb):
        steps = max(64, int(2 * math.pi * max(a, b)))
        for i in range(steps):
            ang = 2 * math.pi * i / steps
            self.dot(cx + int(a * math.cos(ang)),
                     cy + int(b * math.sin(ang)), rgb)

    def chord(self, cx, cy, r, dy, rgb):
        """One horizontal slice of a circle, dy below its centre."""
        half = int(math.sqrt(max(0, r * r - dy * dy)))
        self.fill(cx - half, cy + dy, half * 2 + 1, 1, rgb)


# -------------------------------------------------------------- setting type
def glyph_for(face, ch):
    found = face.glyphs.get(ord(ch))
    if found is None:
        found = face.glyphs.get(ord("?"))
    return found


def text_width(faces, key, s, tracking=0):
    face = faces[key]
    total = 0
    for ch in s:
        total += glyph_for(face, ch).adv + tracking
    return total - tracking if s else 0


def face_height(faces, key):
    face = faces[key]
    return face.asc + face.desc


def draw_text(canvas, faces, key, x, y, s, rgb, tracking=0):
    """Paint a string; hands back the pen position after the last glyph."""
    face = faces[key]
    pen = x
    for ch in s:
        g = glyph_for(face, ch)
        if g.w and g.h:
            stride = (g.w + 7) // 8
            for gy in range(g.h):
                yy = y + g.dy + gy
                if yy < 0 or yy >= canvas.h:
                    continue
                for bx in range(stride):
                    byte = g.bits[gy * stride + bx]
                    if not byte:
                        continue
                    for bit in range(8):
                        if byte & (0x80 >> bit):
                            xx = pen + g.dx + bx * 8 + bit
                            if 0 <= xx < canvas.w:
                                at = (yy * canvas.w + xx) * 3
                                canvas.buf[at:at + 3] = bytes(rgb)
        pen += g.adv + tracking
    return pen


def draw_text_centred(canvas, faces, key, cx, y, s, rgb, tracking=0):
    w = text_width(faces, key, s, tracking)
    draw_text(canvas, faces, key, cx - w // 2, y, s, rgb, tracking)


def wrap_text(faces, key, s, max_w, tracking=0):
    """Greedy word wrap: pack as many words per line as fit."""
    lines = []
    for chunk in s.split("\n"):
        words = chunk.split(" ")
        i = 0
        cur = ""
        while i < len(words):
            word = words[i]
            cand = word if cur == "" else cur + " " + word
            if cur == "" or text_width(faces, key, cand, tracking) <= max_w:
                cur = cand
                i += 1
            else:
                lines.append(cur)
                cur = ""
        lines.append(cur)
    return lines


def draw_paragraph(canvas, faces, key, x, y, s, max_w, rgb, gap=3,
                   tracking=0):
    step = face_height(faces, key) + gap
    cy = y
    for line in wrap_text(faces, key, s, max_w, tracking):
        draw_text(canvas, faces, key, x, cy, line, rgb, tracking)
        cy += step
    return cy


# ------------------------------------------------------------------ the png
def png_bytes(canvas):
    raw = bytearray()
    stride = canvas.w * 3
    for yy in range(canvas.h):
        raw.append(0)
        raw += canvas.buf[yy * stride:(yy + 1) * stride]
    body = zlib.compress(bytes(raw), 9)
    out = [b"\x89PNG\r\n\x1a\n"]
    chunks = (
        (b"IHDR", struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 2, 0, 0, 0)),
        (b"IDAT", body),
        (b"IEND", b""),
    )
    for kind, data in chunks:
        out.append(struct.pack(">I", len(data)))
        out.append(kind)
        out.append(data)
        out.append(struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return b"".join(out)


# -------------------------------------------------------------- the content
MASTHEAD = "THE WORLD IN ONE PAGE"
DATE_LINE = "SUNDAY, 22 NOVEMBER 2026"
TAG_LINE = "39 STORIES  \u00b7  7 REGIONS  \u00b7  ONE DAY"

LEAD = {
    "kicker": "ANTALYA \u2014 COP31 NEARS A DEAL",
    "headline": ["COP31 nears a final deal", "as new package lands"],
    "body": ("Presidents table a text they say all can accept; "
             "objections by 0300 GMT, a vote at 0600 GMT."),
}

# Two columns of region sections; each section has a coloured heading
# and a list of one-line stories with a bold dateline up front.
COLUMNS = [
    [
        {"head": "MIDDLE EAST", "tint": CRIMSON, "items": [
            {"place": "BAHRAIN", "line": "Iran hits 4 US bases; 2 Patriot radars claimed."},
            {"place": "HORMUZ", "line": "3 tankers attacked; 2 hit, 1 mined, no deaths."},
            {"place": "WASHINGTON", "line": "Trump seeks permanent Iran deal."},
            {"place": "KHARG", "line": "14 Iranian tankers mass to break US blockade."},
            {"place": "JERUSALEM", "line": "Eisenkot invites Likud to coalition talks."},
        ]},
        {"head": "EUROPE", "tint": OCEAN, "items": [
            {"place": "HELSINKI", "line": "Finland: war \u2018spilling over\u2019 to Baltic."},
            {"place": "TALLINN", "line": "Estonia to shut its border with Russia."},
            {"place": "BRUSSELS", "line": "EU-Indonesia sign trade pact; tariffs gone."},
            {"place": "BERLIN", "line": "Coalition rallies to push Moscow to talks."},
            {"place": "WARSAW", "line": "Poland fires up Patriots after airspace breach."},
            {"place": "PARIS", "line": "France probes Depardieu over gang-rape claim."},
        ]},
        {"head": "UKRAINE WAR", "tint": PINE, "items": [
            {"place": "LVIV", "line": "Russian strike kills 2, wounds 10 in the west."},
            {"place": "LONDON", "line": "UK, Ukraine to build strike drones together."},
            {"place": "KYIV", "line": "Zelensky: Russia hit bridges 109 times before."},
            {"place": "SOFIA", "line": "Bulgaria backs India Black Sea ceasefire plan."},
        ]},
        {"head": "AMERICAS", "tint": CRIMSON, "items": [
            {"place": "SINALOA", "line": "11 killed as cartel violence erupts."},
            {"place": "BRASILIA", "line": "Bolsonaro in ICU with bowel obstruction."},
            {"place": "WASHINGTON", "line": "FBI probes hack of its crime database."},
            {"place": "PENTAGON", "line": "Memo limits socials with Canadian military."},
        ]},
    ],
    [
        {"head": "ASIA-PACIFIC", "tint": OCEAN, "items": [
            {"place": "PATNA", "line": "Modi opens Nitish Setu bridge in Bihar."},
            {"place": "RANCHI", "line": "Cyclone Akvan cancels 14 flights."},
            {"place": "TOKYO", "line": "Japan to train live-fire in India, a first."},
            {"place": "HONG KONG", "line": "Election Committee voting opens."},
            {"place": "WELLINGTON", "line": "India 629-6, a record total in New Zealand."},
            {"place": "ISLAMABAD", "line": "Suicide bombing kills 5, wounds 13."},
        ]},
        {"head": "MARKETS & TECH", "tint": PINE, "items": [
            {"place": "SHANGHAI", "line": "Leapmotor Q3 profit plunges 73%."},
            {"place": "BEIJING", "line": "Foreign cash into China tech up 31%."},
            {"place": "SHENZHEN", "line": "BYD, Huawei unveil new SUVs."},
            {"place": "LAS VEGAS", "line": "Verstappen on pole; Antonelli penalised."},
            {"place": "WASHINGTON", "line": "Signal blocks screenshots over AI spying."},
            {"place": "LONDON", "line": "Crude oil futures fall more than 3%."},
        ]},
        {"head": "SCIENCE & WORLD", "tint": CRIMSON, "items": [
            {"place": "TIMOR SEA", "line": "M6.8 quake strikes off Timor-Leste."},
            {"place": "GENEVA", "line": "UN fails to agree rules on \u2018killer robots\u2019."},
            {"place": "JOHANNESBURG", "line": "Mlambo-Ngcuka dies at 71."},
            {"place": "CAPE TOWN", "line": "Murders fall, yet 60 a day are killed."},
            {"place": "DAKAR", "line": "Senegal president imposes budget by decree."},
            {"place": "CAIRO", "line": "Egypt nears $2.3bn IMF payout."},
            {"place": "EUROPA", "line": "Sodium cloud traced around Jupiter\u2019s moon."},
        ]},
    ],
]

FIGURES = [
    {"big": "98.5%", "note": "tariffs scrapped\nin EU-Indonesia deal"},
    {"big": "629-6", "note": "India\u2019s record\ntotal in New Zealand"},
    {"big": "M6.8", "note": "quake off\nTimor-Leste"},
    {"big": "11", "note": "killed in Sinaloa\ncartel violence"},
]

CREDIT_A = ("Sources: Reuters \u00b7 AP \u00b7 AFP \u00b7 BBC \u00b7 CNN \u00b7 USGS \u00b7 NYT \u00b7 DW"
            "  \u2014  Events of Sunday 22 November 2026")
CREDIT_B = ("39 stories \u00b7 7 regions \u2014 Drawn by a program. No network, "
            "no AI images; every word set in type.")


# -------------------------------------------------------------- the layout
def paint_story(canvas, faces, x, y, col_w, place, line):
    """One story on a single line: bold dateline, plain rest."""
    head = place + " \u2014 "
    after = draw_text(canvas, faces, (HEAVY, 15), x, y, head, INK)
    draw_text(canvas, faces, (PLAIN, 15), after, y, line, INK)
    total = (text_width(faces, (HEAVY, 15), head)
             + text_width(faces, (PLAIN, 15), line))
    if total > col_w:
        raise ValueError("story too wide: %s %s (%d > %d)"
                         % (place, line, total, col_w))
    return y + 18


def paint_section(canvas, faces, x, col_w, y, sections):
    for sec in sections:
        head_w = text_width(faces, (HEAVY, 19), sec["head"], tracking=1)
        draw_text(canvas, faces, (HEAVY, 19), x, y, sec["head"],
                  sec["tint"], tracking=1)
        canvas.rule(x, y + 25, head_w, sec["tint"], 3)
        y += 33
        for item in sec["items"]:
            y = paint_story(canvas, faces, x, y, col_w,
                            item["place"], item["line"])
        y += 6
    return y


def paint_globe(canvas, cx, cy, r):
    canvas.filled_circle(cx, cy, r, OCEAN)
    canvas.circle(cx, cy, r, INK, 2)
    canvas.circle(cx, cy, r + 7, INK, 1)
    canvas.oval(cx, cy, 24, r - 4, SNOW)
    canvas.oval(cx, cy, r - 4, 24, SNOW)
    canvas.chord(cx, cy, r - 2, -28, SNOW)
    canvas.chord(cx, cy, r - 2, 28, SNOW)
    canvas.filled_circle(cx + 40, cy - 42, 5, CRIMSON)


def build_page(faces):
    sheet = Canvas(SHEET_W, SHEET_H, PAPER)
    sheet.frame(14, 14, SHEET_W - 28, SHEET_H - 28, INK, 2)
    sheet.frame(20, 20, SHEET_W - 40, SHEET_H - 40, INK, 1)

    draw_text_centred(sheet, faces, (HEAVY, 64), SHEET_W // 2, 32,
                      MASTHEAD, INK)
    draw_text_centred(sheet, faces, (HEAVY, 22), SHEET_W // 2, 112,
                      DATE_LINE, CRIMSON)
    draw_text_centred(sheet, faces, (PLAIN, 18), SHEET_W // 2, 142,
                      TAG_LINE, INK, tracking=4)
    sheet.rule(36, 172, SHEET_W - 72, INK, 5)
    sheet.rule(36, 181, SHEET_W - 72, INK, 1)

    # Lead story on the left, the drawn globe on the right.
    draw_text(sheet, faces, (HEAVY, 19), 36, 192, LEAD["kicker"],
              CRIMSON, tracking=1)
    y = 216
    for headline in LEAD["headline"]:
        draw_text(sheet, faces, (HEAVY, 30), 36, y, headline, INK)
        y += face_height(faces, (HEAVY, 30)) + 2
    y += 6
    y = draw_paragraph(sheet, faces, (PLAIN, 20), 36, y, LEAD["body"],
                       664, INK, gap=3)
    paint_globe(sheet, 852, 272, 64)
    sheet.rule(36, 356, SHEET_W - 72, INK, 1)

    # Region grid, two columns with a faint divider between them.
    left_end = paint_section(sheet, faces, 36, 469, 366, COLUMNS[0])
    right_end = paint_section(sheet, faces, 519, 469, 366, COLUMNS[1])
    grid_end = left_end if left_end > right_end else right_end
    sheet.fill(512, 368, 1, grid_end - 374, PALE)

    # Numbers band.
    band_y = grid_end + 10
    band_h = 72
    sheet.frame(36, band_y, SHEET_W - 72, band_h, INK, 1)
    cell = (SHEET_W - 72) // 4
    for idx, fig in enumerate(FIGURES):
        cx = 36 + cell * idx
        if idx:
            sheet.fill(cx, band_y + 8, 1, band_h - 16, PALE)
        draw_text_centred(sheet, faces, (HEAVY, 30), cx + cell // 2,
                          band_y + 4, fig["big"], CRIMSON)
        for j, sub in enumerate(fig["note"].split("\n")):
            draw_text_centred(sheet, faces, (PLAIN, 15), cx + cell // 2,
                              band_y + 38 + j * 17, sub, INK)

    sheet.rule(36, 956, SHEET_W - 72, INK, 1)
    draw_text_centred(sheet, faces, (PLAIN, 14), SHEET_W // 2, 964,
                      CREDIT_A, INK)
    draw_text_centred(sheet, faces, (PLAIN, 14), SHEET_W // 2, 982,
                      CREDIT_B, INK)
    return sheet


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    faces = load_atlas(os.path.join(base, "atlas.bin"))
    data = png_bytes(build_page(faces))
    dest = (os.environ.get("MAKEFUN_OUTPUT_DIR")
            or ("/output" if os.path.isdir("/output") else "out"))
    os.makedirs(dest, exist_ok=True)
    target = os.path.join(dest, "entry.png")
    with open(target, "wb") as handle:
        handle.write(data)
    print("wrote %s (%d bytes)" % (target, len(data)))


if __name__ == "__main__":
    main()
