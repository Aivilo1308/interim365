<script src="https://cdn.jsdelivr.net/npm/chart.js">


document.addEventListener('DOMContentLoaded', function() {
  console.log('📊 Page dashboard workflow initialisée');
  
  // ========================================
  // INITIALISATION DES GRAPHIQUES
  // ========================================
  
  // Données depuis le template Django
  const donneesGraphiques = {{ donnees_graphiques|safe }};
  
  // Graphique d'évolution temporelle
  if (document.getElementById('evolutionChart') && donneesGraphiques.evolution_temporelle) {
    initEvolutionChart(donneesGraphiques.evolution_temporelle);
  }
  
  // Graphique répartition par étapes
  if (document.getElementById('etapesChart') && donneesGraphiques.repartition_etapes) {
    initEtapesChart(donneesGraphiques.repartition_etapes);
  }
  
  // Graphique temps par étape
  if (document.getElementById('tempsChart') && donneesGraphiques.temps_par_etape) {
    initTempsChart(donneesGraphiques.temps_par_etape);
  }
  
  // Graphique performance départements
  if (document.getElementById('departementChart') && donneesGraphiques.performance_departements) {
    initDepartementChart(donneesGraphiques.performance_departements);
  }
  
  // ========================================
  // ANIMATIONS ET INTERACTIONS
  // ========================================
  
  // Animation des KPIs au scroll
  animateKPIs();
  
  // Auto-submit des filtres
  setupFilterAutoSubmit();
  
  // Tooltips et interactions
  setupTooltips();
  
  console.log('✅ Dashboard workflow initialisé avec succès');
});

// ========================================
// FONCTIONS D'INITIALISATION DES GRAPHIQUES
// ========================================

function initEvolutionChart(data) {
  const ctx = document.getElementById('evolutionChart').getContext('2d');
  
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.labels,
      datasets: [
        {
          label: 'Total demandes',
          data: data.datasets.total,
          borderColor: '#6f42c1',
          backgroundColor: 'rgba(111, 66, 193, 0.1)',
          tension: 0.4,
          fill: true
        },
        {
          label: 'Terminées',
          data: data.datasets.terminees,
          borderColor: '#28a745',
          backgroundColor: 'rgba(40, 167, 69, 0.1)',
          tension: 0.4,
          fill: false
        },
        {
          label: 'En retard',
          data: data.datasets.en_retard,
          borderColor: '#dc3545',
          backgroundColor: 'rgba(220, 53, 69, 0.1)',
          tension: 0.4,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top'
        },
        title: {
          display: false
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          grid: {
            color: 'rgba(0,0,0,0.1)'
          }
        },
        x: {
          grid: {
            display: false
          }
        }
      },
      interaction: {
        intersect: false,
        mode: 'index'
      }
    }
  });
}

function initEtapesChart(data) {
  const ctx = document.getElementById('etapesChart').getContext('2d');
  
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.labels,
      datasets: [{
        data: data.data,
        backgroundColor: data.colors,
        borderWidth: 2,
        borderColor: '#fff'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom'
        }
      }
    }
  });
}

function initTempsChart(data) {
  const ctx = document.getElementById('tempsChart').getContext('2d');
  
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.labels,
      datasets: [{
        label: 'Temps moyen (heures)',
        data: data.data,
        backgroundColor: [
          'rgba(111, 66, 193, 0.8)',
          'rgba(40, 167, 69, 0.8)',
          'rgba(23, 162, 184, 0.8)'
        ],
        borderColor: [
          '#6f42c1',
          '#28a745',
          '#17a2b8'
        ],
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          grid: {
            color: 'rgba(0,0,0,0.1)'
          }
        },
        x: {
          grid: {
            display: false
          }
        }
      }
    }
  });
}

function initDepartementChart(data) {
  const ctx = document.getElementById('departementChart').getContext('2d');
  
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.labels,
      datasets: [
        {
          label: 'Total demandes',
          data: data.datasets.total,
          backgroundColor: 'rgba(111, 66, 193, 0.8)',
          borderColor: '#6f42c1',
          borderWidth: 1,
          yAxisID: 'y'
        },
        {
          label: 'Taux completion (%)',
          data: data.datasets.taux_completion,
          backgroundColor: 'rgba(40, 167, 69, 0.8)',
          borderColor: '#28a745',
          borderWidth: 1,
          yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top'
        }
      },
      scales: {
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          beginAtZero: true,
          title: {
            display: true,
            text: 'Nombre de demandes'
          }
        },
        y1: {
          type: 'linear',
          display: true,
          position: 'right',
          beginAtZero: true,
          max: 100,
          title: {
            display: true,
            text: 'Taux completion (%)'
          },
          grid: {
            drawOnChartArea: false
          }
        },
        x: {
          grid: {
            display: false
          }
        }
      }
    }
  });
}

// ========================================
// FONCTIONS D'ANIMATION ET INTERACTION
// ========================================

