from src.altair.core import geo_weather_core as gw


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_obter_clima_cidade_formatado_preserva_acentos(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        if "nominatim.openstreetmap.org" in url:
            return FakeResponse(
                200,
                [
                    {
                        "lat": "20.3155",
                        "lon": "-40.3128",
                        "display_name": "Vitória, Espírito Santo, Brasil",
                        "address": {
                            "city": "Vitória",
                            "state": "Espírito Santo",
                            "country": "Brasil",
                        },
                    }
                ],
            )
        return FakeResponse(
            200,
            {
                "current": {
                    "temperature_2m": 28.9,
                    "apparent_temperature": 33,
                    "relative_humidity_2m": 68,
                    "precipitation": 0.1,
                    "weather_code": 2,
                    "wind_speed_10m": 13.4,
                }
            },
        )

    monkeypatch.setattr(gw.requests, "get", fake_get)

    texto_visual, texto_fala = gw.obter_clima_cidade_formatado("Vitória")

    assert len(calls) == 2
    assert "sensa" in texto_visual.lower()
    assert "precipita" in texto_visual.lower()
    assert "sensação" in texto_visual
    assert "precipitação" in texto_visual
    assert "milímetros" in texto_fala
    assert "quilômetros por hora" in texto_fala
    assert "?" not in texto_visual
    assert "?" not in texto_fala
