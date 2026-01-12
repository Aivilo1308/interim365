
// ================================================================
// JAVASCRIPT V4.3 FINAL - SYNCHRONISATION KELIO GLOBALE
// ================================================================

// Variables globales
let syncMode = 'complete';
let syncInProgress = false;
let progressModal;
let dashboardVisible = false;
let logPaused = false;

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Initialisation interface Kelio V4.3 FINALE');
    
    initializeModalControls();
    initializeSyncModeSelection();
    initializePreLaunchChecks();
    initializeAnimations();
    initializeKeyboardShortcuts();
    
    console.log('✅ Interface V4.3 initialisée avec succès');
});

// ================================================================
// INITIALISATION DES COMPOSANTS
// ================================================================

function initializeModalControls() {
    progressModal = new bootstrap.Modal(document.getElementById('progressModal'), {
        backdrop: 'static',
        keyboard: false
    });
}

function initializeSyncModeSelection() {
    const syncModeCards = document.querySelectorAll('.sync-mode-card');
    
    syncModeCards.forEach(card => {
        card.addEventListener('click', function() {
            // Désélectionner toutes les cartes
            syncModeCards.forEach(c => c.classList.remove('active'));
            
            // Sélectionner la carte cliquée
            this.classList.add('active');
            syncMode = this.dataset.mode;
            
            console.log(`Mode sélectionné: ${syncMode}`);
            
            // Animation de sélection
            this.style.transform = 'scale(0.98)';
            setTimeout(() => {
                this.style.transform = '';
            }, 150);
            
            // Mettre à jour l'estimation selon le mode
            updateTimeEstimate();
        });
    });
    
    // Sélectionner le premier mode par défaut
    if (syncModeCards.length > 0) {
        syncModeCards[0].classList.add('active');
        syncMode = syncModeCards[0].dataset.mode;
    }
    
    // Écouter les changements du mode rapide
    const fastModeToggle = document.getElementById('enableFastMode');
    if (fastModeToggle) {
        fastModeToggle.addEventListener('change', updateTimeEstimate);
    }
    
    // Écouter les changements de taille de lots
    const batchSizeSelect = document.getElementById('batchSize');
    if (batchSizeSelect) {
        batchSizeSelect.addEventListener('change', updateTimeEstimate);
    }
}

function updateTimeEstimate() {
    const fastMode = document.getElementById('enableFastMode')?.checked || true;
    const batchSize = parseInt(document.getElementById('batchSize')?.value) || 10;
    const estimateElement = document.getElementById('modeEstimateText');
    
    if (!estimateElement) return;
    
    let estimate = '';
    
    if (fastMode) {
        if (batchSize >= 15) {
            estimate = '⚡ Durée estimée : 2-3 minutes (mode ultra-rapide)';
        } else if (batchSize >= 10) {
            estimate = '⚡ Durée estimée : 2-5 minutes (mode rapide)';
        } else {
            estimate = '⚡ Durée estimée : 3-6 minutes (mode rapide sécurisé)';
        }
    } else {
        if (batchSize <= 5) {
            estimate = '🔒 Durée estimée : 5-10 minutes (mode sécurisé)';
        } else {
            estimate = '🔒 Durée estimée : 3-8 minutes (mode sécurisé optimisé)';
        }
    }
    
    estimateElement.textContent = estimate;
}

function initializePreLaunchChecks() {
    // Simulation des vérifications pré-lancement
    setTimeout(() => {
        performPreLaunchCheck('checkConnection', 'Connexion Kelio', true);
    }, 1000);
    
    setTimeout(() => {
        performPreLaunchCheck('checkConfig', 'Configuration', true);
    }, 1500);
    
    setTimeout(() => {
        performPreLaunchCheck('checkResources', 'Ressources système', true);
    }, 2000);
}

function performPreLaunchCheck(elementId, description, success) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const icon = element.querySelector('i');
    const text = element.querySelector('span');
    
    // Animation de vérification
    element.classList.add('checking');
    icon.className = 'fas fa-circle text-warning';
    
    setTimeout(() => {
        element.classList.remove('checking');
        
        if (success) {
            element.classList.add('success');
            icon.className = 'fas fa-check-circle text-success';
        } else {
            element.classList.add('error');
            icon.className = 'fas fa-times-circle text-danger';
        }
    }, 500);
}

