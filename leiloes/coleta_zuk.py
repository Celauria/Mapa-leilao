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
import urllib.error
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
PAUSA = 3.0          # entre páginas
PAUSA_BANCO = 20     # entre um banco e outro
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

    def _abrir(self, req, tentativas: int = 4) -> str:
        """Abre com pausa entre pedidos; em 429/503 espera o que o site pedir (Retry-After) e tenta de novo."""
        for t in range(tentativas):
            try:
                with self.op.open(req, timeout=60) as r:
                    corpo = r.read().decode("utf-8", "replace")
                time.sleep(PAUSA)
                return corpo
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 503) or t == tentativas - 1:
                    raise
                espera = exc.headers.get("Retry-After")
                espera = int(espera) if espera and espera.isdigit() else 30 * (t + 1)
                print(f"Zuk pediu calma (HTTP {exc.code}); aguardando {espera}s")
                time.sleep(min(espera, 180))

    def get(self, url):
        return self._abrir(url)

    def post(self, url, dados, referer):
        req = urllib.request.Request(url, data=urllib.parse.urlencode(dados).encode(), headers={
            "X-Requested-With": "XMLHttpRequest", "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        return self._abrir(req)


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
    for n, (banco, slug) in enumerate((bancos or BANCOS).items()):
        if n:
            time.sleep(PAUSA_BANCO)
        try:
            imoveis, completo = coletar_banco(banco, slug)
        except Exception as exc:
            print(f"::warning title=Zuk {banco}::{type(exc).__name__}: {exc}")
            continue
        if imoveis:
            resultado[f"Zuk/{banco}"] = gravar(imoveis, fonte="zuk", banco=banco if completo else None)
    return resultado


# ---------- Detalhes da página do imóvel (ocupação, pagamento, observações) ----------

RISCOS = [
    (r"\bpenhora", "Penhora registrada na matrícula"),
    (r"\ba[çc][aã]o de (execu[çc][aã]o|despejo|cobran[çc]a|usucapi[aã]o|reintegra|anula)|\bprocesso n[ºo°]", "Ação judicial mencionada"),
    (r"indisponibilidade", "Indisponibilidade de bens na matrícula"),
    (r"regulariza[çc][aã]o.{0,200}(a cargo|expensas|responsabilidade) d[oe] arrematante"
     r"|arrematante.{0,80}(suas expensas|seus custos).{0,160}regulariza", "Regularização por conta do comprador"),
    (r"d[eé]bitos?.{0,120}(condom[ií]nio|iptu).{0,120}(a cargo|responsabilidade|por conta) d[oe] arrematante", "Débitos de IPTU/condomínio por conta do comprador"),
    (r"desocupa[çc][aã]o por conta do (adquirente|arrematante)", "Desocupação por conta do comprador"),
    (r"lance sujeito [àa] aprova[çc][aã]o do vendedor", "Lance sujeito à aprovação do banco"),
]


def parse_detalhe(html: str) -> dict:
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "svg", "noscript", "header", "footer", "nav"]):
        t.decompose()
    txt = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s.get_text("\n")))
    baixo = txt.lower()

    ocupado = ("sim" if re.search(r"im[óo]vel ocupado|\bocupado\.", txt, re.I)
               else "nao" if re.search(r"im[óo]vel desocupado|\bdesocupado\b", txt, re.I) else "desconhecido")

    def bloco(inicio, fins):
        i = txt.find(inicio)
        if i < 0:
            return ""
        j = min([k for k in (txt.find(f, i + len(inicio)) for f in fins) if k > 0] or [i + 1500])
        return txt[i + len(inicio):j].strip()

    obs = bloco("Observações", ["Em destaque no texto", "Histórico de alterações", "Formas de pagamento", "Documentos"])
    pag = bloco("Formas de pagamento oferecida(s) pelo comitente vendedor", ["As formas de pagamento", "Documentos"])
    descr = bloco("Descrição do imóvel", ["Matrícula do imóvel", "Observações"])
    matr = bloco("Matrícula do imóvel:", ["Observações", "Formas de pagamento"])
    junto = (obs + " " + pag).lower()
    financ = (1 if re.search(r"financiamento|financiad|cr[ée]dito imobili[áa]rio", pag, re.I)
              else 0 if re.search(r"vista", junto) else None)
    if re.search(r"\d+\s*x\b|parcela", pag, re.I) and not financ:
        alertas_extra = ["Parcelamento direto com o banco (sem financiamento)"]
    else:
        alertas_extra = []
    alertas = [msg for padrao, msg in RISCOS if re.search(padrao, baixo, re.I | re.S)] + alertas_extra
    if ocupado == "sim":
        alertas.insert(0, "Imóvel ocupado")
    acoes = "; ".join(m.group(0)[:160] for m in re.finditer(
        r"(\bA[çc][aã]o de [^.;]{5,140}|\bPenhora[^.;]{0,120}|\bprocesso n[ºo°][^.;]{5,80})", obs, re.I))
    resumo = " ".join(x for x in [
        "Ocupado." if ocupado == "sim" else "Desocupado." if ocupado == "nao" else "",
        f"Pagamento: {re.sub(chr(10), ' ', pag)[:220].rstrip(' .')}." if pag else "",
        f"Matrícula {re.sub(chr(10), ' ', matr)[:80].rstrip(' .')}." if matr else ""] if x)
    return {"ocupado": ocupado, "aceita_financiamento": financ, "acoes_judiciais": acoes or None,
            "alertas": alertas, "resumo": resumo or None, "descricao_completa": descr[:600],
            "observacoes": obs[:1500]}


def detalhar(limite: int = 80, max_dias: int = 7):
    """Lê a página dos imóveis do Zuk que estão nos filtros e ainda não foram lidos (ou faz > max_dias)."""
    import json
    from .alerta import bate, carregar_filtros
    from .db import conectar
    cfg = carregar_filtros()
    con = conectar()
    lidos = {r["imovel_id"]: r["analisado_em"] for r in con.execute("SELECT imovel_id, analisado_em FROM edital")}
    corte = (datetime.now().timestamp() - max_dias * 86400)
    pend = []
    for im in con.execute("SELECT * FROM imovel WHERE fonte='zuk' AND ativo=1 ORDER BY primeira_vez DESC"):
        im = dict(im)
        if not any(bate(im, f) for f in cfg["filtros"]):
            continue
        quando = lidos.get(im["id"])
        if quando and datetime.fromisoformat(quando).timestamp() > corte:
            continue
        pend.append(im)
    s, feitos = _Sessao(), 0
    for im in pend[:limite]:
        try:
            d = parse_detalhe(s.get(im["link"]))
        except Exception as exc:
            print(f"Zuk detalhe {im['id']}: {exc}")
            continue
        con.execute(
            """INSERT OR REPLACE INTO edital (imovel_id, ocupado, aceita_financiamento, acoes_judiciais, alertas,
                   resumo, analisado_em) VALUES (?,?,?,?,?,?,datetime('now'))""",
            (im["id"], d["ocupado"], d["aceita_financiamento"], d["acoes_judiciais"],
             json.dumps(d["alertas"], ensure_ascii=False), d["resumo"]))
        if d["aceita_financiamento"] is not None:
            con.execute("UPDATE imovel SET financiamento=? WHERE id=?",
                        ("Sim" if d["aceita_financiamento"] else "Não", im["id"]))
        con.commit()
        feitos += 1
    msg = f"Zuk detalhes: {feitos} páginas lidas ({max(0, len(pend) - limite)} ficam para a próxima)"
    print(msg)
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::notice title=Detalhes Zuk::{msg}")
