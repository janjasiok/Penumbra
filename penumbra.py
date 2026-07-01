# -*- coding: utf-8 -*-
"""
Penumbra
--------
Vygeneruje mapu světa den/noc (terminátor v aktuálním čase) a nastaví ji jako
tapetu plochy (Windows / macOS). Kreslí soumrak, světla měst, mraky, časová
pásma, dráhu Slunce i Měsíce (s fází), polární záři a družice (ISS, Hubble,
Tiangong) s dráhou, výškou a rychlostí. Vzhled laděný do palety NASA.

Spuštění:   python penumbra.py
Závislosti: pip install -r requirements.txt   (Pillow, numpy, sgp4)
Assety:     assets/textures, assets/fonts, assets/data (viz README.md)

Pro automatické obnovování použij Plánovač úloh (Windows) / cron (macOS).
"""

import os, sys, math, json, ctypes, datetime, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --- cesty k assetům a cache ------------------------------------------------
BASE   = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
CACHE  = os.path.join(BASE, ".cache")

def _asset(*parts):
    return os.path.join(ASSETS, *parts)

def _cache(name):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, name)

# ============================================================
#  NASTAVENÍ  —  vše, co se běžně mění, je tady
#  Rychlý přehled, kde co:
#    • střed mapy ......... CITY / CENTER_LON / CITIES
#    • rozlišení & ořez ... SCREEN, MAP_FILL
#    • co se kreslí ....... SHOW_GRID, SHOW_CITY_MARKER, SHOW_SUBSOLAR, SHOW_STARS
#    • vzhled Země ........ USE_TEXTURE, NIGHT_BRIGHTNESS, LIGHTS_GAIN, TEX_*, SUPERSAMPLE
#    • mraky .............. CLOUDS, CLOUD_OPACITY, CLOUD_DRIFT, CLOUDS_LIVE_*
#    • časová pásma ....... TIMEZONES, SHOW_TZ_CLOCK, SHOW_TZ_NUMBERS, HIGHLIGHT_CITY_ZONE, TZ_DATA
#    • vinětace ........... VIGNETTE, VIGNETTE_STRENGTH, VIGNETTE_SIZE
#    • družice ............ SHOW_SATELLITES, SATELLITES, SAT_TRACK_MIN_BEFORE/AFTER
#    • Slunce/Měsíc ....... SHOW_SUN_PATH, SHOW_MOON, SHOW_MOON_PATH, PATH_HOURS
#    • polární záře ....... SHOW_AURORA, AURORA_GAIN, AURORA_COLOR
# ============================================================

# --- STŘED MAPY -------------------------------------------------------------
CITY = "Ostrava"               # střed mapy: vyber klíč z katalogu CITIES níže (nebo použij CENTER_LON)
CENTER_LON = None              # ručně zem. délka středu; když není None, přebije CITY (např. 18.29)

# katalog měst:  "název": (zeměpisná délka, zeměpisná šířka, IANA časová zóna)
CITIES = {
    "Ostrava": (18.29, 49.84, "Europe/Prague"),
    "Praha":   (14.42, 50.08, "Europe/Prague"),
    "Londýn":  (-0.13, 51.51, "Europe/London"),
    "Paříž":   ( 2.35, 48.86, "Europe/Paris"),
    "Vídeň":   (16.37, 48.21, "Europe/Vienna"),
    "New York":(-74.01, 40.71, "America/New_York"),
    "Tokio":   (139.69, 35.69, "Asia/Tokyo"),
    "Sydney":  (151.21, -33.87, "Australia/Sydney"),
}

# --- ROZLIŠENÍ A OŘEZ -------------------------------------------------------
SCREEN = None                  # None = auto-detekce rozlišení; jinak (šířka, výška), např. (2560, 1440)
MAP_FILL = "contain"           # "cover" = přes celou plochu (ořízne kraje) | "contain" = celá mapa + okraje s hvězdami

# --- ZAMYKACÍ / PŘIHLAŠOVACÍ OBRAZOVKA (Windows) ----------------------------
SET_LOCKSCREEN = True          # nastavit render i jako zamykací (a tím i přihlašovací) obrazovku; vyžaduje admin práva

# --- CO SE KRESLÍ -----------------------------------------------------------
SHOW_GRID        = True        # zeměpisná síť (rovnoběžky; rovné poledníky jen bez dat pásem)
SHOW_CITY_MARKER = True        # tečka + název vystředěného města + zlatý poledník
SHOW_SUBSOLAR    = True        # bod, kde je Slunce přesně v zenitu
SHOW_STARS       = True        # hvězdy v okrajích (jen v režimu "contain")

# --- VZHLED ZEMĚ ------------------------------------------------------------
USE_TEXTURE = True             # True = satelitní textura + světla měst; False = ploché barvy (z land.json)
NIGHT_BRIGHTNESS = 0.26        # jas noční strany (víc = líp vidět mapu; 0.05 ≈ skoro černá)
LIGHTS_GAIN = 1.75             # jas městských světel na temné straně
SUPERSAMPLE = 2                # antialiasing/kvalita: 2 = hladší (pomalejší), 1 = rychlejší
TEX_DAY     = "earth_day.jpg"  # denní textura 8K (equirekt., 2:1, střed 0°)
TEX_NIGHT   = "earth_night.jpg"# noční světla měst 8K

# --- MRAKY ------------------------------------------------------------------
CLOUDS       = True            # mraky na denní straně
TEX_CLOUDS   = "earth_clouds.jpg"
CLOUD_OPACITY = 0.85           # krytí mraků (0–1)
CLOUD_DRIFT  = 6.0             # pomalé otáčení mraků (°/h) – posouvají se i mezi aktualizacemi
CLOUDS_LIVE_URL = ""           # nepovinné: URL na živou mapu mraků (equirekt. 2:1). Prázdné = statická. Příklad viz fetch_live_clouds()
CLOUDS_LIVE_HOURS = 3          # interval stahování živé mapy (h)

# --- ČASOVÁ PÁSMA -----------------------------------------------------------
TIMEZONES = True               # skutečné hranice časových pásem (zubaté, kopírují státy)
SHOW_TZ_CLOCK = False          # hodiny pásem nahoře + místní čas města (False = čas vůbec nezobrazovat)
SHOW_TZ_NUMBERS = False        # číselné označení pásem nahoře (UTC offsety: −6, 0, +1, +8…)
HIGHLIGHT_CITY_ZONE = True     # jemně podbarvit časové pásmo vystředěného města
TZ_DATA   = "timezones.json"   # hranice pásem (Natural Earth); chybí-li, použijí se rovné poledníky po 15°

# --- VINĚTACE (ztmavení horního a dolního okraje) ---------------------------
VIGNETTE          = True        # lineární ztmavení nahoře a dole
VIGNETTE_STRENGTH = 0.85        # síla ztmavení na okraji (0–1; 0 = vypnuto)
VIGNETTE_SIZE     = 0.04        # výška ztmaveného pruhu na každém okraji (podíl výšky obrazu)

# --- DRUŽICE (ISS, Hubble, Tiangong…) ---------------------------------------
SHOW_SATELLITES = True         # dráhy + aktuální polohy družic; vyžaduje internet + knihovnu sgp4
SHOW_ISS_FOOTPRINT = False     # kružnice dosahu ISS (oblast, odkud je nad obzorem)
SAT_TRACK_MIN_BEFORE = 100     # minut dráhy dozadu
SAT_TRACK_MIN_AFTER  = 100     # minut dráhy dopředu
# 100+100 ≈ oběh na každou stranu: úsek u družice tak sahá od levého k pravému okraji jako jedna
# souvislá čára; zbytek (zabalený přes datovou hranici) se zahodí (kreslí se jen úsek u družice)
# seznam družic:  (popisek, NORAD katalogové číslo, barva RGB)
SATELLITES = [
    ("ISS",      25544, (252, 61, 33)),    # NASA červená
    ("Hubble",   20580, (130, 205, 255)),  # světle modrá
    ("Tiangong", 48274, (255, 200, 70)),   # jantarová
]

# --- DRÁHY SLUNCE A MĚSÍCE + MĚSÍC ------------------------------------------
SHOW_SUN_PATH  = True          # dráha subsolárního bodu (kudy dnes prochází Slunce)
SHOW_MOON      = True          # Měsíc: sublunární bod + fáze
SHOW_MOON_PATH = True          # dráha sublunárního bodu (kudy prochází Měsíc)
PATH_HOURS     = 12            # délka drah dozadu i dopředu (h); 12 = celý den
TEX_MOON       = "moon.jpg"    # textura povrchu Měsíce (equirekt. 2:1); chybí-li, kreslí se plochá šedá placka
TEX_SUN        = "sun.jpg"     # textura fotosféry Slunce (equirekt. 2:1); chybí-li, kreslí se zlatý kotouč

