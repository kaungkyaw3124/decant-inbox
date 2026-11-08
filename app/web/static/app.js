// docs/SPEC-v4.15-ui-bootstrap.md: toasts, confirm dialog for dangerous actions, busy buttons, screenshot zoom.
// docs/SPEC-v5.3-performance-pc.md: no full reloads (htmx boost), prefetch on hover, optimistic send, live
// updates (SSE), keyboard. Everything here is an extra: without JavaScript every form still posts and every
// page still works. Nothing with customer data is ever written to localStorage / sessionStorage / cookies.
(function () {
  var htmx = window.htmx;
  // runs for the first page and again for every part htmx swaps in
  var onLoad = htmx ? htmx.onLoad : function (fn) { fn(document.body); };

  onLoad(function (root) {
    // flash toasts fade after 6 s (still role="status" for screen readers)
    root.querySelectorAll(".flash.toast[data-autohide]").forEach(function (el) {
      setTimeout(function () { el.classList.remove("show"); }, 6000);
      var close = el.querySelector("[data-bs-dismiss=toast]");
      if (close) close.addEventListener("click", function () { el.classList.remove("show"); });
    });

    // payment card: amount received vs order total, ✅ or ⚠️ while typing
    root.querySelectorAll("input[data-compare]").forEach(function (input) {
      var box = document.querySelector(".compare");
      if (!box) return;
      input.addEventListener("input", function () {
        var n = parseInt(input.value.replace(/[^0-9]/g, ""), 10), total = parseInt(box.dataset.total, 10);
        box.querySelector(".compare-amount").textContent = isNaN(n) ? "—" : n.toLocaleString("en-US");
        box.querySelector(".compare-mark").textContent = isNaN(n) ? "" : (n === total ? "✅" : "⚠️");
      });
    });

    // phones: wide tables (4+ columns) become label/value cards; each cell gets its column name
    root.querySelectorAll("table:not(.cart-items):not(.stack-table)").forEach(function (table) {
      if (!table.closest("main")) return;
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
    if (root.querySelector(".chat-pane") || root.closest && root.closest(".chat-pane")) toBottom();
  });

  function toBottom() { document.querySelectorAll(".chat-pane").forEach(function (el) { el.scrollTop = el.scrollHeight; }); }

  // <form data-confirm="..."> or <button data-confirm="..."> -> Bootstrap modal instead of posting at once
  var pending = null;
  document.addEventListener("submit", function (e) {
    var form = e.target, by = e.submitter, modalEl = document.getElementById("confirm");
    var text = (by && by.dataset.confirm) || form.dataset.confirm;
    if (!text || form.dataset.confirmed || !modalEl || !window.bootstrap) return;
    e.preventDefault();
    e.stopImmediatePropagation();  // htmx (boosted forms) must not post either
    pending = [form, by];
    document.getElementById("confirm-text").textContent = text;
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }, true);
  document.addEventListener("click", function (e) {
    if (!pending || !e.target.closest("#confirm-yes")) return;
    var form = pending[0], by = pending[1];
    pending = null;
    form.dataset.confirmed = "1";
    window.bootstrap.Modal.getOrCreateInstance(document.getElementById("confirm")).hide();
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

  if (!htmx) return;

  // ---- docs/SPEC-v5.3 M2: page changes swap the body; the <body class> must follow the new page
  function bodyClass(html) {
    var m = /<body[^>]*\sclass="([^"]*)"/.exec(html);
    if (m) document.body.className = m[1];
  }
  document.addEventListener("htmx:beforeSwap", function (e) {
    if (e.detail.target === document.body && e.detail.xhr) bodyClass(e.detail.xhr.responseText);
  });
  document.addEventListener("htmx:afterSettle", function (e) { if (e.detail && e.detail.boosted) toBottom(); });

  // ---- M2 prefetch: hovering a menu link or a chat row loads that page in the background (GET links only,
  // kept in this page's memory for 10 s and used once; never stored by the browser: pages are no-store)
  var PREFETCH = "nav.sidebar a.side-item[href^='/'], nav.sidebar .more-list a[href^='/'], a.chatrow[href^='/']";
  var cache = {}, timer = null;
  function prefetch(a) {
    var url = a.getAttribute("href"), hit = cache[url];
    if (hit && Date.now() - hit.at < 10000) return;
    if (url === location.pathname + location.search) return;
    cache[url] = {at: Date.now(), html: fetch(url, {credentials: "same-origin", headers: {
      "HX-Request": "true", "HX-Boosted": "true", "HX-Current-URL": location.href}})
      .then(function (r) { return r.ok && !r.redirected && !r.headers.get("HX-Redirect") ? r.text() : null; })
      .catch(function () { return null; })};
  }
  function warm(e) {
    var a = e.target.closest && e.target.closest(PREFETCH);
    clearTimeout(timer);
    if (a) timer = setTimeout(function () { prefetch(a); }, 60);  // a real hover, not the mouse passing by
  }
  document.addEventListener("mouseover", warm);
  document.addEventListener("focusin", warm);
  document.addEventListener("htmx:confirm", function (e) {
    var d = e.detail, hit = d.verb === "get" && cache[d.path];
    if (!hit || hit.used || Date.now() - hit.at > 10000) return;
    hit.used = true;  // once only; the entry stays so the click's focus does not fetch it again
    e.preventDefault();
    hit.html.then(function (html) {
      if (html === null) return d.issueRequest(true);
      var box = d.elt.closest("[hx-target]"), body = !box || d.target === document.body;
      if (body) bodyClass(html);
      htmx.swap(d.target, html, {swapStyle: body ? "innerHTML" : (box.getAttribute("hx-swap") || "innerHTML")},
                {select: body ? undefined : box.getAttribute("hx-select"), eventInfo: {boosted: true, elt: d.elt}});
      history.pushState({htmx: true}, "", d.path);
      if (body) window.scrollTo(0, 0);
    });
  });

  // ---- M2 optimistic send: the bubble shows at once as "sending…"; the swapped-in page replaces it with the
  // real outbox row. Error -> red bubble with "Try again" (same idempotency key: never sent twice)
  document.addEventListener("htmx:beforeRequest", function (e) {
    var form = e.detail.elt, thread = document.getElementById("thread");
    if (!form.matches || !form.matches("form.compose-box") || !thread) return;
    var text = (form.querySelector("textarea[name=text]") || {}).value || "";
    if (!text.trim()) return;
    var b = document.createElement("div");
    b.className = "bubble out pending optimistic";
    b.innerHTML = '<p class="text"></p><div class="bubble-meta"></div>';
    b.firstChild.textContent = text.trim();
    b.lastChild.textContent = document.body.dataset.sending || "sending…";
    thread.insertBefore(b, document.getElementById("bottom"));
    toBottom();
    form._bubble = b;
  });
  document.addEventListener("htmx:afterRequest", function (e) {
    var form = e.detail.elt, b = form && form._bubble;
    if (!b) return;
    form._bubble = null;
    if (e.detail.successful) return;
    b.classList.add("status-failed");
    b.lastChild.textContent = "";
    var err = document.createElement("span"), retry = document.createElement("button");
    err.className = "error";
    err.textContent = "✖ " + (document.body.dataset.notSent || "not sent") + " · ";
    retry.type = "button";
    retry.className = "link";
    retry.textContent = document.body.dataset.tryAgain || "Try again";
    retry.addEventListener("click", function () { b.remove(); form.requestSubmit(); });
    b.lastChild.appendChild(err);
    b.lastChild.appendChild(retry);
  });

  // ---- M3 live updates: the server says what changed; only that part is fetched again. While connected the
  // thread's own 4 s polling pauses (window.decantLive); if the connection drops, polling takes over again.
  var source = null;
  function live() {
    var ws = document.getElementById("ws");
    var cid = ws && ws.dataset.customer;
    var url = "/events" + (cid ? "?customer=" + cid : "");
    if (source && source.url.endsWith(url)) return;
    if (source) source.close();
    if (!window.EventSource || !document.body.classList.contains("signed-in")) return;
    source = new EventSource(url);
    source.onopen = function () { window.decantLive = true; };
    source.onerror = function () { window.decantLive = false; };
    source.addEventListener("thread", function () {
      if (!document.getElementById("thread") || !cid) return;
      fetch("/chats/" + cid + "/thread", {credentials: "same-origin", headers: {"HX-Request": "true"}})
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) {
          var thread = document.getElementById("thread"), pane = thread && thread.closest(".chat-pane");
          if (!html || !thread) return;
          var atEnd = !pane || pane.scrollHeight - pane.scrollTop - pane.clientHeight < 80;
          htmx.swap(thread, html, {swapStyle: "outerHTML"});
          if (atEnd) toBottom();  // keep the reading position when the admin scrolled up
        });
    });
    source.addEventListener("list", function () {
      if (document.querySelector(".chatlist") && !document.querySelector(".chatlist :focus"))
        htmx.ajax("GET", location.pathname + location.search, {target: ".chatlist", select: ".chatlist", swap: "outerHTML"});
    });
    source.addEventListener("counts", function (e) {
      var n = JSON.parse(e.data).needs;
      document.querySelectorAll("nav.sidebar a[href='/chats'] .side-count").forEach(function (el) {
        el.textContent = n;
        el.hidden = !n;
      });
    });
  }
  onLoad(function () { setTimeout(live, 0); });
  // while the stream is connected the thread's own 4 s polling is not needed (CSP: no hx-trigger filters)
  document.addEventListener("htmx:beforeRequest", function (e) {
    var t = e.detail.requestConfig && e.detail.requestConfig.triggeringEvent;
    if (window.decantLive && e.detail.elt.id === "thread" && (!t || t.type !== "click")) e.preventDefault();
  });
  window.addEventListener("pagehide", function () { if (source) source.close(); });

  // ---- M6 keyboard (PC): ↑/↓ or J/K next / previous chat, Enter = send the suggested reply shown in the
  // composer, Ctrl+Enter = send what you typed, Esc = close a panel, / = search, ? = this help
  function typing(el) { return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)); }
  document.addEventListener("keydown", function (e) {
    var el = document.activeElement, box = document.querySelector("form.compose-box textarea[name=text]");
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && el && el.matches("form.compose-box textarea")) {
      e.preventDefault();
      if (el.value.trim()) el.form.requestSubmit();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || typing(el) || document.querySelector(".modal.show")) {
      if (e.key === "Escape" && typing(el)) el.blur();
      return;
    }
    if (e.key === "/" ) {
      var search = document.querySelector(".chatlist input[type=search], main input[type=search]");
      if (search) { e.preventDefault(); search.focus(); }
    } else if (e.key === "?") {
      var help = document.getElementById("keys");
      if (help && window.bootstrap) window.bootstrap.Modal.getOrCreateInstance(help).show();
    } else if (e.key === "Escape") {
      var open = document.querySelectorAll("details[open]");
      // docs/SPEC-v5.6: Esc closes the Products dialog, then the side panel
      var close = document.querySelector(".dialog [data-close]") || document.querySelector("#panel [data-close]");
      if (open.length) open.forEach(function (d) { d.open = false; });
      else if (close) close.click();
    } else if (/^(ArrowDown|ArrowUp|j|k)$/.test(e.key)) {
      var rows = Array.prototype.slice.call(document.querySelectorAll("a.chatrow"));
      if (!rows.length) return;
      var at = rows.findIndex(function (a) { return a.getAttribute("aria-current") === "page"; });
      var next = rows[(e.key === "ArrowDown" || e.key === "j") ? Math.min(at + 1, rows.length - 1) : Math.max(at - 1, 0)];
      if (next && next.getAttribute("aria-current") !== "page") {
        e.preventDefault();
        prefetch(next);
        next.click();
        next.focus({preventScroll: false});
      }
    } else if (e.key === "Enter" && box && box.value.trim() && box.value === box.defaultValue
               && (!el || el === document.body)) {
      e.preventDefault();  // the server's suggested reply, unchanged
      box.form.requestSubmit();
    }
  });
})();

