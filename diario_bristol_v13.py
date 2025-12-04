import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import re
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import gspread
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Diário Intestinal V13 (Nuvem)", page_icon="💩", layout="wide")
st.title("💩 Rastreador de Saúde (Conectado à Nuvem)")

# --- 2. CONFIGURAÇÃO GOOGLE SHEETS ---
# O Streamlit Cloud vai ler esta variável, que deve ser o nome exato da sua planilha
NOME_PLANILHA = "Diario_Intestinal_DB" 

# --- LISTAS DE REFERÊNCIA ---
LISTA_ALIMENTOS_OFICIAL = [
    'OVO', 'BANANA', 'ARROZ', 'TAPIOCA', 'FRANGO', 'AVEIA', 
    'CENOURA', 'TOMATE', 'CARNE', 'INHAME', 'ABOBRINHA', 
    'CHUCHU', 'MORANGO', 'PROTEÍNA DE ARROZ', 'LEITE DE AVEIA', 'LEITE DE CASTANHA',
    'PÃO', 'SOJA', 'MILHO', 'FEIJÃO', 'LEITE', 'CAFÉ', 
    'MACARRÃO', 'BATATA', 'QUEIJO', 'IOGURTE', 'CHOCOLATE', 
    'CASTANHA', 'AMENDOIM', 'GLUTEN', 'LACTOSE', 'AÇÚCAR', 
    'KIWI', 'MOLHO', 'FAROFA', 'CREPIOCA', 'ESPINAFRE', 'GOIABA', 
    'BATATA DOCE', 'UVA', 'AMÊNDOAS', 'SEMENTE', 'MACADÂMIA', 
    'MAMÃO', 'PIPOCA', 'POLENTA', 'LENTILHA', 'PEIXE', 'PIZZA',
    'LEITE VEGETAL'
]
LISTA_ALIMENTOS_OFICIAL.sort()

LISTA_SINTOMAS_COMUNS = [
    'Estufamento', 'Gases', 'Cólica', 'Dor Abdominal', 'Refluxo', 
    'Náusea', 'Muco', 'Sangue', 'Urgência', 'Sensação Incompleta', 
    'Cansaço', 'Dor de Cabeça', 'Ansiedade'
]

LISTA_REMEDIOS_COMUNS = [
    'Buscopan', 'Simeticona', 'Probiótico', 'Enzima Lactase', 
    'Mesalazina', 'Antialérgico', 'Analgésico', 'Carvão Ativado'
]


