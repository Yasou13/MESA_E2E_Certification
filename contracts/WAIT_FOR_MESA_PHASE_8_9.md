# WAIT_FOR_MESA_PHASE_8_9 — graph value/retrieval adapter

Status: `WAIT_FOR_MESA_PHASE_8_9`

Required fields: graph origin, stable path/hop/assertion IDs, evidence IDs,
rank contributions, and paired graph-ON/graph-OFF execution identity.

Required semantics: participation, positive utility, neutral effect, and harm
are distinct machine metrics. Worse rank or evidence coverage is graph harm,
not synergy.

Versioning: freeze graph schema, graph snapshot, evaluator version, query set,
and ON/OFF runtime settings.

Fail-closed behavior: logging-only graph claims, unmatched ON/OFF runs, invalid
paths, or missing causal evidence leave B11 unverified/failed.

Synchronization tests: valid path/hop identity, origin participation, rank
improvement, neutral result, rank degradation/harm, and unmatched ablation.
