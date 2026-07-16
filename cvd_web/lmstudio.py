from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .cvd_schema import ICD10_PATTERN
from .versions import APP_VERSION, MODEL_OUTPUT_SCHEMA_VERSION, MODEL_PROMPT_VERSION, PATIENT_SCHEMA_VERSION


LM_STUDIO_USER_AGENT = f"CVD-Web/{APP_VERSION.lstrip('v')}"


SYSTEM_PROMPT = (
    "Ты медицинская модель. Ответ должен быть только валидным JSON-объектом. "
    "Начни ответ с { и закончи }. Не добавляй Markdown и пояснения. "
    "Работаешь только с синтетическими или де-идентифицированными данными "
    "для образовательных и исследовательских целей. Если данных недостаточно, "
    "явно укажи, что модель воздерживается от заключения."
)

USER_PROMPT_TEMPLATE = """You are a clinical decision support component working only with synthetic or de-identified cardiovascular data.
Return compact JSON matching the required response schema. All free-text values must be in Russian.

Rules:
- PATIENT_JSON is the only clinical source. Preserve numeric values exactly and never invent findings.
- Provide at most 3 differential diagnoses and only ICD-10 codes you can support from the supplied data.
- Keep summary to 4 short sentences. Keep evidence lists concise.
- Use at most 4 supporting findings per diagnosis and at most 4 items in every other list.
- Return field values, not source field names or JSON paths. Do not repeat the same fact.
- red_flags contains only findings that may require urgent clinical attention, not ordinary chronic risk factors.
- recommended_next_data contains missing data or investigations, not treatment instructions.
- Respect symptom duration and acuity. Do not label a chronic stable presentation as acute or unstable without supplied acute features.
- Do not list data already present in PATIENT_JSON as missing.
- If evidence is insufficient or contradictory, set model_should_abstain=true.

Metadata:
- prompt_version: {{PROMPT_VERSION}}
- patient_schema_version: {{PATIENT_SCHEMA_VERSION}}
- output_schema_version: {{OUTPUT_SCHEMA_VERSION}}

PATIENT_JSON:
{{PATIENT_JSON}}
"""


TEXT_ARRAY_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "maxItems": 4,
}

MODEL_RESPONSE_JSON_SCHEMA = {
    "name": "cvd_cds_output",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "CDS_OUTPUT": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string", "maxLength": 1200},
                    "possible_diagnoses": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "icd10_codes": TEXT_ARRAY_SCHEMA,
                                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                                "supporting_findings": TEXT_ARRAY_SCHEMA,
                            },
                            "required": [
                                "name",
                                "icd10_codes",
                                "confidence",
                                "supporting_findings",
                            ],
                        },
                    },
                    "red_flags": TEXT_ARRAY_SCHEMA,
                    "missing_data": TEXT_ARRAY_SCHEMA,
                    "recommended_next_data": TEXT_ARRAY_SCHEMA,
                    "limitations": TEXT_ARRAY_SCHEMA,
                    "model_should_abstain": {"type": "boolean"},
                },
                "required": [
                    "summary",
                    "possible_diagnoses",
                    "red_flags",
                    "missing_data",
                    "recommended_next_data",
                    "limitations",
                    "model_should_abstain",
                ],
            },
        },
        "required": ["CDS_OUTPUT"],
    },
}


