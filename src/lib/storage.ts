import type { GradeResult } from "@/lib/api";

const HISTORY_KEY = "omr_grading_history";
const ANSWER_KEYS_CACHE_KEY = "omr_answer_keys_cache";

export interface GradingSession {
  id: string;
  timestamp: string;
  answerKeyId: string;
  answerKeyName: string;
  fileCount: number;
  fileNames: string[];
  results: GradeResult[];
  averagePercentage: number;
}

// ── Grading History ──

export function getGradingHistory(): GradingSession[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveGradingSession(session: Omit<GradingSession, "id" | "timestamp" | "averagePercentage">): GradingSession {
  const history = getGradingHistory();
  const validResults = session.results.filter((r) => !r.error);
  const avg = validResults.length > 0
    ? validResults.reduce((s, r) => s + r.percentage, 0) / validResults.length
    : 0;

  const entry: GradingSession = {
    ...session,
    id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    averagePercentage: Math.round(avg * 100) / 100,
  };

  history.unshift(entry);
  // Keep max 100 sessions
  if (history.length > 100) history.length = 100;
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  return entry;
}

export function deleteGradingSession(id: string) {
  const history = getGradingHistory().filter((s) => s.id !== id);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
}

export function clearGradingHistory() {
  localStorage.removeItem(HISTORY_KEY);
}

// ── Answer Keys Cache ──

export interface CachedAnswerKey {
  id: string;
  name: string;
  form_type: string;
  question_count: number;
  cachedAt: string;
}

export function getCachedAnswerKeys(): CachedAnswerKey[] {
  try {
    const raw = localStorage.getItem(ANSWER_KEYS_CACHE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function setCachedAnswerKeys(keys: { id: string; name: string; form_type: string; question_count: number }[]) {
  const cached: CachedAnswerKey[] = keys.map((k) => ({
    ...k,
    cachedAt: new Date().toISOString(),
  }));
  localStorage.setItem(ANSWER_KEYS_CACHE_KEY, JSON.stringify(cached));
}
