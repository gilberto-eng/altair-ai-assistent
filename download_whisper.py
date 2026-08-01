import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def ensure_huggingface_hub():
    try:
        from huggingface_hub import snapshot_download  # type: ignore

        return snapshot_download
    except Exception:
        print("Instalando huggingface-hub...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface-hub"])
        from huggingface_hub import snapshot_download  # type: ignore

        return snapshot_download


def flatten_existing_nested_dir(target_dir: Path) -> None:
    nested_dir = target_dir / "whisper-base"
    if not nested_dir.exists() or not nested_dir.is_dir():
        return

    for child in nested_dir.iterdir():
        destination = target_dir / child.name
        if child.is_dir():
            if destination.exists():
                shutil.copytree(child, destination, dirs_exist_ok=True)
            else:
                shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)

    shutil.rmtree(nested_dir)


def download_whisper_model(target_dir: Path, repo_id: str = "openai/whisper-base") -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    flatten_existing_nested_dir(target_dir)

    snapshot_download = ensure_huggingface_hub()

    print(f"Baixando modelo {repo_id} para {target_dir}...")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        repo_type="model",
    )

    print("Download concluído.")
    print(f"Arquivos salvos diretamente em: {target_dir}")
    print("Nenhuma subpasta adicional foi criada dentro da pasta do modelo.")
    return target_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Baixa o modelo Whisper para o projeto")
    parser.add_argument(
        "--target",
        default=str(project_root() / "data" / "models" / "whisper-base"),
        help="Diretório onde o modelo será salvo",
    )
    parser.add_argument(
        "--repo-id",
        default="openai/whisper-base",
        help="ID do repositório Hugging Face do modelo Whisper",
    )
    args = parser.parse_args()

    target_dir = Path(args.target).resolve()
    download_whisper_model(target_dir=target_dir, repo_id=args.repo_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
