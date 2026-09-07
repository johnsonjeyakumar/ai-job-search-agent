import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiSend } from "../api/client.js";
import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

const INT_TYPES = ["TELEPHONE","VIDEO","TECHNICAL","BEHAVIORAL","CODING","HR","PANEL","FINAL","OTHER"];
const INT_STATUSES = ["SCHEDULED","IN_PROGRESS","COMPLETED","CANCELLED","NO_SHOW","RESCHEDULED"];
const OUTCOMES = ["PENDING","PASSED","REJECTED","NEXT_ROUND","OFFER","WITHDRAWN","NO_DECISION"];
const CATEGORIES = ["TECHNICAL","BEHAVIORAL","HR","PROJECT","RESUME_BASED","ROLE_SPECIFIC"];
const PREP_STATUSES = ["TODO","IN_PROGRESS","COMPLETED"];

const BADGE = {
  SCHEDULED:"bg-sky-100 text-sky-700",IN_PROGRESS:"bg-amber-100 text-amber-700",
  COMPLETED:"bg-emerald-100 text-emerald-700",CANCELLED:"bg-slate-100 text-slate-500",
  NO_SHOW:"bg-rose-100 text-rose-700",RESCHEDULED:"bg-violet-100 text-violet-700",
  PENDING:"bg-slate-100 text-slate-600",PASSED:"bg-emerald-100 text-emerald-700",
  REJECTED:"bg-rose-100 text-rose-700",NEXT_ROUND:"bg-sky-100 text-sky-700",
  OFFER:"bg-emerald-100 text-emerald-700",WITHDRAWN:"bg-slate-100 text-slate-500",
  NO_DECISION:"bg-amber-100 text-amber-700",HIGH:"bg-rose-100 text-rose-700",
  MEDIUM:"bg-amber-100 text-amber-700",LOW:"bg-slate-100 text-slate-600",
  EASY:"bg-emerald-100 text-emerald-700",HARD:"bg-rose-100 text-rose-700",
  TODO:"bg-slate-100 text-slate-600",
};
const badge = (v) => BADGE[v] || "bg-slate-100 text-slate-600";

const ts = (v) => v ? new Date(v).toLocaleString() : "\u2014";
const sectionClass = "bg-white rounded-xl border border-slate-200 p-5 space-y-4";

export default function InterviewWorkspace() {
  const { id: appId } = useParams();
  const [tab, setTab] = useState("details");
  const [interviews, setInterviews] = useState([]);
  const [questions, setQuestions] = useState([]);
  const [prepItems, setPrepItems] = useState([]);
  const [mockSessions, setMockSessions] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedInterview, setSelectedInterview] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [ints, qs, prep, mocks] = await Promise.all([
        apiGet(`/interviews/applications/${appId}/interviews`),
        apiGet(`/interviews/applications/${appId}/questions`),
        apiGet(`/interviews/applications/${appId}/prep-items`),
        apiGet(`/interviews/applications/${appId}/mock-sessions`),
      ]);
      setInterviews(ints.items || []);
      setSummary(ints.summary || null);
      setQuestions(qs.items || []);
      setPrepItems(prep.items || []);
      setMockSessions(mocks.items || []);
      if (ints.items?.length > 0 && !selectedInterview) {
        setSelectedInterview(ints.items[0]);
      }
    } catch (e) { setError(e.message); }
    setLoading(false);
  }, [appId, selectedInterview]);

  useEffect(() => { load(); }, [appId]);

  if (loading) return <div className="p-8 text-center text-slate-400">Loading...</div>;
  if (error) return <div className="p-8 text-center text-rose-500">{error}</div>;

  const tabs = [
    {key:"details",label:"Details"},{key:"questions",label:"Questions"},
    {key:"mock",label:"Mock Interview"},{key:"notes",label:"Notes & Feedback"},
    {key:"prep",label:"Prep Plan"},
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Interview Workspace">
        <Link to={`/applications/track/${appId}`} className="text-sm text-slate-500 hover:text-slate-700">&larr; Back to Tracking</Link>
      </PageHeader>

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {["total","scheduled","completed","cancelled"].map(k => (
            <div key={k} className="bg-white rounded-lg border p-3 text-center">
              <div className="text-2xl font-bold">{summary[k] || 0}</div>
              <div className="text-xs text-slate-500 capitalize">{k}</div>
            </div>
          ))}
          <div className="bg-white rounded-lg border p-3 text-center">
            <div className="text-2xl font-bold">{interviews.filter(i=>i.outcome==="NEXT_ROUND").length}</div>
            <div className="text-xs text-slate-500">Next Round</div>
          </div>
        </div>
      )}

      <div className="flex gap-1 border-b border-slate-200">
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${tab===t.key ? "border-sky-600 text-sky-600" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "details" && <DetailsTab interviews={interviews} appId={appId} reload={load} setSelectedInterview={setSelectedInterview} />}
      {tab === "questions" && <QuestionsTab questions={questions} appId={appId} reload={load} />}
      {tab === "mock" && <MockTab sessions={mockSessions} appId={appId} reload={load} />}
      {tab === "notes" && <NotesTab interviews={interviews} />}
      {tab === "prep" && <PrepTab items={prepItems} reload={load} />}
    </div>
  );
}

