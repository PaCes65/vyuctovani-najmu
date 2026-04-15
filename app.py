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

# Ověření API klíče
if "GEMINI_API_KEY" not in st.secrets:
    st.error("Kritická chyba: Chybí GEMINI_API_KEY v nastavení Streamlit Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Stav aplikace
if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "typ_smlouvy": "", "poskytovatel": "", "platce": "", 
        "adresa": "", "byt": "", "mesicni_najem": 0, "mesicni_zaloha": 0
    }

# ==========================================
# 2. CORE FUNKCE (Dynamická AI & Zpracování)
# ==========================================
@st.cache_resource
def zjisti_nejlepsi_model():
    """Dynamicky zjistí dostupné modely pro daný API klíč a vybere ten nejlepší. Řeší chybu 404."""
    try:
        dostupne_modely = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Seznam preferencí (od nejlepšího)
        preference = [
            'models/gemini-1.5-flash', 'models/gemini-1.5-pro', 
            'models/gemini-2.0-flash-exp', 'models/gemini-pro', 'models/gemini-1.0-pro'
        ]
        
        for pref in preference:
            if pref in dostupne_modely:
                return pref
                
        # Pokud nenajde preferované, vezme první dostupný Gemini model
        for model in dostupne_modely:
            if 'gemini' in model:
                return model
        return dostupne_modely[0] if dostupne_modely else None
    except Exception as e:
        st.error(f"Chyba při komunikaci s API: {e}")
        return None

def ai_parser(prompt):
    """Spolehlivé volání AI s extrakcí JSONu."""
    model_name = zjisti_nejlepsi_model()
    if not model_name:
        raise Exception("Pro tento API klíč nebyl nalezen žádný kompatibilní AI model.")
    
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        
        # Robustní parsování JSONu pomocí regulárních výrazů
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
        else:
            raise Exception(f"AI nevrátila JSON. Odpověď: {response.text[:200]}...")
    except Exception as e:
        raise Exception(f"Chyba modelu {model_name}: {str(e)}")

def cteni_pdf(file_obj):
    """Extrakce textu z PDF."""
    try:
        reader = PdfReader(file_obj)
        text = "".join(page.extract_text() + "\n" for page in reader.pages if page.extract_text())
        if not text.strip():
            raise ValueError("PDF neobsahuje čitelný text (pravděpodobně obrázkový sken).")
        return text
    except Exception as e:
        raise Exception(f"Nelze přečíst PDF: {str(e)}")

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ
# ==========================================
st.title("🏢 Profesionální systém vyúčtování")

# --- KROK 1: SMLOUVA ---
with st.container(border=True):
    st.subheader("1. Analýza smlouvy")
    pdf_smlouva = st.file_uploader("Nahrát smlouvu (PDF)", type="pdf", key="sml")
    
    if pdf_smlouva and st.button("Spustit AI analýzu smlouvy", type="primary"):
        with st.spinner("AI čte dokument a extrahuje role..."):
            try:
                text_smlouvy = cteni_pdf(pdf_smlouva)
                prompt = f"""
                Jsi právní parser. Extrahuj data.
                Pokud je to Podnájemní smlouva -> poskytovatel=Nájemce, platce=Podnájemce.
                Pokud je to Nájemní smlouva -> poskytovatel=Pronajímatel, platce=Nájemce.
                Vrať POUZE JSON:
                {{
                    "typ_smlouvy": "Nájemní / Podnájemní", "poskytovatel": "Jméno", "platce": "Jméno",
                    "adresa": "Ulice, Město", "byt": "Číslo", "mesicni_najem": 0, "mesicni_zaloha": 0
                }}
                Text smlouvy: {text_smlouvy}
                """
                data = ai_parser(prompt)
                st.session_state.ai_data.update(data)
                st.success("✅ Smlouva úspěšně analyzována.")
            except Exception as e:
                st.error(f"Selhání: {e}")

# --- KROK 2: DATA ---
with st.container(border=True):
    st.subheader("2. Kontrola a parametry")
    c1, c2, c3 = st.columns(3)
    with c1:
        v_posk = st.text_input("Poskytovatel (příjemce)", value=st.session_state.ai_data.get("poskytovatel", ""))
        v_adr = st.text_input("Adresa", value=st.session_state.ai_data.get("adresa", ""))
    with c2:
        v_plat = st.text_input("Plátce (obyvatel)", value=st.session_state.ai_data.get("platce", ""))
        v_byt = st.text_input("Číslo bytu", value=st.session_state.ai_data.get("byt", ""))
    with c3:
        v_najem = st.number_input("Smluvní čistý nájem (Kč)", value=int(st.session_state.ai_data.get("mesicni_najem", 0)))
        v_bonus = st.number_input("Odečtený přeplatek z loňska (Kč)", value=0, help="Kredit, o který plátce ponížil své platby.")

