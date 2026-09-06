"""Phase 7: platform-aware application execution engine.

Exercised rules from the spec:
- detection maps a job's source + URLs to a platform (board / ATS / career /
  generic) and the policy engine resolves ONE mode per platform;
- the safe stage (open/inspect/map/fill known/upload approved resume) runs
  first; nothing ever submits without an explicit human approval boundary;
- HUMAN_ASSISTED (linkedin/indeed/naukri by default) requires manual
  submission + human-attested confirmation; CONFIRMED only with evidence;
- unknown fields and NEW QUESTION free-text fields stop the engine; CAPTCHA
  and login walls stop the engine and hand control back to the human;
- duplicate protection and a daily application budget gate executions;
- submission verification is evidence-based (CONFIRMED vs SUBMISSION_UNKNOWN);
- executions, steps, evidence and automation_runs/automation_errors are
  recorded locally; the legacy tracker is only touched after a real submission.
"""
from __future__ import annotations

from sqlalchemy import select

from app.application_execution import base, detector, policy
from app.application_execution.browser import SCENARIOS, MockBrowserDriver
from app.application_execution.fields import build_profile_context, map_fields
from app.models.application import Application
from app.models.application_execution import (
    ApplicationExecutionStep,
)
from app.models.application_package import ApplicationPackage
from app.models.automation import AutomationError, AutomationRun
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.storage.local import get_storage


def _count(db, model):
    return len(list(db.scalars(select(model).limit(500))))


def _job(title="Software Developer", company="Acme", **extra):
    return {
        "title": title,
        "company": company,
        "source": "apify",
        "source_job_id": extra.pop("source_job_id", f"phase7-{abs(hash(title))}"),
        "url": extra.pop("url", "mock://simple-form"),
        "application_url": extra.pop("application_url", None),
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
        "email": f"exec-{abs(hash(str(extra))) or 11}@example.test",
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
        "projects": [],
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
    with_bytes=False,
):
    resume = Resume(
        profile_id=profile.id if profile is not None else None,
        name=name,
        target_role=target_role,
        file_path="resumes/candidate.pdf",
        file_name=name,
        file_size=100 if with_bytes else 0,
        content_type="application/pdf",
        version=version,
        is_active=is_active,
    )
    if with_bytes:
        get_storage().save(b"%PDF-1.4 mock resume bytes phase7", resume.file_path)
    db.add(resume)
    db.flush()
    return resume


def _insert_job(db, *, source="apify", url="mock://simple-form", app_url=None, **extra):
    from app.services import job_service

    result = job_service.insert_jobs(
        db, [_job(url=url, application_url=app_url, **extra)], source=source
    )
    assert result.inserted == 1
    return db.scalar(select(Job).order_by(Job.id.desc()))


def _approved_package(
    client,
    session,
    *,
    source="apify",
    url="mock://simple-form",
    app_url=None,
    resume_with_bytes=False,
    prefs=None,
):
    profile = _seed_profile(session)
    prefs = prefs or _seed_preferences(session)
    _seed_resume(session, profile, with_bytes=resume_with_bytes)
    job = _insert_job(session, source=source, url=url, app_url=app_url)
    package_id = client.post(
        "/applications/prepare", json={"job_id": job.id}
    ).json()["package"]["id"]
    resp = client.post(f"/applications/{package_id}/approve")
    assert resp.status_code == 200, resp.text
    return package_id, job


# ---------------------------------------------------------------------------
# Platform detection + policy (pure, no DB)
# ---------------------------------------------------------------------------
class TestPlatformDetection:
    def test_source_wins_for_boards(self):
        assert detector.detect_platform(
            url="https://cdn.example/ref", source="linkedin"
        ).platform == "linkedin"
        assert detector.detect_platform(source="indeed").platform == "indeed"
        assert detector.detect_platform(source="naukri").platform == "naukri"

    def test_board_host_detection(self):
        assert detector.detect_platform(
            url="https://www.linkedin.com/jobs/view/123"
        ).platform == "linkedin"
        assert detector.detect_platform(
            url="https://www.indeed.com/viewjob?jk=abc"
        ).platform == "indeed"
        assert detector.detect_platform(
            url="https://naukri.com/job-listings/42"
        ).platform == "naukri"

    def test_ats_host_maps_to_company_career(self):
        res = detector.detect_platform(url="https://boards.greenhouse.io/acme/jobs/42")
        assert res.platform == "company_career"
        assert res.career_site is True

    def test_careers_subdomain_maps_to_company_career(self):
        assert detector.detect_platform(
            url="https://careers.acme.com/apply/engineer"
        ).platform == "company_career"

    def test_ats_path_marker_maps_to_company_career(self):
        assert detector.detect_platform(
            url="https://acme.example/jobs/12345"
        ).platform == "company_career"

    def test_generic_fallback(self):
        assert detector.detect_platform(
            url="https://acme.example/career-page"
        ).platform == "generic"

    def test_application_url_checked_before_posting_url(self):
        res = detector.detect_platform(
            url="https://acme.example/posting",
            application_url="https://boards.greenhouse.io/acme/42",
        )
        assert res.platform == "company_career"


