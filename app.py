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
    st.error("⚠️ Nebyl nalezen API klíč. Zkontroluj nastavení 'Secrets' ve Streamlitu.")

# --- INICIALIZACE PAMĚTI ---
if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "pronajimatel": "", "najemce": "", "adresa": "", "byt": "",
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
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Vytáhni z textu tyto údaje a vrať je POUZE jako platný formát JSON. Dej si pozor na to, kdo je pronajímatel (majitel) a kdo nájemce:
        {{
            "pronajimatel": "Jméno pronajímatele",
            "najemce": "Jméno nájemce",
            "adresa": "Ulice a město",
            "byt": "Číslo bytu",
            "mesicni_najem": cislo,
            "mesicni_zaloha": cislo
        }}
        Text smlouvy: {text_smlouvy}
        """
        response = model.generate_content(prompt)
        cisty_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cisty_text)
    except:
        return st.session_state.ai_data

def analyzuj_vyuctovani_svj(text_vyuctovani):
    """Nová funkce: AI přečte roční vyúčtování a najde náklady pro nájemníka."""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Jsi účetní expert. Přečti si text vyúčtování od SVJ/družstva.
        Najdi celkovou částku za služby, které se běžně přeúčtovávají na nájemníka (např. teplo, voda, elektřina spol. prostor, výtah, odpad).
        Nezapočítávej to, co platí majitel (fond oprav, odměny výboru).
        Vrať POUZE JSON s jednou hodnotou:
        {{
            "uznatelne_naklady_celkem": cislo
        }}
        Text: {text_vyuctovani}
        """
        response = model.generate_content(prompt)
        cisty_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cisty_text)
    except:
        return {"uznatelne_naklady_celkem": 0}

# --- ROZHRANÍ APLIKACE ---
st.set_page_config(page_title="Chytré vyúčtování", page_icon="🏢", layout="centered")

st.title("🏢 Chytré vyúčtování nájmů")

st.header("1. Smlouva")
pdf_smlouva = st.file_uploader("Nahraj smlouvu (PDF) pro předvyplnění", type="pdf")
if pdf_smlouva and st.button("✨ Přečíst smlouvu pomocí AI", use_container_width=True):
    with st.spinner("Čtu smlouvu..."):
        text = extrahuj_text_z_pdf(pdf_smlouva)
        st.session_state.ai_data.update(analyzuj_smlouvu_pomoci_gemini(text))
        st.success("Hotovo! Zkontroluj a případně ručně oprav políčka níže.")

st.header("2. Údaje")
col_a1, col_a2 = st.columns(2)
with col_a1:
    pronajimatel = st.text_input("Pronajímatel", value=st.session_state.ai_data.get("pronajimatel", ""))
with col_a2:
    najemce = st.text_input("Nájemce", value=st.session_state.ai_data.get("najemce", ""))

byt = st.text_input("Číslo bytu", value=st.session_state.ai_data.get("byt", ""))

st.header("3. Podklady pro vyúčtování")
pdf_svj_aktualni = st.file_uploader("1. Aktuální vyúčtování od SVJ (PDF)", type="pdf")
vypis_banka = st.file_uploader("2. Výpis plateb (Excel/CSV)", type=["csv", "xlsx"])

# --- NOVÝ MOTOR PRO TLAČÍTKO ---
if st.button("🚀 Spočítat vyúčtování", use_container_width=True):
    if not pdf_svj_aktualni or not vypis_banka:
        st.error("⚠️ Prosím nahraj vyúčtování od SVJ i výpis plateb.")
    else:
        with st.spinner("Zpracovávám tabulky a analyzuji vyúčtování..."):
            try:
                # 1. Výpočet zaplacených záloh z Excelu
                if vypis_banka.name.endswith('.csv'):
                    df = pd.read_csv(vypis_banka)
                else:
                    df = pd.read_excel(vypis_banka)
                
                # Předpokládáme, že sloupec se jmenuje "Castka"
                zaplaceno_zalohy = df['Castka'].sum()

                # 2. Zjištění nákladů z PDF pomocí AI
                text_svj = extrahuj_text_z_pdf(pdf_svj_aktualni)
                vysledek_ai = analyzuj_vyuctovani_svj(text_svj)
                naklady_svj = vysledek_ai.get("uznatelne_naklady_celkem", 0)

                # 3. Matematika
                rozdil = zaplaceno_zalohy - naklady_svj
                stav = "PŘEPLATEK pro nájemníka" if rozdil >= 0 else "NEDOPLATEK (nájemník dluží)"

                # 4. Zobrazení výsledku na displeji
                st.success("✅ Výpočet dokončen!")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Zaplaceno na zálohách", f"{zaplaceno_zalohy:,.0f} Kč")
                col2.metric("Náklady domu (AI)", f"{naklady_svj:,.0f} Kč")
                col3.metric("Výsledek", f"{abs(rozdil):,.0f} Kč")
                
                st.info(f"Konečný stav: **{stav}** ve výši **{abs(rozdil):,.0f} Kč**.")
                st.write("*(Upozornění: AI čte náklady SVJ orientačně, vždy ověř s původním PDF dokumentem, zda nezapočítala např. fond oprav.)*")

            except Exception as e:
                st.error(f"Při výpočtu nastala chyba: Ujisti se, že má tvůj Excel sloupeček pojmenovaný 'Castka'. Detail chyby: {e}")
