"""The portfolio analyst: a local model answers a question about one run by calling read-only tools.

The model never sees the database. It replies with one JSON object at a time, either a tool call
or an answer, and every number in the answer is checked in code against the tool results it cites.
An answer whose numbers don't all match is returned with verified false and the unmatched numbers,
after one chance to correct it.

The model is reached through ModelClient, so tests use a fake one. Only one question is asked at a
time, under this module's own lock: never physrisk's, which the pipeline holds for minutes.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Protocol

import httpx
import ollama

from engine import analyst_tools
from engine.store import Run

PROMPT_PATH = Path(__file__).parent / "data" / "analyst_prompt.md"
# Qwen's advice for qwen3 with thinking off, the default model. Lower makes it repeat itself.
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20}
# Earlier turns kept in the prompt, and how much of each, so a long chat can't crowd out the rules.
MAX_HISTORY = 6
MAX_HISTORY_CHARS = 2000
# How much of an unusable reply is quoted back to the model when asking it to correct it.
MAX_QUOTED_REPLY = 500

_lock = threading.Lock()

# What a reply may be, for Ollama to hold the model to: one tool call or one answer, so it stops at
# the object's end instead of writing more. Without it, a small model goes on to write further
# calls and made-up TOOL RESULTs, which cost a minute per call on a CPU. _parse still checks each
# reply, so this only shapes the output and never decides what's valid.
REPLY_FORMAT = {
    "anyOf": [
        {
            "type": "object",
            "properties": {"tool": {"enum": list(analyst_tools.TOOLS)}, "args": {"type": "object"}},
            "required": ["tool", "args"],
        },
        {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["answer", "sources"],
        },
    ]
}


class AnalystError(Exception):
    """A question the analyst couldn't answer. The message is readable, for the API's detail."""


class AnalystBusy(AnalystError):
    """Another question is being answered."""


class AnalystUnavailable(AnalystError):
    """The model server can't be reached, or doesn't have the model."""


class AnalystTimeout(AnalystError):
    """One call to the model took longer than its timeout."""


class AnalystOutputError(AnalystError):
    """The model's replies couldn't be used, even after a correction."""


class ModelClient(Protocol):
    def chat(self, prompt: str) -> str:
        """Send the whole prompt as a single user message and return the reply's content."""


class OllamaClient:
    """A model on Ollama, with thinking off, every CPU thread, and one JSON object per reply.

    Thinking is off for every model: on a CPU, reasoning costs hundreds of tokens per call, and
    Ollama rejects think=True for a model that can't think. A reasoning model that writes a
    <think> block anyway has it dropped by extract_json. The thread count is this machine's, which
    is the model server's in the compose stack: Ollama's own default leaves half the cores idle.
    """

    def __init__(self, url: str, model: str, timeout_s: float):
        self.model = model
        self._client = ollama.Client(host=url, timeout=timeout_s)
        self._timeout_s = timeout_s

    def chat(self, prompt: str) -> str:
        try:
            response = self._client.chat(
                model=self.model,
                # Everything in one user message, which every model handles, R1 included.
                messages=[{"role": "user", "content": prompt}],
                think=False,
                format=REPLY_FORMAT,
                options={**SAMPLING, "num_thread": os.cpu_count() or 1},
            )
        except httpx.TimeoutException as e:
            raise AnalystTimeout(
                f"The model took longer than {self._timeout_s:g} seconds to reply."
            ) from e
        except ConnectionError as e:  # what ollama raises for httpx.ConnectError
            raise AnalystUnavailable("The analyst's model server can't be reached.") from e
        except ollama.ResponseError as e:
            if e.status_code == 404:
                raise AnalystUnavailable(
                    f"The model server doesn't have {self.model}. Pull it with "
                    f"`ollama pull {self.model}`, or restart with script/start.sh."
                ) from e
            raise AnalystUnavailable(f"The model server returned an error: {e.error}") from e
        return response.message.content or ""


