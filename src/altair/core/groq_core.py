import json
import os
import re
from typing import Any, Dict, Optional

import requests


class GroqDualLLM:
    def __init__(
        self,
        api_key: Optional[str] = None,
        small_model: Optional[str] = None,
        large_model: Optional[str] = None,
        router_model: Optional[str] = None,
        base_url: Optional[str] = None,
        require_api_key: bool = True,
        timeout: int = 45,
    ) -> None:
        self.api_key = api_key or self._load_api_key()
        self.small_model = small_model or os.getenv("ALTAIR_GROQ_SMALL_MODEL", "llama-3.1-8b-instant")
        self.large_model = large_model or os.getenv("ALTAIR_GROQ_LARGE_MODEL", "llama-3.3-70b-versatile")
        self.router_model = router_model or self.small_model
        self.require_api_key = bool(require_api_key)
        self.timeout = timeout
        self.base_url = base_url or os.getenv(
            "GROQ_BASE_URL",
            "https://api.groq.com/openai/v1/chat/completions",
        )

    def _load_api_key(self) -> str:
        key_env = os.getenv("GROQ_API_KEY", "").strip()
        if key_env:
            return key_env

        key_file = os.getenv("GROQ_API_KEY_FILE", "configs/groq_api_key.txt").strip()
        if key_file and os.path.exists(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                return ""
        return ""

    def disponivel(self) -> bool:
        return bool(self.api_key) or not self.require_api_key

    def _chat(
        self,
        *,
        model: str,
        messages: list[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 500,
        json_mode: bool = False,
    ) -> str:
        if self.require_api_key and not self.api_key:
            raise RuntimeError("API key nao configurada.")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        resposta = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )

        if resposta.status_code >= 400:
            trecho = (resposta.text or "").strip()[:500]
            raise RuntimeError(f"Erro Groq HTTP {resposta.status_code}: {trecho}")

        dados = resposta.json()
        conteudo = (
            dados.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return str(conteudo or "").strip()

    def _parse_json_obj(self, texto: str) -> Dict[str, Any]:
        texto = (texto or "").strip()
        if not texto:
            return {}
        try:
            return json.loads(texto)
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", texto)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}

    def _fallback_classificacao(self, comando: str) -> Dict[str, Any]:
        cmd = (comando or "").lower()
        termos_local = [
            "enviar ",
            "arquivo",
            "audio",
            "áudio",
            "abrir",
            "abre",
            "pesquisar",
            "busque",
            "procure",
            "calcula",
            "calcular",
            "clima",
            "tempo em",
            "previsao",
            "previsão",
            "distancia",
            "distância",
            "mapa",
            "cad",
            "cadquery",
            "3d",
            "modelo 3d",
            "projeto 3d",
        ]
        termos_complexos = [
            "explique",
            "explica",
            "por que",
            "como funciona",
            "program",
            "codigo",
            "código",
            "arquitetura",
            "compar",
        ]

        usar_local = any(t in cmd for t in termos_local)
        usar_grande = any(t in cmd for t in termos_complexos)
        return {
            "acao": "usar_funcao_local" if usar_local else "responder",
            "usar_modelo_grande": usar_grande,
            "categoria": "heuristica_local" if usar_local else "heuristica_resposta",
            "justificativa": "Fallback local por indisponibilidade ou erro na classificacao do Groq.",
        }

    def classificar_tarefa(self, comando: str) -> Dict[str, Any]:
        if not self.disponivel():
            return self._fallback_classificacao(comando)

        system_prompt = (
            "Voce e um roteador de tarefas para assistente. "
            "Responda APENAS JSON valido com as chaves: "
            "acao, usar_modelo_grande, categoria, justificativa. "
            "acao deve ser 'usar_funcao_local' ou 'responder'. "
            "usar_modelo_grande deve ser booleano. "
            "Use 'usar_funcao_local' para comandos operacionais (abrir app, enviar mensagem/audio/arquivo, pesquisar, calculadora, memoria de arquivo, clima por cidade, distancia entre cidades e mapa). "
            "Use 'usar_funcao_local' para geracao de modelos CAD/3D (cad, cadquery, modelo 3d, projeto 3d). "
            "Use 'responder' para resposta textual. "
            "usar_modelo_grande=true somente para raciocinio, explicacao longa, programacao ou pedido complexo."
        )
        user_prompt = f"Comando do usuario: {comando}"

        try:
            bruto = self._chat(
                model=self.router_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=180,
                json_mode=True,
            )
            dados = self._parse_json_obj(bruto)
        except Exception:
            return self._fallback_classificacao(comando)

        acao = str(dados.get("acao", "")).strip()
        if acao not in {"usar_funcao_local", "responder"}:
            acao = "responder"

        usar_modelo_grande = bool(dados.get("usar_modelo_grande", False))
        categoria = str(dados.get("categoria", "")).strip() or "geral"
        justificativa = str(dados.get("justificativa", "")).strip() or "Sem justificativa."

        return {
            "acao": acao,
            "usar_modelo_grande": usar_modelo_grande,
            "categoria": categoria,
            "justificativa": justificativa,
        }

    def classificar_cad_3d(self, comando: str) -> Dict[str, Any]:
        if not self.disponivel():
            return {"cad_3d": False, "justificativa": "API key nao configurada."}

        system_prompt = (
            "Voce classifica se o comando do usuario pede criacao de modelo CAD/3D. "
            "Responda APENAS JSON valido com as chaves: cad_3d (boolean), justificativa (string). "
            "Considere pedidos de objetos, pecas, placas, suportes, furos, dimensoes, CADQuery ou 3D. "
            "Se for apenas pergunta, explicacao, calculo ou conversa, cad_3d=false."
        )
        user_prompt = f"Comando do usuario: {comando}"

        try:
            bruto = self._chat(
                model=self.router_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=120,
                json_mode=True,
            )
            dados = self._parse_json_obj(bruto)
        except Exception:
            return {"cad_3d": False, "justificativa": "Falha ao classificar CAD."}

        cad_3d = bool(dados.get("cad_3d", False))
        justificativa = str(dados.get("justificativa", "")).strip() or "Sem justificativa."
        return {"cad_3d": cad_3d, "justificativa": justificativa}

    def gerar_resposta(self, prompt: str, forcar_modelo_grande: Optional[bool] = None) -> str:
        if not self.disponivel():
            return "API key nao configurada. Defina a chave para usar o modelo remoto."

        usar_modelo_grande = bool(forcar_modelo_grande)
        if forcar_modelo_grande is None:
            classificacao = self.classificar_tarefa(prompt)
            usar_modelo_grande = bool(classificacao.get("usar_modelo_grande", False))

        modelo = self.large_model if usar_modelo_grande else self.small_model
        system_prompt = (
            "Voce e o assistente Altair. Responda em portugues, direto e util. "
            "Quando o pedido for tecnico, seja preciso e estruturado."
        )

        return self._chat(
            model=modelo,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=900 if usar_modelo_grande else 500,
        )

    def escolher_automacao(self, comando: str) -> Dict[str, Any]:
        if not self.disponivel():
            return {"acao": "nenhuma", "confianca": 0.0}

        system_prompt = (
            "Voce seleciona ferramentas de automacao para um assistente. "
            "Responda APENAS JSON valido com chaves: "
            "acao, confianca, app, termo, contato, mensagem. "
            "acao deve ser uma entre: nenhuma, abrir_app, pesquisar_web, enviar_mensagem, enviar_audio. "
            "confianca deve ser numero de 0 a 1. "
            "Se nao houver comando claro de automacao, retorne acao='nenhuma'. "
            "Nao invente dados ausentes."
        )
        user_prompt = f"Comando do usuario: {comando}"

        try:
            bruto = self._chat(
                model=self.router_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=220,
                json_mode=True,
            )
            dados = self._parse_json_obj(bruto)
        except Exception:
            return {"acao": "nenhuma", "confianca": 0.0}

        acao = str(dados.get("acao", "nenhuma")).strip().lower()
        acoes_validas = {"nenhuma", "abrir_app", "pesquisar_web", "enviar_mensagem", "enviar_audio"}
        if acao not in acoes_validas:
            acao = "nenhuma"

        try:
            confianca = float(dados.get("confianca", 0.0))
        except Exception:
            confianca = 0.0
        confianca = max(0.0, min(1.0, confianca))

        return {
            "acao": acao,
            "confianca": confianca,
            "app": str(dados.get("app", "") or "").strip(),
            "termo": str(dados.get("termo", "") or "").strip(),
            "contato": str(dados.get("contato", "") or "").strip(),
            "mensagem": str(dados.get("mensagem", "") or "").strip(),
        }
