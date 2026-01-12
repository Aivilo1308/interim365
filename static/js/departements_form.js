document.addEventListener('DOMContentLoaded', function() {
  const codeInput = document.getElementById('code');
  
  // Convertir en majuscules et filtrer
  if (codeInput) {
    codeInput.addEventListener('input', function() {
      this.value = this.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
    });
  }

  // Validation du formulaire
  const formDepartement = document.getElementById('formDepartement');
  if (formDepartement) {
    formDepartement.addEventListener('submit', function(e) {
      const code = codeInput.value.trim();
      const nom = document.getElementById('nom').value.trim();
      
      if (!code || !nom) {
        e.preventDefault();
        alert('Veuillez remplir tous les champs obligatoires.');
        return;
      }
      
      if (!/^[A-Z0-9]{2,10}$/.test(code)) {
        e.preventDefault();
        alert('Le code doit contenir entre 2 et 10 caractères (lettres majuscules et chiffres).');
        codeInput.focus();
        return;
      }
      
      const btn = document.getElementById('btnSubmit');
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enregistrement...';
    });
  }
});
