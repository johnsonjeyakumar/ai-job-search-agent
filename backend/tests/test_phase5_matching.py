"""Phase 5: personal matching, opportunity decisions, and recommendations."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.job import Job, JobMatch
from app.models.opportunity import OpportunityScore
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.services import (
    job_service,
    matches_service,
    matching_service,
    opportunity_service,
)
from app.services import (
    requirement_extractor as rex,
)
from app.services import (
    skill_normalizer as norm,
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


def _insert_job(db, **extra):
    result = job_service.insert_jobs(db, [_job(**extra)], source="apify")
    assert result.inserted == 1
    return db.scalar(select(Job).order_by(Job.id.desc()))


# ---------------------------------------------------------------------------
# Skill normalization
# ---------------------------------------------------------------------------
class TestSkillNormalizer:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("React.js", "React"),
            ("ReactJS", "React"),
            ("react js", "React"),
            ("Postgres", "PostgreSQL"),
            ("postgresql", "PostgreSQL"),
            ("nodejs", "Node.js"),
            ("Express", "Express"),
            ("SpringBoot", "Spring Boot"),
            ("Kubernets", "kubernets"),
        ],
    )
    def test_canonicalize(self, raw, expected):
        assert norm.canonicalize(raw) == expected

    def test_normalize_key(self):
        assert norm.normalize("  React.Js! ") == "react.js"


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------
class TestRequirementExtractor:
    def test_structured_skills_come_through(self, db_session):
        job = _insert_job(
            db_session,
            skills=["React", "PostgreSQL", "Docker"],
            description="No extra signals.",
        )
        bundle = rex.extract_job_requirements(job)
        assert {r.canonical for r in bundle.skills} == {"React", "PostgreSQL", "Docker"}

    def test_description_scans_skill_intros(self, db_session):
        job = _insert_job(
            db_session,
            description=(
                "We need a developer with strong knowledge of React and "
                "PostgreSQL. Experience writing REST APIs is a plus."
            ),
        )
        bundle = rex.extract_job_requirements(job)
        canon = {r.canonical for r in bundle.skills}
        assert {"React", "PostgreSQL", "REST APIs"} <= canon

    def test_bullet_classifies_categories(self, db_session):
        job = _insert_job(
            db_session,
            requirements=[
                "Must have a bachelor's degree in CS",
                "2-3 years of experience with Java",
                "AWS Certified Solutions Architect preferred",
                "Full time role based in Chennai",
                "Knowledge of SQL is required",
            ],
        )
        bundle = rex.extract_job_requirements(job)
        assert any(r.category == "education" for r in bundle.education)
        assert any(r.category == "experience" for r in bundle.experience)
        assert any(r.category == "certification" for r in bundle.certifications)
        assert any(r.category == "location" for r in bundle.locations)
        assert any(r.term == "Chennai" for r in bundle.locations)
        assert any(r.canonical == "SQL" for r in bundle.skills)

    def test_experience_parsed_from_field(self, db_session):
        job = _insert_job(db_session, experience_required="3-5 Years")
        bundle = rex.extract_job_requirements(job)
        assert bundle.experience and bundle.experience[0].source == "structured"
        assert rex.parse_experience_years("3-5 Years") == (3, 5)

    def test_salary_parsed(self, db_session):
        job = _insert_job(db_session, salary="₹400000 - ₹800000 per annum")
        bundle = rex.extract_job_requirements(job)
        assert bundle.salary and bundle.salary[0].detail

    def test_no_fabrication_when_empty(self, db_session):
        job = _insert_job(db_session, description=None)
        bundle = rex.extract_job_requirements(job)
        assert bundle.skills == []

    def test_ai_refine_returns_deterministic_bundle(self, db_session):
        import asyncio

        job = _insert_job(db_session)
        base = rex.extract_job_requirements(job)
        refined = asyncio.run(rex.refine_with_ai(job, base))
        assert refined is base


# ---------------------------------------------------------------------------
# Personal match
# ---------------------------------------------------------------------------
class TestMatchingService:
    def test_exact_profile_match_scores_high(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(
            db_session,
            title="Software Developer",
            skills=["Python", "React", "PostgreSQL"],
            experience_required="0-2 years",
        )
        computation = matching_service.calculate(db_session, job)
        assert computation.match_score is not None
        assert computation.match_score >= 90
        assert computation.matched_skills == ["Python", "React", "PostgreSQL"]
        assert computation.missing_skills == []

    def test_missing_skills_are_not_fabricated(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(
            db_session,
            title="Software Developer",
            skills=["Kubernetes", "Go"],
        )
        computation = matching_service.calculate(db_session, job)
        assert set(computation.missing_skills) == {"Kubernetes", "Go"}
        assert computation.match_score <= 80

    def test_missing_knowledge_of_a_skill_becomes_missing(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(
            db_session,
            title="Software Developer",
            requirements=["Knowledge of Docker is required"],
        )
        computation = matching_service.calculate(db_session, job)
        assert "Docker" in computation.missing_skills

    def test_experience_impossible_is_blocked(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(db_session, title="Software Developer", experience_required="8-10 years")
        computation = matching_service.calculate(db_session, job)
        assert computation.recommendation == "SKIP"
        assert computation.blockers
        assert computation.components["experience"].score == 0

    def test_location_mismatch_is_partial_not_blocked(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(db_session, title="Software Developer", location="Bengaluru, Karnataka")
        computation = matching_service.calculate(db_session, job)
        component = computation.components["location"]
        assert component.status == "PARTIAL"
        assert computation.recommendation != "SKIP"

    def test_no_profile_defaults_still_score(self, db_session):
        job = _insert_job(db_session, title="Software Developer", employment_type="full_time")
        computation = matching_service.calculate(db_session, job)
        assert computation.match_score is not None
        assert computation.components["skills"].status == "UNKNOWN"

    def test_band_mapping(self):
        assert matching_service.band_for_score(95) == "APPLY_NOW"
        assert matching_service.band_for_score(85) == "APPLY"
        assert matching_service.band_for_score(70) == "REVIEW"
        assert matching_service.band_for_score(55) == "LOW_PRIORITY"
        assert matching_service.band_for_score(20) == "SKIP"
        assert matching_service.band_for_score(None) == "REVIEW"


# ---------------------------------------------------------------------------
# Opportunity decision
# ---------------------------------------------------------------------------
class _FakeQuality:
    def __init__(self, overall=50, freshness=75, company=40):
        self.overall_score = overall
        self.components = {
            "freshness": {"score": freshness},
            "company": {"score": company},
        }


class TestOpportunityService:
    def test_blend_of_match_and_quality(self):
        result = opportunity_service.calculate(
            match_score=100, quality=_FakeQuality(50, 75, 40), freshness_raw="FRESH"
        )
        assert result.opportunity_score > 80
        assert result.recommendation in ("APPLY", "APPLY_NOW")

    def test_stale_caps_score(self):
        result = opportunity_service.calculate(
            match_score=100, quality=_FakeQuality(60, 75, 40), freshness_raw="STALE"
        )
        assert result.opportunity_score <= 55

    def test_low_quality_caps_score(self):
        result = opportunity_service.calculate(
            match_score=100, quality=_FakeQuality(20, 75, 40), freshness_raw="FRESH"
        )
        assert result.opportunity_score <= 45

    def test_missing_match_caps_score(self):
        result = opportunity_service.calculate(
            match_score=None, quality=_FakeQuality(70, 75, 40), freshness_raw="FRESH"
        )
        assert result.opportunity_score <= 60

    def test_blockers_force_skip(self):
        result = opportunity_service.calculate(
            match_score=100, quality=_FakeQuality(), blockers=["Role mismatch"]
        )
        assert result.recommendation == "SKIP"


# ---------------------------------------------------------------------------
# Orchestrator persistence + staleness
# ---------------------------------------------------------------------------
class TestMatchesService:
    def test_decisions_persisted(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(
            db_session,
            title="Software Developer",
            skills=["Python", "React", "PostgreSQL"],
        )
        recomputed = matches_service.ensure_decisions(db_session, [job], force=True)
        assert recomputed == 1

        match_row = db_session.scalar(select(JobMatch).where(JobMatch.job_id == job.id))
        assert match_row is not None
        assert match_row.match_score is not None
        assert match_row.context_key

        opp_row = db_session.scalar(
            select(OpportunityScore).where(OpportunityScore.job_id == job.id)
        )
        assert opp_row is not None
        assert opp_row.recommendation in matching_service.RECOMMENDATION_ORDER

    def test_context_change_triggers_recompute(self, db_session):
        _seed_profile(db_session)
        prefs = _seed_preferences(db_session)
        job = _insert_job(db_session, title="Software Developer")
        assert matches_service.ensure_decisions(db_session, [job], force=True) == 1
        first_key = db_session.scalar(select(JobMatch).where(JobMatch.job_id == job.id)).context_key
        assert matches_service.ensure_decisions(db_session, [job]) == 0  # stable

        prefs.experience_levels = ["8-12 years"]
        # ``onupdate=func.now()`` resolves to transaction_timestamp(), fixed for
        # the whole test transaction; bump it explicitly to model a real edit.
        prefs.updated_at = datetime.now(UTC)
        db_session.flush()
        assert matches_service.ensure_decisions(db_session, [job]) == 1
        refreshed = db_session.scalar(select(JobMatch).where(JobMatch.job_id == job.id))
        assert refreshed.context_key != first_key

    def test_insert_job_seeds_decisions(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(db_session, title="Software Developer")
        assert db_session.scalar(select(JobMatch).where(JobMatch.job_id == job.id)) is not None
        assert (
            db_session.scalar(select(OpportunityScore).where(OpportunityScore.job_id == job.id))
            is not None
        )

    def test_recalculate_all_returns_count(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        _insert_job(db_session, title="Software Developer")
        _insert_job(db_session, title="Frontend Developer", employment_type="full_time")
        assert matches_service.recalculate_all(db_session) == 2

    def test_defaults_when_nothing_stored(self, db_session):
        job = _insert_job(db_session, title="Software Developer")
        assert matches_service.ensure_decisions(db_session, [job], force=True) == 1
        match_row = db_session.scalar(select(JobMatch).where(JobMatch.job_id == job.id))
        assert match_row.match_score is not None


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
class TestPhase5API:
    def test_job_read_includes_match_and_opportunity(self, client_session):
        client, session = client_session
        _seed_profile(session)
        _seed_preferences(session)
        result = job_service.insert_jobs(
            session, [_job(title="Software Developer", skills=["Python", "React"])], source="apify"
        )
        assert result.inserted == 1
        job = session.scalar(select(Job).order_by(Job.id.desc()))

        resp = client.get(f"/jobs/{job.id}")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["match"] is not None
        assert payload["opportunity"] is not None
        assert "criteria_breakdown" in payload["match"]

    def test_dedicated_match_endpoint(self, client_session):
        client, session = client_session
        _seed_profile(session)
        _seed_preferences(session)
        job = _insert_job(session, title="Software Developer", skills=["Python"])
        resp = client.get(f"/jobs/{job.id}/match")
        assert resp.status_code == 200
        body = resp.json()
        assert "matched_requirements" in body
        assert "blockers" in body
        assert body["matching_version"] == "v1"
        assert any(e["term"] == "Python" for e in body["matched_requirements"])

    def test_opportunity_endpoint(self, client_session):
        client, session = client_session
        _seed_profile(session)
        _seed_preferences(session)
        job = _insert_job(session, title="Software Developer")
        resp = client.get(f"/jobs/{job.id}/opportunity")
        assert resp.status_code == 200
        body = resp.json()
        assert body["recommendation"] in matching_service.RECOMMENDATION_ORDER
        assert body["opportunity_version"] == "v1"

    def test_recommendation_filter(self, client_session):
        client, session = client_session
        _seed_profile(session)
        _seed_preferences(session)
        _insert_job(session, title="Software Developer", experience_required="8-10 years")
        _insert_job(session, title="Frontend Developer", employment_type="full_time")
        resp = client.get("/jobs", params={"recommendation": "APPLY"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["opportunity"]["recommendation"] == "APPLY"

    def test_min_opportunity_score_filter(self, client_session):
        client, session = client_session
        _seed_profile(session)
        _seed_preferences(session)
        _insert_job(session, title="Software Developer")
        resp = client.get("/jobs", params={"min_opportunity_score": 95})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        resp = client.get("/jobs", params={"min_opportunity_score": 0})
        assert resp.json()["total"] >= 1

    def test_opportunity_sort(self, client_session):
        client, session = client_session
        _seed_profile(session)
        _seed_preferences(session)
        _insert_job(session, title="Software Developer")
        _insert_job(session, title="Frontend Developer", employment_type="full_time")
        resp = client.get("/jobs", params={"sort": "opportunity_desc", "limit": 5})
        assert resp.status_code == 200
        scores = [item["opportunity"]["opportunity_score"] for item in resp.json()["items"]]
        assert scores == sorted(scores, reverse=True)

    def test_stats_include_matches(self, client_session):
        client, session = client_session
        _seed_profile(session)
        _seed_preferences(session)
        _insert_job(session, title="Software Developer")
        resp = client.get("/jobs/stats")
        assert resp.status_code == 200
        matches_block = resp.json()["matches"]
        assert "recommendation_counts" in matches_block
        assert matches_block["evaluated_jobs"] == 1


# ---------------------------------------------------------------------------
# Architecture rule: the LLM never emits scores.
# ---------------------------------------------------------------------------
class _FakeAI:
    name = "fake"
    payload: dict | None = None

    def __init__(self, payload):
        self.payload = payload

    async def extract_job_requirements(self, job):
        return self.payload


def _refine(monkeypatch, payload, db_session, *, unique=0):
    import asyncio


    job = _insert_job(
        db_session,
        title=f"Backend Engineer {unique}",
        description="None.",
    )
    monkeypatch.setattr("app.ai.registry.get_provider", lambda: _FakeAI(payload))
    base = rex.extract_job_requirements(job)
    return asyncio.run(rex.refine_with_ai(job, base))


class TestAIOutputContract:
    def test_valid_facts_are_merged(self, monkeypatch, db_session):
        bundle = _refine(
            monkeypatch,
            {
                "required_skills": ["Python", "SQL"],
                "preferred_skills": ["Docker"],
                "experience_requirement": "2-4 years",
                "role": "Backend Engineer",
                "location": "Chennai",
                "education_requirement": "Bachelor's degree",
                "certifications": ["AWS"],
                "evidence": ["Description mentions AWS deployments."],
                "confidence": 0.9,
            },
            db_session,
        )
        by_canonical = {r.canonical: r for r in bundle.skills}
        assert by_canonical["Python"].source == "ai"
        assert by_canonical["Python"].mandatory is True
        assert by_canonical["Docker"].mandatory is False
        assert any(r.term == "2-4 years" and r.source == "ai" for r in bundle.experience)
        assert any(r.term == "Backend Engineer" and r.source == "ai" for r in bundle.roles)
        assert any(r.term == "Chennai" and r.source == "ai" for r in bundle.locations)
        assert any(r.category == "education" and r.source == "ai" for r in bundle.education)
        assert any(r.term == "AWS" and r.source == "ai" for r in bundle.certifications)
        assert bundle.ai_evidence == ["Description mentions AWS deployments."]
        assert bundle.confidence == 0.9

    @pytest.mark.parametrize(
        "banned",
        [
            {"match_score": 99},
            {"opportunity_score": 87},
            {"recommendation": "APPLY"},
            {"match_score": 99, "skills": ["Python"]},
            {"match_score": 99, "opportunity_score": 87, "recommendation": "APPLY_NOW"},
        ],
    )
    def test_score_keys_are_rejected_and_fallback_wins(self, monkeypatch, db_session, banned):
        base = _refine(monkeypatch, banned, db_session)
        assert base.confidence is None
        assert base.ai_evidence == []
        # The reject must be total: the payload's skills never leak in either.
        assert not any(r.source == "ai" for r in base.skills)

    def test_invalid_confidence_falls_back(self, monkeypatch, db_session):
        for i, bad in enumerate((1.5, "high", -0.1)):
            base = _refine(
                monkeypatch, {"skills": ["Python"], "confidence": bad}, db_session, unique=i
            )
            assert base.confidence is None
            assert not any(r.source == "ai" for r in base.skills)

    def test_none_and_non_dict_fallback(self, monkeypatch, db_session):
        for i, payload in enumerate((None, "nope", ["Python"], 42)):
            base = _refine(monkeypatch, payload, db_session, unique=i)
            assert base.confidence is None
            assert not any(r.source == "ai" for r in base.skills)

    def test_same_payload_produces_same_bundle(self, monkeypatch, db_session):
        payload = {
            "required_skills": ["React", "PostgreSQL"],
            "experience_requirement": "1-3 years",
            "role": "Frontend Developer",
        }
        first = _refine(monkeypatch, payload, db_session, unique=0)
        second = _refine(monkeypatch, payload, db_session, unique=1)
        assert [(r.canonical, r.source, r.mandatory) for r in first.skills] == [
            (r.canonical, r.source, r.mandatory) for r in second.skills
        ]
        assert [r.term for r in first.experience] == [r.term for r in second.experience]


class TestDeterministicScoring:
    def test_same_input_same_score(self, db_session):
        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(
            db_session,
            title="Software Developer",
            skills=["Python", "React", "PostgreSQL"],
            requirements=["2-3 years of experience with Java"],
            location="Chennai, Tamil Nadu",
        )
        mine = matching_service.calculate(db_session, job)
        again = matching_service.calculate(db_session, job)
        assert mine.match_score == again.match_score
        assert mine.recommendation == again.recommendation
        assert mine.context_key == again.context_key
        assert mine.confidence_score == again.confidence_score
        assert mine.explanation == again.explanation

    def test_rejected_ai_payload_cannot_change_score(
        self, monkeypatch, db_session
    ):
        """A provider trying to sneak a score in must not move the outcome."""
        import asyncio

        _seed_profile(db_session)
        _seed_preferences(db_session)
        job = _insert_job(
            db_session,
            title="Software Developer",
            skills=["Python", "React", "PostgreSQL"],
            location="Chennai, Tamil Nadu",
        )
        deterministic = matching_service.calculate(db_session, job)

        monkeypatch.setattr(
            "app.ai.registry.get_provider",
            lambda: _FakeAI({"match_score": 99, "recommendation": "APPLY_NOW"}),
        )
        refined = asyncio.run(
            rex.refine_with_ai(job, rex.extract_job_requirements(job))
        )
        ai_attempt = matching_service.calculate(
            db_session, job, bundle=refined
        )
        assert ai_attempt.match_score == deterministic.match_score
        assert ai_attempt.recommendation == deterministic.recommendation
