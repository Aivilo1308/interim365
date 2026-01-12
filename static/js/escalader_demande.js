
document.addEventListener('DOMContentLoaded', function() {
  console.log('🚨 Page d\'escalade de demande initialisée');
  
  const form = document.getElementById('formEscalade');
  const btnEscalader = document.getElementById('btnEscalader');
  const loadingOverlay = document.getElementById('loadingOverlay');
  
  if (form) {
    form.addEventListener('submit', function(e) {
      e.preventDefault();
      
      const motif = document.getElementById('motif_escalade').value.trim();
      
      if (!motif) {
        alert('Le motif d\'escalade est obligatoire');
        document.getElementById('motif_escalade').focus();
        return;
      }
      
      if (motif.length < 20) {
        alert('Le motif doit contenir au moins 20 caractères');
        document.getElementById('motif_escalade').focus();
        return;
      }
      
      if (confirm('Êtes-vous sûr de vouloir escalader cette demande ? Cette action est irréversible.')) {
        // Afficher le loading
        if (loadingOverlay) {
          loadingOverlay.style.display = 'flex';
        }
        
        // Désactiver le bouton
        if (btnEscalader) {
          btnEscalader.disabled = true;
          btnEscalader.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Escalade en cours...';
        }
        
        // Soumettre le formulaire
        form.submit();
      }
    });
  }
  
  // Auto-focus sur le textarea
  const motifTextarea = document.getElementById('motif_escalade');
  if (motifTextarea) {
    motifTextarea.focus();
  }
});

