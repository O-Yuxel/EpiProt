"""Doctor report generated ON THE PHONE (no separate doctor software).

PDF with: summary, seizures per day, time of day, event list, recovery times, and one
page of raw signals (EEG, heart rate, movement) per big seizure. A package (PDF + CSV of
the log + raw signal files) is queued in the outbox and sent when the phone is online.
"""
from __future__ import annotations

import csv
import json
import datetime as dt
import io
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,  # noqa: E402
                                TableStyle)

from .eventlog import EventLog  # noqa: E402

SERIES = "#2a78d6"     # one series per chart -> one hue
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
ACCENT = colors.HexColor("#0f6f8f")
LINE = colors.HexColor("#d3dae2")
SOFT = colors.HexColor("#eef3f7")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=13, textColor=ACCENT,
                    spaceBefore=10, spaceAfter=5)
B = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13)
SM = ParagraphStyle("sm", parent=B, fontSize=8, leading=10.5, textColor=colors.HexColor(INK2))
CELL = ParagraphStyle("c", parent=B, fontSize=8.2, leading=10.4)
CELLB = ParagraphStyle("cb", parent=CELL, fontName="Helvetica-Bold")


def _ax_style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _img(fig, width_cm):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    w, h = fig.get_size_inches()
    return Image(buf, width=width_cm * cm, height=width_cm * cm * h / w)


def _clock(start: dt.datetime, s: float) -> dt.datetime:
    return start + dt.timedelta(seconds=float(s))


