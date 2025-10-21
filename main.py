# Calculadora de Faturamento Mínimo — Hologram
# Rodar: streamlit run streamlit_faturamento_minimo.py

import re
import json
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st

# PDF opcional
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib.colors import Color, black
    PDF_OK = True
except Exception:
    PDF_OK = False

# -------------------- CONFIG --------------------
st.set_page_config(
    page_title="Calculadora de Faturamento Mínimo",
    layout="wide",
)

PALETTE = {"accent": "#00A899", "bg": "#050937", "white": "#FFFFFF"}
CALENDLY_URL = "https://calendly.com/"  # troque pelo seu link

# -------------------- ESTILO --------------------
st.markdown(f"""
<style>
:root {{
  --accent:{PALETTE['accent']};
  --bg:{PALETTE['bg']};
  --white:{PALETTE['white']};
}}
html, body, [data-testid="stAppViewContainer"] {{
  background: linear-gradient(180deg, rgba(5,9,55,1) 0%, rgba(0,168,153,0.05) 100%);
  color: var(--white);
}}
.h-panel,.h-card {{
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.02);
  background: linear-gradient(135deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015));
  border: 1px solid rgba(255,255,255,0.06);
}}
.h-card {{ transition: transform .25s ease, box-shadow .25s ease; }}
.h-card:hover {{ transform: translateY(-2px); box-shadow: 0 14px 36px rgba(0,0,0,0.5); }}
.h-title {{font-size:20px;font-weight:800;color:var(--accent);}}
.h-num {{font-size:28px;font-weight:900;margin-top:6px;}}
.h-sub {{font-size:13px;opacity:.8;}}
a.h-cta {{
  display:inline-block;padding:10px 16px;border-radius:12px;text-decoration:none;font-weight:800;
  background:var(--accent);color:var(--bg);
}}
.small-muted {{font-size:12px;opacity:.7;}}
.err {{color:#ffb3b3;font-size:12px;margin-top:4px;}}
.ok  {{color:#9fe7cf;font-size:12px;margin-top:4px;}}
</style>
""", unsafe_allow_html=True)

# -------------------- VALIDADORES --------------------
_LETTERS = "A-Za-zÀ-ÖØ-öø-ÿÇç"
def is_valid_name(s: str) -> bool:
    s = (s or "").strip()
    if len(s) < 3 or " " not in s:  # nome e sobrenome
        return False
    return re.fullmatch(rf"[{_LETTERS}'´`^~\- ]+", s) is not None

# -------------------- VALIDADORES --------------------
import re

_LETTERS = "A-Za-zÀ-ÖØ-öø-ÿÇç"

def is_valid_name(s: str) -> bool:
    s = (s or "").strip()
    if len(s) < 3 or " " not in s:   # exige nome e sobrenome
        return False
    # letras (com acentos), espaço e hífen
    return re.fullmatch(rf"[{_LETTERS}'´`^~\- ]+", s) is not None

def is_valid_company(s: str) -> bool:
    s = (s or "").strip()
    if len(s) < 2:
        return False
    # letras, números, espaço e . & -
    # (corrigido: rf, e hífen no final da classe para não precisar escapar)
    return re.fullmatch(rf"[{_LETTERS}0-9 .,&-]+", s) is not None

def is_valid_email(s: str) -> bool:
    s = (s or "").strip()
    return re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", s) is not None

def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def is_valid_phone_br(s: str) -> bool:
    """Opcional. Aceita com/sem +55; válido com 10 (fixo) ou 11 (móvel) dígitos."""
    if not s:
        return True
    d = only_digits(s)
    if d.startswith("55") and len(d) >= 12:
        d = d[2:]
    return len(d) in (10, 11)


# -------------------- FUNÇÕES DE CÁLCULO --------------------
def to_float_pct(x: float) -> float:
    return float(x) / 100.0

