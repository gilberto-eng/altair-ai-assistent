import datetime
import math
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog
from typing import Callable, Dict, Optional, Any
import shutil

try:
    from PIL import Image, ImageTk
except Exception:  # pillow opcional; seguimos sem preview se nao houver
    Image = None
    ImageTk = None

import customtkinter as ctk
import psutil


class DesktopUI:
    def __init__(
        self,
        process_command: Callable[..., Dict[str, str]],
        speak_text: Callable[[str], None],
        on_audio_start: Callable[[], None],
        on_file_selected: Callable[[str], None],
        app_title: str = "A.L.T.A.I.R",
        on_toggle_startup: Optional[Callable[[], Optional[bool]]] = None,
        on_open_apps_register: Optional[Callable[[ctk.CTk], None]] = None,
        on_open_remote_connect: Optional[Callable[[ctk.CTk], None]] = None,
        on_open_llm_config: Optional[Callable[[ctk.CTk], None]] = None,
        on_open_voice_config: Optional[Callable[[ctk.CTk], None]] = None,
    ) -> None:
        self._process_command = process_command
        self._speak_text = speak_text
        self._on_audio_start = on_audio_start
        self._on_file_selected = on_file_selected
        self._on_toggle_startup = on_toggle_startup
        self._on_open_apps_register = on_open_apps_register
        self._on_open_remote_connect = on_open_remote_connect
        self._on_open_llm_config = on_open_llm_config
        self._on_open_voice_config = on_open_voice_config
        self._menu_aberto = False
        self._menu_frame = None

        self._digitando_label = None
        self._typing_animating = False
        self._tri_ext = None
        self._tri_int = None
        self._hud_text = None

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.app = ctk.CTk()
        # Variáveis tkinter precisam de um master já criado
        self._falar_var = ctk.BooleanVar(master=self.app, value=True)
        # tenta maximizar; se não suportado, ajusta para tamanho da tela
        def _maximize():
            try:
                self.app.state("zoomed")
            except Exception:
                w, h = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
                self.app.geometry(f"{w}x{h}+0+0")
        self.app.after(50, _maximize)
        self.app.title(app_title)
        self.app.grid_columnconfigure(0, weight=1)
        self.app.grid_columnconfigure(1, weight=2)
        self.app.grid_columnconfigure(2, weight=1)
        self.app.grid_rowconfigure(0, weight=1)

        self._criar_coluna_esquerda()
        self._criar_hud_central()
        self._criar_chat_direita()
        self._criar_menu_superior()

        self._atualizar_status()
        self._animar_hud()

    def _criar_coluna_esquerda(self) -> None:
        left_frame = ctk.CTkFrame(self.app, corner_radius=15, fg_color="#1a1a1f")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)

        self.cpu_bar = ctk.CTkProgressBar(left_frame, width=200, height=20)
        self.cpu_bar.pack(pady=5)
        self.cpu_label = ctk.CTkLabel(left_frame, text="CPU: 0%")
        self.cpu_label.pack(pady=2)
        self.ram_bar = ctk.CTkProgressBar(left_frame, width=200, height=20)
        self.ram_bar.pack(pady=5)
        self.ram_label = ctk.CTkLabel(left_frame, text="RAM: 0%")
        self.ram_label.pack(pady=2)
        self.mic_status_label = ctk.CTkLabel(left_frame, text="MICROFONE: Inativo")
        self.mic_status_label.pack(pady=10)
        self.ia_status_label = ctk.CTkLabel(left_frame, text="IA: Pronta")
        self.ia_status_label.pack(pady=10)
        self.hora_label = ctk.CTkLabel(left_frame, text="")
        self.hora_label.pack(pady=10)

    def _criar_hud_central(self) -> None:
        center_frame = ctk.CTkFrame(self.app, corner_radius=15, fg_color="#0b0b0f")
        center_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)

        self.canvas = tk.Canvas(center_frame, bg="#0b0b0f", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._criar_logo)

    def _criar_chat_direita(self) -> None:
        right_frame = ctk.CTkFrame(self.app, corner_radius=20, fg_color="#0e0e12")
        right_frame.grid(row=0, column=2, sticky="nsew", padx=15, pady=15)
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        self.chat_area = ctk.CTkScrollableFrame(
            right_frame,
            corner_radius=15,
            fg_color="#14141a",
        )
        self.chat_area.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        bottom_bar = ctk.CTkFrame(
            right_frame,
            corner_radius=25,
            fg_color="#1a1a22",
            height=60,
        )
        bottom_bar.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        bottom_bar.grid_columnconfigure(1, weight=1)

        btn_anexar = ctk.CTkButton(
            bottom_bar,
            text="+",
            width=45,
            height=45,
            corner_radius=25,
            fg_color="#3a3a46",
            hover_color="#50505f",
            command=self._selecionar_arquivo_envio,
        )
        btn_anexar.grid(row=0, column=0, padx=(10, 5), pady=7)

        self.entry = ctk.CTkEntry(
            bottom_bar,
            placeholder_text="Digite uma mensagem...",
            corner_radius=25,
            height=45,
            fg_color="#2a2a35",
            border_color="#7b2ff7",
            text_color="white",
        )
        self.entry.grid(row=0, column=1, padx=(5, 5), pady=7, sticky="ew")
        self.entry.bind("<Return>", lambda _event: self._enviar())

        btn_send = ctk.CTkButton(
            bottom_bar,
            text="\u27a4",
            width=45,
            height=45,
            corner_radius=25,
            fg_color="#7b2ff7",
            hover_color="#9d4edd",
            command=self._enviar,
        )
        btn_send.grid(row=0, column=2, padx=5, pady=7)

        self.btn_voz = ctk.CTkButton(
            bottom_bar,
            text="\U0001f3a4",
            width=45,
            height=45,
            corner_radius=25,
            fg_color="#5a189a",
            hover_color="#7b2ff7",
            command=self._on_audio_start,
        )
        self.btn_voz.grid(row=0, column=3, padx=(5, 10), pady=7)

        self.chk_falar = ctk.CTkCheckBox(
            bottom_bar,
            text="Falar resposta",
            variable=self._falar_var,
            onvalue=True,
            offvalue=False,
            fg_color="#5a189a",
            hover_color="#7b2ff7",
            text_color="white",
        )
        self.chk_falar.grid(row=0, column=4, padx=(0, 12), pady=7)

        self.label_arquivo = ctk.CTkLabel(
            bottom_bar,
            text="Arquivo: nenhum",
            text_color="#b7b7c6",
            font=("Segoe UI", 11),
        )
        self.label_arquivo.grid(row=1, column=0, columnspan=5, sticky="w", padx=14, pady=(0, 6))

    def _criar_menu_superior(self) -> None:
        self.btn_menu = ctk.CTkButton(
            self.app,
            text="Menu",
            width=70,
            height=34,
            corner_radius=10,
            fg_color="#252533",
            hover_color="#3b3b4f",
            command=self._alternar_menu_superior,
        )
        self.btn_menu.place(x=14, y=14)
        self.btn_menu.lift()

        self._menu_frame = ctk.CTkFrame(
            self.app,
            corner_radius=12,
            fg_color="#151521",
            border_width=1,
            width=240,
            height=240,
        )
        self._menu_frame.configure(border_color="#2e2e44")

        if self._on_toggle_startup:
            self._btn_startup = ctk.CTkButton(
                self._menu_frame,
                text="Iniciar com Windows",
                anchor="w",
                height=34,
                fg_color="#252533",
                hover_color="#3b3b4f",
                command=self._alternar_startup,
            )
            self._btn_startup.pack(fill="x", padx=8, pady=(8, 5))
            self._atualizar_texto_startup()

        btn_apps = ctk.CTkButton(
            self._menu_frame,
            text="Adicionar Apps",
            anchor="w",
            height=34,
            fg_color="#252533",
            hover_color="#3b3b4f",
            command=self._abrir_cadastro_apps,
        )
        btn_apps.pack(fill="x", padx=8, pady=(5, 5))

        btn_remote = ctk.CTkButton(
            self._menu_frame,
            text="Conectar Remotamente",
            anchor="w",
            height=34,
            fg_color="#252533",
            hover_color="#3b3b4f",
            command=self._abrir_conexao_remota,
        )
        btn_remote.pack(fill="x", padx=8, pady=(5, 8))

        btn_llm = ctk.CTkButton(
            self._menu_frame,
            text="Configurar API/Modelos",
            anchor="w",
            height=34,
            fg_color="#252533",
            hover_color="#3b3b4f",
            command=self._abrir_config_llm,
        )
        btn_llm.pack(fill="x", padx=8, pady=(0, 8))

        btn_voz = ctk.CTkButton(
            self._menu_frame,
            text="Configurar Voz",
            anchor="w",
            height=34,
            fg_color="#252533",
            hover_color="#3b3b4f",
            command=self._abrir_config_voz,
        )
        btn_voz.pack(fill="x", padx=8, pady=(0, 8))

    def _atualizar_texto_startup(self, ativo: Optional[bool] = None) -> None:
        if not hasattr(self, "_btn_startup"):
            return
        if ativo is None:
            texto = "Iniciar com Windows"
        else:
            texto = "Desativar inicio com Windows" if ativo else "Iniciar com Windows"
        self._btn_startup.configure(text=texto)

    def _alternar_startup(self) -> None:
        if self._menu_aberto:
            self._alternar_menu_superior()
        if not self._on_toggle_startup:
            return
        try:
            resultado = self._on_toggle_startup()
        except Exception:
            resultado = None
        if isinstance(resultado, bool):
            self._atualizar_texto_startup(resultado)

    def _alternar_menu_superior(self) -> None:
        if self._menu_aberto:
            self._menu_frame.place_forget()
            self._menu_aberto = False
            return
        self._menu_frame.place(x=14, y=54)
        self._menu_frame.lift()
        self.btn_menu.lift()
        self._menu_aberto = True

    def _atualizar_status(self) -> None:
        cpu_percent = psutil.cpu_percent()
        ram_percent = psutil.virtual_memory().percent
        self.cpu_bar.set(cpu_percent / 100)
        self.ram_bar.set(ram_percent / 100)
        self.cpu_label.configure(text=f"CPU: {cpu_percent}%")
        self.ram_label.configure(text=f"RAM: {ram_percent}%")
        self.hora_label.configure(text=datetime.datetime.now().strftime("%H:%M:%S"))
        self.app.after(1000, self._atualizar_status)

    @staticmethod
    def _desenhar_triangulo(cx: int, cy: int, largura: int, altura: int):
        return [cx, cy - altura, cx - largura, cy + altura, cx + largura, cy + altura]

    def _criar_logo(self, _event=None) -> None:
        self.canvas.delete("all")

        largura_canvas = self.canvas.winfo_width()
        altura_canvas = self.canvas.winfo_height()
        if largura_canvas < 10 or altura_canvas < 10:
            return

        cx = largura_canvas // 2
        cy = altura_canvas // 2

        largura = 240
        altura = 140

        self._tri_ext = self.canvas.create_polygon(
            self._desenhar_triangulo(cx, cy, largura, altura),
            outline="#00f2ff",
            width=4,
            fill="",
        )
        self._tri_int = self.canvas.create_polygon(
            self._desenhar_triangulo(cx, cy, largura - 70, altura - 50),
            outline="#7b2ff7",
            width=3,
            fill="",
        )
        self._hud_text = self.canvas.create_text(
            cx,
            cy,
            text="A.L.T.A.I.R",
            fill="#00aaff",
            font=("Orbitron", 32, "bold"),
        )

    def _animar_hud(self) -> None:
        if not self._hud_text:
            self.app.after(50, self._animar_hud)
            return

        largura_canvas = self.canvas.winfo_width()
        altura_canvas = self.canvas.winfo_height()
        cx = largura_canvas // 2
        cy = altura_canvas // 2
        pulse = math.sin(time.time() * 3) * 6

        self.canvas.coords(self._hud_text, cx, cy + pulse)

        if int(time.time() * 2) % 2 == 0:
            self.canvas.itemconfig(self._tri_ext, outline="#00f2ff")
            self.canvas.itemconfig(self._tri_int, outline="#7b2ff7")
        else:
            self.canvas.itemconfig(self._tri_ext, outline="#7b2ff7")
            self.canvas.itemconfig(self._tri_int, outline="#00f2ff")

        self.app.after(16, self._animar_hud)

    def _enviar(self) -> None:
        comando = self.entry.get().strip()
        if not comando:
            return

        self.adicionar_mensagem(comando, "usuario")
        self.entry.delete(0, "end")
        self.mostrar_digitando()
        self.set_ia_status("IA: Processando...")

        def processar():
            try:
                falar_resposta = bool(self._falar_var.get())
                resultado = self._process_command(comando) or {}
                self.app.after(0, lambda: self._finalizar_resposta(resultado))
                texto_fala = resultado.get("fala", "")
                if falar_resposta and texto_fala:
                    threading.Thread(target=self._speak_text, args=(texto_fala,), daemon=True).start()
            except Exception as exc:
                self.app.after(0, lambda: self._mostrar_erro(str(exc)))

        threading.Thread(target=processar, daemon=True).start()

    def _finalizar_resposta(self, resultado: Any) -> None:
        self.remover_digitando()
        if isinstance(resultado, dict):
            self.adicionar_mensagem(
                resultado.get("visual", ""),
                "ia",
                file_path=resultado.get("file") or resultado.get("arquivo"),
            )
        else:
            self.adicionar_mensagem(str(resultado), "ia")
        self.set_ia_status("IA: Pronta")

    def _mostrar_erro(self, erro: str) -> None:
        self.remover_digitando()
        self.adicionar_mensagem(f"[ERRO]: {erro}", "ia")
        self.set_ia_status("IA: Erro")

    def _render_media(self, frame: ctk.CTkFrame, file_path: str, largura_max: int) -> None:
        file_path = os.path.abspath(file_path)
        nome = os.path.basename(file_path)

        thumb_label = ctk.CTkLabel(frame, text="", fg_color=frame.cget("fg_color"))
        thumb_label.pack(anchor="w", padx=6, pady=4)

        btns = ctk.CTkFrame(frame, fg_color=frame.cget("fg_color"))
        btns.pack(anchor="w", padx=6, pady=(0, 4))

        def abrir():
            try:
                os.startfile(file_path)
            except Exception:
                pass

        def download():
            destino = filedialog.asksaveasfilename(
                title="Salvar arquivo",
                initialfile=nome,
                defaultextension=os.path.splitext(nome)[1] or ".png",
            )
            if destino:
                try:
                    shutil.copyfile(file_path, destino)
                except Exception:
                    pass

        btn_open = ctk.CTkButton(btns, text="Abrir", width=80, command=abrir)
        btn_open.pack(side="left", padx=(0, 6))
        btn_dl = ctk.CTkButton(btns, text="Download", width=100, command=download)
        btn_dl.pack(side="left")

        # Preview se PIL estiver disponivel e for imagem
        if Image and ImageTk and os.path.splitext(nome)[1].lower() in {".png", ".jpg", ".jpeg"}:
            try:
                img = Image.open(file_path)
                img.thumbnail((largura_max, 260))
                photo = ImageTk.PhotoImage(img)
                thumb_label.configure(image=photo)
                thumb_label.image = photo  # evitar GC
            except Exception:
                thumb_label.configure(text=nome)
        else:
            thumb_label.configure(text=nome)

    def adicionar_mensagem(self, texto, autor: str = "ia", animar: bool = True, file_path: Optional[str] = None) -> None:
        texto = str(texto)

        container = ctk.CTkFrame(self.chat_area, fg_color="transparent")
        container.pack(fill="x", pady=6, padx=10)

        self.chat_area.update_idletasks()
        largura_area = max(self.chat_area.winfo_width(), 420)
        largura_max = max(220, largura_area - 150)

        if autor == "usuario":
            cor = "#7b2ff7"
            anchor = "e"
            text_color = "white"
            bubble_padx = (80, 18)
        else:
            cor = "#1f1f2b"
            anchor = "w"
            text_color = "white"
            bubble_padx = (10, 80)

        bubble = ctk.CTkFrame(container, fg_color=cor, corner_radius=20)
        bubble.pack(anchor=anchor, padx=bubble_padx)

        label = ctk.CTkLabel(
            bubble,
            text="",
            wraplength=largura_max,
            justify="left",
            text_color=text_color,
            font=("Segoe UI", 15),
        )
        label.pack(padx=15, pady=(10, 6))

        media_frame = None
        if file_path and os.path.exists(file_path):
            media_frame = ctk.CTkFrame(bubble, fg_color=cor)
            media_frame.pack(fill="x", padx=10, pady=(0, 8))
            self._render_media(media_frame, file_path, largura_max)

        if autor == "ia":
            def copiar_com_feedback(t=texto):
                self.copiar_texto_chat(t)
                btn_copiar.configure(text="✓", state="disabled")
                self.app.after(
                    1000,
                    lambda: btn_copiar.configure(text="⧉", state="normal"),
                )

            btn_copiar = ctk.CTkButton(
                bubble,
                text="⧉",
                width=28,
                height=24,
                corner_radius=8,
                fg_color="#2a2a35",
                hover_color="#3f3f4d",
                text_color="#d8d8e2",
                font=("Segoe UI Symbol", 14, "bold"),
                command=copiar_com_feedback,
            )
            btn_copiar.place_forget()

            def mostrar_botao(_event=None):
                btn_copiar.place(relx=1.0, x=-8, y=8, anchor="ne")

            def esconder_botao(_event=None):
                self.app.after(80, _esconder_se_fora)

            def _esconder_se_fora():
                try:
                    x, y = self.app.winfo_pointerxy()
                    atual = self.app.winfo_containing(x, y)
                except Exception:
                    atual = None

                if self._eh_descendente(atual, bubble):
                    return
                btn_copiar.place_forget()

            label.bind("<Double-Button-1>", lambda _e, t=texto: self.copiar_texto_chat(t))
            label.bind("<Button-3>", lambda _e, t=texto: self.copiar_texto_chat(t))
            bubble.bind("<Double-Button-1>", lambda _e, t=texto: self.copiar_texto_chat(t))
            bubble.bind("<Button-3>", lambda _e, t=texto: self.copiar_texto_chat(t))
            label.bind("<Enter>", mostrar_botao)
            bubble.bind("<Enter>", mostrar_botao)
            btn_copiar.bind("<Enter>", mostrar_botao)
            label.bind("<Leave>", esconder_botao)
            bubble.bind("<Leave>", esconder_botao)
            btn_copiar.bind("<Leave>", esconder_botao)

        self.chat_area.update_idletasks()
        self.chat_area._parent_canvas.yview_moveto(1.0)

        if animar and autor == "ia":
            self._animar_fade_in_label(label, texto)
            return

        label.configure(text=texto)
        self.chat_area.update_idletasks()
        self.chat_area._parent_canvas.yview_moveto(1.0)

    @staticmethod
    def _hex_to_rgb(cor: str) -> tuple[int, int, int]:
        cor = cor.lstrip("#")
        return int(cor[0:2], 16), int(cor[2:4], 16), int(cor[4:6], 16)

    @staticmethod
    def _eh_descendente(widget, ancestral) -> bool:
        atual = widget
        while atual is not None:
            if atual == ancestral:
                return True
            atual = getattr(atual, "master", None)
        return False

    @staticmethod
    def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
        r, g, b = rgb
        return f"#{r:02x}{g:02x}{b:02x}"

    def _animar_fade_in_label(self, label: ctk.CTkLabel, texto: str) -> None:
        cor_inicio = "#7a7a86"
        cor_final = "#ffffff"
        passos = 10
        intervalo_ms = 24
        rgb_inicio = self._hex_to_rgb(cor_inicio)
        rgb_final = self._hex_to_rgb(cor_final)

        label.configure(text=texto, text_color=cor_inicio)

        def animar(passo=0):
            t = min(1.0, passo / passos)
            cor_atual = (
                int(rgb_inicio[0] + (rgb_final[0] - rgb_inicio[0]) * t),
                int(rgb_inicio[1] + (rgb_final[1] - rgb_inicio[1]) * t),
                int(rgb_inicio[2] + (rgb_final[2] - rgb_inicio[2]) * t),
            )
            label.configure(text_color=self._rgb_to_hex(cor_atual))
            self.chat_area.update_idletasks()
            self.chat_area._parent_canvas.yview_moveto(1.0)
            if passo < passos:
                self.app.after(intervalo_ms, animar, passo + 1)

        animar(0)

    def mostrar_digitando(self) -> None:
        self._typing_animating = True

        container = ctk.CTkFrame(self.chat_area, fg_color="transparent")
        container.pack(fill="x", pady=8, padx=10)

        bubble = ctk.CTkFrame(container, fg_color="#1f1f2b", corner_radius=20)
        bubble.pack(anchor="w")

        self._digitando_label = ctk.CTkLabel(
            bubble,
            text="\u25cf",
            font=("Segoe UI", 18),
            text_color="#aaaaaa",
        )
        self._digitando_label.pack(padx=20, pady=10)

        def animar_pontos(i=0):
            if not self._typing_animating or not self._digitando_label:
                return
            pontos = ["\u25cf  ", "\u25cf\u25cf ", "\u25cf\u25cf\u25cf"]
            self._digitando_label.configure(text=pontos[i % 3])
            self.app.after(400, animar_pontos, i + 1)

        animar_pontos()

    def remover_digitando(self) -> None:
        self._typing_animating = False
        if self._digitando_label:
            self._digitando_label.master.master.destroy()
            self._digitando_label = None

    def copiar_texto_chat(self, texto: str) -> None:
        self.app.clipboard_clear()
        self.app.clipboard_append(str(texto))
        self.set_ia_status("IA: Texto copiado")
        self.app.after(1200, lambda: self.set_ia_status("IA: Pronta"))

    def _selecionar_arquivo_envio(self) -> None:
        caminho = filedialog.askopenfilename(title="Selecione um arquivo para enviar no WhatsApp")
        if not caminho:
            return

        self._on_file_selected(caminho)
        nome_arquivo = os.path.basename(caminho)
        self.label_arquivo.configure(text=f"Arquivo: {nome_arquivo}")

    def _abrir_cadastro_apps(self) -> None:
        if self._menu_aberto:
            self._alternar_menu_superior()
        if self._on_open_apps_register:
            self._on_open_apps_register(self.app)

    def _abrir_conexao_remota(self) -> None:
        if self._menu_aberto:
            self._alternar_menu_superior()
        if self._on_open_remote_connect:
            self._on_open_remote_connect(self.app)

    def _abrir_config_llm(self) -> None:
        if self._menu_aberto:
            self._alternar_menu_superior()
        if self._on_open_llm_config:
            self._on_open_llm_config(self.app)

    def _abrir_config_voz(self) -> None:
        if self._menu_aberto:
            self._alternar_menu_superior()
        if self._on_open_voice_config:
            self._on_open_voice_config(self.app)

    def atualizar_callback_voz(self, speak_text: Callable[[str], None]) -> None:
        self._speak_text = speak_text

    def set_ia_status(self, texto: str) -> None:
        self.ia_status_label.configure(text=texto)

    def atualizar_botao_microfone(self, ativo: bool) -> None:
        def atualizar():
            if ativo:
                self.btn_voz.configure(text="\U0001f534", fg_color="#ff0033", hover_color="#ff3355")
                self.mic_status_label.configure(text="MICROFONE: Ativo")
            else:
                self.btn_voz.configure(text="\U0001f3a4", fg_color="#5a189a", hover_color="#7b2ff7")
                self.mic_status_label.configure(text="MICROFONE: Inativo")

        self.app.after(0, atualizar)

    def trazer_para_frente(self) -> None:
        self.app.deiconify()
        self.app.lift()
        self.app.attributes("-topmost", True)
        self.app.after(500, lambda: self.app.attributes("-topmost", False))

    def run(self) -> None:
        self.app.mainloop()
