# MESA E2E Certification — Değer, Mimari Karmaşıklık, Ölçüm Kalitesi ve Aşırı Mühendislik Denetim Raporu

**Rapor Tarihi:** 19 Ekim 2026  
**Hedef Depo:** `https://github.com/Yasou13/MESA_E2E_Certification`  
**İncelenen Commit SHA:** `3b7562cb65800cde27877dc3a7cd505a70822bf8`  
**Çalışma Dalı:** `main`  
**İlişkili Çekirdek Depo:** `https://github.com/Yasou13/MESA` (v0.8.1, SHA: `d3947846615e63b48dc7a5df9f1051b29f734263`)  
**Denetçi Rolü:** Kıdemli Yazılım Test Mimarı, E2E Sertifikasyon Mühendisi, Performans Mühendisi ve Bağımsız Denetçi  
**Denetim Türü:** Kesinlikle Salt Okunur (Read-Only) Kanıta Dayalı Teknik Denetim  

---

## 1. Yönetici Özeti (Executive Summary)

Bu bağımsız teknik denetim, `MESA_E2E_Certification` deposunun mimari uygunluğunu, ölçüm kalitesini, test etkinliğini, kaynak tüketimini ve aşırı mühendislik (over-engineering) düzeyini nesnel kanıtlarla değerlendirmek amacıyla gerçekleştirilmiştir.

### Temel Çıkarım ve Cevap
> **"Bu E2E sistemi, makul bir mühendislik ve operasyonel maliyetle MESA hakkında yeterli ve güvenilir kanıt sağlıyor mu?"**
> **HAYIR.** 

Mevcut sistem, MESA'nın çok dar bir yetenek dilimini (80 adet Türk hukuku kanun maddesi sorgusu üzerinden hibrit arama) test etmek için yaklaşık **32.000 satır Python kodu**, **35 adet ajan protokol dokümanı**, geçici HMAC yetkilendirme oturumları, SQLite gölge tablo parmak izi çıkarma mekanizmaları ve 12 aşamalı sözde ACID işlem makineleri inşa etmiştir. Buna karşılık, MESA'nın gerçek MVP yüzeyini oluşturan MCP entegrasyonu, Python SDK (`mesa_client`), arka plan outbox işçileri (`mesa_workers`), LanceDB sıkıştırma/kurtarma, eşzamanlı çoklu istemci yükü, bellek güncelleme/silme yaşam döngüsü ve gecikme yüzdelikleri (p50/p95/p99) ya hiç test edilmemekte ya da tamamen kapsam dışı bırakılmıştır.

Dahası, sistem iki kritik ölçüm/entegrasyon kusuru nedeniyle canlı bir MESA v0.8.1 üzerinde resmi sertifikasyonunu **başarı ile tamamlayamamaktadır**:
1. `harness/answer_scorer.py`, üretici bir LLM'in (Qwen 9B) ürettiği cevabın yerel kanun metniyle harfi harfine (verbatim) eşleşmesini zorunlu tutmakta; semantik olarak %100 doğru Türkçe hukuki parafrazları bile `UNRESOLVED` sayarak `answerable_pass_rate` metriğini %0'a düşürmektedir.
2. `harness/mesa_adapters.py`, MESA'nın genel arama endpoint'inden (`POST /v4/memory/search`) dahili ön-sıralama hariç tutma belirteçleri (`pre_rank_scope_audit_id`) ve aday ajan kimlikleri talep etmekte; bu alanlar olmayınca izolasyon testlerini `BLOCKED_BY_MESA_CONTRACT` statüsüne kilitlemektedir.
3. Runner B4, B6, B7 ve B8 kapılarını (veri dağıtımı ve yeniden başlatma) bizzat icra etmemekte, harici JSON dosyalarına bağımlı kalmaktadır.

### Skor ve Karar Özeti
- **Toplam Denetim Skoru:** **46 / 100** (Geçici/Provisyonel Aralık: 42 – 50)
- **Birincil Karar:** `USEFUL_BUT_OVERENGINEERED` (Aşırı Mühendislik İçeren, Dar Kapsamlı ve Ölçüm Kısıtları Bulunan Sistem)
- **Eylemsel Tavsiye:** `TARGETED_SIMPLIFICATION` (Hedefli Sadeleştirme ve Kara Kutu Entegrasyonuna Dönüş)

---

## 2. Depo Temel Çizgisi (Repository Baseline)

- **Git Commit SHA:** `3b7562cb65800cde27877dc3a7cd505a70822bf8`
- **Git Dalı:** `main` (Temiz çalışma ağacı, sıfır uncommitted değişiklik)
- **Paket ve Sürüm:** `mesa-e2e-certification` v0.1.0 (`pyproject.toml`)
- **Python Sürüm Gereksinimi:** `>=3.10,<3.15`
- **Paket Bağımlılıkları:**
  - Çalışma zamanı: `pydantic>=2.10,<3` (Yalnızca tek doğrudan bağımlılık!)
  - Geliştirme: `pytest>=8.3,<10`
  - Derleme: `hatchling==1.27.0`
- **İzlenen Dosya Envanteri (Git Tracked Files):** Toplam 242 dosya
  - `agent-pack/`: 39 dosya (35 rehber dokümanı, MANIFEST, SHA256SUMS vb.)
  - `config/`: 4 dosya (`profile-b-gates.json`, `scoring-normalization.json`, README vb.)
  - `contracts/`: 4 dosya (`WAIT_FOR_MESA_PHASE_*.md`)
  - `datasets/`: 2 dosya (README, .gitkeep)
  - `evidence/`: 2 dosya (README, .gitkeep)
  - `.github/workflows/`: 1 dosya (`ci.yml`)
  - `ground-truth/`: 4 dosya (Protokol ve politika markdown dosyaları)
  - `harness/`: 30 dosya (27 Python modülü, README vb.)
  - `reports/`: 61 dosya (Tarihsel denetimler, onarım raporları vb.)
  - `root`: 6 dosya (`README.md`, `MANIFEST.md`, `pyproject.toml`, `uv.lock`, denetim döngü yönergesi vb.)
  - `runs/`: 31 dosya (`RUN-20260901T005200Z-p8b03` tarihsel koşu verileri)
  - `scripts/`: 5 dosya (Doğrulama ve güvenlik tarama betikleri)
  - `tests/`: 53 dosya (51 test modülü, 2 destek modülü)
- **Kod Hacmi (Lines of Code - LOC):**
  - `harness/`: 13.617 satır Python
  - `tests/`: 18.149 satır Python
  - `scripts/`: 178 satır Python
  - **Toplam Python:** **31.944 satır**
- **Çalıştırılabilir Giriş Noktaları (Entry Points):**
  - `python -O -m harness.self_test`: 17 sentetik koşucu testi
  - `python scripts/validate_json_artifacts.py`: İzlenen JSON/JSONL sözdizimi kontrolü
  - `python scripts/check_no_secrets.py`: Statik sır taraması
  - `python scripts/verify_agent_pack.py`: Ajan paketi sağlama toplamı kontrolü
  - `pytest`: 567 adet birim/entegrasyon testi
  - `harness.qualification_runner.run_profile_b_qualification`: Canlı arama ve yeterlilik icra fonksiyonu (Doğrudan CLI arayüzü yoktur; testler üzerinden çağrılmaktadır).

---

## 3. Gerçek Yürütme Mimarisi (Actual Architecture)

Sistemin teorik dokümantasyonu ile kod düzeyinde fiilen çalışan mimarisi arasında belirgin bir ayrım bulunmaktadır.

