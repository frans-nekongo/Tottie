"""minisite: stdlib-only Markdown folder -> single-page HTML site."""
from .builder import build_site, collect_pages, render_inline, render_markdown

__version__ = "1.0.0"
__all__ = ["build_site", "collect_pages", "render_inline", "render_markdown"]
