# Headband 3D model (FreeCAD)

**`epiprot_headband.FCStd`** is the model to work on: concept D, two pods at the lower back corners of the
head (left: electronics, right: 700 mAh battery), elastic band below the occipital bump, ear hooks that go up
behind the ears and over them (like glasses temples), four semi-dry pads behind the ears, a bias electrode at the
back and a magnetic safety clasp that opens under a strong pull.

## Change it

1. Open `epiprot_headband.FCStd` in FreeCAD 1.1.
2. Double-click the spreadsheet **Params**; change a value (band width, pod sizes, battery size, pod position,
   `top_strap` = 1 for a strap over the crown, ...).
3. Macro > Macros... > `epiprot_headband.FCMacro` > Execute: the model is rebuilt from the new values.

Pictures (rebuilt with the model): `EPIPROT_SHOTS=1 freecad.exe epiprot_headband.FCMacro`

| File | View |
|---|---|
| `headband_back.png` | from behind |
| `headband_back_left.png`, `headband_back_right.png` | from behind, three-quarter |
| `headband_right_side.png` | right side |
| `headband_inside_left.png` | pods transparent: board, chips, battery inside |

The head is a simple average adult head made of smooth shapes, not a scan; component sizes are from
`../HARDWARE.md`.

## Concept comparison

`concepts.py` / `render_concepts.py` / `concepts.png`: the four layouts compared (A one nape pod, B behind the
ears, C thin nape pod + battery in the band, D two lower corner pods) for pillow pressure lying on the back and
on the side; D was chosen.
