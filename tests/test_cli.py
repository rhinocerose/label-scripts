import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from labelkit.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CliTests(unittest.TestCase):
    def test_inspect(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["inspect", str(FIXTURES / "caps_sample.csv")])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("C100042", output)
        self.assertIn("capacitor", output)
        self.assertIn("unverified", output)

    def test_templates(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["templates"])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("resistor", output)
        self.assertIn("capacitor", output)
        self.assertIn("LCSC Number", output)

    def test_offline_run_and_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "run",
                        str(FIXTURES / "caps_sample.csv"),
                        "--out",
                        tmp,
                        "--offline",
                        "--trust-description",
                        "--allow-unverified",
                        "--no-review",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertTrue((Path(tmp) / "capacitor.csv").exists())
            self.assertTrue((Path(tmp) / "parts.csv").exists())
            self.assertTrue((Path(tmp) / "review.csv").exists())

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["print", "--in", tmp, "--backend", "csv"])
            self.assertEqual(code, 0)
            self.assertIn("capacitor.csv", buffer.getvalue())

    def test_mpn_only_offline_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "run",
                        str(FIXTURES / "caps_sample.csv"),
                        "--out",
                        tmp,
                        "--offline",
                        "--allow-unverified",
                        "--no-review",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertFalse((Path(tmp) / "capacitor.csv").exists())

    def test_inspect_can_show_description_attributes(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(
                [
                    "inspect",
                    "--trust-description",
                    str(FIXTURES / "caps_sample.csv"),
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("10nF", buffer.getvalue())

    def test_pn_flag(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["inspect", "-p", "RC0603FR-0710KL"])
        self.assertEqual(code, 0)
        self.assertIn("RC0603FR-0710KL", buffer.getvalue())
        self.assertIn("resistor", buffer.getvalue())

    def test_export_lbx(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = main(["export-lbx", "--out", tmp])
            self.assertEqual(code, 0)
            files = sorted(Path(tmp).glob("*.lbx"))
            self.assertEqual(len(files), 8)
            self.assertIn("resistor.lbx", {path.name for path in files})

    def test_missing_input_is_an_error(self):
        with redirect_stdout(io.StringIO()):
            code = main(["inspect", "/definitely/not/here.csv"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
