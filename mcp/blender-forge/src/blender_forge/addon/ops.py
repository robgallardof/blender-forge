"""Operations the bridge may run inside Blender. Main thread only.

Each operation takes a dict of JSON arguments and returns a JSON-able dict. Angles are
degrees on the wire and radians inside Blender. Nothing here deletes files, touches the
network or saves over the open .blend unless an argument asks for it explicitly.
"""
import contextlib
import io
import math
import os
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

OPERATIONS = {}


class OpError(Exception):
    def __init__(self, message, code="BAD_ARGUMENTS"):
        super().__init__(message)
        self.code = code


def operation(name):
    def wrap(func):
        OPERATIONS[name] = func
        return func
    return wrap


# ------------------------------------------------------------------ helpers

def vec3(value, label, default=None):
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(isinstance(v, (int, float)) for v in value):
        raise OpError(f"{label} must be three numbers")
    return tuple(float(v) for v in value)


def color(value, label="color"):
    if value is None:
        return None
    if isinstance(value, str):
        h = value.lstrip("#")
        if len(h) not in (6, 8):
            raise OpError(f"{label}: use #RRGGBB")
        rgba = [int(h[i:i + 2], 16) / 255 for i in range(0, len(h), 2)]
        # Hex colours are sRGB; Blender colour sockets are linear.
        rgba[:3] = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgba[:3]]
        return tuple(rgba + [1.0] * (4 - len(rgba)))
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        return tuple(float(v) for v in value) + ((1.0,) if len(value) == 3 else ())
    raise OpError(f"{label} must be #RRGGBB or [r, g, b(, a)]")


def get_object(name):
    obj = bpy.data.objects.get(name or "")
    if obj is None:
        raise OpError(f"no object named {name!r}", "NOT_FOUND")
    return obj


def unique_name(base, own=None):
    """`base`, or base.001… when another object already has it. `own` is the object being renamed."""
    existing = bpy.data.objects.get(base)
    if existing is None or existing == own:
        return base
    i = 1
    while bpy.data.objects.get(f"{base}.{i:03}") not in (None, own):
        i += 1
    return f"{base}.{i:03}"


def apply_transform(obj, args):
    loc = vec3(args.get("location"), "location")
    rot = vec3(args.get("rotation"), "rotation")
    scl = args.get("scale")
    if isinstance(scl, (int, float)):
        scl = (float(scl),) * 3
    scl = vec3(scl, "scale")
    if args.get("relative"):
        if loc:
            obj.location = obj.location + Vector(loc)
        if rot:
            obj.rotation_euler = [a + math.radians(b) for a, b in zip(obj.rotation_euler, rot)]
        if scl:
            obj.scale = [a * b for a, b in zip(obj.scale, scl)]
    else:
        if loc:
            obj.location = loc
        if rot:
            obj.rotation_euler = [math.radians(v) for v in rot]
        if scl:
            obj.scale = scl


def describe(obj, detail=False):
    bpy.context.view_layer.update()  # dimensions/matrices are stale until the depsgraph runs
    info = {"name": obj.name, "type": obj.type, "location": [round(v, 4) for v in obj.location],
            "rotation": [round(math.degrees(v), 3) for v in obj.rotation_euler],
            "scale": [round(v, 4) for v in obj.scale], "dimensions": [round(v, 4) for v in obj.dimensions],
            "parent": obj.parent.name if obj.parent else None, "visible": not obj.hide_render,
            "collection": obj.users_collection[0].name if obj.users_collection else None}
    if obj.type == "MESH":
        info["materials"] = [s.material.name for s in obj.material_slots if s.material]
        info["modifiers"] = [{"name": m.name, "type": m.type} for m in obj.modifiers]
        if detail:
            mesh = obj.data
            info["mesh"] = {"vertices": len(mesh.vertices), "edges": len(mesh.edges), "faces": len(mesh.polygons)}
    elif obj.type == "LIGHT":
        info["light"] = {"type": obj.data.type, "energy": obj.data.energy, "color": list(obj.data.color)}
    elif obj.type == "CAMERA":
        info["camera"] = {"lens": obj.data.lens, "active": bpy.context.scene.camera == obj}
    if detail:
        info["custom"] = {k: obj[k] for k in obj.keys() if isinstance(obj[k], (str, int, float))}
    return info


def link(obj, collection=None):
    target = bpy.context.scene.collection
    if collection:
        target = bpy.data.collections.get(collection)
        if target is None:
            target = bpy.data.collections.new(collection)
            bpy.context.scene.collection.children.link(target)
    target.objects.link(obj)


