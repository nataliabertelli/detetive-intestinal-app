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
st.set_page_config(page_title="Diário Intestinal V25", page_icon="💩", layout="wide")
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
    if not novos_headers: return
    headers = sheet_dados.row_values(1)
    reais_novos = [h for h in novos_headers if h not in headers]
    if reais_novos:
        col_atual = len(headers)
        if col_atual + len(reais_novos) > sheet_dados.col_count:
            sheet_dados.add_cols(len(reais_novos) + 5)
        cell_range = f"{gspread.utils.rowcol_to_a1(1, col_atual + 1)}:{gspread.utils.rowcol_to_a1(1, col_atual + len(reais_novos))}"
        sheet_dados.update(cell_range, [reais_novos])

def gerenciar_listas_config(workbook):
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
    try:
        try: sheet = workbook.worksheet("Receitas")
        except: 
            sheet = workbook.add_worksheet(title="Receitas", rows=100, cols=4)
            sheet.update("A1:D1", [["NomeReceita", "IngredientesPrincipais", "IngredientesMenores", "Rastreadores"]])
        
        records = sheet.get_all_records()
        receitas = {}
        for row in records:
            if row['NomeReceita']:
                main = [x.strip().upper() for x in str(row['IngredientesPrincipais']).split(',') if x.strip()]
                minor_raw = row.get('IngredientesMenores', '')
                minor = [x.strip().upper() for x in str(minor_raw).split(',') if x.strip()]
                trackers = [x.strip().upper() for x in str(row.get('Rastreadores', '')).split(',') if x.strip()]
                receitas[row['NomeReceita'].upper()] = {'main': main, 'minor': minor, 'trackers': trackers}
        return receitas, sheet
    except:
        return {}, None

def cadastrar_item_config(novo_item, tipo, sheet_config, lista_atual):
    item_clean = novo_item.strip().upper() if tipo == 'Alimentos' else novo_item.strip().title()
    if item_clean in lista_atual: return False, "Item já existe."

    col_idx = 1 if tipo == 'Alimentos' else 2
    col_values = sheet_config.col_values(col_idx)
    prox_linha = len(col_values) + 1
    sheet_config.update_cell(prox_linha, col_idx, item_clean)
    
    if tipo == 'Alimentos':
        wb = sheet_config.spreadsheet
        verificar_e_criar_colunas(wb.sheet1, [item_clean])
        
    return True, f"✅ {item_clean} cadastrado!"

