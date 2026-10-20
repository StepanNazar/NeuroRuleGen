import { request } from './api.js';
document.querySelectorAll('[data-block-url]').forEach((button) =>
  button.addEventListener('click', async () => {
    const result = await request(button.dataset.blockUrl, {
      method: button.dataset.blocked === '1' ? 'DELETE' : 'POST',
    });
    if (!result) return;
    document.querySelectorAll('[data-block-url]').forEach((control) => {
      if (control.dataset.blockUrl !== button.dataset.blockUrl) return;
      control.dataset.blocked = result.blocked ? '1' : '0';
      control.textContent = result.blocked ? 'Unblock' : 'Block';
      const row = control.closest('[data-account-row]');
      const badge = row.querySelector('[data-block-badge]');
      badge.textContent = result.blocked ? 'Blocked' : 'Not blocked';
      badge.className = `badge text-bg-${result.blocked ? 'danger' : 'secondary'}`;
      if (row.hasAttribute('data-blocked-account') && !result.blocked) row.remove();
    });
  }),
);
document.getElementById('attempt-details')?.addEventListener('show.bs.modal', (event) => {
  const button = event.relatedTarget;
  document.getElementById('attempt-summary').textContent =
    `${button.dataset.email} · ${button.dataset.count} failed attempts over the last 7 days`;
});
