function render({ model, el }) {
  el.className = "custom-annotation-root";

  const style = document.createElement("style");
  style.textContent = `
    .custom-annotation-root {
      font-family: system-ui, sans-serif;
      max-width: 48rem;
      line-height: 1.5;
    }
    .custom-annotation-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
      margin-bottom: 0.75rem;
    }
    .custom-annotation-toolbar label { font-size: 0.875rem; }
    .custom-annotation-toolbar select,
    .custom-annotation-toolbar button {
      font-size: 0.875rem;
      padding: 0.25rem 0.5rem;
    }
    .custom-annotation-text {
      white-space: pre-wrap;
      border: 1px solid #ccc;
      border-radius: 4px;
      padding: 0.75rem;
      min-height: 4rem;
      user-select: text;
      background: #fafafa;
    }
    .custom-annotation-text span.ca-span {
      border-radius: 2px;
      padding: 0 1px;
      cursor: pointer;
    }
    .custom-annotation-status {
      margin-top: 0.5rem;
      font-size: 0.8rem;
      color: #555;
    }
    .custom-annotation-list {
      margin-top: 0.75rem;
      font-size: 0.8rem;
    }
    .custom-annotation-list li {
      font-family: ui-monospace, monospace;
    }
  `;
  el.appendChild(style);

  const toolbar = document.createElement("div");
  toolbar.className = "custom-annotation-toolbar";

  const labelLabel = document.createElement("label");
  labelLabel.textContent = "Label:";
  const labelSelect = document.createElement("select");

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.textContent = "Add label to selection";

  const clearSelBtn = document.createElement("button");
  clearSelBtn.type = "button";
  clearSelBtn.textContent = "Clear selection";

  toolbar.append(labelLabel, labelSelect, addBtn, clearSelBtn);
  el.appendChild(toolbar);

  const textHost = document.createElement("div");
  textHost.className = "custom-annotation-text";
  textHost.setAttribute("role", "textbox");
  textHost.setAttribute("aria-readonly", "true");
  el.appendChild(textHost);

  const statusEl = document.createElement("div");
  statusEl.className = "custom-annotation-status";
  el.appendChild(statusEl);

  const listTitle = document.createElement("div");
  listTitle.textContent = "Annotations";
  listTitle.style.fontWeight = "600";
  listTitle.style.marginTop = "0.5rem";
  el.appendChild(listTitle);

  const listEl = document.createElement("ul");
  listEl.className = "custom-annotation-list";
  el.appendChild(listEl);

  let pending = null;

  function syncLabelOptions() {
    const labels = model.get("labels") || ["LABEL"];
    const active = model.get("active_label") || labels[0];
    labelSelect.innerHTML = "";
    for (const name of labels) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (name === active) opt.selected = true;
      labelSelect.appendChild(opt);
    }
  }

  function colorForLabel(label) {
    let hash = 0;
    for (let i = 0; i < label.length; i++) {
      hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
    }
    const hue = hash % 360;
    return `hsla(${hue}, 70%, 85%, 1)`;
  }

  function renderText() {
    const full = model.get("text") || "";
    const spans = [...(model.get("spans") || [])].sort((a, b) => a.start - b.start);
    textHost.innerHTML = "";
    let cursor = 0;
    for (const span of spans) {
      if (span.start > cursor) {
        textHost.appendChild(document.createTextNode(full.slice(cursor, span.start)));
      }
      const mark = document.createElement("span");
      mark.className = "ca-span";
      mark.title = `${span.label} (${span.start}:${span.end}) — click to remove`;
      mark.style.background = colorForLabel(span.label);
      mark.dataset.id = span.id;
      mark.textContent = full.slice(span.start, span.end);
      mark.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const next = (model.get("spans") || []).filter((s) => s.id !== span.id);
        model.set("spans", next);
        model.save_changes();
        model.set("status", "Removed annotation.");
        model.save_changes();
      });
      textHost.appendChild(mark);
      cursor = span.end;
    }
    if (cursor < full.length) {
      textHost.appendChild(document.createTextNode(full.slice(cursor)));
    }
  }

  function renderList() {
    const spans = model.get("spans") || [];
    listEl.innerHTML = "";
    for (const span of spans) {
      const li = document.createElement("li");
      li.textContent = `[${span.start}:${span.end}] ${span.label} — "${span.text ?? ""}"`;
      listEl.appendChild(li);
    }
  }

  function captureSelection() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      pending = null;
      return;
    }
    const range = sel.getRangeAt(0);
    if (!textHost.contains(range.commonAncestorContainer)) {
      pending = null;
      return;
    }
    const pre = document.createRange();
    pre.selectNodeContents(textHost);
    pre.setEnd(range.startContainer, range.startOffset);
    const start = pre.toString().length;
    const end = start + range.toString().length;
    pending = { start, end, snippet: range.toString() };
  }

  function addPending() {
    if (!pending || pending.start === pending.end) {
      model.set("status", "Select a non-empty text span first.");
      model.save_changes();
      return;
    }
    const label = labelSelect.value || model.get("active_label") || "LABEL";
    const full = model.get("text") || "";
    const id = crypto.randomUUID().slice(0, 12);
    const entry = {
      id,
      start: pending.start,
      end: pending.end,
      label,
      text: full.slice(pending.start, pending.end),
    };
    const spans = [...(model.get("spans") || []), entry];
    model.set("spans", spans);
    model.set("active_label", label);
    model.set("status", `Added ${label} on "${entry.text}".`);
    model.save_changes();
    pending = null;
    window.getSelection()?.removeAllRanges();
  }

  textHost.addEventListener("mouseup", () => captureSelection());
  textHost.addEventListener("keyup", () => captureSelection());
  addBtn.addEventListener("click", () => addPending());
  clearSelBtn.addEventListener("click", () => {
    pending = null;
    window.getSelection()?.removeAllRanges();
    model.set("status", "Selection cleared.");
    model.save_changes();
  });
  labelSelect.addEventListener("change", () => {
    model.set("active_label", labelSelect.value);
    model.save_changes();
  });

  model.on("change:text", renderText);
  model.on("change:spans", () => {
    renderText();
    renderList();
  });
  model.on("change:labels", syncLabelOptions);
  model.on("change:active_label", syncLabelOptions);
  model.on("change:status", () => {
    statusEl.textContent = model.get("status") || "";
  });

  syncLabelOptions();
  renderText();
  renderList();
  statusEl.textContent = model.get("status") || "";
}

export default { render };
