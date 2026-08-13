"""Cross-platform SQLite persistence for task, approval, and Tool execution facts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from enterprise_agent.contracts import (
    AgentState,
    ApprovalDecision,
    ApprovalRecord,
    ToolResult,
)
from enterprise_agent.contracts.common import utc_now


class ApprovalStateError(ValueError):
    pass


class SQLiteRuntimeStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.setup()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def setup(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL UNIQUE,
                    tenant_id TEXT NOT NULL,
                    package_id TEXT NOT NULL,
                    terminal_status TEXT,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_approvals (
                    approval_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_approvals_thread
                    ON agent_approvals(thread_id);

                CREATE TABLE IF NOT EXISTS tool_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    tool_call_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_state(self, state: AgentState) -> None:
        task = state.task_context
        terminal_status = state.terminal_status.value if state.terminal_status else None
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, thread_id, tenant_id, package_id,
                    terminal_status, state_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    tenant_id = excluded.tenant_id,
                    package_id = excluded.package_id,
                    terminal_status = excluded.terminal_status,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    task.task_id,
                    task.thread_id,
                    task.tenant_id,
                    task.package_id,
                    terminal_status,
                    state.model_dump_json(),
                    utc_now().isoformat(),
                ),
            )

    def load_state_by_thread(self, thread_id: str) -> AgentState | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM agent_tasks WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return AgentState.model_validate_json(row["state_json"]) if row else None

    def create_approval(self, approval: ApprovalRecord) -> None:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT record_json FROM agent_approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            if existing:
                persisted = ApprovalRecord.model_validate_json(existing["record_json"])
                if persisted != approval:
                    raise ApprovalStateError("approval_id already exists with different data")
                return
            connection.execute(
                """
                INSERT INTO agent_approvals (
                    approval_id, thread_id, task_id, decision, record_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.approval_id,
                    approval.thread_id,
                    approval.task_id,
                    approval.decision.value,
                    approval.model_dump_json(),
                    utc_now().isoformat(),
                ),
            )

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM agent_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return ApprovalRecord.model_validate_json(row["record_json"]) if row else None

    def list_pending_approvals(self) -> list[ApprovalRecord]:
        """Return durable approval facts that are still awaiting an approver.

        This deliberately returns the contract model rather than an application
        DTO: hosts remain responsible for presentation-time redaction.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json FROM agent_approvals
                WHERE decision = ?
                ORDER BY updated_at ASC, approval_id ASC
                """,
                (ApprovalDecision.PENDING.value,),
            ).fetchall()
        return [ApprovalRecord.model_validate_json(row["record_json"]) for row in rows]

    def decide_approval(
        self,
        *,
        approval_id: str,
        thread_id: str,
        task_id: str,
        approver_id: str,
        decision: ApprovalDecision,
        reason: str | None,
    ) -> ApprovalRecord:
        if decision is ApprovalDecision.PENDING:
            raise ApprovalStateError("approval decision must be approved or rejected")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_json FROM agent_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise ApprovalStateError(f"approval does not exist: {approval_id}")
            current = ApprovalRecord.model_validate_json(row["record_json"])
            if current.thread_id != thread_id or current.task_id != task_id:
                raise ApprovalStateError("approval task/thread identity mismatch")
            if current.decision is not ApprovalDecision.PENDING:
                if (
                    current.decision is decision
                    and current.approver_id == approver_id
                    and current.reason == reason
                ):
                    return current
                raise ApprovalStateError("approval has already been decided")
            decided = current.model_copy(
                update={
                    "approver_id": approver_id,
                    "decision": decision,
                    "reason": reason,
                    "decided_at": utc_now(),
                }
            )
            connection.execute(
                """
                UPDATE agent_approvals
                SET decision = ?, record_json = ?, updated_at = ?
                WHERE approval_id = ?
                """,
                (
                    decided.decision.value,
                    decided.model_dump_json(),
                    utc_now().isoformat(),
                    approval_id,
                ),
            )
            return decided

    def get_idempotent_result(self, key: str) -> ToolResult | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM tool_idempotency WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        result = ToolResult.model_validate_json(row["result_json"])
        return result.model_copy(update={"from_idempotency_cache": True})

    def put_idempotent_result(self, key: str, result: ToolResult) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_idempotency (
                    idempotency_key, tool_call_id, result_json, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (key, result.tool_call_id, result.model_dump_json(), utc_now().isoformat()),
            )


class SQLiteIdempotencyStore:
    def __init__(self, runtime_store: SQLiteRuntimeStore) -> None:
        self.runtime_store = runtime_store

    def get(self, key: str) -> ToolResult | None:
        return self.runtime_store.get_idempotent_result(key)

    def put(self, key: str, result: ToolResult) -> None:
        self.runtime_store.put_idempotent_result(key, result)
