(function () {
  "use strict";

  // ── Scroll restoration ───────────────────────────────────
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";

  const savedScrollPos = sessionStorage.getItem("pcfScrollPos");
  if (savedScrollPos) document.documentElement.style.visibility = "hidden";

  // ── Helpers ──────────────────────────────────────────────
  function $id(id) { return document.getElementById(id); }

  function parseHiddenJson(id) {
    const el = $id(id);
    if (!el) return null;
    try { return JSON.parse(el.value || "{}"); } catch (e) { return null; }
  }

  // ── Core elements ────────────────────────────────────────
  const form          = $id("pcfForm");
  const saveDraftBtn  = $id("pcfSaveDraftBtn");
  const submitBtn     = $id("pcfSubmitBtn");
  const submitWrap    = $id("pcfSubmitWrap");
  const submitHelp    = $id("pcfSubmitHelp");
  const saveNext      = $id("pcfSaveNext");
  const overviewOpen  = $id("pcfOverviewOpen");
  const backBtn       = $id("pcfBackBtn");
  const cancelBtn     = $id("pcfCancelBtn");

  const ticketRef     = $id("pcfTicketRef");
  const changeReason  = $id("pcfChangeReason");
  const categoryWrap  = $id("pcfCategoryWrap");
  const categorySelect = categoryWrap ? categoryWrap.querySelector("select") : null;

  const bulkCsvInput  = $id("pcfBulkCsvInput");
  const bulkUploadBtn = $id("pcfBulkUploadBtn");
  const bulkModalEl   = $id("pcfBulkModal");
  const saveModalEl   = $id("pcfSaveDraftModal");
  const saveStayBtn   = $id("pcfSaveStayBtn");
  const saveBackBtn   = $id("pcfSaveBackBtn");

  const metaEl        = $id("pcfDraftUxMeta");
  const rowsAddedCount   = metaEl ? parseInt(metaEl.getAttribute("data-rows-added-count") || "0", 10) : 0;
  const focusRowIndexRaw = metaEl ? (metaEl.getAttribute("data-focus-row-index") || "") : "";
  const focusRowIndex    = focusRowIndexRaw === "" ? null : parseInt(focusRowIndexRaw, 10);

  // ── Baseline data ────────────────────────────────────────
  const baselineObj  = parseHiddenJson("pcfBaselinePayload") || {};
  const baselineRows = Array.isArray(baselineObj.rows) ? baselineObj.rows : [];

  let baselineUpdateIds = {};
  try {
    const raw = ($id("pcfBaselineUpdateIds") || {}).value || "{}";
    baselineUpdateIds = JSON.parse(raw);
  } catch (e) { baselineUpdateIds = {}; }

  // ── Operation badge helpers ──────────────────────────────
  const OP_CLASS = {
    "KEEP ROW":      "pcf-op-keep",
    "INSERT ROW":    "pcf-op-insert",
    "UPDATE ROW":    "pcf-op-update",
    "RETIRE ROW":    "pcf-op-retire",
    "UNRETIRE ROW":  "pcf-op-insert",
  };
  const OP_LABEL = {
    "KEEP ROW":      "Keep",
    "INSERT ROW":    "Insert",
    "UPDATE ROW":    "Update",
    "RETIRE ROW":    "Retire",
    "UNRETIRE ROW":  "Unretire",
  };

  function setOpBadge(rowIndex, code) {
    const badge = $id(`pcfOpBadge-${rowIndex}`);
    const hidden = $id(`pcfOpCode-${rowIndex}`);
    if (!badge) return;

    const cls = OP_CLASS[code] || "pcf-op-keep";
    badge.className = `pcf-op ${cls}`;
    badge.textContent = OP_LABEL[code] || code || "";
    if (hidden) hidden.value = code || "";
  }

  function setUpdateRowId(rowIndex, val) {
    const el = $id(`pcfUpdateRowId-${rowIndex}`);
    if (el) el.value = val || "";
  }

  // ── Baseline utilities ───────────────────────────────────
  function baselineValue(rowIndex, col) {
    const r = baselineRows[rowIndex];
    if (!r) return null;
    const v = r[col];
    return (v === undefined || v === null) ? "" : String(v);
  }

  function rowIsNew(rowIndex) { return baselineRows[rowIndex] == null; }

  function isRowRetired(rowIndex) {
    const el = $id(`pcfRowDelete-${rowIndex}`);
    return !!(el && el.value === "1");
  }

  // ── Dirty computation ────────────────────────────────────
  function recomputeAllDirty() {
    // Business cells
    document.querySelectorAll("input.pcf-business-cell").forEach(function (input) {
      const name = input.getAttribute("name") || "";
      const m = name.match(/^cell__(\d+)__(string_\d{2})$/);
      if (!m) return;

      const rowIndex = parseInt(m[1], 10);
      const col = m[2];

      if (isRowRetired(rowIndex)) {
        input.classList.remove("pcf-dirty");
        syncDisplayDirty(input, false);
        return;
      }

      const base = baselineValue(rowIndex, col);
      const now  = input.value ?? "";
      const dirty = (base === null) ? (now.trim() !== "") : (now !== base);

      input.classList.toggle("pcf-dirty", dirty);
      syncDisplayDirty(input, dirty);
    });

    // Comment cells
    document.querySelectorAll("textarea.pcf-comment-cell").forEach(function (el) {
      const rowIndex = parseInt(el.getAttribute("data-row-index") || "", 10);
      if (isNaN(rowIndex)) return;
      const orig  = el.getAttribute("data-orig") || "";
      const dirty = (el.value ?? "").trim() !== String(orig).trim();
      el.classList.toggle("pcf-dirty", dirty);
      syncDisplayDirty(el, dirty);
    });

    // Row-level dirty highlight
    document.querySelectorAll("tr[id^='pcfRow-']").forEach(function (tr) {
      const m = (tr.id || "").match(/^pcfRow-(\d+)$/);
      if (!m) return;
      const rowIndex = parseInt(m[1], 10);
      if (isRowRetired(rowIndex)) { tr.classList.remove("pcf-row-dirty"); return; }
      const hasDirty = !!tr.querySelector(".pcf-dirty");
      tr.classList.toggle("pcf-row-dirty", hasDirty);
    });

    updateSubmitState();
  }

  function syncDisplayDirty(input, dirty) {
    const cte = input.closest(".pcf-cte");
    if (!cte) return;
    const display = cte.querySelector(".pcf-cte-display");
    if (display) display.classList.toggle("pcf-dirty", dirty);
  }

  // ── Row intent (op badge + update_rowid) ─────────────────
  function deriveRowIntent(rowIndex) {
    const row = $id(`pcfRow-${rowIndex}`);
    if (!row) return;

    if (isRowRetired(rowIndex)) {
      setOpBadge(rowIndex, "RETIRE ROW");
      setUpdateRowId(rowIndex, baselineUpdateIds[rowIndex] || "");
      return;
    }
    if (rowIsNew(rowIndex)) {
      setOpBadge(rowIndex, "INSERT ROW");
      setUpdateRowId(rowIndex, "");
      return;
    }
    const anyDirty = !!row.querySelector("input.pcf-business-cell.pcf-dirty");
    if (anyDirty) {
      setOpBadge(rowIndex, "UPDATE ROW");
      setUpdateRowId(rowIndex, baselineUpdateIds[rowIndex] || "");
    } else {
      setOpBadge(rowIndex, "KEEP ROW");
      setUpdateRowId(rowIndex, "");
    }
  }

  // ── Retire / undo ─────────────────────────────────────────
  const preDeleteSnapshots = new Map();

  function applyRetireUI(rowIndex, retiring) {
    const row    = $id(`pcfRow-${rowIndex}`);
    const btn    = $id(`pcfRetireBtn-${rowIndex}`);
    const inputs = row ? row.querySelectorAll("input.pcf-business-cell") : [];

    if (retiring) {
      // Snapshot
      const snap = {};
      inputs.forEach(function (i) { snap[i.getAttribute("data-col") || ""] = i.value ?? ""; });
      preDeleteSnapshots.set(rowIndex, snap);

      // Restore baseline values, lock inputs
      inputs.forEach(function (i) {
        const col  = i.getAttribute("data-col") || "";
        const base = baselineValue(rowIndex, col);
        i.value    = (base === null) ? "" : base;
        i.readOnly = true;
        i.classList.remove("pcf-dirty");

        // Close any open CTE editor and update display
        const cte = i.closest(".pcf-cte");
        if (cte) {
          cteClose(cte, true);
          const display = cte.querySelector(".pcf-cte-display");
          if (display) { display.textContent = i.value; display.classList.remove("pcf-dirty"); }
        }
      });

      if (row) { row.classList.add("pcf-row-retired"); row.classList.remove("pcf-row-dirty"); }
      if (btn) {
        btn.innerHTML = '↶';
        btn.classList.add("is-undo");
        btn.setAttribute("aria-label", "Restore Row");
      }

    } else {
      // Restore snapshot
      const snap = preDeleteSnapshots.get(rowIndex) || {};
      inputs.forEach(function (i) {
        const col = i.getAttribute("data-col") || "";
        if (Object.prototype.hasOwnProperty.call(snap, col)) i.value = snap[col];
        i.readOnly = false;
        // Update display pill
        const cte = i.closest(".pcf-cte");
        if (cte) {
          const display = cte.querySelector(".pcf-cte-display");
          if (display) display.textContent = i.value;
        }
      });

      const delInput = $id(`pcfRowDelete-${rowIndex}`);
      if (delInput) delInput.value = "0";

      if (row) row.classList.remove("pcf-row-retired");
      if (btn) {
        btn.innerHTML = '−';
        btn.classList.remove("is-undo");
        btn.setAttribute("aria-label", "Retire Row");
      }

      recomputeAllDirty();
    }

    deriveRowIntent(rowIndex);
  }

  // ── Save draft state ─────────────────────────────────────
  function metaFieldsDirty() {
    function changed(el) {
      if (!el) return false;
      return (el.value ?? "") !== (el.getAttribute("data-orig") ?? "");
    }
    const catOrig    = categoryWrap ? (categoryWrap.getAttribute("data-orig") ?? "") : "";
    const catChanged = categorySelect ? (categorySelect.value ?? "") !== catOrig : false;

    let commentDirty = false;
    document.querySelectorAll("textarea.pcf-comment-cell").forEach(function (el) {
      if ((el.value ?? "") !== (el.getAttribute("data-orig") ?? "")) commentDirty = true;
    });

    // Reference metadata fields (§0 section — steward/approver only)
    let metaSectionDirty = false;
    document.querySelectorAll(".pcf-hm-field").forEach(function (el) {
      if ((el.value ?? "") !== (el.getAttribute("data-orig") ?? "")) metaSectionDirty = true;
    });

    return changed(ticketRef) || changed(changeReason) || catChanged || commentDirty || metaSectionDirty;
  }

  function updateSaveDraftState() {
    const anyCellDirty = !!document.querySelector("input.pcf-business-cell.pcf-dirty");
    const dirty = anyCellDirty || metaFieldsDirty();
    if (saveDraftBtn) saveDraftBtn.disabled = !dirty;
    if (dirty) showSubmitBtn();
  }

  // Show the Submit button the first time any change is detected
  function showSubmitBtn() {
    if (submitBtn && submitBtn.style.display === "none") {
      submitBtn.style.display = "";
    }
  }

  // ── Submit gating ────────────────────────────────────────
  const CHANGE_OPS = new Set(["INSERT ROW", "UPDATE ROW", "RETIRE ROW", "UNRETIRE ROW"]);

  function hasAnyChangeOp() {
    let found = false;
    document.querySelectorAll("input[id^='pcfOpCode-']").forEach(function (el) {
      if (CHANGE_OPS.has((el.value || "").toUpperCase().trim())) found = true;
    });
    return found;
  }

  function computeMissing() {
    const missing = [];
    if (ticketRef    && !(ticketRef.value || "").trim())    missing.push("ticket");
    if (changeReason && !(changeReason.value || "").trim()) missing.push("reason");
    const cat = categorySelect ? (categorySelect.value || "").toUpperCase().trim() : "";
    if (!cat || cat === "NONE") missing.push("category");
    if (!hasAnyChangeOp()) missing.push("payload");
    return missing;
  }

  function updateSubmitState() {
    // Submit starts enabled — validation runs on click, not on every input.
    // This function is kept so callers don't break; it's a no-op now.
  }

  // Click on submit button → validate; block modal if missing fields
  if (submitBtn) {
    submitBtn.addEventListener("click", function (e) {
      const missing = computeMissing();
      if (missing.length === 0) {
        // All good — let the Bootstrap modal open naturally
        if (submitHelp) submitHelp.classList.add("d-none");
        if (ticketRef)      ticketRef.classList.remove("is-invalid");
        if (changeReason)   changeReason.classList.remove("is-invalid");
        if (categorySelect) categorySelect.classList.remove("is-invalid");
        return;
      }
      // Block the modal from opening and show inline errors
      e.preventDefault();
      e.stopImmediatePropagation();
      if (submitHelp) submitHelp.classList.remove("d-none");
      if (ticketRef)      ticketRef.classList.toggle("is-invalid",    missing.includes("ticket"));
      if (changeReason)   changeReason.classList.toggle("is-invalid", missing.includes("reason"));
      if (categorySelect) categorySelect.classList.toggle("is-invalid", missing.includes("category"));
    }, true); // capture phase so we beat Bootstrap's modal listener
  }

  // Hide the help message as soon as all required fields are filled
  document.addEventListener("input", function (e) {
    if (submitHelp && !submitHelp.classList.contains("d-none")) {
      if (computeMissing().length === 0) {
        submitHelp.classList.add("d-none");
        if (ticketRef)      ticketRef.classList.remove("is-invalid");
        if (changeReason)   changeReason.classList.remove("is-invalid");
        if (categorySelect) categorySelect.classList.remove("is-invalid");
      }
    }
  });

  // Auto-select first real category option
  if (categorySelect) {
    const cur = (categorySelect.value || "").toUpperCase().trim();
    if (!cur || cur === "NONE") {
      const first = Array.from(categorySelect.options || [])
        .find(function (o) { const v = (o.value || "").toUpperCase().trim(); return v && v !== "NONE"; });
      if (first) categorySelect.value = first.value;
    }
  }

  // ── Unified input listener ───────────────────────────────
  document.addEventListener("input", function (e) {
    const el = e.target;
    if (!el) return;

    if (el.classList.contains("pcf-business-cell")) {
      const rowIndex = parseInt(el.getAttribute("data-row-index") || "", 10);
      if (!isNaN(rowIndex) && isRowRetired(rowIndex)) return;
      recomputeAllDirty();
      if (!isNaN(rowIndex)) deriveRowIntent(rowIndex);
      updateSaveDraftState();
      return;
    }
    if (el.classList.contains("pcf-comment-cell")) {
      recomputeAllDirty();
      updateSaveDraftState();
      return;
    }
    if (el === ticketRef || el === changeReason) {
      updateSaveDraftState();
      updateSubmitState();
      return;
    }
    if (el.tagName === "SELECT" && el.closest("#pcfCategoryWrap")) {
      updateSaveDraftState();
      updateSubmitState();
    }
    // Reference metadata fields
    if (el.classList.contains("pcf-hm-field")) {
      updateSaveDraftState();
    }
  });

  // ── Change event listener — catches selects and checkboxes ──
  // Selects fire "change" (not "input") reliably; mirror the same logic.
  document.addEventListener("change", function (e) {
    const el = e.target;
    if (!el) return;
    if (el.tagName === "SELECT" && el.closest("#pcfCategoryWrap")) {
      updateSaveDraftState();
      updateSubmitState();
      return;
    }
    if (el.classList.contains("pcf-hm-field")) {
      updateSaveDraftState();
      return;
    }
  });

  // ── Retire toggle delegation ──────────────────────────────
  document.addEventListener("click", function (e) {
    const btn = e.target && e.target.closest && e.target.closest(".pcf-retire-btn");
    if (!btn) return;

    const rowIndex = parseInt(btn.getAttribute("data-row-index") || "", 10);
    if (isNaN(rowIndex)) return;

    const row = $id(`pcfRow-${rowIndex}`);

    // Newly inserted row → just hide it (SKIP)
    if (rowIsNew(rowIndex) && row) {
      row.querySelectorAll("input.pcf-business-cell").forEach(function (i) {
        i.value = ""; i.classList.remove("pcf-dirty"); i.readOnly = true;
      });
      const opCode = $id(`pcfOpCode-${rowIndex}`);
      if (opCode) opCode.value = "SKIP";
      setOpBadge(rowIndex, "");
      row.classList.add("pcf-row-retired");
      row.style.display = "none";
      updateSaveDraftState();
      return;
    }

    // Existing row → toggle retire
    const delInput = $id(`pcfRowDelete-${rowIndex}`);
    if (!delInput) return;
    const next = delInput.value === "1" ? "0" : "1";
    delInput.value = next;
    applyRetireUI(rowIndex, next === "1");
    updateSaveDraftState();
  });

  // ══════════════════════════════════════════════════════════
  // CLICK-TO-EDIT
  // ══════════════════════════════════════════════════════════

  let _activeCell = null;

  function cteOpen(cell) {
    if (_activeCell && _activeCell !== cell) cteClose(_activeCell, false);

    const tr = cell.closest("tr");
    if (tr && tr.classList.contains("pcf-row-retired")) return;

    const display = cell.querySelector(".pcf-cte-display");
    const editor  = cell.querySelector(".pcf-cte-editor");
    const input   = editor ? editor.querySelector("input, textarea") : null;
    if (!display || !editor || !input || input.readOnly) return;

    display.style.display = "none";
    editor.style.display  = "flex";
    input.focus();
    try { const len = input.value.length; input.setSelectionRange(len, len); } catch (_) {}
    _activeCell = cell;
  }

  function cteClose(cell, revert) {
    const display = cell.querySelector(".pcf-cte-display");
    const editor  = cell.querySelector(".pcf-cte-editor");
    const input   = editor ? editor.querySelector("input, textarea") : null;
    if (!display || !editor || !input) return;

    if (revert) {
      input.value = input.getAttribute("data-orig") || "";
    }

    // Sync display text
    display.textContent = input.value;

    editor.style.display  = "none";
    display.style.display = "";

    if (_activeCell === cell) _activeCell = null;

    // Trigger dirty/save/submit recalc
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function cteInitCell(cell) {
    if (cell.dataset.cteInit) return;
    cell.dataset.cteInit = "1";

    const display    = cell.querySelector(".pcf-cte-display");
    const editor     = cell.querySelector(".pcf-cte-editor");
    const input      = editor ? editor.querySelector("input, textarea") : null;
    const okBtn      = editor ? editor.querySelector(".pcf-cte-ok") : null;
    const cancelBtn  = editor ? editor.querySelector(".pcf-cte-x")  : null;

    if (!display || !editor || !input) return;

    display.addEventListener("click", function () { cteOpen(cell); });

    if (okBtn) okBtn.addEventListener("click", function (e) {
      e.stopPropagation(); cteClose(cell, false);
    });
    if (cancelBtn) cancelBtn.addEventListener("click", function (e) {
      e.stopPropagation(); cteClose(cell, true);
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && input.tagName !== "TEXTAREA") { e.preventDefault(); cteClose(cell, false); }
      if (e.key === "Escape") cteClose(cell, true);
    });
  }

  function cteInitAll() {
    document.querySelectorAll(".pcf-cte").forEach(cteInitCell);
  }

  // Click outside → confirm close
  document.addEventListener("click", function (e) {
    if (!_activeCell) return;
    if (!_activeCell.contains(e.target)) cteClose(_activeCell, false);
  });

  window.pcfInitCTE = cteInitAll;

  // ══════════════════════════════════════════════════════════
  // FORM SUBMIT INTERCEPTION (add_row scroll save)
  // ══════════════════════════════════════════════════════════
  if (form) {
    form.addEventListener("submit", function (e) {
      const submitter = e.submitter;
      if (!submitter) return;
      if (submitter.value === "add_row") {
        // Block if hidden rows exist (need save first)
        const hidden = document.querySelectorAll("tr[id^='pcfRow-'][style*='display: none']");
        if (hidden.length > 0) {
          e.preventDefault();
          alert("Please save your current changes before adding more rows.");
          return;
        }
        sessionStorage.setItem("pcfScrollPos", window.pageYOffset || document.documentElement.scrollTop);
        if (overviewOpen) overviewOpen.value = "1";
      }
    });
  }

  // ══════════════════════════════════════════════════════════
  // BULK UPLOAD MODAL
  // ══════════════════════════════════════════════════════════
  function syncBulkBtn() {
    if (!bulkUploadBtn) return;
    bulkUploadBtn.disabled = !(bulkCsvInput && bulkCsvInput.files && bulkCsvInput.files.length > 0);
  }
  if (bulkCsvInput) bulkCsvInput.addEventListener("change", syncBulkBtn);
  if (bulkModalEl) {
    bulkModalEl.addEventListener("shown.bs.modal", syncBulkBtn);
    bulkModalEl.addEventListener("hidden.bs.modal", function () {
      if (bulkCsvInput) bulkCsvInput.value = "";
      syncBulkBtn();
    });
  }
  syncBulkBtn();

  // ══════════════════════════════════════════════════════════
  // SAVE DRAFT MODAL ACTIONS
  // ══════════════════════════════════════════════════════════
  function hideModal(el) {
    if (!el) return;
    try { bootstrap.Modal.getOrCreateInstance(el).hide(); } catch (_) {}
  }

  function submitDraft(nextVal) {
    if (!form) return;
    if (saveNext) saveNext.value = nextVal;
    hideModal(saveModalEl);
    setTimeout(function () { form.requestSubmit(); }, 50);
  }

  if (saveStayBtn) saveStayBtn.addEventListener("click", function () { submitDraft("stay"); });
  if (saveBackBtn) saveBackBtn.addEventListener("click", function () { submitDraft("back"); });

  // ══════════════════════════════════════════════════════════
  // NAV GUARD (unsaved changes prompt)
  // ══════════════════════════════════════════════════════════
  let navConfirmed = false;

  function isDirtyForNav() {
    if (rowsAddedCount > 0) return true;
    if (document.querySelector("input.pcf-business-cell.pcf-dirty")) return true;
    return metaFieldsDirty();
  }

  function bindNavGuard(el) {
    if (!el) return;
    el.addEventListener("click", function (e) {
      if (navConfirmed || !isDirtyForNav()) return;
      if (!confirm("You have unsaved changes. Leave this page without saving?")) {
        e.preventDefault(); return;
      }
      navConfirmed = true;
    });
  }
  bindNavGuard(backBtn);
  bindNavGuard(cancelBtn);

  // ══════════════════════════════════════════════════════════
  // ROWS-ADDED NOTICE AUTO-DISMISS
  // ══════════════════════════════════════════════════════════
  (function () {
    const notice = $id("pcfRowsNotice");
    if (!notice) return;
    setTimeout(function () {
      try {
        if (window.bootstrap && bootstrap.Alert) { bootstrap.Alert.getOrCreateInstance(notice).close(); return; }
      } catch (_) {}
      notice.remove();
    }, 5000);
  })();

  // ══════════════════════════════════════════════════════════
  // INITIALISE
  // ══════════════════════════════════════════════════════════

  // Set up op badges and retire state for existing rows
  document.querySelectorAll("tr[id^='pcfRow-']").forEach(function (tr) {
    const m = (tr.id || "").match(/^pcfRow-(\d+)$/);
    if (!m) return;
    const rowIndex = parseInt(m[1], 10);

    const opCode = $id(`pcfOpCode-${rowIndex}`);
    const opNow  = (opCode ? opCode.value : "").toUpperCase().trim();
    const delInput = $id(`pcfRowDelete-${rowIndex}`);

    // Align hidden retire flag if payload says RETIRE ROW
    if ((opNow === "RETIRE ROW" || opNow === "DELETE") && delInput) delInput.value = "1";

    if (delInput && delInput.value === "1") {
      applyRetireUI(rowIndex, true);
    } else {
      deriveRowIntent(rowIndex);
    }
  });

  recomputeAllDirty();
  updateSaveDraftState();
  cteInitAll();

  // ── Restore scroll + focus after add_row ─────────────────
  if (savedScrollPos) {
    window.scrollTo(0, parseInt(savedScrollPos, 10));
    sessionStorage.removeItem("pcfScrollPos");
    document.documentElement.style.visibility = "visible";

    if (focusRowIndex !== null && !isNaN(focusRowIndex)) {
      setTimeout(function () {
        const row = $id("pcfRow-" + focusRowIndex);
        if (row) {
          row.scrollIntoView({ behavior: "smooth", block: "center" });
          const firstCte = row.querySelector(".pcf-cte");
          if (firstCte) cteOpen(firstCte);
        }
      }, 80);
    }
  } else if (focusRowIndex !== null && !isNaN(focusRowIndex)) {
    setTimeout(function () {
      const row = $id("pcfRow-" + focusRowIndex);
      document.documentElement.style.visibility = "visible";
      if (row) {
        row.scrollIntoView({ behavior: "smooth", block: "center" });
        const firstCte = row.querySelector(".pcf-cte");
        if (firstCte) cteOpen(firstCte);
      }
    }, 80);
  } else {
    document.documentElement.style.visibility = "visible";
  }

})();