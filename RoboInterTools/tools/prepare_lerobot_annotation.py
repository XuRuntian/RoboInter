#!/usr/bin/env python3
"""
Prepare a LeRobot dataset for RoboInterTools annotation.

This script does the fixed setup steps before launching the annotation server:
- collect LeRobot videos into a flat RoboInterTools work directory
- create video_2_anno.json and user_list.txt
- write no_annotation_*.json / has_annotation_*.json pools
- back up and rewrite config/config.yaml for this dataset

By default videos are symlinked without transcoding. Use --transcode only if
the client or OpenCV cannot decode the original videos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import yaml


def sanitize_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    value = value.strip("._-")
    return value or "dataset"


def relative_to_root(path: Path, root_dir: Path) -> str:
    return path.resolve().relative_to(root_dir.resolve()).as_posix()


def discover_videos(src: Path, camera_filter: str = "") -> list[Path]:
    videos = sorted((src / "videos").glob("**/*.mp4"))
    if camera_filter:
        videos = [video for video in videos if camera_name(video) == camera_filter]
    return videos


def camera_name(video_path: Path) -> str:
    # LeRobot v2.1: videos/chunk-000/{camera}/episode_000000.mp4
    # LeRobot v3:   videos/{camera}/chunk-000/file_000000.mp4
    if video_path.parent.name.startswith("chunk-"):
        return video_path.parent.parent.name
    return video_path.parent.name


def chunk_name(video_path: Path) -> str:
    if video_path.parent.name.startswith("chunk-"):
        return video_path.parent.name
    if video_path.parent.parent.name.startswith("chunk-"):
        return video_path.parent.parent.name
    return "chunk-unknown"


def flat_video_name(video_path: Path) -> str:
    camera = sanitize_name(camera_name(video_path).replace(".", "_"))
    chunk = sanitize_name(chunk_name(video_path))
    return f"{camera}_{chunk}_{video_path.name}"


def episode_name(video_path: Path) -> str:
    return video_path.stem


def flat_episode_name(video_path: Path) -> str:
    chunk = sanitize_name(chunk_name(video_path))
    return f"{chunk}_{episode_name(video_path)}"


def prepare_video(video_path: Path, dst: Path, transcode: bool, force: bool) -> None:
    if dst.exists() or dst.is_symlink():
        if not force:
            print(f"skip existing: {dst}")
            return
        dst.unlink()

    if transcode:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg was not found; rerun without --transcode or install ffmpeg")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                "-preset",
                "veryfast",
                str(dst),
            ],
            check=True,
        )
    else:
        os.symlink(video_path.resolve(), dst)

    print(dst)


def group_multiview_videos(videos: list[Path]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for video in videos:
        key = flat_episode_name(video)
        camera = sanitize_name(camera_name(video).replace(".", "_"))
        grouped.setdefault(key, {})[camera] = str(video.absolute())
    return grouped


def write_video_mapping(out_dir: Path, videos: list[Path]) -> Path:
    mapping_path = out_dir / "video_2_anno.json"
    with mapping_path.open("w") as f:
        json.dump({str(video.absolute()): "" for video in videos}, f, indent=2)
    return mapping_path


def write_user_list(out_dir: Path, users: list[str]) -> Path:
    user_list_path = out_dir / "user_list.txt"
    with user_list_path.open("w") as f:
        for user in users:
            f.write(user + "\n")
    return user_list_path


def distribute_videos(video_paths: list[Path], users: list[str], save_path_template: str) -> dict:
    pools = {user: {} for user in users}
    for idx, video_path in enumerate(video_paths):
        user = users[idx % len(users)]
        video_name = video_path.stem
        pools[user][str(video_path.absolute())] = {
            "anno_path": "",
            "save_path": save_path_template.format(video_name=video_name),
        }
    return pools


def distribute_multiview_episodes(grouped_videos: dict[str, dict[str, str]], users: list[str], save_path_template: str) -> dict:
    pools = {user: {} for user in users}
    for idx, (episode_id, views) in enumerate(sorted(grouped_videos.items())):
        user = users[idx % len(users)]
        primary_video = next(iter(sorted(views.values())))
        pools[user][episode_id] = {
            "anno_path": "",
            "save_path": save_path_template.format(video_name=episode_id),
            "views": views,
            "video_path": primary_video,
        }
    return pools


def write_annotation_pools(out_dir: Path, videos: list[Path], users: list[str], config: dict) -> None:
    server_cfg = config["server"]
    lang_pool = distribute_multiview_episodes(
        group_multiview_videos(videos), users, server_cfg["save_path_lang_temp"]
    )
    sam_pool = distribute_videos(videos, users, server_cfg["save_path_sam_temp"])
    for mode, no_annotation in (("lang", lang_pool), ("sam", sam_pool)):
        has_annotation = {user: {} for user in users}
        with (out_dir / f"no_annotation_{mode}.json").open("w") as f:
            json.dump(no_annotation, f, indent=2)
        with (out_dir / f"has_annotation_{mode}.json").open("w") as f:
            json.dump(has_annotation, f, indent=2)


def build_config(root_dir: Path, out_dir: Path, device: str) -> dict:
    out_rel = relative_to_root(out_dir, root_dir)
    return {
        "sam": {
            "sam_ckpt_path": "segment-anything-2/checkpoints/sam2.1_hiera_large.pt",
            "model_config": "configs/sam2.1/sam2.1_hiera_l.yaml",
            "threshold": 0.5,
            "device": device,
        },
        "cotracker": {},
        "server": {
            "root_dir": str(root_dir.resolve()),
            "no_annotation_lang": f"{out_rel}/no_annotation_lang.json",
            "no_annotation_sam": f"{out_rel}/no_annotation_sam.json",
            "has_annotation_lang": f"{out_rel}/has_annotation_lang.json",
            "has_annotation_sam": f"{out_rel}/has_annotation_sam.json",
            "user_list_file": f"{out_rel}/user_list.txt",
            "user_history_dir": f"{out_rel}/user_config",
            "save_path_lang_temp": f"{out_rel}/human_anno_lang/{{video_name}}.npz",
            "save_path_sam_temp": f"{out_rel}/human_anno_sam/0/sam/{{video_name}}.npz",
            "sam_mask_save_path": f"{out_rel}/human_anno_sam/0/sam_mask/{{video_name}}.npz",
            "sam_video_save_path": f"{out_rel}/human_anno_sam/0/sam_video/{{video_name}}.mp4",
            "video_dir": f"{out_rel}/videos",
            "error_log": f"{out_rel}/user_config/error_video.txt",
        },
    }


def backup_and_write_config(config_path: Path, config: dict) -> Path | None:
    backup_path = None
    if config_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = config_path.with_name(config_path.name + f".bak.{stamp}")
        shutil.copy2(config_path, backup_path)

    with config_path.open("w") as f:
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=False)

    return backup_path


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    root_dir = script_dir.parent
    parser = argparse.ArgumentParser(
        description="Prepare a LeRobot dataset for RoboInterTools annotation."
    )
    parser.add_argument(
        "--src",
        required=True,
        type=Path,
        help="LeRobot dataset root, e.g. /home/user/robocoin_data/Agilex_Cobot_Magic_fold_towel_blue_tray",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output work directory. Default: asserts/lerobot_{dataset_name}",
    )
    parser.add_argument(
        "--camera-filter",
        default="",
        help="Only include one camera key, e.g. observation.images.cam_head_rgb. Default: include all cameras.",
    )
    parser.add_argument(
        "--user",
        action="append",
        default=None,
        help="Annotator username. Can be repeated. Default: root.",
    )
    parser.add_argument(
        "--transcode",
        action="store_true",
        help="Transcode videos to H.264 instead of symlinking originals.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing prepared videos with new symlinks/transcoded files.",
    )
    parser.add_argument(
        "--device",
        default="cuda:0",
        help="SAM device written to config.yaml. Default: cuda:0.",
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=root_dir,
        help="RoboInterTools root directory. Default: inferred from this script.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root_dir / "config" / "config.yaml",
        help="RoboInterTools config.yaml path. Default: config/config.yaml.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root_dir = args.root_dir.resolve()
    src = args.src.resolve()
    if not (src / "videos").exists():
        raise FileNotFoundError(f"LeRobot videos directory not found: {src / 'videos'}")

    dataset_name = sanitize_name(src.name)
    out_dir = args.out.resolve() if args.out else root_dir / "asserts" / f"lerobot_{dataset_name}"
    video_out_dir = out_dir / "videos"
    video_out_dir.mkdir(parents=True, exist_ok=True)

    source_videos = discover_videos(src, args.camera_filter)
    if not source_videos:
        raise RuntimeError("No videos matched the dataset path and camera filter")

    prepared_videos: list[Path] = []
    for source_video in source_videos:
        dst = video_out_dir / flat_video_name(source_video)
        prepare_video(source_video, dst, args.transcode, args.force)
        prepared_videos.append(dst)

    users = args.user or ["root"]
    write_video_mapping(out_dir, prepared_videos)
    write_user_list(out_dir, users)

    config = build_config(root_dir, out_dir, args.device)
    write_annotation_pools(out_dir, prepared_videos, users, config)
    backup_path = backup_and_write_config(args.config, config)

    print("\nDone.")
    print(f"Prepared videos: {len(prepared_videos)}")
    print(f"Language episodes: {len(group_multiview_videos(prepared_videos))}")
    print(f"Work directory: {out_dir}")
    print(f"Task mapping: {out_dir / 'video_2_anno.json'}")
    print(f"SAM pool: {out_dir / 'no_annotation_sam.json'}")
    print(f"Config: {args.config}")
    if backup_path:
        print(f"Config backup: {backup_path}")
    print("\nNext commands:")
    print(f"  cd {root_dir}")
    print("  python server/server.py --port 5000")
    print("  python client/client.py")
    print("  python tools/parse_sam.py --username root --time 0")


if __name__ == "__main__":
    main()
