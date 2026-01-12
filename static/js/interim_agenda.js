
document.addEventListener('DOMContentLoaded', function() {
  console.log('📅 Page agenda des demandes d\'intérim initialisée');
  
  // Animation d'entrée progressive pour les éléments
  const statCards = document.querySelectorAll('.stat-card');
  statCards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, 100 + (index * 100));
  });
  
  // Animation pour les échéances
  const echeanceItems = document.querySelectorAll('.echeance-item');
  echeanceItems.forEach((item, index) => {
    item.style.opacity = '0';
    item.style.transform = 'translateX(-20px)';
    
    setTimeout(() => {
      item.style.transition = 'all 0.5s ease';
      item.style.opacity = '1';
      item.style.transform = 'translateX(0)';
    }, 200 + (index * 150));
  });
  
  // Auto-submit du formulaire de filtres avec debounce
  let filterTimeout;
  const filterInputs = document.querySelectorAll('#type_vue, #departement, #site, #statut, #urgence');
  
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
  
  // Compteur animé pour les statistiques
  const statNumbers = document.querySelectorAll('.stat-number');
  statNumbers.forEach(number => {
    const text = number.textContent;
    const value = parseFloat(text);
    
    if (!isNaN(value) && value > 0) {
      let current = 0;
      const increment = Math.ceil(value / 15);
      const suffix = text.replace(value.toString(), '');
      
      const timer = setInterval(() => {
        current += increment;
        if (current >= value) {
          current = value;
          clearInterval(timer);
        }
        
        number.textContent = Math.floor(current) + suffix;
      }, 80);
    }
  });
  
  // Hover effects pour les événements du calendrier
  const calendarEvents = document.querySelectorAll('.calendar-event');
  calendarEvents.forEach(event => {
    event.addEventListener('mouseenter', function() {
      this.style.transform = 'scale(1.05)';
      this.style.zIndex = '10';
    });
    
    event.addEventListener('mouseleave', function() {
      this.style.transform = 'scale(1)';
      this.style.zIndex = '1';
    });
  });
  
  // Keyboard navigation pour le calendrier
  document.addEventListener('keydown', function(e) {
    const currentDate = new Date({{ annee_actuelle }}, {{ mois_actuel }} - 1, 1);
    
    if (e.key === 'ArrowLeft') {
      // Mois précédent
      const prevMonth = currentDate.getMonth() === 0 ? 12 : currentDate.getMonth();
      const prevYear = currentDate.getMonth() === 0 ? currentDate.getFullYear() - 1 : currentDate.getFullYear();
      window.location.href = updateUrlParameter(window.location.href, 'mois', prevMonth);
      window.location.href = updateUrlParameter(window.location.href, 'annee', prevYear);
    } else if (e.key === 'ArrowRight') {
      // Mois suivant
      const nextMonth = currentDate.getMonth() === 11 ? 1 : currentDate.getMonth() + 2;
      const nextYear = currentDate.getMonth() === 11 ? currentDate.getFullYear() + 1 : currentDate.getFullYear();
      window.location.href = updateUrlParameter(window.location.href, 'mois', nextMonth);
      window.location.href = updateUrlParameter(window.location.href, 'annee', nextYear);
    }
  });
  
  console.log('✅ Animations et interactions initialisées');
});

