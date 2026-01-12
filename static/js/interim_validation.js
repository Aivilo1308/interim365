
// ================================================================
// JAVASCRIPT POUR VALIDATION AVEC MODALES CORRIGÉES
// ================================================================

// Variables globales
let candidatAlternatifTrouve = null;
let propositionAlternativeActive = false;
let debounceTimer = null;
let scoresDetailsCandidats = {}; // Cache des scores détaillés

// ================================================================
// INITIALISATION
// ================================================================

document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation validation workflow avec modales corrigées');
  
  // Initialiser les composants
  initValidationFormulaire();
  initEventListeners();
  configurerEtatInitial();
  
  // Auto-resize des textareas
  document.querySelectorAll('textarea').forEach(textarea => {
    autoResizeTextarea(textarea);
    textarea.addEventListener('input', () => autoResizeTextarea(textarea));
  });
  
  console.log('✅ Interface de validation avec modales fonctionnelles initialisée');
});

// ================================================================
// FONCTIONS POUR LES SCORES DÉTAILLÉS
// ================================================================

async function recupererDetailsScore(candidatMatricule, typeSource, propositionId) {
  try {
    let url;
    if (typeSource === 'proposition' && propositionId) {
      url = `/interim/ajax/proposition/${propositionId}/score-details/`;
    } else if (typeSource === 'automatique') {
      url = `/ajax/candidat/matricule/${candidatMatricule}/score-automatique/{{ demande.id }}/`;
    } else {
      url = `/ajax/candidat/matricule/${candidatMatricule}/score-details/{{ demande.id }}/`;
    }
    
    console.log('🔗 URL appelée:', url);
    
    // Vérifier le cache d'abord
    const cacheKey = `${candidatMatricule}_${typeSource}_${propositionId || 'auto'}`;
    if (scoresDetailsCandidats[cacheKey]) {
      console.log('📋 Utilisation cache scores pour:', cacheKey);
      return { success: true, data: scoresDetailsCandidats[cacheKey] };
    }
    
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/json'
      }
    });
    
    console.log('📡 Réponse HTTP:', response.status, response.statusText);
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const data = await response.json();
    console.log('📊 Données reçues:', data);
    
    // Mettre en cache
    if (data.success) {
      scoresDetailsCandidats[cacheKey] = data.data;
    }
    
    return data;
    
  } catch (error) {
    console.error('❌ Erreur récupération scores AJAX:', error);
    
    return {
      success: false,
      error: error.message || 'Impossible de récupérer les détails du score'
    };
  }
}

async function afficherDetailsScore(candidatMatricule, typeSource, propositionId = null) {
  console.log('📊 Affichage détails score candidat matricule:', candidatMatricule, 'Type:', typeSource, 'PropositionId:', propositionId);
  
  try {
    // Obtenir l'élément modal
    const modalElement = document.getElementById('modalDetailsScore');
    if (!modalElement) {
      console.error('❌ Modale modalDetailsScore non trouvée');
      showToast('Erreur', 'Interface de score non disponible', 'error');
      return;
    }
    
    // Créer et afficher la modale avec compatibilité Bootstrap
    const modal = getBootstrapModal(modalElement);
    if (modal.modal) {
      modal.modal('show'); // Bootstrap 4/jQuery
    } else {
      modal.show(); // Bootstrap 5 ou fallback
    }
    
    // Réinitialiser l'état de la modale
    document.getElementById('scoreModalLoading').style.display = 'block';
    document.getElementById('scoreModalContent').style.display = 'none';
    document.getElementById('scoreModalError').style.display = 'none';
    
    // Récupérer les détails du score
    console.log('🔄 Récupération des détails du score...');
    const scoreDetails = await recupererDetailsScore(candidatMatricule, typeSource, propositionId);
    
    if (scoreDetails && scoreDetails.success) {
      console.log('✅ Détails du score récupérés:', scoreDetails.data);
      
      // Afficher les détails
      afficherContenuDetailsScore(scoreDetails.data);
      
      // Masquer le loading et afficher le contenu
      document.getElementById('scoreModalLoading').style.display = 'none';
      document.getElementById('scoreModalContent').style.display = 'block';
      
      console.log('✅ Modale affichée avec succès');
      
    } else {
      throw new Error(scoreDetails?.error || scoreDetails?.message || 'Erreur de récupération des scores');
    }
    
  } catch (error) {
    console.error('❌ Erreur affichage détails score:', error);
    
    // Afficher l'erreur dans la modale
    document.getElementById('scoreModalLoading').style.display = 'none';
    document.getElementById('scoreModalContent').style.display = 'none';
    document.getElementById('scoreModalError').style.display = 'block';
    
    const errorElement = document.getElementById('scoreModalErrorMessage');
    if (errorElement) {
      errorElement.textContent = error.message || 'Erreur lors du chargement des détails du score';
    }
    
    // Toast pour notification
    showToast('Erreur', error.message || 'Impossible de charger les détails du score', 'error');
  }
}

