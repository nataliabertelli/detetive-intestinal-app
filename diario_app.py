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
st.set_page_config(page_title="Diário Intestinal V19", page_icon="💩", layout="wide")
st.title("💩 Rastreador de Saúde")
FUSO_BR = pytz.timezone('America/Sao_Paulo')

# --- 2. CONFIGURAÇÃO GOOGLE SHEETS ---
NOME_PLANILHA = "Diario_Intestinal_DB" 

# Listas de Backup
LISTA_ALIM_BACKUP = ['ARROZ', 'FEIJÃO', 'OVO', 'FRANGO', 'CAFÉ', 'BANANA', 'GLÚTEN', 'LACTOSE', 'FRITURA']
LISTA_SINT_BACKUP = ['Estufamento', 'Gases', 'Cólica', 'Dor Abdominal']
LISTA_REMEDIOS_COMUNS = ['Buscopan', 'Simeticona', 'Probiótico', 'Enzima Lactase']

# Componentes Especiais para Análise
LISTA_COMPONENTES = ['GLÚTEN', 'LACTOSE', 'FRITURA', 'AÇÚCAR', 'CAFEÍNA', 'ÁLCOOL', 'LEITE DE VACA']

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
        
        vals_alim = sheet.col_values(1)[1:]
        vals_sint = sheet.col_values(2)[1:]
        
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
        receitas = {}
        for row in records:
            if row['NomeReceita']:
                ingreds = [x.strip().upper() for x in row['Ingredientes'].split(',')]
                receitas[row['NomeReceita'].upper()] = ingreds
        return receitas, sheet
    except:
        return {}, None

def cadastrar_novos_itens_automaticamente(novos_itens, tipo, sheet_config, lista_atual):
    if not novos_itens or not sheet_config: return
    
    itens_para_add = []
    for item in novos_itens:
        item_clean = item.strip().upper() if tipo == 'Alimentos' else item.strip().title()
        if item_clean and item_clean not in lista_atual:
            itens_para_add.append([item_clean])
            lista_atual.append(item_clean)
    
    if itens_para_add:
        col_idx = 1 if tipo == 'Alimentos' else 2
        col_values = sheet_config.col_values(col_idx)
        primeira_vazia = len(col_values) + 1
        
        sheet_config.update(
            range_name=f"{chr(64+col_idx)}{primeira_vazia}", 
            values=itens_para_add
        )
        if tipo == 'Alimentos':
            wb = sheet_config.spreadsheet
            sheet_dados = wb.sheet1
            headers = sheet_dados.row_values(1)
            novos_headers = [i[0] for i in itens_para_add if i[0] not in headers]
            
            if novos_headers:
                col_atual = len(headers)
                if col_atual + len(novos_headers) > sheet_dados.col_count:
                    sheet_dados.add_cols(5)
                cell_range = f"{gspread.utils.rowcol_to_a1(1, col_atual + 1)}:{gspread.utils.rowcol_to_a1(1, col_atual + len(novos_headers))}"
                sheet_dados.update(cell_range, [novos_headers])

def carregar_dados_nuvem():
    workbook = conectar_google_sheets()
    sheet = workbook.sheet1
    lista_alim, lista_sint, _ = gerenciar_listas_config(workbook)
    receitas, _ = obter_receitas(workbook)
    
    lista_alim_com_receitas = sorted(list(set(lista_alim + list(receitas.keys()))))
    
    try:
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if df.empty: return pd.DataFrame(), lista_alim_com_receitas, lista_sint, receitas

        cols_alim = [c for c in df.columns if c in lista_alim]
        for col in cols_alim: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
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
        
        return df_cron, lista_alim_com_receitas, lista_sint, receitas
    except Exception as e:
        st.error(f"Erro dados: {e}")
        return pd.DataFrame(), lista_alim_com_receitas, lista_sint, receitas

df, lista_alimentos_display, lista_sintomas_display, receitas_dict = carregar_dados_nuvem()

