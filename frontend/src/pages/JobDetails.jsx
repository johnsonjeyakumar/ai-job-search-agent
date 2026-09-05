import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../api/client.js";
import PageHeader from "../components/PageHeader.jsx";

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
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
    </div>
  );
}