"""Acceptance checks for step 1 (spec: "Rocket Geodome - TZ v1", section Geometry).
Run outside Fusion:  python test_core.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geodome_core as core  # noqa: E402

EXPECT = {
    2: dict(nodes=26, base=10, struts=65, valence={4: 10, 5: 6, 6: 10}, plates=4,
            counts=[30, 35], chords=[0.54653, 0.61803]),
    4: dict(nodes=91, base=20, struts=250, valence={4: 20, 5: 6, 6: 65}, plates=8,
            counts=[30, 60, 30, 30, 70, 30],
            chords=[0.25318, 0.29453, 0.29524, 0.29859, 0.31287, 0.32492]),
    6: dict(nodes=196, base=30, struts=555, valence={4: 30, 5: 6, 6: 160}, plates=13,
            counts=[30, 60, 30, 30, 60, 90, 130, 65, 60],
            chords=[0.16257, 0.18191, 0.18738, 0.19048, 0.19801, 0.20282, 0.20591, 0.21535, 0.21663]),
}

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


for f, e in EXPECT.items():
    d = core.analyze(core.Params(frequency=f))
    tag = "{}V".format(f)
    check(not d.errors, tag + " errors: {}".format(d.errors))
    check(d.n_nodes == e["nodes"], tag + " nodes {} != {}".format(d.n_nodes, e["nodes"]))
    check(d.n_base == e["base"], tag + " base nodes {} != {}".format(d.n_base, e["base"]))
    check(d.n_struts == e["struts"], tag + " struts {} != {}".format(d.n_struts, e["struts"]))
    check(d.crossing == 0, tag + " struts cross the equator: {}".format(d.crossing))
    check(d.valence == e["valence"], tag + " valence {} != {}".format(d.valence, e["valence"]))
    check([t.count for t in d.types] == e["counts"], tag + " type counts {}".format([t.count for t in d.types]))
    check([round(t.factor, 5) for t in d.types] == e["chords"],
          tag + " chord factors {}".format([round(t.factor, 5) for t in d.types]))
    check(len(d.plate_types) == e["plates"], tag + " plate types {} != {}".format(len(d.plate_types), e["plates"]))
    check(sum(t.qty for t in d.plate_types) == 2 * d.n_nodes, tag + " plate qty != 2 x nodes")
    check(all(abs(n[2]) < 1e-12 or n[2] > 0 for n in d.nodes), tag + " node below the equator")
    print("{}: nodes {}, struts {}, strut types {}, plate types {} ({}), r {:.0f} mm, "
          "sharpest {:.2f} deg, spacers {}".format(
              tag, d.n_nodes, d.n_struts, len(d.types), len(d.plate_types),
              ", ".join("{} x{}".format(t.name, t.qty) for t in d.plate_types),
              d.r_node, __import__("math").degrees(d.alpha_min), d.n_spacers))
    for t in d.types:
        print("    {} {:.5f} x{:3d}  chord {:6.1f}  board {:6.1f} x {:5.1f}  middle {:6.1f}  spacers/strut {}".format(
            t.letter, t.factor, t.count, t.chord_out, t.board_len, t.board_wid, t.middle_len, t.spacers_each))

# heights for the defaults (recessed outer plate is flush at R, floor 33 mm below)
d = core.analyze(core.Params())
check(abs(d.z_floor + 33.0) < 1e-9, "floor {}".format(d.z_floor))
check(abs(d.h_total - 3033.0) < 1e-9, "H_total {}".format(d.h_total))
check(abs(d.h_clear - 2865.0) < 1e-9, "H_clear {}".format(d.h_clear))
check(d.n_spacers == 250, "4V spacers {}".format(d.n_spacers))

# params round trip and validation
p = core.Params(diameter=8000, frequency=6, plate_shape="Circle", labels=False)
q = core.Params.from_dict(p.to_dict())
check(q == p, "params round trip")
bad = core.analyze(core.Params(frequency=3))
check(bool(bad.errors), "frequency 3 must be rejected")
check(core.summary_html(bad).startswith("<b>Errors"), "summary with errors")
check("Hub radius" in core.summary_html(d), "summary text")

# single boards and the circle plate still analyse
check(not core.analyze(core.Params(boards_per_strut=1)).errors, "n = 1 errors")
check(not core.analyze(core.Params(plate_shape="Circle")).errors, "circle plate errors")
# a tiny dome must report overlapping hub zones
check(any("overlap" in e for e in core.analyze(core.Params(diameter=1500)).errors), "tiny dome overlap error")

# step 3: part geometry - every tenon sits in its slot with clearance c, loops close
import math  # noqa: E402
for kw in (dict(), dict(frequency=2), dict(frequency=6), dict(boards_per_strut=1), dict(plate_shape="Circle")):
    d = core.analyze(core.Params(**kw))
    fit = core.tenon_fit(d)
    check(fit < 1e-6, "tenon fit {} worst {:.3g} mm".format(kw, fit))
    ok = all(core.loops_closed(core.board_geometry(d, ti, stub=s)["loops"])
             for ti in range(len(d.types)) for s in (False, True))
    ok = ok and all(core.loops_closed(core.plate_geometry(d, k, inner)["loops"])
                    for k in range(d.n_nodes) for inner in (False, True))
    check(ok, "open loop in parts {}".format(kw))
    hub = core.test_hub_node(d)
    check(not d.base[hub] and len(d.adj[hub]) == 6, "test hub node {}".format(kw))
    if d.p.boards_per_strut == 2:
        check(core.loops_closed(core.spacer_geometry(d)["loops"]), "spacer loop {}".format(kw))
        # spacer tenons pass through both boards' slots with clearance c
        a, b, ti = d.struts[0]
        geo = core.board_geometry(d, ti)
        x = geo["spacers_x"][0]
        sf = core.spacer_frame(d, a, b, ti, x)
        p = d.p
        y_mid = (d.types[ti].y_out + d.types[ti].y_in) / 2.0
        tab_h = d.spacer_height / 2.0 - d.shoulder
        for off, sx in zip(p.board_offsets(), (-1.0, 1.0)):
            bf = core.board_frame(d, a, b, ti, off)
            for lx in (sx * p.board_gap / 2.0, sx * (p.board_gap / 2.0 + p.plywood)):
                for ly in (-tab_h, tab_h):
                    for lz in (0.0, p.plywood):
                        o, X, Y, Z = sf
                        w = tuple(o[i] + lx * X[i] + ly * Y[i] + lz * Z[i] for i in range(3))
                        q = core.to_frame(bf, w)
                        ok_x = abs(q[0] - x) <= p.plywood / 2.0 + 1e-6
                        ok_y = abs(q[1] - y_mid) <= tab_h + 1e-6
                        ok_z = -1e-6 <= q[2] <= p.plywood + 1e-6
                        check(ok_x and ok_y and ok_z, "spacer tab outside slot {} {}".format(kw, q))

# step 4: plate types placed by rotated frames land exactly on every node; BOM totals
for kw in (dict(), dict(frequency=2), dict(frequency=6), dict(boards_per_strut=1)):
    d = core.analyze(core.Params(**kw))
    placements, reps = core.plate_placements(d)
    check(len(placements) == d.n_plates, "placements {}".format(kw))
    rep_geo = {k: core.plate_geometry(d, n, inner) for k, (n, inner) in reps.items()}

    def world(fr, q):
        o, x, y, z = fr
        return tuple(o[j] + q[0] * x[j] + q[1] * y[j] for j in range(3))
    worst, i = 0.0, 0
    for n in range(d.n_nodes):
        for inner in (False, True):
            name, frame = placements[i]
            i += 1
            own = [world(core.plate_frame(d, n, inner), s[0]) for s in core.plate_geometry(d, n, inner)["slots"]]
            for s in rep_geo[name]["slots"]:
                a = world(frame, s[0])
                worst = max(worst, min(math.dist(a, b) for b in own))
    check(worst < 1e-6, "plate placement {} worst {:.3g} mm".format(kw, worst))
    rows = core.bom(d)
    by = {}
    for r in rows:
        by[r["part"]] = by.get(r["part"], 0) + r["qty"]
    check(by.get("Board") == d.n_boards, "BOM boards {}".format(kw))
    check(by.get("Plate") == d.n_plates, "BOM plates {}".format(kw))
    check(by.get("Spacer", 0) == d.n_spacers, "BOM spacers {}".format(kw))
    check(core.frame_weight(rows) > 0 and core.bom_csv(d, rows).count("\r\n") == len(rows) + 2, "BOM csv {}".format(kw))

# model 1:N: shape sizes / N, print values as entered, constants scaled, no dogbones
m = core.analyze(core.Params(diameter=3000, frequency=2, model_scale=10))
check(not m.errors and not m.warnings, "model 3 m 2V 1:10: {} {}".format(m.errors, m.warnings))
check(m.model and m.p.model_scale == 1.0 and abs(m.p.diameter - 300.0) < 1e-9, "model effective params")
check(m.p.plywood == 3.0 and m.p.plate == 3.0 and m.p.dogbone == 0.0 and m.p.clearance == 0.2, "model print values")
check(abs(m.r_node - 9.7) < 1e-9 and m.n_spacers == 65, "model r {} spacers {}".format(m.r_node, m.n_spacers))
check(m.name == "Dome D3000 2V model 1-10", "model name " + m.name)
check(core.tenon_fit(m) < 1e-6, "model tenon fit")
no_arcs = all(el[0] != "A" for ti in range(len(m.types)) for loop in core.board_geometry(m, ti)["loops"] for el in loop)
no_arcs = no_arcs and all(el[0] != "A" for loop in core.spacer_geometry(m)["loops"] for el in loop)
no_arcs = no_arcs and all(el[0] != "A" for k in range(m.n_nodes) for loop in core.plate_geometry(m, k)["loops"][1:] for el in loop)
check(no_arcs, "model parts must have no dogbones")
labels = [core.plate_geometry(m, k)["labels"] for k in range(m.n_nodes)]
check(all(len(lb) == 1 for lb in labels), "model plates carry only their code")
rows = core.bom(m)
types = [r["type"] for r in rows]
check("T" in types and "M3x25" in types and "Tube L15" not in " ".join(types), "model BOM {}".format(types))
check(abs(core.frame_weight(rows, m.density) * 1000.0 - 612) < 15, "model PLA grams")
check("Model 1:10" in core.summary_html(m), "model summary")
csv = core.bom_csv(m, rows)
check("g PLA" in csv and csv.count("\r\n") == len(rows) + 2, "model csv")
tf = core.tube_frame(m, 0)
check(abs(math.dist(tf[0], (0, 0, 0)) - (m.p.R - m.p.frame_depth + m.p.clearance / 2)) < 1e-9, "tube between the plates")
check(abs(core.tube_geometry(m)['thickness'] - (m.p.frame_depth - m.p.plate - m.p.clearance)) < 1e-9,
      "recessed hub tube length")
check(any("recessed hub" in err for err in core.analyze(core.Params(frame_depth=10, plate=18)).errors),
      "recess frame depth validation")
# a real dome is not touched by the print values
r1 = core.analyze(core.Params(print_plywood=7, print_hole=0, bed_len=10))
r0 = core.analyze(core.Params())
check(core.bom_csv(r1) == core.bom_csv(r0) and r1.r_node == r0.r_node, "print values leak into the real dome")
check(not core.analyze(core.Params(model_scale=10)).errors, "6 m 4V model 1:10")
bad = core.analyze(core.Params(model_scale=10, print_plywood=0))
check(any("Print board thickness" in e for e in bad.errors), "print thickness validation")

# Straight boards: the outer edge meets the recessed outer plate at the pocket
# exit (tau = 0), the pocket clears the plate, and the inner edge is unchanged.
for kw in (dict(), dict(frequency=2), dict(frequency=6), dict(boards_per_strut=1),
           dict(diameter=3000, frequency=2, model_scale=10), dict(plate_shape="Circle")):
    d = core.analyze(core.Params(**kw))
    p = d.p
    worst_out = worst_in = 0.0
    for ti, t in enumerate(d.types):
        s, c = math.sin(t.half_angle), math.cos(t.half_angle)
        x1 = d.plate_edge + d.transition
        for i in range(41):
            mu = d.r_node + p.tenon_len + (x1 - d.r_node - p.tenon_len) * i / 40.0
            lam_in = (t.y_in + p.R * c - mu * s) / c
            worst_in = max(worst_in, (p.R - p.frame_depth) - lam_in)
        A, B, at = core._board_points(d, ti)
        check(abs(A[4][1] - t.yo(A[4][0])) < 1e-9 and abs(B[2][1] - t.yi(B[2][0])) < 1e-9,
              "edges through the corners {}".format(kw))
        for end in ((0,) if t.socket else (0, 1)):
            A_end, _B_end, at_end = core._end_points(d, t, end)
            target = [at_end(0.0, d.r_node), at_end(0.0, d.r_node + p.tenon_len),
                      at_end(-p.plate, d.r_node + p.tenon_len), at_end(-p.plate, x1), at_end(0.0, x1)]
            worst_out = max(worst_out, *(math.dist(u, v) for u, v in zip(A_end, target)))
        # Both outer plate faces are exactly at the node surface, not raised by tp.
        n = d.struts[0][0]
        pf = core.plate_frame(d, n, False)
        outer_face = tuple(pf[0][j] + p.plate * pf[3][j] for j in range(3))
        worst_out = max(worst_out, math.dist(outer_face, d.pos[n]))
        geo = core.board_geometry(d, ti)
        outline = core._loop_points(geo["loops"][0])
        check(sum(1 for q in outline if abs(q[1] - t.yo(q[0])) < 1e-9) >= 2,
              "outer edge straight {}".format(kw))
        lab = geo["labels"][0]
        check(abs(lab[2] - (t.y_out + t.y_in) / 2.0) < 1e-9, "label on the centre line {}".format(kw))
        if not any(abs(x) < 1e-9 for x in geo["spacers_x"]):
            check(abs(lab[1]) < 1e-9, "label in the middle {} {}".format(kw, lab))
    check(worst_out < 1e-9, "recess and plate face alignment {} dev {:.3g}".format(kw, worst_out))
    check(worst_in < 1e-9, "board cuts into the inner plate {} by {:.3g}".format(kw, worst_in))

# v0.6 base shapes: hemisphere on straight walls, arches on legs
def plate_intrusion(d):
    """Worst mismatch at pocket/plate boundaries, plus inner-plate intrusion.

    The outside edge before the pocket exit is deliberately recessed and must
    not be evaluated using the extrapolated straight edge from the middle.
    """
    p = d.p
    mu0, x1 = d.r_node + p.tenon_len, d.plate_edge + d.transition
    worst = 0.0
    for t in d.types:
        for end in ((0,) if t.socket else (0, 1)):      # a leg's foot end has no plates
            A, B, at = core._end_points(d, t, end)
            for q, expected in zip(A, (at(0, d.r_node), at(0, mu0), at(-p.plate, mu0),
                                       at(-p.plate, x1), at(0, x1))):
                worst = max(worst, math.dist(q, expected))
            phi = t.half_angle if end == 0 else t.phi_q
            s, c = math.sin(phi), math.cos(phi)
            sg = 1.0 if end == 1 else -1.0
            for i in range(41):
                mu = mu0 + (x1 - mu0) * i / 40.0
                # Inner-plate placement is unchanged.
                tau = (t.y_in + t.k_in * (sg * t.chord_out / 2.0 - sg * mu * c) - mu * s) / (c - sg * t.k_in * s)
                worst = max(worst, -p.frame_depth - tau)
    return worst


def lowest_part(d):
    """Lowest point of every board and plate (base plates after the floor cut), above the floor."""
    p, low = d.p, float("inf")
    for a, b, ti in d.struts:
        pts = core._loop_points(core.board_geometry(d, ti)["loops"][0])
        for off in p.board_offsets():
            o, X, Y, Z = core.board_frame(d, a, b, ti, off)
            low = min([low] + [o[2] + qx * X[2] + qy * Y[2] + z * Z[2] for qx, qy in pts for z in (0.0, p.plywood)])
    for n in range(d.n_nodes):
        if d.socket[n]:
            continue
        for inner in (False, True):
            geo = core.plate_geometry(d, n, inner)
            pts = core._loop_points(geo["loops"][0])
            if geo.get("clip") is not None:
                pts = core._clip_x(pts, geo["clip"])
            o, X, Y, Z = core.plate_frame(d, n, inner)
            low = min([low] + [o[2] + qx * X[2] + qy * Y[2] + z * Z[2] for qx, qy in pts for z in (0.0, p.plate)])
    return low - d.z_floor


SHAPES = [
    (dict(base_shape="Walls"), dict(nodes=111, base=20, struts=290, types=7, floor=-1000.0)),
    (dict(base_shape="Walls", frequency=2, wall_rows=2), dict(nodes=46, base=10, struts=105, types=3, floor=-1000.0)),
    (dict(base_shape="Walls", frequency=6, wall_height=1500, wall_rows=3),
     dict(nodes=286, base=30, struts=735, types=10, floor=-1500.0)),
    (dict(base_shape="Arches", frequency=2), dict(nodes=21, base=0, struts=45, types=3, floor=None)),
    (dict(base_shape="Arches"), dict(nodes=56, base=0, struts=140, types=7, floor=None)),
    (dict(base_shape="Arches", frequency=6), dict(nodes=111, base=0, struts=295, types=10, floor=None)),
    (dict(base_shape="Arches", leg_length=5200), dict(nodes=56, base=0, struts=140, types=7, floor=None)),
    (dict(base_shape="Arches", boards_per_strut=1), dict(nodes=56, base=0, struts=140, types=7, floor=None)),
    (dict(base_shape="Arches", frequency=2, diameter=3000, model_scale=10),
     dict(nodes=21, base=0, struts=45, types=3, floor=None)),
    (dict(base_shape="Walls", plate_shape="Circle"), dict(nodes=111, base=20, struts=290, types=7, floor=-1000.0)),
]
for kw, e in SHAPES:
    d = core.analyze(core.Params(**kw))
    tag = "{}".format(kw)
    check(not d.errors, tag + " errors {}".format(d.errors))
    if d.errors:
        continue
    check((d.n_nodes, d.n_base, d.n_struts, len(d.types)) == (e["nodes"], e["base"], e["struts"], e["types"]),
          tag + " counts {} {} {} {}".format(d.n_nodes, d.n_base, d.n_struts, len(d.types)))
    floor = e["floor"] if e["floor"] is not None else d.platform["z_floor"]
    check(abs(d.z_floor - floor) < 1e-9, tag + " floor {}".format(d.z_floor))
    check(abs(d.h_total - (d.p.R - floor)) < 1e-9, tag + " height")
    check(core.tenon_fit(d) < 1e-6, tag + " tenon fit {:.3g}".format(core.tenon_fit(d)))
    check(plate_intrusion(d) < 1e-9, tag + " board cuts into a plate by {:.3g}".format(plate_intrusion(d)))
    if d.feet:      # the boards stand in the platforms, the platforms on the floor
        check(lowest_part(d) > 0, tag + " lowest board {:.3g} above the floor".format(lowest_part(d)))
    else:
        check(abs(lowest_part(d)) < 1e-6, tag + " lowest part {:.3g} above the floor".format(lowest_part(d)))
    hubs = [k for k in range(d.n_nodes) if not d.socket[k]]
    ok = all(core.loops_closed(core.board_geometry(d, ti)["loops"]) for ti in range(len(d.types)))
    ok = ok and all(core.loops_closed(core.plate_geometry(d, k, inner)["loops"])
                    for k in hubs for inner in (False, True))
    check(ok, tag + " open loop")
    # every plate covers its bolt: the centre hole is inside the outline, above the floor cut
    for k in hubs:
        geo = core.plate_geometry(d, k)
        outline = core._loop_points(geo["loops"][0])
        ring = [(d.p.center_hole * math.cos(a / 8.0), d.p.center_hole * math.sin(a / 8.0)) for a in range(50)]
        inside = all(core._inside(outline if core._area(outline) > 0 and
                                  sum(outline[i][0] * outline[(i + 1) % len(outline)][1] -
                                      outline[(i + 1) % len(outline)][0] * outline[i][1]
                                      for i in range(len(outline))) > 0 else outline[::-1], q) for q in ring)
        check(inside and (geo["clip"] is None or geo["clip"] > d.p.center_hole), tag + " plate {} misses its bolt".format(k))
    placements, reps = core.plate_placements(d)
    rep_geo = {k: core.plate_geometry(d, n, inner) for k, (n, inner) in reps.items()}
    worst, i = 0.0, 0
    for n in hubs:
        for inner in (False, True):
            name, frame = placements[i]
            i += 1
            own = [world(core.plate_frame(d, n, inner), s[0]) for s in core.plate_geometry(d, n, inner)["slots"]]
            for s in rep_geo[name]["slots"]:
                worst = max(worst, min(math.dist(world(frame, s[0]), b) for b in own))
    check(worst < 1e-6, tag + " plate placement {:.3g}".format(worst))
    rows = core.bom(d)
    by = {}
    for r in rows:
        by[r["part"]] = by.get(r["part"], 0) + r["qty"]
    check(by.get("Board") == d.n_boards and by.get("Plate") == d.n_plates and by.get("Spacer", 0) == d.n_spacers,
          tag + " BOM totals")
    if d.shape == "Arches":
        part = "Platform" if d.model else "Hardware"
        check(any(r["part"] == part and r["type"] in ("F", "Foot shoe") and r["qty"] == 5 for r in rows), tag + " platforms")
        check(any(r["type"].endswith(" pin") and r["qty"] == 10 for r in rows) == (d.p.center_hole > 0), tag + " pins")
        if d.p.leg_length == 0:
            check(not any("sharpest angle" in w for w in d.warnings), tag + " auto legs keep the hubs small")
        else:
            check(any("sharpest angle" in w for w in d.warnings), tag + " tall legs warning")
        # five legs, each foot on exactly two long sides, neighbouring legs share a hub
        check(len(d.feet) == 5 and all(len(d.adj[f]) == 2 and d.socket[f] for f in d.feet), tag + " feet")
        tops = [m for f in d.feet for m, _t, _s in d.adj[f]]
        check(len(set(tops)) == 5 and all(tops.count(m) == 2 for m in set(tops)), tag + " shared hubs")
        # the platform: boards slide into the pockets without touching, rest on the seat, pin lines up
        pl, hits, seat = d.platform, 0, True
        for a, b, ti in pl["arms"]:
            t = d.types[ti]
            for off in d.p.board_offsets():
                o, X, Y, Z = core.board_frame(d, a, b, ti, off)
                for k in range(25):
                    x = t.x_cut - 1.2 * t.depth * k / 24.0
                    for y in (t.y_in, (t.y_in + t.y_out) / 2.0, t.y_out):
                        for z in (0.0, d.p.plywood):
                            q = tuple(o[i] + x * X[i] + y * Y[i] + z * Z[i] for i in range(3))
                            hits += core.csg_contains(pl["csg_world"], q, eps=1e-6)
                q = tuple(o[i] + (t.x_cut + 0.3 * d.p.plate) * X[i] + t.ym(t.x_cut) * Y[i] + d.p.plywood / 2.0 * Z[i]
                          for i in range(3))
                seat = seat and core.csg_contains(pl["csg_world"], q)
            if d.p.center_hole > 0:   # the pin hole of the board is the platform's pin hole
                hole = core.board_geometry(d, ti)["loops"][1][0]
                check(hole[0] == "C" and abs(hole[1][0] - t.x_pin) < 1e-9, tag + " board pin hole")
        check(hits == 0 and seat, tag + " platform: boards touch it in {} points, seat {}".format(hits, seat))
        lo, hi = pl["bbox"]
        check(abs(lo[2]) < 1e-9 and hi[2] > 0 and pl["volume"] > 0, tag + " platform on its base")
        # spacer tabs sit in their slots on the sloped leg boards too
        if d.p.boards_per_strut == 2:
            p, tab_h, dev = d.p, d.spacer_height / 2.0 - d.shoulder, 0.0
            for a, b, ti in d.struts:
                if d.types[ti].kind != "leg":
                    continue
                for x in core.board_geometry(d, ti)["spacers_x"]:
                    o, X, Y, Z = core.spacer_frame(d, a, b, ti, x)
                    for off, sx in zip(p.board_offsets(), (-1.0, 1.0)):
                        bf = core.board_frame(d, a, b, ti, off)
                        for lx in (sx * p.board_gap / 2.0, sx * (p.board_gap / 2.0 + p.plywood)):
                            for ly in (-tab_h, tab_h):
                                for lz in (0.0, p.plywood):
                                    q = core.to_frame(bf, tuple(o[i] + lx * X[i] + ly * Y[i] + lz * Z[i] for i in range(3)))
                                    dev = max(dev, abs(q[0] - x) - p.plywood / 2.0,
                                              abs(q[1] - d.types[ti].ym(x)) - tab_h, -q[2], q[2] - p.plywood)
            check(dev < 1e-6, tag + " leg spacer tab outside its slot by {:.3g}".format(dev))
    if d.shape == "Walls":
        check(any(r["type"] == "Wall sheathing" for r in rows), tag + " sheathing row")
        posts = [t for t in d.types if t.kind == "wall"]
        check(len(posts) == 1 and abs(posts[0].half_angle) < 1e-9 and abs(posts[0].phi_q) < 1e-9, tag + " posts square")
    print("{}: nodes {}, struts {}, types {}, plate types {}, r {:.0f}, sharpest {:.2f}, floor {:.0f}".format(
        d.name, d.n_nodes, d.n_struts, len(d.types), len(d.plate_types), d.r_node, math.degrees(d.alpha_min), d.z_floor))

# walls and arches as models 1:10, old parameter sets load as a hemisphere
for kw in (dict(base_shape="Walls", diameter=3000, frequency=2, model_scale=10, wall_height=800),):
    m = core.analyze(core.Params(**kw))
    check(not m.errors and core.tenon_fit(m) < 1e-6 and abs(lowest_part(m)) < 1e-6, "model {}".format(kw))
# the 3 m 2V arches model 1:10 prints on a 256 x 256 bed: every part fits
m = core.analyze(core.Params(base_shape="Arches", diameter=3000, frequency=2, model_scale=10))
check(not m.errors and not m.warnings, "arches model: {} {}".format(m.errors, m.warnings))
check(all(max(r["length"], r["width"]) <= 246 for r in core.bom(m) if r["part"] != "Hardware"), "arches model on the bed")
check(max(m.platform["size"]) < 246, "platform on the bed")
check(core.Params.from_dict({"diameter": 5000}).base_shape == "Hemisphere", "old presets load as a hemisphere")
check(core.analyze(core.Params(base_shape="Walls", wall_height=50)).errors, "low wall rejected")
check(core.analyze(core.Params(base_shape="Walls", wall_rows=5)).errors, "too many wall rows rejected")
check(core.analyze(core.Params(base_shape="Arches", leg_length=300)).errors, "short legs rejected")
check(core.analyze(core.Params(base_shape="Igloo")).errors, "unknown shape rejected")
check(core.analyze(core.Params(base_shape="Arches", frequency=2)).name == "Dome D6000 2V arches", "arches name")
check("On straight walls" in core.summary_html(core.analyze(core.Params(base_shape="Walls"))), "walls summary")

# ---------------------------------------------------------------- v1.0 checks
import re  # noqa: E402
import sheet_layout as sl  # noqa: E402

# sheets: 2500 x 1250 by default, margin and spacing checked
q = core.Params()
check((q.sheet_len, q.sheet_wid, q.sheet_margin, q.part_gap) == (2500.0, 1250.0, 10.0, 10.0), "sheet defaults")
check(core.Params(model_scale=10).effective().sheet_margin == 5.0, "model margin from the bed")
check(core.analyze(core.Params(sheet_margin=700)).errors, "margin larger than the sheet rejected")
check(core.analyze(core.Params(part_gap=-1)).errors, "negative spacing rejected")
check(core.analyze(core.Params(bed_len=0, model_scale=10)).errors, "zero bed rejected")
check(not core.analyze(core.Params(bed_len=0)).errors, "the bed is ignored for a real dome")

# Russian: the summary and every message the core produced in these checks
for kw in (dict(), dict(base_shape="Walls", wall_rows=2), dict(base_shape="Arches", leg_length=5200),
           dict(base_shape="Arches", frequency=2, diameter=3000, model_scale=10), dict(diameter=500),
           dict(frame_depth=0, plate=-1), dict(sheet_margin=700), dict(boards_per_strut=2, board_gap=2)):
    m = core.analyze(core.Params(**kw))
    ru = core.summary_html(m, "ru")
    check("Size" not in ru and ("Размеры" in ru or m.errors), "russian summary {}".format(kw))
    for msg in m.errors + m.warnings:
        tr = core.translate(msg, "ru")
        check(tr != msg and not re.search(r"\b(must|does not|the sheet|cannot)\b", tr),
              "untranslated: {} -> {}".format(msg, tr))
check(core.translate("Board A (1 x 2 mm) does not fit the sheet.", "en") ==
      "Board A (1 x 2 mm) does not fit the sheet.", "english stays")


def dxf_pairs(text):
    lines = text.split("\n")
    return [(lines[i].strip(), lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


# layout: every part of the build on a sheet (or listed as too big), inside the
# margin, the spacing kept, boards along the long side; one DXF per sheet
LAYOUT_CASES = [(dict(), "Full dome"), (dict(frequency=6), "Full dome"), (dict(boards_per_strut=1), "Full dome"),
                (dict(plate_shape="Circle"), "Full dome"), (dict(base_shape="Walls", wall_rows=2), "Full dome"),
                (dict(base_shape="Arches", frequency=2), "Full dome"),
                (dict(base_shape="Arches", frequency=2, diameter=3000, model_scale=10), "Full dome"),
                (dict(frequency=2, diameter=3000, model_scale=10), "Test hub"), (dict(), "Test hub"),
                (dict(sheet_len=1525, sheet_wid=1525, part_gap=12), "Full dome"),
                (dict(sheet_len=600, sheet_wid=400), "Full dome")]
for kw, mode in LAYOUT_CASES:
    m = core.analyze(core.Params(**kw))
    tag = "layout {} {}".format(kw, mode)
    parts = sl.flat_parts(m, mode)
    lay = sl.pack(parts, m.p.sheet_len, m.p.sheet_wid, m.p.sheet_margin, m.p.part_gap)
    problems = sl.check(lay)
    check(not problems, tag + ": " + "; ".join(problems[:3]))
    got = dict(lay.placed)
    for k, n in lay.misfit.items():
        got[k] = got.get(k, 0) + n
    check(got == {pt.key: pt.qty for pt in parts}, tag + " counts")
    check(all(pl.rot == 0 for s in lay.sheets for pl in s if pl.part.grain == "length"), tag + " grain")
    check(all(pl.rot in (0, 90) for s in lay.sheets for pl in s), tag + " turns")
    for k in lay.misfit:
        pt = next(x for x in parts if x.key == k)
        room = (lay.L - 2 * lay.margin, lay.W - 2 * lay.margin)
        check(pt.size[0] > room[0] or pt.size[1] > room[1], tag + " misfit really too big: " + k)
    if mode == "Full dome":
        rows = {r["part"] + " " + r["type"]: r["qty"] for r in core.bom(m)}
        for pt in parts:
            want = rows.get(pt.key) or rows.get("Spacer S")
            check(want == pt.qty, tag + " BOM qty " + pt.key)
    for i in range(min(len(lay.sheets), 3)):
        text = sl.sheet_dxf(lay, i)
        pairs = dxf_pairs(text)
        check(pairs[:4] == [("0", "SECTION"), ("2", "HEADER"), ("9", "$ACADVER"), ("1", "AC1009")], tag + " header")
        check(text.endswith("0\nENDSEC\n0\nEOF\n"), tag + " EOF")
        layers = {v for c, v in pairs if c == "8"}
        check(layers <= {"CUT", "HOLES", "TEXT", "SHEET"} and {"CUT", "SHEET", "TEXT"} <= layers, tag + " layers")
        n_cut = sum(1 for (c, v), (c2, v2) in zip(pairs, pairs[1:]) if (c, v) in (("0", "POLYLINE"), ("0", "CIRCLE"))
                    and (c2, v2) == ("8", "CUT"))
        check(n_cut == len(lay.sheets[i]), tag + " one outline per part")
        n_text = sum(1 for (c, v), (c2, v2) in zip(pairs, pairs[1:]) if (c, v) == ("0", "TEXT"))
        check(n_text >= len(lay.sheets[i]), tag + " every part labelled")
        check(text.count("SECTION") == text.count("ENDSEC") == 4, tag + " sections")
        check(all(ord(ch) < 128 for ch in text), tag + " ASCII")
m = core.analyze(core.Params(base_shape="Arches", frequency=2))
lay = sl.pack(sl.flat_parts(m), m.p.sheet_len, m.p.sheet_wid, m.p.sheet_margin, m.p.part_gap)
check(lay.misfit.get("Board C") == 20 and "Does not fit" in " ".join(sl.summary_lines(lay)),
      "6 m 2V arches: the long legs do not fit a sheet and are listed")
# a base plate cut at the floor: its outline is cut, nothing beyond the floor line
m = core.analyze(core.Params())
for pt in sl.flat_parts(m):
    if pt.outer[0] == "poly":
        n, inner = core.plate_placements(m)[1][pt.key.split()[1]]
        clip = core.plate_geometry(m, n, inner)["clip"]
        check(max(q[0] for q in pt.outer[1]) <= clip + 1e-6, "clipped outline " + pt.key)
        check(all(max(q[0] for q in h[1]) <= clip + 1e-6 for h in pt.holes if h[0] == "poly"), "clipped holes " + pt.key)

# a printed model: bold letters 8 mm and 1 mm deep, every plate carries one digit
# that fits clear of its slots and hole; the real dome keeps its names and 0.5 mm
check(core.Params().print_label_height == 8.0 and core.Params().print_label_depth == 1.0, "model label defaults")
MODEL_CASES = [dict(diameter=6000, frequency=4), dict(diameter=3000, frequency=2),
               dict(diameter=6000, frequency=6, base_shape="Walls", wall_height=1500),
               dict(diameter=3000, frequency=2, base_shape="Arches"), dict(diameter=6000, frequency=4, model_scale=20)]
for kw in MODEL_CASES:
    kw = dict(kw)
    kw.setdefault("model_scale", 10)
    m = core.analyze(core.Params(**kw))
    tag = "model labels {}".format(kw)
    check(not m.errors, tag + " errors {}".format(m.errors))
    check(sorted(m.plate_codes.values(), key=int) == [str(i + 1) for i in range(len(m.plate_types))], tag + " codes")
    check(core.label_style(m) == {"label_depth": 1.0, "label_bold": True}, tag + " style")
    placements, reps = core.plate_placements(m)
    for name, (n, inner) in reps.items():
        g = core.plate_geometry(m, n, inner)
        text, x, y, h = g["labels"][-1]
        check(text == m.plate_codes[name], tag + " {} carries {!r}".format(name, text))
        check(g["label_depth"] == 1.0 and g["label_bold"], tag + " {} style".format(name))
        w, t = 0.8 * h * len(text), 1.05 * h      # bold digits measured in Fusion: about 0.7 x 1.0 of h
        box = [(x - w / 2, y - t / 2), (x + w / 2, y - t / 2), (x + w / 2, y + t / 2), (x - w / 2, y + t / 2)]
        slots = [core._rect(ctr, ax, a, b) for ctr, ax, a, b in g["slots"]]
        check(not any(core._overlap(box, r) for r in slots), tag + " {} digit clear of the slots".format(name))
        nx, ny = max(box[0][0], min(0.0, box[1][0])), max(box[0][1], min(0.0, box[2][1]))
        check((nx * nx + ny * ny) ** 0.5 >= m.p.center_hole / 2.0, tag + " {} digit clear of the hole".format(name))
        if g["clip"] is not None:
            check(x + w / 2 <= g["clip"], tag + " {} digit above the floor".format(name))
        if kw["model_scale"] == 10:
            check(h >= 0.6 * m.p.label_height, tag + " {} digit {:.1f} mm".format(name, h))
    for ti, ty in enumerate(m.types):
        g = core.board_geometry(m, ti)
        check(g["label_depth"] == 1.0 and g["label_bold"], tag + " board style")
        if not g["labels"]:
            continue     # no room for any letter on this tiny board
        _letter, lx, _ly, lh = g["labels"][0]
        half = 0.55 * lh     # a bold capital is about as wide as tall: A measured 8.0 x 8.0 in Fusion
        gap = min([abs(lx - x) - (m.p.plywood / 2.0 + m.p.clearance) - half for x in g["spacers_x"]] or [9.9])
        check(gap >= 0.0, tag + " letter {} {:.1f} mm from a spacer slot".format(ty.letter, gap))
        check(ty.x_lo - 1e-6 <= lx - half and lx + half <= ty.x_hi + 1e-6 or lh <= 0.5 * m.p.label_height + 1e-6,
              tag + " letter {} between the hubs".format(ty.letter))
    html = core.summary_html(m, "ru")
    check("на модели цифрой: 1 = " in html, tag + " summary key")
    notes = {r["type"]: r["note"] for r in core.bom(m) if r["part"] == "Plate"}
    check(all(nt.startswith("digit {} on the model".format(m.plate_codes[k])) for k, nt in notes.items()),
          tag + " BOM notes")
    # one type per bed: every bed a single pile, nothing lost, still a valid layout
    parts = sl.flat_parts(m)
    lay = sl.pack(parts, m.p.sheet_len, m.p.sheet_wid, m.p.sheet_margin, m.p.part_gap, by_type=True)
    check(not sl.check(lay), tag + " per-type layout valid")
    check(all(len(sl.type_counts(sheet)) == 1 for sheet in lay.sheets), tag + " one type per bed")
    got = dict(lay.placed)
    for k, q in lay.misfit.items():
        got[k] = got.get(k, 0) + q
    check(got == {pt.key: pt.qty for pt in parts}, tag + " per-type counts")
    lines = sl.summary_lines(lay, "ru")
    check(lines[0].startswith("Столов") and any(ln.startswith("Пластины: 1 (") for ln in lines), tag + " bed list")
    check(" x" in sl.sheet_contents(lay, 0) and all(ch not in sl.sheet_contents(lay, i) for i in range(len(lay.sheets))
                                                    for ch in '\\/:*?"<>|'), tag + " bed names")
real = core.analyze(core.Params())
for name, (n, inner) in core.plate_placements(real)[1].items():
    g = core.plate_geometry(real, n, inner)
    check(g["labels"][-1][0] == name and g["label_depth"] == core.LABEL_DEPTH and not g["label_bold"],
          "real dome plate keeps its name " + name)
check(core.part_title(real, "Plate H6a") == "Plate H6a" and "digit" not in core.summary_html(real), "real titles")
mm = core.analyze(core.Params(model_scale=10))
check(core.part_title(mm, "Plate H6a") == "Plate 2 (H6a)" and core.part_title(mm, "Plate H6a outer") ==
      "Plate 2 (H6a) outer" and core.part_title(mm, "Board A") == "Board A", "model titles")
bad = core.analyze(core.Params(model_scale=10, print_label_depth=3.0))
check(any("label depth" in e for e in bad.errors) and
      "Глубина букв модели должна быть меньше" in core.translate(bad.errors[0], "ru"), "label depth check")
old = core.Params().to_dict()
old.pop("print_label_depth")
old["print_label_height"] = 5.0
check(core.Params.from_dict(old).print_label_height == 8.0, "old 5 mm letters grow to the new default")

if failures:
    print("\nFAILED:")
    for m in failures:
        print("  - " + m)
    sys.exit(1)
print("\nAll checks passed.")
