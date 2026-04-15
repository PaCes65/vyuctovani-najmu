import streamlit as st
import pandas as pd
from pypdf import PdfReader
import google.generativeai as genai
import json
import re

# ==========================================
# 1. KONFIGURACE A INICIALIZACE
# ==========================================
st.set_page_config(page_title="Vyúčtování PRO", layout="wide", page_icon="🏢")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("Kritická chyba: Chybí GEMINI_API_KEY v nastavení Streamlit Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "typ_smlouvy": "", "poskytovatel": "", "platce": "", 
        "adresa": "", "byt": "", "mesicni_najem": 0, "mesicni_zaloha": 0
    }

# ==========================================
# 2. CORE FUNKCE (Dynamická AI)
# ==========================================
@st.cache_resource
def zjisti_nejlepsi_model():
    try:
        dostupne_modely = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        preference = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-2.0-flash-exp', 'models/gemini-pro']
        for pref in preference:
            if pref in dostupne_modely: return pref
        for model in dostupne_modely:
            if 'gemini' in model: return model
        return dostupne_modely[0] if dostupne_modely else None
    except Exception as e:
        st.error(f"Chyba komunikace s API: {e}")
        return None

def ai_parser(prompt):
    model_name = zjisti_nejlepsi_model()
    if not model_name: raise Exception("Žádný kompatibilní AI model.")
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match: return json.loads(match.group())
        else: raise Exception("AI nevrátila validní JSON.")
    except Exception as e:
        raise Exception(f"Chyba modelu: {str(e)}")

def cteni_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = "".join(page.extract_text() + "\n" for page in reader.pages if page.extract_text())
        if not text.strip(): raise ValueError("Prázdné PDF (sken?).")
        return text
    except Exception as e:
        raise Exception(f"Chyba PDF: {str(e)}")

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ
# ==========================================
st.title("🏢 Profesionální vyúčtování (Verze s čistými zálohami)")

# --- KROK 1: SMLOUVA (Informační) ---
with st.container(border=True):
    st.subheader("1. Analýza smlouvy (Volitelné)")
    st.markdown("Nahrajte smlouvu, pokud chcete automaticky předvyplnit hlavičku protokolu.")
    pdf_smlouva = st.file_uploader("Nahrát smlouvu (PDF)", type="pdf", key="sml")
    
    if pdf_smlouva and st.button("Předvyplnit hlavičku z AI", type="primary"):
        with st.spinner("Čtu dokument..."):
            try:
                text_smlouvy = cteni_pdf(pdf_smlouva)
                prompt = f"""
                Extrahuj data. Podnájemní smlouva -> poskytovatel=Nájemce, platce=Podnájemce.
                Nájemní smlouva -> poskytovatel=Pronajímatel, platce=Nájemce.
                Vrať POUZE JSON:
                {{"typ_smlouvy": "...", "poskytovatel": "...", "platce": "...", "adresa": "...", "byt": "...", "mesicni_najem": 0, "mesicni_zaloha": 0}}
                Text smlouvy: {text_smlouvy}
                """
                st.session_state.ai_data.update(ai_parser(prompt))
                st.success("✅ Hlavička předvyplněna.")
            except Exception as e:
                st.error(f"Selhání AI: {e}")

# --- KROK 2: KONTROLA DAT ---
with st.container(border=True):
    st.subheader("2. Údaje pro protokol")
    c1, c2, c3 = st.columns(3)
    with c1:
        v_posk = st.text_input("Poskytovatel", value=st.session_state.ai_data.get("poskytovatel", ""))
        v_adr = st.text_input("Adresa", value=st.session_state.ai_data.get("adresa", ""))
    with c2:
        v_plat = st.text_input("Plátce", value=st.session_state.ai_data.get("platce", ""))
        v_byt = st.text_input("Číslo bytu", value=st.session_state.ai_data.get("byt", ""))
    with c3:
        # Přidali jsme jasné vysvětlení pro bonus
        st.info("Zde zadejte částku, kterou si nájemník v tomto roce odečetl jako vrácení přeplatku z minulého roku.")
        v_bonus = st.number_input("Odečtený přeplatek z loňska (Kč)", value=0)

