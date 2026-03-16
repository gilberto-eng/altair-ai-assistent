import webbrowser
import subprocess
import shutil
import urllib.parse
import re
import sys
import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager 
import undetected_chromedriver as uc
import urllib.parse, webbrowser
from selenium.webdriver.common.by import By
from voice import ElevenLabsVoice, PiperVoice
import time
import json 
import requests
import os
import json
import uuid
import subprocess
import threading
import unicodedata
import socket
from difflib import get_close_matches


driver = None
wwebjs_process = None
wwebjs_log_path = ""
wwebjs_log_handle = None


def _runtime_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parents[3])


BASE_DIR = _runtime_base_dir()
VOICE_CONFIG_FILE = os.path.join(BASE_DIR, 'configs', 'json', 'voice_config.json')
CHROME_PROFILE_DIR = os.getenv("ALTAIR_CHROME_PROFILE_DIR", os.path.join(BASE_DIR, "data", "chrome_profile"))
WWEBJS_DIR = os.getenv("ALTAIR_WWEBJS_DIR", os.path.join(BASE_DIR, "scripts", "whatsapp"))


def _porta_aberta(host, porta, timeout=0.3):
    try:
        with socket.create_connection((host, porta), timeout=timeout):
            return True
    except Exception:
        return False


def _to_float(valor, padrao):
    try:
        return float(str(valor).strip())
    except Exception:
        return float(padrao)


def _carregar_config_voz():
    base_dir = BASE_DIR
    cfg = {
        "provider": "piper",
        "piper_model": os.path.join(base_dir, "assets", "piper", "voices", "pt_BR-faber-medium.onnx"),
        "piper_length_scale": "1.08",
        "piper_noise_scale": "0.38",
        "piper_noise_w": "0.52",
        "piper_modo_pro": "1",
        "eleven_api_key": os.getenv("ELEVENLABS_API_KEY", "").strip(),
        "eleven_voice_id": os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
        "eleven_model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip(),
    }
    if os.path.exists(VOICE_CONFIG_FILE):
        try:
            with open(VOICE_CONFIG_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if isinstance(dados, dict):
                for k in cfg:
                    if k in dados and isinstance(dados[k], str):
                        cfg[k] = dados[k].strip()
        except Exception:
            pass
    return cfg


def _obter_voz_para_audio():
    cfg = _carregar_config_voz()
    modelo = (cfg.get("piper_model") or "").strip()
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


def _pids_escutando_porta(porta):
    try:
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return []

    pids = set()
    alvo = f":{porta}"
    for linha in (proc.stdout or "").splitlines():
        if "LISTENING" not in linha.upper():
            continue
        if alvo not in linha:
            continue
        partes = linha.split()
        if not partes:
            continue
        pid_txt = partes[-1].strip()
        if pid_txt.isdigit():
            pids.add(int(pid_txt))
    return sorted(pids)


def _encerrar_processos_porta(porta):
    for pid in _pids_escutando_porta(porta):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception:
            pass


def garantir_servidor_whatsapp_webjs(force_restart=False):
    global wwebjs_process, wwebjs_log_path, wwebjs_log_handle

    js_path = os.path.join(WWEBJS_DIR, 'teste.js')
    if not os.path.exists(js_path):
        return False, f'Arquivo teste.js nao encontrado em: {js_path}'

    global wwebjs_process

    if force_restart:
        try:
            if wwebjs_process and wwebjs_process.poll() is None:
                wwebjs_process.terminate()
                try:
                    wwebjs_process.wait(timeout=5)
                except Exception:
                    wwebjs_process.kill()
        except Exception:
            pass
        wwebjs_process = None
        if wwebjs_log_handle:
            try:
                wwebjs_log_handle.close()
            except Exception:
                pass
            wwebjs_log_handle = None
        _encerrar_processos_porta(3000)
        time.sleep(1.0)

    if _porta_aberta("127.0.0.1", 3000) and not force_restart:
        return True, "Servidor WhatsApp ja esta ativo."

    node_bin = os.getenv("ALTAIR_NODE_PATH", "node").strip()
    if not shutil.which(node_bin):
        return False, "Node.js nao encontrado. Defina ALTAIR_NODE_PATH ou instale o Node."

    base_dir = WWEBJS_DIR
    create_flags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        create_flags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                create_flags |= subprocess.CREATE_NO_WINDOW

        logs_dir = os.path.join(BASE_DIR, "data", "wwebjs_logs")
        os.makedirs(logs_dir, exist_ok=True)
        wwebjs_log_path = os.path.join(
            logs_dir, f"teste_js_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        wwebjs_log_handle = open(wwebjs_log_path, "w", encoding="utf-8")

        env = os.environ.copy()
        env.setdefault("WWEBJS_HEADLESS", "")  # auto: visivel se nao houver sessao
        env.setdefault("PUPPETEER_DISABLE_HEADLESS_WARNING", "1")

        wwebjs_process = subprocess.Popen(
            [node_bin, js_path],
            cwd=base_dir,
            creationflags=create_flags,
            startupinfo=startupinfo,
            stdout=wwebjs_log_handle,
            stderr=wwebjs_log_handle,
            env=env
        )
    except Exception as e:
        return False, f"Nao foi possivel iniciar teste.js: {e}"

    # Aguarda o servidor subir (primeira vez pode levar mais tempo por login/sessao)
    for _ in range(60):
        if _porta_aberta("127.0.0.1", 3000):
            return True, "Servidor WhatsApp iniciado."
        if wwebjs_process and wwebjs_process.poll() is not None:
            return False, f"teste.js encerrou com codigo {wwebjs_process.poll()}. Log: {wwebjs_log_path}"
        time.sleep(1)

    return False, f"Servidor WhatsApp nao ficou pronto a tempo. Log: {wwebjs_log_path}"


def reiniciar_servidor_whatsapp_webjs():
    return garantir_servidor_whatsapp_webjs(force_restart=True)


def encerrar_servidor_whatsapp_webjs():
    global wwebjs_process, wwebjs_log_handle, wwebjs_log_path
    try:
        if wwebjs_process and wwebjs_process.poll() is None:
            wwebjs_process.terminate()
            try:
                wwebjs_process.wait(timeout=5)
            except Exception:
                wwebjs_process.kill()
    except Exception:
        pass

    wwebjs_process = None
    if wwebjs_log_handle:
        try:
            wwebjs_log_handle.close()
        except Exception:
            pass
        wwebjs_log_handle = None

    _encerrar_processos_porta(3000)
    wwebjs_log_path = ""


def _usar_fallback_selenium():
    return str(os.getenv("ALTAIR_WHATSAPP_FALLBACK_SELENIUM", "0")).strip().lower() in {"1", "true", "sim", "yes"}


def _erro_reiniciavel_whatsapp(texto):
    msg = str(texto or "").lower()
    return any(
        trecho in msg
        for trecho in [
            "detached frame",
            "execution context was destroyed",
            "cannot find context with specified id",
            "target closed",
            "erro interno",
        ]
    )

def iniciar_whatsapp():
    global driver

    if driver is not None:
        return driver

    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")

    # ðŸ”¥ remove automaÃ§Ã£o visÃ­vel
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = uc.Chrome(options=options)

    driver.get("https://web.whatsapp.com")

    print("Aguardando login no WhatsApp Web...")

    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.ID, "pane-side"))
    )

    print("WhatsApp pronto.")

    return driver


