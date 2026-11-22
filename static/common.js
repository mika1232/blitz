(() => {
  'use strict';

  // Show timestamps in the visitor's own timezone.
  document.querySelectorAll('time[datetime]').forEach((t) => {
    const d = new Date(t.getAttribute('datetime'));
    if (!isNaN(d)) {
      t.textContent = d.toLocaleString([], {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      });
    }
  });

  // Show / hide password fields.
  document.querySelectorAll('[data-reveal]').forEach((btn) => {
    const input = document.querySelector(btn.dataset.reveal);
    if (!input) return;
    btn.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Hide' : 'Show';
    });
  });

  // Confirm destructive actions.
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  document.querySelectorAll('[data-print]').forEach((b) =>
    b.addEventListener('click', () => window.print()));

  // Fade flash messages out after a few seconds.
  document.querySelectorAll('.flash').forEach((f) => {
    setTimeout(() => {
      f.classList.add('leaving');
      setTimeout(() => f.remove(), 400);
    }, 6000);
  });
})();
