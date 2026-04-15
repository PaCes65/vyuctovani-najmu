import streamlit as st
import pandas as pd
from datetime import datetime
import PyPDF2
import google.generativeai as genai
import json
import re

# --- KONFIGURACE ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Chybí GEMINI_API_KEY v Secrets.")

if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "typ_smlouvy": "", "poskytovatel": "", "platce": "", "adresa": "", "byt": "",
        "mesicni_najem": 0, "mesicni_zaloha": 0
    }

def extrahuj_text_z_pdf(pdf_file):
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            content = page.extract_text()
            if content: text += content + "\n"
        return text.strip()
    except:
        return ""

def volani_ai(prompt):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group()) if match else None
    except:
        return None

# --- UI ---
st.set_page_config(page_title="Vyúčtování PRO", layout="centered")
st.title("🏢 Profesionální vyúčtování služeb")

st.header("1. Smlouva")
soubor_sml = st.file_uploader("Vložte PDF smlouvu", type="pdf")
if soubor_sml and st.button("✨ Analyzovat smlouvu"):
    text = extrahuj_text_z_pdf(soubor_sml)
    prompt = f"""Jsi právník. Z textu smlouvy extrahuj JSON. 
    Pokud jde o PODNÁJEM: poskytovatel je Nájemce, plátce je Podnájemce.
    Pokud jde o NÁJEM: poskytovatel je Pronajímatel, plátce je Nájemce.
    JSON: {{"typ_smlouvy":"","poskytovatel":"","platce":"","adresa":"","byt":"","mesicni_najem":0,"mesicni_zaloha":0}}
    Text: {text}"""
    data = volani_ai(prompt)
    if data:
        st.session_state.ai_data.update(data)
        st.success("Smlouva načtena.")

st.header("2. Údaje")
c1, c2 = st.columns(2)
with c1:
    posk = st.text_input("Poskytovatel", value=st.session_state.ai_data["poskytovatel"])
    adr = st.text_input("Adresa", value=st.session_state.ai_data["adresa"])
with c2:
    plat = st.text_input("Plátce", value=st.session_state.ai_data["platce"])
    byt_c = st.text_input("Byt č.", value=st.session_state.ai_data["byt"])

c3, c4 = st.columns(2)
with c3: naj = st.number_input("Měsíční nájem (Kč)", value=int(st.session_state.ai_data["mesicni_najem"]))
with c4: zal = st.number_input("Měsíční záloha (Kč)", value=int(st.session_state.ai_data["mesicni_zaloha"]))

st.header("3. Podklady")
soubor_svj = st.file_uploader("Vyúčtování SVJ (PDF)", type="pdf")
soubor_banka = st.file_uploader("Platby (Excel/CSV)", type=["xlsx", "csv"])
v_bonus = st.number_input("Loňský přeplatek/bonus (Kč)", value=0)

if st.button("🚀 Spočítat vyúčtování"):
    if soubor_svj and soubor_banka:
        # Banka
        df = pd.read_csv(soubor_banka) if soubor_banka.name.endswith('.csv') else pd.read_excel(soubor_banka)
        celkem_banka = df['Castka'].sum()
        uhrazene_zalohy = celkem_banka - (naj * len(df)) + v_bonus
        
        # SVJ Audit
        txt_svj = extrahuj_text_z_pdf(soubor_svj)
        prompt_svj = f"""Jsi auditor. Z textu vyúčtování SVJ vypiš položky do JSON.
        preuctovatelne=true pouze pro služby (voda, teplo, odpad, úklid, výtah). Fond oprav=false.
        JSON: {{"polozky":[{{"nazev":"","castka":0,"preuctovatelne":true,"duvod":""}}]}}
        Text: {txt_svj}"""
        audit = volani_ai(prompt_svj)
        
        if audit:
            st.divider()
            st.header("📄 PROTOKOL O VYÚČTOVÁNÍ")
            st.write(f"**Poskytovatel:** {posk} | **Plátce:** {plat}")
            st.write(f"**Nemovitost:** {adr}, byt {byt_c}")
            
            pol = audit.get("polozky", [])
            df_p = pd.DataFrame(pol)
            df_p['Odpovědnost'] = df_p['preuctovatelne'].map({True: "🟢 Plátce", False: "🔴 Vlastník"})
            st.table(df_p[['nazev', 'castka', 'Odpovědnost']])
            
            uznatelne = sum(p['castka'] for p in pol if p.get('preuctovatelne'))
            rozdil = uhrazene_zalohy - uznatelne
            
            st.subheader("Finanční bilance")
            st.write(f"Uhrazené zálohy (po odečtu nájmu): **{uhrazene_zalohy:,.2f} Kč**")
            st.write(f"Skutečné uznatelné náklady: **{uznatelne:,.2f} Kč**")
            
            if rozdil >= 0:
                st.success(f"PŘEPLATEK: {rozdil:,.2f} Kč")
            else:
                st.error(f"NEDOPLATEK: {abs(rozdil):,.2f} Kč")
