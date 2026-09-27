"""Ограниченная нагрузочная проверка отдельного локального тестового сервера.

Создаёт синтетических сотрудников, проходит сценарии через HTTP и проверяет сохранённый
прогресс. Только loopback, порт демо 8000 запрещён. PIN и токены в отчёт не попадают.
"""

import argparse
import json
import math
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4

import httpx

READ_PATHS = (
    "/api/profile",
    "/api/scenarios",
    "/api/notifications",
    "/api/analytics/me",
    "/api/leaderboard?scope=brigade",
)


def checked(response, expected=200):
    if response.status_code != expected:
        raise AssertionError(
            f"{response.request.method} {response.request.url.path}: HTTP {response.status_code}"
        )
    return response.json()


def prepare_employee(base_url, batch, index):
    with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as client:
        employee = checked(
            client.post(
                "/api/integration/employees",
                headers={"X-API-Key": os.environ.get("INTEGRATION_API_KEY", "demo-integration-key")},
                json={
                    "employee_code": f"LOAD-{batch}-{index}",
                    "display_name": f"Нагрузочная проверка {index}",
                    "brigade": "М-01",
                },
            ),
            201,
        )
        login = checked(
            client.post(
                "/api/auth/login",
                json={"employee_code": employee["employee_code"], "pin": employee["pin"]},
            )
        )
        return login["token"]


def exercise(base_url, token, rounds, read_rounds, steady_read_seconds, start):
    samples = []
    completed = 0
    try:
        with httpx.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=15, trust_env=False
        ) as client:

            def request(method, path, expected=200, **kwargs):
                began = time.perf_counter()
                status = 0
                try:
                    response = client.request(method, path, **kwargs)
                    status = response.status_code
                    return checked(response, expected)
                finally:
                    samples.append(
                        {"method": method, "status": status, "ms": (time.perf_counter() - began) * 1000}
                    )

            start.wait(timeout=30)
            profile = request("GET", "/api/profile")
            assert profile["xp_total"] == 0 and profile["runs_count"] == 0, "employee must be new"
            expected_xp = 0
            run_ids = set()
            for _ in range(rounds):
                headers = {"Idempotency-Key": str(uuid4())}
                body = {"scenario_id": "smoking_vestibule"}
                run = request("POST", "/api/sessions", 201, headers=headers, json=body)
                replay = request("POST", "/api/sessions", headers=headers, json=body)
                assert replay["run_id"] == run["run_id"], "idempotent start created another run"
                for _ in range(20):
                    if run["status"] == "finished":
                        break
                    node = run["node"]
                    option = "continue" if node["type"] == "event" else node["options"][0]["id"]
                    run = request(
                        "POST",
                        f"/api/sessions/{run['run_id']}/choose",
                        json={"option_id": option, "step_no": run["step_no"]},
                    )
                assert run["status"] == "finished", "scenario did not finish within 20 moves"
                assert run["expired_timers"] == 0, "load delayed a decision past the timer"
                debrief = request("GET", f"/api/runs/{run['run_id']}/debrief")
                assert debrief["xp"] > 0 and debrief["xp"] == run["xp"], "inconsistent awarded XP"
                expected_xp += debrief["xp"]
                run_ids.add(run["run_id"])
                completed += 1
                for path in READ_PATHS:
                    request("GET", path)
            read_deadline = time.perf_counter() + steady_read_seconds
            reads = 0
            while reads < read_rounds or time.perf_counter() < read_deadline:
                for path in READ_PATHS:
                    request("GET", path)
                reads += 1
            profile = request("GET", "/api/profile")
            assert profile["xp_total"] == expected_xp, "lost or duplicated profile XP"
            assert profile["runs_count"] == rounds, "lost or duplicated completion"
            history = request("GET", "/api/profile/runs")
            assert len(history) == rounds, "unexpected extra history rows"
            assert {row["run_id"] for row in history} == run_ids, "history contains different runs"
            assert all(row["status"] == "finished" for row in history), "unfinished history row"
            assert sum(row["xp"] for row in history) == expected_xp, "history XP disagrees with profile"
            assert request("GET", "/api/sessions/active")["active"] is None, "finished run remains active"
    except Exception as error:
        return {"samples": samples, "completed": completed, "error": f"{type(error).__name__}: {error}"}
    return {"samples": samples, "completed": completed, "error": None}


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2) if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8014")
    parser.add_argument("--users", type=int, default=10, choices=range(1, 51), metavar="1..50")
    parser.add_argument("--rounds", type=int, default=3, choices=range(1, 11), metavar="1..10")
    parser.add_argument("--read-rounds", type=int, default=5, choices=range(0, 21), metavar="0..20")
    parser.add_argument("--max-p95-ms", type=float, default=3000)
    parser.add_argument("--steady-read-seconds", type=int, default=0, choices=range(121), metavar="0..120")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = urlparse(args.base_url)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not url.port
        or url.port == 8000
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        parser.error("use a separate loopback HTTP test server with an explicit port other than 8000")
    if not math.isfinite(args.max_p95_ms) or args.max_p95_ms <= 0:
        parser.error("max-p95-ms must be finite and positive")
    batch = uuid4().hex[:12]
    # Успешная подготовка/вход вне замера: нагрузка имитирует уже вошедших пользователей,
    # а ограничение параллельных попыток PIN остаётся включённым.
    tokens = [prepare_employee(args.base_url, batch, index) for index in range(args.users)]
    start = Barrier(args.users)
    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.users) as executor:
        futures = [
            executor.submit(
                exercise, args.base_url, token, args.rounds, args.read_rounds, args.steady_read_seconds, start
            )
            for token in tokens
        ]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - began
    samples = [sample for result in results for sample in result["samples"]]
    latencies = [sample["ms"] for sample in samples]
    errors = [result["error"] for result in results if result["error"]]
    p95 = percentile(latencies, 0.95)
    report = {
        "users": args.users,
        "rounds_per_user": args.rounds,
        "read_rounds_per_user": args.read_rounds,
        "steady_read_seconds": args.steady_read_seconds,
        "requests": len(samples),
        "completed_runs": sum(result["completed"] for result in results),
        "duration_seconds": round(elapsed, 2),
        "requests_per_second": round(len(samples) / elapsed, 2),
        "latency_ms": {
            "median": round(statistics.median(latencies), 2) if latencies else None,
            "p95": p95,
            "p99": percentile(latencies, 0.99),
            "max": round(max(latencies), 2) if latencies else None,
        },
        "http_errors": sum(sample["status"] == 0 or sample["status"] >= 400 for sample in samples),
        "errors": errors,
        "max_p95_ms": args.max_p95_ms,
        "passed": not errors and p95 is not None and p95 <= args.max_p95_ms,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
