"""Phase 11.1: Skill gap enhancements tests.

Covers:
- PARTIAL classification (resume-only, profile-only, weak evidence)
- Learning resources (CRUD, validation, AI suggested)
- Skill history (state changes, immutability, chronological order)
- Separation of gap status vs learning progress vs verification
- Analytics counts
- Readiness behavior with PARTIAL
- Edge cases
"""
from __future__ import annotations

import pytest

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import learning_plan_service, skill_gap_service

# ---------------------------------------------------------------------------
# Seed helpers (reused from Phase 11 tests)
# ---------------------------------------------------------------------------

def _seed_profile(db):
    profile = Profile(
        name="Phase111 Candidate",
        email="p111@test.example",
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


def _seed_resume(db, profile, target_role="Full Stack Developer"):
    resume = Resume(
        profile_id=profile.id,
        name="p111_resume.pdf",
        target_role=target_role,
        file_path="resumes/p111.pdf",
    )
    db.add(resume)
    db.flush()
    return resume


def _seed_job(db, skills=None, description=None):
    job = Job(
        title="Full Stack Developer",
        company="TestCorp",
        location="Chennai",
        url="https://test.example/job/p111",
        source="test",
        skills=skills or ["Python", "React", "PostgreSQL", "Docker", "AWS", "TypeScript"],
        requirements=[],
        description=description or "Full stack developer with Python, React, PostgreSQL, Docker, AWS, TypeScript.",
    )
    db.add(job)
    db.flush()
    return job


# ---------------------------------------------------------------------------
# PARTIAL classification tests
# ---------------------------------------------------------------------------

class TestPartialClassification:
    def test_resume_only_gives_partial(self, db_session):
        """Skill in resume text only (not profile structured) → PARTIAL."""
        profile = _seed_profile(db_session)
        # Add "Kubernetes" to resume target_role only
        resume = _seed_resume(db_session, profile, target_role="Kubernetes Engineer")
        db_session.flush()

        job = _seed_job(db_session, skills=["Kubernetes", "Python"])
        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        db_session.commit()

        evidence_map = {e["skill"]: e for e in analysis.evidence}
        k8s = evidence_map.get("Kubernetes")
        assert k8s is not None
        assert k8s["status"] == "PARTIAL"
        assert k8s["source"] == "RESUME"

    def test_profile_strong_evidence_gives_matched(self, db_session):
        """Skill in profile.skills → MATCHED."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["Python"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        evidence_map = {e["skill"]: e for e in analysis.evidence}
        assert evidence_map["Python"]["status"] == "MATCHED"
        assert evidence_map["Python"]["source"] in ("PROFILE", "PROJECT", "INTERNSHIP")

    def test_project_evidence_gives_matched(self, db_session):
        """Skill in profile.projects → MATCHED."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["PostgreSQL"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        evidence_map = {e["skill"]: e for e in analysis.evidence}
        pg = evidence_map.get("PostgreSQL")
        assert pg is not None
        assert pg["status"] == "MATCHED"

    def test_no_evidence_gives_missing(self, db_session):
        """Job requires skill, no user evidence → MISSING."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["Angular"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        evidence_map = {e["skill"]: e for e in analysis.evidence}
        assert evidence_map["Angular"]["status"] == "MISSING"

    def test_mixed_matched_partial_missing(self, db_session):
        """Verify correct classification across all statuses."""
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile, target_role="Docker Engineer Kubernetes Expert")
        job = _seed_job(
            db_session,
            skills=["Python", "Docker", "Kubernetes", "Angular"],
            description="Requires Python and Docker.",
        )

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        db_session.commit()

        evidence_map = {e["skill"]: e for e in analysis.evidence}
        # Python: in profile → MATCHED
        assert evidence_map["Python"]["status"] == "MATCHED"
        # Docker: in profile → MATCHED
        assert evidence_map["Docker"]["status"] == "MATCHED"
        # Kubernetes: only in resume text → PARTIAL
        assert evidence_map["Kubernetes"]["status"] == "PARTIAL"
        # Angular: nowhere → MISSING
        assert evidence_map["Angular"]["status"] == "MISSING"

    def test_partial_in_partial_skills_list(self, db_session):
        """PARTIAL skills appear in partial_skills list."""
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile, target_role="Kubernetes Expert")
        job = _seed_job(db_session, skills=["Kubernetes"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        db_session.commit()

        assert "Kubernetes" in analysis.partial_skills
        assert "Kubernetes" not in analysis.matched_skills
        assert "Kubernetes" not in analysis.missing_skills

    def test_readiness_with_partial(self, db_session):
        """PARTIAL skills count as 50% credit toward readiness."""
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile, target_role="Kubernetes Expert Angular Guru")
        job = _seed_job(
            db_session,
            skills=["Python", "Docker", "Kubernetes", "Angular"],
            description="Requires Python and Docker.",
        )

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        db_session.commit()

        # Python + Docker = MATCHED (2), Kubernetes + Angular = PARTIAL (2)
        # Readiness = (2 + 0.5*2) / 4 = 75%
        assert analysis.readiness_percentage == 75
        assert analysis.readiness_label == "MODERATE"

    def test_partial_gets_priority(self, db_session):
        """PARTIAL skills get priority like MISSING skills."""
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile, target_role="Kubernetes Expert")
        job = _seed_job(db_session, skills=["Kubernetes"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        db_session.commit()

        assert "Kubernetes" in analysis.priorities
        assert analysis.priorities["Kubernetes"] in ("HIGH", "MEDIUM", "LOW")

    def test_evidence_has_why_info(self, db_session):
        """Each evidence item includes 'why' information."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["Python", "Angular"])

        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        for ev in analysis.evidence:
            assert "why" in ev
            assert isinstance(ev["why"], list)
            assert len(ev["why"]) > 0
            assert "demand_level" in ev
            assert "mandatory" in ev


# ---------------------------------------------------------------------------
# Learning resource tests
# ---------------------------------------------------------------------------

class TestLearningResources:
    def _setup_plan(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()
        items = learning_plan_service.list_plan_items(db_session, plan.id)
        return plan, items[0] if items else None

    def test_add_resource(self, db_session):
        plan, item = self._setup_plan(db_session)
        resource = learning_plan_service.add_item_resource(
            db_session, item.id,
            title="AWS Documentation",
            resource_type="DOCUMENTATION",
            url="https://docs.aws.amazon.com",
            provider="AWS",
            description="Official AWS docs",
            free_or_paid="FREE",
            difficulty="BEGINNER",
            source="USER",
        )
        db_session.commit()

        assert resource.id is not None
        assert resource.title == "AWS Documentation"
        assert resource.resource_type == "DOCUMENTATION"
        assert resource.source == "USER"

    def test_add_ai_suggested_resource(self, db_session):
        plan, item = self._setup_plan(db_session)
        resource = learning_plan_service.add_item_resource(
            db_session, item.id,
            title="AWS Tutorial",
            resource_type="TUTORIAL",
            url="https://example.com/tutorial",
            source="AI_SUGGESTED",
        )
        db_session.commit()

        assert resource.source == "AI_SUGGESTED"

    def test_invalid_url_raises(self, db_session):
        plan, item = self._setup_plan(db_session)
        with pytest.raises(ValueError, match="Invalid URL"):
            learning_plan_service.add_item_resource(
                db_session, item.id,
                title="Bad URL",
                resource_type="ARTICLE",
                url="not-a-url",
            )

    def test_invalid_resource_type_raises(self, db_session):
        plan, item = self._setup_plan(db_session)
        with pytest.raises(ValueError, match="Invalid resource_type"):
            learning_plan_service.add_item_resource(
                db_session, item.id,
                title="Bad Type",
                resource_type="INVALID_TYPE",
            )

    def test_list_resources(self, db_session):
        plan, item = self._setup_plan(db_session)
        learning_plan_service.add_item_resource(
            db_session, item.id,
            title="Res 1", resource_type="DOCUMENTATION",
        )
        learning_plan_service.add_item_resource(
            db_session, item.id,
            title="Res 2", resource_type="VIDEO",
        )
        db_session.commit()

        resources = learning_plan_service.list_item_resources(db_session, item.id)
        assert len(resources) == 2

    def test_delete_resource(self, db_session):
        plan, item = self._setup_plan(db_session)
        resource = learning_plan_service.add_item_resource(
            db_session, item.id,
            title="To Delete", resource_type="ARTICLE",
        )
        db_session.commit()

        deleted = learning_plan_service.delete_resource(db_session, resource.id)
        db_session.commit()
        assert deleted is True

        resources = learning_plan_service.list_item_resources(db_session, item.id)
        assert len(resources) == 0

    def test_delete_nonexistent_returns_false(self, db_session):
        deleted = learning_plan_service.delete_resource(db_session, 99999)
        assert deleted is False

    def test_optional_url_accepted(self, db_session):
        plan, item = self._setup_plan(db_session)
        resource = learning_plan_service.add_item_resource(
            db_session, item.id,
            title="No URL Resource", resource_type="PRACTICE",
        )
        db_session.commit()
        assert resource.id is not None


# ---------------------------------------------------------------------------
# Skill history tests
# ---------------------------------------------------------------------------

class TestSkillHistory:
    def test_analysis_creates_history(self, db_session):
        """Gap analysis creates skill history records."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["Python", "Angular"])

        skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        history = skill_gap_service.get_skill_history(
            db_session, profile.id
        )
        assert len(history) >= 2
        skills_in_history = {h.skill for h in history}
        assert "Python" in skills_in_history
        assert "Angular" in skills_in_history

    def test_history_records_status(self, db_session):
        """History records the new_status correctly."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["Python"])

        skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        history = skill_gap_service.get_skill_history(
            db_session, profile.id, skill="Python"
        )
        assert len(history) >= 1
        assert history[0].new_status == "MATCHED"

    def test_history_is_immutable(self, db_session):
        """Old history records are not modified by new analyses."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["Python"])

        skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()
        first_count = len(
            skill_gap_service.get_skill_history(db_session, profile.id)
        )

        # Run again
        skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()
        second_count = len(
            skill_gap_service.get_skill_history(db_session, profile.id)
        )

        # More records created, old ones preserved
        assert second_count > first_count

    def test_learning_status_change_creates_history(self, db_session):
        """Updating learning item status creates history."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        learning_plan_service.update_item_status(
            db_session, items[0].id, "IN_PROGRESS", profile_id=profile.id
        )
        db_session.commit()

        history = skill_gap_service.get_skill_history(
            db_session, profile.id, skill=items[0].skill
        )
        # Should have gap analysis record + learning progress record
        learning_records = [h for h in history if h.source == "LEARNING_PROGRESS"]
        assert len(learning_records) >= 1
        assert learning_records[0].new_status == "IN_PROGRESS"

    def test_no_history_for_noop_update(self, db_session):
        """Setting same status twice doesn't create duplicate history."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        # Set to IN_PROGRESS
        learning_plan_service.update_item_status(
            db_session, items[0].id, "IN_PROGRESS", profile_id=profile.id
        )
        db_session.commit()

        count_before = len(
            skill_gap_service.get_skill_history(
                db_session, profile.id, skill=items[0].skill
            )
        )

        # Set to IN_PROGRESS again (noop)
        learning_plan_service.update_item_status(
            db_session, items[0].id, "IN_PROGRESS", profile_id=profile.id
        )
        db_session.commit()

        count_after = len(
            skill_gap_service.get_skill_history(
                db_session, profile.id, skill=items[0].skill
            )
        )
        assert count_after == count_before

    def test_history_chronological_order(self, db_session):
        """History records are returned in chronological order."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        skill_name = items[0].skill

        # Create multiple status changes
        for status in ["IN_PROGRESS", "COMPLETED", "VERIFIED"]:
            learning_plan_service.update_item_status(
                db_session, items[0].id, status, profile_id=profile.id
            )
            db_session.commit()

        history = skill_gap_service.get_skill_history(
            db_session, profile.id, skill=skill_name
        )
        # Descending order (newest first)
        timestamps = [h.created_at for h in history]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# Separation of concerns tests
# ---------------------------------------------------------------------------

class TestSeparationOfConcerns:
    def test_learning_completion_does_not_imply_verification(self, db_session):
        """COMPLETED learning item is not automatically VERIFIED."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        learning_plan_service.update_item_status(
            db_session, items[0].id, "COMPLETED"
        )
        db_session.commit()

        item = learning_plan_service.list_plan_items(db_session, plan.id)[0]
        assert item.status == "COMPLETED"
        assert item.verified_at is None

    def test_gap_classification_independent_of_learning(self, db_session):
        """Learning progress doesn't change gap classification."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        analysis = skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id
        )
        db_session.commit()

        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        items = learning_plan_service.list_plan_items(db_session, plan.id)
        learning_plan_service.update_item_status(
            db_session, items[0].id, "COMPLETED"
        )
        db_session.commit()

        # Re-fetch analysis — should be unchanged
        latest = skill_gap_service.get_latest_analysis(db_session, job.id)
        assert latest.readiness_percentage == analysis.readiness_percentage
        assert latest.missing_skills == analysis.missing_skills

    def test_verification_requires_explicit_action(self, db_session):
        """VERIFIED only happens via explicit status update."""
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        learning_plan_service.update_item_status(
            db_session, items[0].id, "COMPLETED"
        )
        db_session.commit()

        # Plan should not be COMPLETED (item is COMPLETED not VERIFIED)
        plan = learning_plan_service.get_plan(db_session, plan.id)
        assert plan.verified_items == 0


