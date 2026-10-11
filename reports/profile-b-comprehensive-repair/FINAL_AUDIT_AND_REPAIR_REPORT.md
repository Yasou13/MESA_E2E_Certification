# MESA Profile B Kapsamlı Audit ve Repair Raporu

## Yönetici özeti

Repository-wide kaynak→runtime incelemesi tamamlandı. Dört doğrulanmış ölçüm doğruluğu/bütünlük kümesi onarıldı: (1) answer modelinin gizli oracle `fact_id` tahminine bağımlılığı ve fact-ID leakage yüzeyi, (2) boolean/sayısal gate type confusion false-PASS'i, (3) sealed retrieval context'te rank/population/duplicate/render bağlama boşlukları, (4) mutable model tag'lerinin çözülmüş digest olmadan freeze'e girebilmesi. Başlangıçtaki sentetik reproducer seti `10 failed`; onarım sonrası bağımsız clean-export tam suite `567 passed`, skip yoktur.

Kanonik gate eşikleri, qrels, ground truth, normalization contract, frozen historical run, historical verdict ve sealed evidence değiştirilmedi. Official Profile B ve hidden holdout çalıştırılmadı. Bu çalışma yeni bir sertifikasyon sonucu değildir; referans tarihsel sonuç `PROFILE_B_FAIL` olarak değişmez.

Kod düzeyi onarımlar doğrulanmıştır, fakat yeni Profile B run henüz hazır değildir: B4/B6/B7/B8 için meşru runner-owned MESA_Data delivery/restart collector sözleşmeleri ve VM/operator kanıtları repository dışında eksiktir. Bu gate'ler uydurma dosyalarla PASS yapılmamış, `UNVERIFIED` kalacak şekilde korunmuştur.

## Kapsam ve yöntem

- Baseline remote: `https://github.com/Yasou13/MESA_E2E_Certification.git`.
- Baseline SHA: `0a870e0bd94162d48b2b65102da374d30ee54c57`.
- Repair branch: `fix/profile-b-comprehensive-certification-hardening`.
- Source inventory: tüm `harness/`, `config/`, `tests/`, `agent-pack/`, CI, freeze/finalizer/provenance/scoring yolları.
- Döngü: inspect → red synthetic reproduce → causal trace → smallest fix → positive/negative tests → full suite → clean-export verification.
- Read-only historical reconciliation ve external dependency analizi ayrıca yürütüldü.

## Kanonik mimari

`run_profile_b_qualification` frozen scoring/scope/provider authority'yi yükler; trusted MESA ve answer transport'larını kurar; private `OfficialExecutionSession` başlatır. `CertificationTransaction` sıralı olarak bootstrap, freeze, raw execution, raw seal, oracle audit, scoring, gate evaluation ve verdict üretir. Raw ve derived evidence current run/execution identity, SHA sidecar, source lineage ve ephemeral HMAC attestation'a bağlanır. Official scoring yalnız sealed raw manifest ve frozen GT/qrels/identity/normalization/scorer kaynaklarını kullanır. Final PASS, exact B0–B14 registry, bütün hard gate'lerin PASS olması ve official execution verification gerektirir.

Detaylı kaynak/owner/type/eşik haritası `GATE_AUTHORITY_MATRIX.md`, provenance akışı `PROVENANCE_LIFECYCLE.md`, retrieval bağları `RETRIEVAL_CONTEXT_INVARIANTS.md` içindedir.

## Doğrulanmış onarımlar

### PBAR-001 — P0 answer protocol false-FAIL ve oracle bağımlılığı

Eski `AnswerClaim.fact_ids` zorunluluğu ile scorer'ın model-supplied ID üzerinden required fact seçmesi çelişkiliydi: model gizli ID'yi görmemeli, ama doğru claim'in PASS olması için tahmin etmeliydi. Sentetik doğru proposition + doğru visible citation, fact ID olmadan parse edilemedi. Onarım `fact_ids` alanını legacy-read-only opsiyonel yaptı ve matching'i sealed required proposition + explicit pattern + source span üzerinden post-seal gerçekleştirdi. Yanlış fact doğru citation ile halen FAIL; unsupported paraphrase/extra material `UNRESOLVED`; fabricated ID FAIL.

Commit: `5cbb51e`. Oracle provider-boundary ek guardlar: `4fd2e56`, `985089a`.

### PBAR-002 — P0 gate boolean/numeric type confusion

Python'da `bool` bir `int` alt sınıfı olduğu için `True >= 0.8`, `False == 0`, `1 == True` değerlendirmeleri threshold PASS üretebiliyordu. `_comparison_passes` artık boolean contract'ı yalnız exact bool/eq ile, numeric contract'ı bool hariç int/float ile değerlendiriyor.

Commit: `e8b673d`.

### PBAR-003 — P0 sealed context contamination/rank rescue

Doğrudan oluşturulmuş bir `NormalizedRetrievalCapture`, declared `retrieval_limit` üstünde sonuç, rank swap veya duplicate source ID taşıyabildi; builder bunları tekrar doğrulamıyordu. Ayrıca official scorer ID/binding alanlarını doğrulasa da exact model-visible string'i bindings'ten yeniden render etmiyordu. Onarım population≤limit, contiguous rank order, unique source IDs, exact binding key seti ve canonical context re-render eşitliği ekledi. Geçerli ID listesine appended unsealed instruction artık reddedilir.

Commit: `e8b673d`.

### PBAR-004 — P1 immutable provider identity

Kanonik config mutable Magibu `:latest` adını taşıyor ve runtime freeze resolved digest olmadan validation'dan geçebiliyordu. Onarım embedding ve answer authority için non-empty resolved digest'i zorunlu kıldı; aynı Qwen modelini kullanan extraction/answer authority farklı digest verirse reject eder; ayrı extraction modelinde extraction digest zorunludur. LAN IP veya credential hardcode edilmedi.

