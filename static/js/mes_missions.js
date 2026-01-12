
document.addEventListener('DOMContentLoaded', function() {
  console.log('💼 Page mes missions d\'intérim initialisée');
  
  // Animation d'entrée progressive pour les missions
  const missionItems = document.querySelectorAll('.mission-timeline-item');
  missionItems.forEach((item, index) => {
    item.style.opacity = '0';
    item.style.transform = 'translateX(-20px)';
    
    setTimeout(() => {
      item.style.transition = 'all 0.5s ease';
      item.style.opacity = '1';
      item.style.transform = 'translateX(0)';
    }, index * 150);
  });
  
  // Animation des statistiques
  animerStatistiques();
  
  // Auto-submit du formulaire de filtres avec debounce
  let filterTimeout;
  const filterInputs = document.querySelectorAll('#recherche, #statut, #date_debut, #date_fin, #ordre');
  
  filterInputs.forEach(input => {
    input.addEventListener('input', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 500);
    });
    
    input.addEventListener('change', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 200);
    });
  });
  
  // Effet de hover pour les missions
  const missionContents = document.querySelectorAll('.mission-content');
  missionContents.forEach(content => {
    content.addEventListener('mouseenter', function() {
      this.style.transform = 'scale(1.01)';
    });
    
    content.addEventListener('mouseleave', function() {
      this.style.transform = 'scale(1)';
    });
  });
  
  console.log('✅ Interactions missions initialisées');
});

// Animation des statistiques
function animerStatistiques() {
  const statNumbers = document.querySelectorAll('.stat-number');
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const element = entry.target;
        const finalValue = parseInt(element.textContent) || 0;
        
        if (finalValue > 0) {
          animerCompteur(element, finalValue);
        }
        
        observer.unobserve(element);
      }
    });
  });
  
  statNumbers.forEach(number => observer.observe(number));
}

// Animation du compteur
function animerCompteur(element, finalValue) {
  let currentValue = 0;
  const increment = Math.ceil(finalValue / 20);
  
  const timer = setInterval(() => {
    currentValue += increment;
    if (currentValue >= finalValue) {
      currentValue = finalValue;
      clearInterval(timer);
    }
    
    element.textContent = currentValue;
  }, 50);
}

// Fonction pour voir les détails d'une mission
function voirDetailsMission(missionId) {
  console.log('Affichage des détails de la mission:', missionId);
  // Implémentation future : modal ou redirection vers page détaillée
}

// Fonction pour accepter une mission
function accepterMission(missionId) {
  const confirmation = confirm('Êtes-vous sûr de vouloir accepter cette mission ?');
  if (confirmation) {
    console.log('Acceptation de la mission:', missionId);
    
    // Simuler l'appel API
    const button = document.querySelector(`[onclick="accepterMission('${missionId}')"]`);
    if (button) {
      const hideLoading = showLoading(button);
      
      setTimeout(() => {
        hideLoading();
        
        // Notification de succès
        showNotification('Mission acceptée avec succès !', 'success');
        
        // Recharger la page après un délai
        setTimeout(() => {
          window.location.reload();
        }, 1500);
      }, 2000);
    }
  }
}

// Fonction pour refuser une mission
function refuserMission(missionId) {
  const raison = prompt('Veuillez indiquer la raison du refus (optionnel) :');
  if (raison !== null) { // L'utilisateur n'a pas annulé
    console.log('Refus de la mission:', missionId, 'Raison:', raison);
    
    // Simuler l'appel API
    const button = document.querySelector(`[onclick="refuserMission('${missionId}')"]`);
    if (button) {
      const hideLoading = showLoading(button);
      
      setTimeout(() => {
        hideLoading();
        
        // Notification de succès
        showNotification('Mission refusée. Le demandeur sera notifié.', 'warning');
        
        // Recharger la page après un délai
        setTimeout(() => {
          window.location.reload();
        }, 1500);
      }, 2000);
    }
  }
}

