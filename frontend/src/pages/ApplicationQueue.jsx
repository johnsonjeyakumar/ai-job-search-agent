import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api/client.js";
import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

const STATE_STYLES = {
  QUEUED: "bg-sky-100 text-sky-700",
  PREPARING: "bg-indigo-100 text-indigo-700",
  READY: "bg-emerald-100 text-emerald-700",
  NEEDS_INPUT: "bg-amber-100 text-amber-700",
  REVIEW: "bg-orange-100 text-orange-700",
  BLOCKED: "bg-rose-100 text-rose-700",
  APPROVED: "bg-emerald-100 text-emerald-700",
  EXECUTING: "bg-violet-100 text-violet-700",
  SUBMITTED: "bg-emerald-100 text-emerald-700",
  FAILED: "bg-rose-100 text-rose-700",
  SKIPPED: "bg-slate-100 text-slate-500",
  COMPLETED: "bg-emerald-100 text-emerald-700",
};

const ATTENTION_STYLES = {
  AUTO: "bg-emerald-100 text-emerald-700",
  ASK: "bg-amber-100 text-amber-700",
  REVIEW: "bg-orange-100 text-orange-700",
  BLOCK: "bg-rose-100 text-rose-700",
};

function stateStyle(s) { return STATE_STYLES[s] || "bg-slate-100 text-slate-600"; }
function attentionStyle(a) { return ATTENTION_STYLES[a] || "bg-slate-100 text-slate-600"; }

function formatScore(v) { return v != null ? Number(v).toFixed(1) : "—"; }

