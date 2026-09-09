"""Deterministic form-field mapping (Phase 7).

Maps application-package data (profile + preferences + Phase-6 answers) onto
the raw controls a form exposes. Rules:

* every value comes from an explicit stored fact (profile/preferences) or a
  validated Phase-6 answer -- never invented on the spot;
* sensitive or ambiguous fields (gender, current CTC, relocation, salary)
  are classified REQUIRES_REVIEW and never silently guessed;
* a free-text control that matches no prepared answer is surfaced as a
  NEW QUESTION and stops the run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.application_execution import base

_SPLIT_RE = re.compile(r"\W+")


def norm(value: str | None) -> str:
    return _SPLIT_RE.sub(" ", (value or "").lower()).strip()


def _tokens(value: str | None) -> set[str]:
    return set(norm(value).split())


@dataclass
class ProfileContext:
    """The only read inputs field mapping is allowed to use."""

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    degree: str | None = None
    university: str | None = None
    graduation_year: int | None = None
    experience_level: str | None = None
    notice_period: str | None = None
    work_authorization: str | None = None
    salary_preference: str | None = None
    remote_preference: str | None = None
    employment_types: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)  # norm(question) -> answer
    answers_evidence: dict[str, list] = field(default_factory=dict)

    @property
    def first_name(self) -> str | None:
        return (self.full_name or "").strip().split()[0] if (self.full_name or "").strip() else None

    @property
    def last_name(self) -> str | None:
        parts = (self.full_name or "").strip().split()
        return parts[-1] if len(parts) > 1 else None

    @property
    def skills_text(self) -> str | None:
        return ", ".join(self.skills) if self.skills else None


def build_profile_context(
    profile,
    preferences,
    answers: list[dict] | None = None,
) -> ProfileContext:
    answers = answers or []
    ctx = ProfileContext(
        full_name=getattr(profile, "name", None),
        email=getattr(profile, "email", None),
        phone=getattr(profile, "phone", None),
        city=getattr(profile, "city", None),
        state=getattr(profile, "state", None),
        country=getattr(profile, "country", None),
        linkedin_url=getattr(profile, "linkedin_url", None),
        github_url=getattr(profile, "github_url", None),
        portfolio_url=getattr(profile, "portfolio_url", None),
        degree=getattr(profile, "degree", None) or getattr(profile, "education", None),
        university=getattr(profile, "university", None),
        graduation_year=getattr(profile, "graduation_year", None),
        experience_level=getattr(profile, "experience_level", None),
        notice_period=getattr(profile, "notice_period", None),
        work_authorization=getattr(profile, "work_authorization", None),
        salary_preference=getattr(profile, "salary_preference", None),
        remote_preference=getattr(profile, "remote_preference", None),
        employment_types=list(getattr(preferences, "employment_types", None) or []),
        skills=list(getattr(profile, "skills", None) or []),
        answers={
            norm(a.get("question", "")): (a.get("answer") or "").strip()
            for a in answers
            if norm(a.get("question", ""))
        },
        answers_evidence={
            norm(a.get("question", "")): list(a.get("source_evidence") or [])
            for a in answers
        },
    )
    if ctx.salary_preference is None and preferences is not None:
        lo = getattr(preferences, "salary_min", None)
        hi = getattr(preferences, "salary_max", None)
        if lo is not None or hi is not None:
            parts = [p for p in (lo and f"{lo:.0f}" or None, hi and f"{hi:.0f}" or None) if p]
            if parts:
                ctx.salary_preference = f"{'-'.join(parts)} LPA"
    return ctx


@dataclass
class FieldSpec:
    key: str
    labels: list[str]
    provider: str
    sensitive: bool = False
    kinds: tuple[str, ...] = ("text", "select", "radio")


KIND_ANY = ("text", "textarea", "select", "radio", "date", "checkbox",
            "multi_select", "currency", "autocomplete", "file")

_FIELD_SPECS: list[FieldSpec] = [
    FieldSpec("first_name", ["first name", "first", "given name", "firstname"],
              "first_name"),
    FieldSpec("last_name", ["last name", "last", "sur name", "surname",
                            "family name"], "last_name"),
    FieldSpec("full_name", ["full name", "fullname", "name", "your name"],
              "full_name"),
    FieldSpec("email", ["email", "email address", "e mail", "e-mail",
                        "your email"], "email"),
    FieldSpec("phone", ["phone", "phone number", "mobile", "mobile number",
                        "contact number", "telephone", "phone no"], "phone"),
    FieldSpec("city", ["city", "current city"], "city"),
    FieldSpec("state", ["state", "province"], "state"),
    FieldSpec("country", ["country", "country of residence", "residence"],
              "country", kinds=("text", "select", "radio")),
    FieldSpec("linkedin_url", ["linkedin url", "linkedin profile",
                               "linkedin profile url", "linkedin"], "linkedin_url"),
    FieldSpec("github_url", ["github url", "github profile", "github",
                             "github username"], "github_url"),
    FieldSpec("portfolio_url", ["portfolio url", "portfolio", "website",
                                "personal website", "personal url"], "portfolio_url"),
    FieldSpec("degree", ["degree", "qualification", "highest degree",
                         "education level"], "degree", kinds=("text", "select", "radio")),
    FieldSpec("university", ["university", "college", "institution",
                             "school name"], "university"),
    FieldSpec("graduation_year", ["graduation year", "year of graduation",
                                  "pass out year", "passout year"],
              "graduation_year", kinds=("text", "date")),
    FieldSpec("experience_level", ["experience", "years of experience",
                                   "total experience", "experience level",
                                   "work experience"], "experience_level",
              kinds=("text", "select", "radio")),
    FieldSpec("notice_period", ["notice period", "current notice period",
                                "joining notice", "notice"], "notice_period",
              kinds=("text", "select", "radio")),
    FieldSpec("work_authorization", ["work authorization", "work authorisation",
                                     "authorization to work", "right to work",
                                     "visa status"], "work_authorization",
              kinds=("text", "select", "radio")),
    FieldSpec("salary_preference", ["salary", "expected salary", "expected ctc",
                         "current ctc", "current salary", "annual salary",
                         "compensation", "salary expectation"], "salary_preference",
              sensitive=True),
    FieldSpec("remote_preference", ["remote", "remote preference", "work mode",
                                    "work location preference",
                                    "willing to work remotely"], "remote_preference",
              kinds=("text", "select", "radio")),
    FieldSpec("employment_type", ["employment type", "job type", "position type",
                                  "work type"], "employment_type",
              kinds=("select", "radio")),
    FieldSpec("relocation", ["relocation", "willing to relocate",
                             "ready to relocate", "relocate"], "relocation",
              sensitive=True, kinds=("select", "radio")),
    FieldSpec("gender", ["gender", "sex"], "gender",
              sensitive=True, kinds=("select", "radio")),
    FieldSpec("current_ctc", ["current ctc", "current salary lpa",
                              "current package", "monthly ctc"], "current_ctc",
              sensitive=True),
    FieldSpec("skills", ["skills", "skill set", "technical skills", "key skills"],
              "skills"),
    # Phase 17: advanced control fields
    FieldSpec("terms_acceptance", ["terms", "terms and conditions",
              "i agree to the terms", "terms of service"], "terms_acceptance",
              kinds=("checkbox",)),
    FieldSpec("data_consent", ["consent", "data consent", "i consent",
              "data processing consent"], "data_consent",
              kinds=("checkbox",)),
    FieldSpec("work_preference", ["work preference", "work mode",
              "work location", "remote preference"], "work_preference",
              kinds=("select", "radio")),
    FieldSpec("skills_multi", ["preferred technologies", "tech stack",
              "technologies"], "skills_multi",
              kinds=("multi_select", "text")),
    FieldSpec("availability_date", ["availability date", "start date",
              "available from", "earliest start date"], "availability_date",
              kinds=("date", "text")),
    FieldSpec("graduation_date", ["graduation date", "date of graduation"],
              "graduation_date", kinds=("date", "text")),
    FieldSpec("expected_salary", ["expected salary", "desired compensation",
              "salary expectation"], "expected_salary",
              sensitive=True, kinds=("currency", "text")),
    FieldSpec("city_location", ["city/location"], "city_location",
              kinds=("autocomplete", "text", "select")),
]

# sensitively tracked values: profile *may* hold them but we never guess.
_NEVER_GUESS = {"gender", "relocation", "current_ctc"}

_PROVIDERS = {
    "first_name": lambda c: c.first_name,
    "last_name": lambda c: c.last_name,
    "full_name": lambda c: c.full_name,
    "email": lambda c: c.email,
    "phone": lambda c: c.phone,
    "city": lambda c: c.city,
    "state": lambda c: c.state,
    "country": lambda c: c.country,
    "linkedin_url": lambda c: c.linkedin_url,
    "github_url": lambda c: c.github_url,
    "portfolio_url": lambda c: c.portfolio_url,
    "degree": lambda c: c.degree,
    "university": lambda c: c.university,
    "graduation_year": lambda c: str(c.graduation_year) if c.graduation_year else None,
    "experience_level": lambda c: c.experience_level,
    "notice_period": lambda c: c.notice_period,
    "work_authorization": lambda c: c.work_authorization,
    "salary_preference": lambda c: c.salary_preference,
    "remote_preference": lambda c: c.remote_preference,
    "employment_type": lambda c: c.employment_types[0] if c.employment_types else None,
    "relocation": lambda c: None,
    "gender": lambda c: None,
    "current_ctc": lambda c: None,
    "skills": lambda c: c.skills_text,
    # Phase 17: advanced field providers
    "terms_acceptance": lambda c: None,  # never auto-accept terms
    "data_consent": lambda c: None,  # never auto-consent
    "work_preference": lambda c: c.remote_preference,
    "skills_multi": lambda c: c.skills_text,
    "availability_date": lambda c: None,  # not auto-derived
    "graduation_date": lambda c: str(c.graduation_year) if c.graduation_year else None,
    "expected_salary": lambda c: c.salary_preference,
    "city_location": lambda c: c.city,
}

_LABEL_INDEX: dict[str, str] = {}
for _spec in _FIELD_SPECS:
    for label in _spec.labels:
        _LABEL_INDEX.setdefault(norm(label), _spec.key)
    _LABEL_INDEX.setdefault(norm(_spec.key.replace("_", " ")), _spec.key)

_by_key = {s.key: s for s in _FIELD_SPECS}


def _lookup_key(label: str) -> str | None:
    key = _LABEL_INDEX.get(norm(label))
    if key:
        return key
    toks = _tokens(label)
    # tolerate possessive/extra words but require the label to fully contain a spec label
    best = None
    for spec in _FIELD_SPECS:
        for alias in spec.labels:
            alias_toks = _tokens(alias)
            if alias_toks and alias_toks <= toks:
                best = spec.key
                break
        if best:
            break
    return best


def _answer_for_label(ctx: ProfileContext, label: str) -> tuple[str | None, list[str]]:
    """Best prepared-answer match: shared tokens over the shorter question."""
    label_toks = _tokens(label)
    best_answer, best_evidence, best_score = None, [], 0.0
    for question, answer in ctx.answers.items():
        if not answer:
            continue
        q_toks = _tokens(question)
        if not q_toks:
            continue
        overlap = len(label_toks & q_toks)
        score = overlap / max(1.0, min(len(label_toks), len(q_toks)))
        if score >= 0.66 and score > best_score:
            best_answer, best_score = answer, score
            best_evidence = ctx.answers_evidence.get(question, [])
    return best_answer, best_evidence


@dataclass
class MappedField:
    """One field after mapping: what to fill and why (or why not)."""

    detected: base.DetectedField
    matched_key: str | None = None
    value: str | None = None
    classification: str = base.UNKNOWN
    ambiguity: str | None = None
    warning: str | None = None


@dataclass
class MappingResult:
    fields: list[MappedField] = field(default_factory=list)
    new_questions: list[base.NewQuestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def known_count(self) -> int:
        return sum(1 for f in self.fields if f.classification == base.KNOWN)

    @property
    def review_count(self) -> int:
        return sum(1 for f in self.fields if f.classification == base.REQUIRES_REVIEW)

    @property
    def unknown_required(self) -> list[MappedField]:
        return [
            f
            for f in self.fields
            if f.classification in (base.REQUIRES_REVIEW, base.UNKNOWN) and f.detected.required
        ]

    def map_for(self, key: str) -> list[MappedField]:
        return [f for f in self.fields if f.matched_key == key]


def map_fields(
    detected: list[base.DetectedField],
    ctx: ProfileContext,
) -> MappingResult:
    """Classify and value every detected form control."""
    result = MappingResult()

    for raw in detected:
        if raw.kind == "file":
            result.fields.append(
                MappedField(
                    detected=raw,
                    classification=base.REQUIRES_REVIEW
                    if "resume" in norm(raw.label) or "cv" in norm(raw.label)
                    else base.UNKNOWN,
                    ambiguity=(
                        None
                        if "resume" in norm(raw.label) or "cv" in norm(raw.label)
                        else "File upload is not an approved resume field."
                    ),
                )
            )
            continue

        key = _lookup_key(raw.label)
        if key is None:
            answer, evidence = _answer_for_label(ctx, raw.label)
            if answer is not None:
                result.fields.append(
                    MappedField(
                        detected=raw,
                        matched_key="answer",
                        value=answer,
                        classification=base.KNOWN,
                        warning=f"Answered from prepared answer '{raw.label}'.",
                    )
                )
                continue
            result.fields.append(
                MappedField(
                    detected=raw,
                    classification=base.UNKNOWN,
                    ambiguity="No known field or prepared answer matches this label.",
                )
            )
            result.new_questions.append(base.NewQuestion(label=raw.label))
            continue

        spec = _by_key[key]
        value = _PROVIDERS[key](ctx)
        ambiguity: str | None = None
        classification = base.KNOWN

        if key in _NEVER_GUESS:
            value = None
            classification = base.REQUIRES_REVIEW
            ambiguity = f"{key.replace('_', ' ')} is not tracked; never guessed."
        elif value is None:
            classification = base.REQUIRES_REVIEW
            ambiguity = "No stored value for this field."
        elif spec.kinds and "select" in spec.kinds and raw.options:
            if norm(value) not in {norm(o) for o in raw.options}:
                classification = base.REQUIRES_REVIEW
                ambiguity = f"'{value}' is not an available option."
        elif raw.kind == "date":
            if raw.label and "year" not in norm(raw.label) and str(value).isdigit():
                classification = base.REQUIRES_REVIEW
                ambiguity = "Date field semantics uncertain."

        if classification == base.KNOWN:
            result.fields.append(
                MappedField(
                    detected=raw,
                    matched_key=key,
                    value=value,
                    classification=base.KNOWN,
                )
            )
        else:
            result.fields.append(
                MappedField(
                    detected=raw,
                    matched_key=key,
                    value=value,
                    classification=classification,
                    ambiguity=ambiguity,
                )
            )
            result.warnings.append(
                f"'{raw.label}' needs review: {ambiguity or 'no mapped value'}."
            )

    return result
