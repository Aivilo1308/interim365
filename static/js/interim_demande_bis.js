
document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation du formulaire de demande d\'intérim avec proposition automatique');

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
  // VARIABLES GLOBALES POUR PROPOSITION AUTOMATIQUE
  // ================================================================
  
  let candidatsAutomatiques = [];
  let candidatsFiltres = [];
  let candidatSelectionne = null;
  let candidatSpecifique = null;
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
    
    // Créer une notification temporaire
    const notification = document.createElement('div');
    notification.className = `alert alert-${type}`;
    notification.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 350px; animation: slideIn 0.3s ease;';
    notification.innerHTML = `
      <i class="fas fa-info-circle"></i>
      <span>${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    // Retirer après 4 secondes
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

  // ================================================================
  // FONCTIONS DE GESTION DES ÉLÉMENTS
  // ================================================================

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
          showNotification(`Employé ${matricule} trouvé avec succès`, 'success');
          
          // Si c'est un candidat spécifique, calculer le score
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

    // Vérifier la disponibilité pour les candidats
    if (type === 'candidat_propose') {
      setTimeout(verifierDisponibiliteCandidat, 100);
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
  // VÉRIFICATION DE DISPONIBILITÉ
  // ================================================================

  function verifierDisponibiliteCandidat() {
    const candidatId = getElement('candidat_propose_id')?.value;
    const dateDebut = getElement('date_debut')?.value;
    const dateFin = getElement('date_fin')?.value;
    const disponibiliteElement = getElement('candidat_propose_disponibilite');

    if (!candidatId || !dateDebut || !dateFin || !disponibiliteElement) {
      if (disponibiliteElement) {
        disponibiliteElement.style.display = 'none';
      }
      return;
    }

    disponibiliteElement.style.display = 'flex';
    disponibiliteElement.className = 'availability-indicator loading';
    disponibiliteElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Vérification...';

    fetch(`/interim/ajax/verifier-disponibilite-candidat/?candidat_id=${candidatId}&date_debut=${dateDebut}&date_fin=${dateFin}`)
      .then(response => response.json())
      .then(data => {
        if (data.disponible) {
          disponibiliteElement.className = 'availability-indicator available';
          disponibiliteElement.innerHTML = '<i class="fas fa-check"></i> ' + data.raison;
        } else {
          disponibiliteElement.className = 'availability-indicator unavailable';
          disponibiliteElement.innerHTML = '<i class="fas fa-times"></i> ' + data.raison;
        }
      })
      .catch(error => {
        console.error('Erreur vérification disponibilité:', error);
        disponibiliteElement.className = 'availability-indicator unavailable';
        disponibiliteElement.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Erreur de vérification';
      });
  }

  // ================================================================
  // FONCTIONS PROPOSITION AUTOMATIQUE
  // ================================================================

  async function propositionAutomatique() {
    console.log('🤖 DEBUT propositionAutomatique');
    
    // Validation des données requises
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
    
    // Afficher le loading
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
    
    // Afficher la section des résultats
    setElementDisplay('autoProposalResults', true);
    
    // Mettre à jour les statistiques
    setElementContent('candidatsCount', `${candidatsAutomatiques.length} candidats trouvés`);
    
    if (candidatsAutomatiques.length > 0) {
      const scores = candidatsAutomatiques.map(c => c.score);
      const minScore = Math.min(...scores);
      const maxScore = Math.max(...scores);
      setElementContent('scoreRange', `Score: ${minScore}-${maxScore}`);
    }
    
    // Remplir les filtres départements
    const filterDepartement = getElement('filterDepartement');
    if (filterDepartement) {
      const departements = [...new Set(candidatsAutomatiques.map(c => c.departement).filter(d => d))];
      filterDepartement.innerHTML = '<option value="">Tous départements</option>';
      departements.forEach(dept => {
        filterDepartement.innerHTML += `<option value="${dept}">${dept}</option>`;
      });
    }
    
    // Afficher le tableau
    afficherTableauCandidats();
  }

  function afficherTableauCandidats() {
    const tableBody = getElement('candidatesTableBody');
    if (!tableBody) return;
    
    tableBody.innerHTML = '';
    
    // Pagination
    const debut = (paginationActuelle.page - 1) * paginationActuelle.taille;
    const fin = debut + paginationActuelle.taille;
    const candidatsPagines = candidatsFiltres.slice(debut, fin);
    
    candidatsPagines.forEach(candidat => {
      const row = creerLigneCandidatTableau(candidat);
      tableBody.appendChild(row);
    });
    
    // Mettre à jour la pagination
    mettreAJourPagination();
  }

  function creerLigneCandidatTableau(candidat) {
    const row = document.createElement('tr');
    row.dataset.candidatId = candidat.id;
    
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
        <input type="radio" name="candidat_auto_selection" value="${candidat.id}" 
               onchange="selectionnerCandidatAuto(${candidat.id})">
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
    
    // Info pagination
    const debut = (paginationActuelle.page - 1) * paginationActuelle.taille + 1;
    const fin = Math.min(debut + paginationActuelle.taille - 1, total);
    setElementContent('paginationInfo', `Affichage de ${debut}-${fin} sur ${total} candidats`);
    
    // Boutons précédent/suivant
    const btnPrev = getElement('btnPrevPage');
    const btnNext = getElement('btnNextPage');
    
    if (btnPrev) {
      btnPrev.disabled = paginationActuelle.page <= 1;
    }
    if (btnNext) {
      btnNext.disabled = paginationActuelle.page >= totalPages;
    }
    
    // Numéros de pages
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

  function selectionnerCandidatAuto(candidatId) {
    console.log('✅ Sélection candidat automatique:', candidatId);
    
    candidatSelectionne = candidatsAutomatiques.find(c => c.id === candidatId);
    if (!candidatSelectionne) {
      console.error('Candidat non trouvé:', candidatId);
      return;
    }
    
    // Marquer la ligne comme sélectionnée
    const rows = document.querySelectorAll('#candidatesTableBody tr');
    rows.forEach(row => {
      row.classList.remove('selected');
      if (row.dataset.candidatId === candidatId.toString()) {
        row.classList.add('selected');
      }
    });
    
    // Afficher la section de sélection
    afficherSectionSelectionCandidat();
  }

  function afficherSectionSelectionCandidat() {
    if (!candidatSelectionne) return;
    
    setElementDisplay('candidateSelection', true);
    
    // Score coloré
    let scoreClass = 'poor';
    if (candidatSelectionne.score >= 80) scoreClass = 'excellent';
    else if (candidatSelectionne.score >= 60) scoreClass = 'good';
    else if (candidatSelectionne.score >= 40) scoreClass = 'average';
    
    const selectedCandidateInfo = getElement('selectedCandidateInfo');
    if (selectedCandidateInfo) {
      selectedCandidateInfo.innerHTML = `
        <div class="selected-candidate-header">
          <div class="selected-candidate-score ${scoreClass}">${candidatSelectionne.score}</div>
          <div class="selected-candidate-details">
            <h4>${candidatSelectionne.nom_complet}</h4>
            <p>Matricule: ${candidatSelectionne.matricule}</p>
          </div>
        </div>
        <div class="selected-candidate-meta">
          <div class="meta-item"><strong>Poste:</strong> ${candidatSelectionne.poste_actuel || 'Non renseigné'}</div>
          <div class="meta-item"><strong>Département:</strong> ${candidatSelectionne.departement || 'Non renseigné'}</div>
          <div class="meta-item"><strong>Ancienneté:</strong> ${candidatSelectionne.anciennete || 'Non renseignée'}</div>
          <div class="meta-item"><strong>Disponibilité:</strong> ${candidatSelectionne.disponibilite?.raison || 'À vérifier'}</div>
        </div>
      `;
    }
    
    // Afficher le bouton d'enregistrement
    setElementDisplay('btnEnregistrerAuto', true);
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
    const filterDept = getElement('filterDepartement')?.value;
    const filterScore = getElement('filterScore')?.value;
    
    candidatsFiltres = candidatsAutomatiques.filter(candidat => {
      // Filtre département
      if (filterDept && candidat.departement !== filterDept) {
        return false;
      }
      
      // Filtre score
      if (filterScore) {
        const [minScore, maxScore] = filterScore.split('-').map(Number);
        if (candidat.score < minScore || candidat.score > maxScore) {
          return false;
        }
      }
      
      return true;
    });
    
    // Réinitialiser la pagination
    paginationActuelle.page = 1;
    afficherTableauCandidats();
    
    setElementContent('candidatsCount', `${candidatsFiltres.length} candidats affichés`);
  }

  // ================================================================
  // FONCTIONS D'ENREGISTREMENT
  // ================================================================

  async function enregistrerPropositionAutomatique() {
    if (!candidatSelectionne) {
      alert('Veuillez sélectionner un candidat');
      return;
    }

    const justification = getElement('justificationAutoCandidat')?.value?.trim();
    if (!justification) {
      alert('La justification est obligatoire');
      getElement('justificationAutoCandidat')?.focus();
      return;
    }

    const formData = {
      action: 'enregistrer_proposition_auto',
      candidat_selectionne_id: candidatSelectionne.id,
      justification: justification,
      competences_specifiques: getElement('competencesSpecifiquesAuto')?.value?.trim() || '',
      liste_candidats: candidatsAutomatiques,
      // Reprendre les données du formulaire
      personne_remplacee_id: getElement('personne_remplacee_id')?.value,
      poste_id: getElement('poste_id')?.value,
      motif_absence_id: getElement('motif_absence_id')?.value,
      date_debut: getElement('date_debut')?.value,
      date_fin: getElement('date_fin')?.value,
      urgence: getElement('urgence')?.value,
      description_poste: getElement('description_poste')?.value,
      competences_indispensables: getElement('competences_indispensables')?.value,
      instructions_particulieres: getElement('instructions_particulieres')?.value,
      nb_max_propositions: getElement('nb_max_propositions')?.value
    };

    await enregistrerDemande(formData);
  }

  async function enregistrerPropositionSpecifique() {
    const candidatSpecifiqueId = getElement('candidatSpecifiqueId')?.value;
    const justification = getElement('justificationSpecifique')?.value?.trim();

    if (!candidatSpecifiqueId) {
      alert('Veuillez sélectionner un candidat spécifique');
      getElement('candidatSpecifiqueMatricule')?.focus();
      return;
    }

    if (!justification) {
      alert('La justification est obligatoire');
      getElement('justificationSpecifique')?.focus();
      return;
    }

    const formData = {
      action: 'enregistrer_proposition_specifique',
      candidat_specifique_id: candidatSpecifiqueId,
      justification: justification,
      competences_specifiques: getElement('competencesSpecifiquesSpec')?.value?.trim() || '',
      experience_pertinente: getElement('experiencePertinentSpec')?.value?.trim() || '',
      liste_candidats: candidatsAutomatiques, // Inclure la liste si elle existe
      // Reprendre les données du formulaire
      personne_remplacee_id: getElement('personne_remplacee_id')?.value,
      poste_id: getElement('poste_id')?.value,
      motif_absence_id: getElement('motif_absence_id')?.value,
      date_debut: getElement('date_debut')?.value,
      date_fin: getElement('date_fin')?.value,
      urgence: getElement('urgence')?.value,
      description_poste: getElement('description_poste')?.value,
      competences_indispensables: getElement('competences_indispensables')?.value,
      instructions_particulieres: getElement('instructions_particulieres')?.value,
      nb_max_propositions: getElement('nb_max_propositions')?.value
    };

    await enregistrerDemande(formData);
  }

  async function enregistrerDemande(formData) {
    const btnEnregistrer = formData.action === 'enregistrer_proposition_auto' 
      ? getElement('btnEnregistrerAuto') 
      : getElement('btnEnregistrerSpecifique');
    
    if (btnEnregistrer) btnEnregistrer.disabled = true;

    try {
      const response = await fetch(form.action || window.location.href, {
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
      
    } finally {
      if (btnEnregistrer) btnEnregistrer.disabled = false;
    }
  }

  // ================================================================
  // EVENT LISTENERS
  // ================================================================

  // Toggle section proposition manuelle
  const toggleProposition = getElement('toggleProposition');
  const propositionContent = getElement('propositionContent');
  
  if (toggleProposition && propositionContent) {
    toggleProposition.addEventListener('click', function() {
      propositionContent.classList.toggle('show');
      toggleProposition.classList.toggle('expanded');
    });
  }

  // Bouton proposition automatique
  const btnPropositionAuto = getElement('btnPropositionAuto');
  if (btnPropositionAuto) {
    btnPropositionAuto.addEventListener('click', propositionAutomatique);
  }

  // Bouton proposition spécifique
  const btnPropositionSpecifique = getElement('btnPropositionSpecifique');
  if (btnPropositionSpecifique) {
    btnPropositionSpecifique.addEventListener('click', function() {
      setElementDisplay('specificProposalSection', true);
    });
  }

  // Boutons d'enregistrement
  const btnEnregistrerAuto = getElement('btnEnregistrerAuto');
  if (btnEnregistrerAuto) {
    btnEnregistrerAuto.addEventListener('click', enregistrerPropositionAutomatique);
  }

  const btnEnregistrerSpecifique = getElement('btnEnregistrerSpecifique');
  if (btnEnregistrerSpecifique) {
    btnEnregistrerSpecifique.addEventListener('click', enregistrerPropositionSpecifique);
  }

  // Filtres
  const filterDepartement = getElement('filterDepartement');
  const filterScore = getElement('filterScore');
  
  if (filterDepartement) {
    filterDepartement.addEventListener('change', appliquerFiltres);
  }
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
  const candidatMatriculeInput = getElement('candidat_propose_matricule');
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

  if (candidatMatriculeInput) {
    const debouncedSearchCandidat = debounce((matricule) => {
      rechercherEmploye(matricule, 'candidat_propose');
    }, 500);

    candidatMatriculeInput.addEventListener('input', function() {
      const matricule = this.value.trim();
      debouncedSearchCandidat(matricule);
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
        verifierDisponibiliteCandidat();
      }
    });

    dateFinInput.addEventListener('change', function() {
      const dateDebut = new Date(dateDebutInput.value);
      const dateFin = new Date(this.value);
      
      if (dateDebut && dateFin < dateDebut) {
        alert('La date de fin doit être postérieure à la date de début');
        this.value = '';
      } else {
        verifierDisponibiliteCandidat();
      }
    });
  }

  // ================================================================
  // SOUMISSION DU FORMULAIRE CLASSIQUE
  // ================================================================

  if (form) {
    form.addEventListener('submit', function(e) {
      e.preventDefault();
      console.log('📝 Soumission du formulaire classique');

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

      // Validation proposition candidat manuelle
      const candidatId = getElement('candidat_propose_id')?.value;
      const justification = getElement('justification_proposition')?.value?.trim();

      if (candidatId && !justification) {
        alert('La justification est obligatoire si vous proposez un candidat');
        getElement('justification_proposition')?.focus();
        return;
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

      // Désactiver le bouton et afficher le spinner
      if (submitBtn) {
        submitBtn.disabled = true;
      }
      if (loadingSpinner) {
        loadingSpinner.classList.add('show');
      }

      // Soumission AJAX classique
      const formData = new FormData(form);

      fetch(form.action || window.location.href, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json'
        }
      })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          showNotification('Demande créée avec succès !', 'success');
          
          if (data.redirect_url) {
            setTimeout(() => {
              window.location.href = data.redirect_url;
            }, 1000);
          } else {
            form.reset();
            masquerInfosEmploye('personne_remplacee');
            masquerInfosEmploye('candidat_propose');
          }
        } else {
          alert('Erreur: ' + (data.error || 'Une erreur est survenue'));
        }
      })
      .catch(error => {
        console.error('Erreur soumission:', error);
        alert('Erreur de communication avec le serveur');
      })
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

  window.selectionnerCandidatAuto = selectionnerCandidatAuto;
  
  window.voirDetailCandidat = function(candidatId) {
    const candidat = candidatsAutomatiques.find(c => c.id === candidatId);
    if (candidat) {
      alert(`Détails du candidat:\n\nNom: ${candidat.nom_complet}\nMatricule: ${candidat.matricule}\nScore: ${candidat.score}\nPoste: ${candidat.poste_actuel || 'Non renseigné'}\nDépartement: ${candidat.departement || 'Non renseigné'}`);
    }
  };

  // ================================================================
  // AMÉLIORATIONS UX
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

  console.log('✅ Formulaire de demande d\'intérim avec proposition automatique initialisé avec succès');
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

