"""Standalone llmfit hardware normalization tests."""

from __future__ import annotations

import unittest

from aistackd.runtime.backends import plan_llama_cpp_acquisition
from aistackd.runtime.hardware import CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION, HardwareProfile, parse_json_first


class RuntimeHardwareTests(unittest.TestCase):
    def test_parse_json_first_ignores_leading_log_lines(self) -> None:
        payload = parse_json_first('warning before json\n{"provider": "cuda", "device": "nvidia"}\n')

        self.assertEqual(payload, {"provider": "cuda", "device": "nvidia"})

    def test_plan_llama_cpp_acquisition_for_rocm_sets_expected_env(self) -> None:
        profile = HardwareProfile(
            schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
            detector="llmfit",
            backend="amd",
            acceleration_api="rocm",
            target="gfx1100",
            cmake_flags=("-DGGML_HIP=ON", "-DGPU_TARGETS=gfx1100"),
            gpu_layers=99,
            hsa_override_gfx_version="11.0.0",
        )

        plan = plan_llama_cpp_acquisition(profile)

        self.assertEqual(plan.flavor, "rocm")
        self.assertEqual(plan.primary_strategy, "prebuilt")
        self.assertEqual(plan.fallback_strategy, "source")
        self.assertEqual(dict(plan.source_environment)["HSA_OVERRIDE_GFX_VERSION"], "11.0.0")
