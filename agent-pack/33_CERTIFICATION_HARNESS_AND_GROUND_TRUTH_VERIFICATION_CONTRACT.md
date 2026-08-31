# 33 — Certification Harness and Ground-Truth Verification Contract

## Purpose

This document makes Profile B executable and reduces the remaining risk of a
false PASS or false FAIL caused by the certification harness itself.

It defines:

- mandatory harness bootstrap before real corpus testing,
- harness self-tests and scorer canaries,
- source-only semantic ground-truth verification,
- explicit fact-to-evidence linkage,
- NO_ANSWER corpus-wide negative-evidence verification,
- deterministic scoring normalization,
- ambiguity handling,
- harness/oracle separation,
- required executable artifacts and evidence.

The certification harness is part of the system under audit. It must prove
itself before it is allowed to score MESA.

---

# 1. Mandatory Harness Phase H0

After Bootstrap, Phase -1 and Phase 0, but before provider/data benchmark work,
execute:

```text
Phase H0 — Certification Harness Bootstrap and Self-Test
```

Phase H0 MUST complete before real Profile B corpus results can be accepted.

The agent must implement or verify executable certification logic under the
certification repository.

At minimum the harness must provide these capabilities:

```text
request execution
raw request/response persistence
native identity-map validation
ground-truth structural validation
ground-truth semantic validation
retrieval scoring
REL evidence-group scoring
final-answer grading
NO_ANSWER grading
health snapshot capture
contract/config freeze
evidence indexing
checksum generation/verification
scorer canaries
```

Do not add a new framework when simple code in the repository's existing
toolchain is sufficient.

---

# 2. Harness implementation rule

The written Markdown contract is authoritative for semantics, but PASS requires
executable code.

The agent MUST NOT manually calculate official metrics in a notebook, shell
history, chat response, or ad-hoc one-off command.

Official metrics must be produced by versioned harness code stored in the
certification repository and frozen by Git SHA/hash before official TEST.

If harness code changes after TEST freeze:

```text
current RUN = INVALIDATED_CODE_CHANGE
```

and the run must restart according to the failure/restart contract.

---

# 3. Harness self-test before real data

Before using the harness on MESA_Data/MESA results, run deterministic synthetic
self-tests.

The self-test dataset must not be part of official product metrics.

Required synthetic cases include:

1. direct retrieval hit at rank 1,
2. hit exactly at rank 5,
3. complete miss,
4. duplicate returned evidence IDs,
5. equivalent source/MESA chunk identity mapping,
6. source chunk ID different from MESA public chunk ID,
7. REL query with all evidence groups,
8. REL query missing exactly one evidence group,
9. malformed provenance,
10. infrastructure error distinct from retrieval MISS,
11. NO_ANSWER correct abstention,
12. NO_ANSWER hallucinated answer,
13. correct answer with fabricated evidence ID,
14. correct wording but unsupported evidence,
15. Unicode/Turkish normalization fixtures,
16. intentionally wrong qrel expected to fail,
17. intentionally wrong answer expected to fail.

Write:

```text
runs/<RUN_ID>/harness-self-test.json
```

All mandatory harness self-tests must PASS before official scoring.

---

# 4. Ground truth must be source-derived, not model-derived

Ground truth must be constructed from the frozen authoritative source corpus.

Do not derive official qrels/answers from:

- MESA retrieval output,
- MESA graph output,
- MESA extraction output,
- GPT-OSS answer output,
- another LLM's guess,
- repository benchmark output.

LLMs may assist formatting only when the resulting content is independently
verified against exact source evidence before freeze.

The source remains authoritative.

---

# 5. Explicit fact-to-evidence linkage

Every answerable TEST/DEV item must link every required fact to exact source
evidence.

Preferred schema:

```json
{
  "query_id": "Q-001",
  "class": "SINGLE_DIRECT",
  "question": "...",
  "required_facts": [
    {
      "fact_id": "F1",
      "claim": "...",
      "supported_by": [
        {
          "source_chunk_id": "SRC-...",
          "span_id": "SPAN-...",
          "exact_text": "..."
        }
      ]
    }
  ],
  "expected_source_chunk_ids": ["SRC-..."],
  "acceptable_answer_patterns": ["..."],
  "forbidden_claims": []
}
```

For each `required_fact`:

- `claim` must be entailed by the cited exact source span,
- the exact span must exist byte/text-consistently in the approved canonical
  source,
- the fact must not rely on an unstated legal inference unless the query class
  explicitly tests a documented relation and all required evidence groups are
  present.

A free-floating `required_fact` with no exact evidence link is invalid.

---

# 6. Semantic ground-truth verification

Structural validity is not enough.