def enviar_whatsapp(nome_contato, mensagem):
    global driver

    # Para texto, tenta primeiro via whatsapp-web.js (teste.js).
    if not os.path.exists(mensagem):
        sucesso, retorno = enviar_mensagem_whatsapp_webjs(nome_contato, mensagem)
        if sucesso:
            return retorno
        if not _usar_fallback_selenium():
            return f"Falha no envio via WhatsApp Web: {retorno}"
        print("DEBUG: envio via teste.js falhou, tentando fallback Selenium...", retorno)

    try:
        driver = iniciar_whatsapp()
        wait = WebDriverWait(driver, 60)

        print("DEBUG: aguardando WhatsApp carregar...")

        wait.until(EC.presence_of_element_located((By.ID, "pane-side")))

        # ==========================
        # ðŸ”Ž Procurar contato
        # ==========================
        print("DEBUG: procurando contato...")

        caixa_pesquisa = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true"][@role="textbox"]')
            )
        )

        caixa_pesquisa.click()
        time.sleep(1)
        caixa_pesquisa.clear()
        caixa_pesquisa.send_keys(nome_contato)
        time.sleep(2)
        caixa_pesquisa.send_keys(Keys.ENTER)

        print("DEBUG: contato selecionado")

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "footer")))

        time.sleep(2)

        # ==========================
        # ðŸ“Ž SE FOR ARQUIVO
        # ==========================
        if os.path.exists(mensagem):

            print("DEBUG: focando campo mensagem")

            campo_mensagem = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, '//footer//div[@contenteditable="true"]')
                )
            )

            campo_mensagem.click()
            time.sleep(1)

            print("DEBUG: clicando no clip")

            driver.execute_script("""
                var clips = document.querySelectorAll('[data-icon="clip"]');
                if (clips.length > 0) clips[0].click();
            """)

            time.sleep(2)

            print("DEBUG: aguardando input file")

            input_arquivo = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, '//input[@type="file"]')
                )
            )

            input_arquivo.send_keys(os.path.abspath(mensagem))

            print("DEBUG: arquivo carregado, aguardando botÃ£o verde...")

            time.sleep(5)  # importante para tela cheia carregar

            # ==========================
            # ðŸš€ CLIQUE DEFINITIVO
            # ==========================

            print("DEBUG: procurando botÃ£o verde por posiÃ§Ã£o")

            clicou = driver.execute_script("""
                let buttons = document.querySelectorAll('button, div[role="button"]');

                for (let i = buttons.length - 1; i >= 0; i--) {
                    let b = buttons[i];

                    let rect = b.getBoundingClientRect();

                    // botÃ£o grande no canto inferior direito
                    if (rect.width > 40 && rect.height > 40 &&
                        rect.right > window.innerWidth - 200 &&
                        rect.bottom > window.innerHeight - 200) {

                        b.click();
                        return true;
                    }
                }

                return false;
            """)

            if not clicou:
                raise Exception("BotÃ£o verde nÃ£o encontrado.")

            print("DEBUG: envio executado")

            time.sleep(3)

            return "MÃ­dia enviada com sucesso."

        # ==========================
        # ðŸ“ TEXTO NORMAL
        # ==========================
        else:

            print("DEBUG: enviando texto")

            campo_mensagem = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, '//footer//div[@contenteditable="true"]')
                )
            )

            campo_mensagem.click()
            campo_mensagem.send_keys(mensagem)
            campo_mensagem.send_keys(Keys.ENTER)

            return "Mensagem enviada com sucesso."

    except Exception as e:
        print("ERRO DETALHADO:", e)
        return f"Erro ao enviar mensagem: {e}"


