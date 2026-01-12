// Variables globales
let selectedBackupType = null;
let fileToRestore = null;

// Notification
function showNotification(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `alert alert-${type === 'error' ? 'danger' : type} position-fixed`;
  toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
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

// Sélection du type de backup
function selectBackupType(element, type) {
  // Désélectionner tous
  document.querySelectorAll('.backup-option').forEach(el => el.classList.remove('selected'));
  // Sélectionner celui-ci
  element.classList.add('selected');
  selectedBackupType = type;
  // Activer le bouton
  document.getElementById('createBackupBtn').disabled = false;
}

// Création de backup
function createBackup() {
  if (!selectedBackupType) {
    showNotification('Veuillez sélectionner un type de sauvegarde', 'warning');
    return;
  }
  
  const btn = document.getElementById('createBackupBtn');
  const originalText = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner spinning"></i> Création en cours...';
  btn.disabled = true;
  
  fetch(window.BACKUP_URLS?.creer || '/backup/creer/', {
    method: 'POST',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: `backup_type=${selectedBackupType}`
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
      setTimeout(() => location.reload(), 1500);
    } else {
      showNotification(data.error || 'Erreur', 'error');
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur lors de la création', 'error');
    btn.innerHTML = originalText;
    btn.disabled = false;
  });
}

// Suppression de backup
function deleteBackup(filename) {
  if (!confirm(`Êtes-vous sûr de vouloir supprimer "${filename}" ?`)) return;
  
  const url = (window.BACKUP_URLS?.supprimer || '/backup/supprimer/PLACEHOLDER/').replace('PLACEHOLDER', filename);
  
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

// Restauration de backup
function restoreBackup(filename) {
  fileToRestore = filename;
  const modal = new bootstrap.Modal(document.getElementById('restoreModal'));
  modal.show();
}

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
  const confirmRestoreBtn = document.getElementById('confirmRestoreBtn');
  
  if (confirmRestoreBtn) {
    confirmRestoreBtn.addEventListener('click', function() {
      if (!fileToRestore) return;
      
      const btn = this;
      const originalText = btn.innerHTML;
      btn.innerHTML = '<i class="fas fa-spinner spinning"></i> Restauration...';
      btn.disabled = true;
      
      const url = (window.BACKUP_URLS?.restaurer || '/backup/restaurer/PLACEHOLDER/').replace('PLACEHOLDER', fileToRestore);
      
      fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': window.CSRF_TOKEN || '',
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
      .then(response => response.json())
      .then(data => {
        bootstrap.Modal.getInstance(document.getElementById('restoreModal')).hide();
        if (data.success) {
          showNotification(data.message, 'success');
          setTimeout(() => location.reload(), 2000);
        } else {
          showNotification(data.error || 'Erreur', 'error');
          btn.innerHTML = originalText;
          btn.disabled = false;
        }
      })
      .catch(error => {
        console.error('Erreur:', error);
        showNotification('Erreur lors de la restauration', 'error');
        btn.innerHTML = originalText;
        btn.disabled = false;
      });
    });
  }
});