function afficherContenuDetailsScore(scoreData) {
  try {
    // Mettre à jour le nom du candidat
    document.getElementById('scoreModalCandidatNom').textContent = 
      scoreData.candidat_nom || 'Candidat';
    
    // Score principal
    const scoreFinal = scoreData.score_final || 0;
    const scoreDisplay = document.getElementById('scoreFinalDisplay');
    scoreDisplay.textContent = scoreFinal;
    scoreDisplay.className = `score-final-display ${getScoreClass(scoreFinal)}`;
    
    // Type de score
    document.getElementById('scoreTypeDisplay').textContent = 
      scoreData.type_calcul || 'Score calculé';
    
    // Confiance
    document.getElementById('scoreConfidenceDisplay').textContent = 
      `Confiance: ${scoreData.confiance || 'Moyenne'}`;
    
    // Critères de scoring
    afficherCriteresScoring(scoreData.criteres || {});
    
    // Modificateurs (bonus/pénalités)
    afficherModificateursScore(scoreData.modificateurs || {});
    
    // Commentaires
    afficherCommentairesScore(scoreData.commentaires || []);
    
    // Métadonnées
    afficherMetadonneesScore(scoreData.metadonnees || {});
    
  } catch (error) {
    console.error('Erreur affichage contenu score:', error);
    throw error;
  }
}

function afficherCriteresScoring(criteres) {
  const container = document.getElementById('criteriaScoresContainer');
  container.innerHTML = '';
  
  const criteresListe = [
    { key: 'competences', label: 'Compétences', icon: 'fa-tools' },
    { key: 'experience', label: 'Expérience', icon: 'fa-briefcase' },
    { key: 'disponibilite', label: 'Disponibilité', icon: 'fa-calendar-check' },
    { key: 'proximite', label: 'Proximité', icon: 'fa-map-marker-alt' },
    { key: 'similarite_poste', label: 'Similarité poste', icon: 'fa-user-tie' },
    { key: 'anciennete', label: 'Ancienneté', icon: 'fa-clock' }
  ];
  
  criteresListe.forEach(critere => {
    const score = criteres[critere.key] || 0;
    const pourcentage = Math.min(100, Math.max(0, score));
    
    const critereElement = document.createElement('div');
    critereElement.className = 'criteria-item';
    critereElement.innerHTML = `
      <div class="criteria-header">
        <span class="criteria-name">
          <i class="fas ${critere.icon}"></i>
          ${critere.label}
        </span>
        <span class="criteria-score">${score}</span>
      </div>
      <div class="criteria-progress">
        <div class="criteria-progress-bar" style="width: ${pourcentage}%"></div>
      </div>
    `;
    
    container.appendChild(critereElement);
  });
}

function afficherModificateursScore(modificateurs) {
  const container = document.getElementById('modifiersListContainer');
  container.innerHTML = '';
  
  // Bonus
  const bonus = modificateurs.bonus || {};
  Object.entries(bonus).forEach(([key, value]) => {
    if (value !== 0) {
      const modifierElement = document.createElement('div');
      modifierElement.className = 'modifier-item bonus';
      modifierElement.innerHTML = `
        <span class="modifier-name">
          <i class="fas fa-plus"></i>
          ${formatModifierName(key)}
        </span>
        <span class="modifier-value positive">+${value}</span>
      `;
      container.appendChild(modifierElement);
    }
  });
  
  // Pénalités
  const penalites = modificateurs.penalites || {};
  Object.entries(penalites).forEach(([key, value]) => {
    if (value !== 0) {
      const modifierElement = document.createElement('div');
      modifierElement.className = 'modifier-item penalty';
      modifierElement.innerHTML = `
        <span class="modifier-name">
          <i class="fas fa-minus"></i>
          ${formatModifierName(key)}
        </span>
        <span class="modifier-value negative">-${Math.abs(value)}</span>
      `;
      container.appendChild(modifierElement);
    }
  });
  
  // Si aucun modificateur
  if (container.children.length === 0) {
    container.innerHTML = `
      <div class="modifier-item neutral">
        <span class="modifier-name">
          <i class="fas fa-equals"></i>
          Aucun modificateur appliqué
        </span>
        <span class="modifier-value neutral">0</span>
      </div>
    `;
  }
}

function afficherCommentairesScore(commentaires) {
  const container = document.getElementById('commentsListContainer');
  container.innerHTML = '';
  
  if (commentaires.length === 0) {
    container.innerHTML = `
      <div class="text-center text-muted">
        <i class="fas fa-comment-slash fa-2x mb-2"></i>
        <p>Aucun commentaire d'évaluation</p>
      </div>
    `;
    return;
  }
  
  commentaires.forEach(commentaire => {
    const commentElement = document.createElement('div');
    commentElement.className = 'comment-item';
    commentElement.innerHTML = `
      <div class="comment-header">
        <div>
          <span class="comment-author">${commentaire.auteur || 'Auteur inconnu'}</span>
          <span class="comment-type">${commentaire.type || 'Commentaire'}</span>
        </div>
        <span class="comment-date">${formatDate(commentaire.date)}</span>
      </div>
      <div class="comment-content">${commentaire.contenu || 'Aucun contenu'}</div>
      ${commentaire.score_associe ? `<div class="comment-score">Score associé: ${commentaire.score_associe}</div>` : ''}
    `;
    container.appendChild(commentElement);
  });
}

