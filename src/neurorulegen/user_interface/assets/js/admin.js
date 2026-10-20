import { request } from './api.js';
document.querySelectorAll('[data-block-url]').forEach((button) =>
  button.addEventListener('click', async () => {
    const result = await request(button.dataset.blockUrl, {
      method: button.dataset.blocked === '1' ? 'DELETE' : 'POST',
    });
    if (result) location.reload();
  }),
);
document.getElementById('attempt-details')?.addEventListener('show.bs.modal', (event) => {
  const button = event.relatedTarget;
  document.getElementById('attempt-summary').textContent =
    `${button.dataset.email} · ${button.dataset.count} failed attempts over the last 7 days`;
});
