"""Run duration-balanced pytest shards and combine their exact-run evidence."""

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

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Every suite is split into a fixed number of jobs. The assignment of a test
# to a job is computed from the collected inventory, so new tests and modules
# join a shard without a manual list.
SUITES = {"core": 12, "branch": 4}
SHARDS = (*(f"{suite}-{index:02d}" for suite, count in SUITES.items() for index in range(1, count + 1)), "real")
DURATIONS = ROOT / "tools" / "qa_shard_durations.json"
# A module's ungrouped tests are cut into contiguous units of about this many
# seconds, so that module-scoped fixtures are recomputed in few workers.
CHUNK_SECONDS = 600.0
WORKERS = tuple(f"gw{number}" for number in range(4))
FILES = (".coverage", "test-results.xml", *(f"collection-{worker}.json" for worker in WORKERS))
REAL_TESTS = (
    ("viz", ("tests/test_viz.py",)),
    ("report", ("tests/test_report_rendered.py::test_issued_report_renders_every_page_and_retains_expected_content",)),
    ("manual", ("tests/test_manual_rendered.py::test_issued_manual_renders_every_page_and_retains_navigation",)),
)
REAL_RENDERS = (("report", "tools/report_render_fixture.py"), ("manual", "tools/manual_render_fixture.py"))
REAL_FILES = (".coverage", *(f"test-results-real-{name}.xml" for name, _ in REAL_TESTS))
REAL_PHASES = (*(name for name, _ in REAL_TESTS), *(f"render-{name}" for name, _ in REAL_RENDERS))
# Hang guard (owner rule, 9 November 2026): each real-image phase normally takes
# less than 1 min. A phase that runs longer than this limit is a hang. Its process
# tree is stopped, the phase is recorded with REAL_PHASE_TIMEOUT_EXIT and the next
# phase runs, so that the shard fails in minutes with its evidence uploaded. All
# phases together get at most REAL_SHARD_BUDGET_S, which is less than the 20 min
# step limit in qa.yml, so the manifest is always written. A phase that starts
# with less than REAL_PHASE_MIN_S of the budget left does not run and is recorded
# as stopped. The real-image test guard (tests/real_image_guard.py) uses the same
# exit code.
REAL_PHASE_LIMIT_S = 480.0
REAL_SHARD_BUDGET_S = 900.0
REAL_PHASE_MIN_S = 30.0
REAL_PHASE_TIMEOUT_EXIT = 124
# A rerun of failed jobs uploads new evidence only for the shards that ran again.
# When the kept evidence of an earlier attempt is absent or not valid, the gate
# fails with this instruction.
FULL_RERUN = "Run all jobs of the workflow again (a full rerun)."
ARTIFACT_NAME = re.compile(r"sector-core-(?P<run>[1-9][0-9]*)-(?P<attempt>[1-9][0-9]*)-(?P<shard>[a-z]+(?:-[0-9]{2})?)")
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


def shard_position(shard):
    require(shard in SHARDS, "unknown shard")
    require(shard != "real", "the real-image shard has no balanced position")
    suite, index = shard.split("-")
    return suite, int(index)


def suite_shards(suite):
    return [shard for shard in SHARDS if shard.startswith(suite + "-")]


def load_durations(path=DURATIONS):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    require(data.get("schema_version") == 1, "unknown shard duration schema")
    return data


def seconds_for(key, durations):
    if key in durations["tests"]:
        return float(durations["tests"][key])
    module = key.split("::", 1)[0]
    return float(durations["modules"].get(module, durations["default_seconds"]))


def module_seconds(key, durations):
    """Return the mean CI duration of all tests in the module of a node."""
    module = key.split("::", 1)[0]
    return float(durations["module_means"].get(module, durations["default_seconds"]))


def node_groups(item):
    return sorted({str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                   for mark in item.iter_markers("xdist_group")})


def node_row(item):
    """Return the reference identity and xdist group of a collected item."""
    group = "_".join(node_groups(item))
    node = item.nodeid
    if group and not node.endswith("@" + group):
        node += "@" + group
    return node, group


