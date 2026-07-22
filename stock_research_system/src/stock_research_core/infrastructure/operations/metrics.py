"""Prometheus-backed `MetricsPort` implementation.

Every metric name and label set here is the fixed, low-cardinality
vocabulary from the Phase 11 spec - never a raw URL path, job ID,
learner ID, ticker, portfolio ID, or correlation ID as a label. Works
without a running Prometheus server or collector: `prometheus_client`
only maintains in-process counters until `/metrics` is scraped.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

_HTTP_REQUEST_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
_JOB_DURATION_BUCKETS = (0.5, 1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600)


class PrometheusMetrics:
    """A single process-wide registry, built once at startup (API or
    worker) and shared by every request/task in that process."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()

        self.http_requests_total = Counter(
            "finquest_http_requests_total", "Total HTTP requests.",
            ["method", "route", "status_class"], registry=self.registry,
        )
        self.http_request_duration_seconds = Histogram(
            "finquest_http_request_duration_seconds", "HTTP request duration in seconds.",
            ["method", "route"], buckets=_HTTP_REQUEST_LATENCY_BUCKETS, registry=self.registry,
        )
        self.http_requests_in_progress = Gauge(
            "finquest_http_requests_in_progress", "HTTP requests currently being handled.",
            ["method", "route"], registry=self.registry,
        )

        self.jobs_created_total = Counter(
            "finquest_jobs_created_total", "Total background jobs created.",
            ["job_type", "queue"], registry=self.registry,
        )
        self.jobs_completed_total = Counter(
            "finquest_jobs_completed_total", "Total background jobs that succeeded.",
            ["job_type", "queue"], registry=self.registry,
        )
        self.jobs_failed_total = Counter(
            "finquest_jobs_failed_total", "Total background jobs that failed (non-retryably).",
            ["job_type", "queue"], registry=self.registry,
        )
        self.job_duration_seconds = Histogram(
            "finquest_job_duration_seconds", "Background job handler execution duration in seconds.",
            ["job_type"], buckets=_JOB_DURATION_BUCKETS, registry=self.registry,
        )
        self.job_queue_delay_seconds = Histogram(
            "finquest_job_queue_delay_seconds", "Delay between a job becoming available and starting execution.",
            ["job_type", "queue"], buckets=_JOB_DURATION_BUCKETS, registry=self.registry,
        )
        self.jobs_in_progress = Gauge(
            "finquest_jobs_in_progress", "Background jobs currently executing.", ["job_type"], registry=self.registry,
        )
        self.job_retries_total = Counter(
            "finquest_job_retries_total", "Total background job retries scheduled.",
            ["job_type", "queue"], registry=self.registry,
        )
        self.job_lock_failures_total = Counter(
            "finquest_job_lock_failures_total", "Total distributed-lock acquisition failures.", registry=self.registry,
        )

        self.tutor_requests_total = Counter(
            "finquest_tutor_requests_total", "Total tutor requests.", ["status"], registry=self.registry,
        )
        self.tutor_refusals_total = Counter(
            "finquest_tutor_refusals_total", "Total tutor guardrail refusals.", registry=self.registry,
        )
        self.tutor_fallbacks_total = Counter(
            "finquest_tutor_fallbacks_total", "Total tutor fallback responses.", registry=self.registry,
        )
        self.retrieval_duration_seconds = Histogram(
            "finquest_retrieval_duration_seconds", "Knowledge retrieval duration in seconds.", registry=self.registry,
        )
        self.retrieval_candidates_returned = Histogram(
            "finquest_retrieval_candidates_returned", "Number of candidates returned per retrieval.",
            buckets=(0, 1, 2, 5, 8, 10, 20, 40), registry=self.registry,
        )

        # -- Phase 12: learning orchestrator (LangGraph learning coach) -----------------------------------------------
        # Bounded, low-cardinality labels only: intent/route/status/action_type -
        # never a learner, thread, run, scenario, or portfolio id, and never a ticker or user message.
        self.learning_coach_runs_total = Counter(
            "finquest_learning_coach_runs_total", "Total learning-coach graph runs, by terminal status.",
            ["status"], registry=self.registry,
        )
        self.learning_coach_run_duration_seconds = Histogram(
            "finquest_learning_coach_run_duration_seconds", "Learning-coach graph run duration in seconds.",
            buckets=_JOB_DURATION_BUCKETS, registry=self.registry,
        )
        self.learning_coach_runs_in_progress = Gauge(
            "finquest_learning_coach_runs_in_progress", "Learning-coach graph runs currently executing or waiting.",
            registry=self.registry,
        )
        self.learning_coach_intents_total = Counter(
            "finquest_learning_coach_intents_total", "Total learning-coach intent classifications, by intent.",
            ["intent"], registry=self.registry,
        )
        self.learning_coach_routes_total = Counter(
            "finquest_learning_coach_routes_total", "Total learning-coach route selections, by route.",
            ["route"], registry=self.registry,
        )
        self.learning_coach_interrupts_total = Counter(
            "finquest_learning_coach_interrupts_total", "Total learning-coach approval interrupts raised.",
            registry=self.registry,
        )
        self.learning_coach_resumes_total = Counter(
            "finquest_learning_coach_resumes_total", "Total learning-coach run resumes, by learner decision.",
            ["decision"], registry=self.registry,
        )
        self.learning_coach_actions_total = Counter(
            "finquest_learning_coach_actions_total", "Total learning-coach actions executed, by action type.",
            ["action_type"], registry=self.registry,
        )
        self.learning_coach_failures_total = Counter(
            "finquest_learning_coach_failures_total", "Total learning-coach run failures, by failure code.",
            ["failure_code"], registry=self.registry,
        )
        self.learning_coach_step_count = Histogram(
            "finquest_learning_coach_step_count", "Graph step count per learning-coach run.",
            buckets=(1, 2, 3, 5, 8, 10, 15, 20, 25, 30), registry=self.registry,
        )

        self._counters: dict[str, Counter] = {
            "finquest_http_requests_total": self.http_requests_total,
            "finquest_jobs_created_total": self.jobs_created_total,
            "finquest_jobs_completed_total": self.jobs_completed_total,
            "finquest_jobs_failed_total": self.jobs_failed_total,
            "finquest_job_retries_total": self.job_retries_total,
            "finquest_job_lock_failures_total": self.job_lock_failures_total,
            "finquest_tutor_requests_total": self.tutor_requests_total,
            "finquest_tutor_refusals_total": self.tutor_refusals_total,
            "finquest_tutor_fallbacks_total": self.tutor_fallbacks_total,
            "finquest_learning_coach_runs_total": self.learning_coach_runs_total,
            "finquest_learning_coach_intents_total": self.learning_coach_intents_total,
            "finquest_learning_coach_routes_total": self.learning_coach_routes_total,
            "finquest_learning_coach_interrupts_total": self.learning_coach_interrupts_total,
            "finquest_learning_coach_resumes_total": self.learning_coach_resumes_total,
            "finquest_learning_coach_actions_total": self.learning_coach_actions_total,
            "finquest_learning_coach_failures_total": self.learning_coach_failures_total,
        }
        self._gauges: dict[str, Gauge] = {
            "finquest_jobs_in_progress": self.jobs_in_progress,
            "finquest_http_requests_in_progress": self.http_requests_in_progress,
            "finquest_learning_coach_runs_in_progress": self.learning_coach_runs_in_progress,
        }
        self._histograms: dict[str, Histogram] = {
            "finquest_job_duration_seconds": self.job_duration_seconds,
            "finquest_job_queue_delay_seconds": self.job_queue_delay_seconds,
            "finquest_retrieval_duration_seconds": self.retrieval_duration_seconds,
            "finquest_retrieval_candidates_returned": self.retrieval_candidates_returned,
            "finquest_http_request_duration_seconds": self.http_request_duration_seconds,
            "finquest_learning_coach_run_duration_seconds": self.learning_coach_run_duration_seconds,
            "finquest_learning_coach_step_count": self.learning_coach_step_count,
        }

    # -- MetricsPort -----------------------------------------------

    def increment_counter(self, name: str, *, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        metric = self._counters.get(name)
        if metric is None:
            return
        (metric.labels(**labels) if labels else metric).inc(value)

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        metric = self._gauges.get(name)
        if metric is None:
            return
        (metric.labels(**labels) if labels else metric).set(value)

    def observe_histogram(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        metric = self._histograms.get(name)
        if metric is None:
            return
        (metric.labels(**labels) if labels else metric).observe(value)

    @contextmanager
    def time_operation(self, name: str, *, labels: dict[str, str] | None = None) -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
        finally:
            self.observe_histogram(name, time.monotonic() - start, labels=labels)

    def render_latest(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


class NoOpMetrics:
    """Used when `METRICS_ENABLED=false` - every call is a no-op."""

    def increment_counter(self, name: str, *, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        pass

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        pass

    def observe_histogram(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        pass

    @contextmanager
    def time_operation(self, name: str, *, labels: dict[str, str] | None = None) -> Iterator[None]:
        yield


_NORMALIZED_ROUTE_UNKNOWN = "unknown"


def normalize_route(route_template: str | None) -> str:
    return route_template or _NORMALIZED_ROUTE_UNKNOWN


def status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"
