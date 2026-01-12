# -*- coding: utf-8 -*-
"""
Vues Django pour la gestion des jours fériés avec logging avancé

À ajouter dans: mainapp/views_jours_feries.py
"""

from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from datetime import date, datetime, timedelta
from django.contrib import messages
from django.core.exceptions import ValidationError
import json
import logging
import time
import traceback

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
        icon = '✅' if 'succes' in key.lower() or 'ok' in key.lower() else \
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
# FONCTIONS UTILITAIRES
# ================================================================

def user_est_admin(user):
    """Vérifie si l'utilisateur a les droits admin/RH"""
    if hasattr(user, 'profilutilisateur'):
        return user.profilutilisateur.type_profil in ['ADMIN', 'RH']
    return user.is_superuser


def invalider_cache_ferie():
    """Invalide le cache du prochain férié"""
    today_str = date.today().isoformat()
    cache_key = f'prochain_ferie_context_{today_str}'
    cache.delete(cache_key)
    cache.delete('prochain_ferie_context')
    log_action('CACHE', 'INVALIDATION', "Cache jours fériés invalidé")


# ============================================================================
# VUES API - LISTE DES FÉRIÉS MUSULMANS
# ============================================================================

@login_required
@require_http_methods(["GET"])
def api_feries_musulmans(request):
    """
    Retourne la liste des jours fériés musulmans de l'année en cours et suivante
    """
    start_time = time.time()
    
    try:
        from mainapp.models import JourFerie, TypeJourFerie
        
        log_action('FERIES', 'API_MUSULMANS', "Récupération fériés musulmans", request=request)
        
        annee_courante = date.today().year
        
        feries = JourFerie.objects.filter(
            type_ferie=TypeJourFerie.FERIE_MUSULMAN,
            annee__in=[annee_courante, annee_courante + 1],
            date_ferie__gte=date.today() - timedelta(days=30)
        ).select_related('modele').order_by('date_ferie')
        
        result = []
        for ferie in feries:
            jours_avant = (ferie.date_ferie - date.today()).days
            result.append({
                'id': ferie.id,
                'nom': ferie.nom,
                'date_ferie': ferie.date_ferie.isoformat(),
                'date_ferie_formatee': ferie.date_ferie.strftime('%A %d %B %Y'),
                'date_calculee': ferie.date_calculee.isoformat() if ferie.date_calculee else None,
                'date_calculee_formatee': ferie.date_calculee.strftime('%d/%m/%Y') if ferie.date_calculee else None,
                'annee': ferie.annee,
                'est_modifie': ferie.est_modifie,
                'est_modifiable': ferie.modele.est_modifiable if ferie.modele else True,
                'jours_avant': jours_avant,
            })
        
        duree_ms = (time.time() - start_time) * 1000
        log_resume('API_FERIES_MUSULMANS', {
            'nb_feries': len(result),
            'annees': f"{annee_courante}, {annee_courante + 1}",
        }, duree_ms=duree_ms)
        
        return JsonResponse({'success': True, 'feries': result})
        
    except Exception as e:
        log_erreur('FERIES', "Erreur api_feries_musulmans", exception=e, request=request)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================================
# VUES API - SIGNALEMENTS
# ============================================================================

