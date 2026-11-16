"""select: which pipeline an event runs, by the state of its session. No approved plan: the floor (base). A plan that
names a pipeline runs it; a pipeline that does not hold every translator and detector of the floor is refused, so no
plan makes the guards looser."""
from __future__ import annotations

from typing import Optional

from harness.assemble.engine.pipeline import Pipeline, PipelineBook, PipelineError
from harness.utils.shapes import ApprovedPlan

FLOOR = "base"


def select(book: PipelineBook, plan: Optional[ApprovedPlan]) -> Pipeline:
    """The pipeline of the session's plan (None: no plan), never less than the floor.

    Args:
        book: the pipelines (assemble/pipelines/*.json).
        plan: the plan in force in the session, or None; its "pipeline" key names a pipeline (base when absent).

    Returns:
        The resolved Pipeline.

    Raises:
        PipelineError: the pipeline cannot be read, or leaves out a translator or detector of the floor.
    """
    floor = book.resolve(FLOOR)
    name = (plan or {}).get("pipeline") or FLOOR
    chosen = book.resolve(name)
    for kind in ("translators", "detectors"):
        missing = [n for n in getattr(floor, kind) if n not in getattr(chosen, kind)]
        if missing:
            raise PipelineError(f"pipeline {name} leaves out {', '.join(missing)} of the floor; extend {FLOOR}")
    return chosen
