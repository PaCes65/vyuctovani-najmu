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
    st.error("Kritická závislost: Chybí modul python-docx. Přidejte jej do requirements.txt.")
    st.stop()

# ==========================================
# 1. KONFIGURACE A INIT STAVU
# ==========================================
st.set_page_config(page_title="Vyúčtování PRO", layout="wide", page_icon="🏢")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("Chyba konfigurace: GEMINI_API_KEY nenalezen v Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

DEFAULT_DATA = {
    "profil": {"poskytovatel": "", "platce": "", "adresa": "", "byt": "", "typ": ""},
    "osa_najmu": [{"od_mesice": 1, "do_mesice": 12, "najem": 0, "zaloha": 0}],
    "osoby": [{"jmeno": "Hlavní plátce", "od_mesice": 1, "do_mesice": 12}],
    "lonsko": {"vysledek": 0, "typ": "Zadne"},
    "naklady": {"svj": [], "dalsi_sluzby": []},
    "vypocty": {
        "suma_transakci": 0.0, "celkova_pohledavka_najem": 0.0, "korekce_saldo": 0.0,
        "disponibilni_zalohy": 0.0, "uznatelne_naklady": 0.0, "saldo_konecne": 0.0,
        "pocet_transakci": 0, "filtr_transakci": "", "prumerna_obsazenost": 0.0
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
        cisty_text = res.text.strip()
        if "```json" in cisty_text:
            cisty_text = cisty_text.split("```json")[1].split("```")[0].strip()
        elif "```" in cisty_text:
            cisty_text = cisty_text.split("```")[1].split("```")[0].strip()
        return json.loads(cisty_text)
    except Exception as e:
        raise Exception(f"Chyba parsování AI odpovědi: {e}")

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
    
    # I. Identifikace
    doc.add_heading('I. Identifikace subjektů a předmětu', level=1)
    t_id = doc.add_table(rows=4, cols=2)
    t_id.style = 'Table Grid'
    t_id.columns[0].width = Inches(2.0)
    r = t_id.rows
    r[0].cells[0].text = 'Předmět:'; r[0].cells[1].text = f"{db['profil']['adresa']}, Byt: {db['profil']['byt']}"
    r[1].cells[0].text = 'Klasifikace:'; r[1].cells[1].text = db['profil']['typ']
    r[2].cells[0].text = 'Poskytovatel:'; r[2].cells[1].text = db['profil']['poskytovatel']
    r[3].cells[0].text = 'Plátce:'; r[3].cells[1].text = db['profil']['platce']
    
    # Evidenční počet osob
    v = db['vypocty']
    doc.add_heading('II. Evidenční počet osob (obsazenost)', level=1)
    doc.add_paragraph("Přehled uživatelů bytu rozhodný pro rozúčtování nákladů podle zákona č. 67/2013 Sb.:")
    t_osoby = doc.add_table(rows=1, cols=3)
    t_osoby.style = 'Light Shading'
    hr_o = t_osoby.rows[0].cells
    hr_o[0].text = 'Jméno'; hr_o[1].text = 'Období užívání'; hr_o[2].text = 'Osoboměsíců'
    for os in db["osoby"]:
        row = t_osoby.add_row().cells
        pmesicu = max(0, (os["do_mesice"] - os["od_mesice"]) + 1)
        row[0].text = os.get("jmeno", "Neuvedeno")
        row[1].text = f"Měsíc {os['od_mesice']} až {os['do_mesice']}"
        row[2].text = str(pmesicu)
    doc.add_paragraph(f"\nPrůměrný roční počet osob v bytě: {v.get('prumerna_obsazenost', 0.0):.2f}").bold = True

    # Časová osa nájmu
    doc.add_heading('III. Časová osa předpisu plnění', level=1)
    t_predpis = doc.add_table(rows=1, cols=4)
    t_predpis.style = 'Light Shading'
    hr = t_predpis.rows[0].cells
    hr[0].text = 'Měsíce'; hr[1].text = 'Délka (m)'; hr[2].text = 'Nájem (CZK)'; hr[3].text = 'Sumace Nájem (CZK)'
    for o in db["osa_najmu"]:
        row = t_predpis.add_row().cells
        pocet_m = max(0, (o["do_mesice"] - o["od_mesice"]) + 1)
        sub_najem = pocet_m * o["najem"]
        row[0].text = f"{o['od_mesice']} až {o['do_mesice']}"; row[1].text = str(pocet_m)
        row[2].text = f"{o['najem']:,.2f}"; row[3].text = f"{sub_najem:,.2f}"
    doc.add_paragraph(f"\nSrážka předpisu úhrad celkem: {v['celkova_pohledavka_najem']:,.2f} CZK").bold = True

    # Finanční syntéza
    doc.add_heading('IV. Finanční syntéza a disponibilní zálohy', level=1)
    doc.add_paragraph(f"1. Připsané transakce (N={v['pocet_transakci']}): {v['suma_transakci']:,.2f} CZK")
    doc.add_paragraph(f"2. Aplikace srážky předpisu (Pol. III): - {v['celkova_pohledavka_najem']:,.2f} CZK")
    doc.add_paragraph(f"3. Aplikace salda N-1 ({db['lonsko']['typ']}): {'+' if v['korekce_saldo'] >= 0 else ''}{v['korekce_saldo']:,.2f} CZK")
    doc.add_paragraph(f"Disponibilní zálohy k vyrovnání = {v['disponibilni_zalohy']:,.2f} CZK").bold = True

    # Náklady
    doc.add_heading('V. Zúčtovatelné náklady objektu', level=1)
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

    # Konečné saldo
    doc.add_heading('VI. Konečné vypořádání salda', level=1)
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

    # Podpisy
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
    sml_1_pdf = c_p1.file_uploader("Smlouva 1 (Primární)", type="pdf", key="file_sml_1")
    sml_2_pdf = c_p2.file_uploader("Smlouva 2 (Dodatek - modifikátor)", type="pdf", key="file_sml_2")
    
    if st.button("Spustit NLP zpracování", type="primary", key="btn_nlp"):
        if not sml_1_pdf: st.warning("Absentuje primární dokument.")
        else:
            with st.spinner("Procesování NLP modelu..."):
                try:
                    txt = f"--- DOKUMENT 1 (PRIMÁRNÍ) ---\n{cteni_pdf(sml_1_pdf)}\n"
                    if sml_2_pdf: txt += f"--- DOKUMENT 2 (MODIFIKÁTOR) ---\n{cteni_pdf(sml_2_pdf)}\n"
                    prompt = f"""Provést sémantickou analýzu smluv pro 1 rok (měsíce 1-12).
                    1. Identifikuj PŘESNÁ jména. Podnájem -> posk=Nájemce, plat=Podnájemce. Nájem -> posk=Pronajímatel, plat=Nájemce.
                    2. Najdi VŠECHNY uvedené osoby v bytě (hlavní nájemce i spolubydlící).
                    3. Sestav osu nájemného a záloh.
                    JSON: {{"profil": {{"typ": "Nájemní smlouva", "poskytovatel": "Jméno", "platce": "Jméno", "adresa": "Adresa", "byt": "Číslo"}}, "osa_najmu": [{{"od_mesice": 1, "do_mesice": 12, "najem": 10000, "zaloha": 3000}}], "osoby": [{{"jmeno": "Jméno", "od_mesice": 1, "do_mesice": 12}}]}}
                    DATA: {txt}"""
                    res = ai_volani(prompt)
                    if res:
                        if "profil" in res: st.session_state.db["profil"].update(res["profil"])
                        if "osa_najmu" in res: st.session_state.db["osa_najmu"] = res["osa_najmu"]
                        if "osoby" in res and res["osoby"]: st.session_state.db["osoby"] = res["osoby"]
                        st.success("Analýza a kompozice dat úspěšná.")
                except Exception as e: st.error(f"Chyba NLP: {e}")

    c_i = st.columns(4)
    st.session_state.db["profil"]["poskytovatel"] = c_i[0].text_input("Poskytovatel", st.session_state.db["profil"]["poskytovatel"], key="inp_posk")
    st.session_state.db["profil"]["platce"] = c_i[1].text_input("Plátce", st.session_state.db["profil"]["platce"], key="inp_plat")
    st.session_state.db["profil"]["adresa"] = c_i[2].text_input("Adresa", st.session_state.db["profil"]["adresa"], key="inp_adr")
    st.session_state.db["profil"]["byt"] = c_i[3].text_input("ID Bytu", st.session_state.db["profil"]["byt"], key="inp_byt")
    
    col_osa, col_osoby = st.columns(2)
    
    with col_osa:
        st.markdown("#### Časová osa nájemného")
        st.session_state.db["osa_najmu"] = st.data_editor(st.session_state.db["osa_najmu"], num_rows="dynamic", key="editor_osa_najmu")
        # Agregace a vizualizace pro osu nájmu
        s_najem = sum(max(0, (o["do_mesice"] - o["od_mesice"]) + 1) * o["najem"] for o in st.session_state.db["osa_najmu"])
        s_zaloha = sum(max(0, (o["do_mesice"] - o["od_mesice"]) + 1) * o["zaloha"] for o in st.session_state.db["osa_najmu"])
        st.info(f"**Dílčí úhrn předpisu (Nájemné):** {s_najem:,.2f} CZK\n\n**Dílčí úhrn předpisu (Zálohy):** {s_zaloha:,.2f} CZK")
    
    with col_osoby:
        st.markdown("#### Osoby v bytě (Spolubydlící)")
        if "osoby" not in st.session_state.db: 
            st.session_state.db["osoby"] = [{"jmeno": st.session_state.db["profil"].get("platce", "Hlavní plátce"), "od_mesice": 1, "do_mesice": 12}]
        st.session_state.db["osoby"] = st.data_editor(st.session_state.db["osoby"], num_rows="dynamic", key="editor_osoby")
        # Agregace a vizualizace obsazenosti
        total_osobomesicu = sum(max(0, (o["do_mesice"] - o["od_mesice"]) + 1) for o in st.session_state.db["osoby"])
        prumerna_obsazenost = total_osobomesicu / 12.0
        st.info(f"**Celkem osoboměsíců:** {total_osobomesicu}\n\n**Průměrná roční obsazenost bytu:** {prumerna_obsazenost:.2f} osob")
        st.session_state.db["vypocty"]["prumerna_obsazenost"] = prumerna_obsazenost

with t2:
    st.subheader("Historické saldo (N-1)")
    l_pdf = st.file_uploader("Vyúčtování (N-1)", type="pdf", key="file_lon_pdf")
    if l_pdf and st.button("Extrakce salda", key="btn_saldo_lonsko"):
        res = ai_volani(f"Najdi saldo. Přeplatek (kladná), Nedoplatek (záporná). JSON: {{'vysledek': int, 'typ': 'Preplatek/Nedoplatek'}}. Text: {cteni_pdf(l_pdf)}")
        if res: st.session_state.db["lonsko"].update(res); st.success(f"Extrahována hodnota: {res['typ']} {abs(res['vysledek'])} CZK")
    
    c_l = st.columns(2)
    st.session_state.db["lonsko"]["typ"] = c_l[0].selectbox("Klasifikátor salda", ["Preplatek", "Nedoplatek", "Zadne"], index=["Preplatek", "Nedoplatek", "Zadne"].index(st.session_state.db["lonsko"]["typ"]), key="sel_typ_lonsko")
    st.session_state.db["lonsko"]["vysledek"] = c_l[1].number_input("Absolutní hodnota (CZK)", value=abs(st.session_state.db["lonsko"]["vysledek"]), key="num_vysledek_lonsko")

with t3:
    st.subheader("Rozvrh nákladových středisek (N)")
    svj_pdf = st.file_uploader("Primární náklad (SVJ)", type="pdf", key="file_svj_pdf")
    if svj_pdf and st.button("Dekompozice položek", key="btn_dek_svj"):
        res = ai_volani(f"Rozřaď položky. 'preuctovatelne'=true pro služby (voda, teplo, výtah). JSON: {{'polozky': [{{'nazev':'', 'castka':0, 'preuctovatelne':bool}}]}}. Text: {cteni_pdf(svj_pdf)}")
        if res: st.session_state.db["naklady"]["svj"] = res["polozky"]; st.success("Dekompozice uložena.")
    
    st.session_state.db["naklady"]["svj"] = st.data_editor(st.session_state.db["naklady"]["svj"], num_rows="dynamic", key="editor_naklady_svj")
    
    # Agregace SVJ
    sum_svj_vse = sum(p.get("castka", 0) for p in st.session_state.db["naklady"]["svj"])
    sum_svj_uznatelne = sum(p.get("castka", 0) for p in st.session_state.db["naklady"]["svj"] if p.get("preuctovatelne"))
    st.info(f"**Dílčí součet SVJ (Hrubý):** {sum_svj_vse:,.2f} CZK | **Přeúčtovatelné na plátce:** {sum_svj_uznatelne:,.2f} CZK")
    
    st.divider()
    c_ds = st.columns([3, 1])
    d_pdf = c_ds[0].file_uploader("Sekundární náklad (Plyn/El.)", type="pdf", key="file_sek_pdf")
    typ_d = c_ds[1].selectbox("Identifikátor", ["Elektřina", "Plyn", "Internet", "Ostatní"], key="sel_typ_sek")
    if d_pdf and st.button("Přidat entitu", key="btn_add_sek"):
        res = ai_volani(f"Agreguj fakturovanou sumu. JSON: {{'castka': int}}. Text: {cteni_pdf(d_pdf)}")
        if res: st.session_state.db["naklady"]["dalsi_sluzby"].append({"nazev": typ_d, "castka": res["castka"], "preuctovatelne": True}); st.success(f"Extrahována hodnota: {res['castka']} CZK")
        
    st.session_state.db["naklady"]["dalsi_sluzby"] = st.data_editor(st.session_state.db["naklady"]["dalsi_sluzby"], num_rows="dynamic", key="editor_dalsi_sluzby")
    
    # Agregace Sekundárních nákladů
    sum_sek = sum(p.get("castka", 0) for p in st.session_state.db["naklady"]["dalsi_sluzby"])
    sum_sek_uznatelne = sum(p.get("castka", 0) for p in st.session_state.db["naklady"]["dalsi_sluzby"] if p.get("preuctovatelne"))
    st.info(f"**Dílčí součet sekundárních nákladů:** {sum_sek:,.2f} CZK | **Přeúčtovatelné:** {sum_sek_uznatelne:,.2f} CZK")
    
    st.markdown(f"### **Celkový úhrn uznatelných nákladů (Debet plátce): {(sum_svj_uznatelne + sum_sek_uznatelne):,.2f} CZK**")

with t4:
    st.subheader("Finanční agregátor & Výstup")
    filtr = st.text_input("Transakční filtr (Substring matche)", st.session_state.db["profil"]["platce"], key="inp_filtr_trans")
    b_file = st.file_uploader("Export transakcí (XLSX/CSV)", type=["xlsx", "csv"], key="file_banka_xls")
    
    if st.button("KALKULACE & ZÁPIS", type="primary", use_container_width=True, key="btn_calc"):
        if b_file:
            try:
                if b_file.name.endswith('.csv'):
                    df = pd.read_csv(b_file, sep=None, engine='python', header=None, dtype=str)
                else:
                    df = pd.read_excel(b_file, header=None, dtype=str)
                
                mask = df.apply(lambda r: r.astype(str).str.contains(filtr, case=False, na=False).any(), axis=1)
                filtered = df[mask]
                
                if filtered.empty:
                    raise Exception(f"Filtrační argument '{filtr}' nevrátil žádné odpovídající záznamy.")
                
                st.markdown("#### Matice identifikovaných transakcí")
                st.dataframe(filtered, use_container_width=True)

                def parse_fin(val):
                    if pd.isna(val): return 0.0
                    v = str(val).strip()
                    if re.match(r'^\d{1,4}[-\.]\d{1,2}[-\.]\d{1,4}', v): return 0.0
                    v = v.replace(' ', '').replace('\xa0', '')
                    if v.endswith(',-') or v.endswith('.-'): v = v[:-2]
                    v = re.sub(r'[^\d,\.-]', '', v)
                    try:
                        idx_c = v.rfind(',')
                        idx_d = v.rfind('.')
                        if idx_c > idx_d: v = v.replace('.', '').replace(',', '.')
                        else: v = v.replace(',', '')
                        return float(v)
                    except: return 0.0

                sums = {c: filtered[c].apply(parse_fin).sum() for c in filtered.columns}
                target = max(sums, key=sums.get)
                
                if sums[target] == 0:
                    raise Exception("Chyba extrakce: Matice neobsahuje validní numerická finanční data.")
                
                st.info(f"**Identifikovaný finanční sloupec (Index {target}):** Agregována suma {sums[target]:,.2f} CZK")
                
                v = st.session_state.db["vypocty"]
                v["filtr_transakci"] = filtr
                v["suma_transakci"] = sums[target]
                v["pocet_transakci"] = len(filtered)
                v["celkova_pohledavka_najem"] = sum(max(0, (o["do_mesice"] - o["od_mesice"]) + 1) * o["najem"] for o in st.session_state.db["osa_najmu"])
                
                ls = st.session_state.db["lonsko"]
                v["korekce_saldo"] = ls["vysledek"] if ls["typ"] == "Preplatek" else -abs(ls["vysledek"]) if ls["typ"] == "Nedoplatek" else 0
                
                v["disponibilni_zalohy"] = v["suma_transakci"] - v["celkova_pohledavka_najem"] + v["korekce_saldo"]
                v["uznatelne_naklady"] = sum(p['castka'] for p in st.session_state.db["naklady"]["svj"] + st.session_state.db["naklady"]["dalsi_sluzby"] if p.get('preuctovatelne'))
                v["saldo_konecne"] = v["disponibilni_zalohy"] - v["uznatelne_naklady"]
                
                st.success("Kalkulace validována a zapsána do DB.")
            except Exception as e:
                st.error(f"Kritická chyba procesingu: {e}")

    if st.session_state.db["vypocty"]["pocet_transakci"] > 0:
        v_ref = st.session_state.db['vypocty']
        st.markdown("---")
        st.markdown(f"**Disponibilní zálohy:** {v_ref['disponibilni_zalohy']:,.2f} CZK | **Uznatelné náklady:** {v_ref['uznatelne_naklady']:,.2f} CZK")
        st.metric("Vypočtené konečné saldo", f"{v_ref['saldo_konecne']:,.2f} CZK")
        
        docx = generovat_word_protokol(st.session_state.db)
        fn = v_ref["filtr_transakci"].replace(" ", "_")
        st.download_button("📄 EXPORTOVAT DOCX PROTOKOL", data=docx, file_name=f"Zuctovani_{fn}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="btn_export_docx")

with t5:
    st.subheader("Serializace databáze")
    st.download_button("📥 Uložit JSON Image", data=json.dumps(st.session_state.db, indent=4, ensure_ascii=False), file_name="Data_Export.json", mime="application/json", key="btn_export_json")
    st.divider()
    up = st.file_uploader("Obnovit z JSON", type="json", key="file_import_json")
    if up and st.button("RESTORE", key="btn_restore_json"): 
        st.session_state.db = json.load(up)
        st.rerun()
