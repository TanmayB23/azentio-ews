"""Shared AI plumbing: the OpenAI provider, configuration and grounding checks.

Every AI feature asks for a fixed Pydantic schema (structured outputs) and then
checks the answer against its input in code, so a model can draft and explain
but never introduce facts. Features fall back to deterministic output when no
provider is configured or a call fails.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

DEFAULT_MODEL = "gpt-4.1-mini"
T = TypeVar("T", bound=BaseModel)


class AIUnavailable(Exception):
    """The provider could not produce an answer (configuration, network, refusal or bad output)."""


class Provider(Protocol):
    name: str
    model: str

    def parse(self, system: str, content: str | list[dict], schema: type[T], max_tokens: int = 4000) -> T: ...


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import openai  # imported lazily so the app runs without the package when AI is off
        self._openai = openai
        self.model = model or os.environ.get("EWS_AI_MODEL", DEFAULT_MODEL)
        self.client = openai.OpenAI(api_key=api_key, timeout=90.0, max_retries=2)

    def parse(self, system: str, content: str | list[dict], schema: type[T], max_tokens: int = 4000) -> T:
        """content is text, or a list of chat content parts (text, image_url, file)."""
        o = self._openai
        try:
            completion = self.client.chat.completions.parse(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                response_format=schema,
                max_completion_tokens=max_tokens,
                prompt_cache_key=f"ews-{schema.__name__}",
            )
        except (o.LengthFinishReasonError, o.ContentFilterFinishReasonError) as e:
            raise AIUnavailable(f"The model stopped early ({type(e).__name__}).") from e
        except o.AuthenticationError as e:
            raise AIUnavailable("OpenAI rejected the API key (OPENAI_API_KEY).") from e
        except o.NotFoundError as e:
            raise AIUnavailable(f"Model '{self.model}' is not available to this key; set EWS_AI_MODEL.") from e
        except o.RateLimitError as e:
            raise AIUnavailable("OpenAI rate limit or quota reached; try again shortly.") from e
        except o.APIConnectionError as e:
            raise AIUnavailable("Could not reach OpenAI.") from e
        except o.BadRequestError as e:
            raise AIUnavailable(f"OpenAI could not process the request: {e.message}") from e
        except o.APIStatusError as e:
            raise AIUnavailable(f"OpenAI returned an error ({e.status_code}).") from e
        message = completion.choices[0].message
        if message.refusal:
            raise AIUnavailable(f"The model declined: {message.refusal}")
        if message.parsed is None:
            raise AIUnavailable("The model returned no usable answer.")
        return message.parsed

    def draft(self, system: str, payload: dict):
        from api.case_notes import CaseNote
        return self.parse(system, json.dumps(payload, default=str), CaseNote)


def provider_from_env() -> tuple[Provider | None, str | None]:
    """Returns (provider, reason it is disabled)."""
    if os.environ.get("EWS_AI_ENABLED", "1") == "0":
        return None, "AI drafting is turned off (EWS_AI_ENABLED=0)."
    if not os.environ.get("OPENAI_API_KEY"):
        return None, "No OPENAI_API_KEY is set; AI features fall back to rules."
    try:
        return OpenAIProvider(), None
    except ImportError:
        return None, "The openai package is not installed."


# --------------------------------------------------------------------------- grounding checks
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> set[float]:
    out = set()
    for tok in _NUM.findall(text):
        try:
            out.add(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def known_numbers(source: Any) -> set[float]:
    """Every number in the input, with rounded and absolute forms, as allowed values for the output."""
    known = set()
    for n in numbers(json.dumps(source, default=str)):
        known |= {n, abs(n), round(n), round(abs(n)), round(n, 1), round(abs(n), 1)}
    return known


def unverified_numbers(text: str, known: set[float], small: float = 12) -> list[float]:
    """Numbers in text that are not small counts, years or values present in the input."""
    bad = sorted({n for n in numbers(text)
                  if abs(n) > small and not 1990 <= n <= 2100 and n not in known and round(n) not in known})
    return [int(n) if n == int(n) else n for n in bad]
