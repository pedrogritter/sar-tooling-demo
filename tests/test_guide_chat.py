"""Guide chat answers from the guide texts and skips unrelated questions."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scene.belt.run import LIMITS
from scene.guide_chat import GuideChatError, answer_guide_chat, model_or_none
from scene.jobs import MeasurementJobManager
from scene.paths import project_root
from scene.web import dispatch

OFF_TOPIC = "Who won the world cup in 1998?"
REFUSAL = (
    "This chat answers questions about this viewer and about SAR. "
    "It does not answer that."
)
NO_KEY = "Set an OpenAI key in Settings to ask a question."
BRIGHT = "A bright mark is a bright radar return."


class RecordingModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class GuideChatTest(unittest.TestCase):
    def test_an_unrelated_question_does_not_call_the_model(self) -> None:
        model = RecordingModel("unused")
        payload = answer_guide_chat(OFF_TOPIC, None, model)
        self.assertEqual(str(payload["reply"]), REFUSAL)
        self.assertIsNone(payload["section_id"])
        self.assertIsNone(payload["section_title"])
        self.assertFalse(payload["open_section"])
        self.assertEqual(model.prompts, [])

    def test_open_water_keeps_the_limit_and_offers_the_section(self) -> None:
        limit = LIMITS["open-water"]
        model = RecordingModel(f"Dark smooth water. {limit}")
        payload = answer_guide_chat("What is open water?", None, model)
        self.assertEqual(payload["section_id"], "tool-open-water")
        self.assertEqual(payload["section_title"], "Open water")
        self.assertFalse(payload["open_section"])
        reply = str(payload["reply"])
        self.assertIn(limit, reply)
        self.assertIn("Open the Open water section?", reply)
        self.assertEqual(len(model.prompts), 1)
        prompt = model.prompts[0]
        self.assertNotIn("overview.png", prompt)
        glossary = (project_root() / "content" / "sar_glossary.md").read_text(
            encoding="utf-8"
        )
        note = (project_root() / "content" / "scene_note.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Sigma-nought is the brightness", glossary)
        self.assertIn("Sigma-nought is the brightness", prompt)
        self.assertIn("not a vessel identification", note)
        self.assertIn("not a vessel identification", prompt)

    def test_a_ship_reply_is_replaced_and_keeps_the_limit(self) -> None:
        limit = LIMITS["open-water"]
        model = RecordingModel("That bright mark is a ship.")
        payload = answer_guide_chat("What is open water?", None, model)
        reply = str(payload["reply"])
        self.assertNotIn("ship", reply.casefold())
        self.assertIn(limit, reply)
        self.assertIn("Open the Open water section?", reply)

    def test_a_reply_that_drops_the_limit_is_replaced(self) -> None:
        model = RecordingModel("The water looks dark.")
        payload = answer_guide_chat("What is open water?", None, model)
        self.assertIn(LIMITS["open-water"], str(payload["reply"]))

    def test_sar_with_no_section_calls_the_model(self) -> None:
        model = RecordingModel("SAR is synthetic-aperture radar.")
        payload = answer_guide_chat("What is SAR?", None, model)
        self.assertIsNone(payload["section_id"])
        self.assertEqual(str(payload["reply"]), "SAR is synthetic-aperture radar.")
        self.assertEqual(len(model.prompts), 1)

    def test_a_bad_sar_reply_falls_back_to_the_bright_mark_sentence(self) -> None:
        model = RecordingModel("It found a vessel.")
        payload = answer_guide_chat("What is SAR?", None, model)
        self.assertEqual(str(payload["reply"]), BRIGHT)
        self.assertIsNone(payload["section_id"])

    def test_no_key_still_offers_the_section_and_does_not_need_a_model(self) -> None:
        payload = answer_guide_chat("What is speckle?", None, None)
        self.assertEqual(payload["section_id"], "speckle")
        self.assertIn(NO_KEY, str(payload["reply"]))
        self.assertIn("Open the Speckle section?", str(payload["reply"]))

    def test_yes_opens_the_pending_section_without_the_model(self) -> None:
        model = RecordingModel("unused")
        payload = answer_guide_chat("Yes", "tool-open-water", model)
        self.assertTrue(payload["open_section"])
        self.assertEqual(payload["section_id"], "tool-open-water")
        self.assertEqual(str(payload["reply"]), "Opening Open water.")
        self.assertEqual(model.prompts, [])

    def test_yes_without_a_real_section_does_not_call_the_model(self) -> None:
        model = RecordingModel("unused")
        payload = answer_guide_chat("yes", "not-a-section", model)
        self.assertEqual(str(payload["reply"]), REFUSAL)
        self.assertFalse(payload["open_section"])
        self.assertEqual(model.prompts, [])

    def test_blank_and_huge_questions_are_refused(self) -> None:
        with self.assertRaises(GuideChatError) as blank:
            answer_guide_chat("  ", None, None)
        self.assertEqual(str(blank.exception), "Enter a question.")
        with self.assertRaises(GuideChatError) as huge:
            answer_guide_chat("a" * 501, None, None)
        self.assertEqual(str(huge.exception), "Ask in one short question.")
        with self.assertRaises(GuideChatError) as pending:
            answer_guide_chat("What is SAR?", 3, None)
        self.assertEqual(
            str(pending.exception),
            "pending_section_id must be null or a section id.",
        )

    def test_module_imports_no_model_library_at_the_top(self) -> None:
        source = (project_root() / "src" / "scene" / "guide_chat.py").read_text(
            encoding="utf-8"
        )
        for line in source.splitlines():
            if line.startswith(("import ", "from ")):
                self.assertNotIn("langchain", line)
                self.assertNotIn("openai", line)
        self.assertNotIn("overview.png", source)

    def test_a_blank_environment_builds_no_model(self) -> None:
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
            patch("scene.analyze.load_local_env"),
        ):
            self.assertIsNone(model_or_none())


class GuideChatRouteTest(unittest.TestCase):
    def test_post_returns_the_refusal_and_get_is_not_found(self) -> None:
        manager = MeasurementJobManager(output_dir=Path("/tmp"))
        body = json.dumps({"message": OFF_TOPIC}).encode()
        got = dispatch(
            "POST",
            "/api/guide/chat",
            body,
            None,  # type: ignore[arg-type]
            manager,
        )
        self.assertEqual(got.status, 200)
        payload = json.loads(got.body.decode("utf-8"))
        self.assertEqual(payload["reply"], REFUSAL)
        self.assertFalse(payload["open_section"])
        missing = dispatch(
            "GET",
            "/api/guide/chat",
            b"",
            None,  # type: ignore[arg-type]
            manager,
        )
        self.assertEqual(missing.status, 404)