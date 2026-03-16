import datetime
import json
import datetime
import math
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cad_viewer import abrir_viewer_parametrico


def _project_root() -> str:
    try:
        return str(Path(__file__).resolve().parents[3])
    except Exception:
        return os.getcwd()
import cad_library_catalog


def _ensure_sys_path(paths: List[str]) -> None:
    for p in paths:
        if not p:
            continue
        if p not in sys.path and os.path.isdir(p):
            sys.path.insert(0, p)


def _import_module_safe(module_name: str) -> Optional[Any]:
    try:
        return __import__(module_name, fromlist=["*"])
    except Exception:
        return None

def _safe_float(value: Any, default: float) -> float:
    try:
        if isinstance(value, dict):
            value = value.get("default", default)
        if isinstance(value, str):
            value = value.replace(",", ".").strip()
        return float(value)
    except Exception:
        return float(default)

def _sanitizar_codigo(codigo: str) -> str:
    if not codigo:
        return ""
    # Normaliza aspas tipográficas que quebram o parser Python.
    substituicoes = {
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
    }
    for antigo, novo in substituicoes.items():
        codigo = codigo.replace(antigo, novo)
    codigo = _aplicar_hotfixes_cadquery(codigo)
    return codigo


def _aplicar_hotfixes_cadquery(codigo: str) -> str:
    # Hotfix: alguns geradores criam dentes como wire e fazem union sem extrude.
    codigo = re.sub(r"\bcqparts_assembly\b", "cq", codigo)
    linhas = codigo.splitlines()
    if not linhas:
        return codigo

    # Heuristica simples para escolher espessura.
    espessura = "1.0"
    if "largura" in codigo:
        espessura = "largura"
    elif "altura" in codigo:
        espessura = "altura"
    elif "espessura" in codigo:
        espessura = "espessura"
    elif "modulo" in codigo:
        espessura = "modulo"

    novas = []
    for linha in linhas:
        lstr = linha.strip()
        # Hotfix: normaliza argumentos do cq_gears.SpurGear
        if "cq_gears.SpurGear" in linha:
            linha = re.sub(r"\bteeth\s*=", "teeth_number=", linha)
            linha = re.sub(r"\bnum_teeth\s*=", "teeth_number=", linha)
            linha = re.sub(r"\btooth_width\s*=", "width=", linha)
            linha = re.sub(r"\bthickness\s*=", "width=", linha)
            linha = re.sub(r"\bbore_diameter\s*=", "bore_d=", linha)
            linha = re.sub(r"\bpitch_diameter\s*=\s*[^,\n)]+,?\s*", "", linha)
        if "dente" in lstr and lstr.startswith("dente") and " = " in lstr:
            if ".extrude(" not in lstr:
                # Se for uma cadeia 2D (lineTo/rect/circle/close), adiciona extrude.
                if any(tok in lstr for tok in [".lineTo(", ".rect(", ".circle(", ".close()"]):
                    linha = linha.rstrip() + f".extrude({espessura})"
        # Hotfix: union em Workplane vazio (ex.: coroa_dentes = cq.Workplane('XY')).
        if "coroa_dentes" in lstr and ".union(" in lstr:
            linha = linha.replace("coroa_dentes = coroa_dentes.union(", "coroa_dentes = coroa_dentes.add(")
        novas.append(linha)
    return "\n".join(novas)


def _validar_sintaxe(codigo: str) -> None:
    try:
        compile(codigo, "<string>", "exec")
    except SyntaxError as exc:
        linha = (exc.text or "").rstrip()
        detalhe = f"linha {exc.lineno}, coluna {exc.offset or 0}: {linha}"
        raise RuntimeError(f"Erro de sintaxe no codigo CADQuery ({detalhe}).") from exc


def _normalizar_resultado_export(result: Any) -> Any:
    # CadQuery aceita Workplane/Shape/Solid; alguns retornos ficam sem solido no stack.
    try:
        import cadquery as cq
    except Exception:
        return result

    if isinstance(result, cq.Assembly):
        try:
            return result.toCompound()
        except Exception:
            return result

    if isinstance(result, cq.Workplane):
        try:
            return result.findSolid()
        except Exception:
            pass
        try:
            return result.val()
        except Exception:
            return result
    return result


def _patch_workplane_helix(cq: Any) -> None:
    # Alguns modelos gerados usam .helix(), mas nem todas as versoes expõem isso.
    if hasattr(cq.Workplane, "helix"):
        return

    def _helix(self, pitch: float, height: float, radius: float, angle: float = 360.0, lefthand: bool = False, center=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0)) -> Any:
        wire = cq.Wire.makeHelix(pitch, height, radius, center=center, dir=direction, angle=angle, lefthand=lefthand)
        return self.newObject([wire])

    setattr(cq.Workplane, "helix", _helix)


def _patch_workplane_push(cq: Any) -> None:
    # Alguns geradores usam .push(), mas a API correta é pushPoints().
    if hasattr(cq.Workplane, "push"):
        return

    def _push(self, pts: Any) -> Any:
        try:
            return self.pushPoints(pts)
        except Exception:
            return self

    setattr(cq.Workplane, "push", _push)


def _codigo_requer_params_nome(codigo: str) -> bool:
    if not codigo:
        return False
    chaves = set(re.findall(r"params\[['\"]([a-zA-Z0-9_]+)['\"]\]", codigo))
    return chaves == {"nome"}


def _inferir_defaults_parametros(codigo: str) -> Dict[str, float]:
    if not codigo:
        return {}
    chaves = set()
    for match in re.finditer(r"params\[['\"]([a-zA-Z0-9_]+)['\"]\]", codigo):
        chaves.add(match.group(1))
    for match in re.finditer(r"nome\[['\"]([a-zA-Z0-9_]+)['\"]\]", codigo):
        chaves.add(match.group(1))

    defaults: Dict[str, float] = {}
    for chave in chaves:
        k = chave.lower()
        if "raio_interno" in k:
            defaults[chave] = 5.0
        elif "raio_externo" in k:
            defaults[chave] = 15.0
        elif "numero_de_dentes" in k or "dentes" in k:
            defaults[chave] = 12.0
        elif "altura" in k:
            defaults[chave] = 2.0
        elif "largura" in k:
            defaults[chave] = 5.0
        elif "espessura" in k:
            defaults[chave] = 5.0
        elif "diametro" in k:
            defaults[chave] = 10.0
        elif "comprimento" in k:
            defaults[chave] = 50.0
        else:
            defaults[chave] = 10.0
    return defaults


