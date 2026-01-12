document.addEventListener('DOMContentLoaded', function() {
  const dateInput = document.getElementById('date_ferie');
  const apercuDiv = document.getElementById('apercu-date');
  const apercuJour = document.getElementById('apercu-jour');
  const apercuDateComplete = document.getElementById('apercu-date-complete');
  
  const joursSemaine = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi'];
  const mois = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 
                'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  
  // Mise à jour de l'aperçu de la date
  dateInput.addEventListener('change', function() {
    if (this.value) {
      const date = new Date(this.value + 'T00:00:00');
      const jourSemaine = joursSemaine[date.getDay()];
      const jour = date.getDate();
      const moisNom = mois[date.getMonth()];
      const annee = date.getFullYear();
      
      apercuJour.textContent = jourSemaine;
      apercuDateComplete.textContent = `${jour} ${moisNom} ${annee}`;
      
      // Alerte si weekend
      if (date.getDay() === 0 || date.getDay() === 6) {
        apercuJour.innerHTML = jourSemaine + ' <span class="badge bg-warning text-dark ms-2">Weekend</span>';
      }
      
      apercuDiv.style.display = 'block';
    } else {
      apercuDiv.style.display = 'none';
    }
  });
  
  // Validation du formulaire
  document.getElementById('formCreerFerie').addEventListener('submit', function(e) {
    const nom = document.getElementById('nom').value.trim();
    const dateFerie = document.getElementById('date_ferie').value;
    
    if (!nom) {
      e.preventDefault();
      alert('Veuillez saisir un nom pour le jour férié.');
      document.getElementById('nom').focus();
      return;
    }
    
    if (!dateFerie) {
      e.preventDefault();
      alert('Veuillez sélectionner une date.');
      document.getElementById('date_ferie').focus();
      return;
    }
    
    // Désactiver le bouton pour éviter les doubles soumissions
    const btn = document.getElementById('btnSubmit');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Création en cours...';
  });
});
