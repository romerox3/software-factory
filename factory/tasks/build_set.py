"""Build a public task set from a pinned dataset revision.

The driver keeps the order of docs/06 §2.1: download the split, pin each image
by digest, select the eligible rows, and for every candidate pull the image,
extract the repository the image already holds, revalidate it and drop the image
again. Every step is injectable so the tests can run without network or Docker.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory.miner.revalidate import revalidate
from factory.miner.runner import DockerRunner, RunnerError, TestRunner
from factory.tasks.image import ImageError, checkout, extract_repo, pull_image, remove_image
from factory.tasks.import_hf import (
    DEFAULT_EXCLUDED_PATH_REGEXES,
    Candidate,
    Rejection,
    download_split,
    load_split,
    select,
    update_manifest,
    write_task,
)
from factory.tasks.inventory import count_tasks
from factory.tasks.registry import RegistryError
from factory.tasks.registry import resolve_digest as registry_digest

DEFAULT_BUDGET = {"usd": 1.0, "max_turns": 24, "timeout_sec": 900}
REPETITIONS = 3


@dataclass(frozen=True)
class BuildDeps:
    """The side-effecting steps of the build, replaced by fakes in tests."""

    download: Callable[[str, str, str, Path], Path] = download_split
    resolve_digest: Callable[[str], str] = registry_digest
    pull: Callable[[str], None] = pull_image
    extract: Callable[[str, Path], str] = extract_repo
    checkout: Callable[[Path, str], None] = checkout
    remove: Callable[[str], None] = remove_image
    runner: Callable[..., TestRunner] = DockerRunner
    revalidate: Callable[..., dict[str, Any]] = revalidate


def main(argv: Sequence[str] | None = None, *, deps: BuildDeps | None = None) -> int:
    args = _parse(argv)
    deps = deps or BuildDeps()
    args.work.mkdir(parents=True, exist_ok=True)

    downloaded = deps.download(args.dataset, args.revision, args.split, args.work / "download")
    rows = load_split(downloaded, args.split)
    if args.only is not None:
        rows = _restrict(rows, args.only, args.split)
    digests = _resolve_digests(rows, deps.resolve_digest)
    candidates, rejections = select(
        rows,
        source=args.source,
        cutoff=args.cutoff,
        digests=digests,
        excluded_path_regexes=list(DEFAULT_EXCLUDED_PATH_REGEXES),
        seed=args.seed,
        limit=args.limit,
    )

    entries: list[dict[str, str]] = []
    skipped = 0
    for candidate in candidates:
        entries.append(_manifest_entry(candidate, args.dataset, args.revision))
        if (args.store / "hidden" / candidate.task_id / "revalidation.json").is_file():
            skipped += 1
            print(f"skip {candidate.task_id}: already revalidated")
            continue
        _build_one(candidate, args, deps)

    update_manifest(args.manifest, entries)
    _print_summary(args.store, candidates, rejections, skipped)
    return 0


def _build_one(candidate: Candidate, args: argparse.Namespace, deps: BuildDeps) -> None:
    repo = args.work / "repos" / candidate.task_id
    tmp_root = args.work / "tmp"
    try:
        deps.pull(candidate.image)
        if repo.exists():
            shutil.rmtree(repo)
        workdir = deps.extract(candidate.image, repo)
        deps.checkout(repo, candidate.base_commit)
        task = replace(candidate, workdir=workdir)
        write_task(
            task,
            args.store,
            dataset=args.dataset,
            revision=args.revision,
            budget=dict(DEFAULT_BUDGET),
        )
        result = deps.revalidate(
            args.store,
            task.task_id,
            repo,
            deps.runner(candidate.image, tmp_root=tmp_root),
            repetitions=REPETITIONS,
            seed=args.seed,
            tmp_root=tmp_root,
        )
        detail = result.get("detail")
        suffix = f": {detail[:200]}" if detail else ""
        print(f"{task.task_id}: {result['reason']}{suffix}")
    except (ImageError, RunnerError, OSError) as exc:
        print(f"{candidate.task_id}: failed: {str(exc)[:200]}", file=sys.stderr)
    finally:
        if not args.keep_images:
            deps.remove(candidate.image)


def _restrict(rows: list[dict[str, Any]], only: Path, split: str) -> list[dict[str, Any]]:
    """Keep the rows listed in ``only``; ids missing from the split are only reported."""
    ids: list[str] = [
        text
        for line in Path(only).read_text(encoding="utf-8").splitlines()
        if (text := line.strip()) and not text.startswith("#")
    ]
    wanted = set(ids)
    present = {str(row["instance_id"]) for row in rows}
    for instance_id in dict.fromkeys(ids):
        if instance_id not in present:
            print(f"not in split {split}: {instance_id}", file=sys.stderr)
    return [row for row in rows if str(row["instance_id"]) in wanted]


def _resolve_digests(rows: list[dict[str, Any]], resolve: Callable[[str], str]) -> dict[str, str]:
    """Pin every image of the split; an unresolvable one becomes a ``no_digest`` rejection."""
    images = sorted({str(row["docker_image"]) for row in rows if row.get("docker_image")})
    digests: dict[str, str] = {}
    for image in images:
        try:
            digests[image] = resolve(image)
        except RegistryError as exc:
            print(f"no digest for {image}: {exc}", file=sys.stderr)
    return digests


def _manifest_entry(candidate: Candidate, dataset: str, revision: str) -> dict[str, str]:
    return {
        "dataset": dataset,
        "revision": revision,
        "instance_id": candidate.instance_id,
        "task_id": candidate.task_id,
        "image": candidate.image,
        "digest": candidate.digest,
    }


def _print_summary(
    store: Path, candidates: list[Candidate], rejections: list[Rejection], skipped: int
) -> None:
    counts, total = count_tasks(store)
    print(f"candidates: {len(candidates)} ({skipped} already revalidated)")
    reasons = Counter(rejection.reason for rejection in rejections)
    for reason in sorted(reasons):
        print(f"rejected {reason}: {reasons[reason]}")
    for language in sorted(counts):
        print(f"valid {language}: {counts[language]}")
    print(f"valid total: {total}")


def _cutoff(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="factory.tasks.build_set")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--source", required=True, choices=("rebench", "multilang"))
    parser.add_argument("--cutoff", required=True, type=_cutoff)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--only", type=Path)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
