"""Run complete primary-test shards and combine their exact-run evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHARDS = ("report", "combined", "native", "other")
MODULES = {
    "report": (
        "tests/test_report.py",
        "tests/test_report_real_route_matrix.py",
        "tests/test_result_presentation.py",
    ),
    "combined": ("tests/test_combined.py",),
    "native": (
        "tests/test_app_smoke.py",
        "tests/test_torsion.py",
        "tests/test_shear.py",
        "tests/test_reproducible_example.py",
        "tests/test_report_profile_integration.py",
    ),
}
WORKERS = tuple(f"gw{number}" for number in range(4))
FILES = (".coverage", "test-results.xml", *(f"collection-{worker}.json" for worker in WORKERS))
_deselected = []


class QaShardError(ValueError):
    """A shard's identity, completeness or outcome cannot be accepted."""


def require(condition, message):
    if not condition:
        raise QaShardError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args]).decode("utf-8").strip()


def identity():
    result = {key: os.environ.get(environment, "") for key, environment in (
        ("repository", "GITHUB_REPOSITORY"), ("run_id", "GITHUB_RUN_ID"),
        ("run_attempt", "GITHUB_RUN_ATTEMPT"), ("source_revision", "GITHUB_SHA"),
    )}
    require(result["repository"] == "KasperLFabricius/Sector", "unexpected repository")
    require(all(re.fullmatch(r"[1-9][0-9]*", result[key]) for key in ("run_id", "run_attempt")), "invalid run identity")
    require(re.fullmatch(r"[0-9a-f]{40}", result["source_revision"]), "invalid source revision")
    require(git("rev-parse", "HEAD") == result["source_revision"], "checkout revision differs")
    require(not git("diff", "HEAD", "--name-only"), "tracked source differs from checkout")
    result["source_tree"] = git("rev-parse", "HEAD^{tree}")
    result["source_root"] = os.path.normcase(str(ROOT.resolve()))
    return result


def source_digest():
    files = [name for name in git("ls-files", "-z").split("\0") if name]
    values = {name: sha(ROOT / name) for name in sorted(files)}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def shard_for_node(node):
    module = node.split("::", 1)[0]
    require(module.startswith("tests/") and module.endswith(".py"), "node is outside the test inventory")
    owners = [shard for shard, paths in MODULES.items() if module in paths]
    require(len(owners) <= 1, "module belongs to multiple shards")
    return owners[0] if owners else "other"


def selection(shard):
    require(shard in SHARDS, "unknown shard")
    if shard != "other":
        return list(MODULES[shard])
    return ["tests", *(f"--ignore={path}" for paths in MODULES.values() for path in paths)]


def pytest_deselected(items):
    _deselected.extend(item.nodeid for item in items)


def pytest_collection_finish(session):
    destination = os.environ.get("SECTOR_QA_SHARD_OUTPUT")
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker is None:
        reference = os.environ.get("SECTOR_QA_REFERENCE_OUTPUT")
        if reference:
            nodes = []
            for item in session.items:
                groups = sorted({str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                                 for mark in item.iter_markers("xdist_group")})
                nodes.append({"nodeid": item.nodeid, "groups": groups})
            write_json(reference, {"nodes": nodes, "deselected": _deselected})
        return
    if not destination:
        return
    require(worker in WORKERS, "unexpected collection worker")
    write_json(Path(destination) / f"collection-{worker}.json", {
        "worker": worker, "selected": [item.nodeid for item in session.items],
        "deselected": _deselected,
    })


