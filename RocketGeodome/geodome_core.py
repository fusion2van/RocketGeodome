"""Rocket Geodome - geometry core (pure Python, no Fusion imports).

All lengths are in mm. The grid is computed on the unit sphere and scaled by R.
Spec: "Rocket Geodome - TZ v1" (step 1: grid, hemisphere, strut types,
hub radius, plate types, numbers for the dialog).

Base shapes (v0.6): the hemisphere as before; the hemisphere on straight walls
(posts and rings under the equator); arches on legs (v0.7: a cap of the five
upper icosahedron faces on five long V legs, the feet standing in platforms).
Every node has a position and a hub axis; each strut lies in one plane with
both hub axes, so its boards are flat and every tenon sits square in its plates.
"""
import math
import re
from dataclasses import dataclass, asdict, fields
from itertools import combinations

VERSION = "1.0.0"

# --- v1 constants (spec: "Konstanty v1"); shape constants shrink with a model ---
SPACER_SHOULDER = 10.0   # mm, spacer shoulders top and bottom
TRANSITION_GAP = 2.0     # mm, the board's inner edge clears the inner plate edge by this
LABEL_DEPTH = 0.5        # mm, engraved label cut
DENSITY = 650.0          # kg/m3, plywood (weight estimate)
SHEET_MARGIN = 10.0      # mm, default sheet edge allowance (fit check and layout)
MIN_SPACER_ZONE = 50.0   # mm, shorter middle part -> no spacer
# --- printed model 1:N ---
PLA_DENSITY = 1240.0     # kg/m3, solid PLA (weight estimate)
BED_MARGIN = 5.0         # mm, default print bed edge allowance (fit check and layout)
TUBE_WALL = 1.6          # mm, printed tube wall (4 lines of a 0.4 mm nozzle)
# sizes divided by N in a model; thicknesses, clearance, hole, labels and the
# sheet come from the print values instead
SCALED_FIELDS = ('diameter', 'frame_depth', 'board_gap', 'spacer_max', 'spacer_inset',
                 'tenon_len', 'min_web', 'plate_margin', 'corner_radius', 'wall_height', 'leg_length')

FREQUENCIES = (2, 4, 6)
BASE_SHAPES = ('Hemisphere', 'Walls', 'Arches')
MAX_WALL_ROWS = 4
ICOSA_Z = 1.0 / math.sqrt(5.0)     # height of the upper icosahedron ring on the unit sphere
LEG_AUTO = 1.3                     # auto leg: long sides 1.3 x the cap edge (the Quadrome photo)
SOCKET_DEPTH = 1.5                 # foot platform: socket depth = 1.5 x the leg board width
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ANGLE_TOL = 0.02         # deg, tolerance when comparing hub patterns


# ---------------------------------------------------------------- parameters
@dataclass
class Params:
    diameter: float = 6000.0       # D, outer node sphere
    frequency: int = 4             # 2, 4, 6
    base_shape: str = "Hemisphere"  # Hemisphere / Walls / Arches
    wall_height: float = 1000.0    # Walls: floor to the equator ring centre
    wall_rows: int = 1             # Walls: post segments up the wall (rings between them)
    leg_length: float = 0.0        # Arches: long side of a leg, foot to hub, 0 = auto
    frame_depth: float = 150.0     # h, radial
    boards_per_strut: int = 2      # n
    plywood: float = 18.0          # t
    board_gap: float = 30.0        # g
    spacer_max: float = 400.0      # s_max
    spacer_inset: float = 20.0
    plate: float = 18.0            # t_p
    tenon_len: float = 50.0        # L_t
    min_web: float = 10.0          # s_min
    plate_margin: float = 25.0     # m
    plate_shape: str = "Hull"      # Hull / Circle
    corner_radius: float = 10.0    # R_c
    center_hole: float = 12.0      # d_hole (M12, bolt hammered in)
    clearance: float = 0.2         # c, per side
    dogbone: float = 8.2           # 8 mm cutter + 0.2
    sheet_len: float = 2500.0
    sheet_wid: float = 1250.0
    sheet_margin: float = SHEET_MARGIN   # layout: sheet edge to the parts
    part_gap: float = 10.0         # layout: between parts (8 mm cutter + 2)
    labels: bool = True
    label_height: float = 12.0
    model_scale: float = 1.0       # N in 1:N, 1 = the real dome
    print_plywood: float = 3.0     # model: boards and spacers
    print_plate: float = 3.0       # model: hub plates
    print_clearance: float = 0.2   # model: clearance per side
    print_hole: float = 3.3        # model: centre hole (M3)
    print_labels: bool = True
    print_label_height: float = 8.0  # model: letters on the boards, the hub digit at most
    print_label_depth: float = 1.0   # model: how deep letters and digits are cut (prints well)
    bed_len: float = 256.0         # Bambu Lab P2S
    bed_wid: float = 256.0
    bed_margin: float = BED_MARGIN   # model layout: bed edge to the parts
    bed_gap: float = 3.0           # model layout: between parts
    bed_by_type: bool = True       # model layout: one part type per bed

    @property
    def is_model(self):
        return self.model_scale > 1.0 + 1e-9

    def effective(self):
        """The sizes actually built. Real dome: these parameters as they are.
        Model 1:N: shape sizes divided by N, thicknesses, clearance, hole and
        labels from the print values, no dogbones, the print bed as the sheet."""
        if not self.is_model:
            return self
        q = Params.from_dict(self.to_dict())
        for name in SCALED_FIELDS:
            setattr(q, name, getattr(self, name) / self.model_scale)
        q.plywood, q.plate = self.print_plywood, self.print_plate
        q.clearance, q.center_hole, q.dogbone = self.print_clearance, self.print_hole, 0.0
        q.labels, q.label_height = self.print_labels, self.print_label_height
        q.sheet_len, q.sheet_wid = self.bed_len, self.bed_wid
        q.sheet_margin, q.part_gap = self.bed_margin, self.bed_gap
        q.model_scale = 1.0   # already in model units, never scaled twice
        return q

    @property
    def R(self):
        return self.diameter / 2.0

    @property
    def width(self):
        """w = n*t + (n-1)*g, strut width across."""
        n = self.boards_per_strut
        return n * self.plywood + (n - 1) * self.board_gap

    @property
    def dogbone_overcut(self):
        """Dogbone circle through the corner, centre on the bisector inside the
        slot: it bulges past each slot edge by r*(1 - 1/sqrt(2))."""
        return self.dogbone / 2.0 * (1.0 - 1.0 / math.sqrt(2.0))

    def board_offsets(self):
        """d_i = (i - (n-1)/2) * (t + g)"""
        n = self.boards_per_strut
        return [(i - (n - 1) / 2.0) * (self.plywood + self.board_gap) for i in range(n)]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        p = cls()
        for f in fields(cls):
            if f.name in data:
                cur = getattr(p, f.name)
                try:
                    setattr(p, f.name, type(cur)(data[f.name]))
                except (TypeError, ValueError):
                    pass
        if 'print_label_depth' not in data and data.get('print_label_height') == 5.0:
            p.print_label_height = cls.print_label_height   # saved before the model letters grew
        return p