def _coagir_params_inteiros(params: Dict[str, Any]) -> Dict[str, Any]:
    if not params:
        return params
    coerced = dict(params)
    for k, v in list(coerced.items()):
        nome = str(k).lower()
        if any(tok in nome for tok in ["numero", "dentes", "count", "segments"]):
            try:
                coerced[k] = int(round(float(v)))
            except Exception:
                pass
    return coerced


def _extrair_numero(comando: str, padrao: str) -> Optional[float]:
    match = re.search(padrao, comando, re.IGNORECASE)
    if not match:
        return None
    valor = match.group(1).replace(",", ".").strip()
    try:
        return float(valor)
    except Exception:
        return None


def _parse_params_engrenagem(comando: str) -> Dict[str, float]:
    params: Dict[str, float] = {}
    dentes = _extrair_numero(comando, r"(\d+)\s*(?:dentes|dente)")
    if dentes is not None:
        params["teeth_number"] = float(dentes)

    modulo = _extrair_numero(comando, r"(?:modulo|module)\s*([0-9]+(?:[.,][0-9]+)?)")
    if modulo is not None:
        params["module"] = float(modulo)

    largura = _extrair_numero(comando, r"(?:largura|espessura|width)\s*([0-9]+(?:[.,][0-9]+)?)")
    if largura is not None:
        params["width"] = float(largura)

    furo = _extrair_numero(comando, r"(?:furo|bore|diametro interno|di[aâ]metro interno)\s*([0-9]+(?:[.,][0-9]+)?)")
    if furo is not None:
        params["bore_d"] = float(furo)

    return params


def _parse_params_eixo(comando: str) -> Dict[str, float]:
    params: Dict[str, float] = {}
    diam = _extrair_numero(comando, r"(?:eixo|shaft)\s*([0-9]+(?:[.,][0-9]+)?)\s*mm")
    if diam is None:
        diam = _extrair_numero(comando, r"(?:diametro do eixo|di[aâ]metro do eixo)\s*([0-9]+(?:[.,][0-9]+)?)")
    if diam is not None:
        params["shaft_diameter"] = float(diam)
    comprimento = _extrair_numero(comando, r"(?:comprimento do eixo|shaft length|eixo.*comprimento)\s*([0-9]+(?:[.,][0-9]+)?)")
    if comprimento is not None:
        params["shaft_length"] = float(comprimento)
    return params


def _gerar_codigo_montagem_engrenagem_eixo_rolamento(params: Dict[str, float]) -> Tuple[str, List[Dict[str, Any]]]:
    defaults = {
        "module": 1.0,
        "teeth_number": 20.0,
        "width": 6.0,
        "bore_d": 6.0,
        "shaft_diameter": 6.0,
        "shaft_length": 25.0,
        "base_length": 60.0,
        "base_width": 40.0,
        "base_height": 5.0,
        "gear_distance": 30.0,
    }
    merged = {**defaults, **(params or {})}

    codigo = (
        "def build(params):\n"
        "    teeth_number = int(round(params['teeth_number']))\n"
        "    gear = cq_gears.SpurGear(\n"
        "        module=params['module'],\n"
        "        teeth_number=teeth_number,\n"
        "        width=params['width'],\n"
        "        bore_d=params['bore_d'],\n"
        "    )\n"
        "    gear_body = cq.Workplane('XY').gear(gear).val()\n"
        "    base = cq.Workplane('XY').rect(params['base_length'], params['base_width']).extrude(params['base_height']).val()\n"
        "    shaft = cq.Workplane('XY').circle(params['shaft_diameter'] / 2).extrude(params['shaft_length']).val()\n"
        "    bearing = cq_warehouse_bearing.SingleRowDeepGrooveBallBearing(size='M8-22-7', bearing_type='SKT')\n"
        "    assembly = cq.Assembly()\n"
        "    assembly.add(base, name='base')\n"
        "    assembly.add(gear_body, name='gear', loc=cq.Location(cq.Vector(0, 0, params['base_height'])))\n"
        "    assembly.add(shaft, name='shaft', loc=cq.Location(cq.Vector(0, 0, params['base_height'] + params['width'])))\n"
        "    assembly.add(bearing, name='bearing', loc=cq.Location(cq.Vector(0, 0, params['base_height'] + params['width'] + params['shaft_length'])))\n"
        "    return assembly\n"
    )

    params_ui = [
        {"name": "module", "default": merged["module"], "min": 0.2, "max": 10.0, "step": 0.1},
        {"name": "teeth_number", "default": merged["teeth_number"], "min": 6, "max": 200, "step": 1},
        {"name": "width", "default": merged["width"], "min": 1.0, "max": 50.0, "step": 0.5},
        {"name": "bore_d", "default": merged["bore_d"], "min": 0.0, "max": 50.0, "step": 0.5},
        {"name": "shaft_diameter", "default": merged["shaft_diameter"], "min": 2.0, "max": 50.0, "step": 0.5},
        {"name": "shaft_length", "default": merged["shaft_length"], "min": 5.0, "max": 200.0, "step": 1.0},
        {"name": "base_length", "default": merged["base_length"], "min": 20.0, "max": 200.0, "step": 1.0},
        {"name": "base_width", "default": merged["base_width"], "min": 20.0, "max": 200.0, "step": 1.0},
        {"name": "base_height", "default": merged["base_height"], "min": 2.0, "max": 50.0, "step": 1.0},
    ]
    return codigo, params_ui


