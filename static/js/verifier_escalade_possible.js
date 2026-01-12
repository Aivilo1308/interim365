
document.addEventListener('DOMContentLoaded', function() {
  console.log('🔍 Page de vérification d\'escalade initialisée');
  
  // Animation d'entrée pour les cartes de vérification
  const cards = document.querySelectorAll('.verification-card, .action-card');
  cards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, index * 100);
  });
});

