import datetime
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple
import PyPDF2


class FileMemoryService:
    def __init__(self, memory_file: str = "data/memoria_arquivos.json") -> None:
        self.memory_file = memory_file

    def carregar_memoria_arquivos(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    if isinstance(dados, list):
                        return dados
            except Exception as e:
                print("Erro ao carregar memoria de arquivos:", e)
        return []

    def salvar_memoria_arquivos(self, memoria: List[Dict[str, Any]]) -> None:
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(memoria, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("Erro ao salvar memoria de arquivos:", e)

    def extrair_texto_arquivo(self, caminho_arquivo: str, limite_chars: int = 14000) -> Tuple[Optional[str], Optional[str]]:
        caminho_arquivo = os.path.abspath(caminho_arquivo)
        if not os.path.exists(caminho_arquivo):
            return None, f"Arquivo nao encontrado: {caminho_arquivo}"

        ext = os.path.splitext(caminho_arquivo)[1].lower()

        def ler_texto_generico() -> str:
            for enc in ("utf-8", "latin-1"):
                try:
                    with open(caminho_arquivo, "r", encoding=enc) as f:
                        return f.read()
                except Exception:
                    pass
            raise Exception("Nao foi possivel ler como texto.")

        try:
            if ext in [".txt", ".md", ".py", ".json", ".csv", ".log", ".ini", ".yaml", ".yml", ".xml", ".html"]:
                if ext == ".json":
                    with open(caminho_arquivo, "r", encoding="utf-8") as f:
                        obj = json.load(f)
                    texto = json.dumps(obj, ensure_ascii=False, indent=2)
                else:
                    texto = ler_texto_generico()
            elif ext == ".pdf":
                texto = ""
                try:
                    from pypdf import PdfReader

                    reader = PdfReader(caminho_arquivo)
                    for page in reader.pages:
                        texto += (page.extract_text() or "") + "\n"
                except Exception:
                    try:
                        

                        reader = PyPDF2.PdfReader(caminho_arquivo)
                        for page in reader.pages:
                            texto += (page.extract_text() or "") + "\n"
                    except Exception as e:
                        return None, f"Para PDF, instale pypdf. Erro: {e}"
            elif ext == ".docx":
                try:
                    from docx import Document

                    doc = Document(caminho_arquivo)
                    texto = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                except Exception as e:
                    return None, f"Para DOCX, instale python-docx. Erro: {e}"
            else:
                return None, f"Formato nao suportado para analise: {ext or 'sem extensao'}"

            texto = (texto or "").strip()
            if not texto:
                return None, "Nao consegui extrair conteudo textual desse arquivo."

            return texto[:limite_chars], None
        except Exception as e:
            return None, f"Erro ao ler arquivo: {e}"

    def resumir_texto_arquivo(self, nome_arquivo: str, texto: str, llm: Any) -> str:
        if llm:
            prompt = (
                f"Resuma o conteudo do arquivo '{nome_arquivo}' em portugues. "
                "Faca um resumo tecnico e curto, com no maximo 8 linhas, "
                "incluindo pontos principais."
                f"\n\nConteudo:\n{texto}"
            )
            try:
                resposta = llm.gerar_resposta(prompt)
                if resposta and resposta.strip():
                    return resposta.strip()
            except Exception as e:
                print("Erro ao resumir com LLM:", e)

        linhas = [l.strip() for l in texto.splitlines() if l.strip()]
        if not linhas:
            return "Arquivo lido, mas sem conteudo textual util para resumir."
        return "Resumo rapido: " + " ".join(linhas[:6])[:700]

    def analisar_e_memorizar_arquivo(self, caminho_arquivo: str, llm: Any) -> str:
        texto, erro = self.extrair_texto_arquivo(caminho_arquivo)
        if erro:
            return erro

        caminho_absoluto = os.path.abspath(caminho_arquivo)
        nome_arquivo = os.path.basename(caminho_absoluto)
        resumo = self.resumir_texto_arquivo(nome_arquivo, texto or "", llm)

        hash_arquivo = hashlib.md5(caminho_absoluto.encode("utf-8")).hexdigest()
        memoria = self.carregar_memoria_arquivos()
        agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        registro = {
            "id": hash_arquivo,
            "arquivo": nome_arquivo,
            "caminho": caminho_absoluto,
            "resumo": resumo,
            "analisado_em": agora,
        }

        atualizado = False
        for i, item in enumerate(memoria):
            if item.get("id") == hash_arquivo:
                memoria[i] = registro
                atualizado = True
                break
        if not atualizado:
            memoria.append(registro)

        self.salvar_memoria_arquivos(memoria)
        return f"Resumo de {nome_arquivo}:\n{resumo}"
