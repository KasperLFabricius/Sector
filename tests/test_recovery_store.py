"""Recovery writes preserve the exact version observed by each session."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from app import recovery_store


def atomic_writer(data, path):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)
    return True


def test_two_sessions_cannot_replace_each_others_recovery(tmp_path):
    path = tmp_path / "autosave.json"
    assert recovery_store.file_digest(path) is None
    status, identity = recovery_store.write_if_current('{"project":"A"}\n', path, None, atomic_writer)
    assert status == "saved"
    assert identity == hashlib.sha256(path.read_bytes()).hexdigest()
    before = path.read_bytes()
    assert recovery_store.write_if_current('{"project":"B"}', path, None, atomic_writer) == ("conflict", None)
    assert path.read_bytes() == before
    assert recovery_store.write_if_current('{"project":"A","revision":2}', path, identity, atomic_writer)[0] == "saved"


def test_read_then_write_race_preserves_newer_project(tmp_path):
    path = tmp_path / "autosave.json"
    atomic_writer('{"project":"A"}', path)
    observed = recovery_store.file_digest(path)
    atomic_writer('{"project":"B"}', path)
    assert recovery_store.write_if_current('{"project":"A","changed":true}', path, observed, atomic_writer) == ("conflict", None)
    assert path.read_text() == '{"project":"B"}'


def test_exception_releases_lock_and_preserves_original(tmp_path):
    path = tmp_path / "autosave.json"
    atomic_writer("original", path)
    observed = recovery_store.file_digest(path)
    def fail(*args):
        raise OSError("simulated unavailable disk")
    assert recovery_store.write_if_current("replacement", path, observed, fail) == ("failed", None)
    assert path.read_text() == "original"
    assert recovery_store.write_if_current("replacement", path, observed, atomic_writer)[0] == "saved"


def test_process_lock_prevents_write_and_process_exit_releases_it(tmp_path):
    path = tmp_path / "autosave.json"
    code = (
        "import importlib.util,time; from pathlib import Path; "
        "s=importlib.util.spec_from_file_location('recovery', " + repr(recovery_store.__file__) + "); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "lock=m.recovery_lock(Path(" + repr(str(path)) + ")); lock.__enter__(); "
        "print('LOCKED',flush=True); time.sleep(60)"
    )
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        assert process.stdout.readline().strip() == "LOCKED"
        assert recovery_store.write_if_current("project", path, None, atomic_writer) == ("busy", None)
        assert not path.exists()
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert recovery_store.write_if_current("project", path, None, atomic_writer)[0] == "saved"


def test_explicit_loaded_project_has_separate_source_and_recovery_destinations(tmp_path):
    source = tmp_path / "named-project.sector.json"
    source.write_text('{"project":"loaded"}')
    before = source.read_bytes()
    recovery = tmp_path / "recovery" / "autosave.json"
    assert recovery_store.write_if_current(source.read_text(), recovery, None, atomic_writer)[0] == "saved"
    assert source.read_bytes() == before
    assert recovery.read_text() == source.read_text()
