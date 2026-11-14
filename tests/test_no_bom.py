# ===================== 禁止 Python 文件带 BOM =====================
import unittest
from pathlib import Path


class TestNoBom(unittest.TestCase):
    def test_python_files_have_no_bom(self):
        root = Path(__file__).resolve().parents[1]
        bad = []
        for d in ("bot", "scripts", "tests", "checks"):
            for p in (root / d).rglob("*.py"):
                if p.read_bytes().startswith(b"\xef\xbb\xbf"):
                    bad.append(str(p.relative_to(root)))
        self.assertEqual(bad, [], "这些 Python 文件带 UTF-8 BOM: " + ", ".join(bad))


if __name__ == "__main__":
    unittest.main()