def carregar_dados_nuvem():
    workbook = conectar_google_sheets()
    sheet = workbook.sheet1
    lista_alim, lista_sint, _ = gerenciar_listas_config(workbook)
    receitas, _ = obter_receitas(workbook)
    lista_completa_selecao = sorted(list(set(lista_alim + list(receitas.keys()))))
    
    try:
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if df.empty: return pd.DataFrame(), lista_completa_selecao, lista_alim, lista_sint, receitas

        # --- CORREÇÃO DO ERRO ---
        # Definimos todas as colunas que DEVEM ser números: Alimentos Puros + Rastreadores + NOMES DAS RECEITAS
        cols_numericas = lista_alim + LISTA_RASTREADORES + list(receitas.keys())
        
        # Filtra apenas as que existem no DataFrame
        cols_para_converter = [c for c in df.columns if c in cols_numericas]
        
        for col in cols_para_converter:
            # Força conversão para número, transformando texto em NaN e depois em 0
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        # -------------------------
        
        if 'Circunferencia_Cintura' in df.columns: df['Circunferencia_Cintura'] = pd.to_numeric(df['Circunferencia_Cintura'], errors='coerce')
        if 'Circunferencia_Abdominal' in df.columns: df['Circunferencia_Abdominal'] = pd.to_numeric(df['Circunferencia_Abdominal'], errors='coerce')
        if 'Circunferencia' in df.columns and 'Circunferencia_Cintura' not in df.columns:
             df['Circunferencia_Cintura'] = pd.to_numeric(df['Circunferencia'], errors='coerce')

        df['Escala de Bristol'] = pd.to_numeric(df['Escala de Bristol'], errors='coerce').fillna(0)
            
        df['DataHora'] = pd.to_datetime(df['Data'] + ' ' + df['Hora'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['DataHora']).sort_values(by='DataHora', ascending=False).reset_index(drop=True)
        
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
        
        return df, lista_completa_selecao, lista_alim, lista_sint, receitas
    except Exception as e:
        st.error(f"Erro dados: {e}")
        return pd.DataFrame(), lista_completa_selecao, lista_alim, lista_sint, receitas

df, lista_display, lista_alim_pura, lista_sint_pura, receitas_dict = carregar_dados_nuvem()

# --- 4. INTERFACE ---
aba_diario, aba_cadastros, aba_geral, aba_analise = st.tabs(["📝 Diário", "⚙️ Cadastros", "🗂️ Histórico (Dias)", "📊 Detetive"])

# ABA CADASTROS
with aba_cadastros:
    st.header("Central de Cadastros")
    with st.expander("Cadastrar Novos Itens Básicos", expanded=False):
        c_new1, c_new2 = st.columns(2)
        with c_new1:
            novo_alim_txt = st.text_input("Novo Alimento Puro (ex: Ovo)").upper()
            if st.button("Salvar Alimento"):
                if novo_alim_txt:
                    wb = conectar_google_sheets()
                    _, _, sheet_cfg = gerenciar_listas_config(wb)
                    ok, msg = cadastrar_item_config(novo_alim_txt, 'Alimentos', sheet_cfg, lista_alim_pura)
                    if ok: st.success(msg); st.cache_data.clear(); st.rerun()
                    else: st.warning(msg)
        with c_new2:
            novo_sint_txt = st.text_input("Novo Sintoma (ex: Aftas)").title()
            if st.button("Salvar Sintoma"):
                if novo_sint_txt:
                    wb = conectar_google_sheets()
                    _, _, sheet_cfg = gerenciar_listas_config(wb)
                    ok, msg = cadastrar_item_config(novo_sint_txt, 'Sintomas', sheet_cfg, lista_sint_pura)
                    if ok: st.success(msg); st.cache_data.clear(); st.rerun()
                    else: st.warning(msg)

    st.divider()
    with st.container(border=True):
        st.subheader("🧑‍🍳 Nova Receita Inteligente")
        with st.form("form_receita_v22"):
            nome_rec = st.text_input("Nome do Prato (TÍTULO)").upper()
            c_base, c_traco = st.columns(2)
            with c_base:
                st.markdown("🧱 **Base**")
                ingreds_main = st.multiselect("Ingredientes Base", lista_alim_pura)
            with c_traco:
                st.markdown("🧂 **Temperos/Traços**")
                ingreds_minor = st.multiselect("Ingredientes Traço", lista_alim_pura)

            st.markdown("---")
            st.markdown("🔍 **Rastreadores Ocultos:**")
            trackers_selecionados = []
            cols_track = st.columns(4)
            for i, t in enumerate(LISTA_RASTREADORES):
                with cols_track[i % 4]:
                    if st.checkbox(t, key=f"rec_track_{t}"): trackers_selecionados.append(t)
            
            if st.form_submit_button("Salvar Receita"):
                if nome_rec and (ingreds_main or ingreds_minor):
                    wb = conectar_google_sheets()
                    _, sheet_rec = obter_receitas(wb)
                    str_main = ",".join(ingreds_main)
                    str_minor = ",".join(ingreds_minor)
                    str_track = ",".join(trackers_selecionados)
                    sheet_rec.append_row([nome_rec, str_main, str_minor, str_track])
                    todos_novos = trackers_selecionados
                    if todos_novos: verificar_e_criar_colunas(wb.sheet1, todos_novos)
                    st.success(f"Receita '{nome_rec}' salva!")
                    st.cache_data.clear()
                    st.rerun()
                else: st.error("Preencha o nome.")

# ABA DIÁRIO
with aba_diario:
    st.header("Registro Diário")
    agora_br = datetime.now(FUSO_BR)
    
    with st.form("form_diario_v22"):
        c1, c2 = st.columns(2)
        with c1: data_input = st.date_input("📅 Data", agora_br)
        with c2: hora_input = st.time_input("🕒 Hora", agora_br)

        st.divider()
        st.subheader("💩 Bristol")
        bristol_escolhido = st.radio("Selecione:", ["Nenhum"] + [1, 2, 3, 4, 5, 6, 7], horizontal=True, index=0, label_visibility="collapsed")
        
        st.divider()
        with st.expander("🍎 O que você comeu?", expanded=True):
            cp, cm, cg = st.columns(3)
            with cp: sel_pouco = st.multiselect("Nível 1 (Pouco)", lista_display, key="d1")
            with cm: sel_medio = st.multiselect("Nível 2 (Normal)", lista_display, key="d2")
            with cg: sel_muito = st.multiselect("Nível 3 (Muito)", lista_display, key="d3")
            st.caption("Rastreadores avulsos do dia:")
            comps_dia = st.multiselect("Adicionar:", LISTA_RASTREADORES)

        with st.expander("💊 Sintomas & Medidas"):
            meds_sel = st.multiselect("Medicamentos:", LISTA_REMEDIOS_COMUNS)
            sintomas_sel = st.multiselect("Sintomas:", lista_sint_pura)
            st.markdown("---")
            cm1, cm2 = st.columns(2)
            with cm1: circ_cintura = st.number_input("📏 Cintura (Umbigo)", min_value=0.0, step=0.1, format="%.1f")
            with cm2: circ_abd = st.number_input("📏 Baixo Ventre", min_value=0.0, step=0.1, format="%.1f")

        st.divider()
        notas_input = st.text_area("Notas", placeholder="Obs...")
        
        if st.form_submit_button("💾 SALVAR REGISTRO", type="primary", use_container_width=True):
            wb = conectar_google_sheets()
            sheet = wb.sheet1
            sintomas_finais = sintomas_sel
            bristol_save = bristol_escolhido if bristol_escolhido != "Nenhum" else ""
            
            valores_input = {
                'Data': data_input.strftime('%d/%m/%Y'),
                'Hora': hora_input.strftime('%H:%M'),
                'Escala de Bristol': bristol_save,
                'Diarreia': 'S' if bristol_save != "" and bristol_save >= 5 else '',
                'Características': ", ".join(sintomas_finais),
                'Remédios': ", ".join(meds_sel),
                'Circunferencia_Cintura': circ_cintura if circ_cintura > 0 else '',
                'Circunferencia_Abdominal': circ_abd if circ_abd > 0 else '',
                'Notas': notas_input,
                'Humor': ''
            }
            
            ingredientes_processados = {} 
            def processar_item(item, nivel_consumo):
                if item in receitas_dict:
                    for main in receitas_dict[item]['main']:
                        ingredientes_processados[main] = max(ingredientes_processados.get(main, 0), nivel_consumo)
                    for minor in receitas_dict[item]['minor']:
                        ingredientes_processados[minor] = max(ingredientes_processados.get(minor, 0), 1)
                    for track in receitas_dict[item]['trackers']:
                        ingredientes_processados[track] = max(ingredientes_processados.get(track, 0), nivel_consumo)
                    ingredientes_processados[item] = max(ingredientes_processados.get(item, 0), nivel_consumo)
                else:
                    ingredientes_processados[item] = max(ingredientes_processados.get(item, 0), nivel_consumo)

            for item in sel_pouco: processar_item(item, 1)
            for item in sel_medio: processar_item(item, 2)
            for item in sel_muito: processar_item(item, 3)
            for item in comps_dia: processar_item(item, 2)

            for ingred, nivel in ingredientes_processados.items(): valores_input[ingred] = nivel
            
            headers = sheet.row_values(1)
            nova_linha = []
            
            cols_medidas = ['Circunferencia_Cintura', 'Circunferencia_Abdominal']
            cols_faltantes = [c for c in cols_medidas if c not in headers] + [k for k in valores_input.keys() if k not in headers]
            if cols_faltantes:
                verificar_e_criar_colunas(sheet, cols_faltantes)
                headers = sheet.row_values(1)
            
            for h in headers:
                if h in valores_input: nova_linha.append(valores_input[h])
                elif h in lista_alim_pura or h in lista_display or h in LISTA_RASTREADORES: nova_linha.append(valores_input.get(h, 0))
                else: nova_linha.append("")
            
            sheet.append_row(nova_linha)
            st.success("✅ Registro Salvo!")
            st.cache_data.clear()
            st.rerun()

# ABA GERAL (Com o Menu de volta)
with aba_geral:
    st.header("Diário de Bordo")
    
    if not df.empty and ('Circunferencia_Cintura' in df.columns or 'Circunferencia_Abdominal' in df.columns):
        st.subheader("📏 Evolução de Medidas")
        df_medidas = df.copy()
        df_medidas = df_medidas.set_index('DataHora').sort_index()
        cols_plot = []
        if 'Circunferencia_Cintura' in df_medidas.columns: cols_plot.append('Circunferencia_Cintura')
        if 'Circunferencia_Abdominal' in df_medidas.columns: cols_plot.append('Circunferencia_Abdominal')
        if cols_plot: st.line_chart(df_medidas[cols_plot].replace(0, None))

    st.divider()
    
    if not df.empty:
        dias_unicos = sorted(df['DataHora'].dt.date.unique(), reverse=True)
        for dia in dias_unicos[:20]:
            df_dia = df[df['DataHora'].dt.date == dia]
            with st.container(border=True):
                dia_semana = dia.strftime("%A")
                dias_pt = {'Monday':'Seg', 'Tuesday':'Ter', 'Wednesday':'Qua', 'Thursday':'Qui', 'Friday':'Sex', 'Saturday':'Sáb', 'Sunday':'Dom'}
                dia_str = dias_pt.get(dia_semana, dia_semana)
                
                st.markdown(f"### 🗓️ {dia.strftime('%d/%m/%Y')} ({dia_str})")
                
                # Banheiro
                bristols_dia = df_dia[df_dia['Escala de Bristol'] > 0]['Escala de Bristol'].tolist()
                if bristols_dia:
                    bristols_txt = ", ".join([str(int(b)) for b in bristols_dia])
                    cor_status = "red" if any(b >= 5 for b in bristols_dia) else "green"
                    st.markdown(f":{cor_status}[**Evacuações:** {len(bristols_dia)}x (Bristol: {bristols_txt})]")
                
                # COMIDA
                alimentos_dia = set()
                for col in df.columns:
                    # Incluindo Receitas na exibição
                    if (col in lista_alim_pura or col in lista_display or col in LISTA_RASTREADORES):
                        if df_dia[col].sum() > 0:
                            alimentos_dia.add(col)
                if alimentos_dia:
                    st.markdown(f"🍽️ **Menu:** {', '.join(sorted(list(alimentos_dia)))}")

                # Sintomas
                sintomas_dia = []
                for s in df_dia['Características']:
                    if s: sintomas_dia.extend(s.split(','))
                sintomas_dia = list(set([x.strip() for x in sintomas_dia if x.strip()]))
                if sintomas_dia: st.markdown(f"⚠️ **Sintomas:** {', '.join(sintomas_dia)}")

                # Medidas e Notas
                extras = []
                if 'Circunferencia_Cintura' in df_dia.columns and df_dia['Circunferencia_Cintura'].max() > 0:
                     extras.append(f"Cintura: {df_dia['Circunferencia_Cintura'].max()}")
                if 'Circunferencia_Abdominal' in df_dia.columns and df_dia['Circunferencia_Abdominal'].max() > 0:
                     extras.append(f"Ventre: {df_dia['Circunferencia_Abdominal'].max()}")
                
                notas_dia = [n for n in df_dia['Notas'] if n]
                if extras: st.caption(" | ".join(extras))
                if notas_dia: st.info("\n".join(notas_dia))

# ABA DETETIVE (RESTAURADA)
with aba_analise:
    st.header("Análise de Risco (Porto Seguro)")
    
    # 1. Filtros
    col1, col2, col3 = st.columns(3)
    with col1: janela_dias = st.slider("Janela (dias):", 0, 3, 1)
    with col2:
        filtro_qtd = st.selectbox("Quantidade?", ["Todas (1, 2, 3)", "Só Exageros (3)", "Normal e Exagero (2, 3)"])
        min_consumo = st.number_input("Mínimo dias:", 1, value=4)
    with col3: tipo_analise = st.selectbox("Investigar:", ["🚨 Diarreia Aguda (Bristol 7)", "Diarreia Geral (Bristol >= 5)"])

    if st.button("🔍 Analisar"):
        if df.empty:
            st.error("Sem dados para analisar.")
        else:
            # Filtra apenas os dias seguros para análise (evita arraste)
            df_analise = df[df['Porto_Seguro'] == True].copy()
            
            # Define o que é crise
            if "Bristol 7" in tipo_analise:
                df_crises = df[df['Escala de Bristol'] == 7]
            else:
                df_crises = df[df['Escala de Bristol'] >= 5]

            # Lógica de Quantidade
            valor_minimo_considerado = 1
            if filtro_qtd == "Só Exageros (3)": valor_minimo_considerado = 3
            elif filtro_qtd == "Normal e Exagero (2, 3)": valor_minimo_considerado = 2

            # Taxa Basal
            total_dias_registro = df_analise['Data'].nunique()
            dias_com_crise_apos_porto = df_crises[df_crises['Porto_Seguro'] == True]['Data'].nunique()
            risco_basal = (dias_com_crise_apos_porto / total_dias_registro) if total_dias_registro > 0 else 0
            
            st.metric("Taxa Basal (em Porto Seguro)", f"{risco_basal:.1%}")

            # Lista de itens para analisar (Alimentos Puros + Rastreadores)
            # Obs: Não analisamos nomes de receitas, apenas o que elas explodiram (farinha, gluten, etc)
            itens_analise = sorted(list(set(lista_alim_pura + LISTA_RASTREADORES)))

            tabela = []
            for item in itens_analise:
                # Verifica se o item existe nas colunas e é numérico
                if item in df_analise.columns and pd.api.types.is_numeric_dtype(df_analise[item]):
                    # Filtra dias onde comeu esse item na quantidade selecionada
                    mask_comeu = df_analise[item] >= valor_minimo_considerado
                    total_consumo_dias = int(df_analise[mask_comeu]['Data'].nunique())
                    
                    if total_consumo_dias < min_consumo: continue
                    
                    # Verifica crises nos dias seguintes
                    datas_consumo = df_analise[mask_comeu]['DataHora'].dt.date.unique()
                    vezes_gatilho = 0
                    
                    for data_c in datas_consumo:
                        dt = pd.to_datetime(data_c)
                        # Janela de análise (ex: o dia do consumo + 1 dia depois)
                        fim = dt.replace(hour=23, minute=59) if janela_dias == 0 else dt + timedelta(days=janela_dias)
                        
                        # Verifica se houve crise nesse intervalo
                        if df_crises[(df_crises['DataHora'] > dt) & (df_crises['DataHora'] <= fim)].shape[0] > 0:
                            vezes_gatilho += 1
                    
                    risco = min(1.0, vezes_gatilho / total_consumo_dias)
                    impacto = risco / risco_basal if risco_basal > 0 else 0
                    tabela.append({"Item": item, "Dias": total_consumo_dias, "Segurança %": (1-risco)*100, "Impacto": impacto})

            if tabela:
                df_res = pd.DataFrame(tabela)
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("✅ Mais Seguros")
                    st.dataframe(df_res.sort_values(by="Segurança %", ascending=False).head(15), use_container_width=True)
                with c2:
                    st.subheader("⚠️ Maiores Suspeitos (Impacto)")
                    # Filtra apenas quem tem impacto > 1 (piora o basal)
                    st.dataframe(df_res[df_res['Impacto'] > 1.0].sort_values(by="Impacto", ascending=False).head(15), use_container_width=True)
            else:
                st.info("Sem dados suficientes com esses filtros.")