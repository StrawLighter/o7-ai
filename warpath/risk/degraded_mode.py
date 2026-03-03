"""
Degraded Operating Modes — NORMAL / SAFE_MANAGE / FULL_HALT.

State machine managing the bot's operating mode based on risk conditions.
"""

from __future__ import annotations

import logging
import time

from warpath.config import DegradedMode

logger = logging.getLogger(__name__)

# Valid state transitions
_TRANSITIONS: dict[DegradedMode, set[DegradedMode]] = {
    DegradedMode.NORMAL: {DegradedMode.SAFE_MANAGE, DegradedMode.FULL_HALT},
    DegradedMode.SAFE_MANAGE: {DegradedMode.NORMAL, DegradedMode.FULL_HALT},
    DegradedMode.FULL_HALT: {DegradedMode.NORMAL},  # Manual reset only
}


# Severity ordering for escalation comparison
_SEVERITY: dict[DegradedMode, int] = {
    DegradedMode.NORMAL: 0,
    DegradedMode.SAFE_MANAGE: 1,
    DegradedMode.FULL_HALT: 2,
}


class DegradedModeManager:
    """Manages operating mode transitions with safety constraints."""

    def __init__(self) -> None:
        self.mode: DegradedMode = DegradedMode.NORMAL
        self._mode_since: float = time.time()
        self._clear_since: float = 0.0  # when all-clear started
        self._all_clear_required_s: float = 300.0  # 5 min of clear before NORMAL

    @property
    def is_normal(self) -> bool:
        return self.mode == DegradedMode.NORMAL

    @property
    def can_open_positions(self) -> bool:
        return self.mode == DegradedMode.NORMAL

    @property
    def should_tighten_stops(self) -> bool:
        return self.mode == DegradedMode.SAFE_MANAGE

    @property
    def should_flatten(self) -> bool:
        return self.mode == DegradedMode.FULL_HALT

    def transition(self, new_mode: DegradedMode, reason: str = "") -> bool:
        """Attempt a mode transition. Returns True if transition occurred."""
        if new_mode == self.mode:
            return False

        if new_mode not in _TRANSITIONS.get(self.mode, set()):
            logger.warning(
                "Invalid mode transition: %s → %s (reason: %s)",
                self.mode.value, new_mode.value, reason,
            )
            return False

        old_mode = self.mode
        self.mode = new_mode
        self._mode_since = time.time()
        self._clear_since = 0.0

        logger.warning(
            "MODE CHANGE: %s → %s (reason: %s)",
            old_mode.value, new_mode.value, reason,
        )
        return True

    def check_recovery(self, all_gates_clear: bool) -> bool:
        """Check if we can recover from SAFE_MANAGE to NORMAL.

        Requires 5 minutes of continuous all-clear before transitioning.
        FULL_HALT → NORMAL requires manual reset only.
        """
        if self.mode == DegradedMode.FULL_HALT:
            return False  # Manual reset only

        if self.mode != DegradedMode.SAFE_MANAGE:
            return False

        now = time.time()
        if all_gates_clear:
            if self._clear_since == 0.0:
                self._clear_since = now
            elif now - self._clear_since >= self._all_clear_required_s:
                return self.transition(DegradedMode.NORMAL, "All gates clear for 5 minutes")
        else:
            self._clear_since = 0.0

        return False

    def manual_reset(self) -> bool:
        """Manual reset from FULL_HALT to NORMAL (via /resume)."""
        if self.mode == DegradedMode.FULL_HALT:
            return self.transition(DegradedMode.NORMAL, "Manual reset via /resume")
        return False

    def update_from_gate_result(self, requested_mode: DegradedMode, reason: str) -> None:
        """Update mode based on gate evaluation result.

        Only escalates (NORMAL → SAFE_MANAGE → FULL_HALT), never de-escalates.
        De-escalation happens through check_recovery or manual_reset.
        """
        if _SEVERITY[requested_mode] > _SEVERITY[self.mode]:
            # This is an escalation — always allow
            pass
        elif requested_mode == self.mode:
            return
        else:
            # Requested mode is less severe — ignore (recovery handles this)
            return

        # Only escalate
        if requested_mode == DegradedMode.FULL_HALT:
            if self.mode != DegradedMode.FULL_HALT:
                self.transition(DegradedMode.FULL_HALT, reason)
        elif requested_mode == DegradedMode.SAFE_MANAGE:
            if self.mode == DegradedMode.NORMAL:
                self.transition(DegradedMode.SAFE_MANAGE, reason)

    @property
    def status(self) -> dict:
        return {
            "mode": self.mode.value,
            "since": self._mode_since,
            "duration_s": time.time() - self._mode_since,
            "can_open": self.can_open_positions,
        }