@login_required
@require_http_methods(["GET"])
def api_signalements_feries(request):
    """
    Retourne la liste des signalements en attente (pour les admins)
    """
    start_time = time.time()
    
    try:
        from mainapp.models import SignalementDateFerie
        
        log_action('FERIES', 'API_SIGNALEMENTS', "Récupération signalements", request=request)
        
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
            log_anomalie('FERIES', "Accès signalements non autorisé", 
                        severite='WARNING', request=request, type_profil=profil.type_profil)
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
        
        signalements = SignalementDateFerie.objects.filter(
            statut='EN_ATTENTE'
        ).select_related('jour_ferie', 'signale_par').order_by('-date_signalement')
        
        result = []
        for s in signalements:
            result.append({
                'id': s.id,
                'ferie_id': s.jour_ferie.id,
                'ferie_nom': s.jour_ferie.nom,
                'date_actuelle': s.jour_ferie.date_ferie.isoformat(),
                'date_actuelle_formatee': s.jour_ferie.date_ferie.strftime('%d/%m/%Y'),
                'date_suggeree': s.date_suggeree.isoformat(),
                'date_suggeree_formatee': s.date_suggeree.strftime('%d/%m/%Y'),
                'source_info': s.source_info,
                'commentaire': s.commentaire,
                'signale_par': s.signale_par.nom_complet if s.signale_par else 'Anonyme',
                'date_signalement_formatee': s.date_signalement.strftime('%d/%m/%Y %H:%M'),
            })
        
        duree_ms = (time.time() - start_time) * 1000
        log_resume('API_SIGNALEMENTS_FERIES', {
            'nb_signalements': len(result),
            'statut_filtre': 'EN_ATTENTE',
        }, duree_ms=duree_ms)
        
        return JsonResponse({'success': True, 'signalements': result})
        
    except Exception as e:
        log_erreur('FERIES', "Erreur api_signalements_feries", exception=e, request=request)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def signaler_correction_ferie(request):
    """
    Permet à un utilisateur de signaler une correction de date
    """
    start_time = time.time()
    
    try:
        from mainapp.models import JourFerie, SignalementDateFerie
        
        ferie_id = request.POST.get('ferie_id')
        date_suggeree = request.POST.get('date_suggeree')
        source_info = request.POST.get('source_info')
        commentaire = request.POST.get('commentaire', '')
        
        log_action('FERIES', 'SIGNALEMENT', f"Signalement correction férié {ferie_id}",
                  request=request, ferie_id=ferie_id, date_suggeree=date_suggeree)
        
        if not all([ferie_id, date_suggeree, source_info]):
            log_anomalie('FERIES', "Signalement avec données manquantes", 
                        severite='INFO', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Données manquantes'
            }, status=400)
        
        try:
            ferie = JourFerie.objects.get(pk=ferie_id)
        except JourFerie.DoesNotExist:
            log_anomalie('FERIES', f"Férié {ferie_id} non trouvé pour signalement",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Jour férié non trouvé'
            }, status=404)
        
        try:
            date_obj = datetime.strptime(date_suggeree, '%Y-%m-%d').date()
        except ValueError:
            log_anomalie('FERIES', f"Format date invalide: {date_suggeree}",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Format de date invalide'
            }, status=400)
        
        profil = getattr(request.user, 'profilutilisateur', None)
        
        signalement = SignalementDateFerie.objects.create(
            jour_ferie=ferie,
            date_suggeree=date_obj,
            source_info=source_info,
            commentaire=commentaire,
            signale_par=profil,
            statut='EN_ATTENTE'
        )
        
        duree_ms = (time.time() - start_time) * 1000
        log_action('FERIES', 'SIGNALEMENT_CREE', f"Signalement créé: {signalement.id} pour {ferie.nom}",
                  request=request, signalement_id=signalement.id, ferie_nom=ferie.nom)
        
        log_resume('SIGNALEMENT_FERIE', {
            'signalement_id': signalement.id,
            'ferie': ferie.nom,
            'date_actuelle': ferie.date_ferie.isoformat(),
            'date_suggeree': date_obj.isoformat(),
            'source': source_info,
        }, duree_ms=duree_ms)
        
        return JsonResponse({
            'success': True,
            'message': 'Signalement enregistré avec succès',
            'signalement_id': signalement.id
        })
        
    except Exception as e:
        log_erreur('FERIES', "Erreur signaler_correction_ferie", exception=e, request=request)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def traiter_signalement_ferie(request):
    """
    Traite un signalement (accepter ou rejeter) - Admin uniquement
    """
    start_time = time.time()
    
    try:
        from mainapp.models import JourFerie, SignalementDateFerie
        
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
            log_anomalie('FERIES', "Traitement signalement non autorisé",
                        severite='WARNING', request=request, type_profil=profil.type_profil)
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
        
        data = json.loads(request.body)
        signalement_id = data.get('signalement_id')
        action = data.get('action')
        
        log_action('FERIES', 'TRAITEMENT_SIGNALEMENT', f"Traitement signalement {signalement_id}: {action}",
                  request=request, signalement_id=signalement_id, action=action)
        
        if not signalement_id or action not in ['accepter', 'rejeter']:
            log_anomalie('FERIES', "Traitement signalement avec données invalides",
                        severite='INFO', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Données invalides'
            }, status=400)
        
        try:
            signalement = SignalementDateFerie.objects.select_related('jour_ferie').get(pk=signalement_id)
        except SignalementDateFerie.DoesNotExist:
            log_anomalie('FERIES', f"Signalement {signalement_id} non trouvé",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Signalement non trouvé'
            }, status=404)
        
        with transaction.atomic():
            if action == 'accepter':
                ferie = signalement.jour_ferie
                ancienne_date = ferie.date_ferie
                
                ferie.modifier_date(
                    nouvelle_date=signalement.date_suggeree,
                    motif=f"Suite au signalement de {signalement.signale_par}. Source: {signalement.source_info}",
                    utilisateur=profil.nom_complet
                )
                
                signalement.statut = 'ACCEPTE'
                invalider_cache_ferie()
                
                log_action('FERIES', 'SIGNALEMENT_ACCEPTE', 
                          f"Signalement {signalement_id} accepté, date modifiée {ancienne_date} -> {signalement.date_suggeree}",
                          request=request)
                
            else:
                signalement.statut = 'REJETE'
                log_action('FERIES', 'SIGNALEMENT_REJETE', f"Signalement {signalement_id} rejeté",
                          request=request)
            
            signalement.traite_par = profil
            signalement.date_traitement = timezone.now()
            signalement.save()
        
        duree_ms = (time.time() - start_time) * 1000
        log_resume('TRAITEMENT_SIGNALEMENT', {
            'signalement_id': signalement_id,
            'action': action.upper(),
            'ferie': signalement.jour_ferie.nom,
            'traite_par': profil.nom_complet,
        }, duree_ms=duree_ms)
        
        return JsonResponse({
            'success': True,
            'message': f'Signalement {action}'
        })
        
    except Exception as e:
        log_erreur('FERIES', "Erreur traiter_signalement_ferie", exception=e, request=request)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================================