@dataclass(frozen=True)
class ToolCall:
    number: int  # n in TOOL RESULT #n, from 1
    tool: str
    args: dict
    result: dict


@dataclass(frozen=True)
class Answer:
    text: str
    verified: bool  # every number in text matched a cited result, which says nothing of reasoning
    unmatched: list[str]  # the numbers, as written, that didn't
    sources: list[ToolCall]  # the results the answer cites
    tool_calls: list[ToolCall] = field(default_factory=list)  # every call made for the question


def ask(
    run: Run,
    question: str,
    client: ModelClient,
    max_calls: int,
    history: list[dict] | None = None,
) -> Answer:
    """Answer one question about a completed run. Raises AnalystBusy if one is already running.

    history: earlier turns, as {"role": "user" | "assistant", "content": text}, oldest first.
    """
    if not _lock.acquire(blocking=False):
        raise AnalystBusy("The analyst is answering another question. Try again when it's done.")
    try:
        return _Conversation(run, question, client, max_calls, history or []).answer()
    finally:
        _lock.release()


# --- The prompt --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _RunContext:
    label: str
    pairs: list[tuple[str, int | None]]
    shared_hazards: list[str]


def _run_context(run: Run) -> _RunContext:
    with run.connect() as con:
        (label,) = con.execute("SELECT source_name FROM runs").fetchone()
        pairs = con.execute(
            "SELECT DISTINCT scenario, year FROM assessment_pairs "
            "ORDER BY scenario, year NULLS FIRST"
        ).fetchall()
        shared = con.execute("SELECT hazard FROM v_shared_hazards ORDER BY 1").fetchall()
    return _RunContext(label or "unnamed", pairs, [h for (h,) in shared])


def _describe_pair(scenario: str, year: int | None) -> str:
    return f"{scenario} (year null)" if year is None else f"{scenario} {year}"


def describe_tools() -> str:
    """The registry as the prompt lists it: a signature, a description and each argument."""
    lines = []
    for tool in analyst_tools.TOOLS.values():
        properties = tool.parameters["properties"]
        required = tool.parameters.get("required", [])
        params = []
        for name, schema in properties.items():
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            param = f"{name}: {' | '.join(types)}"
            if name not in required:
                param += f" = {json.dumps(schema.get('default'))}"
            params.append(param)
        lines.append(f"- {tool.name}({', '.join(params)}): {tool.description}")
        lines += [f"    - {name}: {schema['description']}" for name, schema in properties.items()]
    return "\n".join(lines)


def _history(history: list[dict]) -> str:
    turns = []
    for message in history[-MAX_HISTORY:]:
        who = "User" if message.get("role") == "user" else "Analyst"
        content = str(message.get("content", ""))[:MAX_HISTORY_CHARS]
        turns.append(f"{who}: {content}")
    return "# Earlier in this conversation\n\n" + "\n\n".join(turns) + "\n\n" if turns else ""


def render_prompt(
    context: _RunContext,
    question: str,
    max_calls: int,
    history: list[dict] | None = None,
    transcript: list[str] | None = None,
) -> str:
    """Fill in the prompt template. A placeholder it doesn't fill raises KeyError."""
    transcript = transcript or []
    return Template(PROMPT_PATH.read_text()).substitute(
        run_label=json.dumps(context.label),  # quoted: it's the uploaded file's name
        pairs=", ".join(_describe_pair(s, y) for s, y in context.pairs) or "nothing",
        shared_hazards=", ".join(context.shared_hazards) or "none",
        tools=describe_tools(),
        max_calls=max_calls,
        history=_history(history or []),
        question=question.strip(),
        transcript="".join(f"\n{entry}\n" for entry in transcript),
    )


# --- Reading replies ---------------------------------------------------------------------------

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def extract_json(reply: str) -> dict | None:
    """The outermost JSON object in a reply, ignoring any text or code fence around it."""
    text = _THINK.sub("", reply)
    decoder = json.JSONDecoder()
    for start in (i for i, char in enumerate(text) if char == "{"):
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


