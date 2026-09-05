import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiSend, apiUpload } from "../api/client.js";
import { useAppData } from "../context/AppDataContext.jsx";
import {
  EXPERIENCE_LEVELS,
  NOTICE_PERIODS,
  TARGET_ROLES,
  WORK_AUTHORIZATIONS,
  validateGraduationYear,
  validateProfileUrl,
} from "../constants/options.js";
import PageHeader from "../components/PageHeader.jsx";
import Field from "../components/form/Field.jsx";
import Input from "../components/form/Input.jsx";
import Select from "../components/form/Select.jsx";
import TagInput from "../components/form/TagInput.jsx";

const STEPS = [
  "Personal",
  "Professional",
  "Skills",
  "Education",
  "Projects & Experience",
  "Job Preferences",
  "Resume",
];

const locVal = (value) => (value && value.trim() ? value : null);

function PersonalStep({ form, setForm, errors, onSave, saving }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Full name" required error={errors.name}>
        <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} invalid={!!errors.name} />
      </Field>
      <Field label="Email" required error={errors.email}>
        <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} invalid={!!errors.email} />
      </Field>
      <Field label="Phone">
        <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
      </Field>
      <Field label="City">
        <Input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
      </Field>
      <Field label="State">
        <Input value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value })} />
      </Field>
      <Field label="Country">
        <Input value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} />
      </Field>
      <StepActions label="Save & Continue" onSave={onSave} saving={saving} />
    </div>
  );
}

function ProfessionalStep({ form, setForm, onSave, saving }) {
  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Experience level">
        <Select value={form.experience_level} onChange={(e) => setField("experience_level", e.target.value)} placeholder="Select experience level" options={EXPERIENCE_LEVELS.map((l) => ({ value: l, label: l }))} />
      </Field>
      <Field label="Notice period">
        <Select value={form.notice_period} onChange={(e) => setField("notice_period", e.target.value)} placeholder="Select notice period" options={NOTICE_PERIODS.map((p) => ({ value: p, label: p }))} />
      </Field>
      <Field label="Remote preference">
        <Select value={form.remote_preference} onChange={(e) => setField("remote_preference", e.target.value)} placeholder="Select remote preference" options={[
          { value: "remote", label: "Remote" },
          { value: "hybrid", label: "Hybrid" },
          { value: "onsite", label: "On-site" },
          { value: "open", label: "Open to all" },
        ]} />
      </Field>
      <Field label="Salary preference">
        <Input value={form.salary_preference} onChange={(e) => setField("salary_preference", e.target.value)} placeholder="e.g. 6-9 LPA" />
      </Field>
      <Field label="Work authorization">
        <Select value={form.work_authorization} onChange={(e) => setField("work_authorization", e.target.value)} placeholder="Select work authorization" options={WORK_AUTHORIZATIONS.map((a) => ({ value: a, label: a }))} />
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
      <StepActions label="Save & Continue" onSave={onSave} saving={saving} />
    </div>
  );
}

function SkillsStep({ form, setForm, onSave, saving }) {
  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Programming languages"><TagInput value={form.skills_programming} onChange={(v) => setField("skills_programming", v)} placeholder="e.g. Python, Java" /></Field>
      <Field label="Frameworks"><TagInput value={form.skills_frameworks} onChange={(v) => setField("skills_frameworks", v)} placeholder="e.g. React, FastAPI" /></Field>
      <Field label="Databases"><TagInput value={form.skills_databases} onChange={(v) => setField("skills_databases", v)} placeholder="e.g. PostgreSQL" /></Field>
      <Field label="Dev tools"><TagInput value={form.skills_tools} onChange={(v) => setField("skills_tools", v)} placeholder="e.g. Docker, Git" /></Field>
      <div className="sm:col-span-2">
        <Field label="Other skills"><TagInput value={form.skills_other} onChange={(v) => setField("skills_other", v)} placeholder="e.g. Communication" /></Field>
      </div>
      <StepActions label="Save & Continue" onSave={onSave} saving={saving} />
    </div>
  );
}

