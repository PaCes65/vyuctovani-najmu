import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# Vytvoření sešitu
wb = openpyxl.Workbook()
wb.remove(wb.active)  # Odstranění výchozího listu

# Definice stylů
header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
subtotal_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
white_font = Font(color="FFFFFF", bold=True)
bold_font = Font(bold=True)
center_align = Alignment(horizontal="center", vertical="center")
left_align = Alignment(horizontal="left", vertical="center")
thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

# --- LIST 1: SOUHRN ---
ws1 = wb.create_sheet("1. Souhrn a Výsledek")
ws1.column_dimensions['A'].width = 30
ws1.column_dimensions['B'].width = 40

# Záhlaví listu
ws1.merge_cells('A1:B1')
ws1['A1'] = "PROTOKOL O ZÚČTOVÁNÍ ZÁLOH NA SLUŽBY"
ws1['A1'].font = Font(size=14, bold=True)
ws1['A1'].alignment = center_align

# Sekce Profil
ws1['A3'] = "IDENTIFIKACE STRAN"
ws1['A3'].font = bold_font
ws1['A4'], ws1['B4'] = "Poskytovatel:", "Vyplňte jméno (např. Pronajímatel)"
ws1['A5'], ws1['B5'] = "Plátce:", "Madar Ruslan"
ws1['A6'], ws1['B6'] = "Adresa / Byt:", "Vyplňte adresu"
ws1['A7'], ws1['B7'] = "Zúčtovací období:", "Rok 2025"

for row in range(4, 8):
    ws1[f'A{row}'].border = thin_border
    ws1[f'B{row}'].border = thin_border

# Sekce Finanční Syntéza
ws1['A9'] = "FINANČNÍ SYNTÉZA"
ws1['A9'].font = bold_font

ws1['A10'], ws1['B10'] = "Celkem přijaté platby (z listu 4):", "='4. Bankovní Transakce'!B14"
ws1['A11'], ws1['B11'] = "Předpis čistého nájemného (z listu 2):", "='2. Předpis a Osoby'!C14"
ws1['A12'], ws1['B12'] = "Korekce salda N-1 (Přeplatek + / Nedoplatek -):", 0
ws1['A13'], ws1['B13'] = "Disponibilní zálohy k vyrovnání:", "=B10-B11+B12"
ws1['A14'], ws1['B14'] = "Uznatelné náklady (z listu 3):", "='3. Náklady'!B14"

ws1['A16'] = "VÝSLEDNÉ SALDO:"
ws1['B16'] = "=B13-B14"
ws1['A16'].font = Font(size=12, bold=True)
ws1['B16'].font = Font(size=12, bold=True)
ws1['B16'].number_format = '#,##0.00 "Kč"'

for row in range(10, 15):
    ws1[f'A{row}'].border = thin_border
    ws1[f'B{row}'].border = thin_border
    ws1[f'B{row}'].number_format = '#,##0.00 "Kč"'

# --- LIST 2: PŘEDPIS A OSOBY ---
ws2 = wb.create_sheet("2. Předpis a Osoby")
ws2.column_dimensions['A'].width = 25
ws2.column_dimensions['B'].width = 15
ws2.column_dimensions['C'].width = 15
ws2.column_dimensions['D'].width = 15

# Tabulka předpisu
headers = ["Období (Od-Do měsíce)", "Počet měsíců", "Nájem / měs.", "Záloha / měs.", "Suma Nájem", "Suma Zálohy"]
for col, text in enumerate(headers, 1):
    cell = ws2.cell(row=2, column=col)
    cell.value = text
    cell.fill = header_fill
    cell.font = white_font
    cell.alignment = center_align

# Příklad dat s modifikací v průběhu roku (Smlouva 1 a Smlouva 2)
# Interval 1: 1-5 měsíc
ws2.append(["1 - 5", 5, 9900, 3000, "=B3*C3", "=B3*D3"])
# Interval 2: 6-12 měsíc (např. zvýšení nájmu)
ws2.append(["6 - 12", 7, 10500, 3200, "=B4*C4", "=B4*D4"])

# Součty předpisu
ws2['B14'] = "CELKEM ROK:"
ws2['B14'].font = bold_font
ws2['C14'] = "=SUM(E3:E12)" # Celkem čistý nájem
ws2['D14'] = "=SUM(F3:F12)" # Celkem zálohy
ws2['C14'].number_format = ws2['D14'].number_format = '#,##0.00 "Kč"'

