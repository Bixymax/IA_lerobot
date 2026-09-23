"""Actions ponctuelles : find-ports, find-cameras, test des bras, aperçu caméras,
enregistrement direct (mode scriptable, un seul appel = un seul enregistrement)."""

from __future__ import annotations

import subprocess

from . import ui
from .commands import build_record_cmd, build_teleoperate_cmd
from .config import Settings
from .system import check_port, default_dataset_root, require_command, resolve_repo_id, run


def find_ports() -> None:
    require_command("lerobot-find-port")
    subprocess.run(["lerobot-find-port"], check=True)


def find_cameras() -> None:
    require_command("lerobot-find-cameras")
    subprocess.run(["lerobot-find-cameras", "opencv"], check=True)


def test_arms(settings: Settings) -> None:
    """Téléopération SANS caméras : vérifie juste que le leader pilote bien le follower."""
    require_command("lerobot-teleoperate")
    check_port(settings.arm.follower_port)
    check_port(settings.arm.leader_port)

    cmd = build_teleoperate_cmd(settings, with_cameras=False)
    ui.banner("Test des bras (téléopération simple, sans caméras)")
    print(f" Follower : {settings.arm.follower_port}   Leader : {settings.arm.leader_port}")
    print(" Bouge le bras leader et vérifie que le follower suit bien. Ctrl+C pour arrêter.")
    run(cmd, dry_run=settings.dry_run)


def preview_cameras(settings: Settings) -> None:
    """Téléopération + caméras, SANS dataset : vérifier le cadrage avant d'enregistrer."""
    require_command("lerobot-teleoperate")
    check_port(settings.arm.follower_port)
    check_port(settings.arm.leader_port)

    cmd = build_teleoperate_cmd(settings, with_cameras=True)
    ui.banner("Aperçu caméras + téléopération (rien n'est enregistré)")
    print(f" Caméras : {ui.camera_summary(settings.camera)}")
    print(" Ctrl+C pour arrêter l'aperçu.")
    run(cmd, dry_run=settings.dry_run)


def record_direct(settings: Settings) -> None:
    """Un seul enregistrement, entièrement piloté par les arguments CLI (mode scriptable)."""
    require_command("lerobot-record")
    check_port(settings.arm.follower_port)
    check_port(settings.arm.leader_port)

    repo_id = resolve_repo_id(settings)
    ds = settings.dataset
    dataset_root = ds.dataset_root
    if ds.resume and not dataset_root:
        dataset_root = default_dataset_root(repo_id)
        print(f"ℹ️  --resume sans --dataset-root : utilisation de {dataset_root}")

    cmd = build_record_cmd(settings, repo_id, settings.task, ds.num_episodes, ds.resume, dataset_root)

    ui.banner("Enregistrement de dataset — récapitulatif")
    print(f" Tâche             : {settings.task}")
    print(f" Episodes          : {ds.num_episodes} (durée max {ds.episode_time_s}s, reset {ds.reset_time_s}s)")
    print(f" Dataset repo_id   : {repo_id}")
    print(f" Push vers le Hub  : {ds.push_to_hub}")
    print(f" Reprise (resume)  : {ds.resume}")
    print(f" Follower / Leader : {settings.arm.follower_port} / {settings.arm.leader_port}")
    print(f" Caméras           : {ui.camera_summary(settings.camera)}")
    print("=" * 60)
    print()
    ui.recording_controls()

    run(cmd, dry_run=settings.dry_run)
