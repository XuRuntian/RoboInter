# ==================== Configuration ====================
import glob
import json
import os
import pickle
from pathlib import Path

import numpy as np

try:
    import lmdb
except ImportError:
    lmdb = None

# LMDB database path
LMDB_PATH = os.environ.get("ROBOINTER_DEMO_LMDB", "demo_data")

# Video file root directory - modify this to your video storage path
# Video files should be named as: {video_name}.mp4
# Example: 11947_exterior_image_1_left.mp4
VIDEO_ROOT = os.environ.get("ROBOINTER_DEMO_VIDEO_ROOT", "videos")

# Optional RoboInterTools config. When demo_data is absent, this lets the
# visualizer review the current annotation client output directly.
TOOLS_CONFIG_PATH = os.environ.get(
    "ROBOINTER_TOOLS_CONFIG",
    str(Path(__file__).resolve().parents[1] / "RoboInterTools" / "config" / "config.yaml"),
)

VIDEO_PATHS = {}
VIDEO_VIEWS = {}

# Coordinate scaling function
def scale_coordinates(annotations, scale_x=4.0, scale_y=4.0):
    """
    Scale coordinates in annotation data
    From (180, 320) to (720, 1280), scaling factor is 4
    Only apply scaling to videos where video_name does not contain 'rh20t'
    """
    scaled_annotations = {}

    for video_name, video_data in annotations.items():
        # Check if video_name contains 'rh20t' (case-insensitive)
        if 'rh20t' in video_name.lower():
            # If it contains rh20t, do not scale, use original data directly
            scaled_annotations[video_name] = video_data
            continue

        scaled_video_data = {}

        for frame_idx, frame_data in video_data.items():
            scaled_frame_data = frame_data.copy()

            # Scale box-type coordinates (format: [[x1, y1], [x2, y2]])
            for box_key in ['object_box', 'placement_proposal', 'gripper_box', 'affordance_box']:
                if box_key in scaled_frame_data and scaled_frame_data[box_key] is not None:
                    box = scaled_frame_data[box_key]
                    if isinstance(box, list) and len(box) == 2:
                        scaled_frame_data[box_key] = [
                            [box[0][0] * scale_x, box[0][1] * scale_y],
                            [box[1][0] * scale_x, box[1][1] * scale_y]
                        ]

            # Scale trace coordinates (format: [[x1, y1], [x2, y2], ...])
            if 'trace' in scaled_frame_data and scaled_frame_data['trace'] is not None:
                trace = scaled_frame_data['trace']
                if isinstance(trace, list):
                    scaled_frame_data['trace'] = [
                        [point[0] * scale_x, point[1] * scale_y] for point in trace
                    ]

            # Scale contact_points coordinates (format: [[x1, y1], [x2, y2], ...])
            if 'contact_points' in scaled_frame_data and scaled_frame_data['contact_points'] is not None:
                points = scaled_frame_data['contact_points']
                if isinstance(points, list):
                    scaled_frame_data['contact_points'] = [
                        [point[0] * scale_x, point[1] * scale_y] for point in points
                    ]

            # Scale grasp_pose coordinates (format: [[x1, y1], [x2, y2], ...])
            if 'grasp_pose' in scaled_frame_data and scaled_frame_data['grasp_pose'] is not None:
                gp = scaled_frame_data['grasp_pose']
                if isinstance(gp, list):
                    scaled_frame_data['grasp_pose'] = [
                        [point[0] * scale_x, point[1] * scale_y] for point in gp
                    ]

            scaled_video_data[frame_idx] = scaled_frame_data

        scaled_annotations[video_name] = scaled_video_data

    return scaled_annotations


