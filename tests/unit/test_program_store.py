from __future__ import annotations

import pytest

from caelum.capture_runtime.store import ProgramNotFound, ProgramStore, ProgramStoreError
from caelum.config.schema import AppConfig

SOURCE = 'PROGRAM = {"description": "mine"}\n\nasync def capture(ctx):\n    return None\n'


def test_lists_builtins_and_user_programs(tmp_path):
    store = ProgramStore(tmp_path)
    store.save("mine.py", SOURCE)
    programs = {p.name: p for p in store.list()}
    assert programs["default.py"].origin == "builtin"
    assert programs["mine.py"].origin == "user"
    assert programs["mine.py"].to_dict()["description"] == "mine"
    assert store.get("mine.py") == (SOURCE, "user")


@pytest.mark.parametrize("name", ["../x.py", "X.py", "a b.py", "noext", ".hidden.py", "a/b.py"])
def test_rejects_bad_names(tmp_path, name):
    with pytest.raises(ProgramStoreError):
        ProgramStore(tmp_path).save(name, SOURCE)


def test_builtins_are_read_only(tmp_path):
    store = ProgramStore(tmp_path)
    with pytest.raises(ProgramStoreError, match="built-in"):
        store.save("default.py", SOURCE)
    with pytest.raises(ProgramStoreError, match="built-in"):
        store.delete("default.py")


def test_production_runs_the_archived_version_not_the_file(tmp_path):
    store = ProgramStore(tmp_path)
    store.save("mine.py", SOURCE)
    sha = store.archive(SOURCE)
    store.save("mine.py", SOURCE.replace("mine", "edited"))
    cfg = AppConfig().model_copy(
        update={"capture": AppConfig().capture.model_copy(update={"active_program": "mine.py", "active_sha256": sha})}
    )
    program = store.active(cfg)
    assert program.sha256 == sha and program.meta["description"] == "mine"
    store.delete("mine.py")
    assert store.load("mine.py", sha).sha256 == sha  # archived versions outlive the file


def test_missing_versions(tmp_path):
    store = ProgramStore(tmp_path)
    with pytest.raises(ProgramNotFound):
        store.load("mine.py", "0" * 64)
    with pytest.raises(ProgramStoreError):
        store.load("mine.py", None)
    with pytest.raises(ProgramStoreError):
        store.archived_source("../../etc/passwd")


def test_crash_marker_is_taken_once(tmp_path):
    from caelum.capture_runtime import load_program

    store = ProgramStore(tmp_path)
    program = load_program("mine.py", SOURCE)
    store.mark_crashed(program)
    assert store.take_crash_marker() == ("mine.py", program.sha256)
    assert store.take_crash_marker() is None
