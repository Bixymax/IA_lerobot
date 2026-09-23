"""Structures de réglages pour l'enregistrement LeRobot.

Les valeurs par défaut des bras peuvent être surchargées par variables
d'environnement (PORT_FOLLOWER, PORT_LEADER, FOLLOWER_ID, LEADER_ID),
pratique quand les ports changent d'une machine à l'autre.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ArmSettings:
    follower_port: str = os.environ.get("PORT_FOLLOWER", "/dev/ttyACM0")
    leader_port: str = os.environ.get("PORT_LEADER", "/dev/ttyACM1")
    follower_id: str = os.environ.get("FOLLOWER_ID", "my_awesome_follower_arm")
    leader_id: str = os.environ.get("LEADER_ID", "my_awesome_leader_arm")


@dataclass
class CameraSettings:
    # Noms utilisés dans --robot.cameras : front / wrist / side
    front_index: int = 0
    wrist_index: int = 1
    side_index: int = 2
    width: int = 640
    height: int = 480
    fps: int = 30


@dataclass
class DatasetSettings:
    name: str = "my_dataset"
    num_episodes: int = 10
    episode_time_s: int = 60
    reset_time_s: int = 60
    encoder_threads: int = 2
    streaming_encoding: bool = True
    auto_vcodec: bool = False
    push_to_hub: bool = True
    repo_id_override: str | None = None
    dataset_root: str | None = None
    resume: bool = False


@dataclass
class Settings:
    """Regroupe tous les réglages utilisés par les commandes et actions."""
    arm: ArmSettings = field(default_factory=ArmSettings)
    camera: CameraSettings = field(default_factory=CameraSettings)
    dataset: DatasetSettings = field(default_factory=DatasetSettings)
    display_data: bool = True
    dry_run: bool = False
    task: str | None = None