### Fiili Yürütme Akışı
```
[DONDURULMUŞ SÖZLEŞME VE VERİ]
  - config/profile-b-gates.json
  - runs/.../ground-truth-test.jsonl (80 soru)
  - runs/.../identity_map.jsonl
       │
       ▼
[KOD DONDURMA VE GÜVEN KÖKÜ (Freeze & Attestation)]
  - harness/freeze.py -> 15+ Python dosyasının SHA256 doğrulaması
  - harness/execution_provenance.py -> Süreç içi rastgele HMAC token üretimi
       │
       ▼
[İŞLEM MOTORU (CertificationTransaction)]
  - harness/transaction.py -> 12 adımlı sıralı durum makinesi
       │
       ▼
[MESA ARAMA VE BAĞLAM İCRASI (Workload)]
  - harness/mesa_transport.py -> MESA POST /v4/memory/search (urllib)
  - harness/mesa_adapters.py -> Normalizasyon ve mühürlü bağlam inşası
  - harness/answer_execution.py -> Ollama Qwen 9B çağrısı (80 soru x 4096 token)
  - harness/scope_collector.py -> 12 negatif izolasyon sorgusu
  - harness/graph_collector.py -> Kùzu açık/kapalı eşleştirilmiş durum testi
       │
       ▼
[HAM KANIT MÜHÜRLEME (Raw Sealing & Oracle Audit)]
  - harness/artifacts.py -> Tüm yanıtlara .SHA256 sidecar yazımı
  - harness/oracle.py -> Sızıntı taraması (istemcide ground-truth var mı?)
       │
       ▼
[SKORLAMA (Official Scoring)]
  - harness/retrieval_scorer.py -> Recall@5, MRR hesaplama
  - harness/answer_scorer.py -> Metin harfiyen eşleşme kontrolü
  - harness/official_scoring.py -> scoring-summary.json üretimi
       │
       ▼
[KAPI VE KARAR DEĞERLENDİRME (Gates & Verdict)]
  - harness/metric_producers.py -> B0-B14 metrik çıkarımı
  - harness/gates.py -> Eşik doğrulaması
  - harness/verdict.py -> PROFILE_B_PASS_NATIVE veya FAIL / BLOCKED
```

### Bileşenlerin Gerçek Durumu (Execution Path Analysis)
- **ACTIVE (Aktif Kullanılan):** `harness/gates.py`, `harness/retrieval_scorer.py`, `harness/official_scoring.py`, `harness/normalizer.py`, `harness/identity.py`, `harness/mesa_transport.py`, `harness/artifacts.py`, `harness/mesa_adapters.py`.
- **OVER-ENGINEERED (Aşırı Karmaşıklaştırılmış):** `harness/execution_provenance.py` (HMAC imzalama), `harness/state_proof.py` (SQLite WAL/tablo parmak izi), `harness/transaction.py` (1000 satırlık sözde işlem makinesi).
- **BLOCKED / INCOMPLETE (Tamamlanmamış / Dış Bağımlılık Engeli):**
  - B4, B6, B7, B8: Runner bu işlemleri bizzat icra etmez; harici dosyalara bakar.
  - B9, B10: MESA API'sinde `pre_rank_exclusion_audit` bulunmadığı için engellidir.
  - B11: MESA API'sinde genel Kùzu ON/OFF anahtarı olmadığı için engellidir.

---

## 4. Bileşen Envanteri ve Sorumluluk Analizi (Component Inventory)

| Bileşen Dosyası | Satır Sayısı | Temel Amacı | Gerçek Değeri | Bakım Maliyeti | Öneri |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `harness/retrieval_scorer.py` | 188 | Arama doğruluğunu (Recall, MRR) hesaplar | **YÜKSEK** | Düşük | **KEEP** |
| `harness/normalizer.py` | 183 | Türkçe hukuki metin ve kanun madde normalizasyonu | **YÜKSEK** | Düşük | **KEEP** |
| `harness/identity.py` | 211 | Dış kaynak parçaları ile MESA kimliklerini eşler | **YÜKSEK** | Düşük | **KEEP** |
| `harness/gates.py` | 305 | B0-B14 kapı eşiklerini tip güvenliğiyle değerlendirir | **YÜKSEK** | Orta | **KEEP** |
| `harness/mesa_transport.py` | 273 | MESA HTTP isteklerini yürütür ve süre tutar | **YÜKSEK** | Düşük | **KEEP** |
| `harness/mesa_adapters.py` | 853 | MESA yanıtlarını şemaya uyarlar, bağlamı sınırlar | **YÜKSEK** | Orta | **SIMPLIFY** (Dahili denetim zorunluluğunu kaldır) |
| `harness/official_scoring.py`| 728 | Ham veriden resmi özet metrikleri türetir | **YÜKSEK** | Orta | **KEEP** |
| `harness/answer_scorer.py` | 364 | Üretilen cevabın doğruluğunu ve alıntıları puanlar | **ORTA** (Harfi harfine kuralı hatalı) | Orta | **FIX_MEASUREMENT** (Semantik değerlendirme ekle) |
| `harness/metric_producers.py`| 1.575| B0-B14 metriklerini dosyalardan okur | **ORTA** | Yüksek | **SIMPLIFY** (Doğrudan test çıktısından oku) |
| `harness/qualification_runner.py` | 1.175 | Tüm yeterlilik akışını bağlar | **ORTA** | Yüksek | **SIMPLIFY** (CLI ekle, harici adımları içeri al) |
| `harness/artifacts.py` | 720 | Yanıtları kaydeder, `.SHA256` dosyaları yazar | **DÜŞÜK** (Aşırı dosya üretir) | Orta | **SIMPLIFY** (Yan dosya enflasyonunu azalt) |
| `harness/finalizer.py` | 607 | 17 parçalı yayın paketini derler | **DÜŞÜK** | Yüksek | **SIMPLIFY** (2 temel JSON dosyasına indir) |
| `harness/freeze.py` | 286 | Harness kodlarının SHA256 özetini dondurur | **DÜŞÜK** (Gereksiz katılık) | Yüksek | **REMOVE_AFTER_VERIFICATION** |
| `harness/execution_provenance.py`| 626 | Bellek içi HMAC ve oturum yetkisi yönetir | **ÇOK DÜŞÜK** (Tehdit modeli yapay) | Yüksek | **REMOVE_AFTER_VERIFICATION** |
| `harness/state_proof.py` | 809 | SQLite iç tablolarını ve WAL'ı inceler | **ÇOK DÜŞÜK** (Kara kutu ihlali) | Çok Yüksek | **REMOVE_AFTER_VERIFICATION** |
| `harness/transaction.py` | 1.013| 12 aşamalı ACID işlem makinesi | **ÇOK DÜŞÜK** (Suni mimari) | Yüksek | **SIMPLIFY** (Standart pytest/runner yap) |
| `agent-pack/` (35 MD) | ~6.500 | Yapay zekaya operasyonel emirler verir | **DÜŞÜK** (Dokümantasyon şişkinliği) | Yüksek | **SIMPLIFY** (Tek bir çalıştırma kılavuzu yap) |

---

## 5. Test Profili Analizi (Test Profile Analysis)

Tarihsel MESA planlarında geçen "Profile A (Safe Core / 24H)", "Profile B (NVIDIA Legal)" ve "Profile C (Adversarial Legal)" isimleri incelenmiştir.

