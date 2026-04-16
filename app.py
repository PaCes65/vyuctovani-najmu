import streamlit as st
import pandas as pd
from pypdf import PdfReader
import google.generativeai as genai
import json
import re
import io
from datetime import datetime
try:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    st.error("Chybí knihovna python-docx. Přidejte 'python-docx' do requirements.txt.")
    st.stop()

# ==========================================
# 1. KONFIGURACE A STAV APLIKACE
# ==========================================
st.set_page_config(page_title="Vyúčtování PRO", layout="wide", page_icon="🏢")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("Chybí GEMINI_API_KEY v Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

DEFAULT_DATA = {
    "profil": {"poskytovatel": "", "platce": "", "adresa": "", "byt": "", "typ": ""},
    "osa_najmu": [{"od_mesice": 1, "do_mesice": 12, "najem": 0, "zaloha": 0}],
    "lonsko": {"vysledek": 0, "typ": "Zadne"},
    "naklady": {"svj": [], "dalsi_sluzby": []}
}

if "db" not in st.session_state:
    st.session_state.db = json.loads(json.dumps(DEFAULT_DATA))

# ==========================================
# 2. JÁDRO AI A EXPORT
# ==========================================
@st.cache_resource
def zjisti_model():
    try:
        modely = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for pref in ['models/gemini-1.5-flash', 'models/gemini-2.0-flash-exp', 'models/gemini-pro']:
            if pref in modely: return pref
        return modely[0] if modely else None
    except: return None

def ai_volani(prompt):
    model_name = zjisti_model()
    if not model_name: raise Exception("Nedostupné AI modely.")
    try:
        model = genai.GenerativeModel(model_name)
        res = model.generate_content(prompt)
        match = re.search(r'\{.*\}', res.text, re.DOTALL)
        if match: return json.loads(match.group())
        raise Exception("Nevalidní JSON výstup.")
    except Exception as e:
        raise Exception(f"AI Chyba: {e}")

def cteni_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = "".join(p.extract_text() + "\n" for p in reader.pages if p.extract_text())
        if not text.strip(): raise ValueError("Prázdný textový výstup z PDF.")
        return text
    except Exception as e:
        raise Exception(f"Chyba PDF parseru: {e}")

def generovat_word_protokol(profil, naklady, finance):
    """Generuje formální DOCX protokol v operační paměti."""
    doc = Document()
    
    # Hlavička
    title = doc.add_heading('PROTOKOL O ROČNÍM VYÚČTOVÁNÍ ZÁLOH NA SLUŽBY', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Vygenerováno dne: {datetime.now().strftime('%d.%m.%Y')}\n").alignment = WD_ALIGN_PARAGRAPH.RIGHT
    
    # Smluvní strany
    doc.add_heading('I. Smluvní strany a předmět', level=1)
    p1 = doc.add_paragraph()
    p1.add_run('Klasifikace vztahu: ').bold = True
    p1.add_run(f"{profil.get('typ', 'Neuvedeno')}\n")
    p1.add_run('Předmět: ').bold = True
    p1.add_run(f"{profil.get('adresa', 'Neuvedeno')}, Byt č. {profil.get('byt', 'Neuvedeno')}\n")
    p1.add_run('Poskytovatel: ').bold = True
    p1.add_run(f"{profil.get('poskytovatel', 'Neuvedeno')}\n")
    p1.add_run('Plátce: ').bold = True
    p1.add_run(f"{profil.get('platce', 'Neuvedeno')}")
    
    # Náklady
    doc.add_heading('II. Uznatelné náklady k tíži plátce', level=1)
    if naklady:
        table = doc.add_table(rows=1, cols=2)
        table.style = 'Table Grid'
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = 'Položka'
        hdr_cells[1].text = 'Částka (CZK)'
        for n in naklady:
            row_cells = table.add_row().cells
            row_cells[0].text = str(n.get('nazev', ''))
            row_cells[1].text = f"{n.get('castka', 0):,.2f}"
    else:
        doc.add_paragraph("Žádné evidované náklady.")
        
    # Finanční syntéza
    doc.add_heading('III. Finanční syntéza a výpočet disponibilních záloh', level=1)
    p2 = doc.add_paragraph()
    p2.add_run('1. Úhrn identifikovaných transakcí: ').bold = True
    p2.add_run(f"{finance['suma_transakci']:,.2f} CZK\n")
    p2.add_run('2. Srážka úhrnné pohledávky (Nájemné): ').bold = True
    p2.add_run(f"- {finance['celkova_pohledavka_najem']:,.2f} CZK\n")
    p2.add_run('3. Korekce salda z předchozího období: ').bold = True
    p2.add_run(f"{'+ ' if finance['korekce_saldo'] >= 0 else '- '}{abs(finance['korekce_saldo']):,.2f} CZK\n")
    p2.add_run('Disponibilní zálohy celkem: ').bold = True
    p2.add_run(f"{finance['disponibilni_zalohy']:,.2f} CZK")

    # Zúčtování
    doc.add_heading('IV. Konečné zúčtování', level=1)
    p3 = doc.add_paragraph()
    p3.add_run('Disponibilní zálohy: ').bold = True
    p3.add_run(f"{finance['disponibilni_zalohy']:,.2f} CZK\n")
    p3.add_run('Celkové uznatelné náklady: ').bold = True
    p3.add_run(f"- {finance['uznatelne_naklady']:,.2f} CZK\n")
    
    saldo = finance['saldo_konecne']
    p_res = doc.add_paragraph()
    p_res_run = p_res.add_run(f"KONEČNÉ SALDO: {saldo:,.2f} CZK")
    p_res_run.bold = True
    
    doc.add_paragraph()
    if saldo > 0:
        doc.add_paragraph("Výsledek: PŘEPLATEK. Poskytovatel se zavazuje uhradit tuto částku plátci, "
                          "případně bude po vzájemné dohodě započtena do plateb v následujícím období.")
    elif saldo < 0:
        doc.add_paragraph("Výsledek: NEDOPLATEK. Plátce se zavazuje uhradit tuto částku poskytovateli "
                          "v zákonné či smluvené lhůtě.")
    else:
        doc.add_paragraph("Výsledek: VYROVNÁNO. Žádná ze stran nemá vůči druhé finanční závazek.")

    # Podpisová pole
    doc.add_paragraph('\n\n')
    doc.add_paragraph('V ........................................ dne ........................................')
    doc.add_paragraph('\n\n')
    
    sig_table = doc.add_table(rows=2, cols=2)
    sig_table.columns[0].width = Inches(3.0)
    sig_table.columns[1].width = Inches(3.0)
    
    row0 = sig_table.rows[0].cells
    row0[0].text = '..........................................................'
    row0[1].text = '..........................................................'
    row0[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    row0[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    row1 = sig_table.rows[1].cells
    row1[0].text = f"Poskytovatel: {profil.get('poskytovatel', '')}"
    row1[1].text = f"Plátce: {profil.get('platce', '')}"
    row1[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    row1[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ
# ==========================================
st.title("🏢 Komplexní správa vyúčtování služeb")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. Profil & Smlouvy", "2. Loňské vyúčtování", "3. Letošní náklady", "4. Banka & Protokol", "💾 Data a Uložení"
])

# --- TAB 1: PROFIL A SMLOUVY ---
with tab1:
    st.subheader("Subjektové údaje a časová osa plnění")
    col_pdf1, col_pdf2 = st.columns(2)
    with col_pdf1: sml_1_pdf = st.file_uploader("Zdrojová smlouva (PDF)", type="pdf", key="sml1")
    with col_pdf2: sml_2_pdf = st.file_uploader("Dodatek / Smlouva 2 (PDF)", type="pdf", key="sml2")

    if st.button("Spustit sémantickou analýzu", type="primary", use_container_width=True):
        if not sml_1_pdf: st.warning("Vyžadován minimálně jeden dokument.")
        else:
            with st.spinner("Provádění extrakce dat..."):
                try:
                    text_celkem = f"--- DOK 1 ---\n{cteni_pdf(sml_1_pdf)}\n"
                    if sml_2_pdf: text_celkem += f"--- DOK 2 ---\n{cteni_pdf(sml_2_pdf)}\n"
                    
                    prompt = f"""Analyzuj smlouvy (12 měsíců).
                    1. Subjekty: Podnájemní -> poskytovatel=Nájemce, platce=Podnájemce. Nájemní -> poskytovatel=Pronajímatel, platce=Nájemce.
                    2. Časová osa (osa_najmu): Intervaly od_mesice, do_mesice (1-12). "najem" (čisté), "zaloha" (služby).
                    JSON: {{"profil": {{"typ": "string", "poskytovatel": "string", "platce": "string", "adresa": "string", "byt": "string"}}, "osa_najmu": [{{"od_mesice": int, "do_mesice": int, "najem": int, "zaloha": int}}]}}
                    Text: {text_celkem}"""
                    vysledek_ai = ai_volani(prompt)
                    
                    if vysledek_ai and "osa_najmu" in vysledek_ai:
                        st.session_state.db["profil"] = vysledek_ai["profil"]
                        st.session_state.db["osa_najmu"] = vysledek_ai["osa_najmu"]
                        st.success("Extrakce úspěšná.")
                except Exception as e: st.error(f"Chyba procesingu: {e}")

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.session_state.db["profil"]["poskytovatel"] = st.text_input("Poskytovatel", value=st.session_state.db["profil"].get("poskytovatel", ""))
    with c2: st.session_state.db["profil"]["platce"] = st.text_input("Plátce", value=st.session_state.db["profil"].get("platce", ""))
    with c3: st.session_state.db["profil"]["adresa"] = st.text_input("Adresa", value=st.session_state.db["profil"].get("adresa", ""))
    with c4: st.session_state.db["profil"]["byt"] = st.text_input("ID Bytu", value=st.session_state.db["profil"].get("byt", ""))

    st.markdown("#### Časová osa předepsaného plnění")
    nova_osa = []
    for idx, obdobi in enumerate(st.session_state.db["osa_najmu"]):
        o1, o2, o3, o4 = st.columns(4)
        with o1: od_m = st.number_input("Od měsíce", value=obdobi.get("od_mesice", 1), min_value=1, max_value=12, key=f"od_{idx}")
        with o2: do_m = st.number_input("Do měsíce", value=obdobi.get("do_mesice", 12), min_value=1, max_value=12, key=f"do_{idx}")
        with o3: njm = st.number_input("Smluvní nájem (CZK)", value=obdobi.get("najem", 0), step=100, key=f"njm_{idx}")
        with o4: zal = st.number_input("Záloha (CZK)", value=obdobi.get("zaloha", 0), step=100, key=f"zal_{idx}")
        nova_osa.append({"od_mesice": od_m, "do_mesice": do_m, "najem": njm, "zaloha": zal})
    st.session_state.db["osa_najmu"] = nova_osa
    
    c_add, c_del = st.columns(2)
    with c_add:
        if st.button("Definovat nový interval"): st.session_state.db["osa_najmu"].append({"od_mesice": 1, "do_mesice": 12, "najem": 0, "zaloha": 0}); st.rerun()
    with c_del:
        if st.button("Odstranit interval") and len(st.session_state.db["osa_najmu"]) > 1: st.session_state.db["osa_najmu"].pop(); st.rerun()

# --- TAB 2: LOŇSKÉ VYÚČTOVÁNÍ ---
with tab2:
    st.subheader("Historická salda (Minulé období)")
    lonske_pdf = st.file_uploader("Zdrojový dokument (Vyúčtování N-1)", type="pdf", key="lon_pdf")
    if lonske_pdf and st.button("Extrahovat saldo N-1"):
        with st.spinner("Analýza zůstatků..."):
            try:
                txt = cteni_pdf(lonske_pdf)
                res = ai_volani(f"""Extrahuj saldo. Přeplatek (kladná), Nedoplatek (záporná). JSON: {{"vysledek": int, "typ": "Preplatek/Nedoplatek/Vyrovnano"}} Text: {txt}""")
                if res: st.session_state.db["lonsko"] = res; st.success(f"Detekováno: {res['typ']}, {abs(res['vysledek'])} CZK")
            except Exception as e: st.error(f"Chyba: {e}")
    
    cl1, cl2 = st.columns(2)
    with cl1: st.session_state.db["lonsko"]["typ"] = st.selectbox("Klasifikace salda N-1", ["Preplatek", "Nedoplatek", "Zadne"], index=["Preplatek", "Nedoplatek", "Zadne"].index(st.session_state.db["lonsko"].get("typ", "Zadne")))
    with cl2: st.session_state.db["lonsko"]["vysledek"] = st.number_input("Absolutní hodnota salda (CZK)", value=abs(st.session_state.db["lonsko"].get("vysledek", 0)))

# --- TAB 3: LETOŠNÍ NÁKLADY ---
with tab3:
    st.subheader("Evidence skutečných nákladů (N)")
    letosni_svj = st.file_uploader("Vyúčtování vlastníka (PDF)", type="pdf", key="let_svj")
    if letosni_svj and st.button("Spustit klasifikaci SVJ"):
        with st.spinner("Klasifikace..."):
            try:
                txt = cteni_pdf(letosni_svj)
                res = ai_volani(f"""Dekompozice. 'preuctovatelne'=true (voda, teplo, výtah, odpady). false (FO, správa, pojištění). JSON: {{"polozky": [{{"nazev":"string", "castka":int, "preuctovatelne":bool}}]}} Text: {txt}""")
                if res and "polozky" in res: st.session_state.db["naklady"]["svj"] = res["polozky"]; st.success("Zpracováno.")
            except Exception as e: st.error(f"Chyba: {e}")

    if st.session_state.db["naklady"]["svj"]:
        df_svj = pd.DataFrame(st.session_state.db["naklady"]["svj"])
        st.dataframe(df_svj, use_container_width=True, hide_index=True)

    st.markdown("#### Sekundární náklady")
    cd1, cd2 = st.columns([3, 1])
    with cd1: dalsi_pdf = st.file_uploader("Faktura (PDF)", type="pdf", key="dal_pdf")
    with cd2: typ_sluzby = st.selectbox("Kategorie", ["Elektřina", "Plyn", "Internet", "Ostatní"])
    if dalsi_pdf and st.button("Zpracovat doklad"):
        with st.spinner("Extrakce..."):
            try:
                txt = cteni_pdf(dalsi_pdf)
                res = ai_volani(f"""Extrahuj sumární náklady. JSON: {{"castka": int}} Text: {txt}""")
                if res: st.session_state.db["naklady"]["dalsi_sluzby"].append({"nazev": typ_sluzby, "castka": res["castka"], "preuctovatelne": True}); st.success("Přidáno.")
            except Exception as e: st.error(f"Chyba: {e}")

    if st.session_state.db["naklady"]["dalsi_sluzby"]:
        st.table(pd.DataFrame(st.session_state.db["naklady"]["dalsi_sluzby"]))
        if st.button("Reset sekundárních nákladů"): st.session_state.db["naklady"]["dalsi_sluzby"] = []; st.rerun()

# --- TAB 4: BANKA & PROTOKOL ---
with tab4:
    st.subheader("Finanční syntéza a Generování výstupu")
    id_transakce = st.text_input("Identifikátor filtru (např. příjmení)", value=st.session_state.db["profil"].get("platce", ""))
    banka_xls = st.file_uploader("Transakční log (XLSX/CSV)", type=["xlsx", "csv"], key="banka_xls")
    
    if st.button("GENEROVAT PROTOKOL A EXPORT", type="primary", use_container_width=True):
        if not banka_xls or not id_transakce: st.error("Chybí transakční data nebo identifikátor."); st.stop()
        with st.spinner("Agregace..."):
            try:
                df = pd.read_csv(banka_xls, header=None, dtype=str) if banka_xls.name.endswith('.csv') else pd.read_excel(banka_xls, header=None, dtype=str)
                mask = df.apply(lambda row: row.astype(str).str.contains(id_transakce, case=False, na=False).any(), axis=1)
                df_filtered = df[mask]
                if df_filtered.empty: raise Exception("Identifikátor nenalezen.")

                def parse_fin(val):
                    if pd.isna(val): return 0.0
                    v = re.sub(r'[^\d,\.-]', '', str(val).replace('\xa0', '').replace(' ', '').removesuffix(',-'))
                    try: return float(v.replace(',', '.'))
                    except: return 0.0

                col_sums = {col: df_filtered[col].apply(parse_fin).sum() for col in df_filtered.columns}
                suma_transakci = col_sums[max(col_sums, key=col_sums.get)]
                
                celkova_pohledavka_najem = sum(((o["do_mesice"] - o["od_mesice"]) + 1) * o["najem"] for o in st.session_state.db["osa_najmu"])
                
                saldo_n_minus_1 = st.session_state.db["lonsko"].get("vysledek", 0)
                korekce_saldo = saldo_n_minus_1 if st.session_state.db["lonsko"]["typ"] == "Preplatek" else -abs(saldo_n_minus_1) if st.session_state.db["lonsko"]["typ"] == "Nedoplatek" else 0
                
                disponibilni_zalohy = suma_transakci - celkova_pohledavka_najem + korekce_saldo
                
                agregovane_naklady = st.session_state.db["naklady"]["svj"] + st.session_state.db["naklady"]["dalsi_sluzby"]
                uznatelne_naklady = sum(p['castka'] for p in agregovane_naklady if p.get('preuctovatelne', False))
                saldo_konecne = disponibilni_zalohy - uznatelne_naklady

                finance = {
                    "suma_transakci": suma_transakci,
                    "celkova_pohledavka_najem": celkova_pohledavka_najem,
                    "korekce_saldo": korekce_saldo,
                    "disponibilni_zalohy": disponibilni_zalohy,
                    "uznatelne_naklady": uznatelne_naklady,
                    "saldo_konecne": saldo_konecne
                }

                st.markdown("---")
                st.header("PROTOKOL O ZÚČTOVÁNÍ")
                c1, c2, c3 = st.columns(3)
                c1.metric("Disponibilní zálohy", f"{disponibilni_zalohy:,.2f} CZK")
                c2.metric("Uznatelné náklady", f"{uznatelne_naklady:,.2f} CZK")
                c3.metric("Konečné saldo", f"{saldo_konecne:,.2f} CZK")
                
                # Generování DOCX
                docx_file = generovat_word_protokol(
                    st.session_state.db["profil"], 
                    [p for p in agregovane_naklady if p.get('preuctovatelne', False)], 
                    finance
                )
                
                st.download_button(
                    label="📄 EXPORTOVAT DO WORDU (.docx)",
                    data=docx_file,
                    file_name=f"Protokol_{id_transakce}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary"
                )

            except Exception as e: st.error(f"Kritická chyba: {e}")

# --- TAB 5: DATA A ZÁLOHY ---
with tab5:
    st.subheader("Export a Import stavu struktury")
    json_data = json.dumps(st.session_state.db, indent=4, ensure_ascii=False)
    st.download_button(label="Export JSON", data=json_data, file_name="Zaloha.json", mime="application/json")
    zaloha_file = st.file_uploader("Import JSON", type="json")
    if zaloha_file and st.button("Načíst"):
        st.session_state.db = json.load(zaloha_file); st.success("Nahráno.")
