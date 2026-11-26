"""Ask Claude three questions about a fixture run (opt-in: pytest -m anthropic).

Needs $ANTHROPIC_API_KEY, and spends API credits on every question. $ASSET_RISK_ANALYST_MODEL picks
the model (default claude-opus-5-5). Each answer must be verified by the grounding check as it
stands: if a model can't pass, that's the finding, not a reason to loosen it. Run with -s to see
each question's time, tokens and answer.
"""

import os
import time

import pytest

from engine.analyst import AnthropicClient, ask

pytestmark = pytest.mark.anthropic

MODEL = os.environ.get("ASSET_RISK_ANALYST_MODEL") or "claude-opus-5-5"
TIMEOUT_S = 120
MAX_CALLS = 4

# Three offices and one bad row. Row 2 has the highest loss under ssp585, and ssp245 has no fire,
# so the scenarios share only wind and river flood.
IMPACTS = [
    (row, hazard, scenario, year, round(aal * factor, 6))
    for row, losses in {
        1: {"Wind": 0.0004, "RiverineInundation": 0.0021, "Fire": 0.0003},
        2: {"Wind": 0.0019, "RiverineInundation": 0.0083, "Fire": 0.0011},
        3: {"Wind": 0.0001, "RiverineInundation": 0.0, "Fire": 0.0002},
    }.items()
    for hazard, aal in losses.items()
    for scenario, year, factor in (
        ("ssp585", 2050, 1.0),
        ("ssp245", 2050, 0.8),
        ("historical", None, 0.6),
    )
    if not (scenario == "ssp245" and hazard == "Fire")
]
PAIRS = [("historical", None), ("ssp245", 2050), ("ssp585", 2050)]

QUESTIONS = [
    ("What is the portfolio's mean annual loss under ssp585 in 2050?", "query_portfolio"),
    ("Which asset has the highest total loss under ssp585 in 2050?", "top_assets"),
    ("How does ssp585 compare with ssp245 in 2050?", "compare_scenarios"),
]


@pytest.fixture
def run(make_run, asset_row):
    assets = [
        asset_row(1),
        asset_row(2, source="assumed"),
        asset_row(3),
        asset_row(4, assessable=False, match="invalid", reason="invalid"),
    ]
    run = make_run(assets, IMPACTS, PAIRS)
    with run.connect() as con:
        con.execute("UPDATE runs SET source_name = 'offices.csv'")
    return run


@pytest.mark.parametrize(("question", "tool"), QUESTIONS)
def test_claude_answers_with_verified_figures(run, question, tool):
    client = AnthropicClient(MODEL, TIMEOUT_S)
    started = time.monotonic()
    answer = ask(run, question, client, MAX_CALLS)
    seconds = time.monotonic() - started
    print(
        f"\n{question}\n{seconds:.0f} s, {len(answer.tool_calls)} calls, "
        f"{client.input_tokens} in / {client.output_tokens} out tokens: {answer.text}"
    )
    if not answer.verified:
        print(f"Unverified: {answer.unmatched}")
    assert tool in {call.tool for call in answer.tool_calls}
    assert answer.verified, answer.unmatched