def run_shard(shard, output):
    binding = identity()
    before = source_digest()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    temporary = Path(os.environ["RUNNER_TEMP"]) / (
        f"sector-core-{binding['run_id']}-{binding['run_attempt']}-{shard}"
    )
    require(not temporary.exists(), "shard basetemp already exists")
    environment = dict(os.environ)
    environment["COVERAGE_FILE"] = str(output / ".coverage")
    environment["SECTOR_QA_SHARD_OUTPUT"] = str(output)
    with (ROOT / "quality-coverage-gate.toml").open("rb") as stream:
        targets = tomllib.load(stream)["coverage"]["targets"]
    command = [sys.executable, "-m", "pytest", *selection(shard), "-n", "4", "--dist", "loadgroup",
               "-m", "not real_image_export", "--basetemp", str(temporary),
               *(f"--cov={target}" for target in targets), "--cov-report=",
               f"--junitxml={output / 'test-results.xml'}", "-p", "tools.qa_core_shards"]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    after = source_digest()
    files = {name: {"sha256": sha(output / name), "size": (output / name).stat().st_size}
             for name in FILES if (output / name).is_file()}
    write_json(output / "manifest.json", {
        "schema_version": 1, **binding, "shard": shard, "command": command,
        "exit_code": result.returncode, "seconds": time.monotonic() - started,
        "source_before": before, "source_after": after, "files": files,
    })
    require(before == after, "source changed during shard execution")
    return result.returncode


def junit_key(node):
    from _pytest import junitxml
    names = junitxml.mangle_test_address(node)
    return ".".join(names[:-1]), junitxml.bin_xml_escape(names[-1])


def read_shard(directory, shard, binding, expected_source_digest):
    require(directory.is_dir() and not directory.is_symlink(), f"missing shard directory: {shard}")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("schema_version") == 1 and manifest.get("shard") == shard, "shard manifest identity differs")
    require(all(manifest.get(key) == value for key, value in binding.items()), "shard run/attempt/source identity differs")
    require(manifest.get("source_before") == manifest.get("source_after") == expected_source_digest, "shard source bytes differ")
    require(type(manifest.get("exit_code")) is int, "shard exit status is absent or malformed")
    require(set(manifest.get("files", {})) == set(FILES), "shard evidence inventory differs")
    require({path.name for path in directory.iterdir()} == {*FILES, "manifest.json"}, "unexpected shard evidence")
    for name in FILES:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), "shard evidence is not a regular file")
        require(manifest["files"][name] == {"sha256": sha(path), "size": path.stat().st_size}, "shard evidence hash or size differs")
    collections = [json.loads((directory / f"collection-{worker}.json").read_text()) for worker in WORKERS]
    selected = collections[0]["selected"]
    require(isinstance(selected, list) and selected and all(isinstance(node, str) for node in selected), "invalid shard collection")
    require(len(selected) == len(set(selected)), "duplicate collected node")
    require(all(shard_for_node(node) == shard for node in selected), "node collected in wrong shard")
    for worker, collection in zip(WORKERS, collections):
        require(collection.get("worker") == worker and collection.get("selected") == selected
                and collection.get("deselected") == collections[0].get("deselected"), "worker collections disagree")
    expected = Counter(junit_key(node) for node in selected)
    require(all(count == 1 for count in expected.values()), "JUnit node collision")
    tree = ET.parse(directory / "test-results.xml")
    cases = list(tree.getroot().iter("testcase"))
    actual = Counter((case.get("classname"), case.get("name")) for case in cases)
    require(actual == expected, "shard JUnit does not cover its complete collection exactly once")
    outcomes = {kind: sum(case.find(kind) is not None for case in cases) for kind in ("failure", "error", "skipped")}
    return manifest, selected, tree, outcomes


def collect_reference(output, binding):
    destination = output / "expected-core-collection.json"
    temporary = Path(os.environ["RUNNER_TEMP"]) / f"sector-core-reference-{binding['run_id']}-{binding['run_attempt']}"
    require(not destination.exists() and not temporary.exists(), "reference collection destination already exists")
    environment = dict(os.environ)
    environment.pop("SECTOR_QA_SHARD_OUTPUT", None)
    environment["SECTOR_QA_REFERENCE_OUTPUT"] = str(destination.resolve())
    command = [sys.executable, "-m", "pytest", "tests", "-n", "0", "--collect-only", "-q",
               "--dist", "loadgroup", "-m", "not real_image_export",
               "--basetemp", str(temporary), "-p", "tools.qa_core_shards"]
    with (output / "core-reference-collection.log").open("xb") as log:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
    require(result.returncode == 0, "complete reference collection failed")
    reference = json.loads(destination.read_text(encoding="utf-8"))["nodes"]
    nodes, groups = [], {}
    for row in reference:
        node = row["nodeid"]
        names = row["groups"]
        require(isinstance(node, str) and isinstance(names, list) and names == sorted(set(names)), "invalid reference node or group")
        shard = shard_for_node(node)
        if names:
            group = "_".join(names)
            groups.setdefault(group, set()).add(shard)
            node += "@" + group
        nodes.append(node)
    require(nodes and len(nodes) == len(set(nodes)), "reference contains duplicate nodes")
    require(all(len(shards) == 1 for shards in groups.values()), "shared xdist group crosses shards")
    return nodes