# VUES API - MODIFICATION DATE (ADMIN)
# ============================================================================

@login_required
@require_POST
def modifier_date_ferie(request):
    """
    Modifie la date d'un jour férié - Admin uniquement
    """
    start_time = time.time()
    
    try:
        from mainapp.models import JourFerie
        
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
            log_anomalie('FERIES', "Modification date non autorisée",
                        severite='WARNING', request=request)
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
        
        ferie_id = request.POST.get('ferie_id')
        nouvelle_date = request.POST.get('nouvelle_date')
        motif = request.POST.get('motif')
        source = request.POST.get('source', '')
        
        log_action('FERIES', 'MODIFICATION_DATE', f"Modification date férié {ferie_id}",
                  request=request, ferie_id=ferie_id, nouvelle_date=nouvelle_date)
        
        if not all([ferie_id, nouvelle_date, motif]):
            return JsonResponse({
                'success': False, 
                'error': 'Données manquantes'
            }, status=400)
        
        try:
            ferie = JourFerie.objects.get(pk=ferie_id)
        except JourFerie.DoesNotExist:
            log_anomalie('FERIES', f"Férié {ferie_id} non trouvé",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Jour férié non trouvé'
            }, status=404)
        
        try:
            date_obj = datetime.strptime(nouvelle_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({
                'success': False, 
                'error': 'Format de date invalide'
            }, status=400)
        
        ancienne_date = ferie.date_ferie
        motif_complet = motif
        if source:
            motif_complet += f" (Source: {source})"
        
        ferie.modifier_date(
            nouvelle_date=date_obj,
            motif=motif_complet,
            utilisateur=profil.nom_complet
        )
        
        invalider_cache_ferie()
        
        duree_ms = (time.time() - start_time) * 1000
        log_action('FERIES', 'DATE_MODIFIEE', 
                  f"Date modifiée pour {ferie.nom}: {ancienne_date} -> {date_obj}",
                  request=request, ferie_id=ferie_id)
        
        log_resume('MODIFICATION_DATE_FERIE', {
            'ferie': ferie.nom,
            'ancienne_date': ancienne_date.isoformat(),
            'nouvelle_date': date_obj.isoformat(),
            'motif': motif[:50] + '...' if len(motif) > 50 else motif,
            'modifie_par': profil.nom_complet,
        }, duree_ms=duree_ms)
        
        return JsonResponse({
            'success': True,
            'message': 'Date modifiée avec succès',
            'nouvelle_date': date_obj.isoformat(),
            'cache_invalide': True
        })
        
    except Exception as e:
        log_erreur('FERIES', "Erreur modifier_date_ferie", exception=e, request=request)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def reinitialiser_date_ferie(request):
    """
    Réinitialise la date d'un jour férié à sa valeur calculée - Admin uniquement
    """
    start_time = time.time()
    
    try:
        from mainapp.models import JourFerie
        
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
            log_anomalie('FERIES', "Réinitialisation non autorisée",
                        severite='WARNING', request=request)
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
        
        data = json.loads(request.body)
        ferie_id = data.get('ferie_id')
        
        log_action('FERIES', 'REINITIALISATION', f"Réinitialisation date férié {ferie_id}",
                  request=request, ferie_id=ferie_id)
        
        if not ferie_id:
            return JsonResponse({
                'success': False, 
                'error': 'ID du jour férié manquant'
            }, status=400)
        
        try:
            ferie = JourFerie.objects.get(pk=ferie_id)
        except JourFerie.DoesNotExist:
            log_anomalie('FERIES', f"Férié {ferie_id} non trouvé pour réinitialisation",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Jour férié non trouvé'
            }, status=404)
        
        if not ferie.date_calculee:
            log_anomalie('FERIES', f"Férié {ferie.nom} sans date calculée",
                        severite='WARNING', request=request)
            return JsonResponse({
                'success': False, 
                'error': 'Ce jour férié n\'a pas de date calculée'
            }, status=400)
        
        ancienne_date = ferie.date_ferie
        ferie.reinitialiser_date(utilisateur=profil.nom_complet)
        invalider_cache_ferie()
        
        duree_ms = (time.time() - start_time) * 1000
        log_action('FERIES', 'DATE_REINITIALISEE', 
                  f"Date réinitialisée pour {ferie.nom}: {ancienne_date} -> {ferie.date_ferie}",
                  request=request)
        
        log_resume('REINITIALISATION_DATE_FERIE', {
            'ferie': ferie.nom,
            'ancienne_date': ancienne_date.isoformat(),
            'nouvelle_date': ferie.date_ferie.isoformat(),
            'reinitialise_par': profil.nom_complet,
        }, duree_ms=duree_ms)
        
        return JsonResponse({
            'success': True,
            'message': 'Date réinitialisée avec succès',
            'date': ferie.date_ferie.isoformat()
        })
        
    except Exception as e:
        log_erreur('FERIES', "Erreur reinitialiser_date_ferie", exception=e, request=request)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# LISTE DES JOURS FÉRIÉS