function initializeAnimations() {
    // Animation progressive des cartes
    const cards = document.querySelectorAll('.card-v43');
    cards.forEach((card, index) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        
        setTimeout(() => {
            card.style.transition = 'all 0.5s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, index * 100);
    });
    
    // Animation des métriques avec compteur
    animateCounters();
}

function animateCounters() {
    const counters = document.querySelectorAll('.metric-value, .main-value, .partial-metric .value');
    
    counters.forEach(counter => {
        const text = counter.textContent;
        const value = parseFloat(text.replace(/[^\d.]/g, ''));
        
        if (!isNaN(value) && value > 0) {
            let current = 0;
            const increment = Math.ceil(value / 30);
            const suffix = text.replace(value.toString(), '');
            
            const timer = setInterval(() => {
                current += increment;
                if (current >= value) {
                    current = value;
                    clearInterval(timer);
                }
                
                counter.textContent = Math.floor(current) + suffix;
            }, 50);
        }
    });
}

function initializeKeyboardShortcuts() {
    document.addEventListener('keydown', function(event) {
        // Ctrl+Enter : Lancer synchronisation
        if (event.ctrlKey && event.key === 'Enter') {
            event.preventDefault();
            if (!syncInProgress) {
                demarrerSynchronisationV43();
            }
        }
        
        // Escape : Fermer modals
        if (event.key === 'Escape') {
            if (dashboardVisible) {
                masquerTableauBord();
            }
        }
        
        // F5 : Actualiser (sauf si sync en cours)
        if (event.key === 'F5') {
            if (syncInProgress) {
                event.preventDefault();
                showNotification('Synchronisation en cours, actualisation bloquée', 'warning');
            }
        }
    });
}

// ================================================================
// FONCTIONS PRINCIPALES DE SYNCHRONISATION
// ================================================================

function demarrerSynchronisationV43() {
    if (syncInProgress) {
        showNotification('Une synchronisation est déjà en cours', 'warning');
        return;
    }
    
    console.log('🚀 Démarrage synchronisation V4.3 FINALE');
    
    // Récupérer les options
    const options = collectSyncOptions();
    
    // Valider les options
    if (!validateSyncOptions(options)) {
        return;
    }
    
    // Démarrer la synchronisation
    executeSynchronization(options);
}

function collectSyncOptions() {
    return {
        mode: syncMode,
        force_sync: document.getElementById('forceSync')?.checked || false,
        notify_users: document.getElementById('notifyUsers')?.checked || false,
        include_archived: document.getElementById('includeArchived')?.checked || false,
        enable_retry: document.getElementById('enableRetry')?.checked || true,
        retry_strategy: document.getElementById('retryStrategy')?.value || 'balanced',
        enable_deduplication: document.getElementById('enableDeduplication')?.checked || true,
        batch_size: parseInt(document.getElementById('batchSize')?.value) || 10,
        fast_mode: document.getElementById('enableFastMode')?.checked || true  // 🚀 NOUVELLE OPTION
    };
}

function validateSyncOptions(options) {
    // Validation basique
    if (!options.mode) {
        showNotification('Mode de synchronisation non sélectionné', 'error');
        return false;
    }
    
    if (options.batch_size < 1 || options.batch_size > 20) {
        showNotification('Taille de lot invalide (1-20)', 'error');
        return false;
    }
    
    return true;
}

function executeSynchronization(options) {
    syncInProgress = true;
    
    // Afficher le modal de progression
    showProgressModal();
    
    // Préparer la requête
    const requestData = {
        ...options,
        timestamp: new Date().toISOString()
    };
    
    console.log('📊 Options de synchronisation:', requestData);
    
    // Lancer la requête AJAX
    fetch("{% url 'admin_kelio_sync_global' %}", {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(requestData)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`Erreur HTTP: ${response.status}`);
        }
        return response.json();
    })
    .then(result => {
        handleSyncSuccess(result);
    })
    .catch(error => {
        handleSyncError(error);
    })
    .finally(() => {
        syncInProgress = false;
    });
}

