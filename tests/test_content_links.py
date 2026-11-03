"""Check links in the published Markdown sources."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from markdown import Markdown


SITE_HOSTS = {"py2exe.org", "www.py2exe.org"}


class PageLinks(HTMLParser):
    """Collect links and image destinations from parsed Markdown."""

    def collect(self, html: str) -> list[str]:
        """Return the destinations in a page body."""
        self.destinations: list[str] = []
        self.feed(html)
        self.close()
        return self.destinations

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Read the destination attribute of each link or image."""
        destination_attribute = {"a": "href", "img": "src"}.get(tag)
        self.destinations.extend(
            value for name, value in attrs if name == destination_attribute and value
        )


def same_site_links(source: str) -> list[str]:
    """Return the destinations that name either public site host."""
    body = re.sub(
        r"\A---[ \t]*\n.*?^(?:---|\.\.\.)[ \t]*(?:\n|\Z)",
        "",
        source,
        count=1,
        flags=re.DOTALL | re.MULTILINE,
    )
    markdown = Markdown(
        extensions=[
            "admonition",
            "attr_list",
            "def_list",
            "footnotes",
            "md_in_html",
            "tables",
            "pymdownx.details",
            "pymdownx.inlinehilite",
            "pymdownx.magiclink",
            "pymdownx.superfences",
            "pymdownx.tabbed",
        ],
    )
    links = PageLinks().collect(markdown.convert(body))
    return [
        url
        for url in links
        if unquote(urlsplit(url).hostname or "").lower().rstrip(".") in SITE_HOSTS
    ]


def test_content_links_use_relative_paths_for_this_site() -> None:
    """Require authors to link locally without either public hostname."""
    root = Path(__file__).resolve().parents[1]
    pages = sorted((root / "content").rglob("*.md"))
    assert pages, f"No Markdown pages found under {root / 'content'}"
    violations = [
        f"{page.relative_to(root).as_posix()}: {url}"
        for page in pages
        for url in same_site_links(page.read_text(encoding="utf-8"))
    ]
    assert not violations, (
        "Use relative paths for the following same-site URLs.\n" + "\n".join(violations)
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("[Guide](https://py2exe.org/guide/)", ["https://py2exe.org/guide/"]),
        (
            "[Guide][ref]\n\n[ref]: http://www.py2exe.org/guide/",
            ["http://www.py2exe.org/guide/"],
        ),
        ("[Guide](//WWW.PY2EXE.ORG.:443/guide/)", ["//WWW.PY2EXE.ORG.:443/guide/"]),
        ("See: <https://py2exe.org/>", ["https://py2exe.org/"]),
        ("See www.py2exe.org.", ["http://www.py2exe.org"]),
        ('<a href="https://py2exe&#46;org/">Home</a>', ["https://py2exe.org/"]),
        ("![Logo](https://py2exe.org/logo.png)", ["https://py2exe.org/logo.png"]),
        ("[GitHub](https://github.com/py2exe/py2exe.org)", []),
        ("[External](https://py2exe.org.example.com/?url=https://py2exe.org/)", []),
        ("[Guide](../guide.md) [Anchor](#example)", []),
        ("---\ndescription: https://py2exe.org/\n---\n\n# Guide", []),
        (
            "`<https://py2exe.org/>`\n\n```text\n[Home](https://www.py2exe.org/)\n```",
            [],
        ),
    ],
)
def test_same_site_links(source: str, expected: list[str]) -> None:
    """Check supported link syntax, external hosts, and literal examples."""
    assert same_site_links(source) == expected
