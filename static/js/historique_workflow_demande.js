
document.addEventListener('DOMContentLoaded', function() {
  console.log('🚀 Interface historique workflow initialisée');

  // ================================================================
  // VARIABLES GLOBALES
  // ================================================================
  
  const timelineItems = document.querySelectorAll('.timeline-item');
  const filterCheckboxes = document.querySelectorAll('#filtresTimeline input[type="checkbox"]');
  const periodeButtons = document.querySelectorAll('.periode-buttons .btn');

  // ================================================================
  // FONCTIONS DE FILTRAGE
  // ================================================================
  
  function filtrerTimeline() {
    const filtresActifs = {
      actions: document.getElementById('filter-actions').checked,
      validations: document.getElementById('filter-validations').checked,
      propositions: document.getElementById('filter-propositions').checked,
      notifications: document.getElementById('filter-notifications').checked
    };
    
    console.log('Filtres actifs:', filtresActifs);
    
    timelineItems.forEach(item => {
      const type = item.dataset.type;
      let afficher = false;
      
      switch(type) {
        case 'action':
          afficher = filtresActifs.actions;
          break;
        case 'validation':
          afficher = filtresActifs.validations;
          break;
        case 'proposition':
        case 'evaluation':
          afficher = filtresActifs.propositions;
          break;
        case 'notification':
          afficher = filtresActifs.notifications;
          break;
        default:
          afficher = true;
      }
      
      if (afficher) {
        item.classList.remove('hidden');
        item.style.display = 'block';
      } else {
        item.classList.add('hidden');
        item.style.display = 'none';
      }
    });
    
    // Mettre à jour les compteurs
    mettreAJourCompteurs();
  }

  window.filtrerPeriode = function(periode) {
    console.log('Filtre période:', periode);
    
    // Mettre à jour les boutons actifs
    periodeButtons.forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    
    const maintenant = new Date();
    let dateDebut;
    
    switch(periode) {
      case 'today':
        dateDebut = new Date(maintenant.getFullYear(), maintenant.getMonth(), maintenant.getDate());
        break;
      case 'week':
        dateDebut = new Date(maintenant.getTime() - 7 * 24 * 60 * 60 * 1000);
        break;
      case 'month':
        dateDebut = new Date(maintenant.getFullYear(), maintenant.getMonth(), 1);
        break;
      default:
        dateDebut = null;
    }
    
    timelineItems.forEach(item => {
      if (periode === 'all') {
        item.style.display = 'block';
        return;
      }
      
      const itemDate = new Date(item.dataset.timestamp);
      if (itemDate >= dateDebut) {
        item.style.display = 'block';
      } else {
        item.style.display = 'none';
      }
    });
    
    // Réappliquer les filtres de type
    setTimeout(filtrerTimeline, 100);
  };

  function mettreAJourCompteurs() {
    const compteurs = {
      actions: 0,
      validations: 0,
      propositions: 0,
      notifications: 0
    };
    
    timelineItems.forEach(item => {
      if (item.style.display !== 'none') {
        const type = item.dataset.type;
        switch(type) {
          case 'action':
            compteurs.actions++;
            break;
          case 'validation':
            compteurs.validations++;
            break;
          case 'proposition':
          case 'evaluation':
            compteurs.propositions++;
            break;
          case 'notification':
            compteurs.notifications++;
            break;
        }
      }
    });
    
    // Mettre à jour les labels des filtres
    const labels = {
      'filter-actions': `Actions (${compteurs.actions})`,
      'filter-validations': `Validations (${compteurs.validations})`,
      'filter-propositions': `Propositions (${compteurs.propositions})`,
      'filter-notifications': `Notifications (${compteurs.notifications})`
    };
    
    Object.entries(labels).forEach(([id, text]) => {
      const label = document.querySelector(`label[for="${id}"]`);
      if (label) {
        const icon = label.querySelector('i');
        const iconHtml = icon ? icon.outerHTML : '';
        label.innerHTML = `<input type="checkbox" id="${id}" ${document.getElementById(id).checked ? 'checked' : ''}><span class="checkmark"></span>${iconHtml} ${text}`;
      }
    });
  }

  // ================================================================
  // FONCTIONS D'EXPORT ET IMPRESSION
  // ================================================================
  
  window.exporterHistorique = function() {
    console.log('Export historique');
    showLoading();
    
    // Préparer les données pour l'export
    const donneesExport = {
      demande: {
        numero: '{{ demande.numero_demande }}',
        statut: '{{ demande.statut }}',
        poste: '{{ demande.poste.titre }}',
        demandeur: '{{ demande.demandeur.nom_complet }}',
        date_creation: '{{ demande.created_at|date:"d/m/Y H:i" }}'
      },
      timeline: []
    };
    
    // Collecter les éléments visibles de la timeline
    timelineItems.forEach(item => {
      if (item.style.display !== 'none') {
        const titre = item.querySelector('.timeline-title').textContent;
        const description = item.querySelector('.timeline-description').textContent;
        const date = item.querySelector('.timeline-date').textContent;
        const utilisateur = item.querySelector('.timeline-user').textContent;
        
        donneesExport.timeline.push({
          type: item.dataset.type,
          titre: titre.trim(),
          description: description.trim(),
          date: date.trim(),
          utilisateur: utilisateur.trim()
        });
      }
    });
    
    // Simulation de l'export (à remplacer par un vrai appel API)
    setTimeout(() => {
      hideLoading();
      
      // Créer un fichier JSON pour téléchargement
      const dataStr = JSON.stringify(donneesExport, null, 2);
      const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
      
      const exportFileDefaultName = `historique_${donneesExport.demande.numero}_${new Date().toISOString().slice(0,10)}.json`;
      
      const linkElement = document.createElement('a');
      linkElement.setAttribute('href', dataUri);
      linkElement.setAttribute('download', exportFileDefaultName);
      linkElement.click();
      
      showToast('Succès', 'Historique exporté avec succès', 'success');
    }, 2000);
  };

  window.imprimerHistorique = function() {
    console.log('Impression historique');
    
    // Créer une nouvelle fenêtre pour l'impression
    const printWindow = window.open('', '_blank');
    const printContent = `
      <!DOCTYPE html>
      <html>
      <head>
        <title>Historique Workflow - {{ demande.numero_demande }}</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 20px; }
          .header { border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 20px; }
          .timeline-item { margin-bottom: 15px; padding: 10px; border-left: 3px solid #007bff; }
          .timeline-title { font-weight: bold; margin-bottom: 5px; }
          .timeline-meta { font-size: 12px; color: #666; margin-bottom: 5px; }
          .timeline-description { margin-bottom: 10px; }
          .page-break { page-break-before: always; }
          @media print { .no-print { display: none; } }
        </style>
      </head>
      <body>
        <div class="header">
          <h1>Historique du Workflow</h1>
          <p><strong>Demande:</strong> {{ demande.numero_demande }}</p>
          <p><strong>Poste:</strong> {{ demande.poste.titre }}</p>
          <p><strong>Statut:</strong> {{ demande.get_statut_display }}</p>
          <p><strong>Date d'impression:</strong> ${new Date().toLocaleDateString('fr-FR')}</p>
        </div>
        
        <div class="timeline">
          ${Array.from(timelineItems).filter(item => item.style.display !== 'none').map(item => {
            const titre = item.querySelector('.timeline-title').textContent;
            const description = item.querySelector('.timeline-description').textContent;
            const date = item.querySelector('.timeline-date').textContent;
            const utilisateur = item.querySelector('.timeline-user').textContent;
            
            return `
              <div class="timeline-item">
                <div class="timeline-title">${titre}</div>
                <div class="timeline-meta">${utilisateur} - ${date}</div>
                <div class="timeline-description">${description}</div>
              </div>
            `;
          }).join('')}
        </div>
      </body>
      </html>
    `;
    
    printWindow.document.write(printContent);
    printWindow.document.close();
    
    setTimeout(() => {
      printWindow.print();
      printWindow.close();
    }, 500);
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
  }

  // ================================================================
  // INITIALISATION DES EVENT LISTENERS
  // ================================================================

  // Event listeners pour les filtres
  filterCheckboxes.forEach(checkbox => {
    checkbox.addEventListener('change', filtrerTimeline);
  });

  // Raccourcis clavier
  document.addEventListener('keydown', function(e) {
    // Ctrl+P : Imprimer
    if (e.ctrlKey && e.key === 'p') {
      e.preventDefault();
      imprimerHistorique();
    }
    
    // Ctrl+E : Exporter
    if (e.ctrlKey && e.key === 'e') {
      e.preventDefault();
      if (typeof exporterHistorique === 'function') {
        exporterHistorique();
      }
    }
    
    // Escape : Fermer les modales
    if (e.key === 'Escape') {
      const modals = document.querySelectorAll('.modal.show');
      modals.forEach(modal => {
        const modalInstance = bootstrap.Modal.getInstance(modal);
        if (modalInstance) {
          modalInstance.hide();
        }
      });
    }
  });

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

  // Animation d'entrée pour les éléments de timeline
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateX(0)';
      }
    });
  }, {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  });

  timelineItems.forEach(item => {
    item.style.opacity = '0';
    item.style.transform = 'translateX(-20px)';
    item.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
    observer.observe(item);
  });

  // Tooltips Bootstrap
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[title]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });

  // Auto-scroll vers l'élément le plus récent
  if (timelineItems.length > 0) {
    const premierElement = timelineItems[0];
    setTimeout(() => {
      premierElement.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
      });
    }, 1000);
  }

  // Initialisation des compteurs
  mettreAJourCompteurs();

  console.log('✅ Interface historique workflow prête');
  console.log(`📊 ${timelineItems.length} éléments dans la timeline`);
});