# =============================================================================

@login_required
def jourferie_liste(request):
    """
    Liste tous les jours fériés de l'année sélectionnée
    """
    start_time = time.time()
    
    from mainapp.models import JourFerie, TypeJourFerie
    
    log_action('FERIES', 'ACCES_LISTE', "Accès liste jours fériés", request=request)
    
    annee_courante = date.today().year
    annee = request.GET.get('annee', annee_courante)
    
    try:
        annee = int(annee)
    except (ValueError, TypeError):
        log_anomalie('FERIES', f"Année invalide: {annee}", severite='INFO', request=request)
        annee = annee_courante
    
    annees_disponibles = list(range(annee_courante - 2, annee_courante + 3))
    type_filtre = request.GET.get('type', '')
    
    feries = JourFerie.objects.filter(
        annee=annee,
        code_pays='CI',
        statut='ACTIF'
    ).select_related('modele').order_by('date_ferie')
    
    if type_filtre and type_filtre in dict(TypeJourFerie.choices):
        feries = feries.filter(type_ferie=type_filtre)
    
    stats = {
        'total': feries.count(),
        'civil': feries.filter(type_ferie=TypeJourFerie.FERIE_CIVIL).count(),
        'chretien': feries.filter(type_ferie=TypeJourFerie.FERIE_CHRETIEN).count(),
        'musulman': feries.filter(type_ferie=TypeJourFerie.FERIE_MUSULMAN).count(),
        'interne': feries.filter(type_ferie=TypeJourFerie.FERIE_INTERNE).count(),
    }
    
    est_admin = user_est_admin(request.user)
    est_superuser = request.user.is_superuser
    
    duree_ms = (time.time() - start_time) * 1000
    log_resume('LISTE_JOURS_FERIES', {
        'annee': annee,
        'total_feries': stats['total'],
        'filtre_type': type_filtre or 'aucun',
    }, duree_ms=duree_ms)

    context = {
        'feries': feries,
        'annee': annee,
        'annee_courante': annee_courante,
        'annees_disponibles': annees_disponibles,
        'type_filtre': type_filtre,
        'types_feries': TypeJourFerie.choices,
        'stats': stats,
        'est_admin': est_admin,
        'est_superuser': est_superuser,
        'today': date.today(),
    }
    
    return render(request, 'jourferie_liste.html', context)


