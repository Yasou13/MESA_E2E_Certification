# Historical audit — RUN-20260901T005200Z-p8b03

This record does not rewrite, delete, rescore, or relabel any artifact in the
historical run directory. The original `CERTIFIED` / `PASS` verdict remains
preserved as historical evidence.

Current interpretation: **not a valid Profile B v2 certification result**.

The live-repository reproduction found nine JSON control artifacts whose
embedded run ID is `RUN-20260831T142600Z-p8b02`, while their directory is
`RUN-20260901T005200Z-p8b03`. No explicit immutable-reuse authorization is
present. The required contract freeze and sidecar checksum are also absent.

The working-plan audit additionally documents hard-gate contradictions,
broad-provenance retrieval inflation, answer-scoring false-PASS behavior, and
missing mandatory evidence. These findings supersede use of the historical
PASS as a future Profile B v2 result; they do not alter the original bytes.

`SHA256SUMS.txt` freezes the original run artifacts as observed during this
audit so accidental later mutation can be detected.
