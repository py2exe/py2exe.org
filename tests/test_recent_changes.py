"""Check the generated history page against real local documentation histories."""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts import recent_changes


REPOSITORY_URL = "https://github.com/py2exe/py2exe.org"
RELOCATION_MESSAGE = "Move wiki pages and attachments into the Zensical layout"
CONVERSION_MESSAGE = "Convert wiki pages to Markdown and add Zensical configuration"
RECENT_CHANGES_LIMIT = 20


@dataclass
class DocumentationHistory:
    """Create committed documentation without accessing any remote service."""

    root: Path
    environment: dict[str, str] = field(init=False)
    sequence: int = 0

    def initialize(self) -> None:
        """Initialize an isolated local repository with a stable author identity."""
        self.root.mkdir(parents=True)
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        self.environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_AUTHOR_NAME": "Documentation writer",
            "GIT_AUTHOR_EMAIL": "writer@example.test",
            "GIT_COMMITTER_NAME": "Documentation writer",
            "GIT_COMMITTER_EMAIL": "writer@example.test",
        })
        self.git("init", "--quiet", "--initial-branch=main")

    def git(self, *arguments: str, environment: dict[str, str] | None = None) -> str:
        """Perform a local fixture operation and return its UTF-8 output.

        Returns:
            The successful command's standard output.
        """
        executable = shutil.which("git")
        if executable is None:
            pytest.fail("Git is required for documentation history tests")
        return subprocess.run(
            (executable, *arguments),
            cwd=self.root,
            env=self.environment if environment is None else environment,
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout

    def write(self, path: str, body: str) -> None:
        """Write UTF-8 source content beneath the fixture repository."""
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding="utf-8")

    def commit(
        self,
        message: str,
        *,
        date: str | None = None,
        author: str = "Documentation writer",
        stage: bool = True,
    ) -> str:
        """Save the complete fixture state with an explicit author date.

        Returns:
            The new commit's object ID.
        """
        self.sequence += 1
        timestamp = (
            date
            or (
                datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=self.sequence)
            ).isoformat()
        )
        if stage:
            self.git("add", "--all")
        self.git(
            "commit",
            "--quiet",
            "--allow-empty",
            "--allow-empty-message",
            "-m",
            message,
            environment={
                **self.environment,
                "GIT_AUTHOR_DATE": timestamp,
                "GIT_COMMITTER_DATE": timestamp,
                "GIT_AUTHOR_NAME": author,
            },
        )
        return self.git("rev-parse", "HEAD").strip()

    def move(self, before: str, after: str) -> None:
        """Relocate source bytes unchanged, including across the content boundary."""
        destination = self.root / after
        destination.parent.mkdir(parents=True, exist_ok=True)
        (self.root / before).rename(destination)

    def render(self) -> str:
        """Generate the page using the fixture's committed snapshot.

        Returns:
            Recent Changes Markdown.
        """
        return recent_changes.render_recent_changes(
            self.root,
            environment=self.environment,
        )


@pytest.fixture
def history(tmp_path: Path) -> DocumentationHistory:
    """Supply a repository whose Unicode path also contains spaces.

    Returns:
        A local documentation history, initially without commits.
    """
    fixture = DocumentationHistory(tmp_path / "documentation with spaces and é")
    fixture.initialize()
    return fixture


def migrated_history(history: DocumentationHistory) -> dict[str, str]:
    """Record wiki content, a legitimate edit, permissions, and the migration.

    Returns:
        Relevant original commit IDs for link assertions.
    """
    history.write("Example", "#acl All:read\nOriginal wiki content\n")
    history.write("Deleted", "A legitimately deleted page\n")
    history.write("Unretained", "Content without a retained modern page\n")
    created = history.commit("Create original wiki documentation")
    history.write("Example", "#acl All:read\nRevised wiki content\n")
    revised = history.commit("Improve the wiki article")
    history.write("Example", "#acl All:read,write\nRevised wiki content\n")
    history.commit("Adjust wiki permissions")
    (history.root / "Deleted").unlink()
    deleted = history.commit("Remove a wiki page")
    history.move("Example", "content/example.md")
    history.move("Unretained", "notes/original.txt")
    history.commit(RELOCATION_MESSAGE)
    history.write("content/example.md", "# Example\n\nConverted article.\n")
    history.commit(CONVERSION_MESSAGE)
    return {"created": created, "revised": revised, "deleted": deleted}


