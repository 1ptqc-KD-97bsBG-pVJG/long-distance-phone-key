const paths = {
  car: '<path d="m6 15 2-6h16l2 6M5 15h22v10H5zM9 25v3m14-3v3M9 20h2m10 0h2M10 9l1-3h10l1 3"/>',
  code: '<rect x="8" y="3" width="16" height="26" rx="4"/><path d="M13 24h6M12 11h1m6 0h1M12 16h1m6 0h1"/>',
  bluetooth: '<path d="m10 8 13 16-7 6V2l7 6-13 16"/>',
  link: '<rect x="3" y="7" width="9" height="18" rx="2"/><path d="M8 21h1m6-5h5m-3-3 3 3-3 3"/><rect x="23" y="10" width="6" height="12" rx="2"/>',
  check: '<path d="m7 16 6 6L26 9"/>',
  alert: '<path d="M16 10v8m0 5h.01"/><circle cx="16" cy="16" r="13"/>'
};
let stageKey = '', started = Date.now(), ticking;
const $ = id => document.getElementById(id);
export function show({title, detail = '', step = 0, icon = 'car', busy = false, tone = 'normal'}) {
  const key = `${title}|${detail}|${step}|${busy}|${icon}|${tone}`;
  if (key === stageKey) return;
  started = Date.now(); stageKey = key;
  $('status').textContent = title; $('detail').textContent = detail;
  document.body.dataset.tone = tone;
  $('visual').classList.toggle('busy', busy);
  $('visual').innerHTML = `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[icon] || paths.car}</svg>`;
  document.querySelectorAll('.progress li').forEach((node, i) => {
    node.dataset.state = step && i < step - 1 ? 'done' : i === step - 1 ? 'current' : 'todo';
    if (i === step - 1) node.setAttribute('aria-current', 'step'); else node.removeAttribute('aria-current');
  });
  $('step-label').textContent = step ? `Step ${step} of 4` : 'Session paused';
  const tick = () => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    $('elapsed').textContent = `Waiting · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  };
  clearInterval(ticking); $('elapsed').hidden = !busy;
  if (busy) { tick(); ticking = setInterval(tick, 1000); }
}
