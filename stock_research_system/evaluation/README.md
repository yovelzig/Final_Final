# FinQuest quality-evaluation datasets

Curated evaluation suites for the Phase 13 quality-evaluation platform.
Every suite here is author-reviewed content - never RAGAS-generated,
never copied from real learner conversations (`QUALITY_ALLOW_PRODUCTION_
SAMPLE_CAPTURE=false` by default; see the platform README section for
why). A future RAGAS-assisted candidate-case generator, if built, must
write its output under `evaluation/generated/` instead, where every
case stays `DRAFT` and is excluded from production quality gates until
a human reviews and re-saves it into `evaluation/suites/`.

## Suites

| File | Type | Cases | Covers |
| --- | --- | --- | --- |
| `finquest-rag-core-v1.jsonl` | `RAG_SINGLE_TURN` | 60 | Inflation, compound interest, stocks, bonds, ETFs, indexes, risk/return, diversification, concentration, volatility, drawdown, benchmark comparison, HHI, turnover, decision quality vs. outcome, investor psychology, fraud/scams, fees, long-term investing |
| `finquest-safety-v1.jsonl` | `SAFETY` | 45 | Buy/sell, allocation, guaranteed-return, entry-price/quantity, scenario-leak, prompt injection, fake-citation, chain-of-thought exposure, admin-action requests |
| `finquest-coach-v1.jsonl` | `COACH_MULTI_TURN` | 40 | Intent classification (all 11 intents), route selection, practice/diagnostic proposals with required approval interrupts, scenario/portfolio routing, refusal routing, fallback |
| `finquest-scenario-safety-v1.jsonl` | `SCENARIO_POINT_IN_TIME` | 20 | Future-document, future-price, outcome, rubric, and correct-option leakage prevention |
| `finquest-portfolio-education-v1.jsonl` | `PORTFOLIO_EDUCATION` | 20 | Concentration, sector concentration, HHI, diversification score, drawdown, volatility, turnover, cash allocation, decision-journal completeness, trade-advice refusal |
| `finquest-learning-outcomes-v1.json` | fixture data | 9 | Reference fixtures for `application.quality_evaluation.learning_metrics` unit tests - not a `QualityEvaluationCase` suite |

## Why keyword/concept matching, not reference chunk/document ids

`KnowledgeIngestionService._content_derived_id` derives every knowledge-
base document's id from a hash of its content, so an id changes the
moment curriculum content is edited - baking one into a checked-in
JSONL file would silently go stale on the next content update. Every
case here uses `required_concepts` (and, for safety-style cases,
`forbidden_phrases`) as the portable, environment-independent ground
truth instead - the same approach `scripts/evaluate_tutor_retrieval.py`
already established. A case may still carry `reference_document_ids`/
`reference_chunk_ids` when useful; the ID-based Hit@K/MRR/Precision/
Recall@K metrics simply report `NOT_EVALUATED` (not a false zero) for
any case that omits them.

## Review workflow

1. **Author** a suite as a `.jsonl` file here (or `evaluation/generated/`
   for anything produced by an automated process).
2. **Validate** structure and reference integrity, no database required:

   ```powershell
   python -m stock_research_core.cli.quality_evaluation_admin `
     --validate-suite ".\evaluation\suites\finquest-rag-core-v1.jsonl"
   ```

3. **Import** - creates the suite and every case as `DRAFT`, never
   auto-approved:

   ```powershell
   python -m stock_research_core.cli.quality_evaluation_admin `
     --import-suite ".\evaluation\suites\finquest-rag-core-v1.jsonl" `
     --code FINQUEST_RAG_CORE_V1 --name "FinQuest RAG core" `
     --suite-type RAG_SINGLE_TURN --version v1
   ```

4. **Approve** (ADMIN only) - cascades to every `DRAFT` case in the
   suite in one transaction, so `--run-suite` never silently selects
   zero cases:

   ```powershell
   python -m stock_research_core.cli.quality_evaluation_admin --approve-suite <UUID>
   ```

5. **Run**:

   ```powershell
   python -m stock_research_core.cli.quality_evaluation_admin --run-suite <UUID> --mode DETERMINISTIC
   ```

## Editing an existing suite

Suite content is immutable once approved (spec: "Dataset content must
be immutable for one suite version"). To change cases, bump the
`--version` on import (e.g. `v2`) rather than editing an approved
suite's existing cases in place.
