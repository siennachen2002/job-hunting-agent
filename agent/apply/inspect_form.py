"""Read an application form's fields from the live page (Ashby / Greenhouse job-boards), without submitting anything."""
from __future__ import annotations
import json, re, sys
from playwright.sync_api import sync_playwright

JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const groupQuestion = (el) => {   // a radio's own label is its option ("Yes"); the question sits above the group
    const own = ((el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) || {}).innerText || '').trim();
    let n = el.parentElement;
    for (let i = 0; i < 7 && n; i++, n = n.parentElement) {
      const radios = n.querySelectorAll(`input[type="radio"]${el.name ? `[name="${CSS.escape(el.name)}"]` : ''}`);
      if (radios.length < 2 && i < 6) continue;
      for (const l of n.querySelectorAll('legend, label, [class*="label"], [class*="title"], [class*="question"], h3, h4, p')) {
        const t = (l.innerText || '').trim();
        if (t && t !== own && !l.querySelector('input') && !/^(yes|no)$/i.test(t)) return t;
      }
    }
    return '';
  };
  const labelFor = (el) => {
    if (el.type === 'radio') { const q = groupQuestion(el); if (q) return q; }
    if (el.id) { const u = document.getElementById('upload-label-' + el.id); if (u && u.innerText.trim()) return u.innerText.trim(); }
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l && !/^(attach|dropbox|enter manually)\b/i.test(l.innerText.trim())) return l.innerText.trim(); }
    if (el.type === 'file') {   // upload buttons are labelled "Attach"; the question is further up
      let n = el;
      for (let i = 0; i < 6 && n; i++) { n = n.parentElement; const l = n && n.querySelector('label, legend, [class*="label"]');
        if (l && l.innerText.trim() && !/^(attach|dropbox|enter manually)\b/i.test(l.innerText.trim())) return l.innerText.trim(); }
    }
    const wrap = el.closest('[class*="field"], fieldset, .application-question, [class*="Field"], [class*="question"]');
    if (wrap) { const l = wrap.querySelector('label, legend, [class*="label"], [class*="title"]'); if (l) return l.innerText.trim(); }
    return el.getAttribute('aria-label') || el.name || el.placeholder || '';
  };
  document.querySelectorAll('input, textarea, select, [role="combobox"]').forEach(el => {
    if (el.type === 'hidden' || el.type === 'submit') return;
    let label = labelFor(el).replace(/\s+/g, ' ').slice(0, 1200);
    const key = label + '|' + (el.name || el.id) + (el.type === 'radio' || el.type === 'checkbox' ? '|' + (el.id || el.value) : '');   // every option of a group
    if (seen.has(key)) return; seen.add(key);
    const wrap = el.closest('fieldset') || el.parentElement;
    let options = [];
    if (el.tagName === 'SELECT') options = [...el.options].map(o => o.text.trim()).filter(Boolean);
    if (el.type === 'radio' || el.type === 'checkbox') { const l = el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)); options = [l ? l.innerText.trim() : el.value]; }
    const fp = el.closest('[data-field-path]');
    out.push({ label, tag: el.tagName.toLowerCase(), type: el.type || el.getAttribute('role'), name: el.name || '', id: el.id || '', path: fp ? fp.getAttribute('data-field-path') : '',
               required: el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label), options });
  });
  return out;
}
"""

def inspect(url: str) -> list[dict]:
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 1600})
        pg.goto(url, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(1500)
        fields = pg.evaluate(JS)
        # custom dropdowns keep their options hidden until opened: open each once and read them
        for f in fields:
            if f["type"] == "combobox" and not f["options"] and f["id"] and len(f["options"]) == 0:
                try:
                    loc = pg.locator(f'[id="{f["id"]}"]').first
                    if not loc.is_visible():
                        continue
                    loc.scroll_into_view_if_needed(timeout=3000); loc.click(timeout=3000); pg.wait_for_timeout(500)
                    opts = [o.inner_text().strip() for o in pg.get_by_role("option").all()][:80]
                    f["options"] = [o for o in opts if o] if len(opts) < 80 else []   # very long lists (schools) are searched at fill time
                    pg.keyboard.press("Escape")
                except Exception:
                    pass
        b.close()
    for f in fields:   # "Question* Select..." is the same field's placeholder, not a second question
        f["label"] = re.sub(r"\s*select\.{3}\s*$", "", f["label"], flags=re.I)
    # merge radio/checkbox groups by label
    merged, idx = [], {}
    for f in fields:
        if f["type"] in ("radio", "checkbox") and f["name"]:
            k = f["name"]
            if k in idx: merged[idx[k]]["options"] += f["options"]; continue
            idx[k] = len(merged)
        merged.append(f)
    return merged

if __name__ == "__main__":
    for f in inspect(sys.argv[1]):
        print(("*" if f["required"] else " "), f["type"], "|", f["label"][:120], "|", f["options"][:6] if f["options"] else "")