def assign(rows, count, durations=None):
    """Map each (node, group) row to a shard number from 1 to count.

    A whole xdist group is one unit; the other tests form contiguous module
    units. The units are placed longest first on the least-loaded shard.
    """
    durations = durations if durations is not None else load_durations()
    units, groups, chunks = [], {}, {}
    for position, (node, group) in enumerate(rows):
        if group:
            unit = groups.get(group)
            if unit is None:
                unit = groups[group] = [position, 0.0, []]
                units.append(unit)
        else:
            module = node.split("::", 1)[0]
            unit = chunks.get(module)
            if unit is None or unit[1] >= CHUNK_SECONDS:
                unit = chunks[module] = [position, 0.0, []]
                units.append(unit)
        unit[1] += seconds_for(node, durations)
        unit[2].append(node)
    loads = [0.0] * count
    owners = {}
    for _, seconds, nodes in sorted(units, key=lambda unit: (-unit[1], unit[0])):
        index = min(range(count), key=lambda number: (loads[number], number))
        loads[index] += seconds
        owners.update(dict.fromkeys(nodes, index + 1))
    return owners


def pytest_deselected(items):
    _deselected.extend(item.nodeid for item in items)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    shard = os.environ.get("SECTOR_QA_SHARD")
    if not shard:
        return
    suite, index = shard_position(shard)
    rows = [node_row(item) for item in items]
    owners = assign(rows, SUITES[suite])
    items[:] = [item for item, (node, _) in zip(items, rows) if owners[node] == index]


def pytest_collection_finish(session):
    destination = os.environ.get("SECTOR_QA_SHARD_OUTPUT")
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker is None:
        reference = os.environ.get("SECTOR_QA_REFERENCE_OUTPUT")
        if reference:
            nodes = [{"nodeid": item.nodeid, "groups": node_groups(item)} for item in session.items]
            write_json(reference, {"nodes": nodes, "deselected": _deselected})
        return
    if not destination:
        return
    require(worker in WORKERS, "unexpected collection worker")
    write_json(Path(destination) / f"collection-{worker}.json", {
        "worker": worker, "selected": [item.nodeid for item in session.items],
        "deselected": _deselected,
    })


def contract():
    with (ROOT / "quality-coverage-gate.toml").open("rb") as stream:
        return tomllib.load(stream)


def suite_command(suite):
    """Return the pytest selection, marker filter and coverage options of a suite."""
    data = contract()
    if suite == "core":
        return ["tests", "-m", "not real_image_export", *(f"--cov={target}" for target in data["coverage"]["targets"])]
    require(suite == "branch", "unknown suite")
    branch = data["branch_coverage"]
    return [*branch["tests"], *(f"--cov={target}" for target in branch["targets"]), "--cov-branch"]


def process_listing():
    """Return one "pid ppid" line for each process of the machine."""
    if os.name == "nt":
        command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }"]
    else:
        command = ["ps", "-A", "-o", "pid=,ppid="]
    return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False).stdout


def descendants(pid):
    """Return every process below ``pid`` by parent links, also in other sessions.

    The shared image exporter calls ``os.setsid()`` on POSIX, so it and its
    browser leave the process group of the phase, but their parent links stay.
    """
    listing = process_listing()
    children = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 2 and all(field.isdigit() for field in fields):
            children.setdefault(int(fields[1]), []).append(int(fields[0]))
    found, pending = [], [pid]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found and child != pid:
                found.append(child)
                pending.append(child)
    return found


def stop_descendants(pid):
    """Stop every process below ``pid`` while its parent links exist.

    The real-image test guard calls this before it stops its own process, so
    that a hung browser or exporter does not survive into the next phase.
    """
    found = descendants(pid)
    if os.name == "nt":
        for child in found:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(child)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
        return found
    import signal

    for child in found:
        try:
            os.kill(child, signal.SIGKILL)
        except OSError:
            pass
    return found


def stop_process_tree(process):
    """Stop a timed-out phase and every browser or worker process below it."""
    if os.name == "nt":
        # taskkill follows the parent links, also into the exporter's job.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        import signal

        # Collect the tree before the kill: an orphan loses its parent link.
        below = descendants(process.pid)
        groups = {process.pid}
        for pid in below:
            try:
                groups.add(os.getpgid(pid))
            except OSError:
                pass
        groups.discard(os.getpgrp())
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except OSError:
                pass
        for pid in below:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=60)


