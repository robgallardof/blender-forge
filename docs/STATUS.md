# Status

## 0.1.0 — 2026-10-27

What exists and how it was checked. Unrun items are marked NOT EXECUTED.

- MCP server with 37 tools (session, modeling, materials, lights, camera, world, render, review, animation,
  files, Poly Haven assets, `build_scene`, opt-in `run_python`), skills as `skill://` resources and the
  `3d-artist` role as a prompt.
- Blender extension (manifest schema 1.0.0, Blender 4.2+) with a signed loopback bridge: HMAC-SHA256,
  timestamp window, single-use nonces, operation allowlist, main-thread execution through a timer (UI) or
  the main loop (headless).
- EXECUTED on Windows 11 with Blender 5.2.3 LTS (`uv run pytest`): protocol tampering/replay/stale tests,
  spec validation, a real MCP stdio client (tools, annotations, resources, prompts, offline error), every
  operation through a real headless Blender (models, modifiers, raw meshes, materials, build_scene, look,
  render_still, glb export and re-import, save-copy refusal to overwrite, keyframes, turntable, PNG frame
  render), a forged request rejected by the real bridge, and the extension built, installed, enabled,
  pinged and removed with Blender's `extension` CLI in an isolated user folder.
- EXECUTED: `pytest -m network`: Poly Haven search, model import with credit, HDRI as world.
- EXECUTED: the installed extension inside an interactive Blender 5.2.3 window (GUI timer path):
  forge_status reported background=false and create_object added a mesh to the open scene.
- EXECUTED in CI (run 40604942500): unit tests on Windows, macOS and Linux; the full Blender suite on
  Linux with the checksum-verified 5.2.3 tarball, including Workbench renders on a headless runner.
- EXECUTED: Docker (optional image): `python scripts/test_docker.py` on Windows 11 with Docker Desktop 29.8
  against a real headless Blender 5.2.3: stdio handshake, skills from /workspace, status, a model, a render
  and a .glb export landing in the mounted host folder, compose over HTTP with a token. CI runs it on Linux.
- Registered with `scripts/install-mcp.py --with-skills` in the clients detected on this PC: Claude Code
  (`claude mcp list`: connected), Codex and VS Code.
- NOT EXECUTED: Eevee and Cycles renders on Linux/macOS (tested on Windows only); model inference
  inside agent hosts.
