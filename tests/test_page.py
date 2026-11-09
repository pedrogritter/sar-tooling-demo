"""The page states its limit and escapes metadata. Markdown cannot inject HTML."""

from __future__ import annotations

import unittest
from pathlib import Path

from lisbon_scene.loader import load_scene
from lisbon_scene.markdown import render_markdown
from lisbon_scene.page import render_page

SCENE_ID = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"


class MarkdownTest(unittest.TestCase):
    def test_subset_and_escape(self) -> None:
        source = "\n".join(
            (
                "## Scene note",
                "",
                "A **bridge** and `<script>alert(1)</script>`.",
                "",
                "- no detector",
                "- `qlk-cog.tif`",
            )
        )
        html = render_markdown(source)
        self.assertIn("<h2>Scene note</h2>", html)
        self.assertIn("<strong>bridge</strong>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("<li>no detector</li>", html)
        self.assertIn("<code>qlk-cog.tif</code>", html)
        self.assertNotIn("<script>", html)


class PageTest(unittest.TestCase):
    def test_real_scene_page_names_the_limit(self) -> None:
        scene = load_scene()
        note_path = Path(__file__).resolve().parent.parent / "scene_note.md"
        note = note_path.read_text(encoding="utf-8")
        html = render_page(scene, note, quicklook_width=1600, quicklook_height=1600)
        self.assertIn("25 de Abril", html)
        self.assertIn(SCENE_ID, html)
        self.assertIn("No detector has run", html)
        self.assertIn('src="/quicklook.png"', html)
        self.assertIn("ICEYE-X52", html)
        self.assertIn("qlk-cog.tif", html)
        self.assertNotIn("vessel detected", html.lower())

    def test_title_from_metadata_is_escaped(self) -> None:
        scene = load_scene()
        html = render_page(scene, "See `<b>`")
        self.assertIn("The quicklook file is not on disk", html)
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>", html)


if __name__ == "__main__":
    unittest.main()
