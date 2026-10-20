"""Coleta a lista pública de imóveis da Caixa (um CSV por UF) e grava no banco.

Formato do arquivo: latin-1, separador ';', algumas linhas de cabeçalho antes
da linha de colunas (que começa com 'N° do imóvel'). As colunas podem mudar,
então o parser localiza cada uma pelo nome.
"""
import csv
import os
import io
import re
import urllib.request

from .db import conectar

URL = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{uf}.csv"
UFS = ("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO").split()

# nome normalizado da coluna -> campo no banco
COLUNAS = {
    "n do imovel": "codigo", "no do imovel": "codigo", "numero do imovel": "codigo",
    "uf": "uf", "cidade": "cidade", "bairro": "bairro", "endereco": "endereco",
    "preco": "preco", "valor de avaliacao": "valor_avaliacao", "desconto": "desconto",
    "descricao": "descricao", "modalidade de venda": "modalidade", "link de acesso": "link",
    "financiamento": "financiamento",
}


def _norm(txt: str) -> str:
    import unicodedata
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", txt.lower()).strip()


def _num(txt: str):
    """'1.234.567,89' -> 1234567.89"""
    txt = (txt or "").strip().replace("R$", "").replace("%", "").strip()
    if not txt:
        return None
    try:
        if "," in txt:  # formato BR: 1.234.567,89
            return float(txt.replace(".", "").replace(",", "."))
        return float(txt)  # ponto decimal: 68.23
    except ValueError:
        return None


def _area(txt: str):
    """Área na descrição vem como '62.00' (ponto decimal) ou '1.234,50' (formato BR)."""
    if "," in txt:
        return _num(txt)
    try:
        v = float(txt)
    except ValueError:
        return None
    return v or None


def _detalhes(descricao: str) -> dict:
    """Extrai tipo, áreas, quartos e vagas do texto livre de descrição da Caixa.

    Ex.: 'Casa, 90.02 de área total, 56.25 de área privativa, 134.46 de área do terreno,
          2 qto(s), a.serv, WC, 1 sala(s), cozinha, 1 vaga(s) de garagem.'
    """
    d = descricao or ""
    def area(nome):
        m = re.search(r"([\d.,]+)\s*(?:m[²2])?\s*de\s*.rea\s*" + nome, d, re.I)
        return _area(m.group(1)) if m else None
    def inteiro(padrao):
        m = re.search(padrao, d, re.I)
        return int(m.group(1)) if m else None
    vagas = inteiro(r"(\d+)\s*vaga")
    return {
        "tipo": d.split(",")[0].strip() if d else None,
        "area_total": area("total"),
        "area_privativa": area("privativa"),
        "area_terreno": area("do\\s*terreno"),
        "quartos": inteiro(r"(\d+)\s*qto"),
        # sem menção a vaga numa descrição detalhada = sem vaga
        "vagas": vagas if vagas is not None else (0 if "qto" in d.lower() else None),
    }


def parse_csv(conteudo: bytes) -> list[dict]:
    texto = conteudo.decode("latin-1")
    linhas = texto.splitlines()
    inicio = next(i for i, l in enumerate(linhas) if "bairro" in _norm(l) and "cidade" in _norm(l))
    leitor = csv.reader(io.StringIO("\n".join(linhas[inicio:])), delimiter=";")
    cab = [COLUNAS.get(_norm(c)) for c in next(leitor)]
    imoveis = []
    for row in leitor:
        if not any(c.strip() for c in row):
            continue
        reg = {campo: (row[i].strip() if i < len(row) else "") for i, campo in enumerate(cab) if campo}
        if not reg.get("codigo"):
            continue
        for campo in ("preco", "valor_avaliacao", "desconto"):
            reg[campo] = _num(reg.get(campo))
        reg.update(_detalhes(reg.get("descricao")))
        imoveis.append(reg)
    return imoveis


BASE = "https://venda-imoveis.caixa.gov.br"
from pathlib import Path as _Path
ENTRADA = _Path(__file__).resolve().parent.parent / "entrada"
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/csv,application/octet-stream,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


class RespostaInvalida(Exception):
    """A Caixa respondeu, mas não com o CSV (bloqueio, manutenção, página de verificação)."""


def _abrir_sessao():
    """Visita a página de download antes, como um navegador, para receber os cookies."""
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = list(CABECALHOS.items())
    try:
        opener.open(BASE + "/sistema/download-lista.asp", timeout=60).read()
    except Exception as exc:  # segue mesmo assim; o diagnóstico abaixo mostra o resultado
        print(f"Aviso: página de download não abriu ({exc})")
    return opener


_SESSAO = None


def baixar(uf: str) -> bytes:
    global _SESSAO
    _SESSAO = _SESSAO or _abrir_sessao()
    req = urllib.request.Request(URL.format(uf=uf), headers={"Referer": BASE + "/sistema/download-lista.asp"})
    with _SESSAO.open(req, timeout=120) as r:
        conteudo, tipo, status = r.read(), r.headers.get("Content-Type", ""), r.status
    print(f"{uf}: HTTP {status} · {tipo or 'sem content-type'} · {len(conteudo):,} bytes")
    return conteudo


