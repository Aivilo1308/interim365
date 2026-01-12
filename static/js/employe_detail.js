
document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Initialisation de la page détail employé');

  // ================================================================
  // GESTION DES ONGLETS
  // ================================================================

  const tabButtons = document.querySelectorAll('.tab-button');
  const tabContents = document.querySelectorAll('.tab-content');

  // Fonction pour changer d'onglet
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
      
      // Sauvegarder l'onglet actif dans le localStorage
      localStorage.setItem('activeEmployeeTab', targetTabId);
      
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

  // Restaurer l'onglet actif depuis le localStorage
  const savedTab = localStorage.getItem('activeEmployeeTab');
  if (savedTab && document.getElementById(`tab-${savedTab}`)) {
    switchTab(savedTab);
  }

  // ================================================================
  // FILTRAGE DES COMPÉTENCES
  // ================================================================

  const filterCategorie = document.getElementById('filterCategorie');
  const filterNiveau = document.getElementById('filterNiveau');
  const competencesGrid = document.getElementById('competencesGrid');

  function filtrerCompetences() {
    if (!competencesGrid) return;

    const categorieFiltre = filterCategorie?.value || '';
    const niveauFiltre = filterNiveau?.value || '';
    
    const competenceCards = competencesGrid.querySelectorAll('.competence-card');
    let visibleCount = 0;

    competenceCards.forEach(card => {
      const categorie = card.dataset.categorie || '';
      const niveau = card.dataset.niveau || '';
      
      const matchCategorie = !categorieFiltre || categorie === categorieFiltre;
      const matchNiveau = !niveauFiltre || niveau === niveauFiltre;
      
      if (matchCategorie && matchNiveau) {
        card.style.display = 'block';
        visibleCount++;
      } else {
        card.style.display = 'none';
      }
    });

    console.log(`🔍 Filtrage compétences: ${visibleCount} visibles sur ${competenceCards.length}`);
    
    // Afficher un message si aucune compétence ne correspond
    let noResultsMessage = competencesGrid.querySelector('.no-results-message');
    if (visibleCount === 0 && competenceCards.length > 0) {
      if (!noResultsMessage) {
        noResultsMessage = document.createElement('div');
        noResultsMessage.className = 'no-results-message empty-state';
        noResultsMessage.innerHTML = `
          <i class="fas fa-search"></i>
          <h3>Aucune compétence trouvée</h3>
          <p>Aucune compétence ne correspond aux filtres sélectionnés.</p>
        `;
        competencesGrid.appendChild(noResultsMessage);
      }
      noResultsMessage.style.display = 'block';
    } else if (noResultsMessage) {
      noResultsMessage.style.display = 'none';
    }
  }

  // Event listeners pour les filtres
  if (filterCategorie) {
    filterCategorie.addEventListener('change', filtrerCompetences);
  }
  if (filterNiveau) {
    filterNiveau.addEventListener('change', filtrerCompetences);
  }

  // ================================================================
  // VÉRIFICATION DE DISPONIBILITÉ
  // ================================================================

  const btnCheckAvailability = document.getElementById('btnCheckAvailability');
  const availabilityCheck = document.getElementById('availabilityCheck');
  const availabilityResult = document.getElementById('availabilityResult');

  if (btnCheckAvailability) {
    btnCheckAvailability.addEventListener('click', function() {
      console.log('🔍 Vérification de disponibilité demandée');
      
      // Afficher la zone de résultats
      if (availabilityCheck) {
        availabilityCheck.style.display = 'block';
      }
      
      // Afficher le loading
      if (availabilityResult) {
        availabilityResult.innerHTML = `
          <i class="fas fa-spinner fa-spin"></i>
          Vérification de la disponibilité en cours...
        `;
      }
      
      // Désactiver le bouton
      this.disabled = true;
      this.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Vérification...';

      // Récupérer le matricule depuis l'URL ou les données de la page
      const matricule = getEmployeeMatricule();

      // Simulation d'une vérification (remplacer par un appel AJAX réel)
      setTimeout(() => {
        checkEmployeeAvailability(matricule);
      }, 1500);
    });
  }

  function getEmployeeMatricule() {
    // Extraire le matricule depuis l'URL ou les données de la page
    const pathParts = window.location.pathname.split('/');
    return pathParts[pathParts.length - 2] || '';
  }

  async function checkEmployeeAvailability(matricule) {
    try {
      const response = await fetch(`/interim/ajax/verifier-disponibilite-employe/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || '',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
          matricule: matricule,
          date_debut: new Date().toISOString().split('T')[0],
          date_fin: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        })
      });

      let data;
      if (response.ok) {
        data = await response.json();
      } else {
        throw new Error(`Erreur HTTP ${response.status}`);
      }

      // Afficher les résultats
      if (availabilityResult) {
        if (data.success) {
          const disponible = data.disponible;
          const raison = data.raison || 'Aucune information disponible';
          
          availabilityResult.innerHTML = `
            <div class="availability-status-result ${disponible ? 'available' : 'unavailable'}">
              <i class="fas fa-${disponible ? 'check-circle' : 'times-circle'}"></i>
              <strong>${disponible ? 'Disponible' : 'Non disponible'}</strong>
            </div>
            <p>${raison}</p>
            ${data.prochaine_disponibilite ? `<p><strong>Prochaine disponibilité:</strong> ${data.prochaine_disponibilite}</p>` : ''}
          `;
        } else {
          availabilityResult.innerHTML = `
            <div class="availability-status-result error">
              <i class="fas fa-exclamation-triangle"></i>
              <strong>Erreur</strong>
            </div>
            <p>${data.error || 'Impossible de vérifier la disponibilité'}</p>
          `;
        }
      }

    } catch (error) {
      console.error('❌ Erreur vérification disponibilité:', error);
      
      if (availabilityResult) {
        availabilityResult.innerHTML = `
          <div class="availability-status-result error">
            <i class="fas fa-exclamation-triangle"></i>
            <strong>Erreur de communication</strong>
          </div>
          <p>Impossible de vérifier la disponibilité pour le moment.</p>
        `;
      }
    } finally {
      // Réactiver le bouton
      if (btnCheckAvailability) {
        btnCheckAvailability.disabled = false;
        btnCheckAvailability.innerHTML = `
          <i class="fas fa-refresh"></i>
          Vérifier à nouveau
        `;
      }
    }
  }

  // ================================================================
  // ANIMATIONS ET AMÉLIORATIONS UX
  // ================================================================

  // Animation d'apparition pour les cartes
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  };

  const cardObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.animationDelay = Math.random() * 0.3 + 's';
        entry.target.classList.add('animate-in');
      }
    });
  }, observerOptions);

  // Observer toutes les cartes
  document.querySelectorAll('.competence-card, .formation-card, .mission-card, .absence-card').forEach(card => {
    cardObserver.observe(card);
  });

  // ================================================================
  // GESTION DES LIENS ET NAVIGATION
  // ================================================================

  // Smooth scroll pour les liens internes
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    });
  });

  // ================================================================
  // TOOLTIPS ET INFORMATIONS CONTEXTUELLES
  // ================================================================

  // Ajouter des tooltips pour les éléments avec titre
  const elementsWithTooltip = document.querySelectorAll('[title]');
  elementsWithTooltip.forEach(element => {
    // Remplacer le titre par un data-tooltip pour éviter le tooltip natif
    element.dataset.tooltip = element.title;
    element.removeAttribute('title');
    
    // Ajouter les event listeners pour afficher le tooltip personnalisé
    element.addEventListener('mouseenter', showTooltip);
    element.addEventListener('mouseleave', hideTooltip);
  });

  function showTooltip(event) {
    const tooltip = event.target.dataset.tooltip;
    if (!tooltip) return;

    const tooltipElement = document.createElement('div');
    tooltipElement.className = 'custom-tooltip';
    tooltipElement.textContent = tooltip;
    document.body.appendChild(tooltipElement);

    // Positionner le tooltip
    const rect = event.target.getBoundingClientRect();
    tooltipElement.style.left = rect.left + (rect.width / 2) - (tooltipElement.offsetWidth / 2) + 'px';
    tooltipElement.style.top = rect.top - tooltipElement.offsetHeight - 10 + 'px';

    // Stocker la référence pour le nettoyage
    event.target._tooltip = tooltipElement;
  }

  function hideTooltip(event) {
    if (event.target._tooltip) {
      document.body.removeChild(event.target._tooltip);
      delete event.target._tooltip;
    }
  }

  // ================================================================
  // RACCOURCIS CLAVIER
  // ================================================================

  document.addEventListener('keydown', function(event) {
    // Raccourcis uniquement si aucun champ n'est en focus
    if (document.activeElement.tagName === 'INPUT' || 
        document.activeElement.tagName === 'TEXTAREA' || 
        document.activeElement.tagName === 'SELECT') {
      return;
    }

    switch(event.key) {
      case '1':
        switchTab('general');
        break;
      case '2':
        switchTab('competences');
        break;
      case '3':
        switchTab('formations');
        break;
      case '4':
        switchTab('absences');
        break;
      case '5':
        switchTab('missions');
        break;
      case '6':
        switchTab('disponibilite');
        break;
      case 'p':
        if (event.ctrlKey || event.metaKey) {
          event.preventDefault();
          window.print();
        }
        break;
      case 'Escape':
        // Fermer les modales ou revenir en arrière
        if (history.length > 1) {
          history.back();
        }
        break;
    }
  });

  // ================================================================
  // AMÉLIORATION DES FORMULAIRES
  // ================================================================

  // Auto-focus sur les champs de recherche
  const searchInputs = document.querySelectorAll('input[type="search"], .search-input');
  searchInputs.forEach(input => {
    input.addEventListener('focus', function() {
      this.select();
    });
  });

  // ================================================================
  // STATISTIQUES ET MÉTRIQUES
  // ================================================================

  // Animer les compteurs dans les statistiques
  const statValues = document.querySelectorAll('.stat-value');
  const animateCounters = () => {
    statValues.forEach(stat => {
      const value = parseInt(stat.textContent);
      if (isNaN(value)) return;

      let current = 0;
      const increment = value / 30; // Animation sur 30 frames
      const timer = setInterval(() => {
        current += increment;
        if (current >= value) {
          stat.textContent = value;
          clearInterval(timer);
        } else {
          stat.textContent = Math.floor(current);
        }
      }, 16); // ~60fps
    });
  };

  // Observer les statistiques pour déclencher l'animation
  const statsObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        animateCounters();
        statsObserver.unobserve(entry.target);
      }
    });
  });

  const statsGrid = document.querySelector('.stats-grid');
  if (statsGrid) {
    statsObserver.observe(statsGrid);
  }

  // ================================================================
  // FONCTIONNALITÉS AVANCÉES
  // ================================================================

  // Recherche rapide dans les compétences
  function addQuickSearch() {
    const competencesTab = document.getElementById('tab-competences');
    if (!competencesTab) return;

    const searchContainer = document.createElement('div');
    searchContainer.className = 'quick-search-container';
    searchContainer.innerHTML = `
      <input type="text" 
             id="competenceSearch" 
             class="form-input search-input" 
             placeholder="🔍 Rechercher une compétence..." 
             style="margin-bottom: 1rem;">
    `;

    const cardHeader = competencesTab.querySelector('.card-header');
    if (cardHeader) {
      cardHeader.appendChild(searchContainer);
    }

    // Event listener pour la recherche
    const searchInput = document.getElementById('competenceSearch');
    if (searchInput) {
      searchInput.addEventListener('input', function() {
        const searchTerm = this.value.toLowerCase().trim();
        const competenceCards = document.querySelectorAll('.competence-card');
        
        competenceCards.forEach(card => {
          const competenceName = card.querySelector('.competence-name')?.textContent.toLowerCase() || '';
          const competenceDesc = card.querySelector('.competence-description')?.textContent.toLowerCase() || '';
          
          if (competenceName.includes(searchTerm) || competenceDesc.includes(searchTerm) || searchTerm === '') {
            card.style.display = 'block';
          } else {
            card.style.display = 'none';
          }
        });
      });
    }
  }

  // Ajouter la recherche rapide après un délai
  setTimeout(addQuickSearch, 500);

  // ================================================================
  // GESTION D'ERREURS ET FALLBACKS
  // ================================================================

  // Gestion globale des erreurs JavaScript
  window.addEventListener('error', function(event) {
    console.error('❌ Erreur JavaScript:', event.error);
    
    // Optionnel: envoyer l'erreur au serveur pour monitoring
    // sendErrorToServer(event.error);
  });

  // Fallback pour les fonctionnalités non supportées
  if (!window.IntersectionObserver) {
    console.warn('⚠️ IntersectionObserver non supporté, désactivation des animations');
    // Afficher immédiatement tous les éléments
    document.querySelectorAll('.competence-card, .formation-card, .mission-card, .absence-card').forEach(card => {
      card.classList.add('animate-in');
    });
  }

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
    notification.className = `notification notification-${type}`;
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 9999;
      max-width: 350px;
      padding: 1rem;
      border-radius: 4px;
      color: white;
      font-weight: 500;
      box-shadow: 0 4px 8px rgba(0,0,0,0.2);
      animation: slideInRight 0.3s ease;
    `;
    
    // Couleurs selon le type
    const colors = {
      success: '#28a745',
      error: '#dc3545',
      warning: '#ffc107',
      info: '#17a2b8'
    };
    
    notification.style.backgroundColor = colors[type] || colors.info;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Retirer après 4 secondes
    setTimeout(() => {
      if (notification.parentNode) {
        notification.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => {
          if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
          }
        }, 300);
      }
    }, 4000);
  }

  // ================================================================
  // INITIALISATION FINALE
  // ================================================================

  console.log('✅ Page détail employé initialisée avec succès');
  console.log('📌 Raccourcis clavier disponibles:');
  console.log('   • 1-6: Changer d\'onglet');
  console.log('   • Ctrl+P: Imprimer');
  console.log('   • Échap: Retour');
  
  // Marquer la page comme chargée
  document.body.classList.add('page-loaded');
});

