// Configuration
const loginConfig = {
  maxAttempts: 3,
  lockoutDuration: 300000, // 5 minutes
  strengthCheck: true
};

// Variables globales
let attemptCount = parseInt(localStorage.getItem('loginAttempts')) || 0;
let lastAttempt = parseInt(localStorage.getItem('lastAttempt')) || 0;

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('loginForm');
  const usernameInput = document.getElementById('username');
  const passwordInput = document.getElementById('password');
  
  // Focus automatique sur le premier champ vide
  if (!usernameInput.value) {
    usernameInput.focus();
  } else {
    passwordInput.focus();
  }
  
  // Vérifier si le compte est bloqué
  checkLockout();
  
  // Validation en temps réel
  usernameInput.addEventListener('input', validateUsername);
  passwordInput.addEventListener('input', validatePassword);
  
  // Soumission du formulaire
  form.addEventListener('submit', handleFormSubmit);
  
  // Raccourcis clavier
  document.addEventListener('keydown', handleKeyboardShortcuts);
  
  // Auto-fermeture des notifications après 5 secondes
  setTimeout(closeAllNotifications, 5000);
});

// Validation du nom d'utilisateur
function validateUsername() {
  const input = document.getElementById('username');
  const value = input.value.trim();
  
  if (value.length === 0) {
    setInputState(input, 'normal');
    return false;
  }
  
  if (value.length < 3) {
    setInputState(input, 'error');
    return false;
  }
  
  setInputState(input, 'valid');
  return true;
}

// Validation du mot de passe
function validatePassword() {
  const input = document.getElementById('password');
  const value = input.value;
  
  if (value.length === 0) {
    setInputState(input, 'normal');
    return false;
  }
  
  if (value.length < 4) {
    setInputState(input, 'error');
    return false;
  }
  
  setInputState(input, 'valid');
  return true;
}

// État des champs de saisie
function setInputState(input, state) {
  input.classList.remove('error', 'valid');
  
  if (state === 'error') {
    input.classList.add('error');
  } else if (state === 'valid') {
    input.classList.add('valid');
  }
}

// Gestion de la soumission
function handleFormSubmit(e) {
  const now = Date.now();
  
  // Vérifier le lockout
  if (isLockedOut()) {
    e.preventDefault();
    const remaining = Math.ceil((lastAttempt + loginConfig.lockoutDuration - now) / 1000);
    showNotification(`Trop de tentatives. Réessayez dans ${remaining} secondes.`, 'error');
    return false;
  }
  
  // Validation des champs
  const usernameValid = validateUsername();
  const passwordValid = validatePassword();
  
  if (!usernameValid || !passwordValid) {
    e.preventDefault();
    showNotification('Veuillez corriger les erreurs de saisie', 'warning');
    return false;
  }
  
  // Afficher le spinner
  showLoading(true);
  
  // Incrémenter le compteur de tentatives
  attemptCount++;
  lastAttempt = now;
  localStorage.setItem('loginAttempts', attemptCount);
  localStorage.setItem('lastAttempt', lastAttempt);
  
  return true;
}

// Affichage/masquage du mot de passe
function togglePassword() {
  const passwordInput = document.getElementById('password');
  const toggleIcon = document.getElementById('passwordToggleIcon');
  
  if (passwordInput.type === 'password') {
    passwordInput.type = 'text';
    toggleIcon.className = 'fas fa-eye-slash';
  } else {
    passwordInput.type = 'password';
    toggleIcon.className = 'fas fa-eye';
  }
}

// Vérification du lockout
function isLockedOut() {
  if (attemptCount < loginConfig.maxAttempts) return false;
  
  const now = Date.now();
  return (now - lastAttempt) < loginConfig.lockoutDuration;
}

