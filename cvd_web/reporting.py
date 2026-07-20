from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from typing import Any

from .field_labels import SCHEMA_FIELD_LABELS
from .reference_ranges import reference_status


SECTION_LABELS = {
    "GENERAL_INFO": "Общие сведения",
    "COMPLAINTS": "Жалобы",
    "RISK_FACTORS": "Факторы риска",
    "PAST_EVENTS": "Анамнез и события",
    "KNOWN_CVD_DIAGNOSES": "Известные сердечно-сосудистые диагнозы",
    "PHYSICAL_EXAM": "Осмотр",
    "LABS_CBC": "Общий анализ крови",
    "LABS_BIOCHEM": "Биохимия",
    "LABS_LIPIDS": "Липидный профиль",
    "LABS_CARDIAC_MARKERS": "Кардиомаркеры",
    "LABS_COAGULATION": "Коагулограмма",
    "ECG_AND_BP_MONITORING": "ЭКГ и мониторинг",
    "ECHOCARDIOGRAPHY": "Эхокардиография",
    "FUNCTIONAL_TESTS": "Функциональные тесты",
    "CORONARY_AND_VASCULAR_IMAGING": "Визуализация",
    "DEVICES_AND_PROCEDURES": "Устройства и процедуры",
    "CURRENT_MEDICATIONS": "Текущая терапия",
    "SCORES_AND_CLASSES": "Шкалы и классы",
    "FINAL_DIAGNOSES": "Рабочие диагнозы врача",
}

# Подписи для печати: развёрнутые там, где экранная форма обходится сокращением.
FIELD_LABELS = {
    "Patient_ID": "ID случая",
    "Full_name": "ФИО пациента",
    "Sex": "Пол",
    "Age": "Возраст, лет",
    "Height_cm": "Рост, см",
    "Weight_kg": "Масса, кг",
    "BMI": "BMI",
    "Main_complaint": "Основная жалоба",
    "Complaint_duration": "Длительность жалоб",
    "Onset_context": "Контекст начала симптомов",
    "Blood_pressure_right_systolic_mmHg": "АД справа, систолическое",
    "Blood_pressure_right_diastolic_mmHg": "АД справа, диастолическое",
    "Blood_pressure_left_systolic_mmHg": "АД слева, систолическое",
    "Blood_pressure_left_diastolic_mmHg": "АД слева, диастолическое",
    "Heart_rate_bpm": "ЧСС",
    "Resp_rate": "ЧДД",
    "SpO2_room_air_percent": "SpO2, %",
    "Resting_ECG_summary": "ЭКГ покоя",
    "Holter_ECG_summary": "Холтер-ЭКГ",
    "ABPM_summary": "СМАД",
    "LVEF_percent": "ФВ ЛЖ, %",
    "Main_cardiovascular_diagnosis_text": "Основной сердечно-сосудистый диагноз",
    "Other_cardiovascular_diagnoses": "Другие сердечно-сосудистые диагнозы",
    "Non_cardiac_comorbidities": "Некардиальные сопутствующие заболевания",
    "ICD10_codes": "Коды МКБ-10",
}


MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _is_filled(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _strip_trailing_icd(text: Any) -> str:
    """Убирает хвост «МКБ-10: I20.8, I10» из текста диагноза.

    Промпт просит модель указывать коды в конце заключения, но и отчёт, и текст
    для МИС печатают коды отдельной строкой — без чистки они задваиваются.
    """
    return re.sub(r"\s*МКБ-?10\s*[::]\s*[A-ZА-Я]?\d[\d.,;\s A-Z]*\.?\s*$", "", str(text or ""), flags=re.IGNORECASE).strip()


def _human_datetime(value: Any) -> str:
    """ISO-время -> «18 июля 2026, 22:52» для печатного документа."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return f"{moment.day} {MONTHS_RU[moment.month - 1]} {moment.year}, {moment:%H:%M}"


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    return str(value)


def _field_label(key: str) -> str:
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    return SCHEMA_FIELD_LABELS.get(key, key.replace("_", " "))


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение: "1 поле", "2 поля", "5 полей"."""
    tail_100 = count % 100
    tail_10 = count % 10
    if 11 <= tail_100 <= 14:
        word = many
    elif tail_10 == 1:
        word = one
    elif 2 <= tail_10 <= 4:
        word = few
    else:
        word = many
    return f"{count} {word}"


def _patient_sections(patient_data: dict[str, Any]) -> str:
    """Приложение с исходными данными.

    Числовые показатели печатаются с референсом: на бумаге нельзя навести курсор,
    а без нормы значение вроде «Гемоглобин 121» ничего не говорит. Отклонения
    помечаются, чтобы работал режим печати «только отклонения».
    """
    blocks = []
    for section_key, section in patient_data.items():
        if section_key == "MODEL_OUTPUT" or not isinstance(section, dict):
            continue
        rows = []
        abnormal_in_section = 0
        for key, value in section.items():
            if not _is_filled(value):
                continue
            status = reference_status(f"{section_key}.{key}", value)
            abnormal = bool(status and status["abnormal"])
            if abnormal:
                abnormal_in_section += 1
            reference_html = (
                f"<span class=\"reference\">норма {escape(status['text'])}</span>" if status else ""
            )
            rows.append(
                f"<div class=\"data-row{' abnormal' if abnormal else ''}\" data-abnormal=\"{'1' if abnormal else '0'}\">"
                f"<dt>{escape(_field_label(key))}</dt>"
                f"<dd>{escape(_text(value))}{reference_html}</dd>"
                "</div>"
            )
        if rows:
            title = escape(SECTION_LABELS.get(section_key, section_key.replace("_", " ")))
            blocks.append(
                f"<section class=\"data-section\" data-abnormal-count=\"{abnormal_in_section}\">"
                f"<h3>{title}</h3><dl>{''.join(rows)}</dl></section>"
            )
    return "".join(blocks) or "<p class=\"muted\">Заполненные данные пациента отсутствуют.</p>"


def _list_block(title: str, values: Any, empty_text: str) -> str:
    items = values if isinstance(values, list) else []
    content = "".join(f"<li>{escape(_text(item))}</li>" for item in items if _is_filled(item))
    if not content:
        content = f"<li class=\"muted\">{escape(empty_text)}</li>"
    return f"<section class=\"result-section\"><h3>{escape(title)}</h3><ul>{content}</ul></section>"


def _diagnoses_block(diagnoses: Any) -> str:
    if not isinstance(diagnoses, list) or not diagnoses:
        return "<p class=\"muted\">Возможные диагнозы не указаны.</p>"
    cards = []
    confidence_labels = {"high": "высокая", "medium": "средняя", "low": "низкая"}
    for item in diagnoses:
        if not isinstance(item, dict):
            continue
        codes = "; ".join(str(code) for code in item.get("icd10_codes", []) if code) or "не указаны"
        findings = item.get("supporting_findings") if isinstance(item.get("supporting_findings"), list) else []
        findings_html = "".join(f"<li>{escape(_text(value))}</li>" for value in findings) or "<li>не указаны</li>"
        confidence = confidence_labels.get(str(item.get("confidence") or ""), "не указана")
        cards.append(
            "<article class=\"diagnosis\">"
            f"<div class=\"diagnosis-head\"><h3>{escape(_text(item.get('name') or 'Диагноз без названия'))}</h3>"
            f"<span>Уверенность: {escape(confidence)}</span></div>"
            f"<p><strong>МКБ-10:</strong> {escape(codes)}</p>"
            f"<p><strong>Поддерживающие данные:</strong></p><ul>{findings_html}</ul>"
            "</article>"
        )
    return "".join(cards) or "<p class=\"muted\">Возможные диагнозы не указаны.</p>"


def _recommendations_block(model_output: dict[str, Any]) -> str:
    blocks = []
    for title, key in (
        ("Тактика ведения", "Model_treatment_recommendations"),
        ("Реабилитация и профилактика", "Model_rehabilitation_recommendations"),
    ):
        value = model_output.get(key)
        if not _is_filled(value):
            continue
        blocks.append(
            f"<section class=\"result-section\"><h3>{escape(title)}</h3><p>{escape(_text(value))}</p></section>"
        )
    if not blocks:
        return ""
    return (
        "<h2>Черновик рекомендаций</h2>"
        "<p class=\"muted\">Ориентиры по тактике без препаратов и доз. Назначения определяет врач.</p>"
        f"<div class=\"result-grid\">{''.join(blocks)}</div>"
    )


def build_mis_text(
    patient_data: dict[str, Any],
    parsed_output: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    """Готовый текстовый блок для вставки в поле протокола МИС (ЕМИАС и др.).

    Врач переносит заключение между системами копированием, поэтому текст
    должен читаться как протокол, а не как выгрузка данных.
    """
    general = patient_data.get("GENERAL_INFO") if isinstance(patient_data.get("GENERAL_INFO"), dict) else {}
    final = patient_data.get("FINAL_DIAGNOSES") if isinstance(patient_data.get("FINAL_DIAGNOSES"), dict) else {}
    cds = parsed_output.get("CDS_OUTPUT") if isinstance(parsed_output.get("CDS_OUTPUT"), dict) else {}
    model_output = parsed_output.get("MODEL_OUTPUT") if isinstance(parsed_output.get("MODEL_OUTPUT"), dict) else {}

    sex_map = {"male": "муж.", "female": "жен.", "other": "иное", "unknown": "пол не указан"}
    patient_parts = [
        _text(general.get("Full_name") or "").strip(),
        f"{_text(general.get('Age'))} лет" if _is_filled(general.get("Age")) else "",
        sex_map.get(str(general.get("Sex") or ""), ""),
        f"ID случая: {_text(general.get('Patient_ID'))}" if _is_filled(general.get("Patient_ID")) else "",
    ]

    lines: list[str] = ["ЗАКЛЮЧЕНИЕ (черновик системы поддержки принятия решений)"]
    patient_line = ", ".join(part for part in patient_parts if part)
    if patient_line:
        lines.append(f"Пациент: {patient_line}")
    lines.append("")

    doctor_diagnosis = _text(final.get("Main_cardiovascular_diagnosis_text") or "").strip()
    doctor_codes = [str(code) for code in (final.get("ICD10_codes") or []) if str(code).strip()]
    lines.append("ДИАГНОЗ ВРАЧА:")
    lines.append(doctor_diagnosis or "не заполнен")
    if doctor_codes:
        lines.append(f"МКБ-10: {', '.join(doctor_codes)}")
    lines.append("")

    ai_diagnosis = _strip_trailing_icd(model_output.get("Final_model_diagnosis"))
    ai_codes = [str(code) for code in (model_output.get("Model_ICD10_codes") or []) if str(code).strip()]
    lines.append("ЧЕРНОВИК AI:")
    if cds.get("model_should_abstain"):
        lines.append("AI воздержался от заключения: данных недостаточно.")
    else:
        lines.append(ai_diagnosis or "заключение не сформировано")
        if ai_codes:
            lines.append(f"МКБ-10: {', '.join(ai_codes)}")
    lines.append("")

    summary = _text(cds.get("summary") or "").strip()
    if summary:
        lines.extend(["ОБОСНОВАНИЕ:", summary])
    red_flags = [str(flag) for flag in (cds.get("red_flags") or []) if str(flag).strip()]
    if red_flags:
        lines.append("Red flags: " + "; ".join(red_flags))
    missing = [str(item) for item in (cds.get("missing_data") or []) if str(item).strip()]
    if missing:
        lines.append("Не хватает данных: " + "; ".join(missing))
    if summary or red_flags or missing:
        lines.append("")

    treatment = _text(model_output.get("Model_treatment_recommendations") or "").strip()
    rehabilitation = _text(model_output.get("Model_rehabilitation_recommendations") or "").strip()
    if treatment or rehabilitation:
        lines.append("РЕКОМЕНДАЦИИ (ориентиры; назначения определяет врач):")
        if treatment:
            lines.append(f"Тактика: {treatment}")
        if rehabilitation:
            lines.append(f"Реабилитация и профилактика: {rehabilitation}")
        lines.append("")

    footer_parts = [
        _human_datetime(metadata.get("generated_at")),
        f"отчёт №{_text(metadata.get('request_id'))}" if _is_filled(metadata.get("request_id")) else "",
        _text(metadata.get("doctor_name") or "").strip(),
    ]
    footer = " · ".join(part for part in footer_parts if part)
    if footer:
        lines.append(footer)
    lines.append("Черновик CVD Engine. Требует проверки врачом, не является самостоятельным медицинским заключением.")
    return "\n".join(lines).strip()


def _codes_html(codes: Any) -> str:
    items = codes if isinstance(codes, list) else []
    chips = "".join(f"<span class=\"code\">{escape(_text(code))}</span>" for code in items if _is_filled(code))
    return chips or "<span class=\"muted\">коды не указаны</span>"


def _conclusion_block(patient_data: dict[str, Any], cds: dict[str, Any], model_output: dict[str, Any]) -> str:
    """Заключение первым экраном: диагноз врача рядом с черновиком AI."""
    final = patient_data.get("FINAL_DIAGNOSES") if isinstance(patient_data.get("FINAL_DIAGNOSES"), dict) else {}
    doctor_diagnosis = _text(final.get("Main_cardiovascular_diagnosis_text") or "")
    doctor_codes = final.get("ICD10_codes")
    ai_diagnosis = _strip_trailing_icd(model_output.get("Final_model_diagnosis"))
    if not ai_diagnosis:
        diagnoses = cds.get("possible_diagnoses") if isinstance(cds.get("possible_diagnoses"), list) else []
        lead = diagnoses[0] if diagnoses and isinstance(diagnoses[0], dict) else {}
        ai_diagnosis = _strip_trailing_icd(lead.get("name"))
        ai_codes = lead.get("icd10_codes")
    else:
        ai_codes = model_output.get("Model_ICD10_codes")
    abstained = bool(cds.get("model_should_abstain"))

    doctor_html = (
        f"<p class=\"conclusion-text\">{escape(doctor_diagnosis)}</p><div class=\"codes\">{_codes_html(doctor_codes)}</div>"
        if doctor_diagnosis
        else "<p class=\"muted\">Рабочий диагноз врача не заполнен.</p>"
    )
    if abstained:
        ai_html = "<p class=\"conclusion-text muted\">AI воздержался от заключения: данных недостаточно.</p>"
    elif ai_diagnosis:
        ai_html = f"<p class=\"conclusion-text\">{escape(ai_diagnosis)}</p><div class=\"codes\">{_codes_html(ai_codes)}</div>"
    else:
        ai_html = "<p class=\"muted\">Заключение AI отсутствует.</p>"

    return (
        "<section class=\"conclusion\">"
        "<div class=\"conclusion-col\"><h3>Диагноз врача</h3>" + doctor_html + "</div>"
        "<div class=\"conclusion-col ai\"><h3>Черновик AI</h3>" + ai_html + "</div>"
        "</section>"
    )


def _stale_banner(metadata: dict[str, Any]) -> str:
    """Печатный документ обязан сообщать, что данные менялись после анализа.

    На экране предупреждение живёт секунду, распечатанный лист - годами.
    """
    if not metadata.get("ai_result_stale"):
        return ""
    changes = metadata.get("ai_result_changes")
    changed = [item for item in changes if isinstance(item, dict)] if isinstance(changes, list) else []
    labels = "; ".join(_field_label(_text(item.get("label") or item.get("path"))) for item in changed[:8])
    detail = f" Изменены поля: {labels}." if labels else ""
    more = f" И ещё {_plural(len(changed) - 8, 'поле', 'поля', 'полей')}." if len(changed) > 8 else ""
    count = f" ({_plural(len(changed), 'поле', 'поля', 'полей')})" if changed else ""
    return (
        "<section class=\"stale-banner\">"
        "<strong>Внимание: заключение относится к прежней версии данных.</strong>"
        f"<span>После анализа случай редактировали{escape(count)}."
        f"{escape(detail)}{escape(more)} Перед использованием обновите анализ.</span>"
        "</section>"
    )


REVIEW_RATING_LABELS = {
    "useful": "полезно",
    "partial": "частично полезно",
    "wrong": "неверно",
    "unsafe": "небезопасно",
}

REVIEW_ISSUE_LABELS = {
    "wrong_icd": "неверный код МКБ-10",
    "wrong_diagnosis": "неверный диагноз",
    "missed_red_flag": "пропущен red flag",
    "missed_diagnosis": "пропущен диагноз",
    "hallucination": "выдуманные данные",
    "unsafe_recommendation": "небезопасная рекомендация",
    "incomplete": "неполный ответ",
    "formatting": "проблемы с форматом ответа",
}


def _review_block(metadata: dict[str, Any]) -> str:
    """Экспертная оценка врача - то, что превращает черновик AI в проверенный документ."""
    review = metadata.get("review")
    if not isinstance(review, dict) or not review.get("rating"):
        return (
            "<section class=\"review-block pending\">"
            "<h3>Экспертная оценка врача</h3>"
            "<p class=\"muted\">Оценка ответа AI не сохранена: заключение остаётся непроверенным черновиком.</p>"
            "</section>"
        )
    rating = str(review.get("rating"))
    label = REVIEW_RATING_LABELS.get(rating, rating)
    rows = [f"<p><strong>Вердикт врача:</strong> {escape(label)}</p>"]
    corrected = _text(review.get("corrected_diagnosis") or "").strip()
    if corrected:
        rows.append(f"<p><strong>Корректный диагноз:</strong> {escape(corrected)}</p>")
    codes = review.get("corrected_icd10")
    if isinstance(codes, list) and codes:
        rows.append(f"<p><strong>Корректные МКБ-10:</strong> {escape('; '.join(str(code) for code in codes))}</p>")
    issues = review.get("issue_types")
    if isinstance(issues, list) and issues:
        readable = "; ".join(REVIEW_ISSUE_LABELS.get(str(item), str(item)) for item in issues)
        rows.append(f"<p><strong>Отмеченные проблемы:</strong> {escape(readable)}</p>")
    comment = _text(review.get("comment") or "").strip()
    if comment:
        rows.append(f"<p><strong>Комментарий:</strong> {escape(comment)}</p>")
    unsafe = rating in {"wrong", "unsafe"}
    return (
        f"<section class=\"review-block{' rejected' if unsafe else ' accepted'}\">"
        "<h3>Экспертная оценка врача</h3>"
        + "".join(rows)
        + "</section>"
    )


def _red_flags_block(cds: dict[str, Any]) -> str:
    """Red flags печатаем отдельным блоком: на бумаге безопасность должна доминировать."""
    flags = [str(flag) for flag in (cds.get("red_flags") or []) if str(flag).strip()]
    if not flags:
        return ""
    items = "".join(f"<li>{escape(flag)}</li>" for flag in flags)
    return f"<section class=\"red-flags\"><h3>Red flags</h3><ul>{items}</ul></section>"


def _signature_block(metadata: dict[str, Any]) -> str:
    doctor = _text(metadata.get("doctor_name") or "")
    doctor_line = escape(doctor) if doctor else "&nbsp;"
    return (
        "<section class=\"signature\">"
        "<div><span class=\"sig-label\">Врач</span><div class=\"sig-line\">" + doctor_line + "</div></div>"
        "<div><span class=\"sig-label\">Подпись</span><div class=\"sig-line\">&nbsp;</div></div>"
        "<div><span class=\"sig-label\">Дата</span><div class=\"sig-line\">&nbsp;</div></div>"
        "</section>"
    )


def build_html_report(
    patient_data: dict[str, Any],
    parsed_output: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    general = patient_data.get("GENERAL_INFO") if isinstance(patient_data.get("GENERAL_INFO"), dict) else {}
    cds = parsed_output.get("CDS_OUTPUT") if isinstance(parsed_output.get("CDS_OUTPUT"), dict) else {}
    model_output = parsed_output.get("MODEL_OUTPUT") if isinstance(parsed_output.get("MODEL_OUTPUT"), dict) else {}
    generated_at = str(metadata.get("generated_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    patient_name = _text(general.get("Full_name") or "Пациент не указан")
    patient_id = _text(general.get("Patient_ID") or "без ID")
    summary = _text(cds.get("summary") or "Сводка AI-анализа отсутствует.")
    abstained = bool(cds.get("model_should_abstain"))
    app_name = _text(metadata.get("app_name") or "CVD Web")
    organization = _text(metadata.get("organization_name") or "")
    request_id = _text(metadata.get("request_id") or "-")
    duration_ms = int(metadata.get("duration_ms") or 0)
    case_id = _text(metadata.get("case_id") or "")
    generated_human = _human_datetime(generated_at) or generated_at
    general_info = general
    age = _text(general_info.get("Age") or "")
    sex_map = {"male": "муж.", "female": "жен.", "other": "иное", "unknown": "не указан"}
    sex = sex_map.get(str(general_info.get("Sex") or ""), "")
    patient_facts = " · ".join(
        part for part in (
            f"ID случая: {patient_id}",
            f"Кейс №{case_id}" if case_id else "",
            f"{age} лет" if age else "",
            sex,
        ) if part
    )
    report_details = [
        f"Отчёт по анализу №{request_id}",
        f"Длительность анализа: {duration_ms / 1000:.1f} с",
        f"Сформировано: {generated_human}",
    ]
    # Трассируемость: по этой строке разбирают инцидент и воспроизводят анализ.
    # Идентификатор модели сюда не попадает: печатный документ для врача говорит
    # от имени системы, а модель под номером анализа хранится в архиве.
    trace_details = [
        part for part in (
            f"{app_name} {_text(metadata.get('app_version') or '')}".strip(),
            f"prompt: {_text(metadata.get('prompt_version'))}" if _is_filled(metadata.get("prompt_version")) else "",
            f"схема ответа: {_text(metadata.get('output_schema_version'))}" if _is_filled(metadata.get("output_schema_version")) else "",
        ) if part
    ]
    running_id = " · ".join(part for part in (patient_name, f"ID {patient_id}" if patient_id else "") if part)

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Кардиологическое заключение — {escape(patient_name)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#17212b; --muted:#5e6b78; --line:#d9e2ea; --soft:#f4f8fb; --accent:#087ea4; --danger:#a62b2b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#eef4f7; color:var(--ink); font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .page {{ width:min(980px,calc(100% - 32px)); margin:28px auto; padding:36px; background:#fff; border:1px solid var(--line); }}
    header {{ display:flex; justify-content:space-between; gap:24px; padding-bottom:20px; border-bottom:3px solid var(--accent); }}
    h1 {{ margin:2px 0 5px; font-size:25px; }} h2 {{ margin:28px 0 12px; font-size:18px; }} h3 {{ margin:0 0 8px; font-size:14px; }} p {{ margin:5px 0; }}
    .eyebrow,.muted,.meta {{ color:var(--muted); }} .eyebrow {{ margin:0; font-size:12px; text-transform:uppercase; font-weight:700; }}
    .print-button {{ align-self:flex-start; border:0; border-radius:6px; padding:10px 16px; color:#fff; background:var(--accent); font-weight:700; cursor:pointer; }}
    .patient-line {{ display:flex; flex-wrap:wrap; gap:8px 20px; margin:18px 0; padding:13px 15px; background:var(--soft); border-left:3px solid var(--accent); }}
    .summary {{ padding:16px; border:1px solid var(--line); background:var(--soft); }} .summary.abstain {{ border-left:4px solid var(--danger); }}
    .diagnoses {{ display:grid; gap:10px; }} .diagnosis {{ padding:14px; border:1px solid var(--line); break-inside:avoid; }}
    .diagnosis-head {{ display:flex; justify-content:space-between; gap:16px; }} .diagnosis-head span {{ color:var(--muted); white-space:nowrap; }}
    .result-grid,.patient-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .result-section,.data-section {{ padding:14px; border:1px solid var(--line); break-inside:avoid; }}
    dl {{ display:grid; grid-template-columns:minmax(130px,.7fr) minmax(0,1.3fr); gap:7px 14px; margin:0; }} dt {{ color:var(--muted); }} dd {{ margin:0; overflow-wrap:anywhere; }}
    ul {{ margin:5px 0 0; padding-left:20px; }} .meta {{ margin-top:22px; font-size:12px; }}
    .warning {{ margin-top:24px; padding:13px 15px; color:#6f2929; background:#fff4f4; border:1px solid #e9c8c8; font-weight:600; }}
    .toolbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px; }}
    .print-toggle {{ display:inline-flex; align-items:center; gap:7px; color:var(--muted); font-size:13px; cursor:pointer; }}
    .conclusion {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:6px 0 4px; break-inside:avoid; }}
    .conclusion-col {{ padding:15px 16px; border:1px solid var(--line); border-top:3px solid var(--ink); }}
    .conclusion-col.ai {{ border-top-color:var(--accent); background:var(--soft); }}
    .conclusion-col h3 {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
    .conclusion-text {{ margin:0; font-size:15px; font-weight:600; line-height:1.4; }}
    .codes {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:9px; }}
    .code {{ padding:2px 9px; border:1px solid var(--line); border-radius:999px; background:#fff; font-size:12px; font-weight:700; }}
    .signature {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:22px; margin-top:26px; break-inside:avoid; }}
    .sig-label {{ color:var(--muted); font-size:12px; }}
    .sig-line {{ margin-top:20px; padding-top:5px; border-top:1px solid var(--ink); font-weight:600; min-height:24px; }}
    .appendix-title {{ display:flex; align-items:baseline; justify-content:space-between; gap:16px; }}
    .running-head {{ display:none; }}
    .stale-banner {{ display:grid; gap:4px; margin:16px 0; padding:13px 15px; border:2px solid var(--danger); border-radius:4px; background:#fff4f4; break-inside:avoid; }}
    .stale-banner strong {{ color:var(--danger); }}
    .red-flags {{ margin:14px 0; padding:13px 16px; border:1px solid var(--danger); border-left:5px solid var(--danger); background:#fff6f6; break-inside:avoid; }}
    .red-flags h3 {{ color:var(--danger); text-transform:uppercase; letter-spacing:.04em; font-size:12px; }}
    .red-flags ul {{ margin:0; padding-left:20px; font-weight:600; }}
    .review-block {{ margin-top:20px; padding:14px 16px; border:1px solid var(--line); border-left:4px solid var(--accent); break-inside:avoid; }}
    .review-block.rejected {{ border-left-color:var(--danger); background:#fff6f6; }}
    .review-block.pending {{ border-left-color:var(--muted); background:var(--soft); }}
    .review-block h3 {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
    .review-block p {{ margin:3px 0; }}
    .data-row {{ display:contents; }}
    .data-row.abnormal dd {{ font-weight:700; }}
    .data-row.abnormal dt::after {{ content:" ▲"; color:var(--danger); font-size:11px; }}
    .reference {{ display:block; color:var(--muted); font-size:11px; }}
    .meta.trace {{ margin-top:4px; font-size:11px; }}
    body.appendix-abnormal .data-row[data-abnormal="0"],
    body.appendix-abnormal .data-section[data-abnormal-count="0"] {{ display:none; }}
    @media (max-width:700px) {{ .page {{ width:100%; margin:0; padding:20px; border:0; }} header {{ align-items:flex-start; }} .result-grid,.patient-grid,.conclusion,.signature {{ grid-template-columns:1fr; }} dl {{ grid-template-columns:1fr; gap:2px; }} dd {{ margin-bottom:7px; }} }}
    @media print {{
      @page {{ size:A4; margin:16mm 14mm 18mm; }}
      body {{ background:#fff; font-size:10pt; }}
      .page {{ width:auto; margin:0; padding:0; border:0; }}
      .no-print {{ display:none !important; }}
      h2 {{ break-after:avoid; font-size:13pt; }} h1 {{ font-size:18pt; }}
      .conclusion, .signature, .diagnosis, .result-section, .data-section, .summary {{ break-inside:avoid; }}
      .appendix {{ break-before:page; }}
      body.appendix-off .appendix {{ display:none; }}
      .stale-banner, .red-flags, .review-block {{ break-inside:avoid; }}
      .running-head {{ display:block; position:fixed; top:-11mm; left:0; right:0; color:var(--muted); font-size:8pt; border-bottom:1px solid var(--line); padding-bottom:2mm; }}
      a {{ color:inherit; text-decoration:none; }}
    }}
  </style>
</head>
<body>
  <div class="running-head">{escape(running_id)} · Отчёт №{escape(request_id)}</div>
  <main class="page">
    <header>
      <div>
        <p class="eyebrow">{escape(organization or app_name)}</p>
        <h1>Кардиологическое заключение</h1>
        <p class="muted">Сформировано: {escape(generated_human)}</p>
      </div>
      <div class="toolbar no-print">
        <button class="print-button" type="button" onclick="window.print()">Печать / Сохранить PDF</button>
        <label class="print-toggle">Исходные данные:
          <select id="appendixMode">
            <option value="off" selected>не печатать</option>
            <option value="abnormal">только отклонения</option>
            <option value="full">полностью</option>
          </select>
        </label>
      </div>
    </header>
    <div class="patient-line"><strong>{escape(patient_name)}</strong><span>{escape(patient_facts)}</span></div>
    {_stale_banner(metadata)}
    <h2>Заключение</h2>
    {_conclusion_block(patient_data, cds, model_output)}
    {_red_flags_block(cds)}
    <section class="summary{' abstain' if abstained else ''}"><h3>{'AI не сформировал заключение' if abstained else 'Клиническая сводка AI'}</h3><p>{escape(summary)}</p></section>
    {_recommendations_block(model_output)}
    {_review_block(metadata)}
    {_signature_block(metadata)}
    <div class="warning">Черновик системы поддержки принятия решений. Требует проверки врачом и не является самостоятельным медицинским заключением.</div>
    <h2>Обоснование AI</h2>
    <div class="diagnoses">{_diagnoses_block(cds.get('possible_diagnoses'))}</div>
    <div class="result-grid">
      {_list_block('Недостающие данные', cds.get('missing_data'), 'Не указаны.')}
      {_list_block('Что ещё собрать', cds.get('recommended_next_data'), 'Не указано.')}
      {_list_block('Ограничения', cds.get('limitations'), 'Не указаны.')}
    </div>
    <section class="appendix">
      <div class="appendix-title"><h2>Приложение: исходные данные пациента</h2><span class="muted no-print" id="appendixHint"></span></div>
      <div class="patient-grid">{_patient_sections(patient_data)}</div>
    </section>
    <p class="meta">{escape(' · '.join(report_details))}</p>
    <p class="meta trace">{escape(' · '.join(trace_details))}</p>
  </main>
  <script>
    const appendixMode = document.getElementById("appendixMode");
    const appendixHint = document.getElementById("appendixHint");
    const abnormalRows = document.querySelectorAll('.data-row[data-abnormal="1"]').length;
    function applyAppendixMode() {{
      const mode = appendixMode ? appendixMode.value : "off";
      document.body.classList.toggle("appendix-off", mode === "off");
      document.body.classList.toggle("appendix-abnormal", mode === "abnormal");
      if (appendixHint) {{
        appendixHint.textContent = mode === "abnormal"
          ? `отклонений: ${{abnormalRows}}`
          : mode === "off" ? "в печать не пойдёт" : "";
      }}
    }}
    appendixMode?.addEventListener("change", applyAppendixMode);
    applyAppendixMode();
  </script>
</body>
</html>"""
