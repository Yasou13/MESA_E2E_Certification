# Answer Contract and Oracle Audit

## Gözlenen eski mekanizma

Canlı kaynakta `AnswerClaim.fact_ids` zorunluydu ve `score_answer` bir oracle `RequiredFact.fact_id` değerini yalnız modelin aynı ID'yi claim içinde döndürmesi halinde aday kabul ediyordu. Model isteğine ground-truth fact ID verilmesi ise oracle politikası tarafından yasaktı. Böylece doğru metin ve doğru citation içeren sıradan bir claim, gizli ID'yi tahmin etmedikçe PASS olamıyordu. Tarihsel resmi run'ın tam provider request'i mevcut olmadığı için geçmişteki özel `"claims": []` prompt iddiası `UNVERIFIED`; kaynak mekanizması sentetik testte `REPRODUCED` durumundadır.

## Yeni sözleşme

- Model çıktısı: `answer`, görünür `evidence_chunk_ids`, `insufficient_evidence`, ve `claims[]`.
- Her claim yalnız doğal dil `text` ve görünür `evidence_chunk_ids` gerektirir.
- `fact_ids` eski capture'ları okuyabilmek için opsiyonel/deprecated tutulur; scorer bu alanı güven sinyali olarak kullanmaz (`harness/models.py:229-242`).
- Post-seal scorer her ordinary claim'i dahili required proposition, explicit answer pattern ve frozen source span ile kendisi eşler (`harness/answer_scorer.py:247-329`).
- Bir citation'ın doğru ID olması tek başına yeterli değildir: yanlış, inkâr eden, ek materyal taşıyan veya exact-source proposition ile doğrulanamayan claim PASS olmaz (`harness/answer_scorer.py:270-348`).
- Semantik paraphrase için onaylı judge metodolojisi yoksa sonuç `UNRESOLVED`; permissive fuzzy PASS yoktur.

## Oracle bariyeri

`fact_id`/`fact_ids`, required facts, qrels, expected labels ve gold IDs artık hem recursive raw audit'te (`harness/oracle.py:11-40`) hem de provider çağrısından önce prompt/request parametrelerinde reddedilir (`harness/answer_execution.py:598-651`). Provider çıktısı audit input yüzeyinden hariçtir; bu, modelin kendi ürettiği string'i oracle sızıntısı sanmaz fakat request'e sızıntıyı engeller.

## Durum semantiği

| Durum | Anlam | B12 etkisi |
|---|---|---|
| PASS | tüm gerekli source-linked propositions, citations, scope ve abstention koşulları sağlandı | pass-rate payına girer |
| FAIL | yanlış/eksik proposition, answerable abstention, fabricated/out-of-context ID, forbidden claim veya hard invariant ihlali | PASS sayılmaz |
| UNRESOLVED | exact deterministik metodolojiyle doğrulanamayan paraphrase/ek materyal veya eksik explicit pattern | PASS sayılmaz; otomatik affedilmez |

NO_ANSWER yalnız exact kanonik abstention marker, `insufficient_evidence=true`, citation/claim yokluğu ile PASS olur (`harness/answer_scorer.py:165-197`). Answerable soruda abstention doğrudan FAIL'dir (`harness/answer_scorer.py:199-209`).

## Reprodüksiyon ve regresyonlar

RED komutu: `uv run --locked pytest -q tests/test_comprehensive_repair_regressions.py` → başlangıçta `10 failed`.

GREEN kapsamı:

- ordinary atomic claim, oracle fact ID olmadan PASS;
- valid citation + yanlış fact FAIL;
- `fact_ids` prompt/request leakage provider çağrısından önce reddedilir;
- fabricated citation, denial, extra unsupported material, malformed response, exact abstention ve answerable-abstention vakaları mevcut `test_answer_scorer_v2.py`, `test_f4_unsupported_answer_claims.py`, `test_mesa_adapters.py` ile korunur;
- sıfır required-fact answerable item PASS olamaz; çoklu fact'te hepsi gerekir.

İlgili commitler: `5cbb51e`, `4fd2e56`, `985089a`, test paketi `fd018dc`.

