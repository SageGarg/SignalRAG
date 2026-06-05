/**
 * api.js — Centralized API service layer for the SignalRAG frontend.
 * All calls to the Flask backend go through this module.
 * The base URL is read from the .env file (VITE_API_BASE_URL) so it
 * never has to be hard-coded anywhere else.
 */

const BASE_URL = window.__ENV__?.VITE_API_BASE_URL || "http://localhost:5000";

/**
 * Generic fetch wrapper that handles JSON encoding / decoding.
 */
async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`API error ${response.status}: ${error}`);
  }
  return response.json();
}

// ── NCHRP ────────────────────────────────────────────────────────────────────

export async function askNchrp(question, email) {
  return request("/nchrp_bp/ask", {
    method: "POST",
    body: JSON.stringify({ question, email }),
  });
}

export async function askNchrpSql(question, email) {
  return request("/nchrp_bp/ask_sql", {
    method: "POST",
    body: JSON.stringify({ question, email }),
  });
}

// ── SignalVerse ───────────────────────────────────────────────────────────────

export async function askSignalverse(question) {
  return request("/ask", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

// ── BDIB ─────────────────────────────────────────────────────────────────────

export async function askBdib(question) {
  return request("/bdib_bp/ask", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}
