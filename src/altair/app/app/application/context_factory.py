import os
from typing import Any, Callable, Dict

from app.state.session_state import SessionState
from paths import PROJECT_ROOT


def build_intent_context(
    state: SessionState,
    ia_llm: Any,
    voz: Any,
    analisar_e_memorizar_arquivo: Callable[[str, Any], str],
    carregar_memoria_arquivos: Callable[[], list],
    enviar_arquivo_whatsapp_webjs: Callable[..., str],
    converter_para_ogg: Callable[[str], str],
    enviar_audio_whatsapp_webjs: Callable[..., Any],
    base_dir: str,
) -> Dict[str, Any]:
    return {
        "arquivo_selecionado_envio": state.arquivo_selecionado_envio,
        "analisar_e_memorizar_arquivo": analisar_e_memorizar_arquivo,
        "ia_llm": ia_llm,
        "carregar_memoria_arquivos": carregar_memoria_arquivos,
        "enviar_arquivo_whatsapp_webjs": enviar_arquivo_whatsapp_webjs,
        "voz": voz,
        "converter_para_ogg": converter_para_ogg,
        "enviar_audio_whatsapp_webjs": enviar_audio_whatsapp_webjs,
        "base_dir": str(PROJECT_ROOT / "data"),
    }

