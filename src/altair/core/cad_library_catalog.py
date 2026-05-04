import ast
import json
import os
import re
from typing import Any, Dict, List, Optional


LIB_CQ_GEARS = r"G:\bibliotecas\cq_gears-main\cq_gears-main\cq_gears"
LIB_CQ_WAREHOUSE = r"G:\bibliotecas\cq_warehouse-main\cq_warehouse-main\src\cq_warehouse"
LIB_CQPARTS_SRC = r"G:\bibliotecas\cqparts-master\cqparts-master\src"


def _ler_arquivo(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _iter_py_files(root: str) -> List[str]:
    arquivos: List[str] = []
    if not root or not os.path.isdir(root):
        return arquivos
    for base, _dirs, files in os.walk(root):
        for nome in files:
            if nome.endswith(".py") and not nome.startswith("."):
                arquivos.append(os.path.join(base, nome))
    return arquivos


def _module_from_path(path: str, root: str, prefix: str) -> str:
    rel = os.path.relpath(path, root).replace(os.sep, ".")
    if rel.endswith(".py"):
        rel = rel[:-3]
    if rel.endswith(".__init__"):
        rel = rel[: -len(".__init__")]
    if rel in ("", "."):
        return prefix
    return f"{prefix}.{rel}"


def _extract_classes_from_file(path: str, root: str, prefix: str) -> List[Dict[str, Any]]:
    source = _ler_arquivo(path)
    if not source:
        return []
    try:
        tree = ast.parse(source)
    except Exception:
        return []

    module_name = _module_from_path(path, root, prefix)
    entries: List[Dict[str, Any]] = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        class_name = node.name
        if class_name.startswith("_"):
            continue

        methods = {
            n.name
            for n in node.body
            if isinstance(n, ast.FunctionDef)
        }
        if not (methods & {"make", "build", "__init__"}):
            continue

        init_params: List[str] = []
        for n in node.body:
            if isinstance(n, ast.FunctionDef) and n.name == "__init__":
                for arg in n.args.args[1:]:
                    init_params.append(arg.arg)
                for arg in n.args.kwonlyargs:
                    init_params.append(arg.arg)

        doc = ast.get_docstring(node) or ""
        doc = doc.strip().splitlines()[0] if doc else ""

        entries.append(
            {
                "class": class_name,
                "module": module_name,
                "params": init_params,
                "doc": doc,
            }
        )

    return entries


def _scan_cq_gears() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for path in _iter_py_files(LIB_CQ_GEARS):
        entries.extend(_extract_classes_from_file(path, LIB_CQ_GEARS, "cq_gears"))
    for e in entries:
        e["source"] = "cq_gears"
    return entries


def _scan_cq_warehouse() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for path in _iter_py_files(LIB_CQ_WAREHOUSE):
        entries.extend(_extract_classes_from_file(path, LIB_CQ_WAREHOUSE, "cq_warehouse"))
    for e in entries:
        e["source"] = "cq_warehouse"
    return entries


def _scan_cqparts() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not os.path.isdir(LIB_CQPARTS_SRC):
        return entries

    for nome in os.listdir(LIB_CQPARTS_SRC):
        if not nome.startswith("cqparts"):
            continue
        pkg_dir = os.path.join(LIB_CQPARTS_SRC, nome)
        if not os.path.isdir(pkg_dir):
            continue
        for path in _iter_py_files(pkg_dir):
            entries.extend(_extract_classes_from_file(path, pkg_dir, nome))

    for e in entries:
        e["source"] = "cqparts"
    return entries


CATALOGO_BASE_MANUAL: List[Dict[str, Any]] = [
    {"class": "Cube", "module": "basic_primitives", "params": ["length"], "doc": "Cubo parametrico", "source": "base"},
    {"class": "Cylinder", "module": "basic_primitives", "params": ["radius", "height"], "doc": "Cilindro", "source": "base"},
    {"class": "Box", "module": "basic_primitives", "params": ["length", "width", "height"], "doc": "Caixa retangular", "source": "base"},
    {"class": "Sphere", "module": "basic_primitives", "params": ["radius"], "doc": "Esfera", "source": "base"},
    {"class": "Plate", "module": "basic", "params": ["length", "width", "thickness"], "doc": "Placa fina", "source": "base"},
    {"class": "Rod", "module": "basic", "params": ["diameter", "length"], "doc": "Barra redonda", "source": "base"},
    {"class": "SpurGear", "module": "cq_gears.spur_gear", "params": ["module", "teeth_number", "width"], "doc": "Engrenagem reta", "source": "gears"},
    {"class": "RackGear", "module": "cq_gears.rack_gear", "params": ["module", "length", "width"], "doc": "Cremaillere", "source": "gears"},
    {"class": "Bearing", "module": "cq_warehouse.bearing", "params": ["size"], "doc": "Rolamento", "source": "warehouse"},
    {"class": "Nut", "module": "cq_warehouse.fastener", "params": ["size"], "doc": "Porca", "source": "warehouse"},
]


_ALIASES_POR_CLASSE = {
    "cube": {"cubo", "box", "caixa", "cubo parametrico"},
    "box": {"caixa", "cubo", "box"},
    "cylinder": {"cilindro", "cylinder"},
    "sphere": {"esfera", "sphere"},
    "plate": {"placa", "plate"},
    "rod": {"barra", "eixo", "shaft", "rod"},
    "shaft": {"barra", "eixo", "shaft", "axle"},
    "spurgear": {"engrenagem", "engrenagem reta", "spur gear", "gear"},
    "rackgear": {"cremalheira", "rack gear", "rack"},
    "bearing": {"rolamento", "bearing"},
    "nut": {"porca", "nut"},
    "screw": {"parafuso", "parafusos", "screw", "bolt"},
    "bevelgear": {"engrenagem conica", "engrenagem cônica", "bevel gear"},
    "crossedhelicalgear": {"engrenagem helicoidal cruzada", "crossed helical gear"},
    "hyperbolicgear": {"engrenagem hiperbolica", "engrenagem hiperbólica", "hyperbolic gear"},
    "ringgear": {"engrenagem anelar", "ring gear"},
}


def _sem_acentos(texto: Optional[str]) -> str:
    import unicodedata

    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ASCII", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", texto).strip().lower()