def run_real_phase(command, *, cwd, env, limit=None):
    """Run one real-image phase, and stop it when it exceeds the hang limit."""
    limit = REAL_PHASE_LIMIT_S if limit is None else limit
    process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=os.name != "nt")
    try:
        return process.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        print(f"Real-image phase did not finish in {limit:.0f} s (hang limit); "
              f"its process tree is stopped: {' '.join(command[1:4])}", file=sys.stderr, flush=True)
        stop_process_tree(process)
        return REAL_PHASE_TIMEOUT_EXIT


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
    # A shard selects its tests only from its own variables, never from a caller's.
    for name in ("SECTOR_QA_SHARD", "SECTOR_QA_SHARD_OUTPUT", "SECTOR_QA_REFERENCE_OUTPUT"):
        environment.pop(name, None)
    environment["COVERAGE_FILE"] = str(output / ".coverage")
    started = time.monotonic()
    if shard == "real":
        temporary.mkdir(parents=True)
        commands, phases = [], {}
        deadline = started + REAL_SHARD_BUDGET_S

        def bounded_phase(phase, command):
            commands.append(command)
            remaining = deadline - time.monotonic()
            if remaining < REAL_PHASE_MIN_S:
                print(f"Real-image phase {phase} does not start: the shard budget of "
                      f"{REAL_SHARD_BUDGET_S:.0f} s is used.", file=sys.stderr, flush=True)
                phases[phase] = REAL_PHASE_TIMEOUT_EXIT
                return
            phases[phase] = run_real_phase(command, cwd=ROOT, env=environment,
                                           limit=min(REAL_PHASE_LIMIT_S, remaining))

        for name, selection in REAL_TESTS:
            bounded_phase(name, [sys.executable, "-m", "pytest", *selection, "-n", "0", "-m", "real_image_export",
                                 "--basetemp", str(temporary / f"real-{name}"),
                                 *(f"--cov={target}" for target in contract()["coverage"]["targets"]),
                                 "--cov-append", "--cov-report=",
                                 f"--junitxml={output / f'test-results-real-{name}.xml'}"])
        for name, script in REAL_RENDERS:
            bounded_phase(f"render-{name}", [sys.executable, script, "--output", str(output / name)])
        exit_code = max(phases.values(), key=abs)
        names = REAL_FILES
        details = {"commands": commands, "phases": phases}
    else:
        suite, _ = shard_position(shard)
        environment["SECTOR_QA_SHARD_OUTPUT"] = str(output)
        environment["SECTOR_QA_SHARD"] = shard
        command = [sys.executable, "-m", "pytest", *suite_command(suite), "-n", "4", "--dist", "loadgroup",
                   "--basetemp", str(temporary), "--cov-report=",
                   f"--junitxml={output / 'test-results.xml'}", "-p", "tools.qa_core_shards"]
        exit_code = subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode
        names = FILES
        details = {"command": command}
    after = source_digest()
    files = {name: {"sha256": sha(output / name), "size": (output / name).stat().st_size}
             for name in names if (output / name).is_file()}
    write_json(output / "manifest.json", {
        "schema_version": 1, **binding, "shard": shard, **details,
        "exit_code": exit_code, "seconds": time.monotonic() - started,
        "source_before": before, "source_after": after, "files": files,
    })
    require(before == after, "source changed during shard execution")
    return exit_code


def junit_key(node):
    from _pytest import junitxml
    names = junitxml.mangle_test_address(node)
    return ".".join(names[:-1]), junitxml.bin_xml_escape(names[-1])


def read_manifest(directory, shard, binding, expected_source_digest, names):
    require(directory.is_dir() and not directory.is_symlink(), f"missing shard directory: {shard}")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("schema_version") == 1 and manifest.get("shard") == shard, "shard manifest identity differs")
    require(all(manifest.get(key) == value for key, value in binding.items()), "shard run/attempt/source identity differs")
    require(manifest.get("source_before") == manifest.get("source_after") == expected_source_digest, "shard source bytes differ")
    require(type(manifest.get("exit_code")) is int, "shard exit status is absent or malformed")
    require(set(manifest.get("files", {})) == set(names), "shard evidence inventory differs")
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), "shard evidence is not a regular file")
        require(manifest["files"][name] == {"sha256": sha(path), "size": path.stat().st_size}, "shard evidence hash or size differs")
    return manifest


def outcomes(cases):
    return {kind: sum(case.find(kind) is not None for case in cases) for kind in ("failure", "error", "skipped")}


