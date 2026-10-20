import { request } from './api.js';
document.querySelectorAll('[data-rule-status]').forEach((button) =>
  button.addEventListener('click', async () => {
    const result = await request(button.dataset.ruleStatus, { method: 'PUT' });
    if (!result) return;
    const badge = button.closest('[data-rule-row]').querySelector('[data-rule-badge]');
    badge.textContent = result.status;
    badge.className = `badge text-bg-${result.status === 'Enabled' ? 'success' : 'secondary'}`;
    button.textContent =
      result.status === 'Draft'
        ? 'Approve'
        : result.status === 'Disabled'
          ? 'Enable'
          : 'Disable';
  }),
);
