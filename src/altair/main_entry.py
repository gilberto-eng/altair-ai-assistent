import json
import ipaddress
import os
import socket
import threading
import sys
import atexit
from difflib import get_close_matches
from .paths import PROJECT_ROOT, CONFIG_DIR, DATA_DIR / "json", DATA_DIR, ASSETS_DIR
if "TCL_LIBRARY" not in os.environ or "TK_LIBRARY" not in os.environ:
    if getattr(sys, "frozen", False):
        base_tcl = os.path.join(getattr(sys, "_MEIPASS", ""), "tcl")
    else:
        base_tcl = os.path.join(sys.base_prefix, "tcl")
    tcl_dir = os.path.join(base_tcl, "tcl8.6")
    tk_dir = os.path.join(base_tcl, "tk8.6")
    if os.path.isdir(tcl_dir):
        os.environ.setdefault("TCL_LIBRARY", tcl_dir)
    if os.path.isdir(tk_dir):
        os.environ.setdefault("TK_LIBRARY", tk_dir)

import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, Dict, Optional

from audio_core import iniciar_loop_audio
from automacao_core import converter_para_ogg
from automacao_core import enviar_arquivo_whatsapp_webjs
from automacao_core import enviar_audio_whatsapp_webjs
from automacao_core import encerrar_servidor_whatsapp_webjs
from automacao_core import fechar_driver_whatsapp
from groq_core import GroqDualLLM
from ia_core import IALocal
from intent_router import executar_intencao, resolver_intencao_comando
from voice import ElevenLabsVoice, PiperVoice

from app.application.command_service import CommandService
from app.application.context_factory import build_intent_context
from app.application.services.file_memory_service import FileMemoryService
from app.interfaces.desktop_ui import DesktopUI
from app.state.session_state import SessionState

atexit.register(encerrar_servidor_whatsapp_webjs)
atexit.register(fechar_driver_whatsapp)

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

ALTAIR_VERSION = "1.0.0"

try:
    from app.interfaces.web_api import criar_api_app, iniciar_api_remota

    FASTAPI_DISPONIVEL = True
except Exception:
    FASTAPI_DISPONIVEL = False


MEMORIA_ARQUIVOS_FILE = str(DATA_DIR / "memoria_arquivos.json")
APP_CONFIG_FILE = str(DATA_DIR / "json" / "app_config.json")
state = SessionState()
file_memory_service = FileMemoryService(memory_file=MEMORIA_ARQUIVOS_FILE)


def carregar_memoria_arquivos():
    return file_memory_service.carregar_memoria_arquivos()


def salvar_memoria_arquivos(memoria):
    file_memory_service.salvar_memoria_arquivos(memoria)


def extrair_texto_arquivo(caminho_arquivo, limite_chars=14000):
    return file_memory_service.extrair_texto_arquivo(caminho_arquivo, limite_chars=limite_chars)


def resumir_texto_arquivo(nome_arquivo, texto, llm):
    return file_memory_service.resumir_texto_arquivo(nome_arquivo, texto, llm)


def analisar_e_memorizar_arquivo(caminho_arquivo, llm):
    return file_memory_service.analisar_e_memorizar_arquivo(caminho_arquivo, llm)


def _carregar_config_app() -> Dict[str, str]:
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _salvar_config_app(cfg: Dict[str, str]) -> None:
    pasta = os.path.dirname(APP_CONFIG_FILE)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


api_lock = threading.Lock()
command_service = None
ia = None
voz = None
ui = None
API_HOST = "127.0.0.1"
API_PORT = 8000


def _env_int(nome: str, padrao: int) -> int:
    valor = os.getenv(nome, str(padrao)).strip()
    try:
        return int(valor)
    except ValueError:
        return padrao


def _descobrir_ip_local() -> str:
    for ip in _descobrir_ips_locais():
        return ip
    return "127.0.0.1"


