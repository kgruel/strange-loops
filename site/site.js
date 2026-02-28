(() => {
  const THEME_KEY = "painted-theme";

  const root = document.documentElement;
  const themeToggle = document.getElementById("theme-toggle");

  const systemTheme = () =>
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";

  const readSavedTheme = () => {
    const raw = localStorage.getItem(THEME_KEY);
    return raw === "light" || raw === "dark" ? raw : null;
  };

  const applyTheme = (theme) => {
    if (theme === "light" || theme === "dark") root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");

    if (themeToggle) {
      const effective = theme ?? systemTheme();
      themeToggle.textContent = effective === "dark" ? "Dark" : "Light";
      themeToggle.setAttribute("aria-pressed", effective === "dark" ? "true" : "false");
    }
  };

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const next = (readSavedTheme() ?? systemTheme()) === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
    });
  }

  applyTheme(readSavedTheme());
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (!readSavedTheme()) applyTheme(null);
  });

  for (const code of document.querySelectorAll("pre > code")) {
    const pre = code.parentElement;
    if (!pre || pre.querySelector(".code-copy")) continue;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "code-copy";
    button.textContent = "Copy";
    button.addEventListener("click", async () => {
      const text = code.textContent ?? "";
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      button.textContent = "Copied";
      window.setTimeout(() => (button.textContent = "Copy"), 900);
    });
    pre.appendChild(button);
  }
})();

