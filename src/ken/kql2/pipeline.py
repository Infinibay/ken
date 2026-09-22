"""Iterative depth-first joins with optional, exclusive operator profiling."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator, Iterator
from dataclasses import asdict, dataclass

from .operators import Frame, Operator


@dataclass(slots=True)
class OperatorStats:
    input_rows: int = 0
    output_rows: int = 0
    elapsed_ms: float = 0

    def measure(self, rows: Iterator[Frame]) -> Iterator[Frame]:
        self.input_rows += 1
        try:
            while True:
                started = time.perf_counter()
                try:
                    row = next(rows)
                except StopIteration:
                    return
                finally:
                    self.elapsed_ms += (time.perf_counter() - started) * 1000
                self.output_rows += 1
                yield row
        finally:
            close = getattr(rows, "close", None)
            if close is not None:
                close()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def run(
    operators: tuple[Operator, ...],
    check: Callable[[], None],
    stats: tuple[OperatorStats, ...] = (),
) -> Generator[Frame, None, None]:
    """Keep suspended iterators, not Python recursion, for each join depth.

    A frame owns its bindings; operators never mutate their input. Closing the
    pipeline closes every suspended scan, including on cancellation or errors.
    """
    stack: list[Iterator[Frame]] = [iter((Frame({}),))]
    try:
        while stack:
            try:
                frame = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            check()
            index = len(stack) - 1
            if index == len(operators):
                yield frame
                continue
            rows = operators[index].apply(frame)
            stack.append(stats[index].measure(rows) if stats else rows)
    finally:
        for rows in reversed(stack):
            close = getattr(rows, "close", None)
            if close is not None:
                close()
