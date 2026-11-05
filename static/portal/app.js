document.querySelectorAll('[data-submit-state]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (form.dataset.submitting === 'true') {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    const submitter = event.submitter;
    if (submitter && submitter.dataset.pendingText) {
      submitter.dataset.originalMarkup = submitter.innerHTML;
      submitter.textContent = submitter.dataset.pendingText;
      submitter.setAttribute('aria-disabled', 'true');
    }
    form.setAttribute('aria-busy', 'true');
  });
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('[data-submit-state]').forEach((form) => {
    delete form.dataset.submitting;
    form.removeAttribute('aria-busy');
    form.querySelectorAll('[aria-disabled]').forEach((button) => {
      button.removeAttribute('aria-disabled');
      if (button.dataset.originalMarkup) button.innerHTML = button.dataset.originalMarkup;
    });
  });
});
const errorField = document.querySelector('[aria-invalid="true"]');
if (errorField) errorField.focus();
