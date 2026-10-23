const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const getFields = () => request("/api/fields");
export const getField = (id) => request(`/api/fields/${id}`);
export const generateReport = (id) =>
  request(`/api/fields/${id}/report`, { method: "POST" });
export const askQuestion = (body) =>
  request("/api/chat", { method: "POST", body: JSON.stringify(body) });
