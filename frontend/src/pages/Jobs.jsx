import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiSend } from "../api/client.js";
import PageHeader from "../components/PageHeader.jsx";
import EmptyState from "../components/EmptyState.jsx";

const PAGE_SIZES = [10, 20, 50];
const SOURCE_OPTIONS = [
  { value: "", label: "All sources" },
  { value: "apify", label: "Apify (Indeed)" },
];
const REMOTE_OPTIONS = [
  { value: "", label: "All work modes" },
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
];
const FRESHNESS_OPTIONS = [
  { value: "", label: "All freshness" },
  { value: "VERY_FRESH", label: "Very fresh (0–3d)" },
  { value: "FRESH", label: "Fresh (4–7d)" },
  { value: "RECENT", label: "Recent (8–14d)" },
  { value: "AGING", label: "Aging (15–30d)" },
  { value: "STALE", label: "Stale (31d+)" },
  { value: "UNKNOWN", label: "Unknown posting date" },
];
const SORT_OPTIONS = [
  { value: "discovered", label: "Newest discovery" },
  { value: "freshness_desc", label: "Freshest posting" },
  { value: "quality_desc", label: "Highest quality" },
  { value: "posted", label: "Latest posted date" },
  { value: "match_desc", label: "Best match" },
  { value: "match_asc", label: "Worst match" },
  { value: "opportunity_desc", label: "Best opportunity" },
  { value: "opportunity_asc", label: "Worst opportunity" },
];
const RECOMMENDATION_OPTIONS = [
  { value: "", label: "All recommendations" },
  { value: "APPLY_NOW", label: "Apply now" },
  { value: "APPLY", label: "Apply" },
  { value: "REVIEW", label: "Review" },
  { value: "LOW_PRIORITY", label: "Low priority" },
  { value: "SKIP", label: "Skip" },
];

const FRESHNESS_STYLES = {
  VERY_FRESH: "bg-emerald-100 text-emerald-700",
  FRESH: "bg-green-100 text-green-700",
  RECENT: "bg-sky-100 text-sky-700",
  AGING: "bg-amber-100 text-amber-700",
  STALE: "bg-rose-100 text-rose-700",
  UNKNOWN: "bg-slate-100 text-slate-500",
};

