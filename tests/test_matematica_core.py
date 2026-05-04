import pytest
import sympy as sp
from src.altair.core.matematica_core import (
    resolver_equacao_direta,
    converter_numeros_por_extenso,
    normalizar_expressao,
    formatar_resultado_matematico,
    gerar_grafico_funcao,
)


@pytest.fixture
def base_dir(tmp_path):
    return str(tmp_path)


def test_converter_numeros_por_extenso():
    assert converter_numeros_por_extenso("dois mais tres") == "2 + 3"
    assert converter_numeros_por_extenso("vinte e cinco") == "25"
    assert converter_numeros_por_extenso("um ponto cinco") == "1.5"


def test_normalizar_expressao():
    assert normalizar_expressao("dois vezes x mais tres") == "2*x+3"
    assert normalizar_expressao("x elevado a dois") == "x**2"


def test_resolver_equacao_direta():
    assert resolver_equacao_direta("x + 1 = 3") == 2
    assert resolver_equacao_direta("2x = 4") == 2


def test_formatar_resultado_matematico():
    resultado = sp.solve(sp.Eq(sp.symbols("x")**2 - 5*sp.symbols("x") + 6, 0))
    formatted = formatar_resultado_matematico(resultado)
    assert "2" in formatted and "3" in formatted


def test_gerar_grafico_funcao(base_dir):
    resultado = gerar_grafico_funcao("grafico de x^2", base_dir)
    assert "gerado" in resultado.lower()
    assert ".png" in resultado
