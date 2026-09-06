import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiSend } from "../api/client.js";
import PageHeader from "../components/PageHeader.jsx";

const STATUS_STYLES = {
  EXECUTING: "bg-sky-100 text-sky-700",
  AWAITING_APPROVAL: "bg-amber-100 text-amber-800",
  AWAITING_USER: "bg-orange-100 text-orange-800",
  BLOCKED: "bg-rose-100 text-rose-800",
  SUBMITTED: "bg-blue-100 text-blue-800",
  SUBMISSION_CONFIRMED: "bg-emerald-100 text-emerald-800",
  SUBMISSION_UNKNOWN: "bg-violet-100 text-violet-800",
  EXECUTION_FAILED: "bg-rose-100 text-rose-800",
  CANCELLED: "bg-slate-100 text-slate-600",
};

const MODE_LABELS = {
  HUMAN_ASSISTED: "Human assisted — engine fills safe fields only, you submit",
  PERMITTED_BROWSER: "Permitted browser — safe steps automated, submit gated",
  UNSUPPORTED: "Unsupported — inspection only",
};

const RECOMMENDATION_LABELS = {
  submit: "Ready to submit — review and approve to submit.",
  complete_manually: "Finish the form manually, then confirm the outcome.",
  review_question: "New question detected — a prepared answer is required.",
  review_unknown: "Required fields need manual completion before submission.",
};

