import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api/client.js";
import PageHeader from "../components/PageHeader.jsx";

const STATUS_COLORS = {
  MATCHED: "bg-emerald-100 text-emerald-700",
  PARTIAL: "bg-amber-100 text-amber-700",
  MISSING: "bg-rose-100 text-rose-700",
  UNKNOWN: "bg-slate-100 text-slate-500",
};

const PRIORITY_COLORS = {
  HIGH: "bg-amber-100 text-amber-700",
  MEDIUM: "bg-sky-100 text-sky-700",
  LOW: "bg-slate-100 text-slate-500",
};

const DEMAND_COLORS = {
  HIGH: "text-emerald-600",
  MEDIUM: "text-amber-600",
  LOW: "text-slate-400",
};

const RESOURCE_TYPE_ICONS = {
  COURSE: "🎓",
  TUTORIAL: "📝",
  DOCUMENTATION: "📖",
  VIDEO: "🎥",
  ARTICLE: "📰",
  BOOK: "📚",
  PRACTICE: "💻",
  PROJECT: "🛠",
};

const SOURCE_ICONS = {
  USER: "",
  AI_SUGGESTED: "🤖",
};

function ReadinessGauge({ label, percentage }) {
  const color =
    percentage >= 80
      ? "bg-emerald-500"
      : percentage >= 50
        ? "bg-amber-500"
        : "bg-rose-500";
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm font-medium text-slate-700 w-20">{label}</span>
      <div className="flex-1 h-3 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full ${color} transition-all`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-sm font-semibold text-slate-900 w-12 text-right">
        {percentage}%
      </span>
    </div>
  );
}

function SkillRow({ skill, onClick }) {
  return (
    <tr
      className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer"
      onClick={() => onClick(skill)}
    >
      <td className="py-2 px-3 text-sm font-medium text-slate-900">
        {skill.skill}
      </td>
      <td className="py-2 px-3">
        <span
          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[skill.status] || STATUS_COLORS.UNKNOWN}`}
        >
          {skill.status}
        </span>
      </td>
      <td className="py-2 px-3 text-xs text-slate-500">{skill.source}</td>
      <td className="py-2 px-3 text-xs text-slate-500 max-w-[200px] truncate">
        {skill.evidence || "—"}
      </td>
      <td className="py-2 px-3">
        <span
          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${PRIORITY_COLORS[skill.priority] || PRIORITY_COLORS.MEDIUM}`}
        >
          {skill.priority || "—"}
        </span>
      </td>
      <td className="py-2 px-3 text-xs">
        <span className={DEMAND_COLORS[skill.demand_level] || "text-slate-400"}>
          {skill.demand_level || "—"}
        </span>
      </td>
    </tr>
  );
}

