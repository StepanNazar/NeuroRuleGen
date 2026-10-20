import { request } from './api.js';
document.querySelectorAll('[data-rule-status]').forEach((button) =>
  button.addEventListener('click', async () => {
    if (await request(button.dataset.ruleStatus, { method: 'PUT' })) location.reload();
  }),
);
