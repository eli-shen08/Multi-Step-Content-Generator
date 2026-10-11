"""Single entry point for every LLM call: moderate in -> generate JSON -> validate -> moderate out."""
import json
import time
from typing import TypeVar

from openai import BadRequestError
from pydantic import BaseModel, ValidationError

from pipeline import moderation
from pipeline.events import emit
from pipeline.config import chat, model_for, reasoning_args

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 2


def call_llm(stage: str, system: str, user: str, schema: type[T], untrusted_input: bool = False) -> T:
    """Every output is moderated. The input is moderated when it holds untrusted text
    (the user's idea); later stages are built only from outputs that already passed."""
    start = time.time()
    model = model_for(stage)
    emit("stage_start", stage=stage, model=model)

    if untrusted_input:
        emit("status", stage=stage, text="Safety check on input")
        moderation.check(user, f"{stage} input")

    system_full = (
        f"{system}\n\nRespond with ONLY a JSON object matching this JSON Schema:\n"
        f"{json.dumps(schema.model_json_schema())}"
    )
    messages = [
        {"role": "system", "content": system_full},
        {"role": "user", "content": user},
    ]

    last_error: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        emit("status", stage=stage, text=f"Generating with {model}")
        try:
            resp = chat(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.4,
                **reasoning_args(model),
            )
        except BadRequestError as exc:
            # In JSON mode Groq rejects a reply that isn't valid JSON with a 400
            # (json_validate_failed) instead of returning it. Treat it like invalid JSON.
            if "json_validate_failed" not in str(exc):
                raise
            last_error = exc
            messages.append({"role": "user", "content": "Your previous reply was not valid JSON. Return only a valid JSON object."})
            continue
        raw = resp.choices[0].message.content or ""
        try:
            result = schema.model_validate_json(raw)
        except ValidationError as exc:
            last_error = exc
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Invalid JSON for the schema: {exc}. Return corrected JSON only."},
            ]
            continue
        emit("status", stage=stage, text="Safety check on output")
        moderation.check(raw, f"{stage} output")
        # Emitted only after the output passed moderation: blocked text never reaches the UI.
        emit("stage_done", stage=stage, seconds=round(time.time() - start, 1), data=result.model_dump())
        return result

    raise ValueError(f"{stage}: model did not return valid JSON") from last_error
