"""Rocket Geodome - simple sheet layout and DXF export (v1.0, pure Python).

The flat parts of one build (boards, hub plates, spacers; the stubs of a test
hub) go onto sheets by their bounding boxes: rows along the long side of the
sheet, boards longest first, then plates and spacers in the room left and on
new sheets. Parts turn by 0 or 90 degrees only, and a board (grain along its
length) always lies along the long side. One DXF per sheet with the layers
CUT (outlines), HOLES (holes and slots), TEXT (part type) and SHEET (sheet edge).

The part list comes from the core for this dome only - never from the Fusion
design - so no other body of the project can end up on a sheet.
All lengths in mm; a sheet runs x along its long side, y along the short one.
"""
import math

try:
    from . import geodome_core as core
except ImportError:          # the tests import the modules side by side
    import geodome_core as core

EPS = 1e-6
ARC_STEP = math.radians(5.0)          # arc sampling for the bounding boxes and cut outlines
LAYERS = (('CUT', 7), ('HOLES', 1), ('TEXT', 3), ('SHEET', 8))   # name, AutoCAD colour


# ------------------------------------------------------------------ geometry
def arc_geometry(p0, pm, p1):
    """Centre, radius, start angle and signed sweep (+ = counter-clockwise) of
    the arc from p0 through pm to p1; None for three points on a line."""
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    den = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(den) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / den
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / den
    r = math.hypot(ax - ux, ay - uy)
    a0, am, a1 = (math.atan2(q[1] - uy, q[0] - ux) for q in (p0, pm, p1))
    tw = 2.0 * math.pi
    span = (a1 - a0) % tw if (am - a0) % tw < (a1 - a0) % tw else -((a0 - a1) % tw)
    return (ux, uy), r, a0, span


def loop_points(loop):
    """Closed loop -> polygon points, arcs sampled every ARC_STEP."""
    if loop and loop[0][0] == 'C':
        (cx, cy), r = loop[0][1], loop[0][2]
        k = 72
        return [(cx + r * math.cos(2.0 * math.pi * i / k), cy + r * math.sin(2.0 * math.pi * i / k)) for i in range(k)]
    pts = []
    for el in loop:
        if el[0] == 'L':
            pts.append(el[1])
            continue
        g = arc_geometry(el[1], el[2], el[3])
        if g is None:
            pts.append(el[1])
            continue
        (ux, uy), r, a0, span = g
        k = max(2, int(math.ceil(abs(span) / ARC_STEP)))
        pts += [(ux + r * math.cos(a0 + span * i / k), uy + r * math.sin(a0 + span * i / k)) for i in range(k)]
    return pts


def _bbox(points):
    xs, ys = [q[0] for q in points], [q[1] for q in points]
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------------- parts
class Part:
    """One part type: its loops in its own frame, how many, grain, the text."""

    def __init__(self, key, label, kind, geo, qty, text_height, title=None):
        self.key = key            # name in the build and the BOM: 'Board A', 'Plate H6a', 'Spacer', 'Stub A'
        self.title = title or key  # as reports and file names show it: a model's 'Plate 2 (H6a)'
        self.label = label        # short type written on the part: 'A', 'H6a', 'S'
        self.kind = kind          # 'board' / 'plate' / 'spacer'
        self.qty = int(qty)
        self.grain = geo.get('grain', 'any')
        self.thickness = geo.get('thickness', 0.0)
        clip = geo.get('clip')
        loops = geo['loops']
        # outline: exact elements, or a polygon when a base plate is cut at the floor
        self.outer = ('poly', core._clip_x(loop_points(loops[0]), clip)) if clip is not None else _shape(loops[0])
        self.holes = []
        for loop in loops[1:]:
            if clip is None:
                self.holes.append(_shape(loop))
                continue
            pts = loop_points(loop)
            xs = [q[0] for q in pts]
            if max(xs) <= clip + EPS:
                self.holes.append(_shape(loop))
            elif min(xs) < clip - EPS:        # a slot cut open by the floor line: its part inside
                self.holes.append(('poly', core._clip_x(pts, clip)))
        outer_pts = self.outer[1] if self.outer[0] == 'poly' else loop_points(loops[0])
        self.bbox = _bbox(outer_pts)
        self.size = (self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1])
        self.texts = []
        for lab in geo.get('labels') or []:
            if lab and lab[0]:
                h = lab[3] if len(lab) > 3 else text_height
                self.texts.append((lab[0], lab[1], lab[2], h))
        if not self.texts:                    # every part carries its type
            h = min(text_height, 0.5 * min(self.size))
            self.texts.append((label, (self.bbox[0] + self.bbox[2]) / 2.0, (self.bbox[1] + self.bbox[3]) / 2.0, h))


