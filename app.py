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

DEFAULT_DATA = {
    "profil": {"poskytovatel": "", "platce": "", "adresa": "", "byt": "", "typ": ""},
    "osa_najmu": [
        {"od_mesice": 1, "do_mesice": 12, "najem": 0, "zaloha": 0}
    ],
    "lonsko": {"vysledek": 0, "typ": "Zadne"},
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
        raise Exception(f"Nevalidní JSON výstup.")
    except Exception as e:
        raise Exception(f"AI Chyba: {e}")

def cteni_pdf(file_obj):
    try:
        reader = PdfReader(file_obj)
        text = "".join(p.extract_text() + "\n" for p in reader.pages if p.extract_text())
        if not text.strip(): raise ValueError("Prázdný textový výstup z PDF.")
        return text
    except Exception as e:
        raise Exception(f"Chyba PDF parseru: {e}")

# ==========================================
# 3. UŽIVATELSKÉ ROZHRANÍ
# ==========================================
st.title("🏢 Komplexní správa vyúčtování služeb")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. Profil & Smlouvy", 
    "2. Loňské vyúčtování", 
    "3. Letošní náklady", 
    "4. Banka & Protokol",
    "💾 Data a Uložení"
])

# --- TAB 1: PROFIL A SMLOUVY ---
with tab1:
    st.subheader("Subjektové údaje a časová osa plnění")
    
    col_pdf1, col_pdf2 = st.columns(2)
    with col_pdf1:
        sml_1_pdf = st.file_uploader("Zdrojová smlouva (PDF)", type="pdf", key="sml1")
    with col_pdf2:
        sml_2_pdf = st.file_uploader("Dodatek / Smlouva 2 (PDF)", type="pdf", key="sml2")

    if st.button("Spustit sémantickou analýzu", type="primary", use_container_width=True):
        if not sml_1_pdf:
            st.warning("Vyžadován minimálně jeden zdrojový dokument.")
        else:
            with st.spinner("Provádění extrakce dat..."):
                try:
                    text_celkem = f"--- DOK 1 ---\n{cteni_pdf(sml_1_pdf)}\n"
                    if sml_2_pdf:
                        text_celkem += f"--- DOK 2 ---\n{cteni_pdf(sml_2_pdf)}\n"
                    
                    prompt = f"""
                    Analyzuj smlouvy o bydlení pro roční zúčtovací období (12 měsíců).
                    1. Subjekty: Podnájemní smlouva -> poskytovatel=Nájemce, platce=Podnájemce. Nájemní smlouva -> poskytovatel=Pronajímatel, platce=Nájemce.
                    2. Časová osa (osa_najmu): Detekuj změny výše plnění. Vytvoř intervaly pomocí od_mesice a do_mesice (v rozsahu 1-12).
                    - "najem" (čisté nájemné), "zaloha" (služby).
                    JSON výstup:
                    {{
                        "profil": {{"typ": "string", "poskytovatel": "string", "platce": "string", "adresa": "string", "byt": "string"}},
                        "osa_najmu": [{{"od_mesice": int, "do_mesice": int, "najem": int, "zaloha": int}}]
                    }}
                    Text:
                    {text_celkem}
                    """
                    vysledek_ai = ai_volani(prompt)
                    
                    if vysledek_ai and "osa_najmu" in vysledek_ai and len(vysledek_ai["osa_najmu"]) > 0:
                        st.session_state.db["profil"] = vysledek_ai["profil"]
                        st.session_state.db["osa_najmu"] = vysledek_ai["osa_najmu"]
                        st.success("Extrakce úspěšná.")
                    else:
                        st.warning("Data neextrahována. Nutný manuální vstup.")
                except Exception as e:
                    st.error(f"Chyba procesingu: {e}")

    st.markdown("#### Validace extrahovaných dat")
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.session_state.db["profil"]["poskytovatel"] = st.text_input("Poskytovatel", value=st.session_state.db["profil"].get("poskytovatel", ""))
    with c2: st.session_state.db["profil"]["platce"] = st.text_input("Plátce", value=st.session_state.db["profil"].get("platce", ""))
    with c3: st.session_state.db["profil"]["adresa"] = st.text_input("Adresa", value=st.session_state.db["profil"].get("adresa", ""))
    with c4: st.session_state.db["profil"]["byt"] = st.text_input("ID Bytu", value=st.session_state.db["profil"].get("byt", ""))

    st.markdown("#### Časová osa předepsaného plnění")
    nova_osa = []
    for idx, obdobi in enumerate(st.session_state.db["osa_najmu"]):
        o1, o2, o3, o4 = st.columns(4)
        with o1: od_m = st.number_input("Od měsíce", value=obdobi.get("od_mesice", 1), min_value=1, max_value=12, key=f"od_{idx}")
        with o2: do_m = st.number_input("Do měsíce", value=obdobi.get("do_mesice", 12), min_value=1, max_value=12, key=f"do_{idx}")
        with o3: njm = st.number_input("Smluvní nájem (CZK)", value=obdobi.get("najem", 0), step=100, key=f"njm_{idx}")
        with o4: zal = st.number_input("Předepsaná záloha (CZK)", value=obdobi.get("zaloha", 0), step=100, key=f"zal_{idx}")
        nova_osa.append({"od_mesice": od_m, "do_mesice": do_m, "najem": njm, "zaloha": zal})
    
    st.session_state.db["osa_najmu"] = nova_osa
    
    col_add, col_del = st.columns(2)
    with col_add:
        if st.button("Definovat nový interval plnění"):
            st.session_state.db["osa_najmu"].append({"od_mesice": 1, "do_mesice": 12, "najem": 0, "zaloha": 0})
            st.rerun()
    with col_del:
        if st.button("Odstranit poslední interval") and len(st.session_state.db["osa_najmu"]) > 1:
             st.session_state.db["osa_najmu"].pop()
             st.rerun()

