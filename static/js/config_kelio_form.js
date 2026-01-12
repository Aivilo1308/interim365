function togglePasswordVisibility() {
  const input = document.getElementById('password');
  const icon = document.getElementById('iconPassword');
  
  if (input.type === 'password') {
    input.type = 'text';
    icon.classList.remove('fa-eye');
    icon.classList.add('fa-eye-slash');
  } else {
    input.type = 'password';
    icon.classList.remove('fa-eye-slash');
    icon.classList.add('fa-eye');
  }
}

document.addEventListener('DOMContentLoaded', function() {
  // Gestion de la soumission du formulaire
  const formConfig = document.getElementById('formConfig');
  if (formConfig) {
    formConfig.addEventListener('submit', function(e) {
      const btn = document.getElementById('btnSubmit');
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enregistrement...';
    });
  }

  // Mise à jour visuelle du switch actif
  const actifSwitch = document.getElementById('actif');
  if (actifSwitch) {
    actifSwitch.addEventListener('change', function() {
      const card = this.closest('.card');
      const icon = this.nextElementSibling.querySelector('i');
      
      if (this.checked) {
        card.classList.remove('border-secondary');
        card.classList.add('border-success');
        icon.classList.remove('text-secondary');
        icon.classList.add('text-success');
      } else {
        card.classList.remove('border-success');
        card.classList.add('border-secondary');
        icon.classList.remove('text-success');
        icon.classList.add('text-secondary');
      }
    });
  }
});
