"""Prepare the NIOSH medium digital headform for the EpiProt headband CAD.

Source: NIOSH Anthropometric Digital Headforms (NIOSH National Personal Protective Technology Laboratory,
NPPTL), as published with a base on the NIH 3D Print Exchange, entry 3DPX-015142 "NIOSH Anthropometric
Digital Headforms with Base" by tprestero (CC-BY). File: "medium with base.stl" (inches).

Writes, next to this script:
  headform_<size>_mm.stl   binary STL in mm, EpiProt axes: x = patient's right, y = forward, z = up,
                           origin midway between the two auricle centres
  landmarks_<size>.json         ear centres / tops, back of the head, occipital bump, mastoid points behind the ears,
                           neck, head circumference - all measured on the mesh

Usage: python device-firmware/cad/headform/prepare_headform.py <path to "<size> with base.stl"> <size>
  sizes used: small, medium, large, longnarrow, shortwide (NIH 3D entry 3DPX-015142, same licence)
  child: the small headform scaled to a 505 mm head circumference (about 6-8 years), an approximation:
         python prepare_headform.py "small with base.stl" child 0.958
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def read_stl(path):
    b = open(path, "rb").read()
    n = int.from_bytes(b[80:84], "little")
    a = np.frombuffer(b[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return a["v"].astype(np.float64)                       # (n, 3, 3)


def write_stl(path, tris):
    n = len(tris)
    nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    rec = np.zeros(n, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = nrm, tris
    with open(path, "wb") as f:
        f.write(b"EpiProt headform (NIOSH medium, mm)".ljust(80, b" "))
        f.write(np.uint32(n).tobytes())
        f.write(rec.tobytes())


def main(src, size="medium", scale=1.0):
    t = read_stl(src)
    if np.ptp(t[..., 1]) < 50:                             # the medium file is in inches, the others in mm
        t = t * 25.4
    # NIOSH file: y = up, z = forward (nose at +z), x = lateral. Patient's right = forward x up = -x.
    t = np.stack([-t[..., 0], t[..., 2], t[..., 1]], axis=-1)
    # child size: a uniformly scaled adult head (approximation: real children have a larger cranium for their
    # face and a shorter neck); NIOSH has no child headforms
    t = t * scale
    v = np.unique(t.reshape(-1, 3), axis=0)
    xc = (v[:, 0].min() + v[:, 0].max()) / 2              # the headform is symmetric: centre it sideways
    t[..., 0] -= xc
    v[:, 0] -= xc
    # auricles (outer ears): they stand out beyond the skull. Ear tip = most lateral point above the shoulders;
    # skull half-width = widest point 40-70 mm above it; auricle = points more than 1.5 mm beyond the skull.
    zmin_head = v[:, 2].min() + 0.35 * np.ptp(v[:, 2])     # above the shoulders
    ears, aur = {}, {}
    for side, sgn in (("right", 1), ("left", -1)):
        hv = v[v[:, 2] > zmin_head]
        z_tip = hv[np.argmax(hv[:, 0] * sgn), 2]
        skull = hv[(hv[:, 2] > z_tip + 40) & (hv[:, 2] < z_tip + 70)]
        thr = (skull[:, 0] * sgn).max() + 1.5
        cand = hv[(hv[:, 0] * sgn > thr) & (np.abs(hv[:, 2] - z_tip) < 45)]
        aur[side] = cand
        ears[side] = np.array([np.median(cand[:, 0]), (cand[:, 1].min() + cand[:, 1].max()) / 2,
                               (cand[:, 2].min() + cand[:, 2].max()) / 2])
    origin = (ears["right"] + ears["left"]) / 2
    origin[0] = 0.0
    t -= origin
    v -= origin
    for k in ears:
        ears[k] = ears[k] - origin
    write_stl(os.path.join(HERE, f"headform_{size}_mm.stl"), t)
    v = v[v[:, 2] > -150]                                  # no shoulders / base

    def band(zlo, zhi):
        return v[(v[:, 2] > zlo) & (v[:, 2] < zhi)]

    lm = {"ear_right": ears["right"], "ear_left": ears["left"]}
    for side, sgn in (("right", 1), ("left", -1)):
        a_ = aur[side] - origin
        lm[f"ear_top_{side}"] = a_[np.argmax(a_[:, 2])]
        lm[f"ear_bottom_{side}"] = a_[np.argmin(a_[:, 2])]
        lm[f"ear_back_{side}"] = a_[np.argmin(a_[:, 1])]
        lm[f"ear_front_{side}"] = a_[np.argmax(a_[:, 1])]
    mid = v[np.abs(v[:, 0]) < 4]
    back = mid[mid[:, 1] < 0]
    lm["head_top"] = mid[np.argmax(mid[:, 2])]
    up = back[back[:, 2] > -10]
    lm["back_of_head"] = up[np.argmin(up[:, 1])]
    for dz, nm in ((-20, "nape_top"), (-45, "neck_back_upper"), (-70, "neck_back")):
        s_ = back[np.abs(back[:, 2] - dz) < 2.5]
        if len(s_):
            lm[nm] = s_[np.argmin(s_[:, 1])]
    # mastoid skin behind each auricle (not on the ear itself): 8 mm behind the ear's back edge
    for side, sgn in (("right", 1), ("left", -1)):
        yb = lm[f"ear_back_{side}"][1] - 8
        for nm, dz in (("upper", 6), ("lower", -14)):
            zt = ears[side][2] + dz
            s_ = v[(np.abs(v[:, 1] - yb) < 2.5) & (np.abs(v[:, 2] - zt) < 2.5) & (v[:, 0] * sgn > 30)]
            if len(s_):
                lm[f"mastoid_{nm}_{side}"] = s_[np.argmax(s_[:, 0] * sgn)]
    # head circumference: largest convex-hull perimeter of 2 mm slices above the ears (tape-measure style)
    def cross(o, a_, b_):
        return (a_[0] - o[0]) * (b_[1] - o[1]) - (a_[1] - o[1]) * (b_[0] - o[0])

    def hull_perimeter(pts2):
        pts2 = sorted(map(tuple, np.unique(np.round(pts2, 2), axis=0)))

        def half(seq):
            h = []
            for q in seq:
                while len(h) >= 2 and cross(h[-2], h[-1], q) <= 0:
                    h.pop()
                h.append(q)
            return h
        hull = np.array(half(pts2)[:-1] + half(pts2[::-1])[:-1])
        return float(np.linalg.norm(np.diff(np.vstack([hull, hull[:1]]), axis=0), axis=1).sum())
    circ, z_circ = max((hull_perimeter(band(z - 1, z + 1)[:, :2]), z) for z in range(int(lm['ear_top_right'][2]) + 8, 90, 2))   # above the auricle tops
    out = {k: [round(float(x), 1) for x in val] for k, val in lm.items()}
    out["head_circumference_mm"] = round(circ, 0)
    out["head_circumference_height_mm"] = z_circ
    out["head_breadth_mm"] = round(float(np.ptp(band(z_circ - 1, z_circ + 1)[:, 0])), 0)
    out["ear_height_mm"] = round(float(lm["ear_top_right"][2] - lm["ear_bottom_right"][2]), 0)
    out["head_length_mm"] = round(float(np.ptp(band(z_circ - 1, z_circ + 1)[:, 1])), 0)
    out["source"] = (f"NIOSH {size} digital headform (NIOSH NPPTL), via NIH 3D Print Exchange 3DPX-015142 by "
                     "tprestero, CC-BY. Converted to mm and EpiProt axes.")
    json.dump(out, open(os.path.join(HERE, f"landmarks_{size}.json"), "w"), indent=1)
    for k2, val in out.items():
        print(k2, val)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "medium", float(sys.argv[3]) if len(sys.argv) > 3 else 1.0)
