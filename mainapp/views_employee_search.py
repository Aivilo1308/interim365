# views_employee_search.py - Version simplifiée sans dépendances Kelio

import json
import logging
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

logger = logging.getLogger(__name__)

# ================================================================
# RECHERCHE PRINCIPALE D'EMPLOYÉ
# ================================================================

@login_required
@require_POST
def rechercher_employe_ajax(request):
    """
    Recherche d'employé par matricule - Version simplifiée
    """
    try:
        # Récupération des paramètres
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        force_kelio_sync = data.get('force_kelio_sync', False)
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        if len(matricule) < 2:
            return JsonResponse({
                'success': False,
                'error': 'Matricule trop court (minimum 2 caractères)'
            })
        
        logger.info(f"🔍 Recherche employé: {matricule}")
        
        # ================================================================
        # RECHERCHE DANS LA BASE LOCALE
        # ================================================================
        
        try:
            employe = ProfilUtilisateur.objects.select_related(
                'user', 'poste', 'departement', 'site', 'manager'
            ).get(matricule=matricule)
            
            logger.info(f"✅ Employé trouvé: {employe.nom_complet}")
            
            # Préparer les données de l'employé
            employe_data = _prepare_employee_data(employe)
            
            # Informations de synchronisation (simulées)
            sync_info = _get_sync_info(employe)
            
            return JsonResponse({
                'success': True,
                'employe': employe_data,
                'sync_info': sync_info,
                'source': 'base_locale',
                'message': f'Employé {matricule} trouvé dans la base locale',
                'timestamp': timezone.now().isoformat()
            })
            
        except ProfilUtilisateur.DoesNotExist:
            logger.info(f"❌ Employé {matricule} non trouvé")
            
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
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Format de données invalide'
        }, status=400)
    
    except Exception as e:
        logger.error(f"❌ Erreur recherche employé {matricule}: {e}")
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
        logger.error(f"❌ Erreur préparation données employé {employe.matricule}: {e}")
        return {
            'id': employe.id,
            'matricule': employe.matricule,
            'nom_complet': employe.nom_complet,
            'error': f'Erreur préparation données: {str(e)}'
        }

def _get_sync_info(employe):
    """Récupère les informations de synchronisation (simulées)"""
    try:
        # Données de synchronisation simulées
        last_update = employe.updated_at if hasattr(employe, 'updated_at') else timezone.now()
        
        if last_update:
            time_diff = timezone.now() - last_update
            is_recent = time_diff.total_seconds() < 86400  # 24h
        else:
            is_recent = False
        
        sync_info = {
            'is_recent': is_recent,
            'from_kelio': False,  # Pas de Kelio pour l'instant
            'needs_update': not is_recent,
            'last_sync': last_update.isoformat() if last_update else None,
            'sync_status': 'LOCAL_ONLY'
        }
        
        return sync_info
        
    except Exception as e:
        logger.error(f"❌ Erreur sync info {employe.matricule}: {e}")
        return {
            'is_recent': False,
            'from_kelio': False,
            'needs_update': True,
            'last_sync': None,
            'sync_status': 'ERROR'
        }

# ================================================================
# AUTRES VUES AJAX SIMPLIFIÉES
# ================================================================

@login_required
@require_POST
def sync_employe_kelio_ajax(request):
    """Synchronisation Kelio (simulée)"""
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        # Simuler une synchronisation
        try:
            employe = ProfilUtilisateur.objects.get(matricule=matricule)
            
            # Simuler la mise à jour
            if hasattr(employe, 'updated_at'):
                employe.updated_at = timezone.now()
                employe.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Synchronisation simulée pour {matricule}',
                'employe_updated': True,
                'timestamp': timezone.now().isoformat()
            })
            
        except ProfilUtilisateur.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Employé {matricule} non trouvé'
            })
    
    except Exception as e:
        logger.error(f"Erreur sync: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def verifier_disponibilite_candidat_ajax(request):
    """Vérification de disponibilité"""
    try:
        candidat_id = request.GET.get('candidat_id')
        date_debut = request.GET.get('date_debut')
        date_fin = request.GET.get('date_fin')
        
        if not all([candidat_id, date_debut, date_fin]):
            return JsonResponse({
                'disponible': False,
                'raison': 'Paramètres manquants'
            })
        
        try:
            candidat = ProfilUtilisateur.objects.get(id=candidat_id)
            
            # Vérifications basiques
            if candidat.statut_employe != 'ACTIF':
                return JsonResponse({
                    'disponible': False,
                    'raison': f'Statut employé: {candidat.statut_employe}'
                })
            
            if not candidat.actif:
                return JsonResponse({
                    'disponible': False,
                    'raison': 'Employé inactif'
                })
            
            # Candidat disponible (vérifications simplifiées)
            return JsonResponse({
                'disponible': True,
                'raison': 'Disponible pour la période demandée'
            })
            
        except ProfilUtilisateur.DoesNotExist:
            return JsonResponse({
                'disponible': False,
                'raison': 'Candidat non trouvé'
            })
    
    except Exception as e:
        logger.error(f"Erreur vérification disponibilité: {e}")
        return JsonResponse({
            'disponible': False,
            'raison': 'Erreur lors de la vérification'
        })

@login_required
def recherche_rapide_employes_ajax(request):
    """Recherche rapide pour autocomplétion"""
    try:
        terme = request.GET.get('q', '').strip()
        limit = min(int(request.GET.get('limit', 10)), 20)
        
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
                'disponible_interim': True  # Simplifié
            })
        
        return JsonResponse({
            'success': True,
            'employes': employes_data,
            'count': len(employes_data)
        })
    
    except Exception as e:
        logger.error(f"Erreur recherche rapide: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors de la recherche'
        }, status=500)

