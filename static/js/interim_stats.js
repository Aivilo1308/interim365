
document.addEventListener('DOMContentLoaded', function() {
  console.log('📊 Page statistiques d\'intérim initialisée');
  
  // Données des graphiques depuis Django
  const interimsMoisData = {{ interims_mois_json|safe }};
  const repartitionSecteurData = {{ repartition_secteur_json|safe }};
  
  // Configuration des couleurs
  const colors = {
    primary: '#28a745',
    secondary: '#20c997',
    info: '#17a2b8',
    warning: '#ffc107',
    danger: '#dc3545',
    light: '#f8f9fa',
    dark: '#343a40'
  };
  
  // Graphique évolution mensuelle
  if (interimsMoisData && interimsMoisData.length > 0) {
    const ctx1 = document.getElementById('chartEvolutionMensuelle');
    if (ctx1) {
      new Chart(ctx1, {
        type: 'line',
        data: {
          labels: interimsMoisData.map(item => {
            const date = new Date(item.mois);
            return date.toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });
          }),
          datasets: [{
            label: 'Demandes d\'intérim',
            data: interimsMoisData.map(item => item.count),
            borderColor: colors.primary,
            backgroundColor: colors.primary + '20',
            borderWidth: 3,
            fill: true,
            tension: 0.4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              ticks: {
                stepSize: 1
              }
            }
          },
          plugins: {
            legend: {
              display: false
            }
          }
        }
      });
    }
  }
  
  // Graphique répartition par secteur
  if (repartitionSecteurData && repartitionSecteurData.length > 0) {
    const ctx2 = document.getElementById('chartRepartitionSecteur');
    if (ctx2) {
      const colors_array = [
        colors.primary, colors.info, colors.warning, colors.danger, colors.secondary,
        '#6f42c1', '#fd7e14', '#e83e8c', '#6c757d', '#007bff'
      ];
      
      new Chart(ctx2, {
        type: 'doughnut',
        data: {
          labels: repartitionSecteurData.map(item => item.poste__departement__nom || 'Non défini'),
          datasets: [{
            data: repartitionSecteurData.map(item => item.count),
            backgroundColor: colors_array.slice(0, repartitionSecteurData.length),
            borderWidth: 2,
            borderColor: '#fff'
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'bottom',
              labels: {
                padding: 20,
                usePointStyle: true
              }
            }
          }
        }
      });
    }
  }
  
  // Animation d'entrée progressive pour les cartes
  const overviewCards = document.querySelectorAll('.overview-card');
  overviewCards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(30px)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.6s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, index * 150);
  });
  
  // Animation des stats cards
  const statCards = document.querySelectorAll('.stat-card');
  statCards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateX(-20px)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateX(0)';
    }, 500 + (index * 100));
  });
  
  // Animation des KPI cards
  const kpiCards = document.querySelectorAll('.kpi-card');
  kpiCards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'scale(0.9)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'scale(1)';
    }, 1000 + (index * 200));
  });
  
  // Compteur animé pour les chiffres
  const animateNumbers = () => {
    const numbers = document.querySelectorAll('.overview-number, .stat-number, .kpi-value');
    numbers.forEach(number => {
      const text = number.textContent;
      const value = parseFloat(text);
      
      if (!isNaN(value) && value > 0) {
        let current = 0;
        const increment = Math.ceil(value / 30);
        const suffix = text.replace(value.toString(), '');
        
        const timer = setInterval(() => {
          current += increment;
          if (current >= value) {
            current = value;
            clearInterval(timer);
          }
          
          if (suffix.includes('%')) {
            number.textContent = Math.floor(current) + '%';
          } else if (suffix.includes('/')) {
            number.textContent = (current).toFixed(1) + suffix.substring(suffix.indexOf('/'));
          } else {
            number.textContent = Math.floor(current) + suffix;
          }
        }, 50);
      }
    });
  };
  
  // Démarrer l'animation des chiffres après un délai
  setTimeout(animateNumbers, 1500);
  
  // Animation des jauges KPI
  const animateGauges = () => {
    const gauges = document.querySelectorAll('.gauge-fill');
    gauges.forEach((gauge, index) => {
      setTimeout(() => {
        const width = gauge.style.width;
        gauge.style.width = '0%';
        gauge.style.transition = 'width 1.5s ease-out';
        
        setTimeout(() => {
          gauge.style.width = width;
        }, 100);
      }, index * 300);
    });
  };
  
  setTimeout(animateGauges, 2000);
  
  // Animation des barres géographiques
  const animateGeoBars = () => {
    const bars = document.querySelectorAll('.geo-fill');
    bars.forEach((bar, index) => {
      setTimeout(() => {
        const width = bar.style.width;
        bar.style.width = '0%';
        
        setTimeout(() => {
          bar.style.width = width;
        }, 100);
      }, index * 100);
    });
  };
  
  setTimeout(animateGeoBars, 2500);
  
  console.log('✅ Animations et graphiques initialisés');
});