Commit: `52fee2b`.

### Regression paketi

`tests/test_comprehensive_repair_regressions.py` false-FAIL, wrong-answer false-PASS, oracle leakage, gate type confusion, rank-6 rescue, rank reorder, duplicate identity, context contamination ve missing digest'i kapsar. Commit `fd018dc`. Provider çağrısı öncesi prompt leakage testi `4fd2e56`.

## Tarihsel kanıt uzlaştırması

`RUN-20261009T152914Z-profile-b-fresh` repository `runs/`, tracked reports ve erişilebilir Desktop ağacında bulunamadı. Dolayısıyla `verdict.json`, `gate-results.json`, `retrieval-summary.json` byte/hash karşılaştırması yapılamadı; raporlardaki `8/3/4` ve `6/5/4` ayrımı kaynak byte olmadan açıklanmadı. Statü: `HISTORICAL_EVIDENCE_UNAVAILABLE`.

Bu eksiklik nedeniyle:

- hiçbir TEST trace'i prose'dan yeniden oluşturulmadı;
- bildirilen Recall/MRR/answer oranları yeniden skorlanmadı;
- artifact rewrite/re-serialization iddiası yapılmadı;
- tarihsel `PROFILE_B_FAIL` verdict değişmedi.

B13 ve B14 canlı kanonik config'te sırasıyla resource stability ve evidence integrity'dir; fact-scoring gate değildir.

## B4/B6/B7/B8 dış bağımlılığı

Metric producers gerçek runner-owned derived artifact ister; resmi runner'ın eriştiği canlı API'ler MESA_Data selected-release/corpus inspection, native delivery receipts, controlled restart receipt ve post-restart idempotency count sağlamaz. Bu repository içinde meşru collector yazmak için kaynak authority yoktur. Arbitrary mevcut JSON'u register etmek veya COMMITTED yazmak yasak ve yanlış olurdu.

Owner/action ayrıntısı `PROVENANCE_LIFECYCLE.md` içindedir. Bu bağımlılıklar çözülene kadar yeni official run başlatılmamalıdır.

## Diğer gate ve güvenlik bulguları

- B1 bayt ölçümünü GiB (`1024**3`) olarak kullanıyor; 8/30 eşiği değişmedi. Bu host/VM kapasitesi ölçülmedi.
- B2/B3 provider/model/config parity fail-closed; live Ollama DEV qualification bu hostta yapılmadı.
- B5 H1 exact run/release/selected-version hashlerine bağlı.
- B9 Phase-7 tenant/dataset/agent/principal ve negative probes; synthetic pre-rank proof reddedilir.
- B10 resmi retrieval request frozen question, session/dataset ve Top-5'e bağlı.
- B11 paired ON/OFF, Kùzu path provenance ve stable state proof gerektirir.
- B12 `UNRESOLVED` PASS değildir; correct citation false proposition'ı kurtarmaz.
- B13 pre/post health ve resource telemetry eksikse doğrulanamaz.
- B14 freeze/raw/oracle/scoring/gate hash zinciri mutation'da fail-closed.
- Path confinement, symlink rejection, secret-field/redaction, raw-first provider attempt lineage ve atomic/immutable artifact kontrolleri mevcut adversarial suite ile doğrulandı.

## Test ve verification

- İlk baseline sandbox run: `543 passed, 11 errors`; errorların tamamı localhost socket permission kaynaklı environment block.
- Yetkili final tam run: çalışma ağacında `567 passed in 13.01s`; bağımsız clean export'ta `567 passed in 13.77s`, `0 failed`, `0 errors`, `0 skipped`.
- Optimized self-test: `17/17`.
- Compile, agent-pack checksum, secret scan, tracked JSON/JSONL validation: PASS.
- Locked dependency sync: PASS.
- Lint/type: repository'de ruff/mypy config/dependency yok; `NOT_CONFIGURED`.

Exact komutlar `VERIFICATION_SUMMARY.md` içinde; saldırı eşlemeleri `ATTACK_MATRIX.md` içindedir.

## Değişmeden korunan varlıklar

- `config/profile-b-gates.json` ve tüm B0–B14 eşikleri.
- `uv.lock`.
- `runs/**`, qrels, ground-truth, historical verdicts, sealed evidence.
- Profile B Top-K=5 ve B12 hard-gate politikası.
- Official model adları ve quantization koşulları; yalnız runtime resolved identity zorunluluğu sıkılaştırıldı.

## Readiness ve handoff

Kod repair'i test açısından doğrulanmıştır. Yeni Profile B için readiness: **CONDITIONAL / EXTERNAL DEPENDENCY BLOCKED**.

VM operatörü için talimat:

1. GitHub'dan `fix/profile-b-comprehensive-certification-hardening` dalını fetch et.
2. Handoff'ta bildirilen exact final SHA'yı detached checkout et ve worktree'nin temiz olduğunu doğrula.
3. Locked dependencies, supported Python/runtime, MESA/MESA_Data exact SHAs, provider resolved digests ve deployment parity'yi doğrula.
4. B4/B6/B7/B8 için runner-owned collector API/receipt sözleşmelerini tamamla; RAM/disk ve H1 blockers'ı temizle.
5. Ancak bundan sonra tamamen yeni run ID/storage ile fresh official Profile B çalıştır. Eski run'ı resume/rewrite etme.

Makine verdict'i, push/CI ve clean-export doğrulaması tamamlandıktan sonra final handoff mesajında tek değer olarak verilecektir. Bu rapor hiçbir şekilde official Profile B certification PASS iddiası değildir.
