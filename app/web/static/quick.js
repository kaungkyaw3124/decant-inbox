// Countdown for one-tap replies: "Sending in N s", then hide Undo when time is up.
(function () {
  function tick() {
    document.querySelectorAll("[data-send-at]").forEach(function (el) {
      var left = Math.ceil((Date.parse(el.dataset.sendAt) - Date.now()) / 1000);
      if (left > 0) {
        el.textContent = "Sending in " + left + " s";
      } else {
        el.textContent = "💬 sending…";
        el.removeAttribute("data-send-at");
        var undo = el.parentElement.querySelector("[data-undo]");
        if (undo) undo.remove();
      }
    });
  }
  setInterval(tick, 1000);
})();
