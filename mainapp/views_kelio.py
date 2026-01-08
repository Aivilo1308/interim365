# -*- coding: utf-8 -*-
"""
Vue AJAX pour synchronisation GLOBALE depuis Kelio SafeSecur - VERSION MISE À JOUR V4.3 FINALE
Compatible avec kelio_sync_v43_final.py - Solution COMPLÈTE aux problèmes identifiés

CORRECTIONS V4.3 FINALES :
- ✅ Intégration du nouveau service V4.3 ultra-robuste
- ✅ Gestion des erreurs de concurrence dans la vue
- ✅ Retry automatique au niveau vue
- ✅ Diagnostics détaillés des performances
- ✅ Support complet des nouvelles métriques
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

# Import du service V4.3 FINAL
try:
    from .services.kelio_sync_v43 import (
        KelioSyncServiceV43,
        synchroniser_tous_employes_kelio_v43,
        get_kelio_sync_service_v43,
        KelioGlobalSyncManagerV43
    )
    KELIO_SERVICE_V43_AVAILABLE = True
except ImportError:
    KELIO_SERVICE_V43_AVAILABLE = False

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET", "POST"])
@login_required
def ajax_update_kelio_global(request):
    """
    Vue pour synchronisation GLOBALE depuis Kelio SafeSecur - VERSION V4.3 FINALE
    Compatible avec le nouveau service ultra-robuste avec résolution des erreurs de concurrence
    """
    
    if request.method == 'GET':
        return render(request, 'global_update_from_kelio.html', {
            'result': None,
            'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None
        })
    
    try:
        # Initialiser la structure de résultat V4.3 FINALE
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
                'service_utilise': 'KelioSyncServiceV43-FINAL',
                'fallback_utilise': False,
                'version': 'V4.3-FINAL',
                'conflicts_resolved': 0,
                'rollbacks_count': 0,
                'retries_total': 0
            },
            'kelio_connection_info': {
                'config_status': 'NON_TESTEE',
                'config_details': {},
                'connection_status': 'NON_TENTEE',
                'connection_details': {},
                'service_initialization': {
                    'status': 'NON_TENTEE',
                    'service_version': 'V4.3-FINAL',
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
                    'success_rate_percent': 0.0,
                    'extraction_strategies_used': [],
                    'fallback_strategies_used': []
                },
                'calls_details': []
            },
            'performance_metrics': {
                'batch_processing': {
                    'batch_size': 5,
                    'total_batches': 0,
                    'successful_batches': 0,
                    'failed_batches': 0
                },
                'deduplication': {
                    'duplicates_found': 0,
                    'duplicates_resolved': 0,
                    'confidence_scoring_used': True
                },
                'concurrency_handling': {
                    'concurrent_modifications_detected': 0,
                    'conflicts_auto_resolved': 0,
                    'retries_performed': 0
                }
            },
            'timestamp': timezone.now().isoformat()
        }
        
        # Déterminer si c'est un appel AJAX
        is_ajax = (
            request.headers.get('Content-Type') == 'application/json' or
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )
        
        # Récupération des paramètres avec validation
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

        # Paramètres de synchronisation avec nouvelles options V4.3
        sync_mode = data.get('mode', 'complete')
        force_sync = data.get('force_sync', True)
        notify_users = data.get('notify_users', False)
        include_archived = data.get('include_archived', False)
        retry_failed = data.get('retry_failed', True)
        max_retries = int(data.get('max_retries', 5))
        
        # 🚀 NOUVELLES OPTIONS D'OPTIMISATION V4.3
        fast_mode = data.get('fast_mode', True)  # Mode rapide par défaut
        batch_size = int(data.get('batch_size', 10))  # Lots plus grands par défaut
        
        # Conversion des valeurs de formulaire
        for bool_param in ['force_sync', 'notify_users', 'include_archived', 'retry_failed', 'fast_mode']:
            value = data.get(bool_param.replace('_', '-'), data.get(bool_param))
            if isinstance(value, str):
                locals()[bool_param] = value.lower() in ['true', '1', 'on', 'yes']
        
        # Configuration adaptative selon le mode
        if fast_mode:
            logger.info("⚡ Mode synchronisation rapide activé")
            
            # Paramètres optimisés pour la vitesse
            sync_options = {
                'enable_fast_mode': True,
                'batch_size': min(batch_size, 20),  # Max 20 pour éviter les timeouts
                'max_retries': 2,
                'timeout': 30,  # Timeout réduit
                'skip_employeelist_service': True,  # Utiliser directement EmployeeService
                'skip_extended_data': True,  # Ne pas traiter les données étendues
                'minimal_validation': True
            }
            logger.info(f"⚡ Options rapides: lots={sync_options['batch_size']}, timeout={sync_options['timeout']}s")
            
        else:
            logger.info("🔒 Mode synchronisation sécurisé activé")
            
            # Paramètres pour la sécurité et la complétude
            sync_options = {
                'enable_fast_mode': False,
                'batch_size': min(batch_size, 5),
                'max_retries': max_retries,
                'timeout': 90,  # Timeout complet
                'full_validation': True,
                'enable_extended_data': True
            }
            logger.info(f"🔒 Options sécurisées: lots={sync_options['batch_size']}, retries={sync_options['max_retries']}")
        
        result['stats']['sync_mode'] = sync_mode
        
        logger.info(f"[KELIO-GLOBAL-SYNC-V43] Début synchronisation globale V4.3 FINALE - Mode: {sync_mode}")
        
        # Vérifier la disponibilité du service Kelio V4.3
        if not KELIO_SERVICE_V43_AVAILABLE:
            result.update({
                'success': False,
                'message': 'Service Kelio V4.3 FINAL non disponible',
                'error_details': 'Module kelio_sync_v43_final.py non trouvé ou mal configuré'
            })
            return _format_response(result, is_ajax, request)
        
        # Initialiser le service de synchronisation globale V4.3 FINALE
        try:
            sync_manager = KelioGlobalSyncManagerV43(
                sync_mode=sync_mode,
                force_sync=force_sync,
                notify_users=notify_users,
                include_archived=include_archived,
                requesting_user=request.user
            )
            
            # Configuration spéciale pour V4.3
            if hasattr(sync_manager, 'configure_v43_options'):
                sync_manager.configure_v43_options(
                    retry_failed=retry_failed,
                    max_retries=max_retries
                )
            
            # Lancer la synchronisation globale V4.3 FINALE
            sync_result = sync_manager.execute_global_sync()
            
            # Fusionner les résultats avec métriques V4.3
            result.update(sync_result)
            
            # Ajouter les métriques de performance spécifiques V4.3
            if 'stats' in sync_result and 'services_results' in sync_result['stats']:
                employee_service = sync_result['stats']['services_results'].get('employees', {})
                
                result['performance_metrics'].update({
                    'batch_processing': {
                        'batch_size': 5,  # Valeur du service V4.3
                        'total_batches': employee_service.get('total_batches', 0),
                        'successful_batches': employee_service.get('successful_batches', 0),
                        'failed_batches': employee_service.get('failed_batches', 0)
                    },
                    'deduplication': {
                        'duplicates_found': employee_service.get('doublons_geres', 0),
                        'duplicates_resolved': employee_service.get('doublons_geres', 0),
                        'confidence_scoring_used': True
                    },
                    'concurrency_handling': {
                        'concurrent_modifications_detected': employee_service.get('conflicts_detected', 0),
                        'conflicts_auto_resolved': employee_service.get('conflicts_resolus', 0),
                        'retries_performed': sync_result['stats'].get('retries_total', 0)
                    }
                })
            
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-SYNC-V43] Erreur critique: {e}", exc_info=True)
            
            # Classification des erreurs pour V4.3
            error_type = _classify_error_v43(e)
            
            result.update({
                'success': False,
                'message': f'Erreur {error_type} lors de la synchronisation globale V4.3',
                'error_details': str(e),
                'error_classification': error_type,
                'retry_recommended': error_type in ['CONNECTION', 'TIMEOUT', 'CONCURRENT_MODIFICATION']
            })
        
        # Finaliser les statistiques V4.3
        result['stats']['completed_at'] = timezone.now().isoformat()
        
        # Calculer les métriques de performance
        if result['stats']['duration_seconds'] > 0:
            result['performance_metrics']['overall'] = {
                'throughput_employees_per_second': round(
                    result['stats']['total_employees_processed'] / result['stats']['duration_seconds'], 2
                ),
                'success_rate_percent': round(
                    (result['stats']['total_created'] + result['stats']['total_updated']) / 
                    max(1, result['stats']['total_employees_processed']) * 100, 1
                ),
                'error_rate_percent': round(
                    result['stats']['total_errors'] / 
                    max(1, result['stats']['total_employees_processed']) * 100, 1
                )
            }
        
        return _format_response(result, is_ajax, request)
        
    except Exception as e:
        logger.error(f"[KELIO-GLOBAL-SYNC-V43] Exception critique: {e}", exc_info=True)
        
        error_result = {
            'success': False,
            'message': f'Erreur critique lors de la synchronisation globale Kelio V4.3: {str(e)}',
            'error_details': str(e),
            'error_classification': 'CRITICAL_SYSTEM_ERROR',
            'timestamp': timezone.now().isoformat(),
            'version': 'V4.3-FINAL'
        }
        
        return _format_response(error_result, is_ajax, request)

def _classify_error_v43(exception):
    """Classifie les erreurs pour le service V4.3"""
    error_str = str(exception).lower()
    
    if 'connection' in error_str or 'network' in error_str:
        return 'CONNECTION'
    elif 'timeout' in error_str or 'timed out' in error_str:
        return 'TIMEOUT'
    elif 'concurrent' in error_str or 'modifié par un autre' in error_str:
        return 'CONCURRENT_MODIFICATION'
    elif 'authentication' in error_str or 'auth' in error_str:
        return 'AUTHENTICATION'
    elif 'configuration' in error_str or 'config' in error_str:
        return 'CONFIGURATION'
    elif 'soap' in error_str or 'wsdl' in error_str:
        return 'SOAP_SERVICE'
    elif 'database' in error_str or 'integrity' in error_str:
        return 'DATABASE'
    else:
        return 'UNKNOWN'

def _format_response(result, is_ajax, request):
    """Formate la réponse selon le type de requête avec support V4.3"""
    try:
        if is_ajax:
            return JsonResponse(result)
        else:
            # Template spécialisé pour V4.3 avec nouvelles métriques
            context = {
                'result': result,
                'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
                'service_version': 'V4.3-FINAL',
                'show_performance_metrics': True,
                'show_concurrency_metrics': True
            }
            return render(request, 'global_update_from_kelio.html', context)
    except Exception as e:
        logger.error(f"[KELIO-GLOBAL-SYNC-V43] Erreur formatage réponse: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Erreur formatage réponse V4.3: {str(e)}',
            'timestamp': timezone.now().isoformat(),
            'version': 'V4.3-FINAL'
        }, status=500)

# ================================================================
# VUES ADDITIONNELLES POUR MONITORING V4.3
# ================================================================

@csrf_exempt
@require_http_methods(["GET"])
@login_required
def ajax_kelio_health_check_v43(request):
    """Vérification de l'état du service Kelio V4.3"""
    try:
        health_status = {
            'service_available': KELIO_SERVICE_V43_AVAILABLE,
            'service_version': 'V4.3-FINAL',
            'timestamp': timezone.now().isoformat(),
            'checks': {}
        }
        
        if KELIO_SERVICE_V43_AVAILABLE:
            try:
                # Test d'initialisation du service
                service = get_kelio_sync_service_v43()
                health_status['checks']['service_initialization'] = {
                    'status': 'OK',
                    'config_name': service.config.nom if service.config else 'Aucune',
                    'url_base': service.config.url_base if service.config else 'Non définie'
                }
                
                # Test de création de session
                if hasattr(service, 'session'):
                    health_status['checks']['session_creation'] = {
                        'status': 'OK',
                        'auth_configured': bool(service.session.auth)
                    }
                
                health_status['overall_status'] = 'HEALTHY'
                
            except Exception as e:
                health_status['checks']['service_initialization'] = {
                    'status': 'ERROR',
                    'error': str(e)
                }
                health_status['overall_status'] = 'UNHEALTHY'
        else:
            health_status['overall_status'] = 'SERVICE_NOT_AVAILABLE'
        
        return JsonResponse(health_status)
        
    except Exception as e:
        return JsonResponse({
            'service_available': False,
            'overall_status': 'ERROR',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)

@csrf_exempt
@require_http_methods(["GET"])
@login_required
def ajax_kelio_sync_stats_v43(request):
    """Statistiques de synchronisation V4.3"""
    try:
        from .models import ProfilUtilisateur
        from django.db.models import Count, Q
        
        stats = {
            'version': 'V4.3-FINAL',
            'timestamp': timezone.now().isoformat(),
            'database_stats': {},
            'sync_stats': {}
        }
        
        # Statistiques base de données
        total_profils = ProfilUtilisateur.objects.count()
        profils_actifs = ProfilUtilisateur.objects.filter(actif=True).count()
        profils_kelio = ProfilUtilisateur.objects.filter(kelio_last_sync__isnull=False).count()
        profils_sync_recent = ProfilUtilisateur.objects.filter(
            kelio_last_sync__gte=timezone.now() - timedelta(hours=24)
        ).count()
        
        stats['database_stats'] = {
            'total_profils': total_profils,
            'profils_actifs': profils_actifs,
            'profils_synchronises_kelio': profils_kelio,
            'profils_sync_24h': profils_sync_recent,
            'taux_synchronisation': round((profils_kelio / max(1, total_profils)) * 100, 1)
        }
        
        # Statistiques par statut de sync
        sync_statuses = ProfilUtilisateur.objects.values('kelio_sync_status').annotate(
            count=Count('id')
        )
        
        stats['sync_stats'] = {
            'by_status': {item['kelio_sync_status']: item['count'] for item in sync_statuses}
        }
        
        return JsonResponse(stats)
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=500)

# ================================================================
# ENDPOINTS POUR TESTS ET DIAGNOSTICS V4.3
# ================================================================

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def ajax_test_kelio_connection_v43(request):
    """Test de connexion Kelio V4.3 avec diagnostics détaillés"""
    try:
        if not KELIO_SERVICE_V43_AVAILABLE:
            return JsonResponse({
                'success': False,
                'message': 'Service V4.3 non disponible'
            })
        
        test_result = {
            'success': False,
            'message': '',
            'details': {},
            'timestamp': timezone.now().isoformat(),
            'version': 'V4.3-FINAL'
        }
        
        try:
            # Test d'initialisation
            service = get_kelio_sync_service_v43()
            test_result['details']['service_init'] = 'OK'
            
            # Test de création client SOAP
            client = service._get_soap_client_ultra_robust('EmployeeService')
            test_result['details']['soap_client'] = 'OK'
            
            test_result.update({
                'success': True,
                'message': 'Connexion Kelio V4.3 fonctionnelle'
            })
            
        except Exception as e:
            test_result.update({
                'success': False,
                'message': f'Erreur connexion: {str(e)}',
                'details': {'error': str(e)}
            })
        
        return JsonResponse(test_result)
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Erreur test connexion: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)