def enviar_mensagem_whatsapp_webjs(nome_contato, mensagem):
    ok, detalhe = garantir_servidor_whatsapp_webjs()
    if not ok:
        return False, detalhe

    for tentativa in range(2):
        try:
            resposta = requests.post(
                "http://localhost:3000/enviar-mensagem",
                json={
                    "nome": nome_contato,
                    "mensagem": mensagem
                },
                timeout=30
            )
        except Exception as e:
            if tentativa == 0:
                ok_restart, detalhe_restart = reiniciar_servidor_whatsapp_webjs()
                if ok_restart:
                    continue
                return False, f"Erro ao conectar no servico WhatsApp (porta 3000)? {e}. Reinicio falhou: {detalhe_restart}"
            return False, f"Erro ao conectar no servico WhatsApp (porta 3000)? {e}"

        if resposta.status_code == 200:
            return True, f"Mensagem enviada para {nome_contato} com sucesso."

        try:
            erro = resposta.json()
        except Exception:
            erro = {"erro": resposta.text}
        detalhe = str(erro.get("erro", resposta.text))

        if tentativa == 0 and _erro_reiniciavel_whatsapp(detalhe):
            ok_restart, _ = reiniciar_servidor_whatsapp_webjs()
            if ok_restart:
                continue

        return False, f"Falha no envio via teste.js: {detalhe}"

    return False, "Falha no envio via teste.js apos tentativa de reinicio."


def enviar_arquivo_whatsapp_webjs(nome_contato, caminho_arquivo, legenda=""):
    ok, detalhe = garantir_servidor_whatsapp_webjs()
    if not ok:
        return f"Falha ao iniciar servidor WhatsApp: {detalhe}"

    caminho_absoluto = os.path.abspath(caminho_arquivo)

    if not os.path.exists(caminho_absoluto):
        return f"Arquivo nao encontrado: {caminho_absoluto}"

    for tentativa in range(2):
        try:
            resposta = requests.post(
                "http://localhost:3000/enviar-arquivo",
                json={
                    "nome": nome_contato,
                    "caminhoArquivo": caminho_absoluto,
                    "legenda": legenda or ""
                },
                timeout=60
            )
        except Exception as e:
            if tentativa == 0:
                ok_restart, detalhe_restart = reiniciar_servidor_whatsapp_webjs()
                if ok_restart:
                    continue
                return f"Erro ao conectar no servico WhatsApp (porta 3000)? {e}. Reinicio falhou: {detalhe_restart}"
            return f"Erro ao conectar no servico WhatsApp (porta 3000)? {e}"

        if resposta.status_code == 200:
            return f"Arquivo enviado para {nome_contato} com sucesso."

        try:
            erro = resposta.json()
        except Exception:
            erro = {"erro": resposta.text}
        detalhe = str(erro.get("erro", resposta.text))

        if tentativa == 0 and _erro_reiniciavel_whatsapp(detalhe):
            ok_restart, _ = reiniciar_servidor_whatsapp_webjs()
            if ok_restart:
                continue

        return f"Falha ao enviar arquivo: {detalhe}"

    return "Falha ao enviar arquivo apos tentativa de reinicio."


