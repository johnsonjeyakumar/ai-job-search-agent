"""Phase 6: application preparation engine.

Rules exercised here:
- a package is a preparation artifact (everything stops at APPROVED, nothing
  submits);
- content is built only from real stored facts (no fabrication);
- duplicate protection returns the existing package instead of overwriting;
- regenerating creates a new version and preserves older ones;
- the approval guard blocks a package whose quality gate is FAIL;
- AI output is validated against strict ``extra="forbid"`` contracts and
  score-tainted or fact-fabricating output is rejected with a deterministic
  fallback.
"""
from __future__ import annotations

import asyncio
from datetime import timezone

from sqlalchemy import select

from app.ai.mock import MockAIProvider
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import (
    application_answers_service as answers_service,
)
from app.services import (
    application_evidence_service as evidence_service,
)
from app.services import (
    application_quality_service as quality_service,
)
from app.services import (
    application_validation_service as validation_service,
)
from app.services import (
    cover_letter_service,
    matching_service,
    tailoring_service,
)
from app.services import (
    requirement_extractor as rex,
)
from app.services import (
    resume_selection_service as selection_service,
)

UTC = timezone.utc


def _job(title="Software Developer", company="Acme", **extra):
    return {
        "title": title,
        "company": company,
        "source": "apify",
        "source_job_id": extra.pop("source_job_id", f"sfd-{abs(hash(title))}"),
        "url": extra.pop("url", "https://example.test/job"),
        "location": extra.pop("location", "Chennai, Tamil Nadu"),
        "remote_type": extra.pop("remote_type", "onsite"),
        "employment_type": extra.pop("employment_type", "full_time"),
        "salary": extra.pop("salary", None),
        "description": extra.pop("description", None),
        "requirements": extra.pop("requirements", []),
        "skills": extra.pop("skills", []),
        "posted_date": extra.pop("posted_date", None),
        **extra,
    }


def _seed_profile(db, **extra):
    values = {
        "name": "Test Candidate",
        "email": f"cand-{abs(hash(str(extra))) or 7}@example.test",
        "city": "Chennai",
        "degree": "B.Tech",
        "university": "Anna University",
        "graduation_year": 2024,
        "skills": ["Python", "React", "PostgreSQL"],
        "skills_programming": ["Python", "Java"],
        "skills_frameworks": ["React"],
        "skills_databases": ["PostgreSQL"],
        "experience_level": "0-2 years",
        "preferred_roles": ["Software Developer", "Frontend Developer"],
        "preferred_locations": ["Chennai"],
        "remote_preference": "hybrid",
        "salary_preference": "4-8 LPA",
        "notice_period": "Immediate",
        "work_authorization": "Authorized to work in India.",
        "projects": [
            {
                "name": "Portfolio Site",
                "technologies": ["Python", "React"],
                "description": "A portfolio application.",
            }
        ],
        "internships": [],
        "certifications": [],
        **extra,
    }
    profile = Profile(**values)
    db.add(profile)
    db.flush()
    return profile


def _seed_preferences(db, **extra):
    values = {
        "preferred_locations": ["Chennai"],
        "experience_levels": ["0-2 years"],
        "target_roles": ["Software Developer", "Frontend Developer"],
        "remote_types": ["remote", "hybrid", "onsite"],
        "employment_types": ["full_time", "part_time", "contract", "internship"],
        "salary_min": 4,
        "salary_max": 8,
        **extra,
    }
    prefs = Preferences(**values)
    db.add(prefs)
    db.flush()
    return prefs


def _seed_resume(
    db,
    profile,
    *,
    name="candidate_resume.pdf",
    target_role="Software Developer",
    is_active=True,
    version="v1",
):
    resume = Resume(
        profile_id=profile.id if profile is not None else None,
        name=name,
        target_role=target_role,
        file_path="resumes/candidate.pdf",
        file_name=name,
        file_size=100,
        content_type="application/pdf",
        version=version,
        is_active=is_active,
    )
    db.add(resume)
    db.flush()
    return resume


def _insert_job(db, **extra):
    from app.services import job_service

    result = job_service.insert_jobs(db, [_job(**extra)], source="apify")
    assert result.inserted == 1
    return db.scalar(select(Job).order_by(Job.id.desc()))


def _clean_job(db_session):
    return _insert_job(
        db_session,
        title="Software Developer",
        skills=["Python", "React", "PostgreSQL"],
        experience_required="0-2 years",
        location="Chennai, Tamil Nadu",
        remote_type="onsite",
        employment_type="full_time",
    )