def read_shard(directory, shard, binding, expected_source_digest, expected_nodes):
    manifest = read_manifest(directory, shard, binding, expected_source_digest, FILES)
    require({path.name for path in directory.iterdir()} == {*FILES, "manifest.json"}, "unexpected shard evidence")
    collections = [json.loads((directory / f"collection-{worker}.json").read_text()) for worker in WORKERS]
    selected = collections[0]["selected"]
    require(isinstance(selected, list) and selected and all(isinstance(node, str) for node in selected), "invalid shard collection")
    require(len(selected) == len(set(selected)), "duplicate collected node")
    require(set(selected) == set(expected_nodes), "shard collection differs from its balanced assignment")
    for worker, collection in zip(WORKERS, collections):
        require(collection.get("worker") == worker and collection.get("selected") == selected
                and collection.get("deselected") == collections[0].get("deselected"), "worker collections disagree")
    expected = Counter(junit_key(node) for node in selected)
    require(all(count == 1 for count in expected.values()), "JUnit node collision")
    tree = ET.parse(directory / "test-results.xml")
    cases = list(tree.getroot().iter("testcase"))
    actual = Counter((case.get("classname"), case.get("name")) for case in cases)
    require(actual == expected, "shard JUnit does not cover its complete collection exactly once")
    return manifest, selected, tree, outcomes(cases)


def read_real(directory, binding, expected_source_digest):
    recorded = directory / "manifest.json"
    if directory.is_dir() and recorded.is_file():
        phases = json.loads(recorded.read_text(encoding="utf-8")).get("phases")
        stopped = sorted(name for name, code in (phases.items() if isinstance(phases, dict) else ())
                         if code == REAL_PHASE_TIMEOUT_EXIT)
        require(not stopped, f"real-image phase exceeded the hang limit: {', '.join(stopped)}")
    manifest = read_manifest(directory, "real", binding, expected_source_digest, REAL_FILES)
    require({path.name for path in directory.iterdir()} == {*REAL_FILES, *(name for name, _ in REAL_RENDERS), "manifest.json"},
            "unexpected real-image evidence")
    require(all((directory / name).is_dir() and not (directory / name).is_symlink() for name, _ in REAL_RENDERS),
            "real-image render evidence is not a directory")
    phases = manifest.get("phases")
    require(isinstance(phases, dict) and set(phases) == set(REAL_PHASES)
            and all(type(value) is int for value in phases.values()), "real-image phase inventory differs")
    counts = {}
    for name, _ in REAL_TESTS:
        cases = list(ET.parse(directory / f"test-results-real-{name}.xml").getroot().iter("testcase"))
        require(cases, f"real-image phase {name} ran no test")
        counts[name] = {"count": len(cases), **outcomes(cases)}
    return manifest, counts


def collect_reference(output, binding, suite):
    destination = output / f"expected-{suite}-collection.json"
    temporary = Path(os.environ["RUNNER_TEMP"]) / f"sector-{suite}-reference-{binding['run_id']}-{binding['run_attempt']}"
    require(not destination.exists() and not temporary.exists(), "reference collection destination already exists")
    environment = dict(os.environ)
    environment.pop("SECTOR_QA_SHARD_OUTPUT", None)
    environment.pop("SECTOR_QA_SHARD", None)
    environment["SECTOR_QA_REFERENCE_OUTPUT"] = str(destination.resolve())
    selection = [token for token in suite_command(suite) if not token.startswith("--cov")]
    command = [sys.executable, "-m", "pytest", *selection, "-n", "0", "--collect-only", "-q",
               "--dist", "loadgroup", "--basetemp", str(temporary), "-p", "tools.qa_core_shards"]
    with (output / f"{suite}-reference-collection.log").open("xb") as log:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
    require(result.returncode == 0, f"complete {suite} reference collection failed")
    rows = []
    for row in json.loads(destination.read_text(encoding="utf-8"))["nodes"]:
        node, names = row["nodeid"], row["groups"]
        require(isinstance(node, str) and isinstance(names, list) and names == sorted(set(names)), "invalid reference node or group")
        group = "_".join(names)
        rows.append((node + "@" + group if group else node, group))
    nodes = [node for node, _ in rows]
    require(nodes and len(nodes) == len(set(nodes)), "reference contains duplicate nodes")
    return rows


