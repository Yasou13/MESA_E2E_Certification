# MESA Legal E2E Certification

**Official certification name:** MESA Profile B — Legal End-to-End Integration & Retrieval Certification  
**Test ID:** `MESA-PROFILE-B-LEGAL-E2E`

This repository contains the independent certification harness, frozen benchmark artifacts, agent operating contract, evidence structure, and reports for the Profile B legal end-to-end certification of **MESA + MESA_Data**.

## What Profile B proves

Profile B is intended to prove, with current-run evidence, that:

1. official legal source data can be acquired and preserved by MESA_Data;
2. raw bytes can be decoded/canonicalized without silent Turkish text loss;
3. approved data can be released and published through the **native MESA_Data → MESA product path**;
4. MESA can ingest the release through its real V4 lifecycle;
5. real NVIDIA Nemotron passage/query embeddings are used correctly;
6. real NVIDIA GPT-OSS structured extraction works through the production extraction path;
7. retrieval quality reaches frozen hard gates without TEST-set tuning;
8. Kùzu graph participation is observable and causally useful on designated relational queries;
9. tenant/principal isolation, provenance, idempotency, and restart persistence hold;
10. final answers are grounded only in retrieved evidence and abstain when evidence is insufficient.

## What Profile B does not prove

A Profile B pass is **not** the same as full MESA MVP certification. Final MVP certification requires the complete certification program, including the other required profiles/gates.

## Repository layout

```text
.
├── agent-pack/       authoritative autonomous-agent operating contract
├── config/           benchmark/runtime config contracts and frozen config artifacts
├── datasets/         corpus manifests and runtime dataset area
├── ground-truth/     independent DEV/TEST qrels and grading truth
├── harness/          deterministic certification harness/scorers
├── evidence/         immutable per-run evidence (runtime content normally ignored)
├── runs/             per-run state/control records
├── reports/          generated/final reports
├── scripts/          reproducibility and operational scripts
├── README.md
└── MANIFEST.md
```

## Agent entry point

The autonomous agent must start with:

```text
agent-pack/00_START_HERE.md
```

It must then read the numbered files **strictly in numerical order**. Do not skip directly to a later file because it looks more relevant.

## Branch policy

The working branch is:

```text
cert/profile-b-e2e
```

Use this branch in this certification repository and in the separate MESA and MESA_Data repositories. Product fixes discovered during certification must never be committed directly to `main`.

## Truth hierarchy

When sources disagree, use this order:

1. observed current runtime behavior;
2. current checked-out source code and schemas;
3. current tests/configuration;
4. this certification contract;
5. old archive findings or previous run evidence;
6. README assumptions or conversation summaries.

Never guess a route, CLI command, schema, environment variable, capability, or expected output when the live repositories can be inspected.

## Key integrity rule

Ground truth and frozen TEST configuration must exist **before** the first TEST retrieval request. TEST results may not be used to edit queries, qrels, expected evidence, thresholds, retrieval weights, prompts, or model settings.

## Failure is an acceptable result

The purpose of this repository is truthful certification, not obtaining a green badge. A reproducible failure or external blocker is preferable to a false PASS.

