import { useEffect, useState } from "react";
import { apiSend } from "../api/client.js";
import { useAppData } from "../context/AppDataContext.jsx";
import {
  DEFAULT_LOCATIONS,
  EMPLOYMENT_TYPES,
  REMOTE_TYPES,
  TARGET_ROLES,
} from "../constants/options.js";
import PageHeader from "../components/PageHeader.jsx";
import SectionCard from "../components/SectionCard.jsx";
import Field from "../components/form/Field.jsx";
import Input from "../components/form/Input.jsx";
import Select from "../components/form/Select.jsx";
import TagInput from "../components/form/TagInput.jsx";

function fromPreferences(preferences) {
  return {
    preferred_locations: preferences?.preferred_locations || [],
    experience_levels: preferences?.experience_levels || [],
    target_roles: preferences?.target_roles || [],
    remote_types: preferences?.remote_types || [],
    employment_types: preferences?.employment_types || [],
    min_match_score: preferences?.min_match_score ?? 60,
    salary_min: preferences?.salary_min ?? "",
    salary_max: preferences?.salary_max ?? "",
    posted_within_days: preferences?.posted_within_days ?? 30,
    include_keywords: preferences?.include_keywords || [],
    exclude_keywords: preferences?.exclude_keywords || [],
  };
}

function Chip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
        active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-slate-300 bg-white text-slate-600 hover:border-slate-400"
      }`}
    >
      {children}
    </button>
  );
}

export default function Preferences() {
  const { preferences, reloadPreferences } = useAppData();
  const [form, setForm] = useState(() => fromPreferences(preferences));
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next = fromPreferences(preferences);
    if (next !== form) setForm(next);
  }, [preferences]);

  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  const toggle = (key, value) =>
    setForm((f) => ({
      ...f,
      [key]: f[key].includes(value) ? f[key].filter((v) => v !== value) : [...f[key], value],
    }));

  async function handleSave() {
    setNotice(null);
    const payload = {
      ...form,
      salary_min: form.salary_min === "" || form.salary_min == null ? null : Number(form.salary_min),
      salary_max: form.salary_max === "" || form.salary_max == null ? null : Number(form.salary_max),
      min_match_score: Number(form.min_match_score),
      posted_within_days: Number(form.posted_within_days),
    };
    if (payload.salary_min != null && payload.salary_max != null && payload.salary_min > payload.salary_max) {
      setNotice({ type: "error", text: "Minimum salary cannot exceed maximum salary." });
      return;
    }
    setSaving(true);
    try {
      await apiSend("PUT", "/preferences", payload);
      await reloadPreferences();
      setNotice({ type: "success", text: "Preferences saved." });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Job Search Preferences"
        description="Controls used to filter and score jobs. Nothing is fixed — adjust anytime."
      />
      <div className="space-y-6">
        <SectionCard title="Locations & Roles">
          <div className="grid gap-4">
            <Field label="Preferred locations" hint="Press Enter to add. Suggested: Chennai, Madurai, Remote - India">
              <TagInput
                value={form.preferred_locations}
                onChange={(value) => setField("preferred_locations", value)}
                placeholder="Type a location and press Enter"
              />
            </Field>
            <div>
              <span className="mb-1 block text-sm font-medium text-slate-700">Quick add</span>
              <div className="flex flex-wrap gap-2">
                {DEFAULT_LOCATIONS.map((location) => (
                  <Chip
                    key={location}
                    active={form.preferred_locations.includes(location)}
                    onClick={() => {
                      if (form.preferred_locations.includes(location)) {
                        setField("preferred_locations", form.preferred_locations.filter((l) => l !== location));
                      } else {
                        setField("preferred_locations", [...form.preferred_locations, location]);
                      }
                    }}
                  >
                    {location}
                  </Chip>
                ))}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Experience Level">
          <div className="flex flex-wrap gap-2">
            {["Fresher", "0-2 years"].map((level) => (
              <Chip key={level} active={form.experience_levels.includes(level)} onClick={() => toggle("experience_levels", level)}>
                {level}
              </Chip>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Target Roles">
          <div className="flex flex-wrap gap-2">
            {TARGET_ROLES.map((role) => (
              <Chip key={role} active={form.target_roles.includes(role)} onClick={() => toggle("target_roles", role)}>
                {role}
              </Chip>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Work Mode">
          <span className="mb-2 block text-xs font-medium uppercase tracking-wide text-slate-400">Remote type</span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(REMOTE_TYPES).map(([value, label]) => (
              <Chip key={value} active={form.remote_types.includes(value)} onClick={() => toggle("remote_types", value)}>
                {label}
              </Chip>
            ))}
          </div>
          <span className="mb-2 mt-5 block text-xs font-medium uppercase tracking-wide text-slate-400">Employment type</span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(EMPLOYMENT_TYPES).map(([value, label]) => (
              <Chip key={value} active={form.employment_types.includes(value)} onClick={() => toggle("employment_types", value)}>
                {label}
              </Chip>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Filters">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Minimum match score" hint={`Only jobs scoring ≥ ${form.min_match_score}% are kept`}>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={form.min_match_score}
                  onChange={(e) => setField("min_match_score", e.target.value)}
                  className="flex-1 accent-slate-900"
                />
                <span className="w-12 text-right text-sm font-semibold text-slate-900">{form.min_match_score}%</span>
              </div>
            </Field>
            <Field label="Posted within">
              <Select
                value={form.posted_within_days}
                onChange={(e) => setField("posted_within_days", e.target.value)}
                options={[7, 14, 30, 60, 90].map((days) => ({ value: days, label: `Last ${days} days` }))}
              />
            </Field>
            <Field label="Minimum salary (₹ per year)">
              <Input type="number" min="0" value={form.salary_min} onChange={(e) => setField("salary_min", e.target.value)} placeholder="e.g. 300000" />
            </Field>
            <Field label="Maximum salary (₹ per year)">
              <Input type="number" min="0" value={form.salary_max} onChange={(e) => setField("salary_max", e.target.value)} placeholder="e.g. 900000" />
            </Field>
          </div>
        </SectionCard>

        <SectionCard title="Keywords">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Include keywords" hint="Jobs mentioning any of these are preferred.">
              <TagInput value={form.include_keywords} onChange={(value) => setField("include_keywords", value)} placeholder="e.g. Django, Docker" />
            </Field>
            <Field label="Exclude keywords" hint="Jobs mentioning any of these are filtered out.">
              <TagInput value={form.exclude_keywords} onChange={(value) => setField("exclude_keywords", value)} placeholder="e.g. night shift" />
            </Field>
          </div>
        </SectionCard>

        {notice && (
          <div className={`rounded border px-4 py-3 text-sm ${notice.type === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
            {notice.text}
          </div>
        )}

        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded bg-slate-900 px-6 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Preferences"}
        </button>
      </div>
    </div>
  );
}