def _gerar_codigo_montagem_duas_engrenagens_base(params: Dict[str, float]) -> Tuple[str, List[Dict[str, Any]]]:
    defaults = {
        "module": 1.0,
        "teeth_number": 20.0,
        "width": 6.0,
        "bore_d": 5.0,
        "gear_distance": 30.0,
        "base_length": 80.0,
        "base_width": 50.0,
        "base_height": 5.0,
    }
    merged = {**defaults, **(params or {})}

    codigo = (
        "def build(params):\n"
        "    teeth_number = int(round(params['teeth_number']))\n"
        "    gear = cq_gears.SpurGear(\n"
        "        module=params['module'],\n"
        "        teeth_number=teeth_number,\n"
        "        width=params['width'],\n"
        "        bore_d=params['bore_d'],\n"
        "    )\n"
        "    gear_body = cq.Workplane('XY').gear(gear).val()\n"
        "    base = cq.Workplane('XY').rect(params['base_length'], params['base_width']).extrude(params['base_height']).val()\n"
        "    assembly = cq.Assembly()\n"
        "    assembly.add(base, name='base')\n"
        "    assembly.add(gear_body, name='gear1', loc=cq.Location(cq.Vector(0, 0, params['base_height'])))\n"
        "    assembly.add(gear_body, name='gear2', loc=cq.Location(cq.Vector(params['gear_distance'], 0, params['base_height'])))\n"
        "    return assembly\n"
    )

    params_ui = [
        {"name": "module", "default": merged["module"], "min": 0.2, "max": 10.0, "step": 0.1},
        {"name": "teeth_number", "default": merged["teeth_number"], "min": 6, "max": 200, "step": 1},
        {"name": "width", "default": merged["width"], "min": 1.0, "max": 50.0, "step": 0.5},
        {"name": "bore_d", "default": merged["bore_d"], "min": 0.0, "max": 50.0, "step": 0.5},
        {"name": "gear_distance", "default": merged["gear_distance"], "min": 5.0, "max": 200.0, "step": 1.0},
        {"name": "base_length", "default": merged["base_length"], "min": 20.0, "max": 200.0, "step": 1.0},
        {"name": "base_width", "default": merged["base_width"], "min": 20.0, "max": 200.0, "step": 1.0},
        {"name": "base_height", "default": merged["base_height"], "min": 2.0, "max": 50.0, "step": 1.0},
    ]
    return codigo, params_ui


def _gerar_codigo_montagem_duas_engrenagens_no_eixo(params: Dict[str, float]) -> Tuple[str, List[Dict[str, Any]]]:
    defaults = {
        "module": 1.0,
        "teeth_number": 20.0,
        "width": 6.0,
        "bore_d": 6.0,
        "gear_offset": 10.0,
        "shaft_diameter": 6.0,
        "shaft_length": 50.0,
        "base_length": 80.0,
        "base_width": 40.0,
        "base_height": 5.0,
    }
    merged = {**defaults, **(params or {})}

    codigo = (
        "def build(params):\n"
        "    teeth_number = int(round(params['teeth_number']))\n"
        "    gear = cq_gears.SpurGear(\n"
        "        module=params['module'],\n"
        "        teeth_number=teeth_number,\n"
        "        width=params['width'],\n"
        "        bore_d=params['bore_d'],\n"
        "    )\n"
        "    gear_body = cq.Workplane('XY').gear(gear).val()\n"
        "    base = cq.Workplane('XY').rect(params['base_length'], params['base_width']).extrude(params['base_height']).val()\n"
        "    shaft = cq.Workplane('XY').circle(params['shaft_diameter'] / 2).extrude(params['shaft_length']).val()\n"
        "    z0 = params['base_height']\n"
        "    z1 = z0 + params['gear_offset']\n"
        "    z2 = z1 + params['width'] + params['gear_offset']\n"
        "    assembly = cq.Assembly()\n"
        "    assembly.add(base, name='base')\n"
        "    assembly.add(shaft, name='shaft', loc=cq.Location(cq.Vector(0, 0, z0)))\n"
        "    assembly.add(gear_body, name='gear1', loc=cq.Location(cq.Vector(0, 0, z1)))\n"
        "    assembly.add(gear_body, name='gear2', loc=cq.Location(cq.Vector(0, 0, z2)))\n"
        "    return assembly\n"
    )

    params_ui = [
        {"name": "module", "default": merged["module"], "min": 0.2, "max": 10.0, "step": 0.1},
        {"name": "teeth_number", "default": merged["teeth_number"], "min": 6, "max": 200, "step": 1},
        {"name": "width", "default": merged["width"], "min": 1.0, "max": 50.0, "step": 0.5},
        {"name": "bore_d", "default": merged["bore_d"], "min": 0.0, "max": 50.0, "step": 0.5},
        {"name": "gear_offset", "default": merged["gear_offset"], "min": 2.0, "max": 50.0, "step": 1.0},
        {"name": "shaft_diameter", "default": merged["shaft_diameter"], "min": 2.0, "max": 50.0, "step": 0.5},
        {"name": "shaft_length", "default": merged["shaft_length"], "min": 10.0, "max": 200.0, "step": 1.0},
        {"name": "base_length", "default": merged["base_length"], "min": 20.0, "max": 200.0, "step": 1.0},
        {"name": "base_width", "default": merged["base_width"], "min": 20.0, "max": 200.0, "step": 1.0},
        {"name": "base_height", "default": merged["base_height"], "min": 2.0, "max": 50.0, "step": 1.0},
    ]
    return codigo, params_ui


