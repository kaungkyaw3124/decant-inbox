// docs/SPEC-v5.0 G4: the Print button (and the print dialog once the slips are shown)
document.getElementById("print").addEventListener("click", function () { window.print(); });
if (document.querySelector(".slip")) window.addEventListener("load", function () { setTimeout(window.print, 300); });
