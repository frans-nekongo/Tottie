"""Markdown parsing + single-page site builder. Stdlib only."""
import html
import re
from pathlib import Path

# ---------------------------------------------------------------- inline ---

_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(([^)\s]+)(?:\s+(?:\"[^\"]*\"|&quot;.*?&quot;))?\)"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})\s*(\w*)\s*$")
_UL_RE = re.compile(r"^(\s*)[-*]\s+(.*\S)\s*$")
_OL_RE = re.compile(r"^(\s*)\d+\.\s+(.*\S)\s*$")
_HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def render_inline(text: str) -> str:
    """Bold, italic, links, inline code. Code spans are immune to the rest."""
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE_SPAN_RE.sub(stash, text)
    text = html.escape(text, quote=True)
    # Links first so URLs containing * don't get mangled by emphasis.
    text = _LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text
    )
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    for i, code in enumerate(codes):
        text = text.replace(
            f"\x00{i}\x00", f"<code>{html.escape(code, quote=True)}</code>"
        )
    return text


# ---------------------------------------------------------------- blocks ---

def _close_list(buf: list[str], tag: str | None) -> str | None:
    if tag:
        buf.append(f"</{tag}>")
    return None


def render_markdown(source: str) -> str:
    """Render a Markdown subset to an HTML fragment (no <html> wrapper)."""
    lines = source.split("\n")
    buf: list[str] = []
    para: list[str] = []
    list_tag: str | None = None
    in_fence = False
    fence_char = ""
    fence_lang = ""
    fence_buf: list[str] = []

    def flush_para() -> None:
        if para:
            buf.append(f"<p>{render_inline(' '.join(para))}</p>")
            para.clear()

    def emit_fence() -> None:
        while fence_buf and fence_buf[-1] == "":
            fence_buf.pop()
        code = html.escape("\n".join(fence_buf), quote=True)
        cls = f' class="language-{fence_lang}"' if fence_lang else ""
        buf.append(f"<pre><code{cls}>{code}</code></pre>")
        fence_buf.clear()

    for line in lines:
        fence = _FENCE_RE.match(line)
        if fence:
            if not in_fence:
                flush_para()
                list_tag = _close_list(buf, list_tag)
                in_fence = True
                fence_char = fence.group(1)[0] * 3
                fence_lang = fence.group(2)
            elif line.startswith(fence_char):
                emit_fence()
                in_fence = False
            else:
                fence_buf.append(line)
            continue
        if in_fence:
            fence_buf.append(line)
            continue

        if not line.strip():
            flush_para()
            list_tag = _close_list(buf, list_tag)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_para()
            list_tag = _close_list(buf, list_tag)
            level = len(heading.group(1))
            text = heading.group(2).strip()
            buf.append(
                f'<h{level} id="{slugify(text)}">{render_inline(text)}</h{level}>'
            )
            continue

        if _HR_RE.match(line):
            flush_para()
            list_tag = _close_list(buf, list_tag)
            buf.append("<hr>")
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            flush_para()
            list_tag = _close_list(buf, list_tag)
            buf.append(f"<blockquote>{render_inline(quote.group(1))}</blockquote>")
            continue

        ul = _UL_RE.match(line)
        ol = _OL_RE.match(line)
        if ul or ol:
            flush_para()
            tag = "ul" if ul else "ol"
            content = (ul or ol).group(2)
            if list_tag != tag:
                list_tag = _close_list(buf, list_tag)
                buf.append(f"<{tag}>")
                list_tag = tag
            buf.append(f"<li>{render_inline(content)}</li>")
            continue

        list_tag = _close_list(buf, list_tag)
        para.append(line.strip())

    if in_fence:  # unclosed fence: emit what we have rather than dropping it
        emit_fence()
    flush_para()
    _close_list(buf, list_tag)
    return "\n".join(buf)


# ------------------------------------------------------------------ site ---

CSS = """\
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.6;
margin:0;color:#1a1a1a;background:#fff}
.layout{display:flex;min-height:100vh}
nav{width:260px;flex-shrink:0;background:#f4f4f5;border-right:1px solid #e4e4e7;
padding:1.5rem;position:sticky;top:0;max-height:100vh;overflow:auto}
nav h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#71717a}
nav ul{list-style:none;padding-left:1rem;margin:.25rem 0}
nav>ul{padding-left:0}
nav a{color:#3f3f46;text-decoration:none}
nav a:hover{color:#000;text-decoration:underline}
main{max-width:760px;padding:2rem 3rem}
section.page{margin-bottom:3rem;padding-bottom:2rem;border-bottom:1px solid #e4e4e7}
pre{background:#18181b;color:#f4f4f5;padding:1rem;border-radius:.5rem;overflow:auto}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em}
p code{background:#f4f4f5;padding:.1em .3em;border-radius:.25rem}
blockquote{border-left:3px solid #d4d4d8;margin-left:0;padding-left:1rem;color:#52525b}
a{color:#2563eb}
table{border-collapse:collapse}
"""


def _page_title(md_text: str, fallback: str) -> str:
    for line in md_text.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            return m.group(2).strip()
    return fallback


def collect_pages(src: Path) -> list[dict]:
    """Walk *.md under src (sorted, nested folders included)."""
    pages = []
    for path in sorted(src.rglob("*.md")):
        rel = path.relative_to(src)
        text = path.read_text(encoding="utf-8")
        anchor = "page-" + slugify(str(rel.with_suffix("")))
        pages.append({
            "rel": rel,
            "parts": list(rel.with_suffix("").parts),
            "title": _page_title(text, rel.stem),
            "anchor": anchor,
            "html": render_markdown(text),
        })
    return pages


def _nav_tree(pages: list[dict]) -> dict:
    tree: dict = {}
    for page in pages:
        node = tree
        for part in page["parts"][:-1]:
            node = node.setdefault(part, {})
        node.setdefault("\x00pages", []).append(page)
    return tree


def _render_nav(tree: dict) -> str:
    items: list[str] = []
    for page in tree.get("\x00pages", []):
        items.append(
            f'<li><a href="#{page["anchor"]}">'
            f"{html.escape(page['title'])}</a></li>"
        )
    for name in sorted(k for k in tree if not k.startswith("\x00")):
        items.append(
            f"<li>{html.escape(name)}{_render_nav(tree[name])}</li>"
        )
    return f"<ul>{''.join(items)}</ul>" if items else ""


def build_site(src_dir: str | Path, title: str = "Minisite") -> str:
    src = Path(src_dir)
    if not src.is_dir():
        raise ValueError(f"input is not a directory: {src_dir}")
    pages = collect_pages(src)
    if not pages:
        raise ValueError(f"no Markdown files found under: {src_dir}")
    nav = _render_nav(_nav_tree(pages))
    sections = "\n".join(
        f'<section class="page" id="{p["anchor"]}">\n'
        f"<h1>{html.escape(p['title'])}</h1>\n"
        f"{p['html']}\n</section>"
        for p in pages
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="layout">
<nav><h2>Contents</h2>{nav}</nav>
<main>{sections}</main>
</div>
</body>
</html>
"""
