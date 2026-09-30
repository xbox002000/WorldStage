"""Blender (headless) -> the low-poly rigged cast for the Three.js presentation runtime, as glTF binaries.

    blender -b --factory-startup --python runtime/blender/build_cast.py -- <out dir>

person.glb  an armature (hips, spine, neck, head, upper arms, forearms, hands, thighs, shins) with rigid-skinned
            parts; materials "cloth", "skin", "trousers", "hair" (the runtime tints cloth per character)
dog.glb     body, neck, head, ears, tail, four legs, and a "mouth" bone where a carried thing is attached
props       wallet, phone, diary, key, watch, ring, ticket, package, sword, cup, letter, and a plain "thing":
            each its own silhouette, so a model (or a viewer) can tell them apart

Blender makes the assets; it decides nothing about the world. The same script and Blender version give the same
files (their hashes go into render requests).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

OUT = Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else Path("assets")


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name: str, rgb: tuple[float, float, float], rough: float = 0.8) -> bpy.types.Material:
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    return m


def part(name: str, kind: str, size: tuple[float, float, float], at: Vector, mat: bpy.types.Material,
         bone: str, obj_parts: list, segments: int = 12) -> None:
    """A mesh piece (box, cylinder along z, or sphere) at `at`, rigidly bound to `bone`."""
    bm = bmesh.new()
    if kind == "box":
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=min(size) * 0.18, segments=2, affect="EDGES")
    elif kind == "cyl":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=size[0], radius2=size[1], depth=size[2])
    else:
        bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=segments // 2 + 2, radius=1.0)
        bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    obj_parts.append((name, bm, mat, bone))


def build(name: str, bones: list[tuple[str, str | None, Vector, Vector]], pieces: list, out: Path) -> None:
    """bones: (name, parent, head, tail) in rest pose; pieces: from part(); one skinned mesh, rigid weights."""
    arm_data = bpy.data.armatures.new(name + "_rig")
    rig = bpy.data.objects.new(name + "_rig", arm_data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    made = {}
    for bname, parent, head, tail in bones:
        eb = arm_data.edit_bones.new(bname)
        eb.head, eb.tail = head, tail
        if parent:
            eb.parent = made[parent]
        made[bname] = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    whole = bmesh.new()
    mats, groups = [], {}
    for _pname, bm, mat, bone in pieces:
        if mat.name not in [m.name for m in mats]:
            mats.append(mat)
        mi = [m.name for m in mats].index(mat.name)
        for f in bm.faces:
            f.material_index = mi
        start = len(whole.verts)
        tmp = bpy.data.meshes.new("tmp")
        bm.to_mesh(tmp)
        whole.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        whole.verts.ensure_lookup_table()
        groups.setdefault(bone, []).extend(range(start, len(whole.verts)))
        bm.free()
    # triangulate here, with fixed methods: left to the exporter, the triangle order changes from run to run
    bmesh.ops.triangulate(whole, faces=list(whole.faces), quad_method="BEAUTY", ngon_method="BEAUTY")
    whole.to_mesh(mesh)
    whole.free()
    for m in mats:
        mesh.materials.append(m)
    for poly in mesh.polygons:
        poly.use_smooth = True
    for bone, idx in groups.items():
        vg = obj.vertex_groups.new(name=bone)
        vg.add(idx, 1.0, "REPLACE")
    mod = obj.modifiers.new("rig", "ARMATURE")
    mod.object = rig
    # not parented to the rig: glTF wants a skinned mesh at the root (the skin carries the binding)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB", use_selection=True, export_skins=True,
                              export_animations=False, export_yup=True, export_apply=False)


V = Vector


def person(out: Path) -> None:
    reset()
    cloth, skin = material("cloth", (0.8, 0.8, 0.8)), material("skin", (0.96, 0.8, 0.68), 0.6)
    trousers, hair = material("trousers", (0.2, 0.22, 0.3)), material("hair", (0.12, 0.1, 0.12), 0.5)
    # Blender: z up, the figure faces +x (the runtime's yaw 0)
    bones = [("hips", None, V((0, 0, 0.92)), V((0, 0, 1.05))),
             ("spine", "hips", V((0, 0, 1.05)), V((0, 0, 1.45))),
             ("neck", "spine", V((0, 0, 1.45)), V((0, 0, 1.55))),
             ("head", "neck", V((0, 0, 1.55)), V((0, 0, 1.85))),
             # facing +x with z up, the figure's left is +y (0.1 had the sides the wrong way round)
             ("upper_arm.L", "spine", V((0, 0.23, 1.42)), V((0, 0.25, 1.12))),
             ("forearm.L", "upper_arm.L", V((0, 0.25, 1.12)), V((0, 0.26, 0.86))),
             ("hand.L", "forearm.L", V((0, 0.26, 0.86)), V((0, 0.26, 0.78))),
             ("upper_arm.R", "spine", V((0, -0.23, 1.42)), V((0, -0.25, 1.12))),
             ("forearm.R", "upper_arm.R", V((0, -0.25, 1.12)), V((0, -0.26, 0.86))),
             ("hand.R", "forearm.R", V((0, -0.26, 0.86)), V((0, -0.26, 0.78))),
             ("thigh.L", "hips", V((0, 0.1, 0.92)), V((0, 0.1, 0.48))),
             ("shin.L", "thigh.L", V((0, 0.1, 0.48)), V((0, 0.1, 0.06))),
             ("thigh.R", "hips", V((0, -0.1, 0.92)), V((0, -0.1, 0.48))),
             ("shin.R", "thigh.R", V((0, -0.1, 0.48)), V((0, -0.1, 0.06)))]
    p: list = []
    part("pelvis", "box", (0.24, 0.36, 0.18), V((0, 0, 0.98)), trousers, "hips", p)
    part("torso", "box", (0.26, 0.4, 0.46), V((0, 0, 1.24)), cloth, "spine", p)
    part("neck", "cyl", (0.055, 0.05, 0.1), V((0, 0, 1.5)), skin, "neck", p)
    part("head", "sphere", (0.13, 0.12, 0.15), V((0.01, 0, 1.68)), skin, "head", p)
    part("hair", "sphere", (0.135, 0.125, 0.09), V((-0.015, 0, 1.76)), hair, "head", p)
    part("nose", "sphere", (0.03, 0.022, 0.028), V((0.135, 0, 1.67)), skin, "head", p)
    for side, y in (("L", 1), ("R", -1)):
        part(f"eye.{side}", "sphere", (0.018, 0.018, 0.02), V((0.118, 0.045 * y, 1.71)), hair, "head", p)
        part(f"arm.{side}", "cyl", (0.055, 0.048, 0.3), V((0, 0.24 * y, 1.27)), cloth, f"upper_arm.{side}", p)
        part(f"fore.{side}", "cyl", (0.045, 0.04, 0.26), V((0, 0.255 * y, 0.99)), skin, f"forearm.{side}", p)
        part(f"hand.{side}", "sphere", (0.05, 0.04, 0.055), V((0, 0.26 * y, 0.82)), skin, f"hand.{side}", p)
        part(f"thigh.{side}", "cyl", (0.075, 0.065, 0.44), V((0, 0.1 * y, 0.7)), trousers, f"thigh.{side}", p)
        part(f"shin.{side}", "cyl", (0.06, 0.055, 0.42), V((0, 0.1 * y, 0.27)), trousers, f"shin.{side}", p)
        part(f"shoe.{side}", "box", (0.2, 0.09, 0.07), V((0.04, 0.1 * y, 0.035)), hair, f"shin.{side}", p)
    build("person", bones, p, out / "person.glb")


def dog(out: Path) -> None:
    reset()
    fur, dark = material("fur", (0.85, 0.62, 0.38)), material("dark", (0.5, 0.33, 0.18))
    light, nose = material("light", (0.96, 0.85, 0.66)), material("nose", (0.1, 0.08, 0.08), 0.4)
    bones = [("body", None, V((-0.25, 0, 0.36)), V((0.2, 0, 0.36))),
             ("neck", "body", V((0.2, 0, 0.38)), V((0.3, 0, 0.46))),
             ("head", "neck", V((0.3, 0, 0.46)), V((0.5, 0, 0.46))),
             ("mouth", "head", V((0.5, 0, 0.41)), V((0.56, 0, 0.41))),
             ("ear.L", "head", V((0.33, 0.07, 0.55)), V((0.33, 0.09, 0.45))),
             ("ear.R", "head", V((0.33, -0.07, 0.55)), V((0.33, -0.09, 0.45))),
             ("tail", "body", V((-0.27, 0, 0.42)), V((-0.4, 0, 0.62)))]
    for n, (x, y) in {"leg.FL": (0.16, 0.08), "leg.FR": (0.16, -0.08), "leg.BL": (-0.2, 0.08), "leg.BR": (-0.2, -0.08)}.items():
        bones.append((n, "body", V((x, y, 0.3)), V((x, y, 0.02))))
    p: list = []
    part("body", "sphere", (0.3, 0.13, 0.13), V((-0.03, 0, 0.36)), fur, "body", p)
    part("chest", "sphere", (0.12, 0.1, 0.1), V((0.13, 0, 0.32)), light, "body", p)
    part("neck", "cyl", (0.07, 0.06, 0.14), V((0.25, 0, 0.42)), fur, "neck", p)
    part("skull", "sphere", (0.11, 0.1, 0.1), V((0.36, 0, 0.48)), fur, "head", p)
    part("snout", "sphere", (0.08, 0.055, 0.05), V((0.46, 0, 0.44)), light, "head", p)
    part("nose", "sphere", (0.022, 0.025, 0.02), V((0.535, 0, 0.455)), nose, "head", p)
    for side, y in (("L", 1), ("R", -1)):
        part(f"eye.{side}", "sphere", (0.016, 0.016, 0.018), V((0.43, 0.05 * y, 0.51)), nose, "head", p)
        part(f"ear.{side}", "box", (0.05, 0.03, 0.11), V((0.33, 0.085 * y, 0.5)), dark, f"ear.{side}", p)
    part("tail", "cyl", (0.025, 0.012, 0.24), V((-0.34, 0, 0.52)), fur, "tail", p)
    for n, (x, y) in {"leg.FL": (0.16, 0.08), "leg.FR": (0.16, -0.08), "leg.BL": (-0.2, 0.08), "leg.BR": (-0.2, -0.08)}.items():
        part(n, "cyl", (0.035, 0.03, 0.28), V((x, y, 0.16)), fur, n, p)
        part(n + ".paw", "sphere", (0.04, 0.035, 0.022), V((x + 0.015, y, 0.022)), light, n, p)
    build("dog", bones, p, out / "dog.glb")


def prop(out: Path, name: str, pieces: list) -> None:
    """A thing a hand or a mouth can carry, with its own silhouette (a wallet is not a phone). Its origin is where it
    rests on the floor; the runtime attaches it by that point. (The caller starts a fresh file.)"""
    bones = [("root", None, V((0, 0, 0)), V((0, 0, 0.05)))]
    p: list = []
    for pname, kind, size, at, mat, *seg in pieces:
        part(pname, kind, size, at, mat, "root", p, *seg)
    build(name, bones, p, out / f"{name}.glb")


def props(out: Path) -> None:
    def mats():
        return {"leather": material("leather", (0.36, 0.2, 0.11), 0.7), "gold": material("metal", (0.85, 0.7, 0.3), 0.3),
                "steel": material("steel", (0.7, 0.72, 0.75), 0.25), "black": material("black", (0.06, 0.06, 0.07), 0.4),
                "paper": material("paper", (0.93, 0.9, 0.82), 0.9), "card": material("card", (0.72, 0.55, 0.36), 0.9),
                "red": material("red", (0.7, 0.12, 0.1), 0.6), "blue": material("blue", (0.15, 0.3, 0.6), 0.6),
                "white": material("white", (0.95, 0.95, 0.95), 0.5), "wood": material("wood", (0.45, 0.3, 0.18), 0.8)}
    shapes = {
        "wallet": [("wallet", "box", (0.18, 0.11, 0.035), V((0, 0, 0.0175)), "leather"),
                   ("clasp", "sphere", (0.012, 0.012, 0.008), V((0.07, 0, 0.036)), "gold")],
        "phone": [("body", "box", (0.08, 0.16, 0.012), V((0, 0, 0.006)), "black"),
                  ("screen", "box", (0.07, 0.14, 0.002), V((0, 0, 0.013)), "blue")],
        "diary": [("cover", "box", (0.16, 0.22, 0.035), V((0, 0, 0.0175)), "red"),
                  ("pages", "box", (0.15, 0.21, 0.03), V((0.006, 0, 0.0175)), "paper"),
                  ("strap", "box", (0.03, 0.225, 0.037), V((0.05, 0, 0.0185)), "leather")],
        "key": [("ring", "cyl", (0.018, 0.018, 0.006), V((0, 0, 0.003)), "steel", 16),
                ("shaft", "box", (0.06, 0.012, 0.004), V((0.045, 0, 0.003)), "steel"),
                ("bit", "box", (0.012, 0.022, 0.004), V((0.07, 0.008, 0.003)), "steel")],
        "watch": [("face", "cyl", (0.022, 0.022, 0.01), V((0, 0, 0.005)), "steel", 16),
                  ("glass", "cyl", (0.018, 0.018, 0.002), V((0, 0, 0.011)), "white", 16),
                  ("strap", "box", (0.02, 0.16, 0.004), V((0, 0, 0.002)), "black")],
        "ring": [("band", "cyl", (0.012, 0.012, 0.006), V((0, 0, 0.003)), "gold", 16),
                 ("stone", "sphere", (0.006, 0.006, 0.006), V((0, 0, 0.009)), "white")],
        "ticket": [("slip", "box", (0.14, 0.06, 0.003), V((0, 0, 0.0015)), "paper"),
                   ("stripe", "box", (0.02, 0.061, 0.0035), V((-0.04, 0, 0.0018)), "red")],
        "package": [("box", "box", (0.3, 0.22, 0.16), V((0, 0, 0.08)), "card"),
                    ("tape", "box", (0.305, 0.04, 0.162), V((0, 0, 0.081)), "paper")],
        "sword": [("blade", "box", (0.75, 0.03, 0.008), V((0.2, 0, 0.012)), "steel"),
                  ("guard", "box", (0.02, 0.12, 0.02), V((-0.18, 0, 0.012)), "gold"),
                  ("grip", "cyl", (0.013, 0.013, 0.16), V((-0.27, 0, 0.012)), "wood")],
        "cup": [("cup", "cyl", (0.04, 0.035, 0.1), V((0, 0, 0.05)), "white", 16),
                ("handle", "box", (0.02, 0.008, 0.05), V((0.048, 0, 0.055)), "white")],
        "letter": [("envelope", "box", (0.16, 0.1, 0.004), V((0, 0, 0.002)), "paper"),
                   ("seal", "cyl", (0.012, 0.012, 0.002), V((0, 0, 0.005)), "red", 12)],
        "thing": [("box", "box", (0.12, 0.12, 0.08), V((0, 0, 0.04)), "blue")],
    }
    for name, pieces in shapes.items():
        reset()
        m = mats()  # materials belong to the fresh file each prop is built in
        prop_pieces = [(pn, kind, size, at, m[mat], *seg) for pn, kind, size, at, mat, *seg in pieces]
        prop(out, name, prop_pieces)


if __name__ == "__main__":
    person(OUT)
    dog(OUT)
    props(OUT)
    print("built", sorted(x.name for x in OUT.glob("*.glb")))