function checkLockout() {
  if (isLockedOut()) {
    const remaining = Math.ceil((lastAttempt + loginConfig.lockoutDuration - Date.now()) / 1000);
    showNotification(`Compte temporairement bloqué. Réessayez dans ${remaining} secondes.`, 'error');
    
    // Désactiver le formulaire
    document.getElementById('loginButton').disabled = true;
    
    // Décompte
    const countdown = setInterval(() => {
      const remaining = Math.ceil((lastAttempt + loginConfig.lockoutDuration - Date.now()) / 1000);
      
      if (remaining <= 0) {
        clearInterval(countdown);
        document.getElementById('loginButton').disabled = false;
        resetAttempts();
        showNotification('Vous pouvez maintenant réessayer', 'success');
      }
    }, 1000);
  }
}

function resetAttempts() {
  attemptCount = 0;
  localStorage.removeItem('loginAttempts');
  localStorage.removeItem('lastAttempt');
}

// Affichage du spinner
function showLoading(show) {
  const button = document.getElementById('loginButton');
  const text = document.getElementById('loginText');
  const spinner = document.getElementById('loginSpinner');
  
  if (show) {
    button.disabled = true;
    text.style.display = 'none';
    spinner.style.display = 'block';
  } else {
    button.disabled = false;
    text.style.display = 'flex';
    spinner.style.display = 'none';
  }
}

// Gestion des notifications
function showNotification(message, type = 'info') {
  const container = document.getElementById('notificationsContainer') || createNotificationContainer();
  
  const notification = document.createElement('div');
  notification.className = `notification ${type}`;
  
  const iconClass = {
    'info': 'fas fa-info-circle',
    'success': 'fas fa-check-circle',
    'warning': 'fas fa-exclamation-triangle',
    'error': 'fas fa-exclamation-circle'
  }[type] || 'fas fa-info-circle';
  
  notification.innerHTML = `
    <div class="icon">
      <i class="${iconClass}"></i>
    </div>
    <div class="content">
      <div class="message">${message}</div>
    </div>
    <button class="close" onclick="closeNotification(this)">
      <i class="fas fa-times"></i>
    </button>
  `;
  
  container.appendChild(notification);
  
  // Auto-fermeture après 5 secondes
  setTimeout(() => {
    if (notification.parentNode) {
      closeNotification(notification.querySelector('.close'));
    }
  }, 5000);
}

function createNotificationContainer() {
  const container = document.createElement('div');
  container.className = 'notifications-container';
  container.id = 'notificationsContainer';
  document.body.appendChild(container);
  return container;
}

function closeNotification(button) {
  const notification = button.closest('.notification');
  notification.style.transform = 'translateX(100%)';
  notification.style.opacity = '0';
  setTimeout(() => {
    if (notification.parentNode) {
      notification.remove();
    }
  }, 300);
}

function closeAllNotifications() {
  const notifications = document.querySelectorAll('.notification .close');
  notifications.forEach(button => {
    setTimeout(() => closeNotification(button), Math.random() * 1000);
  });
}

// Raccourcis clavier
function handleKeyboardShortcuts(e) {
  // Ctrl+A pour sélectionner le nom d'utilisateur
  if (e.ctrlKey && e.key === 'a' && document.activeElement.tagName !== 'INPUT') {
    e.preventDefault();
    document.getElementById('username').select();
  }
  
  // Échap pour effacer les champs
  if (e.key === 'Escape') {
    document.getElementById('username').value = '';
    document.getElementById('password').value = '';
    document.getElementById('username').focus();
  }
}

// Informations de contact
function showContactInfo() {
  showNotification(
    'Pour toute assistance, contactez l\'administrateur système à l\'adresse : admin@Interim365 - BNI.ci', 
    'info'
  );
}

// Nettoyage à la fermeture
window.addEventListener('beforeunload', function() {
  // Réinitialiser le formulaire
  showLoading(false);
});

// Gestion des erreurs
window.addEventListener('error', function(e) {
  console.error('Erreur JavaScript:', e.error);
  showNotification('Une erreur est survenue. Veuillez actualiser la page.', 'error');
});

console.log('Page de connexion initialisée');
