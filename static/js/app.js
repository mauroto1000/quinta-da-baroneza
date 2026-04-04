// Quinta da Baroneza – App JS

// Prevent double-form submissions
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function () {
      const btn = this.querySelector('button[type="submit"]');
      if (btn) {
        setTimeout(() => {
          btn.disabled = true;
          btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Aguarde...';
        }, 50);
      }
    });
  });

  // Priority dropdowns: prevent selecting the same group twice
  const p1 = document.querySelector('select[name="priority_1"]');
  const p2 = document.querySelector('select[name="priority_2"]');
  const p3 = document.querySelector('select[name="priority_3"]');

  if (p1 && p2 && p3) {
    [p1, p2, p3].forEach(sel => {
      sel.addEventListener('change', () => {
        const vals = [p1.value, p2.value, p3.value].filter(v => v !== '0');
        const hasDup = vals.length !== new Set(vals).size;
        const submitBtn = document.querySelector('form button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = hasDup;
          submitBtn.title = hasDup ? 'Não selecione o mesmo grupo mais de uma vez.' : '';
        }
      });
    });
  }
});
