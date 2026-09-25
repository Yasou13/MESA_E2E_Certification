"""Config-authoritative deterministic text and identifier normalization."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_NORMALIZATION_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "scoring-normalization.json"
)


class NormalizationTextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unicode_form: Literal["NFC"]
    newline_normalization: Literal["LF"]
    trim_whitespace: bool
    collapse_whitespace: bool
    preserve_words: Literal[True]
    stemming: Literal[False]
    lemmatization: Literal[False]
    translation: Literal[False]


class TurkishCasingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["turkish_casefold"]
    dotted_i_rule: Literal[True]


class IdentifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    law_number_patterns: list[str] = Field(min_length=1)
    article_number_patterns: list[str] = Field(min_length=1)
    article_output_template: str = "madde-{number}{subpart}"
    article_subpart_separator: str = "-"


class AbstentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_answer_marker: str = Field(min_length=1)
    insufficient_evidence_flag: Literal[True]


class NormalizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalization_version: str = Field(min_length=1)
    text: NormalizationTextConfig
    turkish_casing: TurkishCasingConfig
    identifiers: IdentifierConfig
    abstention: AbstentionConfig


class NormalizationAuthority:
    def __init__(self, config: NormalizationConfig, sha256: str, path: Path):
        self.config = config
        self.sha256 = sha256
        self.path = path

    @property
    def version(self) -> str:
        return self.config.normalization_version


def load_normalization_authority(
    path: str | Path = DEFAULT_NORMALIZATION_PATH,
    expected_sha256: Optional[str] = None,
) -> NormalizationAuthority:
    config_path = Path(path)
    raw_bytes = config_path.read_bytes()
    observed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha256 is not None and expected_sha256 != observed_sha256:
        raise ValueError(
            "normalization SHA-256 mismatch: "
            f"expected {expected_sha256}, observed {observed_sha256}"
        )
    payload = json.loads(raw_bytes.decode("utf-8"))
    config = NormalizationConfig.model_validate(payload)
    for pattern in (
        config.identifiers.law_number_patterns
        + config.identifiers.article_number_patterns
    ):
        re.compile(pattern, re.IGNORECASE)
    return NormalizationAuthority(config, observed_sha256, config_path)


@lru_cache(maxsize=1)
def default_normalization_authority() -> NormalizationAuthority:
    return load_normalization_authority(DEFAULT_NORMALIZATION_PATH)


def _authority(
    authority: Optional[NormalizationAuthority],
) -> NormalizationAuthority:
    return authority if authority is not None else default_normalization_authority()


def normalize_text(
    text: str, authority: Optional[NormalizationAuthority] = None
) -> str:
    """Apply exactly the text rules declared by the normalization authority."""
    if not text:
        return ""
    rules = _authority(authority).config.text
    normalized = unicodedata.normalize(rules.unicode_form, text)
    if rules.newline_normalization == "LF":
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if rules.collapse_whitespace:
        lines = [re.sub(r"[ \t]+", " ", line) for line in lines]
    if rules.trim_whitespace:
        lines = [line.strip() for line in lines]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
    return "\n".join(lines)


def turkish_casefold(
    text: str, authority: Optional[NormalizationAuthority] = None
) -> str:
    """Apply the configured Turkish dotted/dotless-I casefold strategy."""
    if not text:
        return ""
    casing = _authority(authority).config.turkish_casing
    if casing.strategy != "turkish_casefold" or not casing.dotted_i_rule:
        raise ValueError("unsupported Turkish casing configuration")
    prepared = text.replace("İ", "i").replace("I", "ı")
    return unicodedata.normalize("NFC", prepared.casefold())


def normalize_law_id(
    text: str, authority: Optional[NormalizationAuthority] = None
) -> str:
    stripped = text.strip()
    patterns = _authority(authority).config.identifiers.law_number_patterns
    for pattern in patterns:
        match = re.match(pattern, stripped, re.IGNORECASE)
        if match:
            return match.group(1)
    return stripped


def normalize_article_id(
    text: str, authority: Optional[NormalizationAuthority] = None
) -> str:
    stripped = text.strip()
    identifiers = _authority(authority).config.identifiers
    for pattern in identifiers.article_number_patterns:
        match = re.match(pattern, stripped, re.IGNORECASE)
        if not match:
            continue
        number = match.group(1)
        raw_subpart = match.group(2) if match.lastindex and match.lastindex >= 2 else None
        subpart = (
            f"{identifiers.article_subpart_separator}{raw_subpart}"
            if raw_subpart
            else ""
        )
        return identifiers.article_output_template.format(
            number=number, subpart=subpart
        )
    return stripped


def get_abstention_marker(
    authority: Optional[NormalizationAuthority] = None,
) -> str:
    return _authority(authority).config.abstention.expected_answer_marker
