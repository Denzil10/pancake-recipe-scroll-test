"""Aggregate data/*-r*.json (3 runs per site) into index.html.
usage: python3 -I tools/build_report.py <folder>
"""
import json, sys, glob, statistics, shutil, html
from pathlib import Path

root = Path(sys.argv[1])
FIRST_PARTY = json.loads((root / "tools" / "first_party.json").read_text()) if (root / "tools" / "first_party.json").exists() else {}
NAMES = {
    "allrecipes": "Allrecipes", "joyfoodsunshine": "JoyFoodSunshine", "onceuponachef": "Once Upon a Chef",
    "handletheheat": "Handle the Heat", "thestayathomechef": "The Stay at Home Chef", "budgetbytes": "Budget Bytes",
    "preppykitchen": "Preppy Kitchen", "inspiredtaste": "Inspired Taste", "thekitchn": "The Kitchn",
    "foodnetwork": "Food Network", "kingarthur": "King Arthur Baking", "tasty": "Tasty",
    "bettycrocker": "Betty Crocker", "sallysbaking": "Sally's Baking", "bbcgoodfood": "BBC Good Food",
}
order = [l.split("\t")[0] for l in (root / "tools" / "sites.tsv").read_text().splitlines() if l.strip()]

def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None

sites, blocked = [], []
for slug in order:
    runs = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(root / "data" / f"{slug}-r*.json")))]
    good = [r for r in runs if not r.get("timeout") and not r.get("blocked") and r.get("ingredients")]
    if not good:
        blocked.append({"slug": slug, "name": NAMES[slug], "url": runs[0]["url"] if runs else "",
                        "runs": runs,
                        "reason": "; ".join(sorted({(f"HTTP {r.get('status')} - " + (r.get("title") or "")) if r.get("blocked")
                                                   else ("timed out" if r.get("timeout") else "no ingredient list found")
                                                   for r in runs}))})
        continue
    fp = set(FIRST_PARTY.get(slug, []))
    for r in good:
        # Cloudflare bot-challenge traffic (challenges.cloudflare.com) is excluded: it is likely
        # inflated by the test browser itself, not something every reader downloads.
        r["mb"] = round(r["mb"] - r.get("mb_by_domain", {}).get("cloudflare.com", 0), 2)
        r["tp"] = len([d for d in r["third_party_domains"] if d not in fp])
    s = {"slug": slug, "name": NAMES[slug], "url": good[0]["url"], "n": len(good), "nruns": len(runs),
         "screens": med([r["ingredients"]["screens"] for r in good]),
         "words": med([r["ingredients"]["words_before"] for r in good]),
         "overlays": med([r["overlay_count"] for r in good]),
         "tp": med([r["tp"] for r in good]),
         "mb": med([r["mb"] for r in good]),
         "rng": {k: (min(v), max(v)) for k, v in {
             "screens": [r["ingredients"]["screens"] for r in good],
             "words": [r["ingredients"]["words_before"] for r in good],
             "overlays": [r["overlay_count"] for r in good],
             "tp": [r["tp"] for r in good],
             "mb": [r["mb"] for r in good]}.items()}}
    # representative run = the one whose overlay count is the median (ties -> first)
    rep = min(good, key=lambda r: (abs(r["overlay_count"] - s["overlays"]), abs(r["mb"] - s["mb"])))
    s["rep"] = rep
    s["first_ing"] = " ".join(rep["ingredients"]["firstText"].replace("▢", " ").split())
    src = root / "shots" / f"{slug}-r{good[0]['run']}.jpg"
    if src.exists():
        shutil.copy(src, root / "shots" / f"{slug}.jpg")
    sites.append(s)

METRICS = [("screens", "Screens before ingredients", "{:.1f}"), ("words", "Words before ingredients", "{:,.0f}"),
           ("overlays", "Popups & overlays", "{:.0f}"), ("tp", "Third-party domains", "{:.0f}"), ("mb", "Megabytes", "{:.1f}")]
mx = {k: max(s[k] for s in sites) or 1 for k, _, _ in METRICS}
for s in sites:
    s["score"] = round(100 * sum(s[k] / mx[k] for k, _, _ in METRICS) / len(METRICS))
