"""Central runtime gates for every DHIS2 code path.

``DHIS2_ENABLED`` and ``SYNC_ENABLED`` are the operator's switches for contacting the national
instance at all. They were previously checked only by the scheduled command, so an API-created job,
a worker execution or a directly constructed connector could still reach the network on a
deployment where the owner had switched DHIS2 off. Every entry point now funnels through here.

``DHIS2_LOGIN_ENABLED`` stays a separate gate: interactive sign-in and background extraction are
independently switchable, and enabling one must never imply the other.
"""

from __future__ import annotations

from dataclasses import dataclass


class Dhis2Disabled(RuntimeError):
    """A DHIS2 operation was attempted while a runtime gate is closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GateState:
    dhis2_enabled: bool
    sync_enabled: bool

    @property
    def extraction_allowed(self) -> bool:
        return self.dhis2_enabled and self.sync_enabled


def gate_state(settings) -> GateState:
    return GateState(
        dhis2_enabled=bool(settings.dhis2_enabled),
        sync_enabled=bool(settings.sync_enabled),
    )


def extraction_blocked_reason(settings) -> tuple[str, str] | None:
    """The structured reason extraction may not run, or ``None`` when both gates are open."""
    state = gate_state(settings)
    if not state.dhis2_enabled:
        return (
            "dhis2_disabled",
            "DHIS2_ENABLED is false: this deployment does not contact DHIS2.",
        )
    if not state.sync_enabled:
        return (
            "sync_disabled",
            "SYNC_ENABLED is false: scheduled and on-demand extraction are switched off.",
        )
    return None


def ensure_extraction_enabled(settings) -> None:
    """Raise before any request is built when either extraction gate is closed."""
    blocked = extraction_blocked_reason(settings)
    if blocked is not None:
        raise Dhis2Disabled(*blocked)