def _table(rows, widths):
    data = [[Paragraph(str(v), CELLB if r == 0 else CELL) for v in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                           ("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _fmt_dur(s):
    if s is None:
        return "-"
    s = int(round(s))
    if s >= 3600:
        return f"{s // 3600} h {s % 3600 // 60:02d} min"
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


def signal_figure(npz_path: Path, title: str):
    from epiprot.gbm.hrv import r_peaks
    z = np.load(npz_path)
    t0 = float(z["t0_rel_onset"])
    panels = []
    if "eeg" in z.files:
        fs = float(z["eeg_fs"])
        for ci, name in enumerate(["EEG left behind-ear (uV)", "EEG cross-head (uV)"]):
            x = z["eeg"][ci].astype(np.float32)
            panels.append((t0 + np.arange(len(x)) / fs, x, name))
    if "ecg" in z.files:
        fs = float(z["ecg_fs"])
        x = z["ecg"][0].astype(np.float64)
        pk = r_peaks(x, fs) if np.isfinite(x).all() and len(x) > fs * 10 else np.array([], int)
        if len(pk) > 3:
            tt = pk[1:] / fs
            from scipy.signal import medfilt
            hr = medfilt(60.0 / np.diff(pk / fs), 7)
            ok = (hr > 30) & (hr < 220)
            panels.append((t0 + tt[ok], hr[ok], "Heart rate (bpm)"))
    if "mov" in z.files:
        fs = float(z["mov_fs"])
        ch = [str(c) for c in z["mov_ch"]]
        idx = [i for i, c in enumerate(ch) if c.startswith("EEG SD ACC")]
        if len(idx) == 3:
            m = np.sqrt((z["mov"][idx].astype(np.float32) ** 2).sum(0))
            panels.append((t0 + np.arange(len(m)) / fs, m - np.median(m), "Head movement (g, detrended)"))
    fig, axes = plt.subplots(len(panels), 1, figsize=(7.2, 1.25 * len(panels) + 0.4), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (t, x, name) in zip(axes, panels):
        ax.plot(t, x, color=SERIES, linewidth=0.6 if "EEG" in name else 1.2)
        ax.axvline(0, color=INK2, linewidth=1, linestyle="--")
        ax.set_title(name, fontsize=8.5, color=INK, loc="left", pad=3)
        if "EEG" in name:
            lim = np.nanpercentile(np.abs(x), 99.5)
            ax.set_ylim(-lim, lim)
        _ax_style(ax)
    axes[-1].set_xlabel("seconds from seizure start (dashed line)", fontsize=8, color=INK2)
    fig.suptitle(title, fontsize=9.5, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    return fig


def quality_figure(quality: dict, alerts: list, start_clock: dt.datetime, days: int):
    """One row per signal; blue = usable, orange = missing or bad (1-minute bins). Markers = watch warnings."""
    rows = [("brain", "Brain (headband)"), ("head_mov", "Head mov. (headband)"),
            ("heart", "Heart rate (watch)"), ("body_mov", "Body mov. (watch)")]
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    for r, (k, lab) in enumerate(rows):
        bad = quality[k] != 0
        m = len(bad) // 12 * 12
        b = bad[:m].reshape(-1, 12).mean(1) >= 0.5            # 1-minute bins
        ax.broken_barh([(0, len(b) / 1440.0)], (r - 0.32, 0.64), color="#c9d6e3")
        edges = np.flatnonzero(np.diff(np.r_[0, b.astype(int), 0]))
        ax.broken_barh([(st / 1440.0, max((en - st) / 1440.0, 0.004)) for st, en in zip(edges[::2], edges[1::2])],
                       (r - 0.32, 0.64), color="#d4762c")
    for a in alerts:
        rr = [r for r, (k, _) in enumerate(rows) if k in json.loads(a["signals"])]
        ax.plot(a["warned_s"] / 86400, min(rr) - 0.5, marker="v", ms=4, color=INK, lw=0)
    ax.set_yticks(range(len(rows)), [lab for _, lab in rows])
    ax.set_ylim(len(rows) - 0.5, -0.75)
    ax.set_xlim(0, days)
    ax.set_xticks(range(days), [f"{_clock(start_clock, d * 86400):%d.%m}" for d in range(days)])
    _ax_style(ax)
    ax.yaxis.grid(False)
    ax.set_title("Blue: usable   Orange: missing or bad   Black marker: warning sent to the watch",
                 fontsize=8, color=INK2, loc="left")
    return fig


def build(log: EventLog, patient: str, start_clock: dt.datetime, monitored_h: float, now_s: float,
          quality: dict | None = None) -> Path:
    evs = [dict(r) for r in log.events()]
    sz = [e for e in evs if e["kind"] == "seizure"]
    fa = [e for e in evs if e["kind"] == "false_alarm"]
    other = [e for e in evs if e["kind"] == "other_seizure"]
    days = int(np.ceil(monitored_h / 24))
    story = []
    story.append(Paragraph("EpiProt seizure report", ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold",
                                                                     fontSize=18, alignment=0)))
    end_clock = _clock(start_clock, monitored_h * 3600)
    story.append(Paragraph(f"Patient {patient} &nbsp;·&nbsp; {start_clock:%d.%m.%Y %H:%M} - {end_clock:%d.%m.%Y %H:%M} "
                           f"({monitored_h:.0f} h monitored) &nbsp;·&nbsp; generated on the phone", SM))
    story.append(Spacer(1, 8))
    pin = sum(e["cancelled_with_pin"] for e in fa)
    resp = [e["recovery_response_s"] for e in sz if e["recovery_response_s"] is not None]
    lat = [e["alarm_s"] - e["onset_s"] for e in sz if e["source"] == "device"]
    summary = [
        ["Item", "Value"],
        ["Big (tonic-clonic) seizures", f"{len(sz)} &nbsp;({sum(e['source'] == 'device' for e in sz)} detected by the "
                                        f"device, {sum(e['source'] == 'manual' for e in sz)} entered by hand)"],
        ["Seizures per day", f"{len(sz) / max(monitored_h / 24, 1e-9):.1f}"],
        ["Median seizure duration (device estimate)", _fmt_dur(np.median([e["duration_s"] for e in sz])) if sz else "-"],
        ["Alarm after estimated seizure start (median)", _fmt_dur(np.median(lat)) if lat else "-"],
        ["Seizures longer than 5 min (emergency)", str(sum(e["emergency_s"] is not None for e in sz))],
        ["Time until the patient answered after a seizure (median)", _fmt_dur(np.median(resp)) if resp else "-"],
        ["Caregiver alerted again (no answer 15 min)", str(sum(e["recovery_escalated"] for e in sz))],
        ["Caregiver alerts (sent at the moment of the alarm)", str(sum(e["caregiver_notified_s"] is not None for e in evs))],
        ["False alarms", f"{len(fa)} &nbsp;({pin} cancelled by the patient with PIN and a \"false alarm\" message sent "
                         f"to the caregiver, {len(fa) - pin} checked by the caregiver)"],
        ["Other (non-convulsive) seizures that raised an alarm", str(len(other))],
    ]
    story.append(_table(summary, [7 * cm, 9.8 * cm]))

    # seizures per day
    if sz:
        story.append(Paragraph("Big seizures per day", H1))
        counts = np.zeros(days, int)
        for e in sz:
            counts[min(days - 1, int(e["onset_s"] // 86400))] += 1
        fig, ax = plt.subplots(figsize=(7.2, 1.9))
        x = np.arange(days)
        ax.bar(x, counts, color=SERIES, width=0.6)
        ax.set_xticks(x, [f"{_clock(start_clock, d * 86400):%d.%m}" for d in x])
        ax.set_yticks(range(0, max(counts.max(), 1) + 1))
        for xi, c in zip(x, counts):
            if c:
                ax.text(xi, c + 0.05, str(c), ha="center", va="bottom", fontsize=8, color=INK)
        _ax_style(ax)
        story.append(_img(fig, 16.8))

        story.append(Paragraph("Time of day of big seizures", H1))
        hrs = [(_clock(start_clock, e["onset_s"]).hour + _clock(start_clock, e["onset_s"]).minute / 60) for e in sz]
        fig, ax = plt.subplots(figsize=(7.2, 1.7))
        h = np.histogram(hrs, bins=np.arange(0, 25, 2))[0]
        ax.bar(np.arange(0, 24, 2) + 1, h, width=1.6, color=SERIES)
        ax.set_xticks(range(0, 25, 4), [f"{v:02d}:00" for v in range(0, 25, 4)])
        ax.set_yticks(range(0, max(h.max(), 1) + 1))
        _ax_style(ax)
        story.append(_img(fig, 16.8))

    # event list
    story.append(Paragraph("All events", H1))
    rows = [["#", "Date / time", "Type", "Source", "Duration", "Alert", "Answered after", "State", "Heart rate", "Confirmed"]]
    for i, e in enumerate(evs, 1):
        kind = {"seizure": "Big seizure", "false_alarm": "False alarm", "other_seizure": "Other seizure"}.get(e["kind"], e["kind"])
        hr = (f"{e['hr_before']:.0f} → {e['hr_peak']:.0f}" if e["hr_before"] and e["hr_peak"] else "-")
        rows.append([i, f"{_clock(start_clock, e['onset_s']):%d.%m %H:%M}", kind, e["source"],
                     _fmt_dur(e["duration_s"]) if e["kind"] == "seizure" else "-",
                     "sent + PIN" if e["cancelled_with_pin"] else ("sent" if e["caregiver_notified_s"] else "-"),
                     _fmt_dur(e["recovery_response_s"]), e["vigilance"] or "-", hr,
                     f"{e['confirmed'] or '-'} ({e['confirmed_by'] or '-'})"])
    story.append(_table(rows, [0.6 * cm, 2.0 * cm, 1.9 * cm, 1.3 * cm, 1.8 * cm, 1.7 * cm, 1.8 * cm, 1.3 * cm, 1.9 * cm, 2.5 * cm]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Durations are estimated by the device from its own score, which stays high for a while "
                           "after the convulsion, so they are usually longer than the clinical seizure duration. "
                           "Heart rate before and peak come from the ECG.", SM))
    story.append(Paragraph("Raw EEG, ECG and movement are stored for every event (2 min before to 5 min after) and "
                           "included in the data package.", SM))

    # sensor quality and the warnings that were sent to the watch
    alerts = [dict(r) for r in log.sensor_alerts()]
    if quality is not None:
        story.append(PageBreak())
        story.append(Paragraph("Sensor quality", H1))
        story.append(Paragraph("The phone checks every 5-second window. When data from the headband or the watch is "
                               "missing or bad for 2 minutes, the watch vibrates and tells the patient what to fix.", B))
        story.append(Spacer(1, 4))
        story.append(_img(quality_figure(quality, alerts, start_clock, days), 16.8))
        labels = {"brain": "Brain signal (headband)", "head_mov": "Head movement (headband)",
                  "heart": "Heart rate (watch)", "body_mov": "Body movement (watch)"}
        rows = [["Signal", "Usable time", "Warnings sent"]]
        for k, lab in labels.items():
            rows.append([lab, f"{np.mean(quality[k] == 0):.1%}",
                         str(sum(k in json.loads(a["signals"]) for a in alerts))])
        story.append(_table(rows, [7 * cm, 4.9 * cm, 4.9 * cm]))
        if alerts:
            story.append(Paragraph("Warnings sent to the watch", H1))
            rows = [["Warned", "Device", "Message on the watch", "Remin-ders", "Fixed after"]]
            for a in alerts:
                rows.append([f"{_clock(start_clock, a['warned_s']):%d.%m %H:%M}", a["device"],
                             f"{a['message']} <font color='{INK2}'>{a['impact']}</font>",
                             str(len(json.loads(a["reminders"]))),
                             _fmt_dur(a["fixed_s"] - a["bad_from_s"]) if a["fixed_s"] else "still open"])
            story.append(_table(rows, [2.0 * cm, 1.7 * cm, 9.3 * cm, 1.7 * cm, 2.1 * cm]))
            story.append(Spacer(1, 4))
            story.append(Paragraph("'Fixed after' is measured from the moment the data became bad. In this demo nobody "
                                   "reacted to the warnings (recorded data), so it shows how long problems last "
                                   "without the warning system.", SM))

    # signal pages
    for i, e in enumerate(evs, 1):
        if e["kind"] != "seizure" or not e["signal_file"] or not Path(e["signal_file"]).exists():
            continue
        story.append(PageBreak())
        story.append(Paragraph(f"Event {i}: big seizure, {_clock(start_clock, e['onset_s']):%d.%m.%Y %H:%M}", H1))
        steps = log.flow(e["id"])
        if steps:
            story.append(_table([["Time", "Step", "Detail"]] +
                                [[f"{_clock(start_clock, s['t_s']):%H:%M:%S}", s["step"], s["detail"]] for s in steps],
                                [2.2 * cm, 4.3 * cm, 10.3 * cm]))
            story.append(Spacer(1, 6))
        st = json.loads(e["sensor_status"] or "{}")
        missing = [m.upper() for m, v in st.items() if v >= 0.5]
        miss_txt = f" · not recorded: {', '.join(missing)}" if missing else ""
        story.append(_img(signal_figure(Path(e["signal_file"]),
                                        f"{'Detected by the device' if e['source'] == 'device' else 'Entered by hand'}"
                                        f" · duration {_fmt_dur(e['duration_s'])} · {e['vigilance'] or ''}" + miss_txt), 16.8))

    out = log.folder / "reports" / f"report_{patient}.pdf"
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.7 * cm,
                      bottomMargin=1.7 * cm, title=f"EpiProt seizure report {patient}").build(story)
    return out


def package(log: EventLog, report: Path, patient: str, now_s: float) -> Path:
    """Report + CSV of the log + raw signal files, queued for the doctor."""
    out = log.folder / "outbox" / f"epiprot_{patient}.zip"
    evs = [dict(r) for r in log.events()]
    buf = io.StringIO()
    if evs:
        w = csv.DictWriter(buf, fieldnames=list(evs[0]))
        w.writeheader()
        w.writerows(evs)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(report, report.name)
        zf.writestr("events.csv", buf.getvalue())
        for e in evs:
            if e["signal_file"] and Path(e["signal_file"]).exists():
                zf.write(e["signal_file"], f"signals/{Path(e['signal_file']).name}")
    log.queue(out, now_s)
    return out