function SkillDetail({ skill, profileId, onBack }) {
  const [resources, setResources] = useState([]);
  const [history, setHistory] = useState([]);
  const [showAddResource, setShowAddResource] = useState(false);
  const [newResource, setNewResource] = useState({
    title: "",
    resource_type: "COURSE",
    url: "",
    description: "",
  });

  useEffect(() => {
    if (!profileId) return;
    apiGet(`/skills/history/${encodeURIComponent(skill.skill)}?profile_id=${profileId}`)
      .then(setHistory)
      .catch(() => {});
  }, [skill.skill, profileId]);

  const loadResources = (itemId) => {
    apiGet(`/skills/learning-items/${itemId}/resources`)
      .then(setResources)
      .catch(() => {});
  };

  useEffect(() => {
    apiGet(`/skills/learning-plans`)
      .then((plans) => {
        if (plans.length > 0) {
          apiGet(`/skills/learning-plans/${plans[0].id}/items`)
            .then((items) => {
              const match = items.find((i) => i.skill === skill.skill);
              if (match) loadResources(match.id);
            })
            .catch(() => {});
        }
      })
      .catch(() => {});
  }, [skill.skill]);

  const handleAddResource = async () => {
    try {
      apiGet(`/skills/learning-plans`)
        .then(async (plans) => {
          if (plans.length > 0) {
            const items = await apiGet(
              `/skills/learning-plans/${plans[0].id}/items`
            );
            const match = items.find((i) => i.skill === skill.skill);
            if (match) {
              await apiSend(
                "POST",
                `/skills/learning-items/${match.id}/resources`,
                {
                  ...newResource,
                  source: "USER",
                }
              );
              loadResources(match.id);
              setShowAddResource(false);
              setNewResource({
                title: "",
                resource_type: "COURSE",
                url: "",
                description: "",
              });
            }
          }
        })
        .catch(() => {});
    } catch (err) {
      console.error("Failed to add resource:", err);
    }
  };

  return (
    <div>
      <button
        onClick={onBack}
        className="text-sm text-blue-600 hover:underline mb-4"
      >
        ← Back to analysis
      </button>

      <div className="border border-slate-200 rounded-lg p-5 mb-4">
        <div className="flex items-center gap-3 mb-3">
          <h2 className="text-lg font-bold text-slate-900">{skill.skill}</h2>
          <span
            className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[skill.status]}`}
          >
            {skill.status}
          </span>
          <span
            className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${PRIORITY_COLORS[skill.priority]}`}
          >
            {skill.priority}
          </span>
        </div>

        {/* Why this skill matters */}
        {skill.why && skill.why.length > 0 && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold text-slate-700 mb-2">
              Why this skill matters
            </h3>
            <ul className="space-y-1">
              {skill.why.map((reason, i) => (
                <li key={i} className="text-xs text-slate-600 flex items-start gap-1">
                  <span className="text-slate-400 mt-0.5">•</span>
                  {reason}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Evidence */}
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-1">
            Evidence
          </h3>
          <p className="text-xs text-slate-600">
            {skill.evidence || "No evidence found"}
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Source: {skill.source} · Confidence: {skill.confidence}
          </p>
        </div>

        {/* Market demand */}
        {skill.demand_level && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold text-slate-700 mb-1">
              Market Demand
            </h3>
            <p className="text-xs">
              <span className={DEMAND_COLORS[skill.demand_level]}>
                {skill.demand_level}
              </span>
              {skill.demand_frequency && (
                <span className="text-slate-400 ml-2">
                  (required in {skill.demand_frequency} of analyzed jobs)
                </span>
              )}
            </p>
            {skill.mandatory && (
              <p className="text-xs text-amber-600 mt-1">
                This skill is marked as mandatory for the role
              </p>
            )}
          </div>
        )}
      </div>

      {/* Learning Resources */}
      <div className="border border-slate-200 rounded-lg p-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-700">
            Learning Resources
          </h3>
          <button
            onClick={() => setShowAddResource(!showAddResource)}
            className="text-xs text-blue-600 hover:underline"
          >
            {showAddResource ? "Cancel" : "+ Add Resource"}
          </button>
        </div>

        {showAddResource && (
          <div className="border border-slate-200 rounded-lg p-3 mb-3 bg-slate-50">
            <div className="grid grid-cols-2 gap-2 mb-2">
              <input
                placeholder="Resource title"
                value={newResource.title}
                onChange={(e) =>
                  setNewResource({ ...newResource, title: e.target.value })
                }
                className="border border-slate-300 rounded px-2 py-1 text-xs"
              />
              <select
                value={newResource.resource_type}
                onChange={(e) =>
                  setNewResource({
                    ...newResource,
                    resource_type: e.target.value,
                  })
                }
                className="border border-slate-300 rounded px-2 py-1 text-xs"
              >
                <option value="COURSE">Course</option>
                <option value="TUTORIAL">Tutorial</option>
                <option value="DOCUMENTATION">Documentation</option>
                <option value="VIDEO">Video</option>
                <option value="ARTICLE">Article</option>
                <option value="BOOK">Book</option>
                <option value="PRACTICE">Practice</option>
                <option value="PROJECT">Project</option>
              </select>
            </div>
            <input
              placeholder="URL (optional)"
              value={newResource.url}
              onChange={(e) =>
                setNewResource({ ...newResource, url: e.target.value })
              }
              className="w-full border border-slate-300 rounded px-2 py-1 text-xs mb-2"
            />
            <input
              placeholder="Description (optional)"
              value={newResource.description}
              onChange={(e) =>
                setNewResource({ ...newResource, description: e.target.value })
              }
              className="w-full border border-slate-300 rounded px-2 py-1 text-xs mb-2"
            />
            <button
              onClick={handleAddResource}
              disabled={!newResource.title}
              className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50"
            >
              Add
            </button>
          </div>
        )}

        {resources.length === 0 ? (
          <p className="text-xs text-slate-500">
            No resources added yet. Add a resource to start learning.
          </p>
        ) : (
          <div className="space-y-2">
            {resources.map((res) => (
              <div
                key={res.id}
                className="flex items-start gap-2 p-2 bg-slate-50 rounded"
              >
                <span className="text-sm">
                  {RESOURCE_TYPE_ICONS[res.resource_type] || "📄"}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-medium text-slate-900 truncate">
                      {res.title}
                    </span>
                    {res.source === "AI_SUGGESTED" && (
                      <span className="text-xs text-slate-400" title="AI suggested">
                        🤖
                      </span>
                    )}
                  </div>
                  {res.url && (
                    <a
                      href={res.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-600 hover:underline truncate block"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {res.url}
                    </a>
                  )}
                  {res.description && (
                    <p className="text-xs text-slate-500 mt-0.5">
                      {res.description}
                    </p>
                  )}
                </div>
                <span className="text-xs text-slate-400 whitespace-nowrap">
                  {res.difficulty !== "UNKNOWN" && res.difficulty}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Skill History */}
      <div className="border border-slate-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">
          Skill History
        </h3>
        {history.length === 0 ? (
          <p className="text-xs text-slate-500">No history recorded yet.</p>
        ) : (
          <div className="space-y-2">
            {history.slice(0, 10).map((h) => (
              <div
                key={h.id}
                className="flex items-start gap-3 text-xs"
              >
                <div className="w-2 h-2 rounded-full bg-blue-400 mt-1.5 shrink-0" />
                <div>
                  <div className="flex items-center gap-2">
                    {h.previous_status && (
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${STATUS_COLORS[h.previous_status] || "bg-slate-100"}`}
                      >
                        {h.previous_status}
                      </span>
                    )}
                    {h.previous_status && (
                      <span className="text-slate-400">→</span>
                    )}
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${STATUS_COLORS[h.new_status] || "bg-slate-100"}`}
                    >
                      {h.new_status}
                    </span>
                    <span className="text-slate-400">
                      via {h.source.replace("_", " ")}
                    </span>
                  </div>
                  {h.reason && (
                    <p className="text-slate-500 mt-0.5">{h.reason}</p>
                  )}
                  <p className="text-slate-400 mt-0.5">
                    {new Date(h.created_at).toLocaleString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LearningPlanCard({ plan, onClick }) {
  const progress =
    plan.total_items > 0
      ? Math.round((plan.completed_items / plan.total_items) * 100)
      : 0;
  return (
    <div
      className="border border-slate-200 rounded-lg p-4 hover:border-blue-300 cursor-pointer transition-colors"
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{plan.title}</h3>
          <p className="text-xs text-slate-500 mt-1">
            {plan.target_role || "General"} · {plan.estimated_effort_hours}h
            estimated
          </p>
        </div>
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium ${
            plan.status === "COMPLETED"
              ? "bg-emerald-100 text-emerald-700"
              : plan.status === "IN_PROGRESS"
                ? "bg-sky-100 text-sky-700"
                : "bg-slate-100 text-slate-500"
          }`}
        >
          {plan.status.replace("_", " ")}
        </span>
      </div>
      <div className="mt-3">
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
          <span>
            {plan.completed_items}/{plan.total_items} items
          </span>
          <span>·</span>
          <span>{plan.verified_items} verified</span>
        </div>
        <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function LearningPlanDetail({ plan, onBack }) {
  const [items, setItems] = useState([]);
  const [itemResources, setItemResources] = useState({});
  const [expandedItem, setExpandedItem] = useState(null);

  useEffect(() => {
    apiGet(`/skills/learning-plans/${plan.id}/items`).then(setItems);
  }, [plan.id]);

  const handleStatusChange = async (itemId, status) => {
    await apiSend("PATCH", `/skills/learning-items/${itemId}/status`, {
      status,
    });
    setItems((prev) =>
      prev.map((i) => (i.id === itemId ? { ...i, status } : i))
    );
  };

  const toggleResources = async (itemId) => {
    if (expandedItem === itemId) {
      setExpandedItem(null);
      return;
    }
    setExpandedItem(itemId);
    if (!itemResources[itemId]) {
      try {
        const res = await apiGet(`/skills/learning-items/${itemId}/resources`);
        setItemResources((prev) => ({ ...prev, [itemId]: res }));
      } catch {
        setItemResources((prev) => ({ ...prev, [itemId]: [] }));
      }
    }
  };

  const handleAddResource = async (itemId, resource) => {
    await apiSend("POST", `/skills/learning-items/${itemId}/resources`, {
      ...resource,
      source: "USER",
    });
    const res = await apiGet(`/skills/learning-items/${itemId}/resources`);
    setItemResources((prev) => ({ ...prev, [itemId]: res }));
  };

  return (
    <div>
      <button
        onClick={onBack}
        className="text-sm text-blue-600 hover:underline mb-4"
      >
        ← Back to plans
      </button>
      <h2 className="text-lg font-bold text-slate-900 mb-2">{plan.title}</h2>
      <p className="text-sm text-slate-500 mb-4">
        {plan.target_role} · {plan.estimated_effort_hours}h estimated ·{" "}
        {plan.completed_items}/{plan.total_items} completed
      </p>
      <div className="space-y-3">
        {items.map((item) => (
          <div
            key={item.id}
            className="border border-slate-200 rounded-lg p-4"
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-900">
                    {item.skill}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium ${PRIORITY_COLORS[item.priority]}`}
                  >
                    {item.priority}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium ${
                      item.status === "VERIFIED"
                        ? "bg-emerald-100 text-emerald-700"
                        : item.status === "COMPLETED"
                          ? "bg-sky-100 text-sky-700"
                          : item.status === "IN_PROGRESS"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {item.status.replace("_", " ")}
                  </span>
                </div>
                <p className="text-xs text-slate-600 mt-1">{item.objective}</p>
              </div>
              <div className="flex gap-1">
                {item.status === "NOT_STARTED" && (
                  <button
                    onClick={() => handleStatusChange(item.id, "IN_PROGRESS")}
                    className="text-xs px-2 py-1 bg-blue-50 text-blue-600 rounded hover:bg-blue-100"
                  >
                    Start
                  </button>
                )}
                {item.status === "IN_PROGRESS" && (
                  <button
                    onClick={() => handleStatusChange(item.id, "COMPLETED")}
                    className="text-xs px-2 py-1 bg-emerald-50 text-emerald-600 rounded hover:bg-emerald-100"
                  >
                    Complete
                  </button>
                )}
                {item.status === "COMPLETED" && (
                  <button
                    onClick={() => handleStatusChange(item.id, "VERIFIED")}
                    className="text-xs px-2 py-1 bg-purple-50 text-purple-600 rounded hover:bg-purple-100"
                  >
                    Verify
                  </button>
                )}
              </div>
            </div>
            {item.tasks?.length > 0 && (
              <div className="mt-2 pl-3 border-l-2 border-slate-100">
                {item.tasks.map((t, i) => (
                  <div key={i} className="text-xs text-slate-500 py-0.5">
                    {t.title} ({t.estimated_hours}h)
                  </div>
                ))}
              </div>
            )}
            {/* Resources toggle */}
            <button
              onClick={() => toggleResources(item.id)}
              className="mt-2 text-xs text-blue-600 hover:underline"
            >
              {expandedItem === item.id ? "Hide resources" : "Show resources"}
            </button>
            {expandedItem === item.id && (
              <div className="mt-2 pl-3 border-l-2 border-blue-100">
                {(itemResources[item.id] || []).length === 0 ? (
                  <p className="text-xs text-slate-500">No resources yet.</p>
                ) : (
                  <div className="space-y-1">
                    {itemResources[item.id]?.map((res) => (
                      <div key={res.id} className="flex items-center gap-2 text-xs">
                        <span>{RESOURCE_TYPE_ICONS[res.resource_type] || "📄"}</span>
                        <span className="text-slate-700">{res.title}</span>
                        {res.source === "AI_SUGGESTED" && (
                          <span title="AI suggested">🤖</span>
                        )}
                        {res.url && (
                          <a
                            href={res.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            link
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SkillGap() {
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [plans, setPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [selectedSkill, setSelectedSkill] = useState(null);
  const [loading, setLoading] = useState(false);
  const [profileId, setProfileId] = useState(null);

  useEffect(() => {
    apiGet("/jobs").then((data) => setJobs(data.items || data.jobs || []));
    apiGet("/skills/learning-plans").then(setPlans);
    apiGet("/profile").then((p) => setProfileId(p.id)).catch(() => {});
  }, []);

  const analyzeJob = async (jobId) => {
    setLoading(true);
    try {
      const result = await apiSend(
        "POST",
        `/skills/gap-analysis/${jobId}?profile_id=${profileId}`,
        {}
      );
      setAnalysis(result);
      setSelectedJob(jobId);
      setSelectedSkill(null);
    } catch (err) {
      console.error("Analysis failed:", err);
    }
    setLoading(false);
  };

  const generatePlan = async () => {
    if (!selectedJob) return;
    setLoading(true);
    try {
      const plan = await apiSend(
        "POST",
        `/skills/learning-plans/${selectedJob}?profile_id=${profileId}`,
        {}
      );
      setPlans((prev) => [plan, ...prev]);
      setSelectedPlan(plan);
    } catch (err) {
      console.error("Plan generation failed:", err);
    }
    setLoading(false);
  };

  // Skill detail view
  if (selectedSkill && analysis) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <PageHeader title="Skill Development" />
        <SkillDetail
          skill={selectedSkill}
          profileId={profileId}
          onBack={() => setSelectedSkill(null)}
        />
      </div>
    );
  }

  // Learning plan detail view
  if (selectedPlan) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <PageHeader title="Skill Development" />
        <LearningPlanDetail
          plan={selectedPlan}
          onBack={() => setSelectedPlan(null)}
        />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <PageHeader title="Skill Gap Analysis" />

      {/* Job selector */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-slate-700 mb-1">
          Select a job to analyze
        </label>
        <div className="flex gap-2">
          <select
            className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm"
            value={selectedJob || ""}
            onChange={(e) =>
              setSelectedJob(e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">Choose a job…</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title} — {j.company}
              </option>
            ))}
          </select>
          <button
            onClick={() => selectedJob && analyzeJob(selectedJob)}
            disabled={!selectedJob || loading || !profileId}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </div>

      {/* Analysis results */}
      {analysis && (
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold text-slate-900">
              Gap Analysis Results
            </h2>
            <button
              onClick={generatePlan}
              disabled={loading}
              className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 disabled:opacity-50"
            >
              {loading ? "Generating…" : "Generate Learning Plan"}
            </button>
          </div>

          {/* Readiness */}
          <div className="border border-slate-200 rounded-lg p-4 mb-4">
            <h3 className="text-sm font-semibold text-slate-700 mb-3">
              Readiness: {analysis.readiness_label} ({analysis.readiness_percentage}%)
            </h3>
            <ReadinessGauge
              label="Skills"
              percentage={analysis.readiness_percentage}
            />
          </div>

          {/* Market demand */}
          <div className="border border-slate-200 rounded-lg p-4 mb-4">
            <h3 className="text-sm font-semibold text-slate-700 mb-2">
              Market Demand
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {Object.entries(analysis.market_demand || {}).map(
                ([skill, info]) => (
                  <div key={skill} className="flex items-center gap-2 text-xs">
                    <span className="font-medium text-slate-700">{skill}</span>
                    <span className={DEMAND_COLORS[info.demand_level]}>
                      {info.demand_level}
                    </span>
                    <span className="text-slate-400">
                      ({info.frequency}/{info.total_jobs})
                    </span>
                  </div>
                )
              )}
            </div>
          </div>

          {/* Skills table */}
          <div className="border border-slate-200 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="text-left text-xs font-medium text-slate-500 py-2 px-3">
                    Skill
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 py-2 px-3">
                    Status
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 py-2 px-3">
                    Source
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 py-2 px-3">
                    Evidence
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 py-2 px-3">
                    Priority
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 py-2 px-3">
                    Demand
                  </th>
                </tr>
              </thead>
              <tbody>
                {(analysis.evidence || []).map((skill, i) => (
                  <SkillRow
                    key={i}
                    skill={{
                      ...skill,
                      priority: analysis.priorities?.[skill.skill],
                    }}
                    onClick={setSelectedSkill}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Learning Plans */}
      <div>
        <h2 className="text-lg font-bold text-slate-900 mb-4">Learning Plans</h2>
        {plans.length === 0 ? (
          <p className="text-sm text-slate-500">
            No learning plans yet. Analyze a job and generate a plan.
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {plans.map((plan) => (
              <LearningPlanCard
                key={plan.id}
                plan={plan}
                onClick={() => setSelectedPlan(plan)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
