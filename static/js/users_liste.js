
// Fonctions utilitaires
function showModal(modalId) {
  document.getElementById(modalId).classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModal(modalId) {
  document.getElementById(modalId).classList.remove('active');
  document.body.style.overflow = '';
}

// Fermer modal avec Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.active').forEach(modal => {
      modal.classList.remove('active');
    });
    document.body.style.overflow = '';
  }
});

// Fermer modal en cliquant sur l'overlay
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', function(e) {
    if (e.target === this) {
      this.classList.remove('active');
      document.body.style.overflow = '';
    }
  });
});

// Afficher les détails d'un utilisateur
function showUserDetail(userId) {
  fetch(`{% url 'user_detail_ajax' 0 %}`.replace('0', userId))
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        const user = data.user;
        document.getElementById('modalUserName').textContent = user.nom_complet;
        
        let html = `
          <div class="detail-item">
            <div class="detail-label">Matricule</div>
            <div class="detail-value">${user.matricule}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Nom d'utilisateur</div>
            <div class="detail-value">${user.username}</div>
          </div>
          <div class="detail-item full-width">
            <div class="detail-label">Email</div>
            <div class="detail-value">${user.email}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Type de profil</div>
            <div class="detail-value">${user.type_profil}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Statut employé</div>
            <div class="detail-value">${user.statut_employe}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Département</div>
            <div class="detail-value">${user.departement}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Site</div>
            <div class="detail-value">${user.site}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Poste</div>
            <div class="detail-value">${user.poste}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Manager</div>
            <div class="detail-value">${user.manager}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Date d'embauche</div>
            <div class="detail-value">${user.date_embauche}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Source</div>
            <div class="detail-value">
              <span class="badge ${user.source === 'Kelio' ? 'badge-kelio' : 'badge-local'}">
                ${user.source}
              </span>
            </div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Super administrateur</div>
            <div class="detail-value">${user.is_superuser ? '✅ Oui' : '❌ Non'}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Statut</div>
            <div class="detail-value">${user.actif ? '🟢 Actif' : '🔴 Inactif'}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Dernière sync Kelio</div>
            <div class="detail-value">${user.kelio_last_sync}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Badge Kelio</div>
            <div class="detail-value">${user.kelio_badge_code}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Créé le</div>
            <div class="detail-value">${user.created_at}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">Modifié le</div>
            <div class="detail-value">${user.updated_at}</div>
          </div>
        `;
        
        document.getElementById('userDetailContent').innerHTML = html;
        showModal('userDetailModal');
      } else {
        showNotification('Erreur: ' + data.message, 'error');
      }
    })
    .catch(error => {
      console.error('Erreur:', error);
      showNotification('Erreur de chargement', 'error');
    });
}

// Toggle actif/inactif
function toggleUserActif(userId, currentStatus) {
  const action = currentStatus ? 'désactiver' : 'activer';
  
  if (!confirm(`Voulez-vous vraiment ${action} cet utilisateur ?`)) {
    return;
  }
  
  fetch(`{% url 'toggle_user_actif' 0 %}`.replace('0', userId), {
    method: 'POST',
    headers: {
      'X-CSRFToken': '{{ csrf_token }}',
      'Content-Type': 'application/json'
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
      setTimeout(() => location.reload(), 1000);
    } else {
      showNotification('Erreur: ' + data.message, 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur de communication', 'error');
  });
}

// Reset password
function showResetPassword(userId, userName) {
  document.getElementById('resetUserId').value = userId;
  document.getElementById('resetUserName').textContent = userName;
  document.getElementById('newPassword').value = '';
  document.getElementById('confirmPassword').value = '';
  showModal('resetPasswordModal');
}

function submitResetPassword() {
  const userId = document.getElementById('resetUserId').value;
  const newPassword = document.getElementById('newPassword').value;
  const confirmPassword = document.getElementById('confirmPassword').value;
  
  if (newPassword.length < 8) {
    showNotification('Le mot de passe doit contenir au moins 8 caractères', 'error');
    return;
  }
  
  if (newPassword !== confirmPassword) {
    showNotification('Les mots de passe ne correspondent pas', 'error');
    return;
  }
  
  const formData = new FormData();
  formData.append('new_password', newPassword);
  
  fetch(`{% url 'reset_user_password' 0 %}`.replace('0', userId), {
    method: 'POST',
    headers: {
      'X-CSRFToken': '{{ csrf_token }}'
    },
    body: formData
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
      closeModal('resetPasswordModal');
    } else {
      showNotification('Erreur: ' + data.message, 'error');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('Erreur de communication', 'error');
  });
}

// Recherche avec délai
let searchTimeout;
document.querySelector('.search-box input').addEventListener('input', function() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    document.getElementById('filterForm').submit();
  }, 500);
});

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
  console.log('Page gestion utilisateurs chargée');
});