// Fonction pour définir une période prédéfinie
function setPeriodePredefinie(jours) {
  const dateFin = new Date();
  const dateDebut = new Date();
  dateDebut.setDate(dateFin.getDate() - parseInt(jours));
  
  document.getElementById('date_debut').value = dateDebut.toISOString().split('T')[0];
  document.getElementById('date_fin').value = dateFin.toISOString().split('T')[0];
  
  // Soumettre automatiquement le formulaire
  document.querySelector('.periode-form').submit();
}

// Fonction d'export des statistiques
function exportStats() {
  const exportBtn = document.querySelector('[onclick="exportStats()"]');
  if (exportBtn) {
    const icon = exportBtn.querySelector('i');
    const originalClass = icon.className;
    icon.className = 'fas fa-spinner fa-spin';
    exportBtn.disabled = true;
  }
  
  // Simuler l'export (à remplacer par l'appel réel)
  setTimeout(() => {
    // Restaurer le bouton
    if (exportBtn) {
      const icon = exportBtn.querySelector('i');
      icon.className = 'fas fa-file-export';
      exportBtn.disabled = false;
    }
    
    // Notification de succès
    showNotification('Export terminé avec succès !', 'success');
    
  }, 2000);
}

// Fonction pour afficher les notifications
function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.className = `alert alert-${type}`;
  notification.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 9999;
    padding: 1rem 1.5rem;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    animation: slideInRight 0.3s ease;
  `;
  
  const colors = {
    success: { bg: '#d4edda', color: '#155724', border: '#c3e6cb' },
    info: { bg: '#d1ecf1', color: '#0c5460', border: '#bee5eb' },
    warning: { bg: '#fff3cd', color: '#856404', border: '#ffeaa7' },
    danger: { bg: '#f8d7da', color: '#721c24', border: '#f5c6cb' }
  };
  
  const colorScheme = colors[type] || colors.info;
  notification.style.backgroundColor = colorScheme.bg;
  notification.style.color = colorScheme.color;
  notification.style.border = `1px solid ${colorScheme.border}`;
  
  const icon = type === 'success' ? 'check-circle' : 
              type === 'warning' ? 'exclamation-triangle' :
              type === 'danger' ? 'times-circle' : 'info-circle';
  
  notification.innerHTML = `<i class="fas fa-${icon}"></i> ${message}`;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    notification.style.animation = 'slideOutRight 0.3s ease';
    setTimeout(() => {
      notification.remove();
    }, 300);
  }, 3000);
}

// Styles CSS pour les animations
const style = document.createElement('style');
style.textContent = `
  @keyframes slideInRight {
    from {
      transform: translateX(100%);
      opacity: 0;
    }
    to {
      transform: translateX(0);
      opacity: 1;
    }
  }
  
  @keyframes slideOutRight {
    from {
      transform: translateX(0);
      opacity: 1;
    }
    to {
      transform: translateX(100%);
      opacity: 0;
    }
  }
`;

document.head.appendChild(style);

// Initialisation des raccourcis clavier
document.addEventListener('keydown', function(e) {
  // Ctrl+P pour imprimer
  if (e.ctrlKey && e.key === 'p') {
    e.preventDefault();
    window.print();
  }
  
  // Ctrl+E pour exporter
  if (e.ctrlKey && e.key === 'e') {
    e.preventDefault();
    exportStats();
  }
});

console.log('✅ Statistiques d\'intérim - Toutes les fonctionnalités chargées');