def safe_path(value, label="path", must_exist=False):
    if not isinstance(value, str) or not value.strip():
        raise OpError(f"{label} is required")
    path = Path(os.path.expanduser(value)).resolve()
    if must_exist and not path.is_file():
        raise OpError(f"{label}: {path} does not exist", "NOT_FOUND")
    return path


# ------------------------------------------------------------------ scene

@operation("status")
def status(args):
    scene = bpy.context.scene
    return {"blender": bpy.app.version_string, "file": bpy.data.filepath or None, "dirty": bpy.data.is_dirty,
            "background": bpy.app.background, "scene": scene.name, "objects": len(scene.objects),
            "engine": scene.render.engine, "frame_range": [scene.frame_start, scene.frame_end],
            "camera": scene.camera.name if scene.camera else None,
            "python_enabled": bool(args.get("_python_enabled"))}


@operation("scene_info")
def scene_info(args):
    scene = bpy.context.scene
    objs = [describe(o) for o in scene.objects]
    limit = int(args.get("limit", 200))
    world = scene.world
    return {"scene": scene.name, "unit_scale": scene.unit_settings.scale_length, "count": len(objs),
            "objects": objs[:limit], "truncated": len(objs) > limit,
            "materials": [m.name for m in bpy.data.materials if m.users],
            "collections": [c.name for c in bpy.data.collections],
            "world": world.name if world else None, "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y]}


@operation("object_info")
def object_info(args):
    return describe(get_object(args.get("name")), detail=True)


@operation("new_scene")
def new_scene(args):
    """Start from an empty scene (keeps nothing). Only when asked: the server requires confirm."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.get("name"):
        bpy.context.scene.name = args["name"]
    return {"scene": bpy.context.scene.name, "objects": 0}


# ------------------------------------------------------------------ modeling

PRIMITIVES = {
    "cube": lambda a: bpy.ops.mesh.primitive_cube_add(size=a.get("size", 2.0)),
    "plane": lambda a: bpy.ops.mesh.primitive_plane_add(size=a.get("size", 2.0)),
    "uv_sphere": lambda a: bpy.ops.mesh.primitive_uv_sphere_add(radius=a.get("radius", 1.0),
                                                               segments=int(a.get("segments", 32)),
                                                               ring_count=int(a.get("rings", 16))),
    "ico_sphere": lambda a: bpy.ops.mesh.primitive_ico_sphere_add(radius=a.get("radius", 1.0),
                                                                 subdivisions=int(a.get("subdivisions", 2))),
    "cylinder": lambda a: bpy.ops.mesh.primitive_cylinder_add(radius=a.get("radius", 1.0), depth=a.get("depth", 2.0),
                                                             vertices=int(a.get("vertices", 32))),
    "cone": lambda a: bpy.ops.mesh.primitive_cone_add(radius1=a.get("radius", 1.0), radius2=a.get("radius_top", 0.0),
                                                     depth=a.get("depth", 2.0), vertices=int(a.get("vertices", 32))),
    "torus": lambda a: bpy.ops.mesh.primitive_torus_add(major_radius=a.get("radius", 1.0),
                                                       minor_radius=a.get("tube", 0.25)),
    "circle": lambda a: bpy.ops.mesh.primitive_circle_add(radius=a.get("radius", 1.0), fill_type="NGON"),
    "grid": lambda a: bpy.ops.mesh.primitive_grid_add(size=a.get("size", 2.0), x_subdivisions=int(a.get("subdivisions", 10)),
                                                     y_subdivisions=int(a.get("subdivisions", 10))),
    "monkey": lambda a: bpy.ops.mesh.primitive_monkey_add(size=a.get("size", 2.0)),
}


@operation("create_object")
def create_object(args):
    kind = args.get("kind")
    if kind in PRIMITIVES:
        PRIMITIVES[kind](args)
        obj = bpy.context.active_object
    elif kind == "text":
        bpy.ops.object.text_add()
        obj = bpy.context.active_object
        obj.data.body = str(args.get("text", "Text"))
        obj.data.extrude = float(args.get("extrude", 0.0))
        obj.data.size = float(args.get("size", 1.0))
    elif kind == "empty":
        obj = bpy.data.objects.new("Empty", None)
        link(obj)
    else:
        raise OpError(f"kind must be one of {sorted([*PRIMITIVES, 'text', 'empty'])}")
    obj.name = unique_name(args.get("name") or obj.name, own=obj)
    if args.get("collection"):
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        link(obj, args["collection"])
    apply_transform(obj, args)
    if args.get("smooth") and obj.type == "MESH":
        for poly in obj.data.polygons:
            poly.use_smooth = True
    if args.get("material"):
        assign(obj, args["material"])
    return describe(obj)


@operation("create_mesh")
def create_mesh(args):
    """Any shape from raw data: vertices [[x,y,z],...] and faces [[i,j,k,...],...]."""
    verts, faces = args.get("vertices"), args.get("faces", [])
    if not isinstance(verts, list) or len(verts) < 3:
        raise OpError("vertices needs at least three [x, y, z] points")
    pts = [vec3(v, "vertex") for v in verts]
    if len(pts) > 200000:
        raise OpError("too many vertices (max 200000)")
    for f in faces:
        if not isinstance(f, list) or len(f) < 3 or not all(isinstance(i, int) and 0 <= i < len(pts) for i in f):
            raise OpError("each face is a list of 3+ vertex indices")
    edges = args.get("edges", [])
    mesh = bpy.data.meshes.new(args.get("name") or "Mesh")
    mesh.from_pydata(pts, edges, faces)
    mesh.validate()
    mesh.update()
    obj = bpy.data.objects.new(unique_name(args.get("name") or "Mesh"), mesh)
    link(obj, args.get("collection"))
    apply_transform(obj, args)
    if args.get("smooth"):
        for poly in mesh.polygons:
            poly.use_smooth = True
    if args.get("material"):
        assign(obj, args["material"])
    return describe(obj, detail=True)


@operation("transform")
def transform(args):
    obj = get_object(args.get("name"))
    apply_transform(obj, args)
    return describe(obj)


@operation("duplicate")
def duplicate(args):
    src = get_object(args.get("name"))
    count = max(1, min(int(args.get("count", 1)), 500))
    offset = Vector(vec3(args.get("offset"), "offset", (0.0, 0.0, 0.0)))
    linked = bool(args.get("linked", False))
    made = []
    for i in range(1, count + 1):
        obj = src.copy()
        if src.data is not None and not linked:
            obj.data = src.data.copy()
        obj.name = unique_name(args.get("new_name") or src.name)
        obj.location = src.location + offset * i
        for c in src.users_collection:
            c.objects.link(obj)
        made.append(obj.name)
    return {"created": made}


@operation("delete")
def delete(args):
    names = args.get("names") or []
    removed = []
    for name in names:
        obj = get_object(name)
        bpy.data.objects.remove(obj, do_unlink=True)
        removed.append(name)
    return {"deleted": removed}


@operation("parent")
def parent(args):
    child, par = get_object(args.get("child")), get_object(args.get("parent"))
    matrix = child.matrix_world.copy()
    child.parent = par
    child.matrix_world = matrix
    return describe(child)


@operation("join")
def join(args):
    names = args.get("names") or []
    if len(names) < 2:
        raise OpError("join needs at least two mesh names")
    objs = [get_object(n) for n in names]
    if any(o.type != "MESH" for o in objs):
        raise OpError("join only works on meshes")
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    target = bpy.context.active_object
    if args.get("new_name"):
        target.name = unique_name(args["new_name"], own=target)
    return describe(target, detail=True)


MODIFIER_TYPES = {"bevel": "BEVEL", "subdivision": "SUBSURF", "array": "ARRAY", "mirror": "MIRROR",
                  "solidify": "SOLIDIFY", "boolean": "BOOLEAN", "wireframe": "WIREFRAME", "decimate": "DECIMATE",
                  "screw": "SCREW", "smooth": "SMOOTH", "weld": "WELD", "displace": "DISPLACE",
                  "remesh": "REMESH", "triangulate": "TRIANGULATE", "skin": "SKIN", "simple_deform": "SIMPLE_DEFORM"}


@operation("add_modifier")
def add_modifier(args):
    obj = get_object(args.get("name"))
    kind = args.get("type")
    if kind not in MODIFIER_TYPES:
        raise OpError(f"type must be one of {sorted(MODIFIER_TYPES)}")
    mod = obj.modifiers.new(args.get("modifier_name") or kind.title(), MODIFIER_TYPES[kind])
    settings = args.get("settings") or {}
    applied = []
    for key, value in settings.items():
        if key.startswith("_") or not hasattr(mod, key):
            raise OpError(f"{kind} has no setting {key!r}")
        if key in ("object", "offset_object", "mirror_object") and isinstance(value, str):
            value = get_object(value)
        try:
            setattr(mod, key, value)
        except (TypeError, ValueError, AttributeError) as exc:
            raise OpError(f"{kind}.{key}: {exc}") from exc
        applied.append(key)
    mod_name = mod.name
    if args.get("apply"):
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return {"object": obj.name, "modifier": mod_name, "settings": applied, "applied": True}
    return {"object": obj.name, "modifier": mod_name, "settings": applied, "applied": False}


@operation("apply_modifiers")
def apply_modifiers(args):
    obj = get_object(args.get("name"))
    done = []
    with bpy.context.temp_override(object=obj, active_object=obj):
        for mod in list(obj.modifiers):
            bpy.ops.object.modifier_apply(modifier=mod.name)
            done.append(mod.name)
    return {"object": obj.name, "applied": done, **describe(obj, detail=True)}


@operation("shade")
def shade(args):
    obj = get_object(args.get("name"))
    if obj.type != "MESH":
        raise OpError("shade only works on meshes")
    smooth = args.get("mode", "smooth") == "smooth"
    for poly in obj.data.polygons:
        poly.use_smooth = smooth
    return {"object": obj.name, "smooth": smooth}


# ------------------------------------------------------------------ materials

def principled(mat):
    mat.use_nodes = True
    node = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if node is None:
        node = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None) \
            or mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(node.outputs[0], out.inputs[0])
    return node


INPUTS = {"base_color": "Base Color", "metallic": "Metallic", "roughness": "Roughness", "ior": "IOR",
          "alpha": "Alpha", "transmission": "Transmission Weight", "emission_color": "Emission Color",
          "emission_strength": "Emission Strength", "subsurface": "Subsurface Weight", "coat": "Coat Weight",
          "sheen": "Sheen Weight", "specular": "Specular IOR Level"}


@operation("material")
def material(args):
    name = args.get("name")
    if not name:
        raise OpError("name is required")
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    node = principled(mat)
    set_inputs = []
    for key, socket in INPUTS.items():
        if key not in args:
            continue
        value = args[key]
        if key.endswith("color"):
            value = color(value, key)
        elif not isinstance(value, (int, float)):
            raise OpError(f"{key} must be a number")
        node.inputs[socket].default_value = value
        set_inputs.append(key)
    if "base_color" in args:
        mat.diffuse_color = color(args["base_color"])
    if args.get("alpha", 1.0) < 1.0:
        mat.surface_render_method = "BLENDED" if hasattr(mat, "surface_render_method") else mat.blend_method
    if args.get("texture"):
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(safe_path(args["texture"], "texture", must_exist=True)), check_existing=True)
        mat.node_tree.links.new(tex.outputs["Color"], node.inputs["Base Color"])
        set_inputs.append("texture")
    if args.get("assign_to"):
        for obj_name in args["assign_to"]:
            assign(get_object(obj_name), name)
    return {"material": mat.name, "set": set_inputs, "users": mat.users}


def assign(obj, mat_name):
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        raise OpError(f"no material named {mat_name!r}", "NOT_FOUND")
    if not hasattr(obj.data, "materials"):
        raise OpError(f"{obj.name} cannot hold materials")
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


@operation("assign_material")
def assign_material(args):
    names = args.get("objects") or ([args["object"]] if args.get("object") else [])
    for n in names:
        assign(get_object(n), args.get("material"))
    return {"material": args.get("material"), "objects": names}


# ------------------------------------------------------------------ lights, camera, world

LIGHT_TYPES = {"point": "POINT", "sun": "SUN", "spot": "SPOT", "area": "AREA"}


def aim(obj, target):
    point = Vector(vec3(target, "look_at")) if isinstance(target, (list, tuple)) else get_object(target).location
    direction = point - obj.location
    if direction.length < 1e-6:
        return
    if abs(direction.normalized().z) > 0.999:
        # Straight down or up: track_quat is unstable here; keep +Y as screen-up.
        obj.rotation_euler = (0.0, 0.0, 0.0) if direction.z < 0 else (math.pi, 0.0, 0.0)
        return
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


@operation("add_light")
def add_light(args):
    kind = args.get("kind", "point")
    if kind not in LIGHT_TYPES:
        raise OpError(f"kind must be one of {sorted(LIGHT_TYPES)}")
    data = bpy.data.lights.new(args.get("name") or kind.title(), LIGHT_TYPES[kind])
    data.energy = float(args.get("energy", 1000 if kind != "sun" else 3))
    if args.get("color"):
        data.color = color(args["color"])[:3]
    if kind == "area":
        data.size = float(args.get("size", 1.0))
    if kind == "spot" and args.get("spot_size"):
        data.spot_size = math.radians(float(args["spot_size"]))
    obj = bpy.data.objects.new(unique_name(args.get("name") or kind.title()), data)
    link(obj, args.get("collection"))
    apply_transform(obj, args)
    if args.get("look_at") is not None:
        aim(obj, args["look_at"])
    return describe(obj)


@operation("light_rig")
def light_rig(args):
    """Three-point lighting around a target object or point."""
    target = args.get("target")
    center = get_object(target).location.copy() if isinstance(target, str) else Vector(vec3(target, "target", (0, 0, 0)))
    dist = float(args.get("distance", 6.0))
    power = float(args.get("energy", 1000))
    rig = [("Key", (dist * 0.8, -dist * 0.8, dist * 0.7), power, 2.0),
           ("Fill", (-dist, -dist * 0.4, dist * 0.4), power * 0.35, 3.0),
           ("Rim", (0.0, dist, dist * 0.8), power * 0.6, 1.5)]
    made = []
    for label, offset, energy, size in rig:
        made.append(add_light({"kind": "area", "name": f"{args.get('prefix', 'Rig')}{label}", "energy": energy,
                               "size": size, "location": list(center + Vector(offset)), "look_at": list(center)})["name"])
    return {"lights": made}


@operation("add_camera")
def add_camera(args):
    data = bpy.data.cameras.new(args.get("name") or "Camera")
    data.lens = float(args.get("lens", 50))
    obj = bpy.data.objects.new(unique_name(args.get("name") or "Camera"), data)
    link(obj, args.get("collection"))
    apply_transform(obj, args)
    if args.get("look_at") is not None:
        aim(obj, args["look_at"])
    if args.get("active", True):
        bpy.context.scene.camera = obj
    return describe(obj)


def bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type in ("MESH", "CURVE", "FONT", "SURFACE", "META")
           for c in o.bound_box]
    if not pts:
        pts = [o.location for o in objs] or [Vector((0, 0, 0))]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def is_backdrop(obj):
    """A floor or wall: a mesh that is flat along one axis."""
    dims = sorted(obj.dimensions)
    return obj.type == "MESH" and dims[2] > 0 and dims[0] <= dims[2] * 0.01


def scene_objects(names=None):
    if names:
        return [get_object(n) for n in names]
    objs = [o for o in bpy.context.scene.objects
            if o.type in ("MESH", "CURVE", "FONT", "SURFACE", "META") and not o.hide_render and o.name != "ForgeLook"]
    subjects = [o for o in objs if not is_backdrop(o)]
    return subjects or objs


@operation("frame_camera")
def frame_camera(args):
    """Point a camera at objects and back it off until they fit."""
    cam = get_object(args["camera"]) if args.get("camera") else bpy.context.scene.camera
    if cam is None or cam.type != "CAMERA":
        raise OpError("no camera; add one first", "NOT_FOUND")
    lo, hi = bounds(scene_objects(args.get("objects")))
    center, radius = (lo + hi) / 2, max((hi - lo).length / 2, 0.1)
    direction = Vector(vec3(args.get("direction"), "direction", (1.0, -1.0, 0.7))).normalized()
    fov = cam.data.angle
    dist = radius / math.sin(fov / 2) * float(args.get("margin", 1.1))
    cam.location = center + direction * dist
    aim(cam, list(center))
    cam.data.clip_end = max(cam.data.clip_end, dist * 4)
    return {"camera": cam.name, "center": list(center), "distance": round(dist, 3)}


@operation("world")
def world(args):
    scene = bpy.context.scene
    w = scene.world or bpy.data.worlds.new("World")
    scene.world = w
    w.use_nodes = True
    nodes, links = w.node_tree.nodes, w.node_tree.links
    bg = next((n for n in nodes if n.type == "BACKGROUND"), None) or nodes.new("ShaderNodeBackground")
    out = next((n for n in nodes if n.type == "OUTPUT_WORLD"), None) or nodes.new("ShaderNodeOutputWorld")
    links.new(bg.outputs[0], out.inputs[0])
    if args.get("color"):
        bg.inputs["Color"].default_value = color(args["color"])
    if "strength" in args:
        bg.inputs["Strength"].default_value = float(args["strength"])
    if args.get("hdri"):
        env = next((n for n in nodes if n.type == "TEX_ENVIRONMENT"), None) or nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(str(safe_path(args["hdri"], "hdri", must_exist=True)), check_existing=True)
        links.new(env.outputs["Color"], bg.inputs["Color"])
    return {"world": w.name, "hdri": bool(args.get("hdri"))}


# ------------------------------------------------------------------ render

ENGINES = {"eevee": "BLENDER_EEVEE", "cycles": "CYCLES", "workbench": "BLENDER_WORKBENCH"}


@operation("render_settings")
def render_settings(args):
    scene, r = bpy.context.scene, bpy.context.scene.render
    if args.get("engine"):
        if args["engine"] not in ENGINES:
            raise OpError(f"engine must be one of {sorted(ENGINES)}")
        r.engine = ENGINES[args["engine"]]
    if args.get("resolution"):
        r.resolution_x, r.resolution_y = (int(v) for v in args["resolution"])
    if "percentage" in args:
        r.resolution_percentage = int(args["percentage"])
    if "samples" in args:
        if r.engine == "CYCLES":
            scene.cycles.samples = int(args["samples"])
        elif hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = int(args["samples"])
    if "transparent" in args:
        r.film_transparent = bool(args["transparent"])
    if args.get("device") and r.engine == "CYCLES":
        scene.cycles.device = "GPU" if args["device"] == "gpu" else "CPU"
    if args.get("frame_range"):
        scene.frame_start, scene.frame_end = (int(v) for v in args["frame_range"])
    if args.get("fps"):
        r.fps = int(args["fps"])
    return {"engine": r.engine, "resolution": [r.resolution_x, r.resolution_y, r.resolution_percentage],
            "frame_range": [scene.frame_start, scene.frame_end], "fps": r.fps}


@contextlib.contextmanager
def quiet():
    """Blender prints render progress to stdout; keep it out of the bridge logs."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


@operation("render_still")
def render_still(args):
    scene = bpy.context.scene
    if args.get("camera"):
        scene.camera = get_object(args["camera"])
    if scene.camera is None:
        raise OpError("the scene has no camera; add_camera first", "NOT_FOUND")
    path = safe_path(args.get("path") or str(Path(tempfile.gettempdir()) / "blender-forge" / "render.png"))
    path.parent.mkdir(parents=True, exist_ok=True)
    old = (scene.render.filepath, scene.render.image_settings.file_format, scene.frame_current)
    try:
        scene.render.filepath = str(path)
        scene.render.image_settings.file_format = "PNG"
        if "frame" in args:
            scene.frame_set(int(args["frame"]))
        with quiet():
            bpy.ops.render.render(write_still=True)
    finally:
        scene.render.filepath, scene.render.image_settings.file_format = old[0], old[1]
        scene.frame_set(old[2])
    return {"path": str(path), "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x * scene.render.resolution_percentage // 100,
                           scene.render.resolution_y * scene.render.resolution_percentage // 100]}


VIEWS = {"front": (0, -1, 0.15), "back": (0, 1, 0.15), "left": (-1, 0, 0.15), "right": (1, 0, 0.15),
         "top": (0, 0, 1), "iso": (1, -1, 0.75), "iso_back": (-1, 1, 0.75)}


@operation("look")
def look(args):
    """Render the scene (or some objects) from several angles with a temporary camera.

    The open scene is left as it was: engine, resolution, camera and output path are restored.
    """
    scene, r = bpy.context.scene, bpy.context.scene.render
    views = args.get("views") or ["front", "right", "top", "iso"]
    bad = [v for v in views if v not in VIEWS]
    if bad:
        raise OpError(f"unknown views {bad}; use {sorted(VIEWS)}")
    if args.get("out_dir"):
        out_dir = safe_path(args["out_dir"], "out_dir")
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="blender-forge-look-"))
    saved = (r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, scene.camera, r.filepath,
             r.image_settings.file_format, r.film_transparent)
    data = bpy.data.cameras.new("ForgeLook")
    cam = bpy.data.objects.new("ForgeLook", data)
    scene.collection.objects.link(cam)
    files = []
    try:
        engine = args.get("engine", "workbench")
        r.engine = ENGINES.get(engine, "BLENDER_WORKBENCH")
        if r.engine == "BLENDER_WORKBENCH":
            shading = scene.display.shading
            shading.light = "STUDIO"
            shading.color_type = "MATERIAL"
        elif r.engine == "CYCLES":
            scene.cycles.samples = int(args.get("samples", 16))
        size = int(args.get("size", 512))
        r.resolution_x = r.resolution_y = size
        r.resolution_percentage = 100
        r.image_settings.file_format = "PNG"
        scene.camera = cam
        for view in views:
            frame_camera({"camera": cam.name, "objects": args.get("objects"), "direction": list(VIEWS[view]),
                          "margin": args.get("margin", 1.15)})
            target = out_dir / f"{view}.png"
            r.filepath = str(target)
            with quiet():
                bpy.ops.render.render(write_still=True)
            files.append({"view": view, "path": str(target)})
    finally:
        (r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, scene.camera, r.filepath,
         r.image_settings.file_format, r.film_transparent) = saved
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(data)
    return {"views": files, "engine": args.get("engine", "workbench")}