function afficherMetadonneesScore(metadonnees) {
  const container = document.getElementById('metadataContainer');
  container.innerHTML = '';
  
  const metaItems = [
    { key: 'date_calcul', label: 'Date de calcul', icon: 'fa-calendar', formatter: formatDate },
    { key: 'version_algorithme', label: 'Version algorithme', icon: 'fa-code-branch' },
    { key: 'source_donnees', label: 'Sources de données', icon: 'fa-database' },
    { key: 'calcule_par', label: 'Calculé par', icon: 'fa-user-cog' },
    { key: 'duree_calcul', label: 'Durée calcul', icon: 'fa-stopwatch' },
    { key: 'fiabilite', label: 'Fiabilité', icon: 'fa-shield-alt' }
  ];
  
  metaItems.forEach(item => {
    const value = metadonnees[item.key];
    if (value !== undefined && value !== null && value !== '') {
      const metaElement = document.createElement('div');
      metaElement.className = 'metadata-item';
      metaElement.innerHTML = `
        <div class="metadata-label">
          <i class="fas ${item.icon}"></i>
          ${item.label}
        </div>
        <div class="metadata-value">
          ${item.formatter ? item.formatter(value) : value}
        </div>
      `;
      container.appendChild(metaElement);
    }
  });
  
  // Si aucune métadonnée
  if (container.children.length === 0) {
    container.innerHTML = `
      <div class="text-center text-muted">
        <i class="fas fa-info-circle fa-2x mb-2"></i>
        <p>Aucune métadonnée disponible</p>
      </div>
    `;
  }
}

// ================================================================
// OUVERTURE DE LA MODALE CANDIDATS AUTOMATIQUES
// ================================================================

function ouvrirModaleCandidatsAutomatiques() {
  console.log('📋 Ouverture modale candidats automatiques');
  
  try {
    const modalElement = document.getElementById('modalCandidatsAutomatiques');
    if (!modalElement) {
      console.error('❌ Modale modalCandidatsAutomatiques non trouvée');
      showToast('Erreur', 'Interface candidats automatiques non disponible', 'error');
      return;
    }
    
    // Créer et afficher la modale avec compatibilité Bootstrap
    const modal = getBootstrapModal(modalElement);
    if (modal.modal) {
      modal.modal('show'); // Bootstrap 4/jQuery
    } else {
      modal.show(); // Bootstrap 5 ou fallback
    }
    
    console.log('✅ Modale candidats automatiques ouverte');
    
  } catch (error) {
    console.error('❌ Erreur ouverture modale candidats automatiques:', error);
    showToast('Erreur', 'Impossible d\'ouvrir la liste des candidats', 'error');
  }
}

// ================================================================
// GESTION DES PROPOSITIONS
// ================================================================

function togglePropositionOptions(radioElement) {
  console.log('🔄 Toggle proposition:', radioElement.value);
  
  const value = radioElement.value;
  const isValidation = value.startsWith('VALIDER_');
  
  if (isValidation) {
    const propositionId = value.replace('VALIDER_', '');
    
    // Masquer toutes les autres zones
    document.querySelectorAll('[id^="validation_justification_"]').forEach(zone => {
      zone.style.display = 'none';
    });
    document.querySelectorAll('[id^="refus_justification_"]').forEach(zone => {
      zone.style.display = 'none';
    });
    
    // Désactiver la proposition alternative
    const checkboxAlternative = document.getElementById('proposer_alternative');
    if (checkboxAlternative) {
      checkboxAlternative.checked = false;
      togglePropositionAlternative(false);
    }
    
    // Décocher tous les refus individuels
    document.querySelectorAll('[id^="refuser_"]').forEach(radio => {
      radio.checked = false;
    });
    
    // Afficher la zone de validation pour cette proposition
    const validationZone = document.getElementById('validation_justification_' + propositionId);
    if (validationZone) {
      validationZone.style.display = 'block';
    }
    
    showToast('Validation', 'Proposition sélectionnée pour validation', 'success');
  }
  
  updateValidationButtons();
}

function toggleRefusJustification(propositionId, show) {
  console.log('🔄 Toggle refus justification:', propositionId, show);
  
  const zone = document.getElementById('refus_justification_' + propositionId);
  if (zone) {
    zone.style.display = show ? 'block' : 'none';
  }
  
  if (show) {
    // Décocher la validation de cette proposition si elle était sélectionnée
    const validationRadio = document.querySelector(`[value="VALIDER_${propositionId}"]`);
    if (validationRadio) {
      validationRadio.checked = false;
    }
    
    // Masquer la zone de validation
    const validationZone = document.getElementById('validation_justification_' + propositionId);
    if (validationZone) {
      validationZone.style.display = 'none';
    }
    
    // Focus sur le textarea de justification
    setTimeout(() => {
      const textarea = document.getElementById(`justification_refus_${propositionId}`);
      if (textarea) textarea.focus();
    }, 100);
    
    showToast('Refus', 'Veuillez justifier le refus de cette proposition', 'warning');
  }
  
  updateValidationButtons();
}

