"""CLI for the FinQuest grounded AI tutor.

Create a general conversation (PowerShell):

    python -m stock_research_core.cli.ai_tutor `
      --learner-id <UUID> --new-conversation GENERAL_EDUCATION

Ask a question:

    python -m stock_research_core.cli.ai_tutor `
      --conversation-id <UUID> --ask "What is diversification?"

Lesson conversation:

    python -m stock_research_core.cli.ai_tutor `
      --learner-id <UUID> --lesson-id <UUID> --new-lesson-conversation

Exercise-help conversation:

    python -m stock_research_core.cli.ai_tutor `
      --learner-id <UUID> --exercise-id <UUID> --new-exercise-conversation

Scenario before-decision conversation:

    python -m stock_research_core.cli.ai_tutor `
      --learner-id <UUID> --scenario-id <UUID> --submission-id <UUID> `
      --new-scenario-before-conversation

Scenario after-reveal conversation:

    python -m stock_research_core.cli.ai_tutor `
      --learner-id <UUID> --submission-id <UUID> --new-scenario-after-conversation

Portfolio conversation:

    python -m stock_research_core.cli.ai_tutor `
      --learner-id <UUID> --portfolio-id <UUID> --new-portfolio-conversation

Close a conversation:

    python -m stock_research_core.cli.ai_tutor --conversation-id <UUID> --close

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.models import TutorContext, TutorResponse
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.ai_tutor.ports import TutorModelPort
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.application.virtual_portfolio.execution import (
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor
from stock_research_core.infrastructure.ai_tutor.openai_compatible_tutor import OpenAICompatibleTutorAdapter
from stock_research_core.infrastructure.ai_tutor.sentence_transformer_embeddings import (
    SentenceTransformerEmbeddingAdapter,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import (
    PandasScenarioCalculator,
)
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)


def _build_embedding_provider(settings: EmbeddingSettings):
    if settings.embedding_provider == "deterministic_fake":
        return DeterministicFakeEmbeddingAdapter(dimension=settings.embedding_dimension)
    return SentenceTransformerEmbeddingAdapter(
        model_name=settings.embedding_model_name,
        dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )


def _build_tutor_model(settings: TutorModelSettings) -> TutorModelPort:
    if settings.tutor_model_provider == "openai_compatible":
        return OpenAICompatibleTutorAdapter(
            base_url=settings.tutor_model_base_url,
            api_key=settings.tutor_model_api_key,
            model_name=settings.tutor_model_name,
            timeout_seconds=settings.tutor_model_timeout_seconds,
        )
    return DeterministicExtractiveTutor()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.ai_tutor",
        description="Talk to the FinQuest grounded AI tutor.",
    )
    parser.add_argument("--learner-id", metavar="UUID", default=None)
    parser.add_argument("--conversation-id", metavar="UUID", default=None)
    parser.add_argument("--lesson-id", metavar="UUID", default=None)
    parser.add_argument("--exercise-id", metavar="UUID", default=None)
    parser.add_argument("--scenario-id", metavar="UUID", default=None)
    parser.add_argument("--submission-id", metavar="UUID", default=None)
    parser.add_argument("--portfolio-id", metavar="UUID", default=None)

    parser.add_argument(
        "--new-conversation", metavar="CONTEXT_TYPE", default=None,
        choices=[context_type.value for context_type in TutorContextType],
        help="Create a general conversation of the given context type (typically GENERAL_EDUCATION)",
    )
    parser.add_argument("--new-lesson-conversation", action="store_true")
    parser.add_argument("--new-exercise-conversation", action="store_true")
    parser.add_argument("--new-scenario-before-conversation", action="store_true")
    parser.add_argument("--new-scenario-after-conversation", action="store_true")
    parser.add_argument("--new-portfolio-conversation", action="store_true")

    parser.add_argument("--ask", metavar="QUESTION", default=None)
    parser.add_argument(
        "--exercise-submitted", action="store_true",
        help="With --ask on an EXERCISE_HELP conversation: the learner has already submitted an answer",
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--close", action="store_true", help="Close the conversation given by --conversation-id")

    return parser


def _print_response(response: TutorResponse) -> None:
    print("Answer:")
    print(f"  {response.answer.answer_markdown}\n")
    print(f"  Status:          {response.answer.status.value}")
    print(f"  Grounding:       {response.answer.grounding_status.value}")
    print(f"  Provider:        {response.answer.provider_type.value} ({response.answer.model_name})")
    print(f"  Tutor policy:    {response.answer.tutor_policy_version}")
    print(f"  Guardrail:       {response.guardrail.action.value} ({response.guardrail.request_category.value})")
    if response.citations:
        print("  Citations:")
        for citation in response.citations:
            heading = " > ".join(citation.heading_path) or "(no heading)"
            print(f"    [{citation.citation_number}] {citation.source_title} - {heading}")
            print(f"        {citation.excerpt}")


async def _run(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    embedding_settings = EmbeddingSettings()
    tutor_model_settings = TutorModelSettings()
    engine = create_database_engine(settings)
    tutor_model: TutorModelPort | None = None
    try:
        session_factory = create_session_factory(engine)
        uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

        embedding_provider = _build_embedding_provider(embedding_settings)
        retriever = HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)
        tutor_model = _build_tutor_model(tutor_model_settings)
        guardrail = RuleBasedTutorGuardrail()
        prompt_builder = GroundedTutorPromptBuilder()
        tutor_service = GroundedAITutorService(
            unit_of_work_factory=uow_factory, retriever=retriever, tutor_model=tutor_model,
            guardrail=guardrail, prompt_builder=prompt_builder,
        )
        lesson_service = LessonTutorService(tutor_service=tutor_service, unit_of_work_factory=uow_factory)
        scenario_service = ScenarioTutorService(
            tutor_service=tutor_service, unit_of_work_factory=uow_factory,
            scenario_service=HistoricalMarketScenarioService(
                unit_of_work_factory=uow_factory,
                scenario_calculator=PandasScenarioCalculator(),
                scenario_grading_policy=RuleBasedScenarioGradingPolicy(),
                graded_answer_submitter=LearningService(uow_factory),
            ),
        )
        portfolio_service = PortfolioTutorService(
            tutor_service=tutor_service, unit_of_work_factory=uow_factory,
            portfolio_service=VirtualPortfolioService(
                unit_of_work_factory=uow_factory, execution_policy=NextAvailableOpenExecutionPolicy(),
                accounting_policy=AverageCostPortfolioAccountingPolicy(),
            ),
            valuation_service=PortfolioValuationService(
                unit_of_work_factory=uow_factory, analytics=PandasPortfolioAnalytics(),
                feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
            ),
        )

        if args.new_conversation:
            if args.learner_id is None:
                print("error: --new-conversation requires --learner-id", file=sys.stderr)
                return 2
            context = TutorContext(
                context_type=TutorContextType(args.new_conversation), learner_id=UUID(args.learner_id)
            )
            conversation = await tutor_service.create_conversation(learner_id=UUID(args.learner_id), context=context)
            print(f"Conversation created: {conversation.conversation_id}")

        if args.new_lesson_conversation:
            if args.learner_id is None or args.lesson_id is None:
                print("error: requires --learner-id and --lesson-id", file=sys.stderr)
                return 2
            conversation = await lesson_service.create_lesson_conversation(
                learner_id=UUID(args.learner_id), lesson_id=UUID(args.lesson_id)
            )
            print(f"Lesson conversation created: {conversation.conversation_id}")

        if args.new_exercise_conversation:
            if args.learner_id is None or args.exercise_id is None:
                print("error: requires --learner-id and --exercise-id", file=sys.stderr)
                return 2
            conversation = await lesson_service.create_exercise_help_conversation(
                learner_id=UUID(args.learner_id), exercise_id=UUID(args.exercise_id)
            )
            print(f"Exercise-help conversation created: {conversation.conversation_id}")

        if args.new_scenario_before_conversation:
            if args.learner_id is None or args.scenario_id is None or args.submission_id is None:
                print("error: requires --learner-id, --scenario-id, and --submission-id", file=sys.stderr)
                return 2
            conversation = await scenario_service.create_before_decision_conversation(
                learner_id=UUID(args.learner_id), scenario_id=UUID(args.scenario_id),
                submission_id=UUID(args.submission_id),
            )
            print(f"Scenario before-decision conversation created: {conversation.conversation_id}")

        if args.new_scenario_after_conversation:
            if args.learner_id is None or args.submission_id is None:
                print("error: requires --learner-id and --submission-id", file=sys.stderr)
                return 2
            conversation = await scenario_service.create_after_reveal_conversation(
                learner_id=UUID(args.learner_id), submission_id=UUID(args.submission_id)
            )
            print(f"Scenario after-reveal conversation created: {conversation.conversation_id}")

        if args.new_portfolio_conversation:
            if args.learner_id is None or args.portfolio_id is None:
                print("error: requires --learner-id and --portfolio-id", file=sys.stderr)
                return 2
            conversation = await portfolio_service.create_portfolio_conversation(
                learner_id=UUID(args.learner_id), portfolio_id=UUID(args.portfolio_id)
            )
            print(f"Portfolio conversation created: {conversation.conversation_id}")

        if args.ask:
            if args.conversation_id is None:
                print("error: --ask requires --conversation-id", file=sys.stderr)
                return 2
            conversation_id = UUID(args.conversation_id)
            async with uow_factory() as uow:
                conversation = await uow.tutor_conversations.get_conversation(conversation_id)
            if conversation is None:
                print(f"error: no conversation found with id '{conversation_id}'", file=sys.stderr)
                return 1

            if conversation.context_type in (TutorContextType.LESSON_HELP, TutorContextType.EXERCISE_HELP):
                response = await lesson_service.ask(
                    conversation_id=conversation_id, question=args.ask,
                    exercise_submitted=args.exercise_submitted, top_k=args.top_k,
                )
            elif conversation.context_type in (
                TutorContextType.SCENARIO_BEFORE_DECISION, TutorContextType.SCENARIO_AFTER_REVEAL,
            ):
                response = await scenario_service.ask(
                    conversation_id=conversation_id, question=args.ask, top_k=args.top_k
                )
            elif conversation.context_type == TutorContextType.PORTFOLIO_EXPLANATION:
                response = await portfolio_service.ask(
                    conversation_id=conversation_id, question=args.ask, top_k=args.top_k
                )
            else:
                response = await tutor_service.ask(
                    conversation_id=conversation_id, question=args.ask, top_k=args.top_k
                )
            _print_response(response)

        if args.close:
            if args.conversation_id is None:
                print("error: --close requires --conversation-id", file=sys.stderr)
                return 2
            closed = await tutor_service.close_conversation(UUID(args.conversation_id))
            print(f"Conversation closed: {closed.conversation_id} at {closed.closed_at}")

        if not any(
            (
                args.new_conversation, args.new_lesson_conversation, args.new_exercise_conversation,
                args.new_scenario_before_conversation, args.new_scenario_after_conversation,
                args.new_portfolio_conversation, args.ask, args.close,
            )
        ):
            print(
                "error: specify --new-conversation, --new-lesson-conversation, --new-exercise-conversation, "
                "--new-scenario-before-conversation, --new-scenario-after-conversation, "
                "--new-portfolio-conversation, --ask, or --close",
                file=sys.stderr,
            )
            return 2

        return 0
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if isinstance(tutor_model, OpenAICompatibleTutorAdapter):
            await tutor_model.aclose()
        await engine.dispose()


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
