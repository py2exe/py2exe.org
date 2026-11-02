"""Test publishing results and portable command lifecycle contracts."""

import json
import os
import runpy
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from textwrap import dedent
from types import SimpleNamespace
from typing import cast

import pytest
from scripts import site_tasks as tasks


PAGES = "refs/heads/gh-pages"
ARGUMENT_ERROR = 2
CHILD_FAILURE = 23
PROCESS_GROUP_FLAG = 512
FORCE_TERMINATION_SIGNAL = 9
BUILD_PROGRAM = dedent("""\
    import os
    import subprocess
    import sys
    from pathlib import Path

    mode = os.environ.get("PUBLISH_TEST_BUILD", "complete")
    if mode == "fail":
        raise SystemExit(7)
    if mode == "signal":
        os.kill(os.getpid(), 15)
    site = Path("site")
    site.mkdir()
    if mode != "no-homepage":
        (site / "index.html").write_bytes(Path("content/index.md").read_bytes())
    if mode != "no-recent":
        (site / "recent-changes").mkdir()
        (site / "recent-changes/index.html").write_bytes(
            Path("content/recent-changes.md").read_bytes()
        )
    if mode not in {"no-asset", "race"}:
        (site / "asset.txt").write_bytes(b"rendered asset\\n")
    if mode == "race":
        command = ["git", "-C", os.environ["PUBLISH_TEST_REMOTE"]]
        parent = subprocess.check_output(
            [*command, "rev-parse", "refs/heads/gh-pages"], text=True
        ).strip()
        tree = subprocess.check_output(
            [*command, "rev-parse", f"{parent}^{{tree}}"], text=True
        ).strip()
        commit = subprocess.check_output(
            [*command, "commit-tree", tree, "-p", parent, "-m",
             "Concurrent publication"],
            text=True
        ).strip()
        subprocess.check_call(
            [*command, "update-ref", "refs/heads/gh-pages", commit, parent]
        )
    """)


