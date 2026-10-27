"""build_scene specs are checked before Blender is touched."""
import pytest

from blender_forge import spec

GOOD = {
    "materials": [{"name": "Wood", "base_color": "#8a5a3b"}],
    "objects": [{"kind": "cube", "name": "Top", "scale": [1, 0.5, 0.05], "material": "Wood",
                 "modifiers": [{"type": "bevel", "settings": {"width": 0.02}}]},
                {"kind": "cylinder", "name": "Leg", "parent": "Top"}],
    "lights": [{"kind": "rig"}],
    "camera": {"look_at": "Top"},
    "render": {"engine": "eevee"},
}


def test_good_spec_orders_steps():
    kinds = [k for k, _ in spec.validate(GOOD)]
    assert kinds == ["material", "object", "object", "light", "camera", "render"]


@pytest.mark.parametrize("bad,needle", [
    ({}, "empty"),
    ([], "JSON object"),
    ({"objects": [{"kind": "teapot"}]}, "kind"),
    ({"objects": [{"kind": "cube", "material": "Missing"}]}, "not defined"),
    ({"objects": [{"kind": "cube", "parent": "Later"}, {"kind": "cube", "name": "Later"}]}, "earlier"),
    ({"objects": [{"kind": "cube", "location": [1, 2]}]}, "[x, y, z]"),
    ({"objects": [{"kind": "mesh"}]}, "vertices"),
    ({"lights": [{"kind": "laser"}]}, "kind"),
    ({"surprise": 1}, "unknown"),
    ({"objects": [{"kind": "cube"}] * 501}, "at most"),
])
def test_bad_specs_are_refused(bad, needle):
    with pytest.raises(spec.SpecError, match=None) as info:
        spec.validate(bad)
    assert needle in str(info.value)