def enviar_audio_whatsapp_webjs(nome_contato, caminho_audio):
    ok, detalhe = garantir_servidor_whatsapp_webjs()
    if not ok:
        return False, f"Falha ao iniciar servidor WhatsApp: {detalhe}"

    caminho_absoluto = os.path.abspath(caminho_audio)
    if not os.path.exists(caminho_absoluto):
        return False, f"Arquivo de audio nao encontrado: {caminho_absoluto}"

    for tentativa in range(2):
        try:
            resposta = requests.post(
                "http://localhost:3000/enviar-audio",
                json={
                    "nome": nome_contato,
                    "caminhoAudio": caminho_absoluto
                },
                timeout=40
            )
        except Exception as e:
            if tentativa == 0:
                ok_restart, detalhe_restart = reiniciar_servidor_whatsapp_webjs()
                if ok_restart:
                    continue
                return False, f"Erro ao conectar no servico WhatsApp (porta 3000)? {e}. Reinicio falhou: {detalhe_restart}"
            return False, f"Erro ao conectar no servico WhatsApp (porta 3000)? {e}"

        if resposta.status_code == 200:
            return True, f"Audio enviado para {nome_contato}"

        try:
            erro = resposta.json()
        except Exception:
            erro = {"erro": resposta.text}
        detalhe = str(erro.get("erro", resposta.text))

        if tentativa == 0 and _erro_reiniciavel_whatsapp(detalhe):
            ok_restart, _ = reiniciar_servidor_whatsapp_webjs()
            if ok_restart:
                continue

        return False, f"Falha ao enviar audio: {detalhe}"

    return False, "Falha ao enviar audio apos tentativa de reinicio."

        
# ==============================
# SITES CONHECIDOS
# ==============================
SITES_CONHECIDOS = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://www.github.com",
    "gmail": "https://mail.google.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "whatsapp": "https://web.whatsapp.com",
    "stackoverflow": "https://stackoverflow.com",
    "universo narrado" : "https://aluno.universonarrado.com.br/login",
    "chat gpt" : "https://chatgpt.com/c/699b7f50-8f10-8327-8265-55fa42a3bc94"
}

ARTIGOS = ["o ", "a ", "os ", "as "]

APLICATIVOS_PADRAO = {
    "calculadora": "calc",
    "bloco de notas": "notepad",
    "notepad": "notepad",
    "explorador": "explorer",
    "cmd": "cmd",
    "prompt de comando": "cmd",
    "powershell": "powershell",
    "calculador" : "calc",
    "spotify" : "Spotify"
}

# ==============================
# UTILIDADES
# ==============================

def limpar_nome(nome):
    nome = nome.strip().lower()

    for artigo in ARTIGOS:
        if nome.startswith(artigo):
            nome = nome[len(artigo):]

    return nome.strip()


# ==============================
# ABRIR APLICATIVO
# ==============================


# Carregar apps do JSON
JSON_FILE = os.path.join(BASE_DIR, "configs", "apps.json")
APLICATIVOS_CONHECIDOS = dict(APLICATIVOS_PADRAO)
if os.path.exists(JSON_FILE):
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        try:
            apps_json = json.load(f)
            if isinstance(apps_json, dict):
                APLICATIVOS_CONHECIDOS.update(apps_json)
        except Exception:
            pass

_CACHE_APPS_DESCOBERTOS = {}
_CACHE_APPS_ATUALIZADO_EM = 0
_CACHE_APPS_TTL = 600


def _normalizar_chave_app(texto):
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", str(texto))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9\s\-_]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _executar_app(alvo):
    if not alvo:
        return False, "Alvo vazio."
    try:
        if os.path.exists(alvo):
            os.startfile(alvo)
            return True, ""
        subprocess.Popen(alvo, shell=True)
        return True, ""
    except Exception as e:
        return False, str(e)


def _caminhos_de_busca_apps():
    caminhos = []
    for env in ["ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"]:
        base = os.environ.get(env)
        if base and os.path.isdir(base):
            caminhos.append(base)
            if env == "LOCALAPPDATA":
                sub = os.path.join(base, "Programs")
                if os.path.isdir(sub):
                    caminhos.append(sub)
    return caminhos


