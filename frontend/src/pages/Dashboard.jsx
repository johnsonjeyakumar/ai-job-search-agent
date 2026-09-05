import { Link } from "react-router-dom";
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