// Fonction pour signaler un problème
function signalerProbleme(missionId) {
  const probleme = prompt('Décrivez le problème rencontré :');
  if (probleme && probleme.trim()) {
    console.log('Signalement problème mission:', missionId, 'Problème:', probleme);
    
    // Simuler l'appel API
    const button = document.querySelector(`[onclick="signalerProbleme('${missionId}')"]`);
    if (button) {
      const hideLoading = showLoading(button);
      
      setTimeout(() => {
        hideLoading();
        
        // Notification de succès
        showNotification('Problème signalé. L\'équipe sera notifiée.', 'info');
      }, 1500);
    }
  }
}

// Fonction pour évaluer une mission
function evaluerMission(missionId) {
  console.log('Évaluation de la mission:', missionId);
  
  // Créer une modal d'évaluation
  const modal = document.createElement('div');
  modal.className = 'evaluation-modal';
  modal.innerHTML = `
    <div class="evaluation-modal-content">
      <div class="evaluation-modal-header">
        <h3>Évaluer la mission</h3>
        <button onclick="fermerModalEvaluation()" class="btn-close">&times;</button>
      </div>
      <div class="evaluation-modal-body">
        <div class="evaluation-form">
          <div class="form-group">
            <label>Note globale (1-5 étoiles)</label>
            <div class="stars-rating" id="stars-rating">
              <span class="star" data-rating="1">★</span>
              <span class="star" data-rating="2">★</span>
              <span class="star" data-rating="3">★</span>
              <span class="star" data-rating="4">★</span>
              <span class="star" data-rating="5">★</span>
            </div>
          </div>
          <div class="form-group">
            <label>Commentaire (optionnel)</label>
            <textarea id="evaluation-commentaire" placeholder="Votre retour sur cette mission..."></textarea>
          </div>
          <div class="evaluation-actions">
            <button onclick="soumettreEvaluation('${missionId}')" class="btn btn-primary">Envoyer l'évaluation</button>
            <button onclick="fermerModalEvaluation()" class="btn btn-outline">Annuler</button>
          </div>
        </div>
      </div>
    </div>
  `;
  
  // Styles de la modal
  modal.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    animation: fadeIn 0.3s ease;
  `;
  
  document.body.appendChild(modal);
  
  // Gestion des étoiles
  const stars = modal.querySelectorAll('.star');
  let selectedRating = 0;
  
  stars.forEach(star => {
    star.addEventListener('click', function() {
      selectedRating = parseInt(this.dataset.rating);
      updateStars(stars, selectedRating);
    });
    
    star.addEventListener('mouseenter', function() {
      const rating = parseInt(this.dataset.rating);
      updateStars(stars, rating);
    });
  });
  
  modal.addEventListener('mouseleave', function() {
    updateStars(stars, selectedRating);
  });
}

// Mettre à jour l'affichage des étoiles
function updateStars(stars, rating) {
  stars.forEach((star, index) => {
    if (index < rating) {
      star.style.color = '#ffc107';
    } else {
      star.style.color = '#dee2e6';
    }
  });
}

// Fermer la modal d'évaluation
function fermerModalEvaluation() {
  const modal = document.querySelector('.evaluation-modal');
  if (modal) {
    modal.remove();
  }
}

// Soumettre l'évaluation
function soumettreEvaluation(missionId) {
  const rating = document.querySelectorAll('.star[style*="rgb(255, 193, 7)"]').length;
  const commentaire = document.getElementById('evaluation-commentaire').value;
  
  if (rating === 0) {
    alert('Veuillez sélectionner une note.');
    return;
  }
  
  console.log('Évaluation soumise:', { missionId, rating, commentaire });
  
  // Simuler l'envoi
  setTimeout(() => {
    fermerModalEvaluation();
    showNotification('Évaluation envoyée avec succès !', 'success');
  }, 1000);
}

// Fonction d'impression d'une mission
function imprimerMission(missionId) {
  console.log('Impression de la mission:', missionId);
  window.print();
}

// Fonction d'export des missions
function exporterMissions() {
  const exportBtn = document.querySelector('[onclick="exporterMissions()"]');
  if (exportBtn) {
    const hideLoading = showLoading(exportBtn);
    
    setTimeout(() => {
      hideLoading();
      showNotification('Export terminé avec succès !', 'success');
    }, 2000);
  }
}

// Utilitaires
function showLoading(button) {
  const icon = button.querySelector('i');
  const originalClass = icon.className;
  icon.className = 'fas fa-spinner fa-spin';
  button.disabled = true;
  
  return function hideLoading() {
    icon.className = originalClass;
    button.disabled = false;
  };
}

function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 9999;
    padding: 1rem;
    border-radius: 8px;
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    animation: slideInRight 0.3s ease;
    max-width: 400px;
  `;
  
  const colors = {
    success: { bg: '#d4edda', color: '#155724', border: '#c3e6cb' },
    warning: { bg: '#fff3cd', color: '#856404', border: '#ffeaa7' },
    info: { bg: '#d1ecf1', color: '#0c5460', border: '#bee5eb' },
    error: { bg: '#f8d7da', color: '#721c24', border: '#f5c6cb' }
  };
  
  const style = colors[type] || colors.info;
  notification.style.backgroundColor = style.bg;
  notification.style.color = style.color;
  notification.style.border = `1px solid ${style.border}`;
  
  const icons = {
    success: 'fas fa-check-circle',
    warning: 'fas fa-exclamation-triangle',
    info: 'fas fa-info-circle',
    error: 'fas fa-times-circle'
  };
  
  notification.innerHTML = `<i class="${icons[type] || icons.info}"></i> ${message}`;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    notification.style.animation = 'slideOutRight 0.3s ease';
    setTimeout(() => notification.remove(), 300);
  }, 4000);
}

