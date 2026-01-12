document.addEventListener('DOMContentLoaded', function() {
  const formEtape = document.getElementById('formEtape');
  
  if (formEtape) {
    formEtape.addEventListener('submit', function(e) {
      const btn = document.getElementById('btnSubmit');
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enregistrement...';
    });
  }
});
