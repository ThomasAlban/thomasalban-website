(() => {
  'use strict';

  const viewer = document.querySelector('#score-viewer');
  if (!viewer || typeof viewer.showModal !== 'function') return;

  const image = viewer.querySelector('.score-viewer-image');
  const viewport = viewer.querySelector('.score-viewer-viewport');
  const zoomIn = viewer.querySelector('[data-zoom-in]');
  const zoomOut = viewer.querySelector('[data-zoom-out]');
  const status = viewer.querySelector('[data-zoom-status]');
  const previous = viewer.querySelector('[data-preview-previous]');
  const next = viewer.querySelector('[data-preview-next]');
  const previewStatus = viewer.querySelector('[data-preview-status]');
  const close = viewer.querySelector('[data-viewer-close]');
  const previews = Array.from(document.querySelectorAll('[data-score-preview]'));
  let currentIndex = 0;
  let trigger;
  let zoom = 1;

  const render = () => {
    if (!image.naturalWidth || !image.naturalHeight) return;
    const fittedWidth = Math.min(
      viewport.clientWidth,
      viewport.clientHeight * image.naturalWidth / image.naturalHeight,
      image.naturalWidth,
    );
    image.style.width = `${Math.max(1, fittedWidth * zoom)}px`;
    status.textContent = `${Math.round(zoom * 100)}%`;
    zoomOut.disabled = zoom <= 1;
    zoomIn.disabled = zoom >= 4;
  };
  const reset = () => {
    zoom = 1;
    render();
    viewport.scrollTo(0, 0);
  };

  const showPreview = (index) => {
    if (index < 0 || index >= previews.length) return;
    currentIndex = index;
    const link = previews[index];
    image.alt = link.querySelector('img').alt;
    image.removeAttribute('style');
    image.src = link.href;
    previous.disabled = index === 0;
    next.disabled = index === previews.length - 1;
    previewStatus.textContent = `Preview ${index + 1} of ${previews.length}`;
    // Move focus to an available control when the button just used becomes disabled.
    if (document.activeElement === previous && previous.disabled) {
      (next.disabled ? close : next).focus();
    } else if (document.activeElement === next && next.disabled) {
      (previous.disabled ? close : previous).focus();
    }
    reset();
  };

  previews.forEach((link, index) => {
    link.addEventListener('click', (event) => {
      // Preserve opening the original in a new tab with modifier keys.
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      trigger = link;
      viewer.showModal();
      document.body.classList.add('score-viewer-open');
      showPreview(index);
    });
  });
  previous.addEventListener('click', () => showPreview(currentIndex - 1));
  next.addEventListener('click', () => showPreview(currentIndex + 1));
  image.addEventListener('load', reset);
  zoomIn.addEventListener('click', () => {
    zoom = Math.min(4, zoom + .5);
    render();
  });
  zoomOut.addEventListener('click', () => {
    zoom = Math.max(1, zoom - .5);
    render();
  });
  viewer.querySelector('[data-zoom-reset]').addEventListener('click', reset);
  close.addEventListener('click', () => viewer.close());
  viewer.addEventListener('close', () => {
    document.body.classList.remove('score-viewer-open');
    if (trigger) trigger.focus();
  });
  window.addEventListener('resize', () => {
    if (viewer.open) render();
  });
})();
