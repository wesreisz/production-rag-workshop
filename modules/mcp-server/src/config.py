from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    api_endpoint: str
    api_key: str

    @field_validator("api_endpoint")
    @classmethod
    def endpoint_must_start_with_http(cls, v):
        if len(v) < 10:
            raise ValueError("api_endpoint must be at least 10 characters")
        if not v.startswith("http"):
            raise ValueError("api_endpoint must start with http")
        return v

    @field_validator("api_key")
    @classmethod
    def api_key_min_length(cls, v):
        if len(v) < 10:
            raise ValueError("api_key must be at least 10 characters")
        return v


@lru_cache
def get_settings():
    return Settings()
