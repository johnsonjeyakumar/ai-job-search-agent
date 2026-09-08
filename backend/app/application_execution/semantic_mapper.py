"""Semantic field mapper for application forms (Phase 12).

Maps detected form fields to canonical field concepts using a multi-strategy
approach: deterministic label matching, alias lookup, and semantic similarity.
Every mapping includes confidence and method metadata.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.application_execution import base
from app.application_execution.field_catalog import (
    ALL_FIELD_CONCEPTS,
    MAPPING_ALIAS,
    MAPPING_DETERMINISTIC,
    MAPPING_SEMANTIC,
    MAPPING_USER_VERIFIED,
    SENSITIVITY_HIGH,
    SENSITIVITY_LOW,
    SENSITIVITY_MEDIUM,
    get_sensitivity,
    lookup_concept,
)

_SPLIT_RE = re.compile(r"\W+")


def _norm(text: str | None) -> str:
    return _SPLIT_RE.sub(" ", (text or "").lower()).strip()


def _tokens(text: str | None) -> set[str]:
    return set(_norm(text).split())


# ---------------------------------------------------------------------------
# Confidence levels
# ---------------------------------------------------------------------------
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_UNKNOWN = "UNKNOWN"


@dataclass
class FieldMapping:
    """A single field mapping with full metadata."""

    canonical: str | None = None
    raw_label: str = ""
    confidence: str = CONFIDENCE_UNKNOWN
    source: str = "deterministic"
    mapping_method: str = MAPPING_DETERMINISTIC
    sensitivity: str = SENSITIVITY_LOW
    value: str | None = None
    warning: str | None = None
    ambiguity: str | None = None


@dataclass
class SemanticMappingResult:
    """Result of semantic field mapping for all detected fields."""

    mappings: list[FieldMapping] = field(default_factory=list)
    unmapped: list[base.DetectedField] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def mapped_count(self) -> int:
        return len([m for m in self.mappings if m.canonical is not None])

    @property
    def high_confidence_count(self) -> int:
        return len([m for m in self.mappings if m.confidence == CONFIDENCE_HIGH])

    @property
    def needs_review_count(self) -> int:
        return len([
            m for m in self.mappings
            if m.sensitivity in (SENSITIVITY_MEDIUM, SENSITIVITY_HIGH)
            and m.value is not None
        ])

    @property
    def sensitive_fields(self) -> list[FieldMapping]:
        return [m for m in self.mappings if m.sensitivity == SENSITIVITY_HIGH]


# ---------------------------------------------------------------------------
# Semantic similarity (deterministic, no LLM)
# ---------------------------------------------------------------------------

# Common words to ignore in semantic matching
_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "if", "when", "where", "how",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their",
}

# Semantic groups: words that map to the same concept
_SEMANTIC_GROUPS: dict[str, set[str]] = {
    "name": {"name", "names", "named", "called"},
    "email": {"email", "e-mail", "mail", "electronic", "inbox"},
    "phone": {"phone", "telephone", "mobile", "cell", "contact", "number"},
    "location": {"location", "city", "place", "where", "based", "situated"},
    "company": {"company", "employer", "organization", "firm", "corporation"},
    "experience": {"experience", "experienced", "years", "background", "history"},
    "education": {"education", "academic", "degree", "university", "college", "school"},
    "salary": {"salary", "compensation", "wage", "pay", "ctc", "package"},
    "authorization": {"authorization", "authorised", "authorized", "permit", "legal", "right"},
    "sponsorship": {"sponsorship", "sponsor", "visa", "h1b", "h-1b", "permit"},
    "resume": {"resume", "cv", "curriculum", "vitae"},
    "cover": {"cover", "letter", "motivation", "statement"},
    "portfolio": {"portfolio", "website", "project", "work", "sample"},
    "relocation": {"relocation", "relocate", "move", "willing"},
    "gender": {"gender", "sex", "identity"},
    "availability": {"availability", "available", "start", "join", "immediate"},
    "referral": {"referral", "refer", "referred", "heard"},
}


def _semantic_distance(label_tokens: set[str], alias_tokens: set[str]) -> float:
    """Calculate semantic distance between label and alias tokens."""
    if not alias_tokens or not label_tokens:
        return 0.0

    # Direct token overlap
    direct_overlap = len(label_tokens & alias_tokens)
    if direct_overlap:
        return direct_overlap / max(len(label_tokens), len(alias_tokens))

    # Semantic group overlap
    label_groups: set[str] = set()
    for token in label_tokens:
        for group_name, group_words in _SEMANTIC_GROUPS.items():
            if token in group_words:
                label_groups.add(group_name)

    alias_groups: set[str] = set()
    for token in alias_tokens:
        for group_name, group_words in _SEMANTIC_GROUPS.items():
            if token in group_words:
                alias_groups.add(group_name)

    group_overlap = len(label_groups & alias_groups)
    if group_overlap:
        return (group_overlap * 0.5) / max(len(label_tokens), len(alias_tokens))

    return 0.0


# ---------------------------------------------------------------------------
# Multi-strategy mapping
# ---------------------------------------------------------------------------

def map_field_semantic(
    detected: base.DetectedField,
    user_verified: dict[str, str] | None = None,
) -> FieldMapping:
    """Map a single detected field to a canonical concept.

    Strategy order:
    1. Exact label match (DETERMINISTIC, HIGH confidence)
    2. Alias match (ALIAS, HIGH confidence)
    3. Token containment match (ALIAS, MEDIUM confidence)
    4. Semantic similarity (SEMANTIC, MEDIUM/LOW confidence)
    5. User-verified mapping (USER_VERIFIED, HIGH confidence)
    6. No match (UNKNOWN)
    """
    user_verified = user_verified or {}
    raw_label = detected.label or ""
    normalized = _norm(raw_label)

    # Strategy 1: Exact canonical name match
    for concept in ALL_FIELD_CONCEPTS:
        if normalized == concept.canonical.lower().replace("_", " "):
            return FieldMapping(
                canonical=concept.canonical,
                raw_label=raw_label,
                confidence=CONFIDENCE_HIGH,
                source="exact_canonical",
                mapping_method=MAPPING_DETERMINISTIC,
                sensitivity=get_sensitivity(concept.canonical),
            )

    # Strategy 2: Exact alias match
    concept = lookup_concept(raw_label)
    if concept:
        return FieldMapping(
            canonical=concept.canonical,
            raw_label=raw_label,
            confidence=CONFIDENCE_HIGH,
            source="exact_alias",
            mapping_method=MAPPING_ALIAS,
            sensitivity=get_sensitivity(concept.canonical),
        )

    # Strategy 3: Token containment match
    label_tokens = _tokens(raw_label)
    best_concept = None
    best_score = 0.0
    for concept in ALL_FIELD_CONCEPTS:
        for alias in concept.aliases:
            alias_tokens = _tokens(alias)
            if alias_tokens and alias_tokens <= label_tokens:
                score = len(alias_tokens) / max(len(label_tokens), 1)
                if score > best_score:
                    best_score = score
                    best_concept = concept

    if best_concept and best_score >= 0.3:
        confidence = CONFIDENCE_HIGH if best_score >= 0.7 else CONFIDENCE_MEDIUM
        return FieldMapping(
            canonical=best_concept.canonical,
            raw_label=raw_label,
            confidence=confidence,
            source="token_containment",
            mapping_method=MAPPING_ALIAS,
            sensitivity=get_sensitivity(best_concept.canonical),
        )

    # Strategy 4: Semantic similarity
    best_concept = None
    best_distance = 0.0
    for concept in ALL_FIELD_CONCEPTS:
        for alias in concept.aliases:
            alias_tokens = _tokens(alias)
            distance = _semantic_distance(label_tokens, alias_tokens)
            if distance > best_distance:
                best_distance = distance
                best_concept = concept

    if best_concept and best_distance >= 0.3:
        confidence = CONFIDENCE_MEDIUM if best_distance >= 0.5 else CONFIDENCE_LOW
        return FieldMapping(
            canonical=best_concept.canonical,
            raw_label=raw_label,
            confidence=confidence,
            source="semantic_similarity",
            mapping_method=MAPPING_SEMANTIC,
            sensitivity=get_sensitivity(best_concept.canonical),
        )

    # Strategy 5: User-verified mapping
    if normalized in user_verified:
        verified_canonical = user_verified[normalized]
        return FieldMapping(
            canonical=verified_canonical,
            raw_label=raw_label,
            confidence=CONFIDENCE_HIGH,
            source="user_verified",
            mapping_method=MAPPING_USER_VERIFIED,
            sensitivity=get_sensitivity(verified_canonical),
        )

    # No match
    return FieldMapping(
        canonical=None,
        raw_label=raw_label,
        confidence=CONFIDENCE_UNKNOWN,
        source="unmapped",
        mapping_method="NONE",
        sensitivity=SENSITIVITY_LOW,
        ambiguity="No canonical field concept matches this label.",
    )


def map_fields_semantic(
    detected: list[base.DetectedField],
    user_verified: dict[str, str] | None = None,
) -> SemanticMappingResult:
    """Map all detected fields using semantic mapping."""
    result = SemanticMappingResult()

    for raw in detected:
        mapping = map_field_semantic(raw, user_verified)
        result.mappings.append(mapping)

        if mapping.canonical is None:
            result.unmapped.append(raw)
            result.warnings.append(
                f"Unmapped field: '{raw.label}' - {mapping.ambiguity}"
            )
        elif mapping.sensitivity == SENSITIVITY_HIGH:
            result.warnings.append(
                f"Sensitive field: '{raw.label}' -> {mapping.canonical} "
                f"(requires explicit verification)"
            )

    return result