@dataclass(frozen=True)
class _ToolRequest:
    tool: str
    args: dict


@dataclass(frozen=True)
class _AnswerReply:
    text: str
    sources: list[int]


def _parse(reply: str) -> _ToolRequest | _AnswerReply | str:
    """What the reply asks for, or a message saying why it can't be used."""
    value = extract_json(reply)
    if value is None:
        return "Your reply had no JSON object."
    if "answer" in value:
        sources = value.get("sources", [])
        if not isinstance(value["answer"], str) or not value["answer"].strip():
            return '"answer" must be a non-empty string.'
        if not isinstance(sources, list) or not all(
            isinstance(n, int) and not isinstance(n, bool) for n in sources
        ):
            return '"sources" must be a list of TOOL RESULT numbers, like [1, 2].'
        return _AnswerReply(value["answer"].strip(), sources)
    if "tool" in value:
        args = value.get("args", {})
        if not isinstance(value["tool"], str) or not isinstance(args, dict | None):
            return '"tool" must be a tool name and "args" an object.'
        if value["tool"] not in analyst_tools.TOOLS:
            return (
                f"There's no tool named {value['tool']!r}. "
                f"The tools are: {', '.join(analyst_tools.TOOLS)}."
            )
        return _ToolRequest(value["tool"], args or {})
    return 'Your JSON object had neither "tool" nor "answer".'


# --- The grounding check -----------------------------------------------------------------------

# Scenario names like ssp585, SSP5-8.5 or RCP 4.5 are labels, not figures.
_SCENARIO_NAME = re.compile(r"\b(?:ssp|rcp)\s?\d(?:[-.]?\d(?:\.\d)?)?\b", re.IGNORECASE)
_CITATION = re.compile(r"#\s?\d+")
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
# A number not inside a word or another number: "A99" and "V1-30" are zone names. The suffix is a
# percent sign or a scale, as in "1.23%", "€645M" or "2.5 billion".
_NUMBER = re.compile(
    r"(?<![\w.,-])-?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?"
    r"(?:\s?(?P<suffix>%|percent\b|thousand\b|million\b|billion\b|bn\b|[kKMB]\b))?"
)
_SCALES = {"thousand": 1e3, "k": 1e3, "K": 1e3, "million": 1e6, "M": 1e6}
_SCALES |= {"billion": 1e9, "bn": 1e9, "B": 1e9}