// ================================================================
// STYLES D'ANIMATION POUR LES NOTIFICATIONS
// ================================================================

const animationStyles = document.createElement('style');
animationStyles.textContent = `
  @keyframes slideInRight {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  
  @keyframes slideOutRight {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
  }
  
  @keyframes animate-in {
    from { 
      opacity: 0; 
      transform: translateY(20px); 
    }
    to { 
      opacity: 1; 
      transform: translateY(0); 
    }
  }
  
  .animate-in {
    animation: animate-in 0.6s ease forwards;
  }
  
  .custom-tooltip {
    position: absolute;
    background: #333;
    color: white;
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    font-size: 0.875rem;
    z-index: 9999;
    pointer-events: none;
    opacity: 0.9;
    max-width: 200px;
    word-wrap: break-word;
  }
  
  .custom-tooltip::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    margin-left: -5px;
    border-width: 5px;
    border-style: solid;
    border-color: #333 transparent transparent transparent;
  }
  
  .availability-status-result {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.1rem;
    margin-bottom: 1rem;
  }
  
  .availability-status-result.available {
    color: var(--success);
  }
  
  .availability-status-result.unavailable {
    color: var(--danger);
  }
  
  .availability-status-result.error {
    color: var(--warning);
  }
  
  .no-results-message {
    grid-column: 1 / -1;
    text-align: center;
    padding: 2rem;
    color: #6c757d;
  }
  
  .quick-search-container {
    margin-left: auto;
  }
  
  .search-input {
    min-width: 250px;
  }
  
  @media (max-width: 768px) {
    .quick-search-container {
      margin-left: 0;
      margin-top: 1rem;
      width: 100%;
    }
    
    .search-input {
      min-width: auto;
      width: 100%;
    }
  }
`;

document.head.appendChild(animationStyles);

