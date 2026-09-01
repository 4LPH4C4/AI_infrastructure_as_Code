from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError

from macmini_ai_hub.config import (
    ConfigBundle,
    SettingsConfig,
    load_config_bundle,
    load_yaml_model,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def valid_bundle() -> ConfigBundle:
    return load_config_bundle(REPOSITORY_ROOT / "config")


def test_example_configuration_loads_and_cross_validates() -> None:
    bundle = valid_bundle()

    assert bundle.settings.settings.default_runtime.value == "disabled"
    assert bundle.teams.teams["example-product"].project == "example-project"
    assert bundle.projects.projects["example-project"].team == "example-product"
    assert bundle.agents.agents["example-developer"].enabled is False


def test_unknown_config_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SettingsConfig.model_validate(
            {
                "schema_version": 1,
                "settings": {
                    "environment": "local",
                    "api_key": "must-not-be-accepted",
                },
            }
        )


def test_wrong_scalar_type_is_rejected() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["settings"]["settings"]["max_concurrent_tasks"] = "2"

    with pytest.raises(ValidationError, match="valid integer"):
        ConfigBundle.model_validate(data)


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        "schema_version: 1\nsettings:\n  environment: local\n  environment: test\n",
        encoding="utf-8",
    )

    with pytest.raises(ConstructorError, match="duplicate key"):
        load_yaml_model(path, SettingsConfig)


def test_unknown_team_reference_is_rejected() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["agents"]["agents"]["example-developer"]["team"] = "missing-team"

    with pytest.raises(ValidationError, match="unknown team 'missing-team'"):
        ConfigBundle.model_validate(data)


def test_team_agent_membership_must_be_reciprocal() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["teams"]["teams"]["example-product"]["agents"] = ["shared-reviewer"]

    with pytest.raises(ValidationError, match=r"not listed by team|belongs to"):
        ConfigBundle.model_validate(data)


def test_product_and_team_relationship_must_be_reciprocal() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["projects"]["projects"]["example-project"]["team"] = "shared-services"

    with pytest.raises(ValidationError, match=r"not reciprocal|product team"):
        ConfigBundle.model_validate(data)


def test_project_workspace_must_stay_under_workspace_projects() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["projects"]["projects"]["example-project"]["workspace"] = "other/example"

    with pytest.raises(ValidationError, match="workspace must be under"):
        ConfigBundle.model_validate(data)


def test_team_rooms_and_project_workspaces_must_be_unique() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["teams"]["teams"]["another-product"] = {
        "type": "product",
        "display_name": "Another Product",
        "room": "example-product",
        "project": "another-project",
        "agents": ["another-developer"],
    }
    data["agents"]["agents"]["another-developer"] = {
        "role": "developer",
        "team": "another-product",
        "runtime": "codex",
        "enabled": False,
        "permission_profile": "developer",
    }
    data["projects"]["projects"]["another-project"] = {
        "display_name": "Another Project",
        "repository": "https://github.com/example/another-project.git",
        "workspace": "workspace/projects/example-project",
        "team": "another-product",
    }

    with pytest.raises(ValidationError, match=r"share workspace|share room"):
        ConfigBundle.model_validate(data)


def test_repository_url_rejects_embedded_credentials() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["projects"]["projects"]["example-project"]["repository"] = (
        "https://user:password@example.com/repository.git"
    )

    with pytest.raises(ValidationError, match="credentials"):
        ConfigBundle.model_validate(data)


def test_duplicate_permissions_are_rejected() -> None:
    data = deepcopy(valid_bundle().model_dump(mode="json"))
    data["permissions"]["permissions"]["reviewer"] = ["read", "read"]

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        ConfigBundle.model_validate(data)


def test_force_push_cannot_be_enabled_by_configuration() -> None:
    data = valid_bundle().model_dump(mode="json")
    data["settings"]["settings"]["git"]["allow_force_push"] = True

    with pytest.raises(ValidationError, match="False"):
        ConfigBundle.model_validate(data)


def test_example_yaml_contains_no_secret_shaped_keys() -> None:
    forbidden = {"api_key", "password", "private_key", "secret", "token"}

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key).lower() for key in value} | {
                nested_key for child in value.values() for nested_key in keys(child)
            }
        if isinstance(value, list):
            return {nested_key for child in value for nested_key in keys(child)}
        return set()

    for path in (REPOSITORY_ROOT / "config").glob("*.example.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert forbidden.isdisjoint(keys(document)), path
