import io
import re
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

def extrair_dados_e_metadados(pdf_bytes):
    meta = {
        "cedente": "Não identificado",
        "periodo": "Não identificado"
    }
    
    boletos_liquidados = []
    
    with pdfplumber.open(pdf_bytes) as pdf:
        texto_bruto_paginas = []
        todas_linhas_agrupadas = []
        
        for page in pdf.pages:
            t = page.extract_text() or ""
            texto_bruto_paginas.append(t)
            
            # Agrupa palavras pela coordenada vertical (top) com margem de tolerância de 3px
            words = page.extract_words()
            linhas_dict = {}
            for w in words:
                y = round(w['top'] / 3.5) * 3.5
                if y not in linhas_dict:
                    linhas_dict[y] = []
                linhas_dict[y].append(w)
            
            for y in sorted(linhas_dict.keys()):
                # Ordena as palavras da esquerda para a direita (x0)
                palavras_linha = sorted(linhas_dict[y], key=lambda x: x['x0'])
                texto_linha = " ".join([p['text'] for p in palavras_linha])
                todas_linhas_agrupadas.append(texto_linha)

        texto_completo = "\n".join(texto_bruto_paginas)
        
        # Extração do Cedente
        match_cedente = re.search(r'Cedente\s*:\s*(?:[\d\.\-\/]*\s*-\s*)?([^\n\:]+)', texto_completo, re.IGNORECASE)
        if match_cedente:
            nome_cedente = match_cedente.group(1).strip()
            nome_cedente = re.sub(r'::.*$', '', nome_cedente).strip()
            meta["cedente"] = nome_cedente
            
        # Extração do Período
        match_periodo = re.search(r'a partir de\s*([\d\/]+)', texto_completo, re.IGNORECASE)
        if match_periodo:
            meta["periodo"] = f"A partir de {match_periodo.group(1).strip()}"

    documentos_processados = set()

    for i, linha in enumerate(todas_linhas_agrupadas):
        linha_upper = linha.upper()
        
        # Identifica a linha de liquidação com indicação de crédito (C)
        if 'LIQUIDACAO' in linha_upper and ('BLOQUETO' in linha_upper or 'COMPENSACAO' in linha_upper or re.search(r'[\d\.]+\,\d{2}\s*C', linha)):
            
            # Janela de contexto com a linha atual e as anteriores imediatas
            janela = todas_linhas_agrupadas[max(0, i-4):i+1]
            bloco_str = " ".join(janela)
            
            # Captura Nosso Número (14 a 17 dígitos)
            match_doc = re.search(r'\b(\d{14,17})\b', bloco_str)
            nosso_no = match_doc.group(1) if match_doc else f"DOC_{i}"
            
            # Evita duplicidades (como a linha adicional da tarifa de débito)
            if nosso_no in documentos_processados:
                continue
            documentos_processados.add(nosso_no)

            # Captura datas (dd/mm/aaaa)
            datas = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', bloco_str)
            vencto = datas[0] if len(datas) >= 1 else "-"
            data_pgto = datas[1] if len(datas) >= 2 else (datas[0] if len(datas) == 1 else "-")

            # Captura o valor de liquidação (crédito final terminado em C)
            val_credito = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*C', bloco_str)
            valores_gerais = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', bloco_str)
            
            if val_credito:
                v_pago_str = val_credito[0]
            elif len(valores_gerais) >= 2:
                v_pago_str = valores_gerais[1]
            elif len(valores_gerais) == 1:
                v_pago_str = valores_gerais[0]
            else:
                v_pago_str = "0,00"

            v_orig_str = valores_gerais[0] if valores_gerais else v_pago_str
            
            v_orig = float(v_orig_str.replace('.', '').replace(',', '.'))
            v_pago = float(v_pago_str.replace('.', '').replace(',', '.'))

            # Extração de Nome do Pagador e Seu Nº (Imóvel)
            termos_bloqueio = {'LIQUIDACAO', 'BLOQUETO', 'COMPENSACAO', 'SIM', 'NAO', 'CIP', 'TARIFA', 'DEB/CRED'}
            palavras_identificadas = []
            
            for l_j in janela:
                # Remove datas, valores e números de controle
                limpo = re.sub(r'\b\d{2}/\d{2}/\d{4}\b', '', l_j)
                limpo = re.sub(r'\b\d{1,3}(?:\.\d{3})*,\d{2}[CD]?\b', '', limpo)
                limpo = re.sub(r'\b\d{10,18}\b', '', limpo)
                tokens = [t for t in limpo.split() if t.upper() not in termos_bloqueio and len(t) > 0]
                if tokens:
                    palavras_identificadas.extend(tokens)
            
            # O primeiro número ou código curto costuma ser o 'Seu N°' (Imóvel)
            seu_no = "-"
            nome_pagador_tokens = []
            
            for token in palavras_identificadas:
                if seu_no == "-" and (token.isalnum() and len(token) <= 6 and not token.isalpha()):
                    seu_no = token
                elif seu_no == "-" and any(kw in token.upper() for kw in ['SALA', 'MOD', 'APTO', 'LOJA', 'SL']):
                    seu_no = token
                else:
                    nome_pagador_tokens.append(token)
                    
            nome_pagador = " ".join(nome_pagador_tokens).strip()
            if not nome_pagador:
                nome_pagador = "Não identificado"

            boletos_liquidados.append({
                "Nome do Pagador": nome_pagador,
                "Nome do Imóvel": seu_no,
                "Data de Vencimento": vencto,
                "Data de Pagamento": data_pgto,
                "Valor Original": v_orig,
                "Valor Original Formatado": f"R$ {v_orig_str}",
                "Valor Pago": v_pago,
                "Valor Pago Formatado": f"R$ {v_pago_str}",
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
    meta, df_boletos = extrair_dados_e_metadados(arquivo_pdf)
    
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
