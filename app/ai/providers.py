"""AI providers: `openai` (official SDK, Responses API, strict JSON schema, store=false) and
`fake` (tests, no network). The API key is read from settings (SecretStr) and only handed to
the SDK; it is never printed or logged. Errors become AIError(kind) with a short, safe kind:
auth | quota | country | rate_limit | timeout | network | bad_request | server | bad_output | other."""
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import get_settings

MAX_OUTPUT_TOKENS = 2000
CACHE_KEY = "decant-inbox-v1"


class AIError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail[:120]  # never the request / key: only status codes and error codes


@dataclass
class Reply:
    data: dict  # parsed JSON (not yet checked)
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class Provider(Protocol):
    name: str

    def understand(self, instructions: str, schema: dict, user_input: str, model: str, reasoning: str) -> Reply:
        ...


def _code(exc) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        return str(err.get("code") or err.get("type") or "")
    return ""


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, timeout: float):
        import openai  # only the parser worker / eval script need the SDK

        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    def understand(self, instructions: str, schema: dict, user_input: str, model: str, reasoning: str) -> Reply:
        openai = self._openai
        start = time.monotonic()
        for attempt in (1, 2):  # 1 retry, on network errors only (not on timeouts, not on HTTP errors)
            try:
                response = self._client.responses.create(
                    model=model, instructions=instructions, input=user_input, store=False,
                    reasoning={"effort": reasoning}, max_output_tokens=MAX_OUTPUT_TOKENS,
                    prompt_cache_key=CACHE_KEY,
                    text={"format": {"type": "json_schema", "name": "message_understanding", "schema": schema,
                                     "strict": True}})
                break
            except openai.APITimeoutError as exc:
                raise AIError("timeout") from exc
            except openai.APIConnectionError as exc:
                if attempt == 2:
                    raise AIError("network") from exc
            except openai.AuthenticationError as exc:
                raise AIError("auth", _code(exc)) from exc
            except openai.PermissionDeniedError as exc:
                code = _code(exc)
                raise AIError("country" if "country" in code or "region" in code else "auth", code) from exc
            except openai.RateLimitError as exc:
                code = _code(exc)
                raise AIError("quota" if "quota" in code or "billing" in code else "rate_limit", code) from exc
            except openai.BadRequestError as exc:
                raise AIError("bad_request", _code(exc)) from exc
            except openai.InternalServerError as exc:
                raise AIError("server", _code(exc)) from exc
            except openai.APIStatusError as exc:
                raise AIError("other", f"{exc.status_code} {_code(exc)}") from exc
        latency = int((time.monotonic() - start) * 1000)
        usage = response.usage
        reply = Reply({}, usage.input_tokens if usage else 0,
                      (usage.input_tokens_details.cached_tokens if usage and usage.input_tokens_details else 0) or 0,
                      usage.output_tokens if usage else 0, latency)
        if response.status != "completed":
            raise AIError("bad_output", f"status {response.status}")
        try:
            reply.data = json.loads(response.output_text)
        except (TypeError, ValueError) as exc:
            raise AIError("bad_output", "invalid JSON") from exc
        return reply


@dataclass
class FakeProvider:
    """Tests: answers from a function of the user input (or a fixed dict); an Exception value is
    raised. Records every request so tests can check what would leave the server."""
    answer: dict | Exception | Callable[[str], dict | Exception] = field(default_factory=dict)
    input_tokens: int = 2000
    cached_tokens: int = 1500
    output_tokens: int = 120
    requests: list[tuple[str, str]] = field(default_factory=list)  # (instructions, user input)
    name: str = "fake"

    def understand(self, instructions: str, schema: dict, user_input: str, model: str, reasoning: str) -> Reply:
        self.requests.append((instructions, user_input))
        answer = self.answer(user_input) if callable(self.answer) else self.answer
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, str):  # invalid JSON on purpose
            try:
                answer = json.loads(answer)
            except ValueError as exc:
                raise AIError("bad_output", "invalid JSON") from exc
        return Reply(answer, self.input_tokens, self.cached_tokens, self.output_tokens, 5)


_override: Provider | None = None
_cached: Provider | None = None


def use(provider: Provider | None) -> None:
    """Tests: install a provider (None = back to the configured one)."""
    global _override
    _override = provider


def get() -> Provider | None:
    """The provider to use, or None when AI is off / no key."""
    global _cached
    if _override is not None:
        return _override
    s = get_settings()
    if s.ai_provider != "openai" or s.openai_api_key is None or not s.openai_api_key.get_secret_value().strip():
        return None
    if _cached is None:
        _cached = OpenAIProvider(s.openai_api_key.get_secret_value(), s.ai_timeout_s)
    return _cached


def cost_usd(input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """Cached input tokens are billed at the cached price, the rest of the input at the normal one."""
    s = get_settings()
    cached = min(cached_tokens, input_tokens)
    return round(((input_tokens - cached) * s.ai_price_in + cached * s.ai_price_cached_in
                  + output_tokens * s.ai_price_out) / 1_000_000, 8)
