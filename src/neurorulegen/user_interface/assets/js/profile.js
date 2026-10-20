import './forms.js';
import { request } from './api.js';
document
  .getElementById('resend-activation')
  ?.addEventListener('click', () => request('/api/profile/activation-email', { method: 'POST' }));
document.getElementById('disable-totp')?.addEventListener('click', async () => {
  const result = await request('/api/profile/totp', { method: 'DELETE' });
  if (!result || result.enabled) return;
  document.getElementById('totp-status').textContent = 'Disabled';
  const link = document.createElement('a');
  link.className = 'btn btn-secondary';
  link.href = '/totp/setup';
  link.textContent = 'Set up TOTP';
  document.getElementById('disable-totp').replaceWith(link);
});
