"""Photo-real pictures of the EpiProt headband on the NIOSH head (Blender 5.x, Cycles).

Run export_render_meshes.py (FreeCAD) first. Then:
  blender.exe -b -P device-firmware/cad/render/render_blender.py -- [view ...] [--samples N] [--res W H]
views: hero (three-quarter from behind), side (right side), closeup (right side body), xray (see-through
body: battery, board, flex cable), back. Writes device-firmware/cad/render/epiprot_<view>.png
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.join(HERE, "meshes")
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SAMPLES, RES = 128, (1600, 1200)
views = []
i = 0
while i < len(args):
    if args[i] == "--samples":
        SAMPLES = int(args[i + 1]); i += 2
    elif args[i] == "--res":
        RES = (int(args[i + 1]), int(args[i + 2])); i += 3
    else:
        views.append(args[i]); i += 1
views = views or ["hero", "side", "closeup", "xray"]


def principled(name, base, rough=0.5, metal=0.0, **kw):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k, v in kw.items():
        b.inputs[k].default_value = v
    return m


def materials():
    M = {
        "skin": principled("skin", (0.62, 0.40, 0.30), 0.5, **{"Subsurface Weight": 0.25,
                                                               "Subsurface Radius": (0.004, 0.0015, 0.0008),
                                                               "Subsurface Scale": 1.0}),
        "silicone": principled("silicone", (0.035, 0.038, 0.042), 0.62, **{"Coat Weight": 0.08, "Coat Roughness": 0.3,
                                                                          "Sheen Weight": 0.15}),
        "silicone_light": principled("silicone_light", (0.16, 0.17, 0.19), 0.55),
        "hydrogel": principled("hydrogel", (0.62, 0.86, 0.96), 0.12, **{"Transmission Weight": 0.55, "IOR": 1.36}),
        "steel": principled("steel", (0.80, 0.80, 0.82), 0.22, 1.0),
        "gold": principled("gold", (1.0, 0.76, 0.33), 0.18, 1.0),
        "led": principled("led", (0.2, 1.0, 0.4), 0.3, **{"Emission Color": (0.2, 1.0, 0.4, 1), "Emission Strength": 25.0}),
        "battery": principled("battery", (0.78, 0.78, 0.80), 0.35, 0.7),
        "pcb": principled("pcb", (0.02, 0.22, 0.07), 0.38),
        "carrier": principled("carrier", (0.90, 0.90, 0.92), 0.45, **{"Transmission Weight": 0.35}),
        "flex": principled("flex", (0.85, 0.42, 0.05), 0.3, **{"Transmission Weight": 0.2}),
        "titanium": principled("titanium", (0.62, 0.62, 0.65), 0.28, 1.0),
        "shield": principled("shield", (0.86, 0.86, 0.88), 0.25, 0.95),
        "chip": principled("chip", (0.03, 0.03, 0.035), 0.4),
    }
    # see-through silicone for the x-ray view
    xs = principled("silicone_xray", (0.05, 0.06, 0.07), 0.25, **{"Transmission Weight": 0.92, "IOR": 1.05, "Alpha": 0.35})
    M["silicone_xray"] = xs
    return M


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    M = materials()
    parts = json.load(open(os.path.join(HERE, "parts.json")))
    objs = {}
    for name, mat in parts.items():
        bpy.ops.wm.stl_import(filepath=os.path.join(MESH, name + ".stl"))
        o = bpy.context.selected_objects[0]
        o.name = name
        o.scale = (0.001, 0.001, 0.001)                       # model is in mm, Blender works in m
        o.data.materials.append(M[mat])
        bpy.context.view_layer.objects.active = o
        if mat in ("silicone", "skin", "hydrogel", "silicone_light", "carrier"):
            bpy.ops.object.shade_smooth()
            mod = o.modifiers.new("smooth_normals", "WEIGHTED_NORMAL")
            mod.keep_sharp = False
            if mat == "silicone":
                o.modifiers.new("soft_edges", "SMOOTH").factor = 0.35
        objs[name] = (o, mat)
    # studio: light grey cyclorama, soft key, rim, fill
    world = bpy.data.worlds.new("studio"); sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.83, 0.85, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25

    def area(name, loc, energy, size, color=(1, 1, 1)):
        bpy.ops.object.light_add(type="AREA", location=loc)
        L = bpy.context.object; L.name = name
        L.data.energy = energy; L.data.size = size; L.data.color = color
        d = Vector((0, -0.03, -0.03)) - Vector(loc)
        L.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    area("key", (-0.55, -0.55, 0.45), 22, 0.9, (1.0, 0.97, 0.92))
    area("rim", (0.45, -0.25, 0.55), 14, 0.5, (0.9, 0.95, 1.0))
    area("fill", (0.6, 0.5, 0.1), 6, 1.2)
    area("rim2", (-0.5, 0.4, 0.3), 5, 0.6)
    sc.render.engine = "CYCLES"
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    try:                                                     # GPU if there is one
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dev in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = dev
                prefs.get_devices()
                if any(d.type == dev for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = True
                    sc.cycles.device = "GPU"
                    break
            except Exception:
                continue
    except Exception:
        pass
    return sc, objs, M


def camera(sc, name, target, direction, dist, lens):
    d = Vector(direction).normalized()
    loc = Vector(target) + d * dist
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object; cam.name = name
    cam.data.lens = lens
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = dist
    cam.data.dof.aperture_fstop = 8.0
    cam.rotation_euler = (Vector(target) - loc).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    return cam


VIEWS = {   # target (m), direction from target to camera, distance (m), lens (mm)
    "hero": ((0.0, -0.03, -0.01), (-0.55, -0.80, 0.22), 0.80, 70),
    "back": ((0.0, -0.04, -0.01), (0.0, -1.0, 0.12), 0.80, 70),
    "side": ((0.0, -0.01, 0.0), (1.0, -0.12, 0.08), 0.85, 70),
    "closeup": ((0.06, -0.025, -0.035), (0.85, -0.45, 0.18), 0.42, 85),
    "xray": ((0.06, -0.025, -0.035), (0.90, -0.35, 0.12), 0.42, 85),
}


def main():
    sc, objs, M = build_scene()
    for v in views:
        tgt, d, dist, lens = VIEWS[v]
        camera(sc, "cam_" + v, tgt, d, dist, lens)
        for name, (o, mat) in objs.items():
            o.hide_render = (mat in ("battery", "pcb", "carrier", "flex", "titanium", "shield", "chip") and v != "xray")
            if mat == "silicone":
                o.data.materials[0] = M["silicone_xray"] if v == "xray" else M["silicone"]
            if mat == "carrier":
                o.hide_render = True              # carrier walls would hide the cell and board in the x-ray
        sc.render.filepath = os.path.join(HERE, f"epiprot_{v}.png")
        bpy.ops.render.render(write_still=True)
        print("wrote", sc.render.filepath, "device", sc.cycles.device)


main()