def _shape(loop):
    if loop and loop[0][0] == 'C':
        return ('circle', loop[0][1], loop[0][2])
    return ('elems', loop)


def flat_parts(d, mode='Full dome'):
    """The flat parts of a build - the same names and counts the add-in builds."""
    p = d.p
    th = p.label_height
    parts = []
    if mode == 'Test hub':
        n = core.test_hub_node(d)
        outer_name, inner_name = d.node_plate_names[n]
        for key, name, inner in (('Plate {} outer'.format(outer_name), outer_name, False),
                                 ('Plate {} inner'.format(inner_name), inner_name, True)):
            parts.append(Part(key, name, 'plate', core.plate_geometry(d, n, inner), 1, th, core.part_title(d, key)))
        stub_qty, spacer_qty = {}, 0
        for _m, ti, _si in d.adj[n]:
            stub_qty[ti] = stub_qty.get(ti, 0) + p.boards_per_strut
            spacer_qty += len(core.board_geometry(d, ti, stub=True)['spacers_x'])
        for ti in sorted(stub_qty):
            parts.append(Part('Stub ' + core.LETTERS[ti], core.LETTERS[ti], 'board',
                              core.board_geometry(d, ti, stub=True), stub_qty[ti], th))
        if spacer_qty:
            parts.append(Part('Spacer', 'S', 'spacer', core.spacer_geometry(d), spacer_qty, th))
        return parts
    for ti, t in enumerate(d.types):
        parts.append(Part('Board ' + t.letter, t.letter, 'board', core.board_geometry(d, ti),
                          t.count * p.boards_per_strut, th))
    placements, reps = core.plate_placements(d)
    qty = {}
    for name, _frame in placements:
        qty[name] = qty.get(name, 0) + 1
    for pt in d.plate_types:
        n, inner = reps[pt.name]
        parts.append(Part('Plate ' + pt.name, pt.name, 'plate', core.plate_geometry(d, n, inner), qty[pt.name], th,
                          core.part_title(d, 'Plate ' + pt.name)))
    if p.boards_per_strut == 2 and d.n_spacers:
        parts.append(Part('Spacer', 'S', 'spacer', core.spacer_geometry(d), d.n_spacers, th))
    return parts


# -------------------------------------------------------------------- layout
class Placement:
    """A part on a sheet: (x, y) is the corner of its turned bounding box."""
    __slots__ = ('part', 'x', 'y', 'rot', 'w', 'h')

    def __init__(self, part, x, y, rot, w, h):
        self.part, self.x, self.y, self.rot, self.w, self.h = part, x, y, rot, w, h

    def frame2d(self):
        """(origin, x axis, y axis) of the part frame on the sheet."""
        bx0, by0, bx1, by1 = self.part.bbox
        if self.rot == 0:
            return (self.x - bx0, self.y - by0), (1.0, 0.0), (0.0, 1.0)
        return (self.x + by1, self.y - bx0), (0.0, 1.0), (-1.0, 0.0)

    def to_sheet(self, q):
        o, ex, ey = self.frame2d()
        return (o[0] + q[0] * ex[0] + q[1] * ey[0], o[1] + q[0] * ex[1] + q[1] * ey[1])


class Layout:
    def __init__(self, parts, sheet_len, sheet_wid, margin, gap):
        self.parts = parts
        self.L, self.W = max(sheet_len, sheet_wid), min(sheet_len, sheet_wid)
        self.margin, self.gap = margin, gap
        self.sheets = []          # per sheet: [Placement]
        self.misfit = {}          # part key -> pieces that fit no sheet
        self.by_type = False      # every sheet holds one part type (a model's print beds)

    @property
    def placed(self):
        out = {}
        for sheet in self.sheets:
            for pl in sheet:
                out[pl.part.key] = out.get(pl.part.key, 0) + 1
        return out


