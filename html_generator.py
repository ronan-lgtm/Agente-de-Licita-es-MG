"""
html_generator.py
=================
Lê o SQLite (já coletado e classificado) e gera o index.html
que será publicado no GitHub Pages.

Uso:
  python html_generator.py              → gera docs/index.html
  python html_generator.py --out pasta  → gera em pasta/index.html

Chamado automaticamente pelo agendar.py após a pipeline.
"""

import sqlite3
import json
import sys
import re
import unicodedata
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict

DB_PATH    = Path(r"C:\Users\User\Desktop\Agente de Licitações\licitacoes_mg.db")
DOCS_DIR   = Path(__file__).parent / "docs"   # pasta publicada pelo GitHub Pages

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("html_generator")

IBGE_ALVO: set[str] = {
    "3106200","3106705","3117876","3121605","3127701","3131307","3132404",
    "3144805","3136702","3140001","3143302","3143906","3144656","3146107",
    "3147006","3152501","3152006","3156700","3157807","3162500","3164431",
    "3168705","3170107","3118601","3118304","3117504","3119401","3109006",
    "3122306","3128600","3135050","3135209","3137601","3139409","3140654",
    "3107109","3107505","3108503","3109204","3109402","3111200","3112703",
    "3118809","3119104","3122355","3126901","3128105","3134202","3132503",
    "3137536","3141801","3142502","3142700","3144953","3145059","3149309",
    "3151206","3152105","3154804","3155504","3156908","3157203","3166105",
    "3168309","3169703","3170529","3171709","3171808","3103405","3110608",
    "3115300","3124807","3133808","3134103","3134509","3147501","3152204",
    "3155306","3157401","3147105","3104502","3111150","3116308","3122900",
    "3109204","3119500","3126109","3141900","3142700","3144102","3152303",
    "3163706","3165560","3165701","3165776","3170008",
}


def clean(s):
    """Remove caracteres de controle problemáticos para JSON."""
    if not isinstance(s, str):
        return s
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x80-\x9f]', "'", s)