function EducationStep({ form, setForm, errors, onSave, saving }) {
  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Degree"><Input value={form.degree} onChange={(e) => setField("degree", e.target.value)} placeholder="e.g. B.E. Computer Science" /></Field>
      <Field label="University"><Input value={form.university} onChange={(e) => setField("university", e.target.value)} /></Field>
      <Field label="Graduation year" error={errors.graduation_year}>
        <Input type="number" value={form.graduation_year} onChange={(e) => setField("graduation_year", e.target.value)} placeholder="e.g. 2027" invalid={!!errors.graduation_year} />
      </Field>
      <Field label="CGPA / Percentage"><Input value={form.cgpa} onChange={(e) => setField("cgpa", e.target.value)} placeholder="e.g. 8.2 / 10" /></Field>
      <StepActions label="Save & Continue" onSave={onSave} saving={saving} />
    </div>
  );
}

function ExperienceStep({ form, setForm, errors, onSave, saving }) {
  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const urlError = (field) => errors[field] || null;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="LinkedIn URL" error={urlError("linkedin_url")}>
        <Input value={form.linkedin_url} onChange={(e) => setField("linkedin_url", e.target.value)} placeholder="https://linkedin.com/in/..." invalid={!!urlError("linkedin_url")} />
      </Field>
      <Field label="GitHub URL" error={urlError("github_url")}>
        <Input value={form.github_url} onChange={(e) => setField("github_url", e.target.value)} placeholder="https://github.com/..." invalid={!!urlError("github_url")} />
      </Field>
      <div className="sm:col-span-2">
        <Field label="Projects" hint="One per line using the format: Name | Description | Tech1, Tech2 | https://...">
          <textarea
            rows={4}
            value={form.projectsText}
            onChange={(e) => setField("projectsText", e.target.value)}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-100"
            placeholder={"Job Portal | Full stack job search app | React, FastAPI | https://...\nChat Bot | Support bot | Python | https://..."}
          />
        </Field>
      </div>
      <div className="sm:col-span-2">
        <Field label="Experience / Internships" hint="One per line: Company | Role | Duration | Description (optional)">
          <textarea
            rows={3}
            value={form.experienceText}
            onChange={(e) => setField("experienceText", e.target.value)}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-100"
            placeholder={"InfyWorks | SDE Intern | 6 months | Built REST APIs\nOpenSource | Contributor | ongoing | ..."}
          />
        </Field>
      </div>
      <StepActions label="Save & Continue" onSave={onSave} saving={saving} />
    </div>
  );
}

