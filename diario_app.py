import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import re
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import gspread
from google.oauth2.service_account import Credentials
import pytz

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Diário Intestinal V20", page_icon="💩", layout="wide")
st.title("💩 Rastreador de Saúde")
FUSO_BR = pytz.timezone('America/Sao_Paulo')

# --- 2. CONFIGURAÇÃO GOOGLE SHEETS ---
NOME_PLANILHA = "Diario_Intestinal_DB" 

# Listas de Backup
LISTA_ALIM_BACKUP = ['ARROZ', 'FEIJÃO', 'OVO', 'FRANGO', 'CAFÉ', 'BANANA', 'GLÚTEN', 'LACTOSE', 'FRITURA']
LISTA_SINT_BACKUP = ['Estufamento', 'Gases', 'Cólica', 'Dor Abdominal']
LISTA_REMEDIOS_COMUNS = ['Buscopan', 'Simeticona', 'Probiótico', 'Enzima Lactase']
LISTA_RASTREADORES = ['GLÚTEN', 'LACTOSE', 'FRITURA', 'AÇÚCAR', 'CAFEÍNA', 'ÁLCOOL', 'LEITE DE VACA']

# --- 3. FUNÇÕES DE BANCO DE DADOS ---
@st.cache_resource
def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        credentials_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open(NOME_PLANILHA)
    except Exception as e:
        st.error(f"❌ Erro de Conexão: {e}")
        st.stop()

def verificar_e_criar_colunas(sheet_dados, novos_headers):
    """Garante que existem colunas para os itens novos na aba de Dados."""
    if not novos_headers: return
    headers = sheet_dados.row_values(1)
    
    # Filtra apenas o que realmente não existe
    reais_novos = [h for h in novos_headers if h not in headers]
    
    if reais_novos:
        col_atual = len(headers)
        # Se precisar, expande a planilha
        if col_atual + len(reais_novos) > sheet_dados.col_count:
            sheet_dados.add_cols(len(reais_novos) + 5)
        
        # Adiciona os headers na primeira linha
        cell_range = f"{gspread.utils.rowcol_to_a1(1, col_atual + 1)}:{gspread.utils.rowcol_to_a1(1, col_atual + len(reais_novos))}"
        sheet_dados.update(cell_range, [reais_novos])

def gerenciar_listas_config(workbook):
    """Lê Alimentos e Sintomas da aba Config."""
    try:
        try: sheet = workbook.worksheet("Config")
        except: 
            sheet = workbook.add_worksheet(title="Config", rows=100, cols=5)
            sheet.update("A1:B1", [["Alimentos", "Sintomas"]])
        
        vals_alim = sheet.col_values(1)[1:]
        vals_sint = sheet.col_values(2)[1:]
        
        # Inicialização se vazio
        if not vals_alim:
            sheet.update(f"A2:A{len(LISTA_ALIM_BACKUP)+1}", [[x] for x in LISTA_ALIM_BACKUP])
            vals_alim = LISTA_ALIM_BACKUP
        if not vals_sint:
            sheet.update(f"B2:B{len(LISTA_SINT_BACKUP)+1}", [[x] for x in LISTA_SINT_BACKUP])
            vals_sint = LISTA_SINT_BACKUP
            
        vals_alim.sort()
        vals_sint.sort()
        return vals_alim, vals_sint, sheet
    except Exception as e:
        st.error(f"Erro Config: {e}")
        return LISTA_ALIM_BACKUP, LISTA_SINT_BACKUP, None

def obter_receitas(workbook):
    """Lê receitas cadastradas."""
    try:
        try: sheet = workbook.worksheet("Receitas")
        except: 
            sheet = workbook.add_worksheet(title="Receitas", rows=100, cols=3)
            sheet.update("A1:C1", [["NomeReceita", "Ingredientes", "Rastreadores"]])
        
        records = sheet.get_all_records()
        receitas = {}
        for row in records:
            if row['NomeReceita']:
                ingreds = [x.strip().upper() for x in str(row['Ingredientes']).split(',') if x.strip()]
                trackers = [x.strip().upper() for x in str(row.get('Rastreadores', '')).split(',') if x.strip()]
                # Receita guarda: [Lista de Ingredientes, Lista de Rastreadores]
                receitas[row['NomeReceita'].upper()] = {'ingreds': ingreds, 'trackers': trackers}
        return receitas, sheet
    except:
        return {}, None