// ================================================================
// GESTION DE LA PROPOSITION ALTERNATIVE
// ================================================================

function togglePropositionAlternative(activer) {
  console.log('🔄 Toggle proposition alternative:', activer);
  
  propositionAlternativeActive = activer;
  const formulaire = document.getElementById('formulairePropositionAlternative');
  const sectionBody = document.getElementById('propositionAlternativeBody');
  const btn = document.getElementById('btnTogglePropositionAlternative');
  
  if (formulaire && sectionBody) {
    if (activer) {
      // Afficher le formulaire
      formulaire.style.display = 'block';
      sectionBody.setAttribute('data-visible', 'true');
      sectionBody.classList.add('visible');
      sectionBody.style.display = 'block';
      
      // Mettre à jour le bouton
      if (btn) {
        btn.innerHTML = '<i class="fas fa-minus"></i> Fermer la proposition';
        btn.classList.add('active');
      }
      
      // Décocher toutes les validations de propositions précédentes
      document.querySelectorAll('[name="decision_proposition"]').forEach(radio => {
        radio.checked = false;
      });
      
      // Masquer toutes les zones de validation/refus
      document.querySelectorAll('[id^="validation_justification_"]').forEach(zone => {
        zone.style.display = 'none';
      });
      document.querySelectorAll('[id^="refus_justification_"]').forEach(zone => {
        zone.style.display = 'none';
      });
      
      // Focus sur le champ de recherche
      const matriculeInput = document.getElementById('candidat_alternatif_matricule');
      if (matriculeInput) {
        setTimeout(() => matriculeInput.focus(), 300);
      }
      
      showToast('Proposition', 'Section de proposition alternative ouverte', 'info');
    } else {
      // Masquer le formulaire
      formulaire.style.display = 'none';
      sectionBody.setAttribute('data-visible', 'false');
      sectionBody.classList.remove('visible');
      sectionBody.style.display = 'none';
      
      // Mettre à jour le bouton
      if (btn) {
        btn.innerHTML = '<i class="fas fa-plus"></i> Proposer un candidat alternatif';
        btn.classList.remove('active');
      }
      
      // Reset du formulaire alternatif
      resetFormulaireAlternatif();
    }
  }
  
  updateValidationButtons();
}

function resetFormulaireAlternatif() {
  console.log('🔄 Reset formulaire alternatif');
  
  // Reset des champs
  const champs = [
    'candidat_alternatif_matricule',
    'candidat_alternatif_id',
    'justification_proposition_alternative',
    'competences_specifiques_alternative',
    'experience_pertinente_alternative'
  ];
  
  champs.forEach(id => {
    const element = document.getElementById(id);
    if (element) element.value = '';
  });
  
  // Masquer les zones d'affichage
  const zones = [
    'candidat_alternatif_info',
    'candidat_alternatif_error', 
    'candidat_alternatif_loading'
  ];
  
  zones.forEach(id => {
    const element = document.getElementById(id);
    if (element) element.style.display = 'none';
  });
  
  // Masquer le bouton de score alternatif
  const btnScore = document.getElementById('btnScoreAlternatif');
  if (btnScore) {
    btnScore.style.display = 'none';
  }
  
  candidatAlternatifTrouve = null;
}

// ================================================================
// RECHERCHE DE CANDIDAT ALTERNATIF
// ================================================================

function rechercherCandidatAlternatif(matricule) {
  console.log('🔍 Recherche candidat alternatif par matricule:', matricule);
  
  // Nettoyer les timers précédents
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }
  
  if (!matricule || matricule.length < 2) {
    masquerInfosCandidatAlternatif();
    return;
  }
  
  // Debounce pour éviter trop de requêtes
  debounceTimer = setTimeout(() => {
    executerRechercheAlternative(matricule);
  }, 500);
}

