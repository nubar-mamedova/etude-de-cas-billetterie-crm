import pandas as pd, numpy as np, datetime as dt, json
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

REF = dt.date(2026,8,4)
INK, MUT, ALERT, OK, GREY = "#141414","#8A8A8A","#C4452B","#2E6E5B","#D2D2D2"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.edgecolor":"#DDD",
    "axes.linewidth":.8,"figure.dpi":190,"savefig.dpi":190,"text.color":INK,
    "axes.labelcolor":INK,"xtick.color":MUT,"ytick.color":MUT})

o = pd.read_csv("/tmp/pf/data/orders.csv", parse_dates=["order_date"])
b = pd.read_csv("/tmp/pf/data/buyers.csv", parse_dates=["first_seen"])
s = pd.read_csv("/tmp/pf/data/shows.csv",  parse_dates=["show_date","onsale_date"])
orb = o[o.tour=="ORBITE 2026-27"].copy(); old = o[o.tour=="PREMIER CERCLE 2024"]
R = {}

# ---------------------------------------------------------------- 1. PACE
s = s.merge(orb.groupby("show_id").qty.sum().rename("sold"), on="show_id")
s["fill"] = s.sold/s.capacity
s["day"]  = (pd.Timestamp(REF)-s.onsale_date).dt.days
d = orb.merge(s[["show_id","onsale_date","capacity"]], on="show_id")
d["dd"] = (d.order_date-d.onsale_date).dt.days
cur = (d.groupby(["show_id","dd"]).qty.sum().groupby(level=0).cumsum().reset_index()
        .merge(s[["show_id","capacity"]], on="show_id"))
cur["f"] = cur.qty/cur.capacity
ref = cur.groupby("dd").f.median()
s["expected"] = s.day.map(lambda x: ref.reindex(range(0,int(x)+1)).ffill().iloc[-1])
s["pace"] = s.fill/s.expected
s = s.sort_values("pace")
lag = s[s.pace < 0.85]
R.update(pace=s[["show_id","city","venue","capacity","sold","fill","pace","days_to_show"]].round(3).to_dict("records"),
         lagging=lag.city.tolist(),
         gap=int(round(((lag.expected*lag.capacity)-lag.sold).sum())),
         total_tickets=int(orb.qty.sum()), total_capacity=int(s.capacity.sum()),
         gmv=float(orb.gross.sum()), avg_fill=float(s.sold.sum()/s.capacity.sum()))

fig, ax = plt.subplots(figsize=(7.6,3.6))
c = [ALERT if p<.85 else (OK if p>1.10 else "#BFBFBF") for p in s.pace]
ax.barh(s.city+"  ·  "+s.venue, s.fill*100, color=c, height=.62)
for i,(f,p) in enumerate(zip(s.fill,s.pace)):
    ax.text(f*100+1.4,i,f"{f*100:.0f} %    pace {p:.2f}",va="center",fontsize=8,
            color=ALERT if p<.85 else MUT)
ax.set_xlim(0,118); ax.set_xticks([0,25,50,75,100]); ax.xaxis.set_major_formatter(PercentFormatter())
ax.set_xlabel("Remplissage au 4 août 2026")
[ax.spines[x].set_visible(False) for x in ("top","right","left")]; ax.tick_params(left=False)
plt.tight_layout(); plt.savefig("/tmp/pf/charts/pace.png", transparent=True); plt.close()

fig, ax = plt.subplots(figsize=(7.6,3.2))
for sid,g in cur.groupby("show_id"):
    r = s[s.show_id==sid].iloc[0]
    col = ALERT if r.pace<.85 else (OK if r.pace>1.10 else GREY)
    ax.plot(g.dd,g.f*100,color=col,lw=1.9 if col!=GREY else .9,zorder=3 if col!=GREY else 1)
    if col==ALERT: ax.text(g.dd.iloc[-1]+.8,g.f.iloc[-1]*100,r.city,fontsize=8,color=col,va="center")
ax.plot(ref.index,ref.values*100,color=INK,lw=1.4,ls=(0,(4,3)),zorder=4)
ax.text(6,ref.reindex(range(0,7)).ffill().iloc[-1]*100+7,"référence : médiane de la tournée",fontsize=7.5,color=INK)
ax.set_xlabel("Jours depuis la mise en vente"); ax.set_ylabel("% de la jauge vendue")
ax.set_xlim(0,76); ax.yaxis.set_major_formatter(PercentFormatter())
[ax.spines[x].set_visible(False) for x in ("top","right")]
plt.tight_layout(); plt.savefig("/tmp/pf/charts/curve.png", transparent=True); plt.close()

# ------------------------------------------------------------- 2. CHANNELS
ch = orb.groupby("channel").agg(tickets=("qty","sum"),gross=("gross","sum")).reset_index()
ch["share"]=ch.tickets/ch.tickets.sum()
ch["fees"]=[float((orb[orb.channel==c].fee_per_ticket*orb[orb.channel==c].qty).sum()) for c in ch.channel]
ch=ch.sort_values("tickets",ascending=False)
ob = b[b.buyer_id.isin(orb.buyer_id)]
R.update(channels=ch.round(4).to_dict("records"),
         official_share=float(ch.loc[ch.channel=="Site officiel","share"].iloc[0]),
         reseller_fees=float(ch.fees.sum()),
         orbite_buyers=int(len(ob)), contactable=int(ob.contactable.sum()),
         contactable_pct=float(ob.contactable.mean()))
