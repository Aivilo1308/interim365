function testerConnexionKelio() {
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.testerKelio, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' }
  })
  .then(response => response.json())
  .then(data => alert(data.success ? '✅ ' + data.message : '❌ ' + data.message));
}

function purgerCache() {
  if (!confirm('Êtes-vous sûr de vouloir purger le cache expiré ?')) return;
  
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.purgerCache, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'type=expired'
  })
  .then(response => response.json())
  .then(data => { 
    alert(data.success ? '✅ ' + data.message : '❌ ' + data.message); 
    if(data.success) location.reload(); 
  });
}

document.addEventListener('DOMContentLoaded', function() {
  const formImport = document.getElementById('formImport');
  
  if (formImport) {
    formImport.addEventListener('submit', function(e) {
      e.preventDefault();
      const formData = new FormData(this);
      
      fetch(URLS.importParametres, { 
        method: 'POST', 
        body: formData 
      })
      .then(response => response.json())
      .then(data => { 
        alert(data.success ? '✅ ' + data.message : '❌ ' + data.message); 
        if(data.success) location.reload(); 
      });
    });
  }
});
