import { request } from './api.js';
document.getElementById('rename-project')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (
    await request(form.dataset.url, {
      method: 'PUT',
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    })
  )
    location.reload();
});
