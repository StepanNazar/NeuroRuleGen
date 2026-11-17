from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    postgres_user: str = "neurorulegen"
    postgres_password: str
    postgres_db: str = "neurorulegen"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    secret_key: str
    password_pepper: str
    cookies_secure: bool = False
    hcaptcha_sitekey: str
    hcaptcha_secret: str
    brevo_api_key: str
    brevo_sender_name: str
    brevo_sender_email: str
    activation_token_expiration_minutes: int
    password_reset_token_expiration_minutes: int
    email_jwt_secret: str
    base_url: str
    fernet_key: str
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = ""
    github_app_slug: str = ""

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

@lru_cache
def get_settings() -> Settings:
    return Settings()