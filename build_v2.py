#!/usr/bin/env python3
"""Extract root attributes from DE Amazon search terms and build a keyword library."""
import re, json, openpyxl
from collections import defaultdict, Counter
from pathlib import Path

SRC = Path("/Users/hosen/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/7C21D360DBFA836768191953082E98DB/Caches/Files/2026-06/781fd32262d3ebf3a9762247d5be4003/DE广告搜索词近365天.xlsx")
OUT = Path("/Users/hosen/Documents/Amazon/keyword_library")
OUT.mkdir(parents=True, exist_ok=True)

# ── Normalize text before matching ──
def norm(text):
    """Normalize text for matching: lowercase, collapse spaces, normalize variants."""
    t = text.lower().strip()
    t = re.sub(r'\s+', ' ', t)
    t = t.replace('i phone', 'iphone').replace('i-phone', 'iphone').replace('ip ', 'iphone ')
    t = t.replace('apple iphone', 'iphone').replace('apple ', '')
    t = t.replace('google pixel', 'googlepixel').replace('google ', 'google')
    t = t.replace('samsung galaxy', 'samsunggalaxy').replace('samsung ', 'samsung')
    t = t.replace('xiaomi redmi', 'xiaomiredmi').replace('xiaomi ', 'xiaomi')
    t = t.replace('motorola edge', 'motorolaedge').replace('motorola ', 'motorola')
    t = t.replace('huawei nova', 'huaweinova').replace('huawei ', 'huawei')
    t = t.replace('honor magic', 'honormagic').replace('honor ', 'honor')
    t = t.replace('oppo find', 'oppofind').replace('oppo ', 'oppo')
    t = t.replace('oneplus ', 'oneplus')
    t = t.replace('vivo ', 'vivo')
    t = t.replace('cmf phone', 'cmfphone').replace('cmf ', 'cmf')
    t = t.replace('fairphone ', 'fairphone')
    t = t.replace('galaxy ', 'galaxy')
    t = t.replace('pixel ', 'pixel')
    t = t.replace('edge ', 'edge')
    t = t.replace('find ', 'find')
    t = t.replace('magic ', 'magic')
    t = t.replace('nova ', 'nova')
    return t

# ── Model detection (ordered most-specific first) ──
MODELS = [
    # iPhone
    (r"iphone\s*17\s*pro\s*max", "iPhone 17 Pro Max"),
    (r"iphone\s*17\s*pro", "iPhone 17 Pro"),
    (r"iphone\s*17", "iPhone 17"),
    (r"iphone\s*16\s*pro\s*max", "iPhone 16 Pro Max"),
    (r"iphone\s*16\s*pro", "iPhone 16 Pro"),
    (r"iphone\s*16\s*plus", "iPhone 16 Plus"),
    (r"iphone\s*16\s*e", "iPhone 16e"),
    (r"iphone\s*16", "iPhone 16"),
    (r"iphone\s*15\s*pro\s*max", "iPhone 15 Pro Max"),
    (r"iphone\s*15\s*pro", "iPhone 15 Pro"),
    (r"iphone\s*15\s*plus", "iPhone 15 Plus"),
    (r"iphone\s*15", "iPhone 15"),
    (r"iphone\s*14\s*pro\s*max", "iPhone 14 Pro Max"),
    (r"iphone\s*14\s*pro", "iPhone 14 Pro"),
    (r"iphone\s*14\s*plus", "iPhone 14 Plus"),
    (r"iphone\s*14", "iPhone 14"),
    (r"iphone\s*13\s*pro\s*max", "iPhone 13 Pro Max"),
    (r"iphone\s*13\s*pro", "iPhone 13 Pro"),
    (r"iphone\s*13\s*mini", "iPhone 13 mini"),
    (r"iphone\s*13", "iPhone 13"),
    (r"iphone\s*12\s*pro\s*max", "iPhone 12 Pro Max"),
    (r"iphone\s*12\s*pro", "iPhone 12 Pro"),
    (r"iphone\s*12\s*mini", "iPhone 12 mini"),
    (r"iphone\s*12", "iPhone 12"),
    (r"iphone\s*11\s*pro\s*max", "iPhone 11 Pro Max"),
    (r"iphone\s*11\s*pro", "iPhone 11 Pro"),
    (r"iphone\s*11", "iPhone 11"),
    (r"iphone\s*se", "iPhone SE"),
    (r"iphone\s*xr", "iPhone XR"),
    (r"iphone\s*xs\s*max", "iPhone XS Max"),
    (r"iphone\s*xs", "iPhone XS"),
    (r"iphone\s*x\b", "iPhone X"),
    (r"iphone", "iPhone"),
]

