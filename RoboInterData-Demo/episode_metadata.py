import glob
import os
import pickle

import numpy as np


DEFAULT_METADATA_ROOT = "/home/baai/RoboInter/lerobot_build_with_block_312/human_anno_lang"
METADATA_ROOT_ENV = "ROBOINTER_EPISODE_METADATA_ROOT"


def get_episode_metadata(video_name, metadata_root=None):
    """Load episode-level metadata for a video from a matching .npz file."""
    path = find_episode_metadata_path(video_name, metadata_root)
    if path is None:
        return None
    return load_episode_metadata_npz(path)


def find_episode_metadata_path(video_name, metadata_root=None):
    """Find an episode metadata .npz file for the selected video."""
    root = metadata_root or os.environ.get(METADATA_ROOT_ENV, DEFAULT_METADATA_ROOT)
    if not root or not os.path.isdir(root):
        return None

    base_name = os.path.splitext(os.path.basename(str(video_name or "")))[0]
    exact_candidates = []
    if base_name:
        exact_candidates.append(os.path.join(root, f"{base_name}.npz"))
    if video_name:
        exact_candidates.append(os.path.join(root, f"{video_name}.npz"))

    for candidate in exact_candidates:
        if os.path.isfile(candidate):
            return candidate

    npz_files = sorted(glob.glob(os.path.join(root, "*.npz")))
    if not npz_files:
        return None

    normalized_video = _normalize_name(base_name)
    if normalized_video:
        for path in npz_files:
            normalized_path = _normalize_name(os.path.splitext(os.path.basename(path))[0])
            if normalized_video == normalized_path:
                return path
        for path in npz_files:
            normalized_path = _normalize_name(os.path.splitext(os.path.basename(path))[0])
            if normalized_video in normalized_path or normalized_path in normalized_video:
                return path

    if len(npz_files) == 1:
        return npz_files[0]

    return None


def load_episode_metadata_npz(path):
    """Load a dict payload from the arr_0 entry used by human_anno_lang .npz files."""
    with np.load(path, allow_pickle=True) as data:
        if "arr_0" not in data:
            return None
        payload = data["arr_0"]

    if isinstance(payload, np.ndarray):
        payload = payload.item()

    if isinstance(payload, dict):
        return payload

    if isinstance(payload, (bytes, bytearray, np.bytes_)):
        loaded = pickle.loads(bytes(payload))
        return loaded if isinstance(loaded, dict) else None

    return None


def format_episode_metadata(metadata):
    """Format episode-level metadata as Markdown for a read-only UI panel."""
    if not metadata:
        return "No episode metadata found for this video."

    sections = []
    scene = metadata.get("scene")
    if isinstance(scene, dict):
        scene_text = scene.get("text")
        if scene_text:
            sections.append(f"## Scene Summary\n{scene_text}")

        detail_lines = []
        for key, value in scene.items():
            if key == "text" or _is_empty(value):
                continue
            detail_lines.append(f"- {_label(key)}: {_format_value(value)}")
        if detail_lines:
            sections.append("## Scene Details\n" + "\n".join(detail_lines))

    subtasks = metadata.get("subtasks")
    if isinstance(subtasks, list) and subtasks:
        lines = []
        for index, subtask in enumerate(subtasks, start=1):
            if not isinstance(subtask, dict):
                lines.append(f"{index}. {_format_value(subtask)}")
                continue

            text = subtask.get("text") or "Untitled subtask"
            start = subtask.get("start_frame")
            end = subtask.get("end_frame")
            frame_prefix = ""
            if start is not None and end is not None:
                frame_prefix = f"{start}-{end}: "
            elif start is not None:
                frame_prefix = f"{start}: "

            lines.append(f"{index}. {frame_prefix}{text}")

            actions = subtask.get("actions")
            if isinstance(actions, list) and actions:
                action_text = [
                    action.get("text") if isinstance(action, dict) else _format_value(action)
                    for action in actions
                ]
                action_text = [item for item in action_text if item]
                if action_text:
                    lines.append(f"   - Actions: {'; '.join(action_text)}")

        sections.append("## Subtasks\n" + "\n".join(lines))

    extra_lines = []
    for key, value in metadata.items():
        if key in {"scene", "subtasks"} or _is_empty(value):
            continue
        extra_lines.append(f"- {key}: {_format_value(value)}")
    if extra_lines:
        sections.append("## Raw Extra Fields\n" + "\n".join(extra_lines))

    return "\n\n".join(sections) if sections else "No displayable episode metadata found."


def _normalize_name(value):
    return str(value).lower().replace("-", "_").replace(" ", "_")


def _label(key):
    return str(key).replace("_", " ").title()


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, np.ndarray):
        return value.size == 0
    if isinstance(value, (str, list, tuple, dict)):
        return len(value) == 0
    return False


def _format_value(value):
    if isinstance(value, np.ndarray):
        return _format_value(value.tolist())

    if isinstance(value, dict):
        preferred = _format_object_dict(value)
        if preferred:
            return preferred
        return ", ".join(f"{_label(k)}: {_format_value(v)}" for k, v in value.items() if not _is_empty(v))

    if isinstance(value, (list, tuple)):
        if not value:
            return ""
        return ", ".join(_format_value(item) for item in value if not _is_empty(item))

    return str(value)


def _format_object_dict(value):
    name = value.get("name")
    if not name:
        return ""

    details = []
    for key in ("role", "support_or_region", "states", "affordance"):
        item = value.get(key)
        if not _is_empty(item):
            details.append(f"{_label(key)}: {_format_value(item)}")

    return f"{name} ({'; '.join(details)})" if details else str(name)
