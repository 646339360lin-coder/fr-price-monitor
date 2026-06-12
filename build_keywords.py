#!/usr/bin/env python3
"""Extract root attributes from DE Amazon search terms and build a keyword library."""
import re, json, openpyxl
from collections import defaultdict, Counter
from pathlib import Path

SRC = Path("/Users/hosen/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/7C21D360DBFA836768191953082E98DB/Caches/Files/2026-06/781fd32262d3ebf3a9762247d5be4003/DE广告搜索词近365天.xlsx")
OUT = Path("/Users/hosen/Documents/Amazon/keyword_library")
OUT.mkdir(parents=True, exist_ok=True)

# ── Model detection patterns ──
MODELS = [
    # iPhone (ordered most-specific first)
    (r"i\s*phone\s*17\s*pro\s*max", "iPhone 17 Pro Max"),
    (r"i\s*phone\s*17\s*pro", "iPhone 17 Pro"),
    (r"i\s*phone\s*17", "iPhone 17"),
    (r"i\s*phone\s*16\s*pro\s*max", "iPhone 16 Pro Max"),
    (r"i\s*phone\s*16\s*pro", "iPhone 16 Pro"),
    (r"i\s*phone\s*16\s*plus", "iPhone 16 Plus"),
    (r"i\s*phone\s*16\s*e", "iPhone 16e"),
    (r"i\s*phone\s*16", "iPhone 16"),
    (r"i\s*phone\s*15\s*pro\s*max", "iPhone 15 Pro Max"),
    (r"i\s*phone\s*15\s*pro", "iPhone 15 Pro"),
    (r"i\s*phone\s*15\s*plus", "iPhone 15 Plus"),
    (r"i\s*phone\s*15", "iPhone 15"),
    (r"i\s*phone\s*14\s*pro\s*max", "iPhone 14 Pro Max"),
    (r"i\s*phone\s*14\s*pro", "iPhone 14 Pro"),
    (r"i\s*phone\s*14\s*plus", "iPhone 14 Plus"),
    (r"i\s*phone\s*14", "iPhone 14"),
    (r"i\s*phone\s*13\s*pro\s*max", "iPhone 13 Pro Max"),
    (r"i\s*phone\s*13\s*pro", "iPhone 13 Pro"),
    (r"i\s*phone\s*13\s*mini", "iPhone 13 mini"),
    (r"i\s*phone\s*13", "iPhone 13"),
    (r"i\s*phone\s*12\s*pro\s*max", "iPhone 12 Pro Max"),
    (r"i\s*phone\s*12\s*pro", "iPhone 12 Pro"),
    (r"i\s*phone\s*12\s*mini", "iPhone 12 mini"),
    (r"i\s*phone\s*12", "iPhone 12"),
    (r"i\s*phone\s*11\s*pro\s*max", "iPhone 11 Pro Max"),
    (r"i\s*phone\s*11\s*pro", "iPhone 11 Pro"),
    (r"i\s*phone\s*11", "iPhone 11"),
    (r"i\s*phone\s*se", "iPhone SE"),
    (r"i\s*phone\s*xr", "iPhone XR"),
    (r"i\s*phone\s*xs?\s*max", "iPhone XS Max"),
    (r"i\s*phone\s*xs?", "iPhone XS"),
    (r"i\s*phone\s*x\b", "iPhone X"),
    (r"i\s*phone", "iPhone"),
    # Google Pixel
    (r"google\s*pixel\s*10\s*pro\s*xl", "Google Pixel 10 Pro XL"),
    (r"google\s*pixel\s*10\s*pro", "Google Pixel 10 Pro"),
    (r"google\s*pixel\s*10\s*a", "Google Pixel 10a"),
    (r"google\s*pixel\s*10", "Google Pixel 10"),
    (r"google\s*pixel\s*9\s*pro\s*xl", "Google Pixel 9 Pro XL"),
    (r"google\s*pixel\s*9\s*pro", "Google Pixel 9 Pro"),
    (r"google\s*pixel\s*9\s*a", "Google Pixel 9a"),
    (r"google\s*pixel\s*9\s*xl", "Google Pixel 9 XL"),
    (r"google\s*pixel\s*9", "Google Pixel 9"),
    (r"google\s*pixel\s*8\s*pro", "Google Pixel 8 Pro"),
    (r"google\s*pixel\s*8\s*a", "Google Pixel 8a"),
    (r"google\s*pixel\s*8", "Google Pixel 8"),
    (r"google\s*pixel\s*7\s*pro", "Google Pixel 7 Pro"),
    (r"google\s*pixel\s*7\s*a", "Google Pixel 7a"),
    (r"google\s*pixel\s*7", "Google Pixel 7"),
    (r"google\s*pixel\s*6\s*pro", "Google Pixel 6 Pro"),
    (r"google\s*pixel\s*6\s*a", "Google Pixel 6a"),
    (r"google\s*pixel\s*6", "Google Pixel 6"),
    (r"google\s*pixel\s*4\s*a", "Google Pixel 4a"),
    (r"google\s*pixel", "Google Pixel"),
    # Samsung Galaxy S
    (r"samsung\s*galaxy\s*s\s*25\s*fe", "Samsung Galaxy S25 FE"),
    (r"samsung\s*galaxy\s*s\s*25", "Samsung Galaxy S25"),
    (r"samsung\s*galaxy\s*s\s*24\s*fe", "Samsung Galaxy S24 FE"),
    (r"samsung\s*galaxy\s*s\s*24\s*plus", "Samsung Galaxy S24+"),
    (r"samsung\s*galaxy\s*s\s*24", "Samsung Galaxy S24"),
    (r"samsung\s*galaxy\s*s\s*23\s*fe", "Samsung Galaxy S23 FE"),
    (r"samsung\s*galaxy\s*s\s*23", "Samsung Galaxy S23"),
    (r"samsung\s*galaxy\s*s\s*22", "Samsung Galaxy S22"),
    (r"samsung\s*galaxy\s*s\s*21\s*fe", "Samsung Galaxy S21 FE"),
    (r"samsung\s*galaxy\s*s\s*21", "Samsung Galaxy S21"),
    (r"samsung\s*galaxy\s*s\s*20\s*fe", "Samsung Galaxy S20 FE"),
    (r"samsung\s*galaxy\s*s\s*20", "Samsung Galaxy S20"),
    (r"samsung\s*galaxy\s*s\s*10", "Samsung Galaxy S10"),
    (r"samsung\s*galaxy\s*s\s*9", "Samsung Galaxy S9"),
    # Samsung Galaxy A
    (r"samsung\s*galaxy\s*a\s*56\s*5g", "Samsung Galaxy A56 5G"),
    (r"samsung\s*galaxy\s*a\s*55\s*5g", "Samsung Galaxy A55 5G"),
    (r"samsung\s*galaxy\s*a\s*55", "Samsung Galaxy A55"),
    (r"samsung\s*galaxy\s*a\s*54\s*5g", "Samsung Galaxy A54 5G"),
    (r"samsung\s*galaxy\s*a\s*54", "Samsung Galaxy A54"),
    (r"samsung\s*galaxy\s*a\s*53\s*5g", "Samsung Galaxy A53 5G"),
    (r"samsung\s*galaxy\s*a\s*53", "Samsung Galaxy A53"),
    (r"samsung\s*galaxy\s*a\s*52", "Samsung Galaxy A52"),
    (r"samsung\s*galaxy\s*a\s*36\s*5g", "Samsung Galaxy A36 5G"),
    (r"samsung\s*galaxy\s*a\s*35\s*5g", "Samsung Galaxy A35 5G"),
    (r"samsung\s*galaxy\s*a\s*35", "Samsung Galaxy A35"),
    (r"samsung\s*galaxy\s*a\s*34\s*5g", "Samsung Galaxy A34 5G"),
    (r"samsung\s*galaxy\s*a\s*34", "Samsung Galaxy A34"),
    (r"samsung\s*galaxy\s*a\s*33", "Samsung Galaxy A33"),
    (r"samsung\s*galaxy\s*a\s*26\s*5g", "Samsung Galaxy A26 5G"),
    (r"samsung\s*galaxy\s*a\s*25\s*5g", "Samsung Galaxy A25 5G"),
    (r"samsung\s*galaxy\s*a\s*25", "Samsung Galaxy A25"),
    (r"samsung\s*galaxy\s*a\s*24\s*5g", "Samsung Galaxy A24 5G"),
    (r"samsung\s*galaxy\s*a\s*24", "Samsung Galaxy A24"),
    (r"samsung\s*galaxy\s*a\s*23\s*5g", "Samsung Galaxy A23 5G"),
    (r"samsung\s*galaxy\s*a\s*23", "Samsung Galaxy A23"),
    (r"samsung\s*galaxy\s*a\s*17", "Samsung Galaxy A17"),
    (r"samsung\s*galaxy\s*a\s*16\s*5g", "Samsung Galaxy A16 5G"),
    (r"samsung\s*galaxy\s*a\s*16", "Samsung Galaxy A16"),
    (r"samsung\s*galaxy\s*a\s*15\s*5g", "Samsung Galaxy A15 5G"),
    (r"samsung\s*galaxy\s*a\s*15", "Samsung Galaxy A15"),
    (r"samsung\s*galaxy\s*a\s*14\s*5g", "Samsung Galaxy A14 5G"),
    (r"samsung\s*galaxy\s*a\s*14", "Samsung Galaxy A14"),
    (r"samsung\s*galaxy\s*a\s*13", "Samsung Galaxy A13"),
    (r"samsung\s*galaxy\s*a\s*05", "Samsung Galaxy A05s"),
    (r"samsung\s*galaxy\s*a\s*71", "Samsung Galaxy A71"),
    (r"samsung\s*galaxy\s*m\s*35", "Samsung Galaxy M35"),
    (r"samsung\s*galaxy", "Samsung Galaxy"),
    (r"samsung", "Samsung"),
    # Xiaomi
    (r"xiaomi\s*redmi\s*note\s*15\s*pro\s*plus\s*5g", "Xiaomi Redmi Note 15 Pro+ 5G"),
    (r"xiaomi\s*redmi\s*note\s*15\s*pro\s*5g", "Xiaomi Redmi Note 15 Pro 5G"),
    (r"xiaomi\s*redmi\s*note\s*15\s*pro", "Xiaomi Redmi Note 15 Pro"),
    (r"xiaomi\s*redmi\s*note\s*15", "Xiaomi Redmi Note 15"),
    (r"xiaomi\s*redmi\s*note\s*13\s*pro", "Xiaomi Redmi Note 13 Pro"),
    (r"xiaomi\s*redmi\s*note\s*13", "Xiaomi Redmi Note 13"),
    (r"xiaomi\s*redmi\s*15\s*5g", "Xiaomi Redmi 15 5G"),
    (r"xiaomi\s*redmi\s*15\s*c", "Xiaomi Redmi 15C"),
    (r"xiaomi\s*redmi\s*15", "Xiaomi Redmi 15"),
    (r"xiaomi\s*redmi\s*a5", "Xiaomi Redmi A5"),
    (r"xiaomi\s*redmi", "Xiaomi Redmi"),
    (r"xiaomi\s*15\s*t\s*pro", "Xiaomi 15T Pro"),
    (r"xiaomi\s*15\s*t", "Xiaomi 15T"),
    (r"xiaomi\s*15\s*c\s*5g", "Xiaomi 15C 5G"),
    (r"xiaomi\s*15", "Xiaomi 15"),
    (r"xiaomi\s*13\s*t\s*pro", "Xiaomi 13T Pro"),
    (r"xiaomi\s*13\s*t", "Xiaomi 13T"),
    (r"xiaomi\s*13\s*pro", "Xiaomi 13 Pro"),
    (r"xiaomi\s*13", "Xiaomi 13"),
    (r"xiaomi", "Xiaomi"),
    # Motorola
    (r"motorola\s*edge\s*60\s*pro", "Motorola Edge 60 Pro"),
    (r"motorola\s*edge\s*60", "Motorola Edge 60"),
    (r"motorola\s*edge\s*40", "Motorola Edge 40"),
    (r"motorola\s*g75\s*5g", "Motorola G75 5G"),
    (r"motorola\s*g54\s*5g", "Motorola G54 5G"),
    (r"motorola\s*g15", "Motorola G15"),
    (r"motorola", "Motorola"),
    # Others
    (r"huawei\s*nova\s*13\s*pro", "Huawei Nova 13 Pro"),
    (r"huawei", "Huawei"),
    (r"honor\s*magic\s*[87]\s*pro", "Honor Magic Pro"),
    (r"honor", "Honor"),
    (r"oppo\s*find\s*x[93]\s*pro", "Oppo Find X Pro"),
    (r"oppo\s*find\s*x2\s*neo", "Oppo Find X2 Neo"),
    (r"oppo", "Oppo"),
    (r"oneplus\s*15", "OnePlus 15"),
    (r"oneplus", "OnePlus"),
    (r"vivo\s*v50\s*lite", "Vivo V50 Lite"),
    (r"vivo", "Vivo"),
    (r"cmf\s*phone\s*1", "CMF Phone 1"),
    (r"fairphone\s*5", "Fairphone 5"),
    # === Short-form / variant model patterns ===
    # Pixel without 'google' prefix
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
    # Google short: "google 8 pro", "google 8a" etc
    (r"google\s*8\s*pro\b", "Google Pixel 8 Pro"),
    (r"google\s*8\s*a\b", "Google Pixel 8a"),
    (r"google\s*8\b", "Google Pixel 8"),
    (r"google\s*9\s*pro\s*xl\b", "Google Pixel 9 Pro XL"),
    (r"google\s*9\s*pro\b", "Google Pixel 9 Pro"),
    (r"google\s*9\s*a\b", "Google Pixel 9a"),
    (r"google\s*9\s*xl\b", "Google Pixel 9 XL"),
    (r"google\s*9\b", "Google Pixel 9"),
    (r"google\s*7\s*pro\b", "Google Pixel 7 Pro"),
    (r"google\s*7\s*a\b", "Google Pixel 7a"),
    (r"google\s*7\b", "Google Pixel 7"),
    (r"google\s*6\s*pro\b", "Google Pixel 6 Pro"),
    (r"google\s*6\s*a\b", "Google Pixel 6a"),
    (r"google\s*6\b", "Google Pixel 6"),
    # "i phone" with space
    (r"i\s+phone\s+16\s*pro\s*max", "iPhone 16 Pro Max"),
    (r"i\s+phone\s+16\s*pro", "iPhone 16 Pro"),
    (r"i\s+phone\s+16\s*plus", "iPhone 16 Plus"),
    (r"i\s+phone\s+16\s*e", "iPhone 16e"),
    (r"i\s+phone\s+16", "iPhone 16"),
    (r"i\s+phone\s+15\s*pro\s*max", "iPhone 15 Pro Max"),
    (r"i\s+phone\s+15\s*pro", "iPhone 15 Pro"),
    (r"i\s+phone\s+15\s*plus", "iPhone 15 Plus"),
    (r"i\s+phone\s+15", "iPhone 15"),
    (r"i\s+phone\s+14\s*pro\s*max", "iPhone 14 Pro Max"),
    (r"i\s+phone\s+14\s*pro", "iPhone 14 Pro"),
    (r"i\s+phone\s+14\s*plus", "iPhone 14 Plus"),
    (r"i\s+phone\s+14", "iPhone 14"),
    (r"i\s+phone\s+13\s*pro\s*max", "iPhone 13 Pro Max"),
    (r"i\s+phone\s+13\s*pro", "iPhone 13 Pro"),
    (r"i\s+phone\s+13\s*mini", "iPhone 13 mini"),
    (r"i\s+phone\s+13", "iPhone 13"),
    (r"i\s+phone\s+12\s*pro\s*max", "iPhone 12 Pro Max"),
    (r"i\s+phone\s+12\s*pro", "iPhone 12 Pro"),
    (r"i\s+phone\s+12\s*mini", "iPhone 12 mini"),
    (r"i\s+phone\s+12", "iPhone 12"),
    (r"i\s+phone\s+11\s*pro\s*max", "iPhone 11 Pro Max"),
    (r"i\s+phone\s+11\s*pro", "iPhone 11 Pro"),
    (r"i\s+phone\s+11", "iPhone 11"),
    (r"i\s+phone\s+se", "iPhone SE"),
    (r"i\s+phone", "iPhone"),
    # "i-phone" with hyphen
    (r"i-phone\s+16\s*pro\s*max", "iPhone 16 Pro Max"),
    (r"i-phone\s+16\s*pro", "iPhone 16 Pro"),
    (r"i-phone\s+16", "iPhone 16"),
    (r"i-phone\s+15\s*pro\s*max", "iPhone 15 Pro Max"),
    (r"i-phone\s+15\s*pro", "iPhone 15 Pro"),
    (r"i-phone\s+15", "iPhone 15"),
    (r"i-phone\s+14\s*pro\s*max", "iPhone 14 Pro Max"),
    (r"i-phone\s+14\s*pro", "iPhone 14 Pro"),
    (r"i-phone\s+14", "iPhone 14"),
    (r"i-phone\s+13\s*pro\s*max", "iPhone 13 Pro Max"),
    (r"i-phone\s+13\s*pro", "iPhone 13 Pro"),
    (r"i-phone\s+13", "iPhone 13"),
    (r"i-phone\s+12\s*pro\s*max", "iPhone 12 Pro Max"),
    (r"i-phone\s+12\s*pro", "iPhone 12 Pro"),
    (r"i-phone\s+12", "iPhone 12"),
    (r"i-phone\s+11", "iPhone 11"),
    (r"i-phone", "iPhone"),
    # "apple" prefix
    (r"apple\s+iphone\s+16\s*pro\s*max", "iPhone 16 Pro Max"),
    (r"apple\s+iphone\s+16\s*pro", "iPhone 16 Pro"),
    (r"apple\s+iphone\s+16\s*plus", "iPhone 16 Plus"),
    (r"apple\s+iphone\s+16", "iPhone 16"),
    (r"apple\s+iphone\s+15\s*pro\s*max", "iPhone 15 Pro Max"),
    (r"apple\s+iphone\s+15\s*pro", "iPhone 15 Pro"),
    (r"apple\s+iphone\s+15", "iPhone 15"),
    (r"apple\s+iphone\s+14\s*pro\s*max", "iPhone 14 Pro Max"),
    (r"apple\s+iphone\s+14\s*pro", "iPhone 14 Pro"),
    (r"apple\s+iphone\s+14", "iPhone 14"),
    (r"apple\s+iphone\s+13\s*pro\s*max", "iPhone 13 Pro Max"),
    (r"apple\s+iphone\s+13\s*pro", "iPhone 13 Pro"),
    (r"apple\s+iphone\s+13", "iPhone 13"),
    (r"apple\s+iphone\s+12\s*pro\s*max", "iPhone 12 Pro Max"),
    (r"apple\s+iphone\s+12\s*pro", "iPhone 12 Pro"),
    (r"apple\s+iphone\s+12", "iPhone 12"),
    (r"apple\s+iphone\s+11", "iPhone 11"),
    (r"apple\s+iphone", "iPhone"),
    (r"apple\s+14\s*pro\s*max", "iPhone 14 Pro Max"),
    (r"apple\s+14\s*pro", "iPhone 14 Pro"),
    (r"apple\s+14", "iPhone 14"),
    (r"apple\s+15\s*pro\s*max", "iPhone 15 Pro Max"),
    (r"apple\s+15\s*pro", "iPhone 15 Pro"),
    (r"apple\s+15", "iPhone 15"),
    (r"apple\s+16\s*pro\s*max", "iPhone 16 Pro Max"),
    (r"apple\s+16\s*pro", "iPhone 16 Pro"),
    (r"apple\s+16\s*plus", "iPhone 16 Plus"),
    (r"apple\s+16", "iPhone 16"),
    (r"apple\s+13\s*pro\s*max", "iPhone 13 Pro Max"),
    (r"apple\s+13\s*pro", "iPhone 13 Pro"),
    (r"apple\s+13", "iPhone 13"),
    (r"apple\s+12\s*pro\s*max", "iPhone 12 Pro Max"),
    (r"apple\s+12\s*pro", "iPhone 12 Pro"),
    (r"apple\s+12", "iPhone 12"),
    (r"apple\s+11", "iPhone 11"),
    # Samsung short: "galaxy a54", "galaxy s24fe"
    (r"\bgalaxy\s+a\s*(\d+)\s*5g\b", "Samsung Galaxy A\1 5G"),
    (r"\bgalaxy\s+a\s*(\d+)\b", "Samsung Galaxy A\1"),
    (r"\bgalaxy\s+s\s*(\d+)\s*fe\b", "Samsung Galaxy S\1 FE"),
    (r"\bgalaxy\s+s\s*(\d+)\b", "Samsung Galaxy S\1"),
    (r"\bgalaxy\s+m\s*(\d+)\b", "Samsung Galaxy M\1"),
    (r"\bgalaxy\s+(\d+)\s*plus\b", "Samsung Galaxy S\1+"),
    # Samsung S FE short: "s24fe", "s24 fe"
    (r"\bs(\d+)\s*fe\b", "Samsung Galaxy S\1 FE"),
    (r"\bs(\d+)fe\b", "Samsung Galaxy S\1 FE"),
    # Samsung A short: "a54 5g", "a54"
    (r"\ba(\d+)\s*5g\b", "Samsung Galaxy A\1 5G"),
    (r"\ba(\d+)\b", "Samsung Galaxy A\1"),
    # Samsung number-only: "samsung 54 5g", "samsung 14"
    (r"samsung\s+(\d+)\s*5g\b", "Samsung Galaxy A\1 5G"),
    (r"samsung\s+(\d+)\b", "Samsung Galaxy A\1"),
    # Edge 60 pro (Motorola without brand)
    (r"\bedge\s+60\s*pro\b", "Motorola Edge 60 Pro"),
    (r"\bedge\s+60\b", "Motorola Edge 60"),
    # Find x9 pro (Oppo without brand)
    (r"\bfind\s+x([93])\s*pro\b", "Oppo Find X\1 Pro"),

]

