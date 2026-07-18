window.CVD_SCHEMA = [
  {
    key: "GENERAL_INFO",
    title: "Общие сведения",
    fields: [
      { key: "Patient_ID", label: "ID случая", type: "text", placeholder: "CVD_CASE_001" },
      { key: "Full_name", label: "ФИО пациента", type: "text", placeholder: "Тестовый пациент" },
      { key: "Sex", label: "Пол", type: "select", options: [["", "—"], ["male", "Мужской"], ["female", "Женский"], ["other", "Иное"], ["unknown", "Не указано"]] },
      { key: "Age", label: "Возраст, лет", type: "number", min: 0, max: 120 },
      { key: "Height_cm", label: "Рост, см", type: "number", step: "0.5", min: 80, max: 230 },
      { key: "Weight_kg", label: "Масса, кг", type: "number", step: "0.1", min: 20, max: 250 },
      { key: "BMI", label: "BMI", type: "number", step: "0.1" }
    ]
  },
  {
    key: "COMPLAINTS",
    title: "Жалобы",
    fields: [
      { key: "Main_complaint", label: "Основная жалоба", type: "textarea", placeholder: "Одышка, боли в груди, отёки, перебои..." },
      { key: "Complaint_duration", label: "Длительность жалоб", type: "text", placeholder: "Например: 6 месяцев" },
      { key: "Onset_context", label: "Контекст начала симптомов", type: "textarea" }
    ]
  },
  {
    key: "RISK_FACTORS",
    title: "Факторы риска",
    fields: [
      { key: "Smoking_status", label: "Курение", type: "select", options: [["", "—"], ["never", "Никогда"], ["former", "Бросил(а)"], ["current", "Курит сейчас"]] },
      { key: "Hypertension", label: "Артериальная гипертензия", type: "select", options: [["", "—"], ["yes", "Да"], ["no", "Нет"], ["unknown", "Неизвестно"]] },
      { key: "Diabetes_mellitus", label: "Сахарный диабет", type: "select", options: [["", "—"], ["type2", "СД2"], ["type1", "СД1"], ["no", "Нет"], ["unknown", "Неизвестно"]] },
      { key: "Dyslipidemia", label: "Дислипидемия", type: "select", options: [["", "—"], ["yes", "Да"], ["no", "Нет"], ["unknown", "Неизвестно"]] },
      { key: "Obesity_or_Metabolic_syndrome", label: "Ожирение / метаболический синдром", type: "text" },
      { key: "Chronic_kidney_disease_stage", label: "ХБП, стадия", type: "text" },
      { key: "Family_history_early_CVD", label: "Семейный анамнез раннего ССЗ", type: "textarea" },
      { key: "Physical_activity_level", label: "Физическая активность", type: "textarea" },
      { key: "Alcohol_and_other_substances", label: "Алкоголь и другие вещества", type: "textarea" }
    ]
  },
  {
    key: "PAST_EVENTS",
    title: "Анамнез и события",
    fields: [
      { key: "Prior_MI", label: "Перенесённый инфаркт миокарда", type: "textarea" },
      { key: "Prior_stroke_TIA", label: "Инсульт / ТИА в анамнезе", type: "textarea" },
      { key: "Prior_PE_DVT", label: "ТЭЛА / ТГВ в анамнезе", type: "textarea" },
      { key: "Prior_cardiac_surgeries", label: "Кардиохирургические операции", type: "textarea" },
      { key: "Prior_congenital_heart_defect_and_surgeries", label: "ВПС и операции", type: "textarea" },
      { key: "History_myocarditis_pericarditis", label: "Миокардиты / перикардиты", type: "textarea" },
      { key: "Other_major_diseases", label: "Другие важные заболевания", type: "textarea" }
    ]
  },
  {
    key: "KNOWN_CVD_DIAGNOSES",
    title: "Известные СС-диагнозы",
    fields: [
      { key: "Known_IHD", label: "Известная ИБС", type: "textarea" },
      { key: "Known_HF", label: "Хроническая сердечная недостаточность", type: "textarea" },
      { key: "Known_arrhythmias", label: "Аритмии", type: "textarea" },
      { key: "Known_valvular_disease", label: "Клапанные пороки", type: "textarea" },
      { key: "Known_aortic_or_peripheral_arterial_disease", label: "Аорта / периферические артерии", type: "textarea" },
      { key: "Known_pulmonary_hypertension", label: "Лёгочная гипертензия", type: "textarea" },
      { key: "Known_congenital_heart_disease", label: "Врожденные пороки сердца", type: "textarea" }
    ]
  },
  {
    key: "PHYSICAL_EXAM",
    title: "Осмотр",
    fields: [
      { key: "Blood_pressure_right_systolic_mmHg", label: "АД справа, сист.", type: "number" },
      { key: "Blood_pressure_right_diastolic_mmHg", label: "АД справа, диаст.", type: "number" },
      { key: "Blood_pressure_left_systolic_mmHg", label: "АД слева, сист.", type: "number" },
      { key: "Blood_pressure_left_diastolic_mmHg", label: "АД слева, диаст.", type: "number" },
      { key: "Heart_rate_bpm", label: "ЧСС", type: "number" },
      { key: "Resp_rate", label: "ЧДД", type: "number" },
      { key: "SpO2_room_air_percent", label: "SpO2, %", type: "number", step: "0.1" },
      { key: "Peripheral_edema", label: "Периферические отёки", type: "textarea" },
      { key: "Lung_auscultation", label: "Аускультация лёгких", type: "textarea" },
      { key: "Heart_auscultation", label: "Аускультация сердца", type: "textarea" },
      { key: "Peripheral_pulses", label: "Периферические пульсы", type: "textarea" }
    ]
  },
  {
    key: "LABS_CBC",
    title: "ОАК",
    fields: [
      { key: "Hb_g_L", label: "Hb, г/л", type: "number" },
      { key: "WBC_10e9_L", label: "WBC, 10^9/л", type: "number", step: "0.1" },
      { key: "PLT_10e9_L", label: "PLT, 10^9/л", type: "number" }
    ]
  },
  {
    key: "LABS_BIOCHEM",
    title: "Биохимия",
    fields: [
      { key: "Creatinine_umol_L", label: "Креатинин, мкмоль/л", type: "number" },
      { key: "eGFR_ml_min_1_73m2", label: "СКФ, мл/мин/1.73 м2", type: "number" },
      { key: "ALT_U_L", label: "АЛТ, Ед/л", type: "number" },
      { key: "AST_U_L", label: "АСТ, Ед/л", type: "number" },
      { key: "Na_mmol_L", label: "Na, ммоль/л", type: "number", step: "0.1" },
      { key: "K_mmol_L", label: "K, ммоль/л", type: "number", step: "0.1" },
      { key: "Mg_mmol_L", label: "Mg, ммоль/л", type: "number", step: "0.01" },
      { key: "Glucose_fasting_mmol_L", label: "Глюкоза натощак", type: "number", step: "0.1" },
      { key: "HbA1c_percent", label: "HbA1c, %", type: "number", step: "0.1" }
    ]
  },
  {
    key: "LABS_LIPIDS",
    title: "Липидный профиль",
    fields: [
      { key: "Total_cholesterol_mmol_L", label: "Общий холестерин", type: "number", step: "0.1" },
      { key: "LDL_mmol_L", label: "ЛПНП", type: "number", step: "0.1" },
      { key: "HDL_mmol_L", label: "ЛПВП", type: "number", step: "0.1" },
      { key: "Triglycerides_mmol_L", label: "Триглицериды", type: "number", step: "0.1" }
    ]
  },
  {
    key: "LABS_CARDIAC_MARKERS",
    title: "Кардиомаркеры",
    fields: [
      { key: "Troponin_ng_L", label: "Тропонин, нг/л", type: "number" },
      { key: "CKMB_U_L", label: "КФК-МВ, Ед/л", type: "number" },
      { key: "NT_proBNP_pg_ml", label: "NT-proBNP, пг/мл", type: "number" }
    ]
  },
  {
    key: "LABS_COAGULATION",
    title: "Коагулограмма",
    fields: [
      { key: "INR", label: "INR", type: "number", step: "0.01" },
      { key: "APTT_sec", label: "APTT, сек", type: "number", step: "0.1" }
    ]
  },
  {
    key: "ECG_AND_BP_MONITORING",
    title: "ЭКГ и мониторинг",
    fields: [
      { key: "Resting_ECG_summary", label: "ЭКГ покоя, сводка", type: "textarea" },
      { key: "Holter_ECG_summary", label: "Холтер-ЭКГ, сводка", type: "textarea" },
      { key: "ABPM_summary", label: "СМАД, сводка", type: "textarea" }
    ]
  },
  {
    key: "ECHOCARDIOGRAPHY",
    title: "Эхокардиография",
    fields: [
      { key: "LVEDD_mm", label: "КДР ЛЖ, мм", type: "number" },
      { key: "LVESD_mm", label: "КСР ЛЖ, мм", type: "number" },
      { key: "LVEF_percent", label: "ФВ ЛЖ, %", type: "number", step: "0.1" },
      { key: "LA_diameter_mm", label: "ЛП, мм", type: "number" },
      { key: "RV_diameter_mm", label: "ПЖ, мм", type: "number" },
      { key: "PASP_mmHg", label: "PASP, мм рт.ст.", type: "number" },
      { key: "IVS_thickness_mm", label: "МЖП, мм", type: "number", step: "0.1" },
      { key: "PW_LV_thickness_mm", label: "Задняя стенка ЛЖ, мм", type: "number", step: "0.1" },
      { key: "Mitral_valve_area_cm2", label: "Площадь МК, см2", type: "number", step: "0.01" },
      { key: "Aortic_valve_area_cm2", label: "Площадь АК, см2", type: "number", step: "0.01" },
      { key: "Valvular_regurgitation", label: "Клапанные регургитации", type: "textarea" },
      { key: "Pericardial_effusion", label: "Перикардиальный выпот", type: "textarea" }
    ]
  },
  {
    key: "FUNCTIONAL_TESTS",
    title: "Функциональные тесты",
    fields: [
      { key: "Exercise_test_summary", label: "Нагрузочный тест", type: "textarea" },
      { key: "METs_max", label: "Макс. METs", type: "number", step: "0.1" },
      { key: "SixMWT_distance_m", label: "6-минутный тест, м", type: "number" }
    ]
  },
  {
    key: "CORONARY_AND_VASCULAR_IMAGING",
    title: "Визуализация",
    fields: [
      { key: "Coronary_angiography_or_CTCA", label: "Коронарография / КТКА", type: "textarea" },
      { key: "Aorta_CT_MR", label: "КТ/МРТ аорты", type: "textarea" },
      { key: "Carotid_ultrasound", label: "УЗИ сонных артерий", type: "textarea" },
      { key: "Peripheral_artery_imaging", label: "Периферические артерии", type: "textarea" },
      { key: "Venous_ultrasound", label: "УЗИ вен", type: "textarea" }
    ]
  },
  {
    key: "DEVICES_AND_PROCEDURES",
    title: "Устройства и процедуры",
    fields: [
      { key: "Coronary_stents", label: "Стенты коронарных артерий", type: "textarea" },
      { key: "CABG_details", label: "АКШ, детали", type: "textarea" },
      { key: "Valve_surgery_or_prosthesis", label: "Клапанные протезы/пластика", type: "textarea" },
      { key: "Pacemaker_ICD_CRT", label: "ЭКС / ICD / CRT", type: "textarea" },
      { key: "Other_advanced_therapies", label: "Другие терапии", type: "textarea" }
    ]
  },
  {
    key: "CURRENT_MEDICATIONS",
    title: "Текущая терапия",
    fields: [
      { key: "Antiplatelets", label: "Антиагреганты", type: "textarea" },
      { key: "Anticoagulants", label: "Антикоагулянты", type: "textarea" },
      { key: "Beta_blockers", label: "Бета-блокаторы", type: "textarea" },
      { key: "ACEi_ARB_ARNI", label: "иАПФ / БРА / ARNI", type: "textarea" },
      { key: "MRA", label: "MRA", type: "textarea" },
      { key: "SGLT2_inhibitors", label: "SGLT2-ингибиторы", type: "textarea" },
      { key: "Diuretics", label: "Диуретики", type: "textarea" },
      { key: "Antiarrhythmics", label: "Антиаритмики", type: "textarea" },
      { key: "Lipid_lowering", label: "Липидснижающая терапия", type: "textarea" },
      { key: "Antidiabetic_drugs", label: "Гипогликемические препараты", type: "textarea" },
      { key: "Other_relevant_drugs", label: "Другое", type: "textarea" }
    ]
  },
  {
    key: "SCORES_AND_CLASSES",
    title: "Шкалы",
    fields: [
      { key: "NYHA_class", label: "NYHA класс", type: "text" },
      { key: "Angina_CCS_class", label: "Класс стенокардии CCS", type: "text" },
      { key: "Killip_class_if_acute_MI", label: "Killip при ОИМ", type: "text" },
      { key: "CHA2DS2_VASc", label: "CHA2DS2-VASc", type: "number" },
      { key: "HAS_BLED", label: "HAS-BLED", type: "number" }
    ]
  },
  {
    key: "FINAL_DIAGNOSES",
    title: "Итоговые диагнозы врача",
    fields: [
      { key: "Main_cardiovascular_diagnosis_text", label: "Основной СС-диагноз", type: "textarea" },
      { key: "Other_cardiovascular_diagnoses", label: "Другие СС-диагнозы", type: "textarea" },
      { key: "Non_cardiac_comorbidities", label: "Несердечные коморбидности", type: "textarea" },
      { key: "ICD10_codes", label: "Коды МКБ-10, через ;", type: "text", placeholder: "I21.0; I50.2; I10" }
    ]
  },
  {
    key: "MODEL_OUTPUT",
    title: "Ответ модели",
    fields: [
      { key: "Final_model_diagnosis", label: "Диагноз модели", type: "textarea" },
      { key: "Model_ICD10_codes", label: "Коды МКБ-10 модели", type: "text", placeholder: "I21.0; I50.2; I10" },
      { key: "Model_treatment_recommendations", label: "Рекомендации по лечению", type: "textarea" },
      { key: "Model_rehabilitation_recommendations", label: "Реабилитация и образ жизни", type: "textarea" }
    ]
  }
];
