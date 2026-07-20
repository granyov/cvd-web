from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .auth import hash_password, utc_now
from .config import Config
from .lmstudio import USER_PROMPT_TEMPLATE
from .versions import MODEL_PROMPT_VERSION


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'user')) DEFAULT 'user',
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT '',
  ip_address TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  patient_id TEXT NOT NULL DEFAULT '',
  data_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('success', 'error')),
  api_url TEXT NOT NULL,
  model TEXT NOT NULL,
  request_json TEXT NOT NULL,
  response_json TEXT,
  parsed_output_json TEXT,
  prompt_version TEXT NOT NULL DEFAULT '',
  schema_version TEXT NOT NULL DEFAULT '',
  output_schema_version TEXT NOT NULL DEFAULT '',
  settings_snapshot_json TEXT NOT NULL DEFAULT '{}',
  deidentified_input_json TEXT,
  phi_signals_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  tokens_per_second REAL NOT NULL DEFAULT 0,
  finish_reason TEXT NOT NULL DEFAULT '',
  request_source TEXT NOT NULL DEFAULT 'interactive',
  queue_wait_ms INTEGER NOT NULL DEFAULT 0,
  input_data_hash TEXT NOT NULL DEFAULT '',
  input_patient_data_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inference_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'error', 'cancelled')),
  request_json TEXT NOT NULL,
  model_request_id INTEGER REFERENCES model_requests(id) ON DELETE SET NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS text_preparation_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'error', 'cancelled')),
  request_json TEXT NOT NULL,
  input_sha256 TEXT NOT NULL,
  data_preparation_request_id INTEGER REFERENCES data_preparation_requests(id) ON DELETE SET NULL,
  import_id INTEGER REFERENCES data_imports(id) ON DELETE SET NULL,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_request_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_request_id INTEGER NOT NULL REFERENCES model_requests(id) ON DELETE CASCADE,
  case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
  reviewer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating TEXT NOT NULL CHECK (rating IN ('useful', 'partial', 'wrong', 'unsafe')),
  issue_types_json TEXT NOT NULL DEFAULT '[]',
  corrected_diagnosis TEXT NOT NULL DEFAULT '',
  corrected_icd10_json TEXT NOT NULL DEFAULT '[]',
  comment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(model_request_id, reviewer_user_id)
);

CREATE TABLE IF NOT EXISTS data_imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
  source_format TEXT NOT NULL,
  mapping_version TEXT NOT NULL DEFAULT '',
  filename TEXT NOT NULL DEFAULT '',
  content_sha256 TEXT NOT NULL,
  mapped_fields INTEGER NOT NULL DEFAULT 0,
  mapped_paths_json TEXT NOT NULL DEFAULT '[]',
  warning_count INTEGER NOT NULL DEFAULT 0,
  selected_paths_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL CHECK (status IN ('previewed', 'applied')) DEFAULT 'previewed',
  created_at TEXT NOT NULL,
  applied_at TEXT
);

CREATE TABLE IF NOT EXISTS data_preparation_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('success', 'error')),
  model TEXT NOT NULL,
  input_sha256 TEXT NOT NULL,
  chunk_count INTEGER NOT NULL DEFAULT 1,
  mapped_fields INTEGER NOT NULL DEFAULT 0,
  warning_count INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  finish_reason TEXT NOT NULL DEFAULT '',
  queue_wait_ms INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS text_preparation_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  data_preparation_request_id INTEGER REFERENCES data_preparation_requests(id) ON DELETE SET NULL,
  import_id INTEGER REFERENCES data_imports(id) ON DELETE SET NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('prepared', 'applied', 'archived')) DEFAULT 'prepared',
  source_label TEXT NOT NULL DEFAULT '',
  input_sha256 TEXT NOT NULL,
  corrected_text TEXT NOT NULL DEFAULT '',
  mappings_json TEXT NOT NULL DEFAULT '[]',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  mapped_fields INTEGER NOT NULL DEFAULT 0,
  warning_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  applied_at TEXT
);

