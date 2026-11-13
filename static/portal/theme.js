// Apply the theme before styles load, including on the login page.
(() => {
  const key = 'campus-theme';
  const root = document.documentElement;
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = null;

  const readPreference = () => {
    try {
      const value = localStorage.getItem(key);
      return ['light', 'dark'].includes(value) ? value : null;
    } catch { return null; }
  };
  const apply = () => {
    const theme = preference || (system.matches ? 'dark' : 'light');
    root.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      'content', theme === 'dark' ? '#121c20' : '#f5f6f2');
    const label = theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему';
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.setAttribute('aria-label', label);
      button.title = label;
      button.hidden = false;
    });
  };
  preference = readPreference();
  apply();

  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.addEventListener('click', () => {
        preference = root.dataset.theme === 'dark' ? 'light' : 'dark';
        try { localStorage.setItem(key, preference); } catch { /* Theme still works without storage. */ }
        apply();
      });
    });
  });
  system.addEventListener('change', () => { if (!preference) apply(); });
  window.addEventListener('storage', (event) => {
    if (event.key === key || event.key === null) {
      preference = readPreference();
      apply();
    }
  });
  window.addEventListener('pageshow', () => {
    // Re-read saved choices when returning from the back/forward cache.
    const saved = readPreference();
    if (saved) preference = saved;
    apply();
  });
})();
