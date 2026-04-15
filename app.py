import streamlit as st
import pandas as pd
from pypdf import PdfReader
import google.generativeai as genai
import json
import re

# ==========================================
# 1. KONFIGURACE A STAV APLIKACE
# ==========================================
st.set_page_config(page_title="Vyúčtování PRO", layout="wide", page_icon="🏢")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("Chybí GEMINI_API_KEY v Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Výchozí datová struktura pro jednoho nájemníka/rok
DEFAULT_DATA = {
    "profil": {"poskytovatel": "", "platce": "", "adresa": "", "byt": "", "typ": ""},
    "smlouva": {"najem_1": 0, "mesicu_1": 12, "najem_2": 0, "mesicu_2": 0},
    "lonsko": {"vysledek": 0, "typ": "Zadne"}, # Kladné = přeplatek nájemníka, Záporné = nedoplatek
    "naklady": {"svj": [], "dalsi_sluzby": []}
}

if "db" not in st.session_state:
    st.session_state.db = json.loads(json.dumps(DEFAULT_DATA))

# ==========================================
# 2. JÁDRO AI A ZPRACOVÁNÍ SOUBORŮ
# ==========================================
@st.cache_resource
def zjisti_model():
    try:
        modely = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for pref in ['models/gemini-1.5-flash', 'models/gemini-2.0-flash-exp', 'models/gemini-pro']:
            if pref in modely: return pref
        return modely[0] if modely else None
    except: return None

def ai_volani(prompt):
    model_name = zjisti_model()
    if not model_name: raise Exception("Nedostupné AI modely.")
    try:
        model = genai.GenerativeModel(model_name)
        res = model.generate_content(prompt)
        match = re.search(r'\{.*\}', res.text, re.DOTALL)
        if match: return json.loads(match.group())
        raise Exception("AI nevrátila JSON.")
    except Exception as e:
        raise Exception(f"AI Chyba: {e}")

def cteni_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = "".join(p.extract_text() + "\n" for p in reader.pages if p.extract_text())
        if not text.strip(): raise ValueError("PDF bez textu.")
        return text
    except Exception as e:
        raise Exception(f"Chyba PDF: {e}")

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ (Taby pro lepší orientaci)
# ==========================================
st.title("🏢 Komplexní správa vyúčtování služeb")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. Profil & Smlouvy", 
    "2. Loňské vyúčtování", 
    "3. Letošní náklady", 
    "4. Banka & Protokol",
    "💾 Uložit / Načíst"
])

