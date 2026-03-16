import ast
import json
import os
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


def build_catalog() -> Dict[str, Any]:
    catalog: Dict[str, Any] = {
        "generated_at": datetime_now_iso(),
        "entries": [],
    }
    catalog["entries"].extend(_scan_cq_gears())
    catalog["entries"].extend(_scan_cq_warehouse())
    catalog["entries"].extend(_scan_cqparts())
    return catalog


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
        return data
    catalog = build_catalog()
    save_catalog(path, catalog)
    return catalog


def _score_entry(entry: Dict[str, Any], query: str) -> float:
    q = query.lower()
    score = 0.0
    name = str(entry.get("class", "")).lower()
    module = str(entry.get("module", "")).lower()
    doc = str(entry.get("doc", "")).lower()

    for part in q.split():
        if part in name:
            score += 3.0
        if part in module:
            score += 1.5
        if part in doc:
            score += 1.0
    if q and name.startswith(q):
        score += 2.0
    return score


def search_catalog(catalog: Dict[str, Any], query: str, limit: int = 12) -> List[Dict[str, Any]]:
    entries = catalog.get("entries", [])
    if not entries or not query:
        return []
    scored = []
    for e in entries:
        score = _score_entry(e, query)
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _score, e in scored[:limit]]


def datetime_now_iso() -> str:
    try:
        import datetime as _dt
        return _dt.datetime.now().isoformat(timespec="seconds")
    except Exception:
        return ""

