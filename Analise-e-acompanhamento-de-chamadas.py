import streamlit as st
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
from collections import Counter, defaultdict

st.set_page_config(
    page_title="Análise de Chamadas",
    layout="wide"
)

# ===== CONFIGURACIONAL =====
login_url = "https://pabx.evence.com.br/login"
cdr_url = "https://pabx.evence.com.br/cdr/pesquisar"

email = "suporte@interativanet.com.br"
senha = "smk03657"

# =========================================================
# CONFIGURAÇÕES DA APLICAÇÃO
# =========================================================
st.set_page_config(page_title="Análise CDR - PABX", layout="wide")

# CSS para ajustar espaçamentos e evitar que o texto fique apertado nas tabelas
st.markdown("""
    <style>
        .stDataFrame { width: 100%; }
        div[data-testid="stMetricValue"] { font-size: 1.8rem; }
        .stTable { width: 100%; }
        div[role="gridcell"] { padding: 8px !important; }
    </style>
""", unsafe_allow_html=True)

# ATENÇÃO: Garanta que essas variáveis estejam definidas no seu ambiente
# login_url = "https://pabx.evence.com.br/login"
# cdr_url = "https://pabx.evence.com.br/cdr"
# email = "seu_email"
# senha = "sua_senha"

# =========================================================
# SESSÃO REUTILIZÁVEL (Evita múltiplos logins no servidor PABX)
# =========================================================
@st.cache_resource
def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0"
    })
    return session

# =========================================================
# LOGIN NO PABX (Com busca dinâmica de CSRF token)
# =========================================================
def login_pabx():
    session = get_session()

    r = session.get(login_url, timeout=120)
    soup = BeautifulSoup(r.text, "html.parser")

    csrf_input = soup.find("input", {"name": "_token"})
    csrf_token = csrf_input["value"] if csrf_input else ""

    payload = {
        "login": email,
        "senha": senha,
        "_token": csrf_token
    }

    response = session.post(login_url, data=payload, timeout=120)

    if response.url != login_url:
        return session
    else:
        raise Exception("Erro no login")

# =========================================================
# RETRY (Tratamento para instabilidades de rede)
# =========================================================
def request_com_retry(session, url, params, headers, tentativas=4):
    for i in range(tentativas):
        try:
            return session.get(url, params=params, headers=headers, timeout=120)
        except requests.exceptions.Timeout:
            if i == tentativas - 1:
                raise
            time.sleep(2)

# =========================================================
# BUSCA E PARSING DO CDR
# =========================================================
def buscar_cdr(data_inicio, data_fim, progress_ui=None):
    session = login_pabx()

    d_inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
    d_fim = datetime.strptime(data_fim, "%Y-%m-%d")

    if d_inicio > d_fim:
        d_inicio, d_fim = d_fim, d_inicio

    str_inicio = d_inicio.strftime("%d-%m-%Y")
    str_fim = d_fim.strftime("%d-%m-%Y")

    payload = {
        "ramal_origem": "",
        "numero_origem": "",
        "ramal_destino": "",
        "numero_destino": "",
        "did": "",
        "status_chamada": "",
        "centrocusto_id": "",
        "tipo_chamada": "IN",
        "gravacao": "",
        "discador": "0",
        "data_inicial": str_inicio,
        "data_final": str_fim
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://pabx.evence.com.br/cdr"
    }

    dados = []
    pagina = 1

    if progress_ui:
        progress_bar = progress_ui.progress(0)
        status_text = progress_ui.empty()
    else:
        progress_bar = None
        status_text = None

    total_estimado = 70

    while True:
        payload["page"] = pagina

        if status_text:
            status_text.text(f"📄 Processando página {pagina}")

        r = request_com_retry(session, cdr_url, payload, headers)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table tbody tr")

        if not rows:
            break

        for row in rows:
            cols = row.find_all("td")

            # 0: Data/Hora, 1: Num. Virtual, 2: Bina (Cliente), 3: Origem,
            # 4: Destino (Técnico), 5: Duração, 6: Status, 7: Tipo
            if len(cols) >= 8:
                data_hora = cols[0].get_text(strip=True)  # <--- Captura a Data e Hora
                bina = cols[2].get_text(strip=True)       # Telefone do cliente
                tecnico = cols[4].get_text(strip=True)    # Destino / Atendente
                duracao = cols[5].get_text(strip=True)    # Duração (HH:MM:SS)
                status = cols[6].get_text(strip=True)     # ex: Atendida, Abandonada
                tipo = cols[7].get_text(strip=True)       # ex: Entrada, Saída

                try:
                    h, m, s = duracao.split(":")
                    segundos = int(h) * 3600 + int(m) * 60 + int(s)
                except ValueError:
                    segundos = 0

                dados.append({
                    "data_hora": data_hora,              # <--- Armazena Data/Hora
                    "bina": bina,
                    "tecnico": tecnico,
                    "duracao": duracao,
                    "segundos": segundos,
                    "status": status,
                    "tipo": tipo
                })

        if progress_bar:
            progresso = min(pagina / total_estimado, 1.0)
            progress_bar.progress(progresso)

        pagina += 1
        time.sleep(0.3)

    if progress_ui:
        progress_ui.empty()

    return dados