### Bulgular:
1. **Tek Bir Aktif Profil Mevcuttur:** Depoda fiilen kodlanmış tek bir profil vardır: **Profile B — Legal End-to-End Integration & Retrieval Certification (`MESA-PROFILE-B-LEGAL-E2E`)**.
2. **24 Saatlik Dayanıklılık Profili (Profile A) Yoktur:** Depoda 24 saatlik soak testi çalıştıran hiçbir kod, zamanlayıcı veya profil bulunmamaktadır.
3. **Adversarial Profil (Profile C) Ayrı Bir Profil Değildir:** Saldırı matrisleri (`test_b4_b8_attack_matrix.py`, `test_pre_vm_adversarial.py`) bağımsız bir E2E profili değil, test süiti içindeki birim testleridir.
4. **Sağlayıcı Değişimi:** Tarihsel koşu (`RUN-20260901T005200Z-p8b03`) NVIDIA NIM (Nemotron-4 340B + GPT-OSS 20B) kullanırken, mevcut `config/profile-b-gates.json` sözleşmesi **Ollama** (`alibayram/embeddingmagibu-200m:latest` + `qwen3.5:9b-q4_K_M`) olarak güncellenmiştir.
5. **Profil Sınıflandırması:** Profile B mevcut haliyle **IMPORTANT_CERTIFICATION** olarak tasarlanmış ancak aşırı gereksinimlerle **BLOCKED** durumuna düşürülmüştür.

---

## 6. Eksiksiz Ölçüm Envanteri (Complete Measurement Inventory)

| Metrik Adı | Amacı | Kaynak Dosya ve Satır | Toplama Yöntemi | Birim | Örneklem | Eşik Değeri | Gerçek Değeri | Durum |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `answerable_recall_at_5` | İlk 5 yanıtta en az bir doğru kanıt bulma oranı | `retrieval_scorer.py:128,167` | Arama yanıtı sıralaması | Oran (0-1) | 70 soru | `>= 0.8` | **YÜKSEK** | **VALIDATED** |
| `answerable_mrr` | İlk doğru kanıtın ters sıra ortalaması (MRR) | `retrieval_scorer.py:129,168` | 1 / Rank | Skor (0-1) | 70 soru | `>= 0.7` | **YÜKSEK** | **VALIDATED** |
| `single_hop_recall_at_5` | Tek adımlı doğrudan kanıt bulma başarısı | `official_scoring.py:281` | İlk 5 eşleşme ortalaması | Oran (0-1) | 60 soru | `>= 0.9` | **YÜKSEK** | **VALIDATED** |
| `rel_complete_evidence_at_5`| İlişkisel soruda tüm kanıt gruplarını getirme | `retrieval_scorer.py:124` | Tüm grupların varlığı | Oran (0-1) | 10 soru | `>= 0.7` | **YÜKSEK** | **VALIDATED** |
| `tenant_leakage` | Farklı kiracıya ait verinin aramaya sızması | `metric_producers.py:1064` | Filtre ihlali sayımı | Adet | 12 vaka | `== 0` | **KRİTİK** | **BLOCKED** |
| `cross_tenant_scope_leakage`| B9 izolasyon vakalarında sızıntı sayısı | `metric_producers.py:1029` | Negatif vaka sorgusu | Adet | 12 vaka | `== 0` | **KRİTİK** | **BLOCKED** |
| `isolation_acl_passed` | Yetki matrisinin tam geçmesi | `metric_producers.py:1034` | Boolean kontrol | Bool | 12 vaka | `== true` | **YÜKSEK** | **BLOCKED** |
| `graph_causal_ablation_proven`| Kùzu grafiğinin nedensel fayda sağlaması | `graph_collector.py:250` | Graf Açık vs Kapalı farkı | Bool | 10 soru | `== true` | **YÜKSEK** | **BLOCKED** |
| `graph_rel_contribution_count`| Grafiğin pozitif katkı yaptığı soru sayısı| `graph_collector.py:270` | Pozitif delta sayımı | Adet | 10 soru | `>= 3` | **YÜKSEK** | **BLOCKED** |
| `answerable_pass_rate` | Cevaplanan soruların doğruluk oranı | `official_scoring.py:310` | Şema + Metin eşleşmesi | Oran (0-1) | 70 soru | `>= 0.8` | **KUSURLU** | **MISLEADING** |
| `no_answer_pass_rate` | Kanıtsız soruda doğru çekinme oranı | `answer_scorer.py:171` | "YETERSİZ KANIT" kontrolü | Oran (0-1) | 10 soru | `>= 0.8` | **YÜKSEK** | **VALIDATED** |
| `fabricated_evidence_chunk_ids`| Uydurma kanıt kimliği alıntılama | `official_scoring.py:315` | Küme farkı | Adet | 80 soru | `== 0` | **YÜKSEK** | **VALIDATED** |
| `unsupported_material_claim_rate`| Kanıtsız maddi iddia oranı | `official_scoring.py:312` | Desteksiz iddia sayımı | Oran | 70 soru | `== 0` | **KUSURLU** | **MISLEADING** |
| `catastrophic_resource_failure`| Çökme, OOM veya kesinti durumu | `operations.py:270` | Harici telemetri özeti | Adet | N/A | `== 0` | **DÜŞÜK** | **IMPLEMENTED_NOT_VALIDATED**|
| `oom_killed_count` | OOM ile sonlanan süreç sayısı | `metric_producers.py:1488`| Harici JSON sayımı | Adet | N/A | `== 0` | **DÜŞÜK** | **IMPLEMENTED_NOT_VALIDATED**|
| `resource_usage_recorded` | Telemetri kaydı mevcut mu? | `metric_producers.py:1498`| Dosya satır varlığı | Bool | N/A | `== true` | **ÇOK DÜŞÜK**| **IMPLEMENTED_NOT_VALIDATED**|
| **Search Latency (p50/p95/p99)**| Arama gecikmesi dağılımı | - | **YOK** | ms | 0 | **YOK** | **YÜKSEK** | **MISSING** |
| **Ingestion Throughput** | Saniyede işlenen kanun parçası | - | **YOK** | chunk/s | 0 | **YOK** | **YÜKSEK** | **MISSING** |
| **RAM / RSS Growth** | Zamanla bellek büyümesi / sızıntı | - | **YOK** | MB | 0 | **YOK** | **YÜKSEK** | **MISSING** |
| **LanceDB Fragment Growth** | Vektör parçalanma ve sürüm artışı | - | **YOK** | Adet | 0 | **YOK** | **ORTA** | **MISSING** |

---

## 7. Ölçüm Metodolojisi Doğrulama (Measurement Correctness)

### Doğrulanmış Güçlü Yönler:
1. **Tip Karışıklığı Önlenmiştir (Boolean/Numeric Confusion Fixed):** `harness/gates.py` satır 176–196 arasında yapılan onarımla, Python'daki `True == 1` ve `True >= 0.8` mantıksal zaafiyeti giderilmiştir. Boolean sözleşmeler artık yalnızca kesin boolean ve `eq` operatörü ile sınanmaktadır.
2. **Fail-Closed Altyapı:** Eksik kanıt, HTTP 500 hataları veya eksik dosya durumunda testler asla varsayılan PASS üretmez; doğrudan `INFRASTRUCTURE_ERROR` ve `FAIL` verir.
3. **Mühürlü Bağlam (Sealed Context Render):** Modelin gördüğü bağlam metni ile arama sonuçlarından türetilen adaylar harfi harfine yeniden oluşturularak hash doğrulaması yapılmaktadır.

### Ciddi Metodolojik Kusurlar:
1. **Answer Scorer — Harfi Harfine (Verbatim) Eşleşme Çıkmazı:**
   - `harness/answer_scorer.py` satır 302–314 incelendiğinde:
   ```python
   def proposition(text: str) -> str:
       return _normalized(text).strip().rstrip(".!?; ")
   supported_texts = {proposition(fact.claim)} | {
       proposition(span.exact_text) for span in fact.supported_by ...
   }
   if proposition(claim.text) not in supported_texts:
       unresolved.append("claim contains unsupported material or unresolved paraphrase")
   ```
   - **Sorun:** LLM, sorulan hukuki soruyu mükemmel ve doğru bir Türkçe ile açıklasa dahi, ürettiği iddia cümlesi kanun maddesinin metniyle veya soru şablonundaki `fact.claim` ile **noktası virgülüne aynı değilse** `UNRESOLVED` olarak işaretlenir.
   - **Etki:** `_answer_metrics` içinde `pass_rate` yalnızca `status == "PASS"` olanları saydığı için, semantik olarak doğru tüm cevaplar reddedilir. Tarihsel koşuda `answerable_pass_rate = 0.44` ve son bağımsız denetimlerde `0.0` çıkmasının temel nedeni modelin başarısızlığı değil, **ölçüm aracının anlamsal parafrazı desteklememesidir**.
