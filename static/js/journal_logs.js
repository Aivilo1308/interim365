
// Variables globales
const csrfToken = '{{ csrf_token }}';
const PURGE_CONFIRM_TEXT = 'JE CONFIRME LA PURGE DES FICHIERS LOGS';
let selectedPurgeMode = null;
let purgeModalInstance = null;
let logDetailModalInstance = null;

// Initialisation au chargement
document.addEventListener('DOMContentLoaded', function() {
  // Initialiser les modals Bootstrap
  const purgeModalEl = document.getElementById('purgeModal');
  const logDetailModalEl = document.getElementById('logDetailModal');
  
  if (purgeModalEl) {
    purgeModalInstance = new bootstrap.Modal(purgeModalEl);
  }
  if (logDetailModalEl) {
    logDetailModalInstance = new bootstrap.Modal(logDetailModalEl);
  }
  
  console.log('Journal Logs initialisé avec Bootstrap modals');
});

// Toggle filtres
function toggleFilters() {
  document.getElementById('filtersBody').classList.toggle('collapsed');
  document.getElementById('filtersIcon').classList.toggle('fa-chevron-up');
}

// Raccourcis de date
function setDateRange(range) {
  const today = new Date();
  let startDate, endDate;
  switch(range) {
    case 'today': startDate = endDate = today; break;
    case 'yesterday': startDate = endDate = new Date(today.setDate(today.getDate() - 1)); break;
    case 'week': startDate = new Date(today.setDate(today.getDate() - today.getDay())); endDate = new Date(); break;
    case 'month': startDate = new Date(today.getFullYear(), today.getMonth(), 1); endDate = new Date(); break;
    case 'last30': startDate = new Date(new Date().setDate(new Date().getDate() - 30)); endDate = new Date(); break;
    default: return;
  }
  document.querySelector('input[name="date_debut"]').value = startDate.toISOString().split('T')[0];
  document.querySelector('input[name="date_fin"]').value = endDate.toISOString().split('T')[0];
}

// Modal détail log
function showLogDetail(logId) {
  const content = document.getElementById('logDetailContent');
  content.innerHTML = '<div class="text-center p-4"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';
  
  if (logDetailModalInstance) {
    logDetailModalInstance.show();
  }
  
  fetch(`{% url 'journal_logs_detail' 0 %}`.replace('0', logId))
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        const log = data.log;
        content.innerHTML = `
          <div class="row g-3">
            <div class="col-6"><div class="text-muted small">Date</div><div class="fw-bold">${log.date}</div></div>
            <div class="col-6"><div class="text-muted small">Source</div><div class="fw-bold">${log.source}</div></div>
            <div class="col-6"><div class="text-muted small">Action</div><div class="fw-bold">${log.action}</div></div>
            <div class="col-6"><div class="text-muted small">Sévérité</div><div class="fw-bold">${log.severite}</div></div>
            <div class="col-6"><div class="text-muted small">Utilisateur</div><div class="fw-bold">${log.utilisateur}</div></div>
            <div class="col-6"><div class="text-muted small">Matricule</div><div class="fw-bold">${log.matricule}</div></div>
            <div class="col-6"><div class="text-muted small">Email</div><div class="fw-bold">${log.email}</div></div>
            <div class="col-6"><div class="text-muted small">IP</div><div class="fw-bold font-monospace">${log.adresse_ip}</div></div>
            <div class="col-12"><div class="text-muted small">Description</div><div class="fw-bold">${log.description}</div></div>
            <div class="col-12"><div class="text-muted small">User Agent</div><div class="fw-bold font-monospace small">${log.user_agent}</div></div>
            ${log.donnees_avant ? `<div class="col-12"><div class="text-muted small">Données AVANT</div><pre class="bg-dark text-success p-2 rounded small">${JSON.stringify(log.donnees_avant, null, 2)}</pre></div>` : ''}
            ${log.donnees_apres ? `<div class="col-12"><div class="text-muted small">Données APRÈS</div><pre class="bg-dark text-success p-2 rounded small">${JSON.stringify(log.donnees_apres, null, 2)}</pre></div>` : ''}
          </div>`;
      } else {
        content.innerHTML = `<div class="text-center text-muted"><i class="fas fa-exclamation-triangle fa-2x mb-2"></i><p>${data.message}</p></div>`;
      }
    });
}

// Téléchargement ZIP
function downloadZip(includeRotated) {
  const url = includeRotated 
    ? '{% url "journal_logs_download_zip" %}?include_rotated=true'
    : '{% url "journal_logs_download_zip" %}';
  
  showToast('Préparation du téléchargement...', 'success');
  window.location.href = url;
}