# --- 4. INTERFACE ---
aba_inserir, aba_receitas, aba_analise, aba_geral = st.tabs(["📥 Inserir", "🧑‍🍳 Receitas", "📊 Detetive", "📈 Geral"])

# --- ABA: RECEITAS (CADASTRO MESTRE) ---
with aba_receitas:
    st.header("Cadastrar Receita / Prato")
    st.info("Aqui você define do que é feito o seu prato. O sistema vai 'explodir' esses ingredientes automaticamente quando você comer.")
    
    with st.form("form_receita"):
        nome_rec = st.text_input("Nome do Prato (TÍTULO)").upper()
        st.caption("Ex: PÃO DE QUEIJO, BOLO DE CENOURA")
        
        c_ing, c_prop = st.columns([2, 1])
        
        with c_ing:
            # Filtra a lista para não mostrar receitas dentro de receitas (evita loop infinito simples)
            ingreds_rec = st.multiselect("Ingredientes Principais", [x for x in lista_alimentos_display if x not in receitas_dict])
            novos_ingreds = st.text_input("Ingredientes não listados (separar por vírgula)").upper()
        
        with c_prop:
            st.markdown("**Contém:**")
            # Checkboxes para componentes
            props_selecionadas = []
            for comp in LISTA_COMPONENTES:
                if st.checkbox(comp, key=f"rec_{comp}"):
                    props_selecionadas.append(comp)
        
        if st.form_submit_button("💾 Salvar Definição"):
            if nome_rec:
                wb = conectar_google_sheets()
                lista_alim, _, sheet_cfg = gerenciar_listas_config(wb)
                
                # Novos ingredientes digitados
                lista_novos = [x.strip() for x in novos_ingreds.split(',') if x.strip()]
                
                # IMPORTANTE: Cadastra os componentes (Gluten, etc) como "Alimentos" se ainda não existirem
                # Isso garante que eles tenham coluna na planilha para serem contados
                cadastrar_novos_itens_automaticamente(lista_novos + props_selecionadas, 'Alimentos', sheet_cfg, lista_alim)
                
                final_ingreds = ingreds_rec + lista_novos + props_selecionadas
                str_ingreds = ", ".join(final_ingreds)
                
                _, sheet_rec = obter_receitas(wb)
                sheet_rec.append_row([nome_rec, str_ingreds])
                st.success(f"Receita '{nome_rec}' salva com: {str_ingreds}")
            else:
                st.error("Digite o nome do prato.")