const FRESHNESS_LABELS = {
  VERY_FRESH: "Very fresh",
  FRESH: "Fresh",
  RECENT: "Recent",
  AGING: "Aging",
  STALE: "Stale",
  UNKNOWN: "Unknown",
};

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function labelize(value) {
  if (!value) return null;
  return value
    .split(/[_ ]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function Badge({ children }) {
  return children ? (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
      {children}
    </span>
  ) : null;
}

function FreshnessBadge({ freshness }) {
  if (!freshness) return null;
  const status = freshness.status || "UNKNOWN";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${FRESHNESS_STYLES[status] || FRESHNESS_STYLES.UNKNOWN}`}
    >
      {FRESHNESS_LABELS[status] || "Unknown"}
    </span>
  );
}

function QualityChip({ quality }) {
  if (!quality || typeof quality.overall_score !== "number") return null;
  return (
    <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700">
      Quality: {quality.overall_score}/100
    </span>
  );
}

const MATCH_STYLES = {
  APPLY_NOW: "bg-emerald-100 text-emerald-800",
  APPLY: "bg-green-100 text-green-800",
  REVIEW: "bg-amber-100 text-amber-800",
  LOW_PRIORITY: "bg-orange-100 text-orange-800",
  SKIP: "bg-rose-100 text-rose-800",
};

function RecommendationChip({ label, score, band, styles }) {
  if (score == null) return null;
  return (
    <span
      className={`rounded-md border px-2 py-0.5 text-xs font-semibold ${
        (styles || MATCH_STYLES)[band] || "border-slate-200 bg-slate-50 text-slate-700"
      }`}
    >
      {label}: {Math.round(score)} · {band}
    </span>
  );
}

function MatchChip({ match }) {
  if (!match || match.match_score == null) return null;
  return <RecommendationChip label="Match" score={match.match_score} band={match.recommendation} />;
}

function OpportunityChip({ opportunity }) {
  if (!opportunity) return null;
  return (
    <RecommendationChip
      label="Opportunity"
      score={opportunity.opportunity_score}
      band={opportunity.recommendation}
    />
  );
}

function JobCard({ job }) {
  return (
    <Link
      to={`/jobs/${job.id}`}
      className="block rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-400"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">{job.title}</h3>
          <p className="mt-1 text-sm text-slate-600">{job.company}</p>
          <p className="mt-1 text-xs text-slate-500">
            {job.location || "Location not specified"}
            {job.salary ? ` · ${job.salary}` : ""}
          </p>
        </div>
        <Badge>{job.source}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <MatchChip match={job.match} />
        <OpportunityChip opportunity={job.opportunity} />
        <FreshnessBadge freshness={job.freshness} />
        <QualityChip quality={job.quality} />
        <Badge>{labelize(job.remote_type)}</Badge>
        <Badge>{labelize(job.employment_type)}</Badge>
        <Badge>{job.experience_required}</Badge>
        <span className="ml-auto text-xs text-slate-400">
          Posted {formatDate(job.posted_date)} · Discovered {formatDate(job.discovered_date)}
        </span>
      </div>
    </Link>
  );
}

export default function Jobs() {
  const [jobs, setJobs] = useState([]);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(20);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [filters, setFilters] = useState(() => ({
    role: "",
    location: "",
    source: "",
    remote_type: "",
    freshness: "",
    recommendation: "",
    min_score: "",
    sort: "discovered",
    company: new URLSearchParams(window.location.search).get("company") || "",
  }));
  const [showSearch, setShowSearch] = useState(false);
  const [searchForm, setSearchForm] = useState({ role: "", location: "", limit: 20 });
  const [run, setRun] = useState(null);
  const [runError, setRunError] = useState(null);

  function fetchJobs(nextPage = page) {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      page: String(nextPage),
      limit: String(limit),
    });
    if (filters.role.trim()) params.set("role", filters.role.trim());
    if (filters.location.trim()) params.set("location", filters.location.trim());
    if (filters.source) params.set("source", filters.source);
    if (filters.remote_type) params.set("remote_type", filters.remote_type);
    if (filters.freshness) params.set("freshness", filters.freshness);
    if (filters.recommendation) params.set("recommendation", filters.recommendation);
    if (filters.min_score !== "" && Number(filters.min_score) > 0) {
      params.set("min_match_score", String(Number(filters.min_score)));
      params.set("min_opportunity_score", String(Number(filters.min_score)));
    }
    if (filters.sort) params.set("sort", filters.sort);
    if (filters.company.trim()) params.set("company", filters.company.trim());
    apiGet(`/jobs?${params.toString()}`)
      .then((body) => {
        setJobs(body.items);
        setTotal(body.total);
        setPages(body.pages);
        setPage(body.page);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchJobs(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, limit]);

  function applySearch(search = { role: "", location: "", limit: 20 }) {
    setSearchForm(search);
    const payload = {};
    if (search.role.trim()) payload.roles = [search.role.trim()];
    if (search.location.trim()) payload.locations = [search.location.trim()];
    if (search.limit != null && Number(search.limit) > 0) payload.limit = Number(search.limit);
    setRun({ status: "starting", details: {} });
    setRunError(null);
    apiSend("POST", "/jobs/search", payload)
      .then((body) => pollRun(body.run_id))
      .catch((err) => {
        setRun(null);
        setRunError(err.message);
      });
  }

  function pollRun(runId) {
    apiGet(`/jobs/runs/${runId}`)
      .then((body) => {
        setRun(body);
        if (body.status === "RUNNING") {
          window.setTimeout(() => pollRun(runId), 2000);
        } else {
          fetchJobs(1);
        }
      })
      .catch((err) => setRunError(err.message));
  }

  const runDetails = run?.details || {};
  const runFinished = run && run.status !== "RUNNING" && run.status !== "starting";

  return (
    <div>
      <PageHeader
        title="Jobs"
        description="Discovered jobs with personal match, opportunity score, and recommendation. Scores use your profile and preferences; missing signals are shown as unknown."
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={filters.role}
            onChange={(e) => setFilters({ ...filters, role: e.target.value })}
            placeholder="Search title…"
            className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-slate-900 focus:outline-none"
          />
          <input
            value={filters.location}
            onChange={(e) => setFilters({ ...filters, location: e.target.value })}
            placeholder="Location…"
            className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-slate-900 focus:outline-none"
          />
          <select
            value={filters.remote_type}
            onChange={(e) => setFilters({ ...filters, remote_type: e.target.value })}
            className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:outline-none"
          >
            {REMOTE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={filters.source}
            onChange={(e) => setFilters({ ...filters, source: e.target.value })}
            className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:outline-none"
          >
            {SOURCE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={filters.freshness}
            onChange={(e) => setFilters({ ...filters, freshness: e.target.value })}
            className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:outline-none"
          >
            {FRESHNESS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={filters.recommendation}
            onChange={(e) => setFilters({ ...filters, recommendation: e.target.value })}
            className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:outline-none"
          >
            {RECOMMENDATION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <input
            value={filters.min_score}
            onChange={(e) => setFilters({ ...filters, min_score: e.target.value })}
            placeholder="Min score"
            inputMode="numeric"
            className="w-24 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-slate-900 focus:outline-none"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Sort</label>
          <select
            value={filters.sort}
            onChange={(e) => setFilters({ ...filters, sort: e.target.value })}
            className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:outline-none"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={() => {
            if (!showSearch && run?.status === "starting") return;
            setShowSearch((v) => !v);
          }}
          className="rounded bg-slate-900 px-5 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          {showSearch ? "Close" : "Search for New Jobs"}
        </button>
      </div>

      {filters.company.trim() && (
        <div className="mt-3 flex items-center gap-2">
          <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white">
            Company: {filters.company.trim()}
          </span>
          <button
            type="button"
            onClick={() => setFilters({ ...filters, company: "" })}
            className="text-xs font-medium text-slate-600 hover:text-slate-900 hover:underline"
          >
            Clear
          </button>
        </div>
      )}

      {showSearch && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">Search for New Jobs</h3>
          <p className="mt-1 text-xs text-slate-500">
            Uses your saved preferences (locations, roles, posting window). Overrides below are optional.
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Role (optional)</span>
              <input
                value={searchForm.role}
                onChange={(e) => setSearchForm({ ...searchForm, role: e.target.value })}
                placeholder="e.g. Software Developer"
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-slate-900 focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Location (optional)</span>
              <input
                value={searchForm.location}
                onChange={(e) => setSearchForm({ ...searchForm, location: e.target.value })}
                placeholder="e.g. Chennai"
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-slate-900 focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Max results</span>
              <select
                value={searchForm.limit}
                onChange={(e) => setSearchForm({ ...searchForm, limit: Number(e.target.value) })}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:outline-none"
              >
                {[10, 20, 50, 100].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              disabled={run !== null && run.status === "starting"}
              onClick={() => applySearch(searchForm)}
              className="rounded bg-slate-900 px-5 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Run Search
            </button>
            {run && !runFinished && (
              <span className="text-sm text-slate-500">
                {run.status === "starting" ? "Starting…" : "Importing jobs…"}
              </span>
            )}
          </div>

          {runError && <p className="mt-3 text-sm text-red-600">{runError}</p>}
          {runFinished && (
            <div
              className={`mt-4 rounded border px-4 py-3 text-sm ${
                run.status === "FAILED"
                  ? "border-red-200 bg-red-50 text-red-700"
                  : "border-emerald-200 bg-emerald-50 text-emerald-700"
              }`}
            >
              {run.status === "FAILED" ? (
                <span>Search failed: {runDetails.message || run.status}</span>
              ) : (
                <span>
                  Completed — found {runDetails.discovered ?? run.jobs_found ?? 0}, imported{" "}
                  {runDetails.inserted ?? 0}
                  {runDetails.duplicates ? `, skipped ${runDetails.duplicates} duplicates` : ""}
                  {runDetails.invalid ? `, ${runDetails.invalid} invalid` : ""}.
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-6">
        {loading ? (
          <p className="text-sm text-slate-500">Loading jobs…</p>
        ) : jobs.length === 0 ? (
          <EmptyState
            title="No jobs shown"
            description={
              total === 0
                ? "No discovered jobs yet. Run “Search for New Jobs” to import listings from Apify."
                : "No jobs match the current filters."
            }
          />
        ) : (
          <>
            <p className="mb-3 text-xs text-slate-500">
              {total} job{total === 1 ? "" : "s"} · Page {page} of {pages || 1}
            </p>
            <div className="space-y-3">
              {jobs.map((job) => (
                <JobCard key={job.id} job={job} />
              ))}
            </div>
          </>
        )}
      </div>

      {pages > 1 && (
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">Per page</label>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="rounded border border-slate-300 px-2 py-1 text-sm text-slate-700 focus:outline-none"
            >
              {PAGE_SIZES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => fetchJobs(page - 1)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:border-slate-400 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={page >= pages}
              onClick={() => fetchJobs(page + 1)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:border-slate-400 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}