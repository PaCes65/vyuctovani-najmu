import streamlit as st
import pandas as pd
from pypdf import PdfReader
import google.generativeai as genai
import json

# ==========================================
# 1. ARCHITEKTURA A KONFIGURACE
# ==========================================
st.set_page_config(page_title="Vyúčtování PRO", layout="wide", page_icon="🏢")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("Kritická chyba: Chybí GEMINI_API_KEY v nastavení Streamlit Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Inicializace stavu aplikace (State Management)
if "ai_data" not in st.session_state:
    st.session_state.ai_data = {
        "typ_smlouvy": "", "poskytovatel": "", "platce": "", 
        "adresa": "", "byt": "", "mesicni_najem": 0, "mesicni_zaloha": 0
    }

# ==========================================
# 2. CORE FUNKCE (Business Logic & AI)
# ==========================================
def cteni_pdf(file_obj):
    """Robustní čtení PDF s ošetřením chyb."""
    try:
        reader = PdfReader(file_obj)
        text = "".join(page.extract_text() + "\n" for page in reader.pages if page.extract_text())
        if not text.strip():
            raise ValueError("PDF neobsahuje textovou vrstvu (pravděpodobně sken).")
        return text
    except Exception as e:
        st.error(f"Chyba při čtení PDF: {str(e)}")
        return None

def ai_parser(prompt, schema_description):
    """Univerzální AI parser vynucující validní JSON výstup."""
    try:
        # Použití stabilního modelu s vynuceným JSON výstupem na úrovni API
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Selhání AI integrace: {str(e)}")
        return None

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ (Frontend)
# ==========================================
st.title("🏢 Profesionální vyúčtování služeb")

# --- KROK 1: SMLOUVA ---
with st.container(border=True):
    st.subheader("1. Právní rámec (Smlouva)")
    pdf_smlouva = st.file_uploader("Nahrát smlouvu (PDF)", type="pdf", key="sml")
    
    if pdf_smlouva and st.button("Analyzovat smlouvu", type="primary"):
        with st.spinner("Provádím sémantickou analýzu textu..."):
            text_smlouvy = cteni_pdf(pdf_smlouva)
            if text_smlouvy:
                prompt = f"""
                Extrahuj data ze smlouvy. 
                Pravidla: Podnájemní smlouva -> poskytovatel=Nájemce, platce=Podnájemce. 
                Nájemní smlouva -> poskytovatel=Pronajímatel, platce=Nájemce.
                Vrať JSON přesně v této struktuře:
                {{
                    "typ_smlouvy": "string", "poskytovatel": "string", "platce": "string",
                    "adresa": "string", "byt": "string", "mesicni_najem": number, "mesicni_zaloha": number
                }}
                Text: {text_smlouvy}
                """
                data = ai_parser(prompt, "Smlouva")
                if data:
                    st.session_state.ai_data.update(data)
                    st.success("Analýza úspěšná.")
                with st.expander("Vývojářský log: Surový text z PDF"):
                    st.text(text_smlouvy[:1000] + "...")

# --- KROK 2: KOREKCE DAT ---
with st.container(border=True):
    st.subheader("2. Parametry vyúčtování")
    c1, c2, c3 = st.columns(3)
    with c1:
        v_posk = st.text_input("Poskytovatel (příjemce plateb)", value=st.session_state.ai_data.get("poskytovatel", ""))
        v_adr = st.text_input("Adresa", value=st.session_state.ai_data.get("adresa", ""))
    with c2:
        v_plat = st.text_input("Plátce (uživatel bytu)", value=st.session_state.ai_data.get("platce", ""))
        v_byt = st.text_input("Číslo bytu", value=st.session_state.ai_data.get("byt", ""))
    with c3:
        v_najem = st.number_input("Měsíční nájemné ze smlouvy (Kč)", value=int(st.session_state.ai_data.get("mesicni_najem", 0)), step=100)
        v_bonus = st.number_input("Kompenzace / Loňský přeplatek (Kč)", value=0, help="Zadejte přeplatek z loňska, o který si plátce ponížil letošní platby.")

# --- KROK 3: AUDIT & VÝPOČET ---
with st.container(border=True):
    st.subheader("3. Finanční data a vygenerování auditu")
    col_pdf, col_xls = st.columns(2)
    with col_pdf:
        pdf_svj = st.file_uploader("Vyúčtování budovy od SVJ (PDF)", type="pdf", key="svj")
    with col_xls:
        xls_banka = st.file_uploader("Výpis plateb plátce (Excel/CSV)", type=["xlsx", "csv"], key="banka")

    if st.button("Spustit audit a výpočet", type="primary", use_container_width=True):
        if not pdf_svj or not xls_banka:
            st.warning("Systém vyžaduje obě přílohy pro zpracování (SVJ i Banku).")
            st.stop()

        with st.spinner("Probíhá zpracování a validace dat..."):
            # A. Zpracování banky
            try:
                df = pd.read_csv(xls_banka) if xls_banka.name.endswith('.csv') else pd.read_excel(xls_banka)
                # Hledání sloupce s částkou nezávisle na velikosti písmen
                castka_col = next((col for col in df.columns if 'castka' in col.lower() or 'částka' in col.lower()), None)
                if not castka_col:
                    st.error(f"V Excelu chybí sloupec 'Castka'. Nalezené sloupce: {list(df.columns)}")
                    st.stop()
                
                celkem_prijato = df[castka_col].sum()
                pocet_plateb = len(df)
                celkovy_predpis_najmu = v_najem * pocet_plateb
                # Čisté zálohy = (Vše co poslal - Nájemné) + Loňský přeplatek, který neposlal, ale má na něj kredit
                realne_zalohy = celkem_prijato - celkovy_predpis_najmu + v_bonus
            except Exception as e:
                st.error(f"Kritická chyba při čtení finančního výpisu: {str(e)}")
                st.stop()

            # B. Audit SVJ
            text_svj = cteni_pdf(pdf_svj)
            if not text_svj:
                st.stop()

            prompt_svj = f"""
            Vypiš všechny finanční položky z vyúčtování SVJ. 
            'preuctovatelne' je boolean (true = platí uživatel bytu např. teplo, voda, výtah, odpad; false = platí majitel např. fond oprav, odměny, správa).
            Vrať JSON:
            {{
                "polozky": [
                    {{"nazev": "string", "castka": number, "preuctovatelne": boolean, "duvod": "string"}}
                ]
            }}
            Text vyúčtování: {text_svj}
            """
            audit_data = ai_parser(prompt_svj, "Vyúčtování SVJ")
            
            if not audit_data or "polozky" not in audit_data:
                st.error("AI parser nedokázal sestavit validní strukturu nákladů.")
                with st.expander("Zobrazit text přečtený z PDF"): st.text(text_svj)
                st.stop()

            polozky = audit_data["polozky"]
            uznatelne_naklady = sum(p['castka'] for p in polozky if p['preuctovatelne'])
            naklady_vlastnika = sum(p['castka'] for p in polozky if not p['preuctovatelne'])

            # ==========================================
            # REPORTING
            # ==========================================
            st.markdown("---")
            st.header("📄 PROTOKOL O ROČNÍM VYÚČTOVÁNÍ SLUŽEB")
            
            # Hlavička
            st.markdown(f"**Identifikace vztahu:** {st.session_state.ai_data.get('typ_smlouvy', 'Neuvedeno')}")
            st.markdown(f"**Předmět nájmu:** {v_adr}, byt č. {v_byt}")
            st.markdown(f"**Poskytovatel:** {v_posk} | **Plátce:** {v_plat}")
            
            # Tabulka auditu
            st.subheader("I. Audit nákladů budovy (SVJ)")
            df_audit = pd.DataFrame(polozky)
            if not df_audit.empty:
                df_audit['Zodpovědnost'] = df_audit['preuctovatelne'].map({True: "🟢 Plátce (Nájemník)", False: "🔴 Vlastník (Majitel)"})
                # Reorganizace sloupců
                st.dataframe(
                    df_audit[['nazev', 'castka', 'Zodpovědnost', 'duvod']], 
                    use_container_width=True, 
                    hide_index=True
                )
            
            # Matematika
            st.subheader("II. Rekapitulace a finanční vyrovnání")
            
            res1, res2, res3 = st.columns(3)
            res1.metric("Kredit plátce na zálohách", f"{realne_zalohy:,.2f} Kč")
            res2.metric("Přeúčtované náklady SVJ", f"{uznatelne_naklady:,.2f} Kč")
            rozdil = realne_zalohy - uznatelne_naklady
            res3.metric("Výsledek vyúčtování", f"{rozdil:,.2f} Kč")

            with st.expander("🔍 Zobrazit detailní matematický postup", expanded=True):
                st.code(f"""
                PŘÍJMY (KREDIT PLÁTCE):
                + Součet všech došlých plateb na účet:   {celkem_prijato:10.2f} Kč (Celkem {pocet_plateb} plateb)
                - Odečet smluvního nájemného za období: -{celkovy_predpis_najmu:10.2f} Kč ({pocet_plateb} x {v_najem})
                + Započtený bonus/kredit z minulosti:   +{v_bonus:10.2f} Kč
                --------------------------------------------------------
                = ČISTÉ ZÁLOHY NA SLUŽBY:                 {realne_zalohy:10.2f} Kč
                
                NÁKLADY (DEBET PLÁTCE):
                - Uznatelné náklady ze sekce I.:        -{uznatelne_naklady:10.2f} Kč
                --------------------------------------------------------
                = FINÁLNÍ ZŮSTATEK:                       {rozdil:10.2f} Kč
                """, language="text")

            if rozdil > 0:
                st.success(f"### VÝSLEDEK: Přeplatek ve výši {rozdil:,.2f} Kč")
                st.write("Částka bude plátci vrácena na účet, nebo započtena do plateb dalšího období.")
            elif rozdil < 0:
                st.error(f"### VÝSLEDEK: Nedoplatek ve výši {abs(rozdil):,.2f} Kč")
                st.write("Plátce je povinen částku uhradit poskytovateli v zákonné lhůtě.")
            else:
                st.info("### VÝSLEDEK: Vyrovnáno (0 Kč)")
