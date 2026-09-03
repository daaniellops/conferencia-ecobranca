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
            texto_completo += (page.extract_text(layout=True) or page.extract_text() or "") + "\n"
            
        # Extração do Cedente
        match_cedente = re.search(r'Cedente\s*:\s*(?:[\d\.\-\/]*\s*-\s*)?([^\n\:]+)', texto_completo, re.IGNORECASE)
        if match_cedente:
            nome_cedente = match_cedente.group(1).strip()
            # Remove sufixos como :: Consulta Extrato
            nome_cedente = re.sub(r'::.*$', '', nome_cedente).strip()
            meta["cedente"] = nome_cedente
            
        # Extração do Período
        match_periodo = re.search(r'a partir de\s*([\d\/]+)', texto_completo, re.IGNORECASE)
        if match_periodo:
            meta["periodo"] = f"A partir de {match_periodo.group(1).strip()}"

    # Expressão regular focada na linha única de liquidação (Crédito 'C')
    # Formato típico: NossoNo | SeuNo | Nome | Vencto | DataPgto | ValorTitulo | LiqRecebido | ... | ValorC LIQUIDACAO
    linhas = texto_completo.split('\n')
    
    nosso_nos_processados = set()
    
    for i, linha in enumerate(linhas):
        linha_upper = linha.upper()
        
        # Filtra estritamente a linha de crédito da liquidação, ignorando tarifas (D)
        if 'LIQUIDACAO' in linha_upper and re.search(r'[\d\.]+\,\d{2}\s*C', linha):
            
            # Busca o Nosso Nº (14 a 17 dígitos) na linha atual ou na anterior
            match_doc = re.search(r'\b(\d{14,17})\b', linha)
            if not match_doc and i > 0:
                match_doc = re.search(r'\b(\d{14,17})\b', linhas[i-1])
                
            nosso_no = match_doc.group(1) if match_doc else None
            
            # Evita duplicações do mesmo documento
            if nosso_no and nosso_no in nosso_nos_processados:
                continue
            if nosso_no:
                nosso_nos_processados.add(nosso_no)

            # Extração de datas (Vencto e Data Pgto)
            # Podem estar na linha atual ou divididas entre a linha anterior e a atual
            contexto_datas = (linhas[i-1] if i > 0 else "") + " " + linha
            datas = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', contexto_datas)
            
            vencto = datas[0] if len(datas) >= 1 else "-"
            data_pgto = datas[1] if len(datas) >= 2 else vencto
            
            # Extração dos valores de liquidação
            match_credito = re.search(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*C', linha)
            valor_pago_str = match_credito.group(1) if match_credito else "0,00"
            
            # O valor original costuma ser igual ao valor liquidado
            todos_valores = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', contexto_datas)
            valor_orig_str = todos_valores[0] if todos_valores else valor_pago_str
            
            v_orig = float(valor_orig_str.replace('.', '').replace(',', '.'))
            v_pago = float(valor_pago_str.replace('.', '').replace(',', '.'))
            
            # Isolamento do Seu N° (Imóvel) e Nome Sacado (Pagador)
            # Analisa o miolo entre o documento e as datas
            contexto_texto = linha
            if nosso_no:
                contexto_texto = re.sub(r'^\s*' + nosso_no, '', contexto_texto)
            contexto_texto = re.sub(r'\b\d{2}/\d{2}/\d{4}\b.*$', '', contexto_texto).strip()
            
            # Se o texto estiver na linha anterior ou na acima
            if len(contexto_texto) < 3 and i > 0:
                contexto_texto = re.sub(r'^\s*\d{14,17}', '', linhas[i-1])
                contexto_texto = re.sub(r'\b\d{2}/\d{2}/\d{4}\b.*$', '', contexto_texto).strip()

            partes_dados = contexto_texto.split()
            
            # O primeiro elemento após o documento é o 'Seu N°'
            if partes_dados:
                seu_no = partes_dados[0]
                nome_sacado = " ".join(partes_dados[1:])
                # Caso o nome esteja quebrado nas linhas seguintes/anteriores
                if not nome_sacado and i > 0:
                    nome_sacado = linhas[i-1].strip()
            else:
                seu_no = "-"
                nome_sacado = "Não identificado"
                
            # Limpeza final dos nomes
            nome_sacado = re.sub(r'[\d\.\,\:\-\/]', '', nome_sacado).strip()
            if not nome_sacado:
                nome_sacado = "Não identificado"

            boletos_liquidados.append({
                "Nome do Pagador": nome_sacado,
                "Nome do Imóvel": seu_no,
                "Data de Vencimento": vencto,
                "Data de Pagamento": data_pgto,
                "Valor Original": v_orig,
                "Valor Original Formatado": f"R$ {valor_orig_str}",
                "Valor Pago": v_pago,
                "Valor Pago Formatado": f"R$ {valor_pago_str}",
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
