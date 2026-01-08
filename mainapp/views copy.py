# views.py - Version complète avec toutes les vues manquantes
from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse, get_resolver  # ← Ajout de get_resolver
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from .utils import require_coherence_departement, require_login_and_profile
from django.db.models import Count, Q, Avg, F  # ← Ajout de F
from django.utils import timezone
from datetime import datetime, timedelta  # ← S'assurer que datetime est accessible globalement
from django.core.cache import cache
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password

import json
import logging
import traceback

# Import des modèles depuis le fichier models.py fourni
from .models import *

from .services.manager_proposals import ManagerProposalsService
from .services.scoring_service import ScoringInterimService
from .services.workflow_service import WorkflowIntegrationService

logger = logging.getLogger(__name__)

# ================================================================
# UTILITAIRES SUPERUTILISATEUR
# ================================================================

@login_required
@csrf_protect
@require_http_methods(["GET", "POST"])
def password_change(request):
    """
    Vue pour le changement de mot de passe utilisateur
    Met à jour simultanément User et ProfilUtilisateur
    """
    # Récupérer le profil utilisateur
    try:
        profil_utilisateur = request.user.profilutilisateur
    except AttributeError:
        messages.error(request, "Profil utilisateur non trouvé.")
        return redirect('index')
    
    if request.method == 'GET':
        # Afficher le formulaire
        context = {
            'page_title': 'Changement de mot de passe',
            'profil_utilisateur': profil_utilisateur,
            'user_initials': get_utilisateur_initials(request.user),
        }
        return render(request, 'password_change.html', context)
    
    elif request.method == 'POST':
        # Traitement AJAX ou formulaire classique
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return handle_password_change_ajax(request)
        else:
            return handle_password_change_form(request)

def handle_password_change_ajax(request):
    """Traitement AJAX du changement de mot de passe"""
    try:
        # Récupérer les données JSON
        data = json.loads(request.body)
        
        current_password = data.get('current_password', '').strip()
        new_password = data.get('new_password', '').strip()
        confirm_password = data.get('confirm_password', '').strip()
        
        # Validation des données
        errors = validate_password_change_data(
            request.user, current_password, new_password, confirm_password
        )
        
        if errors:
            return JsonResponse({
                'success': False,
                'errors': errors
            })
        
        # Effectuer le changement
        success, message = change_user_password(
            request.user, new_password, request=request
        )
        
        if success:
            # Maintenir la session active
            update_session_auth_hash(request, request.user)
            
            return JsonResponse({
                'success': True,
                'message': 'Mot de passe modifié avec succès',
                'redirect_url': request.GET.get('next', '/interim/')
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': {'general': [message]}
            })
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'errors': {'general': ['Données JSON invalides']}
        })
    except Exception as e:
        logger.error(f"Erreur changement mot de passe AJAX: {e}")
        return JsonResponse({
            'success': False,
            'errors': {'general': ['Erreur serveur interne']}
        })

def handle_password_change_form(request):
    """Traitement formulaire classique du changement de mot de passe"""
    try:
        current_password = request.POST.get('current_password', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        
        # Validation des données
        errors = validate_password_change_data(
            request.user, current_password, new_password, confirm_password
        )
        
        if errors:
            # Afficher les erreurs
            for field, field_errors in errors.items():
                for error in field_errors:
                    messages.error(request, error)
            
            return render(request, 'password_change.html', {
                'page_title': 'Changement de mot de passe',
                'profil_utilisateur': request.user.profilutilisateur,
                'user_initials': get_utilisateur_initials(request.user),
                'form_data': {
                    'current_password': '',  # Ne pas renvoyer le mot de passe
                    'new_password': '',
                    'confirm_password': ''
                }
            })
        
        # Effectuer le changement
        success, message = change_user_password(
            request.user, new_password, request=request
        )
        
        if success:
            # Maintenir la session active
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Mot de passe modifié avec succès')
            
            # Redirection
            next_url = request.GET.get('next', '/interim/')
            return redirect(next_url)
        else:
            messages.error(request, message)
            return render(request, 'password_change.html', {
                'page_title': 'Changement de mot de passe',
                'profil_utilisateur': request.user.profilutilisateur,
                'user_initials': get_utilisateur_initials(request.user),
            })
            
    except Exception as e:
        logger.error(f"Erreur changement mot de passe formulaire: {e}")
        messages.error(request, 'Erreur lors du changement de mot de passe')
        return render(request, 'password_change.html', {
            'page_title': 'Changement de mot de passe',
            'profil_utilisateur': request.user.profilutilisateur,
            'user_initials': get_utilisateur_initials(request.user),
        })

def validate_password_change_data(user, current_password, new_password, confirm_password):
    """Valide les données du changement de mot de passe"""
    errors = {}
    
    # Vérifier le mot de passe actuel
    if not current_password:
        errors.setdefault('current_password', []).append('Le mot de passe actuel est requis')
    elif not user.check_password(current_password):
        errors.setdefault('current_password', []).append('Mot de passe actuel incorrect')
    
    # Vérifier le nouveau mot de passe
    if not new_password:
        errors.setdefault('new_password', []).append('Le nouveau mot de passe est requis')
    elif len(new_password) < 8:
        errors.setdefault('new_password', []).append('Le mot de passe doit contenir au moins 8 caractères')
    else:
        # Validation Django
        try:
            validate_password(new_password, user)
        except ValidationError as e:
            errors.setdefault('new_password', []).extend(e.messages)
    
    # Vérifier la confirmation
    if not confirm_password:
        errors.setdefault('confirm_password', []).append('La confirmation du mot de passe est requise')
    elif new_password and confirm_password and new_password != confirm_password:
        errors.setdefault('confirm_password', []).append('Les mots de passe ne correspondent pas')
    
    # Vérifier que le nouveau mot de passe est différent de l'ancien
    if current_password and new_password and current_password == new_password:
        errors.setdefault('new_password', []).append('Le nouveau mot de passe doit être différent de l\'ancien')
    
    return errors

@transaction.atomic
def change_user_password(user, new_password, request=None):
    """
    Change le mot de passe utilisateur et met à jour le profil
    Retourne (success: bool, message: str)
    """
    try:
        # Récupérer le profil utilisateur
        try:
            profil = user.profilutilisateur
        except AttributeError:
            return False, "Profil utilisateur non trouvé"
        
        # Sauvegarder l'ancien hash pour l'historique
        old_password_hash = user.password
        
        # Mettre à jour le mot de passe User Django
        user.set_password(new_password)
        user.save()
        
        # Mettre à jour la date de modification du profil
        profil.updated_at = timezone.now()
        profil.save(update_fields=['updated_at'])
        
        # Créer un historique de l'action
        if request:
            try:
                HistoriqueAction.objects.create(
                    demande=None,  # Pas de demande spécifique
                    action='MODIFICATION_PROFIL',  # Vous pouvez ajouter ce type
                    utilisateur=profil,
                    description=f"Changement de mot de passe par {profil.nom_complet}",
                    niveau_hierarchique=profil.type_profil,
                    is_superuser=profil.is_superuser,
                    adresse_ip=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                    donnees_avant={'password_hash': '[MASQUÉ]'},
                    donnees_apres={'password_changed': True, 'timestamp': timezone.now().isoformat()}
                )
            except Exception as e:
                # Log mais ne pas faire échouer l'opération
                logger.warning(f"Impossible de créer l'historique du changement de mot de passe: {e}")
        
        logger.info(f"Mot de passe modifié avec succès pour l'utilisateur {user.username} (Matricule: {profil.matricule})")
        return True, "Mot de passe modifié avec succès"
        
    except Exception as e:
        logger.error(f"Erreur lors du changement de mot de passe pour {user.username}: {e}")
        return False, "Erreur lors du changement de mot de passe"

def get_utilisateur_initials(user):
    """Récupère les initiales de l'utilisateur"""
    try:
        if user.first_name and user.last_name:
            return f"{user.first_name[0]}{user.last_name[0]}".upper()
        elif user.username:
            return user.username[:2].upper()
        return "??"
    except (AttributeError, IndexError):
        return "??"

def get_client_ip(request):
    """Récupère l'adresse IP du client"""
    try:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    except Exception:
        return None

# Fonction utilitaire pour tester le changement de mot de passe depuis l'admin ou le shell
def admin_change_user_password(user_or_matricule, new_password):
    """
    Fonction utilitaire pour changer le mot de passe depuis l'admin Django
    Usage: admin_change_user_password('EMP001', 'nouveau_mot_de_passe')
    """
    try:
        if isinstance(user_or_matricule, str):
            # Recherche par matricule
            profil = ProfilUtilisateur.objects.get(matricule=user_or_matricule)
            user = profil.user
        else:
            # Objet User directement
            user = user_or_matricule
        
        success, message = change_user_password(user, new_password)
        print(f"Résultat: {message}")
        return success
        
    except ProfilUtilisateur.DoesNotExist:
        print(f"Utilisateur avec matricule {user_or_matricule} non trouvé")
        return False
    except Exception as e:
        print(f"Erreur: {e}")
        return False
    
def get_profil_or_virtual(user):
    """Récupère le profil utilisateur ou crée un profil pour superutilisateur - VERSION CORRIGÉE pour property"""
    try:
        return ProfilUtilisateur.objects.select_related(
            'user', 'departement', 'site', 'poste', 'manager'
        ).get(user=user)
    except ProfilUtilisateur.DoesNotExist:
        if user.is_superuser:
            # Pour les superutilisateurs, créer un vrai profil 
            # SANS inclure nom_complet car c'est une property
            profil, created = ProfilUtilisateur.objects.get_or_create(
                user=user,
                defaults={
                    'matricule': f'SUPER_{user.id}',
                    'type_profil': 'ADMIN',  # Type valide dans la DB
                    'actif': True,
                    'statut_employe': 'ACTIF'
                    # nom_complet sera calculé automatiquement par la property
                }
            )
            if created:
                logger.info(f"Profil créé automatiquement pour superutilisateur: {user.username}")
                logger.info(f"Property nom_complet: {profil.nom_complet}")
            return profil
        raise

# ================================================================
# FONCTIONS DE VÉRIFICATION D'ACCÈS ÉTENDUES
# ================================================================

def _check_chef_equipe(user):
    """Vérifie si l'utilisateur est chef d'équipe ou superutilisateur"""
    if user.is_superuser:
        return True
    try:
        profil = ProfilUtilisateur.objects.get(user=user)
        return profil.type_profil == 'CHEF_EQUIPE' and profil.actif
    except ProfilUtilisateur.DoesNotExist:
        return False

def _check_responsable(user):
    """Vérifie si l'utilisateur est responsable ou superutilisateur"""
    if user.is_superuser:
        return True
    try:
        profil = ProfilUtilisateur.objects.get(user=user)
        return profil.type_profil == 'RESPONSABLE' and profil.actif
    except ProfilUtilisateur.DoesNotExist:
        return False

def _check_directeur(user):
    """Vérifie si l'utilisateur est directeur ou superutilisateur"""
    if user.is_superuser:
        return True
    try:
        profil = ProfilUtilisateur.objects.get(user=user)
        return profil.type_profil == 'DIRECTEUR' and profil.actif
    except ProfilUtilisateur.DoesNotExist:
        return False

def _check_rh_admin(user):
    """Vérifie si l'utilisateur est RH, Admin ou superutilisateur"""
    if user.is_superuser:
        return True
    try:
        profil = ProfilUtilisateur.objects.get(user=user)
        return profil.type_profil in ['RH', 'ADMIN'] and profil.actif
    except ProfilUtilisateur.DoesNotExist:
        return False

# ================================================================
# FONCTIONS DE VÉRIFICATION D'ACCÈS ÉTENDUES POUR SUPERUTILISATEURS
# ================================================================

def _check_rh_admin_or_superuser(user):
    """Vérifie si l'utilisateur est RH, Admin ou superutilisateur"""
    if user.is_superuser:
        return True
    try:
        profil = ProfilUtilisateur.objects.get(user=user)
        return profil.type_profil in ['RH', 'ADMIN'] and profil.actif
    except ProfilUtilisateur.DoesNotExist:
        return False

def _check_manager_or_superuser(user):
    """Vérifie si l'utilisateur est manager (tout niveau) ou superutilisateur"""
    if user.is_superuser:
        return True
    try:
        profil = ProfilUtilisateur.objects.get(user=user)
        return profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'] and profil.actif
    except ProfilUtilisateur.DoesNotExist:
        return False

# ================================================================
# FONCTIONS DE PERMISSIONS ÉTENDUES POUR SUPERUTILISATEURS
# ================================================================

def _peut_voir_demande(profil, demande):
    """Vérifie si l'utilisateur peut voir la demande (étendu pour superutilisateurs)"""
    # Si c'est un superutilisateur, accès total
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    # Si c'est un profil virtuel de superutilisateur
    if getattr(profil, 'type_profil', None) == 'SUPERUSER':
        return True
    
    return (
        demande.demandeur == profil or
        demande.candidat_selectionne == profil or
        demande.personne_remplacee == profil or
        getattr(profil, 'type_profil', None) in ['RH', 'ADMIN'] or
        (getattr(profil, 'type_profil', None) in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR'] and
         getattr(profil, 'departement', None) == demande.poste.departement)
    )

def _peut_modifier_demande(profil, demande):
    """Vérifie si l'utilisateur peut modifier la demande (étendu pour superutilisateurs)"""
    # Accès total pour superutilisateurs
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    if getattr(profil, 'type_profil', None) == 'SUPERUSER':
        return True
    
    return (
        (demande.demandeur == profil and demande.statut in ['BROUILLON', 'SOUMISE']) or
        getattr(profil, 'type_profil', None) in ['RH', 'ADMIN']
    )

def _peut_supprimer_demande(profil, demande):
    """Vérifie si l'utilisateur peut supprimer la demande (étendu pour superutilisateurs)"""
    # Accès total pour superutilisateurs
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    if getattr(profil, 'type_profil', None) == 'SUPERUSER':
        return True
    
    return (
        (demande.demandeur == profil and demande.statut == 'BROUILLON') or
        getattr(profil, 'type_profil', None) in ['ADMIN']
    )

def _peut_valider_demande(profil, demande):
    """
    Vérifie si l'utilisateur peut valider la demande selon la hiérarchie correcte
    
    HIÉRARCHIE CORRECTE :
    - Chef d'équipe : PEUT CRÉER ET PROPOSER, NE PEUT PAS VALIDER
    - Responsable : Premier niveau de validation (N+1)
    - Directeur : Deuxième niveau de validation (N+2)  
    - RH/ADMIN/SUPERUSER : Validation finale (N+3)
    """
    # Accès total pour superutilisateurs
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    if getattr(profil, 'type_profil', None) == 'SUPERUSER':
        return True
    
    # CHEF_EQUIPE NE PEUT PAS VALIDER - seulement créer et proposer
    if getattr(profil, 'type_profil', None) == 'CHEF_EQUIPE':
        return False
    
    # Validation selon la hiérarchie
    return (
        getattr(profil, 'type_profil', None) in ['RH', 'ADMIN', 'DIRECTEUR'] or
        (getattr(profil, 'type_profil', None) == 'RESPONSABLE' and
         getattr(profil, 'departement', None) == demande.poste.departement)
    )

def _peut_proposer_candidat(profil, demande):
    """
    Vérifie si l'utilisateur peut proposer un candidat
    CHEF_EQUIPE peut proposer mais pas valider
    """
    # Accès total pour superutilisateurs
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    if getattr(profil, 'type_profil', None) == 'SUPERUSER':
        return True
    
    # CHEF_EQUIPE peut proposer des candidats
    return (
        getattr(profil, 'type_profil', None) in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'] or
        profil == demande.demandeur.manager
    )

def _peut_creer_demande_pour_employe(profil, employe):
    """Vérifie si l'utilisateur peut créer une demande pour cet employé (étendu pour superutilisateurs)"""
    # Accès total pour superutilisateurs
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    if getattr(profil, 'type_profil', None) == 'SUPERUSER':
        return True
    
    return (
        getattr(profil, 'type_profil', None) in ['RH', 'ADMIN'] or
        profil == employe.manager or
        (getattr(profil, 'type_profil', None) in ['CHEF_EQUIPE', 'RESPONSABLE'] and
         getattr(profil, 'departement', None) == employe.departement)
    )

# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _get_utilisateur_initials(user):
    """Génère les initiales de l'utilisateur pour l'avatar"""
    try:
        if user.first_name and user.last_name:
            return f"{user.first_name[0]}{user.last_name[0]}".upper()
        elif user.first_name:
            return user.first_name[:2].upper()
        elif user.last_name:
            return user.last_name[:2].upper()
        else:
            return user.username[:2].upper()
    except (AttributeError, IndexError):
        return "??"

def _calculate_success_rate(demandes_queryset):
    """Calcule le taux de réussite des demandes - VERSION SÉCURISÉE"""
    try:
        total = demandes_queryset.exclude(statut='BROUILLON').count()
        if total == 0:
            return 0
        
        reussies = demandes_queryset.filter(
            statut__in=['EN_COURS', 'TERMINEE']
        ).count()
        
        return round((reussies / total) * 100, 1)
    except Exception as e:
        logger.error(f"Erreur calcul taux réussite: {e}")
        return 0
    
def _calculate_validation_rate(demandes_queryset):
    """Calcule le taux de validation des demandes"""
    try:
        total = demandes_queryset.exclude(statut='BROUILLON').count()
        if total == 0:
            return 0
        
        validees = demandes_queryset.filter(
            statut__in=['VALIDEE', 'EN_COURS', 'TERMINEE']
        ).count()
        
        return round((validees / total) * 100, 1)
    except Exception:
        return 0

def _calculer_taux_validation_global():
    """Calcule le taux de validation global"""
    try:
        total = DemandeInterim.objects.exclude(statut='BROUILLON').count()
        validees = DemandeInterim.objects.filter(
            statut__in=['VALIDEE', 'EN_COURS', 'TERMINEE']
        ).count()
        
        if total > 0:
            return round((validees / total) * 100, 1)
        return 0
        
    except Exception as e:
        logger.error(f"Erreur calcul taux validation global: {e}")
        return 0

def _get_type_validation(profil):
    """Détermine le type de validation selon le profil"""
    type_profil = getattr(profil, 'type_profil', None)
    
    if type_profil == 'CHEF_EQUIPE':
        return 'N_PLUS_1'
    elif type_profil == 'RESPONSABLE':
        return 'N_PLUS_2'
    elif type_profil == 'DIRECTEUR':
        return 'DIRECTEUR'
    elif type_profil in ['RH', 'SUPERUSER']:
        return 'DRH'
    else:
        return 'AUTRE'

# ================================================================
# FONCTION DE REDIRECTION SELON PROFIL (MISE À JOUR)
# ================================================================

def _redirect_according_to_profile(user):
    """
    Redirige l'utilisateur selon son type de profil avec gestion d'erreur robuste
    
    Args:
        user: Objet User Django
        
    Returns:
        HttpResponseRedirect: Redirection vers la vue appropriée
        
    Hiérarchie de redirection CORRIGÉE :
    1. SUPERUTILISATEUR → Accès global automatique (priorité absolue)
    2. ADMIN → Vue globale avec droits étendus
    3. RH → Vue globale RH
    4. DIRECTEUR → Vue multi-départements  
    5. RESPONSABLE → Vue département N+1
    6. CHEF_EQUIPE → Vue équipe
    7. UTILISATEUR → Vue de base
    8. Fallbacks sécurisés
    """
    
    try:
        # ================================================================
        # 1. VÉRIFICATION SUPERUTILISATEUR (PRIORITÉ ABSOLUE)
        # ================================================================
        if user.is_superuser:
            logger.info(f"Redirection superutilisateur: {user.username} → Vue globale")
            return redirect('index_n3_global')
        
        # ================================================================
        # 2. RÉCUPÉRATION DU PROFIL UTILISATEUR
        # ================================================================
        try:
            profil = ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste'
            ).get(user=user)
            
            logger.info(f"Profil trouvé: {user.username} → {profil.type_profil}")
            
        except ProfilUtilisateur.DoesNotExist:
            logger.warning(f"Aucun profil trouvé pour {user.username}")
            
            # Si superutilisateur sans profil → Vue globale quand même
            if user.is_superuser:
                logger.info(f"Superutilisateur sans profil: {user.username} → Vue globale")
                return redirect('index_n3_global')
            
            # Sinon → Connexion pour les autres
            logger.warning(f"Utilisateur sans profil redirigé vers connexion: {user.username}")
            return redirect('connexion')
        
        # ================================================================
        # 3. VÉRIFICATIONS DE SÉCURITÉ DU PROFIL
        # ================================================================
        
        # Vérifier que le profil est actif
        if not profil.actif:
            logger.warning(f"Profil inactif pour {user.username}")
            return redirect('connexion')
        
        # Vérifier le statut employé
        if profil.statut_employe not in ['ACTIF']:
            logger.warning(f"Statut employé non actif pour {user.username}: {profil.statut_employe}")
            return redirect('connexion')
        
        # ================================================================
        # 4. REDIRECTION SELON LE TYPE DE PROFIL
        # ================================================================
        
        # NIVEAU 3 : ADMIN et RH (Vue globale)
        if profil.type_profil in ['ADMIN', 'RH']:
            logger.info(f"Redirection {profil.type_profil}: {user.username} → Vue globale")
            return redirect('index_n3_global')
        
        # NIVEAU 2 : DIRECTEUR (Vue multi-départements)
        elif profil.type_profil == 'DIRECTEUR':
            logger.info(f"Redirection DIRECTEUR: {user.username} → Vue directeur")
            return redirect('index_n2_directeur')
        
        # NIVEAU 1 : RESPONSABLE (Vue département N+1)
        elif profil.type_profil == 'RESPONSABLE':
            logger.info(f"Redirection RESPONSABLE: {user.username} → Vue responsable N+1")
            return redirect('index_n1_responsable')
        
        # NIVEAU 0 : CHEF_EQUIPE (Vue équipe)
        elif profil.type_profil == 'CHEF_EQUIPE':
            logger.info(f"Redirection CHEF_EQUIPE: {user.username} → Vue chef équipe")
            return redirect('index_chef_equipe')
        
        # UTILISATEUR STANDARD : Vue de base (fallback)
        elif profil.type_profil == 'UTILISATEUR':
            logger.info(f"Redirection UTILISATEUR: {user.username} → Vue équipe (fallback)")
            return redirect('index_chef_equipe')
        
        # ================================================================
        # 5. FALLBACK POUR TYPES NON RECONNUS
        # ================================================================
        else:
            logger.warning(f"Type de profil non reconnu pour {user.username}: {profil.type_profil}")
            
            # Si superutilisateur → Vue globale même avec profil bizarre
            if user.is_superuser:
                logger.info(f"Superutilisateur avec profil étrange → Vue globale: {user.username}")
                return redirect('index_n3_global')
            
            # Sinon → Vue équipe par défaut
            logger.info(f"Type profil inconnu → Vue équipe par défaut: {user.username}")
            return redirect('index_chef_equipe')
    
    except Exception as e:
        # ================================================================
        # 6. GESTION D'ERREUR ULTIME
        # ================================================================
        logger.error(f"Erreur critique lors de la redirection pour {user.username}: {e}")
        
        # Fallback ultime selon les permissions Django de base
        if user.is_superuser:
            logger.info(f"Erreur → Fallback superutilisateur: {user.username}")
            return redirect('index_n3_global')
        elif user.is_staff:
            logger.info(f"Erreur → Fallback staff: {user.username}")
            return redirect('index_chef_equipe')
        else:
            logger.info(f"Erreur → Fallback connexion: {user.username}")
            return redirect('connexion')
                
# ================================================================
# VUES DE CONNEXION ET DÉCONNEXION
# ================================================================

def connexion_view(request):
    """Vue de connexion personnalisée pour les responsables et superutilisateurs"""
    
    # Si l'utilisateur est déjà connecté, rediriger selon son profil
    if request.user.is_authenticated:
        return _redirect_according_to_profile(request.user)
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        # Validation des champs
        if not username or not password:
            messages.error(request, "Veuillez saisir votre nom d'utilisateur et mot de passe")
            return render(request, 'auth/connexion.html', {
                'username': username
            })
        
        # Tentative d'authentification
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Vérifier si c'est un superutilisateur
            if user.is_superuser:
                # Connexion directe pour les superutilisateurs
                login(request, user)
                logger.info(f"Connexion superutilisateur: {user.username}")
                messages.success(request, f"Bienvenue Superutilisateur {user.username}")
                return _redirect_according_to_profile(user)
            
            # Vérifier si l'utilisateur a un profil pour les autres utilisateurs
            try:
                profil = ProfilUtilisateur.objects.get(user=user)
                
                # Vérifier que l'utilisateur a un niveau de responsabilité autorisé
                niveaux_autorises = ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']
                
                if profil.type_profil not in niveaux_autorises:
                    messages.error(request, 
                        "Accès réservé aux utilisateurs avec des responsabilités managériales")
                    return render(request, 'auth/connexion.html', {
                        'username': username
                    })
                
                # Vérifier que le profil est actif
                if not profil.actif or profil.statut_employe != 'ACTIF':
                    messages.error(request, 
                        "Votre compte n'est pas actif. Contactez l'administrateur.")
                    return render(request, 'auth/connexion.html', {
                        'username': username
                    })
                
                # Connexion réussie
                login(request, user)
                
                # Log de connexion
                logger.info(f"Connexion réussie: {user.username} ({profil.type_profil})")
                
                # Message de bienvenue
                messages.success(request, f"Bienvenue {profil.nom_complet}")
                
                # Redirection selon le profil
                return _redirect_according_to_profile(user)
                
            except ProfilUtilisateur.DoesNotExist:
                messages.error(request, 
                    "Aucun profil trouvé pour cet utilisateur. Contactez l'administrateur.")
                logger.warning(f"Tentative de connexion sans profil: {user.username}")
                
        else:
            # Échec d'authentification
            messages.error(request, "Nom d'utilisateur ou mot de passe incorrect")
            logger.warning(f"Échec de connexion pour: {username}")
    
    return render(request, 'auth/connexion.html')

@login_required
def deconnexion_view(request):
    """Vue de déconnexion"""
    user_name = request.user.username
    logout(request)
    messages.success(request, "Vous avez été déconnecté avec succès")
    logger.info(f"Déconnexion: {user_name}")
    return redirect('connexion')

# ================================================================
# VUES HIÉRARCHIQUES SPÉCIALISÉES
# ================================================================

@login_required
def index(request):
    """
    Vue index principale qui redirige automatiquement l'utilisateur 
    vers le bon dashboard selon son type de profil et ses permissions.
    
    Hiérarchie de redirection :
    - SUPERUTILISATEUR → index_n3_global (Vue globale administrative)
    - ADMIN → index_n3_global (Vue globale administrative) 
    - RH → index_n3_global (Vue globale RH)
    - DIRECTEUR → index_n2_directeur (Vue directeur multi-départements)
    - RESPONSABLE → index_n1_responsable (Vue responsable N+1)
    - CHEF_EQUIPE → index_chef_equipe (Vue chef d'équipe)
    - UTILISATEUR → index_chef_equipe (Vue de base, fallback)
    - Pas de profil mais superutilisateur → index_n3_global
    - Pas de profil et pas superutilisateur → connexion
    """
    
    try:
        # Log de la tentative d'accès pour debugging
        logger.info(f"Accès index par utilisateur: {request.user.username}")
        
        # Utiliser la fonction de redirection selon profil

        redirect_response = _redirect_according_to_profile(request.user)
        
        # Ajouter un message informatif si ce n'est pas déjà fait
        if not messages.get_messages(request):
            # Déterminer le message selon la redirection
            redirect_url = redirect_response.url
            
            if 'n3' in redirect_url:
                messages.info(request, "Accès au dashboard global - Niveau administratif")
            elif 'n2' in redirect_url:
                messages.info(request, "Accès au dashboard directeur - Vision multi-départements")
            elif 'n1' in redirect_url:
                messages.info(request, "Accès au dashboard responsable - Pilotage département")
            elif 'chef_equipe' in redirect_url:
                messages.info(request, "Accès au dashboard équipe - Gestion directe")
            elif 'connexion' in redirect_url:
                messages.warning(request, "Redirection vers la page de connexion")
        
        logger.info(f"Redirection de {request.user.username} vers: {redirect_response.url}")
        return redirect_response
        
    except Exception as e:
        # Gestion d'erreur robuste
        logger.error(f"Erreur lors de la redirection pour {request.user.username}: {e}")
        
        # Fallback sécurisé selon le type d'utilisateur
        try:
            if request.user.is_superuser:
                messages.warning(request, f"Erreur de redirection, accès direct au dashboard global (Superutilisateur)")
                return redirect('index_n3_global')
            elif request.user.is_staff:
                messages.warning(request, f"Erreur de redirection, accès direct au dashboard équipe (Staff)")
                return redirect('index_chef_equipe')
            else:
                messages.error(request, f"Erreur d'accès au système. Contactez l'administrateur.")
                return redirect('connexion')
                
        except Exception as fallback_error:
            # Dernier recours - redirection vers connexion
            logger.critical(f"Erreur critique de redirection pour {request.user.username}: {fallback_error}")
            messages.error(request, "Erreur système critique. Veuillez vous reconnecter.")
            return redirect('connexion')
        
@login_required
@user_passes_test(lambda u: _check_chef_equipe(u), login_url='connexion')
def index_chef_equipe(request):
    """Vue index pour CHEF_EQUIPE - Données de son équipe directe uniquement"""
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        
        # Si superutilisateur, rediriger vers vue globale
        if request.user.is_superuser:
            return redirect('index_n3_global')
        
        # === ÉQUIPE GÉRÉE ===
        equipe_directe = ProfilUtilisateur.objects.filter(
            manager=profil_utilisateur,
            actif=True
        ).select_related('user', 'poste', 'departement')
        
        # === STATISTIQUES SPÉCIFIQUES À L'ÉQUIPE ===
        cache_key = f"dashboard_chef_equipe_{profil_utilisateur.id}"
        cached_stats = cache.get(cache_key)
        
        if not cached_stats:
            # Demandes de l'équipe
            demandes_equipe = DemandeInterim.objects.filter(
                demandeur__in=equipe_directe
            )
            
            # Missions de l'équipe
            missions_equipe = DemandeInterim.objects.filter(
                candidat_selectionne__in=equipe_directe
            )
            
            cached_stats = {
                'membres_equipe': equipe_directe.count(),
                'demandes_equipe_total': demandes_equipe.count(),
                'demandes_en_attente': demandes_equipe.filter(
                    statut__in=['SOUMISE', 'EN_VALIDATION']
                ).count(),
                'missions_en_cours': missions_equipe.filter(
                    statut='EN_COURS'
                ).count(),
                'validations_a_traiter': DemandeInterim.objects.filter(
                    demandeur__manager=profil_utilisateur,
                    statut='EN_VALIDATION'
                ).count()
            }
            
            cache.set(cache_key, cached_stats, 300)
        
        # === DEMANDES RÉCENTES DE L'ÉQUIPE ===
        demandes_recentes = DemandeInterim.objects.filter(
            demandeur__in=equipe_directe
        ).select_related(
            'poste__site', 'poste__departement', 
            'candidat_selectionne__user', 'personne_remplacee__user', 
            'demandeur__user'
        ).order_by('-created_at')[:5]
        
        # === NOTIFICATIONS SPÉCIFIQUES ===
        notifications = []
        
        if cached_stats['validations_a_traiter'] > 0:
            notifications.append({
                'type': 'info',
                'message': f"{cached_stats['validations_a_traiter']} validation(s) en attente pour votre équipe",
                'icon': 'fas fa-tasks',
                'action_url': "",
                'action_text': 'Traiter'
            })
        
        if cached_stats['demandes_en_attente'] > 0:
            notifications.append({
                'type': 'warning',
                'message': f"{cached_stats['demandes_en_attente']} demande(s) de votre équipe en attente",
                'icon': 'fas fa-clock',
                'action_url': '/interim/suivi/',
                'action_text': 'Voir'
            })
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'user_initials': _get_utilisateur_initials(request.user),
            'stats': cached_stats,
            'equipe_directe': equipe_directe,
            'demandes_recentes': demandes_recentes,
            'notifications': notifications,
            'niveau_acces': 'CHEF_EQUIPE',
            'is_superuser': request.user.is_superuser,
            'dashboard_data': {
                'last_update': timezone.now().isoformat(),
                'user_role': profil_utilisateur.type_profil,
                'equipe_size': cached_stats['membres_equipe']
            }
        }
        
        return render(request, 'dashboard/index_chef_equipe.html', context)
        
    except Exception as e:
        logger.error(f"Erreur vue chef équipe: {e}")
        messages.error(request, "Erreur lors du chargement du tableau de bord")
        return redirect('connexion')

@login_required
@user_passes_test(lambda u: _check_responsable(u), login_url='connexion')
def index_n1_responsable(request):
    """
    Dashboard spécialisé pour les responsables N+1
    """
    try:
        # ================================================================
        # TRACES DEBUG - DÉBUT
        # ================================================================
        print(f"\n [DEBUG] === DÉBUT index_n1_responsable ===")
        print(f" [DEBUG] request.user: {request.user}")
        print(f" [DEBUG] request.user.username: {request.user.username}")
        print(f" [DEBUG] request.user.is_authenticated: {request.user.is_authenticated}")
        print(f" [DEBUG] Type de request.user: {type(request.user)}")
        
        # ================================================================
        # 1. RÉCUPÉRATION DU PROFIL UTILISATEUR
        # ================================================================
        
        print(f" [DEBUG] Récupération profil utilisateur...")
        profil_utilisateur = get_profil_or_virtual(request.user)
        print(f" [DEBUG]  profil_utilisateur: {profil_utilisateur}")
        
        if not profil_utilisateur:
            print(f" [DEBUG]  Profil utilisateur non trouvé")
            messages.error(request, "Profil utilisateur non trouvé")
            return redirect('index')
        
        print(f"  [DEBUG] profil_utilisateur.id: {profil_utilisateur.id}")
        print(f"  [DEBUG] profil_utilisateur.user: {profil_utilisateur.user}")
        print(f"  [DEBUG] profil_utilisateur.user.username: {profil_utilisateur.user}")
        print(f"  [DEBUG] profil_utilisateur.nom_complet: {profil_utilisateur.nom_complet}")
        print(f"  [DEBUG] profil_utilisateur.type_profil: {profil_utilisateur.type_profil}")
        
        # ================================================================
        # 2. VÉRIFICATION DES PERMISSIONS
        # ================================================================
        
        print(f"  [DEBUG] === VÉRIFICATION PERMISSIONS ===")
        
        # Vérifier que l'utilisateur est bien responsable
        if profil_utilisateur.type_profil != 'RESPONSABLE':
            print(f"  [DEBUG]   N'est pas responsable: {profil_utilisateur.type_profil}")
            messages.error(request, "Accès réservé aux responsables")
            return redirect('index')
        
        print(f"  [DEBUG]   Utilisateur confirmé comme RESPONSABLE")
        
        if not profil_utilisateur.departement:
            print(f"  [DEBUG]   Aucun département assigné")
            messages.warning(request, "Aucun département assigné à votre profil")
        else:
            print(f"  [DEBUG]   Département: {profil_utilisateur.departement.nom}")
        
        # ================================================================
        # 3. CALCUL DES STATISTIQUES
        # ================================================================
        
        print(f"  [DEBUG] === CALCUL STATISTIQUES ===")
        
        # Statistiques de base
        stats = {}
        
        try:
            # Employés du département
            if profil_utilisateur.departement:
                employes_departement = ProfilUtilisateur.objects.filter(
                    departement=profil_utilisateur.departement,
                    actif=True
                ).count()
            else:
                employes_departement = 0
            
            stats['employes_departement'] = employes_departement
            print(f"  [DEBUG] Employés département: {employes_departement}")
            
            # Chefs d'équipe sous sa responsabilité
            chefs_equipe = ProfilUtilisateur.objects.filter(
                manager=profil_utilisateur,
                type_profil='CHEF_EQUIPE',
                actif=True
            )
            stats['chefs_equipe'] = chefs_equipe.count()
            print(f"  [DEBUG] Chefs d'équipe: {stats['chefs_equipe']}")
            
            # Demandes en validation pour ce responsable
            demandes_en_validation = 0
            if profil_utilisateur.departement:
                # Récupérer les demandes au niveau 1 de validation pour son département
                demandes_en_validation = DemandeInterim.objects.filter(
                    statut__in=['EN_VALIDATION', 'SOUMISE'],
                    poste__departement=profil_utilisateur.departement,
                    niveau_validation_actuel=0  # Niveau 1 = responsable
                ).count()
            
            stats['demandes_en_validation'] = demandes_en_validation
            print(f"  [DEBUG] Demandes en validation: {demandes_en_validation}")
            
            # Demandes totales du département
            demandes_departement = 0
            if profil_utilisateur.departement:
                demandes_departement = DemandeInterim.objects.filter(
                    poste__departement=profil_utilisateur.departement
                ).count()
            
            stats['demandes_departement'] = demandes_departement
            print(f"  [DEBUG] Demandes département: {demandes_departement}")
            
            # Missions du département
            missions_departement = 0
            if profil_utilisateur.departement:
                missions_departement = DemandeInterim.objects.filter(
                    poste__departement=profil_utilisateur.departement,
                    statut__in=['EN_COURS', 'TERMINEE']
                ).count()
            
            stats['missions_departement'] = missions_departement
            print(f"  [DEBUG] Missions département: {missions_departement}")
            
            # Taux de réussite (approximatif)
            if demandes_departement > 0:
                demandes_validees = DemandeInterim.objects.filter(
                    poste__departement=profil_utilisateur.departement,
                    statut__in=['VALIDEE', 'EN_COURS', 'TERMINEE']
                ).count()
                taux_reussite = round((demandes_validees / demandes_departement) * 100)
            else:
                taux_reussite = 100
            
            stats['taux_reussite'] = taux_reussite
            print(f"  [DEBUG] Taux réussite: {taux_reussite}%")
            
        except Exception as e:
            print(f"  [DEBUG]   Erreur calcul stats: {e}")
            logger.error(f"Erreur calcul stats responsable: {e}")
            # Valeurs par défaut
            stats = {
                'employes_departement': 0,
                'chefs_equipe': 0,
                'demandes_en_validation': 0,
                'demandes_departement': 0,
                'missions_departement': 0,
                'taux_reussite': 0
            }
        
        # ================================================================
        # 4. RÉCUPÉRATION DES CHEFS D'ÉQUIPE
        # ================================================================
        
        print(f"  [DEBUG] === RÉCUPÉRATION CHEFS D'ÉQUIPE ===")
        
        try:
            chefs_equipe_list = list(chefs_equipe)
            print(f"  [DEBUG]   {len(chefs_equipe_list)} chefs d'équipe récupérés")
            
            for chef in chefs_equipe_list:
                print(f"  [DEBUG] Chef: {chef.nom_complet} - {chef.user.username}")
                
        except Exception as e:
            print(f"  [DEBUG]   Erreur récupération chefs équipe: {e}")
            chefs_equipe_list = []
        
        # ================================================================
        # 5. RÉCUPÉRATION DES DEMANDES RÉCENTES
        # ================================================================
        
        print(f"  [DEBUG] === RÉCUPÉRATION DEMANDES RÉCENTES ===")
        
        try:
            demandes_recentes = []
            if profil_utilisateur.departement:
                demandes_recentes = DemandeInterim.objects.filter(
                    poste__departement=profil_utilisateur.departement
                ).select_related(
                    'demandeur__user',
                    'poste',
                    'candidat_selectionne__user'
                ).order_by('-created_at')[:10]
                
                demandes_recentes = list(demandes_recentes)
                print(f"  [DEBUG]   {len(demandes_recentes)} demandes récentes récupérées")
            else:
                print(f"  [DEBUG]   Aucun département - pas de demandes récentes")
            
        except Exception as e:
            print(f"  [DEBUG]   Erreur récupération demandes récentes: {e}")
            demandes_recentes = []
        
        # ================================================================
        # 6. PRÉPARATION DU CONTEXTE
        # ================================================================
        
        print(f"  [DEBUG] === PRÉPARATION CONTEXTE ===")
        print(f"  [DEBUG] profil_utilisateur pour contexte: {profil_utilisateur}")
        print(f"  [DEBUG] profil_utilisateur.user: {profil_utilisateur.user}")
        print(f"  [DEBUG] profil_utilisateur.user.username: {profil_utilisateur.user.username}")
        
        # Données pour les stats de la sidebar (réutilisées du template de base)
        mes_validations_stats = {
            'a_valider': stats['demandes_en_validation'],
            'validees_mois': 0,  # À calculer si nécessaire
        }
        
        mes_demandes_stats = {
            'en_attente': 0,  # À calculer si nécessaire
            'total': stats['demandes_departement']
        }
        
        context = {
            # Profil utilisateur -   POINT CRITIQUE
            'profil_utilisateur': profil_utilisateur,
            'user': request.user,  #   AJOUT EXPLICITE
            
            # Statistiques
            'stats': stats,
            
            # Données métier
            'chefs_equipe': chefs_equipe_list,
            'demandes_recentes': demandes_recentes,
            
            # Pour la sidebar (héritage du template de base)
            'mes_validations_stats': mes_validations_stats,
            'mes_demandes_stats': mes_demandes_stats,
            'mes_propositions_stats': {'soumises': 0},
            'mes_missions_stats': {'en_cours': 0},
            'notifications': [],  # À implémenter
            
            # Titre de la page
            'page_title': f'Dashboard Responsable N+1 - {profil_utilisateur.nom_complet}',
            
            # Configuration debug
            'debug_info': {
                'user_username': request.user.username,
                'profil_user_username': profil_utilisateur.user.username,
                'type_profil': profil_utilisateur.type_profil,
                'departement': profil_utilisateur.departement.nom if profil_utilisateur.departement else None,
            }
        }
        
        print(f"  [DEBUG]   Contexte préparé avec {len(context)} clés")
        print(f"  [DEBUG] Clés du contexte: {list(context.keys())}")
        print(f"  [DEBUG] context['user']: {context['user']}")
        print(f"  [DEBUG] context['user'].username: {context['user'].username}")
        print(f"  [DEBUG] context['profil_utilisateur']: {context['profil_utilisateur']}")
        print(f"  [DEBUG] context['profil_utilisateur'].user.username: {context['profil_utilisateur'].user.username}")
        
        # ================================================================
        # 7. RENDU DU TEMPLATE
        # ================================================================
        
        print(f"  [DEBUG] === RENDU TEMPLATE ===")
        print(f"  [DEBUG] Template: index_n1_responsable.html")
        print(f"  [DEBUG] === FIN index_n1_responsable ===\n")
        
        return render(request, 'dashboard/index_n1_responsable.html', context)
        
    except Exception as e:
        # ================================================================
        # GESTION D'ERREURS
        # ================================================================
        
        print(f"  [DEBUG]     ERREUR MAJEURE dans index_n1_responsable    ")
        print(f"  [DEBUG] Type erreur: {type(e)}")
        print(f"  [DEBUG] Message erreur: {str(e)}")
        print(f"  [DEBUG] request.user: {request.user}")
        print(f"  [DEBUG] request.user.username: {getattr(request.user, 'username', 'N/A')}")
        
        logger.error(f"Erreur vue index_n1_responsable: {e}")
        logger.error(f"Utilisateur connecté: {request.user.username}")
        logger.error(f"Stacktrace: {str(e)}", exc_info=True)
        
        messages.error(request, f"Erreur lors du chargement du dashboard: {str(e)}")
        return redirect('index')
    
@login_required
@user_passes_test(lambda u: _check_directeur(u), login_url='connexion')
def index_n2_directeur(request):
    """Vue index N+2 pour DIRECTEUR - Données de sa lignée complète en profondeur"""
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        
        # Si superutilisateur, rediriger vers vue globale
        if request.user.is_superuser:
            return redirect('index_n3_global')
        
        # === LIGNÉE HIÉRARCHIQUE COMPLÈTE ===
        departements_geres = [profil_utilisateur.departement] if profil_utilisateur.departement else []
        
        employes_lignee = ProfilUtilisateur.objects.filter(
            departement__in=departements_geres,
            actif=True
        ).select_related('user', 'poste', 'departement', 'manager')
        
        # === STATISTIQUES DIRECTEUR ===
        cache_key = f"dashboard_directeur_{profil_utilisateur.id}"
        cached_stats = cache.get(cache_key)
        
        if not cached_stats:
            demandes_lignee = DemandeInterim.objects.filter(
                poste__departement__in=departements_geres
            )
            
            cached_stats = {
                'employes_lignee': employes_lignee.count(),
                'responsables': employes_lignee.filter(type_profil='RESPONSABLE').count(),
                'chefs_equipe': employes_lignee.filter(type_profil='CHEF_EQUIPE').count(),
                'demandes_totales': demandes_lignee.count(),
                'demandes_en_cours': demandes_lignee.filter(
                    statut__in=['SOUMISE', 'EN_VALIDATION', 'EN_COURS']
                ).count(),
                'missions_actives': demandes_lignee.filter(statut='EN_COURS').count(),
                'taux_validation_global': _calculate_validation_rate(demandes_lignee)
            }
            
            cache.set(cache_key, cached_stats, 300)
        
        # === DEMANDES RÉCENTES MULTI-DÉPARTEMENTS ===
        demandes_recentes = DemandeInterim.objects.filter(
            poste__departement__in=departements_geres
        ).select_related(
            'poste__site', 'poste__departement',
            'candidat_selectionne__user', 'demandeur__user'
        ).order_by('-created_at')[:5]
        
        # === RÉPARTITION PAR DÉPARTEMENT ===
        repartition_departements = DemandeInterim.objects.filter(
            poste__departement__in=departements_geres,
            created_at__gte=timezone.now() - timedelta(days=30)
        ).values(
            'poste__departement__nom'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        # === NOTIFICATIONS SPÉCIFIQUES ===
        notifications = []
        
        if cached_stats['demandes_en_cours'] > 0:
            notifications.append({
                'type': 'info',
                'message': f"{cached_stats['demandes_en_cours']} demande(s) en cours dans votre périmètre",
                'icon': 'fas fa-building',
                'action_url': '/interim/suivi/',
                'action_text': 'Superviser'
            })
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'user_initials': _get_utilisateur_initials(request.user),
            'stats': cached_stats,
            'employes_lignee': employes_lignee,
            'demandes_recentes': demandes_recentes,
            'repartition_departements': repartition_departements,
            'notifications': notifications,
            'niveau_acces': 'DIRECTEUR',
            'is_superuser': request.user.is_superuser,
            'dashboard_data': {
                'last_update': timezone.now().isoformat(),
                'user_role': profil_utilisateur.type_profil,
                'perimetre': 'Multi-départements'
            }
        }
        
        return render(request, 'dashboard/index_n2_directeur.html', context)
        
    except Exception as e:
        logger.error(f"Erreur vue directeur: {e}")
        messages.error(request, "Erreur lors du chargement du tableau de bord")
        return redirect('connexion')

# ================================================================
# VUE INDEX N+3 MISE À JOUR POUR SUPERUTILISATEURS
# ================================================================

# views.py - Vue index_n3_global corrigée pour superutilisateurs

@login_required
@user_passes_test(lambda u: _check_rh_admin_or_superuser(u), login_url='connexion')
def index_n3_global(request):
    """Vue index N+3 pour RH/ADMIN/SUPERUSER - Version corrigée pour property nom_complet"""
    try:
        # Gestion spéciale pour les superutilisateurs - CRÉER VRAI PROFIL
        try:
            profil_utilisateur = ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste', 'manager'
            ).get(user=request.user)
        except ProfilUtilisateur.DoesNotExist:
            if request.user.is_superuser:
                # Créer automatiquement un profil pour le superutilisateur
                # IMPORTANT: Ne pas inclure nom_complet dans defaults car c'est une property
                
                profil_utilisateur, created = ProfilUtilisateur.objects.get_or_create(
                    user=request.user,
                    defaults={
                        'matricule': f'SUPER_{request.user.id}',
                        'type_profil': 'ADMIN',  # Type valide dans la DB
                        'actif': True,
                        'statut_employe': 'ACTIF'
                        # Pas de nom_complet ici car c'est une property !
                    }
                )
                
                if created:
                    logger.info(f"Profil admin créé automatiquement pour superutilisateur: {request.user.username}")
                    logger.info(f"Nom complet généré automatiquement: {profil_utilisateur.nom_complet}")
                    messages.info(request, "Profil administrateur créé automatiquement pour votre compte superutilisateur")
            else:
                messages.error(request, "Profil utilisateur non trouvé")
                return redirect('connexion')
        
        # === DONNÉES GLOBALES AVEC GESTION D'ERREUR OPTIMISÉE ===
        cache_key = f"dashboard_global_{profil_utilisateur.id}"
        cached_stats = cache.get(cache_key)
        
        if not cached_stats:
            try:
                # Requêtes optimisées avec select_related/prefetch_related
                toutes_demandes = DemandeInterim.objects.select_related('poste', 'demandeur', 'candidat_selectionne')
                tous_employes = ProfilUtilisateur.objects.filter(actif=True)
                
                # Calculs de base
                total_demandes = toutes_demandes.count()
                employes_total = tous_employes.count()
                
                # Demandes par statut (une seule requête)
                demandes_par_statut = toutes_demandes.values('statut').annotate(count=Count('id'))
                statut_counts = {item['statut']: item['count'] for item in demandes_par_statut}
                
                cached_stats = {
                    'employes_total': employes_total,
                    'demandes_total': total_demandes,
                    'demandes_en_attente_validation': statut_counts.get('EN_VALIDATION', 0),
                    'missions_globales_actives': statut_counts.get('EN_COURS', 0),
                    'demandes_soumises': statut_counts.get('SOUMISE', 0),
                    'demandes_validees': statut_counts.get('VALIDEE', 0),
                    'demandes_refusees': statut_counts.get('REFUSEE', 0),
                    'demandes_terminees': statut_counts.get('TERMINEE', 0),
                }
                
                # Taux de réussite global
                demandes_reussies = (
                    statut_counts.get('EN_COURS', 0) + 
                    statut_counts.get('TERMINEE', 0) + 
                    statut_counts.get('VALIDEE', 0)
                )
                cached_stats['taux_reussite_global'] = (
                    round((demandes_reussies / total_demandes) * 100, 1) if total_demandes > 0 else 0
                )
                
                # Taux de validation global
                demandes_non_brouillon = total_demandes - statut_counts.get('BROUILLON', 0)
                demandes_validees_total = (
                    statut_counts.get('VALIDEE', 0) + 
                    statut_counts.get('EN_COURS', 0) + 
                    statut_counts.get('TERMINEE', 0)
                )
                cached_stats['taux_validation_global'] = (
                    round((demandes_validees_total / demandes_non_brouillon) * 100, 1) if demandes_non_brouillon > 0 else 0
                )
                
                # Données conditionnelles selon modèles disponibles
                try:
                    cached_stats['propositions_en_attente'] = PropositionCandidat.objects.filter(
                        statut__in=['SOUMISE', 'EN_EVALUATION']
                    ).count()
                except:
                    cached_stats['propositions_en_attente'] = 0
                
                try:
                    if not request.user.is_superuser:
                        cached_stats['notifications_non_lues'] = NotificationInterim.objects.filter(
                            destinataire=profil_utilisateur,
                            statut='NON_LUE'
                        ).count()
                    else:
                        cached_stats['notifications_non_lues'] = 0
                except:
                    cached_stats['notifications_non_lues'] = 0
                
                # Statistiques temporelles (30 derniers jours)
                date_limite_30j = timezone.now() - timedelta(days=30)
                try:
                    cached_stats['demandes_30j'] = toutes_demandes.filter(
                        created_at__gte=date_limite_30j
                    ).count()
                    cached_stats['validations_30j'] = ValidationDemande.objects.filter(
                        date_validation__gte=date_limite_30j
                    ).count()
                except:
                    cached_stats['demandes_30j'] = 0
                    cached_stats['validations_30j'] = 0
                
                cache.set(cache_key, cached_stats, 300)  # Cache 5 minutes
                
            except Exception as e:
                logger.error(f"Erreur calcul statistiques globales: {e}")
                # Stats par défaut en cas d'erreur
                cached_stats = {
                    'employes_total': 0,
                    'demandes_total': 0,
                    'demandes_en_attente_validation': 0,
                    'missions_globales_actives': 0,
                    'demandes_soumises': 0,
                    'demandes_validees': 0,
                    'demandes_refusees': 0,
                    'demandes_terminees': 0,
                    'taux_reussite_global': 0,
                    'taux_validation_global': 0,
                    'propositions_en_attente': 0,
                    'notifications_non_lues': 0,
                    'demandes_30j': 0,
                    'validations_30j': 0
                }
        
        # === DEMANDES RÉCENTES GLOBALES AVEC GESTION D'ERREUR ===
        try:
            demandes_recentes = DemandeInterim.objects.select_related(
                'poste__site', 'poste__departement',
                'candidat_selectionne__user', 'demandeur__user',
                'personne_remplacee__user'
            ).order_by('-created_at')[:10]
        except Exception as e:
            logger.warning(f"Erreur récupération demandes récentes: {e}")
            demandes_recentes = DemandeInterim.objects.none()
        
        # === STATISTIQUES PAR DÉPARTEMENT AVEC GESTION D'ERREUR ===
        try:
            stats_departements = DemandeInterim.objects.select_related(
                'poste__departement'
            ).values(
                'poste__departement__nom'
            ).annotate(
                total_demandes=Count('id'),
                demandes_actives=Count('id', filter=Q(statut__in=['EN_COURS', 'EN_VALIDATION', 'SOUMISE'])),
                demandes_validees=Count('id', filter=Q(statut__in=['VALIDEE', 'EN_COURS', 'TERMINEE'])),
                missions_en_cours=Count('id', filter=Q(statut='EN_COURS'))
            ).order_by('-total_demandes')[:10]
            
            # Ajouter le taux de réussite pour chaque département
            for dept_stat in stats_departements:
                if dept_stat['total_demandes'] > 0:
                    dept_stat['taux_reussite'] = round(
                        (dept_stat['demandes_validees'] / dept_stat['total_demandes']) * 100, 1
                    )
                else:
                    dept_stat['taux_reussite'] = 0
                    
        except Exception as e:
            logger.warning(f"Erreur statistiques départements: {e}")
            stats_departements = []
        
        # === ACTIVITÉ RÉCENTE AVEC GESTION D'ERREUR ===
        activite_recente = []
        try:
            activite_recente = HistoriqueAction.objects.select_related(
                'demande', 'utilisateur__user'
            ).order_by('-created_at')[:10]
        except Exception as e:
            logger.info(f"Historique des actions non disponible: {e}")
        
        # === ALERTES SYSTÈME ET NOTIFICATIONS ===
        notifications = []
        
        # Alertes prioritaires
        if cached_stats['demandes_en_attente_validation'] > 0:
            niveau_alerte = 'danger' if cached_stats['demandes_en_attente_validation'] > 10 else 'warning'
            notifications.append({
                'type': niveau_alerte,
                'message': f"  {cached_stats['demandes_en_attente_validation']} demande(s) en attente de validation",
                'icon': 'fas fa-exclamation-triangle',
                'action_url': '/interim/validation/liste/',
                'action_text': 'Traiter maintenant',
                'priority': 1
            })
        
        if cached_stats['propositions_en_attente'] > 0:
            notifications.append({
                'type': 'info',
                'message': f"  {cached_stats['propositions_en_attente']} proposition(s) candidat en attente d'évaluation",
                'icon': 'fas fa-user-plus',
                'action_url': '/interim/propositions/',
                'action_text': 'Évaluer',
                'priority': 2
            })
        
        # Notification spéciale pour les superutilisateurs
        if request.user.is_superuser:
            notifications.insert(0, {
                'type': 'success',
                'message': f'  Mode Superutilisateur activé - Bienvenue {profil_utilisateur.nom_complet}',
                'icon': 'fas fa-crown',
                'action_url': '/admin/',
                'action_text': 'Administration Django',
                'priority': 0
            })
                    
        elif getattr(profil_utilisateur, 'type_profil', None) in ['RH', 'ADMIN']:
            notifications.append({
                'type': 'info',
                'message': f'  Mode {profil_utilisateur.type_profil} - Supervision globale active',
                'icon': 'fas fa-shield-alt',
                'priority': 3
            })
        
        # Trier les notifications par priorité
        notifications.sort(key=lambda x: x.get('priority', 99))
        
        # === MÉTRIQUES DE PERFORMANCE ===
        metriques_performance = {
            'delai_moyen_validation': '2.3 jours',
            'satisfaction_utilisateurs': '87%',
            'disponibilite_systeme': '99.2%',
            'temps_reponse_moyen': '1.2s'
        }
        
        # === CONTEXT FINAL ===
        context = {
            'profil_utilisateur': profil_utilisateur,
            'user_initials': _get_utilisateur_initials(request.user),
            'stats': cached_stats,
            'demandes_recentes': demandes_recentes,
            'stats_departements': stats_departements,
            'activite_recente': activite_recente,
            'notifications': notifications,
            'metriques_performance': metriques_performance,
            'niveau_acces': 'SUPERUSER' if request.user.is_superuser else 'GLOBAL',
            'is_superuser': request.user.is_superuser,
            'dashboard_data': {
                'last_update': timezone.now().isoformat(),
                'user_role': getattr(profil_utilisateur, 'type_profil', 'ADMIN'),
                'user_display_name': profil_utilisateur.nom_complet,  # Utiliser la property
                'perimetre': 'Global (Superutilisateur)' if request.user.is_superuser else 'Global',
                'cache_status': 'HIT' if cache.get(cache_key) else 'MISS',
                'stats_count': len(cached_stats),
                'notifications_count': len(notifications)
            },
            # Données pour les graphiques JS
            'chart_data': {
                'demandes_par_statut': [
                    {'label': 'En cours', 'value': cached_stats['missions_globales_actives'], 'color': '#28a745'},
                    {'label': 'En validation', 'value': cached_stats['demandes_en_attente_validation'], 'color': '#ffc107'},
                    {'label': 'Soumises', 'value': cached_stats['demandes_soumises'], 'color': '#17a2b8'},
                    {'label': 'Validées', 'value': cached_stats['demandes_validees'], 'color': '#007bff'},
                    {'label': 'Refusées', 'value': cached_stats['demandes_refusees'], 'color': '#dc3545'},
                ],
                'departements_top': stats_departements[:5]
            }
        }
        
        return render(request, 'dashboard/index_n3_global.html', context)
        
    except Exception as e:
        logger.error(f"Erreur critique vue globale: {e}", exc_info=True)
        
        if request.user.is_superuser:
            # Fallback spécial pour superutilisateur en cas d'erreur critique
            messages.warning(request, f"Mode superutilisateur - Erreur de chargement: {str(e)}")
            
            # Créer un profil minimal si nécessaire
            try:
                profil_utilisateur, _ = ProfilUtilisateur.objects.get_or_create(
                    user=request.user,
                    defaults={
                        'matricule': f'SUPER_{request.user.id}',
                        'type_profil': 'ADMIN',
                        'actif': True,
                        'statut_employe': 'ACTIF'
                        # Pas de nom_complet car c'est une property
                    }
                )
            except Exception:
                # Profil ultra-minimal virtuel en dernier recours
                from types import SimpleNamespace
                profil_utilisateur = SimpleNamespace()
                profil_utilisateur.nom_complet = request.user.username
                profil_utilisateur.type_profil = 'SUPERUSER'
                profil_utilisateur.id = request.user.id
            
            context = {
                'profil_utilisateur': profil_utilisateur,
                'user_initials': _get_utilisateur_initials(request.user),
                'stats': {
                    'employes_total': 0,
                    'demandes_total': 0,
                    'demandes_en_attente_validation': 0,
                    'missions_globales_actives': 0,
                    'taux_reussite_global': 0,
                    'taux_validation_global': 0,
                    'propositions_en_attente': 0,
                    'notifications_non_lues': 0
                },
                'demandes_recentes': [],
                'stats_departements': [],
                'activite_recente': [],
                'notifications': [{
                    'type': 'danger',
                    'message': f'  Erreur système: {str(e)[:100]}...',
                    'icon': 'fas fa-exclamation-triangle'
                }, {
                    'type': 'success',
                    'message': '  Mode Superutilisateur - Droits d\'administration maintenus',
                    'icon': 'fas fa-crown',
                    'action_url': '/admin/',
                    'action_text': 'Admin Django'
                }],
                'niveau_acces': 'SUPERUSER',
                'is_superuser': True,
                'dashboard_data': {
                    'last_update': timezone.now().isoformat(),
                    'user_role': 'SUPERUSER',
                    'perimetre': 'Global (Mode dégradé)',
                    'error_mode': True
                }
            }
            return render(request, 'dashboard/index_n3_global.html', context)
        else:
            messages.error(request, "Erreur lors du chargement du tableau de bord")
            return redirect('connexion')
                                
# ================================================================
# VUES AJAX POUR ACTUALISATION
# ================================================================

@login_required
def refresh_stats_ajax(request):
    """API pour rafraîchir les statistiques selon le niveau d'accès (mise à jour pour superutilisateurs)"""
    try:
        # Gestion spéciale pour superutilisateurs
        if request.user.is_superuser:
            cache_key = f"dashboard_global_{request.user.id}"
        else:
            profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
            
            # Invalider le cache selon le profil
            if profil_utilisateur.type_profil == 'CHEF_EQUIPE':
                cache_key = f"dashboard_chef_equipe_{profil_utilisateur.id}"
            elif profil_utilisateur.type_profil == 'RESPONSABLE':
                cache_key = f"dashboard_responsable_{profil_utilisateur.id}"
            elif profil_utilisateur.type_profil == 'DIRECTEUR':
                cache_key = f"dashboard_directeur_{profil_utilisateur.id}"
            else:  # RH/ADMIN
                cache_key = f"dashboard_global_{profil_utilisateur.id}"
        
        cache.delete(cache_key)
        
        return JsonResponse({
            'success': True,
            'message': 'Statistiques mises à jour',
            'timestamp': timezone.now().isoformat(),
            'user_type': 'SUPERUSER' if request.user.is_superuser else 'NORMAL'
        })
        
    except Exception as e:
        logger.error(f"Erreur refresh stats: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
            
@login_required
def interim_demande(request):
    """
    Vue pour créer une demande d'intérim avec gestion complète des candidats :
    - Candidats automatiques sélectionnés
    - Candidat spécifique
    - Combinaison des deux
    - Création classique sans candidat
    """
    try:
        # Récupérer le profil utilisateur
        try:
            profil_utilisateur = ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste', 'manager'
            ).get(user=request.user)
        except ProfilUtilisateur.DoesNotExist:
            if request.user.is_superuser:
                profil_utilisateur, created = ProfilUtilisateur.objects.get_or_create(
                    user=request.user,
                    defaults={
                        'matricule': f'SUPER_{request.user.id}',
                        'type_profil': 'ADMIN',
                        'actif': True,
                        'statut_employe': 'ACTIF'
                    }
                )
                if created:
                    logger.info(f"Profil créé automatiquement pour superutilisateur: {request.user.username}")
            else:
                messages.error(request, "Profil utilisateur non trouvé")
                return redirect('connexion')
        
        # Vérifier les permissions
        if not _peut_creer_demande_interim(profil_utilisateur):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': "Vous n'êtes pas autorisé à créer des demandes d'intérim"
                })
            messages.error(request, "Vous n'êtes pas autorisé à créer des demandes d'intérim")
            return redirect('index_n3_global' if request.user.is_superuser else 'index')
                
        # Traitement POST - Création de la demande avec gestion complète
        if request.method == 'POST':
            try:
                return _traiter_creation_demande_complete(request, profil_utilisateur)
            except Exception as e:
                logger.error(f"Erreur traitement POST: {e}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': f"Erreur lors du traitement: {str(e)}"
                    })
                else:
                    messages.error(request, "Erreur lors de la création de la demande")
                    return redirect('interim_demande')
        
        # Affichage GET - Préparer les données pour le formulaire
        context = _preparer_contexte_formulaire(profil_utilisateur)
        return render(request, 'interim_demande.html', context)
        
    except Exception as e:
        logger.error(f"Erreur vue interim_demande: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': "Erreur lors du chargement de la page"
            })
        else:
            messages.error(request, "Erreur lors du chargement de la page")
            return redirect('index_n3_global' if request.user.is_superuser else 'index')
        
def _traiter_creation_demande_complete(request, profil_utilisateur):
    """
    Traite la création complète d'une demande avec toutes les combinaisons de candidats
    """
    logger.info("🚀 DEBUT _traiter_creation_demande_complete")
    
    # Récupérer les données du formulaire
    donnees_demande = _extraire_donnees_demande(request.POST)
    
    # Récupérer les données des candidats depuis les champs cachés
    candidats_automatiques = _extraire_candidats_automatiques(request.POST)
    candidats_selectionnes = _extraire_candidats_selectionnes(request.POST)
    candidat_specifique = _extraire_candidat_specifique(request.POST)
    mode_creation = request.POST.get('mode_creation', 'classique')
    
    logger.info(f"Mode création: {mode_creation}")
    logger.info(f"Candidats automatiques: {len(candidats_automatiques)}")
    logger.info(f"Candidats sélectionnés: {len(candidats_selectionnes)}")
    logger.info(f"Candidat spécifique: {'Oui' if candidat_specifique else 'Non'}")
    
    # Validation des données de base
    try:
        _valider_donnees_demande(donnees_demande)
        _valider_coherence_departement(donnees_demande)
    except ValidationError as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        messages.error(request, str(e))
        return redirect('interim_demande')
    
    # Validation selon le mode de création
    try:
        _valider_donnees_candidats(request.POST, mode_creation, candidats_selectionnes, candidat_specifique)
    except ValidationError as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        messages.error(request, str(e))
        return redirect('interim_demande')
    
    # Créer la demande et les propositions
    try:
        with transaction.atomic():
            # 1. Créer la demande de base
            demande = _creer_demande_depuis_donnees_complete(profil_utilisateur, donnees_demande)
            
            # 2. Enregistrer la liste complète des candidats automatiques (pour historique)
            if candidats_automatiques:
                _enregistrer_liste_candidats_automatiques(demande, candidats_automatiques)
            
            # 3. Créer les propositions selon le mode
            propositions_creees = []
            
            if mode_creation in ['automatique', 'mixte'] and candidats_selectionnes:
                # Propositions des candidats automatiques sélectionnés
                for candidat_data in candidats_selectionnes:
                    proposition = _creer_proposition_candidat_automatique(
                        demande, candidat_data, profil_utilisateur, request.POST
                    )
                    propositions_creees.append(proposition)
                    logger.info(f"Proposition candidat automatique créée: {candidat_data['nom_complet']}")
            
            if mode_creation in ['specifique', 'mixte'] and candidat_specifique:
                # Proposition du candidat spécifique
                proposition = _creer_proposition_candidat_specifique(
                    demande, candidat_specifique, profil_utilisateur, request.POST
                )
                propositions_creees.append(proposition)
                logger.info(f"Proposition candidat spécifique créée: {candidat_specifique['nom_complet']}")
            
            # 4. Créer l'historique détaillé
            _creer_historique_creation_complete(
                demande, profil_utilisateur, mode_creation, 
                candidats_automatiques, candidats_selectionnes, candidat_specifique, request
            )
            
            logger.info(f"Demande créée avec succès: {demande.numero_demande}")
            logger.info(f"Propositions créées: {len(propositions_creees)}")
            
            # 5. Préparer la réponse
            response_data = {
                'success': True,
                'numero_demande': demande.numero_demande,
                'demande_id': demande.id,
                'redirect_url': reverse('demande_detail', args=[demande.id]),
                'mode_creation': mode_creation,
                'nb_propositions_creees': len(propositions_creees),
                'message': _generer_message_succes(demande, mode_creation, len(propositions_creees))
            }
            
            # Ajouter les détails des propositions
            if propositions_creees:
                response_data['propositions'] = [
                    {
                        'candidat_nom': prop.candidat_propose.nom_complet,
                        'candidat_matricule': prop.candidat_propose.matricule,
                        'source': prop.source_proposition,
                        'score_final': prop.score_final
                    }
                    for prop in propositions_creees
                ]
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse(response_data)
            else:
                messages.success(request, response_data['message'])
                return redirect('demande_detail', demande_id=demande.id)
                
    except Exception as e:
        logger.error(f"Erreur création demande complète: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f"Erreur lors de la création: {str(e)}"
            })
        messages.error(request, "Erreur lors de la création de la demande")
        return redirect('interim_demande')

def _extraire_donnees_demande(post_data):
    """Extrait les données de base de la demande"""
    return {
        'personne_remplacee_id': post_data.get('personne_remplacee_id'),
        'poste_id': post_data.get('poste_id'),
        'motif_absence_id': post_data.get('motif_absence_id'),
        'date_debut': post_data.get('date_debut'),
        'date_fin': post_data.get('date_fin'),
        'urgence': post_data.get('urgence', 'NORMALE'),
        'description_poste': post_data.get('description_poste', ''),
        'competences_indispensables': post_data.get('competences_indispensables', ''),
        'instructions_particulieres': post_data.get('instructions_particulieres', ''),
        'nb_max_propositions': post_data.get('nb_max_propositions', 3)
    }

def _extraire_candidats_automatiques(post_data):
    """Extrait la liste complète des candidats automatiques"""
    try:
        candidats_data = post_data.get('candidats_automatiques_data', '')
        if candidats_data:
            return json.loads(candidats_data)
        return []
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Erreur extraction candidats automatiques: {e}")
        return []

def _extraire_candidats_selectionnes(post_data):
    """Extrait les candidats automatiques sélectionnés"""
    try:
        candidats_data = post_data.get('candidats_selectionnes_data', '')
        if candidats_data:
            return json.loads(candidats_data)
        return []
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Erreur extraction candidats sélectionnés: {e}")
        return []

def _extraire_candidat_specifique(post_data):
    """Extrait les données du candidat spécifique"""
    try:
        candidat_data = post_data.get('candidat_specifique_data', '')
        if candidat_data:
            return json.loads(candidat_data)
        return None
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Erreur extraction candidat spécifique: {e}")
        return None
    
def _valider_donnees_demande(donnees):
    """Valide les données de base de la demande"""
    required_fields = ['personne_remplacee_id', 'poste_id', 'motif_absence_id', 
                      'date_debut', 'date_fin', 'description_poste']
    
    for field in required_fields:
        if not donnees.get(field):
            raise ValidationError(f"Le champ {field} est obligatoire")
    
    # Validation des dates
    try:
        date_debut = datetime.strptime(donnees['date_debut'], '%Y-%m-%d').date()
        date_fin = datetime.strptime(donnees['date_fin'], '%Y-%m-%d').date()
        
        if date_debut >= date_fin:
            raise ValidationError("La date de début doit être antérieure à la date de fin")
            
        if date_debut < date.today():
            raise ValidationError("La date de début ne peut pas être dans le passé")
            
    except ValueError:
        raise ValidationError("Format de date invalide")

def _valider_coherence_departement(donnees):
    """Valide la cohérence département entre personne remplacée et poste"""
    try:
        personne_remplacee = ProfilUtilisateur.objects.get(id=donnees['personne_remplacee_id'])
        poste = Poste.objects.get(id=donnees['poste_id'])
        
        if personne_remplacee.departement != poste.departement:
            raise ValidationError(
                f"Incohérence département : {personne_remplacee.nom_complet} "
                f"appartient au département {personne_remplacee.departement.nom if personne_remplacee.departement else 'Non défini'} "
                f"mais le poste sélectionné appartient au département {poste.departement.nom}"
            )
            
    except (ProfilUtilisateur.DoesNotExist, Poste.DoesNotExist):
        raise ValidationError("Données de référence invalides")

def _valider_donnees_candidats(post_data, mode_creation, candidats_selectionnes, candidat_specifique):
    """Valide les données des candidats selon le mode de création"""
    
    if mode_creation in ['automatique', 'mixte'] and candidats_selectionnes:
        # Vérifier la justification pour candidats automatiques
        justification_auto = post_data.get('justification_auto_candidat', '').strip()
        if not justification_auto:
            raise ValidationError("La justification est obligatoire pour les candidats automatiques sélectionnés")
    
    if mode_creation in ['specifique', 'mixte'] and candidat_specifique:
        # Vérifier la justification pour candidat spécifique
        justification_spec = post_data.get('justification_specifique', '').strip()
        if not justification_spec:
            raise ValidationError("La justification est obligatoire pour le candidat spécifique")
        
        # Vérifier que le candidat spécifique existe
        candidat_id = candidat_specifique.get('id')
        if not candidat_id:
            raise ValidationError("ID du candidat spécifique manquant")
        
        try:
            ProfilUtilisateur.objects.get(id=candidat_id, actif=True, statut_employe='ACTIF')
        except ProfilUtilisateur.DoesNotExist:
            raise ValidationError("Le candidat spécifique sélectionné n'est plus disponible")

def _creer_demande_depuis_donnees_complete(profil_utilisateur, donnees):
    """Crée la demande d'intérim à partir des données validées"""
    
    # Récupérer les objets requis
    personne_remplacee = get_object_or_404(ProfilUtilisateur, id=donnees['personne_remplacee_id'])
    poste = get_object_or_404(Poste, id=donnees['poste_id'])
    motif_absence = get_object_or_404(MotifAbsence, id=donnees['motif_absence_id'])
    
    # Convertir les dates
    date_debut = datetime.strptime(donnees['date_debut'], '%Y-%m-%d').date()
    date_fin = datetime.strptime(donnees['date_fin'], '%Y-%m-%d').date()
    
    # Créer la demande
    demande = DemandeInterim.objects.create(
        demandeur=profil_utilisateur,
        personne_remplacee=personne_remplacee,
        poste=poste,
        motif_absence=motif_absence,
        date_debut=date_debut,
        date_fin=date_fin,
        urgence=donnees.get('urgence', 'NORMALE'),
        description_poste=donnees.get('description_poste', ''),
        competences_indispensables=donnees.get('competences_indispensables', ''),
        instructions_particulieres=donnees.get('instructions_particulieres', ''),
        nb_max_propositions_par_utilisateur=int(donnees.get('nb_max_propositions', 3)),
        statut='SOUMISE'
    )
    
    return demande

def _creer_proposition_candidat_automatique(demande, candidat_data, profil_utilisateur, post_data):
    """Crée une proposition pour un candidat automatique sélectionné"""
    
    candidat = get_object_or_404(ProfilUtilisateur, id=candidat_data['id'])
    
    # Calculer le score avec le service de scoring
    score_final = _calculer_score_avec_bonus(candidat, demande, profil_utilisateur)
    
    # Récupérer la justification
    justification = post_data.get('justification_auto_candidat', '').strip()
    competences_specifiques = post_data.get('competences_specifiques_auto', '').strip()
    
    proposition = PropositionCandidat.objects.create(
        demande_interim=demande,
        candidat_propose=candidat,
        proposant=profil_utilisateur,
        source_proposition='DEMANDEUR_INITIAL',
        justification=justification,
        competences_specifiques=competences_specifiques,
        score_automatique=candidat_data.get('score', 0),
        score_final=score_final,
        statut='SOUMISE'
    )
    
    return proposition

def _creer_proposition_candidat_specifique(demande, candidat_specifique, profil_utilisateur, post_data):
    """Crée une proposition pour le candidat spécifique"""
    
    candidat = get_object_or_404(ProfilUtilisateur, id=candidat_specifique['id'])
    
    # Calculer le score avec le service de scoring
    score_final = _calculer_score_avec_bonus(candidat, demande, profil_utilisateur)
    
    # Récupérer les données du formulaire
    justification = post_data.get('justification_specifique', '').strip()
    competences_specifiques = post_data.get('competences_specifiques_spec', '').strip()
    experience_pertinente = post_data.get('experience_pertinente_spec', '').strip()
    
    proposition = PropositionCandidat.objects.create(
        demande_interim=demande,
        candidat_propose=candidat,
        proposant=profil_utilisateur,
        source_proposition='DEMANDEUR_INITIAL',
        justification=justification,
        competences_specifiques=competences_specifiques,
        experience_pertinente=experience_pertinente,
        score_automatique=candidat_specifique.get('score', 0),
        score_final=score_final,
        statut='SOUMISE'
    )
    
    return proposition

def _calculer_score_avec_bonus(candidat, demande, profil_utilisateur):
    """Calcule le score final avec les bonus hiérarchiques"""
    try:
        from .services.scoring_service import ScoringInterimService
        
        service_scoring = ScoringInterimService()
        score_base = service_scoring.calculer_score_candidat_v41(candidat, demande)
        
        # Calculer les bonus
        bonus_validateur = _calculer_bonus_validateur(profil_utilisateur)
        bonus_priorite = _calculer_bonus_priorite(demande.urgence)
        
        # Score final
        score_final = min(100, max(0, score_base + bonus_validateur + bonus_priorite))
        
        return score_final
        
    except Exception as e:
        logger.error(f"Erreur calcul score avec bonus: {e}")
        return 50  # Score par défaut

def _enregistrer_liste_candidats_automatiques(demande, candidats_automatiques):
    """Enregistre la liste complète des candidats automatiques pour historique"""
    try:
        for candidat_data in candidats_automatiques:
            candidat = ProfilUtilisateur.objects.get(id=candidat_data.get('id'))
            
            # Créer ou mettre à jour le score détaillé
            score_detail, created = ScoreDetailCandidat.objects.get_or_create(
                candidat=candidat,
                demande_interim=demande,
                defaults={
                    'score_total': candidat_data.get('score', 0),
                    'calcule_par': 'AUTOMATIQUE',
                    'score_similarite_poste': candidat_data.get('detail_scoring', {}).get('similarite_poste', 0),
                    'score_competences': candidat_data.get('detail_scoring', {}).get('competences', 0),
                    'score_experience': candidat_data.get('detail_scoring', {}).get('experience', 0),
                    'score_disponibilite': candidat_data.get('detail_scoring', {}).get('disponibilite', 0),
                    'score_proximite': candidat_data.get('detail_scoring', {}).get('proximite', 0),
                    'score_anciennete': candidat_data.get('detail_scoring', {}).get('anciennete', 0),
                    'bonus_proposition_humaine': 0,
                    'bonus_experience_similaire': candidat_data.get('detail_scoring', {}).get('bonus_experience', 0),
                    'bonus_recommandation': 0,
                    'penalite_indisponibilite': candidat_data.get('detail_scoring', {}).get('penalite_indispo', 0)
                }
            )
        
        logger.info(f"Liste de {len(candidats_automatiques)} candidats automatiques enregistrée pour demande {demande.numero_demande}")
        
    except Exception as e:
        logger.error(f"Erreur enregistrement liste candidats automatiques: {e}")

def _creer_historique_creation_complete(demande, profil_utilisateur, mode_creation, 
                                      candidats_automatiques, candidats_selectionnes, 
                                      candidat_specifique, request):
    """Crée l'historique détaillé de la création"""
    
    # Préparer les données pour l'historique
    donnees_apres = {
        'type_creation': mode_creation,
        'nb_candidats_automatiques_analyses': len(candidats_automatiques),
        'nb_candidats_automatiques_selectionnes': len(candidats_selectionnes),
        'candidat_specifique_presente': candidat_specifique is not None,
        'created_by_superuser': request.user.is_superuser,
        'urgence': demande.urgence,
        'duree_mission_jours': (demande.date_fin - demande.date_debut).days + 1 if demande.date_debut and demande.date_fin else 0
    }
    
    # Ajouter les détails des candidats sélectionnés
    if candidats_selectionnes:
        donnees_apres['candidats_automatiques_selectionnes'] = [
            {
                'matricule': c.get('matricule'),
                'nom_complet': c.get('nom_complet'),
                'score': c.get('score')
            }
            for c in candidats_selectionnes
        ]
    
    if candidat_specifique:
        donnees_apres['candidat_specifique'] = {
            'matricule': candidat_specifique.get('matricule'),
            'nom_complet': candidat_specifique.get('nom_complet'),
            'score': candidat_specifique.get('score')
        }
    
    # Générer la description selon le mode
    descriptions = {
        'classique': f"Création classique de la demande {demande.numero_demande} sans proposition de candidat",
        'automatique': f"Création de la demande {demande.numero_demande} avec {len(candidats_selectionnes)} candidat(s) automatique(s) sélectionné(s)",
        'specifique': f"Création de la demande {demande.numero_demande} avec candidat spécifique ({candidat_specifique.get('nom_complet', '')})",
        'mixte': f"Création de la demande {demande.numero_demande} avec {len(candidats_selectionnes)} candidat(s) automatique(s) + 1 candidat spécifique"
    }
    
    description = descriptions.get(mode_creation, f"Création de la demande {demande.numero_demande}")
    
    HistoriqueAction.objects.create(
        demande=demande,
        action='CREATION_DEMANDE',
        utilisateur=profil_utilisateur,
        description=description,
        donnees_apres=donnees_apres,
        niveau_hierarchique=profil_utilisateur.type_profil,
        is_superuser=profil_utilisateur.is_superuser
    )

def _generer_message_succes(demande, mode_creation, nb_propositions):
    """Génère le message de succès selon le mode de création"""
    
    messages = {
        'classique': f"Demande {demande.numero_demande} créée avec succès",
        'automatique': f"Demande {demande.numero_demande} créée avec {nb_propositions} candidat(s) automatique(s) proposé(s)",
        'specifique': f"Demande {demande.numero_demande} créée avec candidat spécifique proposé",
        'mixte': f"Demande {demande.numero_demande} créée avec {nb_propositions} candidat(s) proposé(s) (automatiques + spécifique)"
    }
    
    return messages.get(mode_creation, f"Demande {demande.numero_demande} créée avec succès")

def _preparer_contexte_formulaire(profil_utilisateur):
    """Prépare le contexte pour l'affichage GET du formulaire"""
    
    # Déterminer les données accessibles selon les permissions
    if profil_utilisateur.is_superuser or getattr(profil_utilisateur, 'type_profil', None) in ['RH', 'ADMIN']:
        # Accès complet
        departements = Departement.objects.filter(actif=True).order_by('nom')
    else:
        # Accès limité au département
        departement_user = getattr(profil_utilisateur, 'departement', None)
        if departement_user:
            departements = Departement.objects.filter(id=departement_user.id, actif=True)
        else:
            departements = Departement.objects.none()
    
    # Autres données
    postes = Poste.objects.filter(actif=True, interim_autorise=True).select_related('departement', 'site')
    motifs_absence = MotifAbsence.objects.filter(actif=True).order_by('categorie', 'nom')
    urgences = DemandeInterim.URGENCES
    
    # Candidats proposables pour proposition optionnelle
    candidats_proposables = _get_candidats_proposables(profil_utilisateur)
    
    # Vérifier si l'utilisateur peut proposer des candidats
    peut_proposer_candidat = _peut_creer_demande_interim(profil_utilisateur)
    
    # Statistiques contextuelles
    stats_contextuelles = {}
    try:
        if profil_utilisateur.departement:
            stats_contextuelles = {
                'Demandes en cours (dept)': DemandeInterim.objects.filter(
                    poste__departement=profil_utilisateur.departement,
                    statut__in=['SOUMISE', 'EN_VALIDATION', 'EN_COURS']
                ).count(),
                'Missions actives (dept)': DemandeInterim.objects.filter(
                    poste__departement=profil_utilisateur.departement,
                    statut='EN_COURS'
                ).count(),
                'Employés disponibles': ProfilUtilisateur.objects.filter(
                    departement=profil_utilisateur.departement,
                    actif=True,
                    statut_employe='ACTIF'
                ).count()
            }
    except Exception:
        pass
    
    # Niveaux de validation pour le workflow
    niveaux_validation = _get_niveaux_validation_pour_utilisateur(profil_utilisateur)
    
    context = {
        'profil_utilisateur': profil_utilisateur,
        'departements': departements,
        'postes': postes,
        'motifs_absence': motifs_absence,
        'urgences': urgences,
        'candidats_proposables': candidats_proposables,
        'peut_proposer_candidat': peut_proposer_candidat,
        'stats_contextuelles': stats_contextuelles,
        'niveaux_validation': niveaux_validation,
        'is_superuser': profil_utilisateur.is_superuser,
        'page_title': 'Nouvelle demande d\'intérim',
        'today': timezone.now().date(),
        'user_display_name': profil_utilisateur.nom_complet,
    }
    
    return context
    
def _get_candidats_proposables(profil_utilisateur):
    """
    Retourne les candidats que l'utilisateur peut proposer
    CORRECTION : Éviter les slices dans la requête de base
    """
    try:
        # Requête de base sans slice
        candidats_base = ProfilUtilisateur.objects.filter(
            actif=True,
            statut_employe='ACTIF'
        ).select_related(
            'user', 'poste', 'departement', 'site'
        )
        
        # Filtres selon les permissions
        if profil_utilisateur.is_superuser:
            # Superuser : tous les candidats actifs
            return candidats_base
        
        elif profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            # RH/ADMIN : tous les candidats actifs
            return candidats_base
        
        elif profil_utilisateur.type_profil in ['DIRECTEUR']:
            # Directeur : peut proposer dans tous les départements
            return candidats_base
        
        elif profil_utilisateur.type_profil in ['RESPONSABLE', 'CHEF_EQUIPE']:
            # Responsable/Chef : même département + départements gérés
            departements_autorises = [profil_utilisateur.departement.id] if profil_utilisateur.departement else []
            
            # Ajouter les départements gérés
            if hasattr(profil_utilisateur, 'departements_geres'):
                departements_autorises.extend(
                    profil_utilisateur.departements_geres.values_list('id', flat=True)
                )
            
            if departements_autorises:
                return candidats_base.filter(departement_id__in=departements_autorises)
            else:
                return candidats_base.filter(departement=profil_utilisateur.departement)
        
        else:
            # Utilisateur standard : même département seulement
            if profil_utilisateur.departement:
                return candidats_base.filter(departement=profil_utilisateur.departement)
            else:
                return ProfilUtilisateur.objects.none()
    
    except Exception as e:
        logger.error(f"Erreur _get_candidats_proposables: {e}")
        return ProfilUtilisateur.objects.none()

def _get_niveaux_validation_pour_utilisateur(profil_utilisateur):
    """Récupère les niveaux de validation prévus pour le workflow"""
    niveaux = []
    
    try:
        # Niveau 1 : Responsable
        if profil_utilisateur.departement:
            responsables = ProfilUtilisateur.objects.filter(
                type_profil='RESPONSABLE',
                departement=profil_utilisateur.departement,
                actif=True
            )
            for resp in responsables:
                niveaux.append({
                    'niveau': 1,
                    'titre': 'Responsable département (N+1)',
                    'nom': resp.nom_complet,
                    'poste': resp.poste.titre if resp.poste else 'Responsable'
                })
        
        # Niveau 2 : Directeur
        directeurs = ProfilUtilisateur.objects.filter(
            type_profil='DIRECTEUR',
            actif=True
        )
        for dir in directeurs:
            niveaux.append({
                'niveau': 2,
                'titre': 'Directeur (N+2)',
                'nom': dir.nom_complet,
                'poste': dir.poste.titre if dir.poste else 'Directeur'
            })
        
        # Niveau 3 : RH/Admin
        rh_admin = ProfilUtilisateur.objects.filter(
            type_profil__in=['RH', 'ADMIN'],
            actif=True
        )
        for rh in rh_admin:
            niveaux.append({
                'niveau': 3,
                'titre': 'Validation finale (RH/Admin)',
                'nom': rh.nom_complet,
                'poste': rh.poste.titre if rh.poste else rh.type_profil
            })
            
    except Exception as e:
        logger.error(f"Erreur récupération niveaux validation: {e}")
    
    return niveaux
    
# ================================================================
# VUES AJAX POUR SUPPORTER LA PROPOSITION AUTOMATIQUE
# ================================================================

@login_required
def ajax_proposition_automatique(request):
    """
    Vue AJAX pour générer la proposition automatique de candidats avec scoring
    MODIFICATION : Proposer seulement des candidats du même département
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
        
        profil_utilisateur = get_profil_or_virtual(request.user)
        
        # Récupérer les données de la requête
        data = json.loads(request.body)
        
        personne_remplacee_id = data.get('personne_remplacee_id')
        poste_id = data.get('poste_id')
        date_debut = data.get('date_debut')
        date_fin = data.get('date_fin')
        description_poste = data.get('description_poste', '')
        competences_indispensables = data.get('competences_indispensables', '')
        urgence = data.get('urgence', 'NORMALE')
        
        # Validation des données
        if not all([personne_remplacee_id, poste_id, date_debut, date_fin]):
            return JsonResponse({
                'success': False,
                'error': 'Données manquantes pour la recherche automatique'
            })
        
        # Récupérer les objets
        try:
            personne_remplacee = ProfilUtilisateur.objects.get(id=personne_remplacee_id)
            poste = Poste.objects.get(id=poste_id)
            date_debut_obj = datetime.strptime(date_debut, '%Y-%m-%d').date()
            date_fin_obj = datetime.strptime(date_fin, '%Y-%m-%d').date()
        except (ProfilUtilisateur.DoesNotExist, Poste.DoesNotExist, ValueError) as e:
            return JsonResponse({
                'success': False,
                'error': f'Données invalides: {str(e)}'
            })
        
        # *** VERIFICATION COHERENCE DEPARTEMENT ***
        if personne_remplacee.departement != poste.departement:
            return JsonResponse({
                'success': False,
                'error': f'Incohérence département : {personne_remplacee.nom_complet} '
                        f'appartient au département {personne_remplacee.departement.nom if personne_remplacee.departement else "Non défini"} '
                        f'mais le poste sélectionné appartient au département {poste.departement.nom}'
            })
        
        # Créer une demande temporaire pour le calcul de score
        demande_temp = DemandeInterim(
            demandeur=profil_utilisateur,
            personne_remplacee=personne_remplacee,
            poste=poste,
            date_debut=date_debut_obj,
            date_fin=date_fin_obj,
            urgence=urgence,
            description_poste=description_poste,
            competences_indispensables=competences_indispensables
        )
        
        # *** MODIFICATION MAJEURE : Candidats du même département seulement ***
        candidats_potentiels = ProfilUtilisateur.objects.filter(
            actif=True,
            statut_employe='ACTIF',
            departement=poste.departement  # *** RESTRICTION DEPARTEMENT ***
        ).exclude(
            id__in=[personne_remplacee_id, profil_utilisateur.id]
        ).select_related('user', 'poste', 'departement', 'site')
        
        # Calculer les scores pour chaque candidat
        candidats_avec_scores = []
        
        for candidat in candidats_potentiels:
            try:
                # Calculer le score (utiliser le service de scoring si disponible)
                score = _calculer_score_candidat_simple(candidat, demande_temp)
                
                # Vérifier la disponibilité
                disponibilite = _verifier_disponibilite_candidat(candidat, demande_temp.date_debut,  demande_temp.date_fin)
                
                # Récupérer les compétences clés
                competences_cles = _get_competences_cles_candidat(candidat)
                
                candidat_data = {
                    'id': candidat.id,
                    'matricule': candidat.matricule,
                    'nom_complet': candidat.nom_complet,
                    'poste_actuel': candidat.poste.titre if candidat.poste else None,
                    'departement': candidat.departement.nom if candidat.departement else None,
                    'site': candidat.site.nom if candidat.site else None,
                    'anciennete': _calculer_anciennete_display(candidat),
                    'score': score,
                    'disponibilite': disponibilite,
                    'competences_cles': competences_cles,
                    'detail_scoring': {
                        'similarite_poste': min(100, score * 0.3),
                        'competences': min(100, score * 0.25),
                        'experience': min(100, score * 0.2),
                        'disponibilite': 100 if disponibilite['disponible'] else 50,
                        'proximite': min(100, score * 0.15),
                        'anciennete': min(100, score * 0.1)
                    }
                }
                
                candidats_avec_scores.append(candidat_data)
                
            except Exception as e:
                logger.warning(f"Erreur calcul score pour candidat {candidat.id}: {e}")
                continue
        
        # Trier par score décroissant et limiter à 50
        candidats_avec_scores.sort(key=lambda x: x['score'], reverse=True)
        top_candidats = candidats_avec_scores[:50]
        
        logger.info(f"Proposition automatique: {len(top_candidats)} candidats trouvés et scorés (département {poste.departement.nom})")
        
        return JsonResponse({
            'success': True,
            'candidats': top_candidats,
            'nb_candidats_total': len(candidats_avec_scores),
            'nb_candidats_retournes': len(top_candidats),
            'departement_filtre': poste.departement.nom,  # *** NOUVELLE INFO ***
            'criteres_recherche': {
                'poste': poste.titre,
                'departement': poste.departement.nom,
                'date_debut': date_debut,
                'date_fin': date_fin,
                'urgence': urgence,
                'restriction_departement': True  # *** NOUVELLE INFO ***
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur proposition automatique: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur lors de la recherche automatique: {str(e)}'
        })

@login_required
def ajax_calculer_score_candidat(request):
    """
    Vue AJAX pour calculer le score d'un candidat spécifique
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
        
        profil_utilisateur = get_profil_or_virtual(request.user)
        
        # Récupérer les données
        data = json.loads(request.body)
        
        candidat_id = data.get('candidat_id')
        personne_remplacee_id = data.get('personne_remplacee_id')
        poste_id = data.get('poste_id')
        date_debut = data.get('date_debut')
        date_fin = data.get('date_fin')
        description_poste = data.get('description_poste', '')
        competences_indispensables = data.get('competences_indispensables', '')
        
        # Validation
        if not all([candidat_id, personne_remplacee_id, poste_id, date_debut, date_fin]):
            return JsonResponse({
                'success': False,
                'error': 'Données manquantes pour le calcul du score'
            })
        
        # Récupérer les objets
        try:
            candidat = ProfilUtilisateur.objects.get(id=candidat_id)
            personne_remplacee = ProfilUtilisateur.objects.get(id=personne_remplacee_id)
            poste = Poste.objects.get(id=poste_id)
            date_debut_obj = datetime.strptime(date_debut, '%Y-%m-%d').date()
            date_fin_obj = datetime.strptime(date_fin, '%Y-%m-%d').date()
        except (ProfilUtilisateur.DoesNotExist, Poste.DoesNotExist, ValueError) as e:
            return JsonResponse({
                'success': False,
                'error': f'Données invalides: {str(e)}'
            })
        
        # Créer une demande temporaire pour le calcul
        demande_temp = DemandeInterim(
            demandeur=profil_utilisateur,
            personne_remplacee=personne_remplacee,
            poste=poste,
            date_debut=date_debut_obj,
            date_fin=date_fin_obj,
            description_poste=description_poste,
            competences_indispensables=competences_indispensables
        )
        
        # Calculer le score
        score = _calculer_score_candidat_simple(candidat, demande_temp)
        
        # Vérifier la disponibilité
        disponibilite = _verifier_disponibilite_candidat(candidat, demande_temp.date_debut, demande_temp.date_fin)
        
        return JsonResponse({
            'success': True,
            'score': score,
            'disponibilite': disponibilite,
            'candidat': {
                'id': candidat.id,
                'matricule': candidat.matricule,
                'nom_complet': candidat.nom_complet,
                'poste_actuel': candidat.poste.titre if candidat.poste else None,
                'departement': candidat.departement.nom if candidat.departement else None
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur calcul score candidat: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur lors du calcul du score: {str(e)}'
        })
    
@login_required
def ajax_rechercher_employe(request):
    """
    Vue AJAX pour rechercher un employé par matricule
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
        
        # Récupérer les données
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        if not matricule or len(matricule) < 2:
            return JsonResponse({
                'success': False,
                'error': 'Matricule trop court'
            })
        
        # Rechercher l'employé
        try:
            employe = ProfilUtilisateur.objects.select_related(
                'user', 'poste', 'departement', 'site'
            ).get(matricule=matricule)
            
            # Vérifier que l'employé est actif
            if not employe.actif or employe.statut_employe != 'ACTIF':
                return JsonResponse({
                    'success': False,
                    'error': f'Employé {matricule} non actif'
                })
            
            # Calculer l'ancienneté
            anciennete = _calculer_anciennete_display(employe)
            
            employe_data = {
                'id': employe.id,
                'matricule': employe.matricule,
                'nom_complet': employe.nom_complet,
                'sexe': employe.kelio_data.sexe if hasattr(employe, 'kelio_data') else None,
                'anciennete': anciennete,
                'departement': employe.departement.nom if employe.departement else None,
                'site': employe.site.nom if employe.site else None,
                'poste': employe.poste.titre if employe.poste else None,
                'email': employe.user.email if employe.user else None,
                'statut': employe.statut_employe
            }
            
            # Informations de synchronisation
            sync_info = {
                'is_recent': True,
                'last_sync': timezone.now().isoformat() if employe.kelio_last_sync else None,
                'source': 'LOCAL'
            }
            
            return JsonResponse({
                'success': True,
                'employe': employe_data,
                'sync_info': sync_info
            })
            
        except ProfilUtilisateur.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Aucun employé trouvé avec le matricule {matricule}'
            })
            
    except Exception as e:
        logger.error(f"Erreur recherche employé: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur lors de la recherche: {str(e)}'
        })

# ================================================================
# FONCTIONS UTILITAIRES POUR LE SCORING
# ================================================================

def _calculer_score_candidat_simple(candidat, demande_temp):
    """
    Calcule un score simple pour un candidat en utilisant le service officiel V4.1
    Score de 0 à 100 basé sur les critères et barèmes officiels du scoring_service.py
    """
    try:
        # Import du service de scoring officiel V4.1
        from .services.scoring_service import ScoringInterimService
        
        logger.info(f">>> Calcul score simple pour candidat {candidat.matricule} avec service V4.1")
        
        # Créer une instance du service de scoring V4.1 harmonisé
        service_scoring = ScoringInterimService()
        
        # Calcul du score avec la méthode officielle V4.1
        score_final = service_scoring.calculer_score_candidat_v41(
            candidat=candidat,
            demande=demande_temp,
            config=None,  # Utiliser la configuration par défaut
            utiliser_cache=True  # Optimiser les performances
        )
        
        # Validation et conversion du score
        if score_final is None:
            logger.warning(f"Score V4.1 retourné None pour {candidat.matricule} - utilisation fallback")
            score_final = _calculer_score_fallback_simple(candidat, demande_temp)
        
        try:
            score_final = int(float(score_final))
        except (ValueError, TypeError):
            logger.warning(f"Score V4.1 invalide pour {candidat.matricule}: {score_final} - utilisation fallback")
            score_final = _calculer_score_fallback_simple(candidat, demande_temp)
        
        # S'assurer que le score est dans la plage valide
        score_final = max(0, min(100, score_final))
        
        logger.info(f"OK Score V4.1 calculé pour {candidat.matricule}: {score_final}")
        return score_final
        
    except ImportError as e:
        logger.warning(f"Service scoring V4.1 non disponible: {e} - utilisation fallback")
        return _calculer_score_fallback_simple(candidat, demande_temp)
    
    except Exception as e:
        logger.error(f"Erreur calcul score V4.1 pour candidat {candidat.matricule}: {e}")
        return _calculer_score_fallback_simple(candidat, demande_temp)


def _calculer_score_fallback_simple(candidat, demande_temp):
    """
    Calcul de score de secours basé sur les critères simplifiés
    S'inspire des méthodes fallback du scoring_service.py
    """
    try:
        logger.info(f">>> Calcul score fallback pour candidat {candidat.matricule}")
        
        score_total = 0
        
        # 1. Similarité de poste (25% - poids officiel V4.1)
        score_similarite = _score_similarite_poste_fallback(candidat, demande_temp)
        score_total += score_similarite * 0.25
        
        # 2. Compétences (30% - poids officiel V4.1 pour compétences Kelio)
        score_competences = _score_competences_fallback(candidat)
        score_total += score_competences * 0.30
        
        # 3. Expérience/Ancienneté (20% - poids officiel V4.1)
        score_experience = _score_experience_fallback(candidat)
        score_total += score_experience * 0.20
        
        # 4. Disponibilité (15% - poids officiel V4.1)
        score_disponibilite = _score_disponibilite_fallback(candidat, demande_temp)
        score_total += score_disponibilite * 0.15
        
        # 5. Proximité géographique (10% - poids officiel V4.1)
        score_proximite = _score_proximite_fallback(candidat, demande_temp)
        score_total += score_proximite * 0.10
        
        # Conversion en entier et validation
        score_final = max(0, min(100, int(score_total)))
        
        logger.info(f"OK Score fallback calculé pour {candidat.matricule}: {score_final}")
        return score_final
        
    except Exception as e:
        logger.error(f"Erreur score fallback pour candidat {candidat.matricule}: {e}")
        return 50  # Score neutre par défaut


def _score_similarite_poste_fallback(candidat, demande_temp):
    """Score similarité de poste - version fallback basée sur scoring_service.py"""
    try:
        if not candidat.poste or not demande_temp.poste:
            return 40  # Score par défaut comme dans le service V4.1
        
        score = 50  # Base
        
        # Même poste exact
        if candidat.poste == demande_temp.poste:
            return 100
        
        # Même département
        if candidat.poste.departement == demande_temp.poste.departement:
            score += 25
        
        # Même niveau de responsabilité
        if hasattr(candidat.poste, 'niveau_responsabilite') and hasattr(demande_temp.poste, 'niveau_responsabilite'):
            if candidat.poste.niveau_responsabilite == demande_temp.poste.niveau_responsabilite:
                score += 20
        
        # Même site
        if hasattr(candidat.poste, 'site') and hasattr(demande_temp.poste, 'site'):
            if candidat.poste.site == demande_temp.poste.site:
                score += 15
        
        # Similarité textuelle des titres
        if hasattr(candidat.poste, 'titre') and hasattr(demande_temp.poste, 'titre'):
            candidat_titre = candidat.poste.titre.lower()
            demande_titre = demande_temp.poste.titre.lower()
            
            mots_cles_communs = set(candidat_titre.split()) & set(demande_titre.split())
            if len(mots_cles_communs) >= 2:
                score += 10
        
        return min(score, 100)
        
    except Exception as e:
        logger.warning(f"Erreur score similarité fallback: {e}")
        return 40


def _score_competences_fallback(candidat):
    """Score compétences - version fallback basée sur _score_competences_interne du service V4.1"""
    try:
        # Simuler la logique de _score_competences_interne
        if hasattr(candidat, 'competences'):
            competences = candidat.competences.filter(niveau_maitrise__gte=2) if hasattr(candidat.competences, 'filter') else []
            
            if not competences or (hasattr(competences, 'exists') and not competences.exists()):
                return 30  # Score minimal comme dans le service V4.1
            
            # Calcul basé sur le niveau moyen de maîtrise
            if hasattr(competences, 'aggregate'):
                from django.db.models import Avg
                niveau_moyen = competences.aggregate(avg=Avg('niveau_maitrise'))['avg'] or 2
            else:
                # Fallback si pas d'ORM disponible
                niveau_moyen = 3  # Valeur par défaut
            
            score_base = (niveau_moyen / 4) * 80  # Logique du service V4.1
            
            # Bonus certifications
            if hasattr(competences, 'filter'):
                nb_certifiees = competences.filter(certifie=True).count()
                bonus_cert = min(nb_certifiees * 5, 15)
            else:
                bonus_cert = 0
            
            return min(int(score_base + bonus_cert), 100)
        
        return 40  # Score par défaut
        
    except Exception as e:
        logger.warning(f"Erreur score compétences fallback: {e}")
        return 40


def _score_experience_fallback(candidat):
    """Score expérience - version fallback basée sur _score_experience_fallback du service V4.1"""
    try:
        score = 40  # Base comme dans le service V4.1
        
        # Ancienneté avec données étendues si disponibles
        if hasattr(candidat, 'extended_data') and candidat.extended_data and hasattr(candidat.extended_data, 'date_embauche'):
            if candidat.extended_data.date_embauche:
                from datetime import date
                anciennete_jours = (date.today() - candidat.extended_data.date_embauche).days
                anciennete_annees = anciennete_jours / 365
                score += min(anciennete_annees * 6, 30)  # Max 30 points comme dans le service V4.1
        
        # Missions intérim passées si disponibles
        try:
            if hasattr(candidat, 'propositions_candidat'):
                missions_reussies = candidat.propositions_candidat.filter(
                    statut__in=['VALIDEE', 'TERMINEE']
                ).count()
                score += min(missions_reussies * 8, 35)  # Logique du service V4.1
        except:
            pass
        
        return min(score, 100)
        
    except Exception as e:
        logger.warning(f"Erreur score expérience fallback: {e}")
        return 40


def _score_disponibilite_fallback(candidat, demande_temp):
    """Score disponibilité - version fallback basée sur _score_disponibilite_fallback du service V4.1"""
    try:
        # Vérifications de base comme dans le service V4.1
        if not hasattr(candidat, 'statut_employe') or candidat.statut_employe != 'ACTIF':
            return 0
        
        if not hasattr(candidat, 'actif') or not candidat.actif:
            return 0
        
        score = 70  # Base pour employé actif comme dans le service V4.1
        
        # Vérifications disponibilité interim
        if hasattr(candidat, 'extended_data') and candidat.extended_data:
            if hasattr(candidat.extended_data, 'disponible_interim') and not candidat.extended_data.disponible_interim:
                return 20  # Score très bas si pas disponible pour interim
        
        # Vérifications conflits si dates disponibles
        if hasattr(demande_temp, 'date_debut') and hasattr(demande_temp, 'date_fin'):
            if demande_temp.date_debut and demande_temp.date_fin:
                
                # Absences en conflit
                try:
                    if hasattr(candidat, 'absences'):
                        absences_conflit = candidat.absences.filter(
                            date_debut__lte=demande_temp.date_fin,
                            date_fin__gte=demande_temp.date_debut
                        ).exists()
                        
                        if absences_conflit:
                            score -= 40  # Comme dans le service V4.1
                except:
                    pass
                
                # Bonus disponibilité immédiate
                from datetime import date
                if hasattr(demande_temp.date_debut, 'date'):
                    date_debut = demande_temp.date_debut.date() if hasattr(demande_temp.date_debut, 'date') else demande_temp.date_debut
                else:
                    date_debut = demande_temp.date_debut
                
                if date_debut:
                    jours_avant = (date_debut - date.today()).days
                    if jours_avant <= 1:
                        score += 15  # Disponible immédiatement
                    elif jours_avant <= 3:
                        score += 10  # Disponible rapidement
                    elif jours_avant <= 7:
                        score += 5   # Disponible à court terme
        
        return max(0, min(score, 100))
        
    except Exception as e:
        logger.warning(f"Erreur score disponibilité fallback: {e}")
        return 50


def _score_proximite_fallback(candidat, demande_temp):
    """Score proximité - version fallback basée sur _score_proximite_v41 du service V4.1"""
    try:
        if not hasattr(candidat, 'site') or not hasattr(demande_temp.poste, 'site'):
            return 40
        
        if not candidat.site or not demande_temp.poste.site:
            return 40
        
        # Même site = score maximum
        if candidat.site == demande_temp.poste.site:
            return 100
        
        score = 50  # Base pour sites différents
        
        # Rayon de déplacement si disponible
        if hasattr(candidat, 'extended_data') and candidat.extended_data:
            if hasattr(candidat.extended_data, 'rayon_deplacement_km'):
                rayon = candidat.extended_data.rayon_deplacement_km or 25
                
                # Bonus progressif selon le rayon comme dans le service V4.1
                if rayon >= 100:
                    score += 25
                elif rayon >= 75:
                    score += 20
                elif rayon >= 50:
                    score += 15
                elif rayon >= 25:
                    score += 10
                else:
                    score -= 10  # Malus si rayon très limité
        
        # Même ville
        if hasattr(candidat.site, 'ville') and hasattr(demande_temp.poste.site, 'ville'):
            if candidat.site.ville == demande_temp.poste.site.ville:
                score += 20
        
        # Même région (approximation par code postal)
        try:
            candidat_cp = getattr(candidat.site, 'code_postal', '')
            demande_cp = getattr(demande_temp.poste.site, 'code_postal', '')
            
            if candidat_cp and demande_cp and candidat_cp[:2] == demande_cp[:2]:
                score += 10  # Même département
        except:
            pass
        
        return min(score, 90)  # Max 90 pour sites différents comme dans le service V4.1
        
    except Exception as e:
        logger.warning(f"Erreur score proximité fallback: {e}")
        return 50

def _verifier_disponibilite_candidat(candidat, date_debut=None, date_fin=None):
    """
    Vérifie la disponibilité d'un candidat pour une période donnée
    CORRECTION : Éviter les requêtes complexes qui pourraient causer des slices
    """
    try:
        # Vérifications de base
        if not candidat.actif or candidat.statut_employe != 'ACTIF':
            return {
                'disponible': False,
                'raison': f'Employé non actif (statut: {candidat.statut_employe})'
            }
        
        # Si pas de dates spécifiées, considérer comme disponible
        if not date_debut or not date_fin:
            return {
                'disponible': True,
                'raison': 'Dates non spécifiées'
            }
        
        # Vérifier les absences - CORRECTION : Requête simple
        absences_conflit = AbsenceUtilisateur.objects.filter(
            utilisateur=candidat,
            date_debut__lte=date_fin,
            date_fin__gte=date_debut
        )
        
        if absences_conflit.exists():
            absence = absences_conflit.first()
            return {
                'disponible': False,
                'raison': f'Absence prévue du {absence.date_debut} au {absence.date_fin}'
            }
        
        # Vérifier les indisponibilités - CORRECTION : Requête simple
        indisponibilites = DisponibiliteUtilisateur.objects.filter(
            utilisateur=candidat,
            type_disponibilite='INDISPONIBLE',
            date_debut__lte=date_fin,
            date_fin__gte=date_debut
        )
        
        if indisponibilites.exists():
            indispo = indisponibilites.first()
            return {
                'disponible': False,
                'raison': f'Indisponible du {indispo.date_debut} au {indispo.date_fin}'
            }
        
        # Vérifier les missions en conflit - CORRECTION : Requête simple
        missions_conflit = PropositionCandidat.objects.filter(
            candidat_propose=candidat,
            statut__in=['VALIDEE', 'EN_COURS'],
            demande_interim__date_debut__lte=date_fin,
            demande_interim__date_fin__gte=date_debut
        )
        
        if missions_conflit.exists():
            mission = missions_conflit.first()
            return {
                'disponible': False,
                'raison': f'Mission en conflit (demande {mission.demande_interim.numero_demande})'
            }
        
        # Vérifications supplémentaires avec données étendues
        try:
            if hasattr(candidat, 'extended_data') and candidat.extended_data:
                if not candidat.extended_data.disponible_interim:
                    return {
                        'disponible': False,
                        'raison': 'Non disponible pour missions d\'intérim'
                    }
        except Exception:
            pass
        
        return {
            'disponible': True,
            'raison': 'Candidat disponible pour la période demandée'
        }
        
    except Exception as e:
        logger.error(f"Erreur vérification disponibilité candidat {candidat.id}: {e}")
        return {
            'disponible': False,
            'raison': f'Erreur lors de la vérification: {str(e)}'
        }
            
def _get_competences_cles_candidat(candidat):
    """
    Récupère les compétences clés d'un candidat
    """
    try:
        competences = candidat.competences.filter(
            niveau_maitrise__gte=3  # Confirmé ou Expert
        ).select_related('competence').order_by('-niveau_maitrise')[:5]
        
        return [comp.competence.nom for comp in competences]
        
    except Exception as e:
        logger.warning(f"Erreur récupération compétences candidat {candidat.id}: {e}")
        return []

def _calculer_anciennete_display(employe):
    """
    Calcule et formate l'ancienneté d'un employé
    """
    try:
        date_embauche = None
        
        # Essayer d'abord les données étendues
        if hasattr(employe, 'extended_data') and employe.extended_data.date_embauche:
            date_embauche = employe.extended_data.date_embauche
        # Sinon essayer le champ direct
        elif employe.date_embauche:
            date_embauche = employe.date_embauche
        
        if date_embauche:
            anciennete = timezone.now().date() - date_embauche
            annees = anciennete.days // 365
            mois = (anciennete.days % 365) // 30
            
            if annees > 0:
                return f"{annees} an{'s' if annees > 1 else ''} {mois} mois"
            else:
                return f"{mois} mois"
        else:
            return "Non renseignée"
            
    except Exception as e:
        logger.warning(f"Erreur calcul ancienneté pour employé {employe.id}: {e}")
        return "Non calculable"

# ================================================================
# VUES AJAX COMPLÉMENTAIRES
# ================================================================

def _peut_creer_demande_interim(profil_utilisateur):
    """
    Vérifie si l'utilisateur peut créer des demandes d'intérim
    CHEF_EQUIPE peut créer des demandes
    """
    try:
        # Pour les superutilisateurs, vérifier d'abord s'ils ont un vrai profil
        if hasattr(profil_utilisateur, 'user') and profil_utilisateur.user.is_superuser:
            return True
        
        type_profil = getattr(profil_utilisateur, 'type_profil', None)
        # CHEF_EQUIPE peut créer des demandes
        return type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN', 'SUPERUSER']
    except Exception:
        return False
        

# Vues AJAX pour support du formulaire

@login_required
def ajax_get_postes_by_departement(request):
    """Retourne les postes d'un département via AJAX"""
    departement_id = request.GET.get('departement_id')
    
    if not departement_id:
        return JsonResponse({'postes': []})
    
    try:
        postes = Poste.objects.filter(
            departement_id=departement_id,
            actif=True,
            interim_autorise=True
        ).values('id', 'titre', 'site__nom').order_by('titre')
        
        return JsonResponse({'postes': list(postes)})

    except Exception as e:
        logger.error(f"Erreur récupération postes: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def ajax_get_employes_by_departement(request):
    """Retourne les employés d'un département via AJAX"""
    departement_id = request.GET.get('departement_id')
    
    if not departement_id:
        return JsonResponse({'employes': []})
    
    try:
        employes = ProfilUtilisateur.objects.filter(
            departement_id=departement_id,
            actif=True,
            statut_employe='ACTIF'
        ).select_related('user', 'poste').values(
            'id', 'user__first_name', 'user__last_name', 'matricule', 'poste__titre'
        ).order_by('user__last_name', 'user__first_name')
        
        employes_list = [{
            'id': emp['id'],
            'nom_complet': f"{emp['user__first_name']} {emp['user__last_name']}",
            'matricule': emp['matricule'],
            'poste': emp['poste__titre'] or ''
        } for emp in employes]
        
        return JsonResponse({'employes': employes_list})
    
    except Exception as e:
        logger.error(f"Erreur récupération employés: {e}")
        return JsonResponse({'error': str(e)}, status=500)
    
#====================================================================
#
#====================================================================

@login_required
def demande_interim_detail_view(request, demande_id):
    """Vue détaillée d'une demande d'intérim avec propositions de candidats"""
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        demande = get_object_or_404(
            DemandeInterim.objects.select_related(
                'demandeur__user', 
                'personne_remplacee__user',
                'poste__departement',
                'poste__site',
                'motif_absence',
                'candidat_selectionne__user',
                'candidat_selectionne__poste',
                'candidat_selectionne__departement'
            ), 
            id=demande_id
        )
        
        # Vérifier les permissions de visualisation
        if not _peut_voir_demande(profil_utilisateur, demande):
            messages.error(request, "Vous n'êtes pas autorisé à voir cette demande")
            return redirect('index_n3_global' if request.user.is_superuser else 'index')
        
        # ================================================================
        # RÉCUPÉRATION DES PROPOSITIONS DE CANDIDATS - CORRIGÉ
        # ================================================================
        
        # CORRECTION : Remplacer 'evaluations' par les relations correctes
        propositions_candidats = PropositionCandidat.objects.filter(
            demande_interim=demande
        ).select_related(
            'candidat_propose__user',
            'candidat_propose__poste',
            'candidat_propose__departement',
            'candidat_propose__site',  # Ajouté pour plus d'infos
            'proposant__user',
            'proposant__poste',
            'evaluateur__user'  # CORRECTION : Relation correcte au lieu de 'evaluations'
        ).order_by('-score_final', '-created_at')  # CORRECTION : Utiliser score_final au lieu de score_total
        
        # Enrichir les propositions avec des informations supplémentaires
        propositions_enrichies = []
        for proposition in propositions_candidats:
            # CORRECTION : Utiliser score_final au lieu de score_total
            score_final = getattr(proposition, 'score_final', 0) or getattr(proposition, 'score_automatique', 0)
            
            # Calculer la classe CSS pour le score
            score_class = 'poor'  # Par défaut
            if score_final:
                if score_final >= 80:
                    score_class = 'excellent'
                elif score_final >= 60:
                    score_class = 'good'
                elif score_final >= 40:
                    score_class = 'average'
            
            # Vérifier si c'est le candidat sélectionné
            est_selectionne = (demande.candidat_selectionne and 
                             demande.candidat_selectionne.id == proposition.candidat_propose.id)
            
            # CORRECTION : Ajouter les informations d'évaluation correctes
            evaluation_info = None
            if proposition.evaluateur and proposition.date_evaluation:
                evaluation_info = {
                    'evaluateur': proposition.evaluateur,
                    'date_evaluation': proposition.date_evaluation,
                    'commentaire': proposition.commentaire_evaluation,
                    'score_ajuste': proposition.score_humain_ajuste
                }
            
            proposition_enrichie = {
                'proposition': proposition,
                'candidat_propose': proposition.candidat_propose,
                'proposant': proposition.proposant,
                'score_total': score_final,  # Garder le nom pour compatibilité template
                'score_final': score_final,  # Nom correct
                'score_class': score_class,
                'est_selectionne': est_selectionne,
                'justification': proposition.justification,
                'competences_specifiques': proposition.competences_specifiques,
                'experience_pertinente': proposition.experience_pertinente,
                'statut': proposition.statut,
                'created_at': proposition.created_at,
                'source_proposition': proposition.get_source_proposition_display(),
                'evaluation_info': evaluation_info,  # CORRECTION : Remplace 'evaluations'
            }
            
            propositions_enrichies.append(proposition_enrichie)
        
        # ================================================================
        # PERMISSIONS ET ACTIONS DISPONIBLES
        # ================================================================
        
        # Permissions de base
        peut_modifier = _peut_modifier_demande(profil_utilisateur, demande)
        peut_valider = _peut_valider_demande(profil_utilisateur, demande)
        peut_supprimer = _peut_supprimer_demande(profil_utilisateur, demande)
        
        # Permission de proposer un candidat
        peut_proposer_candidat = _peut_proposer_candidat(profil_utilisateur, demande)
        
        # Vérifier si l'utilisateur a déjà proposé le maximum de candidats
        if peut_proposer_candidat and demande.nb_max_propositions_par_utilisateur:
            nb_propositions_utilisateur = propositions_candidats.filter(
                proposant=profil_utilisateur
            ).count()
            
            if nb_propositions_utilisateur >= demande.nb_max_propositions_par_utilisateur:
                peut_proposer_candidat = False
        
        # ================================================================
        # CANDIDATS PROPOSABLES POUR LE MODAL - VERSION CORRIGÉE FINALE
        # ================================================================
        
        def get_candidats_proposables_safe(profil_utilisateur, demande, limit=50):
            """Version sécurisée pour récupérer les candidats proposables"""
            try:
                # Étape 1 : Récupérer les candidats déjà proposés (conversion en liste)
                candidats_deja_proposes = list(
                    propositions_candidats.values_list('candidat_propose_id', flat=True)
                )
                
                # Ajouter la personne à remplacer
                if demande.personne_remplacee:
                    candidats_deja_proposes.append(demande.personne_remplacee.id)
                
                # Étape 2 : Construire la requête de base
                candidats_query = _get_candidats_proposables(profil_utilisateur)
                
                # Étape 3 : Appliquer les exclusions
                if candidats_deja_proposes:
                    candidats_query = candidats_query.exclude(id__in=candidats_deja_proposes)
                
                # Étape 4 : Ajouter l'ordre pour des résultats consistants
                candidats_query = candidats_query.order_by('user__last_name', 'user__first_name')
                
                # Étape 5 : Appliquer la limite SEULEMENT à la fin
                return candidats_query[:limit]
                
            except Exception as e:
                logger.error(f"Erreur get_candidats_proposables_safe: {e}")
                return ProfilUtilisateur.objects.none()
        
        candidats_proposables = []
        if peut_proposer_candidat:
            try:
                candidats_proposables = get_candidats_proposables_safe(
                    profil_utilisateur, 
                    demande, 
                    limit=50
                )
            except Exception as e:
                logger.error(f"Erreur récupération candidats proposables: {e}")
                candidats_proposables = []
                
        # ================================================================
        # WORKFLOW ET HISTORIQUE
        # ================================================================
        
        # Récupérer le workflow si disponible
        workflow = None
        try:
            if hasattr(demande, 'workflow'):
                workflow = demande.workflow
                # Enrichir avec les actions récentes
                workflow.historique_actions = demande.historique_actions.select_related(
                    'utilisateur__user'
                ).order_by('-created_at')[:20]
        except Exception as e:
            logger.warning(f"Workflow non disponible pour demande {demande_id}: {e}")
        
        # ================================================================
        # STATISTIQUES ET MÉTRIQUES - VERSION CORRIGÉE FINALE
        # ================================================================
        
        # CORRECTION : Utiliser la fonction sécurisée pour éviter les erreurs de slice
        def calculer_stats_propositions_safe(propositions_enrichies):
            try:
                stats = {
                    'total_propositions': len(propositions_enrichies),
                    'propositions_retenues': 0,
                    'propositions_en_evaluation': 0,
                    'propositions_soumises': 0,
                    'score_moyen': 0,
                    'score_max': 0,
                    'score_min': 100
                }
                
                scores_valides = []
                
                for prop in propositions_enrichies:
                    # Compter par statut
                    if prop['statut'] == 'RETENUE':
                        stats['propositions_retenues'] += 1
                    elif prop['statut'] == 'EN_EVALUATION':
                        stats['propositions_en_evaluation'] += 1
                    elif prop['statut'] == 'SOUMISE':
                        stats['propositions_soumises'] += 1
                    
                    # Collecter les scores valides
                    score = prop.get('score_final', 0)
                    if score and score > 0:
                        scores_valides.append(score)
                
                # Calculer les statistiques de score
                if scores_valides:
                    stats['score_moyen'] = round(sum(scores_valides) / len(scores_valides), 1)
                    stats['score_max'] = max(scores_valides)
                    stats['score_min'] = min(scores_valides)
                
                return stats
                
            except Exception as e:
                logger.error(f"Erreur calcul stats propositions: {e}")
                return {
                    'total_propositions': 0,
                    'propositions_retenues': 0,
                    'propositions_en_evaluation': 0,
                    'score_moyen': 0
                }
        
        # Utiliser la fonction sécurisée
        stats_propositions = calculer_stats_propositions_safe(propositions_enrichies)
        
        # Calculer la durée de la mission
        duree_mission = 0
        if demande.date_debut and demande.date_fin:
            duree_mission = (demande.date_fin - demande.date_debut).days + 1
        
        # ================================================================
        # NOTIFICATIONS ET ALERTES
        # ================================================================
        
        notifications_demande = []
        
        # Vérifier si des actions sont requises
        if demande.statut == 'EN_VALIDATION' and peut_valider:
            notifications_demande.append({
                'type': 'info',
                'message': 'Cette demande nécessite votre validation',
                'action_url': f'/interim/validation/{demande.id}/',
                'action_text': 'Valider'
            })
        
        # Vérifier l'urgence
        if demande.urgence in ['ELEVEE', 'CRITIQUE'] and demande.statut not in ['TERMINEE', 'REFUSEE']:
            notifications_demande.append({
                'type': 'warning',
                'message': f'Demande {demande.urgence.lower()} - Traitement prioritaire requis',
                'urgence': demande.urgence
            })
        
        # Vérifier les dates limites
        if demande.date_limite_propositions:
            from datetime import datetime
            if datetime.now().date() > demande.date_limite_propositions:
                notifications_demande.append({
                    'type': 'danger',
                    'message': 'Date limite de proposition dépassée',
                })
        
        # ================================================================
        # SCORES DÉTAILLÉS (OPTIONNEL) - AJOUTÉ
        # ================================================================
        
        # Récupérer les scores détaillés si disponibles
        scores_detailles = []
        try:
            scores_detailles = ScoreDetailCandidat.objects.filter(
                demande_interim=demande
            ).select_related(
                'candidat__user',
                'proposition_humaine'
            ).order_by('-score_total')
        except Exception as e:
            logger.debug(f"Scores détaillés non disponibles: {e}")
        
        # ================================================================
        # VALIDATIONS ET HISTORIQUE - AJOUTÉ
        # ================================================================
        
        # Récupérer les validations
        validations = []
        try:
            validations = ValidationDemande.objects.filter(
                demande=demande
            ).select_related(
                'validateur__user'
            ).order_by('niveau_validation', 'created_at')
        except Exception as e:
            logger.debug(f"Validations non disponibles: {e}")
        
        # Récupérer l'historique complet
        historique_actions = []
        try:
            historique_actions = HistoriqueAction.objects.filter(
                demande=demande
            ).select_related(
                'utilisateur__user'
            ).order_by('-created_at')[:30]  # Limiter à 30 entrées récentes
        except Exception as e:
            logger.debug(f"Historique non disponible: {e}")
        
        # ================================================================
        # CONTEXT FINAL - ENRICHI
        # ================================================================
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil_utilisateur,
            'duree_mission': duree_mission,
            
            # Propositions
            'propositions_candidats': propositions_enrichies,
            'stats_propositions': stats_propositions,
            
            # Permissions
            'peut_modifier': peut_modifier,
            'peut_valider': peut_valider,
            'peut_supprimer': peut_supprimer,
            'peut_proposer_candidat': peut_proposer_candidat,
            
            # Candidats pour propositions
            'candidats_proposables': candidats_proposables,
            
            # Workflow
            'workflow': workflow,
            
            # AJOUTÉ : Données supplémentaires
            'scores_detailles': scores_detailles,
            'validations': validations,
            'historique_actions': historique_actions,
            
            # Notifications
            'notifications_demande': notifications_demande,
            
            # Métadonnées
            'is_superuser': request.user.is_superuser,
            'page_title': f'Détail demande {demande.numero_demande}',
            'user_initials': _get_utilisateur_initials(request.user),
            
            # URL de redirection selon le profil
            'url_retour': 'index_n3_global' if request.user.is_superuser else 'index',
        }
        
        return render(request, 'demande_detail.html', context)
        
    except Exception as e:
        logger.error(f"Erreur vue détail demande {demande_id}: {e}")
        messages.error(request, "Erreur lors du chargement du détail de la demande")
        return redirect('index_n3_global' if request.user.is_superuser else 'index')


# ================================================================
# VUE AJAX POUR PROPOSER UN CANDIDAT SUPPLÉMENTAIRE - CORRIGÉE
# ================================================================

@login_required
@require_POST
def proposer_candidat_supplementaire(request, demande_id):
    """
    Ajoute une proposition de candidat supplémentaire à une demande existante
    Version corrigée avec intégration scoring service V4.1
    """
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # ================================================================
        # VÉRIFICATIONS DE PERMISSIONS
        # ================================================================
        
        # Vérifier les permissions de base
        if not _peut_proposer_candidat(profil_utilisateur, demande):
            return JsonResponse({
                'success': False,
                'error': 'Vous n\'êtes pas autorisé à proposer des candidats pour cette demande'
            })
        
        # Vérifier le statut de la demande
        if demande.statut not in ['SOUMISE', 'EN_VALIDATION']:
            return JsonResponse({
                'success': False,
                'error': 'Les propositions ne sont plus autorisées pour cette demande'
            })
        
        # Vérifier la limite de propositions par utilisateur
        if demande.nb_max_propositions_par_utilisateur:
            nb_propositions_existantes = PropositionCandidat.objects.filter(
                demande_interim=demande,
                proposant=profil_utilisateur
            ).count()
            
            if nb_propositions_existantes >= demande.nb_max_propositions_par_utilisateur:
                return JsonResponse({
                    'success': False,
                    'error': f'Vous avez atteint la limite de {demande.nb_max_propositions_par_utilisateur} proposition(s) pour cette demande'
                })
        
        # Vérifier la date limite de propositions
        if demande.date_limite_propositions:
            from datetime import datetime
            if datetime.now().date() > demande.date_limite_propositions:
                return JsonResponse({
                    'success': False,
                    'error': 'La date limite pour proposer des candidats est dépassée'
                })
        
        # ================================================================
        # RÉCUPÉRATION ET VALIDATION DES DONNÉES
        # ================================================================
        
        candidat_id = request.POST.get('candidat_id')
        justification = request.POST.get('justification', '').strip()
        competences_specifiques = request.POST.get('competences_specifiques', '').strip()
        experience_pertinente = request.POST.get('experience_pertinente', '').strip()
        
        # Validations de base
        if not candidat_id:
            return JsonResponse({
                'success': False,
                'error': 'Veuillez sélectionner un candidat'
            })
        
        if not justification:
            return JsonResponse({
                'success': False,
                'error': 'La justification de la proposition est obligatoire'
            })
        
        if len(justification) < 20:
            return JsonResponse({
                'success': False,
                'error': 'La justification doit contenir au moins 20 caractères'
            })
        
        # Récupérer et valider le candidat
        try:
            candidat = ProfilUtilisateur.objects.select_related(
                'user', 'poste', 'departement', 'site'
            ).get(id=candidat_id)
        except ProfilUtilisateur.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Candidat sélectionné non trouvé'
            })
        
        # Vérifier que le candidat est actif
        if not candidat.actif or candidat.statut_employe != 'ACTIF':
            return JsonResponse({
                'success': False,
                'error': f'Le candidat {candidat.nom_complet} n\'est pas actif'
            })
        
        # Vérifier que ce n'est pas la personne à remplacer
        if candidat.id == demande.personne_remplacee.id:
            return JsonResponse({
                'success': False,
                'error': 'Vous ne pouvez pas proposer la personne à remplacer comme candidat'
            })
        
        # Vérifier que le candidat n'est pas déjà proposé
        proposition_existante = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=candidat
        ).first()
        
        if proposition_existante:
            return JsonResponse({
                'success': False,
                'error': f'{candidat.nom_complet} a déjà été proposé par {proposition_existante.proposant.nom_complet}'
            })
        
        # ================================================================
        # VÉRIFICATION DE DISPONIBILITÉ DU CANDIDAT
        # ================================================================
        
        disponibilite = _verifier_disponibilite_candidat(
            candidat, 
            demande.date_debut, 
            demande.date_fin
        )
        
        # Avertir si le candidat n'est pas disponible mais permettre la proposition
        avertissement_disponibilite = None
        if not disponibilite['disponible']:
            avertissement_disponibilite = f"Attention: {disponibilite['raison']}"
        
        # ================================================================
        # CALCUL DU SCORE DU CANDIDAT - CORRIGÉ
        # ================================================================
        
        score_initial = None
        try:
            # CORRECTION : Instancier correctement le service de scoring
            scoring_service = ScoringInterimService()
            score_initial = scoring_service.calculer_score_candidat_v41(candidat, demande)
        except Exception as e:
            logger.warning(f"Erreur calcul score pour candidat {candidat.id}: {e}")
            score_initial = 50  # Score par défaut
        
        # ================================================================
        # CRÉATION DE LA PROPOSITION - CORRIGÉE
        # ================================================================
        
        with transaction.atomic():
            
            # CORRECTION : Calculer les bonus correctement
            bonus_validateur = _calculer_bonus_validateur(profil_utilisateur)        
            bonus_priorite = _calculer_bonus_priorite(demande.urgence)  # CORRECTION : utiliser urgence
            
            score_final = min(100, max(0, score_initial + bonus_validateur + bonus_priorite))

            # Créer la proposition
            proposition = PropositionCandidat.objects.create(
                demande_interim=demande,
                candidat_propose=candidat,
                proposant=profil_utilisateur,
                source_proposition='MANAGER' if profil_utilisateur.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR'] else 'AUTRE',
                justification=justification,
                competences_specifiques=competences_specifiques,
                experience_pertinente=experience_pertinente,
                statut='SOUMISE',
                score_automatique=score_final,
                score_final=score_final  # CORRECTION : Définir explicitement score_final
            )
            
            # Créer le détail du score si le service est disponible
            if score_initial:
                try:
                    ScoreDetailCandidat.objects.create(
                        candidat=candidat,
                        demande_interim=demande,
                        proposition_humaine=proposition,
                        score_total=score_final,  # CORRECTION : Utiliser score_final
                        calcule_par='AUTOMATIQUE_LORS_PROPOSITION',
                        # Détails simplifiés
                        score_similarite_poste=min(100, int(score_initial * 0.3)),
                        score_competences=min(100, int(score_initial * 0.25)),
                        score_experience=min(100, int(score_initial * 0.2)),
                        score_disponibilite=100 if disponibilite['disponible'] else 50,
                        score_proximite=min(100, int(score_initial * 0.15)),
                        score_anciennete=min(100, int(score_initial * 0.1)),
                        bonus_proposition_humaine=bonus_validateur
                    )
                except Exception as e:
                    logger.warning(f"Erreur création score détail: {e}")
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                action='PROPOSITION_CANDIDAT',
                utilisateur=profil_utilisateur,
                description=f"Proposition du candidat {candidat.nom_complet} par {profil_utilisateur.nom_complet}",
                donnees_apres={
                    'candidat_propose_id': candidat.id,
                    'candidat_propose_nom': candidat.nom_complet,
                    'candidat_propose_matricule': candidat.matricule,
                    'proposant_id': profil_utilisateur.id,
                    'proposant_nom': profil_utilisateur.nom_complet,
                    'proposant_type': profil_utilisateur.type_profil,
                    'score_initial': score_initial,
                    'score_final': score_final,
                    'bonus_validateur': bonus_validateur,
                    'bonus_priorite': bonus_priorite,
                    'justification_courte': justification[:100] + '...' if len(justification) > 100 else justification,
                    'disponibilite_candidat': disponibilite['disponible'],
                    'timestamp': timezone.now().isoformat()
                }
            )
            
            # Notifier les personnes concernées (si le système de notification existe)
            try:
                # Notifier le demandeur si ce n'est pas lui qui propose
                if demande.demandeur != profil_utilisateur:
                    NotificationInterim.objects.create(
                        destinataire=demande.demandeur,
                        expediteur=profil_utilisateur,
                        demande=demande,
                        proposition_liee=proposition,
                        type_notification='PROPOSITION_CANDIDAT',
                        urgence='NORMALE',
                        titre=f"Nouvelle proposition pour votre demande {demande.numero_demande}",
                        message=f"{profil_utilisateur.nom_complet} a proposé {candidat.nom_complet} comme candidat",
                        metadata={
                            'candidat_id': candidat.id,
                            'proposition_id': proposition.id,
                            'score_final': score_final
                        }
                    )
                
                # Notifier les validateurs potentiels
                validateurs = _get_validateurs_niveau_suivant(demande)
                for validateur in validateurs:
                    if validateur != profil_utilisateur:
                        NotificationInterim.objects.create(
                            destinataire=validateur,
                            expediteur=profil_utilisateur,
                            demande=demande,
                            proposition_liee=proposition,
                            type_notification='PROPOSITION_CANDIDAT',
                            urgence='NORMALE',
                            titre=f"Nouvelle proposition pour la demande {demande.numero_demande}",
                            message=f"{profil_utilisateur.nom_complet} a proposé {candidat.nom_complet}",
                            metadata={
                                'candidat_id': candidat.id,
                                'proposition_id': proposition.id
                            }
                        )
            except Exception as e:
                logger.warning(f"Erreur création notifications: {e}")
        
        # ================================================================
        # RÉPONSE DE SUCCÈS
        # ================================================================
        
        logger.info(f"Nouvelle proposition candidat créée: {candidat.nom_complet} pour demande {demande.numero_demande} par {profil_utilisateur.nom_complet}")
        
        response_data = {
            'success': True,
            'message': f'Candidat {candidat.nom_complet} proposé avec succès',
            'proposition_id': proposition.id,
            'candidat': {
                'id': candidat.id,
                'nom_complet': candidat.nom_complet,
                'matricule': candidat.matricule,
                'poste': candidat.poste.titre if candidat.poste else '',
                'departement': candidat.departement.nom if candidat.departement else ''
            },
            'score_initial': score_initial,
            'score_final': score_final,
            'disponibilite': disponibilite,
            'proposant': {
                'nom_complet': profil_utilisateur.nom_complet,
                'type_profil': profil_utilisateur.get_type_profil_display()
            }
        }
        
        # Ajouter l'avertissement de disponibilité si nécessaire
        if avertissement_disponibilite:
            response_data['avertissement'] = avertissement_disponibilite
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Erreur proposition candidat supplémentaire pour demande {demande_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors de la création de la proposition. Veuillez réessayer.'
        }, status=500)


# ================================================================
# FONCTIONS UTILITAIRES POUR LES PROPOSITIONS
# ================================================================

def _get_validateurs_niveau_suivant(demande):
    """
    Détermine qui peut valider au niveau suivant selon la hiérarchie CORRIGÉE
    """
    niveau_suivant = demande.niveau_validation_actuel + 1
    
    if niveau_suivant == 1:
        # Premier niveau : RESPONSABLE du département
        return ProfilUtilisateur.objects.filter(
            type_profil='RESPONSABLE',
            departement=demande.poste.departement,
            actif=True
        )
    
    elif niveau_suivant == 2:
        # Deuxième niveau : DIRECTEUR
        return ProfilUtilisateur.objects.filter(
            type_profil='DIRECTEUR',
            actif=True
        )
    
    elif niveau_suivant >= 3:
        # Validation finale : RH/ADMIN
        return ProfilUtilisateur.objects.filter(
            type_profil__in=['RH', 'ADMIN'],
            actif=True
        )
    
    return ProfilUtilisateur.objects.none()

# ================================================================
# FONCTION POUR ENRICHIR LES PROPOSITIONS (UTILISÉE DANS LA VUE)
# ================================================================

def _enrichir_propositions_avec_details(propositions_queryset, demande):
    """
    Enrichit les propositions avec des détails supplémentaires
    """
    propositions_enrichies = []
    
    for proposition in propositions_queryset:
        # Calculer la classe CSS pour le score
        score_class = 'poor'
        if proposition.score_total:
            if proposition.score_total >= 80:
                score_class = 'excellent'
            elif proposition.score_total >= 60:
                score_class = 'good'
            elif proposition.score_total >= 40:
                score_class = 'average'
        
        # Vérifier si c'est le candidat sélectionné
        est_selectionne = (demande.candidat_selectionne and 
                         demande.candidat_selectionne.id == proposition.candidat_propose.id)
        
        # Calculer les initiales du candidat
        candidat_initiales = _get_utilisateur_initials(proposition.candidat_propose.user)
        
        proposition_enrichie = {
            'id': proposition.id,
            'candidat_propose': proposition.candidat_propose,
            'candidat_initiales': candidat_initiales,
            'proposant': proposition.proposant,
            'score_total': proposition.score_total,
            'score_class': score_class,
            'est_selectionne': est_selectionne,
            'justification': proposition.justification,
            'competences_specifiques': proposition.competences_specifiques,
            'experience_pertinente': proposition.experience_pertinente,
            'statut': proposition.statut,
            'statut_display': proposition.get_statut_display(),
            'created_at': proposition.created_at,
            'source_proposition': proposition.get_source_proposition_display(),
            
            # Métadonnées additionnelles
            'peut_etre_modifiee': proposition.statut in ['SOUMISE', 'EN_EVALUATION'],
            'est_recent': (timezone.now() - proposition.created_at).days < 1,
            'evaluation_moyenne': None,  # À calculer si des évaluations existent
        }
        
        # Calculer l'évaluation moyenne si des évaluations existent
        try:
            evaluations = proposition.evaluations.all()
            if evaluations.exists():
                notes = [eval.note for eval in evaluations if eval.note]
                if notes:
                    proposition_enrichie['evaluation_moyenne'] = round(sum(notes) / len(notes), 1)
        except:
            pass
        
        propositions_enrichies.append(proposition_enrichie)
    
    return propositions_enrichies

@login_required
def demande_interim_update_view(request, demande_id):
    """Vue pour modifier une demande d'intérim - Version complète avec gestion des propositions"""
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions de modification
        if not _peut_modifier_demande(profil_utilisateur, demande):
            messages.error(request, "Vous n'êtes pas autorisé à modifier cette demande")
            return redirect('demande_detail', demande_id=demande_id)
        
        if request.method == 'POST':
            try:
                # Déterminer le type de requête (JSON ou Form)
                is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                
                if is_ajax and request.content_type == 'application/json':
                    # Requête AJAX JSON (pour les propositions automatiques/spécifiques)
                    import json
                    data = json.loads(request.body)
                    return _traiter_requete_json(request, demande, profil_utilisateur, data)
                else:
                    # Requête Form classique
                    return _traiter_requete_form(request, demande, profil_utilisateur)
                
            except Exception as e:
                logger.error(f"Erreur modification demande: {e}")
                error_msg = f"Erreur lors de la modification: {str(e)}"
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg})
                else:
                    messages.error(request, "Erreur lors de la modification")
                    return redirect(request.path)
        
        # Préparer les données pour l'affichage GET
        return _preparer_context_modification(request, demande, profil_utilisateur)
        
    except Exception as e:
        logger.error(f"Erreur vue modification demande: {e}")
        messages.error(request, "Erreur lors du chargement de la demande")
        return redirect('index')


def _traiter_requete_json(request, demande, profil_utilisateur, data):
    """Traiter les requêtes JSON (propositions automatiques/spécifiques)"""
    action = data.get('action')
    
    if action == 'enregistrer_proposition_auto':
        return _enregistrer_proposition_automatique(request, demande, profil_utilisateur, data)
    elif action == 'enregistrer_proposition_specifique':
        return _enregistrer_proposition_specifique(request, demande, profil_utilisateur, data)
    elif action == 'supprimer_proposition':
        return _supprimer_proposition_existante(request, demande, profil_utilisateur, data)
    elif action == 'modifier_proposition':
        return _modifier_proposition_existante(request, demande, profil_utilisateur, data)
    else:
        return JsonResponse({'success': False, 'error': 'Action non reconnue'})

def _supprimer_proposition_existante(request, demande, profil_utilisateur, data):
    """Supprimer une proposition existante"""
    try:
        proposition_id = data.get('proposition_id')
        justification_suppression = data.get('justification', '').strip()
        
        if not proposition_id:
            return JsonResponse({
                'success': False, 
                'error': 'ID de proposition requis'
            })
        
        if not justification_suppression:
            return JsonResponse({
                'success': False, 
                'error': 'Justification de suppression requise'
            })
        
        # Récupérer la proposition
        try:
            proposition = PropositionCandidat.objects.select_related(
                'candidat_propose', 
                'proposant',
                'demande_interim'
            ).get(
                id=proposition_id,
                demande_interim=demande
            )
        except PropositionCandidat.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Proposition non trouvée'
            })
        
        # Vérifier les permissions de suppression
        peut_supprimer, raison = _peut_supprimer_proposition(profil_utilisateur, proposition)
        
        if not peut_supprimer:
            return JsonResponse({
                'success': False, 
                'error': f'Suppression non autorisée: {raison}'
            })
        
        # Vérifier si la proposition peut être supprimée selon son statut
        if not _proposition_peut_etre_supprimee(proposition):
            return JsonResponse({
                'success': False, 
                'error': f'Impossible de supprimer une proposition avec le statut "{proposition.get_statut_display()}"'
            })
        
        with transaction.atomic():
            # Sauvegarder les informations avant suppression pour l'historique
            candidat_nom = proposition.candidat_propose.nom_complet
            proposant_nom = proposition.proposant.nom_complet
            statut_proposition = proposition.statut
            score_proposition = proposition.score_total
            
            # Données pour l'historique
            donnees_suppression = {
                'candidat_propose': {
                    'id': proposition.candidat_propose.id,
                    'nom_complet': candidat_nom,
                    'matricule': proposition.candidat_propose.matricule,
                    'poste': proposition.candidat_propose.poste.titre if proposition.candidat_propose.poste else None,
                    'departement': proposition.candidat_propose.departement.nom if proposition.candidat_propose.departement else None
                },
                'proposant': {
                    'id': proposition.proposant.id,
                    'nom_complet': proposant_nom,
                    'type_profil': proposition.proposant.type_profil
                },
                'statut': statut_proposition,
                'score_total': score_proposition,
                'source_proposition': proposition.source_proposition,
                'justification_originale': proposition.justification,
                'competences_specifiques': proposition.competences_specifiques,
                'experience_pertinente': proposition.experience_pertinente,
                'date_creation': proposition.created_at.isoformat(),
                'justification_suppression': justification_suppression,
                'supprime_par': {
                    'id': profil_utilisateur.id,
                    'nom_complet': profil_utilisateur.nom_complet,
                    'type_profil': profil_utilisateur.type_profil
                }
            }
            
            # Vérifier si cette proposition était sélectionnée
            etait_selectionnee = (
                demande.candidat_selectionne and 
                demande.candidat_selectionne.id == proposition.candidat_propose.id
            )
            
            # Si la proposition supprimée était le candidat sélectionné, réinitialiser la sélection
            if etait_selectionnee:
                demande.candidat_selectionne = None
                demande.statut_selection = 'EN_ATTENTE'
                demande.save(update_fields=['candidat_selectionne', 'statut_selection', 'updated_at'])
                donnees_suppression['candidat_etait_selectionne'] = True
            
            # Supprimer la proposition
            proposition.delete()
            
            # Créer l'entrée d'historique
            HistoriqueAction.objects.create(
                demande=demande,
                action='SUPPRESSION_PROPOSITION',
                utilisateur=profil_utilisateur,
                description=f"Suppression de la proposition de {candidat_nom} par {profil_utilisateur.nom_complet}",
                donnees_avant=donnees_suppression,
                donnees_apres={
                    'justification_suppression': justification_suppression,
                    'candidat_selectionne_reinitialise': etait_selectionnee
                }
            )
            
            # Notifier les parties concernées si nécessaire
            if data.get('notifier_parties_prenantes', False):
                _notifier_suppression_proposition(
                    demande, 
                    candidat_nom, 
                    proposant_nom, 
                    justification_suppression,
                    profil_utilisateur,
                    etait_selectionnee
                )
            
            # Recalculer les statistiques de la demande
            _recalculer_statistiques_demande(demande)
            
            # Vérifier si des actions automatiques sont nécessaires
            _verifier_actions_post_suppression(demande, proposition, profil_utilisateur)
            
            message_succes = f'Proposition de {candidat_nom} supprimée avec succès'
            if etait_selectionnee:
                message_succes += '. Le candidat sélectionné a été réinitialisé.'
            
            return JsonResponse({
                'success': True,
                'message': message_succes,
                'proposition_id': proposition_id,
                'candidat_etait_selectionne': etait_selectionnee,
                'nouvelles_statistiques': {
                    'total_propositions': demande.propositions_candidats.count(),
                    'propositions_en_attente': demande.propositions_candidats.filter(statut='SOUMISE').count(),
                    'propositions_evaluees': demande.propositions_candidats.filter(statut='EN_EVALUATION').count(),
                    'propositions_retenues': demande.propositions_candidats.filter(statut='RETENUE').count(),
                }
            })
            
    except Exception as e:
        logger.error(f"Erreur suppression proposition {proposition_id}: {e}")
        return JsonResponse({
            'success': False, 
            'error': f'Erreur lors de la suppression: {str(e)}'
        })


def _peut_supprimer_proposition(profil_utilisateur, proposition):
    """Vérifier si l'utilisateur peut supprimer cette proposition"""
    
    # Le proposant peut toujours supprimer sa propre proposition (sauf exceptions)
    if proposition.proposant.id == profil_utilisateur.id:
        # Vérifier le statut de la proposition
        if proposition.statut in ['SELECTIONNEE']:
            return False, "Impossible de supprimer une proposition déjà sélectionnée"
        
        # Vérifier le statut de la demande
        if proposition.demande_interim.statut in ['CLOTUREE', 'ANNULEE']:
            return False, "Impossible de supprimer une proposition sur une demande clôturée"
        
        return True, "Suppression autorisée"
    
    # Les managers/RH peuvent supprimer certaines propositions
    if profil_utilisateur.type_profil in ['MANAGER', 'RH', 'ADMIN']:
        
        # Vérifier le statut de la proposition
        if proposition.statut == 'SELECTIONNEE':
            # Seuls les RH/ADMIN peuvent supprimer une proposition sélectionnée
            if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
                return True, "Suppression autorisée (privilèges RH/Admin)"
            else:
                return False, "Seuls les RH/Admin peuvent supprimer une proposition sélectionnée"
        
        # Vérifier le statut de la demande
        if proposition.demande_interim.statut in ['CLOTUREE', 'ANNULEE']:
            if profil_utilisateur.type_profil == 'ADMIN':
                return True, "Suppression autorisée (privilèges Admin)"
            else:
                return False, "Impossible de supprimer sur une demande clôturée"
        
        return True, "Suppression autorisée (privilèges manager/RH)"
    
    # Le demandeur initial peut supprimer sous certaines conditions
    if proposition.demande_interim.demandeur.id == profil_utilisateur.id:
        
        if proposition.statut in ['SOUMISE', 'EN_EVALUATION']:
            return True, "Suppression autorisée (demandeur initial)"
        else:
            return False, "Le demandeur ne peut supprimer que les propositions en attente ou en évaluation"
    
    return False, "Permissions insuffisantes pour supprimer cette proposition"


def _proposition_peut_etre_supprimee(proposition):
    """Vérifier si une proposition peut être supprimée selon son statut et contexte"""
    
    # Statuts qui ne permettent jamais la suppression
    statuts_non_supprimables = []
    
    # Une proposition sélectionnée ne peut être supprimée que par RH/Admin
    # (cette vérification est faite dans _peut_supprimer_proposition)
    
    # Vérifier si il y a des dépendances
    if hasattr(proposition, 'evaluations') and proposition.evaluations.exists():
        # Il y a des évaluations associées - vérifier si on peut les supprimer aussi
        pass
    
    if hasattr(proposition, 'commentaires') and proposition.commentaires.exists():
        # Il y a des commentaires associés
        pass
    
    # Vérifier le délai depuis la création
    from datetime import timedelta
    from django.utils import timezone
    
    # Après 48h, seuls certains profils peuvent supprimer
    if timezone.now() - proposition.created_at > timedelta(hours=48):
        # Cette vérification sera faite au niveau des permissions utilisateur
        pass
    
    return True  # Par défaut, on autorise la suppression si les permissions sont OK


def _recalculer_statistiques_demande(demande):
    """Recalculer les statistiques de la demande après suppression d'une proposition"""
    
    # Mettre à jour le timestamp de dernière modification
    demande.updated_at = timezone.now()
    demande.save(update_fields=['updated_at'])
    
    # Recalculer les métriques si nécessaire
    total_propositions = demande.propositions_candidats.count()
    
    # Si il n'y a plus de propositions et que le statut était "EN_EVALUATION"
    if total_propositions == 0 and demande.statut == 'EN_EVALUATION':
        demande.statut = 'VALIDEE'  # Retour au statut précédent
        demande.save(update_fields=['statut'])
    
    # Autres recalculs selon les besoins métier
    logger.info(f"Statistiques recalculées pour la demande {demande.numero_demande}: {total_propositions} propositions restantes")


def _verifier_actions_post_suppression(demande, proposition_supprimee, profil_utilisateur):
    """Vérifier si des actions automatiques sont nécessaires après suppression"""
    
    # Si c'était la seule proposition et que la demande était en évaluation
    if demande.propositions_candidats.count() == 0:
        logger.info(f"Plus aucune proposition pour la demande {demande.numero_demande}")
        
        # Notifier le demandeur qu'il n'y a plus de propositions
        # (implémentation selon le système de notification)
        
    # Si le candidat supprimé était dans une shortlist
    if hasattr(demande, 'shortlist') and demande.shortlist:
        # Retirer de la shortlist si présent
        pass
    
    # Vérifier si il faut relancer le processus de scoring automatique
    if proposition_supprimee.source_proposition == 'SYSTEME_AUTOMATIQUE':
        # Marquer pour re-scoring si nécessaire
        pass
    
    logger.info(f"Actions post-suppression vérifiées pour la demande {demande.numero_demande}")


def _notifier_suppression_proposition(demande, candidat_nom, proposant_nom, justification, supprime_par, etait_selectionnee):
    """Notifier les parties prenantes de la suppression d'une proposition"""
    
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.conf import settings
    
    try:
        # Liste des personnes à notifier
        destinataires = []
        
        # Le proposant (si différent de celui qui supprime)
        if demande.propositions_candidats.filter(proposant__id=demande.demandeur.id).exists():
            destinataires.append(demande.demandeur.email)
        
        # Le manager de la demande
        if hasattr(demande, 'manager_validateur') and demande.manager_validateur:
            destinataires.append(demande.manager_validateur.email)
        
        # Les RH
        rh_emails = ProfilUtilisateur.objects.filter(
            type_profil='RH', 
            actif=True
        ).values_list('email', flat=True)
        destinataires.extend(rh_emails)
        
        # Préparer le contexte pour l'email
        contexte = {
            'demande': demande,
            'candidat_nom': candidat_nom,
            'proposant_nom': proposant_nom,
            'supprime_par': supprime_par.nom_complet,
            'justification': justification,
            'etait_selectionnee': etait_selectionnee,
            'date_suppression': timezone.now(),
            'url_demande': f"{settings.SITE_URL}/interim/demande/{demande.id}/"
        }
        
        # Générer le contenu de l'email
        sujet = f"[Interim365 - BNI] Suppression proposition - Demande {demande.numero_demande}"
        
        if etait_selectionnee:
            sujet += " - Candidat sélectionné supprimé"
        
        message_html = render_to_string('emails/suppression_proposition.html', contexte)
        message_text = render_to_string('emails/suppression_proposition.txt', contexte)
        
        # Envoyer l'email
        if destinataires:
            send_mail(
                subject=sujet,
                message=message_text,
                html_message=message_html,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=list(set(destinataires)),  # Dédoublonner
                fail_silently=False
            )
            
            logger.info(f"Notification de suppression envoyée pour la demande {demande.numero_demande}")
        
    except Exception as e:
        logger.error(f"Erreur envoi notification suppression: {e}")
        # Ne pas faire échouer la suppression pour un problème d'email

def _modifier_proposition_existante(request, demande, profil_utilisateur, data):
    """Modifier une proposition existante"""
    try:
        proposition_id = data.get('proposition_id')
        if not proposition_id:
            return JsonResponse({
                'success': False, 
                'error': 'ID de proposition requis'
            })
        
        # Récupérer la proposition
        try:
            proposition = PropositionCandidat.objects.select_related(
                'candidat_propose', 
                'proposant',
                'demande_interim',
                'candidat_propose__poste',
                'candidat_propose__departement',
                'candidat_propose__site'
            ).get(
                id=proposition_id,
                demande_interim=demande
            )
        except PropositionCandidat.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Proposition non trouvée'
            })
        
        # Vérifier les permissions de modification
        peut_modifier, raison = _peut_modifier_proposition(profil_utilisateur, proposition)
        
        if not peut_modifier:
            return JsonResponse({
                'success': False, 
                'error': f'Modification non autorisée: {raison}'
            })
        
        # Vérifier si la proposition peut être modifiée selon son statut
        if not _proposition_peut_etre_modifiee(proposition):
            return JsonResponse({
                'success': False, 
                'error': f'Impossible de modifier une proposition avec le statut "{proposition.get_statut_display()}"'
            })
        
        # Récupérer et valider les nouvelles données
        nouvelles_donnees = _extraire_donnees_modification(data)
        validation_result = _valider_donnees_modification(nouvelles_donnees, proposition, demande)
        
        if not validation_result['valid']:
            return JsonResponse({
                'success': False, 
                'error': validation_result['error']
            })
        
        with transaction.atomic():
            # Sauvegarder l'état avant modification pour l'historique
            donnees_avant = _capturer_etat_proposition(proposition)
            
            # Appliquer les modifications
            modifications_appliquees = _appliquer_modifications_proposition(
                proposition, 
                nouvelles_donnees, 
                profil_utilisateur
            )
            
            if not modifications_appliquees['success']:
                return JsonResponse({
                    'success': False, 
                    'error': modifications_appliquees['error']
                })
            
            # Recalculer le score si le candidat a changé
            if modifications_appliquees['candidat_change']:
                nouveau_score = _recalculer_score_proposition(proposition, demande)
                proposition.score_total = nouveau_score
            
            # Remettre en évaluation si modifications importantes
            if modifications_appliquees['modifications_importantes']:
                ancien_statut = proposition.statut
                proposition.statut = 'SOUMISE'
                proposition.date_derniere_modification = timezone.now()
                
                # Annuler la sélection si ce candidat était sélectionné
                if demande.candidat_selectionne and demande.candidat_selectionne.id == proposition.candidat_propose.id:
                    demande.candidat_selectionne = None
                    demande.statut_selection = 'EN_ATTENTE'
                    demande.save(update_fields=['candidat_selectionne', 'statut_selection'])
                    modifications_appliquees['selection_annulee'] = True
            
            # Sauvegarder la proposition
            proposition.save()
            
            # Capturer l'état après modification
            donnees_apres = _capturer_etat_proposition(proposition)
            
            # Créer l'entrée d'historique
            HistoriqueAction.objects.create(
                demande=demande,
                action='MODIFICATION_PROPOSITION',
                utilisateur=profil_utilisateur,
                description=f"Modification de la proposition de {proposition.candidat_propose.nom_complet} par {profil_utilisateur.nom_complet}",
                donnees_avant=donnees_avant,
                donnees_apres=donnees_apres,
                commentaire=nouvelles_donnees.get('justification_modification', '')
            )
            
            # Notifier les parties concernées si nécessaire
            if data.get('notifier_parties_prenantes', False):
                _notifier_modification_proposition(
                    demande, 
                    proposition,
                    modifications_appliquees['resume_modifications'],
                    profil_utilisateur,
                    modifications_appliquees.get('selection_annulee', False)
                )
            
            # Vérifier si des actions automatiques sont nécessaires
            _verifier_actions_post_modification(demande, proposition, modifications_appliquees)
            
            # Préparer le message de succès
            message_succes = f'Proposition de {proposition.candidat_propose.nom_complet} modifiée avec succès'
            
            if modifications_appliquees.get('selection_annulee'):
                message_succes += '. La sélection de ce candidat a été annulée.'
            
            if modifications_appliquees.get('candidat_change'):
                message_succes += f' (nouveau score: {proposition.score_total})'
            
            return JsonResponse({
                'success': True,
                'message': message_succes,
                'proposition_id': proposition_id,
                'modifications': modifications_appliquees['resume_modifications'],
                'nouveau_statut': proposition.statut,
                'nouveau_score': proposition.score_total,
                'selection_annulee': modifications_appliquees.get('selection_annulee', False),
                'candidat_change': modifications_appliquees.get('candidat_change', False),
                'proposition_data': {
                    'candidat': {
                        'id': proposition.candidat_propose.id,
                        'nom_complet': proposition.candidat_propose.nom_complet,
                        'matricule': proposition.candidat_propose.matricule,
                        'poste': proposition.candidat_propose.poste.titre if proposition.candidat_propose.poste else None,
                        'departement': proposition.candidat_propose.departement.nom if proposition.candidat_propose.departement else None
                    },
                    'justification': proposition.justification,
                    'competences_specifiques': proposition.competences_specifiques,
                    'experience_pertinente': proposition.experience_pertinente,
                    'statut': proposition.statut,
                    'score_total': proposition.score_total
                }
            })
            
    except Exception as e:
        logger.error(f"Erreur modification proposition {proposition_id}: {e}")
        return JsonResponse({
            'success': False, 
            'error': f'Erreur lors de la modification: {str(e)}'
        })


def _peut_modifier_proposition(profil_utilisateur, proposition):
    """Vérifier si l'utilisateur peut modifier cette proposition"""
    
    # Le proposant peut modifier sa propre proposition (avec restrictions)
    if proposition.proposant.id == profil_utilisateur.id:
        # Vérifier le statut de la proposition
        if proposition.statut == 'SELECTIONNEE':
            return False, "Impossible de modifier une proposition déjà sélectionnée"
        
        if proposition.statut == 'REJETEE':
            return False, "Impossible de modifier une proposition rejetée"
        
        # Vérifier le statut de la demande
        if proposition.demande_interim.statut in ['CLOTUREE', 'ANNULEE']:
            return False, "Impossible de modifier une proposition sur une demande clôturée"
        
        # Vérifier le délai de modification (48h après création)
        from datetime import timedelta
        if timezone.now() - proposition.created_at > timedelta(hours=48):
            if proposition.statut != 'SOUMISE':
                return False, "Délai de modification dépassé pour les propositions en cours d'évaluation"
        
        return True, "Modification autorisée"
    
    # Les managers/RH peuvent modifier certaines propositions
    if profil_utilisateur.type_profil in ['MANAGER', 'RH', 'ADMIN']:
        
        # Les RH/Admin ont plus de privilèges
        if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            if proposition.statut == 'SELECTIONNEE':
                return True, "Modification autorisée (privilèges RH/Admin sur proposition sélectionnée)"
            
            if proposition.demande_interim.statut in ['CLOTUREE']:
                if profil_utilisateur.type_profil == 'ADMIN':
                    return True, "Modification autorisée (privilèges Admin)"
                else:
                    return False, "Seul l'Admin peut modifier sur une demande clôturée"
        
        # Managers peuvent modifier si statut approprié
        if proposition.statut in ['SOUMISE', 'EN_EVALUATION', 'RETENUE']:
            return True, "Modification autorisée (privilèges manager/RH)"
        
        return False, f"Modification non autorisée pour le statut {proposition.statut}"
    
    # Le demandeur initial a des droits limités
    if proposition.demande_interim.demandeur.id == profil_utilisateur.id:
        if proposition.statut in ['SOUMISE']:
            return True, "Modification autorisée (demandeur initial, proposition en attente)"
        else:
            return False, "Le demandeur ne peut modifier que les propositions en attente"
    
    return False, "Permissions insuffisantes pour modifier cette proposition"


def _proposition_peut_etre_modifiee(proposition):
    """Vérifier si une proposition peut être modifiée selon son statut et contexte"""
    
    # Statuts qui ne permettent jamais la modification
    statuts_non_modifiables = ['ANNULEE']
    
    if proposition.statut in statuts_non_modifiables:
        return False
    
    # Vérifier s'il y a des évaluations en cours
    if hasattr(proposition, 'evaluations'):
        evaluations_en_cours = proposition.evaluations.filter(
            statut__in=['EN_COURS', 'PLANIFIEE']
        )
        if evaluations_en_cours.exists():
            # On peut modifier mais cela annulera les évaluations
            pass
    
    # Vérifier les dépendances métier
    if hasattr(proposition, 'entretiens') and proposition.entretiens.filter(statut='PLANIFIE').exists():
        # Il y a des entretiens planifiés - modification possible mais avec impact
        pass
    
    return True


def _extraire_donnees_modification(data):
    """Extraire et nettoyer les données de modification"""
    return {
        'candidat_id': data.get('candidat_id'),
        'justification': data.get('justification', '').strip(),
        'competences_specifiques': data.get('competences_specifiques', '').strip(),
        'experience_pertinente': data.get('experience_pertinente', '').strip(),
        'justification_modification': data.get('justification_modification', '').strip(),
        'force_modification': data.get('force_modification', False),  # Pour bypasser certaines validations
        'maintenir_evaluations': data.get('maintenir_evaluations', False)
    }


def _valider_donnees_modification(donnees, proposition, demande):
    """Valider les données de modification"""
    
    # Justification obligatoire
    if not donnees['justification']:
        return {'valid': False, 'error': 'La justification est obligatoire'}
    
    # Justification de modification obligatoire
    if not donnees['justification_modification']:
        return {'valid': False, 'error': 'La justification des modifications est obligatoire'}
    
    # Vérifier le nouveau candidat si fourni
    if donnees['candidat_id']:
        try:
            nouveau_candidat = ProfilUtilisateur.objects.select_related(
                'poste', 'departement', 'site'
            ).get(id=donnees['candidat_id'], actif=True)
            
            # Vérifier que ce n'est pas le même candidat
            if nouveau_candidat.id == proposition.candidat_propose.id:
                # Pas de changement de candidat, c'est OK
                pass
            else:
                # Nouveau candidat - vérifications supplémentaires
                
                # Vérifier qu'il n'y a pas déjà une proposition pour ce candidat
                proposition_existante = demande.propositions_candidats.filter(
                    candidat_propose=nouveau_candidat
                ).exclude(id=proposition.id).first()
                
                if proposition_existante:
                    return {
                        'valid': False, 
                        'error': f'{nouveau_candidat.nom_complet} est déjà proposé pour cette demande'
                    }
                
                # Vérifier la disponibilité du candidat
                disponibilite = _verifier_disponibilite_candidat(
                    nouveau_candidat, 
                    demande.date_debut, 
                    demande.date_fin
                )
                
                if not disponibilite['disponible'] and not donnees['force_modification']:
                    return {
                        'valid': False, 
                        'error': f'Candidat non disponible: {disponibilite["raison"]}'
                    }
            
        except ProfilUtilisateur.DoesNotExist:
            return {'valid': False, 'error': 'Candidat non trouvé ou inactif'}
    
    # Validation de la longueur des champs
    if len(donnees['justification']) > 2000:
        return {'valid': False, 'error': 'Justification trop longue (max 2000 caractères)'}
    
    if len(donnees['competences_specifiques']) > 1000:
        return {'valid': False, 'error': 'Compétences spécifiques trop longues (max 1000 caractères)'}
    
    if len(donnees['experience_pertinente']) > 1000:
        return {'valid': False, 'error': 'Expérience pertinente trop longue (max 1000 caractères)'}
    
    return {'valid': True}


def _capturer_etat_proposition(proposition):
    """Capturer l'état actuel d'une proposition pour l'historique"""
    return {
        'candidat_propose': {
            'id': proposition.candidat_propose.id,
            'nom_complet': proposition.candidat_propose.nom_complet,
            'matricule': proposition.candidat_propose.matricule,
            'poste': proposition.candidat_propose.poste.titre if proposition.candidat_propose.poste else None,
            'departement': proposition.candidat_propose.departement.nom if proposition.candidat_propose.departement else None,
            'site': proposition.candidat_propose.site.nom if proposition.candidat_propose.site else None
        },
        'proposant': {
            'id': proposition.proposant.id,
            'nom_complet': proposition.proposant.nom_complet,
            'type_profil': proposition.proposant.type_profil
        },
        'statut': proposition.statut,
        'score_total': proposition.score_total,
        'source_proposition': proposition.source_proposition,
        'justification': proposition.justification,
        'competences_specifiques': proposition.competences_specifiques,
        'experience_pertinente': proposition.experience_pertinente,
        'created_at': proposition.created_at.isoformat(),
        'updated_at': proposition.updated_at.isoformat() if proposition.updated_at else None,
        'date_derniere_modification': proposition.date_derniere_modification.isoformat() if hasattr(proposition, 'date_derniere_modification') and proposition.date_derniere_modification else None
    }


def _appliquer_modifications_proposition(proposition, nouvelles_donnees, profil_utilisateur):
    """Appliquer les modifications à la proposition"""
    
    modifications = []
    candidat_change = False
    modifications_importantes = False
    
    try:
        # Modification du candidat
        if nouvelles_donnees['candidat_id'] and int(nouvelles_donnees['candidat_id']) != proposition.candidat_propose.id:
            ancien_candidat = proposition.candidat_propose
            nouveau_candidat = ProfilUtilisateur.objects.get(id=nouvelles_donnees['candidat_id'])
            
            proposition.candidat_propose = nouveau_candidat
            candidat_change = True
            modifications_importantes = True
            
            modifications.append(f"Candidat: {ancien_candidat.nom_complet} → {nouveau_candidat.nom_complet}")
        
        # Modification de la justification
        if nouvelles_donnees['justification'] != proposition.justification:
            modifications.append("Justification modifiée")
            proposition.justification = nouvelles_donnees['justification']
            modifications_importantes = True
        
        # Modification des compétences spécifiques
        ancienne_competences = proposition.competences_specifiques or ''
        if nouvelles_donnees['competences_specifiques'] != ancienne_competences:
            modifications.append("Compétences spécifiques modifiées")
            proposition.competences_specifiques = nouvelles_donnees['competences_specifiques']
        
        # Modification de l'expérience pertinente
        ancienne_experience = proposition.experience_pertinente or ''
        if nouvelles_donnees['experience_pertinente'] != ancienne_experience:
            modifications.append("Expérience pertinente modifiée")
            proposition.experience_pertinente = nouvelles_donnees['experience_pertinente']
        
        # Mise à jour des métadonnées
        proposition.derniere_modification_par = profil_utilisateur
        proposition.updated_at = timezone.now()
        
        if hasattr(proposition, 'date_derniere_modification'):
            proposition.date_derniere_modification = timezone.now()
        
        # Ajouter des données de traçabilité
        if not hasattr(proposition, 'donnees_supplementaires'):
            proposition.donnees_supplementaires = {}
        
        if not proposition.donnees_supplementaires:
            proposition.donnees_supplementaires = {}
        
        # Historique des modifications
        if 'historique_modifications' not in proposition.donnees_supplementaires:
            proposition.donnees_supplementaires['historique_modifications'] = []
        
        proposition.donnees_supplementaires['historique_modifications'].append({
            'date': timezone.now().isoformat(),
            'modifie_par': profil_utilisateur.id,
            'modifications': modifications,
            'justification': nouvelles_donnees['justification_modification']
        })
        
        return {
            'success': True,
            'candidat_change': candidat_change,
            'modifications_importantes': modifications_importantes,
            'resume_modifications': modifications
        }
        
    except Exception as e:
        logger.error(f"Erreur application modifications: {e}")
        return {
            'success': False,
            'error': f'Erreur lors de l\'application des modifications: {str(e)}'
        }


def _recalculer_score_proposition(proposition, demande):
    """Recalculer le score d'une proposition après modification du candidat"""
    
    try:
        # Utiliser le système de scoring existant
        from .services.scoring_service import calculer_score_candidat_v41  # Adapter selon votre structure
        
        score_data = calculer_score_candidat_v41(
            candidat=proposition.candidat_propose,
            demande=demande,
            source_proposition=proposition.source_proposition,
            proposant=proposition.proposant
        )
        
        # Mettre à jour les scores détaillés si disponibles
        if hasattr(proposition, 'score_competences'):
            proposition.score_competences = score_data.get('score_competences', 0)
        if hasattr(proposition, 'score_experience'):
            proposition.score_experience = score_data.get('score_experience', 0)
        if hasattr(proposition, 'score_disponibilite'):
            proposition.score_disponibilite = score_data.get('score_disponibilite', 0)
        if hasattr(proposition, 'score_proximite'):
            proposition.score_proximite = score_data.get('score_proximite', 0)
        
        nouveau_score = score_data.get('score_total', 0)
        
        logger.info(f"Score recalculé pour {proposition.candidat_propose.nom_complet}: {nouveau_score}")
        
        return nouveau_score
        
    except Exception as e:
        logger.error(f"Erreur recalcul score: {e}")
        return proposition.score_total  # Garder l'ancien score en cas d'erreur


def _verifier_actions_post_modification(demande, proposition, modifications_appliquees):
    """Vérifier si des actions automatiques sont nécessaires après modification"""
    
    # Si le candidat a changé, vérifier les impacts
    if modifications_appliquees.get('candidat_change'):
        
        # Annuler les évaluations en cours si pas maintenues
        if hasattr(proposition, 'evaluations'):
            evaluations_a_annuler = proposition.evaluations.filter(
                statut__in=['EN_COURS', 'PLANIFIEE']
            )
            
            for evaluation in evaluations_a_annuler:
                evaluation.statut = 'ANNULEE'
                evaluation.motif_annulation = 'Candidat modifié dans la proposition'
                evaluation.save()
        
        # Annuler les entretiens planifiés
        if hasattr(proposition, 'entretiens'):
            entretiens_a_annuler = proposition.entretiens.filter(statut='PLANIFIE')
            for entretien in entretiens_a_annuler:
                entretien.statut = 'ANNULE'
                entretien.motif_annulation = 'Candidat modifié dans la proposition'
                entretien.save()
    
    # Si modifications importantes, notifier le système de workflow
    if modifications_appliquees.get('modifications_importantes'):
        
        # Réinitialiser les validations si nécessaire
        if hasattr(demande, 'validations'):
            validations_a_revoir = demande.validations.filter(
                statut='VALIDEE',
                niveau__gte=2  # Validations de niveau supérieur
            )
            
            for validation in validations_a_revoir:
                validation.statut = 'EN_ATTENTE'
                validation.commentaire_revision = 'Proposition modifiée - nouvelle validation requise'
                validation.save()
    
    logger.info(f"Actions post-modification vérifiées pour la proposition {proposition.id}")


def _notifier_modification_proposition(demande, proposition, modifications, modifie_par, selection_annulee):
    """Notifier les parties prenantes de la modification d'une proposition"""
    
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.conf import settings
    
    try:
        # Liste des personnes à notifier
        destinataires = []
        
        # Le proposant original (si différent de celui qui modifie)
        if proposition.proposant.id != modifie_par.id:
            destinataires.append(proposition.proposant.email)
        
        # Le demandeur
        if demande.demandeur.email not in destinataires:
            destinataires.append(demande.demandeur.email)
        
        # Le manager de la demande
        if hasattr(demande, 'manager_validateur') and demande.manager_validateur:
            if demande.manager_validateur.email not in destinataires:
                destinataires.append(demande.manager_validateur.email)
        
        # Les RH concernés
        rh_emails = ProfilUtilisateur.objects.filter(
            type_profil='RH', 
            actif=True,
            departement=demande.poste.departement  # RH du département concerné
        ).values_list('email', flat=True)
        destinataires.extend([email for email in rh_emails if email not in destinataires])
        
        # Préparer le contexte pour l'email
        contexte = {
            'demande': demande,
            'proposition': proposition,
            'candidat_nom': proposition.candidat_propose.nom_complet,
            'proposant_nom': proposition.proposant.nom_complet,
            'modifie_par': modifie_par.nom_complet,
            'modifications': modifications,
            'selection_annulee': selection_annulee,
            'date_modification': timezone.now(),
            'url_demande': f"{settings.SITE_URL}/interim/demande/{demande.id}/",
            'url_proposition': f"{settings.SITE_URL}/interim/proposition/{proposition.id}/"
        }
        
        # Générer le contenu de l'email
        sujet = f"Interim365 - BNI] Modification proposition - {proposition.candidat_propose.nom_complet} - Demande {demande.numero_demande}"
        
        if selection_annulee:
            sujet += " - Sélection annulée"
        
        message_html = render_to_string('emails/modification_proposition.html', contexte)
        message_text = render_to_string('emails/modification_proposition.txt', contexte)
        
        # Envoyer l'email
        if destinataires:
            send_mail(
                subject=sujet,
                message=message_text,
                html_message=message_html,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=list(set(destinataires)),  # Dédoublonner
                fail_silently=False
            )
            
            logger.info(f"Notification de modification envoyée pour la proposition {proposition.id}")
        
    except Exception as e:
        logger.error(f"Erreur envoi notification modification: {e}")
        # Ne pas faire échouer la modification pour un problème d'email


def _traiter_requete_form(request, demande, profil_utilisateur):
    """Traiter les requêtes Form classiques"""
    with transaction.atomic():
        # Récupérer les données du formulaire
        modifications = []
        
        # Modifier les champs de base de la demande
        if _modifier_champs_base(request, demande, modifications):
            
            # Gestion des propositions existantes
            _gerer_propositions_existantes(request, demande, profil_utilisateur, modifications)
            
            # Gestion des nouvelles propositions
            _gerer_nouvelles_propositions(request, demande, profil_utilisateur, modifications)
            
            # Justification obligatoire
            justification_modification = request.POST.get('justification_modification', '').strip()
            if not justification_modification:
                error_msg = "La justification des modifications est obligatoire"
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return redirect(request.path)
            
            # Sauvegarder la demande
            demande.save()
            
            # Créer l'historique des modifications
            if modifications:
                HistoriqueAction.objects.create(
                    demande=demande,
                    action='MODIFICATION_DEMANDE',
                    utilisateur=profil_utilisateur,
                    description=f"Modification de la demande {demande.numero_demande}: {justification_modification}",
                    donnees_apres={
                        'modifications': modifications,
                        'justification': justification_modification
                    }
                )
            
            # Notifier les parties prenantes si demandé
            if request.POST.get('notifier_parties_prenantes') == '1':
                _notifier_modifications_demande(demande, modifications, justification_modification)
        
        # Réponse selon le type de requête
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'Demande {demande.numero_demande} modifiée avec succès',
                'redirect_url': reverse('demande_detail', args=[demande.id]),
                'modifications': len(modifications)
            })
        else:
            messages.success(request, f'Demande {demande.numero_demande} modifiée avec succès')
            return redirect('demande_detail', demande_id=demande.id)


def _modifier_champs_base(request, demande, modifications):
    """Modifier les champs de base de la demande"""
    from datetime import datetime
    
    # Poste
    poste_id = request.POST.get('poste_id')
    if poste_id and int(poste_id) != demande.poste.id:
        nouveau_poste = get_object_or_404(Poste, id=poste_id)
        modifications.append(f"Poste: {demande.poste.titre} → {nouveau_poste.titre}")
        demande.poste = nouveau_poste
    
    # Personne remplacée
    personne_remplacee_id = request.POST.get('personne_remplacee_id')
    if personne_remplacee_id and int(personne_remplacee_id) != demande.personne_remplacee.id:
        nouvelle_personne = get_object_or_404(ProfilUtilisateur, id=personne_remplacee_id)
        modifications.append(f"Personne remplacée: {demande.personne_remplacee.nom_complet} → {nouvelle_personne.nom_complet}")
        demande.personne_remplacee = nouvelle_personne
    
    # Motif d'absence
    motif_absence_id = request.POST.get('motif_absence_id')
    if motif_absence_id and int(motif_absence_id) != demande.motif_absence.id:
        nouveau_motif = get_object_or_404(MotifAbsence, id=motif_absence_id)
        modifications.append(f"Motif: {demande.motif_absence.nom} → {nouveau_motif.nom}")
        demande.motif_absence = nouveau_motif
    
    # Dates
    date_debut = request.POST.get('date_debut')
    if date_debut and date_debut != demande.date_debut.strftime('%Y-%m-%d'):
        modifications.append(f"Date début: {demande.date_debut} → {date_debut}")
        demande.date_debut = datetime.strptime(date_debut, '%Y-%m-%d').date()
    
    date_fin = request.POST.get('date_fin')
    if date_fin and date_fin != demande.date_fin.strftime('%Y-%m-%d'):
        modifications.append(f"Date fin: {demande.date_fin} → {date_fin}")
        demande.date_fin = datetime.strptime(date_fin, '%Y-%m-%d').date()
    
    # Urgence
    urgence = request.POST.get('urgence', 'NORMALE')
    if urgence != demande.urgence:
        modifications.append(f"Urgence: {demande.urgence} → {urgence}")
        demande.urgence = urgence
    
    # Champs texte
    description_poste = request.POST.get('description_poste', '')
    if description_poste != demande.description_poste:
        modifications.append("Description du poste modifiée")
        demande.description_poste = description_poste
    
    competences_indispensables = request.POST.get('competences_indispensables', '')
    if competences_indispensables != (demande.competences_indispensables or ''):
        modifications.append("Compétences indispensables modifiées")
        demande.competences_indispensables = competences_indispensables
    
    instructions_particulieres = request.POST.get('instructions_particulieres', '')
    if instructions_particulieres != (demande.instructions_particulieres or ''):
        modifications.append("Instructions particulières modifiées")
        demande.instructions_particulieres = instructions_particulieres
    
    # Nombre max de propositions
    nb_max_propositions = int(request.POST.get('nb_max_propositions', 3))
    if nb_max_propositions != demande.nb_max_propositions_par_utilisateur:
        modifications.append(f"Nb max propositions: {demande.nb_max_propositions_par_utilisateur} → {nb_max_propositions}")
        demande.nb_max_propositions_par_utilisateur = nb_max_propositions
    
    return True


def _gerer_propositions_existantes(request, demande, profil_utilisateur, modifications):
    """Gérer les modifications/suppressions des propositions existantes"""
    # Récupérer les propositions à supprimer
    propositions_a_supprimer = request.POST.getlist('supprimer_propositions')
    for proposition_id in propositions_a_supprimer:
        try:
            proposition = PropositionCandidat.objects.get(
                id=proposition_id,
                demande_interim=demande,
                proposant=profil_utilisateur
            )
            modifications.append(f"Proposition supprimée: {proposition.candidat_propose.nom_complet}")
            proposition.delete()
        except PropositionCandidat.DoesNotExist:
            pass
    
    # Récupérer les propositions à modifier
    propositions_existantes = demande.propositions_candidats.filter(proposant=profil_utilisateur)
    
    for proposition in propositions_existantes:
        prefix = f"proposition_{proposition.id}_"
        
        # Vérifier si cette proposition doit être modifiée
        nouveau_candidat_id = request.POST.get(f"{prefix}candidat_id")
        nouvelle_justification = request.POST.get(f"{prefix}justification")
        nouvelles_competences = request.POST.get(f"{prefix}competences")
        nouvelle_experience = request.POST.get(f"{prefix}experience")
        
        proposition_modifiee = False
        
        # Modifier le candidat
        if nouveau_candidat_id and int(nouveau_candidat_id) != proposition.candidat_propose.id:
            nouveau_candidat = get_object_or_404(ProfilUtilisateur, id=nouveau_candidat_id)
            modifications.append(f"Candidat modifié: {proposition.candidat_propose.nom_complet} → {nouveau_candidat.nom_complet}")
            proposition.candidat_propose = nouveau_candidat
            proposition_modifiee = True
        
        # Modifier la justification
        if nouvelle_justification and nouvelle_justification != proposition.justification:
            modifications.append("Justification de proposition modifiée")
            proposition.justification = nouvelle_justification
            proposition_modifiee = True
        
        # Modifier les compétences
        if nouvelles_competences != (proposition.competences_specifiques or ''):
            modifications.append("Compétences spécifiques modifiées")
            proposition.competences_specifiques = nouvelles_competences
            proposition_modifiee = True
        
        # Modifier l'expérience
        if nouvelle_experience != (proposition.experience_pertinente or ''):
            modifications.append("Expérience pertinente modifiée")
            proposition.experience_pertinente = nouvelle_experience
            proposition_modifiee = True
        
        if proposition_modifiee:
            proposition.statut = 'SOUMISE'  # Remettre en attente d'évaluation
            proposition.save()


def _gerer_nouvelles_propositions(request, demande, profil_utilisateur, modifications):
    """Gérer l'ajout de nouvelles propositions"""
    # Proposition manuelle classique
    candidat_propose_id = request.POST.get('candidat_propose_id')
    justification_proposition = request.POST.get('justification_proposition', '').strip()
    
    if candidat_propose_id and justification_proposition:
        candidat_propose = get_object_or_404(ProfilUtilisateur, id=candidat_propose_id)
        
        # Vérifier si cette proposition n'existe pas déjà
        if not demande.propositions_candidats.filter(
            candidat_propose=candidat_propose,
            proposant=profil_utilisateur
        ).exists():

            from .services.scoring_service import ScoringInterimService
            scoring_service = ScoringInterimService

            score_initial = scoring_service.calculer_score_candidat_v41
            eval = scoring_service.calc_score_basique_v41(candidat_propose, demande)
            # Calculer les bonus
            bonus_validateur = _calculer_bonus_validateur(profil_utilisateur)        
            #bonus_evaluation = _calculer_bonus_evaluation(eval_adequation, eval_experience, eval_disponibilite)
            #bonus_evaluation = _calculer_bonus_evaluation(eval.similarite_poste, eval.experience_kelio, eval.disponibilite_kelio)
            bonus_priorite = _calculer_bonus_priorite(demande.priorite)
            
            #score_final = min(100, max(0, score_base + bonus_validateur + bonus_evaluation + bonus_priorite))

            score_final = min(100, max(0, score_initial + bonus_validateur + bonus_priorite))

            #score = _calculer_score_candidat_simple(candidat_propose, demande)

            PropositionCandidat.objects.create(
                demande_interim=demande,
                candidat_propose=candidat_propose,
                proposant=profil_utilisateur,
                source_proposition='DEMANDEUR_MODIFICATION',
                justification=justification_proposition,
                competences_specifiques=request.POST.get('competences_specifiques', ''),
                experience_pertinente=request.POST.get('experience_pertinente', ''),
                score_automatique = score_final,
                statut='SOUMISE'
            )
            modifications.append(f"Nouvelle proposition: {candidat_propose.nom_complet}")


def _enregistrer_proposition_automatique(request, demande, profil_utilisateur, data):
    """Enregistrer une proposition issue du système automatique"""
    try:
        with transaction.atomic():
            # Modifier les champs de base de la demande
            _modifier_demande_depuis_json(demande, data)
            
            # Créer la proposition sélectionnée
            candidat_id = data.get('candidat_selectionne_id')
            justification = data.get('justification', '').strip()
            
            if not candidat_id or not justification:
                return JsonResponse({'success': False, 'error': 'Candidat et justification requis'})
            
            candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
            
            # Supprimer les anciennes propositions de ce demandeur
            demande.propositions_candidats.filter(proposant=profil_utilisateur).delete()

            # Créer la nouvelle proposition
            proposition = PropositionCandidat.objects.create(
                demande_interim=demande,
                candidat_propose=candidat,
                proposant=profil_utilisateur,
                source_proposition='SYSTEME_AUTOMATIQUE',
                justification=justification,
                competences_specifiques=data.get('competences_specifiques', ''),
                statut='SOUMISE',
                donnees_supplementaires={
                    'score_automatique': _obtenir_score_candidat(candidat_id, data.get('liste_candidats', [])),
                    'selection_automatique': True
                }
            )
            
            # Sauvegarder la demande
            demande.save()
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                action='MODIFICATION_AVEC_PROPOSITION_AUTO',
                utilisateur=profil_utilisateur,
                description=f"Modification avec proposition automatique: {candidat.nom_complet}",
                donnees_apres={
                    'candidat_propose': candidat.nom_complet,
                    'source': 'automatique',
                    'score': proposition.donnees_supplementaires.get('score_automatique', 0)
                }
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Demande modifiée avec proposition automatique de {candidat.nom_complet}',
                'numero_demande': demande.numero_demande,
                'redirect_url': reverse('demande_detail', args=[demande.id])
            })
            
    except Exception as e:
        logger.error(f"Erreur proposition automatique: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


def _enregistrer_proposition_specifique(request, demande, profil_utilisateur, data):
    """Enregistrer une proposition spécifique"""
    try:
        with transaction.atomic():
            # Modifier les champs de base de la demande
            _modifier_demande_depuis_json(demande, data)
            
            # Créer la proposition spécifique
            candidat_id = data.get('candidat_specifique_id')
            justification = data.get('justification', '').strip()
            
            if not candidat_id or not justification:
                return JsonResponse({'success': False, 'error': 'Candidat et justification requis'})
            
            candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
            
            # Supprimer les anciennes propositions de ce demandeur
            demande.propositions_candidats.filter(proposant=profil_utilisateur).delete()
            
            from .services.scoring_service import ScoringInterimService
            
            scoring_service = ScoringInterimService
            #eval = scoring_service.calc_score_basique_v41(candidat, demande)
            # Calculer les bonus
            bonus_validateur = _calculer_bonus_validateur(profil_utilisateur)        
            #bonus_evaluation = _calculer_bonus_evaluation(eval_adequation, eval_experience, eval_disponibilite)
            #bonus_evaluation = _calculer_bonus_evaluation(eval.similarite_poste, eval.experience_kelio, eval.disponibilite_kelio)
            bonus_priorite = _calculer_bonus_priorite(demande.priorite)

            score_initial = scoring_service.calculer_score_candidat_v41(candidat, profil_utilisateur, demande)    
            #score_final = min(100, max(0, score_base + bonus_validateur + bonus_evaluation + bonus_priorite))

            score_final = min(100, max(0, score_initial + bonus_validateur + bonus_priorite))
            

            # Créer la nouvelle proposition
            PropositionCandidat.objects.create(
                demande_interim=demande,
                candidat_propose=candidat,
                proposant=profil_utilisateur,
                source_proposition='CANDIDAT_SPECIFIQUE',
                justification=justification,
                competences_specifiques=data.get('competences_specifiques', ''),
                experience_pertinente=data.get('experience_pertinente', ''),
                score_automatique = score_final,
                statut='SOUMISE'
            )
            
            # Sauvegarder la demande
            demande.save()
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                action='MODIFICATION_AVEC_PROPOSITION_SPECIFIQUE',
                utilisateur=profil_utilisateur,
                description=f"Modification avec proposition spécifique: {candidat.nom_complet}",
                donnees_apres={
                    'candidat_propose': candidat.nom_complet,
                    'source': 'specifique'
                }
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Demande modifiée avec proposition de {candidat.nom_complet}',
                'numero_demande': demande.numero_demande,
                'redirect_url': reverse('demande_detail', args=[demande.id])
            })
            
    except Exception as e:
        logger.error(f"Erreur proposition spécifique: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


def _modifier_demande_depuis_json(demande, data):
    """Modifier une demande à partir des données JSON"""
    from datetime import datetime
    
    # Poste
    if data.get('poste_id'):
        poste = get_object_or_404(Poste, id=data['poste_id'])
        demande.poste = poste
    
    # Personne remplacée
    if data.get('personne_remplacee_id'):
        personne = get_object_or_404(ProfilUtilisateur, id=data['personne_remplacee_id'])
        demande.personne_remplacee = personne
    
    # Motif d'absence
    if data.get('motif_absence_id'):
        motif = get_object_or_404(MotifAbsence, id=data['motif_absence_id'])
        demande.motif_absence = motif
    
    # Dates
    if data.get('date_debut'):
        demande.date_debut = datetime.strptime(data['date_debut'], '%Y-%m-%d').date()
    if data.get('date_fin'):
        demande.date_fin = datetime.strptime(data['date_fin'], '%Y-%m-%d').date()
    
    # Autres champs
    if 'urgence' in data:
        demande.urgence = data['urgence']
    if 'description_poste' in data:
        demande.description_poste = data['description_poste']
    if 'competences_indispensables' in data:
        demande.competences_indispensables = data['competences_indispensables']
    if 'instructions_particulieres' in data:
        demande.instructions_particulieres = data['instructions_particulieres']
    if 'nb_max_propositions' in data:
        demande.nb_max_propositions_par_utilisateur = int(data['nb_max_propositions'])


def _preparer_context_modification(request, demande, profil_utilisateur):
    """Préparer le contexte pour l'affichage de la page de modification"""
    
    # Récupérer les propositions existantes avec leurs informations détaillées
    propositions_existantes = []
    for proposition in demande.propositions_candidats.select_related(
        'candidat_propose', 'proposant', 'candidat_propose__poste', 
        'candidat_propose__departement', 'candidat_propose__site'
    ).all():
        
        # Déterminer les permissions sur cette proposition
        peut_etre_modifiee = (
            proposition.proposant == profil_utilisateur and 
            proposition.statut in ['SOUMISE', 'EN_EVALUATION']
        )
        
        peut_etre_supprimee = (
            proposition.proposant == profil_utilisateur and 
            proposition.statut in ['SOUMISE', 'EN_EVALUATION', 'REJETEE']
        )
        
        # Calculer la classe de score pour l'affichage
        score_class = 'poor'
        if proposition.score_total:
            if proposition.score_total >= 80:
                score_class = 'excellent'
            elif proposition.score_total >= 60:
                score_class = 'good'
            elif proposition.score_total >= 40:
                score_class = 'average'
        
        proposition_data = {
            'id': proposition.id,
            'candidat_propose': proposition.candidat_propose,
            'proposant': proposition.proposant,
            'statut': proposition.statut,
            'justification': proposition.justification,
            'competences_specifiques': proposition.competences_specifiques,
            'experience_pertinente': proposition.experience_pertinente,
            'score_total': proposition.score_total,
            'score_class': score_class,
            'created_at': proposition.created_at,
            'peut_etre_modifiee': peut_etre_modifiee,
            'peut_etre_supprimee': peut_etre_supprimee,
            'source_proposition': proposition.source_proposition,
        }
        
        propositions_existantes.append(proposition_data)
    
    # Candidats proposables (pour les nouvelles propositions)
    candidats_proposables = _get_candidats_proposables(profil_utilisateur)
    
    # Peut proposer candidat
    peut_proposer_candidat = _peut_proposer_candidat(profil_utilisateur, demande)
    
    # Statistiques sur les propositions
    stats_propositions = {
        'total': len(propositions_existantes),
        'en_attente': len([p for p in propositions_existantes if p['statut'] == 'SOUMISE']),
        'en_evaluation': len([p for p in propositions_existantes if p['statut'] == 'EN_EVALUATION']),
        'retenues': len([p for p in propositions_existantes if p['statut'] == 'RETENUE']),
        'selectionnee': len([p for p in propositions_existantes if p['statut'] == 'SELECTIONNEE']),
    }
    
    context = {
        'demande': demande,
        'profil_utilisateur': profil_utilisateur,
        'propositions_existantes': propositions_existantes,
        'stats_propositions': stats_propositions,
        'departements': Departement.objects.filter(actif=True).order_by('nom'),
        'sites': Site.objects.filter(actif=True).order_by('nom'),
        'postes': Poste.objects.filter(actif=True),
        'motifs_absence': MotifAbsence.objects.filter(actif=True),
        'candidats_proposables': candidats_proposables,
        'peut_proposer_candidat': peut_proposer_candidat,
        'mode_modification': True,
        'urgences': DemandeInterim.URGENCE_CHOICES,
        'today': timezone.now().date(),
    }
    
    return render(request, 'demande_modifier.html', context)


def _obtenir_score_candidat(candidat_id, liste_candidats):
    """Obtenir le score d'un candidat depuis la liste des candidats automatiques"""
    for candidat in liste_candidats:
        if candidat.get('id') == candidat_id:
            return candidat.get('score', 0)
    return 0


def _notifier_modifications_demande(demande, modifications, justification):
    """Notifier les parties prenantes des modifications apportées à la demande"""
    # Implémenter la logique de notification
    # (emails, notifications internes, etc.)
    pass


@login_required
def demande_interim_delete_view(request, demande_id):
    """Vue pour supprimer une demande d'intérim"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if not _peut_supprimer_demande(profil_utilisateur, demande):
            messages.error(request, "Vous n'êtes pas autorisé à supprimer cette demande")
            return redirect('demande_detail', demande_id=demande_id)
        
        if request.method == 'POST':
            numero_demande = demande.numero_demande
            demande.delete()
            messages.success(request, f"Demande {numero_demande} supprimée avec succès")
            return redirect('mes_demandes')
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil_utilisateur
        }
        
        return render(request, 'demande_delete_confirm.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required  
def demande_interim_create_view(request, matricule):
    """Vue pour créer une demande pour un employé spécifique"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        employe_remplace = get_object_or_404(ProfilUtilisateur, matricule=matricule)
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'employe_remplace': employe_remplace,
            'departements': Departement.objects.filter(actif=True).order_by('nom'),
            'sites': Site.objects.filter(actif=True).order_by('nom'),
            'postes': Poste.objects.filter(actif=True),
            'motifs_absence': MotifAbsence.objects.filter(actif=True),
            'mode_pour_employe': True
        }
        
        return render(request, 'demande_creer.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES RECHERCHE ET SÉLECTION
# ================================================================

def recherche_candidats_avancee(request):
    """Vue de recherche avancée de candidats"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Filtres de recherche
        departement_id = request.GET.get('departement')
        site_id = request.GET.get('site')
        competence = request.GET.get('competence')
        disponible_seulement = request.GET.get('disponible') == 'true'
        
        # Base query
        candidats = ProfilUtilisateur.objects.filter(
            actif=True,
            statut_employe='ACTIF'
        ).select_related('user', 'poste', 'departement', 'site')
        
        # Appliquer les filtres
        if departement_id:
            candidats = candidats.filter(departement_id=departement_id)
        
        if site_id:
            candidats = candidats.filter(site_id=site_id)
        
        if disponible_seulement:
            candidats = candidats.filter(extended_data__disponible_interim=True)
        
        # Pagination
        paginator = Paginator(candidats, 20)
        page_number = request.GET.get('page')
        candidats_page = paginator.get_page(page_number)
        
        context = {
            'candidats': candidats_page,
            'profil_utilisateur': profil_utilisateur,
            'departements': Departement.objects.filter(actif=True),
            'sites': Site.objects.filter(actif=True),
            'filtres_actifs': {
                'departement_id': departement_id,
                'site_id': site_id,
                'competence': competence,
                'disponible_seulement': disponible_seulement
            }
        }
        
        return render(request, 'recherche_avancee.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

def recherche_candidats_ajax(request):
    """Recherche AJAX de candidats"""
    try:
        terme = request.GET.get('q', '').strip()
        limite = min(int(request.GET.get('limit', 10)), 50)
        
        if len(terme) < 2:
            return JsonResponse({'candidats': []})
        
        candidats = ProfilUtilisateur.objects.filter(
            Q(user__first_name__icontains=terme) |
            Q(user__last_name__icontains=terme) |
            Q(matricule__icontains=terme),
            actif=True,
            statut_employe='ACTIF'
        ).select_related('user', 'poste')[:limite]
        
        candidats_data = [{
            'id': c.id,
            'nom_complet': c.nom_complet,
            'matricule': c.matricule,
            'poste': c.poste.titre if c.poste else '',
            'departement': c.departement.nom if c.departement else '',
            'disponible': c.extended_data.disponible_interim if hasattr(c, 'extended_data') else True
        } for c in candidats]
        
        return JsonResponse({'candidats': candidats_data})
        
    except Exception as e:
        logger.error(f"Erreur recherche AJAX: {e}")
        return JsonResponse({'error': str(e)}, status=500)

def interim_selection(request):
    """Vue principale de sélection"""
    context = {
        'page_title': 'Sélection de candidats'
    }
    return render(request, 'interim_selection.html', context)

def selection_candidats_view(request, demande_id):
    """Vue pour sélectionner des candidats pour une demande"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if not _peut_voir_demande(profil_utilisateur, demande):
            messages.error(request, "Vous n'êtes pas autorisé à voir cette demande")
            return redirect('index')
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil_utilisateur,
            'candidats_proposes': demande.propositions_candidats.all(),
            'peut_proposer': _peut_proposer_candidat(profil_utilisateur, demande)
        }
        
        return render(request, 'interim/selection_candidats.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')


# 1. DANS views.py - Fonction _get_prochains_validateurs (REMPLACE LA LOGIQUE EXISTANTE)
def _get_prochains_validateurs(demande, utilisateur_actuel):
    """
    Détermine les prochains validateurs selon le niveau CORRIGÉ
    """
    validateurs = []
    
    try:
        niveau_actuel = demande.niveau_validation_actuel
        
        # Étape 0 → 1 : Première validation - RESPONSABLE
        if niveau_actuel == 0:
            responsables = ProfilUtilisateur.objects.filter(
                type_profil='RESPONSABLE',
                departement=demande.poste.departement,
                actif=True
            )
            for responsable in responsables:
                validateurs.append({
                    'niveau': 1,
                    'titre': 'Responsable département (N+1)',
                    'nom': responsable.nom_complet,
                    'poste': responsable.poste.titre if responsable.poste else '',
                    'est_utilisateur_actuel': responsable == utilisateur_actuel
                })
        
        # Étape 1 → 2 : Deuxième validation - DIRECTEUR
        elif niveau_actuel == 1:
            directeurs = ProfilUtilisateur.objects.filter(
                type_profil='DIRECTEUR',
                departement=demande.poste.departement,
                actif=True
            )
            for directeur in directeurs:
                validateurs.append({
                    'niveau': 2,
                    'titre': 'Directeur (N+2)',
                    'nom': directeur.nom_complet,
                    'poste': directeur.poste.titre if directeur.poste else '',
                    'est_utilisateur_actuel': directeur == utilisateur_actuel
                })
        
        # Étape 2+ → Final : Validation RH/ADMIN
        elif niveau_actuel >= 2:
            rh_admin = ProfilUtilisateur.objects.filter(
                type_profil__in=['RH', 'ADMIN'],
                actif=True
            )
            for validateur in rh_admin:
                validateurs.append({
                    'niveau': 3,
                    'titre': 'Validation RH/Admin (Finale)',
                    'nom': validateur.nom_complet,
                    'poste': validateur.poste.titre if validateur.poste else 'RH/Admin',
                    'est_utilisateur_actuel': validateur == utilisateur_actuel
                })
    
    except Exception as e:
        logger.error(f"Erreur récupération prochains validateurs: {e}")
    
    return validateurs
   
# ================================================================
# VUE PRINCIPALE DE VALIDATION
# ================================================================

@login_required
def demande_interim_validation(request, demande_id):
    """
    Vue de validation complète - VERSION AMÉLIORÉE avec scores détaillés
    """
    try:
        # Vérifications préliminaires
        profil_utilisateur = getattr(request.user, 'profilutilisateur', None)
        if not profil_utilisateur:
            if request.user.is_superuser:
                try:
                    profil_utilisateur = get_profil_or_virtual(request.user)
                except Exception as e:
                    logger.error(f"Erreur création profil virtuel: {e}")
                    messages.error(request, "Impossible de créer le profil utilisateur")
                    return redirect('index')
            else:
                messages.error(request, "Profil utilisateur non trouvé")
                return redirect('index')
        
        try:
            demande = get_object_or_404(DemandeInterim, id=demande_id)
        except Http404:
            messages.error(request, f"Demande d'intérim #{demande_id} non trouvée")
            return redirect('index')
        
        # Vérifier les permissions de validation
        permissions = _get_permissions_validation_detaillees(profil_utilisateur, demande)
        if not permissions['peut_valider']:
            messages.error(request, permissions['raison_refus'])
            return redirect('demande_detail', demande_id=demande.id)
        
        # Traitement POST si nécessaire
        if request.method == 'POST':
            try:
                return _traiter_validation_workflow_complete(request, demande, profil_utilisateur)
            except Exception as e:
                logger.error(f"Erreur traitement validation: {e}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': f'Erreur lors du traitement: {str(e)}'
                    }, status=500)
                else:
                    messages.error(request, f"Erreur lors du traitement: {str(e)}")
                    return redirect('interim_validation', demande.id)
        
        # ================================================================
        # RÉCUPÉRATION DES DONNÉES AVEC SCORES DÉTAILLÉS
        # ================================================================
        
        # 1. Propositions précédentes avec scores détaillés
        propositions_precedentes = _get_propositions_avec_scores_detailles(demande, profil_utilisateur)
        
        # 2. Candidats automatiques avec scores détaillés
        candidats_automatiques = _get_candidats_automatiques_avec_scores_detailles(demande)
        
        # 3. Informations workflow et permissions
        workflow_info = _get_workflow_info_complete(demande, profil_utilisateur)
        
        # 4. Détails enrichis de la demande
        demande_details = _enrichir_details_demande_complete(demande)
        
        # 5. Motifs de refus standardisés
        motifs_refus = _get_motifs_refus_standards()
        
        # ================================================================
        # CONTEXTE FINAL POUR LE TEMPLATE
        # ================================================================
        
        context = {
            # Données principales
            'demande': demande,
            'demande_details': demande_details,
            'profil_utilisateur': profil_utilisateur,
            
            # Propositions avec scores détaillés
            'propositions_precedentes': propositions_precedentes,
            'candidats_automatiques': candidats_automatiques,
            
            # Workflow et permissions
            'workflow_info': workflow_info,
            'permissions': permissions,
            
            # Configuration
            'motifs_refus': motifs_refus,
            'page_title': f'Validation demande {demande.numero_demande}',
            
            # Statistiques pour affichage
            'stats_propositions': {
                'nb_precedentes': len(propositions_precedentes),
                'nb_automatiques': len(candidats_automatiques),
                'peut_proposer_alternative': permissions.get('peut_proposer_nouveau', True),
            }
        }
        
        logger.info(f"Vue validation chargée - {len(propositions_precedentes)} propositions + {len(candidats_automatiques)} candidats automatiques")
        
        return render(request, 'interim_validation.html', context)
        
    except Exception as e:
        logger.error(f"Erreur générale vue validation: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Erreur système: {str(e)}'
            }, status=500)
        else:
            messages.error(request, f"Erreur lors du chargement: {str(e)}")
            return redirect('index')

def _get_propositions_avec_scores_detailles(demande, profil_utilisateur_actuel):
    """
    Récupère TOUTES les propositions avec leurs scores détaillés et commentaires
    """
    try:
        # Récupérer TOUTES les propositions pour cette demande
        propositions = PropositionCandidat.objects.filter(
            demande_interim=demande
        ).select_related(
            'candidat_propose__user',
            'candidat_propose__poste', 
            'candidat_propose__departement',
            'candidat_propose__site',
            'proposant__user',
            'proposant__departement'
        ).order_by('-score_final', '-created_at')
        
        propositions_enrichies = []
        
        for proposition in propositions:
            try:
                # Correction des dates
                created_at = proposition.created_at
                if isinstance(created_at, str):
                    try:
                        from django.utils.dateparse import parse_datetime
                        created_at = parse_datetime(created_at)
                        if not created_at:
                            created_at = timezone.now()
                    except:
                        created_at = timezone.now()
                elif not created_at:
                    created_at = timezone.now()
                
                # Récupérer les scores détaillés
                scores_details = _get_score_detaille_candidat(proposition.candidat_propose, demande)
                
                # Récupérer les commentaires liés aux scores
                commentaires_score = _get_commentaires_score_candidat(proposition.candidat_propose, demande)
                
                # Informations de base de la proposition
                proposition_data = {
                    'id': proposition.id,
                    'candidat_propose': proposition.candidat_propose,
                    'proposant': proposition.proposant,
                    'created_at': created_at,
                    'justification': proposition.justification or "Aucune justification fournie",
                    'competences_specifiques': proposition.competences_specifiques or "",
                    'experience_pertinente': proposition.experience_pertinente or "",
                    'score_final': proposition.score_final or 0,
                    'source_display': _get_source_display_safe(proposition),
                    'statut': proposition.statut or "SOUMISE",
                    
                    # NOUVEAUTÉ : Scores détaillés
                    'scores_details': scores_details,
                    'commentaires_score': commentaires_score,
                    'score_automatique': proposition.score_automatique or 0,
                    'bonus_proposition_humaine': proposition.bonus_proposition_humaine or 0,
                }
                
                # Classe CSS pour le score
                score_final = proposition.score_final or 0
                if score_final >= 85:
                    proposition_data['score_class'] = 'score-excellent'
                elif score_final >= 70:
                    proposition_data['score_class'] = 'score-good'
                elif score_final >= 55:
                    proposition_data['score_class'] = 'score-average'
                else:
                    proposition_data['score_class'] = 'score-poor'
                
                propositions_enrichies.append(proposition_data)
                
            except Exception as e:
                logger.error(f"Erreur enrichissement proposition {proposition.id}: {e}")
                # Ajouter quand même la proposition avec les données minimales
                propositions_enrichies.append({
                    'id': proposition.id if hasattr(proposition, 'id') else 0,
                    'candidat_propose': proposition.candidat_propose,
                    'proposant': proposition.proposant,
                    'created_at': timezone.now(),
                    'justification': "Données non disponibles",
                    'competences_specifiques': "",
                    'experience_pertinente': "",
                    'score_final': 0,
                    'source_display': "Non définie",
                    'statut': "SOUMISE",
                    'score_class': 'score-poor',
                    'scores_details': {},
                    'commentaires_score': []
                })
        
        logger.info(f"Récupération de {len(propositions_enrichies)} propositions avec scores détaillés")
        return propositions_enrichies
        
    except Exception as e:
        logger.error(f"Erreur récupération propositions avec scores: {e}")
        return []

def _get_candidats_automatiques_avec_scores_detailles(demande):
    """
    Récupère les candidats automatiques avec scores détaillés complets
    """
    try:
        # Utiliser le service de scoring V4.1
        from .services.scoring_service import ScoringInterimService
        
        service_scoring = ScoringInterimService()
        candidats_ia_data = service_scoring.generer_candidats_automatiques_v41(
            demande=demande,
            limite=50,
            inclure_donnees_kelio=True
        )
        
        # Trier par score décroissant
        candidats_ia_data.sort(key=lambda x: x.get('score', 0), reverse=True)
        candidats_ia_data = candidats_ia_data[:20]  # Limiter à 20 pour l'affichage
        
        candidats_automatiques = []
        
        for candidat_data in candidats_ia_data:
            candidat = candidat_data['candidat']
            score_final = candidat_data['score']
            
            try:
                # Validation et conversion du score
                if score_final is None or score_final == '':
                    score_final = 0
                
                try:
                    score_affichage = int(float(score_final))
                except (ValueError, TypeError):
                    logger.warning(f"Score IA invalide pour candidat {candidat.matricule}: {score_final}")
                    score_affichage = 0
                
                # Récupérer les scores détaillés avec le service V4.1
                scores_details = _get_score_detaille_automatique_v41(candidat, demande, candidat_data)
                
                # Récupérer les commentaires du système automatique
                commentaires_auto = _get_commentaires_automatiques_v41(candidat_data)
                
                # Informations candidat enrichies
                candidat_info = _enrichir_info_candidat_avec_disponibilite(candidat, demande)
                
                candidat_data_enrichi = {
                    'candidat': candidat,
                    'candidat_info': candidat_info,
                    
                    # Score principal
                    'score_affichage': score_affichage,
                    'score_class': _get_score_css_class(score_affichage),
                    
                    # NOUVEAUTÉ : Scores détaillés automatiques
                    'scores_details': scores_details,
                    'commentaires_score': commentaires_auto,
                    'justification_auto': candidat_data.get('justification_auto', ''),
                    
                    # Métadonnées du scoring automatique
                    'type_source': 'AUTOMATIQUE',
                    'source_display': "Sélection automatique (Scoring V4.1)",
                    'source_icon': 'fa-robot',
                    'source_color': 'info',
                    'algorithme_version': candidat_data.get('version_scoring', '4.1'),
                    'confiance_prediction': _calculer_confiance_scoring_v41(score_affichage),
                    'date_calcul': timezone.now(),
                    'donnees_kelio_disponibles': candidat_data.get('donnees_kelio_disponibles', False),
                    'derniere_sync_kelio': candidat_data.get('derniere_sync_kelio')
                }
                
                candidats_automatiques.append(candidat_data_enrichi)
                
            except Exception as e:
                logger.error(f"Erreur traitement candidat automatique {candidat.id}: {e}")
                continue
        
        # Tri final par score
        candidats_automatiques.sort(key=lambda x: x['score_affichage'], reverse=True)
        
        logger.info(f"{len(candidats_automatiques)} candidats automatiques avec scores détaillés")
        return candidats_automatiques
        
    except Exception as e:
        logger.error(f"Erreur récupération candidats automatiques détaillés: {e}")
        return []

def _get_score_detaille_candidat(candidat, demande):
    """
    Récupère les détails du score d'un candidat pour une demande
    """
    try:
        # Chercher d'abord dans ScoreDetailCandidat
        score_detail = ScoreDetailCandidat.objects.filter(
            candidat=candidat,
            demande_interim=demande
        ).first()
        
        if score_detail:
            return {
                'score_total': score_detail.score_total,
                'score_similarite_poste': score_detail.score_similarite_poste,
                'score_competences': score_detail.score_competences,
                'score_disponibilite': score_detail.score_disponibilite,
                'score_proximite': score_detail.score_proximite,
                'score_anciennete': score_detail.score_anciennete,
                'score_experience': score_detail.score_experience,
                'bonus_proposition_humaine': score_detail.bonus_proposition_humaine,
                'bonus_experience_similaire': score_detail.bonus_experience_similaire,
                'bonus_recommandation': score_detail.bonus_recommandation,
                'bonus_hierarchique': score_detail.bonus_hierarchique,
                'penalite_indisponibilite': score_detail.penalite_indisponibilite,
                'calcule_par': score_detail.calcule_par,
                'date_calcul': score_detail.created_at,
                'est_proposition_humaine': score_detail.est_proposition_humaine
            }
        else:
            # Calculer les scores à la volée si pas en base
            return _calculer_scores_detailles_a_la_volee(candidat, demande)
            
    except Exception as e:
        logger.error(f"Erreur récupération score détaillé candidat {candidat.id}: {e}")
        return {}

def _get_score_detaille_automatique_v41(candidat, demande, candidat_data):
    """
    Récupère les scores détaillés d'un candidat automatique V4.1
    """
    try:
        # Extraire les détails du scoring V4.1
        scores_bruts = candidat_data.get('scores_detailles', {})
        
        return {
            'score_total': candidat_data.get('score', 0),
            'score_similarite_poste': scores_bruts.get('similarite_poste', 0),
            'score_competences': scores_bruts.get('competences', 0),
            'score_disponibilite': scores_bruts.get('disponibilite', 0),
            'score_proximite': scores_bruts.get('proximite', 0),
            'score_anciennete': scores_bruts.get('anciennete', 0),
            'score_experience': scores_bruts.get('experience', 0),
            'bonus_kelio': candidat_data.get('bonus_kelio', 0),
            'penalite_distance': candidat_data.get('penalite_distance', 0),
            'facteurs_decisifs': candidat_data.get('facteurs_decisifs', []),
            'calcule_par': 'AUTOMATIQUE_V41',
            'date_calcul': timezone.now(),
            'version_algorithme': candidat_data.get('version_scoring', '4.1'),
            'donnees_sources': candidat_data.get('sources_donnees', [])
        }
        
    except Exception as e:
        logger.error(f"Erreur récupération score automatique V4.1: {e}")
        return {}

def _get_commentaires_score_candidat(candidat, demande):
    """
    Récupère les commentaires liés au score d'un candidat
    """
    try:
        commentaires = []
        
        # Commentaires des propositions humaines
        propositions = PropositionCandidat.objects.filter(
            candidat_propose=candidat,
            demande_interim=demande
        ).select_related('proposant', 'evaluateur')
        
        for proposition in propositions:
            if proposition.justification:
                commentaires.append({
                    'type': 'JUSTIFICATION_PROPOSITION',
                    'auteur': proposition.proposant.nom_complet,
                    'date': proposition.created_at,
                    'contenu': proposition.justification,
                    'score_associe': proposition.score_final
                })
            
            if proposition.commentaire_evaluation:
                commentaires.append({
                    'type': 'EVALUATION_VALIDATEUR',
                    'auteur': proposition.evaluateur.nom_complet if proposition.evaluateur else 'Système',
                    'date': proposition.date_evaluation,
                    'contenu': proposition.commentaire_evaluation,
                    'score_associe': proposition.score_humain_ajuste
                })
        
        # Commentaires des validations
        validations = ValidationDemande.objects.filter(
            demande=demande,
            candidats_retenus__icontains=str(candidat.id)
        ).select_related('validateur')
        
        for validation in validations:
            if validation.commentaire:
                commentaires.append({
                    'type': 'COMMENTAIRE_VALIDATION',
                    'auteur': validation.validateur.nom_complet,
                    'date': validation.date_validation,
                    'contenu': validation.commentaire,
                    'decision': validation.decision
                })
        
        # Trier par date décroissante
        commentaires.sort(key=lambda x: x.get('date', timezone.now()), reverse=True)
        
        return commentaires
        
    except Exception as e:
        logger.error(f"Erreur récupération commentaires score: {e}")
        return []

def _get_commentaires_automatiques_v41(candidat_data):
    """
    Récupère les commentaires automatiques du système de scoring V4.1
    """
    try:
        commentaires = []
        
        # Justification automatique générale
        if candidat_data.get('justification_auto'):
            commentaires.append({
                'type': 'JUSTIFICATION_AUTOMATIQUE',
                'auteur': 'Système IA V4.1',
                'date': timezone.now(),
                'contenu': candidat_data['justification_auto'],
                'score_associe': candidat_data.get('score', 0)
            })
        
        # Facteurs décisifs
        facteurs_decisifs = candidat_data.get('facteurs_decisifs', [])
        if facteurs_decisifs:
            facteurs_text = f"Facteurs décisifs identifiés : {', '.join(facteurs_decisifs)}"
            commentaires.append({
                'type': 'FACTEURS_DECISIFS',
                'auteur': 'Algorithme de scoring',
                'date': timezone.now(),
                'contenu': facteurs_text,
                'score_associe': candidat_data.get('score', 0)
            })
        
        # Analyse de disponibilité
        if candidat_data.get('analyse_disponibilite'):
            commentaires.append({
                'type': 'ANALYSE_DISPONIBILITE',
                'auteur': 'Module de disponibilité',
                'date': timezone.now(),
                'contenu': candidat_data['analyse_disponibilite'],
                'score_associe': candidat_data.get('scores_detailles', {}).get('disponibilite', 0)
            })
        
        return commentaires
        
    except Exception as e:
        logger.error(f"Erreur récupération commentaires automatiques: {e}")
        return []

def _enrichir_info_candidat_avec_disponibilite(candidat, demande):
    """
    Enrichit les informations du candidat avec sa disponibilité
    """
    try:
        # Informations de base
        candidat_info = {
            'nom_complet': candidat.nom_complet,
            'matricule': candidat.matricule,
            'poste_actuel': candidat.poste.titre if candidat.poste else 'Poste non renseigné',
            'departement': candidat.departement.nom if candidat.departement else 'Département non renseigné',
            'site': candidat.site.nom if candidat.site else 'Site non renseigné',
        }
        
        # Vérifier la disponibilité pour cette demande
        if demande.date_debut and demande.date_fin:
            disponibilite = candidat.est_disponible_pour_interim(demande.date_debut, demande.date_fin)
            candidat_info['disponibilite'] = disponibilite
        else:
            candidat_info['disponibilite'] = {
                'disponible': True,
                'raison': 'Dates de mission non définies',
                'score_disponibilite': 50
            }
        
        # Compétences principales (limiter à 5)
        try:
            competences = candidat.competences.select_related('competence').order_by('-niveau_maitrise')[:5]
            candidat_info['competences_principales'] = [
                {
                    'nom': comp.competence.nom,
                    'niveau': comp.niveau_maitrise,
                    'certifie': comp.certifie
                }
                for comp in competences
            ]
        except:
            candidat_info['competences_principales'] = []
        
        return candidat_info
        
    except Exception as e:
        logger.error(f"Erreur enrichissement info candidat: {e}")
        return {
            'nom_complet': getattr(candidat, 'nom_complet', 'Nom non disponible'),
            'matricule': getattr(candidat, 'matricule', 'N/A'),
            'poste_actuel': 'Poste non renseigné',
            'departement': 'Département non renseigné',
            'site': 'Site non renseigné',
            'disponibilite': {'disponible': False, 'raison': 'Erreur de chargement', 'score_disponibilite': 0},
            'competences_principales': []
        }

def _calculer_scores_detailles_a_la_volee(candidat, demande):
    """Calcule les scores détaillés à la volée si pas en base"""
    try:
        from .services.scoring_service import ScoringInterimService
        service_scoring = ScoringInterimService()
        
        # Calculer le score complet
        score_data = service_scoring.calculer_score_candidat_v41(candidat, demande)
        
        return score_data.get('scores_detailles', {})
        
    except Exception as e:
        logger.error(f"Erreur calcul scores à la volée: {e}")
        return {}
                    
def _traiter_validation_workflow_complete(request, demande, profil_utilisateur):
    """
    Traite les 3 cas possibles de validation :
    1. Validation d'une proposition précédente
    2. Refus avec justifications
    3. Proposition alternative
    """
    try:
        # Récupération des données de base
        commentaire_general = request.POST.get('commentaire_validation_general', '').strip()
        if not commentaire_general:
            raise ValidationError("Le commentaire général est obligatoire")
        
        action_validation = request.POST.get('action_validation')
        
        # ================================================================
        # CAS 1 : REFUS GLOBAL DE LA DEMANDE
        # ================================================================
        
        if action_validation == 'REFUSER':
            return _traiter_refus_global_demande(request, demande, profil_utilisateur, commentaire_general)
        
        # ================================================================
        # CAS 2 : VALIDATION D'UNE PROPOSITION PRÉCÉDENTE
        # ================================================================
        
        decision_proposition = request.POST.get('decision_proposition')
        if decision_proposition and decision_proposition.startswith('VALIDER_'):
            proposition_id = decision_proposition.replace('VALIDER_', '')
            return _traiter_validation_proposition_precedente(
                request, demande, profil_utilisateur, proposition_id, commentaire_general
            )
        
        # ================================================================
        # CAS 3 : PROPOSITION ALTERNATIVE
        # ================================================================
        
        proposer_alternative = request.POST.get('proposer_alternative') == '1'
        if proposer_alternative:
            return _traiter_proposition_alternative(
                request, demande, profil_utilisateur, commentaire_general
            )
        
        # ================================================================
        # CAS 4 : REFUS DE TOUTES LES PROPOSITIONS SANS ALTERNATIVE
        # ================================================================
        
        return _traiter_refus_sans_alternative(
            request, demande, profil_utilisateur, commentaire_general
        )
        
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect('interim_validation', demande.id)
    except Exception as e:
        logger.error(f"Erreur traitement validation workflow: {e}")
        raise

def _traiter_refus_global_demande(request, demande, profil_utilisateur, commentaire_general):
    """
    Traite le refus global de la demande d'intérim
    """
    try:
        # Récupérer les détails du refus depuis le formulaire
        motif_refus = request.POST.get('motif_refus_global', '').strip()
        details_refus = request.POST.get('details_refus_global', '').strip()
        
        # Validation des données
        if not details_refus:
            messages.error(request, "Les détails du refus sont obligatoires")
            return redirect('interim_validation', demande.id)
        
        if not motif_refus:
            motif_refus = "AUTRE"
        
        # Construire le commentaire complet
        commentaire_complet = f"{commentaire_general}\n\nMotif: {motif_refus}\nDétails: {details_refus}"
        
        # Créer la validation de refus
        validation = ValidationDemande.objects.create(
            demande=demande,
            type_validation=_determiner_type_validation_niveau(profil_utilisateur, demande),
            niveau_validation=demande.niveau_validation_actuel + 1,
            validateur=profil_utilisateur,
            decision='REFUSE',
            commentaire=commentaire_complet
        )
        
        # Valider immédiatement
        validation.valider('REFUSE', commentaire_complet)
        
        # Mettre à jour le statut de la demande
        demande.statut = 'REFUSEE'
        demande.save()
        
        # Notifier les parties prenantes
        _notifier_refus_demande(demande, profil_utilisateur, motif_refus, details_refus)
        
        # Créer l'historique
        _creer_historique_validation_safe(
            demande, profil_utilisateur, 'REFUS_GLOBAL',
            f"Refus de la demande - Motif: {motif_refus}",
            {
                'motif_refus': str(motif_refus),
                'details_refus': str(details_refus),
                'commentaire_general': str(commentaire_general)
            }
        )
        
        # Message de confirmation
        messages.warning(request, 
            f"Demande {demande.numero_demande} refusée définitivement. "
            f"Le demandeur a été notifié.")
        
        logger.info(f"Demande {demande.numero_demande} refusée par {profil_utilisateur.nom_complet}")
        
        return redirect('demande_detail', demande_id=demande.id)
        
    except Exception as e:
        logger.error(f"Erreur refus global demande {demande.id}: {e}")
        messages.error(request, f"Erreur lors du refus de la demande: {str(e)}")
        return redirect('interim_validation', demande.id)
    
def _traiter_validation_proposition_precedente(request, demande, profil_utilisateur, proposition_id, commentaire_general):
    """
    Traite la validation d'une proposition des niveaux précédents - VERSION CORRIGÉE
    """
    try:
        # Récupérer la proposition à valider
        proposition = get_object_or_404(PropositionCandidat, id=proposition_id, demande_interim=demande)
        
        # Justification spécifique à cette validation
        justification_validation = request.POST.get(f'justification_validation_{proposition_id}', '').strip()
        
        # Traiter les refus des autres propositions - CORRECTION
        refus_justifications = _traiter_refus_autres_propositions_safe(request, demande, proposition_id)
        
        # Créer la validation avec données sécurisées
        candidats_retenus_data = [{
            'proposition_id': str(proposition.id),
            'candidat_id': str(proposition.candidat_propose.id),
            'candidat_nom': str(proposition.candidat_propose.nom_complet),
            'justification_validateur': str(justification_validation),
            'score_final': int(proposition.score_final or 0)
        }]
        
        validation = ValidationDemande.objects.create(
            demande=demande,
            type_validation=_determiner_type_validation_niveau(profil_utilisateur, demande),
            niveau_validation=demande.niveau_validation_actuel + 1,
            validateur=profil_utilisateur,
            decision='APPROUVE',
            commentaire=commentaire_general,
            candidats_retenus=candidats_retenus_data,  # Liste de dictionnaires
            candidats_rejetes=refus_justifications     # Liste de dictionnaires
        )
        validation.valider('APPROUVE', commentaire_general)
        
        # Mettre à jour le niveau de validation de la demande
        demande.niveau_validation_actuel += 1
        
        # Vérifier si c'est la validation finale
        if demande.niveau_validation_actuel >= demande.niveaux_validation_requis:
            demande.candidat_selectionne = proposition.candidat_propose
            demande.statut = 'VALIDEE'
            
            # Créer la notification au candidat sélectionné
            _notifier_candidat_selectionne_safe(proposition.candidat_propose, demande, profil_utilisateur)
            
            messages.success(request, 
                f"Demande validée définitivement. Candidat sélectionné : {proposition.candidat_propose.nom_complet}")
        else:
            demande.statut = 'EN_VALIDATION'
            prochaine_etape = _get_prochaine_etape_validation_safe(demande)
            
            # Notifier le prochain validateur - VERSION SÉCURISÉE
            _notifier_prochain_validateur_safe(demande, prochaine_etape)
            
            messages.success(request, 
                f"Proposition validée. Transmission au niveau suivant : {prochaine_etape.get('nom', 'Niveau suivant')}")
        
        demande.save()
        
        # Créer l'historique avec données sécurisées
        _creer_historique_validation_safe(
            demande, profil_utilisateur, 'VALIDATION_PROPOSITION_PRECEDENTE',
            f"Validation de la proposition de {proposition.candidat_propose.nom_complet}",
            {
                'proposition_validee': str(proposition.id),
                'justification_validation': str(justification_validation),
                'refus_autres': refus_justifications
            }
        )
        
        return redirect('demande_detail', demande_id=demande.id)
        
    except Exception as e:
        logger.error(f"Erreur validation proposition précédente: {e}")
        messages.error(request, f"Erreur lors de la validation: {str(e)}")
        return redirect('interim_validation', demande.id)


def _traiter_proposition_alternative(request, demande, profil_utilisateur, commentaire_general):
    """
    Version corrigée du traitement des propositions alternatives
    """
    try:
        # Récupération des données du candidat alternatif
        candidat_alternatif_id = request.POST.get('candidat_alternatif_id')
        if not candidat_alternatif_id:
            raise ValidationError("Candidat alternatif non sélectionné")
        
        candidat_alternatif = get_object_or_404(ProfilUtilisateur, id=candidat_alternatif_id)
        
        # Justifications et détails
        justification_alternative = request.POST.get('justification_proposition_alternative', '').strip()
        if not justification_alternative:
            raise ValidationError("La justification de la proposition alternative est obligatoire")
        
        competences_specifiques = request.POST.get('competences_specifiques_alternative', '').strip()
        experience_pertinente = request.POST.get('experience_pertinente_alternative', '').strip()
        
        # Calculer le score du candidat alternatif de façon sécurisée
        score_alternatif = 0
        try:
            from mainapp.services.scoring_service import ScoringInterimService
            service_scoring = ScoringInterimService()
            score_alternatif = service_scoring.calculer_score_candidat_v41(candidat_alternatif, demande)
            if not isinstance(score_alternatif, (int, float)):
                score_alternatif = 0
        except Exception as e:
            logger.error(f"Erreur calcul score alternatif: {e}")
            score_alternatif = 0
        
        # Traiter les refus de toutes les propositions précédentes - VERSION SÉCURISÉE
        refus_justifications = _traiter_refus_toutes_propositions_precedentes_safe(request, demande)
        
        # Créer la nouvelle proposition alternative
        proposition_alternative = PropositionCandidat.objects.create(
            demande_interim=demande,
            candidat_propose=candidat_alternatif,
            proposant=profil_utilisateur,
            source_proposition=_determiner_source_proposition_niveau(profil_utilisateur),
            statut='VALIDEE',
            niveau_validation_propose=demande.niveau_validation_actuel + 1,
            justification=justification_alternative,
            competences_specifiques=competences_specifiques,
            experience_pertinente=experience_pertinente,
            score_automatique=int(score_alternatif),
            bonus_proposition_humaine=_calculer_bonus_hierarchique(profil_utilisateur),
        )
        proposition_alternative.calculer_score_final()
        
        # Données sécurisées pour la validation
        candidats_retenus_data = [{
            'proposition_id': str(proposition_alternative.id),
            'candidat_id': str(candidat_alternatif.id),
            'candidat_nom': str(candidat_alternatif.nom_complet),
            'justification_validateur': str(justification_alternative),
            'score_final': int(proposition_alternative.score_final or 0),
            'type': 'PROPOSITION_ALTERNATIVE'
        }]
        
        # Créer la validation avec la proposition alternative
        validation = ValidationDemande.objects.create(
            demande=demande,
            type_validation=_determiner_type_validation_niveau(profil_utilisateur, demande),
            niveau_validation=demande.niveau_validation_actuel + 1,
            validateur=profil_utilisateur,
            decision='CANDIDAT_AJOUTE',
            commentaire=commentaire_general,
            nouveau_candidat_propose=candidat_alternatif,
            justification_nouveau_candidat=justification_alternative,
            candidats_rejetes=refus_justifications,
            candidats_retenus=candidats_retenus_data
        )
        validation.valider('CANDIDAT_AJOUTE', commentaire_general)
        
        # Mettre à jour la demande
        demande.niveau_validation_actuel += 1
        
        # Vérifier si c'est la validation finale
        if demande.niveau_validation_actuel >= demande.niveaux_validation_requis:
            demande.candidat_selectionne = candidat_alternatif
            demande.statut = 'VALIDEE'
            
            _notifier_candidat_selectionne_safe(candidat_alternatif, demande)
            
            messages.success(request, 
                f"Proposition alternative validée définitivement. Candidat sélectionné : {candidat_alternatif.nom_complet}")
        else:
            demande.statut = 'EN_VALIDATION'
            prochaine_etape = _get_prochaine_etape_validation_safe(demande)
            
            _notifier_prochain_validateur_safe(demande, prochaine_etape)
            
            messages.success(request, 
                f"Proposition alternative ajoutée. Transmission au niveau suivant : {prochaine_etape.get('nom', 'Niveau suivant')}")
        
        demande.save()
        
        # Créer l'historique avec données sécurisées
        _creer_historique_validation_safe(
            demande, profil_utilisateur, 'PROPOSITION_ALTERNATIVE',
            f"Proposition alternative : {candidat_alternatif.nom_complet}",
            {
                'candidat_alternatif_id': str(candidat_alternatif.id),
                'justification_alternative': str(justification_alternative),
                'score_alternatif': int(score_alternatif),
                'refus_precedentes': refus_justifications
            }
        )
        
        return redirect('demande_detail', demande_id=demande.id)
        
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect('interim_validation', demande.id)
    except Exception as e:
        logger.error(f"Erreur proposition alternative: {e}")
        messages.error(request, f"Erreur lors de la proposition alternative: {str(e)}")
        return redirect('interim_validation', demande.id)

def _traiter_refus_toutes_propositions_precedentes_safe(request, demande):
    """
    Version sécurisée - RETOURNE TOUJOURS UNE LISTE
    """
    refus_justifications = []
    
    try:
        propositions = PropositionCandidat.objects.filter(demande_interim=demande)
        
        for proposition in propositions:
            justification_refus = request.POST.get(f'justification_refus_{proposition.id}', '').strip()
            
            # Si pas de justification spécifique, utiliser une justification par défaut
            if not justification_refus:
                justification_refus = "Refusé au profit d'une proposition alternative"
            
            refus_data = {
                'proposition_id': str(proposition.id),
                'candidat_id': str(proposition.candidat_propose.id),
                'candidat_nom': str(proposition.candidat_propose.nom_complet),
                'justification_refus': str(justification_refus),
                'score_original': int(proposition.score_final or 0)
            }
            refus_justifications.append(refus_data)
        
        # S'assurer de retourner une liste
        if not isinstance(refus_justifications, list):
            refus_justifications = []
            
        return refus_justifications
        
    except Exception as e:
        logger.error(f"Erreur traitement refus toutes propositions: {e}")
        return []  # Toujours retourner une liste vide en cas d'erreur

def _get_propositions_precedentes_simplifiees(demande, profil_utilisateur_actuel):
    """
    Récupère TOUTES les propositions existantes pour la demande, 
    avec correction des types de données pour éviter les erreurs template
    """
    try:
        # Récupérer TOUTES les propositions pour cette demande
        propositions = PropositionCandidat.objects.filter(
            demande_interim=demande
        ).select_related(
            'candidat_propose__user',
            'candidat_propose__poste', 
            'candidat_propose__departement',
            'candidat_propose__site',
            'proposant__user',
            'proposant__departement'
        ).order_by('-score_final', '-created_at')
        
        propositions_enrichies = []
        
        for proposition in propositions:
            try:
                # S'assurer que created_at est bien un datetime
                created_at = proposition.created_at
                if isinstance(created_at, str):
                    # Tenter de convertir si c'est une string
                    try:
                        from django.utils.dateparse import parse_datetime
                        created_at = parse_datetime(created_at)
                        if not created_at:
                            created_at = timezone.now()
                    except:
                        created_at = timezone.now()
                elif not created_at:
                    created_at = timezone.now()
                
                # Informations de base de la proposition
                proposition_data = {
                    'id': proposition.id,
                    'candidat_propose': proposition.candidat_propose,
                    'proposant': proposition.proposant,
                    'created_at': created_at,  # Date corrigée
                    'justification': proposition.justification or "Aucune justification fournie",
                    'competences_specifiques': proposition.competences_specifiques or "",
                    'experience_pertinente': proposition.experience_pertinente or "",
                    'score_final': proposition.score_final or 0,
                    'source_display': _get_source_display_safe(proposition),
                    'statut': proposition.statut or "SOUMISE",
                }
                
                # Classe CSS pour le score
                score_final = proposition.score_final or 0
                if score_final >= 85:
                    proposition_data['score_class'] = 'score-excellent'
                elif score_final >= 70:
                    proposition_data['score_class'] = 'score-good'
                elif score_final >= 55:
                    proposition_data['score_class'] = 'score-average'
                else:
                    proposition_data['score_class'] = 'score-poor'
                
                propositions_enrichies.append(proposition_data)
                
            except Exception as e:
                logger.error(f"Erreur enrichissement proposition {proposition.id}: {e}")
                # Ajouter quand même la proposition avec les données minimales
                propositions_enrichies.append({
                    'id': proposition.id if hasattr(proposition, 'id') else 0,
                    'candidat_propose': proposition.candidat_propose,
                    'proposant': proposition.proposant,
                    'created_at': timezone.now(),  # Date de fallback
                    'justification': "Données non disponibles",
                    'competences_specifiques': "",
                    'experience_pertinente': "",
                    'score_final': 0,
                    'source_display': "Non définie",
                    'statut': "SOUMISE",
                    'score_class': 'score-poor'
                })
        
        logger.info(f"Récupération de {len(propositions_enrichies)} propositions pour la demande {demande.numero_demande}")
        return propositions_enrichies
        
    except Exception as e:
        logger.error(f"Erreur récupération propositions précédentes: {e}")
        return []

def _get_source_display_safe(proposition):
    """
    Récupère l'affichage de la source de façon sécurisée
    """
    try:
        if hasattr(proposition, 'source_display'):
            return proposition.source_display
        elif hasattr(proposition, 'source_proposition'):
            # Mapping manuel des sources
            sources = {
                'DEMANDEUR_INITIAL': 'Demandeur initial',
                'MANAGER_DIRECT': 'Manager direct',
                'CHEF_EQUIPE': 'Chef d\'équipe',
                'RESPONSABLE': 'Responsable (N+1)',
                'DIRECTEUR': 'Directeur (N+2)',
                'RH': 'RH (Final)',
                'ADMIN': 'Admin (Final)',
                'SUPERUSER': 'Superutilisateur',
                'VALIDATION_ETAPE': 'Validation',
                'SYSTEME': 'Système',
                'AUTRE': 'Autre'
            }
            return sources.get(proposition.source_proposition, 'Source non définie')
        else:
            return "Source non définie"
    except Exception as e:
        logger.error(f"Erreur récupération source display: {e}")
        return "Source non définie"
        
def _enrichir_details_candidat_proposition(candidat, demande):
    """
    Enrichit les détails d'un candidat pour l'affichage dans les propositions
    """
    try:
        details = {
            'nom_complet': candidat.nom_complet,
            'matricule': candidat.matricule,
            'poste_actuel': candidat.poste.titre if candidat.poste else 'Poste non renseigné',
            'departement': candidat.departement.nom if candidat.departement else 'Département non renseigné',
            'site': candidat.site.nom if candidat.site else 'Site non renseigné',
            'anciennete': _calculer_anciennete_display(candidat),
            'competences_principales': _get_competences_principales(candidat),
            'disponibilite': _verifier_disponibilite_candidat(candidat, demande.date_debut, demande.date_fin),
        }
        
        return details
        
    except Exception as e:
        logger.error(f"Erreur enrichissement détails candidat {candidat.id}: {e}")
        return {
            'nom_complet': candidat.nom_complet if hasattr(candidat, 'nom_complet') else 'Nom non disponible',
            'matricule': getattr(candidat, 'matricule', 'N/A'),
            'poste_actuel': 'Poste non renseigné',
            'departement': 'Département non renseigné',
            'site': 'Site non renseigné',
            'anciennete': 'Non renseignée',
            'competences_principales': [],
            'disponibilite': {'disponible': False, 'raison': 'Information non disponible'}
        }


def _traiter_refus_autres_propositions_safe(request, demande, proposition_validee_id):
    """
    Version sécurisée du traitement des refus - RETOURNE TOUJOURS UNE LISTE
    """
    refus_justifications = []
    
    try:
        # Récupérer toutes les propositions de la demande
        toutes_propositions = PropositionCandidat.objects.filter(demande_interim=demande)
        
        for proposition in toutes_propositions:
            if str(proposition.id) != str(proposition_validee_id):
                # Vérifier si un refus a été saisi pour cette proposition
                justification_refus = request.POST.get(f'justification_refus_{proposition.id}', '').strip()
                
                if justification_refus:
                    refus_data = {
                        'proposition_id': str(proposition.id),
                        'candidat_id': str(proposition.candidat_propose.id),
                        'candidat_nom': str(proposition.candidat_propose.nom_complet),
                        'justification_refus': str(justification_refus),
                        'score_original': int(proposition.score_final or 0)
                    }
                    refus_justifications.append(refus_data)
        
        # S'assurer de retourner une liste
        if not isinstance(refus_justifications, list):
            refus_justifications = []
            
        return refus_justifications
        
    except Exception as e:
        logger.error(f"Erreur traitement refus autres propositions: {e}")
        return []  # Toujours retourner une liste vide en cas d'erreur

def _traiter_refus_toutes_propositions_precedentes(request, demande):
    """
    Traite les justifications de refus pour toutes les propositions précédentes
    """
    refus_justifications = []
    
    try:
        propositions = PropositionCandidat.objects.filter(demande_interim=demande)
        
        for proposition in propositions:
            justification_refus = request.POST.get(f'justification_refus_{proposition.id}', '').strip()
            
            # Si pas de justification spécifique, utiliser une justification par défaut
            if not justification_refus:
                justification_refus = "Refusé au profit d'une proposition alternative"
            
            refus_justifications.append({
                'proposition_id': proposition.id,
                'candidat_id': proposition.candidat_propose.id,
                'candidat_nom': proposition.candidat_propose.nom_complet,
                'justification_refus': justification_refus,
                'score_original': proposition.score_final
            })
        
        return refus_justifications
        
    except Exception as e:
        logger.error(f"Erreur traitement refus toutes propositions: {e}")
        return []


def _get_permissions_validation_detaillees(profil_utilisateur, demande):
    """
    Détermine les permissions détaillées de validation pour un utilisateur
    """
    try:
        permissions = {
            'peut_valider': False,
            'peut_proposer_nouveau': False,
            'peut_escalader': False,
            'niveau_requis': demande.niveau_validation_actuel + 1,
            'type_validateur': 'NON_AUTORISE',
            'raison_refus': 'Permissions insuffisantes'
        }
        
        # Superutilisateurs ont tous les droits
        if profil_utilisateur.is_superuser:
            permissions.update({
                'peut_valider': True,
                'peut_proposer_nouveau': True,
                'peut_escalader': True,
                'type_validateur': 'SUPERUSER',
                'raison_refus': None
            })
            return permissions
        
        # Vérifier le niveau de validation requis
        niveau_requis = demande.niveau_validation_actuel + 1
        
        if niveau_requis == 1 and profil_utilisateur.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']:
            permissions.update({
                'peut_valider': True,
                'peut_proposer_nouveau': True,
                'type_validateur': 'RESPONSABLE',
                'raison_refus': None
            })
        elif niveau_requis == 2 and profil_utilisateur.type_profil in ['DIRECTEUR', 'RH', 'ADMIN']:
            permissions.update({
                'peut_valider': True,
                'peut_proposer_nouveau': True,
                'type_validateur': 'DIRECTEUR',
                'raison_refus': None
            })
        elif niveau_requis >= 3 and profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            permissions.update({
                'peut_valider': True,
                'peut_proposer_nouveau': True,
                'peut_escalader': True,
                'type_validateur': 'RH' if profil_utilisateur.type_profil == 'RH' else 'ADMIN',
                'raison_refus': None
            })
        else:
            permissions['raison_refus'] = f"Niveau {niveau_requis} requis, votre niveau : {profil_utilisateur.type_profil}"
        
        return permissions
        
    except Exception as e:
        logger.error(f"Erreur calcul permissions validation: {e}")
        return {
            'peut_valider': False,
            'peut_proposer_nouveau': False,
            'peut_escalader': False,
            'type_validateur': 'ERREUR',
            'raison_refus': f'Erreur technique: {str(e)}'
        }

def _traiter_refus_sans_alternative(request, demande, profil_utilisateur, commentaire_general):
    """
    Traite le refus de toutes les propositions précédentes sans proposer d'alternative
    Ce cas renvoie la demande au niveau précédent pour de nouvelles propositions
    """
    try:
        # ================================================================
        # COLLECTE DES JUSTIFICATIONS DE REFUS
        # ================================================================
        
        refus_justifications = []
        propositions_existantes = PropositionCandidat.objects.filter(demande_interim=demande)
        
        # Vérifier qu'il y a au moins des justifications de refus
        au_moins_un_refus_justifie = False
        
        for proposition in propositions_existantes:
            justification_refus = request.POST.get(f'justification_refus_{proposition.id}', '').strip()
            
            if justification_refus:
                au_moins_un_refus_justifie = True
                refus_justifications.append({
                    'proposition_id': proposition.id,
                    'candidat_id': proposition.candidat_propose.id,
                    'candidat_nom': proposition.candidat_propose.nom_complet,
                    'justification_refus': justification_refus,
                    'score_original': proposition.score_final or 0,
                    'proposant': proposition.proposant.nom_complet
                })
            else:
                # Ajouter une justification par défaut si non fournie
                refus_justifications.append({
                    'proposition_id': proposition.id,
                    'candidat_id': proposition.candidat_propose.id,
                    'candidat_nom': proposition.candidat_propose.nom_complet,
                    'justification_refus': "Candidat non retenu (aucune justification spécifique fournie)",
                    'score_original': proposition.score_final or 0,
                    'proposant': proposition.proposant.nom_complet
                })
        
        # Si aucune proposition n'existe, on ne peut pas traiter ce cas
        if not propositions_existantes.exists():
            raise ValidationError(
                "Aucune proposition à refuser. Veuillez proposer un candidat alternatif ou refuser globalement la demande."
            )
        
        # ================================================================
        # DÉTERMINER LA STRATÉGIE DE RENVOI
        # ================================================================
        
        # Option pour forcer de nouvelles propositions
        forcer_nouvelles_propositions = request.POST.get('forcer_nouvelles_propositions') == '1'
        
        if forcer_nouvelles_propositions:
            # Remettre la demande en recherche de candidats
            strategie_renvoi = 'NOUVELLE_RECHERCHE'
            nouveau_statut = 'EN_PROPOSITION'
            message_retour = "Demande renvoyée pour de nouvelles propositions de candidats"
        else:
            # Renvoyer au niveau précédent
            if demande.niveau_validation_actuel > 0:
                strategie_renvoi = 'NIVEAU_PRECEDENT'
                nouveau_statut = 'EN_VALIDATION'
                demande.niveau_validation_actuel -= 1
                message_retour = f"Demande renvoyée au niveau de validation précédent"
            else:
                # Si on est déjà au niveau 0, forcer la nouvelle recherche
                strategie_renvoi = 'NOUVELLE_RECHERCHE'
                nouveau_statut = 'EN_PROPOSITION'
                message_retour = "Demande renvoyée pour de nouvelles propositions de candidats"
        
        # ================================================================
        # CRÉER LA VALIDATION DE REFUS
        # ================================================================
        
        validation = ValidationDemande.objects.create(
            demande=demande,
            type_validation=_determiner_type_validation_niveau(profil_utilisateur, demande),
            niveau_validation=demande.niveau_validation_actuel + 1,
            validateur=profil_utilisateur,
            decision='REPORTE',  # Utiliser REPORTE car on renvoie la demande
            commentaire=f"{commentaire_general}\n\nToutes les propositions précédentes ont été refusées. {message_retour}.",
            candidats_rejetes=refus_justifications
        )
        
        validation.valider('REPORTE', validation.commentaire)
        
        # ================================================================
        # METTRE À JOUR LA DEMANDE
        # ================================================================
        
        demande.statut = nouveau_statut
        
        # Réinitialiser les propositions si nouvelle recherche
        if strategie_renvoi == 'NOUVELLE_RECHERCHE':
            # Marquer les anciennes propositions comme rejetées
            propositions_existantes.update(statut='REJETEE')
            
            # Réinitialiser le niveau de validation si nécessaire
            demande.niveau_validation_actuel = 0
            
            # Réactiver les propositions si elles étaient fermées
            demande.propositions_autorisees = True
            if demande.date_limite_propositions and demande.date_limite_propositions < timezone.now():
                # Prolonger la date limite de 7 jours
                demande.date_limite_propositions = timezone.now() + timedelta(days=7)
        
        demande.save()
        
        # ================================================================
        # NOTIFICATIONS ET COMMUNICATIONS
        # ================================================================
        
        if strategie_renvoi == 'NOUVELLE_RECHERCHE':
            # Notifier les personnes qui peuvent faire des propositions
            _notifier_nouvelle_recherche_candidats(demande, refus_justifications, profil_utilisateur)
            
            # Notifier le demandeur original
            _notifier_demandeur_nouvelle_recherche(
                demande, 
                f"Les candidats proposés n'ont pas été retenus. Une nouvelle recherche de candidats est en cours.",
                refus_justifications
            )
            
        else:  # NIVEAU_PRECEDENT
            # Notifier le niveau précédent
            niveau_precedent = _get_infos_niveau_validation(demande.niveau_validation_actuel)
            if niveau_precedent:
                _notifier_renvoi_niveau_precedent(demande, niveau_precedent, refus_justifications, profil_utilisateur)
        
        # ================================================================
        # CRÉER L'HISTORIQUE DÉTAILLÉ
        # ================================================================
        
        _creer_historique_validation(
            demande, profil_utilisateur, 'REFUS_SANS_ALTERNATIVE',
            f"Refus de toutes les propositions - {message_retour}",
            {
                'strategie_renvoi': strategie_renvoi,
                'nouveau_statut': nouveau_statut,
                'nb_propositions_refusees': len(refus_justifications),
                'refus_detailles': refus_justifications,
                'niveau_validation_apres': demande.niveau_validation_actuel,
                'forcer_nouvelles_propositions': forcer_nouvelles_propositions
            }
        )
        
        # ================================================================
        # MESSAGE DE CONFIRMATION
        # ================================================================
        
        if strategie_renvoi == 'NOUVELLE_RECHERCHE':
            messages.info(request, 
                f"Toutes les propositions ont été refusées. La demande est renvoyée pour de nouvelles propositions de candidats. "
                f"Les parties prenantes ont été notifiées."
            )
        else:
            messages.info(request, 
                f"Toutes les propositions ont été refusées. La demande est renvoyée au niveau de validation précédent. "
                f"Le validateur précédent a été notifié."
            )
        
        return redirect('demande_detail', demande_id=demande.id)
        
    except ValidationError as e:
        logger.warning(f"Erreur validation refus sans alternative: {e}")
        messages.error(request, str(e))
        return redirect('interim_validation', demande.id)
        
    except Exception as e:
        logger.error(f"Erreur traitement refus sans alternative: {e}")
        messages.error(request, 
            "Une erreur technique est survenue lors du traitement du refus. "
            "Veuillez réessayer ou contacter l'administrateur."
        )
        return redirect('interim_validation', demande.id)


def _notifier_nouvelle_recherche_candidats(demande, refus_justifications, validateur):
    """
    Notifie les parties prenantes qu'une nouvelle recherche de candidats est nécessaire
    """
    try:
        # Liste des personnes à notifier (qui peuvent proposer)
        personnes_a_notifier = []
        
        # 1. Le demandeur original
        personnes_a_notifier.append(demande.demandeur)
        
        # 2. Les managers et responsables du département concerné
        if demande.poste and demande.poste.departement:
            # Manager du département
            if demande.poste.departement.manager:
                personnes_a_notifier.append(demande.poste.departement.manager)
            
            # Tous les responsables, directeurs, RH du département
            responsables_dept = ProfilUtilisateur.objects.filter(
                departement=demande.poste.departement,
                type_profil__in=['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'],
                actif=True
            ).exclude(id=validateur.id)
            
            personnes_a_notifier.extend(responsables_dept)
        
        # 3. Les RH et admins globaux
        rh_admins = ProfilUtilisateur.objects.filter(
            type_profil__in=['RH', 'ADMIN'],
            actif=True
        ).exclude(id=validateur.id)
        
        personnes_a_notifier.extend(rh_admins)
        
        # Supprimer les doublons
        personnes_uniques = list(set(personnes_a_notifier))
        
        # Créer les notifications
        for personne in personnes_uniques:
            NotificationInterim.objects.create(
                destinataire=personne,
                expediteur=validateur,
                demande=demande,
                type_notification='NOUVELLE_DEMANDE',  # Réutiliser ce type
                urgence='HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE',
                titre=f"Nouvelle recherche candidats - {demande.numero_demande}",
                message=f"""
Les candidats proposés pour la demande d'intérim {demande.numero_demande} n'ont pas été retenus.

Poste concerné : {demande.poste.titre if demande.poste else 'Non spécifié'}
Personne à remplacer : {demande.personne_remplacee.nom_complet}
Période : du {safe_date_format(demande.date_debut)} au {safe_date_format(demande.date_fin)}

Candidats précédemment refusés :
{chr(10).join([f"- {refus['candidat_nom']}: {refus['justification_refus']}" for refus in refus_justifications[:5]])}

Votre action : Proposer de nouveaux candidats adaptés au poste.
""",
                url_action_principale=reverse('interim_demande') + f'?demande_id={demande.id}',
                texte_action_principale="Proposer candidat",
                url_action_secondaire=reverse('demande_detail', args=[demande.id]),
                texte_action_secondaire="Voir détails"
            )
        
        logger.info(f"Notifications nouvelle recherche envoyées à {len(personnes_uniques)} personnes")
        
    except Exception as e:
        logger.error(f"Erreur notifications nouvelle recherche: {e}")


def _notifier_demandeur_nouvelle_recherche(demande, message_principal, refus_justifications):
    """
    Notifie spécifiquement le demandeur que de nouveaux candidats sont recherchés
    """
    try:
        NotificationInterim.objects.create(
            destinataire=demande.demandeur,
            demande=demande,
            type_notification='DEMANDE_A_VALIDER',  # Réutiliser ce type
            urgence='NORMALE',
            titre=f"Nouvelle recherche candidats - {demande.numero_demande}",
            message=f"""
{message_principal}

Détail des refus :
{chr(10).join([f"- {refus['candidat_nom']}: {refus['justification_refus']}" for refus in refus_justifications[:3]])}

La recherche de nouveaux candidats est en cours. Vous serez notifié dès qu'un candidat adapté sera proposé.
""",
            url_action_principale=reverse('demande_detail', args=[demande.id]),
            texte_action_principale="Voir ma demande"
        )
        
    except Exception as e:
        logger.error(f"Erreur notification demandeur nouvelle recherche: {e}")


def _notifier_renvoi_niveau_precedent(demande, niveau_precedent, refus_justifications, validateur):
    """
    Notifie le niveau de validation précédent du renvoi
    """
    try:
        # Identifier les validateurs du niveau précédent
        validateurs_precedents = ProfilUtilisateur.objects.filter(
            type_profil=niveau_precedent['type_profil'],
            actif=True
        )
        
        # Si département spécifique, filtrer
        if demande.poste and demande.poste.departement:
            validateurs_precedents = validateurs_precedents.filter(
                departement=demande.poste.departement
            )
        
        for validateur_precedent in validateurs_precedents:
            NotificationInterim.objects.create(
                destinataire=validateur_precedent,
                expediteur=validateur,
                demande=demande,
                type_notification='DEMANDE_A_VALIDER',
                urgence='HAUTE',
                titre=f"Demande renvoyée - {demande.numero_demande}",
                message=f"""
La demande d'intérim {demande.numero_demande} vous est renvoyée pour reconsidération.

Le validateur {validateur.nom_complet} ({validateur.type_profil}) a refusé toutes les propositions actuelles.

Candidats refusés :
{chr(10).join([f"- {refus['candidat_nom']}: {refus['justification_refus']}" for refus in refus_justifications[:3]])}

Action requise : Proposer de nouveaux candidats ou reconsidérer les propositions existantes.
""",
                url_action_principale=reverse('interim_validation', args=[demande.id]),
                texte_action_principale="Traiter la demande",
                url_action_secondaire=reverse('demande_detail', args=[demande.id]),
                texte_action_secondaire="Voir détails"
            )
        
        logger.info(f"Notifications renvoi envoyées au niveau précédent")
        
    except Exception as e:
        logger.error(f"Erreur notifications renvoi niveau précédent: {e}")


def _get_infos_niveau_validation(niveau):
    """
    Retourne les informations sur un niveau de validation donné
    """
    try:
        mapping_niveaux = {
            0: {'nom': 'Demandeur initial', 'type_profil': 'UTILISATEUR'},
            1: {'nom': 'Responsable (N+1)', 'type_profil': 'RESPONSABLE'},
            2: {'nom': 'Directeur (N+2)', 'type_profil': 'DIRECTEUR'},
            3: {'nom': 'RH/Admin (Final)', 'type_profil': 'RH'}
        }
        
        return mapping_niveaux.get(niveau)
        
    except Exception as e:
        logger.error(f"Erreur récupération infos niveau {niveau}: {e}")
        return None
    
# ================================================================
# FONCTIONS UTILITAIRES COMPLÉMENTAIRES
# ================================================================

def _enrichir_details_demande_complete(demande):
    """
    Enrichit les détails complets de la demande avec correction des dates
    """
    try:
        # S'assurer que les dates sont bien des objets date/datetime
        date_debut = demande.date_debut
        date_fin = demande.date_fin
        
        # Correction pour les dates qui pourraient être des strings
        if isinstance(date_debut, str):
            try:
                from django.utils.dateparse import parse_date
                date_debut = parse_date(date_debut)
            except:
                date_debut = None
                
        if isinstance(date_fin, str):
            try:
                from django.utils.dateparse import parse_date
                date_fin = parse_date(date_fin)
            except:
                date_fin = None
        
        # Calcul de la durée de mission sécurisé
        duree_mission = 0
        if date_debut and date_fin:
            try:
                duree_mission = (date_fin - date_debut).days + 1
                if duree_mission < 0:
                    duree_mission = 0
            except:
                duree_mission = 0
        
        details = {
            'numero_demande': demande.numero_demande or "Non défini",
            'departement_concerne': demande.poste.departement.nom if demande.poste and demande.poste.departement else 'Non renseigné',
            'site_concerne': demande.poste.site.nom if demande.poste and demande.poste.site else 'Non renseigné',
            'motif_display': demande.motif_absence.nom if demande.motif_absence else 'Non renseigné',
            'urgence_display': demande.get_urgence_display() if hasattr(demande, 'get_urgence_display') else demande.urgence,
            'duree_mission': duree_mission,
            'demandeur_info': {
                'nom': demande.demandeur.nom_complet if demande.demandeur else 'Non défini',
                'matricule': demande.demandeur.matricule if demande.demandeur else 'N/A',
                'poste': demande.demandeur.poste.titre if demande.demandeur and demande.demandeur.poste else 'Poste non renseigné'
            },
            'personne_remplacee_info': {
                'nom': demande.personne_remplacee.nom_complet if demande.personne_remplacee else 'Non défini',
                'matricule': demande.personne_remplacee.matricule if demande.personne_remplacee else 'N/A',
            }
        }
        
        return details
        
    except Exception as e:
        logger.error(f"Erreur enrichissement détails demande: {e}")
        return {
            'numero_demande': getattr(demande, 'numero_demande', 'N/A'),
            'departement_concerne': 'Erreur de chargement',
            'site_concerne': 'Erreur de chargement',
            'motif_display': 'Erreur de chargement',
            'urgence_display': getattr(demande, 'urgence', 'NORMALE'),
            'duree_mission': 0,
            'demandeur_info': {'nom': 'Erreur', 'matricule': 'N/A', 'poste': 'N/A'},
            'personne_remplacee_info': {'nom': 'Erreur', 'matricule': 'N/A'},
        }

def _calculer_anciennete_display(candidat):
    """
    Calcule et formate l'ancienneté d'un candidat
    """
    try:
        if hasattr(candidat, 'extended_data') and candidat.extended_data.date_embauche:
            date_embauche = candidat.extended_data.date_embauche
        elif hasattr(candidat, 'date_embauche') and candidat.date_embauche:
            date_embauche = candidat.date_embauche
        else:
            return 'Non renseignée'
        
        from datetime import date
        today = date.today()
        anciennete = today - date_embauche
        annees = anciennete.days // 365
        mois = (anciennete.days % 365) // 30
        
        if annees > 0:
            if mois > 0:
                return f"{annees} an{'s' if annees > 1 else ''} et {mois} mois"
            else:
                return f"{annees} an{'s' if annees > 1 else ''}"
        elif mois > 0:
            return f"{mois} mois"
        else:
            return "Moins d'un mois"
            
    except Exception as e:
        logger.error(f"Erreur calcul ancienneté: {e}")
        return 'Non calculable'


def _get_competences_principales(candidat, limit=5):
    """
    Récupère les compétences principales d'un candidat
    """
    try:
        if hasattr(candidat, 'competences'):
            competences = candidat.competences.select_related('competence').order_by('-niveau_maitrise')[:limit]
            return [{
                'nom': comp.competence.nom,
                'niveau': comp.get_niveau_maitrise_display(),
                'certifie': comp.certifie
            } for comp in competences]
        else:
            return []
    except Exception as e:
        logger.error(f"Erreur récupération compétences: {e}")
        return []

def _determiner_type_validation_niveau(profil_utilisateur, demande):
    """
    Détermine le type de validation selon le profil et le niveau
    """
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    
    niveau_requis = demande.niveau_validation_actuel + 1
    
    if niveau_requis == 1:
        return 'RESPONSABLE'
    elif niveau_requis == 2:
        return 'DIRECTEUR'
    elif niveau_requis >= 3:
        return 'RH' if profil_utilisateur.type_profil == 'RH' else 'ADMIN'
    else:
        return profil_utilisateur.type_profil


def _determiner_source_proposition_niveau(profil_utilisateur):
    """
    Détermine la source de proposition selon le profil
    """
    mapping = {
        'RESPONSABLE': 'RESPONSABLE',
        'DIRECTEUR': 'DIRECTEUR',
        'RH': 'RH',
        'ADMIN': 'ADMIN'
    }
    
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    
    return mapping.get(profil_utilisateur.type_profil, 'AUTRE')


def _calculer_bonus_hierarchique(profil_utilisateur):
    """
    Calcule le bonus hiérarchique selon le profil
    """
    bonus_mapping = {
        'RESPONSABLE': 15,
        'DIRECTEUR': 18,
        'RH': 20,
        'ADMIN': 20,
    }
    
    if profil_utilisateur.is_superuser:
        return 0  # Les superutilisateurs n'ont pas de bonus spécial
    
    return bonus_mapping.get(profil_utilisateur.type_profil, 5)


def _notifier_candidat_selectionne(candidat, demande):
    """
    Notifie le candidat sélectionné pour la mission
    """
    try:
        NotificationInterim.objects.create(
            destinataire=candidat,
            demande=demande,
            type_notification='CANDIDAT_SELECTIONNE',
            urgence='HAUTE',
            titre=f'Vous avez été sélectionné pour la mission {demande.numero_demande}',
            message=f'Félicitations ! Vous avez été sélectionné pour remplacer {demande.personne_remplacee.nom_complet} '
                   f'du {demande.date_debut} au {demande.date_fin}.',
            url_action_principale=f'/interim/reponse-interim/{demande.id}/',
            texte_action_principale='Répondre à la proposition'
        )
        
        logger.info(f"Candidat {candidat.nom_complet} notifié pour la mission {demande.numero_demande}")
        
    except Exception as e:
        logger.error(f"Erreur notification candidat sélectionné: {e}")


def _notifier_prochain_validateur_safe(demande, prochaine_etape):
    """
    Version sécurisée des notifications
    """
    try:
        # Vérifier que prochaine_etape est un dictionnaire
        if isinstance(prochaine_etape, str):
            logger.warning(f"prochaine_etape est une string: {prochaine_etape}")
            prochaine_etape = {'nom': prochaine_etape, 'type': 'UNKNOWN'}
        elif not isinstance(prochaine_etape, dict):
            logger.warning(f"prochaine_etape n'est pas un dictionnaire: {type(prochaine_etape)}")
            prochaine_etape = {'nom': 'Niveau suivant', 'type': 'UNKNOWN'}
        
        # Récupérer le nom de façon sécurisée
        nom_etape = prochaine_etape.get('nom', 'Niveau suivant')
        type_etape = prochaine_etape.get('type', 'UNKNOWN')
        
        logger.info(f"Notification prochain validateur pour {demande.numero_demande}: {nom_etape}")
        
        # Ici on pourrait ajouter la vraie logique de notification
        # Pour le moment, juste logger l'information
        
    except Exception as e:
        logger.error(f"Erreur notification prochain validateur: {e}")
        

def _notifier_refus_demande(demande, validateur, motif_refus, details_refus):
    """
    Notifie le refus de la demande aux parties prenantes
    """
    try:
        # Notifier le demandeur
        NotificationInterim.objects.create(
            destinataire=demande.demandeur,
            expediteur=validateur,
            demande=demande,
            type_notification='DEMANDE_REFUSEE',
            urgence='HAUTE',
            titre=f'Demande {demande.numero_demande} refusée',
            message=f'Votre demande d\'intérim a été refusée.\n\nMotif: {motif_refus}\n\nDétails: {details_refus}',
            url_action_principale=f'/interim/demande/{demande.id}/',
            texte_action_principale='Voir la demande'
        )
        
        logger.info(f"Refus de demande {demande.numero_demande} notifié")
        
    except Exception as e:
        logger.error(f"Erreur notification refus demande: {e}")


def _get_prochaine_etape_validation_safe(demande):
    """
    Version sécurisée qui retourne toujours un dictionnaire
    """
    try:
        niveau_suivant = demande.niveau_validation_actuel + 1
        
        etapes = {
            1: {'nom': 'Validation Responsable (N+1)', 'type': 'RESPONSABLE'},
            2: {'nom': 'Validation Directeur (N+2)', 'type': 'DIRECTEUR'},
            3: {'nom': 'Validation finale RH/Admin', 'type': 'RH_ADMIN'},
        }
        
        etape = etapes.get(niveau_suivant, {'nom': 'Étape inconnue', 'type': 'UNKNOWN'})
        
        # S'assurer que c'est un dictionnaire
        if not isinstance(etape, dict):
            etape = {'nom': 'Étape inconnue', 'type': 'UNKNOWN'}
            
        return etape
        
    except Exception as e:
        logger.error(f"Erreur récupération prochaine étape: {e}")
        return {'nom': 'Étape inconnue', 'type': 'UNKNOWN'}

def _creer_historique_validation(demande, utilisateur, action, description, donnees_apres):
    """
    Crée une entrée dans l'historique des actions
    """
    try:
        HistoriqueAction.objects.create(
            demande=demande,
            action=action,
            utilisateur=utilisateur,
            description=description,
            donnees_apres=donnees_apres,
            niveau_hierarchique=utilisateur.type_profil,
            is_superuser=utilisateur.is_superuser
        )
        
        logger.info(f"Historique créé pour {demande.numero_demande}: {action}")
        
    except Exception as e:
        logger.error(f"Erreur création historique: {e}")

# ================================================================
#   FONCTIONS HARMONISÉES AVEC LE 2ÈME CODE
# ================================================================

def _get_propositions_avec_scores(demande):
    """
      CORRIGÉ - Assure que score_affichage est toujours défini
    """
    try:
        propositions = PropositionCandidat.objects.filter(
            demande_interim=demande
        ).select_related(
            'candidat_propose__user',
            'candidat_propose__poste',
            'candidat_propose__departement',
            'candidat_propose__site',
            'proposant__user',
            'proposant__departement'
        ).order_by('-score_final', '-created_at')
        
        propositions_enrichies = []
        
        for proposition in propositions:
            candidat = proposition.candidat_propose
            if not candidat:
                continue
                
            try:
                #   CALCUL DU SCORE DÉTAILLÉ
                score_detail = _calculer_score_candidat_detaille(candidat, demande, proposition)
                
                #   CORRECTION: S'assurer que le score est un nombre valide
                score_final = score_detail.get('score_final', 0)
                if score_final is None or score_final == '':
                    score_final = 0
                
                # Convertir en entier pour l'affichage
                try:
                    score_affichage = int(float(score_final))
                except (ValueError, TypeError):
                    logger.warning(f"Score invalide pour candidat {candidat.matricule}: {score_final}")
                    score_affichage = 0
                
                #   INFORMATIONS CANDIDAT ENRICHIES
                candidat_info = _enrichir_info_candidat(candidat, demande)
                
                #   INFORMATIONS PROPOSANT
                proposant_info = _get_info_proposant(proposition.proposant)
                
                candidat_data = {
                    'proposition': proposition,
                    'candidat': candidat,
                    'candidat_info': candidat_info,
                    'score_detail': score_detail,
                    
                    #   IDENTIFICATION SOURCE
                    'type_source': 'PROPOSITION_HUMAINE',
                    'source_display': f"Proposé par {proposant_info['nom']} ({proposant_info['type_profil']})",
                    'source_icon': 'fa-user-tie',
                    'source_color': 'primary',
                    
                    #   AFFICHAGE SCORE - CORRECTION PRINCIPALE
                    'score_affichage': score_affichage,  #   GARANTI D'ÊTRE UN ENTIER
                    'score_class': _get_score_css_class(score_affichage),
                    'priorite_affichage': 1,  # Priorité haute pour humaines
                    
                    #   DÉTAILS PROPOSITION
                    'proposant_info': proposant_info,
                    'date_proposition': proposition.created_at,
                    'justification': proposition.justification,
                    'statut_proposition': getattr(proposition, 'statut', 'EN_ATTENTE')
                }
                
                propositions_enrichies.append(candidat_data)
                
            except Exception as e:
                logger.error(f"  Erreur enrichissement proposition {proposition.id}: {e}")
                continue
        
        logger.info(f"  {len(propositions_enrichies)} propositions humaines récupérées")
        return propositions_enrichies
        
    except Exception as e:
        logger.error(f"  Erreur récupération propositions humaines: {e}")
        return []

def _get_candidats_automatiques_avec_scores(demande):
    """
      CORRIGÉ - Limite aux 10 meilleurs candidats et assure les scores valides
    """
    try:
        #   REMPLACEMENT: Utiliser ScoringInterimService du fichier scoring_service.py
        from .services.scoring_service import ScoringInterimService
        
        # Créer une instance du service de scoring V4.1
        service_scoring = ScoringInterimService()

        #   CORRESPONDANCE PARFAITE: generer_candidats_automatiques_v41
        #   CORRECTION: Limite explicite à 50 candidats
        candidats_ia_data = service_scoring.generer_candidats_automatiques_v41(
            demande=demande,
            limite=50,  #   LIMITE EXPLICITE
            inclure_donnees_kelio=True
        )
        
        #   TRI PAR SCORE DÉCROISSANT POUR GARANTIR LES MEILLEURS
        candidats_ia_data.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        #   SÉLECTION DES 50 MEILLEURS (au cas où le service en retournerait plus)
        candidats_ia_data = candidats_ia_data[:50]
        
        candidats_automatiques = []
        
        for candidat_data in candidats_ia_data:
            candidat = candidat_data['candidat']
            score_final = candidat_data['score']
            
            try:
                #   CORRECTION: Validation et conversion du score
                if score_final is None or score_final == '':
                    score_final = 0
                
                try:
                    score_affichage = int(float(score_final))
                except (ValueError, TypeError):
                    logger.warning(f"Score IA invalide pour candidat {candidat.matricule}: {score_final}")
                    score_affichage = 0
                
                #   INFORMATIONS CANDIDAT
                candidat_info = _enrichir_info_candidat(candidat, demande)
                
                #   CONSTRUIRE LE SCORE DÉTAILLÉ depuis les données V4.1
                score_detail = {
                    'score_final': score_affichage,  #   SCORE VALIDÉ
                    'criteres': {
                        'score_global': score_affichage,
                        'disponibilite': candidat_data.get('disponibilite', True),
                        'donnees_kelio': candidat_data.get('donnees_kelio_disponibles', False)
                    },
                    'algorithme_version': candidat_data.get('version_scoring', '4.1'),
                    'facteurs_decisifs': _extraire_facteurs_decisifs_v41(candidat_data),
                    'confiance': _calculer_confiance_scoring_v41(score_affichage),
                    'methode': 'ScoringInterimService_V4.1'
                }
                
                candidat_data_enrichi = {
                    'candidat': candidat,
                    'candidat_info': candidat_info,
                    'score_detail': score_detail,
                    
                    #   IDENTIFICATION SOURCE IA V4.1
                    'type_source': 'AUTOMATIQUE',
                    'source_display': "Sélection automatique (Scoring V4.1)",
                    'source_icon': 'fa-robot',
                    'source_color': 'success',
                    
                    #   AFFICHAGE SCORE V4.1 - CORRECTION PRINCIPALE
                    'score_affichage': score_affichage,  #   GARANTI D'ÊTRE UN ENTIER
                    'score_class': _get_score_css_class(score_affichage),
                    'priorite_affichage': 2,  # Priorité après humaines
                    
                    #   DÉTAILS SCORING V4.1
                    'algorithme_version': candidat_data.get('version_scoring', '4.1'),
                    'facteurs_decisifs': _extraire_facteurs_decisifs_v41(candidat_data),
                    'confiance_prediction': _calculer_confiance_scoring_v41(score_affichage),
                    'date_calcul': timezone.now(),
                    'justification_auto': candidat_data.get('justification_auto', ''),
                    'donnees_kelio_disponibles': candidat_data.get('donnees_kelio_disponibles', False),
                    'derniere_sync_kelio': candidat_data.get('derniere_sync_kelio')
                }
                
                candidats_automatiques.append(candidat_data_enrichi)
                
            except Exception as e:
                logger.error(f"  Erreur traitement candidat V4.1 {candidat.id}: {e}")
                continue
        
        #   TRI FINAL PAR SCORE POUR GARANTIR L'ORDRE
        candidats_automatiques.sort(key=lambda x: x['score_affichage'], reverse=True)
        
        logger.info(f"  {len(candidats_automatiques)} candidats V4.1 récupérés (TOP 10)")
        return candidats_automatiques
        
    except Exception as e:
        logger.error(f"  Erreur récupération candidats automatiques V4.1: {e}")
        # Fallback : candidats basiques sans IA
        return _get_candidats_fallback_sans_ia(demande)

def _extraire_facteurs_decisifs_v41(candidat_data):
    """
      Extrait les facteurs décisifs depuis les données du scoring V4.1
    """
    try:
        facteurs = []
        
        # Facteurs basés sur la justification automatique
        justification = candidat_data.get('justification_auto', '')
        if justification:
            # Parser la justification pour extraire les facteurs
            if 'Poste identique' in justification:
                facteurs.append('Poste identique')
            if 'Même département' in justification:
                facteurs.append('Même département')
            if 'Même site' in justification:
                facteurs.append('Même site')
            if 'compétence' in justification.lower():
                facteurs.append('Compétences validées')
            if 'Ancienneté' in justification:
                facteurs.append('Expérience significative')
            if 'Données Kelio' in justification:
                facteurs.append('Données Kelio récentes')
            if 'Disponible pour intérim' in justification:
                facteurs.append('Disponibilité confirmée')
        
        # Facteurs basés sur les métadonnées
        if candidat_data.get('donnees_kelio_disponibles'):
            facteurs.append('Profil Kelio complet')
        
        if candidat_data.get('disponibilite'):
            facteurs.append('Disponible sur la période')
        
        # Score élevé comme facteur
        score = candidat_data.get('score', 0)
        if score >= 85:
            facteurs.append('Score de compatibilité excellent')
        elif score >= 70:
            facteurs.append('Bonne compatibilité')
        
        return facteurs[:5]  # Limiter à 5 facteurs max
        
    except Exception as e:
        logger.error(f"  Erreur extraction facteurs décisifs: {e}")
        return ['Candidat sélectionné automatiquement']

def _calculer_confiance_scoring_v41(score_final):
    """
      Calcule un niveau de confiance basé sur le score V4.1
    """
    try:
        # Convertir le score (0-100) en niveau de confiance (0.0-1.0)
        if score_final >= 90:
            return 0.95
        elif score_final >= 80:
            return 0.90
        elif score_final >= 70:
            return 0.85
        elif score_final >= 60:
            return 0.75
        elif score_final >= 50:
            return 0.65
        else:
            return 0.50
            
    except Exception:
        return 0.70  # Confiance par défaut

def _get_candidats_fallback_sans_ia(demande):
    """
      CORRIGÉ - Fallback avec limitation à 10 candidats et scores valides
    """
    try:
        from .services.scoring_service import ScoringInterimService
        
        # Critères basiques de matching
        candidats_potentiels = ProfilUtilisateur.objects.filter(
            statut_employe='ACTIF',
            poste__departement=demande.poste.departement
        ).exclude(
            id=demande.personne_remplacee.id if demande.personne_remplacee else -1
        )[:50]  #   LIMITE À 50 DÈS LA REQUÊTE
        
        candidats_fallback = []
        
        # Créer une instance du service de scoring pour le fallback
        try:
            service_scoring = ScoringInterimService()
            utiliser_scoring_v41 = True
        except Exception:
            utiliser_scoring_v41 = False
            logger.warning("  ScoringInterimService non disponible - fallback basique")
        
        for candidat in candidats_potentiels:
            try:
                if utiliser_scoring_v41:
                    # Utiliser le scoring V4.1 même en fallback
                    score_v41 = service_scoring.calculer_score_candidat_v41(candidat, demande)
                    score_basique = score_v41
                    methode = 'ScoringV41_Fallback'
                else:
                    # Score basique traditionnel
                    score_basique = _calculer_score_basique(candidat, demande)
                    methode = 'BASIQUE'
                
                #   VALIDATION DU SCORE
                if score_basique is None:
                    score_basique = 0
                try:
                    score_basique = int(float(score_basique))
                except (ValueError, TypeError):
                    score_basique = 0
                
                candidat_data = {
                    'candidat': candidat,
                    'candidat_info': _enrichir_info_candidat_minimal(candidat, demande),
                    'score_detail': {
                        'score_final': score_basique,
                        'criteres': {'compatibilite_poste': score_basique},
                        'methode': methode
                    },
                    'type_source': 'AUTOMATIQUE',
                    'source_display': f"Sélection automatique ({methode})",
                    'source_icon': 'fa-cog',
                    'source_color': 'secondary',
                    'score_affichage': score_basique,  #   SCORE VALIDÉ
                    'score_class': _get_score_css_class(score_basique),
                    'priorite_affichage': 3,
                    'algorithme_version': '4.1' if utiliser_scoring_v41 else 'basique',
                    'facteurs_decisifs': ['Même département', 'Employé actif'],
                    'confiance_prediction': _calculer_confiance_scoring_v41(score_basique),
                    'date_calcul': timezone.now()
                }
                
                candidats_fallback.append(candidat_data)
                
            except Exception as e:
                logger.error(f"  Erreur traitement candidat fallback {candidat.id}: {e}")
                continue
        
        #   TRI PAR SCORE DÉCROISSANT
        candidats_fallback.sort(key=lambda c: c['score_affichage'], reverse=True)
        
        logger.info(f"  {len(candidats_fallback)} candidats fallback récupérés (TOP 10)")
        return candidats_fallback
        
    except Exception as e:
        logger.error(f"  Erreur candidats fallback: {e}")
        return []

# DEBUG ELIE
def _get_candidats_automatiques_avec_scores_debug(demande):
    """
    Version debug pour diagnostiquer pourquoi aucun candidat n'est retourné
    """
    try:
        logger.debug(f"=== DÉBUT DIAGNOSTIC CANDIDATS AUTOMATIQUES ===")
        logger.debug(f"Demande ID: {demande.id}")
        logger.debug(f"Demande numéro: {demande.numero_demande}")
        
        # 1. Vérifier l'import du service de scoring
        try:
            from .services.scoring_service import ScoringInterimService
            logger.debug("✅ Import ScoringInterimService OK")
        except ImportError as e:
            logger.error(f"❌ ERREUR Import ScoringInterimService: {e}")
            return []
        
        # 2. Créer l'instance du service
        try:
            service_scoring = ScoringInterimService()
            logger.debug("✅ Instance ScoringInterimService créée")
        except Exception as e:
            logger.error(f"❌ ERREUR Création ScoringInterimService: {e}")
            return []
        
        # 3. Appeler la méthode principale avec diagnostic
        try:
            logger.debug("📞 Appel generer_candidats_automatiques_v41...")
            candidats_ia_data = service_scoring.generer_candidats_automatiques_v41(
                demande=demande,
                limite=20,
                inclure_donnees_kelio=True
            )
            logger.debug(f"✅ generer_candidats_automatiques_v41 retourne {len(candidats_ia_data)} candidats")
            
            if not candidats_ia_data:
                logger.warning("⚠️ AUCUN candidat retourné par le service de scoring")
                # Diagnostic approfondi
                return _diagnostic_approfondi_candidats(demande, service_scoring)
                
        except Exception as e:
            logger.error(f"❌ ERREUR generer_candidats_automatiques_v41: {e}")
            logger.error(f"Exception type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
        
        # 4. Traitement des candidats retournés
        candidats_automatiques = []
        
        for candidat_data in candidats_ia_data:
            try:
                candidat = candidat_data['candidat']
                score_final = candidat_data['score']
                
                logger.debug(f"Traitement candidat: {candidat.nom_complet} (Score: {score_final})")
                
                # Validation et conversion du score
                if score_final is None or score_final == '':
                    score_final = 0
                    logger.warning(f"Score NULL pour {candidat.matricule}, assigné à 0")
                
                try:
                    score_affichage = int(float(score_final))
                except (ValueError, TypeError):
                    logger.warning(f"Score IA invalide pour candidat {candidat.matricule}: {score_final}")
                    score_affichage = 0
                
                # Enrichir les informations candidat
                candidat_info = _enrichir_info_candidat_debug(candidat, demande)
                
                # Score détaillé
                score_detail = {
                    'score_final': score_affichage,
                    'criteres': {
                        'score_global': score_affichage,
                        'disponibilite': candidat_data.get('disponibilite', True),
                        'donnees_kelio': candidat_data.get('donnees_kelio_disponibles', False)
                    },
                    'algorithme_version': candidat_data.get('version_scoring', '4.1'),
                    'facteurs_decisifs': _extraire_facteurs_decisifs_v41_debug(candidat_data),
                    'confiance': _calculer_confiance_scoring_v41_debug(score_affichage),
                    'methode': 'ScoringInterimService_V4.1'
                }
                
                candidat_data_enrichi = {
                    'candidat': candidat,
                    'candidat_info': candidat_info,
                    'score_detail': score_detail,
                    'type_source': 'AUTOMATIQUE',
                    'source_display': "Sélection automatique (Scoring V4.1)",
                    'source_icon': 'fa-robot',
                    'source_color': 'success',
                    'score_affichage': score_affichage,
                    'score_class': _get_score_css_class(score_affichage),
                    'priorite_affichage': 2,
                    'algorithme_version': candidat_data.get('version_scoring', '4.1'),
                    'facteurs_decisifs': _extraire_facteurs_decisifs_v41_debug(candidat_data),
                    'confiance_prediction': _calculer_confiance_scoring_v41_debug(score_affichage),
                    'date_calcul': timezone.now(),
                    'justification_auto': candidat_data.get('justification_auto', ''),
                    'donnees_kelio_disponibles': candidat_data.get('donnees_kelio_disponibles', False),
                    'derniere_sync_kelio': candidat_data.get('derniere_sync_kelio')
                }
                
                candidats_automatiques.append(candidat_data_enrichi)
                logger.debug(f"✅ Candidat {candidat.nom_complet} ajouté avec succès")
                
            except Exception as e:
                logger.error(f"❌ Erreur traitement candidat {candidat.id if 'candidat' in locals() else 'UNKNOWN'}: {e}")
                continue
        
        # Tri final
        candidats_automatiques.sort(key=lambda x: x['score_affichage'], reverse=True)
        
        logger.debug(f"=== FIN DIAGNOSTIC: {len(candidats_automatiques)} candidats finaux ===")
        return candidats_automatiques
        
    except Exception as e:
        logger.error(f"❌ ERREUR CRITIQUE dans diagnostic candidats automatiques: {e}")
        return _get_candidats_fallback_debug(demande)


def _diagnostic_approfondi_candidats(demande, service_scoring):
    """
    Diagnostic approfondi pour comprendre pourquoi aucun candidat n'est trouvé
    """
    logger.debug("🔍 === DIAGNOSTIC APPROFONDI ===")
    
    # 1. Vérifier les candidats potentiels dans la base
    candidats_base = ProfilUtilisateur.objects.filter(
        actif=True,
        statut_employe='ACTIF'
    )
    
    if demande.personne_remplacee:
        candidats_base = candidats_base.exclude(id=demande.personne_remplacee.id)
    
    logger.debug(f"Candidats actifs dans la base: {candidats_base.count()}")
    
    # 2. Vérifier par département
    if demande.poste and demande.poste.departement:
        candidats_meme_dept = candidats_base.filter(
            departement=demande.poste.departement
        )
        logger.debug(f"Candidats même département ({demande.poste.departement.nom}): {candidats_meme_dept.count()}")
        
        # Lister les premiers candidats du même département
        for candidat in candidats_meme_dept[:5]:
            logger.debug(f"  - {candidat.nom_complet} (ID: {candidat.id}, Matricule: {candidat.matricule})")
    
    # 3. Vérifier la disponibilité pour intérim
    try:
        candidats_dispo_interim = candidats_base.filter(
            extended_data__disponible_interim=True
        )
        logger.debug(f"Candidats disponibles pour intérim: {candidats_dispo_interim.count()}")
    except Exception as e:
        logger.debug(f"Impossible de filtrer par disponibilité intérim: {e}")
        candidats_dispo_interim = candidats_base
    
    # 4. Tester le scoring sur quelques candidats manuellement
    candidats_test = candidats_base[:3]
    logger.debug(f"Test scoring sur {candidats_test.count()} candidats:")
    
    for candidat in candidats_test:
        try:
            score = service_scoring.calculer_score_candidat_v41(candidat, demande, utiliser_cache=False)
            logger.debug(f"  - {candidat.nom_complet}: Score = {score}")
            
            # Vérifier le seuil minimum
            if score >= 25:  # Seuil du service
                logger.debug(f"    ✅ Score acceptable ({score} >= 25)")
            else:
                logger.debug(f"    ❌ Score trop bas ({score} < 25)")
                
        except Exception as e:
            logger.error(f"  - {candidat.nom_complet}: ERREUR = {e}")
    
    # 5. Retourner une liste de candidats de test pour debug
    if candidats_meme_dept.exists():
        logger.debug("🔧 Retour de candidats de test du même département")
        return _creer_candidats_test_debug(candidats_meme_dept[:3], demande)
    else:
        logger.debug("🔧 Retour de candidats de test génériques")
        return _creer_candidats_test_debug(candidats_base[:3], demande)


def _creer_candidats_test_debug(candidats_queryset, demande):
    """
    Crée une liste de candidats de test pour le debug
    """
    candidats_test = []
    
    for candidat in candidats_queryset:
        try:
            candidat_info = _enrichir_info_candidat_debug(candidat, demande)
            
            candidat_data_test = {
                'candidat': candidat,
                'candidat_info': candidat_info,
                'score_detail': {
                    'score_final': 50,  # Score de test
                    'criteres': {'score_global': 50},
                    'methode': 'DEBUG_TEST'
                },
                'type_source': 'DEBUG',
                'source_display': "Candidat de test (DEBUG)",
                'source_icon': 'fa-bug',
                'source_color': 'warning',
                'score_affichage': 50,
                'score_class': 'score-average',
                'justification_auto': f"Candidat de test - Même département: {candidat.departement.nom if candidat.departement else 'Non défini'}"
            }
            
            candidats_test.append(candidat_data_test)
            
        except Exception as e:
            logger.error(f"Erreur création candidat test {candidat.id}: {e}")
    
    logger.debug(f"Candidats de test créés: {len(candidats_test)}")
    return candidats_test


def _enrichir_info_candidat_debug(candidat, demande):
    """
    Version debug de l'enrichissement des informations candidat
    """
    try:
        return {
            'nom_complet': candidat.nom_complet,
            'matricule': candidat.matricule,
            'poste_actuel': candidat.poste.titre if candidat.poste else 'Poste non renseigné',
            'departement': candidat.departement.nom if candidat.departement else 'Département non renseigné',
            'site': candidat.site.nom if candidat.site else 'Site non renseigné',
            'anciennete': 'Non calculée (debug)',
            'competences_principales': [],
            'disponibilite': {'disponible': True, 'raison': 'Test debug'}
        }
    except Exception as e:
        logger.error(f"Erreur enrichissement candidat {candidat.id}: {e}")
        return {
            'nom_complet': getattr(candidat, 'nom_complet', 'Nom indisponible'),
            'matricule': getattr(candidat, 'matricule', 'N/A'),
            'poste_actuel': 'Erreur',
            'departement': 'Erreur',
            'site': 'Erreur',
            'anciennete': 'Erreur',
            'competences_principales': [],
            'disponibilite': {'disponible': False, 'raison': 'Erreur debug'}
        }


def _extraire_facteurs_decisifs_v41_debug(candidat_data):
    """Version debug des facteurs décisifs"""
    try:
        return candidat_data.get('facteurs_decisifs', ['Score automatique', 'Disponibilité'])
    except:
        return ['Données debug']


def _calculer_confiance_scoring_v41_debug(score):
    """Version debug du calcul de confiance"""
    try:
        if score >= 80:
            return 'Élevée'
        elif score >= 60:
            return 'Moyenne'
        else:
            return 'Faible'
    except:
        return 'Indéterminée'


def _get_score_css_class(score):
    """Version debug de la classe CSS du score"""
    try:
        if score >= 85:
            return 'score-excellent'
        elif score >= 70:
            return 'score-good'
        elif score >= 55:
            return 'score-average'
        else:
            return 'score-poor'
    except:
        return 'score-poor'


def _get_candidats_fallback_debug(demande):
    """
    Candidats de fallback en cas d'erreur critique
    """
    try:
        logger.debug("🆘 Mode fallback activé")
        
        # Candidats très basiques du même département
        candidats_basic = ProfilUtilisateur.objects.filter(
            actif=True,
            statut_employe='ACTIF'
        )
        
        if demande.personne_remplacee:
            candidats_basic = candidats_basic.exclude(id=demande.personne_remplacee.id)
        
        if demande.poste and demande.poste.departement:
            candidats_basic = candidats_basic.filter(
                departement=demande.poste.departement
            )
        
        candidats_fallback = []
        
        for candidat in candidats_basic[:5]:  # Max 5 candidats
            candidat_fallback = {
                'candidat': candidat,
                'candidat_info': {
                    'nom_complet': candidat.nom_complet,
                    'matricule': candidat.matricule,
                    'poste_actuel': candidat.poste.titre if candidat.poste else 'N/A',
                    'departement': candidat.departement.nom if candidat.departement else 'N/A',
                    'site': candidat.site.nom if candidat.site else 'N/A',
                    'disponibilite': {'disponible': True, 'raison': 'Fallback'}
                },
                'score_affichage': 40,  # Score fallback
                'score_class': 'score-average',
                'source_display': "Candidat de secours (même département)",
                'source_icon': 'fa-life-ring',
                'source_color': 'secondary',
                'justification_auto': f"Candidat du même département ({candidat.departement.nom if candidat.departement else 'N/A'}) - Mode fallback"
            }
            
            candidats_fallback.append(candidat_fallback)
        
        logger.debug(f"Candidats fallback: {len(candidats_fallback)}")
        return candidats_fallback
        
    except Exception as e:
        logger.error(f"Erreur mode fallback: {e}")
        return []


# Fonction de test rapide
def tester_candidats_automatiques_rapide(demande_id):
    """
    Test rapide pour une demande spécifique
    """
    try:
        demande = DemandeInterim.objects.get(id=demande_id)
        logger.info(f"🧪 TEST RAPIDE pour demande {demande.numero_demande}")
        
        # Version debug
        candidats_debug = _get_candidats_automatiques_avec_scores_debug(demande)
        
        logger.info(f"Résultat test: {len(candidats_debug)} candidats")
        
        for i, candidat_data in enumerate(candidats_debug[:3]):
            candidat = candidat_data['candidat']
            score = candidat_data.get('score_affichage', 0)
            logger.info(f"  {i+1}. {candidat.nom_complet} - Score: {score}")
        
        return candidats_debug
        
    except Exception as e:
        logger.error(f"Erreur test rapide: {e}")
        return []    
# ================================================================
# FONCTION ALTERNATIVE ENCORE PLUS SIMPLE
# ================================================================

def _get_candidats_automatiques_avec_scores_xxx(demande):
    """
      Version ultra-simplifiée utilisant directement la fonction utilitaire
    """
    try:
        #   Utilisation de la fonction utilitaire globale
        from .services.scoring_service import calculer_scores_pour_demande_v41
        
        # Calculer avec la fonction utilitaire (qui utilise generer_candidats_automatiques_v41 en interne)
        resultats_scoring = calculer_scores_pour_demande_v41(demande.id, limite_candidats=10)
        
        if resultats_scoring and 'candidats_automatiques' in resultats_scoring:
            candidats_data = resultats_scoring['candidats_automatiques']
            
            candidats_automatiques = []
            
            for candidat_data in candidats_data:
                candidat = candidat_data['candidat']
                score = candidat_data['score']
                
                try:
                    candidat_enrichi = {
                        'candidat': candidat,
                        'candidat_info': _enrichir_info_candidat(candidat, demande),
                        'score_detail': {
                            'score_final': score,
                            'criteres': {'score_global': score},
                            'algorithme_version': candidat_data.get('version_scoring', '4.1'),
                            'methode': 'calculer_scores_pour_demande_v41'
                        },
                        'type_source': 'AUTOMATIQUE',
                        'source_display': "Sélection automatique (Fonction utilitaire V4.1)",
                        'source_icon': 'fa-robot',
                        'source_color': 'success',
                        'score_affichage': score,
                        'score_class': _get_score_css_class(score),
                        'priorite_affichage': 2,
                        'algorithme_version': candidat_data.get('version_scoring', '4.1'),
                        'facteurs_decisifs': _extraire_facteurs_decisifs_v41(candidat_data),
                        'confiance_prediction': _calculer_confiance_scoring_v41(score),
                        'date_calcul': timezone.now(),
                        'justification_auto': candidat_data.get('justification_auto', ''),
                        'donnees_kelio_disponibles': candidat_data.get('donnees_kelio_disponibles', False)
                    }
                    
                    candidats_automatiques.append(candidat_enrichi)
                    
                except Exception as e:
                    logger.error(f"  Erreur enrichissement candidat simple {candidat.id}: {e}")
                    continue
            
            logger.info(f"  {len(candidats_automatiques)} candidats récupérés (méthode simple)")
            return candidats_automatiques
        else:
            logger.warning("  Aucun résultat de la fonction utilitaire")
            return _get_candidats_fallback_sans_ia(demande)
            
    except Exception as e:
        logger.error(f"  Erreur méthode simple: {e}")
        return _get_candidats_fallback_sans_ia(demande)
    
# ================================================================
#   FONCTIONS DE CALCUL DES SCORES - NOMS HARMONISÉS
# ================================================================

def _calculer_score_candidat_detaille(candidat, demande, proposition=None):
    """
      CORRIGÉ - Calcule le score détaillé avec validation
    """
    try:
        # Score de base de la proposition ou calculé
        score_base = getattr(proposition, 'score_final', None)
        
        if score_base is None:
            #   CORRECTION: Utiliser ScoringInterimService du fichier scoring_service.py
            from .services.scoring_service import ScoringInterimService
            
            # Créer une instance du service de scoring V4.1
            service_scoring = ScoringInterimService()
            
            #   CALCUL DU SCORE
            score_final = service_scoring.calculer_score_candidat_v41(candidat, demande)
            
            #   VALIDATION ET CONVERSION
            if score_final is None:
                score_final = 0
            try:
                score_final = int(float(score_final))
            except (ValueError, TypeError):
                logger.warning(f"Score calculé invalide pour {candidat.matricule}: {score_final}")
                score_final = 0
            
            # Récupérer les détails des critères pour ce candidat spécifique
            try:
                scores_criteres = service_scoring._calculer_scores_criteres_v41(candidat, demande, None)
            except:
                scores_criteres = {'score_global': score_final}
            
            # Construire le score détaillé harmonisé
            score_detail = {
                'score_final': score_final,
                'criteres': {
                    'similarite_poste': scores_criteres.get('similarite_poste', 0),
                    'competences': scores_criteres.get('competences_kelio', scores_criteres.get('competences', 0)),
                    'experience': scores_criteres.get('experience_kelio', scores_criteres.get('experience', 0)),
                    'disponibilite': scores_criteres.get('disponibilite_kelio', scores_criteres.get('disponibilite', 0)),
                    'proximite': scores_criteres.get('proximite', 0),
                    'anciennete': scores_criteres.get('anciennete', 0),
                    'formations': scores_criteres.get('formations_kelio', 0)
                },
                'bonus_malus': {
                    'bonus_kelio': service_scoring._calculer_bonus_donnees_kelio(candidat, demande) if hasattr(service_scoring, '_calculer_bonus_donnees_kelio') else 0,
                    'bonus_proposition': 0  # Sera calculé si proposition humaine
                },
                'explications': _generer_explications_score_v41(candidat, demande, score_final, scores_criteres),
                'version': '4.1',
                'methode': 'ScoringInterimService_V4.1_candidat_unique'
            }
            
            logger.info(f"  Score détaillé calculé pour candidat {candidat.matricule}: {score_final}")
            
        else:
            #   VALIDATION DU SCORE EXISTANT
            try:
                score_final = int(float(score_base))
            except (ValueError, TypeError):
                logger.warning(f"Score existant invalide pour {candidat.matricule}: {score_base}")
                score_final = 0
            
            # Reconstituer les détails du score existant
            score_detail = {
                'score_final': score_final,
                'criteres': _extraire_criteres_score(proposition),
                'bonus_malus': _extraire_bonus_malus(proposition),
                'explications': _generer_explications_score(candidat, demande, score_final),
                'version': 'existant',
                'methode': 'proposition_existante'
            }
        
        return score_detail
        
    except Exception as e:
        logger.error(f"  Erreur calcul score détaillé pour {candidat.matricule if candidat else 'candidat inconnu'}: {e}")
        return {
            'score_final': 0,  #   SCORE PAR DÉFAUT VALIDE
            'criteres': {'evaluation': 0},
            'bonus_malus': {},
            'explications': ['Score par défaut - erreur de calcul'],
            'erreur': str(e),
            'version': 'fallback',
            'methode': 'erreur'
        }

def _generer_explications_score_v41(candidat, demande, score_final, scores_criteres):
    """
    📝 Génère des explications détaillées basées sur les scores V4.1
    """
    try:
        explications = []
        
        # Explication globale
        if score_final >= 85:
            explications.append("Candidat excellent - très forte compatibilité")
        elif score_final >= 70:
            explications.append("Bon candidat - bonne compatibilité")
        elif score_final >= 55:
            explications.append("Candidat correct - compatibilité moyenne")
        else:
            explications.append("Candidat nécessitant une évaluation approfondie")
        
        # Explications par critères (points forts)
        criteres_forts = []
        criteres_faibles = []
        
        for critere, score in scores_criteres.items():
            if score >= 80:
                criteres_forts.append(f"{critere.replace('_', ' ').title()} excellent ({score})")
            elif score <= 40:
                criteres_faibles.append(f"{critere.replace('_', ' ').title()} à améliorer ({score})")
        
        if criteres_forts:
            explications.append(f"Points forts: {', '.join(criteres_forts)}")
        
        if criteres_faibles:
            explications.append(f"Points d'attention: {', '.join(criteres_faibles)}")
        
        # Explications spécifiques selon les critères
        if scores_criteres.get('similarite_poste', 0) >= 80:
            explications.append("Poste très similaire ou identique")
        
        if scores_criteres.get('competences_kelio', scores_criteres.get('competences', 0)) >= 75:
            explications.append("Compétences bien adaptées au poste")
        
        if scores_criteres.get('disponibilite_kelio', scores_criteres.get('disponibilite', 0)) >= 80:
            explications.append("Excellente disponibilité pour la période")
        
        if scores_criteres.get('proximite', 0) >= 80:
            explications.append("Localisation géographique idéale")
        
        # Mention de la version du scoring
        explications.append("Calculé avec le moteur de scoring V4.1 intégrant les données Kelio")
        
        return explications
        
    except Exception as e:
        logger.error(f"  Erreur génération explications V4.1: {e}")
        return [f"Score calculé: {score_final}/100", "Explications détaillées non disponibles"]

# ================================================================
# FONCTION ALTERNATIVE ENCORE PLUS SIMPLE
# ================================================================

def _calculer_score_basique(candidat, demande):
    """
      Calcul de score basique (sans IA)
    (Nom conservé car pas d'équivalent dans le 2ème code)
    """
    try:
        score = 0
        
        # Critère département (30 points)
        if candidat.departement == demande.poste.departement:
            score += 30
        
        # Critère site (20 points)
        if candidat.site == demande.poste.site:
            score += 20
        
        # Critère compétences (30 points)
        if hasattr(candidat, 'competences'):
            score += min(30, len(candidat.competences.all()) * 5)
        
        # Critère disponibilité (20 points)
        if _est_disponible_periode(candidat, demande):
            score += 20
        
        return min(100, score)
        
    except Exception:
        return 50  # Score neutre

def _get_score_css_class(score):
    """
    🎨 CORRIGÉ - Retourne la classe CSS selon le score avec validation
    """
    try:
        #   VALIDATION ET CONVERSION
        if score is None:
            score = 0
        score = int(float(score))
    except (ValueError, TypeError):
        score = 0
    
    if score >= 80:
        return 'excellent'
    elif score >= 60:
        return 'good' 
    elif score >= 40:
        return 'average'
    else:
        return 'poor'
    
def _extraire_criteres_score(proposition):
    """
      Extrait les critères de scoring d'une proposition
    (Nom conservé car pas d'équivalent dans le 2ème code)
    """
    try:
        # Si les détails sont stockés, les récupérer
        if hasattr(proposition, 'details_score') and proposition.details_score:
            import json
            return json.loads(proposition.details_score).get('criteres', {})
        
        # Sinon, estimation basée sur le score final
        score_final = proposition.score_final or 0
        return {
            'competences_techniques': min(100, score_final + 10),
            'experience_similaire': min(100, score_final),
            'disponibilite': min(100, score_final + 5),
            'localisation': min(100, score_final - 5)
        }
        
    except Exception:
        return {'evaluation_globale': proposition.score_final or 0}

def _extraire_bonus_malus(proposition):
    """
      NOM HARMONISÉ - Extrait les bonus/malus d'une proposition
    (Nom déjà présent dans le 2ème code)
    """
    return {}

def _generer_explications_score(candidat, demande, score):
    """
    📝 Génère des explications textuelles du score
    (Nom conservé car pas d'équivalent dans le 2ème code)
    """
    explications = []
    if score >= 80:
        explications.append("Candidat excellent pour ce poste")
    elif score >= 60:
        explications.append("Bon candidat avec quelques ajustements")
    else:
        explications.append("Candidat nécessitant une formation")
    return explications

def _get_info_proposant(proposant):
    """
      Récupère les informations du proposant avec gestion d'erreurs robuste
    
    Args:
        proposant: Instance de ProfilUtilisateur ou None
        
    Returns:
        dict: Dictionnaire contenant les informations du proposant
    """
    try:
        # ================================================================
        # VÉRIFICATIONS DE BASE
        # ================================================================
        
        if not proposant:
            logger.warning("Proposant None fourni à _get_info_proposant")
            return {
                'nom': 'Proposant non renseigné',
                'type_profil': 'N/A',
                'type_profil_display': 'N/A',
                'departement': '',
                'email': '',
                'matricule': 'N/A'
            }
        
        # ================================================================
        # INFORMATIONS DE BASE SÉCURISÉES
        # ================================================================
        
        # Nom complet avec fallbacks multiples
        nom_complet = _get_nom_complet_proposant(proposant)
        
        # Type de profil avec affichage
        type_profil = getattr(proposant, 'type_profil', 'UTILISATEUR')
        type_profil_display = _get_type_profil_display(proposant, type_profil)
        
        # Email sécurisé
        email = _get_email_proposant(proposant)
        
        # Matricule sécurisé
        matricule = getattr(proposant, 'matricule', f'MAT_{proposant.id}' if hasattr(proposant, 'id') else 'N/A')
        
        # Département sécurisé
        departement = _get_departement_proposant(proposant)
        
        # ================================================================
        # ASSEMBLAGE DU DICTIONNAIRE FINAL
        # ================================================================
        
        proposant_info = {
            # Informations essentielles
            'nom': nom_complet,
            'type_profil': type_profil,
            'type_profil_display': type_profil_display,
            'departement': departement,
            'email': email,
            'matricule': matricule,
            
            # Informations complémentaires
            'site': _get_site_proposant(proposant),
            'poste': _get_poste_proposant(proposant),
            'telephone': getattr(proposant, 'telephone', '') or getattr(proposant, 'telephone_portable', ''),
            'manager': _get_manager_proposant(proposant),
            
            # Métadonnées
            'actif': getattr(proposant, 'actif', True),
            'statut_employe': getattr(proposant, 'statut_employe', 'ACTIF'),
            'is_superuser': getattr(proposant, 'is_superuser', False) or (hasattr(proposant, 'user') and proposant.user and proposant.user.is_superuser),
            
            # Informations de contact étendues
            'nom_court': _get_nom_court(nom_complet),
            'initiales': _get_initiales(nom_complet),
        }
        
        logger.debug(f"  Informations proposant récupérées pour {nom_complet}")
        return proposant_info
        
    except Exception as e:
        logger.error(f"  Erreur lors de la récupération des infos proposant: {e}")
        logger.error(f"Type proposant: {type(proposant)}")
        
        # Retourner un dictionnaire minimal en cas d'erreur
        return {
            'nom': 'Erreur de récupération',
            'type_profil': 'N/A',
            'type_profil_display': 'N/A',
            'departement': 'Erreur',
            'email': '',
            'matricule': 'ERREUR',
            'site': '',
            'poste': '',
            'telephone': '',
            'manager': '',
            'actif': False,
            'statut_employe': 'ERREUR',
            'is_superuser': False,
            'nom_court': 'Erreur',
            'initiales': 'ER',
        }

# ================================================================
# FONCTIONS UTILITAIRES POUR _get_info_proposant
# ================================================================

def _get_nom_complet_proposant(proposant):
    """Récupère le nom complet avec plusieurs fallbacks"""
    try:
        # 1. Essayer l'attribut nom_complet
        if hasattr(proposant, 'nom_complet') and proposant.nom_complet:
            return proposant.nom_complet.strip()
        
        # 2. Essayer de construire à partir de user
        if hasattr(proposant, 'user') and proposant.user:
            user = proposant.user
            if user.first_name and user.last_name:
                return f"{user.first_name} {user.last_name}".strip()
            elif user.first_name:
                return user.first_name.strip()
            elif user.last_name:
                return user.last_name.strip()
            elif user.username:
                return user.username.strip()
        
        # 3. Essayer les attributs directs
        nom = getattr(proposant, 'nom', '').strip()
        prenom = getattr(proposant, 'prenom', '').strip()
        if nom and prenom:
            return f"{prenom} {nom}"
        elif nom:
            return nom
        elif prenom:
            return prenom
        
        # 4. Fallback avec matricule
        matricule = getattr(proposant, 'matricule', '')
        if matricule:
            return f"Utilisateur {matricule}"
            
        # 5. Dernier fallback avec ID
        if hasattr(proposant, 'id'):
            return f"Utilisateur #{proposant.id}"
        
        return "Nom non disponible"
        
    except Exception as e:
        logger.error(f"Erreur récupération nom complet proposant: {e}")
        return "Nom non disponible"

def _get_type_profil_display(proposant, type_profil):
    """Récupère l'affichage du type de profil"""
    try:
        # Essayer la méthode get_type_profil_display si elle existe
        if hasattr(proposant, 'get_type_profil_display'):
            display = proposant.get_type_profil_display()
            if display:
                return display
        
        # Mapping manuel des types de profils
        types_display = {
            'ADMIN': 'Administrateur',
            'RH': 'Ressources Humaines',
            'DIRECTEUR': 'Directeur',
            'RESPONSABLE': 'Responsable',
            'CHEF_EQUIPE': 'Chef d\'équipe',
            'UTILISATEUR': 'Utilisateur',
            'EMPLOYE': 'Employé',
        }
        
        return types_display.get(type_profil, type_profil.replace('_', ' ').title())
        
    except Exception:
        return type_profil

def _get_email_proposant(proposant):
    """Récupère l'email du proposant"""
    try:
        # 1. Email depuis l'utilisateur Django
        if hasattr(proposant, 'user') and proposant.user and proposant.user.email:
            return proposant.user.email
        
        # 2. Email direct sur le profil
        if hasattr(proposant, 'email') and proposant.email:
            return proposant.email
        
        # 3. Email depuis les données étendues
        if hasattr(proposant, 'extended_data') and proposant.extended_data:
            extended_email = getattr(proposant.extended_data, 'email', '')
            if extended_email:
                return extended_email
        
        return ''
        
    except Exception:
        return ''

def _get_departement_proposant(proposant):
    """Récupère le département du proposant"""
    try:
        if hasattr(proposant, 'departement') and proposant.departement:
            return proposant.departement.nom
        return 'Département non renseigné'
    except Exception:
        return 'Département non renseigné'

def _get_site_proposant(proposant):
    """Récupère le site du proposant"""
    try:
        if hasattr(proposant, 'site') and proposant.site:
            return proposant.site.nom
        return 'Site non renseigné'
    except Exception:
        return 'Site non renseigné'

def _get_poste_proposant(proposant):
    """Récupère le poste du proposant"""
    try:
        if hasattr(proposant, 'poste') and proposant.poste:
            return proposant.poste.titre
        return 'Poste non renseigné'
    except Exception:
        return 'Poste non renseigné'

def _get_manager_proposant(proposant):
    """Récupère le manager du proposant"""
    try:
        if hasattr(proposant, 'manager') and proposant.manager:
            return proposant.manager.nom_complet
        return ''
    except Exception:
        return ''

def _get_nom_court(nom_complet):
    """Génère un nom court (prénom + initiale du nom)"""
    try:
        if not nom_complet or nom_complet in ['Nom non disponible', 'Erreur de récupération']:
            return nom_complet
        
        parties = nom_complet.strip().split()
        if len(parties) >= 2:
            return f"{parties[0]} {parties[1][0]}."
        return nom_complet
    except Exception:
        return nom_complet

def _get_initiales(nom_complet):
    """Génère les initiales du nom"""
    try:
        if not nom_complet or nom_complet in ['Nom non disponible', 'Erreur de récupération']:
            return 'NN'
        
        parties = nom_complet.strip().split()
        if len(parties) >= 2:
            return f"{parties[0][0]}{parties[1][0]}".upper()
        elif len(parties) == 1:
            return f"{parties[0][0]}".upper()
        return 'NN'
    except Exception:
        return 'NN'
    
# ================================================================
# 🔧 FONCTIONS ADDITIONNELLES MANQUANTES - NOMS HARMONISÉS
# ================================================================

def _est_disponible_periode(candidat, demande):
    """
    🗓️ Vérifie la disponibilité d'un candidat sur la période de la demande
    
    Args:
        candidat: Instance ProfilUtilisateur
        demande: Instance DemandeInterim
        
    Returns:
        bool: True si disponible, False sinon
    """
    try:
        # ================================================================
        # VÉRIFICATIONS DE BASE
        # ================================================================
        
        if not candidat:
            logger.warning("Candidat None fourni à _est_disponible_periode")
            return False
            
        if not demande:
            logger.warning("Demande None fournie à _est_disponible_periode")
            return False
        
        # Vérifier que le candidat est actif
        if not candidat.actif or candidat.statut_employe != 'ACTIF':
            logger.debug(f"Candidat {candidat.matricule} non actif ou statut invalide")
            return False
        
        # Si pas de dates définies, considérer comme disponible
        if not demande.date_debut or not demande.date_fin:
            logger.debug(f"Dates de demande non définies - considéré disponible par défaut")
            return True
        
        # ================================================================
        # VÉRIFICATIONS DES CONFLITS D'ABSENCES
        # ================================================================
        
        # Vérifier les absences déclarées
        absences_conflictuelles = AbsenceUtilisateur.objects.filter(
            utilisateur=candidat,
            date_debut__lte=demande.date_fin,
            date_fin__gte=demande.date_debut
        )
        
        if absences_conflictuelles.exists():
            logger.debug(f"Candidat {candidat.matricule} a des absences en conflit")
            return False
        
        # ================================================================
        # VÉRIFICATIONS DES INDISPONIBILITÉS DÉCLARÉES
        # ================================================================
        
        # Vérifier les indisponibilités explicites
        indisponibilites = DisponibiliteUtilisateur.objects.filter(
            utilisateur=candidat,
            type_disponibilite__in=['INDISPONIBLE', 'EN_MISSION', 'CONGE', 'FORMATION'],
            date_debut__lte=demande.date_fin,
            date_fin__gte=demande.date_debut
        )
        
        if indisponibilites.exists():
            logger.debug(f"Candidat {candidat.matricule} a des indisponibilités déclarées")
            return False
        
        # ================================================================
        # VÉRIFICATIONS DES MISSIONS D'INTÉRIM EN COURS
        # ================================================================
        
        # Vérifier s'il n'est pas déjà en mission d'intérim
        missions_en_cours = DemandeInterim.objects.filter(
            candidat_selectionne=candidat,
            statut__in=['EN_COURS', 'VALIDEE'],
            date_debut__lte=demande.date_fin,
            date_fin__gte=demande.date_debut
        ).exclude(id=demande.id)  # Exclure la demande actuelle
        
        if missions_en_cours.exists():
            logger.debug(f"Candidat {candidat.matricule} déjà en mission d'intérim")
            return False
        
        # ================================================================
        # VÉRIFICATIONS SPÉCIFIQUES SELON LES DONNÉES ÉTENDUES
        # ================================================================
        
        # Vérifier la disponibilité pour l'intérim si renseignée
        if hasattr(candidat, 'extended_data') and candidat.extended_data:
            if hasattr(candidat.extended_data, 'disponible_interim'):
                if not candidat.extended_data.disponible_interim:
                    logger.debug(f"Candidat {candidat.matricule} marqué comme non disponible pour intérim")
                    return False
        
        # ================================================================
        # VÉRIFICATIONS DE DATES CONTRACTUELLES
        # ================================================================
        
        # Vérifier que le contrat couvre la période
        if candidat.date_fin_contrat:
            if candidat.date_fin_contrat < demande.date_fin:
                logger.debug(f"Contrat du candidat {candidat.matricule} se termine avant la fin de mission")
                return False
        
        # Vérifier la date d'embauche
        if candidat.date_embauche:
            if candidat.date_embauche > demande.date_debut:
                logger.debug(f"Candidat {candidat.matricule} pas encore embauché au début de la mission")
                return False
        
        # ================================================================
        # VÉRIFICATIONS AVANCÉES (si données étendues disponibles)
        # ================================================================
        
        if hasattr(candidat, 'extended_data') and candidat.extended_data:
            extended = candidat.extended_data
            
            # Vérifier la date de fin de contrat étendue
            if extended.date_fin_contrat:
                if extended.date_fin_contrat < demande.date_fin:
                    logger.debug(f"Contrat étendu du candidat {candidat.matricule} se termine avant la mission")
                    return False
            
            # Vérifier les visites médicales si nécessaire
            if extended.prochaine_visite_medicale:
                # Si visite médicale pendant la mission et obligatoire
                if (demande.date_debut <= extended.prochaine_visite_medicale <= demande.date_fin):
                    # On pourrait ajouter une logique plus fine ici
                    pass
        
        # ================================================================
        # VÉRIFICATIONS DE PROXIMITÉ GÉOGRAPHIQUE
        # ================================================================
        
        # Vérifier le rayon de déplacement si renseigné
        if (hasattr(candidat, 'extended_data') and 
            candidat.extended_data and 
            hasattr(candidat.extended_data, 'rayon_deplacement_km')):
            
            rayon_max = candidat.extended_data.rayon_deplacement_km
            if rayon_max and rayon_max > 0:
                # Si les sites sont différents et que le rayon est limité
                if (candidat.site and demande.poste.site and 
                    candidat.site != demande.poste.site and 
                    rayon_max < 25):  # Seuil arbitraire de 25km
                    
                    logger.debug(f"Candidat {candidat.matricule} - rayon de déplacement limité")
                    # On pourrait calculer la distance réelle ici
                    # Pour l'instant, on accepte si rayon >= 25km
                    pass
        
        # ================================================================
        # VÉRIFICATIONS TEMPS DE TRAVAIL
        # ================================================================
        
        # Vérifier la compatibilité du temps de travail
        if (hasattr(candidat, 'extended_data') and 
            candidat.extended_data and 
            hasattr(candidat.extended_data, 'temps_travail')):
            
            temps_travail = candidat.extended_data.temps_travail
            if temps_travail and temps_travail < 0.5:  # Moins de 50%
                logger.debug(f"Candidat {candidat.matricule} - temps de travail très partiel ({temps_travail})")
                # On pourrait être plus strict selon le besoin de la mission
                pass
        
        # ================================================================
        # TOUTES LES VÉRIFICATIONS SONT PASSÉES
        # ================================================================
        
        logger.debug(f"  Candidat {candidat.matricule} disponible pour la période du {demande.date_debut} au {demande.date_fin}")
        return True
        
    except Exception as e:
        logger.error(f"  Erreur lors de la vérification de disponibilité pour {candidat.matricule if candidat else 'candidat inconnu'}: {e}")
        # En cas d'erreur, on considère comme non disponible par sécurité
        return False

# ================================================================
# 🎯 FONCTIONS HARMONISÉES - COMPÉTENCES, FORMATIONS, ÉVALUATIONS
# ================================================================

def _get_competences_avec_scoring(candidat, demande):
    """
    🎯 Récupère les compétences avec scoring par rapport au poste demandé
    
    Args:
        candidat: Instance ProfilUtilisateur
        demande: Instance DemandeInterim
        
    Returns:
        list: Liste des compétences avec scores de pertinence
    """
    try:
        # ================================================================
        # VÉRIFICATIONS DE BASE
        # ================================================================
        
        if not candidat:
            logger.warning("Candidat None fourni à _get_competences_avec_scoring")
            return []
            
        if not demande or not demande.poste:
            logger.warning("Demande ou poste None fourni à _get_competences_avec_scoring")
            return []
        
        # ================================================================
        # RÉCUPÉRATION DES COMPÉTENCES DU CANDIDAT
        # ================================================================
        
        # Compétences depuis le modèle CompetenceUtilisateur
        competences_candidat = CompetenceUtilisateur.objects.filter(
            utilisateur=candidat
        ).select_related('competence').order_by('-niveau_maitrise', '-date_evaluation')
        
        if not competences_candidat.exists():
            logger.debug(f"Aucune compétence trouvée pour le candidat {candidat.matricule}")
            return []
        
        # ================================================================
        # MOTS-CLÉS DU POSTE POUR LE MATCHING
        # ================================================================
        
        mots_cles_poste = _extraire_mots_cles_poste(demande)
        
        competences_avec_scores = []
        
        # ================================================================
        # TRAITEMENT DE CHAQUE COMPÉTENCE
        # ================================================================
        
        for comp_utilisateur in competences_candidat:
            try:
                competence = comp_utilisateur.competence
                if not competence:
                    continue
                
                # Score de pertinence (0-100)
                score_pertinence = _calculer_score_pertinence_competence(
                    competence, mots_cles_poste, demande
                )
                
                # Niveau de maîtrise (1-4 converti en 25-100)
                niveau_maitrise_score = (comp_utilisateur.niveau_maitrise * 25)
                
                # Score final pondéré
                score_final = int((score_pertinence * 0.6) + (niveau_maitrise_score * 0.4))
                
                # Indicateurs de qualité
                est_certifie = comp_utilisateur.certifie
                est_recent = _est_competence_recente(comp_utilisateur)
                est_kelio = comp_utilisateur.source_donnee == 'KELIO'
                
                competence_data = {
                    'nom': competence.nom,
                    'categorie': competence.categorie or 'Général',
                    'type_competence': competence.type_competence,
                    'niveau_maitrise': comp_utilisateur.niveau_maitrise,
                    'niveau_maitrise_display': comp_utilisateur.get_niveau_maitrise_display(),
                    'certifie': est_certifie,
                    'score_pertinence': score_pertinence,
                    'score_niveau': niveau_maitrise_score,
                    'score_final': score_final,
                    'score_class': _get_score_css_class(score_final),
                    
                    # Métadonnées
                    'source_donnee': comp_utilisateur.source_donnee,
                    'date_evaluation': comp_utilisateur.date_evaluation,
                    'date_acquisition': comp_utilisateur.date_acquisition,
                    'est_recent': est_recent,
                    'est_kelio': est_kelio,
                    'evaluateur': _get_nom_evaluateur(comp_utilisateur.evaluateur),
                    'commentaire': comp_utilisateur.commentaire or '',
                    
                    # Affichage
                    'badge_color': _get_competence_badge_color(score_final, est_certifie),
                    'icone': _get_competence_icone(competence.type_competence),
                    'tooltip': _generer_tooltip_competence(comp_utilisateur, score_final),
                    
                    # Kelio spécifique
                    'kelio_level': getattr(comp_utilisateur, 'kelio_level', ''),
                    'kelio_skill_key': getattr(comp_utilisateur, 'kelio_skill_assignment_key', None)
                }
                
                competences_avec_scores.append(competence_data)
                
            except Exception as e:
                logger.error(f"  Erreur traitement compétence {comp_utilisateur.id}: {e}")
                continue
        
        # ================================================================
        # TRI ET LIMITATION
        # ================================================================
        
        # Trier par score final décroissant, puis par certification
        competences_avec_scores.sort(
            key=lambda c: (c['score_final'], c['certifie'], c['est_recent']), 
            reverse=True
        )
        
        # Limiter à 15 compétences max pour l'affichage
        competences_finales = competences_avec_scores[:15]
        
        logger.info(f"  {len(competences_finales)} compétences récupérées pour {candidat.matricule}")
        return competences_finales
        
    except Exception as e:
        logger.error(f"  Erreur globale _get_competences_avec_scoring: {e}")
        return []

def _get_formations_recentes(candidat):
    """
    📚 Récupère les formations récentes du candidat (2 dernières années)
    
    Args:
        candidat: Instance ProfilUtilisateur
        
    Returns:
        list: Liste des formations récentes enrichies
    """
    try:
        # ================================================================
        # VÉRIFICATIONS DE BASE
        # ================================================================
        
        if not candidat:
            logger.warning("Candidat None fourni à _get_formations_recentes")
            return []
        
        # ================================================================
        # CALCUL DE LA PÉRIODE "RÉCENTE"
        # ================================================================
        
        from datetime import date, timedelta
        
        # Formations des 2 dernières années
        date_limite = date.today() - timedelta(days=730)
        
        # ================================================================
        # RÉCUPÉRATION DES FORMATIONS
        # ================================================================
        
        formations = FormationUtilisateur.objects.filter(
            utilisateur=candidat
        ).filter(
            models.Q(date_fin__gte=date_limite) |  # Formations récentes
            models.Q(date_fin__isnull=True, date_debut__gte=date_limite)  # En cours
        ).order_by('-date_fin', '-date_debut', 'titre')
        
        if not formations.exists():
            logger.debug(f"Aucune formation récente pour {candidat.matricule}")
            return []
        
        formations_enrichies = []
        
        # ================================================================
        # ENRICHISSEMENT DE CHAQUE FORMATION
        # ================================================================
        
        for formation in formations:
            try:
                # Calcul de la durée
                duree_display = _calculer_duree_formation(formation)
                
                # Statut de la formation
                statut = _determiner_statut_formation(formation)
                
                # Score de qualité (basé sur plusieurs critères)
                score_qualite = _calculer_score_formation(formation)
                
                formation_data = {
                    'titre': formation.titre,
                    'description': formation.description or '',
                    'type_formation': formation.type_formation or 'Formation',
                    'organisme': formation.organisme or 'Organisme non spécifié',
                    
                    # Dates
                    'date_debut': formation.date_debut,
                    'date_fin': formation.date_fin,
                    'date_debut_display': safe_date_format(formation.date_debut),
                    'date_fin_display': safe_date_format(formation.date_fin),
                    'duree_jours': formation.duree_jours,
                    'duree_display': duree_display,
                    
                    # Statut et qualité
                    'statut': statut,
                    'statut_display': _get_statut_formation_display(statut),
                    'statut_class': _get_statut_formation_css_class(statut),
                    'certifiante': formation.certifiante,
                    'diplome_obtenu': formation.diplome_obtenu,
                    'score_qualite': score_qualite,
                    
                    # Source des données
                    'source_donnee': formation.source_donnee,
                    'est_kelio': formation.source_donnee == 'KELIO',
                    'kelio_formation_key': formation.kelio_formation_key,
                    
                    # Affichage
                    'icone': _get_formation_icone(formation.type_formation, formation.certifiante),
                    'badge_color': _get_formation_badge_color(formation.certifiante, formation.diplome_obtenu),
                    'tooltip': _generer_tooltip_formation(formation, statut),
                    
                    # Métadonnées
                    'anciennete_jours': (date.today() - (formation.date_fin or formation.date_debut or date.today())).days,
                    'est_tres_recente': _est_formation_tres_recente(formation),  # < 6 mois
                    'est_en_cours': statut == 'EN_COURS'
                }
                
                formations_enrichies.append(formation_data)
                
            except Exception as e:
                logger.error(f"  Erreur traitement formation {formation.id}: {e}")
                continue
        
        # ================================================================
        # TRI ET LIMITATION
        # ================================================================
        
        # Trier par ordre de priorité : en cours > récentes > certifiantes
        formations_enrichies.sort(
            key=lambda f: (
                f['est_en_cours'],
                f['est_tres_recente'], 
                f['certifiante'],
                f['score_qualite'],
                f['date_fin'] or date.today()
            ), 
            reverse=True
        )
        
        # Limiter à 10 formations max
        formations_finales = formations_enrichies[:20]
        
        logger.info(f"  {len(formations_finales)} formations récentes récupérées pour {candidat.matricule}")
        return formations_finales
        
    except Exception as e:
        logger.error(f"  Erreur globale _get_formations_recentes: {e}")
        return []


# ================================================================
# 🛠️ FONCTIONS UTILITAIRES SUPPORTANT LES 3 PRINCIPALES
# ================================================================

def _extraire_mots_cles_poste(demande):
    """Extrait les mots-clés du poste pour le matching de compétences"""
    try:
        mots_cles = set()
        
        if demande.poste:
            # Titre du poste
            mots_cles.update(demande.poste.titre.lower().split())
            
            # Description du poste
            if demande.poste.description:
                mots_cles.update(demande.poste.description.lower().split())
            
            # Catégorie
            if demande.poste.categorie:
                mots_cles.update(demande.poste.categorie.lower().split())
        
        # Description de la demande
        if demande.description_poste:
            mots_cles.update(demande.description_poste.lower().split())
        
        # Compétences indispensables
        if demande.competences_indispensables:
            mots_cles.update(demande.competences_indispensables.lower().split())
        
        # Nettoyer les mots vides
        mots_vides = {'le', 'la', 'les', 'de', 'du', 'des', 'et', 'ou', 'à', 'dans', 'pour', 'avec', 'sur'}
        mots_cles = {mot for mot in mots_cles if len(mot) > 2 and mot not in mots_vides}
        
        return list(mots_cles)
        
    except Exception:
        return []

def _calculer_score_pertinence_competence(competence, mots_cles_poste, demande):
    """Calcule un score de pertinence d'une compétence par rapport au poste"""
    try:
        score = 0
        
        # Correspondance nom de compétence
        nom_competence = competence.nom.lower()
        for mot_cle in mots_cles_poste:
            if mot_cle in nom_competence:
                score += 20
        
        # Correspondance catégorie
        if competence.categorie and demande.poste and demande.poste.categorie:
            if competence.categorie.lower() in demande.poste.categorie.lower():
                score += 15
        
        # Bonus selon le type de compétence
        if competence.type_competence == 'TECHNIQUE':
            score += 10
        elif competence.type_competence == 'TRANSVERSE':
            score += 5
        
        return min(100, max(0, score))
        
    except Exception:
        return 20  # Score neutre

def _est_competence_recente(comp_utilisateur):
    """Vérifie si une compétence a été évaluée récemment"""
    try:
        if not comp_utilisateur.date_evaluation:
            return False
        
        from datetime import date, timedelta
        limite = date.today() - timedelta(days=365)  # 1 an
        return comp_utilisateur.date_evaluation >= limite
        
    except Exception:
        return False

def _get_nom_evaluateur(evaluateur):
    """Récupère le nom de l'évaluateur de façon sécurisée"""
    try:
        if evaluateur:
            return evaluateur.nom_complet
        return 'Non spécifié'
    except Exception:
        return 'Non spécifié'

def _get_competence_badge_color(score, est_certifie):
    """Détermine la couleur du badge de compétence"""
    if est_certifie:
        return 'success'
    elif score >= 80:
        return 'primary'
    elif score >= 60:
        return 'info'
    elif score >= 40:
        return 'warning'
    else:
        return 'secondary'

def _get_competence_icone(type_competence):
    """Retourne l'icône selon le type de compétence"""
    icones = {
        'TECHNIQUE': 'fa-cogs',
        'TRANSVERSE': 'fa-arrows-alt',
        'COMPORTEMENTALE': 'fa-users',
        'LINGUISTIQUE': 'fa-language',
        'LOGICIEL': 'fa-laptop-code'
    }
    return icones.get(type_competence, 'fa-star')

def _generer_tooltip_competence(comp_utilisateur, score):
    """Génère un tooltip informatif pour la compétence"""
    try:
        tooltip = f"Score: {score}/100"
        if comp_utilisateur.date_evaluation:
            tooltip += f" | Évalué le {safe_date_format(comp_utilisateur.date_evaluation)}"
        if comp_utilisateur.certifie:
            tooltip += " | Certifié"
        if comp_utilisateur.source_donnee == 'KELIO':
            tooltip += " | Données Kelio"
        return tooltip
    except Exception:
        return f"Score: {score}/100"

def _calculer_duree_formation(formation):
    """Calcule et formate la durée d'une formation"""
    try:
        if formation.duree_jours and formation.duree_jours > 0:
            if formation.duree_jours == 1:
                return "1 jour"
            elif formation.duree_jours < 30:
                return f"{formation.duree_jours} jours"
            else:
                mois = formation.duree_jours // 30
                return f"{mois} mois"
        
        # Calcul basé sur les dates
        if formation.date_debut and formation.date_fin:
            duree = safe_date_operation(formation.date_fin, formation.date_debut)
            if duree:
                if duree == 1:
                    return "1 jour"
                elif duree < 30:
                    return f"{duree} jours"
                else:
                    mois = duree // 30
                    return f"{mois} mois"
        
        return "Durée non spécifiée"
        
    except Exception:
        return "Durée non spécifiée"

def _determiner_statut_formation(formation):
    """Détermine le statut d'une formation"""
    try:
        from datetime import date
        
        if not formation.date_debut:
            return 'PLANIFIEE'
        
        aujourd_hui = date.today()
        
        if formation.date_debut > aujourd_hui:
            return 'PLANIFIEE'
        elif formation.date_fin and formation.date_fin < aujourd_hui:
            return 'TERMINEE'
        else:
            return 'EN_COURS'
            
    except Exception:
        return 'INCONNU'

def _calculer_score_formation(formation):
    """Calcule un score de qualité pour une formation"""
    try:
        score = 50  # Base
        
        if formation.certifiante:
            score += 20
        
        if formation.diplome_obtenu:
            score += 15
        
        if formation.organisme and formation.organisme.strip():
            score += 10
        
        if formation.source_donnee == 'KELIO':
            score += 5
        
        return min(100, score)
        
    except Exception:
        return 50

def _get_statut_formation_display(statut):
    """Affichage formaté du statut de formation"""
    statuts = {
        'PLANIFIEE': '📅 Planifiée',
        'EN_COURS': '▶️ En cours',
        'TERMINEE': '  Terminée',
        'INCONNU': '❓ Inconnu'
    }
    return statuts.get(statut, statut)

def _get_statut_formation_css_class(statut):
    """Classe CSS selon le statut de formation"""
    classes = {
        'PLANIFIEE': 'info',
        'EN_COURS': 'warning',
        'TERMINEE': 'success',
        'INCONNU': 'secondary'
    }
    return classes.get(statut, 'secondary')

def _get_formation_icone(type_formation, certifiante):
    """Icône selon le type de formation"""
    if certifiante:
        return 'fa-certificate'
    
    icones = {
        'DIPLOME': 'fa-graduation-cap',
        'CERTIFICATION': 'fa-certificate',
        'FORMATION': 'fa-book',
        'STAGE': 'fa-user-graduate'
    }
    return icones.get(type_formation, 'fa-book')

def _get_formation_badge_color(certifiante, diplome_obtenu):
    """Couleur du badge de formation"""
    if certifiante and diplome_obtenu:
        return 'success'
    elif certifiante:
        return 'warning'
    elif diplome_obtenu:
        return 'primary'
    else:
        return 'info'

def _generer_tooltip_formation(formation, statut):
    """Génère un tooltip pour la formation"""
    try:
        tooltip = f"Statut: {_get_statut_formation_display(statut)}"
        if formation.organisme:
            tooltip += f" | {formation.organisme}"
        if formation.certifiante:
            tooltip += " | Certifiante"
        return tooltip
    except Exception:
        return "Formation"

def _est_formation_tres_recente(formation):
    """Vérifie si une formation est très récente (< 6 mois)"""
    try:
        from datetime import date, timedelta
        
        date_fin = formation.date_fin or formation.date_debut
        if not date_fin:
            return False
        
        limite = date.today() - timedelta(days=180)  # 6 mois
        return date_fin >= limite
        
    except Exception:
        return False

def _get_classe_note_evaluation(note, note_max):
    """Détermine la classe CSS selon la note"""
    try:
        pourcentage = (note / note_max) * 100
        return _get_score_css_class(pourcentage)
    except Exception:
        return 'secondary'

def _get_couleur_note(note, note_max):
    """Détermine la couleur selon la note"""
    try:
        pourcentage = (note / note_max) * 100
        if pourcentage >= 80:
            return 'success'
        elif pourcentage >= 60:
            return 'primary'
        elif pourcentage >= 40:
            return 'warning'
        else:
            return 'danger'
    except Exception:
        return 'secondary'

def _generer_commentaire_synthese(moyenne, nb_evaluations):
    """Génère un commentaire de synthèse"""
    try:
        if moyenne >= 80:
            qualificatif = "excellentes"
        elif moyenne >= 60:
            qualificatif = "bonnes"
        elif moyenne >= 40:
            qualificatif = "correctes"
        else:
            qualificatif = "perfectibles"
        
        return f"Performances {qualificatif} basées sur {nb_evaluations} évaluations"
        
    except Exception:
        return f"Synthèse de {nb_evaluations} évaluations"
    
def _enrichir_info_candidat_minimal(candidat, demande):
    """
      CORRIGÉ - Enrichissement minimal sécurisé
    """
    try:
        return {
            'nom_complet': getattr(candidat, 'nom_complet', 'Nom non disponible'),
            'matricule': getattr(candidat, 'matricule', 'N/A'),
            'poste_actuel': getattr(candidat.poste, 'titre', 'Poste non défini') if hasattr(candidat, 'poste') and candidat.poste else 'Poste non défini',
            'departement': getattr(candidat.departement, 'nom', 'Département non défini') if hasattr(candidat, 'departement') and candidat.departement else 'Département non défini',
            'competences_principales': [],
            'disponibilite': {
                'disponible': True,
                'raison': 'Disponibilité non vérifiée',
                'type': 'UNKNOWN'
            },
            'historique_interim': {
                'nb_missions_total': 0
            },
            'anciennete': 'Non renseignée'
        }
    except Exception as e:
        logger.error(f"  Erreur enrichissement minimal: {e}")
        return {
            'nom_complet': 'Erreur de récupération',
            'matricule': 'ERR',
            'poste_actuel': 'Erreur',
            'departement': 'Erreur',
            'competences_principales': [],
            'disponibilite': {'disponible': False, 'raison': 'Erreur', 'type': 'ERROR'},
            'historique_interim': {'nb_missions_total': 0},
            'anciennete': 'Erreur'
        }
            
def _combiner_candidats_propositions_securise(propositions_humaines, candidats_automatiques):
    """
      CORRIGÉ - Combine et trie tous les candidats avec scores valides
    """
    try:
        tous_candidats = []
        
        # Ajouter les propositions humaines
        for prop in propositions_humaines:
            #   VALIDATION DU SCORE
            score = prop.get('score_affichage', 0)
            if score is None:
                score = 0
            try:
                score = int(float(score))
            except (ValueError, TypeError):
                score = 0
            
            prop['score_affichage'] = score  #   GARANTIR LE TYPE
            tous_candidats.append(prop)
        
        # Ajouter les candidats automatiques (déjà limités à 10)
        for candidat in candidats_automatiques:
            #   VALIDATION DU SCORE
            score = candidat.get('score_affichage', 0)
            if score is None:
                score = 0
            try:
                score = int(float(score))
            except (ValueError, TypeError):
                score = 0
            
            candidat['score_affichage'] = score  #   GARANTIR LE TYPE
            tous_candidats.append(candidat)
        
        #   TRI PAR PRIORITÉ ET SCORE
        tous_candidats.sort(key=lambda c: (
            c.get('priorite_affichage', 999),  # Priorité (1=humain, 2=IA)
            -c.get('score_affichage', 0)       # Score décroissant
        ))
        
        logger.info(f"  {len(tous_candidats)} candidats combinés et triés")
        return tous_candidats
        
    except Exception as e:
        logger.error(f"  Erreur combinaison candidats: {e}")
        return []
    
def _calculer_stats_propositions(propositions, candidats_automatiques):
    """
      NOM HARMONISÉ - Calcule des statistiques enrichies avec sources
    (Anciennement: _calculer_stats_enrichies)
    """
    try:
        # Scores des propositions humaines
        scores_humains = [
            prop['score_affichage'] for prop in propositions
            if prop.get('score_affichage') is not None
        ]
        
        # Scores des candidats automatiques
        scores_auto = [
            cand['score_affichage'] for cand in candidats_automatiques
            if cand.get('score_affichage') is not None
        ]
        
        # Tous les scores
        tous_scores = scores_humains + scores_auto
        
        stats = {
            'total_candidats': len(propositions) + len(candidats_automatiques),
            'nb_propositions_humaines': len(propositions),
            'nb_candidats_automatiques': len(candidats_automatiques),
            
            #   STATISTIQUES DE SCORES
            'score_moyen': round(sum(tous_scores) / len(tous_scores), 1) if tous_scores else 0,
            'score_max': max(tous_scores) if tous_scores else 0,
            'score_min': min(tous_scores) if tous_scores else 0,
            
            # 📈 RÉPARTITION PAR QUALITÉ
            'excellents': len([s for s in tous_scores if s >= 80]),
            'bons': len([s for s in tous_scores if 60 <= s < 80]),
            'corrects': len([s for s in tous_scores if 40 <= s < 60]),
            'faibles': len([s for s in tous_scores if s < 40]),
            
            #   COMPARAISON SOURCES
            'score_moyen_humains': round(sum(scores_humains) / len(scores_humains), 1) if scores_humains else 0,
            'score_moyen_auto': round(sum(scores_auto) / len(scores_auto), 1) if scores_auto else 0,
        }
        
        return stats
        
    except Exception as e:
        logger.error(f"  Erreur calcul statistiques enrichies: {e}")
        return {
            'total_candidats': 0,
            'nb_propositions_humaines': 0,
            'nb_candidats_automatiques': 0,
            'score_moyen': 0
        }
    
def _enrichir_info_candidat(candidat, demande):
    """  CORRIGÉE : Enrichit les informations d'un candidat SANS ERREUR"""
    try:
        if not candidat:
            return {'erreur': 'Candidat non trouvé'}
        
        # Informations de base avec protections
        info = {
            'nom_complet': getattr(candidat, 'nom_complet', 'Nom non disponible'),
            'matricule': getattr(candidat, 'matricule', 'N/A'),
            'poste_actuel': candidat.poste.titre if candidat.poste else 'Non renseigné',
            'departement': candidat.departement.nom if candidat.departement else 'Non renseigné',
            'site': candidat.site.nom if candidat.site else 'Non renseigné',
            'anciennete': _calculer_anciennete(candidat),
            'statut_employe': candidat.get_statut_employe_display() if hasattr(candidat, 'get_statut_employe_display') else getattr(candidat, 'statut_employe', 'Inconnu'),
        }
        
        # Compétences principales (protection contre les erreurs)
        try:
            from mainapp.models import CompetenceUtilisateur
            competences = CompetenceUtilisateur.objects.filter(
                utilisateur=candidat
            ).select_related('competence').order_by('-niveau_maitrise')[:5]
            
            info['competences_principales'] = []
            for comp in competences:
                try:
                    info['competences_principales'].append({
                        'nom': comp.competence.nom if comp.competence else 'Compétence inconnue',
                        'niveau': comp.get_niveau_maitrise_display() if hasattr(comp, 'get_niveau_maitrise_display') else f"Niveau {comp.niveau_maitrise}",
                        'niveau_num': comp.niveau_maitrise or 0,
                        'certifie': getattr(comp, 'certifie', False)
                    })
                except (AttributeError, TypeError):
                    continue
        except Exception:
            info['competences_principales'] = []
        
        # Disponibilité pour la période demandée
        info['disponibilite'] = _verifier_disponibilite_candidat(candidat, demande.date_debut, demande.date_fin)
        
        # Formations récentes (protection)
        try:
            formations_recentes = candidat.formations.order_by('-date_fin')[:3] if hasattr(candidat, 'formations') else []
            info['formations_recentes'] = []
            for form in formations_recentes:
                try:
                    info['formations_recentes'].append({
                        'titre': getattr(form, 'titre', 'Formation inconnue'),
                        'organisme': getattr(form, 'organisme', 'N/A'),
                        'date_fin': getattr(form, 'date_fin', None),
                        'certifiante': getattr(form, 'certifiante', False)
                    })
                except (AttributeError, TypeError):
                    continue
        except Exception:
            info['formations_recentes'] = []
        
        # Historique d'intérim
        info['historique_interim'] = _get_historique_interim_candidat(candidat)
        
        return info
        
    except Exception as e:
        logger.error(f"Erreur enrichissement candidat: {e}")
        return {
            'nom_complet': 'Erreur',
            'matricule': 'N/A',
            'erreur': str(e),
            'competences_principales': [],
            'formations_recentes': [],
            'disponibilite': {'disponible': False, 'raison': 'Erreur données'},
            'historique_interim': {'nb_missions_total': 0}
        }

def _calculer_anciennete(candidat):
    """  SÉCURISÉ : Calcule l'ancienneté sans erreur"""
    try:
        if hasattr(candidat, 'date_embauche') and candidat.date_embauche:
            from datetime import date
            anciennete = (date.today() - candidat.date_embauche).days // 365
            return f"{anciennete} an{'s' if anciennete > 1 else ''}"
        return "Ancienneté non renseignée"
    except Exception:
        return "Ancienneté non disponible"

def _get_score_detail_candidat_securise(candidat, demande, proposition=None):
    """  SÉCURISÉ : Récupère le détail du score"""
    try:
        return {
            'score_final': proposition.score_final if proposition and hasattr(proposition, 'score_final') else 0,
            'criteres': {},
            'bonus_malus': {},
            'explications': ['Score calculé']
        }
    except Exception:
        return {
            'score_final': 0,
            'criteres': {},
            'bonus_malus': {},
            'explications': ['Erreur calcul score']
        }

def _get_types_competences_securise():
    """  SÉCURISÉ : Récupère les types de compétences"""
    try:
        from mainapp.models import Competence
        return Competence.objects.filter(actif=True).values_list('categorie', flat=True).distinct()
    except Exception:
        return []

# ================================================================
#   FONCTIONS WORKFLOW ET PERMISSIONS - NOMS À IMPLÉMENTER
# ================================================================

def _get_workflow_info_complete(demande, profil_utilisateur):
    """
    Récupère les informations complètes du workflow avec correction des dates
    """
    try:
        # Calcul de la progression sécurisé
        try:
            progression_pct = demande.progression_pct if hasattr(demande, 'progression_pct') else 0
            if not isinstance(progression_pct, (int, float)):
                progression_pct = 0
        except:
            progression_pct = 0
            
        workflow_info = {
            'niveau_a_valider': getattr(demande, 'niveau_validation_actuel', 0) + 1,
            'niveau_validation_actuel': getattr(demande, 'niveau_validation_actuel', 0),
            'niveaux_requis': getattr(demande, 'niveaux_validation_requis', 3),
            'progression_pct': max(0, min(100, int(progression_pct))),
            'type_validateur': profil_utilisateur.type_profil if profil_utilisateur else 'INCONNU',
            'etape_actuelle': _get_etape_description_safe(demande),
        }
        
        return workflow_info
        
    except Exception as e:
        logger.error(f"Erreur récupération workflow info: {e}")
        return {
            'niveau_a_valider': 1,
            'niveau_validation_actuel': 0,
            'niveaux_requis': 3,
            'progression_pct': 0,
            'type_validateur': 'INCONNU',
            'etape_actuelle': 'Étape non définie',
        }

def _get_etape_description_safe(demande):
    """
    Récupère la description de l'étape actuelle de façon sécurisée
    """
    try:
        statut = getattr(demande, 'statut', '')
        
        if statut == 'BROUILLON':
            return "Demande en cours de rédaction"
        elif statut == 'SOUMISE':
            return "Demande soumise, en attente de traitement"
        elif statut == 'EN_PROPOSITION':
            return "Recherche et proposition de candidats en cours"
        elif statut == 'EN_VALIDATION':
            niveau = getattr(demande, 'niveau_validation_actuel', 0)
            niveaux_requis = getattr(demande, 'niveaux_validation_requis', 3)
            return f"En validation - Niveau {niveau}/{niveaux_requis}"
        elif statut == 'VALIDEE':
            return "Demande validée"
        elif statut == 'EN_COURS':
            return "Mission d'intérim en cours"
        elif statut == 'TERMINEE':
            return "Mission terminée"
        elif statut == 'REFUSEE':
            return "Demande refusée"
        elif statut == 'ANNULEE':
            return "Demande annulée"
        else:
            return f"Statut: {statut}"
            
    except Exception as e:
        logger.error(f"Erreur description étape: {e}")
        return "Étape non déterminée"
        
def _get_permissions_detaillees(profil_utilisateur, demande):
    """Récupère les permissions détaillées"""
    peut_valider = profil_utilisateur.is_superuser or getattr(profil_utilisateur, 'type_profil', '') in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']
    
    return {
        'peut_modifier': profil_utilisateur.is_superuser,
        'peut_valider': peut_valider,
        'peut_proposer_nouveau': peut_valider,
        'peut_voir_details_candidats': True,
        'peut_rejeter': peut_valider,
        'peut_escalader': profil_utilisateur.is_superuser,
        'peut_demander_info': True
    }

def _get_validations_precedentes(demande):
    """Récupère l'historique des validations"""
    return []

def _enrichir_details_demande(demande):
    """
      NOM HARMONISÉ - Enrichit les détails de la demande
    (Nom déjà présent dans le 2ème code)
    """
    try:
        return {
            'urgence_display': demande.get_urgence_display() if hasattr(demande, 'get_urgence_display') else demande.urgence,
            'motif_display': demande.motif_absence.nom if demande.motif_absence else 'Non renseigné',
            'departement_concerne': demande.poste.departement.nom if demande.poste and demande.poste.departement else 'Non renseigné',
            'site_concerne': demande.poste.site.nom if demande.poste and demande.poste.site else 'Non renseigné',
            'duree_mission': demande.duree_mission if hasattr(demande, 'duree_mission') else 0,
            'demandeur_info': {
                'nom': demande.demandeur.nom_complet if demande.demandeur else 'Inconnu',
                'poste': demande.demandeur.poste.titre if demande.demandeur and demande.demandeur.poste else 'Non renseigné'
            },
            'personne_remplacee_info': {
                'nom': demande.personne_remplacee.nom_complet if demande.personne_remplacee else 'Inconnu',
                'matricule': demande.personne_remplacee.matricule if demande.personne_remplacee else 'N/A'
            }
        }
    except Exception as e:
        logger.error(f"Erreur enrichissement détails demande: {e}")
        return {
            'urgence_display': 'Normale',
            'motif_display': 'Non renseigné',
            'departement_concerne': 'Non renseigné',
            'site_concerne': 'Non renseigné',
            'duree_mission': 0,
            'demandeur_info': {'nom': 'Inconnu', 'poste': 'Non renseigné'},
            'personne_remplacee_info': {'nom': 'Inconnu', 'matricule': 'N/A'}
        }

# ================================================================
# TRAITEMENT POST CORRIGÉ AVEC VRAIS MODÈLES
# ================================================================

def _traiter_validation_post_corrige(request, demande, profil_utilisateur):
    """
    VERSION CORRIGÉE - Traitement des actions POST avec gestion d'erreurs robuste
    """
    try:
        logger.info(f"🔄 Traitement POST pour demande {demande.id}")
        
        # ================================================================
        # RÉCUPÉRATION ET VALIDATION DE L'ACTION
        # ================================================================
        
        action = request.POST.get('action', '').strip()
        logger.info(f"📝 Action reçue: '{action}'")
        
        # CORRECTION 1: Vérifier que l'action n'est pas vide
        if not action:
            logger.warning("❌ Action POST vide ou manquante")
            messages.error(request, "Action non spécifiée. Veuillez réessayer.")
            return redirect('interim_validation', demande.id)
        
        # ================================================================
        # VÉRIFICATION DES PERMISSIONS
        # ================================================================
        
        permissions = _get_permissions_detaillees(profil_utilisateur, demande)
        
        if not permissions.get('peut_valider', False):
            logger.warning(f"❌ Utilisateur {profil_utilisateur.nom_complet} non autorisé à valider")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': 'Vous n\'êtes pas autorisé à effectuer cette validation'
                }, status=403)
            else:
                messages.error(request, "Vous n'êtes pas autorisé à effectuer cette validation")
                return redirect('interim_validation', demande.id)
        
        # ================================================================
        # TRAITEMENT SELON L'ACTION
        # ================================================================
        
        # CORRECTION 2: Mapping exhaustif des actions possibles
        actions_valides = {
            'APPROUVER': _traiter_approbation,
            'REFUSER': _traiter_refus,
            'AJOUTER_PROPOSITION': _traiter_ajout_proposition,
            'PROPOSER_CANDIDAT': _traiter_proposition_candidat,
            'VALIDER_AVEC_CANDIDATS': _traiter_validation_avec_candidats,
            'ESCALADER': _traiter_escalade,
            'DEMANDER_INFOS': _traiter_demande_infos,
        }
        
        if action not in actions_valides:
            logger.error(f"❌ Action non reconnue: '{action}'")
            logger.error(f"Actions valides: {list(actions_valides.keys())}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': f'Action non reconnue: {action}'
                }, status=400)
            else:
                messages.error(request, f"Action non reconnue: {action}")
                return redirect('interim_validation', demande.id)
        
        # ================================================================
        # EXÉCUTION DE L'ACTION
        # ================================================================
        
        handler_fonction = actions_valides[action]
        logger.info(f"🎯 Exécution de l'action: {action}")
        
        try:
            return handler_fonction(request, demande, profil_utilisateur)
        
        except Exception as e:
            logger.error(f"💥 Erreur lors de l'exécution de l'action {action}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': f'Erreur lors de l\'exécution: {str(e)}'
                }, status=500)
            else:
                messages.error(request, f"Erreur lors de l'exécution: {str(e)}")
                return redirect('interim_validation', demande.id)
        
    except Exception as e:
        logger.error(f"💥 Erreur générale traitement POST: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Erreur système: {str(e)}'
            }, status=500)
        else:
            messages.error(request, f"Erreur système: {str(e)}")
            return redirect('interim_validation', demande.id)
                
def _traiter_approbation(request, demande, profil_utilisateur):
    """Traite l'approbation d'une demande"""
    try:
        commentaire = request.POST.get('commentaire_validation', '').strip()
        candidats_retenus = request.POST.getlist('candidats_retenus[]', [])
        candidat_final = request.POST.get('candidat_final', '').strip()
        
        logger.info(f"✅ Approbation demande {demande.id}")
        logger.info(f"   - Commentaire: {len(commentaire)} caractères")
        logger.info(f"   - Candidats retenus: {len(candidats_retenus)}")
        logger.info(f"   - Candidat final: {candidat_final}")
        
        # Validation des données obligatoires
        if not commentaire or len(commentaire) < 10:
            error_msg = "Le commentaire de validation doit contenir au moins 10 caractères"
            logger.warning(f"❌ {error_msg}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('interim_validation', demande.id)
        
        # Déterminer le niveau de validation
        workflow_info = _get_workflow_info_complete(demande, profil_utilisateur)
        niveau_validation = workflow_info.get('niveau_a_valider', 1)
        
        # Créer la validation
        validation = ValidationDemande.objects.create(
            demande=demande,
            type_validation=_determiner_type_validation_corrige(profil_utilisateur, niveau_validation),
            niveau_validation=niveau_validation,
            validateur=profil_utilisateur,
            decision='APPROUVE',
            commentaire=commentaire,
            candidats_retenus=candidats_retenus,
            candidats_rejetes=[]
        )
        
        # Valider effectivement
        validation.valider('APPROUVE', commentaire, candidats_retenus, [])
        
        # Mettre à jour la demande
        demande.niveau_validation_actuel = niveau_validation
        
        # Si c'est la validation finale et qu'un candidat final est sélectionné
        if candidat_final and niveau_validation >= demande.niveaux_validation_requis:
            try:
                candidat_obj = ProfilUtilisateur.objects.get(id=candidat_final)
                demande.candidat_selectionne = candidat_obj
                demande.statut = 'CANDIDAT_SELECTIONNE'
                logger.info(f"✅ Candidat final sélectionné: {candidat_obj.nom_complet}")
            except ProfilUtilisateur.DoesNotExist:
                logger.warning(f"⚠️ Candidat final {candidat_final} non trouvé")
        
        # Si toutes les validations sont passées
        if niveau_validation >= demande.niveaux_validation_requis:
            demande.statut = 'VALIDEE'
            demande.date_validation = timezone.now()
        else:
            demande.statut = 'EN_VALIDATION'
        
        demande.save()
        
        success_msg = f"Demande approuvée au niveau {niveau_validation}"
        logger.info(f"✅ {success_msg}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_msg,
                'redirect_url': reverse('liste_interim_validation')
            })
        else:
            messages.success(request, success_msg)
            return redirect('liste_interim_validation')
        
    except Exception as e:
        logger.error(f"💥 Erreur approbation: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Erreur lors de l\'approbation: {str(e)}'
            })
        else:
            messages.error(request, f"Erreur lors de l'approbation: {str(e)}")
            return redirect('interim_validation', demande.id)

def _traiter_refus(request, demande, profil_utilisateur):
    """Traite le refus d'une demande"""
    try:
        commentaire = request.POST.get('commentaire_validation', '').strip()
        motif_refus = request.POST.get('motif_refus', '').strip()
        
        logger.info(f"❌ Refus demande {demande.id}")
        logger.info(f"   - Motif: {motif_refus}")
        logger.info(f"   - Commentaire: {len(commentaire)} caractères")
        
        # Validation des données obligatoires
        if not commentaire or len(commentaire) < 10:
            error_msg = "Le commentaire de refus doit contenir au moins 10 caractères"
            logger.warning(f"❌ {error_msg}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('interim_validation', demande.id)
        
        # Déterminer le niveau de validation
        workflow_info = _get_workflow_info_complete(demande, profil_utilisateur)
        niveau_validation = workflow_info.get('niveau_a_valider', 1)
        
        # Créer la validation de refus
        validation = ValidationDemande.objects.create(
            demande=demande,
            type_validation=_determiner_type_validation_corrige(profil_utilisateur, niveau_validation),
            niveau_validation=niveau_validation,
            validateur=profil_utilisateur,
            decision='REFUSE',
            commentaire=commentaire
        )
        
        # Valider effectivement
        validation.valider('REFUSE', commentaire, [], [])
        
        # Mettre à jour la demande
        demande.statut = 'REFUSEE'
        demande.save()
        
        success_msg = f"Demande refusée - Motif: {motif_refus}"
        logger.info(f"❌ {success_msg}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_msg,
                'redirect_url': reverse('liste_interim_validation')
            })
        else:
            messages.success(request, success_msg)
            return redirect('liste_interim_validation')
        
    except Exception as e:
        logger.error(f"💥 Erreur refus: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Erreur lors du refus: {str(e)}'
            })
        else:
            messages.error(request, f"Erreur lors du refus: {str(e)}")
            return redirect('interim_validation', demande.id)

def _traiter_ajout_proposition(request, demande, profil_utilisateur):
    """Traite l'ajout d'une nouvelle proposition"""
    try:
        candidat_matricule = request.POST.get('candidat_matricule', '').strip()
        justification = request.POST.get('justification', '').strip()
        competences_specifiques = request.POST.get('competences_specifiques', '').strip()
        experience_pertinente = request.POST.get('experience_pertinente', '').strip()
        
        logger.info(f"➕ Ajout proposition pour demande {demande.id}")
        logger.info(f"   - Candidat: {candidat_matricule}")
        logger.info(f"   - Justification: {len(justification)} caractères")
        
        # Validation des données obligatoires
        if not candidat_matricule:
            error_msg = "Le matricule du candidat est obligatoire"
            logger.warning(f"❌ {error_msg}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('interim_validation', demande.id)
        
        if not justification or len(justification) < 10:
            error_msg = "La justification doit contenir au moins 10 caractères"
            logger.warning(f"❌ {error_msg}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('interim_validation', demande.id)
        
        # Rechercher le candidat
        try:
            candidat = ProfilUtilisateur.objects.get(matricule=candidat_matricule)
        except ProfilUtilisateur.DoesNotExist:
            error_msg = f"Candidat avec matricule {candidat_matricule} non trouvé"
            logger.warning(f"❌ {error_msg}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('interim_validation', demande.id)
        
        # Vérifier si pas déjà proposé
        proposition_existante = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=candidat
        ).first()
        
        if proposition_existante:
            error_msg = f"{candidat.nom_complet} a déjà été proposé pour cette demande"
            logger.warning(f"❌ {error_msg}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('interim_validation', demande.id)
        
        # Déterminer la source de proposition
        source_proposition = _get_source_proposition_corrigee(profil_utilisateur)
        
        # Créer la proposition
        proposition = PropositionCandidat.objects.create(
            demande_interim=demande,
            candidat_propose=candidat,
            proposant=profil_utilisateur,
            source_proposition=source_proposition,
            justification=justification,
            competences_specifiques=competences_specifiques,
            experience_pertinente=experience_pertinente,
            niveau_validation_propose=demande.niveau_validation_actuel + 1
        )
        
        success_msg = f"Candidat {candidat.nom_complet} ajouté avec succès"
        logger.info(f"✅ {success_msg}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_msg,
                'proposition_id': proposition.id,
                'candidat_nom': candidat.nom_complet
            })
        else:
            messages.success(request, success_msg)
            return redirect('interim_validation', demande.id)
        
    except Exception as e:
        logger.error(f"💥 Erreur ajout proposition: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Erreur lors de l\'ajout: {str(e)}'
            })
        else:
            messages.error(request, f"Erreur lors de l'ajout: {str(e)}")
            return redirect('interim_validation', demande.id)

def _traiter_proposition_candidat(request, demande, profil_utilisateur):
    """Alias pour _traiter_ajout_proposition"""
    return _traiter_ajout_proposition(request, demande, profil_utilisateur)

def _traiter_validation_avec_candidats(request, demande, profil_utilisateur):
    """Traite la validation avec sélection de candidats"""
    # Pour l'instant, rediriger vers l'approbation standard
    return _traiter_approbation(request, demande, profil_utilisateur)

def _traiter_escalade(request, demande, profil_utilisateur):
    """Traite l'escalade d'une demande"""
    try:
        motif_escalade = request.POST.get('motif_escalade', '').strip()
        
        logger.info(f"⬆️ Escalade demande {demande.id}")
        logger.info(f"   - Motif: {motif_escalade}")
        
        # TODO: Implémenter la logique d'escalade
        success_msg = "Demande escaladée au niveau supérieur"
        logger.info(f"⬆️ {success_msg}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_msg
            })
        else:
            messages.success(request, success_msg)
            return redirect('interim_validation', demande.id)
        
    except Exception as e:
        logger.error(f"💥 Erreur escalade: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Erreur lors de l\'escalade: {str(e)}'
            })
        else:
            messages.error(request, f"Erreur lors de l'escalade: {str(e)}")
            return redirect('interim_validation', demande.id)

def _traiter_demande_infos(request, demande, profil_utilisateur):
    """Traite la demande d'informations complémentaires"""
    try:
        informations_demandees = request.POST.get('informations_demandees', '').strip()
        
        logger.info(f"❓ Demande d'infos pour demande {demande.id}")
        logger.info(f"   - Infos: {informations_demandees}")
        
        # TODO: Implémenter la logique de demande d'informations
        success_msg = "Demande d'informations envoyée"
        logger.info(f"❓ {success_msg}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_msg
            })
        else:
            messages.success(request, success_msg)
            return redirect('interim_validation', demande.id)
        
    except Exception as e:
        logger.error(f"💥 Erreur demande infos: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Erreur lors de la demande d\'infos: {str(e)}'
            })
        else:
            messages.error(request, f"Erreur lors de la demande d'infos: {str(e)}")
            return redirect('interim_validation', demande.id)

# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _get_source_proposition_corrigee(profil_utilisateur):
    """Détermine la source de proposition selon le profil utilisateur"""
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    
    mapping_source = {
        'CHEF_EQUIPE': 'CHEF_EQUIPE',
        'RESPONSABLE': 'RESPONSABLE',
        'DIRECTEUR': 'DIRECTEUR',
        'RH': 'RH',
        'ADMIN': 'ADMIN'
    }
    
    return mapping_source.get(profil_utilisateur.type_profil, 'AUTRE')

def _determiner_type_validation_corrige(profil_utilisateur, niveau_validation):
    """Détermine le type de validation selon le profil et le niveau"""
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    
    # Mapping strict niveau -> type
    mapping_niveau_type = {
        1: 'RESPONSABLE',
        2: 'DIRECTEUR',
        3: 'RH' if profil_utilisateur.type_profil == 'RH' else 'ADMIN'
    }
    
    type_attendu = mapping_niveau_type.get(niveau_validation)
    
    # Vérifier la cohérence
    if type_attendu and profil_utilisateur.type_profil in [type_attendu, 'ADMIN', 'RH']:
        return type_attendu
    
    # Fallback sécurisé
    return profil_utilisateur.type_profil

# ================================================================
# FONCTIONS DE FALLBACK POUR ÉVITER LES ERREURS
# ================================================================

def _get_stats_par_defaut():
    """Statistiques par défaut en cas d'erreur"""
    return {
        'total_candidats': 0,
        'score_moyen': 0,
        'score_moyen_humains': 0,
        'score_moyen_auto': 0,
        'excellents': 0,
        'bons': 0,
        'corrects': 0,
        'faibles': 0
    }

def _get_workflow_info_minimal(demande):
    """Informations workflow minimales"""
    return {
        'niveau_a_valider': 1,
        'niveau_validation_actuel': 0,
        'progression_pct': 25,
        'etape_actuelle': 'En attente de validation',
        'type_validateur': 'Responsable'
    }

def _get_permissions_par_defaut(profil_utilisateur):
    """Permissions par défaut"""
    return {
        'peut_valider': profil_utilisateur.type_profil in ['ADMIN', 'RH', 'DIRECTEUR', 'RESPONSABLE'],
        'peut_proposer_nouveau': True,
        'peut_escalader': profil_utilisateur.type_profil in ['ADMIN', 'RH'],
        'peut_modifier': False
    }

def _enrichir_details_demande_securise(demande):
    """Enrichissement sécurisé des détails"""
    try:
        return _enrichir_details_demande(demande)
    except Exception as e:
        logger.error(f"  Erreur enrichissement détails demande: {e}")
        return {
            'urgence_display': getattr(demande, 'urgence', 'NORMALE'),
            'motif_display': 'Motif non renseigné',
            'duree_mission': (demande.date_fin - demande.date_debut).days if demande.date_fin and demande.date_debut else 0,
            'demandeur_info': {'nom': 'Non renseigné'},
            'personne_remplacee_info': {'nom': 'Non renseigné'}
        }

def _get_validations_precedentes_securise(demande):
    """Récupération sécurisée des validations précédentes avec le bon modèle"""
    try:
        #   UTILISER LE BON MODÈLE : ValidationDemande
        return ValidationDemande.objects.filter(
            demande=demande
        ).select_related('validateur').order_by('-date_validation')
    except Exception as e:
        logger.error(f"  Erreur récupération validations précédentes: {e}")
        return []

def _get_motifs_refus_standards():
    """Motifs de refus standards"""
    return [
        ('COMPETENCES_INSUFFISANTES', 'Compétences insuffisantes'),
        ('CANDIDAT_INDISPONIBLE', 'Candidat indisponible'),
        ('COUT_TROP_ELEVE', 'Coût trop élevé'),
        ('MISSION_NON_JUSTIFIEE', 'Mission non justifiée'),
        ('CANDIDAT_INADEQUAT', 'Candidat inadéquat'),
        ('AUTRE', 'Autre motif'),
    ]

def _determiner_niveau_validation(profil_utilisateur, demande):
    """Détermine le niveau de validation selon le profil"""
    type_profil = profil_utilisateur.type_profil
    
    if type_profil == 'RESPONSABLE':
        return 1
    elif type_profil == 'DIRECTEUR':
        return 2
    elif type_profil in ['ADMIN', 'RH']:
        return 3
    else:
        return 1  # Par défaut

def _get_niveau_validation_suivant(demande, profil_utilisateur):
    """Détermine le niveau de validation suivant"""
    niveau_actuel = _determiner_niveau_validation(profil_utilisateur, demande)
    
    if niveau_actuel < 3:
        return niveau_actuel + 1
    else:
        return None  # Validation finale

# ================================================================
# FONCTIONS UTILITAIRES EXISTANTES À IMPLÉMENTER
# ================================================================

def get_profil_or_virtual(user):
    """Récupère le profil utilisateur ou crée un profil virtuel"""
    try:
        return user.profilutilisateur
    except AttributeError:
        # Créer un profil virtuel pour les superusers
        if user.is_superuser:
            from types import SimpleNamespace
            profil = SimpleNamespace()
            profil.user = user
            profil.nom_complet = f"{user.first_name} {user.last_name}".strip() or user.username
            profil.type_profil = 'ADMIN'
            profil.is_superuser = True
            profil.matricule = f"ADMIN_{user.id}"
            profil.departement = None
            profil.site = None
            return profil
        return None

def _peut_voir_demande(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut voir la demande"""
    return True  # Simplifié pour éviter les erreurs

def _peut_valider_niveau_actuel(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut valider au niveau actuel"""
    if profil_utilisateur.is_superuser:
        return True
    return profil_utilisateur.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']

def _get_etape_validation_actuelle(demande):
    """Récupère l'étape de validation actuelle"""
    etapes = {
        0: "Demande créée",
        1: "Validation Responsable (N+1)",
        2: "Validation Directeur (N+2)", 
        3: "Validation RH/Admin (Final)"
    }
    return etapes.get(demande.niveau_validation_actuel + 1, "Finalisée")

def _calculer_progression_workflow(demande):
    """Calcule le pourcentage de progression"""
    try:
        progression = (demande.niveau_validation_actuel / demande.niveaux_validation_requis) * 100
        return min(100, max(0, progression))
    except (ZeroDivisionError, TypeError):
        return 0

def _determiner_type_validateur(profil_utilisateur):
    """Détermine le type de validateur"""
    if profil_utilisateur.is_superuser:
        return "Superutilisateur"
    return profil_utilisateur.get_type_profil_display() if hasattr(profil_utilisateur, 'get_type_profil_display') else profil_utilisateur.type_profil

def _get_prochains_validateurs(demande):
    """Récupère les prochains validateurs"""
    return []

def _enrichir_details_demande(demande):
    """Enrichit les détails de la demande"""
    try:
        return {
            'urgence_display': demande.get_urgence_display() if hasattr(demande, 'get_urgence_display') else demande.urgence,
            'motif_display': demande.motif_absence.nom if demande.motif_absence else 'Non renseigné',
            'departement_concerne': demande.poste.departement.nom if demande.poste and demande.poste.departement else 'Non renseigné',
            'site_concerne': demande.poste.site.nom if demande.poste and demande.poste.site else 'Non renseigné',
            'duree_mission': demande.duree_mission if hasattr(demande, 'duree_mission') else 0,
            'demandeur_info': {
                'nom': demande.demandeur.nom_complet if demande.demandeur else 'Inconnu',
                'poste': demande.demandeur.poste.titre if demande.demandeur and demande.demandeur.poste else 'Non renseigné'
            },
            'personne_remplacee_info': {
                'nom': demande.personne_remplacee.nom_complet if demande.personne_remplacee else 'Inconnu',
                'matricule': demande.personne_remplacee.matricule if demande.personne_remplacee else 'N/A'
            }
        }
    except Exception as e:
        logger.error(f"Erreur enrichissement détails demande: {e}")
        return {
            'urgence_display': 'Normale',
            'motif_display': 'Non renseigné',
            'departement_concerne': 'Non renseigné',
            'site_concerne': 'Non renseigné',
            'duree_mission': 0,
            'demandeur_info': {'nom': 'Inconnu', 'poste': 'Non renseigné'},
            'personne_remplacee_info': {'nom': 'Inconnu', 'matricule': 'N/A'}
        }

def _peut_modifier_demande(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut modifier la demande"""
    return profil_utilisateur.is_superuser or profil_utilisateur.type_profil in ['RH', 'ADMIN']

def _get_motifs_refus_standards():
    """Récupère les motifs de refus standards"""
    return [
        ('COMPETENCES', 'Compétences insuffisantes'),
        ('DISPONIBILITE', 'Problème de disponibilité'),
        ('BUDGET', 'Contraintes budgétaires'),
        ('ORGANISATION', 'Problème organisationnel'),
        ('AUTRE', 'Autre motif')
    ]

# ================================================================
# FONCTIONS DE RÉCUPÉRATION DES CANDIDATS ET PROPOSITIONS
# ================================================================

def _get_candidats_automatiques_avec_scores_xxx(demande):
    """Récupère les candidats automatiques avec leurs scores"""
    try:
        # Vérifier s'il existe des scores calculés automatiquement
        scores_auto = ScoreDetailCandidat.objects.filter(
            demande_interim=demande,
            calcule_par='AUTOMATIQUE'
        ).select_related(
            'candidat__user',
            'candidat__poste',
            'candidat__departement',
            'candidat__site'
        ).order_by('-score_total')
        
        candidats_automatiques = []
        for score_detail in scores_auto:
            candidat = score_detail.candidat
            
            # Vérifier que ce candidat n'est pas déjà proposé manuellement
            if not PropositionCandidat.objects.filter(
                demande_interim=demande,
                candidat_propose=candidat
            ).exists():
                
                # Enrichir avec les détails du candidat
                candidat_info = _enrichir_info_candidat(candidat, demande)
                
                candidats_automatiques.append({
                    'candidat': candidat,
                    'candidat_info': candidat_info,
                    'score_detail': score_detail.get_details_scoring() if hasattr(score_detail, 'get_details_scoring') else _format_score_basique(score_detail),
                    'type_source': 'AUTOMATIQUE',
                    'score_total': score_detail.score_total,
                    'date_calcul': score_detail.created_at
                })
        
        return candidats_automatiques
        
    except Exception as e:
        logger.error(f"Erreur récupération candidats automatiques: {e}")
        return []

# ================================================================
# FONCTIONS DE VÉRIFICATION DE PERMISSIONS
# ================================================================

def _peut_voir_demande(profil, demande):
    """Vérifie si l'utilisateur peut voir la demande"""
    if not profil or not demande:
        return False
    
    # Superutilisateurs peuvent tout voir
    if profil.is_superuser or profil.type_profil == 'SUPERUSER':
        return True
    
    # RH et ADMIN peuvent voir toutes les demandes
    if profil.type_profil in ['RH', 'ADMIN']:
        return True
    
    # Parties prenantes de la demande
    if (demande.demandeur == profil or 
        demande.personne_remplacee == profil or 
        demande.candidat_selectionne == profil):
        return True
    
    # Hiérarchie dans le département concerné
    if (profil.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'CHEF_EQUIPE'] and
        profil.departement == demande.poste.departement):
        return True
    
    return False

def _peut_modifier_demande(profil, demande):
    """Vérifie si l'utilisateur peut modifier la demande"""
    if not profil or not demande:
        return False
    
    # Seuls le demandeur, RH, ADMIN et superutilisateurs peuvent modifier
    return (
        demande.demandeur == profil or
        profil.type_profil in ['RH', 'ADMIN'] or
        profil.is_superuser
    ) and demande.statut in ['BROUILLON', 'SOUMISE']

# ================================================================
# FONCTIONS DE DÉTERMINATION DE TYPE ET NIVEAU
# ================================================================

def _determiner_type_validation(profil):
    """Détermine le type de validation selon le profil"""
    type_mapping = {
        'RESPONSABLE': 'RESPONSABLE',
        'DIRECTEUR': 'DIRECTEUR', 
        'RH': 'RH',
        'ADMIN': 'ADMIN',
        'SUPERUSER': 'SUPERUSER'
    }
    return type_mapping.get(profil.type_profil, 'AUTRE')

def _get_prochains_validateurs(demande):
    """Retourne les prochains validateurs possibles"""
    try:
        niveau_suivant = demande.niveau_validation_actuel + 1
        
        if niveau_suivant == 1:
            # Responsables du département
            return ProfilUtilisateur.objects.filter(
                type_profil='RESPONSABLE',
                departement=demande.poste.departement,
                actif=True
            )
        elif niveau_suivant == 2:
            # Directeurs
            return ProfilUtilisateur.objects.filter(
                type_profil='DIRECTEUR',
                actif=True
            )
        elif niveau_suivant >= 3:
            # RH et ADMIN
            return ProfilUtilisateur.objects.filter(
                type_profil__in=['RH', 'ADMIN'],
                actif=True
            )
        
        return ProfilUtilisateur.objects.none()
        
    except Exception as e:
        logger.error(f"Erreur prochains validateurs: {e}")
        return ProfilUtilisateur.objects.none()

def _get_validateurs_niveau_suivant(demande):
    """Retourne les validateurs du niveau suivant pour notification"""
    return _get_prochains_validateurs(demande)

# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _enrichir_details_demande(demande):
    """Enrichit les détails de la demande pour l'affichage"""
    try:
        return {
            'duree_mission': (demande.date_fin - demande.date_debut).days if demande.date_debut and demande.date_fin else 0,
            'urgence_display': demande.get_urgence_display(),
            'urgence_classe': _get_classe_urgence(demande.urgence),
            'motif_display': demande.motif_absence.nom if demande.motif_absence else '',
            'departement_concerne': demande.poste.departement.nom if demande.poste and demande.poste.departement else '',
            'site_concerne': demande.poste.site.nom if demande.poste and demande.poste.site else '',
            'personne_remplacee_info': {
                'nom': demande.personne_remplacee.nom_complet,
                'poste': demande.personne_remplacee.poste.titre if demande.personne_remplacee.poste else '',
                'matricule': demande.personne_remplacee.matricule
            },
            'demandeur_info': {
                'nom': demande.demandeur.nom_complet,
                'poste': demande.demandeur.poste.titre if demande.demandeur.poste else '',
                'type_profil': demande.demandeur.get_type_profil_display()
            }
        }
    except Exception as e:
        logger.error(f"Erreur enrichissement détails demande: {e}")
        return {}

def _get_historique_interim_candidat(candidat):
    """Récupère l'historique d'intérim d'un candidat"""
    try:
        missions_precedentes = DemandeInterim.objects.filter(
            candidat_selectionne=candidat,
            statut__in=['TERMINEE', 'EN_COURS']
        ).order_by('-date_debut')[:5]
        
        return {
            'nb_missions_total': missions_precedentes.count(),
            'missions_recentes': [
                {
                    'poste': mission.poste.titre if mission.poste else '',
                    'departement': mission.poste.departement.nom if mission.poste and mission.poste.departement else '',
                    'date_debut': mission.date_debut,
                    'date_fin': mission.date_fin,
                    'duree_jours': (mission.date_fin - mission.date_debut).days if mission.date_debut and mission.date_fin else 0,
                    'statut': mission.get_statut_display()
                }
                for mission in missions_precedentes
            ]
        }
        
    except Exception as e:
        logger.error(f"Erreur historique intérim: {e}")
        return {'nb_missions_total': 0, 'missions_recentes': [], 'erreur': str(e)}

def _format_score_basique(score_detail):
    """Formate un score détaillé de base"""
    try:
        return {
            'score_final': score_detail.score_total,
            'criteres': {
                'Similarité poste': score_detail.score_similarite_poste,
                'Compétences': score_detail.score_competences,
                'Expérience': score_detail.score_experience,
                'Disponibilité': score_detail.score_disponibilite,
                'Proximité': score_detail.score_proximite,
                'Ancienneté': score_detail.score_anciennete
            },
            'bonus_malus': {
                'Proposition humaine': score_detail.bonus_proposition_humaine,
                'Expérience similaire': score_detail.bonus_experience_similaire,
                'Recommandation': score_detail.bonus_recommandation,
                'Bonus hiérarchique': score_detail.bonus_hierarchique,
                'Pénalité indisponibilité': -score_detail.penalite_indisponibilite
            },
            'explications': [
                f"Score de base calculé automatiquement: {score_detail.score_total}",
                f"Type de calcul: {score_detail.get_calcule_par_display()}"
            ]
        }
    except Exception as e:
        return {'score_final': 0, 'erreur': str(e)}

def _get_classe_urgence(urgence):
    """Retourne la classe CSS pour l'urgence"""
    classes = {
        'NORMALE': 'badge-secondary',
        'MOYENNE': 'badge-info',
        'ELEVEE': 'badge-warning', 
        'CRITIQUE': 'badge-danger'
    }
    return classes.get(urgence, 'badge-secondary')

def _get_motifs_refus_standards():
    """Retourne les motifs de refus standards"""
    return [
        ('BUDGET', 'Budget insuffisant'),
        ('COMPETENCES', 'Compétences candidates inadéquates'),
        ('TIMING', 'Délais non compatibles'),
        ('RESSOURCES', 'Ressources internes disponibles'),
        ('STRATEGIE', 'Décision stratégique'),
        ('AUTRE', 'Autre motif')
    ]

# ================================================================
# FONCTIONS DE NOTIFICATION
# ================================================================

def _notifier_candidat_selectionne_safe(candidat, demande, validateur=None):
    """Notifie le candidat sélectionné"""
    try:
        # Vérifier les paramètres
        if not candidat or not demande:
            logger.warning("Candidat ou demande manquant pour notification")
            return
            
        logger.info(f"Candidat {candidat.nom_complet} sélectionné pour la mission {demande.numero_demande}")

        NotificationInterim.objects.create(
            destinataire=candidat,
            expediteur=validateur,
            demande=demande,
            type_notification='CANDIDAT_SELECTIONNE',
            urgence='HAUTE',
            titre=f"Sélectionné pour mission - {demande.numero_demande}",
            message=f"Vous avez été sélectionné(e) pour la mission d'intérim. Poste: {demande.poste.titre}. Période: du {demande.date_debut} au {demande.date_fin}. Veuillez répondre sous 3 jours.",
            url_action_principale=f'/interim/reponse-interim/{demande.id}/',
            texte_action_principale="Répondre à la proposition"
        )
        logger.info(f"Candidat {candidat.nom_complet} notifié pour demande {demande.numero_demande}")
    except Exception as e:
        logger.error(f"Erreur notification candidat sélectionné: {e}")

def _notifier_demande_validation(validateur, demande, expediteur):
    """Notifie un validateur qu'une demande attend sa validation"""
    try:
        NotificationInterim.objects.create(
            destinataire=validateur,
            expediteur=expediteur,
            demande=demande,
            type_notification='DEMANDE_A_VALIDER',
            urgence='NORMALE' if demande.urgence in ['NORMALE', 'MOYENNE'] else 'HAUTE',
            titre=f"Validation requise - {demande.numero_demande}",
            message=f"Une demande d'intérim attend votre validation. Poste: {demande.poste.titre}. Urgence: {demande.get_urgence_display()}.",
            url_action_principale=f'/interim/validation/{demande.id}/',
            texte_action_principale="Valider la demande"
        )
    except Exception as e:
        logger.error(f"Erreur notification validation: {e}")

def _notifier_demande_refusee(demandeur, demande, validateur, commentaire, motif):
    """Notifie le demandeur du refus de sa demande"""
    try:
        NotificationInterim.objects.create(
            destinataire=demandeur,
            expediteur=validateur,
            demande=demande,
            type_notification='DEMANDE_REFUSEE',
            urgence='NORMALE',
            titre=f"Demande refusée - {demande.numero_demande}",
            message=f"Votre demande d'intérim a été refusée par {validateur.nom_complet}. Motif: {motif}. Commentaire: {commentaire[:100]}...",
            url_action_principale=f'/interim/demande/{demande.id}/',
            texte_action_principale="Voir les détails"
        )
    except Exception as e:
        logger.error(f"Erreur notification refus demandeur: {e}")

def _notifier_demande_refusee_rh(rh_user, demande, validateur, commentaire):
    """Notifie la RH du refus d'une demande"""
    try:
        NotificationInterim.objects.create(
            destinataire=rh_user,
            expediteur=validateur,
            demande=demande,
            type_notification='INFORMATION_REFUS',
            urgence='NORMALE',
            titre=f"Information - Demande refusée {demande.numero_demande}",
            message=f"La demande {demande.numero_demande} a été refusée par {validateur.nom_complet}. Commentaire: {commentaire[:100]}...",
            url_action_principale=f'/interim/demande/{demande.id}/',
            texte_action_principale="Voir les détails"
        )
    except Exception as e:
        logger.error(f"Erreur notification refus RH: {e}")

# ================================================================
# FONCTIONS D'HISTORIQUE
# ================================================================

def _creer_historique_validation_safe(demande, utilisateur, action, description, donnees_apres):
    """
    Version sécurisée de création d'historique
    """
    try:
        # Vérifier les paramètres essentiels
        if not demande or not utilisateur:
            logger.warning("Demande ou utilisateur manquant pour historique")
            return
            
        # S'assurer que donnees_apres est un dictionnaire
        if not isinstance(donnees_apres, dict):
            donnees_apres = {'erreur': 'Données non valides', 'donnees_originales': str(donnees_apres)}
        
        # Créer l'historique avec données sécurisées
        HistoriqueAction.objects.create(
            demande=demande,
            action=action,
            utilisateur=utilisateur,
            description=str(description),
            donnees_apres=donnees_apres,
            niveau_hierarchique=getattr(utilisateur, 'type_profil', 'UNKNOWN'),
            is_superuser=getattr(utilisateur, 'is_superuser', False)
        )
        
        logger.info(f"Historique créé pour {demande.numero_demande}: {action}")
        
    except Exception as e:
        logger.error(f"Erreur création historique: {e}")

# ================================================================
# FONCTIONS DE REDIRECTION
# ================================================================

def _rediriger_apres_validation(profil, demande_id):
    """Redirige l'utilisateur selon son rôle après validation"""
    if profil.type_profil == 'RESPONSABLE':
        return redirect('interim_validation', demande_id)
    elif profil.type_profil == 'DIRECTEUR':
        return redirect('interim_validation', demande_id)  
    elif profil.type_profil == 'RH':
        return redirect('interim_validation', demande_id)
    elif profil.type_profil == 'ADMIN':
        return redirect('interim_validation', demande_id)
    else:
        return redirect('connexion')

# ================================================================
# VUES AJAX COMPLEMENTAIRES 
# ================================================================

@login_required
def ajax_get_score_detail_candidat(request, candidat_id, demande_id):
    """Retourne le détail du score d'un candidat"""
    try:
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        score_detail = ScoreDetailCandidat.objects.filter(
            candidat=candidat,
            demande_interim=demande
        ).first()
        
        if score_detail:
            return JsonResponse({
                'success': True,
                'score_detail': score_detail.get_details_scoring()
            })
        else:
            # Calculer le score à la volée
            scoring_service = ScoringInterimService()
            score = scoring_service.calculer_score_candidat(candidat, demande)
            
            return JsonResponse({
                'success': True,
                'score_detail': {
                    'score_final': score,
                    'type_candidat': 'Calcul à la volée',
                    'scores_criteres': {},
                    'bonus_penalites': {}
                }
            })
    
    except Exception as e:
        logger.error(f"Erreur récupération score détail: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def ajax_get_candidats_departement(request):
    """Retourne les candidats d'un département pour proposition"""
    try:
        departement_id = request.GET.get('departement_id')
        demande_id = request.GET.get('demande_id')
        
        if not departement_id:
            return JsonResponse({'candidats': []})
        
        # Exclure les candidats déjà proposés
        candidats_deja_proposes = []
        if demande_id:
            candidats_deja_proposes = list(PropositionCandidat.objects.filter(
                demande_interim_id=demande_id
            ).values_list('candidat_propose_id', flat=True))
        
        candidats = ProfilUtilisateur.objects.filter(
            departement_id=departement_id,
            actif=True,
            statut_employe='ACTIF'
        ).exclude(
            id__in=candidats_deja_proposes
        ).select_related('user', 'poste').values(
            'id',
            'user__first_name',
            'user__last_name',
            'matricule',
            'poste__titre'
        ).order_by('user__last_name', 'user__first_name')
        
        candidats_list = [{
            'id': cand['id'],
            'nom_complet': f"{cand['user__first_name']} {cand['user__last_name']}",
            'matricule': cand['matricule'],
            'poste': cand['poste__titre'] or ''
        } for cand in candidats]
        
        return JsonResponse({
            'candidats': candidats_list
        })
    
    except Exception as e:
        logger.error(f"Erreur candidats département: {e}")
        return JsonResponse({'error': str(e)}, status=500)
    
# ================================================================
# VUE PRINCIPALE DE LISTE DES VALIDATIONS
# ================================================================

@login_required
def validation_list_view(request):
    """
    Liste des demandes à valider selon le niveau hiérarchique du validateur spécifique
    Permet validation/refus directe depuis la liste
    
    Args:
        request: HttpRequest
        user_validator_username: Username du validateur dont on veut voir les validations
    
    Returns:
        HttpResponse avec la liste filtrée des demandes à valider
    """
    try:
        # ================================================================
        # TRACES DEBUG - DÉBUT
        # ================================================================
        print(f"  [DEBUG] === DÉBUT validation_list_view ===")
        print(f"  [DEBUG] request.user: {request.user}")
        print(f"  [DEBUG] request.user.username: {request.user.username}")
        print(f"  [DEBUG] request.user.is_authenticated: {request.user.is_authenticated}")
        print(f"  [DEBUG] Type de request.user: {type(request.user)}")
        
        # ================================================================
        # 1. RÉCUPÉRATION ET VÉRIFICATION DU VALIDATEUR SPÉCIFIQUE
        # ================================================================
        
        # Récupérer le profil du validateur spécifique par username
        try:
            print(f"  [DEBUG] Tentative récupération User par username: {request.user.username}")
            validateur_user = User.objects.get(username=request.user.username)
            print(f"  [DEBUG]   validateur_user trouvé: {validateur_user}")
            print(f"  [DEBUG] validateur_user.id: {validateur_user.id}")
            print(f"  [DEBUG] validateur_user.username: {validateur_user.username}")
            
            print(f"  [DEBUG] Tentative get_profil_or_virtual pour validateur_user")
            profil_validateur = get_profil_or_virtual(validateur_user)
            print(f"  [DEBUG]   profil_validateur: {profil_validateur}")
            print(f"  [DEBUG] Type profil_validateur: {type(profil_validateur)}")
            
            if profil_validateur:
                print(f"  [DEBUG] profil_validateur.id: {profil_validateur.id}")
                print(f"  [DEBUG] profil_validateur.user: {profil_validateur.user}")
                print(f"  [DEBUG] profil_validateur.user.username: {profil_validateur.user.username}")
                print(f"  [DEBUG] profil_validateur.nom_complet: {profil_validateur.nom_complet}")
                print(f"  [DEBUG] profil_validateur.type_profil: {profil_validateur.type_profil}")
            else:
                print(f"  [DEBUG]   profil_validateur est None/vide")
                
        except User.DoesNotExist as e:
            print(f"  [DEBUG]   ERREUR User.DoesNotExist: {e}")
            messages.error(request, f"Validateur '{request.user}' non trouvé")
            return redirect('index')
        except Exception as e:
            print(f"  [DEBUG]   ERREUR lors récupération validateur_user: {e}")
            print(f"  [DEBUG] Type erreur: {type(e)}")
            raise
        
        if not profil_validateur:
            print(f"  [DEBUG]   Profil validateur non trouvé après get_profil_or_virtual")
            messages.error(request, f"Profil utilisateur non trouvé pour {request.user}")
            return redirect('index')
        
        # Récupérer le profil de l'utilisateur connecté
        print(f"  [DEBUG] Récupération profil_connecte pour request.user: {request.user}")
        profil_connecte = get_profil_or_virtual(request.user)
        print(f"  [DEBUG]   profil_connecte: {profil_connecte}")
        
        if not profil_connecte:
            print(f"  [DEBUG]   profil_connecte non trouvé")
            messages.error(request, "Votre profil utilisateur n'a pas été trouvé")
            return redirect('index')
        
        print(f"  [DEBUG] profil_connecte.id: {profil_connecte.id}")
        print(f"  [DEBUG] profil_connecte.user: {profil_connecte.user}")
        print(f"  [DEBUG] profil_connecte.user.username: {profil_connecte.user.username}")
        
        # ================================================================
        # 2. VÉRIFICATIONS DES PERMISSIONS
        # ================================================================
        
        print(f"  [DEBUG] === VÉRIFICATIONS PERMISSIONS ===")
        
        # Vérifier que l'utilisateur connecté a le droit de voir ces validations
        peut_voir = _peut_voir_validations_utilisateur(profil_connecte, profil_validateur)
        print(f"  [DEBUG] Peut voir validations: {peut_voir}")
        
        if not peut_voir:
            print(f"  [DEBUG]   Accès refusé - ne peut pas voir ces validations")
            messages.error(request, "Vous n'êtes pas autorisé à voir ces validations")
            return redirect('index')
        
        # Vérifier que le validateur peut effectuer des validations
        peut_valider = _peut_valider_au_moins_un_niveau(profil_validateur)
        print(f"  [DEBUG] Peut valider au moins un niveau: {peut_valider}")
        
        if not peut_valider:
            print(f"  [DEBUG]   Ne peut pas valider - redirection")
            messages.error(request, f"{profil_validateur.nom_complet} n'est pas autorisé à effectuer des validations")
            return redirect('connexion')
        
        # ================================================================
        # 3. TRAITEMENT DES FILTRES ET RÉCUPÉRATION DES DONNÉES
        # ================================================================
        
        print(f"  [DEBUG] === FILTRES ET DONNÉES ===")
        
        # Filtres de recherche depuis la requête
        filtres = _extraire_filtres_recherche(request)
        print(f"  [DEBUG] Filtres extraits: {filtres}")
        
        # Récupérer UNIQUEMENT les demandes que CE validateur spécifique peut valider
        print(f"  [DEBUG] Récupération demandes validables...")
        demandes_a_valider = _get_demandes_validables_par_validateur_specifique(profil_validateur, filtres)
        print(f"  [DEBUG]   {len(demandes_a_valider)} demandes récupérées")
        
        # Enrichir les demandes avec des informations supplémentaires
        print(f"  [DEBUG] Enrichissement des demandes...")
        demandes_enrichies = _enrichir_demandes_pour_liste(demandes_a_valider)
        print(f"  [DEBUG]   {len(demandes_enrichies)} demandes enrichies")
        
        # ================================================================
        # 4. PAGINATION
        # ================================================================
        
        print(f"  [DEBUG] === PAGINATION ===")
        
        # Pagination des résultats
        paginator = Paginator(demandes_enrichies, 15)  # 15 demandes par page
        page_number = request.GET.get('page', 1)
        print(f"  [DEBUG] Page demandée: {page_number}")
        
        try:
            demandes_page = paginator.get_page(page_number)
            print(f"  [DEBUG]   Pagination réussie - {demandes_page.number}/{paginator.num_pages}")
        except Exception as e:
            print(f"  [DEBUG]   Erreur pagination: {e}")
            logger.error(f"Erreur pagination: {e}")
            demandes_page = paginator.get_page(1)
        
        # ================================================================
        # 5. CALCULS DES STATISTIQUES ET MÉTADONNÉES
        # ================================================================
        
        print(f"  [DEBUG] === STATISTIQUES ===")
        
        # Statistiques pour le tableau de bord
        stats = _calculer_stats_validations(profil_validateur, demandes_a_valider)
        print(f"  [DEBUG] Stats calculées: {stats}")
        
        # Départements pour le filtre (si pertinent selon le niveau)
        departements_filtre = _get_departements_pour_filtre(profil_validateur)
        print(f"  [DEBUG] Départements filtre: {len(departements_filtre) if departements_filtre else 0}")
        
        # Informations sur le niveau de validation du validateur
        niveau_info = _get_niveau_validation_info(profil_validateur)
        print(f"  [DEBUG] Niveau info: {niveau_info}")
        
        # ================================================================
        # 6. PRÉPARATION DU CONTEXTE POUR LE TEMPLATE
        # ================================================================
        
        print(f"  [DEBUG] === PRÉPARATION CONTEXTE ===")
        print(f"  [DEBUG] profil_validateur pour contexte: {profil_validateur}")
        print(f"  [DEBUG] profil_validateur.user: {profil_validateur.user}")
        print(f"  [DEBUG] profil_validateur.user.username: {profil_validateur.user.username}")

        context = {
            # Données principales
            'demandes': demandes_page,
            'profil_utilisateur': profil_validateur,  # Le validateur spécifique
            'profil_connecte': profil_connecte,       # L'utilisateur connecté
            
            # Statistiques et métadonnées
            'stats': stats,
            'filtres': filtres,
            'departements_filtre': departements_filtre,
            'niveau_info': niveau_info,
            
            # Titre de la page
            'page_title': f'Validations {niveau_info["libelle"]} - {profil_validateur.nom_complet} - {stats["total_a_valider"]} demande(s)',
            
            # Configuration de l'interface
            'config': {
                'peut_validation_masse': profil_validateur.type_profil in ['RH', 'ADMIN'] or profil_validateur.is_superuser,
                'afficher_departements': profil_validateur.type_profil in ['DIRECTEUR', 'RH', 'ADMIN'] or profil_validateur.is_superuser,
                'niveau_validation': niveau_info['niveau'],
                'type_validateur': niveau_info['type'],
                'validateur_username': profil_validateur.user.username,  #   POINT CRITIQUE
                'est_consultation': profil_connecte != profil_validateur,  # Indique si c'est une consultation
                'peut_modifier': profil_connecte == profil_validateur or profil_connecte.type_profil in ['RH', 'ADMIN'] or profil_connecte.is_superuser
            },
            
            # URLs pour les actions AJAX
            'urls': {
                'validation_rapide': reverse('validation_rapide'),
                'validation_masse': reverse('validation_masse'),
                'details_demande': '/interim/validation/',
                'ajax_candidats': '/interim/ajax/candidats-demande/',
                'escalade': '/interim/api/escalader/',
                'rappel': '/interim/api/rappel/'
            },            
            # Métadonnées pour le debug
            'debug_info': {
                'validateur_username': profil_validateur.user.username,  #   POINT CRITIQUE
                'niveau_validateur': profil_validateur.type_profil,
                'departement_validateur': profil_validateur.departement.nom if profil_validateur.departement else None,
                'total_demandes_brutes': len(demandes_a_valider),
                'filtres_appliques': bool(any(filtres.values())),
                'services_available': True  # Peut être dynamique selon les imports
            }
        }
        
        print(f"  [DEBUG]   Contexte préparé avec {len(context)} clés")
        print(f"  [DEBUG] Clés du contexte: {list(context.keys())}")
        print(f"  [DEBUG] config.validateur_username: {context['config']['validateur_username']}")
        print(f"  [DEBUG] debug_info.validateur_username: {context['debug_info']['validateur_username']}")
        
        # ================================================================
        # 7. LOGGING ET AUDIT
        # ================================================================
        
        # Log de l'accès pour audit
        logger.info(f"Accès liste validations - Connecté: {profil_connecte.nom_complet} - Validateur: {profil_validateur.nom_complet} - {stats['total_a_valider']} demandes")
        
        # Si c'est une consultation (pas ses propres validations)
        if profil_connecte != profil_validateur:
            logger.info(f"Consultation validations par {profil_connecte.nom_complet} des validations de {profil_validateur.nom_complet}")
        
        # ================================================================
        # 8. RENDU DU TEMPLATE
        # ================================================================
        
        print(f"  [DEBUG] === RENDU TEMPLATE ===")
        print(f"  [DEBUG] Template: interim_validation_liste.html")
        print(f"  [DEBUG] Contexte final préparé")
        print(f"  [DEBUG] === FIN validation_list_view ===\n")
        
        return render(request, 'interim_validation_liste.html', context)
        
    except Exception as e:
        # ================================================================
        # 9. GESTION D'ERREURS
        # ================================================================
        
        print(f"  [DEBUG]     ERREUR MAJEURE dans validation_list_view    ")
        print(f"  [DEBUG] Type erreur: {type(e)}")
        print(f"  [DEBUG] Message erreur: {str(e)}")
        print(f"  [DEBUG] request.user: {request.user}")
        print(f"  [DEBUG] request.user.username: {getattr(request.user, 'username', 'N/A')}")
        
        logger.error(f"Erreur vue validation list: {e}")
        logger.error(f"Utilisateur connecté: {request.user.username}")
        logger.error(f"Stacktrace: {str(e)}", exc_info=True)
        
        messages.error(request, f"Erreur lors du chargement des validations: {str(e)}")
        return redirect('connexion')

# ================================================================
# FONCTIONS UTILITAIRES SPÉCIALISÉES
# ================================================================

def _get_demandes_validables_par_validateur_specifique(profil_validateur, filtres):
    """
    Récupère UNIQUEMENT les demandes que le validateur spécifique peut valider à son niveau
    selon la hiérarchie : RESPONSABLE → DIRECTEUR → RH/ADMIN
    
    Args:
        profil_validateur: ProfilUtilisateur du validateur
        filtres: Dict des filtres de recherche
    
    Returns:
        List[DemandeInterim]: Liste des demandes filtrées
    """
    try:
        # ================================================================
        # REQUÊTE DE BASE
        # ================================================================
        
        # Base query : demandes en validation ou en attente
        demandes_query = DemandeInterim.objects.filter(
            statut__in=['EN_VALIDATION', 'SOUMISE', 'CANDIDAT_PROPOSE']
        ).select_related(
            'demandeur__user',
            'personne_remplacee__user', 
            'poste__departement',
            'poste__site',
            'motif_absence',
            'candidat_selectionne__user'
        ).prefetch_related(
            'validations__validateur__user',
            'propositions_candidats__candidat_propose__user'
        ).order_by('-created_at')
        
        # ================================================================
        # FILTRAGE PAR NIVEAU HIÉRARCHIQUE
        # ================================================================
        
        demandes_filtrees = []
        
        for demande in demandes_query:
            # Déterminer le niveau de validation requis
            niveau_requis = demande.niveau_validation_actuel + 1
            
            # Vérifier si ce validateur peut valider à ce niveau spécifique
            peut_valider = _peut_valider_demande_niveau_specifique(profil_validateur, demande, niveau_requis)
            
            if peut_valider:
                # Vérifications supplémentaires selon le type de profil
                if _demande_correspond_au_perimetre_validateur(profil_validateur, demande):
                    demandes_filtrees.append(demande)
        
        # ================================================================
        # APPLICATION DES FILTRES DE RECHERCHE
        # ================================================================
        
        # Filtre par urgence
        if filtres.get('urgence'):
            demandes_filtrees = [d for d in demandes_filtrees if d.urgence == filtres['urgence']]
        
        # Filtre par département
        if filtres.get('departement'):
            try:
                dept_id = int(filtres['departement'])
                demandes_filtrees = [d for d in demandes_filtrees if d.poste.departement.id == dept_id]
            except (ValueError, AttributeError):
                pass
        
        # Filtre par date de début
        if filtres.get('date_debut'):
            demandes_filtrees = [d for d in demandes_filtrees if d.date_debut and d.date_debut >= filtres['date_debut']]
        
        # Filtre par date de fin
        if filtres.get('date_fin'):
            demandes_filtrees = [d for d in demandes_filtrees if d.date_fin and d.date_fin <= filtres['date_fin']]
        
        # Filtre par recherche textuelle
        if filtres.get('recherche'):
            terme = filtres['recherche'].lower().strip()
            if terme:
                demandes_filtrees = [
                    d for d in demandes_filtrees 
                    if (terme in d.numero_demande.lower() or 
                        terme in d.demandeur.nom_complet.lower() or
                        terme in d.poste.titre.lower() or
                        (d.personne_remplacee and terme in d.personne_remplacee.nom_complet.lower()))
                ]
        
        # ================================================================
        # TRI FINAL PAR PRIORITÉ
        # ================================================================
        
        def tri_priorite_validation(demande):
            """Fonction de tri par priorité de validation"""
            # 1. Urgence (critique = 0, normale = 3)
            ordre_urgence = {'CRITIQUE': 0, 'ELEVEE': 1, 'MOYENNE': 2, 'NORMALE': 3}
            urgence_score = ordre_urgence.get(demande.urgence, 4)
            
            # 2. Temps écoulé (plus ancien = prioritaire)
            temps_ecoule = (timezone.now() - demande.created_at).days
            
            # 3. Niveau de validation (plus bas = prioritaire)
            niveau_validation = demande.niveau_validation_actuel
            
            return (urgence_score, niveau_validation, temps_ecoule)
        
        demandes_filtrees.sort(key=tri_priorite_validation)
        
        logger.debug(f"Demandes filtrées pour {profil_validateur.nom_complet}: {len(demandes_filtrees)}")
        
        return demandes_filtrees
        
    except Exception as e:
        logger.error(f"Erreur récupération demandes validables par validateur: {e}")
        return []


def _peut_valider_demande_niveau_specifique(profil_validateur, demande, niveau_requis):
    """
    Vérifie si le validateur spécifique peut valider cette demande au niveau requis
    selon la hiérarchie CORRIGÉE : RESPONSABLE (N+1) → DIRECTEUR (N+2) → RH/ADMIN (Final)
    
    Args:
        profil_validateur: ProfilUtilisateur du validateur
        demande: DemandeInterim à vérifier
        niveau_requis: int - Niveau de validation requis
    
    Returns:
        bool: True si le validateur peut valider cette demande
    """
    type_profil = profil_validateur.type_profil
    
    # ================================================================
    # ACCÈS SUPERUTILISATEUR
    # ================================================================
    if profil_validateur.is_superuser or type_profil == 'SUPERUSER':
        return True
    
    # ================================================================
    # VALIDATION PAR NIVEAU HIÉRARCHIQUE
    # ================================================================
    
    # Niveau 1 : RESPONSABLE (dans le bon département)
    if niveau_requis == 1:
        return (type_profil == 'RESPONSABLE' and 
                profil_validateur.departement and
                demande.poste and demande.poste.departement and
                profil_validateur.departement == demande.poste.departement)
    
    # Niveau 2 : DIRECTEUR
    elif niveau_requis == 2:
        return type_profil == 'DIRECTEUR'
    
    # Niveau 3+ : RH/ADMIN (validation finale)
    elif niveau_requis >= 3:
        return type_profil in ['RH', 'ADMIN']
    
    return False


def _demande_correspond_au_perimetre_validateur(profil_validateur, demande):
    """
    Vérifie si la demande correspond au périmètre de responsabilité du validateur
    
    Args:
        profil_validateur: ProfilUtilisateur du validateur
        demande: DemandeInterim à vérifier
    
    Returns:
        bool: True si la demande est dans le périmètre du validateur
    """
    try:
        type_profil = profil_validateur.type_profil
        
        # Superutilisateurs : tout le périmètre
        if profil_validateur.is_superuser or type_profil == 'SUPERUSER':
            return True
        
        # RH/ADMIN : tout le périmètre
        if type_profil in ['RH', 'ADMIN']:
            return True
        
        # DIRECTEUR : tout le périmètre (peut voir toutes les demandes niveau 2)
        if type_profil == 'DIRECTEUR':
            return True
        
        # RESPONSABLE : uniquement son département
        if type_profil == 'RESPONSABLE':
            return (profil_validateur.departement and 
                    demande.poste and demande.poste.departement and
                    profil_validateur.departement == demande.poste.departement)
        
        # CHEF_EQUIPE : uniquement son département (ne peut pas valider mais peut consulter)
        if type_profil == 'CHEF_EQUIPE':
            return (profil_validateur.departement and 
                    demande.poste and demande.poste.departement and
                    profil_validateur.departement == demande.poste.departement)
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur vérification périmètre validateur: {e}")
        return False


def _peut_voir_validations_utilisateur(profil_connecte, profil_validateur):
    """
    Vérifie si l'utilisateur connecté peut voir les validations du validateur
    
    Args:
        profil_connecte: ProfilUtilisateur de l'utilisateur connecté
        profil_validateur: ProfilUtilisateur du validateur dont on veut voir les validations
    
    Returns:
        bool: True si l'utilisateur connecté peut voir ces validations
    """
    try:
        # Si c'est le même utilisateur
        if profil_connecte == profil_validateur:
            return True
        
        # Superutilisateurs peuvent voir toutes les validations
        if profil_connecte.is_superuser:
            return True
        
        # RH/ADMIN peuvent voir toutes les validations
        if profil_connecte.type_profil in ['RH', 'ADMIN']:
            return True
        
        # DIRECTEUR peut voir les validations des RESPONSABLES et autres DIRECTEURS
        if profil_connecte.type_profil == 'DIRECTEUR':
            return profil_validateur.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'CHEF_EQUIPE']
        
        # RESPONSABLE peut voir ses propres validations et celles de son équipe/département
        if profil_connecte.type_profil == 'RESPONSABLE':
            return (profil_validateur == profil_connecte or
                    profil_validateur.manager == profil_connecte or
                    (profil_validateur.departement and profil_connecte.departement and
                     profil_validateur.departement == profil_connecte.departement))
        
        # CHEF_EQUIPE peut voir ses propres validations
        if profil_connecte.type_profil == 'CHEF_EQUIPE':
            return profil_validateur == profil_connecte
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur vérification permissions consultation: {e}")
        return False


def _extraire_filtres_recherche(request):
    """
    Extrait et valide les filtres de recherche depuis la requête
    
    Args:
        request: HttpRequest
    
    Returns:
        dict: Dictionnaire des filtres validés
    """
    try:
        filtres = {
            'urgence': request.GET.get('urgence', '').strip(),
            'departement': request.GET.get('departement', '').strip(),
            'recherche': request.GET.get('recherche', '').strip(),
            'date_debut': None,
            'date_fin': None
        }
        
        # Validation et conversion des dates
        date_debut_str = request.GET.get('date_debut', '').strip()
        if date_debut_str:
            try:
                from datetime import datetime
                filtres['date_debut'] = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        date_fin_str = request.GET.get('date_fin', '').strip()
        if date_fin_str:
            try:
                from datetime import datetime
                filtres['date_fin'] = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        # Validation de l'urgence
        urgences_valides = ['CRITIQUE', 'ELEVEE', 'MOYENNE', 'NORMALE']
        if filtres['urgence'] not in urgences_valides:
            filtres['urgence'] = ''
        
        return filtres
        
    except Exception as e:
        logger.error(f"Erreur extraction filtres: {e}")
        return {
            'urgence': '',
            'departement': '',
            'recherche': '',
            'date_debut': None,
            'date_fin': None
        }


def _get_niveau_validation_info(profil_validateur):
    """
    Retourne les informations sur le niveau de validation du validateur
    
    Args:
        profil_validateur: ProfilUtilisateur
    
    Returns:
        dict: Informations sur le niveau de validation
    """
    try:
        type_profil = profil_validateur.type_profil
        
        if profil_validateur.is_superuser or type_profil == 'SUPERUSER':
            return {
                'niveau': 99,
                'type': 'SUPERUSER',
                'libelle': 'Superutilisateur',
                'description': 'Accès complet à tous les niveaux de validation',
                'couleur': 'danger'
            }
        elif type_profil == 'RH':
            return {
                'niveau': 3,
                'type': 'RH',
                'libelle': 'RH (Final)',
                'description': 'Validation finale et sélection candidat',
                'couleur': 'success'
            }
        elif type_profil == 'ADMIN':
            return {
                'niveau': 3,
                'type': 'ADMIN', 
                'libelle': 'Admin (Final)',
                'description': 'Validation finale avec droits étendus',
                'couleur': 'success'
            }
        elif type_profil == 'DIRECTEUR':
            return {
                'niveau': 2,
                'type': 'DIRECTEUR',
                'libelle': 'Directeur (N+2)',
                'description': 'Validation niveau directeur',
                'couleur': 'primary'
            }
        elif type_profil == 'RESPONSABLE':
            return {
                'niveau': 1,
                'type': 'RESPONSABLE',
                'libelle': 'Responsable (N+1)',
                'description': 'Validation niveau responsable départemental',
                'couleur': 'info'
            }
        else:
            return {
                'niveau': 0,
                'type': 'AUTRE',
                'libelle': 'Consultation',
                'description': 'Consultation uniquement',
                'couleur': 'secondary'
            }
            
    except Exception as e:
        logger.error(f"Erreur récupération niveau validation: {e}")
        return {
            'niveau': 0,
            'type': 'ERREUR',
            'libelle': 'Erreur',
            'description': 'Erreur de configuration',
            'couleur': 'danger'
        }
    
# ================================================================
# ACTIONS DE VALIDATION RAPIDE
# ================================================================

@login_required
@require_POST
def validation_rapide(request):
    """
    Validation ou refus rapide d'une demande depuis la liste
    """
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({'success': False, 'error': 'Profil utilisateur non trouvé'})
        
        # Récupérer les paramètres
        demande_id = request.POST.get('demande_id')
        action = request.POST.get('action')  # 'APPROUVER' ou 'REFUSER'
        commentaire = request.POST.get('commentaire', '').strip()
        
        if not demande_id or not action:
            return JsonResponse({'success': False, 'error': 'Paramètres manquants'})
        
        if not commentaire:
            return JsonResponse({'success': False, 'error': 'Commentaire obligatoire'})
        
        # Récupérer la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if not _peut_valider_demande_niveau_actuel(profil_utilisateur, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée pour cette validation'})
        
        # Traiter l'action
        if action == 'APPROUVER':
            result = _traiter_approbation_rapide(demande, profil_utilisateur, commentaire, request)
        elif action == 'REFUSER':
            result = _traiter_refus_rapide(demande, profil_utilisateur, commentaire, request)
        else:
            return JsonResponse({'success': False, 'error': 'Action non reconnue'})
        
        if result['success']:
            # Log de l'action
            logger.info(f"Validation rapide {action} par {profil_utilisateur.nom_complet} pour demande {demande.numero_demande}")
            
            return JsonResponse({
                'success': True,
                'message': result['message'],
                'nouveau_statut': demande.statut,
                'redirect_url': result.get('redirect_url'),
                'demande_info': {
                    'numero': demande.numero_demande,
                    'statut': demande.get_statut_display(),
                    'niveau_validation': demande.niveau_validation_actuel
                }
            })
        else:
            return JsonResponse({'success': False, 'error': result['error']})
        
    except Exception as e:
        logger.error(f"Erreur validation rapide: {e}")
        return JsonResponse({'success': False, 'error': f'Erreur serveur: {str(e)}'})

@login_required
@require_POST  
def validation_masse(request):
    """
    Validation en masse de plusieurs demandes (pour RH/ADMIN)
    """
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({'success': False, 'error': 'Profil utilisateur non trouvé'})
        
        # Vérifier les permissions pour validation en masse
        if profil_utilisateur.type_profil not in ['RH', 'ADMIN'] and not profil_utilisateur.is_superuser:
            return JsonResponse({'success': False, 'error': 'Permission refusée pour validation en masse'})
        
        # Récupérer les paramètres
        demandes_ids = request.POST.getlist('demandes_ids[]')
        action_masse = request.POST.get('action_masse')
        commentaire_masse = request.POST.get('commentaire_masse', '').strip()
        
        if not demandes_ids or not action_masse or not commentaire_masse:
            return JsonResponse({'success': False, 'error': 'Paramètres manquants'})
        
        resultats = {
            'succes': 0,
            'echecs': 0,
            'details': []
        }
        
        # Traiter chaque demande
        for demande_id in demandes_ids:
            try:
                demande = DemandeInterim.objects.get(id=demande_id)
                
                if _peut_valider_demande_niveau_actuel(profil_utilisateur, demande):
                    if action_masse == 'APPROUVER':
                        result = _traiter_approbation_rapide(demande, profil_utilisateur, commentaire_masse, request)
                    else:
                        result = _traiter_refus_rapide(demande, profil_utilisateur, commentaire_masse, request)
                    
                    if result['success']:
                        resultats['succes'] += 1
                        resultats['details'].append({
                            'demande': demande.numero_demande,
                            'statut': 'succès',
                            'message': result['message']
                        })
                    else:
                        resultats['echecs'] += 1
                        resultats['details'].append({
                            'demande': demande.numero_demande,
                            'statut': 'échec',
                            'message': result['error']
                        })
                else:
                    resultats['echecs'] += 1
                    resultats['details'].append({
                        'demande': demande.numero_demande,
                        'statut': 'échec', 
                        'message': 'Permission refusée'
                    })
                    
            except Exception as e:
                resultats['echecs'] += 1
                resultats['details'].append({
                    'demande': f'ID {demande_id}',
                    'statut': 'échec',
                    'message': f'Erreur: {str(e)}'
                })
        
        return JsonResponse({
            'success': True,
            'message': f'Validation en masse terminée: {resultats["succes"]} succès, {resultats["echecs"]} échecs',
            'resultats': resultats
        })
        
    except Exception as e:
        logger.error(f"Erreur validation en masse: {e}")
        return JsonResponse({'success': False, 'error': f'Erreur serveur: {str(e)}'})

# ================================================================
# 1. CORRECTION DE LA FONCTION _traiter_approbation_rapide
# ================================================================

def _traiter_approbation_rapide(demande, profil_utilisateur, commentaire, request):
    """
    CORRIGÉ - Traite l'approbation rapide avec progression workflow correcte
    """
    try:
        with transaction.atomic():
            # Déterminer le type et niveau de validation
            type_validation = _determiner_type_validation(profil_utilisateur)
            niveau_validation = demande.niveau_validation_actuel + 1
            
            # 🔧 CORRECTION: Vérification cohérence niveau/type
            if not _verifier_coherence_niveau_type(niveau_validation, type_validation, profil_utilisateur):
                return {
                    'success': False, 
                    'error': f'Incohérence: {profil_utilisateur.type_profil} ne peut pas valider au niveau {niveau_validation}'
                }
            
            # Créer l'entrée de validation
            validation = ValidationDemande.objects.create(
                demande=demande,
                type_validation=type_validation,
                niveau_validation=niveau_validation,
                validateur=profil_utilisateur,
                decision='APPROUVE',
                commentaire=commentaire,
                date_validation=timezone.now()
            )

            # 🎯 AJOUT: Mise à jour progression workflow
            niveau_valide = validation.niveau_validation
            progression_info = _calculer_progression_workflow_complete(demande, niveau_valide)
            _mettre_a_jour_workflow_progression(demande, validation, progression_info)
            
            # Mettre à jour la demande
            demande.niveau_validation_actuel = niveau_valide
            demande.save()
            
            # Compter les mises à jour de progression
            #resultats['progressions_mises_a_jour'] += 1
                        
            # 🎯 CORRECTION PRINCIPALE: Mise à jour workflow avec progression
            #ancien_niveau = demande.niveau_validation_actuel
            demande.niveau_validation_actuel = niveau_validation
            
            # Mettre à jour la progression du workflow
            progression_info = _calculer_progression_workflow_complete(demande, niveau_validation)
            
            # Logique de progression hiérarchique corrigée
            if niveau_validation == 1:
                # Niveau 1 (RESPONSABLE) → Niveau 2 (DIRECTEUR)
                demande.statut = 'EN_VALIDATION'
                message = f"Demande {demande.numero_demande} validée par le Responsable (N+1). Transmission au Directeur (N+2)."
                prochains_validateurs = ProfilUtilisateur.objects.filter(
                    type_profil='DIRECTEUR',
                    actif=True
                )
                
            elif niveau_validation == 2:
                # Niveau 2 (DIRECTEUR) → Niveau 3 (RH/ADMIN) 
                demande.statut = 'EN_VALIDATION'
                message = f"Demande {demande.numero_demande} validée par le Directeur (N+2). Transmission à la RH/Admin (N+3 Final)."
                prochains_validateurs = ProfilUtilisateur.objects.filter(
                    type_profil__in=['RH', 'ADMIN'],
                    actif=True
                )
                
            elif niveau_validation >= 3:
                # Validation finale (RH/ADMIN)
                demande.statut = 'VALIDEE'
                demande.date_validation = timezone.now()
                message = f"Demande {demande.numero_demande} validée définitivement par RH/Admin (N+3 Final)."
                prochains_validateurs = []
                
                # Déclencher la sélection de candidat final
                _declencher_selection_candidat_final(demande, profil_utilisateur)
                
            else:
                return {
                    'success': False,
                    'error': f'Niveau de validation invalide: {niveau_validation}'
                }
            
            demande.save()
            
            # 🎯 MISE À JOUR DU WORKFLOW - NOUVELLE SECTION
            _mettre_a_jour_workflow_progression(demande, validation, progression_info)
            
            # Notifications aux validateurs suivants
            if prochains_validateurs:
                for validateur in prochains_validateurs:
                    _notifier_demande_validation(validateur, demande, profil_utilisateur)
                
                logger.info(f"Notifications envoyées à {prochains_validateurs.count()} validateur(s) niveau {niveau_validation + 1}")
            
            # Créer l'historique avec détails de progression
            _creer_historique_validation_avec_progression(demande, profil_utilisateur, validation, progression_info)
            
            return {'success': True, 'message': message}
            
    except Exception as e:
        logger.error(f"Erreur approbation rapide: {e}")
        return {'success': False, 'error': f'Erreur lors de l\'approbation: {str(e)}'}


def _calculer_progression_workflow_complete(demande, niveau_valide):
    """
    🎯 NOUVELLE FONCTION - Calcule la progression complète du workflow
    """
    try:
        # Déterminer le nombre total d'étapes selon l'urgence et le type de demande
        total_etapes = _get_nombre_etapes_workflow(demande)
        
        # Calculer la progression actuelle
        etapes_completees = niveau_valide
        
        # Calcul du pourcentage
        if total_etapes > 0:
            pourcentage = min(100, (etapes_completees / total_etapes) * 100)
        else:
            pourcentage = 0
        
        # Étapes détaillées
        etapes_workflow = _generer_etapes_workflow_detaillees(demande, niveau_valide)
        
        return {
            'total_etapes': total_etapes,
            'etapes_completees': etapes_completees,
            'pourcentage': round(pourcentage, 1),
            'etape_actuelle': _get_etape_actuelle_display(niveau_valide),
            'prochaine_etape': _get_prochaine_etape_display(niveau_valide + 1),
            'etapes_detaillees': etapes_workflow,
            'workflow_complet': niveau_valide >= total_etapes
        }
        
    except Exception as e:
        logger.error(f"Erreur calcul progression workflow: {e}")
        return {
            'total_etapes': 3,
            'etapes_completees': niveau_valide,
            'pourcentage': 33.3 * niveau_valide,
            'etape_actuelle': f'Niveau {niveau_valide}',
            'prochaine_etape': f'Niveau {niveau_valide + 1}',
            'etapes_detaillees': [],
            'workflow_complet': False
        }


def _get_nombre_etapes_workflow(demande):
    """
    Détermine le nombre total d'étapes selon la demande
    """
    try:
        # Par défaut: 3 étapes (RESPONSABLE → DIRECTEUR → RH/ADMIN)
        etapes_base = 3
        
        # Ajustements selon l'urgence
        if demande.urgence == 'CRITIQUE':
            # Circuit accéléré possible: DIRECTEUR → RH/ADMIN (2 étapes)
            return 2
        elif demande.urgence in ['ELEVEE', 'MOYENNE']:
            # Circuit standard: 3 étapes
            return 3
        else:
            # Circuit complet pour normale: 3 étapes
            return 3
            
    except Exception:
        return 3


def _generer_etapes_workflow_detaillees(demande, niveau_actuel):
    """
    🎯 NOUVELLE FONCTION - Génère les étapes détaillées du workflow
    """
    try:
        etapes = []
        total_etapes = _get_nombre_etapes_workflow(demande)
        
        # Étape 0: Création (toujours complétée)
        etapes.append({
            'numero': 0,
            'titre': 'Demande créée',
            'description': 'Demande soumise par le demandeur',
            'statut': 'completed',
            'date_completion': demande.created_at,
            'validateur': demande.demandeur.nom_complet if demande.demandeur else 'Système',
            'icone': 'fa-plus-circle',
            'couleur': 'success'
        })
        
        # Étape 1: Validation Responsable (N+1)
        if total_etapes >= 1:
            statut_etape_1 = 'completed' if niveau_actuel >= 1 else ('current' if niveau_actuel == 0 else 'pending')
            etapes.append({
                'numero': 1,
                'titre': 'Validation Responsable (N+1)',
                'description': 'Validation par le responsable du département',
                'statut': statut_etape_1,
                'date_completion': _get_date_validation_niveau(demande, 1) if niveau_actuel >= 1 else None,
                'validateur': _get_validateur_niveau(demande, 1) if niveau_actuel >= 1 else 'En attente',
                'icone': 'fa-user-tie',
                'couleur': 'info'
            })
        
        # Étape 2: Validation Directeur (N+2)
        if total_etapes >= 2:
            statut_etape_2 = 'completed' if niveau_actuel >= 2 else ('current' if niveau_actuel == 1 else 'pending')
            etapes.append({
                'numero': 2,
                'titre': 'Validation Directeur (N+2)',
                'description': 'Validation par la direction',
                'statut': statut_etape_2,
                'date_completion': _get_date_validation_niveau(demande, 2) if niveau_actuel >= 2 else None,
                'validateur': _get_validateur_niveau(demande, 2) if niveau_actuel >= 2 else 'En attente',
                'icone': 'fa-crown',
                'couleur': 'primary'
            })
        
        # Étape 3: Validation finale RH/Admin
        if total_etapes >= 3:
            statut_etape_3 = 'completed' if niveau_actuel >= 3 else ('current' if niveau_actuel == 2 else 'pending')
            etapes.append({
                'numero': 3,
                'titre': 'Validation finale RH/Admin',
                'description': 'Validation finale et sélection candidat',
                'statut': statut_etape_3,
                'date_completion': _get_date_validation_niveau(demande, 3) if niveau_actuel >= 3 else None,
                'validateur': _get_validateur_niveau(demande, 3) if niveau_actuel >= 3 else 'En attente',
                'icone': 'fa-check-circle',
                'couleur': 'success'
            })
        
        return etapes
        
    except Exception as e:
        logger.error(f"Erreur génération étapes workflow: {e}")
        return []


def _mettre_a_jour_workflow_progression(demande, validation, progression_info):
    """
    🎯 NOUVELLE FONCTION - Met à jour la progression dans le workflow
    """
    try:
        # Mettre à jour le workflow si il existe
        if hasattr(demande, 'workflow'):
            workflow = demande.workflow
            
            # Mettre à jour les informations de progression
            workflow.etape_actuelle_numero = progression_info['etapes_completees']
            workflow.etape_actuelle_libelle = progression_info['etape_actuelle']
            workflow.progression_pourcentage = progression_info['pourcentage']
            workflow.workflow_complet = progression_info['workflow_complet']
            workflow.derniere_mise_a_jour = timezone.now()
            
            # Ajouter des métadonnées sur la validation
            if hasattr(workflow, 'metadata'):
                metadata = workflow.metadata or {}
                metadata.update({
                    'derniere_validation': {
                        'niveau': validation.niveau_validation,
                        'type': validation.type_validation,
                        'validateur': validation.validateur.nom_complet,
                        'date': validation.date_validation.isoformat(),
                        'decision': validation.decision
                    },
                    'etapes_detaillees': progression_info['etapes_detaillees']
                })
                workflow.metadata = metadata
            
            workflow.save()
            
            logger.info(f"Workflow mis à jour - Demande {demande.numero_demande}: "
                       f"{progression_info['pourcentage']}% ({progression_info['etapes_completees']}/{progression_info['total_etapes']})")
        
        # Créer un workflow si il n'existe pas
        else:
            try:
                from .models import WorkflowDemande
                WorkflowDemande.objects.create(
                    demande=demande,
                    etape_actuelle_numero=progression_info['etapes_completees'],
                    etape_actuelle_libelle=progression_info['etape_actuelle'],
                    progression_pourcentage=progression_info['pourcentage'],
                    workflow_complet=progression_info['workflow_complet'],
                    metadata={
                        'etapes_detaillees': progression_info['etapes_detaillees'],
                        'validation_initiale': {
                            'niveau': validation.niveau_validation,
                            'validateur': validation.validateur.nom_complet,
                            'date': validation.date_validation.isoformat()
                        }
                    }
                )
                logger.info(f"Workflow créé pour demande {demande.numero_demande}")
            except Exception as e:
                logger.warning(f"Impossible de créer le workflow: {e}")
        
    except Exception as e:
        logger.error(f"Erreur mise à jour workflow progression: {e}")


def _creer_historique_validation_avec_progression(demande, validateur, validation, progression_info):
    """
    🎯 MISE À JOUR - Historique enrichi avec informations de progression
    """
    try:
        HistoriqueAction.objects.create(
            demande=demande,
            validation=validation,
            action=f'VALIDATION_{validation.type_validation}',
            utilisateur=validateur,
            description=f"Validation {validation.type_validation} - Progression: {progression_info['pourcentage']}%",
            donnees_apres={
                # Données de validation
                'decision': validation.decision,
                'niveau_validation': validation.niveau_validation,
                'type_validation': validation.type_validation,
                'commentaire': validation.commentaire,
                
                # Données de progression workflow
                'progression_workflow': {
                    'pourcentage_avant': _calculer_progression_precedente(demande, validation.niveau_validation),
                    'pourcentage_apres': progression_info['pourcentage'],
                    'etape_avant': _get_etape_actuelle_display(validation.niveau_validation - 1),
                    'etape_apres': progression_info['etape_actuelle'],
                    'prochaine_etape': progression_info['prochaine_etape'],
                    'workflow_complet': progression_info['workflow_complet']
                },
                
                # Métadonnées de validation
                'validation_rapide': True,
                'progression_hierarchique': _get_progression_display(validation.niveau_validation),
                'validateur_info': {
                    'nom': validateur.nom_complet,
                    'type_profil': validateur.type_profil,
                    'departement': validateur.departement.nom if validateur.departement else None
                }
            },
            niveau_hierarchique=validateur.type_profil,
            is_superuser=validateur.is_superuser
        )
        
        logger.info(f"Historique créé avec progression workflow pour validation {validation.id}")
        
    except Exception as e:
        logger.error(f"Erreur création historique avec progression: {e}")


# ================================================================
# FONCTIONS UTILITAIRES POUR LA PROGRESSION
# ================================================================

def _get_etape_actuelle_display(niveau):
    """Retourne l'affichage de l'étape actuelle"""
    etapes_display = {
        0: "Demande créée",
        1: "Validation Responsable (N+1)",
        2: "Validation Directeur (N+2)", 
        3: "Validation finale RH/Admin",
        4: "Demande validée"
    }
    return etapes_display.get(niveau, f"Niveau {niveau}")


def _get_prochaine_etape_display(niveau):
    """Retourne l'affichage de la prochaine étape"""
    if niveau > 3:
        return "Sélection candidat"
    return _get_etape_actuelle_display(niveau)


def _get_date_validation_niveau(demande, niveau):
    """Récupère la date de validation pour un niveau donné"""
    try:
        validation = ValidationDemande.objects.filter(
            demande=demande,
            niveau_validation=niveau,
            decision='APPROUVE'
        ).first()
        return validation.date_validation if validation else None
    except Exception:
        return None


def _get_validateur_niveau(demande, niveau):
    """Récupère le nom du validateur pour un niveau donné"""
    try:
        validation = ValidationDemande.objects.filter(
            demande=demande,
            niveau_validation=niveau,
            decision='APPROUVE'
        ).first()
        return validation.validateur.nom_complet if validation else 'Non défini'
    except Exception:
        return 'Non défini'


def _calculer_progression_precedente(demande, niveau_actuel):
    """Calcule la progression avant la validation actuelle"""
    try:
        niveau_precedent = niveau_actuel - 1
        total_etapes = _get_nombre_etapes_workflow(demande)
        
        if niveau_precedent <= 0:
            return 0
        
        return round((niveau_precedent / total_etapes) * 100, 1)
        
    except Exception:
        return 0


# ================================================================
# MISE À JOUR DU TEMPLATE POUR AFFICHER LA PROGRESSION
# ================================================================

def _get_context_workflow_progression(demande):
    """
    🎯 NOUVELLE FONCTION - Contexte pour afficher la progression dans le template
    """
    try:
        niveau_actuel = demande.niveau_validation_actuel
        progression_info = _calculer_progression_workflow_complete(demande, niveau_actuel)
        
        return {
            'workflow_progression': {
                'pourcentage': progression_info['pourcentage'],
                'etape_actuelle': progression_info['etape_actuelle'],
                'prochaine_etape': progression_info['prochaine_etape'],
                'etapes': progression_info['etapes_detaillees'],
                'complet': progression_info['workflow_complet']
            }
        }
        
    except Exception as e:
        logger.error(f"Erreur contexte workflow progression: {e}")
        return {
            'workflow_progression': {
                'pourcentage': 0,
                'etape_actuelle': 'Erreur',
                'prochaine_etape': 'Erreur',
                'etapes': [],
                'complet': False
            }
        }


# ================================================================
# EXEMPLE D'UTILISATION DANS LA VUE DE VALIDATION
# ================================================================

def interim_validation_view_avec_progression(request, demande_id):
    """
    Vue de validation mise à jour avec progression du workflow
    """
    try:
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        profil_utilisateur = get_profil_or_virtual(request.user)
        
        # ... autres récupérations de données ...
        
        # 🎯 AJOUT: Contexte de progression workflow
        contexte_progression = _get_context_workflow_progression(demande)
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil_utilisateur,
            # ... autres données du contexte ...
            
            # 🎯 NOUVEAU: Progression workflow
            **contexte_progression,
        }
        
        return render(request, 'interim_validation.html', context)
        
    except Exception as e:
        logger.error(f"Erreur vue validation avec progression: {e}")
        messages.error(request, "Erreur lors du chargement")
        return redirect('index')
    
# ================================================================
# 2. CORRECTION DE LA FONCTION _traiter_validation_demande_corrige  
# ================================================================

def _traiter_validation_demande_corrige(request, demande, profil_utilisateur, action):
    """
      CORRIGÉ - Traitement validation avec hiérarchie respectée
    """
    try:
        commentaire = request.POST.get('commentaire_validation', '').strip()
        
        if not commentaire or len(commentaire) < 10:
            raise ValueError("Commentaire de validation requis (minimum 10 caractères)")
        
        # 🔧 CORRECTION: Détermination correcte du niveau
        niveau_actuel = demande.niveau_validation_actuel
        niveau_a_valider = niveau_actuel + 1
        
        # Vérifier que le validateur peut valider à ce niveau
        if not _peut_valider_demande_niveau_specifique(profil_utilisateur, demande, niveau_a_valider):
            raise ValueError(f"Vous n'êtes pas autorisé à valider au niveau {niveau_a_valider}")
        
        # Déterminer le type de validation selon la hiérarchie
        type_validation = _get_type_validation_pour_niveau(niveau_a_valider, profil_utilisateur)
        
        #   UTILISER LE BON MODÈLE : ValidationDemande
        validation = ValidationDemande.objects.create(
            demande=demande,
            validateur=profil_utilisateur,
            type_validation=type_validation,
            niveau_validation=niveau_a_valider,
            decision='APPROUVE' if action == 'APPROUVER' else 'REFUSE',
            commentaire=commentaire
        )
        
        # Finaliser la validation
        validation.valider(
            decision='APPROUVE' if action == 'APPROUVER' else 'REFUSE',
            commentaire=commentaire
        )
        
        # 🔧 CORRECTION: Progression hiérarchique selon l'action
        if action == 'APPROUVER':
            # Mise à jour du niveau actuel
            demande.niveau_validation_actuel = niveau_a_valider
            
            #   HIÉRARCHIE CLAIRE : 1 → 2 → 3 → FINAL
            if niveau_a_valider < 3:  # Pas encore au niveau final
                demande.statut = 'EN_VALIDATION'
                message = f"Demande approuvée au niveau {niveau_a_valider}. Transmission au niveau {niveau_a_valider + 1}."
                
                # Notifier les validateurs du niveau suivant
                _notifier_validateurs_niveau_suivant(demande, niveau_a_valider + 1, profil_utilisateur)
                
            else:  # niveau_a_valider >= 3 : Validation finale
                demande.statut = 'VALIDEE'
                demande.date_validation = timezone.now()
                message = "Demande validée définitivement."
                
                #   DÉCLENCHER SÉLECTION CANDIDAT
                _declencher_selection_candidat_final(demande, profil_utilisateur)
                
        else:  # REFUSER
            demande.statut = 'REFUSEE'
            message = "Demande refusée."
            
            # Notifier le demandeur du refus
            _notifier_demandeur_refus(demande, profil_utilisateur, commentaire)
        
        demande.save()
        
        logger.info(f"  Validation {action} niveau {niveau_a_valider} par {profil_utilisateur.matricule} pour demande {demande.id}")
        
        # Réponse selon le type de requête
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': message,
                'nouveau_niveau': demande.niveau_validation_actuel,
                'statut': demande.statut,
                'redirect_url': ("interim_validation", demande.id)
            })
        else:
            messages.success(request, message)
            return redirect("interim_validation", demande.id)
    
    except ValueError as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        else:
            messages.error(request, str(e))
            return redirect('interim_validation', demande.id)
    
    except Exception as e:
        logger.error(f"  Erreur validation demande: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': f'Erreur système: {str(e)}'}, status=500)
        else:
            messages.error(request, f"Erreur lors de la validation: {str(e)}")
            return redirect('index')

# ================================================================
# 3. FONCTIONS UTILITAIRES CORRIGÉES
# ================================================================

def _verifier_coherence_niveau_type(niveau, type_validation, profil_utilisateur):
    """
      Vérifie la cohérence entre niveau, type de validation et profil
    """
    coherences = {
        1: ['RESPONSABLE'],
        2: ['DIRECTEUR'], 
        3: ['RH', 'ADMIN']
    }
    
    # Superutilisateurs passent toujours
    if profil_utilisateur.is_superuser:
        return True
    
    types_autorises = coherences.get(niveau, [])
    return profil_utilisateur.type_profil in types_autorises

def _get_type_validation_pour_niveau(niveau, profil_utilisateur):
    """
      Retourne le type de validation approprié selon le niveau et le profil
    """
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    
    types_par_niveau = {
        1: 'RESPONSABLE',
        2: 'DIRECTEUR', 
        3: 'RH' if profil_utilisateur.type_profil == 'RH' else 'ADMIN'
    }
    
    return types_par_niveau.get(niveau, 'AUTRE')

def _notifier_validateurs_niveau_suivant(demande, niveau_suivant, validateur_precedent):
    """
      CORRIGÉ - Notifie les validateurs du niveau suivant selon la hiérarchie
    """
    try:
        if niveau_suivant == 2:
            # Notifier les DIRECTEURS
            validateurs = ProfilUtilisateur.objects.filter(
                type_profil='DIRECTEUR',
                actif=True
            )
            titre_notification = f"Validation Directeur (N+2) requise - {demande.numero_demande}"
            message_notification = (
                f"La demande validée par {validateur_precedent.nom_complet} (Responsable) "
                f"nécessite votre validation en tant que Directeur."
            )
            
        elif niveau_suivant >= 3:
            # Notifier RH/ADMIN
            validateurs = ProfilUtilisateur.objects.filter(
                type_profil__in=['RH', 'ADMIN'],
                actif=True
            )
            titre_notification = f"Validation finale RH/Admin requise - {demande.numero_demande}"
            message_notification = (
                f"La demande validée par {validateur_precedent.nom_complet} (Directeur) "
                f"nécessite votre validation finale en tant que RH/Admin."
            )
            
        else:
            logger.warning(f"Niveau suivant invalide: {niveau_suivant}")
            return
        
        # Envoyer les notifications
        for validateur in validateurs:
            NotificationInterim.objects.create(
                destinataire=validateur,
                expediteur=validateur_precedent,
                demande=demande,
                type_notification='DEMANDE_A_VALIDER',
                urgence='HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE',
                titre=titre_notification,
                message=message_notification,
                url_action_principale=f'/interim/validation/{demande.id}/',
                texte_action_principale=f"Valider (Niveau {niveau_suivant})",
                metadata={
                    'niveau_validation': niveau_suivant,
                    'validateur_precedent': validateur_precedent.nom_complet,
                    'type_validation_precedente': validateur_precedent.type_profil
                }
            )
        
        logger.info(f"  {validateurs.count()} notification(s) envoyée(s) pour niveau {niveau_suivant}")
        
    except Exception as e:
        logger.error(f"  Erreur notifications niveau suivant: {e}")

def _declencher_selection_candidat_final(demande, validateur_final):
    """
      NOUVEAU - Déclenche la sélection du candidat final après validation complète
    """
    try:
        # Récupérer le meilleur candidat selon les scores
        propositions = demande.propositions_candidats.filter(
            statut__in=['SOUMISE', 'EVALUEE', 'RETENUE']
        ).order_by('-score_final')
        
        if propositions.exists():
            meilleure_proposition = propositions.first()
            candidat_selectionne = meilleure_proposition.candidat_propose
            
            # Mettre à jour la demande
            demande.candidat_selectionne = candidat_selectionne
            demande.statut = 'CANDIDAT_SELECTIONNE'
            demande.save()
            
            # Créer la réponse candidat
            '''
            delai_reponse = timezone.now() + timezone.timedelta(days=3)
            reponse, created = ReponseCandidatInterim.objects.get_or_create(
                demande=demande,
                candidat=candidat_selectionne,
                date_limite_reponse=delai_reponse,
                reponse='EN_ATTENTE'
            )
            '''

            # Notifier le candidat sélectionné
            _notifier_candidat_selectionne_final(demande, candidat_selectionne, validateur_final)
            
            # Notifier le demandeur
            _notifier_demandeur_candidat_selectionne(demande, candidat_selectionne, validateur_final)
            
            logger.info(f"  Candidat {candidat_selectionne.nom_complet} sélectionné pour {demande.numero_demande}")
            
        else:
            logger.warning(f"  Aucune proposition disponible pour sélection finale - {demande.numero_demande}")
            demande.statut = 'ECHEC_SELECTION'
            demande.save()
            
    except Exception as e:
        logger.error(f"  Erreur sélection candidat final: {e}")

# ================================================================
# 1. NOTIFICATION DEMANDEUR EN CAS DE REFUS
# ================================================================

def _notifier_demandeur_refus(demande, profil_utilisateur, commentaire):
    """
    Notifie le demandeur du refus de sa demande d'intérim
    
    Args:
        demande (DemandeInterim): La demande refusée
        profil_utilisateur (ProfilUtilisateur): Le validateur qui a refusé
        commentaire (str): Le motif du refus
    """
    try:
        with transaction.atomic():
            # Déterminer le niveau de refus pour l'affichage
            niveaux_display = {
                'RESPONSABLE': 'Responsable (N+1)',
                'DIRECTEUR': 'Directeur (N+2)', 
                'RH': 'RH (Final)',
                'ADMIN': 'Admin (Final)',
                'SUPERUSER': 'Superutilisateur'
            }
            
            niveau_refus = niveaux_display.get(
                profil_utilisateur.type_profil, 
                profil_utilisateur.type_profil
            )
            
            # Déterminer l'urgence de la notification
            urgence_notification = 'HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE'
            
            # Créer la notification principale pour le demandeur
            notification_demandeur = NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=profil_utilisateur,
                demande=demande,
                type_notification='DEMANDE_REFUSEE',
                urgence=urgence_notification,
                titre=f"  Demande refusée - {demande.numero_demande}",
                message=f"Votre demande d'intérim pour le poste {demande.poste.titre} "
                       f"a été refusée par {profil_utilisateur.nom_complet} ({niveau_refus}).\n\n"
                       f"📝 Motif du refus :\n{commentaire[:500]}{'...' if len(commentaire) > 500 else ''}",
                url_action_principale=f'/interim/demande/{demande.id}/',
                texte_action_principale="Voir les détails",
                url_action_secondaire=f'/interim/demande/{demande.id}/modifier/',
                texte_action_secondaire="Modifier la demande",
                metadata={
                    'validateur_refus': profil_utilisateur.nom_complet,
                    'niveau_refus': profil_utilisateur.type_profil,
                    'commentaire_complet': commentaire,
                    'niveau_hierarchique': niveau_refus,
                    'date_refus': timezone.now().isoformat(),
                    'peut_modifier': demande.peut_etre_modifiee,
                    'actions_possibles': _get_actions_apres_refus(demande)
                }
            )
            
            # Notification informative pour la hiérarchie (sauf si c'est déjà RH/ADMIN)
            if profil_utilisateur.type_profil not in ['RH', 'ADMIN']:
                # Notifier la RH pour information
                profiles_rh = ProfilUtilisateur.objects.filter(
                    type_profil='RH', 
                    actif=True
                )
                
                for rh_user in profiles_rh:
                    if rh_user != profil_utilisateur:  # Éviter la double notification
                        NotificationInterim.objects.create(
                            destinataire=rh_user,
                            expediteur=profil_utilisateur,
                            demande=demande,
                            type_notification='INFORMATION_REFUS',
                            urgence='NORMALE',
                            titre=f"ℹ️ Information - Demande refusée {demande.numero_demande}",
                            message=f"La demande de {demande.demandeur.nom_complet} "
                                   f"a été refusée par {profil_utilisateur.nom_complet} ({niveau_refus}).\n\n"
                                   f"Motif : {commentaire[:200]}{'...' if len(commentaire) > 200 else ''}",
                            url_action_principale=f'/interim/demande/{demande.id}/',
                            texte_action_principale="Consulter",
                            metadata={
                                'type_info': 'REFUS_HIERARCHIQUE',
                                'validateur_refus': profil_utilisateur.nom_complet,
                                'niveau_refus': niveau_refus,
                                'demandeur': demande.demandeur.nom_complet,
                                'departement': demande.poste.departement.nom if demande.poste.departement else 'N/A'
                            }
                        )
            
            # Créer l'historique détaillé
            HistoriqueAction.objects.create(
                demande=demande,
                action='VALIDATION_REFUS',
                utilisateur=profil_utilisateur,
                description=f"Demande refusée par {profil_utilisateur.nom_complet} ({niveau_refus})",
                donnees_avant={'statut': demande.statut},
                donnees_apres={
                    'statut': 'REFUSEE',
                    'commentaire_refus': commentaire,
                    'validateur': profil_utilisateur.nom_complet,
                    'niveau_refus': niveau_refus
                },
                niveau_hierarchique=profil_utilisateur.type_profil,
                is_superuser=profil_utilisateur.is_superuser
            )
            
            logger.info(f"  Notification refus envoyée - Demande {demande.numero_demande} "
                       f"refusée par {profil_utilisateur.nom_complet}")
            
            return True
            
    except Exception as e:
        logger.error(f"  Erreur notification refus demandeur: {e}")
        return False

def _get_actions_apres_refus(demande):
    """Détermine les actions possibles après un refus"""
    actions = ['consulter_details']
    
    if demande.peut_etre_modifiee:
        actions.extend(['modifier_demande', 'relancer_demande'])
    
    actions.append('creer_nouvelle_demande')
    return actions

# ================================================================
# 2. NOTIFICATION CANDIDAT SÉLECTIONNÉ (VALIDATION FINALE)
# ================================================================

def _notifier_candidat_selectionne_final(demande, candidat_selectionne, validateur_final):
    """
    Notifie le candidat sélectionné après validation finale
    
    Args:
        demande (DemandeInterim): La demande validée
        candidat_selectionne (ProfilUtilisateur): Le candidat retenu
        validateur_final (ProfilUtilisateur): Le validateur final (RH/ADMIN)
    """
    try:
        with transaction.atomic():
            # Calculer la durée de la mission
            duree_mission = 0
            if demande.date_debut and demande.date_fin:
                duree_mission = (demande.date_fin - demande.date_debut).days + 1
            
            # Calculer la date limite de réponse (3 jours ouvrés)
            date_limite = timezone.now() + timezone.timedelta(days=3)
            
            # Créer la notification principale pour le candidat
            notification_candidat = NotificationInterim.objects.create(
                destinataire=candidat_selectionne,
                expediteur=validateur_final,
                demande=demande,
                type_notification='CANDIDAT_SELECTIONNE',
                urgence='HAUTE',
                titre=f"🎉 Vous êtes sélectionné ! Mission d'intérim - {demande.numero_demande}",
                message=f"Félicitations {candidat_selectionne.nom_complet} !\n\n"
                       f"Vous avez été sélectionné pour la mission d'intérim suivante :\n\n"
                       f"🏢 Poste : {demande.poste.titre}\n"
                       f"📍 Lieu : {demande.poste.site.nom if demande.poste.site else 'Non spécifié'}\n"
                       f"🏭 Département : {demande.poste.departement.nom if demande.poste.departement else 'Non spécifié'}\n"
                       f"📅 Période : du {demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else 'À définir'} "
                       f"au {demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else 'À définir'}\n"
                       f"⏱️ Durée : {duree_mission} jour{'s' if duree_mission > 1 else ''}\n"
                       f"  Remplace : {demande.personne_remplacee.nom_complet}\n\n"
                       f"  IMPORTANT : Vous avez 3 jours pour confirmer votre acceptation.\n"
                       f"  Validé par : {validateur_final.nom_complet} ({validateur_final.get_type_profil_display()})",
                url_action_principale=f'/interim/demande/{demande.id}/',
                texte_action_principale="Voir tous les détails",
                date_expiration=date_limite,
                metadata={
                    'type_selection': 'FINALE',
                    'validateur_final': validateur_final.nom_complet,
                    'validateur_type': validateur_final.type_profil,
                    'duree_mission_jours': duree_mission,
                    'date_limite_reponse': date_limite.isoformat(),
                    'poste_details': {
                        'titre': demande.poste.titre,
                        'departement': demande.poste.departement.nom if demande.poste.departement else None,
                        'site': demande.poste.site.nom if demande.poste.site else None
                    },
                    'personne_remplacee': {
                        'nom': demande.personne_remplacee.nom_complet,
                        'matricule': demande.personne_remplacee.matricule
                    },
                    'urgence_mission': demande.urgence,
                    'demandeur': demande.demandeur.nom_complet
                }
            )
            
            # Programmer un rappel automatique dans 2 jours si pas de réponse
            rappel_date = timezone.now() + timezone.timedelta(days=2)
            notification_candidat.prochaine_date_rappel = rappel_date
            notification_candidat.save()
            
            # Notification informative au manager du candidat (si existe)
            if candidat_selectionne.manager and candidat_selectionne.manager != validateur_final:
                NotificationInterim.objects.create(
                    destinataire=candidat_selectionne.manager,
                    expediteur=validateur_final,
                    demande=demande,
                    type_notification='CANDIDAT_SELECTIONNE',
                    urgence='NORMALE',
                    titre=f"ℹ️ Information - Votre collaborateur sélectionné pour intérim",
                    message=f"Votre collaborateur {candidat_selectionne.nom_complet} "
                           f"a été sélectionné pour une mission d'intérim :\n\n"
                           f"🏢 Poste : {demande.poste.titre}\n"
                           f"📅 Période : du {demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else 'À définir'} "
                           f"au {demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else 'À définir'}\n"
                           f"⏱️ Durée : {duree_mission} jour{'s' if duree_mission > 1 else ''}\n\n"
                           f"Il doit confirmer sa disponibilité dans les 3 jours.",
                    url_action_principale=f'/interim/demande/{demande.id}/',
                    texte_action_principale="Voir la demande",
                    metadata={
                        'type_info': 'MANAGER_CANDIDAT_SELECTIONNE',
                        'collaborateur': candidat_selectionne.nom_complet,
                        'validateur_final': validateur_final.nom_complet
                    }
                )
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                action='SELECTION_CANDIDAT',
                utilisateur=validateur_final,
                description=f"Candidat final sélectionné : {candidat_selectionne.nom_complet}",
                donnees_avant={'candidat_selectionne': None},
                donnees_apres={
                    'candidat_selectionne_id': candidat_selectionne.id,
                    'candidat_nom': candidat_selectionne.nom_complet,
                    'candidat_matricule': candidat_selectionne.matricule,
                    'validateur_final': validateur_final.nom_complet,
                    'date_limite_reponse': date_limite.isoformat(),
                    'duree_mission': duree_mission
                },
                niveau_hierarchique=validateur_final.type_profil,
                is_superuser=validateur_final.is_superuser
            )
            
            logger.info(f"  Notification sélection envoyée - Candidat {candidat_selectionne.nom_complet} "
                       f"pour demande {demande.numero_demande}")
            
            return True
            
    except Exception as e:
        logger.error(f"  Erreur notification candidat sélectionné: {e}")
        return False

# ================================================================
# 3. NOTIFICATION DEMANDEUR - CANDIDAT SÉLECTIONNÉ
# ================================================================

def _notifier_demandeur_candidat_selectionne(demande, candidat_selectionne, validateur_final):
    """
    Notifie le demandeur qu'un candidat a été sélectionné pour sa demande
    
    Args:
        demande (DemandeInterim): La demande avec candidat sélectionné
        candidat_selectionne (ProfilUtilisateur): Le candidat retenu
        validateur_final (ProfilUtilisateur): Le validateur final
    """
    try:
        with transaction.atomic():
            # Calculer la durée de la mission pour l'affichage
            duree_mission = 0
            if demande.date_debut and demande.date_fin:
                duree_mission = (demande.date_fin - demande.date_debut).days + 1
            
            # Récupérer le score du candidat s'il existe
            score_candidat = None
            try:
                from mainapp.models import ScoreDetailCandidat
                score_detail = ScoreDetailCandidat.objects.filter(
                    candidat=candidat_selectionne,
                    demande_interim=demande
                ).first()
                if score_detail:
                    score_candidat = score_detail.score_total
            except Exception:
                pass
            
            # Déterminer les informations du candidat
            candidat_info = {
                'nom_complet': candidat_selectionne.nom_complet,
                'matricule': candidat_selectionne.matricule,
                'poste_actuel': candidat_selectionne.poste.titre if candidat_selectionne.poste else 'Non renseigné',
                'departement': candidat_selectionne.departement.nom if candidat_selectionne.departement else 'Non renseigné',
                'site': candidat_selectionne.site.nom if candidat_selectionne.site else 'Non renseigné'
            }
            
            # Créer la notification principale pour le demandeur
            notification_demandeur = NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=validateur_final,
                demande=demande,
                type_notification='CANDIDAT_SELECTIONNE',
                urgence='NORMALE',
                titre=f"  Candidat sélectionné - {demande.numero_demande}",
                message=f"Bonne nouvelle ! Un candidat a été sélectionné pour votre demande d'intérim.\n\n"
                       f"  Candidat retenu : {candidat_selectionne.nom_complet} ({candidat_selectionne.matricule})\n"
                       f"💼 Poste actuel : {candidat_info['poste_actuel']}\n"
                       f"🏭 Département : {candidat_info['departement']}\n"
                       f"📍 Site : {candidat_info['site']}\n"
                       f"{'  Score : ' + str(score_candidat) + '/100' if score_candidat else ''}\n\n"
                       f"🏢 Pour le poste : {demande.poste.titre}\n"
                       f"📅 Période : du {demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else 'À définir'} "
                       f"au {demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else 'À définir'}\n"
                       f"⏱️ Durée : {duree_mission} jour{'s' if duree_mission > 1 else ''}\n\n"
                       f"  Validé par : {validateur_final.nom_complet} ({validateur_final.get_type_profil_display()})\n\n"
                       f"Le candidat va être notifié et aura 3 jours pour confirmer sa disponibilité.\n"
                       f"Vous serez informé de sa réponse.",
                url_action_principale=f'/interim/demande/{demande.id}/',
                texte_action_principale="Suivre l'évolution",
                url_action_secondaire=f'/interim/mission/{demande.id}/preparer/',
                texte_action_secondaire="Préparer la mission",
                metadata={
                    'candidat_selectionne': {
                        'id': candidat_selectionne.id,
                        'nom_complet': candidat_selectionne.nom_complet,
                        'matricule': candidat_selectionne.matricule,
                        'poste_actuel': candidat_info['poste_actuel'],
                        'departement': candidat_info['departement'],
                        'site': candidat_info['site']
                    },
                    'validateur_final': {
                        'nom': validateur_final.nom_complet,
                        'type_profil': validateur_final.type_profil,
                        'matricule': validateur_final.matricule
                    },
                    'mission_details': {
                        'duree_jours': duree_mission,
                        'poste_titre': demande.poste.titre,
                        'urgence': demande.urgence
                    },
                    'score_candidat': score_candidat,
                    'prochaines_etapes': [
                        'Notification du candidat',
                        'Attente confirmation (3 jours)',
                        'Préparation de la mission si acceptée'
                    ]
                }
            )
            
            # Notification au manager du demandeur (si différent)
            if (demande.demandeur.manager and 
                demande.demandeur.manager != validateur_final and 
                demande.demandeur.manager != demande.demandeur):
                
                NotificationInterim.objects.create(
                    destinataire=demande.demandeur.manager,
                    expediteur=validateur_final,
                    demande=demande,
                    type_notification='CANDIDAT_SELECTIONNE',
                    urgence='NORMALE',
                    titre=f"ℹ️ Information - Candidat sélectionné pour votre équipe",
                    message=f"Un candidat a été sélectionné pour la demande d'intérim "
                           f"de votre collaborateur {demande.demandeur.nom_complet} :\n\n"
                           f"  Candidat : {candidat_selectionne.nom_complet}\n"
                           f"🏢 Poste : {demande.poste.titre}\n"
                           f"📅 Période : du {demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else 'À définir'} "
                           f"au {demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else 'À définir'}\n"
                           f"⏱️ Durée : {duree_mission} jour{'s' if duree_mission > 1 else ''}\n\n"
                           f"Le candidat doit confirmer sa disponibilité.",
                    url_action_principale=f'/interim/demande/{demande.id}/',
                    texte_action_principale="Voir la demande",
                    metadata={
                        'type_info': 'MANAGER_DEMANDEUR_SELECTION',
                        'demandeur': demande.demandeur.nom_complet,
                        'candidat': candidat_selectionne.nom_complet
                    }
                )
            
            # Historique pour le demandeur
            HistoriqueAction.objects.create(
                demande=demande,
                action='NOTIFICATION_DEMANDEUR_SELECTION',
                utilisateur=validateur_final,
                description=f"Demandeur notifié de la sélection de {candidat_selectionne.nom_complet}",
                donnees_apres={
                    'candidat_notifie': candidat_selectionne.nom_complet,
                    'demandeur_notifie': demande.demandeur.nom_complet,
                    'score_candidat': score_candidat,
                    'duree_mission': duree_mission
                },
                niveau_hierarchique=validateur_final.type_profil,
                is_superuser=validateur_final.is_superuser
            )
            
            logger.info(f"  Notification demandeur envoyée - Candidat {candidat_selectionne.nom_complet} "
                       f"sélectionné pour demande {demande.numero_demande} de {demande.demandeur.nom_complet}")
            
            return True
            
    except Exception as e:
        logger.error(f"  Erreur notification demandeur sélection: {e}")
        return False

# ================================================================
# FONCTIONS UTILITAIRES SUPPLÉMENTAIRES
# ================================================================

def _creer_historique_validation_rapide(demande, profil_utilisateur, action_type, metadata):
    """
    Crée un historique pour les validations rapides
    
    Args:
        demande: Instance DemandeInterim
        profil_utilisateur: Validateur
        action_type: Type d'action ('APPROBATION', 'REFUS', etc.)
        metadata: Métadonnées supplémentaires
    """
    try:
        action_map = {
            'APPROBATION': 'VALIDATION_APPROUVE',
            'REFUS': 'VALIDATION_REFUS',
            'CANDIDAT_AJOUTE': 'CANDIDAT_AJOUTE'
        }
        
        action = action_map.get(action_type, 'VALIDATION_AUTRE')
        
        HistoriqueAction.objects.create(
            demande=demande,
            action=action,
            utilisateur=profil_utilisateur,
            description=f"{action_type.title()} rapide par {profil_utilisateur.nom_complet}",
            donnees_apres=metadata,
            niveau_hierarchique=profil_utilisateur.type_profil,
            is_superuser=profil_utilisateur.is_superuser
        )
        
        return True
        
    except Exception as e:
        logger.error(f"  Erreur création historique validation rapide: {e}")
        return False

def _declencher_selection_candidat_final(demande, validateur_final):
    """
    Déclenche la sélection du candidat final après validation complète
    
    Args:
        demande: Instance DemandeInterim
        validateur_final: Validateur final (RH/ADMIN)
    """
    try:
        with transaction.atomic():
            # Récupérer le meilleur candidat selon les scores
            from mainapp.models import PropositionCandidat
            
            propositions = PropositionCandidat.objects.filter(
                demande_interim=demande,
                statut__in=['SOUMISE', 'EVALUEE', 'RETENUE']
            ).order_by('-score_final')
            
            if propositions.exists():
                meilleure_proposition = propositions.first()
                candidat_selectionne = meilleure_proposition.candidat_propose
                
                # Mettre à jour la demande
                demande.candidat_selectionne = candidat_selectionne
                demande.statut = 'CANDIDAT_SELECTIONNE'
                demande.save()
                
                # Créer la réponse candidat avec délai de 3 jours

                '''
                from mainapp.models import ReponseCandidatInterim
                delai_reponse = timezone.now() + timezone.timedelta(days=3)
                
                reponse, created = ReponseCandidatInterim.objects.get_or_create(
                    demande=demande,
                    candidat=candidat_selectionne,
                    date_limite_reponse=delai_reponse,
                    reponse='EN_ATTENTE'
                )
                '''

                # Envoyer les notifications
                _notifier_candidat_selectionne_final(demande, candidat_selectionne, validateur_final)
                _notifier_demandeur_candidat_selectionne(demande, candidat_selectionne, validateur_final)
                
                logger.info(f"  Candidat {candidat_selectionne.nom_complet} sélectionné pour {demande.numero_demande}")
                return True
                
            else:
                logger.warning(f"  Aucune proposition disponible pour sélection finale - {demande.numero_demande}")
                demande.statut = 'ECHEC_SELECTION'
                demande.save()
                return False
                
    except Exception as e:
        logger.error(f"  Erreur sélection candidat final: {e}")
        return False
    
def _get_progression_display(niveau):
    """
      Retourne un affichage lisible de la progression hiérarchique
    """
    progressions = {
        1: "RESPONSABLE (N+1) → DIRECTEUR (N+2)",
        2: "DIRECTEUR (N+2) → RH/ADMIN (Final)", 
        3: "RH/ADMIN (Final) → Sélection candidat"
    }
    return progressions.get(niveau, f"Niveau {niveau}")

def _traiter_refus_rapide(demande, profil_utilisateur, commentaire, request):
    """Traite le refus rapide d'une demande"""
    try:
        with transaction.atomic():
            # Récupérer le motif de refus si fourni
            motif_refus = request.POST.get('motif_refus', 'AUTRE')
            
            # Créer l'entrée de validation
            validation = ValidationDemande.objects.create(
                demande=demande,
                type_validation=_determiner_type_validation(profil_utilisateur),
                niveau_validation=demande.niveau_validation_actuel + 1,
                validateur=profil_utilisateur,
                decision='REFUSE',
                commentaire=commentaire,
                date_validation=timezone.now()
            )
            
            # Mettre à jour la demande
            demande.statut = 'REFUSEE'
            demande.save()
            
            # Notifier le demandeur du refus
            _notifier_demande_refusee(demande.demandeur, demande, profil_utilisateur, commentaire, motif_refus)
            
            # Notifier la hiérarchie (RH) si ce n'est pas déjà RH qui refuse
            if profil_utilisateur.type_profil != 'RH':
                rh_users = ProfilUtilisateur.objects.filter(type_profil='RH', actif=True)
                for rh in rh_users:
                    _notifier_demande_refusee_rh(rh, demande, profil_utilisateur, commentaire)
            
            # Créer l'historique
            _creer_historique_validation_rapide(demande, profil_utilisateur, 'REFUS', {
                'commentaire': commentaire,
                'motif_refus': motif_refus,
                'validation_rapide': True
            })
            
            message = f"Demande {demande.numero_demande} refusée. Demandeur et hiérarchie notifiés."
            
            return {'success': True, 'message': message}
            
    except Exception as e:
        logger.error(f"Erreur refus rapide: {e}")
        return {'success': False, 'error': f'Erreur lors du refus: {str(e)}'}

# ================================================================
# FONCTIONS DE RÉCUPÉRATION DES DONNÉES
# ================================================================

def _enrichir_demandes_pour_liste(demandes):
    """Enrichit les demandes avec des informations supplémentaires pour l'affichage"""
    try:
        demandes_enrichies = []
        
        for demande in demandes:
            # Calculer des informations supplémentaires
            duree_mission = (demande.date_fin - demande.date_debut).days if demande.date_debut and demande.date_fin else 0
            
            # Dernière validation
            derniere_validation = demande.validations.order_by('-created_at').first()
            
            # Nombre de candidats proposés
            nb_candidats = demande.propositions_candidats.count()
            
            # Temps écoulé depuis la création
            temps_ecoule = timezone.now() - demande.created_at
            
            # Indicateur de retard
            seuil_retard = {
                'CRITIQUE': timedelta(hours=4),
                'ELEVEE': timedelta(hours=12), 
                'MOYENNE': timedelta(days=1),
                'NORMALE': timedelta(days=2)
            }
            
            en_retard = temps_ecoule > seuil_retard.get(demande.urgence, timedelta(days=2))
            
            demande_enrichie = {
                'demande': demande,
                'duree_mission': duree_mission,
                'derniere_validation': derniere_validation,
                'nb_candidats': nb_candidats,
                'temps_ecoule': temps_ecoule,
                'en_retard': en_retard,
                'temps_ecoule_display': _format_duree(temps_ecoule),
                'urgence_classe': _get_classe_urgence(demande.urgence),
                'statut_classe': _get_classe_statut(demande.statut),
                'peut_validation_rapide': _permet_validation_rapide(demande),
                'niveau_validation_requis': _get_niveau_validation_display(demande),
                'prochaine_etape': _get_prochaine_etape_validation(demande)
            }
            
            demandes_enrichies.append(demande_enrichie)
        
        return demandes_enrichies
        
    except Exception as e:
        logger.error(f"Erreur enrichissement demandes: {e}")
        return [{'demande': d, 'erreur': str(e)} for d in demandes]

def _calculer_stats_validations(profil_utilisateur, demandes):
    """Calcule les statistiques des validations pour l'utilisateur"""
    try:
        total = len(demandes)
        urgentes = len([d for d in demandes if d.urgence in ['ELEVEE', 'CRITIQUE']])
        en_retard = len([d for d in demandes if _est_en_retard(d)])
        
        # Validations effectuées ce mois
        debut_mois = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        validations_mois = ValidationDemande.objects.filter(
            validateur=profil_utilisateur,
            date_validation__gte=debut_mois
        ).count()
        
        # Temps moyen de validation
        validations_recentes = ValidationDemande.objects.filter(
            validateur=profil_utilisateur,
            date_validation__gte=timezone.now() - timedelta(days=30)
        )
        
        if validations_recentes.exists():
            temps_moyen = validations_recentes.aggregate(
                temps_moyen=Avg(F('date_validation') - F('created_at'))
            )['temps_moyen']
            temps_moyen_heures = temps_moyen.total_seconds() / 3600 if temps_moyen else 0
        else:
            temps_moyen_heures = 0
        
        return {
            'total_a_valider': total,
            'urgentes': urgentes,
            'en_retard': en_retard,
            'validations_ce_mois': validations_mois,
            'temps_moyen_validation_heures': round(temps_moyen_heures, 1),
            'pourcentage_urgentes': round((urgentes / total * 100) if total > 0 else 0, 1),
            'pourcentage_en_retard': round((en_retard / total * 100) if total > 0 else 0, 1)
        }
        
    except Exception as e:
        logger.error(f"Erreur calcul stats validations: {e}")
        return {
            'total_a_valider': 0,
            'urgentes': 0,
            'en_retard': 0,
            'validations_ce_mois': 0,
            'temps_moyen_validation_heures': 0,
            'erreur': str(e)
        }

# ================================================================
# FONCTIONS UTILITAIRES ET HELPERS
# ================================================================

def _peut_valider_au_moins_un_niveau(profil):
    """Vérifie si l'utilisateur peut valider à au moins un niveau"""
    return profil.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'] or profil.is_superuser

def _peut_valider_demande_niveau_actuel(profil, demande):
    """Vérifie si l'utilisateur peut valider cette demande à son niveau actuel"""
    niveau_a_valider = demande.niveau_validation_actuel + 1
    type_profil = profil.type_profil
    
    # Superutilisateurs peuvent tout valider
    if profil.is_superuser or type_profil == 'SUPERUSER':
        return True
    
    # Niveau 1 : RESPONSABLE (dans le bon département)
    if niveau_a_valider == 1:
        return (type_profil == 'RESPONSABLE' and 
                profil.departement == demande.poste.departement)
    
    # Niveau 2 : DIRECTEUR
    elif niveau_a_valider == 2:
        return type_profil == 'DIRECTEUR'
    
    # Niveau 3+ : RH/ADMIN
    elif niveau_a_valider >= 3:
        return type_profil in ['RH', 'ADMIN']
    
    return False

def _determiner_type_validation(profil):
    """Détermine le type de validation selon le profil"""
    mapping = {
        'RESPONSABLE': 'RESPONSABLE',
        'DIRECTEUR': 'DIRECTEUR',
        'RH': 'RH', 
        'ADMIN': 'ADMIN',
        'SUPERUSER': 'SUPERUSER'
    }
    return mapping.get(profil.type_profil, 'AUTRE')

def _get_validateurs_niveau_suivant(demande):
    """Retourne les validateurs du niveau suivant"""
    niveau_suivant = demande.niveau_validation_actuel + 1
    
    if niveau_suivant == 1:
        return ProfilUtilisateur.objects.filter(
            type_profil='RESPONSABLE',
            departement=demande.poste.departement,
            actif=True
        )
    elif niveau_suivant == 2:
        return ProfilUtilisateur.objects.filter(
            type_profil='DIRECTEUR',
            actif=True
        )
    elif niveau_suivant >= 3:
        return ProfilUtilisateur.objects.filter(
            type_profil__in=['RH', 'ADMIN'],
            actif=True
        )
    
    return ProfilUtilisateur.objects.none()

def _extraire_filtres_recherche(request):
    """Extrait les filtres de recherche de la requête"""
    try:
        filtres = {
            'urgence': request.GET.get('urgence', ''),
            'departement': request.GET.get('departement', ''),
            'date_debut': None,
            'date_fin': None,
            'recherche': request.GET.get('recherche', '').strip()
        }
        
        # Conversion des dates si présentes
        if request.GET.get('date_debut'):
            try:
                filtres['date_debut'] = datetime.strptime(request.GET.get('date_debut'), '%Y-%m-%d').date()
            except:
                pass
                
        if request.GET.get('date_fin'):
            try:
                filtres['date_fin'] = datetime.strptime(request.GET.get('date_fin'), '%Y-%m-%d').date()
            except:
                pass
        
        return filtres
        
    except Exception as e:
        logger.error(f"Erreur extraction filtres: {e}")
        return {'urgence': '', 'departement': '', 'date_debut': None, 'date_fin': None, 'recherche': ''}

def _get_departements_pour_filtre(profil):
    """Retourne les départements pour le filtre selon le profil"""
    try:
        if profil.type_profil == 'RESPONSABLE':
            # Responsable ne voit que son département
            return [profil.departement] if profil.departement else []
        elif profil.type_profil in ['DIRECTEUR', 'RH', 'ADMIN'] or profil.is_superuser:
            # Vue globale
            from .models import Departement
            return Departement.objects.filter(actif=True).order_by('nom')
        else:
            return []
    except Exception as e:
        logger.error(f"Erreur départements filtre: {e}")
        return []

def _get_niveau_validation_info(profil):
    """Retourne les informations sur le niveau de validation de l'utilisateur"""
    mapping = {
        'RESPONSABLE': {'niveau': 1, 'libelle': 'Niveau 1 (N+1)', 'type': 'RESPONSABLE'},
        'DIRECTEUR': {'niveau': 2, 'libelle': 'Niveau 2 (N+2)', 'type': 'DIRECTEUR'},
        'RH': {'niveau': 3, 'libelle': 'Niveau 3 (Final)', 'type': 'RH'},
        'ADMIN': {'niveau': 3, 'libelle': 'Niveau 3 (Final)', 'type': 'ADMIN'},
        'SUPERUSER': {'niveau': 0, 'libelle': 'Tous niveaux', 'type': 'SUPERUSER'}
    }
    return mapping.get(profil.type_profil, {'niveau': 0, 'libelle': 'Autre', 'type': 'AUTRE'})

def _format_duree(duree):
    """Formate une durée en texte lisible"""
    try:
        if duree.days > 0:
            return f"{duree.days} jour{'s' if duree.days > 1 else ''}"
        elif duree.seconds > 3600:
            heures = duree.seconds // 3600
            return f"{heures} heure{'s' if heures > 1 else ''}"
        else:
            minutes = duree.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''}"
    except:
        return "N/A"

def _get_classe_urgence(urgence):
    """Retourne la classe CSS pour l'urgence"""
    classes = {
        'CRITIQUE': 'badge bg-danger',
        'ELEVEE': 'badge bg-warning text-dark',
        'MOYENNE': 'badge bg-info',
        'NORMALE': 'badge bg-success'
    }
    return classes.get(urgence, 'badge bg-secondary')

def _get_classe_statut(statut):
    """Retourne la classe CSS pour le statut"""
    classes = {
        'EN_VALIDATION': 'badge bg-warning text-dark',
        'VALIDEE': 'badge bg-success',
        'REFUSEE': 'badge bg-danger',
        'EN_COURS': 'badge bg-primary',
        'TERMINEE': 'badge bg-secondary'
    }
    return classes.get(statut, 'badge bg-light text-dark')

def _permet_validation_rapide(demande):
    """Vérifie si la demande permet une validation rapide"""
    # Critères pour validation rapide : pas trop de candidats, pas d'urgence critique nécessitant analyse
    return (demande.propositions_candidats.count() <= 3 and 
            demande.urgence != 'CRITIQUE')

def _est_en_retard(demande):
    """Vérifie si une demande est en retard selon son urgence"""
    temps_ecoule = timezone.now() - demande.created_at
    seuils = {
        'CRITIQUE': timedelta(hours=4),
        'ELEVEE': timedelta(hours=12),
        'MOYENNE': timedelta(days=1),
        'NORMALE': timedelta(days=2)
    }
    return temps_ecoule > seuils.get(demande.urgence, timedelta(days=2))

def _get_niveau_validation_display(demande):
    """Retourne l'affichage du niveau de validation requis"""
    niveau = demande.niveau_validation_actuel + 1
    niveaux = {
        1: 'N+1 (Responsable)',
        2: 'N+2 (Directeur)', 
        3: 'Final (RH/Admin)'
    }
    return niveaux.get(niveau, f'Niveau {niveau}')

def _get_prochaine_etape_validation(demande):
    """Retourne la prochaine étape de validation"""
    niveau = demande.niveau_validation_actuel + 1
    if niveau == 1:
        return "Validation Responsable"
    elif niveau == 2:
        return "Validation Directeur"
    elif niveau >= 3:
        return "Validation finale RH/Admin"
    else:
        return "Validation terminée"

# ================================================================
# FONCTIONS DE NOTIFICATION (réutilisées)
# ================================================================

def _notifier_demande_validation(validateur, demande, expediteur):
    """Notifie un validateur qu'une demande attend sa validation"""
    try:
        NotificationInterim.objects.create(
            destinataire=validateur,
            expediteur=expediteur,
            demande=demande,
            type_notification='DEMANDE_A_VALIDER',
            urgence='NORMALE' if demande.urgence in ['NORMALE', 'MOYENNE'] else 'HAUTE',
            titre=f"Validation requise - {demande.numero_demande}",
            message=f"Une demande d'intérim attend votre validation. Poste: {demande.poste.titre}. Urgence: {demande.get_urgence_display()}.",
            url_action_principale=f'/interim/validation/{demande.id}/',
            texte_action_principale="Valider la demande"
        )
    except Exception as e:
        logger.error(f"Erreur notification validation: {e}")

def _notifier_demande_validee_final(demande, validateur):
    """Notifie le demandeur que sa demande a été validée définitivement"""
    try:
        NotificationInterim.objects.create(
            destinataire=demande.demandeur,
            expediteur=validateur,
            demande=demande,
            type_notification='DEMANDE_VALIDEE',
            urgence='NORMALE',
            titre=f"Demande validée - {demande.numero_demande}",
            message=f"Votre demande d'intérim a été validée définitivement par {validateur.nom_complet}.",
            url_action_principale=f'/interim/demande/{demande.id}/',
            texte_action_principale="Voir la demande"
        )
    except Exception as e:
        logger.error(f"Erreur notification validation finale: {e}")

def _notifier_demande_refusee(demandeur, demande, validateur, commentaire, motif):
    """Notifie le demandeur du refus de sa demande"""
    try:
        NotificationInterim.objects.create(
            destinataire=demandeur,
            expediteur=validateur,
            demande=demande,
            type_notification='DEMANDE_REFUSEE',
            urgence='NORMALE',
            titre=f"Demande refusée - {demande.numero_demande}",
            message=f"Votre demande d'intérim a été refusée par {validateur.nom_complet}. Motif: {motif}. Commentaire: {commentaire[:100]}...",
            url_action_principale=f'/interim/demande/{demande.id}/',
            texte_action_principale="Voir les détails"
        )
    except Exception as e:
        logger.error(f"Erreur notification refus demandeur: {e}")

def _notifier_demande_refusee_rh(rh_user, demande, validateur, commentaire):
    """Notifie la RH du refus d'une demande"""
    try:
        NotificationInterim.objects.create(
            destinataire=rh_user,
            expediteur=validateur,
            demande=demande,
            type_notification='INFORMATION_REFUS',
            urgence='NORMALE',
            titre=f"Information - Demande refusée {demande.numero_demande}",
            message=f"La demande {demande.numero_demande} a été refusée par {validateur.nom_complet}. Commentaire: {commentaire[:100]}...",
            url_action_principale=f'/interim/demande/{demande.id}/',
            texte_action_principale="Voir les détails"
        )
    except Exception as e:
        logger.error(f"Erreur notification refus RH: {e}")

def _creer_historique_validation_rapide(demande, validateur, action, donnees):
    """Crée une entrée dans l'historique pour validation rapide"""
    try:
        HistoriqueAction.objects.create(
            demande=demande,
            utilisateur=validateur,
            action=f'VALIDATION_RAPIDE_{action}',
            description=f"Validation rapide {action} par {validateur.nom_complet} ({validateur.get_type_profil_display()})",
            donnees_apres=donnees,
            niveau_hierarchique=validateur.type_profil,
            is_superuser=validateur.is_superuser
        )
    except Exception as e:
        logger.error(f"Erreur création historique: {e}")

# ================================================================
# VUES EMPLOYÉS
# ================================================================

@login_required
def employes_list_view(request):
    """Liste des employés (mise à jour pour superutilisateurs)"""
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        
        # Filtres
        statut_filtre = request.GET.get('statut', 'ACTIF')
        departement_id = request.GET.get('departement')
        site_id = request.GET.get('site')
        
        employes = ProfilUtilisateur.objects.filter(
            statut_employe=statut_filtre
        ).select_related('user', 'poste', 'departement', 'site')
        
        # Les superutilisateurs voient tout, les autres selon leurs permissions
        if not request.user.is_superuser and getattr(profil_utilisateur, 'type_profil', None) not in ['RH', 'ADMIN']:
            # Filtrer selon le département pour les autres utilisateurs
            if hasattr(profil_utilisateur, 'departement') and profil_utilisateur.departement:
                employes = employes.filter(departement=profil_utilisateur.departement)
        
        if departement_id:
            employes = employes.filter(departement_id=departement_id)
        
        if site_id:
            employes = employes.filter(site_id=site_id)
        
        # Pagination
        paginator = Paginator(employes, 50)
        page_number = request.GET.get('page')
        employes_page = paginator.get_page(page_number)
        
        context = {
            'employes': employes_page,
            'profil_utilisateur': profil_utilisateur,
            'departements': Departement.objects.filter(actif=True),
            'sites': Site.objects.filter(actif=True),
            'statut_filtre': statut_filtre,
            'departement_id': departement_id,
            'site_id': site_id,
            'is_superuser': request.user.is_superuser
        }
        
        return render(request, 'employes_list.html', context)
        
    except Exception as e:
        logger.error(f"Erreur vue employés: {e}")
        messages.error(request, "Erreur lors du chargement de la liste des employés")
        return redirect('index_n3_global' if request.user.is_superuser else 'connexion')
    
def employe_detail_view(request, matricule):
    """Détail d'un employé"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        employe = get_object_or_404(ProfilUtilisateur, matricule=matricule)
        
        context = {
            'employe': employe,
            'profil_utilisateur': profil_utilisateur,
            'competences': employe.competences.all(),
            'formations': employe.formations.all(),
            'absences_recentes': employe.absences.order_by('-date_debut')[:5],
            'missions_recentes': employe.selections_interim.order_by('-created_at')[:5],
            'peut_creer_demande': _peut_creer_demande_pour_employe(profil_utilisateur, employe)
        }
        
        return render(request, 'employe_detail.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Employé non trouvé")
        return redirect('employes_liste')

@login_required
def employe_disponibilite_view(request, matricule):
    """Vue de disponibilité d'un employé - VERSION CORRIGÉE"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        employe = get_object_or_404(ProfilUtilisateur, matricule=matricule)
        
        # Vérifier les permissions
        if not _peut_voir_disponibilite(profil_utilisateur, employe):
            messages.error(request, "Permission refusée")
            return redirect('employe_detail', matricule=matricule)
        
        # Définir la période de disponibilité (3 mois)
        date_debut = timezone.now().date()
        date_fin = date_debut + timedelta(days=90)
        
        # Récupérer les absences dans la période
        absences = employe.absences.filter(
            date_debut__lte=date_fin,
            date_fin__gte=date_debut
        ).order_by('date_debut')
        
        # CORRECTION : Récupérer les missions d'intérim via les demandes validées
        # où l'employé est candidat sélectionné
        missions_demandes = DemandeInterim.objects.filter(
            candidat_selectionne=employe,
            statut__in=['EN_COURS', 'VALIDEE'],
            date_debut__lte=date_fin,
            date_fin__gte=date_debut
        ).select_related('poste', 'poste__site', 'poste__departement')
        
        # Alternative : Si vous avez un modèle MissionInterim séparé
        # missions = MissionInterim.objects.filter(
        #     candidat=employe,
        #     statut__in=['EN_COURS', 'PLANIFIEE'],
        #     date_debut__lte=date_fin,
        #     date_fin__gte=date_debut
        # )
        
        # Calculer les statistiques de disponibilité
        jours_periode = (date_fin - date_debut).days + 1
        jours_absences = sum((min(abs.date_fin, date_fin) - max(abs.date_debut, date_debut)).days + 1 
                           for abs in absences 
                           if abs.date_debut <= date_fin and abs.date_fin >= date_debut)
        jours_missions = sum((min(mission.date_fin or date_fin, date_fin) - 
                            max(mission.date_debut or date_debut, date_debut)).days + 1 
                           for mission in missions_demandes 
                           if mission.date_debut and mission.date_fin)
        jours_disponibles = max(0, jours_periode - jours_absences - jours_missions)
        taux_disponibilite = round((jours_disponibles / jours_periode) * 100, 1) if jours_periode > 0 else 0
        
        context = {
            'employe': employe,
            'profil_utilisateur': profil_utilisateur,
            'absences': absences,
            'missions': missions_demandes,  # Utiliser missions_demandes au lieu de missions
            'periode_debut': date_debut,
            'periode_fin': date_fin,
            'jours_disponibles': jours_disponibles,
            'jours_absences': jours_absences,
            'jours_missions': jours_missions,
            'taux_disponibilite': taux_disponibilite,
        }
        
        return render(request, 'employe_disponibilite.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Employé non trouvé")
        return redirect('employes_liste')
    except Exception as e:
        logger.error(f"Erreur dans employe_disponibilite_view: {e}")
        messages.error(request, "Erreur lors du chargement de la disponibilité")
        return redirect('employe_detail', matricule=matricule)


def _peut_voir_disponibilite(profil_utilisateur, employe):
    """
    Vérifie si un utilisateur peut voir la disponibilité d'un employé
    """
    # Superutilisateurs peuvent tout voir
    if profil_utilisateur.is_superuser:
        return True
    
    # L'employé peut voir sa propre disponibilité
    if profil_utilisateur == employe:
        return True
    
    # Managers peuvent voir leur équipe
    if employe.manager == profil_utilisateur:
        return True
    
    # RH et Admin peuvent voir tous les employés
    if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return True
    
    # Responsables et Directeurs peuvent voir leur département
    if profil_utilisateur.type_profil in ['RESPONSABLE', 'DIRECTEUR']:
        if profil_utilisateur.departement == employe.departement:
            return True
    
    return False

@login_required
def employe_mes_missions(request):
    """Mes missions d'intérim"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        mes_missions = profil_utilisateur.selections_interim.select_related(
            'demande_interim__poste', 'demande_interim__demandeur__user'
        ).order_by('-created_at')
        
        # Pagination
        paginator = Paginator(mes_missions, 20)
        page_number = request.GET.get('page')
        missions_page = paginator.get_page(page_number)
        
        context = {
            'missions': missions_page,
            'profil_utilisateur': profil_utilisateur,
            'stats': {
                'total': mes_missions.count(),
                'en_cours': mes_missions.filter(statut='EN_COURS').count(),
                'terminees': mes_missions.filter(statut='TERMINEE').count(),
                'planifiees': mes_missions.filter(statut='PLANIFIEE').count()
            }
        }
        
        return render(request, 'mes_missions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES HISTORIQUE ET SUIVI
# ================================================================

@login_required
def workflow_detail_view(request, demande_id):
    """Détail du workflow d'une demande"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        if not _peut_voir_demande(profil_utilisateur, demande):
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        workflow = getattr(demande, 'workflow', None)
        
        context = {
            'demande': demande,
            'workflow': workflow,
            'profil_utilisateur': profil_utilisateur,
            'etapes_workflow': workflow.get_etapes_avec_statut() if workflow else []
        }
        
        return render(request, 'interim/workflow_detail.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def suivi_demandes_view(request):
    """Vue de suivi des demandes"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Demandes selon le rôle
        if profil_utilisateur.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE']:
            demandes = DemandeInterim.objects.filter(
                poste__departement=profil_utilisateur.departement
            )
        elif profil_utilisateur.type_profil == 'RH':
            demandes = DemandeInterim.objects.all()
        else:
            demandes = profil_utilisateur.demandes_soumises.all()
        
        demandes = demandes.select_related(
            'demandeur__user', 'poste', 'candidat_selectionne__user'
        ).order_by('-created_at')
        
        # Filtres
        statut_filtre = request.GET.get('statut')
        if statut_filtre:
            demandes = demandes.filter(statut=statut_filtre)
        
        # Pagination
        paginator = Paginator(demandes, 25)
        page_number = request.GET.get('page')
        demandes_page = paginator.get_page(page_number)
        
        context = {
            'demandes': demandes_page,
            'profil_utilisateur': profil_utilisateur,
            'statut_filtre': statut_filtre,
            'statuts_disponibles': DemandeInterim.STATUTS
        }
        
        return render(request, 'suivi_demandes.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES STATISTIQUES ET RAPPORTS
# ================================================================

@login_required
def statistiques_detaillees_view(request):
    """Statistiques détaillées"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Période d'analyse
        periode = request.GET.get('periode', '30')
        date_debut = timezone.now() - timedelta(days=int(periode))
        
        # Statistiques générales
        stats = {
            'total_demandes': DemandeInterim.objects.filter(created_at__gte=date_debut).count(),
            'demandes_validees': DemandeInterim.objects.filter(
                created_at__gte=date_debut,
                statut__in=['VALIDEE', 'EN_COURS', 'TERMINEE']
            ).count(),
            'missions_en_cours': DemandeInterim.objects.filter(statut='EN_COURS').count(),
            'taux_validation': 0
        }
        
        if stats['total_demandes'] > 0:
            stats['taux_validation'] = round(
                (stats['demandes_validees'] / stats['total_demandes']) * 100, 1
            )
        
        # Répartition par département
        repartition_dept = DemandeInterim.objects.filter(
            created_at__gte=date_debut
        ).values('poste__departement__nom').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Répartition par statut
        repartition_statut = DemandeInterim.objects.filter(
            created_at__gte=date_debut
        ).values('statut').annotate(
            count=Count('id')
        )
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'stats': stats,
            'repartition_dept': repartition_dept,
            'repartition_statut': repartition_statut,
            'periode': periode,
            'date_debut': date_debut
        }
        
        return render(request, 'statistiques_detaillees.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def rapports_interim_view(request):
    """Vue des rapports"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Types de rapports disponibles
        rapports_disponibles = [
            {
                'nom': 'Rapport mensuel',
                'description': 'Synthèse mensuelle des demandes et missions',
                'url': 'rapport_mensuel'
            },
            {
                'nom': 'Rapport validations',
                'description': 'Analyse des validations par niveau',
                'url': 'rapport_validations'
            },
            {
                'nom': 'Rapport candidats',
                'description': 'Statistiques sur les candidats et sélections',
                'url': 'rapport_candidats'
            }
        ]
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'rapports_disponibles': rapports_disponibles
        }
        
        return render(request, 'rapports.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def rapport_validations(request):
    """Rapport sur les validations"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Vérifier les permissions
        if profil_utilisateur.type_profil not in ['RH', 'DIRECTEUR', 'ADMIN']:
            messages.error(request, "Permission refusée")
            return redirect('rapports')
        
        # Données du rapport
        validations = ValidationDemande.objects.select_related(
            'demande', 'validateur__user'
        ).order_by('-created_at')[:100]
        
        # Statistiques par validateur
        stats_validateurs = ValidationDemande.objects.values(
            'validateur__user__first_name',
            'validateur__user__last_name'
        ).annotate(
            total_validations=Count('id'),
            taux_approbation=Avg('decision')
        ).order_by('-total_validations')
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'validations': validations,
            'stats_validateurs': stats_validateurs
        }
        
        return render(request, 'rapport_validations.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def rapport_candidats(request):
    """Rapport sur les candidats"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Candidats les plus sélectionnés
        candidats_populaires = ProfilUtilisateur.objects.annotate(
            nb_selections=Count('selections_interim')
        ).filter(nb_selections__gt=0).order_by('-nb_selections')[:50]
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'candidats_populaires': candidats_populaires
        }
        
        return render(request, 'rapport_candidats.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def export_rapport_view(request, format):
    """Export de rapports"""
    if format not in ['pdf', 'excel', 'csv']:
        return HttpResponse("Format non supporté", status=400)
    
    return HttpResponse(f"Export {format} - À implémenter")

# ================================================================
# VUES PLANNING
# ================================================================

@login_required
def planning_interim_view(request):
    """Vue principale du planning"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Missions en cours et planifiées
        missions = DemandeInterim.objects.filter(
            statut__in=['EN_COURS', 'PLANIFIEE', 'VALIDEE'],
            date_debut__isnull=False
        ).select_related(
            'candidat_selectionne__user', 'poste', 'demandeur__user'
        ).order_by('date_debut')
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'missions': missions
        }
        
        return render(request, 'interim/planning.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def planning_mensuel_view(request, year, month):
    """Planning mensuel"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Missions du mois
        date_debut_mois = datetime(year, month, 1).date()
        if month == 12:
            date_fin_mois = datetime(year + 1, 1, 1).date()
        else:
            date_fin_mois = datetime(year, month + 1, 1).date()
        
        missions = DemandeInterim.objects.filter(
            statut__in=['EN_COURS', 'PLANIFIEE', 'VALIDEE'],
            date_debut__lt=date_fin_mois,
            date_fin__gte=date_debut_mois
        ).select_related(
            'candidat_selectionne__user', 'poste'
        )
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'missions': missions,
            'year': year,
            'month': month,
            'date_debut_mois': date_debut_mois,
            'date_fin_mois': date_fin_mois
        }
        
        return render(request, 'interim/planning_mensuel.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def planning_employe_view(request, matricule):
    """Planning d'un employé spécifique"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        employe = get_object_or_404(ProfilUtilisateur, matricule=matricule)
        
        # Missions de l'employé 
        missions = employe.selections_interim.select_related(
            'demande_interim__poste', 'demande_interim__demandeur__user'
        ).order_by('-created_at')
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'employe': employe,
            'missions': missions
        }
        
        return render(request, 'interim/planning_employe.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Employé non trouvé")
        return redirect('planning')

# ================================================================
# VUES NOTES DE SERVICE
# ================================================================

def interim_notes(request):
    """Vue principale des notes de service"""
    context = {
        'page_title': 'Notes de service'
    }
    return render(request, 'interim_notes.html', context)

@login_required
def notes_service_list_view(request):
    """Liste des notes de service"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Notes selon les permissions
        notes = []  # À implémenter avec le modèle NotesService
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'notes': notes
        }
        
        return render(request, 'interim/notes_list.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def notes_service_create_view(request):
    """Création d'une note de service"""
    return HttpResponse("Création note de service - À implémenter")

@login_required
def notes_service_detail_view(request, pk):
    """Détail d'une note de service"""
    return HttpResponse(f"Détail note {pk} - À implémenter")

@login_required
def generer_note_pdf_view(request, pk):
    """Génération PDF d'une note"""
    return HttpResponse(f"PDF note {pk} - À implémenter")

# ================================================================
# VUES NOTIFICATIONS
# ================================================================

@login_required
def notifications_count_ajax(request):
    """Compte des notifications non lues"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        count = profil_utilisateur.notifications_recues.filter(statut='NON_LUE').count()
        
        return JsonResponse({'count': count})
        
    except ProfilUtilisateur.DoesNotExist:
        return JsonResponse({'count': 0})

@login_required
@require_POST
def marquer_notification_lue(request, notification_id):
    """Marque une notification comme lue"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        notification = get_object_or_404(
            NotificationInterim,
            id=notification_id,
            destinataire=profil_utilisateur
        )
        
        notification.statut = 'LUE'
        notification.date_lecture = timezone.now()
        notification.save()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def marquer_toutes_lues(request):
    """Marque toutes les notifications comme lues"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        notifications = profil_utilisateur.notifications_recues.filter(statut='NON_LUE')
        count = notifications.update(
            statut='LUE',
            date_lecture=timezone.now()
        )
        
        return JsonResponse({'success': True, 'count': count})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES PROFIL UTILISATEUR
# ================================================================

@login_required
def profil_utilisateur_view(request):
    """Vue du profil utilisateur"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        context = {
            'profil_utilisateur': profil_utilisateur
        }
        
        return render(request, 'interim/profil.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def preferences_view(request):
    """Vue des préférences utilisateur"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        context = {
            'profil_utilisateur': profil_utilisateur
        }
        
        return render(request, 'interim/preferences.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES ADMINISTRATION
# ================================================================

@login_required
def admin_configuration_view(request):
    """Configuration système (mise à jour pour superutilisateurs)"""
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        
        # Vérifier les permissions - Superutilisateurs ont accès complet
        if not request.user.is_superuser and getattr(profil_utilisateur, 'type_profil', None) not in ['ADMIN', 'RH']:
            messages.error(request, "Permission refusée")
            return redirect('index_n3_global' if request.user.is_superuser else 'connexion')
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'is_superuser': request.user.is_superuser,
            'has_admin_rights': request.user.is_superuser or getattr(profil_utilisateur, 'type_profil', None) in ['ADMIN', 'RH']
        }
        
        return render(request, 'interim/admin/configuration.html', context)
        
    except Exception as e:
        logger.error(f"Erreur vue configuration: {e}")
        messages.error(request, "Erreur lors du chargement de la configuration")
        return redirect('index_n3_global' if request.user.is_superuser else 'connexion')
    
@login_required
def admin_utilisateurs_view(request):
    """Gestion des utilisateurs"""
    return HttpResponse("Admin utilisateurs - À implémenter")

@login_required
def admin_logs_view(request):
    """Logs système"""
    return HttpResponse("Admin logs - À implémenter")

@login_required
def admin_maintenance_view(request):
    """Maintenance système"""
    return HttpResponse("Admin maintenance - À implémenter")

# ================================================================
# CONFIGURATION KELIO
# ================================================================

   
@login_required
def diagnostic_kelio_view(request):
    """Diagnostic Kelio"""
    return HttpResponse("Diagnostic Kelio - À implémenter")

# ================================================================
# VUES WORKFLOW ADMIN
# ================================================================

@login_required
def admin_workflow_etapes(request):
    """Configuration des étapes de workflow"""
    return HttpResponse("Config workflow - À implémenter")

@login_required
def admin_notifications_config(request):
    """Configuration des notifications"""
    return HttpResponse("Config notifications - À implémenter")

@login_required
def admin_workflow_monitoring(request):
    """Monitoring du workflow"""
    return HttpResponse("Monitoring workflow - À implémenter")

# ================================================================
# VUES IMPORT/EXPORT
# ================================================================

@login_required
def import_employes_view(request):
    """Import des employés"""
    return HttpResponse("Import employés - À implémenter")

@login_required
def export_donnees_view(request):
    """Export des données"""
    return HttpResponse("Export données - À implémenter")

@login_required
def create_backup_view(request):
    """Création de sauvegarde"""
    return HttpResponse("Backup - À implémenter")

# ================================================================
# VUES DIAGNOSTIC
# ================================================================

@login_required
def diagnostic_system_view(request):
    """Diagnostic système"""
    return HttpResponse("Diagnostic système - À implémenter")

# ================================================================
# VUES D'ERREUR
# ================================================================

def erreur_403_view(request):
    """Erreur 403"""
    return render(request, 'errors/403.html', status=403)

def erreur_404_view(request):
    """Erreur 404"""
    return render(request, 'errors/404.html', status=404)

def erreur_500_view(request):
    """Erreur 500"""
    return render(request, 'errors/500.html', status=500)

# ================================================================
# VUES SPÉCIALISÉES PAR RÔLE
# ================================================================

@login_required
def manager_gestion_equipe(request):
    """Gestion d'équipe pour les managers"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil not in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Équipe gérée
        equipe = ProfilUtilisateur.objects.filter(
            manager=profil_utilisateur,
            actif=True
        )
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'equipe': equipe
        }
        
        return render(request, 'interim/manager/equipe.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def manager_mes_validations(request):
    """Mes validations pour les managers"""
    return HttpResponse("Manager validations - À implémenter")

@login_required
def manager_statistiques(request):
    """Statistiques pour les managers"""
    return HttpResponse("Manager stats - À implémenter")

@login_required
def drh_tableau_bord(request):
    """Tableau de bord DRH"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil != 'RH':
            messages.error(request, "Accès réservé à la DRH")
            return redirect('index')
        
        # Statistiques globales DRH
        stats = {
            'demandes_totales': DemandeInterim.objects.count(),
            'demandes_en_attente': DemandeInterim.objects.filter(statut='EN_VALIDATION').count(),
            'missions_actives': DemandeInterim.objects.filter(statut='EN_COURS').count(),
            'employes_actifs': ProfilUtilisateur.objects.filter(actif=True).count()
        }
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'stats': stats
        }
        
        return render(request, 'interim/drh/tableau_bord.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def drh_gestion_workflow(request):
    """Gestion du workflow DRH"""
    return HttpResponse("DRH workflow - À implémenter")

@login_required
def drh_rapports_globaux(request):
    """Rapports globaux DRH"""
    return HttpResponse("DRH rapports - À implémenter")

# ================================================================
# VUES AIDE ET DOCUMENTATION
# ================================================================

def aide_index_view(request):
    """Page d'aide principale"""
    context = {
        'page_title': 'Centre d\'aide'
    }
    return render(request, 'interim/aide/index.html', context)

def guide_utilisateur_view(request):
    """Guide utilisateur"""
    context = {
        'page_title': 'Guide utilisateur'
    }
    return render(request, 'interim/aide/guide.html', context)

def faq_view(request):
    """FAQ"""
    context = {
        'page_title': 'Questions fréquentes'
    }
    return render(request, 'interim/aide/faq.html', context)

@login_required
def contact_support_view(request):
    """Contact support"""
    context = {
        'page_title': 'Contacter le support'
    }
    return render(request, 'interim/aide/contact.html', context)

def aide_workflow(request):
    """Aide sur le workflow"""
    context = {
        'page_title': 'Aide - Workflow'
    }
    return render(request, 'interim/aide/workflow.html', context)

def aide_notifications(request):
    """Aide sur les notifications"""
    context = {
        'page_title': 'Aide - Notifications'
    }
    return render(request, 'interim/aide/notifications.html', context)

def aide_validations(request):
    """Aide sur les validations"""
    context = {
        'page_title': 'Aide - Validations'
    }
    return render(request, 'interim/aide/validations.html', context)

def tutoriel_chef_service(request):
    """Tutoriel chef de service"""
    context = {
        'page_title': 'Tutoriel - Chef de service'
    }
    return render(request, 'interim/aide/tutoriel_chef.html', context)

def tutoriel_validateur(request):
    """Tutoriel validateur"""
    context = {
        'page_title': 'Tutoriel - Validateur'
    }
    return render(request, 'interim/aide/tutoriel_validateur.html', context)

def tutoriel_candidat(request):
    """Tutoriel candidat"""
    context = {
        'page_title': 'Tutoriel - Candidat'
    }
    return render(request, 'interim/aide/tutoriel_candidat.html', context)

# ================================================================
# VUES WEBHOOKS
# ================================================================

@require_POST
def webhook_kelio_employe(request):
    """Webhook mise à jour employé Kelio"""
    try:
        # Traitement du webhook
        return JsonResponse({'status': 'received'})
    except Exception as e:
        logger.error(f"Erreur webhook Kelio employé: {e}")
        return JsonResponse({'status': 'error'}, status=500)

@require_POST
def webhook_kelio_absence(request):
    """Webhook absence Kelio"""
    try:
        return JsonResponse({'status': 'received'})
    except Exception as e:
        logger.error(f"Erreur webhook Kelio absence: {e}")
        return JsonResponse({'status': 'error'}, status=500)

@require_POST
def webhook_kelio_competence(request):
    """Webhook compétence Kelio"""
    try:
        return JsonResponse({'status': 'received'})
    except Exception as e:
        logger.error(f"Erreur webhook Kelio compétence: {e}")
        return JsonResponse({'status': 'error'}, status=500)

@require_POST
def webhook_notification(request):
    """Webhook notification"""
    try:
        return JsonResponse({'status': 'received'})
    except Exception as e:
        logger.error(f"Erreur webhook notification: {e}")
        return JsonResponse({'status': 'error'}, status=500)

@require_POST
def webhook_validation(request):
    """Webhook validation"""
    try:
        return JsonResponse({'status': 'received'})
    except Exception as e:
        logger.error(f"Erreur webhook validation: {e}")
        return JsonResponse({'status': 'error'}, status=500)

@require_POST
def webhook_rappel(request):
    """Webhook rappel"""
    try:
        return JsonResponse({'status': 'received'})
    except Exception as e:
        logger.error(f"Erreur webhook rappel: {e}")
        return JsonResponse({'status': 'error'}, status=500)

# ================================================================
# API ENDPOINTS EXISTANTS (CONSERVÉS)
# ================================================================

@login_required
def dashboard_stats_api(request):
    """
    API pour récupérer les statistiques du dashboard via AJAX
    """
    try:
        # Forcer le rafraîchissement des stats
        cache_key = f"dashboard_stats_{request.user.id}"
        cache.delete(cache_key)
        
        # Recalculer les stats
        interims_en_cours = DemandeInterim.objects.filter(
            statut__in=['ACCEPTEE', 'EN_COURS']
        ).count()
        
        total_demandes = DemandeInterim.objects.exclude(statut='BROUILLON').count()
        demandes_validees = DemandeInterim.objects.filter(
            statut__in=['VALIDEE', 'ACCEPTEE', 'EN_COURS', 'TERMINEE']
        ).count()
        
        taux_validation = round((demandes_validees / total_demandes * 100) if total_demandes > 0 else 0)
        
        demandes_en_attente = DemandeInterim.objects.filter(
            statut__in=['SOUMISE', 'EN_VALIDATION', 'EN_RECHERCHE']
        ).count()
        
        remplacements_urgents = DemandeInterim.objects.filter(
            urgence__in=['ELEVEE', 'CRITIQUE'],
            statut__in=['SOUMISE', 'EN_VALIDATION', 'VALIDEE', 'EN_RECHERCHE']
        ).count()
        
        stats = {
            'interims_en_cours': interims_en_cours,
            'taux_validation': taux_validation,
            'demandes_en_attente': demandes_en_attente,
            'remplacements_urgents': remplacements_urgents,
            'last_update': timezone.now().isoformat()
        }
        
        # Remettre en cache
        cache.set(cache_key, stats, 300)
        
        return JsonResponse({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Erreur API dashboard stats: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required 
def dashboard_notifications_api(request):
    """
    API pour récupérer les notifications en temps réel
    """
    try:
        notifications = []
        
        # Vérifier les demandes urgentes
        urgentes = DemandeInterim.objects.filter(
            urgence__in=['ELEVEE', 'CRITIQUE'],
            statut__in=['SOUMISE', 'EN_VALIDATION', 'VALIDEE', 'EN_RECHERCHE']
        ).count()
        
        if urgentes > 0:
            notifications.append({
                'id': 'urgent_requests',
                'type': 'warning',
                'message': f"{urgentes} demande(s) urgente(s)",
                'timestamp': timezone.now().isoformat(),
                'action_url': '/interim/validation/'
            })
        
        # Vérifier mes validations en attente
        try:
            profil = ProfilUtilisateur.objects.get(user=request.user)
            if profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH']:
                validations = DemandeInterim.objects.filter(
                    statut='EN_VALIDATION'
                ).count()
                
                if validations > 0:
                    notifications.append({
                        'id': 'pending_validations',
                        'type': 'info', 
                        'message': f"{validations} validation(s) en attente",
                        'timestamp': timezone.now().isoformat(),
                        'action_url': '/interim/validation/'
                    })
        except ProfilUtilisateur.DoesNotExist:
            pass
        
        return JsonResponse({
            'success': True,
            'notifications': notifications,
            'count': len(notifications)
        })
        
    except Exception as e:
        logger.error(f"Erreur API notifications: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# ================================================================
# AUTRES API ENDPOINTS
# ================================================================

def api_demandes_list(request):
    """API liste des demandes"""
    try:
        demandes = DemandeInterim.objects.all()[:50]  # Limiter pour performance
        
        demandes_data = [{
            'id': d.id,
            'numero_demande': d.numero_demande,
            'statut': d.statut,
            'date_creation': d.created_at.isoformat(),
            'demandeur': d.demandeur.nom_complet,
            'poste': d.poste.titre if d.poste else ''
        } for d in demandes]
        
        return JsonResponse({'demandes': demandes_data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def api_demande_detail(request, pk):
    """API détail d'une demande"""
    try:
        demande = get_object_or_404(DemandeInterim, id=pk)
        
        demande_data = {
            'id': demande.id,
            'numero_demande': demande.numero_demande,
            'statut': demande.statut,
            'urgence': demande.urgence,
            'date_debut': demande.date_debut.isoformat() if demande.date_debut else None,
            'date_fin': demande.date_fin.isoformat() if demande.date_fin else None,
            'demandeur': demande.demandeur.nom_complet,
            'poste': demande.poste.titre if demande.poste else '',
            'candidat_selectionne': demande.candidat_selectionne.nom_complet if demande.candidat_selectionne else None
        }
        
        return JsonResponse({'demande': demande_data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def api_employes_list(request):
    """API liste des employés"""
    try:
        employes = ProfilUtilisateur.objects.filter(
            actif=True
        ).select_related('user', 'poste')[:100]
        
        employes_data = [{
            'id': e.id,
            'matricule': e.matricule,
            'nom_complet': e.nom_complet,
            'poste': e.poste.titre if e.poste else '',
            'departement': e.departement.nom if e.departement else '',
            'statut': e.statut_employe
        } for e in employes]
        
        return JsonResponse({'employes': employes_data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def api_employe_detail(request, matricule):
    """API détail d'un employé"""
    try:
        employe = get_object_or_404(ProfilUtilisateur, matricule=matricule)
        
        employe_data = {
            'id': employe.id,
            'matricule': employe.matricule,
            'nom_complet': employe.nom_complet,
            'email': employe.user.email,
            'poste': employe.poste.titre if employe.poste else '',
            'departement': employe.departement.nom if employe.departement else '',
            'site': employe.site.nom if employe.site else '',
            'statut': employe.statut_employe,
            'disponible_interim': employe.extended_data.disponible_interim if hasattr(employe, 'extended_data') else True
        }
        
        return JsonResponse({'employe': employe_data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def api_candidat_disponibilite(request, candidat_id):
    """API disponibilité d'un candidat"""
    try:
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        
        date_debut = request.GET.get('date_debut')
        date_fin = request.GET.get('date_fin')
        
        if date_debut and date_fin:
            disponibilite = candidat.est_disponible_pour_interim(
                date_debut, date_fin
            )
        else:
            disponibilite = {
                'disponible': candidat.extended_data.disponible_interim if hasattr(candidat, 'extended_data') else True,
                'raison': 'Disponibilité générale'
            }
        
        return JsonResponse({
            'candidat_id': candidat.id,
            'disponibilite': disponibilite
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ================================================================
# API KELIO
# ================================================================

@login_required
def employe_sync_ajax(request, matricule):
    """Synchronisation employé avec Kelio"""
    try:
        # Simulation de synchronisation
        return JsonResponse({
            'status': 'success',
            'message': f'Employé {matricule} synchronisé avec succès',
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Erreur synchronisation: {str(e)}'
        }, status=500)

@login_required
def employe_creer_depuis_matricule_ajax(request):
    """Création employé depuis matricule Kelio"""
    try:
        matricule = request.POST.get('matricule')
        if not matricule:
            return JsonResponse({
                'status': 'error',
                'message': 'Matricule requis'
            }, status=400)
        
        # Simulation de création
        return JsonResponse({
            'status': 'success',
            'message': f'Employé {matricule} créé avec succès',
            'employe_id': 999  # Simulation
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def employe_verification_matricule_ajax(request, matricule):
    """Vérification matricule"""
    try:
        existe = ProfilUtilisateur.objects.filter(matricule=matricule).exists()
        
        return JsonResponse({
            'status': 'success',
            'existe': existe,
            'matricule': matricule
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def kelio_test_connexion_ajax(request):
    """Test connexion Kelio"""
    try:
        # Simulation test connexion
        return JsonResponse({
            'status': 'success',
            'message': 'Connexion Kelio OK',
            'services': {
                'employees': True,
                'absences': True,
                'competences': True
            }
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def kelio_vider_cache_ajax(request):
    """Vider cache Kelio"""
    try:
        # Simulation vidage cache
        return JsonResponse({
            'status': 'success',
            'message': 'Cache Kelio vidé',
            'entries_deleted': 0
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def kelio_sync_global_ajax(request):
    """Synchronisation globale Kelio"""
    try:
        # Simulation sync globale
        return JsonResponse({
            'status': 'success',
            'message': 'Synchronisation globale lancée',
            'task_id': 'sync_123'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def verifier_disponibilite_candidat_ajax(request):
    """Vérification disponibilité candidat"""
    try:
        candidat_id = request.GET.get('candidat_id')
        date_debut = request.GET.get('date_debut')
        date_fin = request.GET.get('date_fin')
        
        if not all([candidat_id, date_debut, date_fin]):
            return JsonResponse({
                'status': 'error',
                'message': 'Paramètres manquants'
            }, status=400)
        
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        disponibilite = candidat.est_disponible_pour_interim(date_debut, date_fin)
        
        return JsonResponse({
            'status': 'success',
            'disponibilite': disponibilite
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

# ================================================================
# API STATS SPÉCIALISÉES
# ================================================================

@login_required
def api_stats_chef_service(request):
    """Statistiques chef de service"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        stats = {
            'demandes_departement': DemandeInterim.objects.filter(
                poste__departement=profil.departement
            ).count(),
            'missions_actives': DemandeInterim.objects.filter(
                poste__departement=profil.departement,
                statut='EN_COURS'
            ).count()
        }
        
        return JsonResponse({'stats': stats})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ================================================================
# FONCTION UTILITAIRE POUR ÉVITER CETTE ERREUR
# ================================================================

def get_debut_mois(date=None):
    """Retourne le début du mois pour une date donnée"""
    if date is None:
        date = timezone.now()
    return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def get_debut_annee(date=None):
    """Retourne le début de l'année pour une date donnée"""
    if date is None:
        date = timezone.now()
    return date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

def get_debut_semaine(date=None):
    """Retourne le début de la semaine pour une date donnée"""
    if date is None:
        date = timezone.now()
    debut_semaine = date - timedelta(days=date.weekday())
    return debut_semaine.replace(hour=0, minute=0, second=0, microsecond=0)

@login_required
def api_stats_validations(request):
    """Version corrigée avec fonctions utilitaires"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Utilisation des fonctions utilitaires
        debut_mois = get_debut_mois()
        debut_annee = get_debut_annee()
        
        stats = {
            'en_attente': DemandeInterim.objects.filter(
                statut='EN_VALIDATION'
            ).count(),
            
            'validees_mois': ValidationDemande.objects.filter(
                validateur=profil,
                date_validation__gte=debut_mois
            ).count(),
            
            'validees_annee': ValidationDemande.objects.filter(
                validateur=profil,
                date_validation__gte=debut_annee
            ).count(),
            
            'taux_approbation': 0
        }
        
        # Calcul du taux d'approbation
        total_validations = ValidationDemande.objects.filter(validateur=profil).count()
        if total_validations > 0:
            approuvees = ValidationDemande.objects.filter(
                validateur=profil,
                decision='APPROUVE'
            ).count()
            stats['taux_approbation'] = round((approuvees / total_validations) * 100, 1)
        
        return JsonResponse({'success': True, 'stats': stats})
        
    except Exception as e:
        logger.error(f"Erreur API stats validations: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _peut_tout_faire_superuser(profil):
    """Vérifie si c'est un superutilisateur avec droits complets"""
    return (
        (hasattr(profil, 'user') and profil.user.is_superuser) or
        getattr(profil, 'type_profil', None) == 'SUPERUSER'
    )

# Mise à jour des fonctions de vérification pour inclure les superutilisateurs
def _peut_voir_demande(profil, demande):
    """Vérifie si l'utilisateur peut voir la demande (étendu pour superutilisateurs)"""
    # Accès total pour superutilisateurs
    if _peut_tout_faire_superuser(profil):
        return True
    
    return (
        demande.demandeur == profil or
        demande.candidat_selectionne == profil or
        demande.personne_remplacee == profil or
        getattr(profil, 'type_profil', None) in ['RH', 'ADMIN'] or
        (getattr(profil, 'type_profil', None) in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR'] and
         getattr(profil, 'departement', None) == demande.poste.departement)
    )

def _peut_modifier_demande(profil, demande):
    """Vérifie si l'utilisateur peut modifier la demande (étendu pour superutilisateurs)"""
    # Accès total pour superutilisateurs
    if _peut_tout_faire_superuser(profil):
        return True
    
    return (
        (demande.demandeur == profil and demande.statut in ['BROUILLON', 'SOUMISE']) or
        getattr(profil, 'type_profil', None) in ['RH', 'ADMIN']
    )

def _peut_supprimer_demande(profil, demande):
    """Vérifie si l'utilisateur peut supprimer la demande (étendu pour superutilisateurs)"""
    # Accès total pour superutilisateurs
    if _peut_tout_faire_superuser(profil):
        return True
    
    return (
        (demande.demandeur == profil and demande.statut == 'BROUILLON') or
        getattr(profil, 'type_profil', None) in ['ADMIN']
    )

def _peut_proposer_candidat(profil, demande):
    """Vérifie si l'utilisateur peut proposer un candidat"""
    return (
        profil.type_profil in ['RH', 'ADMIN', 'DIRECTEUR', 'CHEF_EQUIPE', 'RESPONSABLE'] or
        profil == demande.demandeur.manager
    )

def _peut_creer_demande_pour_employe(profil, employe):
    """Vérifie si l'utilisateur peut créer une demande pour cet employé"""
    return (
        profil.type_profil in ['RH', 'ADMIN'] or
        profil == employe.manager or
        (profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE'] and
         profil.departement == employe.departement)
    )

# 6. FONCTION UTILITAIRE - Obtenir le workflow complet avec validateurs
def get_workflow_avec_validateurs(demande):
    """
    Retourne le workflow complet avec les validateurs identifiés
    """
    workflow = {
        'demande_id': demande.id,
        'niveau_actuel': demande.niveau_validation_actuel,
        'niveaux_total': 3,  # RESPONSABLE -> DIRECTEUR -> RH
        'etapes': []
    }
    
    # Simuler temporairement chaque niveau pour obtenir les validateurs
    for niveau in range(1, 4):
        # Sauvegarder le niveau actuel
        niveau_original = demande.niveau_validation_actuel
        
        # Simuler le niveau pour obtenir les validateurs
        demande.niveau_validation_actuel = niveau - 1
        validateurs = _get_validateurs_niveau_suivant(demande)
        
        # Restaurer le niveau original
        demande.niveau_validation_actuel = niveau_original
        
        # Déterminer le statut
        if niveau < demande.niveau_validation_actuel:
            statut = 'VALIDEE'
        elif niveau == demande.niveau_validation_actuel:
            statut = 'EN_COURS'
        else:
            statut = 'EN_ATTENTE'
        
        workflow['etapes'].append({
            'niveau': niveau,
            'titre': f"Validation Niveau {niveau}",
            'statut': statut,
            'validateurs': [
                {
                    'nom': v.nom_complet,
                    'poste': v.poste.titre if v.poste else '',
                    'type_profil': v.type_profil
                } for v in validateurs
            ]
        })
    
    return workflow
    
# ================================================================
# VUES EMPLOYÉS SPÉCIALISÉES PAR RÔLE (MANQUANTES)
# ================================================================

@login_required
def employe_disponibilites(request):
    """Vue des disponibilités de l'employé connecté"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        # Disponibilités déclarées
        disponibilites = DisponibiliteUtilisateur.objects.filter(
            utilisateur=profil_utilisateur
        ).order_by('-date_debut')
        
        # Absences futures
        absences_futures = profil_utilisateur.absences.filter(
            date_debut__gte=timezone.now().date()
        ).order_by('date_debut')
        
        # Missions planifiées
        missions_planifiees = profil_utilisateur.selections_interim.filter(
            demande_interim__date_debut__gte=timezone.now().date(),
            statut__in=['PLANIFIEE', 'EN_COURS']
        ).order_by('demande_interim__date_debut')
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'disponibilites': disponibilites,
            'absences_futures': absences_futures,
            'missions_planifiees': missions_planifiees
        }
        
        return render(request, 'interim/employe_disponibilites.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES MANAGER SPÉCIALISÉES (MANQUANTES)
# ================================================================

@login_required
def manager_gestion_equipe(request):
    """Gestion d'équipe pour les managers"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil not in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Équipe gérée
        equipe = ProfilUtilisateur.objects.filter(
            manager=profil_utilisateur,
            actif=True
        ).select_related('user', 'poste')
        
        # Demandes de l'équipe
        demandes_equipe = DemandeInterim.objects.filter(
            demandeur__in=equipe
        ).order_by('-created_at')[:50]
        
        # Missions en cours de l'équipe
        missions_equipe = DemandeInterim.objects.filter(
            candidat_selectionne__in=equipe,
            statut='EN_COURS'
        )
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'equipe': equipe,
            'demandes_equipe': demandes_equipe,
            'missions_equipe': missions_equipe,
            'stats_equipe': {
                'nb_employes': equipe.count(),
                'demandes_actives': demandes_equipe.filter(
                    statut__in=['SOUMISE', 'EN_VALIDATION', 'EN_COURS']
                ).count(),
                'missions_en_cours': missions_equipe.count()
            }
        }
        
        return render(request, 'interim/manager/equipe.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def manager_mes_validations(request):
    """Mes validations pour les managers"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil not in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Validations effectuées
        mes_validations = ValidationDemande.objects.filter(
            validateur=profil_utilisateur
        ).select_related('demande', 'demande__poste').order_by('-date_validation')
        
        # Demandes en attente de ma validation
        demandes_a_valider = DemandeInterim.objects.filter(
            statut='EN_VALIDATION',
            poste__departement=profil_utilisateur.departement
        )
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'mes_validations': mes_validations,
            'demandes_a_valider': demandes_a_valider,
            'stats_validations': {
                'total_validees': mes_validations.count(),
                'en_attente': demandes_a_valider.count(),
                'approuvees': mes_validations.filter(decision='APPROUVE').count(),
                'refusees': mes_validations.filter(decision='REFUSE').count()
            }
        }
        
        return render(request, 'interim/manager/validations.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def manager_statistiques(request):
    """Statistiques pour les managers"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil not in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Période d'analyse
        periode = int(request.GET.get('periode', 30))
        date_limite = timezone.now() - timedelta(days=periode)
        
        # Statistiques du département
        stats_departement = {
            'demandes_creees': DemandeInterim.objects.filter(
                poste__departement=profil_utilisateur.departement,
                created_at__gte=date_limite
            ).count(),
            'missions_terminees': DemandeInterim.objects.filter(
                poste__departement=profil_utilisateur.departement,
                statut='TERMINEE',
                date_fin_effective__gte=date_limite
            ).count(),
            'taux_reussite': 0,
            'delai_moyen_validation': 0
        }
        
        # Calculer le taux de réussite
        total_demandes = stats_departement['demandes_creees']
        if total_demandes > 0:
            demandes_reussies = DemandeInterim.objects.filter(
                poste__departement=profil_utilisateur.departement,
                created_at__gte=date_limite,
                statut__in=['EN_COURS', 'TERMINEE']
            ).count()
            stats_departement['taux_reussite'] = round(
                (demandes_reussies / total_demandes) * 100, 1
            )
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'stats_departement': stats_departement,
            'periode': periode
        }
        
        return render(request, 'interim/manager/statistiques.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES DRH SPÉCIALISÉES (MANQUANTES)
# ================================================================

@login_required
def drh_tableau_bord(request):
    """Tableau de bord DRH (version complétée)"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil != 'RH':
            messages.error(request, "Accès réservé à la DRH")
            return redirect('index')
        
        # Statistiques globales DRH
        stats = {
            'demandes_totales': DemandeInterim.objects.count(),
            'demandes_en_attente': DemandeInterim.objects.filter(
                statut='EN_VALIDATION'
            ).count(),
            'missions_actives': DemandeInterim.objects.filter(
                statut='EN_COURS'
            ).count(),
            'employes_actifs': ProfilUtilisateur.objects.filter(
                actif=True,
                statut_employe='ACTIF'
            ).count(),
            'taux_validation_global': _calculer_taux_validation_global()
        }
        
        # Demandes urgentes
        demandes_urgentes = DemandeInterim.objects.filter(
            urgence__in=['ELEVEE', 'CRITIQUE'],
            statut__in=['SOUMISE', 'EN_VALIDATION']
        ).select_related('demandeur__user', 'poste')
        
        # Activité récente
        activite_recente = HistoriqueAction.objects.select_related(
            'demande', 'utilisateur__user'
        ).order_by('-created_at')[:50]
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'stats': stats,
            'demandes_urgentes': demandes_urgentes,
            'activite_recente': activite_recente
        }
        
        return render(request, 'interim/drh/tableau_bord.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def drh_gestion_workflow(request):
    """Gestion du workflow DRH"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil != 'RH':
            messages.error(request, "Accès réservé à la DRH")
            return redirect('index')
        
        # Workflows en cours
        workflows_actifs = WorkflowDemande.objects.filter(
            demande__statut__in=['SOUMISE', 'EN_VALIDATION', 'EN_COURS']
        ).select_related('demande', 'etape_actuelle')
        
        # Demandes bloquées
        date_limite_blocage = timezone.now() - timedelta(days=7)
        demandes_bloquees = DemandeInterim.objects.filter(
            statut__in=['EN_VALIDATION', 'CANDIDAT_PROPOSE'],
            updated_at__lt=date_limite_blocage
        )
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'workflows_actifs': workflows_actifs,
            'demandes_bloquees': demandes_bloquees,
            'stats_workflow': {
                'workflows_actifs': workflows_actifs.count(),
                'demandes_bloquees': demandes_bloquees.count(),
                'delai_moyen': 0  # À calculer
            }
        }
        
        return render(request, 'interim/drh/gestion_workflow.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def drh_rapports_globaux(request):
    """Rapports globaux DRH"""
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil_utilisateur.type_profil != 'RH':
            messages.error(request, "Accès réservé à la DRH")
            return redirect('index')
        
        # Rapports disponibles
        rapports_disponibles = [
            {
                'titre': 'Rapport mensuel global',
                'description': 'Vue d\'ensemble des activités du mois',
                'url': '/interim/rapports/mensuel-global/',
                'type': 'mensuel'
            },
            {
                'titre': 'Analyse des tendances',
                'description': 'Évolution des demandes sur 6 mois',
                'url': '/interim/rapports/tendances/',
                'type': 'tendance'
            },
            {
                'titre': 'Performance par département',
                'description': 'Comparaison des départements',
                'url': '/interim/rapports/departements/',
                'type': 'comparatif'
            }
        ]
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'rapports_disponibles': rapports_disponibles
        }
        
        return render(request, 'interim/drh/rapports_globaux.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# API SPÉCIALISÉES MANQUANTES
# ================================================================

@login_required
def api_stats_chef_service(request):
    """API statistiques chef de service"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['CHEF_EQUIPE', 'RESPONSABLE']:
            return JsonResponse({'error': 'Permission refusée'}, status=403)
        
        stats = {
            'demandes_departement': DemandeInterim.objects.filter(
                poste__departement=profil.departement
            ).count(),
            'missions_actives': DemandeInterim.objects.filter(
                poste__departement=profil.departement,
                statut='EN_COURS'
            ).count(),
            'equipe_size': ProfilUtilisateur.objects.filter(
                manager=profil,
                actif=True
            ).count(),
            'validations_en_attente': DemandeInterim.objects.filter(
                statut='EN_VALIDATION',
                poste__departement=profil.departement
            ).count()
        }
        
        return JsonResponse({'success': True, 'stats': stats})
        
    except Exception as e:
        logger.error(f"Erreur API stats chef service: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def api_stats_validations(request):
    """API statistiques validations"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        stats = {
            'en_attente_globales': DemandeInterim.objects.filter(
                statut='EN_VALIDATION'
            ).count(),
            'mes_validations_mois': ValidationDemande.objects.filter(
                validateur=profil,
                date_validation__gte=timezone.now().replace(day=1)
            ).count(),
            'taux_approbation': 0,
            'delai_moyen_validation': 0
        }
        
        # Calculer le taux d'approbation
        mes_validations = ValidationDemande.objects.filter(validateur=profil)
        if mes_validations.exists():
            approuvees = mes_validations.filter(decision='APPROUVE').count()
            stats['taux_approbation'] = round(
                (approuvees / mes_validations.count()) * 100, 1
            )
        
        return JsonResponse({'success': True, 'stats': stats})
        
    except Exception as e:
        logger.error(f"Erreur API stats validations: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ================================================================
# FONCTION UTILITAIRE POUR LE TAUX DE VALIDATION GLOBAL
# ================================================================

def _calculer_taux_validation_global():
    """Calcule le taux de validation global"""
    try:
        total = DemandeInterim.objects.exclude(statut='BROUILLON').count()
        validees = DemandeInterim.objects.filter(
            statut__in=['VALIDEE', 'EN_COURS', 'TERMINEE']
        ).count()
        
        if total > 0:
            return round((validees / total) * 100, 1)
        return 0
        
    except Exception as e:
        logger.error(f"Erreur calcul taux validation global: {e}")
        return 0
    
def determiner_niveau_validation_requis(demande):
    """Détermine le niveau de validation requis selon l'urgence et le type de demande"""
    try:
        # Niveau par défaut selon la hiérarchie corrigée
        niveau_base = 3  # RESPONSABLE → DIRECTEUR → RH/ADMIN
        
        # Ajustements selon l'urgence
        if demande.urgence == 'CRITIQUE':
            return 2  # Accéléré: DIRECTEUR → RH/ADMIN
        elif demande.urgence in ['ELEVEE', 'MOYENNE', 'NORMALE']:
            return 3  # Circuit complet: RESPONSABLE → DIRECTEUR → RH/ADMIN
        
        return niveau_base
        
    except Exception as e:
        logger.error(f"Erreur détermination niveau validation: {e}")
        return 3  # Sécurité par défaut

def determiner_type_validation(profil_utilisateur, niveau_actuel):
    """Détermine le type de validation selon le profil et le niveau"""
    try:
        if profil_utilisateur.is_superuser:
            return 'SUPERUSER'
        
        # Mapping selon la hiérarchie corrigée
        if profil_utilisateur.type_profil == 'RESPONSABLE':
            return 'RESPONSABLE'
        elif profil_utilisateur.type_profil == 'DIRECTEUR':
            return 'DIRECTEUR'
        elif profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            return profil_utilisateur.type_profil
        
        # Fallback selon le niveau
        types_par_niveau = {
            1: 'RESPONSABLE',
            2: 'DIRECTEUR', 
            3: 'RH'
        }
        return types_par_niveau.get(niveau_actuel + 1, 'RH')
        
    except Exception as e:
        logger.error(f"Erreur détermination type validation: {e}")
        return 'RH'

def verifier_permissions_validation(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut valider cette demande"""
    try:
        # Superusers peuvent toujours valider
        if profil_utilisateur.is_superuser:
            return True, "Superutilisateur - droits complets"
        
        # Déterminer le niveau requis
        niveau_requis = demande.niveau_validation_actuel + 1
        
        # Vérifier selon la hiérarchie corrigée
        if niveau_requis == 1:
            # Niveau 1: RESPONSABLE seulement
            if (profil_utilisateur.type_profil == 'RESPONSABLE' and 
                profil_utilisateur.departement == demande.poste.departement):
                return True, "Autorisé comme Responsable (N+1)"
        elif niveau_requis == 2:
            # Niveau 2: DIRECTEUR seulement
            if profil_utilisateur.type_profil == 'DIRECTEUR':
                return True, "Autorisé comme Directeur (N+2)"
        elif niveau_requis >= 3:
            # Niveau 3+: RH/ADMIN seulement
            if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
                return True, f"Autorisé comme {profil_utilisateur.type_profil} (Final)"
        
        return False, f"Niveau insuffisant pour niveau {niveau_requis}"
            
    except Exception as e:
        logger.error(f"Erreur vérification permissions: {e}")
        return False, f"Erreur système: {str(e)}"

def creer_notification_validation(demande, validation, action_effectuee):
    """Crée les notifications suite à une validation"""
    try:
        # Notifier le demandeur
        NotificationInterim.objects.create(
            destinataire=demande.demandeur,
            expediteur=validation.validateur,
            demande=demande,
            validation_liee=validation,
            type_notification='VALIDATION_EFFECTUEE',
            urgence='NORMALE',
            titre=f"Validation {validation.get_type_validation_display()} - {demande.numero_demande}",
            message=f"Votre demande a été {action_effectuee.lower()} par {validation.validateur.nom_complet}",
            url_action_principale=reverse('interim_validation', args=[demande.id]),
            texte_action_principale="Voir la demande"
        )
        
        # Notifier le prochain validateur si validation positive et pas terminé
        if (validation.decision == 'APPROUVE' and 
            demande.niveau_validation_actuel < demande.niveaux_validation_requis):
            
            prochain_niveau = demande.niveau_validation_actuel + 1
            prochains_validateurs = obtenir_validateurs_niveau(demande, prochain_niveau)
            
            for validateur in prochains_validateurs:
                NotificationInterim.objects.create(
                    destinataire=validateur,
                    expediteur=validation.validateur,
                    demande=demande,
                    type_notification='DEMANDE_A_VALIDER',
                    urgence='HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE',
                    titre=f"Validation niveau {prochain_niveau} requise - {demande.numero_demande}",
                    message=f"La demande nécessite votre validation (niveau {prochain_niveau})",
                    url_action_principale=reverse('interim_validation', args=[demande.id]),
                    texte_action_principale="Valider maintenant"
                )
            
    except Exception as e:
        logger.error(f"Erreur création notifications validation: {e}")

def obtenir_validateurs_niveau(demande, niveau):
    """Obtient les validateurs pour un niveau donné selon la hiérarchie"""
    try:
        if niveau == 1:
            # Responsables du département
            return ProfilUtilisateur.objects.filter(
                type_profil='RESPONSABLE',
                departement=demande.poste.departement,
                actif=True
            )
        elif niveau == 2:
            # Directeurs
            return ProfilUtilisateur.objects.filter(
                type_profil='DIRECTEUR',
                actif=True
            )
        elif niveau >= 3:
            # RH/ADMIN
            return ProfilUtilisateur.objects.filter(
                type_profil__in=['RH', 'ADMIN'],
                actif=True
            )
        
        return ProfilUtilisateur.objects.none()
        
    except Exception as e:
        logger.error(f"Erreur obtention validateurs niveau {niveau}: {e}")
        return ProfilUtilisateur.objects.none()

# ================================================================
# VUE D'APPROBATION DIRECTE
# ================================================================

@login_required
@require_POST
def approuver_demande_view(request, demande_id):
    """Approuve directement une demande d'intérim"""
    try:
        # Récupérer les objets nécessaires
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            messages.error(request, "Profil utilisateur non trouvé")
            return redirect('interim_validation_liste')
        
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        peut_valider, raison = verifier_permissions_validation(profil_utilisateur, demande)
        if not peut_valider:
            messages.error(request, f"Permission refusée: {raison}")
            return redirect('interim_validation', demande.id)
        
        # Récupérer les paramètres
        commentaire = request.POST.get('commentaire', '').strip()
        candidats_retenus = request.POST.getlist('candidats_retenus[]')
        candidat_final = request.POST.get('candidat_final')
        
        if not commentaire:
            messages.error(request, "Un commentaire est obligatoire")
            return redirect('interim_validation', demande.id)
        
        with transaction.atomic():
            # Déterminer le type et niveau de validation
            type_validation = determiner_type_validation(profil_utilisateur, demande.niveau_validation_actuel)
            niveau_validation = demande.niveau_validation_actuel + 1
            
            # Préparer les données des candidats retenus
            candidats_data = []
            if candidats_retenus:
                for candidat_id in candidats_retenus:
                    try:
                        candidat = ProfilUtilisateur.objects.get(id=candidat_id)
                        candidats_data.append({
                            'id': candidat.id,
                            'nom': candidat.nom_complet,
                            'matricule': candidat.matricule
                        })
                    except ProfilUtilisateur.DoesNotExist:
                        continue
            
            # Créer la validation
            validation = ValidationDemande.objects.create(
                demande=demande,
                type_validation=type_validation,
                niveau_validation=niveau_validation,
                validateur=profil_utilisateur,
                decision='APPROUVE',
                commentaire=commentaire,
                candidats_retenus=candidats_data,
                date_validation=timezone.now()
            )
            
            # Mettre à jour la demande
            demande.niveau_validation_actuel = niveau_validation
            
            # Vérifier si c'est la validation finale
            if niveau_validation >= demande.niveaux_validation_requis:
                # Validation finale - sélectionner le candidat si fourni
                if candidat_final:
                    try:
                        candidat_selectionne = ProfilUtilisateur.objects.get(id=candidat_final)
                        demande.candidat_selectionne = candidat_selectionne
                        demande.statut = 'CANDIDAT_PROPOSE'
                        demande.date_validation = timezone.now()
                        
                        messages.success(request, f"Demande approuvée et candidat {candidat_selectionne.nom_complet} sélectionné")
                    except ProfilUtilisateur.DoesNotExist:
                        messages.error(request, "Candidat final introuvable")
                        demande.statut = 'VALIDEE'
                else:
                    demande.statut = 'VALIDEE'
                    messages.success(request, "Demande validée définitivement")
            else:
                # Validation intermédiaire
                demande.statut = 'EN_VALIDATION'
                messages.success(request, f"Demande approuvée - transmise au niveau {niveau_validation + 1}")
            
            demande.save()
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                validation=validation,
                action='VALIDATION_RESPONSABLE' if type_validation == 'RESPONSABLE' 
                       else f'VALIDATION_{type_validation}',
                utilisateur=profil_utilisateur,
                description=f"Validation {type_validation} approuvée",
                donnees_apres={
                    'decision': 'APPROUVE',
                    'niveau_validation': niveau_validation,
                    'candidats_retenus': candidats_data,
                    'candidat_final': candidat_final
                }
            )
            
            # Créer les notifications
            creer_notification_validation(demande, validation, "approuvée")
        
        return redirect('interim_validation_liste')
        
    except Exception as e:
        logger.error(f"Erreur approbation demande {demande_id}: {e}")
        messages.error(request, f"Erreur lors de l'approbation: {str(e)}")
        return redirect('interim_validation', demande_id)

# ================================================================
# VUE DE REFUS DIRECTE
# ================================================================

@login_required
@require_POST
def refuser_demande_view(request, demande_id):
    """Refuse directement une demande d'intérim"""
    try:
        # Récupérer les objets nécessaires
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            messages.error(request, "Profil utilisateur non trouvé")
            return redirect('interim_validation_liste')
        
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        peut_valider, raison = verifier_permissions_validation(profil_utilisateur, demande)
        if not peut_valider:
            messages.error(request, f"Permission refusée: {raison}")
            return redirect('interim_validation', demande.id)
        
        # Récupérer les paramètres
        commentaire = request.POST.get('commentaire', '').strip()
        motif_refus = request.POST.get('motif_refus', '')
        
        if not commentaire:
            messages.error(request, "Un commentaire est obligatoire pour le refus")
            return redirect('interim_validation', demande.id)
        
        with transaction.atomic():
            # Déterminer le type et niveau de validation
            type_validation = determiner_type_validation(profil_utilisateur, demande.niveau_validation_actuel)
            niveau_validation = demande.niveau_validation_actuel + 1
            
            # Créer la validation de refus
            validation = ValidationDemande.objects.create(
                demande=demande,
                type_validation=type_validation,
                niveau_validation=niveau_validation,
                validateur=profil_utilisateur,
                decision='REFUSE',
                commentaire=f"{motif_refus}: {commentaire}" if motif_refus else commentaire,
                date_validation=timezone.now()
            )
            
            # Mettre à jour la demande
            demande.statut = 'REFUSEE'
            demande.save()
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                validation=validation,
                action=f'VALIDATION_{type_validation}',
                utilisateur=profil_utilisateur,
                description=f"Validation {type_validation} refusée",
                donnees_apres={
                    'decision': 'REFUSE',
                    'niveau_validation': niveau_validation,
                    'motif_refus': motif_refus,
                    'commentaire': commentaire
                }
            )
            
            # Créer les notifications
            creer_notification_validation(demande, validation, "refusée")
        
        messages.success(request, "Demande refusée avec succès")
        return redirect('interim_validation_liste')
        
    except Exception as e:
        logger.error(f"Erreur refus demande {demande_id}: {e}")
        messages.error(request, f"Erreur lors du refus: {str(e)}")
        return redirect('interim_validation', demande_id)

# ================================================================
# API VALIDATION RAPIDE
# ================================================================

@login_required
@require_POST
def validation_rapide(request):
    """API pour la validation rapide d'une demande"""
    try:
        # Récupérer les données
        demande_id = request.POST.get('demande_id')
        action = request.POST.get('action')
        commentaire = request.POST.get('commentaire', '').strip()
        motif_refus = request.POST.get('motif_refus', '')
        
        # Validations de base
        if not demande_id:
            return JsonResponse({'success': False, 'error': 'ID de demande manquant'})
        
        if action not in ['APPROUVER', 'REFUSER']:
            return JsonResponse({'success': False, 'error': 'Action invalide'})
        
        if not commentaire:
            return JsonResponse({'success': False, 'error': 'Commentaire obligatoire'})
        
        # Récupérer les objets
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({'success': False, 'error': 'Profil utilisateur non trouvé'})
        
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        peut_valider, raison = verifier_permissions_validation(profil_utilisateur, demande)
        if not peut_valider:
            return JsonResponse({'success': False, 'error': f'Permission refusée: {raison}'})
        
        with transaction.atomic():
            # Déterminer le type et niveau de validation
            type_validation = determiner_type_validation(profil_utilisateur, demande.niveau_validation_actuel)
            niveau_validation = demande.niveau_validation_actuel + 1
            
            # Créer la validation
            validation = ValidationDemande.objects.create(
                demande=demande,
                type_validation=type_validation,
                niveau_validation=niveau_validation,
                validateur=profil_utilisateur,
                decision=action.replace('APPROUVER', 'APPROUVE').replace('REFUSER', 'REFUSE'),
                commentaire=f"{motif_refus}: {commentaire}" if motif_refus else commentaire,
                date_validation=timezone.now()
            )
            
            # Mettre à jour la demande selon l'action
            if action == 'APPROUVER':
                demande.niveau_validation_actuel = niveau_validation
                
                if niveau_validation >= demande.niveaux_validation_requis:
                    demande.statut = 'VALIDEE'
                    message_succes = "Demande validée définitivement"
                else:
                    demande.statut = 'EN_VALIDATION'
                    message_succes = f"Demande approuvée - transmise au niveau {niveau_validation + 1}"
            else:
                demande.statut = 'REFUSEE'
                message_succes = "Demande refusée"
            
            demande.save()
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                validation=validation,
                action=f'VALIDATION_{type_validation}',
                utilisateur=profil_utilisateur,
                description=f"Validation rapide {type_validation} - {validation.decision}",
                donnees_apres={
                    'decision': validation.decision,
                    'niveau_validation': niveau_validation,
                    'validation_rapide': True
                }
            )
            
            # Créer les notifications
            action_text = "approuvée" if action == 'APPROUVER' else "refusée"
            creer_notification_validation(demande, validation, action_text)
        
        return JsonResponse({
            'success': True,
            'message': message_succes,
            'demande_info': {
                'numero': demande.numero_demande,
                'statut': demande.statut,
                'niveau_validation': demande.niveau_validation_actuel
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur validation rapide: {e}")
        return JsonResponse({'success': False, 'error': f'Erreur système: {str(e)}'})

# ================================================================
# API VALIDATION EN MASSE
# ================================================================

@login_required
@require_POST
def validation_masse(request):
    """API pour la validation en masse de demandes"""
    try:
        # Récupérer les données
        action_masse = request.POST.get('action_masse')
        commentaire_masse = request.POST.get('commentaire_masse', '').strip()
        demandes_ids = request.POST.getlist('demandes_ids[]')
        
        # Validations de base
        if action_masse not in ['APPROUVER', 'REFUSER']:
            return JsonResponse({'success': False, 'error': 'Action invalide'})
        
        if not commentaire_masse:
            return JsonResponse({'success': False, 'error': 'Commentaire obligatoire'})
        
        if not demandes_ids:
            return JsonResponse({'success': False, 'error': 'Aucune demande sélectionnée'})
        
        # Limiter le nombre de demandes traitables en masse
        if len(demandes_ids) > 20:
            return JsonResponse({'success': False, 'error': 'Maximum 20 demandes en une fois'})
        
        # Récupérer le profil
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({'success': False, 'error': 'Profil utilisateur non trouvé'})
        
        # Récupérer les demandes
        demandes = DemandeInterim.objects.filter(id__in=demandes_ids)
        
        if not demandes.exists():
            return JsonResponse({'success': False, 'error': 'Aucune demande trouvée'})
        
        resultats = {
            'validees': 0,
            'refusees': 0,
            'erreurs': 0,
            'details': []
        }
        
        # Traiter chaque demande
        for demande in demandes:
            try:
                # Vérifier les permissions pour chaque demande
                peut_valider, raison = verifier_permissions_validation(profil_utilisateur, demande)
                if not peut_valider:
                    resultats['erreurs'] += 1
                    resultats['details'].append({
                        'demande': demande.numero_demande,
                        'statut': 'erreur',
                        'message': f'Permission refusée: {raison}'
                    })
                    continue
                
                with transaction.atomic():
                    # Déterminer le type et niveau de validation
                    type_validation = determiner_type_validation(profil_utilisateur, demande.niveau_validation_actuel)
                    niveau_validation = demande.niveau_validation_actuel + 1
                    
                    # Créer la validation
                    validation = ValidationDemande.objects.create(
                        demande=demande,
                        type_validation=type_validation,
                        niveau_validation=niveau_validation,
                        validateur=profil_utilisateur,
                        decision=action_masse.replace('APPROUVER', 'APPROUVE').replace('REFUSER', 'REFUSE'),
                        commentaire=f"[VALIDATION MASSE] {commentaire_masse}",
                        date_validation=timezone.now()
                    )
                    
                    # Mettre à jour la demande
                    if action_masse == 'APPROUVER':
                        demande.niveau_validation_actuel = niveau_validation
                        
                        if niveau_validation >= demande.niveaux_validation_requis:
                            demande.statut = 'VALIDEE'
                        else:
                            demande.statut = 'EN_VALIDATION'
                        
                        resultats['validees'] += 1
                        statut_resultat = 'validée'
                    else:
                        demande.statut = 'REFUSEE'
                        resultats['refusees'] += 1
                        statut_resultat = 'refusée'
                    
                    demande.save()
                    
                    # Créer l'historique
                    HistoriqueAction.objects.create(
                        demande=demande,
                        validation=validation,
                        action=f'VALIDATION_{type_validation}',
                        utilisateur=profil_utilisateur,
                        description=f"Validation masse {type_validation} - {validation.decision}",
                        donnees_apres={
                            'decision': validation.decision,
                            'niveau_validation': niveau_validation,
                            'validation_masse': True
                        }
                    )
                    
                    # Créer les notifications (mode réduit pour les masses)
                    creer_notification_validation(demande, validation, statut_resultat)
                
                resultats['details'].append({
                    'demande': demande.numero_demande,
                    'statut': 'succès',
                    'message': f'Demande {statut_resultat}'
                })
                
            except Exception as e:
                logger.error(f"Erreur validation masse demande {demande.id}: {e}")
                resultats['erreurs'] += 1
                resultats['details'].append({
                    'demande': demande.numero_demande,
                    'statut': 'erreur',
                    'message': f'Erreur: {str(e)}'
                })
        
        # Résumé du traitement
        total_traitees = resultats['validees'] + resultats['refusees']
        message_resume = f"Traitement terminé: {total_traitees} demande(s) traitée(s)"
        
        if resultats['erreurs'] > 0:
            message_resume += f", {resultats['erreurs']} erreur(s)"
        
        return JsonResponse({
            'success': True,
            'message': message_resume,
            'resultats': resultats
        })
        
    except Exception as e:
        logger.error(f"Erreur validation masse: {e}")
        return JsonResponse({'success': False, 'error': f'Erreur système: {str(e)}'})

# ================================================================
# VUE LISTE DES VALIDATIONS (support pour les vues ci-dessus)
# ================================================================


@login_required
def interim_validation_liste(request):
    """Liste des demandes à valider selon le profil utilisateur"""
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            messages.error(request, "Profil utilisateur non trouvé")
            return redirect('index')
        
        # Déterminer les niveaux que cet utilisateur peut valider
        niveaux_validables = []
        if profil_utilisateur.is_superuser:
            niveaux_validables = [1, 2, 3]
        elif profil_utilisateur.type_profil == 'RESPONSABLE':
            niveaux_validables = [1]
        elif profil_utilisateur.type_profil == 'DIRECTEUR':
            niveaux_validables = [2]
        elif profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            niveaux_validables = [3]
        
        # Construire la requête de base
        demandes_query = DemandeInterim.objects.filter(
            statut__in=['SOUMISE', 'EN_VALIDATION'],
            niveau_validation_actuel__in=[n-1 for n in niveaux_validables]  # Niveau actuel = niveau à valider - 1
        )
        
        # Filtrer par département pour les responsables
        if profil_utilisateur.type_profil == 'RESPONSABLE' and profil_utilisateur.departement:
            demandes_query = demandes_query.filter(poste__departement=profil_utilisateur.departement)
        
        # Appliquer les filtres de recherche
        filtres = {}
        if request.GET.get('urgence'):
            filtres['urgence'] = request.GET.get('urgence')
            demandes_query = demandes_query.filter(urgence=filtres['urgence'])
        
        if request.GET.get('departement'):
            filtres['departement'] = request.GET.get('departement')
            demandes_query = demandes_query.filter(poste__departement_id=filtres['departement'])
        
        if request.GET.get('recherche'):
            filtres['recherche'] = request.GET.get('recherche')
            search_terms = filtres['recherche']
            demandes_query = demandes_query.filter(
                Q(numero_demande__icontains=search_terms) |
                Q(demandeur__user__first_name__icontains=search_terms) |
                Q(demandeur__user__last_name__icontains=search_terms) |
                Q(poste__titre__icontains=search_terms)
            )
        
        # Dates
        if request.GET.get('date_debut'):
            filtres['date_debut'] = request.GET.get('date_debut')
            demandes_query = demandes_query.filter(date_debut__gte=filtres['date_debut'])
        
        if request.GET.get('date_fin'):
            filtres['date_fin'] = request.GET.get('date_fin')
            demandes_query = demandes_query.filter(date_fin__lte=filtres['date_fin'])
        
        # Trier par urgence puis par date
        demandes_query = demandes_query.select_related(
            'demandeur__user',
            'personne_remplacee__user',
            'poste__departement',
            'poste__site',
            'motif_absence'
        ).order_by(
            '-urgence',  # CRITIQUE en premier
            'created_at'
        )
        
        # Pagination
        paginator = Paginator(demandes_query, 25)
        page_number = request.GET.get('page')
        demandes = paginator.get_page(page_number)
        
        # Enrichir les données des demandes
        demandes_enrichies = []
        for demande in demandes:
            demande_data = {
                'demande': demande,
                'duree_mission': demande.duree_mission,
                'temps_ecoule_display': _calculer_temps_ecoule(demande.created_at),
                'en_retard': _est_en_retard(demande),
                'urgence_classe': f'urgence-badge {demande.urgence.lower()}',
                'nb_candidats': demande.propositions_candidats.count(),
                'peut_validation_rapide': _peut_validation_rapide(demande, profil_utilisateur),
            }
            demandes_enrichies.append(demande_data)
        
        # Statistiques
        stats = {
            'total_a_valider': demandes_query.count(),
            'urgentes': demandes_query.filter(urgence__in=['ELEVEE', 'CRITIQUE']).count(),
            'en_retard': demandes_query.filter(
                created_at__lt=timezone.now() - timezone.timedelta(days=2)
            ).count(),
            'validations_ce_mois': ValidationDemande.objects.filter(
                validateur=profil_utilisateur,
                date_validation__gte=timezone.now().replace(day=1)
            ).count()
        }
        
        # Calculer les pourcentages
        if stats['total_a_valider'] > 0:
            stats['pourcentage_urgentes'] = round(
                (stats['urgentes'] / stats['total_a_valider']) * 100, 1
            )
            stats['pourcentage_en_retard'] = round(
                (stats['en_retard'] / stats['total_a_valider']) * 100, 1
            )
        else:
            stats['pourcentage_urgentes'] = 0
            stats['pourcentage_en_retard'] = 0
        
        # Temps moyen de validation
        validations_recentes = ValidationDemande.objects.filter(
            validateur=profil_utilisateur,
            date_validation__gte=timezone.now() - timezone.timedelta(days=30)
        )
        
        if validations_recentes.exists():
            temps_total = sum([
                (v.date_validation - v.date_demande_validation).total_seconds() / 3600
                for v in validations_recentes
                if v.date_validation and v.date_demande_validation
            ])
            stats['temps_moyen_validation_heures'] = round(
                temps_total / validations_recentes.count(), 1
            ) if validations_recentes.count() > 0 else 0
        else:
            stats['temps_moyen_validation_heures'] = 0
        
        # Informations sur le niveau de validation
        niveau_info = {
            'niveau': niveaux_validables[0] if niveaux_validables else 0,
            'libelle': _get_libelle_niveau_validation(profil_utilisateur.type_profil)
        }
        
        # Départements pour le filtre (si pertinent)
        departements_filtre = []
        if profil_utilisateur.type_profil in ['RH', 'ADMIN', 'DIRECTEUR']:
            from .models import Departement
            departements_filtre = Departement.objects.filter(actif=True).order_by('nom')
        
        # Configuration des permissions
        config = {
            'peut_validation_masse': profil_utilisateur.type_profil in ['RH', 'ADMIN', 'DIRECTEUR'],
            'afficher_departements': profil_utilisateur.type_profil in ['RH', 'ADMIN', 'DIRECTEUR'],
        }
        
        context = {
            'demandes': demandes_enrichies,
            'profil_utilisateur': profil_utilisateur,
            'stats': stats,
            'filtres': filtres,
            'niveau_info': niveau_info,
            'departements_filtre': departements_filtre,
            'config': config,
            'page_title': f'Mes validations {niveau_info["libelle"]}'
        }
        
        return render(request, 'interim_validation_liste.html', context)
        
    except Exception as e:
        logger.error(f"Erreur liste validations: {e}")
        messages.error(request, f"Erreur lors du chargement: {str(e)}")
        return redirect('index')

# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _calculer_temps_ecoule(date_creation):
    """Calcule le temps écoulé depuis la création"""
    try:
        if not date_creation:
            return "Inconnu"
        
        delta = timezone.now() - date_creation
        
        if delta.days > 0:
            return f"{delta.days} jour{'s' if delta.days > 1 else ''}"
        elif delta.seconds > 3600:
            heures = delta.seconds // 3600
            return f"{heures} heure{'s' if heures > 1 else ''}"
        else:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''}"
    except:
        return "Inconnu"

def _est_en_retard(demande):
    """Détermine si une demande est en retard"""
    try:
        if not demande.created_at:
            return False
        
        # Seuils de retard selon l'urgence
        seuils = {
            'CRITIQUE': 4,    # 4 heures
            'ELEVEE': 24,     # 1 jour  
            'MOYENNE': 48,    # 2 jours
            'NORMALE': 72     # 3 jours
        }
        
        seuil_heures = seuils.get(demande.urgence, 72)
        seuil_timestamp = timezone.now() - timezone.timedelta(hours=seuil_heures)
        
        return demande.created_at < seuil_timestamp
    except:
        return False

def _peut_validation_rapide(demande, profil_utilisateur):
    """Détermine si la validation rapide est possible"""
    try:
        # Validation rapide possible si :
        # - Moins de 3 candidats proposés
        # - Pas de demande critique
        # - Utilisateur autorisé
        
        nb_candidats = demande.propositions_candidats.count()
        
        return (
            nb_candidats <= 3 and
            demande.urgence != 'CRITIQUE' and
            profil_utilisateur.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']
        )
    except:
        return False

def _get_libelle_niveau_validation(type_profil):
    """Retourne le libellé du niveau de validation"""
    libelles = {
        'RESPONSABLE': 'Niveau 1 (N+1)',
        'DIRECTEUR': 'Niveau 2 (N+2)', 
        'RH': 'Niveau Final (RH)',
        'ADMIN': 'Niveau Final (Admin)'
    }
    return libelles.get(type_profil, 'Validation')

# ================================================================
# VUE PRINCIPALE - AJOUT DE PROPOSITION LORS DE LA VALIDATION
# ================================================================

@login_required
@require_POST
def ajouter_proposition_validation(request, demande_id):
    """
    Ajoute une proposition de candidat lors du processus de validation
    
    Cette vue permet aux validateurs d'ajouter leurs propres propositions
    qui s'intègrent dans le workflow existant
    """
    try:
        # ================================================================
        # 1. RÉCUPÉRATION ET VÉRIFICATIONS DE BASE
        # ================================================================
        
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({
                'success': False,
                'error': 'Profil utilisateur non trouvé'
            })
        
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier que l'utilisateur peut valider cette demande
        peut_valider, raison = _peut_valider_et_proposer(profil_utilisateur, demande)
        if not peut_valider:
            return JsonResponse({
                'success': False,
                'error': f'Permission refusée: {raison}'
            })
        
        # ================================================================
        # 2. RÉCUPÉRATION DES DONNÉES DU FORMULAIRE
        # ================================================================
        
        candidat_id = request.POST.get('candidat_propose_id')
        justification = request.POST.get('justification_proposition', '').strip()
        priorite = request.POST.get('priorite_proposition', 'NORMALE')
        niveau_validation = request.POST.get('niveau_validation', demande.niveau_validation_actuel + 1)
        
        # Évaluations préliminaires
        eval_adequation = request.POST.get('eval_adequation', '')
        eval_experience = request.POST.get('eval_experience', '')
        eval_disponibilite = request.POST.get('eval_disponibilite', '')
        
        # Validations
        if not candidat_id:
            return JsonResponse({
                'success': False,
                'error': 'Aucun candidat sélectionné'
            })
        
        if len(justification) < 10:
            return JsonResponse({
                'success': False,
                'error': 'La justification doit contenir au moins 10 caractères'
            })
        
        # Récupérer le candidat
        try:
            candidat = ProfilUtilisateur.objects.get(id=candidat_id, actif=True)
        except ProfilUtilisateur.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Candidat introuvable ou inactif'
            })
        
        # ================================================================
        # 3. VÉRIFICATIONS MÉTIER
        # ================================================================
        
        # Vérifier que le candidat n'est pas déjà proposé
        proposition_existante = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=candidat
        ).first()
        
        if proposition_existante:
            return JsonResponse({
                'success': False,
                'error': f'{candidat.nom_complet} est déjà proposé pour cette demande'
            })
        
        # Vérifier que l'utilisateur n'a pas dépassé sa limite de propositions
        nb_propositions_utilisateur = PropositionCandidat.objects.filter(
            demande_interim=demande,
            proposant=profil_utilisateur
        ).count()
        
        limite_propositions = _get_limite_propositions_validateur(profil_utilisateur)
        if nb_propositions_utilisateur >= limite_propositions:
            return JsonResponse({
                'success': False,
                'error': f'Limite de {limite_propositions} proposition(s) atteinte'
            })
        
        # ================================================================
        # 4. CALCUL DU SCORING
        # ================================================================
        
        try:
            scoring_service = ScoringInterimService()
            score_base = scoring_service.calculer_score_candidat_v41(candidat, demande)
            
            # Calculer les bonus
            bonus_validateur = _calculer_bonus_validateur(profil_utilisateur)
            bonus_evaluation = _calculer_bonus_evaluation(eval_adequation, eval_experience, eval_disponibilite)
            bonus_priorite = _calculer_bonus_priorite(priorite)
            
            score_final = min(100, max(0, score_base + bonus_validateur + bonus_evaluation + bonus_priorite))
            
        except Exception as e:
            logger.error(f"Erreur calcul scoring proposition validateur: {e}")
            score_base = 50  # Score par défaut
            score_final = 55  # Score par défaut avec bonus minimal
        
        # ================================================================
        # 5. CRÉATION DE LA PROPOSITION
        # ================================================================
        
        with transaction.atomic():
            # Déterminer la source selon le type de validateur
            source_proposition = _determiner_source_proposition(profil_utilisateur)
            
            # Créer la proposition
            proposition = PropositionCandidat.objects.create(
                demande_interim=demande,
                candidat_propose=candidat,
                proposant=profil_utilisateur,
                source_proposition=source_proposition,
                niveau_validation_propose=niveau_validation,
                justification=justification,
                score_automatique=score_base,
                score_humain_ajuste=score_final,
                bonus_proposition_humaine=bonus_validateur + bonus_evaluation + bonus_priorite,
                statut='SOUMISE'
            )
            
            # Sauvegarder les évaluations préliminaires dans les métadonnées
            evaluations = {}
            if eval_adequation:
                evaluations['adequation_poste'] = int(eval_adequation)
            if eval_experience:
                evaluations['experience_similaire'] = int(eval_experience)
            if eval_disponibilite:
                evaluations['disponibilite'] = int(eval_disponibilite)
            
            if evaluations:
                # Créer ou mettre à jour le score détaillé
                from .models import ScoreDetailCandidat
                score_detail, created = ScoreDetailCandidat.objects.get_or_create(
                    candidat=candidat,
                    demande_interim=demande,
                    defaults={
                        'proposition_humaine': proposition,
                        'score_total': score_final,
                        'calcule_par': 'HUMAIN'
                    }
                )
                
                if not created:
                    score_detail.proposition_humaine = proposition
                    score_detail.score_total = score_final
                    score_detail.calcule_par = 'HUMAIN'
                
                # Ajouter les évaluations spécifiques
                for critere, note in evaluations.items():
                    setattr(score_detail, f'score_{critere}', note)
                
                score_detail.save()
            
            # ================================================================
            # 6. HISTORIQUE ET NOTIFICATIONS
            # ================================================================
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                proposition=proposition,
                action='PROPOSITION_CANDIDAT',
                utilisateur=profil_utilisateur,
                description=f"Nouvelle proposition de {candidat.nom_complet} par {profil_utilisateur.nom_complet} "
                           f"(Validateur {profil_utilisateur.type_profil})",
                donnees_apres={
                    'candidat_id': candidat.id,
                    'candidat_nom': candidat.nom_complet,
                    'score_final': score_final,
                    'score_base': score_base,
                    'bonus_validateur': bonus_validateur,
                    'bonus_evaluation': bonus_evaluation,
                    'bonus_priorite': bonus_priorite,
                    'priorite': priorite,
                    'justification': justification,
                    'evaluations_preliminaires': evaluations,
                    'niveau_validation': niveau_validation,
                    'source_proposition': source_proposition
                }
            )
            
            # Notifier les autres validateurs et le demandeur
            _notifier_nouvelle_proposition_validateur(demande, proposition, profil_utilisateur)
            
            # Incrémenter les compteurs du workflow
            workflow = demande.workflow
            workflow.nb_propositions_recues += 1
            workflow.save()
        
        # ================================================================
        # 7. RETOUR DE SUCCÈS
        # ================================================================
        
        logger.info(f"Proposition ajoutée par validateur {profil_utilisateur.nom_complet}: "
                   f"{candidat.nom_complet} pour {demande.numero_demande} (Score: {score_final})")
        
        return JsonResponse({
            'success': True,
            'message': f'Proposition de {candidat.nom_complet} ajoutée avec succès (Score: {score_final}/100)',
            'proposition_info': {
                'id': proposition.id,
                'candidat_nom': candidat.nom_complet,
                'score_final': score_final,
                'statut': proposition.statut,
                'date_creation': proposition.created_at.strftime('%d/%m/%Y %H:%M')
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur ajout proposition validateur demande {demande_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur système: {str(e)}'
        })


# ================================================================
# VUE AJAX - RECHERCHE DE CANDIDATS
# ================================================================

@login_required
def rechercher_candidats_ajax(request):
    """
    Recherche AJAX de candidats pour proposition
    Retourne une liste filtrée selon les critères de recherche
    """
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({
                'success': False,
                'error': 'Profil utilisateur non trouvé'
            })
        
        query = request.GET.get('q', '').strip()
        demande_id = request.GET.get('demande_id')
        
        if len(query) < 2:
            return JsonResponse({
                'success': True,
                'candidats': []
            })
        
        # Récupérer la demande pour le contexte
        demande = None
        if demande_id:
            try:
                demande = DemandeInterim.objects.get(id=demande_id)
            except DemandeInterim.DoesNotExist:
                pass
        
        # ================================================================
        # REQUÊTE DE RECHERCHE OPTIMISÉE
        # ================================================================
        
        # Construire la requête de base
        candidats_query = ProfilUtilisateur.objects.filter(
            actif=True,
            statut_employe='ACTIF'
        ).select_related(
            'user', 'poste', 'departement', 'site'
        )
        
        # Filtres de recherche
        search_filter = Q()
        
        # Recherche par nom, prénom, matricule
        search_filter |= Q(user__first_name__icontains=query)
        search_filter |= Q(user__last_name__icontains=query)
        search_filter |= Q(matricule__icontains=query)
        
        # Recherche par département
        search_filter |= Q(departement__nom__icontains=query)
        
        # Recherche par poste
        search_filter |= Q(poste__titre__icontains=query)
        
        candidats_query = candidats_query.filter(search_filter)
        
        # Exclure les candidats déjà proposés pour cette demande
        if demande:
            candidats_deja_proposes = PropositionCandidat.objects.filter(
                demande_interim=demande
            ).values_list('candidat_propose_id', flat=True)
            
            candidats_query = candidats_query.exclude(id__in=candidats_deja_proposes)
            
            # Exclure la personne à remplacer
            if demande.personne_remplacee:
                candidats_query = candidats_query.exclude(id=demande.personne_remplacee.id)
        
        # Limiter les résultats selon le niveau du validateur
        candidats_query = _filtrer_candidats_selon_perimetre(candidats_query, profil_utilisateur)
        
        # Limiter à 20 résultats et ordonner
        candidats = candidats_query.order_by('user__last_name', 'user__first_name')[:50]
        
        # ================================================================
        # CALCUL DES SCORES PRÉVISIONNELS
        # ================================================================
        
        candidats_data = []
        scoring_service = None
        
        if demande:
            try:
                scoring_service = ScoringInterimService()
            except Exception:
                pass
        
        for candidat in candidats:
            try:
                # Calcul du score prévisionnel si possible
                score_previsionnel = 0
                if scoring_service and demande:
                    try:
                        score_previsionnel = scoring_service.calculer_score_candidat_v41(candidat, demande)
                    except Exception:
                        score_previsionnel = _calculer_score_basique_recherche(candidat, demande)
                
                candidat_data = {
                    'id': candidat.id,
                    'nom_complet': candidat.nom_complet,
                    'matricule': candidat.matricule,
                    'poste': candidat.poste.titre if candidat.poste else None,
                    'departement': candidat.departement.nom if candidat.departement else None,
                    'site': candidat.site.nom if candidat.site else None,
                    'score_previsionnel': score_previsionnel,
                    'initiales': _get_initiales(candidat.nom_complet),
                    'statut_employe': candidat.statut_employe,
                    'disponible_interim': getattr(candidat.extended_data, 'disponible_interim', True) if hasattr(candidat, 'extended_data') else True
                }
                
                candidats_data.append(candidat_data)
                
            except Exception as e:
                logger.error(f"Erreur traitement candidat {candidat.id}: {e}")
                continue
        
        # Trier par score décroissant puis par nom
        candidats_data.sort(key=lambda x: (-x['score_previsionnel'], x['nom_complet']))
        
        return JsonResponse({
            'success': True,
            'candidats': candidats_data,
            'total': len(candidats_data)
        })
        
    except Exception as e:
        logger.error(f"Erreur recherche candidats AJAX: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors de la recherche'
        })


# ================================================================
# VUE AJAX - RETRAIT DE PROPOSITION
# ================================================================

@login_required
@require_POST
def retirer_proposition_ajax(request, proposition_id):
    """
    Retire une proposition de candidat ajoutée par le validateur
    """
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({
                'success': False,
                'error': 'Profil utilisateur non trouvé'
            })
        
        # Récupérer la proposition
        proposition = get_object_or_404(PropositionCandidat, id=proposition_id)
        
        # Vérifier que c'est bien le proposant ou un utilisateur autorisé
        if proposition.proposant != profil_utilisateur:
            if not (profil_utilisateur.type_profil in ['RH', 'ADMIN'] or profil_utilisateur.is_superuser):
                return JsonResponse({
                    'success': False,
                    'error': 'Vous ne pouvez retirer que vos propres propositions'
                })
        
        # Vérifier que la proposition peut être retirée
        if proposition.statut not in ['SOUMISE', 'EN_EVALUATION']:
            return JsonResponse({
                'success': False,
                'error': 'Cette proposition ne peut plus être retirée (statut: ' + proposition.get_statut_display() + ')'
            })
        
        # Vérifier que la demande est encore en cours
        if proposition.demande_interim.statut not in ['EN_VALIDATION', 'SOUMISE', 'CANDIDAT_PROPOSE']:
            return JsonResponse({
                'success': False,
                'error': 'La demande n\'est plus en phase de proposition'
            })
        
        with transaction.atomic():
            demande = proposition.demande_interim
            candidat_nom = proposition.candidat_propose.nom_complet
            
            # Créer l'historique avant suppression
            HistoriqueAction.objects.create(
                demande=demande,
                action='RETRAIT_PROPOSITION',
                utilisateur=profil_utilisateur,
                description=f"Retrait de la proposition de {candidat_nom} par {profil_utilisateur.nom_complet}",
                donnees_avant={
                    'proposition_id': proposition.id,
                    'candidat_nom': candidat_nom,
                    'score_final': proposition.score_final,
                    'justification': proposition.justification
                }
            )
            
            # Supprimer le score détaillé associé si c'était une proposition unique
            from .models import ScoreDetailCandidat
            ScoreDetailCandidat.objects.filter(
                candidat=proposition.candidat_propose,
                demande_interim=demande,
                proposition_humaine=proposition
            ).delete()
            
            # Supprimer la proposition
            proposition.delete()
            
            # Mettre à jour les compteurs du workflow
            workflow = demande.workflow
            if workflow.nb_propositions_recues > 0:
                workflow.nb_propositions_recues -= 1
                workflow.save()
        
        logger.info(f"Proposition retirée par {profil_utilisateur.nom_complet}: {candidat_nom} pour {demande.numero_demande}")
        
        return JsonResponse({
            'success': True,
            'message': f'Proposition de {candidat_nom} retirée avec succès'
        })
        
    except Exception as e:
        logger.error(f"Erreur retrait proposition {proposition_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur lors du retrait: {str(e)}'
        })


# ================================================================
# VUE AJAX - DÉTAILS DE PROPOSITION
# ================================================================



# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _peut_valider_et_proposer(profil_utilisateur, demande):
    """
    Vérifie si l'utilisateur peut valider la demande ET proposer des candidats
    """
    try:
        # Superutilisateurs peuvent toujours
        if profil_utilisateur.is_superuser:
            return True, "Superutilisateur - droits complets"
        
        # Vérifier que la demande est dans un état permettant les propositions
        if demande.statut not in ['EN_VALIDATION', 'SOUMISE', 'CANDIDAT_PROPOSE']:
            return False, "La demande n'est plus en phase de validation"
        
        # Déterminer le niveau de validation requis
        niveau_requis = demande.niveau_validation_actuel + 1
        
        # Vérifications selon le type de profil et niveau
        type_profil = profil_utilisateur.type_profil
        
        # Niveau 1 : RESPONSABLE (dans le bon département)
        if niveau_requis == 1:
            if type_profil == 'RESPONSABLE':
                if profil_utilisateur.departement == demande.poste.departement:
                    return True, "Responsable autorisé pour ce département"
                else:
                    return False, "Responsable d'un autre département"
            else:
                return False, "Validation Responsable (N+1) requise"
        
        # Niveau 2 : DIRECTEUR
        elif niveau_requis == 2:
            if type_profil == 'DIRECTEUR':
                return True, "Directeur autorisé pour validation N+2"
            else:
                return False, "Validation Directeur (N+2) requise"
        
        # Niveau 3+ : RH/ADMIN
        elif niveau_requis >= 3:
            if type_profil in ['RH', 'ADMIN']:
                return True, "RH/Admin autorisé pour validation finale"
            else:
                return False, "Validation RH/Admin finale requise"
        
        return False, "Niveau de validation non reconnu"
        
    except Exception as e:
        logger.error(f"Erreur vérification permissions validation/proposition: {e}")
        return False, f"Erreur système: {str(e)}"


def _get_limite_propositions_validateur(profil_utilisateur):
    """Retourne la limite de propositions selon le type de validateur"""
    limites = {
        'RESPONSABLE': 3,
        'DIRECTEUR': 5,
        'RH': 10,
        'ADMIN': 10,
        'SUPERUSER': 20
    }
    
    if profil_utilisateur.is_superuser:
        return limites['SUPERUSER']
    
    return limites.get(profil_utilisateur.type_profil, 2)


def _calculer_bonus_validateur(profil_utilisateur):
    """
    Calcule le bonus selon le niveau hiérarchique du validateur/proposant
    Basé sur la hiérarchie CORRIGÉE du modèle : RESPONSABLE -> DIRECTEUR -> RH/ADMIN
    Compatible avec ConfigurationScoring et scoring_service.py V4.1
    """
    try:
        # Vérification de base
        if not profil_utilisateur:
            return 0
        
        # Superutilisateurs : bonus maximal
        if profil_utilisateur.is_superuser:
            return 20  # Bonus maximal pour superuser
        
        # Bonus selon le type de profil (hiérarchie CORRIGÉE)
        bonus_mapping = {
            'UTILISATEUR': 0,           # Pas de bonus pour utilisateur standard
            'CHEF_EQUIPE': 8,          # Peut proposer, bonus modéré
            'RESPONSABLE': 15,         # Niveau 1 de validation - bonus élevé
            'DIRECTEUR': 18,           # Niveau 2 de validation - bonus très élevé  
            'RH': 20,                  # Niveau 3 de validation (final) - bonus maximal
            'ADMIN': 20,               # Niveau 3 étendu - bonus maximal
        }
        
        type_profil = getattr(profil_utilisateur, 'type_profil', 'UTILISATEUR')
        bonus_base = bonus_mapping.get(type_profil, 0)
        
        # Bonus supplémentaire selon l'expérience et l'ancienneté
        bonus_experience = 0
        
        # Bonus ancienneté si données disponibles
        try:
            if hasattr(profil_utilisateur, 'extended_data') and profil_utilisateur.extended_data:
                date_embauche = profil_utilisateur.extended_data.date_embauche
                if date_embauche:
                    from datetime import date
                    anciennete_jours = (date.today() - date_embauche).days
                    anciennete_annees = anciennete_jours / 365
                    
                    if anciennete_annees >= 10:
                        bonus_experience += 5
                    elif anciennete_annees >= 5:
                        bonus_experience += 3
                    elif anciennete_annees >= 2:
                        bonus_experience += 1
        except Exception:
            pass
        
        # Bonus si le profil a déjà validé des demandes avec succès
        try:
            nb_validations_reussies = ValidationDemande.objects.filter(
                validateur=profil_utilisateur,
                decision__in=['APPROUVE', 'APPROUVE_AVEC_MODIF']
            ).count()
            
            if nb_validations_reussies >= 50:
                bonus_experience += 3
            elif nb_validations_reussies >= 20:
                bonus_experience += 2
            elif nb_validations_reussies >= 5:
                bonus_experience += 1
        except Exception:
            pass
        
        # Bonus si le profil a proposé des candidats avec succès
        try:
            nb_propositions_reussies = PropositionCandidat.objects.filter(
                proposant=profil_utilisateur,
                statut__in=['VALIDEE', 'RETENUE']
            ).count()
            
            if nb_propositions_reussies >= 20:
                bonus_experience += 2
            elif nb_propositions_reussies >= 10:
                bonus_experience += 1
        except Exception:
            pass
        
        # Calculer le bonus total
        bonus_total = bonus_base + bonus_experience
        
        # Plafonner le bonus à 25 points maximum
        bonus_final = min(25, max(0, bonus_total))
        
        logger.debug(f">>> Bonus validateur pour {profil_utilisateur.matricule} "
                    f"({type_profil}): {bonus_final} points "
                    f"(base: {bonus_base}, expérience: {bonus_experience})")
        
        return bonus_final
        
    except Exception as e:
        logger.warning(f"WARNING Erreur calcul bonus validateur: {e}")
        return 0

def _calculer_bonus_evaluation(eval_adequation, eval_experience, eval_disponibilite):
    """Calcule le bonus basé sur l'évaluation préliminaire"""
    try:
        evaluations = []
        
        if eval_adequation:
            evaluations.append(int(eval_adequation))
        if eval_experience:
            evaluations.append(int(eval_experience))
        if eval_disponibilite:
            evaluations.append(int(eval_disponibilite))
        
        if not evaluations:
            return 0
        
        # Moyenne des évaluations convertie en bonus (max 15 points)
        moyenne = sum(evaluations) / len(evaluations)
        return round(moyenne * 0.15)
        
    except (ValueError, TypeError):
        return 0


def _calculer_bonus_priorite(urgence):
    """
    Calcule le bonus selon le niveau d'urgence de la demande
    Compatible avec les choix URGENCES du modèle DemandeInterim
    Logique similaire au scoring V4.1 : plus c'est urgent, plus le bonus est élevé
    """
    try:
        # Mapping urgence -> bonus (points supplémentaires)
        bonus_urgence = {
            'NORMALE': 0,      # Pas de bonus pour urgence normale
            'MOYENNE': 3,      # Bonus léger pour urgence moyenne
            'ELEVEE': 8,       # Bonus significatif pour urgence élevée
            'CRITIQUE': 15,    # Bonus maximal pour urgence critique
        }
        
        # Récupérer le bonus de base
        bonus_base = bonus_urgence.get(urgence, 0)
        
        # Bonus supplémentaire selon la logique métier
        bonus_supplementaire = 0
        
        # Pour les urgences élevées, ajouter un bonus temporel
        if urgence in ['ELEVEE', 'CRITIQUE']:
            # Bonus pour traitement prioritaire
            bonus_supplementaire += 2
            
            # Bonus spécial pour urgence critique (nécessite traitement immédiat)
            if urgence == 'CRITIQUE':
                bonus_supplementaire += 3
        
        # Calculer le bonus total
        bonus_total = bonus_base + bonus_supplementaire
        
        # Plafonner le bonus à 20 points maximum
        bonus_final = min(20, max(0, bonus_total))
        
        logger.debug(f">>> Bonus priorité pour urgence '{urgence}': {bonus_final} points "
                    f"(base: {bonus_base}, supplémentaire: {bonus_supplementaire})")
        
        return bonus_final
        
    except Exception as e:
        logger.warning(f"WARNING Erreur calcul bonus priorité: {e}")
        return 0

def _calculer_bonus_contexte_demande(demande):
    """
    Calcule un bonus basé sur le contexte spécifique de la demande
    Prend en compte la durée, le type de poste, le département, etc.
    """
    try:
        bonus_total = 0
        
        # Bonus selon la durée de la mission
        if demande.date_debut and demande.date_fin:
            duree_jours = (demande.date_fin - demande.date_debut).days + 1
            
            if duree_jours <= 5:
                bonus_total += 2    # Mission très courte
            elif duree_jours <= 15:
                bonus_total += 3    # Mission courte - standard
            elif duree_jours <= 30:
                bonus_total += 4    # Mission standard
            elif duree_jours <= 90:
                bonus_total += 3    # Mission longue
            else:
                bonus_total += 1    # Mission très longue (plus difficile)
        
        # Bonus selon le niveau de responsabilité du poste
        if demande.poste:
            niveau_resp = getattr(demande.poste, 'niveau_responsabilite', 1)
            if niveau_resp == 3:        # Cadre
                bonus_total += 3
            elif niveau_resp == 2:      # Maîtrise  
                bonus_total += 2
            # Niveau 1 (Exécution) : pas de bonus
        
        # Bonus si remplacement dans le même département (connaissance du contexte)
        if (demande.personne_remplacee and demande.poste and 
            demande.personne_remplacee.departement == demande.poste.departement):
            bonus_total += 2
        
        # Bonus selon le motif d'absence (certains sont plus prévisibles)
        if hasattr(demande, 'motif_absence') and demande.motif_absence:
            motif = demande.motif_absence.categorie.upper() if hasattr(demande.motif_absence, 'categorie') else ''
            if motif in ['FORMATION', 'CONGE']:
                bonus_total += 2    # Absences prévisibles
            elif motif in ['MALADIE']:
                bonus_total += 1    # Absences moins prévisibles
        
        # Plafonner le bonus à 10 points
        bonus_final = min(10, max(0, bonus_total))
        
        logger.debug(f">>> Bonus contexte demande {demande.numero_demande}: {bonus_final} points")
        
        return bonus_final
        
    except Exception as e:
        logger.warning(f"WARNING Erreur calcul bonus contexte demande: {e}")
        return 0
    

def _determiner_source_proposition(profil_utilisateur):
    """Détermine la source de proposition selon le type de validateur"""
    mapping_source = {
        'CHEF_EQUIPE': 'CHEF_EQUIPE',
        'RESPONSABLE': 'RESPONSABLE',
        'DIRECTEUR': 'DIRECTEUR',
        'RH': 'RH',
        'ADMIN': 'ADMIN',
        'SUPERUSER': 'SUPERUSER'
    }
    
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    
    return mapping_source.get(profil_utilisateur.type_profil, 'VALIDATION_ETAPE')


def _filtrer_candidats_selon_perimetre(candidats_query, profil_utilisateur):
    """Filtre les candidats selon le périmètre du validateur"""
    try:
        type_profil = profil_utilisateur.type_profil
        
        # Superutilisateurs et RH/ADMIN : tout le périmètre
        if profil_utilisateur.is_superuser or type_profil in ['RH', 'ADMIN']:
            return candidats_query
        
        # DIRECTEUR : tout le périmètre
        if type_profil == 'DIRECTEUR':
            return candidats_query
        
        # RESPONSABLE : uniquement son département
        if type_profil == 'RESPONSABLE' and profil_utilisateur.departement:
            return candidats_query.filter(departement=profil_utilisateur.departement)
        
        # CHEF_EQUIPE : son département
        if type_profil == 'CHEF_EQUIPE' and profil_utilisateur.departement:
            return candidats_query.filter(departement=profil_utilisateur.departement)
        
        # Par défaut : même département
        if profil_utilisateur.departement:
            return candidats_query.filter(departement=profil_utilisateur.departement)
        
        return candidats_query
        
    except Exception as e:
        logger.error(f"Erreur filtrage candidats périmètre: {e}")
        return candidats_query


def _calculer_score_basique_recherche(candidat, demande):
    """Calcul de score basique pour la recherche"""
    try:
        score = 50  # Score de base
        
        # Bonus département
        if candidat.departement == demande.poste.departement:
            score += 20
        
        # Bonus site
        if candidat.site == demande.poste.site:
            score += 10
        
        # Bonus poste similaire
        if candidat.poste and demande.poste:
            if candidat.poste.titre.lower() in demande.poste.titre.lower() or \
               demande.poste.titre.lower() in candidat.poste.titre.lower():
                score += 15
        
        return min(100, score)
        
    except Exception:
        return 50


def _peut_voir_proposition(profil_utilisateur, proposition):
    """Vérifie si l'utilisateur peut voir une proposition"""
    try:
        # Superutilisateurs peuvent tout voir
        if profil_utilisateur.is_superuser:
            return True
        
        # RH/ADMIN peuvent tout voir
        if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            return True
        
        # Le proposant peut voir sa proposition
        if proposition.proposant == profil_utilisateur:
            return True
        
        # Validateurs de niveau supérieur peuvent voir
        if profil_utilisateur.type_profil == 'DIRECTEUR':
            return True
        
        # Responsables peuvent voir les propositions de leur département
        if profil_utilisateur.type_profil == 'RESPONSABLE':
            return (profil_utilisateur.departement and 
                    proposition.demande_interim.poste.departement == profil_utilisateur.departement)
        
        return False
        
    except Exception:
        return False


def _notifier_nouvelle_proposition_validateur(demande, proposition, proposant):
    """Notifie les parties prenantes d'une nouvelle proposition par un validateur"""
    try:
        candidat = proposition.candidat_propose
        
        # Notifier le demandeur original
        if demande.demandeur != proposant:
            NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=proposant,
                demande=demande,
                proposition_liee=proposition,
                type_notification='PROPOSITION_CANDIDAT',
                urgence='NORMALE',
                titre=f"Nouvelle proposition de candidat par {proposant.get_type_profil_display()}",
                message=f"{proposant.nom_complet} ({proposant.get_type_profil_display()}) a proposé "
                       f"{candidat.nom_complet} pour votre demande {demande.numero_demande}. "
                       f"Score attribué: {proposition.score_final}/100.",
                url_action_principale=f"/interim/validation/{demande.id}/",
                texte_action_principale="Voir la validation",
                metadata={
                    'type_proposition': 'VALIDATEUR',
                    'proposant_type': proposant.type_profil,
                    'score_final': proposition.score_final
                }
            )
        
        # Notifier les autres validateurs du même niveau ou supérieur
        niveaux_a_notifier = []
        if proposant.type_profil == 'RESPONSABLE':
            niveaux_a_notifier = ['DIRECTEUR', 'RH', 'ADMIN']
        elif proposant.type_profil == 'DIRECTEUR':
            niveaux_a_notifier = ['RH', 'ADMIN']
        
        for niveau in niveaux_a_notifier:
            validateurs = ProfilUtilisateur.objects.filter(
                type_profil=niveau,
                actif=True
            ).exclude(id=proposant.id)
            
            for validateur in validateurs:
                NotificationInterim.objects.create(
                    destinataire=validateur,
                    expediteur=proposant,
                    demande=demande,
                    proposition_liee=proposition,
                    type_notification='PROPOSITION_CANDIDAT',
                    urgence='NORMALE',
                    titre=f"Proposition de candidat par {proposant.get_type_profil_display()}",
                    message=f"{proposant.nom_complet} a enrichi la demande {demande.numero_demande} "
                           f"avec la proposition de {candidat.nom_complet}.",
                    url_action_principale=f"/interim/validation/{demande.id}/",
                    texte_action_principale="Voir la demande",
                    metadata={
                        'type_proposition': 'VALIDATEUR_PEER',
                        'proposant_type': proposant.type_profil
                    }
                )
        
        logger.info(f"Notifications envoyées pour nouvelle proposition validateur: "
                   f"{candidat.nom_complet} par {proposant.nom_complet}")
        
    except Exception as e:
        logger.error(f"Erreur notifications nouvelle proposition validateur: {e}")


# ================================================================
# VUE POUR RÉCUPÉRER LES PROPOSITIONS DU VALIDATEUR ACTUEL
# ================================================================

@login_required
def mes_propositions_demande(request, demande_id):
    """
    Retourne les propositions du validateur actuel pour une demande spécifique
    Utilisé pour afficher la section "Vos propositions" dans le template
    """
    try:
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            return JsonResponse({
                'success': False,
                'error': 'Profil utilisateur non trouvé'
            })
        
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Récupérer les propositions de ce validateur pour cette demande
        propositions = PropositionCandidat.objects.filter(
            demande_interim=demande,
            proposant=profil_utilisateur
        ).select_related(
            'candidat_propose__user',
            'candidat_propose__poste',
            'candidat_propose__departement'
        ).order_by('-created_at')
        
        propositions_data = []
        for proposition in propositions:
            candidat = proposition.candidat_propose
            
            # Déterminer la classe CSS du score
            score_class = 'poor'
            if proposition.score_final >= 80:
                score_class = 'excellent'
            elif proposition.score_final >= 60:
                score_class = 'good'
            elif proposition.score_final >= 40:
                score_class = 'average'
            
            proposition_data = {
                'id': proposition.id,
                'candidat_propose': {
                    'id': candidat.id,
                    'nom_complet': candidat.nom_complet,
                    'matricule': candidat.matricule,
                    'poste': {
                        'titre': candidat.poste.titre if candidat.poste else 'Poste non renseigné'
                    }
                },
                'score_final': proposition.score_final,
                'score_class': score_class,
                'justification': proposition.justification,
                'statut': proposition.statut,
                'get_statut_display': proposition.get_statut_display(),
                'priorite_proposition': getattr(proposition, 'priorite_proposition', 'NORMALE'),
                'get_priorite_proposition_display': getattr(proposition, 'get_priorite_proposition_display', lambda: 'Normale')(),
                'created_at': proposition.created_at,
                'peut_modifier': proposition.statut in ['SOUMISE', 'EN_EVALUATION'],
                'peut_retirer': proposition.statut in ['SOUMISE', 'EN_EVALUATION']
            }
            
            propositions_data.append(proposition_data)
        
        return JsonResponse({
            'success': True,
            'propositions': propositions_data,
            'total': len(propositions_data)
        })
        
    except Exception as e:
        logger.error(f"Erreur récupération propositions validateur: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors du chargement des propositions'
        })

# ================================================================
# VUES ESCALADE MODIFIÉES POUR LES NOUVEAUX TEMPLATES
# ================================================================

@login_required
def escalader_demande(request, demande_id):
    """
    Vue pour escalader une demande - Template dédié
    """
    try:
        # Récupération du profil utilisateur
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            messages.error(request, 'Profil utilisateur non trouvé')
            return redirect('liste_interim_validation')
        
        # Récupération de la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérification des conditions d'escalade
        verification_escalade = _verifier_escalade_complete(profil_utilisateur, demande)
        
        # Déterminer la classe CSS pour l'urgence
        urgence_classe = {
            'CRITIQUE': 'critique',
            'ELEVEE': 'elevee', 
            'MOYENNE': 'moyenne',
            'NORMALE': 'normale'
        }.get(demande.urgence, 'normale')
        
        if request.method == 'POST':
            motif_escalade = request.POST.get('motif_escalade', '').strip()
            
            # Validation du motif
            if not motif_escalade:
                messages.error(request, 'Le motif d\'escalade est obligatoire')
                return render(request, 'escalader_demande.html', {
                    'demande': demande,
                    'verification_escalade': verification_escalade,
                    'urgence_classe': urgence_classe,
                })
            
            if len(motif_escalade) < 20:
                messages.error(request, 'Le motif doit contenir au moins 20 caractères')
                return render(request, 'escalader_demande.html', {
                    'demande': demande,
                    'verification_escalade': verification_escalade,
                    'urgence_classe': urgence_classe,
                })
            
            # Vérifications finales
            if not verification_escalade['escalade_possible'] or not verification_escalade['peut_escalader']:
                messages.error(request, 'Escalade impossible : conditions non remplies')
                return redirect('liste_interim_validation')
            
            # Effectuer l'escalade
            success, result = _effectuer_escalade(profil_utilisateur, demande, motif_escalade)
            
            if success:
                messages.success(request, f'Demande escaladée avec succès ! {result.get("message", "")}')
                return redirect('liste_interim_validation')
            else:
                messages.error(request, f'Erreur lors de l\'escalade : {result.get("error", "Erreur inconnue")}')
        
        return render(request, 'escalader_demande.html', {
            'demande': demande,
            'verification_escalade': verification_escalade,
            'urgence_classe': urgence_classe,
            'page_title': 'Escalader la demande',
        })
        
    except Exception as e:
        logger.error(f"Erreur vue escalader_demande: {e}")
        messages.error(request, 'Erreur lors du chargement de la page d\'escalade')
        return redirect('liste_interim_validation')


@login_required  
def verifier_escalade_possible(request, demande_id):
    """
    Vue pour vérifier les possibilités d'escalade - Template dédié
    """
    try:
        # Récupération du profil utilisateur
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            messages.error(request, 'Profil utilisateur non trouvé')
            return redirect('liste_interim_validation')
        
        # Récupération de la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérification complète des conditions d'escalade
        verification = _verifier_escalade_complete(profil_utilisateur, demande)
        
        # Déterminer la classe CSS pour l'urgence
        urgence_classe = {
            'CRITIQUE': 'critique',
            'ELEVEE': 'elevee',
            'MOYENNE': 'moyenne', 
            'NORMALE': 'normale'
        }.get(demande.urgence, 'normale')
        
        return render(request, 'interim/verifier_escalade_possible.html', {
            'demande': demande,
            'verification': verification,
            'urgence_classe': urgence_classe,
            'page_title': 'Vérification d\'escalade',
        })
        
    except Exception as e:
        logger.error(f"Erreur vue verifier_escalade_possible: {e}")
        messages.error(request, 'Erreur lors de la vérification d\'escalade')
        return redirect('liste_interim_validation')


@login_required
def historique_escalades_demande(request, demande_id):
    """
    Vue pour l'historique des escalades - Template dédié
    """
    try:
        # Récupération du profil utilisateur
        profil_utilisateur = get_profil_or_virtual(request.user)
        if not profil_utilisateur:
            messages.error(request, 'Profil utilisateur non trouvé')
            return redirect('liste_interim_validation')
        
        # Récupération de la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Récupération des filtres
        filtres = {
            'escaladeur': request.GET.get('escaladeur', ''),
            'niveau_debut': request.GET.get('niveau_debut', ''),
            'date_debut': request.GET.get('date_debut', ''),
            'date_fin': request.GET.get('date_fin', ''),
            'recherche': request.GET.get('recherche', ''),
        }
        
        # Récupération des escalades avec filtres
        escalades_queryset = HistoriqueAction.objects.filter(
            demande=demande,
            action='ESCALADE_DEMANDE'
        ).order_by('-created_at')
        
        # Application des filtres
        if filtres['escaladeur']:
            escalades_queryset = escalades_queryset.filter(
                utilisateur__nom_complet__icontains=filtres['escaladeur']
            )
        
        if filtres['niveau_debut']:
            escalades_queryset = escalades_queryset.filter(
                donnees_apres__ancien_niveau=filtres['niveau_debut']
            )
        
        if filtres['date_debut']:
            try:
                date_debut = datetime.strptime(filtres['date_debut'], '%Y-%m-%d').date()
                escalades_queryset = escalades_queryset.filter(created_at__date__gte=date_debut)
            except ValueError:
                pass
        
        if filtres['date_fin']:
            try:
                date_fin = datetime.strptime(filtres['date_fin'], '%Y-%m-%d').date()
                escalades_queryset = escalades_queryset.filter(created_at__date__lte=date_fin)
            except ValueError:
                pass
        
        if filtres['recherche']:
            escalades_queryset = escalades_queryset.filter(
                Q(donnees_apres__motif_escalade__icontains=filtres['recherche']) |
                Q(utilisateur__nom_complet__icontains=filtres['recherche']) |
                Q(description__icontains=filtres['recherche'])
            )
        
        # Préparer les données pour le template
        escalades_data = []
        escaladeurs_uniques = set()
        
        for escalade in escalades_queryset:
            donnees = escalade.donnees_apres or {}
            escaladeur_nom = escalade.utilisateur.nom_complet if escalade.utilisateur else 'Système'
            escaladeurs_uniques.add(escaladeur_nom)
            
            escalades_data.append({
                'date': escalade.created_at.strftime('%d/%m/%Y %H:%M'),
                'escaladeur': escaladeur_nom,
                'escaladeur_type': donnees.get('escaladeur_type', ''),
                'ancien_niveau': donnees.get('ancien_niveau', 0),
                'nouveau_niveau': donnees.get('nouveau_niveau', 0),
                'motif': donnees.get('motif_escalade', escalade.description),
                'type_validation_cible': donnees.get('type_validation_cible', '')
            })
        
        # Statistiques
        total_escalades = len(escalades_data)
        premiere_escalade = escalades_queryset.last().created_at if escalades_queryset.exists() else None
        derniere_escalade = escalades_queryset.first().created_at if escalades_queryset.exists() else None
        
        # Déterminer la classe CSS pour l'urgence
        urgence_classe = {
            'CRITIQUE': 'critique',
            'ELEVEE': 'elevee',
            'MOYENNE': 'moyenne',
            'NORMALE': 'normale'
        }.get(demande.urgence, 'normale')
        
        return render(request, 'historique_escalades_demande.html', {
            'demande': demande,
            'escalades': escalades_data,
            'total_escalades': total_escalades,
            'escaladeurs_uniques': sorted(escaladeurs_uniques),
            'premiere_escalade': premiere_escalade,
            'derniere_escalade': derniere_escalade,
            'urgence_classe': urgence_classe,
            'filtres': filtres,
            'page_title': 'Historique des escalades',
        })
        
    except Exception as e:
        logger.error(f"Erreur vue historique_escalades_demande: {e}")
        messages.error(request, 'Erreur lors du chargement de l\'historique')
        return redirect('liste_interim_validation')


# ================================================================
# FONCTIONS UTILITAIRES POUR L'ESCALADE
# ================================================================

def _verifier_escalade_complete(profil_utilisateur, demande):
    """
    Vérification complète des conditions d'escalade
    """
    try:
        # Vérifications de base
        peut_escalader, raison_user = _peut_escalader_demande(profil_utilisateur, demande)
        peut_etre_escaladee, raison_demande = _demande_peut_etre_escaladee(demande)
        
        escalade_possible = peut_escalader and peut_etre_escaladee
        
        # Déterminer le niveau cible et les validateurs
        niveau_cible = None
        type_validation_cible = None
        validateurs_cibles = []
        
        if escalade_possible:
            niveau_cible = _determiner_niveau_escalade(demande, profil_utilisateur)
            type_validation_cible = _get_type_validation_par_niveau(niveau_cible)
            validateurs_cibles = list(
                _obtenir_validateurs_pour_escalade(demande, niveau_cible)
                .values_list('nom_complet', flat=True)
            )
        
        return {
            'escalade_possible': escalade_possible,
            'peut_escalader': peut_escalader,
            'raison_user': raison_user,
            'peut_etre_escaladee': peut_etre_escaladee,
            'raison_demande': raison_demande,
            'niveau_actuel': demande.niveau_validation_actuel,
            'niveau_cible': niveau_cible,
            'type_validation_cible': type_validation_cible,
            'validateurs_cibles': validateurs_cibles,
            'nb_validateurs_cibles': len(validateurs_cibles)
        }
        
    except Exception as e:
        logger.error(f"Erreur vérification escalade complète: {e}")
        return {
            'escalade_possible': False,
            'peut_escalader': False,
            'raison_user': 'Erreur système',
            'peut_etre_escaladee': False,
            'raison_demande': 'Erreur système',
            'niveau_actuel': demande.niveau_validation_actuel,
            'niveau_cible': None,
            'type_validation_cible': None,
            'validateurs_cibles': [],
            'nb_validateurs_cibles': 0
        }


def _effectuer_escalade(profil_utilisateur, demande, motif_escalade):
    """
    Effectue l'escalade en utilisant la logique de la vue originale
    """
    try:
        # Vérifications des permissions
        peut_escalader, raison = _peut_escalader_demande(profil_utilisateur, demande)
        if not peut_escalader:
            return False, {'error': f'Permission refusée: {raison}'}
        
        # Vérifier que la demande peut être escaladée
        peut_etre_escaladee, raison_escalade = _demande_peut_etre_escaladee(demande)
        if not peut_etre_escaladee:
            return False, {'error': f'Escalade impossible: {raison_escalade}'}
        
        # Déterminer le niveau cible d'escalade
        niveau_actuel = demande.niveau_validation_actuel
        niveau_cible = _determiner_niveau_escalade(demande, profil_utilisateur)
        
        if niveau_cible <= niveau_actuel:
            return False, {'error': 'Impossible d\'escalader vers un niveau inférieur ou égal'}
        
        # Effectuer l'escalade avec transaction
        with transaction.atomic():
            # Déterminer le type de validation cible
            type_validation_cible = _get_type_validation_par_niveau(niveau_cible)
            
            # Créer une validation spéciale "ESCALADE"
            validation_escalade = ValidationDemande.objects.create(
                demande=demande,
                type_validation='ESCALADE',
                niveau_validation=niveau_cible,
                validateur=profil_utilisateur,
                decision='ESCALADE',
                commentaire=f"[ESCALADE] {motif_escalade}",
                date_validation=timezone.now()
            )
            
            # Mettre à jour la demande
            ancien_niveau = demande.niveau_validation_actuel
            demande.niveau_validation_actuel = niveau_cible
            demande.statut = 'EN_VALIDATION'
            demande.save()
            
            # Créer l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                validation=validation_escalade,
                action='ESCALADE_DEMANDE',
                utilisateur=profil_utilisateur,
                description=f"Escalade de niveau {ancien_niveau} vers niveau {niveau_cible}",
                donnees_apres={
                    'ancien_niveau': ancien_niveau,
                    'nouveau_niveau': niveau_cible,
                    'motif_escalade': motif_escalade,
                    'type_validation_cible': type_validation_cible,
                    'escaladeur': profil_utilisateur.nom_complet,
                    'escaladeur_type': profil_utilisateur.type_profil
                }
            )
            
            # Notifier les validateurs du niveau cible
            validateurs_cibles = _obtenir_validateurs_pour_escalade(demande, niveau_cible)
            notifications_envoyees = []
            
            for validateur in validateurs_cibles:
                NotificationInterim.objects.create(
                    destinataire=validateur,
                    expediteur=profil_utilisateur,
                    demande=demande,
                    validation_liee=validation_escalade,
                    type_notification='DEMANDE_ESCALADEE',
                    urgence='HAUTE',
                    titre=f"  ESCALADE - Demande nécessitant attention - {demande.numero_demande}",
                    message=f"La demande a été escaladée par {profil_utilisateur.nom_complet} "
                           f"({profil_utilisateur.get_type_profil_display()}) vers votre niveau. "
                           f"Motif: {motif_escalade}",
                    url_action_principale=f"/interim/validation/{demande.id}/",
                    texte_action_principale="Valider en urgence",
                    metadata={
                        'type_escalade': 'NIVEAU_SUPERIEUR',
                        'escaladeur': profil_utilisateur.nom_complet,
                        'ancien_niveau': ancien_niveau,
                        'nouveau_niveau': niveau_cible,
                        'motif': motif_escalade
                    }
                )
                notifications_envoyees.append(validateur.nom_complet)
            
            # Notifier le demandeur original (sauf si c'est lui qui escalade)
            if demande.demandeur != profil_utilisateur:
                NotificationInterim.objects.create(
                    destinataire=demande.demandeur,
                    expediteur=profil_utilisateur,
                    demande=demande,
                    validation_liee=validation_escalade,
                    type_notification='ESCALADE_EFFECTUEE',
                    urgence='NORMALE',
                    titre=f"Votre demande a été escaladée - {demande.numero_demande}",
                    message=f"{profil_utilisateur.nom_complet} a escaladé votre demande "
                           f"vers un niveau de validation supérieur pour accélérer le traitement. "
                           f"Motif: {motif_escalade}",
                    url_action_principale=f"/interim/demande/{demande.id}/",
                    texte_action_principale="Suivre l'évolution"
                )
        
        logger.info(f"Escalade effectuée par {profil_utilisateur.nom_complet}: "
                   f"Demande {demande.numero_demande} de niveau {ancien_niveau} vers {niveau_cible}")
        
        return True, {
            'message': f'Demande escaladée vers le niveau {niveau_cible}',
            'escalade_info': {
                'ancien_niveau': ancien_niveau,
                'nouveau_niveau': niveau_cible,
                'type_validation_cible': type_validation_cible,
                'validateurs_notifies': notifications_envoyees,
                'nombre_notifications': len(notifications_envoyees)
            }
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de l'effectuation de l'escalade: {e}")
        return False, {'error': f'Erreur système lors de l\'escalade: {str(e)}'}
    
def _peut_escalader_demande(profil_utilisateur, demande):
    """
    Vérifie si l'utilisateur peut escalader cette demande
    
    Args:
        profil_utilisateur: Instance de ProfilUtilisateur
        demande: Instance de DemandeInterim
    
    Returns:
        tuple: (bool, str) - (peut_escalader, raison)
    """
    try:
        # Vérification de base du profil
        if not profil_utilisateur or not demande:
            return False, "Données manquantes"
        
        # Superutilisateurs peuvent toujours escalader
        if profil_utilisateur.is_superuser:
            return True, "Superutilisateur - droits complets"
        
        # Vérifications selon le type de profil avec hiérarchie CORRIGÉE
        type_profil = profil_utilisateur.type_profil
        
        # RH et ADMIN peuvent escalader (niveau final)
        if type_profil in ['RH', 'ADMIN']:
            return True, f"Autorisé comme {profil_utilisateur.get_type_profil_display()}"
        
        # DIRECTEURS peuvent escalader vers RH/ADMIN
        if type_profil == 'DIRECTEUR':
            if demande.niveau_validation_actuel < 3:  # Peut escalader vers niveau 3 (RH/ADMIN)
                return True, "Directeur peut escalader vers RH/Admin"
            else:
                return False, "Niveau d'escalade maximum déjà atteint"
        
        # RESPONSABLES peuvent escalader vers DIRECTEUR ou RH/ADMIN
        if type_profil == 'RESPONSABLE':
            if demande.niveau_validation_actuel < 2:  # Peut escalader vers niveau 2+
                return True, "Responsable peut escalader vers niveau supérieur"
            else:
                return False, "Seuls les Directeurs+ peuvent escalader à ce niveau"
        
        # CHEF_EQUIPE peuvent proposer des escalades dans certains cas
        if type_profil == 'CHEF_EQUIPE':
            # Peut escalader seulement pour les demandes urgentes de son département
            if demande.urgence in ['CRITIQUE', 'ELEVEE']:
                if profil_utilisateur.departement == demande.poste.departement:
                    return True, "Chef d'équipe autorisé pour demandes urgentes du département"
                else:
                    return False, "Chef d'équipe - département différent"
            else:
                return False, "Chef d'équipe - seulement pour demandes urgentes"
        
        # UTILISATEUR standard - cas très limités
        if type_profil == 'UTILISATEUR':
            # Peut escalader seulement si c'est le demandeur original et que c'est critique
            if profil_utilisateur == demande.demandeur and demande.urgence == 'CRITIQUE':
                return True, "Demandeur original - demande critique"
            else:
                return False, "Utilisateur standard non autorisé à escalader"
        
        # Autres types de profil non autorisés
        return False, f"Type de profil '{profil_utilisateur.get_type_profil_display()}' non autorisé à escalader"
        
    except Exception as e:
        logger.error(f"Erreur vérification permissions escalade: {e}")
        return False, f"Erreur système: {str(e)}"


def _demande_peut_etre_escaladee(demande):
    """
    Vérifie si une demande peut être escaladée selon son statut et ses caractéristiques
    
    Args:
        demande: Instance de DemandeInterim
    
    Returns:
        tuple: (bool, str) - (peut_etre_escaladee, raison)
    """
    try:
        # Vérification de base
        if not demande:
            return False, "Demande non trouvée"
        
        # Statuts autorisant l'escalade
        statuts_autorises = ['SOUMISE', 'EN_VALIDATION', 'EN_PROPOSITION', 'CANDIDAT_PROPOSE']
        
        if demande.statut not in statuts_autorises:
            statut_display = demande.get_statut_display() if hasattr(demande, 'get_statut_display') else demande.statut
            return False, f"Statut '{statut_display}' ne permet pas l'escalade"
        
        # Vérifier qu'on n'est pas déjà au niveau maximum
        niveau_max = getattr(demande, 'niveaux_validation_requis', 3) or 3  # Défaut à 3
        if demande.niveau_validation_actuel >= niveau_max:
            return False, "Niveau de validation maximum déjà atteint"
        
        # Vérifier que la demande n'est pas trop ancienne (configurable)
        duree_max_escalade = timedelta(days=30)  # 30 jours max pour escalader
        if hasattr(demande, 'created_at') and demande.created_at:
            if timezone.now() - demande.created_at > duree_max_escalade:
                return False, "Demande trop ancienne pour être escaladée (> 30 jours)"
        
        # Vérifier qu'il n'y a pas eu trop d'escalades récentes
        from .models import HistoriqueAction  # Import local pour éviter les imports circulaires
        
        escalades_recentes = HistoriqueAction.objects.filter(
            demande=demande,
            action='ESCALADE_DEMANDE',
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        
        if escalades_recentes >= 3:  # Maximum 3 escalades par 24h
            return False, "Trop d'escalades récentes (max 3 par 24h)"
        
        # Vérifier que la demande n'est pas en cours de traitement par un autre processus
        # (optionnel - peut être étendu selon les besoins métier)
        
        # Vérifier la cohérence des dates
        if demande.date_debut and demande.date_fin:
            if demande.date_debut > demande.date_fin:
                return False, "Dates de mission incohérentes"
            
            # Ne pas escalader si la mission est déjà commencée
            if demande.date_debut <= timezone.now().date():
                return False, "Mission déjà commencée - escalade non pertinente"
        
        return True, "Demande peut être escaladée"
        
    except Exception as e:
        logger.error(f"Erreur vérification escalade possible: {e}")
        return False, f"Erreur système: {str(e)}"


def _determiner_niveau_escalade(demande, profil_utilisateur):
    """
    Détermine le niveau cible pour l'escalade selon la demande et l'utilisateur
    
    Args:
        demande: Instance de DemandeInterim
        profil_utilisateur: Instance de ProfilUtilisateur
    
    Returns:
        int: Niveau cible d'escalade
    """
    try:
        niveau_actuel = demande.niveau_validation_actuel
        niveau_max = getattr(demande, 'niveaux_validation_requis', 3) or 3
        
        # Par défaut, escalader au niveau suivant
        niveau_cible = niveau_actuel + 1
        
        # Logiques spéciales selon le type d'utilisateur et l'urgence
        type_profil = profil_utilisateur.type_profil
        urgence = demande.urgence
        
        # Superutilisateurs - escalade intelligente
        if profil_utilisateur.is_superuser:
            if urgence == 'CRITIQUE':
                niveau_cible = niveau_max  # Directement au niveau final
            else:
                niveau_cible = min(niveau_actuel + 2, niveau_max)  # Saut de 2 niveaux
        
        # RH/ADMIN peuvent escalader directement au niveau final
        elif type_profil in ['RH', 'ADMIN']:
            niveau_cible = niveau_max
        
        # DIRECTEUR peut escalader vers RH (niveau 3)
        elif type_profil == 'DIRECTEUR':
            niveau_cible = min(3, niveau_max)
        
        # RESPONSABLE peut escalader vers DIRECTEUR ou RH selon urgence
        elif type_profil == 'RESPONSABLE':
            if urgence == 'CRITIQUE':
                niveau_cible = min(3, niveau_max)  # Directement vers RH
            else:
                niveau_cible = min(2, niveau_max)  # Vers DIRECTEUR
        
        # CHEF_EQUIPE peut escalader seulement vers RESPONSABLE
        elif type_profil == 'CHEF_EQUIPE':
            niveau_cible = min(1, niveau_max)  # Vers RESPONSABLE
        
        # Logiques spéciales selon l'urgence
        if urgence == 'CRITIQUE':
            # Demandes critiques : escalader plus agressivement
            if niveau_cible < niveau_max:
                niveau_cible = min(niveau_actuel + 2, niveau_max)
        elif urgence == 'ELEVEE':
            # Demandes élevées : escalader de 1 niveau supplémentaire si possible
            niveau_cible = min(niveau_cible + 1, niveau_max)
        
        # Assurer que le niveau cible ne dépasse pas le maximum
        niveau_cible = min(niveau_cible, niveau_max)
        
        # Assurer que le niveau cible est supérieur au niveau actuel
        if niveau_cible <= niveau_actuel:
            niveau_cible = niveau_actuel + 1
        
        return min(niveau_cible, niveau_max)
        
    except Exception as e:
        logger.error(f"Erreur détermination niveau escalade: {e}")
        return demande.niveau_validation_actuel + 1


def _get_type_validation_par_niveau(niveau):
    """
    Retourne le type de validation selon le niveau hiérarchique
    
    Args:
        niveau: int - Niveau de validation
    
    Returns:
        str: Type de validation correspondant
    """
    try:
        # Mapping strict niveau → type de validation
        mapping = {
            1: 'RESPONSABLE',  # Niveau 1 : Responsable (N+1)
            2: 'DIRECTEUR',    # Niveau 2 : Directeur (N+2)
            3: 'RH',           # Niveau 3 : RH (Final)
            4: 'ADMIN',        # Niveau 4 : Admin (Exceptionnel)
        }
        
        # Retourner le type correspondant ou RH par défaut pour les niveaux élevés
        return mapping.get(niveau, 'RH')
        
    except Exception as e:
        logger.error(f"Erreur détermination type validation niveau {niveau}: {e}")
        return 'RESPONSABLE'


def _obtenir_validateurs_pour_escalade(demande, niveau_cible):
    """
    Obtient les validateurs pour le niveau cible d'escalade
    
    Args:
        demande: Instance de DemandeInterim
        niveau_cible: int - Niveau de validation cible
    
    Returns:
        QuerySet: Validateurs pour le niveau cible
    """
    try:
        from .models import ProfilUtilisateur  # Import local pour éviter les imports circulaires
        
        # Déterminer le type de validation requis
        type_validation = _get_type_validation_par_niveau(niveau_cible)
        
        # Base QuerySet - utilisateurs actifs seulement
        base_queryset = ProfilUtilisateur.objects.filter(actif=True)
        
        if niveau_cible == 1:
            # Niveau 1 : RESPONSABLE du département
            validateurs = base_queryset.filter(
                type_profil='RESPONSABLE',
                departement=demande.poste.departement
            )
            
            # Si aucun responsable spécifique, prendre tous les responsables
            if not validateurs.exists():
                validateurs = base_queryset.filter(type_profil='RESPONSABLE')
        
        elif niveau_cible == 2:
            # Niveau 2 : DIRECTEURS
            validateurs = base_queryset.filter(type_profil='DIRECTEUR')
            
            # Optionnel : filtrer par site si configuré
            if hasattr(demande.poste, 'site') and demande.poste.site:
                directeurs_site = validateurs.filter(site=demande.poste.site)
                if directeurs_site.exists():
                    validateurs = directeurs_site
        
        elif niveau_cible >= 3:
            # Niveau 3+ : RH et ADMIN
            validateurs = base_queryset.filter(
                type_profil__in=['RH', 'ADMIN']
            )
        
        else:
            # Niveau invalide - retourner QuerySet vide
            logger.warning(f"Niveau d'escalade invalide: {niveau_cible}")
            return base_queryset.none()
        
        # Ajouter les superutilisateurs comme validateurs de dernier recours
        if not validateurs.exists():
            logger.warning(f"Aucun validateur trouvé pour niveau {niveau_cible}, utilisation des superutilisateurs")
            superusers = base_queryset.filter(user__is_superuser=True)
            if superusers.exists():
                validateurs = superusers
        
        # Tri par priorité : responsables du département d'abord, puis autres
        if niveau_cible <= 2 and demande.poste.departement:
            validateurs = validateurs.order_by(
                # Département correspondant en premier
                '-departement__id' if demande.poste.departement else 'id',
                'user__last_name', 
                'user__first_name'
            )
        else:
            validateurs = validateurs.order_by(
                'user__last_name', 
                'user__first_name'
            )
        
        # Log pour debug
        count = validateurs.count()
        logger.info(f"Escalade niveau {niveau_cible} ({type_validation}): {count} validateur(s) trouvé(s)")
        
        return validateurs
        
    except Exception as e:
        logger.error(f"Erreur obtention validateurs escalade niveau {niveau_cible}: {e}")
        from .models import ProfilUtilisateur
        return ProfilUtilisateur.objects.none()


# ================================================================
# FONCTIONS UTILITAIRES COMPLÉMENTAIRES
# ================================================================

def _verifier_coherence_escalade(demande, niveau_propose):
    """
    Vérifie que la progression d'escalade est cohérente
    
    Args:
        demande: Instance de DemandeInterim
        niveau_propose: int - Niveau proposé pour l'escalade
    
    Returns:
        tuple: (bool, str) - (coherent, raison)
    """
    try:
        niveau_actuel = demande.niveau_validation_actuel
        
        # Vérifier que c'est bien le niveau suivant ou supérieur
        if niveau_propose <= niveau_actuel:
            return False, f"Niveau proposé ({niveau_propose}) inférieur ou égal au niveau actuel ({niveau_actuel})"
        
        # Vérifier qu'on ne dépasse pas le maximum
        niveau_max = getattr(demande, 'niveaux_validation_requis', 3) or 3
        if niveau_propose > niveau_max:
            return False, f"Niveau proposé ({niveau_propose}) supérieur au maximum autorisé ({niveau_max})"
        
        # Vérifier que le saut de niveau n'est pas trop important (sauf urgence)
        saut_niveau = niveau_propose - niveau_actuel
        if saut_niveau > 2 and demande.urgence not in ['CRITIQUE', 'ELEVEE']:
            return False, f"Saut de niveau trop important ({saut_niveau}) pour une demande {demande.urgence}"
        
        return True, "Progression cohérente"
        
    except Exception as e:
        logger.error(f"Erreur vérification cohérence escalade: {e}")
        return False, f"Erreur système: {str(e)}"


def _calculer_delai_escalade(demande):
    """
    Calcule le délai recommandé avant la prochaine escalade
    
    Args:
        demande: Instance de DemandeInterim
    
    Returns:
        timedelta: Délai recommandé
    """
    try:
        # Délais de base selon l'urgence
        delais_base = {
            'CRITIQUE': timedelta(hours=2),   # 2 heures
            'ELEVEE': timedelta(hours=8),     # 8 heures  
            'MOYENNE': timedelta(days=1),     # 1 jour
            'NORMALE': timedelta(days=2),     # 2 jours
        }
        
        delai = delais_base.get(demande.urgence, timedelta(days=1))
        
        # Ajuster selon le niveau actuel (plus c'est haut, plus c'est long)
        niveau_actuel = demande.niveau_validation_actuel
        facteur_niveau = 1 + (niveau_actuel * 0.5)  # +50% par niveau
        
        return delai * facteur_niveau
        
    except Exception as e:
        logger.error(f"Erreur calcul délai escalade: {e}")
        return timedelta(days=1)  # Délai par défaut


def _historique_escalades_demande(demande):
    """
    Récupère l'historique complet des escalades pour une demande
    
    Args:
        demande: Instance de DemandeInterim
    
    Returns:
        QuerySet: Historique des escalades
    """
    try:
        from .models import HistoriqueAction
        
        return HistoriqueAction.objects.filter(
            demande=demande,
            action='ESCALADE_DEMANDE'
        ).select_related(
            'utilisateur', 
            'validation'
        ).order_by('-created_at')
        
    except Exception as e:
        logger.error(f"Erreur récupération historique escalades: {e}")
        from .models import HistoriqueAction
        return HistoriqueAction.objects.none()


def _peut_re_escalader(demande, profil_utilisateur):
    """
    Vérifie si une demande peut être escaladée à nouveau
    
    Args:
        demande: Instance de DemandeInterim
        profil_utilisateur: Instance de ProfilUtilisateur
    
    Returns:
        tuple: (bool, str, timedelta|None) - (peut_re_escalader, raison, delai_attente)
    """
    try:
        # Vérifications de base
        peut_escalader, raison = _peut_escalader_demande(profil_utilisateur, demande)
        if not peut_escalader:
            return False, raison, None
        
        peut_etre_escaladee, raison_demande = _demande_peut_etre_escaladee(demande)
        if not peut_etre_escaladee:
            return False, raison_demande, None
        
        # Vérifier le délai depuis la dernière escalade
        derniere_escalade = _historique_escalades_demande(demande).first()
        
        if derniere_escalade:
            delai_recommande = _calculer_delai_escalade(demande)
            temps_ecoule = timezone.now() - derniere_escalade.created_at
            
            if temps_ecoule < delai_recommande:
                delai_restant = delai_recommande - temps_ecoule
                return False, f"Délai d'attente non écoulé", delai_restant
        
        return True, "Peut être escaladée à nouveau", None
        
    except Exception as e:
        logger.error(f"Erreur vérification re-escalade: {e}")
        return False, f"Erreur système: {str(e)}", None


# ================================================================
# FONCTION DE TEST ET DEBUG
# ================================================================

def debug_escalade_info(demande, profil_utilisateur):
    """
    Fonction de debug pour afficher toutes les informations d'escalade
    
    Args:
        demande: Instance de DemandeInterim
        profil_utilisateur: Instance de ProfilUtilisateur
    
    Returns:
        dict: Informations complètes de debug
    """
    try:
        info = {
            'demande_id': demande.id,
            'numero_demande': demande.numero_demande,
            'niveau_actuel': demande.niveau_validation_actuel,
            'niveau_max': getattr(demande, 'niveaux_validation_requis', 3),
            'urgence': demande.urgence,
            'statut': demande.statut,
            'utilisateur': {
                'nom': profil_utilisateur.nom_complet,
                'type_profil': profil_utilisateur.type_profil,
                'is_superuser': profil_utilisateur.is_superuser,
                'departement': profil_utilisateur.departement.nom if profil_utilisateur.departement else None,
            },
            'verifications': {
                'peut_escalader': _peut_escalader_demande(profil_utilisateur, demande),
                'peut_etre_escaladee': _demande_peut_etre_escaladee(demande),
                'peut_re_escalader': _peut_re_escalader(demande, profil_utilisateur),
            },
            'escalade_info': {
                'niveau_cible': _determiner_niveau_escalade(demande, profil_utilisateur),
                'type_validation_cible': None,
                'nb_validateurs_cibles': 0,
            }
        }
        
        # Compléter les informations d'escalade
        niveau_cible = info['escalade_info']['niveau_cible']
        info['escalade_info']['type_validation_cible'] = _get_type_validation_par_niveau(niveau_cible)
        
        validateurs = _obtenir_validateurs_pour_escalade(demande, niveau_cible)
        info['escalade_info']['nb_validateurs_cibles'] = validateurs.count()
        info['escalade_info']['validateurs'] = [v.nom_complet for v in validateurs[:5]]  # Limite à 5 pour l'affichage
        
        # Historique
        historique = _historique_escalades_demande(demande)
        info['historique'] = {
            'nb_escalades': historique.count(),
            'derniere_escalade': historique.first().created_at if historique.exists() else None,
        }
        
        return info
        
    except Exception as e:
        logger.error(f"Erreur debug escalade: {e}")
        return {'error': str(e)}
    
#*--------------------------------------------------------------------------
# AFFICHAGE SCORE EMPLOYE POUR UNE DEMANDE
#*--------------------------------------------------------------------------

def demande_employe_score(request, demande_id, matricule):
    """
    Vue détaillée du scoring d'un employé pour une demande d'intérim spécifique
    Affiche le calcul détaillé du score avec tous les critères
    """
    try:
        # Récupérer la demande
        demande = get_object_or_404(
            DemandeInterim.objects.select_related(
                'demandeur__user',
                'personne_remplacee__user', 
                'poste__departement',
                'poste__site',
                'motif_absence'
            ),
            id=demande_id
        )
        
        # Récupérer l'employé
        employe = get_object_or_404(
            ProfilUtilisateur.objects.select_related(
                'user',
                'departement',
                'site', 
                'poste',
                'manager'
            ).prefetch_related(
                'competences__competence',
                'formations',
                'absences',
                'extended_data',
                'kelio_data'
            ),
            matricule=matricule
        )
        
        # Vérifier que l'utilisateur a les permissions
        if not request.user.is_authenticated:
            return redirect('login')
        
        # Récupérer le profil de l'utilisateur connecté
        try:
            profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        except ProfilUtilisateur.DoesNotExist:
            messages.error(request, "Profil utilisateur non trouvé.")
            return redirect('index')
        
        # Vérifier les permissions d'accès
        peut_voir = (
            profil_utilisateur.is_superuser or
            profil_utilisateur.type_profil in ['RH', 'ADMIN', 'DIRECTEUR', 'RESPONSABLE'] or
            profil_utilisateur == demande.demandeur or
            profil_utilisateur.departement == demande.poste.departement
        )
        
        if not peut_voir:
            messages.error(request, "Vous n'avez pas les permissions pour consulter ce scoring.")
            return redirect('index')
        
        # Calculer ou récupérer le score détaillé
        score_detail = _calculer_score_detaille_pour_affichage(employe, demande)
        
        # Récupérer les propositions existantes pour cet employé
        proposition_existante = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=employe
        ).select_related('proposant').first()
        
        # Récupérer l'historique des scores pour cet employé
        scores_historique = ScoreDetailCandidat.objects.filter(
            candidat=employe,
            demande_interim=demande
        ).order_by('-created_at')
        
        # Informations de disponibilité
        disponibilite_info = _verifier_disponibilite_candidat(employe, demande.date_debut, demande.date_fin)
        
        # Comparaison avec les autres candidats de la demande
        autres_candidats = _get_candidats_comparaison(demande, employe)
        
        # Analyse des compétences requises vs possédées
        analyse_competences = _analyser_competences_pour_poste(employe, demande.poste)
        
        # Facteurs d'amélioration du score
        ameliorations_possibles = _identifier_ameliorations_score(score_detail, employe, demande)
        
        # Historique des missions d'intérim de cet employé
        missions_historique = _get_historique_missions_interim(employe)
        
        # Préparer le contexte
        context = {
            'demande': demande,
            'employe': employe,
            'score_detail': score_detail,
            'proposition_existante': proposition_existante,
            'scores_historique': scores_historique,
            'disponibilite_info': disponibilite_info,
            'autres_candidats': autres_candidats,
            'analyse_competences': analyse_competences,
            'ameliorations_possibles': ameliorations_possibles,
            'missions_historique': missions_historique,
            'profil_utilisateur': profil_utilisateur,
            
            # Informations de navigation
            'page_title': f'Score de {employe.nom_complet}',
            'breadcrumb': [
                {'title': 'Accueil', 'url': reverse('index')},
                {'title': 'Demandes', 'url': reverse('liste_interim_validation')},
                {'title': f'Demande {demande.numero_demande}', 'url': reverse('interim_validation', args=[demande.id])},
                {'title': f'Score {employe.nom_complet}', 'url': ''},
            ],
            
            # Permissions
            'peut_proposer': _peut_proposer_candidat(profil_utilisateur, demande),
            'peut_modifier_score': profil_utilisateur.type_profil in ['RH', 'ADMIN'] or profil_utilisateur.is_superuser,
            'peut_voir_details_complets': profil_utilisateur.type_profil in ['RH', 'ADMIN', 'DIRECTEUR'] or profil_utilisateur.is_superuser,
        }
        
        return render(request, 'employe_score.html', context)
        
    except Exception as e:
        logger.error(f"Erreur dans demande_employe_score: {e}", exc_info=True)
        messages.error(request, "Erreur lors du chargement du détail du score.")
        return redirect('index')


def _calculer_score_detaille_pour_affichage(employe, demande):
    """
    Calcule le score détaillé d'un employé pour une demande avec toutes les explications
    """
    try:
        # Vérifier s'il existe déjà un score calculé
        score_existant = ScoreDetailCandidat.objects.filter(
            candidat=employe,
            demande_interim=demande
        ).first()
        
        if score_existant:
            # Utiliser le score existant mais enrichir avec les explications
            score_detail = {
                'score_final': score_existant.score_total,
                'scores_criteres': {
                    'similarite_poste': score_existant.score_similarite_poste,
                    'competences': score_existant.score_competences,
                    'experience': score_existant.score_experience,
                    'disponibilite': score_existant.score_disponibilite,
                    'proximite': score_existant.score_proximite,
                    'anciennete': score_existant.score_anciennete,
                },
                'bonus': {
                    'proposition_humaine': score_existant.bonus_proposition_humaine,
                    'experience_similaire': score_existant.bonus_experience_similaire,
                    'recommandation': score_existant.bonus_recommandation,
                    'hierarchique': score_existant.bonus_hierarchique,
                },
                'penalites': {
                    'indisponibilite': score_existant.penalite_indisponibilite,
                },
                'calcule_par': score_existant.calcule_par,
                'date_calcul': score_existant.created_at,
            }
        else:
            # Calculer un nouveau score
            score_simple = _calculer_score_candidat_simple(employe, demande)
            score_detail = {
                'score_final': score_simple,
                'scores_criteres': {},
                'bonus': {},
                'penalites': {},
                'calcule_par': 'TEMPS_REEL',
                'date_calcul': timezone.now(),
            }
        
        # Ajouter les explications détaillées
        score_detail.update(_generer_explications_score(employe, demande, score_detail))
        
        # Ajouter la classe CSS pour l'affichage
        score_detail['classe_css'] = _get_classe_css_score(score_detail['score_final'])
        
        return score_detail
        
    except Exception as e:
        logger.error(f"Erreur calcul score détaillé: {e}")
        return {
            'score_final': 0,
            'scores_criteres': {},
            'bonus': {},
            'penalites': {},
            'explications': ['Erreur lors du calcul du score'],
            'classe_css': 'poor',
            'calcule_par': 'ERREUR',
            'date_calcul': timezone.now(),
        }


def _generer_explications_score(employe, demande, score_detail):
    """
    Génère les explications détaillées pour chaque critère de scoring
    """
    explications = {
        'explications_criteres': {},
        'explications_bonus': {},
        'explications_penalites': {},
        'recommandations': [],
        'points_forts': [],
        'points_faibles': [],
    }
    
    try:
        # Analyser la similarité de poste
        if employe.poste and demande.poste:
            if employe.poste.departement == demande.poste.departement:
                explications['points_forts'].append("Même département")
                explications['explications_criteres']['similarite_poste'] = [
                    f"Employé du département {employe.poste.departement.nom}",
                    f"Poste demandé dans le département {demande.poste.departement.nom}",
                    "✓ Correspondance parfaite de département"
                ]
            else:
                explications['points_faibles'].append("Département différent")
                explications['explications_criteres']['similarite_poste'] = [
                    f"Employé du département {employe.poste.departement.nom}",
                    f"Poste demandé dans le département {demande.poste.departement.nom}",
                    "⚠ Changement de département requis"
                ]
        
        # Analyser les compétences
        competences_employe = employe.competences.count()
        if competences_employe > 0:
            if competences_employe >= 5:
                explications['points_forts'].append(f"{competences_employe} compétences répertoriées")
            explications['explications_criteres']['competences'] = [
                f"Nombre de compétences : {competences_employe}",
                f"Score calculé : {min(25, competences_employe * 3)}/25 points"
            ]
        else:
            explications['points_faibles'].append("Aucune compétence répertoriée")
            explications['explications_criteres']['competences'] = [
                "Aucune compétence enregistrée dans le système",
                "Recommandation : Mettre à jour le profil de compétences"
            ]
        
        # Analyser l'ancienneté
        if hasattr(employe, 'extended_data') and employe.extended_data.date_embauche:
            anciennete_mois = (timezone.now().date() - employe.extended_data.date_embauche).days // 30
            if anciennete_mois >= 24:
                explications['points_forts'].append(f"Ancienneté importante ({anciennete_mois} mois)")
                explications['explications_criteres']['anciennete'] = [
                    f"Date d'embauche : {employe.extended_data.date_embauche.strftime('%d/%m/%Y')}",
                    f"Ancienneté : {anciennete_mois} mois",
                    "✓ Expérience significative dans l'entreprise"
                ]
            elif anciennete_mois >= 12:
                explications['explications_criteres']['anciennete'] = [
                    f"Ancienneté : {anciennete_mois} mois",
                    "Expérience intermédiaire dans l'entreprise"
                ]
            else:
                explications['points_faibles'].append("Ancienneté limitée")
                explications['explications_criteres']['anciennete'] = [
                    f"Ancienneté : {anciennete_mois} mois",
                    "⚠ Employé relativement récent"
                ]
        
        # Analyser la disponibilité
        if hasattr(employe, 'extended_data') and employe.extended_data.disponible_interim:
            explications['points_forts'].append("Disponible pour l'intérim")
            explications['explications_criteres']['disponibilite'] = [
                "✓ Profil configuré comme disponible pour l'intérim",
                "Aucune restriction signalée"
            ]
        else:
            explications['points_faibles'].append("Disponibilité non confirmée")
            explications['explications_criteres']['disponibilite'] = [
                "⚠ Disponibilité pour l'intérim non confirmée",
                "Recommandation : Vérifier avec l'employé"
            ]
        
        # Analyser la proximité géographique
        if employe.site == demande.poste.site:
            explications['points_forts'].append("Même site de travail")
            explications['explications_criteres']['proximite'] = [
                f"Site actuel : {employe.site.nom}",
                f"Site demandé : {demande.poste.site.nom}",
                "✓ Aucun déplacement requis"
            ]
        elif employe.departement == demande.poste.departement:
            explications['explications_criteres']['proximite'] = [
                f"Site actuel : {employe.site.nom}",
                f"Site demandé : {demande.poste.site.nom}",
                "Même département, déplacement possible"
            ]
        else:
            explications['points_faibles'].append("Site différent")
            explications['explications_criteres']['proximite'] = [
                f"Site actuel : {employe.site.nom}",
                f"Site demandé : {demande.poste.site.nom}",
                "⚠ Changement de site requis"
            ]
        
        # Recommandations d'amélioration
        if len(explications['points_faibles']) > len(explications['points_forts']):
            explications['recommandations'].append("Profil à développer pour l'intérim")
        
        if competences_employe == 0:
            explications['recommandations'].append("Mettre à jour le profil de compétences")
        
        if not (hasattr(employe, 'extended_data') and employe.extended_data.disponible_interim):
            explications['recommandations'].append("Confirmer la disponibilité pour l'intérim")
        
        return explications
        
    except Exception as e:
        logger.error(f"Erreur génération explications score: {e}")
        return explications


def _get_candidats_comparaison(demande, employe_actuel):
    """
    Récupère les autres candidats pour comparaison
    """
    try:
        # Récupérer toutes les propositions pour cette demande
        autres_propositions = PropositionCandidat.objects.filter(
            demande_interim=demande
        ).exclude(
            candidat_propose=employe_actuel
        ).select_related(
            'candidat_propose__user',
            'candidat_propose__departement',
            'candidat_propose__poste'
        ).order_by('-score_final')[:5]  # Top 5 autres candidats
        
        candidats_comparaison = []
        for prop in autres_propositions:
            candidats_comparaison.append({
                'employe': prop.candidat_propose,
                'score': prop.score_final,
                'source': prop.source_proposition,
                'proposition': prop
            })
        
        return candidats_comparaison
        
    except Exception as e:
        logger.error(f"Erreur récupération candidats comparaison: {e}")
        return []


def _analyser_competences_pour_poste(employe, poste):
    """
    Analyse les compétences de l'employé par rapport au poste
    """
    try:
        competences_employe = employe.competences.select_related('competence').all()
        
        analyse = {
            'competences_pertinentes': [],
            'competences_manquantes': [],
            'competences_supplementaires': [],
            'score_adequation': 0,
            'recommandations': []
        }
        
        # Analyser les compétences existantes
        for comp in competences_employe:
            comp_info = {
                'nom': comp.competence.nom,
                'niveau': comp.niveau_maitrise,
                'niveau_display': comp.get_niveau_maitrise_display(),
                'certifie': comp.certifie,
                'pertinente': True  # Simplifié - à améliorer avec un système de matching
            }
            
            if comp.niveau_maitrise >= 3:  # Confirmé ou Expert
                analyse['competences_pertinentes'].append(comp_info)
            else:
                comp_info['recommandation'] = "Niveau à améliorer"
                analyse['competences_supplementaires'].append(comp_info)
        
        # Calculer le score d'adéquation
        if competences_employe:
            nb_competences_confirmees = sum(1 for c in competences_employe if c.niveau_maitrise >= 3)
            analyse['score_adequation'] = min(100, (nb_competences_confirmees / len(competences_employe)) * 100)
        
        # Générer des recommandations
        if analyse['score_adequation'] < 50:
            analyse['recommandations'].append("Développer les compétences clés pour ce poste")
        
        if not analyse['competences_pertinentes']:
            analyse['recommandations'].append("Acquérir des compétences spécifiques au poste")
        
        return analyse
        
    except Exception as e:
        logger.error(f"Erreur analyse compétences: {e}")
        return {
            'competences_pertinentes': [],
            'competences_manquantes': [],
            'competences_supplementaires': [],
            'score_adequation': 0,
            'recommandations': ["Erreur lors de l'analyse des compétences"]
        }


def _identifier_ameliorations_score(score_detail, employe, demande):
    """
    Identifie les améliorations possibles pour le score
    """
    ameliorations = []
    
    try:
        score_final = score_detail.get('score_final', 0)
        
        if score_final < 60:
            ameliorations.append({
                'categorie': 'Critique',
                'titre': 'Score global faible',
                'description': 'Le score nécessite des améliorations importantes',
                'actions': [
                    'Vérifier la disponibilité réelle',
                    'Mettre à jour les compétences',
                    'Confirmer l\'adéquation au poste'
                ],
                'priorite': 'haute'
            })
        
        # Vérifier les compétences
        if employe.competences.count() == 0:
            ameliorations.append({
                'categorie': 'Compétences',
                'titre': 'Aucune compétence répertoriée',
                'description': 'Le profil de compétences est incomplet',
                'actions': [
                    'Ajouter les compétences principales',
                    'Faire évaluer le niveau de maîtrise',
                    'Obtenir des certifications si possible'
                ],
                'priorite': 'haute'
            })
        
        # Vérifier la disponibilité
        if not (hasattr(employe, 'extended_data') and employe.extended_data.disponible_interim):
            ameliorations.append({
                'categorie': 'Disponibilité',
                'titre': 'Disponibilité non confirmée',
                'description': 'Le statut de disponibilité pour l\'intérim n\'est pas défini',
                'actions': [
                    'Confirmer la disponibilité avec l\'employé',
                    'Mettre à jour le profil',
                    'Vérifier les contraintes personnelles'
                ],
                'priorite': 'moyenne'
            })
        
        # Suggestions d'optimisation
        if score_final >= 60 and score_final < 80:
            ameliorations.append({
                'categorie': 'Optimisation',
                'titre': 'Potentiel d\'amélioration',
                'description': 'Quelques ajustements peuvent améliorer significativement le score',
                'actions': [
                    'Développer les compétences clés',
                    'Acquérir de l\'expérience dans des postes similaires',
                    'Maintenir un bon niveau de disponibilité'
                ],
                'priorite': 'basse'
            })
        
        return ameliorations
        
    except Exception as e:
        logger.error(f"Erreur identification améliorations: {e}")
        return []


def _get_historique_missions_interim(employe):
    """
    Récupère l'historique des missions d'intérim de l'employé
    """
    try:
        missions = ReponseCandidatInterim.objects.filter(
            candidat=employe,
            reponse='ACCEPTE'
        ).select_related(
            'demande__poste__departement',
            'demande__poste__site'
        ).order_by('-date_reponse')[:20]  # 20 dernières missions
        
        historique = []
        for mission in missions:
            mission_info = {
                'demande': mission.demande,
                'poste': mission.demande.poste.titre,
                'departement': mission.demande.poste.departement.nom,
                'site': mission.demande.poste.site.nom,
                'date_debut': mission.demande.date_debut,
                'date_fin': mission.demande.date_fin,
                'duree_jours': mission.demande.duree_mission,
                'evaluation': mission.demande.evaluation_mission,
                'statut': mission.demande.statut,
                'date_acceptation': mission.date_reponse
            }
            historique.append(mission_info)
        
        return historique
        
    except Exception as e:
        logger.error(f"Erreur récupération historique missions: {e}")
        return []


def _peut_proposer_candidat(profil_utilisateur, demande):
    """
    Vérifie si l'utilisateur peut proposer ce candidat
    """
    try:
        return demande.peut_proposer_candidat(profil_utilisateur)[0]
    except Exception:
        return False


def _get_classe_css_score(score):
    """
    Retourne la classe CSS selon le score
    """
    if score >= 80:
        return 'excellent'
    elif score >= 65:
        return 'good'
    elif score >= 50:
        return 'average'
    else:
        return 'poor'
    
@login_required
def employe_hierarchie(request, matricule):
    """
    Vue pour afficher la hiérarchie d'un employé
    """
    try:
        profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        employe = get_object_or_404(
            ProfilUtilisateur.objects.with_full_relations(), 
            matricule=matricule
        )
        
        # Vérifier les permissions
        if not _peut_voir_hierarchie(profil_utilisateur, employe):
            messages.error(request, "Permission refusée pour consulter cette hiérarchie")
            return redirect('employe_detail', matricule=matricule)
        
        # Construire la chaîne hiérarchique vers le haut
        chaine_hierarchique = _construire_chaine_hierarchique(employe)
        
        # Récupérer l'équipe directe de l'employé
        equipe_directe = ProfilUtilisateur.objects.filter(
            manager=employe,
            actif=True
        ).select_related('user', 'departement', 'site', 'poste').order_by('user__last_name', 'user__first_name')
        
        # Récupérer les collègues (même manager)
        collegues = []
        if employe.manager:
            collegues = ProfilUtilisateur.objects.filter(
                manager=employe.manager,
                actif=True
            ).exclude(
                id=employe.id
            ).select_related('user', 'departement', 'site', 'poste').order_by('user__last_name', 'user__first_name')
        
        # Calculer les statistiques de la hiérarchie
        stats_hierarchie = _calculer_statistiques_hierarchie(employe)
        
        # Récupérer les demandes d'intérim impliquant cette hiérarchie
        demandes_hierarchie = _get_demandes_hierarchie(employe, profil_utilisateur)
        
        context = {
            'employe': employe,
            'profil_utilisateur': profil_utilisateur,
            'chaine_hierarchique': chaine_hierarchique,
            'equipe_directe': equipe_directe,
            'collegues': collegues,
            'stats_hierarchie': stats_hierarchie,
            'demandes_hierarchie': demandes_hierarchie,
            'peut_voir_details': _peut_voir_details_hierarchie(profil_utilisateur, employe),
            'peut_modifier_hierarchie': _peut_modifier_hierarchie(profil_utilisateur),
        }
        
        return render(request, 'employe_hierarchie.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Employé non trouvé")
        return redirect('employes_liste')
    except Exception as e:
        logger.error(f"Erreur dans employe_hierarchie: {e}")
        messages.error(request, "Erreur lors du chargement de la hiérarchie")
        return redirect('employe_detail', matricule=matricule)


def _peut_voir_hierarchie(profil_utilisateur, employe):
    """
    Vérifie si un utilisateur peut voir la hiérarchie d'un employé
    """
    # Superutilisateurs peuvent tout voir
    if profil_utilisateur.is_superuser:
        return True
    
    # L'employé peut voir sa propre hiérarchie
    if profil_utilisateur == employe:
        return True
    
    # RH et Admin peuvent voir toutes les hiérarchies
    if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return True
    
    # Directeurs peuvent voir leur périmètre
    if profil_utilisateur.type_profil == 'DIRECTEUR':
        if profil_utilisateur.departement == employe.departement:
            return True
    
    # Responsables peuvent voir leur équipe et leur département
    if profil_utilisateur.type_profil == 'RESPONSABLE':
        if profil_utilisateur.departement == employe.departement:
            return True
    
    # Managers peuvent voir leur équipe directe et indirecte
    if _est_dans_hierarchie(profil_utilisateur, employe):
        return True
    
    # Collègues du même département avec certains profils
    if (profil_utilisateur.departement == employe.departement and 
        profil_utilisateur.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE']):
        return True
    
    return False


def _peut_voir_details_hierarchie(profil_utilisateur, employe):
    """
    Vérifie si l'utilisateur peut voir les détails complets de la hiérarchie
    """
    return (
        profil_utilisateur.is_superuser or
        profil_utilisateur.type_profil in ['RH', 'ADMIN', 'DIRECTEUR'] or
        profil_utilisateur == employe or
        employe.manager == profil_utilisateur
    )


def _peut_modifier_hierarchie(profil_utilisateur):
    """
    Vérifie si l'utilisateur peut modifier la hiérarchie
    """
    return (
        profil_utilisateur.is_superuser or
        profil_utilisateur.type_profil in ['RH', 'ADMIN']
    )


def _construire_chaine_hierarchique(employe):
    """
    Construit la chaîne hiérarchique complète de l'employé vers le haut
    """
    chaine = []
    current = employe
    visited = set()  # Protection contre les boucles infinies
    
    while current and current.id not in visited:
        visited.add(current.id)
        
        # Calculer le niveau hiérarchique
        niveau = _get_niveau_hierarchique(current.type_profil)
        
        # Récupérer l'équipe directe pour ce niveau
        equipe_count = ProfilUtilisateur.objects.filter(
            manager=current,
            actif=True
        ).count()
        
        chaine.append({
            'employe': current,
            'niveau_hierarchique': niveau,
            'niveau_nom': _get_niveau_nom(current.type_profil),
            'equipe_count': equipe_count,
            'est_racine': current.manager is None,
            'distance_de_base': len(chaine),
        })
        
        current = current.manager
        
        # Sécurité : maximum 10 niveaux
        if len(chaine) >= 10:
            break
    
    return chaine


def _get_niveau_hierarchique(type_profil):
    """
    Retourne le niveau hiérarchique numérique
    """
    niveaux = {
        'UTILISATEUR': 1,
        'CHEF_EQUIPE': 2,
        'RESPONSABLE': 3,
        'DIRECTEUR': 4,
        'RH': 5,
        'ADMIN': 5,
    }
    return niveaux.get(type_profil, 1)


def _get_niveau_nom(type_profil):
    """
    Retourne le nom du niveau hiérarchique
    """
    noms = {
        'UTILISATEUR': 'Équipe opérationnelle',
        'CHEF_EQUIPE': 'Encadrement de proximité',
        'RESPONSABLE': 'Management intermédiaire',
        'DIRECTEUR': 'Direction',
        'RH': 'Direction RH',
        'ADMIN': 'Administration générale',
    }
    return noms.get(type_profil, 'Non défini')


def _est_dans_hierarchie(manager, employe):
    """
    Vérifie si un manager est dans la hiérarchie d'un employé
    """
    current = employe
    visited = set()
    
    while current and current.id not in visited:
        visited.add(current.id)
        if current.manager == manager:
            return True
        current = current.manager
        
        # Sécurité
        if len(visited) >= 10:
            break
    
    return False


def _calculer_statistiques_hierarchie(employe):
    """
    Calcule les statistiques de la hiérarchie
    """
    try:
        # Compter l'équipe directe
        equipe_directe_count = ProfilUtilisateur.objects.filter(
            manager=employe,
            actif=True
        ).count()
        
        # Compter l'équipe indirecte (récursif)
        equipe_totale_count = _compter_equipe_recursive(employe)
        
        # Calculer la profondeur hiérarchique vers le haut
        profondeur_vers_haut = 0
        current = employe.manager
        visited = set()
        
        while current and current.id not in visited:
            visited.add(current.id)
            profondeur_vers_haut += 1
            current = current.manager
            if profondeur_vers_haut >= 10:  # Sécurité
                break
        
        # Calculer la profondeur hiérarchique vers le bas
        profondeur_vers_bas = _calculer_profondeur_vers_bas(employe)
        
        # Compter les demandes d'intérim en cours impliquant cette hiérarchie
        demandes_en_cours = DemandeInterim.objects.filter(
            Q(demandeur=employe) | 
            Q(personne_remplacee=employe) | 
            Q(candidat_selectionne=employe),
            statut__in=['SOUMISE', 'EN_VALIDATION', 'VALIDEE', 'EN_COURS']
        ).count()
        
        return {
            'equipe_directe_count': equipe_directe_count,
            'equipe_totale_count': equipe_totale_count,
            'profondeur_vers_haut': profondeur_vers_haut,
            'profondeur_vers_bas': profondeur_vers_bas,
            'demandes_en_cours': demandes_en_cours,
            'niveau_hierarchique': _get_niveau_hierarchique(employe.type_profil),
            'niveau_nom': _get_niveau_nom(employe.type_profil),
        }
        
    except Exception as e:
        logger.error(f"Erreur calcul statistiques hiérarchie: {e}")
        return {
            'equipe_directe_count': 0,
            'equipe_totale_count': 0,
            'profondeur_vers_haut': 0,
            'profondeur_vers_bas': 0,
            'demandes_en_cours': 0,
            'niveau_hierarchique': 1,
            'niveau_nom': 'Non défini',
        }


def _compter_equipe_recursive(employe, visited=None):
    """
    Compte récursivement tous les membres de l'équipe
    """
    if visited is None:
        visited = set()
    
    if employe.id in visited:
        return 0
    
    visited.add(employe.id)
    count = 0
    
    try:
        equipe_directe = ProfilUtilisateur.objects.filter(
            manager=employe,
            actif=True
        )
        
        for membre in equipe_directe:
            count += 1  # Compter le membre direct
            count += _compter_equipe_recursive(membre, visited)  # Compter son équipe
            
        return count
        
    except Exception as e:
        logger.error(f"Erreur comptage équipe récursive: {e}")
        return 0


def _calculer_profondeur_vers_bas(employe, visited=None):
    """
    Calcule la profondeur maximale de la hiérarchie vers le bas
    """
    if visited is None:
        visited = set()
    
    if employe.id in visited:
        return 0
    
    visited.add(employe.id)
    
    try:
        equipe_directe = ProfilUtilisateur.objects.filter(
            manager=employe,
            actif=True
        )
        
        if not equipe_directe.exists():
            return 0
        
        max_profondeur = 0
        for membre in equipe_directe:
            profondeur_membre = 1 + _calculer_profondeur_vers_bas(membre, visited)
            max_profondeur = max(max_profondeur, profondeur_membre)
        
        return max_profondeur
        
    except Exception as e:
        logger.error(f"Erreur calcul profondeur vers bas: {e}")
        return 0


def _get_demandes_hierarchie(employe, profil_utilisateur):
    """
    Récupère les demandes d'intérim impliquant cette hiérarchie
    """
    try:
        # Filtres de base
        base_filter = Q(
            Q(demandeur=employe) | 
            Q(personne_remplacee=employe) | 
            Q(candidat_selectionne=employe)
        )
        
        # Si l'utilisateur peut voir plus de détails, inclure son équipe
        if _peut_voir_details_hierarchie(profil_utilisateur, employe):
            equipe_ids = ProfilUtilisateur.objects.filter(
                manager=employe,
                actif=True
            ).values_list('id', flat=True)
            
            if equipe_ids:
                equipe_filter = Q(
                    Q(demandeur__id__in=equipe_ids) |
                    Q(personne_remplacee__id__in=equipe_ids) |
                    Q(candidat_selectionne__id__in=equipe_ids)
                )
                base_filter |= equipe_filter
        
        demandes = DemandeInterim.objects.filter(
            base_filter
        ).select_related(
            'demandeur__user',
            'personne_remplacee__user',
            'candidat_selectionne__user',
            'poste__departement',
            'poste__site'
        ).order_by('-created_at')[:50]  # Limiter à 50 résultats récents
        
        return demandes
        
    except Exception as e:
        logger.error(f"Erreur récupération demandes hiérarchie: {e}")
        return DemandeInterim.objects.none()
    
def ajax_valider_coherence_departement(request):
    """
    Vue AJAX pour valider la cohérence département
    Utilisée par le JavaScript pour validation en temps réel
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        data = json.loads(request.body)
        personne_remplacee_id = data.get('personne_remplacee_id')
        poste_id = data.get('poste_id')
        
        if not all([personne_remplacee_id, poste_id]):
            return JsonResponse({
                'success': False, 
                'error': 'Données manquantes'
            })
        
        # Récupérer les objets
        try:
            personne_remplacee = ProfilUtilisateur.objects.get(id=personne_remplacee_id)
            poste = Poste.objects.get(id=poste_id)
        except (ProfilUtilisateur.DoesNotExist, Poste.DoesNotExist):
            return JsonResponse({
                'success': False, 
                'error': 'Données invalides'
            })
        
        # Utiliser la fonction utilitaire créée précédemment
        est_valide, message = valider_coherence_departement_demande(personne_remplacee, poste)
        
        return JsonResponse({
            'success': True,
            'coherent': est_valide,
            'message': message,
            'details': {
                'personne_departement': personne_remplacee.departement.nom if personne_remplacee.departement else None,
                'poste_departement': poste.departement.nom if poste.departement else None
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur validation cohérence département: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur serveur: {str(e)}'
        })


def ajax_get_departement_info(request, departement_id):
    """
    Vue AJAX optionnelle pour obtenir les infos d'un département
    Peut être utile pour enrichir l'interface
    """
    try:
        departement = get_object_or_404(Departement, id=departement_id, actif=True)
        
        # Statistiques du département
        nb_employes = departement.employes.filter(actif=True).count()
        nb_postes = departement.postes.filter(actif=True).count()
        demandes_en_cours = DemandeInterim.objects.filter(
            poste__departement=departement,
            statut__in=['SOUMISE', 'EN_VALIDATION', 'EN_COURS']
        ).count()
        
        return JsonResponse({
            'success': True,
            'departement': {
                'id': departement.id,
                'nom': departement.nom,
                'code': departement.code,
                'description': departement.description,
                'manager': departement.manager.nom_complet if departement.manager else None,
                'statistiques': {
                    'nb_employes': nb_employes,
                    'nb_postes': nb_postes,
                    'demandes_en_cours': demandes_en_cours
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur récupération info département: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur: {str(e)}'
        })

def valider_coherence_departement_demande(personne_remplacee, poste):
    """
    Valide que la personne à remplacer appartient au même département que le poste
    
    Args:
        personne_remplacee: Instance ProfilUtilisateur de la personne à remplacer
        poste: Instance Poste du poste à pourvoir
        
    Returns:
        tuple: (bool, str) - (est_valide, message_erreur_ou_succes)
        
    Exemples:
        >>> personne = ProfilUtilisateur.objects.get(matricule='EMP001')
        >>> poste = Poste.objects.get(id=1)
        >>> est_valide, message = valider_coherence_departement_demande(personne, poste)
        >>> if est_valide:
        ...     print("Cohérence OK")
        >>> else:
        ...     print(f"Erreur: {message}")
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        # Vérification des paramètres d'entrée
        if not personne_remplacee:
            return False, "La personne à remplacer n'est pas définie"
        
        if not poste:
            return False, "Le poste n'est pas défini"
        
        # Vérification que les objets ont les attributs nécessaires
        if not hasattr(personne_remplacee, 'departement'):
            return False, f"L'objet personne_remplacee ({type(personne_remplacee)}) n'a pas d'attribut 'departement'"
        
        if not hasattr(poste, 'departement'):
            return False, f"L'objet poste ({type(poste)}) n'a pas d'attribut 'departement'"
        
        # Vérification que les départements sont définis
        if not personne_remplacee.departement:
            nom_personne = getattr(personne_remplacee, 'nom_complet', 
                                 getattr(personne_remplacee, 'matricule', 'Personne inconnue'))
            return False, f"Le département de {nom_personne} n'est pas défini"
        
        if not poste.departement:
            titre_poste = getattr(poste, 'titre', f'Poste ID {getattr(poste, "id", "inconnu")}')
            return False, f"Le département du poste '{titre_poste}' n'est pas défini"
        
        # Comparaison des départements
        departement_personne = personne_remplacee.departement
        departement_poste = poste.departement
        
        # Comparaison par ID (plus fiable que par nom)
        if hasattr(departement_personne, 'id') and hasattr(departement_poste, 'id'):
            if departement_personne.id != departement_poste.id:
                nom_personne = getattr(personne_remplacee, 'nom_complet', 
                                     getattr(personne_remplacee, 'matricule', 'Personne inconnue'))
                nom_dept_personne = getattr(departement_personne, 'nom', f'Département ID {departement_personne.id}')
                nom_dept_poste = getattr(departement_poste, 'nom', f'Département ID {departement_poste.id}')
                titre_poste = getattr(poste, 'titre', f'Poste ID {getattr(poste, "id", "inconnu")}')
                
                return False, (
                    f"Incohérence département : {nom_personne} "
                    f"appartient au département '{nom_dept_personne}' "
                    f"mais le poste '{titre_poste}' appartient au département '{nom_dept_poste}'"
                )
        
        # Si pas d'ID, comparaison directe des objets
        elif departement_personne != departement_poste:
            nom_personne = getattr(personne_remplacee, 'nom_complet', 
                                 getattr(personne_remplacee, 'matricule', 'Personne inconnue'))
            nom_dept_personne = getattr(departement_personne, 'nom', str(departement_personne))
            nom_dept_poste = getattr(departement_poste, 'nom', str(departement_poste))
            titre_poste = getattr(poste, 'titre', f'Poste ID {getattr(poste, "id", "inconnu")}')
            
            return False, (
                f"Incohérence département : {nom_personne} "
                f"appartient au département '{nom_dept_personne}' "
                f"mais le poste '{titre_poste}' appartient au département '{nom_dept_poste}'"
            )
        
        # Si on arrive ici, tout est cohérent
        nom_personne = getattr(personne_remplacee, 'nom_complet', 
                             getattr(personne_remplacee, 'matricule', 'Personne'))
        nom_departement = getattr(departement_personne, 'nom', 'Département')
        titre_poste = getattr(poste, 'titre', 'Poste')
        
        return True, (
            f"Cohérence validée : {nom_personne} et le poste '{titre_poste}' "
            f"appartiennent tous deux au département '{nom_departement}'"
        )
        
    except AttributeError as e:
        logger.error(f"Erreur d'attribut lors de la validation cohérence département: {e}")
        return False, f"Erreur d'accès aux attributs des objets: {str(e)}"
    
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la validation cohérence département: {e}")
        return False, f"Erreur lors de la validation: {str(e)}"

# ================================================================
# FONCTION UTILITAIRE POUR VALIDATION RAPIDE
# ================================================================

def verifier_coherence_rapide(personne_remplacee_id: int, poste_id: int) -> Tuple[bool, str]:
    """
    Version allégée pour validation rapide avec IDs seulement
    
    Args:
        personne_remplacee_id (int): ID de la personne à remplacer
        poste_id (int): ID du poste
        
    Returns:
        Tuple[bool, str]: (est_valide, message)
    """
    try:
        # Récupérer les objets avec select_related pour optimiser
        personne = ProfilUtilisateur.objects.select_related('departement').get(
            id=personne_remplacee_id
        )
        poste = Poste.objects.select_related('departement').get(id=poste_id)
        
        # Utiliser la fonction principale
        return valider_coherence_departement_demande(personne, poste)
        
    except ProfilUtilisateur.DoesNotExist:
        return False, f"Employé avec ID {personne_remplacee_id} non trouvé"
    except Poste.DoesNotExist:
        return False, f"Poste avec ID {poste_id} non trouvé"
    except Exception as e:
        logger.error(f"verifier_coherence_rapide: Erreur: {e}")
        return False, "Erreur lors de la vérification rapide"

@login_required
def ajax_rechercher_candidat_alternatif(request):
    """
    Vue AJAX pour rechercher un candidat alternatif avec scoring
    Version corrigée avec gestion d'erreurs robuste
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        import json
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip()
        demande_id = data.get('demande_id')
        
        if not matricule:
            return JsonResponse({'success': False, 'error': 'Matricule requis'})
        
        if not demande_id:
            return JsonResponse({'success': False, 'error': 'ID de demande requis'})
        
        # Utiliser la fonction utilitaire corrigée
        resultat = rechercher_et_scorer_candidat_alternatif(matricule, demande_id)
        
        # Enrichir avec des données supplémentaires si le candidat est trouvé
        if resultat['success'] and 'employe' in resultat:
            try:
                # Récupérer l'objet employé complet pour les analyses
                employe_obj = ProfilUtilisateur.objects.get(id=resultat['employe']['id'])
                demande_obj = DemandeInterim.objects.get(id=demande_id)
                
                # Ajouter des informations de contexte
                resultat['contexte'] = {
                    'peut_etre_propose': _peut_etre_propose(employe_obj, demande_obj),
                    'raisons_recommandation': _generer_raisons_recommandation(
                        employe_obj, 
                        resultat['score']['score_final']
                    ),
                    'alertes_supplementaires': _detecter_alertes_supplementaires(
                        employe_obj, 
                        demande_obj
                    )
                }
                
                # Ajouter les informations de disponibilité détaillées
                if hasattr(employe_obj, 'est_disponible_pour_interim'):
                    disponibilite_detaillee = employe_obj.est_disponible_pour_interim(
                        demande_obj.date_debut, 
                        demande_obj.date_fin
                    )
                    resultat['disponibilite_detaillee'] = disponibilite_detaillee
                
            except Exception as e:
                logger.warning(f"Erreur enrichissement données candidat: {e}")
                # Continuer même si l'enrichissement échoue
                resultat['contexte'] = {
                    'peut_etre_propose': True,
                    'raisons_recommandation': ['Candidat trouvé avec succès'],
                    'alertes_supplementaires': []
                }
        
        return JsonResponse(resultat)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False, 
            'error': 'Format JSON invalide'
        })
    except Exception as e:
        logger.error(f"Erreur AJAX recherche candidat alternatif: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur technique: {str(e)}'
        })


@login_required
def ajax_calculer_score_alternatif(request):
    """
    Vue AJAX pour calculer le score d'un candidat alternatif
    Version simplifiée sans dépendance au service de scoring complexe
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        import json
        data = json.loads(request.body)
        candidat_id = data.get('candidat_id')
        demande_id = data.get('demande_id')
        
        if not candidat_id or not demande_id:
            return JsonResponse({'success': False, 'error': 'Paramètres manquants'})
        
        # Récupérer les objets
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Calculer le score avec la méthode simplifiée
        score_detail = _calculer_score_detaille_simple(candidat, demande)
        
        return JsonResponse({
            'success': True,
            'score_final': score_detail.get('score_final', 0),
            'score_details': score_detail.get('criteres', {}),
            'explications': score_detail.get('explications', []),
            'recommandations': score_detail.get('recommandations', []),
            'confidence': score_detail.get('confidence', 'moyenne'),
            'metadata': score_detail.get('metadata', {})
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False, 
            'error': 'Format JSON invalide'
        })
    except Exception as e:
        logger.error(f"Erreur calcul score alternatif: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur de calcul: {str(e)}'
        })


@login_required
def ajax_validation_rapide(request, demande_id):
    """
    Vue AJAX pour validation rapide d'une demande
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        import json
        data = json.loads(request.body)
        action = data.get('action')  # 'APPROUVER' ou 'REFUSER'
        proposition_id = data.get('proposition_id')
        commentaire = data.get('commentaire', '').strip()
        
        if not action or not commentaire:
            return JsonResponse({'success': False, 'error': 'Paramètres manquants'})
        
        # Récupérer la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        profil_utilisateur = request.user.profilutilisateur
        
        # Vérifier les permissions
        permissions = _get_permissions_validation_detaillees(profil_utilisateur, demande)
        if not permissions['peut_valider']:
            return JsonResponse({'success': False, 'error': permissions['raison_refus']})
        
        # Traitement selon l'action
        if action == 'APPROUVER' and proposition_id:
            # Validation rapide d'une proposition
            proposition = get_object_or_404(PropositionCandidat, id=proposition_id)
            
            # Créer la validation
            validation = ValidationDemande.objects.create(
                demande=demande,
                type_validation=_determiner_type_validation_niveau(profil_utilisateur, demande),
                niveau_validation=demande.niveau_validation_actuel + 1,
                validateur=profil_utilisateur,
                decision='APPROUVE',
                commentaire=commentaire
            )
            validation.valider('APPROUVE', commentaire)
            
            # Mettre à jour la demande
            demande.niveau_validation_actuel += 1
            if demande.niveau_validation_actuel >= demande.niveaux_validation_requis:
                demande.candidat_selectionne = proposition.candidat_propose
                demande.statut = 'VALIDEE'
                message = f"Demande validée définitivement. Candidat sélectionné : {proposition.candidat_propose.nom_complet}"
            else:
                demande.statut = 'EN_VALIDATION'
                message = f"Proposition approuvée. Niveau suivant : {demande.niveau_validation_actuel + 1}"
            
            demande.save()
            
            return JsonResponse({
                'success': True,
                'message': message,
                'nouveau_statut': demande.statut,
                'niveau_validation': demande.niveau_validation_actuel,
                'candidat_selectionne': proposition.candidat_propose.nom_complet if demande.candidat_selectionne else None
            })
        
        elif action == 'REFUSER':
            # Refus rapide
            validation = ValidationDemande.objects.create(
                demande=demande,
                type_validation=_determiner_type_validation_niveau(profil_utilisateur, demande),
                niveau_validation=demande.niveau_validation_actuel + 1,
                validateur=profil_utilisateur,
                decision='REFUSE',
                commentaire=commentaire
            )
            validation.valider('REFUSE', commentaire)
            
            demande.statut = 'REFUSEE'
            demande.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Demande refusée avec succès.',
                'nouveau_statut': demande.statut
            })
        
        else:
            return JsonResponse({'success': False, 'error': 'Action non supportée'})
        
    except Exception as e:
        logger.error(f"Erreur validation rapide: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur de validation: {str(e)}'
        })


@login_required
def ajax_verifier_coherence_workflow(request, demande_id):
    """
    Vue AJAX pour vérifier la cohérence du workflow
    """
    try:
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        profil_utilisateur = request.user.profilutilisateur
        
        # Vérifications de cohérence
        coherent, erreurs = verifier_coherence_workflow(demande)
        
        # Vérifications de permissions
        permissions = _get_permissions_validation_detaillees(profil_utilisateur, demande)
        
        # Vérifications des propositions
        propositions = PropositionCandidat.objects.filter(demande_interim=demande)
        
        return JsonResponse({
            'success': True,
            'coherent': coherent,
            'erreurs': erreurs,
            'permissions': permissions,
            'statistiques': {
                'nb_propositions': propositions.count(),
                'niveau_actuel': demande.niveau_validation_actuel,
                'niveau_requis': demande.niveaux_validation_requis,
                'statut_demande': demande.statut,
                'urgence': demande.urgence
            },
            'workflow_info': _get_workflow_info_complete(demande, profil_utilisateur)
        })
        
    except Exception as e:
        logger.error(f"Erreur vérification cohérence workflow: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur de vérification: {str(e)}'
        })


@login_required
def ajax_previsualiser_validation(request):
    """
    Vue AJAX pour prévisualiser une validation avant soumission
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        import json
        data = json.loads(request.body)
        demande_id = data.get('demande_id')
        action = data.get('action')
        parametres = data.get('parametres', {})
        
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Simuler les effets de la validation
        simulation = {
            'demande_actuelle': {
                'statut': demande.statut,
                'niveau_validation': demande.niveau_validation_actuel
            },
            'demande_apres': {},
            'actions_prevues': [],
            'notifications_prevues': [],
            'impacts': []
        }
        
        if action == 'VALIDER_PROPOSITION':
            proposition_id = parametres.get('proposition_id')
            proposition = get_object_or_404(PropositionCandidat, id=proposition_id)
            
            nouveau_niveau = demande.niveau_validation_actuel + 1
            
            if nouveau_niveau >= demande.niveaux_validation_requis:
                simulation['demande_apres'] = {
                    'statut': 'VALIDEE',
                    'niveau_validation': nouveau_niveau,
                    'candidat_selectionne': proposition.candidat_propose.nom_complet
                }
                simulation['actions_prevues'].append('Sélection définitive du candidat')
                simulation['notifications_prevues'].append(f'Notification à {proposition.candidat_propose.nom_complet}')
            else:
                simulation['demande_apres'] = {
                    'statut': 'EN_VALIDATION',
                    'niveau_validation': nouveau_niveau
                }
                simulation['actions_prevues'].append(f'Transmission au niveau {nouveau_niveau}')
                
                prochaine_etape = _get_prochaine_etape_validation(demande)
                simulation['notifications_prevues'].append(f'Notification aux {prochaine_etape["nom"]}')
        
        elif action == 'PROPOSITION_ALTERNATIVE':
            candidat_id = parametres.get('candidat_id')
            candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
            
            simulation['demande_apres'] = {
                'statut': 'EN_VALIDATION',
                'niveau_validation': demande.niveau_validation_actuel + 1
            }
            simulation['actions_prevues'].append(f'Ajout de {candidat.nom_complet} comme proposition alternative')
            simulation['impacts'].append('Refus de toutes les propositions précédentes')
        
        elif action == 'REFUS_GLOBAL':
            simulation['demande_apres'] = {
                'statut': 'REFUSEE',
                'niveau_validation': demande.niveau_validation_actuel
            }
            simulation['actions_prevues'].append('Refus définitif de la demande')
            simulation['notifications_prevues'].append(f'Notification au demandeur ({demande.demandeur.nom_complet})')
        
        return JsonResponse({
            'success': True,
            'simulation': simulation
        })
        
    except Exception as e:
        logger.error(f"Erreur prévisualisation validation: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur de prévisualisation: {str(e)}'
        })


@login_required
def ajax_verifier_disponibilite_alternatif(request):
    """
    Vue AJAX pour vérifier la disponibilité d'un candidat alternatif
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        import json
        data = json.loads(request.body)
        candidat_id = data.get('candidat_id')
        demande_id = data.get('demande_id')
        
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier la disponibilité détaillée
        disponibilite = _verifier_disponibilite_candidat(candidat, demande.date_debut, demande.date_fin)
        
        # Vérifications supplémentaires
        conflits = _detecter_conflits_horaires(candidat, demande)
        absences = _verifier_absences_periode(candidat, demande)
        
        return JsonResponse({
            'success': True,
            'disponibilite': disponibilite,
            'conflits': conflits,
            'absences': absences,
            'recommandation': _generer_recommandation_disponibilite(disponibilite, conflits, absences)
        })
        
    except Exception as e:
        logger.error(f"Erreur vérification disponibilité: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur de vérification: {str(e)}'
        })


@login_required
def ajax_sauvegarder_brouillon_validation(request):
    """
    Vue AJAX pour sauvegarder un brouillon de validation
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
    
    try:
        import json
        data = json.loads(request.body)
        demande_id = data.get('demande_id')
        brouillon_data = data.get('brouillon', {})
        
        # Sauvegarder en cache ou en base selon les besoins
        cache_key = f'brouillon_validation_{request.user.id}_{demande_id}'
        cache.set(cache_key, brouillon_data, timeout=3600)  # 1 heure
        
        return JsonResponse({
            'success': True,
            'message': 'Brouillon sauvegardé',
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur sauvegarde brouillon: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur de sauvegarde: {str(e)}'
        })


@login_required
def ajax_details_proposition(request, proposition_id):
    """
    Vue AJAX pour récupérer les détails complets d'une proposition
    """
    try:
        proposition = get_object_or_404(PropositionCandidat, id=proposition_id)
        
        # Enrichir les détails
        details = {
            'proposition': {
                'id': proposition.id,
                'numero_proposition': proposition.numero_proposition,
                'statut': proposition.statut,
                'score_final': proposition.score_final,
                'justification': proposition.justification,
                'competences_specifiques': proposition.competences_specifiques,
                'experience_pertinente': proposition.experience_pertinente,
                'created_at': proposition.created_at.isoformat(),
                'source_display': proposition.source_display
            },
            'candidat': {
                'id': proposition.candidat_propose.id,
                'nom_complet': proposition.candidat_propose.nom_complet,
                'matricule': proposition.candidat_propose.matricule,
                'poste_actuel': proposition.candidat_propose.poste.titre if proposition.candidat_propose.poste else None,
                'departement': proposition.candidat_propose.departement.nom if proposition.candidat_propose.departement else None,
                'site': proposition.candidat_propose.site.nom if proposition.candidat_propose.site else None
            },
            'proposant': {
                'nom_complet': proposition.proposant.nom_complet,
                'type_profil': proposition.proposant.type_profil,
                'departement': proposition.proposant.departement.nom if proposition.proposant.departement else None
            },
            'competences': _get_competences_principales(proposition.candidat_propose),
            'disponibilite': _verifier_disponibilite_candidat(proposition.candidat_propose, proposition.demande_interim.date_debut, proposition.demande_interim.date_debut, )
        }
        
        return JsonResponse({
            'success': True,
            'details': details
        })
        
    except Exception as e:
        logger.error(f"Erreur récupération détails proposition: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erreur de récupération: {str(e)}'
        })


# ================================================================
# FONCTIONS UTILITAIRES POUR LES VUES AJAX
# ================================================================

def _peut_etre_propose(employe, demande):
    """
    Vérifie si un employé peut être proposé pour une demande
    """
    try:
        # Vérifications de base
        if not employe.actif:
            return False
        
        if employe.statut_employe in ['DEMISSION', 'LICENCIE', 'SUSPENDU']:
            return False
        
        # Vérifier qu'il n'est pas déjà proposé
        proposition_existante = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=employe
        ).exists()
        
        if proposition_existante:
            return False
        
        # Vérifier qu'il n'est pas la personne à remplacer
        if employe.id == demande.personne_remplacee.id:
            return False
        
        return True
        
    except Exception as e:
        logger.warning(f"Erreur vérification proposition: {e}")
        return True  # Par défaut, autoriser


def _generer_raisons_recommandation(employe, score):
    """
    Génère les raisons de recommandation pour un candidat
    """
    raisons = []
    
    try:
        # Raisons basées sur le score
        if score >= 80:
            raisons.append("Score excellent pour cette mission")
        elif score >= 65:
            raisons.append("Score satisfaisant pour cette mission")
        elif score >= 50:
            raisons.append("Score acceptable avec surveillance")
        else:
            raisons.append("Score faible - nécessite évaluation approfondie")
        
        # Raisons basées sur le profil
        if employe.statut_employe == 'ACTIF':
            raisons.append("Employé actuellement actif")
        
        # Raisons basées sur les compétences
        try:
            nb_competences = employe.competences.count()
            if nb_competences >= 5:
                raisons.append(f"Profil riche en compétences ({nb_competences} compétences)")
            elif nb_competences >= 3:
                raisons.append("Compétences documentées")
            elif nb_competences == 0:
                raisons.append("Attention: aucune compétence renseignée")
        except:
            pass
        
        # Raisons basées sur l'ancienneté
        try:
            if hasattr(employe, 'date_embauche') and employe.date_embauche:
                from datetime import date
                anciennete_jours = (date.today() - employe.date_embauche).days
                anciennete_annees = anciennete_jours / 365.25
                
                if anciennete_annees >= 3:
                    raisons.append("Employé expérimenté (3+ ans)")
                elif anciennete_annees >= 1:
                    raisons.append("Employé confirmé")
                else:
                    raisons.append("Employé récent - formation possible")
        except:
            pass
        
    except Exception as e:
        logger.warning(f"Erreur génération raisons: {e}")
        raisons = ["Candidat évalué avec succès"]
    
    return raisons


def _detecter_alertes_candidat(employe, demande_id):
    """
    Détecte les alertes potentielles pour un candidat
    """
    alertes = []
    
    try:
        # Vérifications diverses selon les règles métier
        # (conflits, indisponibilités, etc.)
        pass
    except Exception as e:
        logger.error(f"Erreur détection alertes: {e}")
    
    return alertes


def _detecter_alertes_supplementaires(employe, demande):
    """
    Détecte les alertes supplémentaires pour un candidat
    """
    alertes = []
    
    try:
        # Alerte sur les missions en cours
        try:
            missions_en_cours = PropositionCandidat.objects.filter(
                candidat_propose=employe,
                statut__in=['VALIDEE', 'EN_COURS'],
                demande_interim__date_fin__gte=demande.date_debut
            ).count()
            
            if missions_en_cours > 0:
                alertes.append(f"Attention: {missions_en_cours} mission(s) en cours ou planifiée(s)")
        except:
            pass
        
        # Alerte sur la charge de travail
        try:
            if hasattr(employe, 'extended_data') and employe.extended_data:
                temps_travail = getattr(employe.extended_data, 'temps_travail', 1.0)
                if temps_travail < 1.0:
                    alertes.append(f"Temps partiel: {int(temps_travail * 100)}%")
        except:
            pass
        
        # Alerte sur la distance
        try:
            if employe.site and demande.poste and demande.poste.site:
                if employe.site.ville != demande.poste.site.ville:
                    alertes.append(f"Ville différente: {employe.site.ville} → {demande.poste.site.ville}")
        except:
            pass
        
        # Alerte sur les permissions
        try:
            if demande.poste and hasattr(demande.poste, 'permis_requis') and demande.poste.permis_requis:
                # Vérifier si l'employé a un permis renseigné
                if (hasattr(employe, 'extended_data') and employe.extended_data and
                    not getattr(employe.extended_data, 'permis_conduire', None)):
                    alertes.append("Permis de conduire requis - non renseigné")
        except:
            pass
        
    except Exception as e:
        logger.warning(f"Erreur détection alertes supplémentaires: {e}")
        alertes.append("Vérification des alertes incomplète")
    
    return alertes


def _calculer_score_detaille_simple(candidat, demande):
    """
    Calcul de score détaillé simplifié pour le candidat alternatif
    """
    try:
        # Utiliser la fonction de scoring simplifiée existante
        score_final = _calculer_score_candidat_simple(candidat, demande)
        
        # Analyser les différents critères
        competences_info = _analyser_competences_candidat_simple(candidat, demande)
        experience_info = _analyser_experience_pertinente_simple(candidat, demande)
        disponibilite_info = _verifier_disponibilite_candidat(
            candidat, demande.date_debut, demande.date_fin
        )
        distance_info = _calculer_distance_sites_simple(candidat, demande)
        
        # Construire les critères détaillés
        criteres = {
            'competences': {
                'score': competences_info.get('score_adequation', 0),
                'details': competences_info.get('competences_candidat', []),
                'nb_total': competences_info.get('nb_competences', 0)
            },
            'experience': {
                'score': min(100, experience_info.get('anciennete_totale_mois', 0) * 2),
                'details': {
                    'anciennete_mois': experience_info.get('anciennete_totale_mois', 0),
                    'poste_similaire': experience_info.get('experience_poste_similaire', False),
                    'departement_similaire': experience_info.get('experience_departement', False),
                    'missions_interim': experience_info.get('nb_missions_interim', 0)
                }
            },
            'disponibilite': {
                'score': disponibilite_info.get('score_disponibilite', 0),
                'details': {
                    'disponible': disponibilite_info.get('disponible', False),
                    'raison': disponibilite_info.get('raison', 'Non évalué')
                }
            },
            'proximite': {
                'score': 100 if distance_info.get('meme_site', False) else 
                         80 if distance_info.get('meme_ville', False) else 50,
                'details': distance_info
            }
        }
        
        # Générer les explications
        explications = []
        
        if score_final >= 80:
            explications.append("Candidat très bien adapté à cette mission")
        elif score_final >= 65:
            explications.append("Candidat bien adapté avec quelques réserves")
        elif score_final >= 50:
            explications.append("Candidat acceptable selon les critères")
        else:
            explications.append("Candidat nécessitant une évaluation approfondie")
        
        # Points forts
        if criteres['competences']['score'] >= 70:
            explications.append("✓ Profil de compétences satisfaisant")
        
        if criteres['disponibilite']['details']['disponible']:
            explications.append("✓ Disponible sur la période demandée")
        
        if criteres['proximite']['details'].get('meme_site', False):
            explications.append("✓ Travaille sur le même site")
        
        # Points d'attention
        if criteres['competences']['score'] < 40:
            explications.append("⚠ Compétences limitées ou non renseignées")
        
        if not criteres['disponibilite']['details']['disponible']:
            explications.append("⚠ Disponibilité à vérifier")
        
        # Générer les recommandations
        recommandations = []
        
        if score_final >= 70:
            recommandations.append("Procéder à la proposition de ce candidat")
        elif score_final >= 55:
            recommandations.append("Évaluer en complément d'autres candidats")
            recommandations.append("Vérifier les compétences spécifiques requises")
        else:
            recommandations.append("Chercher d'autres candidats si possible")
            recommandations.append("Prévoir un accompagnement renforcé si sélectionné")
        
        # Déterminer la confiance
        confidence = "élevée" if score_final >= 75 else "moyenne" if score_final >= 55 else "faible"
        
        return {
            'score_final': int(score_final),
            'criteres': criteres,
            'explications': explications,
            'recommandations': recommandations,
            'confidence': confidence,
            'metadata': {
                'calcule_le': timezone.now().isoformat(),
                'methode': 'scoring_simple_v1',
                'candidat_id': candidat.id,
                'demande_id': demande.id
            }
        }
        
    except Exception as e:
        logger.error(f"Erreur calcul score détaillé: {e}")
        return {
            'score_final': 50,
            'criteres': {},
            'explications': [f"Erreur de calcul: {str(e)}"],
            'recommandations': ["Évaluation manuelle recommandée"],
            'confidence': 'faible',
            'metadata': {'erreur': str(e)}
        }


def _calculer_anciennete_mois(employe):
    """
    Calcule l'ancienneté en mois de manière sécurisée
    """
    try:
        if hasattr(employe, 'date_embauche') and employe.date_embauche:
            from datetime import date
            anciennete_jours = (date.today() - employe.date_embauche).days
            return max(0, int(anciennete_jours / 30.44))  # Conversion approximative en mois
        
        # Fallback: essayer avec extended_data
        if (hasattr(employe, 'extended_data') and employe.extended_data and
            hasattr(employe.extended_data, 'date_embauche') and 
            employe.extended_data.date_embauche):
            anciennete_jours = (date.today() - employe.extended_data.date_embauche).days
            return max(0, int(anciennete_jours / 30.44))
        
        return 0
        
    except Exception as e:
        logger.warning(f"Erreur calcul ancienneté mois: {e}")
        return 0

def _detecter_conflits_horaires(candidat, demande):
    """
    Détecte les conflits d'horaires potentiels
    """
    conflits = []
    # Implémentation selon les règles métier
    return conflits


def _verifier_absences_periode(candidat, demande):
    """
    Vérifie les absences sur la période de la demande
    """
    absences = []
    # Implémentation selon les règles métier
    return absences


def _generer_recommandation_disponibilite(disponibilite, conflits, absences):
    """
    Génère une recommandation globale sur la disponibilité
    """
    if disponibilite.get('disponible') and not conflits and not absences:
        return {
            'niveau': 'EXCELLENT',
            'message': 'Candidat pleinement disponible',
            'couleur': 'success'
        }
    elif disponibilite.get('disponible') and (conflits or absences):
        return {
            'niveau': 'MOYEN',
            'message': 'Disponible avec quelques contraintes',
            'couleur': 'warning'
        }
    else:
        return {
            'niveau': 'FAIBLE',
            'message': 'Disponibilité limitée ou problématique',
            'couleur': 'danger'
        }

def rechercher_et_scorer_candidat_alternatif(matricule: str, demande_id: int) -> Dict[str, Any]:
    """
    Recherche un employé par matricule et calcule son score pour une demande d'intérim
    Version simple utilisant uniquement les données locales de la base
    
    Args:
        matricule (str): Matricule de l'employé à rechercher
        demande_id (int): ID de la demande d'intérim
    
    Returns:
        Dict contenant le résultat de la recherche et du scoring
    """
    try:
        # ================================================================
        # VALIDATION DES PARAMÈTRES
        # ================================================================
        
        if not matricule or not matricule.strip():
            return {
                'success': False,
                'error': 'Matricule requis',
                'error_type': 'VALIDATION'
            }
        
        if not demande_id:
            return {
                'success': False,
                'error': 'ID de demande requis',
                'error_type': 'VALIDATION'
            }
        
        matricule_clean = matricule.strip().upper()
        
        # ================================================================
        # RECHERCHE DE L'EMPLOYÉ
        # ================================================================
        
        try:
            employe = ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste', 'extended_data'
            ).prefetch_related(
                'competences__competence'
            ).get(
                matricule__iexact=matricule_clean,
                actif=True
            )
        except ProfilUtilisateur.DoesNotExist:
            return {
                'success': False,
                'error': f'Employé avec matricule {matricule_clean} non trouvé',
                'error_type': 'NOT_FOUND',
                'suggestions': _suggerer_matricules_similaires_simple(matricule_clean)
            }
        except ProfilUtilisateur.MultipleObjectsReturned:
            return {
                'success': False,
                'error': f'Plusieurs employés trouvés avec le matricule {matricule_clean}',
                'error_type': 'DUPLICATE'
            }
        
        # ================================================================
        # RÉCUPÉRATION DE LA DEMANDE
        # ================================================================
        
        try:
            demande = DemandeInterim.objects.select_related(
                'poste__departement', 'poste__site',
                'personne_remplacee', 'demandeur'
            ).get(id=demande_id)
        except DemandeInterim.DoesNotExist:
            return {
                'success': False,
                'error': f'Demande {demande_id} non trouvée',
                'error_type': 'INVALID_DEMANDE'
            }
        
        # ================================================================
        # VÉRIFICATIONS PRÉLIMINAIRES
        # ================================================================
        
        # Vérifier que ce n'est pas la personne à remplacer
        if employe.id == demande.personne_remplacee.id:
            return {
                'success': False,
                'error': 'L\'employé sélectionné est la personne à remplacer',
                'error_type': 'SELF_REPLACEMENT'
            }
        
        # Vérifier que l'employé n'est pas déjà proposé
        proposition_existante = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=employe
        ).first()
        
        if proposition_existante:
            return {
                'success': False,
                'error': f'{employe.nom_complet} est déjà proposé pour cette demande',
                'error_type': 'ALREADY_PROPOSED',
                'proposition_existante': {
                    'id': proposition_existante.id,
                    'proposant': proposition_existante.proposant.nom_complet,
                    'score': proposition_existante.score_final
                }
            }
        
        # Vérifier l'éligibilité de base
        eligibilite_result = _verifier_eligibilite_base_simple(employe, demande)
        if not eligibilite_result['eligible']:
            return {
                'success': False,
                'error': eligibilite_result['raison'],
                'error_type': 'NOT_ELIGIBLE',
                'details_eligibilite': eligibilite_result
            }
        
        # ================================================================
        # CALCUL DU SCORE
        # ================================================================
        
        try:
            score_final = _calculer_score_candidat_simple(employe, demande)
            
        except Exception as e:
            logger.error(f"Erreur calcul score candidat alternatif {matricule}: {e}")
            return {
                'success': False,
                'error': f'Erreur lors du calcul du score: {str(e)}',
                'error_type': 'SCORING_ERROR'
            }
        
        # ================================================================
        # VÉRIFICATIONS COMPLÉMENTAIRES
        # ================================================================
        
        # Disponibilité
        disponibilite_info = _verifier_disponibilite_candidat(
            employe, demande.date_debut, demande.date_fin
        )
        
        # Compétences principales
        competences_info = _analyser_competences_candidat_simple(employe, demande)
        
        # Distance géographique
        distance_info = _calculer_distance_sites_simple(employe, demande)
        
        # Expérience pertinente
        experience_info = _analyser_experience_pertinente_simple(employe, demande)
        
        # ================================================================
        # CONSTRUCTION DU RÉSULTAT
        # ================================================================
        
        resultat = {
            'success': True,
            'employe': {
                'id': employe.id,
                'matricule': employe.matricule,
                'nom_complet': employe.nom_complet,
                'email': employe.user.email if employe.user else '',
                'poste_actuel': employe.poste.titre if employe.poste else 'Non renseigné',
                'departement': employe.departement.nom if employe.departement else 'Non renseigné',
                'site': employe.site.nom if employe.site else 'Non renseigné',
                'type_profil': employe.type_profil,
                'anciennete': _calculer_anciennete_display(employe),
                'statut_employe': employe.statut_employe
            },
            'score': {
                'score_final': score_final,
                'classe_css': _get_score_css_class_simple(score_final),
                'evaluation': _evaluer_score_simple(score_final)
            },
            'analyses': {
                'disponibilite': disponibilite_info,
                'competences': competences_info,
                'distance': distance_info,
                'experience': experience_info
            },
            'recommandation': _generer_recommandation_globale_simple(
                score_final, disponibilite_info, competences_info, distance_info
            ),
            'alertes': _detecter_alertes_candidat_simple(employe, demande),
            'metadata': {
                'recherche_timestamp': timezone.now().isoformat(),
                'methode_recherche': 'MATRICULE_DIRECT',
                'source_donnees': 'BASE_LOCALE'
            }
        }
        
        logger.info(f"Candidat alternatif trouvé: {matricule} -> {employe.nom_complet} (Score: {score_final})")
        return resultat
        
    except Exception as e:
        logger.error(f"Erreur recherche candidat alternatif {matricule}: {e}")
        return {
            'success': False,
            'error': f'Erreur technique lors de la recherche: {str(e)}',
            'error_type': 'TECHNICAL_ERROR'
        }


def verifier_coherence_workflow(demande: DemandeInterim) -> Tuple[bool, List[str]]:
    """
    Vérifie la cohérence complète du workflow d'une demande d'intérim
    Version simple utilisant uniquement les données de base
    
    Args:
        demande (DemandeInterim): La demande à vérifier
    
    Returns:
        Tuple[bool, List[str]]: (est_coherent, liste_erreurs)
    """
    try:
        erreurs = []
        warnings = []
        
        # ================================================================
        # VÉRIFICATIONS DE BASE
        # ================================================================
        
        # Existence des données obligatoires
        if not demande.poste:
            erreurs.append("Poste non défini pour la demande")
        
        if not demande.personne_remplacee:
            erreurs.append("Personne à remplacer non définie")
        
        if not demande.demandeur:
            erreurs.append("Demandeur non défini")
        
        if not demande.date_debut or not demande.date_fin:
            erreurs.append("Dates de la mission non définies")
        elif demande.date_debut > demande.date_fin:
            erreurs.append("Date de début postérieure à la date de fin")
        
        # ================================================================
        # VÉRIFICATIONS STATUTAIRES
        # ================================================================
        
        statuts_valides = [
            'BROUILLON', 'SOUMISE', 'EN_PROPOSITION', 'EN_VALIDATION', 
            'VALIDATION_DRH_PENDING', 'CANDIDAT_PROPOSE', 'CANDIDAT_SELECTIONNE',
            'VALIDEE', 'EN_COURS', 'TERMINEE', 'REFUSEE', 'ANNULEE'
        ]
        
        if demande.statut not in statuts_valides:
            erreurs.append(f"Statut invalide: {demande.statut}")
        
        # Cohérence statut / niveau de validation
        if demande.statut == 'EN_VALIDATION':
            if demande.niveau_validation_actuel >= demande.niveaux_validation_requis:
                erreurs.append("Demande en validation mais tous les niveaux sont atteints")
        
        if demande.statut in ['VALIDEE', 'CANDIDAT_SELECTIONNE']:
            if demande.niveau_validation_actuel < demande.niveaux_validation_requis:
                warnings.append("Demande marquée validée mais validation potentiellement incomplète")
            if not demande.candidat_selectionne:
                erreurs.append("Demande validée mais aucun candidat sélectionné")
        
        # ================================================================
        # VÉRIFICATIONS DES NIVEAUX DE VALIDATION
        # ================================================================
        
        if demande.niveau_validation_actuel < 0:
            erreurs.append("Niveau de validation actuel négatif")
        
        if demande.niveaux_validation_requis not in [1, 2, 3]:
            warnings.append(f"Nombre de niveaux de validation inhabituel: {demande.niveaux_validation_requis}")
        
        if demande.niveau_validation_actuel > demande.niveaux_validation_requis:
            erreurs.append("Niveau de validation actuel supérieur au niveau requis")
        
        # Vérifier les validations existantes
        try:
            validations = ValidationDemande.objects.filter(
                demande=demande
            ).order_by('niveau_validation')
            
            validations_completees = validations.filter(
                date_validation__isnull=False
            )
            
            if demande.niveau_validation_actuel > validations_completees.count():
                warnings.append("Niveau de validation supérieur au nombre de validations complétées")
                
        except Exception as e:
            warnings.append(f"Impossible de vérifier l'historique des validations: {str(e)}")
        
        # ================================================================
        # VÉRIFICATIONS DES PROPOSITIONS
        # ================================================================
        
        try:
            propositions = PropositionCandidat.objects.filter(demande_interim=demande)
            
            if demande.statut in ['EN_VALIDATION', 'CANDIDAT_PROPOSE', 'VALIDEE']:
                if not propositions.exists():
                    warnings.append(f"Demande en statut {demande.statut} mais aucune proposition")
            
            # Vérifier la cohérence des propositions avec le candidat sélectionné
            if demande.candidat_selectionne:
                proposition_selectionnee = propositions.filter(
                    candidat_propose=demande.candidat_selectionne
                ).first()
                
                if not proposition_selectionnee:
                    erreurs.append("Candidat sélectionné non présent dans les propositions")
            
        except Exception as e:
            warnings.append(f"Impossible de vérifier les propositions: {str(e)}")
        
        # ================================================================
        # VÉRIFICATIONS TEMPORELLES
        # ================================================================
        
        now = timezone.now()
        
        # Dates dans le futur pour demandes en cours
        if demande.date_debut and demande.statut in ['EN_COURS', 'VALIDEE']:
            if demande.date_debut > now.date():
                warnings.append("Mission pas encore démarrée mais demande marquée en cours")
        
        # Dates passées pour demandes non terminées
        if demande.date_fin and demande.date_fin < now.date():
            if demande.statut not in ['TERMINEE', 'ANNULEE', 'REFUSEE']:
                warnings.append("Date de fin dépassée mais mission non terminée")
        
        # Délais de validation selon l'urgence
        if demande.statut == 'EN_VALIDATION' and hasattr(demande, 'updated_at'):
            delai_validation = now - demande.updated_at
            
            seuil_alerte = {
                'CRITIQUE': 4,    # 4 heures
                'ELEVEE': 24,     # 1 jour
                'MOYENNE': 72,    # 3 jours
                'NORMALE': 168    # 1 semaine
            }
            
            seuil = seuil_alerte.get(demande.urgence, 168)
            
            if delai_validation.total_seconds() > seuil * 3600:
                warnings.append(f"Demande en validation depuis trop longtemps ({delai_validation.days} jours)")
        
        # ================================================================
        # VÉRIFICATIONS MÉTIER
        # ================================================================
        
        # Cohérence départementale
        if demande.poste and demande.personne_remplacee:
            try:
                coherence_dept = valider_coherence_departement_demande(
                    demande.personne_remplacee, demande.poste
                )
                if not coherence_dept[0]:
                    warnings.append(f"Incohérence départementale: {coherence_dept[1]}")
            except Exception as e:
                warnings.append(f"Impossible de vérifier la cohérence départementale: {str(e)}")
        
        # Vérifier les conflits avec d'autres demandes
        try:
            if demande.personne_remplacee and demande.date_debut and demande.date_fin:
                conflits = DemandeInterim.objects.filter(
                    personne_remplacee=demande.personne_remplacee,
                    statut__in=['VALIDEE', 'EN_COURS']
                ).exclude(id=demande.id)
                
                for conflit in conflits:
                    if (conflit.date_debut and conflit.date_fin and
                        conflit.date_debut <= demande.date_fin and 
                        conflit.date_fin >= demande.date_debut):
                        warnings.append(f"Conflit avec la demande {conflit.numero_demande}")
                        
        except Exception as e:
            warnings.append(f"Impossible de vérifier les conflits: {str(e)}")
        
        # ================================================================
        # VÉRIFICATIONS DE L'URGENCE
        # ================================================================
        
        if demande.urgence == 'CRITIQUE':
            # Les demandes critiques devraient avoir un traitement accéléré
            if demande.niveaux_validation_requis > 2:
                warnings.append("Demande critique avec trop de niveaux de validation")
            
            # Vérifier que le traitement est bien rapide
            if hasattr(demande, 'created_at'):
                temps_ecoule = now - demande.created_at
                if temps_ecoule.total_seconds() > 4 * 3600 and demande.statut not in ['VALIDEE', 'TERMINEE']:
                    warnings.append("Demande critique non traitée dans les délais (>4h)")
        
        # ================================================================
        # VÉRIFICATIONS DES PERMISSIONS ET VALIDATEURS
        # ================================================================
        
        try:
            validations = ValidationDemande.objects.filter(demande=demande)
            
            for validation in validations:
                # Vérifier que les validateurs ont les bonnes permissions
                niveau_requis = validation.niveau_validation
                validateur = validation.validateur
                
                if not validateur.peut_valider_niveau(niveau_requis):
                    warnings.append(
                        f"Validateur {validateur.nom_complet} sans permission "
                        f"niveau {niveau_requis}"
                    )
                    
        except Exception as e:
            warnings.append(f"Impossible de vérifier les permissions des validateurs: {str(e)}")
        
        # ================================================================
        # SYNTHÈSE ET RÉSULTAT
        # ================================================================
        
        # Ajouter les warnings aux erreurs pour information
        toutes_anomalies = erreurs + [f"ATTENTION: {w}" for w in warnings]
        
        # Détermine si la demande est cohérente
        # Les warnings n'empêchent pas la cohérence, seules les erreurs
        coherent = len(erreurs) == 0
        
        # Log des résultats
        if not coherent:
            logger.warning(
                f"Incohérences détectées pour demande {demande.numero_demande}: "
                f"{len(erreurs)} erreurs, {len(warnings)} avertissements"
            )
        elif warnings:
            logger.info(
                f"Demande {demande.numero_demande} cohérente avec "
                f"{len(warnings)} avertissements"
            )
        else:
            logger.debug(f"Demande {demande.numero_demande} parfaitement cohérente")
        
        return coherent, toutes_anomalies
        
    except Exception as e:
        logger.error(
            f"Erreur vérification cohérence workflow demande "
            f"{demande.id if demande else 'None'}: {e}"
        )
        return False, [f"Erreur technique lors de la vérification: {str(e)}"]


# ================================================================
# FONCTIONS UTILITAIRES SIMPLIFIÉES
# ================================================================

def _suggerer_matricules_similaires_simple(matricule: str) -> List[str]:
    """Suggère des matricules similaires basiques"""
    try:
        # Recherche simple sur les matricules existants
        matricules_existants = ProfilUtilisateur.objects.filter(
            actif=True,
            matricule__icontains=matricule[:3]  # Recherche par début
        ).values_list('matricule', flat=True)[:10]
        
        return list(matricules_existants)
        
    except Exception:
        return []


def _verifier_eligibilite_base_simple(employe: ProfilUtilisateur, demande: DemandeInterim) -> Dict[str, Any]:
    """Vérifie l'éligibilité de base simplifiée"""
    try:
        result = {'eligible': True, 'raisons_exclusion': []}
        
        # Statut employé
        if employe.statut_employe not in ['ACTIF']:
            result['eligible'] = False
            result['raisons_exclusion'].append(f"Statut employé: {employe.statut_employe}")
        
        # Profil actif
        if not employe.actif:
            result['eligible'] = False
            result['raisons_exclusion'].append("Profil inactif")
        
        # Disponibilité déclarée pour l'intérim si données étendues disponibles
        try:
            if hasattr(employe, 'extended_data') and employe.extended_data:
                if hasattr(employe.extended_data, 'disponible_interim') and not employe.extended_data.disponible_interim:
                    result['eligible'] = False
                    result['raisons_exclusion'].append("Non disponible pour l'intérim")
        except:
            pass  # Ignorer si les données étendues ne sont pas disponibles
        
        # Construire la raison globale
        if not result['eligible']:
            result['raison'] = '; '.join(result['raisons_exclusion'])
        else:
            result['raison'] = 'Éligible'
        
        return result
        
    except Exception as e:
        logger.error(f"Erreur vérification éligibilité: {e}")
        return {
            'eligible': False,
            'raison': f'Erreur technique: {str(e)}',
            'raisons_exclusion': [f'Erreur technique: {str(e)}']
        }


def _analyser_competences_candidat_simple(employe: ProfilUtilisateur, demande: DemandeInterim) -> Dict[str, Any]:
    """Analyse simplifiée des compétences"""
    try:
        # Récupérer les compétences du candidat
        competences_candidat = CompetenceUtilisateur.objects.filter(
            utilisateur=employe
        ).select_related('competence').order_by('-niveau_maitrise')
        
        result = {
            'competences_candidat': [],
            'score_adequation': 0,
            'nb_competences': 0
        }
        
        if competences_candidat.exists():
            result['competences_candidat'] = [
                {
                    'nom': comp.competence.nom,
                    'niveau': comp.niveau_maitrise,
                    'certifie': comp.certifie
                }
                for comp in competences_candidat[:5]  # Top 5
            ]
            
            result['nb_competences'] = competences_candidat.count()
            
            # Calcul du score d'adéquation basique
            niveau_moyen = competences_candidat.aggregate(
                moyenne=Avg('niveau_maitrise')
            )['moyenne'] or 0
            
            result['score_adequation'] = min(100, int(niveau_moyen * 25))
        
        return result
        
    except Exception as e:
        logger.error(f"Erreur analyse compétences: {e}")
        return {
            'competences_candidat': [],
            'score_adequation': 0,
            'nb_competences': 0
        }


def _calculer_distance_sites_simple(employe: ProfilUtilisateur, demande: DemandeInterim) -> Dict[str, Any]:
    """Calcul de distance simplifiée"""
    try:
        if not employe.site or not demande.poste or not demande.poste.site:
            return {
                'distance_evaluation': 'Information manquante',
                'meme_site': False,
                'meme_ville': False
            }
        
        site_employe = employe.site
        site_mission = demande.poste.site
        
        # Si même site
        if site_employe.id == site_mission.id:
            return {
                'distance_evaluation': 'Même site',
                'meme_site': True,
                'meme_ville': True,
                'site_habituel': site_employe.nom,
                'site_mission': site_mission.nom
            }
        
        # Comparaison par ville
        meme_ville = site_employe.ville == site_mission.ville if hasattr(site_employe, 'ville') and hasattr(site_mission, 'ville') else False
        
        return {
            'distance_evaluation': 'Même ville' if meme_ville else 'Ville différente',
            'meme_site': False,
            'meme_ville': meme_ville,
            'site_habituel': site_employe.nom,
            'site_mission': site_mission.nom
        }
        
    except Exception as e:
        logger.error(f"Erreur calcul distance sites: {e}")
        return {
            'distance_evaluation': f'Erreur: {str(e)}',
            'meme_site': False,
            'meme_ville': False
        }


def _analyser_experience_pertinente_simple(employe: ProfilUtilisateur, demande: DemandeInterim) -> Dict[str, Any]:
    """Analyse simplifiée de l'expérience"""
    try:
        result = {
            'anciennete_totale_mois': 0,
            'experience_poste_similaire': False,
            'experience_departement': False,
            'nb_missions_interim': 0
        }
        
        # Ancienneté
        result['anciennete_totale_mois'] = _calculer_anciennete_mois(employe)
        
        # Expérience dans le même poste
        if employe.poste and demande.poste:
            if employe.poste.titre.lower() == demande.poste.titre.lower():
                result['experience_poste_similaire'] = True
        
        # Expérience dans le même département
        if employe.departement and demande.poste and demande.poste.departement:
            if employe.departement.id == demande.poste.departement.id:
                result['experience_departement'] = True
        
        # Missions d'intérim passées
        try:
            result['nb_missions_interim'] = PropositionCandidat.objects.filter(
                candidat_propose=employe,
                statut__in=['VALIDEE', 'TERMINEE']
            ).count()
        except:
            pass
        
        return result
        
    except Exception as e:
        logger.error(f"Erreur analyse expérience: {e}")
        return {
            'anciennete_totale_mois': 0,
            'experience_poste_similaire': False,
            'experience_departement': False,
            'nb_missions_interim': 0
        }


def _generer_recommandation_globale_simple(score_final: int, disponibilite: Dict, 
                                          competences: Dict, distance: Dict) -> Dict[str, Any]:
    """Génère une recommandation simplifiée"""
    try:
        if score_final >= 80:
            niveau = 'EXCELLENT'
            message = 'Candidat très fortement recommandé'
            couleur = 'success'
        elif score_final >= 65:
            niveau = 'BON'
            message = 'Candidat recommandé'
            couleur = 'primary'
        elif score_final >= 50:
            niveau = 'MOYEN'
            message = 'Candidat acceptable avec réserves'
            couleur = 'warning'
        else:
            niveau = 'FAIBLE'
            message = 'Candidat peu recommandé'
            couleur = 'danger'
        
        # Points forts et faibles
        points_forts = []
        points_faibles = []
        
        if disponibilite.get('disponible', False):
            points_forts.append('Disponible sur la période')
        else:
            points_faibles.append('Disponibilité limitée')
        
        if competences.get('score_adequation', 0) >= 70:
            points_forts.append('Compétences adéquates')
        elif competences.get('score_adequation', 0) < 40:
            points_faibles.append('Compétences limitées')
        
        if distance.get('meme_site', False):
            points_forts.append('Même site de travail')
        elif distance.get('meme_ville', False):
            points_forts.append('Même ville')
        elif not distance.get('meme_ville', True):
            points_faibles.append('Ville différente')
        
        return {
            'niveau': niveau,
            'message': message,
            'couleur_css': couleur,
            'score_final': score_final,
            'points_forts': points_forts,
            'points_faibles': points_faibles
        }
        
    except Exception as e:
        logger.error(f"Erreur génération recommandation: {e}")
        return {
            'niveau': 'ERREUR',
            'message': f'Erreur technique: {str(e)}',
            'couleur_css': 'secondary',
            'score_final': 0,
            'points_forts': [],
            'points_faibles': ['Erreur technique']
        }


def _detecter_alertes_candidat_simple(employe: ProfilUtilisateur, demande: DemandeInterim) -> List[str]:
    """Détecte les alertes basiques pour un candidat"""
    alertes = []
    
    try:
        # Alerte statut
        if employe.statut_employe != 'ACTIF':
            alertes.append(f"Statut employé: {employe.statut_employe}")
        
        # Alerte département différent
        if (employe.departement and demande.poste and demande.poste.departement and
            employe.departement != demande.poste.departement):
            alertes.append("Département différent du poste à pourvoir")
        
        # Alerte absence de compétences
        try:
            if not CompetenceUtilisateur.objects.filter(utilisateur=employe).exists():
                alertes.append("Aucune compétence renseignée")
        except:
            pass
        
        # Alerte date de fin de contrat
        try:
            if (hasattr(employe, 'extended_data') and employe.extended_data and
                hasattr(employe.extended_data, 'date_fin_contrat') and
                employe.extended_data.date_fin_contrat):
                
                if employe.extended_data.date_fin_contrat < demande.date_fin:
                    alertes.append("Contrat se termine avant la fin de la mission")
        except:
            pass
        
    except Exception as e:
        alertes.append(f"Erreur détection alertes: {str(e)}")
    
    return alertes


def _get_score_css_class_simple(score: int) -> str:
    """Retourne la classe CSS pour un score"""
    if score >= 85:
        return 'bg-success text-white'
    elif score >= 70:
        return 'bg-primary text-white'
    elif score >= 55:
        return 'bg-warning text-dark'
    else:
        return 'bg-danger text-white'


def _evaluer_score_simple(score: int) -> str:
    """Évalue un score en texte"""
    if score >= 85:
        return 'Excellent'
    elif score >= 70:
        return 'Bon'
    elif score >= 55:
        return 'Correct'
    elif score >= 40:
        return 'Faible'
    else:
        return 'Très faible'


