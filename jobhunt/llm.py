"""Thin wrapper around the Claude API for structured (Pydantic) outputs."""
from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class RefusalError(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env / .env
    return _client


def structured(cfg: dict, system: str, prompt: str, schema: type[T], max_tokens: int = 16000) -> T:
    """One Claude call returning a validated `schema` instance.

    The system prompt is cached, so put stable content (master resume, rules) there
    and per-job content (the JD) in `prompt`.
    """
    response = client().beta.messages.parse(
        model=cfg["claude"]["model"],
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": cfg["claude"]["effort"]},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise RefusalError(getattr(response.stop_details, "explanation", None) or "refused")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError(f"Incomplete response (stop_reason={response.stop_reason})")
    return response.parsed_output