async function executerRechercheAlternative(matricule) {
  console.log('🚀 Exécution recherche alternative pour matricule:', matricule);
  
  // Afficher le loading
  document.getElementById('candidat_alternatif_loading').style.display = 'flex';
  masquerInfosCandidatAlternatif();
  
  try {
    const response = await fetch('/interim/ajax/rechercher-candidat-alternatif/', {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/json',
        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
      },
      body: JSON.stringify({
        matricule: matricule,
        demande_id: parseInt('{{ demande.id }}') // S'assurer que c'est un entier
      })
    });
    
    console.log('📡 Réponse recherche alternative:', response.status, response.statusText);
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const data = await response.json();
    console.log('📊 Données candidat alternatif:', data);
    
    if (data.success && data.employe) {
      candidatAlternatifTrouve = data.employe;
      
      // Remplir le champ caché avec l'ID
      document.getElementById('candidat_alternatif_id').value = data.employe.id;
      
      // Extraire le score de manière sécurisée
      let score = 0;
      if (data.score) {
        if (typeof data.score === 'object' && data.score.score_final !== undefined) {
          score = data.score.score_final;
        } else if (typeof data.score === 'number') {
          score = data.score;
        }
      }
      
      // Afficher les informations
      afficherCandidatAlternatif(data.employe, score);
      
      // Afficher le bouton de score détaillé
      const btnScore = document.getElementById('btnScoreAlternatif');
      if (btnScore) {
        btnScore.style.display = 'inline-flex';
      }
      
      showToast('Succès', `Candidat ${data.employe.nom_complet} trouvé`, 'success');
    } else {
      throw new Error(data.message || data.error || 'Candidat non trouvé');
    }
    
  } catch (error) {
    console.error('❌ Erreur recherche:', error);
    
    let messageErreur = 'Erreur de communication';
    
    // Gestion des erreurs spécifiques
    if (error.message) {
      if (error.message.includes('not supported between instances')) {
        messageErreur = 'Erreur de calcul du score. Veuillez réessayer.';
      } else if (error.message.includes('non trouvé')) {
        messageErreur = 'Employé non trouvé avec ce matricule';
      } else if (error.message.includes('déjà proposé')) {
        messageErreur = 'Ce candidat est déjà proposé pour cette demande';
      } else {
        messageErreur = error.message;
      }
    }
    
    afficherErreurCandidatAlternatif(messageErreur);
    showToast('Erreur', messageErreur, 'error');
  } finally {
    document.getElementById('candidat_alternatif_loading').style.display = 'none';
  }
}

function afficherCandidatAlternatif(employe, score) {
  console.log('✅ Affichage candidat alternatif:', employe.nom_complet, 'Score:', score);
  
  // S'assurer que le score est un nombre
  const scoreNumeric = parseFloat(score) || 0;
  
  // Construire le HTML des détails
  const detailsHtml = `
    <div class="employee-info-row">
      <strong>${employe.nom_complet || 'Nom non disponible'}</strong>
      <span class="employee-matricule">${employe.matricule || 'N/A'}</span>
    </div>
    <div class="employee-info-organization">
      <span class="org-info"><i class="fas fa-briefcase"></i> ${employe.poste_actuel || 'Poste non renseigné'}</span>
      <span class="org-info"><i class="fas fa-building"></i> ${employe.departement || 'Département non renseigné'}</span>
      <span class="org-info"><i class="fas fa-map-marker-alt"></i> ${employe.site || 'Site non renseigné'}</span>
      ${employe.anciennete ? `<span class="org-info"><i class="fas fa-calendar-alt"></i> ${employe.anciennete}</span>` : ''}
    </div>
  `;
  
  document.getElementById('candidat_alternatif_details').innerHTML = detailsHtml;
  
  // Afficher le score avec classe appropriée
  const scoreElement = document.getElementById('candidat_alternatif_score');
  if (scoreElement) {
    scoreElement.textContent = scoreNumeric;
    scoreElement.className = 'score-value ' + getScoreClass(scoreNumeric);
  }
  
  // Afficher la zone d'information
  document.getElementById('candidat_alternatif_info').style.display = 'block';
  
  updateValidationButtons();
}

function afficherErreurCandidatAlternatif(message) {
  document.getElementById('candidat_alternatif_error_message').textContent = message;
  document.getElementById('candidat_alternatif_error').style.display = 'flex';
  
  candidatAlternatifTrouve = null;
  document.getElementById('candidat_alternatif_id').value = '';
  
  // Masquer le bouton de score
  const btnScore = document.getElementById('btnScoreAlternatif');
  if (btnScore) {
    btnScore.style.display = 'none';
  }
  
  updateValidationButtons();
}

function masquerInfosCandidatAlternatif() {
  const zones = [
    'candidat_alternatif_info',
    'candidat_alternatif_error'
  ];
  
  zones.forEach(id => {
    const element = document.getElementById(id);
    if (element) element.style.display = 'none';
  });
  
  // Masquer le bouton de score
  const btnScore = document.getElementById('btnScoreAlternatif');
  if (btnScore) {
    btnScore.style.display = 'none';
  }
}

function afficherDetailsScoreAlternatif() {
  if (candidatAlternatifTrouve && candidatAlternatifTrouve.matricule) {
    afficherDetailsScore(candidatAlternatifTrouve.matricule, 'alternatif');
  } else {
    showToast('Erreur', 'Aucun candidat alternatif sélectionné', 'error');
  }
}

// ================================================================
// VALIDATION ET SOUMISSION
// ================================================================

