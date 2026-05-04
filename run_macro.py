import sys
from pathlib import Path


def main() -> int:
    # Permite rodar sem instalar o pacote (workspace layout: src/altair).
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "src"))

    from altair.macro_cli import main as macro_main  # type: ignore

    return int(macro_main())


if __name__ == "__main__":
    raise SystemExit(main())

