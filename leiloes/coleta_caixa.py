"""Coleta a lista pública de imóveis da Caixa (um CSV por UF) e grava no banco.

Formato do arquivo: latin-1, separador ';', algumas linhas de cabeçalho antes
da linha de colunas (que começa com 'N° do imóvel'). As colunas podem mudar,
então o parser localiza cada uma pelo nome.
"""
import csv
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
        return float(txt.replace(".", "").replace(",", "."))
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
    """Extrai tipo, área privativa e quartos do texto livre de descrição."""
    d = descricao or ""
    tipo = d.split(",")[0].strip() if d else None
    area = re.search(r"([\d.,]+)\s*(?:m[²2])?\s*de\s*.rea\s*privativa", d, re.I)
    quartos = re.search(r"(\d+)\s*qto", d, re.I)
    return {
        "tipo": tipo,
        "area_privativa": _area(area.group(1)) if area else None,
        "quartos": int(quartos.group(1)) if quartos else None,
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


def baixar(uf: str) -> bytes:
    req = urllib.request.Request(URL.format(uf=uf), headers={"User-Agent": "Mozilla/5.0 (mapa-leiloes pessoal)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


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
                   desconto, descricao, tipo, area_privativa, quartos, modalidade, link)
               VALUES (:id,:fonte,:codigo,:uf,:cidade,:bairro,:endereco,:preco,:valor_avaliacao,
                   :desconto,:descricao,:tipo,:area_privativa,:quartos,:modalidade,:link)
               ON CONFLICT(id) DO UPDATE SET preco=excluded.preco, desconto=excluded.desconto,
                   valor_avaliacao=excluded.valor_avaliacao, modalidade=excluded.modalidade,
                   link=excluded.link, ativo=1, ultima_vez=datetime('now')""",
            {**{k: im.get(k) for k in COLUNAS.values()}, "id": iid, "fonte": fonte,
             "tipo": im.get("tipo"), "area_privativa": im.get("area_privativa"), "quartos": im.get("quartos")},
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
    resultado = {}
    for uf in ufs:
        conteudo = open(arquivo, "rb").read() if arquivo else baixar(uf)
        imoveis = parse_csv(conteudo)
        resultado[uf] = gravar(imoveis, uf=uf)
    return resultado
