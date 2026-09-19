import polars as pl

from marimo_kpiten import ai

FRAME = pl.DataFrame(
    {
        "name": [f"P{i:05d}" for i in range(50)],  # too many values to be listed
        "state": ["purchase", "done"] * 25,
        "amount": [float(i) for i in range(50)],
    }
).lazy()
PROVIDER = ai.Provider("local", "Local (fake)", "fake", False)


def scripted(*replies):
    """A model that gives the replies in turn, and keeps what it was asked."""
    calls = []

    def complete(provider, system, messages):
        calls.append(messages[:])
        return replies[len(calls) - 1]

    complete.calls = calls
    return complete


def test_the_model_sees_the_columns_and_few_values_never_a_row():
    text = ai.describe(FRAME, send_values=True)
    assert "- amount : Float64" in text
    assert "'done', 'purchase'" in text  # a column with few values : listed
    assert "P00001" not in text  # 50 values : not listed, and no row


def test_no_value_at_all_when_they_are_not_to_be_sent():
    text = ai.describe(FRAME, send_values=False)
    assert "state : String" in text
    assert "purchase" not in text


def test_the_code_of_the_model_runs_in_the_sandbox():
    reply = (
        "Rows per state.\n```python\n"
        'd_next = d.group_by("state").agg(pl.len().alias("n")).sort("state")\n```'
    )
    answer = ai.ask(PROVIDER, FRAME, "", [], "count by state", scripted(reply))
    assert answer.error is None
    assert answer.table.to_dicts() == [
        {"state": "done", "n": 25},
        {"state": "purchase", "n": 25},
    ]
    assert answer.text == "Rows per state."


def test_a_forbidden_code_is_told_to_the_model_which_fixes_it(tmp_path):
    secret = tmp_path / "all.parquet"
    pl.DataFrame({"x": [1]}).write_parquet(secret)
    bad = f"```python\nd_next = d.sql(\"SELECT * FROM read_parquet('{secret}')\")\n```"
    good = '```python\nd_next = d.select(pl.col("amount").sum())\n```'
    model = scripted(bad, good)
    answer = ai.ask(PROVIDER, FRAME, "", [], "total", model)
    assert answer.table["amount"][0] == sum(range(50))
    assert "forbidden call: sql" in model.calls[1][-1]["content"]


def test_a_code_that_stays_wrong_ends_with_the_error():
    bad = '```python\nd_next = d.select(pl.col("nope"))\n```'
    answer = ai.ask(PROVIDER, FRAME, "", [], "?", scripted(bad, bad))
    assert answer.table is None
    assert answer.error and "nope" in answer.error


def test_an_answer_without_code_is_text():
    answer = ai.ask(PROVIDER, FRAME, "", [], "hi", scripted("It holds orders."))
    assert answer.text == "It holds orders." and answer.code is None
    assert [m["role"] for m in answer.exchange] == ["user", "assistant"]


def test_the_rows_of_an_answer_are_capped():
    big = pl.DataFrame({"i": range(ai.MAX_ROWS * 3)}).lazy()
    reply = "```python\nd_next = d.select(pl.col('i'))\n```"
    assert ai.ask(PROVIDER, big, "", [], "all", scripted(reply)).table.height == (
        ai.MAX_ROWS
    )


def test_a_provider_is_listed_when_it_is_configured(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "LOCAL_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert ai.providers() == {}
    monkeypatch.setenv("LOCAL_LLM_MODEL", "qwen")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    found = ai.providers()
    assert set(found) == {"anthropic", "local"}
    assert found["anthropic"].leaves_machine and not found["local"].leaves_machine


def test_claude_is_called_with_the_system_prompt_and_its_text_is_returned(monkeypatch):
    import anthropic

    seen = {}

    class Block:
        type = "text"
        text = "Hello"

    class Client:
        def __init__(self, api_key, timeout):
            seen["key"] = api_key

        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                seen.update(kwargs)
                return type("Reply", (), {"content": [Block()]})()

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    claude = ai.Provider("anthropic", "Claude", "claude-x", True)
    text = ai.complete(claude, "SYSTEM", [{"role": "user", "content": "hi"}])
    assert text == "Hello"
    assert seen["system"] == "SYSTEM" and seen["model"] == "claude-x"
    assert seen["messages"] == [{"role": "user", "content": "hi"}]
    assert seen["key"] == "sk-test"


def test_a_refused_call_comes_back_with_the_allowed_names_that_look_like_it():
    typo = '```python\nd_next = d.with_column(pl.col("amount").alias("a"))\n```'
    good = '```python\nd_next = d.with_columns(pl.col("amount").alias("a"))\n```'
    model = scripted(typo, good)
    answer = ai.ask(PROVIDER, FRAME, "", [], "copy", model)
    assert answer.error is None and answer.table.height == 50
    assert "Did you mean : with_columns" in model.calls[1][-1]["content"]
    assert ai.hint("ValueError : forbidden call: read_parquet") == ""