sites.sort(key=lambda s: -s["score"])
(root / "data" / "summary.json").write_text(json.dumps(
    [{k: s[k] for k in ("slug", "name", "url", "score", "screens", "words", "overlays", "tp", "mb", "rng", "n")} for s in sites] +
    [{"slug": b["slug"], "blocked": b["reason"]} for b in blocked], indent=1))

e = html.escape
def bar(k, v, fmt, rng):
    w = 100 * v / mx[k]
    spread = "" if rng[0] == rng[1] else f" (runs: {fmt.format(rng[0])}–{fmt.format(rng[1])})"
    return (f'<div class="m" title="{e(fmt.format(v))}{e(spread)}"><div class="track"><div class="fill" style="width:{w:.1f}%"></div></div>'
            f'<span class="v">{fmt.format(v)}</span></div>')

KIND_ORDER = ["consent", "signup", "app promo", "video", "ad", "site bar"]
rows = []
for i, s in enumerate(sites, 1):
    kinds = {}
    for o in s["rep"]["overlays"]:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    kind_txt = ", ".join(f"{n}× {k}" for k, n in sorted(kinds.items(), key=lambda kv: KIND_ORDER.index(kv[0]))) or "none"
    fp = set(FIRST_PARTY.get(s["slug"], []))
    tops = [d for d in s["rep"]["third_party_domains"] if d not in fp][:8]
    mbd = ", ".join(f"{d} {v:.1f}" for d, v in [kv for kv in s["rep"].get("mb_by_domain", {}).items() if kv[0] != "cloudflare.com"][:3])
    cells = "".join(f'<td data-label="{e(lbl)}">{bar(k, s[k], fmt, s["rng"][k])}</td>' for k, lbl, fmt in METRICS)
    rows.append(f"""
<tr>
 <td class="rank">{i}</td>
 <td class="site"><img src="shots/{s['slug']}.jpg" alt="First screen of {e(s['name'])}" width="130">
   <div><a href="{e(s['url'])}">{e(s['name'])}</a><div class="score">score {s['score']}</div></div></td>
 {cells}
</tr>
<tr class="detail"><td></td><td colspan="6">
 <b>Overlays seen:</b> {e(kind_txt)} &nbsp;·&nbsp; <b>Ingredient list starts with:</b> “{e(s['first_ing'])}”
 &nbsp;·&nbsp; <b>Biggest downloads (MB):</b> {e(mbd)}<br>
 <b>Some outside domains:</b> {e(', '.join(tops))}{' …' if s['tp'] > 8 else ''}
</td></tr>""")

blocked_html = "".join(
    f'<li><a href="{e(b["url"])}">{e(b["name"])}</a> — <b>blocked us</b>: {e(b["reason"])}. No numbers reported.</li>'
    for b in blocked) or "<li>None — every site loaded.</li>"

