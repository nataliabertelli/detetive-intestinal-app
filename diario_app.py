import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import re
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import gspread
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Diário Intestinal V14 (Dinâmico)", page_icon="💩", layout="wide")
st.title("💩 Rastreador de Saúde (Lista Dinâmica)")

# --- 2. CONFIGURAÇÃO GOOGLE SHEETS ---
NOME_PLANILHA = "Diario_Intestinal_DB" 

# Lista padrão para backup/inicialização
LISTA_PADRAO_BACKUP = [
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

LISTA_SINTOMAS_COMUNS = [
    'Estufamento', 'Gases', 'Cólica', 'Dor Abdominal', 'Refluxo', 
    'Náusea', 'Muco', 'Sangue', 'Urgência', 'Sensação Incompleta', 
    'Cansaço', 'Dor de Cabeça', 'Ansiedade'
]

LISTA_REMEDIOS_COMUNS = [
    'Buscopan', 'Simeticona', 'Probiótico', 'Enzima Lactase', 
    'Mesalazina', 'Antialérgico', 'Analgésico', 'Carvão Ativado'
]


# --- 3. CONEXÃO E FUNÇÕES DO BANCO ---
@st.cache_resource
def conectar_google_sheets():
    """Conecta ao Google Sheets usando st.secrets"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    try:
        credentials_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open(NOME_PLANILHA) # Retorna a planilha inteira (workbook)
    except Exception as e:
        st.error(f"❌ Erro de Conexão: {e}")
        st.stop()

def obter_lista_alimentos(workbook):
    """Lê a lista da aba 'Config' ou cria se não existir."""
    try:
        # Tenta abrir a aba Config
        try:
            sheet_config = workbook.worksheet("Config")
        except:
            # Se não existe, cria ela
            sheet_config = workbook.add_worksheet(title="Config", rows=100, cols=5)
            sheet_config.update_acell("A1", "Alimentos")
        
        # Lê os alimentos da coluna A (ignorando o cabeçalho)
        lista_atual = sheet_config.col_values(1)[1:]
        
        # Se estiver vazia, popula com a lista padrão (Migração Automática)
        if not lista_atual:
            # Transforma lista em lista de listas para o gspread [[Item], [Item]]
            dados_iniciais = [[item] for item in LISTA_PADRAO_BACKUP]
            sheet_config.update("A2", dados_iniciais)
            lista_atual = LISTA_PADRAO_BACKUP
        
        lista_atual.sort()
        return lista_atual, sheet_config
    except Exception as e:
        st.error(f"Erro ao carregar lista de alimentos: {e}")
        return LISTA_PADRAO_BACKUP, None

def adicionar_novo_alimento(novo_alimento, workbook):
    """Adiciona alimento na Config e cria coluna na aba principal."""
    novo_alimento = novo_alimento.strip().upper()
    try:
        lista_atual, sheet_config = obter_lista_alimentos(workbook)
        
        if novo_alimento in lista_atual:
            return False, "Alimento já existe!"

        # 1. Adiciona na aba Config
        sheet_config.append_row([novo_alimento])
        
        # 2. Adiciona coluna na aba principal (Dados) se não existir
        sheet_dados = workbook.sheet1
        headers = sheet_dados.row_values(1)
        if novo_alimento not in headers:
            # Adiciona na primeira coluna vazia da primeira linha
            sheet_dados.update_cell(1, len(headers) + 1, novo_alimento)
            
        return True, f"✅ '{novo_alimento}' cadastrado com sucesso!"
    except Exception as e:
        return False, f"Erro ao salvar: {e}"

def carregar_dados_nuvem():
    workbook = conectar_google_sheets()
    sheet = workbook.sheet1
    
    # Carrega lista dinâmica
    lista_alimentos_dinamica, _ = obter_lista_alimentos(workbook)
    
    try:
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        
        if df.empty: return pd.DataFrame(), lista_alimentos_dinamica

        cols_alim = [c for c in df.columns if c in lista_alimentos_dinamica]
        
        for col in cols_alim:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        if 'Circunferencia' in df.columns:
            df['Circunferencia'] = pd.to_numeric(df['Circunferencia'], errors='coerce')
        
        df['DataHora'] = pd.to_datetime(df['Data'] + ' ' + df['Hora'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['DataHora'])
        df = df.sort_values(by='DataHora').reset_index(drop=True)
        
        # LÓGICA PORTO SEGURO
        df['Porto_Seguro'] = False
        df['Escala de Bristol'] = pd.to_numeric(df['Escala de Bristol'], errors='coerce').fillna(0) 
        crise_mask = (df['Escala de Bristol'] >= 5)
        
        for i in range(len(df)):
            if i < 3: continue
            data_atual = df.loc[i, 'DataHora']
            data_limite_inicio = data_atual - timedelta(days=3)
            df_janela = df[(df['DataHora'] < data_atual) & (df['DataHora'] >= data_limite_inicio)]
            
            if not df_janela.empty and not df_janela[crise_mask].any().any():
                df.loc[i, 'Porto_Seguro'] = True
                    
        return df, lista_alimentos_dinamica
        
    except Exception as e:
        st.error(f"Erro ao processar dados: {e}")
        return pd.DataFrame(), lista_alimentos_dinamica

# Carregamento Inicial
df, lista_alimentos_dinamica = carregar_dados_nuvem()


# --- 4. INTERFACE ---
aba_inserir, aba_analise, aba_geral, aba_dados = st.tabs(["📥 Inserir", "📊 Detetive", "📈 Geral", "📝 Brutos"])

# --- ABA 0: INSERIR ---
with aba_inserir:
    st.header("Novo Registro")
    
    # --- ÁREA DE CADASTRO DE NOVO ALIMENTO ---
    with st.expander("➕ Cadastrar Novo Alimento (Farinha de Arroz, etc.)"):
        c_new1, c_new2 = st.columns([3, 1])
        with c_new1:
            novo_alim_input = st.text_input("Nome do Alimento", placeholder="Ex: Farinha de Arroz").upper()
        with c_new2:
            st.write("") # Espaço
            st.write("") 
            btn_add = st.button("Cadastrar")
        
        if btn_add and novo_alim_input:
            wb = conectar_google_sheets()
            sucesso, msg = adicionar_novo_alimento(novo_alim_input, wb)
            if sucesso:
                st.success(msg)
                st.cache_data.clear() # Limpa cache
                st.rerun() # Recarrega para aparecer na lista abaixo
            else:
                st.warning(msg)

    # --- FORMULÁRIO PADRÃO ---
    with st.form("form_entrada_nuvem"):
        c1, c2 = st.columns(2)
        with c1: data_input = st.date_input("📅 Data", datetime.now())
        with c2: hora_input = st.time_input("🕒 Hora", datetime.now())

        with st.expander("🍎 Alimentação & Medicamentos", expanded=True):
            st.subheader("O que você comeu?")
            cp, cm, cg = st.columns(3)
            with cp:
                st.markdown("🤏 **Pouco (1)**")
                sel_pouco = st.multiselect("Nível 1", lista_alimentos_dinamica, key="s1")
            with cm:
                st.markdown("🍽️ **Normal (2)**")
                sel_medio = st.multiselect("Nível 2", lista_alimentos_dinamica, key="s2")
            with cg:
                st.markdown("🚀 **Muito (3)**")
                sel_muito = st.multiselect("Nível 3", lista_alimentos_dinamica, key="s3")
            
            st.divider()
            st.markdown("💊 **Medicamentos**")
            meds_sel = st.multiselect("Selecione:", LISTA_REMEDIOS_COMUNS)
            meds_extra = st.text_input("Outros:", placeholder="Ex: Vitamina D")

        with st.expander("💩 Banheiro & Corpo", expanded=False):
            cb1, cb2 = st.columns(2)
            with cb1:
                teve_coco = st.checkbox("Houve evacuação?")
                if teve_coco:
                    bristol_input = st.slider("Escala de Bristol", 1, 7, 4)
                    st.image("https://upload.wikimedia.org/wikipedia/commons/b/b4/Bristol_stool_scale.svg", width=300)
                else:
                    bristol_input = ""
            with cb2:
                circunf = st.number_input("📏 Cintura (cm)", min_value=0.0, step=0.1, format="%.1f")
            
            st.divider()
            sintomas_sel = st.multiselect("Sintomas:", LISTA_SINTOMAS_COMUNS)

        st.divider()
        notas_input = st.text_area("Notas", placeholder="Obs...")
        
        enviou = st.form_submit_button("💾 SALVAR NA NUVEM", type="primary")

        if enviou:
            wb = conectar_google_sheets()
            sheet = wb.sheet1
            if sheet:
                try:
                    headers = sheet.row_values(1)
                    nova_linha = []
                    
                    str_remedios = ", ".join(meds_sel)
                    if meds_extra: str_remedios += f", {meds_extra}" if str_remedios else meds_extra
                    str_sintomas = ", ".join(sintomas_sel)
                    bristol_save = bristol_input if teve_coco else ""

                    valores_input = {
                        'Data': data_input.strftime('%d/%m/%Y'),
                        'Hora': hora_input.strftime('%H:%M'),
                        'Escala de Bristol': bristol_save,
                        'Diarreia': 'S' if bristol_save != "" and isinstance(bristol_input, int) and bristol_input >= 5 else '',
                        'Características': str_sintomas,
                        'Remédios': str_remedios,
                        'Circunferencia': circunf if circunf > 0 else '',
                        'Notas': notas_input,
                        'Humor': ''
                    }
                    
                    for item in sel_pouco: valores_input[item] = 1
                    for item in sel_medio: valores_input[item] = 2
                    for item in sel_muito: valores_input[item] = 3
                    
                    for h in headers:
                        if h in valores_input: nova_linha.append(valores_input[h])
                        elif h in lista_alimentos_dinamica: nova_linha.append(valores_input.get(h, 0))
                        else: nova_linha.append("")
                    
                    sheet.append_row(nova_linha)
                    st.success("Salvo!")
                    st.cache_data.clear() 
                    st.rerun()

                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

if df.empty:
    st.info("Aguardando dados...")
    st.stop()

df_analise = df[df['Porto_Seguro'] == True].copy()

# --- ABA 1: DETETIVE ---
with aba_analise:
    st.header("Análise de Risco (Porto Seguro)")
    col1, col2, col3 = st.columns(3)
    with col1: janela_dias = st.slider("Janela (dias):", 0, 3, 1)
    with col2:
        filtro_qtd = st.selectbox("Quantidade?", ["Todas (1, 2, 3)", "Só Exageros (3)", "Normal e Exagero (2, 3)"])
        min_consumo = st.number_input("Mínimo dias:", 1, value=4)
    with col3: tipo_analise = st.selectbox("Investigar:", ["🚨 Diarreia Aguda (Bristol 7)", "Diarreia Geral (Bristol >= 5)"])

    if st.button("🔍 Analisar"):
        if "Bristol 7" in tipo_analise: df_crises = df[df['Escala de Bristol'] == 7]
        else: df_crises = df[df['Escala de Bristol'] >= 5]

        valor_minimo = 1
        if filtro_qtd == "Só Exageros (3)": valor_minimo = 3
        elif filtro_qtd == "Normal e Exagero (2, 3)": valor_minimo = 2

        total_base = df_analise['Data'].nunique()
        crise_base = df_crises[df_crises['Porto_Seguro'] == True]['Data'].nunique()
        risco_basal = (crise_base / total_base) if total_base > 0 else 0
        
        st.metric("Taxa Basal (em Porto Seguro)", f"{risco_basal:.1%}")

        tabela = []
        for alim in lista_alimentos_dinamica:
            if alim in df_analise.columns and pd.api.types.is_numeric_dtype(df_analise[alim]):
                mask = df_analise[alim] >= valor_minimo
                dias_comido = int(df_analise[mask]['Data'].nunique())
                if dias_comido < min_consumo: continue
                
                dates = df_analise[mask]['DataHora'].dt.date.unique()
                gatilhos = 0
                for d in dates:
                    dt = pd.to_datetime(d)
                    fim = dt.replace(hour=23, minute=59) if janela_dias == 0 else dt + timedelta(days=janela_dias)
                    if not df_crises[(df_crises['DataHora'] > dt) & (df_crises['DataHora'] <= fim)].empty:
                        gatilhos += 1
                
                risco = min(1.0, gatilhos / dias_comido)
                impacto = risco / risco_basal if risco_basal > 0 else 0
                tabela.append({"Alimento": alim, "Dias": dias_comido, "Segurança %": (1-risco)*100, "Impacto": impacto})

        if tabela:
            df_res = pd.DataFrame(tabela)
            c1, c2 = st.columns(2)
            c1.dataframe(df_res.sort_values(by="Segurança %", ascending=False).head(15), use_container_width=True)
            c2.dataframe(df_res[df_res['Impacto'] > 1.0].sort_values(by="Impacto", ascending=False).head(15), use_container_width=True)
        else: st.info("Sem dados suficientes.")

# --- ABA 2: GERAL ---
with aba_geral:
    st.header("Panorama Geral")
    contagem_alim = {}
    for c in lista_alimentos_dinamica:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
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
            if not df_medidas.empty: st.line_chart(df_medidas.set_index('DataHora')['Circunferencia'])
            else: st.info("Sem medições.")

    st.divider()
    c_alim, c_nuvem = st.columns(2)
    with c_alim:
        st.subheader("🏆 Alimentos (Dias)")
        if contagem_alim:
            df_c = pd.DataFrame(list(contagem_alim.items()), columns=['Alimento', 'Dias']).sort_values('Dias', ascending=False).head(20)
            st.dataframe(df_c, column_config={"Dias": st.column_config.ProgressColumn(format="%d", max_value=int(df_c['Dias'].max()))}, use_container_width=True, hide_index=True)
    with c_nuvem:
        st.subheader("☁️ Nuvem")
        if contagem_alim:
            wc = WordCloud(width=600, height=300, background_color='black', colormap='Pastel1').generate_from_frequencies(contagem_alim)
            fig, ax = plt.subplots(figsize=(6,3))
            fig.patch.set_facecolor('black')
            ax.imshow(wc); ax.axis('off')
            st.pyplot(fig)

with aba_dados: st.dataframe(df.sort_values(by='DataHora', ascending=False), use_container_width=True)