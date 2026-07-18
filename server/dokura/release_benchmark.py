from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


LIMITS = {
    "catalog_p95_ms": 500.0,
    "cover_first_screen_p95_ms": 1_000.0,
    "preview_first_byte_p95_ms": 1_000.0,
    "preview_complete_p95_ms": 2_000.0,
    "original_first_byte_p95_ms": 1_000.0,
    "original_complete_p95_ms": 3_000.0,
    "rating_p95_ms": 1_000.0,
    "idle_rss_mib": 300.0,
    "peak_rss_mib": 1_536.0,
    "rss_growth_percent": 10.0,
    "scan_seconds": 600.0,
}


def percentile(values: list[float], percent: float = 95.0) -> float:
    if not values:
        raise ValueError("百分位数至少需要一个样本")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)]


@dataclass(frozen=True, slots=True)
class Timing:
    first_byte_ms: float
    complete_ms: float


class HttpProbe:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor())

    def login(self, password: str) -> None:
        response, _ = self.request(
            "/api/v1/auth/login", method="POST",
            body={"username": "admin", "password": password},
        )
        if response.get("username") != "admin":
            raise RuntimeError("登录响应无效")

    def request(
        self, path: str, *, method: str = "GET", body: dict[str, object] | None = None,
    ) -> tuple[dict[str, object] | bytes, Timing]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if method not in {"GET", "HEAD"}:
            headers["Origin"] = self.base_url.rstrip("/")
        request = Request(urljoin(self.base_url, path.lstrip("/")), data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                first = response.read(64 * 1024)
                first_byte = time.perf_counter()
                payload = first + response.read()
                completed = time.perf_counter()
                content_type = response.headers.get_content_type()
        except HTTPError as exc:
            detail = exc.read(1_024).decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} 返回 HTTP {exc.code}: {detail}") from exc
        timing = Timing((first_byte - started) * 1_000, (completed - started) * 1_000)
        if content_type == "application/json":
            return json.loads(payload), timing
        return payload, timing


def process_sample(pid: int) -> dict[str, int]:
    root = Path("/proc") / str(pid)
    status = {}
    for line in (root / "status").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
    return {
        "timestamp_ns": time.time_ns(),
        "rss_kib": int(status["VmRSS"].split()[0]),
        "threads": int(status["Threads"]),
        "file_descriptors": len(list((root / "fd").iterdir())),
    }


