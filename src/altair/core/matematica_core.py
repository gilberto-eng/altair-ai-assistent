import math
import re
import statistics
import unicodedata
import os
from datetime import datetime

import sympy as sp
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMACOES = standard_transformations + (implicit_multiplication_application,)
MODO_RESPOSTA_BONITA_PADRAO = True

UNIDADES_EXTENSO = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
}
DEZENAS_EXTENSO = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
CENTENAS_EXTENSO = {
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "trezentos": 300,
    "quatrocentos": 400,
    "quinhentos": 500,
    "seiscentos": 600,
    "setecentos": 700,
    "oitocentos": 800,
    "novecentos": 900,
}
ESCALAS_EXTENSO = {
    "mil": 1000,
    "milhao": 1000000,
    "milhoes": 1000000,
}
TOKEN_NUMERO_EXTENSO = set(UNIDADES_EXTENSO) | set(DEZENAS_EXTENSO) | set(CENTENAS_EXTENSO) | set(ESCALAS_EXTENSO) | {
    "e",
    "menos",
    "ponto",
    "virgula",
}


def _sem_acentos(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return texto.encode("ASCII", "ignore").decode("utf-8")


def _normalizar_texto(texto):
    texto = _sem_acentos(texto).lower().strip()
    texto = texto.replace(",", ".")
    texto = re.sub(r"\s+", " ", texto)
    texto = converter_numeros_por_extenso(texto)
    return texto


def _parse_inteiro_extenso(tokens):
    total = 0
    atual = 0
    achou = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "e":
            i += 1
            continue
        if tok in UNIDADES_EXTENSO:
            atual += UNIDADES_EXTENSO[tok]
            achou = True
            i += 1
            continue
        if tok in DEZENAS_EXTENSO:
            atual += DEZENAS_EXTENSO[tok]
            achou = True
            i += 1
            continue
        if tok in CENTENAS_EXTENSO:
            atual += CENTENAS_EXTENSO[tok]
            achou = True
            i += 1
            continue
        if tok in ESCALAS_EXTENSO:
            escala = ESCALAS_EXTENSO[tok]
            if atual == 0:
                atual = 1
            total += atual * escala
            atual = 0
            achou = True
            i += 1
            continue
        return None
    if not achou:
        return None
    return total + atual


def _numero_por_extenso_para_float(frase):
    texto = _sem_acentos(frase or "").lower().strip()
    if not texto:
        return None
    tokens = [t for t in texto.split() if t]
    if not tokens:
        return None
    if any(t not in TOKEN_NUMERO_EXTENSO for t in tokens):
        return None

    sinal = 1
    if tokens and tokens[0] == "menos":
        sinal = -1
        tokens = tokens[1:]
    if not tokens:
        return None

    if "virgula" in tokens or "ponto" in tokens:
        separador = "virgula" if "virgula" in tokens else "ponto"
        idx = tokens.index(separador)
        parte_int = tokens[:idx]
        parte_dec = tokens[idx + 1 :]
        if not parte_dec:
            return None
        inteiro = _parse_inteiro_extenso(parte_int) if parte_int else 0
        if inteiro is None:
            return None
        decimal = _parse_inteiro_extenso(parte_dec)
        if decimal is None:
            return None
        dec_txt = str(int(decimal))
        numero = float(f"{inteiro}.{dec_txt}")
        return sinal * numero

    inteiro = _parse_inteiro_extenso(tokens)
    if inteiro is None:
        return None
    return float(sinal * inteiro)


def converter_numeros_por_extenso(texto):
    base = _sem_acentos(texto or "").lower()
    base = re.sub(r"\s+", " ", base).strip()
    if not base:
        return base

    palavras = base.split(" ")
    i = 0
    resultado = []
    while i < len(palavras):
        convertido = None
        usado = 0
        max_j = min(len(palavras), i + 8)
        for j in range(max_j, i, -1):
            trecho = " ".join(palavras[i:j])
            numero = _numero_por_extenso_para_float(trecho)
            if numero is None:
                continue
            if abs(numero - int(numero)) < 1e-12:
                convertido = str(int(numero))
            else:
                convertido = str(numero).replace(",", ".")
            usado = j - i
            break
        if convertido is not None:
            resultado.append(convertido)
            i += usado
            continue
        resultado.append(palavras[i])
        i += 1

    return " ".join(resultado)


def _sympy_expr(expr):
    expr = normalizar_expressao(expr)
    return parse_expr(expr, transformations=TRANSFORMACOES)


def _equacao_para_sympy(texto_eq):
    texto_eq = (texto_eq or "").strip()
    if "=" in texto_eq:
        esquerda, direita = texto_eq.split("=", 1)
        return sp.Eq(_sympy_expr(esquerda), _sympy_expr(direita))
    return sp.Eq(_sympy_expr(texto_eq), 0)


def _resolver_sistema_texto(comando):
    texto = _normalizar_texto(comando)
    texto = texto.replace(" e ", ";")

    candidatos = re.findall(r"[-+*/^().0-9xyz\s]+=[-+*/^().0-9xyz\s]+", texto)
    if len(candidatos) >= 2:
        partes = [c.strip() for c in candidatos]
    else:
        texto = re.sub(r"\b(resolva|resolver|calcule|sistema|linear|equacoes?|o|de)\b", " ", texto)
        partes = [p.strip() for p in re.split(r"[;,]", texto) if "=" in p]

    equacoes = [_equacao_para_sympy(p) for p in partes if "=" in p]
    if len(equacoes) < 2:
        return None
    variaveis = sorted(set().union(*[eq.free_symbols for eq in equacoes]), key=lambda v: v.name)
    return sp.solve(equacoes, variaveis, dict=True)


def _resolver_raizes_equacao(comando):
    texto = _normalizar_texto(comando)
    texto = re.sub(r"\b(encontre|achar|ache|calcule|quais|as|os|raizes?|raiz|da|de|equacao)\b", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        return None
    eq = _equacao_para_sympy(texto)
    x = sp.symbols("x")
    return sp.solve(eq, x)


def interpretar_matematica(comando):
    comando_original = (comando or "").strip()
    if not comando_original:
        return None

    comando = _normalizar_texto(comando_original)
    if not re.search(
        r"\d|[xyz]|integral|derivad|raiz|equac|sistema|log|fatorial|seno|cosseno|tangente|media|area|[+\-*/^=]|\b(mais|menos|vezes|dividido|elevado)\b",
        comando,
    ):
        return None

    if (("sistema" in comando and "=" in comando) or (comando.count("=") >= 2 and re.search(r"[;,]|\se\s", comando))):
        try:
            resultado = _resolver_sistema_texto(comando)
            if resultado is not None:
                return resultado
            if comando.count("=") < 2:
                return None
            return "Nao consegui interpretar o sistema linear."
        except Exception:
            return "Nao consegui resolver o sistema linear."

    if re.search(r"raiz(?: quadrada)? de -?\d+(?:\.\d+)?$", comando):
        match = re.search(r"raiz(?: quadrada)? de (-?\d+(?:\.\d+)?)$", comando)
        numero = float(match.group(1))
        if numero < 0:
            return "Raiz quadrada real nao existe para numero negativo."
        return math.sqrt(numero)

    if re.search(r"\braiz(?:es)?\b", comando) and ("equacao" in comando or "=" in comando or "x" in comando):
        try:
            resultado = _resolver_raizes_equacao(comando)
            if resultado is not None:
                return resultado
            return "Nao consegui encontrar as raizes da equação."
        except Exception:
            return "Nao consegui encontrar as raizes da equação."

    if "integral" in comando:
        try:
            if "definida" in comando or re.search(r"\bde\s*-?\d+(?:\.\d+)?\s*(?:a|ate)\s*-?\d+(?:\.\d+)?\b", comando):
                resultado = integral_definida(comando)
            else:
                resultado = integral_avancada(comando)
            if resultado is not None:
                return resultado
            return "Nao consegui resolver essa integral."
        except Exception:
            return "Nao consegui resolver essa integral."

    if "derivada" in comando:
        try:
            return derivada_avancada(comando)
        except Exception:
            return "Nao consegui resolver essa derivada."

    if "=" in comando and any(v in comando for v in ("x", "y", "z")):
        try:
            if any(v in comando for v in ("x^2", "x**2", "x2")):
                return _resolver_raizes_equacao(comando)
            return resolver_equacao_direta(comando)
        except Exception:
            return "Nao consegui resolver essa equação."

    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:\^|elevado a)\s*(-?\d+(?:\.\d+)?)", comando)
    if match:
        return float(match.group(1)) ** float(match.group(2))

    match = re.search(r"log(?:aritmo)? de (-?\d+(?:\.\d+)?)", comando)
    if match:
        valor = float(match.group(1))
        if valor <= 0:
            return "Logaritmo so existe para valores positivos."
        return math.log10(valor)

    match = re.search(r"fatorial de (\d+)", comando)
    if match:
        return math.factorial(int(match.group(1)))

    match = re.search(r"seno de (-?\d+(?:\.\d+)?)", comando)
    if match:
        return math.sin(math.radians(float(match.group(1))))

    match = re.search(r"cosseno de (-?\d+(?:\.\d+)?)", comando)
    if match:
        return math.cos(math.radians(float(match.group(1))))

    match = re.search(r"tangente de (-?\d+(?:\.\d+)?)", comando)
    if match:
        return math.tan(math.radians(float(match.group(1))))

    match = re.search(r"area do circulo de raio (-?\d+(?:\.\d+)?)", comando)
    if match:
        r = float(match.group(1))
        return math.pi * r ** 2

    match = re.search(r"media de ([\d\s.\-]+)", comando)
    if match:
        numeros = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", match.group(1))]
        if numeros:
            return statistics.mean(numeros)

    expr_livre = normalizar_expressao(comando)
    if re.search(r"[xyz0-9]", expr_livre) and re.search(r"[+\-*/^]", expr_livre):
        try:
            expr = _sympy_expr(expr_livre)
            valor = sp.N(expr)
            return float(valor) if valor.is_real else valor
        except Exception:
            try:
                return sp.simplify(_sympy_expr(expr_livre))
            except Exception:
                return "Nao consegui resolver essa expressão."

    termos_matematica = [
        "raiz",
        "potencia",
        "fatorial",
        "integral",
        "derivada",
        "seno",
        "cosseno",
        "tangente",
        "media",
        "area",
        "equacao",
        "sistema",
    ]
    if any(t in comando for t in termos_matematica):
        return "Nao consegui resolver essa operação matemática."

    return None


def formatar_resultado_matematico(resultado, modo_bonito=MODO_RESPOSTA_BONITA_PADRAO):
    if not modo_bonito:
        return str(resultado)

    def _embelezar_expr(texto: str) -> str:
        txt = str(texto)
        txt = txt.replace("**", "^")
        txt = re.sub(r"(\d)\*([a-zA-Z])", r"\1\2", txt)
        txt = re.sub(r"([a-zA-Z])\*(\d)", r"\1\2", txt)
        txt = re.sub(r"([a-zA-Z])\*([a-zA-Z])", r"\1\2", txt)
        txt = txt.replace("sqrt(", "raiz(")
        return txt

    def _fmt_valor(valor):
        if isinstance(valor, float):
            inteiro = int(valor)
            if abs(valor - inteiro) < 1e-10:
                return str(inteiro)
            return f"{valor:.10g}"
        if isinstance(valor, sp.Basic):
            return _embelezar_expr(sp.sstr(sp.simplify(valor)))
        return _embelezar_expr(str(valor))

    if isinstance(resultado, list):
        if not resultado:
            return "sem solução"
        if all(isinstance(item, dict) for item in resultado):
            linhas = []
            for idx, solucao in enumerate(resultado, start=1):
                pares = [f"{chave} = {_fmt_valor(valor)}" for chave, valor in sorted(solucao.items(), key=lambda kv: str(kv[0]))]
                linhas.append(f"Solucao {idx}: " + ", ".join(pares))
            return "\n".join(linhas)
        return ", ".join(_fmt_valor(item) for item in resultado)

    if isinstance(resultado, dict):
        if not resultado:
            return "sem solucao"
        pares = [f"{chave} = {_fmt_valor(valor)}" for chave, valor in sorted(resultado.items(), key=lambda kv: str(kv[0]))]
        return ", ".join(pares)

    if isinstance(resultado, sp.Equality):
        return f"{_fmt_valor(resultado.lhs)} = {_fmt_valor(resultado.rhs)}"

    if isinstance(resultado, sp.Basic):
        return _fmt_valor(resultado)

    if isinstance(resultado, float):
        return _fmt_valor(resultado)

    return _embelezar_expr(str(resultado))


def resolver_equacao_direta(texto):
    if not texto:
        return None
    x = sp.symbols("x")
    try:
        eq = _equacao_para_sympy(texto)
        solucoes = sp.solve(eq, x)
        if not solucoes:
            return None
        if len(solucoes) == 1:
            return solucoes[0]
        return solucoes
    except Exception:
        return None


def formatar_numero_para_fala(numero):
    if isinstance(numero, float) and numero.is_integer():
        return str(int(numero))

    numero_str = str(numero)
    if "." in numero_str:
        parte_inteira, parte_decimal = numero_str.split(".")
        parte_decimal = parte_decimal.rstrip("0")
        if not parte_decimal:
            return parte_inteira
        decimal_falado = " ".join(parte_decimal)
        return f"{parte_inteira} ponto {decimal_falado}"
    return numero_str


def resolver_segundo_grau(comando):
    x = sp.symbols("x")
    try:
        eq = _equacao_para_sympy(comando)
        return sp.solve(eq, x)
    except Exception:
        return None


def maximo_minimo(comando):
    x = sp.symbols("x")
    expressao = _sympy_expr(comando)
    derivada = sp.diff(expressao, x)
    criticos = sp.solve(derivada, x)
    resultados = []
    for ponto in criticos:
        valor = expressao.subs(x, ponto)
        resultados.append((ponto, valor))
    return resultados


def derivada_avancada(comando):
    x = sp.symbols("x")
    comando = re.sub(r"\bderivada\b", "", _normalizar_texto(comando))
    expr = _sympy_expr(comando)
    return sp.diff(expr, x)


def integral_avancada(comando):
    x = sp.symbols("x")
    comando = _normalizar_texto(comando)
    comando = re.sub(r"\bintegral\b", "", comando).strip()
    comando = re.sub(r"\bdx\b$", "", comando).strip()
    expr = _sympy_expr(comando)
    return sp.integrate(expr, x)


def integral_definida(comando):
    x = sp.symbols("x")
    comando = _normalizar_texto(comando)

    match = re.search(
        r"(?:integral(?: definida)?)\s+de\s+(-?\d+(?:\.\d+)?)\s*(?:a|ate)\s*(-?\d+(?:\.\d+)?)\s+de\s+(.+)",
        comando,
    )
    if not match:
        match = re.search(
            r"de\s+(-?\d+(?:\.\d+)?)\s*(?:a|ate)\s*(-?\d+(?:\.\d+)?)\s+de\s+(.+)",
            comando,
        )
    if not match:
        return None

    a = float(match.group(1))
    b = float(match.group(2))
    expr_texto = re.sub(r"\bdx\b$", "", match.group(3).strip()).strip()
    expr = _sympy_expr(expr_texto)
    return sp.integrate(expr, (x, a, b))


def resolver_sistema(eq1, eq2):
    x, y = sp.symbols("x y")
    try:
        s1 = _equacao_para_sympy(eq1)
        s2 = _equacao_para_sympy(eq2)
        return sp.solve((s1, s2), (x, y), dict=True)
    except Exception:
        return None


def normalizar_expressao(expr):
    expr = _normalizar_texto(expr)
    expr = re.sub(r"\b(de|da|do|calcule|calcular|resolver|resolva|equacao|equacao de|quanto|qual|resultado)\b", " ", expr)

    expr = re.sub(r"ele\s*vado", "elevado", expr)
    expr = re.sub(r"elevad[oa]?\s+a[o]?\s+quadrado", "^2", expr)
    expr = re.sub(r"elevad[oa]?\s+a[o]?\s+cubo", "^3", expr)
    expr = re.sub(r"ao\s+quadrado", "^2", expr)
    expr = re.sub(r"a[o]?\s+cubo", "^3", expr)
    expr = re.sub(r"elevad[oa]?\s+a", "^", expr)
    expr = re.sub(r"\bmais\b", "+", expr)
    expr = re.sub(r"\bmenos\b", "-", expr)
    expr = re.sub(r"\bdividido por\b", "/", expr)
    expr = re.sub(r"\bdivida\b", "/", expr)
    expr = re.sub(r"\bvezes\b", "*", expr)
    expr = re.sub(r"(?<=\d)\s+por\s+(?=\d)", "*", expr)

    expr = expr.replace("seno", "sin")
    expr = expr.replace("cosseno", "cos")
    expr = expr.replace("tangente", "tan")

    expr = re.sub(r"(sin|cos|tan)\s*x", r"\1(x)", expr)
    expr = re.sub(r"\b(?!sin\b|cos\b|tan\b|x\b|y\b|z\b)[a-z]+\b", " ", expr)
    expr = re.sub(r"(\d)(x|y|z)", r"\1*\2", expr)
    expr = re.sub(r"(x|y|z)(\d)", r"\1*\2", expr)

    expr = expr.replace("^", "**")
    expr = re.sub(r"\s+", " ", expr).strip()
    return expr


def formatar_expressao_para_fala(expr):
    expr = str(expr)
    expr = re.sub(r"\^2\b", " ao quadrado", expr)
    expr = re.sub(r"\^3\b", " ao cubo", expr)
    expr = re.sub(r"\^(\d+)", r" elevado a \1", expr)
    expr = expr.replace("**2", " ao quadrado")
    expr = expr.replace("**3", " ao cubo")
    expr = re.sub(r"\*\*(\d+)", r" elevado a \1", expr)
    expr = expr.replace("*", " ")
    expr = expr.replace("sin", "seno")
    expr = expr.replace("cos", "cosseno")
    expr = expr.replace("tan", "tangente")
    expr = expr.replace("(", " de ")
    expr = expr.replace(")", "")
    expr = expr.replace("/", " dividido por ")
    expr = re.sub(r"\s+", " ", expr)
    return expr.strip()


FORMULAS = {
    "bhaskara": "x = (-b ± √(b² - 4ac)) / (2a)",
    "delta": "Δ = b² - 4ac",
    "pitagoras": "a² + b² = c²",
    "juros_simples": "J = C·i·t; M = C + J",
    "juros_compostos": "M = C·(1 + i)^t",
    "mru": "s = s0 + v·t",
    "mruv": "v = v0 + a·t; s = s0 + v0·t + (a·t²)/2; v² = v0² + 2a·Δs",
    "newton_2": "F = m·a",
    "energia_cinetica": "Ec = (m·v²)/2",
    "energia_potencial": "Ep = m·g·h",
    "momento_linear": "p = m·v",
    "impulso": "I = F·Δt = Δp",
}

ALIAS_FORMULAS = {
    "bhaskara": ["bhaskara", "baskara", "equacao do segundo grau", "formula de bhaskara"],
    "delta": ["delta", "discriminante"],
    "pitagoras": ["pitagoras", "pitagoras", "teorema de pitagoras"],
    "juros_simples": ["juros simples", "juros simples formula"],
    "juros_compostos": ["juros compostos", "juros compostos formula"],
    "mru": ["mru", "movimento retilineo uniforme"],
    "mruv": ["mruv", "movimento retilineo uniformemente variado"],
    "newton_2": ["segunda lei de newton", "f = m a", "f=ma"],
    "energia_cinetica": ["energia cinetica", "ec"],
    "energia_potencial": ["energia potencial", "ep"],
    "momento_linear": ["momento linear", "quantidade de movimento", "p = m v"],
    "impulso": ["impulso"],
}


def buscar_formula(consulta: str):
    texto = _sem_acentos(consulta or "").lower()
    if not texto:
        return None
    for chave, aliases in ALIAS_FORMULAS.items():
        for termo in aliases:
            if _sem_acentos(termo) in texto:
                return chave, FORMULAS[chave]
    if "lista" in texto or "todas" in texto or "catalogo" in texto or "catálogo" in texto:
        return "lista", FORMULAS
    return None


def _extrair_intervalo(comando: str):
    texto = _normalizar_texto(comando)
    match = re.search(r"\bde\s*(-?\d+(?:\.\d+)?)\s*(?:a|ate)\s*(-?\d+(?:\.\d+)?)\b", texto)
    if match:
        return float(match.group(1)), float(match.group(2))
    return -10.0, 10.0


def _extrair_funcao_grafico(comando: str):
    original = comando or ""
    if "f(x)" in original.lower():
        match = re.search(r"f\(x\)\s*=\s*(.+)", original, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    match = re.search(r"grafico de\s+(.+)", original, flags=re.IGNORECASE)
    if match:
        expr = match.group(1).strip()
        expr = re.sub(r"\bde\s*-?\d+(?:\.\d+)?\s*(?:a|ate)\s*-?\d+(?:\.\d+)?\b", "", expr).strip()
        return expr
    return None


def gerar_grafico_funcao(comando: str, base_dir: str) -> str:
    expr_txt = _extrair_funcao_grafico(comando)
    if not expr_txt:
        return "Nao consegui identificar a função para o gráfico. Exemplo: grafico de f(x)=x^2 - 3x + 2."

    try:
        expr = _sympy_expr(expr_txt)
    except Exception:
        return "Nao consegui interpretar a função para o gráfico."

    x = sp.symbols("x")
    f = sp.lambdify(x, expr, modules=["numpy", "math"])
    x0, x1 = _extrair_intervalo(comando)
    if x0 == x1:
        x0, x1 = -10.0, 10.0
    xs = np.linspace(x0, x1, 400)
    try:
        ys = f(xs)
    except Exception:
        return "Erro ao avaliar a função no intervalo informado."

    pasta = os.path.join(base_dir, "gráficos")
    os.makedirs(pasta, exist_ok=True)
    nome = f"grafico_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    caminho = os.path.join(pasta, nome)

    plt.figure(figsize=(8, 4.5))
    plt.plot(xs, ys)
    plt.title(f"f(x) = {expr_txt}")
    plt.xlabel("x")
    plt.ylabel("f(x)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(caminho, dpi=140)
    plt.close()

    return f"Grafico gerado: {caminho}"


def simular_lancamento(comando: str, base_dir: str) -> str:
    texto = _normalizar_texto(comando)
    g = 9.81
    v0 = 20.0
    ang = 45.0
    h0 = 0.0

    match_v = re.search(r"v0\s*=?\s*(-?\d+(?:\.\d+)?)", texto)
    if match_v:
        v0 = float(match_v.group(1))
    match_a = re.search(r"angulo\s*=?\s*(-?\d+(?:\.\d+)?)", texto)
    if match_a:
        ang = float(match_a.group(1))
    match_h = re.search(r"altura\s*=?\s*(-?\d+(?:\.\d+)?)", texto)
    if match_h:
        h0 = float(match_h.group(1))

    rad = math.radians(ang)
    vx = v0 * math.cos(rad)
    vy = v0 * math.sin(rad)

    # tempo total aproximado
    disc = vy**2 + 2 * g * h0
    t_total = (vy + math.sqrt(max(0.0, disc))) / g if g > 0 else 0
    ts = np.linspace(0, max(t_total, 0.1), 300)
    xs = vx * ts
    ys = h0 + vy * ts - 0.5 * g * ts**2
    ys = np.maximum(ys, 0)

    pasta = os.path.join(base_dir, "graficos")
    os.makedirs(pasta, exist_ok=True)
    nome = f"lancamento_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    caminho = os.path.join(pasta, nome)

    plt.figure(figsize=(8, 4.5))
    plt.plot(xs, ys)
    plt.title("Lancamento obliquo")
    plt.xlabel("x (m)")
    plt.ylabel("y (m)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(caminho, dpi=140)
    plt.close()

    alcance = xs[-1]
    altura_max = float(np.max(ys))
    return f"Simulacao pronta. Alcance ~ {alcance:.2f} m, altura max ~ {altura_max:.2f} m. Grafico: {caminho}"


def simular_osc_harmonica(comando: str, base_dir: str) -> str:
    texto = _normalizar_texto(comando)
    A = 1.0
    w = 2.0
    fase = 0.0
    dur = 10.0

    mA = re.search(r"amplitude\s*=?\s*(-?\d+(?:\.\d+)?)", texto)
    if mA:
        A = float(mA.group(1))
    mw = re.search(r"omega\s*=?\s*(-?\d+(?:\.\d+)?)", texto)
    if mw:
        w = float(mw.group(1))
    mf = re.search(r"fase\s*=?\s*(-?\d+(?:\.\d+)?)", texto)
    if mf:
        fase = float(mf.group(1))
    md = re.search(r"duracao\s*=?\s*(-?\d+(?:\.\d+)?)", texto)
    if md:
        dur = max(0.1, float(md.group(1)))

    ts = np.linspace(0, dur, 400)
    xs = A * np.cos(w * ts + fase)

    pasta = os.path.join(base_dir, "graficos")
    os.makedirs(pasta, exist_ok=True)
    nome = f"oscilacao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    caminho = os.path.join(pasta, nome)

    plt.figure(figsize=(8, 4.5))
    plt.plot(ts, xs)
    plt.title("Oscilacao harmonica")
    plt.xlabel("t (s)")
    plt.ylabel("x (m)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(caminho, dpi=140)
    plt.close()

    return f"Simulação pronta. Gráfico: {caminho}"