def find_model(text):
    """Find the phone model in a search term. Returns (model_name, remaining_text)."""
    t = text.lower().strip()
    for pat, name in MODELS:
        m = re.search(pat, t)
        if m:
            # If name contains backreferences like \1, expand them
            model_name = name
            if '\\' in name:
                try:
                    model_name = m.expand(name)
                except:
                    model_name = name
            before = t[:m.start()].strip()
            after = t[m.end():].strip()
            remainder = (before + " " + after).strip()
            return model_name, remainder
    return None, t

# ── Attribute extraction ──
# These are the root attributes we care about, with their German/English variants
ATTR_PATTERNS = {
    "Hülle": [
        r"\bhülle\b", r"\bhuelle\b", r"\bhu00fclle\b", r"\bcase\b", r"\bcover\b",
        r"\bhandyhülle\b", r"\bhandyhu00fclle\b", r"\bhandycase\b", r"\bhandycover\b",
        r"\bschutzhülle\b", r"\bschutzhuelle\b", r"\bschutzhülle\b", r"\bschutzcover\b",
        r"\bschale\b", r"\bhandyschale\b", r"\betui\b", r"\bbackcover\b",
        r"\btelefonhülle\b", r"\bvollhülle\b", r"\bvollschutzhülle\b",
        r"\boutdoorhülle\b", r"\boutdoorhuelle\b", r"\bpanzerhülle\b", r"\bpanzerhuelle\b",
        r"\bhardcase\b", r"\bhardcover\b", r"\bbumper\b", r"\bsilikonhülle\b",
        r"\bmetallhülle\b", r"\bmetal\s*case\b", r"\balu\s*case\b", r"\baluminum\s*case\b",
        r"\bcarbon\s*hülle\b", r"\bflipcase\b", r"\brugged\s*case\b",
        r"\bhandytasche\b", r"\bmilitary\b", r"\bmilitär\b",
        r"\bganzkörperhülle\b", r"\brundumschutz\b", r"\bfullbody\b",
        r"\bwasserdicht\b", r"\bwasserfest\b", r"\bwaterproof\b",
        r"\bkomplettschutz\b", r"\bstaubschutz\b", r"\bdustproof\b",
        r"\bdurchsichtig\b", r"\btransparent\b",
        r"\bstoßfest\b", r"\bstoßfeste\b", r"\bshockproof\b", r"\bsturzsicher\b",
        r"\brobust\b", r"\brobuste\b", r"\bstabil\b", r"\barmored\b",
        r"\bkratzfest\b", r"\bkratzfeste\b", r"\bdünn\b", r"\bdünne\b",
        r"\bsilikon\b", r"\bsilicone\b", r"\bleder\b", r"\bholz\b",
        r"\borganizer\b", r"\bklappbar\b",
    ],
    "Ständer": [
        r"\bständer\b", r"\bstaender\b", r"\bstand\b", r"\bstandfuß\b", r"\bstandfuss\b",
        r"\bstandfu00df\b", r"\bkickstand\b", r"\bkick\s*stand\b",
        r"\baufsteller\b", r"\baufstellen\b", r"\bstehend\b", r"\bhinstellen\b",
        r"\bstütze\b", r"\bhalterung\b", r"\bhalter\b",
        r"\bfingerhalter\b", r"\bfingerhalterung\b", r"\bfinger\s*ring\b",
        r"\bpop\s*grip\b", r"\bpopsocket\b", r"\bgriff\b",
        r"\bringständer\b", r"\bring\s*ständer\b", r"\bstandring\b",
        r"\bringhalter\b", r"\bringhalterung\b",
        r"\bdrehständer\b", r"\bdrehbar\b", r"\bdrehbare\b",
        r"\b360\s*grad\b", r"\b360°\b", r"\b360grad\b", r"\b360\s*degree\b",
        r"\brotating\b", r"\b180\s*degree\b",
        r"\bintegriertem\s*ständer\b", r"\bstand\s*case\b",
        r"\bstanding\b", r"\bständerhülle\b", r"\bstand\s*hülle\b",
        r"\bpopup\b", r"\bpop\s*up\b", r"\bverstellbarem\s*kickstand\b",
        r"\badjustable\s*stand\b", r"\bdual\s*stand\b",
    ],
    "MagSafe": [
        r"\bmagsafe\b", r"\bmag\s*safe\b", r"\bmag\s*save\b",
        r"\bmagnet\b", r"\bmagnetisch\b", r"\bmagnetic\b", r"\bmagnetische\b",
        r"\bmagnetischer\b", r"\bmagnetring\b", r"\bmagnet\s*ring\b",
        r"\bmagnethülle\b", r"\bmagnet\s*hülle\b", r"\bmagnetic\s*case\b",
        r"\bmagnethalter\b", r"\bmagnethalterung\b",
        r"\bmagsafehülle\b", r"\bmagsafe-hülle\b",
    ],
    "Ring": [
        r"\bring\b", r"\bringe\b", r"\bringhalter\b", r"\bringhalterung\b",
        r"\bdoppelring\b", r"\bdrehbare\s*ring\b", r"\bdrehbarer\s*ring\b",
        r"\bringke\b",
    ],
    "Kameraschutz": [
        r"\bkameraschutz\b", r"\bkamera\s*schutz\b", r"\bkameraabdeckung\b",
        r"\bkamera\s*abdeckung\b", r"\bcamera\s*protection\b",
        r"\bkamera\s*cover\b", r"\bkamera\s*schutz\b",
    ],
    "Displayschutz": [
        r"\bdisplayschutz\b", r"\bdisplay\s*schutz\b", r"\bpanzerglas\b",
        r"\bpanzer\s*glas\b", r"\bpanzerfolie\b", r"\bschutzfolie\b",
        r"\bschutzglas\b", r"\bschutz\s*glas\b", r"\bscreen\s*protector\b",
        r"\bdisplayschutzfolie\b", r"\bdisplay\s*folie\b", r"\bhandyfolie\b",
        r"\bglass\s*guard\b", r"\bprivacy\s*glass\b", r"\bsichtschutz\b",
        r"\b9h\b", r"\bgehärtetem\s*glas\b",
    ],
    "Kartenfach": [
        r"\bkartenfach\b", r"\bkartenfächer\b", r"\bcard\s*holder\b",
        r"\bcardholder\b", r"\bkartenhalter\b", r"\bmit\s*karte\b",
    ],
    "Band": [
        r"\bmit\s*band\b", r"\bhandband\b", r"\bhandschlaufe\b",
        r"\bmit\s*kette\b", r"\bhandykette\b", r"\bschnur\b",
    ],
    "Induktives Laden": [
        r"\binduktives\s*laden\b", r"\binductive\s*charging\b",
        r"\bwireless\s*charging\b", r"\bkabelloses\s*laden\b",
        r"\bladefunktion\b", r"\bqi\s*ständer\b", r"\bqi\b",
        r"\bpower\s*bank\b", r"\bpowerbank\b", r"\bakku\b",
        r"\bmit\s*ladefunktion\b", r"\bmit\s*induktion\b",
        r"\bmit\s*aufladen\b", r"\bmit\s*laden\b",
    ],
    "360°": [
        r"\b360\s*grad\b", r"\b360°\b", r"\b360grad\b", r"\b360\s*degree\b",
        r"\bvollschutz\b", r"\bvollschutzhülle\b", r"\brundum\b",
    ],
    "Outdoor/Robust": [
        r"\boutdoor\b", r"\boutdor\b", r"\bmilitary\b", r"\bmilitär\b",
        r"\bmilitärisch\b", r"\bstoßfest\b", r"\bstoßfeste\b", r"\bshockproof\b",
        r"\bsturzsicher\b", r"\brobust\b", r"\brobuste\b", r"\barmored\b",
        r"\bwasserdicht\b", r"\bwasserfest\b", r"\bwaterproof\b",
        r"\bstaubschutz\b", r"\bdustproof\b", r"\bdust\s*plug\b",
        r"\brugged\b", r"\btank\s*case\b", r"\bpanzer\b",
        r"\bbaustelle\b", r"\bbaustellen\b",
    ],
    "Farbe": [
        r"\bschwarz\b", r"\bweiß\b", r"\bweiss\b", r"\brot\b", r"\bblau\b",
        r"\bgrün\b", r"\bgruen\b", r"\bgelb\b", r"\borange\b", r"\brosa\b",
        r"\bpink\b", r"\blila\b", r"\bgrau\b", r"\bgold\b", r"\bsilber\b",
        r"\bviolett\b", r"\bhellblau\b", r"\bdunkel\b", r"\bneon\b",
        r"\bglitzer\b", r"\bsparkly\b", r"\bglitter\b", r"\bweinrot\b",
        r"\bmocca\b", r"\beisblau\b", r"\btransparent\b", r"\bdurchsichtig\b",
        r"\bkamoflage\b", r"\bcamouflage\b", r"\bholz\b", r"\bcarbon\b",
        r"\bmetall\b", r"\bmetal\b", r"\btitan\b",
    ],
    "Marke": [
        r"\besr\b", r"\bspigen\b", r"\btorras\b", r"\botterbox\b",
        r"\buag\b", r"\bcaseology\b", r"\bnillkin\b", r"\bsupcase\b",
        r"\btuvror\b", r"\bdexnor\b", r"\bcasekoo\b", r"\bcasebus\b",
        r"\bflolab\b", r"\bapiker\b", r"\bmiracase\b", r"\bhaonande\b",
        r"\bhdqicase\b", r"\bmasopsk\b", r"\bsmacase\b", r"\bsuritch\b",
        r"\bpuyateya\b", r"\bdasfond\b", r"\bfntcase\b", r"\brolemodel\b",
        r"\barc\s*pulse\b", r"\bwhite\s*dome\b", r"\bstone\s*island\b",
        r"\bapple\b", r"\boriginal\b", r"\bferrari\b", r"\bnike\b",
        r"\bbvb\b", r"\bamg\b", r"\betsy\b", r"\bamazon\b",
        r"\btarget\b", r"\bhyped\b", r"\baoui\b", r"\baesthetic\b",
        r"\banime\b", r"\bsnoopy\b", r"\bresident\s*evil\b",
        r"\bchoumi\b", r"\blemaxelers\b", r"\banlalish\b",
        r"\bidioon\b", r"\bmaskica\b", r"\bmetolius\b",
        r"\bpanda\b", r"\bschrulle\b", r"\bwellig\b",
    ],
    "Material": [
        r"\bsilikon\b", r"\bsilicone\b", r"\bleder\b", r"\bmetall\b",
        r"\bmetal\b", r"\baluminium\b", r"\baluminum\b", r"\balu\b",
        r"\bcarbon\b", r"\bholz\b", r"\bwood\b", r"\bkunststoff\b",
        r"\bplastic\b", r"\bmatt\b", r"\bglänzend\b", r"\bgalvanisiert\b",
        r"\brutschfest\b", r"\bsoft\s*touch\b", r"\bmaschen\b",
    ],
    "Design": [
        r"\bdünn\b", r"\bdünne\b", r"\bultra\s*dünn\b", r"\bultra\s*leicht\b",
        r"\bslim\b", r"\bthin\b", r"\bluxury\b", r"\belegant\b",
        r"\bmodern\b", r"\bdesign\b", r"\bästhetisch\b", r"\baesthetic\b",
        r"\bcoole\b", r"\bmotiv\b", r"\bglitzer\b", r"\bglitter\b",
        r"\bsparkly\b", r"\bblumen\b", r"\bwellen\b", r"\bwellig\b",
        r"\bmuster\b", r"\bgedruckt\b", r"\bbunt\b", r"\bfarbig\b",
        r"\bunsichtbar\b", r"\bunsichtbarer\b", r"\binvisible\b",
        r"\bdurchsichtig\b", r"\btransparent\b", r"\bklar\b",
        r"\bmatt\b", r"\bglossy\b", r"\bglänzend\b",
    ],
    "Kompatibilität": [
        r"\bkompatibel\b", r"\bcompatible\b", r"\bpassend\b",
        r"\bfür\b", r"\bfor\b",
    ],
    "Zubehör": [
        r"\bzubehör\b", r"\baccessories\b", r"\baccessory\b",
    ],
    "Montage": [
        r"\b2\s*phase\b", r"\bzweiteilig\b", r"\b2\s*stück\b",
        r"\b2\s*teilig\b", r"\bset\b",
    ],
}

