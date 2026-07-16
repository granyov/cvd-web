from __future__ import annotations

import re
from contextlib import nullcontext
from typing import Any, Callable, ContextManager

from .cvd_schema import CVD_SCHEMA, normalize_field
from .lmstudio import LMStudioError, call_json_lm_studio, extract_json_from_text, text_list, text_value


TEXT_STRUCTURING_VERSION = "cvd-text-structure-v6"
TEXT_CHUNK_MAX_CHARS = 1400
TEXT_CHUNK_MIN_CHARS = 700
TEXT_CHUNK_MAX_COUNT = 8
TEXT_MAX_INPUT_CHARS = 10000
TEXT_MAX_MODEL_CALLS = 12
TEXT_MAX_MODEL_DURATION_MS = 60 * 60 * 1000
TEXT_MAX_OUTPUT_TOKENS = 4096
AI_EXCLUDED_FIELDS = {"Patient_ID", "Full_name", "Sex"}
FIELD_SPECS = {
    f"{section.key}.{field.key}": (section.key, field)
    for section in CVD_SCHEMA
    if section.key != "MODEL_OUTPUT"
    for field in section.fields
    if not (section.key == "GENERAL_INFO" and field.key in AI_EXCLUDED_FIELDS)
}
UNKNOWN_VALUE_MARKERS = {
    "unknown",
    "неизвестно",
    "не указано",
    "нет данных",
    "n/a",
    "none",
    "null",
    "-",
    "—",
}
MEDICATION_CLASS_KEYWORDS = {
    "CURRENT_MEDICATIONS.Antiplatelets": (
        "аспирин", "ацетилсалиц", "клопидогрел", "тикагрелор", "прасугрел",
    ),
    "CURRENT_MEDICATIONS.Anticoagulants": (
        "апиксабан", "ривароксабан", "дабигатран", "эдоксабан", "варфарин", "гепарин", "эноксапарин",
    ),
    "CURRENT_MEDICATIONS.Beta_blockers": (
        "бисопролол", "метопролол", "небиволол", "карведилол", "атенолол", "пропранолол", "бетаксолол",
    ),
    "CURRENT_MEDICATIONS.ACEi_ARB_ARNI": (
        "эналаприл", "лизиноприл", "периндоприл", "рамиприл", "лозартан", "валсартан", "кандесартан",
        "телмисартан", "сакубитрил",
    ),
    "CURRENT_MEDICATIONS.MRA": ("спиронолактон", "эплеренон"),
    "CURRENT_MEDICATIONS.SGLT2_inhibitors": ("дапаглифлозин", "эмпаглифлозин", "канаглифлозин"),
    "CURRENT_MEDICATIONS.Diuretics": (
        "фуросемид", "торасемид", "индапамид", "гидрохлоротиазид", "хлорталидон",
    ),
    "CURRENT_MEDICATIONS.Antiarrhythmics": (
        "амиодарон", "соталол", "флекаинид", "пропафенон", "дронедарон",
    ),
    "CURRENT_MEDICATIONS.Lipid_lowering": (
        "аторвастатин", "розувастатин", "симвастатин", "питавастатин", "эзетимиб", "эволокумаб", "алирокумаб",
    ),
    "CURRENT_MEDICATIONS.Antidiabetic_drugs": (
        "метформин", "инсулин", "гликлазид", "семаглутид", "лираглутид", "ситаглиптин",
    ),
}


def medication_class_path(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("ё", "е")
    matches = [
        path
        for path, keywords in MEDICATION_CLASS_KEYWORDS.items()
        if any(keyword.replace("ё", "е") in normalized for keyword in keywords)
    ]
    return matches[0] if len(matches) == 1 else None

TEXT_STRUCTURING_SCHEMA = {
    "name": "cvd_text_structuring",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mappings": {
                "type": "array",
                "maxItems": 14,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "maxLength": 160},
                        "value": {"type": "string", "maxLength": 500},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "evidence": {"type": "string", "maxLength": 140},
                    },
                    "required": ["path", "value", "confidence", "evidence"],
                },
            },
            "corrected_text": {"type": "string", "maxLength": 600},
            "warnings": {
                "type": "array",
                "maxItems": 4,
                "items": {"type": "string", "maxLength": 240},
            },
        },
        "required": ["mappings", "corrected_text", "warnings"],
    },
}