def merge_shards(inputs, output):
    import coverage

    binding = identity()
    before = source_digest()
    expected_names = {shard: f"sector-core-{binding['run_id']}-{binding['run_attempt']}-{shard}" for shard in SHARDS}
    require(inputs.is_dir() and {path.name for path in inputs.iterdir()} == set(expected_names.values()), "missing, duplicate or foreign shard artifacts")
    output.mkdir(parents=True, exist_ok=True)
    evidence_copy = output / "core-shards"
    require(not evidence_copy.exists(), "core evidence destination already exists")
    shutil.copytree(inputs, evidence_copy)
    require(not (ROOT / ".coverage").exists(), "pre-existing coverage data would contaminate the union")
    joined = ET.Element("testsuites")
    nodes = []
    data_files = []
    summaries = []
    for shard in SHARDS:
        directory = inputs / expected_names[shard]
        manifest, selected, tree, outcomes = read_shard(directory, shard, binding, before)
        nodes.extend(selected)
        root = tree.getroot()
        require(root.tag in {"testsuites", "testsuite"}, "invalid JUnit root")
        joined.extend(list(root) if root.tag == "testsuites" else [root])
        data_files.append(str(directory / ".coverage"))
        summaries.append({"shard": shard, "count": len(selected), "exit_code": manifest["exit_code"],
                          "manifest_sha256": sha(directory / "manifest.json"), **outcomes})
    require(len(nodes) == len(set(nodes)), "test node appears in multiple shards")
    require(Counter(nodes) == Counter(collect_reference(output, binding)), "shards do not cover the complete core reference inventory")
    require(len(data_files) == len(set(data_files)) == 4, "coverage requires four distinct data inputs")
    destination = output / "test-results.xml"
    require(not destination.exists(), "combined JUnit already exists")
    ET.ElementTree(joined).write(destination, encoding="utf-8", xml_declaration=True)
    input_hashes = {path: sha(path) for path in data_files}
    for path in data_files:
        raw = coverage.CoverageData(basename=path)
        raw.read()
        require(raw.measured_files() and not raw.has_arcs(), "core coverage must contain line data, not branch data")
    measured = coverage.Coverage(data_file=str(ROOT / ".coverage"))
    measured.combine(data_paths=data_files, strict=True, keep=True)
    measured.save()
    require(all(sha(path) == digest for path, digest in input_hashes.items()), "raw coverage input changed during combination")
    require(source_digest() == before, "source changed during evidence merge")
    failed = any(row["exit_code"] != 0 or any(row[kind] for kind in ("failure", "error", "skipped")) for row in summaries)
    write_json(output / "core-shard-summary.json", {
        **binding, "source_digest": before, "shards": summaries, "total_nodes": len(nodes),
        "coverage_inputs": [{"path": path, "sha256": sha(path)} for path in data_files],
        "combined_coverage_sha256": sha(ROOT / ".coverage"), "all_core_passed": not failed,
    })
    print(json.dumps({"total_nodes": len(nodes), "shards": summaries, "all_core_passed": not failed}))
    return int(failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--shard", choices=SHARDS, required=True)
    run.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--input", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return run_shard(args.shard, args.output) if args.command == "run" else merge_shards(args.input, args.output)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        print(f"Core shard gate failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
