from datetime import date, datetime

from app.job_sources import normalizer as norm


def test_clean_text_collapses_whitespace():
    assert norm.clean_text("  Hello   world\t ") == "Hello world"
    assert norm.clean_text("   ") is None
    assert norm.clean_text(None) is None
    assert norm.clean_text(42) == "42"


def test_normalize_location():
    assert norm.normalize_location(" Chennai, Tamil Nadu ") == "Chennai, Tamil Nadu"
    assert norm.normalize_location("   Chennai,   Tamil Nadu  ") == "Chennai, Tamil Nadu"
    assert norm.normalize_location("") is None


def test_normalize_url():
    assert norm.normalize_url(" https://example.com/job/1 ") == "https://example.com/job/1"
    assert norm.normalize_url("not a url") is None
    assert norm.normalize_url("javascript:alert(1)") is None
    assert norm.normalize_url("ftp://x") is None
    assert norm.is_valid_url("https://indeed.com/viewjob?jk=abc")


def test_parse_date_iso_and_calendar():
    assert norm.parse_date("2026-07-07") == date(2026, 7, 7)
    assert norm.parse_date("2026-07-07T05:00:00.000Z") == date(2026, 7, 7)
    assert norm.parse_date("2026/07/07") == date(2026, 7, 7)
    assert norm.parse_date(datetime(2026, 8, 1, 12, 0)) == date(2026, 8, 1)


def test_parse_date_ignores_relative_strings():
    assert norm.parse_date("2 days ago") is None
    assert norm.parse_date("today") is None
    assert norm.parse_date(None) is None
    assert norm.parse_date("") is None


def test_first_date_prefers_most_reliable_key():
    raw = {
        "postingDateParsed": "2026-09-04T00:00:00.000Z",
        "postedAt": "2026-09-05T10:00:00.000Z",
        "listedAtISO": "2026-09-06T10:00:00.000Z",
    }
    assert norm.first_date(raw) == date(2026, 9, 4)


def test_first_date_falls_back_to_other_keys():
    assert norm.first_date({"postedAt": "2026-09-03T05:00:00.000Z"}) == date(2026, 9, 3)
    assert norm.first_date({"listedAtISO": "2026-09-02T10:00:00.000Z"}) == date(2026, 9, 2)
    assert norm.first_date({"createdAt": "2026-09-01"}) == date(2026, 9, 1)


def test_first_date_skips_unparseable_first_key():
    # A relative string must not shadow a real date in a later key.
    raw = {
        "postingDateParsed": "Updated 2 days ago",
        "postedAt": "2026-09-03T05:00:00.000Z",
    }
    assert norm.first_date(raw) == date(2026, 9, 3)


def test_first_date_returns_none_when_no_reliable_date():
    assert norm.first_date({"postingDateParsed": "2 days ago"}) is None
    assert norm.first_date({"postedAt": "Just posted"}) is None
    assert norm.first_date({}) is None
    assert norm.first_date({"postedAt": None, "listedAtISO": ""}) is None


def test_classify_remote():
    assert norm.classify_remote({"workplaceType": "Remote"}) == "remote"
    assert norm.classify_remote({"workplaceType": "Hybrid"}) == "hybrid"
    assert norm.classify_remote({"workplaceType": "On-site"}) == "onsite"
    assert norm.classify_remote({}, location="Chennai") is None
    assert norm.classify_remote({}, location="Remote - India") == "remote"
    assert norm.classify_remote({"is_remote": True}) == "remote"


def test_classify_employment():
    assert norm.classify_employment("Full-time") == "full_time"
    assert norm.classify_employment("Part time") == "part_time"
    assert norm.classify_employment("Contract") == "contract"
    assert norm.classify_employment("Internship") == "internship"
    assert norm.classify_employment(None) is None


def test_build_location_from_parts():
    raw = {"city": "Chennai", "state": "Tamil Nadu", "country": "India"}
    assert norm.build_location(raw) == "Chennai, Tamil Nadu, India"
    assert norm.build_location({}) is None


def test_extract_requirements_bullets():
    text = "Requirements:\n- Python\n- FastAPI\n- Team work"
    assert norm.extract_requirements(text) == ["Python", "FastAPI", "Team work"]
    assert norm.extract_requirements(["A", "", "B"]) == ["A", "B"]


def test_experience_regex_present():
    assert norm._EXPERIENCE_RE.search("3 years of experience") is not None
    assert norm._EXPERIENCE_RE.search("Fresher welcome") is not None
    assert norm._EXPERIENCE_RE.search("full stack developer") is None
