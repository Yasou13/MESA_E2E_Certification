# reports/releases/

This directory stores the small, sanitized, Git-tracked final certification bundle for each completed final RUN_ID.

Raw/bulky evidence remains under ignored runtime directories. A release bundle must preserve enough hashed metadata, summaries and evidence references to audit the final verdict after the VM is gone.

Required minimum contents are defined in `../../agent-pack/21_EVIDENCE_MANIFEST_AND_INTEGRITY.md`.

Never place secrets, raw credential-bearing HTTP dumps, databases, full bulk corpora or large runtime logs here.
