import { request } from './api.js';
document.querySelectorAll('[data-toggle-skill]').forEach((button) =>
  button.addEventListener('click', async () => {
    if (await request(button.dataset.toggleSkill, { method: 'PUT' })) location.reload();
  }),
);
document.getElementById('mcp')?.addEventListener('input', (event) => {
  try {
    JSON.parse(event.target.value);
    event.target.setCustomValidity('');
  } catch {
    event.target.setCustomValidity('Enter valid JSON for the MCP configuration.');
  }
});