def _descobrir_ips_locais() -> tuple[str, ...]:
    ips = []
    vistos = set()

    def adicionar_ip(ip: str) -> None:
        if not ip or ip in vistos:
            return
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return
        if addr.version != 4 or addr.is_loopback:
            return
        vistos.add(ip)
        ips.append(ip)

    for alvo in (("8.8.8.8", 80), ("1.1.1.1", 80)):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(alvo)
            adicionar_ip(s.getsockname()[0])
        except Exception:
            pass
        finally:
            s.close()

    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            adicionar_ip(ip)
    except Exception:
        pass

    ips_privados = [ip for ip in ips if ipaddress.ip_address(ip).is_private]
    if ips_privados:
        return tuple(ips_privados)
    return tuple(ips)


def _resolver_host_api() -> str:
    host_env = os.getenv("ALTAIR_API_HOST", "").strip()
    if host_env:
        return host_env
    return "0.0.0.0"


def _resolver_host_qr() -> str:
    host_qr_env = os.getenv("ALTAIR_QR_HOST", "").strip()
    if host_qr_env:
        return host_qr_env
    return _descobrir_ip_local()


def _montar_url_conexao_remota() -> str:
    base_custom = os.getenv("ALTAIR_REMOTE_PUBLIC_URL", "").strip().rstrip("/")
    if base_custom:
        base = base_custom
    else:
        host_qr = API_HOST
        if API_HOST in ("0.0.0.0", "::", "127.0.0.1", "localhost", "::1"):
            host_qr = _resolver_host_qr()
        base = f"http://{host_qr}:{API_PORT}"

    return f"{base}/"


def _carregar_token_remoto() -> str:
    token_env = os.getenv("ALTAIR_REMOTE_TOKEN", "").strip()
    if token_env:
        return token_env

    token_file = os.getenv("ALTAIR_REMOTE_TOKEN_FILE", "remote_api_token.txt").strip()
    if token_file and os.path.exists(token_file):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""


def _startup_dir() -> str:
    appdata = os.getenv("APPDATA", "")
    if not appdata:
        return ""
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def _startup_cmd_path() -> str:
    pasta = _startup_dir()
    if not pasta:
        return ""
    return os.path.join(pasta, "AltairStartup.cmd")


def _startup_ativo() -> bool:
    caminho = _startup_cmd_path()
    return bool(caminho and os.path.exists(caminho))


def _habilitar_startup(exe_path: str) -> bool:
    pasta = _startup_dir()
    if not pasta:
        return False
    os.makedirs(pasta, exist_ok=True)
    cmd_path = _startup_cmd_path()
    conteudo = f'@echo off\nstart "" "{exe_path}"\n'
    try:
        with open(cmd_path, "w", encoding="utf-8") as f:
            f.write(conteudo)
        return True
    except Exception:
        return False


def _desabilitar_startup() -> bool:
    cmd_path = _startup_cmd_path()
    if not cmd_path or not os.path.exists(cmd_path):
        return True
    try:
        os.remove(cmd_path)
        return True
    except Exception:
        return False


def _alternar_startup_windows() -> Optional[bool]:
    if not getattr(sys, "frozen", False):
        messagebox.showwarning(
            "Indisponivel",
            "Esta opcao funciona apenas no executavel. Gere o Altair.exe e tente novamente.",
        )
        return None

    exe_path = sys.executable
    if not exe_path or not os.path.exists(exe_path):
        messagebox.showerror("Erro", "Nao consegui localizar o executavel atual.")
        return None

    if _startup_ativo():
        ok = _desabilitar_startup()
        if ok:
            messagebox.showinfo("Startup", "Inicializacao com Windows desativada.")
            return False
        messagebox.showerror("Erro", "Falha ao desativar a inicializacao.")
        return None

    ok = _habilitar_startup(exe_path)
    if ok:
        messagebox.showinfo("Startup", "Altair sera iniciado junto com o Windows.")
        return True
    messagebox.showerror("Erro", "Falha ao ativar a inicializacao.")
    return None