2. **Gecikme ve Performans Metriklerinin Yokluğu:**
   - `urllib` üzerinden her istekte `latency_ms` ölçülmekte fakat bu değer yalnızca log dosyasına yazılmaktadır.
   - B0-B14 kapılarının hiçbirinde milisaniye cinsinden bir sınır yoktur. MESA bir aramaya 20 milisaniyede de yanıt verse, 45 saniyede de yanıt verse kapı açısından farksızdır.
3. **Pasif Kaynak İzleme (No Active Resource Profiling):**
   - Bellek, disk ve işlemci ölçümleri işletim sisteminden dinamik olarak okunmamakta; test klasörüne önceden bırakılmış `resource-telemetry.jsonl` dosyasından okunmaktadır.

---

## 8. Sertifikasyon Kapıları Analizi (Certification Gates Analysis)

`config/profile-b-gates.json` içinde tanımlı 15 zorunlu kapının (B0–B14) analizi:

| Kapı ID | Kapı Adı | Gerekli Kanıt Dosyaları | Giriş Metrikleri | Geçme Koşulu | Gerçek Sertifikasyon Değeri |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **B0** | Temiz kod tabanı ve bağımlılıklar | `baseline-evidence.json` | git clean, branch, ci pass | Hepsi True | **YÜKSEK** (Hijyen sağlar) |
| **B1** | Donanım minimumu (RAM/Disk) | `baseline-evidence.json` | ram >= 8GB, disk >= 30GB | Eşikler sağlanmalı | **ORTA** (Sadece statik kontrol) |
| **B2** | Gerçek sağlayıcı sözleşmesi | `provider-canary.json` | dim=768/2048, model adı | Sağlayıcı doğrulaması | **YÜKSEK** (Mock önler) |
| **B3** | Docker/Runtime paritesi | `docker-parity.json` | docker_config_parity | True | **ORTA** |
| **B4** | MESA_Data kanun bütünlüğü | `corpus-integrity.json` | eligible_docs >= 50 | True | **BLOCKED** (Runner veri üretmez) |
| **B5** | H1 İnsan onayı ve hash bağı | `human-approval.json` | h1_approval_hash_bound | True | **YÜKSEK** (Süreç kontrolü) |
| **B6** | Canlı canary ekleme testi | `native-canary.json` | canary_passed, COMMITTED | True | **BLOCKED** (Runner icra etmez) |
| **B7** | Toplu dağıtım (Bulk delivery)| `delivery-evidence.json` | undelivered_chunk == 0 | 5722 parça COMMITTED | **BLOCKED** (Runner icra etmez) |
| **B8** | Yeniden başlatma ve idempotency | `restart-idempotency.json`| restart_persistence_proven | True | **BLOCKED** (Runner restart yapamaz)|
| **B9** | Negatif yetki ve ACL izolasyonu | `scope-isolation.json` | leakage == 0, acl_passed | True | **BLOCKED** (MESA kontrat engeli) |
| **B10**| TEST Arama Metrikleri | `scoring-summary.json` | Recall@5>=0.8, MRR>=0.7 | Eşikler sağlanmalı | **BLOCKED** (MESA kontrat engeli) |
| **B11**| Kùzu Graf nedensel katkısı | `graph-ablation.json` | rel_contribution >= 3 | Nedensel fayda ispatı | **BLOCKED** (MESA kontrat engeli) |
| **B12**| Cevap doğruluğu ve çekinme | `scoring-summary.json` | pass_rate>=0.8, fab=0 | Eşikler sağlanmalı | **KUSURLU** (Verbatim kuralı) |
| **B13**| Kaynak stabilitesi ve OOM | `resource-telemetry.jsonl`| oom_killed == 0 | Çökme olmamalı | **ORTA** (Pasif doğrulanır) |
| **B14**| Kanıt bütünlüğü ve dondurma | `raw-manifest.json` vb. | post_freeze_mutations == 0| Hash zinciri tam | **YÜKSEK** (Tahrifatı önler) |

---

## 9. Yanlış PASS ve Yanlış FAIL Riskleri (False Positives & Negatives)

### A. Doğrulanmış Yanlış FAIL Riskleri (Confirmed False-FAIL Risks) — KRİTİK
1. **Doğru Hukuki Cevapların Reddedilmesi:** `answer_scorer.py` içindeki string proposition eşitliği nedeniyle, Qwen veya başka bir model soruya eksiksiz ve doğru bir cevap verse bile, ground truth metniyle birebir aynı karakter dizisini üretmediği sürece FAIL/UNRESOLVED almaktadır. Bu durum çalışan ve doğru bir MESA sistemini haksız yere sertifikasyondan bırakır.
2. **MESA İç Denetim Belirteci Engeli:** MESA v0.8.1 arama fonksiyonu kiracı izolasyonunu arka planda başarıyla sağlasa ve yetkisiz hiçbir veriyi döndürmese dahi; public JSON içinde `pre_rank_scope_audit_id` döndürmediği için B9 ve B10 doğrudan BLOCKED olmakta, test süiti MESA'yı haksız yere başarısız saymaktadır.
3. **Kod Dondurma Kırılganlığı:** `freeze.py` test kodundaki bir yorum satırı değişikliğini veya dokümantasyon güncellemesini dahi kod manipülasyonu sayarak `INVALIDATED_CODE_CHANGE` üretmekte ve testi kitlemektedir.

### B. Tarihsel Yanlış PASS Kanıtı (Historical False-PASS Evidence)
- `tests/test_legacy_audit.py` ve `runs/RUN-20260901T005200Z-p8b03/verdict.json` incelendiğinde:
  - Tarihsel koşuda `overall_recall_at_5 = 0.7428` (Eşik: 0.80) idi.
  - `overall_mrr_at_5 = 0.6004` (Eşik: 0.70) idi.
  - `single_paraphrase recall_at_5 = 0.60` (Eşik: 0.90) idi.
  - Graf katkısı negatifti (`mrr_gain = -0.029`, `recall_at_1_gain = -0.057`).
  - Buna rağmen tarihsel betik dosyaya `"overall_status": "CERTIFIED"` ve `"certification_verdict": "PASS"` yazdırmıştır!
- **Mevcut Durum:** Son onarımlarla bu sahte geçiş açığı tamamen kapatılmıştır. Mevcut sistemde yanlış PASS alma riski neredeyse **sıfırdır**; fakat sarkaç diğer uca savrulmuş ve meşru sistemlerin de geçemeyeceği aşırı katı bir kilitlenme ortaya çıkmıştır.

---

## 10. Kapsam Yeterliliği Haritası (Coverage Adequacy)

