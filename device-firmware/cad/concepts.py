"""EpiProt headband - three layout concepts (FreeCAD, run with freecadcmd).

Simplified average adult head (mm): x = to the patient's right, y = forward, z = up, ear canal at z = 0.
Real component sizes from HARDWARE.md; enclosure walls 1.5 mm, soft silicone over everything.

  A  one pod at the nape (all electronics + 700 mAh battery), low under the back of the head
  B  split behind the ears: electronics behind the left ear, battery behind the right ear
  C  thin nape pod (electronics only) + the battery split into two flat cells in the band behind the ears
  D  two pods at the lower back corners of the head (between nape and ear): electronics left, battery right;
     the zones the pillow loads least when lying on the back and on the side

Writes concepts.FCStd (open it in FreeCAD) and concepts_mesh.npz (for the pictures, render_concepts.py)
and prints simple numbers: thickness, how far each pod stands off the skin where the pillow presses when
lying on the back / on the side, and an estimated weight.

Usage: "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" device-firmware/cad/concepts.py
"""
import json
import math
import os

import FreeCAD as App
import numpy as np
import Part
from FreeCAD import Vector as V

OUT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- head (average adult)
HEAD_C, HEAD_R = V(0, -5, 20), (76.0, 98.0, 105.0)        # cranium ellipsoid centre / radii


def head_shape():
    s = Part.makeSphere(1.0)
    m = App.Matrix()
    m.scale(*HEAD_R)
    cran = s.transformGeometry(m).translated(HEAD_C)
    neck = Part.makeCylinder(52, 140, V(0, -22, -170), V(0, 0, 1))
    ears = [Part.makeCylinder(16, 14, V(sx * 70, 2, 0), V(sx, 0, 0)).transformGeometry(_scale_z(1.9, 0))
            for sx in (-1, 1)]
    return cran.fuse([neck] + ears).removeSplitter()


def _scale_z(f, z0):
    m = App.Matrix()
    m.move(V(0, 0, -z0)); m.scale(1, 1, f); m.move(V(0, 0, z0))
    return m


def head_y_back(x, z):
    """y of the back surface of the cranium at (x, z) (None outside)."""
    t = 1 - (x / HEAD_R[0]) ** 2 - ((z - HEAD_C.z) / HEAD_R[2]) ** 2
    return None if t <= 0 else HEAD_C.y - HEAD_R[1] * math.sqrt(t)


def head_x_side(y, z):
    t = 1 - ((y - HEAD_C.y) / HEAD_R[1]) ** 2 - ((z - HEAD_C.z) / HEAD_R[2]) ** 2
    return None if t <= 0 else HEAD_R[0] * math.sqrt(t)


# ---------------------------------------------------------------- parts
def rounded_box(lx, ly, lz, r=3.0):
    b = Part.makeBox(lx, ly, lz, V(-lx / 2, -ly / 2, -lz / 2))
    try:
        return b.makeFillet(min(r, min(lx, ly, lz) / 2 - 0.1), b.Edges)
    except Exception:
        return b


def place_on_back(shape, x, z, gap=1.0, tilt=True):
    """Put a part (thickness along its local y) onto the back of the head at (x, z)."""
    yb = head_y_back(x, z)
    yb = yb if yb is not None else -80.0
    bb = shape.BoundBox
    s = shape.copy()
    if tilt:                                                   # follow the curve of the head a little
        ang = math.degrees(math.atan2(x, HEAD_R[0])) * 0.6
        s.rotate(V(0, 0, 0), V(0, 0, 1), -ang)
    return s.translated(V(x, yb - gap - bb.YMax, z))


def place_on_side(shape, sx, y, z, gap=1.0):
    """Put a part (thickness along local x after rotation) onto the side of the head behind the ear."""
    xs = head_x_side(y, z) or 70.0
    s = shape.copy()
    s.rotate(V(0, 0, 0), V(0, 0, 1), 90)                       # local y -> x
    bb = s.BoundBox
    off = (xs + gap - bb.XMin) if sx > 0 else (-xs - gap - bb.XMax)
    return s.translated(V(off, y, z))


def band(z_mid=-12, width=16, thick=3.0, a0=-112, a1=112, n=56):
    """Elastic band around the back of the head, from behind one ear to behind the other."""
    segs = []
    for i in range(n):
        t0, t1 = math.radians(a0 + (a1 - a0) * i / n), math.radians(a0 + (a1 - a0) * (i + 1) / n)
        p0 = V(HEAD_R[0] * math.sin(t0) * 1.02, HEAD_C.y - HEAD_R[1] * math.cos(t0) * 0.93 * 1.02, z_mid)
        p1 = V(HEAD_R[0] * math.sin(t1) * 1.02, HEAD_C.y - HEAD_R[1] * math.cos(t1) * 0.93 * 1.02, z_mid)
        d = p1 - p0
        L = d.Length
        b = Part.makeBox(L, thick, width, V(0, -thick / 2, -width / 2))
        b.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(math.atan2(d.y, d.x)))
        segs.append(b.translated(p0))
    return segs[0].fuse(segs[1:]).removeSplitter()


def pads():
    out = []
    for sx in (-1, 1):
        for (y, z) in ((-14, -6), (-20, -30)):                 # upper / lower mastoid
            out.append(place_on_side(Part.makeCylinder(11, 4, V(0, -2, 0), V(0, 1, 0)).rotated(V(0, 0, 0), V(0, 0, 1), 0), sx, y, z, 0.2))
    return out