function PreferencesStep({ form, setForm, onSave, saving }) {
  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const toggle = (key, value) =>
    setForm((f) => ({
      ...f,
      [key]: f[key].includes(value) ? f[key].filter((v) => v !== value) : [...f[key], value],
    }));
  const Chip = ({ active, onClick, children }) => (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${active ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white text-slate-600 hover:border-slate-400"}`}
    >
      {children}
    </button>
  );
  return (
    <div className="grid gap-4">
      <Field label="Preferred locations" hint="Press Enter to add a location.">
        <TagInput value={form.preferred_locations} onChange={(v) => setField("preferred_locations", v)} placeholder="Type a location and press Enter" />
      </Field>
      <div>
        <span className="mb-1 block text-sm font-medium text-slate-700">Target roles</span>
        <div className="flex flex-wrap gap-2">
          {TARGET_ROLES.map((role) => (
            <Chip key={role} active={form.target_roles.includes(role)} onClick={() => toggle("target_roles", role)}>
              {role}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <span className="mb-1 block text-sm font-medium text-slate-700">Minimum match score</span>
        <div className="flex items-center gap-3">
          <input type="range" min="0" max="100" step="5" value={form.min_match_score} onChange={(e) => setField("min_match_score", e.target.value)} className="max-w-sm flex-1 accent-slate-900" />
          <span className="w-12 text-right text-sm font-semibold text-slate-900">{form.min_match_score}%</span>
        </div>
      </div>
      <StepActions label="Save & Continue" onSave={onSave} saving={saving} />
    </div>
  );
}

function ResumeStep({ form, setForm, errors, onSave, saving }) {
  const setField = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Resume name" required error={errors.name}>
        <Input value={form.name} onChange={(e) => setField("name", e.target.value)} invalid={!!errors.name} placeholder="e.g. Full Stack Resume" />
      </Field>
      <Field label="Target role">
        <Input value={form.target_role} onChange={(e) => setField("target_role", e.target.value)} placeholder="e.g. Full Stack Developer" />
      </Field>
      <div className="sm:col-span-2">
        <Field label="File" required hint="PDF, DOC, DOCX, TXT, MD or RTF · up to 10 MB" error={errors.file}>
          <input
            type="file"
            accept=".pdf,.doc,.docx,.txt,.md,.rtf"
            onChange={(e) => setField("file", e.target.files[0] || null)}
            className="block w-full text-sm text-slate-500 file:mr-3 file:rounded file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
          />
        </Field>
      </div>
      <StepActions label="Finish Setup" onSave={onSave} saving={saving} />
    </div>
  );
}

function StepActions({ label, onSave, saving }) {
  return (
    <div className="sm:col-span-2 pt-1">
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="rounded bg-slate-900 px-6 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
      >
        {saving ? "Saving…" : label}
      </button>
    </div>
  );
}

function validateEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? null : "Enter a valid email address.";
}

function validateUrl(value) {
  return validateProfileUrl(value);
}

function parseLines(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split("|").map((part) => part.trim());
      return {
        name: parts[0] || "",
        description: parts[1] || null,
        technologies: parts[2] ? parts[2].split(",").map((t) => t.trim()).filter(Boolean) : [],
        url: parts[3] ? validateUrl(parts[3]) === null ? parts[3] : parts[3] : null,
      };
    });
}

function parseExperience(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split("|").map((part) => part.trim());
      return {
        company: parts[0] || "",
        role: parts[1] || null,
        duration: parts[2] || null,
        description: parts[3] || null,
        technologies: [],
      };
    });
}

