"""Hymn's built-in food list: everyday Indian and foreign foods, per serving.

Servings are the way people actually eat (1 roti, 1 katori dal, 1 plate
biryani, 1 glass milk), not grams. Each food carries:

* calories, protein, carbs, fat and fibre for one serving (typical values,
  compiled from public food composition tables such as India's IFCT and
  USDA FoodData Central, for a typical home recipe);
* what one serving counts towards in Hymn's portion log: vegetables & fruit,
  protein servings, sweets / sugary drinks, fried food.

Home cooking varies a lot (oil, ghee, sugar, bowl size), so every number is a
typical value with a range: ±10% for simple foods (fruit, egg, milk, bread),
−20%/+25% for cooked dishes. ``VALUES_REVIEWED`` stays False until a
nutritionist has checked the list.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Dict, List, Optional

VALUES_REVIEWED = False  # flips once a nutritionist signs off the values

# Range around the typical value, by kind of food.
RANGE = {"simple": (Decimal("0.9"), Decimal("1.1")), "dish": (Decimal("0.8"), Decimal("1.25"))}

FOODS: Dict[str, dict] = {}


def _f(fid, name, aliases, unit, kcal, protein, carbs, fat, fibre, *, veg=0, prot=0, sugary=0, fried=False,
       kind="dish", group="meal"):
    FOODS[fid] = {
        "id": fid, "name": name, "aliases": [a.lower() for a in aliases], "unit": unit,
        "kcal": kcal, "protein_g": protein, "carbs_g": carbs, "fat_g": fat, "fibre_g": fibre,
        "counts": {"veg_fruit_portions": veg, "protein_servings": prot, "sugary_items": sugary},
        "fried": fried, "kind": kind, "group": group,
    }


S = "simple"
# --- Breads ---------------------------------------------------------------
_f("roti", "Roti / chapati", ["chapati", "chapathi", "fulka", "rotli"], "piece", 105, 3, 18, 2.5, 2.5)
_f("phulka", "Phulka (no ghee)", ["phulka", "plain roti"], "piece", 80, 2.5, 16, 0.5, 2)
_f("roti_ghee", "Roti with ghee", ["ghee roti", "chapati with ghee"], "piece", 140, 3, 18, 6, 2.5)
_f("paratha", "Plain paratha", ["parantha", "lachha paratha"], "piece", 200, 4, 28, 8, 3)
_f("aloo_paratha", "Aloo paratha", ["aloo parantha", "potato paratha"], "piece", 290, 6, 40, 12, 4)
_f("paneer_paratha", "Paneer paratha", ["paneer parantha"], "piece", 320, 11, 34, 15, 3, prot=0.5)
_f("gobi_paratha", "Gobi paratha", ["gobhi paratha", "mooli paratha"], "piece", 260, 6, 36, 10, 4)
_f("puri", "Puri", ["poori"], "piece", 100, 1.5, 11, 5.5, 0.5, fried=True)
_f("bhatura", "Bhatura", ["bhature"], "piece", 300, 6, 40, 13, 1.5, fried=True)
_f("naan", "Naan", ["plain naan"], "piece", 260, 8, 45, 5, 2)
_f("butter_naan", "Butter naan", ["garlic naan"], "piece", 320, 8, 45, 12, 2)
_f("kulcha", "Kulcha", ["amritsari kulcha"], "piece", 250, 7, 40, 7, 2)
_f("tandoori_roti", "Tandoori roti", ["tandoori"], "piece", 120, 4, 24, 1, 3)
_f("bajra_roti", "Bajra roti", ["bajra bhakri", "sajje rotti"], "piece", 120, 3.5, 22, 2.5, 3)
_f("jowar_roti", "Jowar roti", ["jowar bhakri", "jolada rotti"], "piece", 110, 3.5, 22, 1, 3)
_f("ragi_roti", "Ragi roti / mudde", ["ragi mudde", "ragi ball", "nachni bhakri"], "piece", 130, 3, 26, 1.5, 3.5)
_f("makki_roti", "Makki ki roti", ["makki roti", "corn roti"], "piece", 150, 3, 25, 4, 3)
_f("thepla", "Thepla", ["methi thepla"], "piece", 120, 3, 16, 5, 2)
_f("bread_white", "White bread", ["bread slice", "sandwich bread"], "slice", 67, 2, 13, 0.8, 0.6, kind=S)
_f("bread_brown", "Brown / whole wheat bread", ["atta bread", "multigrain bread"], "slice", 65, 3, 11, 1, 2, kind=S)
_f("pav", "Pav / bun", ["bun", "ladi pav"], "piece", 120, 4, 22, 1.5, 1, kind=S)

# --- Rice & one-dish meals -------------------------------------------------
_f("rice", "Rice (cooked)", ["chawal", "white rice", "steamed rice", "annam", "sadam"], "katori",
   195, 4, 43, 0.4, 0.6)
_f("brown_rice", "Brown rice (cooked)", ["red rice", "matta rice"], "katori", 165, 3.5, 34, 1.3, 2.7)
_f("jeera_rice", "Jeera rice", ["cumin rice"], "katori", 230, 4, 42, 5, 1)
_f("veg_pulao", "Veg pulao", ["pulav", "vegetable pulao"], "katori", 250, 5, 40, 7, 2)
_f("veg_biryani", "Veg biryani", ["vegetable biryani"], "plate", 400, 9, 60, 14, 4)
_f("chicken_biryani", "Chicken biryani", ["biryani", "hyderabadi biryani"], "plate", 500, 25, 60, 17, 2, prot=1)
_f("mutton_biryani", "Mutton biryani", ["lamb biryani", "goat biryani"], "plate", 560, 26, 58, 24, 2, prot=1)
_f("egg_biryani", "Egg biryani", [], "plate", 450, 16, 60, 15, 2, prot=1)
_f("curd_rice", "Curd rice", ["thayir sadam", "mosaranna", "dahi chawal"], "katori", 230, 7, 36, 6, 1)
_f("lemon_rice", "Lemon rice", ["chitranna", "tamarind rice", "puliyogare", "pulihora"], "katori", 250, 4, 42, 7, 1.5)
_f("bisibelebath", "Bisi bele bath", ["bisibele bath", "sambar rice"], "katori", 260, 8, 40, 8, 5, veg=0.5, prot=0.5)
_f("khichdi", "Khichdi", ["khichri", "dal khichdi"], "katori", 220, 8, 36, 5, 4, prot=0.5)
_f("pongal", "Ven pongal", ["pongal", "khara pongal"], "katori", 280, 8, 38, 11, 3, prot=0.5)
_f("poha", "Poha", ["aval", "avalakki", "chivda poha", "kanda poha"], "plate", 250, 5, 40, 8, 2)
_f("upma", "Upma", ["uppittu", "rava upma"], "plate", 230, 5, 32, 9, 2.5)
_f("rajma_chawal", "Rajma chawal", ["rajma rice"], "plate", 450, 15, 72, 10, 10, prot=1)
_f("dal_chawal", "Dal chawal", ["dal rice"], "plate", 380, 14, 65, 6, 5, prot=1)

# --- South Indian ------------------------------------------------------------
_f("idli", "Idli", ["idly"], "piece", 58, 2, 12, 0.2, 0.5)
_f("dosa", "Plain dosa", ["dosai", "sada dosa", "dose"], "piece", 170, 4, 28, 4.5, 1)
_f("masala_dosa", "Masala dosa", ["masala dose"], "piece", 380, 7, 52, 16, 4)
_f("rava_dosa", "Rava dosa", ["rava dose"], "piece", 200, 4, 28, 8, 1)
_f("set_dosa", "Set dosa", ["set dose"], "piece", 120, 3, 22, 2, 1)
_f("uttapam", "Uttapam", ["uthappam", "oothappam"], "piece", 200, 5, 32, 5, 2)
_f("pesarattu", "Pesarattu", ["moong dosa"], "piece", 160, 7, 24, 4, 4, prot=1)
_f("appam", "Appam", ["palappam"], "piece", 120, 2, 23, 2, 0.5)
_f("medu_vada", "Medu vada", ["vada", "uddina vade", "ulundu vadai"], "piece", 140, 4, 14, 8, 2, fried=True)
_f("sambar", "Sambar", ["saaru", "sambhar"], "katori", 130, 6, 18, 4, 4, veg=1, prot=0.5)
_f("rasam", "Rasam", ["chaaru", "saaru rasam"], "katori", 60, 2, 9, 2, 1.5)
_f("coconut_chutney", "Coconut chutney", ["chutney", "kayi chutney", "thengai chutney"], "2 tbsp", 70, 1, 3, 6, 1.5)
_f("tomato_chutney", "Tomato / onion chutney", ["kara chutney"], "2 tbsp", 45, 0.5, 4, 3, 1)

# --- Dals, curries, vegetables --------------------------------------------
_f("dal", "Dal (plain)", ["toor dal", "moong dal", "masoor dal", "arhar dal", "paruppu", "pappu", "varan"],
   "katori", 150, 9, 20, 4, 4, prot=1)
_f("dal_tadka", "Dal tadka / dal fry", ["dal fry", "tadka dal"], "katori", 180, 9, 20, 7, 4, prot=1)
_f("dal_makhani", "Dal makhani", ["maa ki dal", "kaali dal"], "katori", 280, 10, 24, 16, 6, prot=1)
_f("rajma", "Rajma", ["kidney beans curry"], "katori", 210, 10, 28, 6, 7, prot=1)
_f("chole", "Chole / chana masala", ["chana masala", "chhole", "kabuli chana"], "katori", 240, 10, 30, 8, 8, prot=1)
_f("kala_chana", "Kala chana curry", ["black chana", "kadala curry"], "katori", 200, 10, 28, 5, 9, prot=1)
_f("kadhi", "Kadhi", ["kadhi pakora", "majjige huli", "mor kuzhambu"], "katori", 150, 5, 12, 9, 1)
_f("sprouts", "Sprouts salad", ["moong sprouts", "usal", "misal"], "katori", 110, 8, 18, 1, 5, prot=1)
_f("mixed_veg", "Mixed veg sabzi", ["sabzi", "sabji", "veg curry", "palya", "poriyal", "thoran", "subzi"],
   "katori", 130, 3, 12, 8, 4, veg=1)
_f("aloo_sabzi", "Aloo sabzi", ["potato curry", "aloo bhaji", "batata bhaji", "aloo jeera"], "katori",
   180, 3, 24, 8, 3)
_f("bhindi", "Bhindi sabzi", ["okra", "bhindi masala", "bendekai palya"], "katori", 140, 3, 10, 10, 4, veg=1)
_f("gobi_sabzi", "Gobi / cabbage sabzi", ["aloo gobi", "cabbage poriyal", "gobhi"], "katori", 130, 3, 11, 8, 4, veg=1)
_f("baingan", "Baingan bharta", ["brinjal curry", "eggplant", "baingan"], "katori", 120, 3, 12, 7, 5, veg=1)
_f("palak", "Palak / saag", ["sarson ka saag", "spinach curry", "keerai"], "katori", 120, 4, 8, 8, 4, veg=1)
_f("lauki", "Lauki / tori sabzi", ["bottle gourd", "dudhi", "ghiya", "tinda"], "katori", 90, 2, 9, 5, 3, veg=1)
_f("avial", "Avial", ["aviyal", "kootu"], "katori", 160, 3, 12, 11, 4, veg=1)
_f("palak_paneer", "Palak paneer", ["saag paneer"], "katori", 260, 12, 10, 19, 3, veg=1, prot=1)
_f("paneer_butter_masala", "Paneer butter masala", ["paneer makhani", "kadai paneer", "paneer tikka masala"],
   "katori", 350, 14, 12, 27, 2, prot=1)
_f("matar_paneer", "Matar paneer", ["mutter paneer"], "katori", 280, 13, 14, 19, 4, veg=0.5, prot=1)
_f("shahi_paneer", "Shahi paneer", ["paneer korma"], "katori", 380, 13, 12, 31, 2, prot=1)
_f("paneer_bhurji", "Paneer bhurji", [], "katori", 300, 17, 6, 23, 1, prot=1)
_f("salad", "Salad (cucumber, tomato, onion)", ["green salad", "kachumber", "koshambari", "raita salad"], "bowl",
   25, 1, 5, 0.2, 1.5, veg=1, kind=S)
_f("raita", "Raita", ["boondi raita", "cucumber raita", "pachadi"], "katori", 90, 4, 7, 5, 0.5)

# --- Eggs, meat, fish --------------------------------------------------------
_f("egg_boiled", "Boiled egg", ["egg", "anda", "hard boiled egg"], "piece", 78, 6.3, 0.6, 5.3, 0, prot=0.5, kind=S)
_f("omelette", "Omelette (2 eggs)", ["omlet", "masala omelette"], "piece", 190, 13, 2, 15, 0, prot=1)
_f("egg_bhurji", "Egg bhurji (2 eggs)", ["anda bhurji", "scrambled eggs"], "katori", 220, 13, 4, 17, 1, prot=1)
_f("egg_curry", "Egg curry (2 eggs)", ["anda curry", "egg masala"], "katori", 260, 14, 8, 19, 2, prot=1)
_f("chicken_curry", "Chicken curry", ["chicken masala", "kozhi curry", "chicken gravy"], "katori",
   240, 22, 6, 14, 1, prot=1)
_f("butter_chicken", "Butter chicken", ["murgh makhani", "chicken tikka masala"], "katori", 350, 24, 9, 24, 1, prot=1)
_f("chicken_tikka", "Chicken tikka (6 pieces)", ["tikka", "chicken kebab", "reshmi kebab"], "plate",
   230, 33, 4, 9, 0.5, prot=1)
_f("tandoori_chicken", "Tandoori chicken (quarter)", ["tandoori"], "piece", 300, 40, 4, 13, 0.5, prot=1.5)
_f("chicken_65", "Chicken 65 / fried chicken pieces", ["chicken fry", "chicken pakoda"], "plate",
   380, 26, 14, 24, 1, prot=1, fried=True)
_f("chilli_chicken", "Chilli chicken", ["chicken manchurian", "dragon chicken"], "katori", 350, 22, 18, 21, 2,
   prot=1, fried=True)
_f("mutton_curry", "Mutton curry", ["lamb curry", "goat curry", "rogan josh", "mutton masala"], "katori",
   300, 22, 6, 21, 1, prot=1)
_f("keema", "Keema", ["kheema", "mince curry"], "katori", 320, 22, 8, 22, 2, prot=1)
_f("fish_curry", "Fish curry", ["meen curry", "machher jhol", "fish gravy"], "katori", 200, 20, 6, 11, 1, prot=1)
_f("fish_fry", "Fish fry (1 piece)", ["fried fish", "rava fish fry", "meen varuval"], "piece",
   220, 20, 6, 13, 0, prot=1, fried=True)
_f("prawn_curry", "Prawn curry", ["prawns", "shrimp curry", "chemmeen curry"], "katori", 220, 22, 7, 12, 1, prot=1)
_f("grilled_chicken", "Grilled chicken breast (150 g)", ["chicken breast", "grilled chicken"], "piece",
   250, 46, 0, 6, 0, prot=1.5, kind=S)
_f("salmon", "Salmon fillet (150 g)", ["grilled fish", "baked fish"], "piece", 310, 33, 0, 19, 0, prot=1.5, kind=S)
_f("paneer", "Paneer (100 g)", ["paneer", "cottage cheese"], "100 g", 265, 18, 3.5, 20, 0, prot=1, kind=S)
_f("tofu", "Tofu (100 g)", ["soya paneer"], "100 g", 145, 15, 3, 9, 2, prot=1, kind=S)
_f("soya_chunks", "Soya chunks curry", ["soya", "meal maker", "nutrela"], "katori", 200, 18, 14, 8, 5, prot=1)

# --- Snacks & street food ------------------------------------------------
_f("samosa", "Samosa", ["samosa"], "piece", 260, 4, 30, 14, 2.5, fried=True, group="snack")
_f("kachori", "Kachori", ["khasta kachori"], "piece", 190, 4, 20, 11, 2, fried=True, group="snack")
_f("pakora", "Pakora / bhaji (5 pieces)", ["pakoda", "bhajji", "bajji", "onion bhaji"], "plate",
   280, 7, 26, 17, 3, fried=True, group="snack")
_f("vada_pav", "Vada pav", ["wada pav"], "piece", 300, 7, 42, 12, 3, fried=True, group="snack")
_f("pav_bhaji", "Pav bhaji (2 pav)", [], "plate", 600, 14, 80, 25, 9, veg=1, group="snack")
_f("misal_pav", "Misal pav", [], "plate", 550, 18, 70, 22, 10, prot=1, fried=True, group="snack")
_f("pani_puri", "Pani puri (6)", ["golgappa", "puchka", "gol gappe"], "plate", 200, 4, 32, 7, 2, group="snack")
_f("bhel", "Bhel puri", ["churmuri", "jhal muri"], "plate", 250, 6, 40, 8, 3, group="snack")
_f("sev_puri", "Sev puri / dahi puri", ["dahi puri", "papdi chaat", "chaat"], "plate", 300, 7, 38, 13, 3,
   fried=True, group="snack")
_f("dhokla", "Dhokla (4 pieces)", ["khaman", "khaman dhokla"], "plate", 160, 6, 24, 5, 2, group="snack")
_f("aloo_tikki", "Aloo tikki", ["tikki", "cutlet"], "piece", 150, 2, 20, 7, 2, fried=True, group="snack")
_f("chole_bhature", "Chole bhature (2 bhature)", [], "plate", 650, 16, 80, 30, 10, prot=1, fried=True)
_f("momos_veg", "Veg momos (6, steamed)", ["momo", "dumplings"], "plate", 250, 8, 40, 6, 2, group="snack")
_f("momos_chicken", "Chicken momos (6, steamed)", ["chicken momo"], "plate", 300, 16, 36, 10, 1, prot=1,
   group="snack")
_f("instant_noodles", "Instant noodles (1 pack)", ["maggi", "noodles packet", "cup noodles"], "pack",
   310, 7, 45, 12, 2, fried=True, group="snack")
_f("hakka_noodles", "Veg hakka noodles", ["chowmein", "chow mein", "noodles"], "plate", 450, 9, 65, 17, 4)
_f("fried_rice", "Veg fried rice", ["fried rice"], "plate", 450, 9, 70, 15, 3)
_f("chicken_fried_rice", "Chicken / egg fried rice", ["egg fried rice"], "plate", 550, 22, 70, 20, 3, prot=1)
_f("gobi_manchurian", "Gobi / veg manchurian", ["manchurian", "gobi 65"], "katori", 300, 6, 30, 18, 3,
   fried=True)
_f("namkeen", "Namkeen / mixture (handful)", ["mixture", "chivda", "bhujia", "sev", "khara"], "handful",
   160, 4, 14, 10, 2, fried=True, group="snack")
_f("chips", "Potato chips (small pack)", ["crisps", "wafers", "lays"], "pack", 160, 2, 15, 10, 1, fried=True,
   group="snack", kind=S)
_f("biscuits", "Plain biscuits (4)", ["marie", "glucose biscuits", "rusk"], "4 pieces", 120, 2, 20, 3.5, 0.5,
   group="snack", kind=S)
_f("cream_biscuits", "Cream / chocolate biscuits (3)", ["cookies", "cream biscuit"], "3 pieces", 150, 1.5, 21, 7,
   0.5, sugary=1, group="snack", kind=S)
_f("roasted_chana", "Roasted chana (handful)", ["bhuna chana", "putani"], "handful", 110, 6, 18, 1.5, 5,
   prot=0.5, group="snack", kind=S)
_f("peanuts", "Peanuts (handful)", ["groundnuts", "moongphali", "kadalekai"], "handful", 170, 7.5, 5, 14, 2.5,
   prot=0.5, group="snack", kind=S)
_f("almonds", "Almonds (10)", ["badam", "nuts"], "10 pieces", 70, 2.5, 2.5, 6, 1.5, group="snack", kind=S)
_f("makhana", "Roasted makhana (bowl)", ["fox nuts", "lotus seeds"], "bowl", 95, 2.5, 19, 0.5, 2, group="snack")
_f("sandwich_veg", "Veg sandwich (grilled)", ["sandwich", "bombay sandwich"], "piece", 280, 9, 38, 10, 4,
   group="snack")

# --- Drinks & dairy ---------------------------------------------------------
_f("chai", "Chai with milk & sugar", ["tea", "chai", "masala chai", "cutting chai", "chaha"], "cup", 90, 2.5, 12, 3, 0,
   sugary=1, group="drink", kind=S)
_f("chai_no_sugar", "Chai without sugar", ["tea without sugar", "sugar free tea"], "cup", 45, 2.5, 4, 3, 0,
   group="drink", kind=S)
_f("coffee", "Coffee with milk & sugar", ["filter coffee", "kaapi", "cappuccino", "latte"], "cup",
   100, 3, 12, 4, 0, sugary=1, group="drink", kind=S)
_f("coffee_no_sugar", "Coffee without sugar", ["black coffee", "americano", "espresso"], "cup", 10, 0.5, 1, 0, 0,
   group="drink", kind=S)
_f("green_tea", "Green / black tea (plain)", ["green tea", "lemon tea", "herbal tea"], "cup", 2, 0, 0, 0, 0,
   group="drink", kind=S)
_f("milk", "Milk (toned)", ["doodh", "glass of milk", "haldi doodh"], "glass", 120, 6.5, 9.5, 6, 0, prot=0.5,
   group="drink", kind=S)
_f("curd", "Curd / dahi", ["dahi", "yogurt", "yoghurt", "mosaru", "thayir"], "katori", 60, 3.5, 4.7, 3.3, 0,
   prot=0.5, kind=S)
_f("buttermilk", "Buttermilk / chaas", ["chaas", "majjige", "mor", "chhachh"], "glass", 40, 2, 3, 2, 0,
   group="drink", kind=S)
_f("lassi", "Sweet lassi", ["lassi", "mango lassi"], "glass", 260, 8, 40, 7, 0, sugary=1, group="drink")
_f("soft_drink", "Soft drink (can)", ["cola", "soda", "coke", "pepsi", "cold drink", "thums up", "sprite"], "can",
   140, 0, 35, 0, 0, sugary=1, group="drink", kind=S)
_f("diet_soda", "Diet / zero soft drink", ["diet coke", "coke zero"], "can", 1, 0, 0, 0, 0, group="drink", kind=S)
_f("packaged_juice", "Packaged fruit juice", ["frooti", "maaza", "juice box", "tetra pack juice"], "200 ml",
   110, 0.5, 26, 0, 0, sugary=1, group="drink", kind=S)
_f("fresh_juice", "Fresh fruit juice (no sugar)", ["orange juice", "mosambi juice", "fresh juice"], "glass",
   90, 1.5, 21, 0.4, 0.4, veg=1, group="drink", kind=S)
_f("sugarcane_juice", "Sugarcane juice", ["ganne ka juice", "kabbu juice"], "glass", 180, 0, 45, 0, 0,
   sugary=1, group="drink", kind=S)
_f("coconut_water", "Coconut water", ["tender coconut", "nariyal pani", "elaneer"], "glass", 45, 1.7, 9, 0.5, 0,
   group="drink", kind=S)
_f("milkshake", "Milkshake", ["cold coffee", "shake", "badam milk"], "glass", 300, 8, 45, 10, 0, sugary=1,
   group="drink")
_f("protein_shake", "Protein shake (1 scoop in water)", ["whey", "protein powder"], "scoop", 120, 24, 3, 1.5, 0,
   prot=1, group="drink", kind=S)
_f("beer", "Beer (bottle, 650 ml)", ["beer"], "bottle", 280, 2, 24, 0, 0, group="drink", kind=S)
_f("spirits", "Spirits (1 peg, 30 ml)", ["whisky", "rum", "vodka", "gin", "peg"], "peg", 70, 0, 0, 0, 0,
   group="drink", kind=S)
_f("wine", "Wine (glass, 150 ml)", ["red wine", "white wine"], "glass", 125, 0, 4, 0, 0, group="drink", kind=S)

# --- Fruit --------------------------------------------------------------------
for fid, name, aliases, unit, kcal, p, c, f, fib in (
    ("banana", "Banana", ["kela", "bale hannu", "vazhaipazham"], "piece", 105, 1.3, 27, 0.4, 3.1),
    ("apple", "Apple", ["seb"], "piece", 95, 0.5, 25, 0.3, 4.4),
    ("mango", "Mango", ["aam", "mavinahannu"], "cup", 99, 1.4, 25, 0.6, 2.6),
    ("orange", "Orange / mosambi", ["santra", "mosambi", "sweet lime", "kinnow"], "piece", 62, 1.2, 15, 0.2, 3.1),
    ("papaya", "Papaya", ["papita"], "cup", 62, 0.7, 16, 0.4, 2.5),
    ("guava", "Guava", ["amrood", "peru", "seebe"], "piece", 68, 2.6, 14, 1, 5.4),
    ("grapes", "Grapes", ["angoor"], "cup", 104, 1.1, 27, 0.2, 1.4),
    ("watermelon", "Watermelon", ["tarbooz", "kalingad"], "cup", 46, 0.9, 11.5, 0.2, 0.6),
    ("pomegranate", "Pomegranate", ["anar", "dalimbe"], "half cup", 72, 1.5, 16, 1, 3.5),
    ("chikoo", "Chikoo / sapota", ["sapota", "chiku"], "piece", 83, 0.4, 20, 1.1, 5.3),
    ("pineapple", "Pineapple", ["ananas"], "cup", 82, 0.9, 22, 0.2, 2.3),
    ("fruit_salad", "Fruit bowl (mixed, no sugar)", ["fruit salad", "cut fruit", "fruits"], "bowl", 100, 1, 25, 0.3, 3),
    ("dates", "Dates (2)", ["khajoor", "kharjura"], "2 pieces", 45, 0.4, 12, 0, 1.3),
    ("berries", "Berries", ["strawberries", "blueberries", "jamun"], "cup", 60, 1, 14, 0.4, 3),
    ("pear", "Pear", ["nashpati", "naspati"], "piece", 100, 0.6, 27, 0.2, 5.5),
):
    _f(fid, name, aliases, unit, kcal, p, c, f, fib, veg=0 if fid == "dates" else 1, kind=S, group="fruit")

# --- Sweets -------------------------------------------------------------------
for fid, name, aliases, unit, kcal, p, c, f in (
    ("gulab_jamun", "Gulab jamun", ["jamun sweet", "kala jamun"], "piece", 150, 2, 24, 6),
    ("rasgulla", "Rasgulla", ["rosogolla", "rasmalai"], "piece", 120, 2, 26, 1),
    ("jalebi", "Jalebi (2)", ["imarti", "jilebi"], "2 pieces", 180, 1, 30, 7),
    ("kaju_katli", "Kaju katli", ["kaju barfi"], "piece", 70, 1.5, 8, 3.5),
    ("ladoo", "Ladoo", ["laddu", "besan ladoo", "motichoor ladoo", "boondi ladoo"], "piece", 180, 3, 22, 9),
    ("barfi", "Barfi / peda", ["burfi", "peda", "mithai", "sweet"], "piece", 130, 3, 16, 6),
    ("mysore_pak", "Mysore pak", ["mysorepak"], "piece", 180, 1.5, 15, 13),
    ("halwa", "Halwa", ["gajar halwa", "sooji halwa", "sheera", "kesari bath"], "katori", 270, 4, 35, 13),
    ("kheer", "Kheer / payasam", ["payasam", "payasa", "phirni", "seviyan"], "katori", 230, 6, 34, 7),
    ("shrikhand", "Shrikhand", ["amrakhand"], "katori", 250, 6, 38, 8),
    ("ice_cream", "Ice cream (1 scoop)", ["icecream", "kulfi"], "scoop", 125, 2.2, 14, 6.7),
    ("chocolate", "Chocolate bar", ["chocolate", "dairy milk", "candy bar"], "bar", 210, 3, 24, 12),
    ("cake", "Cake / pastry slice", ["pastry", "brownie", "muffin", "cupcake"], "slice", 300, 4, 40, 14),
    ("doughnut", "Doughnut", ["donut"], "piece", 250, 3, 30, 14),
):
    # Counted once, as a sweet (not also as a fried meal).
    _f(fid, name, aliases, unit, kcal, p, c, f, 0.5, sugary=1, group="sweet")

# --- Foreign / fast food ------------------------------------------------------
_f("pizza", "Pizza (1 slice, medium)", ["pizza slice", "margherita"], "slice", 285, 12, 36, 10, 2.5)
_f("burger_veg", "Veg burger", ["aloo tikki burger", "burger"], "piece", 400, 10, 50, 17, 4, fried=True)
_f("burger_chicken", "Chicken burger", ["chicken burger", "zinger"], "piece", 450, 22, 45, 20, 2, prot=1,
   fried=True)
_f("fries", "French fries (medium)", ["fries", "finger chips"], "portion", 365, 4, 48, 17, 4.4, fried=True)
_f("fried_chicken", "Fried chicken (2 pieces)", ["kfc", "fried chicken", "chicken wings"], "2 pieces",
   500, 35, 16, 32, 1, prot=1, fried=True)
_f("pasta_red", "Pasta in red sauce", ["arrabbiata", "spaghetti", "pasta"], "plate", 380, 12, 62, 9, 5)
_f("pasta_white", "Pasta in white sauce", ["alfredo", "mac and cheese", "white sauce pasta"], "plate",
   520, 15, 58, 25, 3)
_f("sandwich_chicken", "Chicken sandwich / sub", ["sub", "club sandwich"], "piece", 360, 22, 36, 14, 3, prot=1)
_f("wrap_veg", "Veg wrap / frankie", ["frankie", "kathi roll", "veg roll"], "piece", 350, 9, 45, 15, 4)
_f("shawarma", "Chicken shawarma / roll", ["shawarma", "chicken roll", "chicken wrap"], "piece",
   500, 28, 45, 22, 3, prot=1)
_f("burrito", "Burrito", ["burrito bowl"], "piece", 600, 24, 72, 22, 9, prot=1)
_f("tacos", "Tacos (2)", ["taco"], "2 pieces", 340, 14, 32, 17, 4, prot=0.5)
_f("sushi", "Sushi (6 pieces)", ["sushi roll", "maki"], "plate", 300, 9, 55, 4, 2)
_f("ramen", "Ramen bowl", ["pho", "noodle soup"], "bowl", 450, 18, 60, 15, 3, prot=0.5)
_f("caesar_salad", "Caesar salad", ["chicken salad"], "bowl", 350, 20, 12, 25, 3, veg=1, prot=1)
_f("hummus", "Hummus (2 tbsp)", ["hummus"], "2 tbsp", 70, 2, 4, 5, 2)
_f("falafel", "Falafel (4)", ["falafel"], "4 pieces", 230, 9, 22, 12, 5, fried=True, prot=0.5)
_f("soup", "Soup (veg, clear or tomato)", ["tomato soup", "sweet corn soup", "manchow soup"], "bowl",
   100, 3, 15, 3, 2, veg=0.5)
_f("oats", "Oats porridge with milk", ["oatmeal", "porridge", "masala oats"], "bowl", 270, 12, 37, 8, 4, prot=0.5)
_f("cornflakes", "Cornflakes with milk", ["cereal", "chocos", "muesli"], "bowl", 230, 9, 34, 6, 1)
_f("toast_butter", "Toast with butter", ["bread butter", "butter toast"], "slice", 105, 2, 13, 5, 0.6, kind=S)
_f("peanut_butter", "Peanut butter (1 tbsp)", ["pb"], "tbsp", 95, 3.5, 3.5, 8, 1, kind=S)
_f("cheese", "Cheese slice", ["cheese", "processed cheese"], "slice", 60, 3.5, 1.5, 4.5, 0, kind=S)

# --- Add-ons --------------------------------------------------------------------
_f("ghee", "Ghee (1 tsp)", ["desi ghee", "tuppa", "neyyi"], "tsp", 45, 0, 0, 5, 0, kind=S, group="extra")
_f("butter", "Butter (1 tsp)", ["makhan", "amul butter"], "tsp", 36, 0, 0, 4, 0, kind=S, group="extra")
_f("oil", "Cooking oil (1 tsp)", ["oil", "tel"], "tsp", 40, 0, 0, 4.5, 0, kind=S, group="extra")
_f("sugar", "Sugar (1 tsp)", ["chini", "sakkare"], "tsp", 16, 0, 4, 0, 0, kind=S, group="extra")
_f("pickle", "Pickle (1 tbsp)", ["achar", "uppinakayi", "oorugai"], "tbsp", 30, 0.2, 1, 3, 0.5, kind=S,
   group="extra")
_f("papad", "Papad", ["appalam", "pappadam", "happala"], "piece", 40, 2, 6, 1, 1, kind=S, group="extra")


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def search(query: str, extra: Optional[List[dict]] = None, limit: int = 10) -> List[dict]:
    """Foods matching a name, Hindi/regional word or partial word, best first.
    ``extra`` are the person's own foods (searched first on ties)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    qt = _tokens(q)
    scored = []
    for food in list(extra or []) + list(FOODS.values()):
        names = [food["name"].lower()] + food.get("aliases", [])
        best = 0
        for n in names:
            if n == q:
                best = max(best, 100)
            elif n.startswith(q):
                best = max(best, 80)
            elif all(any(w.startswith(t) for w in _tokens(n)) for t in qt):
                best = max(best, 60)
            elif q in n:
                best = max(best, 40)
            else:
                # Some words match ("bhindi fry" → Bhindi sabzi): weaker, by share of words.
                words = _tokens(n)
                hit = [t for t in qt if len(t) >= 3 and any(w.startswith(t) for w in words)]
                if hit:
                    best = max(best, int(30 * len(hit) / len(qt)))
        if best:
            scored.append((best, 1 if food.get("custom") else 0, food))
    scored.sort(key=lambda s: (-s[0], -s[1], len(s[2]["name"])))
    return [s[2] for s in scored[:limit]]


def public(food: dict) -> dict:
    return {k: food[k] for k in ("id", "name", "unit", "kcal", "protein_g", "carbs_g", "fat_g", "fibre_g", "counts",
                                 "fried", "group") if k in food} | {"custom": bool(food.get("custom"))}


def nutrition(food: dict, amount: Decimal) -> dict:
    """Totals for ``amount`` servings, with the calorie range."""
    lo, hi = RANGE[food.get("kind", "dish")]
    kcal = Decimal(str(food["kcal"])) * amount
    out = {"kcal": kcal, "kcal_low": kcal * lo, "kcal_high": kcal * hi}
    for k in ("protein_g", "carbs_g", "fat_g", "fibre_g"):
        out[k] = Decimal(str(food.get(k) or 0)) * amount
    for k, v in food["counts"].items():
        out[k] = Decimal(str(v or 0)) * amount
    out["fried"] = amount if food.get("fried") else Decimal(0)
    return out
