import { useEffect, useState } from "react";
import { apiGet } from "../api/client.js";
import PageHeader from "../components/PageHeader.jsx";

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

const SEVERITY_BADGE = {
  success: "bg-emerald-100 text-emerald-700",
  warning: "bg-amber-100 text-amber-700",
  info: "bg-sky-100 text-sky-700",
};

const QUALITY_BADGE = {
  "EXCELLENT SIGNAL": "bg-emerald-100 text-emerald-700",
  GOOD: "bg-green-100 text-green-700",
  PROMISING: "bg-sky-100 text-sky-700",
  "WEAK SIGNAL": "bg-amber-100 text-amber-700",
  "LIMITED DATA": "bg-slate-100 text-slate-500",
  "INSUFFICIENT DATA": "bg-slate-100 text-slate-400",
};

const RANK_BADGE = {
  "STRONGER SIGNAL": "bg-emerald-100 text-emerald-700",
  PROMISING: "bg-sky-100 text-sky-700",
  "LIMITED DATA": "bg-slate-100 text-slate-500",
  "INSUFFICIENT DATA": "bg-slate-100 text-slate-400",
};

function Card({ title, subtitle, children }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Badge({ text, map, fallback }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${
        map[text] || fallback || map.DEFAULT || "bg-slate-100 text-slate-600"
      }`}
    >
      {String(text).replaceAll("_", " ")}
    </span>
  );
}

function StatBox({ label, value, sub }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-0.5 text-2xl font-semibold text-slate-900">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-slate-400">{sub}</p>}
    </div>
  );
}

function fmt(rate) {
  return rate == null ? "—" : `${rate}%`;
}

function PerformanceTable({ rows, qualityKey, rankKey }) {
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-slate-500">No tracked data yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
            <th className="py-2 pr-4 font-medium">Group</th>
            <th className="py-2 pr-4 font-medium">Apps</th>
            <th className="py-2 pr-4 font-medium">Submitted</th>
            <th className="py-2 pr-4 font-medium">Resp</th>
            <th className="py-2 pr-4 font-medium">Int</th>
            <th className="py-2 pr-4 font-medium">Offer</th>
            <th className="py-2 pr-4 font-medium">Resp%</th>
            <th className="py-2 pr-4 font-medium">Int%</th>
            <th className="py-2 pr-4 font-medium">Offer%</th>
            {qualityKey ? <th className="py-2 font-medium">Quality</th> : null}
            {rankKey ? <th className="py-2 font-medium">Rank</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-slate-100 last:border-0">
              <td className="py-2 pr-4 font-medium text-slate-700">
                {row.label}
                {row.limited_label ? (
                  <span className="ml-2 text-[11px] font-normal text-slate-400">{row.limited_label}</span>
                ) : null}
              </td>
              <td className="py-2 pr-4 text-slate-600">{row.applications}</td>
              <td className="py-2 pr-4 text-slate-600">{row.submitted}</td>
              <td className="py-2 pr-4 text-slate-600">{row.responses}</td>
              <td className="py-2 pr-4 text-slate-600">{row.interviews}</td>
              <td className="py-2 pr-4 text-slate-600">{row.offers}</td>
              <td className="py-2 pr-4 text-slate-600">{fmt(row.response_rate)}</td>
              <td className="py-2 pr-4 text-slate-600">{fmt(row.interview_rate)}</td>
              <td className="py-2 pr-4 text-slate-600">{fmt(row.offer_rate)}</td>
              {qualityKey ? (
                <td className="py-2">
                  <Badge text={row[qualityKey].label} map={QUALITY_BADGE} />
                </td>
              ) : null}
              {rankKey ? (
                <td className="py-2">
                  <Badge text={row[rankKey]} map={RANK_BADGE} />
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FunnelCard({ funnel }) {
  if (!funnel) return null;
  const max = Math.max(1, ...(funnel.steps || []).map((s) => s.count));
  return (
    <Card title="Application Funnel" subtitle={`Tracked progress across the lifecycle · range: ${funnel.range}`}>
      <div className="space-y-2">
        {(funnel.steps || []).map((s) => (
          <div key={s.step} className="flex items-center gap-3">
            <span className="w-40 shrink-0 text-xs text-slate-600">{s.label}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full bg-slate-900" style={{ width: `${(s.count / max) * 100}%` }} />
            </div>
            <span className="w-8 shrink-0 text-right text-xs font-medium text-slate-700">{s.count}</span>
          </div>
        ))}
      </div>
      {Object.keys(funnel.rates || {}).length > 0 ? (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(RATE_LABELS).map(([key, label]) => (
            <div key={key} className="rounded-md bg-slate-50 p-2">
              <p className="text-xs text-slate-500">{label}</p>
              <p className="mt-0.5 text-lg font-semibold text-slate-900">
                {funnel.rates[key] == null ? "—" : `${funnel.rates[key]}%`}
              </p>
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function TrendsCard({ trends }) {
  const items = trends?.items || [];
  if (items.length === 0) return <Card title="Application Trend"><p className="text-sm text-slate-500">No applications yet.</p></Card>;
  const max = Math.max(1, ...items.map((p) => p.applications));
  return (
    <Card title="Applications Over Time" subtitle="Tracked applications per ISO week.">
      <div className="space-y-1.5">
        {items.map((p) => (
          <div key={p.week_start} className="flex items-center gap-3">
            <span className="w-24 shrink-0 text-xs text-slate-600">W{p.week} · {p.year}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full bg-sky-600" style={{ width: `${(p.applications / max) * 100}%` }} />
            </div>
            <span className="w-12 shrink-0 text-right text-xs font-medium text-slate-700">{p.applications}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function ResponseTimesCard({ body }) {
  if (!body) return null;
  const stats = [
    { label: "Response (all)", stat: body.days_to_response },
    { label: "Interview", stat: body.days_to_interview },
    { label: "Offer", stat: body.days_to_offer },
  ];
  return (
    <Card title="Response Times" subtitle="Days from submission to a real milestone (never invented).">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {stats.map((s) => (
          <StatBox
            key={s.label}
            label={s.label}
            value={s.stat?.median_days == null ? "—" : `${s.stat.median_days} d`}
            sub={`${s.stat?.measured ?? 0} measured`}
          />
        ))}
      </div>
    </Card>
  );
}

function BreakdownCard({ data }) {
  if (!data) return null;
  const overall = data.overall || {};
  return (
    <Card
      title="Response Time Breakdowns"
      subtitle={data.basis}
    >
      <div className="mb-4 flex items-center justify-between rounded-md bg-slate-50 p-3">
        <span className="text-xs text-slate-600">Overall (first response)</span>
        <span className="text-sm font-semibold text-slate-900">
          {overall.median_days == null ? "—" : `${overall.median_days} d median`} · {overall.measured ?? 0} measured
        </span>
      </div>
      {(data.dimensions || {})["role"] && (data.dimensions.role.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {Object.entries(data.dimensions).map(([dim, rows]) => (
            rows.length > 0 ? (
              <div key={dim}>
                <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
                  {dim.replaceAll("_", " ")}
                </p>
                <ul className="space-y-1">
                  {rows.slice(0, 8).map((r) => (
                    <li key={r.label} className="flex items-baseline justify-between text-sm">
                      <span className="truncate pr-2 text-slate-600">{r.label}</span>
                      <span className="shrink-0 font-medium text-slate-800">
                        {r.median_days == null ? "—" : `${r.median_days} d`}
                        <span className="ml-1 font-normal text-slate-400">({r.measured})</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null
          ))}
        </div>
      ) : (
        <p className="text-sm text-slate-500">No response-time data yet.</p>
      ))}
    </Card>
  );
}

function SourcePerformanceCard({ data }) {
  if (!data) return null;
  return (
    <Card title="Source Quality" subtitle={data.quality_basis}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">Discovery sources</p>
          <PerformanceTable rows={data.discovery} qualityKey="source_quality" />
        </div>
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">Submission sources</p>
          <PerformanceTable rows={data.submission} qualityKey="source_quality" />
        </div>
      </div>
    </Card>
  );
}

function ResumeCard({ data, compare, setCompare, compareResult, setCompareResult }) {
  if (!data) return null;
  const labels = (data.items || []).map((r) => r.label);
  const runCompare = () => {
    if (!compare.left || !compare.right) return;
    apiGet(`/analytics/resumes/compare?left=${encodeURIComponent(compare.left)}&right=${encodeURIComponent(compare.right)}`)
      .then(setCompareResult)
      .catch(() => {});
  };
  return (
    <Card title="Resume Performance" subtitle="Historical snapshots with deterministic inferred rank.">
      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-md bg-slate-50 p-3">
        <label className="text-xs text-slate-500">
          Left
          <select
            value={compare.left}
            onChange={(e) => setCompare({ ...compare, left: e.target.value })}
            className="mt-1 block w-48 rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
          >
            <option value="">Choose resume…</option>
            {labels.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-500">
          Right
          <select
            value={compare.right}
            onChange={(e) => setCompare({ ...compare, right: e.target.value })}
            className="mt-1 block w-48 rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
          >
            <option value="">Choose resume…</option>
            {labels.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
        <button
          type="button"
          onClick={runCompare}
          disabled={!compare.left || !compare.right}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          Compare
        </button>
      </div>
      {compareResult ? (
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {[
            { key: "left", label: compareResult.left?.label },
            { key: "right", label: compareResult.right?.label },
          ].map((side) => {
            const row = compareResult[side.key]?.row;
            return (
              <div key={side.key} className="rounded-md border border-slate-200 p-3">
                <p className="text-sm font-semibold text-slate-800">{side.label || "Unmatched resume"}</p>
                {row ? (
                  <ul className="mt-2 space-y-1 text-xs text-slate-600">
                    <li>Submitted: {row.submitted} · Responses: {row.responses}</li>
                    <li>Response rate {fmt(row.response_rate)} · Interview {fmt(row.interview_rate)} · Offer {fmt(row.offer_rate)}</li>
                    <li>
                      <Badge text={row.rank_label} map={RANK_BADGE} />
                      <span className="ml-2">Composite {row.composite_score}</span>
                    </li>
                  </ul>
                ) : (
                  <p className="mt-2 text-xs text-slate-400">No matching historical snapshot.</p>
                )}
              </div>
            );
          })}
        </div>
      ) : null}
      <PerformanceTable rows={data.items} rankKey="rank_label" />
      <p className="mt-3 text-xs text-slate-400">
        Rank = composite (interview% + offer%); labels at right of rank column. Sample floor: {data.small_sample_threshold}.
      </p>
    </Card>
  );
}

function RecommendedCard({ data }) {
  if (!data) return null;
  const c = data.candidate;
  return (
    <Card title="Recommended Resume" subtitle={data.basis}>
      {c ? (
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <p className="text-lg font-semibold text-slate-900">{c.label}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {c.submitted} submissions · responses {c.responses} · interviews {c.interviews} · offers {c.offers}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge text={c.rank_label} map={RANK_BADGE} />
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
              composite {c.composite_score}
            </span>
          </div>
          {data.alternative ? (
            <p className="w-full text-xs text-slate-500">
              Alternative: {data.alternative.label} (composite {data.alternative.composite_score}, {data.alternative.submitted} submissions)
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-slate-500">{data.message}</p>
      )}
    </Card>
  );
}

function InsightsCard({ data }) {
  if (!data) return null;
  return (
    <Card title="Insights" subtitle={data.basis}>
      <ul className="space-y-3">
        {(data.items || []).map((item) => (
          <li key={item.key} className="rounded-md border border-slate-200 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge text={item.severity} map={SEVERITY_BADGE} />
              <span className="text-sm font-semibold text-slate-800">{item.title}</span>
            </div>
            <p className="mt-1 text-sm text-slate-600">{item.message}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function FollowUpHealthCard({ data }) {
  if (!data) return null;
  const boxes = [
    { label: "Due today", value: data.due_today, cls: "bg-rose-50" },
    { label: "Overdue", value: data.overdue, cls: "bg-amber-50" },
    { label: "Upcoming", value: data.upcoming, cls: "bg-slate-50" },
    { label: "Completed", value: data.completed, cls: "bg-emerald-50" },
    { label: "Cancelled", value: data.cancelled, cls: "bg-slate-50" },
    { label: "Skipped", value: data.skipped, cls: "bg-slate-50" },
  ];
  return (
    <Card title="Follow-up Health" subtitle={data.date_basis}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {boxes.map((b) => (
          <div key={b.label} className={`rounded-md p-3 ${b.cls}`}>
            <p className="text-xs text-slate-500">{b.label}</p>
            <p className="mt-0.5 text-2xl font-semibold text-slate-900">{b.value}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-400">Total scheduled follow-ups: {data.total}</p>
    </Card>
  );
}

export default function Analytics() {
  const [range, setRange] = useState("all");
  const [funnel, setFunnel] = useState(null);
  const [trends, setTrends] = useState(null);
  const [responses, setResponses] = useState(null);
  const [breakdowns, setBreakdowns] = useState(null);
  const [sources, setSources] = useState(null);
  const [resumes, setResumes] = useState(null);
  const [recommended, setRecommended] = useState(null);
  const [insights, setInsights] = useState(null);
  const [followUps, setFollowUps] = useState(null);
  const [compare, setCompare] = useState({ left: "", right: "" });
  const [compareResult, setCompareResult] = useState(null);

  useEffect(() => {
    apiGet(`/analytics/funnel?range=${range}`).then(setFunnel).catch(() => {});
    apiGet(`/analytics/trends?range=${range}`).then(setTrends).catch(() => {});
  }, [range]);

  useEffect(() => {
    apiGet("/analytics/response-times").then(setResponses).catch(() => {});
    apiGet("/analytics/response-times/breakdowns").then(setBreakdowns).catch(() => {});
    apiGet("/analytics/sources/performance").then(setSources).catch(() => {});
    apiGet("/analytics/resumes").then(setResumes).catch(() => {});
    apiGet("/analytics/recommended-resume").then(setRecommended).catch(() => {});
    apiGet("/analytics/insights").then(setInsights).catch(() => {});
    apiGet("/analytics/follow-ups").then(setFollowUps).catch(() => {});
  }, []);

  return (
    <div>
      <PageHeader title="Analytics" description="Deterministic, evidence-only performance across your job search." />

      <div className="mb-4 flex items-center gap-2">
        <label className="text-sm text-slate-600">Range</label>
        <select
          value={range}
          onChange={(e) => setRange(e.target.value)}
          className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
        >
          <option value="all">All time</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="90d">Last 90 days</option>
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <FunnelCard funnel={funnel} />
        <TrendsCard trends={trends} />
      </div>

      <div className="mt-4">
        <ResponseTimesCard body={responses} />
      </div>

      <div className="mt-4">
        <BreakdownCard data={breakdowns} />
      </div>

      <div className="mt-4">
        <SourcePerformanceCard data={sources} />
      </div>

      <div className="mt-4">
        <RecommendedCard data={recommended} />
      </div>

      <div className="mt-4">
        <ResumeCard
          data={resumes}
          compare={compare}
          setCompare={setCompare}
          compareResult={compareResult}
          setCompareResult={setCompareResult}
        />
      </div>

      <div className="mt-4">
        <FollowUpHealthCard data={followUps} />
      </div>

      <div className="mt-4">
        <InsightsCard data={insights} />
      </div>
    </div>
  );
}