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
        texto_completo = ""
        for page in pdf.pages:
            texto_completo += (page.extract_text() or "") + "\n"
            
        # Extração do Cedente
        match_cedente = re.search(r'Cedente\s*:\s*\d*\s*([^\n]+)', texto_completo, re.IGNORECASE)
        if match_cedente:
            meta["cedente"] = match_cedente.group(1).strip()
            
        # Extração do Período
        match_periodo = re.search(r'a partir de\s*([\d\/]+)', texto_completo, re.IGNORECASE)
        if match_periodo:
            meta["periodo"] = f"A partir de {match_periodo.group(1).strip()}"

    # Divide o texto do PDF usando como separador o padrão 'Nossa No' (15 a 17 dígitos numéricos)
    blocos = re.split(r'(?=\b\d{15,17}\b)', texto_completo)

    for bloco in blocos:
        # Verifica se o bloco contém uma liquidação de crédito (ex: LIQUIDACAO ... C)
        if 'LIQUIDACAO' in bloco.upper() and re.search(r'[\d\.]+\,\d{2}\s*C', bloco):
            linhas = [l.strip() for l in bloco.split('\n') if l.strip()]
            
            # Captura de datas no bloco (dd/mm/aaaa)
            datas = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', bloco)
            vencto = datas[0] if len(datas) >= 1 else "-"
            data_pgto = datas[1] if len(datas) >= 2 else (datas[0] if len(datas) == 1 else "-")
            
            # Captura os valores monetários com indicação de Crédito (C)
            match_valor_credito = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*C', bloco)
            match_todos_valores = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', bloco)
            
            if match_valor_credito:
                val_pago_str = match_valor_credito[0]
            elif len(match_todos_valores) >= 2:
                val_pago_str = match_todos_valores[1]
            elif len(match_todos_valores) == 1:
                val_pago_str = match_todos_valores[0]
            else:
                val_pago_str = "0,00"

            val_orig_str = match_todos_valores[0] if match_todos_valores else val_pago_str

            v_orig = float(val_orig_str.replace('.', '').replace(',', '.'))
            v_pago = float(val_pago_str.replace('.', '').replace(',', '.'))
            
            # Extração e tratamento do Nome Sacado e Nome do Imóvel
            # Filtra palavras do bloco ignorando datas, valores e termos técnicos do extrato
            palavras_ignoradas = {'LIQUIDACAO', 'BLOQUETO', 'COMPENSACAO', 'SIM', 'NAO', 'CIP', 'TARIFA', 'DEB/CRED'}
            linhas_texto = []
            for l in linhas:
                if not re.search(r'\d{2}/\d{2}/\d{4}', l) and not re.search(r'[\d\.]+\,\d{2}', l) and not l.isdigit():
                    partes = [p for p in l.split() if p.upper() not in palavras_ignoradas]
                    if partes:
                        linhas_texto.append(" ".join(partes))
            
            texto_nomes = " ".join(linhas_texto)
            partes_nome = texto_nomes.split()
            
            if len(partes_nome) >= 4:
                meio = len(partes_nome) // 2
                nome_pagador = " ".join(partes_nome[:meio])
                nome_imovel = " ".join(partes_nome[meio:])
            elif partes_nome:
                nome_pagador = " ".join(partes_nome)
                nome_imovel = "-"
            else:
                nome_pagador = "Não identificado"
                nome_imovel = "-"

            boletos_liquidados.append({
                "Nome do Pagador": nome_pagador,
                "Nome do Imóvel": nome_imovel,
                "Data de Vencimento": vencto,
                "Data de Pagamento": data_pgto,
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
            <td>{row['Nome do Imóvel']}</td>
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
                    <th width="26%">Nome do Pagador</th>
                    <th width="20%">Nome do Imóvel</th>
                    <th width="10%">Data Vencimento</th>
                    <th width="10%">Data Pagamento</th>
                    <th width="11%">Valor Original</th>
                    <th width="11%">Valor Pago</th>
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
        st.title(f"CONSULTA EXTRATO E-COBRANÇA (CEDENTE: {meta['cedente']})")
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