class LMStudioError(RuntimeError):
    def __init__(
        self,
        message: str,
        duration_ms: int,
        *,
        request_body: dict[str, Any] | None = None,
        response_payload: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.duration_ms = duration_ms
        self.request_body = request_body
        self.response_payload = response_payload


def remove_empty(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, list):
        cleaned_items = [remove_empty(item) for item in value]
        cleaned_items = [item for item in cleaned_items if item is not None]
        return cleaned_items or None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            cleaned_item = remove_empty(item)
            if cleaned_item is not None:
                cleaned[key] = cleaned_item
        return cleaned or None
    return value


def build_chat_request(
    patient_data: dict[str, Any],
    model: str,
    max_tokens: int,
    temperature: float = 0.2,
    prompt_template: str | None = None,
    prompt_version: str = MODEL_PROMPT_VERSION,
    structured_output: bool = True,
) -> dict[str, Any]:
    cleaned = remove_empty(patient_data) or {}
    patient_json = json.dumps(cleaned, ensure_ascii=False, indent=2)
    template = prompt_template or USER_PROMPT_TEMPLATE
    if "{{PATIENT_JSON}}" not in template:
        template = USER_PROMPT_TEMPLATE
    user_prompt = (
        template
        .replace("{{PROMPT_VERSION}}", prompt_version)
        .replace("{{PATIENT_SCHEMA_VERSION}}", PATIENT_SCHEMA_VERSION)
        .replace("{{OUTPUT_SCHEMA_VERSION}}", MODEL_OUTPUT_SCHEMA_VERSION)
        .replace("{{PATIENT_JSON}}", patient_json)
    )
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if structured_output:
        request_body["response_format"] = {
            "type": "json_schema",
            "json_schema": MODEL_RESPONSE_JSON_SCHEMA,
        }
    return request_body


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.removeprefix("```json").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for start, char in enumerate(cleaned):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(cleaned)):
            current = cleaned[end]
            if escaped:
                escaped = False
                continue
            if current == "\\":
                escaped = True
                continue
            if current == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start : end + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    return parsed if isinstance(parsed, dict) else None
    return None


def text_value(value: Any, max_length: int = 2000) -> str:
    return str(value or "").strip()[:max_length]


def text_list(value: Any, *, max_items: int = 5, max_length: int = 500) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result = []
    for item in values:
        text = text_value(item, max_length)
        if text and text not in result:
            result.append(text)
        if len(result) >= max_items:
            break
    return result


def icd10_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [item.strip() for item in value.replace(",", ";").split(";")]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result = []
    for item in values:
        code = text_value(item, 20).upper()
        if code and ICD10_PATTERN.match(code) and code not in result:
            result.append(code)
        if len(result) >= 5:
            break
    return result


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "да"}


