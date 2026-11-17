"""select: which pipeline an event runs, by the state of its session. No approved plan, or a plan on no unit that names a
pipeline: the floor (base). A plan on units that name pipelines in project.json (spec 13 section 11.6) runs the floor,
then each of those pipelines in the order of the plan's services, each gear once: the engine puts the floor under them,
so no plan makes the guards looser (spec 13 section 7), and the model never picks a pipeline."""
from __future__ import annotations

from typing import Optional

from harness.assemble.engine.pipeline import Pipeline, PipelineBook, PipelineError
from harness.utils.shapes import ApprovedPlan

FLOOR = "base"


def select(book: PipelineBook, plan: Optional[ApprovedPlan], mapped: Optional[dict[str, str]] = None) -> Pipeline:
    """The pipeline an event of the session runs: the floor, and the pipelines of the units its plan works on.

    Args:
        book: the pipelines (assemble/pipelines/*.json).
        plan: the plan in force in the session, or None; its services are the units it works on.
        mapped: {unit: pipeline} of project.json (Config.pipelines); None or {} when no unit names one.

    Returns:
        The Pipeline, named base or base+<pipeline>...: the floor's translators and detectors first, then those each
        pipeline adds, each once.

    Raises:
        PipelineError: the floor or a mapped pipeline cannot be read.
    """
    floor = book.resolve(FLOOR)
    names = list(dict.fromkeys(mapped[s] for s in (plan or {}).get("services", []) if (mapped or {}).get(s)))
    if not names:
        return floor
    added = [book.resolve(n) for n in names]
    return Pipeline("+".join([FLOOR] + names),
                    *(tuple(dict.fromkeys(getattr(floor, k) + tuple(g for a in added for g in getattr(a, k))))
                      for k in ("translators", "detectors")))
