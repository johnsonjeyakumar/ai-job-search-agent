import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiSend } from "../api/client.js";
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

const RESPONSE_CATEGORIES = [
  "NO_RESPONSE",
  "RECRUITER_CONTACT",
  "ASSESSMENT",
  "INTERVIEW",
  "REJECTED",
  "OFFER",
  "OTHER",
];

const INTERVIEW_TYPES = [
  "TELEPHONE",
  "VIDEO",
  "TECHNICAL",
  "BEHAVIORAL",
  "CODING",
  "HR",
  "PANEL",
  "OTHER",
];

const INTERVIEW_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW", "OTHER"];

const OFFER_STATUSES = ["RECEIVED", "ACCEPTED", "DECLINED", "EXPIRED"];

const tss = (v) => (v ? new Date(v).toLocaleString() : "—");

function badgeFor(statusName, map) {
  return map[statusName] || "bg-slate-100 text-slate-600";
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function DetailRow({ label, children }) {
  return (
    <div className="flex items-baseline justify-between py-1 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-900">{children}</span>
    </div>
  );
}

export default function ApplicationTracking() {
  const { id } = useParams();
  const [statusMeta, setStatusMeta] = useState({ statuses: [], transitions: {} });
  const [app, setApp] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const reload = useCallback(() => {
    return apiGet(`/tracking/applications/${id}`)
      .then((body) => {
        setApp(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, [id]);

  useEffect(() => {
    apiGet("/tracking/statuses").then((body) => setStatusMeta(body));
    reload();
  }, [reload]);

  const [statusForm, setStatusForm] = useState({ target_status: "", override: false, notes: "" });
  const [noteText, setNoteText] = useState("");
  const [responseForm, setResponseForm] = useState({
    category: "RECRUITER_CONTACT",
    received_at: today(),
    notes: "",
  });
  const [interviewForm, setInterviewForm] = useState({
    interview_date: today(),
    interview_type: "VIDEO",
    round_number: 1,
    status: "SCHEDULED",
    notes: "",
  });
  const [offerForm, setOfferForm] = useState({ offer_date: today(), status: "RECEIVED", notes: "" });
  const [followUpForm, setFollowUpForm] = useState({ scheduled_date: "" });
  const [busy, setBusy] = useState(false);

  const run = (promise, success) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    promise
      .then(() => {
        setNotice(success);
        return reload();
      })
      .then(() => setBusy(false))
      .catch((err) => {
        setError(err.message);
        setBusy(false);
      });
  };

  if (!app && !error) {
    return <p className="py-10 text-sm text-slate-500">Loading application…</p>;
  }

  if (error && !app) {
    return <p className="py-10 text-sm text-red-600">{error}</p>;
  }

  const targetOptions =
    (statusMeta.transitions && statusMeta.transitions[app.status]) || [];
  const allStatuses = statusMeta.statuses || [];
  const displayOptions = statusForm.override ? allStatuses : targetOptions;
  const followUps = app.follow_ups || [];

  return (
    <div>
      <Link to="/applications" className="text-sm text-slate-500 hover:underline">
        ← Back to applications
      </Link>

      <PageHeader title={app.job_title} description={app.company} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Overview
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeFor(app.status, STATUS_BADGE)}`}>
                {app.status.replace(/_/g, " ")}
              </span>
              {app.legacy_status && (
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500">
                  legacy: {app.legacy_status}
                </span>
              )}
              {app.follow_up_state ? (
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeFor(app.follow_up_state, FOLLOW_UP_BADGE)}`}>
                  follow-up {app.follow_up_state.toLowerCase()}
                </span>
              ) : null}
            </div>
            <dl className="mt-4 max-w-md">
              <DetailRow label="Location">{app.location || "—"}</DetailRow>
              <DetailRow label="Source">{app.source || "—"}</DetailRow>
              <DetailRow label="Applied">{app.applied_date || "—"}</DetailRow>
              <DetailRow label="Waiting">
                {app.days_waiting == null ? "—" : `${app.days_waiting} ${app.days_waiting === 1 ? "day" : "days"}`}
              </DetailRow>
              <DetailRow label="Resume">
                {app.resume_name ? (
                  <>
                    {app.resume_name}
                    {app.resume_version ? ` v${app.resume_version}` : ""}
                  </>
                ) : (
                  "—"
                )}
              </DetailRow>
              <DetailRow label="Created">{tss(app.created_at)}</DetailRow>
            </dl>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Timeline
            </h3>
            {app.timeline && app.timeline.length > 0 ? (
              <ol className="space-y-3 border-l border-slate-200 pl-4">
                {app.timeline.map((ev) => (
                  <li key={ev.id} className="relative">
                    <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-slate-400" />
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-semibold text-slate-800">
                        {ev.event_type.replace(/_/g, " ")}
                      </span>
                      {ev.new_status && (
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badgeFor(ev.new_status, STATUS_BADGE)}`}>
                          {ev.new_status.replace(/_/g, " ")}
                        </span>
                      )}
                      <span className="text-xs text-slate-400">{tss(ev.event_timestamp)}</span>
                    </div>
                    {(ev.previous_status || ev.source) && (
                      <p className="mt-0.5 text-xs text-slate-500">
                        {ev.previous_status
                          ? `from ${ev.previous_status.replace(/_/g, " ").toLowerCase()}`
                          : ""}
                        {ev.source ? ` · ${ev.source.toLowerCase()}` : ""}
                      </p>
                    )}
                    {ev.notes && <p className="mt-0.5 text-sm text-slate-600">{ev.notes}</p>}
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState title="No events yet" description="The timeline fills in as the application moves." />
            )}
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Responses
            </h3>
            <form
              className="mb-4 grid grid-cols-1 gap-3 rounded-md bg-slate-50 p-3 md:grid-cols-3"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  apiSend("POST", `/tracking/applications/${id}/responses`, responseForm),
                  "Response recorded."
                );
              }}
            >
              <select
                value={responseForm.category}
                onChange={(e) => setResponseForm({ ...responseForm, category: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              >
                {RESPONSE_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <input
                type="date"
                value={responseForm.received_at}
                onChange={(e) => setResponseForm({ ...responseForm, received_at: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              />
              <input
                placeholder="Notes (optional)"
                value={responseForm.notes}
                onChange={(e) => setResponseForm({ ...responseForm, notes: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 md:col-span-3 md:justify-self-start"
              >
                Record response
              </button>
            </form>
            {app.responses && app.responses.length > 0 ? (
              <ul className="divide-y divide-slate-100">
                {app.responses.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                    <span className="font-medium text-slate-800">{r.category.replace(/_/g, " ")}</span>
                    <span className="text-slate-500">{r.received_at || "—"}</span>
                    {r.notes && <span className="text-slate-600">{r.notes}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">No responses recorded yet.</p>
            )}
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Interviews
            </h3>
            <form
              className="mb-4 grid grid-cols-1 gap-3 rounded-md bg-slate-50 p-3 md:grid-cols-4"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  apiSend("POST", `/tracking/applications/${id}/interviews`, interviewForm),
                  "Interview recorded."
                );
              }}
            >
              <input
                type="date"
                value={interviewForm.interview_date}
                onChange={(e) => setInterviewForm({ ...interviewForm, interview_date: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              />
              <select
                value={interviewForm.interview_type}
                onChange={(e) => setInterviewForm({ ...interviewForm, interview_type: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              >
                {INTERVIEW_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <select
                value={interviewForm.status}
                onChange={(e) => setInterviewForm({ ...interviewForm, status: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              >
                {INTERVIEW_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min="1"
                value={interviewForm.round_number}
                onChange={(e) => setInterviewForm({ ...interviewForm, round_number: Number(e.target.value) })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              />
              <input
                placeholder="Notes (optional)"
                value={interviewForm.notes}
                onChange={(e) => setInterviewForm({ ...interviewForm, notes: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm md:col-span-3"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                Record interview
              </button>
            </form>
            {app.interviews && app.interviews.length > 0 ? (
              <ul className="divide-y divide-slate-100">
                {app.interviews.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                    <span className="font-medium text-slate-800">
                      Round {r.round ?? 1} · {r.interview_type.replace(/_/g, " ")}
                    </span>
                    <span className="text-slate-500">{r.interview_date || "—"}</span>
                    <span className="text-slate-500">({r.status.replace(/_/g, " ").toLowerCase()})</span>
                    {r.notes && <span className="text-slate-600">{r.notes}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">No interviews recorded yet.</p>
            )}
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Offers
            </h3>
            <form
              className="mb-4 grid grid-cols-1 gap-3 rounded-md bg-slate-50 p-3 md:grid-cols-4"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  apiSend("POST", `/tracking/applications/${id}/offers`, offerForm),
                  "Offer recorded."
                );
              }}
            >
              <input
                type="date"
                value={offerForm.offer_date}
                onChange={(e) => setOfferForm({ ...offerForm, offer_date: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              />
              <select
                value={offerForm.status}
                onChange={(e) => setOfferForm({ ...offerForm, status: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              >
                {OFFER_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
              <input
                placeholder="Notes (optional)"
                value={offerForm.notes}
                onChange={(e) => setOfferForm({ ...offerForm, notes: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm md:col-span-2"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 md:col-span-4 md:justify-self-start"
              >
                Record offer
              </button>
            </form>
            {app.offers && app.offers.length > 0 ? (
              <ul className="divide-y divide-slate-100">
                {app.offers.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                    <span className="font-medium text-slate-800">{r.offer_date || "—"}</span>
                    <span className="text-slate-500">({r.status.replace(/_/g, " ").toLowerCase()})</span>
                    {r.notes && <span className="text-slate-600">{r.notes}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">No offers recorded yet.</p>
            )}
          </section>
        </div>

        <div className="space-y-6">
          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Update status
            </h3>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  apiSend("PATCH", `/tracking/applications/${id}/status`, {
                    target_status: statusForm.target_status,
                    override: statusForm.override,
                    notes: statusForm.notes || null,
                  }),
                  "Status updated."
                ).then(() =>
                  setStatusForm({ target_status: "", override: false, notes: "" })
                );
              }}
            >
              <select
                value={statusForm.target_status}
                onChange={(e) => setStatusForm({ ...statusForm, target_status: e.target.value })}
                className="block w-full rounded border border-slate-300 bg-white px-2 py-2 text-sm"
              >
                <option value="">Select target status…</option>
                {displayOptions.map((s) => (
                  <option key={s} value={s}>
                    {statusForm.override ? s.replace(/_/g, " ") : `${s.replace(/_/g, " ")} (legal)`}
                  </option>
                ))}
              </select>
              {displayOptions.length === 0 && !statusForm.override && (
                <p className="text-xs text-slate-500">
                  No legal moves from {app.status.replace(/_/g, " ")}. Enable override to force a
                  correction.
                </p>
              )}
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={statusForm.override}
                  onChange={(e) => setStatusForm({ ...statusForm, override: e.target.checked })}
                />
                Override (records STATUS_CORRECTED)
              </label>
              <textarea
                rows="3"
                placeholder="Notes (optional)"
                value={statusForm.notes}
                onChange={(e) => setStatusForm({ ...statusForm, notes: e.target.value })}
                className="block w-full rounded border border-slate-300 bg-white px-2 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busy || !statusForm.target_status}
                className="w-full rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                Apply status change
              </button>
            </form>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Follow-ups
            </h3>
            <form
              className="mb-3 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  apiSend("POST", `/tracking/applications/${id}/follow-ups`, {
                    scheduled_date: followUpForm.scheduled_date || null,
                  }),
                  "Follow-up scheduled."
                ).then(() => setFollowUpForm({ scheduled_date: "" }));
              }}
            >
              <input
                type="date"
                value={followUpForm.scheduled_date}
                onChange={(e) => setFollowUpForm({ scheduled_date: e.target.value })}
                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                Schedule
              </button>
            </form>
            {followUps.length > 0 ? (
              <ul className="space-y-2">
                {followUps.map((fu) => (
                  <li key={fu.id} className="rounded-md border border-slate-200 p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badgeFor(fu.state, FOLLOW_UP_BADGE)}`}>
                        {fu.state}
                      </span>
                      <span className="text-slate-600">{fu.scheduled_date || "no date"}</span>
                      {fu.status && <span className="text-xs text-slate-400">({fu.status})</span>}
                    </div>
                    {fu.notes && <p className="mt-1 text-slate-600">{fu.notes}</p>}
                    {fu.state === "PENDING" || fu.state === "DUE" ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <button
                          onClick={() =>
                            run(
                              apiSend("POST", `/tracking/follow-ups/${fu.id}/complete`, null),
                              "Follow-up completed."
                            )
                          }
                          disabled={busy}
                          className="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                        >
                          Complete
                        </button>
                        <button
                          onClick={() => {
                            const next = window.prompt("New scheduled date (YYYY-MM-DD):", fu.scheduled_date || today());
                            if (!next) return;
                            run(
                              apiSend("POST", `/tracking/follow-ups/${fu.id}/reschedule`, {
                                scheduled_date: next,
                                notes: null,
                              }),
                              "Follow-up rescheduled."
                            );
                          }}
                          disabled={busy}
                          className="rounded bg-amber-500 px-2 py-1 text-xs font-medium text-white hover:bg-amber-400 disabled:opacity-50"
                        >
                          Reschedule
                        </button>
                        <button
                          onClick={() =>
                            run(
                              apiSend("POST", `/tracking/follow-ups/${fu.id}/cancel`, null),
                              "Follow-up cancelled."
                            )
                          }
                          disabled={busy}
                          className="rounded bg-rose-500 px-2 py-1 text-xs font-medium text-white hover:bg-rose-400 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">No follow-ups scheduled.</p>
            )}
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Add note
            </h3>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  apiSend("POST", `/tracking/applications/${id}/notes`, { notes: noteText }),
                  "Note added."
                ).then(() => setNoteText(""));
              }}
            >
              <textarea
                rows="3"
                placeholder="Note…"
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                className="block w-full rounded border border-slate-300 bg-white px-2 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busy || !noteText.trim()}
                className="w-full rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                Save note
              </button>
            </form>
            {app.notes && (
              <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-600">
                {app.notes}
              </p>
            )}
          </section>
        </div>
      </div>

      {notice && <p className="mt-4 text-sm text-emerald-700">{notice}</p>}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
    </div>
  );
}