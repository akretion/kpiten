"""The AI models the fronts may call, and the call itself.

Two providers, each one offered only when configured (`bi/.env`, see `.env.example`) :
Claude (`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`) and a local model behind an
OpenAI-compatible api (`LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`) : with it nothing leaves
the machine. What is sent is decided by the caller (`kpiten_core.anonymize`).
"""

from dataclasses import dataclass

import requests

from kpiten_core import env

TIMEOUT = 120  # seconds to wait for the model


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
    """Claude when it is configured, else the local model, else None."""
    found = providers()
    return found.get("anthropic") or found.get("local")


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
    reply = requests.post(
        f"{url}/chat/completions",
        json={
            "model": provider.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
        },
        timeout=TIMEOUT,
    )
    reply.raise_for_status()
    return reply.json()["choices"][0]["message"]["content"]
