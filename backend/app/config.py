"""App settings, read from environment variables or a .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite for local development; Postgres in production, e.g.
    # postgresql+psycopg://reportbox:reportbox@localhost:5432/reportbox
    database_url: str = "sqlite:///./reportbox.db"

    # Create tables automatically on start (handy locally). Production runs Alembic migrations instead.
    auto_create_tables: bool = True

    # Used to hash login codes. Use a long random value in production.
    secret_key: str = "dev-only-change-me"

    # Fernet key that encrypts report PDFs on disk.
    # Generate one: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    file_encryption_key: str = ""

    storage_dir: str = "./storage"

    # Where patients and doctors open links (the website).
    public_base_url: str = "http://localhost:3000"

    # Login cookies. Set COOKIE_SECURE=true when the site runs on HTTPS (always in production).
    cookie_secure: bool = False

    # SMS: "console" prints messages in the terminal; "bulksmsbd" uses BulkSMSBD's API;
    # "http" is a generic adapter you can edit in app/messaging.py for another aggregator.
    sms_provider: str = "console"
    sms_api_key: str = ""
    sms_sender_id: str = ""  # default sender ID; each lab can have its own registered one
    sms_http_url: str = ""
    sms_http_api_key: str = ""

    # Other websites allowed to call the API from a browser. Empty = none (the normal setup).
    # WhatsApp (Meta Cloud API). Reports go by WhatsApp only to patients who turned it on in the
    # app; if WhatsApp fails, the report goes by SMS. See docs/DEPLOY.md for the template to create.
    whatsapp_enabled: bool = False
    wa_api_version: str = "v23.0"
    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_app_secret: str = ""  # checks that delivery updates really come from Meta
    wa_verify_token: str = ""  # any random text; also typed into Meta's webhook settings
    wa_template_report_ready: str = "report_ready"
    wa_template_lang_bn: str = "bn"
    wa_template_lang_en: str = "en"

    # Billing
    vat_percent: float = 0.0  # confirm the VAT rate (and any startup exemption) with an accountant
    payment_bkash_number: str = ""
    payment_nagad_number: str = ""

    cors_origins: str = ""

    # Interactive API docs at /api/docs. Turn off in production.
    show_api_docs: bool = True

    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 5
    otp_max_requests_per_15_min: int = 3
    staff_login_max_failures: int = 5  # per email per 15 minutes
    patient_session_days: int = 90
    staff_session_hours: int = 12
    share_ttl_hours: int = 24
    max_pdf_mb: int = 10
    min_password_length: int = 10

    # Reminder SMS are only sent between these hours (Bangladesh time).
    reminder_start_hour: int = 10
    reminder_end_hour: int = 19


@lru_cache
def get_settings() -> Settings:
    return Settings()
