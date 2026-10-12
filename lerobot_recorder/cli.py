"""Interface en ligne de commande : construit le parser, convertit les arguments
en Settings, puis lance l'action demandée (ponctuelle, directe, ou le menu interactif)."""

from __future__ import annotations

import argparse

from . import actions, session
from .config import ArmSettings, CameraSettings, DatasetSettings, Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enregistre un dataset LeRobot avec 3 caméras (bras SO101 unique).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="Sans option d'action (--test-arms/--preview/--find-*/--task), "
               "lance le menu interactif : python -m lerobot_recorder",
    )

    # Actions ponctuelles
    parser.add_argument("--find-ports", action="store_true",
                         help="Lance `lerobot-find-port` pour identifier les ports USB, puis quitte.")
    parser.add_argument("--find-cameras", action="store_true",
                         help="Lance `lerobot-find-cameras opencv` pour identifier les index caméras, puis quitte.")
    parser.add_argument("--test-arms", action="store_true",
                         help="Téléopération simple SANS caméras, pour tester les bras, puis quitte.")
    parser.add_argument("--preview", action="store_true",
                         help="Aperçu caméras + téléopération, sans rien enregistrer, puis quitte.")

    # Bras
    _arm = ArmSettings()
    parser.add_argument("--follower-port", default=_arm.follower_port)
    parser.add_argument("--leader-port", default=_arm.leader_port)
    parser.add_argument("--follower-id", default=_arm.follower_id)
    parser.add_argument("--leader-id", default=_arm.leader_id)

    # Caméras
    _cam = CameraSettings()
    parser.add_argument("--cam-front-index", type=int, default=_cam.front_index)
    parser.add_argument("--cam-wrist-index", type=int, default=_cam.wrist_index)
    parser.add_argument("--cam-side-index", type=int, default=_cam.side_index)
    parser.add_argument("--cam-width", type=int, default=_cam.width)
    parser.add_argument("--cam-height", type=int, default=_cam.height)
    parser.add_argument("--cam-fps", type=int, default=_cam.fps)

    # Dataset
    _ds = DatasetSettings()
    parser.add_argument("--task", type=str, default=None,
                         help="Description de la tâche. Sans elle (et sans les actions ponctuelles ci-dessus), "
                              "lance le menu interactif.")
    parser.add_argument("--dataset-name", default=_ds.name)
    parser.add_argument("--episodes", type=int, default=_ds.num_episodes)
    parser.add_argument("--episode-time", type=int, default=_ds.episode_time_s)
    parser.add_argument("--reset-time", type=int, default=_ds.reset_time_s)
    parser.add_argument("--encoder-threads", type=int, default=_ds.encoder_threads)
    parser.add_argument("--no-streaming-encoding", action="store_true",
                         help="Désactive dataset.streaming_encoding (activé par défaut).")
    parser.add_argument("--auto-vcodec", action="store_true",
                         help="Ajoute --dataset.rgb_encoder.vcodec=auto.")
    parser.add_argument("--resume", action="store_true",
                         help="(mode direct uniquement) Reprend un enregistrement existant.")
    parser.add_argument("--dataset-root", default=None,
                         help="Chemin local du dataset, utilisé pour les reprises (--resume).")
    parser.add_argument("--no-push", action="store_true",
                         help="N'upload pas sur le Hugging Face Hub (local uniquement).")
    parser.add_argument("--no-display", action="store_true",
                         help="Désactive la visualisation live (utile en SSH/headless).")
    parser.add_argument("--repo-id", default=None,
                         help="Force le repo_id complet (ex: monuser/mon_dataset), sinon déduit de --dataset-name.")

    parser.add_argument("--dry-run", action="store_true",
                         help="Affiche les commandes sans les exécuter.")

    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    return Settings(
        arm=ArmSettings(
            follower_port=args.follower_port,
            leader_port=args.leader_port,
            follower_id=args.follower_id,
            leader_id=args.leader_id,
        ),
        camera=CameraSettings(
            front_index=args.cam_front_index,
            wrist_index=args.cam_wrist_index,
            side_index=args.cam_side_index,
            width=args.cam_width,
            height=args.cam_height,
            fps=args.cam_fps,
        ),
        dataset=DatasetSettings(
            name=args.dataset_name,
            num_episodes=args.episodes,
            episode_time_s=args.episode_time,
            reset_time_s=args.reset_time,
            encoder_threads=args.encoder_threads,
            streaming_encoding=not args.no_streaming_encoding,
            auto_vcodec=args.auto_vcodec,
            push_to_hub=not args.no_push,
            repo_id_override=args.repo_id,
            dataset_root=args.dataset_root,
            resume=args.resume,
        ),
        display_data=not args.no_display,
        dry_run=args.dry_run,
        task=args.task,
    )


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = settings_from_args(args)

    if args.find_ports:
        actions.find_ports()
        return
    if args.find_cameras:
        actions.find_cameras()
        return
    if args.test_arms:
        actions.test_arms(settings)
        return
    if args.preview:
        actions.preview_cameras(settings)
        return
    if settings.task:
        # Mode direct : un seul enregistrement (utile pour scripter / --dry-run).
        actions.record_direct(settings)
        return

    # Aucune action ponctuelle ni tâche -> menu interactif.
    try:
        session.run_session(settings)
    except KeyboardInterrupt:
        print("\n👋 Session interrompue.")
