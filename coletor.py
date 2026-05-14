"""
coletor.py
==========
Puxa TODAS as licitações de MG da API do PNCP e salva no SQLite.
Sem filtro de texto — coleta bruta, paginada.
Executa uma vez por dia (agendado pelo agendar.py).

Estratégia:
  - Busca por modalidade (Pregão, Dispensa, Concorrência)
  - Período: últimos N dias (padrão 3 — pega só o novo em execuções diárias)
  - Primeira execução: use DIAS_RETROATIVOS = 3    # dias retroativos por execução (mude para 90 na 1ª vez)
  - Deduplicação por numeroControlePNCP (chave primária)
  - Marca cada registro com data_coleta para rastrear novidades
"""

import requests
import sqlite3
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH          = Path(r"C:\Users\User\Desktop\Agente de Licitações\licitacoes_mg.db")
BASE_URL         = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
DIAS_RETROATIVOS = 3       # mude para 90 na primeira execução
TAMANHO_PAG      = 50
DELAY_REQ        = 2.0     # segundos entre páginas
MAX_RETRIES      = 3

MODALIDADES = {
    5: "Pregão",
    6: "Dispensa",
    4: "Concorrência",
}

# Janela máxima por modalidade (dias) — evita timeout em modalidades de alto volume
JANELA_MAX: dict[int, int] = {
    5: 90,   # Pregão       — ~21 págs/90 dias, sem problema
    6: 7,    # Dispensa     — ~1876 págs/90 dias → divide em janelas de 7 dias (~130 págs)
    4: 90,   # Concorrência — ~354 págs/90 dias, aceitável
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("coletor")


# ── Banco ─────────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS licitacoes (
        numero_controle     TEXT PRIMARY KEY,
        ano_compra          INTEGER,
        numero_compra       TEXT,
        objeto              TEXT,
        valor_estimado      REAL,
        valor_homologado    REAL,
        modalidade_id       INTEGER,
        modalidade_nome     TEXT,
        situacao_id         INTEGER,
        situacao_nome       TEXT,
        srp                 INTEGER,
        data_publicacao     TEXT,
        data_abertura       TEXT,
        data_encerramento   TEXT,
        data_atualizacao    TEXT,
        orgao_cnpj          TEXT,
        orgao_nome          TEXT,
        uf_sigla            TEXT,
        municipio_nome      TEXT,
        municipio_ibge      TEXT,
        unidade_nome        TEXT,
        processo            TEXT,
        link_pncp           TEXT,
        data_coleta         TEXT    -- quando foi inserido no banco
    );

    CREATE TABLE IF NOT EXISTS coletas (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        iniciada_em     TEXT,
        concluida_em    TEXT,
        registros_novos INTEGER,
        registros_total INTEGER,
        modalidades     TEXT,
        periodo_ini     TEXT,
        periodo_fim     TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_municipio ON licitacoes(municipio_ibge);
    CREATE INDEX IF NOT EXISTS idx_data_pub  ON licitacoes(data_publicacao);
    CREATE INDEX IF NOT EXISTS idx_data_col  ON licitacoes(data_coleta);
    """)
    conn.commit()


# ── Coleta ────────────────────────────────────────────────────────────────────

def fetch_pagina(params: dict) -> tuple[list, int]:
    """Retorna (itens, total_paginas). Retry manual em 429/timeout."""
    for tentativa in range(MAX_RETRIES):
        try:
            time.sleep(DELAY_REQ * (tentativa + 1))
            r = requests.get(
                BASE_URL, params=params, timeout=40,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 429:
                espera = 30 * (tentativa + 1)
                log.warning(f"Rate limit (429) — aguardando {espera}s...")
                time.sleep(espera)
                continue
            if r.status_code != 200:
                log.warning(f"HTTP {r.status_code} — pulando")
                return [], 0
            data = r.json()
            return data.get("data", []), data.get("totalPaginas", 1)
        except requests.exceptions.Timeout:
            log.warning(f"Timeout (tentativa {tentativa+1}/{MAX_RETRIES})")
            time.sleep(10 * (tentativa + 1))
        except Exception as e:
            log.error(f"Erro inesperado: {e}")
            break
    return [], 0


def parse_item(item: dict, data_coleta: str) -> dict:
    uo = item.get("unidadeOrgao", {}) or {}
    oe = item.get("orgaoEntidade", {}) or {}
    num = str(item.get("numeroControlePNCP", ""))
    return {
        "numero_controle"  : num,
        "ano_compra"       : item.get("anoCompra"),
        "numero_compra"    : item.get("numeroCompra", ""),
        "objeto"           : (item.get("objetoCompra", "") or "").strip(),
        "valor_estimado"   : item.get("valorTotalEstimado"),
        "valor_homologado" : item.get("valorTotalHomologado"),
        "modalidade_id"    : item.get("modalidadeId"),
        "modalidade_nome"  : item.get("modalidadeNome", ""),
        "situacao_id"      : item.get("situacaoCompraId"),
        "situacao_nome"    : item.get("situacaoCompraNome", ""),
        "srp"              : 1 if item.get("srp") else 0,
        "data_publicacao"  : item.get("dataPublicacaoPncp", ""),
        "data_abertura"    : item.get("dataAberturaProposta", ""),
        "data_encerramento": item.get("dataEncerramentoProposta", ""),
        "data_atualizacao" : item.get("dataAtualizacao", ""),
        "orgao_cnpj"       : oe.get("cnpj", ""),
        "orgao_nome"       : oe.get("razaoSocial", ""),
        "uf_sigla"         : uo.get("ufSigla", ""),
        "municipio_nome"   : uo.get("municipioNome", ""),
        "municipio_ibge"   : str(uo.get("codigoIbge", "")),
        "unidade_nome"     : uo.get("nomeUnidade", ""),
        "processo"         : item.get("processo", ""),
        "link_pncp"        : "https://pncp.gov.br/app/editais/" + num,
        "data_coleta"      : data_coleta,
    }


def inserir(conn: sqlite3.Connection, registros: list[dict]) -> int:
    """Insere ignorando duplicatas. Retorna quantos eram novos."""
    sql = """
    INSERT OR IGNORE INTO licitacoes (
        numero_controle, ano_compra, numero_compra, objeto,
        valor_estimado, valor_homologado, modalidade_id, modalidade_nome,
        situacao_id, situacao_nome, srp,
        data_publicacao, data_abertura, data_encerramento, data_atualizacao,
        orgao_cnpj, orgao_nome, uf_sigla, municipio_nome, municipio_ibge,
        unidade_nome, processo, link_pncp, data_coleta
    ) VALUES (
        :numero_controle, :ano_compra, :numero_compra, :objeto,
        :valor_estimado, :valor_homologado, :modalidade_id, :modalidade_nome,
        :situacao_id, :situacao_nome, :srp,
        :data_publicacao, :data_abertura, :data_encerramento, :data_atualizacao,
        :orgao_cnpj, :orgao_nome, :uf_sigla, :municipio_nome, :municipio_ibge,
        :unidade_nome, :processo, :link_pncp, :data_coleta
    )
    """
    antes = conn.execute("SELECT COUNT(*) FROM licitacoes").fetchone()[0]
    conn.executemany(sql, registros)
    conn.commit()
    depois = conn.execute("SELECT COUNT(*) FROM licitacoes").fetchone()[0]
    return depois - antes


# ── Main ──────────────────────────────────────────────────────────────────────

def checar_api() -> bool:
    """Verifica se a API está respondendo antes de iniciar a coleta."""
    try:
        r = requests.get(BASE_URL, params={
            "dataInicial": "20260101", "dataFinal": "20260101",
            "codigoModalidadeContratacao": 5,
            "pagina": 1, "tamanhoPagina": 10,
        }, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code in (200, 204):
            log.info("✅ API OK — iniciando coleta")
            return True
        log.error(f"❌ API indisponível — HTTP {r.status_code}. Tente mais tarde.")
        return False
    except Exception as e:
        log.error(f"❌ API sem resposta — {type(e).__name__}. Tente mais tarde.")
        return False


def coletar():
    fim = datetime.now()
    ini = fim - timedelta(days=DIAS_RETROATIVOS)
    data_coleta = datetime.now().isoformat(timespec="seconds")

    log.info(f"Iniciando coleta | período: {ini:%d/%m/%Y} → {fim:%d/%m/%Y}")
    log.info(f"Banco: {DB_PATH}")

    if not checar_api():
        return 0

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total_novos = 0
    inicio_coleta = datetime.now().isoformat(timespec="seconds")

    for cod_mod, nome_mod in MODALIDADES.items():
        log.info(f"── Modalidade: {nome_mod} ──")

        # Divide em sub-janelas para modalidades de alto volume
        janela = JANELA_MAX[cod_mod]
        sub_periodos = []
        cursor = ini
        while cursor < fim:
            sub_fim = min(cursor + timedelta(days=janela - 1), fim)
            sub_periodos.append((cursor, sub_fim))
            cursor = sub_fim + timedelta(days=1)

        for sub_ini, sub_fim in sub_periodos:
            if len(sub_periodos) > 1:
                log.info(f"  janela: {sub_ini:%d/%m} → {sub_fim:%d/%m}")
            pagina = 1

            while True:
                params = {
                    "dataInicial": sub_ini.strftime("%Y%m%d"),
                    "dataFinal":   sub_fim.strftime("%Y%m%d"),
                    "uf": "MG",
                "codigoModalidadeContratacao": cod_mod,
                "pagina": pagina,
                "tamanhoPagina": TAMANHO_PAG,
                # SEM parâmetro "texto" — pega tudo
            }

                itens, total_pags = fetch_pagina(params)

                if not itens:
                    break

                # API já filtra MG — validação extra por segurança
                mg = [i for i in itens
                      if (i.get("unidadeOrgao", {}) or {}).get("ufSigla", "").upper() == "MG"]

                registros = [parse_item(i, data_coleta) for i in mg]
                novos = inserir(conn, registros)
                total_novos += novos

                log.info(f"  pág {pagina:>3}/{total_pags} | "
                         f"{len(mg):>3} MG | {novos:>3} novos")

                if pagina >= total_pags:
                    break
                pagina += 1

    # Registra coleta
    total_banco = conn.execute("SELECT COUNT(*) FROM licitacoes").fetchone()[0]
    conn.execute("""
        INSERT INTO coletas (iniciada_em, concluida_em, registros_novos,
                             registros_total, modalidades, periodo_ini, periodo_fim)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (inicio_coleta, datetime.now().isoformat(timespec="seconds"),
          total_novos, total_banco,
          ",".join(MODALIDADES.values()),
          ini.strftime("%Y-%m-%d"), fim.strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()

    log.info(f"Coleta concluída | {total_novos} novos | {total_banco} total no banco")
    return total_novos


if __name__ == "__main__":
    coletar()