def abrir_interface_conexao_remota(app_root: tk.Tk) -> None:
    if not FASTAPI_DISPONIVEL:
        messagebox.showerror("Erro", "FastAPI/uvicorn nao encontrados. API remota desativada.")
        return

    try:
        import qrcode
        from PIL import ImageTk
    except Exception as e:
        messagebox.showerror(
            "Dependencia ausente",
            "Para gerar QR code, instale 'qrcode' e 'pillow'.\n"
            f"Detalhe: {e}",
        )
        return

    url = _montar_url_conexao_remota()

    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    photo = ImageTk.PhotoImage(img)

    win = tk.Toplevel(app_root)
    win.title("Conectar Remotamente")
    win.geometry("430x560")
    win.resizable(False, False)

    tk.Label(
        win,
        text="Escaneie o QR code para conectar no Altair remoto.",
        font=("Segoe UI", 11, "bold"),
        wraplength=390,
        justify="left",
    ).pack(padx=14, pady=(14, 8), anchor="w")

    token_remoto = _carregar_token_remoto()
    if token_remoto:
        aviso_token = "Token remoto ativo. Informe o token no app remoto."
    else:
        aviso_token = "A conexao remota esta sem token de autenticacao."

    tk.Label(
        win,
        text=aviso_token,
        font=("Segoe UI", 9),
        wraplength=390,
        justify="left",
    ).pack(padx=14, pady=(0, 10), anchor="w")

    qr_label = tk.Label(win, image=photo)
    qr_label.image = photo
    qr_label.pack(pady=4)

    entry_url = tk.Entry(win, width=58)
    entry_url.pack(padx=14, pady=(10, 6))
    entry_url.insert(0, url)
    entry_url.configure(state="readonly")

    def copiar_url():
        app_root.clipboard_clear()
        app_root.clipboard_append(url)
        messagebox.showinfo("Copiado", "URL remota copiada para a area de transferencia.")

    tk.Button(win, text="Copiar URL", command=copiar_url).pack(pady=(2, 8))

    aviso_host = (
        "Se nao abrir no celular, defina ALTAIR_QR_HOST com o IP do PC na rede Wi-Fi. "
        "Para acesso externo a sua rede, configure ALTAIR_REMOTE_PUBLIC_URL."
    )
    tk.Label(win, text=aviso_host, font=("Segoe UI", 9), wraplength=390, justify="left").pack(
        padx=14, pady=(2, 0), anchor="w"
    )


def montar_contexto_intencoes() -> Dict:
    return build_intent_context(
        state=state,
        analisar_e_memorizar_arquivo=analisar_e_memorizar_arquivo,
        ia_llm=ia.llm,
        carregar_memoria_arquivos=carregar_memoria_arquivos,
        enviar_arquivo_whatsapp_webjs=enviar_arquivo_whatsapp_webjs,
        voz=voz,
        converter_para_ogg=converter_para_ogg,
        enviar_audio_whatsapp_webjs=enviar_audio_whatsapp_webjs,
        base_dir=__file__,
    )


def processar_comando_altair(comando: str, falar: bool = False) -> Dict[str, str]:
    if command_service is None:
        return {"visual": "Servico de comando ainda nao inicializado.", "fala": ""}
    return command_service.execute(comando, falar=falar)


if FASTAPI_DISPONIVEL:
    API_HOST = _resolver_host_api()
    API_PORT = _env_int("ALTAIR_API_PORT", 8000)
    API_REMOTE_TOKEN = _carregar_token_remoto()
    api_app = criar_api_app(processar_comando_altair, api_lock, token=API_REMOTE_TOKEN)


wake_words = ["pode acordar", "altair", "alto ai", "assistente", "altai", "bom dia"]


def detectar_wake_word(texto: str) -> bool:
    palavras = texto.split()
    texto_unido = texto.replace(" ", "")
    candidatos = palavras + [texto_unido]

    for palavra in candidatos:
        for wake in wake_words:
            wake_sem_espaco = wake.replace(" ", "")
            parecido = get_close_matches(palavra, [wake, wake_sem_espaco], n=1, cutoff=0.6)
            if parecido:
                return True
    return False


