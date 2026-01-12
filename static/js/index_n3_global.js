
// Configuration spécifique niveau global
const globalDashboardConfig = {
  totalUsers: {{ stats.employes_total }},
  systemScope: 'GLOBAL',
  refreshInterval: 60000, // 1 minute pour les admins
  autoRefresh: true,
  criticalThresholds: {
    systemLoad: 90,
    errorRate: 5,
    pendingValidations: 50
  }
};

// Fonctions d'administration globale
function refreshGlobalData() {
  const refreshBtn = document.querySelector('[onclick="refreshGlobalData()"]');
  if (refreshBtn) {
    const icon = refreshBtn.querySelector('i');
    icon.classList.add('spinning');
  }
  
  fetch('{% url "refresh_stats_ajax" %}', {
    method: 'GET',
    headers: {
      'X-CSRFToken': '{{ csrf_token }}',
      'Content-Type': 'application/json'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification('Données globales mises à jour', 'success');
      setTimeout(() => location.reload(), 1000);
    } else {
      showNotification('Erreur lors de la mise à jour globale', 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur système lors de la mise à jour', 'error');
  })
  .finally(() => {
    if (refreshBtn) {
      const icon = refreshBtn.querySelector('i');
      icon.classList.remove('spinning');
    }
  });
}

function generateGlobalReport() {
  showNotification('Génération du rapport global en cours...', 'info');
  
  // Simulation de génération de rapport
  setTimeout(() => {
    showNotification('Rapport global généré avec succès', 'success');
  }, 3000);
}

function exportGlobalData() {
  showNotification('Export des données globales en cours...', 'info');
  
  // Simulation d'export
  setTimeout(() => {
    showNotification('Export global terminé avec succès', 'success');
  }, 2500);
}

// Surveillance système critique
function monitorSystemHealth() {
  const pendingValidations = {{ stats.demandes_en_attente_validation }};
  const totalDemands = {{ stats.demandes_total }};
  
  // Alerte système critique
  if (pendingValidations >= globalDashboardConfig.criticalThresholds.pendingValidations) {
    showNotification(
      `🚨 ALERTE SYSTÈME: ${pendingValidations} validations en attente - Intervention requise`, 
      'error',
      {
        url: '{% url "liste_interim_validation" %}',
        text: 'Intervenir immédiatement'
      }
    );
  }
  
  // Surveillance du volume global
  if (totalDemands > 1000) {
    showNotification(
      `📊 Volume élevé: ${totalDemands} demandes dans le système`, 
      'info',
      {
        url: '{% url "interim_stats" %}',
        text: 'Analyser les tendances'
      }
    );
  }
}

// Animation avancée des statistiques globales
function animateGlobalStats() {
  const globalStats = document.querySelectorAll('.global-stat-value');
  
  globalStats.forEach((stat, index) => {
    const text = stat.textContent;
    const value = parseFloat(text);
    
    if (!isNaN(value)) {
      let current = 0;
      const increment = value / 60; // Plus fluide pour les grands nombres
      const suffix = text.replace(value.toString(), '');
      
      // Animation échelonnée pour effet visuel
      setTimeout(() => {
        const timer = setInterval(() => {
          current += increment;
          if (current >= value) {
            current = value;
            clearInterval(timer);
          }
          
          if (value >= 100) {
            stat.textContent = Math.floor(current).toLocaleString() + suffix;
          } else {
            stat.textContent = Math.floor(current) + suffix;
          }
        }, 30);
      }, index * 200);
    }
  });
}

// Monitoring en temps réel
function startRealTimeMonitoring() {
  if (!globalDashboardConfig.autoRefresh) return;
  
  // Surveillance continue
  setInterval(() => {
    // Vérifications silencieuses
    fetch('{% url "refresh_stats_ajax" %}', {
      method: 'GET',
      headers: {
        'X-CSRFToken': '{{ csrf_token }}',
        'Content-Type': 'application/json'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Mise à jour silencieuse des indicateurs
        updateRealTimeIndicators(data);
      }
    })
    .catch(error => {
      console.warn('Surveillance temps réel: ', error);
    });
  }, globalDashboardConfig.refreshInterval);
}

function updateRealTimeIndicators(data) {
  // Mise à jour des indicateurs sans rechargement
  if (data.stats) {
    const indicators = document.querySelectorAll('.health-value');
    indicators.forEach(indicator => {
      // Animation subtile pour indiquer la mise à jour
      indicator.style.transform = 'scale(1.05)';
      setTimeout(() => {
        indicator.style.transform = 'scale(1)';
      }, 200);
    });
  }
}

// Raccourcis clavier pour les administrateurs
function setupAdminKeyboardShortcuts() {
  document.addEventListener('keydown', function(e) {
    // Ctrl+Alt+R = Refresh global
    if (e.ctrlKey && e.altKey && e.key === 'r') {
      e.preventDefault();
      refreshGlobalData();
    }
    
    // Ctrl+Alt+E = Export rapide
    if (e.ctrlKey && e.altKey && e.key === 'e') {
      e.preventDefault();
      exportGlobalData();
    }
    
    // Ctrl+Alt+G = Générer rapport
    if (e.ctrlKey && e.altKey && e.key === 'g') {
      e.preventDefault();
      generateGlobalReport();
    }
  });
}

// Initialisation complète niveau global
document.addEventListener('DOMContentLoaded', function() {
  // Surveillance immédiate
  setTimeout(monitorSystemHealth, 2000);
  
  // Animations
  setTimeout(animateGlobalStats, 1000);
  
  // Monitoring temps réel
  startRealTimeMonitoring();
  
  // Raccourcis admin
  setupAdminKeyboardShortcuts();
  
  // Messages de bienvenue admin
  {% if profil_utilisateur.type_profil == 'ADMIN' %}
  setTimeout(() => {
    showNotification(
      '👑 Mode Administrateur activé - Accès complet au système', 
      'success'
    );
  }, 2500);
  {% elif profil_utilisateur.type_profil == 'RH' %}
  setTimeout(() => {
    showNotification(
      '👨‍💼 Mode RH activé - Supervision globale des ressources humaines', 
      'success'
    );
  }, 2500);
  {% endif %}
  
  // Alerte si système surchargé
  {% if stats.demandes_en_attente_validation > 20 %}
  setTimeout(() => {
    showNotification(
      '⚠️ Système surchargé: {{ stats.demandes_en_attente_validation }} validations en attente', 
      'warning',
      {
        url: '{% url "liste_interim_validation" %}',
        text: 'Prendre en charge'
      }
    );
  }, 4000);
  {% endif %}
  
  // Rappel des raccourcis clavier
  setTimeout(() => {
    console.log(`
🔧 RACCOURCIS ADMINISTRATEUR:
• Ctrl+Alt+R : Refresh global
• Ctrl+Alt+E : Export rapide  
• Ctrl+Alt+G : Générer rapport
    `);
  }, 1000);
});

// Gestion des erreurs critiques
window.addEventListener('error', function(e) {
  if (globalDashboardConfig.systemScope === 'GLOBAL') {
    console.error('ERREUR SYSTÈME CRITIQUE:', e.error);
    showNotification('🚨 Erreur système critique détectée', 'error');
  }
});

console.log('Dashboard global initialisé:', globalDashboardConfig);
console.log('🌐 Mode Global RH/Admin actif - Surveillance complète du système');