# --- TAB 2: LOŇSKÉ VYÚČTOVÁNÍ ---
with tab2:
    st.subheader("Historická salda (Minulé období)")
    lonske_pdf = st.file_uploader("Zdrojový dokument (Vyúčtování N-1)", type="pdf", key="lon_pdf")
    
    if lonske_pdf and st.button("Extrahovat saldo N-1"):
        with st.spinner("Analýza zůstatků..."):
            try:
                txt = cteni_pdf(lonske_pdf)
                prompt = f"""Extrahuj celkové saldo plátce.
                Přeplatek (kladná hodnota), Nedoplatek (záporná hodnota).
                JSON: {{"vysledek": int, "typ": "Preplatek/Nedoplatek/Vyrovnano"}}
                Text: {txt}"""
                res = ai_volani(prompt)
                if res:
                    st.session_state.db["lonsko"] = res
                    st.success(f"Detekováno saldo: {res['typ']}, hodnota: {abs(res['vysledek'])} CZK")
            except Exception as e:
                st.error(f"Chyba extrakce: {e}")
    
    cl1, cl2 = st.columns(2)
    with cl1: st.session_state.db["lonsko"]["typ"] = st.selectbox("Klasifikace salda N-1", ["Preplatek", "Nedoplatek", "Zadne"], index=["Preplatek", "Nedoplatek", "Zadne"].index(st.session_state.db["lonsko"].get("typ", "Zadne")))
    with cl2: st.session_state.db["lonsko"]["vysledek"] = st.number_input("Absolutní hodnota salda (CZK)", value=abs(st.session_state.db["lonsko"].get("vysledek", 0)))