// Téléchargement fichier individuel
function downloadFile(filename) {
  window.location.href = `{% url "journal_logs_download_file" "FILENAME" %}`.replace('FILENAME', filename);
}

// Modal Purge
function openPurgeModal() {
  selectedPurgeMode = null;
  document.querySelectorAll('.purge-option').forEach(el => {
    el.classList.remove('border-primary', 'bg-light');
    el.style.borderLeftWidth = '4px';
  });
  document.getElementById('btnExecutePurge').disabled = true;
  
  // Réinitialiser la confirmation
  document.getElementById('purgeConfirmSection').style.display = 'none';
  const confirmInput = document.getElementById('purgeConfirmInput');
  confirmInput.value = '';
  confirmInput.classList.remove('is-valid', 'is-invalid');
  
  if (purgeModalInstance) {
    purgeModalInstance.show();
  }
  loadPurgeInfo();
}

function loadPurgeInfo() {
  fetch('{% url "journal_logs_purge_info" %}')
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        document.getElementById('statTotalSize').textContent = data.info.taille_totale_human;
        document.getElementById('statMainFiles').textContent = data.info.fichiers_principaux.length;
        document.getElementById('statRotatedFiles').textContent = data.info.nb_fichiers_rotation;
      }
    })
    .catch(err => {
      console.error('Erreur chargement info purge:', err);
    });
}

function selectPurgeOption(element) {
  document.querySelectorAll('.purge-option').forEach(el => {
    el.classList.remove('border-primary', 'bg-light');
  });
  element.classList.add('border-primary', 'bg-light');
  selectedPurgeMode = element.dataset.mode;
  
  // Afficher la section de confirmation
  document.getElementById('purgeConfirmSection').style.display = 'block';
  document.getElementById('purgeConfirmInput').value = '';
  document.getElementById('purgeConfirmInput').classList.remove('is-valid', 'is-invalid');
  document.getElementById('btnExecutePurge').disabled = true;
}

function checkPurgeConfirmation() {
  const input = document.getElementById('purgeConfirmInput');
  const value = input.value.trim().toUpperCase();
  const isValid = value === PURGE_CONFIRM_TEXT && selectedPurgeMode !== null;
  
  document.getElementById('btnExecutePurge').disabled = !isValid;
  
  // Feedback visuel Bootstrap
  if (value.length > 0) {
    input.classList.remove('is-valid', 'is-invalid');
    input.classList.add(isValid ? 'is-valid' : 'is-invalid');
  } else {
    input.classList.remove('is-valid', 'is-invalid');
  }
}

function executePurge() {
  if (!selectedPurgeMode) return;
  
  // Vérification finale de la confirmation
  const confirmValue = document.getElementById('purgeConfirmInput').value.trim().toUpperCase();
  if (confirmValue !== PURGE_CONFIRM_TEXT) {
    showToast('Veuillez taper la phrase de confirmation exacte', 'error');
    return;
  }
  
  const btn = document.getElementById('btnExecutePurge');
  const originalText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Purge en cours...';
  
  const payload = {
    mode: selectedPurgeMode,
    confirm: true
  };
  
  if (selectedPurgeMode === 'delete_rotated') {
    payload.jours_retention = parseInt(document.getElementById('retentionDays').value) || 7;
  }
  
  fetch('{% url "journal_logs_purge" %}', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken
    },
    body: JSON.stringify(payload)
  })
  .then(r => r.json())
  .then(data => {
    btn.innerHTML = originalText;
    btn.disabled = false;
    
    if (data.success) {
      if (purgeModalInstance) purgeModalInstance.hide();
      const results = data.results;
      let msg = `Purge réussie! ${results.espace_libere_human} libérés.`;
      showToast(msg, 'success');
      setTimeout(() => location.reload(), 2000);
    } else {
      showToast(data.message || 'Erreur lors de la purge', 'error');
    }
  })
  .catch(err => {
    btn.innerHTML = originalText;
    btn.disabled = false;
    showToast('Erreur de connexion', 'error');
  });
}

// Toast notification
function showToast(message, type = 'success') {
  const toast = document.getElementById('toast');
  const icon = toast.querySelector('i');
  
  toast.className = 'toast ' + type;
  icon.className = type === 'success' ? 'fas fa-check-circle' : 
                   type === 'error' ? 'fas fa-times-circle' : 'fas fa-exclamation-triangle';
  document.getElementById('toastMessage').textContent = message;
  
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 4000);
}

// Fermeture modals avec Escape
document.addEventListener('keydown', e => { 
  if (e.key === 'Escape') {
    if (purgeModalInstance) purgeModalInstance.hide();
    if (logDetailModalInstance) logDetailModalInstance.hide();
  }
});