// ================================================================
// FONCTIONS GLOBALES POUR COMPATIBILITÉ
// ================================================================

window.showLoading = function() {
  document.getElementById('loadingOverlay').style.display = 'flex';
};

window.hideLoading = function() {
  document.getElementById('loadingOverlay').style.display = 'none';
};

window.showToast = function(titre, message, type = 'info') {
  // Fonction définie dans le DOMContentLoaded
  const toastContainer = document.querySelector('.toast-container');
  if (toastContainer) {
    // Réutiliser la logique de showToast
    const event = new CustomEvent('showToast', {
      detail: { titre, message, type }
    });
    document.dispatchEvent(event);
  }
};

// Gestion des erreurs globales
window.addEventListener('error', function(e) {
  console.error('Erreur JavaScript:', e.error);
  if (typeof showToast === 'function') {
    showToast('Erreur', 'Une erreur inattendue s\'est produite', 'error');
  }
});

// Fonction de recherche dans la timeline
window.rechercherDansTimeline = function(terme) {
  console.log('Recherche dans timeline:', terme);
  
  if (!terme || terme.length < 2) {
    // Réafficher tous les éléments
    timelineItems.forEach(item => {
      item.style.display = 'block';
      item.classList.remove('search-highlight');
    });
    return;
  }
  
  terme = terme.toLowerCase();
  let resultatsAffiches = 0;
  
  timelineItems.forEach(item => {
    const titre = item.querySelector('.timeline-title').textContent.toLowerCase();
    const description = item.querySelector('.timeline-description').textContent.toLowerCase();
    const utilisateur = item.querySelector('.timeline-user').textContent.toLowerCase();
    
    if (titre.includes(terme) || description.includes(terme) || utilisateur.includes(terme)) {
      item.style.display = 'block';
      item.classList.add('search-highlight');
      resultatsAffiches++;
    } else {
      item.style.display = 'none';
      item.classList.remove('search-highlight');
    }
  });
  
  // Afficher un message si aucun résultat
  const messageRecherche = document.getElementById('messageRecherche');
  if (messageRecherche) {
    if (resultatsAffiches === 0) {
      messageRecherche.textContent = `Aucun résultat trouvé pour "${terme}"`;
      messageRecherche.style.display = 'block';
    } else {
      messageRecherche.textContent = `${resultatsAffiches} résultat(s) trouvé(s)`;
      messageRecherche.style.display = 'block';
    }
  }
};

