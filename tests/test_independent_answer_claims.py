"""Independent regressions reproduced before correction."""
import json
import gzip
import pytest
from harness.evidence import validate_run_id_consistency
from tests.independent_support import score_claims

def test_every_claim_must_be_checked():
    assert score_claims(["Ceza 5 yıldır", "Sürgün zorunludur"]).status != "PASS"


def test_vocabulary_overlap_does_not_prove_support():
    assert score_claims(["Ceza 5 yıldır ve tazminat 100 milyon TL olarak belirlenmiştir"]).status != "PASS"