def _diagnostico(uf: str, conteudo: bytes):
    from pathlib import Path
    pasta = Path(__file__).resolve().parent.parent / "diagnostico"
    pasta.mkdir(exist_ok=True)
    (pasta / f"resposta_{uf}.bin").write_bytes(conteudo)
    trecho = conteudo[:600].decode("latin-1", "replace").replace("\n", " ")
    return f"{uf}: resposta não é o CSV da Caixa. Início do conteúdo: {trecho!r}"


def gravar(imoveis: list[dict], fonte: str = "caixa", uf: str | None = None) -> dict:
    """Upsert. Devolve contagem de novos, preço alterado e removidos."""
    con = conectar()
    novos, alterados, anterior = [], [], {}
    vistos = set()
    for im in imoveis:
        iid = f"{fonte}:{im['codigo']}"
        vistos.add(iid)
        atual = con.execute("SELECT preco FROM imovel WHERE id=?", (iid,)).fetchone()
        if atual is None:
            novos.append(iid)
        elif atual["preco"] != im["preco"]:
            alterados.append(iid)
            anterior[iid] = atual["preco"]
        con.execute(
            """INSERT INTO imovel (id, fonte, codigo, uf, cidade, bairro, endereco, preco, valor_avaliacao,
                   desconto, descricao, tipo, area_privativa, area_total, area_terreno, quartos, vagas,
                   modalidade, link, financiamento)
               VALUES (:id,:fonte,:codigo,:uf,:cidade,:bairro,:endereco,:preco,:valor_avaliacao,
                   :desconto,:descricao,:tipo,:area_privativa,:area_total,:area_terreno,:quartos,:vagas,
                   :modalidade,:link,:financiamento)
               ON CONFLICT(id) DO UPDATE SET preco=excluded.preco, desconto=excluded.desconto,
                   valor_avaliacao=excluded.valor_avaliacao, modalidade=excluded.modalidade,
                   link=excluded.link, financiamento=excluded.financiamento, descricao=excluded.descricao,
                   tipo=excluded.tipo, area_privativa=excluded.area_privativa, area_total=excluded.area_total,
                   area_terreno=excluded.area_terreno, quartos=excluded.quartos, vagas=excluded.vagas, ativo=1, ultima_vez=datetime('now')""",
            {**{k: im.get(k) for k in COLUNAS.values()}, "id": iid, "fonte": fonte,
             **{k: im.get(k) for k in ("tipo", "area_privativa", "area_total", "area_terreno", "quartos", "vagas")}},
        )
        if atual is None or atual["preco"] != im["preco"]:
            con.execute("INSERT INTO historico_preco (imovel_id, preco) VALUES (?,?)", (iid, im["preco"]))
    removidos = 0
    if uf:  # o que sumiu da lista desta UF foi vendido/retirado
        cur = con.execute("SELECT id FROM imovel WHERE fonte=? AND uf=? AND ativo=1", (fonte, uf))
        sumidos = [r["id"] for r in cur if r["id"] not in vistos]
        con.executemany("UPDATE imovel SET ativo=0 WHERE id=?", [(s,) for s in sumidos])
        removidos = len(sumidos)
    con.commit()
    return {"total": len(imoveis), "novos": novos, "preco_alterado": alterados,
            "preco_anterior": anterior, "removidos": removidos}


def coletar(ufs=("SP",), arquivo: str | None = None) -> dict:
    resultado, falhas = {}, []
    for uf in ufs:
        try:
            enviado = ENTRADA / f"Lista_imoveis_{uf}.csv"
            if arquivo:
                conteudo = open(arquivo, "rb").read()
            elif enviado.exists():  # lista baixada pelo celular/computador e enviada ao repositório
                conteudo = enviado.read_bytes()
                print(f"{uf}: usando lista enviada ({enviado.name}, {len(conteudo):,} bytes)")
            else:
                conteudo = baixar(uf)
            try:
                imoveis = parse_csv(conteudo)
            except StopIteration:
                raise RespostaInvalida(_diagnostico(uf, conteudo))
            resultado[uf] = gravar(imoveis, uf=uf)
        except Exception as exc:  # uma UF com problema não derruba as outras
            print(f"ERRO {uf}: {exc}")
            if os.getenv("GITHUB_ACTIONS"):  # vira anotação visível na página da execução
                msg = str(exc).replace("%", "%25").replace("\r", " ").replace("\n", " ")[:900]
                print(f"::warning title=Coleta {uf}::{msg}")
            falhas.append(uf)
    if falhas and not resultado:
        raise RespostaInvalida(f"Nenhuma UF coletada ({', '.join(falhas)}). Veja as mensagens acima.")
    return resultado
