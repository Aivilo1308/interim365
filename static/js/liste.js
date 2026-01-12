function purgerCache(type) {
  const msg = type === 'all' ? 'Voulez-vous vraiment supprimer TOUT le cache ?' : 'Purger les entrées expirées ?';
  if (!confirm(msg)) return;
  
  fetch(URLS.purger, {
    method: 'POST',
    headers: { 
      'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                     document.querySelector('meta[name="csrf-token"]')?.content,
      'Content-Type': 'application/x-www-form-urlencoded' 
    },
    body: 'type=' + type
  })
  .then(r => r.json())
  .then(d => { 
    alert(d.success ? '✅ ' + d.message : '❌ ' + d.message); 
    if(d.success) location.reload(); 
  });
}

function supprimerEntree(id) {
  if (!confirm('Supprimer cette entrée ?')) return;
  
  fetch(URLS.supprimer.replace('0', id), {
    method: 'POST', 
    headers: { 
      'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                     document.querySelector('meta[name="csrf-token"]')?.content
    }
  })
  .then(r => r.json())
  .then(d => { 
    if(d.success) location.reload(); 
  });
}
