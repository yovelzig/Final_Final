"""Unit tests for `application.learning_orchestrator.event_stream` - a
pure function over plain dicts, no LangGraph/database required."""

from __future__ import annotations

from stock_research_core.application.learning_orchestrator.event_stream import (
    ALLOWED_EVENT_TYPES,
    error_event,
    heartbeat_event,
    interrupt_to_event,
    node_update_to_events,
)


def test_stage_event_uses_a_friendly_label_not_the_raw_node_name() -> None:
    events = node_update_to_events("load_authorized_context", {})
    assert events[0] == {"type": "stage", "stage": "Loading your learning context"}


def test_internal_only_nodes_never_emit_a_stage_event() -> None:
    events = node_update_to_events("build_action_proposal", {"proposed_action": {}})
    assert all(event["type"] != "stage" for event in events)


def test_intent_classification_update_emits_intent_event() -> None:
    events = node_update_to_events("classify_intent", {"intent_classification": {"intent": "EXPLAIN_CONCEPT"}})
    assert {"type": "intent", "intent": "EXPLAIN_CONCEPT"} in events


def test_route_selection_update_emits_route_event() -> None:
    events = node_update_to_events("select_route", {"selected_route": "GROUNDED_EXPLANATION"})
    assert {"type": "route", "route": "GROUNDED_EXPLANATION"} in events


def test_citations_are_bounded_and_learner_safe() -> None:
    citations = [
        {
            "citation_number": i, "source_title": f"Source {i}", "document_title": f"Doc {i}",
            "excerpt": "text", "chunk_id": "should-never-leak",
        }
        for i in range(1, 20)
    ]
    events = node_update_to_events("grounded_explanation", {"citations": citations})
    citation_events = [e for e in events if e["type"] == "citation"]
    assert len(citation_events) <= 10
    for event in citation_events:
        assert "chunk_id" not in event
        assert "excerpt" not in event


def test_action_proposed_only_fires_on_build_action_proposal_node() -> None:
    proposed = {"proposal_id": "abc", "title": "Start practice", "description": "desc"}
    events = node_update_to_events("build_action_proposal", {"proposed_action": proposed})
    assert any(e["type"] == "action_proposed" for e in events)

    events_elsewhere = node_update_to_events("propose_practice_session", {"proposed_action": proposed})
    assert not any(e["type"] == "action_proposed" for e in events_elsewhere)


def test_execute_action_emits_started_then_completed_when_result_present() -> None:
    events = node_update_to_events("execute_action", {"action_result": {"navigation_target": "/practice"}})
    types = [e["type"] for e in events]
    assert types.index("action_started") < types.index("action_completed")


def test_execute_action_emits_only_started_without_a_result() -> None:
    events = node_update_to_events("execute_action", {})
    types = [e["type"] for e in events]
    assert "action_started" in types
    assert "action_completed" not in types


def test_persist_final_result_emits_run_completed() -> None:
    events = node_update_to_events("persist_final_result", {})
    assert {"type": "run_completed"} in events


def test_interrupt_to_event_passes_through_the_already_safe_payload() -> None:
    payload = {
        "proposal_id": "abc", "title": "t", "description": "d", "reason": "r", "safe_parameters": {},
        "expires_at": None,
    }
    event = interrupt_to_event(payload)
    assert event["type"] == "approval_required"
    assert event["proposal_id"] == "abc"


def test_error_and_heartbeat_events_are_allow_listed() -> None:
    assert error_event("oops")["type"] in ALLOWED_EVENT_TYPES
    assert heartbeat_event()["type"] in ALLOWED_EVENT_TYPES


def test_every_event_produced_has_an_allow_listed_type() -> None:
    sample_updates = [
        ("initialize_run", {}),
        ("load_authorized_context", {}),
        ("evaluate_input_guardrail", {}),
        ("classify_intent", {"intent_classification": {"intent": "EXPLAIN_CONCEPT"}}),
        ("select_route", {"selected_route": "GROUNDED_EXPLANATION"}),
        ("grounded_explanation", {"citations": [{"citation_number": 1, "source_title": "s", "document_title": "d"}]}),
        ("execute_action", {"action_result": {}}),
        ("persist_final_result", {}),
    ]
    for node_name, update in sample_updates:
        for event in node_update_to_events(node_name, update):
            assert event["type"] in ALLOWED_EVENT_TYPES
