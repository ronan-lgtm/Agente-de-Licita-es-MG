"""
classificador.py
================
Lê o SQLite, pontua cada licitação por relevância e grava o score
de volta no banco. Roda LOCAL — sem API, sem rede.
"""

import sqlite3
import unicodedata
import logging
from pathlib import Path
from datetime import datetime
from collections import Counter

DB_PATH = Path(r"C:\Users\User\Desktop\Agente de Licitações\licitacoes_mg.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("classificador")

TERMOS: dict[str, tuple[int, str]] = {
    # Videomonitoramento
    "videomonitoramento"           : (10, "Videomonitoramento"),
    "cftv"                         : (10, "Videomonitoramento"),
    "cftv ip"                      : (10, "Videomonitoramento"),
    "circuito fechado de televisao": (9,  "Videomonitoramento"),
    "circuito fechado"             : (8,  "Videomonitoramento"),
    "camera ip"                    : (9,  "Videomonitoramento"),
    "camera de seguranca"          : (9,  "Videomonitoramento"),
    "sistema de videomonitoramento": (10, "Videomonitoramento"),
    "monitoramento por cameras"    : (9,  "Videomonitoramento"),
    "vigilancia eletronica"        : (9,  "Videomonitoramento"),
    "sistema de vigilancia"        : (8,  "Videomonitoramento"),
    "monitoramento eletronico"     : (8,  "Videomonitoramento"),
    "monitoramento urbano"         : (8,  "Videomonitoramento"),
    "monitoramento perimetral"     : (9,  "Videomonitoramento"),
    "monitoramento de veiculos"    : (8,  "Videomonitoramento"),
    "monitoramento de trafego"     : (8,  "Videomonitoramento"),
    "monitoramento rodoviario"     : (7,  "Videomonitoramento"),
    "vigilancia urbana inteligente": (9,  "Videomonitoramento"),
    "plataforma de monitoramento"  : (8,  "Videomonitoramento"),
    "central de monitoramento"     : (9,  "Videomonitoramento"),
    "centro integrado de comando"  : (10, "Videomonitoramento"),
    "cicc"                         : (10, "Videomonitoramento"),
    "olho vivo"                    : (9,  "Videomonitoramento"),
    "sensoriamento urbano"         : (7,  "Videomonitoramento"),
    "monitoramento de eventos"     : (7,  "Videomonitoramento"),
    "contagem de pessoas"          : (8,  "Videomonitoramento"),
    "bodycam"                      : (9,  "Videomonitoramento"),
    "camera corporal"              : (9,  "Videomonitoramento"),
    "cameras corporais"            : (9,  "Videomonitoramento"),
    "softwares de monitoramento"   : (7,  "Videomonitoramento"),
    "sistemas de alarmes"          : (6,  "Videomonitoramento"),
    "sensor optico"                : (6,  "Videomonitoramento"),
    "smart city"                   : (9,  "Smart City"),
    "cidade inteligente"           : (9,  "Smart City"),
    "camera"                       : (2,  "Videomonitoramento"),
    "monitoramento"                : (2,  "Videomonitoramento"),
    "vigilancia"                   : (2,  "Videomonitoramento"),
    # Reconhecimento / LPR
    "reconhecimento facial"           : (10, "Reconhecimento / LPR"),
    "leitura de placas"               : (10, "Reconhecimento / LPR"),
    "leitura automatizada de placas"  : (10, "Reconhecimento / LPR"),
    "lpr"                             : (10, "Reconhecimento / LPR"),
    "anpr"                            : (10, "Reconhecimento / LPR"),
    "ocr veicular"                    : (9,  "Reconhecimento / LPR"),
    "ocr"                             : (7,  "Reconhecimento / LPR"),
    "cerco virtual"                   : (9,  "Reconhecimento / LPR"),
    "biometria"                       : (7,  "Reconhecimento / LPR"),
    "controle de acesso"              : (6,  "Reconhecimento / LPR"),
    # Drones / Sensoriamento
    "drone"                                : (8, "Drones / Sensoriamento"),
    # "vant" removido — falso positivo em "relevante", "observante" etc.
    "veiculo aereo nao tripulado"          : (8, "Drones / Sensoriamento"),
    "estacao meteorologica"                : (7, "Drones / Sensoriamento"),
    "estacao climatica"                    : (7, "Drones / Sensoriamento"),
    "estacao de monitoramento climatico"   : (7, "Drones / Sensoriamento"),
    "sensoriamento climatico"              : (7, "Drones / Sensoriamento"),
    "sensor meteorologico"                 : (6, "Drones / Sensoriamento"),
    # IA / Software
    "inteligencia artificial"       : (9, "IA / Software"),
    "agentes de ia"                 : (9, "IA / Software"),
    "gpt"                           : (8, "IA / Software"),
    "gemini"                        : (7, "IA / Software"),
    "chatbot"                       : (8, "IA / Software"),
    "chatbots para atendimento"     : (8, "IA / Software"),
    "fabrica de software"           : (8, "IA / Software"),
    "digitalizacao de servicos"     : (7, "IA / Software"),
    "integracao de sistemas"        : (6, "IA / Software"),
    "automacao de processos"        : (7, "IA / Software"),
    "automacao"                     : (4, "IA / Software"),
    "solucoes em nuvem"             : (7, "IA / Software"),
    "computacao em nuvem"           : (7, "IA / Software"),
    "desenvolvimento de portal"     : (6, "IA / Software"),
    # Frotas / Telemetria
    "telemetria"                  : (9,  "Frotas / Telemetria"),
    "rastreamento veicular"       : (9,  "Frotas / Telemetria"),
    "controle de frotas"          : (9,  "Frotas / Telemetria"),
    "gestao de frotas"            : (9,  "Frotas / Telemetria"),
    "gestao integrada de frotas"  : (10, "Frotas / Telemetria"),
    "monitoramento veicular"      : (7,  "Frotas / Telemetria"),
    "despacho de ocorrencias"     : (8,  "Frotas / Telemetria"),
    "gestao de ocorrencias"       : (8,  "Frotas / Telemetria"),
    "gestao de transito"          : (8,  "Frotas / Telemetria"),
    "rastreamento"                : (4,  "Frotas / Telemetria"),
    # Cybersecurity
    "firewall"                  : (9, "Cybersecurity"),
    "seguranca da informacao"   : (8, "Cybersecurity"),
    "seguranca de rede"         : (8, "Cybersecurity"),
    "ciberseguranca"            : (9, "Cybersecurity"),
    "siem"                      : (8, "Cybersecurity"),
    "utm"                       : (7, "Cybersecurity"),
    "pentest"                   : (8, "Cybersecurity"),
    "teste de vulnerabilidade"  : (8, "Cybersecurity"),
    "protecao de endpoint"      : (8, "Cybersecurity"),
    "antivirus corporativo"     : (6, "Cybersecurity"),
    "backup"                    : (4, "Cybersecurity"),
    # Infraestrutura TI
    "fibra optica"                     : (8, "Infraestrutura TI"),
    "fibra otica"                      : (8, "Infraestrutura TI"),
    "cabeamento estruturado"           : (8, "Infraestrutura TI"),
    "cabeamento de rede"               : (7, "Infraestrutura TI"),
    "implantacao de rede"              : (8, "Infraestrutura TI"),
    "implantacao de redes"             : (8, "Infraestrutura TI"),
    "rede logica"                      : (7, "Infraestrutura TI"),
    "rede de dados e voz"              : (7, "Infraestrutura TI"),
    "rede local"                       : (6, "Infraestrutura TI"),
    "rede ethernet"                    : (6, "Infraestrutura TI"),
    "rede de computadores"             : (6, "Infraestrutura TI"),
    "infraestrutura de rede"           : (7, "Infraestrutura TI"),
    "modernizacao da rede"             : (7, "Infraestrutura TI"),
    "manutencao de infraestrutura de ti": (6,"Infraestrutura TI"),
    "lancamento de cabos"              : (6, "Infraestrutura TI"),
    "fusao de fibra"                   : (7, "Infraestrutura TI"),
    # "dio" removido — falso positivo em "endereço", "fornecido", "previsto" etc.
    "distribuidor interno optico"      : (7, "Infraestrutura TI"),
    "eletrocalhas"                     : (5, "Infraestrutura TI"),
    "rack de telecomunicacoes"         : (7, "Infraestrutura TI"),
    "switches"                         : (6, "Infraestrutura TI"),
    "roteadores"                       : (6, "Infraestrutura TI"),
    "ativos de rede"                   : (7, "Infraestrutura TI"),
    "access point"                     : (7, "Infraestrutura TI"),
    "wi-fi corporativo"                : (7, "Infraestrutura TI"),
    "wifi corporativo"                 : (7, "Infraestrutura TI"),
    "wlan"                             : (6, "Infraestrutura TI"),
    "controladora wireless"            : (7, "Infraestrutura TI"),
    "servidores"                       : (5, "Infraestrutura TI"),
    "storage"                          : (6, "Infraestrutura TI"),
    "data center"                      : (8, "Infraestrutura TI"),
    "datacenter"                       : (8, "Infraestrutura TI"),
    "centro de dados"                  : (7, "Infraestrutura TI"),
    "nobreak"                          : (4, "Infraestrutura TI"),
    "links de dados"                   : (6, "Infraestrutura TI"),
    "link de internet"                 : (6, "Infraestrutura TI"),
    "link dedicado"                    : (7, "Infraestrutura TI"),
    "monitoramento de redes"           : (7, "Infraestrutura TI"),
    "voip"                             : (7, "Infraestrutura TI"),
    "voz sobre ip"                     : (7, "Infraestrutura TI"),
    "telefonia ip"                     : (7, "Infraestrutura TI"),
    "vdi"                              : (8, "Infraestrutura TI"),
    "virtual desktop"                  : (8, "Infraestrutura TI"),
    "desktop virtual"                  : (8, "Infraestrutura TI"),
    "thin client"                      : (7, "Infraestrutura TI"),
    "zero client"                      : (7, "Infraestrutura TI"),
    "hiperconvergente"                 : (8, "Infraestrutura TI"),
    "vpn"                              : (6, "Infraestrutura TI"),
    "cabeamento"                       : (2, "Infraestrutura TI"),
    "fibra"                            : (2, "Infraestrutura TI"),
    # Engenharia Elétrica
    "engenharia eletrica"       : (6, "Engenharia Elétrica"),
    "cabeamento eletrico"       : (5, "Engenharia Elétrica"),
    "cabeamento de dados"       : (5, "Engenharia Elétrica"),
    "subestacao de energia"     : (6, "Engenharia Elétrica"),
    "subestacao"                : (5, "Engenharia Elétrica"),
    "quadro eletrico"           : (4, "Engenharia Elétrica"),
    "montagem de quadros"       : (4, "Engenharia Elétrica"),
    "aterramento eletrico"      : (4, "Engenharia Elétrica"),
    "spda"                      : (5, "Engenharia Elétrica"),
    "rede de iluminacao publica": (5, "Engenharia Elétrica"),
    "iluminacao led"            : (4, "Engenharia Elétrica"),
    "luminaria"                 : (3, "Engenharia Elétrica"),
    "retrofit"                  : (4, "Engenharia Elétrica"),
}

ENTES: list[str] = [
    "guarda municipal", "secretaria de seguranca", "secretaria de transito",
    "defesa civil", "secretaria de educacao", "secretaria de saude",
    "saae", "cemig", "copasa", "sabesp", "senac", "sebrae", "senai",
    "sesi", "sesc", "senar", "sescoop", "policia civil", "policia militar",
    "bombeiros", "detran", "tribunal de justica", "ministerio publico",
]


def norm(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto).lower())
        if unicodedata.category(c) != "Mn"
    )


