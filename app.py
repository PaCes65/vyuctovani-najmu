import streamlit as st
import pandas as pd
from datetime import datetime
import PyPDF2
import google.generativeai as genai
import json
import re

# --- KONFIGURACE AI ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("⚠️ API klíč nebyl nalezen v 'Secrets'.")

def ziskej_odpoved_ai(prompt):
    """Pokusí se zavolat AI s několika variantami názvů modelů pro maximální stabilitu."""
    # Seznam modelů od nejnovějších/nejlepších
    modely = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-1.5-flash-002', 'gemini-1.0-pro']
    
    posledni_chyba = ""
    for název_modelu in modely:
        try:
            model = genai.GenerativeModel(název_modelu)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            posledni_chyba = str(e)
            continue
    
    st.error(f"❌ AI modely nejsou dostupné. Poslední chyba: {posledni_chyba}")
    return None

# --- PAMĚŤ APLIKACE ---
if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "typ_smlouvy": "Nezjištěno",
        "poskytovatel": "",
        "platce": "",
        "adresa": "",
        "byt": "",
        "mesicni_najem": 0,
        "mesicni_zaloha": 0
    }

def extrahuj_text_z_pdf(pdf_file):
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            obsah = page.extract_text()
            if obsah: text += obsah + "\n"
        return text.strip()
    except:
        return ""

def analyzuj_smlouvu(text):
    prompt = f"""
    Jsi právní expert na nájemní právo. Analyzuj text smlouvy a extrahuj data do JSONu.
    
    INSTRUKCE PRO ROLE:
    1. Zjisti název smlouvy. Pokud je to 'Podnájemní smlouva', poskytovatel je Nájemce a plátce je Podnájemce.
    2. Pokud je to 'Nájemní smlouva', poskytovatel je Pronajímatel a plátce je Nájemce.
    3. NIKDY si nevymýšlej jména (fabulace). Pokud jméno není jasné, nechej "".
    
    JSON FORMÁT:
    {{
        "typ_smlouvy": "Nájemní / Podnájemní",
        "poskytovatel": "Jméno příjemce platby",
        "platce": "Jméno plátce",
        "adresa": "Ulice, město",
        "byt": "Číslo bytu",
        "mesicni_najem": číslo,
        "mesicni_zaloha": číslo
    }}
    Text: {text}
    """
    vysledek = ziskej_odpoved_ai(prompt)
    if vysledek:
        match = re.search(r'\{.*\}', vysledek, re.DOTALL)
        if match: return json.loads(match.group())
    return st.session_state.ai_data

def audit_svj(text):
    prompt = f"""
    Jsi auditor vyúčtování. Vypiš položkově náklady z textu vyúčtování SVJ.
    U každé položky urči:
    - nazev: název služby
    - castka: částka v Kč
    - preuctovatelne: true (služby pro nájemce: voda, teplo, odpad, úklid, výtah) / false (vlastník: fond oprav, správa, pojištění)
    - vysvetleni: krátké zdůvodnění dle zákona.
    
    Vrať pouze JSON:
    {{ "polozky": [...] }}
    Text: {text}
    """
    vysledek = ziskej_odpoved_ai(prompt)
    if vysledek:
        match = re.search(r'\{.*\}', vysledek, re.DOTALL)
        if match: return json.loads(match.group())
    return {"polozky": []}

# --- UI ---
st.set_page_config(page_title="Pro Vyúčtování", layout="centered")
st.title("🏢 Profesionální vyúčtování služeb")

st.header("1. Smlouva")
soubor_sml = st.file_uploader("Vložte PDF smlouvu", type="pdf")
if soubor_sml and st.button("✨ Analyzovat smlouvu", use_container_width=True):
    with st.spinner("Právní analýza..."):
        text = extrahuj_text_z_pdf(soubor_sml)
        if text:
            st.session_state.ai_data.update(analyzuj_smlouvu(text))
            st.success("Smlouva zanalyzována.")

st.header("2. Kontrola údajů")
c1, c2 = st.columns(2)
with c1:
    v_posk = st.text_input("Poskytovatel (Příjemce)", value=st.session_state.ai_data["poskytovatel"])
    v_plat = st.text_input("Plátce (Obyvatel)", value=st.session_state.ai_data["platce"])
