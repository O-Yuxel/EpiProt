"""Where on the real head can the two pods sit without touching the pillow?

For every candidate pod centre (angle around the head from the back centre, height) the pod is laid on the
skin (gap + thickness along the skin normal, footprint w x h on the tangent plane). It then checks
  * lying on the back: the head sinks SINK mm into the pillow, so the pillow surface is the plane SINK mm in
    front of the most posterior skin point; how deep does the pod reach beyond that plane?
  * lying on the side (same side as the pod): same with the most lateral skin point (the ear).
0 mm = the pod does not reach the pillow. Uses the NIOSH medium headform (headform_medium_mm.stl).

Usage: python device-firmware/cad/headform/pod_placement_study.py   (numpy only; writes pod_placement.json)
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SINK = 20.0                              # mm the head sinks into a normal pillow (conservative; foam: more)
GAP = 2.5


def load():
    b = open(os.path.join(HERE, "headform_medium_mm.stl"), "rb").read()
    n = int.from_bytes(b[80:84], "little")
    a = np.frombuffer(b[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    t = a["v"].astype(float)
    return t[t[:, :, 2].max(1) > -110]


T = load()
E1, E2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]


def hit(o, d):
    d = d / np.linalg.norm(d)
    pv = np.cross(d, E2)
    det = (E1 * pv).sum(1)
    ok = np.abs(det) > 1e-9
    inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
    tv = o - T[:, 0]
    u = (tv * pv).sum(1) * inv
    qv = np.cross(tv, E1)
    v = (d * qv).sum(1) * inv
    dist = (E2 * qv).sum(1) * inv
    m = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (dist > 0)
    if not m.any():
        return None, None
    i = np.flatnonzero(m)[np.argmin(dist[m])]
    nrm = np.cross(E1[i], E2[i]); nrm /= np.linalg.norm(nrm)
    if nrm @ d > 0:
        nrm = -nrm
    return o + d * dist[i], nrm


def around(theta, z):
    t = math.radians(theta)
    d = np.array([math.sin(t), -math.cos(t), 0.0])
    return hit(np.array([0, -15.0, z]) + d * 250, -d)


def pod_points(theta, z, w, h, t):
    q, n = around(theta, z)
    if q is None:
        return None
    up = np.array([0, 0, 1.0]) - n * n[2]; up /= np.linalg.norm(up)
    side = np.cross(n, up)
    pts = []
    for a in np.linspace(-0.5, 0.5, 5):
        for b in np.linspace(-0.5, 0.5, 5):
            c = q + side * a * w + up * b * h
            sq, sn = hit(c + n * 60, -n)                  # skin under this footprint point
            base = sq if sq is not None else c
            pts.append(base + n * (GAP + t))               # outer face of the pod
    return np.array(pts)


def main():
    v = T.reshape(-1, 3)
    head = v[v[:, 2] > -110]
    y_back, x_side = head[:, 1].min(), head[:, 0].max()
    pods = {"right_battery": (38, 56, 9.5, 1), "left_electronics": (30, 36, 8.5, -1)}
    res = {}
    for name, (w, h, t, sx) in pods.items():
        rows = []
        for th in range(35, 80, 5):
            for z in range(-35, 6, 5):
                p = pod_points(sx * th, z, w, h, t)
                if p is None:
                    continue
                back = max(0.0, float((y_back + SINK) - p[:, 1].min()))
                side = max(0.0, float(p[:, 0].max() * sx - (x_side - SINK)))
                rows.append({"angle": th, "z": z, "back_mm": round(back, 1), "side_mm": round(side, 1)})
        res[name] = rows
        best = sorted(rows, key=lambda r: (max(r["back_mm"], r["side_mm"]), r["back_mm"] + r["side_mm"]))[:5]
        print(name, "best:", best)
    json.dump({"sink_mm": SINK, "results": res}, open(os.path.join(HERE, "pod_placement.json"), "w"), indent=0)


if __name__ == "__main__":
    main()
