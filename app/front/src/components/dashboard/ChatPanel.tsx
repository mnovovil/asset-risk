import { useId, useMemo, useState, type FormEvent } from "react";

import type { ChatResponse, ChatSource } from "@/api/client";
import { answerParts, elapsedLabel, useAnalystChat, type ChatTurn } from "@/lib/analyst";
import { joinList } from "@/lib/format";

const MAX_QUESTION_CHARS = 2000; // ChatRequest's limit

interface ChatPanelProps {
  runId: string;
  /** Whether the server has the analyst turned on. When it hasn't, there's no panel. */
  enabled: boolean;
  /** The run's row numbers, so only real assets become links. */
  rowNums: ReadonlySet<number>;
  onSelect: (rowNum: number) => void;
}

export function ChatPanel({ runId, enabled, rowNums, onSelect }: ChatPanelProps) {
  if (!enabled) return null;
  return <Chat runId={runId} rowNums={rowNums} onSelect={onSelect} />;
}

function Chat({ runId, rowNums, onSelect }: Omit<ChatPanelProps, "enabled">) {
  const chat = useAnalystChat(runId);
  const [question, setQuestion] = useState("");
  const inputId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || chat.pending !== null) return;
    chat.ask(question);
    setQuestion("");
  };

  return (
    <section className="panel chat-panel" aria-labelledby="chat-heading">
      <h2 id="chat-heading">Ask the analyst</h2>
      <p className="panel-note">
        Claude answers from this run's results, through Anthropic's API, so the results it reads
        leave this machine. A question takes a few seconds. "Verified" means every number matches a
        result the analyst used, not that its reasoning is right.
      </p>
      {chat.turns.length > 0 && (
        <ol className="chat-turns">
          {chat.turns.map((turn, index) => (
            <Turn key={index} turn={turn} rowNums={rowNums} onSelect={onSelect} />
          ))}
        </ol>
      )}
      {chat.pending !== null && (
        <div className="chat-pending" role="status">
          <p>
            <strong>{chat.pending}</strong>
          </p>
          <p className="muted">
            Thinking… <span aria-label="elapsed time">{elapsedLabel(chat.elapsed)}</span>
          </p>
          <button type="button" className="button" onClick={chat.cancel}>
            Cancel
          </button>
        </div>
      )}
      <form className="chat-form" onSubmit={submit}>
        <label htmlFor={inputId}>Question</label>
        <textarea
          id={inputId}
          value={question}
          maxLength={MAX_QUESTION_CHARS}
          rows={2}
          placeholder="Which assets have the highest flood loss under ssp585 in 2050?"
          onChange={(event) => setQuestion(event.target.value)}
        />
        <div className="chat-actions">
          <button
            type="submit"
            className="button button-primary"
            disabled={chat.pending !== null || !question.trim()}
          >
            Ask
          </button>
          {chat.turns.length > 0 && chat.pending === null && (
            <button type="button" className="link-button" onClick={chat.clear}>
              Clear the chat
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

interface TurnProps {
  turn: ChatTurn;
  rowNums: ReadonlySet<number>;
  onSelect: (rowNum: number) => void;
}

function Turn({ turn, rowNums, onSelect }: TurnProps) {
  return (
    <li className="chat-turn">
      <p className="chat-question">
        <strong>{turn.question}</strong>
      </p>
      {turn.response && <Answer response={turn.response} rowNums={rowNums} onSelect={onSelect} />}
      {turn.error && (
        <p className="notice notice-error" role="alert">
          {turn.error}
        </p>
      )}
      {turn.cancelled && (
        <p className="muted">
          Cancelled. The analyst may still be finishing this question, so the next one can wait.
        </p>
      )}
    </li>
  );
}

function Answer({
  response,
  rowNums,
  onSelect,
}: {
  response: ChatResponse;
  rowNums: ReadonlySet<number>;
  onSelect: (rowNum: number) => void;
}) {
  const parts = useMemo(() => answerParts(response.answer, rowNums), [response.answer, rowNums]);
  return (
    <>
      <p className="chat-answer">
        {parts.map((part, index) =>
          "rowNum" in part ? (
            <button
              key={index}
              type="button"
              className="link-button"
              onClick={() => onSelect(part.rowNum)}
            >
              {part.text}
            </button>
          ) : (
            <span key={index}>{part.text}</span>
          ),
        )}
      </p>
      {response.verified ? (
        <p className="chat-verified">Figures verified against the results below.</p>
      ) : (
        <p className="notice notice-warning">
          <strong>Unverified figures:</strong> {joinList(response.unverified_numbers)}. These don't
          match the results the analyst cited. Check them before relying on them.
        </p>
      )}
      {response.sources.length > 0 && (
        <details className="chat-sources">
          <summary>
            {response.sources.length === 1 ? "1 source" : `${response.sources.length} sources`}
          </summary>
          <ul>
            {response.sources.map((source) => (
              <Source key={source.n} source={source} />
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function Source({ source }: { source: ChatSource }) {
  return (
    <li>
      <details>
        <summary>
          #{source.n} {source.tool}
        </summary>
        <p className="muted">Asked for</p>
        <pre className="chat-json">{JSON.stringify(source.args, null, 2)}</pre>
        <p className="muted">The run returned</p>
        <pre className="chat-json">{JSON.stringify(source.result, null, 2)}</pre>
      </details>
    </li>
  );
}