# Google Pixel
PIXEL_MODELS = [
    (r"googlepixel\s*10\s*pro\s*xl", "Google Pixel 10 Pro XL"),
    (r"googlepixel\s*10\s*pro", "Google Pixel 10 Pro"),
    (r"googlepixel\s*10\s*a", "Google Pixel 10a"),
    (r"googlepixel\s*10", "Google Pixel 10"),
    (r"googlepixel\s*9\s*pro\s*xl", "Google Pixel 9 Pro XL"),
    (r"googlepixel\s*9\s*pro", "Google Pixel 9 Pro"),
    (r"googlepixel\s*9\s*a", "Google Pixel 9a"),
    (r"googlepixel\s*9\s*xl", "Google Pixel 9 XL"),
    (r"googlepixel\s*9", "Google Pixel 9"),
    (r"googlepixel\s*8\s*pro", "Google Pixel 8 Pro"),
    (r"googlepixel\s*8\s*a", "Google Pixel 8a"),
    (r"googlepixel\s*8", "Google Pixel 8"),
    (r"googlepixel\s*7\s*pro", "Google Pixel 7 Pro"),
    (r"googlepixel\s*7\s*a", "Google Pixel 7a"),
    (r"googlepixel\s*7", "Google Pixel 7"),
    (r"googlepixel\s*6\s*pro", "Google Pixel 6 Pro"),
    (r"googlepixel\s*6\s*a", "Google Pixel 6a"),
    (r"googlepixel\s*6", "Google Pixel 6"),
    (r"googlepixel\s*4\s*a", "Google Pixel 4a"),
    (r"googlepixel", "Google Pixel"),
    # Short forms: "pixel 8 pro", "pixel 8a" (without google)
    (r"\bpixel\s*10\s*pro\s*xl\b", "Google Pixel 10 Pro XL"),
    (r"\bpixel\s*10\s*pro\b", "Google Pixel 10 Pro"),
    (r"\bpixel\s*10\s*a\b", "Google Pixel 10a"),
    (r"\bpixel\s*10\b", "Google Pixel 10"),
    (r"\bpixel\s*9\s*pro\s*xl\b", "Google Pixel 9 Pro XL"),
    (r"\bpixel\s*9\s*pro\b", "Google Pixel 9 Pro"),
    (r"\bpixel\s*9\s*a\b", "Google Pixel 9a"),
    (r"\bpixel\s*9\s*xl\b", "Google Pixel 9 XL"),
    (r"\bpixel\s*9\b", "Google Pixel 9"),
    (r"\bpixel\s*8\s*pro\b", "Google Pixel 8 Pro"),
    (r"\bpixel\s*8\s*a\b", "Google Pixel 8a"),
    (r"\bpixel\s*8\b", "Google Pixel 8"),
    (r"\bpixel\s*7\s*pro\b", "Google Pixel 7 Pro"),
    (r"\bpixel\s*7\s*a\b", "Google Pixel 7a"),
    (r"\bpixel\s*7\b", "Google Pixel 7"),
    (r"\bpixel\s*6\s*pro\b", "Google Pixel 6 Pro"),
    (r"\bpixel\s*6\s*a\b", "Google Pixel 6a"),
    (r"\bpixel\s*6\b", "Google Pixel 6"),
    (r"\bpixel\s*4\s*a\b", "Google Pixel 4a"),
    # Google short: "google 8 pro", "google 8a"
    (r"\bgoogle\s*8\s*pro\b", "Google Pixel 8 Pro"),
    (r"\bgoogle\s*8\s*a\b", "Google Pixel 8a"),
    (r"\bgoogle\s*8\b", "Google Pixel 8"),
    (r"\bgoogle\s*9\s*pro\s*xl\b", "Google Pixel 9 Pro XL"),
    (r"\bgoogle\s*9\s*pro\b", "Google Pixel 9 Pro"),
    (r"\bgoogle\s*9\s*a\b", "Google Pixel 9a"),
    (r"\bgoogle\s*9\s*xl\b", "Google Pixel 9 XL"),
    (r"\bgoogle\s*9\b", "Google Pixel 9"),
    (r"\bgoogle\s*7\s*pro\b", "Google Pixel 7 Pro"),
    (r"\bgoogle\s*7\s*a\b", "Google Pixel 7a"),
    (r"\bgoogle\s*7\b", "Google Pixel 7"),
    (r"\bgoogle\s*6\s*pro\b", "Google Pixel 6 Pro"),
    (r"\bgoogle\s*6\s*a\b", "Google Pixel 6a"),
    (r"\bgoogle\s*6\b", "Google Pixel 6"),
]
MODELS.extend(PIXEL_MODELS)