// Fonction de zoom sur la timeline
window.zoomTimeline = function(action) {
  const timeline = document.querySelector('.timeline-container');
  if (!timeline) return;
  
  const currentFontSize = parseInt(window.getComputedStyle(timeline).fontSize);
  let newFontSize;
  
  switch(action) {
    case 'in':
      newFontSize = Math.min(currentFontSize + 2, 24);
      break;
    case 'out':
      newFontSize = Math.max(currentFontSize - 2, 12);
      break;
    case 'reset':
      newFontSize = 16;
      break;
    default:
      return;
  }
  
  timeline.style.fontSize = newFontSize + 'px';
  console.log('Zoom timeline:', action, 'nouvelle taille:', newFontSize);
};

// Fonction de navigation dans la timeline
window.naviguerTimeline = function(direction) {
  const itemsVisibles = Array.from(timelineItems).filter(item => item.style.display !== 'none');
  if (itemsVisibles.length === 0) return;
  
  const itemActuel = document.querySelector('.timeline-item.current');
  let index = 0;
  
  if (itemActuel) {
    index = itemsVisibles.indexOf(itemActuel);
    itemActuel.classList.remove('current');
  }
  
  if (direction === 'next') {
    index = (index + 1) % itemsVisibles.length;
  } else if (direction === 'prev') {
    index = index > 0 ? index - 1 : itemsVisibles.length - 1;
  } else if (direction === 'first') {
    index = 0;
  } else if (direction === 'last') {
    index = itemsVisibles.length - 1;
  }
  
  const nouvelItem = itemsVisibles[index];
  nouvelItem.classList.add('current');
  nouvelItem.scrollIntoView({
    behavior: 'smooth',
    block: 'center'
  });
  
  console.log('Navigation timeline:', direction, 'item', index + 1, 'sur', itemsVisibles.length);
};

