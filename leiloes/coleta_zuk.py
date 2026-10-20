"""Coleta imóveis de bancos (Santander, Bradesco, Itaú) no Portal Zuk.

Os bancos não publicam uma lista própria: vendem por leiloeiros parceiros. O Zuk
tem uma página por vendedor (/leilao-de-imoveis/v/banco-santander etc.) com 30
imóveis; o restante vem pelo botão "Carregar mais" (POST /leilao-de-imoveis/mais).

Respeita o robots.txt do Zuk: usa só a listagem pública e a rota /mais (não
proibidas); não acessa /edital, /ajax-lote nem área de usuário. Uma requisição
a cada ~2 s, uma vez por dia.
"""
import http.cookiejar
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime

from bs4 import BeautifulSoup

BASE = "https://www.portalzuk.com.br"
BANCOS = {
    "Santander": "banco-santander",
    "Bradesco": "banco-bradesco",
    "Itaú": "banco-itau",
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
PAUSA = 2.0
MAX_PAGINAS = 60  # 30 + 60×20 ≈ 1.200 imóveis por banco, folga para o volume atual


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper().strip()


def _brl(t: str):
    m = re.search(r"([\d.]+,\d{2})", t or "")
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def _data(t: str):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\D+(\d{2}):(\d{2})", t or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)} {m.group(4)}:{m.group(5)}" if m else None


def _num(t: str):
    m = re.search(r"([\d.]+(?:,\d+)?)", t or "")
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def parse_cards(html: str, banco: str) -> list[dict]:
    """Converte os cards da listagem no mesmo formato dos imóveis da Caixa."""
    s = BeautifulSoup(html, "html.parser")
    imoveis = []
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    for c in s.select(".card_lotes_div"):
        a = c.select_one(".card-property-image-wrapper a[href*='/imovel/']") or c.select_one("a[href*='/imovel/']")
        if not a:
            continue
        link = a["href"].split("?")[0]
        codigo = link.rstrip("/").rsplit("/", 1)[-1]
        partes = urllib.parse.urlparse(link).path.strip("/").split("/")  # imovel/uf/cidade/bairro/rua/id
        uf = partes[1].upper() if len(partes) > 1 else None

        end = c.select_one(".card-property-address")
        spans = end.select("span") if end else []
        cidade_bairro = spans[0].get_text(" ", strip=True) if spans else ""      # "Pinhais / PR - Centro"
        m = re.match(r"(.+?)\s*/\s*([A-Z]{2})\s*(?:-\s*(.*))?$", cidade_bairro)
        cidade = _sem_acento(m.group(1)) if m else None
        uf = (m.group(2) if m else uf)
        bairro = _sem_acento(m.group(3)) if m and m.group(3) else None
        endereco = re.sub(r"\s+", " ", spans[1].get_text(" ", strip=True)) if len(spans) > 1 else None

        tipo_el = c.select_one(".card-property-price-lote")
        tipo = tipo_el.get_text(" ", strip=True) if tipo_el else None

        area_priv = area_terreno = quartos = None
        for li in c.select(".card-property-info"):
            icone = (li.select_one("use") or {}).get("xlink:href", "") if li.select_one("use") else ""
            txt = li.get_text(" ", strip=True)
            if "area" in icone:
                v = _num(txt)
                if "ha" in txt and "terreno" in txt:
                    area_terreno = v * 10000 if v else None
                elif "terreno" in txt:
                    area_terreno = v
                else:  # construída / útil / privativa
                    area_priv = v
            elif "bed" in icone:
                quartos = int(_num(txt) or 0) or None

        pracas = []
        for li in c.select(".card-property-price"):
            rot = li.select_one(".card-property-price-label")
            val = li.select_one(".card-property-price-value")
            if not (rot and val):
                continue
            pct = li.select_one(".card-property-price-percent")
            dt = li.select_one(".card-property-price-data")
            pracas.append({"rotulo": rot.get_text(" ", strip=True), "valor": _brl(val.get_text(" ", strip=True)),
                           "data": _data(dt.get_text(" ", strip=True)) if dt else None,
                           "pct": _num(pct.get_text(" ", strip=True)) if pct else None})
        if not pracas:
            continue
        # preço de referência: a próxima praça; se todas passaram, a última
        futuras = [p for p in pracas if p["data"] and p["data"] >= agora and p["valor"]]
        atual = futuras[0] if futuras else pracas[-1]
        p1 = pracas[0]
        p2 = pracas[1] if len(pracas) > 1 else None
        # Desconto: o % que o Zuk exibe. Com 2 praças, vale o da 2ª (o menor valor pelo qual o
        # imóvel ainda pode sair), medido sobre a 1ª — no leilão extrajudicial a 1ª parte do valor do imóvel.
        desconto = atual["pct"]
        if p2 and p2["valor"] and p1["valor"] and (p2["data"] or "") >= agora[:10]:
            desconto = p2["pct"] if p2["pct"] is not None else round((1 - p2["valor"] / p1["valor"]) * 100, 1)
        modalidade = "Leilão (Zuk)" if len(pracas) > 1 or "leil" in p1["rotulo"].lower() else "Proposta/lance inicial (Zuk)"

        imoveis.append({
            "codigo": codigo, "uf": uf, "cidade": cidade, "bairro": bairro, "endereco": endereco,
            "preco": atual["valor"], "valor_avaliacao": None, "desconto": desconto,
            "descricao": a.get("title"), "tipo": tipo, "area_privativa": area_priv, "area_total": None,
            "area_terreno": area_terreno, "quartos": quartos, "vagas": None,
            "modalidade": modalidade, "link": link, "financiamento": None, "banco": banco,
            "praca1_valor": p1["valor"], "praca1_data": p1["data"],
            "praca2_valor": p2["valor"] if p2 else None, "praca2_data": p2["data"] if p2 else None,
        })
    return imoveis


class _Sessao:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("User-Agent", UA), ("Accept-Language", "pt-BR,pt;q=0.9")]

    def get(self, url):
        with self.op.open(url, timeout=60) as r:
            corpo = r.read().decode("utf-8", "replace")
        time.sleep(PAUSA)
        return corpo

    def post(self, url, dados, referer):
        req = urllib.request.Request(url, data=urllib.parse.urlencode(dados).encode(), headers={
            "X-Requested-With": "XMLHttpRequest", "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        with self.op.open(req, timeout=60) as r:
            corpo = r.read().decode("utf-8", "replace")
        time.sleep(PAUSA)
        return corpo


def coletar_banco(banco: str, slug: str) -> tuple[list[dict], bool]:
    """Devolve (imóveis, completo). completo=False se a paginação falhou no meio."""
    s = _Sessao()
    url = f"{BASE}/leilao-de-imoveis/v/{slug}"
    html = s.get(url)
    vistos, todos = set(), []

    def juntar(lote):
        novos = [i for i in lote if i["codigo"] not in vistos]
        for i in novos:
            vistos.add(i["codigo"])
        todos.extend(novos)
        return len(novos)

    juntar(parse_cards(html, banco))
    tok = re.search(r'name="_token"\s+value="([^"]+)"', html)
    ordem = re.search(r'id="ordenar".*?<option value="([^"]+)"[^>]*selected', html, re.S)
    completo = True
    for _ in range(MAX_PAGINAS):
        if not tok:
            completo = False
            break
        n = len(todos)
        try:
            resp = s.post(f"{BASE}/leilao-de-imoveis/mais", {
                "limit": n, "count_imovel_zuk": n, "path": url, "order": ordem.group(1) if ordem else "data_leilao",
                "div_parceiro_count": 0, "_token": tok.group(1)}, referer=url)
        except Exception as exc:
            print(f"::warning title=Zuk {banco}::'carregar mais' falhou após {n} imóveis ({exc})")
            completo = False
            break
        if juntar(parse_cards(resp, banco)) == 0:
            break  # acabou
    msg = f"Zuk/{banco}: {len(todos)} imóveis{'' if completo else ' (parcial)'}"
    print(msg)
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::notice title=Coleta Zuk::{msg}")
    return todos, completo


def coletar(bancos=None) -> dict:
    from .coleta_caixa import gravar
    resultado = {}
    for banco, slug in (bancos or BANCOS).items():
        try:
            imoveis, completo = coletar_banco(banco, slug)
        except Exception as exc:
            print(f"::warning title=Zuk {banco}::{type(exc).__name__}: {exc}")
            continue
        if imoveis:
            resultado[f"Zuk/{banco}"] = gravar(imoveis, fonte="zuk", banco=banco if completo else None)
    return resultado
