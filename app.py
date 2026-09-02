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

st.title("📊 Consulta Extrato e-Cobrança - Boletos Liquidados")

arquivo_pdf = st.file_uploader("Arraste e solte o PDF do extrato de cobrança aqui", type=["pdf"])

def extrair_dados_e_metadados(pdf_bytes):
    meta = {
        "cedente": "Não identificado",
        "periodo": "Não identificado"
    }
    
    boletos_liquidados = []
    
    with pdfplumber.open(pdf_bytes) as pdf:
        primeira_pagina = pdf.pages[0].extract_text() or ""
        
        # Extração do Cedente
        match_cedente = re.search(r'Cedente\s*:\s*\d*\s*([^\n]+)', primeira_pagina, re.IGNORECASE)
        if match_cedente:
            meta["cedente"] = match_cedente.group(1).strip()
            
        # Extração do Período
        match_periodo = re.search(r'a partir de\s*([\d\/]+)', primeira_pagina, re.IGNORECASE)
        if match_periodo:
            meta["periodo"] = f"A partir de {match_periodo.group(1).strip()}"

        texto_completo = ""
        for page in pdf.pages:
            texto_completo += (page.extract_text() or "") + "\n"

    # Regex para capturar os blocos de liquidação
    padrao_liquidacao = re.compile(
        r'(\d{10,18})\s*\|\s*([^\|]+)\s*\|\s*([^\|]*)\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*([\d\.\,]+)\s*\|\s*([\d\.\,]+)\s*\|\s*[^\|]*\|\s*([^\|]*LIQUIDACAO[^\|]*)',
        re.MULTILINE | re.DOTALL
    )

    matches = padrao_liquidacao.findall(texto_completo)

    for m in matches:
        nossa_no, nome_sacado, seu_no, vencto, data_pgto, valor_titulo, liq_recebido, historico = m
        
        if "LIQUIDACAO" in historico.upper() and "BLOQUETO" in historico.upper():
            v_orig = float(valor_titulo.replace('.', '').replace(',', '.'))
            v_pago = float(liq_recebido.replace('.', '').replace(',', '.'))
            
            boletos_liquidados.append({
                "Nossa No": nossa_no.strip(),
                "Nome do Pagador": " ".join(nome_sacado.split()),
                "Nome do Imóvel": " ".join(seu_no.split()) if seu_no.strip() else "-",
                "Data de Vencimento": vencto.strip(),
                "Data de Pagamento": data_pgto.strip(),
                "Valor Original": v_orig,
                "Valor Original Formatado": f"R$ {valor_titulo.strip()}",
                "Valor Pago": v_pago,
                "Valor Pago Formatado": f"R$ {liq_recebido.strip()}",
                "Status": "Liquidado (Bloqueto - Compensação)"
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

    # HTML com formatação compatível com xhtml2pdf
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
                    <font size="3"><b>CONSULTA EXTRATO E-COBRANÇA</b></font><br/>
                    <b>CEDENTE:</b> {meta['cedente']}
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
                    <th width="20%">Nome do Imóvel (Seu N°)</th>
                    <th width="10%">Data Venc.</th>
                    <th width="10%">Data Pagto</th>
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
            st.error("Erro ao gerar o PDF. Verifique a estrutura HTML.")
    else:
        st.warning("Nenhum boleto liquidado foi encontrado no extrato enviado.")