# ------------------------------------------------------------------ animation

@operation("keyframe")
def keyframe(args):
    obj = get_object(args.get("name"))
    frame = int(args.get("frame", bpy.context.scene.frame_current))
    apply_transform(obj, args)
    keyed = []
    for prop, key in (("location", "location"), ("rotation", "rotation_euler"), ("scale", "scale")):
        if args.get(prop) is not None:
            obj.keyframe_insert(data_path=key, frame=frame)
            keyed.append(prop)
    if not keyed:
        raise OpError("give location, rotation or scale to key")
    return {"object": obj.name, "frame": frame, "keyed": keyed}


@operation("turntable")
def turntable(args):
    """A camera that orbits a target over the frame range."""
    scene = bpy.context.scene
    frames = int(args.get("frames", 120))
    scene.frame_start, scene.frame_end = 1, frames
    target = args.get("target")
    lo, hi = bounds(scene_objects([target] if isinstance(target, str) else None))
    center, radius = (lo + hi) / 2, max((hi - lo).length / 2, 0.1)
    pivot = bpy.data.objects.new(unique_name("TurntablePivot"), None)
    scene.collection.objects.link(pivot)
    pivot.location = center
    cam = add_camera({"name": args.get("name", "TurntableCam"), "lens": args.get("lens", 50)})
    cam_obj = bpy.data.objects[cam["name"]]
    dist = radius / math.sin(cam_obj.data.angle / 2) * 1.2
    cam_obj.parent = pivot
    cam_obj.location = (0, -dist, dist * float(args.get("height", 0.35)))
    aim(cam_obj, [0, 0, 0])
    cam_obj.rotation_euler = (Vector((0, 0, 0)) - cam_obj.location).to_track_quat("-Z", "Y").to_euler()
    pivot.rotation_euler = (0, 0, 0)
    pivot.keyframe_insert("rotation_euler", frame=1)
    pivot.rotation_euler = (0, 0, math.radians(360))
    pivot.keyframe_insert("rotation_euler", frame=frames + 1)
    action = pivot.animation_data.action
    for curve in getattr(action, "fcurves", []):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"
    return {"camera": cam_obj.name, "pivot": pivot.name, "frames": frames}


