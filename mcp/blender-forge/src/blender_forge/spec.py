"""Scene specs for build_scene: validated before anything touches Blender.

A spec is plain JSON an agent can write from a description ("a low-poly desk with a lamp"):

    {"materials": [{"name": "Wood", "base_color": "#8a5a3b", "roughness": 0.6}],
     "objects": [{"kind": "cube", "name": "Desktop", "scale": [1.2, 0.6, 0.04],
                  "location": [0, 0, 0.75], "material": "Wood",
                  "modifiers": [{"type": "bevel", "settings": {"width": 0.02, "segments": 3}}]}],
     "lights": [{"kind": "area", "location": [3, -3, 4], "look_at": [0, 0, 0.7], "energy": 800}],
     "camera": {"look_at": "Desktop", "frame": true},
     "world": {"color": "#1d2230", "strength": 0.6},
     "render": {"engine": "eevee", "resolution": [1280, 720]}}

Order of application: materials, objects (with modifiers, parents), lights, camera, world, render.
"""

KINDS = {"cube", "plane", "uv_sphere", "ico_sphere", "cylinder", "cone", "torus", "circle", "grid", "monkey",
         "text", "empty", "mesh"}
LIGHTS = {"point", "sun", "spot", "area"}
MAX_ITEMS = 500


class SpecError(ValueError):
    pass


def _list(spec, key):
    value = spec.get(key, [])
    if not isinstance(value, list):
        raise SpecError(f"{key} must be a list")
    if len(value) > MAX_ITEMS:
        raise SpecError(f"{key}: at most {MAX_ITEMS} entries")
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise SpecError(f"{key}[{i}] must be an object")
    return value


def _vec(value, label):
    if value is None:
        return
    if isinstance(value, (int, float)) and label.endswith("scale"):
        return
    if not (isinstance(value, list) and len(value) == 3 and all(isinstance(v, (int, float)) for v in value)):
        raise SpecError(f"{label} must be [x, y, z]")


def validate(spec):
    """Return a list of the steps that will run; raise SpecError on the first problem."""
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    unknown = set(spec) - {"materials", "objects", "lights", "camera", "world", "render", "clear"}
    if unknown:
        raise SpecError(f"unknown top-level keys: {sorted(unknown)}")
    steps = []
    materials = {m.get("name") for m in _list(spec, "materials")}
    for i, m in enumerate(_list(spec, "materials")):
        if not isinstance(m.get("name"), str) or not m["name"]:
            raise SpecError(f"materials[{i}].name is required")
        steps.append(("material", m))
    names = set()
    for i, o in enumerate(_list(spec, "objects")):
        label = f"objects[{i}]"
        kind = o.get("kind")
        if kind not in KINDS:
            raise SpecError(f"{label}.kind must be one of {sorted(KINDS)}")
        if kind == "mesh" and not isinstance(o.get("vertices"), list):
            raise SpecError(f"{label}: kind mesh needs vertices and faces")
        for key in ("location", "rotation", "scale"):
            _vec(o.get(key), f"{label}.{key}")
        if o.get("material") and o["material"] not in materials:
            raise SpecError(f"{label}.material {o['material']!r} is not defined in materials")
        if o.get("parent") and o["parent"] not in names:
            raise SpecError(f"{label}.parent {o['parent']!r} must be an earlier object")
        if not isinstance(o.get("modifiers", []), list):
            raise SpecError(f"{label}.modifiers must be a list")
        if o.get("name"):
            names.add(o["name"])
        steps.append(("object", o))
    for i, light in enumerate(_list(spec, "lights")):
        if light.get("kind", "point") not in LIGHTS and light.get("kind") != "rig":
            raise SpecError(f"lights[{i}].kind must be one of {sorted(LIGHTS | {'rig'})}")
        steps.append(("light", light))
    if spec.get("camera") is not None:
        if not isinstance(spec["camera"], dict):
            raise SpecError("camera must be an object")
        steps.append(("camera", spec["camera"]))
    for key in ("world", "render"):
        if spec.get(key) is not None:
            if not isinstance(spec[key], dict):
                raise SpecError(f"{key} must be an object")
            steps.append((key, spec[key]))
    if not steps:
        raise SpecError("spec is empty")
    return steps