def extract_attrs(remainder):
    """Extract attributes from the non-model part of a search term."""
    found = defaultdict(list)
    t = remainder.lower()
    for attr_name, patterns in ATTR_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, t):
                found[attr_name].append(pat)
    return {k: True for k in found}

# ── Main processing ──
wb = openpyxl.load_workbook(SRC)
ws = wb["广告搜索词"]

rows = []
for row in ws.iter_rows(min_row=3, max_row=ws.max_row, values_only=True):
    term = row[1]  # Column B: user search term
    if not term or not str(term).strip():
        continue
    term = str(term).strip()
    model, remainder = find_model(term)
    attrs = extract_attrs(remainder)
    rows.append({
        "original": term,
        "model": model or "",
        "remainder": remainder,
        "attrs": list(attrs.keys()),
    })

print(f"Processed {len(rows)} rows")

# ── Build keyword library ──
# Group by: model -> attribute combination -> list of original terms
from itertools import combinations

# First, build the attribute combination signatures
combo_map = defaultdict(lambda: defaultdict(list))  # model -> attr_sig -> [terms]
for r in rows:
    if not r["model"]:
        continue
    attrs = tuple(sorted(r["attrs"]))
    combo_map[r["model"]][attrs].append(r["original"])

# Build the keyword library: for each attribute combination, create a template
# where {MODEL} replaces the specific model
keyword_library = defaultdict(list)  # attr_sig -> [template_terms]

