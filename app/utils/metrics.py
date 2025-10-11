"""Shared Prometheus metrics helpers used across the Harmony backend."""

from __future__ import annotations

from collections.abc import Sequence
from threading import RLock
from typing import Final

try:  # pragma: no cover - exercised indirectly in tests
    from prometheus_client import CollectorRegistry, Counter, Histogram
except ModuleNotFoundError:  # pragma: no cover - fallback for offline environments

    class Sample:
        __slots__ = ("name", "labels", "value")

        def __init__(self, name: str, labels: dict[str, str], value: float) -> None:
            self.name = name
            self.labels = labels
            self.value = value

    class _MetricFamily:
        __slots__ = ("samples",)

        def __init__(self, samples: list[Sample]) -> None:
            self.samples = samples

    class CollectorRegistry:  # type: ignore[override]
        def __init__(self) -> None:
            self._metrics: list[object] = []

        def register(self, metric: object) -> None:
            self._metrics.append(metric)

        def collect(self) -> list[_MetricFamily]:
            families: list[_MetricFamily] = []
            for metric in self._metrics:
                collect = getattr(metric, "_collect", None)
                if collect is None:
                    continue
                families.append(_MetricFamily(collect()))
            return families

    class _CounterChild:
        __slots__ = ("_parent", "_labels")

        def __init__(self, parent: "Counter", labels: tuple[str, ...]) -> None:
            self._parent = parent
            self._labels = labels

        def inc(self, amount: int = 1) -> None:
            self._parent._values[self._labels] = (
                self._parent._values.get(self._labels, 0.0) + amount
            )

    class Counter:  # type: ignore[override]
        def __init__(
            self,
            name: str,
            documentation: str,
            labelnames: tuple[str, ...] | tuple[str, ...] = (),
            registry: CollectorRegistry | None = None,
        ) -> None:
            self._name = name
            self._labelnames = tuple(labelnames or ())
            self._values: dict[tuple[str, ...], float] = {}
            if registry is not None:
                registry.register(self)

        def labels(self, *values: str, **kwargs: str) -> _CounterChild:
            if kwargs:
                if values:
                    raise ValueError("cannot mix positional and keyword label values")
                ordered = tuple(str(kwargs[name]) for name in self._labelnames)
                return _CounterChild(self, ordered)
            if len(values) != len(self._labelnames):
                raise ValueError("label value count does not match declaration")
            return _CounterChild(self, tuple(str(v) for v in values))

        def _collect(self) -> list[Sample]:
            samples: list[Sample] = []
            for labels, value in self._values.items():
                mapping = {name: str(label) for name, label in zip(self._labelnames, labels)}
                samples.append(Sample(self._name, mapping, float(value)))
            return samples

    class _HistogramChild:
        __slots__ = ("_parent", "_labels")

        def __init__(self, parent: "Histogram", labels: tuple[str, ...]) -> None:
            self._parent = parent
            self._labels = labels

        def observe(self, value: float) -> None:
            store = self._parent._values.setdefault(self._labels, {"count": 0.0, "sum": 0.0})
            store["count"] += 1.0
            store["sum"] += float(value)

    class Histogram:  # type: ignore[override]
        def __init__(
            self,
            name: str,
            documentation: str,
            labelnames: tuple[str, ...] | tuple[str, ...] = (),
            buckets: tuple[float, ...] | None = None,
            registry: CollectorRegistry | None = None,
        ) -> None:
            self._name = name
            self._labelnames = tuple(labelnames or ())
            self._values: dict[tuple[str, ...], dict[str, float]] = {}
            if registry is not None:
                registry.register(self)

        def labels(self, *values: str, **kwargs: str) -> _HistogramChild:
            if kwargs:
                if values:
                    raise ValueError("cannot mix positional and keyword label values")
                ordered = tuple(str(kwargs[name]) for name in self._labelnames)
                return _HistogramChild(self, ordered)
            if len(values) != len(self._labelnames):
                raise ValueError("label value count does not match declaration")
            return _HistogramChild(self, tuple(str(v) for v in values))

        def observe(self, value: float) -> None:
            self.labels().observe(value)

        def _collect(self) -> list[Sample]:
            samples: list[Sample] = []
            for labels, data in self._values.items():
                mapping = {name: str(label) for name, label in zip(self._labelnames, labels)}
                samples.append(Sample(f"{self._name}_count", mapping, data.get("count", 0.0)))
                samples.append(Sample(f"{self._name}_sum", mapping, data.get("sum", 0.0)))
                samples.append(
                    Sample(
                        f"{self._name}_bucket",
                        {**mapping, "le": "+Inf"},
                        data.get("count", 0.0),
                    )
                )
            return samples


__all__ = [
    "get_registry",
    "counter",
    "histogram",
    "reset_registry",
]


_DEFAULT_BUCKETS: Final[tuple[float, ...]] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)

_registry_lock = RLock()
_registry: CollectorRegistry = CollectorRegistry()
_counters: dict[tuple[str, tuple[str, ...]], Counter] = {}
_histograms: dict[tuple[str, tuple[str, ...]], Histogram] = {}


def get_registry() -> CollectorRegistry:
    """Return the shared Prometheus registry used for Harmony metrics."""

    return _registry


def reset_registry() -> None:
    """Reset the registry and cached metric objects (used in tests)."""

    global _registry
    with _registry_lock:
        _registry = CollectorRegistry()
        _counters.clear()
        _histograms.clear()


def counter(
    name: str,
    documentation: str,
    *,
    label_names: Sequence[str] | None = None,
) -> Counter:
    """Return (or create) a labelled Prometheus counter registered globally."""

    labels = tuple(label_names or ())
    cache_key = (name, labels)
    with _registry_lock:
        metric = _counters.get(cache_key)
        if metric is None:
            metric = Counter(
                name,
                documentation,
                labelnames=labels,
                registry=_registry,
            )
            _counters[cache_key] = metric
        return metric


def histogram(
    name: str,
    documentation: str,
    *,
    label_names: Sequence[str] | None = None,
    buckets: Sequence[float] | None = None,
) -> Histogram:
    """Return (or create) a labelled Prometheus histogram."""

    labels = tuple(label_names or ())
    cache_key = (name, labels)
    with _registry_lock:
        metric = _histograms.get(cache_key)
        if metric is None:
            metric = Histogram(
                name,
                documentation,
                labelnames=labels,
                buckets=tuple(buckets or _DEFAULT_BUCKETS),
                registry=_registry,
            )
            _histograms[cache_key] = metric
        return metric