// Fonction de copie de lien vers un élément spécifique
window.copierLienElement = function(elementId) {
  const url = window.location.href.split('#')[0] + '#' + elementId;
  
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(() => {
      showToast('Succès', 'Lien copié dans le presse-papiers', 'success');
    }).catch(() => {
      // Fallback pour les navigateurs plus anciens
      copierTexteDepuisFallback(url);
    });
  } else {
    copierTexteDepuisFallback(url);
  }
};

function copierTexteDepuisFallback(text) {
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.top = '-1000px';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  
  try {
    document.execCommand('copy');
    showToast('Succès', 'Lien copié dans le presse-papiers', 'success');
  } catch (err) {
    showToast('Erreur', 'Impossible de copier le lien', 'error');
  } finally {
    document.body.removeChild(textArea);
  }
}

// Fonction de comparaison de versions
window.comparerVersions = function(elementId1, elementId2) {
  const element1 = document.getElementById(elementId1);
  const element2 = document.getElementById(elementId2);
  
  if (!element1 || !element2) {
    showToast('Erreur', 'Éléments non trouvés pour la comparaison', 'error');
    return;
  }
  
  // Créer une modal de comparaison
  const modalHtml = `
    <div class="modal fade" id="modalComparaison" tabindex="-1">
      <div class="modal-dialog modal-xl">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="fas fa-exchange-alt"></i>
              Comparaison d'éléments
            </h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row">
              <div class="col-md-6">
                <h6>Élément 1</h6>
                <div class="comparaison-element">
                  ${element1.outerHTML}
                </div>
              </div>
              <div class="col-md-6">
                <h6>Élément 2</h6>
                <div class="comparaison-element">
                  ${element2.outerHTML}
                </div>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-outline" data-bs-dismiss="modal">Fermer</button>
          </div>
        </div>
      </div>
    </div>
  `;
  
  // Supprimer l'ancienne modal si elle existe
  const ancienneModal = document.getElementById('modalComparaison');
  if (ancienneModal) {
    ancienneModal.remove();
  }
  
  // Ajouter la nouvelle modal
  document.body.insertAdjacentHTML('beforeend', modalHtml);
  
  // Afficher la modal
  const modal = new bootstrap.Modal(document.getElementById('modalComparaison'));
  modal.show();
  
  console.log('Comparaison lancée entre', elementId1, 'et', elementId2);
};

// Fonctions d'accessibilité
window.toggleContrasteFort = function() {
  document.body.classList.toggle('contraste-fort');
  const etat = document.body.classList.contains('contraste-fort');
  localStorage.setItem('contraste_fort', etat);
  showToast('Accessibilité', `Contraste fort ${etat ? 'activé' : 'désactivé'}`, 'info');
};

window.toggleGrosseTaille = function() {
  document.body.classList.toggle('grosse-taille');
  const etat = document.body.classList.contains('grosse-taille');
  localStorage.setItem('grosse_taille', etat);
  showToast('Accessibilité', `Grosse taille ${etat ? 'activée' : 'désactivée'}`, 'info');
};