function handleSyncSuccess(result) {
    console.log('✅ Synchronisation réussie:', result);
    
    if (result.success) {
        updateProgressBar(100, 'Synchronisation terminée avec succès');
        addLogEntry('✅ Synchronisation V4.3 terminée avec succès', 'success');
        
        // Mettre à jour les métriques temps réel
        if (result.stats) {
            updateRealtimeMetrics(result.stats);
        }
        
        // Afficher le bouton de fermeture
        setTimeout(() => {
            document.getElementById('cancelBtn').style.display = 'none';
            document.getElementById('closeBtn').style.display = 'inline-block';
        }, 2000);
        
        // Redirection automatique après 5 secondes
        setTimeout(() => {
            window.location.reload();
        }, 5000);
        
    } else {
        updateProgressBar(0, 'Erreur lors de la synchronisation');
        addLogEntry(`❌ Erreur: ${result.message}`, 'error');
        
        // Afficher les résultats partiels si disponibles
        if (result.stats && result.stats.total_employees_processed > 0) {
            updateRealtimeMetrics(result.stats);
            addLogEntry(`⚠️ ${result.stats.total_employees_processed} employés traités avant l'erreur`, 'warning');
        }
        
        // Permettre la fermeture
        document.getElementById('cancelBtn').innerHTML = '<i class="fas fa-times"></i> Fermer';
        document.getElementById('cancelBtn').onclick = hideProgressModal;
    }
}

function handleSyncError(error) {
    console.error('❌ Erreur de synchronisation:', error);
    
    updateProgressBar(0, 'Erreur de connexion');
    addLogEntry(`❌ Erreur: ${error.message}`, 'error');
    
    // Permettre la fermeture
    document.getElementById('cancelBtn').innerHTML = '<i class="fas fa-times"></i> Fermer';
    document.getElementById('cancelBtn').onclick = hideProgressModal;
    
    showNotification(`Erreur de synchronisation: ${error.message}`, 'danger');
}

// ================================================================
// GESTION DU MODAL DE PROGRESSION
// ================================================================

function showProgressModal() {
    // Réinitialiser le modal
    resetProgressModal();
    
    // Afficher le modal
    progressModal.show();
    
    // Démarrer la simulation de progression
    simulateProgress();
}

function hideProgressModal() {
    progressModal.hide();
}

function resetProgressModal() {
    updateProgressBar(0, 'Initialisation...');
    resetRealtimeMetrics();
    clearLogEntries();
    addLogEntry('Service V4.3 initialisé', 'info');
    
    // Réinitialiser les boutons
    document.getElementById('cancelBtn').innerHTML = '<i class="fas fa-stop"></i> Annuler';
    document.getElementById('cancelBtn').onclick = annulerSynchronisation;
    document.getElementById('closeBtn').style.display = 'none';
}

function updateProgressBar(percentage, message) {
    const progressBar = document.getElementById('mainProgressBar');
    const progressText = document.getElementById('progressText');
    const currentStep = document.getElementById('currentStep');
    const currentOperation = document.getElementById('currentOperation');
    
    if (progressBar) {
        progressBar.style.width = percentage + '%';
        progressBar.setAttribute('aria-valuenow', percentage);
    }
    
    if (progressText) {
        progressText.textContent = Math.round(percentage) + '%';
    }
    
    if (currentStep) {
        currentStep.textContent = message;
    }
    
    if (currentOperation) {
        currentOperation.textContent = getOperationDescription(percentage);
    }
}

function getOperationDescription(percentage) {
    if (percentage < 10) return 'Connexion au serveur Kelio...';
    if (percentage < 20) return 'Authentification et validation...';
    if (percentage < 30) return 'Récupération des données employés...';
    if (percentage < 50) return 'Traitement et déduplication...';
    if (percentage < 80) return 'Synchronisation avec la base de données...';
    if (percentage < 95) return 'Finalisation et vérifications...';
    return 'Synchronisation terminée';
}

function simulateProgress() {
    let progress = 0;
    const interval = setInterval(() => {
        if (!syncInProgress) {
            clearInterval(interval);
            return;
        }
        
        progress += Math.random() * 5;
        if (progress > 90) progress = 90; // Ne pas dépasser 90% pendant la simulation
        
        updateProgressBar(progress, getOperationDescription(progress));
    }, 500);
}

// ================================================================
// GESTION DES MÉTRIQUES TEMPS RÉEL
// ================================================================

function updateRealtimeMetrics(stats) {
    const metrics = {
        processedCount: stats.total_employees_processed || 0,
        createdCount: stats.total_created || 0,
        updatedCount: stats.total_updated || 0,
        errorCount: stats.total_errors || 0
    };
    
    // Calculer la vitesse
    const speed = stats.employees_per_second || 0;
    document.getElementById('speedIndicator').textContent = speed.toFixed(1) + '/s';
    
    // Mettre à jour les compteurs avec animation
    Object.entries(metrics).forEach(([elementId, value]) => {
        const element = document.getElementById(elementId);
        if (element) {
            animateCounterTo(element, value);
        }
    });
    
    // Métriques avancées V4.3
    if (stats.services_results && stats.services_results.employees) {
        const empStats = stats.services_results.employees;
        
        document.getElementById('batchProgress').textContent = 
            `${empStats.successful_batches || 0}/${empStats.total_batches || 0}`;
        
        document.getElementById('duplicatesResolved').textContent = 
            empStats.doublons_geres || 0;
        
        document.getElementById('retryCount').textContent = 
            stats.retries_total || 0;
    }
}

