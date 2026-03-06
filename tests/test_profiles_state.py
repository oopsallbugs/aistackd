"""Profile state contract tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.state.profiles import (
    CURRENT_PROFILE_SCHEMA_VERSION,
    Profile,
    ProfileStore,
    ProfileValidationError,
)


class ProfileStateTests(unittest.TestCase):
    def test_profile_store_round_trips_profile_and_active_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProfileStore(Path(tmpdir))
            profile = Profile(
                name="local",
                base_url="http://127.0.0.1:8000/",
                api_key_env="AISTACKD_API_KEY",
                role_hint="host",
                description="Local control plane",
            )

            created = store.save_profile(profile)
            active_profile = store.activate_profile("local")
            reloaded = store.load_profile("local")

            self.assertTrue(created)
            self.assertEqual(active_profile.name, "local")
            self.assertEqual(store.get_active_profile_name(), "local")
            self.assertEqual(reloaded.schema_version, CURRENT_PROFILE_SCHEMA_VERSION)
            self.assertEqual(reloaded.base_url, "http://127.0.0.1:8000")
            self.assertEqual(reloaded.role_hint, "host")
            self.assertEqual(reloaded.description, "Local control plane")

    def test_profile_store_rejects_invalid_profile_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProfileStore(Path(tmpdir))

            with self.assertRaises(ProfileValidationError):
                store.save_profile(
                    Profile(
                        name="Local Host",
                        base_url="http://127.0.0.1:8000",
                        api_key_env="AISTACKD_API_KEY",
                    )
                )

    def test_profile_validation_checks_runtime_api_key_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProfileStore(Path(tmpdir))
            store.save_profile(
                Profile(
                    name="lab-host",
                    base_url="http://10.0.0.25:8000",
                    api_key_env="AISTACKD_LAB_HOST_API_KEY",
                    role_hint="remote_host",
                )
            )

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("AISTACKD_LAB_HOST_API_KEY", None)
                result = store.validate_profile("lab-host")

            self.assertFalse(result.ok)
            self.assertEqual(result.definition_errors, ())
            self.assertEqual(
                result.readiness_errors,
                ("api key environment variable 'AISTACKD_LAB_HOST_API_KEY' is not set or empty",),
            )
