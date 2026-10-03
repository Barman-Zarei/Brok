"""State machine for the avatar. No Qt, no timers: the UI calls tick() (cheap, event-driven)."""

from __future__ import annotations

import time
from typing import Callable

from .states import PRIORITY, TRANSIENT_SECONDS, AvatarState

IDLE_TO_SLEEP_SECONDS = 300.0


class AvatarEngine:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.state = AvatarState.IDLE
        self._since = clock()
        self._listeners: list[Callable[[AvatarState, AvatarState], None]] = []

    def subscribe(self, fn: Callable[[AvatarState, AvatarState], None]) -> None:
        self._listeners.append(fn)

    def _switch(self, new: AvatarState) -> None:
        old, self.state, self._since = self.state, new, self.clock()
        if old is not new:
            for fn in self._listeners:
                fn(old, new)

    def request(self, new: AvatarState, force: bool = False) -> bool:
        """Switch unless a higher-priority state (e.g. ERROR) is currently showing."""
        if not force and PRIORITY[new] < PRIORITY[self.state] and self.state in TRANSIENT_SECONDS:
            return False
        self._switch(new)
        return True

    def settle(self, from_state: AvatarState) -> None:
        """Called when an activity ends (speaking finished, tool done): back to idle if still in that state."""
        if self.state is from_state:
            self._switch(AvatarState.IDLE)

    def tick(self) -> AvatarState:
        age = self.clock() - self._since
        limit = TRANSIENT_SECONDS.get(self.state)
        if limit is not None and age >= limit:
            self._switch(AvatarState.IDLE)
        elif self.state is AvatarState.IDLE and age >= IDLE_TO_SLEEP_SECONDS:
            self._switch(AvatarState.SLEEPING)
        return self.state
