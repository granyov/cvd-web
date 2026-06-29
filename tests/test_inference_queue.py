from __future__ import annotations

import threading
import time
import unittest

from cvd_web.inference_queue import InferenceQueue, InferenceQueueFull


class InferenceQueueTests(unittest.TestCase):
    def wait_for_queued(self, queue: InferenceQueue, count: int) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if queue.snapshot()["queued_count"] >= count:
                return
            time.sleep(0.005)
        self.fail(f"Ожидалось {count} запросов в очереди")

    def test_many_users_are_processed_fifo_with_one_active_call(self):
        queue = InferenceQueue(max_concurrent=1, queue_limit=64, per_user_limit=2)
        order: list[int] = []
        active = 0
        max_active = 0
        lock = threading.Lock()

        def worker(user_id: int) -> None:
            nonlocal active, max_active
            kind = "diagnosis" if user_id % 2 else "text_structuring"
            with queue.acquire(user_id=user_id, kind=kind, timeout_seconds=5):
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                    order.append(user_id)
                time.sleep(0.01)
                with lock:
                    active -= 1

        threads: list[threading.Thread] = []
        with queue.acquire(user_id=999, kind="blocker", timeout_seconds=5):
            for user_id in range(1, 51):
                thread = threading.Thread(target=worker, args=(user_id,))
                thread.start()
                threads.append(thread)
                self.wait_for_queued(queue, user_id)

        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        self.assertEqual(order, list(range(1, 51)))
        self.assertEqual(max_active, 1)
        snapshot = queue.snapshot()
        self.assertEqual(snapshot["queued_count"], 0)
        self.assertEqual(snapshot["active_count"], 0)
        self.assertEqual(snapshot["completed_count"], 51)

    def test_per_user_limit_rejects_duplicate_requests(self):
        queue = InferenceQueue(max_concurrent=1, queue_limit=10, per_user_limit=2)
        entered = threading.Event()

        def pending_request() -> None:
            entered.set()
            with queue.acquire(user_id=1, kind="text_structuring", timeout_seconds=5):
                pass

        with queue.acquire(user_id=1, kind="diagnosis", timeout_seconds=5):
            thread = threading.Thread(target=pending_request)
            thread.start()
            entered.wait(timeout=1)
            self.wait_for_queued(queue, 1)
            with self.assertRaises(InferenceQueueFull):
                with queue.acquire(user_id=1, kind="diagnosis", timeout_seconds=1):
                    pass
            user_status = queue.snapshot(user_id=1)["user"]
            self.assertEqual(user_status["active_count"], 1)
            self.assertEqual(user_status["queued_count"], 1)
            self.assertEqual(user_status["position"], 1)

        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