def build_structuring_request(text: str, *, model: str, max_tokens: int) -> dict[str, Any]:
    allowed_paths = "\n".join(
        f"- {path} [{field.kind}]"
        for path, (_, field) in FIELD_SPECS.items()
    )
    prompt = f"""Преобразуй неструктурированную медицинскую запись в поля CVD.

Правила:
- Исправь орфографию и явные опечатки, но не меняй медицинский смысл.
- Извлекай только факты, прямо присутствующие в исходном тексте. Ничего не додумывай.
- Не ставь новый диагноз и не добавляй рекомендации.
- Только для путей с пометкой [number] value должен содержать число без единицы измерения.
- Для текстовых длительностей сохраняй число и единицу времени, например "3 месяца".
- Для нескольких кодов МКБ-10 используй строку с разделителем ;.
- Для пола используй male, female, other или unknown.
- yes, no или unknown используй только для бинарного статуса фактора риска или известного диагноза.
- Для лекарств сохраняй название, дозу и режим приёма; не заменяй препарат на yes/no.
- Не присваивай АД правой или левой руке, если сторона измерения не указана в тексте.
- Не выводи гипертензию или другой диагноз из показателя, если диагноз прямо не указан в тексте.
- Каждое поле укажи не более одного раза. Не возвращай пустые значения.
- path может быть только из списка ALLOWED_PATHS.
- corrected_text должен быть компактной исправленной медицинской заметкой до 600 символов.
- В corrected_text включай только клинически значимые факты из исходного текста, без рассуждений и рекомендаций.
- Верни не более 14 наиболее информативных mappings. Не копируй названия полей в evidence.

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
        "max_tokens": max(256, min(max_tokens, TEXT_MAX_OUTPUT_TOKENS)),
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
        section_key, field = FIELD_SPECS[path]
        raw_value = item.get("value")
        if str(raw_value or "").strip().lower() in UNKNOWN_VALUE_MARKERS:
            warnings.append(f"Поле {path} содержит только признак отсутствия данных; значение пропущено.")
            continue
        confidence = text_value(item.get("confidence"), 20).lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        if confidence != "high":
            warnings.append(f"Поле {path} не имеет высокой уверенности AI; значение пропущено.")
            continue
        if section_key == "CURRENT_MEDICATIONS":
            classified_path = medication_class_path(raw_value)
            if classified_path is None and path != "CURRENT_MEDICATIONS.Other_relevant_drugs":
                warnings.append(f"Класс препарата для {path} не подтверждён сервером; значение пропущено.")
                continue
            if classified_path and classified_path != path:
                warnings.append(f"Препарат перенесён из {path} в подтверждённый класс {classified_path}.")
                path = classified_path
                section_key, field = FIELD_SPECS[path]
        if path in seen_paths:
            warnings.append(f"Поле {path} возвращено повторно; использовано первое значение.")
            continue
        field_errors: list[str] = []
        value = normalize_field(section_key, field, raw_value, field_errors)
        if field_errors or value is None:
            warnings.extend(field_errors or [f"Поле {path} не содержит значения."])
            continue

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


def split_clinical_text(text: str, *, max_chars: int = TEXT_CHUNK_MAX_CHARS) -> list[str]:
    cleaned = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    units: list[str] = []
    for paragraph in re.split(r"\n+", cleaned):
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            while len(sentence) > max_chars:
                split_at = sentence.rfind(" ", 0, max_chars + 1)
                if split_at < max_chars // 2:
                    split_at = max_chars
                units.append(sentence[:split_at].strip())
                sentence = sentence[split_at:].strip()
            if sentence:
                units.append(sentence)

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def merge_structuring_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    corrected_parts: list[str] = []
    warnings: list[str] = []
    merged_by_path: dict[str, dict[str, Any]] = {}
    confidence_rank = {"low": 0, "medium": 1, "high": 2}

    for result in results:
        corrected = text_value(result.get("corrected_text"), 30000)
        if corrected and corrected not in corrected_parts:
            corrected_parts.append(corrected)
        warnings.extend(result.get("warnings") or [])
        for mapping in result.get("mappings") or []:
            path = str(mapping.get("path") or "")
            if not path:
                continue
            incoming = {
                **mapping,
                "sources": [
                    {**source, "value": mapping.get("value")}
                    for source in (mapping.get("sources") or [])
                ],
            }
            existing = merged_by_path.get(path)
            if existing is None:
                merged_by_path[path] = incoming
                continue
            if existing.get("value") == incoming.get("value"):
                known_labels = {str(source.get("label") or "") for source in existing.get("sources") or []}
                existing["sources"].extend(
                    source for source in incoming["sources"]
                    if str(source.get("label") or "") not in known_labels
                )
                if confidence_rank.get(incoming.get("confidence"), 0) > confidence_rank.get(existing.get("confidence"), 0):
                    existing["confidence"] = incoming["confidence"]
                continue
            existing["source_conflict"] = True
            existing["confidence"] = "low"
            existing["sources"].extend(incoming["sources"])
            warnings.append(f"В разных частях текста найдены разные значения для {path}; требуется ручная проверка.")

    return {
        "corrected_text": "\n\n".join(corrected_parts),
        "mappings": list(merged_by_path.values()),
        "warnings": list(dict.fromkeys(str(item) for item in warnings if str(item).strip()))[:30],
    }


def _response_finish_reason(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices") if isinstance(response_json, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    return str(first_choice.get("finish_reason") or "")


def _aggregate_response_payload(
    payloads: list[dict[str, Any]],
    *,
    finish_reason: str,
    chunk_count: int,
    completed_chunk_count: int | None = None,
    failed_chunk_count: int = 0,
) -> dict[str, Any]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for payload in payloads:
        raw_usage = payload.get("raw", {}).get("usage", {}) if isinstance(payload, dict) else {}
        for key in usage:
            try:
                usage[key] += max(0, int(raw_usage.get(key) or 0))
            except (TypeError, ValueError):
                continue
    return {
        "raw": {"usage": usage, "choices": [{"finish_reason": finish_reason}]},
        "content": "",
        "chunk_count": chunk_count,
        "completed_chunk_count": completed_chunk_count if completed_chunk_count is not None else chunk_count,
        "failed_chunk_count": failed_chunk_count,
        "attempt_count": len(payloads),
    }


def _call_text_structuring_chunk(
    *,
    api_url: str,
    model: str,
    text: str,
    timeout_seconds: int,
    max_tokens: int,
    call_guard: Callable[[], ContextManager[Any]] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
    request_body = build_structuring_request(text, model=model, max_tokens=max_tokens)
    with call_guard() if call_guard else nullcontext():
        response_json, content, duration_ms = call_json_lm_studio(
            api_url=api_url,
            request_body=request_body,
            timeout_seconds=max(1, int(timeout_seconds)),
            extra_headers=extra_headers,
        )
    response_payload = {"raw": response_json, "content": content}
    finish_reason = _response_finish_reason(response_json)
    if finish_reason == "length":
        raise LMStudioError(
            f"Ответ части AI-разбора обрезан по лимиту max_tokens={request_body['max_tokens']}. "
            "Она может быть повторена только один раз в меньшем размере.",
            duration_ms,
            request_body=request_body,
            response_payload=response_payload,
        )
    parsed = extract_json_from_text(content)
    if parsed is None:
        raise LMStudioError(
            "LM Studio не вернула завершённый структурированный JSON для разбора текста.",
            duration_ms,
            request_body=request_body,
            response_payload=response_payload,
        )
    normalized = normalize_structuring_output(parsed)
    if not normalized["mappings"] and not normalized["corrected_text"]:
        raise LMStudioError(
            "LM Studio не извлекла ни одного поля и не вернула исправленный текст.",
            duration_ms,
            request_body=request_body,
            response_payload=response_payload,
        )
    return request_body, response_payload, normalized, duration_ms


def call_text_structuring(
    *,
    api_url: str,
    model: str,
    text: str,
    timeout_seconds: int,
    max_tokens: int,
    call_guard: Callable[[], ContextManager[Any]] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
    source_chunks = split_clinical_text(text)
    if not source_chunks:
        raise LMStudioError("Текст для AI-разбора пуст.", 0)
    if len(source_chunks) > TEXT_CHUNK_MAX_COUNT:
        raise LMStudioError(
            f"Текст слишком большой для одного AI-разбора: {len(source_chunks)} частей. "
            "Разделите документ на несколько записей.",
            0,
        )

    pending_chunks = [(index, chunk, 0) for index, chunk in enumerate(source_chunks, start=1)]
    request_bodies: list[dict[str, Any]] = []
    attempt_payloads: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    terminal_failures: list[int] = []
    duration_ms = 0
    last_error: LMStudioError | None = None

    while pending_chunks:
        if len(attempt_payloads) >= TEXT_MAX_MODEL_CALLS or duration_ms >= TEXT_MAX_MODEL_DURATION_MS:
            terminal_failures.extend(index for index, _, _ in pending_chunks)
            break
        source_index, chunk, split_depth = pending_chunks.pop(0)
        try:
            request_body, response_payload, result, chunk_duration = _call_text_structuring_chunk(
                api_url=api_url,
                model=model,
                text=chunk,
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
                call_guard=call_guard,
                extra_headers=extra_headers,
            )
        except LMStudioError as exc:
            last_error = exc
            failed_payload = exc.response_payload if isinstance(exc.response_payload, dict) else None
            if failed_payload:
                attempt_payloads.append(failed_payload)
            duration_ms += max(0, int(exc.duration_ms or 0))
            finish_reason = _response_finish_reason(failed_payload.get("raw", {})) if failed_payload else ""
            retry_chunks = split_clinical_text(
                chunk,
                max_chars=max(TEXT_CHUNK_MIN_CHARS, len(chunk) // 2),
            )
            projected_attempts = len(attempt_payloads) + len(retry_chunks)
            if (
                finish_reason == "length"
                and split_depth == 0
                and len(retry_chunks) > 1
                and projected_attempts <= TEXT_MAX_MODEL_CALLS
            ):
                pending_chunks = [
                    (source_index, retry_chunk, 1) for retry_chunk in retry_chunks
                ] + pending_chunks
                continue
            if finish_reason == "length" and (results or pending_chunks):
                terminal_failures.append(source_index)
                continue
            exc.duration_ms = duration_ms
            exc.request_body = {"requests": request_bodies, "failed_request": exc.request_body}
            exc.response_payload = _aggregate_response_payload(
                attempt_payloads,
                finish_reason=finish_reason or "error",
                chunk_count=len(source_chunks),
                completed_chunk_count=len(results),
                failed_chunk_count=1,
            )
            raise

        request_bodies.append(request_body)
        attempt_payloads.append(response_payload)
        results.append(result)
        duration_ms += chunk_duration

    if not results:
        if last_error is not None:
            last_error.duration_ms = duration_ms
            last_error.response_payload = _aggregate_response_payload(
                attempt_payloads,
                finish_reason="length" if terminal_failures else "error",
                chunk_count=len(source_chunks),
                completed_chunk_count=0,
                failed_chunk_count=max(1, len(set(terminal_failures))),
            )
            raise last_error
        raise LMStudioError(
            "AI-разбор остановлен по лимиту времени или числа обращений к модели.",
            duration_ms,
            response_payload=_aggregate_response_payload(
                attempt_payloads,
                finish_reason="limit",
                chunk_count=len(source_chunks),
                completed_chunk_count=0,
                failed_chunk_count=len(set(terminal_failures)),
            ),
        )

    merged = merge_structuring_results(results)
    failed_count = len(set(terminal_failures))
    if failed_count:
        merged["warnings"].append(
            f"Не удалось полностью обработать {failed_count} частей текста; проверьте результат вручную."
        )
    if not merged["mappings"]:
        merged["warnings"].append("Поля CVD не извлечены; доступен только исправленный текст.")
    response_payload = _aggregate_response_payload(
        attempt_payloads,
        finish_reason="partial" if failed_count else "stop",
        chunk_count=len(source_chunks),
        completed_chunk_count=len(results),
        failed_chunk_count=failed_count,
    )
    return {
        "requests": request_bodies,
        "chunk_count": len(source_chunks),
        "attempt_count": len(attempt_payloads),
        "failed_chunk_count": failed_count,
    }, response_payload, merged, duration_ms
