
document.addEventListener('DOMContentLoaded', function() {
  console.log('🏢 Initialisation de la page hiérarchie organisationnelle');
  
  // Animation d'entrée progressive pour les niveaux
  const hierarchyLevels = document.querySelectorAll('.hierarchy-level');
  hierarchyLevels.forEach((level, index) => {
    level.style.opacity = '0';
    level.style.transform = 'translateY(30px)';
    
    setTimeout(() => {
      level.style.transition = 'all 0.6s ease';
      level.style.opacity = '1';
      level.style.transform = 'translateY(0)';
    }, index * 150);
  });
  
  // Animation des statistiques
  animerStatistiques();
  
  // Gestion des liens de navigation
  setupNavigationLinks();
  
  console.log('✅ Page hiérarchie initialisée avec succès');
});

function animerStatistiques() {
  const statNumbers = document.querySelectorAll('.stat-number');
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const element = entry.target;
        const finalValue = parseInt(element.textContent) || 0;
        
        if (finalValue > 0) {
          animerCompteur(element, finalValue);
        }
        
        observer.unobserve(element);
      }
    });
  }, { threshold: 0.5 });
  
  statNumbers.forEach(number => observer.observe(number));
}

function animerCompteur(element, finalValue) {
  let currentValue = 0;
  const increment = Math.ceil(finalValue / 20);
  
  const timer = setInterval(() => {
    currentValue += increment;
    if (currentValue >= finalValue) {
      currentValue = finalValue;
      clearInterval(timer);
    }
    
    element.textContent = currentValue;
  }, 50);
}

function setupNavigationLinks() {
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
  
  // Préchargement des liens de hiérarchie
  const hierarchyLinks = document.querySelectorAll('a[href*="hierarchie"]');
  hierarchyLinks.forEach(link => {
    link.addEventListener('mouseenter', function() {
      // Précharger la page de destination
      const prefetchLink = document.createElement('link');
      prefetchLink.rel = 'prefetch';
      prefetchLink.href = this.href;
      document.head.appendChild(prefetchLink);
    });
  });
}

function exporterHierarchie() {
  console.log('📁 Export de la hiérarchie organisationnelle');
  
  // Afficher un indicateur de chargement
  const btn = event.target.closest('.action-btn');
  const originalContent = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Génération...</span>';
  btn.disabled = true;
  
  // Simulation de l'export (à remplacer par l'appel réel)
  setTimeout(() => {
    // Restaurer le bouton
    btn.innerHTML = originalContent;
    btn.disabled = false;
    
    // Afficher une notification de succès
    afficherNotification('Organigramme exporté avec succès !', 'success');
  }, 2000);
}

function imprimerHierarchie() {
  console.log('🖨️ Impression de la hiérarchie');
  
  // Masquer les éléments non nécessaires à l'impression
  const elementsToHide = document.querySelectorAll('.btn, .admin-actions, .card-header .count-badge');
  elementsToHide.forEach(el => {
    el.style.display = 'none';
  });
  
  // Lancer l'impression
  window.print();
  
  // Restaurer les éléments après impression
  setTimeout(() => {
    elementsToHide.forEach(el => {
      el.style.display = '';
    });
  }, 1000);
}