# Samsung Galaxy S
SAMSUNG_S = [
    (r"samsunggalaxy\s*s\s*25\s*fe", "Samsung Galaxy S25 FE"),
    (r"samsunggalaxy\s*s\s*25", "Samsung Galaxy S25"),
    (r"samsunggalaxy\s*s\s*24\s*fe", "Samsung Galaxy S24 FE"),
    (r"samsunggalaxy\s*s\s*24\s*plus", "Samsung Galaxy S24+"),
    (r"samsunggalaxy\s*s\s*24", "Samsung Galaxy S24"),
    (r"samsunggalaxy\s*s\s*23\s*fe", "Samsung Galaxy S23 FE"),
    (r"samsunggalaxy\s*s\s*23", "Samsung Galaxy S23"),
    (r"samsunggalaxy\s*s\s*22", "Samsung Galaxy S22"),
    (r"samsunggalaxy\s*s\s*21\s*fe", "Samsung Galaxy S21 FE"),
    (r"samsunggalaxy\s*s\s*21", "Samsung Galaxy S21"),
    (r"samsunggalaxy\s*s\s*20\s*fe", "Samsung Galaxy S20 FE"),
    (r"samsunggalaxy\s*s\s*20", "Samsung Galaxy S20"),
    (r"samsunggalaxy\s*s\s*10", "Samsung Galaxy S10"),
    (r"samsunggalaxy\s*s\s*9", "Samsung Galaxy S9"),
]
# Samsung Galaxy A
SAMSUNG_A = [
    (r"samsunggalaxy\s*a\s*56\s*5g", "Samsung Galaxy A56 5G"),
    (r"samsunggalaxy\s*a\s*55\s*5g", "Samsung Galaxy A55 5G"),
    (r"samsunggalaxy\s*a\s*55", "Samsung Galaxy A55"),
    (r"samsunggalaxy\s*a\s*54\s*5g", "Samsung Galaxy A54 5G"),
    (r"samsunggalaxy\s*a\s*54", "Samsung Galaxy A54"),
    (r"samsunggalaxy\s*a\s*53\s*5g", "Samsung Galaxy A53 5G"),
    (r"samsunggalaxy\s*a\s*53", "Samsung Galaxy A53"),
    (r"samsunggalaxy\s*a\s*52", "Samsung Galaxy A52"),
    (r"samsunggalaxy\s*a\s*36\s*5g", "Samsung Galaxy A36 5G"),
    (r"samsunggalaxy\s*a\s*35\s*5g", "Samsung Galaxy A35 5G"),
    (r"samsunggalaxy\s*a\s*35", "Samsung Galaxy A35"),
    (r"samsunggalaxy\s*a\s*34\s*5g", "Samsung Galaxy A34 5G"),
    (r"samsunggalaxy\s*a\s*34", "Samsung Galaxy A34"),
    (r"samsunggalaxy\s*a\s*33", "Samsung Galaxy A33"),
    (r"samsunggalaxy\s*a\s*26\s*5g", "Samsung Galaxy A26 5G"),
    (r"samsunggalaxy\s*a\s*25\s*5g", "Samsung Galaxy A25 5G"),
    (r"samsunggalaxy\s*a\s*25", "Samsung Galaxy A25"),
    (r"samsunggalaxy\s*a\s*24\s*5g", "Samsung Galaxy A24 5G"),
    (r"samsunggalaxy\s*a\s*24", "Samsung Galaxy A24"),
    (r"samsunggalaxy\s*a\s*23\s*5g", "Samsung Galaxy A23 5G"),
    (r"samsunggalaxy\s*a\s*23", "Samsung Galaxy A23"),
    (r"samsunggalaxy\s*a\s*17", "Samsung Galaxy A17"),
    (r"samsunggalaxy\s*a\s*16\s*5g", "Samsung Galaxy A16 5G"),
    (r"samsunggalaxy\s*a\s*16", "Samsung Galaxy A16"),
    (r"samsunggalaxy\s*a\s*15\s*5g", "Samsung Galaxy A15 5G"),
    (r"samsunggalaxy\s*a\s*15", "Samsung Galaxy A15"),
    (r"samsunggalaxy\s*a\s*14\s*5g", "Samsung Galaxy A14 5G"),
    (r"samsunggalaxy\s*a\s*14", "Samsung Galaxy A14"),
    (r"samsunggalaxy\s*a\s*13", "Samsung Galaxy A13"),
    (r"samsunggalaxy\s*a\s*05", "Samsung Galaxy A05s"),
    (r"samsunggalaxy\s*a\s*71", "Samsung Galaxy A71"),
    (r"samsunggalaxy\s*m\s*35", "Samsung Galaxy M35"),
]
MODELS.extend(SAMSUNG_S)
MODELS.extend(SAMSUNG_A)
# Samsung short forms
SAMSUNG_SHORT = [
    # "galaxy a54 5g", "galaxy s24 fe"
    (r"\bgalaxy\s+a\s*56\s*5g\b", "Samsung Galaxy A56 5G"),
    (r"\bgalaxy\s+a\s*55\s*5g\b", "Samsung Galaxy A55 5G"),
    (r"\bgalaxy\s+a\s*55\b", "Samsung Galaxy A55"),
    (r"\bgalaxy\s+a\s*54\s*5g\b", "Samsung Galaxy A54 5G"),
    (r"\bgalaxy\s+a\s*54\b", "Samsung Galaxy A54"),
    (r"\bgalaxy\s+a\s*53\s*5g\b", "Samsung Galaxy A53 5G"),
    (r"\bgalaxy\s+a\s*53\b", "Samsung Galaxy A53"),
    (r"\bgalaxy\s+a\s*36\s*5g\b", "Samsung Galaxy A36 5G"),
    (r"\bgalaxy\s+a\s*35\s*5g\b", "Samsung Galaxy A35 5G"),
    (r"\bgalaxy\s+a\s*35\b", "Samsung Galaxy A35"),
    (r"\bgalaxy\s+a\s*34\s*5g\b", "Samsung Galaxy A34 5G"),
    (r"\bgalaxy\s+a\s*34\b", "Samsung Galaxy A34"),
    (r"\bgalaxy\s+a\s*25\s*5g\b", "Samsung Galaxy A25 5G"),
    (r"\bgalaxy\s+a\s*25\b", "Samsung Galaxy A25"),
    (r"\bgalaxy\s+a\s*24\s*5g\b", "Samsung Galaxy A24 5G"),
    (r"\bgalaxy\s+a\s*24\b", "Samsung Galaxy A24"),
    (r"\bgalaxy\s+a\s*23\s*5g\b", "Samsung Galaxy A23 5G"),
    (r"\bgalaxy\s+a\s*23\b", "Samsung Galaxy A23"),
    (r"\bgalaxy\s+a\s*16\s*5g\b", "Samsung Galaxy A16 5G"),
    (r"\bgalaxy\s+a\s*16\b", "Samsung Galaxy A16"),
    (r"\bgalaxy\s+a\s*15\s*5g\b", "Samsung Galaxy A15 5G"),
    (r"\bgalaxy\s+a\s*15\b", "Samsung Galaxy A15"),
    (r"\bgalaxy\s+a\s*14\s*5g\b", "Samsung Galaxy A14 5G"),
    (r"\bgalaxy\s+a\s*14\b", "Samsung Galaxy A14"),
    (r"\bgalaxy\s+a\s*13\b", "Samsung Galaxy A13"),
    (r"\bgalaxy\s+s\s*25\s*fe\b", "Samsung Galaxy S25 FE"),
    (r"\bgalaxy\s+s\s*25\b", "Samsung Galaxy S25"),
    (r"\bgalaxy\s+s\s*24\s*fe\b", "Samsung Galaxy S24 FE"),
    (r"\bgalaxy\s+s\s*24\b", "Samsung Galaxy S24"),
    (r"\bgalaxy\s+s\s*23\s*fe\b", "Samsung Galaxy S23 FE"),
    (r"\bgalaxy\s+s\s*23\b", "Samsung Galaxy S23"),
    (r"\bgalaxy\s+s\s*22\b", "Samsung Galaxy S22"),
    (r"\bgalaxy\s+s\s*21\s*fe\b", "Samsung Galaxy S21 FE"),
    (r"\bgalaxy\s+s\s*21\b", "Samsung Galaxy S21"),
    (r"\bgalaxy\s+s\s*20\s*fe\b", "Samsung Galaxy S20 FE"),
    (r"\bgalaxy\s+s\s*20\b", "Samsung Galaxy S20"),
    (r"\bgalaxy\s+s\s*10\b", "Samsung Galaxy S10"),
    (r"\bgalaxy\s+s\s*9\b", "Samsung Galaxy S9"),
    (r"\bgalaxy\s+m\s*35\b", "Samsung Galaxy M35"),
    # "s24fe", "s24 fe", "s23fe"
    (r"\bs24\s*fe\b", "Samsung Galaxy S24 FE"),
    (r"\bs24fe\b", "Samsung Galaxy S24 FE"),
    (r"\bs23\s*fe\b", "Samsung Galaxy S23 FE"),
    (r"\bs23fe\b", "Samsung Galaxy S23 FE"),
    (r"\bs22\b", "Samsung Galaxy S22"),
    (r"\bs21\s*fe\b", "Samsung Galaxy S21 FE"),
    (r"\bs21\b", "Samsung Galaxy S21"),
    (r"\bs20\s*fe\b", "Samsung Galaxy S20 FE"),
    (r"\bs20\b", "Samsung Galaxy S20"),
    # "a54 5g", "a54", "a34 5g" etc
    (r"\ba56\s*5g\b", "Samsung Galaxy A56 5G"),
    (r"\ba55\s*5g\b", "Samsung Galaxy A55 5G"),
    (r"\ba55\b", "Samsung Galaxy A55"),
    (r"\ba54\s*5g\b", "Samsung Galaxy A54 5G"),
    (r"\ba54\b", "Samsung Galaxy A54"),
    (r"\ba53\s*5g\b", "Samsung Galaxy A53 5G"),
    (r"\ba53\b", "Samsung Galaxy A53"),
    (r"\ba36\s*5g\b", "Samsung Galaxy A36 5G"),
    (r"\ba35\s*5g\b", "Samsung Galaxy A35 5G"),
    (r"\ba35\b", "Samsung Galaxy A35"),
    (r"\ba34\s*5g\b", "Samsung Galaxy A34 5G"),
    (r"\ba34\b", "Samsung Galaxy A34"),
    (r"\ba25\s*5g\b", "Samsung Galaxy A25 5G"),
    (r"\ba25\b", "Samsung Galaxy A25"),
    (r"\ba24\s*5g\b", "Samsung Galaxy A24 5G"),
    (r"\ba24\b", "Samsung Galaxy A24"),
    (r"\ba23\s*5g\b", "Samsung Galaxy A23 5G"),
    (r"\ba23\b", "Samsung Galaxy A23"),
    (r"\ba16\s*5g\b", "Samsung Galaxy A16 5G"),
    (r"\ba16\b", "Samsung Galaxy A16"),
    (r"\ba15\s*5g\b", "Samsung Galaxy A15 5G"),
    (r"\ba15\b", "Samsung Galaxy A15"),
    (r"\ba14\s*5g\b", "Samsung Galaxy A14 5G"),
    (r"\ba14\b", "Samsung Galaxy A14"),
    (r"\ba13\b", "Samsung Galaxy A13"),
    # "samsung 54 5g", "samsung 14" (number-only after samsung)
    (r"\bsamsung\s*54\s*5g\b", "Samsung Galaxy A54 5G"),
    (r"\bsamsung\s*54\b", "Samsung Galaxy A54"),
    (r"\bsamsung\s*34\s*5g\b", "Samsung Galaxy A34 5G"),
    (r"\bsamsung\s*34\b", "Samsung Galaxy A34"),
    (r"\bsamsung\s*24\s*fe\b", "Samsung Galaxy S24 FE"),
    (r"\bsamsung\s*24\b", "Samsung Galaxy S24"),
    (r"\bsamsung\s*23\s*fe\b", "Samsung Galaxy S23 FE"),
    (r"\bsamsung\s*23\b", "Samsung Galaxy S23"),
    (r"\bsamsung\s*14\b", "Samsung Galaxy A14"),
    (r"\bsamsung\s*25\b", "Samsung Galaxy S25"),
    (r"\bsamsung\s*9\b", "Samsung Galaxy S9"),
]
MODELS.extend(SAMSUNG_SHORT)
MODELS.extend([
    (r"samsunggalaxy", "Samsung Galaxy"),
    (r"samsung", "Samsung"),
])