# --- POLÁRNÍ ZÁŘE (aurora) --------------------------------------------------
SHOW_AURORA  = False           # auroral oval na noční straně (živá data NOAA OVATION; vyžaduje internet)
AURORA_GAIN  = 1.0             # síla záře (víc = výraznější)
AURORA_COLOR = (95, 255, 150)  # barva záře (zelená)

# --- PÍSMO (NASA Horizon Design System) -------------------------------------
FONT_MAIN = "Inter-SemiBold.ttf" # popisky – Inter (font NASA pro displeje/vizualizace)
FONT_MONO = "DMMono-Medium.ttf"  # čísla – DM Mono (technické/číselné readouty NASA)

# --- BARVY ------------------------------------------------------------------
# NASA paleta (značkové barvy)
NASA_BLUE  = (11, 61, 145)     # #0B3D91
NASA_RED   = (252, 61, 33)     # #FC3D21
NASA_LBLUE = (150, 178, 235)   # světlejší modrá pro tenké linky (čitelná na tmavém)
# zvýraznění časového pásma vystředěného města (laditelné — ať nesplývá s oceánem)
ZONE_FILL = (8, 30, 82)        # tmavě modré podbarvení pásma (ztlumí oblast)
ZONE_EDGE = (180, 210, 255)    # světlý obrys pásma (nese hranici)
ZONE_FILL_ALPHA = 70           # krytí výplně (0–255)
ZONE_EDGE_ALPHA = 210          # krytí obrysu (0–255; víc = výraznější okraj)
# barvy podkladu (záloha, když nejsou textury)
C_SPACE  = (5, 7, 15)
C_OCEAN  = (20, 58, 82)
C_LAND   = (63, 125, 84)
C_GOLD   = (255, 224, 138)

# TODO (živá data mraků): NASA GIBS – viz CLOUDS_LIVE_URL a docstring fetch_live_clouds()
# Textury: Solar System Scope (CC BY 4.0; podklady NASA). Pásma a pevniny: Natural Earth.

OUTPUT = os.path.join(BASE, "penumbra.png")

# ============================================================
#  ASTRONOMIE — subsolární bod (kde je Slunce v zenitu)
# ============================================================
def subsolar(dt_utc):
    jd = dt_utc.timestamp() / 86400.0 + 2440587.5
    n  = jd - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    alpha = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam)))
    decl  = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    gmst = (280.46061837 + 360.98564736629 * n) % 360
    lon = ((alpha - gmst + 180) % 360) - 180
    return decl, lon          # zeměpisná šířka a délka subsolárního bodu

def _moon_subpoint(dt_utc):
    """Zeměpisná šířka a délka sublunárního bodu (kde je Měsíc v zenitu). Nízká přesnost (~0,1°)."""
    jd = dt_utc.timestamp() / 86400.0 + 2440587.5
    T = (jd - 2451545.0) / 36525.0
    s = lambda deg: math.sin(math.radians(deg))
    lam = (218.32 + 481267.8813 * T
           + 6.29 * s(134.9 + 477198.85 * T) - 1.27 * s(259.2 - 413335.38 * T)
           + 0.66 * s(235.7 + 890534.23 * T) + 0.21 * s(269.9 + 954397.70 * T)
           - 0.19 * s(357.5 + 35999.05 * T) - 0.11 * s(186.6 + 966404.05 * T))
    beta = (5.13 * s(93.3 + 483202.03 * T) + 0.28 * s(228.2 + 960400.87 * T)
            - 0.28 * s(318.3 + 6003.18 * T) - 0.17 * s(217.6 - 407332.20 * T))
    eps = math.radians(23.439 - 0.0000004 * (jd - 2451545.0))
    lam_r, beta_r = math.radians(lam), math.radians(beta)
    dec = math.asin(math.sin(beta_r) * math.cos(eps) + math.cos(beta_r) * math.sin(eps) * math.sin(lam_r))
    ra = math.atan2(math.sin(lam_r) * math.cos(eps) - math.tan(beta_r) * math.sin(eps), math.cos(lam_r))
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360
    lon = ((math.degrees(ra) - gmst + 180) % 360) - 180
    return math.degrees(dec), lon

def _moon_phase(dt_utc):
    """Osvětlený podíl (0–1) a zda Měsíc dorůstá (waxing)."""
    jd = dt_utc.timestamp() / 86400.0 + 2440587.5
    T = (jd - 2451545.0) / 36525.0
    D  = (297.8502 + 445267.1115 * T) % 360                  # střední elongace
    M  = math.radians((357.5291 + 35999.0503 * T) % 360)
    Mp = math.radians((134.9634 + 477198.8676 * T) % 360)
    Dr = math.radians(D)
    i = (180 - D - 6.289 * math.sin(Mp) + 2.100 * math.sin(M)
         - 1.274 * math.sin(2 * Dr - Mp) - 0.658 * math.sin(2 * Dr)
         - 0.214 * math.sin(2 * Mp) - 0.110 * math.sin(Dr))
    frac = (1 + math.cos(math.radians(i))) / 2
    return frac, (D < 180)

# ============================================================
#  POMOCNÉ
# ============================================================
def screen_size():
    if SCREEN:
        return SCREEN
    if sys.platform.startswith("win"):
        try:
            u = ctypes.windll.user32; u.SetProcessDPIAware()
            return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        except Exception:
            pass
    elif sys.platform == "darwin":
        # macOS: nativní rozlišení v pixelech (kvůli Retině)
        try:
            import re
            out = subprocess.check_output(["system_profiler", "SPDisplaysDataType"],
                                          text=True, timeout=8)
            mm = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", out)
            if mm:
                return int(mm.group(1)), int(mm.group(2))
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
                text=True, timeout=8)
            n = [int(x) for x in out.replace(",", " ").split()]
            if len(n) == 4:
                return n[2], n[3]
        except Exception:
            pass
    return 1920, 1080            # fallback (jinak doporučuju nastavit SCREEN ručně)

def load_land():
    path = _asset("data", "land.json")
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print("Pozor: land.json nenačten (%s) — mapa bude bez pevnin." % e)
        return []

