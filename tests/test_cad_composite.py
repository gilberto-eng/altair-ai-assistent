import pytest
from src.altair.core.cad_library_catalog import search_catalog, ensure_catalog
from src.altair.core import cad_core
from src.altair.core.cad_core import gerar_projeto_cad


@pytest.fixture
def catalog_path(tmp_path):
    path = tmp_path / "catalog.json"
    return str(path)


def test_search_catalog_base_pieces():
    cat = ensure_catalog("data/json/cad_library_catalog.json")
    cubo = search_catalog(cat, "cubo", 1)
    assert len(cubo) > 0
    assert "Cube" in cubo[0]["class"] or "Box" in cubo[0]["class"]

    gear = search_catalog(cat, "engrenagem", 1)
    assert len(gear) > 0
    assert "SpurGear" in gear[0]["class"]


def test_gerar_projeto_cad_detects_assembly(monkeypatch):
    esperado = {"visual": "assembly", "fala": ""}
    monkeypatch.setattr(cad_core, "gerar_assembly_cad", lambda comando, ia_llm, base_dir: esperado)

    result = gerar_projeto_cad("cubo com cilindro", None, ".")
    assert result == esperado


def test_gerar_projeto_cad_duas_engrenagens_com_eixo(monkeypatch):
    esperado = {"visual": "ok", "fala": "", "file": "x.stl"}

    def _stub(comando, base_dir):
        assert "engrenagens" in comando.lower()
        return esperado

    monkeypatch.setattr(cad_core, "_gerar_modelo_duas_engrenagens_com_eixo", _stub)

    result = gerar_projeto_cad("crie um modelo 3d de 2 engrenagens com um eixo", None, ".")
    assert result == esperado


def test_gerar_projeto_cad_peca_unica(monkeypatch):
    esperado = {"visual": "peca", "fala": "", "file": "peca.stl"}

    def _stub(nome):
        assert nome == "cubo"
        return esperado

    monkeypatch.setattr(cad_core, "_gerar_peca_simples_local", _stub)

    result = gerar_projeto_cad("crie um cubo 3d", None, ".")
    assert result == esperado


def test_catalog_base_manual():
    cat = ensure_catalog("data/json/cad_library_catalog.json")
    assert any("basic_primitives" in e["module"] for e in cat["entries"])
    assert any("Cube" in e["class"] for e in cat["entries"])


def test_search_catalog_aliases_for_shaft():
    cat = ensure_catalog("data/json/cad_library_catalog.json")
    eixo = search_catalog(cat, "eixo", 1)
    assert len(eixo) > 0
    assert eixo[0]["class"] == "Shaft"


def test_gerar_projeto_cad_catalog_piece(monkeypatch):
    esperado = {"visual": "catalogo", "fala": "", "file": "rolamento.stl"}

    def _stub(entry, base_dir):
        assert entry["class"] == "Bearing"
        return esperado

    monkeypatch.setattr(cad_core, "_gerar_peca_do_catalogo", _stub)

    result = gerar_projeto_cad("gere um rolamento 3d", None, ".")
    assert result == esperado


def test_gerar_assembly_cad_usa_planner_langchain(monkeypatch):
    esperado = {"visual": "langchain", "fala": "", "file": "x.stl"}

    def _planner(comando, catalogo, llm):
        assert "cubo" in comando.lower()
        return {
            "mode": "assembly",
            "confidence": 0.93,
            "summary": "assembly simples",
            "pieces": [
                {"query": "cubo", "class": "Cube", "quantity": 1, "params": {}, "reason": "base"},
                {"query": "cilindro", "class": "Cylinder", "quantity": 1, "params": {}, "reason": "base"},
            ],
        }

    monkeypatch.setattr(cad_core, "planejar_cad_com_langchain", _planner)
    monkeypatch.setattr(cad_core, "_gerar_assembly_catalogo", lambda pedidos, base_dir: esperado)

    result = cad_core.gerar_assembly_cad("cubo com cilindro", object(), ".")
    assert result == esperado


def test_gerar_projeto_cad_langchain_quantity_as_assembly(monkeypatch):
    esperado = {"visual": "quantidade", "fala": "", "file": "x.stl"}

    def _planner(comando, catalogo, llm):
        return {
            "mode": "single_piece",
            "confidence": 0.9,
            "summary": "duas unidades",
            "pieces": [
                {"query": "rolamento", "class": "Bearing", "quantity": 2, "params": {}, "reason": "pedido duplicado"},
            ],
        }

    monkeypatch.setattr(cad_core, "planejar_cad_com_langchain", _planner)
    monkeypatch.setattr(cad_core, "_gerar_assembly_catalogo", lambda pedidos, base_dir: esperado)

    result = gerar_projeto_cad("gere dois rolamentos 3d", object(), ".")
    assert result == esperado


def test_catalog_piece_geometry_is_specific():
    cat = ensure_catalog("data/json/cad_library_catalog.json")

    bearing_entry = cad_core._resolver_entrada_catalogo("rolamento", cat)
    bearing_model = cad_core._construir_modelo_catalogo(bearing_entry)
    assert bearing_model is not None
    bearing_bb = bearing_model.val().BoundingBox()
    assert bearing_bb.xlen == 24.0
    assert bearing_bb.ylen == 24.0
    assert bearing_bb.zlen == 6.0

    screw_entry = cad_core._resolver_entrada_catalogo("parafuso", cat)
    screw_model = cad_core._construir_modelo_catalogo(screw_entry)
    assert screw_model is not None
    screw_bb = screw_model.val().BoundingBox()
    assert screw_bb.xlen == 9.0
    assert screw_bb.ylen == 9.0
    assert screw_bb.zlen == 24.0
