// docs/SPEC-v4.15-ui-bootstrap.md: toasts, confirm dialog for dangerous actions, busy buttons, screenshot zoom.
// Everything here is an extra: without JavaScript every form still posts and every page still works.
(function () {
  // flash toasts fade after 6 s (still role="status" for screen readers)
  document.querySelectorAll(".flash.toast[data-autohide]").forEach(function (el) {
    setTimeout(function () { el.classList.remove("show"); }, 6000);
    var close = el.querySelector("[data-bs-dismiss=toast]");
    if (close) close.addEventListener("click", function () { el.classList.remove("show"); });
  });

  // <form data-confirm="..."> or <button data-confirm="..."> -> Bootstrap modal instead of posting at once
  var modalEl = document.getElementById("confirm");
  var pending = null;
  document.addEventListener("submit", function (e) {
    var form = e.target, by = e.submitter;
    var text = (by && by.dataset.confirm) || form.dataset.confirm;
    if (!text || form.dataset.confirmed || !modalEl || !window.bootstrap) return;
    e.preventDefault();
    pending = [form, by];
    document.getElementById("confirm-text").textContent = text;
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }, true);
  var yes = document.getElementById("confirm-yes");
  if (yes) yes.addEventListener("click", function () {
    if (!pending) return;
    var form = pending[0], by = pending[1];
    form.dataset.confirmed = "1";
    window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    if (form.requestSubmit) form.requestSubmit(by || undefined); else form.submit();
  });

  // a posted form: spinner on the clicked button so nobody taps twice (not disabled: its name/value must post)
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented || (e.target.getAttribute("method") || "get").toLowerCase() !== "post") return;
    var by = e.submitter;
    if (by) setTimeout(function () { by.classList.add("htmx-request"); }, 0);
  });
  // HTMX: the clicked button is disabled while its request runs
  document.addEventListener("htmx:beforeRequest", function (e) { if (e.target.tagName === "BUTTON") e.target.disabled = true; });
  document.addEventListener("htmx:afterRequest", function (e) { if (e.target.tagName === "BUTTON") e.target.disabled = false; });

  // payment card: amount received vs order total, ✅ or ⚠️ while typing
  document.querySelectorAll("input[data-compare]").forEach(function (input) {
    var box = document.querySelector(".compare");
    if (!box) return;
    input.addEventListener("input", function () {
      var n = parseInt(input.value.replace(/[^0-9]/g, ""), 10), total = parseInt(box.dataset.total, 10);
      box.querySelector(".compare-amount").textContent = isNaN(n) ? "—" : n.toLocaleString("en-US");
      box.querySelector(".compare-mark").textContent = isNaN(n) ? "" : (n === total ? "✅" : "⚠️");
    });
  });

  // phones: wide tables (4+ columns) become label/value cards; each cell gets its column name
  document.querySelectorAll("main table:not(.cart-items)").forEach(function (table) {
    var heads = table.querySelectorAll("thead th");
    if (heads.length < 4) return;
    table.classList.add("stack-table");
    table.querySelectorAll("tbody tr").forEach(function (tr) {
      Array.prototype.forEach.call(tr.children, function (td, i) {
        if (heads[i] && !td.hasAttribute("data-label")) td.setAttribute("data-label", heads[i].textContent.trim());
      });
    });
  });

  // chat: open at the newest message (the thread scrolls inside its card)
  document.querySelectorAll(".chat-pane").forEach(function (el) { el.scrollTop = el.scrollHeight; });
})();
