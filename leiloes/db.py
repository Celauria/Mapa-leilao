"""Banco SQLite: imóveis, histórico de preço, cache de geocodificação e análise de edital."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "leiloes.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS imovel (
    id            TEXT PRIMARY KEY,          -- fonte:codigo (ex.: caixa:1555512345678)
    fonte         TEXT NOT NULL,
    codigo        TEXT NOT NULL,
    uf            TEXT, cidade TEXT, bairro TEXT, endereco TEXT,
    preco         REAL, valor_avaliacao REAL, desconto REAL,
    descricao     TEXT, tipo TEXT, area_privativa REAL, quartos INTEGER,
    modalidade    TEXT, link TEXT,
    lat           REAL, lon REAL,
    ativo         INTEGER DEFAULT 1,
    primeira_vez  TEXT DEFAULT (datetime('now')),
    ultima_vez    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_imovel_local ON imovel(uf, cidade, bairro);

CREATE TABLE IF NOT EXISTS historico_preco (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imovel_id TEXT, data TEXT DEFAULT (datetime('now')), preco REAL
);
CREATE INDEX IF NOT EXISTS ix_hist ON historico_preco(imovel_id);

CREATE TABLE IF NOT EXISTS geocache (
    consulta TEXT PRIMARY KEY, lat REAL, lon REAL, precisao TEXT
);

CREATE TABLE IF NOT EXISTS edital (
    imovel_id      TEXT PRIMARY KEY,
    ocupado        TEXT,      -- sim / nao / desconhecido
    debitos_iptu   TEXT,      -- quem paga
    debitos_cond   TEXT,
    data_1a_praca  TEXT, data_2a_praca TEXT,
    lance_minimo   REAL,
    aceita_financiamento INTEGER, aceita_fgts INTEGER,
    comissao_leiloeiro REAL,
    acoes_judiciais TEXT,
    alertas        TEXT,      -- JSON: lista de riscos
    resumo         TEXT,
    analisado_em   TEXT DEFAULT (datetime('now'))
);
"""


def conectar(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
