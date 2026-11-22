#!/usr/bin/env python3
"""The World in One Page — Sunday 22 November 2026.

A one-page newspaper drawn entirely by this program: standard library
only, no network, no clock, no randomness, so two runs write identical
bytes. It reads a pre-rendered glyph atlas (atlas.bin) sitting next to
it, paints the page into an RGB buffer and encodes that buffer as PNG.

The page: a masthead with the date, a lead story (COP31 nearing a deal)
beside a drawn globe, then 38 more stories grouped into 7 regions over
two columns, and a band of numbers at the foot. 39 stories in all,
every one real and reported on 22 November 2026 (see SOURCES.md in the
work directory for the source of each story).
"""

import math
import os
import struct
import sys
import zlib

PAGE_W = 1024
PAGE_H = 1024

PAPER = (248, 243, 231)
INK = (24, 23, 20)
RED = (176, 36, 28)
BLUE = (28, 76, 138)
TEAL = (14, 110, 105)
FAINT = (170, 160, 142)
WHITE = (255, 255, 255)

BOLD = 1
REG = 0


# ------------------------------------------------------------------ faces
def read_font_faces(path):
    """Read atlas.bin into {(bold, size): (ascent, descent, glyphs)}."""
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:7] != b"ATLAS1\n":
        raise ValueError("atlas.bin has the wrong magic")
    pos = 7
    (nfaces,) = struct.unpack_from(">I", blob, pos)
    pos += 4
    faces = {}
    for _ in range(nfaces):
        is_bold, size, asc, desc = struct.unpack_from(">HBHH", blob, pos)
        pos += 7
        (count,) = struct.unpack_from(">H", blob, pos)
        pos += 2
        table = {}
        for _ in range(count):
            code, xoff, yoff, gw, gh, adv = struct.unpack_from(
                ">IhhHHH", blob, pos)
            pos += 14
            (nbytes,) = struct.unpack_from(">I", blob, pos)
            pos += 4
            table[code] = (xoff, yoff, gw, gh, adv, blob[pos:pos + nbytes])
            pos += nbytes
        faces[(is_bold, size)] = (asc, desc, table)
    return faces


