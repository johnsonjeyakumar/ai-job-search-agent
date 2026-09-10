# Phase 21 — Knockout Questions + Declarations + Sensitive Answer Safety

## Summary
Phase 21 implements comprehensive question classification, knockout detection, and sensitive answer safety for job application forms. The system handles 16 question classes, 22 reason codes, and 8 approval actions to ensure safe, compliant handling of application questions.

## What Was Built

### Question Classification (`question_handler.py`)
- **QuestionClass enum** (16 values): `NORMAL`, `KNOCKOUT`, `WORK_AUTHORIZATION`, `SPONSORSHIP`, `RELOCATION`, `AVAILABILITY`, `COMPENSATION`, `EXPERIENCE`, `DEMOGRAPHIC`, `DECLARATION`, `ATTESTATION`, `CONSENT`, `E_SIGNATURE`, `LEGAL`, `COMPLIANCE`, `UNKNOWN`
- **QuestionConcept system** (7 concepts): `work_auth`, `sponsorship`, `experience`, `availability`, `salary`, `location`, `education` — each with aliases, categories, and sensitivity levels
- **Detection methods**: Knockout regex patterns (12), declaration regex patterns (10), attestation regex patterns (5), optional consent regex patterns (3), demographic keywords (10), sensitive keywords (20+)
- **`classify_question()`**: Semantic matching, demographic-first detection, concept resolution
- **`compare_experience_requirement()`**: Parses "5+ years", "at least 3 years", "worked with X for 2 years" patterns; returns SAFE/DOES_NOT_MEET

### Answer Engine (`answer_engine.py`)
- **5-step priority**: Verified user answer → Profile data → ProfileDataProvider → Default safe → Missing
- **`ProfileDataProvider`**: Reads user profile fields with semantic mapping; handles availability, salary, location, experience, education
- **`generate_answer()`**: Full answer generation with contradiction detection, confidence state propagation, sensitive answer handling
- **`_check_answer_contradiction()`**: Compares generated answer against profile data for conflicts
- **`_SKIP_PROFILE_MATCH`**: Prevents profile auto-fill for `E_SIGNATURE`, `DECLARATION`, `ATTESTATION`, `DEMOGRAPHIC`
- **`_EXPERIENCE_KNOCKOUT_CLASSES`**: Triggers experience comparison for KNOCKOUT class when skill/years detected

### Memory Store (`memory.py`)
- **13 new question categories**: `work_authorization`, `sponsorship`, `experience`, `availability`, `salary`, `location`, `education`, `demographic`, `declaration`, `attestation`, `consent`, `e_signature`, `legal_compliance`
- **Demographic keywords**: gender, race, ethnicity, religion, age, disability, sexual orientation, marital status, national origin, citizenship status
- **Declaration keywords**: agree, certify, attest, declare, confirm, acknowledge, truth, accurate, complete
- **Sensitive keywords**: salary, compensation, age, race, gender, religion, disability, health, medical, pregnancy, marital status, sexual orientation, national origin, citizenship, criminal history, legal proceedings, bankruptcy, credit score, social security

### Human Approval (`human_approval.py`)
- **8 new ApprovalAction values**: `UNKNOWN_KNOCKOUT_ANSWER`, `SENSITIVE_ANSWER_REVIEW`, `DECLARATION_REVIEW`, `SIGNATURE_REVIEW`, `CONTRADICTORY_ANSWER`, `AMBIGUOUS_QUESTION`, `DOES_NOT_MEET_REQUIREMENT`, `CONSENT_REVIEW`
- **Updated ApprovalPolicy**: `sensitivity_threshold="HIGH"`, `auto_allow_low_sensitivity=True`

### Mock Server (`mock_app_server.py`)
- **14 new scenarios**: Normal question, work authorization, sponsorship, experience knockout, relocation, availability, salary, demographic, declaration, attestation, consent required/optional, signature, mixed

## Test Results
- **110 tests pass** in Phase 21 test suite
- **610 tests pass** across Phases 15-21 (full regression)
- **0 failures** in Phase 21

## Safety Rules Enforced
1. Never fabricate applicant information
2. Never infer sensitive applicant info from unrelated data
3. Never guess knockout/sponsorship/work-authorization/demographic/legal answers
4. Never automatically accept declarations without explicit user authorization
5. Never generate false electronic signatures
6. Human review mandatory for unknown/ambiguous/sensitive/legally significant answers
7. Do not silently change profile values or mutate resumes
8. Optional consent defaults to "No" unless explicitly enabled

## Files Modified
- `app/application_execution/question_handler.py` — Rewritten: 16 question classes, 7 concepts, 12 knockout patterns, 10 declaration patterns, 5 attestation patterns, 3 consent patterns, 10 demographic keywords, 20+ sensitive keywords
- `app/application_execution/answer_engine.py` — Rewritten: 5-step priority, ProfileDataProvider, contradiction detection, sensitive answer handling
- `app/application_execution/memory.py` — Updated: 13 new question categories, expanded keyword lists
- `app/application_execution/human_approval.py` — Updated: 8 new ApprovalAction values
- `tests/e2e/mock_app_server.py` — Added 14 new mock scenarios
- `tests/test_phase21_knockout.py` — New: 110 tests covering all question classes and safety rules
