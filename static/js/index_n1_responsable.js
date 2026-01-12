// Configuration spécifique responsable N+1
const deptDashboardConfig = {
  departmentSize: window.DEPT_STATS?.employesDepartement || 0,
  teamsCount: window.DEPT_STATS?.chefsEquipe || 0,
  refreshInterval: 180000, // 3 minutes pour les responsables
  autoRefresh: true,
  alertThresholds: {
    validationBacklog: 5,
    delayThreshold: 3
  }
};

// Fonctions spécifiques
function refreshTeamsData() {
  const refreshBtn = document.querySelector('[onclick="refreshTeamsData()"]');
  if (refreshBtn) {
    const icon = refreshBtn.querySelector('i');
    icon.classList.add('spinning');
  }
  
  fetch(window.DEPT_URLS?.refreshStats || '/refresh-stats/', {
    method: 'GET',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'Content-Type': 'application/json'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification('Données du département mises à jour', 'success');
      setTimeout(() => location.reload(), 1000);
    } else {
      showNotification('Erreur lors de la mise à jour', 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur lors de la mise à jour', 'error');
  })
  .finally(() => {
    if (refreshBtn) {
      const icon = refreshBtn.querySelector('i');
      icon.classList.remove('spinning');
    }
  });
}

// Surveillance des seuils d'alerte
function checkAlertThresholds() {
  const validationsCount = window.DEPT_STATS?.demandesEnValidation || 0;
  
  if (validationsCount >= deptDashboardConfig.alertThresholds.validationBacklog) {
    showNotification(
      `Attention: ${validationsCount} validations en attente dans votre département`, 
      'warning',
      {
        url: window.DEPT_URLS?.listeInterimValidation || '#',
        text: 'Traiter maintenant'
      }
    );
  }
}

// Auto-refresh pour les responsables
function startAutoRefresh() {
  if (deptDashboardConfig.autoRefresh) {
    setInterval(() => {
      refreshTeamsData();
    }, deptDashboardConfig.refreshInterval);
  }
}

// Animation des statistiques du département
function animateDeptStats() {
  const statValues = document.querySelectorAll('.dept-stat-value');
  statValues.forEach(stat => {
    const value = parseInt(stat.textContent);
    if (!isNaN(value)) {
      let current = 0;
      const increment = value / 30;
      
      const timer = setInterval(() => {
        current += increment;
        if (current >= value) {
          current = value;
          clearInterval(timer);
        }
        stat.textContent = Math.floor(current);
      }, 50);
    }
  });
}

// Vérifications initiales
document.addEventListener('DOMContentLoaded', function() {
  // Vérification des seuils d'alerte
  setTimeout(checkAlertThresholds, 3000);
  
  // Animation des statistiques
  animateDeptStats();
  
  // Démarrage de l'auto-refresh
  startAutoRefresh();
});

console.log('Dashboard responsable N+1 initialisé:', deptDashboardConfig);