# Xiaomi
XIAOMI = [
    (r"xiaomiredmi\s*note\s*15\s*pro\s*plus\s*5g", "Xiaomi Redmi Note 15 Pro+ 5G"),
    (r"xiaomiredmi\s*note\s*15\s*pro\s*5g", "Xiaomi Redmi Note 15 Pro 5G"),
    (r"xiaomiredmi\s*note\s*15\s*pro", "Xiaomi Redmi Note 15 Pro"),
    (r"xiaomiredmi\s*note\s*15", "Xiaomi Redmi Note 15"),
    (r"xiaomiredmi\s*note\s*13\s*pro", "Xiaomi Redmi Note 13 Pro"),
    (r"xiaomiredmi\s*note\s*13", "Xiaomi Redmi Note 13"),
    (r"xiaomiredmi\s*15\s*5g", "Xiaomi Redmi 15 5G"),
    (r"xiaomiredmi\s*15\s*c", "Xiaomi Redmi 15C"),
    (r"xiaomiredmi\s*15", "Xiaomi Redmi 15"),
    (r"xiaomiredmi\s*a5", "Xiaomi Redmi A5"),
    (r"xiaomiredmi", "Xiaomi Redmi"),
    (r"xiaomi\s*15\s*t\s*pro", "Xiaomi 15T Pro"),
    (r"xiaomi\s*15\s*t", "Xiaomi 15T"),
    (r"xiaomi\s*15\s*c\s*5g", "Xiaomi 15C 5G"),
    (r"xiaomi\s*15", "Xiaomi 15"),
    (r"xiaomi\s*13\s*t\s*pro", "Xiaomi 13T Pro"),
    (r"xiaomi\s*13\s*t", "Xiaomi 13T"),
    (r"xiaomi\s*13\s*pro", "Xiaomi 13 Pro"),
    (r"xiaomi\s*13", "Xiaomi 13"),
    (r"xiaomi", "Xiaomi"),
]
MODELS.extend(XIAOMI)

# Motorola
MOTO = [
    (r"motorolaedge\s*60\s*pro", "Motorola Edge 60 Pro"),
    (r"motorolaedge\s*60", "Motorola Edge 60"),
    (r"motorolaedge\s*40", "Motorola Edge 40"),
    (r"motorola\s*g75\s*5g", "Motorola G75 5G"),
    (r"motorola\s*g54\s*5g", "Motorola G54 5G"),
    (r"motorola\s*g15", "Motorola G15"),
    (r"motorola", "Motorola"),
    (r"\bedge\s*60\s*pro\b", "Motorola Edge 60 Pro"),
    (r"\bedge\s*60\b", "Motorola Edge 60"),
]
MODELS.extend(MOTO)

