// Configuration spécifique directeur
const executiveDashboardConfig = {
  organizationSize: window.EXEC_STATS?.employesLignee || 0,
  departmentsCount: window.EXEC_STATS?.departementsCount || 0,
  refreshInterval: 300000, // 5 minutes pour les directeurs
  autoRefresh: true,
  alertThresholds: {
    criticalBacklog: 20,
    performanceThreshold: 70
  }
};

// Fonctions spécifiques directeur
function exportStrategicReport() {
  showNotification('Génération du rapport stratégique en cours...', 'info');
  
  // Simulation d'export
  setTimeout(() => {
    showNotification('Rapport stratégique généré avec succès', 'success');
  }, 2000);
}

function refreshExecutiveData() {
  const refreshBtn = document.querySelector('[onclick="refreshExecutiveData()"]');
  if (refreshBtn) {
    const icon = refreshBtn.querySelector('i');
    icon.classList.add('spinning');
  }
  
  fetch(window.EXEC_URLS?.refreshStats || '/refresh-stats/', {
    method: 'GET',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'Content-Type': 'application/json'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification('Données stratégiques mises à jour', 'success');
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

// Surveillance des seuils critiques
function checkCriticalThresholds() {
  const demandesEnCours = window.EXEC_STATS?.demandesEnCours || 0;
  const performanceGlobale = window.EXEC_STATS?.tauxValidationGlobal || 0;
  
  if (demandesEnCours >= executiveDashboardConfig.alertThresholds.criticalBacklog) {
    showNotification(
      `Alerte: ${demandesEnCours} demandes en cours - Seuil critique atteint`, 
      'warning',
      {
        url: window.EXEC_URLS?.listeInterimValidation || '#',
        text: 'Superviser'
      }
    );
  }
  
  if (performanceGlobale < executiveDashboardConfig.alertThresholds.performanceThreshold) {
    showNotification(
      `Performance globale: ${performanceGlobale}% - En dessous du seuil`, 
      'warning',
      {
        url: window.EXEC_URLS?.interimStats || '#',
        text: 'Analyser'
      }
    );
  }
}

// Animation des KPI
function animateKPIs() {
  const kpiValues = document.querySelectorAll('.kpi-value, .exec-stat-value');
  kpiValues.forEach((kpi, index) => {
    const text = kpi.textContent;
    const value = parseFloat(text);
    
    if (!isNaN(value)) {
      let current = 0;
      const increment = value / 50;
      const suffix = text.replace(value.toString(), '');
      
      const timer = setInterval(() => {
        current += increment;
        if (current >= value) {
          current = value;
          clearInterval(timer);
        }
        kpi.textContent = Math.floor(current) + suffix;
      }, 30 + (index * 10)); // Délai échelonné
    }
  });
}

// Auto-refresh pour les directeurs
function startAutoRefresh() {
  if (executiveDashboardConfig.autoRefresh) {
    setInterval(() => {
      refreshExecutiveData();
    }, executiveDashboardConfig.refreshInterval);
  }
}

// Notification volume élevé
function checkHighVolume() {
  const demandesEnCours = window.EXEC_STATS?.demandesEnCours || 0;
  if (demandesEnCours > 15) {
    setTimeout(() => {
      showNotification(
        `Volume élevé: ${demandesEnCours} demandes nécessitent votre attention`, 
        'info',
        {
          url: window.EXEC_URLS?.listeInterimValidation || '#',
          text: 'Superviser'
        }
      );
    }, 3000);
  }
}

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(checkCriticalThresholds, 4000);
  setTimeout(animateKPIs, 1000);
  
  // Démarrage auto-refresh
  startAutoRefresh();
  
  // Vérification volume élevé
  checkHighVolume();
});

console.log('Dashboard directeur initialisé:', executiveDashboardConfig);
