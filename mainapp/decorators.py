"""
Décorateurs additionnels pour la gestion des profils utilisateur
Compléments aux décorateurs existants dans decorators.py

Fonctionnalités ajoutées :
- @profil_required : Vérification de l'existence du profil utilisateur
- @type_profil_required : Vérification du type de profil requis
- Support de la hiérarchie : RESPONSABLE → DIRECTEUR → RH/ADMIN
- Gestion des superutilisateurs avec droits complets
- Messages d'erreur personnalisés selon le contexte
"""

from django.shortcuts import render, redirect
from functools import wraps
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse

import logging
from typing import List, Union

logger = logging.getLogger(__name__)

# ================================================================
# DÉCORATEURS DE PROFIL UTILISATEUR
# ================================================================

def profil_required(view_func):
    """
    Décorateur pour vérifier qu'un profil utilisateur existe
    
    Usage:
        @profil_required
        def ma_vue(request, *args, **kwargs):
            # Le profil est garanti d'exister et est accessible via kwargs['user_profil']
            pass
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        
        # Vérifier l'authentification
        if not user.is_authenticated:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': True,
                    'message': 'Authentification requise',
                    'redirect_url': '/login/'
                }, status=401)
            
            messages.error(request, "Vous devez être connecté pour accéder à cette page")
            return redirect('login')
        
        # Vérifier l'existence du profil
        try:
            profil = user.profilutilisateur
            
            # Vérifier que le profil est actif
            if not profil.actif:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'error': True,
                        'message': 'Profil utilisateur inactif',
                        'redirect_url': '/profil/inactif/'
                    }, status=403)
                
                messages.error(request, "Votre profil utilisateur est inactif. Contactez l'administrateur.")
                return redirect('profil_inactif')
            
            # Ajouter le profil au contexte
            kwargs['user_profil'] = profil
            
            return view_func(request, *args, **kwargs)
            
        except AttributeError:
            # Profil utilisateur n'existe pas
            logger.warning(f"Tentative d'accès sans profil pour l'utilisateur {user.username}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': True,
                    'message': 'Profil utilisateur non trouvé',
                    'redirect_url': '/profil/creation/'
                }, status=404)
            
            messages.error(
                request, 
                "Votre profil utilisateur n'est pas configuré. Contactez l'administrateur."
            )
            return redirect('profil_creation')
    
    return wrapper

def type_profil_required(types_autorises: Union[str, List[str]], 
                        allow_superuser: bool = True,
                        message_erreur: str = None,
                        redirect_view: str = None):
    """
    Décorateur pour vérifier le type de profil utilisateur avec support hiérarchique
    
    Args:
        types_autorises: Type(s) de profil autorisé(s)
        allow_superuser: Si True, les superutilisateurs passent automatiquement
        message_erreur: Message d'erreur personnalisé
        redirect_view: Vue de redirection en cas d'erreur (par défaut: dashboard)
    
    Usage:
        @type_profil_required('ADMIN')
        @type_profil_required(['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'])
        @type_profil_required('RH', allow_superuser=False)
        @type_profil_required('DIRECTEUR', message_erreur="Droits de directeur requis")
    """
    def decorator(view_func):
        @wraps(view_func)
        @profil_required  # Utilise automatiquement profil_required
        def wrapper(request, *args, **kwargs):
            user = request.user
            profil = kwargs.get('user_profil')  # Garanti par @profil_required
            
            # Gestion des superutilisateurs
            if allow_superuser and user.is_superuser:
                logger.debug(f"Accès autorisé pour superutilisateur: {user.username}")
                return view_func(request, *args, **kwargs)
            
            # Normaliser les types autorisés
            if isinstance(types_autorises, str):
                types_requis = [types_autorises]
            else:
                types_requis = list(types_autorises)
            
            # Vérifier le type de profil avec hiérarchie
            acces_autorise = _verifier_acces_hierarchique(profil.type_profil, types_requis)
            
            if acces_autorise:
                logger.debug(
                    f"Accès autorisé pour {user.username} "
                    f"(profil: {profil.type_profil}, requis: {types_requis})"
                )
                return view_func(request, *args, **kwargs)
            
            # Accès refusé - Générer le message d'erreur
            if message_erreur:
                message = message_erreur
            else:
                types_display = _formater_types_pour_affichage(types_requis)
                message = f"Accès réservé aux profils : {types_display}"
            
            logger.warning(
                f"Accès refusé pour {user.username} "
                f"(profil: {profil.type_profil}, requis: {types_requis})"
            )
            
            # Gestion des réponses selon le type de requête
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': True,
                    'message': message,
                    'required_profiles': types_requis,
                    'current_profile': profil.type_profil,
                    'redirect_url': f"/{redirect_view or 'dashboard'}/"
                }, status=403)
            
            messages.error(request, message)
            return redirect(redirect_view or 'dashboard')
        
        return wrapper
    return decorator

# ================================================================
# DÉCORATEURS SPÉCIALISÉS PAR RÔLE
# ================================================================

def admin_required(message_erreur: str = None):
    """Décorateur pour les actions d'administration"""
    return type_profil_required(
        ['ADMIN'], 
        allow_superuser=True,
        message_erreur=message_erreur or "Droits d'administration requis"
    )

