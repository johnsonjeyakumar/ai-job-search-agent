"""Apify-backed job source.

The default actor is ``schnellscrapers/indeed-jobs-scraper`` which returns
structured, public Indeed listings (2letter country incl. ``in``) with posting
dates, remote flags and apply URLs. The implementation talks to the Apify REST
API, so no MCP dependency is required at runtime.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from app.config.settings import get_settings
from app.job_sources import normalizer as norm
from app.job_sources.base import JobSource, JobSourceError

_MAX_LOCATIONS = 3
_MAX_SALARY_LEN = 255
_MAX_SOURCE_JOB_ID_LEN = 255

_INDIAN_CITIES = {
    "chennai",
    "madurai",
    "bangalore",
    "bengaluru",
    "hyderabad",
    "mumbai",
    "delhi",
    "noida",
    "pune",
    "kolkata",
    "chennai",
}


class ApifyJobSource(JobSource):
    """Discover public job listings through an Apify actor."""

    name = "apify"

    def __init__(
        self,
        token: str | None = None,
        actor_id: str | None = None,
        timeout_secs: int | None = None,
        poll_interval_secs: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.token = token or settings.apify_token
        self.actor_id = actor_id or settings.apify_actor_id
        self.timeout_secs = timeout_secs or settings.apify_run_timeout_secs
        self.poll_interval_secs = (
            poll_interval_secs or settings.apify_poll_interval_secs
        )
        self._client = client or httpx.Client(timeout=60.0)

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    def build_search_params(
        self, preferences: dict[str, Any], limit: int | None = None
    ) -> dict[str, Any]:
        settings = get_settings()
        cap = min(limit or settings.apify_max_items, settings.apify_max_items)
        cap = max(1, cap)

        roles = [r for r in (norm.clean_text(x) for x in preferences.get("target_roles", [])) if r]
        query = roles[0] if roles else "Software Developer"

        locations = [
            loc
            for loc in (
                norm.normalize_location(x) for x in preferences.get("preferred_locations", [])
            )
            if loc
        ]
        locations = locations[:_MAX_LOCATIONS]

        per_search = max(1, cap // len(locations)) if locations else cap

        remote_types = set(preferences.get("remote_types", []) or [])
        remote_only = remote_types == {"remote"}

        # NOTE: ``postedWithinDays`` is deliberately omitted. The actor's
        # date-window filter returns empty results for several country/
        # location combinations (observed for in.indeed.com). Freshness is
        # enforced after storage via posted_date + posted_within_days in the
        # /jobs API instead.
        searches: list[dict[str, Any]] = []
        for location in locations:
            entry: dict[str, Any] = {
                "query": query,
                "location": location,
                "country": self._country_for(location),
                "sort": "relevance",
                "maxItems": per_search,
            }
            if remote_only:
                entry["remoteOnly"] = True
            searches.append(entry)

        if not searches:
            searches = [
                {
                    "query": query,
                    "country": "in",
                    "maxItems": cap,
                }
            ]

        return {
            "searches": searches,
            "maxItems": cap,
            "includeFullDescription": False,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
            },
        }

    def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.token:
            raise JobSourceError(
                "APIFY_TOKEN is not configured. Set it in the backend .env file."
            )
        run = self._start_run(params)
        run_id = run["id"]
        status = self._wait_for_finish(run_id)
        if status != "SUCCEEDED":
            raise JobSourceError(f"Apify run {run_id} ended with status '{status}'")
        return self._fetch_dataset(run_id)

    # ------------------------------------------------------------------ #
    # Normalization / validation
    # ------------------------------------------------------------------ #
    def normalize_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        title = norm.normalize_title(norm._first(raw, norm._TITLE_KEYS)) or ""
        company = norm.normalize_company(norm._first(raw, norm._COMPANY_KEYS))
        location = norm.normalize_location(
            norm._first(raw, norm._LOCATION_KEYS)
        ) or norm.build_location(raw)

        remote_type = norm.classify_remote(
            raw, location=location,
            employment_text=norm.clean_text(norm._first(raw, norm._SALARY_KEYS)),
        )
        employment_type = norm.classify_employment(
            norm._first(raw, ("employmentType", "jobType", "job_type", "type"))
        )

        url = norm.normalize_url(norm._first(raw, norm._URL_KEYS))
        application_url = norm.normalize_url(
            norm._first(
                raw,
                (
                    "applicationUrl",
                    "applyUrl",
                    "apply_url",
                    "easyApplyUrl",
                    "applicationLink",
                ),
            )
        ) or url
        company_url = norm.normalize_url(
            norm._first(raw, norm._COMPANY_URL_KEYS)
        )

        description = norm.clean_description(
            norm._first(raw, norm._DESCRIPTION_KEYS)
        )
        requirements = norm.extract_requirements(
            norm._first(raw, norm._REQUIREMENTS_KEYS) or description
        )
        skills = norm.extract_single_item(norm._first(raw, norm._SKILLS_KEYS))

        salary_text = self._format_salary(norm._first(raw, norm._SALARY_KEYS))
        experience = norm.clean_text(norm._first(raw, norm._EXPERIENCE_KEYS))
        if not experience:
            experience = self._extract_experience(description)

        source_job_id = self._derive_source_job_id(raw, url, title, company)
        posted_date = norm.first_date(raw)

        return {
            "title": title,
            "company": company,
            "location": location,
            "remote_type": remote_type,
            "employment_type": employment_type,
            "experience_required": ((experience or "")[:_MAX_SALARY_LEN] or None),
            "salary": salary_text,
            "description": description,
            "requirements": requirements,
            "skills": skills,
            "url": url,
            "source": self.name,
            "source_job_id": source_job_id,
            "posted_date": posted_date,
            "application_url": application_url,
            "company_url": company_url,
        }

    def validate_job(self, normalized: dict[str, Any]) -> tuple[bool, str]:
        title = norm.clean_text(normalized.get("title"))
        if not title:
            return False, "missing title"
        company = norm.clean_text(normalized.get("company"))
        if not company:
            return False, "missing company"
        if not normalized.get("source"):
            return False, "missing source"
        source_job_id = norm.clean_text(normalized.get("source_job_id"))
        url = normalized.get("url")
        if not source_job_id and not url:
            return False, "missing source_job_id and url"
        if url and not norm.is_valid_url(url):
            return False, "invalid url"
        application_url = normalized.get("application_url")
        if application_url and not norm.is_valid_url(application_url):
            return False, "invalid application_url"
        company_url = normalized.get("company_url")
        if company_url and not norm.is_valid_url(company_url):
            return False, "invalid company_url"
        return True, ""

    def _derive_source_job_id(
        self, raw: dict[str, Any], url: str | None, title: str, company: str | None
    ) -> str | None:
        value = norm._first(
            raw, ("jobKey", "jobId", "job_id", "id", "externalId", "key")
        )
        if value is not None and str(value).strip():
            return str(value).strip()[:_MAX_SOURCE_JOB_ID_LEN]
        seed = url or f"{company or ''}|{title}"
        if not seed:
            return None
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        return f"derived:{digest[:24]}"

    def _format_salary(self, value: object) -> str | None:
        if isinstance(value, dict):
            s_min = norm.clean_text(value.get("min"))
            s_max = norm.clean_text(value.get("max"))
            text = norm.clean_text(value.get("text") or value.get("salaryText"))
            if not text and (s_min or s_max):
                text = f"{s_min or ''} - {s_max or ''}"
        else:
            text = norm.clean_text(value)
        if not text:
            return None
        return text[:_MAX_SALARY_LEN]

    def _extract_experience(self, description: str | None) -> str | None:
        if not description:
            return None
        match = norm._EXPERIENCE_RE.search(description)
        return match.group(0) if match else None

    @staticmethod
    def _country_for(location: str) -> str:
        lowered = location.lower()
        if lowered in ("remote - india", "remote india") or "india" in lowered:
            return "in"
        city = lowered.split(",")[0].strip()
        if city in _INDIAN_CITIES:
            return "in"
        return "in"

    # ------------------------------------------------------------------ #
    # Apify REST API
    # ------------------------------------------------------------------ #
    def _start_run(self, params: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"https://api.apify.com/v2/acts/{self.actor_id}/runs",
            params={"token": self.token},
            json=params,
        )
        return self._parse_run_response(response)

    def _wait_for_finish(self, run_id: str) -> str:
        deadline = time.monotonic() + self.timeout_secs
        while True:
            response = self._client.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                params={"token": self.token},
            )
            body = self._parse_run_response(response)
            status = body.get("status", "")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                return status
            if time.monotonic() >= deadline:
                raise JobSourceError(
                    f"Apify run {run_id} did not finish within {self.timeout_secs}s"
                )
            time.sleep(self.poll_interval_secs)

    def _fetch_dataset(self, run_id: str) -> list[dict[str, Any]]:
        response = self._client.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
            params={"token": self.token, "clean": "true", "format": "json"},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            raise JobSourceError(f"Unexpected dataset response: {data}")
        return data

    @staticmethod
    def _parse_run_response(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise JobSourceError(f"Invalid Apify API response ({response.status_code})") from exc
        if response.status_code >= 400:
            message = payload
            if isinstance(payload, dict):
                message = payload.get("error", {}).get("message", payload)
            raise JobSourceError(f"Apify API error {response.status_code}: {message}")
        data = payload.get("data", payload)
        if not isinstance(data, dict) or "id" not in data:
            raise JobSourceError(f"Unexpected Apify run payload: {data}")
        return data