# --- TAB 3: LETOŠNÍ NÁKLADY ---
with tab3:
    st.subheader("Evidence skutečných nákladů (N)")
    
    st.markdown("#### Primární objektové náklady (SVJ)")
    letosni_svj = st.file_uploader("Vyúčtování vlastníka objektu (PDF)", type="pdf", key="let_svj")
    if letosni_svj and st.button("Spustit položkovou klasifikaci SVJ"):
        with st.spinner("Klasifikace položek (Přeúčtovatelné vs. Neuznatelné)..."):
            try:
                txt = cteni_pdf(letosni_svj)
                prompt = f"""Provést položkovou dekompozici nákladů. 
                'preuctovatelne'=true (voda, teplo, výtah, odpady, spol. el.). 'preuctovatelne'=false (FO, správa, pojištění).
                JSON: {{"polozky": [{{"nazev":"string", "castka":int, "preuctovatelne":bool}}]}}
                Text: {txt}"""
                res = ai_volani(prompt)
                if res and "polozky" in res:
                    st.session_state.db["naklady"]["svj"] = res["polozky"]
                    st.success(f"Zpracováno {len(st.session_state.db['naklady']['svj'])} položek.")
            except Exception as e:
                st.error(f"Chyba klasifikace: {e}")

    if st.session_state.db["naklady"]["svj"]:
        df_svj = pd.DataFrame(st.session_state.db["naklady"]["svj"])
        df_svj['Zodpovědnost'] = df_svj['preuctovatelne'].map({True: "Plátce", False: "Poskytovatel"})
        st.dataframe(df_svj[['nazev', 'castka', 'Zodpovědnost']], use_container_width=True, hide_index=True)

    st.markdown("#### Sekundární náklady (Externí dodavatelé)")
    col_dal1, col_dal2 = st.columns([3, 1])
    with col_dal1:
        dalsi_pdf = st.file_uploader("Fakturační doklad (PDF)", type="pdf", key="dal_pdf")
    with col_dal2:
        typ_sluzby = st.selectbox("Kategorie", ["Elektřina", "Plyn", "Internet", "Ostatní"])
    
    if dalsi_pdf and st.button(f"Zpracovat doklad: {typ_sluzby}"):
        with st.spinner("Extrakce nákladů za zúčtovací období..."):
            try:
                txt = cteni_pdf(dalsi_pdf)
                prompt = f"""Extrahuj sumární fakturované náklady za zúčtovací období (bez ohledu na zálohy).
                JSON: {{"castka": int}}
                Text: {txt}"""
                res = ai_volani(prompt)
                if res and res.get("castka", 0) > 0:
                    st.session_state.db["naklady"]["dalsi_sluzby"].append({"nazev": typ_sluzby, "castka": res["castka"], "preuctovatelne": True})
                    st.success(f"Položka přidána: {typ_sluzby} ({res['castka']} CZK)")
            except Exception as e:
                st.error(f"Chyba extrakce: {e}")

    if st.session_state.db["naklady"]["dalsi_sluzby"]:
        st.table(pd.DataFrame(st.session_state.db["naklady"]["dalsi_sluzby"]))
        if st.button("Reset sekundárních nákladů"):
            st.session_state.db["naklady"]["dalsi_sluzby"] = []
            st.rerun()