export default function ApplicationQueue() {
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [autopilot, setAutopilot] = useState(null);
  const [filter, setFilter] = useState({ state: "", attention: "" });
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    try {
      const params = [];
      if (filter.state) params.push(`state=${filter.state}`);
      if (filter.attention) params.push(`attention=${filter.attention}`);
      const qs = params.length ? `?${params.join("&")}` : "";
      const [s, q] = await Promise.all([
        apiGet("/api/v1/queue/stats"),
        apiGet(`/api/v1/queue${qs}`),
      ]);
      setStats(s);
      setItems(q.items || []);
    } catch (e) { setError(e.message); }
  }

  async function loadAutopilot() {
    try { setAutopilot(await apiGet("/api/v1/queue/autopilot/status")); }
    catch { /* no run */ }
  }

  useEffect(() => { load(); loadAutopilot(); }, [filter]);

  async function startAutopilot(count) {
    setLoading(true);
    try {
      await apiSend("POST", "/api/v1/queue/autopilot/start", { target_count: count });
      await loadAutopilot();
    } catch (e) { setError(e.message); }
    setLoading(false);
  }

  async function pauseAutopilot() {
    if (!autopilot?.active_run) return;
    setLoading(true);
    try {
      await apiSend("POST", `/api/v1/queue/autopilot/${autopilot.active_run.id}/pause`, {});
      await loadAutopilot();
    } catch (e) { setError(e.message); }
    setLoading(false);
  }

  async function resumeAutopilot() {
    if (!autopilot?.active_run) return;
    setLoading(true);
    try {
      await apiSend("POST", `/api/v1/queue/autopilot/${autopilot.active_run.id}/resume`, {});
      await loadAutopilot();
    } catch (e) { setError(e.message); }
    setLoading(false);
  }

  async function stopAutopilot() {
    if (!autopilot?.active_run) return;
    setLoading(true);
    try {
      await apiSend("POST", `/api/v1/queue/autopilot/${autopilot.active_run.id}/stop`, {});
      await loadAutopilot();
    } catch (e) { setError(e.message); }
    setLoading(false);
  }

  async function skipItem(id) {
    if (!confirm("Skip this item?")) return;
    try {
      await apiSend("POST", `/api/v1/queue/${id}/skip`, { reason: "Skipped by user" });
      await load();
    } catch (e) { setError(e.message); }
  }

  async function runPreflight(id) {
    try {
      await apiSend("POST", `/api/v1/queue/${id}/preflight`, {});
      await load();
    } catch (e) { setError(e.message); }
  }

  return (
    <div>
      <PageHeader
        title="Application Queue"
        description="Autopilot orchestration for automatic job applications."
      />

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {/* Stats Cards */}
      {stats && (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard label="Pending" value={stats.pending_count} />
          <StatCard label="Submitted Today" value={stats.daily_submitted} />
          <StatCard label="Target" value={stats.daily_target} />
          <StatCard label="Active" value={stats.active_execution_count} />
        </div>
      )}

      {/* Autopilot Controls */}
      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-700">Autopilot</h3>
        <div className="flex items-center gap-3">
          {autopilot?.active_run ? (
            <>
              <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${autopilot.active_run.status === "RUNNING" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                {autopilot.active_run.status}
              </span>
              <span className="text-xs text-slate-500">
                {autopilot.active_run.processed_count}/{autopilot.active_run.target_count} items
              </span>
              {autopilot.active_run.status === "RUNNING" && (
                <>
                  <button onClick={pauseAutopilot} disabled={loading} className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">Pause</button>
                  <button onClick={stopAutopilot} disabled={loading} className="rounded border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50">Stop</button>
                </>
              )}
              {autopilot.active_run.status === "PAUSED" && (
                <>
                  <button onClick={resumeAutopilot} disabled={loading} className="rounded border border-emerald-300 px-3 py-1.5 text-xs font-medium text-emerald-600 hover:bg-emerald-50 disabled:opacity-50">Resume</button>
                  <button onClick={stopAutopilot} disabled={loading} className="rounded border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50">Stop</button>
                </>
              )}
            </>
          ) : (
            <>
              <span className="text-xs text-slate-500">No active run</span>
              <button onClick={() => startAutopilot(5)} disabled={loading} className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                Start Autopilot (5)
              </button>
              <button onClick={() => startAutopilot(10)} disabled={loading} className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                Start Autopilot (10)
              </button>
            </>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 flex items-center gap-3">
        <select
          value={filter.state}
          onChange={(e) => setFilter((f) => ({ ...f, state: e.target.value }))}
          className="rounded border border-slate-300 px-2 py-1.5 text-xs text-slate-600"
        >
          <option value="">All states</option>
          {Object.keys(STATE_STYLES).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          value={filter.attention}
          onChange={(e) => setFilter((f) => ({ ...f, attention: e.target.value }))}
          className="rounded border border-slate-300 px-2 py-1.5 text-xs text-slate-600"
        >
          <option value="">All attention</option>
          <option value="AUTO">AUTO</option>
          <option value="ASK">ASK</option>
          <option value="REVIEW">REVIEW</option>
          <option value="BLOCK">BLOCK</option>
        </select>
      </div>

      {/* Queue Items */}
      {items.length === 0 && !error ? (
        <EmptyState
          title="Queue is empty"
          description="No items in the processing queue yet. Approved packages will appear here."
        />
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <QueueRow
              key={item.id}
              item={item}
              onSkip={() => skipItem(item.id)}
              onPreflight={() => runPreflight(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value ?? "—"}</p>
    </div>
  );
}

function QueueRow({ item, onSkip, onPreflight }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${stateStyle(item.queue_state)}`}>
              {item.queue_state}
            </span>
            {item.attention && (
              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${attentionStyle(item.attention)}`}>
                {item.attention}
              </span>
            )}
            {item.platform && <span className="text-xs text-slate-400">{item.platform}</span>}
          </div>
          <p className="mt-1.5 truncate text-sm font-medium text-slate-800">
            {item.job_title || `Job #${item.job_id}`}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            {item.company_name || ""} {item.resume_name ? ` · ${item.resume_name}` : ""}
          </p>
          {item.attention_reason && (
            <p className="mt-1 text-xs text-slate-500 italic">{item.attention_reason}</p>
          )}
          {item.error_message && (
            <p className="mt-1 text-xs text-red-500">{item.error_message}</p>
          )}
        </div>
        <div className="ml-4 flex items-center gap-2 text-xs text-slate-500">
          <span title="Match">{formatScore(item.match_score)}</span>
          <span title="Priority" className="font-semibold text-slate-700">{formatScore(item.priority_score)}</span>
          <button onClick={onPreflight} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">Preflight</button>
          <button onClick={onSkip} className="rounded border border-rose-300 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50">Skip</button>
        </div>
      </div>
    </div>
  );
}
