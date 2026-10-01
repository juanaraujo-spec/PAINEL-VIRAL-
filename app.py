import os

import pandas as pd
import plotly.express as px
import streamlit as st

from logic import (COL_TAXA, agregar_virus, indicadores_prod, processar_relatorio_gal)

st.set_page_config(page_title="Painel Viral - LACEN", page_icon="🧬", layout="wide")

st.markdown("""
<style>
    .main-header {
        background-color: #f8f9fa;
        padding: 15px 20px;
        border-radius: 10px;
        border-left: 6px solid #0056b3;
        margin-bottom: 25px;
    }
</style>
""", unsafe_allow_html=True)


# Os relatórios ficam só na memória do servidor; o cache expira em 1 hora.
@st.cache_data(show_spinner="Lendo o relatório...", ttl=3600, max_entries=5)
def carregar(conteudo: bytes):
    return processar_relatorio_gal(conteudo)


def fmt_int(n):
    return f"{int(n):,}".replace(",", ".")


def fmt_dias(x):
    return "–" if pd.isna(x) else f"{x:.2f} dias".replace(".", ",")


st.sidebar.title("Painel de Controle")
if os.path.exists("101915.jpg"):
    st.sidebar.image("101915.jpg", width="stretch")

arquivo = st.sidebar.file_uploader("📥 Envie o relatório do GAL (.xlsx)", type="xlsx")
st.sidebar.caption("O arquivo é processado em memória durante a sessão e não é gravado em disco pelo painel.")

if arquivo is None:
    st.info("👈 Faça upload do relatório .xlsx na barra lateral para carregar o painel.")
    st.stop()

try:
    df_prod_total, df_virus_total = carregar(arquivo.getvalue())
except ValueError as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # arquivo corrompido, formato inesperado etc.
    st.error("Não foi possível ler o relatório. Confira se é o .xlsx do GAL, com as abas "
             "'Produtividade' e 'Mensal'.")
    with st.expander("Detalhes técnicos"):
        st.code(repr(e))
    st.stop()

meses = list(df_prod_total["Mês"])
if not meses:
    st.warning("O relatório não tem nenhum mês na aba Produtividade.")
    st.stop()

selecionados = st.sidebar.multiselect("📅 Meses", options=meses, default=meses)
if not selecionados:
    st.warning("Selecione pelo menos um mês na barra lateral.")
    st.stop()

df_prod = df_prod_total[df_prod_total["Mês"].isin(selecionados)]
df_virus = df_virus_total[df_virus_total["Mês"].isin(selecionados)]

kpi = indicadores_prod(df_prod)
virus, sem_peso = agregar_virus(df_prod, df_virus)
detectados = virus[virus["Casos (n)"] > 0]

st.markdown("""
<div class="main-header">
    <h1 style='margin:0; color:#0056b3;'>📊 Painel Viral — Epidemiológico & Laboratorial</h1>
    <p style='margin:0; color:#6c757d;'>Monitoramento de painel viral e prazos de análise (GAL)</p>
</div>
""", unsafe_allow_html=True)

st.caption("Período: " + (", ".join(selecionados) if len(selecionados) <= 6
                          else f"{selecionados[0]} a {selecionados[-1]} ({len(selecionados)} meses)"))

st.subheader("📌 Indicadores-chave (KPIs)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Amostras liberadas", fmt_int(kpi["liberados"]))
c2.metric("Média de análise", fmt_dias(kpi["analise"]))
c3.metric("Média de liberação", fmt_dias(kpi["liberacao"]))
if detectados.empty:
    c4.metric("Vírus mais frequente", "Nenhum")
else:
    c4.metric("Vírus mais frequente", detectados.iloc[0]["Vírus"],
              f"{fmt_int(detectados.iloc[0]['Casos (n)'])} casos", delta_color="off")
st.caption("Médias de prazo ponderadas pelo nº de amostras liberadas em cada mês.")

st.markdown("---")

col_l, col_r = st.columns([6, 4])
with col_l:
    if detectados.empty:
        st.info("Nenhum vírus detectado no período selecionado.")
    else:
        graf = detectados.sort_values("Casos (n)", ascending=True)
        fig_v = px.bar(graf, x="Casos (n)", y="Vírus", orientation="h", text="Casos (n)",
                       title="<b>Casos por agente etiológico (soma do período)</b>",
                       color=COL_TAXA, color_continuous_scale="Reds")
        fig_v.update_traces(textposition="outside")
        st.plotly_chart(fig_v, width="stretch")

with col_r:
    st.markdown("<b>Detalhamento da taxa de detecção</b>", unsafe_allow_html=True)
    if not detectados.empty:
        st.dataframe(detectados, hide_index=True, width="stretch",
                     column_config={COL_TAXA: st.column_config.NumberColumn(COL_TAXA, format="%.1f%%")})
    if sem_peso:
        st.caption("⚠️ Alguns meses da aba Mensal não foram encontrados na aba Produtividade; "
                   "a taxa foi calculada por média simples.")
    else:
        st.caption("Taxa do período = média das taxas mensais ponderada pelo nº de liberados.")

st.markdown("---")

st.subheader("⏱ Desempenho e prazos (SLA)")
cs1, cs2 = st.columns(2)
with cs1:
    if sum(kpi["sla"].values()) == 0:
        st.info("Sem dados de SLA no período selecionado.")
    else:
        fig_pie = px.pie(names=list(kpi["sla"].keys()), values=list(kpi["sla"].values()),
                         title="<b>SLA de liberação</b>", hole=0.4)
        st.plotly_chart(fig_pie, width="stretch")

with cs2:
    fig_bar = px.bar(x=["Envio", "Análise", "Liberação"],
                     y=[kpi["envio"], kpi["analise"], kpi["liberacao"]],
                     title="<b>Média de dias por etapa</b>",
                     labels={"x": "Etapa", "y": "Dias"}, text_auto=".1f")
    st.plotly_chart(fig_bar, width="stretch")