# =============================================================================
# AFFICHER UN JOUR FÉRIÉ
# =============================================================================

@login_required
def jourferie_afficher(request, pk):
    """
    Affiche les détails d'un jour férié
    """
    start_time = time.time()
    
    from mainapp.models import JourFerie, HistoriqueModification
    
    log_action('FERIES', 'AFFICHER_DETAIL', f"Affichage détail férié {pk}", request=request)
    
    ferie = get_object_or_404(JourFerie, pk=pk)
    
    historique = HistoriqueModification.objects.filter(
        jour_ferie=ferie
    ).order_by('-date_action')[:10]
    
    est_modifiable = (
        ferie.type_ferie == 'FERIE_MUSULMAN' and
        ferie.modele and
        ferie.modele.est_modifiable
    )
    
    est_admin = user_est_admin(request.user)
    est_superuser = request.user.is_superuser
    
    duree_ms = (time.time() - start_time) * 1000
    log_action('FERIES', 'DETAIL_AFFICHE', f"Détail {ferie.nom} affiché",
              request=request, ferie_id=pk, duree_ms=f"{duree_ms:.0f}")
    
    context = {
        'ferie': ferie,
        'historique': historique,
        'est_modifiable': est_modifiable,
        'est_admin': est_admin,
        'est_superuser': est_superuser,
        'today': date.today(),
    }
    
    return render(request, 'jourferie_afficher.html', context)


# =============================================================================
# CRÉER UN JOUR FÉRIÉ INTERNE
# =============================================================================

