
document.addEventListener('DOMContentLoaded', function() {
  console.log('🔐 Initialisation du formulaire de changement de mot de passe');

  // ================================================================
  // VARIABLES GLOBALES
  // ================================================================
  
  const form = document.getElementById('passwordChangeForm');
  const submitBtn = document.getElementById('submitBtn');
  const loadingSpinner = document.getElementById('loadingSpinner');
  
  const currentPasswordInput = document.getElementById('current_password');
  const newPasswordInput = document.getElementById('new_password');
  const confirmPasswordInput = document.getElementById('confirm_password');
  
  const passwordStrength = document.getElementById('password_strength');
  const strengthFill = document.getElementById('strength_fill');
  const strengthText = document.getElementById('strength_text');
  const passwordMatch = document.getElementById('password_match');

  // ================================================================
  // FONCTIONS UTILITAIRES
  // ================================================================

  function showError(fieldId, message) {
    const errorElement = document.getElementById(fieldId + '_error');
    const inputElement = document.getElementById(fieldId);
    
    if (errorElement) {
      errorElement.textContent = message;
      errorElement.style.display = 'block';
    }
    
    if (inputElement) {
      inputElement.classList.add('is-invalid');
      inputElement.classList.remove('is-valid');
    }
  }

  function clearError(fieldId) {
    const errorElement = document.getElementById(fieldId + '_error');
    const inputElement = document.getElementById(fieldId);
    
    if (errorElement) {
      errorElement.style.display = 'none';
    }
    
    if (inputElement) {
      inputElement.classList.remove('is-invalid');
    }
  }

  function clearAllErrors() {
    ['current_password', 'new_password', 'confirm_password'].forEach(clearError);
  }

  function showNotification(message, type = 'info') {
    console.log(`📢 Notification ${type}: ${message}`);
    
    // Créer une notification temporaire
    const notification = document.createElement('div');
    notification.className = `alert alert-${type}`;
    notification.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 350px; animation: slideIn 0.3s ease;';
    notification.innerHTML = `
      <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
      <span>${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    // Retirer après 4 secondes
    setTimeout(() => {
      if (notification.parentNode) {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
          if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
          }
        }, 300);
      }
    }, 4000);
  }

  // ================================================================
  // GESTION DE L'AFFICHAGE DES MOTS DE PASSE
  // ================================================================

  window.togglePassword = function(fieldId) {
    const input = document.getElementById(fieldId);
    const icon = document.getElementById(fieldId + '_icon');
    
    if (input.type === 'password') {
      input.type = 'text';
      icon.classList.remove('fa-eye');
      icon.classList.add('fa-eye-slash');
    } else {
      input.type = 'password';
      icon.classList.remove('fa-eye-slash');
      icon.classList.add('fa-eye');
    }
  };

  // ================================================================
  // VALIDATION ET FORCE DU MOT DE PASSE
  // ================================================================

  function calculatePasswordStrength(password) {
    let score = 0;
    let feedback = '';
    
    // Longueur
    if (password.length >= 8) score += 1;
    if (password.length >= 12) score += 1;
    
    // Complexité
    if (/[a-z]/.test(password)) score += 1;
    if (/[A-Z]/.test(password)) score += 1;
    if (/\d/.test(password)) score += 1;
    if (/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)) score += 1;
    
    // Patterns
    if (!/(.)\1{2,}/.test(password)) score += 1; // Pas de répétitions
    if (!/123|abc|password|admin/i.test(password)) score += 1; // Pas de patterns communs
    
    if (score <= 2) {
      feedback = 'Très faible';
      return { strength: 'weak', score, feedback };
    } else if (score <= 4) {
      feedback = 'Faible';
      return { strength: 'fair', score, feedback };
    } else if (score <= 6) {
      feedback = 'Bon';
      return { strength: 'good', score, feedback };
    } else {
      feedback = 'Très fort';
      return { strength: 'strong', score, feedback };
    }
  }

  function updatePasswordRequirements(password) {
    const requirements = {
      'req_length': password.length >= 8,
      'req_lowercase': /[a-z]/.test(password),
      'req_uppercase': /[A-Z]/.test(password),
      'req_digit': /\d/.test(password),
      'req_special': /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)
    };

    Object.entries(requirements).forEach(([reqId, isValid]) => {
      const element = document.getElementById(reqId);
      const icon = element.querySelector('i');
      
      if (isValid) {
        element.classList.add('valid');
        element.classList.remove('invalid');
        icon.className = 'fas fa-check text-success';
      } else {
        element.classList.add('invalid');
        element.classList.remove('valid');
        icon.className = 'fas fa-times text-danger';
      }
    });

    return Object.values(requirements).every(req => req);
  }

  function updatePasswordMatch() {
    const newPassword = newPasswordInput.value;
    const confirmPassword = confirmPasswordInput.value;

    if (!confirmPassword) {
      passwordMatch.style.display = 'none';
      return;
    }

    passwordMatch.style.display = 'block';

    if (newPassword === confirmPassword) {
      passwordMatch.className = 'password-match match';
      passwordMatch.innerHTML = '<i class="fas fa-check"></i> Les mots de passe correspondent';
      confirmPasswordInput.classList.add('is-valid');
      confirmPasswordInput.classList.remove('is-invalid');
      return true;
    } else {
      passwordMatch.className = 'password-match no-match';
      passwordMatch.innerHTML = '<i class="fas fa-times"></i> Les mots de passe ne correspondent pas';
      confirmPasswordInput.classList.add('is-invalid');
      confirmPasswordInput.classList.remove('is-valid');
      return false;
    }
  }

  // ================================================================
  // EVENT LISTENERS
  // ================================================================

  // Nouveau mot de passe - force et exigences
  newPasswordInput.addEventListener('input', function() {
    const password = this.value;
    
    if (password) {
      passwordStrength.style.display = 'block';
      
      const { strength, feedback } = calculatePasswordStrength(password);
      
      strengthFill.className = `strength-fill ${strength}`;
      strengthText.className = `strength-text ${strength}`;
      strengthText.textContent = feedback;
      
      const allRequirementsMet = updatePasswordRequirements(password);
      
      if (allRequirementsMet) {
        this.classList.add('is-valid');
        this.classList.remove('is-invalid');
        clearError('new_password');
      } else {
        this.classList.remove('is-valid');
      }
    } else {
      passwordStrength.style.display = 'none';
      updatePasswordRequirements('');
      this.classList.remove('is-valid', 'is-invalid');
    }
    
    updatePasswordMatch();
  });

  // Confirmation du mot de passe
  confirmPasswordInput.addEventListener('input', updatePasswordMatch);

  // Effacer les erreurs lors de la saisie
  currentPasswordInput.addEventListener('input', () => clearError('current_password'));
  newPasswordInput.addEventListener('input', () => clearError('new_password'));
  confirmPasswordInput.addEventListener('input', () => clearError('confirm_password'));

  // ================================================================
  // SOUMISSION DU FORMULAIRE
  // ================================================================

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    
    clearAllErrors();
    
    const currentPassword = currentPasswordInput.value.trim();
    const newPassword = newPasswordInput.value.trim();
    const confirmPassword = confirmPasswordInput.value.trim();
    
    // Validation côté client
    let hasErrors = false;
    
    if (!currentPassword) {
      showError('current_password', 'Le mot de passe actuel est requis');
      hasErrors = true;
    }
    
    if (!newPassword) {
      showError('new_password', 'Le nouveau mot de passe est requis');
      hasErrors = true;
    } else if (newPassword.length < 8) {
      showError('new_password', 'Le mot de passe doit contenir au moins 8 caractères');
      hasErrors = true;
    } else if (!updatePasswordRequirements(newPassword)) {
      showError('new_password', 'Le mot de passe ne respecte pas toutes les exigences');
      hasErrors = true;
    }
    
    if (!confirmPassword) {
      showError('confirm_password', 'La confirmation du mot de passe est requise');
      hasErrors = true;
    } else if (newPassword !== confirmPassword) {
      showError('confirm_password', 'Les mots de passe ne correspondent pas');
      hasErrors = true;
    }
    
    if (currentPassword === newPassword) {
      showError('new_password', 'Le nouveau mot de passe doit être différent de l\'ancien');
      hasErrors = true;
    }
    
    if (hasErrors) {
      return;
    }
    
    // Désactiver le bouton et afficher le spinner
    submitBtn.disabled = true;
    loadingSpinner.classList.add('show');
    
    // Soumission AJAX
    const formData = {
      current_password: currentPassword,
      new_password: newPassword,
      confirm_password: confirmPassword
    };
    
    fetch(window.location.href, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        showNotification('Mot de passe modifié avec succès !', 'success');
        
        // Redirection après un délai
        setTimeout(() => {
          if (data.redirect_url) {
            window.location.href = data.redirect_url;
          } else {
            window.location.href = '/interim/';
          }
        }, 1500);
        
      } else {
        // Afficher les erreurs
        if (data.errors) {
          Object.entries(data.errors).forEach(([field, errors]) => {
            if (field === 'general') {
              showNotification(errors[0], 'error');
            } else {
              showError(field, errors[0]);
            }
          });
        } else {
          showNotification('Erreur lors du changement de mot de passe', 'error');
        }
      }
    })
    .catch(error => {
      console.error('Erreur:', error);
      showNotification('Erreur de communication avec le serveur', 'error');
    })
    .finally(() => {
      submitBtn.disabled = false;
      loadingSpinner.classList.remove('show');
    });
  });

  // ================================================================
  // INITIALISATION
  // ================================================================

  // Focus sur le premier champ
  currentPasswordInput.focus();
  
  // Initialiser les exigences
  updatePasswordRequirements('');
  
  console.log('✅ Formulaire de changement de mot de passe initialisé');
});

// ================================================================
// STYLES D'ANIMATION POUR LES NOTIFICATIONS
// ================================================================

const animationStyles = document.createElement('style');
animationStyles.textContent = `
  @keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  
  @keyframes slideOut {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
  }
`;
document.head.appendChild(animationStyles);

