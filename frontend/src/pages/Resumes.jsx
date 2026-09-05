import { useRef, useState } from "react";
import { apiDelete, apiSend, apiUpload, formatBytes } from "../api/client.js";
import { useAppData } from "../context/AppDataContext.jsx";
import PageHeader from "../components/PageHeader.jsx";
import SectionCard from "../components/SectionCard.jsx";
import Field from "../components/form/Field.jsx";
import Input from "../components/form/Input.jsx";

const ALLOWED_EXTENSIONS = [".pdf", ".doc", ".docx", ".txt", ".md", ".rtf"];
const MAX_SIZE_MB = 10;

function validateUpload({ name, file }) {
  if (!file) return "Choose a file to upload.";
  const ext = file.name.toLowerCase().split(".").pop();
  if (!ALLOWED_EXTENSIONS.includes(`.${ext}`)) {
    return `File type .${ext} is not allowed. Allowed: PDF, DOC, DOCX, TXT, MD, RTF.`;
  }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    return `File is larger than ${MAX_SIZE_MB} MB.`;
  }
  if (!name.trim()) return "Give the resume a name.";
  return null;
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function Resumes() {
  const { resumes, reloadResumes } = useAppData();
  const [form, setForm] = useState({ name: "", target_role: "", version: "", is_active: true, file: null });
  const [formError, setFormError] = useState(null);
  const [formNotice, setFormNotice] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [busyId, setBusyId] = useState(null);
  const replaceRefs = useRef({});

  function resetForm() {
    setForm({ name: "", target_role: "", version: "", is_active: true, file: null });
    setFormError(null);
  }

  async function handleUpload() {
    setFormError(null);
    setFormNotice(null);
    const error = validateUpload(form);
    if (error) {
      setFormError(error);
      return;
    }
    const payload = new FormData();
    payload.append("name", form.name.trim());
    payload.append("target_role", form.target_role.trim());
    payload.append("version", form.version.trim());
    payload.append("is_active", String(form.is_active));
    payload.append("file", form.file);
    setUploading(true);
    try {
      await apiUpload("/resumes", payload);
      await reloadResumes();
      resetForm();
      setFormNotice({ type: "success", text: "Resume uploaded." });
    } catch (err) {
      setFormNotice({ type: "error", text: err.message });
    } finally {
      setUploading(false);
    }
  }

  async function setActive(resume) {
    setBusyId(resume.id);
    try {
      await apiSend("PUT", `/resumes/${resume.id}`, { is_active: true });
      await reloadResumes();
    } catch (err) {
      setFormNotice({ type: "error", text: err.message });
    } finally {
      setBusyId(null);
    }
  }

  async function saveRename(resume) {
    setBusyId(resume.id);
    try {
      await apiSend("PUT", `/resumes/${resume.id}`, { name: renameValue.trim() });
      await reloadResumes();
      setEditingId(null);
    } catch (err) {
      setFormNotice({ type: "error", text: err.message });
    } finally {
      setBusyId(null);
    }
  }

  async function replaceFile(resume, file) {
    if (!file) return;
    const error = validateUpload({ name: resume.name, file });
    if (error) {
      setFormNotice({ type: "error", text: error });
      return;
    }
    setBusyId(resume.id);
    const payload = new FormData();
    payload.append("file", file);
    try {
      await apiUpload(`/resumes/${resume.id}/file`, payload);
      await reloadResumes();
      setFormNotice({ type: "success", text: "Resume file replaced." });
    } catch (err) {
      setFormNotice({ type: "error", text: err.message });
    } finally {
      setBusyId(null);
    }
  }

  async function deleteResume(resume) {
    if (!window.confirm(`Delete "${resume.name}" and its file?`)) return;
    setBusyId(resume.id);
    try {
      await apiDelete(`/resumes/${resume.id}`);
      await reloadResumes();
      setFormNotice({ type: "success", text: "Resume deleted." });
    } catch (err) {
      setFormNotice({ type: "error", text: err.message });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <PageHeader title="Resumes" description="Upload, rename, replace and switch between multiple resume versions." />

      <SectionCard title="Upload a resume">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Resume name" required>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Full Stack Resume" />
          </Field>
          <Field label="Target role">
            <Input value={form.target_role} onChange={(e) => setForm({ ...form, target_role: e.target.value })} placeholder="e.g. Full Stack Developer" />
          </Field>
          <Field label="Version">
            <Input value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} placeholder="e.g. v2.1" />
          </Field>
          <Field label="File" required hint="PDF, DOC, DOCX, TXT, MD or RTF · up to 10 MB">
            <input
              type="file"
              accept=".pdf,.doc,.docx,.txt,.md,.rtf"
              onChange={(e) => setForm({ ...form, file: e.target.files[0] || null })}
              className="block w-full text-sm text-slate-500 file:mr-3 file:rounded file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
            />
          </Field>
        </div>
        <label className="mt-4 flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            className="h-4 w-4 rounded border-slate-300 accent-slate-900"
          />
          Set as active now
        </label>
        {formError && <p className="mt-3 text-sm text-red-600">{formError}</p>}
        <button
          type="button"
          onClick={handleUpload}
          disabled={uploading}
          className="mt-4 rounded bg-slate-900 px-6 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload Resume"}
        </button>
      </SectionCard>

      {formNotice && (
        <div className={`mt-6 rounded border px-4 py-3 text-sm ${formNotice.type === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
          {formNotice.text}
        </div>
      )}

      <div className="mt-6 space-y-4">
        {resumes.length === 0 && (
          <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
            No resumes yet. Upload your first resume above.
          </p>
        )}
        {resumes.map((resume) => (
          <div key={resume.id} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-slate-900">
                    {editingId === resume.id ? (
                      <span className="inline-flex items-center gap-2">
                        <Input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} className="w-56" />
                        <button onClick={() => saveRename(resume)} className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800">
                          Save
                        </button>
                        <button onClick={() => setEditingId(null)} className="text-xs text-slate-500 hover:text-slate-700">
                          Cancel
                        </button>
                      </span>
                    ) : (
                      resume.name
                    )}
                  </h3>
                  {resume.is_active && (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">Active</span>
                  )}
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {resume.target_role || "No target role"} · {resume.version || "no version"}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  {resume.file_name} · {formatBytes(resume.file_size)} · {resume.content_type} · Updated {formatDate(resume.updated_at)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {!resume.is_active && (
                  <button onClick={() => setActive(resume)} disabled={busyId === resume.id} className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400 disabled:opacity-50">
                    Activate
                  </button>
                )}
                <button
                  onClick={() => {
                    setEditingId(resume.id);
                    setRenameValue(resume.name);
                  }}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400"
                >
                  Rename
                </button>
                <button
                  onClick={() => replaceRefs.current[resume.id]?.click()}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-400"
                >
                  Replace file
                </button>
                <input
                  ref={(el) => (replaceRefs.current[resume.id] = el)}
                  type="file"
                  accept=".pdf,.doc,.docx,.txt,.md,.rtf"
                  className="hidden"
                  onChange={(e) => replaceFile(resume, e.target.files[0] || null)}
                />
                <button onClick={() => deleteResume(resume)} disabled={busyId === resume.id} className="rounded border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:border-red-300 disabled:opacity-50">
                  Delete
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}