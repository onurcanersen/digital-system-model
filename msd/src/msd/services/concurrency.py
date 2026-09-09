"""Shared unit-level concurrency for the per-unit workflow phases (clone,
scan, analyze): each phase walks the same unit inventory, and its per-unit
work runs here with up to UNIT_CONCURRENCY workers instead of one unit at a
time, so a slow unit no longer stalls the whole phase behind it.

Threads (not processes) because the per-unit work is subprocess/IO bound
(git clone, gmake, file reads): the GIL is released while a subprocess runs,
so the units genuinely overlap. `work_fn` must be safe to call from several
threads at once — the adapters it touches act on separate unit directories
and never on shared state.

The driving thread owns everything else: it submits the work, reports
progress as units complete, and assembles the results in inventory order.
`done` therefore still increments 1..N per phase, in the same shape
PhaseProgress expects, and the caller's progress callback never sees a
concurrent call.

Known trade-off: if one unit's work raises, the exception re-raises on the
driving thread, but the executor's shutdown first lets the already-submitted
(still queued) units finish. Today's sequential loop would have skipped
them; the run's final state (the exception) is the same either way.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, TypeVar

from msd.domain.inventory import SoftwareUnitVersion

UNIT_CONCURRENCY = 4

T = TypeVar("T")


def run_units_concurrently(
    units: List[SoftwareUnitVersion],
    work_fn: Callable[[SoftwareUnitVersion], T],
    phase: str,
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> List[T]:
    """Run `work_fn(unit)` over `units` with up to UNIT_CONCURRENCY concurrent
    workers, returning the results in inventory order.

    `phase` is the progress phase name this work belongs to; `progress`,
    when given, is called from the driving thread with (phase, done, total) —
    once before any work starts, then once per unit as units complete."""
    results: List[T] = [None] * len(units)
    if progress is not None:
        progress(phase, 0, len(units))
    if units:
        with ThreadPoolExecutor(max_workers=UNIT_CONCURRENCY) as pool:
            futures = {pool.submit(work_fn, unit): index for index, unit in enumerate(units)}
            done = 0
            for future in as_completed(futures):
                results[futures[future]] = future.result()
                done += 1
                if progress is not None:
                    progress(phase, done, len(units))
    return results
