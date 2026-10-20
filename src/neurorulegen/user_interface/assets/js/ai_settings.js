import { request } from './api.js';
document.querySelectorAll('[data-toggle-skill]').forEach((button) =>
  button.addEventListener('click', async () => {
    const result = await request(button.dataset.toggleSkill, { method: 'PUT' });
    if (!result) return;
    const badge = button.closest('[data-skill-row]').querySelector('[data-skill-badge]');
    badge.textContent = result.enabled ? 'Enabled' : 'Disabled';
    badge.className = `badge text-bg-${result.enabled ? 'success' : 'secondary'}`;
    button.textContent = result.enabled ? 'Disable' : 'Enable';
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
