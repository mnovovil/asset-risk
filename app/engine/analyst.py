"""The portfolio analyst: Claude answers a question about one run by calling read-only tools.

The model never sees the database. It replies with one JSON object at a time, either a tool call
or an answer, and every number in the answer is checked in code against the tool results it cites.
An answer whose numbers don't all match is returned with verified false and the unmatched numbers,
after one chance to correct it.

The model is reached through ModelClient, so tests use a fake one: AnthropicClient asks Claude over
the Anthropic API. Only one question is asked at a time, under this module's own lock: never
physrisk's, which the pipeline holds for minutes. The lock also keeps spend to one question's calls.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Protocol

import anthropic

from engine import analyst_tools
from engine.store import Run

PROMPT_PATH = Path(__file__).parent / "data" / "analyst_prompt.md"
# Earlier turns kept in the prompt, and how much of each, so a long chat can't crowd out the rules.
MAX_HISTORY = 6
MAX_HISTORY_CHARS = 2000
# How much of an unusable reply is quoted back to the model when asking it to correct it.
MAX_QUOTED_REPLY = 500
# Each reply is one short JSON object, but thinking counts toward max_tokens too.
MAX_TOKENS = 16000
# How hard the model thinks before each reply. Each call picks one tool or writes one short answer
# from results it's given, which low effort handles: measure with pytest -m anthropic before
# raising it, since every level up costs more per question.
EFFORT = "low"
# Models that accept server-side fallbacks, where a refused request is rerun on a model the API
# picks by the refusal's category. Others are sent without them.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
}

_lock = threading.Lock()


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


class AnthropicClient:
    """Claude, over the Anthropic API, with one user message per call and only the text returned.

    The SDK reads the key from $ANTHROPIC_API_KEY (or an `ant auth login` profile), never from
    .asset-risk.json, whose contents end up in Terraform state. Thinking stays on, since current
    models reject turning it off: EFFORT keeps it short. The reply's text blocks are joined and
    thinking blocks dropped; _parse still checks every reply, so nothing here decides what's valid.
    """

    def __init__(self, model: str, timeout_s: float, sdk: anthropic.Anthropic | None = None):
        self.model = model
        self._timeout_s = timeout_s
        self._sdk = sdk or anthropic.Anthropic(timeout=timeout_s, max_retries=2)
        # Tokens billed across every call this client has made, for measuring cost per question.
        self.input_tokens = 0
        self.output_tokens = 0

    def _has_credentials(self) -> bool:
        sdk = self._sdk
        return bool(sdk.api_key or sdk.auth_token or getattr(sdk, "credentials", None))

    def chat(self, prompt: str) -> str:
        if not self._has_credentials():
            raise AnalystUnavailable(
                "The analyst has no Anthropic API key. Set ANTHROPIC_API_KEY and restart."
            )
        request = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            # One user message: the prompt holds the rules, the run and the transcript.
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": EFFORT},
        }
        if self.model in FALLBACK_MODELS:
            request |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self._sdk.beta.messages.create(**request)
        except anthropic.APITimeoutError as e:
            raise AnalystTimeout(
                f"The model took longer than {self._timeout_s:g} seconds to reply."
            ) from e
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise AnalystUnavailable(
                "The Anthropic API rejected the analyst's key. Check ANTHROPIC_API_KEY."
            ) from e
        except anthropic.NotFoundError as e:
            raise AnalystUnavailable(
                f"The Anthropic API has no model named {self.model}. Check analyst_model."
            ) from e
        except anthropic.RateLimitError as e:
            wait = e.response.headers.get("retry-after")
            raise AnalystUnavailable(
                "The Anthropic API's rate or spend limit was reached. Try again "
                + (f"in {wait} seconds." if wait else "in a minute.")
            ) from e
        except anthropic.APIStatusError as e:
            if e.status_code == 402 or "credit balance" in str(e.message).lower():
                raise AnalystUnavailable(
                    "The analyst's API credits have run out. Max plan credits refresh each "
                    "billing cycle, or buy credits in the Claude Console."
                ) from e
            raise AnalystUnavailable(
                f"The Anthropic API returned an error ({e.status_code})."
            ) from e
        except anthropic.APIConnectionError as e:
            raise AnalystUnavailable("The Anthropic API can't be reached.") from e
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.input_tokens += usage.input_tokens or 0
            self.output_tokens += usage.output_tokens or 0
        if response.stop_reason == "refusal":
            raise AnalystOutputError("The model declined to answer this question.")
        return "".join(block.text for block in response.content if block.type == "text")


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
