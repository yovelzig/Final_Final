"""Unit tests for `application.learning_orchestrator.state`."""

from __future__ import annotations

from uuid import uuid4

from stock_research_core.application.learning_orchestrator.state import (
    DEFAULT_MAX_CONTEXT_CHARACTERS,
    FORBIDDEN_STATE_KEYS,
    bounded_list,
    bounded_text,
    new_state,
)


def test_new_state_truncates_user_input_to_max_context_characters() -> None:
    state = new_state(
        thread_id=str(uuid4()), run_id=str(uuid4()), learner_id=str(uuid4()), correlation_id=str(uuid4()),
        graph_version="v1", user_input="x" * (DEFAULT_MAX_CONTEXT_CHARACTERS + 500),
        requested_context_type="GENERAL_EDUCATION",
    )
    assert len(state["user_input"]) == DEFAULT_MAX_CONTEXT_CHARACTERS


def test_new_state_defaults_context_references_to_empty_dict() -> None:
    state = new_state(
        thread_id=str(uuid4()), run_id=str(uuid4()), learner_id=str(uuid4()), correlation_id=str(uuid4()),
        graph_version="v1", user_input="hello", requested_context_type="GENERAL_EDUCATION",
    )
    assert state["context_references"] == {}
    assert state["step_count"] == 0
    assert state["maximum_steps"] == 30


def test_new_state_accepts_custom_maximum_steps() -> None:
    state = new_state(
        thread_id=str(uuid4()), run_id=str(uuid4()), learner_id=str(uuid4()), correlation_id=str(uuid4()),
        graph_version="v1", user_input="hello", requested_context_type="GENERAL_EDUCATION", maximum_steps=10,
    )
    assert state["maximum_steps"] == 10


def test_bounded_list_truncates() -> None:
    assert bounded_list(list(range(100)), max_items=5) == [0, 1, 2, 3, 4]


def test_bounded_text_truncates() -> None:
    assert bounded_text("x" * 100, max_characters=10) == "x" * 10


def test_forbidden_state_keys_cover_infrastructure_and_secrets() -> None:
    expected_present = {
        "session", "db_session", "connection", "vector", "embedding", "api_key", "access_token",
        "refresh_token", "database_url", "password", "reasoning", "chain_of_thought", "prompt", "checkpoint",
    }
    assert expected_present <= FORBIDDEN_STATE_KEYS


def test_new_state_never_produces_a_forbidden_key() -> None:
    state = new_state(
        thread_id=str(uuid4()), run_id=str(uuid4()), learner_id=str(uuid4()), correlation_id=str(uuid4()),
        graph_version="v1", user_input="hello", requested_context_type="GENERAL_EDUCATION",
    )
    assert set(state.keys()).isdisjoint(FORBIDDEN_STATE_KEYS)
