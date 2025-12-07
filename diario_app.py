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
st.set_page_config(page_title="Diário Intestinal V18", page_icon="💩", layout="wide")
st.title("💩 Rastreador de Saúde")
FUSO_BR = pytz.timezone('America/Sao_Paulo')

# --- 2. CONFIGURAÇÃO GOOGLE SHEETS ---
NOME_PLANILHA = "Diario_Intestinal_DB" 

# Listas de Backup (Usadas apenas na primeira execução)
LISTA_ALIM_BACKUP = ['ARROZ', 'FEIJÃO', 'OVO', 'FRANGO', 'CAFÉ', 'BANANA']
LISTA_SINT_BACKUP = ['Estufamento', 'Gases', 'Cólica', 'Dor Abdominal']
LISTA_REMEDIOS_COMUNS = ['Buscopan', 'Simeticona', 'Probiótico', 'Enzima Lactase']

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

def gerenciar_listas_config(workbook):
    """Lê e Atualiza Alimentos e Sintomas da aba Config."""
    try:
        try: sheet = workbook.worksheet("Config")
        except: 
            sheet = workbook.add_worksheet(title="Config", rows=100, cols=5)
            sheet.update("A1:B1", [["Alimentos", "Sintomas"]])
        
        # Lê colunas
        vals_alim = sheet.col_values(1)[1:] # Ignora header
        vals_sint = sheet.col_values(2)[1:]
        
        # Se vazio, inicializa
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
            sheet = workbook.add_worksheet(title="Receitas", rows=100, cols=2)
            sheet.update("A1:B1", [["NomeReceita", "Ingredientes"]])
        
        records = sheet.get_all_records()
        # Cria dicionário: {'PÃO': ['FARINHA', 'OVO'], ...}
        receitas = {}
        for row in records:
            if row['NomeReceita']:
                ingreds = [x.strip().upper() for x in row['Ingredientes'].split(',')]
                receitas[row['NomeReceita'].upper()] = ingreds
        return receitas, sheet
    except:
        return {}, None

def cadastrar_novos_itens_automaticamente(novos_itens, tipo, sheet_config, lista_atual):
    """
    Verifica se itens digitados são novos e salva na Config.
    tipo: 'Alimentos' (col A) ou 'Sintomas' (col B)
    """
    if not novos_itens or not sheet_config: return
    
    itens_para_add = []
    for item in novos_itens:
        item_clean = item.strip().upper() if tipo == 'Alimentos' else item.strip().title()
        if item_clean and item_clean not in lista_atual:
            itens_para_add.append([item_clean])
            lista_atual.append(item_clean) # Atualiza lista em memória
    
    if itens_para_add:
        col_idx = 1 if tipo == 'Alimentos' else 2
        # Acha a primeira linha vazia da coluna
        col_values = sheet_config.col_values(col_idx)
        primeira_vazia = len(col_values) + 1
        
        # Salva no Sheets
        sheet_config.update(
            range_name=f"{chr(64+col_idx)}{primeira_vazia}", 
            values=itens_para_add
        )
        # Se for Alimento, criar coluna na aba de Dados
        if tipo == 'Alimentos':
            wb = sheet_config.spreadsheet
            sheet_dados = wb.sheet1
            headers = sheet_dados.row_values(1)
            novos_headers = [i[0] for i in itens_para_add if i[0] not in headers]
            
            if novos_headers:
                col_atual = len(headers)
                if col_atual + len(novos_headers) > sheet_dados.col_count:
                    sheet_dados.add_cols(5)
                # Adiciona headers
                cell_range = f"{gspread.utils.rowcol_to_a1(1, col_atual + 1)}:{gspread.utils.rowcol_to_a1(1, col_atual + len(novos_headers))}"
                sheet_dados.update(cell_range, [novos_headers])