// Fonction de lecture automatique (Text-to-Speech)
window.lireElement = function(elementId) {
  if (!('speechSynthesis' in window)) {
    showToast('Erreur', 'La synthèse vocale n\'est pas supportée par votre navigateur', 'error');
    return;
  }
  
  const element = document.getElementById(elementId);
  if (!element) {
    showToast('Erreur', 'Élément non trouvé', 'error');
    return;
  }
  
  // Arrêter toute lecture en cours
  speechSynthesis.cancel();
  
  // Extraire le texte à lire
  const titre = element.querySelector('.timeline-title')?.textContent || '';
  const description = element.querySelector('.timeline-description')?.textContent || '';
  const utilisateur = element.querySelector('.timeline-user')?.textContent || '';
  const date = element.querySelector('.timeline-date')?.textContent || '';
  
  const texteALire = `${titre}. ${description}. Par ${utilisateur}, ${date}.`;
  
  const utterance = new SpeechSynthesisUtterance(texteALire);
  utterance.lang = 'fr-FR';
  utterance.rate = 0.8;
  utterance.pitch = 1;
  
  utterance.onstart = function() {
    element.classList.add('en-lecture');
    showToast('Lecture', 'Lecture en cours...', 'info');
  };
  
  utterance.onend = function() {
    element.classList.remove('en-lecture');
  };
  
  utterance.onerror = function(event) {
    element.classList.remove('en-lecture');
    showToast('Erreur', 'Erreur lors de la lecture', 'error');
  };
  
  speechSynthesis.speak(utterance);
  console.log('Lecture audio démarrée pour:', elementId);
};

// Fonction d'analyse de performance
window.analyserPerformanceWorkflow = function() {
  console.log('Analyse de performance du workflow');
  
  const elements = Array.from(timelineItems).filter(item => item.style.display !== 'none');
  if (elements.length === 0) {
    showToast('Info', 'Aucun élément à analyser', 'info');
    return;
  }
  
  // Analyser les délais entre les étapes
  const analyse = {
    duree_totale: 0,
    nb_etapes: elements.length,
    etapes_par_type: {},
    delais_moyens: {},
    goulots_etranglement: []
  };
  
  elements.forEach((element, index) => {
    const type = element.dataset.type;
    analyse.etapes_par_type[type] = (analyse.etapes_par_type[type] || 0) + 1;
    
    if (index > 0) {
      const dateActuelle = new Date(element.dataset.timestamp);
      const datePrecedente = new Date(elements[index - 1].dataset.timestamp);
      const delai = dateActuelle - datePrecedente;
      
      if (!analyse.delais_moyens[type]) {
        analyse.delais_moyens[type] = [];
      }
      analyse.delais_moyens[type].push(delai);
      
      // Identifier les goulots (délai > 2 jours)
      if (delai > 2 * 24 * 60 * 60 * 1000) {
        analyse.goulots_etranglement.push({
          etape: element.querySelector('.timeline-title').textContent,
          delai_jours: Math.round(delai / (24 * 60 * 60 * 1000)),
          type: type
        });
      }
    }
  });
  
  // Calculer les moyennes
  Object.keys(analyse.delais_moyens).forEach(type => {
    const delais = analyse.delais_moyens[type];
    const moyenne = delais.reduce((a, b) => a + b, 0) / delais.length;
    analyse.delais_moyens[type] = Math.round(moyenne / (60 * 60 * 1000)); // en heures
  });
  
  // Durée totale
  if (elements.length > 1) {
    const debut = new Date(elements[elements.length - 1].dataset.timestamp);
    const fin = new Date(elements[0].dataset.timestamp);
    analyse.duree_totale = Math.round((fin - debut) / (24 * 60 * 60 * 1000)); // en jours
  }
  
  // Afficher les résultats
  const modalAnalyse = `
    <div class="modal fade" id="modalAnalysePerformance" tabindex="-1">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header bg-info text-white">
            <h5 class="modal-title">
              <i class="fas fa-chart-line"></i>
              Analyse de performance du workflow
            </h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="row">
              <div class="col-md-6">
                <h6>Statistiques générales</h6>
                <ul class="list-unstyled">
                  <li><strong>Durée totale:</strong> ${analyse.duree_totale} jour(s)</li>
                  <li><strong>Nombre d'étapes:</strong> ${analyse.nb_etapes}</li>
                  <li><strong>Goulots identifiés:</strong> ${analyse.goulots_etranglement.length}</li>
                </ul>
                
                <h6>Répartition par type</h6>
                <ul class="list-unstyled">
                  ${Object.entries(analyse.etapes_par_type).map(([type, count]) => 
                    `<li><strong>${type}:</strong> ${count}</li>`
                  ).join('')}
                </ul>
              </div>
              <div class="col-md-6">
                <h6>Délais moyens (heures)</h6>
                <ul class="list-unstyled">
                  ${Object.entries(analyse.delais_moyens).map(([type, delai]) => 
                    `<li><strong>${type}:</strong> ${delai}h</li>`
                  ).join('')}
                </ul>
                
                ${analyse.goulots_etranglement.length > 0 ? `
                <h6>Goulots d'étranglement</h6>
                <ul class="list-unstyled">
                  ${analyse.goulots_etranglement.map(goulot => 
                    `<li class="text-warning"><strong>${goulot.etape}:</strong> ${goulot.delai_jours} jour(s)</li>`
                  ).join('')}
                </ul>
                ` : '<p class="text-success">Aucun goulot identifié</p>'}
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-primary" onclick="exporterAnalyse()">
              <i class="fas fa-download"></i> Exporter l'analyse
            </button>
            <button type="button" class="btn btn-outline" data-bs-dismiss="modal">Fermer</button>
          </div>
        </div>
      </div>
    </div>
  `;
  
  // Supprimer l'ancienne modal si elle existe
  const ancienneModal = document.getElementById('modalAnalysePerformance');
  if (ancienneModal) {
    ancienneModal.remove();
  }
  
  // Ajouter et afficher la modal
  document.body.insertAdjacentHTML('beforeend', modalAnalyse);
  const modal = new bootstrap.Modal(document.getElementById('modalAnalysePerformance'));
  modal.show();
  
  // Stocker l'analyse pour l'export
  window.derniereAnalyse = analyse;
};

