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
    st.error("⚠️ V 'Secrets' nebyl nalezen API klíč. Aplikace nebude fungovat.")

# --- PAMĚŤ APLIKACE (Session State) ---
if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "typ_smlouvy": "",
        "poskytovatel": "",
        "platce": "",
        "adresa": "",
        "byt": "",
        "mesicni_najem": 0,
        "mesicni_zaloha": 0
    }

def extrahuj_text_z_pdf(pdf_file):
    """Vytáhne surový text z nahraného PDF souboru."""
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return ""

def analyzuj_smlouvu(text_smlouvy):
    """Analyzuje typ smlouvy a rozděluje role (poskytovatel vs. plátce)."""
    prompt = f"""
    Jsi právní analytik. Přečti si text a extrahuj data do JSONu.
    
    PRAVIDLA PRO ROLE:
    1. Urči, zda jde o 'Nájemní smlouvu' nebo 'Podnájemní smlouva'.
    2. Pokud NÁJEMNÍ: Poskytovatel = Pronajímatel, Plátce = Nájemce.
    3. Pokud PODNÁJEMNÍ: Poskytovatel = Nájemce (ten kdo byt pronajímá dál), Plátce = Podnájemce.
    4. U částek hledej 'nájemné' (čistý nájem) a 'zálohy na služby' (poplatky SVJ).
    
    VRÁTÍŠ POUZE ČISTÝ JSON:
    {{
        "typ_smlouvy": "...",
        "poskytovatel": "...",
        "platce": "...",
        "adresa": "...",
        "byt": "...",
        "mesicni_najem": cislo,
        "mesicni_zaloha": cislo
    }}
    Text: {text_smlouvy}
    """
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        res = model.generate_content(prompt)
        cisty_text = res.text.strip().replace("```json", "").replace("```", "")
        return json.loads(cisty_text)
    except:
        return st.session_state.ai_data

def analyzuj_vyuctovani_svj(text_vyuctovani):
    """Provede položkový audit vyúčtování od SVJ/družstva."""
    prompt = f"""
    Jsi auditor vyúčtování služeb. Projdi text a vypiš VŠECHNY nákladové položky do JSON tabulky.
    
    PRAVIDLO PRO PŘEÚČTOVÁNÍ (dle českých norem):
    - TRUE (Plátce): Teplo, Voda, Odpad, Výtah, Úklid, El. spol. prostor, TV/Rádio.
    - FALSE (Majitel): Fond oprav (Dlouhodobá záloha), Pojištění, Odměny výboru, Správa.
    
    VRÁTÍŠ POUZE ČISTÝ JSON:
    {{
        "polozky": [
            {{"nazev": "...", "castka": 123, "duvod": "...", "preuctovatelne": true}}
        ]
    }}
    Text: {text_vyuctovani}
    """
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        res = model.generate_content(prompt)
        cisty_text = res.text.strip().replace("```json", "").replace("```", "")
        return json.loads(cisty_text)
    except:
        return {"polozky": []}

# --- GRAFICKÉ ROZHRANÍ ---
st.set_page_config(page_title="Vyúčtování Nájmu", layout="centered")
st.title("🏢 Profesionální vyúčtování nájmů")

# --- KROK 1: SMLOUVA ---
st.header("1. Analýza smlouvy")
soubor_smlouva = st.file_uploader("Nahrajte PDF smlouvu", type="pdf", key="smlouva_up")
if soubor_smlouva and st.button("✨ Analyzovat smlouvu přes AI", use_container_width=True):
    with st.spinner("AI zkoumá právní vztahy..."):
        text = extrahuj_text_z_pdf(soubor_smlouva)
        data = analyzuj_smlouvu(text)
        st.session_state.ai_data.update(data)
        st.success(f"Rozpoznána: {st.session_state.ai_data['typ_smlouvy']}")

# --- KROK 2: KONTROLA DAT ---
st.header("2. Kontrola údajů")
col1, col2 = st.columns(2)
with col1:
    v_poskytovatel = st.text_input("Poskytovatel (příjemce)", value=st.session_state.ai_data["poskytovatel"])
    v_platce = st.text_input("Plátce (nájemce/podnájemce)", value=st.session_state.ai_data["platce"])
with col2:
    v_adresa = st.text_input("Adresa", value=st.session_state.ai_data["adresa"])
    v_byt = st.text_input("Byt č.", value=st.session_state.ai_data["byt"])

