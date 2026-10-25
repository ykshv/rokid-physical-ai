"""The Python producer and C++ consumer must accept the same scene examples."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rokid_physical_ai.contracts import SceneObservation

FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[1] / "robot_gateway/test/fixtures/scene_validation.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_scene_contract_parity(case):
    scene = copy.deepcopy(FIXTURE["scene"])
    # This fixture uses only add, replace and remove, with literal object keys.
    for patch in case["patch"]:
        target = scene
        keys = patch["path"].lstrip("/").split("/")
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        key = int(keys[-1]) if isinstance(target, list) else keys[-1]
        if patch["op"] == "remove":
            del target[key]
        else:
            assert patch["op"] in ("add", "replace")
            target[key] = patch["value"]
    if case["accepted"]:
        SceneObservation.model_validate(scene)
    else:
        with pytest.raises(ValidationError):
            SceneObservation.model_validate(scene)
