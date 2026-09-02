"""
Deterministic text and identifier normalization for Profile B Certification.
Adheres strictly to config/scoring-normalization.json and Doc 33 Section 10.
"""

import re
import unicodedata

def normalize_text(text: str) -> str:
    """Apply Unicode NFC normalization, LF newlines, and whitespace collapsing."""
    if not text:
        return ""
    # Unicode NFC
    normalized = unicodedata.normalize("NFC", text)
    # Normalize CRLF/CR to LF
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse multiple horizontal whitespace
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    # Strip empty lines from start and end
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)

def turkish_casefold(text: str) -> str:
    """Turkish-aware casefolding handling dotted/dotless I correctly."""
    if not text:
        return ""
    # Pre-process Turkish specific letters before generic casefold
    # I (capital dotless I) -> ı (small dotless I)
    # İ (capital dotted I) -> i (small dotted I)
    text = text.replace("İ", "i").replace("I", "ı")
    return unicodedata.normalize("NFC", text.casefold())

def normalize_law_id(text: str) -> str:
    """Normalize law numbers like '4857 sayılı Kanun', 'Kanun No: 4857' -> '4857'."""
    text = text.strip()
    m = re.match(r"^(?:Kanun\s+No:?\s*)?(\d+)(?:\s+sayılı\s+Kanun)?$", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return text

def normalize_article_id(text: str) -> str:
    """Normalize article identifiers like 'Madde 14', 'm. 14', '14. madde' -> 'madde-14'."""
    text = text.strip()
    m = re.match(r"^(?:Madde|m\.|md\.)\s*(\d+)(?:/([a-z0-9]+))?$", text, re.IGNORECASE)
    if m:
        art_num = m.group(1)
        sub = f"-{m.group(2)}" if m.group(2) else ""
        return f"madde-{art_num}{sub}"
    m2 = re.match(r"^(\d+)\.\s*madde$", text, re.IGNORECASE)
    if m2:
        return f"madde-{m2.group(1)}"
    return text