def pack(parts, sheet_len, sheet_wid, margin, gap, by_type=False):
    """Rows (shelves) along the long side: first fit, boards longest first and all
    in rows of one height, then plates and spacers biggest first. by_type: every
    part type on sheets of its own, in the order of parts (a bed is one pile)."""
    if by_type:
        lay = Layout(parts, sheet_len, sheet_wid, margin, gap)
        lay.by_type = True
        for part in parts:
            own = _pack([part], sheet_len, sheet_wid, margin, gap)
            lay.sheets += own.sheets
            for key, q in own.misfit.items():
                lay.misfit[key] = lay.misfit.get(key, 0) + q
        return lay
    return _pack(parts, sheet_len, sheet_wid, margin, gap)


def _pack(parts, sheet_len, sheet_wid, margin, gap):
    lay = Layout(parts, sheet_len, sheet_wid, margin, gap)
    x_max, y_max = lay.L - margin, lay.W - margin
    room_x, room_y = x_max - margin, y_max - margin
    rows, tops = [], []           # rows: [sheet, y, height, next x]; tops: next free y per sheet

    def turns(part):
        w, h = part.size
        if part.grain == 'length':
            return [(0, w, h)]
        return sorted([(0, w, h), (90, h, w)], key=lambda o: o[2])   # the flatter way first

    boards = sorted((pt for pt in parts if pt.kind == 'board'), key=lambda pt: -pt.size[0])
    others = sorted((pt for pt in parts if pt.kind != 'board'),
                    key=lambda pt: (pt.kind != 'plate', -max(pt.size), -min(pt.size)))
    board_h = max([pt.size[1] for pt in boards if pt.size[0] <= room_x + EPS and pt.size[1] <= room_y + EPS] or [0.0])

    def place(row, part, rot, w, h):
        sheet, y = row[0], row[1]
        lay.sheets[sheet].append(Placement(part, row[3], y, rot, w, h))
        row[3] += w + gap

    def open_row(sheet, y, height):
        row = [sheet, y, height, margin]
        rows.append(row)
        tops[sheet] = y + height + gap
        return row

    for part in boards + others:
        options = turns(part)
        for _ in range(part.qty):
            done = False
            for row in rows:                                   # 1. room left in a row
                for rot, w, h in options:
                    if h <= row[2] + EPS and row[3] + w <= x_max + EPS:
                        place(row, part, rot, w, h)
                        done = True
                        break
                if done:
                    break
            if done:
                continue
            fitting = [o for o in options if o[1] <= room_x + EPS and o[2] <= room_y + EPS]
            if not fitting:
                lay.misfit[part.key] = lay.misfit.get(part.key, 0) + 1
                continue
            heights = []
            for rot, w, h in fitting:                          # boards: rows of one height
                if part.kind == 'board' and board_h > h:
                    heights.append((rot, w, h, board_h))
                heights.append((rot, w, h, h))
            for sheet in range(len(tops)):                     # 2. a new row on a sheet
                for rot, w, h, hh in heights:
                    if tops[sheet] + hh <= y_max + EPS:
                        place(open_row(sheet, tops[sheet], hh), part, rot, w, h)
                        done = True
                        break
                if done:
                    break
            if done:
                continue
            lay.sheets.append([])                              # 3. a new sheet
            tops.append(margin)
            rot, w, h, hh = heights[0]
            place(open_row(len(tops) - 1, margin, hh), part, rot, w, h)
    return lay


def check(lay, eps=1e-6):
    """Problems of a layout: parts off the sheet, overlapping or too close."""
    problems = []
    lo_x, lo_y, hi_x, hi_y = lay.margin, lay.margin, lay.L - lay.margin, lay.W - lay.margin
    for s, sheet in enumerate(lay.sheets):
        for pl in sheet:
            pts = [pl.to_sheet(q) for q in _outline_points(pl.part)]
            x0, y0, x1, y1 = _bbox(pts)
            if x0 < lo_x - eps or y0 < lo_y - eps or x1 > hi_x + eps or y1 > hi_y + eps:
                problems.append('sheet {}: {} off the sheet'.format(s + 1, pl.part.key))
            if abs((x1 - x0) - pl.w) > 1e-3 or abs((y1 - y0) - pl.h) > 1e-3 or abs(x0 - pl.x) > 1e-3 \
                    or abs(y0 - pl.y) > 1e-3:
                problems.append('sheet {}: {} box mismatch'.format(s + 1, pl.part.key))
        boxes = sorted(((pl.x, pl.y, pl.x + pl.w, pl.y + pl.h, pl.part.key) for pl in sheet))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                if b[0] >= a[2] + lay.gap - eps:
                    break
                if b[1] < a[3] + lay.gap - eps and a[1] < b[3] + lay.gap - eps:
                    problems.append('sheet {}: {} and {} closer than {} mm'.format(s + 1, a[4], b[4], lay.gap))
    return problems