// docs/SPEC-v5.4-ui-ux-cleanup.md X3: warn before leaving Settings with changes that are not saved
(() => {
  const box = document.querySelector('.set-layout[data-unsaved]');
  if (!box) return;
  let dirty = false;
  box.addEventListener('input', () => { dirty = true; });
  box.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('click', e => {  // boosted menu links do not fire beforeunload
    const a = e.target.closest('a[href]');
    if (dirty && a && !a.closest('form') && !confirm(box.dataset.unsaved)) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
})();

// docs/SPEC-v5.6-simple-products-page.md: the panel's tabs switch at once (the links still work without JS);
// the More ▾ menu closes on a click outside it
document.addEventListener('click', e => {
  const tab = e.target.closest('#panel .panel-tabs a[data-tab]');
  if (tab && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    const panel = tab.closest('#panel');
    panel.querySelectorAll('.panel-tabs a').forEach(a => a.toggleAttribute('aria-current', a === tab));
    panel.querySelectorAll('.pane').forEach(p => { p.hidden = p.id !== 'pane-' + tab.dataset.tab; });
    if (panel.querySelectorAll('.panel-tabs a[aria-current]').length) panel.querySelector('.panel-tabs a[aria-current]').setAttribute('aria-current', 'page');
    history.replaceState(history.state, '', tab.href);
  }
  document.querySelectorAll('details.more-menu[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; });
});
