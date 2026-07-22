"""Unit tests for `infrastructure.operations.metrics`: counters,
gauges, histograms, the `/metrics` render format, and disabled behavior.
No Prometheus server is required - `prometheus_client` only maintains
in-process state until scraped."""

from __future__ import annotations

from prometheus_client import CollectorRegistry

from stock_research_core.infrastructure.operations.metrics import (
    NoOpMetrics,
    PrometheusMetrics,
    normalize_route,
    status_class,
)


def _metrics() -> PrometheusMetrics:
    return PrometheusMetrics(registry=CollectorRegistry())


class TestPrometheusMetricsCounters:
    def test_http_requests_total_increments(self) -> None:
        metrics = _metrics()
        metrics.increment_counter(
            "finquest_http_requests_total", labels={"method": "GET", "route": "/api/v1/portfolios", "status_class": "2xx"}
        )
        body, _ = metrics.render_latest()
        assert b'finquest_http_requests_total{method="GET",route="/api/v1/portfolios",status_class="2xx"} 1.0' in body

    def test_job_creation_counter(self) -> None:
        metrics = _metrics()
        metrics.increment_counter("finquest_jobs_created_total", labels={"job_type": "PORTFOLIO_VALUATION", "queue": "finquest.portfolio"})
        body, _ = metrics.render_latest()
        assert b"finquest_jobs_created_total" in body

    def test_job_completion_counter(self) -> None:
        metrics = _metrics()
        metrics.increment_counter("finquest_jobs_completed_total", labels={"job_type": "PORTFOLIO_VALUATION", "queue": "finquest.portfolio"})
        body, _ = metrics.render_latest()
        assert b"finquest_jobs_completed_total" in body

    def test_job_failure_counter(self) -> None:
        metrics = _metrics()
        metrics.increment_counter("finquest_jobs_failed_total", labels={"job_type": "PORTFOLIO_VALUATION", "queue": "finquest.portfolio"})
        body, _ = metrics.render_latest()
        assert b"finquest_jobs_failed_total" in body

    def test_retry_counter(self) -> None:
        metrics = _metrics()
        metrics.increment_counter("finquest_job_retries_total", labels={"job_type": "TRACKED_MARKET_REFRESH", "queue": "finquest.market"})
        body, _ = metrics.render_latest()
        assert b"finquest_job_retries_total" in body

    def test_unknown_metric_name_is_ignored_not_raised(self) -> None:
        metrics = _metrics()
        metrics.increment_counter("not_a_real_metric")  # must not raise


class TestPrometheusMetricsHistograms:
    def test_http_request_duration_histogram(self) -> None:
        metrics = _metrics()
        metrics.observe_histogram("finquest_http_request_duration_seconds", 0.05, labels={"method": "GET", "route": "/health"})
        body, _ = metrics.render_latest()
        assert b"finquest_http_request_duration_seconds_bucket" in body

    def test_job_queue_delay_histogram(self) -> None:
        metrics = _metrics()
        metrics.observe_histogram("finquest_job_queue_delay_seconds", 2.5, labels={"job_type": "PORTFOLIO_VALUATION", "queue": "finquest.portfolio"})
        body, _ = metrics.render_latest()
        assert b"finquest_job_queue_delay_seconds_bucket" in body

    def test_time_operation_context_manager_records_a_duration(self) -> None:
        metrics = _metrics()
        with metrics.time_operation("finquest_job_duration_seconds", labels={"job_type": "PORTFOLIO_VALUATION"}):
            pass
        body, _ = metrics.render_latest()
        assert b"finquest_job_duration_seconds_count" in body


class TestPrometheusMetricsGauges:
    def test_jobs_in_progress_gauge(self) -> None:
        metrics = _metrics()
        metrics.set_gauge("finquest_jobs_in_progress", 3, labels={"job_type": "PORTFOLIO_VALUATION"})
        body, _ = metrics.render_latest()
        assert b"finquest_jobs_in_progress" in body


class TestMetricsFormat:
    def test_render_latest_returns_prometheus_text_format(self) -> None:
        metrics = _metrics()
        metrics.increment_counter("finquest_jobs_created_total", labels={"job_type": "X", "queue": "finquest.default"})
        body, content_type = metrics.render_latest()
        assert content_type.startswith("text/plain")
        assert isinstance(body, bytes)

    def test_no_high_cardinality_labels_registered(self) -> None:
        # Structural guarantee: no metric here accepts a job_id, learner_id,
        # ticker, portfolio_id, or correlation_id label - only the fixed,
        # bounded label sets declared in PrometheusMetrics.__init__.
        metrics = _metrics()
        forbidden_label_names = {"job_id", "learner_id", "ticker", "portfolio_id", "correlation_id"}
        for collector in metrics.registry._collector_to_names:  # noqa: SLF001 - structural test only
            label_names = set(getattr(collector, "_labelnames", ()))
            assert not (label_names & forbidden_label_names), f"{collector} exposes a high-cardinality label"


class TestNoOpMetrics:
    def test_every_call_is_a_safe_no_op(self) -> None:
        metrics = NoOpMetrics()
        metrics.increment_counter("anything")
        metrics.set_gauge("anything", 1)
        metrics.observe_histogram("anything", 1.0)
        with metrics.time_operation("anything"):
            pass


class TestNormalizeRouteAndStatusClass:
    def test_normalize_route_handles_none(self) -> None:
        assert normalize_route(None) == "unknown"

    def test_normalize_route_passes_through_template(self) -> None:
        assert normalize_route("/api/v1/portfolios/{portfolio_id}") == "/api/v1/portfolios/{portfolio_id}"

    def test_status_class_buckets_correctly(self) -> None:
        assert status_class(200) == "2xx"
        assert status_class(404) == "4xx"
        assert status_class(503) == "5xx"
