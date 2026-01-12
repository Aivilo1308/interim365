document.addEventListener('DOMContentLoaded', function() {
  const codeInput = document.getElementById('code');
  const couleurInput = document.getElementById('couleur');
  const couleurText = document.getElementById('couleur_text');
  
  // Code en majuscules
  if (codeInput) {
    codeInput.addEventListener('input', function() {
      this.value = this.value.toUpperCase().replace(/[^A-Z0-9_]/g, '');
    });
  }
  
  // Synchroniser les champs couleur
  if (couleurInput && couleurText) {
    couleurInput.addEventListener('input', function() {
      couleurText.value = this.value;
    });
    
    couleurText.addEventListener('input', function() {
      if (/^#[0-9A-Fa-f]{6}$/.test(this.value)) {
        couleurInput.value = this.value;
      }
    });
  }
  
  // Soumission
  const formMotif = document.getElementById('formMotif');
  if (formMotif) {
    formMotif.addEventListener('submit', function(e) {
      // Mettre à jour la couleur depuis le champ texte
      const couleurHiddenInput = document.querySelector('input[name="couleur"]');
      if (couleurHiddenInput && couleurText) {
        couleurHiddenInput.value = couleurText.value;
      }
      
      const btn = document.getElementById('btnSubmit');
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enregistrement...';
    });
  }
});