def _tokenizar_camel_case(texto: str) -> List[str]:
    if not texto:
        return []
    texto = re.sub(r"([a-z])([A-Z])", r"\1 \2", texto)
    texto = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", texto)
    return [t.lower() for t in re.split(r"[^a-zA-Z0-9]+", texto) if t]


def _aliases_da_entrada(entry: Dict[str, Any]) -> List[str]:
    classe = str(entry.get("class", "")).strip()
    modulo = str(entry.get("module", "")).strip()
    doc = str(entry.get("doc", "")).strip()
    params = entry.get("params", [])

    aliases = {
        _sem_acentos(classe),
        _sem_acentos(modulo.split(".")[-1] if modulo else ""),
        _sem_acentos(doc),
        _sem_acentos(" ".join(_tokenizar_camel_case(classe))),
    }

    chave = _sem_acentos(classe).replace(" ", "")
    aliases.update(_ALIASES_POR_CLASSE.get(chave, set()))

    for parametro in params:
        aliases.add(_sem_acentos(str(parametro)))

    return sorted(alias for alias in aliases if alias)


def normalize_catalog(catalog: Dict[str, Any]) -> Dict[str, Any]:
    entries = catalog.get("entries", [])
    normalized_entries: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        novo = dict(entry)
        novo["aliases"] = _aliases_da_entrada(novo)
        normalized_entries.append(novo)

    normalized = dict(catalog)
    normalized["entries"] = normalized_entries
    return normalized


def build_catalog() -> Dict[str, Any]:
    entries = list(CATALOGO_BASE_MANUAL)
    entries.extend(_scan_cq_gears())
    entries.extend(_scan_cq_warehouse())
    entries.extend(_scan_cqparts())
    catalog: Dict[str, Any] = {
        "generated_at": datetime_now_iso(),
        "entries": entries,
    }
    return normalize_catalog(catalog)


def save_catalog(path: str, catalog: Dict[str, Any]) -> None:
    pasta = os.path.dirname(path)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)


def load_catalog(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"generated_at": "", "entries": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "entries" in data:
            return data
    except Exception:
        pass
    return {"generated_at": "", "entries": []}


def ensure_catalog(path: str) -> Dict[str, Any]:
    data = load_catalog(path)
    if data.get("entries"):
        return normalize_catalog(data)
    catalog = build_catalog()
    save_catalog(path, catalog)
    return catalog


def _entry_keywords(entry: Dict[str, Any]) -> List[str]:
    aliases = set(_aliases_da_entrada(entry))
    aliases.update(_sem_acentos(str(entry.get("class", ""))).split())
    aliases.update(_sem_acentos(str(entry.get("module", ""))).split("."))
    aliases.update(_sem_acentos(str(entry.get("doc", ""))).split())
    for parametro in entry.get("params", []):
        aliases.update(_sem_acentos(str(parametro)).split("_"))
    return sorted(alias for alias in aliases if alias)


def _score_entry(entry: Dict[str, Any], query: str) -> float:
    q = _sem_acentos(query)
    if not q:
        return 0.0

    score = 0.0
    name = _sem_acentos(str(entry.get("class", "")))
    module = _sem_acentos(str(entry.get("module", "")))
    doc = _sem_acentos(str(entry.get("doc", "")))
    aliases = _entry_keywords(entry)

    if q == name:
        score += 80.0
    if q == module.split(".")[-1]:
        score += 60.0

    for alias in aliases:
        if not alias:
            continue
        if alias == q:
            score += 70.0 + len(alias.split()) * 2.0
        elif alias in q:
            score += 30.0 + len(alias.split())
        elif q in alias:
            score += 20.0

    q_parts = set(q.split())
    if q_parts:
        score += 3.0 * len(q_parts & set(name.split()))
        score += 1.5 * len(q_parts & set(module.split(".")))
        # Keep doc text as a weak hint only; aliases and class names should dominate.
        score += 2.0 * len(q_parts & set(aliases))

    if q in doc:
        score += 0.5
    return score


def search_catalog(catalog: Dict[str, Any], query: str, limit: int = 12) -> List[Dict[str, Any]]:
    entries = catalog.get("entries", [])
    if not entries or not query:
        return []
    scored = []
    for e in entries:
        score = _score_entry(e, query)
        if score > 0:
            item = dict(e)
            item["search_score"] = round(score, 3)
            scored.append((score, item))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("class", ""))))
    return [e for _score, e in scored[:limit]]


def datetime_now_iso() -> str:
    try:
        import datetime as _dt
        return _dt.datetime.now().isoformat(timespec="seconds")
    except Exception:
        return ""




