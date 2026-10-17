(() => {
  const form = document.querySelector('.filter-form');
  if (!form) return;

  const scrollKey = 'catalogue-scroll';
  const rememberScroll = (url) => {
    try {
      sessionStorage.setItem(scrollKey, JSON.stringify({
        path: url.pathname,
        query: url.searchParams.toString(),
        x: window.scrollX,
        y: window.scrollY,
      }));
    } catch {
      // Filtering still works when browser storage is unavailable.
    }
  };

  form.addEventListener('submit', () => {
    const url = new URL(form.action);
    url.search = new URLSearchParams(new FormData(form)).toString();
    rememberScroll(url);
  });

  form.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', (event) => {
      if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
        rememberScroll(new URL(link.href));
      }
    });
  });

  window.addEventListener('pageshow', () => {
    try {
      const stored = sessionStorage.getItem(scrollKey);
      sessionStorage.removeItem(scrollKey);
      if (!stored) return;
      const position = JSON.parse(stored);
      const url = new URL(window.location.href);
      if (position.path === url.pathname && position.query === url.searchParams.toString()
          && Number.isFinite(position.x) && Number.isFinite(position.y)) {
        window.scrollTo({ left: position.x, top: position.y, behavior: 'instant' });
      }
    } catch {
      // Use the browser's default scroll behaviour if storage is unavailable.
    }
  }, { once: true });

  const years = form.querySelector('.year-dropdown');
  if (!years) return;

  years.addEventListener('change', () => {
    const count = years.querySelectorAll('input:checked').length;
    years.querySelector('#year-filter-summary').textContent = count ? `${count} selected` : 'Any year';
  });

  document.addEventListener('click', (event) => {
    if (!years.contains(event.target)) years.open = false;
  });

  years.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && years.open) {
      years.open = false;
      years.querySelector('summary').focus();
    }
  });
})();