function afficherOrganigrammeComplet() {
  console.log('🗂️ Affichage de l\'organigramme complet');
  
  // Créer une modal pour l'organigramme complet
  const modal = document.createElement('div');
  modal.className = 'organigramme-modal';
  modal.innerHTML = `
    <div class="organigramme-modal-content">
      <div class="organigramme-modal-header">
        <h3>Organigramme complet du département</h3>
        <button onclick="fermerOrganigrammeModal()" class="btn-close">&times;</button>
      </div>
      <div class="organigramme-modal-body">
        <div class="organigramme-placeholder">
          <i class="fas fa-sitemap" style="font-size: 4rem; opacity: 0.3;"></i>
          <h4>Organigramme interactif</h4>
          <p>L'organigramme complet sera affiché ici dans une prochaine version.</p>
          <p>Cette fonctionnalité permettra de visualiser l'ensemble de la structure organisationnelle.</p>
        </div>
      </div>
    </div>
  `;
  
  // Styles de la modal
  modal.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    animation: fadeIn 0.3s ease;
  `;
  
  const content = modal.querySelector('.organigramme-modal-content');
  content.style.cssText = `
    background: white;
    border-radius: 8px;
    max-width: 80%;
    max-height: 80%;
    width: 800px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    overflow: hidden;
  `;
  
  const header = modal.querySelector('.organigramme-modal-header');
  header.style.cssText = `
    padding: 1.5rem;
    border-bottom: 1px solid #dee2e6;
    display: flex;
    justify-content: space-between;
    align-items: center;
  `;
  
  const body = modal.querySelector('.organigramme-modal-body');
  body.style.cssText = `
    padding: 2rem;
    text-align: center;
    color: #6c757d;
  `;
  
  const closeBtn = modal.querySelector('.btn-close');
  closeBtn.style.cssText = `
    background: none;
    border: none;
    font-size: 1.5rem;
    cursor: pointer;
    color: #6c757d;
  `;
  
  document.body.appendChild(modal);
  
  // Fermer en cliquant sur le fond
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      fermerOrganigrammeModal();
    }
  });
}

function fermerOrganigrammeModal() {
  const modal = document.querySelector('.organigramme-modal');
  if (modal) {
    modal.style.animation = 'fadeOut 0.3s ease';
    setTimeout(() => modal.remove(), 300);
  }
}

function afficherNotification(message, type = 'info') {
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
    success: '#27ae60',
    error: '#e74c3c',
    warning: '#f39c12',
    info: '#3498db'
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

// Gestion des raccourcis clavier
document.addEventListener('keydown', function(event) {
  // Raccourcis uniquement si aucun champ n'est en focus
  if (document.activeElement.tagName === 'INPUT' || 
      document.activeElement.tagName === 'TEXTAREA' || 
      document.activeElement.tagName === 'SELECT') {
    return;
  }

  switch(event.key) {
    case 'e':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        exporterHierarchie();
      }
      break;
    case 'p':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        imprimerHierarchie();
      }
      break;
    case 'o':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        afficherOrganigrammeComplet();
      }
      break;
    case 'Escape':
      fermerOrganigrammeModal();
      break;
  }
});

// Gestion du hover pour les cartes d'employé
document.querySelectorAll('.employee-card').forEach(card => {
  card.addEventListener('mouseenter', function() {
    // Ajouter un effet de focus aux connecteurs
    const level = this.closest('.hierarchy-level');
    const connector = level.querySelector('.hierarchy-connector');
    if (connector) {
      connector.style.opacity = '1';
      connector.style.transform = 'scale(1.1)';
    }
  });
  
  card.addEventListener('mouseleave', function() {
    // Restaurer l'état normal des connecteurs
    const level = this.closest('.hierarchy-level');
    const connector = level.querySelector('.hierarchy-connector');
    if (connector) {
      connector.style.opacity = '';
      connector.style.transform = '';
    }
  });
});

// Tooltip pour les badges de niveau
document.querySelectorAll('.level-badge').forEach(badge => {
  badge.addEventListener('mouseenter', function() {
    const level = this.textContent.match(/\d+/)?.[0];
    const descriptions = {
      '1': 'Niveau opérationnel - Exécution des tâches',
      '2': 'Encadrement de proximité - Management direct',
      '3': 'Management intermédiaire - Coordination',
      '4': 'Direction opérationnelle - Stratégie métier',
      '5': 'Direction générale - Vision globale'
    };
    
    if (level && descriptions[level]) {
      this.title = descriptions[level];
    }
  });
});

// Amélioration de l'accessibilité
function ameliorerAccessibilite() {
  // Ajouter des attributs ARIA
  document.querySelectorAll('.employee-card').forEach((card, index) => {
    card.setAttribute('role', 'article');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-label', `Employé niveau hiérarchique ${index + 1}`);
  });
  
  // Navigation au clavier dans la hiérarchie
  document.querySelectorAll('.employee-card').forEach((card, index, cards) => {
    card.addEventListener('keydown', function(e) {
      switch(e.key) {
        case 'ArrowUp':
          e.preventDefault();
          if (index > 0) {
            cards[index - 1].focus();
          }
          break;
        case 'ArrowDown':
          e.preventDefault();
          if (index < cards.length - 1) {
            cards[index + 1].focus();
          }
          break;
        case 'Enter':
        case ' ':
          e.preventDefault();
          const link = this.querySelector('.employee-name a');
          if (link) {
            link.click();
          }
          break;
      }
    });
  });
}

// Performance - Lazy loading pour les images d'avatar
function setupLazyLoading() {
  if ('IntersectionObserver' in window) {
    const avatarObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const avatar = entry.target;
          // Ici on pourrait charger une vraie photo si disponible
          avatar.classList.add('loaded');
          avatarObserver.unobserve(avatar);
        }
      });
    });
    
    document.querySelectorAll('.employee-avatar').forEach(avatar => {
      avatarObserver.observe(avatar);
    });
  }
}

// Fonction pour détecter et signaler les boucles dans la hiérarchie
function detecterBouclesHierarchie() {
  const employeeCards = document.querySelectorAll('.employee-card');
  const matricules = new Set();
  let boucleDetectee = false;
  
  employeeCards.forEach(card => {
    const links = card.querySelectorAll('a[href*="employe"]');
    links.forEach(link => {
      const href = link.getAttribute('href');
      const matricule = href.split('/').pop().replace('/', '');
      
      if (matricules.has(matricule)) {
        console.warn('⚠️ Boucle hiérarchique détectée pour le matricule:', matricule);
        boucleDetectee = true;
        
        // Marquer visuellement la boucle
        card.style.border = '2px dashed #e74c3c';
        card.title = 'Attention: Boucle hiérarchique détectée';
      } else {
        matricules.add(matricule);
      }
    });
  });
  
  if (boucleDetectee) {
    afficherNotification('Attention: Des boucles hiérarchiques ont été détectées', 'warning');
  }
}

// Fonction pour analyser la structure hiérarchique
function analyserStructureHierarchie() {
  const levels = document.querySelectorAll('.hierarchy-level');
  const stats = {
    niveaux: levels.length,
    employesParNiveau: {},
    porteeControle: [],
    profondeurMax: levels.length
  };
  
  levels.forEach((level, index) => {
    const equipeCount = level.querySelector('.employee-stats .stat-value')?.textContent || '0';
    stats.employesParNiveau[`niveau_${index + 1}`] = parseInt(equipeCount);
    
    if (parseInt(equipeCount) > 0) {
      stats.porteeControle.push(parseInt(equipeCount));
    }
  });
  
  // Calculer la portée de contrôle moyenne
  if (stats.porteeControle.length > 0) {
    stats.porteeControleMoyenne = stats.porteeControle.reduce((a, b) => a + b, 0) / stats.porteeControle.length;
  }
  
  console.log('📊 Analyse de la structure hiérarchique:', stats);
  return stats;
}

// Fonction pour optimiser l'affichage selon la taille de la hiérarchie
function optimiserAffichage() {
  const levels = document.querySelectorAll('.hierarchy-level');
  
  // Si trop de niveaux, ajuster l'espacement
  if (levels.length > 6) {
    levels.forEach(level => {
      level.style.marginBottom = '2rem';
    });
    
    // Réduire la taille des cartes
    document.querySelectorAll('.employee-card').forEach(card => {
      card.style.maxWidth = '400px';
      card.style.padding = '1.5rem';
    });
    
    console.log('🎨 Optimisation de l\'affichage pour', levels.length, 'niveaux');
  }
}

// Fonction pour exporter les données hiérarchiques
function exporterDonneesHierarchie() {
  const hierarchieData = {
    timestamp: new Date().toISOString(),
    employe_base: {
      matricule: '{{ employe.matricule }}',
      nom: '{{ employe.nom_complet }}',
      type_profil: '{{ employe.type_profil }}'
    },
    chaine_hierarchique: [],
    statistiques: analyserStructureHierarchie()
  };
  
  // Collecter les données de chaque niveau
  document.querySelectorAll('.hierarchy-level').forEach((level, index) => {
    const card = level.querySelector('.employee-card');
    const nom = card.querySelector('.employee-name a')?.textContent.trim();
    const matricule = card.querySelector('.detail-item')?.textContent.trim();
    const typeProfile = card.querySelector('.detail-item:nth-child(2)')?.textContent.trim();
    
    hierarchieData.chaine_hierarchique.push({
      niveau: index + 1,
      nom: nom,
      matricule: matricule,
      type_profil: typeProfile,
      est_employe_base: level.classList.contains('current-employee')
    });
  });
  
  return hierarchieData;
}

// Initialisation des fonctionnalités avancées
setTimeout(() => {
  ameliorerAccessibilite();
  setupLazyLoading();
  detecterBouclesHierarchie();
  optimiserAffichage();
}, 1000);

// Ajout des styles d'animation manquants
const animationStyles = document.createElement('style');
animationStyles.textContent = `
  @keyframes fadeIn {
    from { opacity: 0; transform: scale(0.9); }
    to { opacity: 1; transform: scale(1); }
  }
  
  @keyframes fadeOut {
    from { opacity: 1; transform: scale(1); }
    to { opacity: 0; transform: scale(0.9); }
  }
  
  @keyframes slideInRight {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  
  @keyframes slideOutRight {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
  }
  
  .employee-avatar.loaded {
    transform: scale(1.05);
    transition: transform 0.3s ease;
  }
  
  .hierarchy-connector {
    transition: all 0.3s ease;
  }
  
  .employee-card:focus {
    outline: 2px solid var(--hierarchy-secondary);
    outline-offset: 2px;
  }
  
  .organigramme-placeholder {
    padding: 3rem 2rem;
    text-align: center;
    color: #6c757d;
  }
  
  .organigramme-placeholder i {
    margin-bottom: 1rem;
    display: block;
  }
  
  .organigramme-placeholder h4 {
    margin-bottom: 1rem;
    color: #495057;
  }
`;

document.head.appendChild(animationStyles);

console.log('🎯 Fonctionnalités avancées de la hiérarchie initialisées');
console.log('📌 Raccourcis clavier disponibles:');
console.log('   • Ctrl+E: Exporter');
console.log('   • Ctrl+P: Imprimer');
console.log('   • Ctrl+O: Organigramme complet');
console.log('   • Flèches: Navigation dans la hiérarchie');
console.log('   • Échap: Fermer les modales');

