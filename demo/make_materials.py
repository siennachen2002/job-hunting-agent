"""Make the demo's sample material: three PDFs and a voice memo about one fictional applicant, Taylor Brooks.

    python demo/make_materials.py          # PDFs (Playwright), then the voice memo
    python demo/make_materials.py pdf      # only the PDFs
    python demo/make_materials.py memo     # only the voice memo

The memo uses Kokoro (voice af_heart) when the running Python has it, else macOS `say`; ffmpeg makes the .m4a.
Every person, company and school named here is fictional. The files are committed, so a demo needs none of this.
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "materials"
NOTE = "Sample material for the Job Hunter Agent demo. Everyone and every organization named here is fictional."
CSS = """<style>@page { size: Letter; margin: 0.7in 0.75in 0.8in; }
body { font: 10.5pt/1.45 "Helvetica Neue", Helvetica, Arial, sans-serif; color: #1c1917; margin: 0; }
h1 { font-size: 22pt; margin: 0 0 2pt; letter-spacing: -.01em; } h2 { font-size: 10.5pt; margin: 16pt 0 6pt; padding-bottom: 3pt; border-bottom: 1px solid #d6d3d1; }
.muted { color: #57534e; } .row { display: flex; justify-content: space-between; margin-top: 8pt; } ul { margin: 4pt 0 0 0; padding-left: 14pt; } li { margin: 2pt 0; }
.note { position: fixed; bottom: 0; left: 0; right: 0; font-size: 7.5pt; color: #a8a29e; }
.serif { font-family: Georgia, "Times New Roman", serif; font-size: 11pt; line-height: 1.6; } .serif h1 { font-size: 18pt; } .serif h2 { border: 0; font-size: 12pt; }
</style>"""

RESUME = f"""{CSS}<h1>Taylor Brooks</h1>
<div class="muted">Senior Product Designer · New York, NY · taylor.brooks@example.com · (555) 010-0199 · taylorbrooks.example</div>
<h2>Experience</h2>
<div class="row"><b>Brightwater Labs · Senior Product Designer</b><span class="muted">New York, NY · 06/2021 - present</span></div>
<div class="muted">A fintech app for renters: utility bills, payments and autopay, used by 400,000 people; plus a dashboard for property managers.</div>
<ul><li>Redesigned onboarding and autopay setup; completion rose from 41% to 68% and autopay enrollment doubled in one quarter.</li>
<li>Designed the bill-forecast feature, now used by 120,000 renters each month.</li>
<li>Led design of an AI bill explainer that answers "why is my bill higher?" in plain language; support tickets fell 23%.</li>
<li>Designed the property-manager dashboard (payments, reconciliation, data tables) for 1,800 buildings, from research to launch.</li>
<li>Built the design system: 210 Figma components with matching React tokens, built with two engineers, plus its usage guide.</li>
<li>Ran 30 interviews with renters and landlords and turned them into the 2023 roadmap with the product and engineering leads.</li></ul>
<div class="row"><b>Northlight Studio · Design Intern</b><span class="muted">Brooklyn, NY · 06/2020 - 08/2020</span></div>
<ul><li>Designed and prototyped a museum's ticketing kiosk in Figma; tested it with 12 visitors.</li>
<li>Wrote the studio's accessibility checklist for client handoffs.</li></ul>
<h2>Education</h2>
<div class="row"><b>Riverside College of Design · BFA Interaction Design</b><span class="muted">05/2021</span></div>
<div class="muted">Capstone: Designing for Renters' Energy Decisions</div>
<h2>Skills</h2>
<div>Product design, Figma, prototyping, design systems, payments and billing flows, dashboards and data visualization,
AI product design (LLM features), user research, accessibility (WCAG 2.2), HTML, CSS and React basics</div>
<h2>Application details</h2>
<div>Authorized to work in the United States; no visa sponsorship needed, now or in the future. Willing to relocate within
the United States. Gender, race, Hispanic or Latino, veteran status, disability: prefer not to say. Required consent and
privacy boxes: I agree.</div>
<div class="note">{NOTE}</div>"""

LETTER = f"""{CSS}<div class="serif">
<div style="display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid #0f766e;padding-bottom:8pt;margin-bottom:28pt">
<b style="font:600 15pt Helvetica,Arial,sans-serif;color:#0f766e">Brightwater Labs</b><span class="muted" style="font:9pt Helvetica,Arial,sans-serif">New York, NY</span></div>
<p>September 15, 2026</p><p>Dear hiring team,</p>
<p>I have been Taylor Brooks's manager at Brightwater Labs for the past five years, and I recommend Taylor without reservation
for a senior product design role.</p>
<p>Taylor designed our bill-forecast feature, which 120,000 renters now use every month, and redesigned autopay setup, which
doubled enrollment in a quarter. Last year Taylor led the design of our AI bill explainer: Taylor wrote the evaluation set
of 200 real customer questions with our engineers, so we shipped only when the answers were right, and support tickets fell
23%. Taylor also designed our property-manager dashboard, led our first accessibility audit (140 issues fixed across iOS
and Android) and mentors two junior designers.</p>
<p>Engineers seek Taylor out before they start building, because Taylor's specifications answer their questions before
they ask them. Taylor is calm in reviews, precise with data, and generous with credit.</p>
<p>Please contact me with any questions.</p>
<p style="margin-top:28pt">Priya Raman<br><span class="muted">Head of Design, Brightwater Labs · priya.raman@example.com</span></p>
</div><div class="note">{NOTE}</div>"""

PAPER = f"""{CSS}<div class="serif">
<h1>Designing for Renters' Energy Decisions</h1>
<p class="muted" style="margin-top:0">Taylor Brooks · BFA Interaction Design capstone · Riverside College of Design · May 2021</p>
<h2>Abstract</h2>
<p>Renters pay utility bills they cannot predict and rarely control. This project followed 18 renter households through a
six-week diary study, mapped when they make energy decisions, and designed a bill-forecast card that shows next month's
likely bill and the one habit that moves it most. In a test with 24 participants, correct answers to "what will your next
bill be, roughly?" rose from 52% with a standard bill to 87% with the card.</p>
<h2>1. Method</h2>
<p>Eighteen households in Queens and Brooklyn kept a photo diary of every moment they thought about energy: adjusting a
thermostat, reading a bill, arguing about the air conditioner. I followed up with an interview in each home.</p>
<h2>2. Findings</h2>
<p>Decisions happen before the bill arrives, not after it. Households understood a bill in dollars, not in kilowatt-hours,
and trusted a forecast more when it named one cause they could change.</p>
<h2>3. Design: the bill-forecast card</h2>
<p>A single card shows the likely bill as a range in dollars, the habit that moves it most this month, and what changing
that habit would save. I prototyped it in Figma and tested three versions with 24 participants.</p>
<h2>4. Results</h2>
<p>With the card, 87% of participants estimated their next bill within ten percent, against 52% with a standard bill.
Participants also named a specific change they would make in 19 of 24 sessions.</p>
</div><div class="note">{NOTE}</div>"""

MEMO = ("Hey, it's Taylor. Quick one, because this isn't on my résumé. On weekends I built a Figma plugin called Contrast "
        "Buddy. It checks color contrast while you design, and suggests the closest color that actually passes W C A G. "
        "About three thousand designers use it, and it has a four point eight rating, which is higher than my karaoke rating. "
        "I also gave a talk about it at a design meetup in Brooklyn last spring. What I want next: a senior product design role, "
        "ideally fintech or AI products, in New York or hybrid.")


def pdfs() -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        for name, html in (("Taylor_Brooks_Resume.pdf", RESUME), ("Reference_letter_Priya_Raman.pdf", LETTER),
                           ("Capstone_paper_Renters_Energy.pdf", PAPER)):
            page.set_content(f"<!doctype html><meta charset='utf-8'>{html}")
            page.pdf(path=str(OUT / name), format="Letter", print_background=True, prefer_css_page_size=True)
            print("  made", name)
        b.close()


def memo() -> None:
    wav = OUT / "voice-memo.wav"
    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
        pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        sf.write(wav, np.concatenate([np.asarray(a) for _, _, a in pipe(MEMO, voice="af_heart", speed=1.05)]), 24000)
    except ImportError:
        subprocess.run(["say", "-o", str(wav.with_suffix(".aiff")), MEMO], check=True)
        wav = wav.with_suffix(".aiff")
    ff = shutil.which("ffmpeg")
    m4a = OUT / "Voice_memo_Contrast_Buddy.m4a"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-c:a", "aac", "-b:a", "64k", str(m4a)] if ff else
                   ["afconvert", "-f", "m4af", "-d", "aac", str(wav), str(m4a)], check=True)
    wav.unlink()
    print("  made", m4a.name)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    if sys.argv[1:] != ["memo"]:
        pdfs()
    if sys.argv[1:] in ([], ["memo"]):
        memo()
