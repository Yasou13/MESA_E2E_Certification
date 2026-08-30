# scripts/

This directory is for small operational/reproducibility scripts owned by the certification repository.

## Allowed examples

- baseline manifest capture;
- sanitized provider/runtime preflight;
- clean-run initialization;
- deterministic checksum generation;
- official result export;
- CI-equivalent convenience wrappers.

## Rules

- scripts must fail closed;
- never print secrets;
- use `set -euo pipefail` for shell where appropriate;
- do not hide non-zero exit codes;
- do not mutate `main`;
- destructive cleanup must be limited to clearly identified current RUN_ID runtime directories;
- important scripts need self-tests or dry-run checks;
- changing an executable script after a run starts invalidates the run.

