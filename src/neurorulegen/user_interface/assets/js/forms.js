import { Options, ZxcvbnFactory } from '@zxcvbn-ts/core'
import * as zxcvbnCommonPackage from '@zxcvbn-ts/language-common'
import * as zxcvbnEnPackage from '@zxcvbn-ts/language-en'

const options = new Options({
  translations: zxcvbnEnPackage.translations,
  graphs: zxcvbnCommonPackage.adjacencyGraphs,
  dictionary: {
    ...zxcvbnCommonPackage.dictionary,
    ...zxcvbnEnPackage.dictionary,
  },
  useLevenshteinDistance: true,
});
const zxcvbnMatcher = new ZxcvbnFactory(options);

const password = document.getElementById('password');
const confirmation = document.getElementById('password-confirmation');
const helpText = document.getElementById('password-help');
const defaultHelpText =
  helpText?.textContent ||
  'Use at least 8 characters, with uppercase, lowercase, a number and a special character.';

function validatePassword() {
  if (!password) return;

  if (confirmation) {
    confirmation.setCustomValidity(
      password.value === confirmation.value ? '' : 'Passwords must match.',
    );
  }

  const strength = document.getElementById('password-strength');
  if (!password.value) {
    if (strength) strength.value = 0;
    if (helpText) helpText.textContent = defaultHelpText;
    password.setCustomValidity('');
    return;
  }

  const hasLength = password.value.length >= 8;
  const hasLower = /[a-z]/.test(password.value);
  const hasUpper = /[A-Z]/.test(password.value);
  const hasDigit = /[0-9]/.test(password.value);
  const hasSpecial = /[^A-Za-z0-9]/.test(password.value);

  const policyPassed = hasLength && hasLower && hasUpper && hasDigit && hasSpecial;

  // Use zxcvbn to evaluate password strength (score 0-4) and detect common/weak patterns
  const result = zxcvbnMatcher.check(password.value);
  if (strength) {
    strength.value = policyPassed ? Math.max(1, result.score + 1) : Math.min(2, result.score);
  }

  if (helpText) {
    if (result.score <= 1) {
      helpText.textContent = 'Password is weak or commonly used. Choose a stronger password.';
    } else {
      helpText.textContent = defaultHelpText;
    }
  }

  if (!policyPassed) {
    password.setCustomValidity('Password must meet complexity requirements.');
  } else if (result.score === 0) {
    password.setCustomValidity('Password is too common or weak.');
  } else {
    password.setCustomValidity('');
  }
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
