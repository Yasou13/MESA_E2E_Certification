# reports/

This directory owns report templates and generated certification summaries.

The authoritative final-report structure is defined in `../agent-pack/23_FINAL_REPORT_TEMPLATE.md`.

## Report rules

- Report the exact verdict; never soften a hard-gate failure into a pass.
- Separate retrieval quality from answer quality.
- Separate native E2E success from diagnostic bridge observations.
- List all limitations and invalidated prior attempts.
- Tie claims to concrete evidence paths/hashes.
- Do not embed the report's own SHA-256 inside itself.
- Generate checksum information only after the report is final.

Generated reports may live under `reports/generated/<RUN_ID>/`.

