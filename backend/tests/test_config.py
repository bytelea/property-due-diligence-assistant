import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings, get_settings


class SettingsTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_environment_secret_is_excluded_from_output(self):
        with patch.dict(os.environ, {"ANYMIZE_API_KEY": "placeholder"}, clear=True):
            settings = Settings()
        self.assertEqual(settings.anymize_api_key.get_secret_value(), "placeholder")
        self.assertNotIn("placeholder", repr(settings))
        self.assertNotIn("placeholder", settings.model_dump_json())
        self.assertNotIn("placeholder", str(settings.anymize_api_key))

    def test_local_file_and_environment_precedence(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("ANYMIZE_API_KEY=placeholder\nGEMINI_MODEL=local-model\n")
            with patch("app.config.LOCAL_ENV_FILE", env_file):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(get_settings().gemini_model, "local-model")
                    self.assertEqual(get_settings().anymize_api_key.get_secret_value(), "placeholder")
                get_settings.cache_clear()
                with patch.dict(os.environ, {"GEMINI_MODEL": "environment-model"}, clear=True):
                    self.assertEqual(get_settings().gemini_model, "environment-model")
                get_settings.cache_clear()
                with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
                    self.assertEqual(get_settings().gemini_model, "")
                    self.assertEqual(get_settings().anymize_api_key.get_secret_value(), "")

    def test_validation_message_hides_input(self):
        with patch.dict(os.environ, {"PORT": "invalid-placeholder"}, clear=True):
            with self.assertRaises(ValidationError) as error:
                Settings()
        self.assertNotIn("invalid-placeholder", str(error.exception))
