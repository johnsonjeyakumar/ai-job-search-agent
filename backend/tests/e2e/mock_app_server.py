"""Local mock application server for Phase 18 E2E tests.

Serves deterministic HTML pages that mimic job application forms.
DO NOT connect tests to real employer websites.
"""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


class _MockHandler(BaseHTTPRequestHandler):
    """Routes requests to mock application pages."""

    # Shared mutable state for controlling page behavior per test.
    scenario: dict = {}
    submitted_data: list[dict] = []
    uploaded_files: dict[str, bytes] = {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        routes: dict[str, callable] = {
            "/": self._page_single_basic,
            "/single-basic": self._page_single_basic,
            "/single-advanced": self._page_single_advanced,
            "/multi-page-1": self._page_multi_1,
            "/multi-page-2": self._page_multi_2,
            "/multi-page-3": self._page_multi_3,
            "/multi-page-review": self._page_multi_review,
            "/conditional": self._page_conditional,
            "/conditional-2": self._page_conditional_2,
            "/file-upload": self._page_file_upload,
            "/auth-required": self._page_auth_required,
            "/mfa-required": self._page_mfa_required,
            "/approval-required": self._page_approval_required,
            "/review": self._page_review,
            "/confirmation": self._page_confirmation,
            "/uncertain": self._page_uncertain,
            "/captcha": self._page_captcha,
            "/stale-field": self._page_stale_field,
            "/autocomplete": self._page_autocomplete,
            "/autocomplete-suggestions": self._api_autocomplete_suggestions,
            # Phase 19 submission verification scenarios
            "/confirm-with-ref": self._page_confirm_with_reference,
            "/confirm-no-ref": self._page_confirm_no_reference,
            "/uncertain-submit": self._page_uncertain_submit,
            "/rejected": self._page_rejected,
            "/duplicate-warning": self._page_duplicate_warning,
            "/delayed-confirm": self._page_delayed_confirm,
            "/network-error": self._page_network_error,
            # Phase 20 preflight scenarios
            "/job-active": self._page_job_active,
            "/job-closed": self._page_job_closed,
            "/job-removed": self._page_job_removed,
            "/job-expired-deadline": self._page_job_expired_deadline,
            # Phase 21 question scenarios
            "/questions/normal": self._page_question_normal,
            "/questions/work-auth": self._page_question_work_auth,
            "/questions/sponsorship": self._page_question_sponsorship,
            "/questions/experience-knockout": self._page_question_experience_knockout,
            "/questions/relocation": self._page_question_relocation,
            "/questions/availability": self._page_question_availability,
            "/questions/salary": self._page_question_salary,
            "/questions/demographic": self._page_question_demographic,
            "/questions/declaration": self._page_question_declaration,
            "/questions/attestation": self._page_question_attestation,
            "/questions/consent-required": self._page_question_consent_required,
            "/questions/consent-optional": self._page_question_consent_optional,
            "/questions/signature": self._page_question_signature,
            "/questions/mixed": self._page_question_mixed,
        }
        handler = routes.get(path, self._page_not_found)
        handler()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        if path == "/submit":
            self._handle_submit(body)
        elif path == "/auth-check":
            self._handle_auth_check(body)
        elif path == "/mfa-verify":
            self._handle_mfa_verify(body)
        elif path == "/upload":
            self._handle_upload(body)
        else:
            self._respond(404, "Not found")

    # ── response helpers ────────────────────────────────────────────────

    def _respond(self, code: int, html: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _respond_json(self, code: int, data: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    # ── page: single basic ──────────────────────────────────────────────

    def _page_single_basic(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Job Application</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form id="application-form" action="/submit" method="post">
  <label for="full_name">Full Name</label>
  <input id="full_name" name="full_name" type="text" required placeholder="John Doe">

  <label for="email">Email Address</label>
  <input id="email" name="email" type="email" required placeholder="john@example.com">

  <label for="phone">Phone Number</label>
  <input id="phone" name="phone" type="tel" required placeholder="555-0100">

  <label for="linkedin">LinkedIn Profile</label>
  <input id="linkedin" name="linkedin" type="url" placeholder="https://linkedin.com/in/johndoe">

  <label for="cover_letter">Cover Letter</label>
  <textarea id="cover_letter" name="cover_letter" rows="5" placeholder="Tell us about yourself..."></textarea>

  <label for="resume">Resume (PDF)</label>
  <input id="resume" name="resume" type="file" accept=".pdf,.docx" required>

  <button type="submit">Submit Application</button>
</form>
</body></html>""")

    # ── page: single advanced ───────────────────────────────────────────

    def _page_single_advanced(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Advanced Application</title></head>
<body>
<h1>Advanced Job Application</h1>
<form id="advanced-form" action="/submit" method="post">
  <label for="full_name">Full Name</label>
  <input id="full_name" name="full_name" type="text" required>

  <label for="email">Email</label>
  <input id="email" name="email" type="email" required>

  <fieldset>
    <legend>Employment Type</legend>
    <label><input type="radio" name="employment_type" value="full_time" required> Full Time</label>
    <label><input type="radio" name="employment_type" value="part_time"> Part Time</label>
    <label><input type="radio" name="employment_type" value="contract"> Contract</label>
  </fieldset>

  <fieldset>
    <legend>Programming Languages (select all that apply)</legend>
    <label><input type="checkbox" name="languages" value="python"> Python</label>
    <label><input type="checkbox" name="languages" value="javascript"> JavaScript</label>
    <label><input type="checkbox" name="languages" value="java"> Java</label>
    <label><input type="checkbox" name="languages" value="go"> Go</label>
    <label><input type="checkbox" name="languages" value="rust"> Rust</label>
  </fieldset>

  <label for="experience">Years of Experience</label>
  <select id="experience" name="experience" required>
    <option value="">Select...</option>
    <option value="0-1">0-1 years</option>
    <option value="2-4">2-4 years</option>
    <option value="5-7">5-7 years</option>
    <option value="8+">8+ years</option>
  </select>

  <label for="start_date">Available Start Date</label>
  <input id="start_date" name="start_date" type="date" required>

  <label for="salary">Expected Salary (USD)</label>
  <input id="salary" name="salary" type="number" min="0" step="1000" placeholder="85000">

  <label for="city">City</label>
  <input id="city" name="city" type="text" placeholder="San Francisco">

  <label for="terms">I agree to the Terms and Conditions</label>
  <input id="terms" name="terms" type="checkbox" required>

  <label for="resume">Resume</label>
  <input id="resume" name="resume" type="file" accept=".pdf,.docx" required>

  <button type="submit">Submit Application</button>
</form>
</body></html>""")

    # ── page: multi-page step 1 ─────────────────────────────────────────

    def _page_multi_1(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Step 1 - Personal Info</title></head>
<body>
<h1>Step 1 of 3: Personal Information</h1>
<form id="step1-form" action="/submit" method="post">
  <input type="hidden" name="_step" value="1">

  <label for="full_name">Full Name</label>
  <input id="full_name" name="full_name" type="text" required>

  <label for="email">Email</label>
  <input id="email" name="email" type="email" required>

  <label for="phone">Phone</label>
  <input id="phone" name="phone" type="tel" required>

  <a href="/multi-page-2" id="next-step">Next Step &rarr;</a>
</form>
</body></html>""")

    def _page_multi_2(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Step 2 - Details</title></head>
<body>
<h1>Step 2 of 3: Job Details</h1>
<form id="step2-form" action="/submit" method="post">
  <input type="hidden" name="_step" value="2">

  <label for="city">City</label>
  <input id="city" name="city" type="text" required>

  <fieldset>
    <legend>Employment Type</legend>
    <label><input type="radio" name="employment_type" value="full_time" required> Full Time</label>
    <label><input type="radio" name="employment_type" value="part_time"> Part Time</label>
  </fieldset>

  <label for="start_date">Start Date</label>
  <input id="start_date" name="start_date" type="date" required>

  <label for="salary">Expected Salary</label>
  <input id="salary" name="salary" type="number" min="0" step="1000">

  <a href="/multi-page-3" id="next-step">Next Step &rarr;</a>
</form>
</body></html>""")

    def _page_multi_3(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Step 3 - Documents</title></head>
<body>
<h1>Step 3 of 3: Documents</h1>
<form id="step3-form" action="/submit" method="post">
  <input type="hidden" name="_step" value="3">

  <label for="resume">Resume (PDF)</label>
  <input id="resume" name="resume" type="file" accept=".pdf,.docx" required>

  <label for="cover_letter">Cover Letter (PDF)</label>
  <input id="cover_letter" name="cover_letter" type="file" accept=".pdf,.docx">

  <label for="portfolio">Portfolio URL</label>
  <input id="portfolio" name="portfolio" type="url" placeholder="https://portfolio.example.com">

  <a href="/multi-page-review" id="next-step">Review &amp; Submit</a>
</form>
</body></html>""")

    def _page_multi_review(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Review Application</title></head>
<body>
<h1>Review Your Application</h1>
<div id="review-summary">
  <p>Please review your information before submitting.</p>
</div>
<form id="review-form" action="/submit" method="post">
  <input type="hidden" name="_step" value="review">
  <input type="hidden" name="review_confirmed" value="true">
  <button type="submit" id="submit-btn">Submit Application</button>
</form>
</body></html>""")

    # ── page: conditional fields ────────────────────────────────────────

    def _page_conditional(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Conditional Fields</title></head>
<body>
<h1>Conditional Application</h1>
<form id="conditional-form" action="/submit" method="post">
  <label for="full_name">Full Name</label>
  <input id="full_name" name="full_name" type="text" required>

  <fieldset>
    <legend>Do you require visa sponsorship?</legend>
    <label><input type="radio" name="sponsorship" value="yes" id="sponsorship-yes"> Yes</label>
    <label><input type="radio" name="sponsorship" value="no" id="sponsorship-no"> No</label>
  </fieldset>

  <div id="sponsorship-details" style="display:none;">
    <label for="visa_type">Visa Type</label>
    <input id="visa_type" name="visa_type" type="text" placeholder="H-1B, L-1, etc.">
  </div>

  <fieldset>
    <legend>Do you want to relocate?</legend>
    <label><input type="radio" name="relocate" value="yes" id="relocate-yes"> Yes</label>
    <label><input type="radio" name="relocate" value="no" id="relocate-no"> No</label>
  </fieldset>

  <div id="relocate-details" style="display:none;">
    <label for="relocate_location">Preferred Location</label>
    <input id="relocate_location" name="relocate_location" type="text" placeholder="City, State">
  </div>

  <label for="resume">Resume</label>
  <input id="resume" name="resume" type="file" accept=".pdf" required>

  <button type="submit">Submit</button>
</form>

<script>
document.getElementById('sponsorship-yes').addEventListener('change', function() {
  document.getElementById('sponsorship-details').style.display = this.checked ? 'block' : 'none';
});
document.getElementById('sponsorship-no').addEventListener('change', function() {
  document.getElementById('sponsorship-details').style.display = 'none';
});
document.getElementById('relocate-yes').addEventListener('change', function() {
  document.getElementById('relocate-details').style.display = this.checked ? 'block' : 'none';
});
document.getElementById('relocate-no').addEventListener('change', function() {
  document.getElementById('relocate-details').style.display = 'none';
});
</script>
</body></html>""")

    def _page_conditional_2(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Conditional Page 2</title></head>
<body>
<h1>Conditional Page 2</h1>
<form id="conditional2-form" action="/submit" method="post">
  <label for="skills">Skills</label>
  <input id="skills" name="skills" type="text" required>

  <button type="submit">Submit</button>
</form>
</body></html>""")

    # ── page: file upload ───────────────────────────────────────────────

    def _page_file_upload(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>File Upload</title></head>
<body>
<h1>Upload Documents</h1>
<form id="upload-form" action="/upload" method="post" enctype="multipart/form-data">
  <label for="resume">Resume (PDF, max 5MB)</label>
  <input id="resume" name="resume" type="file" accept=".pdf,.docx" required>

  <label for="cover_letter">Cover Letter (PDF, max 2MB)</label>
  <input id="cover_letter" name="cover_letter" type="file" accept=".pdf">

  <label for="portfolio">Portfolio (PDF, max 10MB)</label>
  <input id="portfolio" name="portfolio" type="file" accept=".pdf">

  <button type="submit">Upload &amp; Continue</button>
</form>
</body></html>""")

    # ── page: auth required ─────────────────────────────────────────────

    def _page_auth_required(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Login Required</title></head>
<body>
<h1>Sign In to Continue</h1>
<form id="login-form" action="/auth-check" method="post">
  <label for="username">Email</label>
  <input id="username" name="username" type="email" required>

  <label for="password">Password</label>
  <input id="password" name="password" type="password" required>

  <button type="submit">Sign In</button>
</form>
</body></html>""")

    # ── page: MFA required ──────────────────────────────────────────────

    def _page_mfa_required(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>MFA Verification</title></head>
<body>
<h1>Enter Verification Code</h1>
<form id="mfa-form" action="/mfa-verify" method="post">
  <label for="mfa_code">6-digit Code</label>
  <input id="mfa_code" name="mfa_code" type="text" pattern="[0-9]{6}" maxlength="6" required>

  <button type="submit">Verify</button>
</form>
</body></html>""")

    # ── page: approval required ─────────────────────────────────────────

    def _page_approval_required(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Approval Required</title></head>
<body>
<h1>Document Review Required</h1>
<p id="approval-message">Your uploaded document needs review before proceeding.</p>
<form id="approval-form" action="/submit" method="post">
  <input type="hidden" name="approval_confirmed" value="true">
  <button type="submit" id="approve-btn">Approve &amp; Continue</button>
</form>
</body></html>""")

    # ── page: review ────────────────────────────────────────────────────

    def _page_review(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Review Application</title></head>
<body>
<h1>Review Your Application</h1>
<div id="review-content">
  <p>All fields are complete. Please review before submitting.</p>
  <ul id="validation-errors"></ul>
</div>
<form id="review-form" action="/submit" method="post">
  <input type="hidden" name="review_confirmed" value="true">
  <button type="submit" id="submit-application">Submit Application</button>
</form>
</body></html>""")

    # ── page: confirmation ──────────────────────────────────────────────

    def _page_confirmation(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application Submitted</title></head>
<body>
<h1>Application Submitted Successfully</h1>
<div id="confirmation">
  <p>Thank you for your application!</p>
  <p>Your application has been received and is being reviewed.</p>
  <p id="confirmation-id">Confirmation #APP-2026-001</p>
</div>
</body></html>""")

    # ── page: uncertain submission ───────────────────────────────────────

    def _page_uncertain(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Submission Status</title></head>
<body>
<h1>Processing Your Application</h1>
<div id="uncertain-status">
  <p>We are processing your submission. You will receive an email confirmation shortly.</p>
  <p id="status-text">Status: Processing...</p>
</div>
</body></html>""")

    # ── page: captcha ───────────────────────────────────────────────────

    def _page_captcha(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Verification Required</title></head>
<body>
<h1>Security Verification</h1>
<div id="captcha-container">
  <iframe title="captcha verification" src="/captcha-frame" width="300" height="80"></iframe>
  <input type="hidden" name="captcha_token" id="captcha_token">
</div>
<form id="captcha-form" action="/submit" method="post">
  <button type="submit" id="submit-captcha" disabled>Submit</button>
</form>
</body></html>""")

    # ── page: stale field ───────────────────────────────────────────────

    def _page_stale_field(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Stale Field Test</title></head>
<body>
<h1>Dynamic Form</h1>
<form id="stale-form" action="/submit" method="post">
  <label for="field_a">Field A</label>
  <input id="field_a" name="field_a" type="text" required>

  <label for="field_b">Field B</label>
  <input id="field_b" name="field_b" type="text">

  <button type="submit">Submit</button>
</form>
<script>
// Replace Field B after 100ms to simulate stale reference
setTimeout(function() {
  var old = document.getElementById('field_b');
  var container = old.parentNode;
  container.removeChild(old);
  var newInput = document.createElement('input');
  newInput.id = 'field_b';
  newInput.name = 'field_b';
  newInput.type = 'text';
  newInput.placeholder = 'Refreshed field';
  container.insertBefore(newInput, document.querySelector('button[type=submit]'));
}, 100);
</script>
</body></html>""")

    # ── page: autocomplete ──────────────────────────────────────────────

    def _page_autocomplete(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Autocomplete Test</title></head>
<body>
<h1>Autocomplete Form</h1>
<form id="autocomplete-form" action="/submit" method="post">
  <label for="city">City</label>
  <input id="city" name="city" type="text" autocomplete="off" list="city-list" required>
  <datalist id="city-list">
    <option value="New York">
    <option value="New Orleans">
    <option value="Newark">
    <option value="San Francisco">
    <option value="San Diego">
    <option value="Seattle">
  </datalist>

  <label for="skills">Skills</label>
  <input id="skills" name="skills" type="text" autocomplete="off" list="skills-list" required>
  <datalist id="skills-list">
    <option value="Python">
    <option value="JavaScript">
    <option value="TypeScript">
    <option value="Java">
    <option value="Go">
    <option value="Rust">
  </datalist>

  <button type="submit">Submit</button>
</form>
</body></html>""")

    # ── API: autocomplete suggestions ────────────────────────────────────

    def _api_autocomplete_suggestions(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        query = params.get("q", [""])[0].lower()
        suggestions = [
            "New York", "New Orleans", "Newark",
            "San Francisco", "San Diego", "Seattle",
            "Los Angeles", "Chicago", "Houston",
        ]
        matches = [s for s in suggestions if query in s.lower()] if query else suggestions
        self._respond_json(200, {"suggestions": matches[:5]})

    # ── Phase 19: submission verification scenarios ─────────────────────

    def _page_confirm_with_reference(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application Confirmed</title></head>
<body>
<h1>Thank You for Your Application!</h1>
<div id="confirmation">
  <p>Your application has been submitted successfully.</p>
  <p>Application ID: APP-2026-98765</p>
  <p>Confirmation Number: 482917</p>
  <p>We will review your application and get back to you within 5 business days.</p>
</div>
</body></html>""")

    def _page_confirm_no_reference(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Submission Received</title></head>
<body>
<h1>Application Received</h1>
<div id="confirmation">
  <p>Thank you for your application! We have received it and will be in touch.</p>
  <p>Please check your email for updates.</p>
</div>
</body></html>""")

    def _page_uncertain_submit(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Status</title></head>
<body>
<h1>Application Status</h1>
<div id="status">
  <p>Your application is under review. We will contact you if there are updates.</p>
</div>
</body></html>""")

    def _page_rejected(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application Status</title></head>
<body>
<h1>Application Update</h1>
<div id="status">
  <p>We regret to inform you that your application was not selected for this position.</p>
  <p>The position has been filled by another candidate.</p>
  <p>We encourage you to apply for other suitable positions.</p>
</div>
</body></html>""")

    def _page_duplicate_warning(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Duplicate Detected</title></head>
<body>
<h1>Application Already Exists</h1>
<div id="status">
  <p>You have already applied for this position.</p>
  <p>Your previous application (ID: APP-2026-11111) is being reviewed.</p>
  <p>Please do not submit a duplicate application.</p>
</div>
</body></html>""")

    def _page_delayed_confirm(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Thank You</title></head>
<body>
<h1>Thank You!</h1>
<div id="status">
  <p>Application submitted successfully.</p>
  <p>Reference: REF-2026-55555</p>
</div>
</body></html>""")

    def _page_network_error(self) -> None:
        self._respond(500, """<!DOCTYPE html>
<html><head><title>Server Error</title></head>
<body>
<h1>Internal Server Error</h1>
<p>The server encountered an error. Please try again later.</p>
</body></html>""")

    # ── Phase 20: preflight scenarios ────────────────────────────────────

    def _page_job_active(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Software Engineer - Active</title></head>
<body>
<h1>Software Engineer at TechCorp</h1>
<p>We are hiring a Software Engineer. Apply now!</p>
<form action="/submit" method="post">
  <input name="name" type="text" placeholder="Your name">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_job_closed(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Job Closed</title></head>
<body>
<h1>Software Engineer at TechCorp</h1>
<p>This position has been filled. We are no longer accepting applications.</p>
<p>Please check our other open positions.</p>
</body></html>""")

    def _page_job_removed(self) -> None:
        self._respond(404, """<!DOCTYPE html>
<html><head><title>Page Not Found</title></head>
<body>
<h1>404 - Job Not Found</h1>
<p>This job posting has been removed or no longer exists.</p>
</body></html>""")

    def _page_job_expired_deadline(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Applications Closed</title></head>
<body>
<h1>Software Engineer at TechCorp</h1>
<p>This job has expired. The application deadline has passed.</p>
<p>We are no longer accepting applications for this position.</p>
</body></html>""")

    # ── Phase 21: question scenarios ────────────────────────────────────

    def _page_question_normal(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Normal Questions</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>Full Name</label>
  <input name="full_name" type="text" placeholder="Your full name">
  <label>Email</label>
  <input name="email" type="email" placeholder="Your email">
  <label>Phone</label>
  <input name="phone" type="tel" placeholder="Your phone">
  <label>Years of Experience</label>
  <input name="years_experience" type="number" placeholder="Years">
  <label>Why are you interested in this role?</label>
  <textarea name="cover_letter" placeholder="Tell us why..."></textarea>
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_work_auth(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Work Authorization</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>Are you legally authorized to work in the United States?</label>
  <select name="work_auth">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Will you now or in the future require sponsorship?</label>
  <select name="sponsorship">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_sponsorship(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Sponsorship</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>Do you require visa sponsorship?</label>
  <select name="sponsorship">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Will you need sponsorship in the future?</label>
  <select name="future_sponsorship">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_experience_knockout(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Experience Knockout</title></head>
<body>
<h1>Apply for Senior Software Engineer</h1>
<form action="/submit" method="post">
  <label>Do you have at least 5 years of experience with Python?</label>
  <select name="python_experience">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Do you have at least 3 years of experience with React?</label>
  <select name="react_experience">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Can you work weekends?</label>
  <select name="weekends">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_relocation(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Relocation</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>Are you willing to relocate to San Francisco?</label>
  <select name="relocation">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Can you work from another location?</label>
  <select name="remote">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_availability(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Availability</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>When can you start?</label>
  <input name="start_date" type="date">
  <label>Are you available to start immediately?</label>
  <select name="immediate">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_salary(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Salary</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>Expected Salary</label>
  <input name="salary" type="text" placeholder="e.g. 120000">
  <label>Desired Compensation</label>
  <input name="compensation" type="text" placeholder="e.g. $120,000/year">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_demographic(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Demographic</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>What is your gender?</label>
  <select name="gender">
    <option value="male">Male</option>
    <option value="female">Female</option>
    <option value="non-binary">Non-binary</option>
    <option value="prefer-not">Prefer not to say</option>
  </select>
  <label>What is your race/ethnicity?</label>
  <select name="race">
    <option value="white">White</option>
    <option value="black">Black or African American</option>
    <option value="hispanic">Hispanic or Latino</option>
    <option value="asian">Asian</option>
    <option value="other">Other</option>
    <option value="prefer-not">Prefer not to say</option>
  </select>
  <label>Are you a veteran?</label>
  <select name="veteran">
    <option value="yes">Yes</option>
    <option value="no">No</option>
    <option value="prefer-not">Prefer not to say</option>
  </select>
  <label>Do you have a disability?</label>
  <select name="disability">
    <option value="yes">Yes</option>
    <option value="no">No</option>
    <option value="prefer-not">Prefer not to say</option>
  </select>
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_declaration(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Declaration</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>I certify that the information provided is accurate and complete.</label>
  <input name="certify" type="checkbox" value="true">
  <label>I confirm that the information above is true to the best of my knowledge.</label>
  <input name="confirm" type="checkbox" value="true">
  <label>I agree to the terms and conditions.</label>
  <input name="terms" type="checkbox" value="true">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_attestation(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Attestation</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>I attest that I have not been convicted of a felony.</label>
  <input name="attest_felony" type="checkbox" value="true">
  <label>I attest that all information provided is true and accurate.</label>
  <input name="attest_true" type="checkbox" value="true">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_consent_required(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Required Consent</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>I agree to the application privacy notice.</label>
  <input name="privacy" type="checkbox" value="true">
  <label>I consent to the processing of my personal data.</label>
  <input name="data_processing" type="checkbox" value="true">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_consent_optional(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Optional Consent</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>I agree to receive marketing emails.</label>
  <input name="marketing" type="checkbox" value="true">
  <label>I consent to receive promotional updates about new positions.</label>
  <input name="promotional" type="checkbox" value="true">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_signature(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Electronic Signature</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>Type your full legal name as your electronic signature:</label>
  <input name="electronic_signature" type="text" placeholder="Full legal name">
  <label>I acknowledge that this constitutes my electronic signature.</label>
  <input name="signature_ack" type="checkbox" value="true">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    def _page_question_mixed(self) -> None:
        self._respond(200, """<!DOCTYPE html>
<html><head><title>Application - Mixed Questions</title></head>
<body>
<h1>Apply for Software Engineer</h1>
<form action="/submit" method="post">
  <label>Full Name</label>
  <input name="full_name" type="text" placeholder="Your full name">
  <label>Email</label>
  <input name="email" type="email" placeholder="Your email">
  <label>Are you legally authorized to work in the United States?</label>
  <select name="work_auth">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Do you require visa sponsorship?</label>
  <select name="sponsorship">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Do you have at least 5 years of experience with Python?</label>
  <select name="python_exp">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Are you willing to relocate?</label>
  <select name="relocation">
    <option value="yes">Yes</option>
    <option value="no">No</option>
  </select>
  <label>Expected Salary</label>
  <input name="salary" type="text" placeholder="e.g. 120000">
  <label>I certify that the information provided is accurate.</label>
  <input name="certify" type="checkbox" value="true">
  <label>Type your full legal name as your electronic signature:</label>
  <input name="electronic_signature" type="text" placeholder="Full legal name">
  <label>I agree to receive marketing emails.</label>
  <input name="marketing" type="checkbox" value="true">
  <button type="submit">Apply Now</button>
</form>
</body></html>""")

    # ── POST handlers ───────────────────────────────────────────────────

    def _handle_submit(self, body: bytes) -> None:
        self.submitted_data.append({"body": body.decode("utf-8", errors="replace")})
        parsed = urlparse(self.path)
        self._respond(302, "")

    def _handle_auth_check(self, body: bytes) -> None:
        self._respond_json(200, {"status": "auth_ok", "message": "Authenticated"})

    def _handle_mfa_verify(self, body: bytes) -> None:
        self._respond_json(200, {"status": "mfa_ok", "message": "MFA verified"})

    def _handle_upload(self, body: bytes) -> None:
        self._respond_json(200, {"status": "uploaded", "message": "File received"})

    # ── misc ────────────────────────────────────────────────────────────

    def _page_not_found(self) -> None:
        self._respond(404, "<html><body><h1>404 Not Found</h1></body></html>")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # Silence request logging during tests


class MockApplicationServer:
    """Threaded local HTTP server serving mock application pages."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url: str = ""

    def start(self) -> str:
        self._server = HTTPServer((self.host, self.port), _MockHandler)
        actual_port = self._server.server_address[1]
        self.url = f"http://{self.host}:{actual_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        _MockHandler.submitted_data.clear()
        _MockHandler.uploaded_files.clear()

    def reset(self) -> None:
        _MockHandler.submitted_data.clear()
        _MockHandler.uploaded_files.clear()
        _MockHandler.scenario = {}
