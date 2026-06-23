from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Odoo connection settings
    ODOO_URL: str
    ODOO_DB: str
    ODOO_USER: str
    ODOO_PASSWORD: str

    # Google connection settings
    GOOGLE_CREDENTIAL_SERVICE_FILE: str
    GOOGLE_PROJECT_ID: str
    GOOGLE_LOCATION: str

    # Big Query settings
    BQ_DATASET_RAW: str
    BQ_DATASET_CONTROL: str

    # Pipeline tuning (env-overridable)
    BATCH_SIZE: int = 1000

    model_config = SettingsConfigDict(env_file=".env")
