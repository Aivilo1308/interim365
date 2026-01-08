# -*- coding: utf-8 -*-
"""
Vue AJAX pour synchronisation GLOBALE depuis Kelio SafeSecur - VERSION MISE A JOUR V4.1
Avec diagnostics detailles des erreurs de connexion et d'appel API SOAP

Compatible avec kelio_api_simplifie.py V4.1 COMPLETE
Corrections pour la compatibilite avec le nouveau service refactorise
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

# Import des exceptions Kelio depuis kelio_api_simplifie.py V4.1
try:
    from .services.kelio_api_simplifie import (
        get_kelio_sync_service_v41,
        synchroniser_tous_employes_kelio_v41,
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
except ImportError:
    KELIO_SERVICE_AVAILABLE = False

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET", "POST"])
@login_required
def ajax_update_kelio_global(request):
    """
    Vue pour synchronisation GLOBALE depuis Kelio SafeSecur - VERSION MISE A JOUR V4.1
    Compatible avec le nouveau service refactorise avec fallback automatique
    """
    
    if request.method == 'GET':
        return render(request, 'global_update_from_kelio.html', {
            'result': None,
            'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None
        })
    
    try:
        # Initialiser la structure de resultat complete
        result = {
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
                'sync_mode': 'global',
                'started_at': timezone.now().isoformat(),
                'completed_at': None,
                'service_utilise': None,
                'fallback_utilise': False
            },
            'kelio_connection_info': {
                'config_status': 'NON_TESTEE',
                'config_details': {},
                'connection_status': 'NON_TENTEE',
                'connection_details': {},
                'service_initialization': {
                    'status': 'NON_TENTEE',
                    'service_version': 'V4.1',
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
            'timestamp': timezone.now().isoformat()
        }
        
        # Determiner si c'est un appel AJAX
        is_ajax = (
            request.headers.get('Content-Type') == 'application/json' or
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )
        
        # Recuperation des parametres
        if is_ajax or request.content_type == 'application/json':
            try:
                data = json.loads(request.body.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                result.update({
                    'success': False,
                    'message': 'Format JSON invalide',
                    'error_details': str(e)
                })
                return _format_response(result, is_ajax, request)
        else:
            data = request.POST.dict()
        
        # Parametres de synchronisation
        sync_mode = data.get('mode', 'complete')
        force_sync = data.get('force_sync', True)
        notify_users = data.get('notify_users', False)
        include_archived = data.get('include_archived', False)
        
        # Conversion des valeurs de formulaire
        if isinstance(force_sync, str):
            force_sync = force_sync.lower() in ['true', '1', 'on', 'yes']
        if isinstance(notify_users, str):
            notify_users = notify_users.lower() in ['true', '1', 'on', 'yes']
        if isinstance(include_archived, str):
            include_archived = include_archived.lower() in ['true', '1', 'on', 'yes']
        
        result['stats']['sync_mode'] = sync_mode
        
        logger.info(f"[KELIO-GLOBAL-SYNC] Debut synchronisation globale V4.1 - Mode: {sync_mode}")
        
        # Verifier la disponibilite du service Kelio
        if not KELIO_SERVICE_AVAILABLE:
            result.update({
                'success': False,
                'message': 'Service Kelio V4.1 non disponible',
                'error_details': 'Module kelio_api_simplifie.py V4.1 non trouve ou mal configure'
            })
            return _format_response(result, is_ajax, request)
        
        # Initialiser le service de synchronisation globale V4.1
        try:
            sync_manager = KelioGlobalSyncManagerV41(
                sync_mode=sync_mode,
                force_sync=force_sync,
                notify_users=notify_users,
                include_archived=include_archived,
                requesting_user=request.user
            )
            
            # Lancer la synchronisation globale
            sync_result = sync_manager.execute_global_sync()
            
            # Fusionner les resultats
            result.update(sync_result)
            
        except ConfigurationKeliomanquanteError as e:
            logger.error(f"[KELIO-GLOBAL-SYNC] Configuration manquante: {e}")
            result.update({
                'success': False,
                'message': 'Configuration Kelio manquante ou invalide',
                'error_details': str(e)
            })
            
        except KelioConnectionError as e:
            logger.error(f"[KELIO-GLOBAL-SYNC] Erreur connexion Kelio: {e}")
            result.update({
                'success': False,
                'message': 'Impossible de se connecter a Kelio SafeSecur',
                'error_details': str(e)
            })
            
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-SYNC] Erreur inattendue: {e}", exc_info=True)
            result.update({
                'success': False,
                'message': 'Erreur inattendue lors de la synchronisation globale',
                'error_details': str(e)
            })
        
        # Finaliser les statistiques
        result['stats']['completed_at'] = timezone.now().isoformat()
        
        return _format_response(result, is_ajax, request)
        
    except Exception as e:
        logger.error(f"[KELIO-GLOBAL-SYNC] Exception critique: {e}", exc_info=True)
        
        error_result = {
            'success': False,
            'message': f'Erreur critique lors de la synchronisation globale Kelio: {str(e)}',
            'error_details': str(e),
            'timestamp': timezone.now().isoformat()
        }
        
        return _format_response(error_result, is_ajax, request)


def _format_response(result, is_ajax, request):
    """Formate la reponse selon le type de requete"""
    try:
        if is_ajax:
            return JsonResponse(result)
        else:
            context = {
                'result': result,
                'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None
            }
            return render(request, 'global_update_from_kelio.html', context)
    except Exception as e:
        logger.error(f"[KELIO-GLOBAL-SYNC] Erreur formatage reponse: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Erreur formatage reponse: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)


class KelioGlobalSyncManagerV41:
    """
    Service pour la synchronisation globale depuis Kelio SafeSecur - VERSION V4.1
    Compatible avec kelio_api_simplifie.py V4.1 COMPLETE avec fallback automatique
    """
    
    def __init__(self, sync_mode='complete', force_sync=True, notify_users=False, 
                 include_archived=False, requesting_user=None):
        self.sync_mode = sync_mode
        self.force_sync = force_sync
        self.notify_users = notify_users
        self.include_archived = include_archived
        self.requesting_user = requesting_user
        
        # Statistiques globales
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
            'completed_at': None,
            'service_utilise': None,
            'fallback_utilise': False
        }
        
        logger.info(f"[KELIO-GLOBAL-MANAGER] Initialise pour synchronisation V4.1 {sync_mode}")
    
    def execute_global_sync(self):
        """Execute la synchronisation globale avec diagnostics complets V4.1"""
        start_time = timezone.now()
        
        try:
            logger.info(f"[KELIO-GLOBAL-MANAGER] Debut synchronisation globale mode {self.sync_mode}")
            
            # Etape 1: Test et initialisation du service Kelio V4.1
            if not self._setup_kelio_service():
                return self._error_response("Echec de l'initialisation du service Kelio V4.1")
            
            # Etape 2: Execution selon le mode de synchronisation
            if self.sync_mode == 'complete':
                result = self._execute_complete_sync()
            elif self.sync_mode == 'employees_only':
                result = self._execute_employees_only_sync()
            elif self.sync_mode == 'incremental':
                result = self._execute_incremental_sync()
            else:
                return self._error_response(f"Mode de synchronisation inconnu: {self.sync_mode}")
            
            # Etape 3: Calcul duree et resultats finaux
            duration = (timezone.now() - start_time).total_seconds()
            self.stats['duration_seconds'] = duration
            self.stats['completed_at'] = timezone.now().isoformat()
            
            # Calculer la vitesse de traitement
            if self.stats['total_employees_processed'] > 0 and duration > 0:
                self.stats['employees_per_second'] = self.stats['total_employees_processed'] / duration
            
            logger.info(f"[KELIO-GLOBAL-MANAGER] Synchronisation globale V4.1 terminee en {duration:.2f}s")
            
            return result
            
        except Exception as e:
            duration = (timezone.now() - start_time).total_seconds()
            self.stats['duration_seconds'] = duration
            self.stats['completed_at'] = timezone.now().isoformat()
            
            logger.error(f"[KELIO-GLOBAL-MANAGER] Erreur synchronisation globale V4.1: {e}", exc_info=True)
            return self._error_response(f"Erreur: {str(e)}", e)
    
    def _setup_kelio_service(self):
        """Configure l'acces a Kelio SafeSecur V4.1"""
        try:
            logger.info("[KELIO-GLOBAL-MANAGER] Test configuration Kelio SafeSecur V4.1...")
            
            # Recuperation/test de la configuration V4.1
            self.kelio_service = get_kelio_sync_service_v41()
            
            logger.info(f"Service Kelio V4.1 initialise pour {self.kelio_service.config.nom}")
            return True
            
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-MANAGER] Erreur configuration Kelio V4.1: {e}")
            return False
    
    def _execute_complete_sync(self):
        """Execute une synchronisation complete (employes principalement) V4.1"""
        logger.info("[KELIO-GLOBAL-MANAGER] Debut synchronisation complete V4.1")
        
        services_to_sync = [
            ('employees', 'Employes'),
        ]
        
        return self._execute_services_sync(services_to_sync)
    
    def _execute_employees_only_sync(self):
        """Execute une synchronisation des employes seulement V4.1"""
        logger.info("[KELIO-GLOBAL-MANAGER] Debut synchronisation employes seulement V4.1")
        
        services_to_sync = [
            ('employees', 'Employes')
        ]
        
        return self._execute_services_sync(services_to_sync)
    
    def _execute_incremental_sync(self):
        """Execute une synchronisation incrementale V4.1"""
        logger.info("[KELIO-GLOBAL-MANAGER] Debut synchronisation incrementale V4.1")
        
        services_to_sync = [
            ('employees', 'Employes')
        ]
        
        return self._execute_services_sync(services_to_sync)
    
    def _execute_services_sync(self, services_to_sync):
        """Execute la synchronisation pour les services specifies V4.1"""
        try:
            for service_name, service_display in services_to_sync:
                logger.info(f"[KELIO-GLOBAL-MANAGER] Synchronisation {service_display}...")
                
                service_start_time = timezone.now()
                service_result = self._sync_service(service_name)
                service_duration = (timezone.now() - service_start_time).total_seconds()
                
                # Enregistrer les resultats du service
                self.stats['services_results'][service_name] = {
                    'status': 'SUCCESS' if service_result['success'] else 'FAILED',
                    'processed': service_result.get('processed', 0),
                    'success_count': service_result.get('success_count', 0),
                    'error_count': service_result.get('error_count', 0),
                    'duration_seconds': service_duration,
                    'message': service_result.get('message', ''),
                    'service_utilise': service_result.get('service_utilise', 'Non specifie'),
                    'fallback_utilise': service_result.get('fallback_utilise', False)
                }
                
                # Mettre a jour les totaux avec les nouvelles statistiques V4.1
                self.stats['total_employees_processed'] += service_result.get('processed', 0)
                self.stats['total_created'] += service_result.get('created', 0)
                self.stats['total_updated'] += service_result.get('updated', 0)
                self.stats['total_errors'] += service_result.get('error_count', 0)
                self.stats['service_utilise'] = service_result.get('service_utilise')
                self.stats['fallback_utilise'] = service_result.get('fallback_utilise', False)
                
                logger.info(f"[KELIO-GLOBAL-MANAGER] {service_display} termine: {service_result.get('processed', 0)} traites")
            
            # Determiner le succes global
            total_services = len(services_to_sync)
            successful_services = sum(1 for result in self.stats['services_results'].values() 
                                    if result['status'] == 'SUCCESS')
            
            if successful_services == total_services:
                return self._success_response("Synchronisation globale V4.1 terminee avec succes")
            elif successful_services > 0:
                return self._partial_success_response(f"Synchronisation partielle V4.1: {successful_services}/{total_services} services reussis")
            else:
                return self._error_response("Echec de tous les services de synchronisation V4.1")
                
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-MANAGER] Erreur execution services V4.1: {e}")
            return self._error_response(f"Erreur lors de l'execution des services V4.1: {str(e)}")
    
    def _sync_service(self, service_name):
        """Synchronise un service specifique - VERSION V4.1"""
        try:
            if service_name == 'employees':
                return self._sync_employees()
            else:
                return {
                    'success': False,
                    'message': f'Service inconnu: {service_name}',
                    'processed': 0,
                    'error_count': 1
                }
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-MANAGER] Erreur sync service {service_name}: {e}")
            return {
                'success': False,
                'message': f'Erreur service {service_name}: {str(e)}',
                'processed': 0,
                'error_count': 1
            }
    
    def _sync_employees(self):
        """Synchronise tous les employes depuis Kelio - VERSION V4.1 CORRIGEE"""
        try:
            logger.info("[KELIO-GLOBAL-MANAGER] Debut synchronisation employes V4.1")
            
            api_call_start = timezone.now()
            
            try:
                # ✅ CORRECTION : Utiliser la nouvelle fonction V4.1
                result = synchroniser_tous_employes_kelio_v41(mode='complet')
                
                api_call_duration = (timezone.now() - api_call_start).total_seconds() * 1000
                
                if result.get('statut_global') in ['reussi', 'partiel']:
                    # Succes - Adaptation aux nouvelles structures de donnees V4.1
                    donnees = result.get('donnees_globales', {})
                    resume = result.get('resume', {})
                    metadata = result.get('metadata', {})
                    
                    return {
                        'success': True,
                        'message': f"Employes synchronises avec succes (Service: {metadata.get('service_utilise', 'Non specifie')})",
                        'processed': donnees.get('employes_traites', 0) or resume.get('employees_total', 0),
                        'success_count': donnees.get('employes_traites', 0) or resume.get('employees_total', 0),
                        'created': donnees.get('nouveaux_employes', 0) or resume.get('employees_reussis', 0),
                        'updated': donnees.get('employes_mis_a_jour', 0),
                        'error_count': donnees.get('erreurs', 0) or resume.get('employees_erreurs', 0),
                        'service_utilise': metadata.get('service_utilise', 'Service non specifie'),
                        'fallback_utilise': metadata.get('fallback_utilise', False),
                        'api_duration_ms': api_call_duration
                    }
                else:
                    # Echec
                    error_msg = result.get('erreur', 'Erreur inconnue')
                    
                    return {
                        'success': False,
                        'message': f'Echec synchronisation employes V4.1: {error_msg}',
                        'processed': 0,
                        'error_count': 1,
                        'service_utilise': 'Echec initialisation',
                        'fallback_utilise': False
                    }
                
            except Exception as api_exception:
                logger.error(f"[KELIO-GLOBAL-MANAGER] Exception API employes V4.1: {api_exception}")
                
                return {
                    'success': False,
                    'message': f'Exception API employes V4.1: {str(api_exception)}',
                    'processed': 0,
                    'error_count': 1,
                    'service_utilise': 'Exception API',
                    'fallback_utilise': False
                }
                
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-MANAGER] Erreur sync employes V4.1: {e}")
            return {
                'success': False,
                'message': f'Erreur synchronisation employes V4.1: {str(e)}',
                'processed': 0,
                'error_count': 1,
                'service_utilise': 'Erreur critique',
                'fallback_utilise': False
            }
    
    def _success_response(self, message):
        """Genere une reponse de succes V4.1"""
        return {
            'success': True,
            'message': message,
            'data': {
                'sync_mode': self.sync_mode,
                'total_employees_processed': self.stats['total_employees_processed'],
                'service_utilise': self.stats.get('service_utilise'),
                'fallback_utilise': self.stats.get('fallback_utilise', False)
            },
            'stats': self.stats,
            'timestamp': timezone.now().isoformat()
        }
    
    def _partial_success_response(self, message):
        """Genere une reponse de succes partiel V4.1"""
        return {
            'success': True,
            'message': message,
            'data': {
                'sync_mode': self.sync_mode,
                'total_employees_processed': self.stats['total_employees_processed'],
                'partial_success': True,
                'service_utilise': self.stats.get('service_utilise'),
                'fallback_utilise': self.stats.get('fallback_utilise', False)
            },
            'stats': self.stats,
            'timestamp': timezone.now().isoformat()
        }
    
    def _error_response(self, message, exception=None):
        """Genere une reponse d'erreur V4.1"""
        return {
            'success': False,
            'message': message,
            'data': {
                'sync_mode': self.sync_mode,
                'service_utilise': self.stats.get('service_utilise'),
                'fallback_utilise': self.stats.get('fallback_utilise', False)
            },
            'stats': self.stats,
            'error_details': str(exception) if exception else None,
            'timestamp': timezone.now().isoformat()
        }

# Log de confirmation
logger.info("✅ Vue AJAX pour synchronisation GLOBALE Kelio chargee - VERSION V4.1 MISE A JOUR")
print("OK views_kelio.py V4.1 MISE A JOUR - Compatible avec le nouveau service refactorise !")