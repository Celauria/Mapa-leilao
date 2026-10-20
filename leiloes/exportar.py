"""Gera docs/imoveis.json para o mapa estático (GitHub Pages).

Exporta só os imóveis ativos que batem com algum filtro de filtros.json,
já com score, motivos e análise de edital, para o mapa rodar sem servidor.
"""
import json
from datetime import datetime
from pathlib import Path

from .alerta import bate, carregar_filtros
from .db import conectar
from .score import calcular, referencia_m2

CAMPOS = ("id", "uf", "cidade", "bairro", "endereco", "preco", "valor_avaliacao", "desconto", "tipo",
          "area_privativa", "area_total", "area_terreno", "quartos", "vagas", "modalidade", "link", "financiamento", "lat", "lon", "geo_precisao", "primeira_vez")


def exportar(destino: Path | None = None) -> Path:
    destino = destino or Path(__file__).resolve().parent.parent / "docs" / "imoveis.json"
    cfg = carregar_filtros()
    con = conectar()
    todos = [dict(r) for r in con.execute("SELECT * FROM imovel WHERE ativo=1")]
    ref = referencia_m2(todos)
    editais = {r["imovel_id"]: dict(r) for r in con.execute("SELECT * FROM edital")}
    saida = []
    for im in todos:
        f = next((f for f in cfg["filtros"] if bate(im, f)), None)
        if not f:
            continue
        ed = editais.get(im["id"])
        reg = {k: im.get(k) for k in CAMPOS}
        reg.update(calcular(im, ed, ref), filtro=f["nome"])
        if ed:
            reg["edital"] = {"resumo": ed.get("resumo"), "alertas": json.loads(ed.get("alertas") or "[]")}
        saida.append(reg)
    saida.sort(key=lambda x: x["score"], reverse=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"atualizado": datetime.now().isoformat(timespec="minutes"),
                                   "imoveis": saida}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Exportados {len(saida)} imóveis para {destino}")
    return destino
