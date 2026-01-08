# -*- coding: utf-8 -*-
"""
Vue AJAX pour synchronisation GLOBALE depuis Kelio SafeSecur - VERSION CORRIGEE
Compatible avec kelio_api_simplifie.py V4.1

Fonctionnalités principales:
- Synchronisation complète des employés avec données périphériques
- Diagnostics détaillés des erreurs de connexion
- Support des modes: complete, employees_only, incremental
- Gestion d'erreurs robuste avec suggestions
- Interface AJAX et template HTML
"""

import json
import logging
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction

# Import des services Kelio
try:
    from .services.kelio_api_simplifie_modif import (
        get_kelio_sync_service_v41,
        KelioBaseError,
        KelioConnectionError,
        KelioEmployeeNotFoundError,
        KelioAuthenticationError,
        KelioDataError,
        KelioServiceUnavailableError,
        ConfigurationKeliomanquanteError,
        log_kelio_error
    )
    KELIO_SERVICE_AVAILABLE = True
except ImportError as e:
    KELIO_SERVICE_AVAILABLE = False
    print(f"WARNING: Service Kelio non disponible: {e}")

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET", "POST"])
@login_required
def ajax_update_kelio_global(request):
    """
    Vue principale pour synchronisation GLOBALE depuis Kelio SafeSecur
    
    GET: Affiche l'interface de synchronisation
    POST: Exécute la synchronisation avec diagnostics complets
    """
    
    # === GESTION GET - AFFICHAGE INTERFACE ===
    if request.method == 'GET':
        return render(request, 'global_update_from_kelio.html', {
            'result': None,
            'kelio_available': KELIO_SERVICE_AVAILABLE,
            'profil_utilisateur': getattr(request.user, 'profilutilisateur', None)
        })
    
    # === GESTION POST - SYNCHRONISATION ===
    
    # Initialisation de la structure de résultat
    result = _initialize_result_structure()
    
    # Déterminer le type de requête (AJAX ou formulaire)
    is_ajax = _is_ajax_request(request)
    
    try:
        logger.info("[KELIO-GLOBAL-SYNC] Début synchronisation globale Kelio V4.1")
        
        # Vérification de la disponibilité du service
        if not KELIO_SERVICE_AVAILABLE:
            result.update({
                'success': False,
                'message': 'Service Kelio non disponible sur ce serveur',
                'error_details': 'Module kelio_api_simplifie.py non importé correctement',
                'kelio_diagnostics': {
                    'potential_issues': [{
                        'type': 'SERVICE_UNAVAILABLE',
                        'description': 'Module Kelio non disponible',
                        'suggestion': 'Vérifiez l\'installation du module kelio_api_simplifie.py'
                    }]
                }
            })
            return _format_response(result, is_ajax, request)
        
        # Récupération et validation des paramètres
        sync_params = _extract_sync_parameters(request, is_ajax)
        if 'error' in sync_params:
            result.update(sync_params)
            return _format_response(result, is_ajax, request)
        
        # Mise à jour des paramètres dans le résultat
        result['stats']['sync_mode'] = sync_params['mode']
        
        logger.info(f"[KELIO-GLOBAL-SYNC] Mode: {sync_params['mode']}, Force: {sync_params['force_sync']}")
        
        # Exécution de la synchronisation
        sync_manager = KelioGlobalSyncManager(
            sync_mode=sync_params['mode'],
            force_sync=sync_params['force_sync'],
            notify_users=sync_params['notify_users'],
            include_archived=sync_params['include_archived'],
            requesting_user=request.user
        )
        
        # Lancement de la synchronisation
        sync_result = sync_manager.execute_global_sync()
        
        # Fusion des résultats
        result.update(sync_result)
        
        # Log final
        status = result.get('success', False)
        message = result.get('message', 'Inconnu')
        logger.info(f"[KELIO-GLOBAL-SYNC] Terminé - Succès: {status}, Message: {message}")
        
        return _format_response(result, is_ajax, request)
        
    except ConfigurationKeliomanquanteError as e:
        logger.error(f"[KELIO-GLOBAL-SYNC] Configuration manquante: {e}")
        result.update(_handle_configuration_error(e))
        return _format_response(result, is_ajax, request)
        
    except KelioConnectionError as e:
        logger.error(f"[KELIO-GLOBAL-SYNC] Erreur connexion: {e}")
        result.update(_handle_connection_error(e))
        return _format_response(result, is_ajax, request)
        
    except KelioServiceUnavailableError as e:
        logger.error(f"[KELIO-GLOBAL-SYNC] Service indisponible: {e}")
        result.update(_handle_service_unavailable_error(e))
        return _format_response(result, is_ajax, request)
        
    except Exception as e:
        logger.error(f"[KELIO-GLOBAL-SYNC] Erreur critique: {e}", exc_info=True)
        result.update(_handle_critical_error(e))
        return _format_response(result, is_ajax, request)


# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _initialize_result_structure():
    """Initialise la structure de résultat standard"""
    return {
        'success': False,
        'message': '',
        'data': {},
        'stats': {
            'total_employees_processed': 0,
            'total_created': 0,
            'total_updated': 0,
            'total_errors': 0,
            'duration_seconds': 0,
            'employees_per_second': 0,
            'services_results': {},
            'sync_mode': 'unknown',
            'started_at': timezone.now().isoformat(),
            'completed_at': None
        },
        'kelio_connection_info': {
            'config_status': 'NON_TESTEE',
            'config_details': {},
            'connection_status': 'NON_TENTEE',
            'connection_details': {},
            'service_initialization': {
                'status': 'NON_TENTEE',
                'service_version': None,
                'available_methods': [],
                'initialization_time_ms': 0,
                'error_details': None
            }
        },
        'kelio_api_calls': {
            'summary': {
                'total_calls': 0,
                'successful_calls': 0,
                'failed_calls': 0,
                'total_api_time_ms': 0,
                'average_response_time_ms': 0,
                'success_rate_percent': 0.0
            },
            'calls_details': []
        },
        'kelio_diagnostics': {
            'connection_info': {},
            'api_calls_attempted': {},
            'last_successful_call': None,
            'potential_issues': []
        },
        'error_details': None,
        'timestamp': timezone.now().isoformat()
    }

def _is_ajax_request(request):
    """Détermine si c'est une requête AJAX"""
    return (
        request.headers.get('Content-Type') == 'application/json' or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.content_type == 'application/json'
    )

