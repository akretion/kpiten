"""The AI models the fronts may call, and the call itself.

Two providers, each one offered only when configured (`bi/.env`, see `.env.example`) :
Claude (`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`) and a local model behind an
OpenAI-compatible api (`LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`) : with it nothing leaves
the machine. What is sent is decided by the caller (`kpiten_core.anonymize`).

Every call of the fronts goes through `complete` : the querychat of Shiny, the chat and
the step by step of marimo.
"""

from dataclasses import dataclass

import requests

from kpiten_core import env

# seconds to wait for the model : a local model on a CPU may take minutes
TIMEOUT = int(env.get("LLM_TIMEOUT", "600"))


def thinks(model: str) -> bool:
    """A model that reasons before it answers, by default (qwen3) : told not to.

    TODO : review later. It is a special case of qwen : without it, a qwen3 on a CPU
    reasons for minutes before a short answer. Measured with Ollama 0.34 : 100 s for
    « say hi », 1 s with `reasoning_effort: none` (`/no_think` in the prompt does not
    stop it). A setting per model, or a model that does not reason, would be better.
    """
    return model.lower().startswith("qwen")


@dataclass
class Provider:
    key: str
    label: str
    model: str
    leaves_machine: bool  # what is sent goes to a third party


def providers() -> dict[str, Provider]:
    """The providers that are configured, by key."""
    found = {}
    if env.get("ANTHROPIC_API_KEY"):
        model = env.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        found["anthropic"] = Provider("anthropic", f"Claude ({model})", model, True)
    if env.get("LOCAL_LLM_MODEL"):
        model = env.get("LOCAL_LLM_MODEL")
        found["local"] = Provider("local", f"Local ({model})", model, False)
    return found


def default_provider() -> Provider | None:
    """The AI of `kt.config` (`config.ai_default_provider`) when it is configured here,
    else Claude, else the local model, else None. Copy and paste is no provider of the
    api : it falls back the same way."""
    from kpiten_core import config  # the settings of Odoo, read by the front

    found = providers()
    return (
        found.get(config.ai_default_provider())
        or found.get("anthropic")
        or found.get("local")
    )


def complete(provider: Provider, system: str, messages: list[dict]) -> str:
    """The text answer of the model to a conversation."""
    if provider.key == "anthropic":
        import anthropic

        client = anthropic.Anthropic(
            api_key=env.get("ANTHROPIC_API_KEY"), timeout=TIMEOUT
        )
        reply = client.messages.create(
            model=provider.model, max_tokens=2000, system=system, messages=messages
        )
        return "".join(block.text for block in reply.content if block.type == "text")
    url = env.get("LOCAL_LLM_URL", "http://localhost:11434/v1").rstrip("/")
    body = {
        "model": provider.model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": 0,
    }
    if thinks(provider.model):
        body["reasoning_effort"] = "none"
    reply = requests.post(f"{url}/chat/completions", json=body, timeout=TIMEOUT)
    reply.raise_for_status()
    return reply.json()["choices"][0]["message"]["content"]
