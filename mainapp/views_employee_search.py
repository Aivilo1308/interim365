# -*- coding: utf-8 -*-
"""
views_employee_search.py - Recherche d'employés avec logging avancé
Version simplifiée sans dépendances Kelio
"""

import json
import logging
import time
import traceback
from datetime import datetime, timedelta
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.core.cache import cache
from django.db import models
from django.db.models import Q

from .models import ProfilUtilisateur

# ================================================================
# CONFIGURATION LOGGING AVANCÉ
# ================================================================

logger = logging.getLogger('interim')
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
        if duree_ms >= 1000:
            duree_str = f"{duree_ms/1000:.1f} sec"
        else:
            duree_str = f"{duree_ms:.0f} ms"
        lines.append(f"⏱️ Durée: {duree_str}")
    
    lines.append("📈 Statistiques:")
    for key, value in stats.items():
        icon = '✅' if 'succes' in key.lower() or 'trouve' in key.lower() else \
               '❌' if 'erreur' in key.lower() or 'echec' in key.lower() else '•'
        lines.append(f"   {icon} {key}: {value}")
    
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
# RECHERCHE PRINCIPALE D'EMPLOYÉ
# ================================================================

@login_required
@require_POST
def rechercher_employe_ajax(request):
    """
    Recherche d'employé par matricule - Version simplifiée avec logging
    """
    start_time = time.time()
    matricule = None
    
    try:
        # Récupération des paramètres
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        force_kelio_sync = data.get('force_kelio_sync', False)
        
        log_action('RECHERCHE', 'DEBUT_RECHERCHE', f"Recherche employé matricule: {matricule}",
                  request=request, matricule=matricule, force_sync=force_kelio_sync)
        
        if not matricule:
            log_anomalie('RECHERCHE', "Recherche sans matricule", severite='INFO', request=request)
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        if len(matricule) < 2:
            log_anomalie('RECHERCHE', f"Matricule trop court: {matricule}", severite='INFO', request=request)
            return JsonResponse({
                'success': False,
                'error': 'Matricule trop court (minimum 2 caractères)'
            })
        
        # ================================================================
        # RECHERCHE DANS LA BASE LOCALE
        # ================================================================
        
        try:
            employe = ProfilUtilisateur.objects.select_related(
                'user', 'poste', 'departement', 'site', 'manager'
            ).get(matricule=matricule)
            
            log_action('RECHERCHE', 'EMPLOYE_TROUVE', f"Employé trouvé: {employe.nom_complet}",
                      request=request, matricule=matricule, employe_id=employe.id)
            
            # Préparer les données de l'employé
            employe_data = _prepare_employee_data(employe)
            
            # Informations de synchronisation (simulées)
            sync_info = _get_sync_info(employe)
            
            duree_ms = (time.time() - start_time) * 1000
            
            log_resume('RECHERCHE_EMPLOYE', {
                'matricule': matricule,
                'trouve': True,
                'nom_complet': employe.nom_complet,
                'departement': employe.departement.nom if employe.departement else 'N/A',
                'source': 'base_locale',
            }, duree_ms=duree_ms)
            
            return JsonResponse({
                'success': True,
                'employe': employe_data,
                'sync_info': sync_info,
                'source': 'base_locale',
                'message': f'Employé {matricule} trouvé dans la base locale',
                'timestamp': timezone.now().isoformat()
            })
            
        except ProfilUtilisateur.DoesNotExist:
            duree_ms = (time.time() - start_time) * 1000
            
            log_anomalie('RECHERCHE', f"Employé {matricule} non trouvé", 
                        severite='INFO', request=request)
            
            log_resume('RECHERCHE_EMPLOYE', {
                'matricule': matricule,
                'trouve': False,
                'source': 'base_locale',
            }, duree_ms=duree_ms)
            
            return JsonResponse({
                'success': False,
                'error': f'Employé avec matricule {matricule} non trouvé',
                'details': {
                    'error_type': 'NotFound',
                    'suggestions': [
                        'Vérifiez l\'orthographe du matricule',
                        'Vérifiez que l\'employé existe dans le système',
                        'Contactez l\'administrateur si nécessaire'
                    ],
                    'searched_matricule': matricule
                }
            })
    
    except json.JSONDecodeError as e:
        log_anomalie('RECHERCHE', "Format JSON invalide", severite='WARNING', request=request)
        return JsonResponse({
            'success': False,
            'error': 'Format de données invalide'
        }, status=400)
    
    except Exception as e:
        log_erreur('RECHERCHE', f"Erreur recherche employé {matricule}", 
                  exception=e, request=request, matricule=matricule)
        return JsonResponse({
            'success': False,
            'error': 'Erreur interne du serveur',
            'details': {
                'error_type': 'InternalError',
                'suggestions': [
                    'Réessayez dans quelques instants',
                    'Contactez l\'administrateur si le problème persiste'
                ]
            }
        }, status=500)


# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _prepare_employee_data(employe):
    """Prépare les données d'employé pour la réponse"""
    try:
        # Calculer l'ancienneté
        anciennete = "Non renseignée"
        if employe.user and employe.user.date_joined:
            delta = timezone.now() - employe.user.date_joined
            annees = delta.days // 365
            mois = (delta.days % 365) // 30
            
            if annees > 0:
                anciennete = f"{annees} an{'s' if annees > 1 else ''}"
                if mois > 0:
                    anciennete += f" et {mois} mois"
            elif mois > 0:
                anciennete = f"{mois} mois"
            else:
                anciennete = "Moins d'un mois"
        
        # Déterminer le sexe (basique)
        sexe = "N/A"
        if employe.user and employe.user.first_name:
            prenom = employe.user.first_name.lower()
            if prenom.endswith(('a', 'e')) or 'marie' in prenom or 'fatou' in prenom:
                sexe = "F"
            else:
                sexe = "M"
        
        employe_data = {
            'id': employe.id,
            'matricule': employe.matricule,
            'nom_complet': employe.nom_complet,
            'prenom': employe.user.first_name if employe.user else '',
            'nom': employe.user.last_name if employe.user else '',
            'email': employe.user.email if employe.user else '',
            'sexe': sexe,
            'anciennete': anciennete,
            'departement': employe.departement.nom if employe.departement else '',
            'site': employe.site.nom if employe.site else '',
            'poste': employe.poste.titre if employe.poste else '',
            'type_profil': employe.type_profil,
            'statut_employe': employe.statut_employe,
            'actif': employe.actif,
            'manager': employe.manager.nom_complet if employe.manager else ''
        }
        
        return employe_data
        
    except Exception as e:
        log_erreur('RECHERCHE', f"Erreur préparation données employé {employe.matricule}", exception=e)
        return {
            'id': employe.id,
            'matricule': employe.matricule,
            'nom_complet': employe.nom_complet,
            'error': f'Erreur préparation données: {str(e)}'
        }


def _get_sync_info(employe):
    """Récupère les informations de synchronisation (simulées)"""
    try:
        last_update = employe.updated_at if hasattr(employe, 'updated_at') else timezone.now()
        
        if last_update:
            time_diff = timezone.now() - last_update
            is_recent = time_diff.total_seconds() < 86400  # 24h
        else:
            is_recent = False
        
        sync_info = {
            'is_recent': is_recent,
            'from_kelio': False,
            'needs_update': not is_recent,
            'last_sync': last_update.isoformat() if last_update else None,
            'sync_status': 'LOCAL_ONLY'
        }
        
        return sync_info
        
    except Exception as e:
        log_erreur('RECHERCHE', f"Erreur sync info {employe.matricule}", exception=e)
        return {
            'is_recent': False,
            'from_kelio': False,
            'needs_update': True,
            'last_sync': None,
            'sync_status': 'ERROR'
        }


# ================================================================
# AUTRES VUES AJAX
# ================================================================

