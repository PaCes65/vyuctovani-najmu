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
    "naklady": {"svj": [], "dalsi_sluzby": []},
    "vypocty": {
        "suma_transakci": 0,
        "celkova_pohledavka_najem": 0,
        "korekce_saldo": 0,
        "disponibilni_zalohy": 0,
        "uznatelne_naklady": 0,
        "saldo_konecne": 0,
        "pocet_transakci": 0,
        "filtr_transakci": ""
    }
}

if "db" not in st.session_state:
    st.session_state.db = json.loads(json.dumps(DEFAULT_DATA))

# ==========================================
# 2. POMOCNÉ FUNKCE
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
        raise Exception("Nevalidní JSON výstup.")
    except Exception as e:
        raise Exception(f"AI Chyba: {e}")

def cteni_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = "".join(p.extract_text() + "\n" for p in reader.pages if p.extract_text())
        return text
    except Exception as e:
        raise Exception(f"Chyba PDF: {e}")

def generovat_word_protokol(db):
    """Generuje plně formalizovaný DOCX protokol."""
    doc = Document()
    
    # 1. Hlavička
    title = doc.add_heading('PROTOKOL O ZÚČTOVÁNÍ ZÁLOH NA SLUŽBY', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_header = doc.add_paragraph()
    p_header.add_run(f"Dle zákona č. 67/2013 Sb., o službách\n").italic = True
    p_header.add_run(f"Vygenerováno dne: {datetime.now().strftime('%d.%m.%Y')}")
    p_header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    
    doc.add_paragraph("_" * 70).alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # 2. Identifikace vztahu
    doc.add_heading('I. Identifikace smluvního vztahu', level=1)
    t_id = doc.add_table(rows=4, cols=2)
    t_id.style = 'Table Grid'
    t_id.columns[0].width = Inches(2.0)
    t_id.rows[0].cells[0].text = 'Předmět užívání:'
    t_id.rows[0].cells[1].text = f"{db['profil']['adresa']}, Byt: {db['profil']['byt']}"
    t_id.rows[1].cells[0].text = 'Klasifikace vztahu:'
    t_id.rows[1].cells[1].text = db['profil']['typ']
    t_id.rows[2].cells[0].text = 'Poskytovatel (Příjemce):'
    t_id.rows[2].cells[1].text = db['profil']['poskytovatel']
    t_id.rows[3].cells[0].text = 'Plátce (Uživatel):'
    t_id.rows[3].cells[1].text = db['profil']['platce']
    
    # 3. Kalkulační základy
    doc.add_heading('II. Rekapitulace předpisů úhrad a pohledávek', level=1)
    doc.add_paragraph("Zúčtovací období: 1 kalendářní rok (rozděleno dle změn v předpisu nájemného)")
    
    t_predpis = doc.add_table(rows=1, cols=4)
    t_predpis.style = 'Light Shading'
    hr_predpis = t_predpis.rows[0].cells
    hr_predpis[0].text = 'Období (Měsíce)'
    hr_predpis[1].text = 'Počet měsíců'
    hr_predpis[2].text = 'Nájem (Měsíčně)'
    hr_predpis[3].text = 'Celkem Smluvní Nájem'
    
    for o in db["osa_najmu"]:
        row = t_predpis.add_row().cells
        pocet_m = (o["do_mesice"] - o["od_mesice"]) + 1
        sub_najem = pocet_m * o["najem"]
        row[0].text = f"{o['od_mesice']} až {o['do_mesice']}"
        row[1].text = str(pocet_m)
        row[2].text = f"{o['najem']:,.2f} CZK"
        row[3].text = f"{sub_najem:,.2f} CZK"
        
    doc.add_paragraph(f"\nCelková srážka (nájemné za posuzované období): {db['vypocty']['celkova_pohledavka_najem']:,.2f} CZK").bold = True

    # 4. Transakční agregace
    doc.add_heading('III. Úhrn transakcí a disponibilní zálohy', level=1)
    doc.add_paragraph("Výpočet disponibilní částky určené ke krytí nákladů na služby:")
    
    v = db['vypocty']
    doc.add_paragraph(f"1) Fyzicky připsané prostředky na účet (Počet transakcí: {v['pocet_transakci']}): {v['suma_transakci']:,.2f} CZK")
    doc.add_paragraph(f"2) Srážka vypočteného nájemného (Položka II.): - {v['celkova_pohledavka_najem']:,.2f} CZK")
    doc.add_paragraph(f"3) Zohledněné saldo minulého období ({db['lonsko']['typ']}): {'+' if v['korekce_saldo'] >= 0 else ''}{v['korekce_saldo']:,.2f} CZK")
    doc.add_paragraph(f"VÝSLEDEK: Disponibilní zálohy k zúčtování = {v['disponibilni_zalohy']:,.2f} CZK").bold = True

    # 5. Náklady
    doc.add_heading('IV. Audit uznatelných nákladů', level=1)
    agregovane = db['naklady']['svj'] + db['naklady']['dalsi_sluzby']
    uznatelne = [p for p in agregovane if p.get('preuctovatelne')]
    
    if uznatelne:
        t_naklady = doc.add_table(rows=1, cols=2)
        t_naklady.style = 'Table Grid'
        hr_naklady = t_naklady.rows[0].cells
        hr_naklady[0].text = 'Položka'
        hr_naklady[1].text = 'Náklad (CZK)'
        for n in uznatelne:
            row = t_naklady.add_row().cells
            row[0].text = n['nazev']
            row[1].text = f"{n['castka']:,.2f}"
            
        doc.add_paragraph(f"\nCelkové uznatelné náklady (Debet plátce): {v['uznatelne_naklady']:,.2f} CZK").bold = True
    else:
        doc.add_paragraph("Nebyla evidována žádná nákladová položka.")

    # 6. Zúčtování
    doc.add_heading('V. Konečné vypořádání', level=1)
    doc.add_paragraph("Rozdíl disponibilních záloh (Kredit) a uznatelných nákladů (Debet).")
    
    saldo = v['saldo_konecne']
    p_res = doc.add_paragraph()
    p_res.add_run(f"ZJIŠTĚNÉ KONEČNÉ SALDO: {saldo:,.2f} CZK\n").bold = True
    
    if saldo > 0:
        p_res.add_run(f"\nKlasifikace: PŘEPLATEK ve výši {abs(saldo):,.2f} CZK.\n").bold = True
        p_res.add_run("Tato částka představuje závazek poskytovatele vůči plátci a bude vrácena, "
                      "případně po dohodě započtena do plateb dalšího zúčtovacího období.")
    elif saldo < 0:
        p_res.add_run(f"\nKlasifikace: NEDOPLATEK ve výši {abs(saldo):,.2f} CZK.\n").bold = True
        p_res.add_run("Tato částka představuje splatnou pohledávku poskytovatele za plátcem "
                      "s povinností úhrady v zákonné lhůtě dle § 7 zákona č. 67/2013 Sb.")
    else:
        p_res.add_run("\nKlasifikace: VYROVNÁNO. Žádná ze stran nevykazuje závazek.").bold = True

    # 7. Podpisy
    doc.add_paragraph("\n\nSmluvní strany stvrzují svým podpisem, že byly s obsahem protokolu seznámeny, porozuměly mu "
                      "a proti kalkulačnímu postupu ani výstupním hodnotám nevznášejí námitky.")
    
    doc.add_paragraph('\n\nV ........................................ dne ........................................')
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
    row1[0].text = f"Za Poskytovatele:\n{db['profil']['poskytovatel']}"
    row1[1].text = f"Za Plátce:\n{db['profil']['platce']}"
    row1[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    row1[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ
# ==========================================
st.title("🏢 Vyúčtování PRO: Komplet")

t1, t2, t3, t4, t5 = st.tabs(["1. Smlouva", "2. Loňsko", "3. Letošní náklady", "4. Banka & Protokol", "💾 JSON Databáze"])

with t1:
    st.subheader("Parametry vztahu")
    sml_pdf = st.file_uploader("Analyzovat smlouvu (PDF)", type="pdf")
    if sml_pdf and st.button("AI Extrakce"):
        with st.spinner("Pracuji..."):
            txt = cteni_pdf(sml_pdf)
            res = ai_volani(f"Extrahuj do JSON: typ, poskytovatel, platce, adresa, byt, najem, zaloha. Text: {txt}")
            if res:
                st.session_state.db["profil"].update({k: res.get(k, "") for k in st.session_state.db["profil"]})
                st.session_state.db["osa_najmu"][0].update({"najem": res.get("najem", 0), "zaloha": res.get("zaloha", 0)})
    
    c = st.columns(4)
    st.session_state.db["profil"]["poskytovatel"] = c[0].text_input("Poskytovatel", st.session_state.db["profil"]["poskytovatel"])
    st.session_state.db["profil"]["platce"] = c[1].text_input("Plátce", st.session_state.db["profil"]["platce"])
    st.session_state.db["profil"]["adresa"] = c[2].text_input("Adresa", st.session_state.db["profil"]["adresa"])
    st.session_state.db["profil"]["byt"] = c[3].text_input("Byt", st.session_state.db["profil"]["byt"])
    
    st.markdown("#### Časová osa plnění (Rozvrh smluvního nájemného)")
    st.session_state.db["osa_najmu"] = st.data_editor(st.session_state.db["osa_najmu"], num_rows="dynamic")

with t2:
    st.subheader("Historické saldo")
    l_pdf = st.file_uploader("Načíst loňské PDF", type="pdf")
    if l_pdf and st.button("Hledat saldo"):
        res = ai_volani(f"Najdi saldo. JSON: {{'vysledek': int, 'typ': 'Preplatek/Nedoplatek'}}. Text: {cteni_pdf(l_pdf)}")
        if res: st.session_state.db["lonsko"] = res
    
    c2 = st.columns(2)
    st.session_state.db["lonsko"]["typ"] = c2[0].selectbox("Typ minula", ["Preplatek", "Nedoplatek", "Zadne"], 
                                                          index=["Preplatek", "Nedoplatek", "Zadne"].index(st.session_state.db["lonsko"]["typ"]))
    st.session_state.db["lonsko"]["vysledek"] = c2[1].number_input("Částka", value=abs(st.session_state.db["lonsko"]["vysledek"]))

with t3:
    st.subheader("Evidence nákladů")
    svj_pdf = st.file_uploader("Dnešní SVJ (PDF)", type="pdf")
    if svj_pdf and st.button("Audit položek"):
        res = ai_volani(f"Vypiš položky SVJ do JSON {{'polozky': [{{'nazev':'', 'castka':0, 'preuctovatelne':bool}}]}}. Text: {cteni_pdf(svj_pdf)}")
        if res: st.session_state.db["naklady"]["svj"] = res["polozky"]
    
    st.session_state.db["naklady"]["svj"] = st.data_editor(st.session_state.db["naklady"]["svj"], num_rows="dynamic")
    
    st.divider()
    d_pdf = st.file_uploader("Faktura za plyn/elektřinu (PDF)", type="pdf")
    if d_pdf and st.button("Přidat službu"):
        res = ai_volani(f"Najdi celkovou částku v JSON {{'castka': int}}. Text: {cteni_pdf(d_pdf)}")
        if res: st.session_state.db["naklady"]["dalsi_sluzby"].append({"nazev": "Externí služba", "castka": res["castka"], "preuctovatelne": True})
    
    st.session_state.db["naklady"]["dalsi_sluzby"] = st.data_editor(st.session_state.db["naklady"]["dalsi_sluzby"], num_rows="dynamic")

with t4:
    st.subheader("Bankovní data & Protokol")
    filtr = st.text_input("Identifikátor transakcí (Substring filtr)", st.session_state.db["profil"]["platce"])
    b_file = st.file_uploader("Transakční log (XLSX/CSV)", type=["xlsx", "csv"])
    
    if st.button("Vypočítat a uložit stav", type="primary"):
        if b_file:
            df = pd.read_csv(b_file, header=None).astype(str) if b_file.name.endswith('.csv') else pd.read_excel(b_file, header=None).astype(str)
            filtered = df[df.apply(lambda r: r.str.contains(filtr, case=False).any(), axis=1)]
            
            def p(v):
                v = re.sub(r'[^\d,\.-]', '', v.replace(' ', ''))
                try: return float(v.replace(',', '.'))
                except: return 0.0

            sums = {c: filtered[c].apply(p).sum() for c in filtered.columns}
            target = max(sums, key=sums.get)
            
            # Zápis do DB v session_state
            v = st.session_state.db["vypocty"]
            v["filtr_transakci"] = filtr
            v["suma_transakci"] = sums[target]
            v["pocet_transakci"] = len(filtered)
            v["celkova_pohledavka_najem"] = sum(((o["do_mesice"] - o["od_mesice"]) + 1) * o["najem"] for o in st.session_state.db["osa_najmu"])
            
            ls = st.session_state.db["lonsko"]
            v["korekce_saldo"] = ls["vysledek"] if ls["typ"] == "Preplatek" else -abs(ls["vysledek"]) if ls["typ"] == "Nedoplatek" else 0
            
            v["disponibilni_zalohy"] = v["suma_transakci"] - v["celkova_pohledavka_najem"] + v["korekce_saldo"]
            
            agregovane = st.session_state.db["naklady"]["svj"] + st.session_state.db["naklady"]["dalsi_sluzby"]
            v["uznatelne_naklady"] = sum(p['castka'] for p in agregovane if p.get('preuctovatelne'))
            v["saldo_konecne"] = v["disponibilni_zalohy"] - v["uznatelne_naklady"]
            
            st.success("Operace agregace a výpočtu provedena.")

    if st.session_state.db["vypocty"]["pocet_transakci"] > 0:
        st.metric("Konečné saldo", f"{st.session_state.db['vypocty']['saldo_konecne']:,.2f} CZK")
        docx = generovat_word_protokol(st.session_state.db)
        fn_id = st.session_state.db["vypocty"]["filtr_transakci"].replace(" ", "_")
        st.download_button("📄 EXPORTOVAT DO WORDU (.docx)", docx, f"Protokol_Vyuctovani_{fn_id}.docx")

with t5:
    st.subheader("Persistenci dat (JSON)")
    js = json.dumps(st.session_state.db, indent=4, ensure_ascii=False)
    st.download_button("📥 Stáhnout kompletní stav (JSON)", js, "Stav_Vyuctovani.json", "application/json")
    
    st.divider()
    up_js = st.file_uploader("Nahrát stav (JSON)", type="json")
    if up_js:
        st.session_state.db = json.load(up_js)
        st.success("Stav kompletně obnoven.")
        st.rerun()
