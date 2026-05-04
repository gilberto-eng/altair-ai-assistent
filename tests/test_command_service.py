from src.altair.app.app.application.command_service import CommandService


class _DummyIA:
    llm = None

    def decidir_fluxo_comando(self, comando):
        return {"acao": "usar_funcao_local", "usar_modelo_grande": False}

    def perguntar(self, comando, permitir_automacao=True, forcar_modelo_grande=False):
        return {"visual": f"fallback:{comando}", "fala": ""}


def test_command_service_remove_debug_prefix():
    recebido = {}

    def resolver(comando):
        recebido["comando"] = comando
        return "gerar_cad_3d", {"comando": comando}

    def executar(intencao, dados, contexto):
        return {"visual": dados["comando"], "fala": ""}

    service = CommandService(
        ia=_DummyIA(),
        voz=object(),
        resolver_intencao_comando=resolver,
        executar_intencao=executar,
        montar_contexto_intencoes=lambda: {},
    )

    cmd = "DEBUG: comando recebido -> crie um modelo 3d de 2 engrenagens com um eixo"
    result = service.execute(cmd, falar=False)

    esperado = "crie um modelo 3d de 2 engrenagens com um eixo"
    assert recebido["comando"] == esperado
    assert result["visual"] == esperado


def test_command_service_math_usa_acentuacao():
    service = CommandService(
        ia=_DummyIA(),
        voz=object(),
        resolver_intencao_comando=lambda comando: (None, {}),
        executar_intencao=lambda intencao, dados, contexto: {"visual": "", "fala": ""},
        montar_contexto_intencoes=lambda: {},
    )

    result = service.execute("2 + 2", falar=False)

    assert result["visual"].startswith("O resultado é ")
    assert "4" in result["visual"]
    assert result["fala"].startswith("O resultado é ")
