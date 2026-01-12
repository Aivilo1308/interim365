
document.addEventListener('DOMContentLoaded', function() {
  console.log('📅 Page disponibilité employé initialisée pour:', '{{ employe.nom_complet }}');
  
  // Génération du calendrier
  genererCalendrier();
  
  // Animation d'entrée progressive pour les sections
  const cardContainers = document.querySelectorAll('.card-container');
  cardContainers.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, index * 150);
  });
  
  // Animation des statistiques
  animerStatistiques();
  
  console.log('✅ Interactions disponibilité initialisées');
});

// Génération du calendrier
function genererCalendrier() {
  const calendrierGrid = document.getElementById('calendrier-grid');
  if (!calendrierGrid) return;
  
  // Données simulées - à remplacer par les vraies données du backend
  const periodeDebut = new Date('{{ periode_debut|date:"Y-m-d" }}');
  const periodeFin = new Date('{{ periode_fin|date:"Y-m-d" }}');
  
  // Headers des jours
  const joursNoms = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
  joursNoms.forEach(jour => {
    const header = document.createElement('div');
    header.className = 'calendrier-header';
    header.textContent = jour;
    calendrierGrid.appendChild(header);
  });
  
  // Générer les jours du calendrier
  const premierJour = new Date(periodeDebut.getFullYear(), periodeDebut.getMonth(), 1);
  const dernierJour = new Date(periodeFin.getFullYear(), periodeFin.getMonth() + 1, 0);
  
  // Ajuster au début de la semaine
  const debutCalendrier = new Date(premierJour);
  debutCalendrier.setDate(debutCalendrier.getDate() - (debutCalendrier.getDay() || 7) + 1);
  
  // Ajuster à la fin de la semaine
  const finCalendrier = new Date(dernierJour);
  finCalendrier.setDate(finCalendrier.getDate() + (7 - (finCalendrier.getDay() || 7)));
  
  const jourActuel = new Date(debutCalendrier);
  const aujourd_hui = new Date();
  
  // Données d'exemple des absences et missions (à remplacer par les vraies données)
  const absencesData = [
    {% for absence in absences %}
    {
      debut: new Date('{{ absence.date_debut|date:"Y-m-d" }}'),
      fin: new Date('{{ absence.date_fin|date:"Y-m-d" }}'),
      type: '{{ absence.type_absence|escapejs }}'
    },
    {% endfor %}
  ];
  
  const missionsData = [
    {% for mission in missions %}
    {
      debut: new Date('{{ mission.demande_interim.date_debut|date:"Y-m-d"|default:"1970-01-01" }}'),
      fin: new Date('{{ mission.demande_interim.date_fin|date:"Y-m-d"|default:"1970-01-01" }}'),
      poste: '{{ mission.demande_interim.poste.titre|escapejs }}'
    },
    {% endfor %}
  ];
  
  while (jourActuel <= finCalendrier) {
    const jourElement = document.createElement('div');
    jourElement.className = 'calendrier-jour';
    jourElement.textContent = jourActuel.getDate();
    
    // Déterminer le statut du jour
    let statut = 'disponible';
    let details = '';
    
    // Vérifier si c'est un week-end
    if (jourActuel.getDay() === 0 || jourActuel.getDay() === 6) {
      statut = 'weekend';
      details = 'Week-end';
    }
    
    // Vérifier les absences
    for (const absence of absencesData) {
      if (jourActuel >= absence.debut && jourActuel <= absence.fin) {
        statut = 'absence';
        details = `Absence: ${absence.type}`;
        break;
      }
    }
    
    // Vérifier les missions (priorité sur les absences)
    for (const mission of missionsData) {
      if (jourActuel >= mission.debut && jourActuel <= mission.fin) {
        statut = 'mission';
        details = `Mission: ${mission.poste}`;
        break;
      }
    }
    
    // Vérifier si c'est aujourd'hui
    if (jourActuel.toDateString() === aujourd_hui.toDateString()) {
      jourElement.classList.add('aujourd-hui');
    }
    
    // Vérifier si c'est dans un autre mois
    if (jourActuel.getMonth() !== periodeDebut.getMonth() && 
        jourActuel.getMonth() !== periodeFin.getMonth()) {
      jourElement.classList.add('autre-mois');
    }
    
    jourElement.classList.add(statut);
    jourElement.title = `${jourActuel.toLocaleDateString('fr-FR')} - ${details}`;
    
    // Événement de clic pour plus de détails
    jourElement.addEventListener('click', function() {
      afficherDetailsJour(jourActuel, statut, details);
    });
    
    calendrierGrid.appendChild(jourElement);
    
    // Passer au jour suivant
    jourActuel.setDate(jourActuel.getDate() + 1);
  }
}

// Animation des statistiques
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
  });
  
  statNumbers.forEach(number => observer.observe(number));
}