window.exporterAnalyse = function() {
  if (!window.derniereAnalyse) {
    showToast('Erreur', 'Aucune analyse disponible', 'error');
    return;
  }
  
  const dataStr = JSON.stringify(window.derniereAnalyse, null, 2);
  const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
  
  const exportFileDefaultName = `analyse_performance_${new Date().toISOString().slice(0,10)}.json`;
  
  const linkElement = document.createElement('a');
  linkElement.setAttribute('href', dataUri);
  linkElement.setAttribute('download', exportFileDefaultName);
  linkElement.click();
  
  showToast('Succès', 'Analyse exportée avec succès', 'success');
};

// Initialisation des préférences d'accessibilité
document.addEventListener('DOMContentLoaded', function() {
  // Charger les préférences d'accessibilité
  if (localStorage.getItem('contraste_fort') === 'true') {
    document.body.classList.add('contraste-fort');
  }
  
  if (localStorage.getItem('grosse_taille') === 'true') {
    document.body.classList.add('grosse-taille');
  }
  
  // Ajouter la barre d'outils d'accessibilité
  const barreOutils = `
    <div class="barre-accessibilite" id="barreAccessibilite">
      <button type="button" class="btn btn-outline-sm" onclick="toggleContrasteFort()" title="Basculer le contraste fort">
        <i class="fas fa-adjust"></i>
      </button>
      <button type="button" class="btn btn-outline-sm" onclick="toggleGrosseTaille()" title="Basculer la grosse taille">
        <i class="fas fa-text-height"></i>
      </button>
      <button type="button" class="btn btn-outline-sm" onclick="zoomTimeline('in')" title="Zoom avant">
        <i class="fas fa-search-plus"></i>
      </button>
      <button type="button" class="btn btn-outline-sm" onclick="zoomTimeline('out')" title="Zoom arrière">
        <i class="fas fa-search-minus"></i>
      </button>
      <button type="button" class="btn btn-outline-sm" onclick="zoomTimeline('reset')" title="Taille normale">
        <i class="fas fa-undo"></i>
      </button>
    </div>
  `;
  
  document.body.insertAdjacentHTML('beforeend', barreOutils);
});