@operation("render_animation")
def render_animation(args):
    scene, r = bpy.context.scene, bpy.context.scene.render
    if scene.camera is None:
        raise OpError("the scene has no camera", "NOT_FOUND")
    out = safe_path(args.get("path"), "path")
    fmt = args.get("format", "mp4")
    saved = (r.filepath, r.image_settings.file_format)
    try:
        if fmt == "mp4":
            r.image_settings.file_format = "FFMPEG"
            r.ffmpeg.format, r.ffmpeg.codec = "MPEG4", "H264"
            out.parent.mkdir(parents=True, exist_ok=True)
            r.filepath = str(out)
        elif fmt == "png":
            r.image_settings.file_format = "PNG"
            out.mkdir(parents=True, exist_ok=True)
            r.filepath = str(out / "frame_")
        else:
            raise OpError("format must be mp4 or png")
        with quiet():
            bpy.ops.render.render(animation=True)
    finally:
        r.filepath, r.image_settings.file_format = saved
    return {"path": str(out), "frames": [scene.frame_start, scene.frame_end], "format": fmt}


# ------------------------------------------------------------------ files

IMPORTERS = {".glb": lambda p: bpy.ops.import_scene.gltf(filepath=p), ".gltf": lambda p: bpy.ops.import_scene.gltf(filepath=p),
             ".fbx": lambda p: bpy.ops.import_scene.fbx(filepath=p), ".obj": lambda p: bpy.ops.wm.obj_import(filepath=p),
             ".stl": lambda p: bpy.ops.wm.stl_import(filepath=p), ".ply": lambda p: bpy.ops.wm.ply_import(filepath=p),
             ".usd": lambda p: bpy.ops.wm.usd_import(filepath=p), ".usdz": lambda p: bpy.ops.wm.usd_import(filepath=p),
             ".usda": lambda p: bpy.ops.wm.usd_import(filepath=p), ".usdc": lambda p: bpy.ops.wm.usd_import(filepath=p)}