def select_artifacts(inputs, binding):
    """Map each shard to the newest evidence of this run, up to this attempt.

    A rerun of failed jobs runs only the failed shards and their dependants
    again. The other shards keep the evidence of an earlier attempt of the same
    run, which checked out the same source revision. The newest attempt of each
    shard governs, so a shard that fails again stays failed. Each artifact must
    also carry the run binding of its own attempt.
    """
    require(inputs.is_dir(), f"no shard evidence was downloaded. {FULL_RERUN}")
    current = int(binding["run_attempt"])
    newest = {}
    for path in inputs.iterdir():
        match = ARTIFACT_NAME.fullmatch(path.name)
        require(match is not None and match["run"] == binding["run_id"] and match["shard"] in SHARDS
                and int(match["attempt"]) <= current, f"foreign shard artifact: {path.name}")
        attempt = int(match["attempt"])
        if attempt > newest.get(match["shard"], (0, ""))[0]:
            newest[match["shard"]] = (attempt, path.name)
    missing = [shard for shard in SHARDS if shard not in newest]
    require(not missing, f"no evidence in any attempt of run {binding['run_id']} for shard "
                         f"{', '.join(missing)}. {FULL_RERUN}")
    names = {shard: name for shard, (_, name) in newest.items()}
    bindings = {shard: {**binding, "run_attempt": str(attempt)} for shard, (attempt, _) in newest.items()}
    return names, bindings


