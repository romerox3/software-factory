"""The smoke check fails fast and clearly when its environment is incomplete."""

from __future__ import annotations

import pytest

from factory.gateway import smoke


def test_missing_environment_variables_are_named() -> None:
    with pytest.raises(SystemExit) as excinfo:
        smoke.main(environ={})

    message = str(excinfo.value)
    assert "missing required environment variable(s)" in message
    for name in smoke.REQUIRED_ENV:
        assert name in message


def test_missing_plan_is_reported_even_if_the_rest_is_set() -> None:
    environ = {
        "FACTORY_KEYS_URL": "http://keys.test:8080",
        "FACTORY_KEYS_TOKEN": "token",
        "FACTORY_GATEWAY_URL": "http://gateway.test:4000",
    }

    with pytest.raises(SystemExit, match="FACTORY_SMOKE_PLAN"):
        smoke.main(environ=environ)
