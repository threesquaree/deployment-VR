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


def _system_prompt_for_subaction(subaction: str) -> str:
    if subaction == "ExplainNewFact":
        return """You are a natural, conversational museum guide.

IMPORTANT GUIDELINES:
- Be natural and concise.
- Do not quote the visitor verbatim.
- Keep continuity with the conversation.
- Use only fact IDs provided in the prompt when fact IDs are requested.
- Keep responses 2-3 sentences."""
    if subaction in ("RepeatFact", "ClarifyFact"):
        return """You are a natural, conversational museum guide.

IMPORTANT GUIDELINES:
- Be natural and concise.
- Do not quote the visitor verbatim.
- For RepeatFact, use the exact fact ID provided in the prompt.
- For ClarifyFact, avoid adding new fact IDs.
- Keep responses 2-3 sentences."""
    return """You are a natural, conversational museum guide.

IMPORTANT GUIDELINES:
- Be natural and concise.
- Do not quote the visitor verbatim.
- Keep continuity with the conversation.
- Keep responses 2-3 sentences."""


def generate_with_openai(
    prompt: str,
    subaction: str,
    model: str = "gpt-4o-mini",
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

    client = OpenAI(api_key=api_key, timeout=timeout_sec)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _system_prompt_for_subaction(subaction)},
            {"role": "user", "content": prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()

