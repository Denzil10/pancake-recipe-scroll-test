"""Measure one recipe page in headless Chromium at iPhone size.

usage: python3 -I tools/measure.py <slug> <url> <outdir>
Writes <outdir>/data/<slug>.json and <outdir>/shots/<slug>.jpg (+ debug shots).
"""
import asyncio, json, sys, time, re
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright

VW, VH = 390, 844
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1")

MULTI = {"co.uk", "org.uk", "ac.uk", "com.au", "net.au", "co.nz", "co.jp", "co.in",
         "com.br", "co.za", "com.mx", "com.sg", "com.cn", "co.kr", "com.tr"}

def reg_domain(host):
    host = (host or "").lower().strip(".")
    if re.fullmatch(r"[\d.]+", host):
        return host
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])

# ---- in-page JS -------------------------------------------------------------
FIND_LIST_JS = r"""
() => {
  const Q = /(^|\s)(\d+([.,/]\d+)?|[½¼¾⅓⅔⅛]|\d+\s*[½¼¾⅓⅔⅛]|\d+\s+\d\/\d|one|two|three|a pinch|pinch)\s*(-\s*\d+\s*)?(cups?|c\.|tablespoons?|tbsps?|tbs|teaspoons?|tsps?|grams?|g|ml|millilit|ounces?|oz|pounds?|lbs?|large|medium|small|eggs?|sticks?|pinch|dash|quarts?|pints?|litres?|liters?|whole|heaping|level)\b/i;
  const ING = /(flour|milk|egg|sugar|baking powder|baking soda|bicarbonate|salt|butter|oil|buttermilk|vanilla|yogurt|cream)/i;
  const vis = el => { const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.05; };
  const hits = [];
  for (const el of document.querySelectorAll('li, p, div, span, td, label')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 140 || t.length < 4) continue;
    if (!Q.test(t) || !ING.test(t)) continue;
    // keep the innermost-ish: skip if a child element already carries the same text fully
    let child = false;
    for (const c of el.children) { if ((c.innerText||'').trim() === t) { child = true; break; } }
    if (child) continue;
    if (!vis(el)) continue;
    hits.push(el);
  }
  // group by nearest common container: walk up to 3 levels and count matching hits under it
  const groups = new Map();
  for (const h of hits) {
    let p = h.parentElement;
    for (let lvl = 0; p && lvl < 3; lvl++, p = p.parentElement) {
      if (!groups.has(p)) groups.set(p, new Set());
      groups.get(p).add(h);
    }
  }
  let best = null;
  for (const [p, set] of groups) {
    if (set.size < 3) continue;
    const arr = [...set];
    // first hit in document order
    arr.sort((a,b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
    const first = arr[0];
    const top = first.getBoundingClientRect().top + scrollY;
    if (!best || top < best.top - 1) best = {el: first, top, count: set.size, container: p};
  }
  window.__ingEl = best ? best.el : null;
  if (!best) return null;
  best.el.setAttribute('data-ing-first', '1');
  return {top: best.top, count: best.count,
          firstText: best.el.innerText.trim().slice(0,120),
          containerTag: best.container.tagName + '.' + (best.container.className||'').toString().slice(0,80)};
}
"""

WORDS_BEFORE_JS = r"""
() => {
  const target = document.querySelector('[data-ing-first]');
  if (!target) return null;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const visCache = new Map();
  const isVis = el => {
    if (visCache.has(el)) return visCache.get(el);
    let v = true;
    if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|SVG|TITLE)$/i.test(el.tagName)) v = false;
    else if (el.checkVisibility && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) v = false;
    else { const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) v = false; }
    visCache.set(el, v); return v;
  };
  let words = 0, n;
  const sample = [];
  while ((n = walker.nextNode())) {
    // stop at the first text node inside or after the ingredient list
    if (target.contains(n) || (target.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING)) break;
    const p = n.parentElement; if (!p || !isVis(p)) continue;
    const w = (n.nodeValue.match(/[A-Za-z0-9À-ɏ'’]+/g) || []).length;
    words += w;
  }
  return words;
}
"""