@login_required
@require_POST
def sync_employe_kelio_ajax(request):
    """Synchronisation Kelio (simulée)"""
    start_time = time.time()
    
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        log_action('SYNC', 'SYNC_KELIO', f"Synchronisation Kelio demandée pour {matricule}",
                  request=request, matricule=matricule)
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        try:
            employe = ProfilUtilisateur.objects.get(matricule=matricule)
            
            # Simuler la mise à jour
            if hasattr(employe, 'updated_at'):
                employe.updated_at = timezone.now()
                employe.save()
            
            duree_ms = (time.time() - start_time) * 1000
            
            log_action('SYNC', 'SYNC_OK', f"Synchronisation simulée pour {matricule}",
                      request=request, matricule=matricule)
            
            log_resume('SYNC_KELIO_EMPLOYE', {
                'matricule': matricule,
                'statut': 'SIMULÉ',
                'nom_complet': employe.nom_complet,
            }, duree_ms=duree_ms)
            
            return JsonResponse({
                'success': True,
                'message': f'Synchronisation simulée pour {matricule}',
                'employe_updated': True,
                'timestamp': timezone.now().isoformat()
            })
            
        except ProfilUtilisateur.DoesNotExist:
            log_anomalie('SYNC', f"Employé {matricule} non trouvé pour sync",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False,
                'error': f'Employé {matricule} non trouvé'
            })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Format de données invalide'
        }, status=400)
    
    except Exception as e:
        log_erreur('SYNC', f"Erreur synchronisation {matricule}", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': 'Erreur interne du serveur'
        }, status=500)


@login_required
def verifier_disponibilite_candidat_ajax(request):
    """Vérification de disponibilité"""
    start_time = time.time()
    
    try:
        candidat_id = request.GET.get('candidat_id')
        date_debut = request.GET.get('date_debut')
        date_fin = request.GET.get('date_fin')
        
        log_action('DISPONIBILITE', 'VERIFICATION', f"Vérification disponibilité candidat {candidat_id}",
                  request=request, candidat_id=candidat_id, date_debut=date_debut, date_fin=date_fin)
        
        if not all([candidat_id, date_debut, date_fin]):
            return JsonResponse({
                'disponible': False,
                'raison': 'Paramètres manquants'
            })
        
        try:
            candidat = ProfilUtilisateur.objects.get(id=candidat_id)
            
            # Vérifications basiques
            if candidat.statut_employe != 'ACTIF':
                log_anomalie('DISPONIBILITE', f"Candidat {candidat_id} statut non actif",
                            severite='INFO', request=request)
                return JsonResponse({
                    'disponible': False,
                    'raison': f'Statut employé: {candidat.statut_employe}'
                })
            
            if not candidat.actif:
                log_anomalie('DISPONIBILITE', f"Candidat {candidat_id} inactif",
                            severite='INFO', request=request)
                return JsonResponse({
                    'disponible': False,
                    'raison': 'Employé inactif'
                })
            
            duree_ms = (time.time() - start_time) * 1000
            log_action('DISPONIBILITE', 'VERIFICATION_OK', f"Candidat {candidat_id} disponible",
                      request=request, candidat_id=candidat_id)
            
            return JsonResponse({
                'disponible': True,
                'raison': 'Disponible pour la période demandée'
            })
            
        except ProfilUtilisateur.DoesNotExist:
            log_anomalie('DISPONIBILITE', f"Candidat {candidat_id} non trouvé",
                        severite='WARNING', request=request)
            return JsonResponse({
                'disponible': False,
                'raison': 'Candidat non trouvé'
            })
    
    except Exception as e:
        log_erreur('DISPONIBILITE', "Erreur vérification disponibilité", exception=e, request=request)
        return JsonResponse({
            'disponible': False,
            'raison': 'Erreur lors de la vérification'
        })


@login_required
def recherche_rapide_employes_ajax(request):
    """Recherche rapide pour autocomplétion"""
    start_time = time.time()
    
    try:
        terme = request.GET.get('q', '').strip()
        limit = min(int(request.GET.get('limit', 10)), 20)
        
        log_action('RECHERCHE', 'RECHERCHE_RAPIDE', f"Recherche rapide terme: {terme}",
                  request=request, terme=terme, limite=limit)
        
        if len(terme) < 2:
            return JsonResponse({
                'success': True,
                'employes': [],
                'message': 'Saisissez au moins 2 caractères'
            })
        
        # Rechercher les employés
        employes = ProfilUtilisateur.objects.filter(
            Q(matricule__icontains=terme) |
            Q(user__first_name__icontains=terme) |
            Q(user__last_name__icontains=terme),
            actif=True,
            statut_employe='ACTIF'
        ).select_related('user', 'departement', 'poste')[:limit]
        
        employes_data = []
        for emp in employes:
            employes_data.append({
                'id': emp.id,
                'matricule': emp.matricule,
                'nom_complet': emp.nom_complet,
                'departement': emp.departement.nom if emp.departement else '',
                'poste': emp.poste.titre if emp.poste else '',
                'disponible_interim': True
            })
        
        duree_ms = (time.time() - start_time) * 1000
        log_action('RECHERCHE', 'RECHERCHE_RAPIDE_OK', f"{len(employes_data)} employés trouvés",
                  request=request, terme=terme, nb_resultats=len(employes_data))
        
        return JsonResponse({
            'success': True,
            'employes': employes_data,
            'count': len(employes_data)
        })
    
    except Exception as e:
        log_erreur('RECHERCHE', "Erreur recherche rapide", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors de la recherche'
        }, status=500)


