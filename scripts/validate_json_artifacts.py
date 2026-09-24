"""Perform basic syntax validation for tracked JSON and JSONL artifacts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def tracked_artifacts(repository: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "*.json", "*.jsonl"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return sorted(
        repository / raw.decode("utf-8")
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def validate(repository: Path) -> list[str]:
    failures: list[str] = []
    for path in tracked_artifacts(repository):
        try:
            if path.suffix == ".jsonl":
                with path.open("r", encoding="utf-8") as stream:
                    for line_number, line in enumerate(stream, start=1):
                        if line.strip():
                            json.loads(line)
            else:
                with path.open("r", encoding="utf-8") as stream:
                    json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            failures.append(f"{path.relative_to(repository)}: {exc}")
    return failures


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    failures = validate(repository)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: tracked JSON and JSONL artifacts are syntactically valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
