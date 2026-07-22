import { spawnSync } from "node:child_process";
import path from "node:path";

/**
 * Deterministic E2E fixture setup: applies migrations, then seeds
 * curriculum, adaptive-learning profiles, synthetic (network-free)
 * market data, historical scenarios, and the tutor's knowledge base -
 * against whatever `DATABASE_URL` the backend is configured with. Every
 * seed script is idempotent (stable `uuid5`-derived ids), so re-running
 * this setup is always safe and never creates duplicates.
 *
 * Learner accounts themselves are NOT seeded here - each spec creates
 * its own unique learner via the real registration flow, so tests stay
 * independent and never collide on a shared account.
 */

const BACKEND_ROOT = path.resolve(__dirname, "..", "..");
const PYTHON = path.resolve(BACKEND_ROOT, ".venv", "Scripts", "python.exe");

const STEPS: string[][] = [
  ["-m", "alembic", "upgrade", "head"],
  ["scripts/seed_learning_curriculum.py"],
  ["scripts/seed_adaptive_learning_profiles.py"],
  ["scripts/seed_e2e_synthetic_market_data.py"],
  ["scripts/seed_historical_market_scenarios.py", "--ticker", "E2ETEST", "--benchmark", "E2EBENCH", "--scenario-count", "2"],
  ["scripts/seed_finquest_knowledge_base.py"],
];

export default function globalSetup() {
  for (const args of STEPS) {
    const result = spawnSync(PYTHON, args, { cwd: BACKEND_ROOT, stdio: "inherit" });
    if (result.status !== 0) {
      throw new Error(`E2E fixture setup step failed: python ${args.join(" ")}`);
    }
  }
}
