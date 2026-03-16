import math
import webbrowser
from typing import Dict, Optional, Tuple
from urllib.parse import quote

import requests


USER_AGENT = "AltairAssistente/1.0 (local)"

WEATHER_CODE_DESC = {
    0: "c?u limpo",
    1: "predominantemente limpo",
    2: "parcialmente nublado",
    3: "nublado",
    45: "nevoeiro",
    48: "nevoeiro com geada",
    51: "garoa fraca",
    53: "garoa moderada",
    55: "garoa intensa",
    56: "garoa congelante fraca",
    57: "garoa congelante intensa",
    61: "chuva fraca",
    63: "chuva moderada",
    65: "chuva forte",
    66: "chuva congelante fraca",
    67: "chuva congelante forte",
    71: "neve fraca",
    73: "neve moderada",
    75: "neve forte",
    77: "gr?os de neve",
    80: "pancadas de chuva fracas",
    81: "pancadas de chuva moderadas",
    82: "pancadas de chuva fortes",
    85: "pancadas de neve fracas",
    86: "pancadas de neve fortes",
    95: "trovoada",
    96: "trovoada com granizo fraco",
    99: "trovoada com granizo forte",
}


def _nome_curto_local(item: Dict, consulta_original: str) -> str:
    addr = item.get("address", {}) if isinstance(item, dict) else {}

    cidade = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or addr.get("county")
    )
    estado = addr.get("state")
    pais = addr.get("country")

    if cidade and estado:
        if str(cidade).strip().lower() == str(estado).strip().lower():
            return str(cidade)
        return f"{cidade}, {estado}"
    if cidade and pais:
        return f"{cidade}, {pais}"
    if cidade:
        return str(cidade)
    if estado and pais:
        return f"{estado}, {pais}"
    if estado:
        return str(estado)
    if pais:
        return str(pais)
    return (consulta_original or "").strip() or "local informado"


def _geocodificar_cidade(cidade: str) -> Tuple[Optional[Dict], Optional[str]]:
    nome = (cidade or "").strip()
    if not nome:
        return None, "Cidade n?o informada."

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": nome,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
                "accept-language": "pt-BR",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
    except Exception as e:
        return None, f"Erro ao consultar localiza??o: {e}"

    if resp.status_code != 200:
        return None, f"Falha ao consultar localiza??o (HTTP {resp.status_code})."

    try:
        dados = resp.json()
    except Exception:
        return None, "Falha ao interpretar resposta de localiza??o."

    if not dados:
        return None, f"N?o encontrei a cidade '{nome}'."

    item = dados[0]
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except Exception:
        return None, f"N?o consegui coordenadas para '{nome}'."

    return {
        "nome": _nome_curto_local(item, nome),
        "nome_completo": item.get("display_name", nome),
        "lat": lat,
        "lon": lon,
    }, None


def _numero_para_visual(valor) -> str:
    if valor is None:
        return "indispon?vel"
    try:
        numero = float(valor)
    except Exception:
        return str(valor)

    if numero.is_integer():
        return str(int(numero))

    return f"{numero:.1f}".rstrip("0").rstrip(".")


def _numero_para_fala(valor) -> str:
    if valor is None:
        return "indispon?vel"
    try:
        numero = float(valor)
    except Exception:
        return str(valor)

    if numero.is_integer():
        return str(int(numero))

    texto = f"{numero:.1f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def obter_clima_cidade_formatado(cidade: str) -> Tuple[str, str]:
    geo, erro = _geocodificar_cidade(cidade)
    if erro:
        return erro, erro

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["lat"],
                "longitude": geo["lon"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=20,
        )
    except Exception as e:
        erro_txt = f"Erro ao consultar clima: {e}"
        return erro_txt, erro_txt

    if resp.status_code != 200:
        erro_txt = f"Falha ao consultar clima (HTTP {resp.status_code})."
        return erro_txt, erro_txt

    try:
        dados = resp.json()
        atual = dados.get("current", {})
    except Exception:
        erro_txt = "Falha ao interpretar resposta de clima."
        return erro_txt, erro_txt

    temp = atual.get("temperature_2m")
    sens = atual.get("apparent_temperature")
    umid = atual.get("relative_humidity_2m")
    chuva = atual.get("precipitation")
    vento = atual.get("wind_speed_10m")
    codigo = atual.get("weather_code")
    desc = WEATHER_CODE_DESC.get(codigo, "condi??o meteorol?gica n?o identificada")

    temp_visual = _numero_para_visual(temp)
    sens_visual = _numero_para_visual(sens)
    umid_visual = _numero_para_visual(umid)
    chuva_visual = _numero_para_visual(chuva)
    vento_visual = _numero_para_visual(vento)

    temp_fala = _numero_para_fala(temp)
    sens_fala = _numero_para_fala(sens)
    umid_fala = _numero_para_fala(umid)
    chuva_fala = _numero_para_fala(chuva)
    vento_fala = _numero_para_fala(vento)

    texto_visual = (
        f"Clima em {geo['nome']} agora: {desc}. "
        f"Temperatura {temp_visual}°C, sensa??o {sens_visual}°C, "
        f"umidade {umid_visual}%, precipita??o {chuva_visual} mm, "
        f"vento {vento_visual} km/h."
    )
    texto_fala = (
        f"Clima em {geo['nome']}, agora: {desc}. "
        f"Temperatura de {temp_fala} graus Celsius, sensa??o de {sens_fala} graus Celsius, "
        f"umidade de {umid_fala} por cento, precipita??o de {chuva_fala} mil?metros, "
        f"e vento de {vento_fala} quil?metros por hora."
    )
    return texto_visual, texto_fala


def obter_clima_cidade(cidade: str) -> str:
    texto_visual, _ = obter_clima_cidade_formatado(cidade)
    return texto_visual


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def montar_link_mapa_rota(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    rota = quote(f"{lat1},{lon1};{lat2},{lon2}", safe="")
    return f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={rota}"


def calcular_distancia_entre_cidades(cidade_a: str, cidade_b: str, abrir_mapa: bool = True) -> str:
    origem, erro_origem = _geocodificar_cidade(cidade_a)
    if erro_origem:
        return erro_origem

    destino, erro_destino = _geocodificar_cidade(cidade_b)
    if erro_destino:
        return erro_destino

    km = _haversine_km(origem["lat"], origem["lon"], destino["lat"], destino["lon"])
    link = montar_link_mapa_rota(origem["lat"], origem["lon"], destino["lat"], destino["lon"])

    abriu = False
    if abrir_mapa:
        try:
            abriu = webbrowser.open(link)
        except Exception:
            abriu = False

    msg_mapa = "Mapa aberto no navegador." if abriu else f"Link do mapa: {link}"
    return (
        f"Distancia aproximada entre {origem['nome']} e {destino['nome']}: {km:.1f} km. "
        f"{msg_mapa}"
    )