# --- ABA: INSERIR ---
with aba_inserir:
    st.header("Novo Registro")
    agora_br = datetime.now(FUSO_BR)
    
    with st.form("form_entrada_v19"):
        c1, c2 = st.columns(2)
        with c1: data_input = st.date_input("📅 Data", agora_br)
        with c2: hora_input = st.time_input("🕒 Hora", agora_br)

        st.divider()
        st.subheader("💩 Escala de Bristol")
        opcoes_bristol = ["Nenhum"] + [1, 2, 3, 4, 5, 6, 7]
        bristol_escolhido = st.radio("Selecione:", opcoes_bristol, horizontal=True, index=0, label_visibility="collapsed")
        
        st.divider()

        with st.expander("🍎 Alimentação", expanded=True):
            st.info("Selecione alimentos simples ou receitas cadastradas.")
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
            c_new, c_comp = st.columns(2)
            with c_new:
                st.markdown("**Não achou? Digite:**")
                novos_alimentos_txt = st.text_input("Novos Alimentos (separe por vírgula)", placeholder="Ex: Cuscuz, Tapioca").upper()
            
            with c_comp:
                st.markdown("**Rastreadores / Alérgenos do Dia:**")
                st.caption("Marque se comeu algo fora da lista que contenha:")
                # Multiselect para componentes avulsos do dia
                comps_dia = st.multiselect("Adicionar ao registro:", LISTA_COMPONENTES)

        with st.expander("💊 Sintomas & Corpo"):
            meds_sel = st.multiselect("Medicamentos:", LISTA_REMEDIOS_COMUNS)
            st.markdown("**Sintomas:**")
            sintomas_sel = st.multiselect("Lista:", lista_sintomas_display)
            novos_sintomas_txt = st.text_input("Novo Sintoma:", placeholder="Ex: Enxaqueca").title()
            st.markdown("---")
            circunf = st.number_input("📏 Cintura (cm)", min_value=0.0, step=0.1, format="%.1f")

        st.divider()
        notas_input = st.text_area("Notas", placeholder="Obs...")
        
        if st.form_submit_button("💾 SALVAR REGISTRO", type="primary", use_container_width=True):
            wb = conectar_google_sheets()
            lista_alim, lista_sint, sheet_cfg = gerenciar_listas_config(wb)
            
            # 1. PROCESSA NOVOS CADASTROS
            novos_alim_list = [x.strip() for x in novos_alimentos_txt.split(',') if x.strip()]
            novos_sint_list = [x.strip() for x in novos_sintomas_txt.split(',') if x.strip()]
            
            # Garante que os componentes (Gluten, etc) selecionados no dia existam como colunas
            cadastrar_novos_itens_automaticamente(novos_alim_list + comps_dia, 'Alimentos', sheet_cfg, lista_alim)
            cadastrar_novos_itens_automaticamente(novos_sint_list, 'Sintomas', sheet_cfg, lista_sint)
            
            # 2. PREPARA DADOS
            sheet = wb.sheet1
            headers = sheet.row_values(1)
            nova_linha = []
            
            sintomas_finais = sintomas_sel + novos_sint_list
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
            
            # 3. LÓGICA DE RECEITAS + COMPONENTES
            ingredientes_processados = {} 
            
            def processar_item(item, nivel):
                if item in receitas_dict:
                    # Explode receita (que já inclui os componentes como Gluten salvos nela)
                    for ingrediente in receitas_dict[item]:
                        ingredientes_processados[ingrediente] = max(ingredientes_processados.get(ingrediente, 0), nivel)
                else:
                    ingredientes_processados[item] = max(ingredientes_processados.get(item, 0), nivel)

            for item in sel_pouco: processar_item(item, 1)
            for item in sel_medio: processar_item(item, 2)
            for item in sel_muito: processar_item(item, 3)
            for item in novos_alim_list: processar_item(item, 2)
            
            # Adiciona os componentes marcados manualmente no dia (Gluten, Fritura...)
            # Consideramos nível 2 (Normal) para esses marcadores
            for comp in comps_dia:
                ingredientes_processados[comp] = max(ingredientes_processados.get(comp, 0), 2)

            for ingred, nivel in ingredientes_processados.items():
                valores_input[ingred] = nivel
            
            # 4. SALVA
            headers = sheet.row_values(1) # Re-lê headers atualizados
            for h in headers:
                if h in valores_input: nova_linha.append(valores_input[h])
                elif h in lista_alim: nova_linha.append(valores_input.get(h, 0))
                else: nova_linha.append("")
            
            sheet.append_row(nova_linha)
            st.success("✅ Salvo!")
            st.cache_data.clear()
            st.rerun()

# --- ABA: GERAL ---
with aba_geral:
    st.header("Resumo Rápido")
    if not df.empty:
        for idx, row in df.head(10).iterrows():
            with st.container():
                bristol_txt = f"💩 B{int(row['Escala de Bristol'])}" if row['Escala de Bristol'] > 0 else ""
                st.markdown(f"**{row['Data']}** {bristol_txt} | {row['Características']}")
                
                comidos = []
                for c in df.columns:
                    # Mostra alimentos e também os componentes (Gluten, etc) se foram marcados > 0
                    if (c in lista_alimentos_display or c in LISTA_COMPONENTES) and row.get(c, 0) > 0:
                        comidos.append(f"{c}")
                st.caption(", ".join(comidos))
                st.divider()

with aba_analise:
    st.info("Acesse a aba 'Geral' ou versões anteriores para análise profunda.")