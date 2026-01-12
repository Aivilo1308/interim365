// Notification
function showNotification(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `alert alert-${type === 'error' ? 'danger' : type} position-fixed`;
  toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px; animation: slideIn 0.3s ease;';
  toast.innerHTML = `
    <div class="d-flex align-items-center">
      <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'} me-2"></i>
      <span>${message}</span>
      <button type="button" class="btn-close ms-auto" onclick="this.parentElement.parentElement.remove()"></button>
    </div>
  `;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

// Créer une sauvegarde
function createBackup(type = 'json') {
  const btn = event.target.closest('.action-btn, .quick-action');
  if (btn) {
    const icon = btn.querySelector('i');
    if (icon) icon.classList.add('spinning');
  }
  
  showNotification('Création de la sauvegarde en cours...', 'info');
  
  fetch(window.MAINTENANCE_URLS?.backupCreer || '/backup/creer/', {
    method: 'POST',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: `backup_type=${type}`
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
      setTimeout(() => location.reload(), 1500);
    } else {
      showNotification(data.error || 'Erreur lors de la sauvegarde', 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur lors de la sauvegarde', 'error');
  })
  .finally(() => {
    if (btn) {
      const icon = btn.querySelector('i');
      if (icon) icon.classList.remove('spinning');
    }
  });
}

// Supprimer une sauvegarde
function deleteBackup(filename) {
  if (!confirm(`Supprimer la sauvegarde "${filename}" ?`)) return;
  
  const url = (window.MAINTENANCE_URLS?.backupSupprimer || '/backup/supprimer/PLACEHOLDER/').replace('PLACEHOLDER', filename);
  
  fetch(url, {
    method: 'POST',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'X-Requested-With': 'XMLHttpRequest'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
      setTimeout(() => location.reload(), 1000);
    } else {
      showNotification(data.error || 'Erreur', 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur lors de la suppression', 'error');
  });
}

// Optimiser la base de données
function runVacuum() {
  showNotification('Optimisation en cours...', 'info');
  
  fetch(window.MAINTENANCE_URLS?.optimisationVacuum || '/optimisation/vacuum/', {
    method: 'POST',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'X-Requested-With': 'XMLHttpRequest'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
    } else {
      showNotification(data.error || 'Erreur', 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur lors de l\'optimisation', 'error');
  });
}

// Vider le cache
function clearCache() {
  showNotification('Vidage du cache en cours...', 'info');
  
  fetch(window.MAINTENANCE_URLS?.optimisationClearCache || '/optimisation/clear-cache/', {
    method: 'POST',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'X-Requested-With': 'XMLHttpRequest'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
    } else {
      showNotification(data.error || 'Erreur', 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur lors du vidage du cache', 'error');
  });
}

// Nettoyer les sessions
function clearSessions() {
  showNotification('Nettoyage des sessions...', 'info');
  
  fetch(window.MAINTENANCE_URLS?.optimisationClearSessions || '/optimisation/clear-sessions/', {
    method: 'POST',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'X-Requested-With': 'XMLHttpRequest'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
    } else {
      showNotification(data.error || 'Erreur', 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur lors du nettoyage', 'error');
  });
}

console.log('🔧 Module Maintenance chargé');
