# runs/

This directory contains per-run control/state metadata under `runs/<RUN_ID>/`.

A RUN_ID identifies one coherent certification attempt with immutable executable logic, product SHAs, frozen benchmark inputs, and runtime configuration.

## Terminal states

Typical states include:

- `PASS_NATIVE`;
- `FAIL`;
- `BLOCKED_EXTERNAL`;
- `BLOCKED_ENVIRONMENT`;
- `INVALIDATED_CODE_CHANGE`;
- diagnostic-only bridge outcome where applicable.

Never reuse an invalidated RUN_ID. A repair that changes product/harness/config logic requires a new RUN_ID and Phase 0 restart.

See `../agent-pack/14_EXECUTION_PHASES.md` and `19_FAILURE_TRIAGE_REPAIR_RESTART.md`.

