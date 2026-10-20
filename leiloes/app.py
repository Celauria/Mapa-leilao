"""Interface web local: mapa + filtros + ficha do imóvel.  python -m leiloes.cli web"""
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .db import conectar
from .score import calcular, referencia_m2

app = Flask(__name__)
STATIC = Path(__file__).parent / "static"


@app.after_request
def cabecalhos(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com; connect-src 'self'"
    )
    return resp


@app.get("/")
def index():
    return send_file(STATIC / "index.html")


@app.get("/app.js")
def js():
    return send_file(STATIC / "app.js")


@app.get("/api/imoveis")
def imoveis():
    con = conectar()
    sql = "SELECT * FROM imovel WHERE ativo=1"
    args = []
    filtros = {"uf": "uf = ?", "cidade": "cidade = ?", "modalidade": "modalidade = ?"}
    for campo, cond in filtros.items():
        if request.args.get(campo):
            sql += f" AND {cond}"; args.append(request.args[campo])
    if request.args.get("preco_max"):
        sql += " AND preco <= ?"; args.append(float(request.args["preco_max"]))
    if request.args.get("desconto_min"):
        sql += " AND desconto >= ?"; args.append(float(request.args["desconto_min"]))
    if request.args.get("busca"):
        sql += " AND (bairro LIKE ? OR endereco LIKE ? OR descricao LIKE ?)"
        args += [f"%{request.args['busca']}%"] * 3
    linhas = [dict(r) for r in con.execute(sql + " LIMIT 5000", args)]
    editais = {r["imovel_id"]: dict(r) for r in con.execute("SELECT * FROM edital")}
    ref = referencia_m2([dict(r) for r in con.execute("SELECT cidade,bairro,area_privativa,valor_avaliacao FROM imovel")])
    for im in linhas:
        im.update(calcular(im, editais.get(im["id"]), ref))
        im["edital"] = editais.get(im["id"])
    linhas.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(linhas)


@app.get("/api/opcoes")
def opcoes():
    con = conectar()
    q = lambda c: [r[0] for r in con.execute(f"SELECT DISTINCT {c} FROM imovel WHERE ativo=1 AND {c} IS NOT NULL ORDER BY 1")]
    return jsonify({"uf": q("uf"), "cidade": q("cidade"), "modalidade": q("modalidade")})


@app.get("/api/historico/<path:iid>")
def historico(iid):
    con = conectar()
    return jsonify([dict(r) for r in con.execute(
        "SELECT data, preco FROM historico_preco WHERE imovel_id=? ORDER BY data", (iid,))])