function labelize(value) {
  if (!value) return "";
  return value
    .split(/[_ ]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function Section({ title, muted, children }) {
  return (
    <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {muted ? <p className="mt-1 text-xs text-slate-400">{muted}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Detail({ label, children }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-1 text-sm text-slate-700">{children ?? "—"}</dd>
    </div>
  );
}

function StatusBadge({ status }) {
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${STATUS_STYLES[status] || "bg-slate-100 text-slate-600"}`}>
      {labelize(status)}
    </span>
  );
}

function formatDateTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ActionButton({ onClick, disabled, variant = "solid", type = "button", children }) {
  const styles = {
    solid: "bg-slate-900 text-white hover:bg-slate-800",
    confirm: "bg-emerald-700 text-white hover:bg-emerald-800",
    outline: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
    danger: "border border-rose-300 bg-rose-50 text-rose-700 hover:bg-rose-100",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ${styles[variant]}`}
    >
      {children}
    </button>
  );
}

function PreviewPanel({ preview, budget }) {
  const platform = preview?.platform || {};
  const warnings = preview?.warnings || [];
  return (
    <Section title="Execution preview" muted="Pre-flight review before any interaction with the application page.">
      <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <Detail label="Package status">{preview?.package_status}</Detail>
        <Detail label="Quality gate">{preview?.quality_gate}</Detail>
        <Detail label="Platform">{platform?.platform_label || "—"}</Detail>
        <Detail label="Resolved mode">{platform?.mode || "—"}</Detail>
        <Detail label="Job">{preview?.job?.title ? `${preview.job.title} · ${preview.job.company}` : "—"}</Detail>
        <Detail label="Daily budget">
          {budget?.maximum == null
            ? "No limit configured"
            : `${budget?.used_today ?? 0} / ${budget.maximum} used`}
        </Detail>
        <Detail label="Application URL">
          {preview?.job?.url ? (
            <a href={preview.job.url} target="_blank" rel="noopener noreferrer" className="text-slate-700 hover:underline">
              Open
            </a>
          ) : (
            "—"
          )}
        </Detail>
      </dl>
      {warnings.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm text-amber-700">
          {warnings.map((warning, index) => (
            <li key={index}>• {warning}</li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function ApprovalSummary({ payload }) {
  if (!payload) return null;
  const fields = payload.fills || [];
  const requiredUnfilled = payload.required_unfilled || [];
  const newQuestions = payload.new_questions || [];
  return (
    <Section title="Safe execution summary" muted="What the engine did before stopping at the approval boundary.">
      <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <Detail label="Fields detected">{payload.fields_detected}</Detail>
        <Detail label="Fields completed">{payload.fields_completed}</Detail>
        <Detail label="Fields needing review">{payload.fields_needing_review}</Detail>
        <Detail label="Answered questions">{payload.answered_questions}</Detail>
        <Detail label="Auto-submit allowed">{payload.auto_submit_allowed === false ? "No" : "Yes"}</Detail>
        <Detail label="Resume">{payload.resume_name || "—"}</Detail>
        <Detail label="Logged in">{payload.logged_in === false ? "No" : "Yes"}</Detail>
      </dl>

      {payload.recommended_action && (
        <p className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
          {RECOMMENDATION_LABELS[payload.recommended_action] || labelize(payload.recommended_action)}
        </p>
      )}

      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Filled fields</h4>
          <ul className="mt-2 space-y-1 text-sm text-slate-600">
            {fields.map((item, index) => (
              <li key={index}>
                <span className="text-slate-800">{item.label}</span>
                <span className="text-slate-500"> — {item.value || "—"}</span>
              </li>
            ))}
            {fields.length === 0 && <li>No known fields were filled.</li>}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Needs attention</h4>
          <ul className="mt-2 space-y-1 text-sm text-slate-600">
            {requiredUnfilled.map((item, index) => (
              <li key={index}>• {item} — not mapped, never guessed</li>
            ))}
            {newQuestions.map((item, index) => (
              <li key={`q-${index}`}>• {item.label} — new question, no prepared answer</li>
            ))}
            {(requiredUnfilled.length + newQuestions.length) === 0 && (
              <li className="text-slate-500">Nothing requiring manual input.</li>
            )}
          </ul>
        </div>
      </div>

      {payload.warnings?.length > 0 && (
        <ul className="mt-4 space-y-1 text-xs text-amber-700">
          {payload.warnings.map((item, index) => (
            <li key={index}>• {item.message || item}</li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function StepsPanel({ steps }) {
  const items = steps || [];
  return (
    <Section title="Execution steps" muted="Ordered trail of what happened during the run.">
      {items.length === 0 && <p className="text-sm text-slate-500">No steps recorded yet.</p>}
      <ol className="space-y-2">
        {items.map((step) => (
          <li key={step.id} className="flex flex-wrap items-start gap-3 text-sm">
            <span className="mt-0.5 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
              {step.order}
            </span>
            <div className="min-w-0 grow">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-800">{labelize(step.step)}</span>
                {step.status && step.status !== "running" && (
                  <span className="text-xs text-slate-400">({step.status})</span>
                )}
              </div>
              <p className="text-xs text-slate-500">{step.message || "—"}</p>
              {step.url && (
                <a href={step.url} target="_blank" rel="noopener noreferrer" className="text-xs text-slate-600 hover:underline">
                  {step.url}
                </a>
              )}
            </div>
            <span className="text-xs text-slate-400">{formatDateTime(step.completed_at || step.started_at)}</span>
          </li>
        ))}
      </ol>
    </Section>
  );
}

function EvidencePanel({ evidence }) {
  const items = evidence || [];
  return (
    <Section title="Evidence" muted="Recorded verification markers. No secrets are ever stored.">
      {items.length === 0 && <p className="text-sm text-slate-500">No evidence captured.</p>}
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-start justify-between gap-3 text-sm">
            <div>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
                {labelize(item.kind)}
              </span>
              <p className="mt-1 break-all text-xs text-slate-500">{item.value}</p>
            </div>
            {item.url && (
              <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-xs text-slate-600 hover:underline">
                {item.url}
              </a>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

const VERIFICATION_OPTIONS = [
  ["CONFIRMED", "Confirmed — explicit confirmation seen"],
  ["LIKELY", "Likely — strong signal but no explicit confirmation"],
  ["UNKNOWN", "Unknown — could not verify"],
  ["FAILED", "Failed — submission did not go through"],
];

function ConfirmForm({ executionId, packageId, onDone, onError }) {
  const [verification, setVerification] = useState("CONFIRMED");
  const [reference, setReference] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const result = await apiSend(
        "POST",
        `/applications/${packageId}/execution/${executionId}/confirm`,
        { verification, reference, url, note },
      );
      onDone(result);
    } catch (err) {
      onError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Confirm submission outcome</h3>
      <p className="mt-1 text-xs text-slate-400">
        Only CONFIRMED records hard evidence; LIKELY/UNKNOWN keep the run honest without claiming confirmation.
      </p>
      <form onSubmit={submit} className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-medium text-slate-700">
          Verification result
          <select
            value={verification}
            onChange={(event) => setVerification(event.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-800"
          >
            {VERIFICATION_OPTIONS.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium text-slate-700">
          Reference (e.g. application ID)
          <input
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-800"
          />
        </label>
        <label className="text-sm font-medium text-slate-700">
          Confirmation URL
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-800"
          />
        </label>
        <label className="text-sm font-medium text-slate-700">
          Note
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-800"
          />
        </label>
        <div className="sm:col-span-2">
          <ActionButton variant="confirm" type="submit" disabled={saving}>
            {saving ? "Confirming…" : "Record outcome"}
          </ActionButton>
        </div>
      </form>
    </section>
  );
}

export default function ExecutionPage() {
  const { id } = useParams();
  const [state, setState] = useState({ preview: null, execution: null });
  const [budget, setBudget] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    return Promise.all([
      apiGet(`/applications/${id}/execution`),
      apiGet(`/applications/${id}/execution/budget`).catch(() => ({ budget: null })),
    ])
      .then(([executionData, budgetData]) => {
        setState(executionData);
        setBudget(budgetData.budget);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function act(action) {
    setBusy(true);
    setError(null);
    try {
      let result;
      if (action === "execute") {
        result = await apiSend("POST", `/applications/${id}/execute`, { driver: "auto" });
      } else if (action === "approve") {
        result = await apiSend(
          "POST",
          `/applications/${id}/execution/${state.execution.id}/approve`,
          {},
        );
      } else if (action === "cancel") {
        result = await apiSend(
          "POST",
          `/applications/${id}/execution/${state.execution.id}/cancel`,
          {},
        );
      } else if (action === "resume") {
        result = await apiSend(
          "POST",
          `/applications/${id}/execution/${state.execution.id}/resume`,
          { driver: "auto" },
        );
      }
      setState((prev) => ({ ...prev, execution: result.execution }));
      setBusy(false);
      await apiGet(`/applications/${id}/execution/budget`)
        .then((b) => setBudget(b.budget))
        .catch(() => {});
    } catch (err) {
      setError(err.message);
      setBusy(false);
      refresh();
    }
  }

  const execution = state.execution;
  const status = execution?.status;

  return (
    <div>
      <PageHeader
        title="Application execution"
        description="Runs the safe, approved workflow and stops at the human approval boundary."
      />

      <Link to="/applications" className="text-sm font-medium text-slate-700 hover:underline">
        ← Back to applications
      </Link>

      {error && (
        <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      )}

      <PreviewPanel preview={state.preview} budget={budget} />

      {execution && (
        <>
          <Section title="Execution">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge status={status} />
                <span className="text-sm text-slate-500">{execution.platform}</span>
                <span className="text-xs text-slate-400">{MODE_LABELS[execution.execution_mode] || execution.execution_mode}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {status === "AWAITING_APPROVAL" && (
                  <ActionButton onClick={() => act("approve")} disabled={busy}>
                    Approve to submit
                  </ActionButton>
                )}
                {(status === "AWAITING_APPROVAL" || status === "AWAITING_USER") && (
                  <ActionButton variant="danger" onClick={() => act("cancel")} disabled={busy}>
                    Cancel
                  </ActionButton>
                )}
                {(status === "CANCELLED" || status === "EXECUTION_FAILED") && (
                  <ActionButton variant="outline" onClick={() => act("resume")} disabled={busy}>
                    Resume
                  </ActionButton>
                )}
              </div>
            </div>

            <dl className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              <Detail label="Started">{formatDateTime(execution.started_at)}</Detail>
              <Detail label="Completed">{formatDateTime(execution.completed_at)}</Detail>
              <Detail label="Submission status">{execution.submission_status || "—"}</Detail>
              <Detail label="Reference">{execution.confirmation_reference || "—"}</Detail>
              <Detail label="Confirmation URL">
                {execution.confirmation_url ? (
                  <a href={execution.confirmation_url} target="_blank" rel="noopener noreferrer" className="text-slate-700 hover:underline">
                    Open
                  </a>
                ) : (
                  "—"
                )}
              </Detail>
            </dl>
          </Section>

          <ApprovalSummary payload={execution.approval_payload} />

          {status === "AWAITING_USER" && (
            <ConfirmForm
              executionId={execution.id}
              packageId={id}
              onDone={(result) => {
                setState((prev) => ({ ...prev, execution: result.execution }));
                setError(null);
              }}
              onError={(message) => setError(message)}
            />
          )}

          <StepsPanel steps={execution.steps} />
          <EvidencePanel evidence={execution.evidence} />
        </>
      )}

      {!execution && (
        <Section title="Run">
          <p className="text-sm text-slate-500">
            No execution yet for this package. Run the safe steps to detect the platform, fill known fields, and stop at
            the approval boundary — nothing is submitted without your approval.
          </p>
          <div className="mt-4">
            <ActionButton onClick={() => act("execute")} disabled={busy}>
              {busy ? "Starting…" : "Run safe steps"}
            </ActionButton>
          </div>
        </Section>
      )}
    </div>
  );
}