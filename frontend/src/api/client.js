const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function extractDetail(body) {
  if (!body) return "Request failed.";
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    return body.detail
      .map((item) => `${item.loc?.slice(1).join(".") || "value"}: ${item.msg}`)
      .join(" · ");
  }
  return "Request failed.";
}

async function parse(response) {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(extractDetail(body));
  }
  return body;
}

export async function apiGet(path) {
  const response = await fetch(`${API_URL}${path}`);
  return parse(response);
}

export async function apiSend(method, path, payload) {
  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse(response);
}

export async function apiUpload(path, formData) {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    body: formData,
  });
  return parse(response);
}

export async function apiDelete(path) {
  const response = await fetch(`${API_URL}${path}`, { method: "DELETE" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(extractDetail(body));
  }
}

export function formatBytes(bytes) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}