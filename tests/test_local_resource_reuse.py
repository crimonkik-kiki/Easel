"""Regression checks for resource reuse and incomplete model caches."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/shared/scripts/install_tool.py'
spec = importlib.util.spec_from_file_location('reuse_install_tool', SCRIPT)
tool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tool
spec.loader.exec_module(tool)


class ReuseChecks(unittest.TestCase):
    def test_incomplete_model_does_not_count_as_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'config.json').write_text('{}')
            with patch.dict(os.environ, {'EASEL_WHISPER_MODEL': directory}):
                self.assertFalse(tool._pyfn_check_model()[0])

    def test_base_cache_is_identified_without_claiming_large_v3(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('config.json', 'model.bin', 'tokenizer.json'):
                (Path(directory) / name).write_text('test fixture')
            with patch.dict(os.environ, {'EASEL_WHISPER_MODEL': directory,
                                        'EASEL_WHISPER_MODEL_LABEL': 'base'}):
                result = tool.check_all(sys.executable, only=['model'])[0]
            self.assertEqual(result['state'], 'ok')
            self.assertNotIn('large-v3', result['name'])
            self.assertIn('base', result['version'])

    def test_missing_browser_override_is_not_reported_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'EASEL_BROWSER_EXECUTABLE': directory + '/absent.exe'}):
                shell = next(item for item in tool.TOOLS if item.id == 'shell')
                self.assertEqual(tool.check_tool(shell, sys.executable, directory)['state'], 'missing')

    def test_configured_chromium_cache_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'chromium-9999/chrome-win64/chrome.exe'
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH': directory}):
                self.assertEqual(tool._pyfn_check_cft(), (True, 'chromium-9999'))


if __name__ == '__main__':
    unittest.main()
