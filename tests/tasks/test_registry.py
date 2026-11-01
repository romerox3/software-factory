"""The digest resolver must work from headers alone; tests never touch the network."""

from __future__ import annotations

import json

import pytest

from factory.tasks.registry import (
    MANIFEST_ACCEPT,
    RegistryError,
    Response,
    resolve_digest,
    split_image,
)

DIGEST = "sha256:" + "ab" * 32


class FakeTransport:
    """Record calls and answer them in order."""

    def __init__(self, responses: list[Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, method: str, url: str, headers: object) -> Response:
        self.calls.append((method, url, dict(headers)))
        return self.responses.pop(0)


def test_pinned_image_needs_no_request() -> None:
    transport = FakeTransport([])

    assert resolve_digest(f"ghcr.io/acme/widgets@{DIGEST}", transport=transport) == DIGEST
    assert transport.calls == []


def test_registry_host_manifest_digest() -> None:
    transport = FakeTransport(
        [Response(200, {"Docker-Content-Digest": DIGEST}, b"")],
    )

    digest = resolve_digest("ghcr.io/acme/widgets:latest", transport=transport)

    assert digest == DIGEST
    method, url, headers = transport.calls[0]
    assert method == "HEAD"
    assert url == "https://ghcr.io/v2/acme/widgets/manifests/latest"
    assert headers["Accept"] == MANIFEST_ACCEPT


def test_docker_hub_gets_a_token_for_a_public_image() -> None:
    challenge = (
        'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",'
        'scope="repository:library/ubuntu:pull"'
    )
    transport = FakeTransport(
        [
            Response(401, {"WWW-Authenticate": challenge}, b""),
            Response(200, {}, json.dumps({"token": "secret"}).encode()),
            Response(200, {"Docker-Content-Digest": DIGEST}, b""),
        ]
    )

    assert resolve_digest("ubuntu:22.04", transport=transport) == DIGEST
    assert transport.calls[0][1] == "https://registry-1.docker.io/v2/library/ubuntu/manifests/22.04"
    assert transport.calls[1][0] == "GET"
    assert "scope=repository%3Alibrary%2Fubuntu%3Apull" in transport.calls[1][1]
    assert transport.calls[2][2]["Authorization"] == "Bearer secret"


def test_split_image_handles_registries_ports_and_tags() -> None:
    assert split_image("ghcr.io/acme/widgets") == ("ghcr.io", "acme/widgets", "latest")
    assert split_image("localhost:5000/team/app:1.2") == (
        "localhost:5000",
        "team/app",
        "1.2",
    )
    assert split_image("python") == ("registry-1.docker.io", "library/python", "latest")


def test_a_manifest_without_a_digest_is_an_error() -> None:
    transport = FakeTransport([Response(200, {}, b"")])

    with pytest.raises(RegistryError, match="no usable digest"):
        resolve_digest("ghcr.io/acme/widgets:latest", transport=transport)


def test_a_failed_manifest_request_is_an_error() -> None:
    transport = FakeTransport([Response(404, {}, b"")])

    with pytest.raises(RegistryError, match="404"):
        resolve_digest("ghcr.io/acme/widgets:latest", transport=transport)


def test_a_challenge_without_a_realm_is_an_error() -> None:
    transport = FakeTransport([Response(401, {"WWW-Authenticate": "Bearer"}, b"")])

    with pytest.raises(RegistryError, match="realm"):
        resolve_digest("ghcr.io/acme/widgets:latest", transport=transport)
