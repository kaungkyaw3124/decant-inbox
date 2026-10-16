// Countdown for one-tap replies: "Sending in N s", then hide Undo when time is up.
// The words come from <body data-sending-in="… {n} …" data-sending="…"> (dashboard language).
(function () {
  var body = document.body.dataset;
  function tick() {
    document.querySelectorAll("[data-send-at]").forEach(function (el) {
      var left = Math.ceil((Date.parse(el.dataset.sendAt) - Date.now()) / 1000);
      if (left > 0) {
        el.textContent = (body.sendingIn || "Sending in {n} s").replace("{n}", left);
      } else {
        el.textContent = body.sending || "💬 sending…";
        el.removeAttribute("data-send-at");
        var undo = el.parentElement.querySelector("[data-undo]");
        if (undo) undo.remove();
      }
    });
  }
  setInterval(tick, 1000);
})();