@login_required
def jourferie_creer(request):
    """
    Crée un nouveau jour férié interne
    """
    start_time = time.time()
    
    from mainapp.models import JourFerie, TypeJourFerie
    
    log_action('FERIES', 'ACCES_CREATION', "Accès formulaire création férié", request=request)
    
    if not user_est_admin(request.user) or not request.user.is_superuser:
        log_anomalie('FERIES', "Accès création non autorisé", severite='WARNING', request=request)
        messages.error(request, "Vous n'avez pas les droits pour créer un jour férié.")
        return redirect('jourferie_liste')
    
    if request.method == 'POST':
        try:
            nom = request.POST.get('nom', '').strip()
            date_ferie_str = request.POST.get('date_ferie', '')
            description = request.POST.get('description', '').strip()
            est_paye = request.POST.get('est_paye') == 'on'
            
            log_action('FERIES', 'TENTATIVE_CREATION', f"Tentative création férié: {nom}",
                      request=request, date=date_ferie_str)
            
            if not nom:
                raise ValidationError("Le nom du jour férié est obligatoire.")
            
            if not date_ferie_str:
                raise ValidationError("La date est obligatoire.")
            
            try:
                date_ferie = datetime.strptime(date_ferie_str, '%Y-%m-%d').date()
            except ValueError:
                raise ValidationError("Format de date invalide.")
            
            with transaction.atomic():
                ferie = JourFerie.objects.creer_personnalise(
                    annee=date_ferie.year,
                    date_ferie=date_ferie,
                    nom=nom,
                    type_ferie=TypeJourFerie.FERIE_INTERNE,
                    description=description,
                    est_national=False,
                    est_paye=est_paye,
                    code_pays='CI',
                    utilisateur=request.user.get_full_name() or request.user.username
                )
                
                invalider_cache_ferie()
                
                duree_ms = (time.time() - start_time) * 1000
                log_action('FERIES', 'CREATION_REUSSIE', f"Férié créé: {nom} ({date_ferie})",
                          request=request, ferie_id=ferie.pk)
                
                log_resume('CREATION_JOUR_FERIE', {
                    'ferie_id': ferie.pk,
                    'nom': nom,
                    'date': date_ferie.isoformat(),
                    'type': 'INTERNE',
                    'est_paye': est_paye,
                    'cree_par': request.user.username,
                }, duree_ms=duree_ms)
                
                messages.success(request, f"Le jour férié '{nom}' a été créé avec succès.")
                return redirect('jourferie_afficher', pk=ferie.pk)
        
        except ValidationError as e:
            log_anomalie('FERIES', f"Validation échouée: {e}", severite='INFO', request=request)
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            log_erreur('FERIES', "Erreur création jour férié", exception=e, request=request)
            messages.error(request, f"Erreur lors de la création : {e}")
    
    annee_courante = date.today().year
    
    context = {
        'annee_courante': annee_courante,
        'today': date.today(),
    }
    
    return render(request, 'jourferie_creer.html', context)


# =============================================================================
# MODIFIER UN JOUR FÉRIÉ MUSULMAN
# =============================================================================

