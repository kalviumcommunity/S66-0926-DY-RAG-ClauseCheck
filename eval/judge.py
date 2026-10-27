import json
import random
import re
from dataclasses import dataclass

from clausecheck.llm.client import LLMClient
from clausecheck.prompts.loader import Prompt


@dataclass
class Grade:
    label: str
    reason: str


_LABELS = {"correct", "partial", "wrong"}


def grade(client, prompt: Prompt, question, expected, answer) -> Grade:
    filled = (
        prompt.text.replace("{{question}}", str(question))
        .replace("{{expected}}", str(expected))
        .replace("{{answer}}", str(answer))
    )
    try:
        reply = client.complete(filled)
    except Exception as exc:
        return Grade("error", str(exc)[:80])
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        return Grade("error", "unparseable output")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return Grade("error", "unparseable output")
    label = data.get("label")
    reason = data.get("reason", "")
    if label not in _LABELS:
        return Grade("error", "invalid label")
    return Grade(label, str(reason))


def sample_for_review(rows: list[dict], frac: float = 0.1, seed: int = 42) -> list[dict]:
    if not rows:
        return []
    k = max(1, round(len(rows) * frac))
    k = min(k, len(rows))
    rng = random.Random(seed)
    return list(rng.sample(rows, k))


def agreement(judge: list[str], human: list[str]) -> float:
    if not judge or not human:
        return 0.0
    n = min(len(judge), len(human))
    if n == 0:
        return 0.0
    return sum(1 for a, b in zip(judge[:n], human[:n], strict=False) if a == b) / n


def build_judge_client(settings) -> LLMClient:
    from clausecheck.llm.groq import GroqProvider

    return LLMClient(
        primary=GroqProvider(
            settings.groq_api_key, settings.judge_model, settings.llm_timeout_seconds
        ),
        fallback=None,
        max_retries=settings.llm_max_retries,
        wait_seconds=settings.llm_retry_wait_seconds,
    )
