import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api/client.js";
import PageHeader from "../components/PageHeader.jsx";
import EmptyState from "../components/EmptyState.jsx";

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function Companies() {
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiGet("/companies")
      .then((body) => setCompanies(body.items || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHeader
        title="Companies"
        description="Employers observed in your collected jobs. Aggregates are based on your data only."
      />

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-6">
        {loading ? (
          <p className="text-sm text-slate-500">Loading companies…</p>
        ) : companies.length === 0 ? (
          <EmptyState
            title="No companies observed"
            description="Companies appear once you collect jobs mentioning them."
          />
        ) : (
          <>
            <p className="mb-3 text-xs text-slate-500">
              {companies.length} compan{companies.length === 1 ? "y" : "ies"}
            </p>
            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                    <th className="px-5 py-3 font-medium">Company</th>
                    <th className="px-5 py-3 font-medium">Domain</th>
                    <th className="px-5 py-3 font-medium">Industry</th>
                    <th className="px-5 py-3 font-medium">Jobs</th>
                    <th className="px-5 py-3 font-medium">Roles</th>
                    <th className="px-5 py-3 font-medium">Sources</th>
                    <th className="px-5 py-3 font-medium">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {companies.map((company) => (
                    <tr key={company.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="px-5 py-3 font-medium text-slate-800">
                        <Link to={`/jobs?company=${encodeURIComponent(company.display_name || company.normalized_name)}`} className="hover:underline">
                          {company.display_name || company.normalized_name}
                        </Link>
                      </td>
                      <td className="px-5 py-3 text-slate-600">{company.domain || "—"}</td>
                      <td className="px-5 py-3 text-slate-600">{company.industry || "—"}</td>
                      <td className="px-5 py-3 text-slate-700">{company.active_job_count}</td>
                      <td className="px-5 py-3 text-slate-700">{company.distinct_role_count}</td>
                      <td className="px-5 py-3 text-slate-700">{company.source_count}</td>
                      <td className="px-5 py-3 text-slate-600">{formatDate(company.last_seen_job_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}