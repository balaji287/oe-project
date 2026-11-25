"""
eval_llm.py - LLM-stage evaluation for the PS265 Multilingual Tour Guide Assistant.

Run from the project folder (next to app.py) with GEMINI_API_KEY set in .env:
    python eval_llm.py            # full run: 69 calls
    python eval_llm.py --dry      # offline check of the script (mock model, no API calls)

Protocol (paper Section 4.8):
  * 60 profiles = 5 age groups x 4 languages (English, Hindi, Tamil, Kannada)
    x 3 destinations (Taj Mahal, Hampi, Meenakshi Amman Temple), 90 minutes, interest = history
  * 9 time-budget runs = 30/90/240 minutes x 3 destinations (English, adult, history)
  * Per run: latency, word count vs. word budget W(t), number of '## ' sections,
    clean ending (terminal punctuation), share of letters in the target script.
Outputs: eval_llm_runs.csv (one row per run) and eval_llm_summary.json / printed tables
(the numbers for Tables 6 and 7 of the paper). Factual accuracy and age-appropriateness
must still be rated manually.
"""
import csv, json, os, sys, time, statistics as st, unicodedata
from app import AGE_GROUPS, system_prompt, call_llm, LLMError

DRY = "--dry" in sys.argv
GAP_SECONDS = 13          # pause between calls to stay inside free-tier rate limits
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

DESTS = ["Taj Mahal", "Hampi", "Meenakshi Amman Temple"]
LANGS = ["English", "Hindi", "Tamil", "Kannada"]
TOUR_PROMPT = ("Create a personalized tour explanation. Format it in markdown with exactly these sections, each starting with "
               "'## ' (translate the headings): Overview, The Story, What To Look For, Insider Tip, Quick Facts. No other preamble.")

# Unicode ranges used to measure the share of letters written in the target script
SCRIPT_RANGES = {"English": [(0x41, 0x24F)], "Hindi": [(0x900, 0x97F)],
                 "Tamil": [(0xB80, 0xBFF)], "Kannada": [(0xC80, 0xCFF)]}
TERMINAL = tuple(".!?\u0964\u0965\u3002\u2026\"')\u201d\u2019*")  # incl. danda, closing quotes, bold marker


def script_share(text, lang):
    letters = [ch for ch in text if unicodedata.category(ch).startswith("L") or unicodedata.category(ch).startswith("M")]
    if not letters:
        return 0.0
    rng = SCRIPT_RANGES[lang]
    hit = sum(any(a <= ord(ch) <= b for a, b in rng) for ch in letters)
    return hit / len(letters)


def word_budget(minutes):
    return max(120, min(1200, minutes * 8))


def one_run(age, lang, dest, minutes, group):
    p = dict(name="Evaluator", age_group=age, interests=["history"], language=lang, minutes=minutes, destination=dest)
    t0 = time.perf_counter()
    err, text = "", ""
    if DRY:
        text = "## Overview\nText.\n## The Story\nText.\n## What To Look For\nText.\n## Insider Tip\nText.\n## Quick Facts\nText."
    else:
        for attempt in range(6):
            try:
                text = call_llm(system_prompt(p), [{"role": "user", "content": TOUR_PROMPT}])
                err = ""
                break
            except LLMError as e:
                err = str(e)
                busy = e.status in (429, 503, 504) or any(k in err for k in ("503", "429", "high demand", "timed out"))
                if busy and attempt < 5:
                    wait = 65 if "429" in err or e.status == 429 else 30 * (attempt + 1)
                    print(f"   server busy ({err[:60]}...), waiting {wait}s then retrying ({attempt + 1}/5)")
                    time.sleep(wait)    # overloaded or rate-limited: wait and retry
                else:
                    break
    lat = time.perf_counter() - t0
    words = len(text.split())
    secs = sum(1 for ln in text.splitlines() if ln.lstrip().startswith("## "))
    return dict(group=group, age_group=age, language=lang, destination=dest, minutes=minutes, budget=word_budget(minutes),
                latency_s=round(lat, 2), words=words, ratio=round(words / word_budget(minutes), 3) if words else 0,
                sections=secs, complete=int(secs == 5), clean_end=int(bool(text) and text.rstrip().endswith(TERMINAL)),
                script_share=round(script_share(text, lang), 3) if text else 0, error=err, text=text)


def main():
    runs = []
    grid = [(a, l, d, 90, "grid") for a in AGE_GROUPS for l in LANGS for d in DESTS]
    sweep = [("adult", "English", d, m, "sweep") for m in (30, 90, 240) for d in DESTS]
    jobs = grid + sweep
    print(f"{len(jobs)} runs, model={MODEL}, dry={DRY}")
    for i, job in enumerate(jobs, 1):
        r = one_run(*job)
        runs.append(r)
        print(f"[{i}/{len(jobs)}] {job} -> {r['words']} words, {r['sections']} sections, {r['latency_s']} s {r['error']}")
        if not DRY:
            time.sleep(GAP_SECONDS)
    cols = [c for c in runs[0] if c != "text"]
    with open("eval_llm_runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols + ["text"])
        w.writeheader(); w.writerows(runs)

    ok = [r for r in runs if not r["error"] and r["words"]]
    def pct(rows, key): return round(100 * sum(r[key] for r in rows) / len(rows), 1) if rows else None
    def mean(rows, key): return round(st.mean(r[key] for r in rows), 2) if rows else None
    summary = {
        "model": MODEL, "runs": len(runs), "errors": len(runs) - len(ok),
        "latency_mean_s": mean(ok, "latency_s"), "latency_median_s": round(st.median(r["latency_s"] for r in ok), 2) if ok else None,
        "all_five_sections_pct": pct(ok, "complete"), "clean_end_pct": pct(ok, "clean_end"),
        "mean_words_to_budget_ratio": mean(ok, "ratio"),
        "by_language_at_90min": {}, "by_age_group_at_90min": {}, "by_time_budget_adult_english": {},
    }
    g90 = [r for r in ok if r["group"] == "grid"]
    for l in LANGS:
        rr = [r for r in g90 if r["language"] == l]
        summary["by_language_at_90min"][l] = dict(n=len(rr), complete_pct=pct(rr, "complete"), clean_end_pct=pct(rr, "clean_end"),
                                                   mean_words=mean(rr, "words"), script_share=mean(rr, "script_share"), mean_latency_s=mean(rr, "latency_s"))
    for a in AGE_GROUPS:
        rr = [r for r in g90 if r["age_group"] == a]
        summary["by_age_group_at_90min"][a] = dict(n=len(rr), mean_words=mean(rr, "words"), mean_ratio=mean(rr, "ratio"))
    for m in (30, 90, 240):
        rr = [r for r in ok if r["group"] == "sweep" and r["minutes"] == m]
        summary["by_time_budget_adult_english"][m] = dict(n=len(rr), budget=word_budget(m), mean_words=mean(rr, "words"), mean_ratio=mean(rr, "ratio"))
    with open("eval_llm_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