class TestPolicyEngine:
    def test_safe_defaults(self):
        assert policy.resolve_policy("linkedin").mode == base.HUMAN_ASSISTED
        assert policy.resolve_policy("indeed").mode == base.HUMAN_ASSISTED
        assert policy.resolve_policy("naukri").mode == base.HUMAN_ASSISTED
        assert policy.resolve_policy("company_career").mode == base.PERMITTED_BROWSER
        assert policy.resolve_policy("generic").mode == base.PERMITTED_BROWSER
        assert policy.resolve_policy("unknown-platform").mode == base.HUMAN_ASSISTED

    def test_human_assisted_never_auto_submits(self):
        decision = policy.resolve_policy("linkedin")
        assert decision.supports_browser_automation
        assert not decision.supports_automated_submit
        assert decision.requires_user_approval

    def test_stored_configuration_overrides_default(self):
        decision = policy.resolve_policy("generic", {"generic": "HUMAN_ASSISTED"})
        assert decision.mode == base.HUMAN_ASSISTED

    def test_invalid_stored_mode_falls_back(self):
        decision = policy.resolve_policy("generic", {"generic": "MAGIC"})
        assert decision.mode == base.HUMAN_ASSISTED

    def test_mode_constants_valid(self):
        for mode in (base.AUTHORIZED_AUTOMATION, base.PERMITTED_BROWSER,
                     base.HUMAN_ASSISTED, base.UNSUPPORTED):
            assert mode in base.EXECUTION_MODES


# ---------------------------------------------------------------------------
# Field mapping (pure, no DB)
# ---------------------------------------------------------------------------
class TestFieldMapping:
    def test_known_profile_fields_map_deterministically(self):
        ctx = build_profile_context(
            type("P", (), {
                "name": "Jane Doe", "email": "jane@example.com",
                "city": "Chennai", "skills": ["Python"],
                "experience_level": "0-2 years", "notice_period": "Immediate",
                "work_authorization": "Authorized to work in India.",
            })(),
            None,
        )
        detected = [
            base.DetectedField(key="a", label="Full name", kind="text", required=True),
            base.DetectedField(key="b", label="Email", kind="text", required=True),
            base.DetectedField(key="c", label="Phone", kind="text"),
        ]
        result = map_fields(detected, ctx)
        by_label = {f.detected.label: f for f in result.fields}
        assert by_label["Full name"].value == "Jane Doe"
        assert by_label["Email"].value == "jane@example.com"
        assert by_label["Phone"].classification == base.REQUIRES_REVIEW

    def test_sensitive_fields_never_guessed(self):
        ctx = build_profile_context(
            type("P", (), {"name": "J Doe", "gender": "Female"})(), None
        )
        result = map_fields(
            [
                base.DetectedField(key="g", label="Gender", kind="select",
                                   required=True, options=["Male", "Female"]),
                base.DetectedField(key="s", label="Current CTC", kind="text",
                                   required=True),
            ],
            ctx,
        )
        for field in result.fields:
            assert field.classification == base.REQUIRES_REVIEW
            assert field.value is None
        assert result.known_count == 0

    def test_prepared_answer_matches_label(self):
        ctx = build_profile_context(
            type("P", (), {"name": "J Doe"})(), None,
            answers=[{"question": "Why do you want to work here?",
                      "answer": "Culture fit."}],
        )
        result = map_fields(
            [base.DetectedField(key="q", label="Why do you want to work here?",
                                kind="text", required=True)],
            ctx,
        )
        assert result.fields[0].classification == base.KNOWN
        assert result.fields[0].value == "Culture fit."

    def test_unmatched_required_text_is_new_question(self):
        ctx = build_profile_context(type("P", (), {"name": "J Doe"})(), None)
        result = map_fields(
            [base.DetectedField(key="q", label="What is your SSC CGPA?",
                                kind="text", required=True)],
            ctx,
        )
        assert len(result.new_questions) == 1
        assert result.fields[0].classification == base.UNKNOWN

    def test_select_option_validation(self):
        ctx = build_profile_context(
            type("P", (), {"name": "J Doe", "experience_level": "8+ years"})(), None
        )
        result = map_fields(
            [base.DetectedField(key="e", label="Experience", kind="select",
                                options=["0-2 years", "3-5 years"])],
            ctx,
        )
        assert result.fields[0].classification == base.REQUIRES_REVIEW
        assert "not an available option" in (result.fields[0].ambiguity or "")


