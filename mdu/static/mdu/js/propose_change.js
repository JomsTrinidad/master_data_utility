(function () {
  // Prevent browser from trying to restore scroll position after POST-back navigation
  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }

  // Hide body until scroll is restored to prevent flash
  const savedScrollPos = sessionStorage.getItem('proposedDataScrollPos');
  if (savedScrollPos) {
    document.documentElement.style.visibility = 'hidden';
  }


  function $(id) { return document.getElementById(id); }


  function parseJsonHidden(id) {
    const el = $(id);
    if (!el) return null;
    try { return JSON.parse(el.value || "{}"); } catch (e) { return null; }
  }

  // Elements
  const form = $("proposeForm");

  // ----------------------------------------------------
  // Keep Request Overview expanded on Add New Row submit
  // ----------------------------------------------------
  form.addEventListener("submit", function (e) {
    const submitter = e.submitter;
    if (!submitter) return;

    // If adding a new row but there are removed rows, force a save first
    if (submitter.value === "add_row") {
      const removedRows = document.querySelectorAll('tr.d-none.mdu-row-locked');
      if (removedRows.length > 0) {
        e.preventDefault();
        alert("Please save your changes first (removed rows need to be saved) before adding new rows.");
        
        // Trigger save draft modal
        if (saveBtn && !saveBtn.disabled) {
          saveBtn.click();
        }
        return;
      }
      
      // Save current scroll position before submit
      sessionStorage.setItem('proposedDataScrollPos', window.pageYOffset || document.documentElement.scrollTop);




      
    }

    // Only intervene for Add New Row
    if (submitter.value !== "add_row") return;

    // FORCE accordion open state into POST payload
    const openInput = document.getElementById("requestOverviewOpen");
    if (openInput) {
      openInput.value = "1";
    }
  });

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
      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18"
          fill="none" viewBox="0 0 24 24">
        <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"
              stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
  }

  function undoIcon() {
    return `
      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18"
          fill="none" viewBox="0 0 24 24">
        <path d="M9 14l-4-4 4-4M5 10h8a6 6 0 110 12"
              stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
  }


  // ---------- Request Overview (Always Open; No Collapse) ----------
  // Keep POST-backed open flag stable, and do not attach any collapse handlers.
  if (openInput) openInput.value = "1";


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

  // ----------------------------------------------------
  // Submit gating (mirrors server-side rules)
  // ----------------------------------------------------
  const submitBtn = $("submitBtn");
  const submitBtnWrap = $("submitBtnWrap");
  const submitHelp = $("submitHelp");

  const changeTicketRef = $("changeTicketRef");
  const changeReason = $("changeReason");
  const changeCategory = document.querySelector('select[name="change_category"]');

  const CHANGE_OPS = new Set(["INSERT ROW", "UPDATE ROW", "RETIRE ROW", "UNRETIRE ROW"]);

  function _norm(v) {
    return (v == null ? "" : String(v)).trim();
  }

  function hasAnyChangeOp() {
    const opInputs = document.querySelectorAll('input[id^="opCode-"]');
    for (const el of opInputs) {
      const v = _norm(el.value).toUpperCase();
      if (CHANGE_OPS.has(v)) return true;
    }
    return false;
  }

  function computeMissingRequired() {
    const missing = [];
    if (changeTicketRef && !_norm(changeTicketRef.value)) missing.push("change_ticket_ref");
    if (changeReason && !_norm(changeReason.value)) missing.push("change_reason");

    const cat = changeCategory ? _norm(changeCategory.value).toUpperCase() : "";
    if (!cat || cat === "NONE") missing.push("change_category");

    if (!hasAnyChangeOp()) missing.push("payload_json");
    return missing;
  }

  function setInvalid(el, on) {
    if (!el) return;
    el.classList.toggle("is-invalid", !!on);
  }

  function showSubmitMissing(missing) {
    // Show helper text and highlight the fields.
    if (submitHelp) submitHelp.classList.remove("d-none");

    setInvalid(changeTicketRef, missing.includes("change_ticket_ref"));
    setInvalid(changeReason, missing.includes("change_reason"));
    setInvalid(changeCategory, missing.includes("change_category"));

    if (missing.includes("payload_json")) {
      // Guide the user to the table if they haven't made any row changes yet.
      const tableAnchor = document.querySelector("#proposedDataTableWrap") || document.querySelector("#proposedDataWrap") || document.querySelector("table");
      if (tableAnchor) tableAnchor.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      const overview = document.querySelector("#requestOverviewAccordion") || document.querySelector("#headingRequestOverview");
      if (overview) overview.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function updateSubmitState() {
    if (!submitBtn) return;
    const missing = computeMissingRequired();
    const ready = missing.length === 0;
    submitBtn.disabled = !ready;

    // Do not spam the helper text while typing; only show when already visible (server-side attempt)
    // or when the user clicks the disabled submit area.
    if (submitHelp && !ready && submitHelp.classList.contains("d-none")) {
      setInvalid(changeTicketRef, false);
      setInvalid(changeReason, false);
      setInvalid(changeCategory, false);
    }
  }

  // Allow the user to click the disabled submit button wrapper to see what is missing.
  if (submitBtnWrap) {
    submitBtnWrap.addEventListener("click", function () {
      if (!submitBtn || !submitBtn.disabled) return;
      showSubmitMissing(computeMissingRequired());
    });
  }

  // Do not let Change Category sit on a placeholder.
  if (changeCategory) {
    const cur = _norm(changeCategory.value).toUpperCase();
    if (!cur || cur === "NONE") {
      const opts = Array.from(changeCategory.options || []);
      const firstReal = opts.find(o => _norm(o.value) && _norm(o.value).toUpperCase() !== "NONE");
      if (firstReal) changeCategory.value = firstReal.value;
    }
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

      // RETIRE ROW overrides dirty visuals
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

    // Change comments are part of the draft and should also participate in dirty highlighting.
    const comments = document.querySelectorAll("textarea.change-comment-cell, input.change-comment-cell");
    for (const el of comments) {
      const rowIndex = parseInt(el.getAttribute("data-row-index") || "", 10);
      if (Number.isNaN(rowIndex)) continue;
      const orig = (el.getAttribute("data-orig") ?? "");
      const now = (el.value ?? "");
      const isDirty = (now.trim() !== String(orig).trim());
      if (isDirty) el.classList.add("mdu-dirty");
      else el.classList.remove("mdu-dirty");
    }

    updateSubmitState();
  }

  // ---------- Row intent derivation + delete/undo ----------
  const preDeleteSnapshots = new Map(); // rowIndex -> { col -> value }

  // label: what the user sees in the Operation column
  // code: what gets POSTed back to Django (must match locked UI labels)
  // Allowed codes: KEEP ROW | UPDATE ROW | INSERT ROW | RETIRE ROW | UNRETIRE ROW
  // Internal code (never meant to be persisted): SKIP (used when undoing an INSERT row)
  function setOp(rowIndex, label, code) {
    const opLabel = document.getElementById(`opLabel-${rowIndex}`);
    const opCode = document.getElementById(`opCode-${rowIndex}`);
    if (opLabel) opLabel.value = label || "";
    if (opCode) opCode.value = code || "";

    // Visual cue: only RETIRE ROW shows red operation text
    if (opLabel) {
      const isRetire = (String(code || "").toUpperCase() === "RETIRE ROW");
      opLabel.classList.toggle("text-danger", isRetire);
    }

    updateSubmitState();
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
      setOp(rowIndex, "RETIRE ROW", "RETIRE ROW");
      setUpdateRowId(rowIndex, hash);
      return;
    }

    if (rowIsNew(rowIndex)) {
      // UX rule: a newly added row defaults to INSERT ROW even if still blank
      setOp(rowIndex, "INSERT ROW", "INSERT ROW");
      setUpdateRowId(rowIndex, "");
      return;
    }


    const anyDirty = !!document.querySelector(`#row-${rowIndex} input.business-cell.mdu-dirty`);
    if (anyDirty) {
      const hash = baselineUpdateIds[rowIndex] || "";
      setOp(rowIndex, "UPDATE ROW", "UPDATE ROW");
      setUpdateRowId(rowIndex, hash);
    } else {
      setOp(rowIndex, "KEEP ROW", "KEEP ROW");
      setUpdateRowId(rowIndex, "");
    }
  }

  function applyDeleteUI(rowIndex, on) {
    const row = document.getElementById(`row-${rowIndex}`);
    if (!row) return;

    const btn = row.querySelector(`.mdu-row-toggle-delete[data-row-index="${rowIndex}"]`);
    const inputs = row.querySelectorAll("input.business-cell");
    const comment = document.getElementById(`changeComment-${rowIndex}`);

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

      // Change comment remains editable for RETIRE ROW
      if (comment) comment.readOnly = false;
      if (btn) {
        btn.innerHTML  = undoIcon(); //"↩";
        btn.setAttribute("aria-label", "Undo Retire");
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

      const cc = document.getElementById(`changeComment-${rowIndex}`);
      if (cc) cc.readOnly = false;

      // Remove Operation red unless it becomes RETIRE again via deriveRowIntent
      const opLabel = document.getElementById(`opLabel-${rowIndex}`);
      if (opLabel) opLabel.classList.remove("text-danger");

      row.classList.remove("mdu-row-deleted");
      row.classList.remove("mdu-row-locked");

      if (comment) comment.readOnly = false;

      if (comment) {
        comment.readOnly = false;
        comment.classList.remove("text-danger");
      }

      const del = document.getElementById(`rowDelete-${rowIndex}`);
      if (del) del.value = "0";

      if (btn) {
        btn.innerHTML  = deleteIcon();//"🗑";
    btn.setAttribute("aria-label", "Retire Row");
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

    // Any change comment edits should also enable Save Draft
    let commentChanged = false;
    const comments = document.querySelectorAll("textarea.change-comment-cell, input.change-comment-cell");
    for (const el of comments) {
      const orig = (el.getAttribute("data-orig") ?? "");
      if ((el.value ?? "") !== orig) { commentChanged = true; break; }
    }

    return changed(reason) || changed(ticket) || catChanged || commentChanged;
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
      updateSubmitState();
      return;
    }

    if (el.classList && el.classList.contains("change-comment-cell")) {
      recomputeAllDirty();
      updateSaveDraftState();
      updateSubmitState();
      return;
    }

    if (el.id === "changeReason" || el.id === "changeTicketRef") {
      updateSaveDraftState();
      updateSubmitState();
      return;
    }

    if (el.tagName === "SELECT" && el.closest("#changeCategoryWrap")) {
      updateSaveDraftState();
      updateSubmitState();
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

  // If it's a newly added (INSERT ROW) row, clicking the trash icon just hides it
  if (rowIsNew(rowIndex) && row) {
    // Clear values so the server doesn't treat it as an insert
    const inputs = row.querySelectorAll("input.business-cell");
    for (const i of inputs) {
      i.value = "";
      i.classList.remove("mdu-dirty");
      i.readOnly = true;
    }

    // Mark with an internal operation code so server can skip this row
    // (SKIP is never shown to users and should not be included in audits)
    setOp(rowIndex, "", "SKIP");
    setUpdateRowId(rowIndex, "");

    // Mark as locked + removed
    row.classList.add("mdu-row-locked");
    row.classList.add("d-none");

    updateSaveDraftState();
    return;
  }

    // Baseline rows: toggle RETIRE ROW / UNDO
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

      // If payload already has RETIRE ROW, ensure toggle reflects it and styling applied
      const opCode = document.getElementById(`opCode-${rowIndex}`);
      const opNow = opCode ? (opCode.value || "").toUpperCase() : "";
      const alreadyRetired = opNow === "RETIRE ROW" || opNow === "DELETE"; // legacy
      const del = document.getElementById(`rowDelete-${rowIndex}`);
      if (del && alreadyRetired) del.value = "1";

      if (del && del.value === "1") applyDeleteUI(rowIndex, true);
      else deriveRowIntent(rowIndex);
    }
  })();

  // ---------- Initialize all delete button icons ----------
  (function initDeleteIcons() {
    const deleteButtons = document.querySelectorAll('.mdu-row-toggle-delete');
    for (const btn of deleteButtons) {
      const rowIndex = parseInt(btn.getAttribute("data-row-index") || "", 10);
      if (Number.isNaN(rowIndex)) continue;
      
      // Check if row is already marked for deletion
      const del = document.getElementById(`rowDelete-${rowIndex}`);
      if (del && del.value === "1") {
        btn.innerHTML = undoIcon();
      } else {
        btn.innerHTML = deleteIcon();
      }
    }
  })();

  // ---------- Restore scroll and focus after Add Row ----------
  if (savedScrollPos) {
    // Restore scroll position immediately
    window.scrollTo(0, parseInt(savedScrollPos, 10));
    sessionStorage.removeItem('proposedDataScrollPos');
    
    // Make page visible again
    document.documentElement.style.visibility = 'visible';
    
    // Also scroll the table to bottom and focus new row
    if (focusRowIndex !== null && !Number.isNaN(focusRowIndex)) {
      setTimeout(function () {
        const scroller = $("proposedDataScroll");
        const row = $("row-" + focusRowIndex);
        
        if (scroller && row) {
          const rowTop = row.offsetTop;
          scroller.scrollTop = Math.max(0, rowTop - Math.floor(scroller.clientHeight * 0.25));
          
          const firstCell = row.querySelector('input.business-cell:not([readonly])');
          if (firstCell) {
            firstCell.focus({ preventScroll: true });
          }
        }
      }, 0);
    }
  } else if (focusRowIndex !== null && !Number.isNaN(focusRowIndex)) {
    // No saved scroll position, just focus the new row normally
    setTimeout(function () {
      const scroller = $("proposedDataScroll");
      const row = $("row-" + focusRowIndex);

      if (scroller && row) {
        const rowTop = row.offsetTop;
        scroller.scrollTop = Math.max(0, rowTop - Math.floor(scroller.clientHeight * 0.25));
        
        const firstCell = row.querySelector('input.business-cell:not([readonly])');
        if (firstCell) {
          firstCell.focus({ preventScroll: true });
        }
      }
    }, 0);
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

  // ---------- Auto-dismiss "Rows Added" notification ----------
(function () {
    const notice = document.getElementById("rowsAddedNotice");
    if (!notice) return;

    // Auto-hide after 30 seconds (adjust later if needed)
    window.setTimeout(function () {
      // If Bootstrap JS is available, use its alert close animation
      try {
        if (window.bootstrap && bootstrap.Alert) {
          const inst = bootstrap.Alert.getOrCreateInstance(notice);
          inst.close();
          return;
        }
      } catch (e) {}

      // Fallback: remove from DOM
      notice.remove();
    }, 5000);
  })();

})();