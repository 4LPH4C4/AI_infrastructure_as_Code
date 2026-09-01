"""Safe YAML loading for AI Hub configuration."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from yaml.constructor import ConstructorError

from macmini_ai_hub.config.models import (
    AgentRegistry,
    ConfigBundle,
    PermissionRegistry,
    ProjectRegistry,
    SettingsConfig,
    TeamRegistry,
)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that fails closed on duplicate YAML keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml_model[ModelT: BaseModel](path: str | Path, model_type: type[ModelT]) -> ModelT:
    """Load exactly one safe YAML document and validate it as ``model_type``."""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        data = yaml.load(stream, Loader=_UniqueKeySafeLoader)
    if data is None:
        raise ValueError(f"configuration file is empty: {config_path}")
    if not isinstance(data, dict):
        raise ValueError(f"configuration root must be a mapping: {config_path}")
    return model_type.model_validate(data)


def load_config_bundle(
    config_directory: str | Path,
    *,
    use_examples: bool = True,
) -> ConfigBundle:
    """Load the five registries and validate their cross-references.

    Phase 0 callers keep using the public ``*.example.yaml`` templates. A Phase 1
    service passes ``use_examples=False`` and therefore fails closed unless all
    machine-local registry files exist.
    """

    directory = Path(config_directory)
    suffix = ".example.yaml" if use_examples else ".yaml"
    return ConfigBundle(
        settings=load_yaml_model(directory / f"settings{suffix}", SettingsConfig),
        agents=load_yaml_model(directory / f"agents{suffix}", AgentRegistry),
        teams=load_yaml_model(directory / f"teams{suffix}", TeamRegistry),
        projects=load_yaml_model(directory / f"projects{suffix}", ProjectRegistry),
        permissions=load_yaml_model(directory / f"permissions{suffix}", PermissionRegistry),
    )
