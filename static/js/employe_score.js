
document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation de la page score employé');

  // ================================================================
  // GESTION DES ONGLETS
  // ================================================================

  const tabButtons = document.querySelectorAll('.tab-button');
  const tabContents = document.querySelectorAll('.tab-content');

  function switchTab(targetTabId) {
    // Désactiver tous les onglets
    tabButtons.forEach(btn => btn.classList.remove('active'));
    tabContents.forEach(content => content.classList.remove('active'));

    // Activer l'onglet cible
    const targetButton = document.querySelector(`[data-tab="${targetTabId}"]`);
    const targetContent = document.getElementById(`tab-${targetTabId}`);

    if (targetButton && targetContent) {
      targetButton.classList.add('active');
      targetContent.classList.add('active');
      
      // Sauvegarder l'onglet actif
      localStorage.setItem('activeScoreTab', targetTabId);
      
      console.log(`📑 Onglet activé: ${targetTabId}`);
    }
  }

  // Event listeners pour les boutons d'onglets
  tabButtons.forEach(button => {
    button.addEventListener('click', function() {
      const tabId = this.dataset.tab;
      switchTab(tabId);
    });
  });

  // Restaurer l'onglet actif
  const savedTab = localStorage.getItem('activeScoreTab');
  if (savedTab && document.getElementById(`tab-${savedTab}`)) {
    switchTab(savedTab);
  }

  // ================================================================
  // PROPOSITION DE CANDIDAT
  // ================================================================

  window.proposerCandidat = function() {
    const modal = document.getElementById('modalProposerCandidat');
    if (modal && typeof bootstrap !== 'undefined') {
      const bsModal = new bootstrap.Modal(modal);
      bsModal.show();
      
      // Focus sur la justification
      setTimeout(() => {
        const justificationInput = document.getElementById('justification');
        if (justificationInput) {
          justificationInput.focus();
        }
      }, 500);
    }
  };

  window.soumettreProposition = async function() {
    const form = document.getElementById('formProposerCandidat');
    const justification = document.getElementById('justification').value.trim();
    
    if (!justification || justification.length < 10) {
      alert('Veuillez saisir une justification d\'au moins 10 caractères.');
      return;
    }

    const submitButton = document.querySelector('#modalProposerCandidat .btn-primary');
    const originalText = submitButton.innerHTML;
    
    // Afficher le loading
    submitButton.disabled = true;
    submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Proposition en cours...';

    try {
      const formData = new FormData(form);
      formData.append('action', 'proposer_candidat');

      const response = await fetch(window.location.href, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      });

      if (response.ok) {
        const result = await response.json();
        
        if (result.success) {
          // Fermer la modale
          const modal = bootstrap.Modal.getInstance(document.getElementById('modalProposerCandidat'));
          if (modal) modal.hide();
          
          // Afficher un message de succès
          showNotification('Candidat proposé avec succès !', 'success');
          
          // Optionnel: rediriger vers la page de validation
          setTimeout(() => {
            window.location.href = result.redirect_url || `{% url 'interim_validation' demande.id %}`;
          }, 2000);
        } else {
          throw new Error(result.message || 'Erreur lors de la proposition');
        }
      } else {
        throw new Error('Erreur de communication avec le serveur');
      }

    } catch (error) {
      console.error('Erreur proposition candidat:', error);
      showNotification('Erreur lors de la proposition: ' + error.message, 'error');
    } finally {
      // Restaurer le bouton
      submitButton.disabled = false;
      submitButton.innerHTML = originalText;
    }
  };

  // ================================================================
  // ANIMATIONS DES BARRES DE PROGRESSION
  // ================================================================

  function animateProgressBars() {
    const progressBars = document.querySelectorAll('.criterion-progress');
    
    progressBars.forEach(bar => {
      const width = bar.style.width;
      bar.style.width = '0%';
      
      setTimeout(() => {
        bar.style.width = width;
      }, 100);
    });
  }

  // Observer pour déclencher les animations
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  };

  const progressObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        animateProgressBars();
        progressObserver.unobserve(entry.target);
      }
    });
  }, observerOptions);

  const criteriaSection = document.querySelector('.criteria-breakdown');
  if (criteriaSection) {
    progressObserver.observe(criteriaSection);
  }

  // ================================================================
  // INTERACTIONS TABLEAU DE COMPARAISON
  // ================================================================

  const comparisonTable = document.querySelector('.comparison-table');
  if (comparisonTable) {
    // Surligner la ligne au survol
    const rows = comparisonTable.querySelectorAll('tbody tr');
    
    rows.forEach(row => {
      row.addEventListener('mouseenter', function() {
        if (!this.classList.contains('current-candidate')) {
          this.style.backgroundColor = 'rgba(0, 123, 255, 0.1)';
        }
      });
      
      row.addEventListener('mouseleave', function() {
        if (!this.classList.contains('current-candidate')) {
          this.style.backgroundColor = '';
        }
      });
    });
  }

  // ================================================================
  // TOOLTIP POUR LES SCORES
  // ================================================================

  const scoreElements = document.querySelectorAll('.score-display, .score-circle');
  
  scoreElements.forEach(element => {
    element.addEventListener('mouseenter', function() {
      const score = this.textContent.trim();
      let tooltip = '';
      
      const scoreValue = parseInt(score);
      if (scoreValue >= 80) {
        tooltip = 'Excellent candidat - Très adapté';
      } else if (scoreValue >= 65) {
        tooltip = 'Bon candidat - Bien adapté';
      } else if (scoreValue >= 50) {
        tooltip = 'Candidat correct - Adaptation moyenne';
      } else {
        tooltip = 'Candidat à risque - Peu adapté';
      }
      
      this.title = tooltip;
    });
  });

  // ================================================================
  // GESTION DES FORMULAIRES
  // ================================================================

  // Auto-resize des textareas
  const textareas = document.querySelectorAll('.form-textarea');
  textareas.forEach(textarea => {
    textarea.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = this.scrollHeight + 'px';
    });
  });

  // Validation en temps réel
  const justificationInput = document.getElementById('justification');
  if (justificationInput) {
    justificationInput.addEventListener('input', function() {
      const submitButton = document.querySelector('#modalProposerCandidat .btn-primary');
      
      if (this.value.trim().length >= 10) {
        submitButton.disabled = false;
        this.style.borderColor = '#28a745';
      } else {
        submitButton.disabled = true;
        this.style.borderColor = '#dc3545';
      }
    });
  }

  // ================================================================
  // RACCOURCIS CLAVIER
  // ================================================================

  document.addEventListener('keydown', function(event) {
    // Ignore si un champ est en focus
    if (document.activeElement.tagName === 'INPUT' || 
        document.activeElement.tagName === 'TEXTAREA') {
      return;
    }

    switch(event.key) {
      case '1':
        switchTab('score-detail');
        break;
      case '2':
        switchTab('comparaison');
        break;
      case '3':
        switchTab('competences');
        break;
      case '4':
        switchTab('historique');
        break;
      case '5':
        switchTab('ameliorations');
        break;
      case 'p':
        if (event.ctrlKey || event.metaKey) {
          event.preventDefault();
          window.print();
        }
        break;
      case 'Escape':
        // Fermer les modales
        const modals = document.querySelectorAll('.modal.show');
        modals.forEach(modal => {
          const modalInstance = bootstrap.Modal.getInstance(modal);
          if (modalInstance) modalInstance.hide();
        });
        break;
    }
  });

  // ================================================================
  // FONCTIONS UTILITAIRES
  // ================================================================

  window.showNotification = function(message, type = 'info') {
    // Créer une notification toast
    const toastContainer = document.querySelector('.toast-container') || createToastContainer();
    
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
      <div class="toast ${bgClass} text-white" id="${toastId}" role="alert" data-bs-autohide="true" data-bs-delay="5000">
        <div class="toast-header ${bgClass} text-white border-0">
          <i class="fas ${icon} me-2"></i>
          <strong class="me-auto">Notification</strong>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
        </div>
        <div class="toast-body">${message}</div>
      </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    
    const toastElement = document.getElementById(toastId);
    if (toastElement && typeof bootstrap !== 'undefined') {
      const toast = new bootstrap.Toast(toastElement);
      toast.show();
      
      toastElement.addEventListener('hidden.bs.toast', function() {
        toastElement.remove();
      });
    }
  };

  function createToastContainer() {
    const container = document.createElement('div');
    container.className = 'toast-container position-fixed top-0 end-0 p-3';
    container.style.zIndex = '11';
    document.body.appendChild(container);
    return container;
  }

  // ================================================================
  // GESTION D'ERREURS
  // ================================================================

  window.addEventListener('error', function(event) {
    console.error('❌ Erreur JavaScript:', event.error);
  });

  // ================================================================
  // INITIALISATION FINALE
  // ================================================================

  // Animer l'entrée de la page
  document.body.style.opacity = '0';
  setTimeout(() => {
    document.body.style.transition = 'opacity 0.3s ease';
    document.body.style.opacity = '1';
  }, 100);

  // Déclencher les animations initiales
  setTimeout(animateProgressBars, 500);

  console.log('✅ Page score employé initialisée avec succès');
  console.log('📌 Raccourcis disponibles:');
  console.log('   • 1-5: Changer d\'onglet');
  console.log('   • Ctrl+P: Imprimer');
  console.log('   • Échap: Fermer modales');
});

