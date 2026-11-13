document.querySelectorAll('[data-password-toggle]').forEach((button) => {
  const input = document.getElementById(button.getAttribute('aria-controls'));
  if (!input || input.type !== 'password') return;
  const setVisible = (visible) => {
    input.type = visible ? 'text' : 'password';
    button.dataset.visible = String(visible);
    const label = visible ? 'Скрыть пароль' : 'Показать пароль';
    button.setAttribute('aria-label', label);
    button.title = label;
  };
  button.hidden = false;
  button.addEventListener('click', () => setVisible(input.type === 'password'));
  input.form?.addEventListener('submit', () => setVisible(false));
  window.addEventListener('pagehide', () => setVisible(false));
  window.addEventListener('pageshow', () => setVisible(false));
});

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
  const retry = form.querySelector('[data-draft-retry]');
  status.textContent += ' Изменения сохраняются автоматически.';
  let timer;
  let inFlight = null;
  let revision = 0;
  let savedRevision = 0;
  let leaving = false;
  let conflicted = false;

  const save = () => {
    if (leaving || conflicted || inFlight || revision === savedRevision) return;
    const snapshot = revision;
    if (retry) retry.hidden = true;
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
      if (!response.ok) {
        if (result.conflict_url) {
          conflicted = true;
          const link = document.createElement('a');
          link.href = result.conflict_url;
          link.target = '_blank';
          link.rel = 'noopener';
          link.className = 'text-link';
          link.textContent = 'Открыть актуальный черновик в новой вкладке';
          status.after(link);
        }
        throw new Error(result.error || 'Не удалось сохранить черновик.');
      }
      form.elements.draft_version.value = result.draft_version;
      savedRevision = snapshot;
      const time = new Date(result.updated_at).toLocaleTimeString('ru-RU', {
        hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow',
      });
      status.textContent = `Черновик сохранён · ${time} по Москве`;
    }).catch((error) => {
      const message = error instanceof TypeError ? 'Не удалось сохранить черновик. Проверь соединение.' : error.message;
      status.textContent = message + (conflicted ? '' : ' Текст остаётся в форме. Можно сохранить кнопкой ниже.');
      status.classList.add('is-error');
      if (retry) retry.hidden = conflicted;
    }).finally(() => {
      inFlight = null;
      if (!leaving && revision !== snapshot) timer = setTimeout(save, 500);
    });
  };

  retry?.addEventListener('click', () => { clearTimeout(timer); save(); });

  form.addEventListener('input', (event) => {
    if (!['kind', 'destination', 'text'].includes(event.target.name)) return;
    revision += 1;
    if (!conflicted) status.textContent = 'Есть несохранённые изменения…';
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

document.querySelectorAll('[data-view-memory]').forEach((form) => {
  const button = form.querySelector('[data-memory-retry]');
  const status = form.querySelector('[data-memory-status]');
  let pending = false;
  const remember = async () => {
    if (pending) return;
    pending = true;
    button.hidden = true;
    status.textContent = '';
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), credentials: 'same-origin', keepalive: true,
        headers: {Accept: 'application/json'},
      });
      if (response.redirected || !response.ok || !response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('not saved');
      }
      const result = await response.json();
      if (!result.saved) throw new Error('not saved');
      status.textContent = 'Вид сохранён';
    } catch {
      status.textContent = 'Не удалось запомнить вид. Выбранные фильтры продолжают работать.';
      button.textContent = 'Повторить сохранение вида';
      button.hidden = false;
    } finally {
      pending = false;
    }
  };
  form.addEventListener('submit', (event) => { event.preventDefault(); remember(); });
  remember();
});

// Only numeric scroll positions are stored in this tab, separately per account.
const viewer = document.body.dataset.viewer;
const list = document.querySelector('[data-list-state]');
let clearingPosition = false;
if (viewer && list) {
  const key = `student-position:${viewer}:${list.dataset.listState}`;
  const savePosition = () => {
    if (clearingPosition) return;
    try { sessionStorage.setItem(key, String(window.scrollY)); } catch { /* Storage is optional. */ }
  };
  const restorePosition = () => {
    const navigation = performance.getEntriesByType('navigation')[0];
    if (navigation?.type !== 'back_forward' && new URLSearchParams(location.search).get('restore') !== '1') return;
    try {
      const stored = sessionStorage.getItem(key);
      const offset = Number(stored);
      if (stored !== null && Number.isFinite(offset) && offset >= 0) {
        requestAnimationFrame(() => window.scrollTo(0, offset));
      }
    } catch { /* The browser still provides ordinary navigation. */ }
  };
  window.addEventListener('pagehide', savePosition);
  window.addEventListener('pageshow', restorePosition);
}
document.querySelectorAll('[data-clear-ui]').forEach((form) => {
  form.addEventListener('submit', () => {
    clearingPosition = true;
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith(`student-position:${viewer}:`)) sessionStorage.removeItem(key);
      }
    } catch { /* No personal content is kept here. */ }
  });
});