def fmt_date(s):
    """ISO → dd/mm/aaaa."""
    if not s:
        return ""
    try:
        return datetime.fromisoformat(str(s)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(s)[:10]


def dias_restantes(enc_str):
    try:
        d = datetime.fromisoformat(str(enc_str)[:10]).date()
        return (d - date.today()).days
    except Exception:
        return None


def get_cod(link):
    if link and "/app/editais/" in str(link):
        return str(link).split("/app/editais/")[-1]
    return str(link or "")


def load_data():
    """Carrega licitações do banco com os mesmos critérios do relatorio.py."""
    conn = sqlite3.connect(DB_PATH)
    limite_enc = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    query = f"""
        SELECT
            tier, score, categoria, termos_encontrados,
            modalidade_nome, municipio_nome, municipio_ibge,
            objeto, valor_estimado,
            data_publicacao, data_abertura, data_encerramento,
            orgao_nome, link_pncp
        FROM licitacoes
        WHERE (
            (data_encerramento >= date('now')
             OR data_encerramento IS NULL
             OR data_encerramento = '')
            AND (score IS NULL OR score >= 2)
        )
        OR (
            data_encerramento >= '{limite_enc}'
            AND data_encerramento < date('now')
            AND score > 0
        )
        ORDER BY score DESC, data_encerramento ASC
    """
    rows = conn.execute(query).fetchall()
    conn.close()

    cols = ["tier","score","cat","termos","mod","muni","ibge","obj","val",
            "pub_raw","aber_raw","enc_raw","orgao","link"]

    hoje = date.today().strftime("%d/%m/%Y")
    data = []
    for r in rows:
        d = dict(zip(cols, r))

        # Normaliza tier
        tier = str(d["tier"] or "")
        if "Alta" in tier:
            d["tier"] = "⭐⭐⭐ Alta"
        elif "Média" in tier or "Media" in tier:
            d["tier"] = "⭐⭐ Média"
        elif "Baixa" in tier:
            d["tier"] = "⭐ Baixa"
        else:
            d["tier"] = "🔴 Irrelevante"

        d["score"]  = int(d["score"] or 0)
        d["val"]    = float(d["val"] or 0)
        d["alvo"]   = 1 if str(d["ibge"]) in IBGE_ALVO else 0
        d["enc"]    = fmt_date(d["enc_raw"])
        d["pub"]    = fmt_date(d["pub_raw"])
        d["dias"]   = dias_restantes(d["enc_raw"])
        d["link"]   = str(d["link"] or "")
        d["cod"]    = get_cod(d["link"])

        # Modalidade simplificada
        mod = str(d["mod"] or "")
        d["mod"] = mod.replace(" - Eletrônico","").replace(" - Eletrônica","")

        # Status
        dias = d["dias"]
        if dias is None:
            d["status"] = "🟢 Aberta"
        elif dias >= 0:
            d["status"] = "🟢 Aberta"
        else:
            d["status"] = "🔴 Encerrada"

        # Limpa campos de texto
        for k in ["obj","orgao","muni","termos","cat","mod","tier"]:
            d[k] = clean(str(d.get(k) or ""))

        # Remove campos internos desnecessários
        for k in ["ibge","pub_raw","aber_raw","enc_raw"]:
            d.pop(k, None)

        # Hoje flag
        d["hoje"] = 1 if d["pub"] == hoje else 0

        data.append(d)

    return data


def build_muni_stats(data):
    stats = defaultdict(lambda: {"t":0,"a":0,"med":0,"ab":0,"val":0.0,"alvo":0})
    for r in data:
        m = r["muni"]
        stats[m]["t"] += 1
        if r["tier"] == "⭐⭐⭐ Alta":
            stats[m]["a"] += 1
        elif r["tier"] == "⭐⭐ Média":
            stats[m]["med"] += 1
        if "Aberta" in r["status"]:
            stats[m]["ab"] += 1
        stats[m]["val"] += r["val"]
        if r["alvo"] == 1:
            stats[m]["alvo"] = 1

    result = [{"m": k, **v} for k, v in stats.items()]
    result.sort(key=lambda x: -x["t"])
    return result


def gerar_html(data, munis, out_path: Path):
    hoje_str = date.today().strftime("%d/%m/%Y")
    total_munis = len(set(r["muni"] for r in data))

    dados_js = json.dumps(data, ensure_ascii=False, separators=(",",":"))
    munis_js = json.dumps(munis, ensure_ascii=False, separators=(",",":"))

    html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aiplates &mdash; Licitações MG &mdash; {hoje_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--ink:#0D1117;--paper:#F7F4EF;--accent:#1A3A6B;--gold:#C17F24;--green:#1B5E3B;--red:#8B1A1A;--muted:#6B6860;--border:#D8D3CB;--w:#fff}}
body{{font-family:'IBM Plex Sans',sans-serif;background:var(--paper);color:var(--ink);font-size:13px;line-height:1.6;min-height:100vh}}
nav{{background:var(--accent);display:flex;align-items:center;justify-content:space-between;padding:0 22px;height:52px;position:sticky;top:0;z-index:200;gap:8px}}
.brand{{display:flex;align-items:center;gap:7px;flex-shrink:0}}
.brand-dot{{width:9px;height:9px;border-radius:50%;background:#C17F24}}
.brand-name{{font-family:'Syne',sans-serif;font-size:14px;font-weight:800;color:#fff}}
.nav-links{{display:flex;gap:1px;flex:1;justify-content:center;flex-wrap:wrap}}
.nbtn{{background:none;border:none;padding:5px 10px;border-radius:3px;font-size:11px;color:rgba(255,255,255,.55);cursor:pointer;font-family:'IBM Plex Mono',monospace;white-space:nowrap;font-weight:500}}
.nbtn:hover{{color:#fff;background:rgba(255,255,255,.08)}}
.nbtn.on{{color:#fff;background:rgba(255,255,255,.15);font-weight:700}}
.nav-right{{display:flex;align-items:center;gap:7px;flex-shrink:0}}
.nav-pncp{{display:inline-flex;align-items:center;gap:4px;background:#C17F24;color:#fff;padding:4px 11px;border-radius:3px;font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;text-decoration:none;white-space:nowrap}}
.nav-pncp:hover{{background:#a86b1a}}
.bell-wrap{{position:relative}}
.bell-btn{{background:rgba(255,255,255,.12);border:none;border-radius:50%;width:32px;height:32px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;transition:background .15s}}
.bell-btn:hover{{background:rgba(255,255,255,.22)}}
.bell-btn.ring{{animation:rng .5s ease 2}}
@keyframes rng{{0%,100%{{transform:rotate(0)}}25%{{transform:rotate(-18deg)}}75%{{transform:rotate(18deg)}}}}
.bell-badge{{position:absolute;top:-2px;right:-2px;background:#E53E3E;color:#fff;font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:700;min-width:15px;height:15px;border-radius:8px;display:none;align-items:center;justify-content:center;padding:0 3px}}
.notif-panel{{position:fixed;top:56px;right:10px;width:320px;background:var(--w);border:1px solid var(--border);border-radius:6px;box-shadow:0 8px 28px rgba(0,0,0,.14);z-index:300;display:none;max-height:440px;flex-direction:column}}
.notif-panel.open{{display:flex}}
.notif-hdr{{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--border);background:var(--accent);border-radius:6px 6px 0 0;flex-shrink:0}}
.notif-hdr-t{{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#fff}}
.notif-clr{{background:none;border:none;color:rgba(255,255,255,.65);font-size:10px;cursor:pointer;font-family:'IBM Plex Mono',monospace}}
.notif-clr:hover{{color:#fff}}
.notif-body{{overflow-y:auto;flex:1}}
.nitem{{padding:10px 14px;border-bottom:1px solid var(--border);cursor:default}}
.nitem:hover{{background:var(--paper)}}
.nitem:last-child{{border-bottom:none}}
.nitem.new{{border-left:3px solid #C17F24;padding-left:11px}}
.ntag{{display:inline-block;font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:700;padding:2px 6px;border-radius:2px;color:#fff;margin-bottom:3px}}
.ntitle{{font-size:11px;color:var(--ink);line-height:1.4;margin-bottom:2px}}
.nmeta{{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace}}
.notif-empty{{padding:1.5rem;text-align:center;color:var(--muted);font-size:12px}}
.nav-date{{font-family:'IBM Plex Mono',monospace;font-size:10px;padding:3px 8px;border-radius:20px;background:rgba(255,255,255,.1);color:rgba(255,255,255,.75)}}
.page{{display:none}}.page.on{{display:block}}
.mast{{background:var(--accent);color:#fff;padding:34px 48px 26px;position:relative;overflow:hidden}}
.mast::before{{content:'';position:absolute;top:-60px;right:-60px;width:260px;height:260px;border:34px solid rgba(255,255,255,.06);border-radius:50%}}
.mast::after{{content:'';position:absolute;bottom:-40px;right:80px;width:170px;height:170px;border:22px solid rgba(193,127,36,.15);border-radius:50%}}
.mtag{{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.5);margin-bottom:8px}}
.mast h1{{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;line-height:1.15;margin-bottom:6px}}
.mast h1 span{{color:#C17F24}}
.mmeta{{display:flex;gap:22px;margin-top:12px;flex-wrap:wrap}}
.mmi{{font-size:11px;color:rgba(255,255,255,.55)}}.mmi strong{{color:rgba(255,255,255,.9);font-weight:500}}
.phdr{{padding:20px 48px 14px;border-bottom:1px solid var(--border);background:var(--w)}}
.phdr h2{{font-family:'Syne',sans-serif;font-size:19px;font-weight:800;color:var(--accent);margin-bottom:3px}}
.phdr p{{font-size:12px;color:var(--muted)}}
.phdr.ur h2{{color:var(--red)}}.phdr.ab h2{{color:var(--green)}}.phdr.gd h2{{color:var(--gold)}}
.wrap{{max-width:1120px;margin:0 auto;padding:26px 22px 56px}}
.kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:26px}}
.kpi{{background:var(--w);border:1px solid var(--border);border-top:3px solid var(--accent);padding:12px 14px}}
.kpi.g{{border-top-color:var(--green)}}.kpi.r{{border-top-color:var(--red)}}.kpi.gold{{border-top-color:var(--gold)}}
.kpi-n{{font-family:'Syne',sans-serif;font-size:22px;font-weight:700;color:var(--accent)}}
.kpi.g .kpi-n{{color:var(--green)}}.kpi.r .kpi-n{{color:var(--red)}}.kpi.gold .kpi-n{{color:var(--gold)}}
.kpi-l{{font-size:10px;color:var(--muted);margin-top:3px;text-transform:uppercase;letter-spacing:.05em}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:26px}}
.sec{{margin-bottom:30px}}
.shead{{display:flex;align-items:baseline;gap:10px;border-bottom:1px solid var(--border);padding-bottom:7px;margin-bottom:12px;flex-wrap:wrap}}
.shead h3{{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:var(--accent)}}
.sct{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted)}}
.sml{{margin-left:auto}}
.bars{{display:flex;flex-direction:column;gap:8px}}
.brow{{display:flex;align-items:center;gap:8px}}
.blbl{{font-size:11px;color:var(--muted);min-width:145px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.btrk{{flex:1;height:9px;background:#EAE6DF;border-radius:2px;overflow:hidden}}
.bfil{{height:100%;border-radius:2px}}
.bval{{font-family:'IBM Plex Mono',monospace;font-size:11px;min-width:34px;text-align:right;font-weight:500}}
.strow{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}}
.stcard{{background:var(--w);border:1px solid var(--border);padding:10px 14px;flex:1;min-width:70px}}
.stn{{font-family:'Syne',sans-serif;font-size:20px;font-weight:700}}
.stl{{font-size:10px;color:var(--muted);margin-top:2px}}
.tbar{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:10px}}
.ftags{{display:flex;gap:5px;flex-wrap:wrap}}
.ftag{{font-size:11px;font-weight:500;padding:3px 10px;border:1px solid var(--border);background:var(--w);color:var(--muted);cursor:pointer;font-family:'IBM Plex Mono',monospace;border-radius:2px}}
.ftag.on{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.rtools{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
.sbox{{font-family:'IBM Plex Sans',sans-serif;font-size:12px;padding:4px 8px;border:1px solid var(--border);border-radius:2px;background:var(--w);color:var(--ink);width:150px}}
.ssel{{font-family:'IBM Plex Mono',monospace;font-size:11px;padding:4px 8px;border:1px solid var(--border);border-radius:2px;background:var(--w);color:var(--ink);cursor:pointer}}
.bexp{{font-family:'IBM Plex Mono',monospace;font-size:11px;padding:4px 11px;background:var(--accent);color:#fff;border:none;border-radius:2px;cursor:pointer}}
.bexp:hover{{background:#0f2a5a}}
.cards{{display:flex;flex-direction:column;gap:8px}}
.lcard{{display:flex;align-items:flex-start;gap:16px;background:var(--w);border:1px solid var(--border);padding:12px 16px}}
.lcard.cab{{border-left:4px solid var(--green)}}
.lcard.cur{{border-left:4px solid var(--red)}}
.lcard.cirr{{border-left:4px solid #aaa;opacity:.75}}
.lcard.cenc{{border-left:4px solid var(--muted);opacity:.82}}
.lbody{{flex:1;min-width:0}}
.lcat{{font-size:10px;font-weight:600;color:var(--muted);margin-bottom:3px;font-family:'IBM Plex Mono',monospace;text-transform:uppercase;letter-spacing:.06em}}
.ltop{{display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin-bottom:5px}}
.lobj{{font-size:12px;line-height:1.5;color:var(--ink);margin-bottom:6px}}
.ltermos{{font-size:10px;color:var(--muted);margin-bottom:4px;font-family:'IBM Plex Mono',monospace}}
.lmeta{{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted)}}
.lmeta strong{{color:var(--ink);font-weight:500}}
.lright{{display:flex;flex-direction:column;align-items:flex-end;gap:6px;min-width:110px;flex-shrink:0}}
.lval{{font-family:'Syne',sans-serif;font-size:15px;font-weight:700;color:var(--accent);white-space:nowrap}}
.lval.sm{{font-size:12px;color:var(--muted)}}
.bdg{{display:inline-block;font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:500;padding:2px 7px;border-radius:2px;color:#fff}}
.bmod{{display:inline-block;font-size:10px;padding:2px 7px;border-radius:2px;background:#E6EDF8;color:var(--accent);font-family:'IBM Plex Mono',monospace}}
.bst{{font-size:11px;font-weight:500}}
.stag{{font-family:'IBM Plex Mono',monospace;font-size:10px;background:var(--paper);border:1px solid var(--border);padding:2px 6px;border-radius:2px;color:var(--muted)}}
.tirr{{font-family:'IBM Plex Mono',monospace;font-size:10px;background:#f5f0e8;border:1px solid #d0c8bb;padding:2px 6px;border-radius:2px;color:#888}}
.bcod{{font-family:'IBM Plex Mono',monospace;font-size:10px;padding:4px 10px;background:none;border:1px solid var(--border);border-radius:2px;color:var(--muted);cursor:pointer;white-space:nowrap}}
.bcod:hover{{border-color:var(--accent);color:var(--accent)}}
.bcod.ok{{background:var(--green);border-color:var(--green);color:#fff}}
.showmore{{display:block;width:100%;margin-top:10px;padding:8px;background:none;border:1px dashed var(--border);cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted)}}
.showmore:hover{{border-color:var(--accent);color:var(--accent)}}
.tbl-w{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th{{font-family:'IBM Plex Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);padding:7px 8px;text-align:left;border-bottom:2px solid var(--border);white-space:nowrap}}
td{{font-size:12px;padding:7px 8px;border-bottom:1px solid var(--border);vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#f5f2ed}}
.tr{{text-align:right}}.tc{{text-align:center}}.tg{{color:var(--green);font-weight:600}}.tm{{color:var(--muted)}}.tbld{{font-family:'Syne',sans-serif;font-weight:700}}
.alvo-tag{{display:inline-block;font-size:10px;background:#E6EDF8;color:var(--accent);font-family:'IBM Plex Mono',monospace;padding:1px 5px;border-radius:2px;font-weight:600}}
.empty{{text-align:center;padding:1.5rem;color:var(--muted);font-size:12px;background:var(--w);border:1px solid var(--border)}}
#toast{{position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%);background:var(--ink);color:#fff;font-size:12px;padding:7px 18px;border-radius:20px;opacity:0;transition:opacity .3s;z-index:9999;pointer-events:none;font-family:'IBM Plex Mono',monospace}}
footer{{border-top:1px solid var(--border);padding:14px 22px;display:flex;justify-content:space-between;font-size:11px;color:var(--muted);flex-wrap:wrap;gap:.5rem}}
footer strong{{color:var(--ink)}}
@media(max-width:860px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.g2{{grid-template-columns:1fr}}.mast{{padding:22px 18px 16px}}.mast h1{{font-size:18px}}.wrap{{padding:18px 10px 44px}}.phdr{{padding:14px 18px 10px}}.lcard{{flex-direction:column;gap:6px}}.lright{{align-items:flex-start}}.nav-links{{display:none}}}}
</style>
</head>
<body>
<div id="toast"></div>
<div class="notif-panel" id="notif-panel">
  <div class="notif-hdr"><span class="notif-hdr-t">&#128276; Novas Oportunidades</span><button class="notif-clr" onclick="clearNotif()">Limpar</button></div>
  <div class="notif-body" id="notif-list"></div>
</div>
<nav>
  <div class="brand"><div class="brand-dot"></div><span class="brand-name">Aiplates</span></div>
  <div class="nav-links">
    <button class="nbtn on" onclick="go('dash')">Dashboard</button>
    <button class="nbtn" onclick="go('ab')">&#127984; Em Aberto</button>
    <button class="nbtn" onclick="go('ur')">&#9889; Urgentes</button>
    <button class="nbtn" onclick="go('alvo')">&#10003; Alvos</button>
    <button class="nbtn" onclick="go('todos')">&#127758; Todos MG</button>
    <button class="nbtn" onclick="go('munis')">&#128205; Munic&iacute;pios</button>
    <button class="nbtn" onclick="go('enc')">&#9675; Encerradas</button>
  </div>
  <div class="nav-right">
    <a href="https://pncp.gov.br/app/editais?q=&status=recebendo_proposta&pagina=1" target="_blank" rel="noopener" class="nav-pncp">&#8599; Portal PNCP</a>
    <div class="bell-wrap">
      <button class="bell-btn" id="bell-btn" onclick="toggleNotif()" title="Novas oportunidades">&#128276;<span class="bell-badge" id="bell-badge"></span></button>
    </div>
    <span class="nav-date">{hoje_str}</span>
  </div>
</nav>

<!-- DASHBOARD -->
<div id="pg-dash" class="page on">
<div class="mast">
  <p class="mtag">Aiplates &middot; Minas Gerais &middot; PNCP &middot; {hoje_str}</p>
  <h1>Licita&ccedil;&otilde;es P&uacute;blicas de<br>Minas Gerais &mdash; <span>Aiplates</span></h1>
  <div class="mmeta">
    <div class="mmi">Fonte <strong>PNCP</strong></div>
    <div class="mmi">Emiss&atilde;o <strong>{hoje_str}</strong></div>
    <div class="mmi">Atualiza&ccedil;&atilde;o <strong>11:00</strong></div>
  </div>
</div>
<div class="wrap">
  <div class="kpis" id="d-kpis"></div>
  <div class="g2">
    <div>
      <div class="shead"><h3>Por Status</h3></div>
      <div class="strow" id="d-st"></div>
      <div class="shead" style="margin-top:16px"><h3>Por Categoria (Alta)</h3></div>
      <div class="bars" id="d-cats"></div>
    </div>
    <div>
      <div class="shead"><h3>Top Munic&iacute;pios</h3></div>
      <div class="bars" id="d-munis"></div>
      <div class="shead" style="margin-top:20px"><h3>Prazos em Aberto</h3></div>
      <div class="bars" id="d-prazos"></div>
    </div>
  </div>
  <div class="sec">
    <div class="shead"><h3>&#128197; Abertos Hoje</h3><span class="sct" id="d-hc"></span></div>
    <div class="cards" id="d-hcards"></div>
    <div class="empty" id="d-hempty" style="display:none">Nenhum edital publicado hoje.</div>
  </div>
  <div class="sec">
    <div class="shead"><h3>&#9889; Urgentes &mdash; Alta, vencem em at&eacute; 5 dias</h3><span class="sct" id="d-uc"></span><button class="bexp sml" onclick="go('ur')">Ver todos &#8599;</button></div>
    <div class="cards" id="d-ucards"></div>
    <div class="empty" id="d-uempty" style="display:none">Nenhum urgente no momento.</div>
  </div>
  <div class="sec">
    <div class="shead"><h3>&#127984; Em Aberto &mdash; Alta Relev&acirc;ncia</h3><span class="sct" id="d-ac"></span><button class="bexp sml" onclick="go('ab')">Ver todos &#8599;</button></div>
    <div class="cards" id="d-acards"></div>
  </div>
</div>
</div>

<!-- EM ABERTO -->
<div id="pg-ab" class="page">
<div class="phdr ab"><h2>&#127984; Editais em Aberto</h2><p>Licitações abertas &bull; Ordenar por score ou data</p></div>
<div class="wrap">
  <div class="tbar">
    <div class="ftags" id="ab-ftags"></div>
    <div class="rtools">
      <select class="ssel" id="ab-ord" onchange="rAb()"><option value="score">&#9660; Score</option><option value="enc">&#128197; Encerramento</option><option value="pub">&#128197; Publicação</option></select>
      <input class="sbox" id="ab-s" placeholder="Buscar..." oninput="rAb()">
      <button class="bexp" onclick="expPage('ab')">&#8595; CSV</button>
    </div>
  </div>
  <p class="sct" id="ab-ct" style="margin-bottom:10px"></p>
  <div class="cards" id="ab-cards"></div>
  <button class="showmore" id="ab-more" style="display:none" onclick="mAb()"></button>
</div>
</div>

<!-- URGENTES -->
<div id="pg-ur" class="page">
<div class="phdr ur"><h2>&#9889; Urgentes &mdash; Alta Relev&acirc;ncia</h2><p>Score &ge; 10 &bull; Vencem em at&eacute; 5 dias &bull; A&ccedil;&atilde;o imediata</p></div>
<div class="wrap">
  <p class="sct" id="ur-ct" style="margin-bottom:10px"></p>
  <div class="cards" id="ur-cards"></div>
  <div class="empty" id="ur-empty" style="display:none">Nenhum edital urgente no momento.</div>
</div>
</div>

<!-- ALVOS -->
<div id="pg-alvo" class="page">
<div class="phdr gd"><h2>&#10003; Munic&iacute;pios Alvo</h2><p>Alvos estratégicos em destaque &bull; Demais municípios abaixo</p></div>
<div class="wrap">
  <div class="tbar">
    <div class="ftags" id="alvo-ftags"></div>
    <div class="rtools">
      <select class="ssel" id="alvo-ord" onchange="rAlvo()"><option value="score">&#9660; Score</option><option value="enc">&#128197; Encerramento</option></select>
      <input class="sbox" id="alvo-s" placeholder="Buscar..." oninput="rAlvo()">
      <button class="bexp" onclick="expPage('alvo')">&#8595; CSV</button>
    </div>
  </div>
  <div class="shead"><h3>&#10003; Munic&iacute;pios Alvo</h3><span class="sct" id="alvo-ct"></span></div>
  <div class="cards" id="alvo-cards"></div>
  <button class="showmore" id="alvo-more" style="display:none" onclick="mAlvo()"></button>
  <div class="shead" style="margin-top:28px"><h3>&#128205; Demais Munic&iacute;pios</h3><span class="sct" id="nao-alvo-ct"></span></div>
  <div class="cards" id="nao-alvo-cards"></div>
  <button class="showmore" id="nao-alvo-more" style="display:none" onclick="mNaoAlvo()"></button>
</div>
</div>

<!-- TODOS MG -->
<div id="pg-todos" class="page">
<div class="phdr"><h2>&#127758; Todos os Munic&iacute;pios MG</h2><p>Todas as licitações do relatório &bull; {total_munis} municípios</p></div>
<div class="wrap">
  <div class="tbar">
    <div class="ftags" id="todos-ftags"></div>
    <div class="rtools">
      <select class="ssel" id="todos-ord" onchange="rTodos()"><option value="score">&#9660; Score</option><option value="enc">&#128197; Encerramento</option><option value="pub">&#128197; Publicação</option></select>
      <select class="ssel" id="todos-status" onchange="rTodos()"><option value="">Todos status</option><option value="ab">🟢 Abertas</option><option value="enc">🔴 Encerradas</option></select>
      <input class="sbox" id="todos-s" placeholder="Buscar município..." oninput="rTodos()">
      <button class="bexp" onclick="expPage('todos')">&#8595; CSV</button>
    </div>
  </div>
  <p class="sct" id="todos-ct" style="margin-bottom:10px"></p>
  <div class="cards" id="todos-cards"></div>
  <button class="showmore" id="todos-more" style="display:none" onclick="mTodos()"></button>
</div>
</div>

<!-- MUNICÍPIOS -->
<div id="pg-munis" class="page">
<div class="phdr"><h2>&#128205; Ranking Munic&iacute;pios MG</h2><p>{total_munis} municípios &bull; Todos os MG encontrados</p></div>
<div class="wrap">
  <div class="tbar"><div></div><div class="rtools"><input class="sbox" id="muni-s" placeholder="Buscar munic&iacute;pio..." oninput="rMunis()"></div></div>
  <div class="tbl-w"><table><thead><tr><th>#</th><th>Munic&iacute;pio</th><th class="tc">Alvo</th><th class="tc">Total</th><th class="tc">Alta</th><th class="tc">M&eacute;dia</th><th class="tc">Em Aberto</th><th class="tr">Valor Total</th></tr></thead><tbody id="muni-tbody"></tbody></table></div>
</div>
</div>

<!-- ENCERRADAS -->
<div id="pg-enc" class="page">
<div class="phdr"><h2>&#9675; Editais Encerrados</h2><p>Encerrados recentes</p></div>
<div class="wrap">
  <div class="tbar">
    <div class="ftags" id="enc-ftags"></div>
    <div class="rtools">
      <select class="ssel" id="enc-ord" onchange="rEnc()"><option value="score">&#9660; Score</option><option value="enc">&#128197; Encerramento</option></select>
      <input class="sbox" id="enc-s" placeholder="Buscar..." oninput="rEnc()">
      <button class="bexp" onclick="expPage('enc')">&#8595; CSV</button>
    </div>
  </div>
  <p class="sct" id="enc-ct" style="margin-bottom:10px"></p>
  <div class="cards" id="enc-cards"></div>
  <button class="showmore" id="enc-more" style="display:none" onclick="mEnc()"></button>
</div>
</div>

<footer>
  <div><strong>Aiplates</strong> &middot; PNCP &middot; {hoje_str}</div>
  <div>{total_munis} munic&iacute;pios &middot; {len(data)} licitações &middot; Atualização 11:00</div>
</footer>

<script type="application/json" id="_td">{dados_js}</script>
<script type="application/json" id="_md">{munis_js}</script>
<script>
var T=JSON.parse(document.getElementById('_td').textContent);
var M=JSON.parse(document.getElementById('_md').textContent);
var CB={{'Videomonitoramento':'#1B5E3B','Infraestrutura TI':'#1A3A6B','Frotas / Telemetria':'#C17F24','Drones / Sensoriamento':'#888','Reconhecimento / LPR':'#8B1A1A','Cybersecurity':'#6B1A1A','IA / Software':'#3C3489','Engenharia El\\u00e9trica':'#5A4700','Smart City':'#085041'}};
function fv(v){{if(!v||v===0)return '\\u2014';if(v>=1e6)return 'R$ '+(v/1e6).toFixed(1)+'M';if(v>=1000)return 'R$ '+(v/1000).toFixed(0)+'k';return 'R$ '+Math.round(v).toLocaleString('pt-BR')}}
function es(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}}
function tst(m){{var t=document.getElementById('toast');t.textContent=m;t.style.opacity='1';setTimeout(function(){{t.style.opacity='0'}},2500)}}
function parseDt(s){{if(!s)return'99999999';var p=String(s).split('/');if(p.length<3)return'99999999';return p[2]+p[1]+p[0]}}
document.addEventListener('click',function(e){{
  if(e.target.classList.contains('bcod')){{
    var cd=e.target.getAttribute('data-cod');if(!cd)return;
    navigator.clipboard.writeText(cd).then(function(){{e.target.textContent='Copiado!';e.target.classList.add('ok');tst('C\\u00f3digo copiado!');setTimeout(function(){{e.target.innerHTML='&#128203; Copiar';e.target.classList.remove('ok')}},2000)}}).catch(function(){{prompt('Copie:',cd)}});
  }}
  if(!document.getElementById('notif-panel').contains(e.target)&&!document.getElementById('bell-btn').contains(e.target)){{document.getElementById('notif-panel').classList.remove('open')}}
}});
var AB=T.filter(function(l){{return l.status&&l.status.indexOf('Aberta')>=0}});
var EN=T.filter(function(l){{return l.status&&l.status.indexOf('Encerrada')>=0}});
var UR=AB.filter(function(l){{return l.dias!==null&&Number(l.dias)<=5&&l.score>=10}});
var AV=AB.filter(function(l){{return l.alvo===1}});
var NAV=AB.filter(function(l){{return l.alvo===0}});
var AL=T.filter(function(l){{return l.tier==='\\u2b50\\u2b50\\u2b50 Alta'}});
var TV=AB.reduce(function(s,l){{return s+(l.val||0)}},0);
var cats={{}};
AL.forEach(function(l){{if(l.cat)cats[l.cat]=(cats[l.cat]||0)+1}});
var ck=Object.keys(cats).sort(function(a,b){{return cats[b]-cats[a]}});
var hj=new Date().toLocaleDateString('pt-BR',{{day:'2-digit',month:'2-digit',year:'numeric'}});
var HOJE_AB=T.filter(function(l){{return l.hoje===1}});
var NKEY='aiplates_seen_v4';
function getSeen(){{try{{return JSON.parse(localStorage.getItem(NKEY)||'[]')}}catch(e){{return[]}}}}
function saveSeen(ids){{try{{localStorage.setItem(NKEY,JSON.stringify(ids))}}catch(e){{}}}}
function buildNotifs(){{
  var seen=getSeen();var items=[];
  HOJE_AB.forEach(function(l){{var id='h_'+l.cod;items.push({{id:id,tag:'Aberto Hoje',tc:l.score>=10?'#1B5E3B':'#C17F24',title:l.obj,meta:l.muni+' score '+l.score,novo:seen.indexOf(id)<0}})}});
  UR.forEach(function(l){{var id='u_'+l.cod;items.push({{id:id,tag:'Urgente '+l.dias+'d',tc:'#8B1A1A',title:l.obj,meta:l.muni+' enc. '+l.enc,novo:seen.indexOf(id)<0}})}});
  AV.filter(function(l){{return l.score>=10}}).forEach(function(l){{var id='a_'+l.cod;if(!items.find(function(x){{return x.id===id}}))items.push({{id:id,tag:'Alta Alvo',tc:'#1A3A6B',title:l.obj,meta:l.muni+' '+l.cat,novo:seen.indexOf(id)<0}})}});
  return items;
}}
function renderNotifs(){{
  var items=buildNotifs();var novos=items.filter(function(x){{return x.novo}}).length;
  var bb=document.getElementById('bell-badge');var btn=document.getElementById('bell-btn');
  if(novos>0){{bb.style.display='flex';bb.textContent=novos;btn.classList.add('ring');setTimeout(function(){{btn.classList.remove('ring')}},1200)}}else{{bb.style.display='none'}}
  var el=document.getElementById('notif-list');
  if(items.length===0){{el.innerHTML='<div class="notif-empty">Nenhuma novidade.</div>';return}}
  el.innerHTML=items.map(function(it){{return'<div class="nitem'+(it.novo?' new':'')+'"><div><span class="ntag" style="background:'+it.tc+'">'+es(it.tag)+'</span></div><div class="ntitle">'+es(it.title.slice(0,80)+(it.title.length>80?'...':''))+'</div><div class="nmeta">'+es(it.meta)+'</div></div>'}}).join('');
}}
window.toggleNotif=function(){{var p=document.getElementById('notif-panel');p.classList.toggle('open');if(p.classList.contains('open')){{var items=buildNotifs();saveSeen(items.map(function(x){{return x.id}}));document.getElementById('bell-badge').style.display='none'}}}};
window.clearNotif=function(){{saveSeen([]);renderNotifs();document.getElementById('notif-panel').classList.remove('open');tst('Notificações limpas')}};
function go(id){{
  ['dash','ab','ur','alvo','todos','munis','enc'].forEach(function(p){{document.getElementById('pg-'+p).classList.remove('on')}});
  document.getElementById('pg-'+id).classList.add('on');
  document.querySelectorAll('.nbtn').forEach(function(b,i){{b.classList.toggle('on',['dash','ab','ur','alvo','todos','munis','enc'][i]===id)}});
  window.scrollTo(0,0);if(id==='munis')rMunis();if(id==='ur')rUr();if(id==='todos')rTodos();
}}
function card(l){{
  var ug=l.dias!==null&&Number(l.dias)<=5&&l.score>=10;
  var ab=l.status&&l.status.indexOf('Aberta')>=0;
  var irr=l.tier==='\\ud83d\\udd34 Irrelevante';
  var cl=ab?(irr?'cirr':ug?'cur':'cab'):'cenc';
  var dt=l.dias===null?'Sem prazo':Number(l.dias)===0?'Hoje':Number(l.dias)===1?'1 dia':l.dias+' dias';
  var cr=ug?'var(--red)':ab?'var(--green)':'var(--muted)';
  var p=[];
  p.push('<div class="lcard '+cl+'">');
  p.push('<div class="lbody">');
  if(l.cat)p.push('<div class="lcat">'+es(l.cat)+'</div>');
  p.push('<div class="ltop">');
  if(l.mod)p.push('<span class="bdg" style="background:'+(CB[l.cat]||'#888')+'">'+es(l.mod)+'</span>');
  p.push('<span class="bmod">'+es(l.muni)+'</span>');
  p.push('<span class="bst" style="color:'+cr+'">'+(ab?'&#9679;':'&#9675;')+' '+es(dt)+'</span>');
  if(l.alvo===1)p.push('<span class="bmod">&#10003; Alvo</span>');
  if(irr){{p.push('<span class="tirr">Irrelevante</span>')}}else if(l.score>0){{p.push('<span class="stag">score '+l.score+'</span>')}}
  p.push('</div>');
  p.push('<p class="lobj">'+es(l.obj)+'</p>');
  if(l.termos)p.push('<div class="ltermos">&#128269; '+es(l.termos)+'</div>');
  p.push('<div class="lmeta"><span>'+es(l.orgao)+'</span>');
  if(l.enc)p.push('<span>Enc. <strong>'+es(l.enc)+'</strong></span>');
  if(l.pub)p.push('<span>Pub. '+es(l.pub)+'</span>');
  p.push('</div></div>');
  p.push('<div class="lright"><div class="lval '+(l.val>=100000?'':'sm')+'">'+fv(l.val)+'</div>');
  if(l.link)p.push('<button class="bcod" data-cod="'+es(l.cod||l.link)+'">&#128203; Copiar</button>');
  p.push('</div></div>');
  return p.join('');
}}
function sortData(data,ord){{
  if(ord==='enc')return data.slice().sort(function(a,b){{return parseDt(a.enc).localeCompare(parseDt(b.enc))}});
  if(ord==='pub')return data.slice().sort(function(a,b){{return parseDt(b.pub).localeCompare(parseDt(a.pub))}});
  return data.slice().sort(function(a,b){{return b.score-a.score}});
}}
function mkCards(data,elId,moreId,sh){{
  var el=document.getElementById(elId);
  el.innerHTML=data.slice(0,sh).map(card).join('')||'<div class="empty">Nenhum resultado.</div>';
  var bm=document.getElementById(moreId);
  if(bm){{if(data.length>sh){{bm.style.display='block';bm.textContent='+ Mostrar mais ('+(data.length-sh)+' restantes)'}}else bm.style.display='none'}}
}}
function mkFtags(elId,fn){{
  var el=document.getElementById(elId);el.innerHTML='';
  function mk(lbl,val,on){{var b=document.createElement('button');b.className='ftag'+(on?' on':'');b.textContent=lbl;b.onclick=function(){{el.querySelectorAll('.ftag').forEach(function(x){{x.classList.remove('on')}});b.classList.add('on');fn(val)}};el.appendChild(b)}}
  mk('Todas','',true);ck.forEach(function(c){{mk(c,c,false)}});
}}
function expCSV(data,nm){{
  var cols=['Tier','Score','Categoria','Termos','Modalidade','Municipio','Alvo','Status','Dias','Objeto','Valor','Encerramento','Publicacao','Orgao','Codigo','Link'];
  var rows=data.map(function(l){{return[l.tier,l.score,l.cat,'"'+String(l.termos||'').replace(/"/g,'""')+'"',l.mod,l.muni,l.alvo?'Alvo':'',l.status,l.dias,'"'+String(l.obj).replace(/"/g,'""')+'"',l.val,l.enc,l.pub,'"'+String(l.orgao).replace(/"/g,'""')+'"',l.cod,l.link].join(',')}});
  var a=document.createElement('a');a.href='data:text/csv;charset=utf-8,'+encodeURIComponent('\\uFEFF'+cols.join(',')+'\n'+rows.join('\n'));a.download=nm+'.csv';a.click();tst('CSV: '+data.length+' registros');
}}
function bDash(){{
  document.getElementById('d-kpis').innerHTML=[
    {{n:fv(TV),l:'Valor em aberto',cls:'gold'}},
    {{n:T.length,l:'Total licitações',cls:''}},
    {{n:AB.length,l:'Em aberto',cls:'g'}},
    {{n:UR.length,l:'Urgentes \\u22645d',cls:'r'}},
    {{n:AL.length,l:'Alta relevância',cls:'g'}},
    {{n:AV.length,l:'Abertos alvo',cls:'g'}},
  ].map(function(k){{return'<div class="kpi '+k.cls+'"><div class="kpi-n">'+k.n+'</div><div class="kpi-l">'+k.l+'</div></div>'}}).join('');
  document.getElementById('d-st').innerHTML=[
    {{n:AB.length,l:'&#9679; Em aberto',c:'var(--green)'}},
    {{n:EN.length,l:'&#9675; Encerradas',c:'var(--muted)'}},
    {{n:UR.length,l:'&#9889; Urgentes',c:'var(--red)'}},
    {{n:AV.length,l:'&#10003; Alvo ab.',c:'var(--gold)'}},
  ].map(function(s){{return'<div class="stcard"><div class="stn" style="color:'+s.c+'">'+s.n+'</div><div class="stl">'+s.l+'</div></div>'}}).join('');
  var mc=Math.max.apply(null,Object.values(cats).concat([1]));
  document.getElementById('d-cats').innerHTML=ck.map(function(c){{return'<div class="brow"><span class="blbl">'+es(c)+'</span><div class="btrk"><div class="bfil" style="width:'+Math.round(cats[c]/mc*100)+'%;background:'+(CB[c]||'#888')+'"></div></div><span class="bval">'+cats[c]+'</span></div>'}}).join('');
  var t8=M.slice(0,8),mm=Math.max.apply(null,t8.map(function(m){{return m.t}}).concat([1]));
  document.getElementById('d-munis').innerHTML=t8.map(function(m){{return'<div class="brow"><span class="blbl">'+es(m.m)+(m.alvo?' ✅':'')+'</span><div class="btrk"><div class="bfil" style="width:'+Math.round(m.t/mm*100)+'%;background:var(--accent)"></div></div><span class="bval">'+m.t+'</span></div>'}}).join('');
  var pg=[
    {{l:'Hoje/amanhã',n:AB.filter(function(l){{return l.dias!==null&&Number(l.dias)<=1}}).length,c:'var(--red)'}},
    {{l:'2–5 dias',n:AB.filter(function(l){{return l.dias!==null&&Number(l.dias)>1&&Number(l.dias)<=5}}).length,c:'var(--gold)'}},
    {{l:'6–14 dias',n:AB.filter(function(l){{return l.dias!==null&&Number(l.dias)>5&&Number(l.dias)<=14}}).length,c:'var(--green)'}},
    {{l:'+14 dias',n:AB.filter(function(l){{return l.dias!==null&&Number(l.dias)>14}}).length,c:'var(--accent)'}},
  ];
  var mp=Math.max.apply(null,pg.map(function(g){{return g.n}}).concat([1]));
  document.getElementById('d-prazos').innerHTML=pg.map(function(g){{return'<div class="brow"><span class="blbl">'+g.l+'</span><div class="btrk"><div class="bfil" style="width:'+Math.round(g.n/mp*100)+'%;background:'+g.c+'"></div></div><span class="bval">'+g.n+'</span></div>'}}).join('');
  document.getElementById('d-hc').textContent=HOJE_AB.length+' publicados hoje ('+hj+')';
  if(HOJE_AB.length===0){{document.getElementById('d-hcards').innerHTML='';document.getElementById('d-hempty').style.display='block'}}
  else{{document.getElementById('d-hempty').style.display='none';mkCards(HOJE_AB,'d-hcards',null,HOJE_AB.length)}}
  document.getElementById('d-uc').textContent=UR.length+' urgentes';
  if(UR.length===0){{document.getElementById('d-ucards').innerHTML='';document.getElementById('d-uempty').style.display='block'}}
  else{{document.getElementById('d-uempty').style.display='none';mkCards(UR,'d-ucards',null,UR.length)}}
  var aab=AB.filter(function(l){{return l.tier==='\\u2b50\\u2b50\\u2b50 Alta'}});
  document.getElementById('d-ac').textContent=aab.length+' de alta relevância';
  mkCards(sortData(aab,'score'),'d-acards',null,6);
}}
var abCat='',abSh=20;
function rAb(){{var q=(document.getElementById('ab-s').value||'').toLowerCase();var ord=document.getElementById('ab-ord').value;var f=AB.filter(function(l){{return(!abCat||l.cat===abCat)&&(!q||(l.obj+l.muni+l.orgao+l.termos).toLowerCase().indexOf(q)>=0)}});f=sortData(f,ord);document.getElementById('ab-ct').textContent=f.length+' licitações abertas';mkCards(f,'ab-cards','ab-more',abSh)}}
window.mAb=function(){{abSh+=20;rAb()}};
mkFtags('ab-ftags',function(c){{abCat=c;abSh=20;rAb()}});rAb();
function rUr(){{document.getElementById('ur-ct').textContent=UR.length+' urgentes';if(UR.length===0){{document.getElementById('ur-cards').innerHTML='';document.getElementById('ur-empty').style.display='block'}}else{{document.getElementById('ur-empty').style.display='none';mkCards(UR,'ur-cards',null,UR.length)}}}}
var alvCat='',alvSh=20,naoAlvSh=20;
function rAlvo(){{var q=(document.getElementById('alvo-s').value||'').toLowerCase();var ord=document.getElementById('alvo-ord').value;var fa=AV.filter(function(l){{return(!alvCat||l.cat===alvCat)&&(!q||(l.muni+l.obj+l.orgao).toLowerCase().indexOf(q)>=0)}});var fn=NAV.filter(function(l){{return(!alvCat||l.cat===alvCat)&&(!q||(l.muni+l.obj+l.orgao).toLowerCase().indexOf(q)>=0)}});fa=sortData(fa,ord);fn=sortData(fn,ord);document.getElementById('alvo-ct').textContent=fa.length+' licitações em municípios alvo';document.getElementById('nao-alvo-ct').textContent=fn.length+' licitações em demais municípios';mkCards(fa,'alvo-cards','alvo-more',alvSh);mkCards(fn,'nao-alvo-cards','nao-alvo-more',naoAlvSh)}}
window.mAlvo=function(){{alvSh+=20;rAlvo()}};window.mNaoAlvo=function(){{naoAlvSh+=20;rAlvo()}};
mkFtags('alvo-ftags',function(c){{alvCat=c;alvSh=20;naoAlvSh=20;rAlvo()}});rAlvo();
var todosCat='',todosSh=20;
function rTodos(){{var q=(document.getElementById('todos-s').value||'').toLowerCase();var ord=document.getElementById('todos-ord').value;var st=document.getElementById('todos-status').value;var f=T.filter(function(l){{var okCat=!todosCat||l.cat===todosCat;var okQ=!q||(l.muni+l.obj+l.orgao+l.termos).toLowerCase().indexOf(q)>=0;var okSt=!st||(st==='ab'?l.status.indexOf('Aberta')>=0:l.status.indexOf('Encerrada')>=0);return okCat&&okQ&&okSt}});f=sortData(f,ord);document.getElementById('todos-ct').textContent=f.length+' licitações — todos os municípios MG';mkCards(f,'todos-cards','todos-more',todosSh)}}
window.mTodos=function(){{todosSh+=20;rTodos()}};
mkFtags('todos-ftags',function(c){{todosCat=c;todosSh=20;rTodos()}});rTodos();
function rMunis(){{var q=(document.getElementById('muni-s').value||'').toLowerCase();var f=M.filter(function(m){{return!q||m.m.toLowerCase().indexOf(q)>=0}});document.getElementById('muni-tbody').innerHTML=f.map(function(m,i){{return'<tr><td class="tc tm">'+(i+1)+'</td><td><strong>'+es(m.m)+'</strong></td><td class="tc">'+(m.alvo?'<span class="alvo-tag">✅ Alvo</span>':'<span class="tm">—</span>')+'</td><td class="tc tbld">'+m.t+'</td><td class="tc tg">'+m.a+'</td><td class="tc">'+m.med+'</td><td class="tc" style="color:'+(m.ab>0?'var(--green)':'var(--muted)')+'"><strong>'+m.ab+'</strong></td><td class="tr tbld">'+(m.val>0?fv(m.val):'—')+'</td></tr>'}}).join('')}}
rMunis();
var encCat='',encSh=20;
function rEnc(){{var q=(document.getElementById('enc-s').value||'').toLowerCase();var ord=document.getElementById('enc-ord').value;var f=EN.filter(function(l){{return(!encCat||l.cat===encCat)&&(!q||(l.obj+l.muni+l.orgao).toLowerCase().indexOf(q)>=0)}});f=sortData(f,ord);document.getElementById('enc-ct').textContent=f.length+' editais encerrados';mkCards(f,'enc-cards','enc-more',encSh)}}
window.mEnc=function(){{encSh+=20;rEnc()}};
mkFtags('enc-ftags',function(c){{encCat=c;encSh=20;rEnc()}});rEnc();
window.expPage=function(pg){{
  if(pg==='ab'){{var q=(document.getElementById('ab-s').value||'').toLowerCase();var ord=document.getElementById('ab-ord').value;expCSV(sortData(AB.filter(function(l){{return(!abCat||l.cat===abCat)&&(!q||(l.obj+l.muni+l.orgao+l.termos).toLowerCase().indexOf(q)>=0)}}),ord),'abertos')}}
  if(pg==='alvo'){{var q2=(document.getElementById('alvo-s').value||'').toLowerCase();expCSV(AV.filter(function(l){{return(!alvCat||l.cat===alvCat)&&(!q2||(l.muni+l.obj+l.orgao).toLowerCase().indexOf(q2)>=0)}}),'municipios_alvo')}}
  if(pg==='todos'){{var q3=(document.getElementById('todos-s').value||'').toLowerCase();var ord3=document.getElementById('todos-ord').value;expCSV(sortData(T.filter(function(l){{return(!todosCat||l.cat===todosCat)&&(!q3||(l.muni+l.obj+l.orgao).toLowerCase().indexOf(q3)>=0)}}),ord3),'todos_mg')}}
  if(pg==='enc'){{var q4=(document.getElementById('enc-s').value||'').toLowerCase();var ord4=document.getElementById('enc-ord').value;expCSV(sortData(EN.filter(function(l){{return(!encCat||l.cat===encCat)&&(!q4||(l.obj+l.muni+l.orgao).toLowerCase().indexOf(q4)>=0)}}),ord4),'encerrados')}}
}};
bDash();renderNotifs();
</script>
</body>
</html>'''

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    log.info(f"✅ HTML gerado: {out_path} ({out_path.stat().st_size//1024} KB)")
    log.info(f"   Registros: {len(data)} | Municípios: {total_munis}")


def main():
    out_dir = Path(__file__).parent / "docs"
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        out_dir = Path(sys.argv[idx + 1])

    log.info("Carregando dados do banco...")
    data  = load_data()
    munis = build_muni_stats(data)
    gerar_html(data, munis, out_dir / "index.html")


if __name__ == "__main__":
    main()
