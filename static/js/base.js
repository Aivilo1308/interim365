document.addEventListener('DOMContentLoaded', function() {
  // Mobile menu
  const mobileMenuToggle = document.getElementById('mobileMenuToggle');
  const sidebar = document.getElementById('sidebar');
  
  if (mobileMenuToggle && sidebar) {
    mobileMenuToggle.addEventListener('click', function() {
      sidebar.classList.toggle('active');
      const icon = mobileMenuToggle.querySelector('i');
      if (sidebar.classList.contains('active')) {
        icon.classList.remove('fa-bars');
        icon.classList.add('fa-times');
      } else {
        icon.classList.remove('fa-times');
        icon.classList.add('fa-bars');
      }
    });

    // Fermer sidebar au clic extérieur sur mobile
    document.addEventListener('click', function(event) {
      if (
        window.innerWidth <= 768 &&
        sidebar.classList.contains('active') &&
        !sidebar.contains(event.target) && 
        event.target !== mobileMenuToggle && 
        !mobileMenuToggle.contains(event.target)
      ) {
        sidebar.classList.remove('active');
        const icon = mobileMenuToggle.querySelector('i');
        icon.classList.remove('fa-times');
        icon.classList.add('fa-bars');
      }
    });

    // Gestion du redimensionnement
    window.addEventListener('resize', function() {
      if (window.innerWidth > 768) {
        sidebar.classList.remove('active');
        const icon = mobileMenuToggle.querySelector('i');
        icon.classList.remove('fa-times');
        icon.classList.add('fa-bars');
      }
    });
  }

  // Auto-dismiss des messages après 5 secondes
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(alert => {
    if (!alert.classList.contains('alert-error') && !alert.classList.contains('alert-danger')) {
      setTimeout(() => {
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-20px)';
        setTimeout(() => {
          if (alert.parentNode) {
            alert.parentNode.removeChild(alert);
          }
        }, 300);
      }, 5000);
    }
  });

  console.log('Template de base initialisé');
});
