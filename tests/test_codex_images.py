import asyncio
import base64
from io import BytesIO, StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
import contextlib
import sys

from PIL import Image
from easel import codex_images as images
from easel.harnesses.base import HarnessError


def png():
    output = BytesIO()
    Image.new('RGB', (8, 6), '#e6a135').save(output, 'PNG')
    return output.getvalue()


class ImageResultChecks(unittest.TestCase):
    def test_only_completed_image_tool_results_are_accepted(self):
        for item in ({'type': 'agentMessage', 'status': 'completed', 'result': 'fake'},
                     {'type': 'imageGeneration', 'status': 'failed', 'result': ''}):
            with self.assertRaises(HarnessError):
                images.decode_item(item, Path.cwd(), {})

    def test_base64_tool_image_is_decoded(self):
        item = {'type': 'imageGeneration', 'status': 'completed',
                'result': base64.b64encode(png()).decode()}
        self.assertEqual(images.decode_item(item, Path.cwd(), {}), png())

    def test_tool_cannot_read_arbitrary_saved_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'outside.png'
            file.write_bytes(png())
            item = {'type': 'imageGeneration', 'status': 'completed', 'result': '', 'savedPath': str(file)}
            with self.assertRaises(HarnessError):
                images.decode_item(item, Path(directory) / 'project', {'CODEX_HOME': directory + '/codex'})

    def test_image_is_validated_converted_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'test.jpeg'
            result = images.save_image(png(), file, 'jpeg')
            self.assertEqual((result['width'], result['height']), (8, 6))
            with Image.open(file) as decoded:
                self.assertEqual(decoded.format, 'JPEG')
            with self.assertRaises(HarnessError):
                images.save_image(png(), file, 'jpeg')
            with self.assertRaises(HarnessError):
                images.save_image(b'not an image', Path(directory) / 'bad.png', 'png')

    def test_easel_api_credentials_do_not_override_native_login(self):
        env = images.native_environment({'PATH': 'native', 'CODEX_HOME': 'native-home',
            'OPENAI_API_KEY': 'private-key', 'IMG_API_KEY': 'another-key', 'OPENAI_BASE_URL': 'https://example.test'})
        self.assertEqual(env, {'PATH': 'native', 'CODEX_HOME': 'native-home'})

    def test_existing_image_script_routes_to_codex_without_api_credentials(self):
        scripts = Path(__file__).resolve().parents[1] / 'skills/shared/scripts'
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import ai_image
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'from-cli.jpeg'
            generate = AsyncMock(return_value=[{'path': str(target)}])
            with patch.dict(os.environ, {'IMG_PROVIDER': 'codex'}), \
                    patch.object(ai_image, 'load_env_file'), \
                    patch.object(ai_image, 'validate_output_path', return_value=target), \
                    patch.object(ai_image, 'load_and_require', side_effect=AssertionError('API fallback')), \
                    patch.object(images, 'generate_images', generate), contextlib.redirect_stdout(StringIO()):
                ai_image.main(['text2img', '--prompt', 'test', '--output', str(target)])
            self.assertEqual(generate.await_args.kwargs['fmt'], 'jpeg')


class NativeRoundTrip(unittest.IsolatedAsyncioTestCase):
    async def test_missing_image_is_failure_even_when_turn_completes(self):
        class FakeRPC:
            def __init__(self, request, command, notify, respond, **kwargs):
                self.notify = notify
                assert request.sandbox == 'read-only'
                assert kwargs['message_limit'] >= 64 * 1024 * 1024
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send(self, message): pass
            async def call(self, method, params, **kwargs):
                if method == 'account/read': return {'account': {'type': 'chatgpt'}}
                if method == 'thread/start': return {'thread': {'id': 'native-test'}}
                if method == 'turn/start':
                    self.notify('turn/completed', {'threadId': 'native-test', 'turn': {'status': 'completed'}})
                return {}
            async def wait_notification(self, future): return await future
        with patch.object(images, 'RPC', FakeRPC), patch.object(images, 'base_command', return_value=['codex']):
            with self.assertRaisesRegex(HarnessError, '没有返回图片'):
                await images.generate_one('test', Path.cwd(), dict(os.environ))

    async def test_partial_batch_keeps_first_success_and_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = [root / 'outputs/topic/one.png', root / 'outputs/topic/two.png']
            calls = 0
            async def generate(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2: raise HarnessError('limit reached')
                return png(), {'threadId': 'test'}
            with patch.object(images, 'generate_one', generate):
                with self.assertRaisesRegex(HarnessError, 'limit reached'):
                    await images.generate_images('test', targets, root, {})
            self.assertTrue(targets[0].is_file())
            self.assertTrue(targets[0].with_suffix('.png.json').is_file())
            self.assertFalse(targets[1].exists())


if __name__ == '__main__': unittest.main()
