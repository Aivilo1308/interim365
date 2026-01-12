  
    // Configuration globale adaptée
    const dashboardConfig = {
      refreshInterval: 300000, // 5 minutes
      apiBaseUrl: '{% url "index" %}',
      csrfToken: '{{ csrf_token }}'
    };

    // Données dynamiques du dashboard depuis la vue Python
    const dashboardData = {{ dashboard_data|safe }};

    // Menu mobile et dropdowns
    document.addEventListener('DOMContentLoaded', function() {
      const mobileMenuToggle = document.getElementById('mobileMenuToggle');
      const sidebar = document.getElementById('sidebar');
      let isMobile = window.innerWidth <= 768;

      // Détection du changement de taille d'écran
      window.addEventListener('resize', function() {
        const wasMobile = isMobile;
        isMobile = window.innerWidth <= 768;
        
        if (wasMobile !== isMobile) {
          // Fermer le menu mobile si on passe en desktop
          if (!isMobile && sidebar.classList.contains('active')) {
            closeMobileMenu();
          }
        }
      });

      // Fonction simple de toggle
      function toggleMobileMenu() {
        const isActive = sidebar.classList.contains('active');
        
        if (isActive) {
          closeMobileMenu();
        } else {
          // Ouvrir le menu
          sidebar.classList.add('active');
          mobileMenuToggle.innerHTML = '<i class="fas fa-times"></i>';
          document.body.style.overflow = 'hidden';
        }
      }

      // Gestion du menu mobile
      if (mobileMenuToggle) {
        mobileMenuToggle.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          toggleMobileMenu();
        });

        // Support tactile
        mobileMenuToggle.addEventListener('touchstart', function(e) {
          e.preventDefault();
          toggleMobileMenu();
        });
      }

      // Fermer le menu en cliquant ailleurs sur mobile
      document.addEventListener('click', function(event) {
        if (
          isMobile &&
          sidebar.classList.contains('active') &&
          !sidebar.contains(event.target) && 
          event.target !== mobileMenuToggle && 
          !mobileMenuToggle.contains(event.target)
        ) {
          closeMobileMenu();
        }
      });

      // Fermer avec Escape
      document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
          if (isMobile && sidebar.classList.contains('active')) {
            closeMobileMenu();
          }
        }
      });

      function closeMobileMenu() {
        sidebar.classList.remove('active');
        mobileMenuToggle.innerHTML = '<i class="fas fa-bars"></i>';
        document.body.style.overflow = '';
      }

      // Auto-refresh si configuré et services disponibles
      if (dashboardConfig.refreshInterval > 0 && dashboardData.services_available) {
        setInterval(refreshDashboard, dashboardConfig.refreshInterval);
      }
    });

    // Fonctions de gestion des notifications
    function closeNotification(button) {
      const notification = button.closest('.notification');
      notification.style.transform = 'translateX(100%)';
      notification.style.opacity = '0';
      setTimeout(() => {
        notification.remove();
      }, 300);
    }

    function showNotification(message, type = 'info', action = null) {
      const container = document.getElementById('notificationsContainer') || createNotificationContainer();
      
      const notification = document.createElement('div');
      notification.className = `notification ${type}`;
      
      const iconClass = {
        'info': 'fas fa-info-circle',
        'success': 'fas fa-check-circle',
        'warning': 'fas fa-exclamation-triangle',
        'error': 'fas fa-exclamation-circle'
      }[type] || 'fas fa-info-circle';
      
      notification.innerHTML = `
        <div class="icon">
          <i class="${iconClass}"></i>
        </div>
        <div class="content">
          <div class="message">${message}</div>
          ${action ? `<div class="action"><a href="${action.url}">${action.text}</a></div>` : ''}
        </div>
        <button class="close" onclick="closeNotification(this)">
          <i class="fas fa-times"></i>
        </button>
      `;
      
      container.appendChild(notification);
      
      // Auto-fermeture après 5 secondes
      setTimeout(() => {
        if (notification.parentNode) {
          closeNotification(notification.querySelector('.close'));
        }
      }, 5000);
    }

    function createNotificationContainer() {
      const container = document.createElement('div');
      container.className = 'notifications-container';
      container.id = 'notificationsContainer';
      document.body.appendChild(container);
      return container;
    }

    // Fonctions de rafraîchissement
    async function refreshDashboard() {
      const refreshBtn = document.getElementById('refreshBtn');
      refreshBtn.classList.add('spinning');
      
      try {
        const response = await fetch('#', {
          method: 'GET',
          headers: {
            'X-CSRFToken': dashboardConfig.csrfToken,
            'Content-Type': 'application/json'
          }
        });
        
        if (response.ok) {
          const data = await response.json();
          if (data.success) {
            updateStats(data.stats);
            showNotification('Données mises à jour', 'success');
          } else {
            throw new Error(data.error || 'Erreur lors du rafraîchissement');
          }
        } else {
          throw new Error('Erreur lors du rafraîchissement');
        }
      } catch (error) {
        console.error('Erreur refresh:', error);
        showNotification('Erreur lors de la mise à jour', 'error');
      } finally {
        refreshBtn.classList.remove('spinning');
      }
    }

    function updateStats(stats) {
      if (stats) {
        const elements = {
          'interims-en-cours': stats.interims_en_cours || 0,
          'taux-validation': (stats.taux_validation || 0) + '%',
          'demandes-en-attente': stats.demandes_en_attente || 0,
          'remplacements-urgents': stats.remplacements_urgents || 0
        };
        
        Object.entries(elements).forEach(([id, value]) => {
          const element = document.getElementById(id);
          if (element) {
            element.textContent = value;
          }
        });
      }
    }

    async function loadNotifications() {
      try {
        const response = await fetch('#', {
          method: 'GET',
          headers: {
            'X-CSRFToken': dashboardConfig.csrfToken,
            'Content-Type': 'application/json'
          }
        });
        
        if (response.ok) {
          const data = await response.json();
          
          // Effacer les notifications existantes
          const container = document.getElementById('notificationsContainer');
          if (container) {
            container.innerHTML = '';
          }
          
          // Afficher les nouvelles notifications
          if (data.notifications && data.notifications.length > 0) {
            data.notifications.forEach(notification => {
              showNotification(
                notification.message, 
                notification.type,
                notification.action_url ? {
                  url: notification.action_url,
                  text: notification.action_text || 'Voir'
                } : null
              );
            });
          } else {
            showNotification('Aucune nouvelle notification', 'info');
          }
        }
      } catch (error) {
        console.error('Erreur chargement notifications:', error);
        showNotification('Erreur lors du chargement des notifications', 'error');
      }
    }

    // Fonctions utilitaires
    function filterTable() {
      showNotification('Fonction de filtrage en développement', 'info');
    }

    function exportData() {
      showNotification('Fonction d\'export en développement', 'info');
    }

    // Initialisation finale
    document.addEventListener('DOMContentLoaded', function() {
      // Ajouter des gestionnaires d'événements pour les cartes statistiques
      const statCards = document.querySelectorAll('.stat-card[onclick]');
      statCards.forEach(card => {
        card.style.cursor = 'pointer';
      });

      // Initialiser le tri des tableaux
      const tableHeaders = document.querySelectorAll('th');
      tableHeaders.forEach(header => {
        header.style.cursor = 'pointer';
        header.addEventListener('click', function() {
          showNotification('Tri en cours de développement', 'info');
        });
      });

      // Afficher un message de bienvenue si c'est la première visite
      if (dashboardData.user_role === 'UTILISATEUR' && !localStorage.getItem('welcome_shown')) {
        setTimeout(() => {
          showNotification('Bienvenue dans le système d\'intérim Interim365 - BNI', 'success');
          localStorage.setItem('welcome_shown', 'true');
        }, 1000);
      }
    });

    // Gestion des erreurs globales
    window.addEventListener('error', function(event) {
      console.error('Erreur JavaScript:', event.error);
      showNotification('Une erreur est survenue', 'error');
    });

    window.addEventListener('unhandledrejection', function(event) {
      console.error('Erreur de promesse non gérée:', event.reason);
      showNotification('Erreur de connexion', 'error');
    });
  