def _outline_points(part):
    if part.outer[0] == 'poly':
        return part.outer[1]
    if part.outer[0] == 'circle':
        return loop_points([('C', part.outer[1], part.outer[2])])
    return loop_points(part.outer[1])


# ----------------------------------------------------------------------- DXF
class _Dxf:
    """Minimal DXF R12 (AC1009) writer: closed polylines with arcs as bulges,
    circles, centred text. Opens in every CAD, CAM and laser program."""

    def __init__(self):
        self.out = []

    def tag(self, code, value):
        if isinstance(value, float):
            value = '{:.4f}'.format(value)
        self.out.append('{}\n{}\n'.format(code, value))

    def polyline(self, layer, vertices):
        """vertices: [(x, y, bulge)], closed."""
        self.tag(0, 'POLYLINE')
        self.tag(8, layer)
        self.tag(66, 1)
        self.tag(10, 0.0)
        self.tag(20, 0.0)
        self.tag(30, 0.0)
        self.tag(70, 1)
        for x, y, bulge in vertices:
            self.tag(0, 'VERTEX')
            self.tag(8, layer)
            self.tag(10, float(x))
            self.tag(20, float(y))
            self.tag(30, 0.0)
            if abs(bulge) > 1e-12:
                self.tag(42, float(bulge))
        self.tag(0, 'SEQEND')
        self.tag(8, layer)

    def circle(self, layer, c, r):
        self.tag(0, 'CIRCLE')
        self.tag(8, layer)
        self.tag(10, float(c[0]))
        self.tag(20, float(c[1]))
        self.tag(30, 0.0)
        self.tag(40, float(r))

    def text(self, layer, s, at, height, angle):
        self.tag(0, 'TEXT')
        self.tag(8, layer)
        self.tag(10, float(at[0]))
        self.tag(20, float(at[1]))
        self.tag(30, 0.0)
        self.tag(40, float(height))
        self.tag(1, s)
        self.tag(50, float(angle))
        self.tag(72, 1)                    # centred
        self.tag(11, float(at[0]))
        self.tag(21, float(at[1]))
        self.tag(31, 0.0)
        self.tag(73, 2)                    # middle

    def document(self, extents):
        head = _Dxf()
        head.tag(0, 'SECTION')
        head.tag(2, 'HEADER')
        head.tag(9, '$ACADVER')
        head.tag(1, 'AC1009')
        head.tag(9, '$INSBASE')
        head.tag(10, 0.0)
        head.tag(20, 0.0)
        head.tag(30, 0.0)
        head.tag(9, '$EXTMIN')
        head.tag(10, 0.0)
        head.tag(20, 0.0)
        head.tag(30, 0.0)
        head.tag(9, '$EXTMAX')
        head.tag(10, float(extents[0]))
        head.tag(20, float(extents[1]))
        head.tag(30, 0.0)
        head.tag(0, 'ENDSEC')
        head.tag(0, 'SECTION')
        head.tag(2, 'TABLES')
        head.tag(0, 'TABLE')
        head.tag(2, 'LTYPE')
        head.tag(70, 1)
        head.tag(0, 'LTYPE')
        head.tag(2, 'CONTINUOUS')
        head.tag(70, 0)
        head.tag(3, 'Solid line')
        head.tag(72, 65)
        head.tag(73, 0)
        head.tag(40, 0.0)
        head.tag(0, 'ENDTAB')
        head.tag(0, 'TABLE')
        head.tag(2, 'LAYER')
        head.tag(70, len(LAYERS))
        for name, colour in LAYERS:
            head.tag(0, 'LAYER')
            head.tag(2, name)
            head.tag(70, 0)
            head.tag(62, colour)
            head.tag(6, 'CONTINUOUS')
        head.tag(0, 'ENDTAB')
        head.tag(0, 'ENDSEC')
        head.tag(0, 'SECTION')
        head.tag(2, 'BLOCKS')
        head.tag(0, 'ENDSEC')
        head.tag(0, 'SECTION')
        head.tag(2, 'ENTITIES')
        tail = '0\nENDSEC\n0\nEOF\n'
        return ''.join(head.out) + ''.join(self.out) + tail


