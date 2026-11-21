"""Fault scenarios for the virtual headband: does the phone notice, warn correctly, and lose no data?

Each scenario runs one hour of a real SeizeIT2 recording through the headband with one fault. The
phone side is replayed as the app works: a 5 s window is judged with the packets that arrived
before it closed (window end + 2 s), the sensor-health rules of epiprot.app.health decide the
warnings, and everything that arrives later (catch-up data) goes to the diary.

Two phone versions are compared:
  "signal check"   the current app: judges the brain signal only from the samples (flat / saturated)
  "+ contact bits" planned: also uses the electrode contact (lead-off) bits the headband sends

Usage: python -m epiprot.headband.fault_study --raw-dir /raw --sub sub-115 --out epiprot_results/headband/faults
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from epiprot.app import health as H

from . import faults as F
from . import protocol as P
from .device import HardwareConfig, load_source, seizure_runs, simulate
from .phone import Receiver

W = 5.0
WIN_EEG = int(W * 256)
CLOSE_DELAY_MS = 2000
CH_ELECTRODES = {1: (0, 1), 2: (0, 2), 3: (2, 3), 4: (1, 3)}          # channel -> electrode indices


def scenarios():
    return [
        ("No fault", [], {"warnings": []}),
        ("Phone out of range 10 min", [F.Disconnect(600, 600)],
         {"warnings": ["headband_missing"], "no_data_lost": True}),
        ("Phone out of range 45 min (store holds ~38 min)", [F.Disconnect(300, 2700)],
         {"warnings": ["headband_missing"], "oldest_lost": True, "flash_full_reported": True}),
        ("Pad drying out over 40 min (L-bottom)", [F.PadDrying("L-bottom", 300, 2400, 3000)],
         {"warnings": ["brain_weak"], "pad_warning_first": "L-bottom"}),
        ("Pad falls off (L-top)", [F.ElectrodeOff("L-top", 900, 600)],
         {"warnings": ["brain_weak"], "backup_channels_ok": [3, 4]}),
        ("Loose cable (R-top)", [F.LooseCable("R-top", 900, 600)],
         {"warnings": ["brain_weak"]}),
        ("Bias electrode off", [F.ElectrodeOff("bias", 900, 600)],
         {"warnings": ["brain_weak"]}),
        ("Charging 30 min", [F.Charging(900, 1800)],
         {"warnings": ["headband_missing"], "charging_reported": True}),
        ("Motion sensor fails", [F.MotionSensorFailure(900)],
         {"warnings": ["head_mov_missing"], "imu_error_reported": True}),
        ("Battery runs out", [F.BatteryRunsOut(1800, 20)],
         {"warnings": ["headband_missing"], "low_battery_reported": True}),
    ]


def _log_rms(x):
    x = x[np.isfinite(x)]
    return np.log10(np.std(x) + 1e-6) if x.size > 1 else np.nan


def _gamma_log_power(x, fs=256.0):
    x = x[np.isfinite(x)]
    if x.size < 256:
        return np.nan
    x = x - x.mean()
    p = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(x.size, 1 / fs)
    return np.log10(p[(f >= 30) & (f < 60)].sum() / x.size + 1e-12)


def phone_live_view(records, info: P.DeviceInfo, n_win: int, pair=(1, 2)):
    """Per window, what the phone had when the window closed."""
    eeg = np.full((4, n_win * WIN_EEG), np.nan)
    lead = np.zeros(n_win, np.uint8)
    mov = np.zeros(n_win, bool)
    status = []
    for ms, b in records:
        p = P.decode(b)
        if isinstance(p, P.StatusPacket):
            status.append(p)
            continue
        if isinstance(p, P.ContactPacket):
            continue
        if isinstance(p, P.EegPacket):
            w = p.sample_index // WIN_EEG
            if w < n_win and ms <= (w + 1) * W * 1000 + CLOSE_DELAY_MS:
                c = p.codes.astype(float) * info.eeg_lsb_nv / 1000
                c[(p.codes <= P.INT24_MIN) | (p.codes >= P.INT24_MAX)] = np.nan
                if p.flags & P.FLAG_CONTACT_CHECK:
                    c[:] = np.nan
                eeg[:, p.sample_index:p.sample_index + len(c)] = c.T
                lead[w] |= p.lead_off
        else:
            t = p.t_dev / P.TICKS_PER_S
            w = int(t // W)
            if w < n_win and ms <= (w + 1) * W * 1000 + CLOSE_DELAY_MS:
                mov[w] = True
    seg = eeg.reshape(4, n_win, WIN_EEG)
    rms = np.array([[_log_rms(seg[c, w]) for w in range(n_win)] for c in range(4)])
    gamma = np.array([[_gamma_log_power(seg[c, w]) for w in range(n_win)] for c in range(4)])
    return {"rms": rms, "gamma": gamma, "lead": lead, "mov": mov, "status": status}


def brain_quality(view, chans, use_lead_off: bool) -> np.ndarray:
    n = view["rms"].shape[1]
    q = np.zeros(n, np.int8)
    for c in chans:
        r = view["rms"][c - 1]
        q = np.maximum(q, np.where((r < H.FLAT_LOG) | (r > H.SAT_LOG), H.POOR, H.OK).astype(np.int8))
    for c in chans:
        q[np.isnan(view["rms"][c - 1])] = H.MISSING
    if use_lead_off:
        mask = P.LEAD_BIAS
        for e in {e for c in chans for e in CH_ELECTRODES[c]}:
            mask |= 1 << e
        q[(q == H.OK) & ((view["lead"] & mask) > 0)] = H.POOR
    return q


def run_scenario(src_args, faults, expect, pair=(1, 2), cfg=HardwareConfig(), baseline=None):
    src = load_source(*src_args)
    records, meta = simulate(src, cfg, faults=faults)
    info = P.DeviceInfo.decode(bytes.fromhex(meta["device_info"]))
    n_win = meta["eeg_samples"] // WIN_EEG
    view = phone_live_view(records, info, n_win, pair)
    res = {"faults": meta["faults"]}
    q_head = np.where(view["mov"], H.OK, H.MISSING).astype(np.int8)
    ok = np.zeros(n_win, np.int8)
    for label, lo in (("signal check", False), ("+ contact bits", True)):
        q = {"brain": brain_quality(view, pair, lo), "head_mov": q_head, "heart": ok, "body_mov": ok}
        eps = H.monitor(q)
        res[label] = [{"warning": e.code, "bad_from_s": e.bad_from_s, "warned_s": e.warned_s,
                       "fixed_s": e.fixed_s, "impact": e.impact_code} for e in eps]
    # diary: everything that ever arrived
    rx = Receiver(info.encode())
    for ms, b in records:
        rx.feed(ms, b)
    st = view["status"]
    pads = rx.pad_warnings()
    res["pad_warnings"] = {"first_s": pads[0][0] if pads else None, "first_pad": pads[0][1] if pads else None,
                           "first_kohm": pads[0][2] if pads else None, "checks": len(rx.contact)}
    res["diary"] = {"packets_lost_for_good": len(rx.missing_seq()), "catch_up_packets": rx.catchup,
                    "duplicates_ignored": rx.duplicates, "dropped_when_store_full": meta["dropped_when_store_full"]}
    res["status_seen"] = {
        "low_battery_first_s": next((s.uptime_s for s in st if s.state & P.ST_LOW_BATTERY), None),
        "charger_reported": any(s.state & P.ST_CHARGER for s in st),
        "imu_error_reported": any(s.errors & P.ERR_IMU_CHIP for s in st),
        "flash_full_reported": any(s.errors & P.ERR_FLASH_FULL for s in st),
        "lead_off_reported": any(s.lead_off for s in st)}
    fault_win = np.zeros(n_win, bool)
    for f in faults:
        a = getattr(f, "start_s", 0)
        d = getattr(f, "dur_s", None) or (n_win * W - a)
        fault_win[int(a // W):min(n_win, int((a + d) // W))] = True
    if fault_win.any():
        res["channels_usable_during_fault"] = {
            c: float((brain_quality(view, [c], True)[fault_win] == H.OK).mean()) for c in range(1, 5)}
        if baseline is not None:      # same recording, same noise, no fault: the change is the fault's
            d = view["gamma"][:, fault_win] - baseline["gamma"][:, fault_win]
            res["gamma_power_change_log10"] = {c: float(np.nanmedian(d[c - 1])) if np.isfinite(d[c - 1]).any()
                                               else None for c in range(1, 5)}
    res["checks"] = _check(res, expect)
    return res


def _check(res, expect):
    out = {}
    for label in ("signal check", "+ contact bits"):
        got = sorted({e["warning"] for e in res[label]})
        out[f"warnings ({label})"] = got == sorted(expect["warnings"])
    d, s = res["diary"], res["status_seen"]
    if expect.get("no_data_lost"):
        out["no data lost"] = d["packets_lost_for_good"] == 0
    if expect.get("oldest_lost"):
        out["only the oldest data lost"] = d["packets_lost_for_good"] == d["dropped_when_store_full"] > 0
    if expect.get("flash_full_reported"):
        out["store-full reported"] = s["flash_full_reported"]
    if expect.get("charging_reported"):
        out["charging reported"] = s["charger_reported"]
    if expect.get("imu_error_reported"):
        out["sensor error reported"] = s["imu_error_reported"]
    if expect.get("low_battery_reported"):
        out["low battery reported"] = s["low_battery_first_s"] is not None
    if "pad_warning_first" in expect:
        pw, bw = res["pad_warnings"], [e["warned_s"] for e in res["+ contact bits"] if e["warning"] == "brain_weak"]
        out["replace-pad warning before contact is lost"] = (pw["first_pad"] == expect["pad_warning_first"]
                                                            and pw["first_s"] is not None
                                                            and (not bw or pw["first_s"] < min(bw)))
    elif res["pad_warnings"]["first_s"] is not None and not any(
            f["type"] in ("ElectrodeOff", "LooseCable", "PadDrying") for f in res["faults"]):
        out["no replace-pad warning"] = False
    if "backup_channels_ok" in expect:
        out["backup channels usable"] = all(res["channels_usable_during_fault"][c] > 0.95
                                            for c in expect["backup_channels_ok"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--sub", default="sub-115")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    run, onset, _ = seizure_runs(a.raw_dir, a.sub)[0]
    start = max(0.0, onset - 3000)
    src_args = (a.raw_dir, a.sub, run, start, 3600.0)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    allres = {}
    src = load_source(*src_args)
    rec0, meta0 = simulate(src, HardwareConfig())
    base = phone_live_view(rec0, P.DeviceInfo.decode(bytes.fromhex(meta0["device_info"])),
                           meta0["eeg_samples"] // WIN_EEG)
    for name, faults, expect in scenarios():
        r = run_scenario(src_args, faults, expect, baseline=base)
        t0 = min((getattr(f, "start_s", getattr(f, "empty_s", 0)) for f in faults), default=0)
        allres[name] = r
        w = lambda lab: ", ".join(f"{e['warning']} {e['warned_s'] - t0:.0f} s after the fault started"
                                  + (f", cleared at {e['fixed_s']:.0f} s" if e["fixed_s"] else "") for e in r[lab]) or "none"
        print(f"\n== {name}")
        print(f"   phone today    : {w('signal check')}")
        print(f"   + contact bits : {w('+ contact bits')}")
        print(f"   diary          : {r['diary']}")
        pw = r["pad_warnings"]
        print(f"   contact checks : {pw['checks']}, " + (f"first 'replace pad' {pw['first_pad']} at {pw['first_s']:.0f} s"
              f" ({pw['first_kohm']} kOhm)" if pw["first_s"] is not None else "no pad to replace"))
        if "channels_usable_during_fault" in r:
            print(f"   channels usable during fault: {r['channels_usable_during_fault']}")
            print(f"   30-60 Hz power change vs. same time without fault (log10): "
                  + ", ".join(f"ch{c} " + ("lost" if v is None else f"{v:+.2f}")
                              for c, v in r["gamma_power_change_log10"].items()))
        print(f"   checks         : " + ", ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in r["checks"].items()))
    (out / f"{a.sub}_faults.json").write_text(json.dumps(allres, indent=1, default=str))


if __name__ == "__main__":
    main()
