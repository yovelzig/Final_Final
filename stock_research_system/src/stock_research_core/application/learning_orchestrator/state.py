"""The typed LangGraph state for the `finquest-learning-coach` graph.

Every field is a plain, bounded, JSON-serializable value - `str`/`int`/
`float`/`bool`/`dict`/`list` only. UUIDs are always stored as `str`
(never a raw `UUID`), timestamps as ISO-8601 strings. Nothing here is an
ORM object, a SQLAlchemy session, a database connection, a raw
embedding vector, a full retrieved document, a provider API key, an
access/refresh token, a database URL, or hidden model reasoning.

The graph is a single, mostly-linear pipeline per run (no parallel
branches ever write conflicting updates to the same key), so no
reducers are needed - every node's partial-state return simply
overwrites the corresponding key, LangGraph's default behavior for an
un-annotated `TypedDict` field.

Existing tutor-conversation tables remain the canonical conversational
history; this state is the canonical *orchestration position* only -
bounded summaries, never a duplicate of what PostgreSQL already stores
durably (see `domain.learning_orchestrator.models` for the audited,
public FinQuest state).
"""

from __future__ import annotations

from typing import Any, TypedDict

#: Hard bounds enforced when writing into state (see
#: `infrastructure.operations.config`-style env-driven configuration in
#: `infrastructure.learning_orchestrator.graph_runtime`).
DEFAULT_MAX_CONTEXT_CHARACTERS = 20_000
DEFAULT_MAX_STATE_LIST_ITEMS = 50


class LearningCoachGraphState(TypedDict, total=False):
    # -- identity and run -----------------------------------------------
    thread_id: str
    run_id: str
    learner_id: str
    correlation_id: str
    graph_version: str

    # -- input -----------------------------------------------
    user_input: str
    requested_context_type: str
    context_references: dict[str, str]

    # -- routing -----------------------------------------------
    intent_classification: dict[str, Any]
    selected_route: str

    # -- structured learner state (bounded summaries only) -----------------------------------------------
    learner_dashboard: dict[str, Any]
    mastery_summary: list[dict[str, Any]]
    progress_summary: list[dict[str, Any]]
    active_misconceptions: list[dict[str, Any]]
    due_review_summary: list[dict[str, Any]]

    # -- tutor -----------------------------------------------
    tutor_conversation_id: str
    tutor_response: dict[str, Any]
    citations: list[dict[str, Any]]
    guardrail_result: dict[str, Any]

    # -- action -----------------------------------------------
    proposed_action: dict[str, Any]
    approval_result: dict[str, Any]
    action_result: dict[str, Any]

    # -- execution -----------------------------------------------
    step_count: int
    maximum_steps: int
    warnings: list[str]
    safe_errors: list[str]
    final_response: dict[str, Any]
    navigation_target: str | None


#: Keys that must never be written into `LearningCoachGraphState` by any
#: node - a defensive allow-*deny*-list checked by
#: `application.learning_orchestrator.nodes`' shared state-write helper
#: and asserted against in `test_orchestrator_state.py`.
FORBIDDEN_STATE_KEYS = frozenset(
    {
        "session", "db_session", "connection", "engine", "orm", "vector", "vectors", "embedding",
        "embeddings", "raw_document", "raw_documents", "api_key", "access_token", "refresh_token",
        "database_url", "password", "reasoning", "chain_of_thought", "prompt", "checkpoint",
    }
)


def new_state(
    *, thread_id: str, run_id: str, learner_id: str, correlation_id: str, graph_version: str, user_input: str,
    requested_context_type: str, context_references: dict[str, str] | None = None, maximum_steps: int = 30,
) -> LearningCoachGraphState:
    """Build the initial state for a new run. `context_references` values
    are already `str`-encoded UUIDs by the time they reach here (the
    service layer converts at the boundary)."""
    return LearningCoachGraphState(
        thread_id=thread_id, run_id=run_id, learner_id=learner_id, correlation_id=correlation_id,
        graph_version=graph_version, user_input=user_input[:DEFAULT_MAX_CONTEXT_CHARACTERS],
        requested_context_type=requested_context_type, context_references=context_references or {},
        step_count=0, maximum_steps=maximum_steps, warnings=[], safe_errors=[],
    )


def bounded_list(items: list[Any], *, max_items: int = DEFAULT_MAX_STATE_LIST_ITEMS) -> list[Any]:
    return items[:max_items]


def bounded_text(text: str, *, max_characters: int = DEFAULT_MAX_CONTEXT_CHARACTERS) -> str:
    return text[:max_characters]
