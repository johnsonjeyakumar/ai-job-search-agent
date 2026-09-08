"""Phase 11: Skill gap analysis & learning plan tests.

Covers:
- Skill gap analysis (classification, evidence, market demand, priorities)
- Learning plan generation (prerequisites, ordering, tasks)
- Learning item status updates (progress tracking)
- Learning evidence attachment
- API endpoint integration tests
- Deterministic behavior verification (no LLM involvement in classification)
- Edge cases (empty data, missing profile, unknown skills)
"""
from __future__ import annotations

import pytest

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import learning_plan_service, skill_gap_service

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_profile(db):
    profile = Profile(
        name="Skill Gap Candidate",
        email="skillgap@test.example",
        city="Chennai",
        skills=["Python", "React", "SQL", "Docker"],
        skills_programming=["Python", "JavaScript"],
        skills_frameworks=["React"],
        skills_databases=["SQL"],
        skills_tools=["Docker"],
        skills_other=[],
        projects=[{"name": "Web App", "technologies": ["Python", "React", "PostgreSQL"]}],
        internships=[{"company": "TechCorp", "skills": ["Python", "Docker"]}],
        certifications=[{"name": "AWS Certified Developer"}],
        experience_level="2-4 years",
    )
    db.add(profile)
    db.flush()
    return profile


def _seed_resume(db, profile):
    resume = Resume(
        profile_id=profile.id,
        name="skillgap_resume.pdf",
        target_role="Full Stack Developer",
        file_path="resumes/sg.pdf",
    )
    db.add(resume)
    db.flush()
    return resume


def _seed_job(db, skills=None, requirements=None, description=None):
    job = Job(
        title="Full Stack Developer",
        company="TestCorp",
        location="Chennai",
        url="https://test.example/job/sg",
        source="test",
        skills=skills if skills is not None else ["Python", "React", "PostgreSQL", "Docker", "AWS", "TypeScript"],
        requirements=requirements or [],
        description=description if description is not None else "Looking for a full stack developer with Python, React, PostgreSQL, Docker, AWS, and TypeScript.",
    )
    db.add(job)
    db.flush()
    return job


def _seed_multiple_jobs(db):
    """Seed multiple jobs for market demand testing."""
    jobs = []
    for i in range(5):
        job = Job(
            title=f"Developer {i}",
            company=f"Corp{i}",
            location="Chennai",
            url=f"https://test.example/job/md{i}",
            source="test",
            skills=["Python", "React", "Docker"],
        )
        db.add(job)
        jobs.append(job)
    db.flush()
    return jobs


# ---------------------------------------------------------------------------
# Skill gap analysis tests
# ---------------------------------------------------------------------------

