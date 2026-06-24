import os
import pickle
import sys
import tempfile
import unittest

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class EpisodeMetadataTests(unittest.TestCase):
    def write_metadata(self, root, filename, payload):
        path = os.path.join(root, filename)
        np.savez(path, arr_0=np.array(pickle.dumps(payload), dtype=object))
        return path

    def test_loads_scene_and_subtasks_from_npz(self):
        from episode_metadata import get_episode_metadata

        payload = {
            "scene": {
                "text": "Robot stacks colored blocks on the table.",
                "task_type": "stacking",
                "place": "table",
                "objects": ["red block", "blue block"],
                "state": "blocks separated",
                "affordance": "top face",
            },
            "subtasks": [
                {
                    "text": "pick up the red block",
                    "start_frame": 10,
                    "end_frame": 42,
                }
            ],
            "extra_note": "operator checked",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_metadata(tmpdir, "chunk-000_episode_000002.npz", payload)

            metadata = get_episode_metadata("chunk-000_episode_000002", tmpdir)

        self.assertEqual(metadata["scene"]["text"], payload["scene"]["text"])
        self.assertEqual(metadata["scene"]["objects"], ["red block", "blue block"])
        self.assertEqual(metadata["subtasks"][0]["start_frame"], 10)
        self.assertEqual(metadata["extra_note"], "operator checked")

    def test_formats_missing_metadata_as_clear_empty_state(self):
        from episode_metadata import format_episode_metadata

        formatted = format_episode_metadata(None)

        self.assertIn("No episode metadata found", formatted)

    def test_formats_scene_subtasks_and_extra_fields(self):
        from episode_metadata import format_episode_metadata

        formatted = format_episode_metadata(
            {
                "scene": {
                    "text": "Robot arranges blocks.",
                    "task_type": "arrangement",
                    "objects": ["block A", "block B"],
                },
                "subtasks": [
                    {"text": "move block A", "start_frame": 0, "end_frame": 12},
                    {"text": "move block B", "start_frame": 13, "end_frame": 30},
                ],
                "source": "human_anno_lang",
            }
        )

        self.assertIn("## Scene Summary", formatted)
        self.assertIn("Robot arranges blocks.", formatted)
        self.assertIn("Task Type: arrangement", formatted)
        self.assertIn("Objects: block A, block B", formatted)
        self.assertIn("0-12: move block A", formatted)
        self.assertIn("source: human_anno_lang", formatted)

    def test_formats_numpy_array_extra_fields(self):
        from episode_metadata import format_episode_metadata

        formatted = format_episode_metadata({"scores": np.array([1, 2, 3])})

        self.assertIn("scores: 1, 2, 3", formatted)


if __name__ == "__main__":
    unittest.main()