for model, combos in combo_map.items():
    for attrs, terms in combos.items():
        # Create template by replacing the model with {MODEL}
        for t in terms:
            # Find model position and replace
            t_lower = t.lower()
            for pat, name in MODELS:
                m = re.search(pat, t_lower)
                if m and name == model:
                    template = t[:m.start()] + "{MODEL}" + t[m.end():]
                    template = " ".join(template.split())  # normalize whitespace
                    keyword_library[attrs].append(template)
                    break

# Deduplicate templates within each attribute group
for attrs in keyword_library:
    keyword_library[attrs] = list(set(keyword_library[attrs]))

# ── Generate output ──

# 1. Annotated Excel
wb_out = openpyxl.Workbook()
ws_out = wb_out.active
ws_out.title = "搜索词分析"
headers = ["原始搜索词", "识别型号", "剩余文本", "词根属性"]
for c, h in enumerate(headers, 1):
    ws_out.cell(row=1, column=c, value=h)

for i, r in enumerate(rows, 2):
    ws_out.cell(row=i, column=1, value=r["original"])
    ws_out.cell(row=i, column=2, value=r["model"])
    ws_out.cell(row=i, column=3, value=r["remainder"])
    ws_out.cell(row=i, column=4, value=", ".join(r["attrs"]))

