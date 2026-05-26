from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SeedVR2StandaloneSetupTests(unittest.TestCase):
    def test_batch_setup_installs_seedvr2_nightly(self):
        setup_bat = (ROOT / "セットアップ.bat").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("ComfyUI-SeedVR2_VideoUpscaler", setup_bat)
        self.assertIn("https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler", setup_bat)
        self.assertIn("nightly", setup_bat)

    def test_app_accepts_seedvr2_folder_name_variants(self):
        app_py = (ROOT / "app.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("ComfyUI-SeedVR2_VideoUpscaler", app_py)
        self.assertIn("seedvr2_videoupscaler", app_py)


if __name__ == "__main__":
    unittest.main()