@operation("import_file")
def import_file(args):
    path = safe_path(args.get("path"), must_exist=True)
    importer = IMPORTERS.get(path.suffix.lower())
    if importer is None:
        raise OpError(f"unsupported format {path.suffix}; use {sorted(IMPORTERS)}")
    before = set(bpy.data.objects.keys())
    with quiet():
        importer(str(path))
    new = sorted(set(bpy.data.objects.keys()) - before)
    for name in new:
        obj = bpy.data.objects[name]
        if args.get("credit"):
            obj["forge_credit"] = str(args["credit"])[:500]
    if new and (args.get("location") or args.get("scale")):
        roots = [bpy.data.objects[n] for n in new if bpy.data.objects[n].parent is None]
        for obj in roots:
            apply_transform(obj, args)
    return {"imported": new, "path": str(path)}


@operation("export_file")
def export_file(args):
    path = safe_path(args.get("path"))
    path.parent.mkdir(parents=True, exist_ok=True)
    names = args.get("objects")
    bpy.ops.object.select_all(action="DESELECT")
    if names:
        for n in names:
            get_object(n).select_set(True)
    selected = bool(names)
    ext = path.suffix.lower()
    with quiet():
        if ext in (".glb", ".gltf"):
            bpy.ops.export_scene.gltf(filepath=str(path), use_selection=selected,
                                      export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE")
        elif ext == ".fbx":
            bpy.ops.export_scene.fbx(filepath=str(path), use_selection=selected)
        elif ext == ".obj":
            bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=selected)
        elif ext == ".stl":
            bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=selected)
        elif ext == ".ply":
            bpy.ops.wm.ply_export(filepath=str(path), export_selected_objects=selected)
        elif ext in (".usd", ".usdc", ".usda", ".usdz"):
            bpy.ops.wm.usd_export(filepath=str(path), selected_objects_only=selected)
        else:
            raise OpError("export format must be glb, gltf, fbx, obj, stl, ply or usd")
    return {"path": str(path), "bytes": path.stat().st_size if path.exists() else 0, "selection": names or "all"}


