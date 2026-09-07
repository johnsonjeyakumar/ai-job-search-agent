import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api/client.js";
import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

const STATUS_STYLES = {
  PREPARED: "bg-slate-100 text-slate-600",
  VALIDATED: "bg-sky-100 text-sky-700",
  APPROVED: "bg-emerald-100 text-emerald-700",
  REVOKED: "bg-rose-100 text-rose-700",
  ARCHIVED: "bg-slate-100 text-slate-500",
};

const READINESS_STYLES = {
  ready: "bg-emerald-100 text-emerald-700",
  needs_review: "bg-amber-100 text-amber-700",
  blocked: "bg-rose-100 text-rose-700",
};

function statusStyle(status) {
  return STATUS_STYLES[status] || "bg-slate-100 text-slate-600";
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function Applications() {
  const [packages, setPackages] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet("/applications")
      .then(setPackages)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div>
      <div className="mb-4 flex items-start justify-between">
        <PageHeader
          title="Application Packages"
          description="Prepared application packages and their execution status."
        />
        <Link
          to="/applications"
          className="shrink-0 rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          ← Track applications
        </Link>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {packages.length === 0 && !error && (
        <EmptyState
          title="No application packages yet"
          description="Prepare a package from a job match to start the safe application workflow."
        />
      )}

      {packages.length > 0 && (
        <div className="mt-5 overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-semibold">Position</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Readiness</th>
                <th className="px-4 py-3 font-semibold">Quality</th>
                <th className="px-4 py-3 font-semibold">Match / Opportunity</th>
                <th className="px-4 py-3 font-semibold">Updated</th>
                <th className="px-4 py-3 text-right font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {packages.map((pkg) => (
                <tr key={pkg.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link to={`/applications/${pkg.id}/execute`} className="font-medium text-slate-900 hover:underline">
                      {pkg.job_title || "Untitled role"}
                    </Link>
                    <p className="text-xs text-slate-500">{pkg.company || ""}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyle(pkg.status)}`}>
                      {pkg.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${READINESS_STYLES[pkg.readiness] || ""}`}>
                      {pkg.readiness}
                    </span>
                  </td>
                  <td className="px-4 py-3">{pkg.quality_gate}</td>
                  <td className="px-4 py-3">
                    {pkg.match_score == null ? "—" : `${Math.round(pkg.match_score)}`}
                    {pkg.opportunity_score == null ? "" : ` / ${Math.round(pkg.opportunity_score)}`}
                  </td>
                  <td className="px-4 py-3">{formatDate(pkg.updated_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/applications/${pkg.id}/execute`}
                      className={`rounded px-3 py-1.5 text-xs font-medium ${
                        pkg.status === "APPROVED"
                          ? "bg-slate-900 text-white hover:bg-slate-800"
                          : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {pkg.status === "APPROVED" ? "Execute" : "View"}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}