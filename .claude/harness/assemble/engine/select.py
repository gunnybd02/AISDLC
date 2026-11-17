"""select: which pipeline an event runs, by the state of its session. No approved plan, or a plan that names none: the
floor (base). A plan that names a pipeline runs the floor with that pipeline's gears added after it, each once: the
engine puts the floor under it, so no plan makes the guards looser (spec 13 section 7)."""
from __future__ import annotations

from typing import Optional

from harness.assemble.engine.pipeline import Pipeline, PipelineBook, PipelineError
from harness.utils.shapes import ApprovedPlan

FLOOR = "base"


def select(book: PipelineBook, plan: Optional[ApprovedPlan]) -> Pipeline:
    """The pipeline an event of the session runs: the floor, and the gears its plan's pipeline adds.

    Args:
        book: the pipelines (assemble/pipelines/*.json).
        plan: the plan in force in the session, or None; its "pipeline" key names a pipeline (the floor when absent).

    Returns:
        The Pipeline: the floor's translators and detectors first, then those of the plan's pipeline not among them.

    Raises:
        PipelineError: the floor or the plan's pipeline cannot be read.
    """
    floor = book.resolve(FLOOR)
    name = (plan or {}).get("pipeline") or FLOOR
    if name == FLOOR:
        return floor
    added = book.resolve(name)
    return Pipeline(name, *(tuple(dict.fromkeys(getattr(floor, k) + getattr(added, k)))
                            for k in ("translators", "detectors")))