function validerDemande(action) {
  console.log('📤 Validation demande:', action);
  
  // Retirer la classe loading de tous les boutons
  document.querySelectorAll('.btn-action').forEach(btn => {
    btn.classList.remove('loading');
  });
  
  if (action === 'REFUSER') {
    const modalElement = document.getElementById('modalConfirmationRefus');
    if (modalElement) {
      const modal = getBootstrapModal(modalElement);
      if (modal.modal) {
        modal.modal('show'); // Bootstrap 4/jQuery
      } else {
        modal.show(); // Bootstrap 5 ou fallback
      }
    }
  } else if (action === 'APPROUVER') {
    // Vérifier que le formulaire est valide
    if (!validerFormulaire()) {
      return;
    }
    
    // Désactiver les boutons et soumettre
    setLoadingState(true);
    document.getElementById('validationForm').submit();
  }
}

function confirmerRefusGlobal() {
  const motif = document.getElementById('motif_refus_global').value;
  const details = document.getElementById('details_refus_global').value.trim();
  
  if (!details) {
    showToast('Erreur', 'Veuillez saisir les détails du refus.', 'error');
    return;
  }
  
  // Ajouter les champs cachés pour le refus
  const form = document.getElementById('validationForm');
  
  const actionInput = document.createElement('input');
  actionInput.type = 'hidden';
  actionInput.name = 'action_validation';
  actionInput.value = 'REFUSER';
  form.appendChild(actionInput);
  
  const motifInput = document.createElement('input');
  motifInput.type = 'hidden';
  motifInput.name = 'motif_refus_global';
  motifInput.value = motif;
  form.appendChild(motifInput);
  
  const detailsInput = document.createElement('input');
  detailsInput.type = 'hidden';
  detailsInput.name = 'details_refus_global';
  detailsInput.value = details;
  form.appendChild(detailsInput);
  
  // Fermer la modale
  const modalElement = document.getElementById('modalConfirmationRefus');
  if (modalElement) {
    const modal = getBootstrapModal(modalElement);
    if (modal.modal) {
      modal.modal('hide'); // Bootstrap 4/jQuery
    } else {
      modal.hide(); // Bootstrap 5 ou fallback
    }
  }
  
  // Soumettre le formulaire
  setLoadingState(true);
  form.submit();
}

function validerFormulaire() {
  const commentaireGeneral = document.getElementById('commentaire_validation_general').value.trim();
  
  if (!commentaireGeneral || commentaireGeneral.length < 10) {
    showToast('Erreur', 'Veuillez saisir un commentaire général de validation d\'au moins 10 caractères.', 'error');
    document.getElementById('commentaire_validation_general').focus();
    return false;
  }
  
  // Vérifier qu'au moins une action a été choisie
  const propositionValidee = document.querySelector('[name="decision_proposition"]:checked');
  const propositionAlternative = document.getElementById('proposer_alternative')?.checked;
  
  if (!propositionValidee && !propositionAlternative) {
    showToast('Erreur', 'Veuillez valider une proposition existante ou proposer un candidat alternatif.', 'error');
    return false;
  }
  
  // Si proposition alternative, vérifier les champs obligatoires
  if (propositionAlternative) {
    const matricule = document.getElementById('candidat_alternatif_matricule')?.value?.trim();
    const justification = document.getElementById('justification_proposition_alternative')?.value?.trim();
    
    if (!matricule || !candidatAlternatifTrouve) {
      showToast('Erreur', 'Veuillez rechercher et sélectionner un candidat alternatif valide.', 'error');
      document.getElementById('candidat_alternatif_matricule')?.focus();
      return false;
    }
    
    if (!justification || justification.length < 10) {
      showToast('Erreur', 'Veuillez justifier votre proposition alternative (minimum 10 caractères).', 'error');
      document.getElementById('justification_proposition_alternative')?.focus();
      return false;
    }
  }
  
  // Vérifier les justifications de refus si nécessaire
  const refusChecked = document.querySelectorAll('[id^="refuser_"]:checked');
  for (let refusRadio of refusChecked) {
    const propositionId = refusRadio.id.replace('refuser_', '');
    const justificationRefus = document.getElementById(`justification_refus_${propositionId}`);
    if (justificationRefus && !justificationRefus.value.trim()) {
      showToast('Erreur', `Veuillez justifier le refus de la proposition.`, 'error');
      justificationRefus.focus();
      return false;
    }
  }
  
  return true;
}

function updateValidationButtons() {
  const btnApprouver = document.getElementById('btnApprouver');
  const btnRefuser = document.getElementById('btnRefuser');
  
  if (btnApprouver && btnRefuser) {
    const commentaire = document.getElementById('commentaire_validation_general')?.value?.trim() || '';
    const canValidate = commentaire.length >= 10;
    
    btnApprouver.disabled = !canValidate;
    btnRefuser.disabled = !canValidate;
  }
}

function setLoadingState(loading) {
  const buttons = document.querySelectorAll('#btnApprouver, #btnRefuser');
  const spinners = document.querySelectorAll('.loading-spinner');
  const overlay = document.getElementById('loadingOverlay');
  
  buttons.forEach(btn => {
    btn.disabled = loading;
    if (loading) {
      btn.classList.add('loading');
    } else {
      btn.classList.remove('loading');
    }
  });
  
  spinners.forEach(spinner => {
    spinner.style.display = loading ? 'inline-block' : 'none';
  });
  
  if (overlay) {
    overlay.style.display = loading ? 'flex' : 'none';
  }
}

