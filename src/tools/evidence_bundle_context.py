from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator

EvidenceBundle = dict[str, Any]

_CURRENT_BUNDLE: ContextVar[EvidenceBundle | None] = ContextVar(
    "evidence_bundle",
    default=None,
)


def get_current_bundle() -> EvidenceBundle | None:
    return _CURRENT_BUNDLE.get()


def set_current_bundle(bundle: EvidenceBundle | None) -> Token:
    return _CURRENT_BUNDLE.set(bundle)


def reset_current_bundle(token: Token) -> None:
    _CURRENT_BUNDLE.reset(token)


def _resolve_bundle(evidence_bundle: EvidenceBundle | None) -> EvidenceBundle | None:
    if evidence_bundle is not None:
        return evidence_bundle
    return get_current_bundle()


@contextmanager
def use_bundle(bundle: EvidenceBundle | None) -> Iterator[None]:
    token = set_current_bundle(bundle)
    try:
        yield
    finally:
        reset_current_bundle(token)
