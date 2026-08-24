"""Route-manifest generation, sort stability, and identity-warning disposition."""

from __future__ import annotations

import json
import os

from scripts import gen_route_manifest as manifest


def test_compare_operations_sort_only_is_not_a_route_change():
    committed = [
        "GET /api/oaa/memory",
        "GET /api/canon/reserve-blocks/manifest",
        "POST /api/oaa/memory",
        "POST /api/canon/reserve-blocks/anchor",
    ]
    generated = sorted(committed)
    diff = manifest.compare_operations(committed, generated)
    assert diff.match is False
    assert diff.sort_only is True
    assert diff.added == ()
    assert diff.removed == ()
    report = manifest.format_manifest_diff(diff)
    assert "no routes added or removed" in report
    assert "lexicographically sorted" in report


def test_compare_operations_refuses_silent_removal():
    committed = ["GET /health", "POST /ledger/attest"]
    generated = ["GET /health"]
    diff = manifest.compare_operations(committed, generated)
    assert diff.removed == ("POST /ledger/attest",)
    assert diff.added == ()
    assert diff.sort_only is False
    report = manifest.format_manifest_diff(diff)
    assert "REFUSING silent route removal" in report
    assert "POST /ledger/attest" in report


def test_compare_operations_explains_additions():
    committed = ["GET /health"]
    generated = ["GET /health", "POST /api/canon/reserve-blocks/anchor"]
    diff = manifest.compare_operations(committed, generated)
    assert diff.added == ("POST /api/canon/reserve-blocks/anchor",)
    assert diff.removed == ()
    report = manifest.format_manifest_diff(diff)
    assert "POST /api/canon/reserve-blocks/anchor" in report
    assert "not in the committed manifest" in report


def test_compare_operations_match():
    ops = ["GET /health", "POST /ledger/attest"]
    diff = manifest.compare_operations(ops, ops)
    assert diff.match is True
    assert diff.sort_only is False
    assert diff.added == ()
    assert diff.removed == ()


def test_identity_unset_in_ci_is_expected_and_unattested():
    result = manifest.classify_identity_api_base(
        configured=False,
        in_ci=True,
        warning_observed=True,
    )
    assert result.disposition == "expected"
    assert result.production_identity_health == "unattested"
    text = manifest.format_identity_classification(result)
    assert "disposition=expected" in text
    assert "production identity health=unattested" in text
    assert "does not attest production identity health" in text
    assert "health=healthy" not in text


def test_identity_set_in_ci_is_misconfigured_and_unattested():
    result = manifest.classify_identity_api_base(
        configured=True,
        in_ci=True,
        warning_observed=False,
    )
    assert result.disposition == "misconfigured"
    assert result.production_identity_health == "unattested"
    text = manifest.format_identity_classification(result)
    assert "disposition=misconfigured" in text
    assert "Do not treat CI as production identity health" in text


def test_identity_unset_outside_ci_is_degraded_and_unattested():
    result = manifest.classify_identity_api_base(
        configured=False,
        in_ci=False,
        warning_observed=True,
    )
    assert result.disposition == "degraded"
    assert result.production_identity_health == "unattested"


def test_identity_configured_helper_reads_aliases(monkeypatch):
    monkeypatch.delenv("IDENTITY_API_BASE", raising=False)
    monkeypatch.delenv("IDENTITY_SERVICE_URL", raising=False)
    assert manifest.identity_api_base_configured() is False
    monkeypatch.setenv("IDENTITY_SERVICE_URL", "https://example.invalid")
    assert manifest.identity_api_base_configured() is True


def test_committed_manifest_matches_generated_openapi():
    os.environ.setdefault("LEDGER_ALLOW_EPHEMERAL", "true")
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/test_route_manifest.db")
    os.environ.setdefault("LEDGER_DATA_DIR", "/tmp")
    generated, identity = manifest.load_app_operations()
    committed = manifest.load_committed_operations()
    diff = manifest.compare_operations(committed, generated)
    assert diff.removed == (), f"silent route removal: {diff.removed}"
    assert diff.match, manifest.format_manifest_diff(diff)
    assert generated == sorted(generated)
    committed_doc = json.loads(manifest.MANIFEST.read_text(encoding="utf-8"))
    assert committed_doc["operation_count"] == len(generated)
    assert committed_doc["operations"] == generated
    assert identity.production_identity_health == "unattested"
    assert identity.disposition in {"expected", "degraded", "misconfigured"}


def test_check_mode_reports_identity_without_claiming_health(capsys, monkeypatch):
    monkeypatch.delenv("IDENTITY_API_BASE", raising=False)
    monkeypatch.delenv("IDENTITY_SERVICE_URL", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    code = manifest.main(["--check"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert code == 0
    assert "production identity health=unattested" in combined
    assert "does not attest production identity health" in combined
    assert "production identity health=healthy" not in combined
    assert "production identity is healthy" not in combined.lower()
