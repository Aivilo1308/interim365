const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                  document.querySelector('meta[name="csrf-token"]')?.content;

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

function setCardRunning(cardId, running) {
  const card = document.getElementById(cardId);
  if (!card) return;
  
  const icon = card.querySelector('.action-card-icon i');
  if (running) {
    card.classList.add('running');
    icon.className = 'fas fa-spinner spinning';
  } else {
    card.classList.remove('running');
    // Restaurer l'icône originale
    const icons = {
      'vacuumCard': 'fa-compress-arrows-alt',
      'cacheCard': 'fa-broom',
      'sessionsCard': 'fa-user-clock',
      'logsCard': 'fa-archive'
    };
    icon.className = 'fas ' + (icons[cardId] || 'fa-cog');
  }
}

function runVacuum() {
  setCardRunning('vacuumCard', true);
  showNotification('Optimisation VACUUM en cours...', 'info');
  
  fetch(URLS.vacuum, {
    method: 'POST',
    headers: {
      'X-CSRFToken': csrfToken,
      'X-Requested-With': 'XMLHttpRequest'
    }
  })
  .then(response => response.json())
  .then(data => {
    setCardRunning('vacuumCard', false);
    if (data.success) {
      showNotification(data.message, 'success');
    } else {
      showNotification(data.error || 'Erreur', 'error');
    }
  })
  .catch(error => {
    setCardRunning('vacuumCard', false);
    console.error('Erreur:', error);
    showNotification('Erreur lors de l\'optimisation', 'error');
  });
}

function clearCache() {
  setCardRunning('cacheCard', true);
  showNotification('Vidage du cache en cours...', 'info');
  
  fetch(URLS.clearCache, {
    method: 'POST',
    headers: {
      'X-CSRFToken': csrfToken,
      'X-Requested-With': 'XMLHttpRequest'
    }
  })
  .then(response => response.json())
  .then(data => {
    setCardRunning('cacheCard', false);
    if (data.success) {
      showNotification(data.message, 'success');
    } else {
      showNotification(data.error || 'Erreur', 'error');
    }
  })
  .catch(error => {
    setCardRunning('cacheCard', false);
    console.error('Erreur:', error);
    showNotification('Erreur lors du vidage du cache', 'error');
  });
}

function clearSessions() {
  setCardRunning('sessionsCard', true);
  showNotification('Nettoyage des sessions...', 'info');
  
  fetch(URLS.clearSessions, {
    method: 'POST',
    headers: {
      'X-CSRFToken': csrfToken,
      'X-Requested-With': 'XMLHttpRequest'
    }
  })
  .then(response => response.json())
  .then(data => {
    setCardRunning('sessionsCard', false);
    if (data.success) {
      showNotification(data.message, 'success');
    } else {
      showNotification(data.error || 'Erreur', 'error');
    }
  })
  .catch(error => {
    setCardRunning('sessionsCard', false);
    console.error('Erreur:', error);
    showNotification('Erreur lors du nettoyage', 'error');
  });
}

function archiveLogs() {
  const modal = new bootstrap.Modal(document.getElementById('archiveLogsModal'));
  modal.show();
}

document.addEventListener('DOMContentLoaded', function() {
  const confirmArchiveBtn = document.getElementById('confirmArchiveBtn');
  if (confirmArchiveBtn) {
    confirmArchiveBtn.addEventListener('click', function() {
      const days = document.getElementById('archiveDays').value;
      const btn = this;
      const originalText = btn.innerHTML;
      btn.innerHTML = '<i class="fas fa-spinner spinning"></i> Archivage...';
      btn.disabled = true;
      
      fetch(URLS.archiveLogs, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: `days=${days}`
      })
      .then(response => response.json())
      .then(data => {
        bootstrap.Modal.getInstance(document.getElementById('archiveLogsModal')).hide();
        if (data.success) {
          showNotification(data.message, 'success');
        } else {
          showNotification(data.error || 'Erreur', 'error');
        }
        btn.innerHTML = originalText;
        btn.disabled = false;
      })
      .catch(error => {
        console.error('Erreur:', error);
        showNotification('Erreur lors de l\'archivage', 'error');
        btn.innerHTML = originalText;
        btn.disabled = false;
      });
    });
  }
  
  console.log('🚀 Module Optimisation chargé');
});
