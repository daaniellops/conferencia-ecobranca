import io
import re
import unicodedata
from datetime import datetime
import pandas as pd
import pdfplumber
import streamlit as st
from xhtml2pdf import pisa

st.set_page_config(
    page_title="Consulta Extrato e-Cobrança",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Consulta Extrato e-Cobrança")

arquivo_pdf = st.file_uploader("Arraste e solte o PDF do extrato de cobrança aqui", type=["pdf"])

def normalizar(texto):
    if not texto:
        return ""
    # Remove acentos (ex: LIQUIDAÇÃO -> LIQUIDACAO)
    nfkd = unicodedata.normalize('NFKD', texto)
    return u"".join([c for c in nfkd if not unicodedata.combining(c)]).upper()

def extrair_dados_e_metadados(pdf_bytes):
    meta = {
        "cedente": "Não identificado",
        "periodo": "Não identificado"
    }
    
    boletos_liquidados = []
    texto_bruto_acumulado = ""
    
    with pdfplumber.open(pdf_bytes) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            texto_bruto_acumulado += t + "\n"

    # Identificação do Cedente
    match_cedente = re.search(r'Cedente\s*:\s*(?:[\d\.\-\/]*\s*-\s*)?([^\n\:]+)', texto_bruto_acumulado, re.IGNORECASE)
    if match_cedente:
        c_nome = match_cedente.group(1).strip()
        c_nome = re.sub(r'::.*$', '', c_nome).strip()
        meta["cedente"] = c_nome
        
    # Identificação do Período
    match_periodo = re.search(r'a partir de\s*([\d\/]+)', texto_bruto_acumulado, re.IGNORECASE)
    if match_periodo:
        meta["periodo"] = f"A partir de {match_periodo.group(1).strip()}"

    # Limpeza e separação de linhas
    linhas_originais = [l.strip() for l in texto_bruto_acumulado.split('\n') if l.strip()]
    linhas_norm = [normalizar(l) for l in linhas_originais]

    documentos_processados = set()

    for idx, l_norm in enumerate(linhas_norm):
        # Condição 1: A linha possui um valor de crédito final (ex: 282,19C ou 5.608,72 C)
        # Condição 2: Está associada a LIQUIDACAO (na mesma linha ou no bloco vizinho)
        match_cred = re.search(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*C\b', l_norm)
        
        if match_cred:
            # Pega janela de contexto ao redor da ocorrência
            inicio = max(0, idx - 6)
            fim = min(len(linhas_norm), idx + 4)
            bloco_norm = " ".join(linhas_norm[inicio:fim])
            bloco_orig = " ".join(linhas_originais[inicio:fim])

            # Confirma que se trata de uma liquidação (ignora registros sem liquidação)
            if 'LIQUIDAC' in bloco_norm or 'BLOQUETO' in bloco_norm:
                
                # Identifica o Nosso Número para evitar duplicidades
                match_doc = re.search(r'\b(\d{14,17})\b', bloco_norm)
                doc_id = match_doc.group(1) if match_doc else f"ID_{idx}"
                
                if doc_id in documentos_processados:
                    continue
                documentos_processados.add(doc_id)

                # Captura datas (dd/mm/aaaa)
                datas = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', bloco_orig)
                vencto = datas[0] if len(datas) >= 1 else "-"
                data_pgto = datas[1] if len(datas) >= 2 else vencto

                # Valores
                val_pago_str = match_cred.group(1)
                todos_valores = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', bloco_orig)
                val_orig_str = todos_valores[0] if todos_valores else val_pago_str

                v_orig = float(val_orig_str.replace('.', '').replace(',', '.'))
                v_pago = float(val_pago_str.replace('.', '').replace(',', '.'))

                # Extração de texto para Pagador e Imóvel
                termos_ignorar = {
                    'CAIXA', 'CEDENTE', 'NOSSA', 'SACADO', 'SEU', 'VENCTO', 'DATA', 
                    'PAGTO', 'VALOR', 'TITULO', 'LIQ', 'RECEBIDO', 'DESC/ABAT', 
                    'ENC/DESP', 'DEB/CRED', 'HISTORICO', 'CIP', 'LIQUIDACAO', 
                    'BLOQUETO', 'COMPENSACAO', 'SIM', 'NAO', 'NO', 'EXTRATO', 'CONSULTA'
                }

                palavras_validas = []
                for lin in linhas_originais[inicio:idx+1]:
                    limpa = re.sub(r'\b\d{2}/\d{2}/\d{4}\b', '', lin)
                    limpa = re.sub(r'\b\d{1,3}(?:\.\d{3})*,\d{2}[CD]?\b', '', limpa)
                    limpa = re.sub(r'\b\d{10,18}\b', '', limpa)
                    for tok in limpa.split():
                        tok_clean = re.sub(r'[^\w]', '', tok)
                        if normalizar(tok_clean) not in termos_ignorar and len(tok_clean) > 0:
                            palavras_validas.append(tok)

                # Seu N° costuma ser a primeira palavra alfanumérica curta ou indicativo de sala/imóvel
                seu_no = "-"
                pagador_toks = []
                for p in palavras_validas:
                    p_norm = normalizar(p)
                    if seu_no == "-" and (p.isalnum() and len(p) <= 6 and not p.isalpha()):
                        seu_no = p
                    elif seu_no == "-" and any(k in p_norm for k in ['SALA', 'MOD', 'APTO', 'LOJA', 'SL']):
                        seu_no = p
                    else:
                        pagador_toks.append(p)

                nome_pagador = " ".join(pagador_toks).strip()
                if not nome_pagador:
                    nome_pagador = "Não identificado"

                boletos_liquidados.append({
                    "Nome do Pagador": nome_pagador,
                    "Nome do Imóvel": seu_no,
                    "Data de Vencimento": vencto,
                    "Data de Pagamento": data_pgto,
                    "Valor Original": v_orig,
                    "Valor Original Formatado": f"R$ {val_orig_str}",
                    "Valor Pago": v_pago,
                    "Valor Pago Formatado": f"R$ {val_pago_str}",
                    "Status": "Liquidado"
                })

    return meta, pd.DataFrame(boletos_liquidados), texto_bruto_acumulado

def fmt_brl(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def gerar_pdf_relatorio(meta, df_boletos):
    data_emissao = datetime.now().strftime("%d/%m/%Y")
    total_creditos = df_boletos['Valor Pago'].sum() if not df_boletos.empty else 0.0
    
    linhas_tabela = ""
    for idx, row in df_boletos.iterrows():
        linhas_tabela += f"""
        <tr>
            <td align="center">{idx+1:02d}</td>
            <td>{row['Nome do Pagador']}</td>
            <td align="center">{row['Nome do Imóvel']}</td>
            <td align="center">{row['Data de Vencimento']}</td>
            <td align="center">{row['Data de Pagamento']}</td>
            <td align="right">{row['Valor Original Formatado']}</td>
            <td align="right"><b>{row['Valor Pago Formatado']}</b></td>
            <td align="center">Liquidado</td>
        </tr>
        """

    html_full = f"""
    <html>
    <head>
        <style>
            @page {{ size: a4 landscape; margin: 1cm; }}
            body {{ font-family: Helvetica, Arial, sans-serif; font-size: 8pt; color: #111111; }}
            .header-table {{ width: 100%; background-color: #1e3a8a; color: #ffffff; padding: 8px; margin-bottom: 10px; }}
            .info-table {{ width: 100%; background-color: #f1f5f9; padding: 6px; margin-bottom: 10px; border: 1px solid #cbd5e1; }}
            table.data-table {{ width: 100%; border-collapse: collapse; }}
            table.data-table th {{ background-color: #e2e8f0; padding: 5px; font-size: 7.5pt; border-bottom: 1px solid #94a3b8; }}
            table.data-table td {{ padding: 5px; border-bottom: 1px solid #e2e8f0; font-size: 7.5pt; }}
            .total-box {{ background-color: #dcfce7; border: 1px solid #86efac; padding: 8px; font-size: 9.5pt; font-weight: bold; color: #166534; text-align: right; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td>
                    <font size="3"><b>CONSULTA EXTRATO E-COBRANÇA (CEDENTE: {meta['cedente']})</b></font>
                </td>
            </tr>
        </table>
        
        <table class="info-table">
            <tr>
                <td><b>Período:</b> {meta['periodo']}</td>
                <td align="right"><b>Data de Emissão:</b> {data_emissao}</td>
            </tr>
        </table>

        <table class="data-table">
            <thead>
                <tr>
                    <th width="4%">Item</th>
                    <th width="28%">Nome do Pagador</th>
                    <th width="14%">Nome do Imóvel (Seu Nº)</th>
                    <th width="11%">Data Vencimento</th>
                    <th width="11%">Data Pagamento</th>
                    <th width="12%">Valor Original</th>
                    <th width="12%">Valor Pago</th>
                    <th width="8%">Situação</th>
                </tr>
            </thead>
            <tbody>
                {linhas_tabela}
            </tbody>
        </table>

        <div class="total-box">
            VALOR TOTAL DE CRÉDITOS: {fmt_brl(total_creditos)}
        </div>
    </body>
    </html>
    """
    
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(src=io.StringIO(html_full), dest=pdf_buffer)
    
    if pisa_status.err:
        return None
        
    return pdf_buffer.getvalue()

if arquivo_pdf is not None:
    meta, df_boletos, texto_extraido = extrair_dados_e_metadados(arquivo_pdf)
    
    if not df_boletos.empty:
        st.subheader(f"CONSULTA EXTRATO E-COBRANÇA (CEDENTE: {meta['cedente']})")
        st.info(f"**Período:** {meta['periodo']}")
        
        total_creditos = df_boletos['Valor Pago'].sum()
        
        st.metric("VALOR TOTAL DE CRÉDITOS", fmt_brl(total_creditos))
        st.divider()
        
        st.markdown("### 🟢 Boletos Liquidados")
        st.dataframe(
            df_boletos[[
                'Nome do Pagador', 
                'Nome do Imóvel', 
                'Data de Vencimento', 
                'Data de Pagamento', 
                'Valor Original Formatado', 
                'Valor Pago Formatado',
                'Status'
            ]].rename(columns={
                'Nome do Imóvel': 'Nome do Imóvel (Seu Nº)',
                'Valor Original Formatado': 'Valor Original',
                'Valor Pago Formatado': 'Valor Pago'
            }),
            use_container_width=True
        )
        
        pdf_out = gerar_pdf_relatorio(meta, df_boletos)
        
        if pdf_out:
            st.download_button(
                label="📄 Baixar Relatório Ajustado em PDF",
                data=pdf_out,
                file_name=f"Extrato_E_Cobranca_{meta['cedente'].replace(' ', '_')}.pdf",
                mime="application/pdf"
            )
        else:
            st.error("Erro ao gerar o PDF.")
    else:
        st.warning("Nenhum boleto liquidado foi encontrado no extrato enviado.")
        with st.expander("🔍 Diagnóstico do Texto Extraído do PDF"):
            st.text(texto_extraido)
