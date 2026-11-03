"""Utilitaires bas niveau : vérifications système, exécution de commandes, Hugging Face."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .config import Settings


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def require_command(cmd: str) -> None:
    """Quitte proprement si un binaire lerobot-* n'est pas dans le PATH."""
    if shutil.which(cmd) is None:
        eprint(f"❌ '{cmd}' est introuvable dans le PATH.")
        eprint("   Active ton environnement LeRobot d'abord : conda activate lerobot")
        sys.exit(1)


def check_port(port: str) -> None:
    """Avertit (sans bloquer) si un port série n'existe pas."""
    if not Path(port).exists():
        eprint(f"⚠️  Port introuvable : {port}  (branché ? bon nom ? -> ls /dev/ttyACM* /dev/ttyUSB*)")


def get_hf_user() -> str | None:
    """Nom d'utilisateur Hugging Face connecté via `hf auth login`, ou None."""
    if shutil.which("hf") is None:
        return None
    try:
        out = subprocess.run(
            ["hf", "auth", "whoami"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except Exception:
        return None
    first_line = out.strip().splitlines()[0] if out.strip() else ""
    if ":" in first_line:
        return first_line.split(":", 1)[1].strip()
    return first_line or None


def resolve_repo_id(settings: Settings) -> str:
    """Détermine le dataset.repo_id à utiliser (Hub ou local)."""
    ds = settings.dataset
    if ds.repo_id_override:
        return ds.repo_id_override
    if not ds.push_to_hub:
        return f"local/{ds.name}"
    hf_user = get_hf_user()
    if not hf_user:
        eprint("❌ Pas connecté au Hugging Face Hub (ou CLI 'hf' introuvable).")
        eprint("   Connecte-toi avec : hf auth login --add-to-git-credential")
        eprint("   Ou relance avec --no-push pour enregistrer en local uniquement.")
        sys.exit(1)
    return f"{hf_user}/{ds.name}"


def default_dataset_root(repo_id: str) -> str:
    return str(Path.home() / ".cache" / "huggingface" / "lerobot" / repo_id)


def _shell_quote(s: str) -> str:
    if any(c in s for c in " {}\"'$"):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


def run(cmd: list[str], dry_run: bool) -> bool:
    """Affiche puis exécute une commande lerobot-*.

    Retourne True si elle s'est terminée normalement (ou en dry-run),
    False si interrompue (Ctrl+C) ou terminée en erreur.
    """
    print("\nCommande :")
    print(" ".join(_shell_quote(c) for c in cmd))
    print()
    if dry_run:
        print("[dry-run] Rien n'a été exécuté.")
        return True
    try:
        subprocess.run(cmd, check=True)
        return True
    except KeyboardInterrupt:
        print("\n⏹️  Interrompu (Ctrl+C).")
        return False
    except subprocess.CalledProcessError as e:
        eprint(f"❌ La commande a échoué (code {e.returncode}).")
        return False
