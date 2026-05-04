import pytest
from src.altair.core.intent_router import resolver_intencao_comando, normalizar_comando


def test_normalizar_comando():
    assert normalizar_comando("Abrir Calculadora") == "abrir calculadora"


def test_resolver_intencao_calculadora():
    intencao, dados = resolver_intencao_comando("calcule 2 + 2")
    assert intencao == "calcular_na_calculadora"


def test_resolver_intencao_grafico():
    intencao, _ = resolver_intencao_comando("gráfico de x^2")
    assert intencao == "gerar_grafico"


def test_resolver_intencao_cad():
    intencao, _ = resolver_intencao_comando("crie um cubo 3D")
    assert intencao == "gerar_cad_3d"


def test_resolver_intencao_cad_engrenagens():
    intencao, _ = resolver_intencao_comando("crie duas engrenagens e um eixo")
    assert intencao == "gerar_cad_3d"


def test_resolver_intencao_clima():
    intencao, dados = resolver_intencao_comando("clima em São Paulo")
    assert intencao == "clima_cidade"
    assert dados["cidade"] == "São Paulo"


def test_resolver_intencao_distancia():
    intencao, dados = resolver_intencao_comando("distância entre São Paulo e Rio de Janeiro")
    assert intencao == "distancia_cidades"
    assert dados["cidade_a"] == "São Paulo"
    assert dados["cidade_b"] == "Rio de Janeiro"
