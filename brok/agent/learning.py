"""Learning mode: teach instead of dumping code. Builds prompts for each learning step."""

from __future__ import annotations

from typing import Dict

STEPS = ("explain", "example", "exercise", "hint", "solution", "quiz")

_TEMPLATES: Dict[str, str] = {
    "explain": "Explain '{topic}' to a beginner in simple terms, step by step. No code dump; use an analogy.",
    "example": "Give one small, runnable example of '{topic}' and walk through it line by line.",
    "exercise": "Create ONE short practice exercise about '{topic}'. Do NOT include the solution.",
    "hint": "The learner is stuck on an exercise about '{topic}'. Give a small hint only, not the answer.",
    "solution": "Show the full solution for the exercise about '{topic}' and explain why it works.",
    "quiz": "Ask 3 short multiple-choice questions about '{topic}'. Do NOT reveal answers until the learner replies.",
}


def learning_prompt(step: str, topic: str, language: str = "fa") -> str:
    if step not in _TEMPLATES:
        raise ValueError(f"unknown learning step: {step}")
    lang = "Respond in Persian (Farsi); keep code and identifiers in English." if language == "fa" else ""
    return f"{_TEMPLATES[step].format(topic=topic)} {lang}".strip()
