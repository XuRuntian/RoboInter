import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class ConfigPathTests(unittest.TestCase):
    def test_resolve_existing_path_prefers_environment_value(self):
        from config import resolve_existing_path

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, "env")
            local_path = os.path.join(tmpdir, "local")
            fallback_path = os.path.join(tmpdir, "fallback")
            os.mkdir(env_path)
            os.mkdir(local_path)
            os.mkdir(fallback_path)

            previous = os.environ.get("ROBOINTER_TEST_PATH")
            os.environ["ROBOINTER_TEST_PATH"] = env_path
            try:
                resolved = resolve_existing_path("ROBOINTER_TEST_PATH", local_path, fallback_path)
            finally:
                if previous is None:
                    os.environ.pop("ROBOINTER_TEST_PATH", None)
                else:
                    os.environ["ROBOINTER_TEST_PATH"] = previous

        self.assertEqual(resolved, env_path)

    def test_resolve_existing_path_uses_fallback_when_local_missing(self):
        from config import resolve_existing_path

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, "missing")
            fallback_path = os.path.join(tmpdir, "fallback")
            os.mkdir(fallback_path)

            resolved = resolve_existing_path("ROBOINTER_TEST_PATH", local_path, fallback_path)

        self.assertEqual(resolved, fallback_path)


if __name__ == "__main__":
    unittest.main()
