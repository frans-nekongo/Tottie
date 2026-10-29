"""Feature proofs for minisite. Each required feature gets its own test."""
import subprocess
import sys
from pathlib import Path

import pytest

from minisite.builder import build_site, render_inline, render_markdown

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------- headings ---

def test_headings_all_levels_and_ids():
    html = render_markdown("# One\n## Two\n### Three\n#### Four\n##### Five\n###### Six\n")
    for i, word in enumerate(
        ["One", "Two", "Three", "Four", "Five", "Six"], start=1
    ):
        assert f'<h{i} id="{word.lower()}">{word}</h{i}>' in html


def test_heading_inline_formatting():
    html = render_markdown("# Hello **bold** and `code`\n")
    assert "<h1" in html and "<strong>bold</strong>" in html
    assert "<code>code</code>" in html


# ----------------------------------------------------------------- bold ---

def test_bold():
    assert render_inline("a **strong** b") == "a <strong>strong</strong> b"


def test_bold_multichar_and_multiple():
    html = render_inline("**one** plus **two words**")
    assert html == "<strong>one</strong> plus <strong>two words</strong>"


# --------------------------------------------------------------- italic ---

def test_italic():
    assert render_inline("a *soft* b") == "a <em>soft</em> b"


def test_bold_and_italic_coexist():
    html = render_inline("**b** and *i*")
    assert "<strong>b</strong>" in html and "<em>i</em>" in html


# ------------------------------------------------------------ code span ---

def test_inline_code_immune_to_formatting():
    html = render_inline("`**not bold** and *not italic*`")
    assert "<code>**not bold** and *not italic*</code>" in html
    assert "<strong>" not in html and "<em>" not in html


# ----------------------------------------------------------- code block ---

def test_fenced_code_block():
    html = render_markdown("```\nprint('hi')\n```\n")
    assert "<pre><code>" in html
    assert "print(&#x27;hi&#x27;)" in html


def test_fenced_code_block_with_language():
    html = render_markdown("```python\nx = 1\n```\n")
    assert '<pre><code class="language-python">' in html


def test_code_block_ignores_markdown():
    html = render_markdown("```\n# not a heading **not bold**\n```\n")
    assert "<h1" not in html and "<strong>" not in html
    assert "# not a heading **not bold**" in html


def test_unclosed_fence_still_emitted():
    html = render_markdown("```\nleftover\n")
    assert "<pre><code>leftover</code></pre>" in html


# ---------------------------------------------------------------- links ---

def test_link():
    html = render_inline("[Tottie](https://example.com)")
    assert html == '<a href="https://example.com">Tottie</a>'


def test_link_with_title_attribute():
    html = render_inline('[a](https://x.test "tip")')
    assert html == '<a href="https://x.test">a</a>'


def test_link_url_with_star_survives_emphasis():
    html = render_inline("[a](https://x.test/a*b)")
    assert '<a href="https://x.test/a*b">a</a>' in html


# -------------------------------------------------------- blocks/extras ---

def test_paragraphs_lists_quote_hr():
    html = render_markdown("Hello\n\n- a\n- b\n\n1. x\n2. y\n\n> quoted\n\n---\n")
    assert "<p>Hello</p>" in html
    assert "<ul>" in html and "<li>a</li>" in html
    assert "<ol>" in html and "<li>x</li>" in html
    assert "<blockquote>quoted</blockquote>" in html
    assert "<hr>" in html


def test_html_is_escaped():
    html = render_markdown("<script>alert(1)</script>\n")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# -------------------------------------------------------- nested folders ---

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def nested_docs(tmp_path):
    _write(tmp_path / "index.md", "# Home\n\nWelcome to **home**.\n")
    _write(tmp_path / "guide" / "install.md",
           "# Install\n\nRun `pip install x`.\n\n```sh\npip install x\n```\n")
    _write(tmp_path / "guide" / "advanced" / "tuning.md",
           "# Tuning\n\nSee [docs](https://example.com).\n")
    return tmp_path


def test_nested_folders_all_pages_present(nested_docs):
    html = build_site(nested_docs, title="Demo")
    assert html.count('<section class="page"') == 3
    assert "Home" in html and "Install" in html and "Tuning" in html
    assert "<title>Demo</title>" in html


def test_nav_mirrors_folder_hierarchy(nested_docs):
    html = build_site(nested_docs)
    nav = html.split("<nav>")[1].split("</nav>")[0]
    assert "guide" in nav and "advanced" in nav
    # nested <ul> inside the guide entry
    assert nav.index("guide") < nav.index("<ul>", nav.index("guide"))
    # every section is reachable from the nav
    for anchor in ("page-index", "page-guide-install",
                   "page-guide-advanced-tuning"):
        assert f'href="#{anchor}"' in nav
        assert f'id="{anchor}"' in html


def test_single_styled_page_structure(nested_docs):
    html = build_site(nested_docs)
    assert html.startswith("<!DOCTYPE html>")
    assert "<style>" in html and "</html>" in html


def test_page_title_falls_back_to_filename(tmp_path):
    _write(tmp_path / "notes.md", "Just *text*, no heading.\n")
    html = build_site(tmp_path)
    assert "<em>text</em>" in html


def test_empty_dir_raises(tmp_path):
    with pytest.raises(ValueError, match="no Markdown files"):
        build_site(tmp_path)


def test_missing_dir_raises(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        build_site(tmp_path / "nope")


# ------------------------------------------------------------------ CLI ---

def test_cli_end_to_end(nested_docs, tmp_path):
    out = tmp_path / "site.html"
    proc = subprocess.run(
        [sys.executable, "-m", "minisite", str(nested_docs), str(out),
         "--title", "CLI Demo"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    html = out.read_text(encoding="utf-8")
    assert "<title>CLI Demo</title>" in html
    assert html.count('<section class="page"') == 3


def test_cli_missing_input_errors(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "minisite", str(tmp_path / "nope"),
         str(tmp_path / "o.html")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "error" in proc.stderr
