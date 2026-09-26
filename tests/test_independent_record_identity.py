"""Independent regressions reproduced before correction."""
import json
import gzip
import pytest
from harness.evidence import validate_run_id_consistency
from tests.independent_support import score_claims

@pytest.mark.parametrize("extension", ["jsonl", "jsonl.gz", "json", "json.gz"])
def test_every_structured_record_requires_identity(tmp_path, extension):
    rows = [{"run_id": "RUN-independent"}, {"result": "unowned"}]
    text = "\n".join(json.dumps(r) for r in rows) if "jsonl" in extension else json.dumps(rows)
    data = text.encode()
    (tmp_path / ("observations." + extension)).write_bytes(gzip.compress(data) if extension.endswith("gz") else data)
    assert validate_run_id_consistency(tmp_path, "RUN-independent")["status"] != "PASS"