def normalize_model_output(parsed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {"raw_content": str(parsed)}

    model_output = parsed.get("MODEL_OUTPUT") if isinstance(parsed.get("MODEL_OUTPUT"), dict) else parsed
    diagnosis = text_value(model_output.get("Final_model_diagnosis") or model_output.get("summary"))
    codes = icd10_list(model_output.get("Model_ICD10_codes") or model_output.get("icd10_codes"))

    raw_cds = parsed.get("CDS_OUTPUT") if isinstance(parsed.get("CDS_OUTPUT"), dict) else {}
    raw_diagnoses = raw_cds.get("possible_diagnoses") if isinstance(raw_cds.get("possible_diagnoses"), list) else []
    diagnoses = []
    for item in raw_diagnoses[:3]:
        if not isinstance(item, dict):
            continue
        name = text_value(item.get("name"), 300)
        if not name:
            continue
        confidence = text_value(item.get("confidence"), 20).lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"
        diagnoses.append({
            "name": name,
            "icd10_codes": icd10_list(item.get("icd10_codes")),
            "confidence": confidence,
            "supporting_findings": text_list(item.get("supporting_findings")),
            "against_findings": text_list(item.get("against_findings")),
            "missing_data": text_list(item.get("missing_data")),
        })

    summary = text_value(raw_cds.get("summary") or diagnosis)
    schema_complete = isinstance(parsed.get("CDS_OUTPUT"), dict)
    limitations = text_list(raw_cds.get("limitations"))
    if not schema_complete:
        limitations.append("Ответ модели не соответствовал полной CDS-схеме и был нормализован приложением.")

    if not diagnosis and diagnoses:
        diagnosis = "; ".join(item["name"] for item in diagnoses)
    if not codes:
        for item in diagnoses:
            if len(codes) >= 5:
                break
            for code in item["icd10_codes"]:
                if code not in codes:
                    codes.append(code)
                if len(codes) >= 5:
                    break

    return {
        "CDS_OUTPUT": {
            "summary": summary,
            "possible_diagnoses": diagnoses,
            "red_flags": text_list(raw_cds.get("red_flags")),
            "missing_data": text_list(raw_cds.get("missing_data")),
            "recommended_next_data": text_list(raw_cds.get("recommended_next_data")),
            "limitations": limitations[:5],
            "model_should_abstain": bool_value(raw_cds.get("model_should_abstain")) if schema_complete else not bool(summary),
        },
        "MODEL_OUTPUT": {
            "Final_model_diagnosis": diagnosis or summary,
            "Model_ICD10_codes": codes,
            "Model_treatment_recommendations": text_value(model_output.get("Model_treatment_recommendations")),
            "Model_rehabilitation_recommendations": text_value(model_output.get("Model_rehabilitation_recommendations")),
        },
    }


def call_json_lm_studio(
    *,
    api_url: str,
    request_body: dict[str, Any],
    timeout_seconds: int,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str, int]:
    """Send an OpenAI-compatible chat request and return its JSON payload and content."""
    encoded = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": LM_STUDIO_USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        api_url,
        data=encoded,
        method="POST",
        headers=headers,
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        raise LMStudioError(lm_studio_http_error_message(exc.code, body), elapsed_ms) from exc
    except TimeoutError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        raise LMStudioError(
            f"LM Studio не ответила за {timeout_seconds} с. Проверьте нагрузку и таймаут модели.",
            elapsed_ms,
        ) from exc
    except urllib.error.URLError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        raise LMStudioError(f"LM Studio недоступен: {exc.reason}", elapsed_ms) from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        response_json = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LMStudioError(f"LM Studio вернул невалидный JSON: {raw[:500]}", duration_ms) from exc

    content = (
        response_json.get("choices", [{}])[0]
        .get("message", {})
        .get("content")
    )
    if not content:
        content = json.dumps(response_json, ensure_ascii=False)
    return response_json, str(content), duration_ms


def lm_studio_http_error_message(status_code: int, body: str) -> str:
    message = str(body or "").strip()
    try:
        payload = json.loads(message)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("message"):
            message = str(error["message"]).strip()
    except json.JSONDecodeError:
        pass
    lowered = message.lower()
    if "insufficient system resources" in lowered or "requires approximately" in lowered:
        return "LM Studio не смогла загрузить модель: недостаточно памяти. Выберите меньшую модель в админке."
    return f"LM Studio HTTP {status_code}: {message[:1000] or 'ошибка без описания'}"


def call_lm_studio(
    *,
    api_url: str,
    model: str,
    patient_data: dict[str, Any],
    timeout_seconds: int,
    max_tokens: int,
    temperature: float = 0.2,
    prompt_template: str | None = None,
    prompt_version: str = MODEL_PROMPT_VERSION,
    structured_output: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
    request_body = build_chat_request(
        patient_data,
        model,
        max_tokens,
        temperature,
        prompt_template,
        prompt_version,
        structured_output,
    )
    response_json, content, duration_ms = call_json_lm_studio(
        api_url=api_url,
        request_body=request_body,
        timeout_seconds=timeout_seconds,
        extra_headers=extra_headers,
    )

    response_payload = {"raw": response_json, "content": content}
    choices = response_json.get("choices") if isinstance(response_json, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    finish_reason = str(first_choice.get("finish_reason") or "")
    if finish_reason == "length":
        raise LMStudioError(
            f"Ответ LM Studio обрезан по лимиту max_tokens={max_tokens}. "
            "Увеличьте lm_studio_max_tokens и повторите запрос.",
            duration_ms,
            request_body=request_body,
            response_payload=response_payload,
        )

    parsed = extract_json_from_text(content)
    if parsed is None:
        raise LMStudioError(
            "LM Studio вернула незавершённый или невалидный структурированный JSON. "
            "Ответ не принят как клинический результат.",
            duration_ms,
            request_body=request_body,
            response_payload=response_payload,
        )

    raw_cds = parsed.get("CDS_OUTPUT") if isinstance(parsed.get("CDS_OUTPUT"), dict) else None
    if not raw_cds or not text_value(raw_cds.get("summary")):
        raise LMStudioError(
            "LM Studio вернула структурированный ответ без клинической сводки. "
            "Ответ не принят как клинический результат.",
            duration_ms,
            request_body=request_body,
            response_payload=response_payload,
        )
    parsed = normalize_model_output(parsed)

    return request_body, response_payload, parsed, duration_ms