# ---------------------------------------------------------------------------
# Analytics tests
# ---------------------------------------------------------------------------

class TestAnalytics:
    def test_analytics_counts(self, db_session):
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile, target_role="Kubernetes Expert")
        job = _seed_job(
            db_session,
            skills=["Python", "Kubernetes", "Angular"],
            description="Requires Python.",
        )

        skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        db_session.commit()

        analytics = skill_gap_service.get_skill_analytics(db_session, profile.id)
        assert analytics["matched_count"] >= 1  # Python
        assert analytics["partial_count"] >= 1  # Kubernetes
        assert analytics["missing_count"] >= 1  # Angular
        assert analytics["total_analyses"] >= 1

    def test_analytics_learning_counts(self, db_session):
        profile = _seed_profile(db_session)
        job = _seed_job(db_session, skills=["AWS"])
        skill_gap_service.analyze_skill_gaps(db_session, job.id, profile.id)
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        learning_plan_service.update_item_status(
            db_session, items[0].id, "IN_PROGRESS"
        )
        db_session.commit()

        analytics = skill_gap_service.get_skill_analytics(db_session, profile.id)
        assert analytics["total_learning_items"] >= 1
        assert analytics["in_progress_learning_items"] >= 1

    def test_analytics_empty_state(self, db_session):
        analytics = skill_gap_service.get_skill_analytics(db_session, 99999)
        assert analytics["matched_count"] == 0
        assert analytics["partial_count"] == 0
        assert analytics["missing_count"] == 0
        assert analytics["total_learning_items"] == 0