def _shape_out(dxf, layer, shape, pl):
    kind = shape[0]
    if kind == 'circle':
        dxf.circle(layer, pl.to_sheet(shape[1]), shape[2])
    elif kind == 'poly':
        dxf.polyline(layer, [pl.to_sheet(q) + (0.0,) for q in shape[1]])
    else:
        verts = []
        for el in shape[1]:
            bulge = 0.0
            if el[0] == 'A':
                g = arc_geometry(el[1], el[2], el[3])
                bulge = math.tan(g[3] / 4.0) if g else 0.0
            verts.append(pl.to_sheet(el[1]) + (bulge,))
        dxf.polyline(layer, verts)


def sheet_dxf(lay, index):
    """DXF text of sheet `index` (0-based)."""
    dxf = _Dxf()
    dxf.polyline('SHEET', [(0.0, 0.0, 0.0), (lay.L, 0.0, 0.0), (lay.L, lay.W, 0.0), (0.0, lay.W, 0.0)])
    for pl in lay.sheets[index]:
        _shape_out(dxf, 'CUT', pl.part.outer, pl)
        for hole in pl.part.holes:
            _shape_out(dxf, 'HOLES', hole, pl)
        for s, x, y, h in pl.part.texts:
            dxf.text('TEXT', s, pl.to_sheet((x, y)), h, float(pl.rot))
    return dxf.document((lay.L, lay.W))


def type_counts(sheet):
    out = {}
    for pl in sheet:
        out[pl.part.key] = out.get(pl.part.key, 0) + 1
    return out


def sheet_contents(lay, index):
    """What lies on a sheet, in the order of the parts: 'Board E x30, Spacer x10'."""
    counts = type_counts(lay.sheets[index])
    return ', '.join('{} x{}'.format(pt.title, counts[pt.key]) for pt in lay.parts if counts.get(pt.key))


def type_beds(lay):
    """Per part type the sheets (1-based) it lies on: [(part, first, last)]."""
    out = []
    for pt in lay.parts:
        nums = [i + 1 for i, sheet in enumerate(lay.sheets) if any(pl.part is pt for pl in sheet)]
        if nums:
            out.append((pt, nums[0], nums[-1]))
    return out


def summary_lines(lay, lang='en'):
    """Short report of a layout for the dialog and the final message."""
    ru = lang == 'ru'
    total = sum(lay.placed.values())
    out = [('Листов {} ({:g} × {:g} мм), деталей {}' if ru else 'Sheets {} ({:g} x {:g} mm), parts {}')
           .format(len(lay.sheets), lay.L, lay.W, total)]
    placed = lay.placed
    keys = [pt for pt in lay.parts if placed.get(pt.key)]
    if lay.by_type:      # a pile per bed: which beds hold which type, a line per kind of part
        out[0] = (('Столов {} ({:g} × {:g} мм), деталей {}, на каждом столе один тип' if ru else
                   'Beds {} ({:g} x {:g} mm), parts {}, one type per bed').format(len(lay.sheets), lay.L, lay.W, total))
        beds = type_beds(lay)
        for kind, ru_name, en_name in (('board', 'Доски', 'Boards'), ('plate', 'Пластины', 'Plates'),
                                       ('spacer', 'Проставки', 'Spacers')):
            items = []
            for pt, first, last in beds:
                if pt.kind != kind:
                    continue
                where = (('стол {}' if ru else 'bed {}').format(first) if first == last else
                         ('столы {}–{}' if ru else 'beds {}-{}').format(first, last))
                short = pt.title.split(' ', 1)[1] + ' ' if ' ' in pt.title else ''   # 'A ', '2 (H6a) '
                items.append('{}×{} — {}'.format(short, placed[pt.key], where))
            if items:
                out.append('{}: {}'.format(ru_name if ru else en_name, ', '.join(items)))
    elif keys:
        out.append(', '.join('{} ×{}'.format(pt.title, placed[pt.key]) for pt in keys))
    if lay.misfit:
        out.append(('Не помещается на лист: {}' if ru else 'Does not fit a sheet: {}').format(
            ', '.join('{} ×{}'.format(k, q) for k, q in lay.misfit.items())))
    return out
