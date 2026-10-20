import { request } from './api.js';
document.getElementById('refresh-runs')?.addEventListener('click', async (event) => {
  const result = await request(event.currentTarget.dataset.url);
  if (!result) return;
  // Keep each independently paginated list in place; change only visible statuses.
  document.querySelectorAll('[data-run-id]').forEach((badge) => {
    const run = result[badge.dataset.runKind]?.find(
      (row) => row.id === Number(badge.dataset.runId),
    );
    if (run) {
      badge.textContent = run.status;
      badge.className = `badge text-bg-${run.status === 'Completed' ? 'success' : run.status === 'Failed' ? 'danger' : 'warning'}`;
    }
  });
});
