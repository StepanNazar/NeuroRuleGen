import 'vite/modulepreload-polyfill';
import 'bootswatch/dist/brite/bootstrap.min.css';
import 'bootstrap/js/dist/collapse';
import Modal from 'bootstrap/js/dist/modal';
import { request } from './api.js';

// Reserve the fixed header's actual height, including an expanded mobile menu.
const header = document.getElementById('site-header');
const headerSpacer = document.getElementById('header-spacer');
const updateHeaderSpace = () => {
  headerSpacer.style.height = `${header.getBoundingClientRect().height}px`;
};
updateHeaderSpace();
new ResizeObserver(updateHeaderSpace).observe(header);

// One shared confirmation dialog; the initiating button provides the target.
let pending;
const dialog = document.getElementById('confirmation-modal');
document.querySelectorAll('[data-confirm-url]').forEach((button) => {
  button.addEventListener('click', () => {
    pending = button;
    document.getElementById('confirmation-title').textContent = button.dataset.confirmTitle;
    document.getElementById('confirmation-message').textContent = button.dataset.confirmMessage;
    Modal.getOrCreateInstance(dialog).show();
  });
});
document.getElementById('confirmation-submit')?.addEventListener('click', async () => {
  const result = await request(pending.dataset.confirmUrl, { method: 'DELETE' });
  if (!result) return;
  Modal.getOrCreateInstance(dialog).hide();
  if (result.redirect) location.assign(result.redirect);
  else pending.closest('[data-developer-row]')?.remove();
});
