from __future__ import annotations

from src.tools.evidence_bundle_context import (
    _resolve_bundle,
    get_current_bundle,
    use_bundle,
)


def test_get_current_bundle_default_none() -> None:
    assert get_current_bundle() is None


def test_use_bundle_sets_and_resets() -> None:
    bundle = {"prices": {}}

    with use_bundle(bundle):
        assert get_current_bundle() is bundle

    assert get_current_bundle() is None


def test_nested_use_bundle_restores_outer() -> None:
    outer_bundle = {"prices": {}}
    inner_bundle = {"fundamentals": {}}

    with use_bundle(outer_bundle):
        assert get_current_bundle() is outer_bundle
        with use_bundle(inner_bundle):
            assert get_current_bundle() is inner_bundle
        assert get_current_bundle() is outer_bundle

    assert get_current_bundle() is None


def test_resolve_bundle_explicit_arg_wins() -> None:
    explicit_bundle = {"x": 1}

    with use_bundle({"y": 2}):
        assert _resolve_bundle(explicit_bundle) is explicit_bundle


def test_resolve_bundle_falls_back_to_contextvar() -> None:
    bundle = {"prices": {}}

    with use_bundle(bundle):
        assert _resolve_bundle(None) is bundle