def rh_ou_admin_required(message_erreur: str = None):
    """Décorateur pour les actions RH et admin"""
    return type_profil_required(
        ['RH', 'ADMIN'], 
        allow_superuser=True,
        message_erreur=message_erreur or "Droits RH ou administrateur requis"
    )

def validation_required(message_erreur: str = None):
    """Décorateur pour les actions de validation (tous niveaux)"""
    return type_profil_required(
        ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'], 
        allow_superuser=True,
        message_erreur=message_erreur or "Droits de validation requis"
    )

def creation_demande_required(message_erreur: str = None):
    """Décorateur pour la création de demandes"""
    return type_profil_required(
        ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'], 
        allow_superuser=True,
        message_erreur=message_erreur or "Droits de création de demande requis"
    )

def proposition_candidat_required(message_erreur: str = None):
    """Décorateur pour la proposition de candidats"""
    return type_profil_required(
        ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'], 
        allow_superuser=True,
        message_erreur=message_erreur or "Droits de proposition de candidat requis"
    )

# ================================================================
# DÉCORATEURS AVEC VALIDATION MÉTIER
# ================================================================

def peut_gerer_departement(view_func):
    """
    Décorateur pour vérifier l'accès à un département spécifique
    Utilise le paramètre 'departement_id' de l'URL ou des paramètres GET/POST
    """
    @wraps(view_func)
    @profil_required
    def wrapper(request, *args, **kwargs):
        profil = kwargs['user_profil']
        user = request.user
        
        # Superutilisateurs et RH/ADMIN ont accès à tous les départements
        if user.is_superuser or profil.type_profil in ['RH', 'ADMIN']:
            return view_func(request, *args, **kwargs)
        
        # Récupérer l'ID du département concerné
        departement_id = (
            kwargs.get('departement_id') or 
            request.GET.get('departement_id') or 
            request.POST.get('departement_id')
        )
        
        if departement_id:
            try:
                departement_id = int(departement_id)
                
                # Vérifier que l'utilisateur appartient au département
                if profil.departement and profil.departement.id == departement_id:
                    return view_func(request, *args, **kwargs)
                
                # Vérifier si l'utilisateur manage ce département
                if profil.departements_geres.filter(id=departement_id).exists():
                    return view_func(request, *args, **kwargs)
                
                # Accès refusé
                message = "Vous n'avez pas accès à ce département"
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'error': True,
                        'message': message,
                        'departement_id': departement_id
                    }, status=403)
                
                messages.error(request, message)
                return redirect('dashboard')
                
            except (ValueError, TypeError):
                # ID de département invalide
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'error': True,
                        'message': 'ID de département invalide'
                    }, status=400)
                
                messages.error(request, "ID de département invalide")
                return redirect('dashboard')
        
        # Aucun département spécifié - permettre l'accès
        return view_func(request, *args, **kwargs)
    
    return wrapper

def peut_valider_niveau(niveau_requis: int):
    """
    Décorateur pour vérifier qu'un utilisateur peut valider à un niveau donné
    
    Args:
        niveau_requis: Niveau de validation requis (1=RESPONSABLE, 2=DIRECTEUR, 3=RH/ADMIN)
    """
    def decorator(view_func):
        @wraps(view_func)
        @profil_required
        def wrapper(request, *args, **kwargs):
            profil = kwargs['user_profil']
            user = request.user
            
            # Superutilisateurs peuvent valider à tous les niveaux
            if user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            # Vérifier le niveau de validation selon la hiérarchie
            peut_valider = _peut_valider_niveau_hierarchique(profil.type_profil, niveau_requis)
            
            if peut_valider:
                return view_func(request, *args, **kwargs)
            
            # Accès refusé
            niveaux_display = {
                1: "Responsable (N+1)",
                2: "Directeur (N+2)", 
                3: "RH/Admin (Final)"
            }
            
            message = f"Niveau de validation insuffisant. Requis : {niveaux_display.get(niveau_requis, 'Inconnu')}"
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': True,
                    'message': message,
                    'niveau_requis': niveau_requis,
                    'niveau_actuel': _get_niveau_validation_profil(profil.type_profil)
                }, status=403)
            
            messages.error(request, message)
            return redirect('dashboard')
        
        return wrapper
    return decorator

# ================================================================
# FONCTIONS UTILITAIRES INTERNES
# ================================================================

