"""blender-forge MCP server: model, light, render, animate and export in Blender from any agent.

Tools call the bridge running inside Blender (the extension in the UI, or a headless
Blender started by `start_headless`). Errors come back as {"error": {code, message, hint}}.
"""
import functools
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations

from . import assets, images, spec as specs
from .client import Client, ForgeError, Headless

INSTRUCTIONS = """blender-forge drives Blender. Start with forge_status. If no bridge is running, call
start_headless (no window) or ask the user to open Blender with the blender-forge extension.
Build with intent: describe the scene as a build_scene spec, or use the granular tools
(create_object, create_mesh, add_modifier, material, add_light, add_camera ...).
Always look before you say it is done: `look` renders several angles and returns a contact
sheet image; render_still returns the final image. Angles are degrees, sizes are metres.
Colors are #RRGGBB. Nothing is saved over the open .blend unless overwrite=true; delete and
new_scene need confirm=true. Poly Haven assets are CC0 and keep a credit property."""

mcp = FastMCP("blender-forge", instructions=INSTRUCTIONS)
client = Client()
headless = Headless()

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


def guarded(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ForgeError as exc:
            return exc.as_dict()
        except (specs.SpecError, ValueError) as exc:
            return {"error": {"code": "BAD_ARGUMENTS", "message": str(exc)}}
    return wrapper


def call(operation, **arguments):
    return client.call(operation, {k: v for k, v in arguments.items() if v is not None})


Vec = list[float]


# ------------------------------------------------------------------ session

@mcp.tool(annotations=READ)
@guarded
def forge_status() -> dict:
    """Is Blender connected? Version, open file, scene, object count, engine and the operations allowed."""
    pong = client.reachable()
    if not pong:
        raise ForgeError("no Blender bridge is listening", "BRIDGE_OFFLINE",
                         "Call start_headless, or open Blender with the blender-forge extension enabled.")
    info = call("status")
    info["operations"] = pong["operations"]
    info["headless"] = headless.proc is not None
    return info


@mcp.tool(annotations=WRITE)
@guarded
def start_headless(blend_file: str | None = None) -> dict:
    """Start a background Blender (no window) with the bridge, optionally opening a .blend file."""
    return headless.start(client, blend_file)


@mcp.tool(annotations=WRITE)
@guarded
def stop_headless() -> dict:
    """Stop the background Blender started by start_headless (unsaved changes are lost)."""
    return headless.stop()


@mcp.tool(annotations=READ)
@guarded
def scene_info(limit: int = 200) -> dict:
    """Objects (transform, dimensions, materials, modifiers), materials, collections, world and render size."""
    return call("scene_info", limit=limit)


@mcp.tool(annotations=READ)
@guarded
def object_info(name: str) -> dict:
    """Full details of one object, including mesh counts and custom properties."""
    return call("object_info", name=name)


@mcp.tool(annotations=DESTRUCTIVE)
@guarded
def new_scene(confirm: bool = False, name: str | None = None) -> dict:
    """Replace everything with an empty scene. Requires confirm=true; save first if needed."""
    if not confirm:
        raise ForgeError("new_scene discards the open scene", "CONFIRM_REQUIRED", "Pass confirm=true.")
    return call("new_scene", name=name)


# ------------------------------------------------------------------ modeling

@mcp.tool(annotations=WRITE)
@guarded
def create_object(kind: Literal["cube", "plane", "uv_sphere", "ico_sphere", "cylinder", "cone", "torus", "circle",
                                "grid", "monkey", "text", "empty"],
                  name: str | None = None, location: Vec | None = None, rotation: Vec | None = None,
                  scale: Vec | float | None = None, size: float | None = None, radius: float | None = None,
                  depth: float | None = None, vertices: int | None = None, text: str | None = None,
                  extrude: float | None = None, smooth: bool = False, material: str | None = None,
                  collection: str | None = None) -> dict:
    """Add a primitive, text or empty. Rotation in degrees. `material` must already exist."""
    return call("create_object", kind=kind, name=name, location=location, rotation=rotation, scale=scale, size=size,
                radius=radius, depth=depth, vertices=vertices, text=text, extrude=extrude, smooth=smooth,
                material=material, collection=collection)


@mcp.tool(annotations=WRITE)
@guarded
def create_mesh(vertices: list[Vec], faces: list[list[int]], name: str | None = None, location: Vec | None = None,
                rotation: Vec | None = None, scale: Vec | float | None = None, smooth: bool = False,
                material: str | None = None, collection: str | None = None) -> dict:
    """Any shape from raw geometry: vertices [[x,y,z],...] and faces as vertex index lists."""
    return call("create_mesh", vertices=vertices, faces=faces, name=name, location=location, rotation=rotation,
                scale=scale, smooth=smooth, material=material, collection=collection)


@mcp.tool(annotations=WRITE)
@guarded
def transform(name: str, location: Vec | None = None, rotation: Vec | None = None, scale: Vec | float | None = None,
              relative: bool = False) -> dict:
    """Move, rotate (degrees) or scale an object; relative=true adds to the current values."""
    return call("transform", name=name, location=location, rotation=rotation, scale=scale, relative=relative)


@mcp.tool(annotations=WRITE)
@guarded
def duplicate(name: str, count: int = 1, offset: Vec | None = None, new_name: str | None = None,
              linked: bool = False) -> dict:
    """Copy an object `count` times, each shifted by `offset`. linked=true shares the mesh data."""
    return call("duplicate", name=name, count=count, offset=offset, new_name=new_name, linked=linked)


@mcp.tool(annotations=DESTRUCTIVE)
@guarded
def delete(names: list[str], confirm: bool = False) -> dict:
    """Remove objects from the scene. Requires confirm=true."""
    if not confirm:
        raise ForgeError(f"delete would remove {names}", "CONFIRM_REQUIRED", "Pass confirm=true.")
    return call("delete", names=names)


@mcp.tool(annotations=WRITE)
@guarded
def parent(child: str, parent_name: str) -> dict:
    """Parent one object to another, keeping its world position."""
    return call("parent", child=child, parent=parent_name)


@mcp.tool(annotations=WRITE)
@guarded
def join(names: list[str], new_name: str | None = None) -> dict:
    """Join meshes into the first one."""
    return call("join", names=names, new_name=new_name)


@mcp.tool(annotations=WRITE)
@guarded
def add_modifier(name: str, type: Literal["bevel", "subdivision", "array", "mirror", "solidify", "boolean",
                                          "wireframe", "decimate", "screw", "smooth", "weld", "displace", "remesh",
                                          "triangulate", "skin", "simple_deform"],
                 settings: dict[str, Any] | None = None, apply: bool = False, modifier_name: str | None = None) -> dict:
    """Add a modifier. `settings` uses Blender property names, e.g. bevel {"width": 0.02, "segments": 3},
    array {"count": 5, "relative_offset_displace": [1.1, 0, 0]}, boolean {"operation": "DIFFERENCE",
    "object": "Cutter"}, subdivision {"levels": 2, "render_levels": 2}. apply=true bakes it."""
    return call("add_modifier", name=name, type=type, settings=settings or {}, apply=apply, modifier_name=modifier_name)


@mcp.tool(annotations=WRITE)
@guarded
def apply_modifiers(name: str) -> dict:
    """Bake every modifier of an object into its mesh."""
    return call("apply_modifiers", name=name)


@mcp.tool(annotations=WRITE)
@guarded
def shade(name: str, mode: Literal["smooth", "flat"] = "smooth") -> dict:
    """Smooth or flat shading for a mesh."""
    return call("shade", name=name, mode=mode)


# ------------------------------------------------------------------ materials, lights, camera, world

@mcp.tool(annotations=WRITE)
@guarded
def material(name: str, base_color: str | Vec | None = None, metallic: float | None = None,
             roughness: float | None = None, emission_color: str | Vec | None = None,
             emission_strength: float | None = None, alpha: float | None = None, transmission: float | None = None,
             ior: float | None = None, coat: float | None = None, sheen: float | None = None,
             texture: str | None = None, assign_to: list[str] | None = None) -> dict:
    """Create or update a Principled BSDF material (glass: transmission 1 + roughness 0; metal: metallic 1).
    `texture` is a local image used as base color. `assign_to` lists objects to receive it."""
    return call("material", name=name, base_color=base_color, metallic=metallic, roughness=roughness,
                emission_color=emission_color, emission_strength=emission_strength, alpha=alpha,
                transmission=transmission, ior=ior, coat=coat, sheen=sheen, texture=texture, assign_to=assign_to)


@mcp.tool(annotations=WRITE)
@guarded
def assign_material(material_name: str, objects: list[str]) -> dict:
    """Put an existing material on objects (first slot)."""
    return call("assign_material", material=material_name, objects=objects)


@mcp.tool(annotations=WRITE)
@guarded
def add_light(kind: Literal["point", "sun", "spot", "area"] = "point", name: str | None = None,
              location: Vec | None = None, rotation: Vec | None = None, energy: float | None = None,
              color: str | None = None, size: float | None = None, look_at: Vec | str | None = None) -> dict:
    """Add a light. Energy in watts (sun: strength). look_at aims it at a point or an object name."""
    return call("add_light", kind=kind, name=name, location=location, rotation=rotation, energy=energy,
                color=color, size=size, look_at=look_at)


@mcp.tool(annotations=WRITE)
@guarded
def light_rig(target: str | Vec | None = None, distance: float = 6.0, energy: float = 1000) -> dict:
    """Three-point lighting (key, fill, rim area lights) around an object or point."""
    return call("light_rig", target=target, distance=distance, energy=energy)


@mcp.tool(annotations=WRITE)
@guarded
def add_camera(name: str | None = None, location: Vec | None = None, rotation: Vec | None = None,
               look_at: Vec | str | None = None, lens: float = 50, active: bool = True) -> dict:
    """Add a camera (lens in mm) and make it the scene camera by default."""
    return call("add_camera", name=name, location=location, rotation=rotation, look_at=look_at, lens=lens,
                active=active)


@mcp.tool(annotations=WRITE)
@guarded
def frame_camera(camera: str | None = None, objects: list[str] | None = None, direction: Vec | None = None,
                 margin: float = 1.1) -> dict:
    """Aim a camera at objects (all visible meshes by default) and back off until they fit."""
    return call("frame_camera", camera=camera, objects=objects, direction=direction, margin=margin)


@mcp.tool(annotations=WRITE)
@guarded
def world(color: str | None = None, strength: float | None = None, hdri: str | None = None) -> dict:
    """Background color and strength, or a local HDRI file for image-based lighting."""
    return call("world", color=color, strength=strength, hdri=hdri)


# ------------------------------------------------------------------ render and review

@mcp.tool(annotations=WRITE)
@guarded
def render_settings(engine: Literal["eevee", "cycles", "workbench"] | None = None, resolution: list[int] | None = None,
                    percentage: int | None = None, samples: int | None = None, transparent: bool | None = None,
                    device: Literal["cpu", "gpu"] | None = None, frame_range: list[int] | None = None,
                    fps: int | None = None) -> dict:
    """Render engine, resolution, samples, transparency, device and animation range."""
    return call("render_settings", engine=engine, resolution=resolution, percentage=percentage, samples=samples,
                transparent=transparent, device=device, frame_range=frame_range, fps=fps)


@mcp.tool(annotations=WRITE)
@guarded
def render_still(path: str | None = None, camera: str | None = None, frame: int | None = None):
    """Render the scene camera to a PNG and return it so you can check the result."""
    result = call("render_still", path=path, camera=camera, frame=frame)
    return [json.dumps(result), Image(path=str(images.preview(result["path"])))]


@mcp.tool(annotations=WRITE)
@guarded
def look(views: list[Literal["front", "back", "left", "right", "top", "iso", "iso_back"]] | None = None,
         objects: list[str] | None = None, engine: Literal["workbench", "eevee", "cycles"] = "workbench",
         size: int = 384):
    """Look at the scene from several angles (temporary camera, scene left unchanged) and get one contact
    sheet image. Use it after every meaningful change; workbench is fast, eevee/cycles show materials."""
    result = call("look", views=views, objects=objects, engine=engine, size=size)
    sheet = images.contact_sheet(result["views"], Path(result["views"][0]["path"]).with_name("sheet.png"), cell=size)
    return [json.dumps({"views": [v["view"] for v in result["views"]], "sheet": str(sheet)}), Image(path=str(sheet))]


# ------------------------------------------------------------------ animation

@mcp.tool(annotations=WRITE)
@guarded
def keyframe(name: str, frame: int, location: Vec | None = None, rotation: Vec | None = None,
             scale: Vec | float | None = None) -> dict:
    """Set and key an object's transform at a frame."""
    return call("keyframe", name=name, frame=frame, location=location, rotation=rotation, scale=scale)


@mcp.tool(annotations=WRITE)
@guarded
def turntable(target: str | None = None, frames: int = 120, height: float = 0.35, lens: float = 50) -> dict:
    """A camera that orbits an object (or the whole scene) once over `frames`."""
    return call("turntable", target=target, frames=frames, height=height, lens=lens)


@mcp.tool(annotations=WRITE)
@guarded
def render_animation(path: str, format: Literal["mp4", "png"] = "mp4") -> dict:
    """Render the frame range to an MP4 file, or a folder of PNG frames."""
    return call("render_animation", path=path, format=format)


# ------------------------------------------------------------------ files and assets

@mcp.tool(annotations=WRITE)
@guarded
def import_file(path: str, location: Vec | None = None, scale: Vec | float | None = None) -> dict:
    """Import glTF/GLB, FBX, OBJ, STL, PLY or USD."""
    return call("import_file", path=path, location=location, scale=scale)


@mcp.tool(annotations=WRITE)
@guarded
def export_file(path: str, objects: list[str] | None = None) -> dict:
    """Export the scene, or only `objects`, by extension: .glb .gltf .fbx .obj .stl .ply .usd(.c/.a/.z)."""
    return call("export_file", path=path, objects=objects)


@mcp.tool(annotations=WRITE)
@guarded
def save(path: str | None = None, overwrite: bool = False, as_copy: bool = True) -> dict:
    """Save a copy to `path` (default), or save the open file in place with overwrite=true."""
    return call("save", path=path, overwrite=overwrite, as_copy=as_copy)


@mcp.tool(annotations=WRITE)
@guarded
def open_file(path: str, discard_changes: bool = False) -> dict:
    """Open a .blend file. Refuses when the open scene has unsaved changes unless discard_changes=true."""
    return call("open_file", path=path, discard_changes=discard_changes)


@mcp.tool(annotations=READ)
@guarded
def search_assets(query: str = "", kind: Literal["models", "hdris", "textures"] = "models", limit: int = 12) -> dict:
    """Search Poly Haven (CC0) models, HDRIs and textures."""
    return assets.search(query, kind, limit)


@mcp.tool(annotations=WRITE)
@guarded
def import_asset(asset_id: str, kind: Literal["models", "hdris", "textures"] = "models", resolution: str = "1k",
                 location: Vec | None = None, material_name: str | None = None) -> dict:
    """Download a Poly Haven asset and use it: models are imported, HDRIs become the world, textures
    become a material (`material_name`, default the asset id). The credit is stored on imported objects."""
    got = assets.download(asset_id, kind, resolution)
    if kind == "models":
        return {**got, **call("import_file", path=got["path"], location=location, credit=got["credit"])}
    if kind == "hdris":
        return {**got, **call("world", hdri=got["path"])}
    return {**got, **call("material", name=material_name or asset_id, texture=got["path"])}


# ------------------------------------------------------------------ intent

def _run_spec(steps):
    created = {"materials": [], "objects": [], "lights": [], "camera": None}
    for kind, item in steps:
        if kind == "material":
            created["materials"].append(call("material", **item)["material"])
        elif kind == "object":
            item = dict(item)
            mods = item.pop("modifiers", [])
            parent_name = item.pop("parent", None)
            if item.get("kind") == "mesh":
                item.pop("kind")
                obj = call("create_mesh", **item)
            else:
                obj = call("create_object", **item)
            for mod in mods:
                call("add_modifier", name=obj["name"], type=mod.get("type"), settings=mod.get("settings") or {},
                     apply=mod.get("apply", False))
            if parent_name:
                call("parent", child=obj["name"], parent=parent_name)
            created["objects"].append(obj["name"])
        elif kind == "light":
            if item.get("kind") == "rig":
                created["lights"] += call("light_rig", **{k: v for k, v in item.items() if k != "kind"})["lights"]
            else:
                created["lights"].append(call("add_light", **item)["name"])
        elif kind == "camera":
            item = dict(item)
            frame = item.pop("frame", True)
            cam = call("add_camera", **{k: v for k, v in item.items() if k != "objects"})
            if frame and item.get("location") is None:
                call("frame_camera", camera=cam["name"], objects=item.get("objects"), direction=item.get("direction"))
            created["camera"] = cam["name"]
        elif kind == "world":
            call("world", **item)
        elif kind == "render":
            call("render_settings", **item)
    return created


@mcp.tool(annotations=WRITE)
@guarded
def build_scene(spec: dict[str, Any], review: bool = True):
    """Build a whole scene from one JSON spec (materials, objects with modifiers and parents, lights or
    {"kind": "rig"}, camera {"look_at", "frame"}, world, render). The spec is validated first, so nothing
    is created when it is wrong. With review=true a contact sheet comes back."""
    steps = specs.validate(spec)
    created = _run_spec(steps)
    if not review:
        return created
    result = call("look", objects=created["objects"] or None, engine="workbench", size=384)
    sheet = images.contact_sheet(result["views"], Path(result["views"][0]["path"]).with_name("sheet.png"))
    return [json.dumps(created), Image(path=str(sheet))]


@mcp.tool(annotations=DESTRUCTIVE)
@guarded
def run_python(code: str) -> dict:
    """Run Python inside Blender (bpy). Disabled unless the user set allow_python in the bridge config or
    BLENDER_FORGE_ALLOW_PYTHON=1 for Blender. Assign `result` to return a value; print() is captured."""
    return call("run_python", code=code)


# ------------------------------------------------------------------ skills and roles for any MCP client

WORKSPACE = Path(os.environ.get("BLENDER_FORGE_WORKSPACE") or Path(__file__).resolve().parents[4])


def _reader(doc):
    def read() -> str:
        return doc.read_text(encoding="utf-8")
    return read


def _register_playbooks():
    """Every .agents/skills/<name>/SKILL.md becomes skill://<name>; every .agents/agents/<role>.md a prompt."""
    skills = WORKSPACE / ".agents" / "skills"
    for folder in sorted(skills.iterdir()) if skills.is_dir() else []:
        doc = folder / "SKILL.md"
        if doc.is_file():
            mcp.resource(f"skill://{folder.name}", name=folder.name, mime_type="text/markdown")(_reader(doc))
    roles = WORKSPACE / ".agents" / "agents"
    for doc in sorted(roles.glob("*.md")) if roles.is_dir() else []:
        mcp.prompt(name=doc.stem, description=f"Work as the {doc.stem} role")(_reader(doc))


_register_playbooks()


def main():
    transport = os.environ.get("BLENDER_FORGE_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
