import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api/client.js";
import { useAppData } from "../context/AppDataContext.jsx";
import PageHeader from "../components/PageHeader.jsx";
import StatCard from "../components/StatCard.jsx";

const STATS = [
  { label: "Jobs Found", value: 0 },
  { label: "Strong Matches", value: 0 },
  { label: "Applications", value: 0 },
  { label: "Interviews", value: 0 },
  { label: "Rejections", value: 0 },
];

const FRESHNESS_ROWS = [
  { key: "very_fresh", label: "Very fresh", className: "bg-emerald-600" },
  { key: "fresh", label: "Fresh", className: "bg-green-500" },
  { key: "recent", label: "Recent", className: "bg-sky-500" },
  { key: "aging", label: "Aging", className: "bg-amber-500" },
  { key: "stale", label: "Stale", className: "bg-rose-500" },
  { key: "unknown", label: "Unknown", className: "bg-slate-300" },
];

function FreshnessBars({ counts }) {
  const values = FRESHNESS_ROWS.map((row) => ({ ...row, count: counts?.[row.key] ?? 0 }));
  const total = values.reduce((sum, row) => sum + row.count, 0);
  if (total === 0) return <p className="text-sm text-slate-500">No jobs yet — run a search to begin.</p>;
  return (
    <div>
      <div>
        {values.map((row) => (
          <div key={row.key} className="flex items-center gap-2 py-1">
            <span className="w-20 shrink-0 text-xs text-slate-500">{row.label}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full ${row.className}`} style={{ width: `${(row.count / total) * 100}%` }} />
            </div>
            <span className="w-8 shrink-0 text-right text-xs font-medium text-slate-700">{row.count}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-400">Freshness of posting date across all collected jobs.</p>
    </div>
  );
}

const RECOMMENDATION_ROWS = [
  { key: "APPLY_NOW", label: "Apply now", className: "bg-emerald-600" },
  { key: "APPLY", label: "Apply", className: "bg-green-500" },
  { key: "REVIEW", label: "Review", className: "bg-amber-500" },
  { key: "LOW_PRIORITY", label: "Low priority", className: "bg-orange-400" },
  { key: "SKIP", label: "Skip", className: "bg-rose-500" },
];

function RecommendationBars({ counts }) {
  const values = RECOMMENDATION_ROWS.map((row) => ({ ...row, count: counts?.[row.key] ?? 0 }));
  const total = values.reduce((sum, row) => sum + row.count, 0);
  if (total === 0) return <p className="text-sm text-slate-500">No evaluated jobs yet.</p>;
  return (
    <div>
      <div>
        {values.map((row) => (
          <div key={row.key} className="flex items-center gap-2 py-1">
            <span className="w-24 shrink-0 text-xs text-slate-500">{row.label}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full ${row.className}`} style={{ width: `${(row.count / total) * 100}%` }} />
            </div>
            <span className="w-8 shrink-0 text-right text-xs font-medium text-slate-700">{row.count}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-400">
        Final recommendations across {total} evaluated job{total === 1 ? "" : "s"}.
      </p>
    </div>
  );
}

function SetupCheck({ label, done }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span
        className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold ${
          done ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400"
        }`}
      >
        {done ? "✓" : "·"}
      </span>
      <span className={done ? "text-slate-700" : "text-slate-500"}>{label}</span>
    </div>
  );
}

export default function Dashboard() {
  const { profile, preferences, resumes, health, loading } = useAppData();
  const [stats, setStats] = useState(null);

  useEffect(() => {
    apiGet("/jobs/stats")
      .then(setStats)
      .catch(() => {});
  }, []);

  const profileDone = !!profile?.name && !!profile?.email;
  const resumeCount = resumes?.length || 0;
  const stepsDone = [profileDone, resumeCount > 0, !!preferences].filter(Boolean).length;

  return (
    <div>
      <PageHeader title="Dashboard" description="Overview of your job search activity." />

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
        !profileDone && (
          <div className="mb-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Finish setting up your profile</h3>
                <p className="mt-1 text-sm text-slate-500">
                  Complete {3 - stepsDone} of {3 - stepsDone === 1 ? "1 step" : "3 steps"} in under 5 minutes to use the job
                  search fully.
                </p>
              </div>
              <Link
                to="/onboarding"
                className="rounded bg-slate-900 px-5 py-2 text-sm font-medium text-white hover:bg-slate-800"
              >
                Start onboarding
              </Link>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-3">
              <SetupCheck label="Profile details" done={profileDone} />
              <SetupCheck label="Job preferences" done={!!preferences} />
              <SetupCheck label="Upload a resume" done={resumeCount > 0} />
            </div>
          </div>
        )
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {STATS.map((stat) => (
          <StatCard key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Match Intelligence</h3>
            <p className="mt-1 text-xs text-slate-500">How collected jobs fit your profile and preferences.</p>
          </div>
          <Link to="/recommendations" className="text-xs font-medium text-slate-600 hover:underline">
            View recommendations →
          </Link>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Evaluated jobs" value={stats?.matches?.evaluated_jobs ?? 0} />
          <StatCard
            label="Avg match"
            value={stats?.matches?.avg_match_score != null ? `${stats.matches.avg_match_score}/100` : "—"}
          />
          <StatCard
            label="Avg opportunity"
            value={stats?.matches?.avg_opportunity_score != null ? `${stats.matches.avg_opportunity_score}/100` : "—"}
          />
          <StatCard
            label="Avg quality"
            value={stats?.avg_quality != null ? `${stats.avg_quality}/100` : "—"}
          />
        </div>
        <div className="mt-4">
          <RecommendationBars counts={stats?.matches?.recommendation_counts} />
        </div>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">Job Intelligence</h3>
          <p className="mt-1 text-xs text-slate-500">Based on your collected jobs.</p>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <StatCard label="Jobs collected" value={stats?.total ?? 0} />
            <StatCard label="Avg quality" value={stats?.avg_quality != null ? `${stats.avg_quality}/100` : "—"} />
            <div className="flex items-center">
              <Link to="/companies" className="text-xs font-medium text-slate-600 hover:underline">
                View companies →
              </Link>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">Freshness Overview</h3>
          <p className="mt-1 text-xs text-slate-500">How recent the collected job postings are.</p>
          <div className="mt-3">
            <FreshnessBars counts={stats?.freshness_counts} />
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">Top Companies</h3>
        <p className="mt-1 text-xs text-slate-500">Employers with the most collected job postings.</p>
        {stats?.top_companies?.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <th className="py-2 pr-4 font-medium">Company</th>
                  <th className="py-2 pr-4 font-medium">Jobs</th>
                  <th className="py-2 pr-4 font-medium">Roles</th>
                  <th className="py-2 font-medium">Sources</th>
                </tr>
              </thead>
              <tbody>
                {stats.top_companies.map((company, index) => (
                  <tr key={`${company.id}-${index}`} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 pr-4 font-medium text-slate-700">
                      <Link to="/companies" className="hover:underline">
                        {company.display_name || company.normalized_name}
                      </Link>
                    </td>
                    <td className="py-2 pr-4 text-slate-600">{company.active_job_count}</td>
                    <td className="py-2 pr-4 text-slate-600">{company.distinct_role_count}</td>
                    <td className="py-2 text-slate-600">{company.source_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-500">No companies observed yet.</p>
        )}
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">Backend Status</h3>
        {health ? (
          <p className="mt-2 text-sm text-emerald-600">
            Connected — API v{health.version} · Database{" "}
            {health.database ? "available" : "unavailable"}
          </p>
        ) : (
          <p className="mt-2 text-sm text-red-600">Backend unreachable.</p>
        )}
      </div>
    </div>
  );
}