col3, col4 = st.columns(2)
with col3:
    v_m_najem = st.number_input("Smluvní měsíční nájem (Kč)", value=int(st.session_state.ai_data["mesicni_najem"]))
with col4:
    v_m_zaloha = st.number_input("Předepsaná záloha (Kč)", value=int(st.session_state.ai_data["mesicni_zaloha"]))

# --- KROK 3: VÝPOČET ---
st.header("3. Podklady pro vyúčtování")
soubor_svj = st.file_uploader("Vyúčtování SVJ (PDF)", type="pdf", key="svj_up")
soubor_banka = st.file_uploader("Platby z banky (Excel/CSV)", type=["xlsx", "csv"], key="banka_up")

st.subheader("Ostatní úpravy")
v_bonus = st.number_input("Bonus / Přeplatek z loňska (Kč)", value=0, help="Částka, o kterou nájemník zaplatil méně kvůli zápočtu loňského přeplatku.")

if st.button("🚀 Spočítat vyúčtování", use_container_width=True):
    if not soubor_svj or not soubor_banka:
        st.error("Prosím nahrajte vyúčtování SVJ i výpis plateb.")
    else:
        with st.spinner("Provádím položkový audit..."):
            try:
                # 1. Analýza plateb
                df_banka = pd.read_csv(soubor_banka) if soubor_banka.name.endswith('.csv') else pd.read_excel(soubor_banka)
                total_prijato = df_banka['Castka'].sum()
                pocet_plateb = len(df_banka)
                celkove_najemne = v_m_najem * pocet_plateb
                # Čisté zálohy = Vše co přišlo - Nájemné + co si odečetl z loňska
                ciste_zalohy = total_prijato - celkove_najemne + v_bonus

                # 2. Audit SVJ
                text_svj = extrahuj_text_z_pdf(soubor_svj)
                audit = analyzuj_vyuctovani_svj(text_svj)
                polozky = audit.get("polozky", [])
                
                suma_uznatelna = sum(p['castka'] for p in polozky if p.get('preuctovatelne'))
                suma_vlastnik = sum(p['castka'] for p in polozky if not p.get('preuctovatelne'))

                # --- VÝSTUP REPORTU ---
                st.divider()
                st.header("📄 Protokol o vyúčtování")
                
                st.write(f"**Vztah:** {st.session_state.ai_data['typ_smlouvy']}")
                st.write(f"**Nemovitost:** {v_adresa}, byt {v_byt}")
                
                st.subheader("Položkový rozpis nákladů (Audit SVJ)")
                if polozky:
                    df_rep = pd.DataFrame(polozky)
                    df_rep['Kdo hradí'] = df_rep['preuctovatelne'].map({True: "🟢 Plátce", False: "🔴 Vlastník"})
                    st.table(df_rep[['nazev', 'castka', 'Kdo hradí', 'duvod']])
                
                st.subheader("Finální bilance")
                rozdil = ciste_zalohy - suma_uznatelna
                
                res_col1, res_col2, res_col3 = st.columns(3)
                res_col1.metric("Uhrazené zálohy", f"{ciste_zalohy:,.0f} Kč")
                res_col2.metric("Uznatelné náklady", f"{suma_uznatelna:,.0f} Kč")
                res_col3.metric("Výsledek", f"{rozdil:,.0f} Kč")

                st.markdown(f"""
                **Detailní postup výpočtu:**
                - Celkem přijato na účet ({pocet_plateb} plateb): **{total_prijato:,.0f} Kč**
                - Smluvní nájemné k odečtení: **- {celkove_najemne:,.0f} Kč**
                - Započtený bonus (loňský přeplatek): **+ {v_bonus:,.0f} Kč**
                - **Čisté uhrazené zálohy celkem: {ciste_zalohy:,.0f} Kč**
                - **Uznatelné náklady (viz audit): {suma_uznatelna:,.0f} Kč**
                """)

                if rozdil >= 0:
                    st.success(f"**Přeplatek k vrácení plátci: {rozdil:,.0f} Kč**")
                else:
                    st.error(f"**Nedoplatek plátce: {abs(rozdil):,.0f} Kč**")

            except Exception as e:
                st.error(f"Došlo k chybě při zpracování: {e}")