# --- KROK 3: VÝPOČET ---
with st.container(border=True):
    st.subheader("3. Podklady (Audit a Zálohy)")
    col_pdf, col_xls = st.columns(2)
    with col_pdf:
        pdf_svj = st.file_uploader("Vyúčtování SVJ (PDF)", type="pdf", key="svj")
    with col_xls:
        st.markdown("**Tabulka musí obsahovat pouze ZÁLOHY (nájemné vynechte).**")
        xls_banka = st.file_uploader("Tabulka zaplacených záloh (Excel/CSV)", type=["xlsx", "csv"], key="banka")

    if st.button("Vygenerovat protokol", type="primary", use_container_width=True):
        if not pdf_svj or not xls_banka:
            st.warning("Systém vyžaduje obě přílohy.")
            st.stop()

        with st.spinner("Audit SVJ a sčítání záloh..."):
            try:
                # 1. Zpracování čistých záloh
                df = pd.read_csv(xls_banka) if xls_banka.name.endswith('.csv') else pd.read_excel(xls_banka)
                # Hledáme sloupec s částkou (názvy: castka, částka, zaloha, záloha)
                castka_col = next((col for col in df.columns if any(slovo in col.lower() for slovo in ['castka', 'částka', 'zaloha', 'záloha'])), None)
                if not castka_col:
                    st.error("V tabulce chybí sloupec 'Castka' nebo 'Zaloha'.")
                    st.stop()
                
                # Jednoduchý součet očištěných dat
                soucet_zaloh_excel = df[castka_col].sum()
                pocet_zaznamu = len(df)
                
                # Skutečný kredit plátce
                realne_zalohy = soucet_zaloh_excel + v_bonus

                # 2. Audit SVJ
                text_svj = cteni_pdf(pdf_svj)
                prompt_svj = f"""
                Jsi auditor. Vypiš všechny položky z vyúčtování.
                'preuctovatelne' = true (platí obyvatel: voda, teplo, výtah, odpad, úklid, el. spol. prostor).
                'preuctovatelne' = false (platí majitel: fond oprav, pojištění, správa, odměny).
                Vrať POUZE JSON:
                {{
                    "polozky": [
                        {{"nazev": "Teplo", "castka": 1500, "preuctovatelne": true, "duvod": "Služba"}}
                    ]
                }}
                Text: {text_svj}
                """
                audit_data = ai_parser(prompt_svj)
                polozky = audit_data.get("polozky", [])
                uznatelne_naklady = sum(p['castka'] for p in polozky if p['preuctovatelne'])
                
                # --- VYKRESLENÍ REPORTU ---
                st.markdown("---")
                st.header("📄 PROTOKOL O VYÚČTOVÁNÍ SLUŽEB")
                
                st.markdown(f"**Předmět:** {v_adr}, byt {v_byt}")
                st.markdown(f"**Poskytovatel:** {v_posk} | **Plátce:** {v_plat}")
                
                st.subheader("I. Audit nákladů budovy (SVJ)")
                if polozky:
                    df_audit = pd.DataFrame(polozky)
                    df_audit['Zodpovědnost'] = df_audit['preuctovatelne'].map({True: "🟢 Plátce (Služby)", False: "🔴 Vlastník (Fond oprav apod.)"})
                    st.dataframe(df_audit[['nazev', 'castka', 'Zodpovědnost', 'duvod']], use_container_width=True, hide_index=True)

                st.subheader("II. Rekapitulace a Vyrovnání")
                rozdil = realne_zalohy - uznatelne_naklady

                r1, r2, r3 = st.columns(3)
                r1.metric("Kredit plátce (Uhrazené zálohy)", f"{realne_zalohy:,.2f} Kč")
                r2.metric("Debet plátce (Náklady na služby)", f"{uznatelne_naklady:,.2f} Kč")
                r3.metric("Výsledek zúčtování", f"{rozdil:,.2f} Kč")

                st.markdown(f"""
                **Detail výpočtu kreditu:**
                1. Součet přijatých záloh dle tabulky ({pocet_zaznamu} záznamů): **{soucet_zaloh_excel:,.2f} Kč**
                2. Přičtení přeplatku z loňska (pokud byl odečten z platby): **+ {v_bonus:,.2f} Kč**
                3. **Celkový kredit plátce k zúčtování: {realne_zalohy:,.2f} Kč**
                """)

                if rozdil > 0:
                    st.success(f"### VÝSLEDEK: Přeplatek ve výši {rozdil:,.2f} Kč")
                    st.write("Částka bude plátci vrácena na účet, nebo započtena do plateb dalšího období.")
                elif rozdil < 0:
                    st.error(f"### VÝSLEDEK: Nedoplatek ve výši {abs(rozdil):,.2f} Kč")
                    st.write("Plátce je povinen částku uhradit poskytovateli v zákonné lhůtě.")
                else:
                    st.info("### VÝSLEDEK: Vyrovnáno (0 Kč)")

            except Exception as e:
                st.error(f"Chyba výpočtu: {e}")
