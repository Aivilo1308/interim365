
document.addEventListener('DOMContentLoaded', function() {
  console.log('📧 Page notifications initialisée');
  
  // Animation d'entrée progressive pour les éléments de timeline
  const timelineItems = document.querySelectorAll('.timeline-item');
  timelineItems.forEach((item, index) => {
    item.style.opacity = '0';
    item.style.transform = 'translateX(-20px)';
    
    setTimeout(() => {
      item.style.transition = 'all 0.5s ease';
      item.style.opacity = '1';
      item.style.transform = 'translateX(0)';
    }, index * 150);
  });
  
  // Animation d'entrée pour les cartes de statistiques
  const statCards = document.querySelectorAll('.stat-card');
  statCards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    
    setTimeout(() => {
      card.style.transition = 'all 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, 100 + (index * 100));
  });
  
  // Effet de hover amélioré pour les timeline items
  const timelineContents = document.querySelectorAll('.timeline-content');
  timelineContents.forEach(content => {
    content.addEventListener('mouseenter', function() {
      this.style.transform = 'scale(1.02)';
    });
    
    content.addEventListener('mouseleave', function() {
      this.style.transform = 'scale(1)';
    });
  });
  
  // Auto-submit du formulaire de filtres avec debounce
  let filterTimeout;
  const filterInputs = document.querySelectorAll('#recherche, #type, #urgence, #statut, #niveau_hierarchique, #date_debut, #date_fin, #ordre');
  
  filterInputs.forEach(input => {
    input.addEventListener('input', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 500); // 500ms de délai
    });
    
    input.addEventListener('change', function() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        if (this.form) {
          this.form.submit();
        }
      }, 200); // Délai plus court pour les selects
    });
  });
  
  // Compteur animé pour les statistiques
  const statNumbers = document.querySelectorAll('.stat-number');
  statNumbers.forEach(number => {
    const text = number.textContent;
    const value = parseFloat(text);
    
    if (!isNaN(value) && value > 0) {
      let current = 0;
      const increment = Math.ceil(value / 20);
      const suffix = text.replace(value.toString(), '');
      
      const timer = setInterval(() => {
        current += increment;
        if (current >= value) {
          current = value;
          clearInterval(timer);
        }
        
        number.textContent = Math.floor(current) + suffix;
      }, 50);
    }
  });
  
  // Marquer automatiquement les notifications non lues comme lues après 3 secondes
  const notificationsNonLues = document.querySelectorAll('.timeline-content.non-lue');
  notificationsNonLues.forEach(notification => {
    const notificationId = notification.closest('.notification-item').dataset.notificationId;
    
    setTimeout(() => {
      // Marquer visuellement comme lue
      notification.classList.remove('non-lue');
      notification.style.background = 'white';
      notification.style.animation = 'none';
      
      // Appel AJAX pour marquer comme lue côté serveur
      marquerNotificationLue(notificationId);
    }, 3000);
  });
  
  console.log('✅ Animations et interactions initialisées');
});

// Fonction pour marquer toutes les notifications comme lues
function marquerToutesLues() {
  const btn = event.target.closest('button') || event.target;
  const icon = btn.querySelector('i');
  const originalClass = icon.className;
  
  // Animation du bouton
  icon.className = 'fas fa-spinner fa-spin';
  btn.disabled = true;
  
  fetch('/interim/notifications/marquer-toutes-lues/', {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken(),
      'Content-Type': 'application/json',
    },
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      // Marquer visuellement toutes les notifications comme lues
      const notificationsNonLues = document.querySelectorAll('.timeline-content.non-lue');
      notificationsNonLues.forEach(notification => {
        notification.classList.remove('non-lue');
        notification.style.background = 'white';
        notification.style.animation = 'none';
      });
      
      // Mise à jour des badges
      const badges = document.querySelectorAll('.non-lues-badge');
      badges.forEach(badge => badge.style.display = 'none');
      
      // Notification de succès
      showNotification('success', data.message || 'Toutes les notifications ont été marquées comme lues');
      
      // Masquer le bouton
      btn.style.display = 'none';
      
    } else {
      showNotification('error', data.error || 'Erreur lors du marquage des notifications');
    }
  })
  .catch(error => {
    console.error('Erreur:', error);
    showNotification('error', 'Une erreur est survenue');
  })
  .finally(() => {
    // Restaurer le bouton
    icon.className = originalClass;
    btn.disabled = false;
  });
}

// Fonction pour exécuter une action sur une notification
function executerAction(url, method = 'GET') {
  if (method === 'POST') {
    fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken(),
        'Content-Type': 'application/json',
      },
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        showNotification('success', data.message || 'Action exécutée avec succès');
        
        // Recharger la page après un court délai
        setTimeout(() => {
          window.location.reload();
        }, 1500);
      } else {
        showNotification('error', data.error || 'Erreur lors de l\'exécution de l\'action');
      }
    })
    .catch(error => {
      console.error('Erreur:', error);
      showNotification('error', 'Une erreur est survenue');
    });
  } else {
    window.location.href = url;
  }
}

