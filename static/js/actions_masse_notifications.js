document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation des actions en masse - Version finale');

  // === ÉLÉMENTS DE L'INTERFACE ===
  const actionForm = document.getElementById('actionForm');
  const selectAllCheckbox = document.getElementById('selectAll');
  const selectAllSection = document.getElementById('selectAllSection');
  const selectedCountSpan = document.getElementById('selectedCount');
  const actionButtons = document.querySelectorAll('.btn-action');
  
  // === CHECKBOXES ===
  const hiddenCheckboxes = document.querySelectorAll('.hidden-notification-checkbox');
  const displayCheckboxes = document.querySelectorAll('.notification-checkbox-display');
  
  console.log('🔍 DEBUG - Configuration détectée:');
  console.log('- Formulaire principal:', actionForm ? '✅' : '❌');
  console.log('- Checkboxes cachées:', hiddenCheckboxes.length);
  console.log('- Checkboxes d\'affichage:', displayCheckboxes.length);
  console.log('- Boutons d\'action:', actionButtons.length);

  // === VÉRIFICATIONS INITIALES ===
  if (!actionForm) {
    console.error('❌ ERREUR CRITIQUE: Formulaire d\'action manquant');
    showNotification('Erreur système: Formulaire d\'action non trouvé', 'error');
    return;
  }

  if (hiddenCheckboxes.length === 0) {
    console.warn('⚠️ Aucune notification disponible pour sélection');
    showNotification('Aucune notification disponible pour les actions en masse', 'info');
  }

  // === SYNCHRONISATION DES CHECKBOXES ===
  displayCheckboxes.forEach((displayCheckbox, index) => {
    displayCheckbox.addEventListener('change', function() {
      const targetId = this.dataset.target;
      const hiddenCheckbox = document.getElementById(targetId);
      
      if (hiddenCheckbox) {
        hiddenCheckbox.checked = this.checked;
        console.log(`🔗 Sync ${index + 1}: ${targetId} ${this.checked ? 'cochée' : 'décochée'}`);
        updateSelectionStatus();
      } else {
        console.error(`❌ Checkbox cachée introuvable: ${targetId}`);
      }
    });
  });

  // === FONCTION DE MISE À JOUR DU STATUT ===
  function updateSelectionStatus() {
    const checkedHiddenBoxes = document.querySelectorAll('.hidden-notification-checkbox:checked');
    const count = checkedHiddenBoxes.length;
    
    console.log(`📊 Mise à jour: ${count} notifications sélectionnées`);
    
    // Mettre à jour le compteur
    if (selectedCountSpan) {
      selectedCountSpan.innerHTML = `
        <i class="fas fa-list-check"></i> ${count} notification(s) sélectionnée(s)
      `;
    }
    
    // Activer/désactiver les boutons
    actionButtons.forEach(button => {
      button.disabled = count === 0;
      if (count > 0) {
        button.classList.add('btn-ready');
      } else {
        button.classList.remove('btn-ready');
      }
    });
    
    // État du sélecteur global
    if (count === 0) {
      selectAllCheckbox.indeterminate = false;
      selectAllCheckbox.checked = false;
    } else if (count === hiddenCheckboxes.length) {
      selectAllCheckbox.indeterminate = false;
      selectAllCheckbox.checked = true;
    } else {
      selectAllCheckbox.indeterminate = true;
    }

    // États visuels des notifications
    displayCheckboxes.forEach(displayCheckbox => {
      const targetId = displayCheckbox.dataset.target;
      const hiddenCheckbox = document.getElementById(targetId);
      const notificationItem = displayCheckbox.closest('.notification-item');
      
      if (notificationItem && hiddenCheckbox) {
        notificationItem.classList.toggle('selected', hiddenCheckbox.checked);
      }
    });

    // Animation du compteur
    if (selectedCountSpan && count > 0) {
      selectedCountSpan.style.animation = 'pulse 0.3s ease-in-out';
      setTimeout(() => {
        selectedCountSpan.style.animation = '';
      }, 300);
    }
  }

  // === GESTIONNAIRE "TOUT SÉLECTIONNER" ===
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', function() {
      const isChecked = this.checked;
      console.log(`🎯 Sélection globale: ${isChecked ? 'TOUT' : 'RIEN'}`);
      
      // Synchroniser toutes les checkboxes
      hiddenCheckboxes.forEach(hiddenCheckbox => {
        hiddenCheckbox.checked = isChecked;
      });
      
      displayCheckboxes.forEach(displayCheckbox => {
        displayCheckbox.checked = isChecked;
      });
      
      updateSelectionStatus();
      
      // Notification utilisateur
      showNotification(
        isChecked ? 
        `✅ ${hiddenCheckboxes.length} notifications sélectionnées` : 
        '❌ Toutes les sélections annulées', 
        'info'
      );
    });
  }

  // === GESTIONNAIRE DE SOUMISSION PRINCIPAL ===
  if (actionForm) {
    actionForm.addEventListener('submit', function(e) {
      console.log('📤 SOUMISSION DÉCLENCHÉE');
      
      // === VÉRIFICATIONS PRÉLIMINAIRES ===
      const checkedHiddenBoxes = document.querySelectorAll('.hidden-notification-checkbox:checked');
      const selectedValues = Array.from(checkedHiddenBoxes).map(cb => cb.value);
      
      console.log('📋 État de la soumission:');
      console.log('- Notifications sélectionnées:', checkedHiddenBoxes.length);
      console.log('- IDs sélectionnés:', selectedValues);
      console.log('- Bouton soumis:', e.submitter);
      
      // === VÉRIFICATION DE L'ACTION ===
      if (!e.submitter || !e.submitter.value) {
        e.preventDefault();
        console.error('❌ ERREUR: Aucune action définie');
        showNotification('❌ Erreur: Action non définie', 'error');
        return false;
      }
      
      const actionValue = e.submitter.value;
      const actionName = e.submitter.name;
      
      console.log('🎬 Action détectée:', { name: actionName, value: actionValue });
      
      // === VÉRIFICATION DES SÉLECTIONS ===
      if (checkedHiddenBoxes.length === 0) {
        e.preventDefault();
        console.warn('⚠️ Aucune notification sélectionnée');
        
        // Animation d'alerte
        if (selectAllSection) {
          selectAllSection.classList.add('highlight');
          setTimeout(() => {
            selectAllSection.classList.remove('highlight');
          }, 2000);
        }
        
        showNotification('⚠️ Veuillez sélectionner au moins une notification', 'warning');
        return false;
      }

      // === VALIDATION DES IDS ===
      const invalidIds = selectedValues.filter(id => !id || isNaN(parseInt(id)));
      if (invalidIds.length > 0) {
        e.preventDefault();
        console.error('❌ IDs invalides:', invalidIds);
        showNotification(`❌ IDs invalides détectés: ${invalidIds.join(', ')}`, 'error');
        return false;
      }

      // === DEMANDES DE CONFIRMATION ===
      const actionText = e.submitter.textContent.trim();
      let confirmationNeeded = false;
      let confirmMessage = '';
      
      switch(actionValue) {
        case 'supprimer':
          confirmationNeeded = true;
          confirmMessage = `🗑️ Confirmer la suppression définitive de ${checkedHiddenBoxes.length} notification(s) ?\n\n⚠️ Cette action est irréversible !`;
          break;
        case 'archiver':
          confirmationNeeded = true;
          confirmMessage = `📦 Confirmer l'archivage de ${checkedHiddenBoxes.length} notification(s) ?\n\nElles ne seront plus visibles dans la liste principale.`;
          break;
        default:
          if (checkedHiddenBoxes.length > 10) {
            confirmationNeeded = true;
            confirmMessage = `📊 Confirmer l'action "${actionText}" sur ${checkedHiddenBoxes.length} notifications ?`;
          }
      }
      
      if (confirmationNeeded && !confirm(confirmMessage)) {
        e.preventDefault();
        console.log('🚫 Action annulée par l\'utilisateur');
        return false;
      }

      // === PRÉPARATION DE LA SOUMISSION ===
      
      // Ajouter un champ action caché pour garantir la transmission
      let hiddenActionInput = document.querySelector('input[name="action"][type="hidden"]');
      if (hiddenActionInput) {
        hiddenActionInput.remove();
      }
      
      hiddenActionInput = document.createElement('input');
      hiddenActionInput.type = 'hidden';
      hiddenActionInput.name = 'action';
      hiddenActionInput.value = actionValue;
      actionForm.appendChild(hiddenActionInput);
      
      console.log('🔒 Champ action caché ajouté:', hiddenActionInput.value);

      // === INDICATEUR DE CHARGEMENT ===
      const originalContent = e.submitter.innerHTML;
      e.submitter.disabled = true;
      e.submitter.innerHTML = '<span class="loading-spinner"></span> Traitement...';
      
      // Désactiver tous les autres boutons
      actionButtons.forEach(btn => {
        if (btn !== e.submitter) {
          btn.disabled = true;
          btn.style.opacity = '0.3';
        }
      });
      
      // Sauvegarde pour restauration
      window.originalButtonContent = originalContent;
      window.submitButton = e.submitter;
      
      // === DEBUG FINAL ===
      console.log('📊 SOUMISSION FINALE:');
      console.log('- Action:', actionValue);
      console.log('- Notifications:', selectedValues.length);
      console.log('- FormData preview:');
      
      const formData = new FormData(actionForm);
      for (let [key, value] of formData.entries()) {
        if (key === 'notifications_ids') {
          console.log(`  - ${key}: [${Array.from(formData.getAll(key)).length} éléments]`);
        } else {
          console.log(`  - ${key}: ${value}`);
        }
      }
      
      console.log('✅ Soumission autorisée');
      
      // Notification de traitement
      showNotification(`🔄 Traitement de ${checkedHiddenBoxes.length} notifications...`, 'info');
      
      return true;
    });
  }

  // === RACCOURCIS CLAVIER ===
  document.addEventListener('keydown', function(e) {
    if (e.ctrlKey || e.metaKey) {
      switch(e.key.toLowerCase()) {
        case 'a':
          e.preventDefault();
          if (selectAllCheckbox) {
            selectAllCheckbox.checked = !selectAllCheckbox.checked;
            selectAllCheckbox.dispatchEvent(new Event('change'));
          }
          break;
        case 'r':
          e.preventDefault();
          window.location.reload();
          break;
        case 'f':
          e.preventDefault();
          document.getElementById('destinataire')?.focus();
          break;
      }
    } else if (e.key === 'Escape') {
      if (selectAllCheckbox) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.dispatchEvent(new Event('change'));
      }
    }
  });

  // === AUTO-REFRESH INTELLIGENT ===
  let autoRefreshInterval = setInterval(() => {
    if (document.hidden) return; // Ne pas rafraîchir si l'onglet n'est pas visible
    
    const url = new URL(window.location);
    url.searchParams.set('check_updates', '1');
    
    fetch(url, { method: 'HEAD' })
    .then(response => {
      const newCount = response.headers.get('X-Notification-Count');
      const currentCount = document.querySelector('.stats-card h3')?.textContent.trim();
      
      if (newCount && currentCount && newCount !== currentCount) {
        const refreshBtn = document.querySelector('button[onclick="window.location.reload()"]');
        if (refreshBtn && !refreshBtn.querySelector('.badge')) {
          refreshBtn.innerHTML += ' <span class="badge bg-danger ms-1">Nouveau</span>';
        }
        showNotification('🔔 Nouvelles notifications disponibles', 'info');
      }
    })
    .catch(error => {
      console.log('Auto-refresh error:', error);
    });
  }, 120000); // 2 minutes

  // === NETTOYAGE À LA FERMETURE ===
  window.addEventListener('beforeunload', function() {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
    }
  });

  // === INITIALISATION FINALE ===
  updateSelectionStatus();
  convertDjangoMessages();
  
  console.log('✅ Actions en masse entièrement initialisées');
  showNotification('✅ Interface prête pour les actions en masse', 'success');
});