def calc_metrics(fixed: float, var_pct: float, profit_pct: float, ticket: float):
    v = to_float_pct(var_pct)
    p = to_float_pct(profit_pct)
    denom = 1.0 - v - p
    result = {"warning": None}

    if denom <= 0:
        result.update({
            "faturamento_min": float("inf"),
            "ponto_equilibrio": float("inf"),
            "vendas_necessarias": float("inf"),
            "warning": "Percentual de variáveis + lucro ≥ 100%. Ajuste os percentuais para existir solução."
        })
        return result

    faturamento_min = fixed / denom
    ponto_equilibrio = fixed / (1.0 - v) if (1.0 - v) > 0 else float("inf")
    vendas_necessarias = (faturamento_min / ticket) if ticket > 0 else float("inf")

    result.update({
        "faturamento_min": faturamento_min,
        "ponto_equilibrio": ponto_equilibrio,
        "vendas_necessarias": vendas_necessarias,
    })
    return result

def brl(v):
    if v == float("inf"):
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def intfmt(v):
    if v == float("inf"):
        return "—"
    return f"{int(round(v, 0)):,}".replace(",", ".")

def save_server_preset(email, data):
    store = {}
    try:
        with open("presets.json", "r", encoding="utf-8") as f:
            store = json.load(f)
    except Exception:
        store = {}
    store[email] = data
    with open("presets.json", "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)

def load_server_preset(email):
    with open("presets.json", "r", encoding="utf-8") as f:
        return json.load(f).get(email)

def pdf_bytes(client, inputs, metrics):
    if not PDF_OK:
        return None
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    left = 20 * mm
    y = h - 22 * mm
    accent = Color(0/255, 168/255, 153/255)  # #00A899

    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, "Diagnóstico — Calculadora de Faturamento Mínimo")
    y -= 14
    c.setFillColor(black)
    c.setFont("Helvetica", 10)
    c.drawString(left, y, f"Nome: {client['nome']}   E-mail: {client['email']}   Empresa: {client['empresa']}")
    y -= 12
    if client.get("whatsapp"):
        c.drawString(left, y, f"WhatsApp: {client['whatsapp']}")
        y -= 12
    c.drawString(left, y, f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    y -= 18
    c.setFont("Helvetica-Bold", 12); c.drawString(left, y, "Entradas"); y -= 14; c.setFont("Helvetica", 10)
    c.drawString(left, y, f"Gastos Fixos: {brl(inputs['fixed'])}"); y -= 12
    c.drawString(left, y, f"% Variáveis: {inputs['var_pct']:.1f}%"); y -= 12
    c.drawString(left, y, f"Lucro Esperado: {inputs['profit_pct']:.1f}%"); y -= 12
    c.drawString(left, y, f"Ticket Médio: {brl(inputs['ticket'])}"); y -= 12
    c.drawString(left, y, f"Faturamento Atual: {brl(inputs['revenue_current'])}")

    y -= 18
    c.setFont("Helvetica-Bold", 12); c.drawString(left, y, "Resultados"); y -= 14; c.setFont("Helvetica", 10)
    c.drawString(left, y, f"Faturamento Mínimo: {brl(metrics['faturamento_min'])}"); y -= 12
    c.drawString(left, y, f"Ponto de Equilíbrio: {brl(metrics['ponto_equilibrio'])}"); y -= 12
    c.drawString(left, y, f"Vendas Necessárias: {intfmt(metrics['vendas_necessarias'])}")

    y -= 18
    c.setFont("Helvetica-Bold", 12); c.drawString(left, y, "Análise de Gap"); y -= 14; c.setFont("Helvetica", 10)
    if metrics["faturamento_min"] == float("inf"):
        c.drawString(left, y, "Sem solução para os percentuais informados.")
    else:
        gap = metrics["faturamento_min"] - inputs["revenue_current"]
        c.drawString(left, y, f"Gap vs Faturamento Atual: {brl(gap)}")

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()

# -------------------- LAYOUT (PAINEL LATERAL + CALCULADORA) --------------------
st.title("Calculadora de Faturamento Mínimo")
st.caption("Defina os parâmetros e visualize os resultados após preencher seus dados ao lado.")

left, right = st.columns([1, 2])

with left:
    st.markdown("### Dados do Cliente — Liberar resultado")
    with st.form("lead_form"):
        st.markdown("<small>Preencha para liberar os resultados.</small>", unsafe_allow_html=True)

        cliente_nome = st.text_input("Nome completo*", placeholder="Ex.: João Silva")
        if cliente_nome:
            st.markdown(
                "<div class='ok'>✔️ Ex.: João da Silva</div>" if is_valid_name(cliente_nome)
                else "<div class='err'>Informe nome e sobrenome (apenas letras, espaços e hífen).</div>",
                unsafe_allow_html=True
            )

        cliente_email = st.text_input("E-mail profissional*", placeholder="exemplo@empresa.com")
        if cliente_email:
            st.markdown(
                "<div class='ok'>✔️ E-mail válido</div>" if is_valid_email(cliente_email)
                else "<div class='err'>E-mail inválido.</div>",
                unsafe_allow_html=True
            )

        cliente_empresa = st.text_input("Empresa*", placeholder="Nome da empresa")
        if cliente_empresa:
            st.markdown(
                "<div class='ok'>✔️ Empresa válida</div>" if is_valid_company(cliente_empresa)
                else "<div class='err'>Use somente letras, números, espaço e . & -</div>",
                unsafe_allow_html=True
            )

        cliente_whatsapp = st.text_input("WhatsApp (opcional)", placeholder="(DDD) 90000-0000")
        if cliente_whatsapp:
            st.markdown(
                "<div class='ok'>✔️ Telefone OK</div>" if is_valid_phone_br(cliente_whatsapp)
                else "<div class='err'>Telefone inválido. Ex.: (11) 90000-0000 ou +55 11 90000-0000</div>",
                unsafe_allow_html=True
            )

        submit = st.form_submit_button("Liberar resultados")

    # validação obrigatória
    liberar = False
    if submit:
        errors = []
        if not is_valid_name(cliente_nome):
            errors.append("Nome inválido.")
        if not is_valid_email(cliente_email):
            errors.append("E-mail inválido.")
        if not is_valid_company(cliente_empresa):
            errors.append("Empresa inválida.")
        if cliente_whatsapp and not is_valid_phone_br(cliente_whatsapp):
            errors.append("WhatsApp inválido.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            liberar = True
            st.success("✅ Dados recebidos! Você pode visualizar os resultados.")

    st.markdown("---")
    st.markdown("<div class='small-muted'>Calendly</div>", unsafe_allow_html=True)
    st.markdown(f"<a class='h-cta' href='{CALENDLY_URL}' target='_blank'>Agendar diagnóstico</a>", unsafe_allow_html=True)

with right:
    with st.expander("Entradas rápidas", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            fixed = st.number_input(
                "Gastos Fixos (R$)", min_value=0.0,
                value=float(st.session_state.get("fixed", 5000.0)),
                step=100.0, key="fixed"
            )
            ticket = st.number_input(
                "Ticket Médio (R$)", min_value=0.0,
                value=float(st.session_state.get("ticket", 100.0)),
                step=10.0, key="ticket"
            )
            revenue_current = st.number_input(
                "Faturamento Atual (R$)", min_value=0.0,
                value=float(st.session_state.get("revenue_current", 8000.0)),
                step=100.0, key="revenue_current"
            )
        with c2:
            var_pct = st.slider(
                "% Variáveis (sobre faturamento)", min_value=0.0, max_value=100.0,
                value=float(st.session_state.get("var_pct", 20.0)), step=0.5, key="var_pct"
            )
            profit_pct = st.slider(
                "Lucro Esperado (% sobre faturamento)", min_value=0.0, max_value=100.0,
                value=float(st.session_state.get("profit_pct", 10.0)), step=0.5, key="profit_pct"
            )

    # ---- Cálculos (somente após lead liberar) ----
    if liberar:
        base = calc_metrics(fixed, var_pct, profit_pct, ticket)
        gap = base["faturamento_min"] - revenue_current if base["faturamento_min"] != float("inf") else None

        k1, k2, k3, k4 = st.columns([1.2, 1.2, 1.2, 1])
        with k1:
            st.markdown(
                f"<div class='h-card'><div class='h-title'>Faturamento Mínimo</div>"
                f"<div class='h-num'>{brl(base['faturamento_min'])}</div>"
                f"<div class='h-sub'>Cobre fixos + variáveis + lucro</div></div>",
                unsafe_allow_html=True
            )
        with k2:
            st.markdown(
                f"<div class='h-card'><div class='h-title'>Vendas Necessárias</div>"
                f"<div class='h-num'>{intfmt(base['vendas_necessarias'])}</div>"
                f"<div class='h-sub'>Qtde ao ticket médio</div></div>",
                unsafe_allow_html=True
            )
        with k3:
            st.markdown(
                f"<div class='h-card'><div class='h-title'>Ponto de Equilíbrio</div>"
                f"<div class='h-num'>{brl(base['ponto_equilibrio'])}</div>"
                f"<div class='h-sub'>Sem lucro</div></div>",
                unsafe_allow_html=True
            )
        with k4:
            gap_txt = "—" if gap is None else ("Atingido" if gap <= 0 else brl(gap))
            st.markdown(
                f"<div class='h-card'><div class='h-title'>Gap vs. Faturamento Atual</div>"
                f"<div class='h-num'>{gap_txt}</div>"
                f"<div class='h-sub'>Diferença meta x atual</div></div>",
                unsafe_allow_html=True
            )

        if base.get("warning"):
            st.error(base["warning"])

        # salvar/carregar preset por e-mail (opcional, arquivo local)
        st.markdown("---")
        colA, colB = st.columns(2)
        with colA:
            if st.button("Salvar preset no servidor (por e-mail)"):
                if cliente_email:
                    save_server_preset(cliente_email, {
                        "nome": cliente_nome,
                        "empresa": cliente_empresa,
                        "whatsapp": cliente_whatsapp,
                        "fixed": fixed, "var_pct": var_pct, "profit_pct": profit_pct,
                        "ticket": ticket, "revenue_current": revenue_current,
                        "saved_at": datetime.now().isoformat()
                    })
                    st.success("Preset salvo em presets.json.")
                else:
                    st.error("Informe o e-mail.")
        with colB:
            if st.button("Carregar preset do servidor (por e-mail)"):
                if not cliente_email:
                    st.error("Informe o e-mail para buscar.")
                else:
                    try:
                        data = load_server_preset(cliente_email)
                        if data:
                            st.session_state["fixed"] = float(data["fixed"])
                            st.session_state["var_pct"] = float(data["var_pct"])
                            st.session_state["profit_pct"] = float(data["profit_pct"])
                            st.session_state["ticket"] = float(data["ticket"])
                            st.session_state["revenue_current"] = float(data["revenue_current"])
                            st.success("Preset carregado. Recarregando…")
                            st.rerun()
                        else:
                            st.error("Preset não encontrado para este e-mail.")
                    except FileNotFoundError:
                        st.error("Arquivo presets.json não encontrado.")

        # PDF
        st.markdown("---")
        if st.button("Gerar PDF do diagnóstico"):
            if not PDF_OK:
                st.error("Instale 'reportlab' para exportar PDF:  pip install reportlab")
            else:
                bytes_pdf = pdf_bytes(
                    {"nome": cliente_nome, "email": cliente_email, "empresa": cliente_empresa, "whatsapp": cliente_whatsapp},
                    {"fixed": fixed, "var_pct": var_pct, "profit_pct": profit_pct, "ticket": ticket, "revenue_current": revenue_current},
                    base
                )
                if bytes_pdf:
                    st.download_button("Download do PDF", data=bytes_pdf, file_name="diagnostico_faturamento.pdf", mime="application/pdf")
                else:
                    st.error("Falha ao gerar PDF.")
    else:
        st.info("Preencha **Nome**, **E-mail** e **Empresa** válidos e clique em **Liberar resultados** no painel lateral para ver os KPIs.")

st.markdown("---")
st.markdown(f"<div style='text-align:center'><a class='h-cta' href='{CALENDLY_URL}' target='_blank'>Marcar consultoria</a></div>", unsafe_allow_html=True)
st.caption("Feito com ❤️  • Paleta: #00A899 / #050937 / #FFFFFF")
