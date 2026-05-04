from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

try:
    from cad_library_catalog import search_catalog
except ImportError:  # pragma: no cover - fallback for package imports
    from src.altair.core.cad_library_catalog import search_catalog

try:
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import PromptTemplate
    from langchain_core.runnables import RunnableLambda

    LANGCHAIN_CORE_OK = True
except Exception:  # pragma: no cover - optional dependency
    JsonOutputParser = None
    PromptTemplate = None
    RunnableLambda = None
    LANGCHAIN_CORE_OK = False


_PROMPT_TEMPLATE = """
Voce e um planejador de CAD com saida estruturada.
Escolha apenas classes existentes no catalogo fornecido.
Retorne APENAS um objeto JSON valido com as chaves:
mode, confidence, summary, pieces.

Regras:
- mode deve ser single_piece, assembly ou unknown.
- confidence deve ser um numero entre 0 e 1.
- summary deve ser curto.
- pieces deve ser uma lista de objetos com query, class, module, quantity, params e reason.
- class deve ser o nome exato da classe do catalogo.
- se o pedido tiver varias pecas, use mode assembly.
- se o pedido for uma peca unica, use mode single_piece.
- se houver duvida, use mode unknown e ainda assim devolva o melhor palpite.
- nao invente classes fora do catalogo.

Catalogo:
{catalogo}

Comando:
{comando}
""".strip()


def _sem_acentos(texto: Optional[str]) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ASCII", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", texto).strip().lower()


def _prompt_value_to_text(value: Any) -> str:
    if hasattr(value, "to_string"):
        try:
            return str(value.to_string())
        except Exception:
            pass
    if hasattr(value, "text"):
        try:
            return str(value.text)
        except Exception:
            pass
    return str(value or "").strip()


def _call_llm_text(llm: Any, prompt_value: Any) -> str:
    prompt_text = _prompt_value_to_text(prompt_value)
    if not prompt_text:
        return ""

    if llm is None:
        return ""

    gerador = getattr(llm, "gerar_resposta", None)
    if callable(gerador):
        try:
            return str(gerador(prompt_text, forcar_modelo_grande=True) or "").strip()
        except TypeError:
            try:
                return str(gerador(prompt_text) or "").strip()
            except Exception:
                return ""
        except Exception:
            return ""

    if callable(llm):
        try:
            return str(llm(prompt_text) or "").strip()
        except Exception:
            return ""

    return ""


def _catalogo_extrato(catalogo: Dict[str, Any], comando: str, limit: int = 12) -> str:
    candidatos = search_catalog(catalogo, comando, limit=limit)
    if not candidatos:
        candidatos = list(catalogo.get("entries", []))[:limit]

    linhas: List[str] = []
    for entry in candidatos:
        if not isinstance(entry, dict):
            continue
        classe = str(entry.get("class", "")).strip() or "desconhecida"
        modulo = str(entry.get("module", "")).strip() or "desconhecido"
        params = entry.get("params", [])
        aliases = entry.get("aliases", [])
        doc = str(entry.get("doc", "")).strip()
        params_txt = ", ".join(str(p) for p in params[:8]) if params else "nenhum"
        aliases_txt = ", ".join(str(a) for a in aliases[:8]) if aliases else "nenhum"
        doc_txt = f" | doc: {doc}" if doc else ""
        linhas.append(
            f"- class: {classe} | module: {modulo} | params: {params_txt} | aliases: {aliases_txt}{doc_txt}"
        )
    return "\n".join(linhas) if linhas else "- catalogo vazio"


def _resolver_entrada_catalogo_por_chave(catalogo: Dict[str, Any], chave: str) -> Optional[Dict[str, Any]]:
    chave_norm = _sem_acentos(chave)
    if not chave_norm:
        return None

    for entry in catalogo.get("entries", []):
        if not isinstance(entry, dict):
            continue
        classe = _sem_acentos(str(entry.get("class", "")))
        if classe == chave_norm:
            return entry

    matches = search_catalog(catalogo, chave, limit=3)
    if matches:
        return matches[0]
    return None


class CadLangChainPlanner:
    def __init__(self, llm: Any, catalogo: Dict[str, Any]) -> None:
        self._llm = llm
        self._catalogo = catalogo
        self._chain = None

        if not LANGCHAIN_CORE_OK or llm is None:
            return

        if PromptTemplate is None or RunnableLambda is None or JsonOutputParser is None:
            return

        template = PromptTemplate.from_template(_PROMPT_TEMPLATE)
        self._chain = template | RunnableLambda(lambda prompt: _call_llm_text(self._llm, prompt)) | JsonOutputParser()

    def disponivel(self) -> bool:
        return bool(self._chain)

    def _normalizar_plano(self, dados: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(dados, dict):
            return None

        mode = _sem_acentos(str(dados.get("mode", "unknown"))) or "unknown"
        if mode not in {"single_piece", "assembly", "unknown"}:
            mode = "unknown"

        summary = str(dados.get("summary", "")).strip()
        confidence_raw = dados.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        pieces_raw = dados.get("pieces", [])
        if not isinstance(pieces_raw, list):
            pieces_raw = []

        pedidos: Dict[str, Dict[str, Any]] = {}
        for item in pieces_raw:
            if not isinstance(item, dict):
                continue
            chave_busca = str(item.get("class", "") or item.get("query", "")).strip()
            entry = _resolver_entrada_catalogo_por_chave(self._catalogo, chave_busca)
            if entry is None:
                continue

            classe = str(entry.get("class", "")).strip()
            if not classe:
                continue

            try:
                quantidade = int(item.get("quantity", 1))
            except Exception:
                quantidade = 1
            quantidade = max(1, min(quantidade, 12))

            params = item.get("params", {})
            if not isinstance(params, dict):
                params = {}

            if classe in pedidos:
                pedidos[classe]["quantity"] += quantidade
                continue

            pedidos[classe] = {
                "query": str(item.get("query", "") or chave_busca).strip() or classe,
                "quantity": quantidade,
                "entry": entry,
                "params": params,
                "reason": str(item.get("reason", "")).strip(),
                "span": (0, 0),
            }

        if not pedidos:
            return None

        return {
            "mode": mode,
            "confidence": confidence,
            "summary": summary,
            "pieces": list(pedidos.values()),
            "raw": dados,
        }

    def planejar(self, comando: str) -> Optional[Dict[str, Any]]:
        if not self.disponivel():
            return None

        comando = (comando or "").strip()
        if not comando:
            return None

        try:
            dados = self._chain.invoke(
                {
                    "comando": comando,
                    "catalogo": _catalogo_extrato(self._catalogo, comando),
                }
            )
        except Exception:
            return None

        return self._normalizar_plano(dados)


def planejar_cad_com_langchain(
    comando: str,
    catalogo: Dict[str, Any],
    llm: Any,
) -> Optional[Dict[str, Any]]:
    planner = CadLangChainPlanner(llm, catalogo)
    return planner.planejar(comando)
