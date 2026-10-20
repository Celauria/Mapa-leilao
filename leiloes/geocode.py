"""Geocodificação com Nominatim (OpenStreetMap), gratuita, limite de 1 req/s.

Tenta o endereço completo; se falhar, cai para bairro+cidade (precisão menor,
marcada no mapa). Tudo fica em cache no banco para não repetir consultas.
"""
import json
import re
import time
import urllib.parse
import urllib.request

from .db import conectar

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "mapa-leiloes-pessoal/0.1 (uso pessoal)"


def _limpar_endereco(end: str) -> str:
    end = re.sub(r",?\s*(apto|ap|apartamento|casa|bloco|bl|lote|lt|quadra|qd|unid)\b.*$", "", end or "", flags=re.I)
    return re.sub(r"\s+", " ", end).strip(" ,")


def _consultar(q: str):
    url = NOMINATIM + "?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "countrycodes": "br"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        dados = json.load(r)
    time.sleep(1.1)
    return (float(dados[0]["lat"]), float(dados[0]["lon"])) if dados else None


def geocodificar(con, endereco, bairro, cidade, uf):
    tentativas = [
        (f"{_limpar_endereco(endereco)}, {bairro}, {cidade}, {uf}", "endereco"),
        (f"{bairro}, {cidade}, {uf}", "bairro"),
        (f"{cidade}, {uf}", "cidade"),
    ]
    for q, precisao in tentativas:
        hit = con.execute("SELECT lat, lon, precisao FROM geocache WHERE consulta=?", (q,)).fetchone()
        if hit:
            if hit["lat"] is not None:
                return hit["lat"], hit["lon"], hit["precisao"]
            continue
        pos = _consultar(q)
        con.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?,?)",
                    (q, pos[0] if pos else None, pos[1] if pos else None, precisao))
        con.commit()
        if pos:
            return pos[0], pos[1], precisao
    return None, None, None


def geocodificar_pendentes(limite: int = 200):
    con = conectar()
    pend = con.execute("SELECT id, endereco, bairro, cidade, uf FROM imovel WHERE lat IS NULL AND ativo=1 LIMIT ?",
                       (limite,)).fetchall()
    ok = 0
    for p in pend:
        lat, lon, _ = geocodificar(con, p["endereco"], p["bairro"], p["cidade"], p["uf"])
        if lat:
            con.execute("UPDATE imovel SET lat=?, lon=? WHERE id=?", (lat, lon, p["id"]))
            con.commit()
            ok += 1
    return {"pendentes": len(pend), "geocodificados": ok}
