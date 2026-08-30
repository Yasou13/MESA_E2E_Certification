# datasets/

This directory describes the Profile B legal corpus and may contain small tracked manifests. Large mutable runtime data belongs under `datasets/runtime/<RUN_ID>/` and should remain ignored unless explicitly promoted as a stable fixture.

## Source principles

- Prefer official Turkish legal sources.
- Preserve immutable raw bytes and SHA-256.
- Canonical text must remain traceable to raw source.
- Silent decoding loss is forbidden.
- MESA_Data quality/review/release workflow remains authoritative for data preparation.
- Corpus membership must be fixed before TEST ground-truth freeze.

## Target

- target: about 60 legal documents;
- hard minimum: 50 accepted documents;
- enough diversity to support direct, paraphrase, relational, and no-answer queries.

Do not select documents based on which ones MESA retrieves well.

See `../agent-pack/10_CORPUS_DESIGN.md`.