R["unreachable"]=R["orbite_buyers"]-R["contactable"]

fig, ax = plt.subplots(figsize=(7.6,1.35)); left=0
pal={"Site officiel":OK,"Fnac Spectacles":"#B4B4B4","Ticketmaster":"#C6C6C6","Dice":"#D6D6D6","Shotgun":"#E4E4E4"}
for _,r in ch.iterrows():
    ax.barh(0,r.share,left=left,color=pal[r.channel],height=.5)
    ax.text(left+r.share/2,0,f"{r.channel}\n{r.share*100:.0f} %",ha="center",va="center",
            fontsize=8,color="white" if r.channel=="Site officiel" else INK)
    left+=r.share
ax.set_xlim(0,1); ax.axis("off"); plt.tight_layout()
plt.savefig("/tmp/pf/charts/channels.png", transparent=True); plt.close()

# ------------------------------------------------------------------ 3. RFM
last=o.groupby("buyer_id").order_date.max(); freq=o.groupby("buyer_id").order_id.count()
mon=o.groupby("buyer_id").gross.sum()
rfm=pd.DataFrame({"recency":(pd.Timestamp(REF)-last).dt.days,"frequency":freq,"monetary":mon})
rfm["R"]=pd.qcut(rfm.recency,4,labels=[4,3,2,1]).astype(int)
rfm["F"]=pd.cut(rfm.frequency,[0,1,2,3,99],labels=[1,2,3,4]).astype(int)
rfm["M"]=pd.qcut(rfm.monetary.rank(method="first"),4,labels=[1,2,3,4]).astype(int)

set24, setorb = set(old.buyer_id), set(orb.buyer_id)
nshows = orb.groupby("buyer_id").show_id.nunique()
m_hi = rfm.monetary.quantile(.75)
def seg(i,r):
    if i in set24 and i in setorb:       return "Noyau dur"          # came to both tours
    if i not in setorb:                  return "À réactiver"        # 2024 only, silent since
    if nshows.get(i,0) >= 2:             return "Multi-dates"        # ORBITE, ≥2 villes
    if r.monetary >= m_hi:               return "Gros paniers"
    return "Nouveaux acheteurs"
rfm["segment"]=[seg(i,r) for i,r in rfm.iterrows()]
rfm=rfm.join(b.set_index("buyer_id")[["contactable","opt_in_email","opt_in_push","source","dept"]])
seg_sum=(rfm.groupby("segment").agg(buyers=("recency","size"),recency=("recency","median"),
         freq=("frequency","mean"),spend=("monetary","mean"),contactable=("contactable","mean"))
         .sort_values("spend",ascending=False).reset_index())
R["segments"]=seg_sum.round(3).to_dict("records")
R["reactivate_n"]=int(seg_sum.loc[seg_sum.segment=="À réactiver","buyers"].iloc[0])
R["reactivate_contactable"]=int(rfm[(rfm.segment=="À réactiver")&(rfm.contactable)].shape[0])
R["reactivation_rate"]=float(len(set24&setorb)/len(set24))
rfm.reset_index().rename(columns={"index":"buyer_id"}).to_csv("/tmp/pf/data/rfm_segments.csv",index=False)

fig, ax = plt.subplots(figsize=(7.6,2.9))
sg=seg_sum.sort_values("buyers")
cmap={"Noyau dur":INK,"À réactiver":ALERT,"Multi-dates":"#6E6E6E"}
ax.barh(sg.segment,sg.buyers,color=[cmap.get(x,"#CECECE") for x in sg.segment],height=.6)
for i,(n,sp,cc) in enumerate(zip(sg.buyers,sg.spend,sg.contactable)):
    ax.text(n+50,i,f"{n:,}".replace(","," ")+f"    {sp:.0f} € en moyenne    {cc*100:.0f} % joignables",
            va="center",fontsize=8,color=MUT)
ax.set_xlim(0,sg.buyers.max()*1.95); ax.set_xlabel("Acheteurs")
[ax.spines[x].set_visible(False) for x in ("top","right","left")]; ax.tick_params(left=False)
plt.tight_layout(); plt.savefig("/tmp/pf/charts/segments.png",transparent=True); plt.close()

# ------------------------------------------------------------- 4. GEOGRAPHY
geo=orb.merge(b[["buyer_id","dept"]],on="buyer_id").groupby("dept").qty.sum().sort_values(ascending=False)
R["top_depts"]={k:int(v) for k,v in geo.head(6).items()}
json.dump(R,open("/tmp/pf/results.json","w"),indent=1,default=str,ensure_ascii=False)

print(s[["city","venue","capacity","sold","fill","pace","days_to_show"]].to_string(index=False))
print("\n",ch.to_string(index=False))
print("\nbuyers %d | contactable %d (%.1f%%) | unreachable %d | reseller fees %.0f EUR"%(
      R["orbite_buyers"],R["contactable"],R["contactable_pct"]*100,R["unreachable"],R["reseller_fees"]))
print("\n",seg_sum.to_string(index=False))
print("\nlagging",R["lagging"],"gap",R["gap"],"| reactivation rate %.1f%%"%(R["reactivation_rate"]*100),
      "| à réactiver joignables",R["reactivate_contactable"],"/",R["reactivate_n"])
print("fill total %.1f%% | GMV %.0f"%(R["avg_fill"]*100,R["gmv"]))
