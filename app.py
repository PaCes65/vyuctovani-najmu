import streamlit as st
import pandas as pd
from datetime import datetime
import PyPDF2
import google.generativeai as genai
import json
import re

# --- NASTAVENÍ AI ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("⚠️ Nebyl nalezen API klíč v Secrets.")

# --- INICIALIZACE PAMĚTI ---
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
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return ""

def analyzuj_smlouvu_pomoci_gemini(text_smlouvy):
    """AI s bezpečnostní pojistkou (fallback) pro případ výpadku nového modelu."""
    prompt = f"""
    Jsi profesionální analytik českých právních dokumentů. Extrahuj data z textu smlouvy o bydlení.
    
    DŮLEŽITÁ PRAVIDLA PRO ROLE:
    1. Nejdříve zjisti název/typ smlouvy (Nájemní smlouva vs. Podnájemní smlouva).
    2. Podle typu správně urči funkční role:
       - Pokud je to NÁJEMNÍ smlouva: "poskytovatel" = Pronajímatel, "platce" = Nájemce.
       - Pokud je to PODNÁJEMNÍ smlouva: "poskytovatel" = Nájemce, "platce" = Podnájemce.
    3. NIKDY si nevymýšlej jména ani čísla. Pokud chybí, vrať prázdný řetězec "".
    
    Vrať výsledek POUZE jako čistý JSON:
    {{
        "typ_smlouvy": "Nájemní smlouva / Podnájemní smlouva / Jiná",
        "poskytovatel": "Jméno toho, kdo byt přenechává a přijímá platby",
        "platce": "Jméno toho, kdo byt užívá a platí",
        "adresa": "ulice, město",
        "byt": "číslo bytu",
        "mesicni_najem": číslo,
        "mesicni_zaloha": číslo
    }}

    Text smlouvy:
    {text_smlouvy}
    """
    try:
        # Pokus 1: Nejnovější model
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = model.generate_content(prompt)
    except:
        try:
            # Pokus 2: Bezpečný fallback na univerzální model
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(prompt)
        except Exception as e:
            st.error(f"Chyba při komunikaci s AI: {e}")
            return st.session_state.ai_data

    try:
        cisty_text = response.text.strip()
        if "```json" in cisty_text:
            cisty_text = cisty_text.split("```json")[1].split("```")[0].strip()
        elif "```" in cisty_text:
            cisty_text = cisty_text.split("```")[1].split("```")[0].strip()
            
        data = json.loads(cisty_text)
        return data
    except Exception as e:
        st.error(f"Chyba při čtení dat z AI: {e}")
        return st.session_state.ai_data

# --- ROZHRANÍ APLIKACE ---
st.set_page_config(page_title="Chytré vyúčtování", page_icon="🏢", layout="centered")

st.title("🏢 Chytré vyúčtování nájmů")

st.header("1. Analýza smlouvy")
pdf_smlouva = st.file_uploader("Nahraj smlouvu (PDF)", type="pdf")

if pdf_smlouva and st.button("✨ Přečíst smlouvu pomocí AI", use_container_width=True):
    with st.spinner("AI detekuje typ smlouvy a analyzuje role..."):
        text = extrahuj_text_z_pdf(pdf_smlouva)
        if text.strip():
            vysledek = analyzuj_smlouvu_pomoci_gemini(text)
            for key in vysledek:
                st.session_state.ai_data[key] = vysledek[key]
            st.success(f"Hotovo! Detekována: **{st.session_state.ai_data.get('typ_smlouvy', 'Neznámá smlouva')}**")
        else:
            st.error("Z PDF se nepodařilo vytáhnout žádný text.")

st.header("2. Kontrola údajů")
col1, col2 = st.columns(2)
with col1:
    poskytovatel = st.text_input("Poskytovatel bytu (přijímá peníze)", value=st.session_state.ai_data.get("poskytovatel", ""))
    adresa = st.text_input("Adresa", value=st.session_state.ai_data.get("adresa", ""))
with col2:
    platce = st.text_input("Plátce (užívá byt a platí)", value=st.session_state.ai_data.get("platce", ""))
    byt_c = st.text_input("Číslo bytu", value=st.session_state.ai_data.get("byt", ""))

col3, col4 = st.columns(2)
with col3:
    m_najem = st.number_input("Čistý nájem (Kč)", value=int(st.session_state.ai_data.get("mesicni_najem", 0)))
with col4:
    m_zaloha = st.number_input("Záloha na služby (Kč)", value=int(st.session_state.ai_data.get("mesicni_zaloha", 0)))

st.header("3. Podklady pro výpočet")
pdf_svj = st.file_uploader("Aktuální vyúčtování SVJ (PDF)", type="pdf")
vypis = st.file_uploader("Výpis plateb (Excel/CSV)", type=["csv", "xlsx"])

if st.button("🚀 Spočítat vyúčtování", use_container_width=True):
    if not pdf_svj or not vypis:
        st.error("Nahraj prosím vyúčtování SVJ a výpis plateb.")
    else:
        with st.spinner("Počítám..."):
            try:
                if vypis.name.endswith('.csv'):
                    df = pd.read_csv(vypis)
                else:
                    df = pd.read_excel(vypis)
                
                celkem_zaplaceno = df['Castka'].sum()

                text_svj = extrahuj_text_z_pdf(pdf_svj)
                prompt_svj = f"V tomto textu vyúčtování najdi celkovou částku za služby, které se přeúčtovávají uživateli bytu. Ignoruj fond oprav. Vrať jen číslo. Text: {text_svj}"
                
                # Stejná pojistka i pro výpočet SVJ
                try:
                    model = genai.GenerativeModel('gemini-1.5-flash-latest')
                    res_svj = model.generate_content(prompt_svj)
                except:
                    model = genai.GenerativeModel('gemini-pro')
                    res_svj = model.generate_content(prompt_svj)
                
                cisla = re.findall(r'\d+', res_svj.text.replace(" ", ""))
                naklady_svj = int(cisla[0]) if cisla else 0

                rozdil = celkem_zaplaceno - naklady_svj
                
                st.divider()
                st.subheader("Výsledek vyúčtování")
                st.write(f"**Poskytovatel:** {poskytovatel}")
                st.write(f"**Plátce:** {platce}")
                st.write(f"**Byt č.:** {byt_c}")
                
                c1, c2 = st.columns(2)
                c1.metric("Zaplacené zálohy", f"{celkem_zaplaceno:,.0f} Kč")
                c2.metric("Skutečné náklady", f"{naklady_svj:,.0f} Kč")
                
                if rozdil >= 0:
                    st.success(f"Přeplatek k vrácení plátci: {rozdil:,.0f} Kč")
                else:
                    st.error(f"Nedoplatek (plátce dluží): {abs(rozdil):,.0f} Kč")
                    
            except Exception as e:
                st.error(f"Chyba při výpočtu: Ujisti se, že máš v Excelu sloupec 'Castka'. Detail chyby: {e}")
