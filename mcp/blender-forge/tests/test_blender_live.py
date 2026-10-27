"""End to end against a real headless Blender: the bridge, the operations and the MCP tools.

Skipped when no Blender executable is found. CI installs Blender so these always run there.
"""
import json
import socket
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage

from blender_forge import server
from blender_forge.addon import protocol
from blender_forge.client import ADDON_DIR, Client, find_blender

BLENDER = find_blender()
pytestmark = [pytest.mark.blender, pytest.mark.skipif(BLENDER is None, reason="Blender not installed")]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    home = tmp_path_factory.mktemp("forge")
    config = {"port": free_port(), "token": "k" * 64}
    cfg = home / "bridge.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    env = {**__import__("os").environ, "BLENDER_FORGE_CONFIG": str(cfg)}
    proc = subprocess.Popen([str(BLENDER), "-b", "--factory-startup", "--python", str(ADDON_DIR / "serve.py")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(config)
    deadline = time.time() + 90
    while not client.reachable():
        assert proc.poll() is None, "Blender exited before the bridge opened"
        assert time.time() < deadline, "bridge did not open"
        time.sleep(0.5)
    old = server.client
    server.client = client
    yield {"client": client, "config": config, "home": home}
    server.client = old
    proc.terminate()
    proc.wait(20)


def text_of(result):
    return json.loads(result[0])


def test_status_and_empty_start(bridge):
    status = server.forge_status()
    assert status["blender"].startswith(("4.", "5.")), status
    assert "run_python" not in status["operations"]
    server.new_scene(confirm=True)
    assert server.scene_info()["count"] == 0


def test_confirmations_and_refusals(bridge):
    assert server.new_scene()["error"]["code"] == "CONFIRM_REQUIRED"
    assert server.delete(["x"])["error"]["code"] == "CONFIRM_REQUIRED"
    assert server.run_python("result = 1")["error"]["code"] == "UNKNOWN_OPERATION"
    assert server.object_info("nope")["error"]["code"] == "NOT_FOUND"
    assert server.create_object(kind="cube", location=[1, 2])["error"]["code"] == "BAD_ARGUMENTS"


def test_a_forged_request_is_rejected_by_the_real_bridge(bridge):
    bad = Client({"port": bridge["config"]["port"], "token": "z" * 64})
    with pytest.raises(Exception) as info:
        bad.call("status")
    assert getattr(info.value, "code", "") == "BAD_SIGNATURE"


def test_model_material_modifier_and_mesh(bridge):
    server.new_scene(confirm=True)
    mat = server.material(name="Steel", base_color="#9aa4b1", metallic=1.0, roughness=0.3)
    assert set(mat["set"]) >= {"base_color", "metallic", "roughness"}
    cube = server.create_object(kind="cube", name="Box", location=[0, 0, 1], rotation=[0, 0, 45], scale=[1, 2, 0.5],
                                material="Steel")
    assert cube["name"] == "Box" and cube["rotation"][2] == pytest.approx(45, abs=1e-3)
    assert cube["dimensions"] == pytest.approx([2, 4, 1], abs=1e-4)
    assert server.add_modifier("Box", "bevel", {"width": 0.05, "segments": 3})["modifier"]
    baked = server.apply_modifiers("Box")
    assert baked["modifiers"] == [] and baked["mesh"]["vertices"] > 8
    bad = server.add_modifier("Box", "bevel", {"no_such_setting": 1})
    assert bad["error"]["code"] == "BAD_ARGUMENTS"
    monkey = server.create_object(kind="monkey", name="Suzanne")
    assert monkey["name"] == "Suzanne", "an object named like its default must keep the name"
    assert server.create_object(kind="monkey", name="Suzanne")["name"] == "Suzanne.001"
    tri = server.create_mesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                             faces=[[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]], name="Tetra")
    assert tri["mesh"] == {"vertices": 4, "edges": 6, "faces": 4}
    dup = server.duplicate("Tetra", count=3, offset=[2, 0, 0])
    assert len(dup["created"]) == 3
    assert server.delete(dup["created"], confirm=True)["deleted"] == dup["created"]


def test_build_scene_and_look(bridge):
    server.new_scene(confirm=True)
    spec = {
        "materials": [{"name": "Wood", "base_color": "#8a5a3b", "roughness": 0.6},
                      {"name": "Lamp", "emission_color": "#ffd27a", "emission_strength": 8}],
        "objects": [{"kind": "cube", "name": "Desk", "scale": [1.2, 0.6, 0.04], "location": [0, 0, 0.75],
                     "material": "Wood", "modifiers": [{"type": "bevel", "settings": {"width": 0.01}}]},
                    {"kind": "cylinder", "name": "LegA", "radius": 0.03, "depth": 0.75, "location": [1, 0.5, 0.37],
                     "parent": "Desk"},
                    {"kind": "uv_sphere", "name": "Bulb", "radius": 0.08, "location": [0.6, 0, 1.0],
                     "material": "Lamp", "smooth": True}],
        "lights": [{"kind": "rig", "target": "Desk"}],
        "camera": {"look_at": "Desk"},
        "world": {"color": "#1d2230", "strength": 0.5},
    }
    out = server.build_scene(spec)
    created = text_of(out)
    assert created["objects"] == ["Desk", "LegA", "Bulb"] and len(created["lights"]) == 3 and created["camera"]
    assert object_parent("LegA") == "Desk"
    sheet = Path(out[1].path if hasattr(out[1], "path") else out[1].data)
    with PILImage.open(sheet) as im:
        assert im.width >= 384 * 2 and len(set(im.convert("L").get_flattened_data())) > 20, "contact sheet is blank"
    info = server.scene_info()
    assert "ForgeLook" not in [o["name"] for o in info["objects"]], "look left its camera behind"


def object_parent(name):
    return server.object_info(name)["parent"]


def test_render_still_export_import_and_save(bridge, tmp_path):
    server.render_settings(engine="workbench", resolution=[320, 180])
    shot = server.render_still(path=str(tmp_path / "shot.png"))
    meta = text_of(shot)
    with PILImage.open(meta["path"]) as im:
        assert im.size == (320, 180)
    glb = server.export_file(str(tmp_path / "desk.glb"), objects=["Desk"])
    assert glb["bytes"] > 1000
    before = server.scene_info()["count"]
    imported = server.import_file(str(tmp_path / "desk.glb"), location=[5, 0, 0])
    assert imported["imported"] and server.scene_info()["count"] == before + len(imported["imported"])
    saved = server.save(path=str(tmp_path / "scene.blend"))
    assert Path(saved["saved"]).is_file()
    again = server.save(path=str(tmp_path / "scene.blend"))
    assert again["error"]["code"] == "WOULD_OVERWRITE"
    assert server.save()["error"]["code"] in ("WOULD_OVERWRITE", "BAD_ARGUMENTS")


def test_animation_keyframes_and_turntable(bridge, tmp_path):
    key = server.keyframe("Bulb", frame=1, location=[0.6, 0, 1.0])
    assert key["keyed"] == ["location"]
    server.keyframe("Bulb", frame=24, location=[0.6, 0, 1.4])
    spin = server.turntable(target="Desk", frames=12)
    assert spin["frames"] == 12
    server.render_settings(engine="workbench", resolution=[160, 90], frame_range=[1, 3])
    frames = server.render_animation(str(tmp_path / "frames"), format="png")
    assert len(list(Path(frames["path"]).glob("frame_*.png"))) == 3
