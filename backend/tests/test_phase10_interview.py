"""Phase 10: Interview preparation & interview agent tests.

Covers:
- Interview CRUD + lifecycle (create, update, complete, cancel, reschedule, outcome)
- Question generation (deterministic, job/resume evidence, priority)
- Answer save + feedback
- Mock sessions (create, answer, finish, evaluation)
- Prep plan items
- Interview summary
- AI safety (no fabricated facts, no status corruption)
- Data integrity (old interviews preserved, application history untouched)
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.application import Application
from app.models.application_tracking import ApplicationEvent, InterviewRecord
from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_profile(db):
    profile = Profile(
        name="Interview Candidate",
        email=f"int-{abs(hash(object()))}@example.test",
        city="Chennai",
        skills=["Python", "FastAPI", "SQL", "React"],
        skills_programming=["Python"],
        skills_databases=["SQL"],
        experience_level="0-2 years",
        projects=["Built a REST API with FastAPI", "Built a React dashboard"],
    )
    db.add(profile)
    db.flush()
    return profile


def _seed_resume(db, profile):
    resume = Resume(
        profile_id=profile.id,
        name="interview_resume.pdf",
        target_role="Software Developer",
        file_path="resumes/int.pdf",
        file_name="interview_resume.pdf",
        content_type="application/pdf",
        version="v1",
    )
    db.add(resume)
    db.flush()
    return resume


def _seed_job(db):
    job = Job(
        title="Software Developer",
        company="Acme",
        location="Chennai",
        remote_type="onsite",
        source="apify",
        source_job_id=f"p10-{abs(hash(object()))}",
        url="mock://careers/int",
        description="We are looking for a team player who can work in a fast-paced environment.",
        requirements=["Python", "FastAPI", "SQL"],
        skills=["Python", "FastAPI", "SQL", "React"],
    )
    db.add(job)
    db.flush()
    return job


def _seed_app_at_status(db, job, profile, resume, status):
    app = Application(
        job_id=job.id,
        profile_id=profile.id,
        resume_id=resume.id,
        lifecycle_status=status,
        status="applied",
        resume_name=resume.name,
        resume_version=resume.version,
    )
    db.add(app)
    db.flush()
    return app


# ---------------------------------------------------------------------------
# Interview CRUD + lifecycle
# ---------------------------------------------------------------------------

class TestInterviewCRUD:
    def test_create_interview(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL",
            "round_number": 1,
            "scheduled_at": "2026-09-20T10:00:00Z",
            "interviewer_name": "Jane Smith",
            "notes": "First round",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Interview created."
        assert data["interview_id"] is not None
        assert data["status"] == "SCHEDULED"

    def test_list_interviews(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "HR", "round_number": 2,
        })
        resp = client.get(f"/interviews/applications/{app.id}/interviews")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["summary"]["total"] == 2

    def test_get_interview(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.get(f"/interviews/{int_id}")
        assert resp.status_code == 200
        assert resp.json()["interview_type"] == "TECHNICAL"

    def test_update_interview(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.patch(f"/interviews/{int_id}", json={
            "interviewer_name": "John Doe",
            "location": "Conference Room A",
        })
        assert resp.status_code == 200

        get_resp = client.get(f"/interviews/{int_id}")
        assert get_resp.json()["interviewer_name"] == "John Doe"
        assert get_resp.json()["location"] == "Conference Room A"

    def test_update_interview_notes_returns_in_response(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.patch(f"/interviews/{int_id}", json={
            "notes": "Updated via PATCH",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["notes"] == "Updated via PATCH"
        assert data["interview_id"] == int_id

    def test_complete_interview(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.post(f"/interviews/{int_id}/complete")
        assert resp.status_code == 200

        get_resp = client.get(f"/interviews/{int_id}")
        assert get_resp.json()["status"] == "COMPLETED"
        assert get_resp.json()["completed_at"] is not None

    def test_cancel_interview(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.post(f"/interviews/{int_id}/cancel")
        assert resp.status_code == 200

        get_resp = client.get(f"/interviews/{int_id}")
        assert get_resp.json()["status"] == "CANCELLED"

    def test_reschedule_interview(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.post(f"/interviews/{int_id}/reschedule", json={
            "scheduled_at": "2026-09-25T14:00:00Z",
            "notes": "Rescheduled due to conflict",
        })
        assert resp.status_code == 200

        get_resp = client.get(f"/interviews/{int_id}")
        assert get_resp.json()["status"] == "RESCHEDULED"

    def test_cannot_complete_already_completed(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        client.post(f"/interviews/{int_id}/complete")
        resp = client.post(f"/interviews/{int_id}/complete")
        assert resp.status_code == 409

    def test_invalid_interview_type(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "INVALID_TYPE", "round_number": 1,
        })
        assert resp.status_code == 409

    def test_invalid_interview_status(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.post(f"/interviews/{int_id}/status", json={"status": "BOGUS"})
        assert resp.status_code == 409

    def test_interview_outcome(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        client.post(f"/interviews/{int_id}/complete")
        resp = client.post(f"/interviews/{int_id}/outcome", json={
            "outcome": "NEXT_ROUND",
            "notes": "Strong performance",
        })
        assert resp.status_code == 200

        get_resp = client.get(f"/interviews/{int_id}")
        assert get_resp.json()["outcome"] == "NEXT_ROUND"

    def test_invalid_outcome(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.post(f"/interviews/{int_id}/outcome", json={"outcome": "BOGUS"})
        assert resp.status_code == 409

    def test_interview_feedback(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        resp = client.post(f"/interviews/{int_id}/feedback", json={
            "personal_performance": "Good technical skills",
            "topics": ["Python", "FastAPI"],
            "difficulty": "MEDIUM",
        })
        assert resp.status_code == 200

    def test_multiple_rounds(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        for rnd in range(1, 4):
            resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
                "interview_type": "TECHNICAL", "round_number": rnd,
            })
            assert resp.status_code == 200

        list_resp = client.get(f"/interviews/applications/{app.id}/interviews")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["items"]) == 3

    def test_interview_preserves_old_records(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        # Create old InterviewRecord (Phase 8 style).
        old = InterviewRecord(
            application_id=app.id,
            interview_date=date.today(),
            interview_type="VIDEO",
            round=1,
            status="COMPLETED",
        )
        db.add(old)
        db.commit()

        # Create new Phase 10 interview.
        resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 2,
        })
        assert resp.status_code == 200

        # Old record still exists.
        old_row = db.get(InterviewRecord, old.id)
        assert old_row is not None
        assert old_row.interview_type == "VIDEO"


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

class TestQuestionGeneration:
    def test_generate_questions(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={
            "count": 10,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 10

    def test_questions_have_categories(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={
            "count": 5,
        })
        items = resp.json()["items"]
        for q in items:
            valid_cats = (
                "TECHNICAL", "BEHAVIORAL", "HR", "PROJECT",
                "RESUME_BASED", "ROLE_SPECIFIC",
            )
            assert q["category"] in valid_cats

    def test_questions_from_job_requirements(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(
            f"/interviews/applications/{app.id}/questions/generate",
            json={"count": 20},
        )
        items = resp.json()["items"]
        tech_qs = [q for q in items if q["source"] == "JOB_REQUIREMENT"]
        assert len(tech_qs) > 0

    def test_questions_from_resume(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={"count": 20})
        items = resp.json()["items"]
        resume_qs = [q for q in items if q["source"] == "RESUME_EVIDENCE"]
        assert len(resume_qs) > 0

    def test_deterministic_priority(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={"count": 20})
        items = resp.json()["items"]
        for q in items:
            assert q["priority"] in ("HIGH", "MEDIUM", "LOW")

    def test_filter_by_category(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={
            "count": 10,
            "categories": ["TECHNICAL"],
        })
        items = resp.json()["items"]
        for q in items:
            assert q["category"] == "TECHNICAL"

    def test_list_questions(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        client.post(f"/interviews/applications/{app.id}/questions/generate", json={"count": 5})
        resp = client.get(f"/interviews/applications/{app.id}/questions")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 5


# ---------------------------------------------------------------------------
# Answer practice
# ---------------------------------------------------------------------------

class TestAnswerPractice:
    def test_save_answer(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        gen_resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={"count": 1})
        q_id = gen_resp.json()["items"][0]["id"]

        resp = client.post(f"/interviews/questions/{q_id}/answer", json={
            "draft_answer": "I have extensive experience with this technology.",
        })
        assert resp.status_code == 200
        assert resp.json()["checks"]["empty"] is False

    def test_empty_answer(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        gen_resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={"count": 1})
        q_id = gen_resp.json()["items"][0]["id"]

        resp = client.post(f"/interviews/questions/{q_id}/answer", json={
            "draft_answer": "",
        })
        assert resp.status_code == 422

    def test_answer_feedback(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        gen_resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={"count": 1})
        q_id = gen_resp.json()["items"][0]["id"]

        client.post(f"/interviews/questions/{q_id}/answer", json={
            "draft_answer": "I built a FastAPI backend for a social media analytics tool. I chose Python for its simplicity and the rich ecosystem of libraries available for data processing.",
        })
        resp = client.post(f"/interviews/questions/{q_id}/feedback")
        assert resp.status_code == 200
        fb = resp.json()["feedback"]
        assert fb["label"] in ("STRONG", "GOOD", "NEEDS_IMPROVEMENT", "WEAK")

    def test_no_answer_no_feedback(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        gen_resp = client.post(f"/interviews/applications/{app.id}/questions/generate", json={"count": 1})
        q_id = gen_resp.json()["items"][0]["id"]

        resp = client.post(f"/interviews/questions/{q_id}/feedback")
        assert resp.status_code == 200
        assert resp.json()["feedback"] == {}


# ---------------------------------------------------------------------------
# Mock interview sessions
# ---------------------------------------------------------------------------

class TestMockSessions:
    def test_create_mock_session(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/mock-sessions", json={
            "question_count": 5,
            "technical_pct": 60,
            "behavioral_pct": 40,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] is not None
        assert len(data["questions"]) > 0

    def test_answer_mock_question(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/mock-sessions", json={
            "question_count": 3,
        })
        s_id = create_resp.json()["session_id"]

        resp = client.post(f"/interviews/{s_id}/mock-session/answer", json={
            "question_index": 0,
            "answer": "I built a REST API using Python and FastAPI.",
        })
        assert resp.status_code == 200
        assert resp.json()["progress"]["answered"] == 1

    def test_finish_mock_session(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/mock-sessions", json={
            "question_count": 3,
        })
        s_id = create_resp.json()["session_id"]

        # Answer some questions.
        client.post(f"/interviews/{s_id}/mock-session/answer", json={
            "question_index": 0, "answer": "Python and FastAPI.",
        })

        resp = client.post(f"/interviews/{s_id}/mock-session/finish")
        assert resp.status_code == 200
        summary = resp.json()["final_summary"]
        assert summary["total_questions"] == 3
        assert summary["answered"] >= 1
        assert summary["overall_label"] in ("STRONG", "GOOD", "NEEDS_IMPROVEMENT", "WEAK")

    def test_cannot_answer_after_finish(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/mock-sessions", json={"question_count": 2})
        s_id = create_resp.json()["session_id"]

        client.post(f"/interviews/{s_id}/mock-session/finish")
        resp = client.post(f"/interviews/{s_id}/mock-session/answer", json={
            "question_index": 0, "answer": "Too late.",
        })
        assert resp.status_code == 409

    def test_invalid_question_index(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/mock-sessions", json={"question_count": 2})
        s_id = create_resp.json()["session_id"]

        resp = client.post(f"/interviews/{s_id}/mock-session/answer", json={
            "question_index": 99, "answer": "Out of bounds.",
        })
        assert resp.status_code == 422

    def test_list_mock_sessions(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        client.post(f"/interviews/applications/{app.id}/mock-sessions", json={"question_count": 2})
        client.post(f"/interviews/applications/{app.id}/mock-sessions", json={"question_count": 3})

        resp = client.get(f"/interviews/applications/{app.id}/mock-sessions")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    def test_get_mock_session(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/mock-sessions", json={"question_count": 2})
        s_id = create_resp.json()["session_id"]

        resp = client.get(f"/interviews/{s_id}/mock-session")
        assert resp.status_code == 200
        assert resp.json()["id"] == s_id

    def test_multiple_sessions_persist(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        client.post(f"/interviews/applications/{app.id}/mock-sessions", json={"question_count": 2})
        client.post(f"/interviews/applications/{app.id}/mock-sessions", json={"question_count": 3})

        list_resp = client.get(f"/interviews/applications/{app.id}/mock-sessions")
        items = list_resp.json()["items"]
        assert len(items) == 2
        # Sessions should not overwrite each other.
        assert items[0]["id"] != items[1]["id"]


# ---------------------------------------------------------------------------
# Prep plan
# ---------------------------------------------------------------------------

class TestPrepPlan:
    def test_prep_items_created_with_interview(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })

        resp = client.get(f"/interviews/applications/{app.id}/prep-items")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) > 0
        labels = [i["label"] for i in items]
        assert "Resume questions" in labels
        assert "Mock interview" in labels

    def test_update_prep_item_status(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        items_resp = client.get(f"/interviews/applications/{app.id}/prep-items")
        item_id = items_resp.json()["items"][0]["id"]

        resp = client.patch(f"/interviews/prep-items/{item_id}", json={"status": "COMPLETED"})
        assert resp.status_code == 200

        updated = client.get(f"/interviews/applications/{app.id}/prep-items")
        item = next(i for i in updated.json()["items"] if i["id"] == item_id)
        assert item["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------

class TestDataIntegrity:
    def test_application_history_untouched(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        events_before = db.scalars(
            select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)
        ).all()

        client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })

        events_after = db.scalars(
            select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)
        ).all()

        # Interview creation adds events but doesn't modify old ones.
        assert len(events_after) >= len(events_before)

    def test_old_interview_records_preserved(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        old = InterviewRecord(
            application_id=app.id,
            interview_date=date(2026, 1, 15),
            interview_type="HR",
            round=1,
            status="COMPLETED",
        )
        db.add(old)
        db.commit()
        old_id = old.id

        client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 2,
        })

        old_row = db.get(InterviewRecord, old_id)
        assert old_row is not None
        assert old_row.interview_type == "HR"

    def test_no_fabricated_interviewer_details(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = resp.json()["interview_id"]

        detail = client.get(f"/interviews/{int_id}").json()
        # No interviewer details should be fabricated.
        assert detail["interviewer_name"] is None
        assert detail["interviewer_role"] is None


# ---------------------------------------------------------------------------
# Lifecycle fabrication regression
# ---------------------------------------------------------------------------

class TestInterviewOutcomeNoFabrication:
    """Completing an interview or recording an outcome must NOT fabricate
    application lifecycle transitions.  Only explicit, verified external
    evidence (e.g. a recorded response) should move the application."""

    def test_complete_interview_does_not_fabricate_response(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]

        # Interview creation legitimately moves app to INTERVIEW.
        db.expire_all()
        app = db.get(Application, app.id)
        assert app.lifecycle_status == "INTERVIEW"

        # Complete the interview — this must NOT move the application further.
        resp = client.post(f"/interviews/{int_id}/complete")
        assert resp.status_code == 200

        db.expire_all()
        app = db.get(Application, app.id)
        assert app.lifecycle_status == "INTERVIEW", (
            "Completing an interview must not fabricate a lifecycle transition"
        )

    def test_complete_interview_does_not_fabricate_offer(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "INTERVIEW")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "FINAL", "round_number": 3,
        })
        int_id = create_resp.json()["interview_id"]

        client.post(f"/interviews/{int_id}/complete")

        db.expire_all()
        app = db.get(Application, app.id)
        assert app.lifecycle_status == "INTERVIEW", (
            "Completing an interview must not fabricate an offer transition"
        )

    def test_outcome_passed_does_not_move_application(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]
        client.post(f"/interviews/{int_id}/complete")

        # Interview creation moved app to INTERVIEW; PASSED outcome must NOT
        # move it further (e.g. to RESPONSE_RECEIVED or OFFER).
        resp = client.post(f"/interviews/{int_id}/outcome", json={
            "outcome": "PASSED", "notes": "Strong performance",
        })
        assert resp.status_code == 200

        db.expire_all()
        app = db.get(Application, app.id)
        assert app.lifecycle_status == "INTERVIEW", (
            "PASSED outcome must not fabricate a lifecycle transition"
        )

    def test_outcome_offer_does_not_move_application(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "INTERVIEW")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "FINAL", "round_number": 2,
        })
        int_id = create_resp.json()["interview_id"]
        client.post(f"/interviews/{int_id}/complete")

        resp = client.post(f"/interviews/{int_id}/outcome", json={
            "outcome": "OFFER", "notes": "Verbal offer received",
        })
        assert resp.status_code == 200

        db.expire_all()
        app = db.get(Application, app.id)
        assert app.lifecycle_status == "INTERVIEW", (
            "OFFER outcome must not fabricate an application transition"
        )

    def test_outcome_next_round_is_explicit_only(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]
        client.post(f"/interviews/{int_id}/complete")

        resp = client.post(f"/interviews/{int_id}/outcome", json={
            "outcome": "NEXT_ROUND",
        })
        assert resp.status_code == 200

        get_resp = client.get(f"/interviews/{int_id}")
        assert get_resp.json()["outcome"] == "NEXT_ROUND"

        db.expire_all()
        app = db.get(Application, app.id)
        assert app.lifecycle_status == "INTERVIEW"

    def test_outcome_rejected_does_not_move_application(self, client_session):
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "INTERVIEW")
        db.commit()

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "BEHAVIORAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]
        client.post(f"/interviews/{int_id}/complete")

        resp = client.post(f"/interviews/{int_id}/outcome", json={
            "outcome": "REJECTED", "notes": "Did not pass",
        })
        assert resp.status_code == 200

        db.expire_all()
        app = db.get(Application, app.id)
        assert app.lifecycle_status == "INTERVIEW", (
            "REJECTED outcome must not fabricate a lifecycle transition"
        )

    def test_timeline_immutable_after_outcome(self, client_session):
        """Events recorded before the outcome must remain unchanged."""
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "SUBMISSION_CONFIRMED")
        db.commit()

        # Record initial event count.
        events_before = list(
            db.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == app.id)
                .order_by(ApplicationEvent.created_at)
            ).all()
        )
        count_before = len(events_before)  # noqa: F841

        create_resp = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        int_id = create_resp.json()["interview_id"]
        client.post(f"/interviews/{int_id}/complete")
        client.post(f"/interviews/{int_id}/outcome", json={"outcome": "PASSED"})

        db.expire_all()
        events_after = list(
            db.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == app.id)
                .order_by(ApplicationEvent.created_at)
            ).all()
        )
        # Events before the outcome must be unchanged (same ids, same statuses).
        for i, ev in enumerate(events_before):
            assert events_after[i].id == ev.id
            assert events_after[i].event_type == ev.event_type
            assert events_after[i].previous_status == ev.previous_status
            assert events_after[i].new_status == ev.new_status

    def test_multiple_interview_rounds_independent(self, client_session):
        """Multiple interview rounds do not overwrite each other."""
        client, db = client_session
        profile = _seed_profile(db)
        resume = _seed_resume(db, profile)
        job = _seed_job(db)
        app = _seed_app_at_status(db, job, profile, resume, "INTERVIEW")
        db.commit()

        # Create two rounds.
        r1 = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "TECHNICAL", "round_number": 1,
        })
        r2 = client.post(f"/interviews/applications/{app.id}/interviews", json={
            "interview_type": "BEHAVIORAL", "round_number": 2,
        })
        id1, id2 = r1.json()["interview_id"], r2.json()["interview_id"]

        # Complete round 1, set PASSED.
        client.post(f"/interviews/{id1}/complete")
        client.post(f"/interviews/{id1}/outcome", json={"outcome": "PASSED"})

        # Round 2 is still SCHEDULED / PENDING.
        g1 = client.get(f"/interviews/{id1}").json()
        g2 = client.get(f"/interviews/{id2}").json()
        assert g1["status"] == "COMPLETED"
        assert g1["outcome"] == "PASSED"
        assert g2["status"] == "SCHEDULED"
        assert g2["outcome"] == "PENDING"

        # Complete round 2, set REJECTED.
        client.post(f"/interviews/{id2}/complete")
        client.post(f"/interviews/{id2}/outcome", json={"outcome": "REJECTED"})

        g1 = client.get(f"/interviews/{id1}").json()
        g2 = client.get(f"/interviews/{id2}").json()
        assert g1["outcome"] == "PASSED", "Round 1 outcome must not be overwritten"
        assert g2["outcome"] == "REJECTED"