worst = sites[0]
best = sites[-1]
avg_screens = statistics.mean(s["screens"] for s in sites)
avg_words = statistics.mean(s["words"] for s in sites)
when = sorted({r["started"][:10] for s in sites for r in [s["rep"]]})[0]

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>How much do recipe sites make you scroll? Pancakes, measured.</title>
<style>
:root {{ --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#8a8984; --line:#e6e5e0; --series:#2a78d6; --track:#eeede8; --accent:#c2410c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#8f8e86; --line:#33332f; --series:#3987e5; --track:#2a2a27; --accent:#fb923c; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--surface); color:var(--ink) }}
main {{ max-width:1180px; margin:0 auto; padding:16px }}
a {{ color:var(--series) }}
/* ---- the one-screen recipe: must fit 390x844 ---- */
#recipe {{ max-width:390px; height:auto; max-height:844px; margin:0 auto 28px; padding:14px 16px 12px; border:1px solid var(--line); border-radius:14px; font-size:15px; line-height:1.32 }}
#recipe h1 {{ font-size:22px; margin:0 0 2px }}
#recipe .meta {{ color:var(--ink2); font-size:13px; margin:0 0 8px }}
#recipe h2 {{ font-size:13px; letter-spacing:.06em; text-transform:uppercase; color:var(--accent); margin:10px 0 4px }}
#recipe ul, #recipe ol {{ margin:0; padding-left:20px }}
#recipe li {{ margin:2px 0 }}
#recipe .tip {{ font-size:13px; color:var(--ink2); margin:8px 0 0 }}
h2.sec {{ font-size:20px; margin:28px 0 6px }}
.lede {{ font-size:17px; max-width:780px }}
.lede b {{ color:var(--accent) }}
table {{ width:100%; border-collapse:collapse; margin-top:8px }}
th {{ text-align:left; font-size:12px; color:var(--ink2); font-weight:600; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:bottom }}
td {{ padding:10px 8px 4px; vertical-align:middle }}
tr.detail td {{ padding:0 8px 14px; font-size:12.5px; color:var(--ink2); border-bottom:1px solid var(--line) }}
td.rank {{ font-size:20px; font-weight:700; color:var(--muted); width:28px }}
td.site {{ display:flex; gap:10px; align-items:center; min-width:250px }}
td.site img {{ border:1px solid var(--line); border-radius:6px; height:auto }}
td.site a {{ font-weight:650; font-size:15px; color:var(--ink); text-decoration:none }}
td.site a:hover {{ text-decoration:underline }}
.score {{ font-size:12px; color:var(--muted) }}
.m {{ display:flex; align-items:center; gap:6px; min-width:110px }}
.track {{ flex:1; height:8px; background:var(--track); border-radius:4px }}
.fill {{ height:8px; background:var(--series); border-radius:0 4px 4px 0; min-width:2px }}
.m:hover .fill {{ filter:brightness(1.15) }}
.v {{ font-variant-numeric:tabular-nums; font-weight:600; min-width:44px; text-align:right }}
.method {{ font-size:13.5px; color:var(--ink2); max-width:860px }}
.method li {{ margin:4px 0 }}
@media (max-width:820px) {{
  thead {{ display:none }}
  tr:not(.detail) {{ display:grid; grid-template-columns:28px 1fr; border-top:1px solid var(--line); padding-top:6px }}
  tr:not(.detail) td {{ grid-column:2; padding:3px 4px }}
  tr:not(.detail) td.rank {{ grid-column:1; grid-row:1 }}
  tr:not(.detail) td[data-label]::before {{ content:attr(data-label); font-size:11.5px; color:var(--ink2); display:block }}
  tr.detail {{ display:block }} tr.detail td {{ display:block }}
}}
</style></head>
<body><main>

<section id="recipe" aria-label="Pancake recipe">
 <h1>Pancakes</h1>
 <p class="meta">Makes 8–10 · 5 min prep · 15 min cooking</p>
 <h2>Ingredients</h2>
 <ul>
  <li>1½ cups (190 g) all-purpose flour</li>
  <li>2 tbsp sugar</li>
  <li>2 tsp baking powder</li>
  <li>½ tsp salt</li>
  <li>1¼ cups (300 ml) milk</li>
  <li>1 large egg</li>
  <li>3 tbsp butter, melted, plus more for the pan</li>
 </ul>
 <h2>Method</h2>
 <ol>
  <li>Whisk the flour, sugar, baking powder and salt in a bowl.</li>
  <li>In a jug, whisk the milk, egg and melted butter.</li>
  <li>Pour the wet into the dry. Stir until just combined; lumps are fine. Rest 5 min.</li>
  <li>Heat a pan over medium and add a little butter. Pour in ¼ cup batter per pancake.</li>
  <li>Flip when bubbles pop on top and the edges look dry, about 2 min. Cook 1 min more.</li>
 </ol>
 <p class="tip">Serve hot with butter and maple syrup. Keep a batch warm in a 200°F / 95°C oven.</p>
</section>

<h1 style="font-size:28px;margin:0 0 6px">How much do recipe sites make you scroll before the recipe?</h1>
<p class="lede">The recipe above fits on one phone screen. Then {len(sites)} popular pancake pages were loaded in headless Chromium at iPhone size (390×844) and scrolled like a person would. On average you scroll <b>{avg_screens:.1f} phone screens</b> and read past <b>{avg_words:,.0f} words</b> before the ingredient list starts.
The worst offender is <b>{e(worst['name'])}</b>. Its ingredient list starts {worst['screens']:.1f} screens down, after {worst['words']:,.0f} words. The page shows {worst['overlays']:.0f} overlays, contacts {worst['tp']:.0f} outside domains and downloads {worst['mb']:.1f} MB.</p>

<h2 class="sec">Ranking, worst to best</h2>
<p class="method" style="margin:0">Score = the average of the five measures, each scaled to the worst site (100 = worst on everything). Every number is the median of {max(s['n'] for s in sites)} separate visits. Hover a bar to see the range across visits. The screenshot shows the first screen on arrival.</p>
<table>
<thead><tr><th></th><th>Site (first screen)</th>{''.join(f'<th>{e(l)}</th>' for _, l, _ in METRICS)}</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>

<h2 class="sec">Sites that blocked the test browser</h2>
<ul class="method">{blocked_html}</ul>

<h2 class="sec">How this was measured</h2>
<ul class="method">
<li><b>Pages.</b> Web searches for “best pancake recipe”, “fluffy pancakes recipe from scratch” and “easy homemade pancake recipe”, plus searches for the biggest recipe publishers. The test kept each site's top pancake page, one page per site. Search engines don't publish traffic figures, so “most popular” means prominent in search results plus large well-known publishers.</li>
<li><b>Browser.</b> Real Chromium (Playwright, new headless mode) with a 390×844 viewport, 3× pixel density, touch enabled and an iPhone Chrome user agent. Fresh profile every visit (no cache, no cookies). Tests ran on {when} from a connection in India. Ads, consent banners and geo-targeted content can differ in other countries.</li>
<li><b>Behaviour.</b> Wait for the page to load and the network to go quiet (capped), plus 3 s. Take the screenshot. Tap “Agree/Accept” on a consent wall if there is one, as most people do. Then scroll in thumb-flicks of 560 px with 350 ms pauses to the bottom of the page (capped at 150 s). If a modal blocks scrolling, close it the way a person would.</li>
<li><b>Screens before ingredients.</b> Distance from the top of the page to the first line of the real ingredient list, divided by 844 px. Measured after scrolling, so ads that expand while you scroll are included. The real list is the first group of at least 3 visible lines that each have a quantity and an ingredient (“1½ cups flour”). Prose like “Flour: any all-purpose works” doesn't count. Each detected first line was checked against the recipe's own structured data and the screenshots.</li>
<li><b>Words before ingredients.</b> Visible words that come before that first ingredient line in the page: nav, story, tips, FAQ, ad labels. Text inside ad iframes isn't counted, so this number is on the low side.</li>
<li><b>Popups & overlays.</b> Distinct elements that float over the content: fixed-position elements, or sticky bars that follow you down the whole page. Each covers at least 4% of the screen at some point during the visit. Sticky site headers don't count. Pieces of one widget count once. Inline ads that stay in their own slot don't count.</li>
<li><b>Third-party domains.</b> Distinct registrable domains (e.g. <code>doubleclick.net</code>) the page or its frames requested, other than the site's own. Obvious domains owned by the same publisher (their CDN, parent company) don't count. Domains are a proxy for outside companies: one company can own several (e.g. Google: doubleclick.net, googlesyndication.com).</li>
<li><b>Megabytes.</b> Bytes transferred over the network (compressed body + headers) for every request during the visit, including ads loaded while scrolling. Ad-heavy pages keep loading new ads as long as they're open, so this counts one read-through (about 1–3 min), not a ceiling. One exclusion: Handle the Heat also downloaded 7–9 MB from Cloudflare's bot-check service (<code>challenges.cloudflare.com</code>). That traffic is likely inflated by the test browser itself, so it isn't counted (raw totals were 26–34 MB). Without it, Handle the Heat is still the heaviest page.</li>
</ul>
</main></body></html>
"""
(root / "index.html").write_text(page)
print("wrote index.html;", len(sites), "sites,", len(blocked), "blocked; worst:", worst["name"], worst["score"])
for s in sites:
    print(f"{s['score']:4} {s['name']:24} scr {s['screens']:5.1f} words {s['words']:6.0f} ov {s['overlays']:3.0f} tp {s['tp']:4.0f} mb {s['mb']:5.1f}  n={s['n']}/{s['nruns']}")
