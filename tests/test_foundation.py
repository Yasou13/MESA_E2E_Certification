from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from harness.self_test import run_harness_self_tests
from scripts.verify_agent_pack import verify_agent_pack


REPOSITORY = Path(__file__).resolve().parents[1]


def test_harness_modules_compile() -> None:
    for path in sorted((REPOSITORY / "harness").glob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_harness_modules_import() -> None:
    __import__("harness.answer_scorer")
    __import__("harness.identity")
    __import__("harness.models")
    __import__("harness.normalizer")
    __import__("harness.retrieval_scorer")


def test_agent_pack_checksums() -> None:
    assert verify_agent_pack(REPOSITORY / "agent-pack") == []


def test_self_test_uses_no_optimizable_assert_statements() -> None:
    source = (REPOSITORY / "harness" / "self_test.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]


def test_self_test_report_is_green() -> None:
    report = run_harness_self_tests()
    assert report["all_passed"] is True
    assert report["failed_cases"] == 0
    assert report["passed_cases"] == report["total_cases"]


def test_self_test_runs_under_python_optimization() -> None:
    completed = subprocess.run(
        [sys.executable, "-O", "-m", "harness.self_test"],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "all_passed=True" in completed.stdout
