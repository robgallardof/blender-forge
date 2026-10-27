"""Headless entry point: `blender -b [file.blend] --python serve.py`.

Runs the bridge with Blender's main thread as the job loop, so renders and exports
work without a window. Stops when the process is killed or after --idle seconds.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blender_forge.addon import protocol  # noqa: E402
from blender_forge.addon.bridge import Bridge  # noqa: E402

bridge = Bridge(protocol.load_config(create=True)).start()
print(f"blender-forge: headless bridge listening on 127.0.0.1:{bridge.config['port']}", flush=True)
try:
    bridge.serve_blocking()
except KeyboardInterrupt:
    pass
finally:
    bridge.stop()