OVERLAY_JS = r"""
() => {
  const VW = innerWidth, VH = innerHeight, out = [];
  const els = document.querySelectorAll('body *');
  const docH = document.documentElement.scrollHeight;
  for (const el of els) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    // sticky only counts when it is page-level (sticks over the article), not an ad that
    // is sticky inside its own reserved ad slot
    if (s.position === 'sticky' && (!el.parentElement || el.parentElement.getBoundingClientRect().height < 0.5 * docH)) continue;
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) < 0.1) continue;
    const r = el.getBoundingClientRect();
    const x0 = Math.max(0, r.left), x1 = Math.min(VW, r.right), y0 = Math.max(0, r.top), y1 = Math.min(VH, r.bottom);
    if (x1 <= x0 || y1 <= y0) continue;
    const area = (x1-x0)*(y1-y0);
    if (area < 0.04 * VW * VH) continue;            // ignore tiny chips/buttons
    // skip if an ancestor is also a counted fixed element (count outermost only)
    let anc = el.parentElement, nested = false;
    while (anc && anc !== document.body) { const ps = getComputedStyle(anc).position; if (ps === 'fixed') { nested = true; break; } anc = anc.parentElement; }
    if (nested) continue;
    // must actually paint something (not an empty transparent wrapper)
    const hasPaint = s.backgroundColor !== 'rgba(0, 0, 0, 0)' || s.backgroundImage !== 'none' ||
      el.querySelector('iframe, img, video, button, p, h1, h2, h3, a, div[class*=ad], ins') !== null;
    if (!hasPaint) continue;
    const isHeader = r.top <= 2 && (r.bottom - r.top) <= 260 && (el.querySelector('nav, [class*=logo], [class*=Logo], a[href="/"], [class*=menu], [class*=Menu]') !== null || /header|nav/i.test(el.tagName + ' ' + el.className + ' ' + el.id));
    const cls = (el.className && el.className.toString ? el.className.toString() : '');
    const sig = el.tagName + '#' + (el.id||'') + '.' + cls.split(/\s+/).filter(c => !/\d{3,}/.test(c)).slice(0,3).join('.');
    const blob = (sig + ' ' + (el.innerText||'').slice(0,400)).toLowerCase();
    const hasAdFrame = el.querySelector('iframe[id*=google_ads], iframe[src*=doubleclick], iframe[id*=ad], ins.adsbygoogle') !== null;
    let kind = 'site bar';
    if (/cookie|consent|privacy|sp_message|onetrust|partners use|we value your/.test(blob)) kind = 'consent';
    else if (/subscribe|newsletter|sign up|send me|email|formkit|seva/.test(blob)) kind = 'signup';
    else if (/download the|in the app|get the app|branch-|open in app/.test(blob)) kind = 'app promo';
    else if (/player|video|cnx|jwplayer|ads end|ad ends/.test(blob)) kind = 'video';
    else if (hasAdFrame || /(^|[^a-z])(ad|ads|advert|adthrive|adhesive|anchor)([^a-z]|$)|ad-|adthrive|advertis/.test(blob)) kind = 'ad';
    out.push({sig, kind, pos: s.position, x0: Math.round(x0), y0: Math.round(y0), x1: Math.round(x1), y1: Math.round(y1),
              top: Math.round(r.top), h: Math.round(r.height), w: Math.round(r.width),
              frac: +(area/(VW*VH)).toFixed(3), header: isHeader,
              text: (el.innerText||'').replace(/\s+/g,' ').trim().slice(0,80)});
  }
  return out;
}
"""

BLOCK_RE = re.compile(r"(just a moment|attention required|access denied|verify you are human|are you a robot|"
                      r"captcha|request blocked|forbidden|pardon our interruption|unusual traffic)", re.I)


ACCEPT_RE = re.compile(r"^\s*(agree|i agree|accept|accept all|accept all cookies|accept cookies|i accept|allow all|allow|got it|ok|okay|continue)\s*$", re.I)


def overlap(a, b):
    ix = max(0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    sa = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"])
    sb = (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])
    return ix * iy / max(1, min(sa, sb))


