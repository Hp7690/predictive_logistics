"""India pilot geography: Northern sector (Chandigarh / Jammu / Srinagar -> Ladakh, Zanskar, Lahaul-Spiti).
Towns, passes and highway corridors are real public geography. Waypoints are approximate (illustrative, not survey grade).
Stock, troop numbers and consumption are synthetic."""

CH = (30.7333, 76.7794); MANDI = (31.7087, 76.9320); MANALI = (32.2432, 77.1892); KEYLONG = (32.5700, 77.0300)
JISPA = (32.6330, 77.1860); BARALACHA = (32.7468, 77.4181); SARCHU = (32.9060, 77.5730); PANG = (33.1560, 77.7040)
TANGLANG = (33.5110, 77.7480); UPSHI = (33.8350, 77.8040); KARU = (33.9710, 77.7090); LEH = (34.1526, 77.5771)
JM = (32.7266, 74.8570); UDHAMPUR = (32.9160, 75.1410); RAMBAN = (33.2400, 75.2400); BANIHAL = (33.4440, 75.1930)
QAZIGUND = (33.6000, 75.1700); ANANTNAG = (33.7300, 75.1500); SR = (34.0837, 74.7973); SONAMARG = (34.3000, 75.2900)
ZOJI = (34.2842, 75.4724); DRASS = (34.4283, 75.7586); KARGIL = (34.5539, 76.1349); MULBEKH = (34.3950, 76.3600)
LAMAYURU = (34.2897, 76.7840); KHALSI = (34.3167, 76.8833); NIMMU = (34.1830, 77.3470)
SANKOO = (34.3200, 76.0900); PANIKHAR = (34.1700, 76.0700); PENSI = (33.9700, 76.3000); PADUM = (33.4667, 76.8833)
KHARDUNG = (34.2780, 77.6040); DISKIT = (34.5400, 77.5600)
SHIMLA = (31.1048, 77.1734); NARKANDA = (31.2660, 77.4560); RAMPUR = (31.4500, 77.6370); PEO = (31.5330, 78.2700)
NAKO = (31.8750, 78.6000); KAZA = (32.2276, 78.0716); KUNZUM = (32.3944, 77.6300)

ML = [CH, MANDI, MANALI, KEYLONG, JISPA, BARALACHA, SARCHU, PANG, TANGLANG, UPSHI, KARU, LEH]   # Manali-Leh highway
SL = [SR, SONAMARG, ZOJI, DRASS, KARGIL, MULBEKH, LAMAYURU, KHALSI, NIMMU, LEH]                  # Srinagar-Leh NH-1
JS = [JM, UDHAMPUR, RAMBAN, BANIHAL, QAZIGUND, ANANTNAG, SR]                                       # Jammu-Srinagar NH-44
KP = [KARGIL, SANKOO, PANIKHAR, PENSI, PADUM]                                                      # Kargil-Zanskar
LD = [LEH, KHARDUNG, DISKIT]                                                                       # Leh-Nubra
KK = [CH, SHIMLA, NARKANDA, RAMPUR, PEO, NAKO, KAZA]                                               # Kinnaur-Spiti

def seg(path, a, b):
    i, j = path.index(a), path.index(b)
    return path[i:j + 1] if i <= j else path[j:i + 1][::-1]

def _r(d, p, via, km, slope, vf, pass_name, wp):
    return dict(depot=d, post=p, via=via, km=km, slope=slope, vf=vf, pass_name=pass_name, wp=[list(x) for x in wp])

# code, name, lat, lon, altitude_m
DEPOTS = [("D1", "Chandigarh Base Depot", *CH, 350), ("D2", "Jammu Depot", *JM, 330), ("D3", "Srinagar Depot", *SR, 1585)]
# code, name, lat, lon, altitude_m, troop_strength, mule_track
POSTS = [("P1", "Post A (Kargil)", *KARGIL, 2676, 90, False), ("P2", "Post B (Drass)", *DRASS, 3230, 70, False),
         ("P3", "Post C (Leh)", *LEH, 3500, 130, False), ("P4", "Post D (Padum)", *PADUM, 3657, 55, True),
         ("P5", "Post E (Keylong)", *KEYLONG, 3080, 60, False), ("P6", "Post F (Diskit, Nubra)", *DISKIT, 3144, 75, True),
         ("P7", "Post G (Kaza, Spiti)", *KAZA, 3800, 50, True), ("P8", "Post H (Khalsi)", *KHALSI, 2990, 80, False)]
