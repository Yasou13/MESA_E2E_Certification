from pathlib import Path

from scripts.check_no_secrets import scan
from scripts.validate_json_artifacts import validate


REPOSITORY = Path(__file__).resolve().parents[1]


def test_no_high_confidence_secrets_in_tracked_text() -> None:
    assert scan(REPOSITORY) == []


def test_tracked_json_and_jsonl_are_syntactically_valid() -> None:
    assert validate(REPOSITORY) == []
