"""Configuration settings and engine tunables.

Authority: docs/ENGINE_SPEC.md section 12 and docs/TECH_STACK_AND_REPO.md section 4.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = os.environ.get("PROBATION_ENV_FILE", ".env")


class Settings(BaseSettings):
    """System-wide configuration settings loaded from environment and defaults."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    @field_validator("app_profile")
    @classmethod
    def known_profile(cls, value: str) -> str:
        if value not in {"private", "synthetic"}:
            raise ValueError("app_profile must be private or synthetic")
        return value

    # --- LLM Settings (Nebius Token Factory) ---
    llm_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    llm_api_key: str = ""
    model_reader: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    model_writer: str = "nvidia/nemotron-3-super-120b-a12b"
    model_exam_edits: str = "nvidia/Nemotron-3-Ultra-550b-a55b"
    model_wording: str = "nvidia/nemotron-3-super-120b-a12b"
    model_synth: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    llm_max_concurrency: int = 8
    llm_timeout_s: int = 60
    llm_max_retries: int = 3
    llm_instruction_only: bool = True
    budget_hard_limit_usd: float = 20.0
    price_table_path: Path = Path("config/prices.json")

    # --- Storage ---
    db_path: Path = Path("data/db/probation.db")
    world_db_path: Path = Path("data/synth/world.db")

    # --- Runtime ---
    clock_mode: str = "replay"  # "replay" | "live"
    # Selected by trusted server configuration only; a browser can never choose a profile.
    app_profile: str = "private"  # "private" | "synthetic"
    # Synthetic workspace only. Relaxes the loopback check so a public judge can open the
    # demo. Ignored in the private profile; Gmail setup and account routes stay disabled.
    # Settings has no env_prefix, so the alias is required for PROBATION_DEMO_ALLOW_ANY_HOST.
    demo_allow_any_host: bool = Field(
        default=False,
        validation_alias=AliasChoices("PROBATION_DEMO_ALLOW_ANY_HOST", "DEMO_ALLOW_ANY_HOST"),
    )
    # Show the one-click synthetic-demo entry on the sign-in page. Ignored in private mode.
    demo_login: bool = Field(
        default=False,
        validation_alias=AliasChoices("PROBATION_DEMO_LOGIN", "DEMO_LOGIN"),
    )
    user_addresses: str = "meena@example.test"
    user_tz: str = "Asia/Kolkata"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Web Grounding (Tavily) ---
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    tavily_max_calls_per_day: int = 100
    tavily_monthly_credit_budget: int = 800
    user_name_tokens: str = ""
    web_facts_ttl_positive_days: int = 30
    web_facts_ttl_negative_days: int = 7
    extract_max_chars: int = 20000

    # --- Owner-bound local Gmail API (credentials remain in the API/connector roles) ---
    probation_gmail_owner_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("PROBATION_GMAIL_OWNER_API_KEY", "PROBATION_OWNER_API_KEY"),
    )
    probation_gmail_owner_id: str = "local-owner"
    probation_gmail_store: Path | None = Path("data/private/connectors/gmail_metadata.db")
    probation_gmail_bind_host: str = "127.0.0.1"
    probation_accounts_db: Path = Path("data/private/accounts/accounts.db")

    # --- Files Pack ---
    files_watch_dirs: str = "data/synth/1/fs/Downloads,data/synth/1/fs/Desktop"
    files_allowed_roots: str = "data/synth/1/fs"
    files_reader_enabled: bool = False
    files_topk_folders: int = 15
    outcome_window_file_days: int = 14

    # --- Phase 8b: Radar & Reading Packs & Link Substrate ---
    radar_window_days: int = 14
    radar_min_window_days: int = 2
    reading_window_days: int = 14
    quarantine_max_input_chars: int = 6000
    extract_ttl_days: int = 30
    undo_days: int = 7
    lookalike_max_edit_distance: int = 2
    report_hits_min: int = 2

    # --- Engine Tunables (ENGINE_SPEC section 12) ---
    audit_fraction: float = 0.10
    audit_seed: str = "probation-audit-v1"
    l1_min_n: int = 20
    l1_min_lb: float = 0.70
    l2_min_n: int = 60
    l2_min_lb: float = 0.95
    l3_min_n: int = 150
    l3_min_lb: float = 0.98
    cusum_threshold: float = 5.0
    cusum_allowance: float = 0.02
    cusum_base_err_default: float = 0.03
    psi_threshold: float = 0.25
    exam_valid_days: int = 90
    exam_max_per_day: int = 3
    exam_n: int = 30
    exam_min_valid_cases: int = 20
    exam_invariance_max_flip: float = 0.03
    exam_critical_max_violations: int = 0
    exam_other_max_violation_rate: float = 0.05
    retrain_interval_days: int = 7
    train_half_life_days: float = 90.0
    cold_start_min_situations: int = 200
    embedding_model_dir: Path = Path(
        "data/models/all-MiniLM-L6-v2/d13954661f83248295ba75c1ed411eef3b7b936e"
    )
    embedding_manifest_path: Path = Path("data/models/all-MiniLM-L6-v2/manifest.json")
    novelty_k: int = 10
    novelty_pctl: float = 95.0
    pooling_kappa: float = 10.0
    lb_quantile: float = 0.05
    attention_cost: float = 1.0
    evidence_window_days: int = 180
    strong_min_raw_n: int = 60
    licence_min_recent_n: int = 20
    licence_ttl_days: int = 30
    habit_min_support: int = 20
    habit_min_lift: float = 1.5
    habit_q: float = 0.01
    chain_min_support: int = 20
    chain_min_p: float = 0.60
    chain_min_lift: float = 1.5
    chain_link_min_sim: float = 0.45
    chain_window_hours: int = 24


_WORKER_ROLES = frozenset(
    {"observation", "brain", "resolver", "examiner", "webfacts", "api", "executor"}
)


def _source_keys(name: str, field: FieldInfo) -> tuple[str, ...]:
    """The environment keys that may legitimately supply one field, in precedence order."""
    alias = field.validation_alias
    if alias is None:
        return (name,)
    if isinstance(alias, str):
        return (alias,)
    if isinstance(alias, AliasChoices):
        return tuple(str(choice) for choice in alias.choices)
    return (name,)


def _from_mapping(values: Mapping[str, str]) -> dict[str, str]:
    """Map one environment-style mapping onto settings fields, ignoring empty values.

    ``env_ignore_empty`` semantics are kept: an empty variable supplies nothing, so a lower
    priority source may still provide the field.
    """
    supplied: dict[str, str] = {}
    for name, field in Settings.model_fields.items():
        for key in _source_keys(name, field):
            value = values.get(key, values.get(key.upper(), ""))
            if value:
                supplied.setdefault(key, value)
                break
    return supplied


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load trusted settings from exactly one source: the environment handed to this call.

    Validating the worker role from one mapping while reading values out of ``os.environ`` would
    let the two disagree, so the mapping is authoritative for both. A marked worker child is
    additionally denied the dotenv file: its scrubbed environment is all it may have.
    """
    values: Mapping[str, str] = os.environ if environ is None else environ
    role = values.get("PROBATION_WORKER_ROLE")
    if role is not None and role not in _WORKER_ROLES:
        raise ValueError("invalid_worker_role")
    supplied = _from_mapping(values)
    if role is not None:
        # Pydantic Settings accepts this private constructor kwarg at runtime; its stub omits it.
        return Settings(_env_file=None, **supplied)  # type: ignore[call-arg,arg-type]
    return Settings(_env_file=_ENV_FILE, **supplied)  # type: ignore[call-arg,arg-type]


settings = load_settings()