# ------------------------------------------------------------------- vectors
def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _len(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _len(a)
    return (a[0] / n, a[1] / n, a[2] / n)


# ---------------------------------------------------------------------- grid
_GRID_CACHE = {}


def _rotation_to_z(v):
    """Rodrigues rotation that takes unit vector v to +Z."""
    z = (0.0, 0.0, 1.0)
    k = _cross(v, z)
    s = _len(k)
    c = _dot(v, z)
    if s < 1e-12:
        return (lambda p: p) if c > 0 else (lambda p: (p[0], -p[1], -p[2]))
    k = _mul(k, 1.0 / s)

    def rot(p):
        kp = _cross(k, p)
        kd = _dot(k, p)
        return tuple(p[i] * c + kp[i] * s + k[i] * kd * (1.0 - c) for i in range(3))
    return rot


def _icosahedron():
    """Unit icosahedron: a vertex at +Z, first upper-ring vertex at azimuth 0."""
    phi = (1.0 + 5.0 ** 0.5) / 2.0
    raw = []
    for a in (-1.0, 1.0):
        for b in (-phi, phi):
            raw += [(0.0, a, b), (a, b, 0.0), (b, 0.0, a)]
    verts = [_unit(v) for v in raw]
    rot = _rotation_to_z(verts[0])
    verts = [rot(v) for v in verts]
    ring = sorted((v for v in verts if 0.1 < v[2] < 0.9), key=lambda v: math.atan2(v[1], v[0]))
    az = math.atan2(ring[0][1], ring[0][0])
    ca, sa = math.cos(-az), math.sin(-az)
    verts = [(v[0] * ca - v[1] * sa, v[0] * sa + v[1] * ca, v[2]) for v in verts]
    edge = min(_len(_sub(a, b)) for a, b in combinations(verts, 2))
    faces = [f for f in combinations(range(12), 3)
             if all(abs(_len(_sub(verts[i], verts[j])) - edge) < 1e-9 for i, j in combinations(f, 2))]
    return verts, faces


def build_grid(freq):
    """Full-sphere class I (method 1) grid on the unit sphere -> (points, edges)."""
    if freq in _GRID_CACHE:
        return _GRID_CACHE[freq]
    verts, faces = _icosahedron()
    pts = []

    def index_of(p):
        for i, q in enumerate(pts):
            if abs(p[0] - q[0]) < 1e-7 and abs(p[1] - q[1]) < 1e-7 and abs(p[2] - q[2]) < 1e-7:
                return i
        pts.append(p)
        return len(pts) - 1

    edges = set()
    for a, b, c in faces:
        A, B, C = verts[a], verts[b], verts[c]
        grid = {}
        for i in range(freq + 1):
            for j in range(freq + 1 - i):
                k = freq - i - j
                p = _unit(tuple((i * A[t] + j * B[t] + k * C[t]) / freq for t in range(3)))
                grid[(i, j)] = index_of(p)
        for (i, j), u in grid.items():
            for di, dj in ((1, 0), (0, 1), (1, -1)):
                v = grid.get((i + di, j + dj))
                if v is not None:
                    edges.add((min(u, v), max(u, v)))
    result = (pts, sorted(edges))
    _GRID_CACHE[freq] = result
    return result


def hemisphere(freq):
    """Nodes with z >= 0 (top node first) and struts with both ends kept.
    Returns (nodes, struts, crossing) - crossing must be 0 for even frequencies."""
    pts, edges = build_grid(freq)
    keep = [i for i, p in enumerate(pts) if p[2] > -1e-9]

    def order(i):
        x, y, z = pts[i]
        return (round(-z, 9), round(math.atan2(y, x) % (2.0 * math.pi), 9))
    keep.sort(key=order)
    new = {old: n for n, old in enumerate(keep)}
    nodes = []
    for old in keep:
        x, y, z = pts[old]
        nodes.append(_unit((x, y, 0.0)) if abs(z) < 1e-9 else (x, y, z))
    struts = sorted((min(new[a], new[b]), max(new[a], new[b]))
                    for a, b in edges if a in new and b in new)
    crossing = sum(1 for a, b in edges
                   if (pts[a][2] > 1e-9 and pts[b][2] < -1e-9) or (pts[b][2] > 1e-9 and pts[a][2] < -1e-9))
    return nodes, struts, crossing


# ------------------------------------------------------------- hub patterns
def _tangent_dir(P, Q, axis=None):
    """Direction from node P towards Q in the hub plane at P (normal = axis,
    the unit vector of P on the sphere)."""
    ax = P if axis is None else axis
    d = _sub(Q, P)
    return _unit(_sub(d, _mul(ax, _dot(d, ax))))


def _ref_dir(axis, base):
    """Reference direction in the hub plane: down for base hubs (the floor cut
    fixes their rotation), towards the apex for the rest, +X at the apex."""
    if base:
        down = (0.0, 0.0, -1.0)
        return _unit(_sub(down, _mul(axis, _dot(down, axis))))
    up = (0.0, 0.0, 1.0)
    d = _sub(up, _mul(axis, _dot(up, axis)))
    if _len(d) < 1e-9:
        return (1.0, 0.0, 0.0)
    return _unit(d)


def _gaps(items):
    """items: [(angle_deg, letter)] sorted -> cyclic [(gap_to_next_deg, letter)]"""
    k = len(items)
    return [((items[(i + 1) % k][0] - items[i][0]) % 360.0, items[i][1]) for i in range(k)]


def _mirror(base, pat):
    if base:
        return sorted(((360.0 - a) % 360.0, L) for a, L in pat)
    k = len(pat)
    return [(pat[(k - 2 - j) % k][0], pat[k - 1 - j][1]) for j in range(k)]


def _pattern_match(base, a, b):
    if len(a) != len(b):
        return False
    if base:
        return all(x[1] == y[1] and abs(x[0] - y[0]) < ANGLE_TOL for x, y in zip(a, b))
    n = len(a)
    for s in range(n):
        if all(a[(i + s) % n][1] == b[i][1] and abs(a[(i + s) % n][0] - b[i][0]) < ANGLE_TOL
               for i in range(n)):
            return True
    return False


# ------------------------------------------------------------------ analysis
@dataclass
class StrutType:
    letter: str
    factor: float        # chord / R
    count: int           # struts of this type
    half_angle: float    # theta/2, rad: tilt of the hub axis at the P end (x < 0)
    chord_out: float = 0.0
    board_len: float = 0.0
    board_wid: float = 0.0
    middle_len: float = 0.0
    spacers_each: int = 0
    y_out: float = 0.0   # straight outer edge at x = 0, board coordinates (outer chord at y = 0)
    y_in: float = 0.0    # straight inner edge at x = 0
    phi_q: float = None  # tilt of the hub axis at the Q end (x > 0); = half_angle on the sphere
    k_out: float = 0.0   # slopes of the edges (0 when both ends are alike)
    k_in: float = 0.0
    x_lo: float = 0.0    # middle zone between the plate footprints (spacers go here)
    x_hi: float = 0.0
    kind: str = 'dome'   # dome / wall / leg
    socket: bool = False  # the Q end stands in a foot platform socket: square cut, pin hole
    x_cut: float = 0.0   # socket end: the board's end face (x), the seat of the socket
    depth: float = 0.0   # socket end: how deep the board goes into the socket
    x_pin: float = 0.0   # socket end: pin hole position (x), on the centre line

    def __post_init__(self):
        if self.phi_q is None:
            self.phi_q = self.half_angle

    @property
    def symmetric(self):
        return not self.socket and abs(self.phi_q - self.half_angle) < 1e-9

    def yo(self, x):
        return self.y_out + self.k_out * x

    def yi(self, x):
        return self.y_in + self.k_in * x

    def ym(self, x):
        return (self.yo(x) + self.yi(x)) / 2.0


@dataclass
class PlateType:
    name: str
    valence: int
    base: bool
    qty: int


class Dome:
    """Everything the dialog shows for one parameter set."""

    def __init__(self, src):
        self.src = src                     # parameters as entered (real dome + scale)
        self.model = src.is_model
        self.k = src.model_scale if self.model else 1.0
        u = 1.0 / self.k                   # internal mm constants shrink with the model
        self.transition = TRANSITION_GAP * u
        self.shoulder = SPACER_SHOULDER * u
        self.min_spacer_zone = MIN_SPACER_ZONE * u
        self.stub_spacer = STUB_SPACER * u
        self.stub_middle = STUB_MIDDLE * u
        self.r_step = 1.0 * u              # hub radius rounded up to this
        self.density = PLA_DENSITY if self.model else DENSITY
        p = src.effective()
        self.margin = p.sheet_margin       # sheet (or print bed) edge allowance
        self.p = p                         # sizes actually built (model units in a model)
        self.shape = p.base_shape
        self.errors = []
        self.warnings = []
        self.nodes = []           # unit vectors of the outer nodes (on the sphere: the grid itself)
        self.pos = []             # outer node points, mm
        self.axis = []            # hub axes (unit, outwards)
        self.feet = []            # Arches: the foot nodes (they stand in platforms, no plates)
        self.socket = []          # per node: a foot, the leg boards end in a platform socket
        self.leg_len = 0.0        # Arches: long side of a leg, foot node to hub node
        self.leg_drop = 0.0       # Arches: foot node below the equator
        self.foot_angle = 0.0     # Arches: angle between the two long sides at the foot, rad
        self.platform = None      # Arches: the foot platform (see platform_geometry)
        self.wall_posts = 0       # Walls: posts per ring of the wall
        self.struts = []          # (a, b, type_index); a is the P end of the type's board
        self.types = []           # StrutType
        self.plate_types = []     # PlateType
        self.plate_codes = {}     # plate type -> the digit a model's plate carries ('1', '2', ...)
        self.base = []
        self.crossing = 0
        self.valence = {}
        self.alpha_min = 0.0
        self.r_node = 0.0
        self.plate_edge = 0.0
        self.plate_size = 0.0
        self.spacer_height = 0.0
        self.n_spacers = 0
        self.adj = []               # per node: [(neighbour, type_index, strut_index)]
        self.node_plate_names = []  # per node: (outer plate type, inner plate type)
        self.set_floor(-p.width / 2.0)

    def set_floor(self, z_floor):
        p = self.p
        self.z_floor = z_floor
        self.h_total = p.R - z_floor    # the recessed outer plate finishes at the node surface
        self.h_clear = p.R - p.frame_depth - p.plate - z_floor

    @property
    def name(self):
        base = "Dome D{:.0f} {}V".format(self.src.diameter, self.src.frequency)
        if self.shape == 'Walls':
            base += " walls {:.0f}".format(self.src.wall_height)
        elif self.shape == 'Arches':
            base += " arches"
        return base + (" model 1-{:g}".format(self.k) if self.model else "")

    @property
    def has_tubes(self):
        """A printed model gets its tubes between the plates as parts."""
        return self.model and self.p.center_hole > 0

    def fmt(self, v):
        """Lengths for the dialog: whole mm for the dome, 0.1 mm for a model."""
        return ("{:.1f}" if self.model else "{:.0f}").format(v)

    @property
    def n_nodes(self):
        return len(self.nodes)

    @property
    def n_base(self):
        return sum(1 for b in self.base if b)

    @property
    def n_struts(self):
        return len(self.struts)

    @property
    def n_boards(self):
        return self.n_struts * self.p.boards_per_strut

    @property
    def n_hubs(self):
        """Nodes with a hub (plates, bolt, tube); feet stand in platforms instead."""
        return self.n_nodes - len(self.feet)

    @property
    def n_plates(self):
        return 2 * self.n_hubs

    def longest_board(self):
        return max(self.types, key=lambda t: t.board_len) if self.types else None

    def segments(self):
        """Outer-node skeleton in mm: [(p1, p2, type_index)]."""
        return [(self.pos[a], self.pos[b], t) for a, b, t in self.struts]

    def inner(self, n):
        """Inner node point: the frame depth in along the hub axis."""
        return _sub(self.pos[n], _mul(self.axis[n], self.p.frame_depth))

    def tdir(self, n, m):
        """Unit direction from node n towards node m in the hub plane of n."""
        return _tangent_dir(self.pos[n], self.pos[m], self.axis[n])

    def strut_frame(self, a, b):
        """(ex, ey, ez): ex along the outer chord a->b, ey outwards in the strut
        plane (the plane of both hub axes), ez its normal."""
        ex = _unit(_sub(self.pos[b], self.pos[a]))
        s = _add(self.axis[a], self.axis[b])
        ey = _unit(_sub(s, _mul(ex, _dot(s, ex))))
        return ex, ey, _cross(ex, ey)

    def floor_outline(self, inner=False):
        """Base nodes (outer or inner points) dropped to the floor, by azimuth;
        for the arches the five feet (outer only)."""
        if self.feet:
            pts = [] if inner else [self.pos[f] for f in self.feet]
        else:
            pts = [self.inner(n) if inner else self.pos[n] for n in range(len(self.pos)) if self.base[n]]
        pts.sort(key=lambda q: math.atan2(q[1], q[0]))
        return [(q[0], q[1], self.z_floor) for q in pts]


def _validate(p):
    e = []
    if p.frequency not in FREQUENCIES:
        e.append("Frequency must be 2V, 4V or 6V.")
    if p.boards_per_strut not in (1, 2):
        e.append("Boards per strut must be 1 or 2.")
    for label, v in (("Diameter", p.diameter), ("Frame depth", p.frame_depth),
                     ("Plywood thickness", p.plywood), ("Plate thickness", p.plate),
                     ("Tenon length", p.tenon_len)):
        if v <= 0:
            e.append("{} must be greater than 0.".format(label))
    if p.frame_depth <= p.plate:
        e.append("Frame depth must be greater than plate thickness for a recessed hub.")
    if p.boards_per_strut == 2:
        if p.board_gap <= 0:
            e.append("Board gap must be greater than 0.")
        if p.spacer_max <= 0:
            e.append("Max spacer spacing must be greater than 0.")
    for label, v in (("Min web", p.min_web), ("Plate margin", p.plate_margin),
                     ("Clearance", p.clearance), ("Dogbone diameter", p.dogbone),
                     ("Center hole", p.center_hole), ("Spacer inset", p.spacer_inset),
                     ("Corner radius", p.corner_radius)):
        if v < 0:
            e.append("{} cannot be negative.".format(label))
    if p.plate_shape not in ("Hull", "Circle"):
        e.append("Plate shape must be Hull or Circle.")
    if p.base_shape not in BASE_SHAPES:
        e.append("Base shape must be Hemisphere, Walls or Arches.")
    elif p.base_shape == 'Walls':
        if p.wall_height <= p.width:
            e.append("Wall height must be more than the strut width ({:g} mm).".format(p.width))
        if int(p.wall_rows) != p.wall_rows or not 1 <= p.wall_rows <= MAX_WALL_ROWS:
            e.append("Wall rows must be 1 to {}.".format(MAX_WALL_ROWS))
    elif p.base_shape == 'Arches':
        if p.leg_length < 0 or 0 < p.leg_length < min_leg_length(p.R):
            e.append("Leg length must be 0 (auto) or at least {:.0f} mm.".format(math.ceil(min_leg_length(p.R))))
    for label, length, width, margin, gap in (
            ("Sheet", p.sheet_len, p.sheet_wid, p.sheet_margin, p.part_gap),
            ("Print bed", p.bed_len, p.bed_wid, p.bed_margin, p.bed_gap)):
        if label == "Print bed" and not p.is_model:
            continue
        if length <= 0 or width <= 0:
            e.append("{} size must be greater than 0.".format(label))
        elif margin < 0 or gap < 0:
            e.append("{} margin and spacing cannot be negative.".format(label))
        elif 2.0 * margin >= min(length, width):
            e.append("{} margin leaves no room on the {:g} x {:g} mm {}.".format(
                label, length, width, label.lower()))
    if p.model_scale < 1.0:
        e.append("Model scale must be 1 or more.")
    if p.is_model:
        for label, v in (("Print board thickness", p.print_plywood), ("Print plate thickness", p.print_plate),
                         ("Print bed length", p.bed_len), ("Print bed width", p.bed_wid)):
            if v <= 0:
                e.append("{} must be greater than 0.".format(label))
        for label, v in (("Print clearance", p.print_clearance), ("Print center hole", p.print_hole),
                         ("Print label height", p.print_label_height)):
            if v < 0:
                e.append("{} cannot be negative.".format(label))
        if p.print_labels:
            if p.print_label_depth <= 0:
                e.append("Print label depth must be greater than 0.")
            elif p.print_label_depth >= min(p.print_plywood, p.print_plate):
                e.append("Print label depth must be less than the board and plate thickness.")
    return e


def _azimuth(v):
    return math.degrees(math.atan2(v[1], v[0])) % 360.0


def _ang_diff(a, b):
    """a - b in degrees, wrapped to [-180, 180)."""
    return (a - b + 180.0) % 360.0 - 180.0


def cap_edge(R):
    """Arches: chord of an upper icosahedron edge - the cap edge one leg hangs under."""
    cos_angle = ICOSA_Z ** 2 + (1.0 - ICOSA_Z ** 2) * math.cos(math.radians(72.0))
    return R * math.sqrt(2.0 - 2.0 * cos_angle)


def auto_leg_length(R):
    """Arches: the auto long side of a leg (LEG_AUTO x the cap edge, as on the photo)."""
    return LEG_AUTO * cap_edge(R)


def _leg_reach(R):
    """Horizontal distance from a foot (on the circle of radius R, under the middle
    of a cap edge) to the hubs at the ends of that edge."""
    rho = R * math.sqrt(1.0 - ICOSA_Z ** 2)
    return math.sqrt(R * R + rho * rho - 2.0 * R * rho * math.cos(math.radians(36.0)))


def min_leg_length(R):
    """Shortest leg that still reaches clearly below the cap (foot 0.2 R under the hubs)."""
    return math.hypot(_leg_reach(R), 0.2 * R)


def _walls(d, units, pos, axis, base, struts):
    """Straight walls under the equator: a post under every equator node and a
    ring at each level. Wall hubs have horizontal axes, so posts and rings lie
    flat in their planes (diagonals would be skew - sheathing braces the wall)."""
    p = d.p
    eq = sorted((i for i, b in enumerate(base) if b), key=lambda i: _azimuth(units[i]))
    rows = int(p.wall_rows)
    z_ring = -(p.wall_height - p.width / 2.0)      # floor ring centre plane
    for i in eq:
        base[i] = False
    prev = eq
    for j in range(1, rows + 1):
        z = z_ring * j / rows
        cur = []
        for i in eq:
            u = units[i]
            pos.append((p.R * u[0], p.R * u[1], z))
            axis.append((u[0], u[1], 0.0))
            base.append(j == rows)
            cur.append(len(pos) - 1)
        struts += list(zip(prev, cur))
        struts += [(cur[m], cur[(m + 1) % len(cur)]) for m in range(len(cur))]
        prev = cur
    d.wall_posts = len(eq)
    d.set_floor(-p.wall_height)


def _arches(d, units, pos, axis, base, struts):
    """Arches on legs (like the Quadrome photo): the dome is the cap of the five
    upper icosahedron faces; under each cap edge stands a leg - one long triangle
    from a foot up to the two hubs at the ends of that edge, so neighbouring legs
    share a hub and each arch opening is just two long sides. The feet are not
    hubs: the long sides end square in the sockets of a foot platform."""
    p = d.p
    R = p.R
    up = sorted((i for i, u in enumerate(units) if abs(u[2] - ICOSA_Z) < 1e-9), key=lambda i: _azimuth(units[i]))
    normals = []
    for k in range(5):
        nk = _unit(_cross(units[up[k]], units[up[(k + 1) % 5]]))
        normals.append(nk if nk[2] > 0 else _mul(nk, -1.0))

    def inside(q):      # on the apex side of every cap edge (great circle), edges included
        return all(_dot(q, nk) > -1e-9 for nk in normals)
    keep = [i for i, u in enumerate(units) if inside(u)]
    new = {old: k for k, old in enumerate(keep)}
    pos[:] = [pos[i] for i in keep]
    axis[:] = [axis[i] for i in keep]
    base[:] = [False] * len(keep)
    struts[:] = [(new[a], new[b]) for a, b in struts
                 if a in new and b in new and inside(_add(units[a], units[b]))]
    hubs = [new[i] for i in up]
    L = auto_leg_length(R) if p.leg_length <= 0 else p.leg_length
    reach = _leg_reach(R)
    for k in range(5):
        a = math.radians(_azimuth(units[up[k]]) + 36.0)
        hz = pos[hubs[k]][2]
        foot = (R * math.cos(a), R * math.sin(a), hz - math.sqrt(max(L * L - reach * reach, 0.0)))
        pos.append(foot)
        axis.append(_unit(foot))          # radial like the hubs: each long side lies in one plane
        base.append(False)
        f = len(pos) - 1
        d.feet.append(f)
        struts += [(hubs[k], f), (hubs[(k + 1) % 5], f)]
    f = pos[d.feet[0]]
    d1, d2 = _unit(_sub(pos[hubs[0]], f)), _unit(_sub(pos[hubs[1]], f))
    d.foot_angle = math.acos(max(-1.0, min(1.0, _dot(d1, d2))))
    d.leg_len = L
    d.leg_drop = -f[2]
    d.set_floor(f[2])     # moved down to the platform base once the platform is known


def _structure(d):
    """Nodes (outer points, hub axes, floor flags) and struts of the base shape."""
    p = d.p
    units, struts, d.crossing = hemisphere(p.frequency)
    pos = [_mul(u, p.R) for u in units]
    axis = list(units)
    base = [abs(u[2]) < 1e-12 for u in units]
    struts = list(struts)
    if p.base_shape == 'Walls':
        _walls(d, units, pos, axis, base, struts)
    elif p.base_shape == 'Arches':
        _arches(d, units, pos, axis, base, struts)
    d.pos, d.axis, d.base = pos, axis, base
    d.nodes = [_unit(q) for q in pos]
    d.socket = [n in d.feet for n in range(len(pos))]
    return struts


def arch_top(d):
    """Arches: top of an opening (the shared hub) on the inner frame line, above the floor."""
    return (d.p.R - d.p.frame_depth) * ICOSA_Z - d.z_floor


def wall_area(d):
    """Walls: outer wall surface (mm2) from the floor to the top of the equator ring."""
    if d.shape != 'Walls' or not d.wall_posts:
        return 0.0
    n = d.wall_posts
    return n * 2.0 * d.p.R * math.sin(math.pi / n) * (-d.z_floor + d.p.width / 2.0)


_GRID_ALPHA = {}


def grid_alpha(freq):
    """Sharpest angle (rad) between neighbouring struts of the plain hemisphere grid."""
    if freq not in _GRID_ALPHA:
        units, struts, _c = hemisphere(freq)
        nb = [[] for _ in units]
        for a, b in struts:
            nb[a].append(b)
            nb[b].append(a)
        best = math.pi
        for n, ms in enumerate(nb):
            u = units[n]
            ref = _ref_dir(u, abs(u[2]) < 1e-12)
            side = _cross(u, ref)
            angs = sorted(math.degrees(math.atan2(_dot(v, side), _dot(v, ref))) % 360.0
                          for v in (_tangent_dir(u, units[m]) for m in ms))
            best = min([best] + [math.radians(g) for g, _ in _gaps([(x, '') for x in angs])])
        _GRID_ALPHA[freq] = best
    return _GRID_ALPHA[freq]


def _strut_key(d, a, b):
    """Board shape of strut a-b: (chord, tilt at a, tilt at b, coplanarity error)."""
    ex, ey, ez = d.strut_frame(a, b)
    A, B = d.axis[a], d.axis[b]
    phi_a = math.atan2(-_dot(A, ex), _dot(A, ey))
    phi_b = math.atan2(_dot(B, ex), _dot(B, ey))
    skew = max(abs(_dot(A, ez)), abs(_dot(B, ez)))
    return _len(_sub(d.pos[b], d.pos[a])), phi_a, phi_b, skew


def analyze(src):
    d = Dome(src)
    d.errors = _validate(src)
    p = d.p
    if not d.errors and p.frame_depth + p.plate >= p.R:
        d.errors.append("Frame depth + plate thickness must be less than the radius.")
    if d.errors:
        return d
    R, h, w = p.R, p.frame_depth, p.width
    c, o = p.clearance, p.dogbone_overcut
    struts = _structure(d)
    nodes = d.nodes

    # strut types: cluster by board shape (chord and the hub axis tilt at each
    # end); the dome's own struts first by increasing length, then walls / legs
    on_sphere = [abs(_len(q) - R) < 1e-6 * R and _len(_sub(_mul(ax, R), q)) < 1e-6 * R
                 for q, ax in zip(d.pos, d.axis)]
    clusters = []    # [L, phi_p, phi_q, sphere, [(strut index, swapped)], socket at Q]
    for si, (a, b) in enumerate(struts):
        L, pa, pb, skew = _strut_key(d, a, b)
        if skew > 1e-7:
            raise ValueError("strut {}-{}: hub axes not in one plane ({:.2e})".format(a, b, skew))
        sock = d.socket[a] or d.socket[b]
        if sock:     # a leg's long side: the hub end is P, the foot (socket) end is Q
            swapped = d.socket[a]
            lo, hi = (pb, 0.0) if swapped else (pa, 0.0)
        else:
            swapped = pa > pb + 1e-9
            lo, hi = (pb, pa) if swapped else (pa, pb)
        for cl in clusters:
            if (cl[5] == sock and abs(cl[0] - L) < 1e-7 * R and abs(cl[1] - lo) < 1e-7
                    and abs(cl[2] - hi) < 1e-7):
                cl[4].append((si, swapped))
                cl[3] = cl[3] or (on_sphere[a] and on_sphere[b])
                break
        else:
            clusters.append([L, lo, hi, on_sphere[a] and on_sphere[b], [(si, swapped)], sock])
    clusters.sort(key=lambda cl: (not cl[3], cl[5], cl[0], cl[1], cl[2]))
    type_of = {}
    for ti, cl in enumerate(clusters):
        for si, swapped in cl[4]:
            type_of[si] = (ti, swapped)
    d.struts = []
    for si, (a, b) in enumerate(struts):
        ti, swapped = type_of[si]
        d.struts.append((b, a, ti) if swapped else (a, b, ti))

    # hub patterns, valence, sharpest angle
    adj = [[] for _ in nodes]
    for si, (a, b, t) in enumerate(d.struts):
        adj[a].append((b, t, si))
        adj[b].append((a, t, si))
    d.adj = adj
    alpha_min = math.pi
    patterns = []
    for n, nb in enumerate(adj):
        if d.socket[n]:          # a foot: no plates, the platform takes the long sides
            patterns.append(None)
            continue
        ax = d.axis[n]
        ref = _ref_dir(ax, d.base[n])
        side = _cross(ax, ref)
        items = []
        for m, t, _si in nb:
            v = d.tdir(n, m)
            items.append((math.degrees(math.atan2(_dot(v, side), _dot(v, ref))) % 360.0, LETTERS[t]))
        items.sort()
        for g, _ in _gaps(items):
            alpha_min = min(alpha_min, math.radians(g))
        patterns.append(items)
        d.valence[len(nb)] = d.valence.get(len(nb), 0) + 1
    d.alpha_min = alpha_min

    # hub radius r: one for the whole dome (spec, decision 5)
    a_half = w / 2.0 + c + o
    half = alpha_min / 2.0
    r = a_half / math.tan(half) + (p.min_web / 2.0) / math.sin(half) + c + o
    if p.center_hole > 0:
        r = max(r, p.center_hole / 2.0 + p.min_web + c + o)
    d.r_node = round(math.ceil(r / d.r_step - 1e-9) * d.r_step, 6)
    if p.boards_per_strut == 2:
        web = p.board_gap - 2.0 * (c + o)
        if web < p.min_web:
            d.errors.append("Board gap too small: web between twin slots {:.1f} mm < min web {:.1f} mm."
                            .format(web, p.min_web))

    # plate edge along the board (from the hub axis) and plate size
    far = d.r_node + p.tenon_len + c + o
    if p.plate_shape == "Circle":
        radius = math.hypot(far, a_half) + p.plate_margin
        dmax = max(abs(x) for x in p.board_offsets())
        d.plate_edge = math.sqrt(max(radius ** 2 - dmax ** 2, 0.0))
        d.plate_size = 2.0 * radius
    else:
        d.plate_edge = far + p.plate_margin
        d.plate_size = 2.0 * math.hypot(d.plate_edge, a_half + p.plate_margin)

    # The outer surface of each board reaches the outer plate's new, flush face.
    # At each hub, a full-depth shoulder relief clears the recessed plate until
    # just past its footprint (x1). The inner edge remains unchanged.
    x1 = d.plate_edge + d.transition
    for ti, (L, phi_p, phi_q, sphere, members, sock) in enumerate(clusters):
        kind = 'dome' if sphere else ('leg' if d.shape == 'Arches' else 'wall')
        t = StrutType(LETTERS[ti], L / R, len(members), phi_p, L, phi_q=phi_q, kind=kind, socket=sock)
        _shape_type(d, t, x1, d.struts[members[0][0]] if sock else None)
        d.types.append(t)
    if d.feet:
        d.platform = platform_geometry(d)
        d.set_floor(d.platform['z_floor'])

    # one spacer for the whole dome: height by the narrowest board
    if p.boards_per_strut == 2:
        gaps = []
        for t in d.types:   # a sloped (leg) board counts where its spacers actually sit
            if t.symmetric or t.socket:
                gaps.append(t.yo(0.0) - t.yi(0.0))
            elif t.spacers_each:
                span = t.middle_len / (t.spacers_each + 1)
                gaps += [t.yo(t.x_lo + i * span) - t.yi(t.x_lo + i * span) for i in range(1, t.spacers_each + 1)]
        b_min = min(gaps)
        d.spacer_height = b_min - 2.0 * p.spacer_inset
        if d.spacer_height - 2.0 * d.shoulder <= 0:
            d.errors.append("Spacer too low: frame depth minus insets leaves no room for its tenons.")
        d.n_spacers = sum(t.count * t.spacers_each for t in d.types)

    # plate types: outer plate = pattern seen from outside, inner = its mirror
    found = []   # [base, valence, pattern, qty]

    def add(base, valence, pat):
        for i, t in enumerate(found):
            if t[0] == base and t[1] == valence and _pattern_match(base, t[2], pat):
                t[3] += 1
                return i
        found.append([base, valence, pat, 1])
        return len(found) - 1

    node_types = []
    for n, items in enumerate(patterns):
        if items is None:
            node_types.append(None)
            continue
        base = d.base[n]
        pat = list(items) if base else _gaps(items)
        node_types.append((add(base, len(items), pat), add(base, len(items), _mirror(base, pat))))
    names = {}
    for key in sorted(set((t[0], t[1]) for t in found)):
        members = [i for i, t in enumerate(found) if (t[0], t[1]) == key]
        members.sort(key=lambda i: -found[i][3])
        k = 0
        for i in members:
            if i in names:
                continue
            nm = "H{}{}".format(found[i][1], "abcdefghijklmnopqrstuvwxyz"[k])
            k += 1
            names[i] = nm
            mp = _mirror(found[i][0], found[i][2])
            for j in members:
                if j != i and j not in names and _pattern_match(found[j][0], found[j][2], mp):
                    names[j] = nm + "m"
                    break
    d.plate_types = [PlateType(names[i], t[1], t[0], t[3]) for i, t in enumerate(found)]
    d.plate_types.sort(key=lambda t: (t.base, t.valence, t.name))
    d.plate_codes = {t.name: str(i + 1) for i, t in enumerate(d.plate_types)}
    d.node_plate_names = [(names[nt[0]], names[nt[1]]) if nt else ('', '') for nt in node_types]

    # checks; a model is checked against the print bed, a board may lie either way on it
    where = "the print bed" if d.model else "the sheet"
    L_max, W_max = p.sheet_len - 2 * d.margin, p.sheet_wid - 2 * d.margin

    def fits(a, b):
        return (a <= L_max and b <= W_max) or (d.model and a <= W_max and b <= L_max)
    for t in d.types:
        if t.middle_len < 0:
            d.errors.append("Strut {}: hub zones overlap - strut too short for these plates.".format(t.letter))
        elif p.boards_per_strut == 2 and t.middle_len < d.min_spacer_zone:
            d.warnings.append("Strut {}: middle part {} mm - no room for a spacer.".format(t.letter, d.fmt(t.middle_len)))
        if not fits(t.board_len, t.board_wid):
            d.warnings.append("Board {} ({} x {} mm) does not fit {}."
                              .format(t.letter, d.fmt(t.board_len), d.fmt(t.board_wid), where))
    if d.plate_size > min(L_max, W_max):
        d.warnings.append("Hub plate ({} mm) is larger than {}.".format(d.fmt(d.plate_size), where))
    ga = grid_alpha(p.frequency) / 2.0
    r_grid = a_half / math.tan(ga) + (p.min_web / 2.0) / math.sin(ga) + c + o
    if d.shape == 'Arches' and d.r_node > 1.05 * r_grid:
        d.warnings.append("These legs make the sharpest angle {:.1f}&deg; (the dome alone {:.1f}&deg;), so every hub "
                          "grows to r {} mm. Leg length 0 (auto, {} mm) keeps the hubs small.".format(
                              math.degrees(d.alpha_min), math.degrees(grid_alpha(p.frequency)), d.fmt(d.r_node),
                              d.fmt(auto_leg_length(R))))
    if d.platform and d.model:
        size = d.platform['size']
        if not fits(max(size[0], size[1]), min(size[0], size[1])) or (d.model and size[2] > 250.0):
            d.warnings.append("Foot platform ({} x {} x {} mm) does not fit {}.".format(
                d.fmt(size[0]), d.fmt(size[1]), d.fmt(size[2]), where))
    return d


# ------------------------------------------------------------------- summary
def summary_html(d, lang='en'):
    """Text for the Results box of the dialog (basic HTML), English or Russian."""
    p = d.p
    ru = lang == 'ru'

    def T(en, rus):
        return rus if ru else en
    out = []
    if d.errors:
        out.append(T("<b>Errors - fix before building</b>", "<b>Ошибки — исправь перед построением</b>"))
        out += ["&bull; " + translate(e, lang) for e in d.errors]
        if not d.types:
            return "<br/>".join(out)
        out.append("")
    f = d.fmt
    if d.model:
        out.append(T("<b>Model 1:{:g}</b> - every size below is the model, mm",
                     "<b>Модель 1:{:g}</b> — все размеры ниже модельные, мм").format(d.k))
        out.append(T("Real dome D {:.0f} mm, model D {} mm", "Настоящий купол D {:.0f} мм, модель D {} мм")
                   .format(d.src.diameter, f(p.diameter)))
    out.append(T("<b>Size</b>", "<b>Размеры</b>"))
    if d.shape == 'Walls':
        rows = int(p.wall_rows)
        out.append(T("On straight walls: {} mm, {} posts x {} {}", "На прямых стенах: {} мм, {} стоек × {} {}").format(
            f(p.wall_height), d.wall_posts, rows,
            T("row" if rows == 1 else "rows", "ярус" if rows == 1 else "яруса")))
    elif d.shape == 'Arches':
        auto = (T(" (auto)", " (авто)") if p.leg_length <= 0 else
                T(", auto would be {} mm", ", авто было бы {} мм").format(f(auto_leg_length(p.R))))
        out.append(T("Arches on legs: 5 legs, long side {} mm{}", "Арки на ногах: 5 ног, длинная сторона {} мм{}")
                   .format(f(d.leg_len), auto))
    out.append(T("R {} mm, inner R {} mm", "R {} мм, внутренний R {} мм").format(f(p.R), f(p.R - p.frame_depth)))
    out.append(T("Height {} mm, clear inside {} mm", "Высота {} мм, внутри в свету {} мм")
               .format(f(d.h_total), f(d.h_clear)))
    out.append(T("Floor {} mm below the equator", "Пол на {} мм ниже экватора").format(f(-d.z_floor)))
    if d.shape == 'Arches' and d.feet:
        a, b = d.pos[d.feet[0]], d.pos[d.feet[1]]
        out.append(T("5 arch openings: feet {} mm apart, arch top about {} mm above the floor (inner frame)",
                     "5 арок-проходов: пятки в {} мм друг от друга, верх арки около {} мм от пола "
                     "(по внутреннему каркасу)").format(f(_len(_sub(a, b))), f(arch_top(d))))
        if d.platform:
            sz = d.platform['size']
            out.append(T("Foot platform {} x {} x {} mm, sockets {} mm deep{}",
                         "Платформа ноги {} × {} × {} мм, гнёзда глубиной {} мм{}").format(
                f(sz[0]), f(sz[1]), f(sz[2]), f(max(t.depth for t in d.types if t.socket)),
                T(" - printed", " — печатается") if d.model else
                T(" - weld in steel to this shape", " — сварить из стали по этой форме")))
    if d.shape == 'Walls':
        out.append(T("Wall frames are posts and rings: brace them with sheathing (OSB / plywood), about {:.1f} m&sup2;",
                     "Стены — стойки и кольца: жёсткость даёт обшивка (OSB / фанера), около {:.1f} м&sup2;")
                   .format(wall_area(d) / 1e6))
    out.append(T("<b>Counts</b>", "<b>Количество</b>"))
    if d.feet:
        out.append(T("Nodes {} ({} hubs, {} feet), struts {}", "Узлов {} ({} хабов, {} пяток), рёбер {}")
                   .format(d.n_nodes, d.n_hubs, len(d.feet), d.n_struts))
    else:
        out.append(T("Nodes {} (base {}), struts {}", "Узлов {} (в основании {}), рёбер {}")
                   .format(d.n_nodes, d.n_base, d.n_struts))
    parts = T("Boards {}, plates {}", "Досок {}, пластин {}").format(d.n_boards, d.n_plates)
    if p.boards_per_strut == 2:
        parts += T(", spacers {}", ", проставок {}").format(d.n_spacers)
    parts += T(", bolt sets {}", ", комплектов болтов {}").format(d.n_hubs) if p.center_hole > 0 else ""
    parts += T(", foot platforms {}", ", платформ {}").format(len(d.feet)) if d.feet else ""
    out.append(parts + (T(", tubes {}", ", втулок {}").format(d.n_hubs) if d.has_tubes else ""))
    out.append(T("<b>Struts</b> - chord, board L x W, boards", "<b>Рёбра</b> — хорда, доска Д × Ш, досок"))
    for t in d.types:
        out.append("{} {:.5f} - {} mm - {} x {} - x{}".format(
            t.letter, t.factor, f(t.chord_out), f(t.board_len), f(t.board_wid), t.count * p.boards_per_strut)
            .replace(" mm", T(" mm", " мм")))
    out.append(T("<b>Hubs</b>", "<b>Узлы</b>"))
    out.append(T("Hub radius r {} mm, sharpest angle {:.1f}&deg;", "Радиус узла r {} мм, самый острый угол {:.1f}&deg;")
               .format(f(d.r_node), math.degrees(d.alpha_min)))
    out.append(T("Plate size about {} mm", "Пластина около {} мм").format(f(d.plate_size)))
    if d.model and p.labels:
        out.append(T("Plate types {} - the digit on the model: {}", "Типов пластин {} — на модели цифрой: {}").format(
            len(d.plate_types), ", ".join("{} = {} x{}".format(d.plate_codes[t.name], t.name, t.qty)
                                         for t in d.plate_types)))
    else:
        out.append(T("Plate types {}: {}", "Типов пластин {}: {}").format(
            len(d.plate_types), ", ".join("{} x{}".format(t.name, t.qty) for t in d.plate_types)))
    if p.boards_per_strut == 2:
        out.append(T("Spacer {} mm high (one type)", "Проставка высотой {} мм (один тип)").format(f(d.spacer_height)))
    lb = d.longest_board()
    if lb:
        where = T("bed", "стол") if d.model else T("sheet", "лист")
        out.append(T("Longest board {} {} mm, {} {:.0f} x {:.0f} mm", "Самая длинная доска {} {} мм, {} {:.0f} × {:.0f} мм")
                   .format(lb.letter, f(lb.board_len), where, p.sheet_len, p.sheet_wid))
    if not d.errors:
        try:
            rows = bom(d)
            if d.model:
                out.append(T("PLA about {:.0f} g (solid parts)", "PLA около {:.0f} г (сплошные детали)")
                           .format(frame_weight(rows, d.density) * 1000.0))
            else:
                out.append(T("Plywood {:.1f} m&sup2;, frame about {:.0f} kg", "Фанера {:.1f} м&sup2;, каркас около {:.0f} кг")
                           .format(plywood_area(rows), frame_weight(rows)))
        except Exception:
            pass
    if d.warnings:
        out.append(T("<b>Warnings</b>", "<b>Предупреждения</b>"))
        out += ["&bull; " + translate(w, lang) for w in d.warnings]
    return "<br/>".join(out)


# Russian for the messages above: English pattern -> Russian template ({0}, {1}... are the groups)
_RU_NAMES = {
    "Diameter": "Диаметр", "Frame depth": "Глубина каркаса", "Plywood thickness": "Толщина фанеры",
    "Plate thickness": "Толщина пластины", "Tenon length": "Длина шипа", "Board gap": "Зазор между досками",
    "Max spacer spacing": "Шаг проставок", "Min web": "Перемычка", "Plate margin": "Поле пластины",
    "Clearance": "Зазор", "Dogbone diameter": "Диаметр dogbone", "Center hole": "Отверстие",
    "Spacer inset": "Отступ проставки", "Corner radius": "Скругление",
    "Print board thickness": "Толщина досок модели", "Print plate thickness": "Толщина пластин модели",
    "Print bed length": "Стол X", "Print bed width": "Стол Y", "Print clearance": "Зазор модели",
    "Print center hole": "Отверстие модели", "Print label height": "Высота букв модели",
    "Print label depth": "Глубина букв модели",
    "Sheet": "Лист", "Print bed": "Стол принтера", "sheet": "листе", "print bed": "столе",
    "the sheet": "лист", "the print bed": "стол принтера",
}
_RU_PATTERNS = [
    (r"Frequency must be 2V, 4V or 6V\.", "Частота должна быть 2V, 4V или 6V."),
    (r"Boards per strut must be 1 or 2\.", "Досок в ребре — 1 или 2."),
    (r"Print label depth must be less than the board and plate thickness\.",
     "Глубина букв модели должна быть меньше толщины досок и пластин."),
    (r"(.+) must be greater than 0\.", "{0}: должно быть больше 0."),
    (r"(.+) cannot be negative\.", "{0}: не может быть отрицательным."),
    (r"Plate shape must be Hull or Circle\.", "Форма пластины — Многоугольник или Круг."),
    (r"Base shape must be Hemisphere, Walls or Arches\.", "Основание — Полусфера, На стенах или Арки на ногах."),
    (r"Wall height must be more than the strut width \((.+) mm\)\.",
     "Высота стен должна быть больше ширины ребра ({0} мм)."),
    (r"Wall rows must be 1 to (\d+)\.", "Ярусов стен — от 1 до {0}."),
    (r"Leg length must be 0 \(auto\) or at least (.+) mm\.", "Длина ноги — 0 (авто) или не меньше {0} мм."),
    (r"(Sheet|Print bed) size must be greater than 0\.", "{0}: размер должен быть больше 0."),
    (r"(Sheet|Print bed) margin and spacing cannot be negative\.",
     "{0}: отступ и расстояние не могут быть отрицательными."),
    (r"(Sheet|Print bed) margin leaves no room on the (.+) x (.+) mm (sheet|print bed)\.",
     "{0}: при таком отступе на {1} × {2} мм не остаётся места."),
    (r"Model scale must be 1 or more\.", "Масштаб — 1 или больше."),
    (r"Frame depth \+ plate thickness must be less than the radius\.",
     "Глубина каркаса + толщина пластины должны быть меньше радиуса."),
    (r"Frame depth must be greater than plate thickness for a recessed hub\.",
     "Глубина каркаса должна быть больше толщины пластины для утопленного узла."),
    (r"Board gap too small: web between twin slots (.+) mm < min web (.+) mm\.",
     "Зазор между досками мал: перемычка между пазами {0} мм < {1} мм."),
    (r"Spacer too low: frame depth minus insets leaves no room for its tenons\.",
     "Проставка слишком низкая: глубина каркаса минус отступы не оставляет места шипам."),
    (r"Strut (\w+): hub zones overlap - strut too short for these plates\.",
     "Ребро {0}: зоны узлов перекрываются — ребро слишком короткое для этих пластин."),
    (r"Strut (\w+): middle part (.+) mm - no room for a spacer\.",
     "Ребро {0}: средняя часть {1} мм — проставке нет места."),
    (r"Board (\w+) \((.+) x (.+) mm\) does not fit (the sheet|the print bed)\.",
     "Доска {0} ({1} × {2} мм) не помещается на {3}."),
    (r"Hub plate \((.+) mm\) is larger than (the sheet|the print bed)\.",
     "Пластина узла ({0} мм) больше, чем {1}."),
    (r"These legs make the sharpest angle (.+)&deg; \(the dome alone (.+)&deg;\), so every hub grows to r (.+) mm\. "
     r"Leg length 0 \(auto, (.+) mm\) keeps the hubs small\.",
     "С такими ногами самый острый угол {0}&deg; (у купола без ног {1}&deg;), поэтому все узлы вырастают до "
     "r {2} мм. Длина ноги 0 (авто, {3} мм) оставляет узлы маленькими."),
    (r"Foot platform \((.+) x (.+) x (.+) mm\) does not fit (the sheet|the print bed)\.",
     "Платформа ноги ({0} × {1} × {2} мм) не помещается на {3}."),
]


def translate(msg, lang='en'):
    """An error or warning of the core in the dialog language (English as is)."""
    if lang != 'ru':
        return msg
    for pattern, template in _RU_PATTERNS:
        m = re.fullmatch(pattern, msg)
        if m:
            return template.format(*(_RU_NAMES.get(g, g) for g in m.groups()))
    return msg


# ------------------------------------------------------------ part geometry
# 2D loops are lists of ('L', p0, p1) lines, ('A', p0, pm, p1) arcs through
# three points and ('C', centre, radius) circles. Points (x, y) in mm.
SQRT2 = math.sqrt(2.0)
STUB_SPACER = 60.0    # test hub: spacer this far into the middle zone
STUB_MIDDLE = 120.0   # test hub: stub cut this far into the middle zone


def _u2(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n)


def _v2(a, b, s=1.0):
    return (a[0] + s * b[0], a[1] + s * b[1])


def _far(a, b, tol=1e-6):
    return math.hypot(a[0] - b[0], a[1] - b[1]) > tol


def polygon_loop(pts, dogs, rho):
    """Closed polygon. Corners flagged in dogs get a dogbone: a semicircle of
    radius rho through the corner, from sqrt2*rho before it to sqrt2*rho after."""
    n = len(pts)
    entry, exit_, arcs = [], [], []
    for i in range(n):
        V = pts[i]
        if dogs[i] and rho > 0:
            din = _u2((V[0] - pts[i - 1][0], V[1] - pts[i - 1][1]))
            dout = _u2((pts[(i + 1) % n][0] - V[0], pts[(i + 1) % n][1] - V[1]))
            p1, p2 = _v2(V, din, -SQRT2 * rho), _v2(V, dout, SQRT2 * rho)
            entry.append(p1)
            exit_.append(p2)
            arcs.append((p1, V, p2))
        else:
            entry.append(V)
            exit_.append(V)
            arcs.append(None)
    loop = []
    for i in range(n):
        if arcs[i]:
            loop.append(('A',) + arcs[i])
        nxt = entry[(i + 1) % n]
        if _far(exit_[i], nxt):
            loop.append(('L', exit_[i], nxt))
    return loop


def _rect(center, axis, hl, hw):
    pe = (-axis[1], axis[0])
    return [(center[0] + sx * hl * axis[0] + sy * hw * pe[0],
             center[1] + sx * hl * axis[1] + sy * hw * pe[1])
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def _convex_hull(points):
    pts = sorted(set((round(x, 9), round(y, 9)) for x, y in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 1e-9:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 1e-9:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def _offset_convex(poly, dist):
    """Mitered outward offset of a CCW convex polygon."""
    n = len(poly)
    lines = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = _u2((b[0] - a[0], b[1] - a[1]))
        lines.append(((a[0] + dy * dist, a[1] - dx * dist), (dx, dy)))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-12:
            out.append(p2)
            continue
        s = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        out.append((p1[0] + d1[0] * s, p1[1] + d1[1] * s))
    return out


def _rounded_polygon(poly, radius):
    """CCW convex polygon with every corner filleted (radius shrinks on short edges)."""
    n = len(poly)
    corners = []
    for i in range(n):
        A, V, B = poly[i - 1], poly[i], poly[(i + 1) % n]
        la, lb = math.hypot(A[0] - V[0], A[1] - V[1]), math.hypot(B[0] - V[0], B[1] - V[1])
        u1 = ((A[0] - V[0]) / la, (A[1] - V[1]) / la)
        u2 = ((B[0] - V[0]) / lb, (B[1] - V[1]) / lb)
        beta = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
        if radius <= 0 or beta > math.pi - 1e-6:
            corners.append((V, V, None))
            continue
        dt, rr = radius / math.tan(beta / 2.0), radius
        lim = 0.5 * min(la, lb)
        if dt > lim:
            dt, rr = lim, lim * math.tan(beta / 2.0)
        bis = _u2((u1[0] + u2[0], u1[1] + u2[1]))
        C = _v2(V, bis, rr / math.sin(beta / 2.0))
        corners.append((_v2(V, u1, dt), _v2(V, u2, dt), _v2(C, bis, -rr)))
    loop = []
    for i in range(n):
        t1, t2, mid = corners[i]
        if mid is not None:
            loop.append(('A', t1, mid, t2))
        nxt = corners[(i + 1) % n][0]
        if _far(t2, nxt):
            loop.append(('L', t2, nxt))
    return loop


def loops_closed(loops, tol=1e-6):
    for loop in loops:
        if loop and loop[0][0] == 'C':
            continue
        for i, el in enumerate(loop):
            if _far(el[-1], loop[(i + 1) % len(loop)][1], tol):
                return False
    return True


def _end_at(t, end):
    """Board coordinates of one end's hub frame: at(tau, mu) with tau along the
    hub axis from the outer node (out > 0) and mu across it towards the strut.
    end 0 = P (x < 0, tilt half_angle), end 1 = Q (x > 0, tilt phi_q)."""
    L = t.chord_out
    if end == 0:
        s, c = math.sin(t.half_angle), math.cos(t.half_angle)
        return lambda tau, mu: (-L / 2.0 - tau * s + mu * c, tau * c + mu * s)
    s, c = math.sin(t.phi_q), math.cos(t.phi_q)
    return lambda tau, mu: (L / 2.0 + tau * s - mu * c, tau * c + mu * s)


def _line(p0, p1):
    """Line through two points as (y at x = 0, slope)."""
    k = (p1[1] - p0[1]) / (p1[0] - p0[0])
    return p0[1] - k * p0[0], k


def _bridge(left, right, below):
    """The tight straight edge from the left points to the right points: a line
    through one point of each side with every point on its outer side (below=True:
    all points on or above the line, i.e. the edge passes under them)."""
    best = None
    for p0 in left:
        for p1 in right:
            y0, k = _line(p0, p1)
            dev = [q[1] - (y0 + k * q[0]) for q in left + right]
            bad = -min(dev) if below else max(dev)
            if best is None or bad < best[0] - 1e-12:
                best = (bad, y0, k)
    return best[1], best[2]


def _end_points(d, t, end):
    """Key points of one board end in board coordinates: x along the outer chord
    from its midpoint, y outwards, outer chord at y = 0.
    A = outer: tenon end and tip, recessed root and pocket floor, pocket exit
    at the outer board edge. The plate now occupies tau = [-tp, 0], so its
    outside face is flush with the board's edge at the pocket exit.
    B = inner: unchanged tenon end, tip, and inner-edge corner."""
    p = d.p
    tp, r, h = p.plate, d.r_node, p.frame_depth
    mu = r + p.tenon_len
    pocket_end = d.plate_edge + d.transition
    at = _end_at(t, end)
    s, c = (math.sin(t.half_angle), math.cos(t.half_angle)) if end == 0 else (math.sin(t.phi_q), math.cos(t.phi_q))
    half = t.chord_out / 2.0 if end == 1 else -t.chord_out / 2.0
    sg = 1.0 if end == 1 else -1.0

    def tau_on(y0, k, radial):  # where a constant-mu line meets y = y0 + k*x
        return (y0 + k * (half - sg * radial * c) - radial * s) / (c - sg * k * s)
    A = [at(0.0, r), at(0.0, mu), at(-tp, mu), at(-tp, pocket_end),
         at(tau_on(t.y_out, t.k_out, pocket_end), pocket_end)]
    B = [at(-h - tp, r), at(-h - tp, mu), at(tau_on(t.y_in, t.k_in, mu), mu)]
    return A, B, at


def _board_points(d, ti):
    """The P end (x < 0) of strut type ti: (A, B, at), see _end_points."""
    return _end_points(d, d.types[ti], 0)


def _shape_type(d, t, x1, strut=None):
    """Edges, middle zone, size and spacers of a strut type's straight board.
    The outer edge joins the two pocket exits beyond the recessed outer plates;
    the inner edge joins the points just past the inner plates (x1 from the hub
    axis), so it clears both plates.
    A leg's long side (socket type) is a bar parallel to its chord: tenons at the
    hub, a square end in the foot platform socket (strut = one such strut)."""
    p = d.p
    mu, h = d.r_node + p.tenon_len, p.frame_depth
    at_p, at_q = _end_at(t, 0), _end_at(t, 1)
    if t.socket:
        _socket_type(d, t, x1, strut)
        return
    # Outside the recessed shoulders, the straight outer edge meets the face
    # of each outer plate at tau=0, immediately beyond its footprint (x1).
    # The relief between mu and x1 is generated by _end_points.
    t.y_out, t.k_out = _line(at_p(0.0, x1), at_q(0.0, x1))
    t.y_in, t.k_in = _bridge([at_p(-h, x1), at_p(-h, mu)], [at_q(-h, x1), at_q(-h, mu)], False)
    t.x_lo = max(at_p(-h, x1)[0], at_p(0.0, x1)[0])
    t.x_hi = min(at_q(-h, x1)[0], at_q(0.0, x1)[0])
    t.middle_len = t.x_hi - t.x_lo
    pts = []
    for end in (0, 1):
        A, B, _at = _end_points(d, t, end)
        pts += A + B
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    t.board_len, t.board_wid = max(xs) - min(xs), max(ys) - min(ys)
    t.spacers_each = 0
    if p.boards_per_strut == 2 and t.middle_len >= d.min_spacer_zone:
        t.spacers_each = max(1, int(math.ceil(t.middle_len / p.spacer_max - 1e-9)) - 1)


def _socket_type(d, t, x1, strut):
    """Long side of a leg: the edges run parallel to the chord (constant section
    for the socket), the end face sits in the socket at distance s0 from the foot
    point, chosen so the two sockets of a foot keep a wall between them."""
    p = d.p
    mu, h, c, wall = d.r_node + p.tenon_len, p.frame_depth, p.clearance, p.plate
    at_p = _end_at(t, 0)
    t.y_out, t.k_out = at_p(0.0, x1)[1], 0.0
    t.y_in, t.k_in = max(at_p(-h, x1)[1], at_p(-h, mu)[1]), 0.0
    a, b, _ti = strut
    ex, ey, ez = d.strut_frame(a, b)
    foot = d.pos[b]
    up_leg = _mul(ex, -1.0)                                   # from the foot up the long side
    n_sym = _cross((0.0, 0.0, 1.0), _unit((foot[0], foot[1], 0.0)))   # the leg's mirror plane normal
    if _dot(up_leg, n_sym) < 0:
        n_sym = _mul(n_sym, -1.0)
    hw = p.width / 2.0 + c
    s0 = 0.0
    for y in (t.y_in - c, t.y_out + c):
        for z in (-hw, hw):
            s0 = max(s0, (wall / 2.0 - y * _dot(ey, n_sym) - z * _dot(ez, n_sym)) / _dot(up_leg, n_sym))
    width = t.y_out - t.y_in
    t.x_cut = t.chord_out / 2.0 - s0
    t.depth = SOCKET_DEPTH * width
    t.x_pin = t.x_cut - t.depth / 2.0
    t.x_lo = max(at_p(-h, x1)[0], at_p(0.0, x1)[0])
    t.x_hi = t.x_cut - t.depth - p.spacer_inset
    t.middle_len = t.x_hi - t.x_lo
    A, B, _at = _end_points(d, t, 0)
    pts = A + B + [(t.x_cut, t.y_out), (t.x_cut, t.y_in)]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    t.board_len, t.board_wid = max(xs) - min(xs), max(ys) - min(ys)
    t.spacers_each = 0
    if p.boards_per_strut == 2 and t.middle_len >= d.min_spacer_zone:
        t.spacers_each = max(1, int(math.ceil(t.middle_len / p.spacer_max - 1e-9)) - 1)


def _label_x(text, h, xs, half_slot, lo, hi, centre=0.0, wf=0.65, strict=False):
    """Board label position along x: as near the middle (centre) as it fits
    between lo and hi, clear of the spacer slots at xs. wf: letter width / height
    (a model's bold capitals are about as wide as tall)."""
    w = wf * h * len(text)
    clear = half_slot + 0.2 * h + w / 2.0
    cands = sorted([centre] + [x + sg * clear for x in xs for sg in (-1.0, 1.0)],
                   key=lambda x: round(abs(x - centre), 6))
    for cx in cands:
        if lo + w / 2.0 <= cx <= hi - w / 2.0 and all(abs(cx - x) >= clear - 1e-9 for x in xs):
            return cx
    return None if strict else centre


def _model_board_label(letter, h, xs, half_slot, lo, hi, centre):
    """A model board's bold letter: (x, height), the biggest size down to half of h
    that fits clear of the spacer slots; failing that, in the middle of the longest
    free stretch, as big as that stretch takes (0 when there is no room at all)."""
    for k in range(11):
        hh = h * (1.0 - 0.05 * k)
        x = _label_x(letter, hh, xs, half_slot, lo, hi, centre, 1.1, strict=True)
        if x is not None:
            return x, hh
    cuts = sorted(xs)
    stretches = list(zip([lo] + [x + half_slot for x in cuts], [x - half_slot for x in cuts] + [hi]))
    a, b = max(stretches, key=lambda ab: ab[1] - ab[0])
    hh = min(0.5 * h, (b - a - 0.6) / 1.1)
    return (a + b) / 2.0, (hh if hh >= 2.0 else 0.0)


def board_geometry(d, ti, stub=False):
    """Straight board of strut type ti: tenons at both ends with dogbone reliefs
    in the inner corners, spacer slots, the type letter in the middle.
    stub=True gives the test-hub piece: the P end cut d.stub_middle past the plate."""
    p = d.p
    t = d.types[ti]
    A, B, _at = _end_points(d, t, 0)
    rho, cl = p.dogbone / 2.0, p.clearance
    x0 = t.x_lo                       # the plate footprint ends here
    half_slot = p.plywood / 2.0 + cl + p.dogbone_overcut
    holes = []
    if t.socket and not stub:         # a leg's long side: square end in the foot platform socket
        xc = t.x_cut
        pts = A + [(xc, t.yo(xc)), (xc, t.yi(xc))] + B[::-1]
        dogs = [False, False, True, True, False, False, False, True, False, False]
        k = t.spacers_each
        span = t.middle_len / (k + 1)
        xs = [x0 + i * span for i in range(1, k + 1)]
        label_x = _label_x(t.letter, p.label_height, xs, half_slot, t.x_lo, t.x_hi, (t.x_lo + t.x_hi) / 2.0)
        if p.center_hole > 0:
            holes.append([('C', (t.x_pin, t.ym(t.x_pin)), p.center_hole / 2.0)])
    elif stub:
        x_cut = x0 + d.stub_middle
        pts = A + [(x_cut, t.yo(x_cut)), (x_cut, t.yi(x_cut))] + B[::-1]
        dogs = [False, False, True, True, False, False, False, True, False, False]
        xs = [x0 + d.stub_spacer] if p.boards_per_strut == 2 else []
        lo = xs[0] + half_slot + 0.2 * p.label_height if xs else x0
        label_x = (lo + x_cut) / 2.0
    else:
        A2, B2, _at2 = _end_points(d, t, 1)
        pts = A + A2[::-1] + B2 + B[::-1]
        dogs = [False, False, True, True, False, False, True, True, False, False,
                False, False, True, True, False, False]
        k = t.spacers_each
        span = t.middle_len / (k + 1)
        xs = [x0 + i * span for i in range(1, k + 1)]
        centre = 0.0 if t.symmetric else (t.x_lo + t.x_hi) / 2.0
        label_x = _label_x(t.letter, p.label_height, xs, half_slot, t.x_lo, t.x_hi, centre)
    loops = [polygon_loop(pts, dogs, rho)] + holes
    hw = (d.spacer_height - 2.0 * d.shoulder) / 2.0 + cl
    for x in xs:
        loops.append(polygon_loop(_rect((x, t.ym(x)), (1.0, 0.0), p.plywood / 2.0 + cl, hw), [True] * 4, rho))
    label = (t.letter, label_x, t.ym(label_x))
    if d.model and not stub:     # bold capitals, about as wide as tall: placed (and sized) to clear the slots
        lo, hi = t.x_lo, t.x_hi
        centre = (lo + hi) / 2.0 if (t.socket or not t.symmetric) else 0.0
        lx, lh = _model_board_label(t.letter, p.label_height, xs, half_slot, lo, hi, centre)
        label = (t.letter, lx, t.ym(lx), lh) if lh > 0 else None
    geo = {'loops': loops, 'labels': [label] if label else [], 'thickness': p.plywood,
           'spacers_x': xs, 'grain': 'length'}
    geo.update(label_style(d))
    return geo


def _overlap(P, Q):
    """Two convex polygons overlap (separating axis test)."""
    for poly in (P, Q):
        k = len(poly)
        for i in range(k):
            ax = (poly[i][1] - poly[(i + 1) % k][1], poly[(i + 1) % k][0] - poly[i][0])
            pa = [ax[0] * x + ax[1] * y for x, y in P]
            qa = [ax[0] * x + ax[1] * y for x, y in Q]
            if max(pa) <= min(qa) or max(qa) <= min(pa):
                return False
    return True


def _inside(poly, pt):
    """Point inside a CCW convex polygon."""
    k = len(poly)
    return all((poly[(i + 1) % k][0] - poly[i][0]) * (pt[1] - poly[i][1]) -
               (poly[(i + 1) % k][1] - poly[i][1]) * (pt[0] - poly[i][0]) >= 0 for i in range(k))


def _fit_label(text, h0, pref, blocked, room, hole_r, clip, min_scale=0.6, wf=0.65, tf=0.8):
    """Label box as close to pref as it fits: inside room, clear of the blocked
    polygons, the centre hole and the floor cut; shrinks to min_scale (60 %) if it
    must. wf, tf: glyph width and height / text height (a model's bold digits are
    as tall as the text height). Returns (text, x, y, height)."""
    def ok(cx, cy, h):
        w, t = wf * h * len(text), tf * h
        box = [(cx - w / 2, cy - t / 2), (cx + w / 2, cy - t / 2), (cx + w / 2, cy + t / 2), (cx - w / 2, cy + t / 2)]
        if clip is not None and cx + w / 2 > clip - 0.5:
            return False
        if not all(_inside(room, q) for q in box):
            return False
        nx, ny = max(box[0][0], min(0.0, box[1][0])), max(box[0][1], min(0.0, box[2][1]))
        if math.hypot(nx, ny) < hole_r:
            return False
        return not any(_overlap(box, b) for b in blocked)
    if ok(pref[0], pref[1], h0):
        return (text, pref[0], pref[1], h0)
    xs = [q[0] for q in room]
    ys = [q[1] for q in room]
    for k in range(int(round((1.0 - min_scale) / 0.05)) + 1):
        h = h0 * (1.0 - 0.05 * k)
        step = h / 4.0
        cands = [(x0 * step, y0 * step) for x0 in range(int(min(xs) / step), int(max(xs) / step) + 1)
                 for y0 in range(int(min(ys) / step), int(max(ys) / step) + 1)]
        cands.sort(key=lambda q: math.hypot(q[0] - pref[0], q[1] - pref[1]))
        for cx, cy in cands:
            if ok(cx, cy, h):
                return (text, cx, cy, h)
    return (text, pref[0], pref[1], h0 if min_scale >= 0.6 else h0 * min_scale)


def label_style(d):
    """How the labels are cut: a model deeper and in bold so they print, the real
    dome LABEL_DEPTH deep (CNC)."""
    if d.model:
        return {'label_depth': d.p.print_label_depth, 'label_bold': True}
    return {'label_depth': LABEL_DEPTH, 'label_bold': False}


def plate_display(d, name):
    """A plate type as people see it: a model's plates with their digit, '2 (H6a)'."""
    code = d.plate_codes.get(name) if d.model and d.p.labels else None
    return '{} ({})'.format(code, name) if code else name


def part_title(d, key):
    """A part key as shown in reports and file names: 'Plate H6a' -> 'Plate 2 (H6a)'
    in a model ('Plate H6a outer' -> 'Plate 2 (H6a) outer'); anything else as it is."""
    if key.startswith('Plate '):
        name, _sep, side = key[len('Plate '):].partition(' ')
        return 'Plate ' + plate_display(d, name) + (' ' + side if side else '')
    return key


def plate_clip(d, n, inner=False):
    """Base plates are cut at the floor: keep x <= clip in the plate frame (x
    points down the plate). A tilted plate (the feet of the arches) is cut where
    its lower face meets the floor, so nothing of it is below the floor."""
    if not d.base[n]:
        return None
    o, e1, _e2, z = plate_frame(d, n, inner)
    down = -e1[2]
    if down < 1e-9:
        return None
    lowest = o[2] + min(0.0, d.p.plate * z[2])
    return (lowest - d.z_floor) / down


def plate_geometry(d, n, inner=False):
    """Hub plate at node n in its own frame (see plate_frame): slots with dogbones,
    centre hole, Hull or Circle outline. Base plates carry 'clip' (keep x <= clip)."""
    p = d.p
    ax = d.axis[n]
    e1 = _ref_dir(ax, d.base[n])
    e2 = _cross(ax, e1)
    if inner:
        e2 = _mul(e2, -1.0)
    c, o, rho = p.clearance, p.dogbone_overcut, p.dogbone / 2.0
    hl, hw = p.tenon_len / 2.0 + c, p.plywood / 2.0 + c
    mid = d.r_node + p.tenon_len / 2.0
    loops, slots, hull_pts, labels = [], [], [], []
    for m, ti, _si in d.adj[n]:
        w3 = d.tdir(n, m)
        w = _u2((_dot(w3, e1), _dot(w3, e2)))
        pe = (-w[1], w[0])
        for off in p.board_offsets():
            ctr = (w[0] * mid + pe[0] * off, w[1] * mid + pe[1] * off)
            loops.append(polygon_loop(_rect(ctr, w, hl, hw), [True] * 4, rho))
            slots.append((ctr, w, hl, hw))
            hull_pts += _rect(ctr, w, hl + o, hw + o)
        if not d.model:
            far = d.r_node + p.tenon_len + c + o + p.plate_margin / 2.0
            labels.append((LETTERS[ti], w[0] * far, w[1] * far))
    if p.center_hole > 0:
        loops.append([('C', (0.0, 0.0), p.center_hole / 2.0)])
    # the plate always covers its centre (the bolt): a foot hub has only two
    # struts side by side, its slots alone would leave the centre outside
    dirs = sorted(math.degrees(math.atan2(s[1][1], s[1][0])) % 360.0 for s in slots)
    if not dirs or max(g for g, _ in _gaps([(a, '') for a in dirs])) > 180.0 + 1e-6:
        ring = p.center_hole / 2.0 + p.min_web + c + o
        hull_pts += [(ring * math.cos(math.pi * i / 8.0), ring * math.sin(math.pi * i / 8.0)) for i in range(16)]
    hull = _convex_hull(hull_pts)
    if p.plate_shape == 'Circle':
        rc = max(math.hypot(q[0], q[1]) for q in hull_pts) + p.plate_margin
        outer = [('C', (0.0, 0.0), rc)]
        room = [((rc - 1.0) * math.cos(math.pi * i / 24), (rc - 1.0) * math.sin(math.pi * i / 24)) for i in range(48)]
    else:
        outer = _rounded_polygon(_offset_convex(hull, p.plate_margin), p.corner_radius)
        room = _offset_convex(hull, max(p.plate_margin - 1.0, 0.0))
    clip = plate_clip(d, n, inner)
    name = d.node_plate_names[n][1 if inner else 0] if d.node_plate_names else ''
    pref = (0.0, -max(0.45 * d.r_node, p.center_hole / 2.0 + (0.75 if d.model else 0.6) * p.label_height))
    blocked = [_rect(ctr, w, a + o + 0.5, b + o + 0.5) for ctr, w, a, b in slots]
    # a model's plate is too small for 'H6a': it carries one digit (summary and BOM say which type)
    text = d.plate_codes.get(name, name) if d.model else name
    if d.model:
        labels.append(_fit_label(text, p.label_height, pref, blocked, room, p.center_hole / 2.0 + 0.5, clip,
                                 0.4, 0.8, 1.05))
    else:
        labels.append(_fit_label(text, p.label_height, pref, blocked, room, p.center_hole / 2.0 + 0.5, clip))
    geo = {'loops': [outer] + loops, 'slots': slots, 'labels': labels, 'thickness': p.plate,
           'clip': clip, 'grain': 'any', 'name': name}
    geo.update(label_style(d))
    return geo


def spacer_geometry(d):
    """Spacer in its own frame: x across the strut (gap g in the middle, tenons of
    length t through the boards), y radial; shoulders hold the gap."""
    p = d.p
    a, b = p.board_gap / 2.0, d.spacer_height / 2.0
    bt, e = b - d.shoulder, a + p.plywood
    pts = [(-a, -b), (a, -b), (a, -bt), (e, -bt), (e, bt), (a, bt),
           (a, b), (-a, b), (-a, bt), (-e, bt), (-e, -bt), (-a, -bt)]
    return {'loops': [polygon_loop(pts, [False, False, True] * 4, p.dogbone / 2.0)], 'labels': [],
            'thickness': p.plywood, 'grain': 'any'}


def tube_geometry(d):
    """Printed tube between the plates of a model hub, on the bolt (model only)."""
    p = d.p
    r_in = p.center_hole / 2.0
    return {'loops': [[('C', (0.0, 0.0), r_in + TUBE_WALL)], [('C', (0.0, 0.0), r_in)]], 'labels': [],
            'thickness': p.frame_depth - p.plate - p.clearance, 'grain': 'any'}


# ----------------------------------------------------------- foot platform
# The platform is a small solid made of boxes and pins (a CSG tree) in its own
# frame: origin on the floor under the foot point, x outwards, y along the
# circle, z up - so it prints lying on its base. Nodes:
#   ('box', centre, u, v, (lu, lv, lw))  - edges along u, v and u x v
#   ('cyl', p0, p1, radius)
#   ('union', [nodes]), ('diff', node, [nodes]), ('inter', node, node)
def _box(o, ex, ey, ez, x0, x1, y0, y1, z0, z1):
    """Box between x0..x1, y0..y1, z0..z1 of the frame (o, ex, ey, ez)."""
    c = _add(o, _add(_mul(ex, (x0 + x1) / 2.0), _add(_mul(ey, (y0 + y1) / 2.0), _mul(ez, (z0 + z1) / 2.0))))
    return ('box', c, ex, ey, (x1 - x0, y1 - y0, z1 - z0))


def _box_corners(node):
    _k, c, u, v, (lu, lv, lw) = node
    w = _cross(u, v)
    return [_add(c, _add(_mul(u, su * lu / 2.0), _add(_mul(v, sv * lv / 2.0), _mul(w, sw * lw / 2.0))))
            for su in (-1, 1) for sv in (-1, 1) for sw in (-1, 1)]


def _box_floor_points(node, z_floor):
    """Corners of the part of a box above z_floor (the box clipped by the floor)."""
    cs = _box_corners(node)
    pts = [q for q in cs if q[2] >= z_floor]
    edges = [(i, j) for i in range(8) for j in range(i + 1, 8) if bin(i ^ j).count('1') == 1]
    for i, j in edges:
        a, b = cs[i], cs[j]
        if (a[2] - z_floor) * (b[2] - z_floor) < 0:
            t = (z_floor - a[2]) / (b[2] - a[2])
            pts.append(_add(a, _mul(_sub(b, a), t)))
    return pts


def csg_contains(node, q, eps=0.0):
    """Point inside the CSG solid (eps > 0 shrinks every box and pin a little)."""
    k = node[0]
    if k == 'box':
        _k, c, u, v, (lu, lv, lw) = node
        dd = _sub(q, c)
        w = _cross(u, v)
        return (abs(_dot(dd, u)) <= lu / 2.0 - eps and abs(_dot(dd, v)) <= lv / 2.0 - eps
                and abs(_dot(dd, w)) <= lw / 2.0 - eps)
    if k == 'cyl':
        _k, a, b, r = node
        ab = _sub(b, a)
        t = _dot(_sub(q, a), ab) / _dot(ab, ab)
        if t < 0 or t > 1:
            return False
        return _len(_sub(q, _add(a, _mul(ab, t)))) <= r - eps
    if k == 'union':
        return any(csg_contains(ch, q, eps) for ch in node[1])
    if k == 'inter':
        return csg_contains(node[1], q, eps) and csg_contains(node[2], q, eps)
    if k == 'diff':
        return csg_contains(node[1], q, eps) and not any(csg_contains(ch, q, -eps) for ch in node[2])
    raise ValueError(k)


def _csg_map(node, f, fv):
    """The same CSG tree with points mapped by f and directions by fv."""
    k = node[0]
    if k == 'box':
        return ('box', f(node[1]), fv(node[2]), fv(node[3]), node[4])
    if k == 'cyl':
        return ('cyl', f(node[1]), f(node[2]), node[3])
    if k == 'union':
        return ('union', [_csg_map(ch, f, fv) for ch in node[1]])
    if k == 'inter':
        return ('inter', _csg_map(node[1], f, fv), _csg_map(node[2], f, fv))
    return ('diff', _csg_map(node[1], f, fv), [_csg_map(ch, f, fv) for ch in node[2]])


def platform_frames(d):
    """Frames of the five foot platforms (the same part turned round the centre)."""
    return [platform_frame(d, f) for f in d.feet]


def platform_frame(d, foot, z_floor=None):
    """Frame of the platform under a foot node: origin on the floor, x outwards."""
    f = d.pos[foot]
    x = _unit((f[0], f[1], 0.0))
    return (f[0], f[1], d.z_floor if z_floor is None else z_floor), x, (-x[1], x[0], 0.0), (0.0, 0.0, 1.0)


def platform_geometry(d):
    """Foot platform (one design for all five feet): a base on the floor and a
    socket for each long side of the leg - the two boards of a long side slide in
    up to the seat, a fin between them, a pin through walls, boards and fin.
    Returns {'csg', 'csg_world', 'z_floor', 'size', 'volume', 'pin_len', 'arms'}."""
    p = d.p
    c, wall = p.clearance, p.plate
    foot = d.feet[0]
    arms = [(a, b, ti) for a, b, ti in d.struts if b == foot]
    blocks, cuts, seat_low = [], [], []
    hw_block = p.width / 2.0 + c + wall
    for a, b, ti in arms:
        t = d.types[ti]
        ex, ey, ez = d.strut_frame(a, b)
        o = _mul(_add(d.pos[a], d.pos[b]), 0.5)
        mouth = t.x_cut - t.depth
        far = t.chord_out / 2.0 + 2.0 * (t.depth + hw_block)
        blocks.append(_box(o, ex, ey, ez, mouth, far, t.y_in - c - wall, t.y_out + c + wall, -hw_block, hw_block))
        for off in p.board_offsets():
            pocket = _box(o, ex, ey, ez, mouth - wall - 1.0, t.x_cut, t.y_in - c, t.y_out + c,
                          off - p.plywood / 2.0 - c, off + p.plywood / 2.0 + c)
            cuts.append(pocket)
            seat_low.append(min(q[2] for q in _box_corners(pocket) if
                                abs(_dot(_sub(q, o), ex) - t.x_cut) < 1e-6))
        if p.center_hole > 0:
            mid = _add(o, _add(_mul(ex, t.x_pin), _mul(ey, t.ym(t.x_pin))))
            cuts.append(('cyl', _sub(mid, _mul(ez, hw_block + 1.0)), _add(mid, _mul(ez, hw_block + 1.0)),
                         p.center_hole / 2.0))
    z_floor = min(seat_low) - wall - wall           # solid under the seats, then the base
    fo = platform_frame(d, foot, z_floor)
    o_l, xl, yl, zl = fo
    pts = []
    for blk in blocks:
        pts += _box_floor_points(blk, z_floor)
    lx = [_dot(_sub(q, o_l), xl) for q in pts]
    ly = [_dot(_sub(q, o_l), yl) for q in pts]
    m = p.plate_margin
    base = _box(o_l, xl, yl, zl, min(lx) - m, max(lx) + m, min(ly) - m, max(ly) + m, 0.0, wall)
    big = 10.0 * (max(lx) - min(lx) + max(ly) - min(ly) + 4.0 * d.types[arms[0][2]].depth)
    keep = _box(o_l, xl, yl, zl, -big, big, -big, big, 0.0, big)
    world = ('diff', ('union', [('inter', ('union', blocks), keep), base]), cuts)

    def to_local(q):
        dq = _sub(q, o_l)
        return (_dot(dq, xl), _dot(dq, yl), _dot(dq, zl))

    def vec_local(v):
        return (_dot(v, xl), _dot(v, yl), _dot(v, zl))
    local = _csg_map(world, to_local, vec_local)
    corners = []
    for blk in blocks:
        corners += [to_local(q) for q in _box_floor_points(blk, z_floor)]
    corners += [to_local(q) for q in _box_corners(base)]
    xs, ys, zs = [q[0] for q in corners], [q[1] for q in corners], [q[2] for q in corners]
    lo, hi = (min(xs), min(ys), 0.0), (max(xs), max(ys), max(zs))
    n = 24        # volume by sampling the bounding box (for the weight)
    cell = [(hi[i] - lo[i]) / n for i in range(3)]
    inside = sum(1 for i in range(n) for j in range(n) for k in range(n)
                 if csg_contains(local, (lo[0] + (i + 0.5) * cell[0], lo[1] + (j + 0.5) * cell[1],
                                         lo[2] + (k + 0.5) * cell[2])))
    return {'csg': local, 'csg_world': world, 'z_floor': z_floor, 'frame0': fo,
            'size': (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]), 'bbox': (lo, hi),
            'volume': inside * cell[0] * cell[1] * cell[2], 'pin_len': 2.0 * hw_block, 'arms': arms}


# -------------------------------------------------------------------- frames
# A frame is (origin, x, y, z) in world mm, Z up; a part is its 2D geometry in
# the frame's XY plane extruded +z by its thickness.
def board_frame(d, a, b, ti, offset):
    """Board on strut a->b (a = the 'P' end of board_geometry), offset d_i.
    Origin at the middle of the outer chord, x along it, y outwards."""
    ex, ey, ez = d.strut_frame(a, b)
    mid = _mul(_add(d.pos[a], d.pos[b]), 0.5)
    return _add(mid, _mul(ez, offset - d.p.plywood / 2.0)), ex, ey, ez


def plate_frame(d, n, inner=False):
    """Outer plate: its origin is tp inward of N_out; +z extrusion finishes at
    N_out. Inner plate: mirrored, z towards the centre from N_in, so its
    engraved +z face is the visible inner face."""
    ax = d.axis[n]
    e1 = _ref_dir(ax, d.base[n])
    e2 = _cross(ax, e1)
    if inner:
        return d.inner(n), e1, _mul(e2, -1.0), _mul(ax, -1.0)
    # Plate occupies tau [-tp, 0], not [0, tp]. Its outside face is at N_out.
    return _sub(d.pos[n], _mul(ax, d.p.plate)), e1, e2, ax


def tube_frame(d, n):
    """Tube on the hub axis of node n, centred between the plates."""
    ax = d.axis[n]
    e1 = _ref_dir(ax, d.base[n])
    o = _sub(d.pos[n], _mul(ax, d.p.frame_depth - d.p.clearance / 2.0))
    return o, e1, _cross(ax, e1), ax


def spacer_frame(d, a, b, ti, x):
    """Spacer at board coordinate x on strut a->b."""
    ex, ey, ez = d.strut_frame(a, b)
    t = d.types[ti]
    mid = _mul(_add(d.pos[a], d.pos[b]), 0.5)
    centre = _add(_add(mid, _mul(ey, t.ym(x))), _mul(ex, x))
    return _add(centre, _mul(ex, d.p.plywood / 2.0)), ez, ey, _mul(ex, -1.0)


def to_frame(frame, pt):
    o, x, y, z = frame
    v = _sub(pt, o)
    return (_dot(v, x), _dot(v, y), _dot(v, z))


def frame_in(frame, base):
    """Express a world frame in the coordinates of another frame."""
    o, x, y, z = frame
    O, X, Y, Z = base

    def f(v):
        return (_dot(v, X), _dot(v, Y), _dot(v, Z))
    return f(_sub(o, O)), f(x), f(y), f(z)


def test_hub_node(d):
    """A non-base node with 6 dome struts whose outer plate is of the most common type."""
    qty = {t.name: t.qty for t in d.plate_types}
    best = None
    for n in range(d.n_nodes):
        if d.base[n] or len(d.adj[n]) != 6:
            continue
        if not all(d.types[ti].symmetric for _m, ti, _si in d.adj[n]):
            continue
        q = qty.get(d.node_plate_names[n][0], 0)
        if best is None or q > best[0]:
            best = (q, n)
    return best[1] if best else 0


def tenon_fit(d):
    """Worst deviation (mm) of any tenon from its ideal seat: footprint inside a
    plate slot with clearance c on every side, height exactly t_p. The
    outer tenon now runs from tau=-tp (root) to tau=0 (flush face)."""
    p = d.p
    worst = 0.0
    plates = {}
    r, Lt, h, tp = d.r_node, p.tenon_len, p.frame_depth, p.plate
    for a, b, ti in d.struts:
        quads = []
        for end, node in ((0, a), (1, b)):
            if end == 1 and d.types[ti].socket:
                continue
            at = _end_at(d.types[ti], end)
            quads.append((node, False, [at(0.0, r), at(0.0, r + Lt), at(-tp, r + Lt), at(-tp, r)]))
            quads.append((node, True, [at(-h - tp, r), at(-h - tp, r + Lt), at(-h, r + Lt), at(-h, r)]))
        for off in p.board_offsets():
            o, ex, ey, ez = board_frame(d, a, b, ti, off)
            for node, inner, quad in quads:
                key = (node, inner)
                if key not in plates:
                    plates[key] = (plate_frame(d, node, inner), plate_geometry(d, node, inner)['slots'])
                pf, slots = plates[key]
                pts = [to_frame(pf, _add(_add(_add(o, _mul(ex, qx)), _mul(ey, qy)), _mul(ez, z)))
                       for qx, qy in quad for z in (0.0, p.plywood)]
                zs = [q[2] for q in pts]
                worst = max(worst, abs(min(zs)), abs(max(zs) - p.plate))
                best = None
                for ctr, w, hl, hw in slots:
                    pe = (-w[1], w[0])
                    al = [(q[0] - ctr[0]) * w[0] + (q[1] - ctr[1]) * w[1] for q in pts]
                    la = [(q[0] - ctr[0]) * pe[0] + (q[1] - ctr[1]) * pe[1] for q in pts]
                    dev = max(abs(max(al) - (hl - p.clearance)), abs(min(al) + (hl - p.clearance)),
                              abs(max(la) - (hw - p.clearance)), abs(min(la) + (hw - p.clearance)))
                    best = dev if best is None else min(best, dev)
                worst = max(worst, best)
    return worst


# ---------------------------------------------------------- plate placement
def _plate_pattern(d, n, inner):
    """Strut directions at node n in the plate frame: sorted [(angle_deg, letter)]."""
    ax = d.axis[n]
    e1 = _ref_dir(ax, d.base[n])
    e2 = _cross(ax, e1)
    if inner:
        e2 = _mul(e2, -1.0)
    items = []
    for m, ti, _si in d.adj[n]:
        w = d.tdir(n, m)
        items.append((math.degrees(math.atan2(_dot(w, e2), _dot(w, e1))) % 360.0, LETTERS[ti]))
    items.sort()
    return items


def _rotation_between(ref, items):
    """In-plane angle (deg) that turns the reference pattern into items, or None."""
    k = len(ref)
    if k != len(items):
        return None
    for s in range(k):
        diffs = []
        for j in range(k):
            a, la = items[(j + s) % k]
            b, lb = ref[j]
            if la != lb:
                break
            diffs.append((a - b) % 360.0)
        else:
            base = diffs[0]
            dev = [((x - base + 180.0) % 360.0) - 180.0 for x in diffs]
            if all(abs(v) < ANGLE_TOL for v in dev):
                return base + sum(dev) / k
    return None


def _rotate_frame(frame, deg):
    o, x, y, z = frame
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return o, _add(_mul(x, c), _mul(y, s)), _add(_mul(x, -s), _mul(y, c)), z


def plate_placements(d):
    """Every plate (outer, inner of each node, in node order) as (type, frame).
    A type's geometry is built once at its representative reps[type] = (n, inner);
    frames are turned in-plane so that geometry lands on each node."""
    reps, placements = {}, []
    for n in range(d.n_nodes):
        if d.socket[n]:
            continue
        for inner in (False, True):
            name = d.node_plate_names[n][1 if inner else 0]
            items = _plate_pattern(d, n, inner)
            frame = plate_frame(d, n, inner)
            if name not in reps:
                reps[name] = (n, inner, items)
                placements.append((name, frame))
            elif d.base[n]:
                placements.append((name, frame))
            else:
                deg = _rotation_between(reps[name][2], items)
                if deg is None:
                    raise ValueError("plate type {} does not fit node {}".format(name, n))
                placements.append((name, _rotate_frame(frame, deg)))
    return placements, {k: (v[0], v[1]) for k, v in reps.items()}


# ---------------------------------------------------------------- BOM, weight
BOLT_SIZES = (2, 2.5, 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24)
BOLT_LENGTHS = (6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100,
                110, 120, 130, 140, 150, 160, 180, 200, 220, 240, 260, 280, 300)


def bolt_size(hole):
    """Largest metric bolt that goes into the centre hole (12 -> M12, 3.3 -> M3)."""
    fit = [s for s in BOLT_SIZES if s <= hole + 0.05]
    return fit[-1] if fit else None


def _arc_points(p0, pm, p1, steps=8):
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    den = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(den) < 1e-12:
        return [p0, p1]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / den
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / den
    r = math.hypot(ax - ux, ay - uy)
    a0, am, a1 = (math.atan2(q[1] - uy, q[0] - ux) for q in (p0, pm, p1))
    tw = 2.0 * math.pi
    span = (a1 - a0) % tw if (am - a0) % tw < (a1 - a0) % tw else -((a0 - a1) % tw)
    return [(ux + r * math.cos(a0 + span * i / steps), uy + r * math.sin(a0 + span * i / steps))
            for i in range(steps + 1)]


def _loop_points(loop):
    if loop and loop[0][0] == 'C':
        (cx, cy), r = loop[0][1], loop[0][2]
        return [(cx + r * math.cos(math.pi * i / 32), cy + r * math.sin(math.pi * i / 32)) for i in range(64)]
    pts = []
    for el in loop:
        seg = [el[1], el[2]] if el[0] == 'L' else _arc_points(el[1], el[2], el[3])
        pts.extend(seg[:-1])
    return pts


def _area(pts):
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))) / 2.0


