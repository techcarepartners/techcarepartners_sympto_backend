"""LLM Symptom Analysis Engine using Google Gemini via LiteLLM."""

import json
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import litellm

from app.config import get_settings
from app.constants import LLM_MODEL_CHAIN, VALID_SPECIALIZATIONS

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    specializations: list[str] = field(default_factory=lambda: ["general physician"])
    display_names: list[str] = field(default_factory=lambda: ["General Physician"])
    confidence_scores: list[int] = field(default_factory=lambda: [70])
    summary: Optional[str] = None
    urgency: str = "routine"
    is_emergency: bool = False
    followup_question: Optional[str] = None
    was_force_concluded: bool = False


_DEFAULT_RESULT = LLMResult(
    specializations=["general physician"],
    display_names=["General Physician"],
    confidence_scores=[70],
    urgency="routine",
    is_emergency=False,
    followup_question=None,
)

_SYSTEM_PROMPT_TEMPLATE = """You are a medical triage assistant for an Indian healthcare platform.
You receive a patient profile (age, gender) followed by their symptom description and any prior conversation turns.
Your goal is to identify the most appropriate medical specialist(s) for the patient by asking targeted clarifying questions, one at a time, and then routing them to the correct specialist.

SPECIALIST SELECTION — use your medical knowledge:
- Apply clinical reasoning: consider the organ system involved, acuity indicators, demographic risk factors (age, gender), and the presenting symptom pattern.
- Always route to the most specific specialist the symptoms support. General Physician is a last resort — only when symptoms are genuinely non-specific and cannot be attributed to any particular organ or system.
- The valid specializations are: Cardiologist, Dermatologist, ENT, General Physician, Gynaecologist, Neurologist, Ophthalmologist, Orthopaedic, Paediatrician, Psychiatrist, Urologist, Other.
- Use "Other" when the correct specialist is not in this list (e.g. Gastroenterologist, Pulmonologist, Endocrinologist). For "Other" entries, write the actual specialty name in display_names.
- Use patient age and gender to inform urgency and routing: e.g. a child under 14 should generally see a Paediatrician; a 70-year-old with exertional symptoms carries higher cardiac urgency than a 25-year-old.
- Abdominal pain, nausea, vomiting, diarrhea, constipation, bloating, acid reflux, or any digestive/GI tract symptoms → always route to "Other" with display_name "Gastroenterologist". Never use General Physician for these.

FOLLOW-UP QUESTIONING — use your medical knowledge:
- Ask targeted questions that would help you differentiate between plausible specialties for the stated symptoms.
- Ask EXACTLY one short, focused question per turn. Never combine two questions into one message.
- Stop asking and conclude once you have gathered enough information.

RULES:
- MANDATORY FIRST QUESTION: If no prior Q&A turns, you MUST set followup_question to a clarifying question. Never conclude on the first message alone.
- GENERAL PHYSICIAN RULE: General Physician is ONLY acceptable when: (a) AT LEAST 5 follow-up questions answered, AND (b) symptoms genuinely span multiple unrelated organ systems. If fewer than 5 questions answered and best answer is GP, you MUST ask another question.
- Once you have identified a specific non-GP specialist with sufficient confidence, set followup_question to null.
- If {max_turns} or more answered questions, you MUST conclude immediately with followup_question = null.
- Always respond with ONLY raw JSON. No explanation, no markdown, no code fences.
- Never refuse; always pick the best matching specialization(s).

Your response must be exactly this JSON structure:
{{"specializations": ["..."], "display_names": ["..."], "confidence_scores": [85], "summary": "...", "urgency": "...", "is_emergency": false, "followup_question": null}}"""


