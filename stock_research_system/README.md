# stock-research-core

Phase 1 of an AI stock research and prediction system: the shared,
technology-independent **domain layer** that every other component in the
system will build on.

**Product pivot (Phase 4):** this codebase is now the foundation for
**FinQuest**, an adaptive financial-education platform (see
[Phase 4](#phase-4-finquest-learning-platform-foundation) below). The
existing stock-market infrastructure (Phases 1–3) is preserved
unchanged and untouched — it will power future historical market
scenarios, chart-reading exercises, and virtual portfolios. English is
FinQuest's primary and default language.

## What this module is

`stock-research-core` is a small Python package containing:

- Pydantic v2 domain models (securities, requests, documents, events,
  market bars, critical points, predictions, alerts, and the final
  analysis response).
- Enums used across the whole system (exchanges, document types, event
  types, prediction labels, alert severities, etc.).
- `typing.Protocol`-based service contracts ("ports") describing what each
  future component must do, without saying how.
- Unit tests, an example request payload, and this documentation.

## Why shared contracts are required

A system built from independent components (ingestion, extraction, market
analysis, prediction, storage, alerting) only stays coherent if every
component speaks the same, validated language. If components pass around
plain dictionaries, invalid data (bad tickers, impossible OHLC prices,
probabilities that don't sum to one, look-ahead leakage in predictions)
can silently flow from one stage to the next. By requiring every component
to accept and return these domain objects, invalid data is rejected at the
boundary where it is created, not discovered later downstream.

## What is included

- `src/stock_research_core/domain/enums.py` — shared enumerations.
- `src/stock_research_core/domain/models.py` — the `DomainModel` base
  class and all domain objects, with field-level and cross-field
  validation.
- `src/stock_research_core/contracts/ports.py` — `Protocol` definitions
  for security resolution, document ingestion, market data, event
  extraction, market analysis, prediction, knowledge storage, structured
  storage, and alerting.
- `tests/test_models.py` — unit tests covering normalization rules and
  validation failures.
- `examples/sample_analysis_request.json` — a sample `AnalysisRequest`
  payload.

## What is intentionally not included

This phase does **not** implement:

- External API clients (market data providers, news providers, etc.).
- Any database, cache, or vector store integration.
- News ingestion pipelines.
- Machine learning models or training code.
- RAG pipelines.
- LangGraph or n8n orchestration.
- FastAPI endpoints or any user interface.

Those all belong to later phases and will be built as concrete
implementations of the ports defined here.

## Creating a virtual environment

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
```

## Folder structure

```text
stock_research_system/
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── examples/
│   └── sample_analysis_request.json
├── scripts/
│   ├── init_test_db.sql
│   └── wait_for_database.py
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py
├── src/
│   └── stock_research_core/
│       ├── __init__.py
│       ├── domain/                    # Phase 1 - no infrastructure imports
│       │   ├── __init__.py
│       │   ├── enums.py
│       │   ├── models.py
│       │   └── learning/              # Phase 4 - separate domain, no infra imports
│       │       ├── __init__.py
│       │       ├── enums.py
│       │       └── models.py
│       ├── contracts/                 # Phase 1 - Protocol definitions only
│       │   ├── __init__.py
│       │   └── ports.py
│       ├── application/
│       │   ├── __init__.py
│       │   ├── exceptions.py
│       │   ├── market_data/           # Phase 2
│       │   │   ├── __init__.py
│       │   │   ├── models.py
│       │   │   └── service.py
│       │   ├── persistence/           # Phase 3 (UnitOfWorkPort extended in Phase 4)
│       │   │   ├── __init__.py
│       │   │   ├── models.py
│       │   │   ├── ports.py
│       │   │   └── service.py
│       │   └── learning/              # Phase 4
│       │       ├── __init__.py
│       │       ├── models.py
│       │       ├── ports.py
│       │       ├── grading.py
│       │       ├── mastery.py
│       │       └── service.py
│       ├── infrastructure/
│       │   ├── __init__.py
│       │   ├── security/              # Phase 2
│       │   │   ├── __init__.py
│       │   │   └── yfinance_resolver.py
│       │   ├── market_data/           # Phase 2
│       │   │   ├── __init__.py
│       │   │   └── yfinance_adapter.py
│       │   └── database/              # Phase 3 (+ learning ORM/mappers/repos in Phase 4)
│       │       ├── __init__.py
│       │       ├── config.py
│       │       ├── engine.py
│       │       ├── base.py
│       │       ├── unit_of_work.py
│       │       ├── orm/
│       │       ├── mappers/
│       │       └── repositories/
│       └── cli/
│           ├── __init__.py
│           ├── market_data.py         # Phase 2
│           ├── database_status.py     # Phase 3
│           ├── ingest_and_store.py    # Phase 3
│           └── learning_status.py     # Phase 4
├── scripts/
│   ├── init_test_db.sql               # Phase 3
│   ├── wait_for_database.py           # Phase 3
│   └── seed_learning_curriculum.py    # Phase 4
└── tests/
    ├── __init__.py
    ├── test_models.py                 # Phase 1
    ├── test_yfinance_resolver.py      # Phase 2
    ├── test_yfinance_adapter.py       # Phase 2
    ├── test_market_data_service.py    # Phase 2
    ├── unit/                          # no PostgreSQL required
    │   ├── test_database_mappers.py           # Phase 3
    │   ├── test_unit_of_work.py                # Phase 3
    │   ├── test_persistence_service.py         # Phase 3
    │   ├── test_learning_domain_models.py      # Phase 4
    │   ├── test_learning_mappers.py            # Phase 4
    │   ├── test_learning_unit_of_work.py       # Phase 4
    │   └── test_learning_service.py            # Phase 4
    └── integration/                   # requires PostgreSQL/TimescaleDB
        ├── conftest.py
        ├── test_security_repository.py          # Phase 3
        ├── test_market_bar_repository.py         # Phase 3
        ├── test_ingestion_persistence.py         # Phase 3
        ├── test_tracked_security_repository.py   # Phase 3
        ├── test_learner_repository.py            # Phase 4
        ├── test_curriculum_repository.py         # Phase 4
        ├── test_attempt_repository.py             # Phase 4
        ├── test_mastery_repository.py             # Phase 4
        └── test_learning_progress_repository.py   # Phase 4
```

## Rule for future components

Every future component in this system — ingestion, extraction, market
analysis, prediction, storage, alerting, and any API or UI layer — must
accept and return the domain objects defined in
`stock_research_core.domain.models`, and must implement the corresponding
`Protocol` in `stock_research_core.contracts.ports`. Passing unvalidated
dictionaries between components is not permitted.

## Phase 2: security resolution and market-data ingestion

Phase 2 adds the first working, technology-*dependent* components on top
of the Phase 1 domain layer, plus the application-layer glue that keeps
them decoupled from each other.

### What was added

- **Security resolution** — given a ticker or a company name, resolve it
  to a validated `Security` domain object (`SecurityResolverPort`).
- **Historical market-data ingestion** — fetch OHLCV bars for a security
  over a date range and normalize them into `MarketBar` objects.
- **Incremental ingestion** — fetch only the bars published after the
  last stored bar, instead of re-downloading full history.
- **Benchmark ingestion** — fetch bars for a benchmark ticker (e.g. SPY)
  through the same resolver and provider, with no benchmark hard-coded
  into the application layer.
- **Data-quality reporting** — every ingestion run returns a
  `MarketDataQualityReport` describing how many rows the provider sent,
  how many were duplicates or structurally invalid, and any warnings
  (e.g. missing adjusted close, missing volume, a gap near the requested
  end date, or an unusual multi-day gap between bars).

### Current MVP limitation

Only the `1d` (daily) interval is supported. Any other interval raises
`UnsupportedIntervalError` rather than being silently coerced to daily
data.

### Layering

```text
domain/        <- no infrastructure imports (unchanged from Phase 1)
contracts/     <- Protocol definitions only (unchanged from Phase 1)
application/   <- orchestrates domain models + Protocols; NO yfinance/pandas imports
infrastructure/<- the only layer allowed to import yfinance and pandas
cli/           <- composition root; wires infrastructure adapters into the application service
```

`stock_research_core.infrastructure.security.yfinance_resolver` and
`stock_research_core.infrastructure.market_data.yfinance_adapter` are the
first concrete implementations of `SecurityResolverPort` and
`MarketDataPort`. **yfinance is an infrastructure adapter, not a domain
dependency** — it can be swapped for a different provider later without
touching `domain/`, `contracts/`, or `application/market_data/service.py`.
No raw pandas `DataFrame` ever leaves the infrastructure adapter; every
public method returns `MarketBar` / `MarketDataQualityReport` objects.

In Phase 2, `MarketDataIngestionResult` was purely an in-memory
application result. Phase 3 (below) adds the database layer that
persists it.

### Tests are fully offline

`tests/test_yfinance_resolver.py`, `tests/test_yfinance_adapter.py`, and
`tests/test_market_data_service.py` mock every yfinance call and use
deterministic sample data — no internet access or live market prices are
required to run the suite.

### CLI

A manual-testing CLI wires the yfinance adapters into
`MarketDataIngestionService` and prints the resolved security, the
fetched bars, and any data-quality issues.

```powershell
python -m stock_research_core.cli.market_data `
  --ticker NVDA `
  --start 2025-01-01 `
  --end 2025-02-01
```

```powershell
python -m stock_research_core.cli.market_data `
  --company-name "NVIDIA Corporation" `
  --start 2025-01-01 `
  --end 2025-02-01
```

Arguments: `--ticker`, `--company-name` (at least one is required),
`--start`, `--end` (both `YYYY-MM-DD`, interpreted as UTC), `--interval`
(default `1d`), `--limit` (default `10`, number of bars printed). The CLI
exits with a non-zero status and a short message (no stack trace) on any
`StockResearchError`.

## Phase 3: PostgreSQL and TimescaleDB persistence

Phase 3 adds a database layer that stores what Phase 2 ingests, and
connects `MarketDataIngestionService` to it via a new
`PersistedMarketDataIngestionService`.

### Why PostgreSQL, and why TimescaleDB

PostgreSQL gives strong transactional guarantees (a full ingestion run —
security, bars, quality issues, audit record, tracked-security update —
either all commits or none of it does) and native `INSERT ... ON
CONFLICT` upserts, which this phase relies on heavily. **TimescaleDB**
is a PostgreSQL extension purpose-built for time-series data: OHLCV
market bars are append-mostly, queried by time range, and grow
indefinitely, which is exactly the workload a *hypertable* (a table
transparently partitioned by time into "chunks") is designed for —
without changing a single line of application or repository code, since
a hypertable is queried with ordinary SQL.

### Database schema

| Table | Purpose |
|---|---|
| `securities` | Canonical securities. Unique on `(ticker, exchange)`. |
| `market_bars` | OHLCV bars. A TimescaleDB hypertable partitioned by `timestamp`. Composite primary key `(security_id, timestamp, interval, source_name)` — the partitioning column must be part of any unique/primary key on a hypertable. |
| `market_data_ingestion_runs` | One audit row per ingestion attempt: provider, requested range, row counts, status (`STARTED` / `COMPLETED` / `FAILED` / `NO_NEW_DATA`), and a sanitized error type/message (never a raw traceback) on failure. |
| `market_data_quality_issues` | The `DataQualityIssue`s from a run's `MarketDataQualityReport`, cascade-deleted with their run. |
| `tracked_securities` | Which securities are actively monitored, and when they were last successfully updated. Maps 1:1 to the domain `TrackedSecurity`. Monitoring/alert *execution* is not implemented yet. |

`market_bars.security_id`, `market_data_ingestion_runs.security_id`, and
`tracked_securities.security_id` all `ON DELETE RESTRICT` to
`securities` — deleting a security while its market history, audit
trail, or tracking state still exists is rejected rather than silently
cascading data loss.

### Security canonical IDs

`SecurityResolverPort.resolve()` builds a fresh `Security` (with a new
random `security_id`) on every call — including the *second* time you
ingest the same ticker. The `securities` table's `upsert` uses `INSERT
... ON CONFLICT (ticker, exchange) DO UPDATE`, so the **first-ever
stored `security_id` for a ticker+exchange is canonical and never
changes**; later ingestion runs update the mutable fields (company
name, currency, sector, industry, active) in place and return that same
canonical ID. `PersistedMarketDataIngestionService` then rewrites every
bar's `security_id` to the canonical ID before persisting — a bar is
never stored against a security ID that doesn't match its own security
row.

### Historical, incremental, and benchmark ingestion persistence

- **`ingest_historical_and_store`** — resolves + fetches via the Phase 2
  service, upserts the canonical security, bulk-upserts the bars, saves
  quality issues, completes the ingestion-run record, and (by default)
  upserts a `TrackedSecurity` — all in one transaction.
- **`ingest_incremental_and_store`** — looks up the *stored* security by
  ticker (raising `SecurityNotStoredError` if none exists — run
  historical first) and the latest stored bar timestamp (raising
  `NoStoredMarketDataError` if there isn't one), then fetches only bars
  after that timestamp. It never re-downloads full history. A
  provider-reported `NO_NEW_DATA` (e.g. a weekend with no new session)
  is stored as a successful `NO_NEW_DATA` run, not a failure.
- **`ingest_benchmark_and_store`** — same persistence path as
  historical, for any benchmark ticker you pass in (SPY is a caller
  convention, never hard-coded into the service).

### Transaction behavior (Unit of Work)

`SqlAlchemyUnitOfWork` opens one session per `async with` block,
exposes `.securities`, `.market_bars`, `.ingestion_runs`, and
`.tracked_securities` repositories bound to that session, and commits
only when `.commit()` is called explicitly:

```python
async with unit_of_work_factory() as uow:
    security = await uow.securities.upsert(some_security)
    await uow.market_bars.upsert_many(some_bars)
    await uow.commit()
```

If persistence fails partway through, the surrounding `async with`
rolls back automatically (nothing partially commits), and
`PersistedMarketDataIngestionService` makes a best-effort attempt, in a
*separate* fresh transaction, to record the run as `FAILED` with a
sanitized error type/message — a secondary failure while recording that
is swallowed rather than masking the original error.

### Alembic migrations

Migrations are the only source of truth for schema; nothing in the
application ever calls `Base.metadata.create_all()`. The initial
migration (`0001_initial_schema`) enables the `timescaledb` extension,
creates all five tables plus indexes/constraints, and converts
`market_bars` into a hypertable — and is idempotent (`alembic upgrade
head` twice is a no-op the second time).

```powershell
alembic upgrade head
alembic current
alembic downgrade base
```

### Local Docker setup

```powershell
docker compose up -d stock-db
python scripts/wait_for_database.py
alembic upgrade head
python -m stock_research_core.cli.database_status
```

`docker-compose.yml` runs `timescale/timescaledb:2.17.2-pg16` as service
`stock-db` on host port `5433` (container `5432`), database
`stock_research`, user/password `stock_user` / `stock_password` — local
development values only, never for production. On first startup it also
runs `scripts/init_test_db.sql`, which creates the separate
`stock_research_test` database used by integration tests.

### Environment variables

See `.env.example`:

```env
DATABASE_URL=postgresql+asyncpg://stock_user:stock_password@localhost:5433/stock_research
TEST_DATABASE_URL=postgresql+asyncpg://stock_user:stock_password@localhost:5433/stock_research_test
DATABASE_ECHO=false
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
```

`DatabaseSettings` (pydantic-settings) reads these (with the same
values as safe local defaults if unset) and never prints a password —
`masked_database_url()` / `masked_test_database_url()` replace
credentials with `***` wherever a URL is displayed (CLIs, logs).

### Unit versus integration tests

- **`tests/unit/`** — no PostgreSQL required. Mapper tests instantiate
  ORM classes as plain Python objects; `test_unit_of_work.py` mocks the
  session factory; `test_persistence_service.py` uses fake repositories,
  a fake Unit of Work, and a real Phase 2 `MarketDataIngestionService`
  wired to fake resolver/provider ports.
- **`tests/integration/`** — marked `@pytest.mark.integration`, run
  against the real `stock_research_test` database, and are skipped
  automatically (with a clear reason, not a failure) if that database
  isn't reachable. They cover schema/migration checks, all four
  repositories, and two full fake-provider-to-database round trips
  (historical and incremental).

```powershell
pytest                      # everything; integration tests skip cleanly if the DB is down
pytest -m "not integration" # unit tests only, no database needed at all
pytest -m integration       # integration tests only (requires stock-db running)
```

### CLI examples

```powershell
# Historical
python -m stock_research_core.cli.ingest_and_store `
  --ticker NVDA --start 2025-01-01 --end 2025-02-01

# By company name
python -m stock_research_core.cli.ingest_and_store `
  --company-name "NVIDIA Corporation" --start 2025-01-01 --end 2025-02-01

# Incremental (only new bars since the last stored one)
python -m stock_research_core.cli.ingest_and_store `
  --ticker NVDA --incremental --end 2025-03-01

# Benchmark
python -m stock_research_core.cli.ingest_and_store `
  --benchmark SPY --start 2025-01-01 --end 2025-02-01

# Database status
python -m stock_research_core.cli.database_status
```

### Current limitations

- Only the `1d` interval is supported (unchanged from Phase 2).
- No news ingestion, article storage, event extraction, RAG/vector
  storage, machine learning, prediction persistence, alert delivery,
  LangGraph, n8n, FastAPI endpoints, authentication, or frontend yet —
  all later phases.
- Monitoring/alerting *execution* is not implemented; `tracked_securities`
  only records which securities are being watched and when they were
  last updated.

## Phase 4: FinQuest learning platform foundation

Phase 4 pivots the product toward **FinQuest**, a Duolingo-inspired
adaptive financial-education platform, while leaving every Phase 1–3
stock-market capability untouched and fully operational. **English is
FinQuest's primary and default language** — all learner-facing content
(paths, modules, lessons, exercises, options, feedback) is written in
English, and new learners default to `preferred_language="en"`.

### Learning-domain architecture

The learning domain (`stock_research_core.domain.learning`) is a
**separate, technology-independent domain from the market-data domain**
(`stock_research_core.domain.models`) — lessons and exercises never
require a `Security`. A future market-scenario feature may reference a
`Security` by ID from its own model, but the two domains are not merged.
The same architecture rules apply as in earlier phases: no SQLAlchemy,
FastAPI, pandas, yfinance, or LLM/RAG imports in `domain/` or
`application/*/ports.py`; ORM models never leave `infrastructure/`;
repositories map ORM rows to domain/application models; ports own no
opinion about SQLAlchemy at all.

```text
domain/learning/            <- LearnerProfile, Skill, LearningPath, Lesson, Exercise, ...
application/learning/       <- ports (Protocols), grading.py, mastery.py, service.py
infrastructure/database/orm/, mappers/, repositories/  <- SQLAlchemy, mapped to/from domain models
cli/learning_status.py      <- composition root
```

### Curriculum hierarchy

`LearningPath` → `LearningModule` → `Lesson` → `Exercise` → `ExerciseOption`.
A `Skill` (e.g. `DIVERSIFICATION`, `COMPOUND_INTEREST`) is what a lesson
or exercise actually teaches/tests; skills can declare prerequisite
skills, and a lesson has one primary skill plus optional secondary
skills. All curriculum listings are returned in deterministic
`position` order.

### Exercise types and grading

Supported exercise types: `SINGLE_CHOICE`, `MULTIPLE_CHOICE`,
`TRUE_FALSE`, `NUMERIC_INPUT`, `ORDERING`, `SCENARIO_DECISION`,
`TEXT_RESPONSE`. Grading (`application/learning/grading.py`) is fully
**deterministic — no LLM, no machine learning**:

| Type | Rule |
|---|---|
| `SINGLE_CHOICE` / `TRUE_FALSE` | Exactly one option selected must match the one correct option. |
| `MULTIPLE_CHOICE` | The selected option set must exactly match the correct option set. |
| `NUMERIC_INPUT` | `abs(answer - correct_answer) <= tolerance`, both read from `exercise.configuration` and validated (rejects a missing/non-numeric `correct_answer`). |
| `ORDERING` | The submitted `ordered_option_ids` must exactly match the options sorted by their stored `position` (the canonical order). |
| `SCENARIO_DECISION` / `TEXT_RESPONSE` | **Never auto-graded** — the answer is stored and the attempt is marked `SUBMITTED` (not `GRADED`); there is no deterministic rubric for open-ended answers yet. |

### Attempts and answers

`ExerciseAttempt` tracks one learner's attempt end-to-end
(`STARTED` → `SUBMITTED` → `GRADED`, or `ABANDONED`), with strict
datetime ordering (`started_at` ≤ `submitted_at` ≤ `graded_at`) and
graded-attempt requirements (`graded_at`, `score`, `is_correct` all
required once `GRADED`) enforced by the domain model itself.
`ExerciseAnswer` stores exactly what the learner submitted — selected
options, a numeric answer, free text, or an ordered list — and never
judges correctness itself. `attempt_number` is computed from the
learner's prior attempts at that exercise.

### Skill mastery

`SkillMastery` is updated by a single, versioned, explicit rule -
**`mastery-v1`** (`application/learning/mastery.py`), isolated behind a
`MasteryCalculatorPort` so a future algorithm can replace it without
touching `LearningService`:

- First graded attempt for a skill: `mastery_score` = the normalized
  score (0–1) of that attempt.
- Every later attempt: `mastery_score = 0.8 × previous + 0.2 × latest`
  (an exponential moving average).
- `consecutive_correct` increments on a correct attempt, resets to 0
  otherwise.
- Levels: `NOVICE` (< 0.30), `DEVELOPING` (0.30–0.60), `PROFICIENT`
  (0.60–0.85), `MASTERED` (≥ 0.85 **and** at least 3 total graded
  attempts — otherwise it caps at `PROFICIENT`, since one lucky attempt
  isn't "sufficient evidence").

### Progress tracking

`UserProgress` tracks a learner's status toward a path, module, or
lesson (exactly one target per row — enforced at the database level by
three partial unique indexes, since a plain multi-column `UNIQUE`
constraint can't catch duplicates across nullable columns). The current
MVP rule: a lesson is `COMPLETED` once the learner has at least one
correct graded attempt on every exercise it contains;
`completion_percentage` reflects the fraction of exercises passed.

### Misconceptions

`Misconception` records an evidence-backed misunderstanding a learner
appears to hold (e.g. "believes diversification guarantees no losses"),
linked to the graded attempts that are its evidence. Detection logic is
out of scope for this phase — **misconceptions are never invented by an
LLM here**; this phase only validates and stores well-formed records.
Uniqueness on `(learner, skill, code)` is enforced only while a
misconception is `ACTIVE`, so a resolved one can later be re-detected as
a fresh row.

### Database migration

`migrations/versions/0002_learning_core.py` (depends on
`0001_initial_schema`) adds 18 tables: `learner_profiles`,
`financial_skills` (+ `skill_prerequisites`), `learning_paths`,
`learning_modules`, `lessons` (+ `lesson_secondary_skills`),
`exercises` (+ `exercise_skills`), `exercise_options`,
`exercise_attempts`, `exercise_answers` (+
`exercise_answer_selected_options`, `exercise_answer_ordered_options`),
`skill_mastery`, `user_progress`, and `misconceptions` (+
`misconception_evidence_attempts`). Association tables model real
relationships explicitly — JSONB (`exercises.configuration`) is used
only for exercise-type-specific grading parameters, never as a
replacement for a relationship. No TimescaleDB hypertable is needed for
these tables. All Phase 1–3 tables are untouched.

```powershell
alembic upgrade head
alembic current
```

### English curriculum seed

`scripts/seed_learning_curriculum.py` seeds **"Investing Foundations"**:
8 skills, 1 path, 4 modules (*Money and Inflation*, *Stocks, Bonds, and
Funds*, *Risk and Return*, *Diversification*), 8 lessons, and 24
exercises across 5 exercise types. Every ID is derived deterministically
via `uuid.uuid5`, so **re-running the script is idempotent** — it
updates the same rows in place rather than creating duplicates. All
content is in English, with clear correct answers and feedback, no
investment recommendations, and no claims of guaranteed return.

```powershell
python scripts/seed_learning_curriculum.py
```

### CLI

```powershell
# Curriculum content counts
python -m stock_research_core.cli.learning_status --curriculum

# Create a learner (preferred_language defaults to "en")
python -m stock_research_core.cli.learning_status --create-learner "Amit"

# View a learner's dashboard
python -m stock_research_core.cli.learning_status --learner-id <UUID>
```

### Unit versus integration tests

- **`tests/unit/`** (no PostgreSQL): `test_learning_domain_models.py`
  (validation rules), `test_learning_mappers.py` (ORM↔domain, as plain
  Python objects), `test_learning_unit_of_work.py` (mocked session
  factory), and `test_learning_service.py` (grading rules, the
  `mastery-v1` calculator, and `LearningService` orchestration against
  fake repositories and a fake Unit of Work).
- **`tests/integration/`** (real `stock_research_test` database, marked
  `@pytest.mark.integration`, skip cleanly if unreachable):
  `test_learner_repository.py`, `test_curriculum_repository.py`
  (+ schema/migration checks), `test_attempt_repository.py`,
  `test_mastery_repository.py` (+ misconceptions), and
  `test_learning_progress_repository.py` (+ a full
  service-level submission round trip, a rollback check, and a check
  that Phase 1–3 market tables are still valid).

```powershell
pytest                      # everything
pytest -m "not integration" # unit tests only, no database needed
pytest -m integration       # integration tests only (requires stock-db running)
```

### Current limitations

- No frontend, authentication provider, AI tutor, LLM calls, RAG,
  embeddings, n8n, or machine learning yet.
- No historical market scenarios, virtual portfolios, payments,
  notifications, social features, or leaderboards yet.
- Diagnostic assessments and true adaptive learning-path sequencing are
  not implemented — the domain is *shaped* to support them later
  (skills, prerequisites, mastery, misconceptions) without being
  coupled to any specific algorithm.
- Misconception *detection* is out of scope; only storage/validation of
  already-detected misconceptions is implemented.

## Phase 5: adaptive learning engine

Phase 5 adds the first version of the **adaptive learning engine**: the
component that decides what a learner should practice next. It builds
entirely on top of Phase 4's curriculum, attempts, mastery, and
progress — nothing from Phase 1–4 is modified. **English remains the
default and only learner-facing language** (recommendation
explanations, diagnostic instructions, session/CLI text, seeded
adaptive metadata).

### Why the first policy is rule-based

Every adaptive decision in this phase comes from a small set of
**explicit, documented, deterministic rules** — not machine learning,
not an LLM, and no randomness. This is deliberate: a rule-based policy
is auditable from day one (every decision can be explained in plain
English and traced back to the exact inputs that produced it), and it
establishes the `Protocol` seam (`AdaptivePolicyPort`,
`DifficultyPolicyPort`, `ReviewSchedulingPolicyPort`,
`DiagnosticPolicyPort`) that a future ML-based policy can implement
later **without changing `AdaptiveLearningService`, the persistence
schema, or any CLI/API contract**.

```text
domain/adaptive_learning/        <- enums, 7 domain models (no learning-domain import - plain UUIDs)
application/adaptive_learning/   <- app models, ports (Protocols), 4 deterministic policies, service, orchestrator
infrastructure/database/orm/, mappers/, repositories/  <- SQLAlchemy, mapped to/from domain models
cli/adaptive_learning.py         <- composition root
```

### Exercise adaptive profiles

`ExerciseAdaptiveProfile` attaches adaptive metadata to an existing
`Exercise` (base difficulty score, estimated seconds, diagnostic/
review/remediation eligibility, an optional mastery-score range, and
normalized `policy_tags`) **without duplicating** the exercise's
prompt, options, or skill relations. Every seeded exercise gets exactly
one profile (`scripts/seed_adaptive_learning_profiles.py`, idempotent,
deterministic `uuid.uuid5` IDs keyed off the exercise ID).

### Learning sessions

A `LearningSession` bounds one block of practice (`DAILY_PRACTICE`,
`DIAGNOSTIC`, `REVIEW`, `LESSON_PRACTICE`, or `FREE_PRACTICE`) with a
goal in minutes, running counts (recommended/completed/correct items,
score), and a `LearningSessionActivity` per recommended exercise
(recommendation → start → completion/skip). Starting a second
`DAILY_PRACTICE` session while one is already active **reuses the
existing session** rather than erroring, keeping "start my daily
practice" idempotent from a learner's point of view.

### Skill-priority rules (`adaptive-policy-v1`)

`RuleBasedAdaptivePolicy` picks the single best next exercise from an
already-eligible candidate pool using a **strict 7-tier priority
order** — the tier always wins; nothing later can outscore an earlier
tier:

```text
1. Active misconception remediation
2. Overdue review
3. Failed prerequisite skill
4. Recent repeated failure
5. Low-mastery skill
6. In-progress lesson (new content, but continuing what's started)
7. New eligible lesson content
   (no eligible candidates at all -> NO_ELIGIBLE_CONTENT)
```

Within a tier, a **continuous weighted priority score** (0–1, always
computed and stored for every candidate) breaks ties, followed by
lower lesson position, lower exercise position, and finally the
exercise's UUID string — fully deterministic, never `random.choice`.

| Component | Weight |
|---|---|
| Misconception urgency | 0.25 |
| Review urgency | 0.20 |
| Mastery gap | 0.20 |
| Prerequisite importance | 0.15 |
| Recent-failure signal | 0.10 |
| Lesson-progress relevance | 0.05 |
| Novelty | 0.05 |

(weights sum to exactly 1.0, asserted at policy construction). Every
decision's `input_snapshot` records the policy version, winning tier,
winning exercise ID, rounded component scores, and the weights table —
**never** a full learner/exercise object or anything secret. Every
recommendation carries a short English explanation, e.g. *"This
exercise targets a misconception detected in your recent answers"* or
*"Your mastery of this skill is still developing, so this exercise will
help you build it up."*

**Cooldown**: an exercise completed or skipped within the last 3
resolved activities *in the current session* is excluded from
recommendation, unless it qualifies for a documented bypass (overdue
review, active misconception, or repeated recent failure) — preventing
both immediate repetition and an infinite skip loop, without relying on
calendar days as the only signal.

### Difficulty adaptation (`difficulty-policy-v1`)

`RuleBasedDifficultyPolicy` targets a difficulty score from the
learner's mastery band (< 0.30 → 0.20, 0.30–0.60 → 0.40, 0.60–0.85 →
0.60, ≥ 0.85 → 0.80), then adjusts: 2+ consecutive incorrect answers
always **decreases** difficulty (−0.15, plus an extra −0.10 if the miss
came with high/very-high confidence — a likely misconception signal); a
decrease always takes precedence over an increase; 3+ consecutive
correct answers **increases** difficulty (+0.10) *unless* confidence
was low/very-low. Final score is clamped to `[0, 1]`.

### Deterministic spaced repetition (`review-schedule-v1`)

`DeterministicReviewSchedulingPolicy` is a transparent rule set, not a
proprietary algorithm. First review interval depends on score and
confidence (incorrect → 1 day, partial → 2 days, correct+low/no
confidence → 3 days, correct+medium → 5 days, correct+high/very-high →
7 days). Later successful reviews grow the interval
(`max(first_review_interval, round(previous_interval * ease_factor))`)
and nudge the ease factor (+0.10 for a strong high-confidence result,
unchanged otherwise, clamped to `[1.3, 2.8]`); a failed review resets to
a 1-day interval, resets the consecutive-success streak, and decreases
ease (−0.10 partial, −0.20 incorrect).

### Diagnostic assessments (`diagnostic-policy-v1`)

`RuleBasedDiagnosticPolicy.select_items` builds a diagnostic
deterministically: candidates are grouped by requested skill, sorted
(unattempted first, then closeness of difficulty to 0.5, then a stable
UUID string), and chosen **round-robin across skills** so breadth of
coverage is maximized before a second item is added for any one skill.
`summarize` averages normalized scores per skill into
`NOT_ASSESSED` / `NEEDS_FOUNDATION` (< 0.30) / `DEVELOPING` (< 0.60) /
`READY` (< 0.85) / `STRONG` (≥ 0.85), and recommends starting skills
(needs-foundation first, else not-yet-assessed, else all). On
completion, `compute_initial_mastery` blends into skill mastery: a
brand-new skill takes the diagnostic score directly; an existing skill
blends `0.6 × previous + 0.4 × diagnostic`. `MASTERED` is **never**
assigned from a diagnostic alone unless at least 3 diagnostic items
covered the skill *and* the raw diagnostic score is ≥ 0.90.

### Auditability and versioning

Every recommendation is persisted as an `AdaptiveDecision` — an
immutable audit record with `policy_version`, a sanitized
`input_snapshot`, an English `explanation`, target skills, reason
codes, and a full status lifecycle (`GENERATED` → `ACCEPTED` →
`COMPLETED`/`SKIPPED`/`EXPIRED`). Given the same learner state and
policy version, the same recommendation is always produced — no policy
in this phase uses `random` for anything.

### Orchestration

`AdaptiveLearningOrchestrator` composes the existing, already-tested
`LearningService.submit_answer` with the new
`AdaptiveLearningService.record_completed_activity` — grading logic is
**never duplicated**. The two live in separate bounded transactions
(their own Unit of Work each) rather than one shared transaction, since
forcing a shared transaction would require leaking SQLAlchemy session
details across a Protocol boundary. Documented compensation: if grading
succeeds but recording the adaptive outcome fails afterward, the grade
is **not** rolled back (it's independently valid); the adaptive
decision/activity is simply left unresolved, and retrying
`submit_recommended_answer` is safe and idempotent.

### Database migration

`migrations/versions/0003_adaptive_learning.py` (depends on
`0002_learning_core`) adds 11 tables: `exercise_adaptive_profiles`,
`learning_sessions` (+ `learning_session_activities`),
`diagnostic_assessments` (+ `diagnostic_assessment_skills`),
`diagnostic_assessment_items` (+ `diagnostic_item_skills`),
`skill_review_schedules`, and `adaptive_decisions` (+
`adaptive_decision_target_skills`, `adaptive_decision_reasons`).
Association tables model every skill/reason relationship explicitly —
JSONB (`adaptive_decisions.input_snapshot`) is used only for the
sanitized, primitive decision-input snapshot, never as a stand-in for a
real relationship. No TimescaleDB hypertable is needed here. All
Phase 1–4 tables are untouched.

```powershell
alembic upgrade head
alembic current
```

### Adaptive-profile seed

`scripts/seed_adaptive_learning_profiles.py` loads the 24 exercises
seeded by Phase 4's curriculum script and creates one
`ExerciseAdaptiveProfile` per exercise: each lesson's first exercise
(position 0) is diagnostic- and review-eligible, its second (position
1) is review-eligible, and its third (position 2) is
remediation-eligible — 8 diagnostic-eligible, 16 review-eligible, and 8
remediation-eligible profiles in total, guaranteeing every one of the 8
seeded skills has at least one diagnostic-eligible exercise. IDs are
deterministic `uuid.uuid5` values keyed off the exercise ID, so
re-running the script is idempotent.

```powershell
python scripts/seed_learning_curriculum.py
python scripts/seed_adaptive_learning_profiles.py
```

### CLI

```powershell
# Start (or safely reuse) a daily practice session
python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --start-session

# Get the next recommendation in a session
python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --session-id <UUID> --next

# Start a diagnostic assessment
python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --start-diagnostic --maximum-items 6

# Check a diagnostic assessment's status
python -m stock_research_core.cli.adaptive_learning --diagnostic-id <UUID> --diagnostic-status

# List reviews currently due for a learner
python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --due-reviews

# Complete a session
python -m stock_research_core.cli.adaptive_learning --session-id <UUID> --complete-session
```

### Unit versus integration tests

- **`tests/unit/`** (no PostgreSQL): `test_adaptive_domain_models.py`
  (validation rules for all 7 domain models),
  `test_skill_priority_policy.py`, `test_difficulty_policy.py`,
  `test_spaced_repetition_policy.py`, `test_diagnostic_policy.py` (the
  4 deterministic policies), `test_adaptive_learning_service.py` and
  `test_adaptive_learning_orchestrator.py` (fake repositories/services,
  no SQLAlchemy), `test_adaptive_learning_mappers.py` (ORM↔domain, as
  plain Python objects), and `test_adaptive_architecture.py`
  (AST-based import-boundary checks: no SQLAlchemy/pandas/yfinance/
  LangGraph/LLM imports in `domain/adaptive_learning` or
  `application/adaptive_learning`, no `random`, no direct
  `datetime.now()`, `ports.py` stays a pure Protocol module).
- **`tests/integration/`** (real `stock_research_test` database, marked
  `@pytest.mark.integration`, skip cleanly if unreachable):
  `test_adaptive_profile_repository.py`,
  `test_learning_session_repository.py`,
  `test_diagnostic_repository.py`,
  `test_review_schedule_repository.py`,
  `test_adaptive_decision_repository.py`, and
  `test_adaptive_learning_end_to_end.py` (the full recommend → accept →
  start → grade → record-outcome flow and the full diagnostic flow
  against the real `AdaptiveLearningService`/`LearningService`/
  `AdaptiveLearningOrchestrator`, cooldown behavior, and a
  rollback check).

```powershell
pytest                      # everything
pytest -m "not integration" # unit tests only, no database needed
pytest -m integration       # integration tests only (requires stock-db running)
```

### Current limitations

- No machine learning, LLM calls, AI tutor, RAG, embeddings, or n8n
  yet — every policy here is deterministic and rule-based by design.
- No frontend, authentication provider, virtual portfolios,
  notifications, gamification/XP, streaks, social features, or
  leaderboards yet. (Historical market scenarios are now covered by
  Phase 6, below.)
- Misconception *detection* is still out of scope (unchanged from
  Phase 4) — the adaptive engine prioritizes *already-detected*
  misconceptions but never invents one from an attempt pattern.
- No stock/investment recommendations are produced anywhere in this
  phase.

## Phase 6: historical market scenario engine

Phase 6 connects the learning platform to the market-data foundation
from Phase 3: a learner is shown real historical OHLCV data truncated
at a **decision timestamp**, picks a decision, and is graded on the
**quality of the reasoning behind that decision** — never on whether
the market happened to move in their favor afterward. It builds
entirely on top of Phase 3 (`securities`/`market_bars`) and Phase 4/5
(exercises, attempts, mastery, adaptive sessions) — **nothing from
Phase 1–5 is modified except two purely additive extensions** (see
"Additive extensions" below). English remains the only learner-facing
language.

### The core educational principle

A historical scenario must never reward a lucky guess or punish a
sound, unlucky decision. The system explicitly separates three
numbers that a naive implementation would conflate into one:

```text
decision_quality_score   <- graded from the selected option's rubric; the ONLY score that updates skill mastery
outcome_alignment_score  <- computed only after reveal, from the realized return; display-only, never re-grades anything
total_display_score      <- a blended, display-only number combining the two above
```

`ScenarioOptionRubric.decision_quality_score` and everything that feeds
it (risk awareness, benchmark awareness, horizon alignment, information
sufficiency, uncertainty awareness) is fixed **at rubric-authoring
time** and never reads a realized market return — the grading policy's
`grade()` method has no `outcome`/`ScenarioOutcome` parameter at all,
so it is structurally impossible for a future market move to influence
it. After reveal, the same submission also gets an explicit
process-versus-outcome classification and explanation:

```text
GOOD_PROCESS_GOOD_OUTCOME   BAD_PROCESS_GOOD_OUTCOME
GOOD_PROCESS_BAD_OUTCOME    BAD_PROCESS_BAD_OUTCOME
```

### Point-in-time safety

Every learner-facing view is built from bars filtered to
`observation_start_at <= timestamp <= decision_at`; the calculator
never receives, and the learner-safe application models
(`LearnerScenarioView`, `LearnerSafeExerciseOption`) structurally
cannot carry, a bar after that cutoff, a rubric score, an `is_correct`
flag, or a `ScenarioOutcome` — not merely unset, but absent from the
Pydantic schema entirely (`extra="forbid"` everywhere). This is
verified by a dedicated regression suite,
`tests/unit/test_market_scenario_point_in_time.py`, built on synthetic
bars `T1..T120` with the decision at `T80` and reveal end at `T110`: it
proves the learner chart never contains a bar after `T80`, that
tampering with `T81..T120` never changes the observation metrics or the
graded `decision_quality_score`, and that only `ScenarioOutcome`
(computed strictly from bars after `T80`, up to `T110`) changes when the
future is different.

```text
domain/market_scenarios/          <- enums, 7 domain models (UUID-only refs to Security/Exercise, plus the reused ConfidenceLevel enum)
application/market_scenarios/     <- learner-safe models, ports (Protocols), calculator port + version/threshold constants,
                                      RuleBasedScenarioGradingPolicy, HistoricalMarketScenarioService, orchestrator
infrastructure/market_scenarios/  <- PandasScenarioCalculator (the only place pandas/NumPy may appear for this feature)
infrastructure/database/orm/, mappers/, repositories/  <- SQLAlchemy, mapped to/from domain models
cli/market_scenarios.py           <- composition root
```

### Scenario lifecycle

`HistoricalMarketScenario` moves `DRAFT` → `READY` → `PUBLISHED` (or
`ARCHIVED`/`INVALID`), gated by
`HistoricalMarketScenarioService.create_or_update_scenario`, which
checks: the linked exercise is really `SCENARIO_DECISION`; every
exercise option has exactly one rubric and no rubric references an
outside option; the focal (and optional benchmark) security exists;
enough stored bars exist for both the observation window (≥
`minimum_observation_bars`) and the future reveal window (≥
`minimum_reveal_bars`); and no learner-safe text (title, description,
prompt, instructions) contains forward-looking language. A learner's
own submission lifecycle is separate:
`STARTED → SUBMITTED/GRADED → REVEALED` (or `ABANDONED`), enforced by
`ScenarioSubmission`'s own validators (e.g. a `STARTED` submission
cannot yet have a `selected_option_id`, decision score, or feedback).

### Deterministic calculation and grading

`PandasScenarioCalculator` (`scenario-observation-v1` /
`scenario-outcome-v1`) sorts bars ascending, resolves duplicate
timestamps deterministically (keep the latest, log a warning — never
raises on a duplicate, only on genuinely insufficient distinct bars),
and computes: observation return, annualized volatility (log returns,
`sqrt(252)`), maximum observation drawdown, average volume,
benchmark/excess return, then — strictly from bars *after* the decision
cutoff — the realized focal return, maximum future upside/drawdown, and
benchmark/excess return. Outcome direction uses a documented ±1% band
(`> +1%` → `POSITIVE`, `< -1%` → `NEGATIVE`, else `FLAT`). All pandas/
NumPy work runs inside `asyncio.to_thread`; only domain objects ever
leave the calculator — a `DataFrame` never crosses into the application
layer.

`RuleBasedScenarioGradingPolicy` (`scenario-grading-v1`) starts from
the rubric's own weighted score —

| Component | Weight |
|---|---|
| Risk awareness | 0.30 |
| Benchmark awareness | 0.20 |
| Horizon alignment | 0.20 |
| Information sufficiency | 0.15 |
| Uncertainty awareness | 0.15 |

(defined once, in `domain.market_scenarios.models.
RUBRIC_COMPONENT_WEIGHTS`, and re-validated on every stored rubric so
it can never drift from the formula that produced it) — then applies a
small, documented confidence adjustment: `HIGH`/`VERY_HIGH` confidence
on a rubric scoring below 0.50 costs −0.10 (`OVERCONFIDENT_DECISION`);
`LOW`/`VERY_LOW` confidence on a rubric scoring ≥ 0.80 costs nothing,
but adds calibration feedback (`RECOGNIZED_UNCERTAINTY`). The result is
clamped to `[0, 1]` and classified `POOR` (< 0.30) / `DEVELOPING`
(< 0.60) / `GOOD` (< 0.85) / `STRONG` (≥ 0.85). Outcome alignment
(post-reveal, display-only) compares the rubric's `expected_direction`
against the realized `ScenarioOutcomeDirection`: 1.0 for a directional
match, 0.0 for a mismatch, 0.5 for a `NEUTRAL`/`INFORMATION_REQUIRED`
decision or a directional decision facing a `FLAT` outcome.

### Additive extensions to existing modules

Two small, backward-compatible extensions make grading reuse possible
without duplicating it:

- `ExerciseAttempt` gains one new optional field,
  `grading_version: str | None = None` (nullable column, defaults to
  `None` for every existing row) — recording *how* an attempt was
  graded when it wasn't the deterministic auto-grader.
- `LearningService` gains `submit_externally_graded_answer(...)`,
  extracted from `submit_answer` via a shared private
  `_finalize_graded_attempt` helper so **both** paths run the exact
  same answer-persistence, attempt-transition, mastery-update
  (`MasteryCalculatorPort`), and lesson-progress logic — no mastery
  formula is duplicated in the scenario module.
  `HistoricalMarketScenarioService` calls this only through the small
  `ExternallyGradedAnswerPort` Protocol it depends on (never importing
  `LearningService` directly), and only ever passes it the
  `decision_quality_score` — never a realized return, alignment score,
  or blended display score.

`AdaptiveLearningService` similarly gains an optional
`scenario_eligibility: ScenarioEligibilityPort | None` constructor
parameter (a Protocol defined on the *adaptive* side, so the adaptive
engine stays fully decoupled from the scenario feature). A
`SCENARIO_DECISION` exercise — previously excluded outright from
recommendation, since it has no deterministic auto-grader — is now
recommended only when a wired-in eligibility checker confirms: the
scenario is `PUBLISHED`, every option has a rubric, and enough stored
bars exist for both windows.
`HistoricalMarketScenarioService.is_exercise_eligible` structurally
satisfies this Protocol without importing it.

### Database migration

`migrations/versions/0004_historical_market_scenarios.py` (depends on
`0003_adaptive_learning`) adds the nullable `exercise_attempts.
grading_version` column plus 10 tables: `historical_market_scenarios`
(+ `historical_market_scenario_primary_skills`/`_secondary_skills`),
`scenario_securities` (the source of truth for focal/benchmark — not
columns on the scenario row, mirroring how `Lesson.secondary_skill_ids`
lives apart from `lessons`), `scenario_option_rubrics` (+
`scenario_option_rubric_feedback_codes`), `scenario_outcomes` (unique
per `(scenario_id, calculation_version)` — the *only* new table that
stores a calculated result; `ScenarioObservationMetrics` is cheap
enough to always recompute on demand and is never persisted),
`scenario_submissions` (+ `scenario_submission_feedback_codes`, unique
per `exercise_attempt_id`), and `scenario_generation_runs` (an
append-only audit log — never deduplicated, since each seed-script
invocation is a legitimately new attempt). No raw price bar is ever
stored twice: scenarios reference `market_bars` by
`(security_id, source_name, interval, time range)`. All Phase 1–5
tables are untouched.

```powershell
alembic upgrade head
alembic current
```

### Scenario seed script

`scripts/seed_historical_market_scenarios.py` reads bars **already
stored** by Phase 3 ingestion (never calls yfinance) and deterministically
picks up to `--scenario-count` decision windows, evenly spaced across
the stored history, each requiring ≥ 40 observation bars and ≥ 20
future reveal bars. Every ID (scenario, exercise, options, rubrics,
adaptive profile) is a stable `uuid.uuid5` derived from the scenario
code (`{TICKER}_{decision_date}`), so re-running the script updates the
same rows in place. Five fixed, ticker-agnostic decision options are
reused for every scenario (invest-on-momentum, wait-for-information,
diversify, small-long-term-position, avoid-on-recent-decline), each
with hand-authored rubric component scores — **never** derived from
the security's actual later return. `RISK_AND_RETURN` is reused if
already seeded by `seed_learning_curriculum.py`; `MARKET_INDEXES`,
`CHART_READING`, and `LONG_TERM_INVESTING` are created if missing. A
scenario is marked `PUBLISHED` only after passing the same validation
`create_or_update_scenario` runs for any admin edit.

```powershell
# Prerequisite: stored bars must already exist (see "CLI examples" under Phase 3 above)
python -m stock_research_core.cli.ingest_and_store --ticker NVDA --start 2023-01-01 --end 2024-01-01
python -m stock_research_core.cli.ingest_and_store --benchmark SPY --start 2023-01-01 --end 2024-01-01

python scripts/seed_historical_market_scenarios.py `
  --ticker NVDA `
  --benchmark SPY `
  --scenario-count 4
```

### CLI

```powershell
# List published scenarios
python -m stock_research_core.cli.market_scenarios --list

# View a learner-safe scenario (no future data, no rubric scores, no is_correct)
python -m stock_research_core.cli.market_scenarios `
  --learner-id <UUID> --scenario-id <UUID> --view

# Start a scenario against an already-started exercise attempt
python -m stock_research_core.cli.market_scenarios `
  --learner-id <UUID> --scenario-id <UUID> --attempt-id <UUID> --start

# Submit a decision (feedback shown; future outcome NOT shown yet)
python -m stock_research_core.cli.market_scenarios `
  --submission-id <UUID> --option-id <UUID> --confidence HIGH `
  --rationale "I would limit the position because the risk is concentrated." --submit

# Reveal the realized outcome after grading
python -m stock_research_core.cli.market_scenarios --submission-id <UUID> --reveal

# Re-validate an already-stored scenario
python -m stock_research_core.cli.market_scenarios --scenario-id <UUID> --validate
```

### Unit versus integration tests

- **`tests/unit/`** (no PostgreSQL): `test_market_scenario_domain_models.py`
  (validation rules for all 7 domain models),
  `test_scenario_calculator.py` (sorting, dedup, every metric, both
  cutoff windows, insufficient-data errors, determinism — synthetic
  bars only), `test_scenario_grading_policy.py` (weighted score,
  confidence adjustment, classification thresholds, outcome alignment,
  all four process/outcome feedback combinations),
  `test_market_scenario_service.py` and
  `test_market_scenario_orchestrator.py` (fake repositories/services,
  no SQLAlchemy), `test_market_scenario_mappers.py` (ORM↔domain, as
  plain Python objects), `test_market_scenario_point_in_time.py` (the
  `T1..T120`/decision-`T80`/reveal-`T110` leakage regression suite
  described above), and `test_market_scenario_architecture.py`
  (AST-based import-boundary checks: no SQLAlchemy/pandas/NumPy/
  yfinance/LLM imports in `domain/market_scenarios` or
  `application/market_scenarios`, no `asyncio.to_thread` outside the
  infrastructure calculator, no direct `datetime.now()`,
  `LearnerScenarioView` structurally cannot carry a future field).
- **`tests/integration/`** (real `stock_research_test` database, marked
  `@pytest.mark.integration`, skip cleanly if unreachable):
  `test_market_scenario_repository.py` (migration reaches head, all 10
  tables + the new `exercise_attempts.grading_version` column exist,
  round trip, code uniqueness), `test_scenario_rubric_repository.py`,
  `test_scenario_outcome_repository.py` (idempotent upsert by
  calculation version), `test_scenario_submission_repository.py`,
  `test_scenario_generation_run_repository.py`, and
  `test_market_scenario_end_to_end.py` (the full learner flow against
  real Postgres with the real `PandasScenarioCalculator`,
  `RuleBasedScenarioGradingPolicy`, and `LearningService`: view → start
  → submit → mastery updated → reveal → idempotent re-reveal, future
  bars changing the outcome but never the decision-quality score or
  mastery, a failed unique-constraint upsert leaving no partial state,
  and the seed script's window selection run twice with no duplicates).

```powershell
pytest                      # everything
pytest -m "not integration" # unit tests only, no database needed
pytest -m integration       # integration tests only (requires stock-db running)
```

### Current limitations

- No news/article scenarios, event extraction, LLM calls, AI tutor,
  RAG, embeddings, machine learning, or n8n yet — every calculation and
  grading rule here is deterministic and versioned by design.
- No virtual portfolio trading, multi-asset simulation, options data,
  intraday data, real-money recommendations, or live buy/sell signals.
- Only one focal security and at most one benchmark per scenario in
  this phase — no multi-asset scenarios yet.
- Learner rationale text is stored and bounded but not scored — no
  keyword-based or LLM-based rationale grading exists yet, by design
  (grading always flows through the selected-option rubric alone).
- No frontend yet; the CLI is the only learner-facing surface so far.

## Phase 7: virtual portfolio and decision-journal engine

Phase 7 lets a learner build and manage an **educational, simulated
investment portfolio** using stored historical market data (Phase 3) —
buying and selling securities, journaling the reasoning behind every
decision, and receiving deterministic, English feedback about
diversification, concentration, drawdown, and turnover. It builds
entirely on top of Phase 3 (`securities`/`market_bars`) — **nothing
from Phase 1–6 is modified except two purely additive
`MarketBarRepositoryPort` lookup methods** (see below). This is a
simulation for learning, not a brokerage account: it never recommends
a specific security, never predicts a price move, and never claims a
guaranteed return.

```text
domain/virtual_portfolio/        <- enums, 9 domain models (UUID-only refs to Learner/Security/Skill)
application/virtual_portfolio/   <- app models, repository ports, execution.py (trade + accounting policies),
                                     analytics.py (pure Protocol), feedback.py (risk policy),
                                     VirtualPortfolioService, PortfolioValuationService
infrastructure/virtual_portfolio/ <- PandasPortfolioAnalytics (the only place pandas/NumPy may appear for this feature)
infrastructure/database/orm/, mappers/, repositories/  <- SQLAlchemy, mapped to/from domain models
cli/virtual_portfolio.py         <- composition root
```

### Point-in-time trade execution

`NextAvailableOpenExecutionPolicy` (`next-available-open-v1`) is the
single load-bearing rule of this whole feature: **a trade executes at
the OPEN price of the first stored daily bar whose timestamp is
strictly later than the request time** — never a same-day or earlier
price, never an interpolated missing day, never a provider call. This
is verified by a dedicated regression suite,
`tests/unit/test_virtual_portfolio_point_in_time.py`, built on
synthetic bars `T1..T100`: a trade requested at `T50` always executes
at `T51`'s open, never `T50`'s close or `T52`'s open, and mutating
every bar from `T52` onward never changes that execution. The same
file proves a valuation as of `T70` uses no price after `T70`, and
that a benchmark return computed through `T70` is identical whether or
not later bars even exist.

### Trades, fees, and average-cost accounting

A `PortfolioTransaction` moves `PENDING` → `EXECUTED`/`REJECTED`/
`CANCELLED`, carrying its own `execution_rule_version` for full
audit/reproducibility. Fees are deterministic:

```text
fee = fixed_transaction_fee + gross_amount * transaction_fee_bps / 10,000
BUY:  cash_effect = -(gross_amount + fee)
SELL: cash_effect =  gross_amount - fee
```

`AverageCostPortfolioAccountingPolicy` (`average-cost-accounting-v1`)
keeps one weighted-average-cost lot per `(portfolio, security)` — no
individual tax lots, no FIFO/LIFO choice. A buy folds the new gross
amount and fee into the cost basis and recomputes the average; a sell
computes `realized_pnl = gross_proceeds - fee - (average_cost *
quantity_sold)`, leaving the average cost unchanged on a partial sell
and zeroing it out only once the position is fully closed. Every
`PortfolioHolding` enforces `cost_basis == quantity * average_cost`
(within tolerance) and forbids short positions outright (`quantity`
can never go negative).

### Idempotent, concurrency-safe execution

`VirtualPortfolioService.execute_trade` locks the portfolio row (and
the affected holding row, if one exists) with `SELECT ... FOR UPDATE`
before doing anything else, so two concurrent requests against the
same portfolio serialize instead of racing. Every trade carries a
caller-supplied `idempotency_key`, unique per `(portfolio_id,
idempotency_key)` at the database level — replaying the same key
(even from two truly concurrent requests) returns the original,
already-decided result (success **or** rejection) rather than
re-executing anything. `tests/integration/test_portfolio_concurrency.py`
proves this against the real test database: two concurrent buys that
together exceed available cash leave exactly one executed and cash
never negative; two concurrent sells that together exceed the held
quantity leave exactly one executed; and a rejected trade releases its
row locks immediately (the next call never hangs).

### Decision journal

Every trade *may* (and, when `require_decision_journal=True`, *must*)
carry a `PortfolioDecisionJournalEntry`: a rationale (10–5000
characters), an optional expected time horizon, a confidence level,
and normalized, deduplicated lists of documented risks, information
considered, and assumptions. `HOLD`, `REBALANCE`, and `RESEARCH_MORE`
can also be journaled on their own, with no trade attached — a
deliberate "I chose not to act" is a recordable decision.

### Portfolio valuation and risk feedback

`PandasPortfolioAnalytics` (`portfolio-valuation-v1` /
`portfolio-performance-v1`) prices each holding at the latest stored
bar at or before the valuation moment (adjusted close), then computes
market value, unrealized P&L, position/sector weights, HHI
concentration (`sum(weight²)`), and a documented diversification score:

```text
diversification_score =
    0.50 * (1 - portfolio_hhi)
  + 0.30 * (1 - sector_hhi)      <- reallocated into the position component when no holding has known sector data
  + 0.20 * min(position_count / 10, 1)
```

Realized P&L is summed across **every** holding a portfolio has ever
held, including fully-sold (zero-quantity) ones — a closed position's
gain or loss still counts toward the portfolio's lifetime total.
`RuleBasedPortfolioFeedbackPolicy` (`portfolio-feedback-v1`) then turns
the snapshot (plus optional performance and recent journal entries)
into deterministic English feedback — concentration, sector exposure,
diversification, cash allocation, drawdown, volatility, turnover,
missing benchmark, and journal quality (missing horizon/risks,
overconfidence without documented risk, or a well-documented decision)
— describing portfolio **characteristics only**, never a buy/sell
instruction or a promise about future returns. An overall
`risk_level` is the unweighted average of whichever component scores
are available for that valuation, banded `LOW`/`MODERATE`/`HIGH`/
`VERY_HIGH`.

Performance over a date range (`calculate_performance`) reports total
return, annualized volatility (daily returns, `sqrt(252)`), maximum
drawdown (past peaks only — a later catastrophic snapshot never
distorts an earlier window's drawdown), benchmark/excess return, and
turnover ratio (`sum(executed trade gross amounts) / average portfolio
value` over the window).

### Bounded parallel valuation

`PortfolioValuationService.value_many` values several portfolios
concurrently under an `asyncio.Semaphore(max_concurrency)`, with **one
independent Unit of Work per portfolio** — no `AsyncSession` is ever
shared across concurrent valuations. One portfolio's failure (missing
data, a bad state) is caught and reported as a `FAILED` item without
affecting any other portfolio's result; input order is preserved and
duplicate portfolio IDs are silently deduplicated.

### A TimescaleDB hypertable, and its one real constraint

`portfolio_valuation_snapshots` is a TimescaleDB hypertable partitioned
by `as_of`, exactly like `market_bars`. TimescaleDB requires every
unique/primary-key constraint on a hypertable to include the
partitioning column, so its primary key is `(snapshot_id, as_of)`
rather than `snapshot_id` alone. This means `portfolio_position_
valuations.snapshot_id` and `portfolio_risk_assessments.snapshot_id`
**cannot** carry a database-level foreign key back to the hypertable
(Postgres requires an FK to reference a full unique constraint on the
parent) — they're plain, indexed UUID columns instead, with
referential integrity enforced at the application layer. This is a
well-known, documented TimescaleDB limitation, not an oversight;
see the docstring in `infrastructure/database/orm/portfolio_valuation_
snapshot.py` for the full explanation.

### Additive extension to Phase 3

`MarketBarRepositoryPort` gains two read-only lookup methods —
`get_next_bar_after` (the point-in-time execution rule) and
`get_latest_bar_at_or_before` (point-in-time valuation) — implemented
against the existing `market_bars` hypertable with no schema change at
all. Every other Phase 1–6 table, model, and service is untouched.

### Database migration

`migrations/versions/0005_virtual_portfolios.py` (depends on
`0004_historical_market_scenarios`) adds 13 tables: `virtual_portfolios`,
`portfolio_transactions`, `portfolio_holdings`, `portfolio_decision_
journal_entries` (+ `_risk_tags`/`_information_items`/`_assumptions`),
`portfolio_valuation_snapshots` (hypertable), `portfolio_position_
valuations`, `portfolio_risk_assessments` (+ `_feedback_codes`/
`_skills`), and `portfolio_valuation_runs` (an audit trail of every
valuation attempt, including `NO_PRICE_DATA` and `FAILED` outcomes).
Association tables model every risk-tag/feedback-code/skill
relationship explicitly — JSONB is used nowhere in this schema (free-
text `educational_feedback` is a plain Postgres array, matching the
"soft, auxiliary content" pattern already used for `policy_tags` in
Phase 5). All Phase 1–6 tables are untouched.

```powershell
alembic upgrade head
alembic current
```

### CLI

```powershell
# Create a portfolio (benchmark ticker must already be stored)
python -m stock_research_core.cli.virtual_portfolio `
  --learner-id <UUID> --create --name "Learning Portfolio" `
  --initial-cash 10000 --start-date 2024-01-02 --benchmark SPY

# View a portfolio overview
python -m stock_research_core.cli.virtual_portfolio --portfolio-id <UUID> --overview

# Preview a buy (no mutation)
python -m stock_research_core.cli.virtual_portfolio `
  --portfolio-id <UUID> --preview-buy NVDA --quantity 5 --requested-at 2024-02-01

# Execute a buy with a decision journal entry
python -m stock_research_core.cli.virtual_portfolio `
  --portfolio-id <UUID> --buy NVDA --quantity 5 --requested-at 2024-02-01 `
  --idempotency-key buy-nvda-001 --confidence MEDIUM --horizon-days 365 `
  --rationale "I want limited exposure as part of a diversified long-term simulation." `
  --risk-tag concentration --risk-tag volatility

# Execute a sell
python -m stock_research_core.cli.virtual_portfolio `
  --portfolio-id <UUID> --sell NVDA --quantity 2 --requested-at 2024-06-03 `
  --idempotency-key sell-nvda-001 --confidence MEDIUM --horizon-days 180 `
  --rationale "The position has become a large share of the simulated portfolio." `
  --risk-tag concentration

# Record a non-trade decision
python -m stock_research_core.cli.virtual_portfolio `
  --portfolio-id <UUID> --record-decision RESEARCH_MORE --ticker NVDA `
  --decision-at 2024-07-01 --confidence LOW `
  --rationale "I do not yet have enough information to make a simulated trade."

# Value the portfolio
python -m stock_research_core.cli.virtual_portfolio --portfolio-id <UUID> --value-at 2024-12-31

# Performance report over a date range
python -m stock_research_core.cli.virtual_portfolio `
  --portfolio-id <UUID> --performance --start 2024-01-02 --end 2024-12-31
```

### Unit versus integration tests

- **`tests/unit/`** (no PostgreSQL): `test_virtual_portfolio_domain_models.py`
  (validation rules for all 9 domain models), `test_trade_execution_policy.py`,
  `test_portfolio_accounting.py`, `test_portfolio_analytics.py`,
  `test_portfolio_feedback_policy.py` (the 4 deterministic policies),
  `test_virtual_portfolio_service.py` and `test_portfolio_valuation_service.py`
  (fake repositories/services, no SQLAlchemy), `test_portfolio_parallelism.py`
  (bounded-concurrency and independent-Unit-of-Work checks),
  `test_virtual_portfolio_mappers.py` (ORM↔domain, as plain Python objects),
  `test_virtual_portfolio_point_in_time.py` (the `T1..T100` leakage
  regression suite described above), and `test_virtual_portfolio_architecture.py`
  (AST-based import-boundary checks: no SQLAlchemy/pandas/NumPy/yfinance/
  LLM imports in `domain/virtual_portfolio` or `application/virtual_portfolio`,
  pandas confined to `infrastructure/virtual_portfolio`, no direct
  `datetime.now()`, no `DataFrame` leaving infrastructure).
- **`tests/integration/`** (real `stock_research_test` database, marked
  `@pytest.mark.integration`, skip cleanly if unreachable):
  `test_virtual_portfolio_repository.py` (migration reaches head, all 13
  tables + the hypertable exist, round trip, `FOR UPDATE` locking),
  `test_portfolio_transaction_repository.py` (idempotency-key uniqueness),
  `test_portfolio_holding_repository.py`, `test_portfolio_journal_repository.py`,
  `test_portfolio_valuation_repository.py`, `test_portfolio_risk_repository.py`
  (all idempotent upserts), `test_portfolio_concurrency.py` (real concurrent
  trades against real Postgres row locks), and
  `test_virtual_portfolio_end_to_end.py` (the full create → buy → sell →
  value → performance flow against real Postgres with the real
  `PandasPortfolioAnalytics` and `RuleBasedPortfolioFeedbackPolicy`, a
  rejected trade leaving no partial state, and bounded parallel valuation
  across several portfolios).

```powershell
pytest                      # everything
pytest -m "not integration" # unit tests only, no database needed
pytest -m integration       # integration tests only (requires stock-db running)
```

### Current limitations

- No real brokerage integration, live trading, order-book simulation,
  limit/stop orders, short selling, margin, leverage, options,
  cryptocurrency, or bonds without stored market data.
- No foreign-exchange conversion, dividend processing, corporate-action
  processing, or tax calculation — Phase 7 is USD-only, single-lot,
  and does not model cash flows other than trades and fees.
- No AI tutor, LLM calls, RAG, n8n, frontend, gamification, or
  personalized financial recommendations — every calculation and
  feedback rule here is deterministic and versioned by design.
- Educational feedback describes portfolio characteristics only; it
  never recommends a security, predicts a price move, or promises a
  return.

## Phase 8: grounded financial-education AI tutor and RAG engine

Phase 8 adds a conversational tutor that answers financial-education
questions using **only approved FinQuest knowledge** — the published
curriculum plus explicitly approved local documents — retrieved via
hybrid (vector + lexical + metadata) search, with every factual claim
cited back to an exact retrieved chunk. It builds on Phase 3
(`securities`), Phase 4 (`learner_profiles`/curriculum), Phase 6
(historical scenarios), and Phase 7 (virtual portfolios) purely by
reading from their existing repositories through the same Unit of
Work — **nothing from Phase 1–7 is modified**. This is an educational
explainer, not a source of stock predictions: it refuses buy/sell
instructions and guaranteed-return claims, never reveals a scenario's
future outcome before reveal, and never prescribes a portfolio trade.

```text
domain/ai_tutor/                 <- 15 enums, 11 domain models (UUID-only refs to Learner/Lesson/Scenario/Portfolio/Skill)
application/ai_tutor/            <- app models, repository/provider ports, chunking.py (HeadingAwareWordChunker),
                                     guardrails.py (RuleBasedTutorGuardrail), prompt_builder.py, retrieval.py
                                     (HybridKnowledgeRetriever), knowledge_ingestion.py (KnowledgeIngestionService),
                                     service.py (GroundedAITutorService), lesson_tutor.py, scenario_tutor.py,
                                     portfolio_tutor.py
infrastructure/ai_tutor/         <- SentenceTransformerEmbeddingAdapter (lazy-loaded, optional `[ai_tutor]` extra),
                                     DeterministicFakeEmbeddingAdapter (test/dev-only), DeterministicExtractiveTutor,
                                     OpenAICompatibleTutorAdapter (httpx), local_document_parsers.py (pypdf/python-docx)
infrastructure/database/orm/, mappers/, repositories/  <- SQLAlchemy + pgvector, mapped to/from domain models
cli/knowledge_base.py, cli/ai_tutor.py  <- composition roots
scripts/seed_finquest_knowledge_base.py, scripts/evaluate_tutor_retrieval.py
```

### pgvector: no custom Docker image needed

Before writing migration `0006_grounded_ai_tutor`, the running
`timescale/timescaledb:2.17.2-pg16` container was checked directly:

```sql
SELECT name, default_version FROM pg_available_extensions WHERE name IN ('vector', 'timescaledb');
--     name     | default_version
-- -------------+-----------------
--  timescaledb | 2.17.2
--  vector      | 0.7.2
```

`vector` 0.7.2 (which supports HNSW indexes) is already bundled in this
image — no custom image, no rebuild, and the existing database volume
is untouched. `docker-compose.yml` is unchanged from Phase 3. The
migration only runs `CREATE EXTENSION IF NOT EXISTS vector;`. (For the
record: the image's base OS is Alpine 3.21, `apk`-based — relevant only
if a future pgvector version ever needs a custom build.)

`knowledge_chunk_embeddings.embedding` is a `vector(384)` column
(the default dimension for `sentence-transformers/all-MiniLM-L6-v2`),
indexed with `USING hnsw (embedding vector_cosine_ops)`. Lexical search
uses a GIN index over a small `LANGUAGE sql IMMUTABLE` wrapper function,
`knowledge_chunk_tsvector(heading_path, content)`, around
`to_tsvector('english', ...)` — Postgres's two-argument `to_tsvector`
is STABLE, not IMMUTABLE, so neither a generated column nor a plain
expression index accepts it directly; wrapping it in a same-body
immutable function (the language is a fixed literal, so this is safe)
is the standard pattern for indexing `to_tsvector` output.

### Cost-conscious, replaceable providers

Two tutor-model providers exist behind `TutorModelPort`, selected via
`TUTOR_MODEL_PROVIDER`:

- **`extractive` (default, zero cost, zero dependencies).**
  `DeterministicExtractiveTutor` selects the most query-relevant
  sentence from each top-ranked retrieved chunk by deterministic
  lowercase-token overlap — no LLM, no external API, no randomness.
  Reliable and inexpensive, but it extracts existing sentences rather
  than synthesizing new prose.
- **`openai_compatible`.** `OpenAICompatibleTutorAdapter` talks to any
  OpenAI-compatible chat-completions endpoint (a local Ollama `/v1`
  endpoint, vLLM, or a remote compatible provider) via `httpx`,
  configured entirely through environment variables
  (`TUTOR_MODEL_BASE_URL`/`TUTOR_MODEL_API_KEY`/`TUTOR_MODEL_NAME`/
  `TUTOR_MODEL_TIMEOUT_SECONDS`) — no commercial provider is
  hard-coded. It requires a structured `{"answer_markdown",
  "cited_chunk_ids"}` JSON response, retries only on transient network
  errors, and allows exactly one correction attempt on a structured-
  output validation failure before the caller falls back.

Similarly, `EMBEDDING_PROVIDER` selects between `sentence_transformer`
(`SentenceTransformerEmbeddingAdapter`, lazy-loaded — importing
`infrastructure.ai_tutor` never triggers a model download; requires
`pip install -e ".[ai_tutor]"` for the optional `sentence-transformers`/
`torch` dependency) and the dev/test-only `deterministic_fake`
(`DeterministicFakeEmbeddingAdapter`, hash-derived, unit-normalized,
384-dimensional by default so it works directly against the real
`vector(384)` column). **No unit or integration test requires a real
model or network access** — the fake adapter is dimension-matched
specifically so the full pgvector/HNSW query path can be exercised in
`tests/integration/test_hybrid_retrieval.py` without downloading
anything.

### Hybrid retrieval (`hybrid-retrieval-v1`)

`HybridKnowledgeRetriever` (pure orchestration, no SQLAlchemy) asks
`SqlAlchemyKnowledgeRepository.hybrid_search` (the pgvector/lexical SQL)
for two ranked candidate pools — pgvector cosine-distance and
PostgreSQL full-text — combined by **reciprocal rank fusion** (rank
position, not raw score) plus a deterministic metadata-relevance
bonus, then sorted by `(combined_score desc, metadata_score desc,
chunk_id asc)` for a fully stable order:

```text
combined_score = 0.65/(60+vector_rank) + 0.25/(60+lexical_rank) + 0.10*metadata_score
metadata_score = min(1.0, 0.10 + 1.00*[lesson/exercise/scenario/portfolio-code match]
                                   + min(1.00, 0.40*matching_skill_count))
```

Only `APPROVED`+`PROCESSED` documents from `APPROVED` sources, in the
requested language, available at or before `knowledge_cutoff_at`
(defaulting to "now" when the context carries none), are ever
candidates. A structural safety filter,
`_apply_exercise_answer_leakage_guard`, additionally strips
`CURRICULUM_EXERCISE_EXPLANATION` content from `EXERCISE_HELP`
retrieval unless the context explicitly marks the exercise as already
submitted — enforced once, at the single choke point every retrieval
call passes through, rather than trusted to every caller.

### Guardrails and point-in-time scenario safety

`RuleBasedTutorGuardrail` (`tutor-guardrail-v1`) is deterministic
keyword/regex matching — no ML classifier, no randomness — evaluated
before any retrieval or generation (`evaluate_input`, REFUSE/
ALLOW_WITH_BOUNDARY/FALLBACK/ALLOW) and re-checked against the model's
own answer text afterward (`validate_output`, scanning for guaranteed-
return claims, direct buy/sell instructions, scenario future-
information leaks, portfolio trade prescriptions, unverified URLs, and
hidden-reasoning markers). `GroundedAITutorService.ask()` allows exactly
one regeneration attempt on a validation failure before falling back to
the exact required sentence.

For `SCENARIO_BEFORE_DECISION` conversations, point-in-time safety is
defense-in-depth at three independent layers: (1) `TutorConversation`'s
own domain validator requires `knowledge_cutoff_at` to be set — pinned
by `ScenarioTutorService` to `scenario.decision_at`, never computed
elsewhere; (2) the retriever never returns a chunk `available_at` after
that cutoff; (3) the guardrail refuses direct future-information
questions ("What happens next?", "Does the stock rise?", "Which option
is correct?") outright, and separately scans any generated answer text
for outcome-revealing language. `tests/unit/test_ai_tutor_point_in_time.py`
is the dedicated regression suite for this contract; scenario/portfolio
calculations themselves are never duplicated — `ScenarioTutorService`
and `PortfolioTutorService` only ever read from
`HistoricalMarketScenarioService`/`VirtualPortfolioService`/
`PortfolioValuationService`.

### CLI examples

```powershell
# Knowledge base status (vector/timescaledb extensions, counts, recent ingestion runs)
python -m stock_research_core.cli.knowledge_base --status

# Seed the knowledge base from the published curriculum
python -m stock_research_core.cli.knowledge_base --seed-curriculum

# Ingest an approved local document
python -m stock_research_core.cli.knowledge_base `
  --ingest-file "C:\path\to\notes.md" --source-title "Approved Notes" --approval APPROVED

# Hybrid search
python -m stock_research_core.cli.knowledge_base --search "Why does diversification reduce risk?" --top-k 5

# Start a conversation and ask a question
python -m stock_research_core.cli.ai_tutor --learner-id <UUID> --new-conversation GENERAL_EDUCATION
python -m stock_research_core.cli.ai_tutor --conversation-id <UUID> --ask "What is diversification?"

# Lesson / exercise / scenario / portfolio conversations
python -m stock_research_core.cli.ai_tutor --learner-id <UUID> --lesson-id <UUID> --new-lesson-conversation
python -m stock_research_core.cli.ai_tutor --learner-id <UUID> --exercise-id <UUID> --new-exercise-conversation
python -m stock_research_core.cli.ai_tutor `
  --learner-id <UUID> --scenario-id <UUID> --submission-id <UUID> --new-scenario-before-conversation
python -m stock_research_core.cli.ai_tutor --learner-id <UUID> --portfolio-id <UUID> --new-portfolio-conversation
```

To use the deterministic fake embedding provider instead of downloading
the real sentence-transformer model (useful for local exploration
without the `[ai_tutor]` extra installed), set
`$env:EMBEDDING_PROVIDER = "deterministic_fake"` before running either
CLI or `scripts/seed_finquest_knowledge_base.py`.

### Unit versus integration tests

- **`tests/unit/`** (no PostgreSQL): `test_ai_tutor_domain_models.py`
  (validation rules for all 11 domain models), `test_document_chunker.py`,
  `test_embedding_port.py` (the deterministic fake adapter's contract),
  `test_tutor_guardrails.py`, `test_tutor_prompt_builder.py`,
  `test_extractive_tutor.py`, `test_hybrid_retrieval_policy.py` (the
  exercise-answer leakage guard), `test_ai_tutor_service.py` (fake
  Unit of Work + fake retriever/tutor-model, real guardrail/prompt
  builder), `test_lesson_tutor_service.py`,
  `test_scenario_tutor_service.py`, `test_portfolio_tutor_service.py`,
  `test_ai_tutor_mappers.py` (ORM↔domain, as plain Python objects),
  `test_ai_tutor_point_in_time.py` (the scenario-leakage regression
  suite described above), and `test_ai_tutor_architecture.py`
  (AST-based import-boundary checks: no SQLAlchemy/pgvector/
  sentence-transformers/httpx/LLM imports in `domain/ai_tutor` or
  `application/ai_tutor`, no direct `datetime.now()`, no hidden-
  reasoning field on `TutorModelResult`).
- **`tests/integration/`** (real `stock_research_test` database, marked
  `@pytest.mark.integration`, skip cleanly if unreachable):
  `test_pgvector_extension.py` (extensions, HNSW/GIN indexes, the
  immutable tsvector function), `test_knowledge_repository.py`,
  `test_hybrid_retrieval.py` (the real pgvector + lexical query path,
  cutoff filtering, metadata-score ranking — all against the real
  `vector(384)` column via the dimension-matched fake embedding
  adapter), `test_conversation_repository.py`,
  `test_tutor_answer_repository.py`, `test_guardrail_repository.py`,
  `test_knowledge_gap_repository.py`, `test_retrieval_audit_repository.py`,
  and `test_ai_tutor_end_to_end.py` (the full ingest → create
  conversation → grounded answer → refusal → fallback → close flow
  against real Postgres with the extractive tutor).

```powershell
pytest                      # everything
pytest -m "not integration" # unit tests only, no database needed
pytest -m integration       # integration tests only (requires stock-db running)
```

### Current limitations

- No internet search, news ingestion, live web browsing, or automated
  SEC filing ingestion — only the published curriculum and explicitly
  approved local documents are ever retrievable.
- No stock recommendations, personalized asset allocation, real
  brokerage integration, ML-based personalization, or fine-tuning —
  the tutor explains concepts and already-computed metrics; it never
  decides anything on the learner's behalf.
- No autonomous agents, LangGraph, n8n, frontend, voice, notifications,
  gamification rewards, multi-language content, or RAGAS integration —
  retrieval evaluation (`scripts/evaluate_tutor_retrieval.py`) is fully
  deterministic (keyword-based relevance, exact guardrail-category
  matching), with no LLM judge. A RAGAS adapter may be layered on top
  once this deterministic pipeline is stable, but is out of scope here.

## Phase 9: FinQuest Product API, authentication, and authorization

A FastAPI transport layer over every Phase 1-8 application service, plus
a new local-account identity/authentication subsystem
(`domain.identity`/`application.identity`/`infrastructure.identity`).
No business logic is duplicated in the API layer - every route is a
thin, ownership-checked, DTO-mapping call into an existing application
service or (for simple lookups) a Unit-of-Work repository call.

### Identity subsystem

- **Accounts** (`UserAccount`) are a distinct identity concept from
  `LearnerProfile` - one account optionally links to one learner
  (`learner_id`), never the reverse. Roles: `LEARNER` < `CONTENT_EDITOR`
  < `ADMIN` (a hierarchy - an ADMIN satisfies any `LEARNER`-gated route).
- **Passwords**: Argon2id via `pwdlib` (`infrastructure.identity
  .argon2_password_hasher`). Policy (`application.identity.security
  .validate_password_policy`): 10-128 characters, at least 3 of
  {lowercase, uppercase, digit, symbol}, must not equal or contain the
  account's email, rejects a small explicit common-password list. A
  password hash is only ever returned by
  `get_credential_by_normalized_email` (login) and
  `change_password_hash` - never by `get_by_id`/`get_by_normalized_email`,
  and never crosses the API boundary.
- **Access tokens**: short-lived JWTs (`infrastructure.identity
  .jwt_access_token_service`, `jwt-access-v1`, default HS256,
  15 minutes). `AUTH_JWT_SECRET` must be >=32 characters and not a
  well-known placeholder - the API refuses to start without one outside
  `testing=True`. Never persisted anywhere; `decode_access_token`
  performs full signature/issuer/audience/expiry/required-claim
  validation in one call.
- **Refresh tokens**: opaque, `secrets.token_urlsafe(32)`
  (`opaque-refresh-v1`), only the SHA-256 hash is ever stored. Every
  `/auth/refresh` call **rotates** the token via a database-level
  compare-and-swap (`UPDATE ... WHERE status='ACTIVE' ... RETURNING`) -
  under concurrent refresh, at most one caller's rotation succeeds; the
  loser is treated as reuse. Reusing an already-rotated (or otherwise
  inactive) token **revokes the entire token family**, not just that
  token - a stolen-then-rotated token immediately invalidates the
  legitimate session's replacement too, forcing re-authentication.
- **Account lockout**: 5 failed logins locks the account for 15 minutes
  (`AUTH_MAX_FAILED_LOGINS`/`AUTH_LOCKOUT_MINUTES`); the lockout expires
  automatically on the next login attempt after `locked_until` passes.
  Login always raises the same generic error for "no such account" and
  "wrong password" - it never reveals whether an email is registered.
- **Audit**: every registration/login/refresh/logout/lockout event is
  appended to `authentication_audit_events` (`AuthenticationAuditEvent`)
  - correlation ID, hashed email/IP/user-agent (never raw), never a
  password or token.

### API foundation

- **Versioning**: every business route lives under `/api/v1`;
  `/health` (liveness, no database access) and `/ready` (PostgreSQL
  connectivity + Alembic revision + `timescaledb`/`vector` extension
  check) are unversioned and unauthenticated.
- **Error envelope** (every non-2xx response):
  ```json
  {"error": {"code": "NOT_FOUND", "message": "...", "details": [], "correlation_id": "..."}}
  ```
  Every `StockResearchError` subclass maps to an explicit
  `(status_code, code)` pair (`api/exception_handlers.py`); anything
  unmapped falls through to a generic `400 APPLICATION_ERROR`, and any
  truly unhandled exception degrades to a sanitized `500 INTERNAL_ERROR`
  - never a stack trace, SQL, or file path.
- **Pagination** (offset-based, `?limit=20&offset=0`, max `limit=100`):
  applied to genuinely growable per-learner/admin collections (mastery,
  progress, misconceptions, admin accounts) via a shared
  `{"items": [...], "pagination": {"limit", "offset", "returned", "total"}}`
  envelope - small fixed catalogs (learning paths/modules/lessons/
  exercises) are returned as plain lists.
- **Correlation IDs**: `CorrelationIdMiddleware` accepts and echoes a
  client-supplied `X-Correlation-ID` (validated format, generates a
  fresh UUID if absent or malformed) on every response, and every error
  envelope carries it.
- **Rate limiting**: `RateLimiterPort`/`InMemoryRateLimiter` - a
  fixed-window, in-process counter applied via `Depends(rate_limit(...))`
  on register/login/refresh/tutor-question. **Documented limitation**:
  process-local only, not distributed - restarting the process or
  running more than one API replica resets/fragments the counters. A
  future phase would swap in a Redis-backed implementation behind the
  same `RateLimiterPort` Protocol without touching any route.
- **Ownership enforcement**: routes never trust a `learner_id` from the
  request body/path when the principal already implies one
  (`/learners/me/*`, `require_learner_identity`). ID-addressed resources
  (sessions, decisions, submissions, portfolios, conversations) are
  ownership-checked via `ensure_owned_by_learner`, which raises the
  resource's own **404** (not 403) on mismatch so a non-owner can never
  confirm another learner's resource exists; ADMIN bypasses ownership.
- **Security headers**: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` on every
  response; `Cache-Control: no-store` on every `/api/*` response.

### Endpoints (68 total, all under `/api/v1` unless noted)

- **Authentication** (`/auth`): `POST /register`, `POST /login`,
  `POST /refresh`, `POST /logout`, `POST /logout-all`, `GET /me`.
- **Learners** (`/learners/me*`): profile get/patch, dashboard, paginated
  mastery/progress/misconceptions.
- **Curriculum**: learner-safe browsing of paths/modules/lessons/
  exercises (never `is_correct`/`feedback` pre-submission), plus the
  caller's own exercise attempts/answers.
- **Adaptive learning** (`/adaptive`): sessions, recommendations,
  decision accept/start/skip/answer, diagnostics - a thin wrapper over
  `AdaptiveLearningService`/`AdaptiveLearningOrchestrator`; grading
  always flows through the same `LearningService.submit_answer` the
  curriculum router uses.
- **Historical scenarios** (`/scenarios`): catalog, learner-safe
  point-in-time view, start/submit/reveal - built only from
  `LearnerScenarioView`/`ScenarioReveal`, so a future bar or rubric
  score structurally cannot leak before reveal.
- **Virtual portfolios** (`/portfolios`): creation, trade preview,
  trade execution (**requires an `Idempotency-Key` header** - FastAPI's
  own required-header validation returns 422 if omitted; replaying the
  same key returns the original transaction, never a duplicate),
  holdings, transactions, decision journal, valuation, performance.
- **AI tutor** (`/tutor/conversations`): all 6 `TutorContextType`
  values, dispatched to `GroundedAITutorService` directly (
  `GENERAL_EDUCATION`) or via `LessonTutorService`/`ScenarioTutorService`/
  `PortfolioTutorService` (which recompute fresh structured context per
  question); question submission is rate-limited; citations never carry
  a chunk ID, embedding vector, or raw prompt text.
- **Administration** (`/admin`, role-gated): account list/get/disable/
  enable/revoke-sessions (ADMIN only); curriculum authoring - skills,
  paths, modules, lessons, exercises+options, including `is_correct`/
  `feedback` (CONTENT_EDITOR or ADMIN only - the one place in the API
  authorized to see the answer key); knowledge-base ingest-curriculum,
  bounded (20 MB, `.md`/`.txt`/`.pdf`/`.docx` only) local-document
  upload with guaranteed temp-file cleanup, document/ingestion-run
  listing.

### Database

Migration `0007_product_api_auth` (on top of `0006_grounded_ai_tutor`)
adds three tables: `user_accounts`, `account_refresh_tokens` (indexed
on `token_hash` and `token_family_id` for the CAS rotation and
family-revocation queries), and `authentication_audit_events`. Verified
idempotent (`alembic upgrade head` twice against the test database is a
no-op the second time).

### CLI: `identity_admin`

```powershell
# Create the first ADMIN account (prompts for a password via getpass - never a CLI argument)
python -m stock_research_core.cli.identity_admin --create-admin --email admin@example.com --display-name "Admin"

# List / filter accounts
python -m stock_research_core.cli.identity_admin --list-accounts --role ADMIN --status ACTIVE

# Disable an account / revoke every active session
python -m stock_research_core.cli.identity_admin --disable-account --email someone@example.com
python -m stock_research_core.cli.identity_admin --revoke-sessions --email someone@example.com
```

### Docker

`Dockerfile` (python:3.12-slim, non-root `finquest` user, `HEALTHCHECK`
against `/health`) plus a `finquest-api` service in `docker-compose.yml`
(depends on `stock-db` via `condition: service_healthy`, in-network
`DATABASE_URL` pointing at `stock-db:5432`, requires `AUTH_JWT_SECRET`
to be set in the environment - `docker compose` refuses to start
without it). Migrations are **not** run automatically by the container:

```powershell
$env:AUTH_JWT_SECRET = "<a long random secret>"
docker compose up -d --build
docker compose exec finquest-api python -m alembic upgrade head
```

### Tests

- **`tests/unit/`**: `test_identity_domain.py`, `test_identity_security.py`,
  `test_argon2_password_hasher.py`, `test_jwt_access_token_service.py`,
  `test_opaque_refresh_token_service.py`, `test_identity_service.py`
  (register/login/refresh/logout/logout-all/get_principal against fake
  repositories - lockout, generic-login-error, and rotated-token-reuse
  behavior all covered), `test_api_authorization.py` (role hierarchy,
  `ensure_owned_by_learner`), `test_api_middleware.py` (correlation ID,
  security headers, `Authorization` header never logged),
  `test_api_exception_handlers.py` (every `StockResearchError` subclass
  resolves to a mapped status, unhandled exceptions degrade safely),
  `test_identity_architecture.py` (AST-based import-boundary checks:
  no FastAPI/SQLAlchemy/PyJWT/pwdlib in `domain`/`application`, routers
  never import the ORM or SQLAlchemy directly except the documented
  `/ready` exception), `test_openapi_snapshot.py` (structural - tags,
  path list, security-scheme names).
- **`tests/integration/`** (real `stock_research_test` database, driven
  entirely over HTTP via `httpx.ASGITransport`): `test_auth_api.py`,
  `test_learners_api.py`, `test_curriculum_api.py`,
  `test_adaptive_learning_api.py`, `test_market_scenarios_api.py`,
  `test_virtual_portfolios_api.py`, `test_ai_tutor_api.py`,
  `test_admin_api.py`, `test_health_api.py` - full lifecycle flows,
  ownership-enforcement (404 for non-owners), and role-gating (403) for
  every router.

### Current limitations

- No OAuth/social login, email verification/delivery, multi-tenant
  organizations, or account-to-multiple-learner linking - one account
  optionally links to exactly one learner.
- Rate limiting is process-local (see above) - not safe for a
  multi-replica deployment without a shared backing store.
- No API gateway, Kubernetes/ECS manifests, or Redis - `docker-compose.yml`
  covers local/single-host deployment only.

## Phase 10: stabilization and the FinQuest learner web application

Two independent efforts: (1) three targeted backend bug fixes plus two
small additive read endpoints the frontend needed, and (2) a complete
Next.js learner-facing web application (`frontend/`) - login/register,
dashboard, curriculum browsing and exercises (all 7 types), adaptive
daily practice, diagnostic assessment, historical scenarios (with a
strict future-data safety boundary), virtual portfolios (with
idempotent trade execution), a grounded AI tutor with citations, and
settings. No Phase 1-9 backend capability was removed, weakened, or
duplicated - the frontend is a thin, typed client over the existing
API, and the two new endpoints are additive, ownership-checked,
learner-safe reads that reuse existing repository methods and mappers.

### Stabilization fixes

1. **Knowledge-ingestion duplicate content** - `knowledge_documents`
   previously had a single global `UniqueConstraint` on
   `(content_hash, document_version)`, so identical text used in two
   different lesson/exercise/scenario contexts collided and the second
   ingestion silently failed. Fixed by widening the constraint to
   `(content_hash, document_version, source_id, lesson_id, exercise_id,
   scenario_id, portfolio_context_code)` with
   `postgresql_nulls_not_distinct=True` (migration
   `0008_kb_doc_context_uniqueness`), so two documents that are
   identical in every column (including NULL curriculum-context
   columns) still collide as true duplicates, but identical text
   attached to *different* lesson/exercise/scenario contexts is treated
   as distinct content and ingested independently. Content-hash
   deduplication and versioning are otherwise unchanged.
2. **Portfolio performance with fewer than two valuations** -
   `calculate_performance` previously raised a generic `ValueError`
   when zero valuation snapshots existed in the requested window,
   producing a raw 500. Added `InsufficientPortfolioValuationDataError`
   (raised whenever fewer than two snapshots fall in the window - the
   minimum needed to compute a return), mapped by
   `api/exception_handlers.py` to `422
   INSUFFICIENT_PORTFOLIO_VALUATION_DATA` with the message "At least
   two portfolio valuations are required to calculate performance." -
   never a stack trace.
3. **Flaky spaced-repetition test** -
   `DeterministicReviewSchedulingPolicy.update_schedule`'s
   "first review" branch omitted `created_at` on the new
   `SkillReviewSchedule`, so it fell back to the model's
   `default_factory=utc_now` - real wall-clock time instead of the
   policy's injected `practiced_at`. Fixed by passing
   `created_at=practiced_at` explicitly; the test now passes
   deterministically under `pytest --count=50` (added `pytest-repeat` as
   a dev dependency) with no loosened tolerances.

### Two new additive endpoints

The frontend's diagnostic-assessment and virtual-portfolio flows need
reads the Phase 9 API surface didn't expose:

- **`GET /api/v1/exercises/{exercise_id}`** - a diagnostic item only
  carries an `exercise_id` (not a `lesson_id`), so there was no way to
  fetch its prompt/options via the existing lesson-scoped
  `/lessons/{id}/exercises` route. Mirrors that route's mapping
  exactly (`ExerciseResponse.from_domain`, same learner-safe
  guarantees - no `is_correct`/`feedback`), just addressed by exercise
  ID directly.
- **`GET /api/v1/portfolios/securities/{security_id}`** - holdings,
  transactions, and position valuations only carry a `security_id`
  (UUID), not a ticker, so the frontend had no way to display a
  human-readable symbol. Reuses the same `SecurityResponse` schema
  already used by the scenario endpoints and `uow.securities.get_by_id`.

Both are learner-authenticated, read-only, added to the OpenAPI
structural snapshot test (`test_openapi_snapshot.py`), and covered by
new integration tests in `test_curriculum_api.py` /
`test_virtual_portfolios_api.py` (including the 404 case).

### Backend regression

All pre-existing tests plus every new stabilization/endpoint test pass
together - see "Validation commands" below for the exact commands and
counts.

### Frontend architecture (`frontend/`)

Next.js 15 App Router, React 19, TypeScript (`strict`,
`noUncheckedIndexedAccess`), Tailwind CSS v3, TanStack Query v5, React
Hook Form + Zod, Recharts, Vitest + Testing Library + MSW + jest-axe,
Playwright. No `any` as an escape hatch (enforced by
`@typescript-eslint/no-explicit-any: error`); no state-management
library beyond TanStack Query + a small module-level token store.

```
frontend/
├── app/
│   ├── (auth)/{login,register}/page.tsx      # public, redirect-if-authenticated layout
│   ├── (protected)/                          # dashboard/learn/practice/diagnostic/
│   │                                          # scenarios/portfolios/tutor/settings
│   ├── api/auth/{login,register,session,refresh,logout}/route.ts
│   └── healthz/route.ts                      # never calls the backend
├── components/{ui,layout,auth,dashboard,learning,exercises,adaptive,
│               scenarios,portfolios,tutor}/
├── lib/{api,auth,validation,formatting,accessibility}/
├── providers/{AuthProvider,QueryProvider,AppProviders}.tsx
├── hooks/                                     # one file per feature area
├── types/{generated-api.ts,api-schemas.ts,api-error.ts,session.ts}
├── middleware.ts                              # navigation-level route gating only
├── tests/{unit,component,integration,accessibility}/
├── e2e/                                       # 7 Playwright journeys + fixtures + global-setup
├── scripts/check-openapi-fresh.mjs
└── Dockerfile
```

### API contract generation

`scripts/export_openapi.py` (backend) builds `create_app(testing=True)`
and writes a deterministic (`sort_keys=True`) JSON snapshot to
`frontend/openapi/finquest-api.json`. `openapi-typescript` generates
`frontend/types/generated-api.ts` from that file - **never hand-edited**.
`npm run api:check` (`scripts/check-openapi-fresh.mjs`) regenerates
into a temp file and diffs it against the committed one, so CI catches
drift between the backend's OpenAPI schema and the checked-in types.
`types/api-schemas.ts` re-exports the specific schema names actually
used (never a hand-written duplicate shape); `types/api-error.ts`
hand-declares the error envelope, since it's never used as a
`response_model=` and therefore never appears in the generated schema.
The generated types structurally exclude `password_hash`,
`token_hash`, every exercise/scenario `is_correct`/`feedback`/rubric
field, and raw embedding vectors/chunk IDs - because the backend's DTOs
never serialize them, not because of any frontend filtering.

```powershell
# From the repository root, backend venv active:
python scripts/export_openapi.py
cd frontend
npm run api:generate
npm run api:check   # fails if the committed types are stale
```

### Authentication architecture

- **Refresh token**: HttpOnly cookie (`lib/auth/cookies.ts`,
  `Secure` when `AUTH_COOKIE_SECURE=true`, `SameSite=Strict`, `Path=/`,
  bounded `Max-Age`), set only by the Next.js Route Handlers
  (`app/api/auth/{login,register,session}/route.ts`) after a
  server-side call to the FastAPI backend - **never** readable by
  browser JavaScript, and never returned in a JSON body.
- **Access token**: held only in a module-level variable
  (`lib/auth/token-store.ts`) - never `localStorage`/`sessionStorage`/
  `IndexedDB`/a JS-readable cookie. `lib/api/client.ts` (a plain
  module, not a hook) reads/writes it directly so it can attach the
  bearer token to every request; `AuthProvider` subscribes via
  `useSyncExternalStore` to reflect the same value reactively.
  Confirmed by a dedicated unit test
  (`tests/unit/token-store.test.ts`) that nothing is ever written to
  Web Storage.
- **Single-flight refresh + retry-once**: `lib/api/client.ts` holds one
  module-level `Promise | null` shared by every caller in the tab.
  Every 401 awaits that *same* promise (never starts a second
  `/api/auth/refresh` call); the original request is retried at most
  once; a failed refresh clears the in-memory session instead of
  looping. Verified against a real mocked `fetch` in
  `tests/unit/api-client-refresh.test.ts` (three tests: successful
  refresh-then-retry, concurrent-401 single-flight, failed-refresh
  clears session with no loop).
- **CSRF/origin protection**: the cookie-setting Route Handlers
  validate `Origin`/`Host` before processing a mutation
  (`lib/auth/origin.ts`), on top of `SameSite=Strict` - no auth Route
  Handler ever accepts a refresh token from a request body.
- **Route protection**: `middleware.ts` checks for the *presence* of
  the refresh cookie (never its validity - it's HttpOnly/opaque) to
  redirect unauthenticated visitors to `/login?returnTo=<path>` and
  authenticated visitors away from `/login`/`/register`; this is
  explicitly a UX optimization, not the authorization boundary - FastAPI
  independently authorizes every `/api/v1/*` call regardless. `returnTo`
  is sanitized (`lib/auth/return-path.ts`, shared by both `middleware.ts`
  and the `(auth)` layout) to reject protocol-relative and absolute
  URLs, closing the open-redirect vector - covered by 7 unit tests plus
  a dedicated E2E test.
- **Logout**: always clears the in-memory token and the entire
  TanStack Query cache client-side, even if the backend logout call
  itself fails - verified in `tests/component/AuthProvider.test.tsx`.

### Every page and flow

- **Login / register** (`components/auth/{LoginForm,RegisterForm}.tsx`,
  React Hook Form + Zod): client-side password-policy mirror (never the
  sole enforcement - the backend re-validates independently), generic
  "incorrect email or password" messaging (no account enumeration),
  password show/hide toggle, password field cleared on a failed
  attempt.
- **Dashboard** (`/dashboard`): `GET /learners/me/dashboard` +
  `/learners/me/mastery` only - completed/total lessons, active
  misconceptions, skill mastery list. No fabricated progress, streak,
  or XP is ever displayed (the backend's `total_xp`/
  `current_streak_days` fields exist but are deliberately never
  rendered).
- **Curriculum** (`/learn`, `/learn/[pathId]`, `/lessons/[lessonId]`):
  paths → modules → lessons → exercises, safe Markdown rendering
  (`components/learning/LessonMarkdown.tsx` - `react-markdown` with no
  `rehype-raw`, so embedded HTML/`<script>` renders as inert literal
  text; markdown headings are demoted one level so lesson/tutor content
  never introduces a second page `<h1>`).
- **Exercise renderer** (`components/exercises/`): all 7
  `ExerciseType`s - `SingleSelectInput` (SINGLE_CHOICE/TRUE_FALSE/
  SCENARIO_DECISION), `MultipleChoiceInput` (never reveals the expected
  selection count), `NumericAnswerInput`, `OrderingInput` (keyboard
  "Move up"/"Move down" buttons - never drag-and-drop-only),
  `TextResponseInput`. Submission always goes through
  `POST /exercises/{id}/attempts` + `POST /attempts/{id}/answers`;
  `ExerciseResult` renders only backend-provided
  score/correctness/mastery/progress, never recomputes grading.
  `hooks/useExerciseDraft.ts` centralizes draft-state/payload-building/
  completeness logic, shared by the curriculum player, adaptive
  practice, and the diagnostic flow (never duplicated three times).
- **Adaptive practice** (`/practice`): an explicit state machine - start
  session → request recommendation → accept → start → submit or skip →
  request next → complete. Handles `SESSION_COMPLETE`/
  `NO_ELIGIBLE_CONTENT` as terminal, backend-driven outcomes;
  `components/adaptive/RecommendationCard.tsx` translates
  `RecommendationType`/`RecommendationReason` into learner-friendly
  text (a fixed lookup table, never invented). Priority, difficulty,
  and review scheduling are never computed client-side.
- **Diagnostic** (`/diagnostic`): backend selects every item up front;
  the client walks the returned item list, starts/submits each
  attempt, and displays the final skill-readiness grouping
  (`DiagnosticResultSummary`) - grouped by backend-returned
  `DiagnosticSkillResult` level, since the API has no learner-facing
  skill-name endpoint. No score is ever computed client-side.
- **Historical scenarios** (`/scenarios`, `/scenarios/[scenarioId]`):
  the pre-decision view (`LearnerScenarioResponse`) is structurally
  incapable of carrying future data (built server-side from a
  point-in-time-safe domain view). The reveal endpoint
  (`ScenarioRevealResponse` - future charts, realized outcome) is
  fetched *only* when the learner explicitly clicks "Reveal what
  happened," never speculatively, and `reveal_status` gates whether
  that button even renders. `RevealPanel` displays the required
  "mastery is based on decision quality, not market luck" framing.
  Verified end-to-end by `e2e/historical-scenario.spec.ts`, which
  asserts no outcome-direction/return text exists anywhere on the page
  before that click.
- **Virtual portfolios** (`/portfolios`, `/new`, `/[id]`, `/trade`,
  `/journal`): trade execution always goes through a required preview
  step; `hooks/useIdempotencyKey.ts` derives a stable UUID from a
  fingerprint of the trade's meaningful fields (ticker/type/quantity/
  timestamp) and only mints a new key when one of those actually
  changes, so retrying the *same* submission reuses the *same*
  `Idempotency-Key` header. Verified against the real backend in
  `e2e/virtual-portfolio.spec.ts`, which captures the UI's actual
  request, replays it byte-for-byte, and asserts the transaction count
  doesn't increase. The standalone decision-journal page restricts its
  action selector to `HOLD`/`REBALANCE`/`RESEARCH_MORE` (a `BUY`/`SELL`
  journal entry is only ever recorded alongside an actual trade).
  `TickerLabel` resolves `security_id` → ticker via the new
  `/portfolios/securities/{id}` endpoint.
- **Grounded tutor** (`/tutor`, `/tutor/[conversationId]`): supports
  all 6 `TutorContextType` values via `AskTutorButton` entry points
  wired into the lesson page (`LESSON_HELP`), the exercise player
  (`EXERCISE_HELP`), the scenario page before and after reveal
  (`SCENARIO_BEFORE_DECISION`/`SCENARIO_AFTER_REVEAL`), the portfolio
  page (`PORTFOLIO_EXPLANATION`), and a general-question starter on
  `/tutor` itself. `components/tutor/CitationList.tsx` renders only
  the learner-safe citation fields the backend provides (number,
  document/source title, heading path, excerpt) with expand/collapse -
  a chunk ID or embedding vector cannot appear because
  `CitationResponse` never carries one. `ContextSafetyBanner` sets
  explicit expectations for the scenario-before and portfolio contexts.
  Historical messages (`TutorMessageResponse`) don't carry citations at
  all (a backend-schema constraint) - only the just-answered question's
  citations are shown, never invented for older turns.
- **Settings** (`/settings`): only display name, preferred language,
  and daily goal are editable (`LearnerUpdateRequest` structurally
  excludes anything else); email and role are read-only. Logout and
  "log out of all devices" (`revoked_session_count` shown from the
  backend's own response).

### Loading, error, and empty states

Every data-fetching page distinguishes initial loading
(`LoadingSkeletonCard`), an empty result (`EmptyState`), and a failed
request (`ErrorState`) - the latter renders the backend's own safe
message, a "Reference: `<correlation-id>`" line when present, and a
retry action, **never** a stack trace or raw error object
(`lib/api/error.ts`'s `FinQuestApiError` structurally excludes both).
401 triggers the single-flight-refresh-then-retry flow before any
error is ever shown to the learner.

### Accessibility and responsiveness

Semantic landmarks (`<nav>`/`<main>`, a "Skip to main content" link),
exactly one `<h1>` per page (enforced by demoting in-content Markdown
headings), visible focus rings, labeled form fields with
`aria-describedby`-linked errors, `role="alert"`/`role="status"` used
correctly, status never conveyed by color alone (`Badge` always pairs a
tone with a text label), screen-reader announcements for grading
results (`lib/accessibility/gradingAnnouncement`), textual chart
summaries alongside every Recharts chart (`PriceChart`'s `sr-only`
paragraph), ordering exercises operable via buttons (never
drag-and-drop-only). Desktop: left nav rail + main + optional right
panel; mobile: compact top bar + bottom nav, no horizontal overflow.
`jest-axe` asserts zero violations on the 9 non-dynamic-route pages
(`tests/accessibility/pages.test.tsx`); the dynamic detail pages are
covered by the Playwright journeys against real rendered markup.

### Security

No refresh token ever reaches browser JavaScript; no access token in
persistent storage (enforced by a dedicated test); no `NEXT_PUBLIC_`
secret; no `rehype-raw`/`dangerouslySetInnerHTML` anywhere; `returnTo`
open-redirect rejection (unit + E2E covered); Origin-validated
cookie-setting routes; no credential/token/full-tutor-content/
journal-rationale logging in `lib/api/client.ts`; `rel="noopener
noreferrer"` on external links; the frontend never assumes its own
authorization decisions are authoritative (FastAPI is always the real
boundary); Query cache and in-memory token both cleared on logout.

### Environment configuration (`frontend/.env.example`)

`NEXT_PUBLIC_FINQUEST_API_BASE_URL`/`NEXT_PUBLIC_APP_NAME` (browser-safe,
validated eagerly via `lib/environment.ts`'s `browserEnv` - fails fast
with every missing/invalid variable listed) and
`FINQUEST_API_INTERNAL_URL`/`FINQUEST_WEB_ORIGIN`/`AUTH_COOKIE_SECURE`
(server-only, validated lazily via `getServerEnv()` inside Route
Handlers/`middleware.ts` - never importable from a Client Component).
`apiInternalBaseUrl()` prefers the internal (in-Docker-network) URL,
falling back to the public one for local dev without Docker.

### Testing

- **`tests/unit/`** (10 files, 78 tests): login/register validation +
  password confirmation, API error parsing + correlation-ID
  extraction, single-flight refresh/retry-once/failed-refresh-clears-
  session (against a real mocked `fetch`), safe `returnTo` sanitization,
  pagination helpers, date/currency/percentage/relative-time
  formatting + locale-safe numeric parsing, exercise-answer
  serialization (all 7 types, never leaks `is_correct`), idempotency-
  key fingerprint/preservation, environment validation (missing/
  invalid/defaulted), no-persistent-token-storage.
- **`tests/component/`** (15 files, ~48 tests): all 5 distinct exercise
  input components, `ErrorState`/`EmptyState`/`Alert`/`Badge`/
  `ProgressBar`, `PasswordField` show/hide + `aria-describedby`,
  `LoginForm`/`RegisterForm` (validation, submission, safe-error-
  display), `DecisionForm`, `CitationList` (expand/collapse, no chunk
  ID), `PriceChart` (textual summary, empty-data fallback),
  `RevealPanel` (renders only passed-in fields, no independent
  fetching), `AuthProvider` (logout clears cache even on backend
  failure), `AskTutorButton`, `TickerLabel`, `RecommendationCard`,
  `SessionSummaryCard`, `DiagnosticResultSummary`.
- **`tests/integration/`** (8 files, ~19 tests, MSW-mocked HTTP):
  dashboard load + pagination envelope parsing + typed-error
  propagation, curriculum browse/attempt/submit chain, adaptive
  session/recommendation flow (including `SESSION_COMPLETE`), scenario
  future-data-safety (structural absence of future fields pre-reveal;
  reveal never triggered by any other mutation), portfolio
  list/preview/execute with an asserted `Idempotency-Key` header,
  diagnostic start/submit, tutor conversation/citation/guardrail-
  refusal handling, settings update (exact allowed-field set).
- **`tests/accessibility/`** (1 file, 9 tests): `jest-axe`, zero
  serious/critical violations on `/login`, `/register`, `/dashboard`,
  `/learn`, `/practice`, `/scenarios`, `/portfolios`, `/tutor`,
  `/settings`.
- **`e2e/`** (7 spec files, 12 tests, Playwright against the REAL
  Next.js + FastAPI + PostgreSQL stack - nothing mocked):
  `registration-curriculum.spec.ts`, `adaptive-practice.spec.ts`,
  `diagnostic.spec.ts`, `historical-scenario.spec.ts` (explicitly
  asserts no future/outcome text exists pre-reveal and does exist
  post-reveal), `virtual-portfolio.spec.ts` (replays the UI's actual
  captured trade request with the same `Idempotency-Key` and asserts
  exactly one transaction), `tutor.spec.ts` (2 tests: grounded citation
  answer, and a deterministic guardrail refusal for a
  personalized-advice question), `auth-lifecycle.spec.ts` (5 tests:
  protected-route bounce + `returnTo`, already-authenticated
  `/login` redirect, logout, open-redirect rejection). `e2e/fixtures.ts`
  registers a fresh, collision-free learner per test through the real
  registration flow (never seeded directly). `e2e/global-setup.ts`
  deterministically seeds curriculum, adaptive profiles, synthetic
  (network-free) market data for two fixture tickers, historical
  scenarios, and the knowledge base before every run - idempotent, so
  re-running it is always safe.

  Real 15-minute access-token expiry is not waited out in `e2e/` (not
  practical for a CI run); the refresh contract itself is covered
  directly against a real `fetch` in `tests/unit/api-client-refresh.test.ts`.

### Docker

`frontend/Dockerfile`: three stages (`deps` → deterministic `npm ci`;
`builder` → `npm run build` with `NEXT_PUBLIC_*` passed as build args,
since they're baked into the client bundle; `runner` → Next.js
`output: "standalone"` bundle only, non-root `finquest` user, no
secret ever baked in, `HEALTHCHECK` against `/healthz` which never
calls the backend). `docker-compose.yml` adds `finquest-web`,
depending on `finquest-api` via `condition: service_healthy`
(`stock-db` → `finquest-api` → `finquest-web`); `finquest-api`'s
`API_CORS_ORIGINS` is driven by the same `FINQUEST_WEB_ORIGIN` value
the frontend uses - CORS is never a wildcard with credentials
(`CORSMiddleware`'s `allow_credentials` is `False` whenever `"*"` is in
the origin list, in `api/app_factory.py`). `EMBEDDING_PROVIDER`
defaults to `deterministic_fake` for this image (it does not install
the optional `ai_tutor`/`sentence-transformers` extra) - a deployment
wanting real semantic embeddings should rebuild with
`pip install ".[ai_tutor]"` and override it to `sentence_transformer`.

```powershell
$env:AUTH_JWT_SECRET = "<a long random secret>"
docker compose up -d --build stock-db finquest-api finquest-web
docker compose exec finquest-api python -m alembic upgrade head
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:3000/healthz
```

### Validation commands

Backend (from the repository root, venv active):

```powershell
python -m pytest -q
python -m pytest tests\unit\test_spaced_repetition_policy.py --count=50 -q
python -m alembic upgrade head
python -m alembic upgrade head   # confirm the second run is a no-op
python scripts\export_openapi.py
```

Phase 11 additionally requires `REDIS_URL` reachable for the Redis-
dependent integration tests (`test_job_concurrency.py`) - they skip,
never fail, when it is not:

```powershell
docker compose up -d redis
$env:REDIS_URL = "redis://localhost:6379/0"
python -m pytest tests\integration -m integration -q
python -m stock_research_core.cli.worker_status
```

Frontend (from `frontend/`):

```powershell
npm ci
npm run api:generate
npm run api:check
npm run lint
npm run typecheck
npm test
npm run test:a11y
npm run build
npx playwright install --with-deps chromium
npm run test:e2e   # requires the full stack already running - see Docker above
```

### Known limitations

- The Docker image's default `EMBEDDING_PROVIDER=deterministic_fake`
  trades semantic-search quality for a network-free, ML-dependency-free
  build - see "Docker" above for the real-embeddings rebuild path.
- Auth-endpoint rate limiting (`limit=10, window_seconds=60` on
  `/auth/register`, hardcoded in `api/routers/auth.py`, inherited
  unchanged from Phase 9) is keyed by the caller's IP as FastAPI sees
  it - since browser auth traffic is proxied server-side through the
  Next.js Route Handlers, every learner behind one Next.js instance
  shares that instance's rate-limit bucket. This is a pre-existing
  Phase 9 characteristic (already documented as process-local/
  single-replica-only), not something Phase 10 changed; a
  high-registration-volume deployment would need to either raise the
  limit or key it on a forwarded client IP.
- Real 15-minute access-token expiry/rotation is exercised by a real
  mocked `fetch` in the unit suite, not by waiting it out in `e2e/`.
- No admin UI is part of this learner-facing application (Phase 9's
  admin endpoints remain API-only); XP/streak fields exist in the
  dashboard response but are never rendered (no real backend-tracked
  streak/XP mechanic to display honestly yet); LangGraph is not
  connected to any part of this stack; the tutor never gives real
  investment advice (`EXACT_ADVICE_REFUSAL`, unchanged from Phase 8/9).
  (The auth-rate-limit proxy-identity limitation and "n8n not
  connected" limitation noted in earlier revisions of this section are
  resolved in Phase 11 below.)

## Phase 11: production operations, background jobs, observability, and n8n integration

Four things Phase 1-10 didn't have: a durable way to run long-running
work (market refresh across every tracked security, batch portfolio
valuation, knowledge-base maintenance, retrieval evaluation) without
blocking an API request; a way for those jobs to be triggered and
monitored by an external orchestrator (n8n) without ever handing that
orchestrator database credentials; structured, machine-parseable logs
and Prometheus metrics; and two closed Phase 10 stabilization items
(an accidental-production-fake-embeddings footgun, and a naive
`request.client.host` rate-limit/audit identity that trusted whatever
IP the immediate TCP peer happened to be). No Phase 1-10 capability was
removed, weakened, or duplicated - every job handler is a thin
orchestration wrapper around an *existing* application service.

### Why background jobs, and why PostgreSQL is the source of truth

```text
n8n  →  FastAPI Operations/Integration API  →  PostgreSQL (durable PENDING job)  →  Redis (delivery)  →  Celery worker  →  existing FinQuest service  →  PostgreSQL/TimescaleDB/pgvector
```

A `BackgroundJob` row is written and committed to PostgreSQL *before*
it is ever handed to Redis/Celery (`BackgroundJobService.create_job`,
`application/operations/service.py`). If Redis is unreachable at that
moment, the job durably persists as `FAILED` with a sanitized
`ENQUEUE_FAILED` result summary - it is never silently lost, and an
administrator can `--requeue-job` it once Redis recovers. Celery task
state (`AsyncResult`, the Redis result backend) is never treated as
the public job state; every status a caller (admin, n8n, the CLI) ever
sees is read straight from `background_jobs`/`background_job_attempts`/
`background_job_events`. A Celery task's payload is exactly one field,
`job_id` (JSON, never pickle) - workers always reload parameters fresh
from PostgreSQL, so nothing sensitive or stale ever rides on the
message bus, and replaying an old message is always safe.

### Queue and worker topology

| Queue | Job types | Concurrency | Why |
|---|---|---|---|
| `finquest.market` | `TRACKED_MARKET_REFRESH`, `SECURITY_MARKET_REFRESH` | 2 | I/O-bound against an external market-data provider - low, rate-sensitive |
| `finquest.portfolio` | `PORTFOLIO_VALUATION`, `PORTFOLIO_BATCH_VALUATION` | 4 | CPU-light (pandas over already-stored bars) |
| `finquest.knowledge` + `finquest.evaluation` | `CURRICULUM_KNOWLEDGE_REFRESH`, `LOCAL_DOCUMENT_INGESTION`, `KNOWLEDGE_REEMBED`, `KNOWLEDGE_GAP_SUMMARY`, `RETRIEVAL_EVALUATION` | 1 | Chunking/embeddings are CPU/RAM-intensive; the evaluation queue shares this worker rather than getting its own process (both are knowledge-base-adjacent and low-volume) |
| `finquest.default` | `SYSTEM_MAINTENANCE` | 2 | Operational housekeeping only |

Each queue maps to its own Docker Compose service
(`finquest-worker-market`/`-portfolio`/`-knowledge`/`-default`), all
built from the same application image (`target: base`, or `target: ai`
for the knowledge worker when real sentence-transformer embeddings are
wanted), running as the same non-root `finquest` user as the API.
`task_acks_late=True` + `task_reject_on_worker_lost=True` +
`worker_prefetch_multiplier=1`: a worker that dies mid-task never
silently drops it - Celery redelivers, and `BackgroundJobService.execute_job`
is safe against duplicate delivery (see below).

### Job lifecycle, idempotency, attempts, and events

`BackgroundJobStatus`: `PENDING → QUEUED → RUNNING → SUCCEEDED` (or
`FAILED`, or `RETRY_SCHEDULED → QUEUED` again, bounded by
`maximum_attempts`), or `CANCELLED`/`SKIPPED`. `BackgroundJobRegistry`
(`application/operations/job_registry.py`) is the single, validated map
from `BackgroundJobType` to its parameter model, queue, task name,
handler, retry policy, time limit, resource-key builder, and allowed
trigger sources - it fails at construction (not at first use) if any
job type is missing a handler, has an empty queue/task name, an invalid
`maximum_attempts`, or is registered twice. The exact same registry
(via `infrastructure/operations/registry_factory.py::build_operations_registry`)
is built by both the API process (`api/app_factory.py`) and every
worker process (`infrastructure/operations/celery_tasks.py`), so job-type
configuration never drifts between the two.

**Idempotency**: every job creation call supplies an `idempotency_key`;
the canonical scope is `(job_type, trigger_source, requester identity,
idempotency_key)`, enforced by a real PostgreSQL unique constraint
(`uq_background_jobs_idempotency_scope` on a computed `requester_key`
column - `account:{id}` / `integration:{id}` / `source:{trigger_source}` -
so two `SYSTEM`-triggered jobs with no requester also collide correctly
without relying on multi-column `NULL` semantics). A duplicate request
returns the *existing* job (`created: false`, `duplicate_of_job_id`
set) - it never creates a second job or double-enqueues.

**Duplicate delivery safety**: `execute_job` always calls
`get_for_update` (`SELECT ... FOR UPDATE`) first. An already-`SUCCEEDED`
job returns idempotently without re-running the handler; an
already-`RUNNING`/`CANCELLED`/`SKIPPED` job is skipped with a warning.
The row lock is held only for the brief state-transition burst (mark
`RUNNING`, create the attempt, commit) - never for the handler's entire
execution, so progress updates (each in their own short transaction,
`_RepositoryProgressReporter`) are visible to API/n8n pollers
immediately, not buffered behind a long-running commit.

**Attempts and events**: `background_job_attempts` records one row per
execution attempt (worker name, Celery task ID, sanitized error
type/code/message, retry delay - never a raw traceback or credential-
shaped string, enforced both at the domain-model layer and, redundantly,
at the repository write layer via `find_sensitive_keys`/`contains_traceback`).
`background_job_events` is an append-only, immutable
(Pydantic `frozen=True`) audit trail (`CREATED → QUEUED → STARTED →
PROGRESS_UPDATED* → SUCCEEDED|FAILED|RETRY_SCHEDULED|CANCELLED|SKIPPED|LOCK_NOT_ACQUIRED`),
ordered deterministically by `(created_at, event_id)` - since
PostgreSQL's `now()` is stable within one transaction, events committed
together may share a timestamp, so `event_id` is the documented,
deterministic tiebreaker, not insertion order.

### Retry policy

Three deterministic policy shapes (`application/operations/job_registry.py`),
never "retry everything":

- **`FixedScheduleRetryPolicy`** - market-provider transient failures
  (`ProviderRequestError`, `TransientInfrastructureError`): 4 attempts,
  delays `30s, 120s, 600s`. Also used for embedding-provider transient
  failures (`EmbeddingProviderError`): 3 attempts, `30s, 120s`.
- **`ExponentialBackoffRetryPolicy`** - generic infrastructure
  transience (`TransientInfrastructureError` alone, e.g. a lock/queue
  hiccup unrelated to a specific provider): 5 attempts, base 5s, capped
  at 120s, injectable (deterministic-by-default) jitter for tests.
- **`NeverRetryPolicy`** - `SYSTEM_MAINTENANCE` only.

Any exception *not* in a job type's `retryable_exceptions` tuple -
validation errors, `*NotFoundError`s, `InvalidJobParametersError` - is
never retried, classified non-retryable on the first attempt. A lock
that cannot be acquired (`LockAcquisitionError`) is retried on its own
fixed 15s delay, independent of the job type's registered policy, up to
`maximum_attempts`. `BackgroundJobService` re-enqueues a scheduled retry
itself (a fresh Celery message, `available_at` in the future) - Celery's
own `self.retry()` is never used, so PostgreSQL stays the sole authority
over whether/when a retry happens.

### Distributed locks

`RedisDistributedLock` (`infrastructure/operations/redis_lock.py`):
`SET key value NX PX` for acquisition (bounded poll-and-retry, never an
infinite spin), atomic Lua scripts for release (compare-and-delete) and
extend (compare-and-expire) keyed on a unique `owner_id` - a worker can
never release or extend a lock it does not currently hold, even after
its own TTL has expired and a different owner has since acquired the
same key. Resource keys are deterministic per job type
(`application/operations/locking.py`):
`market-security:{security_id}:{source}:{interval}`,
`portfolio-valuation:{portfolio_id}:{as_of}`,
`knowledge-curriculum-refresh`,
`knowledge-document-reembed:{document_id}`,
`retrieval-evaluation:{dataset}:{top_k}`. `CRITICAL` priority never
bypasses locking or authorization - priority only affects queue
ordering.

### Structured logging and metrics

`structlog` (`infrastructure/operations/structured_logging.py`):
JSON-per-line in production, human-readable console in development,
configured once at process startup (API `lifespan`, or a worker's
`worker_process_init` signal - never at import time). Every log record
- both new `structlog` call sites and the existing stdlib
`logging.getLogger(...)` call sites elsewhere in the codebase (request
logging, exception handlers) - passes through the same recursive
redaction filter (`domain/operations/sanitization.py::redact`, shared
with the domain-model validators, so "sensitive" is defined exactly
once) before it is ever rendered: known-sensitive key names are
replaced with `***REDACTED***`, and credential-shaped string *values*
(a JWT-shaped token, a `user:pass@host` URL, a raw `Authorization:
Bearer` header) are redacted even under an innocuous-looking key.
Tutor message content, journal rationale, and full document text are
never logged by any Phase 11 code path.

`prometheus-client` (`infrastructure/operations/metrics.py`), exposed
at unversioned `GET /metrics` (excluded from the OpenAPI schema; gated
by `METRICS_ENABLED`, optionally `METRICS_REQUIRE_AUTH=true` for
ADMIN-only scraping - the documented alternative to restricting it at
the network layer). Every label set is small and fixed - HTTP metrics
label by method + normalized *route template* (never a raw path
containing an ID) + status class; job metrics label by job type/queue/
status - never a job ID, learner ID, ticker, portfolio ID, or
correlation ID, so cardinality stays bounded regardless of traffic
volume. The application layer depends only on `MetricsPort`
(`NoOpMetrics` when `METRICS_ENABLED=false`), never `prometheus_client`
directly.

### Optional OpenTelemetry tracing

`OTEL_ENABLED=false` by default: `NoOpTracing` is used, no collector is
required, nothing errors. When enabled and the optional
`opentelemetry-*` dependencies (`pip install ".[otel]"`) aren't
installed, `build_tracing` logs one warning and falls back to the
no-op tracer rather than crashing the process - tracing is always
best-effort. When enabled *and* available, spans wrap job creation and
execution (`job.execute`) with only bounded, low-cardinality,
non-sensitive attributes (`_sanitize_attributes` - never raw question
text or document content).

### Production embedding-provider safety (closes a Phase 10 limitation)

`FINQUEST_ENV` (`test`/`development`/`production`,
`infrastructure/operations/config.py::FinquestEnv`):
`deterministic_fake` is always allowed in `test`, allowed with a
readiness warning in `development`, and **refused at API/worker
startup** in `production` (`assert_embedding_provider_production_safe`,
raising `UnsafeEmbeddingProviderConfigurationError`) unless
`ALLOW_FAKE_EMBEDDINGS_IN_PRODUCTION=true` is explicitly, deliberately
set (default `false`). `GET /ready` reports the configured provider,
whether it's production-approved, and whether it's initializable (a
bounded, network-free package-importability check for
`sentence_transformer` - **never** a model download; `/health` never
touches this at all). The Dockerfile gained an `ai` build target
(`docker compose build --build-arg` / the `KNOWLEDGE_WORKER_TARGET` compose
variable) that additionally installs the `ai_tutor` extra
(`sentence-transformers`) - the default `base` target (API, and every
worker except knowledge-by-default) stays small and network-free,
exactly as Phase 10 already documented; only a deployment that actually
wants real semantic embeddings needs to opt into the larger image.

### Trusted-proxy-aware client identity (closes a Phase 10 limitation)

Phase 10 documented that browser auth traffic, proxied server-side
through `finquest-web`, meant FastAPI saw the Next.js container's IP
for every learner - a single shared rate-limit bucket. Fixed by
`infrastructure/identity/client_identity.py::resolve_client_ip`:
`X-Forwarded-For` is ignored unless *both* `TRUST_FORWARDED_HEADERS=true`
**and** the immediate TCP peer (`request.client.host`) itself falls
inside a configured `TRUSTED_PROXY_CIDRS` network. Even then, only the
boundary of the trusted-proxy chain is trusted: walking the forwarding
chain from the nearest hop backward, the first hop that is *not* itself
a trusted proxy is the resolved client - never an arbitrary
client-supplied leftmost value. Malformed IPs, an excessively long
header (>1000 chars), or more than 20 hops all fall back safely to the
TCP peer address rather than raising. `docker-compose.yml` runs every
service on a dedicated `finquest-net` bridge network with a fixed
`172.28.0.0/24` subnet - `finquest-api`'s `TRUSTED_PROXY_CIDRS` is
scoped to exactly that subnet, never a broad RFC1918 range and never
`0.0.0.0/0`. The resolved identity feeds both `rate_limit()`
(`api/dependencies.py`) and authentication-audit hashing
(`get_client_ip_hash`) - the raw IP itself is never persisted, only its
SHA-256 hash, unchanged from Phase 9.

### n8n integration: authentication and replay protection

n8n authenticates via `X-FinQuest-Key-Id` + `X-FinQuest-Integration-Key`
headers (`api/integration_dependencies.py::get_integration_principal`)
- never a learner JWT, and the raw key is never logged (only its
SHA-256 hash is stored, generated once by
`cli/operations_admin.py --create-integration-client` and shown exactly
once). Verification is constant-time (`hmac.compare_digest`); every
failure mode - missing headers, unknown key ID, wrong key, `DISABLED`/
`REVOKED` status - returns the same generic 401, never revealing which
case occurred. An `IntegrationClient`'s `allowed_job_types` is an
explicit allow-list checked on every job-trigger request
(`JobTypeNotAllowedError` → `422` if violated).

Every job-trigger request also carries `X-FinQuest-Request-ID` (unique
per logical attempt) and `Idempotency-Key`. `integration_requests`
(unique on `(integration_id, external_request_id)`) provides replay
protection independent of, and layered on top of, the job-level
idempotency scope: replaying the same request ID with the *same*
request-body hash (SHA-256 over `{job_type, parameters}`, canonical
JSON) returns the original canonical job; replaying it with a
*different* body returns `409 REQUEST_CONFLICT`
(`IntegrationRequestConflictError`) rather than silently creating a
different job under the same request ID. `GET /api/v1/integrations/n8n/jobs/{id}`
and `.../events` are ownership-scoped - an integration client can only
ever see jobs it created (a non-owner gets the same generic `404` a
missing job would, never a `403` that would confirm the job exists).
`GET /api/v1/integrations/n8n/ready` is an integration-safe summary
(database/Redis connectivity, migration presence) - never a database
URL, Redis URL, secret, traceback, or learner data.

### n8n workflows (`n8n/`)

Five importable workflow JSON files (`n8n/workflows/`), each following
the same shape for the four job-triggering ones (schedule/manual
trigger → build idempotency key + external request ID → `POST .../jobs`
→ bounded poll loop, 15s × up to 40 attempts = a 10-minute ceiling →
branch on `SUCCEEDED`/`FAILED`/`CANCELLED`/`SKIPPED`/timeout → a
structured summary → a documented no-op placeholder for a future
notification integration, not implemented in this phase) plus an
hourly `system-readiness-watch.json` that just calls the integration
`/ready` endpoint (no polling loop needed - readiness is synchronous).
No workflow ever contains a database/Redis node or an embedded
credential (validated by `tests/integration/test_n8n_workflow_contracts.py`,
which additionally imports each file into a local n8n instance when one
is reachable - skipped, never failed, when it isn't).
`n8n/credentials.example.md` walks through creating an integration
client and the matching n8n credential with no real secrets committed
anywhere. `n8n/examples/trigger-job.{ps1,sh}` exercise the exact same
HTTP contract n8n uses, for testing without n8n running at all.

### Operational CLIs

`cli/operations_admin.py` (composition root, matching every other CLI's
argparse/async/explicit-engine-disposal shape):
`--create-integration-client`/`--list-integration-clients`/
`--revoke-integration-client`, `--create-job` (reads a JSON parameters
file - never an arbitrary Python expression)/`--job-status`/
`--requeue-job`. `cli/worker_status.py` is a bounded health/readiness
check (PostgreSQL, Redis, the Celery broker, the job registry, the
required queues, embedding-provider configuration - never an expensive
job, never a model download) suitable for a Docker `HEALTHCHECK`; every
worker service in `docker-compose.yml` uses it.

### Docker Compose

Adds `redis` (no host port mapping - reachable only inside
`finquest-net`; `maxmemory 256mb`, `maxmemory-policy noeviction`,
persistence disabled since PostgreSQL is the durable source of truth,
not Redis) and `finquest-worker-{market,portfolio,knowledge,default}`.
Every worker shares the API's image, runs as the same non-root
`finquest` user, and does **not** run migrations itself - `alembic
upgrade head` remains an explicit operator step, unchanged from Phase
10.

```powershell
$env:AUTH_JWT_SECRET = "<a long random secret>"
docker compose up -d stock-db redis finquest-api finquest-worker-market `
  finquest-worker-portfolio finquest-worker-knowledge finquest-worker-default
docker compose exec finquest-api python -m alembic upgrade head
curl http://localhost:8080/ready
docker compose exec finquest-api python -m stock_research_core.cli.operations_admin `
  --create-integration-client --name "FinQuest n8n" `
  --allow-job TRACKED_MARKET_REFRESH --allow-job PORTFOLIO_BATCH_VALUATION `
  --allow-job CURRICULUM_KNOWLEDGE_REFRESH --allow-job RETRIEVAL_EVALUATION
```

### Testing

New unit tests (no Redis, no PostgreSQL, no Celery - in-memory fakes
only): `test_operations_domain_models.py` (36), `test_job_registry.py`
(18), `test_operations_locking.py` (11, fake lock port),
`test_client_identity_resolver.py` (11), `test_operations_sanitization.py`
(17), `test_structured_logging.py` (11, redaction + JSON/console
format), `test_operations_metrics.py` (16), `test_job_service.py` (18,
idempotency/execution/retry/duplicate-delivery against in-memory
fakes for every port).

New integration tests (real PostgreSQL; Redis-dependent ones skip,
never fail, when Redis is unreachable): `test_operations_repositories.py`
(12, all 5 repositories including the idempotency-scope unique
constraint and sensitive-result-summary rejection at the write layer),
`test_job_concurrency.py` (7, real Redis lock contention/ownership/
expiry), `test_integration_api.py` (19, admin operations API +
full n8n authentication/replay-protection/ownership contract, using a
real `BackgroundJobService` against the real database with only the
Celery queue and lock faked out), `test_n8n_workflow_contracts.py` (32,
structural validation of every workflow file plus an optional live
n8n-import check).

The full distributed pipeline (real PostgreSQL + real Redis + a real,
separately-running Celery worker process, driven end-to-end through the
containerized `docker compose` stack) was additionally validated
manually during development: a job created through the n8n integration
API is delivered via Redis, consumed by an independent worker
container, and its `SUCCEEDED`/`FAILED` result, attempts, and events
land back in PostgreSQL - including a genuine non-retryable failure
path (a `PORTFOLIO_VALUATION` job for a nonexistent portfolio correctly
reaches `FAILED` in one attempt, never retried, since
`VirtualPortfolioNotFoundError` is not in that job type's
`retryable_exceptions`).

### Frontend

No learner-facing UI was added in this phase. Every Phase 11 job type
is an internal/system job (market refresh, batch portfolio valuation,
knowledge-base maintenance, retrieval evaluation) - none is triggered
by, or owned by, a learner, and no existing learner endpoint was
converted to return `202 Accepted`. Per the phase's own scope
boundary ("do not convert every endpoint into a job... do not expose
system jobs to learners"), building a job-status UI component now would
have nothing real to point at; `types/generated-api.ts` was regenerated
from the updated OpenAPI schema (which now includes the `/operations`
and `/integrations/n8n` paths) purely for contract-drift detection,
not because the frontend calls them - `npm run api:check`, `lint`,
`typecheck`, and the full `npm test` suite all pass unchanged, and no
frontend source file was modified.

### Known limitations

- The `RetrievalEvaluationJobHandler`'s evaluation dataset is a small,
  fixed, built-in fixture (`default_v1`, six cases) - deliberately
  simple and fully deterministic (no LLM judge), but not a substitute
  for a curated, larger-scale evaluation corpus; extending it only
  requires adding cases to `_EVALUATION_DATASETS`, not changing the
  measurement logic.
- `finquest-worker-knowledge` defaults to the `base` (network-free,
  `deterministic_fake`-compatible) image target; getting real
  sentence-transformer embeddings requires rebuilding it with the `ai`
  target and setting `EMBEDDING_PROVIDER=sentence_transformer` - this
  is a deliberate default (matching Phase 10's existing API-image
  default), not an oversight.
- OpenTelemetry tracing covers job creation/execution spans; it does
  not yet instrument SQLAlchemy or Redis calls directly (the optional
  `opentelemetry-instrumentation-sqlalchemy`/`-redis` packages are
  listed as installable extras but not wired into the composition
  roots yet).
- `worker_status.py`'s Celery-broker check and `/ready`'s worker-inspect
  check both use `celery_app.control.inspect(...)` (a bounded, ~1s
  round-trip) - a worker that is technically running but not currently
  consuming from Redis (e.g. mid-restart) may transiently report as
  unavailable.

## Phase 12: LangGraph personalized learning orchestrator ("the coach")

A second, stateful conversational surface alongside the existing
grounded AI tutor (Phase 8-9): the tutor is direct grounded Q&A inside
one context; the coach *orchestrates* - it classifies what a learner is
asking for, routes to the right existing capability (the grounded
tutor, a lesson/exercise/scenario/portfolio-scoped tutor conversation,
a progress reflection, an adaptive recommendation), and, for the small
set of state-changing actions it can take (starting a practice session
or a diagnostic assessment), pauses and requires the learner's explicit
approval before anything happens. It is not a stock-selection, trading,
or portfolio-rebalancing agent, not a replacement for the deterministic
adaptive engine or the grounded tutor, and not a free-form agent with
an open-ended tool registry - every action it can ever take is one of
six enum values, closed at the type level (`LearningActionType`).

```text
learner  →  /api/v1/coach (FastAPI)  →  PersonalizedLearningOrchestratorService
                                              │
                                              ├─ PostgreSQL: learning_orchestrator_threads/runs/events/action_proposals
                                              │  (FinQuest's own audit/state - the public, auditable record)
                                              │
                                              └─ LangGraph `finquest-learning-coach` StateGraph
                                                     │
                                                     └─ PostgreSQL (via `AsyncPostgresSaver`): orchestration
                                                        checkpoints only - bounded step position, never a
                                                        duplicate of tutor-conversation history
```

### Two persistence layers, on purpose

LangGraph's own `AsyncPostgresSaver` (`langgraph-checkpoint-postgres`)
owns exactly one thing: the graph's orchestration position (which node
ran, the bounded `LearningCoachGraphState`, interrupt/resume plumbing).
Its schema is never reimplemented or touched directly by application
code - `infrastructure/learning_orchestrator/postgres_checkpointer.py`
constructs a `psycopg_pool.AsyncConnectionPool` and hands it to
`AsyncPostgresSaver(conn=pool)`, and table creation is one explicit,
idempotent administrative step (`learning_orchestrator_admin
--setup-checkpointer`), never run automatically on API startup.

FinQuest's own four tables (migration `0010_langgraph_orchestrator`) -
`learning_orchestrator_threads`/`runs`/`events`/`action_proposals` -
are the *public, auditable* state: what a learner sees when they list
their coach threads, what an admin sees when investigating a run, what
Prometheus/structured logs report on. A `LearningOrchestratorEvent` is
immutable once written and structurally excludes raw prompts, chain-of-
thought, embedding vectors, and secrets (`domain/learning_orchestrator/
models.py`'s validators reuse Phase 11's `domain.operations.sanitization`
helpers). The two layers are kept honest by a hard rule the application
layer's own `LearningGraphRuntimePort` enforces: nothing outside
`infrastructure/learning_orchestrator/graph_runtime.py` is allowed to
import `AsyncPostgresSaver` or psycopg directly
(`test_orchestrator_architecture.py` asserts this by AST inspection).

### The graph

`application/learning_orchestrator/graph_builder.py` builds an explicit
`StateGraph` (never a generic prebuilt agent loop): `initialize_run →
load_authorized_context → evaluate_input_guardrail → (REFUSE/FALLBACK
short-circuit the existing tutor guardrail, reused as-is, never a
weaker parallel one) → classify_intent → select_route` (a pure,
deterministic function over the classified intent - never an LLM
choosing an arbitrary node name) `→ one of ten route subgraphs →
validate_final_output → persist_final_result → END`. Every route
subgraph (`application/learning_orchestrator/subgraphs.py`) reuses an
*exact* existing service - `GroundedAITutorService`, `LessonTutorService`,
`ScenarioTutorService`, `PortfolioTutorService`,
`AdaptiveLearningService` - never a second implementation of retrieval,
grading, mastery, or portfolio-risk math. Two routes
(`PRACTICE_ACTION`/`DIAGNOSTIC_ACTION`) only ever *propose* an action;
`GraphNodes.build_action_proposal` persists the proposal, then
`approval_interrupt` calls LangGraph's `interrupt()` with a learner-safe
payload (proposal id/title/description/reason/safe parameters/
expiration - never a secret, never raw state) *before* anything
executes. Resuming is `Command(resume={"decision": "APPROVE" | "REJECT"
| "EDIT", ...})`; `AllowlistedLearningActionExecutor` is the entire
action surface - six handlers, one per `LearningActionType`, with no
code path anywhere for a trade, a rebalance, a market-data job, an
operational job, or an admin action. A bounded `maximum_steps` (default
30, enforced inside `GraphNodes`, independent of LangGraph's own
`recursion_limit`) makes an infinite loop structurally impossible.

### Intent classification and the safety boundary

`RuleBasedLearningIntentClassifier` (deterministic regex rules,
`learning-intent-rules-v1`) is the default and primary classifier - an
investment-advice/buy-sell/guaranteed-return check runs *first*, in
isolation from every other rule, and always short-circuits to `UNKNOWN`
with `requires_action_approval=False`; nothing downstream can ever turn
that into a portfolio action. This is defense in depth, not the real
safety boundary - the actual boundary is the existing
`RuleBasedTutorGuardrail`, which runs *before* intent classification in
the graph topology and reuses the exact same refusal text the Phase 8
tutor already uses. An optional, single-call model-assisted fallback
(`ModelAssistedLearningIntentClassifier`,
`LANGGRAPH_MODEL_INTENT_CLASSIFICATION=false` by default) is only ever
consulted when the rule-based result is a genuine `UNKNOWN` - never for
the investment-advice short-circuit - and any failure (timeout,
malformed response, an intent string outside the closed
`LearningIntent` allow-list) silently falls back to the deterministic
`UNKNOWN`/`FALLBACK` path rather than failing the request.

### Concurrency, locking, and durability

One active graph run per thread, enforced by the same
`DistributedLockPort`/`RedisDistributedLock` abstraction Phase 11's
background jobs use (`learning-orchestrator-thread:{thread_id}`) - held
only for the duration of one graph invocation, never for the entire
open-ended human-approval wait; a `WAITING_FOR_LEARNER` run's
PostgreSQL row is the durable source of truth while nothing holds the
lock. This was verified genuinely, not just asserted: a run is started
and driven to `WAITING_FOR_LEARNER` through one `create_app()` instance,
that instance's checkpointer pool and database engine are closed
entirely (simulating an API-process restart), and a *second*,
independent `create_app()` instance resumes and completes the same run
using only what PostgreSQL persisted
(`test_orchestrator_resume.py::test_a_waiting_run_resumes_correctly_after_a_full_process_restart`).

### Streaming

`POST /api/v1/coach/threads/{id}/runs/stream` and `/runs/{id}/resume/
stream` use Server-Sent Events over a plain authenticated `fetch()`
response (never the browser's native `EventSource`, which cannot send
an `Authorization` header). `application/learning_orchestrator/
event_stream.py` is a pure function mapping one LangGraph
`stream_mode="updates"` chunk to zero or more events from a fixed,
learner-safe allow-list (`stage`, `intent`, `route`, `citation`,
`action_proposed`, `approval_required`, `run_completed`, `error`, ...) -
raw state, prompt text, internal node names, chunk ids, and vectors
never cross this boundary, independent of whatever a future node adds
to graph state.

### API

`/api/v1/coach`: `POST`/`GET /threads`, `GET /threads/{id}`, `POST
/threads/{id}/close`, `POST /threads/{id}/runs` (requires an
`Idempotency-Key` header, `202 Accepted`) and `.../runs/stream` (SSE),
`GET /runs/{id}`, `GET /runs/{id}/events`, `POST /runs/{id}/resume`
and `.../resume/stream`, `POST /runs/{id}/cancel`. Every route derives
the caller's learner id from the authenticated principal, never a path
parameter; ownership mismatches return 404 (not 403), matching every
other FinQuest router. The whole router is only registered when
`LANGGRAPH_ENABLED=true` (default `false`) - an unconfigured deployment
gets a 404 for `/api/v1/coach/*`, not a 500, and `/ready`'s new
`learning_coach` block (`enabled`/`graph_compiled`/`graph_version`/
`checkpointer_connected`/`intent_classifier_mode`) never gates the rest
of the API's readiness on the coach subsystem's health.

### Configuration

All new environment variables default to safe/disabled: `LANGGRAPH_ENABLED`
(`false`), `LANGGRAPH_GRAPH_VERSION`, `LANGGRAPH_MAX_STEPS` (30),
`LANGGRAPH_RUN_TIMEOUT_SECONDS` (90), `LANGGRAPH_MAX_REPAIR_ATTEMPTS` (1),
`LANGGRAPH_MODEL_INTENT_CLASSIFICATION` (`false`),
`LANGGRAPH_CHECKPOINTER_ENABLED`, `LANGGRAPH_THREAD_LOCK_TTL_SECONDS` (120),
`LANGGRAPH_THREAD_LOCK_WAIT_SECONDS` (2), `LANGGRAPH_MAX_CONTEXT_CHARACTERS`
(20,000), `LANGGRAPH_MAX_STATE_LIST_ITEMS` (50), `LANGSMITH_TRACING`
(`false`, no account required, `LANGSMITH_TRACE_CONTENT=false` hides
learner input/output from traces even when enabled). See
`.env.example` for the full list.

### Admin CLI

`python -m stock_research_core.cli.learning_orchestrator_admin`:
`--setup-checkpointer` (idempotent, the one-time table-creation step),
`--validate-graph` (compiles the graph against an in-memory checkpointer
- no database required, structural validation only),
`--thread-status`/`--run-status` (FinQuest audit state plus the graph's
bounded orchestration position - never raw checkpoint bytes),
`--close-thread` (admin override, no ownership check), and
`--delete-checkpoint-thread` (requires `--confirm-delete`; deletes
LangGraph checkpoint history only - it never touches the FinQuest audit
tables).

### Test coverage

151 new unit tests (domain model validation, `state.py` bounds/forbidden-
key checks, the rule-based intent classifier against every example
phrase in the spec plus every investment-advice pattern, the pure
`select_route` function, the action allow-list including a structural
guard that it has a handler for every `LearningActionType` and nothing
else, `event_stream.py`'s learner-safe mapping, an AST-based
architecture test enforcing the "no LangGraph outside nodes/subgraphs/
graph_builder, no checkpointer outside graph_runtime.py" boundary,
`PersonalizedLearningOrchestratorService` against in-memory fakes for
every port, individual `GraphNodes` methods, and the full interrupt/
approve/reject/edit/resume cycle against a real compiled graph with
LangGraph's `InMemorySaver`) plus 33 new integration tests against the
real PostgreSQL test database - `test_orchestrator_repositories.py`
(14), `test_langgraph_postgres_checkpointer.py` (3, including a
checkpoint-survives-a-fresh-connection-pool round trip),
`test_orchestrator_api.py` (11, every endpoint including SSE streaming
and the full HTTP approval flow), `test_orchestrator_resume.py` (1, the
genuine cross-process durability test described above), and
`test_orchestrator_concurrency.py` +
`test_orchestrator_end_to_end.py` (4, real-Redis lock contention and a
full multi-turn learner session). All 1024 unit tests and every
existing integration test continue to pass unchanged.

Writing the integration tests surfaced two real bugs that unit tests
with fakes could not have caught: `app_factory.py` referenced
`PandasScenarioCalculator`/`PandasPortfolioAnalytics` without importing
them (a `NameError` that only manifests when `LANGGRAPH_ENABLED=true`,
since that code path is otherwise dead), and `service.py` called
`.value` on `LearningApprovalRequest.decision`, which is a plain
validated `str` field, not an enum (an `AttributeError` on every
resume). Both were found and fixed by rebuilding the real
`finquest-api` Docker image, enabling `LANGGRAPH_ENABLED=true` against
the real stack, and driving a full HTTP session through it - the
`execute_action` node's exception handling was also widened from
`except StockResearchError` to `except Exception` after a unit test
proved a plain `RuntimeError` from a future/misbehaving action executor
would otherwise crash the entire graph run instead of degrading to a
sanitized, learner-safe failure message.

### Frontend

*(Not yet built in this pass - `/coach` route, streaming client, and
approval-card UI remain outstanding; the existing Tutor UI is
unaffected.)*

### Known limitations

- The Windows-development-only friction already documented for the
  checkpointer (`tests/integration/conftest.py`'s Phase 12 note):
  psycopg's async mode requires `WindowsSelectorEventLoopPolicy`, which
  the checkpointer-dependent integration test modules set at their own
  module level rather than forcing session-wide - a complete non-issue
  on Linux/Docker/CI, where there is no Proactor/Selector split at all.
- Those same modules require a reachable Redis; docker-compose's
  `redis` service deliberately has no host port mapping (a Phase 11
  security decision this phase preserves), so running them from a
  Windows host (rather than inside the Docker network, as CI does)
  needs a temporary local forwarder - see
  `learning_orchestrator_app_fixtures.py`'s docstring.
- `ModelAssistedLearningIntentClassifier`'s HTTP client
  (`HttpIntentClassificationModelClient`) is not exercised in this
  pass's test suite beyond construction - it is disabled by default
  (`LANGGRAPH_MODEL_INTENT_CLASSIFICATION=false`) and every failure
  mode falls back to the deterministic rule-based result, but a mocked-
  transport test (mirroring `test_extractive_tutor.py`'s pattern for
  the tutor model adapter) would still be worth adding.
- `subgraphs.py`'s ten route handlers are plain, independently testable
  async functions registered as graph nodes rather than literal nested,
  compiled `StateGraph` objects - each still satisfies "a dedicated,
  bounded-responsibility, inspectable node per route," but is not a
  second level of LangGraph subgraph compilation.
- **Observed, not fully root-caused**: driving the SSE endpoints through
  a real browser (Playwright, full Docker stack) and then letting the
  page navigate away mid-stream (a client abandoning the `fetch()`
  before it completes - exactly what a tab close or a fast page
  navigation does) occasionally left one `learning-orchestrator-thread:
  {thread_id}` Redis lock un-released and, once, made `/ready` and a
  subsequent request briefly slow. The safety properties that matter
  most still held in every observation - no corrupted run, no double-
  executed action, and the orphaned lock self-heals within
  `LANGGRAPH_THREAD_LOCK_TTL_SECONDS` (120s) rather than blocking that
  thread forever - but the exact mechanism (most likely an
  `asyncio.CancelledError`/`GeneratorExit` from an abandoned client
  connection not fully unwinding through every nested `async with` in
  the LangGraph/psycopg call chain before Starlette abandons the
  generator) was not pinned down precisely enough to fix with
  confidence in this pass. Concurrent multi-request load *without* a
  mid-stream client abandonment (`test_orchestrator_concurrency.py`,
  real Redis, real lock contention) shows no such issue. Worth a
  dedicated follow-up: reproduce with direct `httpx` client cancellation
  (removing the browser as a variable) and instrument
  `psycopg_pool.AsyncConnectionPool`'s connection-health callbacks.

## Phase 13: RAGAS and learning-quality evaluation platform

### Stabilization gate: the Phase 12 SSE-cancellation lock leak, fixed

The limitation documented directly above is now root-caused and fixed.
The mechanism was not `GeneratorExit` failing to unwind - it was anyio's
cancel-scope semantics (which Starlette's `StreamingResponse` uses
under the hood): once a scope is cancelled, *every subsequent await*
inside it re-raises cancellation immediately, including an await sitting
inside a `finally` block that is trying to clean up. `held_lock`'s
`finally: await lock_port.release(...)` (`application/operations/
locking.py`) was exactly such an await - a disconnect arriving while
that release call was in flight could abort the release itself before
Redis confirmed the key was gone, leaving it to expire via TTL instead.

The fix shields the release call from that outer cancellation and bounds
it independently:

```python
await asyncio.wait_for(
    asyncio.shield(lock_port.release(key=key, owner_id=owner_id)),
    timeout=release_timeout_seconds,
)
```

`asyncio.shield` runs the release as a separate task the cancel scope
cannot reach; `wait_for` still bounds how long *this* caller waits for
confirmation (a hung Redis call cannot block shutdown forever - the
lock's TTL remains the final backstop, not the normal cleanup path).
A cleanup that could not be confirmed synchronously increments
`finquest_sse_lock_cleanup_failures_total` rather than failing silently.
`PersonalizedLearningOrchestratorService._stream_and_finalize` also now
explicitly `aclose()`s the LangGraph stream iterator on the way out, for
the same reason. This benefits every `held_lock` caller, not just the
Coach - `BackgroundJobService.execute_job` gets the identical guarantee
for free.

Validated with `tests/integration/test_orchestrator_sse_cancellation.py`:
cancellation at each of the four documented stages (context loading,
mid-stream, immediately before an interrupt, immediately after an event
is yielded), plus the spec-mandated repeated-validation run -
**200/200 iterations, 0 unreleased locks, 0 corrupted runs** - against a
real Redis instance, using `pytest-repeat`.

### The evaluation platform

```text
Curated JSONL suites (evaluation/suites/*.jsonl)
        |  validate -> import (DRAFT) -> admin approve (cascades to cases)
        v
QualityEvaluationService.create_run/execute_run
        |
        +- QualityEvaluationRunner -> EvaluationCaseExecutorPort
        |     `- TutorGroundedCaseExecutor: the REAL GroundedAITutorService.ask(),
        |        under a dedicated, always-closed evaluation conversation/learner -
        |        never a real learner's history (spec section 16)
        |
        +- deterministic_metrics.py: Hit@K/MRR/Precision/Recall@K (chunk + document
        |     identity), citation validity/ordering, guardrail/refusal/leakage
        |     prevention, Coach intent/route/action/interrupt accuracy - the
        |     ALWAYS-AVAILABLE path, no evaluator LLM, no API key
        |
        +- RagasEvaluationPort -> infrastructure/quality_evaluation/ragas_adapter.py
        |     (the only two files that import `ragas`; RAGAS_ENABLED=false by default)
        |
        `- PostgreSQL: quality_evaluation_suites/cases/runs/sample_results/
              quality_metric_results/baselines, learning_quality_aggregates
              (migration 0011_ragas_learning_quality)
```

Reused, never duplicated: retrieval (`HybridKnowledgeRetriever`),
generation and guardrails (`GroundedAITutorService`), citation data
(`ConversationRepositoryPort`/`RetrievalAuditRepositoryPort`) - the
executor calls the exact same production code path a learner's request
would, then *grades* what came back.

**Hard gates always win.** `citation_validity`,
`personalized_advice_refusal_accuracy`,
`scenario_future_leakage_prevention`, `unauthorized_action_prevention`,
and five others are release-gating booleans (spec section 13) - a
single hard-gate failure marks a run FAILED for gating purposes
regardless of how high its average RAGAS score is
(`reports.build_gate_decision`, `regression.compare_metric`'s
`is_hard_gate` path).

**Curated datasets use concept coverage, not content-hash IDs.**
`KnowledgeIngestionService._content_derived_id` means a knowledge-base
document's UUID changes whenever its content changes, so hand-authoring
`reference_document_ids`/`reference_chunk_ids` into a checked-in JSONL
file would silently go stale on the next curriculum edit - exactly the
problem `scripts/evaluate_tutor_retrieval.py` (the deterministic
retrieval evaluator from an earlier phase) already solved by matching on
keywords instead. Curated cases follow the same pattern:
`required_concepts` (portable, environment-independent) is the primary
ground truth; ID-based Hit@K/MRR/Precision/Recall@K still work whenever
a case *does* carry reference IDs, reported `NOT_EVALUATED` (not a false
zero) otherwise.

**Side-effect safety.** Evaluation runs under a fixed, seeded fixture
learner (`scripts/seed_quality_evaluation_fixtures.py`,
`TutorGroundedCaseExecutor.EVALUATION_FIXTURE_LEARNER_ID`) whose
conversations are opened and closed within a single case execution -
never left active, never mixed with real learner history. Coach case
execution stops at proposal generation and never approves or executes
an action; `unauthorized_action_prevention` asserts this held for every
sample.

**RAGAS compatibility.** Pinned `ragas==0.4.3`. Its own dependency on
`langchain-community` has no upper bound, and the latest
`langchain-community` (0.4.x) dropped the `chat_models.vertexai`
submodule that `ragas.llms.base` imports unconditionally - `import
ragas` fails without also pinning `langchain-community==0.3.31`
(`pyproject.toml`'s `quality_evaluation` extra pins both together; see
its comment for the exact failure). Built against the current
collections-based per-sample API (`ragas.metrics.collections.*`, each
metric an `ascore(...)` coroutine) rather than the legacy
`evaluate()`/`ragas.metrics.*` API 0.4.x itself deprecates. Verified
against the real installed package in
`tests/unit/test_ragas_adapter.py`'s compatibility smoke test.

**Scope note - what is and is not wired up this phase.** DETERMINISTIC
mode's `GENERAL_RAG` case type (the `finquest-rag-core-v1`/
`finquest-safety-v1` suites) runs against the real tutor pipeline,
verified end to end via CLI, API, and automated tests including real
knowledge-base content. Lesson/exercise/scenario/portfolio/Coach case
execution and the cohort-wide learning-quality calculator raise a
clear, typed error rather than a fabricated result - each needs its own
service-specific context plumbing (`lesson_id`/`scenario_id`/etc.) or,
for learning-quality, bulk/cohort query methods that today's per-learner
repository ports don't expose. RAGAS mode is fully built and tested
(mocked transport) but disabled by default with no evaluator configured.

### Admin surfaces

```text
CLI:   python -m stock_research_core.cli.quality_evaluation_admin
         --validate-suite / --import-suite / --approve-suite / --run-suite --mode / --run-status / --compare-run --baseline
API:   /api/v1/admin/evaluations/{suites,runs,baselines}/* (ADMIN-only)
Jobs:  RAGAS_QUALITY_EVALUATION / LEARNING_QUALITY_AGGREGATION / QUALITY_BASELINE_COMPARISON
       (queue finquest.evaluation - already consumed by finquest-worker-knowledge)
```

`POST /runs` returns `202` and queues a durable background job - it
never runs an evaluation inline. Suite approval cascades to every
`DRAFT` case in that suite in the same transaction (a suite-level-only
approval would otherwise leave `execute_run` selecting zero cases,
since it only ever runs cases whose own status is `APPROVED`).

### Testing

New, all passing against the real stack (PostgreSQL, Redis via
`REDIS_TEST_URL`, real tutor pipeline): domain model validation, JSONL
dataset loader, deterministic metrics, learning-outcome metric formulas,
regression comparison, RAGAS adapter (mocked transport + real-package
compatibility smoke test), repositories (suite/case/run/result/baseline/
aggregate round trips against real Postgres), the real
`TutorGroundedCaseExecutor` against real ingested content, the full
`QualityEvaluationService` orchestration (idempotency, hard-gate-
overrides-average, baseline approval/comparison), the three operational
job handlers, and the admin API (auth, import/approve, run creation,
samples/metrics/compare, baseline approval) - plus the stabilization
gate's 200-iteration cancellation suite above. Every prior phase's test
count is unchanged.