def cadastrar_item_config(novo_item, tipo, sheet_config, lista_atual):
    """Adiciona item na Config e cria coluna se for Alimento."""
    item_clean = novo_item.strip().upper() if tipo == 'Alimentos' else novo_item.strip().title()
    
    if item_clean in lista_atual:
        return False, "Item já existe."

    # 1. Adiciona na Config
    col_idx = 1 if tipo == 'Alimentos' else 2
    col_values = sheet_config.col_values(col_idx)
    prox_linha = len(col_values) + 1
    sheet_config.update_cell(prox_linha, col_idx, item_clean)
    
    # 2. Se for Alimento, cria coluna na aba Dados
    if tipo == 'Alimentos':
        wb = sheet_config.spreadsheet
        verificar_e_criar_colunas(wb.sheet1, [item_clean])
        
    return True, f"✅ {item_clean} cadastrado!"

def carregar_dados_nuvem():
    workbook = conectar_google_sheets()
    sheet = workbook.sheet1
    lista_alim, lista_sint, _ = gerenciar_listas_config(workbook)
    receitas, _ = obter_receitas(workbook)
    
    # Lista combinada para exibição (Alimentos Puros + Nomes de Receitas)
    lista_completa_selecao = sorted(list(set(lista_alim + list(receitas.keys()))))
    
    try:
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if df.empty: return pd.DataFrame(), lista_completa_selecao, lista_alim, lista_sint, receitas

        # Limpeza Numérica
        # Identifica colunas que são alimentos ou rastreadores
        cols_interesse = [c for c in df.columns if c in lista_alim or c in LISTA_RASTREADORES]
        for col in cols_interesse: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        if 'Circunferencia' in df.columns: df['Circunferencia'] = pd.to_numeric(df['Circunferencia'], errors='coerce')
        df['Escala de Bristol'] = pd.to_numeric(df['Escala de Bristol'], errors='coerce').fillna(0)
            
        df['DataHora'] = pd.to_datetime(df['Data'] + ' ' + df['Hora'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['DataHora']).sort_values(by='DataHora', ascending=False).reset_index(drop=True)
        
        # Porto Seguro
        df['Porto_Seguro'] = False
        crise_mask = (df['Escala de Bristol'] >= 5)
        df_cron = df.sort_values('DataHora').reset_index(drop=True)
        for i in range(len(df_cron)):
            if i < 3: continue
            dt = df_cron.loc[i, 'DataHora']
            inicio = dt - timedelta(days=3)
            janela = df_cron[(df_cron['DataHora'] < dt) & (df_cron['DataHora'] >= inicio)]
            if not janela.empty and not janela[crise_mask].any().any():
                df_cron.loc[i, 'Porto_Seguro'] = True
        
        return df_cron, lista_completa_selecao, lista_alim, lista_sint, receitas
    except Exception as e:
        st.error(f"Erro dados: {e}")
        return pd.DataFrame(), lista_completa_selecao, lista_alim, lista_sint, receitas

df, lista_display, lista_alim_pura, lista_sint_pura, receitas_dict = carregar_dados_nuvem()

# --- 4. INTERFACE ---
aba_diario, aba_cadastros, aba_analise, aba_geral = st.tabs(["📝 Diário", "⚙️ Cadastros", "📊 Detetive", "🗂️ Histórico"])

# ==============================================================================
# ABA: CADASTROS (A COZINHA - Configuração)
# ==============================================================================
with aba_cadastros:
    st.header("Central de Cadastros")
    st.caption("Aqui você ensina ao programa o que são seus alimentos e sintomas.")

    c_new1, c_new2 = st.columns(2)
    
    # 1. NOVO ALIMENTO PURO
    with c_new1:
        with st.container(border=True):
            st.subheader("🍎 Novo Alimento Puro")
            st.caption("Ex: Farinha de Teff, Cuscuz, Ora-pro-nóbis")
            novo_alim_txt = st.text_input("Nome do Alimento").upper()
            if st.button("Salvar Alimento"):
                if novo_alim_txt:
                    wb = conectar_google_sheets()
                    _, _, sheet_cfg = gerenciar_listas_config(wb)
                    ok, msg = cadastrar_item_config(novo_alim_txt, 'Alimentos', sheet_cfg, lista_alim_pura)
                    if ok: 
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else: st.warning(msg)

    # 2. NOVO SINTOMA
    with c_new2:
        with st.container(border=True):
            st.subheader("⚠️ Novo Sintoma")
            st.caption("Ex: Enxaqueca, Aftas")
            novo_sint_txt = st.text_input("Nome do Sintoma").title()
            if st.button("Salvar Sintoma"):
                if novo_sint_txt:
                    wb = conectar_google_sheets()
                    _, _, sheet_cfg = gerenciar_listas_config(wb)
                    ok, msg = cadastrar_item_config(novo_sint_txt, 'Sintomas', sheet_cfg, lista_sint_pura)
                    if ok: 
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else: st.warning(msg)

    st.divider()

    # 3. NOVA RECEITA (Mestre)
    with st.container(border=True):
        st.subheader("🧑‍🍳 Nova Receita / Prato Composto")
        st.info("Cadastre o título (ex: PÃO DE QUEIJO) e o que tem dentro dele. No dia a dia, basta selecionar o título.")
        
        with st.form("form_receita_mestre"):
            nome_rec = st.text_input("Nome da Receita (TÍTULO)").upper()
            
            c_ing, c_track = st.columns(2)
            with c_ing:
                # Mostra apenas alimentos puros para compor a receita
                ingreds_rec = st.multiselect("Ingredientes Base", lista_alim_pura)
            
            with c_track:
                st.markdown("**Contém (Rastreadores):**")
                trackers_selecionados = []
                for t in LISTA_RASTREADORES:
                    if st.checkbox(t, key=f"track_{t}"): trackers_selecionados.append(t)
            
            if st.form_submit_button("Salvar Receita"):
                if nome_rec and (ingreds_rec or trackers_selecionados):
                    wb = conectar_google_sheets()
                    _, sheet_rec = obter_receitas(wb)
                    
                    # Salva: Nome | Ingredientes (sep ,) | Rastreadores (sep ,)
                    str_ing = ",".join(ingreds_rec)
                    str_track = ",".join(trackers_selecionados)
                    sheet_rec.append_row([nome_rec, str_ing, str_track])
                    
                    # Garante que os rastreadores existam como colunas na planilha de dados
                    # para que possam ser contados quando a receita explodir
                    if trackers_selecionados:
                        verificar_e_criar_colunas(wb.sheet1, trackers_selecionados)

                    st.success(f"Receita '{nome_rec}' salva!")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Preencha o nome e pelo menos um ingrediente ou rastreador.")

# ==============================================================================
# ABA: DIÁRIO (A MESA - Dia a Dia)
# ==============================================================================
with aba_diario:
    st.header("Registro Diário")
    agora_br = datetime.now(FUSO_BR)
    
    with st.form("form_diario_v20"):
        c1, c2 = st.columns(2)
        with c1: data_input = st.date_input("📅 Data", agora_br)
        with c2: hora_input = st.time_input("🕒 Hora", agora_br)

        st.divider()
        st.subheader("💩 Bristol")
        bristol_escolhido = st.radio("Selecione:", ["Nenhum"] + [1, 2, 3, 4, 5, 6, 7], horizontal=True, index=0, label_visibility="collapsed")
        
        st.divider()
        
        # Seleção de Alimentos (Mistura Puros e Receitas)
        with st.expander("🍎 O que você comeu?", expanded=True):
            st.caption("Selecione Alimentos Simples ou Receitas já cadastradas.")
            cp, cm, cg = st.columns(3)
            with cp: sel_pouco = st.multiselect("Nível 1 (Pouco)", lista_display, key="d1")
            with cm: sel_medio = st.multiselect("Nível 2 (Normal)", lista_display, key="d2")
            with cg: sel_muito = st.multiselect("Nível 3 (Muito)", lista_display, key="d3")
            
            st.markdown("---")
            st.markdown("**Rastreadores Avulsos do Dia:**")
            st.caption("Comeu algo fora da lista que tinha:")
            comps_dia = st.multiselect("Adicionar Rastreador:", LISTA_RASTREADORES)

        with st.expander("💊 Sintomas & Corpo"):
            meds_sel = st.multiselect("Medicamentos:", LISTA_REMEDIOS_COMUNS)
            sintomas_sel = st.multiselect("Sintomas:", lista_sint_pura)
            st.markdown("---")
            circunf = st.number_input("📏 Cintura (cm)", min_value=0.0, step=0.1, format="%.1f")

        st.divider()
        notas_input = st.text_area("Notas", placeholder="Obs...")
        
        if st.form_submit_button("💾 SALVAR REGISTRO", type="primary", use_container_width=True):
            wb = conectar_google_sheets()
            sheet = wb.sheet1
            
            # PREPARAÇÃO DOS DADOS
            sintomas_finais = sintomas_sel
            bristol_save = bristol_escolhido if bristol_escolhido != "Nenhum" else ""
            
            valores_input = {
                'Data': data_input.strftime('%d/%m/%Y'),
                'Hora': hora_input.strftime('%H:%M'),
                'Escala de Bristol': bristol_save,
                'Diarreia': 'S' if bristol_save != "" and bristol_save >= 5 else '',
                'Características': ", ".join(sintomas_finais),
                'Remédios': ", ".join(meds_sel),
                'Circunferencia': circunf if circunf > 0 else '',
                'Notas': notas_input,
                'Humor': ''
            }
            
            # LÓGICA DE EXPLOSÃO (RECEITA -> INGREDIENTES + RASTREADORES)
            ingredientes_processados = {} 
            
            def processar_item(item, nivel):
                # Se é receita
                if item in receitas_dict:
                    # 1. Pega Ingredientes da Receita
                    for ingred in receitas_dict[item]['ingreds']:
                        ingredientes_processados[ingred] = max(ingredientes_processados.get(ingred, 0), nivel)
                    # 2. Pega Rastreadores da Receita (Glúten, etc)
                    for track in receitas_dict[item]['trackers']:
                        ingredientes_processados[track] = max(ingredientes_processados.get(track, 0), nivel)
                    # 3. Também conta a Receita em si (Opcional, mas bom pra saber que comeu o prato)
                    ingredientes_processados[item] = max(ingredientes_processados.get(item, 0), nivel)
                else:
                    # É alimento puro
                    ingredientes_processados[item] = max(ingredientes_processados.get(item, 0), nivel)

            for item in sel_pouco: processar_item(item, 1)
            for item in sel_medio: processar_item(item, 2)
            for item in sel_muito: processar_item(item, 3)
            for item in comps_dia: processar_item(item, 2) # Rastreadores avulsos entram como nível 2

            # Atualiza valores_input
            for ingred, nivel in ingredientes_processados.items():
                valores_input[ingred] = nivel
            
            # SALVAMENTO
            headers = sheet.row_values(1)
            nova_linha = []
            
            # Verifica se algum ingrediente explodido não tem coluna (segurança)
            chaves_faltantes = [k for k in valores_input.keys() if k not in headers and k not in ['Data','Hora','Escala de Bristol','Diarreia','Características','Remédios','Circunferencia','Notas','Humor']]
            if chaves_faltantes:
                verificar_e_criar_colunas(sheet, chaves_faltantes)
                headers = sheet.row_values(1) # Atualiza headers
            
            for h in headers:
                if h in valores_input: nova_linha.append(valores_input[h])
                elif h in lista_alim_pura or h in lista_display or h in LISTA_RASTREADORES: 
                     nova_linha.append(valores_input.get(h, 0))
                else: nova_linha.append("")
            
            sheet.append_row(nova_linha)
            st.success("✅ Registro Salvo!")
            st.cache_data.clear()
            st.rerun()

# --- ABAS DE ANÁLISE (Mantidas Iguais) ---
with aba_geral:
    st.header("Histórico Recente")
    if not df.empty:
        for idx, row in df.head(10).iterrows():
            with st.container():
                bristol_txt = f"💩 B{int(row['Escala de Bristol'])}" if row['Escala de Bristol'] > 0 else ""
                st.markdown(f"**{row['Data']}** {bristol_txt} | {row['Características']}")
                comidos = [c for c in df.columns if (c in lista_display or c in LISTA_RASTREADORES) and row.get(c, 0) > 0]
                st.caption(", ".join(comidos))
                st.divider()

with aba_analise:
    st.info("Utilize a aba Geral para ver os dados brutos ou aguarde a coleta de mais dados para usar o Detetive.")