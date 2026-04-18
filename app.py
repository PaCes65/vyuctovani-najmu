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
    from docx.shared import Pt, Inches, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    st.error("Kritická závislost: Chybí modul python-docx.")
    st.stop()

# ==========================================
# 1. KONFIGURACE A INIT STAVU
# ==========================================
st.set_page_config(page_title="Vyúčtování PRO", layout="wide", page_icon="🏢")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("Chyba konfigurace: GEMINI_API_KEY nenalezen.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

DEFAULT_DATA = {
    "profil": {"poskytovatel": "", "platce": "", "adresa": "", "byt": "", "typ": ""},
    "osa_najmu": [{"od_mesice": 1, "do_mesice": 12, "najem": 0, "zaloha": 0}],
    "lonsko": {"vysledek": 0, "typ": "Zadne"},
    "naklady": {"svj": [], "dalsi_sluzby": []},
    "vypocty": {
        "suma_transakci": 0, "celkova_pohledavka_najem": 0, "korekce_saldo": 0,
        "disponibilni_zalohy": 0, "uznatelne_naklady": 0, "saldo_konecne": 0,
        "pocet_transakci": 0, "filtr_transakci": ""
    }
}

if "db" not in st.session_state:
    st.session_state.db = json.loads(json.dumps(DEFAULT_DATA))

# ==========================================
# 2. IO & AI SUBSYSTÉM
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
    try:
        model = genai.GenerativeModel(model_name)
        res = model.generate_content(prompt)
        match = re.search(r'\{.*\}', res.text, re.DOTALL)
        if match: return json.loads(match.group())
        raise Exception("Nevalidní struktura JSON.")
    except Exception as e:
        raise Exception(f"API Chyba: {e}")

def cteni_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = "".join(p.extract_text() + "\n" for p in reader.pages if p.extract_text())
        return text
    except Exception as e:
        raise Exception(f"Chyba dekódování PDF: {e}")

def generovat_word_protokol(db):
    doc = Document()
    title = doc.add_heading('PROTOKOL O ZÚČTOVÁNÍ ZÁLOH NA SLUŽBY', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_header = doc.add_paragraph()
    p_header.add_run(f"Dle zákona č. 67/2013 Sb., o službách\n").italic = True
    p_header.add_run(f"Generováno: {datetime.now().strftime('%d.%m.%Y')}")
    p_header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph("_" * 70).alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    doc.add_heading('I. Identifikace subjektů a předmětu', level=1)
    t_id = doc.add_table(rows=4, cols=2)
    t_id.style = 'Table Grid'
    t_id.columns[0].width = Inches(2.0)
    r = t_id.rows
    r[0].cells[0].text = 'Předmět:'; r[0].cells[1].text = f"{db['profil']['adresa']}, Byt: {db['profil']['byt']}"
    r[1].cells[0].text = 'Klasifikace:'; r[1].cells[1].text = db['profil']['typ']
    r[2].cells[0].text = 'Poskytovatel:'; r[2].cells[1].text = db['profil']['poskytovatel']
    r[3].cells[0].text = 'Plátce:'; r[3].cells[1].text = db['profil']['platce']
    
    doc.add_heading('II. Časová osa předpisu plnění', level=1)
    t_predpis = doc.add_table(rows=1, cols=4)
    t_predpis.style = 'Light Shading'
    hr = t_predpis.rows[0].cells
    hr[0].text = 'Měsíce'; hr[1].text = 'Délka (m)'; hr[2].text = 'Nájem (CZK)'; hr[3].text = 'Sumace Nájem (CZK)'
    for o in db["osa_najmu"]:
        row = t_predpis.add_row().cells
        pocet_m = (o["do_mesice"] - o["od_mesice"]) + 1
        sub_najem = pocet_m * o["najem"]
        row[0].text = f"{o['od_mesice']} až {o['do_mesice']}"; row[1].text = str(pocet_m)
        row[2].text = f"{o['najem']:,.2f}"; row[3].text = f"{sub_najem:,.2f}"
    doc.add_paragraph(f"\nSrážka předpisu úhrad celkem: {db['vypocty']['celkova_pohledavka_najem']:,.2f} CZK").bold = True

    doc.add_heading('III. Finanční syntéza a disponibilní zálohy', level=1)
    v = db['vypocty']
    doc.add_paragraph(f"1. Připsané transakce (N={v['pocet_transakci']}): {v['suma_transakci']:,.2f} CZK")
    doc.add_paragraph(f"2. Aplikace srážky předpisu (Pol. II): - {v['celkova_pohledavka_najem']:,.2f} CZK")
    doc.add_paragraph(f"3. Aplikace salda N-1 ({db['lonsko']['typ']}): {'+' if v['korekce_saldo'] >= 0 else ''}{v['korekce_saldo']:,.2f} CZK")
    doc.add_paragraph(f"Disponibilní zálohy k vyrovnání = {v['disponibilni_zalohy']:,.2f} CZK").bold = True

    doc.add_heading('IV. Zúčtovatelné náklady objektu', level=1)
    agregovane = db['naklady']['svj'] + db['naklady']['dalsi_sluzby']
    uznatelne = [p for p in agregovane if p.get('preuctovatelne')]
    if uznatelne:
        t_naklady = doc.add_table(rows=1, cols=2)
        t_naklady.style = 'Table Grid'
        t_naklady.rows[0].cells[0].text = 'Identifikátor nákladu'; t_naklady.rows[0].cells[1].text = 'Hodnota (CZK)'
        for n in uznatelne:
            row = t_naklady.add_row().cells
            row[0].text = n['nazev']; row[1].text = f"{n['castka']:,.2f}"
        doc.add_paragraph(f"\nUznatelné náklady k tíži plátce celkem: {v['uznatelne_naklady']:,.2f} CZK").bold = True
    else:
        doc.add_paragraph("Kalkulace neobsahuje nákladové položky.")

    doc.add_heading('V. Konečné vypořádání salda', level=1)
    saldo = v['saldo_konecne']
    p_res = doc.add_paragraph()
    p_res.add_run(f"VÝSLEDNÉ KONEČNÉ SALDO: {saldo:,.2f} CZK\n").bold = True
    
    if saldo > 0:
        p_res.add_run(f"\nKlasifikace: PŘEPLATEK ({abs(saldo):,.2f} CZK).\n").bold = True
        p_res.add_run("Identifikován závazek poskytovatele vůči plátci s povinností vypořádání.")
    elif saldo < 0:
        p_res.add_run(f"\nKlasifikace: NEDOPLATEK ({abs(saldo):,.2f} CZK).\n").bold = True
        p_res.add_run("Identifikována splatná pohledávka poskytovatele za plátcem dle § 7 zák. č. 67/2013 Sb.")
    else:
        p_res.add_run("\nKlasifikace: VYROVNÁNO. Finanční závazky nulové.").bold = True

    doc.add_paragraph("\n\nSmluvní strany stvrzují podpisem akceptaci kalkulační metodiky a výsledného salda.")
    doc.add_paragraph('\n\nV ........................................ dne ........................................')
    sig_table = doc.add_table(rows=2, cols=2)
    sig_table.columns[0].width = Inches(3.0); sig_table.columns[1].width = Inches(3.0)
    sig_table.rows[0].cells[0].text = '..........................................................'
    sig_table.rows[0].cells[1].text = '..........................................................'
    sig_table.rows[1].cells[0].text = f"Za Poskytovatele:\n{db['profil']['poskytovatel']}"
    sig_table.rows[1].cells[1].text = f"Za Plátce:\n{db['profil']['platce']}"
    for r in sig_table.rows:
        for c in r.cells: c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ
# ==========================================
st.title("🏢 Vyúčtování PRO: Komplexní systém")

t1, t2, t3, t4, t5 = st.tabs(["1. Profil & Osy", "2. Saldo N-1", "3. Náklady N", "4. Agregace & Export", "💾 Perzistence"])

with t1:
    st.subheader("Extrakce struktur a časových řad")
    c_p1, c_p2 = st.columns(2)
    sml_1_pdf = c_p1.file_uploader("Smlouva 1 (Primární)", type="pdf")
    sml_2_pdf = c_p2.file_uploader("Smlouva 2 (Dodatek - modifikátor)", type="pdf")
    
    if st.button("Spustit NLP zpracování", type="primary"):
        if not sml_1_pdf: st.warning("Absentuje primární dokument.")
        else:
            with st.spinner("Procesování NLP modelu..."):
                try:
                    txt = f"--- DOKUMENT 1 (PRIMÁRNÍ) ---\n{cteni_pdf(sml_1_pdf)}\n"
                    if sml_2_pdf: txt += f"--- DOKUMENT 2 (MODIFIKÁTOR) ---\n{cteni_pdf(sml_2_pdf)}\n"
                    
                    prompt = f"""
                    Provést sémantickou a chronologickou analýzu smluv pro 1 zúčtovací rok (měsíce 1-12).
                    PRAVIDLA:
                    1. Subjekty: Podnájem -> posk=Nájemce, plat=Podnájemce. Nájem -> posk=Pronajímatel, plat=Nájemce.
                    2. ČASOVÁ OSA (osa_najmu):
                       - Smlouva 1 definuje výchozí stav (od_mesice=1).
                       - Pokud existuje Smlouva 2 / Dodatek, detekuj měsíc jeho účinnosti (M).
                       - Platnost Smlouvy 1 TERMINUJE měsícem (M - 1).
                       - Platnost Smlouvy 2 INICIALIZUJE měsícem (M) až do konce období (do_mesice=12).
                       - "najem" = čisté plnění majiteli, "zaloha" = záloha na služby.
                    JSON: {{"profil": {{"typ": "string", "poskytovatel": "string", "platce": "string", "adresa": "string", "byt": "string"}}, "osa_najmu": [{{"od_mesice": int, "do_mesice": int, "najem": int, "zaloha": int}}]}}
                    DATA: {txt}
                    """
                    res = ai_volani(prompt)
                    if res and "osa_najmu" in res:
                        st.session_state.db["profil"].update({k: res["profil"].get(k, "") for k in st.session_state.db["profil"]})
                        st.session_state.db["osa_najmu"] = res["osa_najmu"]
                        st.success("Kompozice osy úspěšná.")
                except Exception as e: st.error(f"Chyba NLP: {e}")

    c_i = st.columns(4)
    st.session_state.db["profil"]["poskytovatel"] = c_i[0].text_input("Poskytovatel", st.session_state.db["profil"]["poskytovatel"])
    st.session_state.db["profil"]["platce"] = c_i[1].text_input("Plátce", st.session_state.db["profil"]["platce"])
    st.session_state.db["profil"]["adresa"] = c_i[2].text_input("Adresa", st.session_state.db["profil"]["adresa"])
    st.session_state.db["profil"]["byt"] = c_i[3].text_input("ID Bytu", st.session_state.db["profil"]["byt"])
    
    st.markdown("#### Datová matice předpisů (Intervaly)")
    st.session_state.db["osa_najmu"] = st.data_editor(st.session_state.db["osa_najmu"], num_rows="dynamic")

with t2:
    st.subheader("Historické saldo (N-1)")
    l_pdf = st.file_uploader("Vyúčtování (N-1)", type="pdf")
    if l_pdf and st.button("Extrakce salda"):
        res = ai_volani(f"Najdi saldo. Přeplatek (kladná), Nedoplatek (záporná). JSON: {{'vysledek': int, 'typ': 'Preplatek/Nedoplatek'}}. Text: {cteni_pdf(l_pdf)}")
        if res: st.session_state.db["lonsko"].update(res); st.success(f"Aplikováno: {res['typ']} {abs(res['vysledek'])} CZK")
    
    c_l = st.columns(2)
    st.session_state.db["lonsko"]["typ"] = c_l[0].selectbox("Klasifikátor", ["Preplatek", "Nedoplatek", "Zadne"], index=["Preplatek", "Nedoplatek", "Zadne"].index(st.session_state.db["lonsko"]["typ"]))
    st.session_state.db["lonsko"]["vysledek"] = c_l[1].number_input("Absolutní hodnota", value=abs(st.session_state.db["lonsko"]["vysledek"]))

with t3:
    st.subheader("Rozvrh nákladových středisek (N)")
    svj_pdf = st.file_uploader("Primární náklad (SVJ)", type="pdf")
    if svj_pdf and st.button("Dekompozice položek"):
        res = ai_volani(f"Rozřaď položky. 'preuctovatelne'=true pro služby (voda, teplo, výtah). JSON: {{'polozky': [{{'nazev':'', 'castka':0, 'preuctovatelne':bool}}]}}. Text: {cteni_pdf(svj_pdf)}")
        if res: st.session_state.db["naklady"]["svj"] = res["polozky"]; st.success("Dekompozice uložena.")
    st.session_state.db["naklady"]["svj"] = st.data_editor(st.session_state.db["naklady"]["svj"], num_rows="dynamic")
    
    st.divider()
    c_ds = st.columns([3, 1])
    d_pdf = c_ds[0].file_uploader("Sekundární náklad (Plyn/El.)", type="pdf")
    typ_d = c_ds[1].selectbox("Identifikátor", ["Elektřina", "Plyn", "Internet"])
    if d_pdf and st.button("Přidat entitu"):
        res = ai_volani(f"Agreguj fakturovanou sumu. JSON: {{'castka': int}}. Text: {cteni_pdf(d_pdf)}")
        if res: st.session_state.db["naklady"]["dalsi_sluzby"].append({"nazev": typ_d, "castka": res["castka"], "preuctovatelne": True}); st.success("Entita přidána.")
    st.session_state.db["naklady"]["dalsi_sluzby"] = st.data_editor(st.session_state.db["naklady"]["dalsi_sluzby"], num_rows="dynamic")

with t4:
    st.subheader("Finanční agregátor & Výstup")
    filtr = st.text_input("Transakční filtr (Substring matche)", st.session_state.db["profil"]["platce"])
    b_file = st.file_uploader("Export transakcí (XLSX/CSV)", type=["xlsx", "csv"])
    
    if st.button("KALKULACE & ZÁPIS", type="primary", use_container_width=True):
        if b_file:
            df = pd.read_csv(b_file, header=None).astype(str) if b_file.name.endswith('.csv') else pd.read_excel(b_file, header=None).astype(str)
            filtered = df[df.apply(lambda r: r.str.contains(filtr, case=False).any(), axis=1)]
            
            def p(v):
                try: return float(re.sub(r'[^\d,\.-]', '', v.replace(' ', '')).replace(',', '.'))
                except: return 0.0

            sums = {c: filtered[c].apply(p).sum() for c in filtered.columns}
            target = max(sums, key=sums.get)
            
            v = st.session_state.db["vypocty"]
            v["filtr_transakci"] = filtr
            v["suma_transakci"] = sums[target]
            v["pocet_transakci"] = len(filtered)
            v["celkova_pohledavka_najem"] = sum(((o["do_mesice"] - o["od_mesice"]) + 1) * o["najem"] for o in st.session_state.db["osa_najmu"])
            
            ls = st.session_state.db["lonsko"]
            v["korekce_saldo"] = ls["vysledek"] if ls["typ"] == "Preplatek" else -abs(ls["vysledek"]) if ls["typ"] == "Nedoplatek" else 0
            
            v["disponibilni_zalohy"] = v["suma_transakci"] - v["celkova_pohledavka_najem"] + v["korekce_saldo"]
            v["uznatelne_naklady"] = sum(p['castka'] for p in st.session_state.db["naklady"]["svj"] + st.session_state.db["naklady"]["dalsi_sluzby"] if p.get('preuctovatelne'))
            v["saldo_konecne"] = v["disponibilni_zalohy"] - v["uznatelne_naklady"]
            
            st.success("Transakční blok zpracován.")

    if st.session_state.db["vypocty"]["pocet_transakci"] > 0:
        st.metric("Vypočtené konečné saldo", f"{st.session_state.db['vypocty']['saldo_konecne']:,.2f} CZK")
        docx = generovat_word_protokol(st.session_state.db)
        fn = st.session_state.db["vypocty"]["filtr_transakci"].replace(" ", "_")
        st.download_button("📄 EXPORTOVAT DOCX PROTOKOL", docx, f"Zuctovani_{fn}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

with t5:
    st.subheader("Serializace databáze")
    st.download_button("📥 Uložit JSON Image", json.dumps(st.session_state.db, indent=4, ensure_ascii=False), "Data_Export.json", "application/json")
    st.divider()
    up = st.file_uploader("Obnovit z JSON", type="json")
    if up and st.button("RESTORE"): st.session_state.db = json.load(up); st.rerun()
