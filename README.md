# How much do recipe sites make you scroll before the recipe?

Claude Code (Claude Opus 5.5, an AI coding agent) measured 15 popular pancake recipe pages in a headless Chromium at iPhone size (390x844): phone screens scrolled before the ingredient list, words before it, popups/overlays, third-party domains contacted, megabytes downloaded. Three visits per site, medians reported. The agent wrote the measuring code, ran it, double-checked the extreme numbers and built the report. Its one-screen pancake recipe is at the top.

Report: https://denzil10.github.io/pancake-recipe-scroll-test/

- Measured 2026-11-02/03 from a home connection in India; ads and consent banners can differ in the US/UK.
- The Kitchn returned HTTP 403 on all 3 visits; it is listed without numbers.
- Third-party domains stand in for outside companies; one company can own several domains.
- `data/` holds the raw per-visit results, `tools/` the agent's scripts (`measure.py`, `build_report.py`).

The whole prompt:

> Settle this with data: how much do recipe websites make you scroll through before the recipe? Use web search to find the 15 most popular pancake recipe pages, one per website. Open each in a real headless Chromium at iPhone size (390x844), let it load and scroll like a person would, then measure: how many phone screens you scroll before the ingredient list starts, how many words come before it, how many popups or overlays cover the page, how many outside companies (third-party domains) it contacts, and how many megabytes it downloads. Save a small screenshot of each first screen. Then build index.html: a report ranking them worst to best with the numbers and screenshots, and at the top your own pancake recipe written so the whole recipe fits on one phone screen. Double-check any number that looks extreme. If a site blocks you, say so instead of guessing. Work only in this folder. Finish by telling me the worst offender.
