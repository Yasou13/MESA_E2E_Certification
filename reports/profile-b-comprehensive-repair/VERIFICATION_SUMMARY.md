# Verification Summary

## Ortam ve baseline

- Başlangıç: `main` = `origin/main` = `0a870e0bd94162d48b2b65102da374d30ee54c57`.
- Dal: `fix/profile-b-comprehensive-certification-hardening`.
- Python: CPython `3.13.12` (uv managed); host `/usr/bin/python3` `3.10.12`.
- uv: `0.10.8`; Pydantic `2.13.5`; pytest `9.1.1`.
- Kilit: `uv.lock`; `uv sync --locked --all-groups` başarılı.
- CI workflow: `.github/workflows/ci.yml`; compile, agent-pack, secret scan, JSON validation, optimized self-test ve pytest.

## RED kayıtları

`UV_CACHE_DIR=/tmp/mesa-e2e-uv-cache uv run --locked pytest -q tests/test_comprehensive_repair_regressions.py`

İlk çalıştırma: `10 failed`. Hatalar: missing `AnswerClaim.fact_ids`; fact-ID oracle tokeninin PASS audit alması; üç bool/numeric type-confusion PASS'i; rank-6, rank-swap ve duplicate source capture'ların kabulü; missing provider digest'in kabulü.

## GREEN kayıtları

| Komut | Sonuç |
|---|---|
| focused comprehensive regressions | `11 passed` (son ek context-contamination vakası dahil) |
| scorer/adapters/official-scoring/context focused set | `49 passed` |
| non-socket broad suite | `552 passed` |
| tam suite, localhost socket izniyle | `565 passed in 13.05s` |
| `python -m compileall -q harness scripts tests` | PASS |
| `scripts/verify_agent_pack.py` | PASS |
| `scripts/check_no_secrets.py` | PASS |
| `scripts/validate_json_artifacts.py` | PASS |
| `python -O -m harness.self_test` | `17/17 passed` |

İlk sandbox çalıştırmasında `543 passed, 11 errors` oluştu; 11 error'ın tamamı `test_official_http_happy_path.py` fixture'ının localhost socket açmasına verilen `PermissionError` idi. Aynı commit ve bağımlılıklarla yetkili localhost çalıştırması `565/565` geçti. Skip/xfailed yoktur.

## Statik ve sözleşme kontrolü

- B0–B14 registry ve `config/profile-b-gates.json` diff'i yok.
- qrels, ground-truth, normalization, official runs ve historical verdict dosyalarında diff yok.
- `uv.lock` değişmedi.
- Ruff/mypy repository'de yapılandırılmamış; `NOT_CONFIGURED`, başarı iddiası yok.
- Official Profile B veya hidden holdout çalıştırılmadı.
- DEV provider/MESA integration çalıştırılmadı; gerçek servisler ve VM collector APIs bu hostta yok.

## Bağımsız post-repair doğrulama

Final rapor commit'inden sonra `git archive HEAD` ile `/tmp` altında temiz export oluşturulacak; locked dependency check, full pytest ve CI eşdeğer kontroller bu export'ta tekrar çalıştırılacaktır. Sonuç ve final SHA bu dosya ile final handoff'ta güncellenecektir.

## CI

Push öncesinde remote CI `NOT_RUN`. Push sonrasında exact final SHA için GitHub Actions sonucu kontrol edilecek; ağ/izin nedeniyle doğrulanamazsa açıkça `UNKNOWN` raporlanacaktır.

