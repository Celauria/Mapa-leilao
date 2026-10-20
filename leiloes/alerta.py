"""Rotina diária: coleta as UFs dos filtros, acha novidades e avisa.

  python -m leiloes.cli alerta                 # usa filtros.json
  python -m leiloes.cli alerta --teste         # não envia, só mostra

Canal de aviso (variáveis de ambiente, pode usar os dois):
  Telegram: TELEGRAM_TOKEN e TELEGRAM_CHAT_ID
  E-mail:   SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, ALERTA_PARA
Sem nenhum configurado, o resultado só vai para a tela e para o relatório HTML.
"""
import html
import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from . import coleta_caixa, geocode
from .coleta_caixa import _norm
from .db import conectar

RAIZ = Path(__file__).resolve().parent.parent


def carregar_filtros(caminho=None) -> dict:
    return json.loads(Path(caminho or RAIZ / "filtros.json").read_text(encoding="utf-8"))


def bate(im: dict, f: dict) -> bool:
    if f.get("uf") and im.get("uf") != f["uf"]:
        return False
    if f.get("cidade") and _norm(im.get("cidade") or "") != _norm(f["cidade"]):
        return False
    if f.get("preco_max") and (im.get("preco") or 0) > f["preco_max"]:
        return False
    if f.get("desconto_min") and (im.get("desconto") or 0) < f["desconto_min"]:
        return False
    return True


def _brl(v):
    return "—" if v is None else "R$ " + f"{v:,.0f}".replace(",", ".")



def montar(resultado_coleta: dict, cfg: dict) -> list[dict]:
    """Lista de achados: novos e (opcionalmente) quedas de preço que batem com algum filtro."""
    con = conectar()
    achados = []
    for uf, r in resultado_coleta.items():
        # Na primeira carga de uma UF tudo é "novo": registra como linha de base, sem alertar.
        if r["total"] and len(r["novos"]) == r["total"]:
            continue
        ids = [(i, "novo") for i in r["novos"]]
        if cfg.get("avisar_queda_de_preco", True):
            ids += [(i, "queda") for i in r["preco_alterado"]]
        for iid, motivo in ids:
            im = dict(con.execute("SELECT * FROM imovel WHERE id=?", (iid,)).fetchone())
            filtro = next((f for f in cfg["filtros"] if bate(im, f)), None)
            if not filtro:
                continue
            if motivo == "queda":
                antes = r.get("preco_anterior", {}).get(iid)
                if antes is None or im["preco"] is None or im["preco"] >= antes:
                    continue  # só avisa quando o preço caiu
                im["preco_anterior"] = antes
            im["motivo"], im["filtro"] = motivo, filtro["nome"]
            achados.append(im)
    achados.sort(key=lambda x: (x["filtro"], -(x.get("desconto") or 0)))
    return achados


def texto(achados: list[dict]) -> str:
    if not achados:
        return "Leilões: nada novo nos seus filtros hoje."
    linhas = [f"Leilões: {len(achados)} novidade(s) nos seus filtros"]
    for f in sorted({a["filtro"] for a in achados}):
        linhas.append(f"\n{f}")
        for a in (x for x in achados if x["filtro"] == f):
            preco = _brl(a["preco"])
            if a["motivo"] == "queda":
                preco = f"{_brl(a['preco_anterior'])} → {preco}"
            area = f" · {a['area_privativa']:.0f} m²" if a.get("area_privativa") else ""
            linhas.append(f"• {preco} (-{a.get('desconto') or 0:.0f}%) {a.get('tipo') or 'Imóvel'}{area} · "
                          f"{a.get('bairro')}, {a.get('cidade')} · {a.get('modalidade')}\n  {a.get('link')}")
    return "\n".join(linhas)


def relatorio_html(achados: list[dict]) -> Path:
    e = lambda v: html.escape(str(v if v is not None else ""))
    linhas = "".join(
        f"<tr><td>{e(a['filtro'])}</td><td>{'Queda' if a['motivo'] == 'queda' else 'Novo'}</td>"
        f"<td>{e(_brl(a['preco']))}</td><td>{e(a.get('desconto'))}%</td><td>{e(a.get('tipo'))}</td>"
        f"<td>{e(a.get('bairro'))}, {e(a.get('cidade'))}</td><td>{e(a.get('modalidade'))}</td>"
        f"<td><a href='{e(a.get('link'))}' rel='noopener noreferrer'>abrir</a></td></tr>"
        for a in achados if str(a.get("link", "")).startswith("https://"))
    pasta = RAIZ / "relatorios"; pasta.mkdir(exist_ok=True)
    arq = pasta / f"alerta_{datetime.now():%Y-%m-%d}.html"
    arq.write_text(
        "<!doctype html><meta charset='utf-8'><title>Leilões do dia</title>"
        "<style>body{font:14px system-ui;margin:24px}td,th{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}</style>"
        f"<h1>Leilões — {datetime.now():%d/%m/%Y}</h1><table><tr><th>Filtro</th><th>Novidade</th><th>Preço</th>"
        f"<th>Desc.</th><th>Imóvel</th><th>Local</th><th>Modalidade</th><th></th></tr>{linhas}</table>",
        encoding="utf-8")
    return arq


def enviar_telegram(msg: str):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    for i in range(0, len(msg), 3800):  # limite de 4096 caracteres por mensagem
        dados = urllib.parse.urlencode({"chat_id": chat, "text": msg[i:i + 3800],
                                        "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", dados, timeout=30)
    return True


def enviar_email(msg: str, anexo: Path):
    host, para = os.getenv("SMTP_HOST"), os.getenv("ALERTA_PARA")
    if not (host and para):
        return False
    m = EmailMessage()
    m["Subject"] = msg.splitlines()[0]
    m["From"] = os.getenv("SMTP_USER")
    m["To"] = para
    m.set_content(msg)
    m.add_attachment(anexo.read_bytes(), maintype="text", subtype="html", filename=anexo.name)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        s.send_message(m)
    return True


def rodar(teste: bool = False, caminho_filtros=None, resultado_coleta=None) -> list[dict]:
    cfg = carregar_filtros(caminho_filtros)
    ufs = sorted({f["uf"] for f in cfg["filtros"]})
    resultado = resultado_coleta or coleta_caixa.coletar(ufs)
    for uf, r in resultado.items():
        print(f"{uf}: {r['total']} imóveis · {len(r['novos'])} novos · {len(r['preco_alterado'])} preço alterado")
    achados = montar(resultado, cfg)
    msg = texto(achados)
    base = [uf for uf, r in resultado.items() if r["total"] and len(r["novos"]) == r["total"]]
    if base:
        con = conectar()
        n = sum(1 for row in con.execute("SELECT * FROM imovel WHERE ativo=1")
                if any(bate(dict(row), f) for f in cfg["filtros"]))
        msg = (f"Leilões: primeira carga de {', '.join(base)} feita — {n} imóveis já batem com seus filtros "
               f"(veja no mapa). A partir de amanhã você recebe só o que for novo ou baixar de preço.")
    arq = relatorio_html(achados)
    print(msg, f"\nRelatório: {arq}", sep="\n")
    if not teste and achados:
        canais = [c for c, ok in (("Telegram", enviar_telegram(msg)), ("e-mail", enviar_email(msg, arq))) if ok]
        print("Enviado por: " + (", ".join(canais) or "nenhum canal configurado"))
    try:  # deixa o mapa pronto para os imóveis dos filtros
        geocode.geocodificar_pendentes(cfg.get("geocodificar_ate", 300))
    except Exception as exc:
        print(f"Geocodificação adiada: {exc}")
    return achados