# Other brands
OTHERS = [
    (r"huaweinova\s*13\s*pro", "Huawei Nova 13 Pro"),
    (r"huawei", "Huawei"),
    (r"honormagic\s*[87]\s*pro", "Honor Magic Pro"),
    (r"honor", "Honor"),
    (r"oppofind\s*x\s*9\s*pro", "Oppo Find X9 Pro"),
    (r"oppofind\s*x\s*3\s*pro", "Oppo Find X3 Pro"),
    (r"oppofind\s*x\s*2\s*neo", "Oppo Find X2 Neo"),
    (r"oppo", "Oppo"),
    (r"\bfind\s*x\s*9\s*pro\b", "Oppo Find X9 Pro"),
    (r"\bfind\s*x\s*3\s*pro\b", "Oppo Find X3 Pro"),
    (r"oneplus\s*15", "OnePlus 15"),
    (r"oneplus", "OnePlus"),
    (r"vivo\s*v50\s*lite", "Vivo V50 Lite"),
    (r"vivo", "Vivo"),
    (r"cmfphone\s*1", "CMF Phone 1"),
    (r"cmf", "CMF"),
    (r"fairphone\s*5", "Fairphone 5"),
    (r"fairphone", "Fairphone"),
]
MODELS.extend(OTHERS)
# Bare iPhone numbers (no "iphone" prefix): "15 pro", "13 pro max", "12 pro"
BARE_IPHONE = [
    (r"\b17\s*pro\s*max\b", "iPhone 17 Pro Max"),
    (r"\b17\s*pro\b", "iPhone 17 Pro"),
    (r"\b17\b", "iPhone 17"),
    (r"\b16\s*pro\s*max\b", "iPhone 16 Pro Max"),
    (r"\b16\s*pro\b", "iPhone 16 Pro"),
    (r"\b16\s*plus\b", "iPhone 16 Plus"),
    (r"\b16\s*e\b", "iPhone 16e"),
    (r"\b16\b", "iPhone 16"),
    (r"\b15\s*pro\s*max\b", "iPhone 15 Pro Max"),
    (r"\b15\s*pro\b", "iPhone 15 Pro"),
    (r"\b15\s*plus\b", "iPhone 15 Plus"),
    (r"\b15\b", "iPhone 15"),
    (r"\b14\s*pro\s*max\b", "iPhone 14 Pro Max"),
    (r"\b14\s*pro\b", "iPhone 14 Pro"),
    (r"\b14\s*plus\b", "iPhone 14 Plus"),
    (r"\b14\b", "iPhone 14"),
    (r"\b13\s*pro\s*max\b", "iPhone 13 Pro Max"),
    (r"\b13\s*pro\b", "iPhone 13 Pro"),
    (r"\b13\s*mini\b", "iPhone 13 mini"),
    (r"\b13\b", "iPhone 13"),
    (r"\b12\s*pro\s*max\b", "iPhone 12 Pro Max"),
    (r"\b12\s*pro\b", "iPhone 12 Pro"),
    (r"\b12\s*mini\b", "iPhone 12 mini"),
    (r"\b12\b", "iPhone 12"),
    (r"\b11\s*pro\s*max\b", "iPhone 11 Pro Max"),
    (r"\b11\s*pro\b", "iPhone 11 Pro"),
    (r"\b11\b", "iPhone 11"),
]
MODELS.extend(BARE_IPHONE)

# "galaxys" merged patterns (when "galaxy s" gets merged without space)
GALAXYS_MERGED = [
    (r"\bgalaxys25\s*fe\b", "Samsung Galaxy S25 FE"),
    (r"\bgalaxys25\b", "Samsung Galaxy S25"),
    (r"\bgalaxys24\s*fe\b", "Samsung Galaxy S24 FE"),
    (r"\bgalaxys24\b", "Samsung Galaxy S24"),
    (r"\bgalaxys23\s*fe\b", "Samsung Galaxy S23 FE"),
    (r"\bgalaxys23\b", "Samsung Galaxy S23"),
    (r"\bgalaxys22\b", "Samsung Galaxy S22"),
    (r"\bgalaxys21\s*fe\b", "Samsung Galaxy S21 FE"),
    (r"\bgalaxys21\b", "Samsung Galaxy S21"),
    (r"\bgalaxys20\s*fe\b", "Samsung Galaxy S20 FE"),
    (r"\bgalaxys20\b", "Samsung Galaxy S20"),
    (r"\bgalaxys10\b", "Samsung Galaxy S10"),
    (r"\bgalaxys9\b", "Samsung Galaxy S9"),
]
MODELS.extend(GALAXYS_MERGED)

# "galaxya" merged patterns (when "galaxy a" gets merged without space)
GALAXYA_MERGED = [
    (r"\bgalaxya56\s*5g\b", "Samsung Galaxy A56 5G"),
    (r"\bgalaxya55\s*5g\b", "Samsung Galaxy A55 5G"),
    (r"\bgalaxya55\b", "Samsung Galaxy A55"),
    (r"\bgalaxya54\s*5g\b", "Samsung Galaxy A54 5G"),
    (r"\bgalaxya54\b", "Samsung Galaxy A54"),
    (r"\bgalaxya53\s*5g\b", "Samsung Galaxy A53 5G"),
    (r"\bgalaxya53\b", "Samsung Galaxy A53"),
    (r"\bgalaxya36\s*5g\b", "Samsung Galaxy A36 5G"),
    (r"\bgalaxya35\s*5g\b", "Samsung Galaxy A35 5G"),
    (r"\bgalaxya35\b", "Samsung Galaxy A35"),
    (r"\bgalaxya34\s*5g\b", "Samsung Galaxy A34 5G"),
    (r"\bgalaxya34\b", "Samsung Galaxy A34"),
    (r"\bgalaxya25\s*5g\b", "Samsung Galaxy A25 5G"),
    (r"\bgalaxya25\b", "Samsung Galaxy A25"),
    (r"\bgalaxya24\s*5g\b", "Samsung Galaxy A24 5G"),
    (r"\bgalaxya24\b", "Samsung Galaxy A24"),
    (r"\bgalaxya23\s*5g\b", "Samsung Galaxy A23 5G"),
    (r"\bgalaxya23\b", "Samsung Galaxy A23"),
    (r"\bgalaxya16\s*5g\b", "Samsung Galaxy A16 5G"),
    (r"\bgalaxya16\b", "Samsung Galaxy A16"),
    (r"\bgalaxya15\s*5g\b", "Samsung Galaxy A15 5G"),
    (r"\bgalaxya15\b", "Samsung Galaxy A15"),
    (r"\bgalaxya14\s*5g\b", "Samsung Galaxy A14 5G"),
    (r"\bgalaxya14\b", "Samsung Galaxy A14"),
    (r"\bgalaxya13\b", "Samsung Galaxy A13"),
    (r"\bgalaxyam35\b", "Samsung Galaxy M35"),
]
MODELS.extend(GALAXYA_MERGED)


