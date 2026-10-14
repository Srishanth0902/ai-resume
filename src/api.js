async function request(path, options) {
  const res = await fetch(path, options);
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new Error(detail);
  }
  return body;
}

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const listCandidates = () => request("/api/candidates");
export const getCandidate = (code) => request(`/api/candidates/${code}`);
export const decide = (code, decision, note) => request(`/api/candidates/${code}/decision`, json("POST", { decision, note }));
export const setStage = (code, stage) => request(`/api/candidates/${code}/stage`, json("POST", { stage }));
export const deleteCandidate = (code) => request(`/api/candidates/${code}`, { method: "DELETE" });
export const originalUrl = (code) => `/api/candidates/${code}/original`;
export const blindPdfUrl = (code) => `/api/candidates/${code}/blind.pdf`;

export function uploadResume(file, options) {
  const form = new FormData();
  form.append("file", file);
  form.append("hide_institutions", options.hide_institutions);
  form.append("hide_education_years", options.hide_education_years);
  return request("/api/candidates", { method: "POST", body: form });
}

export function formatDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
