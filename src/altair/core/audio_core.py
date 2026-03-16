import time
import math
import queue
import threading
import os
import numpy as np
import sounddevice as sd
from difflib import get_close_matches
from faster_whisper import WhisperModel
# ==============================
# CONFIG WHISPER
# ==============================

print("Carregando modelo Whisper...")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))
DEFAULT_MODEL_DIR = os.path.join(PROJECT_ROOT, "data", "models", "whisper-base")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", DEFAULT_MODEL_DIR).strip()
if os.path.isdir(WHISPER_MODEL):
    model_id = WHISPER_MODEL
else:
    model_id = WHISPER_MODEL or "base"

whisper_model = WhisperModel(model_id, compute_type="int8")

# ==============================
# OUVIR MICROFONE
# ==============================

driver = None


def ouvir_microfone():
    print("🎤 Aguardando fala...")

    samplerate = 16000
    threshold = 0.005
    silence_limit = 1.5
    max_duration = 10

    audio_chunks = []
    silence_start = None
    speaking = False

    def callback(indata, frames, time_info, status):
        nonlocal silence_start, speaking, audio_chunks

        volume = np.linalg.norm(indata) / len(indata)

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
            callback=callback
        ):
            inicio = time.time()
            while True:
                time.sleep(0.1)
                if time.time() - inicio > max_duration:
                    break
    except:
        pass

    if not audio_chunks:
        return ""

    audio_data = np.concatenate(audio_chunks, axis=0)

    segments, _ = whisper_model.transcribe(
        audio_data.flatten(),
        language="pt",
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False
    )

    texto = " ".join([seg.text for seg in segments])
    print("TEXTO CAPTADO:", texto.strip())
    return texto.strip()

# ==============================
# WAKE WORD
# ==============================

wake_words = ["pode acordar", "altair", "assistente", "altaí"]

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
                cutoff=0.6
            )
            if parecido:
                return True
    return False

# ==============================
# LOOP PRINCIPAL DE ÁUDIO
# ==============================

def iniciar_loop_audio(app, ia, voz, adicionar_mensagem, atualizar_botao, trazer_para_frente):

    escutando = True

    def loop():
        print("🟣 Modo espera ativado")
        atualizar_botao(True)

        ativo = False
        ultimo_comando = 0
        TEMPO_TIMEOUT = 30

        while escutando:

            texto = ouvir_microfone()
            if not texto:
                continue

            if detectar_wake_word(texto):
                trazer_para_frente()
                voz.speak("Sim senhor.")
                ativo = True
                ultimo_comando = time.time()
                continue

            if ativo:
                agora = time.time()

                if agora - ultimo_comando > TEMPO_TIMEOUT:
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
                    voz.speak(resposta_fala)

        atualizar_botao(False)

    threading.Thread(target=loop, daemon=True).start()