# --- TAB 1: PROFIL A SMLOUVY ---
with tab1:
    st.subheader("Informace o vztahu a změnách nájemného")
    
    col_pdf, col_btn = st.columns([3, 1])
    with col_pdf:
        sml_pdf = st.file_uploader("Analyzovat aktuální/minulou smlouvu (PDF)", type="pdf", key="sml_pdf")
    with col_btn:
        st.write("")
        if sml_pdf and st.button("Extrahovat data"):
            with st.spinner("Analyzuji..."):
                txt = cteni_pdf(sml_pdf)
                prompt = f"""Vytáhni data. Podnájem = Poskytovatel je Nájemce. Nájem = Poskytovatel je Pronajímatel.
                JSON: {{"typ":"Nájem/Podnájem", "posk":"Jméno", "plat":"Jméno", "adr":"Adresa", "byt":"číslo", "najem": 0}}
                Text: {txt}"""
                res = ai_volani(prompt)
                if res:
                    st.session_state.db["profil"]["typ"] = res.get("typ", "")
                    st.session_state.db["profil"]["poskytovatel"] = res.get("posk", "")
                    st.session_state.db["profil"]["platce"] = res.get("plat", "")
                    st.session_state.db["profil"]["adresa"] = res.get("adr", "")
                    st.session_state.db["profil"]["byt"] = res.get("byt", "")
                    st.session_state.db["smlouva"]["najem_1"] = int(res.get("najem", 0))
                    st.success("Načteno.")

    st.markdown("#### Ruční korekce a změny v průběhu roku")
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.session_state.db["profil"]["poskytovatel"] = st.text_input("Poskytovatel", value=st.session_state.db["profil"]["poskytovatel"])
    with c2: st.session_state.db["profil"]["platce"] = st.text_input("Plátce", value=st.session_state.db["profil"]["platce"])
    with c3: st.session_state.db["profil"]["adresa"] = st.text_input("Adresa", value=st.session_state.db["profil"]["adresa"])
    with c4: st.session_state.db["profil"]["byt"] = st.text_input("Byt č.", value=st.session_state.db["profil"]["byt"])

    st.markdown("**Časová osa nájemného (pokud se během roku měnilo):**")
    cn1, cn2, cn3, cn4 = st.columns(4)
    with cn1: st.session_state.db["smlouva"]["najem_1"] = st.number_input("Nájemné - Období 1 (Kč)", value=st.session_state.db["smlouva"]["najem_1"])
    with cn2: st.session_state.db["smlouva"]["mesicu_1"] = st.number_input("Počet měsíců (Období 1)", value=st.session_state.db["smlouva"]["mesicu_1"], min_value=0, max_value=12)
    with cn3: st.session_state.db["smlouva"]["najem_2"] = st.number_input("Nájemné - Období 2 (Kč)", value=st.session_state.db["smlouva"]["najem_2"])
    with cn4: st.session_state.db["smlouva"]["mesicu_2"] = st.number_input("Počet měsíců (Období 2)", value=st.session_state.db["smlouva"]["mesicu_2"], min_value=0, max_value=12)

# --- TAB 2: LOŇSKÉ VYÚČTOVÁNÍ (Pro kompenzace) ---
with tab2:
    st.subheader("Historie z minulého roku")
    st.info("Pokud plátce letos poslal méně/více peněz kvůli vypořádání loňského roku, nahrajte loňské vyúčtování.")
    lonske_pdf = st.file_uploader("Nahrát loňské vyúčtování (PDF)", type="pdf", key="lon_pdf")
    if lonske_pdf and st.button("Zjistit loňský zůstatek"):
        with st.spinner("Hledám konečný zůstatek..."):
            txt = cteni_pdf(lonske_pdf)
            prompt = f"""Přečti vyúčtování a najdi konečný výsledek pro uživatele bytu.
            Pokud mu vrací peníze, je to 'Preplatek' a kladná částka. Pokud doplácí on, je to 'Nedoplatek' a záporná částka.
            JSON: {{"vysledek": 0, "typ": "Preplatek/Nedoplatek/Vyrovnano"}}
            Text: {txt}"""
            res = ai_volani(prompt)
            if res:
                st.session_state.db["lonsko"] = res
                st.success(f"Zjištěno: {res['typ']} ve výši {abs(res['vysledek'])} Kč.")
    
    st.markdown("**Ruční nastavení loňského zůstatku:**")
    cl1, cl2 = st.columns(2)
    with cl1: st.session_state.db["lonsko"]["typ"] = st.selectbox("Stav z loňska", ["Preplatek", "Nedoplatek", "Zadne"], index=["Preplatek", "Nedoplatek", "Zadne"].index(st.session_state.db["lonsko"].get("typ", "Zadne")))
    with cl2: st.session_state.db["lonsko"]["vysledek"] = st.number_input("Částka z loňska (Kč)", value=abs(st.session_state.db["lonsko"]["vysledek"]))

