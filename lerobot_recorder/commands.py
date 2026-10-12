"""Construction des commandes `lerobot-teleoperate` / `lerobot-record`.

Ce module ne fait qu'assembler des listes d'arguments — aucune exécution ici,
voir system.run() pour ça. Ça permet de tester la construction des commandes
(--dry-run, ou des tests unitaires) sans toucher au matériel.
"""

from __future__ import annotations

import json

from .config import CameraSettings, Settings


def build_cameras_json(camera: CameraSettings) -> str:
    """Config JSON pour --robot.cameras, avec les 3 caméras front/wrist/side."""
    cams = {
        "front": {
            "type": "opencv", "index_or_path": camera.front_index,
            "width": camera.width, "height": camera.height, "fps": camera.fps,
        },
        "wrist": {
            "type": "opencv", "index_or_path": camera.wrist_index,
            "width": camera.width, "height": camera.height, "fps": camera.fps,
        },
        "side": {
            "type": "opencv", "index_or_path": camera.side_index,
            "width": camera.width, "height": camera.height, "fps": camera.fps,
        },
    }
    return json.dumps(cams)


def build_teleoperate_cmd(settings: Settings, with_cameras: bool) -> list[str]:
    """`lerobot-teleoperate` : test simple des bras (with_cameras=False),
    ou aperçu complet caméras + bras (with_cameras=True). Aucun dataset créé."""
    arm = settings.arm
    cmd = [
        "lerobot-teleoperate",
        "--robot.type=so101_follower",
        f"--robot.port={arm.follower_port}",
        f"--robot.id={arm.follower_id}",
    ]
    if with_cameras:
        cmd.append(f"--robot.cameras={build_cameras_json(settings.camera)}")
    cmd += [
        "--teleop.type=so101_leader",
        f"--teleop.port={arm.leader_port}",
        f"--teleop.id={arm.leader_id}",
        f"--display_data={'true' if settings.display_data else 'false'}",
    ]
    return cmd


def build_record_cmd(
    settings: Settings,
    repo_id: str,
    task: str,
    episodes: int,
    resume: bool,
    dataset_root: str | None,
) -> list[str]:
    """`lerobot-record` avec les 3 caméras, pour une série de `episodes` épisodes."""
    arm = settings.arm
    ds = settings.dataset
    cmd = [
        "lerobot-record",
        "--robot.type=so101_follower",
        f"--robot.port={arm.follower_port}",
        f"--robot.id={arm.follower_id}",
        f"--robot.cameras={build_cameras_json(settings.camera)}",
        "--teleop.type=so101_leader",
        f"--teleop.port={arm.leader_port}",
        f"--teleop.id={arm.leader_id}",
        f"--display_data={'true' if settings.display_data else 'false'}",
        f"--dataset.repo_id={repo_id}",
        f"--dataset.single_task={task}",
        f"--dataset.num_episodes={episodes}",
        f"--dataset.episode_time_s={ds.episode_time_s}",
        f"--dataset.reset_time_s={ds.reset_time_s}",
        f"--dataset.push_to_hub={'true' if ds.push_to_hub else 'false'}",
        f"--dataset.streaming_encoding={'true' if ds.streaming_encoding else 'false'}",
        f"--dataset.encoder_threads={ds.encoder_threads}",
    ]
    if ds.auto_vcodec:
        cmd.append("--dataset.rgb_encoder.vcodec=auto")
    if resume:
        cmd.append("--resume=true")
        cmd.append(f"--dataset.root={dataset_root}")
    return cmd
