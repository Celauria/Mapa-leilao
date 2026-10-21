"""Coletor que roda no computador do usuário (Windows, Mac ou Linux).

A Caixa bloqueia os servidores do GitHub, mas não uma conexão residencial. Este
script baixa as listas da Caixa das UFs de filtros.json, confere se são mesmo o
CSV, grava em entrada/ e envia ao GitHub. O push dispara o workflow, que faz o
resto (bancos, geocodificação, mercado, mapa).

Roda no máximo uma vez por dia (use --forcar para repetir). Primeiro tenta um
download direto; se vier a página anti-robô, usa o Microsoft Edge (ou Chrome) do
próprio computador em segundo plano, via Playwright.

  python -m leiloes.coletor_local            # coleta (se ainda não coletou hoje) e envia
  python -m leiloes.coletor_local --forcar   # coleta de novo
  python -m leiloes.coletor_local --sem-enviar
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "entrada"
PASTA_LOCAL = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share") / "MapaLeiloes"
MARCA_DIA = PASTA_LOCAL / "ultima_coleta.txt"
LOG = PASTA_LOCAL / "coleta.log"
URL_LISTA = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{uf}.csv"
PAGINA = "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"


def log(msg: str):
    PASTA_LOCAL.mkdir(parents=True, exist_ok=True)
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(linha)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def eh_lista_caixa(conteudo: bytes) -> bool:
    from .coleta_caixa import parse_csv
    try:
        return len(parse_csv(conteudo)) > 0
    except Exception:
        return False


def baixar_direto(uf: str) -> bytes | None:
    from .coleta_caixa import _abrir_sessao  # sessão com cookies e cabeçalhos de navegador
    try:
        s = _abrir_sessao()
        req = urllib.request.Request(URL_LISTA.format(uf=uf), headers={"Referer": PAGINA})
        with s.open(req, timeout=120) as r:
            dados = r.read()
        return dados if eh_lista_caixa(dados) else None
    except Exception as exc:
        log(f"{uf}: download direto falhou ({type(exc).__name__}: {exc})")
        return None


def baixar_navegador(ufs: list[str]) -> dict[str, bytes]:
    """Usa o Edge/Chrome instalado (sem baixar navegador) para passar pela checagem anti-robô."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("Playwright não instalado; rode: py -m pip install --user playwright")
        return {}
    obtidos = {}
    with sync_playwright() as p:
        nav = None
        for canal in ("msedge", "chrome"):
            try:
                nav = p.chromium.launch(channel=canal, headless=True)
                break
            except Exception:
                continue
        if not nav:
            log("Nem Edge nem Chrome encontrados para o modo navegador")
            return {}
        ctx = nav.new_context(accept_downloads=True, locale="pt-BR")
        pg = ctx.new_page()
        pg.goto(PAGINA, wait_until="networkidle", timeout=90000)
        time.sleep(3)
        for uf in ufs:
            try:
                resp = ctx.request.get(URL_LISTA.format(uf=uf), headers={"Referer": PAGINA}, timeout=120000)
                dados = resp.body()
                if eh_lista_caixa(dados):
                    obtidos[uf] = dados
                else:
                    with pg.expect_download(timeout=120000) as dl:
                        pg.evaluate("u => { const a = document.createElement('a'); a.href = u; document.body.append(a); a.click(); }",
                                    URL_LISTA.format(uf=uf))
                    dados = Path(dl.value.path()).read_bytes()
                    if eh_lista_caixa(dados):
                        obtidos[uf] = dados
                time.sleep(2)
            except Exception as exc:
                log(f"{uf}: modo navegador falhou ({type(exc).__name__}: {exc})")
        nav.close()
    return obtidos


def git(*args, check=True) -> str:
    r = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def coletar(forcar=False, enviar=True) -> int:
    hoje = datetime.now().strftime("%Y-%m-%d")
    if not forcar and MARCA_DIA.exists() and MARCA_DIA.read_text().strip() == hoje:
        print("Já coletou hoje. Use --forcar para coletar de novo.")
        return 0
    if enviar:
        git("pull", "--rebase", "--autostash", "-q")
    cfg = json.loads((RAIZ / "filtros.json").read_text(encoding="utf-8"))
    ufs = sorted({f["uf"] for f in cfg["filtros"]})
    listas = {}
    for uf in ufs:
        dados = baixar_direto(uf)
        if dados:
            listas[uf] = dados
            log(f"{uf}: lista baixada direto ({len(dados):,} bytes)")
    faltam = [uf for uf in ufs if uf not in listas]
    if faltam:
        log(f"Tentando pelo navegador: {', '.join(faltam)}")
        for uf, dados in baixar_navegador(faltam).items():
            listas[uf] = dados
            log(f"{uf}: lista baixada pelo navegador ({len(dados):,} bytes)")
    if not listas:
        log("ERRO: nenhuma lista da Caixa baixada. O mapa segue com as listas anteriores.")
        return 1

    ENTRADA.mkdir(exist_ok=True)
    mudou = []
    for uf, dados in listas.items():
        destino = ENTRADA / f"Lista_imoveis_{uf}.csv"
        antigo = destino.read_bytes() if destino.exists() else b""
        if hashlib.sha256(antigo).digest() != hashlib.sha256(dados).digest():
            destino.write_bytes(dados)
            mudou.append(uf)
    if not mudou:
        log("Listas iguais às do último envio; nada a enviar.")
    elif enviar:
        git("add", "entrada")
        git("-c", "user.name=Coletor local", "-c", "user.email=coletor-local@users.noreply.github.com",
            "commit", "-q", "-m", f"Listas da Caixa {hoje} ({', '.join(mudou)}) enviadas pelo computador")
        for tentativa in range(3):
            try:
                git("push", "-q")
                break
            except RuntimeError as exc:
                log(f"push recusado ({exc}); tentando de novo")
                git("pull", "--rebase", "-q", check=False)
                time.sleep(5)
        else:
            log("ERRO: não consegui enviar ao GitHub. Confira a internet e o login do Git.")
            return 1
        log(f"Enviado ao GitHub: {', '.join(mudou)}. O mapa atualiza em alguns minutos.")
    if len(listas) == len(ufs):
        PASTA_LOCAL.mkdir(parents=True, exist_ok=True)
        MARCA_DIA.write_text(hoje)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="coletor_local")
    ap.add_argument("--forcar", action="store_true", help="coleta mesmo se já coletou hoje")
    ap.add_argument("--sem-enviar", action="store_true", help="só baixa para entrada/, sem git")
    a = ap.parse_args()
    try:
        sys.exit(coletar(forcar=a.forcar, enviar=not a.sem_enviar))
    except Exception as exc:
        log(f"ERRO inesperado: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