class _FakeAI(MockAIProvider):
    """Configured provider for AI-contract tests (name != 'mock')."""

    name = "fake"

    def __init__(self):
        self.draft_cover_letter_result = None
        self.draft_answers_result = None
        self.suggest_tailoring_result = None
        self.validate_application_result = None

    async def draft_cover_letter(self, job, profile, resume):
        return self.draft_cover_letter_result

    async def draft_application_answers(self, job, profile, resume, questions):
        return self.draft_answers_result

    async def suggest_tailoring(self, job, profile, resume, gaps):
        return self.suggest_tailoring_result

    async def validate_application(self, job, profile, resume, package):
        return self.validate_application_result


# ---------------------------------------------------------------------------
# Resume selection
# ---------------------------------------------------------------------------
class TestResumeSelection:
    def test_prefers_target_role_match(self, db_session):
        profile = _seed_profile(db_session)
        _seed_preferences(db_session)
        _seed_resume(db_session, profile, name="a.pdf", target_role="Software Developer")
        _seed_resume(db_session, profile, name="b.pdf", target_role="Accounting Assistant")
        job = _clean_job(db_session)
        resumes = list(db_session.scalars(select(Resume).order_by(Resume.id)))
        selection = selection_service.select_resume(db_session, job, resumes, profile)
        assert selection.selected is not None
        assert selection.selected.target_role == "Software Developer"

    def test_no_resumes_is_none(self, db_session):
        job = _clean_job(db_session)
        selection = selection_service.select_resume(db_session, job, [], None)
        assert selection.selected_id is None
        assert any("No resumes" in line for line in selection.explanation)

    def test_active_bonus_breaks_ties(self, db_session):
        profile = _seed_profile(db_session)
        _seed_preferences(db_session)
        _seed_resume(
            db_session, profile, name="inactive-exact.pdf",
            target_role="Software Developer", is_active=False,
        )
        _seed_resume(
            db_session, profile, name="active-partial.pdf",
            target_role="Developer", is_active=True,
        )
        job = _clean_job(db_session)
        resumes = list(db_session.scalars(select(Resume).order_by(Resume.id)))
        selection = selection_service.select_resume(db_session, job, resumes, profile)
        assert selection.selected.name == "active-partial.pdf"

    def test_filename_never_scores(self, db_session):
        profile = _seed_profile(db_session)
        _seed_preferences(db_session)
        # Identical metadata, wildly different names: the choice must be
        # deterministic (latest inserted wins), never based on the filename.
        _seed_resume(
            db_session, profile,
            name="quiet-and-clean.pdf", target_role="Software Developer",
        )
        _seed_resume(
            db_session, profile,
            name="zz-misleading-999.pdf", target_role="Software Developer",
        )
        job = _clean_job(db_session)
        resumes = list(db_session.scalars(select(Resume).order_by(Resume.id)))
        selection = selection_service.select_resume(db_session, job, resumes, profile)
        assert selection.selected.resume_id == resumes[-1].id
        assert not any("misleading" in r for cand in selection.candidates for r in cand.reasons)


# ---------------------------------------------------------------------------
# Evidence mapping
# ---------------------------------------------------------------------------
class TestEvidenceMapping:
    def _entries(self, db_session, job):
        bundle = rex.extract_job_requirements(job)
        computation = matching_service.calculate(db_session, job, bundle=bundle)
        return evidence_service.build_evidence_entries(
            bundle=bundle,
            buckets={
                "matched_requirements": computation.matched_requirements,
                "partial_requirements": computation.partial_requirements,
                "missing_requirements": computation.missing_requirements,
                "unknown_requirements": computation.unknown_requirements,
            },
            profile=db_session.scalar(select(Profile).order_by(Profile.id).limit(1)),
            preferences=db_session.scalar(select(Preferences).order_by(Preferences.id).limit(1)),
            resume=db_session.scalar(select(Resume).order_by(Resume.id).limit(1)),
            selection=None,
        )

    def test_matched_and_missing_skills(self, db_session):
        profile = _seed_profile(db_session)
        _seed_preferences(db_session)
        _seed_resume(db_session, profile)
        job = _insert_job(
            db_session, skills=["Python", "React", "Kubernetes"], employment_type="full_time"
        )
        entries = self._entries(db_session, job)
        by_term = {e.requirement: e for e in entries}
        assert by_term["Python"].status == "MATCHED"
        assert by_term["Python"].source in ("profile", "project", "resume")
        assert "Python" in (by_term["Python"].evidence or "")
        assert by_term["Kubernetes"].status == "MISSING_EVIDENCE"
        assert by_term["Kubernetes"].evidence is None

    def test_unverifiable_requirement_is_unknown(self, db_session):
        # A salary demand with no expectation on file cannot be verified --
        # the engine must say UNKNOWN, never invent a verdict.
        job = _insert_job(db_session, title="Software Developer", salary="5-10 LPA")
        entries = self._entries(db_session, job)
        salary = next(e for e in entries if e.category == "salary")
        assert salary.status == "UNKNOWN"
        assert salary.evidence is None
        assert not any(e.status == "MATCHED" for e in entries if e.category == "salary")

    def test_evidence_carries_real_sources(self, db_session):
        profile = _seed_profile(db_session)
        _seed_preferences(db_session)
        _seed_resume(db_session, profile)
        job = _insert_job(db_session, skills=["Python"], location="Chennai, Tamil Nadu")
        entries = self._entries(db_session, job)
        location = next(e for e in entries if e.category == "location")
        assert location.status == "MATCHED"
        assert "Chennai" in (location.evidence or "")


