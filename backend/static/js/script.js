// IT Helpdesk RAG - Interactive Frontend Scripts
document.addEventListener('DOMContentLoaded', () => {
  // 1. Password Visibility Toggle with Eye Icons
  const eyeOpenSvg = `
    <svg class="eye-icon eye-open" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
      <circle cx="12" cy="12" r="3"></circle>
    </svg>`;
  const eyeClosedSvg = `
    <svg class="eye-icon eye-closed" style="display: none;" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
      <line x1="1" y1="1" x2="23" y2="23"></line>
    </svg>`;

  const toggleButtons = document.querySelectorAll('.toggle-password');
  toggleButtons.forEach(btn => {
    // Populate eye icons
    if (!btn.querySelector('.eye-icon')) {
      btn.innerHTML = eyeOpenSvg + eyeClosedSvg;
      btn.setAttribute('aria-label', 'Toggle password visibility');
      btn.setAttribute('title', 'Show / Hide password');
    }

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const targetId = btn.getAttribute('data-target');
      const input = document.getElementById(targetId);
      if (!input) return;

      const eyeOpen = btn.querySelector('.eye-open');
      const eyeClosed = btn.querySelector('.eye-closed');

      if (input.type === 'password') {
        input.type = 'text';
        if (eyeOpen) eyeOpen.style.display = 'none';
        if (eyeClosed) eyeClosed.style.display = 'block';
        btn.setAttribute('aria-label', 'Hide password');
      } else {
        input.type = 'password';
        if (eyeOpen) eyeOpen.style.display = 'block';
        if (eyeClosed) eyeClosed.style.display = 'none';
        btn.setAttribute('aria-label', 'Show password');
      }
    });
  });

  // 2. Alert Dismissal
  const closeAlertButtons = document.querySelectorAll('.alert-close');
  closeAlertButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const alert = btn.closest('.alert');
      if (alert) {
        alert.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-10px)';
        setTimeout(() => alert.remove(), 200);
      }
    });
  });

  // 3. Client-side Form Validation for Registration
  const registerForm = document.getElementById('registerForm');
  if (registerForm) {
    const passwordInput = document.getElementById('password');
    const confirmInput = document.getElementById('confirm_password');
    const errorContainer = document.getElementById('client-validation-error');

    registerForm.addEventListener('submit', (e) => {
      if (passwordInput && confirmInput) {
        if (passwordInput.value !== confirmInput.value) {
          e.preventDefault();
          if (errorContainer) {
            errorContainer.textContent = 'Passwords do not match.';
            errorContainer.style.display = 'block';
          } else {
            alert('Passwords do not match.');
          }
          confirmInput.focus();
        } else if (passwordInput.value.length < 6) {
          e.preventDefault();
          if (errorContainer) {
            errorContainer.textContent = 'Password must be at least 6 characters.';
            errorContainer.style.display = 'block';
          }
          passwordInput.focus();
        }
      }
    });
  }
});