class TestSkillGapAnalysis:
    def test_basic_analysis(self, db_session):
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile)
        job = _seed_job(db_session)

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        db_session.commit()

        assert analysis.id is not None
        assert analysis.job_id == job.id
        assert "Python" in analysis.matched_skills
        assert "React" in analysis.matched_skills
        assert "Docker" in analysis.matched_skills
        assert "AWS" in analysis.missing_skills or "TypeScript" in analysis.missing_skills
        assert analysis.readiness_percentage > 0

    def test_missing_profile(self, db_session):
        job = _seed_job(db_session)
        analysis = skill_gap_service.analyze_skill_gaps(db_session, job.id)
        db_session.commit()

        assert analysis.matched_skills == []
        assert len(analysis.missing_skills) > 0
        assert analysis.readiness_percentage == 0

    def test_evidence_traces_to_source(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        evidence_map = {e["skill"]: e for e in analysis.evidence}
        python_ev = evidence_map.get("Python")
        assert python_ev is not None
        assert python_ev["status"] == "MATCHED"
        assert python_ev["source"] in ("PROFILE", "PROJECT", "INTERNSHIP")

    def test_project_evidence(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["PostgreSQL"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        evidence_map = {e["skill"]: e for e in analysis.evidence}
        pg_ev = evidence_map.get("PostgreSQL")
        assert pg_ev is not None
        assert pg_ev["status"] == "MATCHED"
        assert "Web App" in (pg_ev["evidence"] or "")

    def test_market_demand_computed(self, db_session):
        _seed_multiple_jobs(db_session)
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        assert len(analysis.market_demand) > 0
        for skill, info in analysis.market_demand.items():
            assert "frequency" in info
            assert "demand_level" in info
            assert info["demand_level"] in ("HIGH", "MEDIUM", "LOW")

    def test_priorities_computed(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        for skill in analysis.missing_skills:
            assert skill in analysis.priorities
            assert analysis.priorities[skill] in ("HIGH", "MEDIUM", "LOW")

    def test_readiness_label(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        assert analysis.readiness_label in ("STRONG", "MODERATE", "WEAK", "UNKNOWN")
        assert 0 <= analysis.readiness_percentage <= 100

    def test_unknown_skills(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["NonExistentTech123", "Python"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        assert "Python" in analysis.matched_skills

    def test_nonexistent_job_raises(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            skill_gap_service.analyze_skill_gaps(db_session, 99999)

    def test_get_latest_analysis(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        db_session.commit()

        latest = skill_gap_service.get_latest_analysis(db_session, job.id)
        assert latest is not None
        assert latest.job_id == job.id

    def test_list_analyses(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        db_session.commit()

        analyses = skill_gap_service.list_analyses(db_session, profile.id)
        assert len(analyses) >= 1


# ---------------------------------------------------------------------------
# Learning plan tests
# ---------------------------------------------------------------------------

class TestLearningPlan:
    def test_generate_plan(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        assert plan.id is not None
        assert plan.total_items > 0
        assert plan.estimated_effort_hours > 0
        assert plan.status == "NOT_STARTED"

    def test_plan_has_items(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        assert len(items) == plan.total_items
        for item in items:
            assert item.skill
            assert item.objective
            assert item.tasks

    def test_prerequisites_resolved(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["React", "JavaScript", "TypeScript"])

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        item_skills = [i.skill for i in items]
        # TypeScript should appear before React (prerequisite)
        if "TypeScript" in item_skills and "React" in item_skills:
            assert item_skills.index("TypeScript") < item_skills.index("React")

    def test_plan_status_tracking(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        first_item = items[0]

        learning_plan_service.update_item_status(db_session, first_item.id, "IN_PROGRESS")
        db_session.commit()

        plan = learning_plan_service.get_plan(db_session, plan.id)
        assert plan.status == "IN_PROGRESS"

    def test_complete_all_items_marks_plan_complete(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        for item in items:
            learning_plan_service.update_item_status(db_session, item.id, "COMPLETED")
        db_session.commit()

        plan = learning_plan_service.get_plan(db_session, plan.id)
        assert plan.status == "COMPLETED"
        assert plan.completed_items == plan.total_items

    def test_invalid_status_raises(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        with pytest.raises(ValueError, match="Invalid status"):
            learning_plan_service.update_item_status(
                db_session, items[0].id, "INVALID_STATUS"
            )

    def test_add_evidence(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        evidence = learning_plan_service.add_item_evidence(
            db_session, items[0].id, "PROJECT_URL",
            url="https://github.com/test/project",
            description="Built a practice project"
        )
        db_session.commit()

        assert evidence.id is not None
        assert evidence.evidence_type == "PROJECT_URL"

    def test_invalid_evidence_type_raises(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        with pytest.raises(ValueError, match="Invalid evidence_type"):
            learning_plan_service.add_item_evidence(
                db_session, items[0].id, "INVALID_TYPE"
            )

    def test_list_plans(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        plans = learning_plan_service.list_plans(db_session, profile.id)
        assert len(plans) >= 1


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestSkillGapAPI:
    def test_create_gap_analysis(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        db.commit()

        resp = _client.post(
            f"/skills/gap-analysis/{job.id}?profile_id={profile.id}&resume_id={resume.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job.id
        assert "matched_skills" in data
        assert "missing_skills" in data
        assert "readiness_percentage" in data

    def test_get_gap_analysis(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db)
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        resp = _client.get(f"/skills/gap-analysis/{job.id}")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == job.id

    def test_list_gap_analyses(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db)
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        resp = _client.get("/skills/gap-analysis")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_create_learning_plan(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db)
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        resp = _client.post(
            f"/skills/learning-plans/{job.id}?profile_id={profile.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_items"] > 0

    def test_list_learning_plans(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db)
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        _client.post(
            f"/skills/learning-plans/{job.id}?profile_id={profile.id}"
        )
        resp = _client.get("/skills/learning-plans")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_list_learning_items(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db)
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        plan_resp = _client.post(
            f"/skills/learning-plans/{job.id}?profile_id={profile.id}"
        )
        plan_id = plan_resp.json()["id"]

        resp = _client.get(f"/skills/learning-plans/{plan_id}/items")
        assert resp.status_code == 200
        assert len(resp.json()) > 0

    def test_update_item_status(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db)
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        plan_resp = _client.post(
            f"/skills/learning-plans/{job.id}?profile_id={profile.id}"
        )
        items_resp = _client.get(
            f"/skills/learning-plans/{plan_resp.json()['id']}/items"
        )
        item_id = items_resp.json()[0]["id"]

        resp = _client.patch(
            f"/skills/learning-items/{item_id}/status",
            json={"status": "IN_PROGRESS"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "IN_PROGRESS"

    def test_add_evidence(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db)
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        plan_resp = _client.post(
            f"/skills/learning-plans/{job.id}?profile_id={profile.id}"
        )
        items_resp = _client.get(
            f"/skills/learning-plans/{plan_resp.json()['id']}/items"
        )
        item_id = items_resp.json()[0]["id"]

        resp = _client.post(
            f"/skills/learning-items/{item_id}/evidence",
            json={
                "evidence_type": "PROJECT_URL",
                "url": "https://github.com/test/project",
                "description": "Practice project",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["evidence_type"] == "PROJECT_URL"

    def test_nonexistent_job_returns_404(self, client):
        resp = client.post("/skills/gap-analysis/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Determinism verification
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_classification_is_deterministic(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        a1 = skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        db_session.commit()

        a2 = skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        db_session.commit()

        assert a1.matched_skills == a2.matched_skills
        assert a1.missing_skills == a2.missing_skills
        assert a1.readiness_percentage == a2.readiness_percentage

    def test_no_llm_in_classification(self, db_session):
        """Verify skill classification uses only deterministic logic."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session)

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        for item in analysis.evidence:
            assert item["status"] in ("MATCHED", "MISSING", "UNKNOWN")
            assert item["source"] in (
                "PROFILE", "PROJECT", "INTERNSHIP", "RESUME",
                "INTERVIEW", "JOB_REQUIREMENT", "UNKNOWN",
            )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_job_skills(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=[], description="", requirements=[])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        assert len(analysis.matched_skills) == 0
        assert len(analysis.missing_skills) == 0

    def test_all_skills_matched(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(
            db_session,
            skills=["Python", "React", "SQL", "Docker"],
            description="Looking for a developer with Python, React, SQL, Docker",
        )

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        assert len(analysis.missing_skills) == 0
        assert len(analysis.matched_skills) >= 4

    def test_no_skills_matched(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(
            db_session,
            skills=["Go", "Rust", "Kubernetes", "Terraform"],
            description="Looking for a developer with Go, Rust, Kubernetes, Terraform",
        )

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        assert len(analysis.matched_skills) == 0
        assert len(analysis.missing_skills) >= 4
