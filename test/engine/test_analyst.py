import json
import threading
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from engine import analyst, analyst_tools, assess
from engine.analyst import (
    AnalystBusy,
    AnalystOutputError,
    AnalystTimeout,
    AnalystUnavailable,
    AnthropicClient,
    ask,
    extract_json,
    unmatched_numbers,
)

# Asset 1 totals 3% and asset 2 7% under ssp585, a mean of 5%. ssp245 has only Wind.
IMPACTS = [
    (1, "Wind", "ssp585", 2050, 0.01),
    (1, "Fire", "ssp585", 2050, 0.02),
    (2, "Wind", "ssp585", 2050, 0.03),
    (2, "Fire", "ssp585", 2050, 0.04),
    (1, "Wind", "ssp245", 2050, 0.05),
    (2, "Wind", "ssp245", 2050, 0.07),
]
PAIRS = [("ssp245", 2050), ("ssp585", 2050)]
PORTFOLIO = {"tool": "query_portfolio", "args": {"scenario": "ssp585", "year": 2050}}


@pytest.fixture
def run(make_run, asset_row):
    run = make_run([asset_row(1), asset_row(2)], IMPACTS, PAIRS)
    with run.connect() as con:
        con.execute("UPDATE runs SET source_name = ?", ["madrid offices.csv"])
    return run


