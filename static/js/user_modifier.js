
// Gestion des onglets du formulaire
function showFormTab(tabName) {
  // Masquer tous les contenus
  document.querySelectorAll('.form-tab-content').forEach(content => {
    content.classList.remove('active');
  });
  
  // Désactiver tous les onglets
  document.querySelectorAll('.form-tab').forEach(tab => {
    tab.classList.remove('active');
  });
  
  // Activer l'onglet et le contenu sélectionné
  document.getElementById('tab-' + tabName).classList.add('active');
  event.currentTarget.classList.add('active');
}

// Gestion des checkboxes
function updateCheckboxStyle(checkbox, item) {
  if (checkbox.checked) {
    item.classList.add('checked');
  } else {
    item.classList.remove('checked');
  }
}

// Superuser implique staff
document.getElementById('is_superuser').addEventListener('change', function() {
  const staffCheckbox = document.getElementById('is_staff');
  if (this.checked) {
    staffCheckbox.checked = true;
    updateCheckboxStyle(staffCheckbox, document.getElementById('staffItem'));
  }
  updateCheckboxStyle(this, document.getElementById('superuserItem'));
});

// Event listeners pour les checkboxes
['actif', 'is_active', 'is_staff', 'is_superuser'].forEach(id => {
  const checkbox = document.getElementById(id);
  const item = document.getElementById(id + 'Item') || document.getElementById(id.replace('is_', '') + 'Item');
  if (checkbox && item) {
    checkbox.addEventListener('change', function() {
      updateCheckboxStyle(this, item);
    });
  }
});

// Modal
function showModal(modalId) {
  document.getElementById(modalId).style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function closeModal(modalId) {
  document.getElementById(modalId).style.display = 'none';
  document.body.style.overflow = '';
}

function confirmDelete() {
  showModal('deleteModal');
}

function deleteUser() {
  // Rediriger vers la vue de suppression (à implémenter si nécessaire)
  // Pour l'instant, on utilise l'admin Django
  window.location.href = "{% url 'admin:mainapp_profilutilisateur_delete' profil.pk %}";
}

// Fermer modal avec Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay').forEach(modal => {
      modal.style.display = 'none';
    });
    document.body.style.overflow = '';
  }
});

// Fermer modal en cliquant sur l'overlay
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', function(e) {
    if (e.target === this) {
      this.style.display = 'none';
      document.body.style.overflow = '';
    }
  });
});

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
  console.log('Formulaire modification utilisateur initialisé');
});


<style>
/* Modal styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: none;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal {
  background: white;
  border-radius: 1rem;
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
}

.modal-header {
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--gray-200);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  margin: 0;
  font-size: 1.1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.modal-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--gray-500);
  padding: 0.25rem;
}

.modal-body {
  padding: 1.5rem;
}

.modal-footer {
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--gray-200);
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}
</style>