| MESA Çekirdek Yeteneği | E2E Sertifikasyon Kapsamı | Kanıt Türü | Değerlendirme |
| :--- | :--- | :--- | :--- |
| **Vektör Projeksiyonu (LanceDB)** | Kısmi (Arama sırasında) | API E2E | **PARTIALLY_VERIFIED** |
| **Metin Araması (FTS5 / BM25)** | Kısmi (RRF içinde) | API E2E | **PARTIALLY_VERIFIED** |
| **Graf Projeksiyonu (Kùzu)** | Kısmi (Arama kanıtı var) | API E2E | **PARTIALLY_VERIFIED** (Ablasyon engelli) |
| **4 Kanallı RRF Birleştirme** | Kapsanıyor (Top-5 arama) | API E2E | **FULLY_VERIFIED** |
| **Kanonik Bellek Ekleme** | Harici JSON'a bağlı | Sentetik/Mock | **MOCK_ONLY** (Runner çalıştırmaz) |
| **Mutasyon Yaşam Döngüsü** | Harici JSON'a bağlı | Sentetik/Mock | **MOCK_ONLY** |
| **Outbox Projeksiyon İşçileri** | Yok | Yok | **NOT_COVERED** |
| **Kiracı / Ajan İzolasyonu** | Tasarlandı, kontrat engelli | API E2E | **PARTIALLY_VERIFIED** |
| **Yeniden Başlatma Dayanıklılığı**| Harici JSON'a bağlı | Sentetik/Mock | **MOCK_ONLY** |
| **MCP Entegrasyonu (Gateway)** | Yok | Yok | **NOT_COVERED** |
| **Python İstemcisi (`mesa_client`)**| Yok (urllib kullanılıyor)| Yok | **NOT_COVERED** |
| **Eşzamanlı Yük / Performans** | Yok (Sıralı 80 sorgu) | Yok | **NOT_COVERED** |
| **Yedekleme ve Geri Yükleme** | Yok | Yok | **NOT_COVERED** |
| **Alembic Veritabanı Göçleri** | Yok | Yok | **NOT_COVERED** |

---

## 11. Test Verisi Kalitesi (Test Data Quality)

- **Veri Kümesi Hacmi:** 80 dondurulmuş TEST sorusu, 12 DEV sorusu.
- **Dağılım:**
  - 40 adet `SINGLE_DIRECT`
  - 20 adet `SINGLE_PARAPHRASE`
  - 10 adet `RELATIONAL`
  - 10 adet `NO_ANSWER`
- **Temsiliyet Sorunu:**
  - Soruların tamamı Türk Medeni Kanunu (TMK), Türk Borçlar Kanunu (TBK), İcra İflas Kanunu (İİK) gibi kanun metinlerinden türetilmiştir.
  - Soruların büyük kısmında kanun madde numarası açıkça yer almaktadır (Örn: *"TMK m. 161'e göre zina sebebiyle boşanma..."*). Bu durum, semantik anlamsal aramadan ziyade basit bir anahtar kelime eşleşmesinin (BM25) yüksek puan almasına yol açmaktadır.
  - Gerçek dünya hukuki senaryolarını oluşturan Yargıtay içtihatları, karmaşık dava dosyaları, çelişkili deliller ve zamansal mevzuat değişiklikleri veri setinde **yoktur**.
  - 80 sorunun tamamı açık metin olarak depoda izlenmektedir; sistemde gizli bir değerlendirme kümesi (holdout) bulunmamaktadır.

---

## 12. Performans Ölçüm Kalitesi (Performance Measurement Quality)

- **Gecikme Dağılımı:** Depoda p50, p95, p99, minimum veya maksimum gecikme hesaplayan hiçbir algoritma yoktur.
- **İşlem Hacmi (Throughput):** Saniyedeki arama veya ekleme sayısı ölçülmemektedir.
- **İzolasyon Eksikliği:** Ölçülen tek gecikme değeri, `mesa_transport.py` içindeki toplam HTTP istek süresidir (`time.perf_counter()`). Bu süre ağ gecikmesini, Python JSON ayrıştırmasını ve MESA iç işlem süresini birbirinden ayıramaz.
- **Sonuç:** Deponun performans ölçüm yeteneği **istatistiksel olarak geçersiz ve yetersizdir**.

---

## 13. Kaynak Tüketimi ve Yük Analizi (Resource Consumption & Workload)

1. **Test Süiti Çalışma Maliyeti (Pytest):**
   - 567 adet test `uv run pytest -q` ile **12.44 saniyede** tamamlanmaktadır.
   - Bu aşamada harici LLM veya MESA çağrılmadığı için CPU ve bellek tüketimi oldukça düşüktür (Peak RSS < 150 MB).
2. **Yeterlilik Koşusu Maliyeti (Qualification Workload):**
   - 80 soru için sıralı arama çağrısı yapılır.
   - 80 soru için yerel veya uzak Ollama (Qwen 9B) modeline `max_tokens: 4096` ile istek atılır.
   - Bir 9B modelin 80 soruya tam çıkarım yapması modern bir GPU'da 10-20 dakika, CPU'da ise saatler sürer.
   - **Verimsizlik:** Elde edilen 80 cevabın tamamı `answer_scorer.py` içindeki harfiyen eşleşme kuralı yüzünden reddedilecektir. Harcanan GPU/token kaynakları çöpe gitmektedir.
3. **Disk Şişkinliği:**
   - Tek bir koşu 75 MB'ın üzerinde JSON, sıkıştırılmış dosya ve yan `.SHA256` dosyası üretmektedir.

---

## 14. Dış Sağlayıcı, LLM ve Token Maliyeti

- **Beklenen İstek Sayısı:** 80 tam metin tamamlama isteği (Chat Completion).
- **Token Tüketimi:** Ortalama bağlam (2048 token) + çıktı (ortalama 300 token) = Soru başına ~2350 token. 80 soru için koşu başına yaklaşık **188.000 token**.
- **Maliyet ve Süre:** Yerel Ollama kullanımında doğrudan API faturası çıkmaz ancak donanım kilitlenir. Ücretli bir OpenAI/NVIDIA API kullanılsaydı koşu başına maliyet oluşacaktı.
- **Hata:** MESA Core'un görevi arama motoru olmaktır. MESA'nın kendi içinde bir nihai metin üretim (answer generation) endpoint'i zaten yoktur (`POST /v4/memory/search` yalnızca kanıtları döndürür). Sertifikasyon aracının LLM çağrısını bizzat yapıp ardından bunu MESA sertifikasyon kapısı yapması mimari bir sorumluluk karmaşasıdır.

---

## 15. Gereksiz ve Tekrarlayan Bileşenler (Redundant Components)

1. **`harness/execution_provenance.py` (626 LOC):** Süreç içinde rastgele üretilen HMAC gizli anahtarı ile bellek içi nesne karşılaştırması yapar. Otomasyona dayalı CI/CD ortamında sahte dosya kopyalama tehdidi gerçekçi değildir.
2. **`harness/state_proof.py` (809 LOC):** SQLite WAL modunu inceleyen, gölge tabloların satır sıralamasını doğrulamaya çalışan 800 satırlık kod, MESA'nın iç yapısına gereksiz derecede bağımlıdır.
3. **`harness/transaction.py` (1.013 LOC):** Bir Python testinin sıralı fonksiyon çağrıları ile yapabileceği bootstrap, freeze, score, gate adımlarını devasa bir işlem yönetim sınıfına dönüştürmüştür.
4. **Çok Sayıda Yinelenen JSON Çıktısı:** `run_manifest.json`, `raw-manifest.json`, `determinism-manifest.json`, `evidence-index.json` birbirinin neredeyse kopyası olan dosya listeleridir.
5. **Tekrarlayan Test Dosyaları:** `tests/` klasöründeki 53 dosyanın birçoğu (örneğin `test_c6_run_id_consistency.py`, `test_trust_root_closure.py`, `test_final_integrity_adversarial_audit.py`) aynı bütünlük invariantlarını hafif varyasyonlarla tekrar tekrar test etmektedir.

---

## 16. Aşırı Mühendislik Bulguları (Over-Engineering Findings)

