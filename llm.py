import os
import sys
import asyncio
import importlib
from typing import Callable, Dict, List, Optional

from . import config


def chat(
    messages: List[Dict[str, str]],
    on_token: Optional[Callable[[str], None]] = None,
    model_override: Optional[str] = None,
) -> str:
    """Send messages to the configured LLM backend.

    Streams tokens via *on_token* callback as they arrive (or to stdout if
    on_token is None).  Returns the complete assembled response text.
    model_override, if given, replaces the configured model for this call only.
    """
    cfg = config.load_config()
    backend = cfg.get("backend", "anthropic")

    if backend != "anthropic":
        raise RuntimeError(
            f"Unsupported backend '{backend}'. "
            "Fastfold PyMOL Agent currently supports Anthropic only. Run: fastfold setup"
        )
    if cfg.get("anthropic_use_agent_sdk", True):
        return _anthropic_agent_sdk_chat(
            messages,
            cfg,
            on_token=on_token,
            model_override=model_override,
        )
    return _anthropic_chat(messages, cfg, on_token=on_token, model_override=model_override)


def _emit(token: str, on_token: Optional[Callable]) -> None:
    """Write a token to the on_token callback or directly to stdout."""
    if on_token:
        on_token(token)
    else:
        sys.stdout.write(token)
        sys.stdout.flush()


def _anthropic_chat(
    messages: List[Dict[str, str]],
    cfg: dict,
    on_token: Optional[Callable] = None,
    model_override: Optional[str] = None,
) -> str:
    try:
        anthropic = importlib.import_module("anthropic")
    except Exception:
        raise RuntimeError("anthropic package not installed. Run: fastfold deps install")

    api_key = (cfg.get("anthropic_api_key", "") or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Anthropic API key not set. Run: fastfold setup "
            "or fastfold config set anthropic_api_key <your-key>."
        )

    model = model_override or cfg.get("anthropic_model", config.DEFAULT_ANTHROPIC_MODEL)
    if model not in config.SUPPORTED_ANTHROPIC_MODELS:
        allowed = ", ".join(config.SUPPORTED_ANTHROPIC_MODELS)
        raise RuntimeError(
            f"Unsupported Anthropic model '{model}'. "
            f"Allowed models: {allowed}. "
            "Update with: fastfold config set anthropic_model <model-id>"
        )

    # Separate the system message — Anthropic takes it as a distinct param.
    # Wrap it with cache_control so the large system prompt is cached server-side
    # after the first call (5-min TTL), cutting latency and cost on every turn.
    system_content = ""
    filtered: List[Dict] = []
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            filtered.append({"role": msg["role"], "content": msg["content"]})

    if not filtered:
        raise RuntimeError("No user messages to send.")

    system_param = (
        [{"type": "text", "text": system_content, "cache_control": {"type": "ephemeral"}}]
        if system_content
        else []
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        kwargs: dict = dict(model=model, max_tokens=2048, messages=filtered)
        if system_param:
            kwargs["system"] = system_param

        full_text: List[str] = []
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                full_text.append(text)
                _emit(text, on_token)
        if not on_token:
            sys.stdout.write("\n")
            sys.stdout.flush()
        return "".join(full_text)
    except Exception as e:
        raise RuntimeError(f"LLM call failed (anthropic): {e}")


def _anthropic_agent_sdk_chat(
    messages: List[Dict[str, str]],
    cfg: dict,
    on_token: Optional[Callable] = None,
    model_override: Optional[str] = None,
) -> str:
    api_key = (cfg.get("anthropic_api_key", "") or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Anthropic API key not set. Run: fastfold setup "
            "or fastfold config set anthropic_api_key <your-key>."
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = api_key

    model = model_override or cfg.get("anthropic_model", config.DEFAULT_ANTHROPIC_MODEL)
    if model not in config.SUPPORTED_ANTHROPIC_MODELS:
        allowed = ", ".join(config.SUPPORTED_ANTHROPIC_MODELS)
        raise RuntimeError(
            f"Unsupported Anthropic model '{model}'. "
            f"Allowed models: {allowed}. "
            "Update with: fastfold config set anthropic_model <model-id>"
        )
    max_turns = int(cfg.get("agent_sdk_max_turns", 30))

    try:
        from .agent_sdk import run_claude_agent_sdk

        return asyncio.run(
            run_claude_agent_sdk(
                messages,
                model=model,
                max_turns=max_turns,
                on_token=on_token,
            )
        )
    except Exception as e:
        raise RuntimeError(f"LLM call failed (anthropic Claude Agent SDK): {e}")
