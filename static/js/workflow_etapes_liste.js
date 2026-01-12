document.addEventListener('DOMContentLoaded', function() {
  const container = document.getElementById('listeEtapes');
  if (!container) return;
  
  const items = container.querySelectorAll('.etape-item');
  let draggedItem = null;

  items.forEach(item => {
    item.addEventListener('dragstart', function(e) {
      draggedItem = this;
      this.classList.add('dragging');
    });

    item.addEventListener('dragend', function() {
      this.classList.remove('dragging');
      items.forEach(i => i.classList.remove('drag-over'));
      sauvegarderOrdre();
    });

    item.addEventListener('dragover', function(e) {
      e.preventDefault();
      if (this !== draggedItem) {
        this.classList.add('drag-over');
      }
    });

    item.addEventListener('dragleave', function() {
      this.classList.remove('drag-over');
    });

    item.addEventListener('drop', function(e) {
      e.preventDefault();
      if (this !== draggedItem) {
        const allItems = [...container.querySelectorAll('.etape-item')];
        const draggedIdx = allItems.indexOf(draggedItem);
        const targetIdx = allItems.indexOf(this);
        
        if (draggedIdx < targetIdx) {
          this.parentNode.insertBefore(draggedItem, this.nextSibling);
        } else {
          this.parentNode.insertBefore(draggedItem, this);
        }
      }
      this.classList.remove('drag-over');
    });
  });

  function sauvegarderOrdre() {
    const ordre = [...container.querySelectorAll('.etape-item')].map(item => item.dataset.id);
    
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                      document.querySelector('meta[name="csrf-token"]')?.content;
    
    fetch(URLS.reordonner, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ ordre: ordre })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Mettre à jour les numéros affichés
        container.querySelectorAll('.etape-item').forEach((item, index) => {
          item.querySelector('.badge.bg-info').textContent = index + 1;
        });
      }
    });
  }
});

function supprimerEtape(id, nom) {
  if (!confirm(`Voulez-vous vraiment supprimer l'étape "${nom}" ?\nCette action est irréversible.`)) return;
  
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    document.querySelector('meta[name="csrf-token"]')?.content;
  
  fetch(URLS.supprimer.replace('0', id), {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfToken }
  })
  .then(response => response.json())
  .then(data => { 
    if (data.success) location.reload(); 
    else alert('❌ ' + data.message); 
  });
}