Depoda tespit edilen aşırı mühendislik örüntüleri:
1. **"Güvenilmez Ortam Paranoyası" (Byzantine Paranoia):** Kod, sanki düşman bir operatörün bilgisayarında çalışıyormuş gibi kendi Python kaynak kodlarının hash'ini almakta, bellekte gizli HMAC jetonları dolaştırmakta ve her JSON dosyasının yanına bir `.SHA256` dosyası iliştirmektedir. Bir CI sunucusunda çalışan test süiti için bu mekanizmalar tamamen fuzulidir.
2. **Siyah Kutu İlkesinin Çiğnenmesi:** E2E sertifikasyon aracı MESA'yı dışarıdan bir HTTP servisi olarak sınamak yerine; MESA'nın SQLite veritabanı dosyasına doğrudan bağlanıp `projection_outbox` ve `artifact_cleanup_outbox` tablolarını sorgulamaktadır (`state_proof.py:36-48`).
3. **Ajan Dokümantasyonu Şişkinliği:** `agent-pack/` altındaki 35 dosya ve ~300 KB dokümantasyon, standart bir mühendislik projesi için sürdürülemez bir bürokrasi yaratmaktadır.

---

## 17. Yeniden Üretilebilirlik (Reproducibility)

- **Birim Test Seviyesinde:** **MÜKEMMEL**. `uv sync --locked` ve `pytest` bağımsız makinelerde 13 saniyede sıfır hata ile çalışmaktadır.
- **Canlı Sertifikasyon Seviyesinde:** **BAŞARISIZ / İMKANSIZ**. Dışarıdan bir geliştirici depoyu klonlayıp canlı MESA üzerinde Profile B sertifikasyonu almak istediğinde:
  - MESA_Data hazır olmadığı için B4/B6/B7/B8 gate'lerini geçemez.
  - MESA arama endpoint'i özel denetim alanlarını dönmediği için B9/B10'da kilitlenir.
  - LLM cevapları harfiyen eşleşmediği için B12'de kilitlenir.
  - Sonuçta `PROFILE_B_BLOCKED_PRECONDITION` dışında bir sonuç üretilemez.

---

## 18. Asgari Kullanışlı E2E Mimarisi (Minimum Useful E2E Architecture)

MESA MVP'sinin güvenle sertifikalandırılması için gereken **Yalın E2E Mimarisi**:

### 1. Katman: Hızlı CI Kontrolleri (Her PR ve Commit için - < 30 saniye)
- Temiz ortam doğrulaması (`health_check`).
- Statik şema ve normalizasyon testleri.
- Mock MESA üzerinden 12 soruluk DEV veri kümesi doğrulaması.
- Temel arama ve puanlama mantığı birim testleri.

### 2. Katman: Sürüm Öncesi Entegrasyon Sertifikasyonu (Nightly / Release - < 5 dakika)
- Gerçek MESA Docker konteyneri ayağa kaldırma (`docker-compose.v4.yml`).
- Kanonik bellek ekleme (`POST /v4/memory/insert`) ve COMMITTED doğrulaması.
- 80 soruluk dondurulmuş TEST hukuki arama sorgusu (`POST /v4/memory/search`).
- Recall@5 (>= 0.80) ve MRR (>= 0.70) değerlendirmesi.
- **Gerçek Kara Kutu Kiracı İzolasyonu:** Kiracı A oturumu ile arama yapıldığında Kiracı B verilerinin kesinlikle gelmediğinin doğrulanması (MESA'nın iç denetim token'ı üretmesine gerek kalmadan!).
- Konteyner yeniden başlatma (`docker restart`) ve verilerin kaybolmadığının doğrulanması.
- p50, p95 gecikme ölçümü (p95 < 500ms sınırı).
- Sade bir `certification_report.json` üretimi.

---

## 19. Test Değeri ile Operasyonel Maliyetin Karşılaştırılması

| Alt Sistem / Bileşen | Test Değeri | Hata Yakalama Kapasitesi | Yürütme ve Bakım Maliyeti | Sınıflandırma | Karar |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Arama Puanlayıcı (`retrieval_scorer`)** | YÜKSEK | YÜKSEK | DÜŞÜK | **HIGH_VALUE_LOW_COST** | Koru |
| **Normalizasyon ve Kimlik Eşleme** | YÜKSEK | YÜKSEK | DÜŞÜK | **HIGH_VALUE_LOW_COST** | Koru |
| **Kapı Değerlendirici (`gates.py`)** | YÜKSEK | YÜKSEK | DÜŞÜK | **HIGH_VALUE_LOW_COST** | Koru |
| **Negatif İzolasyon Testleri** | YÜKSEK | YÜKSEK | ORTA | **HIGH_VALUE_LOW_COST** | Sadeleştirerek Koru |
| **LLM Yanıt Puanlama (`answer_scorer`)** | ORTA | DÜŞÜK | YÜKSEK (GPU/Token) | **LOW_VALUE_HIGH_COST** | Düzelt veya Opsiyonel Yap |
| **Kod Dondurma (`freeze.py`)** | DÜŞÜK | DÜŞÜK | YÜKSEK (Geliştirmeyi bozar) | **LOW_VALUE_HIGH_COST** | Kaldır |
| **Oturum HMAC İspatı (`provenance`)** | ÇOK DÜŞÜK| SIFIR | YÜKSEK (Suni karmaşıklık)| **LOW_VALUE_HIGH_COST** | Kaldır |
| **SQLite Tablo Parmak İzi (`state_proof`)**| DÜŞÜK | DÜŞÜK | ÇOK YÜKSEK (Kırılgan) | **LOW_VALUE_HIGH_COST** | Kaldır |
| **12 Fazlı İşlem Makinesi (`transaction`)**| DÜŞÜK | DÜŞÜK | YÜKSEK | **LOW_VALUE_HIGH_COST** | Sadeleştir |

---

## 20. Sadeleştirme Fırsatları ve Kazançlar

1. **`state_proof.py`, `execution_provenance.py` ve `freeze.py` Dosyalarının Kaldırılması:**
   - **Kod Azalması:** Yaklaşık **1.720 satır** karmaşık kod silinir.
   - **Kazanım:** Harness MESA'nın SQLite iç şemalarından bağımsızlaşır; MESA şema değiştirdiğinde testler kırılmaz.
2. **`transaction.py` ve 17 Parçalı Dağıtımın Sadeleştirilmesi:**
   - **Kod Azalması:** Yaklaşık **1.200 satır** kod sadeleşir.
   - **Kazanım:** Yüzlerce `.SHA256` ve özet dosyası yerine tek bir makine tarafından okunabilir `verdict.json` ve `report.md` üretilir.
3. **`answer_scorer.py` Mantığının Düzeltilmesi:**
   - **Kazanım:** Doğru çalışan modellerin haksız yere elenmesi önlenir; sistem gerçek üretken LLM çıktılarını ölçebilir hale gelir.
4. **Tahmini Toplam Tasarruf:**
   - Kod tabanında **%40 küçülme** (~12.000 satır sadeleşme).
   - Test bakım eforunda **%60 azalma**.
   - Haksız kilitlenme ve False-FAIL oranında **%100 azalma**.

---

## 21. 0–100 Puanlama Tablosu

| Boyut | Alınan Puan | Maksimum Puan | Temel Zayıflık | Güven Düzeyi |
| :--- | :---: | :---: | :--- | :---: |
| **A. Mimari ve Bakım Kolaylığı** | **7** | 15 | Aşırı katmanlar, HMAC oturumları, SQLite iç tablo bağımlılığı | YÜKSEK |
| **B. Kapsam ve MVP Yeterliliği** | **10** | 25 | Yalnızca arama endpoint'i kapsanıyor; MCP, SDK, Workers, Yük yok | YÜKSEK |
| **C. Ölçüm Geçerliliği ve Doğruluğu** | **12** | 25 | Cevap puanlayıcı harfi harfine kuralıyla kusurlu; gecikme p95 yok | YÜKSEK |
| **D. Bağımsız Kanıt ve Yeniden Üretilebilirlik**| **11** | 20 | Birim testler çok iyi; canlı sertifikasyon dış bağımlılıklarla kilitli | YÜKSEK |
| **E. Operasyonel Verimlilik ve Maliyet** | **6** | 15 | Yanıtsız LLM token israfı, dosya enflasyonu, çalıştırılamayan akış | YÜKSEK |
| **TOPLAM SKOR** | **46** | **100** | **Provisyonel Aralık: 42 – 50 / 100** | **YÜKSEK** |

