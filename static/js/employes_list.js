
document.addEventListener('DOMContentLoaded', function() {
  console.log('👥 Page liste des employés initialisée');
  
  // Animation d'entrée progressive pour les cartes employés
  const employeCards = document.querySelectorAll('.employe-card');
  employeCards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, index * 100);
  });
  
  // Auto-submit du formulaire de filtres avec debounce
  let filterTimeout;
  const filterInputs = document.querySelectorAll('#recherche, #statut, #departement, #site, #ordre');
  
  filterInputs.forEach(input => {
    input.addEventListener('input', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 500);
    });
    
    input.addEventListener('change', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 200);
    });
  });
  
  // Effet de hover amélioré pour les cartes employés
  employeCards.forEach(card => {
    card.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-4px)';
    });
    
    card.addEventListener('mouseleave', function() {
      this.style.transform = 'translateY(0)';
    });
  });
  
  console.log('✅ Interactions employés initialisées');
});

// Fonction d'export des employés
function exporterEmployes() {
  const exportBtn = document.querySelector('[onclick="exporterEmployes()"]');
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

// Fonction pour filtrer rapidement par statut
function filtrerParStatut(statut) {
  const statutSelect = document.getElementById('statut');
  if (statutSelect) {
    statutSelect.value = statut;
    statutSelect.form.submit();
  }
}

// Fonction pour filtrer rapidement par département
function filtrerParDepartement(departementId) {
  const deptSelect = document.getElementById('departement');
  if (deptSelect) {
    deptSelect.value = departementId;
    deptSelect.form.submit();
  }
}

