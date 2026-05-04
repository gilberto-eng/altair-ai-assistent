import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from difflib import get_close_matches

import numpy as np
import sounddevice as sd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))
DEFAULT_MODEL_DIR = os.path.join(PROJECT_ROOT, "data", "models", "whisper-base")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", DEFAULT_MODEL_DIR).strip()
if os.path.isdir(WHISPER_MODEL):
    model_id = WHISPER_MODEL
else:
    model_id = WHISPER_MODEL or "base"

_whisper_probe_done = False
_whisper_probe_ok = False
_whisper_disabled = False

# ==============================
# OUVIR MICROFONE
# ==============================

driver = None
_audio_loop_lock = threading.Lock()
_audio_loop_thread = None
_audio_stop_event = threading.Event()
_wake_enabled = True


def set_wake_enabled(enabled: bool) -> None:
    """Habilita/desabilita o reconhecimento por wake word dentro do loop de audio."""
    global _wake_enabled
    _wake_enabled = bool(enabled)


def wake_enabled() -> bool:
    return bool(_wake_enabled)


def parar_loop_audio() -> bool:
    """Solicita parada do loop de audio (escuta continua)."""
    _audio_stop_event.set()
    with _audio_loop_lock:
        th = _audio_loop_thread
    return bool(th and th.is_alive())


def _run_whisper_subprocess(script: str, audio_path: str | None = None, timeout_s: int = 90) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-c", script]
    if audio_path:
        cmd.extend([audio_path, model_id])
    else:
        cmd.append(model_id)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)


def _probe_whisper_runtime() -> bool:
    global _whisper_probe_done, _whisper_probe_ok
    if _whisper_probe_done:
        return _whisper_probe_ok

    _whisper_probe_done = True
    script = (
        "import sys; "
        "from faster_whisper import WhisperModel; "
        "WhisperModel(sys.argv[1], compute_type='int8'); "
        "print('ok')"
    )

    try:
        probe = _run_whisper_subprocess(script, timeout_s=60)
    except Exception as exc:
        print(f"AVISO: probe do Whisper falhou ({exc}). Desativando entrada de voz.")
        _whisper_probe_ok = False
        return False

    if probe.returncode != 0:
        saida = (probe.stderr or probe.stdout or "").strip()
        if saida:
            print(f"AVISO: Whisper indisponivel neste ambiente: {saida}")
        else:
            print("AVISO: Whisper indisponivel neste ambiente (falha nativa).")
        _whisper_probe_ok = False
        return False

    _whisper_probe_ok = True
    return True


def _transcrever_audio_subprocess(audio_data: np.ndarray) -> str:
    global _whisper_disabled

    if _whisper_disabled:
        return ""

    if not _probe_whisper_runtime():
        _whisper_disabled = True
        return ""

    # Roda a transcricao em subprocesso para evitar que falhas nativas do faster_whisper
    # derrubem o processo principal da UI.
    script = (
        "import sys; "
        "import numpy as np; "
        "from faster_whisper import WhisperModel; "
        "audio = np.load(sys.argv[1]); "
        "model = WhisperModel(sys.argv[2], compute_type='int8'); "
        "segments, _ = model.transcribe(audio, language='pt', beam_size=1, temperature=0.0, condition_on_previous_text=False); "
        "print(' '.join(seg.text for seg in segments).strip())"
    )

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as tmp:
            tmp_path = tmp.name
        np.save(tmp_path, audio_data.astype(np.float32, copy=False))

        proc = _run_whisper_subprocess(script, audio_path=tmp_path, timeout_s=120)
        if proc.returncode != 0:
            saida = (proc.stderr or proc.stdout or "").strip()
            if saida:
                print(f"AVISO: falha ao transcrever com Whisper: {saida}")
            else:
                print("AVISO: falha nativa ao transcrever com Whisper. Entrada de voz desativada.")
            _whisper_disabled = True
            return ""

        return (proc.stdout or "").strip()
    except Exception as exc:
        print(f"AVISO: erro ao executar transcricao em subprocesso ({exc}).")
        _whisper_disabled = True
        return ""
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def ouvir_microfone(on_listen_level=None):
    print("Aguardando fala...")

    if _whisper_disabled:
        time.sleep(0.5)
        return ""

    samplerate = 16000
    threshold = float(os.getenv("ALTAIR_MIC_THRESHOLD", "0.003"))
    silence_limit = 1.5
    max_duration = 10

    audio_chunks = []
    silence_start = None
    speaking = False

    def callback(indata, frames, time_info, status):
        nonlocal silence_start, speaking, audio_chunks

        # RMS real do frame (evita subestimar o volume por divisao excessiva).
        volume = float(np.sqrt(np.mean(np.square(indata))))

        if on_listen_level:
            try:
                on_listen_level(volume)
            except Exception:
                pass

        if volume > threshold:
            speaking = True
            silence_start = None
            audio_chunks.append(indata.copy())

        elif speaking:
            audio_chunks.append(indata.copy())

            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start > silence_limit:
                raise sd.CallbackStop()

    try:
        with sd.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            inicio = time.time()
            while True:
                time.sleep(0.1)
                if time.time() - inicio > max_duration:
                    break
    except Exception:
        pass

    if not audio_chunks:
        return ""

    audio_data = np.concatenate(audio_chunks, axis=0).flatten()
    texto = _transcrever_audio_subprocess(audio_data)
    if texto:
        print("TEXTO CAPTADO:", texto)
    return texto


