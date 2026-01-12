<!-- ✅ BOOTSTRAP 5.3 JS via CDN -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js" integrity="sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV8Qyq46cDfL" crossorigin="anonymous">


document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Interface de validation avec liens directs d\'escalade');

  // Variables globales
  window.demandesSelectionnees = [];
  
  // Récupérer le token CSRF
  function getCSRFToken() {
    let token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    
    if (!token) {
      token = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
    }
    
    if (!token) {
      const cookieName = 'csrftoken=';
      const cookies = document.cookie.split(';');
      for (let cookie of cookies) {
        cookie = cookie.trim();
        if (cookie.indexOf(cookieName) === 0) {
          token = cookie.substring(cookieName.length);
          break;
        }
      }
    }
    
    console.log('🔐 Token CSRF:', token ? 'Trouvé (' + token.substring(0, 10) + '...)' : 'MANQUANT');
    return token;
  }

  // Fonction pour toggle select all
  window.toggleSelectAll = function(checkbox) {
    console.log('📋 Toggle select all:', checkbox.checked);
    
    const checkboxes = document.querySelectorAll('.demande-checkbox');
    checkboxes.forEach(cb => {
      cb.checked = checkbox.checked;
      
      const id = cb.value;
      if (checkbox.checked) {
        if (!window.demandesSelectionnees.includes(id)) {
          window.demandesSelectionnees.push(id);
        }
      } else {
        const index = window.demandesSelectionnees.indexOf(id);
        if (index > -1) {
          window.demandesSelectionnees.splice(index, 1);
        }
      }
    });
    
    updateSelectionCount();
    updateValidationMasseVisibility();
  };

  // Fonction pour mettre à jour le compteur
  window.updateSelectionCount = function() {
    const count = window.demandesSelectionnees.length;
    const badge = document.getElementById('nombreSelectionnes');
    if (badge) {
      badge.textContent = `${count} sélectionnée(s)`;
    }
    
    console.log('📊 Sélections mises à jour:', count, window.demandesSelectionnees);
    
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.demande-checkbox');
    
    if (selectAll && checkboxes.length > 0) {
      const allChecked = count === checkboxes.length;
      const someChecked = count > 0;
      
      selectAll.checked = allChecked;
      selectAll.indeterminate = someChecked && !allChecked;
    }
    
    updateValidationMasseVisibility();
  };

  // Fonction pour afficher/masquer la section validation masse
  function updateValidationMasseVisibility() {
    const validationMasse = document.getElementById('validationMasse');
    if (validationMasse) {
      if (window.demandesSelectionnees.length > 0) {
        validationMasse.classList.add('show');
        validationMasse.style.display = 'block';
      } else {
        validationMasse.classList.remove('show');
        validationMasse.style.display = 'none';
      }
    }
  }

  // Gestionnaire pour les checkboxes individuelles
  document.addEventListener('change', function(e) {
    if (e.target.classList.contains('demande-checkbox')) {
      const id = e.target.value;
      
      if (e.target.checked) {
        if (!window.demandesSelectionnees.includes(id)) {
          window.demandesSelectionnees.push(id);
        }
      } else {
        const index = window.demandesSelectionnees.indexOf(id);
        if (index > -1) {
          window.demandesSelectionnees.splice(index, 1);
        }
      }
      
      updateSelectionCount();
    }
  });

  // ================================================================
  // FONCTIONS DE VALIDATION EN MASSE
  // ================================================================

  // Validation en masse
  window.validerEnMasse = function(action) {
    console.log('🎯 Validation en masse demandée:', action);
    console.log('📋 Demandes sélectionnées:', window.demandesSelectionnees);
    
    if (window.demandesSelectionnees.length === 0) {
      alert('Veuillez sélectionner au moins une demande');
      return;
    }
    
    if (window.demandesSelectionnees.length > 20) {
      alert('Maximum 20 demandes à la fois');
      return;
    }
    
    const modal = document.getElementById('modalValidationMasse');
    if (!modal) {
      console.error('❌ Modal validation masse non trouvée');
      alert('Erreur: Modal non trouvée');
      return;
    }

    const modalHeader = document.getElementById('modalMasseHeader');
    const modalTitre = document.getElementById('modalMasseTitre');
    const btnConfirmer = document.getElementById('btnConfirmerMasse');
    const listeDemandes = document.getElementById('listeDemandes');
    
    if (action === 'APPROUVER') {
      if (modalHeader) modalHeader.className = 'modal-header bg-success text-white';
      if (modalTitre) modalTitre.innerHTML = '<i class="fas fa-check-double"></i> Approuver en masse';
      if (btnConfirmer) {
        btnConfirmer.className = 'btn btn-success';
        btnConfirmer.innerHTML = '<i class="fas fa-check"></i> Confirmer approbation en masse';
      }
    } else {
      if (modalHeader) modalHeader.className = 'modal-header bg-danger text-white';
      if (modalTitre) modalTitre.innerHTML = '<i class="fas fa-times-circle"></i> Refuser en masse';
      if (btnConfirmer) {
        btnConfirmer.className = 'btn btn-danger';
        btnConfirmer.innerHTML = '<i class="fas fa-times"></i> Confirmer refus en masse';
      }
    }
    
    if (listeDemandes) {
      listeDemandes.textContent = `${window.demandesSelectionnees.length} demande(s) sélectionnée(s)`;
    }
    
    const actionInput = document.getElementById('actionMasse');
    if (actionInput) {
      actionInput.value = action;
    }
    
    const commentaireInput = document.getElementById('commentaireMasse');
    if (commentaireInput) {
      commentaireInput.value = '';
      commentaireInput.focus();
    }
    
    try {
      const modalInstance = new bootstrap.Modal(modal);
      modalInstance.show();
    } catch (error) {
      console.error('❌ Erreur ouverture modal:', error);
      alert('Erreur ouverture modal: ' + error.message);
    }
  };

  // Confirmation validation en masse
  window.confirmerValidationMasse = function() {
    console.log('🚀 Confirmation validation en masse');
    
    const commentaire = document.getElementById('commentaireMasse')?.value?.trim();
    const action = document.getElementById('actionMasse')?.value;
    
    if (!commentaire) {
      alert('Le commentaire est obligatoire');
      document.getElementById('commentaireMasse')?.focus();
      return;
    }
    
    if (!action || !['APPROUVER', 'REFUSER'].includes(action)) {
      console.error('❌ Action invalide:', action);
      alert('Action invalide: ' + action);
      return;
    }
    
    if (!window.demandesSelectionnees || window.demandesSelectionnees.length === 0) {
      alert('Aucune demande sélectionnée');
      return;
    }
    
    const token = getCSRFToken();
    if (!token) {
      alert('Token de sécurité manquant. Rechargez la page.');
      return;
    }
    
    showLoading();
    
    const formData = new FormData();
    formData.append('action_masse', action);
    formData.append('commentaire_masse', commentaire);
    formData.append('csrfmiddlewaretoken', token);
    
    window.demandesSelectionnees.forEach(id => {
      formData.append('demandes_ids[]', id);
    });
    
    console.log('📤 Envoi requête validation masse:');
    console.log('  - URL:', '/interim/api/validation/masse/');
    console.log('  - Action:', action);
    console.log('  - Commentaire:', commentaire.substring(0, 50) + '...');
    console.log('  - IDs:', window.demandesSelectionnees);
    console.log('  - Token CSRF:', token ? 'Présent' : 'MANQUANT');
    
    fetch('/interim/api/validation/masse/', {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': token
      }
    })
    .then(response => {
      console.log('📡 Réponse serveur:', response.status, response.statusText);
      
      if (response.status === 403) {
        throw new Error('Erreur CSRF - Token invalide ou expiré');
      }
      if (response.status === 404) {
        throw new Error('URL non trouvée - Vérifiez la configuration des URLs');
      }
      if (response.status === 500) {
        throw new Error('Erreur serveur interne - Vérifiez les logs Django');
      }
      if (!response.ok) {
        throw new Error(`Erreur HTTP: ${response.status} ${response.statusText}`);
      }
      
      return response.json();
    })
    .then(data => {
      console.log('✅ Réponse JSON:', data);
      
      if (data.success) {
        const modal = document.getElementById('modalValidationMasse');
        if (modal) {
          try {
            bootstrap.Modal.getInstance(modal)?.hide();
          } catch (error) {
            console.log('Info: Modal déjà fermée');
          }
        }
        
        showToast('Validation en masse terminée', data.message, 'success');
        
        window.demandesSelectionnees = [];
        document.querySelectorAll('.demande-checkbox').forEach(cb => cb.checked = false);
        const selectAll = document.getElementById('selectAll');
        if (selectAll) selectAll.checked = false;
        updateSelectionCount();
        
        setTimeout(() => {
          window.location.reload();
        }, 2000);
        
      } else {
        console.error('❌ Erreur métier:', data.error);
        showToast('Erreur', data.error || 'Erreur inconnue du serveur', 'error');
      }
    })
    .catch(error => {
      console.error('💥 Erreur complète:', error);
      
      let message = 'Erreur de communication avec le serveur';
      if (error.message.includes('CSRF')) {
        message = 'Erreur de sécurité. Rechargez la page.';
      } else if (error.message.includes('404')) {
        message = 'Configuration incorrecte. Contactez l\'administrateur.';
      } else if (error.message.includes('500')) {
        message = 'Erreur serveur interne. Vérifiez les logs Django.';
      } else {
        message = 'Erreur: ' + error.message;
      }
      
      showToast('Erreur', message, 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  // ================================================================
  // FONCTIONS UTILITAIRES
  // ================================================================

  // Voir historique normal (fonction simple car les modals d'escalade ont été supprimées)
  window.voirHistorique = function(demandeId) {
    console.log('📜 Historique pour demande:', demandeId);
    // Cette fonction peut être implémentée selon vos besoins
    showToast('Information', 'Fonctionnalité en cours de développement', 'info');
  };

  // Fonctions utilitaires
  window.showLoading = function() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
      overlay.style.display = 'flex';
    }
  };
  
  window.hideLoading = function() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
      overlay.style.display = 'none';
    }
  };
  
  window.showToast = function(titre, message, type = 'info') {
    const toastContainer = document.querySelector('.toast-container');
    if (!toastContainer) {
      console.error('❌ Container toast non trouvé');
      alert(titre + ': ' + message);
      return;
    }
    
    const toastId = 'toast_' + Date.now();
    
    const bgClass = {
      'success': 'bg-success',
      'error': 'bg-danger',
      'warning': 'bg-warning',
      'info': 'bg-info'
    }[type] || 'bg-info';
    
    const icon = {
      'success': 'fa-check-circle',
      'error': 'fa-exclamation-circle',
      'warning': 'fa-exclamation-triangle',
      'info': 'fa-info-circle'
    }[type] || 'fa-info-circle';
    
    const toastHtml = `
      <div class="toast ${bgClass} text-white" id="${toastId}" role="alert">
        <div class="toast-header ${bgClass} text-white">
          <i class="fas ${icon} me-2"></i>
          <strong class="me-auto">${titre}</strong>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
        </div>
        <div class="toast-body">
          ${message}
        </div>
      </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    
    const toastElement = document.getElementById(toastId);
    try {
      const toast = new bootstrap.Toast(toastElement, {
        autohide: true,
        delay: type === 'error' ? 8000 : 5000
      });
      toast.show();
      
      toastElement.addEventListener('hidden.bs.toast', function() {
        this.remove();
      });
    } catch (error) {
      console.error('❌ Erreur création toast:', error);
      alert(titre + ': ' + message);
    }
  };

  // Fonction de test pour la validation en masse
  window.testValidationMasse = function() {
    console.log('🧪 Test des fonctions de validation en masse');
    
    const token = getCSRFToken();
    console.log('1. Token CSRF:', token ? '✅ Présent' : '❌ Manquant');
    
    console.log('2. Variables globales:', {
      demandesSelectionnees: window.demandesSelectionnees,
      length: window.demandesSelectionnees?.length
    });
    
    const elements = {
      modalValidationMasse: !!document.getElementById('modalValidationMasse'),
      actionMasse: !!document.getElementById('actionMasse'),
      commentaireMasse: !!document.getElementById('commentaireMasse'),
      selectAll: !!document.getElementById('selectAll'),
      checkboxes: document.querySelectorAll('.demande-checkbox').length
    };
    console.log('3. Éléments DOM:', elements);
    
    const fonctions = {
      validerEnMasse: typeof window.validerEnMasse,
      confirmerValidationMasse: typeof window.confirmerValidationMasse,
      updateSelectionCount: typeof window.updateSelectionCount,
      showToast: typeof window.showToast
    };
    console.log('4. Fonctions:', fonctions);
    
    console.log('5. Bootstrap Modal:', typeof bootstrap?.Modal);
    
    const problemes = [];
    if (!token) problemes.push('Token CSRF manquant');
    if (!elements.modalValidationMasse) problemes.push('Modal manquante');
    if (elements.checkboxes === 0) problemes.push('Aucune checkbox trouvée');
    if (typeof bootstrap?.Modal !== 'function') problemes.push('Bootstrap non chargé');
    
    if (problemes.length === 0) {
      console.log('✅ Tous les tests passent - Validation en masse OK');
    } else {
      console.log('❌ Problèmes détectés:', problemes);
    }
    
    return problemes.length === 0;
  };

  // Initialisation
  updateValidationMasseVisibility();
  
  console.log('✅ Interface de validation avec liens directs initialisée');
  console.log('🔧 Fonctionnalités disponibles:');
  console.log('   • Validation en masse (modal)');
  console.log('   • Liens directs vers escalade');
  console.log('   • Liens directs vers vérification escalade');
  console.log('   • Liens directs vers historique escalades');
  console.log('🧪 Test disponible: testValidationMasse()');
});