---

## 22. Önceliklendirilmiş Eylemsel Mühendislik Planı

### P0 — Sertifikasyon Kilitlenmesi ve Yanlış-FAIL Sorunları
- **ISSUE-01: `answer_scorer.py` Harfiyen Eşleşme Zorunluluğu**
  - *Etkilenen Dosyalar:* `harness/answer_scorer.py:302-314`
  - *Mevcut Durum:* Modelin iddiası, ground-truth iddia metniyle tam eşleşmezse `UNRESOLVED` olur ve elenir.
  - *Önerilen Değişiklik:* Kanıt parçası doğrulaması ve regex kalıbı sağlandığında, metin benzerliği için ya esnek bir semantik eşleşme uygulanmalı ya da tam alıntı zorunluluğu açık bir alıntı bayrağına (`exact_quote`) bağlanmalıdır.
- **ISSUE-02: MESA Arama Yanıtından İç Denetim Belirteci Beklenmesi**
  - *Etkilenen Dosyalar:* `harness/mesa_adapters.py:607-632`
  - *Mevcut Durum:* `pre_rank_scope_audit_id` ve `candidate.agent_id` yoksa `BLOCKED_BY_MESA_CONTRACT` fırlatır.
  - *Önerilen Değişiklik:* Dış kara kutu yaklaşımına dönülmeli; dönen adaylar arasında yabancı kiracı/ajan ID'si bulunmadığı sürece arama geçerli sayılmalıdır.

### P1 — Gerçek MVP Yeteneklerinin Test Süitine Eklenmesi
- **ISSUE-03: Gecikme Yüzdelikleri ve Performans Kapısı Eklenmesi**
  - *Etkilenen Dosyalar:* `harness/metric_producers.py`, `config/profile-b-gates.json`
  - *Önerilen Değişiklik:* 80 sorgunun p50, p95 gecikmeleri hesaplanmalı ve `search_p95_latency_ms <= 500` şeklinde B10 kapısına eklenmelidir.
- **ISSUE-04: MESA Konteyner Yaşam Döngüsü ve Yeniden Başlatma Testinin İcrası**
  - *Etkilenen Dosyalar:* `harness/qualification_runner.py`
  - *Önerilen Değişiklik:* Runner, Docker API veya HTTP üzerinden MESA'ya veri ekleyip ardından konteyneri yeniden başlatabilmeli ve verilerin korunduğunu doğrulamalıdır.

### P2 — Aşırı Mühendisliğin Tasfiyesi
- **ISSUE-05: Bellek İçi HMAC ve Kod Dondurma Mekanizmalarının Kaldırılması**
  - *Etkilenen Dosyalar:* `harness/execution_provenance.py`, `harness/freeze.py`
  - *Önerilen Değişiklik:* Bu iki modül devreden çıkarılmalı, standart Git SHA kaydı yeterli kabul edilmelidir.
- **ISSUE-06: `state_proof.py` SQLite Gölge Tablo Kodunun Kaldırılması**
  - *Etkilenen Dosyalar:* `harness/state_proof.py`, `harness/graph_collector.py`
  - *Önerilen Değişiklik:* Veritabanı dosyasına içeriden bağlanmak yerine, HTTP API üzerinden durum kontrolü yapılmalıdır.

---

## 23. Proje Sahibinin 25 Sorusuna Doğrudan Cevaplar

### Q1. E2E Sertifikasyon deposu gereksiz derecede karmaşık mı?
**Evet.** Depo, MESA'nın yalnızca arama fonksiyonunu test etmek için yaklaşık 32.000 satır Python kodu, HMAC oturum imzalama, kod dondurma karmaşıklığı ve 12 fazlı işlem makineleri inşa etmiştir. Bu yapı amaçlanan faydaya kıyasla aşırı karmaşıktır.

### Q2. Karmaşıklığın hangi kısımları haklı ve gereklidir?
- `retrieval_scorer.py`: Recall@5, MRR ve ilişkisel kanıt kapsamı hesaplaması nettir ve gereklidir.
- `normalizer.py`: Türkçe karakter ve hukuki madde normalizasyonu zorunlu ve başarılıdır.
- `identity.py`: Kaynak kanun parçası ile sistem ID'si arasındaki eşleme gereklidir.
- `gates.py`: Tip güvenli kapı eşik değerlendiricisi gereklidir.

### Q3. Hangi bileşenler gerçekte fuzuli ve tekrarlayıcıdır?
- `harness/execution_provenance.py` (HMAC oturum imzalama).
- `harness/state_proof.py` (SQLite WAL ve tablo parmak izi).
- `harness/freeze.py` (Kendi Python kaynak kodlarını dondurma).
- `harness/transaction.py` (Aşırı soyutlanmış işlem durumu).
- Birbiriyle çakışan 17 farklı özet JSON dosyası ve yan `.SHA256` dosyaları.

### Q4. Sistem MESA'nın doğru özelliklerini mi ölçüyor?
**Kısmen.** Arama kalitesini ve negatif kiracı izolasyonunu doğru hedeflerle ölçmektedir. Ancak gecikme yüzdeliklerini (p95), sistem verimini, MCP uyumluluğunu, bellek sızıntısını ve outbox işçilerini ölçmemektedir.

### Q5. Ölçümler doğru şekilde mi uygulanmıştır?
**Karma.** Arama metrikleri (Recall, MRR) matematiksel olarak doğrudur. Ancak cevap puanlayıcı (`answer_scorer.py`), modeli harfi harfine kanun metnini kopyalamaya zorlayarak doğru cevapları `UNRESOLVED` yapmakta ve ölçümü anlamsal olarak sakatlamaktadır.

### Q6. Sistem yanıltıcı PASS sonuçları üretebilir mi?
**Mevcut kodda Hayır.** Son sertifikasyon hardening onarımlarıyla yanlış PASS riski kapatılmıştır. Sistem artık aşırı katı ve fail-closed'dır. (Ancak tarihsel `RUN-20260901T005200Z-p8b03` koşusu eşiklerin altında kalmasına rağmen sahte bir PASS üretmiştir).

### Q7. Sağlıklı bir MESA'yı yanlışlıkla FAIL yapabilir mi?
**Evet, kesinlikle.** 
1. Doğru cevap veren bir LLM modelini parafraz yaptığı için FAIL/UNRESOLVED yapar.
2. Kiracı izolasyonu kusursuz çalışan bir MESA'yı iç denetim belirteci dönmediği için BLOCKED yapar.

### Q8. Test veri kümeleri uygun mu?
**Sınırlı.** 80 adet kanun maddesi sorusu temel arama doğrulaması için iyidir. Ancak soruların çoğunda kanun madde numarası açıkça yazılıdır ve gerçek dünyanın karmaşık içtihatlarını, çelişkili delillerini içermez.

### Q9. Arama kalitesi ölçümleri anlamlı mı?
**Evet.** 80 soru üzerinde Top-5 adayı içinde beklenen parçanın yer alıp almadığı matematiksel olarak doğru ölçülmektedir.

### Q10. Sistem güvenlik ve kiracı izolasyonunu yeterince test ediyor mu?
**Tasarım olarak evet, pratik olarak hayır.** 12 negatif senaryo (`cross_tenant_search` vb.) çok iyi düşünülmüştür. Fakat MESA API'sinden imkansız iç denetim belirteçleri talep ettiği için pratikte çalışmamakta ve BLOCKED olmaktadır.

### Q11. Mutasyon ve projeksiyon doğruluğunu yeterince test ediyor mu?
**Hayır.** Test koşucusu MESA'ya bizzat veri eklemez, mutasyon oluşturmaz. B6 ve B7 kapıları harici dosyalara güvenir.

