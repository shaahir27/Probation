"""Configuration settings and engine tunables.

Authority: docs/ENGINE_SPEC.md section 12 and docs/TECH_STACK_AND_REPO.md section 4.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """System-wide configuration settings loaded from environment and defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM Settings (Nebius Token Factory) ---
    llm_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    llm_api_key: str = ""
    model_reader: str = "nvidia/nemotron-mini-4b-instruct"
    model_writer: str = "nvidia/nemotron-4-340b-instruct"
    model_exam_edits: str = "nvidia/nemotron-mini-4b-instruct"
    model_synth: str = "nvidia/nemotron-mini-4b-instruct"
    llm_max_concurrency: int = 8
    llm_timeout_s: int = 60
    llm_max_retries: int = 3
    budget_hard_limit_usd: float = 20.0
    price_table_path: Path = Path("config/prices.json")

    # --- Storage ---
    db_path: Path = Path("data/db/probation.db")
    world_db_path: Path = Path("data/synth/world.db")

    # --- Runtime ---
    clock_mode: str = "replay"  # "replay" | "live"
    user_addresses: str = "meena@example.test"
    user_tz: str = "Asia/Kolkata"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Web Grounding (Tavily) ---
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    tavily_max_calls_per_day: int = 100
    tavily_monthly_credit_budget: int = 800
    user_name_tokens: str = ""

    # --- Files Pack ---
    files_watch_dirs: str = "data/synth/1/fs/Downloads,data/synth/1/fs/Desktop"
    files_allowed_roots: str = "data/synth/1/fs"
    files_reader_enabled: bool = False

    # --- Engine Tunables (ENGINE_SPEC section 12) ---
    audit_fraction: float = 0.10
    l1_min_n: int = 20
    l1_min_lb: float = 0.70
    l2_min_n: int = 50
    l2_min_lb: float = 0.95
    l3_min_n: int = 100
    l3_min_lb: float = 0.98
    cusum_threshold: float = 5.0
    psi_threshold: float = 0.25
    exam_valid_days: int = 90
    exam_max_per_day: int = 5


settings = Settings()
