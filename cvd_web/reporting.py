from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any


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


def _is_filled(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    return str(value)


def _field_label(key: str) -> str:
    return FIELD_LABELS.get(key, key.replace("_", " "))


def _patient_sections(patient_data: dict[str, Any]) -> str:
    blocks = []
    for section_key, section in patient_data.items():
        if section_key == "MODEL_OUTPUT" or not isinstance(section, dict):
            continue
        rows = []
        for key, value in section.items():
            if not _is_filled(value):
                continue
            rows.append(
                f"<dt>{escape(_field_label(key))}</dt><dd>{escape(_text(value))}</dd>"
            )
        if rows:
            title = escape(SECTION_LABELS.get(section_key, section_key.replace("_", " ")))
            blocks.append(f"<section class=\"data-section\"><h3>{title}</h3><dl>{''.join(rows)}</dl></section>")
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


def build_html_report(
    patient_data: dict[str, Any],
    parsed_output: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    general = patient_data.get("GENERAL_INFO") if isinstance(patient_data.get("GENERAL_INFO"), dict) else {}
    cds = parsed_output.get("CDS_OUTPUT") if isinstance(parsed_output.get("CDS_OUTPUT"), dict) else {}
    generated_at = str(metadata.get("generated_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    patient_name = _text(general.get("Full_name") or "Пациент не указан")
    patient_id = _text(general.get("Patient_ID") or "без ID")
    summary = _text(cds.get("summary") or "Сводка AI-анализа отсутствует.")
    abstained = bool(cds.get("model_should_abstain"))
    app_name = _text(metadata.get("app_name") or "CVD Web")
    organization = _text(metadata.get("organization_name") or "")
    request_id = _text(metadata.get("request_id") or "-")
    duration_ms = int(metadata.get("duration_ms") or 0)
    report_details = [
        f"Запрос: #{request_id}",
        f"Длительность: {duration_ms / 1000:.1f} с",
    ]

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Заключение CVD - {escape(patient_name)}</title>
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
    @media (max-width:700px) {{ .page {{ width:100%; margin:0; padding:20px; border:0; }} header {{ align-items:flex-start; }} .result-grid,.patient-grid {{ grid-template-columns:1fr; }} dl {{ grid-template-columns:1fr; gap:2px; }} dd {{ margin-bottom:7px; }} }}
    @media print {{ @page {{ size:A4; margin:14mm; }} body {{ background:#fff; font-size:10pt; }} .page {{ width:auto; margin:0; padding:0; border:0; }} .print-button {{ display:none; }} h2 {{ break-after:avoid; }} }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div><p class="eyebrow">{escape(organization or app_name)}</p><h1>Результат клинического анализа</h1><p class="muted">Сформировано: {escape(generated_at)}</p></div>
      <button class="print-button" type="button" onclick="window.print()">Распечатать</button>
    </header>
    <div class="patient-line"><strong>{escape(patient_name)}</strong><span>ID случая: {escape(patient_id)}</span></div>
    <h2>Результат AI-анализа</h2>
    <section class="summary{' abstain' if abstained else ''}"><h3>{'AI не сформировал заключение' if abstained else 'Клиническая сводка'}</h3><p>{escape(summary)}</p></section>
    <h2>Возможные диагнозы</h2>
    <div class="diagnoses">{_diagnoses_block(cds.get('possible_diagnoses'))}</div>
    <div class="result-grid">
      {_list_block('Red flags', cds.get('red_flags'), 'Не указаны.')}
      {_list_block('Недостающие данные', cds.get('missing_data'), 'Не указаны.')}
      {_list_block('Что ещё собрать', cds.get('recommended_next_data'), 'Не указано.')}
      {_list_block('Ограничения', cds.get('limitations'), 'Не указаны.')}
    </div>
    <h2>Исходные данные пациента</h2>
    <div class="patient-grid">{_patient_sections(patient_data)}</div>
    <p class="meta">{escape(' · '.join(report_details))}</p>
    <div class="warning">Результат сформирован системой поддержки принятия решений и требует обязательной проверки врачом. Документ не является медицинским заключением.</div>
  </main>
</body>
</html>"""