Before GT freeze, every TEST/DEV item must pass semantic verification:

```text
question
  ↓
exact source evidence
  ↓
required facts
  ↓
expected answer semantics
```

The verifier must establish that:

- the question is answerable from the cited frozen evidence,
- each required fact is supported by exact evidence,
- the expected answer does not contain facts absent from the evidence,
- the question is not materially ambiguous,
- the evidence does not support two incompatible expected answers,
- cited article/document/version is the intended one,
- temporal wording matches the source version/time,
- relational questions contain all evidence groups needed for the relation.

If this cannot be proven, mark the candidate:

```text
GT_AMBIGUOUS
```

and exclude it before TEST freeze.

Do not repair ambiguity after seeing MESA results.

---

# 7. Deterministic replacement policy

If a candidate TEST item fails semantic GT verification:

1. record the rejection reason,
2. remove it before GT freeze,
3. select a replacement only from the predeclared candidate pool,
4. use deterministic ordering/seed,
5. validate the replacement from source,
6. preserve the required TEST class distribution.

Do not select a replacement because MESA performs better on it.

Once TEST is frozen, query replacement is forbidden for that RUN.

---

# 8. REL evidence groups

For `RELATIONAL` questions, qrels must explicitly encode evidence groups.

Example:

```json
{
  "evidence_groups": [
    {
      "group_id": "G1",
      "acceptable_source_chunk_ids": ["SRC-A", "SRC-A2"]
    },
    {
      "group_id": "G2",
      "acceptable_source_chunk_ids": ["SRC-B"]
    }
  ]
}
```

A REL complete-evidence hit requires all required groups according to the frozen
scoring contract.

Do not count one chunk that merely contains the answer wording if the intended
question requires multiple independently sourced relation steps.

---

# 9. NO_ANSWER negative-evidence audit

`NO_ANSWER` is valid only if the frozen corpus does not contain sufficient
evidence to answer the question under the benchmark rules.

Before freeze, run a source-side negative-evidence audit over the entire frozen
corpus.

The audit must not use MESA retrieval as the authority.

At minimum:

- search exact important terms,
- search normalized legal identifiers,
- inspect likely related documents/articles,
- check aliases/synonyms defined by the dataset,
- verify no approved source chunk or valid evidence-group combination answers
  the question.

Write a safe audit artifact such as:

```text
ground-truth/no-answer-audit.jsonl
```

Each NO_ANSWER item should record:

```text
query_id
audit_method
candidate_matches_reviewed
answerable=false
review_notes
```

If corpus-wide unanswerability cannot be established, mark the item ambiguous
and replace it before freeze.

---

# 10. Canonical scoring normalization

The harness MUST use one versioned deterministic normalization specification.

Write/freeze:

```text
config/scoring-normalization.json
```

and record:

```text
normalization_version
```

in the contract freeze.

The default canonical normalization is conservative:

## Text normalization

- Unicode NFC,
- normalize CRLF/CR to LF,
- trim leading/trailing whitespace,
- collapse runs of horizontal whitespace where comparison semantics permit,
- do not remove words,
- do not stem/lemmatize,
- do not translate,
- do not perform semantic paraphrase matching unless explicitly defined by an
  acceptable pattern.

## Turkish text

Do not use naive English-only lowercasing as legal-answer authority.

If case-insensitive matching is required, use an explicitly implemented and
unit-tested Turkish-aware/casefold strategy and freeze its version.

## Legal identifiers

Normalize only well-defined syntactic equivalents, for example when explicitly
implemented/tested:

```text
4857
4857 sayılı Kanun
Kanun No: 4857
```

may map to a canonical law-number token for a field whose semantics are a law
number.

Do not apply this transformation to arbitrary prose.

## Article identifiers

Explicitly supported forms such as:

```text
Madde 14
m. 14
14. madde
```

may map to a canonical article identifier only in article-identifier fields or
patterns.

## Dates/numbers

Normalize dates/numbers only when the transformation is unambiguous and covered
by unit tests.

Never let normalization invent legal equivalence.

---

# 11. Answer grading contract

Final-answer grading should be deterministic whenever possible.

For each answer:

1. persist raw answer,
2. persist cited evidence IDs,
3. apply the frozen normalization version,
4. validate evidence IDs,
5. evaluate `required_facts`,
6. evaluate `forbidden_claims`,
7. evaluate acceptable patterns,
8. evaluate insufficient-evidence behavior.

A correct-looking answer with unsupported/fabricated evidence is not grounded
PASS.

A semantically uncertain case is:

```text
UNRESOLVED
```

and counts as non-PASS under hard grounded-answer gates.

Do not create a hidden second human gate after TEST.

---

