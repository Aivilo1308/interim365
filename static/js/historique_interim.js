
document.addEventListener('DOMContentLoaded', function() {
  console.log('📊 Page historique des demandes d\'intérim initialisée');
  
  // Animation d'entrée progressive pour les éléments de timeline
  const timelineItems = document.querySelectorAll('.timeline-item');
  timelineItems.forEach((item, index) => {
    item.style.opacity = '0';
    item.style.transform = 'translateX(-20px)';
    
    setTimeout(() => {
      item.style.transition = 'all 0.5s ease';
      item.style.opacity = '1';
      item.style.transform = 'translateX(0)';
    }, index * 200);
  });
  
  // Animation d'entrée pour les cartes de statistiques
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
  
  // Effet de hover amélioré pour les timeline items
  const timelineContents = document.querySelectorAll('.timeline-content');
  timelineContents.forEach(content => {
    content.addEventListener('mouseenter', function() {
      this.style.transform = 'scale(1.01)';
    });
    
    content.addEventListener('mouseleave', function() {
      this.style.transform = 'scale(1)';
    });
  });
  
  // Auto-submit du formulaire de filtres avec debounce
  let filterTimeout;
  const filterInputs = document.querySelectorAll('#recherche, #statut, #urgence, #departement, #date_debut, #date_fin, #ordre');
  
  filterInputs.forEach(input => {
    input.addEventListener('input', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 500); // 500ms de délai
    });
    
    input.addEventListener('change', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 200); // Délai plus court pour les selects
    });
  });
  
  // Compteur animé pour les statistiques
  const statNumbers = document.querySelectorAll('.stat-number');
  statNumbers.forEach(number => {
    const text = number.textContent;
    const value = parseFloat(text);
    
    if (!isNaN(value) && value > 0) {
      let current = 0;
      const increment = Math.ceil(value / 20);
      const suffix = text.replace(value.toString(), '');
      
      const timer = setInterval(() => {
        current += increment;
        if (current >= value) {
          current = value;
          clearInterval(timer);
        }
        
        number.textContent = Math.floor(current) + suffix;
      }, 50);
    }
  });
  
  // Interaction pour les propositions et validations
  const propositionItems = document.querySelectorAll('.proposition-item');
  propositionItems.forEach(item => {
    item.addEventListener('click', function() {
      // Supprimer la sélection des autres items
      propositionItems.forEach(p => p.classList.remove('active'));
      // Ajouter la sélection à l'item cliqué
      this.classList.add('active');
    });
  });
  
  // Tooltip pour les badges de score
  const scoreBadges = document.querySelectorAll('.score-badge');
  scoreBadges.forEach(badge => {
    badge.addEventListener('mouseenter', function() {
      const score = parseInt(this.textContent);
      let tooltip = '';
      
      if (score >= 80) {
        tooltip = 'Excellent candidat - Très bon match';
      } else if (score >= 70) {
        tooltip = 'Bon candidat - Match satisfaisant';
      } else if (score >= 50) {
        tooltip = 'Candidat correct - Match moyen';
      } else {
        tooltip = 'Candidat peu adapté - Faible match';
      }
      
      this.title = tooltip;
    });
  });
  
  console.log('✅ Animations et interactions initialisées');
});

// Fonction d'export de l'historique
function exportHistorique() {
  const exportBtn = document.querySelector('[onclick="exportHistorique()"]');
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
    notification.className = 'alert alert-success';
    notification.style.position = 'fixed';
    notification.style.top = '20px';
    notification.style.right = '20px';
    notification.style.zIndex = '9999';
    notification.style.padding = '1rem';
    notification.style.borderRadius = '8px';
    notification.style.backgroundColor = '#d4edda';
    notification.style.color = '#155724';
    notification.style.border = '1px solid #c3e6cb';
    notification.innerHTML = '<i class="fas fa-check-circle"></i> Export terminé avec succès !';
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
      notification.remove();
    }, 3000);
    
  }, 2000);
}

// Fonction pour afficher les détails d'une demande (modal ou expansion)
function afficherDetailsDemande(numeroDeemande) {
  console.log('Affichage des détails pour la demande:', numeroDeemande);
  // Implémentation future : modal avec détails complets
}

// Fonction pour filtrer rapidement par statut
function filtrerParStatut(statut) {
  const statutSelect = document.getElementById('statut');
  if (statutSelect) {
    statutSelect.value = statut;
    statutSelect.form.submit();
  }
}

// Fonction pour filtrer rapidement par urgence
function filtrerParUrgence(urgence) {
  const urgenceSelect = document.getElementById('urgence');
  if (urgenceSelect) {
    urgenceSelect.value = urgence;
    urgenceSelect.form.submit();
  }
}

