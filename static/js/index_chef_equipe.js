// Configuration spécifique chef d'équipe
const teamDashboardConfig = {
  teamSize: window.TEAM_STATS?.membresEquipe || 0,
  refreshInterval: 90000, // 1.5 minutes pour les chefs d'équipe
  autoRefresh: true,
  teamScope: 'TEAM_LEAD',
  criticalThresholds: {
    teamLoad: 80,
    pendingValidations: 10,
    unavailableMembers: 3
  }
};

// Fonctions de gestion d'équipe
function refreshTeamData() {
  const refreshBtn = document.querySelector('[onclick="refreshTeamData()"]');
  if (refreshBtn) {
    const icon = refreshBtn.querySelector('i');
    icon.classList.add('spinning');
  }
  
  fetch(window.TEAM_URLS?.refreshStats || '/refresh-stats/', {
    method: 'GET',
    headers: {
      'X-CSRFToken': window.CSRF_TOKEN || '',
      'Content-Type': 'application/json'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification('Données d\'équipe mises à jour', 'success');
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

function exportTeamData() {
  showNotification('Export des données d\'équipe en cours...', 'info');
  
  // Simulation d'export
  setTimeout(() => {
    showNotification('Export de l\'équipe terminé avec succès', 'success');
  }, 2000);
}

function generateTeamReport() {
  showNotification('Génération du rapport d\'équipe en cours...', 'info');
  
  // Simulation de génération de rapport
  setTimeout(() => {
    showNotification('Rapport d\'équipe généré avec succès', 'success');
  }, 2500);
}

// Surveillance spécifique équipe
function monitorTeamHealth() {
  const teamSize = window.TEAM_STATS?.membresEquipe || 0;
  const pendingValidations = window.TEAM_STATS?.validationsATraiter || 0;
  const activeMissions = window.TEAM_STATS?.missionsEnCours || 0;
  
  // Alerte si équipe réduite
  if (teamSize < 3) {
    showNotification(
      `⚠️ Équipe réduite: seulement ${teamSize} membre(s) - Planification recommandée`, 
      'warning'
    );
  }
  
  // Alerte charge de travail
  if (activeMissions > teamSize * 2) {
    showNotification(
      `📊 Charge élevée: ${activeMissions} missions pour ${teamSize} membre(s)`, 
      'info'
    );
  }
  
  // Rappel validations
  if (pendingValidations > 0) {
    setTimeout(() => {
      showNotification(
        `📋 Rappel: ${pendingValidations} validation(s) en attente pour votre équipe`, 
        'info',
        {
          url: window.TEAM_URLS?.listeInterimValidation || '#',
          text: 'Suivre le statut'
        }
      );
    }, 3000);
  }
}

// Animation des statistiques équipe
function animateTeamStats() {
  const teamStats = document.querySelectorAll('.team-stat-value');
  
  teamStats.forEach((stat, index) => {
    const text = stat.textContent;
    const value = parseFloat(text);
    
    if (!isNaN(value)) {
      let current = 0;
      const increment = value / 50; // Animation plus rapide pour équipe
      const suffix = text.replace(value.toString(), '');
      
      setTimeout(() => {
        const timer = setInterval(() => {
          current += increment;
          if (current >= value) {
            current = value;
            clearInterval(timer);
          }
          
          if (value >= 100) {
            stat.textContent = Math.floor(current) + suffix;
          } else {
            stat.textContent = Math.floor(current) + suffix;
          }
        }, 25);
      }, index * 150);
    }
  });
}

// Monitoring temps réel équipe
function startTeamMonitoring() {
  if (!teamDashboardConfig.autoRefresh) return;
  
  setInterval(() => {
    // Vérifications silencieuses pour l'équipe
    fetch(window.TEAM_URLS?.refreshStats || '/refresh-stats/', {
      method: 'GET',
      headers: {
        'X-CSRFToken': window.CSRF_TOKEN || '',
        'Content-Type': 'application/json'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        updateTeamIndicators(data);
      }
    })
    .catch(error => {
      console.warn('Surveillance équipe: ', error);
    });
  }, teamDashboardConfig.refreshInterval);
}

function updateTeamIndicators(data) {
  // Mise à jour subtile des indicateurs équipe
  if (data.stats) {
    const healthCards = document.querySelectorAll('.health-value');
    healthCards.forEach(card => {
      card.style.transform = 'scale(1.02)';
      setTimeout(() => {
        card.style.transform = 'scale(1)';
      }, 150);
    });
  }
}

// Raccourcis clavier pour chef d'équipe
function setupTeamKeyboardShortcuts() {
  document.addEventListener('keydown', function(e) {
    // Ctrl+T = Refresh équipe
    if (e.ctrlKey && e.key === 't') {
      e.preventDefault();
      refreshTeamData();
    }
    
    // Ctrl+N = Nouvelle demande
    if (e.ctrlKey && e.key === 'n') {
      e.preventDefault();
      window.location.href = window.TEAM_URLS?.interimDemande || '#';
    }
    
    // Ctrl+E = Export équipe
    if (e.ctrlKey && e.key === 'e') {
      e.preventDefault();
      exportTeamData();
    }
    
    // Ctrl+G = Gestion équipe
    if (e.ctrlKey && e.key === 'g') {
      e.preventDefault();
      window.location.href = window.TEAM_URLS?.employesListe || '#';
    }
  });
}

// Gestion des notifications équipe
function setupTeamNotifications() {
  // Alerte si membre critique indisponible
  if (window.TEAM_STATS?.membresCritiquesIndisponibles > 0) {
    setTimeout(() => {
      showNotification(
        `🚨 Attention: ${window.TEAM_STATS.membresCritiquesIndisponibles} membre(s) critique(s) indisponible(s)`, 
        'warning',
        {
          url: window.TEAM_URLS?.employesListe || '#',
          text: 'Voir l\'équipe'
        }
      );
    }, 4000);
  }
  
  // Message de motivation équipe
  const teamPerformance = window.TEAM_STATS?.tauxReussiteEquipe || 85;
  if (teamPerformance >= 90) {
    setTimeout(() => {
      showNotification(
        `🏆 Excellente performance d'équipe: ${teamPerformance}% de réussite!`, 
        'success'
      );
    }, 6000);
  }
}

// Initialisation complète chef d'équipe
document.addEventListener('DOMContentLoaded', function() {
  // Surveillance équipe
  setTimeout(monitorTeamHealth, 1500);
  
  // Animations
  setTimeout(animateTeamStats, 800);
  
  // Monitoring temps réel
  startTeamMonitoring();
  
  // Raccourcis clavier
  setupTeamKeyboardShortcuts();
  
  // Notifications équipe
  setupTeamNotifications();
  
  // Message de bienvenue chef d'équipe
  setTimeout(() => {
    showNotification(
      `👥 Mode Chef d'Équipe activé - Supervision de ${teamDashboardConfig.teamSize} collaborateur(s)`, 
      'success'
    );
  }, 2000);
  
  // Rappel des raccourcis
  setTimeout(() => {
    console.log(`
👥 RACCOURCIS CHEF D'ÉQUIPE:
• Ctrl+T : Refresh équipe
• Ctrl+N : Nouvelle demande
• Ctrl+E : Export équipe
• Ctrl+G : Gestion équipe
    `);
  }, 1000);
});

// Fonctions avancées chef d'équipe
function quickTeamAssign() {
  showNotification('Assignation rapide d\'équipe...', 'info');
  // Logique d'assignation rapide
}

function teamEmergencyAlert() {
  const alertMessage = prompt('Message d\'alerte équipe:');
  if (alertMessage) {
    showNotification('🚨 ALERTE ÉQUIPE: ' + alertMessage, 'warning');
  }
}

function generateTeamPlan() {
  showNotification('Génération du planning équipe...', 'info');
  
  setTimeout(() => {
    showNotification('Planning équipe généré avec succès', 'success');
  }, 2000);
}

console.log('Dashboard chef d\'équipe initialisé:', teamDashboardConfig);
console.log('👥 Mode Chef d\'Équipe actif - Gestion complète de l\'équipe');