@login_required
def employe_verification_matricule_ajax(request, matricule):
    """Vérification d'existence de matricule"""
    try:
        matricule = matricule.strip().upper()
        
        existe = ProfilUtilisateur.objects.filter(matricule=matricule).exists()
        
        if existe:
            employe = ProfilUtilisateur.objects.select_related('user').get(matricule=matricule)
            return JsonResponse({
                'success': True,
                'existe': True,
                'matricule': matricule,
                'nom_complet': employe.nom_complet,
                'actif': employe.actif,
                'statut': employe.statut_employe
            })
        else:
            return JsonResponse({
                'success': True,
                'existe': False,
                'matricule': matricule
            })
    
    except Exception as e:
        logger.error(f"Erreur vérification matricule: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def statut_sync_employe_ajax(request, matricule):
    """Statut de synchronisation"""
    try:
        employe = get_object_or_404(ProfilUtilisateur, matricule=matricule.upper())
        
        statut = {
            'matricule': employe.matricule,
            'nom_complet': employe.nom_complet,
            'derniere_sync': employe.updated_at.isoformat() if hasattr(employe, 'updated_at') and employe.updated_at else None,
            'sync_status': 'LOCAL_ONLY',
            'needs_update': False
        }
        
        return JsonResponse({
            'success': True,
            'statut': statut
        })
    
    except Exception as e:
        logger.error(f"Erreur statut sync: {e}")
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
        
        # Simuler l'invalidation de cache
        cache_keys = [
            f'employe_{matricule}',
            f'employe_disponibilite_{matricule}'
        ]
        
        for key in cache_keys:
            cache.delete(key)
        
        return JsonResponse({
            'success': True,
            'message': f'Cache invalidé pour {matricule}'
        })
    
    except Exception as e:
        logger.error(f"Erreur invalidation cache: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def forcer_sync_kelio_ajax(request):
    """Synchronisation forcée"""
    try:
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        # Simuler une synchronisation forcée
        try:
            employe = ProfilUtilisateur.objects.get(matricule=matricule)
            
            return JsonResponse({
                'success': True,
                'message': f'Synchronisation forcée simulée pour {matricule}',
                'employe': _prepare_employee_data(employe)
            })
            
        except ProfilUtilisateur.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Employé {matricule} non trouvé'
            })
    
    except Exception as e:
        logger.error(f"Erreur sync forcée: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def obtenir_suggestions_matricule_ajax(request):
    """Suggestions de matricules"""
    try:
        prefixe = request.GET.get('prefixe', '').strip().upper()
        limite = min(int(request.GET.get('limite', 5)), 10)
        
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
        
        return JsonResponse({
            'success': True,
            'suggestions': suggestions
        })
    
    except Exception as e:
        logger.error(f"Erreur suggestions: {e}")
        return JsonResponse({
            'success': False,
            'suggestions': []
        }, status=500)

@login_required
def statistiques_cache_employes_ajax(request):
    """Statistiques de cache"""
    try:
        # Statistiques simulées
        stats = {
            'employes_actifs': ProfilUtilisateur.objects.filter(actif=True).count(),
            'employes_total': ProfilUtilisateur.objects.count(),
            'cache_hits': 0,  # Simulé
            'cache_misses': 0,  # Simulé
            'timestamp': timezone.now().isoformat()
        }
        
        return JsonResponse({
            'success': True,
            'statistiques': stats
        })
    
    except Exception as e:
        logger.error(f"Erreur statistiques: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
    
@login_required
@require_POST
def test_ajax_rechercher_employe(request):
    """Vue de test ultra-simple - RÉPONSE COURTE"""
    import json
    
    try:
        # Parser le JSON
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip().upper()
        
        if not matricule:
            return JsonResponse({
                'success': False,
                'error': 'Matricule requis'
            })
        
        # Recherche simple
        try:
            from .models import ProfilUtilisateur
            employe = ProfilUtilisateur.objects.select_related(
                'user', 'poste', 'departement', 'site'
            ).get(matricule=matricule)
            
            # RÉPONSE SIMPLIFIÉE - Éviter les données trop longues
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
            return JsonResponse({
                'success': False,
                'error': f'Employé {matricule} non trouvé'
            })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Erreur: {str(e)}'
        }, status=500)