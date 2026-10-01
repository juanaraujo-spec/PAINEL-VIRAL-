"""Leitura do relatório do GAL e cálculos do Painel Viral (LACEN).

Sem nenhuma chamada ao Streamlit: assim a lógica pode ser testada à parte.
"""
import io
from datetime import datetime

import numpy as np
import pandas as pd

ABAS = ("Produtividade", "Mensal")

COL_N = "N liberados"
COL_ENVIO = "Envio — média (dias)"
COL_ANALISE = "Análise — média (dias)"
COL_LIBERACAO = "Liberação — média (dias)"
COLS_SLA = {"≤ 3 dias": "≤3 dias", "4 - 7 dias": "4-7 dias",
            "8 - 10 dias": "8-10 dias", "> 10 dias": ">10 dias"}
COL_TAXA = "Taxa de detecção (%)"

COLUNAS_PRODUTIVIDADE = ["Mês", COL_N, COL_ENVIO, COL_ANALISE, COL_LIBERACAO, *COLS_SLA.values()]


def _rotulo_mes(valor):
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.strftime("%m/%Y")
    return str(valor).strip()


def _ler_taxa(valor):
    """Devolve (número, veio_com_símbolo_%). Aceita 0.05, 5, '5%', '5,0%'."""
    if pd.isna(valor):
        return np.nan, False
    if isinstance(valor, str):
        texto = valor.strip()
        com_simbolo = "%" in texto
        texto = texto.replace("%", "").replace(",", ".").strip()
        try:
            return float(texto), com_simbolo
        except ValueError:
            return np.nan, False
    try:
        return float(valor), False
    except (TypeError, ValueError):
        return np.nan, False


def _normalizar_taxas(brutas):
    """Converte a coluna de percentuais para a escala 0–100.

    Decide por coluna (e não por célula): se todos os valores numéricos são <= 1,
    o Excel guardou frações (0,05 = 5%); caso contrário já estão em pontos percentuais.
    Textos com '%' são sempre lidos como pontos percentuais.
    """
    pares = brutas.map(_ler_taxa)
    valores = pares.map(lambda p: p[0])
    com_simbolo = pares.map(lambda p: p[1])
    numericos = valores[~com_simbolo].dropna()
    fracao = (not numericos.empty) and float(numericos.max()) <= 1.0
    taxa = np.where(com_simbolo, valores, valores * 100 if fracao else valores)
    return pd.Series(taxa, index=brutas.index).fillna(0.0).round(2)