// ================================================================
// ACTIONS SUPPLÉMENTAIRES
// ================================================================

function voirDetailsCandidatProposition(candidatMatricule) {
  console.log('👤 Voir détails candidat proposition matricule:', candidatMatricule);
  window.open(`/interim/employe/${candidatMatricule}/`, '_blank');
}

function demanderInfos() {
  const informations = prompt('Quelles informations complémentaires souhaitez-vous demander ?');
  if (informations && informations.trim()) {
    fetch('/interim/ajax/demander-informations/', {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/json',
        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
      },
      body: JSON.stringify({
        demande_id: parseInt('{{ demande.id }}'), // S'assurer que c'est un entier
        informations: informations
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        showToast('Information', 'Demande d\'informations envoyée avec succès', 'success');
      } else {
        showToast('Erreur', data.message || 'Erreur lors de l\'envoi', 'error');
      }
    })
    .catch(error => {
      console.error('Erreur demande informations:', error);
      showToast('Erreur', 'Erreur de communication', 'error');
    });
  }
}

function escaladerValidation() {
  if (confirm('Êtes-vous sûr de vouloir escalader cette validation au niveau supérieur ?')) {
    const motif = prompt('Motif de l\'escalade:');
    if (motif && motif.trim()) {
      fetch('/interim/ajax/escalader-validation/', {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
          demande_id: parseInt('{{ demande.id }}'), // S'assurer que c'est un entier
          motif: motif
        })
      })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          showToast('Escalade', 'Escalade effectuée avec succès', 'success');
          setTimeout(() => location.reload(), 2000);
        } else {
          showToast('Erreur', data.message || 'Erreur lors de l\'escalade', 'error');
        }
      })
      .catch(error => {
        console.error('Erreur escalade:', error);
        showToast('Erreur', 'Erreur de communication', 'error');
      });
    }
  }
}

// ================================================================
// FONCTIONS D'INITIALISATION ET UTILITAIRES
// ================================================================

function initEventListeners() {
  console.log('🔧 Initialisation des event listeners...');
  
  // Event listener pour le bouton toggle proposition alternative
  const btnToggle = document.getElementById('btnTogglePropositionAlternative');
  if (btnToggle) {
    btnToggle.addEventListener('click', function(e) {
      e.preventDefault();
      const sectionBody = document.getElementById('propositionAlternativeBody');
      const isVisible = sectionBody?.getAttribute('data-visible') === 'true';
      togglePropositionAlternative(!isVisible);
    });
  }
  
  // Event listener pour la checkbox proposition alternative
  const checkboxAlternative = document.getElementById('proposer_alternative');
  if (checkboxAlternative) {
    checkboxAlternative.addEventListener('change', function() {
      const formulaire = document.getElementById('formulairePropositionAlternative');
      if (formulaire) {
        formulaire.style.display = this.checked ? 'block' : 'none';
      }
    });
  }
  
  // Event listener pour la recherche de candidat
  const matriculeInput = document.getElementById('candidat_alternatif_matricule');
  if (matriculeInput) {
    matriculeInput.addEventListener('input', function() {
      rechercherCandidatAlternatif(this.value.trim());
    });
  }
  
  // Event listener pour la justification
  const justificationInput = document.getElementById('justification_proposition_alternative');
  if (justificationInput) {
    justificationInput.addEventListener('input', function() {
      updateValidationButtons();
      autoResizeTextarea(this);
    });
  }
  
  // Event listener pour le commentaire général
  const commentaireGeneral = document.getElementById('commentaire_validation_general');
  if (commentaireGeneral) {
    commentaireGeneral.addEventListener('input', function() {
      updateValidationButtons();
      autoResizeTextarea(this);
    });
  }
  
  // Raccourcis clavier
  document.addEventListener('keydown', function(e) {
    // Escape pour fermer les sections ouvertes
    if (e.key === 'Escape') {
      const sectionBody = document.getElementById('propositionAlternativeBody');
      if (sectionBody && sectionBody.getAttribute('data-visible') === 'true') {
        togglePropositionAlternative(false);
      }
      
      // Note: La fermeture des modales avec Escape est gérée dans le script Bootstrap universel
    }
  });
  
  console.log('✅ Event listeners initialisés');
}

function configurerEtatInitial() {
  console.log('🔧 Configuration état initial...');
  
  // S'assurer que la section proposition alternative est fermée
  const sectionBody = document.getElementById('propositionAlternativeBody');
  if (sectionBody) {
    sectionBody.style.display = 'none';
    sectionBody.setAttribute('data-visible', 'false');
    sectionBody.classList.remove('visible');
  }
  
  // Masquer le formulaire alternatif
  const formulaire = document.getElementById('formulairePropositionAlternative');
  if (formulaire) {
    formulaire.style.display = 'none';
  }
  
  // Vérification initiale des boutons
  updateValidationButtons();
  
  console.log('✅ État initial configuré');
}