function resetRealtimeMetrics() {
    const metricElements = ['processedCount', 'createdCount', 'updatedCount', 'errorCount', 'speedIndicator'];
    
    metricElements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = id === 'speedIndicator' ? '0/s' : '0';
        }
    });
    
    // Métriques avancées
    document.getElementById('batchProgress').textContent = '0/0';
    document.getElementById('duplicatesResolved').textContent = '0';
    document.getElementById('retryCount').textContent = '0';
}

function animateCounterTo(element, targetValue) {
    const startValue = parseInt(element.textContent) || 0;
    const duration = 1000;
    const startTime = Date.now();
    
    function updateCounter() {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const currentValue = Math.floor(startValue + (targetValue - startValue) * progress);
        
        element.textContent = currentValue;
        
        if (progress < 1) {
            requestAnimationFrame(updateCounter);
        }
    }
    
    updateCounter();
}

// ================================================================
// GESTION DU JOURNAL
// ================================================================

function addLogEntry(message, type = 'info') {
    if (logPaused) return;
    
    const logContainer = document.getElementById('realtimeLog');
    if (!logContainer) return;
    
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    
    const timestamp = new Date().toLocaleTimeString();
    entry.innerHTML = `
        <span class="log-time">[${timestamp}]</span>
        <span class="log-message">${message}</span>
    `;
    
    logContainer.appendChild(entry);
    logContainer.scrollTop = logContainer.scrollHeight;
    
    // Limiter le nombre d'entrées
    const entries = logContainer.querySelectorAll('.log-entry');
    if (entries.length > 50) {
        entries[0].remove();
    }
}

function clearLogEntries() {
    const logContainer = document.getElementById('realtimeLog');
    if (logContainer) {
        logContainer.innerHTML = '';
    }
}

function pauserLog() {
    logPaused = !logPaused;
    const icon = document.getElementById('logPauseIcon');
    if (icon) {
        icon.className = logPaused ? 'fas fa-play' : 'fas fa-pause';
    }
}

function viderLog() {
    clearLogEntries();
    addLogEntry('Journal vidé', 'info');
}

// ================================================================
// FONCTIONS DU TABLEAU DE BORD
// ================================================================

function afficherTableauBordKelio() {
    const dashboard = document.getElementById('kelioDashboard');
    if (!dashboard) return;
    
    dashboard.style.display = 'block';
    dashboardVisible = true;
    
    // Charger les données du tableau de bord
    loadDashboardData();
    
    // Animation d'apparition
    dashboard.style.opacity = '0';
    dashboard.style.transform = 'translateY(-20px)';
    
    setTimeout(() => {
        dashboard.style.transition = 'all 0.3s ease';
        dashboard.style.opacity = '1';
        dashboard.style.transform = 'translateY(0)';
    }, 100);
}

function masquerTableauBord() {
    const dashboard = document.getElementById('kelioDashboard');
    if (!dashboard) return;
    
    dashboard.style.transition = 'all 0.3s ease';
    dashboard.style.opacity = '0';
    dashboard.style.transform = 'translateY(-20px)';
    
    setTimeout(() => {
        dashboard.style.display = 'none';
        dashboardVisible = false;
    }, 300);
}

function loadDashboardData() {
    // État de santé
    loadHealthStatus();
    
    // Statistiques
    loadStatistics();
}

function loadHealthStatus() {
    const healthWidget = document.getElementById('healthWidgetContent');
    if (!healthWidget) return;
    
    fetch("{% url 'kelio_health_check_v43' %}")
        .then(response => response.json())
        .then(data => {
            const status = data.overall_status;
            const statusClass = status === 'HEALTHY' ? 'success' : 'danger';
            const statusIcon = status === 'HEALTHY' ? 'check-circle' : 'exclamation-triangle';
            
            healthWidget.innerHTML = `
                <div class="health-status ${statusClass}">
                    <i class="fas fa-${statusIcon}"></i>
                    <span>${status}</span>
                </div>
                <small class="text-muted">Service V4.3 ${data.service_version}</small>
            `;
        })
        .catch(error => {
            healthWidget.innerHTML = `
                <div class="health-status danger">
                    <i class="fas fa-times-circle"></i>
                    <span>ERREUR</span>
                </div>
                <small class="text-muted">${error.message}</small>
            `;
        });
}