# ── Model finder ──
def find_model(text):
    """Find phone model in a search term. Returns (model_name, remaining_text).
    Uses the LONGEST match to avoid leaving model fragments in remainder."""
    t = norm(text)
    best_match = None
    best_len = 0
    for pat, name in MODELS:
        for m in re.finditer(pat, t):
            match_len = m.end() - m.start()
            if match_len > best_len:
                best_len = match_len
                best_match = (m, name)
    if best_match:
        m, name = best_match
        before = t[:m.start()].strip()
        after = t[m.end():].strip()
        remainder = (before + " " + after).strip()
        return name, remainder
    return None, text.strip()

# ── Attribute extraction patterns ──
ATTRS = {
    "Hülle": [r"\bhülle\b", r"\bhuelle\b", r"\bcase\b", r"\bcover\b",
              r"\bhandyhülle\b", r"\bhandycase\b", r"\bhandycover\b",
              r"\bschutzhülle\b", r"\bschutzcover\b", r"\bschale\b",
              r"\betui\b", r"\bbackcover\b", r"\btelefonhülle\b",
              r"\bvollhülle\b", r"\boutdoorhülle\b", r"\bpanzerhülle\b",
              r"\bhardcase\b", r"\bhardcover\b", r"\bbumper\b",
              r"\bsilikonhülle\b", r"\bmetallhülle\b", r"\bmetal\s*case\b",
              r"\balu\s*case\b", r"\bcarbon\s*hülle\b", r"\bflipcase\b",
              r"\brugged\s*case\b", r"\bhandytasche\b", r"\bmilitary\b",
              r"\bganzkörperhülle\b", r"\brundumschutz\b", r"\bfullbody\b",
              r"\bwasserdicht\b", r"\bwasserfest\b", r"\bwaterproof\b",
              r"\bkomplettschutz\b", r"\bstaubschutz\b", r"\bdustproof\b",
              r"\bdurchsichtig\b", r"\btransparent\b", r"\bstoßfest\b",
              r"\bshockproof\b", r"\bsturzsicher\b", r"\brobust\b",
              r"\bstabil\b", r"\barmored\b", r"\bkratzfest\b",
              r"\bdünn\b", r"\bsilikon\b", r"\bsilicone\b",
              r"\bleder\b", r"\bholz\b", r"\borganizer\b", r"\bklappbar\b"],
    "Ständer": [r"\bständer\b", r"\bstaender\b", r"\bstand\b",
                r"\bstandfuß\b", r"\bstandfuss\b", r"\bkickstand\b",
                r"\baufsteller\b", r"\baufstellen\b", r"\bstehend\b",
                r"\bhinstellen\b", r"\bstütze\b", r"\bhalterung\b",
                r"\bhalter\b", r"\bfingerhalter\b", r"\bfingerhalterung\b",
                r"\bpopsocket\b", r"\bgriff\b", r"\bringständer\b",
                r"\bstandring\b", r"\bringhalter\b", r"\bringhalterung\b",
                r"\bdrehständer\b", r"\bdrehbar\b", r"\bdrehbare\b",
                r"\b360\s*grad\b", r"\b360°\b", r"\b360grad\b",
                r"\b360\s*degree\b", r"\brotating\b", r"\b180\s*degree\b",
                r"\bintegriertem\s*ständer\b", r"\bstand\s*case\b",
                r"\bstanding\b", r"\bständerhülle\b", r"\bstand\s*hülle\b",
                r"\bpopup\b", r"\bpop\s*up\b", r"\bverstellbarem\s*kickstand\b",
                r"\badjustable\s*stand\b", r"\bdual\s*stand\b"],
    "MagSafe": [r"\bmagsafe\b", r"\bmag\s*safe\b", r"\bmag\s*save\b",
                r"\bmagnet\b", r"\bmagnetisch\b", r"\bmagnetic\b",
                r"\bmagnetische\b", r"\bmagnetring\b", r"\bmagnethülle\b",
                r"\bmagnetic\s*case\b", r"\bmagnethalter\b",
                r"\bmagsafehülle\b", r"\bmagsafe-hülle\b"],
    "Ring": [r"\bring\b", r"\bringe\b", r"\bringhalter\b",
             r"\bringhalterung\b", r"\bdoppelring\b", r"\bdrehbare\s*ring\b",
             r"\bdrehbarer\s*ring\b", r"\bringke\b"],
    "Kameraschutz": [r"\bkameraschutz\b", r"\bkamera\s*schutz\b",
                     r"\bkameraabdeckung\b", r"\bcamera\s*protection\b"],
    "Displayschutz": [r"\bdisplayschutz\b", r"\bpanzerglas\b",
                      r"\bpanzerfolie\b", r"\bschutzfolie\b", r"\bschutzglas\b",
                      r"\bscreen\s*protector\b", r"\bdisplayschutzfolie\b",
                      r"\bdisplay\s*folie\b", r"\bhandyfolie\b",
                      r"\bglass\s*guard\b", r"\bprivacy\s*glass\b",
                      r"\bsichtschutz\b", r"\b9h\b", r"\bgehärtetem\s*glas\b"],
    "Kartenfach": [r"\bkartenfach\b", r"\bkartenfächer\b",
                   r"\bcard\s*holder\b", r"\bcardholder\b", r"\bkartenhalter\b"],
    "Band": [r"\bmit\s*band\b", r"\bhandband\b", r"\bhandschlaufe\b",
             r"\bmit\s*kette\b", r"\bhandykette\b", r"\bschnur\b"],
    "Induktion": [r"\binduktives\s*laden\b", r"\binductive\s*charging\b",
                  r"\bwireless\s*charging\b", r"\bkabelloses\s*laden\b",
                  r"\bladefunktion\b", r"\bqi\b", r"\bpower\s*bank\b",
                  r"\bpowerbank\b", r"\bakku\b", r"\bmit\s*induktion\b"],
    "Outdoor": [r"\boutdoor\b", r"\boutdor\b", r"\bmilitary\b",
                r"\bmilitär\b", r"\bmilitärisch\b", r"\bstoßfest\b",
                r"\bshockproof\b", r"\bsturzsicher\b", r"\brobust\b",
                r"\barmored\b", r"\bwasserdicht\b", r"\bwasserfest\b",
                r"\bwaterproof\b", r"\bstaubschutz\b", r"\bdustproof\b",
                r"\bdust\s*plug\b", r"\brugged\b", r"\btank\s*case\b",
                r"\bpanzer\b", r"\bbaustelle\b"],
    "Farbe": [r"\bschwarz\b", r"\bweiß\b", r"\bweiss\b", r"\brot\b",
              r"\bblau\b", r"\bgrün\b", r"\bgruen\b", r"\bgelb\b",
              r"\borange\b", r"\brosa\b", r"\bpink\b", r"\blila\b",
              r"\bgrau\b", r"\bgold\b", r"\bsilber\b", r"\bviolett\b",
              r"\bhellblau\b", r"\bdunkel\b", r"\bneon\b", r"\bglitzer\b",
              r"\bglitter\b", r"\bweinrot\b", r"\bmocca\b", r"\beisblau\b",
              r"\bkamoflage\b", r"\bcamouflage\b", r"\btitan\b"],
    "Marke": [r"\besr\b", r"\bspigen\b", r"\btorras\b", r"\botterbox\b",
              r"\buag\b", r"\bcaseology\b", r"\bnillkin\b", r"\bsupcase\b",
              r"\btuvror\b", r"\bdexnor\b", r"\bcasekoo\b", r"\bcasebus\b",
              r"\bflolab\b", r"\bmiracase\b", r"\bhaonande\b", r"\bmasopsk\b",
              r"\bsmacase\b", r"\bsuritch\b", r"\bpuyateya\b", r"\bdasfond\b",
              r"\bfntcase\b", r"\brolemodel\b", r"\barc\s*pulse\b",
              r"\bwhite\s*dome\b", r"\bstone\s*island\b", r"\bapple\b",
              r"\boriginal\b", r"\bferrari\b", r"\bnike\b", r"\bbvb\b",
              r"\bamg\b", r"\betsy\b", r"\bamazon\b", r"\btarget\b",
              r"\bhyped\b", r"\baoui\b", r"\baesthetic\b", r"\banime\b",
              r"\bsnoopy\b", r"\bresident\s*evil\b", r"\bchoumi\b",
              r"\blemaxelers\b", r"\banlalish\b", r"\bidioon\b",
              r"\bmaskica\b", r"\bmetolius\b", r"\bpanda\b", r"\bschrulle\b",
              r"\bwellig\b", r"\bhdqicase\b", r"\bapiker\b",
              r"\bsteelguard\b", r"\bshields\s*up\b"],
    "Material": [r"\bsilikon\b", r"\bsilicone\b", r"\bleder\b",
                 r"\bmetall\b", r"\bmetal\b", r"\baluminium\b",
                 r"\baluminum\b", r"\balu\b", r"\bcarbon\b", r"\bholz\b",
                 r"\bwood\b", r"\bkunststoff\b", r"\bplastic\b", r"\bmatt\b",
                 r"\bgalvanisiert\b", r"\brutschfest\b", r"\bmaschen\b"],
    "Design": [r"\bdünn\b", r"\bdünne\b", r"\bultra\s*dünn\b",
               r"\bultra\s*leicht\b", r"\bslim\b", r"\bthin\b",
               r"\bluxury\b", r"\belegant\b", r"\bmodern\b", r"\bdesign\b",
               r"\bästhetisch\b", r"\baesthetic\b", r"\bcoole\b",
               r"\bmotiv\b", r"\bglitzer\b", r"\bglitter\b", r"\bsparkly\b",
               r"\bblumen\b", r"\bwellen\b", r"\bwellig\b", r"\bmuster\b",
               r"\bbunt\b", r"\bfarbig\b", r"\bunsichtbar\b",
               r"\binvisible\b", r"\bklar\b", r"\bmatt\b"],
    "Zubehör": [r"\bzubehör\b", r"\baccessories\b", r"\baccessory\b"],
    "Montage": [r"\b2\s*phase\b", r"\bzweiteilig\b", r"\b2\s*stück\b",
                r"\b2\s*teilig\b", r"\bset\b"],
}

