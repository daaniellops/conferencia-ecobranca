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
        primeira_pagina = pdf.pages[0].extract_text() or ""
        
        # Extração do Cedente
        match_cedente = re.search(r'Cedente\s*:\s*\d*\s*([^\n]+)', primeira_pagina, re.IGNORECASE)
        if match_cedente:
            meta["cedente"] = match_cedente.group(1).strip()
            
        # Extração do Período
        match_periodo = re.search(r'a partir de\s*([\d\/]+)', primeira_pagina, re.IGNORECASE)
        if match_periodo:
            meta["periodo"] = f"A partir de {match_periodo.group(1).strip()}"

        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Garante que a linha tenha colunas suficientes e não seja cabeçalho/rodape
                    if not row or len(row) < 7:
                        continue
                    
                    # Unifica o texto das colunas para verificação
                    texto_linha = " ".join([str(cell) for cell in row if cell]).replace('\n', ' ')
                    
                    # Filtra apenas registros de LIQUIDAÇÃO (ignora Tarifas e Registros)
                    if 'LIQUIDACAO' in texto_linha.upper() and ('BLOQUETO' in texto_linha.upper() or 'COMPENSACAO' in texto_linha.upper()):
                        
                        # Limpeza do Nome Sacado e Seu N° (Nome do Imóvel)
                        raw_sacado = str(row[1]).replace('\n', ' ').strip() if len(row) > 1 and row[1] else ""
                        raw_seu_no = str(row[2]).replace('\n', ' ').strip() if len(row) > 2 and row[2] else ""
                        
                        # Tratamento das datas e valores
                        vencto = str(row[3]).replace('\n', ' ').strip() if len(row) > 3 and row[3] else "-"
                        data_pgto = str(row[4]).replace('\n', ' ').strip() if len(row) > 4 and row[4] else "-"
                        val_titulo_str = str(row[5]).replace('\n', ' ').strip() if len(row) > 5 and row[5] else "0,00"
                        liq_rec_str = str(row[6]).replace('\n', ' ').strip() if len(row) > 6 and row[6] else "0,00"
                        
                        # Extrai apenas valores numéricos formatados
                        match_v1 = re.search(r'[\d\.]+\,\d{2}', val_titulo_str)
                        match_v2 = re.search(r'[\d\.]+\,\d{2}', liq_rec_str)
                        
                        v_orig_str = match_v1.group(0) if match_v1 else "0,00"
                        v_pago_str = match_v2.group(0) if match_v2 else "0,00"
                        
                        v_orig = float(v_orig_str.replace('.', '').replace(',', '.'))
                        v_pago = float(v_pago_str.replace('.', '').replace(',', '.'))
                        
                        nome_pagador = " ".join(raw_sacado.split()) if raw_sacado else "Não identificado"
                        nome_imovel = " ".join(raw_seu_no.split()) if raw_seu_no else "-"
                        
                        boletos_liquidados.append({
                            "Nome do Pagador": nome_pagador,
                            "Nome do Imóvel": nome_imovel,
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
