"""Configuration is complete or the service must not start."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.gateway.config import ConfigError, load_config

from .test_support import MASTER_KEY, base_config, write_config


def test_loads_a_valid_configuration(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path), environ={"LITELLM_MASTER_KEY": MASTER_KEY})

    assert config.litellm_url == "http://litellm.test:4000"
    assert config.classes["public"].team_id == "team-public"
    assert config.classes["verifier"].max_ttl_sec == 7200
    assert len(config.tokens) == 2
    assert config.master_key == MASTER_KEY


def test_missing_master_key_fails_to_start(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="LITELLM_MASTER_KEY"):
        load_config(write_config(tmp_path), environ={})


def test_missing_config_file_fails_to_start() -> None:
    with pytest.raises(ConfigError, match="FACTORY_KEYS_CONFIG"):
        load_config(environ={"LITELLM_MASTER_KEY": MASTER_KEY})


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda config: config.pop("litellm_url"), "litellm_url"),
        (lambda config: config.pop("tokens"), "tokens"),
        (lambda config: config["classes"]["public"].pop("team_id"), "team_id"),
        (lambda config: config["classes"]["public"].pop("max_budget_usd"), "max_budget_usd"),
        (lambda config: config["classes"]["public"].pop("max_ttl_sec"), "max_ttl_sec"),
        (lambda config: config["classes"].pop("public"), "unknown data_class"),
        (lambda config: config["tokens"][0].update(classes=["unknown"]), "unknown data_class"),
        (lambda config: config["tokens"][0].update(sha256="not-hex"), "sha256"),
        (lambda config: config.update(master_key=MASTER_KEY), "unknown fields"),
    ],
)
def test_incomplete_configuration_fails_to_start(tmp_path: Path, mutate, expected) -> None:
    raw = base_config()
    mutate(raw)

    with pytest.raises(ConfigError, match=expected):
        load_config(write_config(tmp_path, raw), environ={"LITELLM_MASTER_KEY": MASTER_KEY})