@login_required
def jourferiemusulman_modifier(request, pk):
    """
    Modifie la date d'un jour férié musulman
    """
    start_time = time.time()
    
    from mainapp.models import JourFerie, HistoriqueModification
    
    log_action('FERIES', 'ACCES_MODIFICATION', f"Accès modification férié musulman {pk}",
              request=request, ferie_id=pk)
    
    ferie = get_object_or_404(JourFerie, pk=pk)
    
    if not user_est_admin(request.user) or not request.user.is_superuser:
        log_anomalie('FERIES', "Modification non autorisée", severite='WARNING', request=request)
        messages.error(request, "Vous n'avez pas les droits pour modifier ce jour férié.")
        return redirect('jourferie_afficher', pk=pk)
    
    if ferie.type_ferie != 'FERIE_MUSULMAN':
        log_anomalie('FERIES', f"Tentative modification férié non-musulman: {ferie.type_ferie}",
                    severite='WARNING', request=request, ferie_id=pk)
        messages.error(request, "Seuls les jours fériés musulmans peuvent être modifiés.")
        return redirect('jourferie_afficher', pk=pk)
    
    if ferie.modele and not ferie.modele.est_modifiable:
        log_anomalie('FERIES', f"Férié {pk} non modifiable", severite='INFO', request=request)
        messages.error(request, "Ce jour férié n'est pas modifiable.")
        return redirect('jourferie_afficher', pk=pk)
    
    if request.method == 'POST':
        action = request.POST.get('action', 'modifier')
        
        try:
            with transaction.atomic():
                if action == 'reinitialiser':
                    if not ferie.date_calculee:
                        raise ValidationError("Impossible de réinitialiser : pas de date calculée.")
                    
                    ancienne_date = ferie.date_ferie
                    ferie.reinitialiser_date(
                        utilisateur=request.user.get_full_name() or request.user.username
                    )
                    
                    invalider_cache_ferie()
                    
                    log_action('FERIES', 'REINITIALISATION_REUSSIE',
                              f"Férié {ferie.nom} réinitialisé: {ancienne_date} -> {ferie.date_ferie}",
                              request=request)
                    
                    messages.success(request, f"La date de '{ferie.nom}' a été réinitialisée.")
                    
                else:
                    nouvelle_date_str = request.POST.get('nouvelle_date', '')
                    motif = request.POST.get('motif', '').strip()
                    source = request.POST.get('source', '').strip()
                    
                    if not nouvelle_date_str:
                        raise ValidationError("La nouvelle date est obligatoire.")
                    
                    if not motif:
                        raise ValidationError("Le motif de modification est obligatoire.")
                    
                    try:
                        nouvelle_date = datetime.strptime(nouvelle_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        raise ValidationError("Format de date invalide.")
                    
                    motif_complet = motif
                    if source:
                        motif_complet += f" (Source: {source})"
                    
                    ancienne_date = ferie.date_ferie
                    ferie.modifier_date(
                        nouvelle_date=nouvelle_date,
                        motif=motif_complet,
                        utilisateur=request.user.get_full_name() or request.user.username
                    )
                    
                    invalider_cache_ferie()
                    
                    duree_ms = (time.time() - start_time) * 1000
                    log_action('FERIES', 'MODIFICATION_REUSSIE',
                              f"Férié {ferie.nom} modifié: {ancienne_date} -> {nouvelle_date}",
                              request=request)
                    
                    log_resume('MODIFICATION_FERIE_MUSULMAN', {
                        'ferie': ferie.nom,
                        'ancienne_date': ancienne_date.isoformat(),
                        'nouvelle_date': nouvelle_date.isoformat(),
                        'motif': motif[:50] + '...' if len(motif) > 50 else motif,
                        'modifie_par': request.user.username,
                    }, duree_ms=duree_ms)
                    
                    messages.success(request, f"La date de '{ferie.nom}' a été modifiée.")
                
                return redirect('jourferie_afficher', pk=pk)
        
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            log_erreur('FERIES', "Erreur modification jour férié", exception=e, request=request)
            messages.error(request, f"Erreur lors de la modification : {e}")
    
    historique = HistoriqueModification.objects.filter(
        jour_ferie=ferie
    ).order_by('-date_action')[:5]
    
    context = {
        'ferie': ferie,
        'historique': historique,
        'today': date.today(),
    }
    
    return render(request, 'jourferiemusulman_modifier.html', context)


# =============================================================================
# SUPPRIMER UN JOUR FÉRIÉ
# =============================================================================

@login_required
@require_POST
def jourferie_supprimer(request, pk):
    """
    Supprime (désactive) un jour férié
    """
    start_time = time.time()
    
    from mainapp.models import JourFerie
    
    log_action('FERIES', 'TENTATIVE_SUPPRESSION', f"Tentative suppression férié {pk}",
              request=request, ferie_id=pk)
    
    ferie = get_object_or_404(JourFerie, pk=pk)
    
    if not user_est_admin(request.user) or not request.user.is_superuser:
        log_anomalie('FERIES', "Suppression non autorisée", severite='WARNING', request=request)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Droits insuffisants"}, status=403)
        messages.error(request, "Vous n'avez pas les droits pour supprimer ce jour férié.")
        return redirect('jourferie_liste')
    
    if ferie.type_ferie != 'FERIE_INTERNE' and not ferie.est_personnalise:
        log_anomalie('FERIES', f"Tentative suppression férié non-interne: {ferie.type_ferie}",
                    severite='WARNING', request=request, ferie_id=pk)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False, 
                'error': "Seuls les jours fériés internes peuvent être supprimés"
            }, status=400)
        messages.error(request, "Seuls les jours fériés internes peuvent être supprimés.")
        return redirect('jourferie_afficher', pk=pk)
    
    try:
        motif = request.POST.get('motif', 'Suppression manuelle')
        nom = ferie.nom
        
        ferie.desactiver(
            motif=motif,
            utilisateur=request.user.get_full_name() or request.user.username
        )
        
        invalider_cache_ferie()
        
        duree_ms = (time.time() - start_time) * 1000
        log_action('FERIES', 'SUPPRESSION_REUSSIE', f"Férié supprimé: {nom}",
                  request=request, ferie_id=pk)
        
        log_resume('SUPPRESSION_JOUR_FERIE', {
            'ferie_id': pk,
            'nom': nom,
            'motif': motif,
            'supprime_par': request.user.username,
        }, duree_ms=duree_ms)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': f"'{nom}' a été supprimé."})
        
        messages.success(request, f"Le jour férié '{nom}' a été supprimé.")
        return redirect('jourferie_liste')
    
    except Exception as e:
        log_erreur('FERIES', "Erreur suppression jour férié", exception=e, request=request)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        messages.error(request, f"Erreur lors de la suppression : {e}")
        return redirect('jourferie_afficher', pk=pk)


