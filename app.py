import streamlit as st
import pandas as pd
from datetime import datetime
import PyPDF2
import google.generativeai as genai
import json
import re

# --- KONFIGURACE AI ---
# Pokusíme se o maximální stabilitu při volání modelů
def ziskej_model():
    models_to_try = ['gemini-1.5-flash', 'gemini-1.5-flash-latest', 'gemini-pro']
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            # Testovací volání není možné bez promptu, tak jen připravíme instanci
            return model
        except:
            continue
    return None

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("⚠️ API klíč nebyl nalezen. Nastav GEMINI_API_KEY v Secrets ve Streamlitu.")

# --- PAMĚŤ APLIKACE (Session State) ---
if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "typ_smlouvy": "Smlouva o nájmu/podnájmu",
        "poskytovatel": "",
        "platce": "",
        "adresa": "",
        "byt": "",
        "mesicni_najem": 0,
        "mesicni_zaloha": 0
    }

def extrahuj_text_z_pdf(pdf_file):
    """Vytáhne text z PDF. Pokud je to sken (obrázek), vrátí prázdný řetězec."""
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            content = page.extract_text()
            if content:
                text += content + "\n"
        return text.strip()
    except Exception as e:
        st.error(f"Chyba při čtení souboru: {e}")
        return ""

def vycisti_a_parsuj_json(text):
    """Najde JSON v textu a převede ho na slovník."""
    try:
        # Hledáme text mezi první { a poslední }
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception:
        return None