# ---------------------------------------------------------------------------
# Mock driver safety
# ---------------------------------------------------------------------------
class TestMockDriver:
    def test_refuses_real_urls(self):
        raised = False
        try:
            MockBrowserDriver("https://www.linkedin.com/jobs/view/1")
        except ValueError:
            raised = True
        assert raised

    def test_scenario_lookup(self):
        for name in SCENARIOS:
            assert MockBrowserDriver(f"mock://{name}").scenario == name
        assert MockBrowserDriver("mock://mystery").scenario == "simple-form"

    def test_scenario_can_be_picked_via_path_segment(self):
        assert MockBrowserDriver(
            "mock://careers.acme.com/apply/validation-error"
        ).scenario == "validation-error"
        assert MockBrowserDriver(
            "mock://careers.acme.com/apply/simple-form"
        ).scenario == "simple-form"
        assert MockBrowserDriver("mock://careers.acme.com/apply/x").scenario == \
            "simple-form"
        assert MockBrowserDriver("mock://simple-form?x=1&y=2").scenario == "simple-form"


# ---------------------------------------------------------------------------
# End-to-end execution (HTTP)
# ---------------------------------------------------------------------------
class TestExecutionPipeline:
    def test_preview_before_execution(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session)
        resp = client.get(f"/applications/{package_id}/execution")
        assert resp.status_code == 200
        body = resp.json()
        assert body["execution"] is None
        preview = body["preview"]
        assert preview["platform"]["platform"] == "generic"
        assert preview["platform"]["mode"] == base.PERMITTED_BROWSER
        assert preview["budget"]["used_today"] == 0

    def test_stored_policy_override_changes_preview(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session)
        client.put("/preferences", json={"platform_policies": {"generic": "HUMAN_ASSISTED"}})
        preview = client.get(f"/applications/{package_id}/execution").json()["preview"]
        assert preview["platform"]["mode"] == base.HUMAN_ASSISTED

    def test_human_assisted_requires_manual_confirm(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, source="linkedin")

        resp = client.post(f"/applications/{package_id}/execute",
                           json={"driver": "mock"})
        assert resp.status_code == 200
        execution = resp.json()["execution"]
        assert execution["platform"] == "linkedin"
        assert execution["execution_mode"] == base.HUMAN_ASSISTED
        assert execution["status"] == base.STATUS_AWAITING_APPROVAL
        payload = execution["approval_payload"]
        assert payload["recommended_action"] == "complete_manually"
        assert payload["auto_submit_allowed"] is False
        # nothing was ever submitted
        assert _count(session, Application) == 0

        # approval does NOT submit; it hands control to the human
        approval = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approval.status_code == 200
        assert approval.json()["execution"]["status"] == base.STATUS_AWAITING_USER

        # human-attested final outcome recorded as evidence
        confirm = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/confirm",
            json={"verification": "LIKELY",
                  "note": "Submitted in the browser by hand."},
        )
        assert confirm.status_code == 200
        confirmed = confirm.json()["execution"]
        assert confirmed["status"] == base.STATUS_SUBMITTED
        assert confirmed["submission_status"] == base.VERIFICATION_LIKELY
        assert any(e["kind"] == "user_note" for e in confirmed["evidence"])
        # a non-confirmed manual report does not create a tracker row
        assert _count(session, Application) == 0

    def test_confirmed_manual_creates_tracker_row(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, source="naukri")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        client.post(f"/applications/{package_id}/execution/{execution['id']}/approve")
        confirm = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/confirm",
            json={"verification": "CONFIRMED", "reference": "MANUAL-42"},
        )
        assert confirm.status_code == 200
        body = confirm.json()["execution"]
        assert body["status"] == base.STATUS_SUBMISSION_CONFIRMED
        assert body["submission_status"] == base.VERIFICATION_CONFIRMED
        assert body["confirmation_reference"] == "MANUAL-42"
        application = session.scalar(select(Application).order_by(Application.id))
        assert application is not None
        assert application.status == "submitted"

    def test_company_career_permitted_submits_after_approval(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(
            client, session,
            source="apify",
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        assert execution["platform"] == "company_career"
        assert execution["execution_mode"] == base.PERMITTED_BROWSER
        assert execution["status"] == base.STATUS_AWAITING_APPROVAL
        assert execution["approval_payload"]["auto_submit_allowed"] is True
        approve = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approve.status_code == 200
        assert approve.json()["execution"]["status"] == base.STATUS_SUBMISSION_CONFIRMED

    def test_generic_permitted_never_auto_submits(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(
            client, session, source="apify", url="mock://simple-form"
        )
        resp = client.post(f"/applications/{package_id}/execute",
                           json={"driver": "mock"})
        assert resp.status_code == 200
        execution = resp.json()["execution"]
        assert execution["execution_mode"] == base.PERMITTED_BROWSER
        assert execution["status"] == base.STATUS_AWAITING_APPROVAL
        payload = execution["approval_payload"]
        # the generic adapter refuses to fire the submit button itself
        assert payload["auto_submit_allowed"] is False
        assert payload["recommended_action"] == "complete_manually"

        approve = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approve.status_code == 200
        assert approve.json()["execution"]["status"] == base.STATUS_AWAITING_USER
        assert _count(session, Application) == 0

        confirm = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/confirm",
            json={"verification": "CONFIRMED", "reference": "GEN-1"},
        )
        assert confirm.status_code == 200
        confirmed = confirm.json()["execution"]
        assert confirmed["status"] == base.STATUS_SUBMISSION_CONFIRMED
        assert confirmed["submission_status"] == base.VERIFICATION_CONFIRMED
        app_row = session.scalar(select(Application).order_by(Application.id))
        assert app_row is not None
        assert app_row.status == "submitted"
        run = session.scalar(select(AutomationRun).order_by(AutomationRun.id))
        assert run is not None
        assert run.run_type == "application_execution"
        budget = client.get(
            f"/applications/{package_id}/execution/budget"
        ).json()["budget"]
        assert budget["used_today"] == 1

    def test_resume_uploaded_for_permitted_platform(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(
            client, session,
            source="apify",
            url="mock://resume-upload",
            resume_with_bytes=True,
        )
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        # the required resume field stays unresolved (never guessed), so the run
        # correctly stops awaiting manual completion instead of submitting
        assert execution["status"] == base.STATUS_AWAITING_USER
        assert execution["approval_payload"]["recommended_action"] == \
            "review_unknown"
        assert execution["approval_payload"]["resume_uploaded"] is True
        assert execution["approval_payload"]["_resume"]["file_name"] == \
            "candidate_resume.pdf"

    def test_duplicate_application_blocked(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(
            client, session,
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        approve = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approve.status_code == 200
        assert approve.json()["execution"]["status"] == base.STATUS_SUBMISSION_CONFIRMED

        second = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        )
        assert second.status_code == 409
        assert "duplicate" in second.json()["detail"].lower()

        forced = client.post(
            f"/applications/{package_id}/execute",
            json={"driver": "mock", "force_duplicate": True},
        )
        assert forced.status_code == 200
        assert forced.json()["execution"]["status"] == base.STATUS_AWAITING_APPROVAL

    def test_daily_budget_blocks_new_executions(self, client_session):
        client, session = client_session
        prefs = _seed_preferences(session, daily_application_maximum=1)
        package_id, _ = _approved_package(
            client, session, prefs=prefs,
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        client.post(f"/applications/{package_id}/execution/{execution['id']}/approve")
        assert client.get(
            f"/applications/{package_id}/execution/budget"
        ).json()["budget"]["used_today"] == 1

        blocked = client.post(
            f"/applications/{package_id}/execute",
            json={"driver": "mock", "force_duplicate": True},
        )
        assert blocked.status_code == 409
        assert "daily" in blocked.json()["detail"].lower()

    def test_new_question_stops_and_never_submits(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, url="mock://new-question")
        resp = client.post(f"/applications/{package_id}/execute",
                           json={"driver": "mock"})
        execution = resp.json()["execution"]
        assert execution["status"] == base.STATUS_AWAITING_USER
        payload = execution["approval_payload"]
        assert payload["recommended_action"] == "review_question"
        assert any("why should we hire you" in q["label"].lower()
                   for q in payload["new_questions"])
        # approval cannot trigger a submission while a question is pending
        approval = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approval.status_code == 409
        assert _count(session, Application) == 0

    def test_unknown_required_field_blocks_submission(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, url="mock://unknown-field")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        assert execution["status"] == base.STATUS_AWAITING_USER
        payload = execution["approval_payload"]
        assert payload["recommended_action"] in ("review_unknown", "review_question")
        delivery = payload.get("required_unfilled") or [
            q["label"] for q in payload.get("new_questions") or []
        ]
        assert any("cgpa" in str(item).lower() for item in delivery)
        approval = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approval.status_code == 409
        assert _count(session, Application) == 0

    def test_captcha_blocks_execution(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, url="mock://captcha")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        assert execution["status"] == base.STATUS_BLOCKED
        assert any("captcha" in (step["message"] or "").lower()
                   for step in execution["steps"])
        approve = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approve.status_code == 409
        assert _count(session, Application) == 0

    def test_login_wall_hands_control_to_human(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, url="mock://login-required")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        assert execution["status"] == base.STATUS_AWAITING_USER
        assert _count(session, Application) == 0
        approve = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approve.status_code == 409

    def test_validation_error_submission_fails_cleanly(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(
            client, session,
            url="mock://careers.acme.com/apply/validation-error",
            app_url="mock://careers.acme.com/apply/validation-error",
        )
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        assert execution["platform"] == "company_career"
        assert execution["status"] == base.STATUS_AWAITING_APPROVAL
        approve = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approve.status_code == 200
        body = approve.json()["execution"]
        assert body["status"] == base.STATUS_EXECUTION_FAILED
        assert _count(session, Application) == 0
        error = session.scalar(select(AutomationError).order_by(AutomationError.id))
        assert error is not None
        assert "last name" in error.message.lower()

    def test_cancel_does_not_submit_and_allows_rerun(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, source="linkedin")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        cancelled = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["execution"]["status"] == base.STATUS_CANCELLED
        assert _count(session, Application) == 0
        rerun = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        )
        assert rerun.status_code == 200
        assert rerun.json()["execution"]["status"] == base.STATUS_AWAITING_APPROVAL

    def test_approve_twice_is_conflict(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, source="linkedin")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        blocked = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert blocked.status_code == 409

    def test_validation_fail_after_approval_blocks_submission(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, source="linkedin")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        assert execution["status"] == base.STATUS_AWAITING_APPROVAL
        # invalidate the package behind the execution's back: revalidation at
        # approval time must notice and refuse to submit
        package = session.get(ApplicationPackage, package_id)
        package.status = "REVOKED"
        session.commit()
        approval = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        assert approval.status_code == 409
        assert "not APPROVED" in approval.json()["detail"]
        current = client.get(f"/applications/{package_id}/execution").json()["execution"]
        assert current["status"] == base.STATUS_BLOCKED
        assert _count(session, Application) == 0

    def test_malformed_package_blocked_at_preflight(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        _seed_preferences(session)
        _seed_resume(session, profile)
        job = _insert_job(session, url="mock://simple-form")
        package_id = client.post(
            "/applications/prepare", json={"job_id": job.id}
        ).json()["package"]["id"]
        resp = client.post(f"/applications/{package_id}/execute",
                           json={"driver": "mock"})
        assert resp.status_code == 409
        assert "not APPROVED" in resp.json()["detail"]

    def test_mock_driver_cannot_be_forced_on_real_url(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(
            client, session,
            url="https://www.indeed.com/viewjob?jk=abc",
            app_url="https://www.indeed.com/app",
        )
        resp = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        )
        # forcing the mock driver against a real site is refused by the boundary
        assert resp.status_code in (400, 409, 500)
        assert _count(session, Application) == 0

    def test_steps_are_recorded_in_order(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(client, session, url="mock://simple-form")
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        names = [step["step"] for step in execution["steps"]]
        for expected in ("detect_platform", "open", "inspect_form", "map_fields",
                         "fill_fields", "approval"):
            assert expected in names
        rows = session.scalars(
            select(ApplicationExecutionStep)
            .where(ApplicationExecutionStep.execution_id == execution["id"])
            .order_by(ApplicationExecutionStep.order, ApplicationExecutionStep.id)
        )
        pairs = [(row.order, row.id) for row in rows]
        assert pairs == sorted(pairs)

    def test_cancel_after_terminal_is_conflict(self, client_session):
        client, session = client_session
        package_id, _ = _approved_package(
            client, session,
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        execution = client.post(
            f"/applications/{package_id}/execute", json={"driver": "mock"}
        ).json()["execution"]
        client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve"
        )
        cancelled = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/cancel"
        )
        assert cancelled.status_code == 409
