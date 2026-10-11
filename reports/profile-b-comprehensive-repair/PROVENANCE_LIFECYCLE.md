# B4/B6/B7/B8 Provenance Lifecycle

## Doğrulanan mevcut davranış

`_require_official_runner_owned` resmi modda active `OfficialExecutionSession.verify_derived_artifact` doğrulaması olmadan B4/B6/B7/B8 kanıtını kabul etmez (`harness/metric_producers.py:346-361`). `register_derived_artifact` current execution ID, run ID, sealed sidecar, registered raw kaynakları ve HMAC attestation ister (`harness/execution_provenance.py:469-513`). Yanlış RUN_ID, forged producer, mutated bytes, stale artifact ve uydurma COMMITTED dosyası bu nedenle fail-closed olur.

## Üretici haritası

| Gate | Beklenen artifact/type | Kanıtlaması gereken gerçek olay | Mevcut durum |
|---|---|---|---|
| B4 | `corpus-integrity.json` / `corpus_integrity` | onaylı seçili corpus raw+canonical hash, encoding, quality ve count | `EXTERNAL_DEPENDENCY` |
| B6 | `native-canary.json` / `native_canary` | MESA_Data publisher üzerinden native insert/search/retry; bridge yok | `EXTERNAL_DEPENDENCY` |
| B7 | `delivery-evidence.json` / `delivery_evidence` | selected release'teki her source chunk'ın mutation ve MESA chunk eşlemesi, terminal state | `EXTERNAL_DEPENDENCY` |
| B8 | `restart-idempotency.json` / `restart_idempotency` | gerçek runtime restart öncesi/sonrası proof ve idempotent republish | `EXTERNAL_DEPENDENCY` |

## Neden bu repoda collector eklenmedi

`run_profile_b_qualification` native MESA search/session, Phase 7 scope ve graph ablation yürütür; fakat MESA_Data seçili-release enumerasyonu, publish receipt stream'i, kontrollü MESA restart komutu ve post-restart logical-count API'si bu repository'nin güvenilir girişleri değildir (`harness/qualification_runner.py:835-1115`). Mevcut bir JSON dosyasını yalnız register etmek gerçek olayı kanıtlamaz ve prompt'un açık yasağını ihlal ederdi.

Gerekli dış sözleşmeler:

1. **MESA_Data sahibi:** hash-bound selected release'i enumerate eden ve canonical/raw hashleri döndüren read-only manifest API/CLI.
2. **MESA_Data + MESA sahipleri:** stable delivery identity/idempotency key ile native publish receipts; source_chunk→MESA chunk/mutation mapping ve terminal-state sorgusu.
3. **VM operatörü/MESA sahibi:** yetkili kontrollü restart receipt'i (önceki process/container identity, yeni identity, timestamps) ve aynı store üzerinde read-only persistence probe.
4. **MESA sahibi:** dataset scoped logical-count/idempotency lookup; duplicate/loss ölçümü.

Bu arayüzler freeze'de kimliklendirilip exact raw exchanges olarak runner tarafından capture edilene kadar B4/B6/B7/B8 `UNVERIFIED` kalmalıdır. Bu, sonuç manipülasyonu değil güvenli blokajdır.

Mevcut adversarial testler: `tests/test_b4_b8_attack_matrix.py`, `tests/test_metric_producers.py`, `tests/test_trust_root_closure.py`. False session, mutated bytes, stale/wrong RUN_ID, missing producer ve forged provenance PASS olamaz.

