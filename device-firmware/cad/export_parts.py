"""Export the EpiProt headband v3 parts for manufacturing / 3D printing (run after epiprot_headband.FCMacro).

Writes device-firmware/cad/export/:
  epiprot_headband_assembly.step   every part, for any CAD program
  side_body_R.stl, side_body_L.stl, nape_band.stl   outer soft bodies (silicone moulding masters; or TPU 85A prints)
  carrier_R_base.stl / carrier_R_lid.stl, carrier_L_base.stl / carrier_L_lid.stl
                                    rigid carriers split at mid-height (print in PA12 / tough resin), with a
                                    5 x 1.6 mm slot at the top for the flex cable

Usage: "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" device-firmware/cad/export_parts.py
"""
import os

import FreeCAD as App
import Import
import Mesh
import Part
from FreeCAD import Vector as V

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "export")


def main():
    os.makedirs(OUT, exist_ok=True)
    doc = App.openDocument(os.path.join(HERE, "epiprot_headband.FCStd"))
    parts = [o for o in doc.Objects if o.TypeId == "Part::Feature"]
    Import.export(parts, os.path.join(OUT, "epiprot_headband_assembly.step"))
    for name, fn in (("Side_body_R", "side_body_R"), ("Side_body_L", "side_body_L"), ("Nape_spring_band", "nape_band")):
        Mesh.export([doc.getObject(name)], os.path.join(OUT, fn + ".stl"))
    for s in ("R", "L"):
        car = doc.getObject(f"Carrier_{s}").Shape
        # carrier axes: its faces are planes; the thin direction is the normal of its largest face
        big = max(car.Faces, key=lambda f: f.Area)
        n = big.normalAt(0, 0)
        c = car.BoundBox.Center
        half = Part.makeBox(200, 200, 200, V(-100, -100, 0))
        rot = App.Rotation(V(0, 0, 1), n)
        half.Placement = App.Placement(c, rot)
        base = car.cut(half)
        lid = car.common(half)
        # flex-cable slot through the end wall nearest the module (highest end)
        ends = sorted(car.Faces, key=lambda f: f.CenterOfMass.z)
        top = ends[-1]
        slot = Part.makeBox(5.0, 1.6, 6.0, V(-2.5, -0.8, -3.0))
        slot.Placement = App.Placement(top.CenterOfMass, App.Rotation(V(0, 0, 1), top.normalAt(0, 0)))
        base, lid = base.cut(slot), lid.cut(slot)
        for nm, sh in (("base", base), ("lid", lid)):
            m = Mesh.Mesh(sh.tessellate(0.05))
            m.write(os.path.join(OUT, f"carrier_{s}_{nm}.stl"))
            print(f"carrier_{s}_{nm}: volume {sh.Volume / 1000:.2f} cm3, valid {sh.isValid()}")
    print("written to", OUT)


main()
