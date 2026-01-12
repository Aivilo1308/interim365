# -*- coding: utf-8 -*-
"""
Vues de gestion des utilisateurs
Liste, recherche, filtrage et création de super utilisateurs
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import ProfilUtilisateur, Departement, Site

logger = logging.getLogger(__name__)

# ================================================================
# CONFIGURATION LOGGING AVANCÉ
# ================================================================

import time
import traceback

logger = logging.getLogger('interim')
action_logger = logging.getLogger('interim.actions')
anomaly_logger = logging.getLogger('interim.anomalies')
perf_logger = logging.getLogger('interim.performance')


def log_action(category, action, message, request=None, **kwargs):
    """Log une action utilisateur avec contexte complet"""
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
    """Log une anomalie détectée avec niveau de sévérité"""
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
    """Log un résumé d'opération avec statistiques visuelles"""
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
        icon = '✅' if 'succes' in key.lower() or 'ok' in key.lower() or 'cree' in key.lower() else \
               '❌' if 'erreur' in key.lower() or 'echec' in key.lower() else \
               '⚠️' if 'warning' in key.lower() or 'anomal' in key.lower() else '•'
        lines.append(f"   {icon} {key}: {value}")
    
    lines.extend(["=" * 60, ""])
    
    resume_text = '\n'.join(lines)
    perf_logger.info(resume_text)
    logger.info(resume_text)


def log_erreur(category, message, exception=None, request=None, **kwargs):
    """Log une erreur avec stack trace complète"""
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



def is_admin_or_rh(user):
    """Vérifie si l'utilisateur est admin ou RH"""
    if user.is_superuser:
        return True
    if hasattr(user, 'profilutilisateur'):
        return user.profilutilisateur.type_profil in ['ADMIN', 'RH']
    return False