// Animation du compteur
function animerCompteur(element, finalValue) {
  const suffix = element.textContent.replace(finalValue.toString(), '');
  let currentValue = 0;
  const increment = Math.ceil(finalValue / 30);
  
  const timer = setInterval(() => {
    currentValue += increment;
    if (currentValue >= finalValue) {
      currentValue = finalValue;
      clearInterval(timer);
    }
    
    element.textContent = currentValue + suffix;
  }, 50);
}

// Afficher les détails d'un jour
function afficherDetailsJour(date, statut, details) {
  console.log('Détails pour le', date.toLocaleDateString('fr-FR'), ':', statut, details);
  
  // Créer une modal simple
  const modal = document.createElement('div');
  modal.className = 'jour-modal';
  modal.innerHTML = `
    <div class="jour-modal-content">
      <div class="jour-modal-header">
        <h3>${date.toLocaleDateString('fr-FR', { 
          weekday: 'long', 
          year: 'numeric', 
          month: 'long', 
          day: 'numeric' 
        })}</h3>
        <button onclick="fermerModalJour()" class="btn-close">&times;</button>
      </div>
      <div class="jour-modal-body">
        <div class="statut-jour ${statut}">
          <i class="fas fa-${getStatutIcon(statut)}"></i>
          ${details}
        </div>
        <div class="actions-jour">
          <button onclick="fermerModalJour()" class="btn btn-outline">Fermer</button>
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
  
  const content = modal.querySelector('.jour-modal-content');
  content.style.cssText = `
    background: white;
    border-radius: 8px;
    padding: 2rem;
    max-width: 400px;
    width: 90%;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  `;
  
  document.body.appendChild(modal);
  
  // Fermer en cliquant sur le fond
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      fermerModalJour();
    }
  });
}

// Fermer la modal du jour
function fermerModalJour() {
  const modal = document.querySelector('.jour-modal');
  if (modal) {
    modal.style.animation = 'fadeOut 0.3s ease';
    setTimeout(() => modal.remove(), 300);
  }
}

// Icône selon le statut
function getStatutIcon(statut) {
  const icons = {
    'disponible': 'check-circle',
    'absence': 'times-circle',
    'mission': 'briefcase',
    'weekend': 'calendar'
  };
  return icons[statut] || 'question-circle';
}

// Fonction d'impression du planning
function imprimerPlanning() {
  console.log('Impression du planning de disponibilité');
  
  // Masquer les éléments non nécessaires à l'impression
  const elementsToHide = document.querySelectorAll('.disponibilite-header .btn, .actions-grid, .card-header .btn');
  elementsToHide.forEach(el => {
    el.style.display = 'none';
  });
  
  // Styles spécifiques pour l'impression
  const printStyles = document.createElement('style');
  printStyles.innerHTML = `
    @media print {
      body { font-size: 12pt; }
      .card-container { break-inside: avoid; margin-bottom: 1rem; }
      .calendrier-grid { grid-template-columns: repeat(7, 1fr); gap: 1px; }
      .calendrier-jour { padding: 0.5rem; font-size: 10pt; }
      .timeline-item { break-inside: avoid; }
    }
  `;
  document.head.appendChild(printStyles);
  
  // Lancer l'impression
  window.print();
  
  // Restaurer les éléments après impression
  setTimeout(() => {
    elementsToHide.forEach(el => {
      el.style.display = '';
    });
    printStyles.remove();
  }, 1000);
}

// Fonction d'export du planning
function exporterPlanning() {
  const exportBtn = document.querySelector('[onclick="exporterPlanning()"]');
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
    notification.className = 'export-notification';
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 9999;
      padding: 1rem;
      border-radius: 8px;
      background-color: #d4edda;
      color: #155724;
      border: 1px solid #c3e6cb;
      box-shadow: 0 4px 8px rgba(0,0,0,0.1);
      animation: slideInRight 0.3s ease;
    `;
    notification.innerHTML = '<i class="fas fa-check-circle"></i> Planning exporté avec succès !';
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
      notification.style.animation = 'slideOutRight 0.3s ease';
      setTimeout(() => notification.remove(), 300);
    }, 3000);
    
  }, 2000);
}

// Fonction pour naviguer entre les mois
function changerMois(direction) {
  console.log('Navigation calendrier:', direction);
  // Implémentation future : navigation entre les mois
}

// Fonction pour aller à une date spécifique
function allerADate(date) {
  console.log('Navigation vers la date:', date);
  // Implémentation future : navigation vers une date spécifique
}

// Gestion des raccourcis clavier
document.addEventListener('keydown', function(e) {
  // Échap pour fermer les modals
  if (e.key === 'Escape') {
    fermerModalJour();
  }
  
  // Ctrl+P pour imprimer
  if (e.ctrlKey && e.key === 'p') {
    e.preventDefault();
    imprimerPlanning();
  }
});

// Ajout des styles d'animation
const styleSheet = document.createElement('style');
styleSheet.innerHTML = `
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
`;
document.head.appendChild(styleSheet);