def _indexar_start_menu():
    resultado = {}
    pastas = [
        os.path.join(os.environ.get("ProgramData", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
    ]
    for pasta in pastas:
        if not pasta or not os.path.isdir(pasta):
            continue
        for raiz, _, arquivos in os.walk(pasta):
            for arq in arquivos:
                if not arq.lower().endswith(".lnk"):
                    continue
                nome_lnk = os.path.splitext(arq)[0]
                chave = _normalizar_chave_app(nome_lnk)
                if chave and chave not in resultado:
                    resultado[chave] = os.path.join(raiz, arq)
    return resultado


def _indexar_executaveis(max_por_pasta=120):
    resultado = {}
    for base in _caminhos_de_busca_apps():
        encontrados = 0
        for raiz, _, arquivos in os.walk(base):
            for arq in arquivos:
                if not arq.lower().endswith(".exe"):
                    continue
                nome_exe = os.path.splitext(arq)[0]
                chave = _normalizar_chave_app(nome_exe)
                if chave and chave not in resultado:
                    resultado[chave] = os.path.join(raiz, arq)
                encontrados += 1
                if encontrados >= max_por_pasta:
                    break
            if encontrados >= max_por_pasta:
                break
    return resultado


def _reconstruir_cache_apps():
    global _CACHE_APPS_DESCOBERTOS, _CACHE_APPS_ATUALIZADO_EM
    agora = time.time()
    if _CACHE_APPS_DESCOBERTOS and (agora - _CACHE_APPS_ATUALIZADO_EM) < _CACHE_APPS_TTL:
        return _CACHE_APPS_DESCOBERTOS

    index = {}
    for nome_app, alvo in APLICATIVOS_CONHECIDOS.items():
        chave = _normalizar_chave_app(nome_app)
        if chave:
            index[chave] = alvo

    index.update(_indexar_start_menu())
    deep_scan = str(os.getenv("ALTAIR_APPS_DEEP_SCAN", "0")).strip().lower() in {"1", "true", "sim", "yes"}
    if deep_scan:
        index.update(_indexar_executaveis())

    _CACHE_APPS_DESCOBERTOS = index
    _CACHE_APPS_ATUALIZADO_EM = agora
    return _CACHE_APPS_DESCOBERTOS


def _buscar_alvo_app(nome):
    consulta = _normalizar_chave_app(nome)
    if not consulta:
        return None, None

    caminho = shutil.which(consulta) or shutil.which(f"{consulta}.exe")
    if caminho:
        return consulta, caminho

    index = _reconstruir_cache_apps()
    if consulta in index:
        return consulta, index[consulta]

    candidatos = []
    for chave, alvo in index.items():
        if consulta in chave or chave in consulta:
            score = min(len(consulta), len(chave)) / max(len(consulta), len(chave))
            candidatos.append((score, chave, alvo))
    if candidatos:
        candidatos.sort(key=lambda x: x[0], reverse=True)
        _, chave, alvo = candidatos[0]
        return chave, alvo

    aproximados = get_close_matches(consulta, list(index.keys()), n=1, cutoff=0.72)
    if aproximados:
        chave = aproximados[0]
        return chave, index[chave]

    return None, None


def abrir_aplicativo(nome):
    nome = (nome or "").strip()
    app_nome, alvo = _buscar_alvo_app(nome)
    if not alvo:
        return None

    # Caso nÃ£o encontre, tenta pelo sistema
    ok, erro = _executar_app(alvo)
    if not ok:
        return f"Erro ao abrir {app_nome or nome}: {erro}"
    return f"Abrindo {app_nome or nome}"

# ==============================
# ABRIR COMO SITE
# ==============================
def abrir_como_site(nome):

    # 1ï¸âƒ£ Site conhecido
    if nome in SITES_CONHECIDOS:
        webbrowser.open(SITES_CONHECIDOS[nome])
        return f"Abrindo {nome}"

    # 2ï¸âƒ£ Se parece domÃ­nio
    if "." in nome:
        if not nome.startswith("http"):
            nome = "https://" + nome
        webbrowser.open(nome)
        return f"Abrindo {nome}"

    # 3ï¸âƒ£ Tenta .com automÃ¡tico
    if re.match(r"^[a-zA-Z0-9\-]+$", nome):
        tentativa = f"https://www.{nome}.com"
        webbrowser.open(tentativa)
        return f"Tentando abrir {nome}.com"

    return None


# ==============================
# PESQUISA GOOGLE
# ==============================
def pesquisar_google(termo):
    url = "https://www.google.com/search?q=" + urllib.parse.quote(termo)
    webbrowser.open(url)
    return f"Pesquisando por {termo}"


def _extrair_termo_pesquisa(comando_original: str) -> str:
    texto = (comando_original or "").strip()
    if not texto:
        return ""
    padrao = re.search(
        r"^(?:pesquisar|pesquise|pesquisa|busque|buscar|procure|procurar|pesquisando)(?:\s+(?:por|sobre))?\s+(.+)$",
        texto,
        flags=re.IGNORECASE,
    )
    if padrao:
        termo = (padrao.group(1) or "").strip()
        if termo:
            return termo
    return texto


def pesquisar_youtube(termo):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(termo)
    webbrowser.open(url)
    return f"Abrindo YouTube e pesquisando por {termo}"


def _resolver_pasta_comum(texto):
    txt = normalizar_texto(texto or "")
    home = os.path.expanduser("~")
    if "download" in txt:
        return os.path.join(home, "Downloads")
    if "documento" in txt:
        return os.path.join(home, "Documents")
    if "desktop" in txt or "area de trabalho" in txt:
        return os.path.join(home, "Desktop")
    return None


def _limpar_texto_pasta(texto):
    pasta = (texto or "").strip().strip('"').strip("'")
    pasta = re.sub(r"[.!,;:]+$", "", pasta).strip()
    pasta = re.sub(r"^(?:a|o|na|no|da|do)\s+", "", pasta, flags=re.IGNORECASE)
    pasta = re.sub(r"^(?:pasta|diretorio)\s+(?:de\s+)?", "", pasta, flags=re.IGNORECASE)
    return pasta.strip()


def _resolver_caminho_pasta(texto_pasta):
    pasta = _limpar_texto_pasta(texto_pasta)
    if not pasta:
        return None

    pasta_expandida = os.path.expandvars(os.path.expanduser(pasta))
    if os.path.isabs(pasta_expandida) and os.path.isdir(pasta_expandida):
        return os.path.abspath(pasta_expandida)

    pasta_comum = _resolver_pasta_comum(pasta)
    if pasta_comum and os.path.isdir(pasta_comum):
        return os.path.abspath(pasta_comum)

    userprofile = os.environ.get("USERPROFILE", "")
    home = os.path.expanduser("~")
    onedrive = os.environ.get("OneDrive", "")
    bases = [b for b in [home, userprofile, onedrive] if b and os.path.isdir(b)]

    relativo = pasta_expandida.strip().strip("\\/")
    if relativo:
        for base in bases:
            candidato = os.path.abspath(os.path.join(base, relativo))
            if os.path.isdir(candidato):
                return candidato

    if "\\" not in relativo and "/" not in relativo:
        alvo_norm = normalizar_texto(relativo).replace(" ", "")
        for base in bases:
            try:
                for nome in os.listdir(base):
                    caminho = os.path.join(base, nome)
                    if not os.path.isdir(caminho):
                        continue
                    nome_norm = normalizar_texto(nome).replace(" ", "")
                    if nome_norm == alvo_norm:
                        return os.path.abspath(caminho)
            except Exception:
                continue

    return None


def organizar_pasta_arquivos(caminho_pasta):
    pasta = _limpar_texto_pasta(caminho_pasta)
    if not pasta:
        return "Informe a pasta para organizar."

    pasta_resolvida = _resolver_caminho_pasta(pasta)
    if not pasta_resolvida:
        return (
            f"Pasta nao encontrada: {pasta}. "
            "Informe o caminho completo (ex.: C:\\Users\\SeuUsuario\\Downloads)."
        )
    pasta = pasta_resolvida

    movidos = 0
    ignorados = 0
    for nome in os.listdir(pasta):
        origem = os.path.join(pasta, nome)
        if not os.path.isfile(origem):
            ignorados += 1
            continue

        ext = os.path.splitext(nome)[1].lower().lstrip(".")
        destino_dir = os.path.join(pasta, ext if ext else "sem_extensao")
        os.makedirs(destino_dir, exist_ok=True)

        base, ext_nome = os.path.splitext(nome)
        destino = os.path.join(destino_dir, nome)
        idx = 1
        while os.path.exists(destino):
            destino = os.path.join(destino_dir, f"{base}_{idx}{ext_nome}")
            idx += 1

        try:
            shutil.move(origem, destino)
            movidos += 1
        except Exception:
            ignorados += 1

    try:
        os.startfile(pasta)
    except Exception:
        pass

    return f"Pasta organizada: {movidos} arquivos movidos, {ignorados} itemns ignorados."


# ==============================
# EXTRAÃ‡ÃƒO INTELIGENTE
# ==============================
def extrair_objeto(comando, palavras_chave):
    for palavra in palavras_chave:
        match = re.search(rf"{palavra}\s+(.*)", comando)
        if match:
            return limpar_nome(match.group(1))
    return None


def converter_para_ogg(wav_path):
    try:
        import subprocess
        import os

        if not os.path.exists(wav_path):
            print("WAV nÃ£o existe.")
            return None

        ogg_path = wav_path.replace(".wav", ".ogg")

        comando = [
            "ffmpeg",
            "-y",
            "-i", wav_path,
            "-c:a", "libopus",
            ogg_path
        ]

        print("Executando:", " ".join(comando))

        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True
        )

        if resultado.returncode != 0:
            print("âŒ ERRO REAL DO FFMPEG:")
            print(resultado.stderr)
            return None

        if not os.path.exists(ogg_path):
            print("OGG nÃ£o foi criado.")
            return None

        print("OGG criado com sucesso:", ogg_path)
        return ogg_path

    except Exception as e:
        print("Erro na conversÃ£o:", e)
        return None
    
def normalizar_texto(texto):
    if not isinstance(texto, str):
        return texto
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.lower()



def deletar_arquivo(caminho):
    try:
        if caminho and os.path.exists(caminho):
            os.remove(caminho)
            print(f"Arquivo removido: {caminho}")
    except Exception as e:
        print(f"Erro ao remover arquivo {caminho}: {e}")



def processar_automacao(comando, llm=None):
    comando_original = comando
    comando = comando.lower().strip()


    comando_original = comando
    comando = comando.lower().strip()

    # Pasta correta para os audios temporarios
    PASTA_AUDIOS = os.path.join(BASE_DIR, "data", "audios_temp")
    os.makedirs(PASTA_AUDIOS, exist_ok=True)

    # Comandos compostos diretos
    match_youtube = re.search(
        r"(?:abra|abrir|abre).{0,30}youtube.{0,20}e\s+(?:busque|pesquise|procure)\s+(?:por\s+)?(.+)$",
        comando_original,
        flags=re.IGNORECASE,
    )
    if match_youtube:
        termo = (match_youtube.group(1) or "").strip()
        if termo:
            return pesquisar_youtube(termo)

    match_org = re.search(
        r"(?:abra|abrir|abre).{0,20}(?:explorer|explorador|explorer\.exe).{0,20}e\s+organize(?:r)?\s+(?:a\s+)?(?:tal\s+)?pasta(?:\s+de\s+arquivos?)?\s+(.+)$",
        comando_original,
        flags=re.IGNORECASE,
    )
    if match_org:
        abrir_aplicativo("explorer")
        pasta = (match_org.group(1) or "").strip()
        return organizar_pasta_arquivos(pasta)

    # ==========================================================
    # FUNCOES AUXILIARES
    # ==========================================================

    def deletar_arquivo(caminho):
        try:
            if caminho and os.path.exists(caminho):
                os.remove(caminho)
                print("Arquivo removido:", caminho)
        except Exception as e:
            print("Erro ao remover arquivo:", e)

    def gerar_audio_e_enviar(contato, mensagem):
        wav_path = None
        ogg_path = None

        try:
            nome_unico = str(uuid.uuid4())

            # Salva dentro de audios_temp
            wav_path = os.path.join(PASTA_AUDIOS, f"{nome_unico}.wav")

            voz_envio = _obter_voz_para_audio()
            wav_path = voz_envio.save_to_file(mensagem, wav_path)
            if not wav_path or not os.path.exists(wav_path):
                print("Falha ao gerar WAV")
                return None

            ogg_path = converter_para_ogg(wav_path)
            if not ogg_path or not os.path.exists(ogg_path):
                print("Falha ao gerar OGG")
                return None

            ok_audio, retorno_audio = enviar_audio_whatsapp_webjs(contato, ogg_path)
            if not ok_audio:
                print("Falha no envio de audio via teste.js:", retorno_audio)
                return f"Falha ao enviar audio: {retorno_audio}"

            print(f"Audio enviado para {contato}")
            return retorno_audio

        except Exception as e:
            print("Erro no pipeline de audio:", e)
            return None
        finally:
            deletar_arquivo(wav_path)
            deletar_arquivo(ogg_path)

    def normalizar_texto(txt):
        if not isinstance(txt, str):
            return ""
        return (
            txt.lower()
            .replace("?", "c")
            .replace("?", "a")
            .replace("?", "a")
            .replace("?", "a")
            .replace("?", "e")
            .replace("?", "e")
            .replace("?", "i")
            .replace("?", "o")
            .replace("?", "o")
            .replace("?", "u")
            .replace("?", "o")
            .strip()
        )

    def classificar_intencao(cmd):
        cmd = cmd.lower()

        if "arquivo" in cmd and "para" in cmd:
            return "enviar_arquivo"

        if "audio" in cmd or "?udio" in cmd:
            return "enviar_audio"

        if "mensagem" in cmd or "manda" in cmd:
            if "para" in cmd:
                return "enviar_mensagem"

        if any(p in cmd for p in ["abrir", "abre"]):
            return "abrir_app"

        if any(p in cmd for p in ["pesquise", "busque", "procure", "buscar"]):
            return "pesquisar_web"

        return None

    def extrair_contato(cmd):
        match = re.search(
            r"(?:para|pro|pra|no\s+grupo|no\s+contato)\s+(.+?)\s+(dizendo|explicando|falando|sobre)",
            cmd.lower(),
        )
        return match.group(1) if match else None

    def extrair_mensagem(cmd):
        padroes = [
            r"dizendo\s+(.+)",
            r"explicando\s+(.+)",
            r"falando\s+(.+)",
            r"sobre\s+(.+)",
            r"que diga\s+(.+)",
        ]

        for padrao in padroes:
            match = re.search(padrao, cmd.lower())
            if match:
                return match.group(1).strip()

        return None

    def extrair_dados_arquivo(cmd):
        cmd = cmd.strip()
        padrao = re.search(
            r"(?:enviar|manda(?:r)?)\s+arquivo\s+para\s+(.+?)\s+(?:caminho|arquivo)\s+(.+?)(?:\s+legenda\s+(.+))?$",
            cmd,
            flags=re.IGNORECASE,
        )
        if not padrao:
            return None, None, ""

        contato = padrao.group(1).strip()
        caminho = padrao.group(2).strip().strip('"').strip("'")
        legenda = (padrao.group(3) or "").strip()
        return contato, caminho, legenda

    # ==========================================================
    # CLASSIFICADOR LEVE
    # ==========================================================

    intencao = classificar_intencao(comando_original)

    if intencao == "enviar_audio":
        if "explicando sobre" in comando_original.lower():
            return None

        contato = extrair_contato(comando_original)
        mensagem = extrair_mensagem(comando_original)

        if contato and mensagem:
            return gerar_audio_e_enviar(contato, mensagem)

    if intencao == "enviar_mensagem":
        contato = extrair_contato(comando_original)
        mensagem = extrair_mensagem(comando_original)

        if contato and mensagem:
            return enviar_whatsapp(contato, mensagem)

    if intencao == "abrir_app":
        nome = comando_original.replace("abrir", "").replace("abre", "").strip()
        if nome:
            resposta = abrir_aplicativo(nome)
            if resposta:
                return resposta
            return abrir_como_site(nome)

    if intencao == "pesquisar_web":
        termo = _extrair_termo_pesquisa(comando_original)
        termo_codificado = urllib.parse.quote(termo)
        webbrowser.open(f"https://www.google.com/search?q={termo_codificado}")
        return f"Pesquisando {termo}"

    padrao_organizar = re.search(
        r"(?:organize|organizar)\s+(?:a\s+)?(?:tal\s+)?pasta(?:\s+de\s+arquivos?)?\s+(.+)$",
        comando_original,
        flags=re.IGNORECASE,
    )
    if padrao_organizar:
        pasta = (padrao_organizar.group(1) or "").strip()
        if pasta:
            return organizar_pasta_arquivos(pasta)

    # ==========================================================
    # Fallback por LLM (modelo menor escolhe ferramenta)
    # ==========================================================
    seletor_automacao = getattr(llm, "escolher_automacao", None) if llm else None
    if callable(seletor_automacao):
        try:
            plano = seletor_automacao(comando_original) or {}
            acao_llm = str(plano.get("acao", "nenhuma")).strip().lower()
            confianca = float(plano.get("confianca", 0.0) or 0.0)
            print("DEBUG automacao llm:", plano)
        except Exception as e:
            print("DEBUG: erro no seletor de automacao LLM:", e)
            return None

        if confianca < 0.6 or acao_llm == "nenhuma":
            return None

        if acao_llm == "abrir_app":
            app = str(plano.get("app", "")).strip()
            if app:
                resposta = abrir_aplicativo(app)
                if resposta:
                    return resposta
                return abrir_como_site(app)
            return None

        if acao_llm == "pesquisar_web":
            termo = str(plano.get("termo", "")).strip() or _extrair_termo_pesquisa(comando_original)
            termo_codificado = urllib.parse.quote(termo)
            webbrowser.open(f"https://www.google.com/search?q={termo_codificado}")
            return f"Pesquisando {termo}"

        if acao_llm == "enviar_mensagem":
            contato = str(plano.get("contato", "")).strip()
            mensagem = str(plano.get("mensagem", "")).strip()
            if contato and mensagem:
                return enviar_whatsapp(contato, mensagem)
            return None

        if acao_llm == "enviar_audio":
            contato = str(plano.get("contato", "")).strip()
            mensagem = str(plano.get("mensagem", "")).strip()
            if contato and mensagem:
                return gerar_audio_e_enviar(contato, mensagem)
            return None

    return None

def fechar_driver_whatsapp():
    global driver
    try:
        if driver:
            driver.quit()
    except Exception:
        pass
    driver = None
