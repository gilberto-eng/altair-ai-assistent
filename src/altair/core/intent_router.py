import hashlib
import os
import re
import unicodedata
import uuid
from typing import Dict, Optional, Tuple

from calculadora_core import (
    avaliar_expressao_calculadora,
    executar_calculo_na_calculadora,
    interpretar_comando_calculadora,
)
from geo_weather_core import calcular_distancia_entre_cidades, obter_clima_cidade_formatado
from matematica_core import buscar_formula, gerar_grafico_funcao, simular_lancamento, simular_osc_harmonica
from cad_core import gerar_projeto_cad


def normalizar_comando(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ASCII", "ignore").decode("utf-8")
    texto = re.sub(r"\s+", " ", texto).strip().lower()
    return texto


def resolver_intencao_comando(comando: str) -> Tuple[Optional[str], Dict[str, str]]:
    comando_original = (comando or "").strip()
    comando_normalizado = normalizar_comando(comando_original)
    if not comando_normalizado:
        return None, {}

    dados_calc = interpretar_comando_calculadora(comando_original)
    if dados_calc.get("match"):
        if dados_calc.get("expressao"):
            return "calcular_na_calculadora", {"expressao": dados_calc["expressao"]}
        return "calcular_na_calculadora", {
            "erro": dados_calc.get("erro", "Nao consegui interpretar a operacao para a calculadora.")
        }

    if re.search(
        r"\b(analisar|analisa|ler|leia|resumir|resuma|estudar|estude|interpretar|interprete)\b.*\b(esse|este|selecionado|selecionada)\b.*\barquivo\b",
        comando_normalizado,
    ):
        return "analisar_arquivo_selecionado", {}

    caminho_match = re.search(
        r"(?:analisar|analisa|ler|leia|resumir|resuma|estudar|estude|interpretar|interprete)\s+arquivo\s+(.+)$",
        comando_original,
        re.IGNORECASE,
    )
    if caminho_match:
        caminho_cmd = caminho_match.group(1).strip().strip('"').strip("'")
        return "analisar_arquivo_caminho", {"caminho": caminho_cmd}

    if re.search(
        r"\b(mostrar|mostre|ver|veja|listar|liste|exibir|exiba)\b.*\b(memoria|memoria de arquivos|historico)\b.*\b(arquivos?|analises?)\b",
        comando_normalizado,
    ):
        return "mostrar_memoria_arquivos", {}

    if re.search(r"\b(grafico|gráfico)\b", comando_original, re.IGNORECASE):
        return "gerar_grafico", {"comando": comando_original}

    if re.search(r"\b(simular|simulacao|simulação)\b", comando_original, re.IGNORECASE):
        return "simular_fisica", {"comando": comando_original}

    if re.search(
        r"\b(cad|cadquery|modelo 3d|projeto 3d|modelar|modelagem 3d|3d|cubo|cilindro|esfera|furo|suporte|placa)\b",
        comando_original,
        re.IGNORECASE,
    ):
        return "gerar_cad_3d", {"comando": comando_original}

    if re.search(r"\b(formula|fórmula|formulas|fórmulas|equacao|equação)\b", comando_original, re.IGNORECASE):
        return "consultar_formula", {"comando": comando_original}

    if re.search(
        r"\b(o que|qual|quais)\b.*\b(lembra|recorda|sabe|memoriza)\b.*\b(arquivo|disso)\b",
        comando_normalizado,
    ):
        return "lembrar_arquivo_selecionado", {}

    match_arquivo = re.search(
        r"(?:enviar|envie|mande|encaminhe|compartilhe)\s+(?:esse|este|o)?\s*arquivo\s+(?:para|pra|pro)\s+(.+?)(?:\s+(?:dizendo|legenda|com a mensagem|mensagem)\s+(.+))?$",
        comando_original,
        re.IGNORECASE,
    )
    if match_arquivo:
        nome = (match_arquivo.group(1) or "").strip()
        legenda = (match_arquivo.group(2) or "").strip()
        if nome:
            return "enviar_arquivo", {"nome": nome, "legenda": legenda}

    match_audio = re.search(
        r"(?:enviar|envie|mande|encaminhe)\s+(?:audio|áudio)\s+(?:para|pra|pro)\s+(.+?)\s+(?:dizendo|falando|com a mensagem|mensagem)\s+(.+)$",
        comando_original,
        re.IGNORECASE,
    )
    if match_audio:
        nome = (match_audio.group(1) or "").strip()
        mensagem = (match_audio.group(2) or "").strip()
        if nome and mensagem:
            return "enviar_audio", {"nome": nome, "mensagem": mensagem}

    match_clima = re.search(
        r"(?:\bclima\b|\btempo\b|\bprevis[aã]o\b).{0,20}\b(?:em|de|para)\b\s+(.+)$",
        comando_original,
        re.IGNORECASE,
    )
    if match_clima:
        cidade = (match_clima.group(1) or "").strip().strip('"').strip("'")
        if cidade:
            return "clima_cidade", {"cidade": cidade}

    match_distancia = re.search(
        r"(?:dist[aâ]ncia|distancia)\s+(?:entre|de)\s+(.+?)\s+(?:e|para|ate|at[eé])\s+(.+?)(?:\s+(?:no|na)\s+mapa)?$",
        comando_original,
        re.IGNORECASE,
    )
    if match_distancia:
        cidade_a = (match_distancia.group(1) or "").strip().strip('"').strip("'")
        cidade_b = (match_distancia.group(2) or "").strip().strip('"').strip("'")
        if cidade_a and cidade_b:
            return "distancia_cidades", {"cidade_a": cidade_a, "cidade_b": cidade_b}

    return None, {}


def executar_intencao(intencao: str, dados: Dict[str, str], contexto: Dict) -> Dict[str, str]:
    arquivo_selecionado_envio = contexto.get("arquivo_selecionado_envio")
    analisar_e_memorizar_arquivo = contexto["analisar_e_memorizar_arquivo"]
    ia_llm = contexto["ia_llm"]
    carregar_memoria_arquivos = contexto["carregar_memoria_arquivos"]
    enviar_arquivo_whatsapp_webjs = contexto["enviar_arquivo_whatsapp_webjs"]
    voz = contexto["voz"]
    converter_para_ogg = contexto["converter_para_ogg"]
    enviar_audio_whatsapp_webjs = contexto["enviar_audio_whatsapp_webjs"]
    base_dir = contexto["base_dir"]

    if intencao == "analisar_arquivo_selecionado":
        if not arquivo_selecionado_envio:
            return {"visual": "Nenhum arquivo selecionado. Clique no botao + para escolher um arquivo.", "fala": ""}
        texto_visual = analisar_e_memorizar_arquivo(arquivo_selecionado_envio, ia_llm)
        return {"visual": texto_visual, "fala": ""}

    if intencao == "calcular_na_calculadora":
        erro_expr = dados.get("erro", "").strip()
        if erro_expr:
            return {"visual": erro_expr, "fala": ""}

        expr = dados.get("expressao", "").strip()
        if not expr:
            return {"visual": "Operacao da calculadora vazia.", "fala": ""}

        try:
            resultado_num = avaliar_expressao_calculadora(expr)
        except Exception:
            return {"visual": "Expressao invalida para calcular.", "fala": ""}

        ok_calc, detalhe = executar_calculo_na_calculadora(expr)
        if not ok_calc:
            return {
                "visual": f"Calculo feito ({expr} = {resultado_num}), mas nao consegui controlar a Calculadora: {detalhe}",
                "fala": "",
            }

        return {
            "visual": f"Calculadora aberta e operação executada: {expr} = {resultado_num}",
            "fala": f"O resultado é {resultado_num}",
        }

    if intencao == "analisar_arquivo_caminho":
        caminho_cmd = dados.get("caminho", "")
        texto_visual = analisar_e_memorizar_arquivo(caminho_cmd, ia_llm)
        return {"visual": texto_visual, "fala": ""}

    if intencao == "mostrar_memoria_arquivos":
        memoria = carregar_memoria_arquivos()
        if not memoria:
            texto_visual = "A memoria de arquivos esta vazia."
        else:
            ultimos = memoria[-5:]
            linhas = [f"- {m.get('arquivo')} ({m.get('analisado_em')})" for m in ultimos]
            texto_visual = "Ultimos arquivos na memoria:\n" + "\n".join(linhas)
        return {"visual": texto_visual, "fala": ""}

    if intencao == "lembrar_arquivo_selecionado":
        if not arquivo_selecionado_envio:
            return {"visual": "Nenhum arquivo selecionado para consultar memoria.", "fala": ""}
        caminho_atual = os.path.abspath(arquivo_selecionado_envio)
        hash_atual = hashlib.md5(caminho_atual.encode("utf-8")).hexdigest()
        memoria = carregar_memoria_arquivos()
        item = next((m for m in memoria if m.get("id") == hash_atual), None)
        if not item:
            texto_visual = "Ainda nao tenho memoria desse arquivo. Peca para eu analisar primeiro."
        else:
            texto_visual = f"Lembro disso sobre {item.get('arquivo')}:\n{item.get('resumo')}"
        return {"visual": texto_visual, "fala": ""}

    if intencao == "enviar_arquivo":
        nome = dados.get("nome", "").strip()
        legenda = dados.get("legenda", "").strip()
        if not arquivo_selecionado_envio:
            return {"visual": "Nenhum arquivo selecionado. Clique no botao + para escolher um arquivo.", "fala": ""}
        texto_visual = enviar_arquivo_whatsapp_webjs(nome, arquivo_selecionado_envio, legenda)
        return {"visual": texto_visual, "fala": ""}

    if intencao == "enviar_audio":
        nome = dados.get("nome", "").strip()
        mensagem = dados.get("mensagem", "").strip()

        pasta_audios = os.path.join(base_dir,"data", "audios_temp")
        os.makedirs(pasta_audios, exist_ok=True)
        nome_unico = str(uuid.uuid4())
        wav_path = os.path.join(pasta_audios, f"{nome_unico}.wav")
        wav_gerado = voz.save_to_file(mensagem, wav_path)
        ogg_gerado = converter_para_ogg(wav_path)
        if not ogg_gerado:
            raise Exception("falha ao gerar audio")
        ogg_path = ogg_gerado
        if not wav_gerado or not os.path.exists(wav_gerado):
            raise Exception("erro ao gerar audio wav")

        ok_audio, retorno_audio = enviar_audio_whatsapp_webjs(nome, ogg_path)
        if not ok_audio:
            raise Exception(retorno_audio)

        return {"visual": retorno_audio, "fala": ""}

    if intencao == "clima_cidade":
        cidade = dados.get("cidade", "").strip()
        if not cidade:
            return {"visual": "Cidade nao informada para consulta de clima.", "fala": ""}
        texto_visual, texto_fala = obter_clima_cidade_formatado(cidade)
        return {"visual": texto_visual, "fala": texto_fala}

    if intencao == "distancia_cidades":
        cidade_a = dados.get("cidade_a", "").strip()
        cidade_b = dados.get("cidade_b", "").strip()
        if not cidade_a or not cidade_b:
            return {"visual": "Informe duas cidades para calcular a distancia.", "fala": ""}
        texto = calcular_distancia_entre_cidades(cidade_a, cidade_b, abrir_mapa=True)
        return {"visual": texto, "fala": texto}
    
    if intencao == "gerar_grafico":
        comando = dados.get("comando", "")
        resp = gerar_grafico_funcao(comando, base_dir)
        caminho = resp if isinstance(resp, str) else ""
        if isinstance(resp, str):
            m = re.search(r"(Grafico|Gráfico).*?:\s*(.*\.png)", resp, re.IGNORECASE)
            if m:
                caminho = m.group(2).strip()
        if caminho and os.path.exists(caminho):
            return {"visual": f"Gráfico gerado: {caminho}", "fala": "", "file": caminho}
        return {"visual": str(resp), "fala": ""}


    if intencao == "simular_fisica":
        comando = dados.get("comando", "")
        cmd_norm = comando.lower()
        if "lancamento" in cmd_norm or "lançamento" in cmd_norm or "projetil" in cmd_norm:
            texto = simular_lancamento(comando, base_dir)
            caminho = None
            m = re.search(r"Grafico:\s*(.*\.png)", texto, re.IGNORECASE)
            if m:
                caminho = m.group(1).strip()
            payload = {"visual": texto, "fala": ""}
            if caminho and os.path.exists(caminho):
                payload["file"] = caminho
            return payload
        if "oscil" in cmd_norm or "pendulo" in cmd_norm or "pêndulo" in cmd_norm:
            texto = simular_osc_harmonica(comando, base_dir)
            caminho = None
            m = re.search(r"Grafico:\s*(.*\.png)", texto, re.IGNORECASE)
            if m:
                caminho = m.group(1).strip()
            payload = {"visual": texto, "fala": ""}
            if caminho and os.path.exists(caminho):
                payload["file"] = caminho
            return payload
        return {"visual": "Simulacao nao reconhecida. Exemplo: simular lancamento v0=20 angulo=45.", "fala": ""}


    if intencao == "gerar_cad_3d":
        comando = dados.get("comando", "")
        return gerar_projeto_cad(comando, ia_llm, base_dir)

    if intencao == "consultar_formula":
        comando = dados.get("comando", "")
        resultado = buscar_formula(comando)
        if not resultado:
            return {"visual": "Nao encontrei essa formula. Peça por 'lista de formulas' para ver o catalogo.", "fala": ""}
        chave, formula = resultado
        if chave == "lista":
            linhas = [f"- {k}: {v}" for k, v in formula.items()]
            return {"visual": "Formulas disponiveis:\n" + "\n".join(linhas), "fala": ""}
        return {"visual": f"{chave}: {formula}", "fala": ""}

    return {"visual": "", "fala": ""}
