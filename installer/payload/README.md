# Payload do instalador (conteudo embutido no .exe)

"
    "Este diretorio deve conter tudo o que o instalador vai extrair na maquina do usuario.

"
    "Estrutura esperada (exemplo):

"
    "- `python/`
"
    "  - `python.exe`
"
    "  - `pythonw.exe` (opcional)
"
    "  - `python310.dll` (ou correspondente)
"
    "  - `Lib/` (se usar distribuicao completa)
"
    "  - `get-pip.py` (obrigatorio se o Python embutido nao vier com pip)
"
    "- `run_altair.py`
"
    "- `src/`
"
    "- `assets/`
"
    "- `configs/` (se existir no seu projeto)
"
    "- `scripts/` (se existir)
"
    "- `json/` (se existir)

"
    "Notas:
"
    "- O instalador cria um venv em `.venv/` e baixa as bibliotecas via pip conforme os checkboxes.
"
    "- Para obter o Python embutido, use o pacote oficial `Windows embeddable package` e extraia aqui em `python/`.
"
    "- Coloque tambem o `get-pip.py` dentro de `python/`.
"
    