function animateKPIs() {
  const kpiNumbers = document.querySelectorAll('.kpi-number');
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const target = entry.target;
        const finalValue = parseFloat(target.textContent);
        
        if (!isNaN(finalValue)) {
          animateNumber(target, 0, finalValue, 1000);
        }
        
        observer.unobserve(target);
      }
    });
  });
  
  kpiNumbers.forEach(number => {
    observer.observe(number);
  });
}

function animateNumber(element, start, end, duration) {
  const range = end - start;
  const increment = range / (duration / 16);
  let current = start;
  
  const timer = setInterval(() => {
    current += increment;
    
    if ((increment > 0 && current >= end) || (increment < 0 && current <= end)) {
      current = end;
      clearInterval(timer);
    }
    
    // Formatter selon le type de nombre
    if (element.parentElement.querySelector('.kpi-label').textContent.includes('%')) {
      element.textContent = Math.round(current) + '%';
    } else {
      element.textContent = Math.round(current);
    }
  }, 16);
}

function setupFilterAutoSubmit() {
  const filterInputs = document.querySelectorAll('#departement, #site, #urgence, #statut, #niveau_validation, #avec_retard');
  let filterTimeout;
  
  filterInputs.forEach(input => {
    input.addEventListener('change', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 300);
    });
  });
  
  // Auto-submit pour les dates avec délai plus long
  const dateInputs = document.querySelectorAll('#date_debut, #date_fin');
  dateInputs.forEach(input => {
    input.addEventListener('change', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 1000);
    });
  });
}

function setupTooltips() {
  // Initialiser les tooltips Bootstrap si disponible
  if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
      return new bootstrap.Tooltip(tooltipTriggerEl);
    });
  }
  
  // Tooltips personnalisés pour les éléments spéciaux
  const kpiCards = document.querySelectorAll('.kpi-card');
  kpiCards.forEach(card => {
    card.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-5px)';
    });
    
    card.addEventListener('mouseleave', function() {
      this.style.transform = 'translateY(0)';
    });
  });
}

// ========================================
// FONCTIONS D'ACTION
// ========================================

function traiterDemandeCritique(demandeId) {
  // Rediriger vers la page de traitement de la demande
  window.location.href = `/interim/demande/${demandeId}/traiter/`;
}

function exporterDashboard() {
  const exportBtn = document.querySelector('[onclick="exporterDashboard()"]');
  if (exportBtn) {
    const icon = exportBtn.querySelector('i');
    const originalClass = icon.className;
    icon.className = 'fas fa-spinner fa-spin';
    exportBtn.disabled = true;
    
    // Simuler l'export
    setTimeout(() => {
      icon.className = originalClass;
      exportBtn.disabled = false;
      
      showNotification('Export du dashboard terminé avec succès !', 'success');
    }, 3000);
  }
}

function afficherAnalyseApprofondie() {
  // Ouvrir une nouvelle fenêtre avec l'analyse approfondie
  window.open('/interim/workflow/analyse-approfondie/', '_blank');
}

function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.className = `alert alert-${type} position-fixed`;
  notification.style.cssText = `
    top: 20px; 
    right: 20px; 
    z-index: 9999; 
    padding: 1rem; 
    border-radius: 8px;
    max-width: 400px;
    animation: slideInRight 0.3s ease-out;
  `;
  
  const icons = {
    'success': 'fas fa-check-circle',
    'error': 'fas fa-exclamation-triangle',
    'warning': 'fas fa-exclamation-circle',
    'info': 'fas fa-info-circle'
  };
  
  notification.innerHTML = `
    <i class="${icons[type] || icons.info}"></i> ${message}
    <button type="button" class="btn-close ms-2" onclick="this.parentElement.remove()"></button>
  `;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    if (notification.parentElement) {
      notification.remove();
    }
  }, 5000);
}

// ========================================
// GESTION DES RACCOURCIS CLAVIER
// ========================================

document.addEventListener('keydown', function(e) {
  // R pour actualiser
  if (e.key === 'r' && e.ctrlKey) {
    e.preventDefault();
    window.location.reload();
  }
  
  // E pour exporter (si disponible)
  if (e.key === 'e' && e.ctrlKey && document.querySelector('[onclick="exporterDashboard()"]')) {
    e.preventDefault();
    exporterDashboard();
  }
  
  // A pour analyse approfondie
  if (e.key === 'a' && e.ctrlKey) {
    e.preventDefault();
    afficherAnalyseApprofondie();
  }
});

// ========================================
// GESTION RESPONSIVE
// ========================================

function handleResponsiveChanges() {
  const isMobile = window.innerWidth <= 768;
  const chartWrappers = document.querySelectorAll('.chart-wrapper');
  
  chartWrappers.forEach(wrapper => {
    if (isMobile) {
      wrapper.style.height = '250px';
    } else {
      wrapper.style.height = '300px';
    }
  });
}

window.addEventListener('resize', handleResponsiveChanges);
handleResponsiveChanges(); // Appel initial

console.log('📊 Scripts dashboard workflow chargés avec succès');

