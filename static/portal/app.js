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

document.querySelectorAll('[data-draft-form]').forEach((form) => {
  const status = form.querySelector('[data-draft-status]');
  status.textContent += ' Изменения сохраняются автоматически.';
  let timer;
  let inFlight = null;
  let revision = 0;
  let savedRevision = 0;
  let leaving = false;

  const save = () => {
    if (leaving || inFlight || revision === savedRevision) return;
    const snapshot = revision;
    status.textContent = 'Сохраняем черновик…';
    status.classList.remove('is-error');
    inFlight = fetch(form.dataset.draftUrl, {
      method: 'POST', body: new FormData(form), credentials: 'same-origin',
      headers: {Accept: 'application/json'},
    }).then(async (response) => {
      if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Сохранение недоступно. Проверь соединение и вход в аккаунт.');
      }
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Не удалось сохранить черновик.');
      savedRevision = snapshot;
      const time = new Date(result.updated_at).toLocaleTimeString('ru-RU', {
        hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow',
      });
      status.textContent = `Черновик сохранён · ${time} по Москве`;
    }).catch((error) => {
      const message = error instanceof TypeError ? 'Не удалось сохранить черновик. Проверь соединение.' : error.message;
      status.textContent = message + ' Текст остаётся в форме. Можно сохранить кнопкой ниже.';
      status.classList.add('is-error');
    }).finally(() => {
      inFlight = null;
      if (!leaving && revision !== snapshot) timer = setTimeout(save, 500);
    });
  };

  form.addEventListener('input', (event) => {
    if (!['kind', 'destination', 'text'].includes(event.target.name)) return;
    revision += 1;
    status.textContent = 'Есть несохранённые изменения…';
    clearTimeout(timer);
    timer = setTimeout(save, 700);
  });
  // Some browsers fire only change for a select controlled by touch/keyboard.
  form.querySelector('select')?.addEventListener('change', () => {
    revision += 1;
    clearTimeout(timer);
    timer = setTimeout(save, 700);
  });
  form.addEventListener('submit', (event) => {
    if (event.defaultPrevented) return;
    leaving = true;
    clearTimeout(timer);
    if (inFlight) {
      // Finish an older snapshot before the POST saves the final form values.
      event.preventDefault();
      const submitter = event.submitter;
      inFlight.finally(() => {
        delete form.dataset.submitting;
        form.requestSubmit(submitter);
      });
    }
  });
  window.addEventListener('beforeunload', (event) => {
    if (!leaving && revision !== savedRevision) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  window.addEventListener('pageshow', () => { leaving = false; });
});

// A link to a specific help topic also opens its keyboard-accessible disclosure.
const revealHelpTopic = () => {
  const topic = document.getElementById(location.hash.slice(1));
  if (topic?.matches('details.help-item')) topic.open = true;
};
revealHelpTopic();
window.addEventListener('hashchange', revealHelpTopic);