def _gerar_codigo_montagem_tres_engrenagens_cambio(params: Dict[str, float]) -> Tuple[str, List[Dict[str, Any]]]:
    defaults = {
        "module": 1.5,
        "teeth1": 20.0,
        "teeth2": 30.0,
        "teeth3": 40.0,
        "width": 6.0,
        "bore_d": 6.0,
        "gear_distance": 25.0,
        "shaft_diameter": 6.0,
        "shaft_length": 60.0,
        "base_length": 120.0,
        "base_width": 60.0,
        "base_height": 6.0,
    }
    merged = {**defaults, **(params or {})}

    codigo = (
        "def build(params):\n"
        "    t1 = int(round(params['teeth1']))\n"
        "    t2 = int(round(params['teeth2']))\n"
        "    t3 = int(round(params['teeth3']))\n"
        "    g1 = cq_gears.SpurGear(module=params['module'], teeth_number=t1, width=params['width'], bore_d=params['bore_d'])\n"
        "    g2 = cq_gears.SpurGear(module=params['module'], teeth_number=t2, width=params['width'], bore_d=params['bore_d'])\n"
        "    g3 = cq_gears.SpurGear(module=params['module'], teeth_number=t3, width=params['width'], bore_d=params['bore_d'])\n"
        "    gear1 = cq.Workplane('XY').gear(g1).val()\n"
        "    gear2 = cq.Workplane('XY').gear(g2).val()\n"
        "    gear3 = cq.Workplane('XY').gear(g3).val()\n"
        "    base = cq.Workplane('XY').rect(params['base_length'], params['base_width']).extrude(params['base_height']).val()\n"
        "    shaft = cq.Workplane('XY').circle(params['shaft_diameter']/2).extrude(params['shaft_length']).val()\n"
        "    bearing = cq_warehouse_bearing.SingleRowDeepGrooveBallBearing(size='M8-22-7', bearing_type='SKT')\n"
        "    d = params['gear_distance']\n"
        "    assembly = cq.Assembly()\n"
        "    assembly.add(base, name='base')\n"
        "    assembly.add(gear1, name='gear1', loc=cq.Location(cq.Vector(-d, 0, params['base_height'])))\n"
        "    assembly.add(gear2, name='gear2', loc=cq.Location(cq.Vector(0, 0, params['base_height'])))\n"
        "    assembly.add(gear3, name='gear3', loc=cq.Location(cq.Vector(d, 0, params['base_height'])))\n"
        "    assembly.add(shaft, name='shaft', loc=cq.Location(cq.Vector(0, 0, params['base_height'] + params['width'])))\n"
        "    assembly.add(bearing, name='bearing', loc=cq.Location(cq.Vector(0, 0, params['base_height'] + params['width'] + params['shaft_length'])))\n"
        "    return assembly\n"
    )

    params_ui = [
        {"name": "module", "default": merged["module"], "min": 0.2, "max": 10.0, "step": 0.1},
        {"name": "teeth1", "default": merged["teeth1"], "min": 6, "max": 200, "step": 1},
        {"name": "teeth2", "default": merged["teeth2"], "min": 6, "max": 200, "step": 1},
        {"name": "teeth3", "default": merged["teeth3"], "min": 6, "max": 200, "step": 1},
        {"name": "width", "default": merged["width"], "min": 1.0, "max": 50.0, "step": 0.5},
        {"name": "bore_d", "default": merged["bore_d"], "min": 0.0, "max": 50.0, "step": 0.5},
        {"name": "gear_distance", "default": merged["gear_distance"], "min": 5.0, "max": 200.0, "step": 1.0},
        {"name": "shaft_diameter", "default": merged["shaft_diameter"], "min": 2.0, "max": 50.0, "step": 0.5},
        {"name": "shaft_length", "default": merged["shaft_length"], "min": 5.0, "max": 200.0, "step": 1.0},
        {"name": "base_length", "default": merged["base_length"], "min": 40.0, "max": 300.0, "step": 1.0},
        {"name": "base_width", "default": merged["base_width"], "min": 40.0, "max": 200.0, "step": 1.0},
        {"name": "base_height", "default": merged["base_height"], "min": 2.0, "max": 50.0, "step": 1.0},
    ]
    return codigo, params_ui
def _gerar_codigo_engrenagem_cq_gears(params: Dict[str, float]) -> Tuple[str, List[Dict[str, Any]]]:
    defaults = {
        "module": 1.0,
        "teeth_number": 20.0,
        "width": 5.0,
        "bore_d": 5.0,
    }
    merged = {**defaults, **(params or {})}

    codigo = (
        "def build(params):\n"
        "    teeth_number = int(round(params['teeth_number']))\n"
        "    gear = cq_gears.SpurGear(\n"
        "        module=params['module'],\n"
        "        teeth_number=teeth_number,\n"
        "        width=params['width'],\n"
        "        bore_d=params['bore_d'],\n"
        "    )\n"
        "    return cq.Workplane('XY').gear(gear)\n"
    )

    params_ui = [
        {"name": "module", "default": merged["module"], "min": 0.2, "max": 10.0, "step": 0.1},
        {"name": "teeth_number", "default": merged["teeth_number"], "min": 6, "max": 200, "step": 1},
        {"name": "width", "default": merged["width"], "min": 1.0, "max": 50.0, "step": 0.5},
        {"name": "bore_d", "default": merged["bore_d"], "min": 0.0, "max": 50.0, "step": 0.5},
    ]
    return codigo, params_ui

def _extrair_codigo_de_json(texto: str) -> str:
    texto = (texto or "").strip()
    if not texto:
        return ""
    # Tenta JSON valido primeiro.
    if texto.startswith("{") and '"code"' in texto:
        dados = _parse_json_resposta(texto)
        codigo = _extrair_codigo(str(dados.get("code", "")))
        if codigo:
            return codigo
    # Fallback para JSON "quebrado" com quebras de linha dentro de strings.
    match = re.search(r'"code"\s*:\s*"(.*?)"\s*,\s*"params"', texto, re.DOTALL)
    if match:
        codigo = match.group(1)
        # Desfaz escapes comuns e remove quebra de linha inicial.
        codigo = codigo.replace("\\n", "\n").replace("\\t", "\t").lstrip("\n")
        return codigo
    return ""


def _extrair_params_de_json(texto: str) -> List[Dict[str, Any]]:
    texto = (texto or "").strip()
    if not texto:
        return []
    # Primeiro tenta JSON valido.
    if texto.startswith("{") and '"params"' in texto:
        dados = _parse_json_resposta(texto)
        params = _validar_params(dados.get("params", []))
        if params:
            return params
    # Fallback: captura o array de params mesmo em JSON quebrado.
    match = re.search(r'"params"\s*:\s*(\[[\s\S]*?\])\s*}', texto, re.DOTALL)
    if not match:
        return []
    bloco = match.group(1)
    try:
        params_raw = json.loads(bloco)
        return _validar_params(params_raw)
    except Exception:
        return []


