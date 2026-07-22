"""`ModelAssistedLearningIntentClassifier`: the optional, single-call
model-assisted fallback (spec section 11).

Only ever consulted when `RuleBasedLearningIntentClassifier` returns
`UNKNOWN` for reasons *other* than the investment-advice safety
boundary, and only when explicitly enabled
(`LANGGRAPH_MODEL_INTENT_CLASSIFICATION=true`, default `false`). At most
one model call per classification - no retry loop, no chain of
follow-up calls. Any failure (network, timeout, malformed response, an
intent string outside the closed `LearningIntent` allow-list) falls
back to the rule-based `UNKNOWN` result; a broken or slow model
endpoint must never turn into a broken learner request, since the graph
already has a deterministic `FALLBACK` route for `UNKNOWN`.
"""

from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

import httpx

from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import IntentClassificationMethod, LearningIntent
from stock_research_core.domain.learning_orchestrator.models import IntentClassification

_INVESTMENT_ADVICE_RULE_CODE = "INVESTMENT_ADVICE_BOUNDARY"
_MODEL_ASSISTED_VERSION_SUFFIX = "+model-fallback-v1"

#: The model is only ever allowed to pick from this closed vocabulary -
#: never a free-form string, never a route or action name.
_CANDIDATE_INTENTS = tuple(intent.value for intent in LearningIntent if intent != LearningIntent.UNKNOWN)

_SYSTEM_PROMPT = (
    "Classify a financial-education learner's message into exactly one of these categories, and "
    'respond with a single JSON object of exactly this shape: {"intent": "<one of the categories>"}. '
    f"Categories: {', '.join(_CANDIDATE_INTENTS)}. "
    "If the message asks what to buy, sell, or invest in, or requests personalized financial advice, "
    'respond with {"intent": "UNKNOWN"} - do not guess a category for it.'
)


class IntentClassificationModelPort(Protocol):
    """A minimal, dedicated model port for this one call - deliberately
    not `application.ai_tutor.ports.TutorModelPort`, which is shaped
    around retrieval-grounded answer generation, not classification."""

    async def classify(self, *, user_input: str) -> str | None:
        """Returns a raw intent string, or `None` on any failure."""
        ...


class HttpIntentClassificationModelClient:
    """Calls a configured OpenAI-compatible chat-completions endpoint for
    one classification call. Tests must inject an `httpx.AsyncClient`
    built with a mock transport - this adapter never requires real
    network access to be unit-tested."""

    def __init__(
        self, *, base_url: str, api_key: str, model_name: str, timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def classify(self, *, user_input: str) -> str | None:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            "max_tokens": 50, "temperature": 0,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            intent_value = json.loads(content).get("intent")
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None
        if not isinstance(intent_value, str):
            return None
        return intent_value


class ModelAssistedLearningIntentClassifier:
    """Wraps `RuleBasedLearningIntentClassifier`; only escalates to the
    injected `IntentClassificationModelPort` when the rule-based result
    is a genuine `UNKNOWN` (not the investment-advice safety boundary)
    and `enabled=True`."""

    def __init__(
        self, *, rule_based: RuleBasedLearningIntentClassifier, model_client: IntentClassificationModelPort,
        enabled: bool = False,
    ) -> None:
        self._rule_based = rule_based
        self._model_client = model_client
        self._enabled = enabled

    async def classify(
        self, *, learner_id: UUID, user_input: str, context_type: TutorContextType,
        context_references: dict[str, UUID],
    ) -> IntentClassification:
        rule_result = await self._rule_based.classify(
            learner_id=learner_id, user_input=user_input, context_type=context_type,
            context_references=context_references,
        )
        if not self._enabled or rule_result.intent != LearningIntent.UNKNOWN:
            return rule_result
        if _INVESTMENT_ADVICE_RULE_CODE in rule_result.matched_rule_codes:
            return rule_result

        raw_intent = await self._model_client.classify(user_input=user_input)
        if raw_intent not in _CANDIDATE_INTENTS:
            return rule_result

        return IntentClassification(
            intent=LearningIntent(raw_intent), confidence=0.6, method=IntentClassificationMethod.MODEL_ASSISTED,
            context_references=context_references, matched_rule_codes=["MODEL_ASSISTED_FALLBACK"],
            requires_grounded_tutor=LearningIntent(raw_intent) != LearningIntent.UNKNOWN,
            requires_action_approval=LearningIntent(raw_intent) in {
                LearningIntent.START_DAILY_PRACTICE, LearningIntent.START_DIAGNOSTIC,
            },
            classifier_version=self._rule_based.classifier_version + _MODEL_ASSISTED_VERSION_SUFFIX,
        )
