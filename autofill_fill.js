// Fills the visible application form in this page/frame from autofill.yaml answers.
// Called by autofill.py as:  return (function(P){...})(profile)
// NEVER clicks submit / next buttons. Fields matching never_fill are outlined red, filled ones
// green, required fields still empty orange. Returns a report for the terminal.
return (function (P) {
  const flags = "iu";
  const re = (s) => new RegExp(s, flags);
  const NEVER = re(P.never_fill);
  const CONSENT = re(P.consent);
  const FIELDS = P.fields.map((f) => ({ ...f, rx: re(f.match) }));
  const YESNO = P.yes_no.map((q) => ({ ...q, rx: re(q.match) }));
  const YES = /^\s*(yes|כן|true|y)(?!\p{L})/iu, NO = /^\s*(no|לא|false|n)(?!\p{L})/iu;
  const HEB = /[֐-׿]/;
  const report = { filled: [], checked: [], skipped_sensitive: [], todo: [], files: 0 };

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const mark = (el, color) => { try { el.style.outline = `3px solid ${color}`; el.style.outlineOffset = "1px"; } catch (e) {} };

  function textOf(el) {
    // label / aria / placeholder / name / nearby text — whatever describes this field
    const parts = [];
    if (el.labels) for (const l of el.labels) parts.push(l.innerText);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) for (const id of lb.split(/\s+/)) { const n = document.getElementById(id); if (n) parts.push(n.innerText); }
    for (const a of ["aria-label", "placeholder", "title", "data-label"]) parts.push(el.getAttribute(a));
    if (!clean(parts.join(" "))) {
      // no label: the closest container that holds only this field
      let n = el.parentElement;
      for (let i = 0; n && i < 4; i++, n = n.parentElement) {
        if (n.querySelectorAll("input,textarea,select").length > 1) break;
        const t = clean(n.innerText);
        if (t) { parts.push(t.slice(0, 120)); break; }
      }
    }
    parts.push((el.getAttribute("name") || "").replace(/[_\-\[\]]/g, " "), (el.id || "").replace(/[_\-]/g, " "));
    return clean(parts.filter(Boolean).join(" | "));
  }

  function questionOf(el) {
    // the question text of a radio group / select
    const fs = el.closest("fieldset");
    if (fs) { const lg = fs.querySelector("legend"); if (lg && clean(lg.innerText)) return clean(lg.innerText); }
    let n = el.parentElement;
    for (let i = 0; n && i < 6; i++, n = n.parentElement) {
      const t = clean(n.innerText);
      if (t.length > 8 && t.length < 400 && n.querySelectorAll("input[type=radio],select").length >= 1) {
        // drop the option labels themselves
        return t;
      }
    }
    return textOf(el);
  }

  function setValue(el, v) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype
      : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v); // works with React-controlled inputs
    for (const ev of ["input", "change", "blur"]) el.dispatchEvent(new Event(ev, { bubbles: true }));
  }

  function valueFor(field, label, el) {
    if (field.number !== undefined && el.type === "number") return String(field.number);
    if (field.value !== undefined) return field.value;
    return HEB.test(label) || document.documentElement.lang === "he" ? (field.he ?? field.en) : (field.en ?? field.he);
  }

  // Answers written as sentences ("I don't have any family member ...", "I have no problem to arrive ...").
  // yes → the one option that reads positive; no → the one that reads negative and not positive. Else null.
  const POS = /(^|\s)(yes|no problem|fine with|willing|i can|i agree|happy to|ok with|כן|אין בעיה|מוכן|מוכנה|מסכים|מסכימה)(?=$|[\s.,!?])/iu;
  const NEG = /(^|\s)(no|not|don'?t|do not|doesn'?t|none|never|אין|לא|אינני|אינו|אינה)(?=$|[\s.,!?])/iu;
  function sentencePick(opts, yn, text) {
    const pos = opts.filter((o) => POS.test(text(o)));
    const neg = opts.filter((o) => NEG.test(text(o)) && !POS.test(text(o)));
    if (yn === "yes") return pos.length === 1 ? pos[0] : null;
    return neg.length === 1 ? neg[0] : null;
  }

  function yesNo(question) {
    for (const q of YESNO) if (q.rx.test(question)) return q.answer === true || q.answer === "yes" ? "yes" : "no";
    return null;
  }

  // 1) text inputs / textareas / selects
  const els = [...document.querySelectorAll("input, textarea, select")].filter((el) => !el.disabled && !el.readOnly);
  for (const el of els) {
    const type = (el.type || "").toLowerCase();
    if (["hidden", "submit", "button", "reset", "image", "file", "radio", "checkbox", "password"].includes(type)) continue;
    if (!visible(el)) continue;
    const label = textOf(el);
    if (NEVER.test(label)) { mark(el, "red"); report.skipped_sensitive.push(label.slice(0, 60)); continue; }
    if (el.tagName !== "SELECT" && clean(el.value)) continue; // already filled (autofill / saved)

    if (el.tagName === "SELECT") {
      const opts = [...el.options].filter((o) => o.value !== "" && !/^(select|בחר|choose|--)/iu.test(clean(o.text)));
      if (el.selectedIndex > 0 && clean(el.value)) continue;
      let pick = null;
      const yn = yesNo(questionOf(el));
      if (yn && opts.some((o) => YES.test(o.text)) && opts.some((o) => NO.test(o.text))) {
        pick = opts.find((o) => (yn === "yes" ? YES : NO).test(o.text));
      } else if (yn && sentencePick(opts, yn, (o) => clean(o.text))) {
        pick = sentencePick(opts, yn, (o) => clean(o.text));
      } else {
        const f = FIELDS.find((f) => f.rx.test(label));
        if (f) {
          const want = clean(valueFor(f, label, el)).toLowerCase();
          if (want) pick = opts.find((o) => clean(o.text).toLowerCase() === want)
            || opts.find((o) => clean(o.text).toLowerCase().includes(want) || want.includes(clean(o.text).toLowerCase()));
        }
      }
      if (pick) { setValue(el, pick.value); mark(el, "limegreen"); report.filled.push(`${label.slice(0, 40)} = ${clean(pick.text)}`); }
      else if (el.required || el.getAttribute("aria-required") === "true") { mark(el, "orange"); report.todo.push(label.slice(0, 60)); }
      continue;
    }

    // long free-text questions ("why do you want to join...") are left for you
    // a long label made of a short field name + a site hint ("Mobile Phone | Only numbers ...") still counts
    const head = label.split(" | ")[0];
    const f = label.length <= 90 ? FIELDS.find((f) => f.rx.test(label))
      : head.length <= 40 ? FIELDS.find((f) => f.rx.test(head)) : null;
    const v = f ? valueFor(f, label, el) : "";
    if (v) {
      setValue(el, v); mark(el, "limegreen");
      report.filled.push(`${label.slice(0, 40)} = ${v}`);
    } else if (el.required || el.getAttribute("aria-required") === "true") {
      mark(el, "orange"); report.todo.push(label.slice(0, 60));
    }
  }

  // 2) radio groups (yes / no questions)
  const groups = {};
  for (const r of document.querySelectorAll("input[type=radio]")) {
    if (r.disabled) continue;
    (groups[r.name || r.id] = groups[r.name || r.id] || []).push(r);
  }
  for (const radios of Object.values(groups)) {
    if (radios.some((r) => r.checked)) continue;
    const q = questionOf(radios[0]);
    if (NEVER.test(q)) continue;
    const yn = yesNo(q);
    const opt = (r) => clean(textOf(r));
    const pick = yn && (radios.find((r) => (yn === "yes" ? YES : NO).test(opt(r)) || (yn === "yes" ? YES : NO).test(r.value))
                        || sentencePick(radios, yn, opt));
    if (pick) {
      pick.click(); if (!pick.checked) { pick.checked = true; pick.dispatchEvent(new Event("change", { bubbles: true })); }
      mark(pick.closest("label") || pick, "limegreen");
      report.filled.push(`${q.slice(0, 50)} = ${yn}`);
    } else if (radios.some((r) => r.required)) {
      mark(radios[0].closest("label") || radios[0], "orange"); report.todo.push(q.slice(0, 60));
    }
  }

  // 3) consent / privacy checkboxes
  for (const c of document.querySelectorAll("input[type=checkbox]")) {
    if (c.checked || c.disabled) continue;
    const label = textOf(c);
    if (CONSENT.test(label) && !NEVER.test(label)) {
      c.click(); if (!c.checked) { c.checked = true; c.dispatchEvent(new Event("change", { bubbles: true })); }
      mark(c.closest("label") || c, "limegreen");
      report.checked.push(label.slice(0, 50));
    }
  }

  report.files = document.querySelectorAll("input[type=file]").length;
  return report;
})(arguments[0]);
