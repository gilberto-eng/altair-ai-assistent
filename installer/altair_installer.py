from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import zipfile
import urllib.request
import threading




@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    description: str
    pip_packages: list[str]
    required: bool = False


FEATURES: list[Feature] = [
    Feature(
        key="core",
        label="Core (UI)",
        description="Interface + execucao basica do Altair.",
        pip_packages=[
            "psutil",
            "PyQt5",
            "requests",
            "pillow",
            "pygame",
            "pydantic",
            "qrcode",
            "python-docx",
            "pypdf",
        ],
        required=True,
    ),
    Feature(
        key="voz",
        label="Reconhecimento de fala (Whisper)",
        description="Microfone + transcricao (sounddevice + faster-whisper).",
        pip_packages=[
            "sounddevice",
            "numpy",
            "faster-whisper",
        ],
    ),
    Feature(
        key="automacao",
        label="Automacao (WhatsApp/abrir apps/web)",
        description="Automacao via Selenium e integracoes web.",
        pip_packages=[
            "selenium",
            "webdriver-manager",
            "undetected-chromedriver",
        ],
    ),
    Feature(
        key="api",
        label="API Remota (FastAPI)",
        description="Expor API HTTP para celular/rede.",
        pip_packages=[
            "fastapi",
            "uvicorn",
        ],
    ),
    Feature(
        key="macros",
        label="Macros (automatizar tarefas)",
        description="Gravacao e reproducao de mouse/teclado (pynput).",
        pip_packages=[
            "pynput",
        ],
    ),
    Feature(
        key="matematica",
        label="Matematica e graficos",
        description="Derivadas/integrais/graficos (sympy + matplotlib).",
        pip_packages=[
            "sympy",
            "matplotlib",
        ],
    ),
    Feature(
        key="cad",
        label="CAD / 3D",
        description="Modelagem 3D (cadquery + pyvista).",
        pip_packages=[
            "cadquery",
            "pyvista",
        ],
    ),
]


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, out.strip()


def _py() -> str:
    # Usa o python do proprio instalador (se for exe via PyInstaller, ainda funciona).
    return sys.executable


def _default_install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Altair"


def _copy_payload(dest: Path) -> None:
    """Instala o payload (codigo/recursos) na pasta de destino.

    - Distribuicao (.exe): extrai payload.zip embutido no executavel.
    - Dev (repo): copia pastas do projeto.
    """
    dest.mkdir(parents=True, exist_ok=True)

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        payload_zip = Path(str(meipass)) / "payload.zip"
        if not payload_zip.exists():
            raise RuntimeError("payload.zip nao encontrado dentro do instalador.")
        with zipfile.ZipFile(payload_zip, "r") as zf:
            zf.extractall(dest)
        return

    here = Path(__file__).resolve().parents[1]
    run_altair = here / "run_altair.py"
    if not run_altair.exists():
        raise RuntimeError("run_altair.py nao encontrado. Rode o instalador a partir da pasta do projeto.")

    for name in ("src", "assets", "configs", "scripts", "json"):
        src_path = here / name
        if not src_path.exists():
            continue
        dst_path = dest / name
        if dst_path.exists():
            shutil.rmtree(dst_path, ignore_errors=True)
        shutil.copytree(src_path, dst_path)
    shutil.copy2(run_altair, dest / "run_altair.py")
    run_macro = here / "run_macro.py"
    if run_macro.exists():
        shutil.copy2(run_macro, dest / "run_macro.py")


def _possible_python_paths() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))

    return [
        local / "Programs/Python/Python312/python.exe",
        local / "Programs/Python/Python311/python.exe",
    ]



def _find_python() -> Path | None:
    for cmd in ("py", "python"):
        try:
            code, out = _run([cmd, "--version"])
            if code == 0 and "Python" in out:
                result = shutil.which(cmd)
                if result:
                    return Path(result)
        except Exception:
            pass

    for p in _possible_python_paths():
        if p.exists():
            return p

    return None





def _install_python(dest: Path) -> None:
    installer = dest / "python_installer.exe"

    url = "https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe"

    urllib.request.urlretrieve(url, installer)

    code, out = _run([
        str(installer),
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_pip=1",
    ])

    if code != 0:
        raise RuntimeError(out or "Falha ao instalar Python")



def _embedded_python(dest: Path) -> Path:
    py = _find_python()

    if py:
        return Path(py)

    _install_python(dest)

    py = _find_python()

    if not py:
        raise RuntimeError("Python nao foi instalado corretamente.")

    return Path(py)



def _ensure_pip(py: Path, dest: Path) -> None:
    code, _out = _run([str(py), "-m", "pip", "--version"])
    if code == 0:
        return
    get_pip = dest / "python" / "get-pip.py"
    if not get_pip.exists():
        raise RuntimeError("pip nao encontrado e get-pip.py nao esta no payload. Rebuild o payload.")
    code2, out2 = _run([str(py), str(get_pip)])
    if code2 != 0:
        raise RuntimeError(out2 or "Falha ao instalar pip no Python embutido")


def _write_launcher(dest: Path) -> None:
    bat = dest / "Altair.bat"
    bat.write_text(
        "@echo off\n"
        "setlocal\n"
        "set ROOT=%~dp0\n"
        "\"%ROOT%\\.venv\\Scripts\\python.exe\" \"%ROOT%\\run_altair.py\"\n"
        "endlocal\n",
        encoding="utf-8",
    )


