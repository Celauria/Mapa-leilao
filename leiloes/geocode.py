"""Geocodificação com Nominatim (OpenStreetMap), gratuita, limite de 1 req/s.

Duas etapas para o mapa encher rápido:
  1. Todo imóvel sem posição recebe a do bairro (ou da cidade). Muitos imóveis
     compartilham bairro e o cache evita repetir consultas, então é rápido.
  2. Depois, até `limite` imóveis por execução são refinados para o endereço exato.
O campo geo_precisao (endereco / bairro / cidade) fica salvo e aparece no mapa.
"""
import json
import os
import re
import urllib.error
import time
import urllib.parse
import urllib.request

from .db import conectar

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "mapa-leiloes-pessoal/0.2 (uso pessoal; github.com/Celauria/Mapa-leilao)"


def _limpar_endereco(end: str) -> str:
    end = re.sub(r",?\s*(apto|ap|apartamento|casa|bloco|bl|lote|lt|quadra|qd|unid|sala)\b.*$", "", end or "", flags=re.I)
    end = re.sub(r"\bN\.\s*", "", end)
    return re.sub(r"\s+", " ", end).strip(" ,-")


class GeoIndisponivel(Exception):
    """O serviço recusou várias vezes seguidas; para e tenta de novo amanhã."""


_FALHAS_SEGUIDAS = 0


def _aviso(msg: str):
    print(msg)
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::warning title=Geocodificação::{msg[:900]}")


def _consultar(q: str):
    """Consulta o Nominatim com até 3 tentativas. None = lugar não encontrado."""
    global _FALHAS_SEGUIDAS
    url = NOMINATIM + "?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "countrycodes": "br"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = json.load(r)
            _FALHAS_SEGUIDAS = 0
            time.sleep(1.1)
            return (float(dados[0]["lat"]), float(dados[0]["lon"])) if dados else None
        except urllib.error.HTTPError as exc:
            corpo = exc.read()[:300].decode("utf-8", "replace")
            erro = f"HTTP {exc.code} {exc.reason} · {' '.join(corpo.split())}"
        except Exception as exc:
            erro = f"{type(exc).__name__}: {exc}"
        _FALHAS_SEGUIDAS += 1
        if _FALHAS_SEGUIDAS == 1 or _FALHAS_SEGUIDAS % 10 == 0:
            _aviso(f"Falha ao consultar '{q[:60]}': {erro}")
        if _FALHAS_SEGUIDAS >= 15:
            raise GeoIndisponivel(f"Nominatim indisponível após {_FALHAS_SEGUIDAS} falhas seguidas ({erro})")
        time.sleep(5 * (tentativa + 1))
    return "erro"  # não grava no cache: tenta de novo na próxima execução


def _cache(con, q, precisao):
    """(lat, lon) do cache ou da API; None se o lugar não existe."""
    hit = con.execute("SELECT lat, lon FROM geocache WHERE consulta=?", (q,)).fetchone()
    if hit:
        return (hit["lat"], hit["lon"]) if hit["lat"] is not None else None
    pos = _consultar(q)
    if pos == "erro":
        return "erro"  # falha de rede: não grava no cache
    con.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?,?)",
                (q, pos[0] if pos else None, pos[1] if pos else None, precisao))
    con.commit()
    return pos


def _aproximado(con, im):
    for q, precisao in ((f"{im['bairro']}, {im['cidade']}, {im['uf']}", "bairro"),
                        (f"{im['cidade']}, {im['uf']}", "cidade")):
        pos = _cache(con, q, precisao)
        if pos and pos != "erro":
            return pos, precisao
    return None, None


def geocodificar_pendentes(limite: int = 200, tempo_max: int = 1800, filtro=None):
    """Etapa 1 para todos os pendentes, etapa 2 para até `limite`; para em `tempo_max` segundos."""
    con = conectar()
    inicio = time.time()
    fim = lambda: time.time() - inicio > tempo_max
    resumo = {"aproximados": 0, "refinados": 0, "sem_posicao": 0}

    ok = filtro or (lambda im: True)  # só geocodifica o que aparece no mapa
    pend = [im for im in con.execute("SELECT * FROM imovel WHERE lat IS NULL AND ativo=1 ORDER BY preco")
            if ok(dict(im))]
    try:
        _etapas(con, pend, ok, limite, fim, resumo)
    except GeoIndisponivel as exc:
        _aviso(str(exc))
        resumo["interrompido"] = True
    con.commit()
    resumo["segundos"] = round(time.time() - inicio)
    print(f"Geocodificação: {resumo}")
    return resumo


def _etapas(con, pend, ok, limite, fim, resumo):
    for n, im in enumerate(pend, 1):
        if fim():
            break
        if n % 25 == 0:
            con.commit()
        pos, precisao = _aproximado(con, im)
        if pos:
            con.execute("UPDATE imovel SET lat=?, lon=?, geo_precisao=? WHERE id=?", (*pos, precisao, im["id"]))
            resumo["aproximados"] += 1
        else:
            resumo["sem_posicao"] += 1
    con.commit()

    refinar = [im for im in con.execute(
        "SELECT * FROM imovel WHERE ativo=1 AND lat IS NOT NULL "
        "AND COALESCE(geo_precisao,'') NOT IN ('endereco','endereco-falhou') ORDER BY desconto DESC")
        if ok(dict(im))][:limite]
    for im in refinar:
        if fim():
            break
        pos = _cache(con, f"{_limpar_endereco(im['endereco'])}, {im['cidade']}, {im['uf']}", "endereco")
        if pos == "erro":
            continue
        if pos:
            con.execute("UPDATE imovel SET lat=?, lon=?, geo_precisao='endereco' WHERE id=?", (*pos, im["id"]))
            resumo["refinados"] += 1
        else:  # não tenta de novo todo dia; fica na posição do bairro
            con.execute("UPDATE imovel SET geo_precisao='endereco-falhou' WHERE id=?", (im["id"],))
        con.commit()
