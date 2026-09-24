"""Scan tracked text files for a small set of high-confidence secret formats."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


SECRET_PATTERNS = {
    "private key": re.compile(
        b"-" * 5 + rb"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY" + b"-" * 5
    ),
    "OpenAI-style key": re.compile(rb"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
}
MAX_TEXT_FILE_BYTES = 5 * 1024 * 1024


def tracked_paths(repository: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return [repository / raw.decode("utf-8") for raw in completed.stdout.split(b"\0") if raw]


def scan(repository: Path) -> list[str]:
    findings: list[str] = []
    for path in tracked_paths(repository):
        if not path.is_file() or path.stat().st_size > MAX_TEXT_FILE_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(data):
                findings.append(f"{path.relative_to(repository)}: {label}")
    return findings


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    findings = scan(repository)
    if findings:
        for finding in findings:
            print(f"FAIL: potential secret: {finding}")
        return 1
    print("PASS: no high-confidence secret formats in tracked text files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
