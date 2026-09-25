"""Fail-closed MESA-to-source identity map loading and resolution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class IdentityMapError(ValueError):
    """Base class for identity integrity failures."""


class IdentityMapValidationError(IdentityMapError):
    """The JSONL input does not conform to the identity row schema."""


class DuplicateMappingError(IdentityMapError):
    """The exact same identity pair appears more than once."""


class ConflictingMappingError(IdentityMapError):
    """One MESA ID points to more than one authoritative source ID."""


class UnknownIdentityError(IdentityMapError):
    """A returned ID cannot be resolved by the frozen identity map."""


class IdentityHashMismatchError(IdentityMapError):
    """The byte-exact identity map differs from its frozen hash."""


class IdentityMapRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mesa_chunk_id: str = Field(min_length=1)
    source_chunk_id: str = Field(min_length=1)
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    delivery_state: Optional[str] = None
    document_id: Optional[str] = None
    remote_mutation_id: Optional[str] = None
    version_id: Optional[str] = None


class IdentityMap:
    def __init__(self) -> None:
        self._mesa_to_source: dict[str, str] = {}
        self._source_to_mesa: dict[str, set[str]] = {}
        self.map_sha256: Optional[str] = None

    @property
    def mapping_count(self) -> int:
        return len(self._mesa_to_source)

    def load_from_file(
        self, filepath: str | Path, expected_sha256: Optional[str] = None
    ) -> None:
        path = Path(filepath)
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            raise IdentityMapValidationError(f"cannot read identity map: {path}") from exc

        observed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if expected_sha256 is not None and observed_sha256 != expected_sha256:
            raise IdentityHashMismatchError(
                "identity map SHA-256 mismatch: "
                f"expected {expected_sha256}, observed {observed_sha256}"
            )

        mesa_to_source: dict[str, str] = {}
        source_to_mesa: dict[str, set[str]] = {}
        seen_pairs: set[tuple[str, str]] = set()
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IdentityMapValidationError("identity map is not valid UTF-8") from exc

        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = IdentityMapRow.model_validate_json(line)
            except ValidationError as exc:
                raise IdentityMapValidationError(
                    f"invalid identity row at line {line_number}: {exc}"
                ) from exc

            pair = (row.mesa_chunk_id, row.source_chunk_id)
            if pair in seen_pairs:
                raise DuplicateMappingError(
                    f"duplicate identity mapping at line {line_number}: {pair!r}"
                )
            previous = mesa_to_source.get(row.mesa_chunk_id)
            if previous is not None and previous != row.source_chunk_id:
                raise ConflictingMappingError(
                    f"conflicting source IDs for {row.mesa_chunk_id!r}: "
                    f"{previous!r} and {row.source_chunk_id!r}"
                )
            seen_pairs.add(pair)
            mesa_to_source[row.mesa_chunk_id] = row.source_chunk_id
            source_to_mesa.setdefault(row.source_chunk_id, set()).add(
                row.mesa_chunk_id
            )

        if not mesa_to_source:
            raise IdentityMapValidationError("identity map contains no mappings")

        self._mesa_to_source = mesa_to_source
        self._source_to_mesa = source_to_mesa
        self.map_sha256 = observed_sha256

    def add_mapping(self, mesa_chunk_id: str, source_chunk_id: str) -> None:
        if not mesa_chunk_id or not source_chunk_id:
            raise IdentityMapValidationError("identity IDs must be non-empty strings")
        pair_exists = self._mesa_to_source.get(mesa_chunk_id)
        if pair_exists == source_chunk_id:
            raise DuplicateMappingError(
                f"duplicate identity mapping: {(mesa_chunk_id, source_chunk_id)!r}"
            )
        if pair_exists is not None:
            raise ConflictingMappingError(
                f"conflicting source IDs for {mesa_chunk_id!r}: "
                f"{pair_exists!r} and {source_chunk_id!r}"
            )
        self._mesa_to_source[mesa_chunk_id] = source_chunk_id
        self._source_to_mesa.setdefault(source_chunk_id, set()).add(mesa_chunk_id)

    def resolve_source_chunk_id(self, chunk_id: str) -> str:
        """Resolve a known MESA or authoritative source chunk ID."""
        if chunk_id in self._mesa_to_source:
            return self._mesa_to_source[chunk_id]
        if chunk_id in self._source_to_mesa:
            return chunk_id
        raise UnknownIdentityError(f"unknown MESA/source chunk ID: {chunk_id!r}")

    def resolve_mesa_chunk_ids(self, source_chunk_id: str) -> set[str]:
        if source_chunk_id not in self._source_to_mesa:
            raise UnknownIdentityError(
                f"unknown authoritative source chunk ID: {source_chunk_id!r}"
            )
        return set(self._source_to_mesa[source_chunk_id])

    def validation_report(self, source_path: str) -> dict[str, object]:
        if self.map_sha256 is None:
            raise IdentityMapValidationError(
                "validation artifact requires a map loaded from a byte-exact file"
            )
        return {
            "schema_version": "1.0",
            "status": "PASS",
            "source_path": source_path,
            "sha256": self.map_sha256,
            "mapping_count": len(self._mesa_to_source),
            "source_id_count": len(self._source_to_mesa),
            "duplicate_count": 0,
            "conflict_count": 0,
        }

    def write_validation_artifact(
        self, output_path: str | Path, source_path: str
    ) -> None:
        payload = self.validation_report(source_path)
        serialized = json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        Path(output_path).write_text(serialized, encoding="utf-8", newline="\n")
