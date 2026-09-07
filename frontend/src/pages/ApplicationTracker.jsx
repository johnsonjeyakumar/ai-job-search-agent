import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiGet } from "../api/client.js";
import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

const STATUS_BADGE = {
  DISCOVERED: "bg-slate-100 text-slate-600",
  SHORTLISTED: "bg-indigo-100 text-indigo-700",
  PREPARING: "bg-amber-100 text-amber-700",
  READY_FOR_REVIEW: "bg-amber-100 text-amber-800",
  APPROVED: "bg-emerald-100 text-emerald-700",
  EXECUTION_READY: "bg-emerald-100 text-emerald-800",
  EXECUTING: "bg-sky-100 text-sky-700",
  SUBMITTED: "bg-sky-100 text-sky-800",
  SUBMISSION_CONFIRMED: "bg-teal-100 text-teal-700",
  RESPONSE_RECEIVED: "bg-violet-100 text-violet-700",
  INTERVIEW: "bg-purple-100 text-purple-700",
  OFFER: "bg-emerald-100 text-emerald-700",
  REJECTED: "bg-rose-100 text-rose-700",
  WITHDRAWN: "bg-slate-100 text-slate-500",
  EXPIRED: "bg-slate-100 text-slate-500",
  CANCELLED: "bg-rose-50 text-rose-500",
};

const FOLLOW_UP_BADGE = {
  DUE: "bg-rose-100 text-rose-700",
  PENDING: "bg-amber-100 text-amber-700",
  COMPLETED: "bg-emerald-100 text-emerald-700",
  CANCELLED: "bg-slate-100 text-slate-500",
};

const SORT_OPTIONS = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "waiting", label: "Longest waiting" },
  { value: "follow_up_due", label: "Follow-up due" },
];

function badgeFor(statusName, map) {
  return map[statusName] || "bg-slate-100 text-slate-600";
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function ApplicationTracker() {
  const [searchParams] = useSearchParams();
  const [statusOptions, setStatusOptions] = useState([]);
  const [filters, setFilters] = useState({
    status: searchParams.get("status") || "",
    follow_up: searchParams.get("follow_up") || "",
    sort: searchParams.get("sort") || "newest",
    company: searchParams.get("company") || "",
    role: searchParams.get("role") || "",
  });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiGet("/tracking/statuses")
      .then((body) => setStatusOptions(body.statuses || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.follow_up) params.set("follow_up", filters.follow_up);
    params.set("sort", filters.sort);
    if (filters.company.trim()) params.set("company", filters.company.trim());
    if (filters.role.trim()) params.set("role", filters.role.trim());
    const query = params.toString();
    setLoading(true);
    apiGet(`/tracking/applications${query ? `?${query}` : ""}`)
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [filters]);

  const items = data?.items || [];
  const statusCounts = data?.status_counts || {};

  return (
    <div>
      <PageHeader
        title="Applications"
        description="Track every application across its lifecycle with an immutable timeline, follow-ups, and funnels."
      />

      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <label className="block text-xs font-medium text-slate-600">
            Status
            <select
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="">All</option>
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs font-medium text-slate-600">
            Follow-up
            <select
              value={filters.follow_up}
              onChange={(e) => setFilters({ ...filters, follow_up: e.target.value })}
              className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="">All</option>
              <option value="DUE">Due / overdue</option>
              <option value="PENDING">Pending</option>
              <option value="COMPLETED">Completed</option>
              <option value="NONE">No follow-up</option>
            </select>
          </label>
          <label className="block text-xs font-medium text-slate-600">
            Sort
            <select
              value={filters.sort}
              onChange={(e) => setFilters({ ...filters, sort: e.target.value })}
              className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs font-medium text-slate-600">
            Company
            <input
              value={filters.company}
              onChange={(e) => setFilters({ ...filters, company: e.target.value })}
              placeholder="Filter by company"
              className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-xs font-medium text-slate-600">
            Role
            <input
              value={filters.role}
              onChange={(e) => setFilters({ ...filters, role: e.target.value })}
              placeholder="Filter by title"
              className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
            />
          </label>
        </div>
        <Link
          to="/applications/packages"
          className="rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          View packages →
        </Link>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {!loading && items.length === 0 && !error && (
        <EmptyState
          title="No tracked applications"
          description="Discovered jobs become tracked applications as soon as they move through the pipeline."
        />
      )}

      {items.length > 0 && (
        <div className="mt-5 overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-semibold">Position</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Location</th>
                <th className="px-4 py-3 font-semibold">Applied</th>
                <th className="px-4 py-3 font-semibold">Waiting</th>
                <th className="px-4 py-3 font-semibold">Follow-up</th>
                <th className="px-4 py-3 font-semibold">Last event</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((row) => (
                <tr key={row.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link
                      to={`/applications/track/${row.id}`}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {row.job_title || "Untitled role"}
                    </Link>
                    <p className="text-xs text-slate-500">
                      {row.company || ""}
                      {row.source ? ` · ${row.source}` : ""}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badgeFor(
                        row.status,
                        STATUS_BADGE
                      )}`}
                    >
                      {row.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{row.location || "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{formatDate(row.applied_date)}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {row.days_waiting == null ? "—" : `${row.days_waiting}d`}
                  </td>
                  <td className="px-4 py-3">
                    {row.follow_up_state ? (
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badgeFor(
                            row.follow_up_state,
                            FOLLOW_UP_BADGE
                          )}`}
                        >
                          {row.follow_up_state}
                        </span>
                        <span className="text-xs text-slate-400">{formatDate(row.follow_up_date)}</span>
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{row.last_event || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <p className="mt-3 text-xs text-slate-400">
          {data.total} tracked application{data.total === 1 ? "" : "s"} in view{loading ? " · loading…" : ""}
          {" · "}
          {Object.entries(statusCounts)
            .filter(([, count]) => count > 0)
            .map(([label, count]) => `${label.toLowerCase()} ${count}`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}