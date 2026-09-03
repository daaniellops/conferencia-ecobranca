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

arquivo_pdf = st.file_uploader("Arraste e solte o PDF do extrato de cobrança aqui", type=["pdf"])

def normalizar(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFKD', texto)
    return u"".join([c for c in nfkd if not unicodedata.combining(c)]).upper()

def extrair_dados_e_metadados(pdf_bytes):
    meta = {
        "responsavel": "Não identificado",
        "cedente": "Não identificado",
        "periodo": "Não identificado"
    }
    
    boletos_liquidados = []
    texto_completo = ""
    
    with pdfplumber.open(pdf_bytes) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            texto_completo += t + "\n"

    linhas_puras = [l.strip() for l in texto_completo.split('\n') if l.strip()]

    # 1. Extração do Responsável pela Conta
    for l in linhas_puras[:8]:
        if re.search(r'\d{3}\.\d{3}\.\d{3}\-\d{2}', l) and 'CEDENTE' not in l.upper():
            meta["responsavel"] = l.strip()
            break

    # 2. Extração do Cedente
    match_cedente = re.search(r'Cedente\s*:\s*([^\n\:]+)', texto_completo, re.IGNORECASE)
    if match_cedente:
        c_nome = match_cedente.group(1).strip()
        c_nome = re.sub(r'::.*$', '', c_nome).strip()
        meta["cedente"] = f"Cedente: {c_nome}"

    # 3. Extração do Período
    match_periodo = re.search(r'a partir de\s*([\d\/]+)', texto_completo, re.IGNORECASE)
    if match_periodo:
        meta["periodo"] = f"A partir de {match_periodo.group(1).strip()}"

    # 4. Extração dos Boletos Liquidados
    documentos_processados = set()
    linhas_norm = [normalizar(l) for l in linhas_puras]

    for idx, l_norm in enumerate(linhas_norm):
        match_cred = re.search(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*C\b', l_norm)
        
        if match_cred:
            inicio = max(0, idx - 6)
            fim = min(len(linhas_norm), idx + 3)
            bloco_norm = " ".join(linhas_norm[inicio:fim])
            
            if 'LIQUIDAC' in bloco_norm or 'BLOQUETO' in bloco_norm:
                match_doc = re.search(r'\b(\d{14,17})\b', bloco_norm)
                doc_id = match_doc.group(1) if match_doc else f"DOC_{idx}"
                
                if doc_id in documentos_processados:
                    continue
                documentos_processados.add(doc_id)

                bloco_orig = " ".join(linhas_puras[inicio:fim])
                datas = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', bloco_orig)
                
                data_vencimento = datas[0] if len(datas) >= 1 else "-"
                data_pagamento = datas[1] if len(datas) >= 2 else data_vencimento

                val_pago_str = match_cred.group(1)
                todos_valores = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', bloco_orig)
                val_orig_str = todos_valores[0] if todos_valores else val_pago_str

                v_orig = float(val_orig_str.replace('.', '').replace(',', '.'))
                v_pago = float(val_pago_str.replace('.', '').replace(',', '.'))

                termos_ignorar = {
                    'CAIXA', 'CEDENTE', 'NOSSA', 'SACADO', 'SEU', 'VENCTO', 'DATA', 
                    'PAGTO', 'VALOR', 'TITULO', 'LIQ', 'RECEBIDO', 'DESC/ABAT', 
                    'ENC/DESP', 'DEB/CRED', 'HISTORICO', 'CIP', 'LIQUIDACAO', 
                    'BLOQUETO', 'COMPENSACAO', 'SIM', 'NAO', 'NO', 'EXTRATO', 'CONSULTA'
                }

                palavras_sacado = []
                for lin in linhas_puras[inicio:idx+1]:
                    l_limpa = re.sub(r'\b\d{2}/\d{2}/\d{4}\b', '', lin)
                    l_limpa = re.sub(r'\b\d{1,3}(?:\.\d{3})*,\d{2}[CD]?\b', '', l_limpa)
                    l_limpa = re.sub(r'\b\d{10,18}\b', '', l_limpa)
                    
                    for token in l_limpa.split():
                        tok_sem_pont = re.sub(r'[^\w]', '', token)
                        if tok_sem_pont.isdigit() and len(tok_sem_pont) <= 5:
                            continue
                        if normalizar(tok_sem_pont) not in termos_ignorar and len(tok_sem_pont) > 0:
                            palavras_sacado.append(token)

                nome_pagador = " ".join(palavras_sacado).strip()
                if not nome_pagador:
                    nome_pagador = "Não identificado"

                boletos_liquidados.append({
                    "Nome do Pagador": nome_pagador,
                    "Data de Vencimento": data_vencimento,
                    "Data de Pagamento": data_pagamento,
                    "Valor Original": v_orig,
                    "Valor Original Formatado": f"R$ {val_orig_str}",
                    "Valor Pago": v_pago,
                    "Valor Pago Formatado": f"R$ {val_pago_str}",
                    "Status": "Liquidado"
                })

    return meta, pd.DataFrame(boletos_liquidados)

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
            <td align="center">{row['Data de Vencimento']}</td>
            <td align="center">{row['Data de Pagamento']}</td>
            <td align="right">{row['Valor Original Formatado']}</td>
            <td align="right">{row['Valor Pago Formatado']}</td>
        </tr>
        """

    # Estrutura com medidas absolutas e sem conflito de padding para evitar a quebra do ReportLab
    html_full = f"""
    <html>
    <head>
        <style>
            @page {{
                size: a4 landscape;
                margin: 10mm;
            }}
            body {{
                font-family: Helvetica, sans-serif;
                font-size: 8pt;
                color: #222222;
            }}
            .header-box {{
                background-color: #1e3a8a;
                color: #ffffff;
                padding: 6pt;
                margin-bottom: 6pt;
            }}
            .info-box {{
                background-color: #f1f5f9;
                padding: 4pt;
                margin-bottom: 8pt;
                border: 0.5pt solid #cbd5e1;
            }}
            table.data-table {{
                width: 100%;
                border-collapse: collapse;
            }}
            table.data-table th {{
                background-color: #e2e8f0;
                font-size: 7.5pt;
                border-bottom: 1pt solid #94a3b8;
                padding: 3pt;
            }}
            table.data-table td {{
                border-bottom: 0.5pt solid #e2e8f0;
                font-size: 7.5pt;
                padding: 3pt;
            }}
            .total-box {{
                background-color: #dcfce7;
                border: 0.5pt solid #86efac;
                padding: 6pt;
                font-size: 9pt;
                font-weight: bold;
                color: #166534;
                text-align: right;
                margin-top: 8pt;
            }}
        </style>
    </head>
    <body>
        <div class="header-box">
            <b><font size="3">CONSULTA EXTRATO E-COBRANÇA</font></b><br/>
            <b>{meta['responsavel']}</b><br/>
            {meta['cedente']}
        </div>
        
        <div class="info-box">
            <b>Período:</b> {meta['periodo']} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Data de Emissão:</b> {data_emissao}
        </div>

        <table class="data-table">
            <thead>
                <tr>
                    <th width="25">Item</th>
                    <th width="320">Nome do Pagador</th>
                    <th width="85">Data de Vencimento</th>
                    <th width="85">Data de Pagamento</th>
                    <th width="90">Valor Original</th>
                    <th width="90">Valor Pago</th>
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
    meta, df_boletos = extrair_dados_e_metadados(arquivo_pdf)
    
    if not df_boletos.empty:
        st.subheader("CONSULTA EXTRATO E-COBRANÇA")
        st.markdown(f"**Responsável:** {meta['responsavel']}")
        st.markdown(f"**{meta['cedente']}**")
        st.info(f"**Período:** {meta['periodo']}")
        
        total_creditos = df_boletos['Valor Pago'].sum()
        
        st.metric("VALOR TOTAL DE CRÉDITOS", fmt_brl(total_creditos))
        st.divider()
        
        st.markdown("### 🟢 Boletos Liquidados")
        st.dataframe(
            df_boletos[[
                'Nome do Pagador', 
                'Data de Vencimento', 
                'Data de Pagamento', 
                'Valor Original Formatado', 
                'Valor Pago Formatado'
            ]].rename(columns={
                'Valor Original Formatado': 'Valor Original',
                'Valor Pago Formatado': 'Valor Pago'
            }),
            use_container_width=True
        )
        
        pdf_out = gerar_pdf_relatorio(meta, df_boletos)
        
        if pdf_out:
            nome_arq_limpo = re.sub(r'[^\w\s-]', '', meta['responsavel']).strip().replace(' ', '_')
            st.download_button(
                label="📄 Baixar Relatório Ajustado em PDF",
                data=pdf_out,
                file_name=f"Extrato_E_Cobranca_{nome_arq_limpo}.pdf",
                mime="application/pdf"
            )
        else:
            st.error("Erro ao gerar o PDF.")
    else:
        st.warning("Nenhum boleto liquidado foi encontrado no extrato enviado.")
