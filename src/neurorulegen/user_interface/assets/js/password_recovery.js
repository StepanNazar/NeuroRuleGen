import './forms.js';
import { request } from './api.js';
document.getElementById('request-code')?.addEventListener('click', async () => {
  const email = document.getElementById('email');
  if (email.reportValidity())
    await request('/api/password-recovery/code', {
      method: 'POST',
      body: JSON.stringify({ email: email.value }),
    });
});
