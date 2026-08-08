"""The Turso shim is copied, not shared. Prove this copy has not drifted.

WHY A COPY AT ALL. Both this repo and CEO-Agent ship a REGULAR scripts/lib
package (each has __init__.py). Python binds a regular package to exactly one
directory, so putting CEO-Agent's scripts/ on this repo's sys.path would make
`lib` resolve entirely to CEO-Agent's copy -- and lib.claude_cli differs between
the two repos (4.3KB here, 9.6KB there). Six live daemons import it. A path
insert would silently swap the module every automation uses to call a model.

So each repo carries its own copy, and this test is what keeps them honest:
CEO-Agent asserts the same hashes against the same manifest. Edit either copy
alone and that repo's test fails.

To change the shim: edit it in CEO-Agent, copy across, regenerate
docs/turso_shim_sha256.txt in both, land both PRs together.
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "docs" / "turso_shim_sha256.txt"


def _manifest() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, rel = line.partition("  ")
        if digest and rel:
            out[rel.strip()] = digest.strip()
    return out


class TestTursoShimParity(unittest.TestCase):
    def test_the_manifest_exists_and_is_not_empty(self):
        self.assertTrue(MANIFEST.exists(), f"missing {MANIFEST}")
        self.assertTrue(_manifest(), "manifest lists no files")

    def test_every_listed_file_is_present(self):
        for rel in _manifest():
            with self.subTest(file=rel):
                self.assertTrue((REPO / rel).exists(),
                                f"{rel} is in the manifest but not on disk")

    def test_no_shim_file_has_drifted(self):
        for rel, expected in _manifest().items():
            with self.subTest(file=rel):
                p = REPO / rel
                if not p.exists():
                    self.skipTest(f"{rel} missing -- covered by another test")
                actual = hashlib.sha256(p.read_bytes()).hexdigest()
                self.assertEqual(
                    actual, expected,
                    f"\n{rel} no longer matches CEO-Agent's copy."
                    f"\n  expected {expected}"
                    f"\n  actual   {actual}"
                    f"\nEditing one repo's copy alone breaks the other. Sync both,"
                    f"\nregenerate docs/turso_shim_sha256.txt in both, land together.")

    def test_the_shim_actually_imports(self):
        """A matching hash on a file that cannot import is still broken."""
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import lib.tls_trust  # noqa: F401
            import lib.structured_log  # noqa: F401
            import lib.secret_loader  # noqa: F401
        except ImportError as exc:
            self.fail(f"shim prerequisite failed to import: {exc}")
        finally:
            sys.path.remove(str(REPO / "scripts"))

    def test_sitecustomize_is_inert_unless_the_backend_is_turso(self):
        """It must never change behaviour just by being present on disk.

        This file lands in site-packages and runs at every interpreter start,
        including recovery tooling. If it acted without EMPIRE_DATA_BACKEND
        being set to turso_cloud, merely deploying it would flip the backend.
        """
        src = (REPO / "scripts" / "_bootstrap" / "sitecustomize.py").read_text(
            encoding="utf-8")
        self.assertIn('EMPIRE_DATA_BACKEND', src)
        self.assertIn('turso_cloud', src)
        # The install must be guarded, not unconditional.
        self.assertRegex(
            src,
            r'if\s+os\.environ\.get\(\s*[\'"]EMPIRE_DATA_BACKEND[\'"]\s*\)\s*==\s*'
            r'[\'"]turso_cloud[\'"]',
            "sitecustomize must only patch when EMPIRE_DATA_BACKEND==turso_cloud")


if __name__ == "__main__":
    unittest.main()