@pytest.mark.parametrize("modern_count", [19, 20, 21])
def test_latest_twenty_changes_fill_available_slots_from_wiki(
    history: DocumentationHistory,
    modern_count: int,
) -> None:
    """Exclude migration, permissions, and tooling while keeping twenty edits."""
    migrated_history(history)
    for number in range(modern_count):
        history.write("content/example.md", f"# Example\n\nRevision {number}.\n")
        history.commit(f"Documentation revision {number}")
    history.write("mise.toml", "[tasks]\n")
    history.commit("Contributor tooling only")

    page = history.render()

    assert page.count('??? info "') == RECENT_CHANGES_LIMIT
    assert "Contributor tooling only" not in page
    assert "Adjust wiki permissions" not in page
    assert RELOCATION_MESSAGE not in page
    assert CONVERSION_MESSAGE not in page
    assert "Create original wiki documentation" not in page
    assert ("## Imported wiki history" in page) is (modern_count < RECENT_CHANGES_LIMIT)
    assert ("**Documentation revision 0**" in page) is (
        modern_count <= RECENT_CHANGES_LIMIT
    )
    assert "[Example](example.md)" in page


def test_wiki_content_edits_survive_migration(
    history: DocumentationHistory,
) -> None:
    """Preserve meaningful archived edits and link retained pages by modern name."""
    commits = migrated_history(history)
    page = history.render()

    assert "## Imported wiki history" in page
    assert "Improve the wiki article" in page
    assert "Create original wiki documentation" in page
    assert "Remove a wiki page" not in page
    assert "Adjust wiki permissions" not in page
    assert "[Example](example.md) (added)" in page
    assert (
        f"[diff-{commits['revised']}]: {REPOSITORY_URL}/commit/{commits['revised']}"
        in page
    )


def test_archived_editorial_changes_include_body_acl_examples(
    history: DocumentationHistory,
) -> None:
    """Only leading access directives are omitted when classifying wiki edits."""
    history.write("Example", "#acl All:read\n#language en\nFirst body\n")
    history.commit("Create retained article")
    history.write("Example", "#acl All:read,write\n#language en\nFirst body\n")
    history.commit("Change access permissions")
    history.write(
        "Example",
        "#acl All:read,write\n#language en\nFirst body\n#acl shown as an example\n",
    )
    editorial = history.commit("Document an ACL example")
    history.move("Example", "content/example.md")
    history.commit(RELOCATION_MESSAGE)
    history.write("content/example.md", "# Example\n")
    history.commit(CONVERSION_MESSAGE)

    page = history.render()

    assert "Document an ACL example" in page
    assert "Change access permissions" not in page
    assert "Create retained article" in page
    assert f"[diff-{editorial}]: {REPOSITORY_URL}/commit/{editorial}" in page


@pytest.mark.parametrize(
    ("before", "after", "label"),
    [
        ("draft.md", "content/example.md", "[Example](example.md) (added)"),
        ("content/example.md", "draft.md", "Example (removed)"),
        (
            "content/previous.md",
            "content/example.md",
            "[Example](example.md) (renamed)",
        ),
    ],
)
def test_moving_pages_reports_their_effect_on_the_site(
    history: DocumentationHistory,
    before: str,
    after: str,
    label: str,
) -> None:
    """Represent entry into, exit from, and movement within the published content."""
    history.write(before, "# Example\n\nUnchanged page content.\n")
    history.write("notes/before.txt", "Unpublished notes\n")
    history.commit("Create initial content")
    history.move(before, after)
    history.move("notes/before.txt", "notes/after.txt")
    moved = history.commit("Move the documentation")

    page = history.render()

    assert "Move the documentation" in page
    assert label in page
    assert "notes/" not in page
    assert f"[diff-{moved}]: {REPOSITORY_URL}/commit/{moved}" in page


