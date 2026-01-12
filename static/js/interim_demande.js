
document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation du formulaire de demande d\'intérim avec gestion complète des candidats');

  // ================================================================
  // VARIABLES GLOBALES
  // ================================================================
  
  const form = document.getElementById('interimForm');
  const submitBtn = document.getElementById('submitBtn');
  const loadingSpinner = document.getElementById('loadingSpinner');
  
  // Cache pour les recherches d'employés
  const employeeCache = new Map();
  const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes

  // ================================================================
  // VARIABLES GLOBALES POUR GESTION DES CANDIDATS
  // ================================================================
  
  let candidatsAutomatiques = [];
  let candidatsSelectionnes = new Set();
  let candidatSpecifique = null;
  let candidatsFiltres = [];
  let paginationActuelle = {
    page: 1,
    taille: 10,
    total: 0
  };

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

  function showNotification(message, type = 'info') {
    console.log(`📢 Notification ${type}: ${message}`);
    
    const notification = document.createElement('div');
    notification.className = `alert alert-${type}`;
    notification.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 350px; animation: slideIn 0.3s ease;';
    notification.innerHTML = `
      <i class="fas fa-info-circle"></i>
      <span>${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
      if (notification.parentNode) {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
          if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
          }
        }, 300);
      }
    }, 4000);
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
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
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

      if (data && data.success === true) {
        console.log(`✅ Succès détecté`);
        
        if (data.employe) {
          console.log(`👤 Employé trouvé:`, data.employe);
          
          employeeCache.set(cacheKey, {
            data: data,
            timestamp: Date.now()
          });

          afficherInfosEmploye(data, type);
          showNotification(`Employé ${matricule} trouvé avec succès`, 'success');
          
          if (type === 'candidat_specifique') {
            setTimeout(() => calculerScoreCandidatSpecifique(data.employe.id), 100);
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

  function afficherInfosEmploye(data, type) {
    console.log(`📝 DEBUT afficherInfosEmploye pour type: ${type}`, data);
    
    const employe = data.employe;
    if (!employe) {
      console.error(`❌ Pas de données employé`);
      return;
    }

    setElementDisplay(`${type}_error`, false);
    setElementDisplay(`${type}_loading`, false);

    setElementContent(`${type}_nom_complet`, employe.nom_complet, 'Nom non disponible');
    setElementContent(`${type}_matricule_display`, employe.matricule);
    
    if (employe.sexe) {
      setElementContent(`${type}_sexe`, employe.sexe === 'M' ? '👨 Homme' : '👩 Femme');
    }
    
    if (employe.anciennete) {
      setElementContent(`${type}_anciennete`, `⏰ ${employe.anciennete}`);
    }

    if (employe.departement) {
      setElementContent(`${type}_departement`, `🏢 ${employe.departement}`);
    }
    
    if (employe.site) {
      setElementContent(`${type}_site`, `📍 ${employe.site}`);
    }
    
    if (employe.poste) {
      setElementContent(`${type}_poste`, `💼 ${employe.poste}`);
    }

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

    const hiddenInput = getElement(`${type}_id`);
    if (hiddenInput && employe.id) {
      hiddenInput.value = employe.id;
      console.log(`✅ ID caché défini: ${employe.id}`);
    }

    setElementDisplay(`${type}_info`, true);
    
    if (type === 'candidat_specifique') {
      candidatSpecifique = {
        id: employe.id,
        matricule: employe.matricule,
        nom_complet: employe.nom_complet,
        poste_actuel: employe.poste,
        departement: employe.departement,
        site: employe.site,
        score: null
      };
      mettreAJourAffichage();
    }
    
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

    const hiddenInput = getElement(`${type}_id`);
    if (hiddenInput) {
      hiddenInput.value = '';
    }

    if (type === 'candidat_specifique') {
      candidatSpecifique = null;
      mettreAJourAffichage();
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

    if (type === 'candidat_specifique') {
      candidatSpecifique = null;
      mettreAJourAffichage();
    }
  }

  // ================================================================
  // FONCTIONS PROPOSITION AUTOMATIQUE
  // ================================================================

  async function propositionAutomatique() {
    console.log('🤖 DEBUT propositionAutomatique');
    
    const formData = {
      personne_remplacee_id: getElement('personne_remplacee_id')?.value,
      poste_id: getElement('poste_id')?.value,
      date_debut: getElement('date_debut')?.value,
      date_fin: getElement('date_fin')?.value,
      description_poste: getElement('description_poste')?.value,
      competences_indispensables: getElement('competences_indispensables')?.value,
      urgence: getElement('urgence')?.value
    };

    if (!formData.personne_remplacee_id || !formData.poste_id || !formData.date_debut || !formData.date_fin) {
      alert('Veuillez remplir les informations de base avant de demander une proposition automatique');
      return;
    }

    const btnPropositionAuto = getElement('btnPropositionAuto');
    const loadingAutoProposal = getElement('loadingAutoProposal');
    
    if (btnPropositionAuto) btnPropositionAuto.disabled = true;
    if (loadingAutoProposal) loadingAutoProposal.classList.add('show');

    try {
      const response = await fetch('/interim/ajax/proposition-automatique/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(formData)
      });

      if (!response.ok) {
        throw new Error(`Erreur HTTP ${response.status}`);
      }

      const data = await response.json();
      
      if (data.success) {
        candidatsAutomatiques = data.candidats || [];
        candidatsFiltres = [...candidatsAutomatiques];
        candidatsSelectionnes.clear();
        
        afficherResultatsPropositionAuto(data);
        showNotification(`${candidatsAutomatiques.length} candidats trouvés et analysés`, 'success');
        
      } else {
        throw new Error(data.error || 'Erreur lors de la proposition automatique');
      }

    } catch (error) {
      console.error('❌ Erreur proposition automatique:', error);
      alert('Erreur lors de la proposition automatique: ' + error.message);
      
    } finally {
      if (btnPropositionAuto) btnPropositionAuto.disabled = false;
      if (loadingAutoProposal) loadingAutoProposal.classList.remove('show');
    }
  }

  function afficherResultatsPropositionAuto(data) {
    console.log('📊 Affichage résultats proposition automatique', data);
    
    setElementDisplay('autoProposalResults', true);
    
    const departementInfo = data.departement_filtre ? ` (Département: ${data.departement_filtre})` : '';
    setElementContent('candidatsCount', `${candidatsAutomatiques.length} candidats trouvés${departementInfo}`);
    
    if (candidatsAutomatiques.length > 0) {
      const scores = candidatsAutomatiques.map(c => c.score);
      const minScore = Math.min(...scores);
      const maxScore = Math.max(...scores);
      setElementContent('scoreRange', `Score: ${minScore}-${maxScore}`);
    }
    
    afficherTableauCandidats();
    mettreAJourAffichage();
  }

  function afficherTableauCandidats() {
    const tableBody = getElement('candidatesTableBody');
    if (!tableBody) return;
    
    tableBody.innerHTML = '';
    
    const debut = (paginationActuelle.page - 1) * paginationActuelle.taille;
    const fin = debut + paginationActuelle.taille;
    const candidatsPagines = candidatsFiltres.slice(debut, fin);
    
    candidatsPagines.forEach(candidat => {
      const row = creerLigneCandidatTableau(candidat);
      tableBody.appendChild(row);
    });
    
    mettreAJourPagination();
  }

  function creerLigneCandidatTableau(candidat) {
    const row = document.createElement('tr');
    row.dataset.candidatId = candidat.id;
    
    const estSelectionne = candidatsSelectionnes.has(candidat.id);
    if (estSelectionne) {
      row.classList.add('selected');
    }
    
    // Score coloré
    let scoreClass = 'poor';
    if (candidat.score >= 80) scoreClass = 'excellent';
    else if (candidat.score >= 60) scoreClass = 'good';
    else if (candidat.score >= 40) scoreClass = 'average';
    
    // Disponibilité
    const disponibiliteClass = candidat.disponibilite?.disponible ? 'available' : 'unavailable';
    const disponibiliteTexte = candidat.disponibilite?.raison || 'À vérifier';
    
    // Compétences
    const competencesHtml = candidat.competences_cles?.slice(0, 3).map(comp => 
      `<span class="skill-tag">${comp}</span>`
    ).join('') || '<span class="skill-tag">Aucune</span>';
    
    row.innerHTML = `
      <td>
        <input type="checkbox" name="candidat_auto_selection" value="${candidat.id}" 
               ${estSelectionne ? 'checked' : ''}
               onchange="toggleCandidatSelection(${candidat.id})">
      </td>
      <td>
        <div class="candidate-score ${scoreClass}">${candidat.score}</div>
      </td>
      <td>
        <div class="candidate-info">
          <div class="candidate-name">${candidat.nom_complet}</div>
          <div class="candidate-matricule">${candidat.matricule}</div>
        </div>
      </td>
      <td>
        <div class="candidate-details">
          <div class="candidate-poste">${candidat.poste_actuel || 'Non renseigné'}</div>
          <div class="candidate-anciennete">${candidat.anciennete || 'Non renseignée'}</div>
        </div>
      </td>
      <td>${candidat.departement || 'Non renseigné'}</td>
      <td>
        <div class="candidate-skills">${competencesHtml}</div>
      </td>
      <td>
        <div class="availability-status ${disponibiliteClass}">
          <i class="fas fa-${candidat.disponibilite?.disponible ? 'check' : 'times'}"></i>
          ${disponibiliteTexte}
        </div>
      </td>
      <td>
        <button type="button" class="btn btn-outline-small" onclick="voirDetailCandidat(${candidat.id})">
          <i class="fas fa-eye"></i>
        </button>
      </td>
    `;
    
    return row;
  }

  function mettreAJourPagination() {
    const total = candidatsFiltres.length;
    const totalPages = Math.ceil(total / paginationActuelle.taille);
    paginationActuelle.total = total;
    
    const debut = (paginationActuelle.page - 1) * paginationActuelle.taille + 1;
    const fin = Math.min(debut + paginationActuelle.taille - 1, total);
    setElementContent('paginationInfo', `Affichage de ${debut}-${fin} sur ${total} candidats`);
    
    const btnPrev = getElement('btnPrevPage');
    const btnNext = getElement('btnNextPage');
    
    if (btnPrev) {
      btnPrev.disabled = paginationActuelle.page <= 1;
    }
    if (btnNext) {
      btnNext.disabled = paginationActuelle.page >= totalPages;
    }
    
    const pageNumbers = getElement('pageNumbers');
    if (pageNumbers) {
      pageNumbers.innerHTML = '';
      
      const maxPages = 5;
      let startPage = Math.max(1, paginationActuelle.page - Math.floor(maxPages / 2));
      let endPage = Math.min(totalPages, startPage + maxPages - 1);
      
      if (endPage - startPage + 1 < maxPages) {
        startPage = Math.max(1, endPage - maxPages + 1);
      }
      
      for (let i = startPage; i <= endPage; i++) {
        const pageBtn = document.createElement('button');
        pageBtn.className = `page-number ${i === paginationActuelle.page ? 'active' : ''}`;
        pageBtn.textContent = i;
        pageBtn.onclick = () => changerPage(i);
        pageNumbers.appendChild(pageBtn);
      }
    }
  }

  function changerPage(page) {
    paginationActuelle.page = page;
    afficherTableauCandidats();
  }

  function toggleCandidatSelection(candidatId) {
    if (candidatsSelectionnes.has(candidatId)) {
      candidatsSelectionnes.delete(candidatId);
    } else {
      candidatsSelectionnes.add(candidatId);
    }
    
    // Mettre à jour l'affichage de la ligne
    const row = document.querySelector(`tr[data-candidat-id="${candidatId}"]`);
    if (row) {
      if (candidatsSelectionnes.has(candidatId)) {
        row.classList.add('selected');
      } else {
        row.classList.remove('selected');
      }
    }
    
    mettreAJourAffichage();
  }

  function selectionnerTousCandidats() {
    candidatsFiltres.forEach(candidat => {
      candidatsSelectionnes.add(candidat.id);
    });
    afficherTableauCandidats();
    mettreAJourAffichage();
  }

  function deselectionnerTousCandidats() {
    candidatsSelectionnes.clear();
    afficherTableauCandidats();
    mettreAJourAffichage();
  }

  // ================================================================
  // FONCTIONS CANDIDAT SPÉCIFIQUE
  // ================================================================

  async function calculerScoreCandidatSpecifique(candidatId) {
    const formData = {
      candidat_id: candidatId,
      personne_remplacee_id: getElement('personne_remplacee_id')?.value,
      poste_id: getElement('poste_id')?.value,
      date_debut: getElement('date_debut')?.value,
      date_fin: getElement('date_fin')?.value,
      description_poste: getElement('description_poste')?.value,
      competences_indispensables: getElement('competences_indispensables')?.value
    };

    if (!formData.personne_remplacee_id || !formData.poste_id || !formData.date_debut || !formData.date_fin) {
      return;
    }

    try {
      const response = await fetch('/interim/ajax/calculer-score-candidat/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(formData)
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          afficherScoreCandidatSpecifique(data.score);
          if (candidatSpecifique) {
            candidatSpecifique.score = data.score;
          }
        }
      }
    } catch (error) {
      console.error('Erreur calcul score candidat spécifique:', error);
    }
  }

  function afficherScoreCandidatSpecifique(score) {
    const scoreElement = getElement('candidat_specifique_score_value');
    if (!scoreElement) return;
    
    let scoreClass = 'poor';
    if (score >= 80) scoreClass = 'excellent';
    else if (score >= 60) scoreClass = 'good';
    else if (score >= 40) scoreClass = 'average';
    
    scoreElement.textContent = score;
    scoreElement.className = `score-value candidate-score ${scoreClass}`;
    
    setElementDisplay('candidat_specifique_score', true);
  }

  // ================================================================
  // FONCTIONS DE FILTRAGE
  // ================================================================

  function appliquerFiltres() {
    const filterScore = getElement('filterScore')?.value;
    
    candidatsFiltres = candidatsAutomatiques.filter(candidat => {
      if (filterScore) {
        const [minScore, maxScore] = filterScore.split('-').map(Number);
        if (candidat.score < minScore || candidat.score > maxScore) {
          return false;
        }
      }
      
      return true;
    });
    
    paginationActuelle.page = 1;
    afficherTableauCandidats();
    
    setElementContent('candidatsCount', `${candidatsFiltres.length} candidats affichés`);
  }

  // ================================================================
  // FONCTIONS DE MISE À JOUR DE L'AFFICHAGE
  // ================================================================

  function mettreAJourAffichage() {
    // Afficher/masquer la justification pour candidats automatiques
    const autoJustification = getElement('autoSelectionJustification');
    if (autoJustification) {
      if (candidatsSelectionnes.size > 0) {
        autoJustification.style.display = 'block';
        const textarea = getElement('justificationAutoCandidat');
        if (textarea) {
          textarea.required = true;
        }
      } else {
        autoJustification.style.display = 'none';
        const textarea = getElement('justificationAutoCandidat');
        if (textarea) {
          textarea.required = false;
        }
      }
    }

    // Mettre à jour le résumé des sélections
    mettreAJourResume();

    // Mettre à jour les boutons d'action
    mettreAJourBoutonsAction();

    // Mettre à jour les champs cachés
    mettreAJourChampsCache();
  }

  function mettreAJourResume() {
    const selectionSummary = getElement('selectionSummary');
    const summaryContent = getElement('summaryContent');
    
    if (!selectionSummary || !summaryContent) return;

    const aSelections = candidatsSelectionnes.size > 0 || candidatSpecifique;
    
    if (!aSelections) {
      selectionSummary.style.display = 'none';
      return;
    }

    selectionSummary.style.display = 'block';
    summaryContent.innerHTML = '';

    // Candidats automatiques sélectionnés
    if (candidatsSelectionnes.size > 0) {
      const candidatsSelectionnesArray = candidatsAutomatiques.filter(c => candidatsSelectionnes.has(c.id));
      
      const autoSection = document.createElement('div');
      autoSection.className = 'summary-item';
      autoSection.innerHTML = `
        <div class="summary-item-header">
          <span class="summary-item-title">
            <i class="fas fa-robot"></i> Candidats automatiques sélectionnés
          </span>
          <span class="summary-item-count">${candidatsSelectionnes.size}</span>
        </div>
        <div class="summary-candidates-list">
          ${candidatsSelectionnesArray.map(c => 
            `<span class="summary-candidate-badge">${c.nom_complet} (${c.matricule}) - Score: ${c.score}</span>`
          ).join('')}
        </div>
      `;
      summaryContent.appendChild(autoSection);
    }

    // Candidat spécifique
    if (candidatSpecifique) {
      const specificSection = document.createElement('div');
      specificSection.className = 'summary-item';
      specificSection.innerHTML = `
        <div class="summary-item-header">
          <span class="summary-item-title">
            <i class="fas fa-user-plus"></i> Candidat spécifique
          </span>
          <span class="summary-item-count">1</span>
        </div>
        <div class="summary-candidates-list">
          <span class="summary-candidate-badge">
            ${candidatSpecifique.nom_complet} (${candidatSpecifique.matricule})
            ${candidatSpecifique.score ? ` - Score: ${candidatSpecifique.score}` : ''}
          </span>
        </div>
      `;
      summaryContent.appendChild(specificSection);
    }
  }

  function mettreAJourBoutonsAction() {
    const btnCreateClassic = getElement('btnCreateClassic');
    const submitBtn = getElement('submitBtn');

    const aSelections = candidatsSelectionnes.size > 0 || candidatSpecifique;
    const aAutomatiques = candidatsAutomatiques.length > 0;

    if (btnCreateClassic) {
      // Afficher le bouton "créer sans candidat" seulement si on a fait une recherche automatique
      btnCreateClassic.style.display = aAutomatiques ? 'inline-flex' : 'none';
    }

    if (submitBtn) {
      if (aSelections) {
        submitBtn.innerHTML = `
          <i class="fas fa-save"></i>
          Créer la demande avec sélections
          <div class="loading-spinner" id="loadingSpinner">
            <i class="fas fa-spinner fa-spin"></i>
          </div>
        `;
      } else {
        submitBtn.innerHTML = `
          <i class="fas fa-paper-plane"></i>
          Créer la demande
          <div class="loading-spinner" id="loadingSpinner">
            <i class="fas fa-spinner fa-spin"></i>
          </div>
        `;
      }
    }
  }

  function mettreAJourChampsCache() {
    // Candidats automatiques (tous)
    const candidatsAutomatiquesInput = getElement('candidatsAutomatiquesData');
    if (candidatsAutomatiquesInput) {
      candidatsAutomatiquesInput.value = JSON.stringify(candidatsAutomatiques);
    }

    // Candidats sélectionnés
    const candidatsSelectionnesInput = getElement('candidatsSelectionnesData');
    if (candidatsSelectionnesInput) {
      const candidatsSelectionnesArray = candidatsAutomatiques.filter(c => candidatsSelectionnes.has(c.id));
      candidatsSelectionnesInput.value = JSON.stringify(candidatsSelectionnesArray);
    }

    // Candidat spécifique
    const candidatSpecifiqueInput = getElement('candidatSpecifiqueData');
    if (candidatSpecifiqueInput) {
      candidatSpecifiqueInput.value = candidatSpecifique ? JSON.stringify(candidatSpecifique) : '';
    }

    // Mode de création
    const modeCreationInput = getElement('modeCreation');
    if (modeCreationInput) {
      if (candidatsSelectionnes.size > 0 && candidatSpecifique) {
        modeCreationInput.value = 'mixte';
      } else if (candidatsSelectionnes.size > 0) {
        modeCreationInput.value = 'automatique';
      } else if (candidatSpecifique) {
        modeCreationInput.value = 'specifique';
      } else {
        modeCreationInput.value = 'classique';
      }
    }
  }

  // ================================================================
  // FONCTIONS D'ENREGISTREMENT
  // ================================================================

  async function enregistrerDemande(formData) {
    try {
      console.log('📤 Envoi de la demande:', formData);

      const response = await fetch(form.action || window.location.href, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json'
        }
      });

      if (!response.ok) {
        throw new Error(`Erreur HTTP ${response.status}`);
      }

      const data = await response.json();
      
      if (data.success) {
        showNotification(`Demande ${data.numero_demande} créée avec succès !`, 'success');
        
        if (data.redirect_url) {
          setTimeout(() => {
            window.location.href = data.redirect_url;
          }, 1000);
        }
      } else {
        throw new Error(data.error || 'Une erreur est survenue');
      }

    } catch (error) {
      console.error('Erreur enregistrement:', error);
      alert('Erreur: ' + error.message);
    }
  }

  // ================================================================
  // EVENT LISTENERS
  // ================================================================

  // Bouton proposition automatique
  const btnPropositionAuto = getElement('btnPropositionAuto');
  if (btnPropositionAuto) {
    btnPropositionAuto.addEventListener('click', propositionAutomatique);
  }

  // Bouton toggle candidat spécifique
  const btnToggleSpecific = getElement('btnToggleSpecific');
  if (btnToggleSpecific) {
    btnToggleSpecific.addEventListener('click', function() {
      const section = getElement('specificCandidateSection');
      if (section) {
        const isVisible = section.style.display !== 'none';
        section.style.display = isVisible ? 'none' : 'block';
        
        if (!isVisible) {
          const matriculeInput = getElement('candidatSpecifiqueMatricule');
          if (matriculeInput) {
            matriculeInput.focus();
          }
        } else {
          // Effacer les données si on masque la section
          const matriculeInput = getElement('candidatSpecifiqueMatricule');
          if (matriculeInput) {
            matriculeInput.value = '';
          }
          masquerInfosEmploye('candidat_specifique');
        }
      }
    });
  }

  // Bouton retirer candidat spécifique
  const btnRemoveSpecific = getElement('btnRemoveSpecific');
  if (btnRemoveSpecific) {
    btnRemoveSpecific.addEventListener('click', function() {
      const section = getElement('specificCandidateSection');
      if (section) {
        section.style.display = 'none';
      }
      
      const matriculeInput = getElement('candidatSpecifiqueMatricule');
      if (matriculeInput) {
        matriculeInput.value = '';
      }
      
      masquerInfosEmploye('candidat_specifique');
    });
  }

  // Boutons de sélection en masse
  const btnSelectAllAuto = getElement('btnSelectAllAuto');
  const btnDeselectAllAuto = getElement('btnDeselectAllAuto');
  
  if (btnSelectAllAuto) {
    btnSelectAllAuto.addEventListener('click', selectionnerTousCandidats);
  }
  
  if (btnDeselectAllAuto) {
    btnDeselectAllAuto.addEventListener('click', deselectionnerTousCandidats);
  }

  // Checkbox "Sélectionner tous"
  const selectAllCheckbox = getElement('selectAllCandidates');
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', function() {
      if (this.checked) {
        selectionnerTousCandidats();
      } else {
        deselectionnerTousCandidats();
      }
    });
  }

  // Filtres
  const filterScore = getElement('filterScore');
  if (filterScore) {
    filterScore.addEventListener('change', appliquerFiltres);
  }

  // Pagination
  const btnPrevPage = getElement('btnPrevPage');
  const btnNextPage = getElement('btnNextPage');
  
  if (btnPrevPage) {
    btnPrevPage.addEventListener('click', () => {
      if (paginationActuelle.page > 1) {
        changerPage(paginationActuelle.page - 1);
      }
    });
  }
  
  if (btnNextPage) {
    btnNextPage.addEventListener('click', () => {
      const totalPages = Math.ceil(candidatsFiltres.length / paginationActuelle.taille);
      if (paginationActuelle.page < totalPages) {
        changerPage(paginationActuelle.page + 1);
      }
    });
  }

  // Recherche d'employés avec debounce
  const personneMatriculeInput = getElement('personne_remplacee_matricule');
  const candidatSpecifiqueMatriculeInput = getElement('candidatSpecifiqueMatricule');

  if (personneMatriculeInput) {
    const debouncedSearchPersonne = debounce((matricule) => {
      rechercherEmploye(matricule, 'personne_remplacee');
    }, 500);

    personneMatriculeInput.addEventListener('input', function() {
      const matricule = this.value.trim();
      debouncedSearchPersonne(matricule);
    });
  }

  if (candidatSpecifiqueMatriculeInput) {
    const debouncedSearchCandidatSpecifique = debounce((matricule) => {
      rechercherEmploye(matricule, 'candidat_specifique');
    }, 500);

    candidatSpecifiqueMatriculeInput.addEventListener('input', function() {
      const matricule = this.value.trim();
      debouncedSearchCandidatSpecifique(matricule);
    });
  }

  // Cascade département -> postes
  const departementSelect = getElement('departement_id');
  const posteSelect = getElement('poste_id');

  if (departementSelect && posteSelect) {
    departementSelect.addEventListener('change', function() {
      const departementId = this.value;
      
      posteSelect.innerHTML = '<option value="">Chargement...</option>';
      
      if (departementId) {
        fetch(`/interim/ajax/postes-by-departement/?departement_id=${departementId}`)
          .then(response => response.json())
          .then(data => {
            posteSelect.innerHTML = '<option value="">Sélectionnez un poste</option>';
            if (data.postes) {
              data.postes.forEach(poste => {
                const siteInfo = poste.site__nom ? ` - ${poste.site__nom}` : '';
                posteSelect.innerHTML += `<option value="${poste.id}">${poste.titre}${siteInfo}</option>`;
              });
            }
          })
          .catch(error => {
            console.error('Erreur chargement postes:', error);
            posteSelect.innerHTML = '<option value="">Erreur de chargement</option>';
          });
      } else {
        posteSelect.innerHTML = '<option value="">Sélectionnez d\'abord un département</option>';
      }
    });
  }

  // Validation des dates
  const dateDebutInput = getElement('date_debut');
  const dateFinInput = getElement('date_fin');

  if (dateDebutInput && dateFinInput) {
    dateDebutInput.addEventListener('change', function() {
      const dateDebut = new Date(this.value);
      const dateFin = new Date(dateFinInput.value);
      
      if (dateFin && dateDebut > dateFin) {
        alert('La date de début doit être antérieure à la date de fin');
        this.value = '';
      } else {
        dateFinInput.min = this.value;
      }
    });

    dateFinInput.addEventListener('change', function() {
      const dateDebut = new Date(dateDebutInput.value);
      const dateFin = new Date(this.value);
      
      if (dateDebut && dateFin < dateDebut) {
        alert('La date de fin doit être postérieure à la date de début');
        this.value = '';
      }
    });
  }

  // Bouton créer sans candidat
  const btnCreateClassic = getElement('btnCreateClassic');
  if (btnCreateClassic) {
    btnCreateClassic.addEventListener('click', function() {
      // Vider les sélections
      candidatsSelectionnes.clear();
      candidatSpecifique = null;
      
      // Soumettre le formulaire en mode classique
      const modeCreationInput = getElement('modeCreation');
      if (modeCreationInput) {
        modeCreationInput.value = 'classique';
      }
      
      form.dispatchEvent(new Event('submit'));
    });
  }

  // ================================================================
  // SOUMISSION DU FORMULAIRE
  // ================================================================

  if (form) {
    form.addEventListener('submit', function(e) {
      e.preventDefault();
      console.log('📝 Soumission du formulaire');

      // Validation des champs requis
      const requiredFields = form.querySelectorAll('[required]');
      let allValid = true;

      requiredFields.forEach(field => {
        if (!field.value.trim()) {
          field.style.borderColor = '#dc3545';
          allValid = false;
        } else {
          field.style.borderColor = '';
        }
      });

      if (!allValid) {
        alert('Veuillez remplir tous les champs obligatoires');
        return;
      }

      // Validation spécifique pour candidat spécifique
      if (candidatSpecifique) {
        const justificationSpec = getElement('justificationSpecifique')?.value?.trim();
        if (!justificationSpec) {
          alert('La justification est obligatoire pour le candidat spécifique');
          getElement('justificationSpecifique')?.focus();
          return;
        }
      }

      // Validation spécifique pour candidats automatiques sélectionnés
      if (candidatsSelectionnes.size > 0) {
        const justificationAuto = getElement('justificationAutoCandidat')?.value?.trim();
        if (!justificationAuto) {
          alert('La justification est obligatoire pour les candidats automatiques sélectionnés');
          getElement('justificationAutoCandidat')?.focus();
          return;
        }
      }

      // Validation des dates
      if (dateDebutInput && dateFinInput) {
        const dateDebut = new Date(dateDebutInput.value);
        const dateFin = new Date(dateFinInput.value);
        
        if (dateDebut >= dateFin) {
          alert('La date de début doit être antérieure à la date de fin');
          return;
        }
      }

      // Mettre à jour les champs cachés avant soumission
      mettreAJourChampsCache();

      // Désactiver le bouton et afficher le spinner
      if (submitBtn) {
        submitBtn.disabled = true;
      }
      const loadingSpinner = getElement('loadingSpinner');
      if (loadingSpinner) {
        loadingSpinner.classList.add('show');
      }

      // Soumission
      const formData = new FormData(form);
      
      enregistrerDemande(formData)
        .finally(() => {
          if (submitBtn) {
            submitBtn.disabled = false;
          }
          if (loadingSpinner) {
            loadingSpinner.classList.remove('show');
          }
        });
    });
  }

  // ================================================================
  // FONCTIONS GLOBALES POUR LES ÉVÉNEMENTS ONCLICK
  // ================================================================

  window.toggleCandidatSelection = toggleCandidatSelection;
  
  window.voirDetailCandidat = function(candidatId) {
    const candidat = candidatsAutomatiques.find(c => c.id === candidatId);
    if (candidat) {
      alert(`Détails du candidat:\n\nNom: ${candidat.nom_complet}\nMatricule: ${candidat.matricule}\nScore: ${candidat.score}\nPoste: ${candidat.poste_actuel || 'Non renseigné'}\nDépartement: ${candidat.departement || 'Non renseigné'}`);
    }
  };

  // ================================================================
  // INITIALISATION
  // ================================================================

  // Auto-resize des textareas
  const textareas = document.querySelectorAll('.form-textarea');
  textareas.forEach(textarea => {
    textarea.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = this.scrollHeight + 'px';
    });
  });

  // Focus sur le premier champ requis vide
  const firstRequiredEmpty = form?.querySelector('[required]:not([value])');
  if (firstRequiredEmpty) {
    firstRequiredEmpty.focus();
  }

  // Initialiser l'affichage
  mettreAJourAffichage();

  console.log('✅ Formulaire de demande d\'intérim avec gestion complète des candidats initialisé avec succès');
});

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