# ---------------------------------------------------------------------------
# Tailoring suggestions
# ---------------------------------------------------------------------------
class TestTailoring:
    def _evidence(self, *items):
        return [
            evidence_service.EvidenceEntry(
                requirement=req,
                category=cat,
                status=status,
                evidence=evidence,
            )
            for req, cat, status, evidence in items
        ]

    def test_missing_evidence_is_do_not_claim(self, db_session):
        job = _clean_job(db_session)
        suggestions = asyncio.run(
            tailoring_service.generate_tailoring_suggestions(
                db_session,
                job,
                None,
                None,
                self._evidence(("Kubernetes", "skill", "MISSING_EVIDENCE", None)),
            )
        )
        assert suggestions and suggestions[0].review_status == "SAFE_TO_APPLY"
        assert "Do not claim" in suggestions[0].suggested_wording

    def test_unknown_requires_user_review(self, db_session):
        job = _clean_job(db_session)
        suggestions = asyncio.run(
            tailoring_service.generate_tailoring_suggestions(
                db_session,
                job,
                None,
                None,
                self._evidence(("Role fit", "role", "UNKNOWN", None)),
            )
        )
        assert suggestions and suggestions[0].review_status == "NEEDS_USER_REVIEW"

    def test_matched_produces_no_suggestion(self, db_session):
        job = _clean_job(db_session)
        suggestions = asyncio.run(
            tailoring_service.generate_tailoring_suggestions(
                db_session,
                job,
                None,
                None,
                self._evidence(("Python", "skill", "MATCHED", "Profile lists the skill.")),
            )
        )
        assert suggestions == []

    def test_ai_wording_asserting_new_fact_is_downgraded(self, monkeypatch, db_session):
        ai = _FakeAI()
        ai.suggest_tailoring_result = [
            {
                "requirement": "Docker",
                "suggested_wording": "Add Docker Kubernetes to the resume headline.",
                "reason": "gap",
                "review_status": "SAFE_TO_APPLY",
                "confidence": 0.9,
            }
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        job = _clean_job(db_session)
        suggestions = asyncio.run(
            tailoring_service.generate_tailoring_suggestions(db_session, job, None, None, [])
        )
        assert suggestions
        assert all(s.review_status == "NEEDS_USER_REVIEW" for s in suggestions)

    def test_ai_score_tainted_suggestion_is_rejected(self, monkeypatch, db_session):
        ai = _FakeAI()
        ai.suggest_tailoring_result = [
            {
                "requirement": "Docker",
                "suggested_wording": "A gentle nudge.",
                "review_status": "SAFE_TO_APPLY",
                "score": 99,
            }
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        job = _clean_job(db_session)
        suggestions = asyncio.run(
            tailoring_service.generate_tailoring_suggestions(db_session, job, None, None, [])
        )
        assert suggestions == []


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
class TestAnswers:
    def test_clean_profile_covers_all_categories(self, db_session):
        profile = _seed_profile(db_session)
        preferences = _seed_preferences(db_session)
        resume = _seed_resume(db_session, profile)
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(
            db_session, job, profile, preferences, resume, resume.target_role
        )
        assert {d.category for d in drafts} == set(answers_service.REQUIRED_CATEGORIES)
        assert all(d.answer for d in drafts)
        assert all(d.validation_status == "VALID" for d in drafts)

    def test_missing_profile_never_fabricates(self, db_session):
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(db_session, job, None, None, None, None)
        assert {d.category for d in drafts} == set(answers_service.REQUIRED_CATEGORIES)
        assert all(not d.answer for d in drafts)
        assert all(d.validation_status == "NEEDS_REVIEW" for d in drafts)

    def test_ai_answer_with_new_fact_is_rejected(self, monkeypatch, db_session):
        profile = _seed_profile(db_session)
        preferences = _seed_preferences(db_session)
        resume = _seed_resume(db_session, profile)
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(
            db_session, job, profile, preferences, resume, resume.target_role
        )
        target = next(d for d in drafts if d.category == "motivation")
        ai = _FakeAI()
        ai.draft_answers_result = [
            {
                "category": "motivation",
                "question": target.question,
                "answer": "I have 5 years of experience and used Terraform at Infosys.",
                "source_evidence": [],
                "confidence": 0.9,
            }
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        refined = asyncio.run(
            answers_service.refine_answers_with_ai(job, profile, resume, drafts)
        )
        updated = next(d for d in refined if d.category == "motivation")
        assert updated.validation_status == "INVALID"
        assert updated.answer != "I have 5 years of experience and used Terraform at Infosys."

    def test_clean_ai_answer_is_merged(self, monkeypatch, db_session):
        profile = _seed_profile(db_session)
        preferences = _seed_preferences(db_session)
        resume = _seed_resume(db_session, profile)
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(
            db_session, job, profile, preferences, resume, resume.target_role
        )
        target = next(d for d in drafts if d.category == "experience")
        ai = _FakeAI()
        ai.draft_answers_result = [
            {
                "category": "experience",
                "question": target.question,
                "answer": "I have 0-2 years of internship experience at Acme Labs.",
                "source_evidence": [
                    "Profile.experience_level: 0-2 years",
                    "Profile.internships: Software Engineer Intern at Acme Labs",
                ],
                "confidence": 0.8,
            }
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        refined = asyncio.run(
            answers_service.refine_answers_with_ai(job, profile, resume, drafts)
        )
        updated = next(d for d in refined if d.category == "experience")
        assert updated.validation_status == "VALID"
        assert "Acme Labs" in updated.answer

    def test_ai_score_key_is_rejected(self, monkeypatch, db_session):
        profile = _seed_profile(db_session)
        preferences = _seed_preferences(db_session)
        resume = _seed_resume(db_session, profile)
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(
            db_session, job, profile, preferences, resume, resume.target_role
        )
        target = next(d for d in drafts if d.category == "motivation")
        ai = _FakeAI()
        ai.draft_answers_result = [
            {
                "category": "motivation",
                "question": target.question,
                "answer": "A sincere interest.",
                "match_score": 99,
            }
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        refined = asyncio.run(
            answers_service.refine_answers_with_ai(job, profile, resume, drafts)
        )
        updated = next(d for d in refined if d.category == "motivation")
        assert updated.answer == target.answer  # unchanged deterministic draft

    def test_ai_drafts_are_evidence_isolated(self, monkeypatch, db_session):
        # Draft A carries real evidence and must validate. Draft B claims the
        # same kind of fact with NO evidence: evidence from Draft A (or from
        # deterministic drafts) must never lend support to Draft B.
        profile = _seed_profile(db_session)
        preferences = _seed_preferences(db_session)
        resume = _seed_resume(db_session, profile)
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(
            db_session, job, profile, preferences, resume, resume.target_role
        )
        experience = next(d for d in drafts if d.category == "experience")
        motivation = next(d for d in drafts if d.category == "motivation")
        ai = _FakeAI()
        ai.draft_answers_result = [
            {
                "category": "experience",
                "question": experience.question,
                "answer": "I have 0-2 years of internship experience at Acme Labs.",
                "source_evidence": [
                    "Profile.experience_level: 0-2 years",
                    "Profile.internships: Software Engineer Intern at Acme Labs",
                ],
                "confidence": 0.8,
            },
            {
                "category": "motivation",
                "question": motivation.question,
                "answer": "This role suits my 5 years of Python experience.",
                "source_evidence": [],
                "confidence": 0.9,
            },
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        refined = asyncio.run(
            answers_service.refine_answers_with_ai(job, profile, resume, drafts)
        )
        by_cat = {d.category: d for d in refined}
        assert by_cat["experience"].validation_status == "VALID"
        assert "Acme Labs" in by_cat["experience"].answer
        # Draft A's "years" evidence must not insulate Draft B's claim.
        assert by_cat["motivation"].validation_status == "INVALID"
        assert by_cat["motivation"].answer == motivation.answer  # fallback kept

    def test_ai_drafts_match_own_evidence_only(self, monkeypatch, db_session):
        # Draft B reuses Draft A's evidence copy verbatim. The evidence does
        # not reference AWS, so B's AWS claim stays unsupported -- evidence
        # cannot be borrowed across drafts.
        profile = _seed_profile(db_session)
        preferences = _seed_preferences(db_session)
        resume = _seed_resume(db_session, profile)
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(
            db_session, job, profile, preferences, resume, resume.target_role
        )
        experience = next(d for d in drafts if d.category == "experience")
        motivation = next(d for d in drafts if d.category == "motivation")
        ai = _FakeAI()
        ai.draft_answers_result = [
            {
                "category": "experience",
                "question": experience.question,
                "answer": "I have 0-2 years of internship experience at Acme Labs.",
                "source_evidence": [
                    "Profile.experience_level: 0-2 years",
                    "Profile.internships: Software Engineer Intern at Acme Labs",
                ],
                "confidence": 0.8,
            },
            {
                "category": "motivation",
                "question": motivation.question,
                "answer": "This role suits my AWS expertise.",
                "source_evidence": [
                    "Profile.experience_level: 0-2 years",
                    "Profile.internships: Software Engineer Intern at Acme Labs",
                ],
                "confidence": 0.9,
            },
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        refined = asyncio.run(
            answers_service.refine_answers_with_ai(job, profile, resume, drafts)
        )
        by_cat = {d.category: d for d in refined}
        assert by_cat["experience"].validation_status == "VALID"
        # Draft A's evidence is a copy, not shared state.
        assert by_cat["motivation"].validation_status == "INVALID"
        assert by_cat["motivation"].answer == motivation.answer  # fallback kept

    def test_ai_empty_and_malformed_payload_falls_back(self, monkeypatch, db_session):
        profile = _seed_profile(db_session)
        preferences = _seed_preferences(db_session)
        resume = _seed_resume(db_session, profile)
        job = _clean_job(db_session)
        drafts = answers_service.draft_answers(
            db_session, job, profile, preferences, resume, resume.target_role
        )
        target = next(d for d in drafts if d.category == "motivation")
        ai = _FakeAI()
        ai.draft_answers_result = [
            "not-a-dict",
            42,
            {"category": "motivation", "question": target.question, "answer": 7},
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        refined = asyncio.run(
            answers_service.refine_answers_with_ai(job, profile, resume, drafts)
        )
        updated = next(d for d in refined if d.category == "motivation")
        assert updated.answer == target.answer  # unchanged deterministic draft


# ---------------------------------------------------------------------------
# Truth and consistency validation
# ---------------------------------------------------------------------------
class _answers:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def build(self):
        return [
            {"category": c, "answer": a, "validation_status": "VALID"}
            for c, a in self.kwargs.items()
        ]


class TestValidation:
    def _run(self, db_session, *, answers=None, cover_letter=None, resume=None):
        profile = db_session.scalar(select(Profile).order_by(Profile.id).limit(1))
        preferences = db_session.scalar(select(Preferences).order_by(Preferences.id).limit(1))
        job = db_session.scalar(select(Job).order_by(Job.id).limit(1))
        return validation_service.validate_package_content(
            job=job,
            profile=profile,
            preferences=preferences,
            resume=resume,
            answers=answers or [],
            cover_letter=cover_letter,
            tailoring_suggestions=[],
        )

    def test_clean_content_has_no_open_findings(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        resume = _seed_resume(db_session, db_session.scalar(select(Profile)))
        _clean_job(db_session)
        findings = self._run(
            db_session,
            answers=_answers(
                motivation="I am applying for this role at Acme (Software Developer).",
                experience="0-2 years experience.",
                **{"technical skills": "I bring Python, React, PostgreSQL."},
                project="Built Portfolio Site (Python, React).",
                education="B.Tech at Anna University.",
                relocation="Based in Chennai. I am available for this location.",
                remote="Preferred work mode: hybrid.",
                salary="My expectation is around 4-8 LPA.",
                **{"notice period": "I have a notice period of Immediate."},
                **{"work authorization": "Authorized to work in India."},
                availability="I can join after my notice period (Immediate).",
            ).build(),
            resume=resume,
        )
        assert findings == []

    def test_fabricated_years_is_invalid(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        resume = _seed_resume(db_session, db_session.scalar(select(Profile)))
        _clean_job(db_session)
        findings = self._run(
            db_session,
            answers=_answers(experience="I bring 8 years of experience in Python.").build(),
            resume=resume,
        )
        assert any(f.status == "INVALID" and f.check == "experience" for f in findings)

    def test_fabricated_skill_needs_review(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        _clean_job(db_session)
        findings = self._run(
            db_session,
            answers=_answers(
                **{
                    "technical skills": "I am an expert in Docker."
                }
            ).build(),
        )
        assert any(
            f.check == "skill_claim" and f.status == "NEEDS_REVIEW" for f in findings
        )

    def test_fabricated_certification_needs_review(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        _clean_job(db_session)
        findings = self._run(
            db_session,
            answers=_answers(
                motivation="I am applying for this role at Acme (Software Developer).",
                experience="I hold an AWS Certified Solutions Architect credential.",
            ).build(),
        )
        assert any(f.check == "certification_claim" for f in findings)

    def test_fabricated_employer_needs_review(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        _clean_job(db_session)
        findings = self._run(
            db_session,
            answers=_answers(experience="I worked at Infosys as a backend developer.").build(),
        )
        assert any(f.check == "employer_claim" for f in findings)
        assert all(f.status != "INVALID" for f in findings)

    def test_target_company_is_not_an_employer_claim(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        resume = _seed_resume(db_session, db_session.scalar(select(Profile)))
        _clean_job(db_session)
        findings = self._run(
            db_session,
            answers=_answers(
                motivation="I am applying for this role at Acme (Software Developer)."
            ).build(),
            resume=resume,
        )
        assert not any(f.check == "employer_claim" for f in findings)

    def test_fabricated_location_needs_review(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        _clean_job(db_session)
        findings = self._run(
            db_session, answers=_answers(relocation="I am currently in Bengaluru.").build()
        )
        assert any(f.check == "location_claim" for f in findings)

    def test_claiming_higher_degree_needs_review(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        _clean_job(db_session)
        findings = self._run(
            db_session, answers=_answers(education="I hold a Ph.D from IIT Madras.").build()
        )
        assert any(f.check == "education_claim" for f in findings)

    def test_missing_resume_is_flagged(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        _clean_job(db_session)
        findings = self._run(
            db_session, answers=_answers(motivation="Something.").build(), resume=None
        )
        assert any(f.section == "package" and f.check == "selected_resume" for f in findings)


# ---------------------------------------------------------------------------
# Cover letters
# ---------------------------------------------------------------------------
class TestCoverLetter:
    async def _gen(self, db_session, job, profile, resume, requested):
        return await cover_letter_service.generate_cover_letter_for_package(
            db_session, job, profile, resume, [], requested=requested
        )

    def test_not_requested_is_skipped(self, db_session):
        job = _clean_job(db_session)
        profile = _seed_profile(db_session)
        result = asyncio.run(self._gen(db_session, job, profile, None, requested=False))
        assert result.status == "skipped"
        assert result.text is None

    def test_mock_uses_deterministic_template(self, db_session):
        job = _clean_job(db_session)
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile)
        result = asyncio.run(self._gen(db_session, job, profile, resume, requested=True))
        assert result.status == "generated"
        assert "Software Developer" in result.text
        assert "Acme" in result.text

    def test_clean_ai_letter_is_kept(self, monkeypatch, db_session):
        ai = _FakeAI()
        ai.draft_cover_letter_result = {"text": "Dear Team, I am genuinely interested in the role."}
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        job = _clean_job(db_session)
        profile = _seed_profile(db_session)
        result = asyncio.run(self._gen(db_session, job, profile, None, requested=True))
        assert result.status == "generated"
        assert "genuinely interested" in result.text

    def test_fabricating_ai_letter_needs_review(self, monkeypatch, db_session):
        ai = _FakeAI()
        ai.draft_cover_letter_result = {
            "text": "I have 5 years of experience building Terraform pipelines at Oracle."
        }
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        job = _clean_job(db_session)
        profile = _seed_profile(db_session)
        result = asyncio.run(self._gen(db_session, job, profile, None, requested=True))
        assert result.status == "needs_review"

    def test_score_tainted_ai_letter_falls_back(self, monkeypatch, db_session):
        ai = _FakeAI()
        ai.draft_cover_letter_result = {"text": "Dear Team, hi.", "match_score": 99}
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)
        job = _clean_job(db_session)
        profile = _seed_profile(db_session)
        result = asyncio.run(self._gen(db_session, job, profile, None, requested=True))
        assert result.status == "generated"
        assert "Dear Hiring Team" in result.text


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------
class TestQualityGate:
    def _finding(self, status):
        return validation_service.ValidationFinding(
            section="answers", check="x", status=status, message="m"
        )

    def test_fail_on_invalid_finding(self):
        result = quality_service.evaluate(
            answers=[], findings=[self._finding(validation_service.INVALID)],
            selected_resume_id=1, cover_letter_status="skipped", match_score=None,
        )
        assert result.gate == "FAIL"
        assert result.readiness == "NOT_READY"

    def test_pass_when_clean_and_complete(self):
        result = quality_service.evaluate(
            answers=[{"category": c, "answer": "ok"} for c in answers_service.REQUIRED_CATEGORIES],
            findings=[], selected_resume_id=1, cover_letter_status="skipped", match_score=None,
        )
        assert result.gate == "PASS"
        assert result.readiness == "READY"

    def test_needs_review_when_unanswered(self):
        result = quality_service.evaluate(
            answers=[], findings=[], selected_resume_id=1,
            cover_letter_status="skipped", match_score=None,
        )
        assert result.gate == "NEEDS_REVIEW"

    def test_needs_review_without_resume(self):
        result = quality_service.evaluate(
            answers=[{"category": c, "answer": "ok"} for c in answers_service.REQUIRED_CATEGORIES],
            findings=[], selected_resume_id=None,
            cover_letter_status="skipped", match_score=None,
        )
        assert result.gate == "NEEDS_REVIEW"

    def test_lock_requires_resume(self, db_session):
        profile = _seed_profile(db_session)
        _seed_preferences(db_session)
        _seed_resume(db_session, profile)
        job = _insert_job(db_session, title="Software Developer", skills=["Python"])

        # A package built without a resume must NOT be READY.
        bundle = rex.extract_job_requirements(job)
        computation = matching_service.calculate(db_session, job, bundle=bundle)
        entries = evidence_service.build_evidence_entries(
            bundle=bundle,
            buckets={"matched_requirements": computation.matched_requirements},
            profile=profile,
            preferences=db_session.scalar(select(Preferences)),
            resume=None,
            selection=None,
        )
        assert any(e.status == "MATCHED" for e in entries)  # sanity: computation is real

        drafts = answers_service.draft_answers(db_session, job, profile, None, None, None)
        findings = validation_service.validate_package_content(
            job=job, profile=profile, preferences=None, resume=None,
            answers=[a.to_dict() for a in drafts], cover_letter=None,
            tailoring_suggestions=[],
        )
        result = quality_service.evaluate(
            answers=[a.to_dict() for a in drafts], findings=findings,
            selected_resume_id=None, cover_letter_status="skipped", match_score=None,
        )
        assert result.gate == "NEEDS_REVIEW"
        assert result.readiness == "NOT_READY"


# ---------------------------------------------------------------------------
# Package orchestration + API
# ---------------------------------------------------------------------------
class TestPackagePipeline:
    def test_prepare_creates_ready_package(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)

        resp = client.post("/applications/prepare", json={"job_id": job.id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["created"] is True
        summary = body["package"]
        assert summary["status"] == "READY_FOR_REVIEW"
        assert summary["quality_gate"] == "PASS"
        assert summary["readiness"] == "READY"
        assert summary["resume_name"] == "candidate_resume.pdf"
        assert summary["match_score"] is not None

        package_id = summary["id"]

        list_resp = client.get("/applications")
        assert list_resp.status_code == 200
        assert any(item["id"] == package_id for item in list_resp.json())

        detail = client.get(f"/applications/{package_id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == package_id

        preview = client.get(f"/applications/{package_id}/preview")
        assert preview.status_code == 200
        data = preview.json()
        assert data["job"]["title"] == "Software Developer"
        assert len(data["answers"]) == 11
        assert data["quality_gate"] == "PASS"
        assert data["resume_selection"]["selected_resume_id"] is not None
        assert data["validation_findings"] == []

    def test_duplicate_prepare_returns_existing(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)

        first = client.post("/applications/prepare", json={"job_id": job.id})
        assert first.json()["created"] is True
        second = client.post("/applications/prepare", json={"job_id": job.id})
        assert second.status_code == 200
        body = second.json()
        assert body["created"] is False
        assert body["duplicate_disclaimer"]
        assert body["package"]["id"] == first.json()["package"]["id"]

    def test_approve_marks_approved(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)
        package_id = client.post(
            "/applications/prepare", json={"job_id": job.id}
        ).json()["package"]["id"]

        resp = client.post(f"/applications/{package_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["package"]["status"] == "APPROVED"

    def test_validate_demotes_fabricated_edit_to_fail(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)
        package_id = client.post(
            "/applications/prepare", json={"job_id": job.id}
        ).json()["package"]["id"]
        preview = client.get(f"/applications/{package_id}/preview").json()
        experience = next(a for a in preview["answers"] if a["category"] == "experience")

        updated = client.put(
            f"/applications/{package_id}/answers/{experience['id']}",
            json={"answer_text": "I bring 8 years of experience in Python."},
        )
        assert updated.status_code == 200
        assert updated.json()["validation_status"] == "NEEDS_REVIEW"

        validated = client.post(f"/applications/{package_id}/validate")
        assert validated.status_code == 200
        assert validated.json()["package"]["quality_gate"] == "FAIL"
        assert validated.json()["package"]["status"] == "NEEDS_REVIEW"

        blocked = client.post(f"/applications/{package_id}/approve")
        assert blocked.status_code == 409

    def test_reject_edit_after_approval(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)
        package_id = client.post(
            "/applications/prepare", json={"job_id": job.id}
        ).json()["package"]["id"]
        client.post(f"/applications/{package_id}/approve")
        preview = client.get(f"/applications/{package_id}/preview").json()
        motivation = next(a for a in preview["answers"] if a["category"] == "motivation")
        resp = client.put(
            f"/applications/{package_id}/answers/{motivation['id']}",
            json={"answer_text": "Something else."},
        )
        assert resp.status_code == 409

    def test_regenerate_creates_new_version_and_preserves_old(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)
        first = client.post("/applications/prepare", json={"job_id": job.id}).json()["package"]
        regenerated = client.post(f"/applications/{first['id']}/regenerate")
        assert regenerated.status_code == 200
        second = regenerated.json()["package"]
        assert second["version"] == first["version"] + 1
        assert second["id"] != first["id"]

        latest = client.get("/applications").json()
        assert len(latest) == 1
        assert latest[0]["id"] == second["id"]

        history = client.get("/applications", params={"include_history": True}).json()
        assert {item["version"] for item in history} == {1, 2}

        old_ok = client.get(f"/applications/{first['id']}")
        assert old_ok.status_code == 200
        assert old_ok.json()["version"] == first["version"]

    def test_archive_allows_new_prepare(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)
        first = client.post("/applications/prepare", json={"job_id": job.id}).json()["package"]
        archived = client.post(f"/applications/{first['id']}/archive")
        assert archived.status_code == 200
        assert archived.json()["package"]["status"] == "ARCHIVED"

        second = client.post("/applications/prepare", json={"job_id": job.id})
        assert second.json()["created"] is True
        assert second.json()["package"]["id"] != first["id"]

    def test_cover_letter_optional_and_editable(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)
        package_id = client.post(
            "/applications/prepare",
            json={"job_id": job.id, "include_cover_letter": True},
        ).json()["package"]["id"]
        preview = client.get(f"/applications/{package_id}/preview").json()
        assert preview["cover_letter_status"] == "generated"
        assert preview["cover_letter"]

        resp = client.put(
            f"/applications/{package_id}/cover-letter",
            json={"text": "My own cover letter for Acme."},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == package_id

    def test_prepare_missing_job_404(self, client_session):
        client, session = client_session
        resp = client.post("/applications/prepare", json={"job_id": 999999})
        assert resp.status_code == 404

    def test_preview_missing_package_404(self, client_session):
        client, session = client_session
        assert client.get("/applications/999999/preview").status_code == 404


# ---------------------------------------------------------------------------
# AI output contract at the package level
# ---------------------------------------------------------------------------
class TestAIOutputContractPhase6:
    def test_invalid_ai_finding_is_invalid_but_score_key_rejected(
        self, monkeypatch, client_session
    ):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _clean_job(session)

        ai = _FakeAI()
        ai.validate_application_result = [
            {
                "check": "experience",
                "status": "INVALID",
                "message": "Claims unknown years.",
            },
            {
                "check": "skills",
                "status": "NEEDS_REVIEW",
                "message": "Check the skills list.",
                "score": 0.99,
            },
        ]
        monkeypatch.setattr("app.ai.registry.get_provider", lambda: ai)

        resp = client.post("/applications/prepare", json={"job_id": job.id})
        assert resp.status_code == 200
        package_id = resp.json()["package"]["id"]
        preview = client.get(f"/applications/{package_id}/preview").json()
        checks = {f["check"]: f["status"] for f in preview["validation_findings"]}
        assert checks["experience"] == "INVALID"
        # The score-tainted finding must have been rejected wholesale.
        assert "skills" not in checks
        assert resp.json()["package"]["quality_gate"] == "FAIL"
