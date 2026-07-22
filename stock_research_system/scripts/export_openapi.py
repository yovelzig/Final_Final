"""Export the FinQuest API's OpenAPI schema to a deterministic JSON file
for frontend type generation.

Usage (PowerShell):

    python scripts/export_openapi.py

Builds the FastAPI app via `create_app(testing=True)` - this only
constructs routes/schemas and never opens a database connection or
runs the app's lifespan (which is what actually creates the engine),
so this is safe to run with no database available at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

_OUTPUT_PATH = _PROJECT_ROOT / "frontend" / "openapi" / "finquest-api.json"


def main() -> int:
    from stock_research_core.api.app_factory import create_app
    from stock_research_core.infrastructure.learning_orchestrator.config import LangGraphSettings

    # Phase 12's `/api/v1/coach` router is only registered when
    # `LANGGRAPH_ENABLED=true` (a deployment's actual runtime default is
    # `false`) - forced on here so the exported schema (and therefore the
    # generated frontend types) always includes it, regardless of what
    # any given deployment has enabled. This never runs the app's
    # lifespan, so it still opens no database/checkpointer connection.
    app = create_app(testing=True, learning_orchestrator_settings=LangGraphSettings(langgraph_enabled=True))
    schema = app.openapi()

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    _OUTPUT_PATH.write_text(serialized, encoding="utf-8")

    path_count = len(schema.get("paths", {}))
    print(f"Exported OpenAPI schema ({path_count} paths) to {_OUTPUT_PATH.relative_to(_PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
