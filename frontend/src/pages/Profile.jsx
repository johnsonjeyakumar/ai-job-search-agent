import { useEffect, useState } from "react";
import { apiSend } from "../api/client.js";
import { useAppData } from "../context/AppDataContext.jsx";
import {
  EXPERIENCE_LEVELS,
  NOTICE_PERIODS,
  TARGET_ROLES,
  WORK_AUTHORIZATIONS,
  validateGraduationYear,
  validateProfileUrl,
} from "../constants/options.js";
import Field from "../components/form/Field.jsx";
import Input from "../components/form/Input.jsx";
import Select from "../components/form/Select.jsx";
import TextArea from "../components/form/TextArea.jsx";
import TagInput from "../components/form/TagInput.jsx";
import PageHeader from "../components/PageHeader.jsx";
import SectionCard from "../components/SectionCard.jsx";

const EMPTY_PROJECT = { name: "", description: "", technologies: [], url: "" };
const EMPTY_INTERNSHIP = { company: "", role: "", duration: "", description: "", technologies: [] };
const EMPTY_CERT = { name: "", issuer: "", date: "", credential_url: "" };

function emptyForm() {
  return {
    name: "",
    email: "",
    phone: "",
    city: "",
    state: "",
    country: "",
    experience_level: "",
    preferred_roles: [],
    preferred_locations: [],
    remote_preference: "",
    salary_preference: "",
    notice_period: "",
    work_authorization: "",
    linkedin_url: "",
    github_url: "",
    portfolio_url: "",
    degree: "",
    university: "",
    graduation_year: "",
    cgpa: "",
    skills_programming: [],
    skills_frameworks: [],
    skills_databases: [],
    skills_tools: [],
    skills_other: [],
    projects: [],
    internships: [],
    certifications: [],
  };
}

function fromProfile(profile) {
  const form = emptyForm();
  if (!profile) return form;
  const strip = (value) => value ?? "";
  Object.keys(form).forEach((key) => {
    if (key === "projects" || key === "internships" || key === "certifications") {
      form[key] = (profile[key] || []).map(copyItems([key]));
    } else if (Array.isArray(profile[key])) {
      form[key] = profile[key];
    } else if (profile[key] !== undefined) {
      form[key] = strip(profile[key]);
    }
  });
  form.graduation_year = profile.graduation_year ? String(profile.graduation_year) : "";
  return form;
}

function copyItems(key) {
  if (key === "projects") {
    return (p) => ({ ...EMPTY_PROJECT, ...p, technologies: [...(p.technologies || [])] });
  }
  if (key === "internships") {
    return (p) => ({ ...EMPTY_INTERNSHIP, ...p, technologies: [...(p.technologies || [])] });
  }
  return (p) => ({ ...EMPTY_CERT, ...p });
}

