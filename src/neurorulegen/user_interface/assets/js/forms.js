const password = document.getElementById('password');
const confirmation = document.getElementById('password-confirmation');
function validatePassword() {
  if (!password || !confirmation) return;
  confirmation.setCustomValidity(
    password.value === confirmation.value ? '' : 'Passwords must match.',
  );
  const strength = document.getElementById('password-strength');
  strength.value = [
    password.value.length >= 8,
    /[a-z]/.test(password.value),
    /[A-Z]/.test(password.value),
    /[0-9]/.test(password.value),
    /[^A-Za-z0-9]/.test(password.value),
  ].filter(Boolean).length;
}
password?.addEventListener('input', validatePassword);
confirmation?.addEventListener('input', validatePassword);

const provider = document.getElementById('provider');
const model = document.getElementById('model');
provider?.addEventListener('change', () => {
  const option = document.createElement('option');
  option.value = option.textContent = provider.value === 'anthropic' ? 'claude-sonnet' : 'gpt-5';
  model.replaceChildren(option);
});
const mode = document.getElementById('mode');
function updateMode() {
  const iterative = mode.value !== 'Simple';
  document.getElementById('iteration-field').hidden = !iterative;
  document.getElementById('iterations').disabled = !iterative;
}
mode?.addEventListener('change', updateMode);
if (mode) updateMode();

const usage = document.getElementById('usage-filters');
if (usage) {
  const start = document.getElementById('start'),
    end = document.getElementById('end');
  function updatePeriod() {
    const hasPeriod = Boolean(
      start.value && end.value && start.validity.valid && end.value >= start.value,
    );
    document.getElementById('group-field').hidden = !hasPeriod;
    document.getElementById('group').disabled = !hasPeriod;
    end.min = start.value;
    end.setCustomValidity(
      start.value && end.value && start.value > end.value
        ? 'The end date must be on or after the start date.'
        : '',
    );
  }
  start.addEventListener('change', updatePeriod);
  end.addEventListener('change', updatePeriod);
  updatePeriod();
}
