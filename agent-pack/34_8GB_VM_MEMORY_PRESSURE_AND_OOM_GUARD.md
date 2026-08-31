# 34 — 8 GiB VM Memory Pressure and OOM Guard

## Purpose

Profile B is expected to be runnable on a certification VM with at least
8 GiB RAM.

This document defines proactive memory-pressure protection so the agent does
not merely detect an OOM after the fact.

The guard applies to:

- MESA,
- MESA_Data,
- certification harness,
- Docker/Compose,
- SQLite,
- LanceDB,
- Kùzu,
- workers,
- ingestion/indexing,
- retrieval benchmark,
- graph ablation,
- final-answer generation.

The purpose is to preserve a valid certification run without hiding genuine
product resource failures.

---

# 1. Hard environment floor

Official Profile B requires:

```text
RAM >= 8 GiB
```

Recommended:

```text
RAM >= 12 GiB
```

If total usable RAM is below 8 GiB:

```text
PROFILE_B_BLOCKED_PRECONDITION
```

Do not compensate for sub-8-GiB RAM by silently increasing swap and pretending
the RAM requirement was met.

---

# 2. Swap policy

Swap is a safety buffer, not replacement RAM.

For an 8 GiB VM, approximately 4 GiB swap is recommended when the host permits
it.

Before changing swap, inspect:

```text
free -h
swapon --show
df -h
```

The agent MUST NOT blindly create/resize swap.

If swap creation is necessary and safe:

- do it only before official RUN freeze,
- require sufficient disk space,
- preserve any existing user/admin swap configuration,
- use the smallest reasonable change,
- record the change in `decision_log.jsonl`,
- record before/after state in the environment evidence.

If the agent lacks safe privileges or cannot prove the change is harmless,
leave swap unchanged and continue only if the memory guard can safely protect
the run.

Heavy sustained swapping is a resource warning, not a successful substitute for
RAM.

---

# 3. Canonical 8 GiB pressure thresholds

For the canonical 8 GiB VM, use these predeclared host `MemAvailable`
thresholds unless a stronger pre-frozen environment policy exists:

```text
NORMAL:
  MemAvailable >= 2.0 GiB

WARNING:
  1.5 GiB <= MemAvailable < 2.0 GiB

PRESSURE:
  1.0 GiB <= MemAvailable < 1.5 GiB

CRITICAL:
  MemAvailable < 1.0 GiB
```

These thresholds are resource-safety thresholds, not product scoring
thresholds.

Record the exact thresholds in:

```text
runs/<RUN_ID>/resource-guard-config.json
```

before official TEST.

Do not loosen them after observing TEST behavior.

---

# 4. What must be monitored

At minimum capture:

```text
host MemTotal
host MemAvailable
host SwapTotal
host SwapFree
host swap used
load average
disk free
Docker/container memory usage
Docker/container memory limit
container restart count
container OOMKilled state
MESA API RSS/memory
MESA worker RSS/memory
MESA_Data process RSS/memory when active
LanceDB-related process/container memory
Kùzu-related process/container memory
kernel/cgroup OOM events
```

When cgroup v2 is available, inspect relevant:

```text
memory.current
memory.max
memory.events
```

and especially counters such as:

```text
oom
oom_kill
```

Do not assume a container restart was benign.

---

# 5. Monitoring cadence

The guard must run:

- before MESA boot,
- after MESA boot,
- before native MESA_Data publish,
- during ingestion/indexing,
- during graph construction,
- before official TEST,
- during official TEST,
- during graph ON/OFF ablation,
- before final-answer generation batches,
- after official TEST,
- before teardown.

During active heavy phases, sample memory frequently enough to detect pressure
before an OOM.

Recommended default:

```text
every 5-15 seconds during heavy operations
every 30-60 seconds during low activity
```

The exact cadence may be chosen before freeze and recorded.

Do not poll so aggressively that the monitor itself materially distorts the
benchmark.

---

# 6. NORMAL behavior

At:

```text
MemAvailable >= 2.0 GiB
```

the agent may proceed normally with the already frozen workload.

Do not increase concurrency simply because spare RAM exists once official TEST
has begun.

---

# 7. WARNING behavior

At:

```text
1.5 GiB <= MemAvailable < 2.0 GiB
```

the agent must:

- record a pressure event,
- increase monitoring frequency,
- avoid starting a new unrelated heavy operation,
- avoid launching extra diagnostic workloads concurrently,
- avoid cache-warming or optional tooling that is not required for the active
  gate,
- allow the already-running product operation to complete if safe.

Do not change frozen official TEST semantics.

---

# 8. PRESSURE behavior

At:

```text
1.0 GiB <= MemAvailable < 1.5 GiB
```

the agent must:

- record a PRESSURE event,
- stop scheduling new heavy harness work,
- serialize optional harness-side tasks,
- wait for currently expected temporary peaks to recover,
- inspect swap growth,
- inspect container/process memory,
- inspect restart/OOM indicators,
- determine whether the pressure is harness/environment or product driven.

Allowed before official freeze:

- reduce certification-harness concurrency,
- reduce certification-harness batch size,
- serialize independent harness operations,
- avoid running ingestion and benchmark phases concurrently.

Not allowed as a hidden product fix:

- disabling required MESA components,
- bypassing graph,
- reducing official corpus/query set,
- replacing real providers with mocks,
- changing required product semantics,
- hiding a MESA memory leak by permanently constraining the benchmark below its
  intended workload.

---

# 9. CRITICAL behavior

At:

```text
MemAvailable < 1.0 GiB
```

the agent MUST NOT start another heavy phase.

Actions:

1. persist current resource evidence,
2. stop scheduling new harness work,
3. allow only safe bounded recovery,
4. inspect swap/cgroup/kernel/container state,
5. determine whether an OOM/restart already occurred,
6. wait a bounded interval for memory to recover,
7. if memory does not recover, safely abort the active certification phase.

Default bounded recovery window:

```text
up to 120 seconds
```

The agent may choose a smaller safe value before freeze.

It must not wait forever.

If the active product process must be killed to save the VM, preserve evidence
first where possible and classify the run appropriately.

---

# 10. Harness pressure vs product failure

This distinction is mandatory.

## Harness/environment-induced pressure

Example:

```text
certification harness starts excessive parallel workers
+
MESA itself is not showing runaway growth
```

Classify as:

```text
CERT_HARNESS
or
ENVIRONMENT
```

Before official freeze, the agent may reduce harness-only concurrency/batching,
prove the fix, record it, and then freeze the safe configuration.

After freeze, changing official harness execution parameters invalidates the
RUN if the change can affect benchmark semantics/timing/results.

## Product-induced pressure

Example:

```text
normal supported Profile B workload
+
required MESA components
+
8 GiB standard VM
+
MESA memory continues growing
→ OOM/restart
```

This is not solved by hiding the workload.

Classify as product/runtime resource failure.

A standard Profile B run that OOMs because of genuine MESA resource behavior
cannot receive `PROFILE_B_PASS_NATIVE`.

---

# 11. Pre-freeze adaptive sizing only

Before official TEST freeze, the agent may perform bounded resource discovery
using DEV/preflight workloads.

Safe sequence:

```text
start with conservative harness concurrency
        ↓
run representative preflight/DEV workload
        ↓
observe peak memory
        ↓
increase only if needed and safe
        ↓
choose stable harness concurrency/batch size
        ↓
record values
        ↓
freeze
```

The goal is not maximum throughput.

The goal is a valid, representative run that does not waste VM memory.

Do not tune using TEST results.

---

# 12. Official TEST immutability

Once the official contract is frozen, these values are immutable for that RUN
if they can affect execution:

```text
harness concurrency
harness batch size
worker-count overrides
resource-guard thresholds
resource-guard behavior
```

If a material change is required after TEST begins:

```text
current RUN = INVALIDATED_CODE_CHANGE
```

or the appropriate invalidation/config-change verdict.

Then:

1. preserve evidence,
2. adjust before the next RUN,
3. refreeze,
4. rerun TEST from the beginning.

---

# 13. Memory telemetry artifact

Write an append-only machine-readable stream such as:

```text
runs/<RUN_ID>/resource-telemetry.jsonl
```

Each sample should contain, where available:

```text
timestamp_utc
phase
mem_total_bytes
mem_available_bytes
swap_total_bytes
swap_free_bytes
swap_used_bytes
disk_free_bytes
mesa_api_memory_bytes
mesa_worker_memory_bytes
mesa_data_memory_bytes
docker_container_memory
container_restart_counts
container_oomkilled_flags
cgroup_oom_count
cgroup_oom_kill_count
pressure_state
```

Do not include secrets.

---

# 14. Pressure event log

Write:

```text
runs/<RUN_ID>/resource-pressure-events.jsonl
```

For each WARNING/PRESSURE/CRITICAL event record:

```text
timestamp
phase
pressure_state
mem_available
swap_used
largest_processes_or_containers
action_taken
recovery_result
classification
evidence_refs
```

This log is evidence, not a mechanism for silently rewriting the workload.

---

# 15. OOM detection sources

Check multiple sources where available:

