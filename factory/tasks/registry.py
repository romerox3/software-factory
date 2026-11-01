"""Resolve the digest of ``repo:tag`` from the registry without pulling the image.

Pulling a few gigabytes just to learn an immutable reference is wasteful when the
registry answers a ``HEAD`` on the manifest. Docker Hub and GitHub's registry
both require a bearer token for private repositories and advertise it through the
``WWW-Authenticate`` header; both then return the digest in
``Docker-Content-Digest``.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

DOCKER_HUB_REGISTRY = "registry-1.docker.io"
MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMEOUT_SEC = 30

_CHALLENGE = re.compile(r'(\w+)="([^"]*)"')


class RegistryError(RuntimeError):
    """The registry did not answer with a manifest digest."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


Transport = Callable[[str, str, Mapping[str, str]], Response]


def resolve_digest(image: str, *, transport: Transport | None = None) -> str:
    """Return ``repo:tag``'s manifest digest, pinned as ``sha256:...``."""
    if "@" in image:
        digest = image.split("@", 1)[1]
        if DIGEST_PATTERN.match(digest):
            return digest
        raise RegistryError(f"image carries an invalid digest: {image!r}")
    registry, repository, tag = split_image(image)
    url = f"https://{registry}/v2/{repository}/manifests/{tag}"
    headers = {"Accept": MANIFEST_ACCEPT}
    send = transport or _https_transport
    response = send("HEAD", url, headers)
    if response.status == 401:
        token = _bearer_token(response.headers, repository, send)
        response = send("HEAD", url, {**headers, "Authorization": f"Bearer {token}"})
    if response.status != 200:
        raise RegistryError(f"registry answered {response.status} for {image!r}")
    digest = _header(response.headers, "Docker-Content-Digest")
    if digest is None or not DIGEST_PATTERN.match(digest):
        raise RegistryError(f"registry returned no usable digest for {image!r}")
    return digest


def split_image(image: str) -> tuple[str, str, str]:
    """Return ``(registry, repository, tag)`` for an untagged or tagged image."""
    name = image.split("@", 1)[0]
    slash = name.rfind("/")
    colon = name.rfind(":")
    if colon > slash:
        name, tag = name[:colon], name[colon + 1 :]
    else:
        tag = "latest"
    parts = name.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry = parts[0]
        repository = "/".join(parts[1:])
    else:
        registry = DOCKER_HUB_REGISTRY
        repository = name
    if registry == DOCKER_HUB_REGISTRY and "/" not in repository:
        repository = f"library/{repository}"
    return registry, repository, tag


def _bearer_token(headers: Mapping[str, str], repository: str, transport: Transport) -> str:
    challenge = _header(headers, "WWW-Authenticate")
    if challenge is None:
        raise RegistryError("registry asked for authentication without a challenge")
    scheme, _, parameters = challenge.partition(" ")
    if scheme.lower() != "bearer":
        raise RegistryError(f"unsupported authentication scheme: {scheme!r}")
    fields = dict(_CHALLENGE.findall(parameters))
    realm = fields.get("realm")
    if not realm:
        raise RegistryError("bearer challenge has no realm")
    query = {key: fields[key] for key in ("service", "scope") if key in fields}
    query.setdefault("scope", f"repository:{repository}:pull")
    url = f"{realm}?{urllib.parse.urlencode(query)}"
    response = transport("GET", url, {"Accept": "application/json"})
    if response.status != 200:
        raise RegistryError(f"token endpoint answered {response.status}")
    try:
        document = json.loads(response.body)
    except ValueError as exc:
        raise RegistryError("token endpoint returned invalid JSON") from exc
    token = document.get("token") or document.get("access_token")
    if not isinstance(token, str) or not token:
        raise RegistryError("token endpoint returned no token")
    return token


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _https_transport(method: str, url: str, headers: Mapping[str, str]) -> Response:
    request = urllib.request.Request(url, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            return Response(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, dict(error.headers or {}), error.read())
    except urllib.error.URLError as error:
        raise RegistryError(f"cannot reach {url}: {error.reason}") from error
