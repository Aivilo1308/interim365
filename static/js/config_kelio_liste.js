function testerConnexion() {
  const btn = document.getElementById('btnTester');
  const resultatsDiv = document.getElementById('resultatsTest');
  const resultatsBody = document.getElementById('resultatsTestBody');
  
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Test en cours...';
  resultatsDiv.classList.add('d-none');
  
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.tester, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfToken }
  })
  .then(response => response.json())
  .then(data => {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-sync-alt me-1"></i> Tester la connexion';
    
    // Afficher les résultats
    let html = '';
    
    if (data.success) {
      html += '<div class="alert alert-success"><i class="fas fa-check-circle me-2"></i><strong>Connexion réussie!</strong> ' + data.message + '</div>';
    } else {
      html += '<div class="alert alert-danger"><i class="fas fa-times-circle me-2"></i><strong>Échec de connexion</strong> ' + data.message + '</div>';
    }
    
    if (data.tests && data.tests.length > 0) {
      html += '<table class="table table-sm">';
      html += '<thead><tr><th>Test</th><th>Résultat</th><th>Détails</th></tr></thead><tbody>';
      
      data.tests.forEach(test => {
        const icon = test.success ? '<i class="fas fa-check text-success"></i>' : '<i class="fas fa-times text-danger"></i>';
        const details = test.details ? test.details.join('<br><small class="text-muted">') : '-';
        html += `<tr>
          <td>${test.nom}</td>
          <td class="text-center">${icon}</td>
          <td><small>${details}</small></td>
        </tr>`;
      });
      
      html += '</tbody></table>';
    }
    
    if (data.temps_execution) {
      html += '<div class="small text-muted"><i class="fas fa-clock me-1"></i>Temps d\'exécution: ' + data.temps_execution + '</div>';
    }
    
    resultatsBody.innerHTML = html;
    resultatsDiv.classList.remove('d-none');
  })
  .catch(error => {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-sync-alt me-1"></i> Tester la connexion';
    alert('❌ Erreur lors du test: ' + error.message);
  });
}

function viderCache() {
  if (!confirm('Voulez-vous vraiment vider tout le cache Kelio ?\nCela forcera une nouvelle synchronisation des données.')) return;
  
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.purgerCache, {
    method: 'POST',
    headers: { 
      'X-CSRFToken': csrfToken,
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: 'type=all'
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      alert('✅ ' + data.message);
      location.reload();
    } else {
      alert('❌ ' + data.message);
    }
  });
}

function toggleActif() {
  const action = CONFIG_DATA.actif ? 'désactiver' : 'activer';
  if (!confirm(`Voulez-vous vraiment ${action} la configuration API Kelio ?`)) return;
  
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.toggleActif, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfToken }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      location.reload();
    } else {
      alert('❌ ' + data.message);
    }
  });
}

function lancerSynchro() {
  if (!confirm('Lancer une synchronisation complète avec Kelio ?\nCette opération peut prendre plusieurs minutes.')) return;
  
  alert('🔄 Synchronisation lancée en arrière-plan.\nConsultez les logs pour suivre la progression.');
  
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.lancerSync, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfToken }
  })
  .then(response => response.json())
  .then(data => {
    alert(data.success ? '✅ ' + data.message : '❌ ' + data.message);
  });
}
