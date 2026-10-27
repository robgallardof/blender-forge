---
name: blender-modeling
description: Model objects with blender-forge from primitives, modifiers and raw meshes - blockout, real-world proportions, modifier recipes, low-poly and hard-surface style. Use when asked to create or model anything in Blender.
---

# Modeling with blender-forge

## Method
1. **Blockout**: big shapes first, with primitives at real sizes. Look.
2. **Shape**: modifiers before raw geometry. Look.
3. **Detail**: bevels, small parts, smoothing. Look.
4. Only then materials and light.

## Real-world sizes (metres)

| Thing | Size |
|---|---|
| Person | 1.75 tall |
| Door | 0.9 x 2.0 |
| Desk / table top | 0.72-0.76 high, 1.2-1.6 x 0.6-0.8 |
| Chair seat | 0.45 high, 0.45 x 0.45 |
| Sofa | 0.85 high, seat 0.42 |
| Mug | 0.09 high, 0.04 radius |
| Room | 2.5-2.8 ceiling |
| Car | 4.5 x 1.8 x 1.45 |

## Modifier recipes (`add_modifier` settings use Blender property names)
- Soft edges on hard surfaces: `bevel {"width": 0.01-0.03, "segments": 3}`.
- Organic and smooth: `subdivision {"levels": 2, "render_levels": 2}` plus `shade` smooth.
- Repeats (shelves, fence, stairs): `array {"count": 8, "relative_offset_displace": [1.1, 0, 0]}`.
- Symmetry: model half, then `mirror {"use_axis": [true, false, false]}`.
- Holes and cuts: make a cutter object, `boolean {"operation": "DIFFERENCE", "object": "Cutter"}`, then
  `apply_modifiers` and remove the cutter (ask first).
- Thin walls (vases, shells): `solidify {"thickness": 0.01}`.
- Low-poly look: `decimate {"ratio": 0.3}` and flat shading.
- Lathe shapes (bottles, vases): `create_mesh` with a profile (vertices in the X/Z plane, edges between
  them), then `screw {"steps": 32, "angle": 6.283}`.

## Custom shapes
`create_mesh(vertices, faces)` builds anything: compute the coordinates, keep faces consistently ordered
(counter-clockwise seen from outside) and `shade` smooth when curved. `join` pieces that belong to one
mesh; `parent` pieces that should move together but stay separate.

## Checks before finishing
- Nothing floats unless intended: bottoms rest at z = 0 or on their support.
- No parts poke through each other (check the front and right views).
- Proportions match the references above.
