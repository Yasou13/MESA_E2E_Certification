> **Profile B Autonomous Agent Pack v3.1**
> Scope: autonomous decisions for unspecified cases without weakening Profile B.
> Authority rule: live current source/runtime behavior outranks assumptions; hard gates, frozen GT/config, security and H1 remain non-negotiable.

# 28 — AUTONOMOUS DECISION DOCTRINE

This file governs situations that are not explicitly covered elsewhere in the pack. The goal is to let the agent choose the most reasonable safe action without repeatedly asking the user, while keeping the benchmark credible.

## Decision hierarchy

When an unspecified situation occurs, apply this order:

1. **Discover facts first.** Inspect current source, CLI/OpenAPI/schema/runtime state and existing evidence. Do not guess.
2. **Preserve test validity.** Never choose an option that lowers a hard gate, changes frozen TEST/GT/corpus/config to improve results, hides a failure, bypasses native product paths, or weakens security.
3. **Prefer the smallest architecture-consistent action.** Reuse existing product abstractions and dependencies. Avoid new frameworks, broad refactors, speculative features and unrelated cleanup.
4. **Prefer reversible and deterministic actions.** If several options are correct, choose the one with the smallest blast radius, clearest rollback, least state mutation and best reproducibility.
5. **Prefer evidence over convenience.** A slower but bounded real-path verification is preferred over a mock/assumption when a hard gate depends on real behavior.
6. **Classify before repairing.** Product, cross-repo contract, deployment, harness, data-quality, environment and external-provider failures require different actions.
7. **Record the decision before or immediately after execution.** Material unspecified decisions go to `decision_log.jsonl`.

## Decision log schema

Append one JSON object per material decision:

```json
{
  "decision_id": "D-0001",
  "run_id": "B-...",
  "phase": "Phase 2",
  "utc": "...Z",
  "situation": "What was not explicitly covered",
  "facts_discovered": ["..."],
  "options_considered": [
    {"option":"A","pros":["..."],"cons":["..."]},
    {"option":"B","pros":["..."],"cons":["..."]}
  ],
  "selected_option": "B",
  "reason": "Why this best preserves product architecture and certification validity",
  "evidence_paths": ["..."],
  "impact_on_test": "none|run-invalidating|precondition-only|other",
  "changes_hard_gate": false,
  "reversible": true,
  "requires_human_authorization": false
}
```

## The agent may decide autonomously when

All are true:

- the action stays inside already-authorized Profile B scope;
- it does not change a frozen benchmark definition or hard threshold;
- it does not expose secrets or weaken authorization/isolation;
- it is reversible or has a clear bounded recovery path;
- it is supported by current code/runtime evidence;
- it is the smallest reasonable action;
- its rationale is logged.

Examples: choosing the current CLI spelling discovered from `--help`, selecting the next deterministic acquisition window, using an existing repository test helper instead of writing a duplicate, choosing a bounded retry within policy, or fixing a reproduced small contract bug on the correct cert branch.

## The agent must stop and request authorization when

Any applies:

- H1 human approval is required or rejected;
- a decision would change hard gates, TEST composition, GT semantics, corpus policy, model/provider identity, or certification scope;
- destructive/irreversible action would touch user data/history outside disposable run state;
- force-push/reset/delete/secret rotation/security weakening would be required;
- two materially different architecture choices remain and current source/tests do not establish the correct product intent;
- legal/source authenticity cannot be established safely;
- an action would incur unbounded external/provider cost beyond the declared budget;
- the agent lacks authorization required by GitHub/provider/environment.

Stopping truthfully is preferred to inventing authority.

## Unspecified bug policy

For a newly discovered bug not named in this pack:

```text
preserve evidence
→ reproduce minimally
→ classify root cause
→ inspect intended current architecture
→ add focused regression where practical
→ make minimal fix in the owning repository cert branch
→ focused tests + local CI-equivalent
→ inspect diff
→ atomic green commit
→ invalidate active run if executable behavior changed
→ new RUN_ID / clean state / Phase 0
```

Do not add a feature merely because it might improve benchmark metrics. A product change is justified only by a reproduced correctness/integration/safety defect within Profile B scope.

## Conflict resolution

If documents conflict, use this precedence:

1. explicit hard-gate/security/H1/anti-gaming rules in this pack;
2. live product contract and tests/runtime behavior for implementation details;
3. this decision doctrine;
4. archive findings/examples;
5. convenience.

Record the conflict and resolution in the decision log.

## Workspace cleanup decisions

For historical VM artifacts, the default decision is **do not delete**.

Prefer:

1. isolation,
2. leaving non-contaminating state untouched,
3. quarantine/archive of clearly certification-owned state when necessary,
4. deletion only when ownership and necessity are both proven.

Material cleanup/isolation decisions must be written to
`runs/<RUN_ID>/decision_log.jsonl`.