// === FONCTIONS UTILITAIRES ===

function showNotification(message, type = 'info') {
  const icons = {
    'success': 'fas fa-check-circle',
    'warning': 'fas fa-exclamation-triangle',
    'error': 'fas fa-times-circle',
    'info': 'fas fa-info-circle'
  };
  
  const colors = {
    'success': { bg: '#d1fae5', text: '#065f46', border: '#10b981' },
    'warning': { bg: '#fef3c7', text: '#92400e', border: '#f59e0b' },
    'error': { bg: '#fee2e2', text: '#991b1b', border: '#ef4444' },
    'info': { bg: '#dbeafe', text: '#1e40af', border: '#3b82f6' }
  };
  
  // Supprimer les notifications existantes du même type
  document.querySelectorAll(`.toast-notification[data-type="${type}"]`).forEach(n => n.remove());
  
  const notification = document.createElement('div');
  notification.className = 'toast-notification';
  notification.setAttribute('data-type', type);
  notification.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 10000;
    max-width: 400px;
    min-width: 320px;
    background: ${colors[type].bg};
    color: ${colors[type].text};
    border: 2px solid ${colors[type].border};
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
    font-size: 14px;
    line-height: 1.5;
    animation: slideInRight 0.4s cubic-bezier(0.68, -0.55, 0.265, 1.55);
    display: flex;
    align-items: flex-start;
    gap: 12px;
  `;
  
  notification.innerHTML = `
    <i class="${icons[type]}" style="margin-top: 2px; font-size: 18px;"></i>
    <div style="flex: 1;">${message}</div>
    <button onclick="this.parentElement.remove()" style="
      background: none;
      border: none;
      color: ${colors[type].text};
      font-size: 20px;
      cursor: pointer;
      padding: 0;
      margin-left: 8px;
      opacity: 0.7;
      transition: opacity 0.2s;
    " onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'">&times;</button>
  `;
  
  document.body.appendChild(notification);
  
  // Auto-remove avec délai adaptatif
  const delays = { 'success': 4000, 'info': 5000, 'warning': 7000, 'error': 10000 };
  setTimeout(() => {
    if (notification.parentNode) {
      notification.style.animation = 'slideOutRight 0.3s ease-in';
      setTimeout(() => notification.remove(), 300);
    }
  }, delays[type] || 5000);
}

function convertDjangoMessages() {
  const djangoAlerts = document.querySelectorAll('.alert[data-message]');
  djangoAlerts.forEach(alert => {
    const messageText = alert.dataset.message;
    const messageType = alert.dataset.type;
    
    let type = 'info';
    if (messageType === 'success') type = 'success';
    else if (messageType === 'warning') type = 'warning';
    else if (['error', 'danger'].includes(messageType)) type = 'error';
    
    alert.style.display = 'none';
    setTimeout(() => showNotification(messageText, type), 100);
  });
}

// === GESTION D'ERREURS GLOBALE ===
window.addEventListener('error', function(e) {
  console.error('❌ Erreur JavaScript:', e.error);
  showNotification('Une erreur inattendue s\'est produite. Rechargez la page.', 'error');
});

// === RESTAURATION EN CAS D'ERREUR ===
window.addEventListener('pageshow', function() {
  if (window.submitButton && window.originalButtonContent) {
    window.submitButton.disabled = false;
    window.submitButton.innerHTML = window.originalButtonContent;
    
    // Réactiver tous les boutons
    document.querySelectorAll('.btn-action').forEach(btn => {
      btn.disabled = false;
      btn.style.opacity = '';
    });
  }
});
