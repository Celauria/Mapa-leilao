"""Entorno do imóvel: estação de metrô/trem/VLT mais próxima (OpenStreetMap).

As estações de SP e SC são baixadas uma vez por mês pela Overpass API e ficam em
data/estacoes.json. A distância é em linha reta e só é informada até 3 km; para
imóveis com posição aproximada (centro do bairro/cidade) ela vale como indicação.
"""
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

OVERPASS = "https://overpass-api.de/api/interpreter"
SAIDA = Path(__file__).resolve().parent.parent / "data" / "estacoes.json"
UA = "mapa-leiloes-pessoal/0.3 (uso pessoal; github.com/Celauria/Mapa-leilao)"
CONSULTA = """
[out:json][timeout:180];
area["ISO3166-2"~"^BR-(SP|SC)$"]->.a;
(
  node["railway"="station"](area.a);
  node["station"~"^(subway|light_rail|train)$"](area.a);
  node["public_transport"="station"]["subway"="yes"](area.a);
);
out tags;
"""


def atualizar(max_dias: int = 30, forcar: bool = False) -> bool:
    if SAIDA.exists() and not forcar:
        idade = (datetime.now() - datetime.fromisoformat(json.loads(SAIDA.read_text())["gerado"])).days
        if idade < max_dias:
            print(f"Estações: lista de {idade} dia(s), sem necessidade de atualizar")
            return False
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": CONSULTA}).encode(),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=240) as r:
        dados = json.load(r)
    estacoes, vistos = [], set()
    for e in dados.get("elements", []):
        t = e.get("tags", {})
        nome = t.get("name")
        if not nome or t.get("railway") in ("halt",) and not t.get("public_transport"):
            continue
        if t.get("usage") == "freight" or t.get("disused") == "yes" or t.get("railway") == "disused_station":
            continue
        tipo = ("metrô" if t.get("station") == "subway" or t.get("subway") == "yes"
                else "VLT" if t.get("station") == "light_rail" or t.get("light_rail") == "yes" else "trem")
        chave = (nome, round(e["lat"], 3), round(e["lon"], 3))
        if chave in vistos:
            continue
        vistos.add(chave)
        estacoes.append([nome, tipo, round(e["lat"], 6), round(e["lon"], 6)])
    if len(estacoes) < 50:
        raise RuntimeError(f"Estações: só {len(estacoes)} encontradas — consulta pode ter falhado")
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(json.dumps({"gerado": datetime.now().isoformat(timespec="seconds"), "fonte": "OpenStreetMap",
                                 "estacoes": estacoes}, ensure_ascii=False, separators=(",", ":")))
    print(f"Estações: {len(estacoes)} salvas")
    return True


def _dist_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_CACHE = None


def estacao_proxima(lat, lon, raio_m: int = 3000):
    """(nome, tipo, distância em m) da estação mais próxima até raio_m, ou None."""
    global _CACHE
    if lat is None or lon is None:
        return None
    if _CACHE is None:
        _CACHE = json.loads(SAIDA.read_text())["estacoes"] if SAIDA.exists() else []
    melhor = None
    for nome, tipo, la, lo in _CACHE:
        if abs(la - lat) > 0.05 or abs(lo - lon) > 0.05:  # ~5 km: descarta rápido
            continue
        d = _dist_m(lat, lon, la, lo)
        if d <= raio_m and (melhor is None or d < melhor[2]):
            melhor = (nome, tipo, round(d))
    return melhor