def _extrair_codigo(texto: str) -> str:
    texto = (texto or "").strip()
    if not texto:
        return ""
    match = re.search(r"```(?:python|json)?\s*([\s\S]*?)```", texto, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return texto


def _codigo_parece_json(codigo: str) -> bool:
    codigo = (codigo or "").lstrip()
    if not codigo:
        return False
    if codigo.startswith("{") and '"code"' in codigo:
        return True
    trecho = codigo[:200]
    return bool(re.search(r'"code"\s*:', trecho))


def _salvar_debug_resposta(pasta_saida: str, resposta: str, codigo: str, erro: str) -> str:
    nome_base = datetime.datetime.now().strftime("cadquery_debug_%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta_saida, f"{nome_base}.txt")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("ERRO:\n")
        f.write(erro.strip() + "\n\n")
        f.write("RESPOSTA_LLM:\n")
        f.write((resposta or "").rstrip() + "\n\n")
        f.write("CODIGO_EXTRAIDO:\n")
        f.write((codigo or "").rstrip() + "\n")
    return caminho


def _parse_json_resposta(texto: str) -> Dict[str, Any]:
    try:
        return json.loads(texto)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", texto)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _gerar_nome_base() -> str:
    agora = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"cadquery_{agora}"


def _criar_pasta_saida(base_dir: str) -> str:
    pasta = os.path.join(_project_root(), "data", "models", "cad_generated")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _tentar_biblioteca(
    comando: str, base_dir: str
) -> Optional[Tuple[str, List[Dict[str, Any]], Dict[str, Any]]]:
    comando_norm = (comando or "").lower()

    if re.search(r"\b(montagem|conjunto|assembl(e|y)|mais de uma peca|multiplas pecas|duas pecas|duas engrenagens|engrenagens)\b", comando_norm):
        params_gear = _parse_params_engrenagem(comando)
        params_eixo = _parse_params_eixo(comando)
        params = {**params_gear, **params_eixo}

        if re.search(r"\bduas engrenagens\b", comando_norm) and re.search(r"\beixo\b", comando_norm):
            _ensure_sys_path([r"G:\bibliotecas\cq_gears-main\cq_gears-main"])
            cq_gears = _import_module_safe("cq_gears")
            if cq_gears is not None:
                codigo, params_ui = _gerar_codigo_montagem_duas_engrenagens_no_eixo(params)
                extra_globals = {"cq_gears": cq_gears}
                return codigo, params_ui, extra_globals

        if re.search(r"\b(3|tres)\s+engrenagens\b", comando_norm) or "cambio" in comando_norm:
            _ensure_sys_path([
                r"G:\bibliotecas\cq_gears-main\cq_gears-main",
                r"G:\bibliotecas\cq_warehouse-main\cq_warehouse-main\src",
            ])
            cq_gears = _import_module_safe("cq_gears")
            cq_warehouse_bearing = _import_module_safe("cq_warehouse.bearing")
            if cq_gears is not None and cq_warehouse_bearing is not None:
                codigo, params_ui = _gerar_codigo_montagem_tres_engrenagens_cambio(params)
                extra_globals = {
                    "cq_gears": cq_gears,
                    "cq_warehouse_bearing": cq_warehouse_bearing,
                }
                return codigo, params_ui, extra_globals

        if "rolamento 608" in comando_norm or "rolamento608" in comando_norm:
            _ensure_sys_path([
                r"G:\bibliotecas\cq_gears-main\cq_gears-main",
                r"G:\bibliotecas\cq_warehouse-main\cq_warehouse-main\src",
            ])
            cq_gears = _import_module_safe("cq_gears")
            cq_warehouse_bearing = _import_module_safe("cq_warehouse.bearing")
            if cq_gears is not None and cq_warehouse_bearing is not None:
                codigo, params_ui = _gerar_codigo_montagem_engrenagem_eixo_rolamento(params)
                extra_globals = {
                    "cq_gears": cq_gears,
                    "cq_warehouse_bearing": cq_warehouse_bearing,
                }
                return codigo, params_ui, extra_globals

        if re.search(r"\bduas engrenagens\b", comando_norm) and "base" in comando_norm:
            _ensure_sys_path([r"G:\bibliotecas\cq_gears-main\cq_gears-main"])
            cq_gears = _import_module_safe("cq_gears")
            if cq_gears is not None:
                codigo, params_ui = _gerar_codigo_montagem_duas_engrenagens_base(params)
                extra_globals = {"cq_gears": cq_gears}
                return codigo, params_ui, extra_globals

        return None

    if "engrenagem" in comando_norm or "gear" in comando_norm:
        caminhos = [
            r"G:\bibliotecas\cq_gears-main\cq_gears-main",
        ]
        _ensure_sys_path(caminhos)
        cq_gears = _import_module_safe("cq_gears")
        if cq_gears is None:
            return None

        params_extraidos = _parse_params_engrenagem(comando)
        codigo, params = _gerar_codigo_engrenagem_cq_gears(params_extraidos)
        extra_globals = {"cq_gears": cq_gears}
        return codigo, params, extra_globals

    return None


def _detectar_bibliotecas_no_codigo(codigo: str) -> Dict[str, Any]:
    extra: Dict[str, Any] = {}
    codigo_lower = (codigo or "").lower()

    if "cq_gears" in codigo_lower:
        _ensure_sys_path([r"G:\bibliotecas\cq_gears-main\cq_gears-main"])
        mod = _import_module_safe("cq_gears")
        if mod is not None:
            extra["cq_gears"] = mod

    if "cq_warehouse" in codigo_lower:
        _ensure_sys_path([r"G:\bibliotecas\cq_warehouse-main\cq_warehouse-main\src"])
        mod = _import_module_safe("cq_warehouse")
        if mod is not None:
            extra["cq_warehouse"] = mod
            for match in re.findall(r"\bcq_warehouse\.([a-z0-9_]+)\b", codigo_lower):
                sub = match.strip()
                if not sub:
                    continue
                try:
                    import importlib
                    submod = importlib.import_module(f"cq_warehouse.{sub}")
                    setattr(mod, sub, submod)
                except Exception:
                    pass

    if "cqparts" in codigo_lower:
        _ensure_sys_path([r"G:\bibliotecas\cqparts-master\cqparts-master\src"])
        mod = _import_module_safe("cqparts")
        if mod is not None:
            extra["cqparts"] = mod
        # Importa bibliotecas de conteudo se citadas no codigo.
        for match in re.findall(r"\b(cqparts_[a-z0-9_]+)\b", codigo_lower):
            mod_name = match.strip()
            if mod_name and mod_name not in extra:
                mod_lib = _import_module_safe(mod_name)
                if mod_lib is not None:
                    extra[mod_name] = mod_lib

    return extra


def _montar_contexto_catalogo(comando: str, base_dir: str, limite: int = 12) -> str:
    try:
        catalog_path = os.path.join(_project_root(), "data", "json", "cad_library_catalog.json")
        catalog = cad_library_catalog.ensure_catalog(catalog_path)
        matches = cad_library_catalog.search_catalog(catalog, comando, limit=limite)
        if not matches:
            return ""
        linhas = ["Catalogo de pecas disponiveis (use se fizer sentido):"]
        for e in matches:
            params = ", ".join(e.get("params") or [])
            doc = e.get("doc") or ""
            linha = f"- {e.get('source')}: {e.get('module')}.{e.get('class')}"
            if params:
                linha += f" | params: {params}"
            if doc:
                linha += f" | {doc}"
            linhas.append(linha)
        return "\n".join(linhas)
    except Exception:
        return ""


def _catalogo_permitido(base_dir: str) -> Dict[str, set]:
    try:
        catalog_path = os.path.join(_project_root(), "data", "json", "cad_library_catalog.json")
        catalog = cad_library_catalog.ensure_catalog(catalog_path)
        entries = catalog.get("entries", [])
        allowed = set()
        for e in entries:
            mod = e.get("module")
            cls = e.get("class")
            if mod and cls:
                allowed.add(f"{mod}.{cls}")
        return {"allowed": allowed}
    except Exception:
        return {"allowed": set()}


def _validar_referencias_catalogo(codigo: str, base_dir: str) -> List[str]:
    allowed = _catalogo_permitido(base_dir)["allowed"]
    if not allowed:
        return []

    refs: set = set()
    refs.update(re.findall(r"\b(cq_gears\.[A-Za-z0-9_]+)\b", codigo))
    refs.update(re.findall(r"\b(cq_warehouse\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+)\b", codigo))
    refs.update(re.findall(r"\b(cqparts_[A-Za-z0-9_]+\.[A-Za-z0-9_]+)\b", codigo))
    refs.update(re.findall(r"\b(cqparts_[A-Za-z0-9_]+)\b", codigo))

    invalid = []
    for ref in refs:
        if ref not in allowed:
            invalid.append(ref)
    return invalid


def _executar_cadquery(codigo: str, pasta_saida: str, extra_globals: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    try:
        import cadquery as cq
    except Exception as exc:
        raise RuntimeError(f"cadquery nao esta disponivel: {exc}")

    _patch_workplane_helix(cq)
    _patch_workplane_push(cq)

    proibidos = ["import ", "__", "open(", "exec(", "eval(", "os.", "sys."]
    codigo_lower = codigo.lower()
    if any(p in codigo_lower for p in proibidos):
        raise RuntimeError("Codigo CADQuery contem termos proibidos para execucao.")

    safe_builtins = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "round": round,
        "range": range,
        "len": len,
        "float": float,
        "int": int,
        "print": print,
    }

    codigo = _sanitizar_codigo(codigo)
    _validar_sintaxe(codigo)
    globais = {"__builtins__": safe_builtins, "cq": cq, "math": math}
    if extra_globals:
        globais.update(extra_globals)
    locais: Dict[str, Any] = {}
    exec(codigo, globais, locais)

    result = locais.get("result")
    if result is None:
        build_fn = locais.get("build")
        if callable(build_fn):
            try:
                result = build_fn({})
            except Exception as exc:
                raise RuntimeError(f"Falha ao executar build(params): {exc}")
        if result is None:
            raise RuntimeError("Codigo CADQuery precisa definir a variavel 'result'.")

    nome_base = _gerar_nome_base()
    caminho_py = os.path.join(pasta_saida, f"{nome_base}.py")
    caminho_stl = os.path.join(pasta_saida, f"{nome_base}.stl")

    with open(caminho_py, "w", encoding="utf-8") as f:
        f.write(codigo.strip() + "\n")

    try:
        from cadquery import exporters
        result_export = _normalizar_resultado_export(result)
        exporters.export(result_export, caminho_stl)
    except Exception as exc:
        raise RuntimeError(f"Falha ao exportar STL: {exc}")

    return caminho_py, caminho_stl


def _abrir_viewer_pyvista(caminho_stl: str) -> Optional[str]:
    try:
        import pyvista as pv
    except Exception as exc:
        return f"pyvista nao esta disponivel: {exc}"

    def _run_viewer() -> None:
        try:
            mesh = pv.read(caminho_stl)
            plotter = pv.Plotter(title="Altair CAD Viewer")
            plotter.add_mesh(mesh, color="#c7d1ff", show_edges=True)
            plotter.add_axes()
            plotter.show()
        except Exception:
            pass

    threading.Thread(target=_run_viewer, daemon=True).start()
    return None


def _validar_params(params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    validos: List[Dict[str, Any]] = []
    for p in params or []:
        nome = str(p.get("name", "")).strip()
        if not nome:
            continue
        minimo = _safe_float(p.get("min", 1.0), 1.0)
        maximo = _safe_float(p.get("max", 100.0), 100.0)
        if maximo <= minimo:
            maximo = minimo + 1.0
        step = _safe_float(p.get("step", 1.0), 1.0)
        default = _safe_float(p.get("default", minimo), minimo)
        validos.append(
            {
                "name": nome,
                "min": minimo,
                "max": maximo,
                "step": step,
                "default": default,
            }
        )
    return validos


def _executar_cadquery_parametrico(
    codigo: str,
    pasta_saida: str,
    params_default: Dict[str, float],
    extra_globals: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, Any]:
    try:
        import cadquery as cq
    except Exception as exc:
        raise RuntimeError(f"cadquery nao esta disponivel: {exc}")

    _patch_workplane_helix(cq)
    _patch_workplane_push(cq)

    proibidos = ["import ", "__", "open(", "exec(", "eval(", "os.", "sys."]
    codigo_lower = codigo.lower()
    if any(p in codigo_lower for p in proibidos):
        raise RuntimeError("Codigo CADQuery contem termos proibidos para execucao.")

    safe_builtins = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "round": round,
        "range": range,
        "len": len,
        "float": float,
        "int": int,
        "print": print,
    }

    codigo = _sanitizar_codigo(codigo)
    _validar_sintaxe(codigo)
    globais = {"__builtins__": safe_builtins, "cq": cq, "math": math}
    if extra_globals:
        globais.update(extra_globals)
    locais: Dict[str, Any] = {}
    exec(codigo, globais, locais)

    build_fn = locais.get("build")
    if not callable(build_fn):
        result = locais.get("result")
        if result is None:
            raise RuntimeError("Codigo CADQuery precisa definir a funcao build(params).")
        # Fallback: codigo com result pronto (sem funcao build).
        def _static_build(_params: Dict[str, float]) -> Any:
            return result
        build_fn = _static_build

    nome_base = _gerar_nome_base()
    caminho_py = os.path.join(pasta_saida, f"{nome_base}.py")
    caminho_stl = os.path.join(pasta_saida, f"{nome_base}.stl")

    with open(caminho_py, "w", encoding="utf-8") as f:
        f.write(codigo.strip() + "\n")

    needs_nested = _codigo_requer_params_nome(codigo)
    inferred = _inferir_defaults_parametros(codigo)
    # Mescla defaults inferidos com os recebidos (recebidos têm prioridade).
    merged = {**inferred, **(params_default or {})}
    params_exec: Dict[str, Any] = _coagir_params_inteiros(merged)
    if needs_nested:
        params_exec = {"nome": dict(params_exec)}
    def _try_build(params_to_use: Dict[str, Any]) -> Any:
        try:
            return build_fn(params_to_use)
        except TypeError:
            # Fallback: build() sem parametros.
            try:
                return build_fn()
            except Exception:
                raise
        except KeyError as exc:
            missing = exc.args[0] if exc.args else None
            if missing:
                if missing not in params_to_use:
                    params_to_use[missing] = inferred.get(missing, 10.0)
                return build_fn(params_to_use)
            raise

    try:
        result = _try_build(dict(params_exec))
        from cadquery import exporters

        result_export = _normalizar_resultado_export(result)
        exporters.export(result_export, caminho_stl)
    except KeyError as exc:
        if needs_nested:
            try:
                result = _try_build(dict(merged))
                from cadquery import exporters

                result_export = _normalizar_resultado_export(result)
                exporters.export(result_export, caminho_stl)
            except Exception as exc_inner:
                raise RuntimeError(f"Falha ao exportar STL: {exc_inner}") from exc_inner
        else:
            raise RuntimeError(f"Falha ao exportar STL: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Falha ao exportar STL: {exc}")

    if needs_nested:
        def _wrapper(params: Dict[str, float]) -> Any:
            merged_runtime = {**inferred, **(params or {})}
            merged_runtime = _coagir_params_inteiros(merged_runtime)
            try:
                return build_fn({"nome": merged_runtime})
            except KeyError as exc:
                missing = exc.args[0] if exc.args else None
                if missing:
                    merged_runtime.setdefault(missing, inferred.get(missing, 10.0))
                return build_fn(merged_runtime)
        return caminho_py, caminho_stl, _wrapper
    return caminho_py, caminho_stl, build_fn


def gerar_projeto_cad(comando: str, ia_llm: Any, base_dir: str) -> Dict[str, str]:
    comando = (comando or "").strip()
    if not comando:
        return {"visual": "Comando vazio para gerar CAD.", "fala": ""}

    biblioteca = _tentar_biblioteca(comando, base_dir)
    if biblioteca is not None:
        codigo, params, extra_globals = biblioteca
        pasta_saida = _criar_pasta_saida(base_dir)
        params_default = {p["name"]: _safe_float(p.get("default", 0.0), 0.0) for p in params}
        try:
            caminho_py, caminho_stl, build_fn = _executar_cadquery_parametrico(
                codigo, pasta_saida, params_default, extra_globals=extra_globals
            )
        except Exception as exc:
            return {"visual": f"Erro ao executar CADQuery: {exc}", "fala": ""}

        erro_viewer = abrir_viewer_parametrico(
            build_fn=build_fn,
            params=params,
            output_dir=pasta_saida,
        )

        linhas = [
            "Projeto CAD 3D parametrico gerado com biblioteca.",
            f"Codigo salvo em: {caminho_py}",
            f"Modelo STL salvo em: {caminho_stl}",
        ]
        if erro_viewer:
            linhas.append(f"Aviso viewer 3D: {erro_viewer}")
        else:
            linhas.append("Viewer 3D aberto com sliders.")

        return {"visual": "\n".join(linhas), "fala": ""}

    if ia_llm is None:
        return {"visual": "LLM nao configurado. Configure a API para gerar o CAD.", "fala": ""}

    catalogo_contexto = _montar_contexto_catalogo(comando, base_dir)
    prompt = (
        "Voce e especialista em CADQuery. Converta o pedido em codigo Python CADQuery.\n"
        "Responda APENAS JSON valido com as chaves: code (string) e params (lista).\n"
        "Regras do codigo:\n"
        "- Nao use imports.\n"
        "- Use apenas 'cq' (cadquery) e 'math'.\n"
        "- Pode usar bibliotecas ja carregadas: cq_gears, cq_warehouse, cqparts e cqparts_*.\n"
        "- PRIORIDADE: se houver pecas no catalogo, use apenas classes listadas.\n"
        "- Se nao houver classe adequada no catalogo, use CADQuery puro.\n"
        "- Se o pedido for montagem/conjunto, crie multiplas pecas e posicione com translate/rotate.\n"
        "- O build(params) pode retornar cq.Workplane OU cq.Assembly.\n"
        "- Para engrenagens use cq_gears.SpurGear + cq.Workplane('XY').gear(gear).\n"
        "- Evite cq_gears.spur_gear.GearBase.\n"
        "- Use params['nome'] para dimensoes.\n"
        "Regras dos params:\n"
        "- Cada item: {name, default, min, max, step}.\n"
        "- Use mm como unidade.\n"
        "- Se faltar medida, escolha valores razoaveis.\n"
        f"{catalogo_contexto}\n"
        f"Pedido: {comando}"
    )

    try:
        resposta = ia_llm.gerar_resposta(prompt, forcar_modelo_grande=True)
    except Exception as exc:
        return {"visual": f"Falha ao gerar codigo CADQuery: {exc}", "fala": ""}

    dados = _parse_json_resposta(resposta)
    codigo = _extrair_codigo(str(dados.get("code", "")))
    params = _validar_params(dados.get("params", []))
    if not codigo:
        codigo = _extrair_codigo_de_json(resposta)
    if not params:
        params = _extrair_params_de_json(resposta)
    if _codigo_parece_json(codigo):
        codigo = _extrair_codigo_de_json(codigo)

    invalid_refs = _validar_referencias_catalogo(codigo, base_dir)
    if invalid_refs:
        retry_prompt = (
            "Seu codigo usou classes que NAO estao no catalogo local: "
            + ", ".join(invalid_refs)
            + ". Corrija e gere novo codigo usando apenas classes do catalogo "
            "ou CADQuery puro. Retorne SOMENTE JSON valido com code e params.\n"
            f"{catalogo_contexto}\n"
            f"Pedido: {comando}"
        )
        try:
            resposta_retry = ia_llm.gerar_resposta(retry_prompt, forcar_modelo_grande=True)
            dados_retry = _parse_json_resposta(resposta_retry)
            codigo = _extrair_codigo(str(dados_retry.get("code", "")))
            params = _validar_params(dados_retry.get("params", []))
            if not codigo:
                codigo = _extrair_codigo_de_json(resposta_retry)
            if _codigo_parece_json(codigo):
                codigo = _extrair_codigo_de_json(codigo)
        except Exception:
            pass

    if not codigo:
        # Fallback: tenta extrair codigo diretamente da resposta textual.
        codigo = _extrair_codigo(resposta)
        if not codigo:
            codigo = _extrair_codigo_de_json(resposta)
        if _codigo_parece_json(codigo):
            codigo = _extrair_codigo_de_json(codigo)
        if not params:
            params = _extrair_params_de_json(resposta)
        if not codigo or "def build" not in codigo:
            # Retry pedindo JSON estrito.
            retry_prompt = (
                "Corrija e retorne SOMENTE JSON valido com chaves code e params. "
                "Nao explique. " 
                f"Pedido: {comando}"
            )
            try:
                resposta_retry = ia_llm.gerar_resposta(retry_prompt, forcar_modelo_grande=True)
                dados_retry = _parse_json_resposta(resposta_retry)
                codigo = _extrair_codigo(str(dados_retry.get("code", "")))
                params = _validar_params(dados_retry.get("params", []))
                if not codigo:
                    codigo = _extrair_codigo_de_json(resposta_retry)
                if _codigo_parece_json(codigo):
                    codigo = _extrair_codigo_de_json(codigo)
                if not params:
                    params = _extrair_params_de_json(resposta_retry)
            except Exception:
                codigo = ""

    if not codigo:
        return {"visual": "Nao consegui gerar o codigo CADQuery. Tente reformular o pedido.", "fala": ""}

    pasta_saida = _criar_pasta_saida(base_dir)

    if params:
        params_default = {p["name"]: _safe_float(p.get("default", 0.0), 0.0) for p in params}
        try:
            extra_globals = _detectar_bibliotecas_no_codigo(codigo)
            caminho_py, caminho_stl, build_fn = _executar_cadquery_parametrico(
                codigo, pasta_saida, params_default, extra_globals=extra_globals
            )
        except Exception as exc:
            if "Erro de sintaxe no codigo CADQuery" in str(exc):
                caminho_debug = _salvar_debug_resposta(pasta_saida, resposta, codigo, str(exc))
                return {
                    "visual": f"Erro ao executar CADQuery: {exc}\nDebug salvo em: {caminho_debug}",
                    "fala": "",
                }
            return {"visual": f"Erro ao executar CADQuery: {exc}", "fala": ""}

        erro_viewer = abrir_viewer_parametrico(
            build_fn=build_fn,
            params=params,
            output_dir=pasta_saida,
        )

        linhas = [
            "Projeto CAD 3D parametrico gerado com sucesso.",
            f"Codigo salvo em: {caminho_py}",
            f"Modelo STL salvo em: {caminho_stl}",
        ]
        if erro_viewer:
            linhas.append(f"Aviso viewer 3D: {erro_viewer}")
        else:
            linhas.append("Viewer 3D aberto com sliders.")

        return {"visual": "\n".join(linhas), "fala": ""}

    try:
        extra_globals = _detectar_bibliotecas_no_codigo(codigo)
        caminho_py, caminho_stl = _executar_cadquery(codigo, pasta_saida, extra_globals=extra_globals)
    except Exception as exc:
        if "Erro de sintaxe no codigo CADQuery" in str(exc):
            caminho_debug = _salvar_debug_resposta(pasta_saida, resposta, codigo, str(exc))
            return {
                "visual": f"Erro ao executar CADQuery: {exc}\nDebug salvo em: {caminho_debug}",
                "fala": "",
            }
        return {"visual": f"Erro ao executar CADQuery: {exc}", "fala": ""}

    erro_viewer = _abrir_viewer_pyvista(caminho_stl)

    linhas = [
        "Projeto CAD 3D gerado com sucesso.",
        f"Codigo salvo em: {caminho_py}",
        f"Modelo STL salvo em: {caminho_stl}",
    ]
    if erro_viewer:
        linhas.append(f"Aviso viewer 3D: {erro_viewer}")
    else:
        linhas.append("Viewer 3D aberto com PyVista.")

    return {"visual": "\n".join(linhas), "fala": ""}
