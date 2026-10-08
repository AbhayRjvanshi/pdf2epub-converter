"""Phase 13 (engine): DualValidator execution hardening.

One resolution path for detection and execution, temp report dirs with
caller-owned reports_dir semantics, argv-list EPUBCheck commands, and
tree-kill timeouts that stay invisible behind the existing contracts.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pdf2epub.engine import packaging_and_validation as pk


def test_resolve_tool_is_the_single_resolution_path(monkeypatch):
    monkeypatch.setattr(pk.shutil, "which", lambda name: f"/resolved/{name}")
    assert pk.resolve_tool("ace") == "/resolved/ace"
    monkeypatch.setattr(pk.shutil, "which", lambda name: None)
    assert pk.resolve_tool("nope") is None


def test_unresolvable_tools_keep_the_not_installed_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)
    validator = pk.DualValidator()
    epub = tmp_path / "b.epub"
    assert validator.run_epubcheck(str(epub)) == (
        True, 0, "EPUBCheck not installed ('epubcheck') - skipped.", False,
    )
    assert validator.run_daisy_ace(str(epub)) == (
        True, {}, "Ace not installed ('ace') - skipped.", False,
    )
    # an absent tool must not create the report directory either
    assert not (tmp_path / "ace_report").exists()


def test_ace_runner_executes_the_resolved_shim(tmp_path, monkeypatch):
    captured = []

    def fake_run(cmd, timeout):
        captured.append(cmd)
        out = Path(cmd[cmd.index("--outdir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: "C:/npm/ace.cmd")
    monkeypatch.setattr(pk, "_run_with_tree_kill", fake_run)

    epub = tmp_path / "b.epub"
    epub.write_bytes(b"x")
    passed, violations, log, available = pk.DualValidator().run_daisy_ace(str(epub))
    assert available is True and passed is True
    assert captured[0][0] == "C:/npm/ace.cmd"  # the resolved path, not the bare name


def test_epubcheck_argv_lists_run_with_the_first_token_resolved(tmp_path, monkeypatch):
    captured = []

    def fake_run(cmd, timeout):
        captured.append(cmd)
        report = Path(cmd[cmd.index("--json") + 1])
        report.write_text(json.dumps({"messages": []}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        pk, "resolve_tool", lambda cmd: "C:/tools/java.exe" if cmd == "java" else None
    )
    monkeypatch.setattr(pk, "_run_with_tree_kill", fake_run)

    validator = pk.DualValidator(epubcheck_cmd=["java", "-jar", "epubcheck.jar"])
    epub = tmp_path / "b.epub"
    epub.write_bytes(b"x")
    passed, errors, log, available = validator.run_epubcheck(str(epub))
    assert available is True and passed is True and errors == 0
    assert captured[0][:3] == ["C:/tools/java.exe", "-jar", "epubcheck.jar"]
    assert str(epub) in captured[0][3]


def test_timeout_still_maps_to_the_existing_result(monkeypatch):
    def boom(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: "C:/fake/tool")
    monkeypatch.setattr(pk, "_run_with_tree_kill", boom)
    validator = pk.DualValidator()
    assert validator.run_epubcheck(str(Path("b.epub"))) == (
        False, -1, "EPUBCheck timed out.", True,
    )
    assert validator.run_daisy_ace(str(Path("b.epub"))) == (
        False, {"error": -1}, "Ace timed out.", True,
    )


def test_tree_kill_is_an_implementation_detail_of_the_timeout(monkeypatch):
    killed = []
    monkeypatch.setattr(pk, "_kill_tree", lambda proc: killed.append(proc.pid))

    class FakeProc:
        pid = 4242
        returncode = 1

        def communicate(self, timeout=None):
            if not killed:
                raise subprocess.TimeoutExpired(["ace"], 1)
            return "", ""

    monkeypatch.setattr(pk.subprocess, "Popen", lambda *a, **kw: FakeProc())
    with pytest.raises(subprocess.TimeoutExpired):
        pk._run_with_tree_kill(["ace"], timeout=1)
    assert killed == [4242]  # the tree was killed before the raise


def test_validate_leaves_no_litter_beside_the_epub(tmp_path, monkeypatch):
    validator = pk.DualValidator()

    def fake_epubcheck(path, work_dir=None):
        Path(work_dir, "epubcheck_marker.json").write_text("x", encoding="utf-8")
        return True, 0, "ok", True

    def fake_ace(path, out_dir=None):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        Path(out_dir, "ace_marker.json").write_text("x", encoding="utf-8")
        return True, {}, "ok", True

    monkeypatch.setattr(validator, "run_epubcheck", fake_epubcheck)
    monkeypatch.setattr(validator, "run_daisy_ace", fake_ace)

    epub = tmp_path / "book.epub"
    epub.write_bytes(b"x")
    validator.validate(str(epub))
    assert set(tmp_path.iterdir()) == {epub}  # reports lived and died in the temp dir


def test_reports_dir_is_caller_owned_and_survives(tmp_path, monkeypatch):
    validator = pk.DualValidator()
    reports = tmp_path / "kept-reports"

    def fake_epubcheck(path, work_dir=None):
        Path(work_dir, "epubcheck_marker.json").write_text("x", encoding="utf-8")
        return True, 0, "ok", True

    def fake_ace(path, out_dir=None):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        Path(out_dir, "ace_marker.json").write_text("x", encoding="utf-8")
        return True, {}, "ok", True

    monkeypatch.setattr(validator, "run_epubcheck", fake_epubcheck)
    monkeypatch.setattr(validator, "run_daisy_ace", fake_ace)

    epub = tmp_path / "book.epub"
    epub.write_bytes(b"x")
    validator.validate(str(epub), reports_dir=str(reports))
    assert reports.is_dir()  # caller directory never deleted
    assert (reports / "epubcheck_marker.json").exists()
    assert (reports / "ace" / "ace_marker.json").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only .cmd shim behaviour")
def test_windows_cmd_shims_resolve_and_run(tmp_path, monkeypatch):
    shim = tmp_path / "pdftool.cmd"
    shim.write_text("@echo pdftool version 1.2.3\r\n", encoding="utf-8")
    monkeypatch.setenv(
        "PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", "")
    )

    resolved = pk.resolve_tool("pdftool")
    assert resolved is not None
    # shutil.which constructs the PATHEXT extension in its declared case
    assert Path(resolved).name.lower() == "pdftool.cmd"

    proc = pk._run_with_tree_kill([resolved], timeout=15)
    assert proc.returncode == 0
    assert "1.2.3" in proc.stdout