def read_kept(shard, binding, current_attempt, reader):
    """Read one shard's evidence; name the full rerun when kept evidence fails."""
    try:
        return reader()
    except (QaShardError, OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        attempt = int(binding["run_attempt"])
        if attempt < int(current_attempt):
            raise QaShardError(f"kept evidence of shard {shard} from attempt {attempt} is not valid ({exc}). "
                               f"{FULL_RERUN}") from exc
        raise


def merge_suite(suite, inputs, output, binding, before, names, bindings):
    rows = collect_reference(output, binding, suite)
    owners = assign(rows, SUITES[suite])
    shards = suite_shards(suite)
    joined = ET.Element("testsuites")
    nodes, data_files, summaries, located = [], [], [], {}
    for index, shard in enumerate(shards, 1):
        directory = inputs / names[shard]
        expected = [node for node, owner in owners.items() if owner == index]
        manifest, selected, tree, counts = read_kept(
            shard, bindings[shard], binding["run_attempt"],
            lambda directory=directory, shard=shard, expected=expected: read_shard(
                directory, shard, bindings[shard], before, expected))
        nodes.extend(selected)
        located.update(dict.fromkeys(selected, shard))
        root = tree.getroot()
        require(root.tag in {"testsuites", "testsuite"}, "invalid JUnit root")
        joined.extend(list(root) if root.tag == "testsuites" else [root])
        data_files.append(str(directory / ".coverage"))
        summaries.append({"shard": shard, "attempt": int(bindings[shard]["run_attempt"]),
                          "count": len(selected), "exit_code": manifest["exit_code"],
                          "seconds": manifest.get("seconds"), "manifest_sha256": sha(directory / "manifest.json"), **counts})
    require(len(nodes) == len(set(nodes)), "test node appears in multiple shards")
    require(Counter(nodes) == Counter(node for node, _ in rows), f"shards do not cover the complete {suite} reference inventory")
    groups = {}
    for node, group in rows:
        if group:
            groups.setdefault(group, set()).add(located[node])
    require(all(len(owners) == 1 for owners in groups.values()), "shared xdist group crosses shards")
    for path in data_files:
        raw = coverage_data(path)
        if suite == "core":
            require(raw.measured_files() and not raw.has_arcs(), "core coverage must contain line data, not branch data")
        else:
            require(raw.measured_files() and raw.has_arcs(), "decision-branch coverage must contain branch data")
    return joined, nodes, data_files, summaries


def coverage_data(path):
    import coverage

    raw = coverage.CoverageData(basename=path)
    raw.read()
    return raw


def combine(destination, data_files):
    import coverage

    input_hashes = {path: sha(path) for path in data_files}
    measured = coverage.Coverage(data_file=str(destination))
    measured.combine(data_paths=data_files, strict=True, keep=True)
    measured.save()
    require(all(sha(path) == digest for path, digest in input_hashes.items()), "raw coverage input changed during combination")
    return measured


def write_junit(element, destination):
    require(not destination.exists(), "combined JUnit already exists")
    ET.ElementTree(element).write(destination, encoding="utf-8", xml_declaration=True)


def merge_shards(inputs, output):
    binding = identity()
    before = source_digest()
    names, bindings = select_artifacts(inputs, binding)
    output.mkdir(parents=True, exist_ok=True)
    evidence_copy = output / "core-shards"
    require(not evidence_copy.exists(), "core evidence destination already exists")
    shutil.copytree(inputs, evidence_copy)
    require(not (ROOT / ".coverage").exists(), "pre-existing coverage data would contaminate the union")
    branch_data = output / "branch.coverage"
    require(not branch_data.exists(), "pre-existing branch coverage data would contaminate the union")

    real_directory = inputs / names["real"]
    real_manifest, real_counts = read_kept(
        "real", bindings["real"], binding["run_attempt"],
        lambda: read_real(real_directory, bindings["real"], before))
    real_coverage = str(real_directory / ".coverage")
    raw = coverage_data(real_coverage)
    require(raw.measured_files() and not raw.has_arcs(), "real-image coverage must contain line data, not branch data")
    for name in (*(f"test-results-real-{name}.xml" for name, _ in REAL_TESTS), *(name for name, _ in REAL_RENDERS)):
        destination = output / name
        require(not destination.exists(), "real-image evidence destination already exists")
        (shutil.copytree if (real_directory / name).is_dir() else shutil.copy2)(real_directory / name, destination)

    core, core_nodes, core_data, core_summaries = merge_suite("core", inputs, output, binding, before, names, bindings)
    write_junit(core, output / "test-results.xml")
    combine(ROOT / ".coverage", [*core_data, real_coverage])

    branch, branch_nodes, branch_files, branch_summaries = merge_suite("branch", inputs, output, binding, before, names, bindings)
    write_junit(branch, output / "test-results-branches.xml")
    measured = combine(branch_data, branch_files)
    results = output / "branch-coverage.json"
    require(not results.exists(), "branch coverage results already exist")
    measured.json_report(outfile=str(results))
    require(source_digest() == before, "source changed during evidence merge")

    def failed(rows):
        return any(row["exit_code"] != 0 or any(row[kind] for kind in ("failure", "error", "skipped")) for row in rows)

    real_failed = real_manifest["exit_code"] != 0 or any(row["failure"] or row["error"] for row in real_counts.values())
    summary = {
        "total_nodes": len(core_nodes), "branch_nodes": len(branch_nodes),
        "real_tests": sum(row["count"] for row in real_counts.values()),
        "all_core_passed": not failed(core_summaries), "all_branch_passed": not failed(branch_summaries),
        "all_real_passed": not real_failed,
    }
    write_json(output / "core-shard-summary.json", {
        **binding, "source_digest": before, **summary, "shards": core_summaries,
        "branch_shards": branch_summaries,
        "real": {"attempt": int(bindings["real"]["run_attempt"]), "phases": real_manifest["phases"], "tests": real_counts},
        "coverage_inputs": [{"path": path, "sha256": sha(path)} for path in (*core_data, real_coverage)],
        "combined_coverage_sha256": sha(ROOT / ".coverage"),
        "branch_coverage_inputs": [{"path": path, "sha256": sha(path)} for path in branch_files],
        "combined_branch_coverage_sha256": sha(branch_data),
    })
    print(json.dumps({**summary, "seconds": {row["shard"]: round(row["seconds"] or 0) for row in (*core_summaries, *branch_summaries)}}))
    return int(not (summary["all_core_passed"] and summary["all_branch_passed"] and summary["all_real_passed"]))


def refresh_durations(inputs, destination):
    """Write the duration table from the JUnit evidence of downloaded core shards."""
    tests, small, everything = {}, {}, {}
    for directory in sorted(inputs.iterdir()):
        if not re.search(r"-core-[0-9]{2}$", directory.name):
            continue
        selected = json.loads((directory / "collection-gw0.json").read_text())["selected"]
        nodes = {junit_key(node): node for node in selected}
        for case in ET.parse(directory / "test-results.xml").getroot().iter("testcase"):
            node = nodes[(case.get("classname"), case.get("name"))]
            seconds = float(case.get("time") or 0.0)
            everything.setdefault(node.split("::", 1)[0], []).append(seconds)
            if seconds >= 1.0:
                tests[node] = round(seconds, 1)
            else:
                small.setdefault(node.split("::", 1)[0], []).append(seconds)
    require(tests, "no core shard timing evidence")
    modules = {module: round(sum(values) / len(values), 3) for module, values in sorted(small.items())}
    means = {module: round(sum(values) / len(values), 3) for module, values in sorted(everything.items())}
    value = {"schema_version": 1, "default_seconds": 2.0, "modules": modules, "module_means": means,
             "tests": dict(sorted(tests.items()))}
    # The refresh replaces the checked-in table, so it must overwrite the file.
    Path(destination).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--shard", choices=SHARDS, required=True)
    run.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--input", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    durations = commands.add_parser("durations")
    durations.add_argument("--input", type=Path, required=True)
    durations.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_shard(args.shard, args.output)
        if args.command == "merge":
            return merge_shards(args.input, args.output)
        return refresh_durations(args.input, args.output)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        print(f"Core shard gate failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
