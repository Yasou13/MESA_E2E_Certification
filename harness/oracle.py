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


def extract_raw_audit_surfaces(
    run_dir: str | Path, raw_manifest: dict[str, Any]
) -> dict[str, Any]:
    """Derive recursive audit surfaces from sealed raw artifacts."""
    surfaces: dict[str, Any] = {}
    base_dir = Path(run_dir)
    for entry in raw_manifest.get("entries", []):
        file_path = base_dir / entry["path"]
        if not file_path.is_file():
            continue
        try:
            content = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Scan all execution inputs/requests/prompts/context; exclude outputs
        audit_payload = {
            k: v
            for k, v in content.items()
            if k not in {"response", "raw_response", "parsed_response"}
        }
        surfaces[entry["path"]] = audit_payload
    return surfaces


def audit_oracle_surfaces(
    surfaces: dict[str, Any],
    *,
    known_oracle_values: set[str] | list[str] | None = None,
    raw_manifest: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    oracle_val_set: set[str] = {str(v) for v in (known_oracle_values or []) if v}

    if not surfaces and raw_manifest and not raw_manifest.get("entries"):
        findings.append(
            {
                "path": "raw_manifest",
                "kind": "empty_raw_execution",
                "matched_token": "0_records",
            }
        )

    def _check_oracle_val(text: str, path: str) -> None:
        for token in oracle_val_set:
            if token == text or re.search(r"(?:\b|_)" + re.escape(token) + r"(?:\b|_)", text, re.IGNORECASE):
                findings.append(
                    {
                        "path": path,
                        "kind": "known_oracle_value",
                        "matched_token": token,
                    }
                )

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
                for label, pattern in FORBIDDEN_TEXT_PATTERNS:
                    if pattern.search(key_text):
                        findings.append(
                            {
                                "path": child_path,
                                "kind": "forbidden_key_token",
                                "matched_token": label,
                            }
                        )
                _check_oracle_val(key_text, child_path)
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
            _check_oracle_val(value, path)
        elif isinstance(value, (int, float, bool)):
            _check_oracle_val(str(value), path)

    visit(surfaces, "")
    manifest_hash = raw_manifest.get("manifest_hash") if isinstance(raw_manifest, dict) else None
    raw_artifacts = raw_manifest.get("entries") if isinstance(raw_manifest, dict) else []
    return {
        "schema_version": "1.0",
        "auditor_version": "1.0.0",
        "run_id": run_id,
        "status": "FAIL" if findings else "PASS",
        "finding_count": len(findings),
        "findings": findings,
        "values_redacted": True,
        "raw_manifest_hash": manifest_hash,
        "raw_artifacts": raw_artifacts,
    }


def write_oracle_audit(report: dict[str, object], path: str | Path) -> None:
    serialized = json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    Path(path).write_text(serialized, encoding="utf-8", newline="\n")
