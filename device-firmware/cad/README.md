# Headband 3D model (FreeCAD)

**`epiprot_headband.FCStd`** is the model to work on (v3, `../HARDWARE.md` D16–D19), built on a real head
(NIOSH medium headform, 553 mm head circumference):

- **Side bodies**, one moulded piece per side: ear hook over the ear root (flat 6 x 4 mm), electrode module on
  the mastoid (upper + lower 18 mm pad, bias pad under the right ones), pod on the side of the neck (right:
  700 mAh LiPo 603040 in a carrier with 0.6 mm swelling room; left: board, nRF52840 module, ADS1299, IMU,
  flash, button, LED).
- **Nape spring band**: 1.3 mm beta-titanium wire in silicone, joins the pods and presses the pads (1.5 N per
  side, 22 mmHg); magnetic breakaway clasp (5 N) at the back.

## Checks and calculations

| File | What |
|---|---|
| `headband_checks.json` | written on every rebuild: parts inside the body, gaps to the skin, pillow contact, pad pressure, weight, size numbers |
| `headform/pod_placement_study.py` | where the pods can sit without touching the pillow (lying on the back / side) |
| `headform/mechanics.py` → `mechanics_results.json` | spring wire (nitinol / beta-titanium / steel compared), force on 5 heads, fit, sizes, staying on, ear-root pressure, clasp |
| `headform/headband_checks_<head>.json` | the model rebuilt on each NIOSH head (sizing): `EPIPROT_HEAD=large freecadcmd ...` |

## Change it

1. Open `epiprot_headband.FCStd` in FreeCAD 1.1.
2. Double-click the spreadsheet **Params** and change a value (pod size and position, pad size, band, battery, ...).
3. Macro > Macros... > `epiprot_headband.FCMacro` > Execute: the model is rebuilt on the head and re-checked.

Pictures: `EPIPROT_SHOTS=1 freecad.exe epiprot_headband.FCMacro` → `headband_back.png`, `headband_back_left.png`,
`headband_right_side.png`, `headband_front_right.png`, `headband_inside_left.png`, `headband_inside_right.png`.

## Manufacturing files

`freecadcmd export_parts.py` → `export/`: `epiprot_headband_assembly.step` (all parts), `side_body_R/L.stl` and
`nape_band.stl` (silicone mould masters or TPU fit prints), `carrier_R/L_base.stl` + `_lid.stl` (print in PA12 or
tough resin; flex-cable slot at the top).

## The heads

`headform/headform_<size>_mm.stl`: NIOSH anthropometric digital headforms small, medium, large, long-narrow,
short-wide (NIOSH National Personal Protective Technology Laboratory, NPPTL), from the NIH 3D Print Exchange
entry 3DPX-015142 "NIOSH Anthropometric Digital Headforms with Base" by tprestero, licensed CC-BY.
`headform/prepare_headform.py` converted them to mm and our axes (x = right, y = forward, z = up, 0 = between
the auricle centres) and measured the landmarks in `landmarks_<size>.json`. The small headform's ears are
smoothed in the scan, so its ear landmarks are less reliable.

## Concept comparison

`concepts.py` / `render_concepts.py` / `concepts.png`: the four early layouts on a simple head; D (pods low at
the back corners) was chosen and developed into v3.

## Photo-real pictures (Blender 5.3, Cycles)

`render/epiprot_hero.png`, `epiprot_back.png`, `epiprot_side.png`, `epiprot_closeup.png`, `epiprot_xray.png`.
Rebuild: `freecadcmd render/export_render_meshes.py` (part meshes, not kept in git), then
`blender.exe -b -P render/render_blender.py -- hero back side closeup xray`.
