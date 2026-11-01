"""The build driver orchestrates without touching the network or Docker."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory.tasks import build_set
from factory.tasks.build_set import BuildDeps
from factory.tasks.import_hf import load_rows
from factory.tasks.registry import RegistryError

REPO_ROOT = Path(__file__).parents[2]
REBENCH = REPO_ROOT / "fixtures" / "hf" / "rebench-sample.jsonl"
TASK_ID = "acme__widgets-1001"
DIGEST = "sha256:" + "ab" * 32
DATASET = "nebius/SWE-rebench-leaderboard"
REVISION = "f" * 40


class FakeBuild:
    def __init__(self, tmp_path: Path, *, digest_error: bool = False) -> None:
        self.download_dir = tmp_path / "download"
        self.download_dir.mkdir(parents=True)
        row = dict(load_rows(REBENCH)[0])
        (self.download_dir / "2026_03.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.digest_error = digest_error
        self.calls: list[tuple[Any, ...]] = []

    def download(self, dataset: str, revision: str, split: str, dest: Path) -> Path:
        self.calls.append(("download", dataset, revision, split))
        return self.download_dir

    def resolve_digest(self, image: str) -> str:
        self.calls.append(("digest", image))
        if self.digest_error:
            raise RegistryError("no network")
        return DIGEST

    def pull(self, image: str) -> None:
        self.calls.append(("pull", image))

    def extract(self, image: str, dest: Path) -> str:
        self.calls.append(("extract", image, dest))
        dest.mkdir(parents=True)
        (dest / "package.py").write_text("value = 1\n", encoding="utf-8")
        return "/testbed"

    def checkout(self, repo: Path, commit: str) -> None:
        self.calls.append(("checkout", repo, commit))

    def remove(self, image: str) -> None:
        self.calls.append(("remove", image))

    def revalidate(
        self,
        store: Path,
        task_id: str,
        base_repo: Path,
        runner: object,
        *,
        repetitions: int,
        seed: int,
    ) -> dict[str, Any]:
        self.calls.append(("revalidate", task_id, base_repo, repetitions))
        outcome = {"valid": True, "reason": "ok", "f2p": [], "p2p": []}
        path = store / "hidden" / task_id / "revalidation.json"
        path.write_text(json.dumps(outcome), encoding="utf-8")
        return outcome

    def deps(self) -> BuildDeps:
        return BuildDeps(
            download=self.download,
            resolve_digest=self.resolve_digest,
            pull=self.pull,
            extract=self.extract,
            checkout=self.checkout,
            remove=self.remove,
            runner=lambda image: object(),
            revalidate=self.revalidate,
        )


def arguments(tmp_path: Path, *extra: str, cutoff: str = "2026-01-01") -> list[str]:
    return [
        "--dataset",
        DATASET,
        "--revision",
        REVISION,
        "--split",
        "2026_03",
        "--source",
        "rebench",
        "--cutoff",
        cutoff,
        "--limit",
        "5",
        "--store",
        str(tmp_path / "store"),
        "--manifest",
        str(tmp_path / "tasks" / "public-v1.manifest.json"),
        "--work",
        str(tmp_path / "work"),
        *extra,
    ]


def test_one_candidate_runs_the_whole_recipe_and_drops_the_image(tmp_path: Path) -> None:
    fake = FakeBuild(tmp_path)

    assert build_set.main(arguments(tmp_path), deps=fake.deps()) == 0

    kinds = [call[0] for call in fake.calls]
    assert kinds == ["download", "digest", "pull", "extract", "checkout", "revalidate", "remove"]
    task = json.loads((tmp_path / "store" / "visible" / TASK_ID / "factory.task.json").read_text())
    assert task["repo"]["workdir"] == "/testbed"
    assert task["image"] == f"ghcr.io/acme/widgets-1001@{DIGEST}"
    manifest = json.loads((tmp_path / "tasks" / "public-v1.manifest.json").read_text())
    assert manifest["tasks"] == [
        {
            "dataset": DATASET,
            "revision": REVISION,
            "instance_id": TASK_ID,
            "task_id": TASK_ID,
            "image": f"ghcr.io/acme/widgets-1001@{DIGEST}",
            "digest": DIGEST,
        }
    ]
    checkout = next(call for call in fake.calls if call[0] == "checkout")
    assert checkout[2] == load_rows(REBENCH)[0]["base_commit"]


def test_keep_images_leaves_the_image_in_place(tmp_path: Path) -> None:
    fake = FakeBuild(tmp_path)

    build_set.main(arguments(tmp_path, "--keep-images"), deps=fake.deps())

    assert "remove" not in [call[0] for call in fake.calls]


def test_an_already_revalidated_task_is_skipped(tmp_path: Path) -> None:
    fake = FakeBuild(tmp_path)
    outcome = tmp_path / "store" / "hidden" / TASK_ID / "revalidation.json"
    outcome.parent.mkdir(parents=True)
    outcome.write_text(json.dumps({"valid": True}), encoding="utf-8")

    assert build_set.main(arguments(tmp_path), deps=fake.deps()) == 0

    assert [call[0] for call in fake.calls] == ["download", "digest"]
    manifest = json.loads((tmp_path / "tasks" / "public-v1.manifest.json").read_text())
    assert [entry["task_id"] for entry in manifest["tasks"]] == [TASK_ID]


def test_an_unresolvable_digest_rejects_the_row(tmp_path: Path) -> None:
    fake = FakeBuild(tmp_path, digest_error=True)

    assert build_set.main(arguments(tmp_path), deps=fake.deps()) == 0

    assert [call[0] for call in fake.calls] == ["download", "digest"]
    assert not (tmp_path / "store" / "visible" / TASK_ID).exists()


def test_the_cutoff_drops_older_rows(tmp_path: Path) -> None:
    fake = FakeBuild(tmp_path)

    build_set.main(arguments(tmp_path, cutoff="2027-01-01"), deps=fake.deps())

    assert [call[0] for call in fake.calls] == ["download", "digest"]


def test_cutoff_is_parsed_as_utc_midnight() -> None:
    args = build_set._parse(
        [
            "--dataset",
            DATASET,
            "--revision",
            REVISION,
            "--split",
            "2026_03",
            "--source",
            "rebench",
            "--cutoff",
            "2026-01-01",
            "--limit",
            "1",
            "--store",
            "store",
            "--manifest",
            "manifest.json",
            "--work",
            "work",
        ]
    )

    assert args.cutoff == datetime(2026, 1, 1, tzinfo=UTC)
