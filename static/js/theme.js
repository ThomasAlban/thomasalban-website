(() => {
  'use strict';

  const root = document.documentElement;
  const storageKey = 'theme';
  let theme = 'dark';

  try {
    if (localStorage.getItem(storageKey) === 'light') theme = 'light';
  } catch {
    // Storage may be unavailable; the toggle still works for this page.
  }
  // Restore before the stylesheet loads to avoid flashing the default theme.
  root.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.querySelector('.theme-toggle');
    if (!toggle) return;

    toggle.setAttribute('aria-pressed', String(theme === 'light'));
    toggle.hidden = false;
    toggle.addEventListener('click', () => {
      toggle.classList.add('theme-interacted');
      theme = theme === 'dark' ? 'light' : 'dark';
      root.dataset.theme = theme;
      toggle.setAttribute('aria-pressed', String(theme === 'light'));
      try {
        localStorage.setItem(storageKey, theme);
      } catch {
        // Keep the selected theme even when it cannot be saved.
      }
    });
  });
})();
