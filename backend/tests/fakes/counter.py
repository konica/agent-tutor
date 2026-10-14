"""A counter that remembers how many times it was incremented."""

from smart_tutor.shared.ports.counter import Counter


class CountingCounter(Counter):
    def __init__(self) -> None:
        self.count = 0

    async def increment(self) -> None:
        self.count += 1