# --- TAB 3: LETOŠNÍ NÁKLADY (SVJ + Elektřina/Plyn) ---
with tab3:
    st.subheader("Zpracování letošních nákladů")
    
    # SVJ
    st.markdown("#### Hlavní vyúčtování budovy (SVJ)")
    letosni_svj = st.file_uploader("Nahrát letošní SVJ (PDF)", type="pdf", key="let_svj")
    if letosni_svj and st.button("Auditovat položky SVJ"):
        with st.spinner("Audituji SVJ..."):
            txt = cteni_pdf(letosni_svj)
            prompt = f"""Vypiš všechny položky SVJ. 'preuctovatelne'=true pro vodu, teplo, odpad, výtah atd. 'preuctovatelne'=false pro fond oprav, pojištění, správu.
            JSON: {{"polozky": [{{"nazev":"..", "castka":0, "preuctovatelne":true}}]}}
            Text: {txt}"""
            res = ai_volani(prompt)
            if res:
                st.session_state.db["naklady"]["svj"] = res.get("polozky", [])
                st.success(f"Načteno {len(st.session_state.db['naklady']['svj'])} položek.")

    if st.session_state.db["naklady"]["svj"]:
        df_svj = pd.DataFrame(st.session_state.db["naklady"]["svj"])
        st.dataframe(df_svj, use_container_width=True)

    # DALŠÍ SLUŽBY
    st.markdown("#### Dodatečné služby (Elektřina, Plyn, Internet)")
    dalsi_pdf = st.file_uploader("Nahrát fakturu za další službu (PDF)", type="pdf", key="dal_pdf")
    typ_sluzby = st.selectbox("Druh služby", ["Elektřina", "Plyn", "Internet", "Jiné"])
    
    if dalsi_pdf and st.button("Přidat externí fakturu"):
        with st.spinner("Čtu fakturu..."):
            txt = cteni_pdf(dalsi_pdf)
            prompt = f"""Najdi celkovou fakturovanou částku za dané zúčtovací období (nikoliv jen nedoplatek/přeplatek, ale celkovou cenu spotřeby).
            JSON: {{"castka": 0}}
            Text: {txt}"""
            res = ai_volani(prompt)
            if res and res["castka"] > 0:
                st.session_state.db["naklady"]["dalsi_sluzby"].append({"nazev": typ_sluzby, "castka": res["castka"], "preuctovatelne": True})
                st.success(f"Přidáno: {typ_sluzby} - {res['castka']} Kč")

    if st.session_state.db["naklady"]["dalsi_sluzby"]:
        st.table(pd.DataFrame(st.session_state.db["naklady"]["dalsi_sluzby"]))
        if st.button("Vymazat dodatečné služby"):
            st.session_state.db["naklady"]["dalsi_sluzby"] = []
            st.rerun()

