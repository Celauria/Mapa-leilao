"""Referência de mercado para a cidade de São Paulo com as guias de ITBI pagas.

A Secretaria da Fazenda publica um Excel por ano com cada transação (rua, número,
bairro, valor declarado, data, área construída, uso do IPTU). Daqui sai a mediana
de R$/m² das compras e vendas por rua e por bairro, separada por tipo de imóvel,
nos últimos 12 meses. O resultado (pequeno) fica em data/mercado_sp.json e é
recalculado no máximo uma vez por mês, quando a prefeitura publica o mês novo.

Fonte: https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501
"""
import json
import re
import statistics
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PAGINA = "https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501"
SAIDA = Path(__file__).resolve().parent.parent / "data" / "mercado_sp.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MIN_AMOSTRA = 3
TIPOS_LOGRADOURO = {"R", "RUA", "AV", "AVENIDA", "AL", "ALAMEDA", "TV", "TRAVESSA", "PC", "PCA", "PRACA", "EST",
                    "ESTRADA", "ROD", "RODOVIA", "LGO", "LARGO", "VL", "VIELA", "VD", "VIADUTO", "PQ", "PARQUE",
                    "PSG", "PASSAGEM", "VIA", "BC", "BECO", "LD", "LADEIRA", "PRQ", "JD", "JARDIM", "ESTR", "TR"}


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", t)).strip()


def rua(endereco: str) -> str:
    """'RUA PEDROSO ALVARENGA, N. 1254 APTO 5' e 'R PEDROSO ALVARENGA' -> 'PEDROSO ALVARENGA'."""
    base = re.split(r",|\s+N[º°o]?\.?\s*\d|\s+S/N|\s+-\s", str(endereco or ""), maxsplit=1)[0]
    partes = _norm(base).split()
    while partes and partes[0] in TIPOS_LOGRADOURO:
        partes = partes[1:]
    while partes and partes[0] in ("DO", "DA", "DOS", "DAS", "DE"):
        partes = partes[1:]
    while len(partes) > 1 and partes[-1].isdigit():  # número colado no fim ("RUA X 299")
        partes = partes[:-1]
    return " ".join(partes)


def categoria(descricao_uso: str = "", tipo_caixa: str = "") -> str | None:
    t = _norm(descricao_uso or tipo_caixa)
    if "APARTAMENTO" in t:
        return "apto"
    if "RESIDENCIA" in t or t.startswith("CASA") or "SOBRADO" in t:
        return "casa"
    return None


def _links_xlsx() -> list[str]:
    req = urllib.request.Request(PAGINA, headers={"User-Agent": UA, "Accept-Language": "pt-BR"})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    links = re.findall(r'href="([^"]+\.xlsx)"', html, re.I)
    links = [l for l in links if "itbi" in l.lower()]
    vistos = []
    for l in links:  # a página lista do ano mais recente para o mais antigo
        if l not in vistos:
            vistos.append(l)
    return [urllib.parse.urljoin(PAGINA, l.replace(" ", "%20")) for l in vistos[:2]]


def _baixar(url: str, destino: Path):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "pt-BR", "Referer": PAGINA,
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"})
    with urllib.request.urlopen(req, timeout=600) as r, open(destino, "wb") as f:
        while bloco := r.read(1 << 20):
            f.write(bloco)
    time.sleep(2)


def _linhas(xlsx: Path):
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        cab = next(it, None)
        if not cab or "Valor de Transação" not in " ".join(str(c) for c in cab if c):
            continue  # abas de legenda/explicações
        idx = {_norm(c): i for i, c in enumerate(cab) if c}
        col = lambda nome: next((i for k, i in idx.items() if k.startswith(_norm(nome))), None)
        c = {k: col(v) for k, v in {
            "rua": "Nome do Logradouro", "bairro": "Bairro", "natureza": "Natureza de Transação",
            "valor": "Valor de Transação", "data": "Data de Transação", "area": "Área Construída",
            "uso": "Descrição do uso", "prop": "Proporção Transmitida"}.items()}
        for row in it:
            yield {k: (row[i] if i is not None and i < len(row) else None) for k, i in c.items()}


def calcular(arquivos: list[Path], meses: int = 12) -> dict:
    corte = datetime.now() - timedelta(days=30 * meses)
    grupos: dict[str, list[float]] = {}
    total = usadas = 0
    for arq in arquivos:
        for r in _linhas(arq):
            total += 1
            if not str(r["natureza"] or "").startswith("1."):  # só compra e venda
                continue
            data = r["data"]
            if isinstance(data, str):
                try:
                    data = datetime.fromisoformat(data[:10])
                except ValueError:
                    continue
            if not isinstance(data, datetime) or data < corte:
                continue
            try:
                valor, area = float(r["valor"]), float(r["area"])
                prop = float(r["prop"] or 100)
            except (TypeError, ValueError):
                continue
            if prop < 99 or area < 15 or valor < 20000:  # só transmissão integral e unidades plausíveis
                continue
            cat = categoria(r["uso"])
            if not cat:
                continue
            m2 = valor / area
            if not 800 <= m2 <= 60000:
                continue
            usadas += 1
            for chave in (f"rua|{rua(r['rua'])}|{cat}", f"bairro|{_norm(r['bairro'])}|{cat}"):
                grupos.setdefault(chave, []).append(m2)
    tabela = {k: [round(statistics.median(v)), len(v)] for k, v in grupos.items() if len(v) >= MIN_AMOSTRA}
    print(f"ITBI SP: {total:,} linhas, {usadas:,} compras e vendas usadas, {len(tabela):,} referências")
    return tabela


def atualizar(max_dias: int = 30, forcar: bool = False) -> bool:
    """Baixa e recalcula se o arquivo local tiver mais de max_dias. Devolve True se atualizou."""
    if SAIDA.exists() and not forcar:
        idade = (datetime.now() - datetime.fromisoformat(json.loads(SAIDA.read_text())["gerado"])).days
        if idade < max_dias:
            print(f"ITBI SP: referência de {idade} dia(s), sem necessidade de atualizar")
            return False
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        arquivos = []
        for i, url in enumerate(_links_xlsx()):
            destino = Path(tmp) / f"itbi_{i}.xlsx"
            _baixar(url, destino)
            print(f"ITBI SP: baixado {url.rsplit('/', 1)[-1]} ({destino.stat().st_size / 1e6:.0f} MB)")
            arquivos.append(destino)
        tabela = calcular(arquivos)
    if len(tabela) < 100:
        raise RuntimeError(f"ITBI SP: só {len(tabela)} referências — formato do arquivo pode ter mudado")
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(json.dumps({"gerado": datetime.now().isoformat(timespec="seconds"),
                                 "fonte": PAGINA, "tabela": tabela}, ensure_ascii=False, separators=(",", ":")))
    return True


_CACHE = None


def referencia(im: dict):
    """(R$/m² de referência, nº de vendas, nível 'rua'|'bairro') para um imóvel da capital, ou None."""
    global _CACHE
    if _norm(im.get("cidade")) != "SAO PAULO" or im.get("uf") != "SP":
        return None
    if _CACHE is None:
        _CACHE = json.loads(SAIDA.read_text())["tabela"] if SAIDA.exists() else {}
    cat = categoria(tipo_caixa=im.get("tipo"))
    if not cat:
        return None
    for nivel, chave in (("rua", rua(im.get("endereco"))), ("bairro", _norm(im.get("bairro")))):
        hit = _CACHE.get(f"{nivel}|{chave}|{cat}")
        if chave and hit:
            return hit[0], hit[1], nivel
    return None
