import datetime
import html as html_lib
import math
import os
import re
import shutil
import threading
import time
from typing import Any, Callable, Dict, Optional

import psutil

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt, QThread, QTimer, QUrl, QObject, QEvent, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap, QRadialGradient, QTransform, QTextOption
from PyQt5.QtWidgets import QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QProgressBar, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QListWidget, QListWidgetItem, QToolButton, QTextEdit, QVBoxLayout, QWidget, QInputDialog


class _UiBridge(QObject):
    add_message = pyqtSignal(str, str, bool, object)
    show_typing = pyqtSignal()
    remove_typing = pyqtSignal()
    set_status = pyqtSignal(str)
    set_mic = pyqtSignal(bool)
    set_mic_btn_enabled = pyqtSignal(bool)
    bring_front = pyqtSignal()
    final_response = pyqtSignal(object)
    show_error = pyqtSignal(str)
    set_hud_state = pyqtSignal(str)
    set_hud_level = pyqtSignal(float)
    set_hud_responding = pyqtSignal(bool)


class HudWidget(QWidget):
    def __init__(self, owner: "DesktopUI") -> None:
        super().__init__(owner)
        self._owner = owner
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            self._owner._paint_hud(painter, self.width(), self.height())
        finally:
            if painter.isActive():
                painter.end()


class ComposerEdit(QTextEdit):
    send_requested = pyqtSignal()

    MIN_HEIGHT = 56
    MAX_HEIGHT = 180

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Digite uma mensagem...")
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setTabChangesFocus(True)
        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setMaximumHeight(self.MAX_HEIGHT)
        self.textChanged.connect(self._ajustar_altura)
        self._ajustar_altura()

    def _ajustar_altura(self) -> None:
        margem = self.frameWidth() * 2 + 22
        altura_texto = int(self.document().size().height()) + margem
        self.setFixedHeight(max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, altura_texto)))

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._ajustar_altura()