def _clip_x(pts, xmax):
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if a[0] <= xmax:
            out.append(a)
        if (a[0] <= xmax) != (b[0] <= xmax):
            t = (xmax - a[0]) / (b[0] - a[0])
            out.append((xmax, a[1] + t * (b[1] - a[1])))
    return out


def part_size(geo):
    """(length, width, area m2) of a part in its own frame, holes subtracted,
    base plates cut at the floor."""
    outer = _loop_points(geo['loops'][0])
    holes = [_loop_points(loop) for loop in geo['loops'][1:]]
    if geo.get('clip') is not None:
        outer = _clip_x(outer, geo['clip'])
        holes = [_clip_x(h, geo['clip']) for h in holes]
    xs, ys = [q[0] for q in outer], [q[1] for q in outer]
    area = _area(outer) - sum(_area(h) for h in holes if len(h) >= 3)
    return max(xs) - min(xs), max(ys) - min(ys), area / 1e6


def bom(d):
    """Parts and hardware: dicts with type, part, qty, length, width, thickness,
    area (m2 each) and note."""
    p = d.p
    rows = []
    where = {'dome': '', 'wall': ', wall', 'leg': ', leg'}
    for ti, t in enumerate(d.types):
        L, W, A = part_size(board_geometry(d, ti))
        rows.append(dict(type=t.letter, part='Board', qty=t.count * p.boards_per_strut, length=L, width=W,
                         thickness=p.plywood, area=A, note='grain along the board' + where.get(t.kind, '')))
    placements, reps = plate_placements(d)
    qty = {}
    for name, _frame in placements:
        qty[name] = qty.get(name, 0) + 1
    for pt in d.plate_types:
        n, inner = reps[pt.name]
        L, W, A = part_size(plate_geometry(d, n, inner))
        notes = ['digit {} on the model'.format(d.plate_codes[pt.name])] if d.model and p.labels else []
        notes += ['base, cut at the floor'] if pt.base else []
        rows.append(dict(type=pt.name, part='Plate', qty=qty[pt.name], length=L, width=W,
                         thickness=p.plate, area=A, note='; '.join(notes)))
    if p.boards_per_strut == 2 and d.n_spacers:
        L, W, A = part_size(spacer_geometry(d))
        rows.append(dict(type='S', part='Spacer', qty=d.n_spacers, length=L, width=W,
                         thickness=p.plywood, area=A, note=''))
    nn = d.n_hubs
    if d.has_tubes:
        L, W, A = part_size(tube_geometry(d))
        rows.append(dict(type='T', part='Tube', qty=nn, length=L, width=W,
                         thickness=p.frame_depth - p.plate - p.clearance, area=A, note='printed, between the plates'))
    m = bolt_size(p.center_hole) if p.center_hole > 0 else None
    if m:
        ms = '{:g}'.format(m)
        need = p.frame_depth + p.plate + 1.7 * m             # recessed outer plate, inner plate, hardware
        bolt = next((b for b in BOLT_LENGTHS if b >= need), int(math.ceil(need / 10.0) * 10))
        hardware = [('M{}x{}'.format(ms, bolt), nn, bolt, 'bolt, min length {:.0f} mm'.format(need)),
                    ('M{} nut'.format(ms), nn, 0, ''), ('M{} washer'.format(ms), 2 * nn, 0, '')]
        if not d.has_tubes:
            tube_len = p.frame_depth - p.plate
            hardware.append(('Tube L{:.0f}'.format(tube_len), nn, tube_len,
                             'between the plates, inner diameter >= {:g} mm'.format(p.center_hole + 1.0)))
        for typ, q, length, note in hardware:
            rows.append(dict(type=typ, part='Hardware', qty=q, length=length, width=0.0, thickness=0.0,
                             area=0.0, note=note))
    if d.platform:
        pl, nf = d.platform, len(d.feet)
        L, W, H = pl['size']
        if d.model:
            rows.append(dict(type='F', part='Platform', qty=nf, length=L, width=W, thickness=H,
                             area=pl['volume'] / H / 1e6, note='printed foot platform, base down, no supports'))
        else:
            rows.append(dict(type='Foot shoe', part='Hardware', qty=nf, length=L, width=W, thickness=0.0, area=0.0,
                             note='steel, welded to the platform shape: base plate + 2 sockets, '
                                  '{:.0f} mm high, anchored to the ground'.format(H)))
        m = bolt_size(p.center_hole) if p.center_hole > 0 else None
        if m:
            need = pl['pin_len'] + 1.7 * m
            pin = next((b for b in BOLT_LENGTHS if b >= need), int(math.ceil(need / 10.0) * 10))
            rows.append(dict(type='M{:g}x{} pin'.format(m, pin), part='Hardware', qty=2 * nf, length=pin, width=0.0,
                             thickness=0.0, area=0.0, note='bolt + nut through socket, boards and fin'))
    if not d.model and d.shape == 'Walls':
        area = wall_area(d) / 1e6
        sheets = int(math.ceil(area * 1.1 / (p.sheet_len * p.sheet_wid / 1e6) - 1e-9))
        rows.append(dict(type='Wall sheathing', part='Hardware', qty=sheets, length=0.0, width=0.0, thickness=0.0,
                         area=0.0, note='OSB / plywood sheets {:.0f} x {:.0f}, about {:.1f} m2 + 10 %: braces the wall '
                         'frames'.format(p.sheet_len, p.sheet_wid, area)))
    return rows


