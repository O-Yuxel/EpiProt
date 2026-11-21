"""Export every part of the headband model as its own fine mesh for Blender (run with freecadcmd).

Writes device-firmware/cad/render/meshes/<part>.stl (not kept in git) and parts.json: part -> material.
Usage: "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" device-firmware/cad/render/export_render_meshes.py
"""
import json
import os

import FreeCAD as App
import Mesh
import MeshPart

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.dirname(HERE)
OUT = os.path.join(HERE, "meshes")


def material(name):
    if name.startswith(("Side_body", "Nape_spring_band")):
        return "silicone"
    if name.startswith("Pad_"):
        return "hydrogel"
    if name.startswith(("Snap_", "Breakaway")):
        return "steel"
    if name.startswith("Charge_contact"):
        return "gold"
    if name.startswith("LED"):
        return "led"
    if name.startswith(("Button", "Blank_cap")):
        return "silicone_light"
    if name.startswith("Battery"):
        return "battery"
    if name.startswith(("PCB", "Charge_protect")):
        return "pcb"
    if name.startswith("Carrier"):
        return "carrier"
    if name.startswith("Flex_cable"):
        return "flex"
    if name.startswith("Spring_wire"):
        return "titanium"
    if name.startswith("BLE"):
        return "shield"
    return "chip"


def main():
    os.makedirs(OUT, exist_ok=True)
    doc = App.openDocument(os.path.join(CAD, "epiprot_headband.FCStd"))
    parts = {}
    for o in doc.Objects:
        if o.TypeId == "Part::Feature" and not o.Name.startswith("Antenna_keepout"):
            m = MeshPart.meshFromShape(Shape=o.Shape, LinearDeflection=0.05, AngularDeflection=0.15, Relative=False)
            m.write(os.path.join(OUT, o.Name + ".stl"))
            parts[o.Name] = material(o.Name)
    head = doc.getObject("Headform_NIOSH_medium")
    head.Mesh.write(os.path.join(OUT, "Headform.stl"))
    parts["Headform"] = "skin"
    json.dump(parts, open(os.path.join(HERE, "parts.json"), "w"), indent=1)
    print("exported", len(parts), "parts to", OUT)


main()
