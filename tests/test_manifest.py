"""The manifest has to agree with the package it sits in, or Home Assistant will not load it."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "adaptive_heating"


class ManifestTests(unittest.TestCase):
    def test_the_domain_matches_the_package_folder(self) -> None:
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], PACKAGE.name)

    def test_the_manifest_carries_what_home_assistant_requires(self) -> None:
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        for key in ("domain", "name", "version", "documentation", "codeowners", "iot_class"):
            self.assertIn(key, manifest)

    def test_the_published_version_matches_the_manifest(self) -> None:
        """Every thermostat publishes this string and the add-on reads it as the integration's version."""
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        source = (PACKAGE / "const.py").read_text(encoding="utf-8")
        declared = re.search(r'INTEGRATION_VERSION: Final = "([^"]+)"', source)
        assert declared is not None
        self.assertEqual(declared.group(1), manifest["version"])


if __name__ == "__main__":
    unittest.main()