function initValidationFormulaire() {
  // Auto-resize pour toutes les textareas
  document.querySelectorAll('.form-textarea').forEach(textarea => {
    autoResizeTextarea(textarea);
  });
  
  // Focus sur le commentaire général
  {% if permissions.peut_valider %}
  const commentaireInput = document.getElementById('commentaire_validation_general');
  if (commentaireInput) {
    setTimeout(() => commentaireInput.focus(), 500);
  }
  {% endif %}
}

// ================================================================
// FONCTIONS UTILITAIRES
// ================================================================

function autoResizeTextarea(textarea) {
  if (textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
  }
}

function getScoreClass(score) {
  if (score >= 85) return 'score-excellent';
  if (score >= 70) return 'score-good';
  if (score >= 55) return 'score-average';
  return 'score-poor';
}

function formatModifierName(key) {
  const names = {
    'proposition_humaine': 'Proposition humaine',
    'experience_similaire': 'Expérience similaire',
    'recommandation': 'Recommandation',
    'hierarchique': 'Bonus hiérarchique',
    'kelio': 'Données Kelio',
    'indisponibilite': 'Indisponibilité',
    'distance': 'Distance excessive',
    'competences_manquantes': 'Compétences manquantes'
  };
  return names[key] || key.replace(/_/g, ' ');
}

function formatDate(dateStr) {
  if (!dateStr) return 'Non définie';
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString('fr-FR') + ' à ' + date.toLocaleTimeString('fr-FR', {
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return dateStr;
  }
}

function showToast(titre, message, type = 'info') {
  const toastContainer = document.querySelector('.toast-container');
  if (!toastContainer) {
    if (type === 'error') alert(`Erreur: ${message}`);
    return;
  }
  
  const toastId = 'toast_' + Date.now();
  const bgClass = {
    'success': 'text-bg-success',
    'error': 'text-bg-danger', 
    'warning': 'text-bg-warning',
    'info': 'text-bg-info'
  }[type] || 'text-bg-info';
  
  const icon = {
    'success': 'fa-check-circle',
    'error': 'fa-exclamation-circle',
    'warning': 'fa-exclamation-triangle', 
    'info': 'fa-info-circle'
  }[type] || 'fa-info-circle';
  
  const toastHtml = `
    <div class="toast ${bgClass}" id="${toastId}" role="alert" data-bs-autohide="true" data-bs-delay="${type === 'error' ? '8000' : '5000'}">
      <div class="toast-header">
        <i class="fas ${icon} me-2"></i>
        <strong class="me-auto">${titre}</strong>
        <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
      </div>
      <div class="toast-body">${message}</div>
    </div>
  `;
  
  toastContainer.insertAdjacentHTML('beforeend', toastHtml);
  
  const toastElement = document.getElementById(toastId);
  if (toastElement) {
    const toast = new bootstrap.Toast(toastElement);
    toast.show();
    toastElement.addEventListener('hidden.bs.toast', function() {
      toastElement.remove();
    });
  }
}

// ================================================================
// EXPOSITION DES FONCTIONS GLOBALES
// ================================================================

// Nouvelles fonctions pour les scores
window.afficherDetailsScore = afficherDetailsScore;
window.afficherDetailsScoreAlternatif = afficherDetailsScoreAlternatif;

// Fonctions principales
window.togglePropositionOptions = togglePropositionOptions;
window.toggleRefusJustification = toggleRefusJustification;
window.togglePropositionAlternative = togglePropositionAlternative;
window.rechercherCandidatAlternatif = rechercherCandidatAlternatif;

// Fonctions de validation
window.validerDemande = validerDemande;
window.confirmerRefusGlobal = confirmerRefusGlobal;

// Fonctions modales
window.ouvrirModaleCandidatsAutomatiques = ouvrirModaleCandidatsAutomatiques;
window.voirDetailsCandidatProposition = voirDetailsCandidatProposition;
window.demanderInfos = demanderInfos;
window.escaladerValidation = escaladerValidation;

// ================================================================
// MESSAGES DE BIENVENUE
// ================================================================

setTimeout(() => {
  {% if permissions.peut_valider %}
  showToast(
    'Interface de validation améliorée', 
    'Analysez les propositions avec leurs scores détaillés, ou proposez un candidat alternatif si besoin.', 
    'info'
  );
  {% else %}
  showToast(
    'Consultation', 
    'Vous consultez cette demande en lecture seule avec accès aux scores détaillés.', 
    'info'
  );
  {% endif %}
}, 1000);

console.log('🎉 Interface de validation avec modales corrigées chargée avec succès');
console.log('🔧 Version: Workflow complet + Scores détaillés + UX moderne + Modales Bootstrap 5');
console.log('📅 Chargement terminé:', new Date().toLocaleTimeString());