# Load annotation data from LMDB
def load_annotations_from_lmdb(lmdb_path):
    """
    Load all annotation data from LMDB database
    Return format:
    {
        "video_name": {
            frame_idx: {
                "time_clip": list or None,
                "instruction_add": str or None,
                "substask": str or None,
                "primitive_skill": str or None,
                "segmentation": np.ndarray or None,
                "object_box": list or None,
                "placement_proposal": list or None,
                "trace": list or None,
                "gripper_box": list or None,
                "contact_frame": int or None,
                "state_affordance": list or None,
                "affordance_box": list or None,
                "contact_points": list or None,
            },
            ...
        },
        ...
    }
    """
    if not os.path.exists(lmdb_path):
        return {}
    if lmdb is None:
        print("Warning: lmdb is not installed; skipping LMDB annotations.")
        return {}

    annotations = {}
    env = lmdb.open(lmdb_path, readonly=True)

    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            video_name = key.decode('utf-8') if isinstance(key, bytes) else str(key)
            try:
                video_data = pickle.loads(value)
                annotations[video_name] = video_data
            except Exception as e:
                print(f"Error loading data for {video_name}: {e}")

    env.close()
    # print(f"Loaded {len(annotations)} videos from LMDB")

    # Apply coordinate scaling (from 180x320 to 720x1280)
    annotations = scale_coordinates(annotations, scale_x=4.0, scale_y=4.0)
    # print(f"Applied 4x coordinate scaling to all annotations")

    return annotations

def parse_server_config(config_path):
    """Read RoboInterTools server config with a small YAML fallback."""
    if not config_path or not os.path.exists(config_path):
        return {}

    try:
        import yaml

        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
        return config.get("server", {}) or {}
    except ImportError:
        pass

    server_config = {}
    in_server = False
    with open(config_path, "r") as f:
        for raw_line in f:
            line = raw_line.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("server:"):
                in_server = True
                continue
            if in_server and line and not line.startswith(" "):
                break
            if not in_server or ":" not in line:
                continue
            key, value = line.strip().split(":", 1)
            server_config[key.strip()] = value.strip().strip("'\"")
    return server_config


def resolve_path(root_dir, path_value):
    if not path_value:
        return ""
    path = Path(str(path_value))
    if path.is_absolute():
        return str(path)
    return str((Path(root_dir) / path).resolve())