class FakeClient:
    """Replies in order, and keeps every prompt it was sent."""

    def __init__(self, *replies):
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        self.prompts: list[str] = []

    def chat(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def answer(text, *sources):
    return {"answer": text, "sources": list(sources)}


def test_a_tool_call_then_an_answer(run):
    client = FakeClient(
        "<think>I should look at the portfolio.</think>\n```json\n"
        + json.dumps(PORTFOLIO)
        + "\n```",
        answer("Under ssp585 in 2050 the mean annual loss is 5.00% across 2 assets.", 1),
    )
    result = ask(run, "What's the mean loss under ssp585?", client, max_calls=4)
    assert result.verified and result.unmatched == []
    assert [(c.number, c.tool) for c in result.sources] == [(1, "query_portfolio")]
    assert result.sources[0].result["mean_total_aal"] == pytest.approx(0.05)
    assert result.tool_calls == result.sources
    assert "TOOL RESULT #1 (query_portfolio): {" in client.prompts[1]
    assert "You have 3 tool calls left." in client.prompts[1]


def test_malformed_json_gets_one_correction_then_fails(run):
    client = FakeClient("The answer is about 5%.", "{not json")
    with pytest.raises(AnalystOutputError, match="no JSON object"):
        ask(run, "How bad is it?", client, max_calls=4)
    assert "CORRECTION: Your reply had no JSON object." in client.prompts[1]
    assert "The answer is about 5%." in client.prompts[1]


def test_a_correction_can_recover(run):
    client = FakeClient('{"thought": "hmm"}', answer("I can't tell from this run."))
    result = ask(run, "Will it flood?", client, max_calls=4)
    assert (result.text, result.verified) == ("I can't tell from this run.", True)
    assert 'neither "tool" nor "answer"' in client.prompts[1]


def test_an_unknown_tool_gets_a_correction_listing_the_tools(run):
    client = FakeClient({"tool": "run_sql", "args": {}}, {"tool": "run_sql", "args": {}})
    with pytest.raises(AnalystOutputError, match="no tool named 'run_sql'"):
        ask(run, "Anything", client, max_calls=4)
    assert ", ".join(analyst_tools.TOOLS) in client.prompts[1]


def test_an_invalid_argument_is_a_tool_result_the_model_can_read(run):
    client = FakeClient(
        {"tool": "query_portfolio", "args": {"scenario": "ssp126", "year": 2050}},
        PORTFOLIO,
        answer("The mean is 5%.", 2),
    )
    result = ask(run, "ssp126?", client, max_calls=4)
    assert result.tool_calls[0].result == {
        "error": "This run wasn't assessed for ssp126 2050. "
        "It was assessed for: ssp245 2050, ssp585 2050."
    }
    assert result.verified


def test_after_the_last_call_the_model_is_asked_for_the_answer(run):
    client = FakeClient(PORTFOLIO, PORTFOLIO, answer("The mean is 5%.", 1))
    result = ask(run, "Mean?", client, max_calls=1)
    assert len(result.tool_calls) == 1
    assert "no tool calls left" in client.prompts[1]
    assert "You've used all 1 tool calls" in client.prompts[2]
    assert result.verified


def test_a_model_that_never_answers_fails(run):
    client = FakeClient(PORTFOLIO, PORTFOLIO, PORTFOLIO)
    with pytest.raises(AnalystOutputError, match="didn't answer within 1 tool calls"):
        ask(run, "Mean?", client, max_calls=1)


def test_an_invented_number_gets_one_retry_then_is_unverified(run):
    invented = answer("The mean is 5%, and 12.5% for wind.", 1)
    client = FakeClient(PORTFOLIO, invented, invented)
    result = ask(run, "Mean?", client, max_calls=4)
    assert (result.verified, result.unmatched) == (False, ["12.5%"])
    assert "aren't in the TOOL RESULTs listed in sources: 12.5%" in client.prompts[2]


def test_the_retry_can_fix_the_answer(run):
    client = FakeClient(
        PORTFOLIO, answer("The mean is 6%.", 1), answer("The mean is 5%; wind's is 2%.", 1)
    )
    result = ask(run, "Mean?", client, max_calls=4)
    assert (result.text, result.verified) == ("The mean is 5%; wind's is 2%.", True)


def test_numbers_must_come_from_cited_results(run):
    # The figure is in result #1, but the answer cites nothing.
    client = FakeClient(PORTFOLIO, answer("The mean is 5%."), answer("The mean is 5%."))
    result = ask(run, "Mean?", client, max_calls=4)
    assert (result.verified, result.unmatched, result.sources) == (False, ["5%"], [])


def test_the_runs_years_and_the_questions_numbers_need_no_result(run):
    reply = answer("I can only show the top 3 for 2050, not 2099.")
    result = ask(run, "Show the top 3 assets", FakeClient(reply, reply), max_calls=4)
    assert result.unmatched == ["2099"]


@pytest.mark.parametrize(
    ("text", "results"),
    [
        ("1.23%", [{"aal": 0.0123}]),
        ("about 1.2%", [{"aal": 0.0123}]),  # rounded to what's shown
        ("roughly 1%", [{"aal": 0.0123}]),
        ("0.0123", [{"aal": 0.0123}]),
        ("1.23 percent", [{"aal": 0.0123}]),
        ("1,234 assets", [{"assets": 1234}]),
        ("€1.2M", [{"expected_loss_total": 1234567.0}]),
        ("2.5 billion", [{"valued_total": 2.5e9}]),
        ("0.04 lower", [{"difference_b_minus_a": -0.04}]),
        ("-4%", [{"difference_b_minus_a": -0.04}]),
        ("row 12 (asset b-77)", [{"row_num": 12, "asset_id": "b-77"}]),
        ("Zone A99 and V1-30", [{"fema_zone": "A99"}]),
        ("ssp585 and SSP5-8.5 and SSP2-4.5", []),
        ("See TOOL RESULT #3.", []),
        ("1. Row 2 is first\n2. Row 1 is second", [{"row_num": 1}, {"row_num": 2}]),
        ("in 2050", [{"year": 2050}]),
        ("0%", [{"mean_aal": 0.0}]),
        ("0.000024%", [{"mean_aal": 2.3908e-07}]),
        ("It has no results.", []),
    ],
)
def test_grounding_accepts_a_number_as_shown(text, results):
    assert unmatched_numbers(text, results) == []


@pytest.mark.parametrize(
    ("text", "results", "missing"),
    [
        ("1.24%", [{"aal": 0.0123}], ["1.24%"]),
        ("2%", [{"aal": 0.0123}], ["2%"]),
        ("12 assets", [{"assets": 1234}], ["12"]),
        ("1,235", [{"assets": 1234}], ["1,235"]),
        ("€2M", [{"expected_loss_total": 1234567.0}], ["2M"]),
        ("true counts as 1", [{"covered": True}], ["1"]),
        ("5% and 7%", [{"mean": 0.05}], ["7%"]),
    ],
)
def test_grounding_rejects_a_number_no_result_has(text, results, missing):
    assert unmatched_numbers(text, results) == missing


def test_the_lock_is_the_analysts_own_and_not_blocking(run):
    assert analyst._lock is not assess._physrisk_lock
    with analyst._lock:
        with pytest.raises(AnalystBusy, match="another question"):
            ask(run, "Mean?", FakeClient(answer("No.")), max_calls=4)
    assert ask(run, "Mean?", FakeClient(answer("No.")), max_calls=4).verified


def test_a_failure_releases_the_lock(run):
    with pytest.raises(AnalystOutputError):
        ask(run, "?", FakeClient("x", "y"), max_calls=4)
    assert analyst._lock.acquire(blocking=False)
    analyst._lock.release()


def test_a_second_question_waits_for_nothing(run):
    started, release = threading.Event(), threading.Event()

    class Slow(FakeClient):
        def chat(self, prompt):
            started.set()
            release.wait(5)
            return super().chat(prompt)

    thread = threading.Thread(target=ask, args=(run, "?", Slow(answer("No.")), 4))
    thread.start()
    started.wait(5)
    with pytest.raises(AnalystBusy):
        ask(run, "?", FakeClient(answer("No.")), max_calls=4)
    release.set()
    thread.join(5)


def test_the_prompt_lists_every_tool_and_the_run(run):
    client = FakeClient(answer("No."))
    history = [
        {"role": "user", "content": "Which asset is worst?"},
        {"role": "assistant", "content": "Row 2."},
    ]
    ask(run, "And under ssp245?", client, max_calls=3, history=history)
    prompt = client.prompts[0]
    for tool in analyst_tools.TOOLS.values():
        assert f"- {tool.name}(" in prompt
        assert tool.description in prompt
        for name, schema in tool.parameters["properties"].items():
            assert f"    - {name}: {schema['description']}" in prompt
    assert "top_assets(scenario: string, year: integer | null, hazard: string | null = null, " in (
        prompt
    )
    assert '"madrid offices.csv"' in prompt
    assert "Assessed for: ssp245 2050, ssp585 2050" in prompt
    assert "every scenario and year: Wind" in prompt
    assert "at most 3 tools" in prompt
    assert "User: Which asset is worst?\n\nAnalyst: Row 2." in prompt
    assert prompt.rstrip().endswith("You have 3 tool calls left.")
    assert "And under ssp245?" in prompt
    assert "$" not in prompt  # every placeholder filled


def test_long_history_is_trimmed(run):
    client = FakeClient(answer("No."))
    history = [{"role": "user", "content": f"q{i} " + "x" * 5000} for i in range(10)]
    ask(run, "?", client, max_calls=1, history=history)
    assert "q3 " not in client.prompts[0] and "q4 " in client.prompts[0]
    assert "x" * (analyst.MAX_HISTORY_CHARS + 1) not in client.prompts[0]


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"tool": "list_exclusions"}', {"tool": "list_exclusions"}),
        ('Sure! {"answer": "x", "sources": []} Hope that helps.', {"answer": "x", "sources": []}),
        (
            '```json\n{"tool": "get_asset", "args": {"row_num": 2}}\n```',
            {"tool": "get_asset", "args": {"row_num": 2}},
        ),
        ('<think>{"answer": "draft"}</think>{"answer": "final"}', {"answer": "final"}),
        ("no braces at all", None),
        ("{broken", None),
    ],
)
def test_extract_json_takes_the_outermost_object(reply, expected):
    assert extract_json(reply) == expected


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(kind, status, message="error", headers=None):
    response = httpx2.Response(status, request=_REQUEST, headers=headers or {})
    return kind(message, response=response, body=None)


