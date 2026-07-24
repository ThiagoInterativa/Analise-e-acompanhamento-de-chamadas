import streamlit as st
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
from collections import Counter, defaultdict

# ===== CONFIG =====
login_url = "https://pabx.evence.com.br/login"
cdr_url = "https://pabx.evence.com.br/cdr/pesquisar"

email = "suporte@interativanet.com.br"
senha = "smk03657"

# =========================================================
# SESSÃO REUTILIZÁVEL
# =========================================================
@st.cache_resource
def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0"
    })
    return session

# =========================================================
# LOGIN NO PABX
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
# RETRY
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
# BUSCA CDR (EXTRAI NÚMERO DE ORIGEM)
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

            # Mapeamento assumindo padrão de tabela CDR HTML:
            # ex: cols[1]=Origem, cols[4]=Técnico/Destino, cols[5]=Duração
            if len(cols) >= 6:
                cliente = cols[1].get_text(strip=True) if len(cols) > 1 else "Desconhecido"
                tecnico = cols[4].get_text(strip=True)
                duracao = cols[5].get_text(strip=True)

                if "Fila" in tecnico:
                    continue

                try:
                    h, m, s = duracao.split(":")
                    segundos = int(h) * 3600 + int(m) * 60 + int(s)
                except ValueError:
                    segundos = 0

                dados.append({
                    "cliente": cliente,
                    "tecnico": tecnico,
                    "duracao": duracao,
                    "segundos": segundos
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
# ANÁLISE E INSIGHTS ESTRATÉGICOS
# =========================================================
def analisar_dados(dados):
    total_chamadas = len(dados)
    if total_chamadas == 0:
        return None

    segundos_totais = sum(d["segundos"] for d in dados)
    
    # Horas e Minutos Formatados
    horas = int(segundos_totais // 3600)
    minutos = int((segundos_totais % 3600) // 60)
    tempo_total_fmt = f"{horas}h {minutos}m"

    # TMA
    tma_seg = int(round(segundos_totais / total_chamadas))
    tma_fmt = f"{tma_seg // 60:02d}:{tma_seg % 60:02d}"

    # Frequência de chamadas por cliente
    contagem_clientes = Counter([d["cliente"] for d in dados if d["cliente"]])
    clientes_reincidentes = {k: v for k, v in contagem_clientes.items() if v > 1}
    
    # Mapeamento de fragmentação (Atendimento por múltiplos técnicos)
    tecnicos_por_cliente = defaultdict(set)
    tempo_por_cliente = defaultdict(int)

    for d in dados:
        cli = d["cliente"]
        tecnicos_por_cliente[cli].add(d["tecnico"])
        tempo_por_cliente[cli] += d["segundos"]

    # Clientes atendidos por mais de 1 técnico
    clientes_fragmentados = {
        cli: list(tecs) for cli, tecs in tecnicos_por_cliente.items() if len(tecs) > 1
    }

    # Desempenho dos funcionários
    desempenho_tecnicos = defaultdict(lambda: {"chamadas": 0, "segundos": 0})
    for d in dados:
        tec = d["tecnico"]
        desempenho_tecnicos[tec]["chamadas"] += 1
        desempenho_tecnicos[tec]["segundos"] += d["segundos"]

    ranking_tecnicos = []
    for tec, info in desempenho_tecnicos.items():
        tma_t = int(round(info["segundos"] / info["chamadas"])) if info["chamadas"] > 0 else 0
        ranking_tecnicos.append({
            "Técnico": tec,
            "Total Chamadas": info["chamadas"],
            "Tempo Total (h)": f"{info['segundos'] // 3600:02d}:{(info['segundos'] % 3600) // 60:02d}",
            "TMA": f"{tma_t // 60:02d}:{tma_t % 60:02d}"
        })

    ranking_tecnicos.sort(key=lambda x: x["Total Chamadas"], reverse=True)

    return {
        "total_chamadas": total_chamadas,
        "tempo_total_fmt": tempo_total_fmt,
        "tma_fmt": tma_fmt,
        "contagem_clientes": contagem_clientes,
        "reincidentes": clientes_reincidentes,
        "fragmentados": clientes_fragmentados,
        "tempo_por_cliente": tempo_por_cliente,
        "ranking_tecnicos": ranking_tecnicos
    }

# =========================================================
# INTERFACE STREAMLIT
# =========================================================
st.set_page_config(page_title="Análise de Chamadas", layout="wide")

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
# DASHBOARD DE RESULTADOS
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
                
                c1.metric("Valor Total de Ligações", f"{analise['total_chamadas']} chamadas")
                c2.metric("Tempo Total em Ligação", analise["tempo_total_fmt"])
                c3.metric("Tempo Médio de Atendimento (TMA)", analise["tma_fmt"])
                
                pct_reincidencia = (len(analise["reincidentes"]) / len(analise["contagem_clientes"])) * 100 if analise["contagem_clientes"] else 0
                c4.metric("Taxa de Reincidência de Clientes", f"{pct_reincidencia:.1f}%")

                st.divider()

                # 2. INSIGHTS ANALÍTICOS ESTRATÉGICOS
                st.subheader("💡 Insights Analíticos Estratégicos")

                col_left, col_right = st.columns(2)

                with col_left:
                    st.markdown("### 🔁 Reincidência e Clientes que Mais Ligaram")
                    st.caption("Números de telefone que ligaram repetidamente no período.")
                    
                    reincidencias_ordenadas = sorted(
                        analise["reincidentes"].items(), key=lambda x: x[1], reverse=True
                    )

                    if reincidencias_ordenadas:
                        tabela_reincidencia = []
                        for numero, qtd in reincidencias_ordenadas[:10]:
                            seg_totais = analise["tempo_por_cliente"][numero]
                            tabela_reincidencia.append({
                                "Telefone / Cliente": numero,
                                "Qtd. Ligações": qtd,
                                "Tempo Total": f"{seg_totais // 3600:02d}:{(seg_totais % 3600) // 60:02d}"
                            })
                        st.table(tabela_reincidencia)
                    else:
                        st.info("Nenhum cliente realizou ligações repetidas no período.")

                with col_right:
                    st.markdown("### 🔀 Fragmentação no Atendimento")
                    st.caption("Clientes atendidos por múltiplos funcionários (possível retrabalho ou falta de resolução rápida).")

                    if analise["fragmentados"]:
                        tabela_fragmentacao = []
                        for cliente, tecs in list(analise["fragmentados"].items())[:10]:
                            tabela_fragmentacao.append({
                                "Telefone / Cliente": cliente,
                                "Nº Funcionários": len(tecs),
                                "Funcionários Envolvidos": ", ".join(tecs)
                            })
                        st.table(tabela_fragmentacao)
                    else:
                        st.success("Não houve fragmentação. Os clientes foram atendidos sempre pelo mesmo funcionário.")

                st.divider()

                # 3. PERFORMANCE DA EQUIPE
                st.subheader("👨‍💻 Desempenho e Produtividade dos Funcionários")
                st.table(analise["ranking_tecnicos"])

        except Exception as e:
            st.error(f"Erro ao processar a consulta: {e}")
