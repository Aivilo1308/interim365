# Créer le fichier : mainapp/utils.py
"""
mainapp/utils.py - Utilitaires pour le système d'intérim
"""

import json
import logging
from functools import wraps
from typing import Tuple
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from .models import ProfilUtilisateur, Poste, Departement

logger = logging.getLogger(__name__)

# ================================================================
# FONCTION PRINCIPALE DE VALIDATION
# ================================================================

def valider_coherence_departement_demande(personne_remplacee: ProfilUtilisateur, poste: Poste) -> Tuple[bool, str]:
    """
    Valide que la personne à remplacer appartient au même département que le poste
    [Toute la fonction complète que j'ai fournie précédemment]
    """
    # ... code complet de la fonction ...

def verifier_coherence_rapide(personne_remplacee_id: int, poste_id: int) -> Tuple[bool, str]:
    """
    Version allégée pour validation rapide avec IDs seulement
    """
    # ... code complet de la fonction ...

# ================================================================
# DÉCORATEUR DE VALIDATION
# ================================================================

def require_coherence_departement(view_func):
    """
    Décorateur pour valider automatiquement la cohérence département dans les vues
    
    Usage:
        @require_coherence_departement
        def ma_vue_ajax(request):
            # La validation est automatique
            pass
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method == 'POST':
            try:
                # Essayer de récupérer les données selon le format
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                else:
                    data = request.POST
                
                personne_id = data.get('personne_remplacee_id')
                poste_id = data.get('poste_id')
                
                if personne_id and poste_id:
                    est_valide, message = verifier_coherence_rapide(
                        int(personne_id), int(poste_id)
                    )
                    
                    if not est_valide:
                        return JsonResponse({
                            'success': False,
                            'error': message,
                            'type_erreur': 'coherence_departement'
                        })
            
            except (ValueError, TypeError, json.JSONDecodeError):
                # Si on ne peut pas valider, on laisse passer
                pass
        
        # Appeler la vue originale
        return view_func(request, *args, **kwargs)
    
    return wrapper

# ================================================================
# AUTRES UTILITAIRES LIÉS À L'INTÉRIM
# ================================================================

def get_profil_or_virtual(user):
    """Récupère le profil utilisateur ou crée un profil virtuel pour les superusers"""
    try:
        return user.profilutilisateur
    except:
        if user.is_superuser:
            # Créer un profil virtuel pour les superusers
            class VirtualProfile:
                def __init__(self, user):
                    self.user = user
                    self.matricule = f'SUPER_{user.id}'
                    self.type_profil = 'ADMIN'
                    self.is_superuser = True
                    self.nom_complet = f'{user.first_name} {user.last_name}' if user.first_name else user.username
                    self.departement = None
                    self.actif = True
            return VirtualProfile(user)
        return None

# ================================================================
# UTILISATION DANS LES VUES
# ================================================================

# Dans views.py, importer les utilitaires :
# from .utils import valider_coherence_departement_demande, require_coherence_departement, verifier_coherence_rapide

# ================================================================
# OPTION 2 : CRÉER UN FICHIER DECORATORS.PY (ALTERNATIVE)
# ================================================================

# Créer le fichier : mainapp/decorators.py
"""
mainapp/decorators.py - Décorateurs pour les vues d'intérim
"""

import json
import logging
from functools import wraps
from django.http import JsonResponse
from .utils import verifier_coherence_rapide

logger = logging.getLogger(__name__)

def require_coherence_departement(view_func):
    """
    Décorateur pour valider automatiquement la cohérence département dans les vues
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method == 'POST':
            try:
                # Essayer de récupérer les données selon le format
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                else:
                    data = request.POST
                
                personne_id = data.get('personne_remplacee_id')
                poste_id = data.get('poste_id')
                
                if personne_id and poste_id:
                    est_valide, message = verifier_coherence_rapide(
                        int(personne_id), int(poste_id)
                    )
                    
                    if not est_valide:
                        return JsonResponse({
                            'success': False,
                            'error': message,
                            'type_erreur': 'coherence_departement'
                        })
            
            except (ValueError, TypeError, json.JSONDecodeError):
                # Si on ne peut pas valider, on laisse passer
                pass
        
        # Appeler la vue originale
        return view_func(request, *args, **kwargs)
    
    return wrapper

def require_login_and_profile(view_func):
    """Décorateur pour vérifier connexion et profil utilisateur"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'success': False, 'error': 'Connexion requise'})
        
        # Vérifier le profil
        from .utils import get_profil_or_virtual
        profil = get_profil_or_virtual(request.user)
        if not profil:
            return JsonResponse({'success': False, 'error': 'Profil utilisateur requis'})
        
        return view_func(request, *args, **kwargs)
    
    return wrapper