def _extract_sync_parameters(request, is_ajax):
    """Extrait et valide les paramètres de synchronisation"""
    try:
        # Récupération des données selon le type de requête
        if is_ajax:
            try:
                data = json.loads(request.body.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return {
                    'error': True,
                    'success': False,
                    'message': 'Format JSON invalide',
                    'error_details': str(e)
                }
        else:
            data = request.POST.dict()
        
        # Extraction des paramètres avec valeurs par défaut
        sync_mode = data.get('mode', 'complete')
        force_sync = data.get('force_sync', True)
        notify_users = data.get('notify_users', False)
        include_archived = data.get('include_archived', False)
        
        # Conversion des valeurs string en boolean si nécessaire
        if isinstance(force_sync, str):
            force_sync = force_sync.lower() in ['true', '1', 'on', 'yes']
        if isinstance(notify_users, str):
            notify_users = notify_users.lower() in ['true', '1', 'on', 'yes']
        if isinstance(include_archived, str):
            include_archived = include_archived.lower() in ['true', '1', 'on', 'yes']
        
        # Validation du mode de synchronisation
        valid_modes = ['complete', 'employees_only', 'incremental']
        if sync_mode not in valid_modes:
            return {
                'error': True,
                'success': False,
                'message': f'Mode de synchronisation invalide: {sync_mode}',
                'error_details': f'Modes valides: {", ".join(valid_modes)}'
            }
        
        return {
            'mode': sync_mode,
            'force_sync': force_sync,
            'notify_users': notify_users,
            'include_archived': include_archived
        }
        
    except Exception as e:
        return {
            'error': True,
            'success': False,
            'message': 'Erreur extraction paramètres',
            'error_details': str(e)
        }

def _handle_configuration_error(error):
    """Gère les erreurs de configuration Kelio"""
    return {
        'success': False,
        'message': 'Configuration Kelio manquante ou invalide',
        'error_details': str(error),
        'kelio_connection_info': {
            'config_status': 'MANQUANTE_OU_INVALIDE',
            'service_initialization': {
                'status': 'CONFIG_ERROR',
                'error_details': str(error)
            }
        },
        'kelio_diagnostics': {
            'potential_issues': [{
                'type': 'CONFIGURATION_ISSUE',
                'description': f'Configuration Kelio manquante: {str(error)}',
                'suggestion': 'Vérifiez la configuration Kelio dans l\'administration Django'
            }]
        }
    }

def _handle_connection_error(error):
    """Gère les erreurs de connexion Kelio"""
    return {
        'success': False,
        'message': 'Impossible de se connecter à Kelio SafeSecur',
        'error_details': str(error),
        'kelio_connection_info': {
            'config_status': 'TESTEE',
            'connection_status': 'ECHEC',
            'connection_details': {
                'url': getattr(error, 'url', 'URL non spécifiée'),
                'timeout': getattr(error, 'timeout', 'Timeout non spécifié'),
                'service_name': getattr(error, 'service_name', 'Service non spécifié'),
                'error': str(error)
            }
        },
        'kelio_diagnostics': {
            'potential_issues': [{
                'type': 'CONNECTION_ISSUE',
                'description': f'Erreur de connexion au serveur Kelio: {str(error)}',
                'suggestion': 'Vérifiez la connectivité réseau et la disponibilité du serveur Kelio SafeSecur'
            }]
        }
    }

def _handle_service_unavailable_error(error):
    """Gère les erreurs de service indisponible"""
    return {
        'success': False,
        'message': 'Service Kelio SafeSecur temporairement indisponible',
        'error_details': str(error),
        'kelio_connection_info': {
            'config_status': 'OK',
            'connection_status': 'SERVICE_UNAVAILABLE',
            'service_initialization': {
                'status': 'SERVICE_UNAVAILABLE',
                'error_details': str(error)
            }
        },
        'kelio_diagnostics': {
            'potential_issues': [{
                'type': 'SERVICE_UNAVAILABLE',
                'description': f'Service Kelio temporairement indisponible: {str(error)}',
                'suggestion': 'Réessayez dans quelques minutes. Si le problème persiste, contactez l\'administrateur Kelio'
            }]
        }
    }

def _handle_critical_error(error):
    """Gère les erreurs critiques"""
    return {
        'success': False,
        'message': 'Erreur critique lors de la synchronisation globale',
        'error_details': str(error),
        'kelio_diagnostics': {
            'potential_issues': [{
                'type': 'CRITICAL_ERROR',
                'description': f'Erreur système critique: {str(error)}',
                'suggestion': 'Contactez l\'administrateur système avec les détails de cette erreur'
            }]
        }
    }

def _format_response(result, is_ajax, request):
    """Formate la réponse selon le type de requête"""
    try:
        # Finaliser les statistiques
        result['stats']['completed_at'] = timezone.now().isoformat()
        
        if is_ajax:
            return JsonResponse(result)
        else:
            # Préparer le contexte pour le template
            context = {
                'result': result,
                'kelio_available': KELIO_SERVICE_AVAILABLE,
                'profil_utilisateur': getattr(request.user, 'profilutilisateur', None)
            }
            return render(request, 'global_update_from_kelio.html', context)
            
    except Exception as e:
        logger.error(f"[KELIO-GLOBAL-SYNC] Erreur formatage réponse: {e}")
        error_response = {
            'success': False,
            'message': f'Erreur formatage réponse: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }
        
        if is_ajax:
            return JsonResponse(error_response, status=500)
        else:
            return render(request, 'global_update_from_kelio.html', {
                'result': error_response,
                'error': True
            })


# ================================================================
# CLASSE DE GESTION DE SYNCHRONISATION GLOBALE
# ================================================================

class KelioGlobalSyncManager:
    """
    Manager pour la synchronisation globale Kelio V4.1
    Gère les diagnostics, les appels API et les statistiques
    """
    
    def __init__(self, sync_mode='complete', force_sync=True, notify_users=False, 
                 include_archived=False, requesting_user=None):
        """Initialise le manager de synchronisation"""
        self.sync_mode = sync_mode
        self.force_sync = force_sync
        self.notify_users = notify_users
        self.include_archived = include_archived
        self.requesting_user = requesting_user
        
        # Diagnostics de connexion
        self.connection_diagnostics = {
            'config_status': 'NON_TESTEE',
            'config_details': {},
            'connection_status': 'NON_TENTEE',
            'connection_details': {},
            'service_initialization': {
                'status': 'NON_TENTEE',
                'service_version': None,
                'available_methods': [],
                'initialization_time_ms': 0,
                'error_details': None
            }
        }
        
        # Journal des appels API
        self.api_calls_log = {
            'summary': {
                'total_calls': 0,
                'successful_calls': 0,
                'failed_calls': 0,
                'total_api_time_ms': 0,
                'average_response_time_ms': 0,
                'success_rate_percent': 0.0
            },
            'calls_details': []
        }
        
        # Statistiques
        self.stats = {
            'total_employees_processed': 0,
            'total_created': 0,
            'total_updated': 0,
            'total_errors': 0,
            'duration_seconds': 0,
            'employees_per_second': 0,
            'services_results': {},
            'sync_mode': sync_mode,
            'started_at': timezone.now().isoformat(),
            'completed_at': None
        }
        
        self.kelio_service = None
        
        logger.info(f"[KELIO-SYNC-MANAGER] Initialisé pour mode {sync_mode}")
    
    def execute_global_sync(self):
        """Exécute la synchronisation globale avec diagnostics complets"""
        start_time = timezone.now()
        
        try:
            logger.info(f"[KELIO-SYNC-MANAGER] Début synchronisation globale {self.sync_mode}")
            
            # ÉTAPE 1: Configuration et initialisation du service Kelio
            if not self._setup_kelio_service():
                return self._create_error_response("Échec initialisation service Kelio")
            
            # ÉTAPE 2: Exécution de la synchronisation selon le mode
            sync_result = self._execute_sync_by_mode()
            
            # ÉTAPE 3: Finalisation des statistiques
            duration = (timezone.now() - start_time).total_seconds()
            self.stats['duration_seconds'] = duration
            self.stats['completed_at'] = timezone.now().isoformat()
            
            # Calcul de la vitesse de traitement
            if self.stats['total_employees_processed'] > 0 and duration > 0:
                self.stats['employees_per_second'] = round(
                    self.stats['total_employees_processed'] / duration, 2
                )
            
            # Finalisation des statistiques API
            self._finalize_api_statistics()
            
            logger.info(f"[KELIO-SYNC-MANAGER] Synchronisation terminée en {duration:.2f}s")
            
            return sync_result
            
        except Exception as e:
            duration = (timezone.now() - start_time).total_seconds()
            self.stats['duration_seconds'] = duration
            self.stats['completed_at'] = timezone.now().isoformat()
            
            logger.error(f"[KELIO-SYNC-MANAGER] Erreur synchronisation: {e}", exc_info=True)
            return self._create_error_response(f"Erreur synchronisation: {str(e)}", e)
    
    def _setup_kelio_service(self):
        """Configure et teste le service Kelio"""
        setup_start = timezone.now()
        
        try:
            logger.info("[KELIO-SYNC-MANAGER] Configuration service Kelio V4.1")
            self.connection_diagnostics['config_status'] = 'EN_COURS'
            
            # Initialisation du service
            self.kelio_service = get_kelio_sync_service_v41()
            
            if not self.kelio_service:
                self.connection_diagnostics['config_status'] = 'ECHEC'
                return False
            
            # Récupération des détails de configuration
            if hasattr(self.kelio_service, 'config'):
                config = self.kelio_service.config
                self.connection_diagnostics['config_details'] = {
                    'configuration_id': config.id,
                    'nom': config.nom,
                    'url_base': config.url_base,
                    'username': config.username,
                    'timeout_seconds': config.timeout_seconds,
                    'actif': config.actif
                }
            
            # Test de connexion
            self._test_connection()
            
            # Initialisation réussie
            setup_time = (timezone.now() - setup_start).total_seconds() * 1000
            self.connection_diagnostics['service_initialization'] = {
                'status': 'REUSSI',
                'service_version': 'V4.1',
                'service_class': self.kelio_service.__class__.__name__,
                'available_methods': [
                    method for method in dir(self.kelio_service) 
                    if not method.startswith('_') and callable(getattr(self.kelio_service, method))
                ],
                'initialization_time_ms': setup_time
            }
            
            self.connection_diagnostics['config_status'] = 'REUSSIE'
            logger.info(f"[KELIO-SYNC-MANAGER] Service Kelio V4.1 initialisé ({setup_time:.0f}ms)")
            
            return True
            
        except ConfigurationKeliomanquanteError as e:
            self.connection_diagnostics['config_status'] = 'MANQUANTE'
            self.connection_diagnostics['config_details']['error'] = str(e)
            logger.error(f"[KELIO-SYNC-MANAGER] Configuration manquante: {e}")
            raise
            
        except Exception as e:
            setup_time = (timezone.now() - setup_start).total_seconds() * 1000
            self.connection_diagnostics['config_status'] = 'ERREUR'
            self.connection_diagnostics['service_initialization'] = {
                'status': 'ERREUR',
                'error_details': str(e),
                'initialization_time_ms': setup_time
            }
            logger.error(f"[KELIO-SYNC-MANAGER] Erreur configuration: {e}")
            return False
    
    def _test_connection(self):
        """Teste la connexion au service Kelio"""
        connection_start = timezone.now()
        
        try:
            logger.info("[KELIO-SYNC-MANAGER] Test connexion Kelio")
            self.connection_diagnostics['connection_status'] = 'EN_COURS'
            
            # Test basique de connectivité
            if hasattr(self.kelio_service, '_create_session'):
                session = self.kelio_service._create_session()
                
                # Test de l'URL de base
                import requests
                from urllib.parse import urlparse
                
                parsed_url = urlparse(self.kelio_service.config.url_base)
                test_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                
                response = requests.get(
                    test_url, 
                    timeout=self.kelio_service.config.timeout_seconds,
                    verify=False
                )
                
                connection_time = (timezone.now() - connection_start).total_seconds() * 1000
                
                self.connection_diagnostics['connection_details'] = {
                    'target_host': parsed_url.netloc,
                    'response_status': response.status_code,
                    'response_time_ms': connection_time,
                    'connection_success': response.status_code in [200, 404, 403]
                }
                
                if response.status_code in [200, 404, 403]:
                    self.connection_diagnostics['connection_status'] = 'REUSSIE'
                    logger.info(f"[KELIO-SYNC-MANAGER] Connexion OK ({connection_time:.0f}ms)")
                else:
                    self.connection_diagnostics['connection_status'] = 'ECHEC_HTTP'
                    logger.warning(f"[KELIO-SYNC-MANAGER] Connexion suspecte: HTTP {response.status_code}")
            
        except Exception as e:
            connection_time = (timezone.now() - connection_start).total_seconds() * 1000
            self.connection_diagnostics['connection_status'] = 'ERREUR'
            self.connection_diagnostics['connection_details'] = {
                'error': str(e),
                'test_duration_ms': connection_time
            }
            logger.error(f"[KELIO-SYNC-MANAGER] Erreur test connexion: {e}")
    
    def _execute_sync_by_mode(self):
        """Exécute la synchronisation selon le mode choisi"""
        try:
            if self.sync_mode == 'complete':
                return self._execute_complete_sync()
            elif self.sync_mode == 'employees_only':
                return self._execute_employees_only_sync()
            elif self.sync_mode == 'incremental':
                return self._execute_incremental_sync()
            else:
                return self._create_error_response(f"Mode de synchronisation inconnu: {self.sync_mode}")
                
        except Exception as e:
            logger.error(f"[KELIO-SYNC-MANAGER] Erreur exécution sync {self.sync_mode}: {e}")
            return self._create_error_response(f"Erreur exécution {self.sync_mode}: {str(e)}")
    
    def _execute_complete_sync(self):
        """Exécute une synchronisation complète"""
        logger.info("[KELIO-SYNC-MANAGER] Synchronisation complète")
        
        api_call_start = timezone.now()
        
        try:
            # Appel de la méthode de synchronisation complète du service Kelio
            result = self.kelio_service.synchroniser_tous_les_employes(mode='complet')
            
            api_call_duration = (timezone.now() - api_call_start).total_seconds() * 1000
            
            # Traitement du résultat
            return self._process_sync_result(result, api_call_duration, 'synchroniser_tous_les_employes')
            
        except Exception as e:
            api_call_duration = (timezone.now() - api_call_start).total_seconds() * 1000
            self._log_api_call('synchroniser_tous_les_employes', 'EXCEPTION', api_call_duration, error=str(e))
            
            return self._create_error_response(f"Erreur synchronisation complète: {str(e)}")
    
    def _execute_employees_only_sync(self):
        """Exécute une synchronisation des employés uniquement"""
        logger.info("[KELIO-SYNC-MANAGER] Synchronisation employés uniquement")
        
        api_call_start = timezone.now()
        
        try:
            # Appel de la méthode de synchronisation en mode employés uniquement
            result = self.kelio_service.synchroniser_tous_les_employes(mode='employees_only')
            
            api_call_duration = (timezone.now() - api_call_start).total_seconds() * 1000
            
            # Traitement du résultat
            return self._process_sync_result(result, api_call_duration, 'synchroniser_tous_les_employes_only')
            
        except Exception as e:
            api_call_duration = (timezone.now() - api_call_start).total_seconds() * 1000
            self._log_api_call('synchroniser_tous_les_employes_only', 'EXCEPTION', api_call_duration, error=str(e))
            
            return self._create_error_response(f"Erreur synchronisation employés: {str(e)}")
    
    def _execute_incremental_sync(self):
        """Exécute une synchronisation incrémentale"""
        logger.info("[KELIO-SYNC-MANAGER] Synchronisation incrémentale")
        
        # Déterminer le mode selon la dernière synchronisation
        try:
            from .models import ConfigurationApiKelio
            config = ConfigurationApiKelio.objects.filter(actif=True).first()
            
            if config and config.kelio_last_sync:
                time_since_last = timezone.now() - config.kelio_last_sync
                mode = 'employees_only' if time_since_last.total_seconds() < 3600 else 'complet'
            else:
                mode = 'complet'
                
        except Exception:
            mode = 'employees_only'
        
        api_call_start = timezone.now()
        
        try:
            result = self.kelio_service.synchroniser_tous_les_employes(mode=mode)
            
            api_call_duration = (timezone.now() - api_call_start).total_seconds() * 1000
            
            return self._process_sync_result(result, api_call_duration, f'synchroniser_incremental_{mode}')
            
        except Exception as e:
            api_call_duration = (timezone.now() - api_call_start).total_seconds() * 1000
            self._log_api_call(f'synchroniser_incremental_{mode}', 'EXCEPTION', api_call_duration, error=str(e))
            
            return self._create_error_response(f"Erreur synchronisation incrémentale: {str(e)}")
    
    def _process_sync_result(self, result, api_call_duration, method_name):
        """Traite le résultat de synchronisation"""
        try:
            statut_global = result.get('statut_global', 'inconnu')
            
            if statut_global in ['reussi', 'partiel']:
                # Succès
                resume = result.get('resume', {})
                
                # Mise à jour des statistiques
                self.stats.update({
                    'total_employees_processed': resume.get('employees_total', 0),
                    'total_created': resume.get('employees_reussis', 0),
                    'total_updated': resume.get('employees_reussis', 0),
                    'total_errors': resume.get('employees_erreurs', 0)
                })
                
                # Log de l'appel API
                self._log_api_call(
                    method_name,
                    'REUSSI',
                    api_call_duration,
                    response_data={
                        'employees_total': resume.get('employees_total', 0),
                        'employees_processed': result.get('employees_traites', 0),
                        'employees_success': result.get('employees_reussis', 0),
                        'employees_errors': result.get('employees_erreurs', 0)
                    }
                )
                
                return self._create_success_response(
                    f"Synchronisation {self.sync_mode} réussie",
                    result
                )
                
            else:
                # Échec
                error_msg = result.get('erreur_critique', result.get('erreur', 'Erreur inconnue'))
                
                self._log_api_call(method_name, 'ECHEC', api_call_duration, error=error_msg)
                
                return self._create_error_response(f"Échec synchronisation: {error_msg}")
                
        except Exception as e:
            logger.error(f"[KELIO-SYNC-MANAGER] Erreur traitement résultat: {e}")
            return self._create_error_response(f"Erreur traitement résultat: {str(e)}")
    
    def _log_api_call(self, method, status, duration_ms, error=None, response_data=None):
        """Enregistre un appel API dans les logs"""
        self.api_calls_log['summary']['total_calls'] += 1
        
        if status == 'REUSSI':
            self.api_calls_log['summary']['successful_calls'] += 1
        else:
            self.api_calls_log['summary']['failed_calls'] += 1
        
        self.api_calls_log['summary']['total_api_time_ms'] += duration_ms
        
        # Détails de l'appel
        call_detail = {
            'timestamp': timezone.now().isoformat(),
            'method': method,
            'status': status,
            'duration_ms': duration_ms,
            'sync_mode': self.sync_mode
        }
        
        if error:
            call_detail['error'] = error
        if response_data:
            call_detail['response_data'] = response_data
        
        self.api_calls_log['calls_details'].append(call_detail)
        
        # Log console
        status_icon = "✅" if status == 'REUSSI' else "❌"
        logger.info(f"[API-LOG] {status_icon} {method}: {status} ({duration_ms:.0f}ms)")
    
    def _finalize_api_statistics(self):
        """Finalise les statistiques des appels API"""
        try:
            summary = self.api_calls_log['summary']
            
            if summary['total_calls'] > 0:
                summary['average_response_time_ms'] = summary['total_api_time_ms'] / summary['total_calls']
                summary['success_rate_percent'] = (summary['successful_calls'] / summary['total_calls']) * 100
                
        except Exception as e:
            logger.error(f"[KELIO-SYNC-MANAGER] Erreur finalisation stats API: {e}")
    
    def _create_success_response(self, message, kelio_result=None):
        """Crée une réponse de succès"""
        return {
            'success': True,
            'message': message,
            'data': {
                'sync_mode': self.sync_mode,
                'kelio_result': kelio_result
            },
            'stats': self.stats,
            'kelio_connection_info': self.connection_diagnostics,
            'kelio_api_calls': self.api_calls_log,
            'timestamp': timezone.now().isoformat()
        }
    
    def _create_error_response(self, message, exception=None):
        """Crée une réponse d'erreur"""
        potential_issues = []
        
        # Analyse des problèmes potentiels
        if self.connection_diagnostics['connection_status'] != 'REUSSIE':
            potential_issues.append({
                'type': 'CONNECTION_ISSUE',
                'description': f"Problème de connexion: {self.connection_diagnostics['connection_status']}",
                'suggestion': "Vérifiez la connectivité réseau et la configuration URL"
            })
        
        if self.api_calls_log['summary']['failed_calls'] > 0:
            potential_issues.append({
                'type': 'API_FAILURE',
                'description': f"Échecs API: {self.api_calls_log['summary']['failed_calls']}/{self.api_calls_log['summary']['total_calls']}",
                'suggestion': "Vérifiez les paramètres d'authentification et les permissions"
            })
        
        return {
            'success': False,
            'message': message,
            'data': {'sync_mode': self.sync_mode},
            'stats': self.stats,
            'error_details': str(exception) if exception else None,
            'kelio_connection_info': self.connection_diagnostics,
            'kelio_api_calls': self.api_calls_log,
            'kelio_diagnostics': {
                'connection_info': self.connection_diagnostics,
                'api_calls_attempted': self.api_calls_log,
                'potential_issues': potential_issues
            },
            'timestamp': timezone.now().isoformat()
        }


# ================================================================
# LOG DE CONFIRMATION
# ================================================================

logger.info("✅ Vue AJAX Kelio Global V4.1 chargée")
logger.info(">>> Fonctionnalités:")
logger.info("    • Synchronisation complète des employés avec données périphériques")
logger.info("    • Modes: complete, employees_only, incremental")
logger.info("    • Diagnostics détaillés des erreurs")
logger.info("    • Interface AJAX et template HTML")
logger.info("    • Compatible avec kelio_api_simplifie.py V4.1")

print("OK views_kelio_global.py V4.1 - Vue AJAX Kelio Global réécrite !")