# ------------------------------------------------------------------- page
class Page:
    """An RGB pixel buffer with rectangle, line and circle primitives."""

    def __init__(self, width, height, background):
        self.width = width
        self.height = height
        self.pixels = bytearray(bytes(background) * width * height)

    def put(self, x, y, colour):
        if 0 <= x < self.width and 0 <= y < self.height:
            at = (y * self.width + x) * 3
            self.pixels[at:at + 3] = bytes(colour)

    def rect(self, x, y, w, h, colour):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + w)
        y1 = min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(colour) * (x1 - x0)
        for yy in range(y0, y1):
            at = (yy * self.width + x0) * 3
            self.pixels[at:at + len(row)] = row

    def hline(self, x, y, w, colour, thick=1):
        self.rect(x, y, w, thick, colour)

    def outline(self, x, y, w, h, colour, thick=1):
        self.rect(x, y, w, thick, colour)
        self.rect(x, y + h - thick, w, thick, colour)
        self.rect(x, y, thick, h, colour)
        self.rect(x + w - thick, y, thick, h, colour)

    def segment(self, x0, y0, x1, y1, colour):
        """Bresenham line."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.put(x0, y0, colour)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def disc(self, cx, cy, r, colour):
        for yy in range(cy - r, cy + r + 1):
            dy = yy - cy
            half = int(math.sqrt(max(0, r * r - dy * dy)))
            self.rect(cx - half, yy, half * 2 + 1, 1, colour)

    def ring(self, cx, cy, r, colour, thick=1):
        for t in range(thick):
            rr = r - t
            steps = max(64, int(2 * math.pi * rr))
            for i in range(steps):
                a = 2 * math.pi * i / steps
                self.put(cx + int(rr * math.cos(a)),
                         cy + int(rr * math.sin(a)), colour)

    def ellipse(self, cx, cy, a, b, colour):
        steps = max(64, int(2 * math.pi * max(a, b)))
        for i in range(steps):
            ang = 2 * math.pi * i / steps
            self.put(cx + int(a * math.cos(ang)),
                     cy + int(b * math.sin(ang)), colour)

    def chord(self, cx, cy, r, dy, colour):
        """Horizontal chord of a circle, dy below centre."""
        half = int(math.sqrt(max(0, r * r - dy * dy)))
        self.rect(cx - half, cy + dy, half * 2 + 1, 1, colour)


# ------------------------------------------------------------------- type
def lookup(faces, face, char):
    _, _, table = faces[face]
    found = table.get(ord(char))
    if found is None:
        found = table.get(ord("?"))
    return found


def measure(faces, face, text, tracking=0):
    total = 0
    for char in text:
        total += lookup(faces, face, char)[4] + tracking
    return total - tracking if text else 0


def pitch(faces, face):
    ascent, descent, _ = faces[face]
    return ascent + descent


def typeset(page, faces, face, x, y_top, text, colour, tracking=0):
    """Paint text; returns the pen x after the last glyph."""
    ascent, _, _ = faces[face]
    baseline = y_top + ascent
    pen = x
    for char in text:
        xoff, yoff, gw, gh, adv, bits = lookup(faces, face, char)
        if gw and gh:
            row_bytes = (gw + 7) // 8
            for gy in range(gh):
                yy = baseline - ascent + yoff + gy
                if yy < 0 or yy >= page.height:
                    continue
                for bx in range(row_bytes):
                    byte = bits[gy * row_bytes + bx]
                    if not byte:
                        continue
                    for bit in range(8):
                        if byte & (0x80 >> bit):
                            xx = pen + xoff + bx * 8 + bit
                            if 0 <= xx < page.width:
                                at = (yy * page.width + xx) * 3
                                page.pixels[at:at + 3] = bytes(colour)
        pen += adv + tracking
    return pen


def typeset_centred(page, faces, face, cx, y_top, text, colour, tracking=0):
    width = measure(faces, face, text, tracking)
    typeset(page, faces, face, cx - width // 2, y_top, text, colour, tracking)


def wrap(faces, face, text, max_width, tracking=0):
    lines = []
    for chunk in text.split("\n"):
        words = chunk.split(" ")
        current = ""
        for word in words:
            trial = word if not current else current + " " + word
            if not current or measure(faces, face, trial, tracking) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def typeset_para(page, faces, face, x, y_top, text, max_width,
                 colour, gap=3, tracking=0):
    step = pitch(faces, face) + gap
    y = y_top
    for line in wrap(faces, face, text, max_width, tracking):
        typeset(page, faces, face, x, y, line, colour, tracking)
        y += step
    return y


# -------------------------------------------------------------------- png
def encode_png(page):
    raw = bytearray()
    stride = page.width * 3
    for yy in range(page.height):
        raw.append(0)
        raw += page.pixels[yy * stride:(yy + 1) * stride]
    payload = zlib.compress(bytes(raw), 9)

    def chunk(kind, data):
        out = struct.pack(">I", len(data)) + kind + data
        return out + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", page.width, page.height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", payload) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- content
MASTHEAD = "THE WORLD IN ONE PAGE"
DATE_LINE = "SUNDAY, 22 NOVEMBER 2026"
TAG_LINE = "39 STORIES  \u00b7  7 REGIONS  \u00b7  ONE DAY"

LEAD_KICKER = "ANTALYA \u2014 COP31 NEARS A DEAL"
LEAD_LINES = ["COP31 nears a final deal", "as new package lands"]
LEAD_TEXT = (
    "Presidents table a text they say all can accept; objections by "
    "0300 GMT, a vote at 0600 GMT."
)

# (region kicker, colour, [(dateline, one-line story), ...])
REGIONS_LEFT = [
    ("MIDDLE EAST", RED, [
        ("BAHRAIN", "Iran hits 4 US bases; 2 Patriot radars claimed."),
        ("HORMUZ", "3 tankers attacked; 2 hit, 1 mined, no deaths."),
        ("WASHINGTON", "Trump seeks permanent Iran deal."),
        ("KHARG", "14 Iranian tankers mass to break US blockade."),
        ("JERUSALEM", "Eisenkot invites Likud to coalition talks."),
    ]),
    ("EUROPE", BLUE, [
        ("HELSINKI", "Finland: war \u2018spilling over\u2019 to Baltic."),
        ("TALLINN", "Estonia to shut its border with Russia."),
        ("BRUSSELS", "EU-Indonesia sign trade pact; tariffs gone."),
        ("BERLIN", "Coalition rallies to push Moscow to talks."),
        ("WARSAW", "Poland fires up Patriots after airspace breach."),
        ("PARIS", "France probes Depardieu over gang-rape claim."),
    ]),
    ("UKRAINE WAR", TEAL, [
        ("LVIV", "Russian strike kills 2, wounds 10 in the west."),
        ("LONDON", "UK, Ukraine to build strike drones together."),
        ("KYIV", "Zelensky: Russia hit bridges 109 times before."),
        ("SOFIA", "Bulgaria backs India Black Sea ceasefire plan."),
    ]),
    ("AMERICAS", RED, [
        ("SINALOA", "11 killed as cartel violence erupts."),
        ("BRASILIA", "Bolsonaro in ICU with bowel obstruction."),
        ("WASHINGTON", "FBI probes hack of its crime database."),
        ("PENTAGON", "Memo limits socials with Canadian military."),
    ]),
]

REGIONS_RIGHT = [
    ("ASIA-PACIFIC", BLUE, [
        ("PATNA", "Modi opens Nitish Setu bridge in Bihar."),
        ("RANCHI", "Cyclone Akvan cancels 14 flights."),
        ("TOKYO", "Japan to train live-fire in India, a first."),
        ("HONG KONG", "Election Committee voting opens."),
        ("WELLINGTON", "India 629-6, a record total in New Zealand."),
        ("ISLAMABAD", "Suicide bombing kills 5, wounds 13."),
    ]),
    ("MARKETS & TECH", TEAL, [
        ("SHANGHAI", "Leapmotor Q3 profit plunges 73%."),
        ("BEIJING", "Foreign cash into China tech up 31%."),
        ("SHENZHEN", "BYD, Huawei unveil new SUVs."),
        ("LAS VEGAS", "Verstappen on pole; Antonelli penalised."),
        ("WASHINGTON", "Signal blocks screenshots over AI spying."),
        ("LONDON", "Crude oil futures fall more than 3%."),
    ]),
    ("SCIENCE & WORLD", RED, [
        ("TIMOR SEA", "M6.8 quake strikes off Timor-Leste."),
        ("GENEVA", "UN fails to agree rules on \u2018killer robots\u2019."),
        ("JOHANNESBURG", "Mlambo-Ngcuka dies at 71."),
        ("CAPE TOWN", "Murders fall, yet 60 a day are killed."),
        ("DAKAR", "Senegal president imposes budget by decree."),
        ("CAIRO", "Egypt nears $2.3bn IMF payout."),
        ("EUROPA", "Sodium cloud traced around Jupiter\u2019s moon."),
    ]),
]

STATS = [
    ("98.5%", "tariffs scrapped\nin EU-Indonesia deal"),
    ("629-6", "India\u2019s record\ntotal in New Zealand"),
    ("M6.8", "quake off\nTimor-Leste"),
    ("11", "killed in Sinaloa\ncartel violence"),
]

FOOT_A = ("Sources: Reuters \u00b7 AP \u00b7 AFP \u00b7 BBC \u00b7 CNN \u00b7 USGS \u00b7 NYT \u00b7 DW"
          "  \u2014  Events of Sunday 22 November 2026")
FOOT_B = ("39 stories \u00b7 7 regions \u2014 Drawn by a program. No network, "
          "no AI images; every word set in type.")


# ------------------------------------------------------------------ layout
def draw_item(page, faces, x, y, width, dateline, text):
    """One story on a single line: bold dateline, regular rest."""
    head = dateline + " \u2014 "
    after = typeset(page, faces, (BOLD, 15), x, y, head, INK)
    typeset(page, faces, (REG, 15), after, y, text, INK)
    total = measure(faces, (BOLD, 15), head) + \
        measure(faces, (REG, 15), text)
    if total > width:
        raise ValueError("item too wide for column: %s %s (%d > %d)"
                         % (dateline, text, total, width))
    return y + 18


def draw_block(page, faces, x, width, y, regions):
    for kicker, colour, items in regions:
        kw = measure(faces, (BOLD, 19), kicker, tracking=1)
        typeset(page, faces, (BOLD, 19), x, y, kicker, colour, tracking=1)
        page.hline(x, y + 25, kw, colour, 3)
        y += 33
        for dateline, text in items:
            y = draw_item(page, faces, x, y, width, dateline, text)
        y += 6
    return y


def draw_world(page, cx, cy, r):
    page.disc(cx, cy, r, BLUE)
    page.ring(cx, cy, r, INK, 2)
    page.ring(cx, cy, r + 7, INK, 1)
    page.ellipse(cx, cy, 24, r - 4, WHITE)
    page.ellipse(cx, cy, r - 4, 24, WHITE)
    page.chord(cx, cy, r - 2, -28, WHITE)
    page.chord(cx, cy, r - 2, 28, WHITE)
    page.disc(cx + 40, cy - 42, 5, RED)


def render(faces):
    page = Page(PAGE_W, PAGE_H, PAPER)
    page.outline(14, 14, PAGE_W - 28, PAGE_H - 28, INK, 2)
    page.outline(20, 20, PAGE_W - 40, PAGE_H - 40, INK, 1)

    typeset_centred(page, faces, (BOLD, 64), PAGE_W // 2, 32, MASTHEAD, INK)
    typeset_centred(page, faces, (BOLD, 22), PAGE_W // 2, 112, DATE_LINE, RED)
    typeset_centred(page, faces, (REG, 18), PAGE_W // 2, 142, TAG_LINE,
                    INK, tracking=4)
    page.hline(36, 172, PAGE_W - 72, INK, 5)
    page.hline(36, 181, PAGE_W - 72, INK, 1)

    # Lead story, left; drawn globe, right.
    typeset(page, faces, (BOLD, 19), 36, 192, LEAD_KICKER, RED, tracking=1)
    y = 216
    for line in LEAD_LINES:
        typeset(page, faces, (BOLD, 30), 36, y, line, INK)
        y += pitch(faces, (BOLD, 30)) + 2
    y += 6
    y = typeset_para(page, faces, (REG, 20), 36, y, LEAD_TEXT, 664,
                     INK, gap=3)
    draw_world(page, 852, 272, 64)
    page.hline(36, 356, PAGE_W - 72, INK, 1)

    # Region grid, two columns.
    left_end = draw_block(page, faces, 36, 469, 366, REGIONS_LEFT)
    right_end = draw_block(page, faces, 519, 469, 366, REGIONS_RIGHT)
    grid_end = max(left_end, right_end)
    page.rect(512, 368, 1, grid_end - 374, FAINT)

    # Numbers band.
    band_y = grid_end + 10
    band_h = 72
    page.outline(36, band_y, PAGE_W - 72, band_h, INK, 1)
    cell_w = (PAGE_W - 72) // 4
    for i, (big, small) in enumerate(STATS):
        cx = 36 + cell_w * i
        if i:
            page.rect(cx, band_y + 8, 1, band_h - 16, FAINT)
        typeset_centred(page, faces, (BOLD, 30), cx + cell_w // 2,
                        band_y + 4, big, RED)
        for j, line in enumerate(small.split("\n")):
            typeset_centred(page, faces, (REG, 15), cx + cell_w // 2,
                            band_y + 38 + j * 17, line, INK)

    page.hline(36, 956, PAGE_W - 72, INK, 1)
    typeset_centred(page, faces, (REG, 14), PAGE_W // 2, 964, FOOT_A, INK)
    typeset_centred(page, faces, (REG, 14), PAGE_W // 2, 982, FOOT_B, INK)
    return page


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    faces = read_font_faces(os.path.join(here, "atlas.bin"))
    data = encode_png(render(faces))
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if not outdir:
        outdir = "/output" if os.path.isdir("/output") else "out"
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "entry.png")
    with open(path, "wb") as handle:
        handle.write(data)
    sys.stdout.write("wrote %s (%d bytes)\n" % (path, len(data)))


if __name__ == "__main__":
    main()
