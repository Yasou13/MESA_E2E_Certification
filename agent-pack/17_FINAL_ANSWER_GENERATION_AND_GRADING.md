> **Profile B Autonomous Agent Pack v3.1**
> Scope: MESA + MESA_Data native legal E2E certification on a dedicated certification branch.  
> Authority rule: the live checked-out repositories and runtime behavior outrank this document when code has changed. Never guess an API, CLI, schema, path, or capability: discover and record it first.

# 17 — FINAL ANSWER GENERATION AND GRADING

## Separation from retrieval

Final-answer scoring is a second lane. Do not let answer correctness alter retrieval qrels/scores.

## Context construction

For each TEST query, create context only from the exact frozen top-5 MESA search response. Include bounded source text plus stable returned chunk/document/source references. Do not fetch additional corpus content based on the model's requests.

If current MESA has a production answer-generation path, prefer it. If MESA is retrieval-only, a certification answer harness may call the current MESA-configured OpenAI-compatible adapter, but it must use only MESA retrieval context and the frozen answer prompt.

## Frozen answer protocol

Require structured output, e.g. current equivalent of:

```json
{
  "answer": "...",
  "evidence_chunk_ids": ["..."],
  "insufficient_evidence": false
}
```

Prompt rules:

- answer only from supplied context;
- do not use unstated legal/world knowledge;
- cite only supplied chunk IDs;
- if evidence is insufficient, return exact `YETERSİZ KANIT` and `insufficient_evidence=true`;
- no markdown commentary outside the schema.

Freeze model, temperature, max tokens, prompt hash and context formatting before TEST.

## Deterministic grading first

Do not use the same GPT-OSS model as a subjective judge of its own answers for hard pass/fail.

For answerable qrels, a grounded PASS requires all:

1. `insufficient_evidence=false`;
2. cited evidence IDs are a non-empty subset of the actual retrieved context IDs;
3. retrieved/cited evidence covers the qrel's required evidence groups/facts;
4. answer contains/normalizes to the required fact patterns or acceptable forms;
5. no forbidden material claim is present;
6. every material claim used for PASS is supported by cited context.

Items 4–6 should be made as deterministic as practical via normalized required facts/patterns and explicit prohibited claims. An ambiguous semantic case is recorded as `UNRESOLVED` and counts as **non-PASS** in the hard grounded-answer denominator. It is reported for later audit, but the agent must not create a second human checkpoint during Profile B and must never let an LLM self-judge convert ambiguity into PASS.

## NO_ANSWER grading

PASS when:

```text
insufficient_evidence=true
answer normalized exactly to YETERSİZ KANIT
no substantive unsupported answer is appended
no fabricated evidence IDs
```

## Critical anti-guess rule

If retrieval misses required evidence but GPT-OSS happens to know the law and outputs the correct answer, retrieval remains a miss and the final answer is **not grounded PASS**.

## Outputs

Save raw answer records, deterministic grader records and summaries separately. Include per-query links from final report to retrieval evidence, answer evidence and GT entry.


## Final-answer oracle barrier

The answer-generation model receives only allowed retrieved context and normal
answer instructions.

Never provide expected answers, required facts, forbidden claims, gold
evidence IDs or grader rubric to the answer model.

Persist the raw answer first; only then load ground truth for grading.

## Source-linked required facts

The grader must evaluate source-linked `required_facts` from document 33.

A required fact without exact frozen evidence linkage is invalid GT.

Answer normalization must use the frozen scoring-normalization version.
Semantically ambiguous grading remains `UNRESOLVED` and non-PASS; do not add a
post-TEST hidden human judge.