def test_current_titles_and_readable_removed_page_labels(
    history: DocumentationHistory,
) -> None:
    """Use current headings, Home, and readable fallback names in page links."""
    history.write("content/index.md", "# A heading that does not replace Home\n")
    history.write("content/topic/index.md", "An article without a heading.\n")
    history.write("content/plain-title.md", "An article without a heading.\n")
    history.write("content/spaces and é.md", "\n # Fish &amp; Chips\n")
    history.write("content/removed-page.md", "# A title unavailable after removal\n")
    history.commit("Add several pages")
    history.write("content/plain-title.md", "# A newer title\n")
    (history.root / "content/removed-page.md").unlink()
    history.commit("Update and remove documentation")
    history.write("content/recent-changes.md", "# Generated notes\n")
    history.write("content/assets/example.py", "print('attachment')\n")
    history.write("content/notes.txt", "Other content\n")
    history.commit("Regenerate and copy supporting files")

    page = history.render()

    assert "[Home](index.md)" in page
    assert "[Topic](topic/index.md)" in page
    assert "[A newer title](plain-title.md)" in page
    assert "[Fish &#38; Chips](spaces%20and%20%C3%A9.md)" in page
    assert "Removed page (removed)" in page
    assert "A title unavailable after removal" not in page
    assert "Regenerate and copy supporting files" not in page
    assert '??? info "1 updated · 1 removed"' in page
    assert '??? info "5 pages added"' in page


def test_history_is_ordered_and_grouped_by_utc_author_date(
    history: DocumentationHistory,
) -> None:
    """Normalize timezone offsets and sort independently of parent order."""
    history.write("content/example.md", "# Example\nFirst body\n")
    history.commit("Later UTC day", date="2026-11-02T02:30:00+02:00")
    history.write("content/example.md", "# Example\nSecond body\n")
    history.commit("Earlier UTC day", date="2026-11-02T01:00:00+03:00")
    history.write("content/other.md", "# Other\n")
    history.commit("Same UTC day", date="2026-11-02T02:00:00+03:00")
    page = history.render()

    assert page.index("**Later UTC day**") < page.index("**Same UTC day**")
    assert page.index("**Same UTC day**") < page.index("**Earlier UTC day**")
    assert "## November 2, 2026\n" in page
    assert "## November 1, 2026\n" in page
    assert page.count("## November 1, 2026\n") == 1
    assert "00:30 · Documentation writer ·" in page
    assert "22:00 · Documentation writer ·" in page


def test_unpaired_migration_named_commit_is_an_ordinary_edit(
    history: DocumentationHistory,
) -> None:
    """A matching subject alone must not hide a documentation change."""
    history.write("content/example.md", "# Example\n")
    history.commit(RELOCATION_MESSAGE)
    history.write("notes.txt", "Intervening ordinary commit\n")
    history.commit("Unrelated parent")
    history.write("content/example.md", "# Example\nUpdated\n")
    history.commit(CONVERSION_MESSAGE)
    page = history.render()

    assert RELOCATION_MESSAGE in page
    assert CONVERSION_MESSAGE in page
    assert "Imported wiki history" not in page


