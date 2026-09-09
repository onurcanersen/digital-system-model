"""Progress reporting for one clone → generate run.

The run's four phases — clone, scan, analyze, finalize — each work over the
same unit inventory, so the run's overall progress is a count of work units:
one per unit per per-unit phase, plus one unit for finalize. The aggregator
below converts the per-phase (done, total) reports the workflow steps emit
into a single 0-100 percent, handed to the caller's callback.

The phase model (order, the finalize weight, the assumption that every
per-unit phase totals what clone reported) lives here on purpose: it is the
workflow's own definition, and keeping it inside msd means a caller sees a
finished percent rather than being asked to do the arithmetic.
"""

from __future__ import annotations

from typing import Dict, Optional

PHASE_CLONE = "clone"
PHASE_SCAN = "scan"
PHASE_ANALYZE = "analyze"
PHASE_FINALIZE = "finalize"

# The order the run works through its phases. `completed` is only meaningful
# because earlier phases are finished before a later one reports.
_PHASE_ORDER = (PHASE_CLONE, PHASE_SCAN, PHASE_ANALYZE, PHASE_FINALIZE)
# finalize is one unit of work (validate + build graph + write), not one per
# unit, so it is weighted separately from the per-unit phases.
_FINALIZE_TOTAL = 1
# Until a per-unit phase has reported its own total, it is assumed to work
# the same inventory clone did.
_PER_UNIT_PHASES = (PHASE_CLONE, PHASE_SCAN, PHASE_ANALYZE)


class PhaseProgress:
    """Aggregates per-phase (done, total) reports into the run's overall
    0-100 percent, calling `reporter(percent, phase)` on every step.

    `reporter` must tolerate being called once per unit of work (3N+2 times
    for N units) and must not raise in a way that should fail the run — that
    policy is the caller's (the worker's own channel guard).
    """

    def __init__(self, reporter):
        self._reporter = reporter
        self._totals: Dict[str, int] = {}
        self._done: Dict[str, int] = {}

    def report(self, phase: str, done: int, total: int) -> None:
        if phase not in _PHASE_ORDER:
            return
        self._totals[phase] = total
        self._done[phase] = done
        denominator = self._denominator()
        if denominator < 1:
            return
        completed = self._completed(phase)
        percent = min(100, max(0, 100 * completed // denominator))
        self._reporter(percent, phase)

    def _denominator(self) -> int:
        total = 0
        for name in _PHASE_ORDER:
            total += self._totals.get(name) or self._assumed_total(name)
        return total

    def _assumed_total(self, name: str) -> int:
        if name == PHASE_FINALIZE:
            return _FINALIZE_TOTAL
        for per_unit in _PER_UNIT_PHASES:
            if per_unit in self._totals:
                return self._totals[per_unit]
        return 0

    def _completed(self, phase: str) -> int:
        completed = 0
        for name in _PHASE_ORDER:
            if name == phase:
                completed += self._done.get(phase, 0)
                break
            completed += self._totals.get(name, 0)
        return completed
