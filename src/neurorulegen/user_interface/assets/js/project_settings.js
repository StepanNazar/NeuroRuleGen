import { request } from './api.js';
document.getElementById('rename-project')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const result = await request(form.dataset.url, {
    method: 'PUT',
    body: JSON.stringify(Object.fromEntries(new FormData(form))),
  });
  if (!result) return;
  form.elements.name.value = result.name;
  document.querySelectorAll('[data-project-name]').forEach((element) => {
    element.textContent = result.name;
  });
});
