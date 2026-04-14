
import streamlit as st
import pandas as pd
from datetime import datetime

# --- Naše předchozí logika (mírně zjednodušená pro UI) ---
class Smlouva:
    def __init__(self, jmeno, datum_od, datum_do):
        self.jmeno = jmeno
        self.datum_od = datum_od # Streamlit už vrací objekty datetime.date
        self.datum_do = datum_do

    def pocet_dni_v_roce(self, rok):
        zacatek_roku = datetime(rok, 1, 1).date()
        konec_roku = datetime(rok, 12, 31).date()
        realny_zacatek = max(self.datum_od, zacatek_roku)
        realny_konec = min(self.datum_do, konec_roku)
        dny = (realny_konec - realny_zacatek).days + 1
        return dny if dny > 0 else 0

# --- Grafické rozhraní pro mobil (Streamlit) ---
st.set_page_config(page_title="Vyúčtování Nájmů", page_icon="📱", layout="centered")

st.title("📱 Vyúčtování nájmů")
st.write("Aplikace pro rychlý výpočet ročního vyúčtování.")

st.header("1. Údaje ze smlouvy")
jmeno_najemnika = st.text_input("Jméno nájemníka", placeholder="např. Jan Novák")
col1, col2 = st.columns(2)
with col1:
    datum_od = st.date_input("Platnost OD")
with col2:
    datum_do = st.date_input("Platnost DO")

rok_vyuctovani = st.number_input("Rok vyúčtování", min_value=2020, max_value=2030, value=2025)

st.header("2. Nahrání podkladů")
# Tlačítka, která na mobilu otevřou výběr souborů
pdf_svj = st.file_uploader("Nahraj vyúčtování od SVJ (PDF)", type="pdf")
vypis_banka = st.file_uploader("Nahraj výpis plateb záloh (CSV/Excel)", type=["csv", "xlsx"])

st.header("3. Výpočet")
if st.button("📊 Spočítat vyúčtování", use_container_width=True):
    if not jmeno_najemnika or not pdf_svj or not vypis_banka:
        st.error("⚠️ Prosím, vyplň jméno a nahraj oba soubory (SVJ i banku).")
    else:
        # Zde později zavoláme naši kompletní logiku pro parsování PDF
        smlouva = Smlouva(jmeno_najemnika, datum_od, datum_do)
        pocet_dni = smlouva.pocet_dni_v_roce(rok_vyuctovani)
        
        st.success("✅ Výpočet úspěšně dokončen!")
        st.info(f"Nájemník {jmeno_najemnika} užíval byt v roce {rok_vyuctovani} celkem {pocet_dni} dní.")
        
        # Místo pro finální report
        st.metric(label="Výsledný přeplatek/nedoplatek", value="Bude doplněno Kč")
