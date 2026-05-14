"""
agendar.py  (versão com publicação automática)
==============================================
Orquestra a pipeline completa e registra no Windows Task Scheduler.

Uso:
  python agendar.py             → roda a pipeline agora
  python agendar.py --instalar  → cria tarefa agendada às 11h todo dia
  python agendar.py --status    → mostra último log e stats do banco
  python agendar.py --html      → só gera e publica o HTML (sem coletar)

Pipeline completa:
  1. coletor.py        → puxa novidades de MG da API do PNCP
  2. classificador.py  → pontua os novos registros (sem API)
  3. relatorio.py      → gera Excel do dia
  4. html_generator.py → gera docs/index.html
  5. git_push.py       → commit + push → GitHub Actions publica no Pages
"""

import subprocess
import sqlite3
import sys
import logging
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH     = Path(r"C:\Users\User\Desktop\Agente de Licitações\licitacoes_mg.db")
SCRIPTS_DIR = Path(__file__).parent.resolve()
PYTHON      = sys.executable
LOG_PATH    = Path(r"C:\Users\User\Desktop\Agente de Licitações\licitacoes_mg.log")

TAREFA_NOME   = "AgenteLicitacoesMG"
HORA_AGENDADA = "11:00"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("agendar")


# ── Pipeline ──────────────────────────────────────────────────────────────────

def rodar_script(nome: str, args: list[str] = []) -> bool:
    caminho = SCRIPTS_DIR / nome
    cmd     = [PYTHON, str(caminho)] + args
    log.info(f"▶ {nome} {' '.join(args)}")
    inicio = datetime.now()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=1800, encoding="utf-8")
        dur = (datetime.now() - inicio).seconds
        if result.stdout:
            for linha in result.stdout.strip().splitlines():
                log.info(f"   {linha}")
        if result.returncode != 0:
            log.error(f"   ❌ Erro ({result.returncode}) em {dur}s")
            if result.stderr:
                log.error(f"   {result.stderr[:500]}")
            return False
        log.info(f"   ✅ Concluído em {dur}s")
        return True
    except subprocess.TimeoutExpired:
        log.error(f"   ⏱️  Timeout após 30min")
        return False
    except Exception as e:
        log.error(f"   💥 {e}")
        return False


def pipeline(pular_coleta: bool = False):
    log.info("=" * 55)
    log.info(f"PIPELINE INICIADA — {datetime.now():%d/%m/%Y %H:%M}")
    log.info("=" * 55)

    etapas = []

    if not pular_coleta:
        etapas += [
            ("coletor.py",       []),
            ("classificador.py", []),
            ("relatorio.py",     []),
        ]

    # Sempre roda geração de HTML e publicação
    etapas += [
        ("html_generator.py", []),
        ("git_push.py",       []),
    ]

    ok = True
    for script, args in etapas:
        if not rodar_script(script, args):
            # Falha no git_push não interrompe — só avisa
            if script == "git_push.py":
                log.warning("   ⚠️  Push falhou, mas pipeline continua.")
                continue
            log.error(f"Pipeline interrompida em {script}")
            ok = False
            break

    if ok:
        log.info("✅ Pipeline concluída com sucesso")
    log.info("=" * 55)
    return ok


# ── Status ────────────────────────────────────────────────────────────────────

def status():
    if not DB_PATH.exists():
        print("⚠️  Banco ainda não existe. Rode:  python agendar.py")
        return

    conn = sqlite3.connect(DB_PATH)

    total = conn.execute("SELECT COUNT(*) FROM licitacoes").fetchone()[0]
    print(f"\n📦 Banco: {DB_PATH}")
    print(f"   Total de registros: {total:,}")

    print("\n📊 Por relevância:")
    for row in conn.execute(
        "SELECT tier, COUNT(*) FROM licitacoes WHERE score IS NOT NULL "
        "GROUP BY tier ORDER BY score DESC"
    ):
        print(f"   {row[0]}: {row[1]:,}")

    print("\n🕐 Últimas coletas:")
    for row in conn.execute(
        "SELECT iniciada_em, registros_novos, registros_total "
        "FROM coletas ORDER BY id DESC LIMIT 5"
    ):
        print(f"   {row[0][:16]}  +{row[1]:>4} novos  |  {row[2]:>6} total")

    print("\n⏰ Próximos encerramentos (Alta/Média):")
    for row in conn.execute("""
        SELECT municipio_nome, data_encerramento, objeto, score
        FROM licitacoes
        WHERE tier IN ('⭐⭐⭐ Alta','⭐⭐ Média')
          AND data_encerramento > datetime('now')
        ORDER BY data_encerramento ASC
        LIMIT 5
    """):
        print(f"   {row[1][:10]}  |  {row[0]:<22}  |  {(row[2] or '')[:50]}")

    conn.close()


# ── Agendamento Windows ───────────────────────────────────────────────────────

def instalar_tarefa():
    script = SCRIPTS_DIR / "agendar.py"
    cmd_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{datetime.now().strftime('%Y-%m-%d')}T{HORA_AGENDADA}:00</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{PYTHON}</Command>
      <Arguments>"{script}"</Arguments>
      <WorkingDirectory>{SCRIPTS_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
</Task>"""

    xml_path = SCRIPTS_DIR / "tarefa.xml"
    xml_path.write_text(cmd_xml, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", TAREFA_NOME,
         "/XML", str(xml_path), "/F"],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        print(f"✅ Tarefa '{TAREFA_NOME}' criada — roda todo dia às {HORA_AGENDADA}")
        print(f"   Para remover: schtasks /Delete /TN {TAREFA_NOME} /F")
        print(f"   Para rodar agora: schtasks /Run /TN {TAREFA_NOME}")
    else:
        print(f"❌ Erro ao criar tarefa: {result.stderr}")
        print(f"   Execute como Administrador.")

    xml_path.unlink(missing_ok=True)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--instalar" in sys.argv:
        instalar_tarefa()
    elif "--status" in sys.argv:
        status()
    elif "--html" in sys.argv:
        pipeline(pular_coleta=True)
    else:
        pipeline()