# ---------------------------------------------------------------------------
# API endpoint tests for new features
# ---------------------------------------------------------------------------

class TestPhase111API:
    def test_add_resource_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["AWS"])
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
            f"/skills/learning-items/{item_id}/resources",
            json={
                "title": "AWS Docs",
                "resource_type": "DOCUMENTATION",
                "url": "https://docs.aws.amazon.com",
                "source": "USER",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "AWS Docs"
        assert data["resource_type"] == "DOCUMENTATION"

    def test_list_resources_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["AWS"])
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        plan_resp = _client.post(
            f"/skills/learning-plans/{job.id}?profile_id={profile.id}"
        )
        items_resp = _client.get(
            f"/skills/learning-plans/{plan_resp.json()['id']}/items"
        )
        item_id = items_resp.json()[0]["id"]

        _client.post(
            f"/skills/learning-items/{item_id}/resources",
            json={"title": "R1", "resource_type": "VIDEO"},
        )
        resp = _client.get(f"/skills/learning-items/{item_id}/resources")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_delete_resource_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["AWS"])
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")
        plan_resp = _client.post(
            f"/skills/learning-plans/{job.id}?profile_id={profile.id}"
        )
        items_resp = _client.get(
            f"/skills/learning-plans/{plan_resp.json()['id']}/items"
        )
        item_id = items_resp.json()[0]["id"]

        res_resp = _client.post(
            f"/skills/learning-items/{item_id}/resources",
            json={"title": "To Delete", "resource_type": "ARTICLE"},
        )
        resource_id = res_resp.json()["id"]

        resp = _client.delete(f"/skills/learning-resources/{resource_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_invalid_resource_url_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["AWS"])
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
            f"/skills/learning-items/{item_id}/resources",
            json={
                "title": "Bad",
                "resource_type": "ARTICLE",
                "url": "not-a-url",
            },
        )
        assert resp.status_code == 400

    def test_skill_history_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["Python"])
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")

        resp = _client.get(f"/skills/history?profile_id={profile.id}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_skill_history_by_name_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["Python"])
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")

        resp = _client.get(
            f"/skills/history/Python?profile_id={profile.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["skill"] == "Python"

    def test_analytics_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["Python"])
        db.commit()

        _client.post(f"/skills/gap-analysis/{job.id}?profile_id={profile.id}")

        resp = _client.get(f"/skills/analytics?profile_id={profile.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "matched_count" in data
        assert "partial_count" in data
        assert "missing_count" in data
        assert "verified_learning_items" in data

    def test_gap_analysis_response_has_why(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["Python"])
        db.commit()

        resp = _client.post(
            f"/skills/gap-analysis/{job.id}?profile_id={profile.id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        for ev in data["evidence"]:
            assert "why" in ev
            assert isinstance(ev["why"], list)

    def test_resource_invalid_type_via_api(self, client, client_session):
        _client, db = client_session
        profile = _seed_profile(db)
        job = _seed_job(db, skills=["AWS"])
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
            f"/skills/learning-items/{item_id}/resources",
            json={"title": "X", "resource_type": "INVALID"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Learning plan includes PARTIAL skills
# ---------------------------------------------------------------------------

class TestLearningPlanIncludesPartial:
    def test_plan_includes_partial_skills(self, db_session):
        """Learning plan should include PARTIAL skills, not just MISSING."""
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile, target_role="Kubernetes Expert")
        job = _seed_job(db_session, skills=["Kubernetes", "Angular"])

        skill_gap_service.analyze_skill_gaps(
            db_session, job.id, profile.id, resume.id
        )
        plan = learning_plan_service.generate_learning_plan(
            db_session, job.id, profile.id
        )
        db_session.commit()

        items = learning_plan_service.list_plan_items(db_session, plan.id)
        item_skills = [i.skill for i in items]
        # Kubernetes should be in plan (PARTIAL → needs learning)
        assert "Kubernetes" in item_skills
        # Angular should be in plan (MISSING → needs learning)
        assert "Angular" in item_skills