out_xlsx = OUT / "DE搜索词_词根属性分析.xlsx"
wb_out.save(out_xlsx)
print(f"Saved annotated Excel: {out_xlsx}")

# 2. Keyword library (JSON)
lib_data = {}
for attrs, templates in sorted(keyword_library.items()):
    key = " + ".join(attrs) if attrs else "通用"
    lib_data[key] = templates

with open(OUT / "关键词库.json", "w", encoding="utf-8") as f:
    json.dump(lib_data, f, ensure_ascii=False, indent=2)
print(f"Saved keyword library JSON: {OUT / '关键词库.json'}")

# 3. Keyword library (readable text)
with open(OUT / "关键词库.txt", "w", encoding="utf-8") as f:
    f.write("=" * 80 + "\n")
    f.write("DE Amazon 手机壳关键词库\n")
    f.write("使用说明：将 {MODEL} 替换为具体型号即可生成投放关键词\n")
    f.write("例如：{MODEL} Hülle mit Ständer → iPhone 17 Pro Hülle mit Ständer\n")
    f.write("=" * 80 + "\n\n")

    for attrs, templates in sorted(keyword_library.items()):
        key = " + ".join(attrs) if attrs else "通用"
        f.write(f"\n## {key}\n")
        f.write(f"  模板数: {len(templates)}\n\n")
        for t in sorted(templates):
            f.write(f"  {t}\n")