// Gestion des raccourcis clavier
document.addEventListener('keydown', function(e) {
  // Échap pour fermer les modals
  if (e.key === 'Escape') {
    fermerModalEvaluation();
  }
  
  // Ctrl+P pour imprimer
  if (e.ctrlKey && e.key === 'p') {
    e.preventDefault();
    window.print();
  }
  
  // Ctrl+E pour exporter
  if (e.ctrlKey && e.key === 'e') {
    e.preventDefault();
    exporterMissions();
  }
});

// Filtrage rapide par statut
function filtrerParStatut(statut) {
  const statutSelect = document.getElementById('statut');
  if (statutSelect) {
    statutSelect.value = statut;
    statutSelect.form.submit();
  }
}

// Styles CSS pour les modals et notifications
const styleSheet = document.createElement('style');
styleSheet.innerHTML = `
  @keyframes fadeIn {
    from { opacity: 0; transform: scale(0.9); }
    to { opacity: 1; transform: scale(1); }
  }
  
  @keyframes fadeOut {
    from { opacity: 1; transform: scale(1); }
    to { opacity: 0; transform: scale(0.9); }
  }
  
  @keyframes slideInRight {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  
  @keyframes slideOutRight {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
  }
  
  .evaluation-modal-content {
    background: white;
    border-radius: 8px;
    padding: 2rem;
    max-width: 500px;
    width: 90%;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }
  
  .evaluation-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid #dee2e6;
    padding-bottom: 1rem;
  }
  
  .evaluation-modal-header h3 {
    margin: 0;
    color: #495057;
  }
  
  .btn-close {
    background: none;
    border: none;
    font-size: 1.5rem;
    color: #6c757d;
    cursor: pointer;
    padding: 0;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .btn-close:hover {
    color: #495057;
  }
  
  .evaluation-form {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  
  .evaluation-form .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  
  .evaluation-form label {
    font-weight: 600;
    color: #495057;
  }
  
  .stars-rating {
    display: flex;
    gap: 0.25rem;
    font-size: 2rem;
  }
  
  .star {
    cursor: pointer;
    color: #dee2e6;
    transition: color 0.2s ease;
  }
  
  .star:hover {
    color: #ffc107;
  }
  
  #evaluation-commentaire {
    padding: 0.75rem;
    border: 1px solid #ced4da;
    border-radius: 4px;
    font-size: 1rem;
    font-family: inherit;
    resize: vertical;
    min-height: 100px;
  }
  
  #evaluation-commentaire:focus {
    outline: 0;
    border-color: #fd7e14;
    box-shadow: 0 0 0 0.2rem rgba(253, 126, 20, 0.25);
  }
  
  .evaluation-actions {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    margin-top: 1rem;
  }
  
  .notification {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 500;
  }
  
  .notification i {
    font-size: 1.1rem;
  }
`;
document.head.appendChild(styleSheet);