with c2:
    v_adr = st.text_input("Adresa", value=st.session_state.ai_data["adresa"])
    v_byt = st.text_input("Byt č.", value=st.session_state.ai_data["byt"])

c3, c4 = st.columns(2)
with c3: v_naj = st.number_input("Měsíční nájem (Kč)", value=int(st.session_state.ai_data["mesicni_najem"]))
with c4: v_zal = st.number_input("Předepsaná záloha (Kč)", value=int(st.session_state.ai_data["mesicni_zaloha"]))

st.header("3. Podklady")
soubor_svj = st.file_uploader("Vyúčtování SVJ (PDF)", type="pdf")
soubor_banka = st.file_uploader("Platby z banky (Excel/CSV)", type=["xlsx", "csv"])
v_bonus = st.number_input("Odečtený přeplatek z loňska (Kč)", value=0)

if st.button("🚀 Vygenerovat normované vyúčtování", use_container_width=True):
    if not soubor_svj or not soubor_banka:
        st.error("Chybí podklady.")
    else:
        with st.spinner("Generování položkového reportu..."):
            try:
                # Výpočet banky
                df = pd.read_csv(soubor_banka) if soubor_banka.name.endswith('.csv') else pd.read_excel(soubor_banka)
                prijato_celkem = df['Castka'].sum()
                pocet_mesicu = len(df)
                smluvni_najem_celkem = v_naj * pocet_mesicu
                uhrazene_zalohy = prijato_celkem - smluvni_najem_celkem + v_bonus

                # Audit SVJ
                txt_svj = extrahuj_text_z_pdf(soubor_svj)
                data_audit = audit_svj(txt_svj)
                polozky = data_audit.get("polozky", [])
                suma_uznatelna = sum(p['castka'] for p in polozky if p.get('preuctovatelne'))

                # REPORT
                st.divider()
                st.header("📄 PROTOKOL O ROČNÍM VYÚČTOVÁNÍ")
                
                st.subheader("I. Identifikace a vstupní data")
                st.write(f"**Typ smlouvy:** {st.session_state.ai_data['typ_smlouvy']}")
                st.write(f"**Předmět:** {v_adr}, byt č. {v_byt}")
                st.write(f"**Smluvní strany:** {v_posk} (Poskytovatel) vs. {v_plat} (Plátce)")
                
                st.subheader("II. Položkový rozbor nákladů (Audit SVJ)")
                if polozky:
                    df_rep = pd.DataFrame(polozky)
                    df_rep['Kdo hradí'] = df_rep['preuctovatelne'].map({True: "🟢 Plátce", False: "🔴 Vlastník"})
                    st.table(df_rep[['nazev', 'castka', 'Kdo hradí', 'vysvetleni']])
                
                st.subheader("III. Výpočet a finanční vypořádání")
                rozdil = uhrazene_zalohy - suma_uznatelna
                
                # Zobrazení postupu
                st.markdown(f"""
                **1. Rekapitulace plateb plátce:**
                - Celková suma plateb dle výpisu ({pocet_mesicu} měsíců): **{prijato_celkem:,.2f} Kč**
                - Odpočet čistého nájemného dle smlouvy: **- {smluvni_najem_celkem:,.2f} Kč**
                - Započtený bonus (loňský přeplatek): **+ {v_bonus:,.2f} Kč**
                - **Uhrazené zálohy na služby celkem: {uhrazene_zalohy:,.2f} Kč**
                
                **2. Rekapitulace uznatelných nákladů:**
                - Skutečné náklady na služby (viz položkový audit): **{suma_uznatelna:,.2f} Kč**
                
                **3. Závěrečné vyrovnání:**
                - Rozdíl (Zálohy - Náklady): **{rozdil:,.2f} Kč**
                """)

                if rozdil >= 0:
                    st.success(f"**VÝSLEDEK: PŘEPLATEK ve výši {rozdil:,.2f} Kč**")
                    st.info("Částka bude vrácena plátci nebo započtena do budoucích plateb.")
                else:
                    st.error(f"**VÝSLEDEK: NEDOPLATEK ve výši {abs(rozdil):,.2f} Kč**")
                    st.warning("Plátce je povinen uhradit tuto částku v zákonné lhůtě.")

            except Exception as e:
                st.error(f"Chyba ve výpočtu: {e}")