class _FakeSDK:
    """Stands in for anthropic.Anthropic: records each request and returns or raises."""

    def __init__(self, reply=None, error=None, api_key="sk-test"):
        self.api_key = api_key
        self.auth_token = None
        self.credentials = None
        self.sent = []
        self._reply = reply
        self._error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.sent.append(kwargs)
        if self._error:
            raise self._error
        return self._reply


def _reply(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def test_anthropic_client_sends_one_user_message_at_low_effort_with_fallbacks():
    sdk = _FakeSDK(_reply(SimpleNamespace(type="thinking", thinking=""), _text('{"answer": "ok"')))
    sdk._reply.content.append(_text(', "sources": []}'))
    client = AnthropicClient("claude-opus-5-5", 120, sdk=sdk)
    assert client.chat("the prompt") == '{"answer": "ok", "sources": []}'
    assert sdk.sent == [
        {
            "model": "claude-opus-5-5",
            "max_tokens": analyst.MAX_TOKENS,
            "messages": [{"role": "user", "content": "the prompt"}],
            "output_config": {"effort": "low"},
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
    ]
    # Current models reject sampling settings and disabled thinking with a 400.
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(sdk.sent[0])


def test_anthropic_client_sends_no_fallbacks_to_a_model_without_them():
    sdk = _FakeSDK(_reply(_text("{}")))
    AnthropicClient("claude-haiku-5-5", 120, sdk=sdk).chat("p")
    assert "fallbacks" not in sdk.sent[0] and "betas" not in sdk.sent[0]


def test_anthropic_client_without_a_key_asks_for_one_and_sends_nothing():
    sdk = _FakeSDK(api_key=None)
    with pytest.raises(AnalystUnavailable, match="ANTHROPIC_API_KEY"):
        AnthropicClient("claude-opus-5-5", 120, sdk=sdk).chat("p")
    assert sdk.sent == []


def test_anthropic_client_reads_the_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    client = AnthropicClient("claude-opus-5-5", 120)
    assert client._sdk.api_key == "sk-from-env"
    assert client._sdk.timeout == 120


def test_a_refusal_is_an_output_error():
    sdk = _FakeSDK(_reply(stop_reason="refusal"))
    with pytest.raises(AnalystOutputError, match="declined"):
        AnthropicClient("claude-opus-5-5", 120, sdk=sdk).chat("p")


def test_a_truncated_reply_is_returned_for_parse_to_correct(run):
    replies = iter(['{"answer": "cut o', '{"answer": "ok", "sources": []}'])
    sdk = _FakeSDK()
    sdk.beta.messages.create = lambda **kw: _reply(_text(next(replies)), stop_reason="max_tokens")
    answer = ask(run, "hi", AnthropicClient("claude-opus-5-5", 120, sdk=sdk), max_calls=2)
    assert answer.text == "ok"


@pytest.mark.parametrize(
    ("error", "kind", "message"),
    [
        (anthropic.APITimeoutError(request=_REQUEST), AnalystTimeout, "longer than 120 seconds"),
        (anthropic.APIConnectionError(request=_REQUEST), AnalystUnavailable, "can't be reached"),
        (_status_error(anthropic.AuthenticationError, 401), AnalystUnavailable, "rejected"),
        (_status_error(anthropic.PermissionDeniedError, 403), AnalystUnavailable, "rejected"),
        (_status_error(anthropic.NotFoundError, 404), AnalystUnavailable, "no model named"),
        (
            _status_error(anthropic.RateLimitError, 429, headers={"retry-after": "30"}),
            AnalystUnavailable,
            "in 30 seconds",
        ),
        (_status_error(anthropic.RateLimitError, 429), AnalystUnavailable, "in a minute"),
        (
            _status_error(
                anthropic.BadRequestError,
                400,
                "Your credit balance is too low to access the Anthropic API.",
            ),
            AnalystUnavailable,
            "credits have run out",
        ),
        (_status_error(anthropic.PaymentRequiredError, 402), AnalystUnavailable, "credits"),
        (_status_error(anthropic.InternalServerError, 500), AnalystUnavailable, r"error \(500\)"),
    ],
)
def test_anthropic_client_errors_are_readable(error, kind, message):
    sdk = _FakeSDK(error=error)
    with pytest.raises(kind, match=message):
        AnthropicClient("claude-opus-5-5", 120, sdk=sdk).chat("p")
