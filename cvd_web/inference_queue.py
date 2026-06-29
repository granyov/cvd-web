from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


class InferenceQueueError(RuntimeError):
    pass


class InferenceQueueFull(InferenceQueueError):
    pass


class InferenceQueueTimeout(InferenceQueueError):
    pass


@dataclass
class InferenceLease:
    ticket_id: int
    user_id: int
    kind: str
    enqueued_at: float
    started_at: float = 0.0

    @property
    def wait_ms(self) -> int:
        if not self.started_at:
            return 0
        return max(0, round((self.started_at - self.enqueued_at) * 1000))


class InferenceQueue:
    """Process-local FIFO admission control for expensive LM Studio calls."""

    def __init__(
        self,
        *,
        max_concurrent: int = 1,
        queue_limit: int = 64,
        per_user_limit: int = 2,
    ):
        self._condition = threading.Condition()
        self._max_concurrent = max(1, max_concurrent)
        self._queue_limit = max(1, queue_limit)
        self._per_user_limit = max(1, per_user_limit)
        self._next_ticket_id = 1
        self._pending: list[InferenceLease] = []
        self._active: dict[int, InferenceLease] = {}
        self._completed = 0
        self._total_wait_ms = 0
        self._max_wait_ms = 0

    def configure(self, *, max_concurrent: int, queue_limit: int, per_user_limit: int) -> None:
        with self._condition:
            self._max_concurrent = max(1, int(max_concurrent))
            self._queue_limit = max(1, int(queue_limit))
            self._per_user_limit = max(1, int(per_user_limit))
            self._condition.notify_all()

    @contextmanager
    def acquire(
        self,
        *,
        user_id: int,
        kind: str,
        timeout_seconds: int,
    ) -> Iterator[InferenceLease]:
        lease = self._wait_for_slot(
            user_id=int(user_id),
            kind=str(kind or "unknown")[:40],
            timeout_seconds=max(1, int(timeout_seconds)),
        )
        try:
            yield lease
        finally:
            self._release(lease)

    def _wait_for_slot(self, *, user_id: int, kind: str, timeout_seconds: int) -> InferenceLease:
        enqueued_at = time.monotonic()
        deadline = enqueued_at + timeout_seconds
        with self._condition:
            outstanding_for_user = sum(
                1 for item in [*self._pending, *self._active.values()] if item.user_id == user_id
            )
            if outstanding_for_user >= self._per_user_limit:
                raise InferenceQueueFull(
                    f"У пользователя уже выполняется или ожидает {outstanding_for_user} AI-запроса. "
                    "Дождитесь их завершения."
                )
            if len(self._pending) >= self._queue_limit:
                raise InferenceQueueFull(
                    f"Очередь LM Studio заполнена ({self._queue_limit} ожидающих запросов). "
                    "Повторите попытку позже."
                )

            lease = InferenceLease(
                ticket_id=self._next_ticket_id,
                user_id=user_id,
                kind=kind,
                enqueued_at=enqueued_at,
            )
            self._next_ticket_id += 1
            self._pending.append(lease)

            while True:
                is_first = bool(self._pending and self._pending[0] is lease)
                if is_first and len(self._active) < self._max_concurrent:
                    self._pending.pop(0)
                    lease.started_at = time.monotonic()
                    self._active[lease.ticket_id] = lease
                    return lease

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if lease in self._pending:
                        self._pending.remove(lease)
                    self._condition.notify_all()
                    waited = max(1, round((time.monotonic() - enqueued_at) * 1000))
                    error = InferenceQueueTimeout(
                        f"Истекло время ожидания LM Studio в очереди ({timeout_seconds} с). "
                        "Повторите запрос позже."
                    )
                    error.wait_ms = waited
                    raise error
                self._condition.wait(timeout=remaining)

    def _release(self, lease: InferenceLease) -> None:
        with self._condition:
            if self._active.pop(lease.ticket_id, None) is not None:
                self._completed += 1
                self._total_wait_ms += lease.wait_ms
                self._max_wait_ms = max(self._max_wait_ms, lease.wait_ms)
            self._condition.notify_all()

    def snapshot(self, *, user_id: int | None = None) -> dict[str, Any]:
        with self._condition:
            pending = list(self._pending)
            active = list(self._active.values())
            by_kind: dict[str, dict[str, int]] = {}
            for state, items in (("queued", pending), ("active", active)):
                for item in items:
                    counts = by_kind.setdefault(item.kind, {"queued": 0, "active": 0})
                    counts[state] += 1
            snapshot: dict[str, Any] = {
                "max_concurrent": self._max_concurrent,
                "queue_limit": self._queue_limit,
                "per_user_limit": self._per_user_limit,
                "active_count": len(active),
                "queued_count": len(pending),
                "completed_count": self._completed,
                "average_wait_ms": round(self._total_wait_ms / self._completed) if self._completed else 0,
                "max_wait_ms": self._max_wait_ms,
                "by_kind": by_kind,
            }
            if user_id is not None:
                user_pending = [item for item in pending if item.user_id == user_id]
                user_active = [item for item in active if item.user_id == user_id]
                positions = [pending.index(item) + 1 for item in user_pending]
                user_by_kind: dict[str, dict[str, int | str]] = {}
                for item in user_pending:
                    kind_state = user_by_kind.setdefault(
                        item.kind,
                        {"active_count": 0, "queued_count": 0, "position": 0, "state": "idle"},
                    )
                    kind_state["queued_count"] = int(kind_state["queued_count"]) + 1
                    position = pending.index(item) + 1
                    current_position = int(kind_state["position"])
                    kind_state["position"] = min(current_position, position) if current_position else position
                    kind_state["state"] = "queued"
                for item in user_active:
                    kind_state = user_by_kind.setdefault(
                        item.kind,
                        {"active_count": 0, "queued_count": 0, "position": 0, "state": "idle"},
                    )
                    kind_state["active_count"] = int(kind_state["active_count"]) + 1
                    kind_state["state"] = "running"
                snapshot["user"] = {
                    "active_count": len(user_active),
                    "queued_count": len(user_pending),
                    "position": min(positions) if positions else 0,
                    "state": "running" if user_active else "queued" if user_pending else "idle",
                    "kinds": sorted({item.kind for item in [*user_pending, *user_active]}),
                    "by_kind": user_by_kind,
                }
            return snapshot
