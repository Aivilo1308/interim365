
document.addEventListener('DOMContentLoaded', function() {
  console.log('📊 Page historique des escalades initialisée');
  
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
      this.style.transform = 'scale(1.02)';
    });
    
    content.addEventListener('mouseleave', function() {
      this.style.transform = 'scale(1)';
    });
  });
  
  // Auto-submit du formulaire de filtres avec debounce
  let filterTimeout;
  const filterInputs = document.querySelectorAll('#recherche, #escaladeur, #niveau_debut, #date_debut, #date_fin');
  
  filterInputs.forEach(input => {
    input.addEventListener('input', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 500); // 500ms de délai
    });
  });
  
  // Compteur animé pour les statistiques
  const statNumbers = document.querySelectorAll('.stat-number');
  statNumbers.forEach(number => {
    const finalValue = parseInt(number.textContent);
    if (!isNaN(finalValue) && finalValue > 0) {
      let currentValue = 0;
      const increment = Math.ceil(finalValue / 20);
      const timer = setInterval(() => {
        currentValue += increment;
        if (currentValue >= finalValue) {
          currentValue = finalValue;
          clearInterval(timer);
        }
        number.textContent = currentValue;
      }, 50);
    }
  });
  
  console.log('✅ Animations et interactions initialisées');
});