def extract_attrs(remainder):
    """Extract attributes from the non-model part of a search term."""
    found = {}
    t = remainder.lower()
    for attr_name, patterns in ATTRS.items():
        for pat in patterns:
            if re.search(pat, t):
                found[attr_name] = True
                break
    return list(found.keys())

# ── Main processing ──
print("Loading Excel...")
wb = openpyxl.load_workbook(SRC)
ws = wb["广告搜索词"]

rows = []
for row in ws.iter_rows(min_row=3, max_row=ws.max_row, values_only=True):
    term = row[1]  # Column B
    if not term or not str(term).strip():
        continue
    term_orig = str(term).strip()
    model, remainder = find_model(term_orig)
    attrs = extract_attrs(remainder)
    rows.append({
        "original": term_orig,
        "model": model or "",
        "remainder": remainder,
        "attrs": attrs,
    })

print(f"Processed {len(rows)} rows")

# ── Build keyword library ──
# Group by attribute combination, create templates with {MODEL}
combo_map = defaultdict(lambda: defaultdict(list))
for r in rows:
    if not r["model"]:
        continue
    attrs_key = tuple(sorted(r["attrs"]))
    combo_map[r["model"]][attrs_key].append(r["original"])

keyword_library = defaultdict(list)
for model, combos in combo_map.items():
    for attrs, terms in combos.items():
        for t in terms:
            t_norm = norm(t)
            for pat, name in MODELS:
                m = re.search(pat, t_norm)
                if m and name == model:
                    # Replace matched portion with {MODEL}
                    template = t[:m.start()] + "{MODEL}" + t[m.end():]
                    template = " ".join(template.split())
                    keyword_library[attrs].append(template)
                    break

# Deduplicate and filter out templates from generic models
GENERIC_MODELS = {
    "Samsung", "Samsung Galaxy", "iPhone", "Google Pixel", "Xiaomi", "Xiaomi Redmi",
    "Motorola", "Huawei", "Honor", "Oppo", "OnePlus", "Vivo", "CMF", "Fairphone",
    "Honor Magic Pro", "Oppo Find X Pro",
}

