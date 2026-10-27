---
name: blender-forge
description: Drive Blender through the blender-forge MCP server - connect, build scenes, review renders, save and export safely. Load before any task that touches Blender (modeling, materials, lighting, render, animation, import/export).
---

# blender-forge

## Connect
1. `forge_status`. If it reports `BRIDGE_OFFLINE`: call `start_headless` (no window, good for renders and
   exports), or ask the user to open Blender; the extension starts the bridge with Blender.
2. Never assume the scene is empty: read `scene_info` first. Use `new_scene(confirm=true)` only when the
   user asked for a fresh scene.

## Conventions
- Z is up, units are metres, rotations are **degrees**, colours are `#RRGGBB` (sRGB).
- Primitives are centred on their origin: a cube of size 2 spans -1..1. A 0.75 m high desk top sits at
  `z = 0.75`; legs go at half their height.
- Names are how you refer to things later; give every object and material a clear name.

## Workflow
1. Plan the pieces and real-world sizes (see `blender-modeling` for references).
2. Build in one go with `build_scene` (validated first: nothing is created if the spec is wrong), or step by
   step with `create_object`, `create_mesh`, `add_modifier`, `material`, `add_light`, `add_camera`.
3. **Look before you say it is done**: `look` returns a contact sheet (front, right, top, iso). Check
   proportions, floating or intersecting parts, missing pieces. Fix with `transform` and look again.
4. Light and frame: `light_rig` for three-point light, `frame_camera` to fit the subject.
5. Final image: `render_settings` (eevee for speed, cycles for quality), then `render_still`; check the
   returned image.
6. Deliver: `save(path=...)` writes a copy; `export_file` for .glb (web), .fbx (Unity/Unreal), .usd, .obj,
   .stl (3D printing).

## Safety
- `delete` and `new_scene` need `confirm=true`; ask the user before removing their work.
- `save` never overwrites the open file unless `overwrite=true`.
- `run_python` is disabled unless the user enabled it. Prefer the dedicated tools; if you need Python, say
  what the script will do first.
- Assets from `search_assets` / `import_asset` are Poly Haven CC0; the credit is stored on the objects.

## Errors
Every error has `code`, `message` and sometimes `hint`. `NOT_FOUND`: check names with `scene_info`.
`BAD_ARGUMENTS`: the message names the field. `CONFIRM_REQUIRED`: ask the user, then retry with confirm.
