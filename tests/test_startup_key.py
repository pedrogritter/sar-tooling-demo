"""Startup key status. No test here starts the server or calls a model."""

from __future__ import annotations

import os
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scene.report.chains import ModelKeyError, startup_key_status
from scene.serve import announce_model_key, main


class StartupKeyStatusTests(unittest.TestCase):
    """A missing or blank key boots. A bad non-blank key is named, not echoed."""

    @contextmanager
    def _environment(self, env_text: str | None, **environ: str) -> Iterator[None]:
        """A project root holding ``env_text`` as .env, and exactly ``environ``."""

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            if env_text is not None:
                (root / ".env").write_text(env_text, encoding="utf-8")
            with (
                patch("scene.analyze.project_root", return_value=root),
                patch.dict(os.environ, environ, clear=True),
            ):
                yield

    def test_absent_and_blank_are_unset(self) -> None:
        cases: tuple[tuple[str | None, dict[str, str]], ...] = (
            (None, {}),
            ("OPENAI_API_KEY=\n", {}),
            (None, {"OPENAI_API_KEY": "   "}),
            ("OPENAI_API_KEY=from-dotenv\n", {"OPENAI_API_KEY": ""}),
        )
        for env_text, environ in cases:
            with self.subTest(env_text=env_text, environ=environ):
                with self._environment(env_text, **environ):
                    self.assertEqual(startup_key_status(), "unset")

    def test_environment_wins_over_dotenv(self) -> None:
        with self._environment(
            "OPENAI_API_KEY=from-dotenv\n", OPENAI_API_KEY="from-environment"
        ):
            self.assertEqual(startup_key_status(), "environment")

    def test_dotenv_is_file_when_the_environment_has_no_key(self) -> None:
        with self._environment("OPENAI_API_KEY=from-dotenv\n"):
            self.assertEqual(startup_key_status(), "file")

    def test_a_space_or_an_overlong_key_raises_without_the_value(self) -> None:
        secret = "sk secret"
        overlong = "k" * 513
        cases: tuple[tuple[str | None, dict[str, str], str], ...] = (
            (None, {"OPENAI_API_KEY": secret}, "the environment"),
            ("OPENAI_API_KEY=sk secret\n", {}, ".env"),
            (None, {"OPENAI_API_KEY": overlong}, "the environment"),
            (f"OPENAI_API_KEY={overlong}\n", {}, ".env"),
        )
        for env_text, environ, origin in cases:
            with self.subTest(origin=origin):
                with self._environment(env_text, **environ):
                    with self.assertRaises(ModelKeyError) as raised:
                        startup_key_status()
                message = str(raised.exception)
                self.assertIn(origin, message)
                self.assertNotIn(secret, message)
                self.assertNotIn(overlong, message)

    def test_five_hundred_twelve_characters_are_kept(self) -> None:
        with self._environment(None, OPENAI_API_KEY="k" * 512):
            self.assertEqual(startup_key_status(), "environment")

    def test_status_does_not_build_a_model(self) -> None:
        with (
            self._environment(None, OPENAI_API_KEY="from-environment"),
            patch("scene.report.chains.ChatOpenAI") as chat,
        ):
            self.assertEqual(startup_key_status(), "environment")
        chat.assert_not_called()


class AnnounceModelKeyTests(unittest.TestCase):
    """The log names the source. It does not name the key or build a model."""

    @contextmanager
    def _environment(self, env_text: str | None, **environ: str) -> Iterator[None]:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            if env_text is not None:
                (root / ".env").write_text(env_text, encoding="utf-8")
            with (
                patch("scene.analyze.project_root", return_value=root),
                patch.dict(os.environ, environ, clear=True),
            ):
                yield

    def test_logs_unset_environment_and_file_without_the_secret(self) -> None:
        secret = "sk-from-environment"
        cases: tuple[tuple[str | None, dict[str, str], str], ...] = (
            (None, {}, "OPENAI_API_KEY is unset"),
            (
                None,
                {"OPENAI_API_KEY": secret},
                "OPENAI_API_KEY arrived from the environment",
            ),
            ("OPENAI_API_KEY=from-dotenv\n", {}, "OPENAI_API_KEY arrived from .env"),
        )
        for env_text, environ, sentence in cases:
            with self.subTest(sentence=sentence):
                with self._environment(env_text, **environ):
                    with self.assertLogs(level="INFO") as logs:
                        announce_model_key()
                text = "\n".join(logs.output)
                self.assertIn(sentence, text)
                self.assertNotIn(secret, text)
                self.assertNotIn("from-dotenv", text)

    def test_announce_does_not_build_a_model(self) -> None:
        with (
            self._environment(None, OPENAI_API_KEY="from-environment"),
            patch("scene.report.chains.ChatOpenAI") as chat,
            self.assertLogs(level="INFO"),
        ):
            announce_model_key()
        chat.assert_not_called()

    def test_a_bad_key_exits_before_seed_and_listen(self) -> None:
        with (
            patch(
                "scene.serve.announce_model_key",
                side_effect=ModelKeyError(
                    "OPENAI_API_KEY from the environment must not contain spaces"
                ),
            ),
            patch("scene.serve.seed_if_needed") as seed,
            patch("scene.serve.serve") as serve,
        ):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 1)
        seed.assert_not_called()
        serve.assert_not_called()

    def test_the_image_build_does_not_receive_the_key(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("OPENAI_API_KEY", text)