def iniciar_audio() -> None:
    iniciar_loop_audio(
        ui.app,
        ia,
        voz,
        ui.adicionar_mensagem,
        ui.atualizar_botao_microfone,
        ui.trazer_para_frente,
    )


JSON_FILE = str(CONFIG_DIR / "apps.json")
LLM_CONFIG_FILE = str(DATA_DIR / "json" / "llm_provider_config.json")
VOICE_CONFIG_FILE = str(DATA_DIR / "json" / "voice_config.json")

PROVEDORES_LLM = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "local": "http://127.0.0.1:11434/v1/chat/completions",
}

if os.path.exists(JSON_FILE):
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        APLICATIVOS_CONHECIDOS = json.load(f)
else:
    APLICATIVOS_CONHECIDOS = {}


def salvar_apps() -> None:
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(APLICATIVOS_CONHECIDOS, f, indent=4, ensure_ascii=False)


def _carregar_api_key_groq_padrao() -> str:
    key_env = os.getenv("GROQ_API_KEY", "").strip()
    if key_env:
        return key_env

    key_file = os.getenv("GROQ_API_KEY_FILE", "groq_api_key.txt").strip()
    if key_file and os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""


def _config_llm_padrao() -> Dict[str, str]:
    return {
        "provider": "groq",
        "api_key": _carregar_api_key_groq_padrao(),
        "base_url": PROVEDORES_LLM["groq"],
        "model_main": os.getenv("ALTAIR_GROQ_LARGE_MODEL", "llama-3.3-70b-versatile"),
        "model_router": os.getenv("ALTAIR_GROQ_SMALL_MODEL", ""),
    }


