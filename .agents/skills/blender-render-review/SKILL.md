---
name: blender-render-review
description: Light, shade, render and review Blender scenes with blender-forge - material recipes, lighting setups, engines, contact-sheet review and export targets. Use when asked to render, make it look good, or deliver a model.
---

# Render and review

## Materials (Principled BSDF through `material`)

| Look | Settings |
|---|---|
| Painted / plastic | base_color, roughness 0.4-0.6 |
| Wood | warm brown base_color, roughness 0.5-0.7 (or `texture` from a Poly Haven wood) |
| Metal | metallic 1, roughness 0.2-0.4 |
| Glass | transmission 1, roughness 0, ior 1.45 |
| Glow / screen | emission_color, emission_strength 5-20 |
| Rubber | dark base_color, roughness 0.9 |

## Light
- Product or object: `light_rig` on the subject, dark world (#1a1d24, strength 0.3-0.6).
- Outdoor: a `sun` (energy 3-5) plus an HDRI (`import_asset` with kind `hdris`).
- Interior: area lights near the windows, 200-1000 W.
- Too dark: raise the light energy. Burnt highlights: lower the key light.

## Camera
- `frame_camera` fits the subject. 35 mm for rooms, 50 mm for objects, 85 mm for close product shots.
- A floor plane under the subject grounds it; `look` ignores flat floors when framing.

## Engines

| Engine | Use |
|---|---|
| workbench | Fast checks of shape and layout (default for `look`) |
| eevee | Quick final renders with materials and light |
| cycles | Highest quality; samples 64-256, device gpu when available |

## Review checklist (after every `look` and `render_still`)
- The subject fills the frame and nothing is cut off unless intended.
- The light direction reads clearly; shadows ground the object.
- Materials look like what was asked (metal reflects, glass is clear, wood is warm).
- No black or blown-out render. A black render means no light, or a camera facing away.

## Deliver

| Target | Export |
|---|---|
| Web / three.js | .glb |
| Unity / Unreal | .fbx |
| Pipelines / Apple | .usd / .usdz |
| 3D printing | .stl (apply modifiers first) |
| Turntable video | `turntable` then `render_animation` mp4 |
