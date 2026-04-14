import streamlit as st
import pandas as pd
from datetime import datetime
import PyPDF2
import google.generativeai as genai
import json

# --- NASTAVENÍ AI ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("⚠️ Nebyl nalezen API klíč v Secrets.")

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
    prompt = f"""
    Extrahuj data z textu smlouvy o bydlení do JSON.
    1. Zjisti typ (Nájemní smlouva / Podnájemní smlouva).
    2. NÁJEM: "poskytovatel" = Pronajímatel, "platce" = Nájemce. PODNÁJEM: "poskytovatel" = Nájemce, "platce" = Podnájemce.
    {{
        "typ_smlouvy": "...", "poskytovatel": "...", "platce": "...", "adresa": "...", "byt": "...",
        "mesicni_najem": cislo, "mesicni_zaloha": cislo
    }}
    Text: {text_smlouvy}
    """
    try:
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            res = model.generate_content(prompt)
        except:
            model = genai.GenerativeModel('gemini-2.5-pro')
            res = model.generate_content(prompt)
            
        cisty_text = res.text.strip()
        if "
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
http://googleusercontent.com/immersive_entry_chip/2
http://googleusercontent.com/immersive_entry_chip/3

Když teď aplikaci spustíš, přesně uvidíš, jaká čísla si AI z vyúčtování vytáhla, a můžeš si zkontrolovat, jestli třeba omylem nazařadila odměny výboru mezi tvoje náklady. 

Budeme v dalším kroku chtít do kódu přidat tlačítko, které tento vygenerovaný report uloží do pěkného PDF souboru, abys ho mohl rovnou poslat nájemníkovi/podnájemníkovi?
