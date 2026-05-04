from __future__ import annotations

import re
from pathlib import Path

p = Path(installer/altair_installer.py)
txt = p.read_text(encoding=utf-8, errors=replace)

# Expand core deps
if requests not in txt:
    txt = txt.replace(
         "psutil",\n "PyQt5",\n,
         "psutil",\n "PyQt5",\n "requests",\n "pillow",\n "pygame",\n "pydantic",\n "qrcode",\n "python-docx",\n "pypdf",\n,
    )

# Automacao deps
if webdriver-manager not in txt:
    txt = txt.replace(
         pip_packages=[\n "selenium",\n ],\n,
         pip_packages=[\n "selenium",\n "webdriver-manager",\n "undetected-chromedriver",\n ],\n,
    )

# Replace _copy_payload body
m = re.search(rdef _copy_payload\(dest: Path\) -> None:\n.*?\n\n\ndef _create_venv\(, txt, flags=re.S)
if not m:
    raise SystemExit(Nao achei _copy_payload)

new_copy = "def _copy_payload(dest: Path) -> None:
    # Standalone: extrai payload.zip embutido no executavel.
    # Dev: copia do repo.
    dest.mkdir(parents=True, exist_ok=True)

    meipass = getattr(sys, _MEIPASS, None)
    if meipass:
        payload_zip = Path(str(meipass)) / payload.zip
        if not payload_zip.exists():
            raise RuntimeError(payload.zip nao encontrado dentro do instalador.)
        import zipfile
        with zipfile.ZipFile(payload_zip, r) as zf:
            zf.extractall(dest)
        return

    here = Path(__file__).resolve().parents[1]
    run_altair = here / run_altair.py
    if not run_altair.exists():
        raise RuntimeError(run_altair.py nao encontrado. Rode o instalador a partir do repo.)

    for name in (src, assets, configs, scripts, json):
        src_path = here / name
        if not src_path.exists():
            continue
        dst_path = dest / name
        if dst_path.exists():
            import shutil
            shutil.rmtree(dst_path, ignore_errors=True)
        import shutil
        shutil.copytree(src_path, dst_path)

    import shutil
    shutil.copy2(run_altair, dest / run_altair.py)
    run_macro = here / run_macro.py
    if run_macro.exists():
        shutil.copy2(run_macro, dest / run_macro.py)
"

prefix = txt[:m.start()]
suffix = txt[m.end() - len(\n\n\ndef _create_venv() :]
txt = prefix + new_copy + \n\n\n + suffix

# Insert launcher helper
if def _write_launcher not in txt:
    ins = "\n\ndef _write_launcher(dest: Path) -> None:
    bat = dest / Altair.bat
    bat.write_text(
        @echo off\n
        setlocal\n
        set ROOT=%~dp0\n
        "%ROOT%\\.venv\\Scripts\\python.exe" "%ROOT%\\run_altair.py"\n
        endlocal\n,
        encoding=utf-8,
    )
"
    txt = txt.replace(\n\nclass InstallerUI, ins + \n\nclass InstallerUI)

# Call launcher after pip
if _write_launcher(dest) not in txt:
    txt = txt.replace(
        _pip_install(venv_dir, pkgs2),
        _pip_install(venv_dir, pkgs2)\n\n self._log("Criando launcher...")\n _write_launcher(dest),
    )

# Update message
txt = txt.replace(Abra pelo arquivo run_altair.py, Abra pelo arquivo Altair.bat)

p.write_text(txt, encoding=utf-8)
print(OK)