def concept(name):
    parts = {"band": [band()], "pads": pads()}
    pcb = Part.makeBox(40, 1.6, 26, V(-20, -0.8, -13))
    batt = Part.makeBox(50, 6, 34, V(-25, -3, -17))            # 700 mAh LiPo
    if name == "A":
        pod = rounded_box(58, 13, 42, 5)
        pod_p = place_on_back(pod, 0, -48, tilt=False)
        c = pod_p.BoundBox.Center
        parts["pods"] = [pod_p]
        parts["inside"] = [pcb.translated(c + V(0, 4.5, 0)), batt.translated(c + V(0, -1.5, 0))]
    elif name == "B":
        podL = rounded_box(30, 9, 42, 4)
        podR = rounded_box(38, 10, 54, 4)
        pl = place_on_side(podL, -1, -36, -24)
        pr = place_on_side(podR, 1, -36, -24)
        parts["pods"] = [pl, pr]
        cl, cr = pl.BoundBox.Center, pr.BoundBox.Center
        parts["inside"] = [Part.makeBox(1.6, 24, 38, V(-0.8, -12, -19)).translated(cl),
                           Part.makeBox(6, 34, 50, V(-3, -17, -25)).translated(cr)]
    elif name == "D":
        podL = rounded_box(32, 9, 34, 4)
        podR = rounded_box(38, 10, 52, 4)
        pl = place_on_back(podL, -44, -42)
        pr = place_on_back(podR, 44, -46)
        parts["pods"] = [pl, pr]
        parts["inside"] = [Part.makeBox(26, 1.6, 30, V(-13, -0.8, -15)).translated(pl.BoundBox.Center),
                           Part.makeBox(34, 6, 50, V(-17, -3, -25)).translated(pr.BoundBox.Center)]
    else:                                                      # C
        pod = rounded_box(46, 8, 32, 4)
        pod_p = place_on_back(pod, 0, -46, tilt=False)
        cells = [place_on_side(rounded_box(30, 8, 38, 4), sx, -42, -26) for sx in (-1, 1)]
        parts["pods"] = [pod_p] + cells
        parts["inside"] = [pcb.translated(pod_p.BoundBox.Center)] + \
                          [Part.makeBox(5, 26, 34, V(-2.5, -13, -17)).translated(c.BoundBox.Center) for c in cells]
    return parts


def metrics(parts):
    """Stand-off of the pods from the skin in the pillow zones, thickness, weight."""
    sup, side, thick = 0.0, 0.0, 0.0
    yback = HEAD_C.y - HEAD_R[1]                               # most posterior point of the head
    for p in parts["pods"]:
        bb = p.BoundBox
        x, z = bb.Center.x, bb.Center.z
        # lying on the back: the head sinks ~25 mm into the pillow; anything behind (yback + 25) presses
        sup = max(sup, (yback + 25.0) - bb.YMin)
        # lying on the side: same with the side of the head (xside ~ 76 mm)
        xs = head_x_side(bb.Center.y, bb.Center.z) or HEAD_R[0]      # side of the head at the pod's height
        side = max(side, max(abs(bb.XMin), abs(bb.XMax)) - (HEAD_R[0] - 25.0) - max(0.0, HEAD_R[0] - xs))
        thick = max(thick, min(bb.XLength, bb.YLength, bb.ZLength))
    vol = sum(p.Volume for p in parts["pods"]) - sum(p.Volume for p in parts["inside"])
    weight = 0.0011 * vol + 13.0 + 6.0 + 4.0 + 0.0011 * parts["band"][0].Volume   # silicone + battery + PCB/parts + pads
    return {"supine_pressure_mm": round(max(sup, 0.0), 1), "side_pressure_mm": round(max(side, 0.0), 1),
            "max_thickness_mm": round(thick, 1), "weight_g": round(weight, 0)}


def mesh(shape, tol=1.2):
    v, f = shape.tessellate(tol)
    return np.array([[p.x, p.y, p.z] for p in v], np.float32), np.array(f, np.int32)


def main():
    doc = App.newDocument("EpiProtConcepts")
    head = head_shape()
    store = {}
    hv, hf = mesh(head, 2.5)
    store["head_v"], store["head_f"] = hv, hf
    doc.addObject("Part::Feature", "Head").Shape = head
    res = {}
    for k in "ABCD":
        parts = concept(k)
        res[k] = metrics(parts)
        grp = doc.addObject("App::DocumentObjectGroup", f"Concept_{k}")
        for role, shapes in parts.items():
            for i, s in enumerate(shapes):
                o = doc.addObject("Part::Feature", f"{k}_{role}_{i}")
                o.Shape = s
                grp.addObject(o)
                v, f = mesh(s)
                store[f"{k}|{role}|{i}_v"], store[f"{k}|{role}|{i}_f"] = v, f
    doc.saveAs(os.path.join(OUT, "concepts.FCStd"))
    np.savez_compressed(os.path.join(OUT, "concepts_mesh.npz"), **store)
    json.dump(res, open(os.path.join(OUT, "concepts_metrics.json"), "w"), indent=1)
    for k, r in res.items():
        print(k, r)


main()
