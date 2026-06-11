"""Boot-time data dir probing logs when LEDGER_DATA_DIR is unusable."""
import logging

import ledger.app.db as db_mod


def test_get_data_dir_logs_when_requested_path_not_writable(monkeypatch, caplog):
    monkeypatch.setenv("LEDGER_DATA_DIR", "/var/lib/ledger")

    def fake_probe(path: str) -> None:
        if path == "/var/lib/ledger":
            raise PermissionError("[Errno 13] Permission denied: '/var/lib/ledger'")

    monkeypatch.setattr(db_mod, "_probe_writable_dir", fake_probe)

    caplog.set_level(logging.WARNING, logger="ledger.app.db")
    chosen = db_mod.get_data_dir()
    logged = "\n".join(record.getMessage() for record in caplog.records)

    assert chosen == "/tmp/ledger_data"
    assert "LEDGER_DATA_DIR='/var/lib/ledger' is not writable" in logged
    assert "using '/tmp/ledger_data'" in logged


def test_get_data_dir_logs_success_on_requested_path(monkeypatch, caplog):
    monkeypatch.setenv("LEDGER_DATA_DIR", "/tmp/cpc_test_ledger_dir")
    monkeypatch.setattr(db_mod, "_probe_writable_dir", lambda path: None)

    caplog.set_level(logging.INFO, logger="ledger.app.db")
    chosen = db_mod.get_data_dir()
    logged = "\n".join(record.getMessage() for record in caplog.records)

    assert chosen == "/tmp/cpc_test_ledger_dir"
    assert "Using LEDGER_DATA_DIR='/tmp/cpc_test_ledger_dir'" in logged