def _build_user_message(
    age: int,
    gender: str,
    symptoms_text: str,
    followup_turns: list[dict],
    force_conclude: bool,
    force_followup_hint: bool,
) -> str:
    parts = [
        f"Patient profile: Age: {age}, Gender: {gender}",
        "",
        f"Patient's initial symptoms: {symptoms_text}",
    ]

    for i, turn in enumerate(followup_turns):
        role_label = "Doctor's question" if turn["role"] == "question" else "Patient's answer"
        parts.append(f"\n{role_label}: {turn['content']}")

    if force_conclude:
        parts.append(
            "\n[INSTRUCTION: You have gathered enough information. "
            "You MUST now provide the final result with followup_question set to null.]"
        )
    if force_followup_hint:
        parts.append(
            "\n[OVERRIDE: You concluded too early. The patient profile and symptoms do not yet "
            "provide sufficient differentiation. You MUST ask one more targeted question. "
            "Set followup_question to a clarifying question and do NOT conclude yet.]"
        )

    return "\n".join(parts)


def _parse_llm_response(raw: str) -> LLMResult | None:
    """Parse raw JSON string into LLMResult. Returns None on failure."""
    try:
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text.strip())

        specializations = [s.lower() for s in data.get("specializations", ["general physician"])]
        # Validate against known specializations
        valid = [s for s in specializations if s in VALID_SPECIALIZATIONS]
        if not valid:
            valid = ["general physician"]

        return LLMResult(
            specializations=valid,
            display_names=data.get("display_names", [s.title() for s in valid]),
            confidence_scores=data.get("confidence_scores", [70]),
            summary=data.get("summary"),
            urgency=data.get("urgency", "routine"),
            is_emergency=bool(data.get("is_emergency", False)),
            followup_question=data.get("followup_question") or None,
        )
    except Exception:
        return None


async def _call_llm(system_prompt: str, user_message: str) -> LLMResult | None:
    """Try each model in the fallback chain. Return first successful parse."""
    settings = get_settings()

    for model in LLM_MODEL_CHAIN:
        for attempt in range(2):
            try:
                response = await asyncio.to_thread(
                    litellm.completion,
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.7,
                    max_tokens=1024,
                    api_key=settings.gemini_api_key,
                )
                raw = response.choices[0].message.content or ""
                result = _parse_llm_response(raw)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning("LLM call failed (model=%s attempt=%d): %s", model, attempt, e)

    return None


async def analyze_symptoms(
    age: int,
    gender: str,
    symptoms_text: str,
    followup_turns: list[dict],
    language: str = "english",
    force_conclude: bool = False,
) -> LLMResult:
    """
    Main entry point for symptom analysis.
    Applies quality gates after LLM call.
    Returns LLMResult (never raises).
    """
    settings = get_settings()
    max_turns = settings.max_followup_turns

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(max_turns=max_turns)

    answered_turns = sum(1 for t in followup_turns if t["role"] == "answer")

    user_message = _build_user_message(
        age=age,
        gender=gender,
        symptoms_text=symptoms_text,
        followup_turns=followup_turns,
        force_conclude=force_conclude or answered_turns >= max_turns,
        force_followup_hint=False,
    )

    result = await _call_llm(system_prompt, user_message)
    if result is None:
        logger.error("All LLM models failed, returning default result")
        return _DEFAULT_RESULT

    result.was_force_concluded = answered_turns >= max_turns

    # Quality Gate 1: Non-GP specialist concluded too early
    if (
        result.followup_question is None
        and not any(s == "general physician" for s in result.specializations)
        and answered_turns < 3
        and not force_conclude
    ):
        user_msg_retry = _build_user_message(
            age=age, gender=gender, symptoms_text=symptoms_text,
            followup_turns=followup_turns,
            force_conclude=False, force_followup_hint=True,
        )
        retry = await _call_llm(system_prompt, user_msg_retry)
        if retry is not None:
            result = retry

    # Quality Gate 2: GP returned with fewer than 5 answered turns
    elif (
        result.followup_question is None
        and any(s == "general physician" for s in result.specializations)
        and answered_turns < 5
        and not force_conclude
    ):
        user_msg_retry = _build_user_message(
            age=age, gender=gender, symptoms_text=symptoms_text,
            followup_turns=followup_turns,
            force_conclude=False, force_followup_hint=True,
        )
        retry = await _call_llm(system_prompt, user_msg_retry)
        if retry is not None:
            result = retry

    return result
