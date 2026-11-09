"""The parallel gate must preserve complete identities, outcomes and raw coverage."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import coverage
import pytest
import tomllib

from tools import qa_core_shards as shards

ROOT = Path(__file__).resolve().parents[1]
UNIFORM = {"schema_version": 1, "default_seconds": 2.0, "modules": {}, "tests": {}}
GROUPED = "tests/test_report.py::test_example[literal@value]@native-member-report"


def _rows(suite):
    """One node per shard; each node is its own module, so node i owns shard i."""
    rows = []
    for index, shard in enumerate(shards.suite_shards(suite), 1):
        if shard == "core-01":
            rows.append((GROUPED, "native-member-report"))
        else:
            rows.append((f"tests/test_{suite}_{index:02d}.py::test_example[literal@value]", ""))
    return rows


def _save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(directory, change=None, names=shards.FILES):
    path = directory / "manifest.json"
    value = json.loads(path.read_text())
    if change:
        change(value)
    value["files"] = {name: {"sha256": shards.sha(directory / name), "size": (directory / name).stat().st_size}
                      for name in names if (directory / name).exists()}
    _save(path, value)


def _junit(path, nodes):
    suite = ET.Element("testsuite", name="pytest", tests=str(len(nodes)), failures="0", errors="0", skipped="0")
    for node in nodes:
        classname, name = shards.junit_key(node)
        ET.SubElement(suite, "testcase", classname=classname, name=name, time="0.01")
    ET.ElementTree(suite).write(path)


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    model = root / "model.py"
    model.write_text("a = 1\nb = 2\nc = 3\nd = 4\n" * 5)
    decision = root / "decision.py"
    decision.write_text("a = 1\n")
    binding = {"repository": "KasperLFabricius/Sector", "run_id": "123", "run_attempt": "2",
               "source_revision": "a" * 40, "source_tree": "b" * 40, "source_root": str(root)}
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    directories = {}
    rows = {suite: _rows(suite) for suite in shards.SUITES}
    for suite in shards.SUITES:
        for index, (shard, (node, _)) in enumerate(zip(shards.suite_shards(suite), rows[suite]), 1):
            directory = inputs / f"sector-core-123-2-{shard}"
            directory.mkdir()
            directories[shard] = directory
            data = coverage.CoverageData(basename=str(directory / ".coverage"))
            if suite == "core":
                data.add_lines({str(model): {index}})
            else:
                data.add_arcs({str(decision): {(-1, 1), (1, -1)}})
            data.write()
            _junit(directory / "test-results.xml", [node])
            for worker in shards.WORKERS:
                _save(directory / f"collection-{worker}.json",
                      {"worker": worker, "selected": [node], "deselected": []})
            _save(directory / "manifest.json", {"schema_version": 1, **binding, "shard": shard,
                  "exit_code": 0, "source_before": "source-bytes", "source_after": "source-bytes"})
            _manifest(directory)
    real = inputs / "sector-core-123-2-real"
    real.mkdir()
    directories["real"] = real
    data = coverage.CoverageData(basename=str(real / ".coverage"))
    data.add_lines({str(model): {20}})
    data.write()
    for name, _ in shards.REAL_TESTS:
        _junit(real / f"test-results-real-{name}.xml", [f"tests/test_real_{name}.py::test_export"])
    for name, _ in shards.REAL_RENDERS:
        (real / name).mkdir()
        (real / name / "page.png").write_bytes(b"png")
    _save(real / "manifest.json", {"schema_version": 1, **binding, "shard": "real", "exit_code": 0,
          "phases": dict.fromkeys(shards.REAL_PHASES, 0),
          "source_before": "source-bytes", "source_after": "source-bytes"})
    _manifest(real, names=shards.REAL_FILES)
    monkeypatch.setattr(shards, "ROOT", root)
    monkeypatch.setattr(shards, "identity", lambda: binding)
    monkeypatch.setattr(shards, "source_digest", lambda: "source-bytes")
    monkeypatch.setattr(shards, "load_durations", lambda path=None: UNIFORM)
    monkeypatch.setattr(shards, "collect_reference", lambda output, actual_binding, suite: list(rows[suite]))
    return SimpleNamespace(root=root, inputs=inputs, output=tmp_path / "output", directories=directories,
                           binding=binding, model=model, rows=rows)


def test_shard_inventory_is_twelve_core_four_branch_and_one_real_shard():
    assert shards.SUITES == {"core": 12, "branch": 4}
    assert shards.SHARDS == (*(f"core-{index:02d}" for index in range(1, 13)),
                             *(f"branch-{index:02d}" for index in range(1, 5)), "real")
    assert shards.suite_shards("branch") == ["branch-01", "branch-02", "branch-03", "branch-04"]
    assert shards.shard_position("core-07") == ("core", 7)
    for shard in ("real", "core-13", "other"):
        with pytest.raises(shards.QaShardError):
            shards.shard_position(shard)


def test_suites_keep_the_core_marker_filter_and_the_exact_branch_contract():
    with (ROOT / "quality-coverage-gate.toml").open("rb") as stream:
        data = tomllib.load(stream)
    assert shards.suite_command("core") == ["tests", "-m", "not real_image_export", "--cov=app", "--cov=sector"]
    branch = data["branch_coverage"]
    assert shards.suite_command("branch") == [
        *branch["tests"], *(f"--cov={target}" for target in branch["targets"]), "--cov-branch"]
    with pytest.raises(shards.QaShardError, match="unknown suite"):
        shards.suite_command("other")


def test_real_shard_retains_the_serial_exports_and_render_fixtures():
    assert shards.REAL_TESTS == (
        ("viz", ("tests/test_viz.py",)),
        ("report", ("tests/test_report_rendered.py::"
                    "test_issued_report_renders_every_page_and_retains_expected_content",)),
        ("manual", ("tests/test_manual_rendered.py::"
                    "test_issued_manual_renders_every_page_and_retains_navigation",)),
    )
    assert shards.REAL_RENDERS == (
        ("report", "tools/report_render_fixture.py"), ("manual", "tools/manual_render_fixture.py"))


def test_balanced_assignment_keeps_groups_whole_and_places_every_new_test():
    durations = {"schema_version": 1, "default_seconds": 2.0, "modules": {"tests/test_small.py": 0.1},
                 "tests": {"tests/test_big.py::test_a": 900.0, "tests/test_big.py::test_b": 900.0,
                           "tests/test_g.py::test_x@shared": 500.0}}
    rows = [("tests/test_big.py::test_a", ""), ("tests/test_big.py::test_b", ""),
            ("tests/test_g.py::test_x@shared", "shared"), ("tests/test_h.py::test_y@shared", "shared"),
            *((f"tests/test_small.py::test_{index}", "") for index in range(30)),
            ("tests/test_future_module.py::test_new", "")]
    owners = shards.assign(rows, 3, durations)
    assert owners == shards.assign(rows, 3, durations)
    assert set(owners) == {node for node, _ in rows} and set(owners.values()) == {1, 2, 3}
    assert owners["tests/test_g.py::test_x@shared"] == owners["tests/test_h.py::test_y@shared"]
    # Each 900 s test fills its own chunk, so the two halves of the module balance.
    assert owners["tests/test_big.py::test_a"] != owners["tests/test_big.py::test_b"]
    assert len({owners[f"tests/test_small.py::test_{index}"] for index in range(30)}) == 1
    assert shards.seconds_for("tests/test_future_module.py::test_new", durations) == 2.0


def test_collection_filter_selects_exactly_the_assigned_shard(monkeypatch):
    def item(nodeid, *groups):
        marks = [SimpleNamespace(args=(group,), kwargs={}) for group in groups]
        return SimpleNamespace(nodeid=nodeid, iter_markers=lambda name, marks=marks: marks)
    collected = [item("tests/test_a.py::test_x", "solo"), item("tests/test_b.py::test_y@pair", "pair"),
                 item("tests/test_c.py::test_z", "pair"), *(item(f"tests/test_d{index}.py::test_w") for index in range(20))]
    monkeypatch.setattr(shards, "load_durations", lambda path=None: UNIFORM)
    owners = shards.assign([shards.node_row(entry) for entry in collected], 12)
    seen = []
    for shard in shards.suite_shards("core"):
        monkeypatch.setenv("SECTOR_QA_SHARD", shard)
        items = list(collected)
        shards.pytest_collection_modifyitems(None, items)
        assert items and all(owners[shards.node_row(entry)[0]] == int(shard[-2:]) for entry in items)
        seen.extend(items)
    assert sorted(map(id, seen)) == sorted(map(id, collected))
    assert shards.node_row(collected[1]) == ("tests/test_b.py::test_y@pair", "pair")
    assert shards.node_row(collected[2]) == ("tests/test_c.py::test_z@pair", "pair")
    monkeypatch.delenv("SECTOR_QA_SHARD")
    items = list(collected)
    shards.pytest_collection_modifyitems(None, items)
    assert items == collected


def test_checked_in_duration_table_is_complete_and_positive():
    data = shards.load_durations()
    assert data["default_seconds"] > 0 and data["tests"] and data["modules"]
    assert all(key.startswith("tests/") and value >= 1.0 for key, value in data["tests"].items())
    assert all(key.startswith("tests/") and value >= 0 for key, value in data["modules"].items())


def test_raw_coverage_union_and_junit_retain_every_shard_and_literal_at(evidence):
    before = {str(path): shards.sha(path) for path in evidence.inputs.rglob("*") if path.is_file()}
    assert shards.merge_shards(evidence.inputs, evidence.output) == 0
    result = coverage.CoverageData(basename=str(evidence.root / ".coverage"))
    result.read()
    assert sorted(result.lines(str(evidence.model))) == [*range(1, 13), 20]
    cases = list(ET.parse(evidence.output / "test-results.xml").getroot().iter("testcase"))
    assert {(case.get("classname"), case.get("name")) for case in cases} == {
        shards.junit_key(node) for node, _ in evidence.rows["core"]}
    assert len(cases) == 12
    branch_cases = list(ET.parse(evidence.output / "test-results-branches.xml").getroot().iter("testcase"))
    assert len(branch_cases) == 4
    assert "totals" in json.loads((evidence.output / "branch-coverage.json").read_text())
    for name, _ in shards.REAL_TESTS:
        assert (evidence.output / f"test-results-real-{name}.xml").is_file()
    assert (evidence.output / "report" / "page.png").is_file() and (evidence.output / "manual").is_dir()
    assert all(shards.sha(path) == digest for path, digest in before.items())
    summary = json.loads((evidence.output / "core-shard-summary.json").read_text())
    assert summary["all_core_passed"] and summary["all_branch_passed"] and summary["all_real_passed"]
    assert (summary["total_nodes"], summary["branch_nodes"], summary["real_tests"]) == (12, 4, 3)
    assert len(summary["coverage_inputs"]) == 13 and len(summary["branch_coverage_inputs"]) == 4


@pytest.mark.parametrize("shard", ["core-02", "branch-03"])
@pytest.mark.parametrize("kind", ["failure", "error", "skipped", "nonzero_exit"])
def test_nonpassing_shard_retains_union_and_failed_outcome(evidence, shard, kind):
    directory = evidence.directories[shard]
    if kind == "nonzero_exit":
        _manifest(directory, lambda value: value.update(exit_code=1))
    else:
        path = directory / "test-results.xml"
        tree = ET.parse(path)
        ET.SubElement(next(tree.getroot().iter("testcase")), kind, message="observed nonpass")
        tree.write(path)
        _manifest(directory)
    assert shards.merge_shards(evidence.inputs, evidence.output) == 1
    assert (evidence.output / "test-results.xml").is_file()
    assert (evidence.root / ".coverage").is_file()
    summary = json.loads((evidence.output / "core-shard-summary.json").read_text())
    assert summary["all_core_passed" if shard.startswith("core") else "all_branch_passed"] is False


@pytest.mark.parametrize("kind", ["failure", "error", "nonzero_phase"])
def test_failed_real_image_phase_fails_the_merge(evidence, kind):
    directory = evidence.directories["real"]
    if kind == "nonzero_phase":
        _manifest(directory, lambda value: value.update(exit_code=1, phases={**value["phases"], "render-manual": 1}),
                  names=shards.REAL_FILES)
    else:
        path = directory / "test-results-real-viz.xml"
        tree = ET.parse(path)
        ET.SubElement(next(tree.getroot().iter("testcase")), kind, message="observed nonpass")
        tree.write(path)
        _manifest(directory, names=shards.REAL_FILES)
    assert shards.merge_shards(evidence.inputs, evidence.output) == 1
    assert json.loads((evidence.output / "core-shard-summary.json").read_text())["all_real_passed"] is False


def _attempt_copy(evidence, shard, attempt, *, move=False):
    """Give a shard the evidence of another attempt of the same run."""
    import shutil

    source = evidence.directories[shard]
    target = evidence.inputs / f"sector-core-123-{attempt}-{shard}"
    (shutil.move if move else shutil.copytree)(source, target)
    names = shards.REAL_FILES if shard == "real" else shards.FILES
    _manifest(target, lambda value: value.update(run_attempt=str(attempt)), names=names)
    return target


def _fail_junit(directory, name="test-results.xml"):
    path = directory / name
    tree = ET.parse(path)
    ET.SubElement(next(tree.getroot().iter("testcase")), "failure", message="observed nonpass")
    tree.write(path)


@pytest.mark.parametrize("shard", ["core-03", "branch-02", "real"])
def test_rerun_of_failed_jobs_keeps_the_evidence_of_the_earlier_attempt(evidence, shard):
    # A rerun of failed jobs (attempt 2) does not run this shard again.
    _attempt_copy(evidence, shard, 1, move=True)
    assert shards.merge_shards(evidence.inputs, evidence.output) == 0
    summary = json.loads((evidence.output / "core-shard-summary.json").read_text())
    attempts = {row["shard"]: row["attempt"] for row in (*summary["shards"], *summary["branch_shards"])}
    attempts["real"] = summary["real"]["attempt"]
    assert attempts == {name: 1 if name == shard else 2 for name in shards.SHARDS}


@pytest.mark.parametrize("newest_passes", [True, False])
def test_newest_attempt_of_a_shard_governs_its_outcome(evidence, newest_passes):
    earlier = _attempt_copy(evidence, "core-02", 1)
    names = shards.FILES
    if newest_passes:
        _fail_junit(earlier)
        _manifest(earlier, names=names)
    else:
        _fail_junit(evidence.directories["core-02"])
        _manifest(evidence.directories["core-02"], names=names)
    assert shards.merge_shards(evidence.inputs, evidence.output) == (0 if newest_passes else 1)


@pytest.mark.parametrize("damage", ["later_attempt", "other_run", "claims_newer_attempt", "padded_attempt"])
def test_evidence_of_another_run_or_attempt_cannot_pass(evidence, damage):
    import shutil

    if damage == "later_attempt":
        _attempt_copy(evidence, "core-04", 3)
    elif damage == "other_run":
        shutil.copytree(evidence.directories["core-04"], evidence.inputs / "sector-core-122-2-core-04")
    elif damage == "claims_newer_attempt":
        # The name says attempt 1, but the manifest is the evidence of attempt 2.
        evidence.directories["core-04"].rename(evidence.inputs / "sector-core-123-1-core-04")
    else:
        shutil.copytree(evidence.directories["core-04"], evidence.inputs / "sector-core-123-02-core-04")
    with pytest.raises(shards.QaShardError):
        shards.merge_shards(evidence.inputs, evidence.output)


def _process_exists(pid):
    import os
    import subprocess

    if os.name == "nt":
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                                check=False).stdout
        return str(pid) in listed.split()
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_real_phase_past_the_hang_limit_stops_its_process_tree(tmp_path):
    import sys
    import time

    grandchild = tmp_path / "grandchild.pid"
    child = ("import pathlib, subprocess, sys, time; "
             "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
             f"pathlib.Path({str(grandchild)!r}).write_text(str(p.pid)); time.sleep(120)")
    started = time.monotonic()
    code = shards.run_real_phase([sys.executable, "-c", child], cwd=tmp_path, env=None, limit=10.0)
    assert code == shards.REAL_PHASE_TIMEOUT_EXIT
    assert time.monotonic() - started < 60
    pid = int(grandchild.read_text())
    deadline = time.monotonic() + 15
    while _process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not _process_exists(pid), "the browser-like grandchild of a stopped phase still runs"
    assert shards.run_real_phase([sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path, env=None) == 3


def test_real_phase_stopped_at_the_hang_limit_fails_the_merge_by_name(evidence):
    _manifest(evidence.directories["real"], lambda value: value.update(
        exit_code=shards.REAL_PHASE_TIMEOUT_EXIT,
        phases={**value["phases"], "viz": shards.REAL_PHASE_TIMEOUT_EXIT}), names=shards.REAL_FILES)
    with pytest.raises(shards.QaShardError, match="hang limit: viz"):
        shards.merge_shards(evidence.inputs, evidence.output)


@pytest.mark.parametrize("field,value", [
    ("run_id", "122"), ("run_attempt", "1"), ("source_revision", "c" * 40),
    ("source_tree", "c" * 40), ("repository", "another/repo"), ("source_root", "another-root"),
    ("source_before", "different"), ("source_after", "different"), ("shard", "core-02"),
    ("exit_code", False), ("exit_code", "0"), ("schema_version", 0),
])
def test_foreign_or_malformed_manifest_is_rejected(evidence, field, value):
    directory = evidence.directories["core-01"]
    _manifest(directory, lambda manifest: manifest.update({field: value}))
    with pytest.raises(shards.QaShardError):
        shards.read_shard(directory, "core-01", evidence.binding, "source-bytes", [GROUPED])


@pytest.mark.parametrize("damage", [
    "missing_artifact", "foreign_artifact", "missing_coverage", "changed_bytes", "missing_case",
    "duplicate_case", "worker_disagrees", "incomplete_reference", "contaminated_destination",
    "branch_data", "line_branch_data", "wrong_assignment", "empty_shard", "real_missing_render",
    "real_missing_phase", "real_without_tests", "real_branch_data", "real_extra_file",
])
def test_missing_duplicated_or_corrupt_execution_evidence_cannot_pass(evidence, monkeypatch, damage):
    directory = evidence.directories["core-01"]
    real = evidence.directories["real"]
    if damage == "missing_artifact":
        directory.rename(evidence.inputs / "foreign-name")
    elif damage == "foreign_artifact":
        (evidence.inputs / "unexpected").mkdir()
    elif damage == "missing_coverage":
        (directory / ".coverage").unlink()
        _manifest(directory)
    elif damage == "changed_bytes":
        with (directory / "test-results.xml").open("ab") as stream:
            stream.write(b" ")
    elif damage in {"missing_case", "duplicate_case"}:
        path = directory / "test-results.xml"
        tree = ET.parse(path)
        case = next(tree.getroot().iter("testcase"))
        tree.getroot().remove(case) if damage == "missing_case" else tree.getroot().append(deepcopy(case))
        tree.write(path)
        _manifest(directory)
    elif damage == "worker_disagrees":
        path = directory / "collection-gw1.json"
        value = json.loads(path.read_text())
        value["selected"] = [evidence.rows["core"][1][0]]
        _save(path, value)
        _manifest(directory)
    elif damage == "incomplete_reference":
        rows = {suite: [*evidence.rows[suite], ("tests/test_new.py::test_new", "")] for suite in shards.SUITES}
        monkeypatch.setattr(shards, "collect_reference", lambda output, binding, suite: rows[suite])
    elif damage == "contaminated_destination":
        (evidence.root / ".coverage").write_bytes(b"pre-existing")
    elif damage in {"branch_data", "line_branch_data", "real_branch_data"}:
        target = {"branch_data": directory, "line_branch_data": evidence.directories["branch-01"],
                  "real_branch_data": real}[damage]
        path = target / ".coverage"
        path.unlink()
        data = coverage.CoverageData(basename=str(path))
        if damage == "line_branch_data":
            data.add_lines({str(evidence.model): {1}})
        else:
            data.add_arcs({str(evidence.model): {(1, 2)}})
        data.write()
        _manifest(target, names=shards.REAL_FILES if target == real else shards.FILES)
    elif damage in {"wrong_assignment", "empty_shard"}:
        # core-02 also claims the node of core-01, which the balance assigns elsewhere.
        other = evidence.directories["core-02"]
        selected = [] if damage == "empty_shard" else [evidence.rows["core"][1][0], GROUPED]
        for worker in shards.WORKERS:
            _save(other / f"collection-{worker}.json", {"worker": worker, "selected": selected, "deselected": []})
        _junit(other / "test-results.xml", selected)
        _manifest(other)
    elif damage == "real_missing_render":
        (real / "manual" / "page.png").write_bytes(b"x")
        for path in (real / "manual").iterdir():
            path.unlink()
        (real / "manual").rmdir()
    elif damage == "real_missing_phase":
        _manifest(real, lambda value: value["phases"].pop("render-report"), names=shards.REAL_FILES)
    elif damage == "real_without_tests":
        _junit(real / "test-results-real-manual.xml", [])
        _manifest(real, names=shards.REAL_FILES)
    elif damage == "real_extra_file":
        (real / "stray.txt").write_text("x")
    with pytest.raises(shards.QaShardError):
        shards.merge_shards(evidence.inputs, evidence.output)


@pytest.mark.parametrize("suite", ["core", "branch"])
def test_reference_collects_the_whole_suite_without_coverage_or_shard_filter(tmp_path, monkeypatch, suite):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "temporary"))
    monkeypatch.setenv("SECTOR_QA_SHARD", "core-01")
    expected = [
        {"nodeid": "tests/test_report.py::test_x[a@b]", "groups": ["shared"]},
        {"nodeid": "tests/test_result_presentation.py::test_y", "groups": []},
    ]
    def collect(command, **kwargs):
        assert command[2] == "pytest" and "--collect-only" in command and command[command.index("-n") + 1] == "0"
        selection = [token for token in shards.suite_command(suite) if not token.startswith("--cov")]
        assert command[3:3 + len(selection)] == selection
        assert not any(token.startswith(("--cov", "--ignore")) for token in command)
        assert "SECTOR_QA_SHARD" not in kwargs["env"]
        _save(Path(kwargs["env"]["SECTOR_QA_REFERENCE_OUTPUT"]), {"nodes": expected, "deselected": []})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(shards.subprocess, "run", collect)
    assert shards.collect_reference(tmp_path, {"run_id": "1", "run_attempt": "1"}, suite) == [
        ("tests/test_report.py::test_x[a@b]@shared", "shared"), ("tests/test_result_presentation.py::test_y", "")]


def test_duration_refresh_reads_core_junit_through_the_collected_identities(tmp_path):
    inputs = tmp_path / "inputs"
    for shard, nodes in (("core-01", [GROUPED, "tests/test_a.py::test_fast"]), ("branch-01", ["tests/test_b.py::test_x"])):
        directory = inputs / f"sector-core-1-1-{shard}"
        directory.mkdir(parents=True)
        _save(directory / "collection-gw0.json", {"worker": "gw0", "selected": nodes, "deselected": []})
        _junit(directory / "test-results.xml", nodes)
        tree = ET.parse(directory / "test-results.xml")
        next(tree.getroot().iter("testcase")).set("time", "12.34")
        tree.write(directory / "test-results.xml")
    destination = tmp_path / "durations.json"
    destination.write_text("stale table")
    assert shards.refresh_durations(inputs, destination) == 0
    data = json.loads(destination.read_text())
    assert data["tests"] == {GROUPED: 12.3}
    assert data["modules"] == {"tests/test_a.py": 0.01}
    assert data["module_means"] == {"tests/test_a.py": 0.01, "tests/test_report.py": 12.34}
    assert shards.load_durations(destination)["default_seconds"] == 2.0


def test_slow_marker_follows_the_duration_table_and_the_group_suffix():
    import conftest

    durations = shards.load_durations()
    limit = conftest.SLOW_SECONDS
    plain = next(key for key, seconds in durations["tests"].items() if "@" not in key and seconds >= limit)
    grouped = next(key for key, seconds in durations["tests"].items()
                   if "@" in key and "[" not in key and seconds >= limit)
    base, group = grouped.rsplit("@", 1)
    light = next(name for name, seconds in durations["module_means"].items() if seconds < limit)
    heavy = next(name for name, seconds in durations["module_means"].items()
                 if seconds >= limit and durations["modules"].get(name, limit) < limit)
    assert base not in durations["tests"]

    def item(nodeid, *groups, real=False):
        marks = [SimpleNamespace(args=(name,), kwargs={}) for name in groups]
        added = []
        return SimpleNamespace(nodeid=nodeid, added=added, add_marker=added.append,
                               iter_markers=lambda name, marks=marks: marks,
                               get_closest_marker=lambda name, real=real: real and name == "real_image_export")
    items = [item(plain), item(base, group), item(light + "::test_not_in_the_table"),
             item(heavy + "::test_not_in_the_table"), item("tests/test_new_module.py::test_x"),
             item(light + "::test_real_export", real=True)]
    conftest.pytest_collection_modifyitems(None, items)
    assert [[mark.name for mark in entry.added] for entry in items] == [
        ["slow"], ["slow"], [], ["slow"], ["slow"], ["slow"]]


def test_native_report_references_are_registered_only_by_conftest():
    """A module import of the fixtures would add a second session cache."""
    import re

    tests = Path(__file__).resolve().parent
    importer = re.compile(r"^[ \t]*(?:from|import)[ \t]+native_member_report_fixtures\b", re.M)
    importers = sorted(
        path.name for path in tests.glob("*.py")
        if importer.search(path.read_text(encoding="utf-8"))
    )
    assert importers == []
    conftest = (tests / "conftest.py").read_text(encoding="utf-8")
    assert 'pytest_plugins = ("native_member_report_fixtures",)' in conftest