# --- TAB 4: BANKA A PROTOKOL ---
with tab4:
    st.subheader("Finanční výkaz a Protokol")
    banka_xls = st.file_uploader("Nahrát výpis od plátce (Excel/CSV)", type=["xlsx", "csv"], key="banka_xls")
    
    if st.button("🚀 GENEROVAT FINÁLNÍ PROTOKOL", type="primary", use_container_width=True):
        if not banka_xls:
            st.error("Chybí výpis z banky.")
        else:
            try:
                # 1. Matematika příjmů
                df = pd.read_csv(banka_xls) if banka_xls.name.endswith('.csv') else pd.read_excel(banka_xls)
                castka_col = next((c for c in df.columns if 'castka' in c.lower() or 'částka' in c.lower()), None)
                if not castka_col: raise Exception("V Excelu chybí sloupec 'Castka'.")
                
                celkem_prijato = df[castka_col].sum()
                smluvni_najem = (st.session_state.db["smlouva"]["najem_1"] * st.session_state.db["smlouva"]["mesicu_1"]) + (st.session_state.db["smlouva"]["najem_2"] * st.session_state.db["smlouva"]["mesicu_2"])
                
                # Korekce dle loňska: Pokud loni Přeplatek, bereme jako že letos zaplatil o to víc (protože poslal fyzicky méně)
                korekce_lonsko = st.session_state.db["lonsko"]["vysledek"] if st.session_state.db["lonsko"]["typ"] == "Preplatek" else -abs(st.session_state.db["lonsko"]["vysledek"])
                
                uhrazene_zalohy = celkem_prijato - smluvni_najem + korekce_lonsko

                # 2. Matematika výdajů
                vsechny_naklady = st.session_state.db["naklady"]["svj"] + st.session_state.db["naklady"]["dalsi_sluzby"]
                naklady_platce = sum(p['castka'] for p in vsechny_naklady if p.get('preuctovatelne', False))

                # --- VYKRESLENÍ REPORTU ---
                st.markdown("---")
                st.header("📄 PROTOKOL O VYÚČTOVÁNÍ SLUŽEB A ENERGIÍ")
                
                st.write(f"**Vztah:** {st.session_state.db['profil']['typ']} | **Objekt:** {st.session_state.db['profil']['adresa']}, Byt: {st.session_state.db['profil']['byt']}")
                st.write(f"**Poskytovatel:** {st.session_state.db['profil']['poskytovatel']} | **Plátce:** {st.session_state.db['profil']['platce']}")
                
                st.subheader("I. Přehled uznatelných nákladů (Debet)")
                if vsechny_naklady:
                    df_naklady = pd.DataFrame([p for p in vsechny_naklady if p.get('preuctovatelne')])
                    st.table(df_naklady[['nazev', 'castka']])
                
                st.subheader("II. Účetní závěrka")
                rozdil = uhrazene_zalohy - naklady_platce

                st.markdown(f"""
                **Výpočet čistých uhrazených záloh (Kredit):**
                1. Fyzicky obdrženo na účet: **{celkem_prijato:,.2f} Kč**
                2. Smluvní nájemné ({st.session_state.db['smlouva']['mesicu_1']}+{st.session_state.db['smlouva']['mesicu_2']} měsíců): **- {smluvni_najem:,.2f} Kč**
                3. Korekce z minulého období ({st.session_state.db['lonsko']['typ']}): **{'+' if korekce_lonsko >= 0 else ''} {korekce_lonsko:,.2f} Kč**
                = **Zálohy na služby k zúčtování: {uhrazene_zalohy:,.2f} Kč**
                """)

                c1, c2, c3 = st.columns(3)
                c1.metric("Zálohy k zúčtování", f"{uhrazene_zalohy:,.2f} Kč")
                c2.metric("Náklady celkem", f"{naklady_platce:,.2f} Kč")
                c3.metric("Výsledek", f"{rozdil:,.2f} Kč")

                if rozdil > 0: st.success(f"### VÝSLEDEK: Přeplatek {rozdil:,.2f} Kč")
                elif rozdil < 0: st.error(f"### VÝSLEDEK: Nedoplatek {abs(rozdil):,.2f} Kč")
                else: st.info("### VÝSLEDEK: Vyrovnáno")

            except Exception as e:
                st.error(f"Chyba reportu: {e}")

# --- TAB 5: DATABÁZE A ULOŽENÍ ---
with tab5:
    st.subheader("Správa databází a archivace")
    st.markdown("Pro vytvoření profilu nájemníka si stáhněte tento soubor. Příští rok ho jen nahrajete a vše se obnoví.")
    
    # Export
    json_data = json.dumps(st.session_state.db, indent=4, ensure_ascii=False)
    st.download_button(
        label="📥 Stáhnout profil nájemníka (Záloha.json)",
        data=json_data,
        file_name=f"Vyuctovani_{st.session_state.db['profil']['platce']}.json",
        mime="application/json"
    )
    
    st.divider()
    # Import
    zaloha_file = st.file_uploader("📤 Nahrát existující profil (Záloha.json)", type="json")
    if zaloha_file and st.button("Obnovit data ze zálohy"):
        try:
            nactena_data = json.load(zaloha_file)
            st.session_state.db = nactena_data
            st.success("Data úspěšně obnovena! Můžete přejít na další záložky.")
        except Exception as e:
            st.error(f"Chyba formátu: {e}")
