(() => {
  'use strict';

  const header = document.querySelector('.site-header');
  const toggle = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('#main-navigation');
  if (!header || !toggle || !navigation) return;

  const mobile = window.matchMedia('(max-width: 48rem)');
  const close = () => toggle.setAttribute('aria-expanded', 'false');

  toggle.addEventListener('click', () => {
    header.classList.add('navigation-interacted');
    toggle.setAttribute('aria-expanded', String(toggle.getAttribute('aria-expanded') !== 'true'));
  });
  header.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobile.matches && toggle.getAttribute('aria-expanded') === 'true') {
      close();
      toggle.focus();
    }
  });
  mobile.addEventListener('change', () => {
    // Do not leave keyboard focus in a menu that becomes hidden on resize.
    if (mobile.matches && navigation.contains(document.activeElement)) toggle.focus();
    if (!mobile.matches && document.activeElement === toggle) navigation.querySelector('a').focus();
    close();
  });

  toggle.hidden = false;
  header.classList.add('navigation-ready');
})();
