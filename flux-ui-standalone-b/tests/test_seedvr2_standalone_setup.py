from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SeedVR2StandaloneSetupTests(unittest.TestCase):
    def test_launcher_installs_seedvr2_nightly(self):
        launcher_py = (ROOT / "launcher.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("ComfyUI-SeedVR2_VideoUpscaler", launcher_py)
        self.assertIn("https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler", launcher_py)
        self.assertIn('"branch": "nightly"', launcher_py)
        self.assertIn("install_custom_nodes(comfy_dir, python_exe)", launcher_py)

    def test_app_accepts_seedvr2_folder_name_variants(self):
        app_py = (ROOT / "app" / "app.py").read_text(encoding="utf-8", errors="ignore")

        self.assertIn("ComfyUI-SeedVR2_VideoUpscaler", app_py)
        self.assertIn("seedvr2_videoupscaler", app_py)


if __name__ == "__main__":
    unittest.main()