@login_required
@user_passes_test(is_admin_or_rh)
def admin_users_liste(request):
    """
    Vue de liste des utilisateurs avec pagination, recherche et filtres
    """
    # Récupération des paramètres de recherche et filtres
    search_query = request.GET.get('search', '').strip()
    type_profil_filter = request.GET.get('type_profil', '')
    statut_filter = request.GET.get('statut', '')
    departement_filter = request.GET.get('departement', '')
    source_filter = request.GET.get('source', '')  # kelio, local, tous
    actif_filter = request.GET.get('actif', '')
    sort_by = request.GET.get('sort', '-created_at')
    per_page = request.GET.get('per_page', '25')
    
    # Query de base avec optimisations
    users_qs = ProfilUtilisateur.objects.select_related(
        'user', 'departement', 'site', 'poste', 'manager'
    ).all()
    
    # Application des filtres
    if search_query:
        users_qs = users_qs.filter(
            Q(matricule__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(kelio_badge_code__icontains=search_query)
        )
    
    if type_profil_filter:
        users_qs = users_qs.filter(type_profil=type_profil_filter)
    
    if statut_filter:
        users_qs = users_qs.filter(statut_employe=statut_filter)
    
    if departement_filter:
        users_qs = users_qs.filter(departement_id=departement_filter)
    
    if source_filter == 'kelio':
        users_qs = users_qs.filter(kelio_employee_key__isnull=False)
    elif source_filter == 'local':
        users_qs = users_qs.filter(kelio_employee_key__isnull=True)
    
    if actif_filter == 'actif':
        users_qs = users_qs.filter(actif=True)
    elif actif_filter == 'inactif':
        users_qs = users_qs.filter(actif=False)
    
    # Tri
    valid_sorts = [
        'matricule', '-matricule',
        'user__last_name', '-user__last_name',
        'user__first_name', '-user__first_name',
        'type_profil', '-type_profil',
        'departement__nom', '-departement__nom',
        'created_at', '-created_at',
        'kelio_last_sync', '-kelio_last_sync',
    ]
    if sort_by not in valid_sorts:
        sort_by = '-created_at'
    
    users_qs = users_qs.order_by(sort_by)
    
    # Statistiques
    stats = {
        'total': ProfilUtilisateur.objects.count(),
        'actifs': ProfilUtilisateur.objects.filter(actif=True).count(),
        'kelio': ProfilUtilisateur.objects.filter(kelio_employee_key__isnull=False).count(),
        'locaux': ProfilUtilisateur.objects.filter(kelio_employee_key__isnull=True).count(),
        'superusers': User.objects.filter(is_superuser=True).count(),
        'filtres_actifs': users_qs.count(),
    }
    
    # Pagination
    try:
        per_page = int(per_page)
        if per_page not in [10, 25, 50, 100]:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25
    
    paginator = Paginator(users_qs, per_page)
    page = request.GET.get('page', 1)
    
    try:
        users_page = paginator.page(page)
    except PageNotAnInteger:
        users_page = paginator.page(1)
    except EmptyPage:
        users_page = paginator.page(paginator.num_pages)
    
    # Données pour les filtres
    departements = Departement.objects.filter(actif=True).order_by('nom')
    types_profil = ProfilUtilisateur.TYPES_PROFIL
    statuts_employe = ProfilUtilisateur.STATUTS_EMPLOYE
    
    context = {
        'users': users_page,
        'stats': stats,
        'departements': departements,
        'types_profil': types_profil,
        'statuts_employe': statuts_employe,
        'search_query': search_query,
        'type_profil_filter': type_profil_filter,
        'statut_filter': statut_filter,
        'departement_filter': departement_filter,
        'source_filter': source_filter,
        'actif_filter': actif_filter,
        'sort_by': sort_by,
        'per_page': per_page,
        'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
    }
    
    return render(request, 'users_liste.html', context)


@login_required
@user_passes_test(is_admin_or_rh)
def ajouter_superutilisateur(request):
    """
    Vue pour ajouter un super utilisateur non-Kelio
    """
    departements = Departement.objects.filter(actif=True).order_by('nom')
    sites = Site.objects.filter(actif=True).order_by('nom')
    types_profil = ProfilUtilisateur.TYPES_PROFIL
    
    if request.method == 'POST':
        # Récupération des données du formulaire
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        matricule = request.POST.get('matricule', '').strip()
        type_profil = request.POST.get('type_profil', 'ADMIN')
        departement_id = request.POST.get('departement', '')
        site_id = request.POST.get('site', '')
        is_superuser = request.POST.get('is_superuser') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        
        errors = []
        
        # Validations
        if not username:
            errors.append("Le nom d'utilisateur est obligatoire")
        elif User.objects.filter(username=username).exists():
            errors.append("Ce nom d'utilisateur existe déjà")
        
        if not email:
            errors.append("L'email est obligatoire")
        elif User.objects.filter(email=email).exists():
            errors.append("Cet email est déjà utilisé")
        
        if not password:
            errors.append("Le mot de passe est obligatoire")
        elif len(password) < 8:
            errors.append("Le mot de passe doit contenir au moins 8 caractères")
        elif password != password_confirm:
            errors.append("Les mots de passe ne correspondent pas")
        
        if not matricule:
            errors.append("Le matricule est obligatoire")
        elif ProfilUtilisateur.objects.filter(matricule=matricule).exists():
            errors.append("Ce matricule existe déjà")
        
        if not first_name:
            errors.append("Le prénom est obligatoire")
        
        if not last_name:
            errors.append("Le nom est obligatoire")
        
        if errors:
            for error in errors:
                messages.error(request, error)
            
            context = {
                'departements': departements,
                'sites': sites,
                'types_profil': types_profil,
                'form_data': request.POST,
                'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
            }
            return render(request, 'ajouter_superutilisateur.html', context)
        
        try:
            # Création de l'utilisateur Django
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_superuser=is_superuser,
                is_staff=is_staff or is_superuser,  # Superuser implique staff
                is_active=True
            )
            
            # Création du profil utilisateur
            profil = ProfilUtilisateur.objects.create(
                user=user,
                matricule=matricule,
                type_profil=type_profil,
                statut_employe='ACTIF',
                departement_id=departement_id if departement_id else None,
                site_id=site_id if site_id else None,
                actif=True,
                kelio_sync_status='JAMAIS',  # Non synchronisé avec Kelio
            )
            
            logger.info(f"[USERS] Super utilisateur créé: {username} (matricule: {matricule}) par {request.user.username}")
            
            messages.success(
                request, 
                f"✅ Utilisateur '{first_name} {last_name}' créé avec succès ! "
                f"{'(Super administrateur)' if is_superuser else ''}"
            )
            
            return redirect('admin_users_liste')
            
        except Exception as e:
            logger.error(f"[USERS] Erreur création utilisateur: {e}")
            messages.error(request, f"Erreur lors de la création : {str(e)}")
    
    context = {
        'departements': departements,
        'sites': sites,
        'types_profil': types_profil,
        'form_data': {},
        'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
    }
    
    return render(request, 'ajouter_superutilisateur.html', context)