```text
docker inspect
docker stats --no-stream
journalctl -k
dmesg / kernel log where permitted
/proc/meminfo
/proc/<pid>/status
cgroup memory.events
```

An OOM is proven if reliable runtime evidence indicates:

```text
OOMKilled=true
kernel OOM kill
cgroup oom_kill increment
process exit attributable to OOM
```

A container that automatically restarts after OOM does not erase the failure.

---

# 16. Swap-pressure rule

Record swap usage throughout the run.

For an 8 GiB VM:

- modest transient swap use may be acceptable,
- rapidly increasing or sustained heavy swap is a WARNING/PRESSURE signal,
- performance results obtained under severe swap thrashing must be labeled.

Do not declare healthy resource behavior solely because the kernel avoided OOM
by aggressively swapping.

If swap thrashing materially invalidates latency comparability, report the
resource condition explicitly.

---

# 17. Disk guard

Memory protection also depends on disk availability because:

- swap may use disk,
- LanceDB can produce files/fragments,
- logs/evidence grow,
- Docker layers/volumes grow.

Before and during heavy phases record free disk.

The existing Profile B disk minimum remains authoritative.

If disk approaches exhaustion:

- do not delete unknown/user data,
- do not prune Docker globally,
- preserve certification evidence,
- classify the issue,
- stop safely if required.

---

# 18. Optional work suppression under pressure

When memory is WARNING/PRESSURE, the agent may postpone optional work such as:

- nonessential report rendering,
- extra diagnostics,
- duplicate static scans,
- unrelated package indexing,
- optional benchmark variants.

It must not postpone or omit required official gates and later pretend they
passed.

Required gates either run successfully or remain non-PASS/blocked.

---

# 19. Antigravity/self-memory discipline

The automation agent itself must avoid unnecessary local resource pressure.

Prefer:

- streaming file processing,
- bounded result sets,
- incremental JSONL evidence,
- one heavy analysis at a time,
- avoiding simultaneous large archive extraction + Docker build + benchmark,
- removing only known temporary certification-owned files when safe.

Do not keep huge logs/results in RAM when they can be streamed to disk.

Do not load the full corpus repeatedly when an indexed/streaming approach is
sufficient.

---

# 20. Pre-TEST resource gate

Immediately before official TEST, require all:

```text
RAM total >= 8 GiB
MemAvailable >= 2.0 GiB
no current OOMKilled required container
no unexplained container restart
cgroup/kernel OOM counters baseline captured
disk requirement satisfied
swap state captured
resource telemetry active
resource guard config frozen
```

If `MemAvailable < 2.0 GiB`, do not start official TEST immediately.

Investigate/recover first.

---

# 21. Post-TEST resource gate

Immediately after official TEST:

- capture final memory/swap state,
- capture peak memory,
- capture OOM/restart counters,
- compare cgroup OOM counters with pre-TEST baseline,
- confirm required services still healthy,
- confirm no hidden OOM/restart occurred.

A numerical benchmark PASS with hidden OOM/restart is not
`PROFILE_B_PASS_NATIVE`.

---

# 22. Required artifacts

This document adds:

```text
runs/<RUN_ID>/resource-guard-config.json
runs/<RUN_ID>/resource-telemetry.jsonl
runs/<RUN_ID>/resource-pressure-events.jsonl
```

and requires OOM/resource summaries in the compact final evidence bundle.

---

# 23. Final report requirements

Report at least:

```text
VM RAM
swap total
peak swap used
minimum observed MemAvailable
peak MESA/API memory
peak worker memory
peak MESA_Data memory
peak container memory
WARNING event count
PRESSURE event count
CRITICAL event count
OOM count
OOM kill count
container restart count
resource-related aborts
```

If no metric is available, state `unavailable` rather than inventing a value.

---

# 24. PASS conditions

Resource guard PASS requires:

- VM RAM floor satisfied,
- resource guard configured before TEST,
- telemetry active during heavy phases,
- memory pressure acted on safely,
- no hidden OOM,
- no unexplained required-container restart,
- no benchmark-semantic weakening to avoid OOM,
- genuine product OOM not reclassified as harness success,
- pre/post resource gates pass,
- evidence artifacts are preserved and checksummed.

A genuine OOM in the required normal Profile B workload prevents
`PROFILE_B_PASS_NATIVE`.

## Token efficiency also protects RAM

Document 35 complements this memory guard.

Prefer:

- streaming evidence,
- bounded source/log reads,
- one heavy analysis/build/test at a time,
- avoiding duplicate Docker builds,
- avoiding repeated full-corpus in-memory analysis.

Do not keep large logs/corpora in memory solely to reduce future tool calls.
Persist them safely and use indexed/bounded reads.
