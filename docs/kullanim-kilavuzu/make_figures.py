"""Labelled pictures of the headband for the user manual (from the Blender renders).

python docs/kullanim-kilavuzu/make_figures.py   (needs matplotlib, e.g. the epiprot-gbm Docker image)
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "..", "..", "device-firmware", "cad", "render")
TEAL, CORAL = "#075E66", "#B0302A"


def label(png, out, items, crop=None):
    img = mpimg.imread(os.path.join(RENDER, png))
    if crop:
        x0, y0, x1, y1 = crop
        img = img[y0:y1, x0:x1]
    else:
        x0 = y0 = 0
    h, w = img.shape[:2]
    fig = plt.figure(figsize=(w / 200, h / 200), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img)
    ax.axis("off")
    for n, (text, (px, py), (tx, ty)) in enumerate(items, start=1):
        px, py, tx, ty = px - x0, py - y0, tx - x0, ty - y0
        ax.annotate(f"{n}  {text}", xy=(px, py), xytext=(tx, ty), fontsize=9, fontweight="bold", color="white",
                    ha="left", va="center",
                    bbox=dict(boxstyle="round,pad=0.35", fc=TEAL, ec="none"),
                    arrowprops=dict(arrowstyle="-|>", color=CORAL, lw=1.6, shrinkA=0, shrinkB=2))
    fig.savefig(os.path.join(HERE, out), dpi=200)
    plt.close(fig)


LABELS = {
    "tr": {"hook": "Kulak kancası", "module": "Elektrot modülü (pedler içte)", "battery": "Pil kutusu (sağ)",
           "contacts": "Şarj kontakları", "band": "Ense bandı", "light": "Işık", "button": "Tuş",
           "electronics": "Elektronik kutusu (sol)", "clasp": "Güvenlik klipsi", "upper": "Üst ped", "lower": "Alt ped",
           "small": "Küçük ped (referans)", "cell": "Pil", "suffix": ""},
    "en": {"hook": "Ear hook", "module": "Electrode module (pads inside)", "battery": "Battery case (right)",
           "contacts": "Charging contacts", "band": "Neck band", "light": "Light", "button": "Button",
           "electronics": "Electronics case (left)", "clasp": "Safety clasp", "upper": "Upper pad", "lower": "Lower pad",
           "small": "Small pad (reference)", "cell": "Battery", "suffix": "_en"},
}
for L in LABELS.values():
    label("epiprot_side.png", f"parcalar_yan{L['suffix']}.png", [
        (L["hook"], (925, 515), (1050, 380)),
        (L["module"], (790, 640), (930, 700)),
        (L["battery"], (745, 860), (900, 900)),
        (L["contacts"], (737, 932), (850, 1010)),
        (L["band"], (640, 832), (300, 760)),
    ], crop=(250, 300, 1450, 1100))
    label("epiprot_hero.png", f"parcalar_arka{L['suffix']}.png", [
        (L["light"], (608, 822), (250, 700)),
        (L["button"], (605, 858), (250, 800)),
        (L["electronics"], (630, 900), (250, 920)),
        (L["clasp"], (866, 815), (900, 960)),
        (L["battery"], (995, 760), (1080, 660)),
        (L["hook"], (455, 455), (250, 430)),
    ], crop=(200, 350, 1400, 1050))
    label("epiprot_xray.png", f"parcalar_ic{L['suffix']}.png", [
        (L["upper"], (870, 225), (1050, 180)),
        (L["lower"], (845, 400), (1050, 330)),
        (L["small"], (825, 550), (1050, 480)),
        (L["cell"], (740, 850), (1000, 820)),
    ], crop=(300, 0, 1500, 1200))
print("figures written")
