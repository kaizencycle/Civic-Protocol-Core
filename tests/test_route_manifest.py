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


def test_check_fails_when_generator_owned_metadata_is_stale():
    operations = ["GET /health", "POST /ledger/attest"]
    generated = manifest.build_manifest(operations)
    committed = dict(generated)
    committed["operation_count"] = 99
    committed["note"] = "stale note"
    diff = manifest.compare_committed_to_generated(
        committed,
        manifest.serialize_manifest(committed),
        generated,
    )
    assert diff.operations.match is True
    assert diff.match is False
    assert "operation_count" in diff.metadata_mismatch
    assert "note" in diff.metadata_mismatch
    report = manifest.format_document_diff(diff)
    assert "operation_count" in report
    assert "note" in report
    assert "build_manifest(operations)" in report


def test_check_fails_when_serialization_differs_but_parsed_values_match():
    operations = ["GET /health"]
    generated = manifest.build_manifest(operations)
    compact = json.dumps(generated)
    diff = manifest.compare_committed_to_generated(generated, compact, generated)
    assert diff.operations.match is True
    assert diff.metadata_mismatch == ()
    assert diff.serialization_match is False
    assert diff.match is False
    assert "serialization differs" in manifest.format_document_diff(diff)


def test_encode_github_workflow_value_preserves_multiline_annotations():
    raw = "REFUSING silent route removal.\n  - POST /ledger/attest\n  - GET /health"
    encoded = manifest.encode_github_workflow_value(raw)
    assert "\n" not in encoded
    assert "%0A" in encoded
    assert encoded.count("%0A") == 2
    assert "POST /ledger/attest" in encoded.replace("%0A", "\n")


def test_emit_status_encodes_newlines_for_github_actions(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    report = "Generated OpenAPI has 1 operation(s) not in the committed manifest:\n  - POST /api/canon/reserve-blocks/anchor"
    manifest.emit_status(report, level="error")
    captured = capsys.readouterr()
    annotation = [line for line in captured.err.splitlines() if line.startswith("::error::")]
    assert len(annotation) == 1
    assert "\n" not in annotation[0][len("::error::"):]
    assert "%0A  - POST /api/canon/reserve-blocks/anchor" in annotation[0]
    assert "POST /api/canon/reserve-blocks/anchor" in captured.err


def test_document_diff_keeps_named_operation_changes():
    committed = manifest.build_manifest(["GET /health", "POST /ledger/attest"])
    generated = manifest.build_manifest(["GET /health"])
    diff = manifest.compare_committed_to_generated(
        committed,
        manifest.serialize_manifest(committed),
        generated,
    )
    assert diff.operations.removed == ("POST /ledger/attest",)
    report = manifest.format_document_diff(diff)
    assert "REFUSING silent route removal" in report
    assert "POST /ledger/attest" in report
    assert "operation_count" in diff.metadata_mismatch
    assert "path_count" in diff.metadata_mismatch


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
    committed_doc = manifest.load_committed_manifest()
    committed_text = manifest.MANIFEST.read_text(encoding="utf-8")
    generated_doc = manifest.build_manifest(generated)
    diff = manifest.compare_committed_to_generated(
        committed_doc, committed_text, generated_doc
    )
    assert diff.operations.removed == (), f"silent route removal: {diff.operations.removed}"
    assert diff.match, manifest.format_document_diff(diff)
    assert generated == sorted(generated)
    assert committed_doc == generated_doc
    assert committed_text == manifest.serialize_manifest(generated_doc)
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
