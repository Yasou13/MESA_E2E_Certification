# Profile B Gate Authority Matrix

Bu matris `config/profile-b-gates.json` ile `harness/metric_producers.py` kaynaklarından, başlangıç SHA'sı `0a870e0bd94162d48b2b65102da374d30ee54c57` üzerinde doğrulanmıştır. Eşikler değiştirilmemiştir.

| Gate | Kanonik anlam | Değişmez koşullar/eşik | Üretici ve yetki | Eksik/geçersiz kanıt |
|---|---|---|---|---|
| B0 | Temiz kesin kod tabanları ve yeniden üretilebilir bağımlılıklar | üç depo temiz ve özel dalda; SHA-bağlı CI başarılı; kilitli senkronizasyon başarılı | `_b0`, `baseline-evidence.json`; dondurulmuş üretici kodu | `UNVERIFIED` veya eşik `FAIL` |
| B1 | VM kaynak alt sınırı ve izole depolama | RAM `>= 8 GiB`; disk `>= 30 GiB`; temiz/izole storage | `_b1`, `workspace-baseline.json`, `environment-baseline.json`; bayt ölçümü `1024**3` ile GiB'ye çevrilir | `UNVERIFIED`/`FAIL`; kapasite kodla düşürülemez |
| B2 | Gerçek Ollama Magibu/Qwen sağlayıcı sözleşmesi | 768 boyut, L2; gerçek istek kimlikleri; Qwen completion/extraction; dondurulmuş çözülmüş digest | `_b2`, `provider-canary.json`; freeze runtime identity | `UNVERIFIED`/`FAIL`; fallback yok |
| B3 | Üretim Docker yapılandırma eşliği | intended=container=effective; sağlayıcı/model/dim/language/token koşulları | `_b3`, `runtime-config-parity.json`; kanonik provider contract | `UNVERIFIED`/`FAIL` |
| B4 | MESA_Data ham bütünlük, kanonikleştirme, parse kapsamı | uygun belge `>=50`; hash ve UTF-8/quality kontrolleri | `_b4`, `corpus-integrity.json`; `corpus_integrity` runner attestation | Runner-owned collector yoksa `UNVERIFIED` |
| B5 | Hash-bağlı H1 onayı | H1A/H1B literal kararları seçili sürüm/release hash'lerine bağlı, teslim izni verilmiş | `_b5`, `human-approval.json`; freeze `upstream_authority` hash'i | `UNVERIFIED`/`FAIL` |
| B6 | Native MESA_Data→MESA canary | native `/v4/memory/insert`; bridge yok; COMMITTED; arama eşleşmesi; retry sonrası çoğalma yok | `_b6`, `native-canary.json`; `native_canary` runner attestation | Runner-owned collector yoksa `UNVERIFIED` |
| B7 | Tam native teslim | tüm planlanan chunk'lar benzersiz eşlenmiş; terminal COMMITTED/ALREADY_COMMITTED; teslim edilmeyen `0` | `_b7`, `delivery-evidence.json`; `delivery_evidence` runner attestation | Runner-owned collector yoksa `UNVERIFIED` |
| B8 | Restart kalıcılığı ve idempotent yeniden yayın | gerçek restart gözlemi; before=after; sabit idempotency key; logical count değişmez | `_b8`, `restart-idempotency.json`; `restart_idempotency` runner attestation | Runner-owned collector yoksa `UNVERIFIED` |
| B9 | İzolasyon ve ACL negatifleri | tenant/dataset/agent/time/jurisdiction/repealed kontrolleri; leakage `0` | `_b9`, `scope-isolation.json`; runner-owned Phase 7 capture | MESA sözleşmesi yetersizse `BLOCKED`, aksi hata `UNVERIFIED`/`FAIL` |
| B10 | Frozen TEST retrieval ölçütleri | answerable MRR `>=0.70`; Recall@5 `>=0.80`; single-hop `>=0.90`; relational complete `>=0.70`; tenant leakage `0`; Top-K `5` | `_b10`, resmi scoring summary + scope kanıtı | eksik population/kimlik/hash `UNVERIFIED`/`FAIL` |
| B11 | Gerçek Kùzu kökeni ve nedensel ON/OFF | capability/provenance/paired ablation; katkı sayısı `>=3` | `_b11`, `graph-ablation.json`; runner-owned stable-state proof | runtime state proof yoksa `BLOCKED`; aksi `UNVERIFIED`/`FAIL` |
| B12 | Yalnız bağlamdan yanıt ve abstention | answerable/no-answer pass rate `>=0.80`; fabricated IDs `0`; unsupported claim rate `0` | `_b12`, resmi answer score summary | eksik population veya unresolved cevap PASS sayılmaz |
| B13 | OOM/Killed/katastrofik kaynak hatası yok | catastrophic `0`; OOMKilled `0`; yetkili telemetry var | `_b13`, pre/post health + resource telemetry | eksik/bozuk telemetry `UNVERIFIED`/`FAIL` |
| B14 | Freeze sonrası kanıt bütünlüğü | bütünlük doğrulanmış; mutation `0` | `_b14`, freeze/raw manifest/oracle/score/gate hash zinciri | herhangi bir drift `FAIL`/invalidated |

## Yetki zinciri

Kanonik akış `CertificationTransaction.PHASE_SEQUENCE` içinde `BOOTSTRAP → FREEZE → RAW_EXECUTION → RAW_SEALING → ORACLE_AUDIT → SCORING → GATE_EVALUATION → VERDICT_DERIVATION → EVIDENCE_INDEX → RUN_ID_CONSISTENCY → HEALTH_VERIFICATION → RELEASE_FINALIZATION` sırasındadır (`harness/transaction.py:50-76`). Resmi ağ ve derived artifact kayıtları `OfficialExecutionSession` HMAC-attestation ile bağlanır (`harness/execution_provenance.py:470-594`). Nihai PASS ancak B0–B14'ün tamamı PASS ve resmi execution doğrulanmışsa mümkündür (`harness/verdict.py:152-239`).