@login_required
def employe_verification_matricule_ajax(request, matricule):
    """Vérification d'existence de matricule"""
    start_time = time.time()
    
    try:
        matricule = matricule.strip().upper()
        
        log_action('VERIFICATION', 'CHECK_MATRICULE', f"Vérification existence matricule {matricule}",
                  request=request, matricule=matricule)
        
        existe = ProfilUtilisateur.objects.filter(matricule=matricule).exists()
        
        duree_ms = (time.time() - start_time) * 1000
        
        if existe:
            employe = ProfilUtilisateur.objects.select_related('user').get(matricule=matricule)
            log_action('VERIFICATION', 'MATRICULE_EXISTE', f"Matricule {matricule} existe",
                      request=request, matricule=matricule)
            
            return JsonResponse({
                'success': True,
                'existe': True,
                'matricule': matricule,
                'nom_complet': employe.nom_complet,
                'actif': employe.actif,
                'statut': employe.statut_employe
            })
        else:
            log_action('VERIFICATION', 'MATRICULE_INEXISTANT', f"Matricule {matricule} n'existe pas",
                      request=request, matricule=matricule)
            return JsonResponse({
                'success': True,
                'existe': False,
                'matricule': matricule
            })
    
    except Exception as e:
        log_erreur('VERIFICATION', "Erreur vérification matricule", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def verifier_disponibilite_employe_ajax(request):
    """Vérification de disponibilité d'un employé"""
    start_time = time.time()
    
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        date_debut_str = data.get('date_debut')
        date_fin_str = data.get('date_fin')
        
        log_action('DISPONIBILITE', 'VERIFICATION', f"Vérification disponibilité {matricule}",
                  request=request, matricule=matricule, date_debut=date_debut_str, date_fin=date_fin_str)
        
        if not all([matricule, date_debut_str, date_fin_str]):
            return JsonResponse({
                'success': False,
                'error': 'Matricule et dates requis'
            })
        
        try:
            employe = ProfilUtilisateur.objects.get(matricule=matricule)
            
            # Parser les dates
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
            
            # Vérifier la disponibilité
            if hasattr(employe, 'est_disponible_pour_interim'):
                disponibilite = employe.est_disponible_pour_interim(date_debut, date_fin)
            else:
                disponibilite = {
                    'disponible': True,
                    'raison': 'Vérification non disponible'
                }
            
            duree_ms = (time.time() - start_time) * 1000
            
            log_action('DISPONIBILITE', 'VERIFICATION_OK', 
                      f"Disponibilité {matricule}: {disponibilite.get('disponible', 'N/A')}",
                      request=request, matricule=matricule, disponible=disponibilite.get('disponible'))
            
            return JsonResponse({
                'success': True,
                'matricule': matricule,
                'disponibilite': disponibilite,
                'periode': {
                    'debut': date_debut_str,
                    'fin': date_fin_str
                }
            })
            
        except ProfilUtilisateur.DoesNotExist:
            log_anomalie('DISPONIBILITE', f"Employé {matricule} non trouvé",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False,
                'error': f'Employé {matricule} non trouvé'
            })
        except ValueError as e:
            log_anomalie('DISPONIBILITE', f"Format date invalide: {e}",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False,
                'error': 'Format de date invalide'
            })
    
    except Exception as e:
        log_erreur('DISPONIBILITE', "Erreur vérification disponibilité", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def verifier_matricule_existe_ajax(request):
    """Vérifie si un matricule existe"""
    start_time = time.time()
    
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        log_action('VERIFICATION', 'CHECK_MATRICULE', f"Vérification existence matricule {matricule}",
                  request=request, matricule=matricule)
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        existe = ProfilUtilisateur.objects.filter(matricule=matricule).exists()
        
        duree_ms = (time.time() - start_time) * 1000
        
        if existe:
            employe = ProfilUtilisateur.objects.select_related('user').get(matricule=matricule)
            log_action('VERIFICATION', 'MATRICULE_EXISTE', f"Matricule {matricule} existe",
                      request=request, matricule=matricule)
            
            return JsonResponse({
                'success': True,
                'existe': True,
                'matricule': matricule,
                'nom_complet': employe.nom_complet,
                'actif': employe.actif
            })
        else:
            log_action('VERIFICATION', 'MATRICULE_INEXISTANT', f"Matricule {matricule} n'existe pas",
                      request=request, matricule=matricule)
            return JsonResponse({
                'success': True,
                'existe': False,
                'matricule': matricule
            })
    
    except Exception as e:
        log_erreur('VERIFICATION', "Erreur vérification matricule", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def statut_sync_employe_ajax(request, matricule):
    """Statut de synchronisation"""
    start_time = time.time()
    
    try:
        log_action('SYNC', 'CHECK_STATUT', f"Vérification statut sync {matricule}",
                  request=request, matricule=matricule)
        
        employe = get_object_or_404(ProfilUtilisateur, matricule=matricule.upper())
        
        statut = {
            'matricule': employe.matricule,
            'nom_complet': employe.nom_complet,
            'derniere_sync': employe.updated_at.isoformat() if hasattr(employe, 'updated_at') and employe.updated_at else None,
            'sync_status': 'LOCAL_ONLY',
            'needs_update': False
        }
        
        duree_ms = (time.time() - start_time) * 1000
        log_action('SYNC', 'STATUT_OK', f"Statut sync récupéré pour {matricule}",
                  request=request, matricule=matricule)
        
        return JsonResponse({
            'success': True,
            'statut': statut
        })
    
    except Exception as e:
        log_erreur('SYNC', f"Erreur statut sync {matricule}", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def invalider_cache_employe_ajax(request):
    """Invalidation de cache"""
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        log_action('CACHE', 'INVALIDATION', f"Invalidation cache pour {matricule}",
                  request=request, matricule=matricule)
        
        cache_keys = [
            f'employe_{matricule}',
            f'employe_disponibilite_{matricule}'
        ]
        
        for key in cache_keys:
            cache.delete(key)
        
        log_action('CACHE', 'INVALIDATION_OK', f"Cache invalidé pour {matricule}",
                  request=request, matricule=matricule, nb_cles=len(cache_keys))
        
        return JsonResponse({
            'success': True,
            'message': f'Cache invalidé pour {matricule}'
        })
    
    except Exception as e:
        log_erreur('CACHE', "Erreur invalidation cache", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def forcer_sync_kelio_ajax(request):
    """Synchronisation forcée"""
    start_time = time.time()
    
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        log_action('SYNC', 'SYNC_FORCEE', f"Synchronisation forcée pour {matricule}",
                  request=request, matricule=matricule)
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        try:
            employe = ProfilUtilisateur.objects.get(matricule=matricule)
            
            duree_ms = (time.time() - start_time) * 1000
            
            log_action('SYNC', 'SYNC_FORCEE_OK', f"Synchronisation forcée simulée pour {matricule}",
                      request=request, matricule=matricule)
            
            log_resume('SYNC_FORCEE_KELIO', {
                'matricule': matricule,
                'nom_complet': employe.nom_complet,
                'statut': 'SIMULÉ',
            }, duree_ms=duree_ms)
            
            return JsonResponse({
                'success': True,
                'message': f'Synchronisation forcée simulée pour {matricule}',
                'employe': _prepare_employee_data(employe)
            })
            
        except ProfilUtilisateur.DoesNotExist:
            log_anomalie('SYNC', f"Employé {matricule} non trouvé pour sync forcée",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False,
                'error': f'Employé {matricule} non trouvé'
            })
    
    except Exception as e:
        log_erreur('SYNC', "Erreur sync forcée", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def obtenir_suggestions_matricule_ajax(request):
    """Suggestions de matricules"""
    start_time = time.time()
    
    try:
        prefixe = request.GET.get('prefixe', '').strip().upper()
        limite = min(int(request.GET.get('limite', 5)), 10)
        
        log_action('SUGGESTION', 'RECHERCHE', f"Suggestions matricules préfixe: {prefixe}",
                  request=request, prefixe=prefixe, limite=limite)
        
        if len(prefixe) < 1:
            return JsonResponse({
                'success': True,
                'suggestions': []
            })
        
        matricules = ProfilUtilisateur.objects.filter(
            matricule__istartswith=prefixe,
            actif=True
        ).values_list('matricule', flat=True)[:limite]
        
        suggestions = []
        for matricule in matricules:
            try:
                employe = ProfilUtilisateur.objects.select_related('user').get(matricule=matricule)
                suggestions.append({
                    'matricule': matricule,
                    'nom_complet': employe.nom_complet,
                    'actif': employe.actif
                })
            except ProfilUtilisateur.DoesNotExist:
                continue
        
        duree_ms = (time.time() - start_time) * 1000
        
        log_action('SUGGESTION', 'RESULTATS', f"{len(suggestions)} suggestions trouvées",
                  request=request, prefixe=prefixe, nb_resultats=len(suggestions))
        
        return JsonResponse({
            'success': True,
            'suggestions': suggestions
        })
    
    except Exception as e:
        log_erreur('SUGGESTION', "Erreur suggestions matricules", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'suggestions': []
        }, status=500)


@login_required
def statistiques_cache_employes_ajax(request):
    """Statistiques de cache"""
    start_time = time.time()
    
    try:
        log_action('STATS', 'CACHE_STATS', "Récupération statistiques cache",
                  request=request)
        
        # Statistiques simulées
        stats = {
            'employes_actifs': ProfilUtilisateur.objects.filter(actif=True).count(),
            'employes_total': ProfilUtilisateur.objects.count(),
            'cache_hits': 0,
            'cache_misses': 0,
            'timestamp': timezone.now().isoformat()
        }
        
        duree_ms = (time.time() - start_time) * 1000
        
        log_resume('STATS_CACHE_EMPLOYES', {
            'employes_actifs': stats['employes_actifs'],
            'employes_total': stats['employes_total'],
        }, duree_ms=duree_ms)
        
        return JsonResponse({
            'success': True,
            'statistiques': stats
        })
    
    except Exception as e:
        log_erreur('STATS', "Erreur statistiques cache", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def test_ajax_rechercher_employe(request):
    """Vue de test ultra-simple"""
    start_time = time.time()
    
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        log_action('TEST', 'RECHERCHE_TEST', f"Test recherche employé {matricule}",
                  request=request, matricule=matricule)
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        try:
            employe = ProfilUtilisateur.objects.select_related(
                'user', 'poste', 'departement', 'site'
            ).get(matricule=matricule)
            
            duree_ms = (time.time() - start_time) * 1000
            
            log_action('TEST', 'RECHERCHE_TEST_OK', f"Test réussi pour {matricule}",
                      request=request, matricule=matricule)
            
            return JsonResponse({
                'success': True,
                'employe': {
                    'id': employe.id,
                    'matricule': employe.matricule,
                    'nom_complet': employe.nom_complet,
                    'departement': employe.departement.nom if employe.departement else '',
                    'poste': employe.poste.titre if employe.poste else '',
                    'site': employe.site.nom if employe.site else '',
                    'sexe': 'M',
                    'anciennete': '1 an'
                },
                'sync_info': {
                    'is_recent': True,
                    'from_kelio': False
                },
                'source': 'test_local',
                'message': f'Employé {matricule} trouvé'
            })
            
        except ProfilUtilisateur.DoesNotExist:
            log_anomalie('TEST', f"Employé test {matricule} non trouvé",
                        severite='INFO', request=request)
            return JsonResponse({
                'success': False,
                'error': f'Employé {matricule} non trouvé'
            })
    
    except Exception as e:
        log_erreur('TEST', "Erreur test recherche", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'error': f'Erreur: {str(e)}'
        }, status=500)