# --- 3. CONEXÃO COM O BANCO DE DADOS (GOOGLE) ---
@st.cache_resource
def conectar_google_sheets():
    """Conecta ao Google Sheets usando st.secrets (Segredos do Streamlit Cloud)"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        # Pega as credenciais do Secrets do Streamlit Cloud
        credentials_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        client = gspread.authorize(creds)
        # Abre a planilha
        sheet = client.open(NOME_PLANILHA).sheet1
        return sheet
    except Exception as e:
        # Se falhar, exibe o erro e para o aplicativo
        st.error(f"❌ Erro ao conectar ao Google Sheets: {e}")
        st.stop()

def carregar_dados_nuvem():
    """Lê os dados brutos da planilha e retorna o DataFrame limpo."""
    sheet = conectar_google_sheets()
    if not sheet: return pd.DataFrame(), []
    
    try:
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        
        if df.empty: return pd.DataFrame(), []

        # Limpeza e Tipagem (Garante que os dados da nuvem são numéricos)
        cols_sistema = ['Data', 'Hora', 'DataHora', 'Escala de Bristol', 'Diarreia', 'Características', 'Remédios', 'Circunferencia', 'Notas', 'Humor', 'Porto_Seguro']
        cols_alim = [c for c in df.columns if c in LISTA_ALIMENTOS_OFICIAL]
        
        for col in cols_alim:
            # Converte todos os valores de alimentos (que vieram como texto) para float (0 ou 1/2/3)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        if 'Circunferencia' in df.columns:
            df['Circunferencia'] = pd.to_numeric(df['Circunferencia'], errors='coerce')
        
        # Cria DataHora
        df['DataHora'] = pd.to_datetime(df['Data'] + ' ' + df['Hora'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['DataHora'])
        df = df.sort_values(by='DataHora').reset_index(drop=True)
        
        # LÓGICA PORTO SEGURO (Anti-Arraste)
        df['Porto_Seguro'] = False
        # Garante que Bristol seja número para a lógica funcionar
        df['Escala de Bristol'] = pd.to_numeric(df['Escala de Bristol'], errors='coerce').fillna(0) 
        crise_mask = (df['Escala de Bristol'] >= 5)
        
        for i in range(len(df)):
            if i < 3: continue
            data_atual = df.loc[i, 'DataHora']
            data_limite_inicio = data_atual - timedelta(days=3)
            
            df_janela_antes = df[
                (df['DataHora'] < data_atual) & 
                (df['DataHora'] >= data_limite_inicio)
            ]
            
            if not df_janela_antes.empty:
                teve_crise_antes = df_janela_antes[crise_mask].any().any()
                if not teve_crise_antes:
                    df.loc[i, 'Porto_Seguro'] = True
                    
        return df, cols_alim
        
    except Exception as e:
        st.error(f"Erro ao processar dados da nuvem: {e}")
        return pd.DataFrame(), []

# O Streamlit só vai recarregar isso quando você pedir (st.cache_data.clear())
@st.cache_data
def load_data():
    return carregar_dados_nuvem()

df, colunas_alimentos = load_data()


# --- Se não tiver dados, para aqui ---
if df.empty:
    st.info("Planilha vazia ou com erro de leitura. Insira o cabeçalho e os dados na sua planilha Google Sheets e atualize.")
    st.stop()


# Filtra DF para análise
df_analise = df[df['Porto_Seguro'] == True].copy()


# --- 4. INTERFACE ---
aba_inserir, aba_analise, aba_geral, aba_dados = st.tabs(["📥 Inserir (Nuvem)", "📊 Detetive", "📈 Geral", "📝 Brutos"])

# --- ABA 0: INSERIR DADOS (ENVIA PARA GOOGLE SHEETS) ---
with aba_inserir:
    st.header("Novo Registro")
    
    with st.form("form_entrada_nuvem"):
        # 1. QUANDO?
        c1, c2 = st.columns(2)
        with c1: data_input = st.date_input("📅 Data", datetime.now())
        with c2: hora_input = st.time_input("🕒 Hora", datetime.now())

        # 2. O QUE ENTROU? (Comida e Remédio)
        with st.expander("🍎 Alimentação & Medicamentos", expanded=True):
            st.subheader("O que você comeu?")
            cp, cm, cg = st.columns(3)
            with cp:
                st.markdown("🤏 **Pouco (1)**")
                sel_pouco = st.multiselect("Nível 1", LISTA_ALIMENTOS_OFICIAL, key="s1", label_visibility="collapsed")
            with cm:
                st.markdown("🍽️ **Normal (2)**")
                sel_medio = st.multiselect("Nível 2", LISTA_ALIMENTOS_OFICIAL, key="s2", label_visibility="collapsed")
            with cg:
                st.markdown("🚀 **Muito (3)**")
                sel_muito = st.multiselect("Nível 3", LISTA_ALIMENTOS_OFICIAL, key="s3", label_visibility="collapsed")
            
            st.divider()
            st.markdown("💊 **Medicamentos**")
            meds_sel = st.multiselect("Selecione:", LISTA_REMEDIOS_COMUNS)
            meds_extra = st.text_input("Outros:", placeholder="Ex: Vitamina D")

        # 3. O QUE SAIU / SINTOMAS?
        with st.expander("💩 Banheiro & Corpo", expanded=False):
            cb1, cb2 = st.columns(2)
            with cb1:
                teve_coco = st.checkbox("Houve evacuação?")
                if teve_coco:
                    bristol_input = st.slider("Escala de Bristol", 1, 7, 4)
                else:
                    bristol_input = "" # Vazio para salvar no sheets se não teve coco
            with cb2:
                circunf = st.number_input("📏 Cintura (cm)", min_value=0.0, step=0.1, format="%.1f")
            
            st.divider()
            st.markdown("⚠️ **Sintomas**")
            sintomas_sel = st.multiselect("Sintomas:", LISTA_SINTOMAS_COMUNS)

        st.divider()
        notas_input = st.text_area("Notas", placeholder="Obs...")
        
        enviou = st.form_submit_button("💾 SALVAR NA NUVEM", type="primary")

        if enviou:
            sheet = conectar_google_sheets()
            if sheet:
                # Prepara linha para o Google Sheets
                try:
                    headers = sheet.row_values(1)
                    nova_linha = []
                    
                    # Dicionário temporário com os valores
                    str_remedios = ", ".join(meds_sel)
                    if meds_extra: str_remedios += f", {meds_extra}" if str_remedios else meds_extra
                    str_sintomas = ", ".join(sintomas_sel)
                    
                    # Garantir que o Bristol seja vazio se não houve evacuação
                    bristol_save = bristol_input if teve_coco else ""

                    valores_input = {
                        'Data': data_input.strftime('%d/%m/%Y'),
                        'Hora': hora_input.strftime('%H:%M'),
                        'Escala de Bristol': bristol_save,
                        'Diarreia': 'S' if bristol_save != "" and bristol_input >= 5 else '',
                        'Características': str_sintomas,
                        'Remédios': str_remedios,
                        'Circunferencia': circunf if circunf > 0 else '',
                        'Notas': notas_input,
                        'Humor': ''
                    }
                    
                    # Preenche alimentos
                    for item in sel_pouco: valores_input[item] = 1
                    for item in sel_medio: valores_input[item] = 2
                    for item in sel_muito: valores_input[item] = 3
                    
                    # Monta a lista ordenada baseada nos headers da planilha
                    for h in headers:
                        if h in valores_input:
                            nova_linha.append(valores_input[h])
                        elif h in LISTA_ALIMENTOS_OFICIAL:
                            nova_linha.append(valores_input.get(h, 0)) # Se não comeu, é 0
                        else:
                            nova_linha.append("") # Coluna desconhecida
                    
                    # Envia para o Google
                    sheet.append_row(nova_linha)
                    st.success("Salvo na nuvem! Recarregando...")
                    # Limpa o cache para forçar o app a ler o dado novo da planilha
                    st.cache_data.clear() 
                    st.rerun() # Recarrega a página

                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

# --- ABA 1: DETETIVE ---
with aba_analise:
    st.header("Análise de Risco (Porto Seguro)")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        janela_dias = st.slider("Janela (dias):", 0, 3, 1)
    with col2:
        filtro_qtd = st.selectbox("Quantidade?", ["Todas (1, 2, 3)", "Só Exageros (3)", "Normal e Exagero (2, 3)"])
        min_consumo = st.number_input("Mínimo dias:", 1, value=4)
    with col3:
        tipo_analise = st.selectbox("Investigar:", ["🚨 Diarreia Aguda (Bristol 7)", "Diarreia Geral (Bristol >= 5)"])

    if st.button("🔍 Analisar"):
        if "Bristol 7" in tipo_analise:
            df_crises = df[df['Escala de Bristol'] == 7]
        else:
            df_crises = df[df['Escala de Bristol'] >= 5]

        valor_minimo_considerado = 1
        if filtro_qtd == "Só Exageros (3)": valor_minimo_considerado = 3
        elif filtro_qtd == "Normal e Exagero (2, 3)": valor_minimo_considerado = 2

        total_dias_registro = df_analise['Data'].nunique()
        dias_com_crise_apos_porto = df_crises[df_crises['Porto_Seguro'] == True]['Data'].nunique()
        risco_basal = (dias_com_crise_apos_porto / total_dias_registro) if total_dias_registro > 0 else 0
        
        st.metric("Taxa Basal (em Porto Seguro)", f"{risco_basal:.1%}")

        tabela = []
        for alim in colunas_alimentos:
            if pd.api.types.is_numeric_dtype(df_analise[alim]):
                mask_comeu_porto = df_analise[alim] >= valor_minimo_considerado
                total_consumo_dias = int(df_analise[mask_comeu_porto]['Data'].nunique())
                if total_consumo_dias < min_consumo: continue
                
                datas_consumo = df_analise[mask_comeu_porto]['DataHora'].dt.date.unique()
                vezes_gatilho = 0
                for data_c in datas_consumo:
                    dt = pd.to_datetime(data_c)
                    fim = dt.replace(hour=23, minute=59) if janela_dias == 0 else dt + timedelta(days=janela_dias)
                    if df_crises[(df_crises['DataHora'] > dt) & (df_crises['DataHora'] <= fim)].shape[0] > 0:
                        vezes_gatilho += 1
                
                risco = min(1.0, vezes_gatilho / total_consumo_dias)
                impacto = risco / risco_basal if risco_basal > 0 else 0
                tabela.append({"Alimento": alim, "Dias": total_consumo_dias, "Segurança %": (1-risco)*100, "Impacto": impacto})

        if tabela:
            df_res = pd.DataFrame(tabela)
            c1, c2 = st.columns(2)
            c1.dataframe(df_res.sort_values(by="Segurança %", ascending=False).head(15), use_container_width=True)
            c2.dataframe(df_res[df_res['Impacto'] > 1.0].sort_values(by="Impacto", ascending=False).head(15), use_container_width=True)
        else:
            st.info("Sem dados suficientes.")

# --- ABA 2: GERAL ---
with aba_geral:
    st.header("Panorama Geral")
    
    contagem_alim = {}
    for c in colunas_alimentos:
        if pd.api.types.is_numeric_dtype(df[c]):
             dias = df[df[c] >= 1]['Data'].nunique()
             if dias > 0: contagem_alim[c] = dias

    c_sint, c_circ = st.columns(2)
    with c_sint:
        st.subheader("📉 Sintomas")
        todas_tags = []
        for item in df['Características'].dropna():
            tags = re.split(r'[,;]\s*|\s\s+', str(item))
            todas_tags.extend([t.strip().capitalize() for t in tags if t.strip()])
        
        if todas_tags:
            df_sint = pd.DataFrame(todas_tags, columns=['Sintoma'])
            sint_counts = df_sint['Sintoma'].value_counts().reset_index()
            sint_counts.columns = ['Sintoma', 'Qtd']
            sint_counts['%'] = (sint_counts['Qtd'] / len(df)) * 100
            st.dataframe(sint_counts.head(15), column_config={"%": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)}, use_container_width=True, hide_index=True)
    
    with c_circ:
        st.subheader("📏 Cintura (cm)")
        if 'Circunferencia' in df.columns:
            df_medidas = df[pd.to_numeric(df['Circunferencia'], errors='coerce') > 0].sort_values('DataHora')
            if not df_medidas.empty:
                st.line_chart(df_medidas.set_index('DataHora')['Circunferencia'])
            else:
                st.info("Sem medições.")

    st.divider()
    
    c_alim, c_nuvem = st.columns(2)
    with c_alim:
        st.subheader("🏆 Alimentos (Dias)")
        if contagem_alim:
            df_c = pd.DataFrame(list(contagem_alim.items()), columns=['Alimento', 'Dias']).sort_values('Dias', ascending=False).head(20)
            max_d = int(df_c['Dias'].max())
            st.dataframe(df_c, column_config={"Dias": st.column_config.ProgressColumn(format="%d", max_value=max_d)}, use_container_width=True, hide_index=True)
    
    with c_nuvem:
        st.subheader("☁️ Nuvem")
        if contagem_alim:
            wc = WordCloud(width=600, height=300, background_color='black', colormap='Pastel1').generate_from_frequencies(contagem_alim)
            fig, ax = plt.subplots(figsize=(6,3))
            fig.patch.set_facecolor('black')
            ax.imshow(wc)
            ax.axis('off')
            st.pyplot(fig)

with aba_dados:
    st.dataframe(df.sort_values(by='DataHora', ascending=False), use_container_width=True)