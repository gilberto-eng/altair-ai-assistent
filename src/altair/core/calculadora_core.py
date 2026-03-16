import re
import subprocess
import time
import unicodedata

from automacao_core import abrir_aplicativo
from matematica_core import converter_numeros_por_extenso


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ASCII", "ignore").decode("utf-8")
    texto = re.sub(r"\s+", " ", texto).strip().lower()
    return texto


def extrair_expressao_calculadora(comando_original: str, comando_normalizado: str):
    comando_normalizado = converter_numeros_por_extenso(comando_normalizado)
    padroes_diretos = [
        r"(?:entre|entra|abra|abrir|inicie|iniciar).{0,30}calculadora.{0,20}(?:calcule|calcular|resolva|fa[çc]a)\s+(.+)$",
        r"(?:calcule|calcular|resolva|fa[çc]a)\s+(.+?)\s+(?:na|no)\s+calculadora\b",
        r"(?:na|no)\s+calculadora.{0,20}(?:calcule|calcular|resolva|fa[çc]a)\s+(.+)$",
    ]
    for padrao in padroes_diretos:
        match = re.search(padrao, comando_original, re.IGNORECASE)
        if match:
            expr = (match.group(1) or "").strip()
            if expr:
                return expr

    op_especifica = re.search(r"\bmultiplique\s+([0-9.,]+)\s*(?:x|vezes|por)\s*([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        a = op_especifica.group(1).replace(",", ".")
        b = op_especifica.group(2).replace(",", ".")
        return f"{a}*{b}"

    op_especifica = re.search(r"\bsome\s+([0-9.,]+)\s*(?:e|com|mais)\s*([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        a = op_especifica.group(1).replace(",", ".")
        b = op_especifica.group(2).replace(",", ".")
        return f"{a}+{b}"

    op_especifica = re.search(r"\bdivida\s+([0-9.,]+)\s+por\s+([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        a = op_especifica.group(1).replace(",", ".")
        b = op_especifica.group(2).replace(",", ".")
        return f"{a}/{b}"

    op_especifica = re.search(r"\bsubtraia\s+([0-9.,]+)\s+de\s+([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        a = op_especifica.group(1).replace(",", ".")
        b = op_especifica.group(2).replace(",", ".")
        return f"{b}-{a}"

    op_especifica = re.search(r"\b([0-9.,]+)\s*(?:%|por cento)\s+de\s+([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        p = op_especifica.group(1).replace(",", ".")
        base = op_especifica.group(2).replace(",", ".")
        return f"({p}/100)*{base}"

    op_especifica = re.search(r"\bquanto\s+e\s+([0-9.,]+)\s+por\s+cento\s+de\s+([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        p = op_especifica.group(1).replace(",", ".")
        base = op_especifica.group(2).replace(",", ".")
        return f"({p}/100)*{base}"

    op_especifica = re.search(r"\b([0-9.,]+)\s*(?:\^|elevado a)\s*([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        a = op_especifica.group(1).replace(",", ".")
        b = op_especifica.group(2).replace(",", ".")
        return f"{a}**{b}"

    op_especifica = re.search(r"\braiz(?: quadrada)? de\s+([0-9.,]+)\b", comando_normalizado)
    if op_especifica:
        n = op_especifica.group(1).replace(",", ".")
        return f"({n})**0.5"

    if "calculadora" in comando_normalizado:
        return comando_original
    return None


def normalizar_expressao_calculadora(texto: str):
    expr = normalizar_texto(texto)
    expr = converter_numeros_por_extenso(expr)
    if not expr:
        return None

    expr = re.sub(r"^(?:calcule|calcular|resolva|faca|quanto e|resultado de)\s+", "", expr).strip()

    substituicoes = [
        (r"\bmais\b", "+"),
        (r"\bmenos\b", "-"),
        (r"\bdividido por\b", "/"),
        (r"\bdivida\b", "/"),
        (r"\bpor cento\b", "%"),
        (r"\belevado a\b", "^"),
        (r"\bvezes\b", "*"),
        (r"\bx\b", "*"),
    ]
    for padrao, alvo in substituicoes:
        expr = re.sub(padrao, alvo, expr)

    expr = re.sub(r"(?<=\d)\s+por\s+(?=\d)", "*", expr)
    expr = expr.replace(",", ".")
    expr = expr.replace("^", "**")
    expr = re.sub(r"(\d+(?:\.\d+)?)%\s*de\s*(\d+(?:\.\d+)?)", r"(\1/100)*\2", expr)
    expr = re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", expr)
    expr = re.sub(r"raiz(?:quadrada)?de(\d+(?:\.\d+)?)", r"(\1)**0.5", expr)
    expr = re.sub(r"\s+", "", expr)

    if not expr:
        return None
    if not re.fullmatch(r"[0-9+\-*/().%]+", expr):
        return None
    if not re.search(r"[+\-*/%]", expr):
        return None
    return expr


def interpretar_comando_calculadora(comando_original: str):
    comando_normalizado = normalizar_texto(comando_original)
    if "calculadora" not in comando_normalizado:
        return {"match": False}

    gatilho = re.search(
        r"\b(calcule|calcular|resolva|faca|quanto e|some|subtraia|divida|multiplique|x|vezes|mais|menos|raiz|elevado|potencia|por cento|%)\b",
        comando_normalizado,
    )
    if not gatilho:
        return {"match": False}

    expr_bruta = extrair_expressao_calculadora(comando_original, comando_normalizado)
    expr = normalizar_expressao_calculadora(expr_bruta or "")
    if expr:
        return {"match": True, "expressao": expr}
    return {"match": True, "erro": "Nao consegui interpretar a operacao para a calculadora."}


def avaliar_expressao_calculadora(expr: str):
    return eval(expr, {"__builtins__": {}}, {})


def expandir_potencia_para_calculadora(expr: str):
    def _expandir(match):
        base = match.group(1)
        expoente_raw = match.group(2)
        try:
            expoente = float(expoente_raw)
        except Exception:
            return match.group(0)

        if expoente.is_integer() and 0 <= int(expoente) <= 10:
            exp_i = int(expoente)
            if exp_i == 0:
                return "1"
            if exp_i == 1:
                return base
            return "(" + "*".join([base] * exp_i) + ")"
        return match.group(0)

    padrao = re.compile(r"(\d+(?:\.\d+)?|\([^)]+\))\*\*(-?\d+(?:\.\d+)?)")
    atual = expr
    for _ in range(4):
        novo = padrao.sub(_expandir, atual)
        if novo == atual:
            break
        atual = novo
    return atual


def montar_sendkeys_calculadora(expr: str):
    expr = expandir_potencia_para_calculadora(expr)
    mapa = {
        "+": "{ADD}",
        "-": "{SUBTRACT}",
        "*": "{MULTIPLY}",
        "/": "{DIVIDE}",
        "(": "{(}",
        ")": "{)}",
        "%": "{%}",
    }
    return "".join(mapa.get(ch, ch) for ch in expr)


def executar_calculo_na_calculadora(expr: str):
    abrir_aplicativo("calculadora")
    time.sleep(1.0)

    expr_para_calc = expandir_potencia_para_calculadora(expr)
    if "**" in expr_para_calc:
        expr_para_calc = str(avaliar_expressao_calculadora(expr))

    teclas_expr = montar_sendkeys_calculadora(expr_para_calc)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$ok = $ws.AppActivate('Calculadora'); "
        "if (-not $ok) { $ok = $ws.AppActivate('Calculator') }; "
        "if (-not $ok) { Write-Output 'ERRO:NAO_ATIVOU'; exit 1 }; "
        "Start-Sleep -Milliseconds 250; "
        "$ws.SendKeys('{ESC}'); "
        "Start-Sleep -Milliseconds 80; "
        f"$ws.SendKeys('{teclas_expr}'); "
        "Start-Sleep -Milliseconds 80; "
        "$ws.SendKeys('{ENTER}'); "
        "Write-Output 'OK'"
    )
    resultado = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    saida = (resultado.stdout or "").strip()
    if resultado.returncode != 0:
        erro = (resultado.stderr or saida or "falha ao enviar teclas para a calculadora").strip()
        return False, erro
    return True, "operacao executada na calculadora"
