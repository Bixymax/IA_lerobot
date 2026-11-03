"""Petits helpers d'affichage terminal (bannières, rappels clavier)."""

from __future__ import annotations

from .config import CameraSettings


def banner(title: str) -> None:
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)


def camera_summary(camera: CameraSettings) -> str:
    return (
        f"front={camera.front_index}  wrist={camera.wrist_index}  side={camera.side_index}  "
        f"({camera.width}x{camera.height}@{camera.fps}fps)"
    )


def recording_controls() -> None:
    print("Pendant l'enregistrement :")
    print("  → ou n : terminer l'épisode courant / passer au suivant")
    print("  ← ou r : annuler et ré-enregistrer l'épisode courant")
    print("  ESC ou q : arrêter, encoder les vidéos et uploader le dataset")