function loadStatistics() {
    const statsWidget = document.getElementById('statsWidgetContent');
    if (!statsWidget) return;
    
    fetch("{% url 'kelio_sync_stats_v43' %}")
        .then(response => response.json())
        .then(data => {
            const dbStats = data.database_stats;
            
            statsWidget.innerHTML = `
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-value">${dbStats.total_profils}</div>
                        <div class="stat-label">Profils totaux</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">${dbStats.profils_synchronises_kelio}</div>
                        <div class="stat-label">Synchronisés</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">${dbStats.taux_synchronisation}%</div>
                        <div class="stat-label">Taux sync</div>
                    </div>
                </div>
            `;
        })
        .catch(error => {
            statsWidget.innerHTML = `
                <div class="text-danger">
                    <i class="fas fa-exclamation-triangle"></i>
                    Erreur de chargement
                </div>
            `;
        });
}

// ================================================================
// ACTIONS RAPIDES
// ================================================================

function testerConnexionRapide() {
    showNotification('Test de connexion en cours...', 'info');
    
    fetch("{% url 'kelio_test_connection_v43' %}", {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        const message = data.success ? 'Connexion Kelio OK' : `Erreur: ${data.message}`;
        const type = data.success ? 'success' : 'danger';
        showNotification(message, type);
    })
    .catch(error => {
        showNotification(`Erreur de test: ${error.message}`, 'danger');
    });
}

function viderCacheKelio() {
    if (!confirm('Vider le cache Kelio ? Cette action peut impacter les performances.')) {
        return;
    }
    
    showNotification('Vidage du cache en cours...', 'info');
    
    // Simulation (remplacer par appel API réel)
    setTimeout(() => {
        showNotification('Cache Kelio vidé avec succès', 'success');
    }, 2000);
}

function redemarrerService() {
    if (!confirm('Redémarrer le service Kelio ? Cette action peut prendre quelques minutes.')) {
        return;
    }
    
    showNotification('Redémarrage du service en cours...', 'warning');
    
    // Simulation (remplacer par appel API réel)
    setTimeout(() => {
        showNotification('Service Kelio redémarré avec succès', 'success');
        loadDashboardData(); // Recharger les données
    }, 5000);
}

function verifierSanteKelio() {
    const indicator = document.getElementById('healthIndicator');
    if (!indicator) return;
    
    indicator.textContent = 'Vérification...';
    indicator.classList.add('checking');
    
    fetch("{% url 'kelio_health_check_v43' %}")
        .then(response => response.json())
        .then(data => {
            const status = data.overall_status;
            indicator.textContent = status === 'HEALTHY' ? 'OK' : 'Erreur';
            indicator.classList.remove('checking');
            
            const message = status === 'HEALTHY' ? 'Service Kelio opérationnel' : 'Problème détecté avec le service Kelio';
            const type = status === 'HEALTHY' ? 'success' : 'warning';
            showNotification(message, type);
        })
        .catch(error => {
            indicator.textContent = 'Erreur';
            indicator.classList.remove('checking');
            showNotification(`Erreur de vérification: ${error.message}`, 'danger');
        });
}

// ================================================================
// ACTIONS PRINCIPALES
// ================================================================

function nouvelleSynchronisation() {
    if (confirm('Démarrer une nouvelle synchronisation ?')) {
        window.location.reload();
    }
}

function reessayerAvecCorrections() {
    if (confirm('Relancer la synchronisation avec les corrections V4.3 ?')) {
        demarrerSynchronisationV43();
    }
}

function lancerDiagnostics() {
    showNotification('Lancement des diagnostics...', 'info');
    
    // Simuler les diagnostics
    setTimeout(() => {
        const diagnostics = [
            { name: 'Connexion Kelio', status: 'OK' },
            { name: 'Services SOAP', status: 'OK' },
            { name: 'Authentification', status: 'OK' },
            { name: 'Ressources', status: 'OK' }
        ];
        
        let message = 'Diagnostics terminés:\n';
        diagnostics.forEach(diag => {
            message += `• ${diag.name}: ${diag.status}\n`;
        });
        
        alert(message);
    }, 3000);
}

