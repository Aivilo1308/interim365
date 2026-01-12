
document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Interface de gestion des propositions initialisée');

  // ================================================================
  // VARIABLES GLOBALES
  // ================================================================
  
  let propositionsSelectionnees = [];
  
  // Correction pour le CSRF token
  function getCSRFToken() {
    // Méthode 1: Depuis le cookie
    const cookieValue = document.cookie
      .split('; ')
      .find(row => row.startsWith('csrftoken='))
      ?.split('=')[1];
    
    if (cookieValue) {
      console.log('✅ CSRF token depuis cookie:', cookieValue);
      return cookieValue;
    }
    
    // Méthode 2: Depuis un input hidden
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    if (csrfInput && csrfInput.value) {
      console.log('✅ CSRF token depuis input:', csrfInput.value);
      return csrfInput.value;
    }
    
    // Méthode 3: Depuis une meta tag
    const csrfMeta = document.querySelector('meta[name=csrf-token]');
    if (csrfMeta && csrfMeta.getAttribute('content')) {
      console.log('✅ CSRF token depuis meta:', csrfMeta.getAttribute('content'));
      return csrfMeta.getAttribute('content');
    }
    
    console.error('❌ Aucun CSRF token trouvé !');
    return null;
  }
  
  const csrfToken = getCSRFToken();

  // Cache pour les recherches d'employés
  const employeeCache = new Map();
  const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes

  // ================================================================
  // FONCTIONS UTILITAIRES
  // ================================================================

  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }

  function getElement(id, required = false) {
    const element = document.getElementById(id);
    if (!element && required) {
      console.error(`❌ Élément requis non trouvé: ${id}`);
    } else if (!element) {
      console.warn(`⚠️ Élément optionnel non trouvé: ${id}`);
    }
    return element;
  }

  function setElementContent(id, content, fallback = '') {
    const element = getElement(id);
    if (element) {
      element.textContent = content || fallback;
      return true;
    }
    return false;
  }

  function setElementDisplay(id, show) {
    const element = getElement(id);
    if (element) {
      element.style.display = show ? 'block' : 'none';
      return true;
    }
    return false;
  }

  // ================================================================
  // FONCTIONS DE RECHERCHE D'EMPLOYÉ
  // ================================================================

  async function rechercherEmploye(matricule, type) {
    console.log(`🔍 DEBUT rechercherEmploye: matricule="${matricule}", type="${type}"`);
    
    if (!matricule || matricule.length < 2) {
      console.log(`❌ Matricule invalide: "${matricule}"`);
      masquerInfosEmploye(type);
      return;
    }

    // Vérifier le cache
    const cacheKey = `${matricule}_${type}`;
    const cached = employeeCache.get(cacheKey);
    
    if (cached && (Date.now() - cached.timestamp) < CACHE_DURATION) {
      console.log(`💾 Cache hit pour ${matricule}`);
      afficherInfosEmploye(cached.data, type);
      return;
    }

    afficherChargementEmploye(type, true);
    console.log(`🔍 Requête AJAX pour ${matricule}`);

    try {
      const requestData = {
        matricule: matricule,
        force_kelio_sync: false
      };
      
      console.log(`📤 Envoi requête:`, requestData);
      
      const response = await fetch('/interim/ajax/rechercher-employe/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(requestData)
      });

      console.log(`📨 Status: ${response.status} ${response.statusText}`);

      if (!response.ok) {
        throw new Error(`Erreur HTTP ${response.status}: ${response.statusText}`);
      }

      const responseText = await response.text();
      console.log(`📨 Réponse brute (${responseText.length} chars):`, responseText.substring(0, 200) + '...');

      let data;
      try {
        data = JSON.parse(responseText);
        console.log(`📨 Données parsées:`, data);
      } catch (parseError) {
        console.error(`❌ Erreur parsing JSON:`, parseError);
        throw new Error(`Réponse non-JSON: ${responseText.substring(0, 100)}...`);
      }

      // Traitement de la réponse
      if (data && data.success === true) {
        console.log(`✅ Succès détecté`);
        
        if (data.employe) {
          console.log(`👤 Employé trouvé:`, data.employe);
          
          // Mettre en cache
          employeeCache.set(cacheKey, {
            data: data,
            timestamp: Date.now()
          });

          // Afficher les informations
          afficherInfosEmploye(data, type);
          showToast('Succès', `Employé ${matricule} trouvé avec succès`, 'success');
          
          // Si c'est un candidat dans la modal d'ajout, calculer le score et vérifier disponibilité
          if (type === 'candidat') {
            setTimeout(() => {
              calculerScoreCandidat(data.employe.id);
              verifierDisponibiliteCandidat(data.employe.id);
            }, 100);
          }
          
        } else {
          console.log(`❌ Pas d'employé dans la réponse`);
          afficherErreurEmploye('Réponse invalide du serveur', type);
        }
        
      } else if (data && data.success === false) {
        console.log(`❌ Échec explicite:`, data.error);
        afficherErreurEmploye(data.error || 'Erreur du serveur', type);
        
      } else {
        console.log(`❌ Structure de réponse inattendue:`, data);
        afficherErreurEmploye('Réponse serveur invalide', type);
      }

    } catch (error) {
      console.error('❌ ERREUR dans rechercherEmploye:', error);
      
      let errorMessage = 'Erreur de communication avec le serveur';
      
      if (error.message.includes('404')) {
        errorMessage = 'Service de recherche non disponible';
      } else if (error.message.includes('500')) {
        errorMessage = 'Erreur serveur temporaire';
      } else if (error.message.includes('JSON')) {
        errorMessage = 'Erreur de format de réponse';
      }
      
      afficherErreurEmploye(errorMessage, type);
      
    } finally {
      console.log(`🔍 FIN rechercherEmploye pour ${matricule}`);
      afficherChargementEmploye(type, false);
    }
  }

  // ================================================================
  // FONCTIONS D'AFFICHAGE
  // ================================================================

  function afficherInfosEmploye(data, type) {
    console.log(`📝 DEBUT afficherInfosEmploye pour type: ${type}`, data);
    
    const employe = data.employe;
    if (!employe) {
      console.error(`❌ Pas de données employé`);
      return;
    }

    // Masquer erreurs et chargement
    setElementDisplay(`${type}_error`, false);
    setElementDisplay(`${type}_loading`, false);

    // Remplir les informations principales
    setElementContent(`${type}_nom_complet`, employe.nom_complet, 'Nom non disponible');
    setElementContent(`${type}_matricule_display`, employe.matricule);
    
    // Détails avec icônes
    if (employe.sexe) {
      setElementContent(`${type}_sexe`, employe.sexe === 'M' ? '👨 Homme' : '👩 Femme');
    }
    
    if (employe.anciennete) {
      setElementContent(`${type}_anciennete`, `⏰ ${employe.anciennete}`);
    }

    // Informations organisationnelles
    if (employe.departement) {
      setElementContent(`${type}_departement`, `🏢 ${employe.departement}`);
    }
    
    if (employe.site) {
      setElementContent(`${type}_site`, `📍 ${employe.site}`);
    }
    
    if (employe.poste) {
      setElementContent(`${type}_poste`, `💼 ${employe.poste}`);
    }

    // Statut de synchronisation
    const syncStatusElement = getElement(`${type}_sync_status`);
    if (syncStatusElement && data.sync_info) {
      if (data.sync_info.is_recent) {
        syncStatusElement.textContent = 'Données à jour';
        syncStatusElement.className = 'employee-sync-status sync-status-recent';
      } else {
        syncStatusElement.textContent = 'Données locales';
        syncStatusElement.className = 'employee-sync-status sync-status-local';
      }
    }

    // Définir l'ID caché
    const hiddenInput = getElement(`${type}_id`);
    if (hiddenInput && employe.id) {
      hiddenInput.value = employe.id;
      console.log(`✅ ID caché défini: ${employe.id}`);
    }

    // Afficher le container principal
    setElementDisplay(`${type}_info`, true);
    
    console.log(`📝 FIN afficherInfosEmploye pour ${type}`);
  }

  function afficherErreurEmploye(message, type) {
    console.log(`❌ Affichage erreur pour ${type}: ${message}`);
    
    setElementDisplay(`${type}_info`, false);
    setElementDisplay(`${type}_loading`, false);
    
    const errorContainer = getElement(`${type}_error`);
    if (errorContainer) {
      const messageElement = errorContainer.querySelector('.error-message');
      if (messageElement) {
        messageElement.textContent = message;
      }
      errorContainer.style.display = 'flex';
    }

    // Vider l'ID caché
    const hiddenInput = getElement(`${type}_id`);
    if (hiddenInput) {
      hiddenInput.value = '';
    }
  }

  function afficherChargementEmploye(type, show) {
    setElementDisplay(`${type}_loading`, show);
    if (show) {
      setElementDisplay(`${type}_info`, false);
      setElementDisplay(`${type}_error`, false);
    }
  }

  function masquerInfosEmploye(type) {
    setElementDisplay(`${type}_info`, false);
    setElementDisplay(`${type}_error`, false);
    setElementDisplay(`${type}_loading`, false);
    
    const hiddenInput = getElement(`${type}_id`);
    if (hiddenInput) {
      hiddenInput.value = '';
    }
  }

  // ================================================================
  // FONCTIONS DE CALCUL DE SCORE ET DISPONIBILITÉ
  // ================================================================

  async function calculerScoreCandidat(candidatId) {
    console.log('📊 Calcul du score pour candidat:', candidatId);
    
    const formData = {
      candidat_id: candidatId,
      demande_id: {{ demande.id }},
      poste_id: {{ demande.poste.id }},
      date_debut: '{{ demande.date_debut|date:"Y-m-d" }}',
      date_fin: '{{ demande.date_fin|date:"Y-m-d" }}',
      description_poste: '{{ demande.description_poste|escapejs }}',
      competences_indispensables: '{{ demande.competences_indispensables|escapejs }}'
    };

    try {
      const response = await fetch('/interim/ajax/calculer-score-candidat/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(formData)
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          afficherScoreCandidatModal(data.score);
        }
      }
    } catch (error) {
      console.error('Erreur calcul score candidat:', error);
    }
  }

  function afficherScoreCandidatModal(score) {
    const scoreElement = document.getElementById('candidat_score_value');
    const scoreContainer = document.getElementById('candidat_score');
    
    if (!scoreElement || !scoreContainer) return;
    
    let scoreClass = 'poor';
    if (score >= 80) scoreClass = 'excellent';
    else if (score >= 60) scoreClass = 'good';
    else if (score >= 40) scoreClass = 'average';
    
    scoreElement.textContent = score;
    scoreElement.className = `score-value candidate-score ${scoreClass}`;
    
    scoreContainer.style.display = 'flex';
  }

  async function verifierDisponibiliteCandidat(candidatId) {
    console.log('📅 Vérification disponibilité pour candidat:', candidatId);
    
    const disponibiliteElement = document.getElementById('candidat_disponibilite');
    if (!disponibiliteElement) return;

    disponibiliteElement.style.display = 'flex';
    disponibiliteElement.className = 'availability-indicator loading';
    disponibiliteElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Vérification...';

    try {
      const url = `/interim/ajax/verifier-disponibilite-candidat/?candidat_id=${candidatId}&date_debut={{ demande.date_debut|date:"Y-m-d" }}&date_fin={{ demande.date_fin|date:"Y-m-d" }}`;
      
      const response = await fetch(url, {
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      });
      
      const data = await response.json();
      
      if (data.disponible) {
        disponibiliteElement.className = 'availability-indicator available';
        disponibiliteElement.innerHTML = '<i class="fas fa-check"></i> ' + data.raison;
      } else {
        disponibiliteElement.className = 'availability-indicator unavailable';
        disponibiliteElement.innerHTML = '<i class="fas fa-times"></i> ' + data.raison;
      }
    } catch (error) {
      console.error('Erreur vérification disponibilité:', error);
      disponibiliteElement.className = 'availability-indicator unavailable';
      disponibiliteElement.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Erreur de vérification';
    }
  }

  // ================================================================
  // FONCTIONS DE TRI ET FILTRAGE
  // ================================================================
  
  window.changerTri = function() {
    const triSelect = document.getElementById('triSelect');
    const url = new URL(window.location);
    url.searchParams.set('tri', triSelect.value);
    window.location.href = url.toString();
  };

  window.inverserOrdre = function() {
    const url = new URL(window.location);
    const ordreActuel = url.searchParams.get('ordre') || 'desc';
    const nouvelOrdre = ordreActuel === 'desc' ? 'asc' : 'desc';
    url.searchParams.set('ordre', nouvelOrdre);
    window.location.href = url.toString();
  };

  // ================================================================
  // FONCTIONS DE GESTION DES SÉLECTIONS
  // ================================================================
  
  window.toggleSelectAll = function(checkbox) {
    console.log('Toggle select all:', checkbox.checked);
    const checkboxes = document.querySelectorAll('.proposition-checkbox');
    checkboxes.forEach(cb => {
      cb.checked = checkbox.checked;
    });
    updateSelectionCount();
  };
  
  window.updateSelectionCount = function() {
    const checkboxes = document.querySelectorAll('.proposition-checkbox:checked');
    const count = checkboxes.length;
    
    console.log('Update selection count:', count);
    
    // Mettre à jour les propositions sélectionnées
    propositionsSelectionnees = Array.from(checkboxes).map(cb => cb.value);
    
    // Activer/désactiver les boutons d'action
    const btnsActions = document.querySelectorAll('.actions-rapides .btn');
    btnsActions.forEach(btn => {
      if (count > 0) {
        btn.removeAttribute('disabled');
      } else {
        btn.setAttribute('disabled', 'disabled');
      }
    });
  };

  // ================================================================
  // FONCTIONS D'ACTIONS SUR LES CANDIDATS
  // ================================================================
  
  window.voirDetailCandidat = function(candidatId, propositionId) {
    console.log('Voir détail candidat:', candidatId, 'proposition:', propositionId);
    showLoading();
    
    fetch(`{{ url_scores_details }}?candidat_id=${candidatId}&proposition_id=${propositionId}`, {
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        document.getElementById('modalDetailCandidatBody').innerHTML = data.html;
        const modal = new bootstrap.Modal(document.getElementById('modalDetailCandidat'));
        modal.show();
      } else {
        showToast('Erreur', 'Impossible de charger les détails du candidat', 'error');
      }
    })
    .catch(error => {
      console.error('Erreur détail candidat:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  window.evaluerCandidat = function(propositionId) {
    console.log('Évaluer candidat proposition:', propositionId);
    
    // Charger les données de la proposition
    const row = document.querySelector(`#row_${propositionId}`);
    if (!row) return;
    
    // Configurer la modal
    document.getElementById('propositionIdEval').value = propositionId;
    
    // Charger les infos candidat dans la modal (simulation)
    const candidatNom = row.querySelector('.candidat-nom').textContent;
    const candidatPoste = row.querySelector('.poste-titre')?.textContent || 'N/A';
    
    document.getElementById('candidatResumeEval').innerHTML = `
      <div class="candidat-resume-info">
        <h6>${candidatNom}</h6>
        <p>Poste actuel: ${candidatPoste}</p>
      </div>
    `;
    
    // Réinitialiser le formulaire
    document.getElementById('formEvaluationCandidat').reset();
    document.getElementById('scoreRange').value = 50;
    document.getElementById('scoreAjuste').value = 50;
    
    // Afficher la modal
    const modal = new bootstrap.Modal(document.getElementById('modalEvaluationCandidat'));
    modal.show();
  };

  window.retenirCandidat = function(propositionId) {
    console.log('Retenir candidat:', propositionId);
    ouvrirModalDecision(propositionId, 'RETENIR');
  };

  window.rejeterCandidat = function(propositionId) {
    console.log('Rejeter candidat:', propositionId);
    ouvrirModalDecision(propositionId, 'REJETER');
  };

  function ouvrirModalDecision(propositionId, action) {
    const modal = document.getElementById('modalDecisionCandidat');
    const titre = document.getElementById('modalDecisionTitre');
    const header = document.getElementById('modalDecisionHeader');
    const btnConfirmer = document.getElementById('btnConfirmerDecision');
    const divMotif = document.getElementById('divMotifRefus');
    const divPriorite = document.getElementById('divPrioriteCandidat');
    
    document.getElementById('propositionIdDecision').value = propositionId;
    document.getElementById('actionDecision').value = action;
    
    // Charger les infos candidat (simulation)
    const row = document.querySelector(`tr[id*="${propositionId}"]`);
    const candidatNom = row?.querySelector('.candidat-nom')?.textContent || 'Candidat';
    
    document.getElementById('candidatDecisionResume').innerHTML = `
      <div class="alert alert-info">
        <strong>Candidat:</strong> ${candidatNom}
      </div>
    `;
    
    if (action === 'RETENIR') {
      titre.innerHTML = '<i class="fas fa-check"></i> Retenir le candidat';
      header.className = 'modal-header bg-success text-white';
      btnConfirmer.className = 'btn btn-success';
      btnConfirmer.innerHTML = '<i class="fas fa-check"></i> Retenir ce candidat';
      divMotif.style.display = 'none';
      divPriorite.style.display = 'block';
    } else {
      titre.innerHTML = '<i class="fas fa-times"></i> Rejeter le candidat';
      header.className = 'modal-header bg-danger text-white';
      btnConfirmer.className = 'btn btn-danger';
      btnConfirmer.innerHTML = '<i class="fas fa-times"></i> Rejeter ce candidat';
      divMotif.style.display = 'block';
      divPriorite.style.display = 'none';
    }
    
    // Réinitialiser le formulaire
    document.getElementById('formDecisionCandidat').reset();
    
    // Afficher la modal
    const modalInstance = new bootstrap.Modal(modal);
    modalInstance.show();
  }

  window.confirmerDecisionCandidat = function() {
    const form = document.getElementById('formDecisionCandidat');
    const formData = new FormData(form);
    const action = document.getElementById('actionDecision').value;
    
    // Validation
    const commentaire = document.getElementById('commentaireDecision').value.trim();
    if (!commentaire) {
      alert('Le commentaire est obligatoire');
      return;
    }
    
    if (action === 'REJETER') {
      const motif = document.getElementById('motifRefus').value;
      if (!motif) {
        alert('Le motif de refus est obligatoire');
        return;
      }
    }
    
    showLoading();
    
    formData.append('csrfmiddlewaretoken', csrfToken);
    
    fetch(`{{ url_retenir_proposition }}`, {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        bootstrap.Modal.getInstance(document.getElementById('modalDecisionCandidat')).hide();
        showToast('Succès', data.message, 'success');
        setTimeout(() => window.location.reload(), 2000);
      } else {
        showToast('Erreur', data.error, 'error');
      }
    })
    .catch(error => {
      console.error('Erreur décision candidat:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  // ================================================================
  // FONCTIONS D'ÉVALUATION
  // ================================================================
  
  window.updateScoreDisplay = function(value) {
    document.getElementById('scoreAjuste').value = value;
  };

  window.updateScoreRange = function(value) {
    document.getElementById('scoreRange').value = value;
  };

  window.sauvegarderEvaluation = function() {
    const form = document.getElementById('formEvaluationCandidat');
    const formData = new FormData(form);
    
    // Validation
    const commentaire = document.getElementById('commentaireEvaluation').value.trim();
    if (!commentaire) {
      alert('Le commentaire d\'évaluation est obligatoire');
      return;
    }
    
    showLoading();
    
    formData.append('csrfmiddlewaretoken', csrfToken);
    
    fetch(`{{ url_evaluer_proposition }}`, {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        bootstrap.Modal.getInstance(document.getElementById('modalEvaluationCandidat')).hide();
        showToast('Succès', 'Évaluation sauvegardée avec succès', 'success');
        
        // Mettre à jour la ligne du tableau
        const propositionId = document.getElementById('propositionIdEval').value;
        const row = document.querySelector(`tr[id*="${propositionId}"]`);
        if (row && data.nouveau_score) {
          const scoreElement = row.querySelector('.score-principal');
          if (scoreElement) {
            scoreElement.textContent = data.nouveau_score;
            scoreElement.className = `score-principal ${data.score_classe}`;
          }
        }
        
      } else {
        showToast('Erreur', data.error, 'error');
      }
    })
    .catch(error => {
      console.error('Erreur sauvegarde évaluation:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  // ================================================================
  // FONCTIONS D'AJOUT DE PROPOSITION
  // ================================================================
  
  window.ouvrirAjoutProposition = function() {
    console.log('Ouvrir ajout proposition');
    
    // Réinitialiser le formulaire
    document.getElementById('formAjoutProposition').reset();
    masquerInfosEmploye('candidat');
    document.getElementById('btnSoumettreProposition').disabled = true;
    
    // Afficher la modal
    const modal = new bootstrap.Modal(document.getElementById('modalAjoutProposition'));
    modal.show();
  };

  function validerFormulaireProposition() {
    const candidatId = getElement('candidatId')?.value;
    const justification = getElement('justificationProposition')?.value?.trim();
    
    document.getElementById('btnSoumettreProposition').disabled = !(candidatId && justification && justification.length >= 10);
  }

  window.soumettreNouvelleProposition = function() {
    const form = document.getElementById('formAjoutProposition');
    const formData = new FormData(form);
    
    showLoading();
    
    formData.append('csrfmiddlewaretoken', csrfToken);
    
    fetch(`{{ url_ajouter_proposition }}`, {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        bootstrap.Modal.getInstance(document.getElementById('modalAjoutProposition')).hide();
        showToast('Succès', 'Proposition ajoutée avec succès', 'success');
        setTimeout(() => window.location.reload(), 2000);
      } else {
        showToast('Erreur', data.error, 'error');
      }
    })
    .catch(error => {
      console.error('Erreur ajout proposition:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  // ================================================================
  // FONCTIONS D'AFFICHAGE DES DÉTAILS
  // ================================================================
  
  window.voirScoreDetail = function(propositionId) {
    console.log('Voir détail score proposition:', propositionId);
    showLoading();
    
    fetch(`{{ url_scores_details }}?proposition_id=${propositionId}`, {
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        document.getElementById('modalDetailScoreBody').innerHTML = data.html;
        const modal = new bootstrap.Modal(document.getElementById('modalDetailScore'));
        modal.show();
      } else {
        showToast('Erreur', 'Impossible de charger les détails du score', 'error');
      }
    })
    .catch(error => {
      console.error('Erreur détail score:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  window.voirJustification = function(propositionId) {
    console.log('Voir justification proposition:', propositionId);
    showLoading();
    
    fetch(`/interim/ajax/justification-proposition/?proposition_id=${propositionId}`, {
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        document.getElementById('modalJustificationBody').innerHTML = data.html;
        const modal = new bootstrap.Modal(document.getElementById('modalJustification'));
        modal.show();
      } else {
        showToast('Erreur', 'Impossible de charger la justification', 'error');
      }
    })
    .catch(error => {
      console.error('Erreur justification:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  window.voirHistoriqueCandidat = function(candidatId) {
    console.log('Voir historique candidat:', candidatId);
    window.open(`/interim/candidat/${candidatId}/historique/`, '_blank');
  };

  // ================================================================
  // FONCTIONS UTILITAIRES
  // ================================================================
  
  function showLoading() {
    document.getElementById('loadingOverlay').style.display = 'flex';
  }
  
  function hideLoading() {
    document.getElementById('loadingOverlay').style.display = 'none';
  }
  
  function showToast(titre, message, type = 'info') {
    try {
      const toastContainer = document.querySelector('.toast-container');
      if (!toastContainer) {
        console.warn('⚠️ Toast container non trouvé');
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
      
      // Vérifier si Bootstrap est disponible
      if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
        const toast = new bootstrap.Toast(toastElement, {
          autohide: true,
          delay: type === 'error' ? 8000 : 5000
        });
        
        toast.show();
        
        // Nettoyer après fermeture
        toastElement.addEventListener('hidden.bs.toast', function() {
          this.remove();
        });
      } else {
        // Fallback sans Bootstrap
        console.warn('⚠️ Bootstrap non disponible, affichage toast simple');
        toastElement.style.display = 'block';
        toastElement.style.opacity = '1';
        
        // Auto-suppression après délai
        setTimeout(() => {
          if (toastElement.parentNode) {
            toastElement.parentNode.removeChild(toastElement);
          }
        }, type === 'error' ? 8000 : 5000);
      }
    } catch (error) {
      console.error('❌ Erreur dans showToast:', error);
      // Fallback ultime: console.log
      console.log(`${titre}: ${message}`);
    }
  }

  // ================================================================
  // FONCTIONS D'ÉVALUATION EN MASSE
  // ================================================================
  
  window.evaluationRapide = function(action) {
    console.log('Évaluation rapide:', action, 'pour', propositionsSelectionnees.length, 'propositions');
    
    if (propositionsSelectionnees.length === 0) {
      alert('Veuillez sélectionner au moins une proposition');
      return;
    }
    
    const commentaire = prompt(`Commentaire pour ${action.toLowerCase()} les propositions sélectionnées:`);
    if (!commentaire) return;
    
    showLoading();
    
    const formData = new FormData();
    formData.append('action', action);
    formData.append('commentaire', commentaire);
    formData.append('csrfmiddlewaretoken', csrfToken);
    
    propositionsSelectionnees.forEach(id => {
      formData.append('propositions_ids[]', id);
    });
    
    fetch('/interim/propositions/evaluation-masse/', {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        showToast('Succès', data.message, 'success');
        setTimeout(() => window.location.reload(), 2000);
      } else {
        showToast('Erreur', data.error, 'error');
      }
    })
    .catch(error => {
      console.error('Erreur évaluation masse:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  // ================================================================
  // FONCTIONS AVANCÉES
  // ================================================================

  window.ajusterScore = function(propositionId) {
    console.log('Ajuster score proposition:', propositionId);
    
    const nouveauScore = prompt('Nouveau score (0-100):');
    if (!nouveauScore || isNaN(nouveauScore) || nouveauScore < 0 || nouveauScore > 100) {
      alert('Score invalide. Veuillez entrer un nombre entre 0 et 100.');
      return;
    }
    
    const motif = prompt('Motif de l\'ajustement:');
    if (!motif) return;
    
    showLoading();
    
    const formData = new FormData();
    formData.append('proposition_id', propositionId);
    formData.append('nouveau_score', nouveauScore);
    formData.append('motif_ajustement', motif);
    formData.append('csrfmiddlewaretoken', csrfToken);
    
    fetch('/interim/propositions/ajuster-score/', {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        showToast('Succès', 'Score ajusté avec succès', 'success');
        
        // Mettre à jour l'affichage du score
        const row = document.querySelector(`tr[id*="${propositionId}"]`);
        if (row) {
          const scoreElement = row.querySelector('.score-principal');
          if (scoreElement) {
            scoreElement.textContent = nouveauScore;
            scoreElement.className = `score-principal ${data.score_classe}`;
          }
        }
      } else {
        showToast('Erreur', data.error, 'error');
      }
    })
    .catch(error => {
      console.error('Erreur ajustement score:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    })
    .finally(() => {
      hideLoading();
    });
  };

  // ================================================================
  // INITIALISATION DES EVENT LISTENERS
  // ================================================================

  // Recherche de candidat avec debounce - VERSION DEBUG
  const candidatMatriculeInput = document.getElementById('candidatMatricule');
  console.log('🔍 Recherche input candidat:', candidatMatriculeInput);
  
  if (candidatMatriculeInput) {
    console.log('✅ Input candidat trouvé, ajout des listeners');
    
    const debouncedSearchCandidat = debounce((matricule) => {
      console.log('🚀 Appel debounced pour matricule:', matricule);
      rechercherEmployeCandidat(matricule);
    }, 500);

    candidatMatriculeInput.addEventListener('input', function() {
      const matricule = this.value.trim();
      console.log('⌨️ Input event - matricule saisi:', matricule);
      debouncedSearchCandidat(matricule);
    });
  } else {
    console.error('❌ Input candidatMatricule non trouvé !');
  }

  // ================================================================
  // FONCTION SPÉCIFIQUE POUR LA RECHERCHE DE CANDIDAT - VERSION DEBUG
  // ================================================================

  async function rechercherEmployeCandidat(matricule) {
    console.log(`🔍 DEBUT rechercherEmployeCandidat: matricule="${matricule}"`);
    
    // Test de tous les éléments HTML
    console.log('🧪 Test des éléments HTML:');
    console.log('- candidat_info:', document.getElementById('candidat_info'));
    console.log('- candidat_loading:', document.getElementById('candidat_loading'));
    console.log('- candidat_error:', document.getElementById('candidat_error'));
    console.log('- candidatId:', document.getElementById('candidatId'));
    console.log('- candidat_nom_complet:', document.getElementById('candidat_nom_complet'));
    
    if (!matricule || matricule.length < 2) {
      console.log(`❌ Matricule invalide: "${matricule}"`);
      masquerInfosCandidatModal();
      return;
    }

    // Vérifier le cache
    const cacheKey = `${matricule}_candidat_modal`;
    const cached = employeeCache.get(cacheKey);
    
    if (cached && (Date.now() - cached.timestamp) < CACHE_DURATION) {
      console.log(`💾 Cache hit pour ${matricule}`);
      afficherInfosCandidatModal(cached.data);
      return;
    }

    afficherChargementCandidatModal(true);
    console.log(`🔍 Requête AJAX pour ${matricule}`);

    try {
      const requestData = {
        matricule: matricule,
        force_kelio_sync: false
      };
      
      console.log(`📤 Envoi requête candidat:`, requestData);
      console.log(`📤 CSRF Token:`, csrfToken);
      
      const response = await fetch('/interim/ajax/rechercher-employe/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(requestData)
      });

      console.log(`📨 Status candidat: ${response.status} ${response.statusText}`);

      // Si erreur CSRF, essayer avec FormData
      if (response.status === 403) {
        console.log('🔄 Tentative avec FormData après erreur CSRF...');
        
        const formData = new FormData();
        formData.append('matricule', matricule);
        formData.append('force_kelio_sync', 'false');
        formData.append('csrfmiddlewaretoken', csrfToken);
        
        const retryResponse = await fetch('/interim/ajax/rechercher-employe/', {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          },
          body: formData
        });
        
        console.log(`📨 Retry Status: ${retryResponse.status} ${retryResponse.statusText}`);
        
        if (!retryResponse.ok) {
          throw new Error(`Erreur HTTP après retry ${retryResponse.status}: ${retryResponse.statusText}`);
        }
        
        const retryResponseText = await retryResponse.text();
        console.log(`📨 Retry Réponse:`, retryResponseText);
        
        try {
          data = JSON.parse(retryResponseText);
          console.log(`📨 Retry Données parsées:`, data);
        } catch (parseError) {
          console.error(`❌ Erreur parsing JSON retry:`, parseError);
          throw new Error(`Réponse non-JSON: ${retryResponseText.substring(0, 100)}...`);
        }
      } else {
        if (!response.ok) {
          throw new Error(`Erreur HTTP ${response.status}: ${response.statusText}`);
        }

        const responseText = await response.text();
        console.log(`📨 Réponse candidat brute:`, responseText);

        try {
          data = JSON.parse(responseText);
          console.log(`📨 Données candidat parsées:`, data);
        } catch (parseError) {
          console.error(`❌ Erreur parsing JSON candidat:`, parseError);
          console.error(`❌ Texte de réponse:`, responseText);
          throw new Error(`Réponse non-JSON: ${responseText.substring(0, 100)}...`);
        }
      }

      // Traitement de la réponse
      if (data && data.success === true) {
        console.log(`✅ Succès candidat détecté`);
        
        if (data.employe) {
          console.log(`👤 Candidat trouvé:`, data.employe);
          
          // Mettre en cache
          employeeCache.set(cacheKey, {
            data: data,
            timestamp: Date.now()
          });

          // Afficher les informations
          console.log('🧪 AVANT afficherInfosCandidatModal');
          try {
            afficherInfosCandidatModal(data);
            console.log('✅ afficherInfosCandidatModal exécutée');
          } catch (errorAffichage) {
            console.error('❌ Erreur dans afficherInfosCandidatModal:', errorAffichage);
          }
          
          // Toast sans Bootstrap si nécessaire
          try {
            showToast('Succès', `Candidat ${matricule} trouvé avec succès`, 'success');
          } catch (errorToast) {
            console.warn('⚠️ Erreur toast (non critique):', errorToast);
            // Notification alternative simple
            console.log(`✅ Candidat ${matricule} trouvé avec succès`);
          }
          
          // Calculer le score et vérifier disponibilité
          setTimeout(() => {
            console.log('⏰ Calcul score et disponibilité...');
            try {
              calculerScoreCandidat(data.employe.id);
              verifierDisponibiliteCandidat(data.employe.id);
            } catch (errorCalc) {
              console.error('❌ Erreur calculs:', errorCalc);
            }
          }, 100);
          
        } else {
          console.log(`❌ Pas de candidat dans la réponse`);
          console.log(`❌ Structure data:`, Object.keys(data));
          afficherErreurCandidatModal('Réponse invalide du serveur - pas d\'employé');
        }
        
      } else if (data && data.success === false) {
        console.log(`❌ Échec candidat explicite:`, data.error);
        afficherErreurCandidatModal(data.error || 'Erreur du serveur');
        
      } else {
        console.log(`❌ Structure de réponse candidat inattendue:`, data);
        console.log(`❌ data.success:`, data?.success);
        console.log(`❌ Toute la réponse:`, data);
        afficherErreurCandidatModal('Réponse serveur invalide');
      }

    } catch (error) {
      console.error('❌ ERREUR dans rechercherEmployeCandidat:', error);
      
      let errorMessage = 'Erreur de communication avec le serveur';
      
      if (error.message.includes('404')) {
        errorMessage = 'Service de recherche non disponible';
      } else if (error.message.includes('500')) {
        errorMessage = 'Erreur serveur temporaire';
      } else if (error.message.includes('JSON')) {
        errorMessage = 'Erreur de format de réponse';
      }
      
      afficherErreurCandidatModal(errorMessage);
      
    } finally {
      console.log(`🔍 FIN rechercherEmployeCandidat pour ${matricule}`);
      afficherChargementCandidatModal(false);
    }
  }

  // ================================================================
  // FONCTIONS D'AFFICHAGE SPÉCIFIQUES MODAL CANDIDAT - VERSION DEBUG
  // ================================================================

  function afficherInfosCandidatModal(data) {
    console.log(`📝 === DEBUT afficherInfosCandidatModal ===`);
    console.log(`📝 Data reçue:`, data);
    
    const employe = data.employe;
    if (!employe) {
      console.error(`❌ Pas de données candidat dans data.employe`);
      console.error(`❌ Clés disponibles dans data:`, Object.keys(data));
      return;
    }

    console.log(`📝 Données employé:`, employe);
    console.log(`📝 Clés employé:`, Object.keys(employe));

    // Tester tous les éléments avant manipulation
    console.log('🧪 === TEST ÉLÉMENTS AVANT AFFICHAGE ===');
    const candidatError = document.getElementById('candidat_error');
    const candidatLoading = document.getElementById('candidat_loading');
    const candidatInfo = document.getElementById('candidat_info');
    const candidatId = document.getElementById('candidatId');
    const nomElement = document.getElementById('candidat_nom_complet');
    const matriculeElement = document.getElementById('candidat_matricule_display');
    const sexeElement = document.getElementById('candidat_sexe');
    const ancienneteElement = document.getElementById('candidat_anciennete');
    const departementElement = document.getElementById('candidat_departement');
    const siteElement = document.getElementById('candidat_site');
    const posteElement = document.getElementById('candidat_poste');
    const syncStatusElement = document.getElementById('candidat_sync_status');

    console.log('- candidatError:', candidatError ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- candidatLoading:', candidatLoading ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- candidatInfo:', candidatInfo ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- candidatId:', candidatId ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- nomElement:', nomElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- matriculeElement:', matriculeElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- sexeElement:', sexeElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- ancienneteElement:', ancienneteElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- departementElement:', departementElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- siteElement:', siteElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- posteElement:', posteElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');
    console.log('- syncStatusElement:', syncStatusElement ? '✅ TROUVÉ' : '❌ NON TROUVÉ');

    // FORCER L'AFFICHAGE MÊME SI ÉLÉMENTS MANQUANTS
    console.log('🔧 === FORÇAGE AFFICHAGE ===');

    // Masquer erreurs et chargement
    if (candidatError) {
      candidatError.style.display = 'none';
      console.log('✅ candidatError masqué');
    }
    if (candidatLoading) {
      candidatLoading.style.display = 'none';
      console.log('✅ candidatLoading masqué');
    }

    // Remplir les informations principales avec vérifications
    if (nomElement) {
      const nomValue = employe.nom_complet || employe.nom || 'Nom non disponible';
      nomElement.textContent = nomValue;
      console.log(`✅ Nom défini: "${nomValue}"`);
    } else {
      console.error('❌ nomElement (candidat_nom_complet) NON TROUVÉ !');
    }
    
    if (matriculeElement) {
      const matriculeValue = employe.matricule || '';
      matriculeElement.textContent = matriculeValue;
      console.log(`✅ Matricule défini: "${matriculeValue}"`);
    } else {
      console.error('❌ matriculeElement (candidat_matricule_display) NON TROUVÉ !');
    }
    
    // Détails avec icônes
    if (sexeElement && employe.sexe) {
      const sexeValue = employe.sexe === 'M' ? '👨 Homme' : '👩 Femme';
      sexeElement.textContent = sexeValue;
      console.log(`✅ Sexe défini: "${sexeValue}"`);
    }
    
    if (ancienneteElement && employe.anciennete) {
      const ancienneteValue = `⏰ ${employe.anciennete}`;
      ancienneteElement.textContent = ancienneteValue;
      console.log(`✅ Ancienneté définie: "${ancienneteValue}"`);
    }

    // Informations organisationnelles
    if (departementElement && employe.departement) {
      const departementValue = `🏢 ${employe.departement}`;
      departementElement.textContent = departementValue;
      console.log(`✅ Département défini: "${departementValue}"`);
    }
    
    if (siteElement && employe.site) {
      const siteValue = `📍 ${employe.site}`;
      siteElement.textContent = siteValue;
      console.log(`✅ Site défini: "${siteValue}"`);
    }
    
    if (posteElement && employe.poste) {
      const posteValue = `💼 ${employe.poste}`;
      posteElement.textContent = posteValue;
      console.log(`✅ Poste défini: "${posteValue}"`);
    }

    // Statut de synchronisation
    if (syncStatusElement && data.sync_info) {
      if (data.sync_info.is_recent) {
        syncStatusElement.textContent = 'Données à jour';
        syncStatusElement.className = 'employee-sync-status sync-status-recent';
      } else {
        syncStatusElement.textContent = 'Données locales';
        syncStatusElement.className = 'employee-sync-status sync-status-local';
      }
      console.log(`✅ Sync status défini`);
    }

    // Définir l'ID caché
    if (candidatId && employe.id) {
      candidatId.value = employe.id;
      console.log(`✅ ID candidat défini: ${employe.id}`);
    } else {
      console.error('❌ candidatId NON TROUVÉ ou employe.id manquant !');
      if (!candidatId) console.error('❌ Element candidatId non trouvé');
      if (!employe.id) console.error('❌ employe.id manquant:', employe);
    }

    // FORCER L'AFFICHAGE DU CONTAINER
    if (candidatInfo) {
      candidatInfo.style.display = 'block';
      candidatInfo.style.visibility = 'visible';
      candidatInfo.style.opacity = '1';
      console.log('✅ candidatInfo FORCÉ à être visible');
      
      // Test si réellement visible
      const computedStyle = window.getComputedStyle(candidatInfo);
      console.log('🧪 Style calculé candidatInfo:');
      console.log('- display:', computedStyle.display);
      console.log('- visibility:', computedStyle.visibility);
      console.log('- opacity:', computedStyle.opacity);
      console.log('- offsetHeight:', candidatInfo.offsetHeight);
      console.log('- offsetWidth:', candidatInfo.offsetWidth);
    } else {
      console.error('❌ candidatInfo (candidat_info) NON TROUVÉ !');
      
      // Chercher tous les éléments qui pourraient correspondre
      console.log('🔍 Recherche d\'éléments similaires:');
      const allCandidatElements = document.querySelectorAll('[id*="candidat"]');
      allCandidatElements.forEach(el => {
        console.log(`- Trouvé: ${el.id} (${el.tagName})`);
      });
    }

    // Déclencher la validation du formulaire
    try {
      validerFormulaireProposition();
      console.log('✅ Validation formulaire déclenchée');
    } catch (errorValidation) {
      console.error('❌ Erreur validation formulaire:', errorValidation);
    }
    
    console.log(`📝 === FIN afficherInfosCandidatModal ===`);
  }

  function afficherErreurCandidatModal(message) {
    console.log(`❌ Affichage erreur candidat modal: ${message}`);
    
    const candidatInfo = document.getElementById('candidat_info');
    const candidatLoading = document.getElementById('candidat_loading');
    const candidatError = document.getElementById('candidat_error');
    const candidatId = document.getElementById('candidatId');

    console.log('🧪 Éléments pour erreur:');
    console.log('- candidatInfo:', candidatInfo);
    console.log('- candidatLoading:', candidatLoading);
    console.log('- candidatError:', candidatError);
    console.log('- candidatId:', candidatId);

    if (candidatInfo) candidatInfo.style.display = 'none';
    if (candidatLoading) candidatLoading.style.display = 'none';
    
    if (candidatError) {
      const messageElement = candidatError.querySelector('.error-message');
      console.log('- messageElement:', messageElement);
      if (messageElement) {
        messageElement.textContent = message;
      }
      candidatError.style.display = 'flex';
      console.log('✅ Erreur affichée');
    } else {
      console.error('❌ candidatError non trouvé !');
    }

    // Vider l'ID caché
    if (candidatId) {
      candidatId.value = '';
    }

    // Déclencher la validation du formulaire
    validerFormulaireProposition();
  }

  function afficherChargementCandidatModal(show) {
    console.log(`⏳ Affichage chargement candidat: ${show}`);
    
    const candidatLoading = document.getElementById('candidat_loading');
    const candidatInfo = document.getElementById('candidat_info');
    const candidatError = document.getElementById('candidat_error');

    console.log('🧪 Éléments pour chargement:');
    console.log('- candidatLoading:', candidatLoading);
    console.log('- candidatInfo:', candidatInfo);
    console.log('- candidatError:', candidatError);

    if (candidatLoading) {
      candidatLoading.style.display = show ? 'flex' : 'none';
      console.log(`✅ candidatLoading: ${show ? 'affiché' : 'masqué'}`);
    } else {
      console.error('❌ candidatLoading non trouvé !');
    }
    
    if (show) {
      if (candidatInfo) candidatInfo.style.display = 'none';
      if (candidatError) candidatError.style.display = 'none';
    }
  }

  function masquerInfosCandidatModal() {
    console.log('🫥 Masquer infos candidat modal');
    
    const candidatInfo = document.getElementById('candidat_info');
    const candidatError = document.getElementById('candidat_error');
    const candidatLoading = document.getElementById('candidat_loading');
    const candidatId = document.getElementById('candidatId');
    const candidatScore = document.getElementById('candidat_score');
    const candidatDisponibilite = document.getElementById('candidat_disponibilite');

    console.log('🧪 Éléments à masquer:');
    console.log('- candidatInfo:', candidatInfo);
    console.log('- candidatError:', candidatError);
    console.log('- candidatLoading:', candidatLoading);
    console.log('- candidatId:', candidatId);
    console.log('- candidatScore:', candidatScore);
    console.log('- candidatDisponibilite:', candidatDisponibilite);

    if (candidatInfo) candidatInfo.style.display = 'none';
    if (candidatError) candidatError.style.display = 'none';
    if (candidatLoading) candidatLoading.style.display = 'none';
    if (candidatScore) candidatScore.style.display = 'none';
    if (candidatDisponibilite) candidatDisponibilite.style.display = 'none';
    
    if (candidatId) {
      candidatId.value = '';
    }

    // Déclencher la validation du formulaire
    validerFormulaireProposition();
  }

  // Validation en temps réel du formulaire d'ajout
  const justificationInput = getElement('justificationProposition');
  if (justificationInput) {
    justificationInput.addEventListener('input', validerFormulaireProposition);
  }

  // Initialiser les event listeners pour les checkboxes
  document.querySelectorAll('.proposition-checkbox').forEach(checkbox => {
    checkbox.addEventListener('change', updateSelectionCount);
  });

  // Auto-soumission des filtres avec délai
  const filtreInputs = document.querySelectorAll('#filtresForm input, #filtresForm select');
  let timeoutFiltres;
  
  filtreInputs.forEach(input => {
    input.addEventListener('change', function() {
      clearTimeout(timeoutFiltres);
      timeoutFiltres = setTimeout(() => {
        console.log('Auto-soumission des filtres');
        document.getElementById('filtresForm').submit();
      }, 1000);
    });
  });

  // Raccourcis clavier
  document.addEventListener('keydown', function(e) {
    // Ctrl+A : Sélectionner tout
    if (e.ctrlKey && e.key === 'a') {
      e.preventDefault();
      const selectAllCheckbox = document.getElementById('selectAll');
      if (selectAllCheckbox) {
        selectAllCheckbox.checked = !selectAllCheckbox.checked;
        toggleSelectAll(selectAllCheckbox);
        console.log('Raccourci Ctrl+A utilisé');
      }
    }
    
    // F5 : Actualiser
    if (e.key === 'F5') {
      e.preventDefault();
      console.log('Raccourci F5 - Actualisation');
      window.location.reload();
    }
    
    // Escape : Fermer les modales ouvertes
    if (e.key === 'Escape') {
      const modals = document.querySelectorAll('.modal.show');
      modals.forEach(modal => {
        const modalInstance = bootstrap.Modal.getInstance(modal);
        if (modalInstance) {
          modalInstance.hide();
        }
      });
    }
    
    // N : Nouvelle proposition (si autorisé)
    if (e.key === 'n' && !e.ctrlKey && !e.altKey) {
      const btnAjouter = document.querySelector('[onclick="ouvrirAjoutProposition()"]');
      if (btnAjouter && !btnAjouter.disabled) {
        e.preventDefault();
        ouvrirAjoutProposition();
        console.log('Raccourci N - Nouvelle proposition');
      }
    }
  });

  // ================================================================
  // FONCTIONS D'AMÉLIORATION UX
  // ================================================================

  // Confirmation avant navigation si des propositions sont sélectionnées
  window.addEventListener('beforeunload', function(e) {
    if (propositionsSelectionnees.length > 0) {
      const message = `Vous avez ${propositionsSelectionnees.length} proposition(s) sélectionnée(s). Êtes-vous sûr de vouloir quitter cette page ?`;
      e.returnValue = message;
      return message;
    }
  });

  // Tooltips Bootstrap
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[title]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });

  // Animation d'entrée pour les lignes du tableau
  const rows = document.querySelectorAll('.table-propositions tbody tr');
  rows.forEach((row, index) => {
    row.style.opacity = '0';
    row.style.transform = 'translateY(20px)';
    
    setTimeout(() => {
      row.style.transition = 'all 0.3s ease';
      row.style.opacity = '1';
      row.style.transform = 'translateY(0)';
    }, index * 50);
  });

  // Auto-rafraîchissement toutes les 5 minutes
  setInterval(() => {
    console.log('Vérification automatique nouvelles propositions...');
    fetch(window.location.href + '&ajax=1', {
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.nouvelles_propositions && data.nouvelles_propositions > 0) {
        showToast(
          'Nouvelles propositions',
          `${data.nouvelles_propositions} nouvelle(s) proposition(s) ajoutée(s)`,
          'info'
        );
      }
    })
    .catch(error => {
      console.log('Erreur vérification nouvelles propositions:', error);
    });
  }, 5 * 60 * 1000); // 5 minutes

  // ================================================================
  // FINALISATION DE L'INITIALISATION
  // ================================================================

  // Initialisation finale
  updateSelectionCount();

  // Gestion des erreurs globales
  window.addEventListener('error', function(e) {
    console.error('Erreur JavaScript globale:', e.error);
    showToast('Erreur', 'Une erreur inattendue s\'est produite', 'error');
  });

  console.log('✅ Interface de gestion des propositions initialisée avec succès');
});

// ================================================================
// FONCTIONS GLOBALES POUR COMPATIBILITÉ
// ================================================================

// Ces fonctions sont définies globalement pour être accessibles depuis les attributs onclick
window.showLoading = function() {
  document.getElementById('loadingOverlay').style.display = 'flex';
};

window.hideLoading = function() {
  document.getElementById('loadingOverlay').style.display = 'none';
};

window.showToast = function(titre, message, type = 'info') {
  const toastContainer = document.querySelector('.toast-container');
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
  const toast = new bootstrap.Toast(toastElement, {
    autohide: true,
    delay: type === 'error' ? 8000 : 5000
  });
  
  toast.show();
  
  // Nettoyer après fermeture
  toastElement.addEventListener('hidden.bs.toast', function() {
    this.remove();
  });
};

console.log('🎯 Système de gestion des propositions prêt - Version avec recherche d\'employé améliorée');