class DesktopUI(QMainWindow):
    def __init__(
        self,
        process_command: Callable[..., Dict[str, str]],
        speak_text: Callable[[str], None],
        on_audio_start: Callable[[], None],
        on_file_selected: Callable[[str], None],
        app_title: str = "A.L.T.A.I.R",
        continuous_listen_default: bool = True,
        on_toggle_startup: Optional[Callable[[], Optional[bool]]] = None,
        on_open_apps_register: Optional[Callable[[QWidget], None]] = None,
        on_open_remote_connect: Optional[Callable[[QWidget], None]] = None,
        on_open_llm_config: Optional[Callable[[QWidget], None]] = None,
        on_open_voice_config: Optional[Callable[[QWidget], None]] = None,
    ) -> None:
        self._qt_app = QApplication.instance() or QApplication([])
        super().__init__()
        self._process_command = process_command
        self._speak_text = speak_text
        self._on_audio_start = on_audio_start
        self._on_file_selected = on_file_selected
        self._on_toggle_startup = on_toggle_startup
        self._on_open_apps_register = on_open_apps_register
        self._on_open_remote_connect = on_open_remote_connect
        self._on_open_llm_config = on_open_llm_config
        self._on_open_voice_config = on_open_voice_config
        self._continuous_listen_enabled = bool(continuous_listen_default)
        self._bridge = _UiBridge()
        self._bridge.add_message.connect(self._adicionar_mensagem_impl)
        self._bridge.show_typing.connect(self._mostrar_digitando_impl)
        self._bridge.remove_typing.connect(self._remover_digitando_impl)
        self._bridge.set_status.connect(self._set_ia_status_impl)
        self._bridge.set_mic.connect(self._atualizar_botao_microfone_impl)
        self._bridge.set_mic_btn_enabled.connect(self._set_mic_button_enabled_impl)
        self._bridge.bring_front.connect(self._trazer_para_frente_impl)
        self._bridge.final_response.connect(self._finalizar_resposta_impl)
        self._bridge.show_error.connect(self._mostrar_erro_impl)
        self._bridge.set_hud_state.connect(self._set_hud_state_impl)
        self._bridge.set_hud_level.connect(self._set_hud_audio_level_impl)
        self._bridge.set_hud_responding.connect(self._set_hud_responding_impl)
        self._audio_starting = False

        self._typing_widget: Optional[QWidget] = None
        self._typing_label: Optional[QLabel] = None
        self._typing_timer: Optional[QTimer] = None
        self._typing_index = 0
        self._hud_angle_main = 0.0
        self._hud_angle_inner = 0.0
        self._hud_grid_offset = 0.0
        self._blueprint_progress = 0.0
        self._blueprint_pulse_phase = 0.0
        self._blueprint_shimmer_phase = 0.0
        self._gear_spinning = False
        self._gear_spin_factor = 0.0
        self._processing_count = 0
        self._hud_last_tick = time.perf_counter()
        self._hud_dt_smoothed = 1.0 / 45.0
        self._hud_target_frame_ms = int(os.getenv("ALTAIR_HUD_FRAME_MS", "30"))
        self._hud_restore_hold_until = 0.0
        self._hud_was_iconic = False
        self._hud_state = "inactive"
        self._hud_mic_active = False
        self._hud_responding = False
        # Escuta continua pode ficar rodando em background; UI "ouvindo" so aparece quando
        # o usuario ativa pelo botao de audio.
        self._continuous_listen_running = False
        self._ptt_active = False
        self._hud_audio_level = 0.0
        self._hud_audio_level_target = 0.0
        self._hud_response_wave = 0.0
        self._hud_wave_intensity = 0.18

        # Macros (automatizar tarefas)
        self._macro_recorder = None
        self._macro_recording = False
        self._macro_last_path = ""
        self._macro_esc_listener = None
        self._macro_player_thread = None
        self._macro_dialog = None
        self._macro_trash_show_until = 0.0
        self._macro_trash_hide_timer = QTimer(self)
        self._macro_trash_hide_timer.setSingleShot(True)
        self._macro_trash_hide_timer.timeout.connect(self._macro_hide_all_trash_buttons)

        self._apply_theme()
        self._build_ui(app_title)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._atualizar_status)
        self._status_timer.start(1000)

        self._hud_timer = QTimer(self)
        self._hud_timer.timeout.connect(self._animar_hud_visual)
        self._hud_timer.start(self._hud_target_frame_ms)
        self._atualizar_status()

        # Escuta continua: inicia automaticamente apos a UI estar pronta.
        QTimer.singleShot(900, self._maybe_start_continuous_listen)

    def _apply_theme(self) -> None:
        self.setObjectName("altairWindow")
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(
            """
            QMainWindow#altairWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #02060f,
                    stop:0.50 #020913,
                    stop:1 #01040b);
            }
            QFrame#panel {
                background: rgba(4, 12, 24, 220);
                border: 1px solid rgba(56, 108, 164, 72);
                border-radius: 20px;
            }
            QFrame#composerPanel {
                background: rgba(6, 15, 30, 222);
                border: 1px solid rgba(68, 120, 178, 88);
                border-radius: 18px;
            }
            QFrame#messageBubble {
                border-radius: 20px;
                border: 1px solid rgba(92, 152, 214, 95);
            }
            QTextEdit {
                background: rgba(8, 20, 36, 236);
                color: #eef7ff;
                border: 1px solid rgba(78, 132, 194, 122);
                border-radius: 16px;
                padding: 10px 15px;
                font-size: 11pt;
            }
            QTextEdit:focus {
                border: 1px solid rgba(120, 198, 255, 180);
            }
            QLabel {
                color: #d9ecff;
            }
            QCheckBox {
                color: #d9ecff;
                spacing: 8px;
                font-size: 9.5pt;
            }
            QCheckBox::indicator {
                width: 0px;
                height: 0px;
            }
            QPushButton, QToolButton {
                background: rgba(10, 25, 44, 228);
                color: #eef7ff;
                border: 1px solid rgba(70, 130, 196, 98);
                border-radius: 14px;
                padding: 8px 13px;
                font-size: 10pt;
            }
            QPushButton:hover, QToolButton:hover { background: rgba(18, 38, 62, 232); border-color: rgba(120, 192, 255, 145); }
            QPushButton:pressed, QToolButton:pressed { background: rgba(8, 18, 34, 225); }
            QProgressBar {
                background: rgba(8, 20, 34, 214);
                border: 1px solid rgba(48, 96, 150, 98);
                border-radius: 6px;
                height: 9px;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #42d9ff,
                    stop:1 #3f7dff);
            }
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: transparent;
                width: 9px;
                margin: 10px 2px 10px 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(118, 174, 232, 120);
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(150, 221, 255, 180);
            }
            """
        )

        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#040b14"))
        palette.setColor(QPalette.Base, QColor("#081224"))
        palette.setColor(QPalette.Text, QColor("#eef7ff"))
        palette.setColor(QPalette.WindowText, QColor("#eef7ff"))
        palette.setColor(QPalette.Button, QColor("#223a56"))
        palette.setColor(QPalette.ButtonText, QColor("#eef7ff"))
        self._qt_app.setPalette(palette)
        self._qt_app.setStyle("Fusion")

    def _build_ui(self, app_title: str) -> None:
        self.setWindowTitle(app_title)
        self.resize(1760, 1020)
        self.setMinimumSize(1500, 900)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)
        root.addLayout(top_bar)

        self.btn_menu = QToolButton(self)
        self.btn_menu.setText("")
        self.btn_menu.setIcon(self._icon_pixmap("menu", 20))
        self.btn_menu.setIconSize(self.btn_menu.iconSize())
        self.btn_menu.setFixedSize(42, 42)
        self.btn_menu.setToolTip("Menu")
        self.btn_menu.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        self._action_startup = menu.addAction("Iniciar com Windows")
        self._action_startup.setEnabled(self._on_toggle_startup is not None)
        self._action_startup.triggered.connect(self._alternar_startup)
        self._action_continuous_listen = menu.addAction("Escuta continua (ao iniciar)")
        self._action_continuous_listen.setCheckable(True)
        self._action_continuous_listen.setChecked(self._continuous_listen_enabled)
        self._action_continuous_listen.toggled.connect(self._toggle_continuous_listen)
        menu.addSeparator()
        menu.addAction("Adicionar Apps").triggered.connect(self._abrir_cadastro_apps)
        menu.addAction("Conectar Remotamente").triggered.connect(self._abrir_conexao_remota)
        menu.addAction("Configurar API/Modelos").triggered.connect(self._abrir_config_llm)
        menu.addAction("Configurar Voz").triggered.connect(self._abrir_config_voz)
        menu.setFont(QFont("Segoe UI", 11))
        menu.setStyleSheet(
            """
            QMenu {
                background: rgba(10, 15, 23, 245);
                color: #eef7ff;
                border: 1px solid rgba(110, 145, 198, 120);
                border-radius: 12px;
                padding: 6px;
            }
            QMenu::item {
                padding: 8px 22px;
                border-radius: 8px;
                font-size: 11pt;
            }
            QMenu::item:selected {
                background: rgba(72, 96, 128, 180);
            }
            """
        )
        self.btn_menu.setMenu(menu)
        top_bar.addWidget(self.btn_menu)

        logo = QLabel(self)
        logo.setPixmap(self._icon_pixmap("bot", 18).pixmap(18, 18))
        top_bar.addWidget(logo)

        title = QLabel(app_title, self)
        title.setStyleSheet("font: 500 15px 'Segoe UI'; color: #d4eeff; letter-spacing: 1px;")
        top_bar.addWidget(title)
        top_bar.addStretch(1)

        top_rule = QFrame(self)
        top_rule.setFrameShape(QFrame.HLine)
        top_rule.setStyleSheet("color: rgba(70, 112, 156, 86); background: rgba(70, 112, 156, 86);")
        top_rule.setFixedHeight(1)
        root.addWidget(top_rule)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        left = self._make_panel()
        left.setFixedWidth(304)
        body.addWidget(left, 0)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        gear_icon = QLabel(left)
        gear_icon.setPixmap(self._icon_pixmap("cpu", 16).pixmap(16, 16))
        header.addWidget(gear_icon)
        left_title = QLabel("SISTEMA", left)
        left_title.setStyleSheet("font: 700 13px 'Segoe UI'; color: #dbefff; letter-spacing: 1.1px;")
        header.addWidget(left_title)
        header.addStretch(1)
        left_layout.addLayout(header)

        def make_status_block(
            title_text: str,
            value_label: QLabel,
            bar: Optional[QProgressBar] = None,
            status_label: Optional[QLabel] = None,
            icon_kind: str = "gear",
        ) -> None:
            block = QFrame(left)
            block.setObjectName("statusBlock")
            block.setStyleSheet(
                "QFrame#statusBlock { background: rgba(9, 19, 33, 220); border: 1px solid rgba(64, 120, 170, 86); border-radius: 14px; }"
            )
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(12, 10, 12, 10)
            block_layout.setSpacing(4)
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setSpacing(8)
            icon = QLabel(block)
            icon.setPixmap(self._icon_pixmap(icon_kind, 14).pixmap(14, 14))
            top.addWidget(icon)
            title = QLabel(title_text, block)
            title.setStyleSheet("font: 600 10.5px 'Segoe UI'; color: #cfe5f7;")
            top.addWidget(title)
            top.addStretch(1)
            value_label.setStyleSheet("font: 700 10.5px 'Segoe UI'; color: #9fdcff;")
            top.addWidget(value_label)
            block_layout.addLayout(top)
            if status_label is not None:
                status_label.setStyleSheet("font: 500 10px 'Segoe UI'; color: #41e2a1;")
                block_layout.addWidget(status_label)
            if bar is not None:
                bar.setFixedHeight(9)
                block_layout.addWidget(bar)
            left_layout.addWidget(block)

        self.cpu_bar = self._progress_bar()
        self.cpu_label = QLabel("0.0%", left)
        self.cpu_status = QLabel("Estavel", left)
        make_status_block("CPU", self.cpu_label, self.cpu_bar, self.cpu_status, "cpu")

        self.ram_bar = self._progress_bar()
        self.ram_label = QLabel("0.0%", left)
        self.ram_status = QLabel("Moderado", left)
        make_status_block("MEMORIA", self.ram_label, self.ram_bar, self.ram_status, "ram")

        self.mic_status_label = QLabel("Inativo", left)
        self.mic_value_label = QLabel("VOZ / MICROFONE", left)
        make_status_block("VOZ / MICROFONE", self.mic_status_label, None, self.mic_value_label, "voice")

        self.ia_status_label = QLabel("Processando", left)
        self.ia_value_label = QLabel("IA", left)
        make_status_block("IA", self.ia_status_label, None, self.ia_value_label, "ia")

        # Automatizar tarefas (macros)
        macro_block = QFrame(left)
        macro_block.setObjectName("statusBlock")
        macro_block.setStyleSheet(
            "QFrame#statusBlock { background: rgba(9, 19, 33, 220); border: 1px solid rgba(64, 120, 170, 86); border-radius: 14px; }"
        )
        macro_l = QVBoxLayout(macro_block)
        macro_l.setContentsMargins(12, 10, 12, 10)
        macro_l.setSpacing(8)
        macro_top = QHBoxLayout()
        macro_top.setContentsMargins(0, 0, 0, 0)
        macro_top.setSpacing(8)
        macro_icon = QLabel(macro_block)
        macro_icon.setPixmap(self._icon_pixmap("terminal", 14).pixmap(14, 14))
        macro_top.addWidget(macro_icon)
        macro_title = QLabel("AUTOMACAO", macro_block)
        macro_title.setStyleSheet("font: 600 10.5px 'Segoe UI'; color: #cfe5f7;")
        macro_top.addWidget(macro_title)
        macro_top.addStretch(1)
        macro_l.addLayout(macro_top)

        self.btn_macro = QPushButton("Automatizar tarefas", macro_block)
        self.btn_macro.setCursor(Qt.PointingHandCursor)
        self.btn_macro.setFixedHeight(34)
        self.btn_macro.setStyleSheet(
            "QPushButton { background: rgba(9, 17, 30, 228); border: 1px solid rgba(72, 125, 180, 96); "
            "border-radius: 12px; color: #d8eeff; padding: 6px 12px; font: 700 10.2pt 'Segoe UI'; text-align: left; }"
            "QPushButton:hover { background: rgba(18, 37, 62, 236); border-color: rgba(112, 188, 255, 170); }"
            "QPushButton:pressed { background: rgba(8, 14, 24, 236); }"
        )
        self.btn_macro.clicked.connect(self._abrir_macro_menu)
        macro_l.addWidget(self.btn_macro)
        left_layout.addWidget(macro_block)

        # Removido: "ATIVIDADE RECENTE" e relogio no painel lateral (menos poluicao visual).
        left_layout.addStretch(1)

        center = self._make_panel()
        body.addWidget(center, 5)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(14, 14, 14, 14)
        center_layout.setSpacing(10)

        self.hud_top_badge = QLabel("OUVINDO...", center)
        self.hud_top_badge.setAlignment(Qt.AlignCenter)
        self.hud_top_badge.setStyleSheet(
            "background: rgba(46, 28, 88, 220); border: 1px solid rgba(140, 88, 255, 180);"
            "border-radius: 18px; color: #d9c4ff; font: 700 11pt 'Segoe UI'; padding: 8px 20px;"
        )
        self.hud_top_badge.setFixedWidth(220)
        center_layout.addWidget(self.hud_top_badge, 0, Qt.AlignHCenter)

        self.hud_widget = HudWidget(self)
        self.hud_widget.setMinimumSize(680, 580)
        center_layout.addWidget(self.hud_widget, 1)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(10)
        center_layout.addLayout(quick_row)
        for titulo, subtitulo in [
            ("Conversar", "Enviar mensagem"),
            ("Falar", "Ativar voz"),
            ("Comandos", "Executar acoes"),
            ("Sugestoes", "Ver exemplos"),
        ]:
            card = QFrame(center)
            card.setObjectName("quickCard")
            card.setStyleSheet(self._estilo_card_rapido(hover=False))
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(14, 10, 14, 10)
            card_l.setSpacing(4)
            kind = "chat"
            if titulo == "Falar":
                kind = "voice"
            elif titulo == "Comandos":
                kind = "terminal"
            elif titulo == "Sugestoes":
                kind = "bulb"
            ic = QLabel(card)
            ic.setPixmap(self._icon_pixmap(kind, 18).pixmap(18, 18))
            card_l.addWidget(ic, 0, Qt.AlignLeft)
            t = QLabel(titulo, card)
            t.setStyleSheet("font: 600 10.8pt 'Segoe UI'; color: #d8eeff;")
            s = QLabel(subtitulo, card)
            s.setStyleSheet("font: 500 10pt 'Segoe UI'; color: #8db3d3;")
            card_l.addWidget(t)
            card_l.addWidget(s)
            card.setCursor(Qt.PointingHandCursor)
            card.enterEvent = (lambda _event, c=card: c.setStyleSheet(self._estilo_card_rapido(hover=True)))
            card.leaveEvent = (lambda _event, c=card: c.setStyleSheet(self._estilo_card_rapido(hover=False)))
            card.mousePressEvent = (lambda _event, acao=titulo.lower(): self._acao_card_rapido(acao))
            quick_row.addWidget(card, 1)

        # Removido do HUD central: macros ficam no painel lateral esquerdo.

        right = self._make_panel()
        right.setMinimumWidth(440)
        right.setMaximumWidth(520)
        body.addWidget(right, 3)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        chat_header = QHBoxLayout()
        chat_icon = QLabel(right)
        chat_icon.setPixmap(self._icon_pixmap("chat", 16).pixmap(16, 16))
        chat_header.addWidget(chat_icon)
        chat_title = QLabel("CONVERSA", right)
        chat_title.setStyleSheet("font: 700 12pt 'Segoe UI'; color: #dff2ff; letter-spacing: 0.8px;")
        chat_header.addWidget(chat_title)
        chat_header.addStretch(1)
        self.btn_limpar_chat = QToolButton(right)
        self.btn_limpar_chat.setText("Limpar conversa")
        self.btn_limpar_chat.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_limpar_chat.setFixedHeight(30)
        self.btn_limpar_chat.clicked.connect(self._limpar_chat)
        chat_header.addWidget(self.btn_limpar_chat)
        right_layout.addLayout(chat_header)

        self.chat_scroll = QScrollArea(right)
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_content = QWidget()
        self.chat_content.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(6)
        self.chat_layout.addStretch(1)
        self.chat_scroll.setWidget(self.chat_content)
        right_layout.addWidget(self.chat_scroll, 1)

        bottom = QFrame(right)
        bottom.setObjectName("composerPanel")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(13, 13, 13, 13)
        bottom_layout.setSpacing(10)

        self.entry = ComposerEdit(bottom)
        self.entry.send_requested.connect(self._enviar)
        self.entry.setMinimumWidth(0)
        self.entry.setMaximumWidth(10000)
        self.entry.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bottom_layout.addWidget(self.entry)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        bottom_layout.addLayout(actions_row)

        self.btn_attach = QToolButton(bottom)
        self.btn_attach.setText("+")
        self.btn_attach.setFixedSize(40, 40)
        self.btn_attach.setToolTip("Anexar arquivo")
        self.btn_attach.clicked.connect(self._selecionar_arquivo_envio)
        actions_row.addWidget(self.btn_attach)
        actions_row.addStretch(1)

        self.btn_send = QToolButton(bottom)
        self.btn_send.setText("")
        self.btn_send.setIcon(self._icon_pixmap("send", 20))
        self.btn_send.setFixedSize(42, 42)
        self.btn_send.setToolTip("Enviar mensagem")
        self.btn_send.clicked.connect(self._enviar)
        actions_row.addWidget(self.btn_send)

        self.btn_voz = QToolButton(bottom)
        self.btn_voz.setText("")
        self.btn_voz.setIcon(self._icon_pixmap("mic_record", 20))
        self.btn_voz.setFixedSize(40, 40)
        self.btn_voz.setToolTip("Iniciar audio")
        self.btn_voz.clicked.connect(self._iniciar_audio_seguro)
        self.btn_voz.setStyleSheet(
            "background: #d8d8d8; border: 1px solid #bdbdbd; border-radius: 12px;"
        )
        actions_row.addWidget(self.btn_voz)

        options_row = QHBoxLayout()
        options_row.setContentsMargins(2, 0, 2, 0)
        options_row.setSpacing(8)
        bottom_layout.addLayout(options_row)
        self.btn_falar = QToolButton(bottom)
        self.btn_falar.setCheckable(True)
        self.btn_falar.setChecked(True)
        self.btn_falar.setText("Voz: ligada")
        self.btn_falar.setIcon(self._icon_pixmap("mic_on", 16))
        self.btn_falar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_falar.setFixedHeight(32)
        self.btn_falar.toggled.connect(self._atualizar_botao_falar_impl)
        options_row.addWidget(self.btn_falar)
        options_row.addStretch(1)
        self._atualizar_botao_falar_impl(True)

        right_layout.addWidget(bottom, 0)
        # Removido: pontinhos decorativos abaixo do composer.
        self._atualizar_texto_startup()

        bottom_status = QFrame(self)
        bottom_status.setObjectName("composerPanel")
        bottom_status.setFixedHeight(46)
        bar_l = QHBoxLayout(bottom_status)
        bar_l.setContentsMargins(14, 6, 14, 6)
        bar_l.setSpacing(18)
        self.footer_datetime = QLabel("--/--/---- --:--", bottom_status)
        self.footer_datetime.setStyleSheet("font: 600 10.5pt 'Segoe UI'; color: #b9d9f1;")
        bar_l.addStretch(1)
        bar_l.addWidget(self.footer_datetime, 0, Qt.AlignRight)
        root.addWidget(bottom_status, 0)

    def _make_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("panel")
        effect = QGraphicsDropShadowEffect(panel)
        effect.setBlurRadius(20)
        effect.setOffset(0, 8)
        effect.setColor(QColor(0, 0, 0, 160))
        panel.setGraphicsEffect(effect)
        return panel

    def _progress_bar(self) -> QProgressBar:
        bar = QProgressBar(self)
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        return bar

    @staticmethod
    def _icon_pixmap(kind: str, size: int = 22) -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        pen = QPen(QColor("#eaf6ff"), max(2, size // 10))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        c = size / 2

        if kind == "menu":
            for y in (c - size * 0.18, c, c + size * 0.18):
                painter.drawLine(int(size * 0.2), int(y), int(size * 0.8), int(y))
        elif kind == "bot":
            glow = QRadialGradient(QPointF(c, c), size * 0.46)
            glow.setColorAt(0.0, QColor(40, 188, 255, 230))
            glow.setColorAt(1.0, QColor(36, 96, 210, 80))
            painter.setBrush(glow)
            painter.setPen(QPen(QColor("#4cc9ff"), max(2, size // 10)))
            painter.drawEllipse(QPointF(c, c), size * 0.34, size * 0.34)
            painter.setPen(QPen(QColor("#d8f6ff"), max(1, size // 14)))
            painter.drawEllipse(QPointF(c - size * 0.10, c - size * 0.03), size * 0.04, size * 0.04)
            painter.drawEllipse(QPointF(c + size * 0.10, c - size * 0.03), size * 0.04, size * 0.04)
        elif kind == "trash":
            # Lixeira (icone mais legivel em tamanhos pequenos)
            pen_w = max(1, int(size * 0.08))
            painter.setPen(QPen(QColor("#eaf6ff"), pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            # tampa
            painter.drawLine(int(size * 0.28), int(size * 0.30), int(size * 0.72), int(size * 0.30))
            painter.drawLine(int(size * 0.40), int(size * 0.22), int(size * 0.60), int(size * 0.22))
            painter.drawLine(int(size * 0.46), int(size * 0.22), int(size * 0.46), int(size * 0.30))
            painter.drawLine(int(size * 0.54), int(size * 0.22), int(size * 0.54), int(size * 0.30))
            # corpo
            body = QRectF(size * 0.32, size * 0.33, size * 0.36, size * 0.50)
            painter.drawRoundedRect(body, size * 0.08, size * 0.08)
            # linhas internas
            painter.drawLine(int(size * 0.44), int(size * 0.40), int(size * 0.44), int(size * 0.76))
            painter.drawLine(int(size * 0.56), int(size * 0.40), int(size * 0.56), int(size * 0.76))
            painter.drawArc(int(c - size * 0.16), int(c - size * 0.02), int(size * 0.32), int(size * 0.22), 0, -180 * 16)
        elif kind == "cpu":
            painter.setPen(QPen(QColor("#6aa8ff"), max(2, size // 11)))
            painter.drawRoundedRect(int(size * 0.27), int(size * 0.27), int(size * 0.46), int(size * 0.46), 3, 3)
            for k in (0.14, 0.86):
                painter.drawLine(int(size * k), int(size * 0.38), int(size * k), int(size * 0.62))
                painter.drawLine(int(size * 0.38), int(size * k), int(size * 0.62), int(size * k))
        elif kind == "ram":
            painter.setPen(QPen(QColor("#f2c33f"), max(2, size // 11)))
            painter.drawRoundedRect(int(size * 0.18), int(size * 0.34), int(size * 0.64), int(size * 0.32), 3, 3)
            for i in range(4):
                x = int(size * (0.25 + i * 0.13))
                painter.drawLine(x, int(size * 0.39), x, int(size * 0.61))
        elif kind == "voice":
            painter.setPen(QPen(QColor("#39e7b0"), max(2, size // 10)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(int(size * 0.38), int(size * 0.14), int(size * 0.24), int(size * 0.42), int(size * 0.12), int(size * 0.12))
            painter.drawArc(int(size * 0.24), int(size * 0.30), int(size * 0.52), int(size * 0.44), 180 * 16, 180 * 16)
            painter.drawLine(int(c), int(size * 0.68), int(c), int(size * 0.90))
            painter.drawLine(int(size * 0.34), int(size * 0.92), int(size * 0.66), int(size * 0.92))
        elif kind == "ia":
            painter.setPen(QPen(QColor("#46a7ff"), max(2, size // 11)))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(int(size * 0.20), int(size * 0.20), int(size * 0.60), int(size * 0.60), 0, 270 * 16)
            painter.drawEllipse(QPointF(c, c), size * 0.08, size * 0.08)
        elif kind == "chat":
            painter.setPen(QPen(QColor("#39c9ff"), max(2, size // 11)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(int(size * 0.18), int(size * 0.22), int(size * 0.64), int(size * 0.44), 4, 4)
            painter.drawLine(int(size * 0.38), int(size * 0.66), int(size * 0.28), int(size * 0.84))
            painter.drawLine(int(size * 0.32), int(size * 0.42), int(size * 0.46), int(size * 0.42))
            painter.drawLine(int(size * 0.54), int(size * 0.42), int(size * 0.68), int(size * 0.42))
        elif kind == "terminal":
            painter.setPen(QPen(QColor("#39e7b0"), max(2, size // 11)))
            painter.drawRoundedRect(int(size * 0.16), int(size * 0.24), int(size * 0.68), int(size * 0.52), 4, 4)
            painter.drawLine(int(size * 0.28), int(size * 0.40), int(size * 0.40), int(size * 0.50))
            painter.drawLine(int(size * 0.28), int(size * 0.60), int(size * 0.40), int(size * 0.50))
            painter.drawLine(int(size * 0.48), int(size * 0.60), int(size * 0.66), int(size * 0.60))
        elif kind == "bulb":
            painter.setPen(QPen(QColor("#f2c33f"), max(2, size // 11)))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(c, size * 0.42), size * 0.2, size * 0.2)
            painter.drawLine(int(size * 0.42), int(size * 0.62), int(size * 0.58), int(size * 0.62))
            painter.drawLine(int(size * 0.45), int(size * 0.70), int(size * 0.55), int(size * 0.70))
        elif kind == "clip":
            painter.setPen(QPen(QColor("#eaf6ff"), max(2, size // 11)))
            path = QPainterPath()
            path.moveTo(c - size * 0.04, c - size * 0.22)
            path.cubicTo(c + size * 0.18, c - size * 0.22, c + size * 0.18, c + size * 0.20, c, c + size * 0.20)
            path.cubicTo(c - size * 0.10, c + size * 0.20, c - size * 0.10, c - size * 0.05, c - size * 0.01, c - size * 0.05)
            path.cubicTo(c + size * 0.08, c - size * 0.05, c + size * 0.08, c + size * 0.12, c, c + size * 0.12)
            painter.drawPath(path)
        elif kind == "attach":
            path = QPainterPath()
            path.moveTo(c - size * 0.18, c + size * 0.02)
            path.cubicTo(c - size * 0.05, c - size * 0.18, c + size * 0.1, c - size * 0.18, c + size * 0.1, c - size * 0.02)
            path.cubicTo(c + size * 0.1, c + size * 0.12, c - size * 0.05, c + size * 0.18, c - size * 0.18, c + size * 0.08)
            painter.drawPath(path)
        elif kind == "send":
            path = QPainterPath()
            path.moveTo(size * 0.18, c)
            path.lineTo(size * 0.78, size * 0.22)
            path.lineTo(size * 0.56, c)
            path.lineTo(size * 0.78, size * 0.78)
            path.closeSubpath()
            painter.setBrush(QColor("#eaf6ff"))
            painter.drawPath(path)
        elif kind == "mic":
            painter.setBrush(QColor("#eaf6ff"))
            painter.drawRoundedRect(int(size * 0.38), int(size * 0.18), int(size * 0.24), int(size * 0.42), int(size * 0.12), int(size * 0.12))
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(int(c), int(size * 0.6), int(c), int(size * 0.82))
            painter.drawLine(int(size * 0.34), int(size * 0.82), int(size * 0.66), int(size * 0.82))
        elif kind == "mic_on":
            painter.setPen(QPen(QColor("#ffdce3"), max(2, size // 10)))
            painter.setBrush(QColor("#ff5a76"))
            painter.drawRoundedRect(int(size * 0.38), int(size * 0.18), int(size * 0.24), int(size * 0.42), int(size * 0.12), int(size * 0.12))
            painter.setPen(QPen(QColor("#ffdce3"), max(2, size // 12)))
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(int(c), int(size * 0.6), int(c), int(size * 0.82))
            painter.drawLine(int(size * 0.34), int(size * 0.82), int(size * 0.66), int(size * 0.82))
        elif kind in {"mic_record", "mic_record_on"}:
            color = QColor("#0a0a0a") if kind == "mic_record" else QColor("#111111")
            mic_pen = QPen(color, max(2, size // 9))
            mic_pen.setCapStyle(Qt.RoundCap)
            mic_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(mic_pen)
            painter.setBrush(Qt.NoBrush)

            capsule = QRectF(size * 0.34, size * 0.10, size * 0.32, size * 0.48)
            painter.drawRoundedRect(capsule, size * 0.16, size * 0.16)

            arc = QRectF(size * 0.20, size * 0.30, size * 0.60, size * 0.52)
            painter.drawArc(arc, 180 * 16, 180 * 16)

            painter.drawLine(QPointF(c, size * 0.72), QPointF(c, size * 0.92))
            painter.drawLine(QPointF(size * 0.34, size * 0.94), QPointF(size * 0.66, size * 0.94))
        elif kind == "copy":
            painter.drawRoundedRect(int(size * 0.28), int(size * 0.24), int(size * 0.34), int(size * 0.42), 3, 3)
            painter.drawRoundedRect(int(size * 0.38), int(size * 0.14), int(size * 0.34), int(size * 0.42), 3, 3)
        elif kind == "copy_ok":
            painter.drawLine(int(size * 0.25), int(c), int(size * 0.42), int(size * 0.72))
            painter.drawLine(int(size * 0.42), int(size * 0.72), int(size * 0.76), int(size * 0.3))
        elif kind == "minus":
            painter.drawLine(int(size * 0.28), int(c), int(size * 0.72), int(c))
        elif kind == "pencil":
            path = QPainterPath()
            path.moveTo(size * 0.25, size * 0.70)
            path.lineTo(size * 0.70, size * 0.25)
            path.lineTo(size * 0.78, size * 0.33)
            path.lineTo(size * 0.33, size * 0.78)
            path.closeSubpath()
            painter.setBrush(QColor("#eaf6ff"))
            painter.drawPath(path)
        elif kind == "open":
            folder_pen = QPen(QColor("#f2fbff"), max(3, size // 8))
            folder_pen.setCapStyle(Qt.RoundCap)
            folder_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(folder_pen)
            painter.drawRoundedRect(int(size * 0.16), int(size * 0.36), int(size * 0.58), int(size * 0.38), 4, 4)
            painter.drawLine(int(size * 0.2), int(size * 0.36), int(size * 0.36), int(size * 0.24))
            painter.drawLine(int(size * 0.36), int(size * 0.24), int(size * 0.6), int(size * 0.24))
            arrow_pen = QPen(QColor("#8fd5ff"), max(3, size // 7))
            arrow_pen.setCapStyle(Qt.RoundCap)
            arrow_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(arrow_pen)
            painter.drawLine(int(size * 0.46), int(size * 0.18), int(size * 0.8), int(size * 0.18))
            painter.drawLine(int(size * 0.8), int(size * 0.18), int(size * 0.8), int(size * 0.52))
            painter.drawLine(int(size * 0.67), int(size * 0.39), int(size * 0.8), int(size * 0.52))
            painter.drawLine(int(size * 0.93), int(size * 0.39), int(size * 0.8), int(size * 0.52))
        elif kind == "download":
            down_pen = QPen(QColor("#f2fbff"), max(3, size // 8))
            down_pen.setCapStyle(Qt.RoundCap)
            down_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(down_pen)
            painter.drawLine(int(c), int(size * 0.16), int(c), int(size * 0.56))
            painter.drawLine(int(size * 0.3), int(size * 0.42), int(c), int(size * 0.62))
            painter.drawLine(int(size * 0.7), int(size * 0.42), int(c), int(size * 0.62))
            tray_pen = QPen(QColor("#8fd5ff"), max(3, size // 9))
            tray_pen.setCapStyle(Qt.RoundCap)
            tray_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(tray_pen)
            painter.drawRoundedRect(int(size * 0.18), int(size * 0.72), int(size * 0.64), int(size * 0.14), 3, 3)
        elif kind == "gear":
            painter.setBrush(QColor("#eaf6ff"))
            painter.drawEllipse(QPointF(c, c), size * 0.16, size * 0.16)
            for ang in range(0, 360, 45):
                rad = math.radians(ang)
                x1 = c + math.cos(rad) * size * 0.18
                y1 = c + math.sin(rad) * size * 0.18
                x2 = c + math.cos(rad) * size * 0.32
                y2 = c + math.sin(rad) * size * 0.32
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        else:
            painter.drawEllipse(QPointF(c, c), size * 0.2, size * 0.2)

        painter.end()
        return QIcon(pix)

    def _on_gui_thread(self) -> bool:
        return QThread.currentThread() == self.thread()

    def _insert_chat_widget(self, widget: QWidget) -> None:
        self.chat_layout.insertWidget(max(0, self.chat_layout.count() - 1), widget)
        widget.show()
        widget.adjustSize()
        self.chat_layout.activate()
        self.chat_content.adjustSize()
        QTimer.singleShot(0, self._scroll_chat_to_bottom)
        QTimer.singleShot(50, self._scroll_chat_to_bottom)

    def _scroll_chat_to_bottom(self) -> None:
        barra = self.chat_scroll.verticalScrollBar()
        barra.setValue(barra.maximum())

    def _hex_to_rgb(self, cor: str) -> tuple[int, int, int]:
        cor = cor.lstrip("#")
        return int(cor[0:2], 16), int(cor[2:4], 16), int(cor[4:6], 16)

    def _rgb_to_hex(self, rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    @staticmethod
    def _mix_color(color_a: str, color_b: str, factor: float) -> str:
        factor = max(0.0, min(1.0, factor))
        ra, ga, ba = int(color_a[1:3], 16), int(color_a[3:5], 16), int(color_a[5:7], 16)
        rb, gb, bb = int(color_b[1:3], 16), int(color_b[3:5], 16), int(color_b[5:7], 16)
        r = int(ra + (rb - ra) * factor)
        g = int(ga + (gb - ga) * factor)
        b = int(ba + (bb - ba) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _gear_points(cx: float, cy: float, r_root: float, r_tip: float, teeth: int, angle_deg: float = 0.0, tooth_ratio: float = 0.58):
        points = []
        base = math.radians(angle_deg)
        pitch = (2.0 * math.pi) / max(teeth, 1)
        flat = pitch * max(0.35, min(0.8, tooth_ratio))
        flank = (pitch - flat) / 2.0
        for i in range(teeth):
            start = base + i * pitch
            a0, a1, a2, a3 = start, start + flank, start + flank + flat, start + pitch
            points.extend([cx + math.cos(a0) * r_root, cy + math.sin(a0) * r_root])
            points.extend([cx + math.cos(a1) * r_root, cy + math.sin(a1) * r_root])
            points.extend([cx + math.cos(a1) * r_tip, cy + math.sin(a1) * r_tip])
            points.extend([cx + math.cos(a2) * r_tip, cy + math.sin(a2) * r_tip])
            points.extend([cx + math.cos(a2) * r_root, cy + math.sin(a2) * r_root])
            points.extend([cx + math.cos(a3) * r_root, cy + math.sin(a3) * r_root])
        return points

    def _gear_path_qt(self, cx: float, cy: float, r_root: float, r_tip: float, teeth: int, angle_deg: float, tooth_ratio: float):
        pontos = self._gear_points(cx, cy, r_root, r_tip, teeth, angle_deg=angle_deg, tooth_ratio=tooth_ratio)
        if not pontos:
            return None
        path = QPainterPath(QPointF(pontos[0], pontos[1]))
        for i in range(2, len(pontos), 2):
            path.lineTo(QPointF(pontos[i], pontos[i + 1]))
        path.closeSubpath()
        return path

    def _paint_hud(self, painter: QPainter, w: int, h: int) -> None:
        painter.fillRect(0, 0, w, h, QColor("#071018"))
        p = max(0.0, min(1.0, self._blueprint_progress))
        pulse = 0.5 + 0.5 * math.sin(self._blueprint_pulse_phase)
        shimmer = 0.5 + 0.5 * math.sin(self._blueprint_shimmer_phase)

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor("#0a1218"))
        bg.setColorAt(1.0, QColor("#05090e"))
        painter.fillRect(0, 0, w, h, bg)

        step = 38
        offset_x = self._hud_grid_offset % step
        offset_y = (self._hud_grid_offset * 0.5) % step
        sweep_x = int(w * min(1.0, p * 1.1))
        sweep_y = int(h * min(1.0, p * 1.1))
        for x in range(-step, w + step, step):
            xx = x + offset_x
            if (sweep_x - xx) <= -step:
                continue
            major = (x // step) % 5 == 0
            a = int((88 if major else 52) + 18 * pulse)
            painter.setPen(QPen(QColor(58, 90, 118, a), 2 if major else 1))
            painter.drawLine(int(round(xx)), 0, int(round(xx)), h)
        for y in range(-step, h + step, step):
            yy = y + offset_y
            if (sweep_y - yy) <= -step:
                continue
            major = (y // step) % 5 == 0
            a = int((88 if major else 52) + 18 * pulse)
            painter.setPen(QPen(QColor(58, 90, 118, a), 2 if major else 1))
            painter.drawLine(0, int(round(yy)), w, int(round(yy)))

        center_x, center_y = w / 2, h / 2
        base = min(w, h) * 0.24

        def draw_gear_layer(
            cx: float,
            cy: float,
            r_root: float,
            r_tip: float,
            teeth: int,
            angle: float,
            grad_a: QColor,
            grad_b: QColor,
            rim_color: QColor,
            shadow_dx: float = 8.0,
            shadow_dy: float = 10.0,
            outer_glow: bool = False,
        ) -> None:
            r_root = max(12.0, r_root)
            r_tip = max(r_root * 1.03, min(r_tip, r_root * 1.07))
            path = self._gear_path_qt(cx, cy, r_root, r_tip, teeth, angle, 0.22)
            if path is None:
                return
            shadow = self._gear_path_qt(cx + shadow_dx, cy + shadow_dy, r_root, r_tip, teeth, angle, 0.22)
            if shadow is not None:
                painter.fillPath(shadow, QColor(5, 12, 20, 145))

            grad = QRadialGradient(QPointF(cx - r_root * 0.25, cy - r_root * 0.3), max(r_tip, r_root) * 1.35)
            grad.setColorAt(0.0, grad_a)
            grad.setColorAt(0.45, QColor(self._mix_color(grad_a.name(), grad_b.name(), 0.35)))
            grad.setColorAt(1.0, grad_b)
            painter.fillPath(path, grad)
            painter.setPen(QPen(rim_color, 2))
            painter.drawPath(path)

            if outer_glow:
                painter.setPen(QPen(QColor(160, 220, 255, 70), 1))
                painter.drawPath(path)

            # polishing highlight
            painter.setPen(QPen(QColor(210, 225, 236, 55), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(int(cx - r_tip * 1.05), int(cy - r_tip * 1.05), int(r_tip * 2.1), int(r_tip * 2.1), 16 * 40, int(16 * 95))

        painter.setPen(QPen(QColor(84, 116, 138, 36), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(int(center_x - base * 2.05), int(center_y - base * 2.05), int(base * 4.1), int(base * 4.1), 16 * 20, int(16 * 220 * (0.38 + 0.48 * shimmer)))
        painter.drawArc(int(center_x - base * 1.52), int(center_y - base * 1.52), int(base * 3.04), int(base * 3.04), 16 * 220, int(16 * 92))
        painter.drawLine(int(center_x - base * 2.0), int(center_y), int(center_x - base * 1.32), int(center_y))
        painter.drawLine(int(center_x + base * 1.32), int(center_y), int(center_x + base * 2.0), int(center_y))

        draw_gear_layer(
            center_x,
            center_y + 10,
            base + 12,
            base + 34,
            22,
            self._hud_angle_main * 0.85,
            QColor("#d4ebff"),
            QColor("#6a8a9c"),
            QColor("#9dbad0"),
            shadow_dx=12,
            shadow_dy=14,
            outer_glow=True,
        )
        draw_gear_layer(
            center_x + base * 1.16,
            center_y - base * 0.30,
            base * 0.34,
            base * 0.44,
            14,
            -self._hud_angle_main * 1.45,
            QColor("#c6d6e1"),
            QColor("#4a6374"),
            QColor("#86a3b5"),
            shadow_dx=8,
            shadow_dy=9,
        )
        draw_gear_layer(
            center_x - base * 1.04,
            center_y + base * 0.40,
            base * 0.30,
            base * 0.40,
            12,
            self._hud_angle_main * 1.6,
            QColor("#b6c9d5"),
            QColor("#394b59"),
            QColor("#768b99"),
            shadow_dx=7,
            shadow_dy=8,
        )

        inner = self._gear_path_qt(center_x, center_y, base - 58, base - 18, 16, self._hud_angle_inner, 0.20)
        if inner is not None:
            inner_grad = QRadialGradient(QPointF(center_x - base * 0.10, center_y - base * 0.10), base * 0.92)
            inner_grad.setColorAt(0.0, QColor("#d4f1ff"))
            inner_grad.setColorAt(0.48, QColor("#7f9bb0"))
            inner_grad.setColorAt(1.0, QColor("#17212a"))
            painter.fillPath(inner, inner_grad)
            painter.setPen(QPen(QColor("#aee6ff"), 2))
            painter.drawPath(inner)

        core_shadow = QRadialGradient(QPointF(center_x - base * 0.10, center_y - base * 0.10), base * 0.70)
        core_shadow.setColorAt(0.0, QColor(42, 60, 76, 248))
        core_shadow.setColorAt(0.6, QColor(18, 28, 36, 244))
        core_shadow.setColorAt(1.0, QColor(7, 12, 16, 255))
        painter.setBrush(core_shadow)
        core_outer = max(20.0, base - 44)
        core_inner = max(12.0, base - 62)
        painter.setPen(QPen(QColor("#a8d8f5"), 3))
        painter.drawEllipse(QPointF(center_x, center_y), core_outer, core_outer)
        painter.setPen(QPen(QColor("#4a6374"), 2))
        painter.drawEllipse(QPointF(center_x, center_y), core_inner, core_inner)

        for ang in range(0, 360, 45):
            rad = math.radians(ang + self._hud_angle_main * 0.22)
            bx = center_x + math.cos(rad) * (base + 4)
            by = center_y + math.sin(rad) * (base + 4)
            painter.setBrush(QColor("#c3e9ff"))
            painter.setPen(QPen(QColor("#7394aa"), 1))
            painter.drawEllipse(QPointF(bx, by), 4, 4)

        painter.setPen(QPen(QColor("#7fcfff"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(int(center_x - base - 36), int(center_y - base - 36), int((base + 36) * 2), int((base + 36) * 2), 16 * 18, int(16 * 124 * (0.5 + 0.5 * shimmer)))

        font = QFont("Segoe UI", max(16, int(base * 0.16)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(115, 226, 255))
        painter.drawText(QRectF(center_x - base - 14, center_y - 28, (base + 14) * 2, 56), int(Qt.AlignCenter), "A.L.T.A.I.R")
        small_font = QFont("Segoe UI", 11)
        small_font.setBold(False)
        painter.setFont(small_font)
        painter.setPen(QColor(146, 176, 196))
        painter.drawText(QRectF(center_x - base * 0.2, center_y - base * 1.28, base * 0.4, 24), int(Qt.AlignCenter), "90Â°")
        painter.drawText(QRectF(center_x - base * 0.2, center_y + base * 1.08, base * 0.4, 24), int(Qt.AlignCenter), "180Â°")
        painter.drawText(QRectF(center_x - base * 1.98, center_y - 14, 44, 24), int(Qt.AlignCenter), "90")
        painter.drawText(QRectF(center_x + base * 1.54, center_y - 14, 44, 24), int(Qt.AlignCenter), "30")

        if p > 0:
            scan_y = int((p * 1.4 % 1.0) * (h + 12)) - 6
            painter.setPen(QPen(QColor(120, 200, 255, 140), 1))
            painter.drawLine(0, scan_y, w, scan_y)

    def _atualizar_status(self) -> None:
        cpu = float(psutil.cpu_percent())
        ram = float(psutil.virtual_memory().percent)
        self.cpu_bar.setValue(int(round(cpu)))
        self.ram_bar.setValue(int(round(ram)))
        self.cpu_label.setText(f"{cpu:.1f}%")
        self.ram_label.setText(f"{ram:.1f}%")
        # Relogio lateral removido; mantemos apenas data/hora na barra inferior.
        if hasattr(self, "cpu_status"):
            self.cpu_status.setText("Estavel" if cpu < 70 else ("Moderado" if cpu < 90 else "Alto"))
        if hasattr(self, "ram_status"):
            self.ram_status.setText("Estavel" if ram < 65 else ("Moderado" if ram < 85 else "Alto"))
        if hasattr(self, "footer_datetime"):
            self.footer_datetime.setText(datetime.datetime.now().strftime("%d/%m/%Y  %H:%M"))

    def _animar_hud_visual(self) -> None:
        now = time.perf_counter()
        dt = max(0.001, min(0.06, now - self._hud_last_tick))
        self._hud_last_tick = now
        self._hud_dt_smoothed = self._hud_dt_smoothed * 0.82 + dt * 0.18
        anim_dt = self._hud_dt_smoothed

        if self.isMinimized() or not self.isVisible():
            self._hud_was_iconic = True
            self._hud_restore_hold_until = max(self._hud_restore_hold_until, now + 0.25)
            return
        if self._hud_was_iconic:
            self._hud_was_iconic = False
            self._hud_restore_hold_until = max(self._hud_restore_hold_until, now + 0.25)
        if now < self._hud_restore_hold_until:
            return

        self._blueprint_progress = min(1.0, self._blueprint_progress + anim_dt * 0.06)
        self._blueprint_pulse_phase += anim_dt * 1.15
        self._blueprint_shimmer_phase += anim_dt * 0.42

        self._hud_state = self._resolver_estado_hud()
        if hasattr(self, "hud_top_badge"):
            state_map = {
                "inactive": ("INATIVO", "#5f7f9d", "rgba(24, 37, 56, 220)", "rgba(86, 116, 152, 130)"),
                "listening": ("OUVINDO...", "#a379ff", "rgba(46, 28, 88, 220)", "rgba(140, 88, 255, 180)"),
                "processing": ("PROCESSANDO...", "#4ca2ff", "rgba(20, 52, 96, 220)", "rgba(82, 158, 255, 180)"),
                "responding": ("RESPONDENDO...", "#2dd8b2", "rgba(16, 64, 66, 220)", "rgba(56, 220, 184, 180)"),
            }
            txt, cor, bg, border = state_map.get(self._hud_state, state_map["inactive"])
            self.hud_top_badge.setText(txt)
            self.hud_top_badge.setStyleSheet(
                f"background: {bg}; border: 1px solid {border}; border-radius: 18px; "
                f"color: {cor}; font: 700 11pt 'Segoe UI'; padding: 8px 20px;"
            )

        target_level = max(0.0, min(1.0, self._hud_audio_level_target))
        attack = 1.0 - math.exp(-14.0 * anim_dt)
        release = 1.0 - math.exp(-4.8 * anim_dt)
        if target_level >= self._hud_audio_level:
            self._hud_audio_level += (target_level - self._hud_audio_level) * attack
        else:
            self._hud_audio_level += (target_level - self._hud_audio_level) * release
        if self._hud_state != "listening":
            self._hud_audio_level *= max(0.0, 1.0 - anim_dt * 3.2)
        if self._hud_audio_level < 0.002:
            self._hud_audio_level = 0.0
        self._hud_audio_level_target *= max(0.0, 1.0 - anim_dt * 4.4)
        if self._hud_audio_level_target < 0.002:
            self._hud_audio_level_target = 0.0

        # Suaviza a intensidade base da waveform para evitar "salto" entre estados.
        wave_target_map = {
            "inactive": 0.16,
            "listening": 0.32,
            "processing": 0.54,
            "responding": 0.64,
        }
        wave_target = wave_target_map.get(self._hud_state, 0.20)
        wave_target += self._hud_audio_level * (0.35 if self._hud_state == "listening" else 0.10)
        wave_target = max(0.12, min(1.0, wave_target))
        wave_mix = 1.0 - math.exp(-3.8 * anim_dt)
        self._hud_wave_intensity += (wave_target - self._hud_wave_intensity) * wave_mix
        self._hud_wave_intensity = max(0.12, min(1.0, self._hud_wave_intensity))

        state_speed = {
            "inactive": (16.0, 22.0, 9.0),
            "listening": (36.0, 66.0, 13.0),
            "processing": (90.0, 150.0, 18.0),
            "responding": (52.0, 96.0, 15.0),
        }
        main_speed, inner_speed, grid_speed = state_speed.get(self._hud_state, state_speed["inactive"])
        level_boost = 1.0 + self._hud_audio_level * 0.9
        self._hud_angle_main = (self._hud_angle_main + anim_dt * main_speed * level_boost) % 360.0
        self._hud_angle_inner = (self._hud_angle_inner - anim_dt * inner_speed * level_boost) % 360.0
        self._hud_grid_offset += anim_dt * grid_speed

        if self._hud_state == "responding":
            self._hud_response_wave = (self._hud_response_wave + anim_dt * 0.95) % 1.0
        else:
            self._hud_response_wave = max(0.0, self._hud_response_wave - anim_dt * 0.75)
        self._gear_spinning = self._hud_state in {"processing", "responding"}
        self.hud_widget.update()

    def _chat_label(self, parent: QWidget) -> QLabel:
        label = QLabel("", parent)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        label.setFont(QFont("Segoe UI", 11))
        label.setStyleSheet("background: transparent; border: none; color: #f4f8ff;")
        return label

    def _texto_para_html_chat(self, texto: str) -> str:
        texto = str(texto or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not texto:
            return ""
        linhas = texto.split("\n")
        partes: list[str] = []
        em_codigo = False
        codigo: list[str] = []

        def fechar_codigo() -> None:
            if not codigo:
                return
            bloco = html_lib.escape("\n".join(codigo))
            bloco = bloco.replace("  ", "&nbsp;&nbsp;").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
            partes.append(
                "<div style='margin: 8px 0 8px 0; padding: 10px 12px; "
                "background: rgba(8, 12, 18, 0.92); border: 1px solid rgba(120, 144, 176, 0.28); "
                "border-radius: 12px; font-family: Consolas, \"Courier New\", monospace; "
                "font-size: 10.5pt; line-height: 1.45; white-space: pre-wrap; color: #eef7ff;'>"
                + bloco
                + "</div>"
            )
            codigo.clear()

        for linha in linhas:
            limpa = linha.strip()
            if limpa.startswith("```"):
                if em_codigo:
                    fechar_codigo()
                    em_codigo = False
                else:
                    em_codigo = True
                continue

            if em_codigo:
                codigo.append(linha)
                continue

            if not limpa:
                partes.append("\n")
                continue

            m_lista = re.match(r"^([-*•]|\d+\.)\s+(.*)$", limpa)
            if m_lista:
                partes.append("• " + html_lib.escape(m_lista.group(2)) + "\n")
                continue

            partes.append(html_lib.escape(limpa) + "\n")

        if em_codigo:
            fechar_codigo()

        if not partes:
            partes.append(html_lib.escape(texto))

        return (
            "<div style='color: #f4f8ff; font-family: Segoe UI; font-size: 11pt; line-height: 1.35; "
            "white-space: pre-wrap;'>"
            + "".join(partes)
            + "</div>"
        )

    def _add_message_widget(self, texto: str, autor: str = "ia", animar: bool = True, file_path: Optional[str] = None) -> QWidget:
        container = QFrame(self.chat_content)
        container.setStyleSheet("background: transparent;")
        row = QHBoxLayout(container)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(0)

        bubble = QFrame(container)
        bubble.setObjectName("messageBubble")
        viewport_width = self.chat_scroll.viewport().width() or 1120
        bubble_width = max(260, min(620, viewport_width - 52))
        bubble.setMaximumWidth(bubble_width)
        bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        if autor == "usuario":
            bubble.setStyleSheet(
                """
                QFrame#messageBubble {
                    background: rgba(22, 70, 158, 214);
                    border: 1px solid rgba(85, 162, 255, 150);
                    border-radius: 16px;
                }
                """
            )
        else:
            bubble.setStyleSheet(
                """
                QFrame#messageBubble {
                    background: rgba(13, 28, 48, 228);
                    border: 1px solid rgba(70, 118, 168, 98);
                    border-radius: 16px;
                }
                """
            )
        bubble_effect = QGraphicsDropShadowEffect(bubble)
        if autor == "usuario":
            bubble_effect.setBlurRadius(14)
            bubble_effect.setOffset(0, 4)
            bubble_effect.setColor(QColor(0, 0, 0, 92))
        else:
            bubble_effect.setBlurRadius(12)
            bubble_effect.setOffset(0, 4)
            bubble_effect.setColor(QColor(0, 0, 0, 80))
        bubble.setGraphicsEffect(bubble_effect)
        bubble_layout = QVBoxLayout(bubble)
        if autor == "usuario":
            bubble_layout.setContentsMargins(14, 10, 14, 10)
            bubble_layout.setSpacing(4)
        else:
            bubble_layout.setContentsMargins(14, 10, 14, 10)
            bubble_layout.setSpacing(4)

        label = self._chat_label(bubble)
        label.setTextFormat(Qt.PlainText)
        label.setStyleSheet(
            "background: transparent; border: none; color: #f4f8ff; font-size: 11pt;"
            if autor == "usuario"
            else "background: transparent; border: none; color: #f4f8ff; font-size: 11.2pt;"
        )
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setWordWrap(True)
        label.setFixedWidth(max(240, bubble_width - 28))
        label.setText(texto)
        label.adjustSize()
        bubble_layout.addWidget(label)

        if file_path and os.path.exists(file_path):
            media = self._render_media(file_path, label.width(), bubble)
            bubble_layout.addWidget(media)

        if autor == "usuario":
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight)
        else:
            row.addWidget(bubble, 0, Qt.AlignLeft)
            row.addStretch(1)

        self._insert_chat_widget(container)
        label.adjustSize()
        bubble.adjustSize()
        container.adjustSize()
        self.chat_content.adjustSize()
        return container

    def _render_media(self, file_path: str, largura_max: int, parent: QWidget) -> QWidget:
        file_path = os.path.abspath(file_path)
        nome = os.path.basename(file_path)
        frame = QFrame(parent)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        preview = QLabel(nome, frame)
        preview.setWordWrap(True)
        preview.setStyleSheet("color: #d9ecff; font-size: 10.5pt;")
        layout.addWidget(preview)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)

        def abrir() -> None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

        def download() -> None:
            destino, _ = QFileDialog.getSaveFileName(self, "Salvar arquivo", nome, "Todos os arquivos (*)")
            if destino:
                try:
                    shutil.copyfile(file_path, destino)
                except Exception:
                    pass

        open_btn = QToolButton(frame)
        open_btn.setText("")
        open_btn.setIcon(self._icon_pixmap("open", 18))
        open_btn.setToolTip("Abrir arquivo")
        open_btn.clicked.connect(abrir)
        open_btn.setFixedSize(38, 38)
        dl_btn = QToolButton(frame)
        dl_btn.setText("")
        dl_btn.setIcon(self._icon_pixmap("download", 18))
        dl_btn.setToolTip("Salvar arquivo")
        dl_btn.setFixedSize(38, 38)
        dl_btn.clicked.connect(download)
        buttons.addWidget(open_btn)
        buttons.addWidget(dl_btn)
        buttons.addStretch(1)

        if os.path.splitext(nome)[1].lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            pix = QPixmap(file_path)
            if not pix.isNull():
                preview.setText("")
                preview.setPixmap(pix.scaled(largura_max, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return frame

    def _mostrar_digitando_impl(self) -> None:
        if self._typing_widget is not None:
            return
        container = QFrame(self.chat_content)
        container.setStyleSheet("background: transparent;")
        row = QHBoxLayout(container)
        row.setContentsMargins(10, 2, 10, 2)
        bubble = QFrame(container)
        bubble.setStyleSheet("QFrame { background: #0f151d; border: 1px solid #314050; border-radius: 18px; }")
        bubble_effect = QGraphicsDropShadowEffect(bubble)
        bubble_effect.setBlurRadius(20)
        bubble_effect.setOffset(0, 6)
        bubble_effect.setColor(QColor(0, 0, 0, 125))
        bubble.setGraphicsEffect(bubble_effect)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(16, 10, 16, 10)
        self._typing_label = QLabel("...", bubble)
        self._typing_label.setStyleSheet("color: #c9d8ff; font: 700 17px 'Segoe UI';")
        bubble_layout.addWidget(self._typing_label)
        row.addWidget(bubble)
        row.addStretch(1)
        self._typing_widget = container
        self._insert_chat_widget(container)
        self._typing_index = 0
        self._typing_timer = QTimer(container)

        def tick() -> None:
            if not self._typing_label:
                return
            dots = ["...", "..", "."]
            self._typing_label.setText(dots[self._typing_index % 3])
            self._typing_index += 1

        self._typing_timer.timeout.connect(tick)
        self._typing_timer.start(400)
        tick()

    def _remover_digitando_impl(self) -> None:
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer.deleteLater()
            self._typing_timer = None
        if self._typing_widget is not None:
            self._typing_widget.deleteLater()
            self._typing_widget = None
            self._typing_label = None

    def _set_ia_status_impl(self, texto: str) -> None:
        status_limpo = str(texto or "").replace("IA:", "").strip()
        self.ia_status_label.setText(status_limpo or "Pronta")
        if hasattr(self, "ia_value_label"):
            self.ia_value_label.setText("IA")

    @staticmethod
    def _estilo_card_rapido(hover: bool = False) -> str:
        if hover:
            return (
                "QFrame#quickCard { background: rgba(18, 37, 62, 236); "
                "border: 1px solid rgba(112, 188, 255, 170); border-radius: 14px; }"
            )
        return (
            "QFrame#quickCard { background: rgba(9, 17, 30, 228); "
            "border: 1px solid rgba(72, 125, 180, 96); border-radius: 14px; }"
        )

    def _mostrar_tutorial_popup(self, titulo: str, texto: str) -> None:
        dlg = QDialog(self)
        dlg.setModal(True)
        dlg.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dlg.setAttribute(Qt.WA_TranslucentBackground, True)
        dlg.setGeometry(self.frameGeometry())

        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        overlay = QFrame(dlg)
        overlay.setStyleSheet("background: rgba(2, 8, 16, 188);")
        root.addWidget(overlay)

        lay = QVBoxLayout(overlay)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(0)
        lay.addStretch(1)

        bubble = QFrame(overlay)
        bubble.setObjectName("tutorialBubble")
        bubble.setStyleSheet(
            "QFrame#tutorialBubble { background: rgba(8, 20, 36, 246); border: 1px solid rgba(92, 160, 232, 170); border-radius: 14px; }"
        )
        bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        bubble.setMinimumWidth(560)
        bubble.setMaximumWidth(760)
        bubble_shadow = QGraphicsDropShadowEffect(bubble)
        bubble_shadow.setBlurRadius(28)
        bubble_shadow.setOffset(0, 10)
        bubble_shadow.setColor(QColor(0, 0, 0, 190))
        bubble.setGraphicsEffect(bubble_shadow)

        bubble_l = QVBoxLayout(bubble)
        bubble_l.setContentsMargins(22, 18, 22, 14)
        bubble_l.setSpacing(10)

        title_lbl = QLabel(titulo, bubble)
        title_lbl.setStyleSheet("font: 700 13pt 'Segoe UI'; color: #d6efff;")
        bubble_l.addWidget(title_lbl)

        # Texto pode ficar grande (ex.: tutorial de comandos). Entao usamos um scroll
        # para nunca cortar o conteudo nem estourar a altura da janela.
        scroll = QScrollArea(bubble)
        scroll.setObjectName("tutorialScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea#tutorialScroll { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 0 2px 0; }"
            "QScrollBar::handle:vertical { background: rgba(92, 160, 232, 110); border-radius: 5px; min-height: 22px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(92, 160, 232, 150); }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

        scroll_host = QWidget(scroll)
        scroll_host.setStyleSheet("background: transparent;")
        scroll_l = QVBoxLayout(scroll_host)
        scroll_l.setContentsMargins(0, 0, 0, 0)
        scroll_l.setSpacing(0)

        text_lbl = QLabel(texto, scroll_host)
        text_lbl.setWordWrap(True)
        text_lbl.setMaximumWidth(680)
        text_lbl.setStyleSheet("font: 500 10.5pt 'Segoe UI'; color: #a8cbe5;")
        text_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        scroll_l.addWidget(text_lbl)
        scroll.setWidget(scroll_host)

        # Altura ideal (sem cortar) mas com limite pra nao ocupar a tela toda.
        max_h = int(dlg.height() * 0.42)
        max_h = max(220, min(520, max_h))
        rect_texto = text_lbl.fontMetrics().boundingRect(QRect(0, 0, 680, 6000), int(Qt.TextWordWrap), texto)
        ideal_h = min(rect_texto.height() + 10, max_h)
        scroll.setMaximumHeight(max_h)
        scroll.setMinimumHeight(max(140, ideal_h))

        bubble_l.addWidget(scroll)

        ok_row = QHBoxLayout()
        ok_row.addStretch(1)
        ok_btn = QPushButton("OK", bubble)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setFixedSize(92, 34)
        ok_btn.setStyleSheet(
            "QPushButton { background: rgba(30, 84, 150, 228); border: 1px solid rgba(122, 188, 255, 170); "
            "border-radius: 10px; color: #eaf6ff; font: 700 10pt 'Segoe UI'; }"
            "QPushButton:hover { background: rgba(44, 104, 176, 236); border-color: rgba(154, 210, 255, 190); }"
            "QPushButton:pressed { background: rgba(24, 68, 126, 236); }"
        )
        ok_btn.clicked.connect(dlg.accept)
        ok_row.addWidget(ok_btn)
        bubble_l.addLayout(ok_row)

        tail_row = QHBoxLayout()
        tail_row.setContentsMargins(0, 0, 0, 0)
        tail_row.setSpacing(0)
        tail_row.addSpacing(40)
        tail = QLabel("◢", overlay)
        tail.setStyleSheet("color: rgba(92, 160, 232, 210); font: 700 22px 'Segoe UI';")
        tail_row.addWidget(tail, 0, Qt.AlignTop)
        tail_row.addStretch(1)

        lay.addWidget(bubble, 0, Qt.AlignHCenter)
        lay.addLayout(tail_row)
        lay.addStretch(1)

        dlg.exec_()

    def _acao_card_rapido(self, acao: str) -> None:
        acao = (acao or "").strip().lower()
        if acao == "conversar":
            texto = (
                "Para enviar mensagens, digite no campo de texto na parte inferior direita e clique no botao de enviar."
            )
        elif acao == "falar":
            texto = (
                "O botao 'Voz: ligada' ativa ou desativa a fala do Altair nas respostas. "
                "Quando desligado, ele responde apenas por texto."
            )
        elif acao == "comandos":
            texto = (
                "Comandos disponiveis (com exemplos):\n"
                "\n"
                "Automatizar tarefas (macros):\n"
                "• executar tarefa NOME\n"
                "• rodar tarefa NOME 5x\n"
                "• reproduzir tarefa NOME 3 vezes\n"
                "• (atalho) digite apenas o NOME da tarefa salva\n"
                "Dica: durante a execucao, aperte ESC para parar.\n"
                "\n"
                "WhatsApp:\n"
                "• enviar mensagem para NOME dizendo TEXTO\n"
                "• enviar audio para NOME dizendo TEXTO\n"
                "• enviar esse arquivo para NOME dizendo LEGENDA (selecione o arquivo no botao +)\n"
                "\n"
                "Clima e mapas:\n"
                "• clima/tempo/previsao em CIDADE\n"
                "• distancia entre CIDADE_A e CIDADE_B (opcional: 'no mapa')\n"
                "\n"
                "Pesquisar e abrir:\n"
                "• pesquise por TEMA (pesquisa na internet)\n"
                "• abra NOME_DO_APP_OU_SITE\n"
                "• abra youtube e pesquise por TEMA\n"
                "• organizar a pasta de arquivos CAMINHO\n"
                "\n"
                "Matematica:\n"
                "• quanto e 25 vezes 7\n"
                "• derivada de x^2 + 3x\n"
                "• integral de x^2 de 0 a 2\n"
                "• raiz de 144 / fatorial de 6 / log de 100\n"
                "• seno/cosseno/tangente de 30\n"
                "• resolva a equacao: 2x + 3 = 0\n"
                "• raizes da equacao: x^2 - 5x + 6 = 0\n"
                "• sistema: x + y = 3 e x - y = 1\n"
                "\n"
                "Graficos:\n"
                "• grafico de f(x)=x^2 - 3x + 2\n"
                "• grafico de sen(x) de -6.28 a 6.28\n"
                "\n"
                "Fisica (gera grafico):\n"
                "• simular lancamento v0=20 angulo=45 altura=1\n"
                "• simular oscilacao amplitude=1 omega=2 fase=0 duracao=10\n"
                "\n"
                "CAD / 3D:\n"
                "• modelo 3d de um cubo 40mm com furo 10mm\n"
                "\n"
                "Formulas:\n"
                "• qual a formula de bhaskara?\n"
                "• lista de formulas"
            )
        else:
            texto = (
                "Sugestoes de comandos:\n"
                "• enviar mensagem para mãe dizendo cheguei em casa\n"
                "• abrir calculadora\n"
                "• enviar audio para pai dizendo bom dia\n"
                "• clima em Vitória Espírito Santo\n"
                "• distancia entre São Paulo e Belo Horizonte\n"
                "• abra youtube e pesquise por inteligencia artificial\n"
                "• calcule a integral de x ao quadrado\n"
                "• grafico de x^3\n"
                "• executar tarefa agendar alarme\n"
            )
        self._mostrar_tutorial_popup("Tutorial Altair", texto)

    def _limpar_chat(self) -> None:
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _resolver_estado_hud(self) -> str:
        if self._hud_responding:
            return "responding"
        if self._processing_count > 0:
            return "processing"
        # "OUVINDO..." so quando o usuario ativar explicitamente no botao.
        if self._ptt_active:
            return "listening"
        return "inactive"

    def _set_hud_state_impl(self, estado: str) -> None:
        estado_norm = (estado or "").strip().lower()
        if estado_norm not in {"inactive", "listening", "processing", "responding"}:
            estado_norm = "inactive"
        self._hud_state = estado_norm

    def _set_hud_audio_level_impl(self, nivel: float) -> None:
        n = max(0.0, min(1.0, float(nivel) * 140.0))
        self._hud_audio_level_target = n

    def _set_hud_responding_impl(self, ativo: bool) -> None:
        self._hud_responding = bool(ativo)
        self._hud_state = self._resolver_estado_hud()

    def _falar_com_estado(self, texto: str) -> None:
        self.set_hud_responding(True)
        try:
            self._speak_text(texto)
        finally:
            self.set_hud_responding(False)

    def _iniciar_audio_seguro(self) -> None:
        # Botao de audio:
        # - quando escuta continua esta ativa, ele so liga/desliga o "ouvindo" visual (PTT),
        #   sem parar o loop em background
        # - quando escuta continua esta desativada, ele inicia/para o loop de audio
        if self._ptt_active:
            # Desliga o "ouvindo" visual (mas pode manter o loop rodando).
            self._ptt_active = False
            self._hud_mic_active = False
            self._hud_state = self._resolver_estado_hud()
            self._atualizar_ui_microfone()
            set_wake = self._get_set_wake_enabled()
            if callable(set_wake):
                set_wake(False)
            self.set_ia_status("IA: Voz desativada")

            # Se nao for escuta continua, parar o loop de audio de verdade.
            if not getattr(self, "_continuous_listen_enabled", False):
                parar_loop_audio = self._get_parar_loop_audio()
                if callable(parar_loop_audio):
                    parar_loop_audio()
            return

        # Liga o "ouvindo" visual.
        self._ptt_active = True
        self._hud_mic_active = True
        self._hud_state = self._resolver_estado_hud()
        self._atualizar_ui_microfone()
        set_wake = self._get_set_wake_enabled()
        if callable(set_wake):
            set_wake(True)

        # Garante que o loop esteja rodando.
        if not self._continuous_listen_running:
            self._start_audio_loop_background()
        else:
            self.set_ia_status("IA: Aguardando wake word...")
        return

    def _start_audio_loop_background(self) -> None:
        # Start silencioso (usado para escuta continua ao iniciar / menu),
        # sem ligar o estado "ouvindo" visual.
        if self._continuous_listen_running or self._audio_starting:
            return
        self._audio_starting = True
        self.btn_voz.setEnabled(False)
        self.set_ia_status("IA: Iniciando escuta...")

        def start_bg() -> None:
            try:
                self._on_audio_start()
            except Exception as exc:
                self._bridge.show_error.emit(f"Falha ao iniciar audio: {exc}")
            finally:
                self._audio_starting = False
                self._bridge.set_mic_btn_enabled.emit(True)

        threading.Thread(target=start_bg, daemon=True).start()

    def _get_parar_loop_audio(self):
        try:
            from altair.core.audio_core import parar_loop_audio  # type: ignore

            return parar_loop_audio
        except Exception:
            try:
                from audio_core import parar_loop_audio  # type: ignore

                return parar_loop_audio
            except Exception:
                return None

    def _get_set_wake_enabled(self):
        try:
            from altair.core.audio_core import set_wake_enabled  # type: ignore

            return set_wake_enabled
        except Exception:
            try:
                from audio_core import set_wake_enabled  # type: ignore

                return set_wake_enabled
            except Exception:
                return None

    def _macro_imports(self):
        try:
            from altair.macro_cli import MacroPlayer, MacroRecorder, load_macro  # type: ignore

            return MacroPlayer, MacroRecorder, load_macro
        except Exception:
            try:
                from macro_cli import MacroPlayer, MacroRecorder, load_macro  # type: ignore

                return MacroPlayer, MacroRecorder, load_macro
            except Exception as exc:
                raise RuntimeError(str(exc)) from exc

    def _macro_dir(self) -> str:
        data_dir = os.path.abspath(os.getenv("ALTAIR_DATA_DIR", os.path.join(os.getcwd(), "data")))
        macro_dir = os.path.join(data_dir, "macros")
        os.makedirs(macro_dir, exist_ok=True)
        return macro_dir

    @staticmethod
    def _macro_sanitize_name(nome: str) -> str:
        nome = (nome or "").strip()
        nome = re.sub(r"\s+", " ", nome)
        # Mantem letras, numeros, espaco, underscore e hifen.
        safe = re.sub(r"[^0-9A-Za-z _\\-]", "", nome).strip()
        safe = safe.replace(" ", "_")
        return safe[:64] or "tarefa"

    def _macro_refresh_saved_list(self) -> None:
        if not hasattr(self, "_macro_saved_list") or self._macro_saved_list is None:
            return
        lst: QListWidget = self._macro_saved_list
        lst.clear()
        macro_dir = self._macro_dir()
        try:
            paths = sorted([p for p in os.listdir(macro_dir) if p.lower().endswith(".json")])
        except Exception:
            paths = []
        for fn in paths:
            nome_base = os.path.splitext(fn)[0]
            path = os.path.join(macro_dir, fn)

            item = QListWidgetItem()
            item.setData(Qt.UserRole, path)
            # Altura fixa pra acomodar o icone de lixeira.
            item.setSizeHint(QSize(10, 38))
            lst.addItem(item)

            row = QFrame(lst)
            row.setObjectName("macroRow")
            row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row.setStyleSheet(
                "QFrame#macroRow { background: transparent; border-radius: 10px; }"
                "QFrame#macroRow:hover { background: rgba(30, 84, 150, 70); }"
            )
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(10, 6, 10, 6)
            row_l.setSpacing(10)

            lbl = QLabel(nome_base.replace("_", " "), row)
            lbl.setMinimumWidth(0)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lbl.setStyleSheet("font: 600 10.3pt 'Segoe UI'; color: #eaf6ff;")
            row_l.addWidget(lbl, 1)

            trash = QToolButton(row)
            trash.setObjectName("macroTrashBtn")
            trash.setCursor(Qt.PointingHandCursor)
            trash.setIcon(self._icon_pixmap("trash", 16))
            trash.setIconSize(QSize(16, 16))
            trash.setFixedSize(30, 28)
            trash.setStyleSheet(
                "QToolButton#macroTrashBtn { background: rgba(16, 22, 31, 160); border: 1px solid rgba(93, 112, 136, 80); border-radius: 10px; }"
                "QToolButton#macroTrashBtn:hover { background: rgba(120, 54, 54, 200); border-color: rgba(255, 120, 120, 170); }"
            )
            trash.setToolTip("Apagar tarefa")
            trash.clicked.connect(lambda _=False, p=path: self._macro_delete_task(p))
            row_l.addWidget(trash, 0, Qt.AlignRight)

            # Por padrao, fica "inativo" (quase invisivel) e aparece no hover/scroll.
            trash.setVisible(False)
            row.enterEvent = (lambda _ev, b=trash: b.setVisible(True))
            row.leaveEvent = (lambda _ev, b=trash: self._macro_hide_trash_if_not_forced(b))

            lst.setItemWidget(item, row)

        self._macro_saved_run.setEnabled(lst.count() > 0)

    def _macro_selected_path(self) -> str:
        if not hasattr(self, "_macro_saved_list") or self._macro_saved_list is None:
            return ""
        item = self._macro_saved_list.currentItem()
        if not item:
            return ""
        path = item.data(Qt.UserRole)
        return str(path or "")

    def _macro_delete_task(self, path: str) -> None:
        path = str(path or "").strip()
        if not path:
            return
        nome = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
        resp = QMessageBox.question(
            self,
            "Apagar tarefa",
            f"Apagar a tarefa '{nome}'?\n\nEssa acao nao pode ser desfeita.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        try:
            os.remove(path)
        except Exception as exc:
            self._mostrar_erro_impl(f"Falha ao apagar tarefa: {exc}")
            return
        self._macro_refresh_saved_list()

    def _macro_show_all_trash_buttons_temporarily(self, ms: int = 1200) -> None:
        self._macro_trash_show_until = time.time() + max(0.2, ms / 1000.0)
        if not hasattr(self, "_macro_saved_list") or self._macro_saved_list is None:
            return
        lst: QListWidget = self._macro_saved_list
        for i in range(lst.count()):
            item = lst.item(i)
            w = lst.itemWidget(item)
            if not w:
                continue
            btn = w.findChild(QToolButton, "macroTrashBtn")
            if btn is not None:
                btn.setVisible(True)
        self._macro_trash_hide_timer.start(int(ms))

    def _macro_hide_trash_if_not_forced(self, btn: QToolButton) -> None:
        if time.time() < float(getattr(self, "_macro_trash_show_until", 0.0)):
            return
        try:
            btn.setVisible(False)
        except Exception:
            pass

    def _macro_hide_all_trash_buttons(self) -> None:
        if time.time() < float(getattr(self, "_macro_trash_show_until", 0.0)):
            return
        if not hasattr(self, "_macro_saved_list") or self._macro_saved_list is None:
            return
        lst: QListWidget = self._macro_saved_list
        for i in range(lst.count()):
            item = lst.item(i)
            w = lst.itemWidget(item)
            if not w:
                continue
            btn = w.findChild(QToolButton, "macroTrashBtn")
            if btn is not None:
                btn.setVisible(False)

    def _macro_find_saved_by_name(self, nome: str) -> str:
        """Resolve um nome digitado pelo usuario para um arquivo de macro salvo."""
        nome = (nome or "").strip()
        if not nome:
            return ""
        alvo = self._macro_sanitize_name(nome).lower()
        macro_dir = self._macro_dir()
        try:
            for fn in os.listdir(macro_dir):
                if not fn.lower().endswith(".json"):
                    continue
                base = os.path.splitext(fn)[0]
                if base.lower() == alvo:
                    return os.path.join(macro_dir, fn)
        except Exception:
            return ""
        return ""

    @staticmethod
    def _extrair_repeticoes(texto: str) -> int:
        # Exemplos aceitos: "3x", "x3", "3 vezes", "repetir 3", "repita 3"
        t = (texto or "").strip().lower()
        m = re.search(r"\b(\d{1,3})\s*(?:x|vezes)\b", t)
        if not m:
            m = re.search(r"\bx\s*(\d{1,3})\b", t)
        if not m:
            m = re.search(r"\b(?:repetir|repita|repete)\s+(\d{1,3})\b", t)
        if m:
            try:
                return max(1, min(999, int(m.group(1))))
            except Exception:
                return 1
        return 1

    def _macro_start_esc_listener(self) -> None:
        # ESC deve parar a gravacao mesmo fora de foco (captura global).
        try:
            from pynput import keyboard
        except Exception:
            return

        self._macro_stop_esc_listener()

        def on_press(key):
            try:
                if key == keyboard.Key.esc:
                    QTimer.singleShot(0, self._macro_stop_recording)
                    return False
            except Exception:
                return None
            return None

        self._macro_esc_listener = keyboard.Listener(on_press=on_press)
        self._macro_esc_listener.start()

    def _macro_stop_esc_listener(self) -> None:
        if self._macro_esc_listener is not None:
            try:
                self._macro_esc_listener.stop()
            except Exception:
                pass
        self._macro_esc_listener = None

    def _macro_start_recording(self) -> None:
        try:
            _MacroPlayer, MacroRecorder, _load_macro = self._macro_imports()
            self._macro_recorder = MacroRecorder(record_moves=True, move_interval_s=0.03)
            self._macro_recorder.start_recording()
            self._macro_recording = True
            self._macro_btn_start.setEnabled(False)
            self._macro_btn_stop.setEnabled(True)
            self._macro_run.setEnabled(False)
            self._macro_step.setText("Gravando... faça a tarefa agora.\\nAperte ESC ou clique em Parar gravacao para encerrar.")
            self._macro_start_esc_listener()
        except Exception as exc:
            self._mostrar_erro_impl(f"Falha ao iniciar gravacao: {exc}")

    def _macro_stop_recording(self) -> None:
        if not self._macro_recording:
            return
        self._macro_recording = False
        self._macro_stop_esc_listener()

        try:
            events = self._macro_recorder.stop_recording() if self._macro_recorder else []
        except Exception:
            events = []

        if not events:
            self._macro_step.setText("Gravacao vazia. Clique em Iniciar gravacao e tente novamente.")
            self._macro_btn_start.setEnabled(True)
            self._macro_btn_stop.setEnabled(False)
            return

        # Nome da tarefa
        sugestao = datetime.datetime.now().strftime("tarefa_%Y%m%d_%H%M%S")
        nome, ok = QInputDialog.getText(
            self,
            "Salvar tarefa",
            "Nome da tarefa automatizada:",
            QLineEdit.Normal,
            sugestao,
        )
        if not ok:
            self._macro_step.setText("Gravacao encerrada. (Nao salva) Escolha as repeticoes e clique em Executar.")
            self._macro_last_path = ""
        else:
            safe = self._macro_sanitize_name(nome)
            macro_path = os.path.join(self._macro_dir(), f"{safe}.json")
            try:
                self._macro_recorder.save(macro_path)
                self._macro_last_path = macro_path
            except Exception as exc:
                self._mostrar_erro_impl(f"Falha ao salvar macro: {exc}")
                self._macro_btn_start.setEnabled(True)
                self._macro_btn_stop.setEnabled(False)
                return
            self._macro_refresh_saved_list()

        self._macro_btn_start.setEnabled(True)
        self._macro_btn_stop.setEnabled(False)
        self._macro_run.setEnabled(True)
        self._macro_step.setText("Gravacao encerrada. Agora escolha quantas vezes repetir e clique em Executar.")

    def _macro_run_playback(self) -> None:
        if not self._macro_last_path:
            QMessageBox.information(self, "Automatizar tarefas", "Nenhuma tarefa gravada/salva ainda.")
            return
        rep = int(self._macro_rep.value())
        self._macro_run.setEnabled(False)
        self._macro_btn_start.setEnabled(False)
        self._macro_step.setText("Execucao iniciada.\\nAperte ESC para parar a execucao.")

        def play_bg() -> None:
            try:
                MacroPlayer, _MacroRecorder, load_macro = self._macro_imports()
                evs = load_macro(self._macro_last_path)
                player = MacroPlayer(failsafe_corner=True)
                player.play_macro(evs, repeticoes=rep, velocidade=1.0, log=False)
            except Exception as exc:
                self._bridge.show_error.emit(f"Falha ao reproduzir macro: {exc}")
            finally:
                QTimer.singleShot(0, lambda: self._macro_btn_start.setEnabled(True))
                QTimer.singleShot(0, lambda: self._macro_run.setEnabled(True))

        self._macro_player_thread = threading.Thread(target=play_bg, daemon=True)
        self._macro_player_thread.start()

    def _macro_run_saved(self) -> None:
        path = self._macro_selected_path()
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "Automatizar tarefas", "Selecione uma tarefa salva.")
            return
        rep = int(self._macro_saved_rep.value())
        self._macro_saved_run.setEnabled(False)
        self._macro_saved_info.setText("Execucao iniciada. Aperte ESC para parar.")

        def play_bg() -> None:
            try:
                MacroPlayer, _MacroRecorder, load_macro = self._macro_imports()
                evs = load_macro(path)
                player = MacroPlayer(failsafe_corner=True)
                player.play_macro(evs, repeticoes=rep, velocidade=1.0, log=False)
            except Exception as exc:
                self._bridge.show_error.emit(f"Falha ao reproduzir macro: {exc}")
            finally:
                QTimer.singleShot(0, lambda: self._macro_saved_run.setEnabled(True))
                QTimer.singleShot(0, lambda: self._macro_saved_info.setText("Dica: aperte ESC para parar a execucao."))

        threading.Thread(target=play_bg, daemon=True).start()

    def _set_mic_button_enabled_impl(self, enabled: bool) -> None:
        try:
            self.btn_voz.setEnabled(bool(enabled))
        except Exception:
            pass

    def _maybe_start_continuous_listen(self) -> None:
        # Evita iniciar se o usuario desativou a opcao no menu.
        if getattr(self, "_continuous_listen_enabled", False):
            self._start_audio_loop_background()
            set_wake = self._get_set_wake_enabled()
            if callable(set_wake):
                set_wake(True)

    def _toggle_continuous_listen(self, checked: bool) -> None:
        self._continuous_listen_enabled = bool(checked)
        if checked:
            self.set_ia_status("IA: Escuta continua ativada")
            QTimer.singleShot(150, self._start_audio_loop_background)
        else:
            # Desativa auto-inicio. O botao de audio continua permitindo iniciar/parar.
            self.set_ia_status("IA: Escuta continua desativada")

    def _abrir_macro_menu(self) -> None:
        if self._macro_dialog is not None:
            try:
                self._macro_dialog.raise_()
                self._macro_dialog.activateWindow()
            except Exception:
                pass
            return

        dlg = QDialog(self)
        dlg.setModal(False)
        dlg.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dlg.setAttribute(Qt.WA_TranslucentBackground, True)
        dlg.setFixedWidth(560)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        overlay = QFrame(dlg)
        overlay.setStyleSheet("background: rgba(2, 8, 16, 188);")
        root.addWidget(overlay)

        lay = QVBoxLayout(overlay)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(0)
        lay.addStretch(1)

        box = QFrame(overlay)
        box.setObjectName("macroBox")
        # Importante: usar seletor para nao aplicar borda nos filhos (labels ficavam com "margens/linhas").
        box.setStyleSheet(
            "QFrame#macroBox { background: rgba(8, 20, 36, 246); border: 1px solid rgba(92, 160, 232, 170); border-radius: 14px; }"
        )
        box_shadow = QGraphicsDropShadowEffect(box)
        box_shadow.setBlurRadius(28)
        box_shadow.setOffset(0, 10)
        box_shadow.setColor(QColor(0, 0, 0, 190))
        box.setGraphicsEffect(box_shadow)
        lay.addWidget(box, 0, Qt.AlignHCenter)
        lay.addStretch(1)

        box_l = QVBoxLayout(box)
        box_l.setContentsMargins(18, 16, 18, 14)
        box_l.setSpacing(10)

        title = QLabel("Automatizar tarefas", box)
        title.setStyleSheet("font: 800 13pt 'Segoe UI'; color: #d6efff;")
        box_l.addWidget(title)

        tabs = QTabWidget(box)
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 0; }"
            "QTabBar::tab { background: rgba(6, 12, 20, 230); color: rgba(210, 230, 245, 200); padding: 8px 14px; border-radius: 10px; margin-right: 8px; }"
            "QTabBar::tab:selected { background: rgba(30, 84, 150, 210); color: #eaf6ff; }"
        )
        box_l.addWidget(tabs)

        tab_record = QWidget(tabs)
        tab_saved = QWidget(tabs)
        tabs.addTab(tab_record, "Gravar")
        tabs.addTab(tab_saved, "Tarefas salvas")

        # -------- Tab gravacao --------
        rec_l = QVBoxLayout(tab_record)
        rec_l.setContentsMargins(0, 0, 0, 0)
        rec_l.setSpacing(10)

        self._macro_step = QLabel(
            "1. Clique em Iniciar gravacao e faça a tarefa.\n2. Clique em Parar gravacao (ou aperte ESC).",
            tab_record,
        )
        self._macro_step.setWordWrap(True)
        self._macro_step.setStyleSheet("font: 500 10.5pt 'Segoe UI'; color: #a8cbe5;")
        rec_l.addWidget(self._macro_step)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._macro_btn_start = QPushButton("Iniciar gravacao", tab_record)
        self._macro_btn_stop = QPushButton("Parar gravacao", tab_record)
        self._macro_btn_stop.setEnabled(False)
        for b in (self._macro_btn_start, self._macro_btn_stop):
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(34)
            b.setStyleSheet(
                "QPushButton { background: rgba(30, 84, 150, 228); border: 1px solid rgba(122, 188, 255, 170); "
                "border-radius: 10px; color: #eaf6ff; font: 700 10pt 'Segoe UI'; padding: 0 14px; }"
                "QPushButton:hover { background: rgba(44, 104, 176, 236); border-color: rgba(154, 210, 255, 190); }"
                "QPushButton:disabled { background: rgba(18, 32, 48, 220); border-color: rgba(90, 120, 150, 80); color: rgba(200, 220, 238, 120); }"
            )
        btn_row.addWidget(self._macro_btn_start)
        btn_row.addWidget(self._macro_btn_stop)
        btn_row.addStretch(1)
        rec_l.addLayout(btn_row)

        rep_row = QHBoxLayout()
        rep_row.setSpacing(10)
        self._macro_rep_lbl = QLabel("Repetir:", tab_record)
        self._macro_rep_lbl.setStyleSheet("font: 700 10.5pt 'Segoe UI'; color: #cfe5f7;")
        self._macro_rep = QSpinBox(tab_record)
        self._macro_rep.setRange(1, 999)
        self._macro_rep.setValue(1)
        self._macro_rep.setFixedHeight(32)
        self._macro_rep.setStyleSheet(
            "QSpinBox { background: rgba(6, 12, 20, 230); color: #eaf6ff; border: 1px solid rgba(92, 160, 232, 110); border-radius: 10px; padding: 4px 10px; }"
        )
        self._macro_run = QPushButton("Executar", tab_record)
        self._macro_run.setCursor(Qt.PointingHandCursor)
        self._macro_run.setFixedHeight(34)
        self._macro_run.setEnabled(False)
        self._macro_run.setStyleSheet(
            "QPushButton { background: rgba(45, 150, 110, 210); border: 1px solid rgba(80, 220, 170, 180); "
            "border-radius: 10px; color: #eaf6ff; font: 800 10pt 'Segoe UI'; padding: 0 14px; }"
            "QPushButton:hover { background: rgba(52, 176, 128, 230); }"
            "QPushButton:disabled { background: rgba(18, 32, 48, 220); border-color: rgba(90, 120, 150, 80); color: rgba(200, 220, 238, 120); }"
        )
        rep_row.addWidget(self._macro_rep_lbl)
        rep_row.addWidget(self._macro_rep)
        rep_row.addStretch(1)
        rep_row.addWidget(self._macro_run)
        rec_l.addLayout(rep_row)

        self._macro_hint = QLabel("Dica: durante a execucao, aperte ESC para parar.", tab_record)
        self._macro_hint.setWordWrap(True)
        self._macro_hint.setStyleSheet("font: 500 10pt 'Segoe UI'; color: rgba(168, 203, 229, 190);")
        rec_l.addWidget(self._macro_hint)

        # -------- Tab salvas --------
        sav_l = QVBoxLayout(tab_saved)
        sav_l.setContentsMargins(0, 0, 0, 0)
        sav_l.setSpacing(10)

        self._macro_saved_list = QListWidget(tab_saved)
        self._macro_saved_list.setStyleSheet(
            "QListWidget { background: rgba(6, 12, 20, 230); color: #eaf6ff; border: 1px solid rgba(92, 160, 232, 90); border-radius: 12px; padding: 6px; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 10px; }"
            "QListWidget::item:selected { background: rgba(30, 84, 150, 200); }"
        )
        sav_l.addWidget(self._macro_saved_list, 1)

        sav_row = QHBoxLayout()
        sav_row.setSpacing(10)
        sav_lbl = QLabel("Repetir:", tab_saved)
        sav_lbl.setStyleSheet("font: 700 10.5pt 'Segoe UI'; color: #cfe5f7;")
        self._macro_saved_rep = QSpinBox(tab_saved)
        self._macro_saved_rep.setRange(1, 999)
        self._macro_saved_rep.setValue(1)
        self._macro_saved_rep.setFixedHeight(32)
        self._macro_saved_rep.setStyleSheet(
            "QSpinBox { background: rgba(6, 12, 20, 230); color: #eaf6ff; border: 1px solid rgba(92, 160, 232, 110); border-radius: 10px; padding: 4px 10px; }"
        )
        self._macro_saved_run = QPushButton("Executar", tab_saved)
        self._macro_saved_run.setCursor(Qt.PointingHandCursor)
        self._macro_saved_run.setFixedHeight(34)
        self._macro_saved_run.setEnabled(False)
        self._macro_saved_run.setStyleSheet(self._macro_run.styleSheet())
        sav_row.addWidget(sav_lbl)
        sav_row.addWidget(self._macro_saved_rep)
        sav_row.addStretch(1)
        sav_row.addWidget(self._macro_saved_run)
        sav_l.addLayout(sav_row)

        self._macro_saved_info = QLabel("Dica: aperte ESC para parar a execucao.", tab_saved)
        self._macro_saved_info.setWordWrap(True)
        self._macro_saved_info.setStyleSheet("font: 500 10pt 'Segoe UI'; color: rgba(168, 203, 229, 190);")
        sav_l.addWidget(self._macro_saved_info)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Fechar", box)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(92, 34)
        close_btn.setStyleSheet(
            "QPushButton { background: rgba(16, 22, 31, 220); border: 1px solid rgba(93, 112, 136, 85); "
            "border-radius: 10px; color: #eaf6ff; font: 700 10pt 'Segoe UI'; }"
            "QPushButton:hover { background: rgba(24, 31, 42, 228); border-color: rgba(124, 145, 170, 110); }"
        )
        close_btn.clicked.connect(dlg.close)
        close_row.addWidget(close_btn)
        box_l.addLayout(close_row)

        self._macro_btn_start.clicked.connect(self._macro_start_recording)
        self._macro_btn_stop.clicked.connect(self._macro_stop_recording)
        self._macro_run.clicked.connect(self._macro_run_playback)
        self._macro_saved_run.clicked.connect(self._macro_run_saved)
        self._macro_saved_list.currentItemChanged.connect(lambda *_: self._macro_saved_run.setEnabled(bool(self._macro_selected_path())))
        try:
            self._macro_saved_list.viewport().installEventFilter(self)
            self._macro_saved_list.verticalScrollBar().valueChanged.connect(lambda _v: self._macro_show_all_trash_buttons_temporarily(900))
        except Exception:
            pass
        self._macro_refresh_saved_list()

        def on_close(_ev):
            self._macro_dialog = None
            try:
                self._macro_stop_esc_listener()
            except Exception:
                pass

        dlg.closeEvent = on_close
        self._macro_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _atualizar_botao_microfone_impl(self, ativo: bool) -> None:
        # "ativo" aqui significa loop de audio rodando, nao necessariamente UI ouvindo.
        self._continuous_listen_running = bool(ativo)
        if not self._continuous_listen_running:
            # Se o loop parou, derruba o "ouvindo" visual tambem.
            self._ptt_active = False
            self._hud_mic_active = False
        self._hud_state = self._resolver_estado_hud()
        self._atualizar_ui_microfone()

    def _atualizar_ui_microfone(self) -> None:
        # Botao e labels do painel lateral seguem o estado visual (PTT), nao o loop em background.
        self.btn_voz.setText("")

        if self._ptt_active:
            self.btn_voz.setIcon(self._icon_pixmap("mic_record_on", 20))
            self.btn_voz.setStyleSheet(
                "background: #f2a9b4; border: 1px solid #da7a88; border-radius: 12px;"
            )
            self.btn_voz.setToolTip("Desativar audio")
            self.mic_status_label.setText("Ativo")
            if hasattr(self, "mic_value_label"):
                self.mic_value_label.setText("Escutando")
            return

        # PTT desligado: se o loop estiver rodando (escuta continua), fica em "Pronto/Em espera"
        # sem mostrar "ouvindo". Se nem loop estiver rodando, fica "Inativo".
        self.btn_voz.setIcon(self._icon_pixmap("mic_record", 20))
        if self._continuous_listen_running:
            self.btn_voz.setStyleSheet(
                "background: rgba(32, 44, 62, 234); border: 1px solid rgba(156, 205, 255, 132); border-radius: 12px;"
            )
            self.btn_voz.setToolTip("Ativar audio")
            self.mic_status_label.setText("Ativo")
            if hasattr(self, "mic_value_label"):
                self.mic_value_label.setText("Em espera")
        else:
            self.btn_voz.setStyleSheet(
                "background: #d8d8d8; border: 1px solid #bdbdbd; border-radius: 12px;"
            )
            self.btn_voz.setToolTip("Ativar audio")
            self.mic_status_label.setText("Inativo")
            if hasattr(self, "mic_value_label"):
                self.mic_value_label.setText("Aguardando")

    def _atualizar_botao_falar_impl(self, ativo: bool) -> None:
        self.btn_falar.setText("Voz: ligada" if ativo else "Voz: desligada")
        self.btn_falar.setIcon(self._icon_pixmap("mic_on" if ativo else "mic", 16))
        self.btn_falar.setToolTip("Desativar fala da resposta" if ativo else "Ativar fala da resposta")
        if ativo:
            self.btn_falar.setStyleSheet(
                """
                QToolButton {
                    background: rgba(32, 44, 62, 234);
                    color: #e5f3ff;
                    border: 1px solid rgba(156, 205, 255, 132);
                    border-radius: 12px;
                    padding: 6px 12px;
                    font-size: 9pt;
                    font-weight: 700;
                }
                QToolButton:hover {
                    background: rgba(40, 56, 78, 238);
                    border-color: rgba(176, 221, 255, 150);
                }
                """
            )
        else:
            self.btn_falar.setStyleSheet(
                """
                QToolButton {
                    background: rgba(16, 22, 31, 220);
                    color: #aab9c8;
                    border: 1px solid rgba(93, 112, 136, 85);
                    border-radius: 12px;
                    padding: 6px 12px;
                    font-size: 9pt;
                    font-weight: 600;
                }
                QToolButton:hover {
                    background: rgba(24, 31, 42, 228);
                    border-color: rgba(124, 145, 170, 110);
                }
                """
            )

    def _paint_hud(self, painter: QPainter, w: int, h: int) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor("#040a14"))
        bg.setColorAt(0.55, QColor("#030915"))
        bg.setColorAt(1.0, QColor("#02050d"))
        painter.fillRect(0, 0, w, h, bg)

        # Grade sutil para aproximar o aspecto de "painel" futurista.
        step = 48
        grid_pen_minor = QPen(QColor(22, 68, 112, 26), 1)
        grid_pen_major = QPen(QColor(32, 98, 154, 34), 1)
        for x in range(0, w + 1, step):
            painter.setPen(grid_pen_major if (x // step) % 4 == 0 else grid_pen_minor)
            painter.drawLine(x, 0, x, h)
        for y in range(0, h + 1, step):
            painter.setPen(grid_pen_major if (y // step) % 4 == 0 else grid_pen_minor)
            painter.drawLine(0, y, w, y)

        center_x, center_y = w / 2.0, h / 2.0
        base = min(w, h) * 0.30
        self._draw_ai_core_overlay(painter, center_x, center_y, base)

    def _draw_ai_core_overlay(self, painter: QPainter, cx: float, cy: float, base: float) -> None:
        state = self._hud_state
        level = max(0.0, min(1.0, self._hud_audio_level))
        phase = self._blueprint_pulse_phase
        wave_phase = self._blueprint_shimmer_phase

        bg_halo = QRadialGradient(QPointF(cx, cy), base * 1.42)
        bg_halo.setColorAt(0.0, QColor(30, 134, 208, 74))
        bg_halo.setColorAt(0.42, QColor(20, 86, 146, 34))
        bg_halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_halo)
        painter.drawEllipse(QPointF(cx, cy), base * 1.42, base * 1.42)

        palette = {
            "inactive": QColor(92, 164, 212),
            "listening": QColor(76, 228, 255),
            "processing": QColor(112, 176, 255),
            "responding": QColor(102, 246, 234),
        }
        core_color = palette.get(state, QColor(92, 164, 212))

        outer_ring = base * 0.90
        inner_ring = base * 0.68
        ring_glow = QPen(QColor(core_color.red(), core_color.green(), core_color.blue(), 96), 2)
        painter.setPen(ring_glow)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), outer_ring, outer_ring)
        painter.setPen(QPen(QColor(core_color.red(), core_color.green(), core_color.blue(), 70), 1))
        painter.drawEllipse(QPointF(cx, cy), inner_ring, inner_ring)
        painter.setPen(QPen(QColor(core_color.red(), core_color.green(), core_color.blue(), 40), 1))
        for k in (1.22, 1.45, 1.72):
            painter.drawEllipse(QPointF(cx, cy), outer_ring * k, outer_ring * k)

        line_len = base * 1.92
        bars = 84
        base_gain = max(0.12, min(1.0, self._hud_wave_intensity))
        mic_gain = level * (0.75 if state == "listening" else 0.20)
        gain = max(0.12, min(1.0, base_gain + mic_gain))

        for i in range(bars + 1):
            t = (i / bars) * 2.0 - 1.0
            x = cx + t * line_len
            envelope = max(0.06, 1.0 - abs(t) ** 1.6)
            movement = abs(math.sin(wave_phase * 2.9 + i * 0.31))
            tone = 0.56 + 0.44 * abs(math.sin(phase * 2.1 + i * 0.14))
            h = base * 0.64 * envelope * gain * (0.33 + movement * 0.67) * tone
            h = max(2.0, h)

            a = int(74 + 146 * envelope)
            left = QColor(128, 84, 255, a)
            right = QColor(52, 246, 226, a)
            mix = (t + 1.0) * 0.5
            r = int(left.red() + (right.red() - left.red()) * mix)
            g = int(left.green() + (right.green() - left.green()) * mix)
            b = int(left.blue() + (right.blue() - left.blue()) * mix)
            pen = QPen(QColor(r, g, b, a), 2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, cy - h), QPointF(x, cy + h))

        painter.setPen(QPen(QColor(core_color.red(), core_color.green(), core_color.blue(), 130), 1))
        painter.drawLine(QPointF(cx - line_len, cy), QPointF(cx + line_len, cy))

        # Núcleo central com logo.
        core_r = base * 0.42
        core_grad = QRadialGradient(QPointF(cx - core_r * 0.20, cy - core_r * 0.24), core_r * 1.12)
        core_grad.setColorAt(0.0, QColor(130, 196, 255, 230))
        core_grad.setColorAt(0.34, QColor(32, 102, 190, 240))
        core_grad.setColorAt(0.78, QColor(8, 24, 58, 245))
        core_grad.setColorAt(1.0, QColor(4, 12, 32, 250))
        painter.setPen(QPen(QColor(126, 206, 255, 205), 2))
        painter.setBrush(core_grad)
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

        painter.setFont(QFont("Segoe UI", max(16, int(base * 0.12)), QFont.Bold))
        painter.setPen(QColor(103, 226, 255))
        painter.drawText(QRectF(cx - core_r, cy - 28, core_r * 2, 56), int(Qt.AlignCenter), "A.L.T.A.I.R")

    def _trazer_para_frente_impl(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)

    def _finalizar_resposta_impl(self, resultado: Any) -> None:
        self._remover_digitando_impl()
        self._processing_count = max(0, self._processing_count - 1)
        self._gear_spinning = self._processing_count > 0
        self._hud_state = self._resolver_estado_hud()
        if isinstance(resultado, dict):
            texto = (resultado.get("visual") or resultado.get("fala") or "").strip()
            arquivo = resultado.get("file") or resultado.get("arquivo")
            self.adicionar_mensagem(texto, "ia", file_path=arquivo)
        else:
            self.adicionar_mensagem(str(resultado), "ia")
        self.set_ia_status("IA: Pronta")

    def _mostrar_erro_impl(self, erro: str) -> None:
        self._remover_digitando_impl()
        self._processing_count = max(0, self._processing_count - 1)
        self._gear_spinning = self._processing_count > 0
        self._hud_state = self._resolver_estado_hud()
        self.adicionar_mensagem(f"[ERRO]: {erro}", "ia")
        self.set_ia_status("IA: Erro")

    def _atualizar_texto_startup(self, ativo: Optional[bool] = None) -> None:
        texto = "Iniciar com Windows" if ativo is None else ("Desativar inicio com Windows" if ativo else "Iniciar com Windows")
        self._action_startup.setText(texto)

    def _alternar_startup(self) -> None:
        if not self._on_toggle_startup:
            return
        try:
            resultado = self._on_toggle_startup()
        except Exception:
            resultado = None
        if isinstance(resultado, bool):
            self._atualizar_texto_startup(resultado)

    def _abrir_cadastro_apps(self) -> None:
        if self._on_open_apps_register:
            self._on_open_apps_register(self)

    def _abrir_conexao_remota(self) -> None:
        if self._on_open_remote_connect:
            self._on_open_remote_connect(self)

    def _abrir_config_llm(self) -> None:
        if self._on_open_llm_config:
            self._on_open_llm_config(self)

    def _abrir_config_voz(self) -> None:
        if self._on_open_voice_config:
            self._on_open_voice_config(self)

    def _selecionar_arquivo_envio(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, "Selecione um arquivo para enviar no WhatsApp")
        if not caminho:
            return
        self._on_file_selected(caminho)
        self.btn_attach.setToolTip(f"Anexar arquivo: {os.path.basename(caminho)}")

    def _enviar(self) -> None:
        comando = self.entry.toPlainText().strip()
        if not comando:
            return

        # Atalho: executar macro salva pelo nome (sem passar pelo LLM).
        # Exemplos:
        # - "executar tarefa NOME"
        # - "rodar tarefa NOME 5x"
        # - "NOME" (se bater exatamente com uma tarefa salva)
        cmd_norm = comando.strip()
        cmd_norm_low = cmd_norm.lower()
        nome_tarefa = ""
        if cmd_norm_low.startswith("executar tarefa "):
            nome_tarefa = cmd_norm[15:].strip()
        elif cmd_norm_low.startswith("rodar tarefa "):
            nome_tarefa = cmd_norm[12:].strip()
        elif cmd_norm_low.startswith("reproduzir tarefa "):
            nome_tarefa = cmd_norm[16:].strip()

        repeticoes = self._extrair_repeticoes(cmd_norm)
        if not nome_tarefa:
            # Tenta match direto pelo nome inteiro digitado
            nome_tarefa = cmd_norm

        macro_path = self._macro_find_saved_by_name(nome_tarefa)
        if macro_path:
            self.adicionar_mensagem(comando, "usuario")
            self.entry.clear()
            self.set_ia_status("IA: Executando tarefa...")
            self._processing_count += 1
            self._hud_state = self._resolver_estado_hud()

            def run_macro_bg() -> None:
                try:
                    MacroPlayer, _MacroRecorder, load_macro = self._macro_imports()
                    evs = load_macro(macro_path)
                    player = MacroPlayer(failsafe_corner=True)
                    player.play_macro(evs, repeticoes=int(repeticoes), velocidade=1.0, log=False)
                    self._bridge.add_message.emit(
                        f"Tarefa executada: {os.path.splitext(os.path.basename(macro_path))[0].replace('_',' ')} ({repeticoes}x).",
                        "ia",
                        True,
                        None,
                    )
                except Exception as exc:
                    self._bridge.show_error.emit(f"Falha ao executar tarefa: {exc}")
                finally:
                    def done():
                        self._processing_count = max(0, self._processing_count - 1)
                        self._hud_state = self._resolver_estado_hud()
                        self.set_ia_status("IA: Pronta")
                    QTimer.singleShot(0, done)

            self._bridge.add_message.emit(
                f"Executando tarefa: {os.path.splitext(os.path.basename(macro_path))[0].replace('_',' ')} ({repeticoes}x).\nAperte ESC para parar.",
                "ia",
                True,
                None,
            )
            threading.Thread(target=run_macro_bg, daemon=True).start()
            return

        self.adicionar_mensagem(comando, "usuario")
        self.entry.clear()
        self.mostrar_digitando()
        self.set_ia_status("IA: Processando...")
        self._processing_count += 1
        self._gear_spinning = True
        self._hud_state = self._resolver_estado_hud()
        falar_resposta = bool(self.btn_falar.isChecked())

        def processar() -> None:
            try:
                resultado = self._process_command(comando) or {}
                self._bridge.final_response.emit(resultado)
                fala = resultado.get("fala", "")
                if falar_resposta and fala:
                    threading.Thread(target=self._falar_com_estado, args=(fala,), daemon=True).start()
            except Exception as exc:
                self._bridge.show_error.emit(str(exc))

        threading.Thread(target=processar, daemon=True).start()

    def adicionar_mensagem(self, texto, autor: str = "ia", animar: bool = True, file_path: Optional[str] = None) -> None:
        if not self._on_gui_thread():
            self._bridge.add_message.emit(str(texto), autor, animar, file_path)
            return
        self._adicionar_mensagem_impl(str(texto), autor, animar, file_path)

    def _adicionar_mensagem_impl(self, texto: str, autor: str = "ia", animar: bool = True, file_path: Optional[str] = None) -> None:
        self._add_message_widget(texto, autor=autor, animar=animar, file_path=file_path)

    def mostrar_digitando(self) -> None:
        if not self._on_gui_thread():
            self._bridge.show_typing.emit()
            return
        self._mostrar_digitando_impl()

    def remover_digitando(self) -> None:
        if not self._on_gui_thread():
            self._bridge.remove_typing.emit()
            return
        self._remover_digitando_impl()

    def set_ia_status(self, texto: str) -> None:
        if not self._on_gui_thread():
            self._bridge.set_status.emit(texto)
            return
        self._set_ia_status_impl(texto)

    def set_hud_state(self, estado: str) -> None:
        if not self._on_gui_thread():
            self._bridge.set_hud_state.emit(estado)
            return
        self._set_hud_state_impl(estado)

    def set_hud_audio_level(self, nivel: float) -> None:
        if not self._on_gui_thread():
            self._bridge.set_hud_level.emit(float(nivel))
            return
        self._set_hud_audio_level_impl(float(nivel))

    def set_hud_responding(self, ativo: bool) -> None:
        if not self._on_gui_thread():
            self._bridge.set_hud_responding.emit(bool(ativo))
            return
        self._set_hud_responding_impl(bool(ativo))

    def atualizar_botao_microfone(self, ativo: bool) -> None:
        if not self._on_gui_thread():
            self._bridge.set_mic.emit(ativo)
            return
        self._atualizar_botao_microfone_impl(ativo)

    def trazer_para_frente(self) -> None:
        if not self._on_gui_thread():
            self._bridge.bring_front.emit()
            return
        self._trazer_para_frente_impl()

    def atualizar_callback_voz(self, speak_text: Callable[[str], None]) -> None:
        self._speak_text = speak_text

    def copiar_texto_chat(self, texto: str) -> None:
        self._qt_app.clipboard().setText(str(texto))
        self.set_ia_status("IA: Texto copiado")
        QTimer.singleShot(1200, lambda: self.set_ia_status("IA: Pronta"))

    def eventFilter(self, obj, event) -> bool:
        try:
            if hasattr(self, "_macro_saved_list") and self._macro_saved_list is not None:
                vp = self._macro_saved_list.viewport()
                if obj == vp and event.type() == QEvent.Wheel:
                    self._macro_show_all_trash_buttons_temporarily(1200)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def run(self) -> None:
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        self._qt_app.exec_()
















