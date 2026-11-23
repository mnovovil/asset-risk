import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, askAnalyst, type ChatMessage, type ChatResponse } from "@/api/client";

/** One question and what came of it. */
export interface ChatTurn {
  question: string;
  response?: ChatResponse;
  error?: string;
  cancelled?: boolean;
}

/** A piece of an answer: plain text, or a row the dashboard can open. */
export type AnswerPart = { text: string } | { text: string; rowNum: number };

// The analyst names assets as "row 12", as its prompt asks.
const ROW_MENTION = /\brow\s+(\d+)\b/gi;
// Earlier turns sent with a question. The server keeps only the last few, and caps the list.
const MAX_HISTORY_TURNS = 5;
const STORAGE_PREFIX = "asset-risk:chat:";

/** The answered turns, oldest first, as the messages the API takes as history. */
export function historyFrom(turns: ChatTurn[]): ChatMessage[] {
  return turns
    .filter((turn) => turn.response)
    .slice(-MAX_HISTORY_TURNS)
    .flatMap((turn) => [
      { role: "user" as const, content: turn.question },
      { role: "assistant" as const, content: turn.response?.answer ?? "" },
    ]);
}

/** Split an answer so each "row N" that names an asset in the run can be a link. */
export function answerParts(answer: string, rowNums: ReadonlySet<number>): AnswerPart[] {
  const parts: AnswerPart[] = [];
  let last = 0;
  for (const match of answer.matchAll(ROW_MENTION)) {
    const rowNum = Number(match[1]);
    if (!rowNums.has(rowNum)) continue;
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: answer.slice(last, start) });
    parts.push({ text: match[0], rowNum });
    last = start + match[0].length;
  }
  if (last < answer.length) parts.push({ text: answer.slice(last) });
  return parts;
}

/** Minutes and seconds, as 0:07 or 3:12. */
export function elapsedLabel(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

// The chat is kept in this tab's session storage, so a refresh doesn't lose a slow answer. Storage
// can be missing or full, and the chat works without it.
function loadTurns(runId: string): ChatTurn[] {
  try {
    const stored = sessionStorage.getItem(STORAGE_PREFIX + runId);
    const turns: unknown = stored ? JSON.parse(stored) : [];
    return Array.isArray(turns) ? (turns as ChatTurn[]) : [];
  } catch {
    return [];
  }
}

function saveTurns(runId: string, turns: ChatTurn[]) {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + runId, JSON.stringify(turns));
  } catch {
    // Only a convenience.
  }
}

export interface AnalystChat {
  turns: ChatTurn[];
  /** The question being answered, or null. */
  pending: string | null;
  /** Seconds since the pending question was sent. */
  elapsed: number;
  ask: (question: string) => void;
  cancel: () => void;
  clear: () => void;
}

export function useAnalystChat(runId: string): AnalystChat {
  const [turns, setTurns] = useState<ChatTurn[]>(() => loadTurns(runId));
  const [pending, setPending] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => saveTurns(runId, turns), [runId, turns]);

  useEffect(() => {
    if (pending === null) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed((Date.now() - started) / 1000), 1000);
    return () => clearInterval(timer);
  }, [pending]);

  // Leaving the dashboard stops waiting for an answer.
  useEffect(() => () => controller.current?.abort(), []);

  const ask = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || controller.current) return;
      const current = new AbortController();
      controller.current = current;
      setPending(trimmed);
      const done = (turn: ChatTurn) => {
        if (controller.current === current) controller.current = null;
        setPending(null);
        setTurns((previous) => [...previous, turn]);
      };
      askAnalyst(runId, { question: trimmed, history: historyFrom(turns) }, current.signal)
        .then((response) => done({ question: trimmed, response }))
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") {
            done({ question: trimmed, cancelled: true });
          } else {
            const message =
              error instanceof ApiError ? error.message : "The analyst couldn't answer.";
            done({ question: trimmed, error: message });
          }
        });
    },
    [runId, turns],
  );

  const cancel = useCallback(() => controller.current?.abort(), []);
  const clear = useCallback(() => setTurns([]), []);

  return { turns, pending, elapsed, ask, cancel, clear };
}