// Fonction pour marquer une notification individuelle comme lue
function marquerNotificationLue(notificationId) {
  fetch(`/interim/notifications/${notificationId}/marquer-lue/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken(),
      'Content-Type': 'application/json',
    },
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      console.log(`Notification ${notificationId} marquée comme lue`);
    }
  })
  .catch(error => {
    console.error('Erreur marquage notification:', error);
  });
}

// Fonction pour confirmer la suppression d'une notification
function confirmerSuppression(url) {
  if (confirm('Êtes-vous sûr de vouloir supprimer cette notification ? Cette action est irréversible.')) {
    executerAction(url, 'POST');
  }
}

// Fonction utilitaire pour obtenir le token CSRF
function getCsrfToken() {
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  if (csrfToken) {
    return csrfToken;
  }
  
  // Fallback: chercher dans les cookies
  const cookies = document.cookie.split(';');
  for (let cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'csrftoken') {
      return value;
    }
  }
  
  return '';
}

// Fonction pour afficher une notification toast
function showNotification(type, message, action = null) {
  const notification = document.createElement('div');
  notification.className = `notification-toast ${type}`;
  notification.style.position = 'fixed';
  notification.style.top = '20px';
  notification.style.right = '20px';
  notification.style.zIndex = '9999';
  notification.style.padding = '1rem 1.5rem';
  notification.style.borderRadius = '8px';
  notification.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
  notification.style.maxWidth = '400px';
  notification.style.fontSize = '0.9rem';
  notification.style.fontWeight = '500';
  notification.style.transform = 'translateX(100%)';
  notification.style.transition = 'transform 0.3s ease-in-out';
  notification.style.cursor = 'pointer';
  
  let bgColor, textColor, borderColor, icon;
  
  switch(type) {
    case 'success':
      bgColor = '#d4edda';
      textColor = '#155724';
      borderColor = '#c3e6cb';
      icon = 'fas fa-check-circle';
      break;
    case 'error':
      bgColor = '#f8d7da';
      textColor = '#721c24';
      borderColor = '#f5c6cb';
      icon = 'fas fa-exclamation-circle';
      break;
    case 'info':
      bgColor = '#d1ecf1';
      textColor = '#0c5460';
      borderColor = '#bee5eb';
      icon = 'fas fa-info-circle';
      break;
    case 'warning':
      bgColor = '#fff3cd';
      textColor = '#856404';
      borderColor = '#ffeaa7';
      icon = 'fas fa-exclamation-triangle';
      break;
  }
  
  notification.style.backgroundColor = bgColor;
  notification.style.color = textColor;
  notification.style.border = `1px solid ${borderColor}`;
  notification.innerHTML = `<i class="${icon}"></i> ${message}`;
  
  if (action) {
    notification.innerHTML += '<br><small>Cliquez pour actualiser</small>';
  }
  
  document.body.appendChild(notification);
  
  // Animation d'entrée
  setTimeout(() => {
    notification.style.transform = 'translateX(0)';
  }, 100);
  
  // Gestion du clic
  notification.addEventListener('click', () => {
    if (action) {
      action();
    }
    notification.style.transform = 'translateX(100%)';
    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 300);
  });
  
  // Suppression automatique
  setTimeout(() => {
    notification.style.transform = 'translateX(100%)';
    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 300);
  }, action ? 8000 : 4000); // Plus long si action disponible
}

// Fonction pour rafraîchir automatiquement le compteur de notifications
function rafraichirCompteurNotifications() {
  fetch('/interim/api/notifications/count-non-lues/')
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Mettre à jour les badges de compteur
        const badges = document.querySelectorAll('.non-lues-badge');
        badges.forEach(badge => {
          if (data.count > 0) {
            badge.textContent = `${data.count} non lue${data.count > 1 ? 's' : ''}`;
            badge.style.display = 'inline-block';
          } else {
            badge.style.display = 'none';
          }
        });
        
        // Mettre à jour le titre de la page
        if (data.count > 0) {
          document.title = `(${data.count}) Interim365 - BNI | Mes notifications`;
        } else {
          document.title = 'Interim365 - BNI | Mes notifications';
        }
      }
    })
    .catch(error => {
      console.log('Erreur rafraîchissement compteur:', error);
    });
}

// Fonction pour vérifier les nouvelles notifications
function verifierNouvellesNotifications() {
  const currentCount = document.querySelectorAll('.timeline-item').length;
  
  fetch('/interim/api/notifications/recentes/?limit=1')
    .then(response => response.json())
    .then(data => {
      if (data.success && data.notifications.length > 0) {
        const latestNotification = data.notifications[0];
        const latestDate = new Date(latestNotification.created_at);
        
        // Comparer avec la dernière notification affichée
        const firstTimeline = document.querySelector('.timeline-item');
        if (firstTimeline) {
          const firstNotifId = firstTimeline.dataset.notificationId;
          
          if (parseInt(latestNotification.id) > parseInt(firstNotifId)) {
            // Nouvelle notification détectée
            showNotification('info', 
              `Nouvelle notification: ${latestNotification.titre}`,
              () => window.location.reload()
            );
          }
        }
      }
    })
    .catch(error => {
      console.log('Erreur vérification nouvelles notifications:', error);
    });
}

// Démarrer la vérification automatique toutes les 30 secondes
setInterval(rafraichirCompteurNotifications, 30000);
setInterval(verifierNouvellesNotifications, 60000);