PASSES = {"Zoji La": ZOJI, "Baralacha La": BARALACHA, "Kunzum La": KUNZUM}

_ML_KG = seg(ML, CH, LEH)
ROUTES = [
    _r("D3", "P1", "Srinagar-Leh NH-1 (Zoji La)", 205, .8, .6, "Zoji La", seg(SL, SR, KARGIL)),
    _r("D2", "P1", "Jammu-Srinagar-Zoji La", 475, .8, .6, "Zoji La", JS + seg(SL, SR, KARGIL)[1:]),
    _r("D1", "P1", "Manali-Leh Hwy + Leh-Kargil", 990, .75, .65, "Baralacha La", _ML_KG + seg(SL, LEH, KARGIL)[1:]),
    _r("D3", "P2", "Srinagar-Leh NH-1 (Zoji La)", 140, .8, .6, "Zoji La", seg(SL, SR, DRASS)),
    _r("D2", "P2", "Jammu-Srinagar-Zoji La", 410, .8, .6, "Zoji La", JS + seg(SL, SR, DRASS)[1:]),
    _r("D1", "P2", "Manali-Leh Hwy + Leh-Drass", 1050, .75, .65, "Baralacha La", _ML_KG + seg(SL, LEH, DRASS)[1:]),
    _r("D3", "P3", "Srinagar-Leh NH-1 (Zoji La)", 420, .8, .6, "Zoji La", SL),
    _r("D2", "P3", "Jammu-Srinagar-Zoji La", 690, .8, .6, "Zoji La", JS + SL[1:]),
    _r("D1", "P3", "Manali-Leh Highway (Baralacha La)", 770, .75, .65, "Baralacha La", ML),
    _r("D3", "P4", "Srinagar-Kargil-Zanskar road", 445, .85, .7, "Zoji La", seg(SL, SR, KARGIL) + KP[1:]),
    _r("D2", "P4", "Jammu-Srinagar-Kargil-Zanskar", 715, .85, .7, "Zoji La", JS + seg(SL, SR, KARGIL)[1:] + KP[1:]),
    _r("D1", "P4", "Manali-Leh Hwy + Kargil-Zanskar", 1210, .8, .7, "Baralacha La", _ML_KG + seg(SL, LEH, KARGIL)[1:] + KP[1:]),
    _r("D1", "P5", "Manali-Keylong (Atal Tunnel)", 425, .45, .4, None, seg(ML, CH, KEYLONG)),
    _r("D3", "P6", "Srinagar-Leh-Khardung La", 540, .85, .65, "Zoji La", SL + LD[1:]),
    _r("D2", "P6", "Jammu-Srinagar-Leh-Khardung La", 810, .85, .65, "Zoji La", JS + SL[1:] + LD[1:]),
    _r("D1", "P6", "Manali-Leh Hwy + Khardung La", 890, .8, .65, "Baralacha La", ML + LD[1:]),
    _r("D1", "P7", "NH-5 Shimla-Kinnaur-Spiti", 450, .5, .5, None, KK),
    _r("D1", "P7", "Manali-Kunzum La-Kaza", 510, .7, .6, "Kunzum La", seg(ML, CH, MANALI) + [KUNZUM, KAZA]),
    _r("D3", "P8", "Srinagar-Leh NH-1 (Zoji La)", 300, .8, .6, "Zoji La", seg(SL, SR, KHALSI)),
    _r("D2", "P8", "Jammu-Srinagar-Zoji La", 570, .8, .6, "Zoji La", JS + seg(SL, SR, KHALSI)[1:]),
    _r("D1", "P8", "Manali-Leh Hwy + Leh-Khalsi", 860, .75, .65, "Baralacha La", _ML_KG + seg(SL, LEH, KHALSI)[1:]),
]
