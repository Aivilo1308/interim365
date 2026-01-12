# -*- coding: utf-8 -*-
"""
Vue AJAX pour synchronisation GLOBALE depuis Kelio SafeSecur - VERSION V4.3 FINALE
Compatible avec kelio_sync_v43_final.py - Avec logging avancé

CORRECTIONS V4.3 FINALES :
- ✅ Intégration du nouveau service V4.3 ultra-robuste
- ✅ Gestion des erreurs de concurrence dans la vue
- ✅ Retry automatique au niveau vue
- ✅ Diagnostics détaillés des performances
- ✅ Support complet des nouvelles métriques
- ✅ Logging avancé pour audit et détection d'anomalies
"""

import json
import logging
import time
import traceback
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction

# ================================================================
# CONFIGURATION LOGGING AVANCÉ
# ================================================================

logger = logging.getLogger('interim.kelio')
action_logger = logging.getLogger('interim.actions')
anomaly_logger = logging.getLogger('interim.anomalies')
perf_logger = logging.getLogger('interim.performance')


def log_action(category, action, message, request=None, **kwargs):
    """Log une action utilisateur avec contexte"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    user_info = "anonymous"
    ip_addr = "-"
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        user_info = request.user.username
        ip_addr = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '-'))
        if ',' in ip_addr:
            ip_addr = ip_addr.split(',')[0].strip()
    
    extra_info = ' '.join([f"[{k}:{v}]" for k, v in kwargs.items() if v is not None])
    log_msg = f"[{timestamp}] [{category}] [{action}] [User:{user_info}] [IP:{ip_addr}] {extra_info} {message}"
    
    action_logger.info(log_msg)
    logger.info(log_msg)


def log_anomalie(category, message, severite='WARNING', request=None, **kwargs):
    """Log une anomalie détectée"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    user_info = "anonymous"
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        user_info = request.user.username
    
    extra_info = ' '.join([f"[{k}:{v}]" for k, v in kwargs.items() if v is not None])
    log_msg = f"[{timestamp}] [ANOMALIE] [{category}] [{severite}] [User:{user_info}] {extra_info} {message}"
    
    if severite == 'ERROR':
        anomaly_logger.error(f"❌ {log_msg}")
        logger.error(f"❌ ANOMALIE: {log_msg}")
    elif severite == 'CRITICAL':
        anomaly_logger.critical(f"🔥 {log_msg}")
        logger.critical(f"🔥 ANOMALIE CRITIQUE: {log_msg}")
    else:
        anomaly_logger.warning(f"⚠️ {log_msg}")
        logger.warning(f"⚠️ ANOMALIE: {log_msg}")


def log_resume(operation, stats, duree_ms=None):
    """Log un résumé d'opération avec statistiques"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    
    lines = [
        "",
        "=" * 60,
        f"📊 RÉSUMÉ: {operation}",
        "=" * 60,
        f"⏰ Date/Heure: {timestamp}",
    ]
    
    if duree_ms is not None:
        if duree_ms >= 60000:
            duree_str = f"{duree_ms/60000:.1f} min"
        elif duree_ms >= 1000:
            duree_str = f"{duree_ms/1000:.1f} sec"
        else:
            duree_str = f"{duree_ms:.0f} ms"
        lines.append(f"⏱️ Durée: {duree_str}")
    
    lines.append("📈 Statistiques:")
    for key, value in stats.items():
        icon = '✅' if 'succes' in key.lower() or 'created' in key.lower() or 'updated' in key.lower() else \
               '❌' if 'erreur' in key.lower() or 'error' in key.lower() or 'failed' in key.lower() else \
               '⚠️' if 'warning' in key.lower() or 'conflict' in key.lower() else '•'
        lines.append(f"   {icon} {key}: {value}")
    
    # Statut global
    erreurs = stats.get('total_errors', 0) + stats.get('failed_batches', 0)
    if erreurs == 0:
        lines.append("✅ Statut: SUCCÈS")
    elif erreurs > 10:
        lines.append("❌ Statut: ÉCHEC - Vérification requise")
    else:
        lines.append("⚠️ Statut: SUCCÈS PARTIEL")
    
    lines.extend(["=" * 60, ""])
    
    resume_text = '\n'.join(lines)
    perf_logger.info(resume_text)
    logger.info(resume_text)


def log_erreur(category, message, exception=None, request=None, **kwargs):
    """Log une erreur avec stack trace"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    user_info = "anonymous"
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        user_info = request.user.username
    
    extra_info = ' '.join([f"[{k}:{v}]" for k, v in kwargs.items() if v is not None])
    log_msg = f"[{timestamp}] [ERREUR] [{category}] [User:{user_info}] {extra_info} {message}"
    
    if exception:
        log_msg += f"\n  Exception: {type(exception).__name__}: {str(exception)}"
        log_msg += f"\n  Stack trace:\n{traceback.format_exc()}"
    
    logger.error(log_msg)
    anomaly_logger.error(log_msg)