def analyzuj_smlouvu(text_smlouvy):
    """AI analýza smlouvy s důrazem na role."""
    model = ziskej_model()
    if not model: return st.session_state.ai_data

    prompt = f"""
    Jsi právní analytik. Přečti text a extrahuj data do JSONu.
    DŮLEŽITÉ: 
    - Pokud je to 'Nájemní smlouva', poskytovatel je Pronajímatel, plátce je Nájemce.
    - Pokud je to 'Podnájemní smlouva', poskytovatel je Nájemce, plátce je Podnájemce.
    - Pokud údaj nenajdeš, neuváděj vymyšlená jména, nech prázdné "".
    - Částky uváděj jako čistá čísla.

    Vrať JSON:
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
        res = model.generate_content(prompt)
        data = vycisti_a_parsuj_json(res.text)
        return data if data else st.session_state.ai_data
    except Exception as e:
        st.warning(f"AI se nepodařilo smlouvu plně analyzovat: {e}")
        return st.session_state.ai_data

def analyzuj_vyuctovani_svj(text_vyuctovani):
    """Audit vyúčtování SVJ."""
    model = ziskej_model()
    if not model: return {"polozky": []}

    prompt = f"""
    Jsi auditor vyúčtování. Vypiš všechny nákladové položky z textu.
    Urči 'preuctovatelne': true (pro plátce: voda, teplo, odpad, úklid, výtah, el. spol. prostor) 
    nebo false (pro majitele: fond oprav, správa, pojištění, odměny výboru).
    
    Vrať JSON:
    {{
        "polozky": [
            {{"nazev": "...", "castka": 123, "duvod": "...", "preuctovatelne": true}}
        ]
    }}
    Text: {text_vyuctovani}
    """
    try:
        res = model.generate_content(prompt)
        data = vycisti_a_parsuj_json(res.text)
        return data if data else {"polozky": []}
    except Exception:
        return {"polozky": []}

# --- UI APLIKACE ---
st.set_page_config(page_title="Vyúčtování Nájmu", layout="centered")
st.title("🏢 Profesionální vyúčtování služeb")

# 1. SEKCE SMLOUVA
st.header("1. Smlouva")
soubor_sml = st.file_uploader("Nahrajte PDF smlouvu", type="pdf")
if soubor_sml and st.button("✨ Analyzovat smlouvu", use_container_width=True):
    with st.spinner("Právní analýza dokumentu..."):
        text = extrahuj_text_z_pdf(soubor_sml)
        if text:
            data = analyzuj_smlouvu(text)
            st.session_state.ai_data.update(data)
            st.success(f"Hotovo: {st.session_state.ai_data['typ_smlouvy']}")
        else:
            st.error("Z PDF se nepodařilo vyčíst text. Je to sken? Prosím, vyplňte údaje ručně níže.")

# 2. SEKCE KONTROLA
st.header("2. Kontrola údajů")
col1, col2 = st.columns(2)
with col1:
    v_poskytovatel = st.text_input("Poskytovatel (příjemce plateb)", value=st.session_state.ai_data["poskytovatel"])
    v_platce = st.text_input("Plátce (uživatel bytu)", value=st.session_state.ai_data["platce"])
with col2:
    v_adresa = st.text_input("Adresa nemovitosti", value=st.session_state.ai_data["adresa"])
    v_byt = st.text_input("Číslo bytu", value=st.session_state.ai_data["byt"])

c3, c4 = st.columns(2)
with c3:
    v_najem = st.number_input("Měsíční čistý nájem (Kč)", value=int(st.session_state.ai_data["mesicni_najem"]))
with c4:
    v_zaloha = st.number_input("Předepsaná záloha (Kč)", value=int(st.session_state.ai_data["mesicni_zaloha"]))

# 3. SEKCE PODKLADY
st.header("3. Podklady pro výpočet")
soubor_svj = st.file_uploader("Aktuální vyúčtování od SVJ (PDF)", type="pdf")
soubor_banka = st.file_uploader("Výpis plateb z banky (Excel/CSV)", type=["xlsx", "csv"])

st.subheader("Ostatní úpravy")
v_bonus = st.number_input("Bonus / Přeplatek z loňska (Kč)", value=0, help="Částka, o kterou nájemník zaplatil méně kvůli zápočtu přeplatku z minulého roku.")

if st.button("🚀 Spočítat vyúčtování", use_container_width=True):
    if not soubor_svj or not soubor_banka:
        st.error("Nahrajte prosím vyúčtování SVJ i výpis z banky.")
    else:
        with st.spinner("Provádím audit položek a výpočet..."):
            try:
                # 1. Zpracování banky
                df_b = pd.read_csv(soubor_banka) if soubor_banka.name.endswith('.csv') else pd.read_excel(soubor_banka)
                total_in = df_b['Castka'].sum()
                pocet_mesicu = len(df_b)
                suma_najem_smlouva = v_najem * pocet_mesicu
                
                # Výpočet uhrazených záloh: Co přišlo - Smluvní nájem + Co bylo započteno z loňska
                skutecne_zalohy = total_in - suma_najem_smlouva + v_bonus

                # 2. Zpracování SVJ přes AI
                text_svj = extrahuj_text_z_pdf(soubor_svj)
                audit = analyzuj_vyuctovani_svj(text_svj)
                polozky = audit.get("polozky", [])
                
                suma_uznatelna = sum(p['castka'] for p in polozky if p.get('preuctovatelne'))

                # REPORT
                st.divider()
                st.header("📄 PROTOKOL O VYÚČTOVÁNÍ")
                
                st.subheader("I. Základní údaje")
                st.write(f"**Vztah:** {st.session_state.ai_data['typ_smlouvy']}")
                st.write(f"**Předmět:** {v_adresa}, byt č. {v_byt}")
                st.write(f"**Smluvní strany:** {v_poskytovatel} (Poskytovatel) a {v_platce} (Plátce)")

                st.subheader("II. Položkový rozpis nákladů (Audit SVJ)")
                if polozky:
                    df_rep = pd.DataFrame(polozky)
                    df_rep['Odpovědnost'] = df_rep['preuctovatelne'].map({True: "🟢 Plátce", False: "🔴 Vlastník"})
                    st.table(df_rep[['nazev', 'castka', 'Odpovědnost', 'duvod']])
                else:
                    st.warning("AI nenašla v dokumentu SVJ žádné čitelné položky. Zkontrolujte, zda PDF není pouze obrázek.")

                st.subheader("III. Finanční rekapitulace")
                rozdil = skutecne_zalohy - suma_uznatelna
                
                col_res1, col_res2, col_res3 = st.columns(3)
                col_res1.metric("Uhrazené zálohy", f"{skutecne_zalohy:,.0f} Kč")
                col_res2.metric("Skutečné náklady", f"{suma_uznatelna:,.0f} Kč")
                col_res3.metric("Výsledek", f"{rozdil:,.0f} Kč")

                st.markdown(f"""
                **Podrobný postup výpočtu:**
                1. Celkem na účet od plátce ({pocet_plateb if 'pocet_plateb' in locals() else pocet_mesicu} plateb): **{total_in:,.0f} Kč**
                2. Odpočet smluvního nájemného: **- {suma_najem_smlouva:,.0f} Kč**
                3. Připočtení loňského přeplatku (bonus): **+ {v_bonus:,.0f} Kč**
                4. **Čisté uhrazené zálohy celkem: {skutecne_zalohy:,.0f} Kč**
                5. **Uznatelné náklady na služby (viz audit): {suma_uznatelna:,.0f} Kč**
                """)

                if rozdil >= 0:
                    st.success(f"**VÝSLEDEK: Přeplatek ve výši {rozdil:,.0f} Kč**")
                    st.write("Tato částka bude vrácena plátci nebo započtena do budoucích plateb.")
                else:
                    st.error(f"**VÝSLEDEK: Nedoplatek ve výši {abs(rozdil):,.0f} Kč**")
                    st.write("Plátce je povinen uhradit tuto částku v souladu se smlouvou.")

            except Exception as e:
                st.error(f"Při výpočtu došlo k chybě. Zkontrolujte název sloupce 'Castka' v Excelu. Detail: {e}")