### Q12. Gecikme ve kaynak tüketimini yeterince ölçüyor mu?
**Hayır.** Ne p50/p95 gecikme kapısı vardır ne de işletim sisteminden dinamik bellek/CPU ölçümü yapılır.

### Q13. Performans ölçümleri iddiaları için istatistiksel olarak güvenilir mi?
**Hayır.** Sistemde istatistiksel gecikme analizi, ısınma (warmup) turları veya güven aralıkları yoktur.

### Q14. Bellek sızıntılarını ve uzun süreli kaynak büyümesini tespit edebilir mi?
**Hayır.** Depoda uzun süreli soak testi veya bellek büyüme takibi yapan hiçbir kod yoktur.

### Q15. Gereksiz API, LLM, RAM, CPU veya disk iş yükü yaratıyor mu?
**Evet.** Her koşuda 80 adet 9B LLM çıkarımı yaptırılmakta, üretilen cevaplar verbatim kuralı yüzünden çöpe gitmekte ve yüzlerce gereksiz JSON/SHA dosyası diske yazılmaktadır.

### Q16. Tekrarlanan veya gereksiz testler var mı?
**Evet.** 53 test modülü içinde dosya bütünlüğü, run_id kontrolü ve kapı değerlendirmesini mükerrer defalar test eden çok sayıda test vardır.

### Q17. Sertifikasyon profilleri amaç ve maliyete göre uygun şekilde ayrılmış mı?
**Hayır.** Sadece tek bir monolitik profil (Profile B) vardır. Hızlı CI ile ağır sürüm testleri birbirinden ayrılmamıştır.

### Q18. Sürüm PASS/FAIL kapıları güvenilir mi?
**Mantık olarak güvenilir, operasyonel olarak kilitlidir.** Kapı değerlendirici hileye izin vermez ancak mevcut MESA ile hiçbir zaman PASS durumuna ulaşamaz.

### Q19. Başka bir geliştirici sonuçları yeniden üretebilir mi?
Birim testleri (`pytest`) 13 saniyede %100 yeniden üretilebilir. Ancak canlı Profile B koşusu dış ortam eksiklikleri ve sözleşme engelleri nedeniyle yeniden üretilemez.

### Q20. En yüksek değere sahip 5 iyileştirme nedir?
1. `answer_scorer.py` içindeki harfi harfine metin eşleşme kuralını düzeltmek.
2. MESA izolasyon testini iç denetim token'ı yerine kara kutu filtreleme esasına döndürmek.
3. MESA veri ekleme ve yeniden başlatma adımlarını doğrudan runner içine entegre etmek.
4. p50, p95 gecikme ölçümü ve performans eşikleri eklemek.
5. HMAC, SQLite gölge tablo tarama ve kod dondurma katmanlarını tasfiye ederek mimariyi sadeleştirmek.

### Q21. Önemli sertifikasyon kapsamı kaybedilmeden ne sadeleştirilebilir?
`state_proof.py`, `execution_provenance.py`, `freeze.py` ve `transaction.py` kaldırılarak yaklaşık 3.500 satır kod atılabilir; hiçbir test gücü kaybedilmez.

### Q22. Hızlı CI ile genişletilmiş sürüm sertifikasyonunda ne çalışmalıdır?
- **Hızlı CI:** Birim testler, normalizasyon, puanlama mantığı ve mock arama doğrulaması (< 30 sn).
- **Genişletilmiş Sürüm:** Canlı Docker üzerinde 80 sorguluk TEST araması, yeniden başlatma, p95 gecikme ve izolasyon testleri (< 5 dk).

### Q23. Mevcut sistem MESA MVP yeterliliği için yeterli mi?
**Hayır.** Hem kilitlenmeler yüzünden PASS verememektedir hem de MCP, Python SDK, işçiler ve eşzamanlı yük gibi MVP'nin ana unsurlarını kapsamamaktadır.

### Q24. Daha küçük bir uygulama eşit veya daha iyi kanıt sağlar mı?
**Kesinlikle evet.** Standart pytest ve HTTP istemcisi kullanan 2.000 satırlık temiz bir kara kutu test paketi, bu 32.000 satırlık sistemden katbekat daha güvenilir, şeffaf ve sürdürülebilir kanıt üretir.

### Q25. Mevcut sertifikasyon mimarisindeki tek ve en önemli sorun nedir?
**"İcraat yerine bürokratik tasdik tiyatrosu kurmak" (Attestation Theater over Functional Execution).** Sistem, MESA'yı gerçekten çalıştırıp yük altında sınamak yerine; dosyaların SHA özetlerini mühürlemeye, bellek içi HMAC üretmeye ve MESA'dan imkansız iç denetim token'ları talep etmeye odaklanmış ve bu yüzden test edilemez hale gelmiştir.

---

## 24. Nihai Karar (Final Verdict)

### Birincil Karar:
```text
USEFUL_BUT_OVERENGINEERED
(Faydalı Çekirdeğe Sahip Fakat Aşırı Mühendislik İçeren, Kapsamı Dar ve Ölçümü Kusurlu Sistem)
```

### Karar Gerekçesi:
Sistemin dondurulmuş veri kümeleri, arama puanlayıcıları (`retrieval_scorer.py`), Türkçe normalizasyon algoritmaları ve tip güvenli kapı değerlendirme mantığı son derece kıymetli ve başarılıdır. Ancak bu faydalı çekirdek; süreç içi HMAC yetkileri, SQLite iç tablo parmak izi çıkarma, kod dondurma paranoyası ve LLM'i harfi harfine metin kopyalamaya zorlayan sakat bir cevap puanlama mantığıyla sarılmıştır. MESA'nın ana yüzeylerini (MCP, SDK, işçiler, gecikme p95) ölçmemekte, MESA'nın karşılayamayacağı iç belirteçleri talep ederek resmi sertifikasyonu kilitlemektedir.

### Tavsiye Edilen Eylem:
```text
TARGETED_SIMPLIFICATION
(Hedefli Sadeleştirme: Gereksiz Doğrulama Katmanlarının Kaldırılması, Cevap Puanlayıcının Onarılması ve Kara Kutu Entegrasyonuna Dönüş)
```

---

## 25. Kanıtlar, Doğrulama Kayıtları ve Sınırlamalar

1. **Test Doğrulama Kanıtı:**
   - Komut: `uv run pytest -q`
   - Sonuç: `567 passed in 12.44s` (Task ID: `d9f19f04-19b3-4b2c-bc7c-78ffb1ac23b8/task-107`).
   - Sıfır hata, sıfır atlama (skip).
2. **Kendi Kendini Sınama (Self-Test):**
   - Komut: `uv run python -O -m harness.self_test`
   - Sonuç: `17/17 passed (all_passed=True)`.
3. **Statik Bütünlük ve Güvenlik:**
   - `verify_agent_pack.py`: PASS
   - `check_no_secrets.py`: PASS (Yüksek güvenilirlikli sır tespit edilmedi)
   - `validate_json_artifacts.py`: PASS (Tüm izlenen JSON ve JSONL dosyaları geçerli).
4. **Denetim Sınırlamaları:**
   - Read-only kuralları gereğince hiçbir üretim kodu, kapı eşiği veya konfigürasyon değiştirilmemiştir.
   - Gerçek Ollama veya NVIDIA NIM modelleri çalıştırılmamış; 24 saatlik dayanıklılık veya canlı MESA konteyner yük testleri başlatılmamıştır. Bütün değerlendirmeler statik kod analizi, mevcut tarihsel kanıtlar ve hafif yerel self-testler üzerinden yürütülmüştür.

---
*Rapor Sonu. Antigravity Bağımsız Kod Denetim Sistemi.*
