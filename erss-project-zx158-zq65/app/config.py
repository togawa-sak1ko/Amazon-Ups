from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    app_name: str = "team1c-amazon"
    app_host: str = "0.0.0.0"
    app_port: int = 8080

    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/amazon"
    sync_database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/amazon"

    amazon_host: str = "web"
    amazon_port: int = 8080
    ups_host: str = "host.docker.internal"
    ups_port: int = 8081

    world_host: str = "host.docker.internal"
    world_port: int = 23456
    world_id: Optional[int] = None
    world_sim_speed: int = 100
    worker_poll_seconds: float = 1.0

    warehouse_id: int = 1
    warehouse_x: int = 10
    warehouse_y: int = 10

    @property
    def ups_base_url(self) -> str:
        return f"http://{self.ups_host}:{self.ups_port}"

    @field_validator("world_id", mode="before")
    @classmethod
    def empty_world_id_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
