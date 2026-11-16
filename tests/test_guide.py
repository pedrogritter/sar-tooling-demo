"""GET /api/guide quotes the toolkit limits and does not call a model."""

from __future__ import annotations

import json
import unittest

from scene.guide import guide_payload
from scene.jobs import MeasurementJobManager
from scene.paths import project_root
from scene.toolkit.catalog import TOOLS
from scene.toolkit.run import LIMITS
from scene.web import dispatch

READ_GRD = (
    "It reads grd-cog.tif. The calibration factor and the ground size of "
    "an overview pixel come from grd-json.json."
)
READ_MOTION = (
    "It reads grd-cog.tif and vid-cog.tif. vid-cog.tif is the georeferenced "
    "dwell stack. The stage video is vid-mp4, and this tool does not read "
    "that file."
)
READ_PAIR = (
    "It reads grd-cog.tif on the open scene and grd-cog.tif on the partner "
    "scene. The partner is resampled onto the open scene's overview grid."
)
READ_STACK = (
    "It reads grd-cog.tif on the open scene and grd-cog.tif on every matched "
    "scene. A stack compares every matched scene, not only one partner."
)
STACK_MEAN_LOCK = (
    "It stays locked until five matched scenes, including the open one, "
    "are on disk."
)
FILE_SENTENCE = {
    "single": READ_GRD,
    "motion": READ_MOTION,
    "pair": READ_PAIR,
    "stack": READ_STACK,
    "stack-mean": READ_STACK,
}
DESCRIPTIONS = {
    "open-water": (
        "Dark smooth water, from the darkest histogram mode. It reports "
        "the area, the fraction of the scene, and the median sigma-nought."
    ),
    "sea-roughness": (
        "Calm water against wind-roughened water, inside the water mask. "
        "A sea that spans less than 1.5 dB stays one class."
    ),
    "built-up": (
        "Bright clusters on land. It reports the fraction of land and a "
        "cluster count."
    ),
    "returns-on-water": (
        "Compact bright returns that touch the water. The label stays "
        "bright return."
    ),
    "long-structure": "A long bright return along the waterline.",
    "dwell-motion": (
        "Tracks of bright returns during this collect. Cyan held still. "
        "Red moved. It reports displacement and speed over those seconds."
    ),
    "amplitude-change": (
        "Earlier date in red, later date in cyan. The darker, brighter, "
        "and unchanged areas count a difference of at least 3 dB in a "
        "patch of at least 8 pixels."
    ),
    "water-persistence": "How many dates each pixel is water.",
    "sea-state": "The median sigma-nought of the water on each date.",
    "dark-sea-anomaly": (
        "Water at least 2 dB darker than the stack median, in a patch of "
        "at least 8 pixels, whose surrounding ring is at least 1 dB "
        "brighter. It reports extent only."
    ),
    "shoreline-series": "The waterline once per date.",
    "date-of-change": (
        "The date a pixel left the stack median, when the departure is "
        "at least 3 dB and the patch is at least 8 pixels."
    ),
    "repeat-returns": (
        "A bright return seen on many dates against one seen once."
    ),
    "site-activity": (
        "A bright cluster that appears or leaves relative to the stack "
        "median."
    ),
    "stack-mean": "The mean of at least five matched dates.",
}
SHIP_SENTENCES = (
    "The page does not name a ship, match AIS, or claim that a model read "
    "the radar.",
    "The prose may not name a ship, a spill, a tide height, or a building "
    "height.",
)
VESSEL_SENTENCE = (
    "A bright return on the water is not a vessel identification."
)
INTRO_IDS = (
    "what-this-is",
    "search",
    "download",
    "open-a-scene",
    "run-a-tool",
    "run-a-report",
    "sigma-nought",
    "incidence",
    "look-side",
    "speckle",
    "layover",
    "bright-return",
)