def processar_relatorio_gal(conteudo: bytes):
    """Lê o .xlsx do GAL e devolve (df_prod, df_virus).

    df_prod  : uma linha por mês (aba Produtividade), sem a linha TOTAL.
    df_virus : uma linha por mês × vírus (aba Mensal): Mês, Vírus, Casos (n), Taxa de detecção (%).
    """
    xls = pd.ExcelFile(io.BytesIO(conteudo))
    faltam_abas = [a for a in ABAS if a not in xls.sheet_names]
    if faltam_abas:
        raise ValueError(f"O arquivo não tem a(s) aba(s) {faltam_abas}. "
                         f"Abas encontradas: {xls.sheet_names}.")

    # ---- Produtividade
    df_prod = pd.read_excel(xls, sheet_name="Produtividade")
    df_prod.columns = [str(c).strip() for c in df_prod.columns]
    faltam = [c for c in COLUNAS_PRODUTIVIDADE if c not in df_prod.columns]
    if faltam:
        raise ValueError(f"Colunas ausentes na aba Produtividade: {faltam}. O layout do relatório mudou?")
    df_prod = df_prod[df_prod["Mês"].notna()].copy()
    df_prod["Mês"] = df_prod["Mês"].map(_rotulo_mes)
    df_prod = df_prod[df_prod["Mês"].str.upper() != "TOTAL"].copy()
    for c in COLUNAS_PRODUTIVIDADE[1:]:
        df_prod[c] = pd.to_numeric(df_prod[c], errors="coerce")
    df_prod = df_prod.reset_index(drop=True)

    # ---- Mensal (cabeçalho em 2 linhas; vírus a partir da coluna 4, em pares n / %)
    bruto = pd.read_excel(xls, sheet_name="Mensal", header=None)
    if bruto.shape[0] < 3 or bruto.shape[1] < 6:
        raise ValueError("A aba Mensal está menor que o esperado (layout do relatório mudou?).")
    nomes = pd.Series(bruto.iloc[0].values).ffill().values

    linhas = []
    for idx in range(2, len(bruto)):
        linha = bruto.iloc[idx]
        mes = linha.iloc[0]
        if pd.isna(mes):
            continue
        mes = _rotulo_mes(mes)
        if mes.upper() == "TOTAL":
            continue
        for c in range(4, len(linha), 2):
            virus = nomes[c]
            if pd.isna(virus):
                continue
            linhas.append({
                "Mês": mes,
                "Vírus": str(virus).strip(),
                "Casos (n)": linha.iloc[c],
                "_taxa_bruta": linha.iloc[c + 1] if (c + 1) < len(linha) else np.nan,
            })

    df_virus = pd.DataFrame(linhas, columns=["Mês", "Vírus", "Casos (n)", "_taxa_bruta"])
    df_virus["Casos (n)"] = pd.to_numeric(df_virus["Casos (n)"], errors="coerce").fillna(0).astype(int)
    df_virus[COL_TAXA] = _normalizar_taxas(df_virus["_taxa_bruta"])
    df_virus = df_virus.drop(columns="_taxa_bruta")
    return df_prod, df_virus


def media_ponderada(valores, pesos):
    """Média de `valores` ponderada por `pesos`; sem pesos válidos, cai na média simples."""
    v = pd.to_numeric(valores, errors="coerce")
    w = pd.to_numeric(pesos, errors="coerce").fillna(0)
    ok = v.notna() & (w > 0)
    if ok.any():
        return float((v[ok] * w[ok]).sum() / w[ok].sum())
    return float(v.mean()) if v.notna().any() else float("nan")


def indicadores_prod(df_prod):
    """KPIs e prazos agregados sobre todos os meses presentes em df_prod."""
    pesos = df_prod[COL_N]
    return {
        "liberados": int(pesos.fillna(0).sum()),
        "envio": media_ponderada(df_prod[COL_ENVIO], pesos),
        "analise": media_ponderada(df_prod[COL_ANALISE], pesos),
        "liberacao": media_ponderada(df_prod[COL_LIBERACAO], pesos),
        "sla": {rotulo: int(df_prod[col].fillna(0).sum()) for rotulo, col in COLS_SLA.items()},
    }


def agregar_virus(df_prod, df_virus):
    """Soma os casos por vírus (todos os meses) e pondera a taxa de detecção pelo nº de liberados do mês.

    Devolve (tabela, sem_peso). `sem_peso` é True se algum mês da aba Mensal não foi
    encontrado na aba Produtividade (a taxa cai, nesse caso, em média simples).
    """
    pesos = df_prod[["Mês", COL_N]]
    base = df_virus.merge(pesos, on="Mês", how="left")
    sem_peso = bool(base[COL_N].isna().any()) if not base.empty else False
    linhas = []
    for virus, g in base.groupby("Vírus", sort=False):
        linhas.append({
            "Vírus": virus,
            "Casos (n)": int(g["Casos (n)"].sum()),
            COL_TAXA: round(media_ponderada(g[COL_TAXA], g[COL_N]), 2),
        })
    tabela = pd.DataFrame(linhas, columns=["Vírus", "Casos (n)", COL_TAXA])
    tabela = tabela.sort_values("Casos (n)", ascending=False, kind="stable").reset_index(drop=True)
    return tabela, sem_peso