def test_tooling_only_history_has_a_useful_empty_state(
    history: DocumentationHistory,
) -> None:
    """Show a clear message when a repository has no authored page edits."""
    history.write("README.md", "# Contributor tools\n")
    history.commit("Start contributor tools")
    history.commit("Empty housekeeping commit")
    page = history.render()

    assert "# Recent Changes\n" in page
    assert "No documentation changes yet.\n" in page
    assert "generated_recent_changes: true" in page
    assert "??? info" not in page
    assert f"[commit-history]: {REPOSITORY_URL}/commits/main/\n" in page


def test_worktree_edits_do_not_change_committed_history_or_titles(
    history: DocumentationHistory,
) -> None:
    """Render only committed data and leave caller files untouched."""
    history.write("content/example.md", "# Committed title\n")
    head = history.commit("Committed documentation")
    history.write("content/example.md", "# Uncommitted title\n")
    history.write("content/local.md", "# Local page\n")
    before = history.git("status", "--porcelain=v1")
    page = history.render()

    assert "[Committed title](example.md)" in page
    assert "Uncommitted title" not in page
    assert "Local page" not in page
    assert history.git("status", "--porcelain=v1") == before
    assert history.git("rev-parse", "HEAD").strip() == head
    assert (history.root / "content/example.md").read_text(encoding="utf-8") == (
        "# Uncommitted title\n"
    )


def test_markup_in_git_metadata_is_displayed_as_literal_text(
    history: DocumentationHistory,
) -> None:
    """Prevent Git subjects, authors, and headings from becoming active markup."""
    history.write("content/example.md", "# A [title](https://invalid.example/)\n")
    history.commit(
        "[Click](https://invalid.example/) <script> & `code`",
        author="*New* **Author**",
    )
    page = history.render()

    assert "https://invalid.example/" not in page
    assert "<script>" not in page
    assert "*New*" not in page
    assert "&#91;Click&#93;" in page
    assert "&#91;title&#93;" in page
    assert "&#42;New&#42;" in page


def test_missing_git_reports_an_actionable_error(
    history: DocumentationHistory,
    tmp_path: Path,
) -> None:
    """Fail clearly when the explicit execution environment has no Git."""
    empty_path = tmp_path / "empty executable search path"
    empty_path.mkdir()
    with pytest.raises(FileNotFoundError, match="Git is required"):
        recent_changes.render_recent_changes(
            history.root,
            environment={"PATH": str(empty_path)},
        )


def test_explicit_environment_is_not_mutated(history: DocumentationHistory) -> None:
    """Caller-supplied execution settings remain unchanged by page generation."""
    history.write("content/example.md", "# Example\n")
    history.commit("Add documentation")
    before = history.environment.copy()

    assert "Add documentation" in history.render()
    assert history.environment == before