# --- KROK 3: VÝPOČET ---
with st.container(border=True):
    st.subheader("3. Podklady a Audit")
    col_pdf, col_xls = st.columns(2)
    with col_pdf:
        pdf_svj = st.file_uploader("Vyúčtování SVJ (PDF)", type="pdf", key="svj")
    with col_xls:
        xls_banka = st.file_uploader("Platby plátce (Excel/CSV)", type=["xlsx", "csv"], key="banka")

    if st.button("Vygenerovat protokol", type="primary", use_container_width=True):
        if not pdf_svj or not xls_banka:
            st.warning("Systém vyžaduje obě přílohy.")
            st.stop()

        with st.spinner("Provádím položkový audit a finanční výpočet..."):
            try:
                # 1. Zpracování banky
                df = pd.read_csv(xls_banka) if xls_banka.name.endswith('.csv') else pd.read_excel(xls_banka)
                castka_col = next((col for col in df.columns if 'castka' in col.lower() or 'částka' in col.lower()), None)
                if not castka_col:
                    raise Exception("V Excelu chybí sloupec 'Castka'.")
                
                celkem_prijato = df[castka_col].sum()
                pocet_mesicu = len(df)
                celkove_najemne = v_najem * pocet_mesicu
                # Klíčová logika: Vše přijato - Nájem = Zálohy (+ případný kredit z loňska)
                realne_zalohy = celkem_prijato - celkove_najemne + v_bonus

                # 2. Zpracování SVJ (Položkový audit)
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
                
                # Identifikace
                st.markdown(f"**Vztah:** {st.session_state.ai_data.get('typ_smlouvy', 'Nespecifikováno')} | **Předmět:** {v_adr}, byt {v_byt}")
                st.markdown(f"**Poskytovatel:** {v_posk} | **Plátce:** {v_plat}")
                
                # Tabulka SVJ
                st.subheader("I. Audit nákladů budovy (SVJ)")
                if polozky:
                    df_audit = pd.DataFrame(polozky)
                    df_audit['Zodpovědnost'] = df_audit['preuctovatelne'].map({True: "🟢 Plátce", False: "🔴 Vlastník"})
                    st.dataframe(df_audit[['nazev', 'castka', 'Zodpovědnost', 'duvod']], use_container_width=True, hide_index=True)
                else:
                    st.warning("Nebyla nalezena žádná data o nákladech.")

                # Matematika a Výsledek
                st.subheader("II. Rekapitulace a Vyrovnání")
                rozdil = realne_zalohy - uznatelne_naklady

                r1, r2, r3 = st.columns(3)
                r1.metric("Uhrazené zálohy (Kredit)", f"{realne_zalohy:,.2f} Kč")
                r2.metric("Náklady na služby (Debet)", f"{uznatelne_naklady:,.2f} Kč")
                r3.metric("Výsledek", f"{rozdil:,.2f} Kč")

                st.markdown(f"""
                **Detail výpočtu záloh:**
                1. Celkem přijato na účet ({pocet_mesicu} plateb): **{celkem_prijato:,.2f} Kč**
                2. Odečet smluvního nájemného ({pocet_mesicu} x {v_najem}): **- {celkove_najemne:,.2f} Kč**
                3. Přičtení přeplatku z loňska: **+ {v_bonus:,.2f} Kč**
                4. **Skutečné zálohy plátce k zúčtování: {realne_zalohy:,.2f} Kč**
                """)

                if rozdil > 0:
                    st.success(f"### VÝSLEDEK: Přeplatek ve výši {rozdil:,.2f} Kč")
                elif rozdil < 0:
                    st.error(f"### VÝSLEDEK: Nedoplatek ve výši {abs(rozdil):,.2f} Kč")
                else:
                    st.info("### VÝSLEDEK: Vyrovnáno (0 Kč)")

            except Exception as e:
                st.error(f"Kritická chyba výpočtu: {e}")