@operation("save")
def save(args):
    """Save a copy by default; overwrite the open file only with overwrite=True."""
    if args.get("path"):
        path = safe_path(args["path"])
        if path.exists() and not args.get("overwrite"):
            raise OpError(f"{path} exists; pass overwrite=true to replace it", "WOULD_OVERWRITE")
        path.parent.mkdir(parents=True, exist_ok=True)
        if args.get("as_copy", True):
            bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
        else:
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
        return {"saved": str(path), "copy": args.get("as_copy", True)}
    if not bpy.data.filepath:
        raise OpError("the scene was never saved; pass a path")
    if not args.get("overwrite"):
        raise OpError("saving over the open file needs overwrite=true", "WOULD_OVERWRITE")
    bpy.ops.wm.save_mainfile()
    return {"saved": bpy.data.filepath, "copy": False}


@operation("open_file")
def open_file(args):
    path = safe_path(args.get("path"), must_exist=True)
    if bpy.data.is_dirty and not args.get("discard_changes"):
        raise OpError("the open scene has unsaved changes; save first or pass discard_changes=true", "UNSAVED_CHANGES")
    bpy.ops.wm.open_mainfile(filepath=str(path))
    return status({})


@operation("run_python")
def run_python(args):
    """Escape hatch. The bridge only lists this operation when the user enabled it."""
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        raise OpError("code is required")
    out = io.StringIO()
    scope = {"bpy": bpy, "__name__": "__forge__"}
    with contextlib.redirect_stdout(out):
        exec(compile(code, "<blender-forge>", "exec"), scope)  # noqa: S102 - opt-in by the user
    result = scope.get("result")
    return {"stdout": out.getvalue()[-20000:], "result": result if isinstance(result, (str, int, float, bool, list, dict, type(None))) else repr(result)}
