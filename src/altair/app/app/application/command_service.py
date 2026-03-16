from typing import Any, Callable, Dict, Optional, Tuple
import re

from matematica_core import (
    formatar_expressao_para_fala,
    formatar_resultado_matematico,
    interpretar_matematica,
)


class CommandService:
    def __init__(
        self,
        ia: Any,
        voz: Any,
        resolver_intencao_comando: Callable[[str], Tuple[Optional[str], Dict[str, str]]],
        executar_intencao: Callable[[str, Dict[str, str], Dict[str, Any]], Dict[str, str]],
        montar_contexto_intencoes: Callable[[], Dict[str, Any]],
    ) -> None:
        self.ia = ia
        self.voz = voz
        self.resolver_intencao_comando = resolver_intencao_comando
        self.executar_intencao = executar_intencao
        self.montar_contexto_intencoes = montar_contexto_intencoes

    def execute(self, comando: str, falar: bool = False) -> Dict[str, str]:
        comando = (comando or "").strip()
        if not comando:
            return {"visual": "Comando vazio.", "fala": ""}

        comandos_compostos = self._dividir_comando_composto(comando)
        if len(comandos_compostos) > 1:
            saidas = []
            for parte in comandos_compostos:
                resp = self._executar_unico(parte, falar=False)
                visual = (resp or {}).get("visual", "").strip()
                if visual:
                    saidas.append(visual)
            texto_visual = "\n".join(saidas) if saidas else "Comando composto recebido, mas nada foi executado."
            if falar and texto_visual:
                self.voz.speak(texto_visual)
            return {"visual": texto_visual, "fala": texto_visual}

        return self._executar_unico(comando, falar=falar)

    @staticmethod
    def _dividir_comando_composto(comando: str) -> list[str]:
        texto = (comando or "").strip()
        if not texto or " e " not in texto.lower():
            return [texto]
        if re.search(r"\b(dizendo|falando|explicando|mensagem)\b", texto, re.IGNORECASE):
            return [texto]
        if texto.count(" e ") > 3:
            return [texto]
        if re.search(r"\b(?:abra|abrir|abre)\b.*\bcalculadora\b.*\be\b.*\b(?:faca|faça|calcule|calcular|resolva)\b", texto, re.IGNORECASE):
            return [texto]
        if re.search(r"\b(?:abra|abrir|abre)\b.*\byoutube\b.*\be\b.*\b(?:busque|pesquise|procure)\b", texto, re.IGNORECASE):
            return [texto]

        verbos = r"(abra|abrir|abre|busque|buscar|pesquise|procure|calcule|calcular|faca|faça|organize|enviar|envie|mande)"
        if not re.search(verbos, texto, re.IGNORECASE):
            return [texto]

        partes = [p.strip(" ,.;") for p in re.split(r"\s+e\s+", texto, flags=re.IGNORECASE) if p.strip(" ,.;")]
        if len(partes) < 2:
            return [texto]

        if not re.search(verbos, partes[0], re.IGNORECASE):
            return [texto]
        return partes

    def _executar_unico(self, comando: str, falar: bool = False) -> Dict[str, str]:
        comando = (comando or "").strip()
        if not comando:
            return {"visual": "Comando vazio.", "fala": ""}

        texto_visual = ""
        texto_fala = ""
        try:
            print("\n==========================")
            print("DEBUG: comando recebido ->", comando)

            # Executa funcoes locais antes de qualquer roteador LLM.
            intencao_pre, dados_pre = self.resolver_intencao_comando(comando)
            if intencao_pre:
                return self.executar_intencao(intencao_pre, dados_pre, self.montar_contexto_intencoes())

            # Forca matematica local antes de qualquer fallback conversacional/LLM.
            resultado_matematica = interpretar_matematica(comando)
            if resultado_matematica is not None:
                resultado_visual = formatar_resultado_matematico(resultado_matematica, modo_bonito=True)
                resultado_fala = formatar_expressao_para_fala(resultado_visual)
                texto_visual = f"O resultado é {resultado_visual}"
                texto_fala = f"O resultado é {resultado_fala}"
                if falar and texto_fala:
                    self.voz.speak(texto_fala)
                return {"visual": texto_visual, "fala": texto_fala}

            # Quando nao encaixa em nenhuma funcao local, usa o LLM pequeno como classificador CAD.
            classificador_cad = getattr(getattr(self.ia, "llm", None), "classificar_cad_3d", None)
            if callable(classificador_cad):
                try:
                    decisao_cad = classificador_cad(comando) or {}
                except Exception:
                    decisao_cad = {}
                if bool(decisao_cad.get("cad_3d")):
                    return self.executar_intencao("gerar_cad_3d", {"comando": comando}, self.montar_contexto_intencoes())

            decisao_modelo = self.ia.decidir_fluxo_comando(comando)
            acao = decisao_modelo.get("acao", "usar_funcao_local")
            usar_modelo_grande = bool(decisao_modelo.get("usar_modelo_grande", False))
            print("DEBUG: roteador ->", decisao_modelo)

            if acao == "usar_funcao_local":
                intencao, dados = self.resolver_intencao_comando(comando)
                if intencao:
                    return self.executar_intencao(intencao, dados, self.montar_contexto_intencoes())

            resposta = self.ia.perguntar(
                comando,
                permitir_automacao=(acao == "usar_funcao_local"),
                forcar_modelo_grande=usar_modelo_grande,
            )
            if isinstance(resposta, dict):
                texto_visual = resposta.get("visual", "")
                texto_fala = resposta.get("fala", "")
            else:
                texto_visual = str(resposta)
                texto_fala = str(resposta)

            if falar and texto_fala:
                self.voz.speak(texto_fala)
            return {"visual": texto_visual, "fala": texto_fala}

        except Exception as e:
            print("ERRO GERAL:", e)
            return {"visual": f"[ERRO]: {e}", "fala": ""}