# 12. Identity-map validation before scoring

Before official retrieval scoring:

- validate every identity-map row structurally,
- reject duplicate/conflicting source mappings,
- verify mapped MESA identifiers exist in native publish/commit evidence,
- verify the mapping was frozen before TEST,
- verify no mapping was inferred from TEST retrieval results.

Write:

```text
runs/<RUN_ID>/identity-map-validation.json
```

Official scorer must use only the validated frozen mapping.

---

# 13. Oracle separation in executable code

The harness should separate execution artifacts from scoring artifacts.

Preferred layout:

```text
runs/<RUN_ID>/raw/
runs/<RUN_ID>/scored/
ground-truth/
```

The request executor must not require expected answers/qrels to construct the
MESA request.

A practical verification must inspect the serialized TEST request objects and
confirm they contain no:

```text
expected answer
required facts
gold chunk IDs
gold document IDs
qrel labels
PASS/FAIL labels
```

Write:

```text
runs/<RUN_ID>/oracle-leakage-audit.json
```

Any oracle leakage invalidates the RUN.

---

# 14. Required harness tests

The certification repository must contain automated tests for at least:

- Recall@1,
- Recall@5,
- MRR,
- REL group completeness,
- multiple acceptable evidence IDs,
- identity-map normalization,
- duplicate result handling,
- malformed provenance,
- infra-error classification,
- NO_ANSWER scoring,
- fabricated evidence rejection,
- required fact grading,
- forbidden claim grading,
- normalization behavior,
- Turkish Unicode/case behavior used by the grader,
- freeze mutation detection,
- oracle leakage guard.

Run these tests before official TEST and after any harness change.

---

# 15. Harness readiness evidence

Before real TEST, produce:

```text
runs/<RUN_ID>/harness-readiness.json
```

It must contain at least:

```json
{
  "harness_tests_pass": true,
  "scorer_canaries_pass": true,
  "gt_structural_validation_pass": true,
  "gt_semantic_validation_pass": true,
  "no_answer_audit_pass": true,
  "identity_map_validation_pass": true,
  "normalization_frozen": true,
  "oracle_leakage_audit_pass": true,
  "official_test_allowed": true
}
```

If any required field is false, official TEST must not start.

---

# 16. Required executable/output artifacts

Before official TEST, the repository/run must contain working equivalents of:

```text
harness request executor
harness retrieval scorer
harness final-answer grader
harness GT validator
harness identity-map validator
harness health/freeze/evidence utilities
automated harness tests
config/scoring-normalization.json
ground-truth/no-answer-audit.jsonl
runs/<RUN_ID>/harness-self-test.json
runs/<RUN_ID>/harness-readiness.json
runs/<RUN_ID>/identity-map-validation.json
runs/<RUN_ID>/oracle-leakage-audit.json
```

Exact filenames for executable source modules may follow the repository's
current implementation, but capabilities and evidence are mandatory.

---

# 17. Harness bug policy

If the harness itself is wrong:

1. preserve raw product responses,
2. reproduce the harness bug with a synthetic unit test,
3. fix the smallest correct harness code,
4. run all harness tests/canaries,
5. commit the fix,
6. invalidate the active frozen RUN,
7. create a new RUN_ID,
8. refreeze and rerun official TEST from the beginning.

Never silently rescore a frozen official RUN with changed scorer semantics and
keep the old verdict.

---

# 18. PASS conditions

Phase H0 / harness integrity PASS requires all of:

- executable harness exists,
- automated harness tests pass,
- synthetic harness self-test passes,
- scorer canaries pass,
- GT structural validation passes,
- GT semantic validation passes,
- every required fact links to exact source evidence,
- ambiguous GT items are removed before freeze,
- NO_ANSWER corpus-wide negative-evidence audit passes,
- identity map validates,
- normalization spec is versioned/frozen,
- oracle leakage audit passes,
- official harness/config hashes are frozen.

Failure of any item blocks official TEST.

## Harness resource discipline

The executable harness must integrate document 34 resource telemetry without
loading large evidence/corpus objects unnecessarily into RAM.

Prefer streaming JSONL evidence and bounded batches.

Harness self-tests must prove that a synthetic CRITICAL pressure signal prevents
new heavy scheduling without falsely marking product gates PASS.

## Harness execution efficiency

The harness must support document 35 efficiency rules:

- stream raw evidence,
- use bounded batches,
- avoid loading the full corpus/log set into agent context,
- avoid duplicate provider/test execution,
- expose stable machine-readable phase summaries,
- support resume from persisted checkpoint/evidence without resubmitting
  already completed official TEST operations in the same valid RUN.

No cache may expose GT/oracle data to request construction.