CREATE TABLE IF NOT EXISTS batch_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')),
  total_items INTEGER NOT NULL DEFAULT 0,
  completed_items INTEGER NOT NULL DEFAULT 0,
  success_items INTEGER NOT NULL DEFAULT 0,
  error_items INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS batch_job_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_job_id INTEGER NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'success', 'error', 'cancelled')),
  model_request_id INTEGER REFERENCES model_requests(id) ON DELETE SET NULL,
  error TEXT,
  started_at TEXT,
  finished_at TEXT,
  UNIQUE(batch_job_id, case_id)
);

CREATE TABLE IF NOT EXISTS gold_cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  expected_diagnosis TEXT NOT NULL DEFAULT '',
  expected_icd10_json TEXT NOT NULL DEFAULT '[]',
  expected_red_flags_json TEXT NOT NULL DEFAULT '[]',
  expected_missing_data_json TEXT NOT NULL DEFAULT '[]',
  expected_abstain INTEGER NOT NULL DEFAULT 0,
  severity TEXT NOT NULL DEFAULT 'medium',
  notes TEXT NOT NULL DEFAULT '',
  created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(case_id)
);

CREATE TABLE IF NOT EXISTS gold_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('completed', 'empty')),
  total_items INTEGER NOT NULL DEFAULT 0,
  evaluated_items INTEGER NOT NULL DEFAULT 0,
  avg_score_percent INTEGER NOT NULL DEFAULT 0,
  settings_snapshot_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  finished_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gold_run_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gold_run_id INTEGER NOT NULL REFERENCES gold_runs(id) ON DELETE CASCADE,
  gold_case_id INTEGER NOT NULL REFERENCES gold_cases(id) ON DELETE CASCADE,
  case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  model_request_id INTEGER REFERENCES model_requests(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('evaluated', 'pending')),
  score_percent INTEGER NOT NULL DEFAULT 0,
  evaluation_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(gold_run_id, gold_case_id)
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  id TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_cases_user_updated ON cases(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_requests_user_created ON model_requests(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inference_jobs_user_created ON inference_jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inference_jobs_status_created ON inference_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_text_jobs_user_created ON text_preparation_jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_text_jobs_status_created ON text_preparation_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reviews_request ON model_request_reviews(model_request_id);
CREATE INDEX IF NOT EXISTS idx_reviews_created ON model_request_reviews(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_imports_user_created ON data_imports(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_preparation_user_created ON data_preparation_requests(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_text_preparation_user_created ON text_preparation_items(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_status_created ON batch_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_batch_items_job_status ON batch_job_items(batch_job_id, status, id);
CREATE INDEX IF NOT EXISTS idx_gold_cases_updated ON gold_cases(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_gold_runs_created ON gold_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gold_run_items_run ON gold_run_items(gold_run_id, status);
"""

DEFAULT_ADMIN_PASSWORDS = {
    "admin12345",
    "change-this-long-password",
}

SCHEMA_MIGRATIONS = [
    "0001_initial_schema",
    "0002_model_request_versions_and_metrics",
    "0003_import_mapping_metadata",
    "0004_text_preparation_queue_metrics",
    "0005_text_preparation_items",
    "0006_gold_set_validation",
    "0007_gold_set_quality_targets",
    "0008_ai_gateway_multi_headers",
    "0009_production_runtime_settings",
    "0010_gold_release_gate",
    "0011_inference_jobs",
    "0012_q8_streaming_defaults",
    "0013_text_preparation_jobs",
    "0014_prompt_v5_treatment_recommendations",
    "0015_active_prompt_version_follows_template",
]

# Прежние дефолтные значения active_prompt_version. Миграция 0014 обновляла шаблон,
# но не версию, поэтому анализы на промпте v5 помечались как v4.
LEGACY_PROMPT_VERSIONS = ("cvd-cds-prompt-v4", "cvd-cds-prompt-v3")

# Предыдущие дефолтные шаблоны промпта. Если администратор не менял шаблон,
# миграция подставляет актуальный; кастомные шаблоны остаются нетронутыми.
LEGACY_PROMPT_TEMPLATE_PREFIXES = (
    "You are a clinical decision support component working only with synthetic",
)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        suppress = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return suppress


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(config: Config) -> None:
    with connect(config.db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        apply_migrations(conn)
        seed_default_settings(conn, config)
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count == 0:
            if config.production_mode and config.admin_password in DEFAULT_ADMIN_PASSWORDS:
                raise RuntimeError(
                    "Refusing to bootstrap production with the default administrator password. "
                    "Set CVD_ADMIN_PASSWORD to a strong unique value before first start."
                )
            now = utc_now()
            conn.execute(
                """
                INSERT INTO users
                  (email, full_name, password_hash, role, is_active, must_change_password, created_at, updated_at)
                VALUES (?, ?, ?, 'admin', 1, ?, ?, ?)
                """,
                (
                    config.admin_email.lower().strip(),
                    "Initial administrator",
                    hash_password(config.admin_password),
                    1 if config.admin_password in DEFAULT_ADMIN_PASSWORDS else 0,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_log (action, target_type, target_id, details_json, created_at)
                VALUES ('bootstrap_admin', 'user', ?, ?, ?)
                """,
                (
                    config.admin_email.lower().strip(),
                    json.dumps({"email": config.admin_email.lower().strip()}, ensure_ascii=False),
                    now,
                ),
            )


SETTINGS_KEYS = [
    "app_name",
    "organization_name",
    "system_description",
    "usage_notice",
    "support_contact",
    "default_theme",
    "ai_gateway_profile",
    "ai_gateway_headers_json",
    "ai_gateway_auth_header_name",
    "ai_gateway_auth_header_value",
    "lm_studio_api_url",
    "lm_studio_model",
    "text_structuring_model",
    "lm_studio_timeout_seconds",
    "lm_studio_max_tokens",
    "lm_studio_context_tokens",
    "lm_studio_temperature",
    "lm_studio_structured_output",
    "lm_studio_max_concurrent",
    "lm_studio_queue_limit",
    "lm_studio_per_user_limit",
    "lm_studio_queue_timeout_seconds",
    "inference_queue_backend",
    "inference_queue_dsn",
    "rate_limit_backend",
    "rate_limit_dsn",
    "inference_worker_mode",
    "deidentify_before_model",
    "active_prompt_version",
    "active_prompt_template",
    "gold_min_score_percent",
    "max_request_bytes",
]


def default_settings(config: Config) -> dict[str, tuple[str, str]]:
    return {
        "app_name": ("CVD Web", "Название приложения в интерфейсе."),
        "organization_name": ("Health Heart", "Организация или проект."),
        "system_description": (
            "Система структурирования сердечно-сосудистых кейсов и анализа через локальную LLM.",
            "Краткое описание системы.",
        ),
        "usage_notice": (
            "Только для образовательных и исследовательских сценариев. Не использовать для диагностики и лечения реальных пациентов.",
            "Предупреждение для пользователей.",
        ),
        "support_contact": ("", "Контакт администратора или поддержки."),
        "default_theme": ("light", "Тема по умолчанию: light или dark."),
        "ai_gateway_profile": ("local", "Профиль подключения к AI Gateway: local, lan, wsl2 или cloudflared."),
        "ai_gateway_headers_json": ("[]", "JSON-список дополнительных HTTP-заголовков для tunnel/auth."),
        "ai_gateway_auth_header_name": ("", "Имя дополнительного HTTP-заголовка для tunnel/auth, например Authorization."),
        "ai_gateway_auth_header_value": ("", "Значение дополнительного HTTP-заголовка для tunnel/auth."),
        "lm_studio_api_url": (config.lm_studio_api_url, "OpenAI-compatible endpoint LM Studio."),
        "lm_studio_model": (config.lm_studio_model, "Имя модели для запросов."),
        "text_structuring_model": ("", "Отдельная модель подготовки текста; пустое значение использует основную модель."),
        "lm_studio_timeout_seconds": (str(config.lm_studio_timeout_seconds), "Таймаут запроса к LM Studio в секундах."),
        "lm_studio_max_tokens": (str(config.lm_studio_max_tokens), "max_tokens для ответа модели."),
        "lm_studio_context_tokens": ("0", "Контекст загруженной модели в токенах; заполняется health-check, 0 — не проверять объём."),
        "lm_studio_temperature": (str(config.lm_studio_temperature), "temperature для запроса к LM Studio."),
        "lm_studio_structured_output": ("1", "Запрашивать JSON Schema structured output у LM Studio: 1 или 0."),
        "lm_studio_max_concurrent": ("1", "Максимальное число одновременных генераций LM Studio."),
        "lm_studio_queue_limit": ("64", "Максимальное число запросов, ожидающих LM Studio."),
        "lm_studio_per_user_limit": ("2", "Максимальное число активных и ожидающих AI-запросов одного пользователя."),
        "lm_studio_queue_timeout_seconds": ("1800", "Максимальное ожидание свободного слота LM Studio в секундах."),
        "inference_queue_backend": ("memory", "Backend очереди: memory, redis или postgresql. Redis/PostgreSQL требуют отдельного worker-адаптера."),
        "inference_queue_dsn": ("", "DSN внешней очереди Redis/PostgreSQL без публикации пользователям."),
        "rate_limit_backend": ("memory", "Backend rate limit: memory, redis или postgresql. Production требует внешний backend."),
        "rate_limit_dsn": ("", "DSN внешнего rate limiter без публикации пользователям."),
        "inference_worker_mode": ("in_process", "Режим выполнения AI-задач: in_process или external."),
        "deidentify_before_model": ("1", "Удалять явные идентификаторы из данных перед отправкой в LM Studio: 1 или 0."),
        "active_prompt_version": (MODEL_PROMPT_VERSION, "Активная версия prompt для запросов к модели."),
        "active_prompt_template": (USER_PROMPT_TEMPLATE, "Шаблон user prompt. Должен содержать {{PATIENT_JSON}}."),
        "gold_min_score_percent": ("80", "Минимальный средний score Gold Set для release gate."),
        "max_request_bytes": (str(config.max_request_bytes), "Максимальный размер JSON-запроса пользователя."),
    }


def seed_default_settings(conn: sqlite3.Connection, config: Config) -> None:
    now = utc_now()
    for key, (value, description) in default_settings(config).items():
        conn.execute(
            """
            INSERT OR IGNORE INTO app_settings (key, value, description, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, value, description, now),
        )


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          id TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )
    applied_migration_ids = {
        row["id"] for row in conn.execute("SELECT id FROM schema_migrations").fetchall()
    }
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_requests)").fetchall()}
    migrations = {
        "prompt_version": "ALTER TABLE model_requests ADD COLUMN prompt_version TEXT NOT NULL DEFAULT ''",
        "schema_version": "ALTER TABLE model_requests ADD COLUMN schema_version TEXT NOT NULL DEFAULT ''",
        "output_schema_version": "ALTER TABLE model_requests ADD COLUMN output_schema_version TEXT NOT NULL DEFAULT ''",
        "settings_snapshot_json": "ALTER TABLE model_requests ADD COLUMN settings_snapshot_json TEXT NOT NULL DEFAULT '{}'",
        "deidentified_input_json": "ALTER TABLE model_requests ADD COLUMN deidentified_input_json TEXT",
        "phi_signals_json": "ALTER TABLE model_requests ADD COLUMN phi_signals_json TEXT NOT NULL DEFAULT '[]'",
        "prompt_tokens": "ALTER TABLE model_requests ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0",
        "completion_tokens": "ALTER TABLE model_requests ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0",
        "total_tokens": "ALTER TABLE model_requests ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0",
        "tokens_per_second": "ALTER TABLE model_requests ADD COLUMN tokens_per_second REAL NOT NULL DEFAULT 0",
        "finish_reason": "ALTER TABLE model_requests ADD COLUMN finish_reason TEXT NOT NULL DEFAULT ''",
        "request_source": "ALTER TABLE model_requests ADD COLUMN request_source TEXT NOT NULL DEFAULT 'interactive'",
        "queue_wait_ms": "ALTER TABLE model_requests ADD COLUMN queue_wait_ms INTEGER NOT NULL DEFAULT 0",
        "input_data_hash": "ALTER TABLE model_requests ADD COLUMN input_data_hash TEXT NOT NULL DEFAULT ''",
        "input_patient_data_json": "ALTER TABLE model_requests ADD COLUMN input_patient_data_json TEXT",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)

    conn.execute(
        """
        UPDATE model_requests
        SET status = 'error',
            error = COALESCE(NULLIF(error, ''), 'Ответ LM Studio был обрезан по лимиту max_tokens.'),
            parsed_output_json = NULL
        WHERE status = 'success' AND finish_reason = 'length'
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inference_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
          status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'error', 'cancelled')),
          request_json TEXT NOT NULL,
          model_request_id INTEGER REFERENCES model_requests(id) ON DELETE SET NULL,
          error TEXT,
          created_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inference_jobs_user_created ON inference_jobs(user_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inference_jobs_status_created ON inference_jobs(status, created_at)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS text_preparation_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'error', 'cancelled')),
          request_json TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          data_preparation_request_id INTEGER REFERENCES data_preparation_requests(id) ON DELETE SET NULL,
          import_id INTEGER REFERENCES data_imports(id) ON DELETE SET NULL,
          result_json TEXT,
          error TEXT,
          created_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_text_jobs_user_created ON text_preparation_jobs(user_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_text_jobs_status_created ON text_preparation_jobs(status, created_at)")
    text_job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(text_preparation_jobs)").fetchall()}
    if text_job_columns and "result_json" not in text_job_columns:
        conn.execute("ALTER TABLE text_preparation_jobs ADD COLUMN result_json TEXT")

    import_columns = {row["name"] for row in conn.execute("PRAGMA table_info(data_imports)").fetchall()}
    if import_columns and "mapping_version" not in import_columns:
        conn.execute("ALTER TABLE data_imports ADD COLUMN mapping_version TEXT NOT NULL DEFAULT ''")
    if import_columns and "mapped_paths_json" not in import_columns:
        conn.execute("ALTER TABLE data_imports ADD COLUMN mapped_paths_json TEXT NOT NULL DEFAULT '[]'")

    preparation_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(data_preparation_requests)").fetchall()
    }
    if preparation_columns and "finish_reason" not in preparation_columns:
        conn.execute("ALTER TABLE data_preparation_requests ADD COLUMN finish_reason TEXT NOT NULL DEFAULT ''")
    if preparation_columns and "chunk_count" not in preparation_columns:
        conn.execute("ALTER TABLE data_preparation_requests ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 1")
    if preparation_columns and "queue_wait_ms" not in preparation_columns:
        conn.execute("ALTER TABLE data_preparation_requests ADD COLUMN queue_wait_ms INTEGER NOT NULL DEFAULT 0")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS text_preparation_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          data_preparation_request_id INTEGER REFERENCES data_preparation_requests(id) ON DELETE SET NULL,
          import_id INTEGER REFERENCES data_imports(id) ON DELETE SET NULL,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          status TEXT NOT NULL CHECK (status IN ('prepared', 'applied', 'archived')) DEFAULT 'prepared',
          source_label TEXT NOT NULL DEFAULT '',
          input_sha256 TEXT NOT NULL,
          corrected_text TEXT NOT NULL DEFAULT '',
          mappings_json TEXT NOT NULL DEFAULT '[]',
          warnings_json TEXT NOT NULL DEFAULT '[]',
          mapped_fields INTEGER NOT NULL DEFAULT 0,
          warning_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          applied_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_text_preparation_user_created ON text_preparation_items(user_id, created_at DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gold_cases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          expected_diagnosis TEXT NOT NULL DEFAULT '',
          expected_icd10_json TEXT NOT NULL DEFAULT '[]',
          expected_red_flags_json TEXT NOT NULL DEFAULT '[]',
          expected_missing_data_json TEXT NOT NULL DEFAULT '[]',
          expected_abstain INTEGER NOT NULL DEFAULT 0,
          severity TEXT NOT NULL DEFAULT 'medium',
          notes TEXT NOT NULL DEFAULT '',
          created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(case_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gold_cases_updated ON gold_cases(updated_at DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gold_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          status TEXT NOT NULL CHECK (status IN ('completed', 'empty')),
          total_items INTEGER NOT NULL DEFAULT 0,
          evaluated_items INTEGER NOT NULL DEFAULT 0,
          avg_score_percent INTEGER NOT NULL DEFAULT 0,
          settings_snapshot_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          finished_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gold_run_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          gold_run_id INTEGER NOT NULL REFERENCES gold_runs(id) ON DELETE CASCADE,
          gold_case_id INTEGER NOT NULL REFERENCES gold_cases(id) ON DELETE CASCADE,
          case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
          model_request_id INTEGER REFERENCES model_requests(id) ON DELETE SET NULL,
          status TEXT NOT NULL CHECK (status IN ('evaluated', 'pending')),
          score_percent INTEGER NOT NULL DEFAULT 0,
          evaluation_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          UNIQUE(gold_run_id, gold_case_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gold_runs_created ON gold_runs(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gold_run_items_run ON gold_run_items(gold_run_id, status)")

    gold_columns = {row["name"] for row in conn.execute("PRAGMA table_info(gold_cases)").fetchall()}
    if gold_columns and "expected_missing_data_json" not in gold_columns:
        conn.execute("ALTER TABLE gold_cases ADD COLUMN expected_missing_data_json TEXT NOT NULL DEFAULT '[]'")
    if gold_columns and "severity" not in gold_columns:
        conn.execute("ALTER TABLE gold_cases ADD COLUMN severity TEXT NOT NULL DEFAULT 'medium'")

    if "0012_q8_streaming_defaults" not in applied_migration_ids:
        conn.execute(
            """
            UPDATE app_settings
            SET value = '4096', updated_at = ?
            WHERE key = 'lm_studio_max_tokens' AND value = '1536'
            """,
            (utc_now(),),
        )

    if "0014_prompt_v5_treatment_recommendations" not in applied_migration_ids:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'active_prompt_template'"
        ).fetchone()
        stored_template = str(row["value"]) if row else ""
        if stored_template.strip().startswith(LEGACY_PROMPT_TEMPLATE_PREFIXES):
            conn.execute(
                "UPDATE app_settings SET value = ?, updated_at = ? WHERE key = 'active_prompt_template'",
                (USER_PROMPT_TEMPLATE, utc_now()),
            )

    if "0015_active_prompt_version_follows_template" not in applied_migration_ids:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'active_prompt_version'"
        ).fetchone()
        stored_version = str(row["value"]).strip() if row else ""
        template_row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'active_prompt_template'"
        ).fetchone()
        stored_template = str(template_row["value"]).strip() if template_row else ""
        # Версию поднимаем только когда шаблон действительно актуальный и версия
        # осталась прежней дефолтной: кастомные значения администратора не трогаем.
        if stored_version in LEGACY_PROMPT_VERSIONS and stored_template == USER_PROMPT_TEMPLATE.strip():
            conn.execute(
                "UPDATE app_settings SET value = ?, updated_at = ? WHERE key = 'active_prompt_version'",
                (MODEL_PROMPT_VERSION, utc_now()),
            )

    applied_at = utc_now()
    for migration_id in SCHEMA_MIGRATIONS:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (migration_id, applied_at),
        )


def get_app_settings(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def get_app_settings_full(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT key, value, description, updated_at FROM app_settings ORDER BY key"
    ).fetchall()
    return rows_to_dicts(rows)


def update_app_settings(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    now = utc_now()
    for key, value in values.items():
        if key not in SETTINGS_KEYS:
            continue
        conn.execute(
            "UPDATE app_settings SET value = ?, updated_at = ? WHERE key = ?",
            (str(value), now, key),
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in rows if row is not None]


def audit(
    conn: sqlite3.Connection,
    *,
    user_id: int | None,
    action: str,
    target_type: str = "",
    target_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (user_id, action, target_type, target_id, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            action,
            target_type,
            str(target_id),
            json.dumps(details or {}, ensure_ascii=False),
            utc_now(),
        ),
    )
