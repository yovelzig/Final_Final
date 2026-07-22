"""Phase 12 LangGraph learning-orchestrator configuration (spec section
29). Importing this module never opens a connection or compiles a
graph - it only describes how one *would* be configured, matching
`infrastructure.operations.config` and `infrastructure.database.config`.

`langgraph_enabled` defaults to `False`: an existing FinQuest deployment
(or the test suite) that never sets `LANGGRAPH_ENABLED=true` is
completely unaffected by this module - no checkpointer pool is opened,
no graph is compiled, and `/api/v1/coach` is not even registered.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class LangGraphSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    langgraph_enabled: bool = False
    langgraph_graph_version: str = "learning-coach-graph-v1"

    langgraph_max_steps: int = 30
    langgraph_run_timeout_seconds: int = 90
    langgraph_max_repair_attempts: int = 1
    langgraph_model_intent_classification: bool = False

    langgraph_checkpointer_enabled: bool = True
    langgraph_checkpoint_schema: str = "langgraph"
    langgraph_checkpointer_pool_min_size: int = 1
    langgraph_checkpointer_pool_max_size: int = 5

    langgraph_thread_lock_ttl_seconds: int = 120
    langgraph_thread_lock_wait_seconds: int = 2

    langgraph_max_context_characters: int = 20_000
    langgraph_max_state_list_items: int = 50

    #: Optional model-assisted intent-classification fallback endpoint -
    #: only ever consulted when `langgraph_model_intent_classification=True`.
    langgraph_intent_model_base_url: str = ""
    langgraph_intent_model_api_key: str = ""
    langgraph_intent_model_name: str = ""

    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "finquest-learning-coach"
    langsmith_trace_content: bool = False
