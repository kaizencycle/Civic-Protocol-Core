"""Unit tests for Render → routine shim helpers."""

from scripts.render_routine_shim import app as shim_app


def test_deploy_status_from_data():
    body = {"type": "deploy", "data": {"status": "deploy_succeeded", "service": {"name": "ledger"}}}
    assert shim_app._deploy_status(body) == "deploy_succeeded"
    assert shim_app._service_name(body) == "ledger"


def test_skipped_status_not_in_success_set():
    body = {"data": {"status": "build_failed"}}
    assert shim_app._deploy_status(body) == "build_failed"
    assert shim_app._deploy_status(body) not in shim_app._SUCCESS_STATUSES
