#!/usr/bin/env python3
"""Regenerate scripts/expected_routes.json from the app's own OpenAPI.

This is the source of truth for deploy-drift detection: it records every HTTP
operation (METHOD + path) the CURRENT code (origin/main) exposes. The drift
checker compares a live deployment against this manifest. Run after
intentionally adding/removing routes:

    python3 scripts/gen_route_manifest.py

CI selftest (does not write; fails with an explained add/remove/sort report):

    python3 scripts/gen_route_manifest.py --check

The app imports cleanly with ephemeral storage + a throwaway sqlite DB, so this
works in CI without Postgres or a persistent disk.

IDENTITY_API_BASE is intentionally unset here. Import-time RuntimeWarning is
expected CI/local isolation, not production identity drift. This process does
not attest production identity health.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

MANIFEST = Path(__file__).resolve().parent / "expected_routes.json"

HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})

IdentityDisposition = Literal["expected", "degraded", "misconfigured"]
ProductionIdentityHealth = Literal["unattested"]


@dataclass(frozen=True)
class IdentityClassification:
    disposition: IdentityDisposition
    production_identity_health: ProductionIdentityHealth
    configured: bool
    warning_observed: bool
    reason: str


@dataclass(frozen=True)
class ManifestDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    sort_only: bool
    match: bool


@dataclass(frozen=True)
class ManifestDocumentDiff:
    operations: ManifestDiff
    metadata_mismatch: tuple[str, ...]
    serialization_match: bool

    @property
    def match(self) -> bool:
        return (
            self.operations.match
            and not self.metadata_mismatch
            and self.serialization_match
        )


def _assert_never(value: object) -> NoReturn:
    raise AssertionError(f"unhandled variant: {value!r}")


def operations_from_openapi(spec: dict) -> list[str]:
    """Return sorted METHOD path strings from an OpenAPI spec."""
    ops: set[str] = set()
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                ops.add(f"{method.upper()} {path}")
    return sorted(ops)


def identity_api_base_configured(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return bool(
        env.get("IDENTITY_API_BASE", "").strip()
        or env.get("IDENTITY_SERVICE_URL", "").strip()
    )


def classify_identity_api_base(
    *,
    configured: bool,
    in_ci: bool,
    warning_observed: bool,
) -> IdentityClassification:
    """Classify IDENTITY_API_BASE for manifest generation (not a live probe).

    Disposition is about this process, never about production Identity:
    - expected: unset during CI/local OpenAPI generation (isolation by design)
    - degraded: warning observed outside CI — identity-dependent attest paths
      in *this* process would 400; still not a production probe
    - misconfigured: IDENTITY_API_BASE is set in CI selftest, which can look
      like identity health without any production probe having run
    Production identity health is always unattested here.
    """
    if in_ci and configured:
        return IdentityClassification(
            disposition="misconfigured",
            production_identity_health="unattested",
            configured=True,
            warning_observed=warning_observed,
            reason=(
                "IDENTITY_API_BASE is set during CI manifest generation, but this "
                "job does not probe production Identity. Do not treat CI as "
                "production identity health."
            ),
        )
    if warning_observed and not in_ci:
        return IdentityClassification(
            disposition="degraded",
            production_identity_health="unattested",
            configured=configured,
            warning_observed=True,
            reason=(
                "IDENTITY_API_BASE is unset in this process, so lab_source "
                "'terminal'/'identity' attestations would 400 here. This is not a "
                "production identity probe; production identity health is unattested."
            ),
        )
    if not configured:
        return IdentityClassification(
            disposition="expected",
            production_identity_health="unattested",
            configured=False,
            warning_observed=warning_observed,
            reason=(
                "IDENTITY_API_BASE is unset during manifest generation. That is "
                "expected CI/local isolation: OpenAPI is derived from local code "
                "without calling production Identity. This process does not attest "
                "production identity health."
            ),
        )
    return IdentityClassification(
        disposition="expected",
        production_identity_health="unattested",
        configured=True,
        warning_observed=warning_observed,
        reason=(
            "IDENTITY_API_BASE is set locally for development. Manifest generation "
            "still does not probe production Identity and does not attest "
            "production identity health."
        ),
    )


def format_identity_classification(result: IdentityClassification) -> str:
    disposition = result.disposition
    if disposition == "expected":
        label = "expected"
    elif disposition == "degraded":
        label = "degraded"
    elif disposition == "misconfigured":
        label = "misconfigured"
    else:
        _assert_never(disposition)
    return (
        f"IDENTITY_API_BASE disposition={label}; "
        f"production identity health={result.production_identity_health}; "
        f"configured={str(result.configured).lower()}; "
        f"warning_observed={str(result.warning_observed).lower()}. "
        f"{result.reason}"
    )


def encode_github_workflow_value(value: str) -> str:
    """Percent-encode a GitHub Actions workflow-command message.

    Commands are single-line. Unescaped newlines truncate the Checks UI
    annotation at the first newline, dropping named add/remove operations.
    Encode ``%`` first so later ``%0A`` / ``%0D`` sequences stay literal.
    """
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def emit_status(message: str, *, level: Literal["notice", "warning", "error"] = "notice") -> None:
    if os.getenv("GITHUB_ACTIONS") == "true":
        encoded = encode_github_workflow_value(message)
        print(f"::{level}::{encoded}", file=sys.stderr)
    print(message, file=sys.stderr)


def compare_operations(committed: list[str], generated: list[str]) -> ManifestDiff:
    committed_set = set(committed)
    generated_set = set(generated)
    added = tuple(sorted(generated_set - committed_set))
    removed = tuple(sorted(committed_set - generated_set))
    match = committed == generated
    sort_only = (not added and not removed and not match)
    return ManifestDiff(
        added=added,
        removed=removed,
        sort_only=sort_only,
        match=match,
    )


def format_manifest_diff(diff: ManifestDiff) -> str:
    if diff.match:
        return "operations match current code (no additions, removals, or method changes)"
    lines: list[str] = []
    if diff.removed:
        lines.append(
            "REFUSING silent route removal. Committed manifest has "
            f"{len(diff.removed)} operation(s) absent from generated OpenAPI:"
        )
        lines.extend(f"  - {op}" for op in diff.removed)
        lines.append(
            "Confirm each removal is intentional before regenerating and committing."
        )
    if diff.added:
        lines.append(
            "Generated OpenAPI has "
            f"{len(diff.added)} operation(s) not in the committed manifest:"
        )
        lines.extend(f"  - {op}" for op in diff.added)
        lines.append("Run scripts/gen_route_manifest.py and commit the additions.")
    if diff.sort_only:
        lines.append(
            "Operations match as a set (no routes added or removed) but the "
            "committed JSON is not lexicographically sorted. Run "
            "scripts/gen_route_manifest.py and commit (sort-only correction)."
        )
    return "\n".join(lines)


def compare_manifest_documents(committed: dict, generated: dict) -> tuple[str, ...]:
    """Return generator-owned keys whose parsed values differ."""
    keys = set(committed) | set(generated)
    mismatched = [key for key in sorted(keys) if committed.get(key) != generated.get(key)]
    return tuple(mismatched)


def serialize_manifest(document: dict) -> str:
    return json.dumps(document, indent=2) + "\n"


def compare_committed_to_generated(
    committed_doc: dict,
    committed_text: str,
    generated_doc: dict,
) -> ManifestDocumentDiff:
    committed_ops = committed_doc.get("operations", [])
    generated_ops = generated_doc.get("operations", [])
    if not isinstance(committed_ops, list):
        committed_ops = []
    if not isinstance(generated_ops, list):
        generated_ops = []
    operations = compare_operations(
        [op for op in committed_ops if isinstance(op, str)],
        [op for op in generated_ops if isinstance(op, str)],
    )
    metadata_mismatch = tuple(
        key for key in compare_manifest_documents(committed_doc, generated_doc) if key != "operations"
    )
    return ManifestDocumentDiff(
        operations=operations,
        metadata_mismatch=metadata_mismatch,
        serialization_match=committed_text == serialize_manifest(generated_doc),
    )


def format_document_diff(diff: ManifestDocumentDiff) -> str:
    if diff.match:
        return (
            "manifest matches current generator output "
            "(operations and metadata; no additions, removals, or method changes)"
        )
    lines: list[str] = []
    if not diff.operations.match:
        lines.append(format_manifest_diff(diff.operations))
    if diff.metadata_mismatch:
        lines.append(
            "Generator-owned metadata is stale or malformed: "
            + ", ".join(diff.metadata_mismatch)
            + ". Compare the committed document to build_manifest(operations)."
        )
    if diff.operations.match and not diff.metadata_mismatch and not diff.serialization_match:
        lines.append(
            "Committed JSON serialization differs from generator output "
            "(key order or whitespace). Run scripts/gen_route_manifest.py and commit."
        )
    return "\n".join(lines)


def load_committed_manifest(path: Path = MANIFEST) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must be a JSON object")
    operations = document.get("operations")
    if not isinstance(operations, list) or not all(isinstance(op, str) for op in operations):
        raise ValueError(f"{path} operations must be a list of strings")
    return document


def load_app_operations() -> tuple[list[str], IdentityClassification]:
    # Make the app importable in a stateless way (no Postgres, no persistent disk).
    os.environ.setdefault("LEDGER_ALLOW_EPHEMERAL", "true")
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/cpc_manifest_gen.db")
    os.environ.setdefault("LEDGER_DATA_DIR", "/tmp")

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    in_ci = os.getenv("GITHUB_ACTIONS") == "true"
    configured = identity_api_base_configured()
    warning_observed = False

    # Suppress the app's import-time stdout (startup banners). Capture the
    # IDENTITY_API_BASE RuntimeWarning so CI can classify it instead of
    # presenting it as unclassified production identity failure.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        # Import after env defaults: ledger.app.main creates the engine and
        # emits IDENTITY_API_BASE warnings at module import (not circular).
        from ledger.app.main import app  # noqa: E402

        warning_observed = any(
            "IDENTITY_API_BASE" in str(item.message) for item in caught
        )
        operations = operations_from_openapi(app.openapi())

    classification = classify_identity_api_base(
        configured=configured,
        in_ci=in_ci,
        warning_observed=warning_observed,
    )
    return operations, classification


def build_manifest(operations: list[str]) -> dict:
    path_count = len({op.split(" ", 1)[1] for op in operations})
    return {
        "generated_from": "ledger.app.main:app OpenAPI (METHOD + path)",
        "operation_count": len(operations),
        "path_count": path_count,
        "operations": operations,
        "note": (
            "Source of truth for deploy-drift detection. Each entry is "
            "'METHOD /path'. Regenerate with scripts/gen_route_manifest.py "
            "after intentionally adding/removing routes or HTTP methods."
        ),
    }


def write_manifest(operations: list[str]) -> None:
    document = build_manifest(operations)
    MANIFEST.write_text(serialize_manifest(document), encoding="utf-8")
    path_count = document["path_count"]
    print(
        f"wrote {MANIFEST} — {len(operations)} operations across {path_count} paths",
        file=sys.stderr,
    )


def identity_notice_level(result: IdentityClassification) -> Literal["notice", "warning", "error"]:
    disposition = result.disposition
    if disposition == "expected":
        return "notice"
    if disposition == "degraded":
        return "warning"
    if disposition == "misconfigured":
        return "warning"
    _assert_never(disposition)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or check CPC route manifest")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare generated OpenAPI to the committed manifest without writing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    operations, identity = load_app_operations()
    emit_status(
        format_identity_classification(identity),
        level=identity_notice_level(identity),
    )
    emit_status(
        "CI/local manifest generation does not attest production identity health.",
        level="notice",
    )

    if args.check:
        try:
            committed_doc = load_committed_manifest()
            committed_text = MANIFEST.read_text(encoding="utf-8")
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
            emit_status(f"cannot read committed manifest: {exc}", level="error")
            return 1
        generated_doc = build_manifest(operations)
        diff = compare_committed_to_generated(committed_doc, committed_text, generated_doc)
        report = format_document_diff(diff)
        if diff.match:
            emit_status(report, level="notice")
            return 0
        emit_status(report, level="error")
        if diff.operations.removed:
            emit_status(
                "expected_routes.json would drop routes. Refusing silent removal.",
                level="error",
            )
        else:
            emit_status(
                "expected_routes.json is stale. Run scripts/gen_route_manifest.py and commit.",
                level="error",
            )
        return 1

    write_manifest(operations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
