import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api/client.js";
import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

const BAND_STYLES = {
  APPLY_NOW: "border-emerald-200 bg-emerald-50",
  APPLY: "border-green-200 bg-green-50",
  REVIEW: "border-amber-200 bg-amber-50",
  LOW_PRIORITY: "border-orange-200 bg-orange-50",
  SKIP: "border-rose-200 bg-rose-50",
};

const BAND_LABEL = {
  APPLY_NOW: "text-emerald-700",
  APPLY: "text-green-700",
  REVIEW: "text-amber-700",
  LOW_PRIORITY: "text-orange-700",
  SKIP: "text-rose-700",
};

const GROUPS = [
  { key: "APPLY_NOW", title: "Apply now", hint: "High personal match and strong listing quality." },
  { key: "APPLY", title: "Apply", hint: "Good fit for your profile — worth pursuing." },
  { key: "REVIEW", title: "Review", hint: "Reasonable fit; check the details before deciding." },
  { key: "LOW_PRIORITY", title: "Low priority", hint: "Weak fit — only if you have spare effort." },
  { key: "SKIP", title: "Skip", hint: "Blocked or a poor match — not worth applying." },
];

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function ScorePill({ label, value }) {
  if (value == null) {
    return (
      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-400">
        {label}: unknown
      </span>
    );
  }
  return (
    <span className="rounded-md bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white">
      {label}: {Math.round(value)}
    </span>
  );
}

function JobRow({ job }) {
  return (
    <div className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0">
        <Link to={`/jobs/${job.id}`} className="text-sm font-semibold text-slate-900 hover:underline">
          {job.title}
        </Link>
        <p className="text-xs text-slate-500">
          {job.company} · {job.location || "Location not specified"}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <ScorePill label="Opportunity" value={job.opportunity?.opportunity_score} />
        <ScorePill label="Match" value={job.match?.match_score} />
        <span className="hidden text-xs text-slate-400 md:inline">Posted {formatDate(job.posted_date)}</span>
      </div>
    </div>
  );
}

export default function Recommendations() {
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet("/jobs?sort=opportunity_desc&limit=100")
      .then((data) => setJobs(data.items || []))
      .catch((err) => setError(err.message));
  }, []);

  const evaluated = jobs.filter((job) => job.opportunity?.opportunity_score != null);
  const grouped = {};
  for (const group of GROUPS) grouped[group.key] = evaluated.filter((job) => job.opportunity.recommendation === group.key);

  return (
    <div>
      <PageHeader
        title="Recommendations"
        description="Collected jobs ranked by opportunity — a blend of personal match, listing quality, freshness, and company signals."
      />
      <p className="text-xs text-slate-400">
        Missing signals are treated as unknown and excluded from scoring, never guessed. Scores use your profile and
        preferences.
      </p>

      {error ? (
        <p className="mt-4 text-sm text-red-600">{error}</p>
      ) : evaluated.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            title="No recommendations yet"
            description="Match and opportunity scoring will appear once jobs exist and a profile is configured."
          />
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          {GROUPS.map((group) => {
            const items = grouped[group.key];
            if (items.length === 0) return null;
            return (
              <div key={group.key} className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
                <div className={`flex flex-wrap items-center justify-between gap-2 border-b px-5 py-3 ${BAND_STYLES[group.key]}`}>
                  <div>
                    <h3 className={`text-sm font-semibold ${BAND_LABEL[group.key]}`}>
                      {group.title} <span className="font-normal text-slate-500">({items.length})</span>
                    </h3>
                    <p className="mt-0.5 text-xs text-slate-500">{group.hint}</p>
                  </div>
                  <Link to="/jobs" className="text-xs font-medium text-slate-600 hover:underline">
                    Browse all jobs →
                  </Link>
                </div>
                <div className="divide-y divide-slate-100 px-5">
                  {items.map((job) => (
                    <JobRow key={job.id} job={job} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}