@login_required
@user_passes_test(is_admin_or_rh)
def toggle_user_actif(request, user_id):
    """Active/désactive un utilisateur via AJAX"""
    if request.method == 'POST':
        try:
            profil = get_object_or_404(ProfilUtilisateur, pk=user_id)
            
            # Empêcher de se désactiver soi-même
            if profil.user == request.user:
                return JsonResponse({
                    'success': False,
                    'message': "Vous ne pouvez pas vous désactiver vous-même"
                })
            
            profil.actif = not profil.actif
            profil.save(update_fields=['actif', 'updated_at'])
            
            if profil.user:
                profil.user.is_active = profil.actif
                profil.user.save(update_fields=['is_active'])
            
            action = "activé" if profil.actif else "désactivé"
            logger.info(f"[USERS] Utilisateur {profil.matricule} {action} par {request.user.username}")
            
            return JsonResponse({
                'success': True,
                'actif': profil.actif,
                'message': f"Utilisateur {action} avec succès"
            })
            
        except Exception as e:
            logger.error(f"[USERS] Erreur toggle actif: {e}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            })
    
    return JsonResponse({'success': False, 'message': 'Méthode non autorisée'})


@login_required
@user_passes_test(is_admin_or_rh)
def user_detail_ajax(request, user_id):
    """Retourne les détails d'un utilisateur en JSON pour modal"""
    try:
        profil = get_object_or_404(
            ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste', 'manager'
            ),
            pk=user_id
        )
        
        data = {
            'success': True,
            'user': {
                'id': profil.pk,
                'matricule': profil.matricule,
                'nom_complet': profil.nom_complet,
                'username': profil.user.username if profil.user else '-',
                'email': profil.user.email if profil.user else '-',
                'type_profil': profil.get_type_profil_display(),
                'type_profil_code': profil.type_profil,
                'statut_employe': profil.get_statut_employe_display(),
                'departement': profil.departement.nom if profil.departement else '-',
                'site': str(profil.site) if profil.site else '-',
                'poste': str(profil.poste) if profil.poste else '-',
                'manager': profil.manager.nom_complet if profil.manager else '-',
                'actif': profil.actif,
                'is_superuser': profil.user.is_superuser if profil.user else False,
                'is_staff': profil.user.is_staff if profil.user else False,
                'date_embauche': profil.date_embauche.strftime('%d/%m/%Y') if profil.date_embauche else '-',
                'kelio_employee_key': profil.kelio_employee_key,
                'kelio_badge_code': profil.kelio_badge_code or '-',
                'kelio_last_sync': profil.kelio_last_sync.strftime('%d/%m/%Y %H:%M') if profil.kelio_last_sync else 'Jamais',
                'kelio_sync_status': profil.kelio_sync_status,
                'source': 'Kelio' if profil.kelio_employee_key else 'Local',
                'created_at': profil.created_at.strftime('%d/%m/%Y %H:%M'),
                'updated_at': profil.updated_at.strftime('%d/%m/%Y %H:%M'),
            }
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        logger.error(f"[USERS] Erreur détail user: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_admin_or_rh)
@require_http_methods(["POST"])
def reset_user_password(request, user_id):
    """Réinitialise le mot de passe d'un utilisateur"""
    try:
        profil = get_object_or_404(ProfilUtilisateur, pk=user_id)
        
        if not profil.user:
            return JsonResponse({
                'success': False,
                'message': "Cet utilisateur n'a pas de compte Django associé"
            })
        
        new_password = request.POST.get('new_password', '')
        
        if len(new_password) < 8:
            return JsonResponse({
                'success': False,
                'message': "Le mot de passe doit contenir au moins 8 caractères"
            })
        
        profil.user.set_password(new_password)
        profil.user.save()
        
        logger.info(f"[USERS] Mot de passe réinitialisé pour {profil.matricule} par {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'message': "Mot de passe réinitialisé avec succès"
        })
        
    except Exception as e:
        logger.error(f"[USERS] Erreur reset password: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_admin_or_rh)
def user_details(request, matricule):
    """
    Vue détaillée d'un utilisateur avec toutes ses informations
    Paramètre: matricule (str) - Le matricule de l'utilisateur
    """
    from .models import (
        AbsenceUtilisateur, FormationUtilisateur, CompetenceUtilisateur,
        ProfilUtilisateurExtended, ProfilUtilisateurKelio
    )
    
    # Récupérer le profil avec toutes les relations via le matricule
    profil = get_object_or_404(
        ProfilUtilisateur.objects.select_related(
            'user', 'departement', 'site', 'poste', 'manager'
        ),
        matricule=matricule
    )
    
    # Données Kelio étendues
    kelio_data = None
    try:
        kelio_data = ProfilUtilisateurKelio.objects.filter(profil=profil).first()
    except:
        pass
    
    # Données étendues
    extended_data = None
    try:
        extended_data = ProfilUtilisateurExtended.objects.filter(profil=profil).first()
    except:
        pass
    
    # Absences (les plus récentes en premier)
    absences = []
    absences_stats = {'total': 0, 'en_cours': 0, 'a_venir': 0}
    try:
        absences_qs = AbsenceUtilisateur.objects.filter(
            utilisateur=profil
        ).order_by('-date_debut')[:10]
        absences = list(absences_qs)
        
        today = timezone.now().date()
        absences_stats['total'] = AbsenceUtilisateur.objects.filter(utilisateur=profil).count()
        absences_stats['en_cours'] = AbsenceUtilisateur.objects.filter(
            utilisateur=profil,
            date_debut__lte=today,
            date_fin__gte=today
        ).count()
        absences_stats['a_venir'] = AbsenceUtilisateur.objects.filter(
            utilisateur=profil,
            date_debut__gt=today
        ).count()
    except Exception as e:
        logger.warning(f"[USER-DETAILS] Erreur chargement absences: {e}")
    
    # Formations
    formations = []
    formations_stats = {'total': 0}
    try:
        formations_qs = FormationUtilisateur.objects.filter(
            utilisateur=profil
        ).order_by('-date_fin')[:10]
        formations = list(formations_qs)
        formations_stats['total'] = FormationUtilisateur.objects.filter(utilisateur=profil).count()
    except Exception as e:
        logger.warning(f"[USER-DETAILS] Erreur chargement formations: {e}")
    
    # Compétences
    competences = []
    competences_stats = {'total': 0}
    try:
        competences_qs = CompetenceUtilisateur.objects.filter(
            utilisateur=profil
        ).select_related('competence').order_by('-niveau_maitrise')[:15]
        competences = list(competences_qs)
        competences_stats['total'] = CompetenceUtilisateur.objects.filter(utilisateur=profil).count()
    except Exception as e:
        logger.warning(f"[USER-DETAILS] Erreur chargement compétences: {e}")
    
    # Équipe (si manager)
    equipe = []
    equipe_count = 0
    try:
        if profil.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN', 'CHEF_EQUIPE']:
            equipe_qs = ProfilUtilisateur.objects.filter(
                manager=profil, actif=True
            ).select_related('user', 'poste')[:10]
            equipe = list(equipe_qs)
            equipe_count = ProfilUtilisateur.objects.filter(manager=profil, actif=True).count()
    except Exception as e:
        logger.warning(f"[USER-DETAILS] Erreur chargement équipe: {e}")
    
    # Missions/Demandes d'intérim
    missions = []
    missions_stats = {'total': 0, 'en_cours': 0, 'terminees': 0}
    try:
        from .models import ReponseCandidatInterim
        missions_qs = ReponseCandidatInterim.objects.filter(
            candidat=profil
        ).select_related('demande').order_by('-created_at')[:10]
        missions = list(missions_qs)
        
        missions_stats['total'] = ReponseCandidatInterim.objects.filter(candidat=profil).count()
        missions_stats['en_cours'] = ReponseCandidatInterim.objects.filter(
            candidat=profil, statut='EN_COURS'
        ).count()
        missions_stats['terminees'] = ReponseCandidatInterim.objects.filter(
            candidat=profil, statut='TERMINEE'
        ).count()
    except Exception as e:
        logger.warning(f"[USER-DETAILS] Erreur chargement missions: {e}")
    
    # Historique des actions
    historique = []
    try:
        from .models import HistoriqueAction
        historique_qs = HistoriqueAction.objects.filter(
            utilisateur=profil
        ).select_related('utilisateur').order_by('-created_at')[:15]
        historique = list(historique_qs)
    except Exception as e:
        logger.warning(f"[USER-DETAILS] Erreur chargement historique: {e}")
    
    context = {
        'profil': profil,
        'kelio_data': kelio_data,
        'extended_data': extended_data,
        'absences': absences,
        'absences_stats': absences_stats,
        'formations': formations,
        'formations_stats': formations_stats,
        'competences': competences,
        'competences_stats': competences_stats,
        'equipe': equipe,
        'equipe_count': equipe_count,
        'missions': missions,
        'missions_stats': missions_stats,
        'historique': historique,
        'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
    }
    
    return render(request, 'user_details.html', context)


@login_required
@user_passes_test(is_admin_or_rh)
def user_modifier(request, matricule):
    """
    Vue pour modifier un utilisateur existant
    Paramètre: matricule (str) - Le matricule de l'utilisateur
    """
    # Récupérer le profil avec les relations
    profil = get_object_or_404(
        ProfilUtilisateur.objects.select_related(
            'user', 'departement', 'site', 'poste', 'manager'
        ),
        matricule=matricule
    )
    
    # Données pour les selects
    departements = Departement.objects.filter(actif=True).order_by('nom')
    sites = Site.objects.filter(actif=True).order_by('nom')
    types_profil = ProfilUtilisateur.TYPES_PROFIL
    statuts_employe = ProfilUtilisateur.STATUTS_EMPLOYE
    
    # Liste des managers potentiels (exclure l'utilisateur lui-même)
    managers_potentiels = ProfilUtilisateur.objects.filter(
        actif=True,
        type_profil__in=['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']
    ).exclude(pk=profil.pk).select_related('user').order_by('user__last_name', 'user__first_name')
    
    # Liste des postes
    from .models import Poste
    postes = Poste.objects.filter(actif=True).select_related('departement', 'site').order_by('titre')
    
    if request.method == 'POST':
        # Récupération des données du formulaire
        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        type_profil_form = request.POST.get('type_profil', profil.type_profil)
        statut_employe = request.POST.get('statut_employe', profil.statut_employe)
        departement_id = request.POST.get('departement', '')
        site_id = request.POST.get('site', '')
        poste_id = request.POST.get('poste', '')
        manager_id = request.POST.get('manager', '')
        date_embauche = request.POST.get('date_embauche', '')
        date_fin_contrat = request.POST.get('date_fin_contrat', '')
        is_superuser = request.POST.get('is_superuser') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        is_active = request.POST.get('is_active') == 'on'
        actif = request.POST.get('actif') == 'on'
        
        errors = []
        
        # Validations
        if not first_name:
            errors.append("Le prénom est obligatoire")
        
        if not last_name:
            errors.append("Le nom est obligatoire")
        
        if email:
            # Vérifier que l'email n'est pas déjà utilisé par un autre utilisateur
            from django.contrib.auth.models import User
            existing_email = User.objects.filter(email=email).exclude(pk=profil.user.pk if profil.user else None).exists()
            if existing_email:
                errors.append("Cet email est déjà utilisé par un autre utilisateur")
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            try:
                # Mise à jour de l'utilisateur Django
                if profil.user:
                    profil.user.email = email
                    profil.user.first_name = first_name
                    profil.user.last_name = last_name
                    profil.user.is_superuser = is_superuser
                    profil.user.is_staff = is_staff or is_superuser
                    profil.user.is_active = is_active
                    profil.user.save()
                
                # Mise à jour du profil
                profil.type_profil = type_profil_form
                profil.statut_employe = statut_employe
                profil.departement_id = departement_id if departement_id else None
                profil.site_id = site_id if site_id else None
                profil.poste_id = poste_id if poste_id else None
                profil.manager_id = manager_id if manager_id else None
                profil.actif = actif
                
                # Dates
                if date_embauche:
                    from datetime import datetime
                    profil.date_embauche = datetime.strptime(date_embauche, '%Y-%m-%d').date()
                else:
                    profil.date_embauche = None
                    
                if date_fin_contrat:
                    from datetime import datetime
                    profil.date_fin_contrat = datetime.strptime(date_fin_contrat, '%Y-%m-%d').date()
                else:
                    profil.date_fin_contrat = None
                
                profil.save()
                
                logger.info(f"[USERS] Utilisateur modifié: {profil.matricule} par {request.user.username}")
                
                messages.success(request, f"✅ Utilisateur '{first_name} {last_name}' modifié avec succès !")
                
                return redirect('user_details', matricule=profil.matricule)
                
            except Exception as e:
                logger.error(f"[USERS] Erreur modification utilisateur: {e}")
                messages.error(request, f"Erreur lors de la modification : {str(e)}")
    
    context = {
        'profil': profil,
        'departements': departements,
        'sites': sites,
        'postes': postes,
        'types_profil': types_profil,
        'statuts_employe': statuts_employe,
        'managers_potentiels': managers_potentiels,
        'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
    }
    
    return render(request, 'user_modifier.html', context)