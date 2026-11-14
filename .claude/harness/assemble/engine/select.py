"""select: which pipeline an event runs, by the state of its session. No approved plan: the floor (base). A plan that
names a pipeline runs it; a pipeline that does not hold every translator and detector of the floor is refused, so no
plan makes the guards looser."""
from harness.assemble.engine.pipeline import PipelineBook, PipelineError

FLOOR = "base"


def select(book: PipelineBook, plan):
    """The pipeline of the session's plan (None: no plan), never less than the floor."""
    floor = book.resolve(FLOOR)
    name = (plan or {}).get("pipeline") or FLOOR
    chosen = book.resolve(name)
    for kind in ("translators", "detectors"):
        missing = [n for n in getattr(floor, kind) if n not in getattr(chosen, kind)]
        if missing:
            raise PipelineError(f"pipeline {name} leaves out {', '.join(missing)} of the floor; extend {FLOOR}")
    return chosen
