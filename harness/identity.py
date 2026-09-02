"""
Identity Map validator and resolver for MESA to Source Chunk mappings.
Adheres strictly to Doc 15, Doc 30, Doc 33.
"""

import json
import hashlib
from typing import Optional

class IdentityMap:
    def __init__(self):
        # mesa_chunk_id -> source_chunk_id
        self._mesa_to_source: dict[str, str] = {}
        # source_chunk_id -> set(mesa_chunk_id)
        self._source_to_mesa: dict[str, set[str]] = {}
        self.map_sha256: Optional[str] = None

    def load_from_file(self, filepath: str) -> None:
        hasher = hashlib.sha256()
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                hasher.update(line.encode("utf-8"))
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                mesa_id = row["mesa_chunk_id"]
                src_id = row["source_chunk_id"]
                self._mesa_to_source[mesa_id] = src_id
                self._source_to_mesa.setdefault(src_id, set()).add(mesa_id)
        self.map_sha256 = hasher.hexdigest()

    def add_mapping(self, mesa_chunk_id: str, source_chunk_id: str) -> None:
        self._mesa_to_source[mesa_chunk_id] = source_chunk_id
        self._source_to_mesa.setdefault(source_chunk_id, set()).add(mesa_chunk_id)

    def resolve_source_chunk_id(self, mesa_chunk_id: str) -> str:
        """Resolve MESA public chunk ID to authoritative source chunk ID."""
        return self._mesa_to_source.get(mesa_chunk_id, mesa_chunk_id)

    def resolve_mesa_chunk_ids(self, source_chunk_id: str) -> set[str]:
        """Resolve source chunk ID to all corresponding MESA chunk IDs."""
        return self._source_to_mesa.get(source_chunk_id, {source_chunk_id})