def pontuar(objeto: str, orgao: str) -> tuple[int, str, str]:
    obj_n = norm(objeto)
    org_n = norm(orgao)
    hits: dict[str, tuple[int, str]] = {}
    for termo, (peso, cat) in TERMOS.items():
        if norm(termo) in obj_n:
            hits[termo] = (peso, cat)
    if not hits:
        return 0, "Irrelevante", ""
    score = sum(p for p, _ in hits.values())
    bonus = 5 if any(norm(e) in org_n for e in ENTES) else 0
    score += bonus
    cat_principal = max(hits.items(), key=lambda x: x[1][0])[1][1]
    termos_enc    = ", ".join(sorted(hits.keys()))
    return score, cat_principal, termos_enc


def tier(score: int) -> str:
    if score < 3:  return "🔴 Irrelevante"
    if score < 6:  return "⭐ Baixa"
    if score < 10: return "⭐⭐ Média"
    return "⭐⭐⭐ Alta"


def ensure_columns(conn: sqlite3.Connection):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(licitacoes)")}
    for col, tipo in [
        ("score","INTEGER"), ("tier","TEXT"), ("categoria","TEXT"),
        ("termos_encontrados","TEXT"), ("classificado_em","TEXT"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE licitacoes ADD COLUMN {col} {tipo}")
    conn.commit()


def classificar(apenas_novos: bool = True):
    conn = sqlite3.connect(DB_PATH)
    ensure_columns(conn)
    # Ignora editais com data de publicação anterior a 2025 (lixo da API)
    filtro_data = "AND (data_publicacao >= '2025-01-01' OR data_publicacao IS NULL OR data_publicacao = '')"
    if apenas_novos:
        sql = f"SELECT numero_controle, objeto, orgao_nome FROM licitacoes WHERE score IS NULL {filtro_data}"
    else:
        sql = f"SELECT numero_controle, objeto, orgao_nome FROM licitacoes WHERE 1=1 {filtro_data}"
    rows = conn.execute(sql).fetchall()
    log.info(f"Classificando {len(rows)} registros...")
    agora   = datetime.now().isoformat(timespec="seconds")
    updates = []
    for num, objeto, orgao in rows:
        s, cat, termos = pontuar(objeto or "", orgao or "")
        updates.append((s, tier(s), cat, termos, agora, num))
    conn.executemany("""
        UPDATE licitacoes
        SET score=?, tier=?, categoria=?, termos_encontrados=?, classificado_em=?
        WHERE numero_controle=?
    """, updates)
    conn.commit()

    stats = conn.execute("""
        SELECT tier, COUNT(*) FROM licitacoes
        WHERE score IS NOT NULL GROUP BY tier ORDER BY MIN(score) DESC
    """).fetchall()
    log.info("Classificação concluída:")
    for t, c in stats:
        log.info(f"  {t}: {c}")

    log.info("\nTop termos (Média+Alta):")
    top = conn.execute("""
        SELECT termos_encontrados FROM licitacoes
        WHERE score >= 6 AND termos_encontrados != ''
    """).fetchall()
    contador = Counter()
    for (t,) in top:
        for termo in t.split(", "):
            if termo:
                contador[termo.strip()] += 1
    for termo, qtd in contador.most_common(12):
        log.info(f"  {termo}: {qtd}x")

    conn.close()
    return len(updates)


if __name__ == "__main__":
    import sys
    classificar(apenas_novos="--tudo" not in sys.argv)