# --- TAB 4: BANKA & PROTOKOL ---
with tab4:
    st.subheader("Finanční syntéza a Generování výstupu")
    
    id_transakce = st.text_input("Transakční identifikátor filtru (např. příjmení plátce)", value=st.session_state.db["profil"].get("platce", ""))
    banka_xls = st.file_uploader("Transakční log (XLSX/CSV)", type=["xlsx", "csv"], key="banka_xls")
    
    if st.button("GENEROVAT PROTOKOL", type="primary", use_container_width=True):
        if not banka_xls or not id_transakce:
            st.error("Neúplné vstupy: Chybí transakční data nebo filtrační identifikátor.")
            st.stop()
            
        with st.spinner("Filtrace, agregace a výpočet..."):
            try:
                # 1. Agnostické načtení matice bez hlaviček
                if banka_xls.name.endswith('.csv'):
                    df = pd.read_csv(banka_xls, header=None, dtype=str)
                else:
                    df = pd.read_excel(banka_xls, header=None, dtype=str)
                
                # Globální filtrace záznamů dle identifikátoru napříč maticí
                mask = df.apply(lambda row: row.astype(str).str.contains(id_transakce, case=False, na=False).any(), axis=1)
                df_filtered = df[mask]
                
                if df_filtered.empty:
                    raise Exception(f"Identifikátor '{id_transakce}' nebyl detekován v datovém setu.")

                # Sanitace a extrakce numerických hodnot
                def parse_fin_value(val):
                    if pd.isna(val): return 0.0
                    v = str(val).replace('\xa0', '').replace(' ', '')
                    if v.endswith(',-'): v = v[:-2]
                    v = re.sub(r'[^\d,\.-]', '', v)
                    try: return float(v.replace(',', '.'))
                    except: return 0.0

                # Dynamická identifikace hodnotového sloupce
                col_sums = {}
                for col in df_filtered.columns:
                    col_sums[col] = df_filtered[col].apply(parse_fin_value).sum()
                
                target_col = max(col_sums, key=col_sums.get)
                suma_transakci = col_sums[target_col]
                pocet_transakci = len(df_filtered)
                
                # Výpočet smluvní pohledávky (Nájem)
                celkova_pohledavka_najem = 0
                for obdobi in st.session_state.db["osa_najmu"]:
                    pocet_mesicu = (obdobi["do_mesice"] - obdobi["od_mesice"]) + 1
                    celkova_pohledavka_najem += pocet_mesicu * obdobi["najem"]
                
                # Aplikace salda N-1
                saldo_n_minus_1 = st.session_state.db["lonsko"].get("vysledek", 0)
                if st.session_state.db["lonsko"]["typ"] == "Preplatek":
                    korekce_saldo = saldo_n_minus_1
                elif st.session_state.db["lonsko"]["typ"] == "Nedoplatek":
                    korekce_saldo = -abs(saldo_n_minus_1)
                else:
                    korekce_saldo = 0

                # Výpočet disponibilních záloh
                disponibilni_zalohy = suma_transakci - celkova_pohledavka_najem + korekce_saldo

                # 2. Agregace nákladů
                agregovane_naklady = st.session_state.db["naklady"]["svj"] + st.session_state.db["naklady"]["dalsi_sluzby"]
                uznatelne_naklady = sum(p['castka'] for p in agregovane_naklady if p.get('preuctovatelne', False))

                # --- PROTOKOL ---
                st.markdown("---")
                st.header("PROTOKOL O ZÚČTOVÁNÍ SLUŽEB")
                
                st.markdown(f"**Klasifikace vztahu:** {st.session_state.db['profil'].get('typ', 'Neuvedeno')}")
                st.markdown(f"**Identifikace objektu:** {st.session_state.db['profil'].get('adresa', '')}, Byt: {st.session_state.db['profil'].get('byt', '')}")
                st.markdown(f"**Poskytovatel:** {st.session_state.db['profil'].get('poskytovatel', '')} | **Plátce:** {st.session_state.db['profil'].get('platce', '')}")
                
                st.subheader("I. Uznatelné náklady (Zúčtovatelné položky)")
                if agregovane_naklady:
                    df_naklady_uznatelne = pd.DataFrame([p for p in agregovane_naklady if p.get('preuctovatelne')])
                    st.dataframe(df_naklady_uznatelne[['nazev', 'castka']], hide_index=True, use_container_width=True)

                st.subheader("II. Syntéza zúčtování")
                saldo_konecne = disponibilni_zalohy - uznatelne_naklady

                st.markdown(f"""
                **Výpočet disponibilních záloh:**
                * Úhrn transakcí po filtraci ({pocet_transakci} záznamů): **{suma_transakci:,.2f} CZK**
                * Srážka pohledávky (Nájem): **- {celkova_pohledavka_najem:,.2f} CZK**
                * Korekce salda (N-1): **{'+' if korekce_saldo >= 0 else ''} {korekce_saldo:,.2f} CZK**
                * **Disponibilní zálohy: {disponibilni_zalohy:,.2f} CZK**
                """)

                c1, c2, c3 = st.columns(3)
                c1.metric("Disponibilní zálohy", f"{disponibilni_zalohy:,.2f} CZK")
                c2.metric("Uznatelné náklady", f"{uznatelne_naklady:,.2f} CZK")
                c3.metric("Konečné saldo", f"{saldo_konecne:,.2f} CZK")

                if saldo_konecne > 0: st.success(f"VÝSLEDEK: Závazek vůči plátci (Přeplatek): {saldo_konecne:,.2f} CZK")
                elif saldo_konecne < 0: st.error(f"VÝSLEDEK: Pohledávka za plátcem (Nedoplatek): {abs(saldo_konecne):,.2f} CZK")
                else: st.info("VÝSLEDEK: Saldo nulové")

            except Exception as e:
                st.error(f"Kritická chyba procesingu: {e}")

# --- TAB 5: DATA A ZÁLOHY ---
with tab5:
    st.subheader("Export a Import stavu struktury")
    
    json_data = json.dumps(st.session_state.db, indent=4, ensure_ascii=False)
    id_platce = st.session_state.db["profil"].get("platce", "Neznamy").replace(" ", "_")
    
    st.download_button(
        label="Export objektu JSON",
        data=json_data,
        file_name=f"Vyuctovani_Export_{id_platce}.json",
        mime="application/json",
        type="primary"
    )
    
    st.divider()
    zaloha_file = st.file_uploader("Import objektu JSON", type="json")
    if zaloha_file and st.button("Načíst strukturu"):
        try:
            st.session_state.db = json.load(zaloha_file)
            st.success("Struktura nahrána do paměti.")
        except Exception as e:
            st.error(f"Chyba IO operace: {e}")