// Fonction pour afficher les détails d'un événement
function afficherDetailsEvenement(demandeId) {
  const modal = new bootstrap.Modal(document.getElementById('eventDetailsModal'));
  const modalContent = document.getElementById('eventDetailsContent');
  
  // Afficher le loading
  modalContent.innerHTML = `
    <div class="text-center">
      <i class="fas fa-spinner fa-spin fa-2x text-primary"></i>
      <p class="mt-2">Chargement des détails...</p>
    </div>
  `;
  
  modal.show();
  
  // Charger les détails via AJAX (URL Django dynamique)
  fetch(`{% url 'agenda_event' 0 %}`.replace('0', demandeId))
    .then(response => response.json())
    .then(data => {
      if (data.error) {
        modalContent.innerHTML = `
          <div class="alert alert-danger">
            <i class="fas fa-exclamation-triangle"></i>
            ${data.message}
          </div>
        `;
        return;
      }
      
      // ✅ CORRECTION : Mapping avec la vraie structure de réponse
      
      // Construire les propositions
      let propositionsHtml = '';
      if (data.propositions && data.propositions.liste && data.propositions.liste.length > 0) {
        propositionsHtml = `
          <div class="mt-3">
            <h6><i class="fas fa-users"></i> Propositions (${data.propositions.total})</h6>
            <div class="list-group">
              ${data.propositions.liste.map(prop => `
                <div class="list-group-item ${prop.est_selectionne ? 'border-success' : ''}">
                  <div class="d-flex justify-content-between align-items-center">
                    <div>
                      <strong>${prop.candidat.nom_complet}</strong>
                      ${prop.est_selectionne ? '<span class="badge bg-success ms-2">Sélectionné</span>' : ''}
                      <br><small class="text-muted">Proposé par ${prop.proposant.nom_complet} (${prop.proposant.source})</small>
                      ${prop.justification ? `<br><em class="text-muted">"${prop.justification.substring(0, 100)}${prop.justification.length > 100 ? '...' : ''}"</em>` : ''}
                    </div>
                    <div class="text-end">
                      ${prop.scores.final ? `<span class="badge ${prop.scores.final >= 70 ? 'bg-success' : prop.scores.final >= 50 ? 'bg-warning' : 'bg-danger'}">${prop.scores.final}/100</span>` : ''}
                      <br><small class="text-muted">${prop.date_proposition}</small>
                    </div>
                  </div>
                </div>
              `).join('')}
            </div>
            ${data.propositions.total > data.propositions.liste.length ? `
              <div class="text-center mt-2">
                <small class="text-muted">... et ${data.propositions.total - data.propositions.liste.length} autres proposition(s)</small>
              </div>
            ` : ''}
          </div>
        `;
      }
      
      // Construire les validations
      let validationsHtml = '';
      if (data.validations && data.validations.liste && data.validations.liste.length > 0) {
        validationsHtml = `
          <div class="mt-3">
            <h6><i class="fas fa-check-square"></i> Validations (${data.validations.total})</h6>
            <div class="list-group">
              ${data.validations.liste.map(val => `
                <div class="list-group-item">
                  <div class="d-flex justify-content-between align-items-center">
                    <div>
                      <strong>${val.type}</strong> (Niveau ${val.niveau})
                      <br><small class="text-muted">${val.validateur.nom_complet} (${val.validateur.type_profil})</small>
                      ${val.commentaire ? `<br><em class="text-muted">"${val.commentaire.substring(0, 80)}${val.commentaire.length > 80 ? '...' : ''}"</em>` : ''}
                    </div>
                    <div class="text-end">
                      <span class="badge ${val.decision_code === 'APPROUVE' ? 'bg-success' : val.decision_code === 'REFUSE' ? 'bg-danger' : 'bg-warning'}">${val.decision}</span>
                      <br><small class="text-muted">${val.date_validation || 'En attente'}</small>
                      ${val.delai_traitement ? `<br><small class="text-info">${val.delai_traitement.total_heures}h</small>` : ''}
                    </div>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        `;
      }
      
      // Construire le workflow
      let workflowHtml = '';
      if (data.workflow) {
        const progressClass = data.workflow.progression_pourcentage >= 100 ? 'bg-success' : 
                             data.workflow.progression_pourcentage >= 66 ? 'bg-primary' : 
                             data.workflow.progression_pourcentage >= 33 ? 'bg-warning' : 'bg-danger';
        
        workflowHtml = `
          <div class="mt-3">
            <h6><i class="fas fa-tasks"></i> Workflow de validation</h6>
            <div class="progress mb-2" style="height: 20px;">
              <div class="progress-bar ${progressClass}" role="progressbar" 
                   style="width: ${data.workflow.progression_pourcentage}%" 
                   aria-valuenow="${data.workflow.progression_pourcentage}" 
                   aria-valuemin="0" aria-valuemax="100">
                ${data.workflow.progression_pourcentage}%
              </div>
            </div>
            <div class="row">
              <div class="col-md-6">
                <small><strong>Étape actuelle :</strong> ${data.workflow.etape_actuelle}</small>
                ${data.workflow.en_retard ? '<br><span class="badge bg-danger">En retard</span>' : ''}
              </div>
              <div class="col-md-6">
                <small><strong>Prochaine étape :</strong> ${data.workflow.prochaine_etape}</small>
                <br><small class="text-muted">Depuis ${data.workflow.delai_depuis_creation} jour(s)</small>
              </div>
            </div>
          </div>
        `;
      }
      
      // ✅ CORRECTION : Utilisation des vraies clés de data
      modalContent.innerHTML = `
        <div class="event-details">
          <!-- En-tête -->
          <div class="row mb-3">
            <div class="col-md-8">
              <h5 class="mb-1">${data.demande.numero_demande}</h5>
              <p class="mb-0 text-muted">${data.poste.titre} - ${data.poste.site.nom}</p>
            </div>
            <div class="col-md-4 text-end">
              <span class="badge ${data.demande.statut_code === 'TERMINEE' ? 'bg-success' : data.demande.statut_code === 'REFUSEE' ? 'bg-danger' : 'bg-info'}">${data.demande.statut}</span>
              <br>
              <span class="badge ${data.demande.est_urgente ? 'bg-danger' : 'bg-warning'} mt-1">${data.demande.urgence}</span>
            </div>
          </div>
          
          <!-- Informations principales -->
          <div class="row mb-3">
            <div class="col-md-6">
              <div class="info-group mb-2">
                <label class="fw-bold">Demandeur :</label>
                <span>${data.personnes.demandeur.nom_complet}</span>
                <small class="text-muted">(${data.personnes.demandeur.matricule})</small>
              </div>
              <div class="info-group mb-2">
                <label class="fw-bold">Personne remplacée :</label>
                <span>${data.personnes.personne_remplacee.nom_complet}</span>
                <small class="text-muted">(${data.personnes.personne_remplacee.matricule})</small>
              </div>
              <div class="info-group mb-2">
                <label class="fw-bold">Motif d'absence :</label>
                <span style="color: ${data.absence.motif.couleur}">${data.absence.motif.nom}</span>
                <small class="text-muted">(${data.absence.motif.categorie})</small>
              </div>
            </div>
            <div class="col-md-6">
              <div class="info-group mb-2">
                <label class="fw-bold">Département :</label>
                <span>${data.poste.departement.nom}</span>
                <small class="text-muted">(${data.poste.departement.code})</small>
              </div>
              <div class="info-group mb-2">
                <label class="fw-bold">Site :</label>
                <span>${data.poste.site.nom} - ${data.poste.site.ville}</span>
              </div>
              <div class="info-group mb-2">
                <label class="fw-bold">Période :</label>
                <span>${data.absence.periode.date_debut || 'Non définie'} - ${data.absence.periode.date_fin || 'Non définie'}</span>
                ${data.absence.periode.duree_jours ? `<small class="text-muted">(${data.absence.periode.duree_jours} jour(s))</small>` : ''}
              </div>
            </div>
          </div>
          
          <!-- Candidat sélectionné -->
          ${data.candidat_selectionne ? `
            <div class="alert alert-success">
              <h6 class="mb-1"><i class="fas fa-user-check"></i> Candidat sélectionné</h6>
              <div class="row">
                <div class="col-md-8">
                  <strong>${data.personnes.candidat_selectionne.nom_complet}</strong>
                  <small class="text-muted">(${data.personnes.candidat_selectionne.matricule})</small>
                  <br><small>${data.personnes.candidat_selectionne.departement} - ${data.personnes.candidat_selectionne.poste}</small>
                </div>
                <div class="col-md-4 text-end">
                  ${data.candidat_selectionne.selection.score_obtenu ? `
                    <span class="badge bg-primary">${data.candidat_selectionne.selection.score_obtenu}/100</span>
                  ` : ''}
                  ${data.candidat_selectionne.selection.proposant_origine ? `
                    <br><small class="text-muted">Proposé par ${data.candidat_selectionne.selection.proposant_origine.nom}</small>
                  ` : ''}
                </div>
              </div>
              ${data.candidat_selectionne.selection.justification_selection ? `
                <div class="mt-2">
                  <small><strong>Justification :</strong> <em>"${data.candidat_selectionne.selection.justification_selection.substring(0, 150)}${data.candidat_selectionne.selection.justification_selection.length > 150 ? '...' : ''}"</em></small>
                </div>
              ` : ''}
            </div>
          ` : ''}
          
          ${workflowHtml}
          
          <!-- Description du poste -->
          ${data.poste.description ? `
            <div class="mt-3">
              <h6><i class="fas fa-info-circle"></i> Description du poste</h6>
              <p class="text-muted">${data.poste.description}</p>
            </div>
          ` : ''}
          
          <!-- Compétences requises -->
          ${data.poste.competences_requises ? `
            <div class="mt-3">
              <h6><i class="fas fa-star"></i> Compétences requises</h6>
              <p class="text-muted">${data.poste.competences_requises}</p>
            </div>
          ` : ''}
          
          <!-- Instructions particulières -->
          ${data.poste.instructions_particulieres ? `
            <div class="mt-3">
              <h6><i class="fas fa-exclamation-circle"></i> Instructions particulières</h6>
              <p class="text-muted">${data.poste.instructions_particulieres}</p>
            </div>
          ` : ''}
          
          ${propositionsHtml}
          ${validationsHtml}
          
          <!-- Statistiques rapides -->
          ${data.statistiques ? `
            <div class="mt-3">
              <h6><i class="fas fa-chart-line"></i> Statistiques</h6>
              <div class="row">
                <div class="col-md-3">
                  <small><strong>Durée processus :</strong><br>${data.statistiques.duree_totale_processus} jour(s)</small>
                </div>
                ${data.statistiques.score_moyen_propositions ? `
                  <div class="col-md-3">
                    <small><strong>Score moyen :</strong><br>${data.statistiques.score_moyen_propositions}/100</small>
                  </div>
                ` : ''}
                ${data.statistiques.taux_reponse_candidats ? `
                  <div class="col-md-3">
                    <small><strong>Taux réponse :</strong><br>${data.statistiques.taux_reponse_candidats}%</small>
                  </div>
                ` : ''}
                ${data.statistiques.temps_moyen_validation ? `
                  <div class="col-md-3">
                    <small><strong>Temps validation :</strong><br>${data.statistiques.temps_moyen_validation}h</small>
                  </div>
                ` : ''}
              </div>
            </div>
          ` : ''}
          
          <!-- Actions disponibles -->
          ${data.actions_disponibles ? `
            <div class="mt-3 pt-2 border-top">
              <div class="d-flex gap-2 flex-wrap">
                ${data.actions_disponibles.peut_voir_details_complets ? `
                  <button class="btn btn-sm btn-outline-primary" onclick="voirDetailsComplets(${data.demande.id})">
                    <i class="fas fa-eye"></i> Détails complets
                  </button>
                ` : ''}
                ${data.actions_disponibles.peut_proposer_candidat ? `
                  <button class="btn btn-sm btn-outline-success" onclick="proposerCandidat(${data.demande.id})">
                    <i class="fas fa-user-plus"></i> Proposer candidat
                  </button>
                ` : ''}
                ${data.actions_disponibles.peut_valider ? `
                  <button class="btn btn-sm btn-outline-warning" onclick="validerDemande(${data.demande.id}, ${data.actions_disponibles.niveau_validation_possible})">
                    <i class="fas fa-check"></i> Valider
                  </button>
                ` : ''}
                ${data.actions_disponibles.peut_exporter ? `
                  <button class="btn btn-sm btn-outline-info" onclick="exporterDemande(${data.demande.id})">
                    <i class="fas fa-download"></i> Exporter
                  </button>
                ` : ''}
              </div>
            </div>
          ` : ''}
          
          <!-- Métadonnées -->
          <div class="mt-3 text-muted">
            <small>
              <i class="fas fa-calendar-plus"></i> Créée le ${data.demande.date_creation}
              | <i class="fas fa-edit"></i> Modifiée le ${data.demande.date_modification}
              ${data.metadata ? `| <i class="fas fa-user"></i> Vue avec accès ${data.metadata.niveau_acces_utilisateur}` : ''}
            </small>
          </div>
        </div>
      `;
    })
    .catch(error => {
      console.error('Erreur lors du chargement des détails:', error);
      modalContent.innerHTML = `
        <div class="alert alert-danger">
          <i class="fas fa-exclamation-triangle"></i>
          Erreur lors du chargement des détails. Veuillez réessayer.
        </div>
      `;
    });
}

// Fonction pour afficher les détails d'un jour
function afficherJourDetails(dateStr) {
  console.log('Affichage des détails pour le jour:', dateStr);
  // Implémentation future : modal avec tous les événements du jour
}

// Fonction d'export de l'agenda
function exporterAgenda() {
  const exportBtn = document.querySelector('[onclick="exporterAgenda()"]');
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
    const notification = document.createElement('div');
    notification.className = 'alert alert-success position-fixed';
    notification.style.top = '20px';
    notification.style.right = '20px';
    notification.style.zIndex = '9999';
    notification.style.padding = '1rem';
    notification.style.borderRadius = '8px';
    notification.innerHTML = '<i class="fas fa-check-circle"></i> Export de l\'agenda terminé avec succès !';
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
      notification.remove();
    }, 3000);
    
  }, 2000);
}

// Fonction utilitaire pour modifier les paramètres d'URL
function updateUrlParameter(url, param, paramVal) {
  let newAdditionalURL = "";
  let tempArray = url.split("?");
  let baseURL = tempArray[0];
  let additionalURL = tempArray[1];
  let temp = "";
  if (additionalURL) {
    tempArray = additionalURL.split("&");
    for (let i = 0; i < tempArray.length; i++) {
      if (tempArray[i].split('=')[0] != param) {
        newAdditionalURL += temp + tempArray[i];
        temp = "&";
      }
    }
  }
  
  let rows_txt = temp + "" + param + "=" + paramVal;
  return baseURL + "?" + newAdditionalURL + rows_txt;
}

// Gestion des raccourcis clavier
document.addEventListener('keydown', function(e) {
  // Échapper pour fermer les modals
  if (e.key === 'Escape') {
    const openModal = document.querySelector('.modal.show');
    if (openModal) {
      const modal = bootstrap.Modal.getInstance(openModal);
      if (modal) {
        modal.hide();
      }
    }
  }
  
  // F5 pour actualiser
  if (e.key === 'F5') {
    e.preventDefault();
    window.location.reload();
  }
});

// Gestion responsive améliorée
function handleResponsiveChanges() {
  const isMobile = window.innerWidth <= 768;
  const calendarEvents = document.querySelectorAll('.calendar-event');
  
  calendarEvents.forEach(event => {
    if (isMobile) {
      event.style.fontSize = '0.7rem';
      event.style.padding = '0.2rem 0.3rem';
    } else {
      event.style.fontSize = '0.75rem';
      event.style.padding = '0.25rem 0.5rem';
    }
  });
}

// Écouter les changements de taille d'écran
window.addEventListener('resize', handleResponsiveChanges);
handleResponsiveChanges(); // Appel initial

console.log('📅 Scripts agenda d\'intérim chargés avec succès');

// ✅ NOUVELLES FONCTIONS pour les actions du modal

// Fonction pour voir les détails complets d'une demande
function voirDetailsComplets(demandeId) {
  // Rediriger vers la page de détails ou ouvrir un autre modal
  window.open(`/interim/demande/${demandeId}/details/`, '_blank');
}

// Fonction pour proposer un candidat
function proposerCandidat(demandeId) {
  // Rediriger vers la page de proposition
  window.location.href = `/interim/demande/${demandeId}/proposer-candidat/`;
}

// Fonction pour valider une demande
function validerDemande(demandeId, niveau) {
  // Rediriger vers la page de validation
  window.location.href = `/interim/demande/${demandeId}/valider/?niveau=${niveau}`;
}

// Fonction pour exporter une demande
function exporterDemande(demandeId) {
  // Lancer l'export PDF de la demande
  window.open(`/interim/demande/${demandeId}/export/pdf/`, '_blank');
}

// Fonction pour gérer les erreurs AJAX de manière robuste
function handleAjaxError(error, context = 'Action') {
  console.error(`Erreur ${context}:`, error);
  
  // Afficher une notification d'erreur
  const notification = document.createElement('div');
  notification.className = 'alert alert-danger position-fixed';
  notification.style.cssText = `
    top: 20px; 
    right: 20px; 
    z-index: 9999; 
    padding: 1rem; 
    border-radius: 8px;
    max-width: 400px;
  `;
  notification.innerHTML = `
    <i class="fas fa-exclamation-triangle"></i> 
    Erreur lors de ${context.toLowerCase()}. Veuillez réessayer.
    <button type="button" class="btn-close ms-2" onclick="this.parentElement.remove()"></button>
  `;
  
  document.body.appendChild(notification);
  
  // Supprimer automatiquement après 5 secondes
  setTimeout(() => {
    if (notification.parentElement) {
      notification.remove();
    }
  }, 5000);
}

// Fonction pour afficher une notification de succès
function showSuccessNotification(message) {
  const notification = document.createElement('div');
  notification.className = 'alert alert-success position-fixed';
  notification.style.cssText = `
    top: 20px; 
    right: 20px; 
    z-index: 9999; 
    padding: 1rem; 
    border-radius: 8px;
    max-width: 400px;
  `;
  notification.innerHTML = `
    <i class="fas fa-check-circle"></i> ${message}
    <button type="button" class="btn-close ms-2" onclick="this.parentElement.remove()"></button>
  `;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    if (notification.parentElement) {
      notification.remove();
    }
  }, 3000);
}

// ✅ AMÉLIORATION : Gestion robuste des événements du calendrier
function setupCalendarEventHandlers() {
  // Gérer les clics sur les événements du calendrier
  document.addEventListener('click', function(e) {
    const eventElement = e.target.closest('.calendar-event');
    if (eventElement && eventElement.onclick) {
      e.preventDefault();
      e.stopPropagation();
      // L'onclick est déjà défini dans le HTML
    }
  });
  
  // Gérer les touches du clavier pour la navigation
  document.addEventListener('keydown', function(e) {
    // Échapper pour fermer les modals
    if (e.key === 'Escape') {
      const openModal = document.querySelector('.modal.show');
      if (openModal) {
        const modalInstance = bootstrap.Modal.getInstance(openModal);
        if (modalInstance) {
          modalInstance.hide();
        }
      }
    }
  });
}

// ✅ AMÉLIORATION : Initialisation robuste au chargement
document.addEventListener('DOMContentLoaded', function() {
  console.log('📅 Initialisation agenda d\'intérim...');
  
  try {
    setupCalendarEventHandlers();
    
    // Vérifier la présence de Bootstrap
    if (typeof bootstrap === 'undefined') {
      console.warn('⚠️ Bootstrap non détecté - certaines fonctionnalités peuvent ne pas fonctionner');
    }
    
    // Initialiser les tooltips si disponibles
    if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
      const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
      tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
      });
    }
    
    console.log('✅ Agenda d\'intérim initialisé avec succès');
    
  } catch (error) {
    console.error('❌ Erreur lors de l\'initialisation:', error);
    handleAjaxError(error, 'l\'initialisation');
  }
});

