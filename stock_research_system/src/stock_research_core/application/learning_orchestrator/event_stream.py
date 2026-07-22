"""Learner-safe SSE event shaping (spec section 20).

Maps a single LangGraph node's partial state update (as yielded by
`stream_mode="updates"`) into zero or more learner-safe event dicts.
Only the allow-listed event *types* below are ever produced - no raw
state, prompt text, chunk id, vector, internal node name, traceback, or
chain-of-thought crosses this boundary. This module has no LangGraph
import of its own - it is a pure function over plain dicts, so it can be
unit-tested without a graph, a checkpointer, or a database.
"""

from __future__ import annotations

from typing import Any

from stock_research_core.application.learning_orchestrator.nodes import stage_label

ALLOWED_EVENT_TYPES = frozenset(
    {
        "run_started", "stage", "intent", "route", "retrieval_started", "retrieval_completed",
        "response_started", "response_completed", "citation", "action_proposed", "approval_required",
        "action_started", "action_completed", "run_completed", "error", "heartbeat",
    }
)

_MAX_STREAMED_CITATIONS = 10

#: Internal graph node names that must never be exposed to a learner
#: verbatim - `stage_label` already renders a friendly label for known
#: nodes, but this set is a second, explicit check so a future node
#: added without a label can't leak its raw identifier.
_INTERNAL_ONLY_NODE_NAMES = frozenset({"build_action_proposal", "persist_final_result"})


def node_update_to_events(node_name: str, update: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one `(node_name, partial_state_update)` pair from a
    LangGraph `updates`-mode stream chunk into learner-safe events."""
    events: list[dict[str, Any]] = []

    if node_name not in _INTERNAL_ONLY_NODE_NAMES:
        events.append({"type": "stage", "stage": stage_label(node_name)})

    if "intent_classification" in update:
        events.append({"type": "intent", "intent": update["intent_classification"].get("intent")})

    if "selected_route" in update:
        events.append({"type": "route", "route": update["selected_route"]})

    if node_name in {"grounded_explanation", "lesson_tutor", "exercise_tutor"}:
        events.append({"type": "retrieval_started"})

    for citation in (update.get("citations") or [])[:_MAX_STREAMED_CITATIONS]:
        events.append(
            {
                "type": "citation", "citation_number": citation.get("citation_number"),
                "source_title": citation.get("source_title"), "document_title": citation.get("document_title"),
            }
        )

    if "final_response" in update and node_name != "persist_final_result":
        final_response = update["final_response"] or {}
        events.append(
            {
                "type": "response_completed",
                "answer_markdown": final_response.get("answer_markdown"),
                "grounding_status": final_response.get("grounding_status"),
                "navigation_target": final_response.get("navigation_target"),
            }
        )

    proposed_action = update.get("proposed_action")
    if proposed_action and "proposal_id" in proposed_action and node_name == "build_action_proposal":
        events.append(
            {
                "type": "action_proposed", "proposal_id": proposed_action["proposal_id"],
                "title": proposed_action["title"], "description": proposed_action["description"],
            }
        )

    if node_name == "execute_action":
        events.append({"type": "action_started"})
        if update.get("action_result") is not None:
            events.append({"type": "action_completed"})

    if node_name == "persist_final_result":
        events.append({"type": "run_completed"})

    return events


def interrupt_to_event(interrupt_value: dict[str, Any]) -> dict[str, Any]:
    """The single `approval_required` event shape sent for a LangGraph
    `interrupt()` - `interrupt_value` is already the learner-safe payload
    `GraphNodes.approval_interrupt` built (proposal id/title/description/
    reason/safe parameters/expiration only)."""
    return {"type": "approval_required", **interrupt_value}


def error_event(message: str) -> dict[str, Any]:
    return {"type": "error", "message": message}


def heartbeat_event() -> dict[str, Any]:
    return {"type": "heartbeat"}
