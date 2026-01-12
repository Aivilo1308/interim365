
// Gestion des onglets
function showTab(tabName) {
  // Masquer tous les contenus
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.remove('active');
  });
  
  // Désactiver tous les onglets
  document.querySelectorAll('.tab').forEach(tab => {
    tab.classList.remove('active');
  });
  
  // Activer l'onglet et le contenu sélectionné
  document.getElementById('tab-' + tabName).classList.add('active');
  event.currentTarget.classList.add('active');
  
  // Sauvegarder l'onglet actif dans l'URL
  history.replaceState(null, '', '?tab=' + tabName);
}

// Restaurer l'onglet actif depuis l'URL
document.addEventListener('DOMContentLoaded', function() {
  const urlParams = new URLSearchParams(window.location.search);
  const tab = urlParams.get('tab');
  
  if (tab) {
    const tabElement = document.querySelector(`.tab[onclick*="${tab}"]`);
    if (tabElement) {
      tabElement.click();
    }
  }
  
  console.log('Page détails utilisateur chargée');
});