def _leaves(value, numbers: list[float], strings: list[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _leaves(item, numbers, strings)
    elif isinstance(value, list):
        for item in value:
            _leaves(item, numbers, strings)
    elif isinstance(value, bool):
        pass
    elif isinstance(value, int | float):
        if math.isfinite(value):
            numbers.append(abs(float(value)))
    elif isinstance(value, str):
        strings.append(value)


def _matches(shown: float, decimals: int, suffix: str | None, values: list[float]) -> bool:
    """Whether a number as written rounds from one of the values, at the precision it shows."""
    if suffix in ("%", "percent"):
        targets = [shown]
        scale = 1.0
        candidates = [(v * 100) for v in values] + values  # a fraction shown as %, or a % already
    else:
        scale = _SCALES.get(suffix, 1.0)
        targets = [shown * scale]
        candidates = values
    tolerance = 0.5 * 10**-decimals * scale * (1 + 1e-9) + 1e-12
    return any(abs(t - c) <= tolerance for t in targets for c in candidates)


def unmatched_numbers(text: str, results: list[dict], allowed: list[float] = ()) -> list[str]:
    """The numbers in text that no value in results rounds to, as written.

    Matches allow a fraction shown as a %, the precision shown, thousands separators and scales,
    and ignore sign, since "0.04 lower" and -0.04 are the same figure. Numbers inside words,
    scenario names, citations like #2 and list markers aren't figures. Text that also appears as a
    string in a result, such as an asset_id or a zone, is taken out first. allowed holds numbers
    that need no result, like the run's years.
    """
    numbers: list[float] = [abs(float(a)) for a in allowed]
    strings: list[str] = []
    for result in results:
        _leaves(result, numbers, strings)
    for string in sorted({s for s in strings if len(s) >= 2}, key=len, reverse=True):
        text = text.replace(string, " ")
    for pattern in (_SCENARIO_NAME, _CITATION, _LIST_MARKER):
        text = pattern.sub(" ", text)
    missing = []
    for match in _NUMBER.finditer(text):
        whole = match["int"].replace(",", "")
        frac = match["frac"] or ""
        shown = float(whole + frac)
        decimals = max(len(frac) - 1, 0)
        if not _matches(shown, decimals, match["suffix"], numbers):
            missing.append(match.group(0).strip())
    return missing


# --- The loop ----------------------------------------------------------------------------------


class _Conversation:
    def __init__(self, run, question, client, max_calls, history):
        self.run = run
        self.question = question
        self.client = client
        self.max_calls = max_calls
        self.history = history
        self.context = _run_context(run)
        self.calls: list[ToolCall] = []
        self.transcript: list[str] = []

    def _reply(self) -> str:
        left = self.max_calls - len(self.calls)
        status = (
            f"You have {left} tool call{'s' if left != 1 else ''} left."
            if left
            else "You have no tool calls left: answer now from the results above."
        )
        prompt = render_prompt(
            self.context, self.question, self.max_calls, self.history, self.transcript + [status]
        )
        return self.client.chat(prompt)

    def _allowed(self) -> list[float]:
        # The run's years are in the prompt, and a number in the question ("the top 5") is the
        # user's own.
        years = [y for _, y in self.context.pairs if y is not None]
        asked = [float(m["int"].replace(",", "")) for m in _NUMBER.finditer(self.question)]
        return years + asked

    def answer(self) -> Answer:
        corrected = False  # the last reply was unusable and has had its correction
        out_of_calls = False  # the model asked for a tool after its last call, and was told
        regrounded = False  # the answer's numbers didn't match once, and it was told
        while True:
            reply = self._reply()
            parsed = _parse(reply)

            if isinstance(parsed, str):
                if corrected:
                    raise AnalystOutputError(f"The model's reply couldn't be used: {parsed}")
                corrected = True
                self.transcript.append(
                    f"YOU: {reply.strip()[:MAX_QUOTED_REPLY]}\n"
                    f"CORRECTION: {parsed} Reply with exactly one JSON object, as described above."
                )
                continue
            corrected = False

            if isinstance(parsed, _ToolRequest):
                said = json.dumps({"tool": parsed.tool, "args": parsed.args})
                if len(self.calls) >= self.max_calls:
                    if out_of_calls:
                        raise AnalystOutputError(
                            f"The model didn't answer within {self.max_calls} tool calls."
                        )
                    out_of_calls = True
                    self.transcript.append(
                        f"YOU: {said}\nCORRECTION: You've used all {self.max_calls} tool calls. "
                        'Reply with {"answer": ..., "sources": [...]} now.'
                    )
                    continue
                result = analyst_tools.call(self.run, parsed.tool, parsed.args)
                call = ToolCall(len(self.calls) + 1, parsed.tool, parsed.args, result)
                self.calls.append(call)
                self.transcript.append(
                    f"YOU: {said}\nTOOL RESULT #{call.number} ({call.tool}): {json.dumps(result)}"
                )
                continue

            cited = [c for c in self.calls if c.number in set(parsed.sources)]
            unmatched = unmatched_numbers(parsed.text, [c.result for c in cited], self._allowed())
            if not unmatched or regrounded:
                return Answer(parsed.text, not unmatched, unmatched, cited, list(self.calls))
            regrounded = True
            self.transcript.append(
                "YOU: "
                + json.dumps({"answer": parsed.text, "sources": parsed.sources})
                + "\nCORRECTION: These numbers aren't in the TOOL RESULTs listed in sources: "
                + ", ".join(unmatched)
                + ". Answer again using only numbers from the results, and list every result "
                "you use in sources. If you need a figure no result has, call a tool for it."
            )
