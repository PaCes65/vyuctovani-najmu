import streamlit as st
import pandas as pd
from datetime import datetime
import PyPDF2 # Nová knihovna pro čtení PDF

# --- INICIALIZACE PAMĚTI FORMULÁŘE (Session State) ---
# Toto zajistí, že se data z AI udrží v políčkách
if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "pronajimatel": "", "najemce": "", "adresa": "", "byt": "",
        "mesicni_najem": 0, "mesicni_zaloha": 0
    }

class Smlouva:
    def __init__(self, pronajimatel, najemce, adresa, byt, datum_od, datum_do, mesicni_najem, mesicni_zaloha):
        self.pronajimatel = pronajimatel
        self.najemce = najemce
        self.adresa = adresa
        self.byt = byt
        self.datum_od = datum_od
        self.datum_do = datum_do
        self.mesicni_najem = mesicni_najem
        self.mesicni_zaloha = mesicni_zaloha

def extrahuj_text_z_pdf(pdf_file):
    """Pomocná funkce pro vytažení textu z nahraného PDF souboru."""
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Chyba při čtení PDF: {e}"

def analyzuj_smlouvu_pomoci_gemini(text_smlouvy):
    """
    Zde bude reálné volání Gemini API.
    Zatím vracíme simulovaná (tzv. mock) data pro ukázku fungování UI.
    """
    # Simulujeme, že AI chvilku přemýšlí...
    import time
    time.sleep(2) 
    
    # Simulovaná odpověď od Gemini (reálně nám Gemini vrátí JSON)
    return {
        "pronajimatel": "Jan Novák st.", 
        "najemce": "Madar Ruslan", 
        "adresa": "Brněnská 123, Praha", 
        "byt": "4B",
        "mesicni_najem": 10500, 
        "mesicni_zaloha": 2800
    }

# --- MOBILNÍ ROZHRANÍ (STREAMLIT) ---
st.set_page_config(page_title="Chytré vyúčtování", page_icon="🤖", layout="centered")

st.title("🤖 Chytré vyúčtování nájmů")

# --- SEKCE A: AI PARSOVÁNÍ SMLOUVY ---
st.header("1. Nahrání a analýza smlouvy")
pdf_smlouva = st.file_uploader("Nahraj nájemní smlouvu (PDF) pro automatické vyplnění", type="pdf")

if pdf_smlouva is not None:
    if st.button("✨ Přečíst smlouvu pomocí AI", use_container_width=True):
        with st.spinner("AI čte smlouvu, moment strpení..."):
            text = extrahuj_text_z_pdf(pdf_smlouva)
            vytezena_data = analyzuj_smlouvu_pomoci_gemini(text)
            
            # Uložení dat z AI do paměti aplikace
            st.session_state.ai_data.update(vytezena_data)
            st.success("Smlouva úspěšně přečtena! Zkontroluj předvyplněné údaje níže.")

# --- SEKCE B: FORMULÁŘ (S PŘEDVYPLNĚNÍM) ---
st.header("2. Kontrola a úprava údajů ze smlouvy")

# Políčka berou svou výchozí hodnotu (value) z naší paměti (st.session_state)
col_a1, col_a2 = st.columns(2)
with col_a1:
    pronajimatel = st.text_input("Pronajímatel", value=st.session_state.ai_data["pronajimatel"])
    adresa = st.text_input("Adresa nemovitosti", value=st.session_state.ai_data["adresa"])
with col_a2:
    najemce = st.text_input("Nájemce", value=st.session_state.ai_data["najemce"])
    byt = st.text_input("Číslo/Označení bytu", value=st.session_state.ai_data["byt"])

col_b1, col_b2 = st.columns(2)
with col_b1:
    mesicni_najem = st.number_input("Měsíční čistý nájem (Kč)", value=int(st.session_state.ai_data["mesicni_najem"]), step=100)
with col_b2:
    mesicni_zaloha = st.number_input("Předepsaná záloha (Kč)", value=int(st.session_state.ai_data["mesicni_zaloha"]), step=100)

col_c1, col_c2 = st.columns(2)
with col_c1:
    datum_od = st.date_input("Smlouva platná OD")
with col_c2:
    datum_do = st.date_input("Smlouva platná DO")

# --- SEKCE C: DALŠÍ SOUBORY ---
st.header("3. Podklady pro vyúčtování")
pdf_svj_aktualni = st.file_uploader("1. Aktuální vyúčtování od SVJ (PDF)", type="pdf")
pdf_svj_minule = st.file_uploader("2. PŘEDCHOZÍ vyúčtování (PDF)", type="pdf")
vypis_banka = st.file_uploader("3. Výpis plateb (CSV/Excel)", type=["csv", "xlsx"])

if st.button("🚀 Spočítat vyúčtování", use_container_width=True):
    st.info("Zde proběhne finální výpočet...")
