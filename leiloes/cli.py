"""Linha de comando.

  python -m leiloes.cli coletar SP RJ          # baixa listas da Caixa
  python -m leiloes.cli coletar SP --arquivo exemplo.csv
  python -m leiloes.cli geocodificar --limite 300
  python -m leiloes.cli edital caixa:155551234 edital.pdf
  python -m leiloes.cli novos --desconto-min 40 --preco-max 400000
  python -m leiloes.cli web                     # http://127.0.0.1:5000
"""
import argparse
import json

from . import coleta_caixa, geocode
from .db import conectar


def _carregar_env():
    """Lê .env da raiz do projeto, sem sobrescrever variáveis já definidas."""
    from pathlib import Path
    import os
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


def main():
    _carregar_env()
    ap = argparse.ArgumentParser(prog="leiloes")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("coletar"); c.add_argument("ufs", nargs="*", default=["SP"]); c.add_argument("--arquivo")
    g = sub.add_parser("geocodificar"); g.add_argument("--limite", type=int, default=200)
    e = sub.add_parser("edital"); e.add_argument("imovel_id"); e.add_argument("pdf")
    n = sub.add_parser("novos", help="imóveis vistos pela 1ª vez nas últimas 24h que batem com o filtro")
    n.add_argument("--desconto-min", type=float, default=0); n.add_argument("--preco-max", type=float)
    n.add_argument("--cidade")
    w = sub.add_parser("web"); w.add_argument("--porta", type=int, default=5000)
    al = sub.add_parser("alerta", help="coleta as UFs de filtros.json e avisa o que é novo ou baixou de preço")
    al.add_argument("--teste", action="store_true", help="não envia, só mostra"); al.add_argument("--filtros")
    sub.add_parser("exportar", help="gera docs/imoveis.json para o mapa estático")
    me = sub.add_parser("mercado", help="atualiza a referência de mercado de SP (ITBI), no máximo 1x por mês")
    me.add_argument("--forcar", action="store_true")
    en = sub.add_parser("entorno", help="atualiza a lista de estações (OpenStreetMap), no máximo 1x por mês")
    en.add_argument("--forcar", action="store_true")

    a = ap.parse_args()
    if a.cmd == "coletar":
        r = coleta_caixa.coletar([u.upper() for u in a.ufs], a.arquivo)
        for uf, x in r.items():
            print(f"{uf}: {x['total']} imóveis · {len(x['novos'])} novos · {len(x['preco_alterado'])} com preço alterado · {x['removidos']} saíram da lista")
    elif a.cmd == "geocodificar":
        print(geocode.geocodificar_pendentes(a.limite))
    elif a.cmd == "edital":
        from .edital import analisar
        print(json.dumps(analisar(a.imovel_id, a.pdf), ensure_ascii=False, indent=2))
    elif a.cmd == "novos":
        sql = "SELECT * FROM imovel WHERE ativo=1 AND primeira_vez >= datetime('now','-1 day') AND desconto >= ?"
        args = [a.desconto_min]
        if a.preco_max: sql += " AND preco <= ?"; args.append(a.preco_max)
        if a.cidade: sql += " AND cidade = ?"; args.append(a.cidade.upper())
        for r in conectar().execute(sql + " ORDER BY desconto DESC", args):
            print(f"{r['preco']:>12,.0f}  -{r['desconto']:.0f}%  {r['bairro']}, {r['cidade']}  {r['link']}")
    elif a.cmd == "alerta":
        from .alerta import rodar
        rodar(teste=a.teste, caminho_filtros=a.filtros)
    elif a.cmd == "mercado":
        from .mercado_sp import atualizar
        atualizar(forcar=a.forcar)
    elif a.cmd == "entorno":
        from .entorno import atualizar
        atualizar(forcar=a.forcar)
    elif a.cmd == "exportar":
        from .exportar import exportar
        exportar()
    elif a.cmd == "web":
        from .app import app
        app.run(host="127.0.0.1", port=a.porta)


if __name__ == "__main__":
    main()