def load_font(size, mono=False):
    if mono:
        cand = [FONT_MONO, "DMMono-Medium.ttf", "DMMono-Regular.ttf", "consola.ttf", "DejaVuSansMono.ttf"]
    else:
        cand = [FONT_MAIN, "Inter-SemiBold.ttf", "Inter-var.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
    for n in cand:
        for p in (_asset("fonts", n), n):                # nejdřív přibalené, pak systémové
            try:
                ft = ImageFont.truetype(p, size)
                if not mono and "Inter" in n:            # variabilní Inter → o něco silnější řez
                    try:
                        ax = ft.get_variation_axes()
                        if ax:
                            ft.set_variation_by_axes([min(32, max(14, size)), 560][:len(ax)])
                    except Exception:
                        pass
                return ft
            except Exception:
                continue
    return ImageFont.load_default()

def _marker_reticle(color, r):
    """Zaměřovací terčík (jádro + prstenec + křížové rysky + záře) ve stylu sledování misí."""
    SS = 4
    pad = int(r * 2.8)
    sz = pad * 2
    im = Image.new("RGBA", (sz * SS, sz * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = pad * SS
    col = tuple(color)
    gr = int(r * 2.5 * SS)                                   # výraznější měkká záře
    for rr in range(gr, 0, -1):
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=col + (int(100 * (1 - rr / gr) ** 1.6),))
    im = im.filter(ImageFilter.GaussianBlur(r * SS * 0.25))  # změkčit jen záři
    d = ImageDraw.Draw(im)
    ring = int(r * SS)                                       # prstenec (ostrý)
    d.ellipse([c - ring, c - ring, c + ring, c + ring], outline=col + (255,),
              width=max(SS, int(0.16 * r * SS)))
    t0, t1 = int(r * 1.18 * SS), int(r * 1.75 * SS)          # křížové rysky N/E/S/W
    wt = max(SS, int(0.16 * r * SS))
    d.line([c, c - t0, c, c - t1], fill=col + (255,), width=wt)
    d.line([c, c + t0, c, c + t1], fill=col + (255,), width=wt)
    d.line([c - t0, c, c - t1, c], fill=col + (255,), width=wt)
    d.line([c + t0, c, c + t1, c], fill=col + (255,), width=wt)
    cr = int(r * 0.42 * SS)                                  # bílé jádro
    d.ellipse([c - cr, c - cr, c + cr, c + cr], fill=(255, 255, 255, 255))
    return im.resize((sz, sz), Image.LANCZOS), pad

_SUNTEX = False     # False = nenačteno, None = není k dispozici, jinak np.float32 pole
def _sun_texture():
    global _SUNTEX
    if _SUNTEX is False:
        try:
            im = Image.open(_asset("textures", TEX_SUN)).convert("RGB")
            _SUNTEX = np.asarray(im, dtype=np.float32)
        except Exception:
            _SUNTEX = None
    return _SUNTEX

def _marker_sun(r):
    """Zářící Slunce – měkká koróna (pro tmavou stranu) + kotouč fotosféry ze skutečné
    textury se ztmaveným okrajem (limb darkening). Bez textury kreslí zlatý kotouč s lemem."""
    SS = 4
    pad = int(r * 5.0)
    sz = pad * 2
    im = Image.new("RGBA", (sz * SS, sz * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = pad * SS
    gr = int(r * 4.5 * SS)                                   # koróna s hladkým spádem do nuly
    for rr in range(gr, 0, -1):
        t = rr / gr                                          # 1 na okraji, 0 ve středu
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=(255, 239, 208, int(150 * (1 - t) ** 2.8)))
    im = im.filter(ImageFilter.GaussianBlur(r * SS * 0.35))  # změkčit jen korónu (žádné hrany)
    tex = _sun_texture()
    if tex is not None:
        R = r * 1.15 * SS                                    # ortografická projekce fotosféry
        szpx = sz * SS
        yy, xx = np.mgrid[0:szpx, 0:szpx]
        X = xx - c; Y = yy - c
        disk = X * X + Y * Y <= R * R
        nx = X / R; ny = Y / R
        nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        th, tw = tex.shape[:2]
        lat = np.degrees(np.arcsin(np.clip(-ny, -1.0, 1.0)))
        lon = np.degrees(np.arctan2(nx, nz))
        u = (((lon + 180.0) / 360.0 * tw).astype(np.int32)) % tw
        v = np.clip(((90.0 - lat) / 180.0 * th).astype(np.int32), 0, th - 1)
        col = tex[v, u].astype(np.float32)
        col *= (nz ** 0.45)[..., None]                       # ztmavení okraje (limb darkening)
        col = np.clip(col * 1.15 + 10.0, 0, 255)
        arr = np.asarray(im).astype(np.uint8).copy()
        rgb = col.astype(np.uint8)
        arr[disk] = np.concatenate([rgb[disk], np.full((int(disk.sum()), 1), 255, np.uint8)], axis=1)
        im = Image.fromarray(arr, "RGBA")
        ImageDraw.Draw(im).ellipse([c - R, c - R, c + R, c + R],
                                   outline=(180, 90, 20, 230), width=max(SS, int(0.10 * R)))
    else:
        d = ImageDraw.Draw(im)
        disk = int(r * 1.15 * SS)                           # zlatý kotouč (plochá záloha)
        core = (255, 250, 238); edge = (255, 176, 48)
        for rr in range(disk, 0, -1):
            t = rr / disk
            colf = tuple(int(core[i] + (edge[i] - core[i]) * t) for i in range(3))
            d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=colf + (255,))
        d.ellipse([c - disk, c - disk, c + disk, c + disk], outline=(206, 112, 24, 255),
                  width=max(SS, int(0.22 * r * SS)))
    return im.resize((sz, sz), Image.LANCZOS), pad

_MOONTEX = False    # False = nenačteno, None = není k dispozici, jinak np.float32 pole
def _moon_texture():
    global _MOONTEX
    if _MOONTEX is False:
        try:
            im = Image.open(_asset("textures", TEX_MOON)).convert("RGB")
            _MOONTEX = np.asarray(im, dtype=np.float32)
        except Exception:
            _MOONTEX = None
    return _MOONTEX

def _marker_moon(r, frac, waxing):
    """Měsíc se skutečným povrchem (textura přivrácené strany) a správnou fází
    (osvětlená/stinná strana) + jemná záře. Bez textury kreslí plochou šedou placku."""
    SS = 4
    R = r * SS
    pad = int(r * 2.4)
    sz = pad * 2
    im = Image.new("RGBA", (sz * SS, sz * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = pad * SS
    gr = int(r * 2.2 * SS)                                   # jemná chladná záře
    for rr in range(gr, 0, -1):
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=(205, 216, 240, int(70 * (1 - rr / gr) ** 1.6)))
    im = im.filter(ImageFilter.GaussianBlur(r * SS * 0.25))
    arr = np.asarray(im).astype(np.uint8).copy()
    yy, xx = np.mgrid[0:sz * SS, 0:sz * SS]
    X = xx - c; Y = yy - c
    disk = X * X + Y * Y <= R * R
    xr = np.sqrt(np.maximum(R * R - Y * Y, 0.0))
    xt = (1 - 2 * frac) * xr                                 # terminátor
    lit = disk & ((X >= xt) if waxing else (X <= -xt))
    tex = _moon_texture()
    if tex is not None:
        th, tw = tex.shape[:2]                               # ortografická projekce přivrácené strany
        nx = X / R; ny = Y / R
        nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        lat = np.degrees(np.arcsin(np.clip(-ny, -1.0, 1.0)))
        lon = np.degrees(np.arctan2(nx, nz))                 # −90..90 přes viditelný kotouč
        u = (((lon + 180.0) / 360.0 * tw).astype(np.int32)) % tw
        v = np.clip(((90.0 - lat) / 180.0 * th).astype(np.int32), 0, th - 1)
        col = tex[v, u].astype(np.float32)                   # navzorkovaný povrch
        col[lit] = np.clip(col[lit] * 1.25 + 12.0, 0, 255)   # osvětlená strana zjasnit (ať jsou moře vidět)
        shadow = disk & ~lit
        col[shadow] = col[shadow] * 0.18 + np.array([2.0, 4.0, 12.0], np.float32)  # stín + chladný nádech
        rgb = np.clip(col, 0, 255).astype(np.uint8)
        arr[disk] = np.concatenate([rgb[disk], np.full((int(disk.sum()), 1), 255, np.uint8)], axis=1)
    else:
        arr[disk & ~lit] = [70, 76, 92, 255]                # stinná strana (plochá záloha)
        arr[lit] = [236, 239, 247, 255]                      # osvětlená strana
    im = Image.fromarray(arr, "RGBA")
    d = ImageDraw.Draw(im)
    d.ellipse([c - R, c - R, c + R, c + R], outline=(150, 162, 190, 210), width=max(SS, int(0.06 * R)))
    return im.resize((sz, sz), Image.LANCZOS), pad

def _marker_city(r):
    """Majákový terčík vystředěného města (jádro + dva prstence + jemná záře)."""
    SS = 4
    pad = int(r * 3.0)
    sz = pad * 2
    im = Image.new("RGBA", (sz * SS, sz * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = pad * SS
    gr = int(r * 2.7 * SS)                                   # výraznější měkká bílá záře
    for rr in range(gr, 0, -1):
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=(255, 255, 255, int(90 * (1 - rr / gr) ** 1.6)))
    im = im.filter(ImageFilter.GaussianBlur(r * SS * 0.25))  # změkčit jen záři
    d = ImageDraw.Draw(im)
    r1 = int(r * 1.85 * SS)                                  # vnější prstenec (NASA modrá)
    d.ellipse([c - r1, c - r1, c + r1, c + r1], outline=(120, 160, 235, 240), width=max(SS, int(0.11 * r * SS)))
    r2 = int(r * 1.05 * SS)                                  # vnitřní bílý prstenec
    d.ellipse([c - r2, c - r2, c + r2, c + r2], outline=(255, 255, 255, 255), width=max(SS, int(0.13 * r * SS)))
    cr = int(r * 0.5 * SS)                                   # bílé jádro
    d.ellipse([c - cr, c - cr, c + cr, c + cr], fill=(255, 255, 255, 255))
    return im.resize((sz, sz), Image.LANCZOS), pad

_SHADOW = (1, 3)   # jednotný směr a délka vrženého stínu (dolů a kousek vpravo)

def _text(md, mapimg, xy, text, font, fill, blur=None):
    """Text s jemným rozostřeným stínem (lepší čitelnost na pestrém podkladu)."""
    if blur is None:
        blur = max(1.5, font.size / 16.0)
    b = md.textbbox((0, 0), text, font=font)
    pad = int(blur * 3) + 2
    layer = Image.new("RGBA", (b[2] - b[0] + pad * 2, b[3] - b[1] + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((pad - b[0], pad - b[1]), text, font=font, fill=(0, 0, 0, 215))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    dx, dy = _SHADOW                                          # jednotný vržený stín
    mapimg.paste(layer, (int(xy[0] - pad + dx), int(xy[1] - pad + dy)), layer)
    md.text(xy, text, font=font, fill=fill)

def _dashed_line(draw, pts, color, width, dash, gap):
    """Přerušovaná (čárkovaná) lomená čára podle délky oblouku."""
    if len(pts) < 2:
        return
    on = True
    left = dash
    prev = pts[0]
    for cur in pts[1:]:
        dx, dy = cur[0] - prev[0], cur[1] - prev[1]
        seglen = math.hypot(dx, dy)
        if seglen < 1e-9:
            prev = cur; continue
        ux, uy = dx / seglen, dy / seglen
        pos, p0 = 0.0, prev
        while pos < seglen:
            step = min(left, seglen - pos)
            p1 = (p0[0] + ux * step, p0[1] + uy * step)
            if on:
                draw.line([p0, p1], fill=color, width=width)
            p0 = p1; pos += step; left -= step
            if left <= 1e-9:
                on = not on
                left = dash if on else gap
        prev = cur

def load_texture(name, size):
    path = _asset("textures", name)
    try:
        im = Image.open(path).convert("RGB").resize(size, Image.LANCZOS)
        return np.asarray(im, dtype=np.float32)
    except Exception:
        return None

_TZCACHE = None
def load_timezones():
    global _TZCACHE
    if _TZCACHE is None:
        path = _asset("data", TZ_DATA)
        try:
            _TZCACHE = json.load(open(path, encoding="utf-8"))
        except Exception:
            _TZCACHE = []
    return _TZCACHE

def _pt_in_rings(lon, lat, rings):
    inside = False
    for ring in rings:
        n = len(ring); j = n - 1
        for i in range(n):
            xi, yi = ring[i]; xj, yj = ring[j]
            if ((yi > lat) != (yj > lat)) and \
               (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
    return inside

def offset_at(lon, lat, tz):
    """UTC offset (h) pro daný bod podle hranic pásem; None když nenalezeno."""
    lon = ((lon + 180) % 360) - 180
    for z, rings in tz:
        if _pt_in_rings(lon, lat, rings):
            return z
    return None

def _sat_tle(catnr):
    """Stáhne (a cachuje ~3 h) TLE družice z Celestraku; vrací (řádek1, řádek2)."""
    import time as _t, urllib.request
    cache = _cache("tle_%s.txt" % catnr)
    def parse(txt):
        ls = [l.strip() for l in txt.splitlines() if l.strip()]
        l1 = next(l for l in ls if l.startswith("1 "))
        l2 = next(l for l in ls if l.startswith("2 "))
        return l1, l2
    try:
        if os.path.exists(cache) and _t.time() - os.path.getmtime(cache) < 3 * 3600:
            return parse(open(cache, encoding="utf-8").read())
        url = "https://celestrak.org/NORAD/elements/gp.php?CATNR=%s&FORMAT=TLE" % catnr
        txt = urllib.request.urlopen(url, timeout=15).read().decode()
        open(cache, "w", encoding="utf-8").write(txt)
        return parse(txt)
    except Exception:
        try:
            return parse(open(cache, encoding="utf-8").read())   # použij starou cache
        except Exception:
            return None

def _sat_latlon(sat, dt):
    from sgp4.api import jday
    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond * 1e-6)
    e, r, v = sat.sgp4(jd, fr)
    if e != 0:
        return None
    x, y, z = r
    n = (jd - 2451545.0) + fr
    g = math.radians((280.46061837 + 360.98564736629 * n) % 360)   # GMST
    xe =  x * math.cos(g) + y * math.sin(g)                          # TEME -> ECEF
    ye = -x * math.sin(g) + y * math.cos(g)
    lon = ((math.degrees(math.atan2(ye, xe)) + 180) % 360) - 180
    lat = math.degrees(math.atan2(z, math.hypot(xe, ye)))
    alt = math.sqrt(x * x + y * y + z * z) - 6371.0          # výška nad povrchem (km)
    spd = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) # rychlost (km/s)
    return lat, lon, alt, spd

def get_aurora():
    """Mřížka pravděpodobnosti polární záře (181×360 = lat −90..90 × lon 0..359, 0–100). None když nelze."""
    if not SHOW_AURORA:
        return None
    import urllib.request, time as _t
    cache = _cache("aurora.json")
    def build(txt):
        d = json.loads(txt)
        A = np.zeros((181, 360), np.float32)
        for lon, lat, val in d["coordinates"]:
            A[int(lat) + 90, int(lon) % 360] = val
        return A
    try:
        if os.path.exists(cache) and _t.time() - os.path.getmtime(cache) < 900:
            return build(open(cache, encoding="utf-8").read())
        url = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
        txt = urllib.request.urlopen(url, timeout=15).read().decode()
        open(cache, "w", encoding="utf-8").write(txt)
        return build(txt)
    except Exception:
        try:
            return build(open(cache, encoding="utf-8").read())   # poslední cache
        except Exception:
            return None

def get_sat(catnr, now):
    """Vrátí (dráha=[(lat,lon)...], aktuální=(lat,lon)) pro družici, nebo None."""
    if not SHOW_SATELLITES:
        return None
    try:
        from sgp4.api import Satrec
    except Exception:
        return None
    tle = _sat_tle(catnr)
    if not tle:
        return None
    try:
        sat = Satrec.twoline2rv(tle[0], tle[1])
    except Exception:
        return None
    track = []
    steps = (SAT_TRACK_MIN_BEFORE + SAT_TRACK_MIN_AFTER) * 4     # ~15 s krok = hladká křivka
    for s in range(steps + 1):
        mm = -SAT_TRACK_MIN_BEFORE + s * 0.25
        p = _sat_latlon(sat, now + datetime.timedelta(minutes=mm))
        if p:
            track.append((p[0], p[1]))
    cur = _sat_latlon(sat, now)                                 # (lat, lon, výška km)
    return (track, cur) if track else None

def fetch_live_clouds():
    """Nepovinné: stáhne aktuální mapu mraků z CLOUDS_LIVE_URL do cache (s fallbackem).
    V URL lze použít {date} -> doplní se včerejší datum (YYYY-MM-DD).
    Příklad (NASA GIBS, hrubší mrak. pokrytí, bez klíče):
    https://wvs.earthdata.nasa.gov/api/v1/snapshot?REQUEST=GetSnapshot&LAYERS=MODIS_Terra_Cloud_Fraction_Day&CRS=EPSG:4326&BBOX=-90,-180,90,180&WIDTH=2048&HEIGHT=1024&FORMAT=image/jpeg&TIME={date}
    """
    if not CLOUDS_LIVE_URL:
        return None
    import urllib.request, time as _t
    url = CLOUDS_LIVE_URL.replace("{date}", (datetime.date.today() - datetime.timedelta(days=1)).isoformat())
    cache = _cache("clouds_live.jpg")
    try:
        fresh = os.path.exists(cache) and (_t.time() - os.path.getmtime(cache) < CLOUDS_LIVE_HOURS * 3600)
        if not fresh:
            req = urllib.request.Request(url, headers={"User-Agent": "daynight-wallpaper"})
            data = urllib.request.urlopen(req, timeout=20).read()
            open(cache, "wb").write(data)
        return "clouds_live.jpg"
    except Exception:
        return "clouds_live.jpg" if os.path.exists(cache) else None

# ============================================================
#  VYKRESLENÍ
# ============================================================
def build_wallpaper(when=None):
    sw, sh = screen_size()
    city = CITIES.get(CITY)
    center = CENTER_LON if CENTER_LON is not None else (city[0] if city else 0.0)
    city_lat = city[1] if (city and CENTER_LON is None) else None
    city_tz  = city[2] if (city and CENTER_LON is None and len(city) > 2) else None

    # cover = mapa pokryje celou plochu (větší rozměr, ořez); contain = celá mapa vejde dovnitř
    cover = (MAP_FILL == "cover")
    map_w = (max(sw, sh * 2) if cover else min(sw, sh * 2))
    map_w -= map_w % 2
    map_h = map_w // 2

    now = when or datetime.datetime.now(datetime.timezone.utc)
    decl, slon = subsolar(now)

    # render v supersamplované velikosti kvůli antialiasingu (s ochranou paměti na 4K)
    ss = max(1, SUPERSAMPLE)
    if map_w * ss > 5200:
        ss = 1
    rw, rh = map_w * ss, map_h * ss

    # ---- 1) základ Země: satelitní textura, nebo ploché barvy jako záloha ----
    base = load_texture(TEX_DAY, (rw, rh)) if USE_TEXTURE else None
    lights = None
    cloud = None
    if base is not None:
        textured = True
        ln = load_texture(TEX_NIGHT, (rw, rh))
        if ln is not None:
            lum = 0.299 * ln[..., 0] + 0.587 * ln[..., 1] + 0.114 * ln[..., 2]
            lights = np.clip((lum - 48.0) / (255.0 - 48.0), 0.0, 1.0)  # vytáhne jen jasná města
        if CLOUDS:
            cpath = fetch_live_clouds() or TEX_CLOUDS
            cl = load_texture(cpath, (rw, rh))
            if cl is None and cpath != TEX_CLOUDS:
                cl = load_texture(TEX_CLOUDS, (rw, rh))   # fallback na přibalenou texturu
            if cl is not None:
                clum = (0.299 * cl[..., 0] + 0.587 * cl[..., 1] + 0.114 * cl[..., 2]) / 255.0
                cloud = np.clip((clum - 0.06) / 0.94, 0.0, 1.0) * CLOUD_OPACITY
                if CLOUD_DRIFT:   # pomalé otáčení podle času
                    shift = int(round((CLOUD_DRIFT * now.timestamp() / 3600.0 / 360.0) * rw)) % rw
                    if shift:
                        cloud = np.roll(cloud, shift, axis=1)
                c3 = cloud[..., None]
                base = base * (1 - c3) + 245.0 * c3          # bílé osvětlené mraky
    else:
        textured = False
        flat = Image.new("RGB", (rw, rh), C_OCEAN)
        dr = ImageDraw.Draw(flat)
        for ring in load_land():
            pts = [((lng + 180) / 360 * rw, (90 - lat) / 180 * rh) for lng, lat in ring]
            dr.polygon(pts, fill=C_LAND)
        base = np.asarray(flat, dtype=np.float32)

    # ---- 2) výška Slunce nad obzorem pro každý pixel (střed 0°) ----
    latg = (90 - (np.arange(rh) + 0.5) / rh * 180.0)
    lngg = ((np.arange(rw) + 0.5) / rw * 360.0 - 180.0)
    LAT, LNG = np.meshgrid(np.radians(latg), np.radians(lngg), indexing="ij")
    Hang = LNG - math.radians(slon)
    sinElev = (np.sin(LAT) * math.sin(math.radians(decl)) +
               np.cos(LAT) * math.cos(math.radians(decl)) * np.cos(Hang))
    elev = np.degrees(np.arcsin(np.clip(sinElev, -1, 1)))

    # ---- 3) vrstvený soumrak: jas podle výšky Slunce (noc lze zesvětlit přes NIGHT_BRIGHTNESS) ----
    #   den ≥0:1.0 | civilní 0..−6:1.0→0.55 | nautický −6..−12:0.55→0.32
    #   astronomický −12..−18:0.32→NB | noc <−18:NB
    NB = NIGHT_BRIGHTNESS
    a_civ, a_nau = 0.55, 0.32
    civ = (elev < 0)   & (elev >= -6)
    nau = (elev < -6)  & (elev >= -12)
    ast = (elev < -12) & (elev >= -18)
    bright = np.full_like(elev, NB)
    bright[elev >= 0] = 1.0
    bright[civ] = 1.0   + (elev[civ] / 6.0)        * (1.0 - a_civ)
    bright[nau] = a_civ + ((elev[nau] + 6) / 6.0)  * (a_civ - a_nau)
    bright[ast] = a_nau + ((elev[ast] + 12) / 6.0) * (a_nau - NB)

    out = base * bright[..., None]
    darkfac = np.clip((-elev) / 12.0, 0.0, 1.0)    # 0 ve dne, 1 v noci (od −12°)

    # chladný nádech noční strany (jen u textury)
    if textured:
        out[..., 2] += darkfac * 12.0
        out[..., 0] -= darkfac * 3.0

    # teplá záře přesně na terminátoru
    glow = np.exp(-(elev / 2.2) ** 2)
    out[..., 0] += glow * 60.0
    out[..., 1] += glow * 38.0
    out[..., 2] += glow * 12.0

    # městská světla na temné straně (mraky je tlumí)
    if lights is not None:
        atten = (1.0 - 0.7 * cloud) if cloud is not None else 1.0
        ls = lights * darkfac * LIGHTS_GAIN * atten
        out[..., 0] += ls * 255.0
        out[..., 1] += ls * 214.0
        out[..., 2] += ls * 140.0

    img_full = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")

    # ---- 4) downscale (antialiasing) + odrolování na zvolený střed (bez švu) ----
    if ss != 1:
        img_full = img_full.resize((map_w, map_h), Image.LANCZOS)
    arr = np.asarray(img_full, dtype=np.uint8)
    roll_px = int(round(-(center / 360.0) * map_w))
    arr = np.roll(arr, roll_px, axis=1)

    # pixelová x/y souřadnice pro zeměpisnou délku/šířku (po vycentrování)
    def sx(lon_deg):
        rel = ((lon_deg - center + 180) % 360) - 180
        return map_w / 2 + rel / 360.0 * map_w
    def sy(lat_deg):
        return (90 - lat_deg) / 180.0 * map_h

    tz = load_timezones() if TIMEZONES else []
    real_tz = bool(tz)

    # jemné poledníky a rovnoběžky — míchané přímo do RGB (přežijí i ořez fullscreenu)
    if SHOW_GRID:
        f = arr.astype(np.float32)
        gcol = np.array(NASA_LBLUE, np.float32)
        ga = 0.15
        if not real_tz:                          # rovné poledníky jen jako záloha bez dat pásem
            mer_step = 15 if TIMEZONES else 30
            for L in range(-180, 180, mer_step):
                x = int(round(sx(L)))
                if 0 <= x < map_w:
                    f[:, x] = f[:, x] * (1 - ga) + gcol * ga
        for P in range(-60, 61, 30):             # rovnoběžky po 30°
            y = int(round(sy(P)))
            if 0 <= y < map_h:
                f[y, :] = f[y, :] * (1 - ga) + gcol * ga
        ye = int(round(sy(0)))                    # rovník o chlup výrazněji
        if 0 <= ye < map_h:
            f[ye, :] = f[ye, :] * (1 - 0.20) + gcol * 0.20
        arr = np.clip(f, 0, 255).astype(np.uint8)

    # středový poledník města — jemná měkká bílá linka (3 px)
    if SHOW_CITY_MARKER:
        f = arr.astype(np.float32)
        xp = int(round(sx(center)))
        gold = np.array([238, 243, 252], np.float32)   # bílá (NASA paleta)
        for dx, al in ((-1, 0.10), (0, 0.32), (1, 0.10)):
            xx = xp + dx
            if 0 <= xx < map_w:
                f[:, xx] = f[:, xx] * (1 - al) + gold * al
        arr = np.clip(f, 0, 255).astype(np.uint8)

    mapimg = Image.fromarray(arr, "RGB").convert("RGBA")

    # ---- polární záře (auroral oval) na noční straně ----
    if SHOW_AURORA:
        A = get_aurora()
        if A is not None:
            small = np.roll(A[::-1], -180, axis=1)            # nahoře +90°, lon −180..180
            au = np.asarray(Image.fromarray(np.clip(small, 0, 255).astype(np.uint8))
                            .resize((map_w, map_h), Image.BILINEAR), np.float32)
            ys = 90 - (np.arange(map_h) + 0.5) / map_h * 180
            xs = -180 + (np.arange(map_w) + 0.5) / map_w * 360
            latg = np.radians(ys)[:, None]; lng = np.radians(xs)[None, :]
            elev = np.degrees(np.arcsin(
                math.sin(math.radians(decl)) * np.sin(latg) +
                math.cos(math.radians(decl)) * np.cos(latg) * np.cos(lng - math.radians(slon))))
            darkness = np.clip((-elev) / 6.0, 0.0, 1.0)        # vidět jen po setmění
            a = np.clip((au / 100.0) ** 0.8 * AURORA_GAIN * darkness, 0.0, 1.0)
            ov = np.zeros((map_h, map_w, 4), np.float32)
            ov[..., 0] = AURORA_COLOR[0]; ov[..., 1] = AURORA_COLOR[1]; ov[..., 2] = AURORA_COLOR[2]
            ov[..., 3] = a * 230
            ov = np.roll(ov, roll_px, axis=1)
            ov_img = Image.fromarray(ov.astype(np.uint8), "RGBA").filter(
                ImageFilter.GaussianBlur(max(1, map_w // 500)))   # měkká záře
            mapimg = Image.alpha_composite(mapimg, ov_img)

    # zvýraznění časového pásma vystředěného města — podbarvení + jasný obrys
    if real_tz and HIGHLIGHT_CITY_ZONE and SHOW_CITY_MARKER:
        czone = offset_at(center, city_lat if city_lat is not None else 0.0, tz)
        if czone is not None:
            S = 2 if map_w <= 3000 else 1                 # supersampling kvůli hladkému obrysu
            fillov = Image.new("RGBA", (map_w * S, map_h * S), (0, 0, 0, 0))
            fd = ImageDraw.Draw(fillov)
            ocol = tuple(ZONE_EDGE) + (ZONE_EDGE_ALPHA,)   # obrys hranice pásma
            ow = max(S, int(map_w * S / 1100))
            for z, rings in tz:                       # výplň + obrys ve „středu 0°", pak se odroluje jako mapa
                if abs(z - czone) > 1e-6:
                    continue
                for ring in rings:
                    pts = [((p[0] + 180) / 360 * map_w * S, (90 - p[1]) / 180 * map_h * S) for p in ring]
                    fd.polygon(pts, fill=tuple(ZONE_FILL) + (ZONE_FILL_ALPHA,))   # podbarvení pásma
                    seg = pts[:1]                             # obrys jen mezi body bez přeskoku švu
                    for k in range(1, len(pts)):
                        if abs(pts[k][0] - pts[k - 1][0]) > map_w * S * 0.5:
                            if len(seg) > 1:
                                fd.line(seg, fill=ocol, width=ow, joint="curve")
                            seg = [pts[k]]
                        else:
                            seg.append(pts[k])
                    if len(seg) > 1:
                        fd.line(seg, fill=ocol, width=ow, joint="curve")
            if S != 1:
                fillov = fillov.resize((map_w, map_h), Image.LANCZOS)
            fillov = fillov.filter(ImageFilter.GaussianBlur(max(1.0, map_w / 1400.0)))  # měkké zjemnění hran
            fa = np.roll(np.asarray(fillov), roll_px, axis=1)
            mapimg = Image.alpha_composite(mapimg, Image.fromarray(fa, "RGBA"))

    # skutečné hranice časových pásem (zubaté, kopírují státy) – poloprůhledná vrstva
    if real_tz:
        ov = Image.new("RGBA", (map_w, map_h), (0, 0, 0, 0))
        ovd = ImageDraw.Draw(ov)
        bcol = NASA_LBLUE + (95,)
        for z, rings in tz:
            for ring in rings:
                pts = [(sx(p[0]), sy(p[1])) for p in ring]
                seg = [pts[0]]
                for k in range(1, len(pts)):
                    if abs(pts[k][0] - pts[k - 1][0]) > map_w * 0.5:   # přeskoč šev na okraji
                        if len(seg) > 1:
                            ovd.line(seg, fill=bcol, width=1)
                        seg = [pts[k]]
                    else:
                        seg.append(pts[k])
                if len(seg) > 1:
                    ovd.line(seg, fill=bcol, width=1)
        mapimg = Image.alpha_composite(mapimg, ov)

    md = ImageDraw.Draw(mapimg, "RGBA")

    # ---- dráhy Slunce a Měsíce (pozemní stopy subsolárního/sublunárního bodu) ----
    _paths = []
    if SHOW_SUN_PATH:
        sp = [subsolar(now + datetime.timedelta(minutes=10 * k))
              for k in range(-PATH_HOURS * 6, PATH_HOURS * 6 + 1)]
        _paths.append((sp, (255, 226, 150, 175), 1.8))            # Slunce – teplá
    if SHOW_MOON_PATH:
        # lunární den ≈ 24 h 50 min (Měsíc obíhá) → vzorkujeme přes celý lunární den, ať se dráha uzavře jako u Slunce
        half = 24.8412 * 60 / 2.0
        n = PATH_HOURS * 12
        mp = [_moon_subpoint(now + datetime.timedelta(minutes=-half + 2.0 * half * i / n))
              for i in range(n)]                                  # n bodů = uzavřená smyčka (bez duplicitního konce)
        # pootoč smyčku tak, aby zbytkový zlom padl na datovou hranici (kraj mapy) → v mapě není patrný
        rc = lambda lo: ((lo - center + 180) % 360) - 180
        for i in range(1, len(mp)):
            if abs(rc(mp[i][1]) - rc(mp[i - 1][1])) > 180:
                mp = mp[i:] + mp[:i]
                break
        _paths.append((mp, (180, 200, 240, 170), 1.8))           # Měsíc – chladná
    if _paths:
        S = 3 if map_w <= 2600 else 2
        pim = Image.new("RGBA", (map_w * S, map_h * S), (0, 0, 0, 0))
        pd = ImageDraw.Draw(pim)
        dash, gap = int(13 * S), int(9 * S)
        for pts_ll, col, wpx in _paths:
            pts = [(sx(lo), sy(la)) for (la, lo) in pts_ll]
            seg = pts[:1]
            for k in range(1, len(pts)):
                if abs(pts[k][0] - pts[k - 1][0]) > map_w * 0.5:
                    if len(seg) > 1:
                        _dashed_line(pd, [(px * S, py * S) for px, py in seg], col, max(2, int(wpx * S)), dash, gap)
                    seg = [pts[k]]
                else:
                    seg.append(pts[k])
            if len(seg) > 1:
                _dashed_line(pd, [(px * S, py * S) for px, py in seg], col, max(2, int(wpx * S)), dash, gap)
        mapimg = Image.alpha_composite(mapimg, pim.resize((map_w, map_h), Image.LANCZOS))
        md = ImageDraw.Draw(mapimg, "RGBA")

    # subsolární bod (Slunce v zenitu) — hladký zářící disk
    if SHOW_SUBSOLAR:
        x, y = sx(slon), sy(decl)
        sun, pad = _marker_sun(max(10, map_w // 175))
        mapimg.alpha_composite(sun, (int(x - pad), int(y - pad)))

    # Měsíc (sublunární bod) + fáze
    if SHOW_MOON:
        mlat, mlon = _moon_subpoint(now)
        frac, waxing = _moon_phase(now)
        # Měsíc stejně velký jako Slunce (jako na obloze ~0,5°): kotouč Slunce je 1.15×, Měsíce 1.0×
        moon, mpad = _marker_moon(round(max(10, map_w // 175) * 1.15), frac, waxing)
        mx, my = sx(mlon), sy(mlat)
        mapimg.alpha_composite(moon, (int(mx - mpad), int(my - mpad)))

    # střed = vystředěné město; majákový terčík v jeho skutečné poloze
    if SHOW_CITY_MARKER:
        cx = map_w / 2
        font = load_font(max(16, map_w // 90))
        label = CITY if CENTER_LON is None else ("%.2f°" % center)
        if city_lat is not None:
            x, y = sx(center), sy(city_lat)
            beacon, bpad = _marker_city(max(8, map_w // 200))
            mapimg.alpha_composite(beacon, (int(x - bpad), int(y - bpad)))
            lx = x + bpad + 3
            ny = y - font.size // 2 - 2
            _text(md, mapimg, (lx, ny), label, font, (255, 255, 255, 245))
            # posun od nultého (greenwichského) poledníku
            off = None
            if city_tz:
                try:
                    from zoneinfo import ZoneInfo
                    uo = now.astimezone(ZoneInfo(city_tz)).utcoffset()
                    off = uo.total_seconds() / 3600.0 if uo else None
                except Exception:
                    off = None
            if off is None:
                off = offset_at(center, city_lat, tz) if real_tz else round(center / 15.0)

            def _utc(o):
                if o is None:
                    return ""
                if abs(o) < 1e-6:
                    return "UTC+0"
                sg = "+" if o > 0 else "−"; a = abs(o); h = int(a); mn = int(round((a - h) * 60))
                return "UTC%s%d" % (sg, h) if mn == 0 else "UTC%s%d:%02d" % (sg, h, mn)

            ouf = _utc(off)
            if ouf:
                sfont = load_font(max(12, map_w // 135), mono=True)
                ty = ny + font.size + 1
                _text(md, mapimg, (lx, ty), ouf, sfont, (255, 255, 255, 240))
        else:
            md.text((cx + 8, 10), label, font=font, fill=(255, 255, 255, 230))

    # ---- popisky časových pásem nahoře (čísla pásem nebo hodiny) ----
    if TIMEZONES and (SHOW_TZ_CLOCK or SHOW_TZ_NUMBERS):
        y0c = max(0, (map_h - sh) // 2) if cover else 0   # ať jsou popisky i ve fullscreenu vidět
        ytop = y0c + 6
        utc = now.hour + now.minute / 60.0 + now.second / 3600.0
        tzfont = load_font(max(14, map_w // 115))

        def fmt_off(o):
            if o is None:
                return ""
            if abs(o) < 1e-6:
                return "0"
            sign = "+" if o > 0 else "−"
            a = abs(o); h = int(a); m = int(round((a - h) * 60))
            return "%s%d" % (sign, h) if m == 0 else "%s%d:%02d" % (sign, h, m)

        def label_for(off):
            if SHOW_TZ_CLOCK:          # hodiny mají přednost, pokud jsou zapnuté
                lh = (utc + off) % 24
                return "%02d:%02d" % (int(lh), int(round((lh % 1) * 60)) % 60)
            return fmt_off(off)        # jinak číslo pásma (UTC offset)

        def put(xc, s):
            if not s or not (14 < xc < map_w - 14):
                return
            w = md.textbbox((0, 0), s, font=tzfont)[2]
            x = xc - w / 2
            md.text((x + 1, ytop + 2), s, font=tzfont, fill=(0, 0, 0, 130))   # jemný stín
            md.text((x, ytop),         s, font=tzfont, fill=(236, 242, 250, 255))

        if real_tz:
            # navzorkuj offset napříč obrazem (na rovníku), seskup do pásem a popiš střed pásma
            cols = 120
            samp = [((i + 0.5) / cols * map_w,
                     offset_at(center + ((i + 0.5) / cols - 0.5) * 360.0, 0.0, tz)) for i in range(cols)]
            i = 0
            while i < cols:
                off = samp[i][1]; j = i
                while j + 1 < cols and samp[j + 1][1] == off:
                    j += 1
                if off is not None:
                    put((samp[i][0] + samp[j][0]) / 2.0, label_for(off))
                i = j + 1
        else:
            for L in range(-180, 181, 15):
                put(sx(L), label_for(round(L / 15.0)))

        # vystředěné místo: skutečný místní čas — jen v režimu hodin (žádný popisek UTC u čísel)
        if SHOW_TZ_CLOCK:
            ctxt = None
            if city_tz:
                try:
                    from zoneinfo import ZoneInfo
                    ctxt = now.astimezone(ZoneInfo(city_tz)).strftime("%H:%M")
                except Exception:
                    ctxt = None
            if ctxt is None:
                off = offset_at(center, city_lat if city_lat is not None else 0.0, tz) if real_tz else None
                lh = (utc + (off if off is not None else center / 15.0)) % 24
                ctxt = "%02d:%02d" % (int(lh), int(round((lh % 1) * 60)) % 60)
            cf = load_font(max(14, map_w // 100))
            w = md.textbbox((0, 0), ctxt, font=cf)[2]
            gx = map_w / 2 - w / 2; gy = ytop + 22
            md.text((gx + 1, gy + 2), ctxt, font=cf, fill=(0, 0, 0, 130))
            md.text((gx, gy),         ctxt, font=cf, fill=(255, 215, 140, 255))

    # ---- družice: dráhy (pozemní stopy) + aktuální polohy ----
    if SHOW_SATELLITES:
        sats = []
        for label, catnr, color in SATELLITES:
            d = get_sat(catnr, now)
            if d:
                sats.append((label, tuple(color), d[0], d[1]))
        if sats:
            # ---- footprint ISS (oblast, odkud je nad obzorem) ----
            if SHOW_ISS_FOOTPRINT:
                for label, color, track, cur in sats:
                    if not cur or label != "ISS":
                        continue
                    Re, h = 6371.0, max(1.0, cur[2])
                    theta = math.acos(Re / (Re + h))                  # úhlový poloměr dosahu
                    lat0, lon0 = math.radians(cur[0]), math.radians(cur[1])
                    ys = 90 - (np.arange(map_h) + 0.5) / map_h * 180
                    xs = -180 + (np.arange(map_w) + 0.5) / map_w * 360
                    latg, lng = np.radians(ys)[:, None], np.radians(xs)[None, :]
                    ang = np.arccos(np.clip(math.sin(lat0) * np.sin(latg)
                                            + math.cos(lat0) * np.cos(latg) * np.cos(lng - lon0), -1, 1))
                    ov = np.zeros((map_h, map_w, 4), np.uint8)
                    ov[ang <= theta] = (color[0], color[1], color[2], 30)              # průsvitná výplň
                    ov[np.abs(ang - theta) < math.radians(0.45)] = (color[0], color[1], color[2], 205)  # obrys
                    ov = np.roll(ov, roll_px, axis=1)
                    fp = Image.fromarray(ov, "RGBA").filter(ImageFilter.GaussianBlur(1.2))
                    mapimg = Image.alpha_composite(mapimg, fp)
            S = 3 if map_w <= 2600 else 2
            big = Image.new("RGBA", (map_w * S, map_h * S), (0, 0, 0, 0))
            bd = ImageDraw.Draw(big)
            w = max(2, round(2.4 * S))

            def _flush(seg, col):
                if len(seg) > 1:
                    bd.line([(px * S, py * S) for px, py in seg], fill=col, width=w, joint="curve")

            for label, color, track, cur in sats:                 # každá dráha svou barvou
                col = color + (235,)
                pts = [(sx(lo), sy(la)) for (la, lo) in track]
                segs = []                                         # rozděl dráhu na úseky podle švu (datová hranice)
                seg = pts[:1]
                for k in range(1, len(pts)):
                    if abs(pts[k][0] - pts[k - 1][0]) > map_w * 0.5:
                        segs.append(seg); seg = [pts[k]]
                    else:
                        seg.append(pts[k])
                segs.append(seg)
                if cur:                                           # jen úsek u družice — ať se dráha neukáže na druhé straně
                    cxp, cyp = sx(cur[1]), sy(cur[0])
                    best = min(segs, key=lambda s: min((px - cxp) ** 2 + (py - cyp) ** 2 for px, py in s))
                    _flush(best, col)
                else:
                    for s in segs:
                        _flush(s, col)

            tracks_img = big.resize((map_w, map_h), Image.LANCZOS)
            tsh = Image.new("RGBA", tracks_img.size, (0, 0, 0, 0))    # měkký stín pod dráhy
            tsh.putalpha(tracks_img.split()[3].point(lambda v: int(v * 0.55)))
            tsh = tsh.filter(ImageFilter.GaussianBlur(2))
            mapimg.paste(tsh, _SHADOW, tsh)                          # jednotný vržený stín dolů
            mapimg = Image.alpha_composite(mapimg, tracks_img)
            md = ImageDraw.Draw(mapimg, "RGBA")
            isf = load_font(max(12, map_w // 125))
            aff = load_font(max(10, map_w // 155), mono=True)
            mr = max(9, map_w // 175)
            mb = int(mr * 2.0)                                   # ochranná zóna kolem terčíku družice
            # terčíky všech družic jsou pro popisky překážky (text nesmí zasahovat do cizí značky)
            placed = [[sx(c[1]) - mb, sy(c[0]) - mb, sx(c[1]) + mb, sy(c[0]) + mb]
                      for _, _, _, c in sats if c]
            vtop = ((map_h - sh) // 2) if cover else 0            # svislé meze viditelné oblasti
            vbot = vtop + (sh if cover else map_h)
            def _overlap(a, b):
                return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
            for label, color, track, cur in sats:                 # terčíky + popisky (název / výška / rychlost)
                if not cur:
                    continue
                ix, iy = sx(cur[1]), sy(cur[0])
                ret, pad = _marker_reticle(color, mr)
                rsh = Image.new("RGBA", ret.size, (0, 0, 0, 0))      # měkký stín pod terčík
                rsh.putalpha(ret.split()[3].point(lambda v: int(v * 0.5)))
                rsh = rsh.filter(ImageFilter.GaussianBlur(2))
                mapimg.paste(rsh, (int(ix - pad + _SHADOW[0]), int(iy - pad + _SHADOW[1])), rsh)   # jednotný stín
                mapimg.alpha_composite(ret, (int(ix - pad), int(iy - pad)))
                lines = [(label, isf, color + (255,))]            # název
                if len(cur) > 3:
                    lines.append(("%.1f km/s" % cur[3], aff, (225, 230, 240, 240)))    # rychlost
                if len(cur) > 2:
                    lines.append(("%.0f km" % cur[2], aff, (225, 230, 240, 240)))      # výška
                wlab = max(md.textbbox((0, 0), t, font=f)[2] for t, f, _ in lines)
                rlim = ((map_w + sw) // 2) if cover else map_w    # viditelný pravý/levý okraj
                llim = ((map_w - sw) // 2) if cover else 0
                if ix + pad + 4 + wlab <= rlim - 4:
                    tx = ix + pad + 4                             # popisek vpravo
                else:
                    tx = ix - pad - 4 - wlab                      # nevejde se → vlevo od značky
                tx = min(max(tx, llim + 4), rlim - 4 - wlab)
                bh = sum(f.size for _, f, _ in lines)             # výška bloku popisku
                y0 = iy - bh // 2                                 # výchozí poloha: vystředěná na značku
                step = max(2, isf.size // 4)
                def _box(yy):
                    return [tx - 2, yy - 2, tx + wlab + 2, yy + bh + 2]
                y = y0
                for _ in range(400):                             # posuň dolů, dokud se nepřekrývá
                    if not any(_overlap(_box(y), pb) for pb in placed):
                        break
                    y += step
                if _box(y)[3] > vbot or any(_overlap(_box(y), pb) for pb in placed):
                    y = y0                                        # dolů to nešlo → zkus nahoru od původní
                    for _ in range(400):
                        if not any(_overlap(_box(y), pb) for pb in placed):
                            break
                        y -= step
                y = min(max(y, vtop + 2), vbot - bh - 2)          # udrž blok ve viditelné oblasti
                placed.append(_box(y))
                for t, f, fill in lines:
                    _text(md, mapimg, (tx, y), t, f, fill)
                    y += f.size

    # rámeček (jen v režimu contain — ve fullscreenu žádné okraje)
    if not cover:
        md.rectangle([0, 0, map_w - 1, map_h - 1], outline=(150, 175, 210, 60), width=1)

    # ---- 4) složení na plochu ----
    if cover:
        # mapa pokryje celou plochu; přebytek se symetricky ořízne od středu
        x0 = (map_w - sw) // 2
        y0 = (map_h - sh) // 2
        canvas = mapimg.crop((x0, y0, x0 + sw, y0 + sh)).convert("RGB")
    else:
        canvas = Image.new("RGB", (sw, sh), C_SPACE)
        if SHOW_STARS and (sw > map_w or sh > map_h):
            sd = ImageDraw.Draw(canvas, "RGBA")
            rng = np.random.default_rng(7)
            nstar = (sw * sh) // 2600                     # hustší hvězdné pole
            xs = rng.integers(0, sw, nstar); ys = rng.integers(0, sh, nstar)
            mags = rng.random(nstar) ** 3                 # většina slabých, pár jasných
            tints = rng.random(nstar)
            for i in range(nstar):
                b = int(70 + 185 * mags[i])
                t = tints[i]
                if t < 0.20:   col = (b, int(b * 0.92), int(b * 0.78))   # teplá
                elif t > 0.80: col = (int(b * 0.80), int(b * 0.90), b)   # chladná
                else:          col = (b, b, b)
                x, y = int(xs[i]), int(ys[i])
                sd.point((x, y), fill=col + (255,))
                if mags[i] > 0.85:                        # jasnější hvězdy: jemný křížek/záře
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        sd.point((x + dx, y + dy), fill=col + (110,))
        # planeta se u horního a dolního okraje plynule rozplyne do vesmíru (krátký pruh jako vinětace)
        band = int(VIGNETTE_SIZE * map_h)
        if band > 0 and sh > map_h:
            am = np.array(mapimg)
            ramp = np.linspace(0.0, 1.0, band).astype(np.float32)
            a = am[..., 3].astype(np.float32)
            a[:band] *= ramp[:, None]
            a[map_h - band:] *= ramp[::-1][:, None]
            am[..., 3] = a.astype(np.uint8)
            mapimg = Image.fromarray(am, "RGBA")
        canvas.paste(mapimg, ((sw - map_w) // 2, (sh - map_h) // 2), mapimg)

    # ---- lineární vinětace nahoře a dole ----
    if VIGNETTE and VIGNETTE_STRENGTH > 0:
        ca = np.asarray(canvas).astype(np.float32)
        band = int(VIGNETTE_SIZE * sh)
        fac = np.ones(sh, dtype=np.float32)
        if band > 0:
            ramp = np.linspace(1.0 - VIGNETTE_STRENGTH, 1.0, band)  # tmavý okraj → 1 ve středu (lineárně)
            fac[:band] = ramp
            fac[sh - band:] = ramp[::-1]
        ca *= fac[:, None, None]
        canvas = Image.fromarray(np.clip(ca, 0, 255).astype(np.uint8), "RGB")

    canvas.save(OUTPUT, "PNG")
    return OUTPUT, center, (decl, slon)

# ============================================================
#  NASTAVENÍ TAPETY (Windows)
# ============================================================
def set_wallpaper(path):
    path = os.path.abspath(path)
    if sys.platform.startswith("win"):
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, "10")  # 10 = Vyplnit
            winreg.SetValueEx(k, "TileWallpaper",  0, winreg.REG_SZ, "0")
            winreg.CloseKey(k)
        except Exception:
            pass
        return bool(ctypes.windll.user32.SystemParametersInfoW(20, 0, path, 3))
    if sys.platform == "darwin":
        # nastaví tapetu na všech plochách/monitorech
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to tell every desktop to set picture to "%s"' % path],
                check=True, timeout=10)
            return True
        except Exception:
            return False
    return False

# ============================================================
#  ZAMYKACÍ / PŘIHLAŠOVACÍ OBRAZOVKA (Windows, vyžaduje admin)
# ============================================================
def set_lockscreen(path):
    """Nastaví obrázek zamykací (a tím i přihlašovací) obrazovky přes PersonalizationCSP.
    Zapisuje do HKLM → vyžaduje administrátorská práva. Windows obrázek kešují, proto
    střídáme dva soubory a měníme cestu — to vynutí znovunačtení při každém renderu."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg, shutil
        keypath = r"SOFTWARE\Microsoft\Windows\CurrentVersion\PersonalizationCSP"
        cur = ""                                              # aktuálně nastavená cesta (ať zapíšeme do druhého souboru)
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, keypath) as k:
                cur, _ = winreg.QueryValueEx(k, "LockScreenImagePath")
        except Exception:
            pass
        a = os.path.join(BASE, "penumbra_lock_a.png")
        b = os.path.join(BASE, "penumbra_lock_b.png")
        target = b if os.path.abspath(cur) == os.path.abspath(a) else a   # přepni na ten druhý
        other  = a if target == b else b
        shutil.copyfile(path, target)
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, keypath) as k:
            winreg.SetValueEx(k, "LockScreenImageStatus", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "LockScreenImagePath", 0, winreg.REG_SZ, target)
            winreg.SetValueEx(k, "LockScreenImageUrl",  0, winreg.REG_SZ, target)
        try:
            if os.path.exists(other):
                os.remove(other)                              # uklid starý soubor
        except Exception:
            pass
        return True
    except PermissionError:
        return False
    except Exception:
        return False

# ============================================================
if __name__ == "__main__":
    path, center, (decl, slon) = build_wallpaper()
    print("Mapa vykreslena: %s" % path)
    print("Střed: %s (%.2f°)   Slunce v zenitu: %.1f°, %.1f°" % (CITY, center, decl, slon))
    if sys.platform.startswith("win") or sys.platform == "darwin":
        print("Tapeta nastavena." if set_wallpaper(path) else "Tapetu se nepodařilo nastavit.")
        if SET_LOCKSCREEN and sys.platform.startswith("win"):
            print("Zamykací obrazovka nastavena." if set_lockscreen(path)
                  else "Zamykací obrazovku se nepodařilo nastavit (chybí admin práva?).")
    else:
        print("(Tapetu umím nastavit jen na Windows/macOS — PNG je každopádně hotové.)")

# ------------------------------------------------------------
# AUTOMATICKÉ OBNOVOVÁNÍ
#
# WINDOWS (Plánovač úloh):
#   Spustit program: pythonw.exe   Argument: "C:\cesta\penumbra.py"
#   Spustit v: "C:\cesta"          Spouštěč: opakovat každých 10 minut
#
# macOS (cron):  crontab -e  a přidej řádek:
#   */10 * * * * /usr/bin/python3 /Users/ty/cesta/penumbra.py
#   (na Macu doporučuju nastavit SCREEN ručně na rozlišení displeje)
# ------------------------------------------------------------