export default function Onboarding() {
  const { profile, preferences, reloadAll } = useAppData();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const [notice, setNotice] = useState(null);

  const [personal, setPersonal] = useState(() => ({ name: "", email: "", phone: "", city: "", state: "", country: "" }));
  const [professional, setProfessional] = useState(() => ({
    experience_level: "", notice_period: "", remote_preference: "", salary_preference: "",
    work_authorization: "", preferred_roles: [], preferred_locations: [],
  }));
  const [skills, setSkills] = useState(() => ({ skills_programming: [], skills_frameworks: [], skills_databases: [], skills_tools: [], skills_other: [] }));
  const [education, setEducation] = useState(() => ({ degree: "", university: "", graduation_year: "", cgpa: "" }));
  const [experience, setExperience] = useState(() => ({ linkedin_url: "", github_url: "", projectsText: "", experienceText: "" }));
  const [prefForm, setPrefForm] = useState(() => ({
    preferred_locations: [], target_roles: [], min_match_score: 60,
  }));
  const [resumeForm, setResumeForm] = useState(() => ({ name: "", target_role: "", file: null }));

  useEffect(() => {
    if (step >= 5 && preferences) {
      setPrefForm((f) => ({
        preferred_locations: f.preferred_locations.length ? f.preferred_locations : (preferences.preferred_locations || []),
        target_roles: f.target_roles.length ? f.target_roles : (preferences.target_roles || []),
        min_match_score: f.min_match_score ?? preferences.min_match_score ?? 60,
      }));
    }
  }, [step, preferences]);

  useEffect(() => {
    if (profile && step >= 0 && step <= 4) {
      const p = profile;
      if (step === 0) {
        setPersonal((f) => f.name || f.email || f.phone ? f : { name: p.name || "", email: p.email || "", phone: p.phone || "", city: p.city || "", state: p.state || "", country: p.country || "" });
      }
      if (step === 1 || step === 4) {
        setProfessional((f) => {
          if (f.preferred_roles.length || f.preferred_locations.length || f.experience_level) return f;
          return {
            experience_level: p.experience_level || "",
            notice_period: p.notice_period || "",
            remote_preference: p.remote_preference || "",
            salary_preference: p.salary_preference || "",
            work_authorization: p.work_authorization || "",
            preferred_roles: p.preferred_roles || [],
            preferred_locations: p.preferred_locations || [],
          };
        });
      }
      if (step === 2) {
        setSkills((f) => f.skills_programming.length || f.skills_frameworks.length ? f : {
          skills_programming: p.skills_programming || [],
          skills_frameworks: p.skills_frameworks || [],
          skills_databases: p.skills_databases || [],
          skills_tools: p.skills_tools || [],
          skills_other: p.skills_other || [],
        });
      }
      if (step === 3) {
        setEducation((f) => f.degree || f.graduation_year ? f : {
          degree: p.degree || "",
          university: p.university || "",
          graduation_year: p.graduation_year ? String(p.graduation_year) : "",
          cgpa: p.cgpa || "",
        });
      }
      if (step === 4 && !experience.projectsText) {
        const projectsText = (p.projects || [])
          .map((project) => [project.name, project.description, (project.technologies || []).join(", "), project.url].filter(Boolean).join(" | "))
          .join("\n");
        const experienceText = (p.internships || [])
          .map((item) => [item.company, item.role, item.duration, item.description].filter(Boolean).join(" | "))
          .join("\n");
        setExperience({
          linkedin_url: p.linkedin_url || "",
          github_url: p.github_url || "",
          projectsText,
          experienceText,
        });
      }
    }
  }, [profile, step]); // eslint-disable-line react-hooks/exhaustive-deps

  function validateStep() {
    const next = {};
    if (step === 0) {
      if (!personal.name.trim()) next.name = "Full name is required.";
      if (!personal.email.trim()) next.email = validateEmail(personal.email) || "Email is required.";
    }
    if (step === 3 && education.graduation_year) {
      const yearError = validateGraduationYear(education.graduation_year);
      if (yearError) next.graduation_year = yearError;
    }
    if (step === 4) {
      if (experience.linkedin_url) {
        const err = validateUrl(experience.linkedin_url);
        if (err) next.linkedin_url = err;
      }
      if (experience.github_url) {
        const err = validateUrl(experience.github_url);
        if (err) next.github_url = err;
      }
      parseLines(experience.projectsText).forEach((project, index) => {
        if (project.url && validateUrl(project.url)) next[`projects.${index}.url`] = validateUrl(project.url);
      });
    }
    if (step === 6) {
      if (!resumeForm.name.trim()) next.name = "Give the resume a name.";
      if (!resumeForm.file) next.file = "Choose a PDF, DOC, DOCX, TXT, MD or RTF file.";
      else {
        const ext = resumeForm.file.name.toLowerCase().split(".").pop();
        if (![".pdf", ".doc", ".docx", ".txt", ".md", ".rtf"].includes(`.${ext}`)) {
          next.file = `File type .${ext} is not allowed.`;
        } else if (resumeForm.file.size > 10 * 1024 * 1024) {
          next.file = "File is larger than 10 MB.";
        }
      }
    }
    return next;
  }

  async function handleSaveAndContinue() {
    setErrors({});
    setNotice(null);
    const nextErrors = validateStep();
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }
    setSaving(true);
    try {
      if (step === 0) {
        if (profile) {
          await apiSend("PUT", "/profile", {
            name: personal.name.trim(),
            email: personal.email.trim(),
            phone: locVal(personal.phone),
            city: locVal(personal.city),
            state: locVal(personal.state),
            country: locVal(personal.country),
          });
        } else {
          await apiSend("POST", "/profile", {
            name: personal.name.trim(),
            email: personal.email.trim(),
            phone: locVal(personal.phone),
            city: locVal(personal.city),
            state: locVal(personal.state),
            country: locVal(personal.country),
          });
        }
      } else if (step >= 1 && step <= 4) {
        const payloads = {
          1: professional,
          2: skills,
          3: { ...education, graduation_year: education.graduation_year ? Number(education.graduation_year) : null },
          4: {
            linkedin_url: locVal(experience.linkedin_url),
            github_url: locVal(experience.github_url),
            projects: parseLines(experience.projectsText).filter((p) => p.name),
            internships: parseExperience(experience.experienceText).filter((p) => p.company),
            certifications: [],
          },
        };
        await apiSend("PUT", "/profile", payloads[step]);
      } else if (step === 5) {
        await apiSend("PUT", "/preferences", {
          preferred_locations: prefForm.preferred_locations,
          target_roles: prefForm.target_roles,
          min_match_score: Number(prefForm.min_match_score),
        });
      } else if (step === 6) {
        const payload = new FormData();
        payload.append("name", resumeForm.name.trim());
        payload.append("target_role", resumeForm.target_role.trim());
        payload.append("is_active", "true");
        payload.append("file", resumeForm.file);
        await apiUpload("/resumes", payload);
        await reloadAll();
        navigate("/");
        return;
      }
      await reloadAll();
      setStep((s) => s + 1);
      setNotice(null);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Welcome" description="Set up your job-search profile in a few quick steps. You can save & continue later at any point." />

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between text-xs font-medium text-slate-500">
          <span>Step {step + 1} of {STEPS.length}</span>
          <span>{STEPS[step]}</span>
        </div>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-slate-900 transition-all"
            style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {STEPS.map((label, index) => (
            <span
              key={label}
              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                index === step
                  ? "bg-slate-900 text-white"
                  : index < step
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-slate-100 text-slate-400"
              }`}
            >
              {index + 1}. {label}
            </span>
          ))}
        </div>
      </div>

      {notice && (
        <div className={`mb-4 rounded border px-4 py-3 text-sm ${notice.type === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
          {notice.text}
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        {step === 0 && <PersonalStep form={personal} setForm={setPersonal} errors={errors} onSave={handleSaveAndContinue} saving={saving} />}
        {step === 1 && <ProfessionalStep form={professional} setForm={setProfessional} onSave={handleSaveAndContinue} saving={saving} />}
        {step === 2 && <SkillsStep form={skills} setForm={setSkills} onSave={handleSaveAndContinue} saving={saving} />}
        {step === 3 && <EducationStep form={education} setForm={setEducation} errors={errors} onSave={handleSaveAndContinue} saving={saving} />}
        {step === 4 && <ExperienceStep form={experience} setForm={setExperience} errors={errors} onSave={handleSaveAndContinue} saving={saving} />}
        {step === 5 && <PreferencesStep form={prefForm} setForm={setPrefForm} onSave={handleSaveAndContinue} saving={saving} />}
        {step === 6 && <ResumeStep form={resumeForm} setForm={setResumeForm} errors={errors} onSave={handleSaveAndContinue} saving={saving} />}
      </div>

      <div className="mt-4 flex items-center justify-between">
        {step > 0 ? (
          <button type="button" onClick={() => setStep((s) => s - 1)} className="text-sm font-medium text-slate-500 hover:text-slate-800">
            ← Back
          </button>
        ) : (
          <span />
        )}
        {step > 0 && (
          <button
            type="button"
            onClick={() => navigate("/")}
            className="text-sm font-medium text-slate-400 hover:text-slate-600"
          >
            Save & continue later
          </button>
        )}
      </div>
    </div>
  );
}