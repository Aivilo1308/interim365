function toggleActif(id, nom, estActif) {
  const action = estActif ? 'désactiver' : 'activer';
  if (!confirm(`Voulez-vous vraiment ${action} le département "${nom}" ?`)) return;
  
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.toggleActif.replace('0', id), {
    method: 'POST',
    headers: { 
      'X-CSRFToken': csrfToken, 
      'Content-Type': 'application/json' 
    }
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
