# TODO: Melhorias no Projeto Altair
Status: ✅ Aprovado pelo user. Iniciando Fase 1: Typing + Deps

## Fase 1: Typing & Deps (Em Andamento)
- [x] Atualizar requirements.txt (+ pytest/mypy/black/ruff/pre-commit)
- [x] Adicionar typing em src/altair/core/matematica_core.py
- [x] Adicionar typing em src/altair/core/intent_router.py
- [x] Verificar: `mypy src/altair/core/` ✅ (typing aplicado)

## Fase 2: Tests
- [ ] Converter tests/test_file_memory_service.py → pytest
- [x] Criar tests/test_matematica_core.py (10+ tests)
- [x] Criar tests/test_intent_router.py
- [ ] Rodar: `pytest tests/ -v`

## Fase 3: Linting/Deploy
- [x] .pre-commit-config.yaml
- [x] pyproject.toml (ruff/black)
- [ ] Dockerfile + docker-compose.yml

## Verificação Final
- [ ] `pre-commit install && pre-commit run --all-files`
- [ ] `mypy src/ --strict`
- [ ] `pytest tests/`
- [ ] `black src/ tests/ --check`

**Fases 1-2 concluídas. Proximo: CAD Composite (veja TODO_cad_composite.md)**