# =========================================================
# PROCESSAMENTO DE KPIS E INSIGHTS
# =========================================================
def analisar_dados(dados):
    total_chamadas_bruto = len(dados) 
    
    if total_chamadas_bruto == 0:
        return None

    dados_validos = [d for d in dados if "Fila" not in d["tecnico"]]
    chamadas_abandonadas = [d for d in dados if "Fila" in d["tecnico"]]

    total_atendidas_tecnicos = len(dados_validos)
    segundos_totais = sum(d["segundos"] for d in dados_validos)

    horas = int(segundos_totais // 3600)
    minutos = int((segundos_totais % 3600) // 60)
    tempo_total_fmt = f"{horas}h {minutos}m"

    tma_seg = int(round(segundos_totais / total_atendidas_tecnicos)) if total_atendidas_tecnicos > 0 else 0
    tma_fmt = f"{tma_seg // 60:02d}:{tma_seg % 60:02d}"

    contagem_clientes = Counter([d["bina"] for d in dados_validos if d["bina"]])
    clientes_reincidentes = {k: v for k, v in contagem_clientes.items() if v > 1}

    # Agrupa as datas/horas por cada cliente (Bina)
    datas_por_cliente = defaultdict(list)
    for d in dados_validos:
        if d["bina"]:
            datas_por_cliente[d["bina"]].append(d["data_hora"])

    ligacoes_curtas = [
        {
            "Data/Hora": d["data_hora"],
            "Telefone (Bina)": d["bina"],
            "Técnico": d["tecnico"],
            "Status": d["status"],
            "Duração": d["duracao"]
        }
        for d in dados_validos if d["segundos"] < 10
    ]

    tecnicos_por_cliente = defaultdict(set)
    tempo_por_cliente = defaultdict(int)

    for d in dados_validos:
        cli = d["bina"]
        tecnicos_por_cliente[cli].add(d["tecnico"])
        tempo_por_cliente[cli] += d["segundos"]

    clientes_fragmentados = {
        cli: list(tecs) for cli, tecs in tecnicos_por_cliente.items() if len(tecs) > 1
    }

    desempenho_tecnicos = defaultdict(lambda: {"chamadas": 0, "segundos": 0})
    for d in dados_validos:
        tec = d["tecnico"]
        desempenho_tecnicos[tec]["chamadas"] += 1
        desempenho_tecnicos[tec]["segundos"] += d["segundos"]

    ranking_tecnicos = []
    for tec, info in desempenho_tecnicos.items():
        tma_t = int(round(info["segundos"] / info["chamadas"])) if info["chamadas"] > 0 else 0
        ranking_tecnicos.append({
            "Técnico": tec,
            "Total Chamadas": info["chamadas"],
            "Tempo Total": f"{info['segundos'] // 3600:02d}:{(info['segundos'] % 3600) // 60:02d}",
            "TMA": f"{tma_t // 60:02d}:{tma_t % 60:02d}"
        })

    ranking_tecnicos.sort(key=lambda x: x["Total Chamadas"], reverse=True)

    return {
        "total_chamadas_bruto": total_chamadas_bruto,
        "total_atendidas": total_atendidas_tecnicos,
        "total_abandonadas": len(chamadas_abandonadas),
        "chamadas_abandonadas": chamadas_abandonadas,
        "tempo_total_fmt": tempo_total_fmt,
        "tma_fmt": tma_fmt,
        "contagem_clientes": contagem_clientes,
        "reincidentes": clientes_reincidentes,
        "datas_por_cliente": datas_por_cliente,           # <--- Retorna agrupamento de horários
        "fragmentados": clientes_fragmentados,
        "tempo_por_cliente": tempo_por_cliente,
        "ranking_tecnicos": ranking_tecnicos,
        "ligacoes_curtas": ligacoes_curtas
    }

# =========================================================
# INTERFACE GRÁFICA (Streamlit)
# =========================================================
st.title("📊 Análise de Chamadas e Insights Estratégicos")

with st.form("form_filtro"):
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        data_inicio = st.date_input("Data início")

    with col2:
        data_fim = st.date_input("Data fim")

    with col3:
        st.write("")
        st.write("")
        submit = st.form_submit_button("🔍 Consultar")

# =========================================================
# EXIBIÇÃO DOS RESULTADOS
# =========================================================
if submit:
    if not data_inicio or not data_fim:
        st.error("Por favor, selecione as datas de início e fim.")
    else:
        progress_ui = st.empty()
        try:
            dados = buscar_cdr(str(data_inicio), str(data_fim), progress_ui)

            if not dados:
                st.warning("Nenhuma chamada encontrada no período selecionado.")
            else:
                analise = analisar_dados(dados)

                # 1. RESUMO EXECUTIVO
                st.subheader("📌 Resumo Executivo")
                c1, c2, c3, c4 = st.columns(4)

                c1.metric("Total de Chamadas (PABX)", f"{analise['total_chamadas_bruto']}")
                c2.metric("Atendidas por Técnicos", f"{analise['total_atendidas']}")
                c3.metric("Tempo Total Falado", analise["tempo_total_fmt"])
                c4.metric("TMA Médio", analise["tma_fmt"])

                st.divider()

                # 2. SEÇÃO DE LIGAÇÕES CURTAS (< 10s)
                st.subheader("⏱️ Ligações Curtas (Menos de 10 segundos)")
                st.caption("Chamadas encerradas rapidamente. Podem indicar quedas de linha ou enganos.")
                
                if analise["ligacoes_curtas"]:
                    st.warning(f"Foram encontradas {len(analise['ligacoes_curtas'])} ligações com menos de 10 segundos.")
                    st.dataframe(
                        analise["ligacoes_curtas"], 
                        use_container_width=True, 
                        hide_index=True
                    )
                else:
                    st.success("Nenhuma ligação com menos de 10 segundos foi registrada.")

                st.divider()

                # 3. INSIGHTS ANALÍTICOS ESTRATÉGICOS# =========================================================
# INSIGHTS ANALÍTICOS ESTRATÉGICOS (TRECHO ATUALIZADO)
# =========================================================
st.subheader("💡 Insights Analíticos Estratégicos")

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("### 🔁 Reincidência de Clientes (Bina)")
    st.caption("Clientes que ligaram mais de uma vez no período.")
    
    reincidencias_ordenadas = sorted(
        analise["reincidentes"].items(), key=lambda x: x[1], reverse=True
    )

    if reincidencias_ordenadas:
        tabela_reincidencia = []
        for bina, qtd in reincidencias_ordenadas[:10]:
            # Formata a lista de datas/horas separadas por vírgula e quebra de linha
            datas_str = " | ".join(analise["datas_por_cliente"][bina])
            
            tabela_reincidencia.append({
                "Cliente (Bina)": bina,
                "Qtd. Ligações": qtd,
                "Datas / Horários das Chamadas": datas_str
                # Coluna "Tempo Acumulado" removida com sucesso
            })
        st.dataframe(
            tabela_reincidencia, 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info("Nenhum cliente realizou chamadas repetidas no período.")

with col_right:
    st.markdown("### 🔀 Fragmentação no Atendimento")
    st.caption("Clientes que falaram com mais de um funcionário diferente.")

    if analise["fragmentados"]:
        tabela_fragmentacao = []
        for bina, tecs in list(analise["fragmentados"].items())[:10]:
            tabela_fragmentacao.append({
                "Cliente (Bina)": bina,
                "Nº Funcionários": len(tecs),
                "Funcionários": ", ".join(tecs)
            })
        st.dataframe(
            tabela_fragmentacao, 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.success("Nenhum cliente precisou ser atendido por múltiplos funcionários.")
        
                with col_right:
                    st.markdown("### 🔀 Fragmentação no Atendimento")
                    st.caption("Clientes que falaram com mais de um funcionário diferente.")

                    if analise["fragmentados"]:
                        tabela_fragmentacao = []
                        for bina, tecs in list(analise["fragmentados"].items())[:10]:
                            tabela_fragmentacao.append({
                                "Cliente (Bina)": bina,
                                "Nº Funcionários": len(tecs),
                                "Funcionários": ", ".join(tecs)
                            })
                        st.dataframe(
                            tabela_fragmentacao, 
                            use_container_width=True, 
                            hide_index=True
                        )
                    else:
                        st.success("Nenhum cliente precisou ser atendido por múltiplos funcionários.")

                st.divider()

                # 4. CHAMADAS NÃO ATENDIDAS / ABANDONADAS
                st.subheader("⚠️ Chamadas Não Atendidas / Fila (Diferença do PABX)")

                if analise["chamadas_abandonadas"]:
                    st.warning(f"Encontradas {analise['total_abandonadas']} chamadas que não chegaram a ser atendidas por um técnico.")
                    
                    tabela_nao_atendidas = [
                        {
                            "Data/Hora": d["data_hora"],               # <--- Incluído Data/Hora aqui também
                            "Telefone (Cliente/Bina)": d["bina"],
                            "Destino/Fila": d["tecnico"],
                            "Status PABX": d["status"],
                            "Tempo de Espera": d["duracao"]
                        }
                        for d in analise["chamadas_abandonadas"]
                    ]
                    
                    with st.expander("🔍 Clique aqui para ver a lista completa destas chamadas"):
                        st.dataframe(
                            tabela_nao_atendidas, 
                            use_container_width=True, 
                            hide_index=True
                        )
                else:
                    st.success("Todas as chamadas do PABX foram atendidas por técnicos!")

                st.divider()

                # 5. RANKING DE FUNCIONÁRIOS
                st.subheader("👨‍💻 Desempenho da Equipe")
                st.dataframe(
                    analise["ranking_tecnicos"], 
                    use_container_width=True, 
                    hide_index=True
                )

        except Exception as e:
            st.error(f"Erro ao processar a consulta: {e}")
