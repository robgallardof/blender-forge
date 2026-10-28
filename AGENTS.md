# blender-forge — instructions for any agent

An MCP server that lets agents model, light, render, animate and export in **Blender** (4.2+, tested on
5.2.3 LTS), with visual review. Works with any agent that reads `AGENTS.md`, Agent Skills (`SKILL.md`) and
MCP: Claude Code, Codex, OpenCode, DeepSeek Harness, Cursor, Gemini CLI, VS Code. Reply in the user's language.

## What is here

| Path | What it is |
|---|---|
| `mcp/blender-forge/src/blender_forge/server.py` | MCP tools (thin: validate, call the bridge, return images) |
| `mcp/blender-forge/src/blender_forge/addon/` | The Blender extension: signed loopback bridge (`bridge.py`, `protocol.py`) and the operations (`ops.py`) |
| `mcp/blender-forge/src/blender_forge/spec.py` | `build_scene` spec validation, pure Python |
| `mcp/blender-forge/src/blender_forge/assets.py` | Poly Haven (CC0) search and download |
| `mcp/blender-forge/src/blender_forge/install.py` | Builds and installs the extension with Blender's own `extension` CLI |
| `.agents/skills/`, `.agents/agents/` | Portable skills and roles; the server also exposes them as `skill://` resources and prompts |
| `config/mcp.servers.json` | Launch definition read by `scripts/install-mcp.py` |

## Using it

1. Load the `blender-forge` skill, then `forge_status`. If offline: `start_headless`, or the user opens Blender.
2. Read `scene_info` before changing anything. Look (`look`) after every meaningful change.
3. Never delete, start a new scene or overwrite the open file without the user's explicit OK.
4. `run_python` stays disabled unless the user enables it (`blender-forge-install --allow-python`).

## Developing

- Operations live only in `addon/ops.py` and run on Blender's main thread. Register new ones with
  `@operation("name")`; the bridge allowlist is that registry. Add the matching tool in `server.py`.
- `addon/` must stay importable inside Blender with the standard library only (no `mcp`, no Pillow).
- Tests: `cd mcp/blender-forge && uv run pytest` runs protocol, spec, stdio MCP, real headless Blender
  (every operation, renders, exports) and the extension install into an isolated Blender user folder.
  Blender is found automatically or through `BLENDER_FORGE_BLENDER`. Poly Haven tests: `-m network`.
- Own implementation only: do not copy code from other Blender MCP servers.
- Docker (optional): `Dockerfile` + `compose.yaml` (+ `compose.linux.yaml`); the container is only the MCP server
  and reaches the host bridge through `BLENDER_FORGE_BRIDGE_HOST`, translating paths with `BLENDER_FORGE_PATH_MAP`.
  Real test against a headless Blender: `python scripts/test_docker.py`. Details: [docs/DOCKER.md](docs/DOCKER.md).
- Docs in English and Spanish (`README.md`, `README.es.md`).

## Commit language

All new Git commit subjects and bodies must be written in English, detailed, with no AI co-author trailers.