async def main(slug, url, outdir, run):
    out = Path(outdir)
    for d in ("data", "shots", "debug"):
        (out / d).mkdir(parents=True, exist_ok=True)
    tag = f"{slug}-r{run}"
    site = reg_domain(urlparse(url).hostname)
    res = {"slug": slug, "run": run, "url": url, "site": site, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    reqs, sizes_tasks = [], []
    overlay_obs = []   # merged list of overlay dicts
    seen_sigs = {}

    def note(obs, phase):
        obs = [o for o in obs if not o["header"]]
        # merge pieces of the same widget seen in this snapshot
        obs.sort(key=lambda o: -o["frac"])
        groups = []
        for o in obs:
            for g in groups:
                if overlap(g[0], o) > 0.5:
                    g.append(o); break
            else:
                groups.append([o])
        for g in groups:
            big = g[0]
            sigs = {o["sig"] for o in g}
            known = next((seen_sigs[s_] for s_ in sigs if s_ in seen_sigs), None)
            if known is None:
                big = dict(big, phase=phase, parts=sorted(sigs))
                overlay_obs.append(big)
                known = big
            else:
                if big["frac"] > known["frac"]:
                    known["frac"] = big["frac"]
                if known["kind"] == "site bar" and big["kind"] != "site bar":
                    known["kind"] = big["kind"]
            for s_ in sigs:
                seen_sigs[s_] = known

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chromium", headless=True)
        ctx = await browser.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=3,
                                        is_mobile=True, has_touch=True, user_agent=UA,
                                        locale="en-US", timezone_id="America/New_York")
        page = await ctx.new_page()

        async def ev(js, timeout=20):
            return await asyncio.wait_for(page.evaluate(js), timeout)

        async def shot(name):
            try:
                await page.screenshot(path=str(out / "debug" / name), timeout=15000)
                return True
            except Exception:
                return False

        def on_req(r):
            h = urlparse(r.url).hostname
            if h and r.url.startswith("http"):
                reqs.append(h)
        ctx.on("request", on_req)

        async def grab(r):
            try:
                s = await asyncio.wait_for(r.sizes(), 10)
                return (reg_domain(urlparse(r.url).hostname), r.resource_type,
                        s["responseBodySize"] + s["responseHeadersSize"])
            except Exception:
                return ("?", "?", 0)
        ctx.on("requestfinished", lambda r: sizes_tasks.append(asyncio.ensure_future(grab(r))))

        t0 = time.time()
        status = None
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            status = resp.status if resp else None
        except Exception as e:
            res["error"] = f"goto: {e}"[:300]
        res["status"] = status
        for state, to in (("load", 20000), ("networkidle", 8000)):
            try:
                await page.wait_for_load_state(state, timeout=to)
            except Exception:
                pass
        await page.wait_for_timeout(3000)
        res["final_url"] = page.url
        try:
            res["title"] = await asyncio.wait_for(page.title(), 10)
        except Exception:
            res["title"] = ""

        # first screen exactly as a person sees it on arrival
        await shot(f"{tag}-first.png")
        try:
            note(await ev(OVERLAY_JS), "on arrival")
        except Exception:
            pass

        body_text = ""
        try:
            body_text = await ev("document.body ? document.body.innerText.slice(0, 3000) : ''")
        except Exception:
            pass
        blocked = (status in (401, 403, 429, 503)) or bool(BLOCK_RE.search(res["title"] or "")) or \
                  (len(body_text) < 1500 and bool(BLOCK_RE.search(body_text)))
        res["blocked"] = blocked
        res["body_head"] = body_text[:400]

        # a person taps "Agree/Accept" on a consent wall (may live in an iframe)
        res["consent_clicked"] = None
        if not blocked:
            for fr in page.frames:
                try:
                    btns = fr.locator("button, a[role=button], [role=button], input[type=button]")
                    n = min(await btns.count(), 60)
                    for k in range(n):
                        b = btns.nth(k)
                        txt = (await b.inner_text(timeout=500)).strip()
                        if ACCEPT_RE.match(txt) and await b.is_visible(timeout=500):
                            await b.click(timeout=2000)
                            res["consent_clicked"] = txt
                            break
                except Exception:
                    pass
                if res["consent_clicked"]:
                    break
            if res["consent_clicked"]:
                await page.wait_for_timeout(2500)

        # scroll like a person: thumb flicks of ~2/3 screen, short reading pauses
        scrolls, stuck = 0, 0
        await page.mouse.move(VW / 2, VH / 2)
        scroll_t0 = time.time()
        for i in range(220):
            if blocked or time.time() - scroll_t0 > 150:
                break
            try:
                y_before = await ev("scrollY")
                await page.mouse.wheel(0, 560)
                await page.wait_for_timeout(350)
                y_after = await ev("scrollY")
                at_bottom = await ev("scrollY + innerHeight >= document.documentElement.scrollHeight - 4")
            except Exception:
                res.setdefault("eval_timeouts", 0)
                res["eval_timeouts"] += 1
                continue
            if i % 2 == 0:
                try:
                    note(await ev(OVERLAY_JS), f"after scrolling {int(y_after / VH)} screens")
                except Exception:
                    pass
            if i == 6:
                await shot(f"{tag}-scroll.png")
            if y_after <= y_before:
                stuck += 1
                if at_bottom:
                    if stuck >= 3:
                        break
                    continue
                if stuck in (2, 5):
                    # something is trapping the scroll (modal). Do what a person does: close it.
                    res.setdefault("scroll_trapped", []).append(int(y_after))
                    await shot(f"{tag}-trapped{stuck}.png")
                    await page.keyboard.press("Escape")
                    for sel in ['[aria-label*="close" i]', 'button:has-text("No thanks")', 'button:has-text("Close")',
                                'button:has-text("Maybe later")']:
                        try:
                            loc = page.locator(sel).first
                            if await loc.is_visible(timeout=300):
                                await loc.click(timeout=1000)
                                break
                        except Exception:
                            pass
                if stuck >= 8:
                    await page.evaluate("window.scrollBy(0, 560)")
                if stuck >= 12:
                    break
            else:
                stuck = 0
            scrolls += 1
        res["scroll_steps"] = scrolls
        await page.wait_for_timeout(3000)

        ing = None
        if not blocked:
            try:
                res["page_height_px"] = await ev("document.documentElement.scrollHeight")
                ing = await ev(FIND_LIST_JS, 40)
            except Exception as e:
                res["ing_error"] = str(e)[:200]
            if ing:
                try:
                    await ev("window.__ingEl && window.__ingEl.scrollIntoView({block:'center'})")
                    await page.wait_for_timeout(2500)
                    top2 = await ev("""(() => { const e = document.querySelector('[data-ing-first]');
                         return e ? e.getBoundingClientRect().top + scrollY : null })()""")
                    if top2 is not None:
                        ing["top"] = top2
                    await shot(f"{tag}-ing.png")
                    ing["screens"] = round(ing["top"] / VH, 2)
                    ing["words_before"] = await ev(WORDS_BEFORE_JS, 40)
                except Exception as e:
                    res["ing_error"] = str(e)[:200]
            try:
                res["jsonld_first_ingredient"] = await ev(r"""(() => {
                  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                    try { const stack = [JSON.parse(s.textContent)];
                      while (stack.length) { const o = stack.pop(); if (!o || typeof o !== 'object') continue;
                        if (Array.isArray(o)) { stack.push(...o); continue; }
                        if (o.recipeIngredient) return o.recipeIngredient[0];
                        for (const v of Object.values(o)) if (typeof v === 'object') stack.push(v); }
                    } catch (e) {}
                  } return null; })()""")
            except Exception:
                res["jsonld_first_ingredient"] = None
        res["ingredients"] = ing

        await page.wait_for_timeout(2000)
        res["session_seconds"] = round(time.time() - t0, 1)
        sizes = await asyncio.gather(*sizes_tasks)
        res["bytes"] = int(sum(x[2] for x in sizes))
        bd, bt = {}, {}
        for d_, t_, n_ in sizes:
            bd[d_] = bd.get(d_, 0) + n_
            bt[t_] = bt.get(t_, 0) + n_
        res["mb_by_domain"] = {k: round(v / 1e6, 2) for k, v in sorted(bd.items(), key=lambda kv: -kv[1])[:12]}
        res["mb_by_type"] = {k: round(v / 1e6, 2) for k, v in sorted(bt.items(), key=lambda kv: -kv[1])}
        res["mb"] = round(res["bytes"] / 1e6, 2)
        res["requests"] = len(reqs)
        doms = {}
        for h in reqs:
            d = reg_domain(h)
            doms[d] = doms.get(d, 0) + 1
        third = {d: c for d, c in doms.items() if d != site}
        res["third_party_domains"] = dict(sorted(third.items(), key=lambda kv: -kv[1]))
        res["third_party_count"] = len(third)
        for o in overlay_obs:
            for k in ("x0", "x1", "y0", "y1"):
                o.pop(k, None)
        res["overlays"] = overlay_obs
        res["overlay_count"] = len(overlay_obs)
        try:
            await asyncio.wait_for(browser.close(), 20)
        except Exception:
            pass

    first = out / "debug" / f"{tag}-first.png"
    if first.exists():
        from PIL import Image
        im = Image.open(first).convert("RGB")
        im = im.resize((260, int(260 * im.height / im.width)), Image.LANCZOS)
        im.save(out / "shots" / f"{tag}.jpg", quality=72, optimize=True)
    (out / "data" / f"{tag}.json").write_text(json.dumps(res, indent=1))
    print(tag, "status", res.get("status"), "blocked", res["blocked"], "consent", res["consent_clicked"],
          "screens", (ing or {}).get("screens"), "words", (ing or {}).get("words_before"),
          "overlays", res["overlay_count"], [o["kind"] for o in overlay_obs],
          "3p", res["third_party_count"], "MB", res["mb"], flush=True)


async def guarded(slug, url, outdir, run):
    try:
        await asyncio.wait_for(main(slug, url, outdir, run), 420)
    except asyncio.TimeoutError:
        print(f"{slug}-r{run} TIMEOUT (page did not finish within 7 min)", flush=True)
        Path(outdir, "data", f"{slug}-r{run}.json").write_text(json.dumps(
            {"slug": slug, "run": run, "url": url, "timeout": True}))


if __name__ == "__main__":
    asyncio.run(guarded(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])))
