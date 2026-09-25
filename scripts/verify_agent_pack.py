"""Fail-closed checksum verification for the frozen agent pack."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


SHA256_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^/\\]+)$")


def verify_agent_pack(agent_pack: Path) -> list[str]:
    manifest = agent_pack / "SHA256SUMS.txt"
    if not manifest.is_file():
        return [f"missing checksum manifest: {manifest}"]

    failures: list[str] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = SHA256_LINE.fullmatch(raw_line)
        if match is None:
            failures.append(f"malformed manifest line {line_number}")
            continue
        name = match.group("name")
        if name in seen:
            failures.append(f"duplicate manifest entry: {name}")
            continue
        seen.add(name)
        path = agent_pack / name
        if not path.is_file():
            failures.append(f"missing agent-pack file: {name}")
            continue
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != match.group("digest"):
            failures.append(f"checksum mismatch: {name}")

    frozen_files = {
        path.name
        for path in agent_pack.iterdir()
        if path.is_file() and path.name not in {manifest.name, ".gitkeep"}
    }
    unlisted = sorted(frozen_files - seen)
    if unlisted:
        failures.extend(f"unlisted agent-pack file: {name}" for name in unlisted)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent-pack", type=Path, default=Path("agent-pack"), help="agent pack path"
    )
    args = parser.parse_args()
    failures = verify_agent_pack(args.agent_pack)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: agent-pack checksums and membership verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
