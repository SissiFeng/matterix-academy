// Apply the saved theme before first paint (external file: CSP forbids inline scripts).
(function () {
  try {
    var theme = localStorage.getItem("lab.theme");
    if (theme === "light" || theme === "dark")
      document.documentElement.dataset.theme = theme;
  } catch (e) {}
})();
