"""
LÜMA — Tournée ORBITE 2026-27  ·  simulated ticketing dataset
Every figure in the case study is produced by this file. Seed fixed → reruns are identical.

Simulation choices are deliberate, not decorative:
  · sales follow the real shape of ticketing demand (on-sale burst → long flat middle
    → late spike that has NOT happened yet, because we sit mid-campaign)
  · channel mix varies by market (app-native in Paris, retail in the regions)
  · resellers do not hand back the buyer's email — this is what creates the
    owned-audience problem the case study is actually about
  · a 2024 tour exists, so Frequency and Monetary are real rather than decorative
"""
import numpy as np, pandas as pd, datetime as dt
rng = np.random.default_rng(20260804)
REF = dt.date(2026, 8, 4)                      # analysis date; tour is mid-campaign
QTY_P, QTY_V = [0.24,0.36,0.15,0.15,0.07,0.03], [1,2,2,2,3,4]
MEAN_QTY = float(np.dot(QTY_P, QTY_V))

# ----------------------------------------------------------- 1. PRIOR TOUR 2024
S24 = [("Paris","La Maroquinerie",500,"2024-10-11",24),("Lyon","Le Sonic",300,"2024-10-18",22),
       ("Bordeaux","I.Boat",350,"2024-10-25",22),("Nantes","Le Ferrailleur",300,"2024-11-08",22),
       ("Lille","La Bulle Café",250,"2024-11-15",21),("Toulouse","Le Rex",400,"2024-11-22",22)]
s24 = pd.DataFrame(S24, columns=["city","venue","capacity","show_date","base_price"])
s24["show_id"] = ["P%02d"%(i+1) for i in range(len(s24))]
s24["show_date"] = pd.to_datetime(s24.show_date).dt.date

DEPT = {"Paris":"75","Lyon":"69","Bordeaux":"33","Toulouse":"31","Nantes":"44","Rennes":"35",
        "Lille":"59","Strasbourg":"67","Marseille":"13","Montpellier":"34","Bruxelles":"BE"}
orders, buyers, oid, nid = [], {}, 0, 0

def new_buyer(date, source, city):
    global nid; nid += 1; bid = "B%05d"%nid
    buyers[bid] = dict(buyer_id=bid, first_seen=date, source=source,
                       dept=DEPT[city] if rng.random()<0.78 else rng.choice(list(DEPT.values())),
                       opt_in_email=bool(rng.random()<0.66), opt_in_push=bool(rng.random()<0.21))
    return bid

pool24 = []
for _, s in s24.iterrows():
    sold, n = int(s.capacity*rng.uniform(.74,.93)), 0
    while n < sold:
        # 22% of a date's audience already came to an earlier 2024 date
        if pool24 and rng.random() < 0.22: b = str(rng.choice(pool24))
        else:
            b = new_buyer(s.show_date - dt.timedelta(days=int(rng.integers(20,90))),
                          "Tournée 2024", s.city); pool24.append(b)
        qty = int(rng.choice(QTY_V, p=QTY_P)); n += qty; oid += 1
        orders.append(dict(order_id="O%06d"%oid, buyer_id=b, show_id=s.show_id,
                           order_date=s.show_date-dt.timedelta(days=int(rng.integers(14,95))),
                           channel="Site officiel", tier="Normal", qty=qty,
                           unit_price=float(s.base_price), fee_per_ticket=0.0,
                           gross=round(float(s.base_price)*qty,2)))
pool24 = sorted(set(pool24))

# --------------------------------------------------------- 2. ORBITE 2026-27
SHOWS = [("Paris","Le Trianon",1100,"2026-11-14","2026-06-02",32,1.00),
         ("Paris","La Cigale",1389,"2027-02-06","2026-06-02",34,0.96),
         ("Lyon","Le Transbordeur",1800,"2026-11-21","2026-06-09",30,0.83),
         ("Bordeaux","Rock School Barbey",600,"2026-11-27","2026-06-09",27,0.79),
         ("Toulouse","Le Bikini",1500,"2026-11-28","2026-06-09",28,0.62),
         ("Nantes","Stereolux",800,"2026-12-04","2026-06-16",27,0.74),
         ("Rennes","L'Antipode",500,"2026-12-05","2026-06-16",25,0.71),
         ("Lille","L'Aéronef",1200,"2026-12-11","2026-06-16",28,0.58),
         ("Strasbourg","La Laiterie",950,"2027-01-16","2026-06-23",27,0.55),
         ("Marseille","Le Molotov",450,"2027-01-22","2026-06-23",26,0.88),
         ("Montpellier","Le Rockstore",700,"2027-01-23","2026-06-23",26,0.64),
         ("Bruxelles","Botanique",650,"2027-01-30","2026-06-30",29,0.81)]
