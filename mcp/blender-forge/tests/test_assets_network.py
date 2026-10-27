"""Poly Haven search, download and import. Opt in: pytest -m "network and blender"."""
import pytest

from blender_forge import assets, server

from test_blender_live import BLENDER, bridge  # noqa: F401 - reuse the headless Blender fixture

pytestmark = [pytest.mark.network]


def test_search_finds_cc0_models():
    found = assets.search("chair", "models", limit=5)
    assert found["license"] == "CC0" and found["results"], found


@pytest.mark.blender
@pytest.mark.skipif(BLENDER is None, reason="Blender not installed")
def test_import_a_model_and_an_hdri(bridge, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("BLENDER_FORGE_CACHE", str(tmp_path / "cache"))
    server.new_scene(confirm=True)
    model = server.search_assets("chair", "models", limit=1)["results"][0]["id"]
    got = server.import_asset(model, "models", "1k", location=[0, 0, 0])
    assert got["imported"], got
    credit = server.object_info(got["imported"][0])["custom"].get("forge_credit", "")
    assert "Poly Haven" in credit
    hdri = server.search_assets("studio", "hdris", limit=1)["results"][0]["id"]
    world = server.import_asset(hdri, "hdris", "1k")
    assert world["hdri"] is True