# ==============================
# WAKE WORD
# ==============================

wake_words = ["pode acordar", "altair", "assistente", "altai"]


def detectar_wake_word(texto):
    palavras = texto.split()
    texto_unido = texto.replace(" ", "")
    candidatos = palavras + [texto_unido]

    for palavra in candidatos:
        for wake in wake_words:
            wake_sem_espaco = wake.replace(" ", "")
            parecido = get_close_matches(
                palavra,
                [wake, wake_sem_espaco],
                n=1,
                cutoff=0.6,
            )
            if parecido:
                return True
    return False


# ==============================
# LOOP PRINCIPAL DE AUDIO
# ==============================


def iniciar_loop_audio(
    app,
    ia,
    voz,
    adicionar_mensagem,
    atualizar_botao,
    trazer_para_frente,
    on_speak_start=None,
    on_speak_end=None,
    on_listen_level=None,
):
    global _audio_loop_thread

    with _audio_loop_lock:
        if _audio_loop_thread is not None and _audio_loop_thread.is_alive():
            print("Loop de audio ja esta ativo. Ignorando novo inicio.")
            return False

    _audio_stop_event.clear()

    if _whisper_disabled or not _probe_whisper_runtime():
        print("Entrada de voz desativada neste ambiente.")
        return False

    escutando = True

    def loop():
        global _audio_loop_thread
        try:
            print("Modo espera ativado")
            atualizar_botao(True)

            ativo = False
            ultimo_comando = 0
            tempo_timeout = 30

            def falar_altair(texto: str) -> None:
                if not texto:
                    return
                try:
                    if on_speak_start:
                        on_speak_start()
                    voz.speak(texto)
                finally:
                    if on_speak_end:
                        on_speak_end()

            while escutando and (not _audio_stop_event.is_set()):
                texto = ouvir_microfone(on_listen_level=on_listen_level)
                if not texto:
                    continue

                # Quando desabilitado pelo usuario, ignora tudo (inclusive wake word).
                if not _wake_enabled:
                    ativo = False
                    continue

                if detectar_wake_word(texto):
                    trazer_para_frente()
                    falar_altair("Sim senhor.")
                    ativo = True
                    ultimo_comando = time.time()
                    continue

                if ativo:
                    agora = time.time()

                    if agora - ultimo_comando > tempo_timeout:
                        ativo = False
                        continue

                    ultimo_comando = agora

                    adicionar_mensagem(texto, "usuario")
                    resposta = ia.perguntar(texto)

                    if isinstance(resposta, dict):
                        resposta_visual = str(resposta.get("visual", "")).strip()
                        resposta_fala = str(resposta.get("fala", "")).strip()
                    else:
                        resposta_visual = str(resposta).strip()
                        resposta_fala = resposta_visual

                    if resposta_visual:
                        adicionar_mensagem(resposta_visual, "ia")
                    if resposta_fala:
                        falar_altair(resposta_fala)
        except Exception as exc:
            print(f"ERRO no loop de audio: {exc}")
            traceback.print_exc()
        finally:
            try:
                atualizar_botao(False)
            except Exception:
                pass
            with _audio_loop_lock:
                _audio_loop_thread = None

    thread = threading.Thread(target=loop, daemon=True, name="altair-audio-loop")
    with _audio_loop_lock:
        _audio_loop_thread = thread
    thread.start()
    return True

