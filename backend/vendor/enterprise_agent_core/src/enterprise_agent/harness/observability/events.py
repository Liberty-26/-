"""Create consistently correlated events without copying raw task content."""

from __future__ import annotations

from typing import Any

from enterprise_agent.contracts import ActorType, Correlation, EventType, RunEvent, TaskContext


class EventFactory:
    def __init__(self, task: TaskContext) -> None:
        self.correlation = Correlation(
            trace_id=task.trace_id,
            task_id=task.task_id,
            thread_id=task.thread_id,
            tenant_id=task.tenant_id,
            package_id=task.package_id,
        )

    def create(
        self,
        event_type: EventType,
        *,
        actor: ActorType = ActorType.HARNESS,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        return RunEvent(
            event_type=event_type,
            actor=actor,
            correlation=self.correlation,
            payload=payload or {},
        )