export default function Profile() {
  const { profile, reloadProfile } = useAppData();
  const [form, setForm] = useState(() => emptyForm());
  const [errors, setErrors] = useState({});
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (profile) setForm(fromProfile(profile));
  }, [profile]);

  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  const updateItem = (listKey, index, patch) =>
    setForm((f) => {
      const list = [...f[listKey]];
      list[index] = { ...list[index], ...patch };
      return { ...f, [listKey]: list };
    });

  const addItem = (listKey, template) =>
    setForm((f) => ({ ...f, [listKey]: [...f[listKey], { ...template }] }));

  const removeItem = (listKey, index) =>
    setForm((f) => ({ ...f, [listKey]: f[listKey].filter((_, i) => i !== index) }));

  function buildPayload() {
    const emptyStringToNull = (value) => (value && value.trim() ? value : null);
    const urlOrNull = (value) => (value && value.trim() ? value.trim() : null);

    return {
      name: form.name.trim(),
      email: form.email.trim(),
      phone: emptyStringToNull(form.phone),
      city: emptyStringToNull(form.city),
      state: emptyStringToNull(form.state),
      country: emptyStringToNull(form.country),
      experience_level: emptyStringToNull(form.experience_level),
      preferred_roles: form.preferred_roles,
      preferred_locations: form.preferred_locations,
      remote_preference: emptyStringToNull(form.remote_preference),
      salary_preference: emptyStringToNull(form.salary_preference),
      notice_period: emptyStringToNull(form.notice_period),
      work_authorization: emptyStringToNull(form.work_authorization),
      linkedin_url: urlOrNull(form.linkedin_url),
      github_url: urlOrNull(form.github_url),
      portfolio_url: urlOrNull(form.portfolio_url),
      degree: emptyStringToNull(form.degree),
      university: emptyStringToNull(form.university),
      graduation_year: form.graduation_year ? Number(form.graduation_year) : null,
      cgpa: emptyStringToNull(form.cgpa),
      skills_programming: form.skills_programming,
      skills_frameworks: form.skills_frameworks,
      skills_databases: form.skills_databases,
      skills_tools: form.skills_tools,
      skills_other: form.skills_other,
      skills: [],
      projects: form.projects.map((p) => ({
        ...p,
        name: p.name.trim(),
        description: emptyStringToNull(p.description),
        url: urlOrNull(p.url),
      })),
      internships: form.internships.map((p) => ({
        ...p,
        company: p.company.trim(),
        role: emptyStringToNull(p.role),
        duration: emptyStringToNull(p.duration),
        description: emptyStringToNull(p.description),
      })),
      certifications: form.certifications.map((c) => ({
        ...c,
        name: c.name.trim(),
        issuer: emptyStringToNull(c.issuer),
        date: emptyStringToNull(c.date),
        credential_url: urlOrNull(c.credential_url),
      })),
    };
  }

  function validate(payload) {
    const next = {};
    if (!payload.name) next.name = "Full name is required.";
    if (!payload.email) next.email = "Email is required.";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(payload.email)) {
      next.email = "Enter a valid email address.";
    }
    if (validateGraduationYear(payload.graduation_year)) {
      next.graduation_year = validateGraduationYear(payload.graduation_year);
    }
    if (validateProfileUrl(payload.linkedin_url)) next.linkedin_url = validateProfileUrl(payload.linkedin_url);
    if (validateProfileUrl(payload.github_url)) next.github_url = validateProfileUrl(payload.github_url);
    if (validateProfileUrl(payload.portfolio_url)) next.portfolio_url = validateProfileUrl(payload.portfolio_url);
    payload.projects.forEach((project, index) => {
      if (!project.name) next[`projects.${index}.name`] = "Project name is required.";
    });
    payload.certifications.forEach((cert, index) => {
      if (!cert.name) next[`certifications.${index}.name`] = "Certification name is required.";
    });
    payload.internships.forEach((item, index) => {
      if (!item.company) next[`internships.${index}.company`] = "Company is required.";
    });
    return next;
  }

  async function handleSave() {
    setErrors({});
    setNotice(null);
    const payload = buildPayload();
    const nextErrors = validate(payload);
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }
    setSaving(true);
    try {
      await apiSend("POST", "/profile", payload);
      await reloadProfile();
      setNotice({ type: "success", text: "Profile saved." });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Profile"
        description="Your personal, professional and academic details used across the job search."
      />
      <div className="space-y-6">
        <SectionCard title="Personal Information">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name" required error={errors.name}>
              <Input value={form.name} onChange={(e) => setField("name", e.target.value)} invalid={!!errors.name} />
            </Field>
            <Field label="Email" required error={errors.email}>
              <Input type="email" value={form.email} onChange={(e) => setField("email", e.target.value)} invalid={!!errors.email} />
            </Field>
            <Field label="Phone">
              <Input value={form.phone} onChange={(e) => setField("phone", e.target.value)} />
            </Field>
            <Field label="City">
              <Input value={form.city} onChange={(e) => setField("city", e.target.value)} />
            </Field>
            <Field label="State">
              <Input value={form.state} onChange={(e) => setField("state", e.target.value)} />
            </Field>
            <Field label="Country">
              <Input value={form.country} onChange={(e) => setField("country", e.target.value)} />
            </Field>
          </div>
        </SectionCard>

        <SectionCard title="Professional">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Experience level">
              <Select
                value={form.experience_level}
                onChange={(e) => setField("experience_level", e.target.value)}
                placeholder="Select experience level"
                options={EXPERIENCE_LEVELS.map((level) => ({ value: level, label: level }))}
              />
            </Field>
            <Field label="Notice period">
              <Select
                value={form.notice_period}
                onChange={(e) => setField("notice_period", e.target.value)}
                placeholder="Select notice period"
                options={NOTICE_PERIODS.map((period) => ({ value: period, label: period }))}
              />
            </Field>
            <Field label="Remote preference">
              <Select
                value={form.remote_preference}
                onChange={(e) => setField("remote_preference", e.target.value)}
                placeholder="Select remote preference"
                options={[
                  { value: "remote", label: "Remote" },
                  { value: "hybrid", label: "Hybrid" },
                  { value: "onsite", label: "On-site" },
                  { value: "open", label: "Open to all" },
                ]}
              />
            </Field>
            <Field label="Salary preference">
              <Input value={form.salary_preference} onChange={(e) => setField("salary_preference", e.target.value)} placeholder="e.g. 6-9 LPA" />
            </Field>
            <Field label="Work authorization">
              <Select
                value={form.work_authorization}
                onChange={(e) => setField("work_authorization", e.target.value)}
                placeholder="Select work authorization"
                options={WORK_AUTHORIZATIONS.map((auth) => ({ value: auth, label: auth }))}
              />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Target roles" hint="Press Enter to add a role.">
                <TagInput value={form.preferred_roles} onChange={(value) => setField("preferred_roles", value)} />
              </Field>
            </div>
            <div className="sm:col-span-2">
              <Field label="Preferred locations" hint="Press Enter to add a location.">
                <TagInput value={form.preferred_locations} onChange={(value) => setField("preferred_locations", value)} />
              </Field>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Links">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="LinkedIn URL" error={errors.linkedin_url}>
              <Input value={form.linkedin_url} onChange={(e) => setField("linkedin_url", e.target.value)} placeholder="https://linkedin.com/in/..." invalid={!!errors.linkedin_url} />
            </Field>
            <Field label="GitHub URL" error={errors.github_url}>
              <Input value={form.github_url} onChange={(e) => setField("github_url", e.target.value)} placeholder="https://github.com/..." invalid={!!errors.github_url} />
            </Field>
            <Field label="Portfolio URL" error={errors.portfolio_url}>
              <Input value={form.portfolio_url} onChange={(e) => setField("portfolio_url", e.target.value)} placeholder="https://..." invalid={!!errors.portfolio_url} />
            </Field>
          </div>
        </SectionCard>

        <SectionCard title="Education">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Degree">
              <Input value={form.degree} onChange={(e) => setField("degree", e.target.value)} placeholder="e.g. B.E. Computer Science" />
            </Field>
            <Field label="University">
              <Input value={form.university} onChange={(e) => setField("university", e.target.value)} />
            </Field>
            <Field label="Graduation year" error={errors.graduation_year}>
              <Input type="number" value={form.graduation_year} onChange={(e) => setField("graduation_year", e.target.value)} placeholder="e.g. 2027" invalid={!!errors.graduation_year} />
            </Field>
            <Field label="CGPA / Percentage">
              <Input value={form.cgpa} onChange={(e) => setField("cgpa", e.target.value)} placeholder="e.g. 8.2 / 10" />
            </Field>
          </div>
        </SectionCard>

        <SectionCard title="Skills">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Programming languages">
              <TagInput value={form.skills_programming} onChange={(value) => setField("skills_programming", value)} placeholder="e.g. Python, Java" />
            </Field>
            <Field label="Frameworks">
              <TagInput value={form.skills_frameworks} onChange={(value) => setField("skills_frameworks", value)} placeholder="e.g. React, FastAPI" />
            </Field>
            <Field label="Databases">
              <TagInput value={form.skills_databases} onChange={(value) => setField("skills_databases", value)} placeholder="e.g. PostgreSQL, MongoDB" />
            </Field>
            <Field label="Dev tools">
              <TagInput value={form.skills_tools} onChange={(value) => setField("skills_tools", value)} placeholder="e.g. Docker, Git, VS Code" />
            </Field>
            <Field label="Other skills">
              <TagInput value={form.skills_other} onChange={(value) => setField("skills_other", value)} placeholder="e.g. Teamwork, Communication" />
            </Field>
          </div>
        </SectionCard>

        <SectionCard
          title="Projects"
          description="Academic or personal projects that showcase your skills."
        >
          <div className="space-y-4">
            {form.projects.map((project, index) => (
              <div key={index} className="rounded border border-slate-200 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Name" error={errors[`projects.${index}.name`]} required>
                    <Input value={project.name} onChange={(e) => updateItem("projects", index, { name: e.target.value })} invalid={!!errors[`projects.${index}.name`]} />
                  </Field>
                  <Field label="URL">
                    <Input value={project.url} onChange={(e) => updateItem("projects", index, { url: e.target.value })} placeholder="https://..." />
                  </Field>
                  <div className="sm:col-span-2">
                    <Field label="Technologies">
                      <TagInput value={project.technologies} onChange={(value) => updateItem("projects", index, { technologies: value })} />
                    </Field>
                  </div>
                  <div className="sm:col-span-2">
                    <Field label="Description">
                      <TextArea value={project.description} onChange={(e) => updateItem("projects", index, { description: e.target.value })} />
                    </Field>
                  </div>
                </div>
                <button type="button" onClick={() => removeItem("projects", index)} className="mt-2 text-xs font-medium text-red-600 hover:text-red-700">
                  Remove project
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => addItem("projects", EMPTY_PROJECT)}
              className="rounded border border-dashed border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:border-slate-400 hover:text-slate-800"
            >
              + Add project
            </button>
          </div>
        </SectionCard>

        <SectionCard title="Internships & Experience">
          <div className="space-y-4">
            {form.internships.map((item, index) => (
              <div key={index} className="rounded border border-slate-200 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Company" error={errors[`internships.${index}.company`]} required>
                    <Input value={item.company} onChange={(e) => updateItem("internships", index, { company: e.target.value })} invalid={!!errors[`internships.${index}.company`]} />
                  </Field>
                  <Field label="Role">
                    <Input value={item.role} onChange={(e) => updateItem("internships", index, { role: e.target.value })} />
                  </Field>
                  <Field label="Duration">
                    <Input value={item.duration} onChange={(e) => updateItem("internships", index, { duration: e.target.value })} placeholder="e.g. 6 months" />
                  </Field>
                  <Field label="Technologies">
                    <TagInput value={item.technologies} onChange={(value) => updateItem("internships", index, { technologies: value })} />
                  </Field>
                  <div className="sm:col-span-2">
                    <Field label="Description">
                      <TextArea value={item.description} onChange={(e) => updateItem("internships", index, { description: e.target.value })} />
                    </Field>
                  </div>
                </div>
                <button type="button" onClick={() => removeItem("internships", index)} className="mt-2 text-xs font-medium text-red-600 hover:text-red-700">
                  Remove experience
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => addItem("internships", EMPTY_INTERNSHIP)}
              className="rounded border border-dashed border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:border-slate-400 hover:text-slate-800"
            >
              + Add experience
            </button>
          </div>
        </SectionCard>

        <SectionCard title="Certifications">
          <div className="space-y-4">
            {form.certifications.map((cert, index) => (
              <div key={index} className="rounded border border-slate-200 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Name" error={errors[`certifications.${index}.name`]} required>
                    <Input value={cert.name} onChange={(e) => updateItem("certifications", index, { name: e.target.value })} invalid={!!errors[`certifications.${index}.name`]} />
                  </Field>
                  <Field label="Issuer">
                    <Input value={cert.issuer} onChange={(e) => updateItem("certifications", index, { issuer: e.target.value })} />
                  </Field>
                  <Field label="Date">
                    <Input value={cert.date} onChange={(e) => updateItem("certifications", index, { date: e.target.value })} placeholder="e.g. Jun 2026" />
                  </Field>
                  <Field label="Credential URL">
                    <Input value={cert.credential_url} onChange={(e) => updateItem("certifications", index, { credential_url: e.target.value })} placeholder="https://..." />
                  </Field>
                </div>
                <button type="button" onClick={() => removeItem("certifications", index)} className="mt-2 text-xs font-medium text-red-600 hover:text-red-700">
                  Remove certification
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => addItem("certifications", EMPTY_CERT)}
              className="rounded border border-dashed border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:border-slate-400 hover:text-slate-800"
            >
              + Add certification
            </button>
          </div>
        </SectionCard>

        {notice && (
          <div className={`rounded border px-4 py-3 text-sm ${notice.type === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
            {notice.text}
          </div>
        )}

        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded bg-slate-900 px-6 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {saving ? "Saving…" : profile ? "Save Changes" : "Create Profile"}
          </button>
        </div>
      </div>
    </div>
  );
}