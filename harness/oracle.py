"""Recursive oracle leakage audit for execution requests, prompts, and context."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


FORBIDDEN_FIELD_NAMES = {
    "acceptableanswerpatterns",
    "expectedanswer",
    "expectedanswers",
    "expectedlabel",
    "expectedstatus",
    "forbiddenclaims",
    "goldevidenceid",
    "goldevidenceids",
    "qrel",
    "qrels",
    "requiredfact",
    "requiredfacts",
}
FORBIDDEN_TEXT_PATTERNS = (
    ("expected_answer", re.compile(r"\bexpected[ _-]+answers?\b", re.IGNORECASE)),
    ("required_facts", re.compile(r"\brequired[ _-]+facts?\b", re.IGNORECASE)),
    (
        "gold_evidence_ids",
        re.compile(r"\bgold[ _-]+evidence(?:[ _-]+ids?)?\b", re.IGNORECASE),
    ),
    ("qrels", re.compile(r"\bqrels?\b", re.IGNORECASE)),
    (
        "expected_pass_fail_label",
        re.compile(r"\bexpected[ _-]+(?:pass|fail)[ _-]+label\b", re.IGNORECASE),
    ),
)


def _normalized_field(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def audit_oracle_surfaces(surfaces: dict[str, Any]) -> dict[str, object]:
    findings: list[dict[str, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value, key=str):
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _normalized_field(key_text) in FORBIDDEN_FIELD_NAMES:
                    findings.append(
                        {
                            "path": child_path,
                            "kind": "forbidden_field",
                            "matched_token": key_text,
                        }
                    )
                    continue
                visit(value[key], child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        elif isinstance(value, str):
            for label, pattern in FORBIDDEN_TEXT_PATTERNS:
                if pattern.search(value):
                    findings.append(
                        {
                            "path": path,
                            "kind": "forbidden_prompt_token",
                            "matched_token": label,
                        }
                    )

    visit(surfaces, "")
    return {
        "schema_version": "1.0",
        "status": "FAIL" if findings else "PASS",
        "finding_count": len(findings),
        "findings": findings,
        "values_redacted": True,
    }


def write_oracle_audit(report: dict[str, object], path: str | Path) -> None:
    serialized = json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    Path(path).write_text(serialized, encoding="utf-8", newline="\n")
