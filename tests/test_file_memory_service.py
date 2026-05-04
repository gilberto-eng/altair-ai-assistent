import json
import tempfile
import unittest
from pathlib import Path

from app.application.services.file_memory_service import FileMemoryService


class FileMemoryServiceTests(unittest.TestCase):
    def test_salvar_e_carregar_memoria(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            memoria_path = Path(tmp_dir) / "memoria_arquivos.json"
            service = FileMemoryService(memory_file=str(memoria_path))

            dados = [{"id": "1", "arquivo": "a.txt", "resumo": "ok"}]
            service.salvar_memoria_arquivos(dados)

            carregado = service.carregar_memoria_arquivos()
            self.assertEqual(carregado, dados)

    def test_resumir_sem_llm_faz_fallback_curto(self):
        service = FileMemoryService(memory_file="memoria_arquivos.json")
        texto = "linha 1\nlinha 2\n\nlinha 3"
        resumo = service.resumir_texto_arquivo("doc.txt", texto, llm=None)

        self.assertTrue(resumo.startswith("Resumo rapido:"))
        self.assertIn("linha 1", resumo)

    def test_analisar_arquivo_inexistente_retorna_erro(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            memoria_path = Path(tmp_dir) / "memoria_arquivos.json"
            service = FileMemoryService(memory_file=str(memoria_path))

            resposta = service.analisar_e_memorizar_arquivo(str(Path(tmp_dir) / "nao_existe.txt"), llm=None)
            self.assertIn("Arquivo nao encontrado", resposta)

    def test_analisar_arquivo_texto_salva_memoria(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            memoria_path = Path(tmp_dir) / "memoria_arquivos.json"
            arquivo = Path(tmp_dir) / "exemplo.txt"
            arquivo.write_text("alpha\nbeta\ngamma", encoding="utf-8")

            service = FileMemoryService(memory_file=str(memoria_path))
            resposta = service.analisar_e_memorizar_arquivo(str(arquivo), llm=None)

            self.assertTrue(resposta.startswith("Resumo de exemplo.txt:"))
            dados = json.loads(memoria_path.read_text(encoding="utf-8"))
            self.assertEqual(len(dados), 1)
            self.assertEqual(dados[0]["arquivo"], "exemplo.txt")


if __name__ == "__main__":
    unittest.main()