def carregar_config_llm() -> Dict[str, str]:
    cfg = _config_llm_padrao()
    if os.path.exists(LLM_CONFIG_FILE):
        try:
            with open(LLM_CONFIG_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if isinstance(dados, dict):
                for k in ("provider", "api_key", "base_url", "model_main", "model_router"):
                    if k in dados and isinstance(dados[k], str):
                        cfg[k] = dados[k].strip()
        except Exception as e:
            print("Aviso: falha ao carregar configuracao de LLM:", e)

    prov = cfg.get("provider", "groq").strip().lower()
    if prov not in {"groq", "openai", "local", "custom"}:
        prov = "groq"
    cfg["provider"] = prov

    if prov != "custom":
        cfg["base_url"] = PROVEDORES_LLM[prov]

    if not cfg.get("model_main"):
        cfg["model_main"] = _config_llm_padrao()["model_main"]

    if not cfg.get("model_router"):
        cfg["model_router"] = cfg["model_main"]

    return cfg


def salvar_config_llm(cfg: Dict[str, str]) -> None:
    pasta = os.path.dirname(LLM_CONFIG_FILE)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(LLM_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def criar_llm_por_config(cfg: Dict[str, str]) -> GroqDualLLM:
    prov = (cfg.get("provider") or "groq").strip().lower()
    base_url = (cfg.get("base_url") or "").strip()
    if prov in PROVEDORES_LLM:
        base_url = PROVEDORES_LLM[prov]
    if not base_url:
        base_url = PROVEDORES_LLM["groq"]

    model_main = (cfg.get("model_main") or "").strip()
    model_router = (cfg.get("model_router") or "").strip() or model_main

    return GroqDualLLM(
        api_key=(cfg.get("api_key") or "").strip(),
        base_url=base_url,
        large_model=model_main,
        small_model=model_main,
        router_model=model_router,
        require_api_key=(prov != "local"),
    )


def aplicar_config_llm(cfg: Dict[str, str]) -> None:
    ia.llm = criar_llm_por_config(cfg)


def abrir_interface_llm_config(app_root: tk.Tk) -> None:
    cfg_atual = carregar_config_llm()

    win = tk.Toplevel(app_root)
    win.title("Configurar API e Modelos")
    win.geometry("560x400")
    win.resizable(False, False)

    tk.Label(win, text="Provedor").pack(anchor="w", padx=14, pady=(12, 2))
    prov_var = tk.StringVar(value=cfg_atual["provider"])
    prov_menu = tk.OptionMenu(win, prov_var, "groq", "openai", "local", "custom")
    prov_menu.config(width=18)
    prov_menu.pack(anchor="w", padx=14)

    tk.Label(win, text="API Key").pack(anchor="w", padx=14, pady=(10, 2))
    entry_key = tk.Entry(win, width=72, show="*")
    entry_key.insert(0, cfg_atual.get("api_key", ""))
    entry_key.pack(anchor="w", padx=14)

    tk.Label(win, text="Base URL (custom/local)").pack(anchor="w", padx=14, pady=(10, 2))
    entry_base = tk.Entry(win, width=72)
    entry_base.insert(0, cfg_atual.get("base_url", ""))
    entry_base.pack(anchor="w", padx=14)

    tk.Label(win, text="Modelo principal (respostas)").pack(anchor="w", padx=14, pady=(10, 2))
    entry_main = tk.Entry(win, width=72)
    entry_main.insert(0, cfg_atual.get("model_main", ""))
    entry_main.pack(anchor="w", padx=14)

    tk.Label(win, text="Modelo menor (interpretar comandos) - opcional").pack(anchor="w", padx=14, pady=(10, 2))
    entry_router = tk.Entry(win, width=72)
    entry_router.insert(0, cfg_atual.get("model_router", ""))
    entry_router.pack(anchor="w", padx=14)

    aviso = tk.Label(
        win,
        text="Se o modelo menor ficar vazio, o principal sera usado automaticamente.",
        fg="#6a6a6a",
    )
    aviso.pack(anchor="w", padx=14, pady=(8, 0))

    def atualizar_base_url(*_args):
        prov = prov_var.get().strip().lower()
        if prov in {"groq", "openai"}:
            entry_base.delete(0, tk.END)
            entry_base.insert(0, PROVEDORES_LLM[prov])
            entry_base.config(state="readonly")
        else:
            entry_base.config(state="normal")
            if prov == "local" and not entry_base.get().strip():
                entry_base.insert(0, PROVEDORES_LLM["local"])

    prov_var.trace_add("write", atualizar_base_url)
    atualizar_base_url()

    def salvar_llm():
        prov = prov_var.get().strip().lower()
        api_key = entry_key.get().strip()
        base_url = entry_base.get().strip()
        model_main = entry_main.get().strip()
        model_router = entry_router.get().strip()

        if prov not in {"groq", "openai", "local", "custom"}:
            messagebox.showerror("Erro", "Provedor invalido.")
            return
        if not model_main:
            messagebox.showerror("Erro", "Informe o modelo principal.")
            return
        if prov in {"custom", "local"} and not base_url:
            messagebox.showerror("Erro", "Informe a Base URL para provedor custom/local.")
            return
        if not model_router:
            model_router = model_main

        cfg_novo = {
            "provider": prov,
            "api_key": api_key,
            "base_url": base_url if prov in {"custom", "local"} else PROVEDORES_LLM[prov],
            "model_main": model_main,
            "model_router": model_router,
        }
        salvar_config_llm(cfg_novo)
        aplicar_config_llm(cfg_novo)
        if ui:
            ui.set_ia_status("IA: API/modelos atualizados")
            ui.app.after(1800, lambda: ui.set_ia_status("IA: Pronta"))
        messagebox.showinfo("Sucesso", "Configuracao aplicada com sucesso.")
        win.destroy()

    tk.Button(win, text="Salvar e aplicar", command=salvar_llm).pack(anchor="e", padx=14, pady=14)


def _config_voz_padrao() -> Dict[str, str]:
    base_dir = str(PROJECT_ROOT)
    return {
        "provider": "piper",
        "piper_model": str(ASSETS_DIR / "piper" / "voices" / "pt_BR-faber-medium.onnx"),
        "piper_length_scale": "1.08",
        "piper_noise_scale": "0.38",
        "piper_noise_w": "0.52",
        "piper_modo_pro": "1",
        "eleven_api_key": os.getenv("ELEVENLABS_API_KEY", "").strip(),
        "eleven_voice_id": os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
        "eleven_model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip(),
    }


def carregar_config_voz() -> Dict[str, str]:
    cfg = _config_voz_padrao()
    if os.path.exists(VOICE_CONFIG_FILE):
        try:
            with open(VOICE_CONFIG_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if isinstance(dados, dict):
                for k in cfg:
                    if k in dados and isinstance(dados[k], str):
                        cfg[k] = dados[k].strip()
        except Exception as e:
            print("Aviso: falha ao carregar configuracao de voz:", e)

    prov = cfg.get("provider", "piper").strip().lower()
    if prov not in {"piper", "elevenlabs"}:
        prov = "piper"
    cfg["provider"] = prov
    return cfg


def salvar_config_voz(cfg: Dict[str, str]) -> None:
    pasta = os.path.dirname(VOICE_CONFIG_FILE)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(VOICE_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def _to_float(valor: str, padrao: float) -> float:
    try:
        return float((valor or "").strip())
    except Exception:
        return float(padrao)


def criar_voz_por_config(cfg: Dict[str, str]):
    modelo = (cfg.get("piper_model") or "").strip() or _config_voz_padrao()["piper_model"]
    modo_pro = str(cfg.get("piper_modo_pro", "1")).strip().lower() in {"1", "true", "sim", "yes"}
    voz_piper = PiperVoice(
        modelo_path=modelo,
        modo_pro=modo_pro,
        length_scale=_to_float(cfg.get("piper_length_scale", "1.08"), 1.08),
        noise_scale=_to_float(cfg.get("piper_noise_scale", "0.38"), 0.38),
        noise_w=_to_float(cfg.get("piper_noise_w", "0.52"), 0.52),
    )

    prov = (cfg.get("provider") or "piper").strip().lower()
    if prov == "elevenlabs":
        return ElevenLabsVoice(
            api_key=(cfg.get("eleven_api_key") or "").strip(),
            voice_id=(cfg.get("eleven_voice_id") or "").strip(),
            model_id=(cfg.get("eleven_model_id") or "eleven_multilingual_v2").strip(),
            fallback_voice=voz_piper,
        )

    return voz_piper


def aplicar_config_voz(cfg: Dict[str, str]) -> None:
    global voz
    voz = criar_voz_por_config(cfg)
    ia.piper = voz
    if command_service:
        command_service.voz = voz
    if ui:
        ui.atualizar_callback_voz(voz.speak)


def abrir_interface_voz_config(app_root: tk.Tk) -> None:
    cfg_atual = carregar_config_voz()

    win = tk.Toplevel(app_root)
    win.title("Configurar Voz")
    win.geometry("620x520")
    win.resizable(False, False)

    tk.Label(win, text="Provedor de voz").pack(anchor="w", padx=14, pady=(12, 2))
    prov_var = tk.StringVar(value=cfg_atual["provider"])
    prov_menu = tk.OptionMenu(win, prov_var, "piper", "elevenlabs")
    prov_menu.config(width=18)
    prov_menu.pack(anchor="w", padx=14)

    tk.Label(win, text="Piper - Modelo ONNX").pack(anchor="w", padx=14, pady=(10, 2))
    piper_model = tk.Entry(win, width=80)
    piper_model.insert(0, cfg_atual.get("piper_model", ""))
    piper_model.pack(anchor="w", padx=14)

    def escolher_modelo_piper():
        caminho = filedialog.askopenfilename(title="Selecionar modelo Piper", filetypes=[("ONNX", "*.onnx")])
        if not caminho:
            return
        piper_model.delete(0, tk.END)
        piper_model.insert(0, caminho)

    tk.Button(win, text="Escolher modelo Piper", command=escolher_modelo_piper).pack(anchor="w", padx=14, pady=(6, 8))

    tk.Label(win, text="Piper - length_scale | noise_scale | noise_w | modo_pro(1/0)").pack(
        anchor="w", padx=14, pady=(4, 2)
    )
    frame_piper = tk.Frame(win)
    frame_piper.pack(anchor="w", padx=14)
    piper_len = tk.Entry(frame_piper, width=10)
    piper_len.insert(0, cfg_atual.get("piper_length_scale", "1.08"))
    piper_len.pack(side="left", padx=(0, 6))
    piper_noise = tk.Entry(frame_piper, width=10)
    piper_noise.insert(0, cfg_atual.get("piper_noise_scale", "0.38"))
    piper_noise.pack(side="left", padx=6)
    piper_noisew = tk.Entry(frame_piper, width=10)
    piper_noisew.insert(0, cfg_atual.get("piper_noise_w", "0.52"))
    piper_noisew.pack(side="left", padx=6)
    piper_modo = tk.Entry(frame_piper, width=10)
    piper_modo.insert(0, cfg_atual.get("piper_modo_pro", "1"))
    piper_modo.pack(side="left", padx=6)

    tk.Label(win, text="ElevenLabs - API Key").pack(anchor="w", padx=14, pady=(14, 2))
    eleven_key = tk.Entry(win, width=80, show="*")
    eleven_key.insert(0, cfg_atual.get("eleven_api_key", ""))
    eleven_key.pack(anchor="w", padx=14)

    tk.Label(win, text="ElevenLabs - Voice ID").pack(anchor="w", padx=14, pady=(10, 2))
    eleven_voice = tk.Entry(win, width=80)
    eleven_voice.insert(0, cfg_atual.get("eleven_voice_id", ""))
    eleven_voice.pack(anchor="w", padx=14)

    tk.Label(win, text="ElevenLabs - Model ID").pack(anchor="w", padx=14, pady=(10, 2))
    eleven_model = tk.Entry(win, width=80)
    eleven_model.insert(0, cfg_atual.get("eleven_model_id", "eleven_multilingual_v2"))
    eleven_model.pack(anchor="w", padx=14)

    aviso = tk.Label(
        win,
        text=(
            "Troca aplicada na hora. Para ElevenLabs, informe API Key e Voice ID. "
            "No plano gratuito, algumas library voices retornam paid_plan_required."
        ),
        fg="#6a6a6a",
    )
    aviso.pack(anchor="w", padx=14, pady=(10, 0))

    def salvar_voz():
        prov = prov_var.get().strip().lower()
        cfg_novo = {
            "provider": prov,
            "piper_model": piper_model.get().strip(),
            "piper_length_scale": piper_len.get().strip(),
            "piper_noise_scale": piper_noise.get().strip(),
            "piper_noise_w": piper_noisew.get().strip(),
            "piper_modo_pro": piper_modo.get().strip() or "1",
            "eleven_api_key": eleven_key.get().strip(),
            "eleven_voice_id": eleven_voice.get().strip(),
            "eleven_model_id": eleven_model.get().strip() or "eleven_multilingual_v2",
        }

        if prov not in {"piper", "elevenlabs"}:
            messagebox.showerror("Erro", "Provedor de voz invalido.")
            return
        if prov == "piper" and not cfg_novo["piper_model"]:
            messagebox.showerror("Erro", "Informe o modelo ONNX do Piper.")
            return
        if prov == "elevenlabs":
            if not cfg_novo["eleven_api_key"]:
                messagebox.showerror("Erro", "Informe a API Key do ElevenLabs.")
                return
            if not cfg_novo["eleven_voice_id"]:
                messagebox.showerror("Erro", "Informe o Voice ID do ElevenLabs.")
                return

        salvar_config_voz(cfg_novo)
        aplicar_config_voz(cfg_novo)
        if ui:
            ui.set_ia_status("IA: Voz atualizada")
            ui.app.after(1800, lambda: ui.set_ia_status("IA: Pronta"))
        messagebox.showinfo("Sucesso", "Configuracao de voz aplicada.")
        win.destroy()

    tk.Button(win, text="Salvar e aplicar", command=salvar_voz).pack(anchor="e", padx=14, pady=14)


def abrir_interface_cadastro(app_root: tk.Tk) -> None:
    cadastro_win = tk.Toplevel(app_root)
    cadastro_win.title("Cadastro de Aplicativos ALTAIR")
    cadastro_win.geometry("400x250")

    tk.Label(cadastro_win, text="Nome do aplicativo:").pack(pady=5)
    entry_nome = tk.Entry(cadastro_win, width=40)
    entry_nome.pack(pady=5)

    label_status = tk.Label(cadastro_win, text=f"{len(APLICATIVOS_CONHECIDOS)} apps cadastrados")
    label_status.pack(pady=5)

    def adicionar_app():
        caminho = filedialog.askopenfilename(
            title="Escolha o executavel do app", filetypes=[("Executaveis", "*.exe")]
        )
        if not caminho:
            return

        nome = entry_nome.get().strip().lower()
        if not nome:
            messagebox.showerror("Erro", "Digite um nome para o aplicativo")
            return

        APLICATIVOS_CONHECIDOS[nome] = caminho
        salvar_apps()
        messagebox.showinfo("Sucesso", f"Aplicativo '{nome}' adicionado!")
        entry_nome.delete(0, tk.END)
        label_status.config(text=f"{len(APLICATIVOS_CONHECIDOS)} apps cadastrados")

    tk.Button(cadastro_win, text="Escolher executavel e adicionar", command=adicionar_app).pack(
        pady=10
    )


def atualizar_arquivo_selecionado(caminho: str) -> None:
    state.arquivo_selecionado_envio = caminho


def processar_comando_ui(comando: str) -> Dict[str, str]:
    with api_lock:
        return processar_comando_altair(comando, falar=False)


BASE_DIR = str(PROJECT_ROOT)
cfg_voz_inicial = carregar_config_voz()
voz = criar_voz_por_config(cfg_voz_inicial)
cfg_llm_inicial = carregar_config_llm()
llm_groq = criar_llm_por_config(cfg_llm_inicial)
if not llm_groq.disponivel():
    print("AVISO: API key nao configurada. O fallback local continuara ativo.")

ia = IALocal(voz, llm_groq)
command_service = CommandService(
    ia=ia,
    voz=voz,
    resolver_intencao_comando=resolver_intencao_comando,
    executar_intencao=executar_intencao,
    montar_contexto_intencoes=montar_contexto_intencoes,
)

ui = DesktopUI(
    process_command=processar_comando_ui,
    speak_text=voz.speak,
    on_audio_start=iniciar_audio,
    on_file_selected=atualizar_arquivo_selecionado,
    app_title=f"A.L.T.A.I.R v{ALTAIR_VERSION}",
    on_toggle_startup=_alternar_startup_windows,
    on_open_apps_register=abrir_interface_cadastro,
    on_open_remote_connect=abrir_interface_conexao_remota,
    on_open_llm_config=abrir_interface_llm_config,
    on_open_voice_config=abrir_interface_voz_config,
)

if FASTAPI_DISPONIVEL:
    threading.Thread(
        target=iniciar_api_remota,
        args=(api_app,),
        kwargs={"host": API_HOST, "port": API_PORT},
        daemon=True,
    ).start()
    ips_locais = _descobrir_ips_locais()
    ip_local = _descobrir_ip_local()
    url_qr = _montar_url_conexao_remota()
    token_status = "token ativo" if API_REMOTE_TOKEN else "sem token"
    print(f"API remota iniciada em http://{API_HOST}:{API_PORT} ({token_status})")
    print(f"Acesso na rede local: http://{ip_local}:{API_PORT}")
    print(f"URL para QR/celular: {url_qr}")
    if ips_locais:
        print("IPs locais detectados:", ", ".join(ips_locais))
else:
    print("FastAPI/uvicorn nao encontrados. API remota desativada.")

welcome_text = ia.responder("saudacao")
ui.adicionar_mensagem(welcome_text, "ia")
voz.speak(welcome_text)

ui.run()
