<script src="https://cdn.jsdelivr.net/npm/chart.js">

document.addEventListener('DOMContentLoaded', function() {
  console.log('🔍 Page de recherche d\'intérim initialisée');
  
  // Variables globales
  let searchTimeout;
  let currentFilters = {};
  let isLoading = false;
  
  // === INITIALISATION ===
  initializeSearchForm();
  initializeFilters();
  initializeAnimations();
  initializeCharts();
  initializeEventListeners();
  
  // === FONCTIONS D'INITIALISATION ===
  
  function initializeSearchForm() {
    const searchInput = document.getElementById('q');
    const hiddenInput = document.getElementById('hiddenQ');
    
    if (searchInput) {
      // Synchroniser les champs de recherche
      searchInput.addEventListener('input', function() {
        hiddenInput.value = this.value;
        performSmartSearch(this.value);
      });
      
      // Suggestions en temps réel
      searchInput.addEventListener('input', debounce(function() {
        if (this.value.length >= 2) {
          fetchSearchSuggestions(this.value);
        } else {
          hideSuggestions();
        }
      }, 300));
      
      // Masquer suggestions quand on clique ailleurs
      document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target)) {
          hideSuggestions();
        }
      });
    }
  }
  
  function initializeFilters() {
    // Filtres rapides
    const quickFilters = document.querySelectorAll('.filter-tag');
    quickFilters.forEach(filter => {
      filter.addEventListener('click', function() {
        const action = this.getAttribute('onclick');
        if (action) {
          eval(action);
        }
      });
    });
    
    // Filtres détaillés avec auto-submit
    const filterInputs = document.querySelectorAll('#departement, #site, #statut, #urgence, #avec_candidat, #niveau_validation');
    filterInputs.forEach(input => {
      input.addEventListener('change', debounce(function() {
        updateActiveFilters();
        submitSearchForm();
      }, 500));
    });
    
    // Filtres de dates
    const dateInputs = document.querySelectorAll('#date_debut, #date_fin');
    dateInputs.forEach(input => {
      input.addEventListener('change', function() {
        updateActiveFilters();
        submitSearchForm();
      });
    });
    
    // Filtres de scores
    const scoreInputs = document.querySelectorAll('#score_min, #score_max');
    scoreInputs.forEach(input => {
      input.addEventListener('input', debounce(function() {
        validateScoreInput(this);
        updateActiveFilters();
        submitSearchForm();
      }, 800));
    });
    
    // Toggle des filtres détaillés
    const toggleBtn = document.getElementById('toggleFilters');
    const filtersContainer = document.getElementById('detailedFilters');
    const toggleText = document.getElementById('toggleText');
    
    if (toggleBtn && filtersContainer) {
      toggleBtn.addEventListener('click', function() {
        const isVisible = filtersContainer.style.display !== 'none';
        filtersContainer.style.display = isVisible ? 'none' : 'block';
        toggleText.textContent = isVisible ? 'Afficher les filtres' : 'Masquer les filtres';
        
        const icon = toggleBtn.querySelector('i');
        icon.className = isVisible ? 'fas fa-chevron-down' : 'fas fa-chevron-up';
      });
    }
    
    // Initialiser l'affichage des filtres actifs
    updateActiveFilters();
  }
  
  function initializeAnimations() {
    // Animation progressive des cartes de statistiques
    const statCards = document.querySelectorAll('.stat-card');
    statCards.forEach((card, index) => {
      card.style.opacity = '0';
      card.style.transform = 'translateY(20px)';
      
      setTimeout(() => {
        card.style.transition = 'all 0.6s ease';
        card.style.opacity = '1';
        card.style.transform = 'translateY(0)';
      }, 100 + (index * 100));
    });
    
    // Animation des cartes de demandes
    const demandeRows = document.querySelectorAll('.demande-row');
    demandeRows.forEach((row, index) => {
      row.style.opacity = '0';
      row.style.transform = 'translateX(-20px)';
      
      setTimeout(() => {
        row.style.transition = 'all 0.5s ease';
        row.style.opacity = '1';
        row.style.transform = 'translateX(0)';
      }, 200 + (index * 100));
    });
    
    // Compteurs animés pour les statistiques
    animateStatNumbers();
  }
  
  function initializeCharts() {
    // Graphique d'évolution des demandes
    const chartCanvas = document.getElementById('demandesChart');
    if (chartCanvas && window.evolutionData) {
      createEvolutionChart(chartCanvas);
    }
  }
  
  function initializeEventListeners() {
    // Sélection/désélection des demandes
    const checkboxes = document.querySelectorAll('.form-check-input[id^="check_"]');
    checkboxes.forEach(checkbox => {
      checkbox.addEventListener('change', updateBatchActions);
    });
    
    // Tri des résultats
    const sortSelect = document.getElementById('sortBy');
    if (sortSelect) {
      sortSelect.addEventListener('change', function() {
        applySorting(this.value);
      });
    }
    
    // Changement de vue
    const viewButtons = document.querySelectorAll('[onclick^="switchView"]');
    viewButtons.forEach(btn => {
      btn.addEventListener('click', function() {
        const view = this.getAttribute('onclick').match(/'([^']+)'/)[1];
        switchView(view);
      });
    });
  }
  
  // === FONCTIONS DE RECHERCHE ===
  
  function performSmartSearch(query) {
    console.log('🔍 Recherche intelligente:', query);
    
    // Analyser la requête pour des patterns spéciaux
    analyzeSearchQuery(query);
    
    // Déclencher la recherche avec délai
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      if (query.length >= 2 || query.length === 0) {
        submitSearchForm();
      }
    }, 600);
  }
  
  function analyzeSearchQuery(query) {
    // Pattern pour les scores : "score >80", "score:75", etc.
    const scorePattern = /score\s*[><=:]\s*(\d+)/i;
    const scoreMatch = query.match(scorePattern);
    
    if (scoreMatch) {
      const scoreValue = scoreMatch[1];
      const operator = scoreMatch[0].match(/[><=:]/)[0];
      
      if (operator === '>' || operator === ':') {
        document.getElementById('score_min').value = scoreValue;
      } else if (operator === '<') {
        document.getElementById('score_max').value = scoreValue;
      } else if (operator === '=') {
        document.getElementById('score_min').value = scoreValue;
        document.getElementById('score_max').value = scoreValue;
      }
    }
    
    // Pattern pour l'urgence : "urgent", "critique", etc.
    if (/urgent|critique/i.test(query)) {
      document.getElementById('urgence').value = 'CRITIQUE';
    } else if (/élevé|elevé|haute/i.test(query)) {
      document.getElementById('urgence').value = 'ELEVEE';
    }
    
    // Pattern pour les statuts
    if (/validation|attente/i.test(query)) {
      document.getElementById('statut').value = 'EN_VALIDATION';
    } else if (/terminé|terminée|fini/i.test(query)) {
      document.getElementById('statut').value = 'TERMINEE';
    }
  }
  
  function fetchSearchSuggestions(query) {
    // Simulation d'appel AJAX pour les suggestions
    // En production, remplacer par un appel réel à l'API
    const suggestions = [
      { label: `Demande: ${query}`, value: query, category: 'Numéros' },
      { label: `Poste: ${query}`, value: query, category: 'Postes' },
      { label: `Personne: ${query}`, value: query, category: 'Personnes' }
    ];
    
    showSuggestions(suggestions);
  }
  
  function showSuggestions(suggestions) {
    const container = document.getElementById('searchSuggestions');
    if (!container || suggestions.length === 0) return;
    
    container.innerHTML = '';
    
    suggestions.forEach(suggestion => {
      const item = document.createElement('div');
      item.className = 'suggestion-item';
      item.innerHTML = `
        <div class="suggestion-content">
          <strong>${suggestion.label}</strong>
          <small class="text-muted">${suggestion.category}</small>
        </div>
      `;
      
      item.addEventListener('click', () => {
        document.getElementById('q').value = suggestion.value;
        document.getElementById('hiddenQ').value = suggestion.value;
        hideSuggestions();
        submitSearchForm();
      });
      
      container.appendChild(item);
    });
    
    container.style.display = 'block';
  }
  
  function hideSuggestions() {
    const container = document.getElementById('searchSuggestions');
    if (container) {
      container.style.display = 'none';
    }
  }
  
  // === FONCTIONS DE FILTRAGE ===
  
  function toggleQuickFilter(type, value) {
    console.log('🏷️ Filtre rapide:', type, value);
    
    let currentValue = '';
    let inputElement = null;
    
    switch(type) {
      case 'urgence':
        inputElement = document.getElementById('urgence');
        currentValue = inputElement.value;
        break;
      case 'avec_candidat':
        inputElement = document.getElementById('avec_candidat');
        currentValue = inputElement.value;
        break;
      case 'statut':
        inputElement = document.getElementById('statut');
        currentValue = inputElement.value;
        break;
      case 'periode':
        if (value === 'cette_semaine') {
          setDateRange('week');
          return;
        }
        break;
      case 'score':
        if (value === 'excellent') {
          document.getElementById('score_min').value = '80';
          document.getElementById('score_max').value = '';
          updateActiveFilters();
          submitSearchForm();
          return;
        }
        break;
    }
    
    if (inputElement) {
      inputElement.value = currentValue === value ? '' : value;
      updateActiveFilters();
      submitSearchForm();
    }
  }
  
  function resetAllFilters() {
    console.log('🧹 Réinitialisation des filtres');
    
    // Vider tous les champs
    document.getElementById('q').value = '';
    document.getElementById('hiddenQ').value = '';
    document.getElementById('departement').value = '';
    document.getElementById('site').value = '';
    document.getElementById('statut').value = '';
    document.getElementById('urgence').value = '';
    document.getElementById('avec_candidat').value = '';
    document.getElementById('niveau_validation').value = '';
    document.getElementById('date_debut').value = '';
    document.getElementById('date_fin').value = '';
    document.getElementById('score_min').value = '';
    document.getElementById('score_max').value = '';
    
    updateActiveFilters();
    submitSearchForm();
  }
  
  function setDateRange(period) {
    const today = new Date();
    const formatDate = (date) => date.toISOString().split('T')[0];
    
    let startDate, endDate;
    
    switch(period) {
      case 'today':
        startDate = endDate = today;
        break;
      case 'week':
        startDate = new Date(today);
        startDate.setDate(today.getDate() - today.getDay()); // Lundi de cette semaine
        endDate = new Date(startDate);
        endDate.setDate(startDate.getDate() + 6); // Dimanche
        break;
      case 'month':
        startDate = new Date(today.getFullYear(), today.getMonth(), 1);
        endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        break;
    }
    
    if (startDate && endDate) {
      document.getElementById('date_debut').value = formatDate(startDate);
      document.getElementById('date_fin').value = formatDate(endDate);
      updateActiveFilters();
      submitSearchForm();
    }
  }
  
  function updateActiveFilters() {
    const container = document.getElementById('activeFilters');
    if (!container) return;
    
    const filters = [];
    
    // Collecter tous les filtres actifs
    const filterFields = {
      'q': 'Recherche',
      'departement': 'Département',
      'site': 'Site',
      'statut': 'Statut',
      'urgence': 'Urgence',
      'avec_candidat': 'Candidat',
      'niveau_validation': 'Niveau',
      'date_debut': 'Date début',
      'date_fin': 'Date fin',
      'score_min': 'Score min',
      'score_max': 'Score max'
    };
    
    Object.entries(filterFields).forEach(([fieldId, label]) => {
      const field = document.getElementById(fieldId);
      if (field && field.value) {
        let displayValue = field.value;
        
        // Formatage spécial pour certains champs
        if (field.tagName === 'SELECT') {
          const option = field.options[field.selectedIndex];
          displayValue = option ? option.text : field.value;
        }
        
        filters.push({
          field: fieldId,
          label: label,
          value: displayValue,
          rawValue: field.value
        });
      }
    });
    
    // Afficher les filtres actifs
    container.innerHTML = filters.map(filter => `
      <div class="active-filter">
        <strong>${filter.label}:</strong> ${filter.value}
        <span class="remove-filter" onclick="removeFilter('${filter.field}')">
          <i class="fas fa-times"></i>
        </span>
      </div>
    `).join('');
  }
  
  function removeFilter(fieldId) {
    const field = document.getElementById(fieldId);
    if (field) {
      field.value = '';
      updateActiveFilters();
      submitSearchForm();
    }
  }
  
  function validateScoreInput(input) {
    const value = parseInt(input.value);
    if (isNaN(value)) return;
    
    if (value < 0) input.value = 0;
    if (value > 100) input.value = 100;
    
    // Validation croisée des scores min/max
    const scoreMin = document.getElementById('score_min');
    const scoreMax = document.getElementById('score_max');
    
    if (scoreMin.value && scoreMax.value) {
      const min = parseInt(scoreMin.value);
      const max = parseInt(scoreMax.value);
      
      if (min > max) {
        if (input === scoreMin) {
          scoreMax.value = min;
        } else {
          scoreMin.value = max;
        }
      }
    }
  }
  
  // === FONCTIONS D'INTERFACE ===
  
  function switchView(view) {
    const container = document.getElementById('resultsContainer');
    const viewButtons = document.querySelectorAll('.view-controls .btn');
    
    // Mettre à jour les boutons
    viewButtons.forEach(btn => btn.classList.remove('active'));
    event.target.closest('.btn').classList.add('active');
    
    // Appliquer la vue
    container.className = `results-container view-${view}`;
    
    console.log('👁️ Vue changée:', view);
  }
  
  function applySorting(sortType) {
    console.log('🔄 Tri appliqué:', sortType);
    
    const container = document.getElementById('resultsContainer');
    const rows = Array.from(container.querySelectorAll('.demande-row'));
    
    rows.sort((a, b) => {
      switch(sortType) {
        case 'date_desc':
          return new Date(b.dataset.dateCreation) - new Date(a.dataset.dateCreation);
        case 'date_asc':
          return new Date(a.dataset.dateCreation) - new Date(b.dataset.dateCreation);
        case 'score_desc':
          return (b.dataset.score || 0) - (a.dataset.score || 0);
        case 'urgence_desc':
          const urgenceOrder = {'CRITIQUE': 4, 'ELEVEE': 3, 'MOYENNE': 2, 'NORMALE': 1};
          return (urgenceOrder[b.dataset.urgence] || 0) - (urgenceOrder[a.dataset.urgence] || 0);
        default:
          return 0;
      }
    });
    
    // Réorganiser les éléments
    rows.forEach(row => container.appendChild(row));
    
    // Réanimer les éléments
    rows.forEach((row, index) => {
      row.style.animation = 'none';
      setTimeout(() => {
        row.style.animation = `fadeInUp 0.3s ease-out ${index * 50}ms forwards`;
      }, 10);
    });
  }
  
  function updateBatchActions() {
    const selectedCheckboxes = document.querySelectorAll('.form-check-input[id^="check_"]:checked');
    const batchActions = document.querySelector('.batch-actions');
    
    if (batchActions) {
      const count = selectedCheckboxes.length;
      const button = batchActions.querySelector('.dropdown-toggle');
      
      if (count > 0) {
        button.innerHTML = `<i class="fas fa-cogs"></i> Actions (${count})`;
        batchActions.style.display = 'block';
      } else {
        button.innerHTML = '<i class="fas fa-cogs"></i> Actions';
      }
    }
  }
  
  function selectAllVisible() {
    const checkboxes = document.querySelectorAll('.form-check-input[id^="check_"]');
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);
    
    checkboxes.forEach(checkbox => {
      checkbox.checked = !allChecked;
    });
    
    updateBatchActions();
  }
  
  // === FONCTIONS D'ANIMATION ===
  
  function animateStatNumbers() {
    const statNumbers = document.querySelectorAll('.stat-number');
    
    statNumbers.forEach(element => {
      const text = element.textContent;
      const match = text.match(/(\d+(?:\.\d+)?)/);
      
      if (match) {
        const finalValue = parseFloat(match[1]);
        const suffix = text.replace(match[1], '');
        
        animateNumber(element, 0, finalValue, 1500, suffix);
      }
    });
  }
  
  function animateNumber(element, start, end, duration, suffix = '') {
    const startTime = performance.now();
    
    function update(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      // Fonction d'easing
      const easeOut = 1 - Math.pow(1 - progress, 3);
      const current = start + (end - start) * easeOut;
      
      element.textContent = Math.floor(current) + suffix;
      
      if (progress < 1) {
        requestAnimationFrame(update);
      } else {
        element.textContent = end + suffix;
      }
    }
    
    requestAnimationFrame(update);
  }
  
  // === FONCTIONS DE GRAPHIQUES ===
  
  function createEvolutionChart(canvas) {
    const ctx = canvas.getContext('2d');
    
    // Données d'exemple (à remplacer par les vraies données)
    const data = {
      labels: ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'],
      datasets: [{
        label: 'Demandes créées',
        data: [12, 19, 8, 15, 10, 13, 9],
        borderColor: '#007bff',
        backgroundColor: 'rgba(0, 123, 255, 0.1)',
        borderWidth: 3,
        fill: true,
        tension: 0.4
      }]
    };
    
    new Chart(ctx, {
      type: 'line',
      data: data,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: {
              color: 'rgba(0,0,0,0.1)'
            }
          },
          x: {
            grid: {
              display: false
            }
          }
        },
        elements: {
          point: {
            radius: 4,
            hoverRadius: 6
          }
        }
      }
    });
  }
  
  // === FONCTIONS UTILITAIRES ===
  
  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func.apply(this, args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }
  
  function submitSearchForm() {
    if (isLoading) return;
    
    const form = document.getElementById('searchForm');
    if (form) {
      showLoading();
      form.submit();
    }
  }
  
  function showLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
      overlay.style.display = 'flex';
      isLoading = true;
      
      // Simulation de progression
      const progressBar = document.getElementById('loadingProgress');
      let progress = 0;
      const interval = setInterval(() => {
        progress += Math.random() * 20;
        if (progress >= 100) {
          progress = 100;
          clearInterval(interval);
        }
        if (progressBar) {
          progressBar.style.width = progress + '%';
        }
      }, 200);
    }
  }
  
  function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
      overlay.style.display = 'none';
      isLoading = false;
    }
  }
  
  // === FONCTIONS EXPOSÉES GLOBALEMENT ===
  
  window.clearSearch = function() {
    document.getElementById('q').value = '';
    document.getElementById('hiddenQ').value = '';
    hideSuggestions();
    submitSearchForm();
  };
  
  window.startVoiceSearch = function() {
    if ('webkitSpeechRecognition' in window) {
      const recognition = new webkitSpeechRecognition();
      recognition.lang = 'fr-FR';
      recognition.onresult = function(event) {
        const result = event.results[0][0].transcript;
        document.getElementById('q').value = result;
        document.getElementById('hiddenQ').value = result;
        submitSearchForm();
      };
      recognition.start();
    } else {
      alert('Recherche vocale non supportée par votre navigateur');
    }
  };
  
  window.setSearchExample = function(example) {
    document.getElementById('q').value = example;
    document.getElementById('hiddenQ').value = example;
    submitSearchForm();
  };
  
  window.advancedSearch = function() {
    const filtersContainer = document.getElementById('detailedFilters');
    if (filtersContainer) {
      filtersContainer.style.display = 'block';
      filtersContainer.scrollIntoView({ behavior: 'smooth' });
    }
  };
   
  window.refreshStats = function() {
    const btn = event.target.closest('button');
    const icon = btn.querySelector('i');
    const originalClass = icon.className;
    
    icon.className = 'fas fa-spinner fa-spin';
    btn.disabled = true;
    
    setTimeout(() => {
      location.reload();
    }, 1000);
  };
  
  window.filterByStatus = function(filter) {
    if (filter) {
      const params = new URLSearchParams(filter);
      params.forEach((value, key) => {
        const field = document.getElementById(key);
        if (field) {
          field.value = value;
        }
      });
    }
    
    updateActiveFilters();
    submitSearchForm();
  };
  
  window.saveCurrentSearch = function() {
    // Ici on pourrait sauvegarder la recherche actuelle
    // Pour la démo, on affiche juste une notification
    showNotification('Recherche sauvegardée', 'success');
  };
  
  window.bulkExport = function() {
    const selected = document.querySelectorAll('.form-check-input[id^="check_"]:checked');
    console.log('📤 Export en lot:', selected.length, 'demandes');
    showNotification(`Export de ${selected.length} demandes en cours...`, 'info');
  };
  
  window.bulkNotify = function() {
    const selected = document.querySelectorAll('.form-check-input[id^="check_"]:checked');
    console.log('🔔 Notification en lot:', selected.length, 'demandes');
    showNotification(`Notifications envoyées pour ${selected.length} demandes`, 'success');
  };
  
  window.viewDetails = function(demandeId) {
    console.log('👁️ Voir détails demande:', demandeId);
    // Redirection vers la page de détails
    window.location.href = `/interim/demande/${demandeId}/`;
  };
  
  window.validateDemande = function(demandeId) {
    console.log('✅ Valider demande:', demandeId);
    if (confirm('Êtes-vous sûr de vouloir valider cette demande ?')) {
      // Ici on ferait l'appel AJAX pour valider
      showNotification('Demande validée avec succès', 'success');
    }
  };
  
  window.editDemande = function(demandeId) {
    console.log('✏️ Modifier demande:', demandeId);
    window.location.href = `/interim/demande/${demandeId}/modifier/`;
  };
  
  window.duplicateDemande = function(demandeId) {
    console.log('📋 Dupliquer demande:', demandeId);
    if (confirm('Voulez-vous créer une nouvelle demande basée sur celle-ci ?')) {
      window.location.href = `/interim/demande/${demandeId}/dupliquer/`;
    }
  };
  
  window.exportDemande = function(demandeId) {
    console.log('📄 Exporter demande:', demandeId);
    // Créer un lien de téléchargement temporaire
    const link = document.createElement('a');
    link.href = `/interim/demande/${demandeId}/export/`;
    link.download = `demande_${demandeId}.pdf`;
    link.click();
    showNotification('Export en cours...', 'info');
  };
  
  window.addToFavorites = function(demandeId) {
    console.log('⭐ Ajouter aux favoris:', demandeId);
    // Ici on ferait l'appel AJAX pour ajouter aux favoris
    showNotification('Demande ajoutée aux favoris', 'success');
  };
  
  window.viewHistory = function(demandeId) {
    console.log('📋 Voir historique:', demandeId);
    window.location.href = `/interim/demande/${demandeId}/historique/`;
  };
  
  window.copyToClipboard = function(text, element) {
    navigator.clipboard.writeText(text).then(() => {
      element.style.transform = 'scale(1.1)';
      element.style.backgroundColor = '#28a745';
      element.style.color = 'white';
      
      setTimeout(() => {
        element.style.transform = 'scale(1)';
        element.style.backgroundColor = '#e3f2fd';
        element.style.color = '#007bff';
      }, 200);
      
      showNotification('Numéro copié dans le presse-papiers', 'success');
    });
  };
  
  window.startExport = function() {
    const format = document.querySelector('input[name="format"]:checked').value;
    const options = {
      basicInfo: document.getElementById('includeBasicInfo').checked,
      scoring: document.getElementById('includeScoring').checked,
      justifications: document.getElementById('includeJustifications').checked,
      history: document.getElementById('includeHistory').checked
    };
    
    console.log('📤 Démarrage export:', format, options);
    
    // Simulation d'export

    showLoading();
    
    setTimeout(() => {
      hideLoading();
      showNotification('Export terminé avec succès', 'success');
    }, 3000);
  };
  
  window.cancelLoading = function() {
    hideLoading();
    showNotification('Opération annulée', 'warning');
  };
  
  // === FONCTIONS DE NOTIFICATION ===
  
  function showNotification(message, type = 'info') {
    const container = document.querySelector('.toast-container');
    if (!container) return;
    
    const toastId = 'toast_' + Date.now();
    const iconMap = {
      success: 'fa-check-circle',
      error: 'fa-exclamation-circle',
      warning: 'fa-exclamation-triangle',
      info: 'fa-info-circle'
    };
    
    const colorMap = {
      success: 'text-success',
      error: 'text-danger',
      warning: 'text-warning',
      info: 'text-info'
    };
    
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = 'toast';
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
      <div class="toast-header">
        <i class="fas ${iconMap[type]} ${colorMap[type]} me-2"></i>
        <strong class="me-auto">Notification</strong>
        <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
      </div>
      <div class="toast-body">
        ${message}
      </div>
    `;
    
    container.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast, {
      autohide: true,
      delay: type === 'error' ? 8000 : 5000
    });
    
    bsToast.show();
    
    toast.addEventListener('hidden.bs.toast', () => {
      toast.remove();
    });
  }
  
  // === GESTION DES ERREURS ===
  
  window.addEventListener('error', function(e) {
    console.error('Erreur JavaScript:', e.error);
    hideLoading();
    showNotification('Une erreur inattendue s\'est produite', 'error');
  });
  
  // === RACCOURCIS CLAVIER ===
  
  document.addEventListener('keydown', function(e) {
    // Ctrl+F ou Cmd+F pour focus sur la recherche
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      const searchInput = document.getElementById('q');
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    }
    
    // Échap pour fermer les suggestions ou modals
    if (e.key === 'Escape') {
      hideSuggestions();
      hideLoading();
    }
    
    // Entrée pour lancer la recherche si on est dans le champ de recherche
    if (e.key === 'Enter' && document.activeElement.id === 'q') {
      e.preventDefault();
      submitSearchForm();
    }
  });
  
  // === SAUVEGARDE AUTOMATIQUE DE L'ÉTAT ===
  
  function saveSearchState() {
    const state = {
      query: document.getElementById('q').value,
      filters: {
        departement: document.getElementById('departement').value,
        site: document.getElementById('site').value,
        statut: document.getElementById('statut').value,
        urgence: document.getElementById('urgence').value,
        avec_candidat: document.getElementById('avec_candidat').value,
        niveau_validation: document.getElementById('niveau_validation').value,
        date_debut: document.getElementById('date_debut').value,
        date_fin: document.getElementById('date_fin').value,
        score_min: document.getElementById('score_min').value,
        score_max: document.getElementById('score_max').value
      },
      timestamp: Date.now()
    };
    
    localStorage.setItem('interim_search_state', JSON.stringify(state));
  }
  
  function restoreSearchState() {
    try {
      const saved = localStorage.getItem('interim_search_state');
      if (!saved) return;
      
      const state = JSON.parse(saved);
      
      // Ne restaurer que si c'est récent (moins de 1 heure)
      if (Date.now() - state.timestamp > 3600000) return;
      
      // Restaurer seulement si aucun paramètre n'est déjà défini
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.toString()) return;
      
      document.getElementById('q').value = state.query || '';
      document.getElementById('hiddenQ').value = state.query || '';
      
      Object.entries(state.filters).forEach(([key, value]) => {
        const element = document.getElementById(key);
        if (element && value) {
          element.value = value;
        }
      });
      
      updateActiveFilters();
      
    } catch (error) {
      console.warn('Erreur lors de la restauration de l\'état:', error);
    }
  }
  
  // Sauvegarder l'état avant de quitter la page
  window.addEventListener('beforeunload', saveSearchState);
  
  // Restaurer l'état au chargement
  restoreSearchState();
  
  // === MÉTRIQUES ET ANALYTICS ===
  
  function trackSearchEvent(action, details = {}) {
    // Ici on pourrait envoyer des métriques à un service d'analytics
    console.log('📊 Événement tracké:', action, details);
    
    // Exemple d'envoi à Google Analytics (si configuré)
    if (typeof gtag === 'function') {
      gtag('event', action, {
        event_category: 'search',
        event_label: 'interim_requests',
        custom_map: details
      });
    }
  }
  
  // Tracker certains événements
  document.getElementById('q').addEventListener('input', debounce(function() {
    if (this.value.length >= 3) {
      trackSearchEvent('search_query_typed', { query_length: this.value.length });
    }
  }, 2000));
  
  // === OPTIMISATIONS PERFORMANCE ===
  
  // Observer d'intersection pour le lazy loading des images/contenus
  const observerOptions = {
    root: null,
    rootMargin: '50px',
    threshold: 0.1
  };
  
  const lazyObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const element = entry.target;
        
        // Charger les images lazy
        const lazyImages = element.querySelectorAll('img[data-src]');
        lazyImages.forEach(img => {
          img.src = img.dataset.src;
          img.removeAttribute('data-src');
        });
        
        // Animer l'entrée des éléments
        element.classList.add('animated', 'fadeInUp');
        
        lazyObserver.unobserve(element);
      }
    });
  }, observerOptions);
  
  // Observer toutes les cartes de demandes
  document.querySelectorAll('.demande-row').forEach(row => {
    lazyObserver.observe(row);
  });
  
  // === ACCESSIBILITÉ ===
  
  // Support du clavier pour les filtres tags
  document.querySelectorAll('.filter-tag').forEach(tag => {
    tag.setAttribute('tabindex', '0');
    tag.setAttribute('role', 'button');
    
    tag.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.click();
      }
    });
  });
  
  // Annonces pour les lecteurs d'écran
  function announceToScreenReader(message) {
    const announcement = document.createElement('div');
    announcement.setAttribute('aria-live', 'polite');
    announcement.setAttribute('aria-atomic', 'true');
    announcement.style.position = 'absolute';
    announcement.style.left = '-10000px';
    announcement.style.width = '1px';
    announcement.style.height = '1px';
    announcement.style.overflow = 'hidden';
    announcement.textContent = message;
    
    document.body.appendChild(announcement);
    
    setTimeout(() => {
      document.body.removeChild(announcement);
    }, 1000);
  }
  
  // === FINALISATION ===
  
  console.log('✅ Initialisation complète de la recherche d\'intérim');
  
  // Annoncer aux lecteurs d'écran que la page est prête
  announceToScreenReader('Page de recherche d\'intérim chargée et prête à utiliser');
  
  // Masquer l'overlay de chargement si visible
  hideLoading();
  
  // Focus sur le champ de recherche si aucun autre élément n'est focusé
  setTimeout(() => {
    if (document.activeElement === document.body) {
      const searchInput = document.getElementById('q');
      if (searchInput && !searchInput.value) {
        searchInput.focus();
      }
    }
  }, 500);
  
  // Performance: marquer la fin du chargement
  if ('performance' in window && 'mark' in performance) {
    performance.mark('interim-search-loaded');
  }
});

// === FONCTIONS GLOBALES SUPPLÉMENTAIRES ===

// Fonction pour réinitialiser complètement la page
window.resetPage = function() {
  localStorage.removeItem('interim_search_state');
  window.location.href = window.location.pathname;
};

// Fonction pour partager un lien de recherche
window.shareSearch = function() {
  const url = window.location.href;
  if (navigator.share) {
    navigator.share({
      title: 'Recherche d\'intérim',
      url: url
    });
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(url).then(() => {
      showNotification('Lien copié dans le presse-papiers', 'success');
    });
  }
};

// Fonction pour basculer entre thème clair/sombre (si implémenté)
window.toggleTheme = function() {
  const body = document.body;
  const isDark = body.classList.contains('dark-theme');
  
  if (isDark) {
    body.classList.remove('dark-theme');
    localStorage.setItem('theme', 'light');
  } else {
    body.classList.add('dark-theme');
    localStorage.setItem('theme', 'dark');
  }
  
  showNotification(`Thème ${isDark ? 'clair' : 'sombre'} activé`, 'info');
};

// Fonction pour obtenir des statistiques de performance
window.getPerformanceStats = function() {
  if ('performance' in window) {
    const navigation = performance.getEntriesByType('navigation')[0];
    const stats = {
      loadTime: Math.round(navigation.loadEventEnd - navigation.fetchStart),
      domReady: Math.round(navigation.domContentLoadedEventEnd - navigation.fetchStart),
      ttfb: Math.round(navigation.responseStart - navigation.fetchStart)
    };
    
    console.table(stats);
    return stats;
  }
  return null;
};

// Fonction d'aide pour le debug
window.debugSearch = function() {
  const debug = {
    searchParams: {
      query: document.getElementById('q').value,
      hidden: document.getElementById('hiddenQ').value
    },
    activeFilters: currentFilters,
    url: window.location.href,
    performance: getPerformanceStats(),
    localStorage: localStorage.getItem('interim_search_state')
  };
  
  console.group('🔍 Debug Recherche Intérim');
  console.log('Paramètres:', debug.searchParams);
  console.log('Filtres actifs:', debug.activeFilters);
  console.log('URL:', debug.url);
  console.log('Performance:', debug.performance);
  console.log('État sauvé:', debug.localStorage);
  console.groupEnd();
  
  return debug;
};

// Export pour les tests unitaires si nécessaire
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    debounce,
    validateScoreInput,
    animateNumber,
    showNotification
  };
}

