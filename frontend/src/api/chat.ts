import { authFetch } from "../lib/auth";

export type RetrievalCategory =
  | "comparative"
  | "factual"
  | "indirect"
  | "relational"
  | "thematic"
  | "unknown";

export type RetrievalStrategy = "dense" | "hybrid" | "sparse";

export interface RetrievedMovie {
  movie_id: number;
  title: string;
  release_year: number | null;
  rrf_score: number;
  chunk_preview: string;
}

export interface ChatQueryResponse {
  question: string;
  retrieval_category: RetrievalCategory;
  retrieval_strategy: RetrievalStrategy;
  answer: string;
  retrieved: RetrievedMovie[];
}

async function parseError(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  const detail = data.detail;
  if (typeof detail === "string") return detail;
  return fallback;
}

export async function submitChatQuery(
  question: string,
  k = 5,
): Promise<ChatQueryResponse> {
  const res = await authFetch("/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, k, include_chunks: false }),
  });
  if (res.status === 404) {
    throw new Error("No relevant movies found. Try rephrasing your question.");
  }
  if (!res.ok) throw new Error(await parseError(res, "Query failed"));
  return res.json();
}