function DetailsTab({ interviews, appId, reload, setSelectedInterview }) {
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({interview_type:"TECHNICAL",round_number:1,interviewer_name:"",notes:"",scheduled_at:""});
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [outForm, setOutForm] = useState({outcome:"PENDING",notes:""});

  const createInterview = async () => {
    setCreating(true);
    try {
      await apiSend("POST", `/interviews/applications/${appId}/interviews`, {
        ...form,
        scheduled_at: form.scheduled_at || null,
        round_number: Number(form.round_number),
      });
      setShowCreate(false);
      setForm({interview_type:"TECHNICAL",round_number:1,interviewer_name:"",notes:"",scheduled_at:""});
      reload();
    } catch (e) { alert(e.message); }
    setCreating(false);
  };

  const setOutcome = async (intId) => {
    try {
      await apiSend("POST", `/interviews/${intId}/outcome`, outForm);
      setEditing(null);
      reload();
    } catch (e) { alert(e.message); }
  };

  const changeStatus = async (intId, status) => {
    try {
      await apiSend("POST", `/interviews/${intId}/${status}`);
      reload();
    } catch (e) { alert(e.message); }
  };

  return (
    <div className={sectionClass}>
      <div className="flex justify-between items-center">
        <h3 className="font-semibold text-slate-800">Interviews ({interviews.length})</h3>
        <button onClick={() => setShowCreate(!showCreate)} className="px-3 py-1.5 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700">
          {showCreate ? "Cancel" : "+ New Interview"}
        </button>
      </div>
      {showCreate && (
        <div className="bg-slate-50 rounded-lg p-4 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <select value={form.interview_type} onChange={e => setForm({...form, interview_type:e.target.value})}
              className="border rounded-lg px-3 py-2 text-sm">
              {INT_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
            <input type="number" min="1" value={form.round_number} onChange={e => setForm({...form, round_number:e.target.value})}
              className="border rounded-lg px-3 py-2 text-sm" placeholder="Round" />
            <input type="text" value={form.interviewer_name} onChange={e => setForm({...form, interviewer_name:e.target.value})}
              className="border rounded-lg px-3 py-2 text-sm" placeholder="Interviewer name" />
            <input type="datetime-local" value={form.scheduled_at} onChange={e => setForm({...form, scheduled_at:e.target.value})}
              className="border rounded-lg px-3 py-2 text-sm" />
            <input type="text" value={form.notes} onChange={e => setForm({...form, notes:e.target.value})}
              className="border rounded-lg px-3 py-2 text-sm col-span-2" placeholder="Notes" />
          </div>
          <button onClick={createInterview} disabled={creating}
            className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 disabled:opacity-50">
            {creating ? "Creating..." : "Create Interview"}
          </button>
        </div>
      )}
      <div className="space-y-2">
        {interviews.map(i => (
          <div key={i.id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm">Round {i.round}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${badge(i.status)}`}>{i.status}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${badge(i.outcome)}`}>{i.outcome}</span>
                <span className="text-xs text-slate-500">{i.interview_type}</span>
              </div>
              <div className="text-xs text-slate-500 mt-1">
                {i.interviewer_name && <span>{i.interviewer_name}{i.interviewer_role ? ` (${i.interviewer_role})` : ""} &middot; </span>}
                {i.scheduled_at ? ts(i.scheduled_at) : "No date"}
                {i.location && ` \u00b7 ${i.location}`}
              </div>
            </div>
            <div className="flex gap-1">
              {i.status === "SCHEDULED" && (
                <>
                  <button onClick={() => changeStatus(i.id, "complete")} className="text-xs px-2 py-1 bg-emerald-100 text-emerald-700 rounded hover:bg-emerald-200">Complete</button>
                  <button onClick={() => changeStatus(i.id, "cancel")} className="text-xs px-2 py-1 bg-rose-100 text-rose-700 rounded hover:bg-rose-200">Cancel</button>
                </>
              )}
              <button onClick={() => setEditing(editing===i.id ? null : i.id)} className="text-xs px-2 py-1 bg-slate-100 text-slate-700 rounded hover:bg-slate-200">Outcome</button>
            </div>
            {editing === i.id && (
              <div className="flex gap-2 items-center">
                <select value={outForm.outcome} onChange={e => setOutForm({...outForm, outcome:e.target.value})}
                  className="border rounded px-2 py-1 text-xs">
                  {OUTCOMES.map(o => <option key={o}>{o}</option>)}
                </select>
                <input value={outForm.notes} onChange={e => setOutForm({...outForm, notes:e.target.value})}
                  className="border rounded px-2 py-1 text-xs" placeholder="Notes" />
                <button onClick={() => setOutcome(i.id)} className="text-xs px-2 py-1 bg-sky-600 text-white rounded">Save</button>
              </div>
            )}
          </div>
        ))}
        {interviews.length === 0 && <EmptyState message="No interviews yet." />}
      </div>
    </div>
  );
}

function QuestionsTab({ questions, appId, reload }) {
  const [generating, setGenerating] = useState(false);
  const [count, setCount] = useState(10);
  const [catFilter, setCatFilter] = useState(null);
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(null);

  const generate = async () => {
    setGenerating(true);
    try {
      await apiSend("POST", `/interviews/applications/${appId}/questions/generate`, { count });
      reload();
    } catch (e) { alert(e.message); }
    setGenerating(false);
  };

  const saveAnswer = async (qId) => {
    setSubmitting(qId);
    try {
      await apiSend("POST", `/interviews/questions/${qId}/answer`, { draft_answer: answers[qId] || "" });
      const fb = await apiSend("POST", `/interviews/questions/${qId}/feedback`);
      reload();
    } catch (e) { alert(e.message); }
    setSubmitting(null);
  };

  const filtered = catFilter ? questions.filter(q => q.category === catFilter) : questions;

  return (
    <div className={sectionClass}>
      <div className="flex justify-between items-center">
        <h3 className="font-semibold text-slate-800">Questions ({filtered.length})</h3>
        <div className="flex gap-2">
          <select value={count} onChange={e => setCount(Number(e.target.value))} className="border rounded px-2 py-1 text-sm">
            {[5,10,15,20].map(n => <option key={n}>{n}</option>)}
          </select>
          <button onClick={generate} disabled={generating}
            className="px-3 py-1.5 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700 disabled:opacity-50">
            {generating ? "Generating..." : "Generate Questions"}
          </button>
        </div>
      </div>
      <div className="flex gap-1 flex-wrap">
        <button onClick={() => setCatFilter(null)} className={`text-xs px-2 py-1 rounded-full ${!catFilter ? "bg-sky-600 text-white" : "bg-slate-100 text-slate-600"}`}>All</button>
        {CATEGORIES.map(c => (
          <button key={c} onClick={() => setCatFilter(c===catFilter ? null : c)}
            className={`text-xs px-2 py-1 rounded-full ${catFilter===c ? "bg-sky-600 text-white" : "bg-slate-100 text-slate-600"}`}>{c}</button>
        ))}
      </div>
      <div className="space-y-3">
        {filtered.map((q, idx) => (
          <div key={q.id} className="bg-slate-50 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full ${badge(q.priority)}`}>{q.priority}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${badge(q.category)}`}>{q.category}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${badge(q.difficulty)}`}>{q.difficulty}</span>
              <span className="text-xs text-slate-400">{q.source}</span>
            </div>
            <p className="text-sm font-medium text-slate-800">{q.question}</p>
            {q.rationale && <p className="text-xs text-slate-500 italic">Rationale: {q.rationale}</p>}
            {q.source_context && <p className="text-xs text-slate-400">Source: {q.source_context}</p>}
            <div className="flex gap-2">
              <textarea value={answers[q.id] || q.draft_answer || ""} onChange={e => setAnswers({...answers, [q.id]:e.target.value})}
                className="flex-1 border rounded-lg px-3 py-2 text-sm" rows={2} placeholder="Draft your answer..." />
              <button onClick={() => saveAnswer(q.id)} disabled={submitting===q.id}
                className="px-3 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 disabled:opacity-50 self-end">
                {submitting===q.id ? "Saving..." : "Save"}
              </button>
            </div>
            {q.answer_feedback?.label && (
              <div className={`text-xs px-2 py-1 rounded ${badge(q.answer_feedback.label)}`}>
                {q.answer_feedback.label} ({q.answer_feedback.word_count} words)
              </div>
            )}
          </div>
        ))}
        {filtered.length === 0 && <EmptyState message="No questions yet. Generate some to get started." />}
      </div>
    </div>
  );
}

function MockTab({ sessions, appId, reload }) {
  const [creating, setCreating] = useState(false);
  const [activeSession, setActiveSession] = useState(null);
  const [config, setConfig] = useState({question_count:5,technical_pct:60,behavioral_pct:40});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState(null);

  const createSession = async () => {
    setCreating(true);
    try {
      const resp = await apiSend("POST", `/interviews/applications/${appId}/mock-sessions`, config);
      setActiveSession(resp);
      setCurrentIdx(0);
      setAnswer("");
      setResult(null);
    } catch (e) { alert(e.message); }
    setCreating(false);
  };

  const submitAnswer = async () => {
    try {
      await apiSend("POST", `/interviews/${activeSession.session_id}/mock-session/answer`, { question_index: currentIdx, answer });
      const questions = activeSession.questions;
      if (currentIdx < questions.length - 1) {
        setCurrentIdx(currentIdx + 1);
        setAnswer("");
      }
    } catch (e) { alert(e.message); }
  };

  const finishSession = async () => {
    try {
      const resp = await apiSend("POST", `/interviews/${activeSession.session_id}/mock-session/finish`);
      setResult(resp.final_summary);
      reload();
    } catch (e) { alert(e.message); }
  };

  const questions = activeSession?.questions || [];
  const total = questions.length;
  const progress = total > 0 ? Math.round((currentIdx / total) * 100) : 0;

  if (result) {
    return (
      <div className={sectionClass}>
        <h3 className="font-semibold text-slate-800">Mock Interview Complete</h3>
        <div className="bg-slate-50 rounded-lg p-4 space-y-3">
          <div className={`text-lg font-bold ${result.overall_label === "STRONG" ? "text-emerald-600" : result.overall_label === "NEEDS_IMPROVEMENT" ? "text-amber-600" : "text-sky-600"}`}>
            {result.overall_label}
          </div>
          <div className="text-sm text-slate-600">{result.message}</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[["strong","Strong","emerald"],["good","Good","sky"],["needs_improvement","Needs Work","amber"],["weak","Weak","rose"]].map(([k,l,c]) => (
              <div key={k} className={`bg-${c}-50 rounded p-2 text-center`}>
                <div className="text-xl font-bold">{result[k] || 0}</div>
                <div className="text-xs text-slate-500">{l}</div>
              </div>
            ))}
          </div>
          <button onClick={() => { setActiveSession(null); setResult(null); }}
            className="px-4 py-2 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700">
            Start New Session
          </button>
        </div>
      </div>
    );
  }

  if (activeSession) {
    const q = questions[currentIdx];
    return (
      <div className={sectionClass}>
        <div className="flex justify-between items-center">
          <h3 className="font-semibold text-slate-800">Question {currentIdx + 1} / {total}</h3>
          <button onClick={finishSession} className="text-sm text-rose-600 hover:underline">End Session</button>
        </div>
        <div className="w-full bg-slate-200 rounded-full h-2">
          <div className="bg-sky-600 h-2 rounded-full transition-all" style={{width:`${progress}%`}} />
        </div>
        {q && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full ${badge(q.category)}`}>{q.category}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${badge(q.difficulty)}`}>{q.difficulty}</span>
            </div>
            <p className="text-sm font-medium text-slate-800">{q.question}</p>
            <textarea value={answer} onChange={e => setAnswer(e.target.value)} rows={4}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="Type your answer..." />
            <button onClick={submitAnswer}
              className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700">
              {currentIdx < total - 1 ? "Next Question" : "Finish"}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={sectionClass}>
      <h3 className="font-semibold text-slate-800">Mock Interviews</h3>
      <div className="bg-slate-50 rounded-lg p-4 space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="text-xs text-slate-500">Questions</label>
            <input type="number" min="1" max="30" value={config.question_count} onChange={e => setConfig({...config, question_count:Number(e.target.value)})}
              className="w-full border rounded px-2 py-1 text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500">Technical %</label>
            <input type="number" min="0" max="100" value={config.technical_pct} onChange={e => setConfig({...config, technical_pct:Number(e.target.value)})}
              className="w-full border rounded px-2 py-1 text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500">Behavioral %</label>
            <input type="number" min="0" max="100" value={config.behavioral_pct} onChange={e => setConfig({...config, behavioral_pct:Number(e.target.value)})}
              className="w-full border rounded px-2 py-1 text-sm" />
          </div>
        </div>
        <button onClick={createSession} disabled={creating}
          className="px-4 py-2 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700 disabled:opacity-50">
          {creating ? "Starting..." : "Start Mock Interview"}
        </button>
      </div>
      <div className="space-y-2">
        {sessions.map(s => (
          <div key={s.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
            <div>
              <span className="text-sm font-medium">Session #{s.id}</span>
              <span className="text-xs text-slate-500 ml-2">{ts(s.started_at)}</span>
              {s.completed_at && <span className="text-xs text-emerald-600 ml-2">Completed</span>}
            </div>
            {s.final_summary?.overall_label && (
              <span className={`text-xs px-2 py-0.5 rounded-full ${badge(s.final_summary.overall_label === "STRONG" ? "PASSED" : s.final_summary.overall_label === "NEEDS_IMPROVEMENT" ? "PENDING" : "CANCELLED")}`}>
                {s.final_summary.overall_label}
              </span>
            )}
          </div>
        ))}
        {sessions.length === 0 && <EmptyState message="No mock sessions yet." />}
      </div>
    </div>
  );
}

function NotesTab({ interviews }) {
  const [selectedId, setSelectedId] = useState(interviews[0]?.id || null);
  const [notes, setNotes] = useState("");
  const [feedback, setFeedback] = useState({personal_performance:"",interviewer_feedback:"",areas_to_improve:""});
  const [saving, setSaving] = useState(false);

  const selected = interviews.find(i => i.id === selectedId);

  useEffect(() => {
    if (selected) {
      setNotes(selected.notes || "");
      setFeedback({
        personal_performance: selected.feedback_json?.personal_performance || "",
        interviewer_feedback: selected.feedback_json?.interviewer_feedback || "",
        areas_to_improve: (selected.feedback_json?.areas_to_improve || []).join(", "),
      });
    }
  }, [selectedId]);

  const saveNotes = async () => {
    setSaving(true);
    try {
      await apiSend("PATCH", `/interviews/${selectedId}`, { notes });
    } catch (e) { alert(e.message); }
    setSaving(false);
  };

  const saveFeedback = async () => {
    setSaving(true);
    try {
      await apiSend("POST", `/interviews/${selectedId}/feedback`, {
        ...feedback,
        areas_to_improve: feedback.areas_to_improve ? feedback.areas_to_improve.split(",").map(s => s.trim()) : [],
      });
    } catch (e) { alert(e.message); }
    setSaving(false);
  };

  return (
    <div className="space-y-4">
      <div className={sectionClass}>
        <h3 className="font-semibold text-slate-800">Interview Notes</h3>
        <select value={selectedId || ""} onChange={e => setSelectedId(Number(e.target.value))}
          className="border rounded-lg px-3 py-2 text-sm w-full">
          {interviews.map(i => <option key={i.id} value={i.id}>Round {i.round} - {i.interview_type} ({i.status})</option>)}
        </select>
        {selected && (
          <div className="space-y-3">
            <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={4}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="Add notes..." />
            <button onClick={saveNotes} disabled={saving}
              className="px-4 py-2 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700 disabled:opacity-50">
              {saving ? "Saving..." : "Save Notes"}
            </button>
          </div>
        )}
      </div>
      {selected && (
        <div className={sectionClass}>
          <h3 className="font-semibold text-slate-800">Interview Feedback</h3>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-slate-500">Your Performance</label>
              <textarea value={feedback.personal_performance} onChange={e => setFeedback({...feedback, personal_performance:e.target.value})} rows={2}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="text-xs text-slate-500">Interviewer Feedback</label>
              <textarea value={feedback.interviewer_feedback} onChange={e => setFeedback({...feedback, interviewer_feedback:e.target.value})} rows={2}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="text-xs text-slate-500">Areas to Improve (comma separated)</label>
              <input value={feedback.areas_to_improve} onChange={e => setFeedback({...feedback, areas_to_improve:e.target.value})}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <button onClick={saveFeedback} disabled={saving}
              className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 disabled:opacity-50">
              {saving ? "Saving..." : "Save Feedback"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PrepTab({ items, reload }) {
  const toggleStatus = async (itemId, newStatus) => {
    try {
      await apiSend("PATCH", `/interviews/prep-items/${itemId}`, { status: newStatus });
      reload();
    } catch (e) { alert(e.message); }
  };

  const completedCount = items.filter(i => i.status === "COMPLETED").length;
  const pct = items.length > 0 ? Math.round((completedCount / items.length) * 100) : 0;

  return (
    <div className={sectionClass}>
      <h3 className="font-semibold text-slate-800">Preparation Plan</h3>
      <div className="w-full bg-slate-200 rounded-full h-2">
        <div className="bg-emerald-600 h-2 rounded-full transition-all" style={{width:`${pct}%`}} />
      </div>
      <div className="text-xs text-slate-500">{completedCount}/{items.length} completed ({pct}%)</div>
      <div className="space-y-2">
        {items.map(item => (
          <div key={item.id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
            <span className={`text-xs px-2 py-0.5 rounded-full ${badge(item.category)}`}>{item.category}</span>
            <span className="flex-1 text-sm">{item.label}</span>
            <div className="flex gap-1">
              {PREP_STATUSES.map(s => (
                <button key={s} onClick={() => toggleStatus(item.id, s)}
                  className={`text-xs px-2 py-1 rounded ${item.status === s ? badge(s) : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ))}
        {items.length === 0 && <EmptyState message="No prep items. Create an interview to generate a prep plan." />}
      </div>
    </div>
  );
}
