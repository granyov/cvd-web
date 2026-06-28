from __future__ import annotations

from typing import Any

from .cvd_schema import CVD_SCHEMA, normalize_field
from .lmstudio import call_json_lm_studio, extract_json_from_text, text_list, text_value


TEXT_STRUCTURING_VERSION = "cvd-text-structure-v1"
FIELD_SPECS = {
    f"{section.key}.{field.key}": (section.key, field)
    for section in CVD_SCHEMA
    if section.key != "MODEL_OUTPUT"
    for field in section.fields
}

TEXT_STRUCTURING_SCHEMA = {
    "name": "cvd_text_structuring",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "corrected_text": {"type": "string"},
            "mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string"},
                        "value": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "evidence": {"type": "string"},
                    },
                    "required": ["path", "value", "confidence", "evidence"],
                },
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["corrected_text", "mappings", "warnings"],
    },
}


def build_structuring_request(text: str, *, model: str, max_tokens: int) -> dict[str, Any]:
    allowed_paths = "\n".join(f"- {path}" for path in FIELD_SPECS)
    prompt = f"""Преобразуй неструктурированную медицинскую запись в поля CVD.

Правила:
- Исправь орфографию и явные опечатки, но не меняй медицинский смысл.
- Извлекай только факты, прямо присутствующие в исходном тексте. Ничего не додумывай.
- Не ставь новый диагноз и не добавляй рекомендации.
- Для числового поля value должен содержать только число без единицы измерения.
- Для нескольких кодов МКБ-10 используй строку с разделителем ;.
- Для пола используй male, female, other или unknown.
- Для признаков со значениями да/нет используй yes, no или unknown, если это соответствует полю.
- Каждое поле укажи не более одного раза. Не возвращай пустые значения.
- path может быть только из списка ALLOWED_PATHS.
- corrected_text должен быть исправленной версией исходного текста на русском языке.

ALLOWED_PATHS:
{allowed_paths}

SOURCE_TEXT:
{text}
"""
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты модуль нормализации медицинских данных. Верни только валидный JSON по схеме. "
                    "Не делай клинических выводов и не создавай отсутствующие факты."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max(256, min(max_tokens, 4096)),
        "stream": False,
        "response_format": {"type": "json_schema", "json_schema": TEXT_STRUCTURING_SCHEMA},
    }


def normalize_structuring_output(parsed: Any) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {}
    warnings = text_list(parsed.get("warnings"), max_items=20, max_length=500)
    normalized_mappings: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    raw_mappings = parsed.get("mappings") if isinstance(parsed.get("mappings"), list) else []
    for item in raw_mappings[:150]:
        if not isinstance(item, dict):
            continue
        path = text_value(item.get("path"), 160)
        if path not in FIELD_SPECS:
            if path:
                warnings.append(f"Модель вернула неизвестное поле {path}; значение пропущено.")
            continue
        if path in seen_paths:
            warnings.append(f"Поле {path} возвращено повторно; использовано первое значение.")
            continue

        section_key, field = FIELD_SPECS[path]
        field_errors: list[str] = []
        value = normalize_field(section_key, field, item.get("value"), field_errors)
        if field_errors or value is None:
            warnings.extend(field_errors or [f"Поле {path} не содержит значения."])
            continue

        confidence = text_value(item.get("confidence"), 20).lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        evidence = text_value(item.get("evidence"), 500)
        normalized_mappings.append({
            "path": path,
            "value": value,
            "confidence": confidence,
            "source_conflict": False,
            "sources": [{
                "resource_type": "AI text structuring",
                "label": evidence or "Извлечено из свободного текста",
            }],
        })
        seen_paths.add(path)

    return {
        "corrected_text": text_value(parsed.get("corrected_text"), 30000),
        "mappings": normalized_mappings,
        "warnings": list(dict.fromkeys(warnings))[:30],
    }


def call_text_structuring(
    *,
    api_url: str,
    model: str,
    text: str,
    timeout_seconds: int,
    max_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
    request_body = build_structuring_request(text, model=model, max_tokens=max_tokens)
    response_json, content, duration_ms = call_json_lm_studio(
        api_url=api_url,
        request_body=request_body,
        timeout_seconds=timeout_seconds,
    )
    parsed = extract_json_from_text(content)
    if parsed is None:
        raise ValueError("LM Studio не вернул структурированный JSON")
    normalized = normalize_structuring_output(parsed)
    return request_body, {"raw": response_json, "content": content}, normalized, duration_ms
