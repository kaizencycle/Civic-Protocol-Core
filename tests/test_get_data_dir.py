"""Boot-time data dir probing logs when LEDGER_DATA_DIR is unusable."""
import importlib

import ledger.app.db as db_mod


def test_get_data_dir_logs_when_requested_path_not_writable(monkeypatch, capsys):
    monkeypatch.setenv("LEDGER_DATA_DIR", "/var/lib/ledger")
    calls: list[str] = []

    def fake_probe(path: str) -> None:
        calls.append(path)
        if path == "/var/lib/ledger":
            raise PermissionError("[Errno 13] Permission denied: '/var/lib/ledger'")

    monkeypatch.setattr(db_mod, "_probe_writable_dir", fake_probe)

    chosen = db_mod.get_data_dir()
    out = capsys.readouterr().out

    assert calls[0] == "/var/lib/ledger"
    assert chosen == "/tmp/ledger_data"
    assert "LEDGER_DATA_DIR='/var/lib/ledger' is not writable" in out
    assert "using '/tmp/ledger_data'" in out


def test_get_data_dir_logs_success_on_requested_path(monkeypatch, capsys):
    monkeypatch.setenv("LEDGER_DATA_DIR", "/tmp/cpc_test_ledger_dir")
    monkeypatch.setattr(db_mod, "_probe_writable_dir", lambda path: None)

    chosen = db_mod.get_data_dir()
    out = capsys.readouterr().out

    assert chosen == "/tmp/cpc_test_ledger_dir"
    assert "Using LEDGER_DATA_DIR='/tmp/cpc_test_ledger_dir'" in out
