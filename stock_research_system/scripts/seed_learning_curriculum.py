"""Seed the "Investing Foundations" curriculum.

Deterministic and idempotent: every ID is derived from a stable string
key via `uuid.uuid5`, so re-running this script updates the same rows
in place instead of creating duplicates. Safe to run repeatedly.

Usage (PowerShell):

    python scripts/seed_learning_curriculum.py

No investment recommendations and no claims of guaranteed return appear
anywhere in this content - it teaches concepts, not stock picks.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseOption,
    LearningModule,
    LearningPath,
    Lesson,
    Skill,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

_NAMESPACE = uuid.UUID("f1a4a1e0-1111-4000-8000-000000000000")


def _id(key: str) -> uuid.UUID:
    """A stable, deterministic UUID derived from `key`."""
    return uuid.uuid5(_NAMESPACE, key)


# --------------------------------------------------------------------------
# Script-local content specs (not domain/application models - just data
# used to build them below).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionSpec:
    key: str
    content: str
    is_correct: bool
    feedback: str | None = None


@dataclass(frozen=True)
class ExerciseSpec:
    key: str
    exercise_type: ExerciseType
    prompt: str
    explanation: str
    options: list[OptionSpec] = field(default_factory=list)
    configuration: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LessonSpec:
    key: str
    title: str
    summary: str
    content_markdown: str
    primary_skill_key: str
    secondary_skill_keys: list[str]
    exercises: list[ExerciseSpec]


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    title: str
    description: str
    lessons: list[LessonSpec]


SKILLS: dict[str, dict] = {
    "MONEY_BASICS": dict(
        name="Money Basics",
        description=(
            "Understand what money is, why it exists, and the basic functions "
            "it serves in an economy."
        ),
        category=FinancialSkillCategory.MONEY_BASICS,
    ),
    "INFLATION": dict(
        name="Inflation",
        description=(
            "Understand what inflation is and how it affects the purchasing "
            "power of money over time."
        ),
        category=FinancialSkillCategory.INFLATION,
    ),
    "COMPOUND_INTEREST": dict(
        name="Compound Interest",
        description=(
            "Understand the difference between simple and compound interest "
            "and why compounding matters for long-term growth."
        ),
        category=FinancialSkillCategory.COMPOUND_INTEREST,
    ),
    "STOCKS": dict(
        name="Stocks",
        description=(
            "Understand what owning a share of stock represents and how "
            "stock ownership relates to a company."
        ),
        category=FinancialSkillCategory.STOCKS,
    ),
    "BONDS": dict(
        name="Bonds",
        description="Understand how bonds work as a loan from an investor to a borrower.",
        category=FinancialSkillCategory.BONDS,
    ),
    "FUNDS_AND_ETFS": dict(
        name="Funds and ETFs",
        description=(
            "Understand what mutual funds and exchange-traded funds are and "
            "how they pool many investments together."
        ),
        category=FinancialSkillCategory.FUNDS_AND_ETFS,
    ),
    "RISK_AND_RETURN": dict(
        name="Risk and Return",
        description=(
            "Understand the basic relationship between the risk an "
            "investment carries and its potential return."
        ),
        category=FinancialSkillCategory.RISK_AND_RETURN,
    ),
    "DIVERSIFICATION": dict(
        name="Diversification",
        description=(
            "Understand how spreading investments across different assets "
            "can reduce risk."
        ),
        category=FinancialSkillCategory.DIVERSIFICATION,
    ),
}

MODULES: list[ModuleSpec] = [
    ModuleSpec(
        key="money-and-inflation",
        title="Money and Inflation",
        description=(
            "Learn the basic functions of money and how inflation erodes "
            "purchasing power over time."
        ),
        lessons=[
            LessonSpec(
                key="what-money-is-for",
                title="What Money Is For",
                summary=(
                    "Money serves three basic functions: a medium of exchange, "
                    "a store of value, and a unit of account."
                ),
                content_markdown=(
                    "# What Money Is For\n\n"
                    "Money exists to solve a simple problem: trading goods and "
                    "services directly (bartering) is inefficient. Money serves "
                    "three basic functions:\n\n"
                    "1. **Medium of exchange** - it lets people buy and sell "
                    "without bartering.\n"
                    "2. **Store of value** - it lets people save purchasing "
                    "power for later.\n"
                    "3. **Unit of account** - it gives a common way to price "
                    "and compare goods and services.\n\n"
                    "Money is *not* a guarantee of investment profit - that is "
                    "a separate idea covered in later lessons."
                ),
                primary_skill_key="MONEY_BASICS",
                secondary_skill_keys=[],
                exercises=[
                    ExerciseSpec(
                        key="money-functions-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="Which of the following is NOT one of the three basic functions of money?",
                        explanation=(
                            "Money's three classic functions are medium of exchange, "
                            "store of value, and unit of account. It does not "
                            "guarantee investment profit."
                        ),
                        options=[
                            OptionSpec("a", "A medium of exchange", False),
                            OptionSpec("b", "A store of value", False),
                            OptionSpec("c", "A guarantee of investment profit", True),
                            OptionSpec("d", "A unit of account", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="money-store-of-value-true-false",
                        exercise_type=ExerciseType.TRUE_FALSE,
                        prompt=(
                            "True or false: Money is considered a good store of value "
                            "only if it keeps its purchasing power reasonably stable "
                            "over time."
                        ),
                        explanation=(
                            "If money's value swings wildly or steadily erodes, it "
                            "becomes a poor way to store value for the future."
                        ),
                        options=[
                            OptionSpec("true", "True", True),
                            OptionSpec("false", "False", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="money-functions-multiple-choice",
                        exercise_type=ExerciseType.MULTIPLE_CHOICE,
                        prompt="Which of these are functions of money? Select all that apply.",
                        explanation=(
                            "Medium of exchange, store of value, and unit of account "
                            "are money's three functions. Guaranteed income is not - "
                            "no financial asset guarantees income or profit."
                        ),
                        options=[
                            OptionSpec("exchange", "Medium of exchange", True),
                            OptionSpec("store", "Store of value", True),
                            OptionSpec("account", "Unit of account", True),
                            OptionSpec("income", "Source of guaranteed income", False),
                        ],
                    ),
                ],
            ),
            LessonSpec(
                key="what-inflation-does",
                title="What Inflation Does to Purchasing Power",
                summary=(
                    "Inflation is a general rise in prices that reduces how much "
                    "your money can buy over time."
                ),
                content_markdown=(
                    "# What Inflation Does to Purchasing Power\n\n"
                    "Inflation is a general and sustained rise in the prices of "
                    "goods and services across an economy. When prices rise, "
                    "each unit of currency buys less than it used to - this is "
                    "called a loss of **purchasing power**.\n\n"
                    "A useful shortcut for estimating how fast prices double is "
                    "the **rule of 72**: divide 72 by the annual inflation rate "
                    "to estimate the number of years it takes for prices to "
                    "double."
                ),
                primary_skill_key="INFLATION",
                secondary_skill_keys=[],
                exercises=[
                    ExerciseSpec(
                        key="inflation-definition-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="Which statement best describes inflation?",
                        explanation=(
                            "Inflation refers to a general, sustained rise in prices "
                            "across the economy - not a single product or company."
                        ),
                        options=[
                            OptionSpec(
                                "a",
                                "A general and sustained rise in the prices of goods and services over time",
                                True,
                            ),
                            OptionSpec("b", "A sudden drop in a single company's stock price", False),
                            OptionSpec("c", "An increase in interest rates only", False),
                            OptionSpec("d", "A one-time price change in a single product", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="inflation-rule-of-72-numeric",
                        exercise_type=ExerciseType.NUMERIC_INPUT,
                        prompt=(
                            "If inflation is 4% per year, approximately how many years "
                            "does it take for prices to double? (Use the rule of 72: "
                            "72 divided by the rate.)"
                        ),
                        explanation="Using the rule of 72: 72 / 4 = 18 years.",
                        configuration={"correct_answer": 18, "tolerance": 1},
                    ),
                    ExerciseSpec(
                        key="inflation-purchasing-power-true-false",
                        exercise_type=ExerciseType.TRUE_FALSE,
                        prompt=(
                            "True or false: When inflation is positive, the same "
                            "amount of money buys fewer goods and services in the "
                            "future than it does today."
                        ),
                        explanation=(
                            "That is exactly what a loss of purchasing power means."
                        ),
                        options=[
                            OptionSpec("true", "True", True),
                            OptionSpec("false", "False", False),
                        ],
                    ),
                ],
            ),
        ],
    ),
    ModuleSpec(
        key="stocks-bonds-and-funds",
        title="Stocks, Bonds, and Funds",
        description="Learn what stocks, bonds, and funds represent and how each one works.",
        lessons=[
            LessonSpec(
                key="what-a-stock-represents",
                title="What a Stock Represents",
                summary="A share of stock represents partial ownership in a company.",
                content_markdown=(
                    "# What a Stock Represents\n\n"
                    "A share of stock is a small piece of ownership in a company. "
                    "As a shareholder, you can benefit if the company grows in "
                    "value, and the value of your shares can also fall if the "
                    "company performs poorly.\n\n"
                    "Share prices are influenced by many factors: the company's "
                    "profits and growth prospects, overall investor sentiment, "
                    "and broader economic conditions."
                ),
                primary_skill_key="STOCKS",
                secondary_skill_keys=[],
                exercises=[
                    ExerciseSpec(
                        key="stock-ownership-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="What does owning a share of stock represent?",
                        explanation=(
                            "A share of stock is a small ownership stake in a "
                            "company - not a loan (that is a bond) and not a "
                            "guaranteed payment."
                        ),
                        options=[
                            OptionSpec("a", "A loan you have made to the company", False),
                            OptionSpec("b", "A small ownership stake in the company", True),
                            OptionSpec("c", "A guaranteed fixed payment from the company", False),
                            OptionSpec("d", "A government-issued savings certificate", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="stock-benefit-true-false",
                        exercise_type=ExerciseType.TRUE_FALSE,
                        prompt=(
                            "True or false: As a partial owner via stock, a "
                            "shareholder can benefit if the company's value grows "
                            "over time."
                        ),
                        explanation="Share value tends to track the company's success over time.",
                        options=[
                            OptionSpec("true", "True", True),
                            OptionSpec("false", "False", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="stock-price-factors-multiple-choice",
                        exercise_type=ExerciseType.MULTIPLE_CHOICE,
                        prompt=(
                            "Which of the following can affect the value of a "
                            "share of stock? Select all that apply."
                        ),
                        explanation=(
                            "Company performance, investor sentiment, and the "
                            "broader economy can all move a stock's price. Cosmetic "
                            "details like a logo do not."
                        ),
                        options=[
                            OptionSpec("profits", "The company's profits and growth prospects", True),
                            OptionSpec("sentiment", "Overall investor sentiment in the market", True),
                            OptionSpec("economy", "Broad economic conditions", True),
                            OptionSpec("logo", "The color of the company's logo", False),
                        ],
                    ),
                ],
            ),
            LessonSpec(
                key="how-bonds-and-funds-work",
                title="How Bonds and Funds Work",
                summary=(
                    "A bond is a loan to a borrower, and a fund pools money from "
                    "many investors into one basket of holdings."
                ),
                content_markdown=(
                    "# How Bonds and Funds Work\n\n"
                    "A **bond** is effectively a loan: when you buy a bond, you "
                    "are lending money to the issuer (a company or government) "
                    "in exchange for interest payments and the return of your "
                    "principal later.\n\n"
                    "A **fund** - such as a mutual fund or an exchange-traded "
                    "fund (ETF) - pools money from many investors and holds a "
                    "basket of investments. Buying one share of a fund can give "
                    "you exposure to many underlying holdings at once."
                ),
                primary_skill_key="BONDS",
                secondary_skill_keys=["FUNDS_AND_ETFS"],
                exercises=[
                    ExerciseSpec(
                        key="bond-definition-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="When you buy a bond, what are you doing?",
                        explanation=(
                            "A bond represents lending money to the issuer in "
                            "return for interest - it is debt, not ownership."
                        ),
                        options=[
                            OptionSpec("a", "Buying part ownership of a company", False),
                            OptionSpec(
                                "b",
                                "Lending money to the issuer in exchange for interest payments",
                                True,
                            ),
                            OptionSpec("c", "Buying an insurance policy", False),
                            OptionSpec("d", "Making a one-time donation", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="etf-definition-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="What is an ETF?",
                        explanation=(
                            "An ETF (exchange-traded fund) holds a basket of many "
                            "investments and trades on an exchange like a single stock."
                        ),
                        options=[
                            OptionSpec("a", "A single company's stock", False),
                            OptionSpec(
                                "b",
                                "A fund that holds a basket of many investments and trades on an exchange like a stock",
                                True,
                            ),
                            OptionSpec("c", "A type of government bond only", False),
                            OptionSpec("d", "A type of savings account", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="fund-exposure-true-false",
                        exercise_type=ExerciseType.TRUE_FALSE,
                        prompt=(
                            "True or false: A fund can let an investor gain "
                            "exposure to many different investments through a "
                            "single purchase."
                        ),
                        explanation="That pooling is the main appeal of funds and ETFs.",
                        options=[
                            OptionSpec("true", "True", True),
                            OptionSpec("false", "False", False),
                        ],
                    ),
                ],
            ),
        ],
    ),
    ModuleSpec(
        key="risk-and-return",
        title="Risk and Return",
        description=(
            "Learn how risk and return are related and how compound interest "
            "drives long-term growth."
        ),
        lessons=[
            LessonSpec(
                key="understanding-risk-and-return",
                title="Understanding Risk and Return",
                summary=(
                    "Investments that carry more risk generally offer the "
                    "potential for higher returns, and vice versa."
                ),
                content_markdown=(
                    "# Understanding Risk and Return\n\n"
                    "In general, investments that carry more risk offer the "
                    "*potential* for higher returns - along with a higher "
                    "chance of loss. Lower-risk investments typically offer "
                    "more modest, steadier returns.\n\n"
                    "No investment is risk-free, and no strategy - including "
                    "diversification - can guarantee that an investor cannot "
                    "lose money."
                ),
                primary_skill_key="RISK_AND_RETURN",
                secondary_skill_keys=[],
                exercises=[
                    ExerciseSpec(
                        key="risk-return-relationship-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="In general, how are investment risk and potential return related?",
                        explanation=(
                            "Higher risk is generally associated with higher "
                            "potential return - and a higher chance of loss. "
                            "Return is never guaranteed."
                        ),
                        options=[
                            OptionSpec(
                                "a",
                                "Higher risk investments generally offer the potential for higher returns, along with a higher chance of loss",
                                True,
                            ),
                            OptionSpec("b", "Risk and return are unrelated", False),
                            OptionSpec("c", "Lower risk always produces higher returns", False),
                            OptionSpec("d", "Return is guaranteed regardless of risk", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="diversification-guarantee-true-false",
                        exercise_type=ExerciseType.TRUE_FALSE,
                        prompt="True or false: Diversification guarantees that an investor cannot lose money.",
                        explanation=(
                            "Diversification reduces certain risks but cannot "
                            "eliminate the possibility of loss."
                        ),
                        options=[
                            OptionSpec("true", "True", False),
                            OptionSpec("false", "False", True),
                        ],
                    ),
                    ExerciseSpec(
                        key="return-percentage-numeric",
                        exercise_type=ExerciseType.NUMERIC_INPUT,
                        prompt=(
                            "An investment grows from $1,000 to $1,050 in one year. "
                            "What is the return, expressed as a percentage? (Enter "
                            "just the number, e.g. 5 for 5%.)"
                        ),
                        explanation="($1,050 - $1,000) / $1,000 = 5%.",
                        configuration={"correct_answer": 5, "tolerance": 0.1},
                    ),
                ],
            ),
            LessonSpec(
                key="simple-vs-compound-interest",
                title="Simple Interest vs. Compound Interest",
                summary=(
                    "Compound interest grows faster than simple interest "
                    "because it is earned on both the original amount and "
                    "prior interest."
                ),
                content_markdown=(
                    "# Simple Interest vs. Compound Interest\n\n"
                    "**Simple interest** is calculated only on the original "
                    "amount (the principal). **Compound interest** is "
                    "calculated on the principal *plus* any interest already "
                    "earned - so the balance grows faster over time as each "
                    "round of interest builds on the last."
                ),
                primary_skill_key="COMPOUND_INTEREST",
                secondary_skill_keys=[],
                exercises=[
                    ExerciseSpec(
                        key="simple-vs-compound-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="What is the key difference between simple interest and compound interest?",
                        explanation=(
                            "Compound interest is earned on the principal plus "
                            "previously earned interest, which is why it grows "
                            "faster than simple interest over time."
                        ),
                        options=[
                            OptionSpec(
                                "a",
                                "Simple interest is calculated only on the original amount; compound interest is calculated on the original amount plus previously earned interest",
                                True,
                            ),
                            OptionSpec("b", "They are the same thing", False),
                            OptionSpec("c", "Compound interest is always lower than simple interest", False),
                            OptionSpec("d", "Simple interest only applies to bonds", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="simple-interest-numeric",
                        exercise_type=ExerciseType.NUMERIC_INPUT,
                        prompt=(
                            "You invest $100 at 10% simple annual interest. How "
                            "much interest (in dollars) will you earn after 2 years?"
                        ),
                        explanation="Simple interest = principal x rate x time = 100 x 0.10 x 2 = $20.",
                        configuration={"correct_answer": 20, "tolerance": 0.5},
                    ),
                    ExerciseSpec(
                        key="compound-growth-ordering",
                        exercise_type=ExerciseType.ORDERING,
                        prompt="Arrange the steps of compound growth in the correct order, from first to last.",
                        explanation=(
                            "Each round of interest is added to the balance, and "
                            "the next round is calculated on that larger total - "
                            "which is why growth accelerates over time."
                        ),
                        options=[
                            OptionSpec("step1", "Interest is earned on the original amount", True),
                            OptionSpec("step2", "That interest is added to the original amount", True),
                            OptionSpec(
                                "step3", "The next round of interest is calculated on the new, larger total", True
                            ),
                            OptionSpec("step4", "The balance keeps growing faster over time", True),
                        ],
                    ),
                ],
            ),
        ],
    ),
    ModuleSpec(
        key="diversification",
        title="Diversification",
        description="Learn why spreading investments across different assets can reduce risk.",
        lessons=[
            LessonSpec(
                key="why-diversification-matters",
                title="Why Diversification Matters",
                summary=(
                    "Diversification means spreading investments across "
                    "different assets so that no single investment can cause "
                    "major damage."
                ),
                content_markdown=(
                    "# Why Diversification Matters\n\n"
                    "Diversification means spreading investments across "
                    "different companies, industries, asset classes, and even "
                    "countries. The goal is that a decline in any single "
                    "holding has a smaller effect on the overall portfolio.\n\n"
                    "Diversification reduces certain risks, but it does not "
                    "eliminate the possibility of loss and does not guarantee "
                    "a profit."
                ),
                primary_skill_key="DIVERSIFICATION",
                secondary_skill_keys=[],
                exercises=[
                    ExerciseSpec(
                        key="most-diversified-portfolio-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="Which portfolio is more diversified?",
                        explanation=(
                            "Spreading holdings across many companies, "
                            "industries, and asset classes is what makes a "
                            "portfolio diversified."
                        ),
                        options=[
                            OptionSpec("a", "A portfolio holding shares of one company", False),
                            OptionSpec(
                                "b",
                                "A portfolio holding shares across many companies, industries, and asset classes",
                                True,
                            ),
                            OptionSpec("c", "A portfolio holding only cash", False),
                            OptionSpec("d", "A portfolio holding a single bond", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="diversification-guarantee-true-false-2",
                        exercise_type=ExerciseType.TRUE_FALSE,
                        prompt="True or false: Diversification guarantees that an investor cannot lose money.",
                        explanation=(
                            "No strategy, including diversification, can "
                            "guarantee against loss."
                        ),
                        options=[
                            OptionSpec("true", "True", False),
                            OptionSpec("false", "False", True),
                        ],
                    ),
                    ExerciseSpec(
                        key="diversification-examples-multiple-choice",
                        exercise_type=ExerciseType.MULTIPLE_CHOICE,
                        prompt="Which of the following are examples of diversifying a portfolio? Select all that apply.",
                        explanation=(
                            "Spreading holdings across industries, asset types, "
                            "and countries all diversify a portfolio. Putting "
                            "everything into one stock does the opposite."
                        ),
                        options=[
                            OptionSpec("industries", "Holding stocks across multiple industries", True),
                            OptionSpec("assets", "Holding both stocks and bonds", True),
                            OptionSpec("countries", "Investing in companies from different countries", True),
                            OptionSpec("concentrated", "Putting all your savings into a single stock", False),
                        ],
                    ),
                ],
            ),
            LessonSpec(
                key="concentration-risk",
                title="Concentration Risk",
                summary=(
                    "Concentration risk is the added risk of holding too much "
                    "of your portfolio in a single investment."
                ),
                content_markdown=(
                    "# Concentration Risk\n\n"
                    "Concentration risk is the added risk that comes from "
                    "holding too much of a portfolio in a single investment, "
                    "company, or sector. If that one holding performs badly, "
                    "it can have an outsized effect on the whole portfolio - "
                    "which is the opposite of what diversification aims to "
                    "achieve."
                ),
                primary_skill_key="DIVERSIFICATION",
                secondary_skill_keys=["RISK_AND_RETURN"],
                exercises=[
                    ExerciseSpec(
                        key="concentration-risk-definition-single-choice",
                        exercise_type=ExerciseType.SINGLE_CHOICE,
                        prompt="What is concentration risk?",
                        explanation=(
                            "Concentration risk comes from holding too much of a "
                            "portfolio in one investment - not from holding too "
                            "many different ones."
                        ),
                        options=[
                            OptionSpec(
                                "a",
                                "The risk that comes from holding too much of your portfolio in a single investment",
                                True,
                            ),
                            OptionSpec("b", "The risk of holding too many different investments", False),
                            OptionSpec("c", "A type of interest rate risk", False),
                            OptionSpec("d", "The risk of inflation only", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="concentration-vs-spread-true-false",
                        exercise_type=ExerciseType.TRUE_FALSE,
                        prompt=(
                            "True or false: A portfolio invested entirely in one "
                            "company's stock has more concentration risk than a "
                            "portfolio spread across many companies."
                        ),
                        explanation="Concentrating in one holding increases concentration risk.",
                        options=[
                            OptionSpec("true", "True", True),
                            OptionSpec("false", "False", False),
                        ],
                    ),
                    ExerciseSpec(
                        key="equal-split-percentage-numeric",
                        exercise_type=ExerciseType.NUMERIC_INPUT,
                        prompt=(
                            "A portfolio is split evenly across 5 different "
                            "stocks. What percentage of the portfolio does each "
                            "stock represent? (Enter the number only, e.g. 25 "
                            "for 25%.)"
                        ),
                        explanation="100% divided evenly among 5 holdings is 20% each.",
                        configuration={"correct_answer": 20, "tolerance": 0},
                    ),
                ],
            ),
        ],
    ),
]


def _build_skills() -> list[Skill]:
    return [
        Skill(
            skill_id=_id(f"skill:{code}"),
            code=code,
            name=spec["name"],
            description=spec["description"],
            category=spec["category"],
            difficulty=DifficultyLevel.BEGINNER,
        )
        for code, spec in SKILLS.items()
    ]


def _build_path() -> LearningPath:
    return LearningPath(
        path_id=_id("path:investing-foundations"),
        code="investing-foundations",
        title="Investing Foundations",
        description=(
            "A beginner-friendly introduction to the core ideas behind saving "
            "and investing: what money and inflation do, how stocks, bonds, "
            "and funds work, the relationship between risk and return, and "
            "why diversification matters."
        ),
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        estimated_minutes=120,
        published=True,
    )


def _build_modules(path_id: uuid.UUID) -> list[LearningModule]:
    return [
        LearningModule(
            module_id=_id(f"module:{module.key}"),
            path_id=path_id,
            code=module.key,
            title=module.title,
            description=module.description,
            position=position,
            estimated_minutes=30,
            published=True,
        )
        for position, module in enumerate(MODULES)
    ]


def _build_lessons() -> list[Lesson]:
    lessons: list[Lesson] = []
    for module in MODULES:
        module_id = _id(f"module:{module.key}")
        for position, lesson in enumerate(module.lessons):
            lessons.append(
                Lesson(
                    lesson_id=_id(f"lesson:{lesson.key}"),
                    module_id=module_id,
                    code=lesson.key,
                    title=lesson.title,
                    summary=lesson.summary,
                    content_markdown=lesson.content_markdown,
                    difficulty=DifficultyLevel.BEGINNER,
                    status=LessonStatus.PUBLISHED,
                    position=position,
                    estimated_minutes=15,
                    primary_skill_id=_id(f"skill:{lesson.primary_skill_key}"),
                    secondary_skill_ids=[
                        _id(f"skill:{key}") for key in lesson.secondary_skill_keys
                    ],
                )
            )
    return lessons


def _build_exercises_and_options() -> list[tuple[Exercise, list[ExerciseOption]]]:
    results: list[tuple[Exercise, list[ExerciseOption]]] = []
    for module in MODULES:
        for lesson in module.lessons:
            lesson_id = _id(f"lesson:{lesson.key}")
            skill_ids = [_id(f"skill:{lesson.primary_skill_key}")]
            for position, exercise_spec in enumerate(lesson.exercises):
                exercise_id = _id(f"exercise:{exercise_spec.key}")
                exercise = Exercise(
                    exercise_id=exercise_id,
                    lesson_id=lesson_id,
                    exercise_type=exercise_spec.exercise_type,
                    prompt=exercise_spec.prompt,
                    explanation=exercise_spec.explanation,
                    difficulty=DifficultyLevel.BEGINNER,
                    position=position,
                    skill_ids=skill_ids,
                    maximum_score=1.0,
                    passing_score=1.0,
                    configuration=exercise_spec.configuration,
                )
                options = [
                    ExerciseOption(
                        option_id=_id(f"option:{exercise_spec.key}:{option.key}"),
                        exercise_id=exercise_id,
                        option_key=option.key,
                        content=option.content,
                        position=option_position,
                        is_correct=option.is_correct,
                        feedback=option.feedback,
                    )
                    for option_position, option in enumerate(exercise_spec.options)
                ]
                results.append((exercise, options))
    return results


async def seed() -> None:
    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        uow = SqlAlchemyUnitOfWork(session_factory)

        skills = _build_skills()
        path = _build_path()
        modules = _build_modules(path.path_id)
        lessons = _build_lessons()
        exercises_and_options = _build_exercises_and_options()

        async with uow:
            for skill in skills:
                await uow.curriculum.upsert_skill(skill)
            await uow.curriculum.upsert_path(path)
            for module in modules:
                await uow.curriculum.upsert_module(module)
            for lesson in lessons:
                await uow.curriculum.upsert_lesson(lesson)
            for exercise, options in exercises_and_options:
                await uow.curriculum.upsert_exercise(exercise)
                if options:
                    await uow.curriculum.upsert_options(options)
            await uow.commit()

        print(
            f"Seeded {len(skills)} skills, 1 path, {len(modules)} modules, "
            f"{len(lessons)} lessons, {len(exercises_and_options)} exercises."
        )
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