def plywood_area(rows):
    return sum(r['qty'] * r['area'] for r in rows if r['part'] != 'Hardware')


def frame_weight(rows, density=DENSITY):
    """kg of all parts (area m2 x thickness mm)."""
    return sum(r['qty'] * r['area'] * r['thickness'] / 1000.0 * density for r in rows if r['part'] != 'Hardware')


def bom_csv(d, rows=None):
    """Semicolon CSV with decimal commas (opens directly in German/Russian Excel)."""
    rows = rows if rows is not None else bom(d)

    def num(v, nd):
        return '{:.{}f}'.format(v, nd).replace('.', ',')
    lines = ['Type;Part;Qty;Length mm;Width mm;Thickness mm;Area each m2;Area total m2;Note']
    nd, ad = (1, 6) if d.model else (0, 4)
    for r in rows:
        hw = r['part'] == 'Hardware'
        lines.append(';'.join([r['type'], r['part'], str(r['qty']),
                               num(r['length'], nd) if r['length'] else '',
                               '' if hw else num(r['width'], nd), '' if hw else num(r['thickness'], 1),
                               '' if hw else num(r['area'], ad), '' if hw else num(r['area'] * r['qty'], ad - 1),
                               r['note']]))
    if d.model:
        lines.append(';;;;;;;{};printed parts, about {} g PLA (solid), model 1:{:g}'.format(
            num(plywood_area(rows), ad - 1), num(frame_weight(rows, d.density) * 1000.0, 0), d.k))
    else:
        lines.append(';;;;;;;{};plywood total, frame about {} kg ({} kg/m3)'.format(
            num(plywood_area(rows), 3), num(frame_weight(rows), 0), num(DENSITY, 0)))
    return '\r\n'.join(lines) + '\r\n'
