"""
git_push.py
===========
Faz commit do docs/index.html gerado e envia ao GitHub.
Chamado pelo agendar.py após o html_generator.py.

Pré-requisito: git instalado e repositório já clonado/configurado
no REPO_DIR abaixo. Token configurado via git credential manager
ou URL remota com token embutido.
"""

import subprocess
import logging
from pathlib import Path
from datetime import date

REPO_DIR = Path(__file__).parent   # raiz do repositório git
HTML_REL = "docs/index.html"       # caminho relativo ao repo

log = logging.getLogger("git_push")


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout + r.stderr).strip()
    return r.returncode, out


def push():
    hoje = date.today().strftime("%d/%m/%Y")
    html = REPO_DIR / HTML_REL

    if not html.exists():
        log.error(f"HTML não encontrado: {html}")
        return False

    log.info("Verificando alterações no git...")

    # Status — há algo para commitar?
    code, out = run(["git", "status", "--porcelain", HTML_REL], REPO_DIR)
    if not out.strip():
        log.info("Nenhuma alteração no HTML — push ignorado.")
        return True

    log.info("Adicionando arquivo...")
    code, out = run(["git", "add", HTML_REL], REPO_DIR)
    if code != 0:
        log.error(f"git add falhou: {out}")
        return False

    log.info("Fazendo commit...")
    msg = f"Dashboard {hoje} — atualização automática"
    code, out = run(["git", "commit", "-m", msg], REPO_DIR)
    if code != 0:
        log.error(f"git commit falhou: {out}")
        return False
    log.info(f"  {out[:120]}")

    log.info("Enviando para o GitHub (git push)...")
    code, out = run(["git", "push"], REPO_DIR)
    if code != 0:
        log.error(f"git push falhou: {out}")
        log.error("  Verifique: git remote -v  e  git credential manager")
        return False

    log.info(f"✅ Push concluído — GitHub Actions publicará em ~1 minuto")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    push()
