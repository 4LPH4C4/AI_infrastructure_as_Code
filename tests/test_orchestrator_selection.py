from __future__ import annotations

from pathlib import Path

import pytest

from macmini_ai_hub.config import ConfigBundle, load_config_bundle
from macmini_ai_hub.domain.tasks import Task
from macmini_ai_hub.orchestrator import DeveloperSelectionError, select_developer

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def task() -> Task:
    return Task(
        task_id="TASK-3001",
        source="test",
        project="example-project",
        team="example-product",
        request="Implement the approved test change.",
    )


def enabled_bundle() -> ConfigBundle:
    bundle = load_config_bundle(REPOSITORY_ROOT / "config")
    data = bundle.model_dump(mode="json")
    data["agents"]["agents"]["example-developer"]["enabled"] = True
    return ConfigBundle.model_validate(data)


def test_selects_one_enabled_capable_product_developer() -> None:
    selected = select_developer(enabled_bundle(), task())

    assert selected.agent_id == "example-developer"


def test_disabled_developer_is_rejected() -> None:
    bundle = load_config_bundle(REPOSITORY_ROOT / "config")

    with pytest.raises(DeveloperSelectionError, match="no enabled"):
        select_developer(bundle, task())


def test_phase_one_rejects_multiple_eligible_developers() -> None:
    data = enabled_bundle().model_dump(mode="json")
    data["agents"]["agents"]["another-developer"] = {
        **data["agents"]["agents"]["example-developer"],
    }
    data["teams"]["teams"]["example-product"]["agents"].append("another-developer")
    bundle = ConfigBundle.model_validate(data)

    with pytest.raises(DeveloperSelectionError, match="exactly one"):
        select_developer(bundle, task())


@pytest.mark.parametrize("capability", ["network", "deploy", "admin"])
def test_phase_one_rejects_dangerous_developer_capabilities(capability: str) -> None:
    data = enabled_bundle().model_dump(mode="json")
    data["permissions"]["permissions"]["developer"].append(capability)
    bundle = ConfigBundle.model_validate(data)

    with pytest.raises(DeveloperSelectionError, match="no enabled"):
        select_developer(bundle, task())


def test_phase_one_requires_project_workspace_policy() -> None:
    data = enabled_bundle().model_dump(mode="json")
    data["agents"]["agents"]["example-developer"]["working_directory_policy"] = "read-only"
    bundle = ConfigBundle.model_validate(data)

    with pytest.raises(DeveloperSelectionError, match="no enabled"):
        select_developer(bundle, task())