print(f"Saved keyword library text: {OUT / '关键词库.txt'}")

# 4. Summary statistics
print("\n=== 统计摘要 ===")
print(f"总搜索词数: {len(rows)}")
print(f"识别到型号的: {sum(1 for r in rows if r['model'])}")
print(f"未识别型号的: {sum(1 for r in rows if not r['model'])}")
print(f"关键词库模板组数: {len(keyword_library)}")
total_templates = sum(len(v) for v in keyword_library.values())
print(f"关键词库模板总数: {total_templates}")

# Top attribute combinations
attr_counts = Counter()
for r in rows:
    if r["attrs"]:
        attr_counts[", ".join(r["attrs"])] += 1
print("\n最常见的属性组合 (Top 20):")
for combo, count in attr_counts.most_common(20):
    print(f"  {combo}: {count}")

# Models found
model_counts = Counter(r["model"] for r in rows if r["model"])
print(f"\n识别到的型号分布 (Top 20):")
for model, count in model_counts.most_common(20):
    print(f"  {model}: {count}")

# Unmatched terms (no model detected)
unmatched = [r for r in rows if not r["model"]]
if unmatched:
    print(f"\n未识别型号的搜索词 (前30条):")
    for r in unmatched[:30]:
        print(f"  {r['original']}")

print("\nDone!")
