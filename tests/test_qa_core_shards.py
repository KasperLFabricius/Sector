"""The parallel gate must preserve complete identities, outcomes and raw coverage."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import coverage
import pytest

from tools import qa_core_shards as shards


def _node(shard):
    return {
        "report": "tests/test_report.py::test_example[literal@value]@native-member-report",
        "combined": "tests/test_combined.py::test_example",
        "native": "tests/test_torsion.py::test_example",
        "other": "tests/test_qa_core_shards.py::test_example[literal@value]",
    }[shard]


def _save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(directory, change=None):
    path = directory / "manifest.json"
    value = json.loads(path.read_text())
    if change:
        change(value)
    value["files"] = {name: {"sha256": shards.sha(directory / name), "size": (directory / name).stat().st_size}
                      for name in shards.FILES if (directory / name).exists()}
    _save(path, value)


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    model = root / "model.py"
    model.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")
    binding = {"repository": "KasperLFabricius/Sector", "run_id": "123", "run_attempt": "2",
               "source_revision": "a" * 40, "source_tree": "b" * 40, "source_root": str(root)}
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    directories = {}
    for index, shard in enumerate(shards.SHARDS, 1):
        directory = inputs / f"sector-core-123-2-{shard}"
        directory.mkdir()
        directories[shard] = directory
        data = coverage.CoverageData(basename=str(directory / ".coverage"))
        data.add_lines({str(model): {index}})
        data.write()
        suite = ET.Element("testsuite", name="pytest", tests="1", failures="0", errors="0", skipped="0")
        classname, name = shards.junit_key(_node(shard))
        ET.SubElement(suite, "testcase", classname=classname, name=name, time="0.01")
        ET.ElementTree(suite).write(directory / "test-results.xml")
        for worker in shards.WORKERS:
            _save(directory / f"collection-{worker}.json",
                  {"worker": worker, "selected": [_node(shard)], "deselected": []})
        _save(directory / "manifest.json", {"schema_version": 1, **binding, "shard": shard,
              "exit_code": 0, "source_before": "source-bytes", "source_after": "source-bytes"})
        _manifest(directory)
    monkeypatch.setattr(shards, "ROOT", root)
    monkeypatch.setattr(shards, "identity", lambda: binding)
    monkeypatch.setattr(shards, "source_digest", lambda: "source-bytes")
    monkeypatch.setattr(shards, "collect_reference", lambda output, actual_binding: [_node(shard) for shard in shards.SHARDS])
    return SimpleNamespace(root=root, inputs=inputs, output=tmp_path / "output", directories=directories,
                           binding=binding, model=model)


def test_module_selection_is_disjoint_and_other_covers_every_unlisted_module():
    listed = [path for paths in shards.MODULES.values() for path in paths]
    assert len(listed) == len(set(listed))
    for shard, paths in shards.MODULES.items():
        assert shards.selection(shard) == list(paths)
        assert all(shards.shard_for_node(path + "::test_x[a@b]") == shard for path in paths)
    assert shards.selection("other") == ["tests", *(f"--ignore={path}" for path in listed)]
    assert shards.shard_for_node("tests/test_future_module.py::test_new") == "other"
    assert all(shards.shard_for_node(path + "::test_x") == "report" for path in (
        "tests/test_report.py", "tests/test_report_real_route_matrix.py", "tests/test_result_presentation.py"))
    with pytest.raises(shards.QaShardError, match="unknown shard"):
        shards.selection("missing")


def test_raw_coverage_union_and_junit_retain_every_shard_and_literal_at(evidence):
    before = {str(path): shards.sha(path) for path in evidence.inputs.rglob("*") if path.is_file()}
    assert shards.merge_shards(evidence.inputs, evidence.output) == 0
    result = coverage.CoverageData(basename=str(evidence.root / ".coverage"))
    result.read()
    assert sorted(result.lines(str(evidence.model))) == [1, 2, 3, 4]
    cases = list(ET.parse(evidence.output / "test-results.xml").getroot().iter("testcase"))
    assert {(case.get("classname"), case.get("name")) for case in cases} == {
        shards.junit_key(_node(shard)) for shard in shards.SHARDS}
    assert len(cases) == 4
    assert all(shards.sha(path) == digest for path, digest in before.items())
    summary = json.loads((evidence.output / "core-shard-summary.json").read_text())
    assert summary["all_core_passed"] is True and summary["total_nodes"] == 4
    assert len(summary["coverage_inputs"]) == 4


@pytest.mark.parametrize("kind", ["failure", "error", "skipped", "nonzero_exit"])
def test_nonpassing_core_retains_union_and_failed_outcome(evidence, kind):
    directory = evidence.directories["combined"]
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
    assert json.loads((evidence.output / "core-shard-summary.json").read_text())["all_core_passed"] is False


@pytest.mark.parametrize("field,value", [
    ("run_id", "122"), ("run_attempt", "1"), ("source_revision", "c" * 40),
    ("source_tree", "c" * 40), ("repository", "another/repo"), ("source_root", "another-root"),
    ("source_before", "different"), ("source_after", "different"), ("shard", "native"),
    ("exit_code", False), ("exit_code", "0"), ("schema_version", 0),
])
def test_foreign_or_malformed_manifest_is_rejected(evidence, field, value):
    directory = evidence.directories["report"]
    _manifest(directory, lambda manifest: manifest.update({field: value}))
    with pytest.raises(shards.QaShardError):
        shards.read_shard(directory, "report", evidence.binding, "source-bytes")


@pytest.mark.parametrize("damage", ["missing_artifact", "foreign_artifact", "missing_coverage", "changed_bytes",
                                   "missing_case", "duplicate_case", "worker_disagrees", "incomplete_reference",
                                   "contaminated_destination", "branch_data"])
def test_missing_duplicated_or_corrupt_execution_evidence_cannot_pass(evidence, monkeypatch, damage):
    directory = evidence.directories["report"]
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
        value["selected"] = [_node("other")]
        _save(path, value)
        _manifest(directory)
    elif damage == "incomplete_reference":
        monkeypatch.setattr(shards, "collect_reference", lambda *_: [_node(shard) for shard in shards.SHARDS] + ["tests/test_new.py::test_new"])
    elif damage == "contaminated_destination":
        (evidence.root / ".coverage").write_bytes(b"pre-existing")
    elif damage == "branch_data":
        path = directory / ".coverage"
        path.unlink()
        data = coverage.CoverageData(basename=str(path))
        data.add_arcs({str(evidence.model): {(1, 2)}})
        data.write()
        _manifest(directory)
    with pytest.raises(shards.QaShardError):
        shards.merge_shards(evidence.inputs, evidence.output)


def test_reference_collects_the_whole_core_and_rejects_cross_shard_groups(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "temporary"))
    expected = [
        {"nodeid": "tests/test_report.py::test_x[a@b]", "groups": ["shared"]},
        {"nodeid": "tests/test_result_presentation.py::test_y", "groups": ["shared"]},
    ]
    def collect(command, **kwargs):
        assert command[2:4] == ["pytest", "tests"]
        assert "--collect-only" in command and command[command.index("-n") + 1] == "0"
        assert command[command.index("-m", 3) + 1] == "not real_image_export"
        assert not any(token.startswith("--ignore") for token in command)
        _save(Path(kwargs["env"]["SECTOR_QA_REFERENCE_OUTPUT"]), {"nodes": expected, "deselected": []})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(shards.subprocess, "run", collect)
    first = tmp_path / "first"
    first.mkdir()
    assert shards.collect_reference(first, {"run_id": "1", "run_attempt": "1"}) == [
        "tests/test_report.py::test_x[a@b]@shared", "tests/test_result_presentation.py::test_y@shared"]
    expected[1]["nodeid"] = "tests/test_combined.py::test_y"
    second = tmp_path / "second"
    second.mkdir()
    with pytest.raises(shards.QaShardError, match="crosses shards"):
        shards.collect_reference(second, {"run_id": "1", "run_attempt": "1"})
