"""App Subsystem (Master Orchestrator)."""

from app.models import (
    ActionResult,
    ActionTrigger,
    AppExitReport,
    AppRuntimeContext,
    ShutdownReason,
)
from app.orchestrator import (
    AppOrchestrator,
    cycle_next_synonym,
    dispatch_action_pipeline,
    init_application,
    shutdown_application,
)

__all__ = [
    "ActionResult",
    "ActionTrigger",
    "AppExitReport",
    "AppRuntimeContext",
    "ShutdownReason",
    "AppOrchestrator",
    "init_application",
    "dispatch_action_pipeline",
    "cycle_next_synonym",
    "shutdown_application",
]