# Rebuild keyword_library only from specific models
keyword_library = defaultdict(list)
for model, combos in combo_map.items():
    if model in GENERIC_MODELS:
        continue  # Skip generic models
    for attrs, terms in combos.items():
        for t in terms:
            t_norm = norm(t)
            best_m = None
            best_len = 0
            for pat, name in MODELS:
                if name == model:
                    for m in re.finditer(pat, t_norm):
                        match_len = m.end() - m.start()
                        if match_len > best_len:
                            best_len = match_len
                            best_m = m
            if best_m:
                # Use normalized text for template to ensure correct positions
                template = t_norm[:best_m.start()] + "{MODEL}" + t_norm[best_m.end():]
                template = " ".join(template.split())
                remainder_lower = (t_norm[:best_m.start()] + " " + t_norm[best_m.end():]).lower()
                if not re.search(r'\b(galaxy|pixel|iphone|samsung|xiaomi|motorola|huawei|honor|oppo|oneplus|vivo|redmi|edge|nova|magic|find|cmf|fairphone)\b', remainder_lower):
                    keyword_library[attrs].append(template)

for attrs in keyword_library:
    keyword_library[attrs] = sorted(set(keyword_library[attrs]))

# ── Output 1: Annotated Excel ──
print("Writing annotated Excel...")
wb_out = openpyxl.Workbook()
ws_out = wb_out.active
ws_out.title = "搜索词分析"
for c, h in enumerate(["原始搜索词", "识别型号", "剩余文本", "词根属性"], 1):
    ws_out.cell(row=1, column=c, value=h)
for i, r in enumerate(rows, 2):
    ws_out.cell(row=i, column=1, value=r["original"])
    ws_out.cell(row=i, column=2, value=r["model"])
    ws_out.cell(row=i, column=3, value=r["remainder"])
    ws_out.cell(row=i, column=4, value=", ".join(r["attrs"]))

out_xlsx = OUT / "DE搜索词_词根属性分析.xlsx"
wb_out.save(out_xlsx)
print(f"  -> {out_xlsx}")

# ── Output 2: Keyword library JSON ──
lib_data = {}
for attrs, templates in sorted(keyword_library.items()):
    key = " + ".join(attrs) if attrs else "通用"
    lib_data[key] = templates

with open(OUT / "关键词库.json", "w", encoding="utf-8") as f:
    json.dump(lib_data, f, ensure_ascii=False, indent=2)
print(f"  -> {OUT / '关键词库.json'}")

# ── Output 3: Readable keyword library text ──
with open(OUT / "关键词库.txt", "w", encoding="utf-8") as f:
    f.write("=" * 80 + "\n")
    f.write("DE Amazon 手机壳关键词库\n")
    f.write("使用说明：将 {MODEL} 替换为具体型号即可生成投放关键词\n")
    f.write("型号规范：iPhone 16 Pro Max, Google Pixel 9 Pro XL, Samsung Galaxy S24 FE 等\n")
    f.write("注意：消费者常将型号连写，如 \"iphone 16pro\" → 对应 {MODEL} = iPhone 16 Pro\n")
    f.write("=" * 80 + "\n\n")

    for attrs, templates in sorted(keyword_library.items()):
        key = " + ".join(attrs) if attrs else "通用"
        f.write(f"\n## {key}\n")
        f.write(f"  模板数: {len(templates)}\n\n")
        for t in templates:
            f.write(f"  {t}\n")

print(f"  -> {OUT / '关键词库.txt'}")

# ── Output 4: Model-specific keyword sheets ──
print("Writing model-specific keyword sheets...")
wb_models = openpyxl.Workbook()
# Remove default sheet
wb_models.remove(wb_models.active)

# Group templates by model from original data
model_templates = defaultdict(set)
for r in rows:
    if not r["model"]:
        continue
    t_norm = norm(r["original"])
    for pat, name in MODELS:
        m = re.search(pat, t_norm)
        if m and name == r["model"]:
            template = r["original"][:m.start()] + "{MODEL}" + r["original"][m.end():]
            template = " ".join(template.split())
            model_templates[r["model"]].add(template)
            break

# Create one sheet per major model
major_models = sorted(model_templates.keys(), key=lambda x: -len(model_templates[x]))[:30]
for model in major_models:
    ws_m = wb_models.create_sheet(title=model[:31])  # Excel sheet name limit
    ws_m.cell(row=1, column=1, value=f"型号: {model}")
    ws_m.cell(row=1, column=2, value=f"共 {len(model_templates[model])} 个模板")
    ws_m.cell(row=2, column=1, value="模板关键词")
    ws_m.cell(row=2, column=2, value="替换后示例")
    for i, t in enumerate(sorted(model_templates[model]), 3):
        ws_m.cell(row=i, column=1, value=t)
        ws_m.cell(row=i, column=2, value=t.replace("{MODEL}", model))

out_models = OUT / "各型号关键词模板.xlsx"
wb_models.save(out_models)
print(f"  -> {out_models}")

# ── Summary ──
print("\n" + "=" * 60)
print("统计摘要")
print("=" * 60)
print(f"总搜索词数: {len(rows)}")
matched = sum(1 for r in rows if r["model"])
print(f"识别到型号: {matched} ({matched/len(rows)*100:.1f}%)")
print(f"未识别型号: {len(rows) - matched}")
print(f"关键词库属性组合数: {len(keyword_library)}")
total_templates = sum(len(v) for v in keyword_library.values())
print(f"关键词库模板总数: {total_templates}")

# Top attribute combos
attr_counts = Counter()
for r in rows:
    if r["attrs"]:
        attr_counts[", ".join(r["attrs"])] += 1
print("\n最常见属性组合 (Top 15):")
for combo, count in attr_counts.most_common(15):
    print(f"  {combo}: {count}")

# Top models
model_counts = Counter(r["model"] for r in rows if r["model"])
print(f"\n型号分布 (Top 20):")
for model, count in model_counts.most_common(20):
    print(f"  {model}: {count}")

# Unmatched samples
unmatched = [r for r in rows if not r["model"]]
if unmatched:
    print(f"\n未识别搜索词示例 (前20条):")
    for r in unmatched[:20]:
        print(f"  [{r['original']}]")

print("\nDone!")
