// Password strength checker
function checkPasswordStrength(password) {
  let strength = 0;
  
  if (password.length >= 8) strength++;
  if (password.length >= 12) strength++;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
  if (/\d/.test(password)) strength++;
  if (/[^a-zA-Z0-9]/.test(password)) strength++;
  
  return strength;
}

function updatePasswordStrength() {
  const password = document.getElementById('password').value;
  const strengthFill = document.getElementById('strengthFill');
  const strengthText = document.getElementById('strengthText');
  
  const strength = checkPasswordStrength(password);
  
  strengthFill.className = 'strength-fill';
  
  if (password.length === 0) {
    strengthText.textContent = 'Entrez un mot de passe';
    strengthFill.style.width = '0%';
  } else if (strength <= 1) {
    strengthFill.classList.add('weak');
    strengthText.textContent = 'Faible - Ajoutez des majuscules, chiffres et caractères spéciaux';
  } else if (strength <= 2) {
    strengthFill.classList.add('fair');
    strengthText.textContent = 'Moyen - Continuez à améliorer';
  } else if (strength <= 3) {
    strengthFill.classList.add('good');
    strengthText.textContent = 'Bon - Presque parfait !';
  } else {
    strengthFill.classList.add('strong');
    strengthText.textContent = 'Excellent - Mot de passe robuste';
  }
}

function checkPasswordMatch() {
  const password = document.getElementById('password').value;
  const confirm = document.getElementById('password_confirm').value;
  const matchText = document.getElementById('passwordMatch');
  
  if (confirm.length === 0) {
    matchText.textContent = '';
    matchText.style.color = '';
  } else if (password === confirm) {
    matchText.textContent = '✓ Les mots de passe correspondent';
    matchText.style.color = 'var(--secondary)';
  } else {
    matchText.textContent = '✗ Les mots de passe ne correspondent pas';
    matchText.style.color = 'var(--danger)';
  }
}

// Checkbox styling
function updateCheckboxStyle(checkbox, item) {
  if (checkbox.checked) {
    item.classList.add('checked');
  } else {
    item.classList.remove('checked');
  }
}

// Superuser implies staff
document.getElementById('is_superuser').addEventListener('change', function() {
  const staffCheckbox = document.getElementById('is_staff');
  if (this.checked) {
    staffCheckbox.checked = true;
    staffCheckbox.disabled = true;
    updateCheckboxStyle(staffCheckbox, document.getElementById('staffItem'));
  } else {
    staffCheckbox.disabled = false;
  }
  updateCheckboxStyle(this, document.getElementById('superuserItem'));
});

document.getElementById('is_staff').addEventListener('change', function() {
  updateCheckboxStyle(this, document.getElementById('staffItem'));
});

// Event listeners
document.getElementById('password').addEventListener('input', function() {
  updatePasswordStrength();
  checkPasswordMatch();
});

document.getElementById('password_confirm').addEventListener('input', checkPasswordMatch);

// Form validation
document.getElementById('userForm').addEventListener('submit', function(e) {
  const password = document.getElementById('password').value;
  const confirm = document.getElementById('password_confirm').value;
  
  if (password !== confirm) {
    e.preventDefault();
    showNotification('Les mots de passe ne correspondent pas', 'error');
    return false;
  }
  
  if (password.length < 8) {
    e.preventDefault();
    showNotification('Le mot de passe doit contenir au moins 8 caractères', 'error');
    return false;
  }
});

// Initialize
document.addEventListener('DOMContentLoaded', function() {
  // Initialize checkbox styles
  updateCheckboxStyle(
    document.getElementById('is_superuser'), 
    document.getElementById('superuserItem')
  );
  updateCheckboxStyle(
    document.getElementById('is_staff'), 
    document.getElementById('staffItem')
  );
  
  // Check if superuser is already checked
  if (document.getElementById('is_superuser').checked) {
    document.getElementById('is_staff').disabled = true;
  }
  
  console.log('Formulaire création utilisateur initialisé');
});

// Notification helper (si showNotification n'est pas défini globalement)
if (typeof showNotification === 'undefined') {
  function showNotification(message, type) {
    alert(message);
  }
}
