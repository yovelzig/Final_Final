"""Learning platform use cases: result models, repository ports, grading,
mastery calculation, and the orchestrating `LearningService`.

`LearningService` is intentionally not re-exported here: it imports
`stock_research_core.application.persistence.ports` (for `UnitOfWorkPort`),
which in turn imports `stock_research_core.application.learning.ports` -
eagerly importing `service` from this package's `__init__.py` would make
that a circular import. Import it directly:
`from stock_research_core.application.learning.service import LearningService`.
"""

from stock_research_core.application.learning.mastery import (
    DeterministicMasteryCalculator,
    MasteryCalculatorPort,
)
from stock_research_core.application.learning.models import (
    LearnerDashboard,
    LearningActivityResult,
    LessonWithExercises,
)

__all__ = [
    "DeterministicMasteryCalculator",
    "LearnerDashboard",
    "LearningActivityResult",
    "LessonWithExercises",
    "MasteryCalculatorPort",
]
