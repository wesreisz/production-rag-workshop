from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    api_endpoint: str = Field(..., min_length=10)
    api_key: str = Field(..., min_length=10)

    @field_validator("api_endpoint")
    @classmethod
    def validate_api_endpoint_scheme(cls, v: str) -> str:
        if not v.startswith("http"):
            raise ValueError("api_endpoint must start with http:// or https://")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
