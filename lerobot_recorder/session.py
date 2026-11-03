"""Menu interactif : tester les bras, prévisualiser les caméras, enregistrer en boucle
en enchaînant rapidement les séries (reprise automatique du même dataset)."""

from __future__ import annotations

from . import actions, ui
from .commands import build_record_cmd
from .config import Settings
from .system import check_port, default_dataset_root, require_command, resolve_repo_id, run


def _ask(prompt_text: str, default: str | None = None) -> str | None:
    suffix = f" [{default}]" if default is not None else ""
    try:
        val = input(f"{prompt_text}{suffix} : ").strip()
    except EOFError:
        return None
    return val if val else default


def run_session(settings: Settings) -> None:
    require_command("lerobot-record")
    require_command("lerobot-teleoperate")
    check_port(settings.arm.follower_port)
    check_port(settings.arm.leader_port)

    repo_id = resolve_repo_id(settings)
    ds = settings.dataset
    dataset_root = ds.dataset_root
    already_recorded = False  # True dès qu'une série a réussi -> les suivantes utilisent --resume
    total_episodes = 0
    last_task = settings.task or ""
    last_episodes = ds.num_episodes

    ui.banner("Session interactive")
    print(f" Dataset repo_id   : {repo_id}")
    print(f" Follower / Leader : {settings.arm.follower_port} / {settings.arm.leader_port}")
    print(f" Caméras           : {ui.camera_summary(settings.camera)}")
    print("=" * 60)

    while True:
        print()
        print("Que veux-tu faire ?")
        print("  [1] Tester les bras (téléopération simple, sans caméras)")
        print("  [2] Prévisualiser les caméras (téléopération + caméras)")
        print("  [3] Enregistrer une série d'épisodes")
        if total_episodes:
            print(f"      (épisodes déjà enregistrés cette session : {total_episodes})")
        print("  [4] Quitter")
        choice = _ask("Ton choix", "3" if total_episodes else "1")
        if choice is None:
            break
        choice = choice.strip().lower()

        if choice in ("1", "bras", "arms", "test"):
            actions.test_arms(settings)
            continue

        if choice in ("2", "p", "preview"):
            actions.preview_cameras(settings)
            continue

        if choice in ("4", "q", "quit", "quitter"):
            break

        if choice not in ("3", "r", "record", "enregistrer"):
            print("Choix non reconnu, réessaie.")
            continue

        task = _ask("Description de la tâche", last_task or None)
        if not task:
            print("⚠️  Une description de tâche est nécessaire, série annulée.")
            continue

        episodes_str = _ask("Nombre d'épisodes pour cette série", str(last_episodes))
        try:
            episodes = int(episodes_str)
            if episodes <= 0:
                raise ValueError
        except (TypeError, ValueError):
            print("⚠️  Nombre d'épisodes invalide, série annulée.")
            continue

        if already_recorded and not dataset_root:
            dataset_root = default_dataset_root(repo_id)

        cmd = build_record_cmd(
            settings, repo_id, task, episodes,
            resume=already_recorded,
            dataset_root=dataset_root,
        )

        print()
        print(f"▶️  Série de {episodes} épisode(s) — tâche : « {task} »")
        if already_recorded:
            print("   (reprise du même dataset, épisodes ajoutés à la suite)")
        ui.recording_controls()

        ok = run(cmd, dry_run=settings.dry_run)

        if ok and not settings.dry_run:
            already_recorded = True
            total_episodes += episodes
        last_task, last_episodes = task, episodes

        print("✅ Série terminée — retour au menu pour enchaîner rapidement.")

    print()
    print(f"Session terminée. Épisodes enregistrés au total : {total_episodes}")
    if total_episodes and ds.push_to_hub:
        print(f"Dataset : https://huggingface.co/datasets/{repo_id}")