sh = pd.DataFrame(SHOWS, columns=["city","venue","capacity","show_date","onsale_date","base_price","strength"])
sh["show_id"] = ["S%02d"%(i+1) for i in range(len(sh))]
sh["show_date"]   = pd.to_datetime(sh.show_date).dt.date
sh["onsale_date"] = pd.to_datetime(sh.onsale_date).dt.date
sh["days_on_sale"] = (pd.Timestamp(REF)-pd.to_datetime(sh.onsale_date)).dt.days
sh["days_to_show"] = (pd.to_datetime(sh.show_date)-pd.Timestamp(REF)).dt.days

orbite_pool = []
CH = ["Site officiel","Fnac Spectacles","Ticketmaster","Dice","Shotgun"]
def ch_probs(c):
    if c in ("Paris","Bruxelles"):                        return [.29,.16,.14,.24,.17]
    if c in ("Lyon","Marseille","Bordeaux","Nantes"):      return [.24,.28,.20,.16,.12]
    return [.19,.36,.24,.13,.08]

for _, s in sh.iterrows():
    win = int(s.days_on_sale)
    w = np.array([3.2*np.exp(-d/4.0)+0.28 for d in range(win+1)])
    target_orders = (s.capacity*s.strength*0.95)/MEAN_QTY     # tickets → orders
    w = w/w.sum()*target_orders
    remaining = s.capacity
    for d in range(win+1):
        for _ in range(rng.poisson(max(w[d],0.01))):
            if remaining <= 0: break
            # who is buying: a 2024 fan, someone who already bought another ORBITE
            # date, or a brand-new name
            p_ret = 0.07 if d <= 6 else 0.015                 # pre-sale mail favours returners
            u = rng.random()
            if u < p_ret and pool24:
                b = str(rng.choice(pool24))
            elif u < p_ret + 0.11 and orbite_pool:            # second date, or a re-buy
                b = str(rng.choice(orbite_pool))
            else:
                b = new_buyer(s.onsale_date+dt.timedelta(days=d), "Tournée ORBITE", s.city)
                orbite_pool.append(b)
            qty = min(int(rng.choice(QTY_V, p=QTY_P)), remaining); remaining -= qty
            ch  = str(rng.choice(CH, p=ch_probs(s.city)))
            tier = str(rng.choice(["Prévente","Normal","Carré or"],
                       p=[.18,.76,.06] if d<=6 else [.02,.90,.08]))
            unit = round(s.base_price*{"Prévente":.88,"Normal":1.,"Carré or":1.45}[tier], 2)
            oid += 1
            orders.append(dict(order_id="O%06d"%oid, buyer_id=b, show_id=s.show_id,
                order_date=s.onsale_date+dt.timedelta(days=d), channel=ch, tier=tier, qty=qty,
                unit_price=unit, fee_per_ticket=0.0 if ch=="Site officiel" else round(float(rng.uniform(1.9,3.4)),2),
                gross=round(unit*qty,2)))

od = pd.DataFrame(orders); bu = pd.DataFrame(buyers.values())
od["tour"] = np.where(od.show_id.str.startswith("P"), "PREMIER CERCLE 2024", "ORBITE 2026-27")

# Reseller channels return money, not identity. This flag is the whole case study.
owned = set(od[od.channel=="Site officiel"].buyer_id)
bu["contactable"] = bu.buyer_id.isin(owned) & bu.opt_in_email

od.to_csv("/tmp/pf/data/orders.csv", index=False)
bu.to_csv("/tmp/pf/data/buyers.csv", index=False)
sh.drop(columns=["strength"]).to_csv("/tmp/pf/data/shows.csv", index=False)
s24.to_csv("/tmp/pf/data/shows_2024.csv", index=False)

orb = od[od.tour=="ORBITE 2026-27"]
print("2024 buyers      :", len(pool24))
print("ORBITE orders    :", len(orb), "| tickets:", int(orb.qty.sum()),
      "| buyers:", orb.buyer_id.nunique())
print("reactivated 2024 :", len(set(orb.buyer_id) & set(pool24)),
      "(%.0f%%)" % (100*len(set(orb.buyer_id)&set(pool24))/len(pool24)))
print("GMV ORBITE       : %.0f EUR" % orb.gross.sum())
print("max fill         : %.3f" % (orb.groupby("show_id").qty.sum()/sh.set_index("show_id").capacity).max())