class ResourceSampler:
    def __init__(self, pid: int, interval: float = 5.0) -> None:
        self.pid = pid
        self.interval = interval
        self.samples: list[dict[str, int]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dokura-release-resource-sampler")

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples.append(process_sample(self.pid))
            self._stop.wait(self.interval)


def resource_summary(samples: list[dict[str, int]], duration: float) -> dict[str, float | int]:
    if not samples:
        raise ValueError("没有进程资源样本")
    window = max(1, round(len(samples) * min(600.0, duration) / max(duration, 1.0)))
    first = statistics.median(item["rss_kib"] for item in samples[:window])
    last = statistics.median(item["rss_kib"] for item in samples[-window:])
    return {
        "idle_rss_mib": samples[0]["rss_kib"] / 1024,
        "peak_rss_mib": max(item["rss_kib"] for item in samples) / 1024,
        "rss_growth_percent": (last - first) * 100 / max(first, 1),
        "file_descriptors_min": min(item["file_descriptors"] for item in samples),
        "file_descriptors_max": max(item["file_descriptors"] for item in samples),
        "threads_min": min(item["threads"] for item in samples),
        "threads_max": max(item["threads"] for item in samples),
        "sample_count": len(samples),
    }


def hardware() -> dict[str, object]:
    memory_kib = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            memory_kib = int(line.split()[1])
            break
    return {
        "platform": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "logical_cpus": os.cpu_count(),
        "memory_gib": round(memory_kib / 1024 / 1024, 2),
    }


def benchmark(args: argparse.Namespace) -> dict[str, object]:
    probe = HttpProbe(args.base_url, args.timeout)
    probe.login(args.password)
    catalog_paths = {
        "list": "/api/v1/catalog?path=&page=1&per_page=50&sort=name&direction=asc",
        "search": "/api/v1/catalog?path=&page=1&per_page=50&query=caf%C3%A9&scope=recursive",
        "filter": "/api/v1/catalog?path=&page=1&per_page=50&rating_min=3&rating_max=5&scope=recursive",
        "sort": "/api/v1/catalog?path=&page=1&per_page=50&sort=modified&direction=desc&scope=recursive",
    }
    for path in catalog_paths.values():
        probe.request(path)
    catalog_p95 = {
        name: percentile([probe.request(path)[1].complete_ms for _ in range(args.requests)])
        for name, path in catalog_paths.items()
    }
    measurements: dict[str, float] = {
        "catalog_p95_ms": max(catalog_p95.values()),
        **{f"catalog_{name}_p95_ms": value for name, value in catalog_p95.items()},
    }

    cases = json.loads(args.cases.read_text()) if args.cases else {}
    for name, limit_name in (
        ("covers", "cover_first_screen_p95_ms"),
        ("previews", "preview_complete_p95_ms"),
        ("originals", "original_complete_p95_ms"),
    ):
        urls = cases.get(name, [])
        if not urls:
            continue
        timings = [probe.request(urls[index % len(urls)])[1] for index in range(args.image_requests)]
        measurements[limit_name] = percentile([item.complete_ms for item in timings])
        if name in {"previews", "originals"}:
            measurements[f"{name[:-1]}_first_byte_p95_ms"] = percentile([item.first_byte_ms for item in timings])

    file_id = cases.get("rating_file_id")
    if file_id:
        timings = [
            probe.request(f"/api/v1/files/{file_id}/rating", method="PUT", body={"rating": index % 6})[1].complete_ms
            for index in range(args.image_requests)
        ]
        measurements["rating_p95_ms"] = percentile(timings)

    resources = None
    scan_runs: list[float] = []
    if args.pid:
        idle_samples = []
        idle_deadline = time.monotonic() + args.idle_seconds
        while time.monotonic() < idle_deadline:
            idle_samples.append(process_sample(args.pid))
            time.sleep(min(args.sample_interval, max(0, idle_deadline - time.monotonic())))
        if not idle_samples:
            idle_samples.append(process_sample(args.pid))
        end = time.monotonic() + args.duration
        active_scan_id = None
        active_scan_started = None
        if args.scan:
            probe.request("/api/v1/admin/scan", method="POST")
        with ResourceSampler(args.pid, args.sample_interval) as sampler:
            index = 0
            mixed_catalog = {name: [] for name in catalog_paths}
            task_queue_samples = []
            recorded_scan_ids: set[str] = set()
            while time.monotonic() < end:
                operation = tuple(catalog_paths)[index % len(catalog_paths)]
                mixed_catalog[operation].append(probe.request(catalog_paths[operation])[1].complete_ms)
                index += 1
                if args.scan:
                    status, _ = probe.request("/api/v1/admin/scan")
                    tasks, _ = probe.request("/api/v1/admin/tasks")
                    task_queue_samples.append(tasks["waiting_count"])
                    scan_id = status.get("id")
                    if status.get("status") == "running" and scan_id != active_scan_id:
                        active_scan_id = scan_id
                        active_scan_started = time.monotonic()
                    elif active_scan_id == scan_id and active_scan_started is not None and status.get("status") in {"completed", "partial", "failed"}:
                        scan_runs.append(time.monotonic() - active_scan_started)
                        active_scan_id = None
                        active_scan_started = None
                        probe.request("/api/v1/admin/scan", method="POST")
                    elif scan_id and scan_id not in recorded_scan_ids and status.get("status") in {"completed", "partial", "failed"}:
                        started_at, completed_at = status.get("started_at"), status.get("completed_at")
                        if started_at and completed_at:
                            scan_runs.append((datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds())
                            recorded_scan_ids.add(scan_id)
                        probe.request("/api/v1/admin/scan", method="POST")
                if cases.get("originals") and index % 5 == 0:
                    probe.request(cases["originals"][index % len(cases["originals"])])
        resources = resource_summary(sampler.samples, args.duration)
        resources["idle_rss_mib"] = statistics.median(item["rss_kib"] for item in idle_samples) / 1024
        if task_queue_samples:
            resources["task_queue_min"] = min(task_queue_samples)
            resources["task_queue_max"] = max(task_queue_samples)
        measurements.update({key: value for key, value in resources.items() if key in LIMITS})
        scan_ratios = {}
        for name, samples in mixed_catalog.items():
            if not samples:
                continue
            measurements[f"scan_catalog_{name}_p95_ms"] = percentile(samples)
            ratio = measurements[f"scan_catalog_{name}_p95_ms"] / max(catalog_p95[name], 0.001)
            measurements[f"scan_catalog_{name}_ratio"] = ratio
            scan_ratios[name] = ratio
        if scan_ratios:
            measurements["scan_catalog_p95_ms"] = max(
                measurements[f"scan_catalog_{name}_p95_ms"] for name in scan_ratios
            )
            measurements["scan_catalog_ratio"] = max(scan_ratios.values())
        if scan_runs:
            measurements["scan_seconds"] = max(scan_runs)

    failures = {
        name: {"actual": round(value, 3), "limit": LIMITS[name]}
        for name, value in measurements.items() if name in LIMITS and value > LIMITS[name]
    }
    if args.scan and not scan_runs:
        failures["scan_runs"] = {"actual": 0, "limit": "至少完成一次"}
    if measurements.get("scan_catalog_ratio", 0) > 2:
        failures["scan_catalog_ratio"] = {
            "actual": round(measurements["scan_catalog_ratio"], 3), "limit": 2.0,
        }
    return {
        "result": "failed" if failures else "passed",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hardware": hardware(),
        "environment": {
            "network": args.network, "storage": args.storage, "dataset": args.dataset,
            "version": args.version, "cache_condition": args.cache_condition,
        },
        "parameters": {
            "requests_per_catalog_operation": args.requests, "image_requests": args.image_requests,
            "stability_seconds": args.duration if args.pid else 0,
            "idle_seconds": args.idle_seconds if args.pid else 0,
        },
        "measurements": {key: round(value, 3) for key, value in measurements.items()},
        "resources": resources,
        "scan_runs_seconds": [round(value, 3) for value in scan_runs],
        "limits": LIMITS,
        "failures": failures,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dokura 阶段 9 HTTP 性能与资源稳定性验收")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", default="admin")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--scan", action="store_true", help="稳定性期间反复执行完整扫描并记录混合负载")
    parser.add_argument("--allow-failures", action="store_true", help="仅供 smoke 收集失败报告，不改变 result 字段")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--image-requests", type=int, default=20)
    parser.add_argument("--duration", type=float, default=3_600)
    parser.add_argument("--sample-interval", type=float, default=5)
    parser.add_argument("--idle-seconds", type=float, default=300)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--network", required=True)
    parser.add_argument("--storage", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--cache-condition", choices=("cold", "warm", "mixed"), required=True)
    args = parser.parse_args(argv)
    if args.requests < 1 or args.image_requests < 1 or args.duration <= 0 or args.sample_interval <= 0 or args.idle_seconds < 0:
        parser.error("请求数、持续时间和采样间隔必须大于 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = benchmark(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"result": report["result"], "report": str(args.report), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["result"] == "passed" or args.allow_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
