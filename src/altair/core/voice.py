import os
import uuid
import subprocess
import pygame
import time
import re
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..', '..', '..'))


class PiperVoice:
    def __init__(
        self,
        modelo_path,
        piper_path=None,
        length_scale=1.45,
        noise_scale=0.45,
        noise_w=0.6,
        modo_pro=True
    ):

        if not pygame.mixer.get_init():
            pygame.mixer.init()

        self.modelo = modelo_path
        self.piper_path = piper_path or os.path.join(PROJECT_ROOT, "assets", "piper", "piper.exe")
        self.length_scale = str(length_scale)
        self.noise_scale = str(noise_scale)
        self.noise_w = str(noise_w)
        self.modo_pro = modo_pro

    # ==========================================================
    # 🔊 FALAR DIRETAMENTE
    # ==========================================================

    def _normalizar_texto_fala(self, texto):
        txt = str(texto or "")
        txt = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", txt)
        txt = re.sub(r"[#*_`~|<>]", " ", txt)
        txt = re.sub(r"[{}\[\]\\\\]", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt

    def speak(self, texto):
        texto_limpo = self._normalizar_texto_fala(texto)
        if not texto_limpo:
            return

        nome_original = f"voz_{uuid.uuid4().hex}.wav"
        nome_final = f"voz_pro_{uuid.uuid4().hex}.wav"

        try:
            comando = [
                self.piper_path,
                "--model", self.modelo,
                "--output_file", nome_original,
                "--length_scale", self.length_scale,
                "--noise_scale", self.noise_scale,
                "--noise_w", self.noise_w
            ]

            processo = subprocess.Popen(
                comando,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            processo.communicate(texto_limpo)

            if not os.path.exists(nome_original):
                print("❌ Piper não gerou o áudio.")
                return

            if self.modo_pro:
                # Perfil "assistente premium": grave mais presente, menos sibilancia e dinamica controlada.
                filtro_audio = (
                    "highpass=f=55,"
                    "lowpass=f=7600,"
                    "equalizer=f=120:width_type=o:width=1.8:g=2.5,"
                    "equalizer=f=3200:width_type=o:width=1.2:g=-2.0,"
                    "acompressor=threshold=-20dB:ratio=2.8:attack=20:release=180,"
                    "alimiter=limit=0.92"
                )

                efeito = [
                    "ffmpeg",
                    "-y",
                    "-i", nome_original,
                    "-af", filtro_audio,
                    nome_final
                ]

                resultado = subprocess.call(
                    efeito,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                if resultado == 0 and os.path.exists(nome_final):
                    os.remove(nome_original)
                    audio_para_tocar = nome_final
                else:
                    print("⚠ FFmpeg falhou. Tocando original.")
                    audio_para_tocar = nome_original
            else:
                audio_para_tocar = nome_original

            pygame.mixer.music.load(audio_para_tocar)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                time.sleep(0.1)

            pygame.mixer.music.unload()

        except Exception as e:
            print("Erro na síntese de voz:", e)

        finally:
            if os.path.exists(nome_original):
                os.remove(nome_original)

            if os.path.exists(nome_final):
                os.remove(nome_final)

    # ==========================================================
    # 💾 SALVAR EM ARQUIVO (USADO PELO WHATSAPP)
    # ==========================================================

    def save_to_file(self, texto, caminho_arquivo):

        try:
            print("ARQUIVO DA CLASSE:", __file__)
            print("DEBUG SAVE: modelo =", self.modelo)
            print("DEBUG SAVE: piper =", self.piper_path)

            caminho_arquivo = os.path.abspath(caminho_arquivo)

            pasta = os.path.dirname(caminho_arquivo)
            if pasta and not os.path.exists(pasta):
                os.makedirs(pasta, exist_ok=True)

            comando = [
                self.piper_path,
                "--model", self.modelo,
                "--output_file", caminho_arquivo,
                "--length_scale", self.length_scale,
                "--noise_scale", self.noise_scale,
                "--noise_w", self.noise_w
                
            ]
            processo = subprocess.Popen(
            comando,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
            )

           
            texto_limpo = self._normalizar_texto_fala(texto)
            if not texto_limpo:
                return None

            processo.communicate(texto_limpo)

           
            

            if not os.path.exists(caminho_arquivo):
                print("❌ WAV não foi criado.")
                return None

            print("✅ Áudio salvo em:", caminho_arquivo)
            return caminho_arquivo

        except subprocess.CalledProcessError as e:
            print("Erro no Piper:")
            print(e.stderr.decode(errors="ignore"))
            return None

        except Exception as e:
            print("Erro ao salvar áudio:", e)
            return None


# ==========================================================
# 🎤 INSTÂNCIA GLOBAL
# ==========================================================

class ElevenLabsVoice:
    def __init__(
        self,
        api_key,
        voice_id,
        model_id="eleven_multilingual_v2",
        stability=0.4,
        similarity_boost=0.75,
        style=0.2,
        use_speaker_boost=True,
        fallback_voice=None,
    ):
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        self.api_key = (api_key or "").strip()
        self.voice_id = (voice_id or "").strip()
        self.model_id = model_id
        self.stability = float(stability)
        self.similarity_boost = float(similarity_boost)
        self.style = float(style)
        self.use_speaker_boost = bool(use_speaker_boost)
        self.fallback_voice = fallback_voice

    def _normalizar_texto_fala(self, texto):
        txt = str(texto or "")
        txt = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", txt)
        txt = re.sub(r"[#*_`~|<>]", " ", txt)
        txt = re.sub(r"[{}\[\]\\\\]", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt

    def _sintetizar_mp3(self, texto):
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY nao configurada.")
        if not self.voice_id:
            raise RuntimeError("ELEVENLABS_VOICE_ID nao configurado.")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": texto,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
                "style": self.style,
                "use_speaker_boost": self.use_speaker_boost,
            },
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        if resp.status_code >= 400:
            detalhe = (resp.text or "").strip()[:400]
            if resp.status_code == 402 and "paid_plan_required" in detalhe:
                raise RuntimeError(
                    "ElevenLabs bloqueou esta voz para plano gratuito "
                    "(paid_plan_required / library voice)."
                )
            raise RuntimeError(f"Erro ElevenLabs HTTP {resp.status_code}: {detalhe}")
        return resp.content

    def speak(self, texto):
        texto_limpo = self._normalizar_texto_fala(texto)
        if not texto_limpo:
            return

        nome_mp3 = f"voz_eleven_{uuid.uuid4().hex}.mp3"
        try:
            audio_bin = self._sintetizar_mp3(texto_limpo)
            with open(nome_mp3, "wb") as f:
                f.write(audio_bin)

            pygame.mixer.music.load(nome_mp3)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            pygame.mixer.music.unload()
        except Exception as e:
            print("Erro na sintese ElevenLabs:", e)
            if self.fallback_voice:
                print("Fallback de voz: usando Piper para esta resposta.")
                try:
                    self.fallback_voice.speak(texto_limpo)
                except Exception as fb_err:
                    print("Erro no fallback Piper:", fb_err)
        finally:
            if os.path.exists(nome_mp3):
                os.remove(nome_mp3)

    def save_to_file(self, texto, caminho_arquivo):
        texto_limpo = self._normalizar_texto_fala(texto)
        if not texto_limpo:
            return None

        try:
            caminho_arquivo = os.path.abspath(caminho_arquivo)
            pasta = os.path.dirname(caminho_arquivo)
            if pasta and not os.path.exists(pasta):
                os.makedirs(pasta, exist_ok=True)

            audio_bin = self._sintetizar_mp3(texto_limpo)

            if caminho_arquivo.lower().endswith(".mp3"):
                with open(caminho_arquivo, "wb") as f:
                    f.write(audio_bin)
                return caminho_arquivo

            temp_mp3 = f"{os.path.splitext(caminho_arquivo)[0]}_{uuid.uuid4().hex}.mp3"
            with open(temp_mp3, "wb") as f:
                f.write(audio_bin)

            cmd = ["ffmpeg", "-y", "-i", temp_mp3, caminho_arquivo]
            ret = subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ret != 0 or not os.path.exists(caminho_arquivo):
                print("Erro ElevenLabs: falha ao converter audio para o formato de saida.")
                return None
            return caminho_arquivo
        except Exception as e:
            print("Erro ao salvar audio ElevenLabs:", e)
            if self.fallback_voice:
                print("Fallback de voz: gerando audio com Piper.")
                try:
                    return self.fallback_voice.save_to_file(texto_limpo, caminho_arquivo)
                except Exception as fb_err:
                    print("Erro no fallback Piper (save_to_file):", fb_err)
            return None
        finally:
            try:
                if "temp_mp3" in locals() and os.path.exists(temp_mp3):
                    os.remove(temp_mp3)
            except Exception:
                pass


voice = PiperVoice(
    modelo_path=os.path.join(
        BASE_DIR,
        "piper",
        "voices",
        "pt_BR-faber-medium.onnx"
    )
)
