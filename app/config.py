import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./aereo.db")
    upload_bytes: int = 10 * 1024 * 1024
    expanded_bytes: int = 50 * 1024 * 1024
    zip_members: int = 100
    features: int = 10_000
    vertices: int = 500_000
    timeout_seconds: int = 30
    concurrent_jobs: int = 2
