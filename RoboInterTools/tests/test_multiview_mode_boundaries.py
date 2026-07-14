import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

import client as client_module


class _Event:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


class _Button:
    def __init__(self):
        self.click_count = 0

    def click(self):
        self.click_count += 1


class _FrameLabel:
    def width(self):
        return 360

    def height(self):
        return 220

    def setPixmap(self, pixmap):
        self.pixmap = pixmap


class _QImage:
    Format_RGB888 = object()

    def __init__(self, *args):
        pass


class _QPixmap:
    @staticmethod
    def fromImage(image):
        return object()


class _Slider:
    def value(self):
        return 0


class _TextDisplay:
    def __init__(self):
        self.text = None
        self.clear_count = 0

    def setText(self, text):
        self.text = text

    def clear(self):
        self.clear_count += 1


class MultiviewModeBoundaryTests(unittest.TestCase):
    def test_e_shortcut_does_not_enter_sam_navigation_in_language_mode(self):
        sam_next_button = _Button()
        player = SimpleNamespace(
            mode="语言标注",
            sam_next_button=sam_next_button,
        )

        client_module.VideoPlayer.keyPressEvent(
            player, _Event(client_module.Qt.Key_E)
        )

        self.assertEqual(sam_next_button.click_count, 0)

    def test_e_shortcut_keeps_sam_navigation_in_segmentation_mode(self):
        sam_next_button = _Button()
        player = SimpleNamespace(
            mode="分割标注",
            sam_next_button=sam_next_button,
        )

        client_module.VideoPlayer.keyPressEvent(
            player, _Event(client_module.Qt.Key_E)
        )

        self.assertEqual(sam_next_button.click_count, 1)

    def test_multiview_render_does_not_store_boolean_as_last_frame(self):
        player = SimpleNamespace(
            last_frame=np.zeros((4, 4, 3), dtype=np.uint8),
            update_frame_position_label=lambda: None,
            video_views={
                "camera0": np.zeros((1, 8, 8, 3), dtype=np.uint8),
            },
            video_view_labels={"camera0": _FrameLabel()},
        )

        with (
            patch.object(client_module, "QImage", _QImage),
            patch.object(client_module, "QPixmap", _QPixmap),
        ):
            client_module.VideoPlayer.update_multiview_frame(player, 0)

        self.assertIsNone(player.last_frame)

    def test_seek_video_uses_multiview_media_as_loaded_state(self):
        update_calls = []
        player = SimpleNamespace(
            last_frame=None,
            video_views={
                "camera0": np.zeros((1, 8, 8, 3), dtype=np.uint8),
            },
            ori_video={},
            progress_slider=_Slider(),
            update_frame=lambda frame_number: update_calls.append(frame_number),
            cur_frame_idx=0,
            frame_count=1,
            video_position_label=_TextDisplay(),
            mode="语言标注",
            lang_anno={},
            video_lang_input=_TextDisplay(),
            get_clip_description=lambda: ((None, None), ("", "", "")),
            clip_lang_input=_TextDisplay(),
        )

        client_module.VideoPlayer.seek_video(player)

        self.assertEqual(update_calls, [0])
        self.assertEqual(player.video_position_label.text, "帧: 1/1")

    def test_sam_object_navigation_is_ignored_in_language_mode(self):
        player = SimpleNamespace(mode="语言标注")

        client_module.VideoPlayer.next_sam_object(player)
        client_module.VideoPlayer.pre_sam_object(player)


if __name__ == "__main__":
    unittest.main()
