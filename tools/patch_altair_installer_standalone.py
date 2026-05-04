# Auto-patcher for installer/altair_installer.py
# Keeps edits reproducible when we need to regenerate the standalone-installer logic.

import re
from pathlib import Path


def main() -> None:
    p = Path("installer/altair_installer.py")
    txt = p.read_text(encoding="utf-8", errors="replace")

    # Remove unused import
    txt = txt.replace("import tempfile\n", "")

    # Update core packages (add common runtime deps)
    txt = txt.replace(
        '        pip_packages=[\n            "psutil",\n            "PyQt5",\n        ],\n',
        '        pip_packages=[\n            "psutil",\n            "PyQt5",\n            "requests",\n            "pillow",\n            "pygame",\n            "pydantic",\n            "qrcode",\n            "python-docx",\n            "pypdf",\n        ],\n',
    )

    # Whisper optional label/description
    txt = txt.replace(
        '        key="voz",\n        label="Voz (microfone + Whisper)",\n        description="Reconhecimento de voz e audio (sounddevice + faster-whisper).",\n',
        '        key="voz",\n        label="Reconhecimento de fala (Whisper)",\n        description="Microfone + transcricao (sounddevice + faster-whisper).",\n',
    )

    # Automation deps
    txt = txt.replace(
        '        pip_packages=[\n            "selenium",\n        ],\n',
        '        pip_packages=[\n            "selenium",\n            "webdriver-manager",\n            "undetected-chromedriver",\n        ],\n',
    )

    # Replace _copy_payload + helper functions up to (but not including) def _create_venv(
    m = re.search(
        r"def _copy_payload\(dest: Path\) -> None:\n.*?\n\n\ndef _create_venv\(",
        txt,
        flags=re.S,
    )
    if not m:
        raise SystemExit("Nao encontrei _copy_payload para substituir.")

    new_block = (
        "def _copy_payload(dest: Path) -> None:\n"
        "    \"\"\"Instala o payload (codigo/recursos) na pasta de destino.\n\n"
        "    - Distribuicao (.exe): extrai payload.zip embutido no executavel.\n"
        "    - Dev (repo): copia pastas do projeto.\n"
        "    \"\"\"\n"
        "    dest.mkdir(parents=True, exist_ok=True)\n\n"
        "    meipass = getattr(sys, \"_MEIPASS\", None)\n"
        "    if meipass:\n"
        "        payload_zip = Path(str(meipass)) / \"payload.zip\"\n"
        "        if not payload_zip.exists():\n"
        "            raise RuntimeError(\"payload.zip nao encontrado dentro do instalador.\")\n"
        "        with zipfile.ZipFile(payload_zip, \"r\") as zf:\n"
        "            zf.extractall(dest)\n"
        "        return\n\n"
        "    here = Path(__file__).resolve().parents[1]\n"
        "    run_altair = here / \"run_altair.py\"\n"
        "    if not run_altair.exists():\n"
        "        raise RuntimeError(\"run_altair.py nao encontrado. Rode o instalador a partir da pasta do projeto.\")\n\n"
        "    for name in (\"src\", \"assets\", \"configs\", \"scripts\", \"json\"):\n"
        "        src_path = here / name\n"
        "        if not src_path.exists():\n"
        "            continue\n"
        "        dst_path = dest / name\n"
        "        if dst_path.exists():\n"
        "            shutil.rmtree(dst_path, ignore_errors=True)\n"
        "        shutil.copytree(src_path, dst_path)\n"
        "    shutil.copy2(run_altair, dest / \"run_altair.py\")\n"
        "    run_macro = here / \"run_macro.py\"\n"
        "    if run_macro.exists():\n"
        "        shutil.copy2(run_macro, dest / \"run_macro.py\")\n\n\n"
        "def _embedded_python(dest: Path) -> Path:\n"
        "    py = dest / \"python\" / \"python.exe\"\n"
        "    if not py.exists():\n"
        "        raise RuntimeError(\"Python embutido nao encontrado em <pasta>/python/python.exe. Rebuild o payload.\")\n"
        "    return py\n\n\n"
        "def _ensure_pip(py: Path, dest: Path) -> None:\n"
        "    code, _out = _run([str(py), \"-m\", \"pip\", \"--version\"])\n"
        "    if code == 0:\n"
        "        return\n"
        "    get_pip = dest / \"python\" / \"get-pip.py\"\n"
        "    if not get_pip.exists():\n"
        "        raise RuntimeError(\"pip nao encontrado e get-pip.py nao esta no payload. Rebuild o payload.\")\n"
        "    code2, out2 = _run([str(py), str(get_pip)])\n"
        "    if code2 != 0:\n"
        "        raise RuntimeError(out2 or \"Falha ao instalar pip no Python embutido\")\n\n\n"
        "def _write_launcher(dest: Path) -> None:\n"
        "    bat = dest / \"Altair.bat\"\n"
        "    bat.write_text(\n"
        "        \"@echo off\\n\"\n"
        "        \"setlocal\\n\"\n"
        "        \"set ROOT=%~dp0\\n\"\n"
        "        \"\\\"%ROOT%\\\\.venv\\\\Scripts\\\\python.exe\\\" \\\"%ROOT%\\\\run_altair.py\\\"\\n\"\n"
        "        \"endlocal\\n\",\n"
        "        encoding=\"utf-8\",\n"
        "    )\n\n\n"
    )

    prefix = txt[: m.start()]
    # m ends right after "def _create_venv("; keep the marker and everything after
    suffix = txt[m.end() - len("def _create_venv(") :]
    txt = prefix + new_block + suffix

    # Patch _create_venv to use embedded python for venv creation
    txt = txt.replace(
        '    code, out = _run([_py(), "-m", "venv", str(venv_dir)])\n',
        '    py = _embedded_python(dest)\n    _ensure_pip(py, dest)\n    code, out = _run([str(py), "-m", "venv", str(venv_dir)])\n',
    )

    # Ensure fallback to virtualenv exists
    if '"virtualenv"' not in txt and "virtualenv" not in txt:
        txt = txt.replace(
            '    if code != 0:\n        raise RuntimeError(out or "Falha ao criar venv")\n',
            '    if code != 0:\n        _run([str(py), "-m", "pip", "install", "--upgrade", "virtualenv"])\n        code2, out2 = _run([str(py), "-m", "virtualenv", str(venv_dir)])\n        if code2 != 0:\n            raise RuntimeError(out2 or out or "Falha ao criar venv")\n',
        )

    # Call launcher during install
    if "_write_launcher(dest)" not in txt:
        txt = txt.replace(
            "            _pip_install(venv_dir, pkgs2)\n\n            cfg = {\"features\": [f.key for f in selected]}",
            "            _pip_install(venv_dir, pkgs2)\n\n            self._log(\"Criando launcher...\")\n            _write_launcher(dest)\n\n            cfg = {\"features\": [f.key for f in selected]}",
        )

    txt = txt.replace("Abra pelo arquivo run_altair.py", "Abra pelo arquivo Altair.bat")

    p.write_text(txt, encoding="utf-8")
    print("OK")


if __name__ == "__main__":
    main()