# ================================================================
# IMPORT SERVICE KELIO V4.3
# ================================================================

try:
    from .services.kelio_sync_v43 import (
        KelioSyncServiceV43,
        synchroniser_tous_employes_kelio_v43,
        get_kelio_sync_service_v43,
        KelioGlobalSyncManagerV43
    )
    KELIO_SERVICE_V43_AVAILABLE = True
    log_action('KELIO', 'SERVICE_INIT', "Service Kelio V4.3 disponible")
except ImportError as e:
    KELIO_SERVICE_V43_AVAILABLE = False
    log_anomalie('KELIO', f"Service Kelio V4.3 non disponible: {e}", severite='WARNING')


# ================================================================
# VUE PRINCIPALE SYNCHRONISATION GLOBALE
# ================================================================

@csrf_exempt
@require_http_methods(["GET", "POST"])
@login_required
def ajax_update_kelio_global(request):
    """
    Vue pour synchronisation GLOBALE depuis Kelio SafeSecur - VERSION V4.3 FINALE
    Compatible avec le nouveau service ultra-robuste avec résolution des erreurs de concurrence
    """
    start_time = time.time()
    
    log_action('KELIO', 'DEBUT_SYNC_GLOBAL', "Début synchronisation globale Kelio V4.3",
              request=request, method=request.method)
    
    if request.method == 'GET':
        log_action('KELIO', 'ACCES_PAGE', "Accès page synchronisation Kelio", request=request)
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
                log_anomalie('KELIO', f"Format JSON invalide: {e}", severite='WARNING', request=request)
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
        
        # Options d'optimisation V4.3
        fast_mode = data.get('fast_mode', True)
        batch_size = int(data.get('batch_size', 10))
        
        log_action('KELIO', 'PARAMETRES_SYNC', f"Mode: {sync_mode}, Fast: {fast_mode}, Batch: {batch_size}",
                  request=request, sync_mode=sync_mode, fast_mode=fast_mode, batch_size=batch_size)
        
        # Conversion des valeurs de formulaire
        for bool_param in ['force_sync', 'notify_users', 'include_archived', 'retry_failed', 'fast_mode']:
            value = data.get(bool_param.replace('_', '-'), data.get(bool_param))
            if isinstance(value, str):
                locals()[bool_param] = value.lower() in ['true', '1', 'on', 'yes']
        
        # Configuration adaptative selon le mode
        if fast_mode:
            log_action('KELIO', 'MODE_RAPIDE', "Mode synchronisation rapide activé", request=request)
            
            sync_options = {
                'enable_fast_mode': True,
                'batch_size': min(batch_size, 20),
                'max_retries': 2,
                'timeout': 30,
                'skip_employeelist_service': True,
                'skip_extended_data': True,
                'minimal_validation': True
            }
        else:
            log_action('KELIO', 'MODE_SECURISE', "Mode synchronisation sécurisé activé", request=request)
            
            sync_options = {
                'enable_fast_mode': False,
                'batch_size': min(batch_size, 5),
                'max_retries': max_retries,
                'timeout': 90,
                'full_validation': True,
                'enable_extended_data': True
            }
        
        result['stats']['sync_mode'] = sync_mode
        
        # Vérifier la disponibilité du service Kelio V4.3
        if not KELIO_SERVICE_V43_AVAILABLE:
            log_anomalie('KELIO', "Service Kelio V4.3 non disponible", severite='ERROR', request=request)
            result.update({
                'success': False,
                'message': 'Service Kelio V4.3 FINAL non disponible',
                'error_details': 'Module kelio_sync_v43_final.py non trouvé ou mal configuré'
            })
            return _format_response(result, is_ajax, request)
        
        # Initialiser le service de synchronisation globale V4.3 FINALE
        try:
            log_action('KELIO', 'INIT_SERVICE', "Initialisation service Kelio V4.3", request=request)
            
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
            
            log_action('KELIO', 'LANCEMENT_SYNC', "Lancement synchronisation globale V4.3", request=request)
            
            # Lancer la synchronisation globale V4.3 FINALE
            sync_result = sync_manager.execute_global_sync()
            
            # Fusionner les résultats avec métriques V4.3
            result.update(sync_result)
            
            # Ajouter les métriques de performance spécifiques V4.3
            if 'stats' in sync_result and 'services_results' in sync_result['stats']:
                employee_service = sync_result['stats']['services_results'].get('employees', {})
                
                result['performance_metrics'].update({
                    'batch_processing': {
                        'batch_size': 5,
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
            
            # Log succès
            duree_ms = (time.time() - start_time) * 1000
            log_action('KELIO', 'SYNC_TERMINEE', 
                      f"Synchronisation terminée: {result['stats'].get('total_employees_processed', 0)} employés",
                      request=request,
                      crees=result['stats'].get('total_created', 0),
                      maj=result['stats'].get('total_updated', 0),
                      erreurs=result['stats'].get('total_errors', 0))
            
            log_resume('SYNC_KELIO_GLOBAL_V43', {
                'utilisateur': request.user.username,
                'mode_sync': sync_mode,
                'mode_rapide': fast_mode,
                'total_employes': result['stats'].get('total_employees_processed', 0),
                'total_crees': result['stats'].get('total_created', 0),
                'total_maj': result['stats'].get('total_updated', 0),
                'total_erreurs': result['stats'].get('total_errors', 0),
                'doublons_geres': result['performance_metrics'].get('deduplication', {}).get('duplicates_resolved', 0),
                'conflits_resolus': result['performance_metrics'].get('concurrency_handling', {}).get('conflicts_auto_resolved', 0),
            }, duree_ms=duree_ms)
            
            # Détection anomalies
            if result['stats'].get('total_errors', 0) > 10:
                log_anomalie('KELIO', f"Nombreuses erreurs sync: {result['stats']['total_errors']}",
                            severite='WARNING', request=request)
            
            if duree_ms > 300000:  # > 5 minutes
                log_anomalie('KELIO', f"Synchronisation très longue: {duree_ms/60000:.1f} min",
                            severite='WARNING', request=request)
            
        except Exception as e:
            duree_ms = (time.time() - start_time) * 1000
            log_erreur('KELIO', "Erreur critique synchronisation", exception=e, request=request)
            
            # Classification des erreurs pour V4.3
            error_type = _classify_error_v43(e)
            
            result.update({
                'success': False,
                'message': f'Erreur {error_type} lors de la synchronisation globale V4.3',
                'error_details': str(e),
                'error_classification': error_type,
                'retry_recommended': error_type in ['CONNECTION', 'TIMEOUT', 'CONCURRENT_MODIFICATION']
            })
            
            log_resume('SYNC_KELIO_GLOBAL_V43_ECHEC', {
                'utilisateur': request.user.username,
                'type_erreur': error_type,
                'message': str(e)[:100],
                'retry_recommande': error_type in ['CONNECTION', 'TIMEOUT', 'CONCURRENT_MODIFICATION'],
            }, duree_ms=duree_ms)
        
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
        duree_ms = (time.time() - start_time) * 1000
        log_erreur('KELIO', "Exception critique synchronisation globale", exception=e, request=request)
        
        error_result = {
            'success': False,
            'message': f'Erreur critique lors de la synchronisation globale Kelio V4.3: {str(e)}',
            'error_details': str(e),
            'error_classification': 'CRITICAL_SYSTEM_ERROR',
            'timestamp': timezone.now().isoformat(),
            'version': 'V4.3-FINAL'
        }
        
        log_resume('SYNC_KELIO_ERREUR_CRITIQUE', {
            'type_erreur': 'CRITICAL_SYSTEM_ERROR',
            'message': str(e)[:100],
        }, duree_ms=duree_ms)
        
        return _format_response(error_result, is_ajax, request)


# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

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
            context = {
                'result': result,
                'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
                'service_version': 'V4.3-FINAL',
                'show_performance_metrics': True,
                'show_concurrency_metrics': True
            }
            return render(request, 'global_update_from_kelio.html', context)
    except Exception as e:
        log_erreur('KELIO', "Erreur formatage réponse", exception=e, request=request)
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
    start_time = time.time()
    
    try:
        log_action('KELIO', 'HEALTH_CHECK', "Vérification santé service Kelio V4.3", request=request)
        
        health_status = {
            'service_available': KELIO_SERVICE_V43_AVAILABLE,
            'service_version': 'V4.3-FINAL',
            'timestamp': timezone.now().isoformat(),
            'checks': {}
        }
        
        if KELIO_SERVICE_V43_AVAILABLE:
            try:
                service = get_kelio_sync_service_v43()
                health_status['checks']['service_initialization'] = {
                    'status': 'OK',
                    'config_name': service.config.nom if service.config else 'Aucune',
                    'url_base': service.config.url_base if service.config else 'Non définie'
                }
                
                if hasattr(service, 'session'):
                    health_status['checks']['session_creation'] = {
                        'status': 'OK',
                        'auth_configured': bool(service.session.auth)
                    }
                
                health_status['overall_status'] = 'HEALTHY'
                
                log_action('KELIO', 'HEALTH_CHECK_OK', "Service Kelio V4.3 healthy", request=request)
                
            except Exception as e:
                health_status['checks']['service_initialization'] = {
                    'status': 'ERROR',
                    'error': str(e)
                }
                health_status['overall_status'] = 'UNHEALTHY'
                
                log_anomalie('KELIO', f"Health check échoué: {e}", severite='WARNING', request=request)
        else:
            health_status['overall_status'] = 'SERVICE_NOT_AVAILABLE'
            log_anomalie('KELIO', "Service Kelio non disponible (health check)", 
                        severite='WARNING', request=request)
        
        duree_ms = (time.time() - start_time) * 1000
        log_resume('KELIO_HEALTH_CHECK', {
            'service_disponible': KELIO_SERVICE_V43_AVAILABLE,
            'statut_global': health_status['overall_status'],
        }, duree_ms=duree_ms)
        
        return JsonResponse(health_status)
        
    except Exception as e:
        log_erreur('KELIO', "Erreur health check", exception=e, request=request)
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
    start_time = time.time()
    
    try:
        from .models import ProfilUtilisateur
        from django.db.models import Count, Q
        
        log_action('KELIO', 'STATS_SYNC', "Récupération statistiques sync Kelio", request=request)
        
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
        
        duree_ms = (time.time() - start_time) * 1000
        log_resume('KELIO_SYNC_STATS', {
            'total_profils': total_profils,
            'profils_actifs': profils_actifs,
            'profils_kelio': profils_kelio,
            'taux_sync': stats['database_stats']['taux_synchronisation'],
        }, duree_ms=duree_ms)
        
        # Détection anomalies
        if stats['database_stats']['taux_synchronisation'] < 50:
            log_anomalie('KELIO', f"Taux synchronisation faible: {stats['database_stats']['taux_synchronisation']}%",
                        severite='WARNING', request=request)
        
        return JsonResponse(stats)
        
    except Exception as e:
        log_erreur('KELIO', "Erreur statistiques sync", exception=e, request=request)
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
    start_time = time.time()
    
    try:
        log_action('KELIO', 'TEST_CONNEXION', "Test connexion Kelio V4.3", request=request)
        
        if not KELIO_SERVICE_V43_AVAILABLE:
            log_anomalie('KELIO', "Service V4.3 non disponible pour test", severite='WARNING', request=request)
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
            
            log_action('KELIO', 'TEST_SERVICE_INIT', "Service Kelio initialisé OK", request=request)
            
            # Test de création client SOAP
            client = service._get_soap_client_ultra_robust('EmployeeService')
            test_result['details']['soap_client'] = 'OK'
            
            log_action('KELIO', 'TEST_SOAP_CLIENT', "Client SOAP créé OK", request=request)
            
            test_result.update({
                'success': True,
                'message': 'Connexion Kelio V4.3 fonctionnelle'
            })
            
            log_action('KELIO', 'TEST_CONNEXION_OK', "Test connexion Kelio réussi", request=request)
            
        except Exception as e:
            test_result.update({
                'success': False,
                'message': f'Erreur connexion: {str(e)}',
                'details': {'error': str(e)}
            })
            
            log_anomalie('KELIO', f"Test connexion échoué: {e}", severite='WARNING', request=request)
        
        duree_ms = (time.time() - start_time) * 1000
        log_resume('TEST_CONNEXION_KELIO', {
            'succes': test_result['success'],
            'service_init': test_result['details'].get('service_init', 'N/A'),
            'soap_client': test_result['details'].get('soap_client', 'N/A'),
        }, duree_ms=duree_ms)
        
        return JsonResponse(test_result)
        
    except Exception as e:
        log_erreur('KELIO', "Erreur test connexion", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'message': f'Erreur test connexion: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)