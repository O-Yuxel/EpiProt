"""EpiProt headband v3 - spring wire, clamping force on five head sizes, fit, staying on, comfort.

Input: device_geometry.json (written by ../epiprot_headband.FCMacro: nape band centreline, pad positions and
normals, ear-hook seat, pod inner faces, weight) and the five NIOSH headforms + landmarks in this folder.
Output: mechanics_results.json and a short printout. numpy only.

1. Spring. The nape band is a nitinol wire in soft silicone. The side bodies (module + pod, rigid carriers) act as
   rigid levers from where the band leaves the pod to the pads. Unit-load method (Castigliano) on the real 3D
   band centreline: the lateral pad displacement per newton of lateral pad force, bending + torsion, half band
   clamped at the back centre (symmetry). Silicone adds <1 % stiffness (E ~ 3 MPa) and is ignored.
2. Five heads. The pad spread on each NIOSH head (mastoid width) sets how far the band is opened -> force and
   pad pressure per head.
3. Fit. The device sits on the ear roots with its hooks, so on each head it is moved by that head's ear-top
   position: do the pads land on that head's mastoids, do the pods keep off its skin?
4. Staying on and comfort: inertial loads (walking, running, convulsion, fall) against what holds the device
   (hooks, nape band, friction at the pads), hook pressure on the ear root, pad pressure.

Usage: python device-firmware/cad/headform/mechanics.py
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = ["small", "medium", "large", "longnarrow", "shortwide"]
G = 9.81

# materials (typical datasheet values; nitinol: superelastic Ti-50.8Ni, austenite at skin temperature)
NITINOL = {"E": 60e3, "nu": 0.33, "linear_limit_MPa": 450.0, "recoverable_strain": 0.06}   # MPa
STEEL = {"E": 200e3, "nu": 0.30, "linear_limit_MPa": 1100.0, "recoverable_strain": 0.0055}  # music wire, for comparison
BETA_TI = {"E": 105e3, "nu": 0.33, "linear_limit_MPa": 900.0, "recoverable_strain": 0.0086}  # Ti-11.5Mo-6Zr-4.5Sn (TMA /
# beta-titanium: orthodontic wires, eyewear frames); nickel-free; yield ~1100-1200 MPa, 900 used as the allowable
DONNING_MM = 6.0             # extra opening per side to slide the pads over the head when putting it on
HOOK_WIRE_MM = 1.0           # separate, thinner beta-titanium wire in the ear hooks (soft release, see below)
HOOK_CONTACT_MM2 = 6.0 * 0.7 * 26     # flat 6 mm hook underside, ~70 % in contact along ~26 mm of ear root
CLASP_OPEN_N = 5.0           # magnetic breakaway clasp at the nape opens at this pull
MU_PAD_SKIN = 0.3            # silicone/hydrogel pad on skin, deliberately low (sweaty skin); dry skin is 0.5-1.0
TARGET_N = 1.5               # lateral clamping force per side on the medium head


def load_stl(name):
    b = open(os.path.join(HERE, f"headform_{name}_mm.stl"), "rb").read()
    n = int.from_bytes(b[80:84], "little")
    a = np.frombuffer(b[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    t = a["v"].astype(float)
    return t[t[:, :, 2].max(1) > -140]


class Head:
    def __init__(self, name):
        self.name = name
        self.t = load_stl(name)
        self.e1, self.e2 = self.t[:, 1] - self.t[:, 0], self.t[:, 2] - self.t[:, 0]
        self.lm = json.load(open(os.path.join(HERE, f"landmarks_{name}.json")))

    def gap(self, p, n):
        """Distance from p to the skin along -n (negative: p is inside the head)."""
        o, d = p + n * 30, -n / np.linalg.norm(n)
        pv = np.cross(d, self.e2)
        det = (self.e1 * pv).sum(1)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
        tv = o - self.t[:, 0]
        u = (tv * pv).sum(1) * inv
        qv = np.cross(tv, self.e1)
        v = (d * qv).sum(1) * inv
        dist = (self.e2 * qv).sum(1) * inv
        m = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (dist > 0)
        return None if not m.any() else float(dist[m].min() - 30)

    def mastoid_half_width(self):
        return np.mean([abs(self.lm[f"mastoid_{k}_{s}"][0]) for k in ("upper", "lower") for s in ("right", "left")])


def compliance(band, i0, i1, pad, e, EI, GJ):
    """Lateral displacement of the pad per newton (mm/N): band from index i0 (leaves the pod) to i1 (back centre)."""
    c = 0.0
    m_b_max = 0.0
    for i in range(min(i0, i1), max(i0, i1)):
        a, b = band[i], band[i + 1]
        ds = np.linalg.norm(b - a)
        t = (b - a) / ds
        x = (a + b) / 2
        m = np.cross(pad - x, e)                 # moment of a unit force at the pad, about this section
        mt = m @ t
        mb = m - mt * t
        c += (mb @ mb / EI + mt * mt / GJ) * ds
        m_b_max = max(m_b_max, float(np.linalg.norm(mb)))
    return c, m_b_max


def main():
    geo = json.load(open(os.path.join(HERE, "device_geometry.json")))
    band = np.array(geo["band_centreline"])
    n = len(band)
    i_exit_r = int(geo["band_pod_fraction"][0] * n)
    i_mid = int(np.argmin(np.abs(band[:, 0])))
    padR = np.array([q for q, _ in geo["sides"]["R"]["pads"]])
    padL = np.array([q for q, _ in geo["sides"]["L"]["pads"][:2]])
    pad_c = padR.mean(0)
    e = np.array([1.0, 0, 0])                    # lateral
    heads = {s: Head(s) for s in SIZES}
    hw = {s: heads[s].mastoid_half_width() for s in SIZES}
    res = {"band_free_length_mm_per_side": round(float(np.sum(np.linalg.norm(np.diff(band[i_exit_r:i_mid + 1], axis=0), axis=1))), 0)}

    # ---- 1+2: wire size, preload, force on five heads
    opts = []
    for mat_name, mat in (("nitinol", NITINOL), ("beta-titanium", BETA_TI), ("spring steel", STEEL)):
        for d in (1.0, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0):
            I = math.pi * d ** 4 / 64
            EI = mat["E"] * I
            GJ = mat["E"] / (2 * (1 + mat["nu"])) * 2 * I
            c, mb = compliance(band, i_exit_r, i_mid, pad_c, e, EI, GJ)
            k = float(1 / c)                     # N/mm per side
            pre = TARGET_N / k                   # how far each side is opened on the medium head
            forces = {s: float(k * (pre + hw[s] - hw["medium"])) for s in SIZES}
            don = pre + max(hw.values()) - hw["medium"] + DONNING_MM
            stress = (k * don) * mb * (d / 2) / I
            stress_head = max(forces.values()) * mb * (d / 2) / I
            opts.append({"material": mat_name, "wire_mm": d, "k_N_per_mm": round(k, 4),
                         "preload_mm_per_side": round(pre, 1),
                         "force_N": {s: round(f, 2) for s, f in forces.items()},
                         "donning_stress_MPa": round(stress, 0), "worn_stress_max_MPa": round(stress_head, 0),
                         "donning_strain_pct": round(100 * stress / mat["E"], 2),
                         "stress_ok": bool(stress < mat["linear_limit_MPa"])})
    # choose: nitinol, stress within the linear range, smallest force spread across heads
    # choose: stress inside the material's elastic range even while putting it on, force spread across the five
    # heads as small as possible; prefer nickel-free beta-titanium on a tie (nickel allergy)
    ok = [o for o in opts if o["stress_ok"] and o["preload_mm_per_side"] <= 40]
    best = min(ok, key=lambda o: (round(max(o["force_N"].values()) - min(o["force_N"].values()), 1),
                                  o["material"] != "beta-titanium", o["donning_stress_MPa"]))
    res["wire_options"] = opts
    res["chosen_wire"] = best
    area_R = 2 * math.pi * 9 ** 2 + math.pi * 7 ** 2          # two 18 mm pads + 14 mm bias on the right
    area_L = 2 * math.pi * 9 ** 2
    res["pad_pressure_mmHg"] = {s: round(f / area_L * 1e6 / 133.3, 1) for s, f in best["force_N"].items()}
    res["pad_pressure_note"] = "left side (2 pads, the higher one); right side has 3 pads: x%.2f" % (area_L / area_R)

    # ---- 3: fit on five heads (device moved by each head's ear tops; pads spread by the spring)
    med = heads["medium"].lm
    fit = {}
    for s in SIZES:
        L = heads[s].lm
        f = {}
        for side, nm, sx in (("R", "right", 1), ("L", "left", -1)):
            shift = np.array(L[f"ear_top_{nm}"]) - np.array(med[f"ear_top_{nm}"])
            shift[0] = sx * (hw[s] - hw["medium"])
            pads = [np.array(q) + shift for q, _ in geo["sides"][side]["pads"][:2]]
            targets = [np.array(L[f"mastoid_upper_{nm}"]), np.array(L[f"mastoid_lower_{nm}"])]
            miss = [float(np.linalg.norm((p - t)[1:])) for p, t in zip(pads, targets)]
            gaps = []
            for q, nn in geo["sides"][side]["inner_face"]:
                g = heads[s].gap(np.array(q) + shift, np.array(nn))
                if g is not None:
                    gaps.append(g)
            f[side] = {"pad_off_mastoid_mm": [round(m, 1) for m in miss], "min_body_skin_gap_mm": round(min(gaps), 1)}
        fit[s] = {"circumference_mm": L["head_circumference_mm"], **f}
    res["fit_one_size"] = fit

    # ---- 3b: sizing - the parametric model rebuilt on each head (EPIPROT_HEAD=<size> freecadcmd ...)
    sizing = {}
    for sz in SIZES:
        f = os.path.join(os.path.dirname(HERE), "headband_checks.json") if sz == "medium" else os.path.join(HERE, f"headband_checks_{sz}.json")
        if os.path.exists(f):
            r = json.load(open(f))
            sizing[sz] = {k: r.get(k) for k in ("size_band_length_mm", "size_pad_spread_mm", "size_ear_top_to_upper_pad_mm",
                                                 "size_pod_to_upper_pad_mm", "min_skin_gap_mm_side_R", "min_skin_gap_mm_band",
                                                 "battery_inside_body_pct", "pillow_back_mm_side_R", "pillow_side_mm_side_R")}
    res["sizing_per_head"] = sizing

    # ---- 4: staying on, comfort
    m = geo["weight_g"] / 1000
    W = m * G
    I = math.pi * HOOK_WIRE_MM ** 4 / 64
    hook_L = 25.0                                # free hook length in front of the ear top
    hook_k = 3 * BETA_TI["E"] * I / hook_L ** 3
    hook_release = hook_k * 5.0                  # tip must lift ~5 mm to clear the ear root
    clamp = best["force_N"]["medium"]
    friction = 2 * MU_PAD_SKIN * clamp
    holds = {
        "down": ("ear hooks carry it (rest on both ear roots)", float("inf")),
        "backward": ("both hook tips must lift over the ear roots + pad friction", 2 * hook_release + friction),
        "up": ("nape band must ride over the occipital bump + hooks lift + friction", 2 * hook_release + friction),
        "forward": ("nape band is behind the neck", float("inf")),
        "sideways": ("far-side hook must lift + friction", hook_release + friction),
    }
    cases = {"standing still": 1.0, "walking (head peak ~1.5 g)": 1.5, "running (head peak ~3 g)": 3.0,
             "convulsion, head jerks (design 3 g)": 3.0, "fall, head hits bed/floor (design 6 g)": 6.0}
    stay = {}
    for c, gs in cases.items():
        load = m * G * gs
        stay[c] = {"inertial_load_N": round(load, 2),
                   "weakest_hold_N": round(min(h for _, h in holds.values()), 2),
                   "safety_factor": round(min(h for _, h in holds.values()) / load, 1)}
    half_inertia_6g = m / 2 * G * 6
    res["breakaway_clasp"] = {"opens_at_N": CLASP_OPEN_N,
                              "largest_service_pull_N (half the device at 6 g)": round(half_inertia_6g, 2),
                              "snag: pull needed to drag both hooks off the ears_N": round(2 * hook_release + friction, 2),
                              "ok": bool(half_inertia_6g < CLASP_OPEN_N < 2 * hook_release + friction)}
    res["staying_on"] = {"weight_g": geo["weight_g"], "hook_wire_mm": HOOK_WIRE_MM, "hook_release_force_N_each": round(hook_release, 2),
                         "pad_friction_N_total": round(friction, 2), "holds": {k: [v[0], None if v[1] == float("inf") else round(v[1], 2)] for k, v in holds.items()},
                         "cases": stay}
    res["ear_root_pressure_mmHg"] = round((W / 2) / HOOK_CONTACT_MM2 * 1e6 / 133.3, 1)   # all weight on the hooks (worst case)
    res["skin_limit_note"] = "capillary closing pressure ~32 mmHg (Landis 1930); pads and ear root must stay below"
    json.dump(res, open(os.path.join(HERE, "mechanics_results.json"), "w"), indent=1)

    print("band free length per side %.0f mm" % res["band_free_length_mm_per_side"])
    for o in opts:
        print("%-13s d=%.1f  k=%.3f N/mm  preload %5.1f mm  force S/M/L/LN/SW %s  donning %4.0f MPa (%.2f%%) %s" % (
            o["material"], o["wire_mm"], o["k_N_per_mm"], o["preload_mm_per_side"],
            "/".join("%.2f" % v for v in o["force_N"].values()), o["donning_stress_MPa"], o["donning_strain_pct"],
            "ok" if o["stress_ok"] else "TOO HIGH"))
    print("chosen:", best["material"], best["wire_mm"], "mm; head half-widths", {s: round(v, 1) for s, v in hw.items()})
    print("pad pressure mmHg", res["pad_pressure_mmHg"], "| ear root", res["ear_root_pressure_mmHg"])
    for s, f in fit.items():
        print("fit one size", s, f)
    for s, f in res["sizing_per_head"].items():
        print("fitted to", s, f)
    print("clasp", res["breakaway_clasp"])
    print("staying on", json.dumps(res["staying_on"], indent=0))


if __name__ == "__main__":
    main()
