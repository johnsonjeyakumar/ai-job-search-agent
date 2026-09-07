import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiSend } from "../api/client.js";
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

const RATE_LABELS = {
  shortlist_rate: "Shortlisted",
  application_rate: "Applied",
  submission_confirmed_rate: "Confirmed",
  response_rate: "Responses",
  interview_rate: "Interviews",
  offer_rate: "Offers",
  rejection_rate: "Rejections",
  withdrawal_rate: "Withdrawn",
};

function FunnelSection({ funnel }) {
  if (!funnel) return null;
  const max = Math.max(1, ...(funnel.steps || []).map((s) => s.count));
  const rates = funnel.rates || {};
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Application Funnel</h3>
          <p className="mt-1 text-xs text-slate-500">
            Tracked progress across the lifecycle · range: {funnel.range}.
          </p>
        </div>
        <Link to="/applications" className="text-xs font-medium text-slate-600 hover:underline">
          Track applications →
        </Link>
      </div>
      <div className="mt-4 space-y-2">
        {(funnel.steps || []).map((s) => (
          <div key={s.step} className="flex items-center gap-3">
            <span className="w-40 shrink-0 text-xs text-slate-600">{s.label}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full bg-slate-900"
                style={{ width: `${(s.count / max) * 100}%` }}
              />
            </div>
            <span className="w-8 shrink-0 text-right text-xs font-medium text-slate-700">{s.count}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Object.entries(RATE_LABELS).map(([key, label]) => {
          const value = rates[key];
          return (
            <div key={key} className="rounded-md bg-slate-50 p-2">
              <p className="text-xs text-slate-500">{label}</p>
              <p className="mt-0.5 text-lg font-semibold text-slate-900">
                {value == null ? "—" : `${value}%`}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const FOLLOW_UP_STYLE = {
  DUE: "bg-rose-50 text-rose-700 ring-rose-200",
  OVERDUE: "bg-rose-100 text-rose-800 ring-rose-300",
  SCHEDULED: "bg-sky-50 text-sky-700 ring-sky-200",
  RESCHEDULED: "bg-violet-50 text-violet-700 ring-violet-200",
  COMPLETED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  CANCELLED: "bg-slate-100 text-slate-500 ring-slate-200",
  SKIPPED: "bg-slate-100 text-slate-500 ring-slate-200",
};

const PRIORITY_STYLE = {
  HIGH: "bg-rose-100 text-rose-700",
  MEDIUM: "bg-amber-100 text-amber-700",
  LOW: "bg-slate-100 text-slate-600",
};

function followUpActions(followUp, onAction) {
  if (followUp.lifecycle_state === "COMPLETED") return [];
  if (followUp.lifecycle_state === "CANCELLED" || followUp.lifecycle_state === "SKIPPED") {
    return [{ key: "restore", label: "Restore", onClick: () => onAction("restore") }];
  }
  return [
    { key: "complete", label: "Complete", onClick: () => onAction("complete") },
    { key: "reschedule", label: "Reschedule", onClick: () => onAction("reschedule") },
    { key: "skip", label: "Skip", onClick: () => onAction("skip") },
  ];
}

function FollowUpItem({ followUp, onAction }) {
  const reasonLabel = (followUp.reason || "SUBMISSION_FOLLOW_UP").toLowerCase().replaceAll("_", " ");
  return (
    <li className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <Link
          to={`/applications/track/${followUp.application_id}`}
          className="min-w-0 truncate font-medium text-slate-800 hover:underline"
        >
          {followUp.job_title || "Untitled role"}
        </Link>
        <div className="flex shrink-0 items-center gap-1.5">
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${
              FOLLOW_UP_STYLE[followUp.lifecycle_state] || FOLLOW_UP_STYLE.SCHEDULED
            }`}
          >
            {followUp.lifecycle_state}
          </span>
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
              PRIORITY_STYLE[followUp.priority] || PRIORITY_STYLE.MEDIUM
            }`}
          >
            {followUp.priority}
          </span>
        </div>
      </div>
      <p className="truncate text-xs text-slate-500">
        {[followUp.company, reasonLabel, followUp.scheduled_date]
          .filter(Boolean)
          .join(" · ")}
        {followUp.days_late ? ` · ${followUp.days_late}d late` : ""}
        {followUp.resume_version ? ` · ${followUp.resume_version}` : ""}
      </p>
      <div className="flex items-center gap-2 pt-0.5">
        {followUpActions(followUp, (action) => onAction(followUp, action)).map((action) => (
          <button
            key={action.key}
            type="button"
            onClick={action.onClick}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            {action.label}
          </button>
        ))}
      </div>
    </li>
  );
}

function FollowUpSection({ followUps, refreshFollowUps }) {
  if (!followUps) return null;
  const items = followUps.items || [];

  const groups = [
    { key: "OVERDUE", label: "Overdue", items: items.filter((f) => f.lifecycle_state === "OVERDUE") },
    { key: "DUE", label: "Due today", items: items.filter((f) => f.lifecycle_state === "DUE") },
    {
      key: "UPCOMING",
      label: "Upcoming",
      items: items.filter(
        (f) => f.lifecycle_state === "SCHEDULED" || f.lifecycle_state === "RESCHEDULED"
      ),
    },
  ];
  const shown = groups.filter((g) => g.items.length > 0);
  const totalActive = shown.reduce((sum, g) => sum + g.items.length, 0);

  async function handleAction(followUp, action) {
    try {
      if (action === "complete") await apiSend("POST", `/tracking/follow-ups/${followUp.id}/complete`, {});
      if (action === "skip") await apiSend("POST", `/tracking/follow-ups/${followUp.id}/skip`, {});
      if (action === "restore") await apiSend("POST", `/tracking/follow-ups/${followUp.id}/restore`, {});
      if (action === "reschedule") {
        const next = window.prompt("New date (YYYY-MM-DD):", followUp.scheduled_date || "");
        if (!next) return;
        await apiSend("POST", `/tracking/follow-ups/${followUp.id}/reschedule`, { scheduled_date: next });
      }
      refreshFollowUps();
    } catch (error) {
      window.alert(String(error.message || error));
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Follow-ups</h3>
          <p className="mt-1 text-xs text-slate-500">
            Priority, reason and due states across all applications.
          </p>
        </div>
        <Link to="/applications?follow_up=PENDING" className="text-xs font-medium text-slate-600 hover:underline">
          View all →
        </Link>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <div className="rounded-md bg-rose-50 p-2">
          <p className="text-xs text-rose-500">Due today</p>
          <p className="mt-0.5 text-lg font-semibold text-slate-900">{followUps.due_today}</p>
        </div>
        <div className="rounded-md bg-amber-50 p-2">
          <p className="text-xs text-amber-600">Overdue</p>
          <p className="mt-0.5 text-lg font-semibold text-slate-900">{followUps.overdue}</p>
        </div>
        <div className="rounded-md bg-slate-50 p-2">
          <p className="text-xs text-slate-500">Upcoming</p>
          <p className="mt-0.5 text-lg font-semibold text-slate-900">{followUps.upcoming}</p>
        </div>
      </div>
      {totalActive > 0 ? (
        <div className="mt-4 space-y-4">
          {shown.map((group) => (
            <div key={group.key}>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
                {group.label} ({group.items.length})
              </p>
              <ul className="space-y-3">
                {group.items.slice(0, 6).map((followUp) => (
                  <FollowUpItem
                    key={followUp.id}
                    followUp={followUp}
                    onAction={handleAction}
                  />
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-500">No active follow-ups scheduled.</p>
      )}
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
  const [funnel, setFunnel] = useState(null);
  const [followUps, setFollowUps] = useState(null);

  useEffect(() => {
    apiGet("/jobs/stats")
      .then(setStats)
      .catch(() => {});
    apiGet("/analytics/funnel?range=all")
      .then(setFunnel)
      .catch(() => {});
  }, []);

  const refreshFollowUps = () => {
    apiGet("/tracking/follow-ups")
      .then(setFollowUps)
      .catch(() => {});
  };

  useEffect(refreshFollowUps, []);

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
            value={stats?.matches?.average_match_score != null ? `${stats.matches.average_match_score}/100` : "—"}
          />
          <StatCard
            label="Avg opportunity"
            value={stats?.matches?.average_opportunity_score != null ? `${stats.matches.average_opportunity_score}/100` : "—"}
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

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <FunnelSection funnel={funnel} />
        <FollowUpSection followUps={followUps} refreshFollowUps={refreshFollowUps} />
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