"""Progress events (stage started, safety check, rate-limit wait, stage done).

The server streams them to the browser; the CLI prints them. Whoever runs the
pipeline picks the listener with `listen()`; without one, events print to stdout.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

Listener = Callable[[dict], None]

_listener: ContextVar[Listener | None] = ContextVar("listener", default=None)


def emit(type: str, **fields) -> None:
    (_listener.get() or _print)({"type": type, **fields})


@contextmanager
def listen(fn: Listener):
    token = _listener.set(fn)
    try:
        yield
    finally:
        _listener.reset(token)


def _print(event: dict) -> None:
    kind = event["type"]
    if kind == "stage_start":
        print(f"  {event['stage']:<11} {event['model']:<22} ", end="", flush=True)
    elif kind == "wait":
        print(f"[rate limited on {event['model']}, waiting {event['seconds']:.0f}s] ", end="", flush=True)
    elif kind == "stage_done":
        print(f"done {event['seconds']:.1f}s", flush=True)
