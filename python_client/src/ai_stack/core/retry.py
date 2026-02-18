"""Bounded retry/backoff helpers for transient operations."""

from __future__ import annotations

import time
from typing import Callable, Iterable, Optional, Tuple, Type, TypeVar

from ai_stack.core.logging import emit_event

T = TypeVar("T")

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.25
DEFAULT_RETRY_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    OSError,
    RuntimeError,
    TimeoutError,
    ConnectionError,
)


def retry_call(
    *,
    operation: str,
    fn: Callable[[], T],
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    retry_on: Iterable[Type[BaseException]] = DEFAULT_RETRY_EXCEPTIONS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """
    Execute `fn` with bounded retries for transient failures.

    Raises the last exception after attempts are exhausted.
    """
    retry_tuple = tuple(retry_on)
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_error: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_tuple as exc:
            last_error = exc
            emit_event(
                "retry.attempt",
                operation=operation,
                attempt=attempt,
                attempts=attempts,
                error=str(exc),
            )
            if attempt >= attempts:
                emit_event(
                    "retry.exhausted",
                    level="error",
                    operation=operation,
                    attempts=attempts,
                    error=str(exc),
                )
                raise
            delay = backoff_seconds * (2 ** (attempt - 1))
            emit_event("retry.sleep", operation=operation, attempt=attempt, delay_seconds=delay)
            sleep_fn(delay)

    # Unreachable in normal flow, but keeps type checker happy.
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_call reached unexpected state")


__all__ = [
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_RETRY_ATTEMPTS",
    "DEFAULT_RETRY_EXCEPTIONS",
    "retry_call",
]
