import streamlit as st
import pandas as pd
from pypdf import PdfReader
import google.generativeai as genai
import json
import re
from datetime import datetime
from typing import Dict, List, Optional
import plotly.graph_objects as go

# ==========================================
# KONFIGURACE A INICIALIZACE
# ==========================================
st.set_page_config(page_title="Vyúčtování PRO - Multi", layout="wide", page_icon="🏢")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("Kritická chyba: Chybí GEMINI_API_KEY v nastavení Streamlit Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# ==========================================
# DATOVÝ MODEL - Multi-tenancy
# ==========================================
def init_session_state():
    """Inicializace struktury pro více nájmů a let"""
    if "databaze" not in st.session_state:
        st.session_state.databaze = {
            "najmy": {},  # {id_najmu: {adresa, byt, historie: {rok: data}}}
            "aktivni_najem": None,
            "aktivni_rok": datetime.now().year
        }

    if "sluzby_config" not in st.session_state:
        st.session_state.sluzby_config = {
            "svj": {"nazev": "SVJ (Společenství vlastníků)", "aktivni": True, "povinne": True},
            "elektrina": {"nazev": "Elektřina", "aktivni": False, "povinne": False},
            "plyn": {"nazev": "Plyn", "aktivni": False, "povinne": False},
            "internet": {"nazev": "Internet", "aktivni": False, "povinne": False},
            "tv": {"nazev": "Kabelová TV", "aktivni": False, "povinne": False},
            "voda": {"nazev": "Vodné stočné", "aktivni": False, "povinne": False},
            "uklid": {"nazev": "Úklid bytu", "aktivni": False, "povinne": False}
        }

def get_default_vyuctovani():
    """Výchozí struktura ročního vyúčtování"""
    return {
        "zakladni_udaje": {
            "poskytovatel": "", "platce": "", "adresa": "", "byt": "",
            "mesicni_najem": 0.0, "mesicni_zaloha": 0.0
        },
        "minula_smlouva": {
            "soubor": None, "data": {}, "zmeny": []
        },
        "minule_vyuctovani": {
            "soubor": None, "preplatek": 0.0, "komentar": ""
        },
        "slozky": {},  # {typ: {zalohy_sum, naklady_sum, polozky: []}}
        "platby_priebeh": [],  # změny plateb v průběhu roku
        "vysledek": {"rozdil": 0, "stav": "nevyhodnoceno"}
    }

# ==========================================
# AI FUNKCE
# ==========================================
@st.cache_resource
def zjisti_nejlepsi_model():
    try:
        dostupne = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        preference = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-2.0-flash-exp']
        for pref in preference:
            if pref in dostupne: return pref
        return next((m for m in dostupne if 'gemini' in m), dostupne[0] if dostupne else None)
    except Exception as e:
        st.error(f"Chyba API: {e}")
        return None

def ai_chat(prompt, json_mode=True):
    """Univerzální AI volání s ošetřením chyb"""
    model_name = zjisti_nejlepsi_model()
    if not model_name: raise Exception("AI model není dostupný")

    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        text = response.text

        if json_mode:
            # Extrakce JSON z markdown nebo čistého textu
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            match = re.search(r\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            else:
                raise Exception("AI nevrátila validní JSON")
        return text
    except Exception as e:
        raise Exception(f"AI chyba: {str(e)}")

def porovnej_smlouvy(stara_text, nova_text):
    """AI analýza změn mezi smlouvami"""
    prompt = f"""
    Porovnej starou a novou nájemní smlouvu. Identifikuj:
    1. Změny výše nájmu (stará vs nová částka)
    2. Změny záloh na služby
    3. Nové nebo zrušené služby
    4. Změny v platebních podmínkách

    Stará smlouva: {stara_text[:3000]}
    Nová smlouva: {nova_text[:3000]}

    Vrať JSON:
    {{
        "zmeny_najmu": {{"mesicni_zmena": 0, "rocni_dopad": 0}},
        "zmeny_zaloh": [{{"sluzba": "...", "stara": 0, "nova": 0, "rozdil": 0}}],
        "nove_sluzby": ["..."],
        "zrusene_sluzby": ["..."],
        "komentar": "..."
    }}
    """
    return ai_chat(prompt)

def analyza_vyuctovani_svj(text_pdf, vybrane_sluzby):
    """Rozšířená analýza SVJ s filtrováním služeb"""
    sluzby_filter = ", ".join([k for k, v in vybrane_sluzby.items() if v["aktivni"] or v["povinne"]])

    prompt = f"""
    Analyzuj vyúčtování SVJ. Vrať pouze položky týkající se: {sluzby_filter}.

    Pro každou položku urči:
    - "preuctovatelne": true/false (zda to jde na nájemníka)
    - "kategorie": jedna z [{sluzby_filter}]
    - "castka": číselná hodnota

    Vrať JSON:
    {{
        "polozky": [
            {{"nazev": "...", "castka": 0, "preuctovatelne": true, "kategorie": "...", "poznamka": "..."}}
        ],
        "celkem": 0
    }}

    Text: {text_pdf[:4000]}
    """
    return ai_chat(prompt)

def detekce_zmen_plateb(text_smlouvy, text_minule_vyuctovani, bankovni_pohyby):
    """AI analýza proč bylo placeno jinak než dle smlouvy"""
    prompt = f"""
    Jsi analytik nájemních vztahů. 

    Na základě:
    1. Smlouvy (platná výše záloh): {text_smlouvy[:2000]}
    2. Minulého vyúčtování (přeplatek/nedoplatek): {text_minule_vyuctovani[:2000] if text_minule_vyuctovani else "Není k dispozici"}
    3. Bankovních pohybů: {bankovni_pohyby}

    Vysvětli:
    - Proč nájemník posílal jiné částky než je ve smlouvě?
    - Jde o vracení přeplatku z minulého roku?
    - Byly nějaké mimořádné platby (např. doplatek minulého roku)?
    - Jaké jsou dopady na aktuální vyúčtování?

    Vrať JSON:
    {{
        "vysvetleni": "...",
        "odchylky": [{{"mesic": "...", "ocekavano": 0, "skutecnost": 0, "duvod": "..."}}],
        "dopad_na_vyuctovani": "...",
        "doporuceni": "..."
    }}
    """
    return ai_chat(prompt)

# ==========================================
# UI KOMPONENTY
# ==========================================
def render_sprava_najmu():
    """Sidebar pro správu více nájmů"""
    with st.sidebar:
        st.header("🏠 Správa nájmů")

        # Výběr nebo vytvoření nájmu
        najmy_list = [("Nový nájem...", None)] + [
            (f"{data['adresa']} - {data['byt']}", id_n) 
            for id_n, data in st.session_state.databaze["najmy"].items()
        ]

        vybrany = st.selectbox(
            "Vyberte nájem:", 
            options=[x[1] for x in najmy_list],
            format_func=lambda x: next(n[0] for n in najmy_list if n[1] == x)
        )

        if vybrany is None:
            # Formulář nový nájem
            with st.form("novy_najem"):
                st.subheader("Nový nájem")
                adr = st.text_input("Adresa nemovitosti")
                byt = st.text_input("Číslo bytu/označení")
                rok = st.number_input("Rok vyúčtování", min_value=2020, max_value=2030, value=datetime.now().year)

                if st.form_submit_button("Vytvořit"):
                    id_n = f"{adr}_{byt}_{rok}".replace(" ", "_")
                    st.session_state.databaze["najmy"][id_n] = {
                        "adresa": adr, "byt": byt, "vyuctovani": {}
                    }
                    st.session_state.databaze["najmy"][id_n]["vyuctovani"][str(int(rok))] = get_default_vyuctovani()
                    st.session_state.databaze["aktivni_najem"] = id_n
                    st.session_state.databaze["aktivni_rok"] = int(rok)
                    st.rerun()
        else:
            st.session_state.databaze["aktivni_najem"] = vybrany
            akt = st.session_state.databaze["najmy"][vybrany]

            # Výběr roku
            dostupne_roky = list(akt["vyuctovani"].keys())
            novy_rok = st.selectbox("Rok vyúčtování:", dostupne_roky + ["+ Nový rok"])

            if novy_rok == "+ Nový rok":
                r = st.number_input("Zadejte rok:", 2020, 2030, datetime.now().year)
                if st.button("Přidat rok"):
                    akt["vyuctovani"][str(int(r))] = get_default_vyuctovani()
                    st.session_state.databaze["aktivni_rok"] = int(r)
                    st.rerun()
            else:
                st.session_state.databaze["aktivni_rok"] = int(novy_rok)

        # Export/Import
        st.divider()
        if st.button("📥 Exportovat vše (JSON)"):
            st.download_button(
                "Stáhnout databázi",
                data=json.dumps(st.session_state.databaze, ensure_ascii=False, indent=2),
                file_name=f"najmy_export_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )

        nahrany = st.file_uploader("📤 Importovat databázi", type="json")
        if nahrany:
            if st.button("Načíst data"):
                st.session_state.databaze = json.load(nahrany)
                st.rerun()

def render_konfigurace_sluzby():
    """Nastavení aktivních služeb pro aktuální vyúčtování"""
    st.subheader("⚙️ Konfigurace služeb")

    cols = st.columns(4)
    sluzby = st.session_state.sluzby_config

    for idx, (key, config) in enumerate(sluzby.items()):
        with cols[idx % 4]:
            if config["povinne"]:
                st.checkbox(config["nazev"], value=True, disabled=True, key=f"sl_{key}")
            else:
                sluzby[key]["aktivni"] = st.checkbox(
                    config["nazev"], 
                    value=config["aktivni"],
                    key=f"sl_{key}"
                )

def render_srovnani_smluv():
    """Sekce pro nahrání a srovnání staré a nové smlouvy"""
    st.subheader("🔄 Srovnání s minulou smlouvou")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Minulá smlouva (předchozí období)**")
        pdf_stara = st.file_uploader("Nahrát starou smlouvu", type="pdf", key="stara_sml")

    with col2:
        st.markdown("**Aktuální smlouva**")
        pdf_nova = st.file_uploader("Nahrát aktuální smlouvu", type="pdf", key="nova_sml")

    if pdf_stara and pdf_nova and st.button("Analyzovat změny", type="primary"):
        with st.spinner("Porovnávám smlouvy..."):
            try:
                # Čtení PDF
                text_stara = ""
                reader = PdfReader(pdf_stara)
                for page in reader.pages:
                    text_stara += page.extract_text() or ""

                text_nova = ""
                reader = PdfReader(pdf_nova)
                for page in reader.pages:
                    text_nova += page.extract_text() or ""

                analyza = porovnej_smlouvy(text_stara, text_nova)

                # Zobrazení výsledků
                st.success("Analýza změn dokončena")

                zmeny = analyza.get("zmeny_najmu", {})
                if zmeny.get("mesicni_zmena", 0) != 0:
                    st.metric(
                        "Změna měsíčního nájmu", 
                        f"{zmeny['mesicni_zmena']:+,} Kč",
                        f"Roční dopad: {zmeny['rocni_dopad']:+,} Kč"
                    )

                if analyza.get("zmeny_zaloh"):
                    st.markdown("**Změny záloh na služby:**")
                    df_zmeny = pd.DataFrame(analyza["zmeny_zaloh"])
                    st.dataframe(df_zmeny, hide_index=True)

                # Uložení do session
                aktivni = get_aktivni_vyuctovani()
                aktivni["minula_smlouva"]["data"] = analyza
                aktivni["minula_smlouva"]["zmeny"] = analyza.get("zmeny_zaloh", [])

            except Exception as e:
                st.error(f"Chyba analýzy: {e}")

def render_minule_vyuctovani():
    """Nahrání minulého vyúčtování pro kontext"""
    st.subheader("📜 Kontext minulého vyúčtování")

    pdf_minule = st.file_uploader(
        "Nahrát loňské vyúčtování (PDF)", 
        type="pdf", 
        help="Pro analýzu přeplatků a změn plateb v průběhu roku"
    )

    if pdf_minule:
        preplatek = st.number_input("Přeplatek z minulého roku (Kč)", min_value=0.0, value=0.0)
        komentar = st.text_area("Poznámka k minulému vyúčtování")

        if st.button("Uložit kontext"):
            aktivni = get_aktivni_vyuctovani()
            aktivni["minule_vyuctovani"]["soubor"] = pdf_minule.name
            aktivni["minule_vyuctovani"]["preplatek"] = preplatek
            aktivni["minule_vyuctovani"]["komentar"] = komentar
            st.success("Kontext uložen")

def render_zpracovani_slozek():
    """Zpracování jednotlivých složek vyúčtování"""
    st.subheader("📊 Zpracování složek")

    sluzby = st.session_state.sluzby_config
    aktivni = get_aktivni_vyuctovani()

    # Vytvoření záložek pro každou aktivní službu
    aktivni_sluzby = [k for k, v in sluzby.items() if v["aktivni"] or v["povinne"]]

    if not aktivni_sluzby:
        st.warning("Nejsou vybrány žádné služby k vyúčtování")
        return

    tabs = st.tabs([sluzby[k]["nazev"] for k in aktivni_sluzby])

    for idx, sluzba_key in enumerate(aktivni_sluzby):
        with tabs[idx]:
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**📄 Faktura/Vyúčtování**")
                pdf_faktura = st.file_uploader(
                    f"Nahrát doklad ({sluzba_key})", 
                    type="pdf",
                    key=f"fakt_{sluzba_key}"
                )

            with col2:
                st.markdown("**💰 Zaplatené zálohy**")
                excel_zalohy = st.file_uploader(
                    f"Bankovní pohyby ({sluzba_key})",
                    type=["xlsx", "csv"],
                    key=f"zal_{sluzba_key}"
                )

            if pdf_faktura and st.button(f"Analyzovat {sluzba_key}", key=f"btn_{sluzba_key}"):
                with st.spinner(f"Zpracovávám {sluzba_key}..."):
                    try:
                        # Čtení PDF
                        text = ""
                        reader = PdfReader(pdf_faktura)
                        for page in reader.pages:
                            text += page.extract_text() or ""

                        if sluzba_key == "svj":
                            data = analyza_vyuctovani_svj(text, sluzby)
                        else:
                            # Generická analýza pro ostatní služby
                            prompt = f"""
                            Extrahuj z faktury: celkovou částku, období, položky rozpisu.
                            Služba: {sluzba_key}
                            Text: {text[:3000]}
                            Vrať JSON: {{"celkem": 0, "polozky": [], "obdobi": "..."}}
                            """
                            data = ai_chat(prompt)

                        # Uložení
                        if sluzba_key not in aktivni["slozky"]:
                            aktivni["slozky"][sluzba_key] = {"naklady": 0, "zalohy": 0, "polozky": []}

                        aktivni["slozky"][sluzba_key]["naklady"] = data.get("celkem", 0)
                        aktivni["slozky"][sluzba_key]["polozky"] = data.get("polozky", [])

                        st.success(f"{sluzba_key}: Náklady {data.get('celkem', 0)} Kč")
                        st.json(data)

                    except Exception as e:
                        st.error(f"Chyba: {e}")

            # Ruční zadání pokud nemáme AI
            with st.expander("Ruční zadání"):
                naklady = st.number_input(
                    f"Celkové náklady ({sluzba_key})",
                    min_value=0.0,
                    value=float(aktivni["slozky"].get(sluzba_key, {}).get("naklady", 0)),
                    key=f"man_nakl_{sluzba_key}"
                )
                zalohy = st.number_input(
                    f"Zaplatené zálohy ({sluzba_key})",
                    min_value=0.0,
                    value=float(aktivni["slozky"].get(sluzba_key, {}).get("zalohy", 0)),
                    key=f"man_zal_{sluzba_key}"
                )

                if st.button(f"Uložit {sluzba_key}", key=f"save_{sluzba_key}"):
                    if sluzba_key not in aktivni["slozky"]:
                        aktivni["slozky"][sluzba_key] = {}
                    aktivni["slozky"][sluzba_key]["naklady"] = naklady
                    aktivni["slozky"][sluzba_key]["zalohy"] = zalohy
                    st.success("Uloženo")

def render_analyza_plateb():
    """Analýza odchylek plateb od smlouvy"""
    st.subheader("🔍 Analýza průběžných plateb")

    st.markdown("""
    **Proč to potřebujete:** Pokud nájemník posílal v průběhu roku jiné částky než je ve smlouvě 
    (např. kvůli vracení přeplatku z minulého roku), tato analýza vysvětlí souvislosti.
    """)

    banka_file = st.file_uploader(
        "Kompletní bankovní výpis za rok (Excel/CSV)",
        type=["xlsx", "csv"],
        help="Sloupce: datum, castka, poznamka. Systém detekuje odchylky od smluvních záloh."
    )

    if banka_file and st.button("Analyzovat platby", type="primary"):
        try:
            df = pd.read_excel(banka_file) if banka_file.name.endswith('.xlsx') else pd.read_csv(banka_file)

            # Jednoduchá analýza bez AI (rychlejší pro demo)
            st.markdown("**Statistika plateb:**")

            # Předpokládáme sloupec 'castka' nebo 'částka'
            castka_col = next((col for col in df.columns if 'castka' in col.lower() or 'částka' in col.lower()), None)
            if castka_col:
                mesicni_prumer = df[castka_col].mean()
                celkem = df[castka_col].sum()

                col1, col2, col3 = st.columns(3)
                col1.metric("Počet plateb", len(df))
                col2.metric("Průměrná platba", f"{mesicni_prumer:,.2f} Kč")
                col3.metric("Celkem zaplaceno", f"{celkem:,.2f} Kč")

                # Graf plateb v čase
                if 'datum' in df.columns:
                    df['datum'] = pd.to_datetime(df['datum'])
                    df = df.sort_values('datum')

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=df['datum'], 
                        y=df[castka_col],
                        mode='lines+markers',
                        name='Platby'
                    ))
                    fig.add_hline(y=mesicni_prumer, line_dash="dash", annotation_text="Průměr")
                    fig.update_layout(title="Vývoj plateb v čase", xaxis_title="Datum", yaxis_title="Částka (Kč)")
                    st.plotly_chart(fig, use_container_width=True)

                # Uložení do session
                aktivni = get_aktivni_vyuctovani()
                aktivni["platby_priebeh"] = df.to_dict('records')

        except Exception as e:
            st.error(f"Chyba analýzy: {e}")

def render_prehled():
    """Celkový přehled a výsledek"""
    st.header("📋 Rekapitulace vyúčtování")

    aktivni = get_aktivni_vyuctovani()
    sluzby = st.session_state.sluzby_config

    if not aktivni["slozky"]:
        st.warning("Zatím nejsou zpracovány žádné složky")
        return

    # Základní údaje
    with st.expander("✏️ Editace základních údajů", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            aktivni["zakladni_udaje"]["poskytovatel"] = st.text_input(
                "Poskytovatel", 
                value=aktivni["zakladni_udaje"].get("poskytovatel", "")
            )
            aktivni["zakladni_udaje"]["platce"] = st.text_input(
                "Plátce", 
                value=aktivni["zakladni_udaje"].get("platce", "")
            )
        with col2:
            aktivni["zakladni_udaje"]["adresa"] = st.text_input(
                "Adresa", 
                value=aktivni["zakladni_udaje"].get("adresa", "")
            )
            aktivni["zakladni_udaje"]["byt"] = st.text_input(
                "Byt", 
                value=aktivni["zakladni_udaje"].get("byt", "")
            )

    # Výpočet součtů
    celkem_naklady = 0
    celkem_zalohy = 0

    data_prehled = []
    for key, slozka in aktivni["slozky"].items():
        nakl = slozka.get("naklady", 0)
        zal = slozka.get("zalohy", 0)
        rozdil = zal - nakl

        celkem_naklady += nakl
        celkem_zalohy += zal

        data_prehled.append({
            "Služba": sluzby[key]["nazev"],
            "Náklady": f"{nakl:,.2f} Kč",
            "Zálohy": f"{zal:,.2f} Kč",
            "Rozdíl": f"{rozdil:,.2f} Kč",
            "Stav": "✅ Přeplatek" if rozdil > 0 else "❌ Nedoplatek" if rozdil < 0 else "⚖️ Vyrovnáno"
        })

    # Přeplatek z minulého roku
    preplatek_minuly = aktivni["minule_vyuctovani"].get("preplatek", 0)
    if preplatek_minuly > 0:
        data_prehled.append({
            "Služba": "Přeplatek z minulého roku",
            "Náklady": "-",
            "Zálohy": f"{preplatek_minuly:,.2f} Kč",
            "Rozdíl": f"{preplatek_minuly:,.2f} Kč",
            "Stav": "🔄 Převedeno"
        })
        celkem_zalohy += preplatek_minuly

    df_prehled = pd.DataFrame(data_prehled)
    st.dataframe(df_prehled, hide_index=True, use_container_width=True)

    # Finální výsledek
    celkovy_rozdil = celkem_zalohy - celkem_naklady

    st.divider()
    st.subheader("💰 Finální vyúčtování")

    col1, col2, col3 = st.columns(3)
    col1.metric("Celkem zaplaceno", f"{celkem_zalohy:,.2f} Kč")
    col2.metric("Celkem nákladů", f"{celkem_naklady:,.2f} Kč")

    if celkovy_rozdil > 0:
        col3.metric("VÝSLEDEK", f"{celkovy_rozdil:,.2f} Kč", delta="Přeplatek pro nájemníka")
        st.success(f"### ✅ Nájemník má nárok na vrácení {celkovy_rozdil:,.2f} Kč")
        st.info("Doporučení: Částka bude vrácena na účet nebo započtena do nájmu příštího období.")
    elif celkovy_rozdil < 0:
        col3.metric("VÝSLEDEK", f"{celkovy_rozdil:,.2f} Kč", delta="Doplatek od nájemníka")
        st.error(f"### ❌ Nájemník dluží {abs(celkovy_rozdil):,.2f} Kč")
        st.warning("Doporučení: Vystavte fakturu na doplatek se splatností dle nájemní smlouvy.")
    else:
        col3.metric("VÝSLEDEK", "0 Kč", delta="Vyrovnáno")
        st.info("### ⚖️ Vyúčtování je vyrovnané")

    # Graf
    if len(data_prehled) > 0:
        fig = go.Figure(data=[
            go.Bar(name='Náklady', 
                   x=[s["Služba"] for s in data_prehled if s["Náklady"] != "-"], 
                   y=[float(s["Náklady"].replace(" Kč", "").replace(",", "")) for s in data_prehled if s["Náklady"] != "-"], 
                   marker_color='#e74c3c'),
            go.Bar(name='Zálohy', 
                   x=[s["Služba"] for s in data_prehled], 
                   y=[float(s["Zálohy"].replace(" Kč", "").replace(",", "")) for s in data_prehled], 
                   marker_color='#2ecc71')
        ])
        fig.update_layout(
            barmode='group', 
            title='Srovnání nákladů a záloh podle kategorií',
            xaxis_tickangle=-45
        )
        st.plotly_chart(fig, use_container_width=True)

    # Export protokolu
    st.divider()
    if st.button("📄 Generovat finální protokol (PDF)", type="primary"):
        st.success("Protokol připraven k tisku (funkce exportu PDF je připravena k implementaci)")

        # Zobrazení textu protokolu
        st.markdown("---")
        st.markdown("### Náhled protokolu:")
        st.markdown(f"""
        **PROTOKOL O VYÚČTOVÁNÍ SLUŽEB**

        Adresa: {aktivni["zakladni_udaje"]["adresa"]}, byt {aktivni["zakladni_udaje"]["byt"]}
        Období: {st.session_state.databaze["aktivni_rok"]}

        Poskytovatel: {aktivni["zakladni_udaje"]["poskytovatel"]}
        Plátce: {aktivni["zakladni_udaje"]["platce"]}

        Celkem zaplaceno: {celkem_zalohy:,.2f} Kč
        Celkem nákladů: {celkem_naklady:,.2f} Kč
        Výsledek: {celkovy_rozdil:,.2f} Kč ({"přeplatek" if celkovy_rozdil > 0 else "doplatek" if celkovy_rozdil < 0 else "vyrovnáno"})
        """)

def get_aktivni_vyuctovani():
    """Helper pro získání aktuálního vyúčtování"""
    najem_id = st.session_state.databaze.get("aktivni_najem")
    rok = str(st.session_state.databaze.get("aktivni_rok", datetime.now().year))

    if not najem_id:
        return get_default_vyuctovani()

    najem = st.session_state.databaze["najmy"].get(najem_id, {})
    if "vyuctovani" not in najem:
        najem["vyuctovani"] = {}
    if rok not in najem["vyuctovani"]:
        najem["vyuctovani"][rok] = get_default_vyuctovani()

    return najem["vyuctovani"][rok]

# ==========================================
# HLAVNÍ APLIKACE
# ==========================================
def main():
    init_session_state()

    st.title("🏢 Profesionální vyúčtování nájemného - Multi verze")
    st.caption("Systém pro správu více nemovitostí a historie vyúčtování")

    # Sidebar správa
    render_sprava_najmu()

    # Kontrola zda máme vybraný nájem
    if not st.session_state.databaze.get("aktivni_najem"):
        st.info("👈 Vyberte nebo vytvořte nájem v postranní liště")
        st.markdown("""
        ### Vítejte v systému Vyúčtování PRO

        Tato aplikace umožňuje:
        - 📁 Spravovat více nájmů/nemovitostí
        - 📅 Ukládat historii vyúčtování pro jednotlivé roky
        - ⚡ Porovnávat změny smluv mezi roky
        - 🔍 Analyzovat odchylky plateb
        - 📊 Zpracovávat různé služby (SVJ, elektřina, plyn, internet...)

        Začněte vytvořením nového nájmu v menu vlevo.
        """)
        return

    # Základní údaje
    najem_info = st.session_state.databaze["najmy"][st.session_state.databaze["aktivni_najem"]]
    st.header(f"📍 {najem_info['adresa']}, byt {najem_info['byt']}")
    st.subheader(f"Rok vyúčtování: {st.session_state.databaze['aktivni_rok']}")

    # Konfigurace služeb
    render_konfigurace_sluzby()
    st.divider()

    # Tabs pro jednotlivé sekce
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔄 Srovnání smluv", 
        "📜 Historie & Kontext", 
        "📊 Zpracování složek",
        "📋 Rekapitulace"
    ])

    with tab1:
        render_srovnani_smluv()

    with tab2:
        render_minule_vyuctovani()
        st.divider()
        render_analyza_plateb()

    with tab3:
        render_zpracovani_slozek()

    with tab4:
        render_prehled()

if __name__ == "__main__":
    main()