def test_default_environment_can_generate_the_page(
    history: DocumentationHistory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use inherited process settings when no explicit environment is supplied."""
    history.write("content/example.md", "# Example\n")
    history.commit("Add documentation")
    for key, value in history.environment.items():
        monkeypatch.setenv(key, value)

    assert recent_changes.render_recent_changes(history.root) == history.render()


def test_git_failures_are_not_reported_as_an_empty_history(
    history: DocumentationHistory,
) -> None:
    """Propagate failure when a repository has no committed HEAD."""
    with pytest.raises(subprocess.CalledProcessError):
        history.render()


def test_command_line_writes_the_same_utf8_page(
    history: DocumentationHistory,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone script writes Markdown on stdout from its own checkout."""
    scripts = history.root / "scripts"
    scripts.mkdir()
    source = Path(recent_changes.__file__)
    script = scripts / "recent_changes.py"
    shutil.copyfile(source, script)
    history.write("content/example.md", "# Éclair\n")
    history.commit("Publish UTF-8 documentation")
    for key, value in history.environment.items():
        monkeypatch.setenv(key, value)

    # Execute the unchanged script at a fixture checkout location. Keeping the
    # original code filename lets coverage include the command-line entry point.
    namespace = {"__name__": "__main__", "__file__": str(script)}
    exec(compile(source.read_bytes(), str(source), "exec"), namespace)

    assert capsys.readouterr().out == history.render()


def test_archived_renames_keep_changes_to_each_retained_page(
    history: DocumentationHistory,
) -> None:
    """Present archived moves when either or both names have retained articles."""
    history.write("Alpha", "First retained wiki article\n")
    history.write("unpublished.txt", "Unrelated source bytes\n")
    history.commit("Start the retained wiki history")
    history.move("Alpha", "Beta")
    history.commit("Move between retained wiki names")
    history.move("Beta", "Temporary")
    history.commit("Move away from a retained wiki name")
    history.move("Temporary", "Beta")
    history.commit("Move into a retained wiki name")
    history.move("unpublished.txt", "notes/renamed.txt")
    history.commit("Move unpublished notes")
    history.write("Alpha", "Another distinct retained article\n")
    history.commit("Restore the other retained article")
    history.move("Alpha", "content/alpha.md")
    history.move("Beta", "content/beta.md")
    history.commit(RELOCATION_MESSAGE)
    history.write("content/alpha.md", "# Alpha\n")
    history.write("content/beta.md", "# Beta\n")
    history.commit(CONVERSION_MESSAGE)

    page = history.render()

    assert "Move between retained wiki names" in page
    assert "Move away from a retained wiki name" in page
    assert "Move into a retained wiki name" in page
    assert "Move unpublished notes" not in page
    assert "[Beta](beta.md) (renamed)" in page
    assert "[Alpha](alpha.md) (added)" in page


@pytest.mark.parametrize("archived", [False, True])
def test_file_kind_changes_are_not_documentation_edits(
    history: DocumentationHistory,
    *,
    archived: bool,
) -> None:
    """Ignore file-kind metadata when the same bytes remain in a page blob."""
    path = "Example" if archived else "content/example.md"
    history.write(path, "# Example\n\nUnchanged source bytes.\n")
    history.commit("Create the example article")
    blob = history.git("hash-object", "-w", path).strip()
    # Index modes model native Git file-kind changes without creating symlinks,
    # so this fixture also runs on Windows accounts without symlink privileges.
    history.git("update-index", "--cacheinfo", f"120000,{blob},{path}")
    history.commit("Change the file kind", stage=False)
    history.git("update-index", "--cacheinfo", f"100644,{blob},{path}")
    history.commit("Restore the file kind", stage=False)
    if archived:
        history.move(path, "content/example.md")
        history.commit(RELOCATION_MESSAGE)
        history.write("content/example.md", "# Example\nConverted page\n")
        history.commit(CONVERSION_MESSAGE)

    page = history.render()

    assert "Create the example article" in page
    assert "Change the file kind" not in page
    assert "Restore the file kind" not in page
    assert "[Example](example.md) (added)" in page


def test_missing_commit_metadata_has_readable_defaults(
    history: DocumentationHistory,
) -> None:
    """Display an anonymous historical commit with an empty message clearly."""
    history.write("content/example.md", "A page without a heading.\n")
    history.git("add", "--all")
    tree = history.git("write-tree").strip()
    stamp = int(datetime(2026, 11, 1, tzinfo=UTC).timestamp())
    raw = (
        f"tree {tree}\n"
        f"author  <> {stamp} +0000\n"
        f"committer Documentation writer <writer@example.test> {stamp} +0000\n"
        "\n"
    )
    # Imported repositories can contain metadata that ordinary commit commands
    # refuse to author. Store that real Git commit rather than mocking its log.
    history.write("historical-commit.txt", raw)
    commit = history.git(
        "hash-object",
        "-t",
        "commit",
        "-w",
        "historical-commit.txt",
    ).strip()
    history.git("update-ref", "refs/heads/main", commit)

    page = history.render()

    assert "**Documentation update**" in page
    assert "00:00 · Anonymous ·" in page
    assert "[Example](example.md) (added)" in page
    assert '??? info "1 page added"' in page
