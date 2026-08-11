import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _load_runtime_env() -> None:
    prompt_dir = Path(__file__).resolve().parent
    rl_root = prompt_dir.parent
    env_path = rl_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        return
    load_dotenv(override=True)


def _make_client(api_key: str, timeout_sec: Optional[float], max_retries: Optional[int] = None):
    """Build an OpenAI-compatible client.

    If a 'base_url' env var is set (e.g. https://openrouter.ai/api/v1), the
    client is pointed at that endpoint; otherwise it uses the default OpenAI
    endpoint. This keeps OpenAI behaviour unchanged while allowing
    OpenAI-compatible providers such as OpenRouter.

    max_retries defaults to the SDK's own value (2) for the generation and judge
    paths. Pass it explicitly when a call has a latency budget: timeout_sec is
    per-attempt, so the SDK default lets a "2 s" call take ~6 s of wall clock.
    """
    from openai import OpenAI

    kwargs = {"api_key": api_key, "timeout": timeout_sec}
    if max_retries is not None:
        kwargs["max_retries"] = int(max_retries)
    base_url = os.getenv("base_url") or os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _system_prompt_for_subaction(subaction: str) -> str:
    if subaction == "ExplainNewFact":
        return """You are a natural, conversational museum guide.

IMPORTANT GUIDELINES:
- Be natural and concise.
- Do not quote the visitor verbatim.
- Keep continuity with the conversation.
- Use only fact IDs provided in the prompt when fact IDs are requested.
- Maximum two sentences."""
    if subaction in ("RepeatFact", "ClarifyFact"):
        return """You are a natural, conversational museum guide.

IMPORTANT GUIDELINES:
- Be natural and concise.
- Do not quote the visitor verbatim.
- For RepeatFact, use the exact fact ID provided in the prompt.
- For ClarifyFact, avoid adding new fact IDs.
- Maximum two sentences."""
    return """You are a natural, conversational museum guide.

IMPORTANT GUIDELINES:
- Be natural and concise.
- Do not quote the visitor verbatim.
- Keep continuity with the conversation.
- Maximum two sentences."""


def generate_with_openai(
    prompt: str,
    subaction: str,
    model: str = "gpt-5.4",
    api_key_env: str = "api_key",
    timeout_sec: Optional[float] = None,
) -> str:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("Package 'openai' is required for RL OpenAI generation.") from exc

    _load_runtime_env()
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing OpenAI API key in env var '{api_key_env}'")

    client = _make_client(api_key, timeout_sec)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _system_prompt_for_subaction(subaction)},
            {"role": "user", "content": prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


def generate_classification_label(
    prompt: str,
    model: str = "gpt-5.4",
    api_key_env: str = "api_key",
    timeout_sec: Optional[float] = 2.0,
    max_tokens: int = 10,
    temperature: float = 0.0,
    max_retries: int = 1,
) -> str:
    """Single-label classification call for the response-type classifier.

    Deliberately separate from generate_judge_json: this one runs BEFORE the
    policy forward pass, on the participant-facing critical path, so it pins
    temperature=0 for study reproducibility, caps output at a few tokens, and
    actually passes timeout_sec (the other call sites leave it None, which lets
    the SDK default of 600 s apply).

    max_retries is pinned because timeout_sec is PER ATTEMPT: at the SDK default
    of 2 retries a nominal 2 s budget was observed taking 5.9 s of wall clock.
    One retry bounds the worst case at roughly 2x timeout_sec.
    """
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("Package 'openai' is required for response-type classification.") from exc

    _load_runtime_env()
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing OpenAI API key in env var '{api_key_env}'")

    client = _make_client(api_key, timeout_sec, max_retries=max_retries)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You label museum-visitor utterances with one dialogue-act label. "
                    "Reply with exactly one label and nothing else."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (completion.choices[0].message.content or "").strip()


def generate_judge_json(
    prompt: str,
    model: str = "gpt-5.4",
    api_key_env: str = "api_key",
    timeout_sec: Optional[float] = None,
) -> str:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("Package 'openai' is required for RL judge generation.") from exc

    _load_runtime_env()
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing OpenAI API key in env var '{api_key_env}'")

    client = _make_client(api_key, timeout_sec)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a strict JSON verifier. Return valid JSON only, no markdown.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


def generate_revision_text(
    prompt: str,
    model: str = "gpt-5.4",
    api_key_env: str = "api_key",
    timeout_sec: Optional[float] = None,
) -> str:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("Package 'openai' is required for RL revision generation.") from exc

    _load_runtime_env()
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing OpenAI API key in env var '{api_key_env}'")

    client = _make_client(api_key, timeout_sec)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Revise the candidate text only. Output final response text only.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()

