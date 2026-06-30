import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import {
  submitChatQuery,
  type ChatQueryResponse,
  type RetrievalStrategy,
  type RetrievedMovie,
} from "../api/chat";

const MAX_CHARS = 250;

const EXAMPLE_QUESTIONS = [
  "What are the best sci-fi films from the 1980s?",
  "Compare Christopher Nolan's style to Denis Villeneuve's",
  "Which films deal with isolation and survival?",
  "Recommend a feel-good movie for a rainy day",
];

type ChatMessage =
  | { role: "user"; id: string; text: string }
  | { role: "assistant"; id: string; response: ChatQueryResponse };

let _msgId = 0;
const makeId = () => String(++_msgId);

const STRATEGY_BADGE: Record<RetrievalStrategy, string> = {
  dense: "border-accent/40 text-accent",
  hybrid: "border-border text-muted",
  sparse: "border-border text-muted",
};

export default function ChatPage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Redirect unauthenticated users.
  useEffect(() => {
    if (!authLoading && !user) navigate("/auth", { replace: true });
  }, [user, authLoading, navigate]);

  // Auto-scroll to the newest message / thinking indicator.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Auto-resize the textarea up to a cap.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }, [input]);

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-sm text-muted">Loading…</p>
      </div>
    );
  }
  if (!user) return null;

  const trimmed = input.trim();
  const canSend = !loading && trimmed.length > 0 && input.length <= MAX_CHARS;

  async function handleSubmit() {
    const question = input.trim();
    if (loading || !question || input.length > MAX_CHARS) return;

    setMessages((prev) => [...prev, { role: "user", id: makeId(), text: question }]);
    setInput("");
    setError(null);
    setLoading(true);

    try {
      const response = await submitChatQuery(question);
      setMessages((prev) => [...prev, { role: "assistant", id: makeId(), response }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  }

  function handleExample(question: string) {
    setInput(question);
    textareaRef.current?.focus();
  }

  const remaining = MAX_CHARS - input.length;
  const hasMessages = messages.length > 0;

  return (
    <main
      className="mx-auto flex w-full max-w-4xl flex-col px-4"
      style={{ height: "calc(100vh - 5rem)" }}
    >
      {/* Zone 1 — header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border py-3">
        <h1 className="text-sm font-semibold text-text">Movie Chat</h1>
        {hasMessages && (
          <button
            type="button"
            onClick={() => {
              setMessages([]);
              setError(null);
            }}
            className="rounded-lg px-2 py-1 text-xs text-muted transition-colors hover:text-text"
          >
            Clear
          </button>
        )}
      </div>

      {/* Zone 2 — messages */}
      <div className="min-h-0 flex-1 overflow-y-auto py-6">
        {!hasMessages && !loading ? (
          <WelcomeState onPick={handleExample} />
        ) : (
          <div className="space-y-6">
            {messages.map((msg) =>
              msg.role === "user" ? (
                <UserBubble key={msg.id} text={msg.text} />
              ) : (
                <AssistantBubble
                  key={msg.id}
                  response={msg.response}
                  onMovieClick={(id) => navigate(`/movie/${id}`)}
                />
              ),
            )}
            {loading && <ThinkingBubble />}
            {error && (
              <div className="rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-2 text-sm text-red-500">
                {error}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Zone 3 — input bar */}
      <div className="shrink-0 border-t border-border py-3">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
              rows={1}
              maxLength={MAX_CHARS}
              placeholder="Ask about movies…"
              className="max-h-32 w-full resize-none overflow-y-auto rounded-2xl border border-border bg-surface px-4 py-3 pb-6 text-sm text-text outline-none focus:border-accent disabled:opacity-50"
            />
            <span
              className={`absolute bottom-2 right-3 text-xs ${
                remaining < 10 ? "text-red-500" : "text-muted"
              }`}
            >
              {remaining}
            </span>
          </div>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!canSend}
            className="shrink-0 rounded-2xl bg-text px-4 py-3 text-sm font-medium text-bg transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
    </main>
  );
}

function WelcomeState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <h2 className="text-lg font-semibold text-text">Movie Assistant</h2>
      <p className="mt-2 max-w-md text-sm text-muted">
        Ask anything about movies — recommendations, comparisons, themes. Answers
        are grounded in the films we know about.
      </p>
      <div className="mt-6 grid w-full max-w-lg gap-2 sm:grid-cols-2">
        {EXAMPLE_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="rounded-xl border border-border bg-surface px-4 py-3 text-left text-xs text-muted transition-colors hover:border-accent/40 hover:text-text"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-text px-4 py-3">
        <p className="whitespace-pre-wrap text-sm text-bg">{text}</p>
      </div>
    </div>
  );
}

function AssistantBubble({
  response,
  onMovieClick,
}: {
  response: ChatQueryResponse;
  onMovieClick: (id: number) => void;
}) {
  return (
    <div className="max-w-3xl">
      <div className="rounded-2xl rounded-tl-sm border border-border bg-surface px-4 py-3">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-text">
          {response.answer}
        </p>
        <div className="mt-3 flex items-center gap-2 text-xs text-muted">
          <span
            className={`rounded-full border px-2 py-0.5 ${
              STRATEGY_BADGE[response.retrieval_strategy]
            }`}
          >
            {response.retrieval_strategy}
          </span>
          <span>·</span>
          <span>{response.retrieval_category}</span>
        </div>
      </div>
      {response.retrieved.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {response.retrieved.map((m) => (
            <MovieChip key={m.movie_id} movie={m} onClick={onMovieClick} />
          ))}
        </div>
      )}
    </div>
  );
}

function MovieChip({
  movie,
  onClick,
}: {
  movie: RetrievedMovie;
  onClick: (id: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick(movie.movie_id)}
      className="rounded-full border border-border bg-bg px-3 py-1 text-xs text-muted transition-colors hover:border-accent/40 hover:text-text"
    >
      {movie.title}
      {movie.release_year ? ` (${movie.release_year})` : ""}
    </button>
  );
}

function ThinkingBubble() {
  return (
    <div className="max-w-3xl">
      <div className="inline-flex items-center gap-1 rounded-2xl rounded-tl-sm border border-border bg-surface px-4 py-3">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:300ms]" />
      </div>
    </div>
  );
}
