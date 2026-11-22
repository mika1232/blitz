(() => {
  'use strict';

  // "Generate" / "New" buttons fill a password field with a fresh, unused one.
  document.querySelectorAll('[data-generate]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const input = document.querySelector(btn.dataset.target);
      if (!input) return;
      btn.disabled = true;
      try {
        const res = await fetch(btn.dataset.url, { headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error('request failed');
        const data = await res.json();
        input.value = data.password;
        input.focus();
      } catch (_) {
        window.alert("Couldn't generate a password. Please refresh and try again.");
      } finally {
        btn.disabled = false;
      }
    });
  });
})();