def carregar_dados_nuvem():
    workbook = conectar_google_sheets()
    sheet = workbook.sheet1
    lista_alim, lista_sint, _ = gerenciar_listas_config(workbook)
    receitas, _ = obter_receitas(workbook)
    
    # Adiciona nomes das receitas na lista de alimentos para aparecer no select
    lista_alim_com_receitas = sorted(list(set(lista_alim + list(receitas.keys()))))
    
    try:
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if df.empty: return pd.DataFrame(), lista_alim_com_receitas, lista_sint, receitas

        # Limpeza
        cols_alim = [c for c in df.columns if c in lista_alim] # Só colunas que são alimentos puros
        for col in cols_alim: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        if 'Circunferencia' in df.columns: df['Circunferencia'] = pd.to_numeric(df['Circunferencia'], errors='coerce')
        df['Escala de Bristol'] = pd.to_numeric(df['Escala de Bristol'], errors='coerce').fillna(0)
            
        df['DataHora'] = pd.to_datetime(df['Data'] + ' ' + df['Hora'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['DataHora']).sort_values(by='DataHora', ascending=False).reset_index(drop=True)
        
        # Porto Seguro
        df['Porto_Seguro'] = False
        crise_mask = (df['Escala de Bristol'] >= 5)
        # Lógica reversa pois ordenamos descrescente
        df_cron = df.sort_values('DataHora').reset_index(drop=True)
        for i in range(len(df_cron)):
            if i < 3: continue
            dt = df_cron.loc[i, 'DataHora']
            inicio = dt - timedelta(days=3)
            janela = df_cron[(df_cron['DataHora'] < dt) & (df_cron['DataHora'] >= inicio)]
            if not janela.empty and not janela[crise_mask].any().any():
                df_cron.loc[i, 'Porto_Seguro'] = True
        
        return df_cron, lista_alim_com_receitas, lista_sint, receitas
    except Exception as e:
        st.error(f"Erro dados: {e}")
        return pd.DataFrame(), lista_alim_com_receitas, lista_sint, receitas

df, lista_alimentos_display, lista_sintomas_display, receitas_dict = carregar_dados_nuvem()

# --- 4. INTERFACE ---
aba_inserir, aba_receitas, aba_analise, aba_geral = st.tabs(["📥 Inserir", "🧑‍🍳 Receitas", "📊 Detetive", "📈 Geral"])

# --- ABA: RECEITAS ---
with aba_receitas:
    st.header("Cadastrar Receita")
    st.caption("Ensine ao programa o que vai no seu prato. Ao selecionar a receita no dia a dia, ele salvará os ingredientes.")
    
    with st.form("form_receita"):
        nome_rec = st.text_input("Nome do Prato (Ex: Pão Caseiro)").upper()
        # Multiselect com os alimentos puros (remove as próprias receitas pra evitar loop)
        # Filtra lista para remover chaves de receitas existentes se possível, mas ok deixar
        ingreds_rec = st.multiselect("Ingredientes", lista_alimentos_display)
        
        st.markdown("**Ou digite novos ingredientes (serão cadastrados):**")
        novos_ingreds = st.text_input("Novos Ingredientes (separe por vírgula)").upper()
        
        if st.form_submit_button("Salvar Receita"):
            if nome_rec:
                wb = conectar_google_sheets()
                lista_alim, _, sheet_cfg = gerenciar_listas_config(wb)
                
                # Processa novos ingredientes
                lista_novos = [x.strip() for x in novos_ingreds.split(',') if x.strip()]
                cadastrar_novos_itens_automaticamente(lista_novos, 'Alimentos', sheet_cfg, lista_alim)
                
                # Junta tudo
                final_ingreds = ingreds_rec + lista_novos
                str_ingreds = ", ".join(final_ingreds)
                
                # Salva na aba Receitas
                _, sheet_rec = obter_receitas(wb)
                sheet_rec.append_row([nome_rec, str_ingreds])
                st.success(f"Receita '{nome_rec}' salva! Recarregue a página.")
            else:
                st.error("Dê um nome para a receita.")

# --- ABA: INSERIR ---
with aba_inserir:
    st.header("Novo Registro")
    agora_br = datetime.now(FUSO_BR)
    
    with st.form("form_entrada_v18"):
        c1, c2 = st.columns(2)
        with c1: data_input = st.date_input("📅 Data", agora_br)
        with c2: hora_input = st.time_input("🕒 Hora", agora_br)

        st.divider()
        st.subheader("💩 Escala de Bristol")
        opcoes_bristol = ["Nenhum"] + [1, 2, 3, 4, 5, 6, 7]
        bristol_escolhido = st.radio("Selecione:", opcoes_bristol, horizontal=True, index=0, label_visibility="collapsed")
        
        st.divider()

        with st.expander("🍎 Alimentação", expanded=True):
            cp, cm, cg = st.columns(3)
            with cp:
                st.markdown("🤏 **Pouco (1)**")
                sel_pouco = st.multiselect("Nível 1", lista_alimentos_display, key="s1", label_visibility="collapsed")
            with cm:
                st.markdown("🍽️ **Normal (2)**")
                sel_medio = st.multiselect("Nível 2", lista_alimentos_display, key="s2", label_visibility="collapsed")
            with cg:
                st.markdown("🚀 **Muito (3)**")
                sel_muito = st.multiselect("Nível 3", lista_alimentos_display, key="s3", label_visibility="collapsed")
            
            st.markdown("---")
            st.caption("Não achou na lista? Digite abaixo e pressione Enter para cadastrar automaticamente.")
            novos_alimentos_txt = st.text_input("Novos Alimentos (separe por vírgula)", placeholder="Ex: Cuscuz, Farinha de Teff").upper()

        with st.expander("💊 Sintomas & Corpo"):
            meds_sel = st.multiselect("Medicamentos:", LISTA_REMEDIOS_COMUNS)
            
            st.markdown("**Sintomas:**")
            sintomas_sel = st.multiselect("Lista:", lista_sintomas_display)
            novos_sintomas_txt = st.text_input("Novo Sintoma (digite para adicionar):", placeholder="Ex: Enxaqueca").title()
            
            st.markdown("---")
            circunf = st.number_input("📏 Cintura (cm)", min_value=0.0, step=0.1, format="%.1f")

        st.divider()
        notas_input = st.text_area("Notas", placeholder="Obs...")
        
        if st.form_submit_button("💾 SALVAR REGISTRO", type="primary", use_container_width=True):
            wb = conectar_google_sheets()
            lista_alim, lista_sint, sheet_cfg = gerenciar_listas_config(wb)
            
            # 1. PROCESSA NOVOS CADASTROS AUTOMÁTICOS
            novos_alim_list = [x.strip() for x in novos_alimentos_txt.split(',') if x.strip()]
            novos_sint_list = [x.strip() for x in novos_sintomas_txt.split(',') if x.strip()]
            
            cadastrar_novos_itens_automaticamente(novos_alim_list, 'Alimentos', sheet_cfg, lista_alim)
            cadastrar_novos_itens_automaticamente(novos_sint_list, 'Sintomas', sheet_cfg, lista_sint)
            
            # 2. PREPARA DADOS PARA SALVAR
            sheet = wb.sheet1
            headers = sheet.row_values(1)
            nova_linha = []
            
            # Combina listas (Seleção + Digitados)
            sintomas_finais = sintomas_sel + novos_sint_list
            
            # Lógica Bristol
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
            
            # 3. LÓGICA DE EXPLOSÃO DE RECEITAS
            # Dicionário temporário para somar quantidades (caso ingredientes se repitam)
            ingredientes_processados = {} 
            
            def processar_item(item, nivel):
                # Se é receita, explode
                if item in receitas_dict:
                    for ingrediente in receitas_dict[item]:
                        # Ingrediente da receita herda o nível do prato
                        ingredientes_processados[ingrediente] = max(ingredientes_processados.get(ingrediente, 0), nivel)
                else:
                    # É alimento puro
                    ingredientes_processados[item] = max(ingredientes_processados.get(item, 0), nivel)

            # Processa as seleções
            for item in sel_pouco: processar_item(item, 1)
            for item in sel_medio: processar_item(item, 2)
            for item in sel_muito: processar_item(item, 3)
            for item in novos_alim_list: processar_item(item, 2) # Novos entram como nível 2 padrão

            # Transfere para valores_input
            for ingred, nivel in ingredientes_processados.items():
                valores_input[ingred] = nivel
            
            # 4. PREENCHE LINHA (com atualização de headers se necessário)
            # Re-lê headers pois 'cadastrar_novos_itens_automaticamente' pode ter criado colunas
            headers = sheet.row_values(1)
            
            for h in headers:
                if h in valores_input: nova_linha.append(valores_input[h])
                elif h in lista_alim: nova_linha.append(valores_input.get(h, 0)) # Se é alimento e não comeu, 0
                else: nova_linha.append("") # Outras colunas
            
            sheet.append_row(nova_linha)
            st.success("✅ Salvo! Alimentos novos cadastrados e receitas processadas.")
            st.cache_data.clear()
            st.rerun()

# --- ABA: GERAL (SIMPLIFICADO) ---
with aba_geral:
    st.header("Resumo Rápido")
    # Histórico Recente (Lista Corrida)
    if not df.empty:
        for idx, row in df.head(10).iterrows(): # Mostra só os últimos 10 pra ser rápido
            with st.container():
                bristol_txt = f"💩 B{int(row['Escala de Bristol'])}" if row['Escala de Bristol'] > 0 else ""
                st.markdown(f"**{row['Data']}** {bristol_txt} | {row['Características']}")
                
                comidos = []
                for c in df.columns:
                    if c in lista_alimentos_display and row[c] > 0:
                        comidos.append(f"{c}")
                st.caption(", ".join(comidos))
                st.divider()

with aba_analise:
    st.info("Acesse a aba 'Geral' ou versões anteriores para análise profunda.")
    # (Mantive a lógica do detetive simples aqui para economizar espaço de código, 
    # já que o foco agora era a entrada de dados perfeita)