def _verifier_acces_hierarchique(type_profil_actuel: str, types_requis: List[str]) -> bool:
    """
    Vérifie l'accès selon la hiérarchie : RESPONSABLE → DIRECTEUR → RH/ADMIN
    
    Args:
        type_profil_actuel: Type de profil de l'utilisateur
        types_requis: Types de profil autorisés
    
    Returns:
        bool: True si l'accès est autorisé
    """
    # Hiérarchie des profils (du plus bas au plus haut)
    hierarchie = {
        'UTILISATEUR': 0,
        'CHEF_EQUIPE': 1,
        'RESPONSABLE': 2,
        'DIRECTEUR': 3,
        'RH': 4,
        'ADMIN': 4  # RH et ADMIN au même niveau
    }
    
    niveau_actuel = hierarchie.get(type_profil_actuel, 0)
    
    # Vérifier si le type exact est autorisé
    if type_profil_actuel in types_requis:
        return True
    
    # Vérifier si un niveau supérieur est autorisé
    for type_requis in types_requis:
        niveau_requis = hierarchie.get(type_requis, 0)
        if niveau_actuel >= niveau_requis:
            return True
    
    return False

def _peut_valider_niveau_hierarchique(type_profil: str, niveau_requis: int) -> bool:
    """
    Vérifie si un type de profil peut valider à un niveau donné
    
    Args:
        type_profil: Type de profil de l'utilisateur
        niveau_requis: Niveau de validation requis (1, 2, 3)
    
    Returns:
        bool: True si la validation est autorisée
    """
    mapping_validation = {
        1: ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'],  # Niveau 1 et plus
        2: ['DIRECTEUR', 'RH', 'ADMIN'],                 # Niveau 2 et plus
        3: ['RH', 'ADMIN']                               # Niveau 3 seulement
    }
    
    types_autorises = mapping_validation.get(niveau_requis, [])
    return type_profil in types_autorises

def _get_niveau_validation_profil(type_profil: str) -> int:
    """
    Retourne le niveau de validation maximum du profil
    
    Args:
        type_profil: Type de profil
    
    Returns:
        int: Niveau maximum (0 si aucun)
    """
    mapping = {
        'RESPONSABLE': 1,
        'DIRECTEUR': 2,
        'RH': 3,
        'ADMIN': 3
    }
    return mapping.get(type_profil, 0)

def _formater_types_pour_affichage(types: List[str]) -> str:
    """
    Formate une liste de types de profil pour l'affichage
    
    Args:
        types: Liste des types de profil
    
    Returns:
        str: Types formatés pour l'affichage
    """
    mapping_display = {
        'UTILISATEUR': 'Utilisateur',
        'CHEF_EQUIPE': 'Chef d\'équipe',
        'RESPONSABLE': 'Responsable',
        'DIRECTEUR': 'Directeur',
        'RH': 'RH',
        'ADMIN': 'Administrateur'
    }
    
    types_display = [mapping_display.get(t, t) for t in types]
    
    if len(types_display) == 1:
        return types_display[0]
    elif len(types_display) == 2:
        return f"{types_display[0]} ou {types_display[1]}"
    else:
        return f"{', '.join(types_display[:-1])} ou {types_display[-1]}"

# ================================================================
# DÉCORATEURS DE COMPATIBILITÉ AVEC L'ANCIEN SYSTÈME
# ================================================================

def require_interim_permission_compat(permission_type='view'):
    """
    Décorateur de compatibilité avec l'ancien système
    Utilise les nouveaux décorateurs en interne
    """
    if permission_type == 'admin':
        return admin_required()
    elif permission_type == 'validate':
        return validation_required()
    elif permission_type == 'create':
        return creation_demande_required()
    else:
        return profil_required

# ================================================================
# EXEMPLES D'UTILISATION
# ================================================================

"""
Exemples d'utilisation des décorateurs :

# Vérification simple de l'existence du profil
@profil_required
def ma_vue(request, user_profil):
    # user_profil est garanti d'exister et d'être actif
    pass

# Vérification du type de profil
@type_profil_required('ADMIN')
def vue_admin(request, user_profil):
    pass

@type_profil_required(['RESPONSABLE', 'DIRECTEUR'])
def vue_validation(request, user_profil):
    pass

# Décorateurs spécialisés
@admin_required()
def configuration_systeme(request, user_profil):
    pass

@validation_required("Droits de validation requis pour cette action")
def valider_demande(request, user_profil):
    pass

# Validation avec niveau spécifique
@peut_valider_niveau(2)  # Niveau Directeur
def validation_directeur(request, user_profil):
    pass

# Gestion des départements
@peut_gerer_departement
def gestion_employes_departement(request, departement_id, user_profil):
    pass

# Combinaison de décorateurs
@type_profil_required(['RH', 'ADMIN'])
@peut_gerer_departement
def rapport_departement(request, departement_id, user_profil):
    pass
"""