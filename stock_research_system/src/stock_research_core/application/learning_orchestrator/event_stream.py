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
        # Spec G2D2 section 12: automatic Live Research trigger events -
        # bounded, no provider/job internals, driven purely by
        # server-pushed SSE so the frontend never needs a manual
        # "resume" action to see a research answer land.
        "research_started", "research_waiting_update", "research_completed", "research_unavailable",
    }
)

#: Live Research node names whose `final_response`/interrupt payload get
#: their own distinct event type below, instead of the generic
#: `response_completed`/`approval_required` every other node uses.
_LIVE_RESEARCH_NODE_NAMES = frozenset({"request_live_research", "synthesize_research_response"})

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

    if "research_job_id" in update and node_name == "request_live_research":
        events.append(
            {
                "type": "research_started", "research_job_id": update.get("research_job_id"),
                "deadline_at": update.get("research_deadline_at"),
            }
        )

    if "final_response" in update and node_name != "persist_final_result":
        final_response = update["final_response"] or {}
        if node_name in _LIVE_RESEARCH_NODE_NAMES:
            research_event_type = (
                "research_completed" if final_response.get("grounding_status") == "GROUNDED" else "research_unavailable"
            )
            events.append(
                {
                    "type": research_event_type,
                    "answer_markdown": final_response.get("answer_markdown"),
                    "grounding_status": final_response.get("grounding_status"),
                    "navigation_target": final_response.get("navigation_target"),
                }
            )
        else:
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


def interrupt_reason(interrupt_value: dict[str, Any]) -> str:
    """This graph has exactly two `interrupt()` call sites -
    `approval_interrupt` and `await_research_result` - discriminated
    here by payload shape (never by node name, since a LangGraph
    `__interrupt__` chunk carries only the interrupt's own value, not
    the name of the node that raised it): `await_research_result`'s
    payload always has a `research_job_id` key and never a `proposal_id`
    key, `approval_interrupt`'s payload is the reverse. Returns
    `"research"` or `"approval"` - the single source of truth both
    `interrupt_to_event` (SSE shaping) and
    `LangGraphOrchestratorRuntime`/`PersonalizedLearningOrchestratorService`
    (run-status finalization) use to classify an interrupt, so the two
    can never disagree about which one just fired."""
    if "research_job_id" in interrupt_value and "proposal_id" not in interrupt_value:
        return "research"
    return "approval"


def interrupt_to_event(interrupt_value: dict[str, Any]) -> dict[str, Any]:
    """`interrupt_value` is already the learner-safe payload the raising
    node built (proposal id/title/description/reason/safe parameters/
    expiration, or research_job_id/scope/deadline_at - never raw
    evidence, never provider/job internals)."""
    if interrupt_reason(interrupt_value) == "research":
        return {
            "type": "research_waiting_update", "research_job_id": interrupt_value.get("research_job_id"),
            "scope": interrupt_value.get("scope"), "deadline_at": interrupt_value.get("deadline_at"),
        }
    return {"type": "approval_required", **interrupt_value}


def error_event(message: str) -> dict[str, Any]:
    return {"type": "error", "message": message}


def heartbeat_event() -> dict[str, Any]:
    return {"type": "heartbeat"}