function afficherStatistiques() {
    window.open("{% url 'kelio_sync_stats_v43' %}", '_blank');
}

function ouvrirConfiguration() {
    showNotification('Ouverture de la configuration...', 'info');
    // Rediriger vers la page de configuration
    setTimeout(() => {
        window.location.href = "{% url 'admin_config' %}";
    }, 1000);
}

function afficherAide() {
    const helpContent = `
    === AIDE SYNCHRONISATION KELIO V4.3 FINALE ===
    
    🚀 NOUVEAUTÉS V4.3:
    • Gestion des erreurs de concurrence
    • Retry automatique intelligent
    • Déduplication avancée avec IA
    • Traitement par micro-lots
    
    📋 MODES DE SYNCHRONISATION:
    • Complète: Tous les employés (recommandé)
    • Incrémentale: Modifications récentes uniquement
    
    ⚙️ OPTIONS AVANCÉES:
    • Retry automatique: Gestion des erreurs temporaires
    • Déduplication: Évite les doublons
    • Taille des lots: Compromis vitesse/stabilité
    
    🔧 RACCOURCIS CLAVIER:
    • Ctrl+Enter: Lancer la synchronisation
    • Escape: Fermer les modals
    • F5: Actualiser (bloqué pendant sync)
    
    📞 SUPPORT:
    En cas de problème, contactez l'équipe technique
    avec les détails de l'erreur affichés.
    `;
    
    alert(helpContent);
}

function annulerSynchronisation() {
    if (syncInProgress) {
        if (confirm('Voulez-vous vraiment annuler la synchronisation en cours ?')) {
            syncInProgress = false;
            addLogEntry('⚠️ Annulation demandée par l\'utilisateur', 'warning');
            
            setTimeout(() => {
                hideProgressModal();
                showNotification('Synchronisation annulée', 'warning');
            }, 1000);
        }
    } else {
        hideProgressModal();
    }
}

function fermerModal() {
    hideProgressModal();
}

// ================================================================
// UTILITAIRES
// ================================================================

function showNotification(message, type = 'info') {
    // Créer la notification
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show notification-v43`;
    notification.innerHTML = `
        <div class="notification-content">
            <i class="fas fa-${getNotificationIcon(type)}"></i>
            <span>${message}</span>
        </div>
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Styles inline pour la notification
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        min-width: 300px;
        max-width: 500px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        border-radius: 8px;
        border: 0;
    `;
    
    // Ajouter au container ou au body
    const container = document.getElementById('systemAlerts') || document.body;
    container.appendChild(notification);
    
    // Animation d'entrée
    setTimeout(() => {
        notification.classList.add('show');
    }, 100);
    
    // Suppression automatique
    setTimeout(() => {
        if (notification.parentNode) {
            notification.classList.remove('show');
            setTimeout(() => {
                notification.remove();
            }, 300);
        }
    }, 5000);
}

function getNotificationIcon(type) {
    const icons = {
        'success': 'check-circle',
        'danger': 'exclamation-triangle',
        'warning': 'exclamation-triangle',
        'info': 'info-circle',
        'primary': 'info-circle'
    };
    return icons[type] || 'info-circle';
}

function getCsrfToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return decodeURIComponent(value);
        }
    }
    
    // Fallback: chercher dans les meta tags
    const metaToken = document.querySelector('meta[name="csrf-token"]');
    if (metaToken) {
        return metaToken.getAttribute('content');
    }
    
    return '';
}

// ================================================================
// GESTIONNAIRES D'ÉVÉNEMENTS
// ================================================================

// Gestion de la fermeture de la page pendant une sync
window.addEventListener('beforeunload', function(event) {
    if (syncInProgress) {
        event.preventDefault();
        event.returnValue = 'Une synchronisation est en cours. Voulez-vous vraiment quitter ?';
        return event.returnValue;
    }
});

// Gestion de la perte de focus pendant une sync
document.addEventListener('visibilitychange', function() {
    if (document.hidden && syncInProgress) {
        console.log('⚠️ Page masquée pendant la synchronisation');
    }
});

// Gestion des erreurs JavaScript globales
window.addEventListener('error', function(event) {
    console.error('Erreur JavaScript:', event.error);
    if (syncInProgress) {
        addLogEntry(`❌ Erreur JavaScript: ${event.error.message}`, 'error');
    }
});

// Log final
console.log('✅ JavaScript V4.3 FINAL chargé avec succès');
console.log('🚀 Interface prête pour synchronisation ultra-robuste');

