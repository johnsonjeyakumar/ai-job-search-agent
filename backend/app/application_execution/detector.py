"""Platform detection (Phase 7).

Detection combines the crawl ``source`` label, the posting URL, and the
application URL. A host can directly identify a known board; a known ATS host
(greenhouse, lever, workday, ...) is classified as ``company_career`` before
ever falling back to ``generic``. Detection never relies on URL text alone when
metadata is available -- but metadata (source) is honored first because it is
produced at discovery time and is the most reliable signal we have.
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.application_execution.base import DetectionResult

# Source labels produced by the Apify discovery sources.
_SOURCE_PLATFORMS = {
    "linkedin": "linkedin",
    "indeed": "indeed",
    "naukri": "naukri",
}

_BOARD_HOSTS = {
    "linkedin.com": "linkedin",
    "www.linkedin.com": "linkedin",
    "m.linkedin.com": "linkedin",
    "www.indeed.com": "indeed",
    "indeed.com": "indeed",
    "naukri.com": "naukri",
    "www.naukri.com": "naukri",
}

# Well-known applicant tracking / career portals → company career sites.
_ATS_HOSTS = {
    "greenhouse.io",
    "boards.greenhouse.io",
    "jobs.lever.co",
    "lever.co",
    "workday.com",
    "myworkdayjobs.com",
    "icims.com",
    "jobs.icims.com",
    "jazzhr.com",
    "smartrecruiters.com",
    "bamboohr.com",
    "bamboohr.eu",
    "talentlyft.com",
    "apply.workable.com",
    "workable.com",
    "recruitee.com",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "teamtailor.com",
}

# ATS-style path markers on an otherwise generic host (e.g. careers.acme.com).
_ATS_PATH_MARKERS = ("/apply/", "/careers/", "/jobs/", "/job/", "/careers-at/")


def _host_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return None


def detect_platform(
    *,
    url: str | None = None,
    application_url: str | None = None,
    source: str | None = None,
) -> DetectionResult:
    """Return the best platform guess from all available signals."""
    source_norm = (source or "").strip().lower()
    if source_norm in _SOURCE_PLATFORMS:
        return DetectionResult(
            platform=_SOURCE_PLATFORMS[source_norm],
            url=application_url or url,
            based_on="source",
            confidence="high",
            hostname=_host_of(application_url or url),
        )

    for candidate_url, based_on in ((application_url, "application_url"), (url, "url")):
        if not candidate_url:
            continue
        host = _host_of(candidate_url)
        if host in _BOARD_HOSTS:
            return DetectionResult(
                platform=_BOARD_HOSTS[host],
                url=candidate_url,
                hostname=host,
                based_on=based_on,
                confidence="high",
            )
        if host and any(host == a or host.endswith(f".{a}") for a in _ATS_HOSTS):
            return DetectionResult(
                platform="company_career",
                url=candidate_url,
                hostname=host,
                career_site=True,
                based_on=based_on,
                confidence="high",
            )

    # A subdomain of the posting host that smells like a careers portal.
    for candidate_url, based_on in ((application_url, "application_url"), (url, "url")):
        host = _host_of(candidate_url)
        if not host:
            continue
        if host.startswith("careers.") or host.startswith("jobs.") or host.startswith("apply."):
            return DetectionResult(
                platform="company_career",
                url=candidate_url,
                hostname=host,
                career_site=True,
                based_on=based_on,
                confidence="medium",
            )
        path = urlparse(candidate_url).path.lower()
        if any(marker in path for marker in _ATS_PATH_MARKERS):
            return DetectionResult(
                platform="company_career",
                url=candidate_url,
                hostname=host,
                career_site=True,
                based_on=based_on,
                confidence="medium",
            )

    if url or application_url:
        return DetectionResult(
            platform="generic",
            url=application_url or url,
            hostname=_host_of(application_url or url),
            based_on="url",
            confidence="low",
        )

    return DetectionResult(platform="generic", url=None, based_on="none", confidence="low")