def git(root: Path, *arguments: str) -> str:
    """Read or modify only the disposable repository selected by a test.

    Returns:
        UTF-8 standard output with command failures propagated.
    """
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.run(
        (executable, "-C", str(root), *arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


@pytest.fixture
def publisher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SimpleNamespace]:
    """Supply an unpublished source checkout and a file-only publication remote.

    Yields:
        Paths and environment for observable publication assertions.
    """
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    for key, value in {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Documentation Éditor",
        "GIT_AUTHOR_EMAIL": "editor@example.test",
        "GIT_COMMITTER_NAME": "Documentation Éditor",
        "GIT_COMMITTER_EMAIL": "editor@example.test",
        "GIT_AUTHOR_DATE": "2026-11-10T10:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-11-10T10:00:00+00:00",
    }.items():
        monkeypatch.setenv(key, value)
    root = tmp_path / "source with spaces and é"
    remote = tmp_path / "publication"
    workspaces = tmp_path / "workspaces"
    for path in (root, remote, workspaces):
        path.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(workspaces))
    monkeypatch.setenv("PUBLISH_TEST_REMOTE", str(remote))
    git(root, "init", "--quiet", "--initial-branch=main")
    git(remote, "init", "--quiet", "--bare", "--initial-branch=main")
    git(root, "remote", "add", "origin", remote.as_uri())
    scripts = root / "scripts"
    scripts.mkdir()
    for name in ("site_tasks.py", "recent_changes.py"):
        (scripts / name).write_bytes(Path(tasks.__file__).with_name(name).read_bytes())
    (root / "content").mkdir()
    (root / "content/index.md").write_text("# Committed homepage\n", encoding="utf-8")
    (root / "build_fixture.py").write_text(BUILD_PROGRAM, encoding="utf-8")
    command = f'"{sys.executable}" build_fixture.py'
    (root / "mise.toml").write_text(
        f"[tasks.build]\nrun = {json.dumps(command)}\n",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text("/site/\n", encoding="utf-8")
    git(root, "add", "--all")
    git(root, "commit", "--quiet", "-m", "Add contributor documentation")
    (root / "content/index.md").write_text("# Uncommitted homepage\n", encoding="utf-8")
    (root / "content/recent-changes.md").write_text(
        "Uncommitted notes\n",
        encoding="utf-8",
    )
    (root / "site").mkdir()
    (root / "site/index.html").write_text("Local preview\n", encoding="utf-8")
    before = git(root, "status", "--porcelain=v1")
    yield SimpleNamespace(root=root, remote=remote, workspaces=workspaces)
    assert git(root, "status", "--porcelain=v1") == before
    assert (root / "content/index.md").read_text(
        encoding="utf-8",
    ) == "# Uncommitted homepage\n"
    assert (root / "content/recent-changes.md").read_text(
        encoding="utf-8",
    ) == "Uncommitted notes\n"
    assert (root / "site/index.html").read_text(encoding="utf-8") == "Local preview\n"
    assert list(workspaces.iterdir()) == []


def run_publisher(fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run the public command from its installed source location.

    Returns:
        The command's documented exit status.
    """
    monkeypatch.setattr(tasks, "__file__", str(fixture.root / "scripts/site_tasks.py"))
    monkeypatch.setattr(sys, "argv", ["site_tasks.py", "publish"])
    return tasks.main()


def test_publishes_only_committed_pages_and_replaces_complete_builds(
    publisher: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish complete builds, retain history, and avoid duplicate deployments."""
    assert run_publisher(publisher, monkeypatch) == 0
    remote = publisher.remote
    first = git(remote, "rev-parse", PAGES).strip()
    assert git(remote, "for-each-ref", "--format=%(refname)") == f"{PAGES}\n"
    assert git(remote, "show", f"{PAGES}:index.html") == "# Committed homepage\n"
    assert git(remote, "show", f"{PAGES}:CNAME") == "py2exe.org\n"
    assert not git(remote, "show", f"{PAGES}:.nojekyll")
    assert git(remote, "show", f"{PAGES}:asset.txt") == "rendered asset\n"
    recent = git(remote, "show", f"{PAGES}:recent-changes/index.html")
    assert "Add contributor documentation" in recent
    assert "Uncommitted notes" not in recent
    assert git(remote, "log", "-1", "--format=%an <%ae>", PAGES).strip() == (
        "Documentation Éditor <editor@example.test>"
    )
    monkeypatch.setenv("PUBLISH_TEST_BUILD", "no-asset")
    assert run_publisher(publisher, monkeypatch) == 0
    second = git(remote, "rev-parse", PAGES).strip()
    assert second != first
    assert git(remote, "rev-parse", f"{PAGES}^").strip() == first
    assert "asset.txt" not in git(remote, "ls-tree", "-r", "--name-only", PAGES)
    assert run_publisher(publisher, monkeypatch) == 0
    assert git(remote, "rev-parse", PAGES).strip() == second


@pytest.mark.parametrize(
    ("mode", "status", "message"),
    [
        ("fail", 7, "failed with exit status"),
        ("no-homepage", 1, "did not produce the homepage"),
        ("no-recent", 1, "did not produce /recent-changes/"),
    ],
)
def test_failed_or_incomplete_builds_leave_publication_untouched(
    publisher: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    mode: str,
    status: int,
    message: str,
) -> None:
    """Reject failed artifacts and clean temporary copies without publishing."""
    monkeypatch.setenv("PUBLISH_TEST_BUILD", mode)
    assert run_publisher(publisher, monkeypatch) == status
    assert message in capsys.readouterr().err
    assert not git(publisher.remote, "for-each-ref")


def test_concurrent_publication_cannot_be_overwritten(
    publisher: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the winning publication when another deployment races ours."""
    assert run_publisher(publisher, monkeypatch) == 0
    first = git(publisher.remote, "rev-parse", PAGES).strip()
    monkeypatch.setenv("PUBLISH_TEST_BUILD", "race")
    assert run_publisher(publisher, monkeypatch) != 0
    assert git(publisher.remote, "rev-parse", f"{PAGES}^").strip() == first
    assert git(publisher.remote, "log", "-1", "--format=%s", PAGES).strip() == (
        "Concurrent publication"
    )


def test_cli_rejects_unknown_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """The installed script rejects unsupported operations before publishing."""
    monkeypatch.setattr(sys, "argv", ["site_tasks.py", "unknown"])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(tasks.__file__, run_name="__main__")
    assert error.value.code == ARGUMENT_ERROR


@pytest.mark.parametrize("capture", [False, True])
def test_commands_preserve_utf8_output_working_directory_and_environment(
    tmp_path: Path,
    *,
    capture: bool,
) -> None:
    """Execute commands without changing their working-directory or data contract."""
    program = (
        "import os, sys; from pathlib import Path; "
        "sys.stdout.reconfigure(encoding='utf-8'); "
        "Path('result.txt').write_text(os.environ['EXAMPLE'], encoding='utf-8'); "
        "print('résultat')"
    )
    result = tasks.run_command(
        (sys.executable, "-c", program),
        cwd=tmp_path,
        environment={**os.environ, "EXAMPLE": "value with spaces and é"},
        capture=capture,
    )
    assert result == ("résultat\n" if capture else "")
    assert (tmp_path / "result.txt").read_text(
        encoding="utf-8",
    ) == "value with spaces and é"


def test_commands_report_failure_and_unavailable_executables() -> None:
    """Preserve child exit status and report a command that cannot be started."""
    with pytest.raises(subprocess.CalledProcessError) as error:
        tasks.run_command((sys.executable, "-c", "raise SystemExit(23)"))
    assert error.value.returncode == CHILD_FAILURE
    with pytest.raises(FileNotFoundError):
        tasks.run_command(("nonexistent-py2exe-test-command",))


def test_disposable_directories_are_removed_after_use() -> None:
    """Remove temporary build files after a completed operation."""
    with tasks.temporary_directory("py2exe-test-") as directory:
        (directory / "file").write_text("temporary", encoding="utf-8")
    assert not directory.exists()


def test_readonly_cleanup_recovers_permission_errors_only(tmp_path: Path) -> None:
    """Delete read-only artifacts and propagate failures unrelated to permissions."""
    path = tmp_path / "readonly"
    path.write_bytes(b"artifact")
    path.chmod(stat.S_IREAD)
    tasks.remove_readonly(os.unlink, str(path), PermissionError())
    assert not path.exists()
    failure = FileNotFoundError("already absent")
    with pytest.raises(FileNotFoundError) as error:
        tasks.remove_readonly(os.unlink, str(path), failure)
    assert error.value is failure


@pytest.mark.parametrize("unsafe", ["directory-link", "file-link", "git", "pipe"])
def test_unsafe_build_artifacts_cannot_be_staged(tmp_path: Path, unsafe: str) -> None:
    """Reject links, Git metadata, and special files rather than publishing them."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("homepage", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    if unsafe in {"directory-link", "file-link"}:
        source = site if unsafe == "directory-link" else site / "index.html"
        link = tmp_path / "linked-site" if unsafe == "directory-link" else site / "link"
        try:
            link.symlink_to(source, target_is_directory=source.is_dir())
        except OSError:
            pytest.skip("This account cannot create symbolic links")
        site = link if unsafe == "directory-link" else site
    elif unsafe == "git":
        (site / ".GiT").mkdir()
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("Named pipes are unavailable on this platform")
        os.mkfifo(site / "pipe")
    with pytest.raises(
        ValueError,
        match=r"(Unsupported entry|symbolic link or junction)",
    ):
        tasks.stage_site(site, tmp_path / "deployment")
    assert not (tmp_path / "deployment").exists()


@dataclass(kw_only=True)
class NativeChild:
    """Model child lifetime at the operating-system boundary."""

    pid: int = 12345
    parent_alive: bool = True
    descendant_alive: bool = True
    slow: bool = False
    waited: bool = False
    returncode: int = 0

    def poll(self) -> int | None:
        """Report whether the parent still exists.

        Returns:
            Zero after exit, or None while running.
        """
        return None if self.parent_alive else 0

    def wait(self, timeout: float | None = None) -> int:
        """Allow one delayed exit acknowledgement.

        Returns:
            The terminated child's status.

        Raises:
            TimeoutExpired: The child has not acknowledged its termination yet.
        """
        if self.parent_alive or (self.slow and not self.waited):
            self.waited = True
            msg = "child"
            raise subprocess.TimeoutExpired(msg, timeout or 0)
        return 0

    def kill(self) -> None:
        """Terminate only this process, as a native process handle does."""
        self.parent_alive = False

    def signal_group(self, pid: int, number: int) -> None:
        """Apply a signal only to its addressed process group.

        Raises:
            ProcessLookupError: The caller selected an unknown process group.
        """
        if pid != self.pid:
            raise ProcessLookupError
        self.parent_alive = False
        if number == FORCE_TERMINATION_SIGNAL:
            self.descendant_alive = False

    def run_native(
        self,
        arguments: tuple[str, ...],
        **options: object,
    ) -> subprocess.CompletedProcess[str]:
        """Apply taskkill semantics to the addressed native process tree.

        Returns:
            The system command's successful or unsuccessful exit status.
        """
        del options
        command = tuple(argument.upper() for argument in arguments[1:])
        selected = (
            PureWindowsPath(arguments[0]).name.lower() == "taskkill.exe"
            and "/PID" in command
            and command[command.index("/PID") + 1] == str(self.pid)
        )
        if selected and "/F" in command:
            self.parent_alive = False
            if "/T" in command:
                self.descendant_alive = False
        return subprocess.CompletedProcess(arguments, 0 if selected else 1)

    def communicate(self) -> tuple[str, None]:
        """Return the native child's captured UTF-8 output.

        Returns:
            Captured standard output and absent standard error.
        """
        self.parent_alive = False
        self.descendant_alive = False
        return "résultat\n", None


@pytest.mark.parametrize(
    ("platform", "exited", "slow"),
    [
        ("nt", True, False),
        ("nt", False, False),
        ("nt", False, True),
        ("posix", False, False),
        ("posix", False, True),
        ("posix", True, False),
    ],
)
def test_cancellation_releases_native_process_resources(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    *,
    exited: bool,
    slow: bool,
) -> None:
    """Release live descendants and tolerate delayed or already-finished parents."""
    child = NativeChild(parent_alive=not exited, slow=slow)
    if platform == "nt" and exited:
        child.descendant_alive = False

    monkeypatch.setattr(os, "name", platform)
    monkeypatch.setattr(signal, "SIGKILL", FORCE_TERMINATION_SIGNAL, raising=False)
    monkeypatch.setattr(os, "killpg", child.signal_group, raising=False)
    monkeypatch.setattr(subprocess, "run", child.run_native)
    tasks.stop_process_tree(cast("subprocess.Popen[str]", child))
    assert not child.parent_alive
    assert not child.descendant_alive


def test_native_windows_commands_capture_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native Windows command can be started and collected without a shell."""
    native_start = subprocess.Popen
    native_platform = os.name

    def start_native(
        arguments: tuple[str, ...],
        **options: object,
    ) -> subprocess.Popen[str]:
        # Adapt native Windows process creation to the host OS, preserving the
        # requested program, data, pipes, and independent process-group lifetime.
        if native_platform != "nt":
            options["start_new_session"] = bool(
                cast("int", options.pop("creationflags", 0)) & PROCESS_GROUP_FLAG,
            )
        return cast("Callable[..., subprocess.Popen[str]]", native_start)(
            arguments,
            **options,
        )

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(
        subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        PROCESS_GROUP_FLAG,
        raising=False,
    )
    monkeypatch.setattr(subprocess, "Popen", start_native)
    assert (
        tasks.run_command(
            (sys.executable, "-c", "print('résultat')"),
            environment={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture=True,
        )
        == "résultat\n"
    )


def test_vanished_process_groups_are_already_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation remains successful when the OS has already reaped a group."""
    child = NativeChild(parent_alive=False)
    child.descendant_alive = False

    def absent_group(pid: int, number: int) -> None:
        del pid, number
        raise ProcessLookupError

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "SIGKILL", FORCE_TERMINATION_SIGNAL, raising=False)
    monkeypatch.setattr(os, "killpg", absent_group, raising=False)
    tasks.stop_process_tree(cast("subprocess.Popen[str]", child))
    assert not child.parent_alive
    assert not child.descendant_alive


def test_signal_interruption_cleans_commands_and_restores_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report termination once while allowing child and directory cleanup."""
    child = NativeChild()
    handlers = {
        number: signal.getsignal(number) for number in tasks.termination_numbers()
    }

    def receive_signal() -> tuple[str, None]:
        signal.raise_signal(signal.SIGTERM)
        return "", None

    def start_native(*arguments: object, **options: object) -> NativeChild:
        del arguments, options
        return child

    monkeypatch.setattr(child, "communicate", receive_signal)
    monkeypatch.setattr(subprocess, "Popen", start_native)
    monkeypatch.setattr(subprocess, "run", child.run_native)
    monkeypatch.setattr(os, "killpg", child.signal_group, raising=False)
    with (
        pytest.raises(tasks.TaskInterruptedError) as error,
        tasks.termination_signals(),
    ):
        tasks.run_command((sys.executable, "-c", "pass"))
    assert error.value.number == signal.SIGTERM
    assert not child.parent_alive
    assert not child.descendant_alive
    assert {number: signal.getsignal(number) for number in handlers} == handlers


@pytest.mark.parametrize("failure", ["signal", "negative-status", "os-error"])
def test_cli_reports_native_failures_with_conventional_exit_statuses(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    """Translate native interruption, child failure, and startup errors for callers."""
    child = NativeChild()

    def start_native(*arguments: object, **options: object) -> NativeChild:
        del arguments, options
        if failure == "os-error":
            msg = "cannot start command"
            raise OSError(msg)
        child.returncode = -9
        if failure == "signal":
            signal.raise_signal(signal.SIGTERM)
        return child

    monkeypatch.setattr(sys, "argv", ["site_tasks.py", "publish"])
    monkeypatch.setattr(subprocess, "Popen", start_native)
    assert tasks.main() == (
        143 if failure == "signal" else 137 if failure == "negative-status" else 1
    )
    stderr = capsys.readouterr().err
    if failure == "negative-status":
        assert "failed with exit status -9" in stderr
    elif failure == "os-error":
        assert "cannot start command" in stderr


def test_linked_content_cannot_write_generated_history(
    publisher: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reject an OS-reported content junction before adding generated files."""
    original = Path.is_junction

    def is_junction(path: Path) -> bool:
        return path.name == "content" or original(path)

    monkeypatch.setattr(Path, "is_junction", is_junction)
    assert run_publisher(publisher, monkeypatch) == 1
    assert (
        "content directory must not be a symbolic link or junction"
        in capsys.readouterr().err
    )
    assert not git(publisher.remote, "for-each-ref")


def test_junction_build_directory_cannot_be_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an OS-reported build junction before copying or altering its files."""
    site = tmp_path / "site"
    site.mkdir()
    homepage = site / "index.html"
    homepage.write_text("unchanged homepage", encoding="utf-8")
    original = Path.is_junction

    def is_junction(path: Path) -> bool:
        return path == site or original(path)

    monkeypatch.setattr(Path, "is_junction", is_junction)
    with pytest.raises(ValueError, match="symbolic link or junction"):
        tasks.stage_site(site, tmp_path / "deployment")
    assert homepage.read_text(encoding="utf-8") == "unchanged homepage"
    assert not (tmp_path / "deployment").exists()