def _as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError("expected an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise AssertionError("expected a string key")
        result[key] = item
    return result


def _rows() -> list[dict[str, object]]:
    raw = guide_payload()["sections"]
    if not isinstance(raw, list):
        raise AssertionError("sections is not a list")
    return [_as_dict(item) for item in raw]


def _paragraphs(section: dict[str, object]) -> list[str]:
    raw = section["paragraphs"]
    if not isinstance(raw, list):
        raise AssertionError("paragraphs is not a list")
    paragraphs: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item == "":
            raise AssertionError("paragraph is empty")
        paragraphs.append(item)
    return paragraphs


def _text() -> str:
    chunks: list[str] = []
    for section in _rows():
        chunks.extend(_paragraphs(section))
    return "\n".join(chunks)


class GuidePayloadTest(unittest.TestCase):
    def test_section_order_and_keys(self) -> None:
        payload = guide_payload()
        self.assertEqual(set(payload), {"sections"})
        rows = _rows()
        ids: list[str] = []
        for section in rows:
            self.assertEqual(set(section), {"id", "title", "paragraphs"})
            section_id = section["id"]
            title = section["title"]
            if not isinstance(section_id, str) or section_id == "":
                raise AssertionError("id")
            if not isinstance(title, str) or title == "":
                raise AssertionError("title")
            ids.append(section_id)
            _paragraphs(section)
        expected = (
            INTRO_IDS
            + tuple(f"tool-{spec.id}" for spec in TOOLS)
            + ("retrieval", "kubernetes")
        )
        self.assertEqual(tuple(ids), expected)

    def test_each_tool_keeps_its_limit_description_and_file(self) -> None:
        by_id = {str(section["id"]): section for section in _rows()}
        for spec in TOOLS:
            section = by_id[f"tool-{spec.id}"]
            self.assertEqual(section["title"], spec.label)
            paragraphs = _paragraphs(section)
            self.assertEqual(paragraphs[0], DESCRIPTIONS[spec.id])
            self.assertIn(FILE_SENTENCE[spec.kind], paragraphs)
            self.assertEqual(paragraphs[-1], LIMITS[spec.id])
            if spec.kind == "stack-mean":
                self.assertIn(STACK_MEAN_LOCK, paragraphs)
                self.assertEqual(paragraphs[-2], STACK_MEAN_LOCK)

    def test_science_and_scene_note_are_quotes(self) -> None:
        root = project_root()
        glossary = (root / "content" / "sar_glossary.md").read_text(
            encoding="utf-8"
        )
        note = (root / "content" / "scene_note.md").read_text(encoding="utf-8")
        by_id = {str(section["id"]): section for section in _rows()}
        for section_id in (
            "sigma-nought",
            "incidence",
            "look-side",
            "speckle",
            "layover",
            "bright-return",
        ):
            for paragraph in _paragraphs(by_id[section_id]):
                self.assertIn(paragraph, glossary)
        self.assertIn(VESSEL_SENTENCE, note)
        self.assertIn(VESSEL_SENTENCE, _text())
        what = _paragraphs(by_id["what-this-is"])
        self.assertIn(
            "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF",
            "\n".join(what),
        )
        self.assertIn("25 de Abril bridge", "\n".join(what))
        self.assertIn(
            "A bright mark is a bright radar return.",
            "\n".join(what),
        )

    def test_how_to_and_sketches(self) -> None:
        by_id = {str(section["id"]): section for section in _rows()}
        self.assertIn("scene id", "\n".join(_paragraphs(by_id["search"])))
        self.assertIn("preview pack", "\n".join(_paragraphs(by_id["download"])))
        self.assertIn("Library", "\n".join(_paragraphs(by_id["open-a-scene"])))
        self.assertIn(
            "does not call a model",
            "\n".join(_paragraphs(by_id["run-a-tool"])),
        )
        self.assertIn(
            "does not ask a question",
            "\n".join(_paragraphs(by_id["run-a-report"])),
        )
        self.assertIn("not running", "\n".join(_paragraphs(by_id["retrieval"])))
        self.assertIn(
            "This checkout does not run in Kubernetes.",
            "\n".join(_paragraphs(by_id["kubernetes"])),
        )
        self.assertIn("not running", "\n".join(_paragraphs(by_id["kubernetes"])))

    def test_claim_limits(self) -> None:
        text = _text()
        lowered = text.lower()
        self.assertNotIn("model inspected", lowered)
        self.assertNotIn("inspected a raster", lowered)
        self.assertNotIn("inspected the radar", lowered)
        stripped = text
        for sentence in SHIP_SENTENCES:
            self.assertIn(sentence, stripped)
            stripped = stripped.replace(sentence, "")
        self.assertIn(VESSEL_SENTENCE, stripped)
        stripped = stripped.replace(VESSEL_SENTENCE, "")
        self.assertNotIn("ship", stripped.lower())
        self.assertNotIn("ais", stripped.lower())
        self.assertNotIn("vessel", stripped.lower())

    def test_guide_module_does_not_import_a_model_library(self) -> None:
        source = (project_root() / "src" / "scene" / "guide.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("openai", source)
        self.assertNotIn("langchain", source)


class GuideRouteTest(unittest.TestCase):
    def test_get_returns_the_guide_and_post_is_not_found(self) -> None:
        manager = MeasurementJobManager()
        got = dispatch(
            "GET",
            "/api/guide",
            b"",
            None,  # type: ignore[arg-type]
            manager,
        )
        self.assertEqual(got.status, 200)
        self.assertEqual(got.content_type, "application/json; charset=utf-8")
        payload = json.loads(got.body.decode("utf-8"))
        self.assertEqual(set(payload), {"sections"})
        posted = dispatch(
            "POST",
            "/api/guide",
            b"{}",
            None,  # type: ignore[arg-type]
            manager,
        )
        self.assertEqual(posted.status, 404)