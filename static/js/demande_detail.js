document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation du détail de demande avec propositions');

  // Actualisation automatique du statut
  const refreshStatus = () => {
    fetch(`${URLS.apiWorkflowStatus}${DEMANDE_ID}/`)
      .then(response => response.json())
      .then(data => {
        if (data.status !== DEMANDE_STATUT) {
          showNotification('Le statut de la demande a été mis à jour', 'info');
        }
      })
      .catch(error => {
        console.log('Erreur lors de la vérification du statut:', error);
      });
  };

  // Vérifier le statut toutes les 30 secondes
  setInterval(refreshStatus, 30000);

  // Raccourcis clavier
  document.addEventListener('keydown', function(e) {
    if (e.ctrlKey) {
      switch(e.key) {
        case 'p':
          e.preventDefault();
          window.print();
          break;
        case 'h':
          e.preventDefault();
          window.location.href = URLS.historiqueInterim;
          break;
        case 'n':
          if (PEUT_PROPOSER_CANDIDAT) {
            e.preventDefault();
            ouvrirModalProposition();
          }
          break;
      }
    }
  });

  // Initialisation du modal de proposition si autorisé
  if (PEUT_PROPOSER_CANDIDAT) {
    const modalProposition = document.getElementById('modalProposition');
    const formProposition = document.getElementById('formProposition');
    
    if (modalProposition) {
      // Fermer le modal en cliquant à l'extérieur
      modalProposition.addEventListener('click', function(e) {
        if (e.target === this) {
          fermerModalProposition();
        }
      });
    }
    
    if (formProposition) {
      // Gérer la soumission du formulaire de proposition
      formProposition.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const formData = new FormData(this);
        
        fetch(this.action, {
          method: 'POST',
          body: formData,
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            showNotification(data.message, 'success');
            fermerModalProposition();
            // Recharger la page pour afficher la nouvelle proposition
            setTimeout(() => window.location.reload(), 1000);
          } else {
            showNotification(data.error || 'Erreur lors de la proposition', 'error');
          }
        })
        .catch(error => {
          console.error('Erreur:', error);
          showNotification('Erreur de communication avec le serveur', 'error');
        });
      });
    }
  }

  console.log(`✅ Détail de demande initialisé pour la demande ${DEMANDE_NUMERO}`);
});

// ================================================================
// FONCTIONS POUR LE MODAL DE PROPOSITION
// ================================================================

function ouvrirModalProposition() {
  const modal = document.getElementById('modalProposition');
  if (modal) {
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }
}

function fermerModalProposition() {
  const modal = document.getElementById('modalProposition');
  const form = document.getElementById('formProposition');
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
  }
  if (form) {
    form.reset();
  }
}

// ================================================================
// FONCTION DE NOTIFICATION
// ================================================================

function showNotification(message, type = 'info') {
  console.log(`📢 Notification ${type}: ${message}`);
  
  const notification = document.createElement('div');
  notification.className = `alert alert-${type}`;
  notification.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 350px; animation: slideIn 0.3s ease;';
  notification.innerHTML = `
    <i class="fas fa-info-circle"></i>
    <div class="alert-content">${message}</div>
  `;
  
  document.body.appendChild(notification);
  
  // Supprimer après 5 secondes
  setTimeout(() => {
    if (notification.parentNode) {
      notification.style.animation = 'slideOut 0.3s ease';
      setTimeout(() => {
        if (notification.parentNode) {
          notification.parentNode.removeChild(notification);
        }
      }, 300);
    }
  }, 5000);
}

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