console.log('🎯 Fonctionnalités avancées d\'historique workflow chargées');
console.log('⚡ Fonctions disponibles: recherche, zoom, navigation, accessibilité, analyse');


<!-- Styles CSS additionnels pour les fonctionnalités avancées -->
<style>
/* ================================================================
   STYLES POUR LES FONCTIONNALITÉS AVANCÉES
================================================================ */

/* Barre d'outils d'accessibilité */
.barre-accessibilite {
  position: fixed;
  top: 50%;
  right: 10px;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  background: rgba(255, 255, 255, 0.9);
  padding: 0.5rem;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  z-index: 1000;
}

.barre-accessibilite .btn {
  width: 40px;
  height: 40px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Styles pour contraste fort */
.contraste-fort {
  filter: contrast(150%) brightness(110%);
}

.contraste-fort .timeline-item {
  border: 2px solid #000;
}

.contraste-fort .timeline-icon {
  border: 3px solid #000;
}

/* Styles pour grosse taille */
.grosse-taille {
  font-size: 120%;
}

.grosse-taille .timeline-icon {
  width: 4rem;
  height: 4rem;
  font-size: 1.5rem;
}

.grosse-taille .btn {
  padding: 1rem 2rem;
  font-size: 1.2rem;
}

/* Styles pour la recherche */
.search-highlight {
  background: linear-gradient(135deg, #fff3cd, #ffeaa7) !important;
  border-left: 4px solid #ffc107 !important;
  box-shadow: 0 0 10px rgba(255, 193, 7, 0.3) !important;
}

.search-highlight .timeline-title {
  color: #856404;
  font-weight: bold;
}

/* Styles pour la navigation */
.timeline-item.current {
  background: linear-gradient(135deg, #e3f2fd, #bbdefb) !important;
  border-left: 4px solid #2196f3 !important;
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(33, 150, 243, 0.3) !important;
}

/* Styles pour la lecture audio */
.timeline-item.en-lecture {
  background: linear-gradient(135deg, #e8f5e8, #c8e6c9) !important;
  border-left: 4px solid #4caf50 !important;
  animation: lecture-pulse 2s infinite;
}

@keyframes lecture-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.8; }
}

/* Styles pour la comparaison */
.comparaison-element {
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  padding: 1rem;
  max-height: 400px;
  overflow-y: auto;
}

.comparaison-element .timeline-item {
  margin-bottom: 0;
  transform: none !important;
}

/* Styles pour les messages */
#messageRecherche {
  background: #d4edda;
  border: 1px solid #c3e6cb;
  color: #155724;
  padding: 0.75rem;
  border-radius: 4px;
  margin: 1rem 0;
  text-align: center;
  display: none;
}

/* Responsive pour la barre d'outils */
@media (max-width: 768px) {
  .barre-accessibilite {
    right: 5px;
    padding: 0.25rem;
  }
  
  .barre-accessibilite .btn {
    width: 35px;
    height: 35px;
  }
}

/* Styles pour l'impression */
@media print {
  .barre-accessibilite,
  .loading-overlay,
  .toast-container,
  .btn,
  .modal {
    display: none !important;
  }
  
  .timeline-item {
    page-break-inside: avoid;
    break-inside: avoid;
  }
  
  .timeline-icon {
    background: #000 !important;
    color: #fff !important;
  }
}

/* Animations fluides */
.timeline-item {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.timeline-item:hover {
  transform: translateX(5px) scale(1.01);
}

/* Focus visible pour l'accessibilité */
.btn:focus,
.timeline-item:focus {
  outline: 3px solid #007bff;
  outline-offset: 2px;
}

/* Amélioration du contraste des liens */
a {
  color: #0056b3;
  text-decoration: underline;
}

a:hover {
  color: #004085;
  text-decoration: none;
}

/* Indicateurs visuels pour les états */
.timeline-item[data-type="validation"] {
  border-left-color: #28a745;
}

.timeline-item[data-type="action"] {
  border-left-color: #007bff;
}

.timeline-item[data-type="proposition"] {
  border-left-color: #17a2b8;
}

.timeline-item[data-type="notification"] {
  border-left-color: #fd7e14;
}
</style>