def load_json(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def annotation_from_npz(path):
    with np.load(path, allow_pickle=True) as data:
        key = "anno_file" if "anno_file" in data.files else data.files[0]
        value = data[key]

    if hasattr(value, "shape") and value.shape == ():
        value = value.item()
    if isinstance(value, np.ndarray) and value.dtype.kind in {"S", "O"} and value.size == 1:
        value = value.item()
    if isinstance(value, (bytes, bytearray)):
        return pickle.loads(value)
    if isinstance(value, dict):
        return value
    if hasattr(value, "item"):
        item = value.item()
        if isinstance(item, (bytes, bytearray)):
            return pickle.loads(item)
        return item
    return value


def collect_pool_entries(server_config, root_dir):
    entries = {}
    for key in ("has_annotation_lang", "no_annotation_lang"):
        pool = load_json(resolve_path(root_dir, server_config.get(key, "")))
        for _, tasks in (pool or {}).items():
            if not isinstance(tasks, dict):
                continue
            for task_id, info in tasks.items():
                if isinstance(info, dict):
                    item = dict(info)
                else:
                    item = {"anno_path": info}
                item.setdefault("task_id", task_id)
                save_path = resolve_path(root_dir, item.get("save_path", ""))
                if save_path:
                    item["save_path"] = save_path
                    entries[save_path] = item
                entries.setdefault(task_id, item)
    return entries


def collect_lang_save_paths(server_config, root_dir, pool_entries):
    save_paths = {
        key for key in pool_entries
        if isinstance(key, str) and key.endswith(".npz") and os.path.exists(key)
    }

    save_template = server_config.get("save_path_lang_temp", "")
    if save_template:
        pattern = resolve_path(root_dir, save_template).replace("{video_name}", "*")
        save_paths.update(glob.glob(pattern))

    return sorted(path for path in save_paths if os.path.exists(path))


def clip_skill_text(subtask):
    actions = subtask.get("actions") or []
    skills = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        skill = action.get("skill") or action.get("text")
        if skill:
            skills.append(str(skill))
    if skills:
        return " + ".join(skills)
    return str(subtask.get("primitive_skill") or subtask.get("skill") or "")


def convert_language_annotation(annotation):
    """Convert RoboInterTools language annotation to frame-level demo format."""
    episode = annotation.get("episode") or {}
    subtasks = annotation.get("subtasks") or []
    video_text = annotation.get("video_text") or annotation.get("instruction_add") or ""

    frame_count = episode.get("frames")
    if not isinstance(frame_count, int) or frame_count <= 0:
        ends = [int(st.get("end_frame", 0)) for st in subtasks if isinstance(st, dict)]
        frame_count = max(ends) + 1 if ends else 0

    time_clip = []
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        start = int(subtask.get("start_frame", 0))
        end = int(subtask.get("end_frame", start))
        time_clip.append([start, end])

    frames = {}
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        start = max(0, int(subtask.get("start_frame", 0)))
        end = int(subtask.get("end_frame", start))
        if frame_count > 0:
            end = min(end, frame_count - 1)
        frame_data = {
            "time_clip": time_clip,
            "instruction_add": video_text,
            "substask": subtask.get("text") or "",
            "primitive_skill": clip_skill_text(subtask),
            "segmentation": None,
            "object_box": None,
            "placement_proposal": None,
            "trace": None,
            "gripper_box": None,
            "contact_frame": None,
            "state_affordance": None,
            "affordance_box": None,
            "contact_points": None,
            "grasp_pose": None,
            "scene": annotation.get("scene") or {},
        }
        for frame_idx in range(start, end + 1):
            frames[frame_idx] = dict(frame_data)

    if frame_count > 0 and not frames:
        frames[0] = {
            "time_clip": time_clip,
            "instruction_add": video_text,
            "substask": "",
            "primitive_skill": "",
        }
    return frames


def load_robointertools_annotations(config_path):
    server_config = parse_server_config(config_path)
    if not server_config:
        return {}, {}, {}

    root_dir = server_config.get("root_dir") or str(Path(config_path).resolve().parents[1])
    pool_entries = collect_pool_entries(server_config, root_dir)
    save_paths = collect_lang_save_paths(server_config, root_dir, pool_entries)

    annotations = {}
    video_paths = {}
    video_views = {}

    for save_path in save_paths:
        try:
            annotation = annotation_from_npz(save_path)
        except Exception as exc:
            print(f"Warning: failed to load {save_path}: {exc}")
            continue
        if not isinstance(annotation, dict):
            continue

        episode = annotation.get("episode") or {}
        pool_info = pool_entries.get(save_path, {})
        video_name = (
            episode.get("episode_id")
            or Path(save_path).stem
            or pool_info.get("task_id")
        )
        video_name = str(video_name)

        annotations[video_name] = convert_language_annotation(annotation)

        views = episode.get("views") if isinstance(episode.get("views"), dict) else None
        if not views and isinstance(pool_info.get("views"), dict):
            views = pool_info.get("views")
        if views:
            video_views[video_name] = {str(name): str(path) for name, path in views.items()}

        primary_path = (
            episode.get("primary_video_path")
            or episode.get("video_path")
            or pool_info.get("video_path")
            or pool_info.get("task_id")
        )
        if primary_path:
            video_paths[video_name] = str(primary_path)

    seen_task_ids = set()
    for pool_info in pool_entries.values():
        task_id = str(pool_info.get("task_id") or "")
        if not task_id or task_id in seen_task_ids:
            continue
        seen_task_ids.add(task_id)

        video_name = task_id if not os.path.exists(task_id) else Path(task_id).stem
        if video_name in video_paths:
            continue

        views = pool_info.get("views") if isinstance(pool_info.get("views"), dict) else {}
        primary_path = pool_info.get("video_path") or (views and next(iter(views.values())))
        if primary_path:
            video_paths[video_name] = str(primary_path)
        if views and video_name not in video_views:
            video_views[video_name] = {str(name): str(path) for name, path in views.items()}
        annotations.setdefault(video_name, {})

    return annotations, video_paths, video_views


def get_video_names():
    names = list(ANNOTATIONS.keys())
    for name in VIDEO_PATHS:
        if name not in ANNOTATIONS:
            names.append(name)
    return names


# Load data. Keep LMDB compatibility, then overlay directly saved tool output.
ANNOTATIONS = load_annotations_from_lmdb(LMDB_PATH)
_tool_annotations, _tool_video_paths, _tool_video_views = load_robointertools_annotations(TOOLS_CONFIG_PATH)
ANNOTATIONS.update(_tool_annotations)
VIDEO_PATHS.update(_tool_video_paths)
VIDEO_VIEWS.update(_tool_video_views)
