import './forms.js';
import { request } from './api.js';
document
  .getElementById('resend-activation')
  ?.addEventListener('click', () => request('/api/profile/activation-email', { method: 'POST' }));
document.getElementById('disable-totp')?.addEventListener('click', async () => {
  if (await request('/api/profile/totp', { method: 'DELETE' })) location.reload();
});