# Tabulka osob
ws2['A17'] = "EVIDENCE OSOB (OBSAZENOST)"
ws2['A17'].font = bold_font
headers_os = ["Jméno osoby", "Od měsíce", "Do měsíce", "Osoboměsíců"]
for col, text in enumerate(headers_os, 1):
    cell = ws2.cell(row=18, column=col)
    cell.value = text
    cell.fill = header_fill
    cell.font = white_font

ws2.append(["Madar Ruslan", 1, 12, "=C19-B19+1"])
ws2.append(["Spolubydlící 1", 1, 6, "=C20-B20+1"])

ws2['C25'] = "Průměrný počet osob:"
ws2['D25'] = "=SUM(D19:D24)/12"
ws2['D25'].number_format = '0.00'

# --- LIST 3: NÁKLADY ---
ws3 = wb.create_sheet("3. Náklady")
ws3.column_dimensions['A'].width = 40
ws3.column_dimensions['B'].width = 20

ws3['A2'] = "Položka nákladu (SVJ / Energie)"
ws3['B2'] = "Částka [Kč]"
for col in range(1, 3):
    ws3.cell(row=2, column=col).fill = header_fill
    ws3.cell(row=2, column=col).font = white_font

# Simulace nákladů
naklady_data = [
    ("SVJ - Studená voda", 4500),
    ("SVJ - Teplá voda (ohřev)", 8200),
    ("SVJ - Teplo / Topení", 12000),
    ("SVJ - Výtah", 1200),
    ("SVJ - Úklid společných prostor", 2400),
    ("Elektřina (přímá faktura)", 15000),
    ("Plyn (přímá faktura)", 18000),
]

for r_idx, (name, val) in enumerate(naklady_data, 3):
    ws3[f'A{r_idx}'] = name
    ws3[f'B{r_idx}'] = val
    ws3[f'B{r_idx}'].number_format = '#,##0.00 "Kč"'

ws3['A14'] = "CELKEM UZNATELNÉ NÁKLADY:"
ws3['A14'].font = bold_font
ws3['B14'] = "=SUM(B3:B13)"
ws3['B14'].number_format = '#,##0.00 "Kč"'

# --- LIST 4: TRANSAKCE ---
ws4 = wb.create_sheet("4. Bankovní Transakce")
ws4.column_dimensions['A'].width = 15
ws4.column_dimensions['B'].width = 15
ws4.column_dimensions['C'].width = 40

ws4['A2'] = "Datum"
ws4['B2'] = "Částka [Kč]"
ws4['C2'] = "Poznámka / Variabilní symbol"
for col in range(1, 4):
    ws4.cell(row=2, column=col).fill = header_fill
    ws4.cell(row=2, column=col).font = white_font

# Simulace plateb z CSV (Madar Ruslan)
for m in range(1, 13):
    ws4.cell(row=m+2, column=1).value = f"2025-{m:02d}-14"
    ws4.cell(row=m+2, column=2).value = 12900 # Celková platba (Nájem+Záloha)
    ws4.cell(row=m+2, column=3).value = "Nájem P13 Madar"
    ws4.cell(row=m+2, column=2).number_format = '#,##0.00 "Kč"'

ws4['A14'] = "SOUČET PŘIJATO:"
ws4['A14'].font = bold_font
ws4['B14'] = "=SUM(B3:B13)"
ws4['B14'].number_format = '#,##0.00 "Kč"'

# Uložení
file_path = "Vyuctovani_Madar_2025.xlsx"
wb.save(file_path)

print(file_path)
Váš soubor Excel je připraven.
[file-tag: code-generated-file-330c9e6e4a]

Co tento soubor obsahuje:
Automatické výpočty: Na listu 1. Souhrn se automaticky sčítají data z ostatních listů. Stačí upravit částky na vedlejších listech a výsledek se sám přepočítá.

Práce s více smlouvami: Na listu 2. Předpis a Osoby jsem připravil strukturu, kde můžete rozdělit rok na více období (např. 1–5 měsíc se starou cenou a 6–12 měsíc s novou cenou).

Průměrná obsazenost: Excel automaticky počítá "osoboměsíce" a průměr na osobu za rok, což je klíčové pro správné rozúčtování vody nebo výtahu.

Profesionální formátování: Všechny částky jsou ve formátu měny (Kč), záhlaví jsou barevně odlišena a buňky jsou připraveny k tisku.

Tento soubor můžete dál rozšiřovat nebo do něj kopírovat data z vašich bankovních exportů. Pokud budete chtít doplnit další specifické výpočty, dejte vědět!





Gemini is AI and can make mistakes, including about people. Your privacy and GeminiOpens in a new window


