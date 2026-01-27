(function () {
  function $(id) { return document.getElementById(id); }

  function parseJsonHidden(id) {
    const el = $(id);
    if (!el) return null;
    try { return JSON.parse(el.value || "{}"); } catch (e) { return null; }
  }

  // Elements
  const form = $("proposeForm");
  const saveBtn = $("saveDraftBtn");

  const accordionToggle = $("requestOverviewToggle");
  const collapseEl = $("collapseRequestOverview");
  const openInput = $("requestOverviewOpen");

  const backBtn = $("backToReferenceBtn");
  const cancelBtn = $("cancelBtn");

  const bulkCsvInput = $("bulkCsvInput");
  const bulkUploadBtn = $("bulkUploadBtn");
  const bulkModalEl = $("bulkUploadModal");

  const meta = $("draftUxMeta");
  const rowsAddedCount = meta ? parseInt(meta.getAttribute("data-rows-added-count") || "0", 10) : 0;
  const focusRowIndexRaw = meta ? (meta.getAttribute("data-focus-row-index") || "") : "";
  const focusRowIndex = focusRowIndexRaw === "" ? null : parseInt(focusRowIndexRaw, 10);

  // Save Draft modal elements
  const saveNext = $("saveNext");                 // hidden input name="save_next"
  const saveModalEl = $("saveDraftModal");        // modal id
  const saveStayBtn = $("saveDraftStayBtn");      // Keep Editing
  const saveBackBtn = $("saveDraftBackBtn");      // Return To Reference


  function deleteIcon() {
    return `
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
          fill="none" viewBox="0 0 24 24">
        <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"
              stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
  }

  function undoIcon() {
    return `
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
          fill="none" viewBox="0 0 24 24">
        <path d="M9 14l-4-4 4-4M5 10h8a6 6 0 110 12"
              stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
  }




  // ---------- Accordion label + open state ----------
  function setAccordionLabel(isExpanded) {
    if (!accordionToggle) return;
    accordionToggle.textContent = isExpanded
      ? "Request Overview — Click To Collapse"
      : "Request Overview — Click To Expand";
  }

  function setAccordionOpenHidden(isExpanded) {
    if (openInput) openInput.value = isExpanded ? "1" : "0";
  }

  if (collapseEl) {
    collapseEl.addEventListener("shown.bs.collapse", function () {
      setAccordionLabel(true);
      setAccordionOpenHidden(true);
    });
    collapseEl.addEventListener("hidden.bs.collapse", function () {
      setAccordionLabel(false);
      setAccordionOpenHidden(false);
    });

    const isExpanded = collapseEl.classList.contains("show");
    setAccordionLabel(isExpanded);
    setAccordionOpenHidden(isExpanded);
  }

  // ---------- Bulk upload button enable/disable ----------
  function syncBulkUploadBtn() {
    if (!bulkUploadBtn) return;
    const ok = !!(bulkCsvInput && bulkCsvInput.files && bulkCsvInput.files.length > 0);
    bulkUploadBtn.disabled = !ok;
  }

  if (bulkCsvInput) bulkCsvInput.addEventListener("change", syncBulkUploadBtn);

  if (bulkModalEl) {
    bulkModalEl.addEventListener("shown.bs.modal", syncBulkUploadBtn);
    bulkModalEl.addEventListener("hidden.bs.modal", function () {
      if (bulkCsvInput) bulkCsvInput.value = "";
      syncBulkUploadBtn();
    });
  }

  syncBulkUploadBtn();

  // ---------- Baseline-driven dirty ----------
  const baselineObj = parseJsonHidden("baselinePayload") || {};
  const baselineRows = Array.isArray(baselineObj.rows) ? baselineObj.rows : [];

  let baselineUpdateIds = {};
  try {
    const raw = (document.getElementById("baselineUpdateIds") || {}).value || "{}";
    baselineUpdateIds = JSON.parse(raw);
  } catch (e) {
    baselineUpdateIds = {};
  }

  function baselineValue(rowIndex, col) {
    const r = baselineRows[rowIndex];
    if (!r) return null; // new row not in baseline
    const v = r[col];
    return (v === undefined || v === null) ? "" : String(v);
  }

  function isRowDeleted(rowIndex) {
    const del = document.getElementById(`rowDelete-${rowIndex}`);
    return !!(del && del.value === "1");
  }

  function recomputeAllDirty() {
    const inputs = document.querySelectorAll("input.business-cell");
    for (const input of inputs) {
      const name = input.getAttribute("name") || "";
      const m = name.match(/^cell__(\d+)__(string_\d{2})$/);
      if (!m) continue;

      const rowIndex = parseInt(m[1], 10);
      const col = m[2];

      // DELETE overrides dirty visuals
      if (isRowDeleted(rowIndex)) {
        input.classList.remove("mdu-dirty");
        continue;
      }

      const base = baselineValue(rowIndex, col);
      const now = (input.value ?? "");

      let isDirty = false;
      if (base === null) isDirty = now.trim() !== "";
      else isDirty = now !== base;

      if (isDirty) input.classList.add("mdu-dirty");
      else input.classList.remove("mdu-dirty");
    }
  }

  // ---------- Row intent derivation + delete/undo ----------
  const preDeleteSnapshots = new Map(); // rowIndex -> { col -> value }

  function setOp(rowIndex, label, code) {
    const opLabel = document.getElementById(`opLabel-${rowIndex}`);
    const opCode = document.getElementById(`opCode-${rowIndex}`);
    if (opLabel) opLabel.value = label || "";
    if (opCode) opCode.value = code || "";
  }

  function setUpdateRowId(rowIndex, val) {
    const el = document.getElementById(`updateRowId-${rowIndex}`);
    if (el) el.value = val || "";
  }

  function rowHasAnyValue(rowIndex) {
    const row = document.getElementById(`row-${rowIndex}`);
    if (!row) return false;
    const inputs = row.querySelectorAll("input.business-cell");
    for (const i of inputs) {
      if ((i.value || "").trim() !== "") return true;
    }
    return false;
  }

  function rowIsNew(rowIndex) {
    return baselineRows[rowIndex] == null;
  }

  function deriveRowIntent(rowIndex) {
    // header rows don't have row-<idx> id; guard anyway
    const row = document.getElementById(`row-${rowIndex}`);
    if (!row) return;

    if (isRowDeleted(rowIndex)) {
      const hash = baselineUpdateIds[rowIndex] || "";
      setOp(rowIndex, "DELETE", "DELETE");
      setUpdateRowId(rowIndex, hash);
      return;
    }

    if (rowIsNew(rowIndex)) {
      // UX rule: a newly added row defaults to INSERT even if still blank
      setOp(rowIndex, "INSERT", "INSERT");
      setUpdateRowId(rowIndex, "");
      return;
    }


    const anyDirty = !!document.querySelector(`#row-${rowIndex} input.business-cell.mdu-dirty`);
    if (anyDirty) {
      const hash = baselineUpdateIds[rowIndex] || "";
      setOp(rowIndex, "UPDATE", "UPDATE");
      setUpdateRowId(rowIndex, hash);
    } else {
      setOp(rowIndex, "RETAIN", "");
      setUpdateRowId(rowIndex, "");
    }
  }

  function applyDeleteUI(rowIndex, on) {
    const row = document.getElementById(`row-${rowIndex}`);
    if (!row) return;

    const btn = row.querySelector(`.mdu-row-toggle-delete[data-row-index="${rowIndex}"]`);
    const inputs = row.querySelectorAll("input.business-cell");

    if (on) {
      // snapshot current edits for undo
      const snap = {};
      for (const i of inputs) {
        const col = i.getAttribute("data-col") || "";
        snap[col] = i.value ?? "";
      }
      preDeleteSnapshots.set(rowIndex, snap);

      // restore baseline values (clears dirty)
      for (const i of inputs) {
        const col = i.getAttribute("data-col") || "";
        const base = baselineValue(rowIndex, col);
        i.value = (base === null) ? "" : base;
        i.readOnly = true;
        i.classList.remove("mdu-dirty");
      }

      row.classList.add("mdu-row-deleted");
      row.classList.add("mdu-row-locked");
      if (btn) {
        btn.textContent = "↩";
        btn.setAttribute("aria-label", "Undo Delete");
      }
    } else {
      // restore snapshot
      const snap = preDeleteSnapshots.get(rowIndex) || {};
      for (const i of inputs) {
        const col = i.getAttribute("data-col") || "";
        if (Object.prototype.hasOwnProperty.call(snap, col)) {
          i.value = snap[col];
        }
        i.readOnly = false;
      }

      row.classList.remove("mdu-row-deleted");
      row.classList.remove("mdu-row-locked");

      const del = document.getElementById(`rowDelete-${rowIndex}`);
      if (del) del.value = "0";

      if (btn) {
        btn.textContent = "🗑";
        btn.setAttribute("aria-label", "Delete Row");
      }


      recomputeAllDirty();
    }

    deriveRowIntent(rowIndex);
  }

  // ---------- Save Draft enable/disable ----------
  function makerFieldsDirty() {
    const reason = $("changeReason");
    const ticket = $("changeTicketRef");
    const wrap = $("changeCategoryWrap");
    const select = wrap ? wrap.querySelector("select") : null;

    const changed = (el) => {
      if (!el) return false;
      const orig = el.getAttribute("data-orig") ?? "";
      return (el.value ?? "") !== orig;
    };

    const catOrig = wrap ? (wrap.getAttribute("data-orig") ?? "") : "";
    const catChanged = select ? ((select.value ?? "") !== catOrig) : false;

    return changed(reason) || changed(ticket) || catChanged;
  }

  function updateSaveDraftState() {
    const anyCellDirty = !!document.querySelector("input.business-cell.mdu-dirty");
    const changed = anyCellDirty || makerFieldsDirty();
    if (saveBtn) saveBtn.disabled = !changed;
  }

  // ---------- Unified input handler ----------
  document.addEventListener("input", function (e) {
    const el = e.target;
    if (!el) return;

    if (el.classList && el.classList.contains("business-cell")) {
      const rowIndex = parseInt(el.getAttribute("data-row-index") || "", 10);

      // If deleted, ignore edits (should be readonly anyway)
      if (!Number.isNaN(rowIndex) && isRowDeleted(rowIndex)) return;

      recomputeAllDirty();
      if (!Number.isNaN(rowIndex)) deriveRowIntent(rowIndex);
      updateSaveDraftState();
      return;
    }

    if (el.id === "changeReason" || el.id === "changeTicketRef") {
      updateSaveDraftState();
      return;
    }

    if (el.tagName === "SELECT" && el.closest("#changeCategoryWrap")) {
      updateSaveDraftState();
      return;
    }
  });

  // ---------- Trash / Undo click handler (event delegation) ----------
  document.addEventListener("click", function (e) {
    const btn = e.target && e.target.closest && e.target.closest(".mdu-row-toggle-delete");
    if (!btn) return;

    const rowIndex = parseInt(btn.getAttribute("data-row-index") || "", 10);
    if (Number.isNaN(rowIndex)) return;

    const row = document.getElementById(`row-${rowIndex}`);

    // If it's a newly added (INSERT) row, "delete" means remove from view
    if (rowIsNew(rowIndex) && row) {
    // Clear values so the server doesn't treat it as an insert
      const inputs = row.querySelectorAll("input.business-cell");
      for (const i of inputs) {
        i.value = "";
        i.classList.remove("mdu-dirty");
        i.readOnly = true;
      }

      setOp(rowIndex, "RETAIN", "");
      setUpdateRowId(rowIndex, "");

      // Mark as locked + removed
      row.classList.add("mdu-row-locked");
      row.classList.add("d-none");

      updateSaveDraftState();
      return;
    }


    // Baseline rows: toggle DELETE / UNDO
    const del = document.getElementById(`rowDelete-${rowIndex}`);
    if (!del) return;

    const next = (del.value === "1") ? "0" : "1";
    del.value = next;

    applyDeleteUI(rowIndex, next === "1");
    updateSaveDraftState();
  });

  // ---------- Initial compute ----------
  recomputeAllDirty();
  updateSaveDraftState();

  // Derive operation labels on load
  (function initRowIntents() {
    const trs = document.querySelectorAll('tr[id^="row-"]');
    for (const tr of trs) {
      const id = tr.getAttribute("id") || "";
      const m = id.match(/^row-(\d+)$/);
      if (!m) continue;

      const rowIndex = parseInt(m[1], 10);

      // If payload already has DELETE, ensure toggle reflects it and styling applied
      const opCode = document.getElementById(`opCode-${rowIndex}`);
      const alreadyDelete = opCode && (opCode.value || "").toUpperCase() === "DELETE";
      const del = document.getElementById(`rowDelete-${rowIndex}`);
      if (del && alreadyDelete) del.value = "1";

      if (del && del.value === "1") applyDeleteUI(rowIndex, true);
      else deriveRowIntent(rowIndex);
    }
  })();

  // ---------- Reduce bounce: collapse accordion before add_row / bulk_upload submits ----------
  if (form && collapseEl) {
    form.addEventListener("submit", function (e) {
      const submitter = e.submitter;
      if (!submitter) return;

      const action = submitter.value;
      if (action !== "add_row" && action !== "bulk_upload") return;

      try {
        setAccordionOpenHidden(false);
        const bs = bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false });
        bs.hide();
      } catch (err) {}
    });
  }

  // ---------- Focus newly added row / show notice ----------
  if (focusRowIndex !== null && !Number.isNaN(focusRowIndex)) {
    setTimeout(function () {
      const row = $("row-" + focusRowIndex);
      if (row) {
        row.scrollIntoView({ behavior: "auto", block: "center" });
        const firstCell = row.querySelector("input.business-cell");
        if (firstCell) firstCell.focus();
      }
      const notice = $("rowsAddedNotice");
      if (notice) notice.scrollIntoView({ behavior: "auto", block: "nearest" });
    }, 25);
  }

  // ---------- Save Draft modal actions ----------
  function hideModal(el) {
    if (!el) return;
    try {
      const inst = bootstrap.Modal.getOrCreateInstance(el);
      inst.hide();
    } catch (e) {}
  }

  function submitDraft(nextVal) {
    if (!form) return;
    if (saveNext) saveNext.value = nextVal; // "stay" or "back"
    hideModal(saveModalEl);
    setTimeout(function () {
      form.requestSubmit();
    }, 50);
  }

  if (saveStayBtn) saveStayBtn.addEventListener("click", function () { submitDraft("stay"); });
  if (saveBackBtn) saveBackBtn.addEventListener("click", function () { submitDraft("back"); });

  // ---------- Unsaved changes prompt ----------
  let navConfirmed = false;

  function isDirtyForNav() {
    if (rowsAddedCount > 0) return true;
    if (document.querySelector("input.business-cell.mdu-dirty")) return true;
    return makerFieldsDirty();
  }

  function bindNavConfirm(el) {
    if (!el) return;
    el.addEventListener("click", function (e) {
      if (navConfirmed) return;
      if (!isDirtyForNav()) return;

      const ok = confirm("You Have Unsaved Changes. Leave This Page Without Saving?");
      if (!ok) {
        e.preventDefault();
        return;
      }
      navConfirmed = true;
    });
  }

  bindNavConfirm(backBtn);
  bindNavConfirm(cancelBtn);
})();
