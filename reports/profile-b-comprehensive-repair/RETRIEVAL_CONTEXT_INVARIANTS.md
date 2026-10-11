# B10 → B12 Retrieval/Context Invariants

## Yetkili akış

1. Frozen authority `top_k=5` ve `answer_context_policy=sealed_retrieval_top_k` yükler (`config/profile-b-gates.json`).
2. Runner her frozen question için tek MESA search çağrısı yapar ve request limitini frozen Top-K'ye eşitler (`harness/qualification_runner.py:970-1012`).
3. `normalize_search_response` request/response session, dataset, rank population, first-class assertion/source kimliği ve scope metadata'yı doğrular (`harness/mesa_adapters.py:299-541`).
4. `build_sealed_retrieval_context` yalnız bu capture'dan deterministic JSON evidence blocks üretir; budget kanıt sınırlarında uygulanır (`harness/mesa_adapters.py:732-853`).
5. Provider capture retrieval hash, allowed IDs, included IDs, bindings ve exact rendered context'i saklar.
6. Official scorer retrieval capture'ı tekrar normalize eder, bindings'i byte-anlamlı biçimde karşılaştırır ve visible context'i bindings'ten yeniden render ederek eşitlik ister (`harness/official_scoring.py:608-670`).

## Onarılan invariants

- `len(results) <= retrieval_limit`; rank-6/8 rescue doğrudan reddedilir.
- ranklar tam `[1..N]` ve list order ile aynı olmalıdır.
- source chunk IDs benzersizdir; alias/duplicate ile context çoğaltılamaz.
- `context_evidence_ids` sırası included bindings ile tam aynıdır.
- Model-visible string included binding'lerden canonical olarak yeniden oluşturulur; geçerli ID listesine unsealed instruction/text eklemek reddedilir.
- Observed binding anahtar seti tam yetkili alanlar + `included/rejection_reason` olmalıdır; misleading metadata kabul edilmez.
- Excluded item yalnız `token_budget` nedeni taşır; sessiz omission yoktur.

## Korunan invariants

- cited IDs ⊆ model-visible IDs ⊆ sealed retrieval allowed IDs.
- retrieval/answer query, session, dataset, MESA SHA ve response hash aynıdır.
- source ID, candidate ID, evidence/assertion ID ve document ID ayrı first-class alanlardır; join tahmin edilmez.
- tenant/agent scope karışımı fail-closed.
- ikinci retrieval, replay/mock veya external citation resmi context'e giremez.

Regresyonlar: `tests/test_b10_b12_context_invariants.py`, `tests/test_comprehensive_repair_regressions.py`, `tests/test_official_scoring_transaction.py`. İlgili commit: `e8b673d`; test commit: `fd018dc`.

