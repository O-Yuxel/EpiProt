"""Pictures of the three headband concepts (from concepts_mesh.npz, written by concepts.py).

Usage (needs matplotlib, e.g. the epiprot-gbm Docker image):
  python device-firmware/cad/render_concepts.py
"""
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
COL = {"head": "#e9cdb6", "band": "#0e7c86", "pads": "#7d8b8d", "pods": "#d9483b", "inside": "#f2c14e"}
NAMES = {"A": "A  One pod at the nape", "B": "B  Split behind the ears", "C": "C  Thin nape pod + battery in the band",
         "D": "D  Two pods at the lower back corners"}
LIGHT = np.array([0.3, -0.6, 0.75]) / np.linalg.norm([0.3, -0.6, 0.75])


def tris(v, f):
    return v[f]


def shade(t, base):
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
    k = 0.55 + 0.45 * np.clip(np.abs(n @ LIGHT), 0, 1)
    rgb = np.array(matplotlib.colors.to_rgb(base))
    return np.clip(rgb[None] * k[:, None], 0, 1)


def draw(ax, z, concept, elev, azim, pillow=None, show_head=True):
    if show_head:
        t = tris(z["head_v"], z["head_f"])
        ax.add_collection3d(Poly3DCollection(t, facecolors=shade(t, COL["head"]), linewidths=0, alpha=0.7))
    for key in z.files:
        if not key.startswith(concept + "|") or not key.endswith("_v"):
            continue
        role = key.split("|")[1]
        if role == "inside":
            continue
        t = tris(z[key], z[key[:-2] + "_f"])
        ax.add_collection3d(Poly3DCollection(t, facecolors=shade(t, COL[role]), linewidths=0, alpha=1.0))
    if pillow is not None:
        axis, val = pillow
        g = np.linspace(-130, 130, 2)
        A, B = np.meshgrid(g, g)
        if axis == "y":
            ax.plot_surface(A, np.full_like(A, val), B, color="#9db8d9", alpha=0.35, linewidth=0)
        else:
            ax.plot_surface(np.full_like(A, val), A, B, color="#9db8d9", alpha=0.35, linewidth=0)
    ax.set_xlim(-105, 105); ax.set_ylim(-125, 85); ax.set_zlim(-120, 70)
    ax.set_box_aspect((210, 210, 190))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()


def main():
    z = np.load(os.path.join(HERE, "concepts_mesh.npz"))
    m = json.load(open(os.path.join(HERE, "concepts_metrics.json")))
    yback = -5 - 98
    fig = plt.figure(figsize=(15, 20), dpi=100)
    cols = [("From behind, slightly from the left", dict(elev=18, azim=-125)),
            ("Lying on the back: seen from the right side, pillow behind the head", dict(elev=0, azim=0, pillow=("y", yback + 25))),
            ("Lying on the right side: seen from behind, pillow on the right", dict(elev=0, azim=-90, pillow=("x", 76 - 25)))]
    for r, k in enumerate("ABCD"):
        for c, (title, kw) in enumerate(cols):
            ax = fig.add_subplot(4, 3, r * 3 + c + 1, projection="3d")
            draw(ax, z, k, **kw)
            if c == 0:
                ax.text2D(0.0, 1.02, NAMES[k], transform=ax.transAxes, fontsize=13, weight="bold")
            if r == 0:
                ax.set_title(title, fontsize=11, pad=18)
            if c == 1:
                ax.text2D(0.05, -0.02, f"presses into pillow: {m[k]['supine_pressure_mm']} mm", transform=ax.transAxes, fontsize=10)
            if c == 2:
                ax.text2D(0.05, -0.02, f"presses into pillow: {m[k]['side_pressure_mm']} mm", transform=ax.transAxes, fontsize=10)
    fig.text(0.5, 0.01, "teal = elastic band, grey = semi-dry pads, red = electronics / battery pods.  "
             "Pillow (blue): the head sinks ~25 mm; a pod beyond that line presses on the skin.", ha="center", fontsize=10)
    out = os.path.join(HERE, "concepts.png")
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


main()
