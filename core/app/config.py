"""Tottie settings — every knob arrives via env; .env files are dev convenience only.

Precedence: real environment > Tottie/.env > core/.env > code defaults.
Orch injects env directly (see orch.config.json). Dual-layer mandate: a new
variable goes into BOTH .env.example and orch.config.json.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), extra="ignore", populate_by_name=True
    )

    # ---- engine ----
    port: int = Field(default=8765, alias="TOTTIE_PORT")
    owner: str = Field(default="owner_local", alias="TOTTIE_OWNER")
    api_token: str = Field(default="changeme-local-token", alias="TOTTIE_API_TOKEN")
    db_url: str = Field(
        default="postgresql://localhost:5432/tottie", alias="TOTTIE_DB_URL"
    )
    ui_origin: str = Field(
        default="http://127.0.0.1:3055", alias="TOTTIE_UI_ORIGIN"
    )
    # auto|meta|local. Read fresh per resolve() call: flip with no restart.
    provider: str = Field(default="auto", alias="TOTTIE_PROVIDER")

    # ---- embeddings ----
    embedder: str = Field(default="fastembed", alias="TOTTIE_EMBEDDER")
    embed_model: str = Field(
        default="BAAI/bge-small-en-v1.5", alias="TOTTIE_EMBED_MODEL"
    )
    embedding_cache_dir: str = Field(
        default="../../local LLMS", alias="EMBEDDING_CACHE_DIR"
    )

    # ---- model providers (Meta primary, local fallback) ----
    meta_api_key: str = Field(default="", alias="META_API_KEY")
    meta_base_url: str = Field(default="", alias="META_BASE_URL")
    meta_model: str = Field(default="", alias="META_MODEL")
    local_llm_url: str = Field(
        default="http://127.0.0.1:11434", alias="LOCAL_LLM_URL"
    )
    local_llm_model: str = Field(
        default="nkngo-qwen-coder-3b", alias="LOCAL_LLM_MODEL"
    )
    local_llm_max_ctx: int = Field(default=4096, alias="LOCAL_LLM_MAX_CTX")
    local_llm_max_tokens: int = Field(default=512, alias="LOCAL_LLM_MAX_TOKENS")

    # ---- curation tuning (initial values; harness calibrates) ----
    identity_salience: float = Field(default=0.90, alias="TOTTIE_IDENTITY_SALIENCE")
    reconcile_cosine: float = Field(default=0.86, alias="TOTTIE_RECONCILE_COSINE")
    active_cosine: float = Field(default=0.60, alias="TOTTIE_ACTIVE_COSINE")
    recall_k: int = Field(default=8, alias="TOTTIE_RECALL_K")
    familiarity_cosine: float = Field(
        default=0.80, alias="TOTTIE_FAMILIARITY_COSINE")
    utility_half_life_days: int = Field(
        default=30, alias="TOTTIE_UTILITY_HALF_LIFE_DAYS"
    )
    confidence_floor: float = Field(default=0.35, alias="TOTTIE_CONFIDENCE_FLOOR")
    rif_enabled: bool = Field(default=False, alias="TOTTIE_RIF_ENABLED")
    # ---- contradiction verifier (G1 fix): familiar>=floor routes to NLI,
    # never straight to SKIP. Flag-off restores pure old behavior.
    nli_enabled: bool = Field(default=True, alias="TOTTIE_NLI_ENABLED")
    nli_threshold: float = Field(default=0.70, alias="TOTTIE_NLI_THRESHOLD")
    nli_model_dir: str = Field(default="", alias="TOTTIE_NLI_DIR")
    hnsw_ef_search: int = Field(default=100, alias="TOTTIE_HNSW_EF_SEARCH")

    # ---- write path ----
    inline_write: bool = Field(default=False, alias="TOTTIE_INLINE_WRITE")

    # ---- prospective ----
    replay_n: int = Field(default=50, alias="TOTTIE_REPLAY_N")

    # ---- sleep (consolidation) ----
    sleep_window_days: int = Field(default=7, alias="TOTTIE_SLEEP_WINDOW_DAYS")
    sleep_replay_cap: int = Field(default=50, alias="TOTTIE_SLEEP_REPLAY_CAP")
    sleep_rank_salience: float = Field(
        default=0.6, alias="TOTTIE_SLEEP_RANK_SALIENCE")

    # ---- rate limits ----
    rate_limit_per_min: int = Field(default=60, alias="TOTTIE_RATE_LIMIT_PER_MIN")
    max_rows_per_day: int = Field(default=2000, alias="TOTTIE_MAX_ROWS_PER_DAY")

    # ---- MCP ----
    mcp_transport: str = Field(default="stdio", alias="TOTTIE_MCP_TRANSPORT")
    use_sampling: bool = Field(default=False, alias="TOTTIE_USE_SAMPLING")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
