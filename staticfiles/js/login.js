// ================================================
// newsdecklive — Login / Signup Interactions
// ================================================

document.addEventListener('DOMContentLoaded', () => {
  const wrapper    = document.getElementById('authWrapper');
  const showSignup = document.getElementById('showSignup');
  const showLogin  = document.getElementById('showLogin');
  const flipper    = document.getElementById('cardFlipper');
  const frontCard  = document.querySelector('.card-face--front');
  const backCard   = document.querySelector('.card-face--back');

  // Sync flipper height to the visible card so footer never overlaps
  function syncHeight(showBack) {
    if (!flipper) return;
    const active = showBack ? backCard : frontCard;
    if (active) {
      flipper.style.minHeight = active.scrollHeight + 'px';
    }
  }
  // Set initial height
  syncHeight(wrapper && wrapper.classList.contains('show-signup'));

  // ---------- Card Flip ----------
  if (showSignup) {
    showSignup.addEventListener('click', (e) => {
      e.preventDefault();
      wrapper.classList.add('show-signup');
      syncHeight(true);
    });
  }

  if (showLogin) {
    showLogin.addEventListener('click', (e) => {
      e.preventDefault();
      wrapper.classList.remove('show-signup');
      syncHeight(false);
    });
  }

  // ---------- Password Toggle ----------
  document.querySelectorAll('.form-group__toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const input = document.getElementById(targetId);
      if (!input) return;

      const icon = btn.querySelector('i');
      if (input.type === 'password') {
        input.type = 'text';
        icon.classList.replace('fa-eye', 'fa-eye-slash');
      } else {
        input.type = 'password';
        icon.classList.replace('fa-eye-slash', 'fa-eye');
      }
    });
  });

  // ---------- Button Loading State ----------
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', () => {
      const btn = form.querySelector('.btn-submit');
      if (btn) {
        btn.classList.add('is-loading');
        btn.disabled = true;
      }
    });
  });

  // ---------- Floating Particles ----------
  const particlesContainer = document.getElementById('particles');
  if (particlesContainer) {
    const count = 30;
    for (let i = 0; i < count; i++) {
      const particle = document.createElement('div');
      particle.classList.add('particle');
      particle.style.left = Math.random() * 100 + '%';
      particle.style.width = particle.style.height = (Math.random() * 3 + 1.5) + 'px';
      particle.style.animationDuration = (Math.random() * 15 + 10) + 's';
      particle.style.animationDelay = (Math.random() * 15) + 's';
      particle.style.opacity = Math.random() * 0.3 + 0.05;
      particlesContainer.appendChild(particle);
    }
  }

  // ---------- Input Focus Ripple Effect ----------
  document.querySelectorAll('.form-group__input, .form-group__select').forEach(input => {
    input.addEventListener('focus', () => {
      input.parentElement.style.transform = 'scale(1.01)';
      input.parentElement.style.transition = 'transform 0.2s ease';
    });
    input.addEventListener('blur', () => {
      input.parentElement.style.transform = 'scale(1)';
    });
  });
});
