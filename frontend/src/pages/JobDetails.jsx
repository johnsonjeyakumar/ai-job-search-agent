import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../api/client.js";
import PageHeader from "../components/PageHeader.jsx";

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function labelize(value) {
  if (!value) return null;
  return value
    .split(/[_ ]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function Detail({ label, children }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-1 text-sm text-slate-700">{children || "—"}</dd>
    </div>
  );
}

function LinkOut({ job }) {
  const links = [
    { href: job.url || job.application_url, label: "View job posting" },
    { href: job.company_url, label: "Company profile" },
  ].filter((link) => link.href);
  if (links.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {links.map((link) => (
        <a
          key={link.label}
          href={link.href}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          {link.label}
        </a>
      ))}
    </div>
  );
}

function ListBlock({ title, items }) {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
        {values.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

const FRESHNESS_STYLES = {
  VERY_FRESH: "bg-emerald-100 text-emerald-700",
  FRESH: "bg-green-100 text-green-700",
  RECENT: "bg-sky-100 text-sky-700",
  AGING: "bg-amber-100 text-amber-700",
  STALE: "bg-rose-100 text-rose-700",
  UNKNOWN: "bg-slate-100 text-slate-500",
};

function Section({ title, children }) {
  return (
    <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

function JobIntelligence({ freshness, quality }) {
  if (!freshness && !quality) return null;
  const status = freshness?.status || "UNKNOWN";
  return (
    <Section title="Job Intelligence">
      <p className="mt-1 text-xs text-slate-400">Based on your collected jobs.</p>

      <div className="mt-4 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Freshness</dt>
          <dd className="mt-1">
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${FRESHNESS_STYLES[status]}`}>
              {freshness?.explanation || "Undefined"}
            </span>
          </dd>
        </div>
        <Detail label="Age">{(freshness?.age_in_days ?? null) === null ? "Unknown" : `${freshness.age_in_days} days`}</Detail>
        <Detail label="Quality score">{quality ? `${quality.overall_score}/100` : "—"}</Detail>
        <Detail label="Scoring version">{quality?.scoring_version || "—"}</Detail>
      </div>

      {quality && (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(quality.components || {}).map(([key, component]) => (
              <div key={key} className="rounded-md border border-slate-100 bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-700">{component.label}</span>
                  <span className="text-sm font-bold text-slate-900">
                    {component.score ?? "—"}
                    {component.score === null ? "" : "/100"}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{component.message || "—"}</p>
              </div>
            ))}
          </div>

          {(quality.positive?.length > 0 || quality.negative?.length > 0) && (
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              {quality.positive?.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-emerald-600">Positive signals</h4>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                    {quality.positive.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              {quality.negative?.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-rose-600">Missing signals</h4>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                    {quality.negative.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Section>
  );
}

const MATCH_STYLES = {
  APPLY_NOW: "bg-emerald-100 text-emerald-800",
  APPLY: "bg-green-100 text-green-800",
  REVIEW: "bg-amber-100 text-amber-800",
  LOW_PRIORITY: "bg-orange-100 text-orange-800",
  SKIP: "bg-rose-100 text-rose-800",
};

const STATUS_STYLES = {
  MATCHED: "text-emerald-700",
  PARTIAL: "text-amber-700",
  MISSING: "text-rose-700",
  UNKNOWN: "text-slate-500",
};

function RequirementBucket({ title, items }) {
  const values = Array.isArray(items) ? items : [];
  if (values.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title} ({values.length})
      </h4>
      <ul className="mt-2 space-y-1 text-sm text-slate-700">
        {values.map((item, index) => (
          <li key={index} className="flex flex-wrap items-start justify-between gap-2">
            <span>
              {item.term}
              {item.reason ? <span className="text-xs text-slate-400"> — {item.reason}</span> : null}
            </span>
            <span className={`text-xs font-medium ${STATUS_STYLES[item.status] || "text-slate-500"}`}>
              {item.status}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MatchIntelligence({ match }) {
  if (!match) return null;
  const breakdown = match.criteria_breakdown || {};
  const requirementBuckets = [
    ["Matched requirements", match.matched_requirements],
    ["Partial requirements", match.partial_requirements],
    ["Missing requirements", match.missing_requirements],
    ["Unknown requirements", match.unknown_requirements],
  ];
  return (
    <Section title="Personal Match">
      <p className="mt-1 text-xs text-slate-400">
        How well this job fits your profile and preferences. Missing signals are excluded, never guessed.
      </p>

      <div className="mt-4 flex flex-wrap gap-3">
        <div className="flex items-center gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3">
          <span className="text-3xl font-bold text-slate-900">
            {match.match_score == null ? "—" : Math.round(match.match_score)}
          </span>
          <div>
            <span className={`rounded-md border px-2 py-0.5 text-xs font-semibold ${MATCH_STYLES[match.recommendation] || ""}`}>
              {match.recommendation || "REVIEW"}
            </span>
            <p className="mt-1 text-xs text-slate-500">Confidence {Math.round((match.confidence_score || 0) * 100)}%</p>
          </div>
        </div>
        <div className="grow rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Evidence</p>
          <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">
            {(match.evidence || []).slice(0, 8).map((item, index) => (
              <li key={index}>{item}</li>
            ))}
            {(match.evidence || []).length === 0 && <li>No positive signals yet.</li>}
          </ul>
        </div>
      </div>

      {(match.blockers || []).length > 0 && (
        <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-rose-600">Blockers — recommend skipping</h4>
          <ul className="mt-1 list-disc pl-5 text-sm text-rose-700">
            {match.blockers.map((blocker, index) => (
              <li key={index}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(breakdown).map(([key, component]) => (
          <div key={key} className="rounded-md border border-slate-100 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-700">{component.label || key}</span>
              <span className={`text-sm font-bold ${STATUS_STYLES[component.status] || ""}`}>
                {component.score == null ? component.status : `${Math.round(component.score)}/100`}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-500">{component.message || "—"}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-6 sm:grid-cols-2">
        {requirementBuckets.map(([title, items]) => (
          <RequirementBucket key={title} title={title} items={items} />
        ))}
      </div>
    </Section>
  );
}

function OpportunityIntelligence({ opportunity }) {
  if (!opportunity) return null;
  const explanation = opportunity.explanation || [];
  const blockers = opportunity.blockers || [];
  const rows = explanation.filter((entry) => entry.key !== "cap" && entry.key !== "blocker");
  const caps = explanation.filter((entry) => entry.key === "cap");
  return (
    <Section title="Opportunity Score">
      <p className="mt-1 text-xs text-slate-400">
        Blends personal match with listing quality, freshness, and company signals for a final recommendation.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span className="text-3xl font-bold text-slate-900">
          {opportunity.opportunity_score == null ? "—" : Math.round(opportunity.opportunity_score)}
        </span>
        <span
          className={`rounded-md border px-2 py-0.5 text-xs font-semibold ${
            MATCH_STYLES[opportunity.recommendation] || "border-slate-200 bg-slate-50 text-slate-700"
          }`}
        >
          {opportunity.recommendation || "REVIEW"}
        </span>
        <span className="text-xs text-slate-400">v{opportunity.opportunity_version}</span>
      </div>

      {blockers.length > 0 && (
        <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-rose-600">Blockers — skipping</h4>
          <ul className="mt-1 list-disc pl-5 text-sm text-rose-700">
            {blockers.map((blocker, index) => (
              <li key={index}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {rows.map((entry) => (
          <div key={entry.key} className="rounded-md border border-slate-100 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-700">{entry.label}</span>
              <span className="text-sm font-bold text-slate-900">
                {entry.score == null ? "—" : `${Math.round(entry.score)}/100`}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {entry.message} {entry.weight > 0 ? `· weight ${Math.round(entry.weight * 100)}%` : ""}
            </p>
          </div>
        ))}
      </div>

      {caps.length > 0 && (
        <ul className="mt-4 space-y-1 text-xs text-slate-500">
          {caps.map((entry, index) => (
            <li key={index}>• {entry.message}</li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function CompanyIntelligence({ company }) {
  if (!company) return null;
  return (
    <Section title="Company Intelligence">
      <p className="mt-1 text-xs text-slate-400">Based on your collected jobs.</p>
      <dl className="mt-4 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <Detail label="Company">{company.display_name || company.normalized_name}</Detail>
        <Detail label="Domain">{company.domain || "—"}</Detail>
        <Detail label="Website">
          {company.website ? (
            <a href={company.website} target="_blank" rel="noopener noreferrer" className="text-slate-700 hover:underline">
              {company.website}
            </a>
          ) : (
            "—"
          )}
        </Detail>
        <Detail label="Careers page">{company.careers_url || "—"}</Detail>
        <Detail label="Industry">{company.industry || "Not collected"}</Detail>
        <Detail label="Company size">{company.company_size || "Not collected"}</Detail>
        <Detail label="Jobs observed">{company.active_job_count}</Detail>
        <Detail label="Distinct roles">{company.distinct_role_count}</Detail>
        <Detail label="Sources observed">{company.source_count}</Detail>
        <Detail label="Last seen">{formatDate(company.last_seen_job_at)}</Detail>
      </dl>
    </Section>
  );
}

function RecentActivity({ events }) {
  const items = Array.isArray(events) ? events : [];
  if (items.length === 0) return null;
  return (
    <Section title="Recent Activity">
      <p className="mt-1 text-xs text-slate-400">Lifecycle events observed for this job.</p>
      <ul className="mt-4 space-y-2">
        {items.map((event) => (
          <li key={event.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">
              {labelize(event.event_type)}
            </span>
            <span className="text-xs text-slate-500">{formatDateTime(event.created_at)}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export default function JobDetails() {
  const { id } = useParams();
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet(`/jobs/${id}`)
      .then(setJob)
      .catch((err) => setError(err.message));
  }, [id]);

  if (error) {
    return (
      <div>
        <PageHeader title="Job details" description="" />
        <p className="text-sm text-red-600">{error}</p>
        <Link to="/jobs" className="mt-3 inline-block text-sm font-medium text-slate-700 hover:underline">
          ← Back to jobs
        </Link>
      </div>
    );
  }

  if (!job) {
    return (
      <div>
        <PageHeader title="Job details" description="" />
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title={job.title} description={`${job.company} · ${job.location || "Location not specified"}`} />

      <Link to="/jobs" className="text-sm font-medium text-slate-700 hover:underline">
        ← Back to jobs
      </Link>

      <div className="mt-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <LinkOut job={job} />
          <span className="text-xs text-slate-400">
            {job.source} · Posted {formatDate(job.posted_date)} · Discovered {formatDate(job.discovered_date)}
          </span>
        </div>

        <dl className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <Detail label="Remote type">{labelize(job.remote_type)}</Detail>
          <Detail label="Employment type">{labelize(job.employment_type)}</Detail>
          <Detail label="Experience">{job.experience_required}</Detail>
          <Detail label="Salary">{job.salary}</Detail>
          <Detail label="Source ID">{job.source_job_id}</Detail>
        </dl>

        {job.description && (
          <div className="mt-6">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Description</h4>
            <p className="mt-2 whitespace-pre-line text-sm text-slate-700">{job.description}</p>
          </div>
        )}

        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          <ListBlock title="Requirements" items={job.requirements} />
          <ListBlock title="Skills" items={job.skills} />
        </div>
      </div>

      <MatchIntelligence match={job.match} />
      <OpportunityIntelligence opportunity={job.opportunity} />
      <JobIntelligence freshness={job.freshness} quality={job.quality} />
      <CompanyIntelligence company={job.company_info} />
      <RecentActivity events={job.recent_events} />
    </div>
  );
}