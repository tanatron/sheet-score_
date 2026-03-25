const API_KEY = "omr_api_base_url";
const DEFAULT_URL = "http://localhost:8000";

export function getApiBaseUrl(): string {
  return localStorage.getItem(API_KEY) || DEFAULT_URL;
}

export function setApiBaseUrl(url: string) {
  localStorage.setItem(API_KEY, url.replace(/\/+$/, ""));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getApiBaseUrl();
  const res = await fetch(`${base}${path}`, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

// ── Health ──
export const checkHealth = () => request<{ status: string }>("/api/health");

// ── Answer Keys ──
export interface AnswerKeySummary {
  id: string;
  name: string;
  form_type: string;
  question_count: number;
}

export interface AnswerKeyFull {
  name: string;
  form_type: string;
  answers: Record<string, string>;
}

export const listAnswerKeys = () => request<AnswerKeySummary[]>("/api/answer-keys");

export const getAnswerKey = (id: string) => request<AnswerKeyFull>(`/api/answer-keys/${id}`);

export const deleteAnswerKey = (id: string) => request<{ deleted: string }>(`/api/answer-keys/${id}`, { method: "DELETE" });

export async function createAnswerKey(name: string, formType: string, answers: Record<string, string>) {
  const fd = new FormData();
  fd.append("name", name);
  fd.append("form_type", formType);
  fd.append("answers", JSON.stringify(answers));
  return request<AnswerKeySummary>("/api/answer-keys", { method: "POST", body: fd });
}

// ── Grading ──
export interface GradeDetail {
  given: string;
  correct: string;
  is_correct: boolean;
}

export interface GradeResult {
  result_id: string;
  score: number;
  total: number;
  percentage: number;
  details: Record<string, GradeDetail>;
  subject_code?: string;
  student_id?: string;
  image_url: string;
  filename?: string;
  error?: string;
}

export async function gradeSingle(file: File, answerKeyId: string): Promise<GradeResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("answer_key_id", answerKeyId);
  return request<GradeResult>("/api/grade/single", { method: "POST", body: fd });
}

export async function gradeBatch(files: File[], answerKeyId: string): Promise<{ batch_results: GradeResult[]; processed: number }> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  fd.append("answer_key_id", answerKeyId);
  return request<{ batch_results: GradeResult[]; processed: number }>("/api/grade/batch", { method: "POST", body: fd });
}

export async function gradeBatchDownload(files: File[], answerKeyId: string): Promise<Blob> {
  const base = getApiBaseUrl();
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  fd.append("answer_key_id", answerKeyId);
  const res = await fetch(`${base}/api/grade/batch/download`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.blob();
}

export function getResultImageUrl(imageUrl: string): string {
  return `${getApiBaseUrl()}${imageUrl}`;
}

// ── History ──
export interface HistorySessionSummary {
  id: string;
  timestamp: string;
  answerKeyId: string;
  answerKeyName: string;
  formType: "A" | "B";
  averagePercentage: number;
  fileCount: number;
}

export interface HistorySessionFull extends HistorySessionSummary {
  results: GradeResult[];
}

export const listHistory = (search: string = "") => {
  const url = search ? `/api/history?search=${encodeURIComponent(search)}` : "/api/history";
  return request<HistorySessionSummary[]>(url);
};

export const getHistoryDetails = (id: string) => request<HistorySessionFull>(`/api/history/${id}`);

export const deleteHistorySession = (id: string) => request<{ deleted: string }>(`/api/history/${id}`, { method: "DELETE" });