# =============================================================================
# APIS AJAX
# =============================================================================

@login_required
@require_GET
def api_jourferie_details(request, pk):
    """
    API pour récupérer les détails d'un jour férié en JSON
    """
    start_time = time.time()
    
    from mainapp.models import JourFerie
    
    log_action('FERIES', 'API_DETAILS', f"API détails férié {pk}", request=request)
    
    ferie = get_object_or_404(JourFerie, pk=pk)
    
    data = {
        'id': ferie.pk,
        'nom': ferie.nom,
        'date_ferie': ferie.date_ferie.isoformat(),
        'date_ferie_formatee': ferie.date_ferie.strftime('%d/%m/%Y'),
        'date_calculee': ferie.date_calculee.isoformat() if ferie.date_calculee else None,
        'type_ferie': ferie.type_ferie,
        'type_ferie_display': ferie.get_type_ferie_display(),
        'statut': ferie.statut,
        'est_modifie': ferie.est_modifie,
        'est_personnalise': ferie.est_personnalise,
        'est_national': ferie.est_national,
        'est_paye': ferie.est_paye,
        'jour_semaine': ferie.jour_semaine,
        'jours_avant': ferie.jours_avant,
        'description': ferie.description,
        'annee': ferie.annee,
    }
    
    duree_ms = (time.time() - start_time) * 1000
    log_action('FERIES', 'API_DETAILS_OK', f"Détails {ferie.nom} retournés",
              request=request, duree_ms=f"{duree_ms:.0f}")
    
    return JsonResponse(data)


@login_required
@require_GET  
def api_jourferie_liste(request):
    """
    API pour récupérer la liste des jours fériés en JSON
    """
    start_time = time.time()
    
    from mainapp.models import JourFerie, TypeJourFerie
    
    log_action('FERIES', 'API_LISTE', "API liste jours fériés", request=request)
    
    annee = request.GET.get('annee', date.today().year)
    type_filtre = request.GET.get('type', '')
    
    try:
        annee = int(annee)
    except (ValueError, TypeError):
        annee = date.today().year
    
    feries = JourFerie.objects.filter(
        annee=annee,
        code_pays='CI',
        statut='ACTIF'
    ).select_related('modele').order_by('date_ferie')
    
    if type_filtre and type_filtre in dict(TypeJourFerie.choices):
        feries = feries.filter(type_ferie=type_filtre)
    
    data = []
    for f in feries:
        est_modifiable = (
            f.type_ferie == 'FERIE_MUSULMAN' and
            f.modele and
            f.modele.est_modifiable
        )
        
        data.append({
            'id': f.pk,
            'nom': f.nom,
            'date_ferie': f.date_ferie.isoformat(),
            'date_ferie_formatee': f.date_ferie.strftime('%d/%m/%Y'),
            'type_ferie': f.type_ferie,
            'type_ferie_display': f.get_type_ferie_display(),
            'jour_semaine': f.jour_semaine,
            'jours_avant': f.jours_avant,
            'est_modifie': f.est_modifie,
            'est_personnalise': f.est_personnalise,
            'est_modifiable': est_modifiable,
            'peut_supprimer': f.type_ferie == 'FERIE_INTERNE' or f.est_personnalise,
        })
    
    duree_ms = (time.time() - start_time) * 1000
    log_resume('API_LISTE_FERIES', {
        'annee': annee,
        'type_filtre': type_filtre or 'aucun',
        'nb_feries': len(data),
    }, duree_ms=duree_ms)
    
    return JsonResponse({'feries': data, 'annee': annee, 'count': len(data)})