def _create_venv(dest: Path) -> Path:
    venv_dir = dest / ".venv"
    if venv_dir.exists():
        return venv_dir
    py = _embedded_python(dest)
    _ensure_pip(py, dest)
    code, out = _run([str(py), "-m", "venv", str(venv_dir)])
    if code != 0:
        _run([str(py), "-m", "pip", "install", "--upgrade", "virtualenv"])
        code2, out2 = _run([str(py), "-m", "virtualenv", str(venv_dir)])
        if code2 != 0:
            raise RuntimeError(out2 or out or "Falha ao criar venv")
    return venv_dir


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / "Scripts" / "python.exe"




def _pip_install(venv_dir: Path, packages: list[str], log=None) -> None:
    py = _venv_python(venv_dir)

    code, out = _run([
        str(py),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip"
    ])

    if code != 0:
        raise RuntimeError(out or "Falha ao atualizar pip")

    if not packages:
        return

    for pkg in packages:
        if log:
            log(f"Instalando: {pkg}")

        code, out = _run([
            str(py),
            "-m",
            "pip",
            "install",
            pkg
        ])

        if code != 0:
            raise RuntimeError(
                f"Falha ao instalar {pkg}\n\n{out}"
            )




class InstallerUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Instalador A.L.T.A.I.R")
        self.geometry("720x520")
        self.minsize(720, 520)

        self.install_dir = tk.StringVar(value=str(_default_install_dir()))
        self.vars: dict[str, tk.BooleanVar] = {}
        for f in FEATURES:
            self.vars[f.key] = tk.BooleanVar(value=f.required)
            if f.required:
                self.vars[f.key].set(True)

        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=14)
        top.pack(fill="x")

        ttk.Label(top, text="Diretorio de instalacao:").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(6, 0))
        ent = ttk.Entry(row, textvariable=self.install_dir)
        ent.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Escolher...", command=self._pick_dir).pack(side="left", padx=(8, 0))

        mid = ttk.Frame(self, padding=(14, 10))
        mid.pack(fill="both", expand=True)

        ttk.Label(mid, text="Ferramentas integradas:").pack(anchor="w")
        list_frame = ttk.Frame(mid)
        list_frame.pack(fill="both", expand=True, pady=(8, 0))

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self._scroll = ttk.Frame(canvas)

        self._scroll.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._scroll, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for f in FEATURES:
            card = ttk.Frame(self._scroll, padding=10)
            card.pack(fill="x", pady=6)
            chk = ttk.Checkbutton(
                card,
                text=f.label,
                variable=self.vars[f.key],
                command=lambda ff=f: self._on_toggle(ff),
            )
            chk.pack(anchor="w")
            ttk.Label(card, text=f.description, foreground="#445").pack(anchor="w", pady=(2, 0))
            if f.required:
                ttk.Label(card, text="(Obrigatorio)", foreground="#744").pack(anchor="w", pady=(2, 0))

        bot = ttk.Frame(self, padding=14)
        bot.pack(fill="x")
        self.progress = ttk.Progressbar(bot, mode="indeterminate")
        self.progress.pack(fill="x")
        btn_row = ttk.Frame(bot)
        btn_row.pack(fill="x", pady=(10, 0))
        
        ttk.Button(
        btn_row,
        text="Instalar",
        command=lambda: threading.Thread(
        target=self._install,
        daemon=True
        ).start()
        ).pack(side="right")


        ttk.Button(btn_row, text="Sair", command=self.destroy).pack(side="right", padx=(0, 8))

        self.log = tk.Text(self, height=8)
        self.log.pack(fill="both", padx=14, pady=(0, 14))
        self.log.insert("end", "Selecione as ferramentas e clique em Instalar.\n")
        self.log.configure(state="disabled")

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.update_idletasks()

    def _pick_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=self.install_dir.get(), title="Escolha o diretorio de instalacao")
        if d:
            self.install_dir.set(d)

    def _on_toggle(self, feat: Feature) -> None:
        if feat.required:
            self.vars[feat.key].set(True)

    def _install(self) -> None:
        dest = Path(self.install_dir.get()).expanduser()
        selected = [f for f in FEATURES if self.vars[f.key].get()]
        pkgs: list[str] = []
        for f in selected:
            pkgs.extend(f.pip_packages)

        # remove duplicados preservando ordem
        seen: set[str] = set()
        pkgs2: list[str] = []
        for p in pkgs:
            if p not in seen:
                seen.add(p)
                pkgs2.append(p)

        self.progress.start(10)
        try:
            self._log(f"Instalando em: {dest}")
            self._log("Copiando arquivos...")
            _copy_payload(dest)

            self._log("Criando ambiente virtual...")
            venv_dir = _create_venv(dest)

            self._log("Instalando bibliotecas (pip)...")
            self._log("Pacotes: " + ", ".join(pkgs2))
            _pip_install(venv_dir, pkgs2, self._log)

            self._log("Criando launcher...")
            _write_launcher(dest)

            cfg = {"features": [f.key for f in selected]}
            (dest / "install_features.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

            self._log("OK. Instalacao concluida.")
            messagebox.showinfo("Altair", "Instalacao concluida.\nAbra pelo arquivo Altair.bat dentro da pasta instalada.")
        except Exception as exc:
            self._log("ERRO: " + str(exc))
            messagebox.showerror("Altair", str(exc))
        finally:
            self.progress.stop()


def main() -> int:
    app = InstallerUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

