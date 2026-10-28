# Docker (optional)

blender-forge runs natively with `uv`, and that stays the recommended setup. Docker is for people who would
rather not install Python. **Blender always runs on the host**: the container is only the MCP server, and it
talks to Blender through the same signed bridge as the native server.

```
 MCP client ──stdio or HTTP──▶ container: blender-forge ──signed TCP──▶ host: Blender + bridge (loopback)
                                   │ /work  ◀── bind mount ──▶  host folder (e.g. C:/Users/me/3d)
```

## Before you start

1. Install the extension once natively: `cd mcp/blender-forge && uv run blender-forge-install`. It writes the
   token and port to `~/.config/blender-forge/bridge.json`; the container mounts that file read-only.
2. Open Blender (the bridge starts with it), or run it headless:
   `blender -b --python mcp/blender-forge/src/blender_forge/addon/serve.py`.
   `start_headless` does not work inside the container: there is no Blender in the image.

## How the container reaches Blender

| Variable | Meaning |
|---|---|
| `BLENDER_FORGE_BRIDGE_HOST` | Where the bridge is. Docker Desktop (Windows/macOS): `host.docker.internal`. Linux: run with `--network host` and keep `127.0.0.1` |
| `BLENDER_FORGE_PATH_MAP` | `CONTAINER=HOST` pairs separated by `;`, e.g. `/work=C:/Users/me/3d`. Paths sent to Blender become host paths; paths coming back become `/work/...` |
| `BLENDER_FORGE_CONFIG` | Bridge config inside the container (default `/config/bridge.json`) |
| `BLENDER_FORGE_CACHE` | Poly Haven downloads (default `/work/.blender-forge/cache`, so Blender can read them) |

The bridge keeps binding to the host loopback only. On Docker Desktop, connections to `host.docker.internal`
arrive on the host loopback, so nothing is opened to the network. Renders, contact sheets and exports without an
explicit path go to `/work/.blender-forge/`; give the agent `/work/...` paths for everything else.

## Build

```bash
docker build -t blender-forge:local .
```

## stdio: launched by your MCP client

```json
{
  "mcpServers": {
    "blender-forge": {
      "command": "docker",
      "args": ["run", "--rm", "-i",
               "--add-host", "host.docker.internal:host-gateway",
               "-e", "BLENDER_FORGE_BRIDGE_HOST=host.docker.internal",
               "-e", "BLENDER_FORGE_PATH_MAP=/work=C:/Users/me/3d",
               "-v", "C:/Users/me/3d:/work",
               "-v", "C:/Users/me/.config/blender-forge/bridge.json:/config/bridge.json:ro",
               "-v", "C:/path/to/blender-forge:/workspace:ro",
               "blender-forge:local"]
    }
  }
}
```

Keep `-i`, never `-t`. The `/workspace` mount is optional: it serves the skills (`skill://…`) and the
`3d-artist` role. On Linux replace the `--add-host` pair with `--network host` and set
`BLENDER_FORGE_BRIDGE_HOST=127.0.0.1`.

## HTTP with a token (compose)

```bash
export BLENDER_FORGE_MCP_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
FORGE_WORK=C:/Users/me/3d docker compose up -d --build --wait                         # Windows / macOS
FORGE_WORK=$HOME/3d docker compose -f compose.yaml -f compose.linux.yaml up -d --build --wait   # Linux
```

The MCP endpoint is `http://127.0.0.1:8080/mcp` (`BLENDER_FORGE_PORT` changes the port). Every request needs
`Authorization: Bearer <token>`; requests with a browser `Origin` are refused; `/healthz` answers without a
token. The container runs as a non-root user with a read-only root filesystem, no capabilities and
`no-new-privileges`.

## Verified

`python scripts/test_docker.py` builds the image and runs it against a real headless Blender on the host:
stdio handshake, skills from `/workspace`, `forge_status`, a model, a render and a `.glb` export that land in
the mounted host folder, then compose over HTTP with a token. It passes on Windows 11 with Docker Desktop
29.8 and Blender 5.2.3, and CI runs it on Linux.

---

## En español (resumen)

Docker es opcional: el contenedor solo corre el servidor MCP y **Blender sigue en tu equipo** con su bridge en
loopback. Instala la extensión una vez (`uv run blender-forge-install`), abre Blender o córrelo headless, y monta
tu carpeta de trabajo en `/work` con `BLENDER_FORGE_PATH_MAP=/work=<tu carpeta>`. En Docker Desktop usa
`BLENDER_FORGE_BRIDGE_HOST=host.docker.internal`; en Linux, `--network host`. Para HTTP usa `compose.yaml` con
`BLENDER_FORGE_MCP_TOKEN` (32+ caracteres). `scripts/test_docker.py` lo comprueba de punta a punta con un Blender
real.
