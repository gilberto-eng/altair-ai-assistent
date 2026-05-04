import importlib
import math
import os
import re
import threading
import unicodedata
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib
import numpy as np
import numpy.typing as npt
import sympy as sp

try:
    from cad_library_catalog import ensure_catalog, search_catalog
except ImportError:  # pragma: no cover - fallback for package imports
    from src.altair.core.cad_library_catalog import ensure_catalog, search_catalog

try:
    from cad_langchain import planejar_cad_com_langchain
except ImportError:  # pragma: no cover - fallback for package imports
    from src.altair.core.cad_langchain import planejar_cad_com_langchain

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cadquery import exporters
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMACOES = standard_transformations + (implicit_multiplication_application,)
MODO_RESPOSTA_BONITA_PADRAO: bool = True

UNIDADES_EXTENSO: Dict[str, int] = {
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
DEZENAS_EXTENSO: Dict[str, int] = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
CENTENAS_EXTENSO: Dict[str, int] = {
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
ESCALAS_EXTENSO: Dict[str, int] = {
    "mil": 1000,
    "milhao": 1000000,
    "milhoes": 1000000,
}
TOKEN_NUMERO_EXTENSO: set[str] = (
    set(UNIDADES_EXTENSO)
    | set(DEZENAS_EXTENSO)
    | set(CENTENAS_EXTENSO)
    | set(ESCALAS_EXTENSO)
    | {"e", "menos", "ponto", "virgula"}
)

SIMPLE_PIECE_CLASSES = {"Cube", "Box", "Cylinder", "Sphere", "Plate", "Rod"}
SIMPLE_CANONICAL_NAMES = {
    "Cube": "cubo",
    "Box": "box",
    "Cylinder": "cilindro",
    "Sphere": "esfera",
    "Plate": "placa",
    "Rod": "eixo",
}
QUANTIFIERS: Dict[str, int] = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
}


def _sem_acentos(texto: Optional[str]) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return texto.encode("ASCII", "ignore").decode("utf-8")


def _normalizar_texto(texto: str) -> str:
    texto = _sem_acentos(texto).lower().strip()
    texto = texto.replace(",", ".")
    texto = re.sub(r"\s+", " ", texto)
    texto = converter_numeros_por_extenso(texto)
    return texto


def _parse_inteiro_extenso(tokens: List[str]) -> Optional[int]:
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


def _numero_por_extenso_para_float(frase: str) -> Optional[float]:
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


def converter_numeros_por_extenso(texto: str) -> str:
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


def _sympy_expr(expr: str) -> sp.Expr:
    expr = normalizar_expressao(expr)
    return parse_expr(expr, transformations=TRANSFORMACOES)


def _equacao_para_sympy(texto_eq: str) -> sp.Eq:
    texto_eq = (texto_eq or "").strip()
    if "=" in texto_eq:
        esquerda, direita = texto_eq.split("=", 1)
        return sp.Eq(_sympy_expr(esquerda), _sympy_expr(direita))
    return sp.Eq(_sympy_expr(texto_eq), 0)


def _resolver_sistema_texto(comando: str) -> Optional[List[Dict[str, Any]]]:
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
    variaveis = sorted(set().union(*[eq.free_symbols for eq in equacoes]), key=lambda v: str(v.name))
    return sp.solve(equacoes, variaveis, dict=True)


def _resolver_raizes_equacao(comando: str) -> Optional[List[Union[float, sp.Expr]]]:
    texto = _normalizar_texto(comando)
    texto = re.sub(r"\b(encontre|achar|ache|calcule|quais|as|os|raizes?|raiz|da|de|equacao)\b", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        return None
    eq = _equacao_para_sympy(texto)
    x = sp.symbols("x")
    return sp.solve(eq, x)


def interpretar_matematica(comando: str) -> Optional[Any]:
    comando_original = (comando or "").strip()
    if not comando_original:
        return None

    comando = _normalizar_texto(comando_original)
    if not re.search(
        r"\b(calcular|calcule|resolve|resolva|resolver|somar|subtrair|multiplicar|dividir|raiz|raiz quadrada|\d)\b",
        comando,
    ):
        return None

    resultado = _resolver_sistema_texto(comando)
    if resultado is not None:
        return resultado

    resultado = _resolver_raizes_equacao(comando)
    if resultado is not None:
        return resultado

    try:
        expr = _sympy_expr(comando)
        if expr.free_symbols:
            return expr
        return sp.N(expr)
    except Exception:
        return None


def normalizar_expressao(expr: str) -> str:
    expr = _normalizar_texto(expr)
    expr = expr.replace("^", "**")
    expr = re.sub(r"\b(raiz quadrada de|raiz de)\b", "sqrt", expr)
    return expr


def formatar_expressao_para_fala(texto: str) -> str:
    return texto.replace("**", " elevado a ").replace("/", " dividido por ")


def formatar_numero_para_fala(numero: Any) -> str:
    try:
        valor = float(numero)
        if abs(valor - int(valor)) < 1e-12:
            return str(int(valor))
        return str(valor)
    except Exception:
        return str(numero)


def formatar_resultado_matematico(resultado: Any, modo_bonito: bool = True) -> str:
    if isinstance(resultado, list):
        return ", ".join(str(item) for item in resultado)
    return str(resultado)


def resolver_equacao_direta(comando: str) -> Optional[Any]:
    return interpretar_matematica(comando)


def _project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    except Exception:
        return os.getcwd()


def _strip_debug_prefix(texto: str) -> str:
    return re.sub(
        r"^\s*debug\s*:\s*comando\s*recebido\s*->\s*",
        "",
        texto or "",
        flags=re.IGNORECASE,
    ).strip()


def _canonical_simple_name(nome: str) -> str:
    alias = {
        "cubo": "cubo",
        "cube": "cubo",
        "box": "box",
        "caixa": "box",
        "cilindro": "cilindro",
        "cylinder": "cilindro",
        "esfera": "esfera",
        "sphere": "esfera",
        "placa": "placa",
        "plate": "placa",
        "eixo": "eixo",
        "shaft": "eixo",
        "rod": "eixo",
        "bearing": "bearing",
        "screw": "screw",
        "bolt": "screw",
        "nut": "nut",
    }
    chave = _sem_acentos(nome).lower().strip()
    return alias.get(chave, chave)


def _detectar_duas_engrenagens_com_eixo(cmd_norm: str) -> bool:
    tem_engrenagem = bool(re.search(r"\b(engrenagem|engrenagens|gear|gears)\b", cmd_norm))
    tem_eixo = bool(re.search(r"\b(eixo|shaft|axle)\b", cmd_norm))
    if not (tem_engrenagem and tem_eixo):
        return False

    if re.search(r"\b(2|duas|dois)\s+(engrenagem|engrenagens|gear|gears)\b", cmd_norm):
        return True

    return bool(re.search(r"\bengrenagens\b|\bgears\b", cmd_norm))


def _abrir_visualizador_arquivo(caminho: str) -> None:
    caminho_abs = os.path.abspath(caminho)

    def _run() -> None:
        try:
            import pyvista as pv

            mesh = pv.read(caminho_abs)
            plotter = pv.Plotter(title="Altair CAD Viewer")
            plotter.set_background("#08111e")
            plotter.add_axes()
            plotter.add_mesh(mesh, color="#9fc1e8", show_edges=True)
            plotter.show()
            return
        except Exception:
            pass

        try:
            os.startfile(caminho_abs)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def _solid_from_name(cq: Any, nome: str) -> Any:
    nome = _canonical_simple_name(nome)

    if nome in ("cubo", "box"):
        return cq.Workplane("XY").box(32, 32, 32)
    if nome == "cilindro":
        return cq.Workplane("XY").circle(12).extrude(36)
    if nome == "esfera":
        return cq.Workplane("XY").sphere(16)
    if nome == "eixo":
        return cq.Workplane("XY").circle(5).extrude(60)
    if nome == "placa":
        return cq.Workplane("XY").box(60, 40, 8)
    if nome == "bearing":
        outer = cq.Workplane("XY").circle(12).extrude(6)
        inner = cq.Workplane("XY").circle(6).extrude(6)
        return outer.cut(inner)
    if nome in ("screw", "bolt"):
        shaft = cq.Workplane("XY").circle(2.5).extrude(24)
        head = cq.Workplane("XY").circle(4.5).extrude(4).translate((0, 0, 20))
        return shaft.union(head)
    if nome == "nut":
        return cq.Workplane("XY").polygon(6, 8).extrude(4).faces(">Z").workplane().hole(3.2)
    if nome in ("engrenagem", "gear"):
        dentes = 18
        raio_base = 17
        altura_dente = 3.2
        espessura = 9.5
        largura_dente = 3.2
        gear = cq.Workplane("XY").circle(raio_base).extrude(espessura)
        for idx in range(dentes):
            ang = (2.0 * math.pi * idx) / dentes
            dente = (
                cq.Workplane("XY")
                .center((raio_base + altura_dente / 2.0) * math.cos(ang), (raio_base + altura_dente / 2.0) * math.sin(ang))
                .transformed(rotate=(0, 0, math.degrees(ang)))
                .rect(largura_dente, altura_dente)
                .extrude(espessura)
            )
            gear = gear.union(dente)
        return gear.faces(">Z").workplane().hole(8.3)

    return cq.Workplane("XY").box(30, 30, 30)


def _exportar_modelo_stl(modelo: Any, prefixo: str) -> str:
    try:
        import cadquery as cq

        if isinstance(modelo, cq.Assembly):
            try:
                modelo = modelo.toCompound()
            except Exception:
                pass
        if isinstance(modelo, cq.Workplane):
            try:
                modelo = modelo.val()
            except Exception:
                try:
                    modelo = modelo.findSolid()
                except Exception:
                    pass
    except Exception:
        pass

    output_dir = os.path.join(_project_root(), "data", "cad")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{prefixo}_{uuid.uuid4().hex[:8]}.stl")
    exporters.export(modelo, output_file, exportType="STL")
    return output_file


def _gerar_modelo_duas_engrenagens_com_eixo(_comando: str, _base_dir: str) -> Dict[str, str]:
    try:
        import cadquery as cq
    except Exception as exc:
        return {"visual": f"Nao consegui gerar CAD local (cadquery indisponivel): {exc}", "fala": ""}

    try:
        eixo = _solid_from_name(cq, "eixo").translate((0, 0, -10))
        gear_a = _solid_from_name(cq, "engrenagem").translate((0, 0, 10))
        gear_b = _solid_from_name(cq, "engrenagem").translate((0, 0, 34))
        modelo = eixo.union(gear_a).union(gear_b)

        output_file = _exportar_modelo_stl(modelo, "duas_engrenagens_eixo")
        _abrir_visualizador_arquivo(output_file)

        return {
            "visual": f"Modelo 3D gerado com sucesso: {output_file}",
            "fala": "Modelo 3D de duas engrenagens com eixo gerado.",
            "file": output_file,
        }
    except Exception as exc:
        return {"visual": f"Falha ao gerar o modelo 3D de engrenagens: {exc}", "fala": ""}


def _gerar_peca_simples_local(nome_peca: str) -> Dict[str, str]:
    try:
        import cadquery as cq

        modelo = _solid_from_name(cq, nome_peca)
        output_file = _exportar_modelo_stl(modelo, f"peca_{_canonical_simple_name(nome_peca)}")
        _abrir_visualizador_arquivo(output_file)
        return {
            "visual": f"Peca CAD gerada: {output_file}",
            "fala": "Peca CAD gerada.",
            "file": output_file,
        }
    except Exception as exc:
        return {"visual": f"Nao consegui gerar a peca CAD localmente: {exc}", "fala": ""}


def _valor_padrao_parametro(nome: str, entry: Optional[Dict[str, Any]] = None) -> float:
    nome_norm = _sem_acentos(nome).replace(" ", "_")
    classe = _sem_acentos(str((entry or {}).get("class", "")))

    if nome_norm in {"module", "modulo"}:
        return 2.0 if "gear" in classe else 1.0
    if any(chave in nome_norm for chave in {"teeth", "dentes", "number", "count", "quantidade"}):
        return 16.0
    if any(chave in nome_norm for chave in {"radius", "raio", "diameter", "diametro", "size"}):
        return 10.0
    if any(chave in nome_norm for chave in {"length", "comprimento", "width", "largura", "height", "altura"}):
        return 20.0
    if any(chave in nome_norm for chave in {"thickness", "espessura", "face_width"}):
        return 5.0
    if any(chave in nome_norm for chave in {"pressure_angle"}):
        return 20.0
    if any(chave in nome_norm for chave in {"helix_angle", "cone_angle", "twist_angle", "angle"}):
        return 0.0 if "helix" in nome_norm else 45.0
    if any(chave in nome_norm for chave in {"clearance", "backlash"}):
        return 0.1
    if nome_norm in {"x", "y", "z"}:
        return 0.0
    if nome_norm == "step":
        return 1.0
    return 1.0


def _montar_kwargs_para_entrada(entry: Dict[str, Any], classe: Any) -> Dict[str, float]:
    import inspect

    nomes_parametros: List[str] = []
    try:
        assinatura = inspect.signature(classe)
        for nome, parametro in assinatura.parameters.items():
            if nome == "self":
                continue
            if parametro.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
                continue
            nomes_parametros.append(nome)
    except Exception:
        pass

    if not nomes_parametros:
        nomes_parametros = [str(p) for p in entry.get("params", [])]

    kwargs: Dict[str, float] = {}
    for nome in nomes_parametros:
        kwargs[nome] = _valor_padrao_parametro(nome, entry)
    return kwargs


def _tentar_instanciar_entrada_catalogo(entry: Dict[str, Any]) -> Optional[Any]:
    modulo_nome = str(entry.get("module", "")).strip()
    classe_nome = str(entry.get("class", "")).strip()
    if not modulo_nome or not classe_nome:
        return None

    try:
        modulo = importlib.import_module(modulo_nome)
        classe = getattr(modulo, classe_nome)
    except Exception:
        return None

    kwargs = _montar_kwargs_para_entrada(entry, classe)
    candidatos = []
    if kwargs:
        candidatos.append(kwargs)
    candidatos.append({})

    for payload in candidatos:
        try:
            objeto = classe(**payload)
        except Exception:
            continue
        for metodo in ("build", "make"):
            func = getattr(objeto, metodo, None)
            if callable(func):
                try:
                    resultado = func()
                    if resultado is not None:
                        return resultado
                except Exception:
                    pass
        return objeto

    return None


def _construir_modelo_catalogo(entry: Dict[str, Any]) -> Optional[Any]:
    classe = str(entry.get("class", ""))
    if classe in SIMPLE_PIECE_CLASSES:
        try:
            import cadquery as cq

            return _solid_from_name(cq, SIMPLE_CANONICAL_NAMES.get(classe, classe))
        except Exception:
            return None

    if classe in {"Bearing", "Screw", "Nut"}:
        try:
            import cadquery as cq

            nome_base = _canonical_simple_name(classe)
            return _solid_from_name(cq, nome_base)
        except Exception:
            return None

    objeto = _tentar_instanciar_entrada_catalogo(entry)
    if objeto is not None:
        return objeto

    try:
        import cadquery as cq

        nome_base = SIMPLE_CANONICAL_NAMES.get(classe, _canonical_simple_name(classe))
        return _solid_from_name(cq, nome_base)
    except Exception:
        return None


def _gerar_peca_do_catalogo(entry: Dict[str, Any], base_dir: str) -> Dict[str, str]:
    modelo = _construir_modelo_catalogo(entry)
    if modelo is None:
        return {
            "visual": f"Nao consegui construir a peca '{entry.get('class', '')}' a partir do catalogo.",
            "fala": "",
        }

    prefixo = f"peca_{_sem_acentos(str(entry.get('class', 'peca'))).replace(' ', '_')}"
    output_file = _exportar_modelo_stl(modelo, prefixo)
    _abrir_visualizador_arquivo(output_file)
    return {
        "visual": f"Peca do catalogo gerada: {entry.get('class')} -> {output_file}",
        "fala": f"Peca {entry.get('class')} gerada.",
        "file": output_file,
    }


def _resolver_entrada_catalogo(query: str, catalog: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    matches = search_catalog(catalog, query, limit=5)
    if not matches:
        return None
    return matches[0]


def _extrair_pedidos_de_peca(comando: str, catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    cmd_norm = _normalizar_texto(comando)
    aliases: List[str] = []
    for entry in catalog.get("entries", []):
        for alias in entry.get("aliases", []):
            alias_norm = _sem_acentos(str(alias))
            if alias_norm and len(alias_norm) >= 3:
                aliases.append(alias_norm)
    aliases = sorted(set(aliases), key=lambda s: (-len(s), s))

    pedidos: List[Dict[str, Any]] = []
    ocupados: List[Tuple[int, int]] = []
    for alias in aliases:
        pattern = re.compile(
            rf"\b(?:(?P<qty>\d+|uma|um|duas|dois|tres|quatro|cinco)\s+)?{re.escape(alias)}\b"
        )
        for match in pattern.finditer(cmd_norm):
            inicio, fim = match.span()
            if any(not (fim <= s or inicio >= e) for s, e in ocupados):
                continue
            qty_txt = match.group("qty") or ""
            quantidade = QUANTIFIERS.get(qty_txt, 1)
            entry = _resolver_entrada_catalogo(alias, catalog)
            if entry is None:
                continue
            pedidos.append(
                {
                    "query": alias,
                    "quantity": quantidade,
                    "entry": entry,
                    "span": (inicio, fim),
                }
            )
            ocupados.append((inicio, fim))

    if pedidos:
        return pedidos

    top = search_catalog(catalog, cmd_norm, limit=1)
    if top:
        pedidos.append(
            {
                "query": cmd_norm,
                "quantity": 1,
                "entry": top[0],
                "span": (0, len(cmd_norm)),
            }
        )
    return pedidos


def _gerar_assembly_catalogo(pedidos: List[Dict[str, Any]], base_dir: str) -> Dict[str, str]:
    try:
        import cadquery as cq
    except Exception as exc:
        return {"visual": f"Nao consegui gerar assembly CAD (cadquery indisponivel): {exc}", "fala": ""}

    assembly = cq.Assembly()
    itens: List[str] = []
    cursor = 0.0
    for pedido in pedidos:
        entry = pedido.get("entry") or {}
        quantidade = int(pedido.get("quantity", 1))
        for _ in range(max(1, quantidade)):
            modelo = _construir_modelo_catalogo(entry)
            if modelo is None:
                continue
            nome_item = str(entry.get("class", "peca"))
            itens.append(nome_item)
            try:
                assembly.add(modelo, name=f"{nome_item}_{len(itens)}", loc=cq.Location(cq.Vector(cursor, 0, 0)))
            except Exception:
                assembly.add(modelo)
            cursor += 45.0

    if not itens:
        return {"visual": "Nao consegui montar nenhuma peca do catalogo para o assembly.", "fala": ""}

    output_file = _exportar_modelo_stl(assembly, "assembly_catalogo")
    _abrir_visualizador_arquivo(output_file)
    return {
        "visual": f"Assembly catalogado gerado com {len(itens)} pecas: {output_file}",
        "fala": "Assembly gerado a partir do catalogo.",
        "file": output_file,
    }


def gerar_projeto_cad(comando: str, ia_llm: Any, base_dir: str) -> Dict[str, str]:
    """Entrada usada pelo intent_router."""
    cmd = _strip_debug_prefix(comando or "")
    cmd_norm = _normalizar_texto(cmd)

    if _detectar_duas_engrenagens_com_eixo(cmd_norm):
        return _gerar_modelo_duas_engrenagens_com_eixo(cmd, base_dir)

    catalog_path = os.path.join(_project_root(), "data", "json", "cad_library_catalog.json")
    catalog = ensure_catalog(catalog_path)
    pedidos = _extrair_pedidos_de_peca(cmd, catalog)
    pedidos_langchain = _pedidos_do_plano_langchain(cmd, catalog, ia_llm)
    if pedidos_langchain:
        pedidos = pedidos_langchain

    if len(pedidos) >= 2:
        return gerar_assembly_cad(cmd, ia_llm, base_dir)

    if len(pedidos) == 1:
        pedido = pedidos[0]
        entry = pedido.get("entry") or {}
        classe = str(entry.get("class", ""))
        quantidade = int(pedido.get("quantity", 1))
        if quantidade > 1:
            return _gerar_assembly_catalogo(pedidos, base_dir)
        if classe in SIMPLE_PIECE_CLASSES:
            return _gerar_peca_simples_local(SIMPLE_CANONICAL_NAMES.get(classe, classe))
        return _gerar_peca_do_catalogo(entry, base_dir)

    top = search_catalog(catalog, cmd_norm, limit=1)
    if top:
        entry = top[0]
        classe = str(entry.get("class", ""))
        if classe in SIMPLE_PIECE_CLASSES:
            return _gerar_peca_simples_local(SIMPLE_CANONICAL_NAMES.get(classe, classe))
        return _gerar_peca_do_catalogo(entry, base_dir)

    return {
        "visual": "Nao identifiquei a peca do CAD. Exemplo: 'duas engrenagens com um eixo' ou 'cubo com cilindro'.",
        "fala": "",
    }


def gerar_assembly_cad(comando: str, ia_llm: Any, base_dir: str) -> Dict[str, str]:
    cmd = _strip_debug_prefix(comando or "")
    catalog_path = os.path.join(_project_root(), "data", "json", "cad_library_catalog.json")
    catalog = ensure_catalog(catalog_path)
    pedidos = _extrair_pedidos_de_peca(cmd, catalog)
    pedidos_langchain = _pedidos_do_plano_langchain(cmd, catalog, ia_llm)
    if pedidos_langchain:
        pedidos = pedidos_langchain

    if not pedidos:
        return {"visual": "Nao consegui identificar pecas para montar o assembly.", "fala": ""}

    if len(pedidos) == 1 and int(pedidos[0].get("quantity", 1)) <= 1:
        entry = pedidos[0].get("entry") or {}
        return _gerar_peca_do_catalogo(entry, base_dir)

    return _gerar_assembly_catalogo(pedidos, base_dir)







def _pedidos_do_plano_langchain(
    comando: str,
    catalogo: Dict[str, Any],
    llm: Any,
) -> Optional[List[Dict[str, Any]]]:
    plano = planejar_cad_com_langchain(comando, catalogo, llm)
    if not isinstance(plano, dict):
        return None

    pedidos_raw = plano.get("pieces", [])
    if not isinstance(pedidos_raw, list):
        return None

    pedidos: Dict[str, Dict[str, Any]] = {}
    for item in pedidos_raw:
        if not isinstance(item, dict):
            continue

        chave = str(item.get("class", "") or item.get("query", "")).strip()
        if not chave:
            continue

        entry = _resolver_entrada_catalogo(chave, catalogo)
        if entry is None:
            continue

        classe = str(entry.get("class", "")).strip()
        if not classe:
            continue

        try:
            quantidade = int(item.get("quantity", 1))
        except Exception:
            quantidade = 1
        quantidade = max(1, min(quantidade, 12))

        params = item.get("params", {})
        if not isinstance(params, dict):
            params = {}

        if classe in pedidos:
            pedidos[classe]["quantity"] += quantidade
            continue

        pedidos[classe] = {
            "query": str(item.get("query", "") or chave).strip() or classe,
            "quantity": quantidade,
            "entry": entry,
            "span": (0, 0),
            "params": params,
            "source": "langchain",
        }

    if not pedidos:
        return None

    return list(pedidos.values())





