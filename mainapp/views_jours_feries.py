# -*- coding: utf-8 -*-
"""
Vues Django pour la gestion des jours fériés

À ajouter dans: mainapp/views_jours_feries.py
Ou à intégrer dans views.py ou views_suite.py

Importer dans urls.py:
    from mainapp import views_jours_feries
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from datetime import date, datetime, timedelta
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
import json
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# VUES API - LISTE DES FÉRIÉS MUSULMANS
# ============================================================================

@login_required
@require_http_methods(["GET"])
def api_feries_musulmans(request):
    """
    Retourne la liste des jours fériés musulmans de l'année en cours et suivante
    """
    try:
        from mainapp.models import JourFerie, TypeJourFerie
        
        annee_courante = date.today().year
        
        # Fériés musulmans à venir
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
        
        return JsonResponse({'success': True, 'feries': result})
        
    except Exception as e:
        logger.error(f"Erreur api_feries_musulmans: {e}")
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
    try:
        from mainapp.models import SignalementDateFerie
        
        # Vérifier les droits admin
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
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
        
        return JsonResponse({'success': True, 'signalements': result})
        
    except Exception as e:
        logger.error(f"Erreur api_signalements_feries: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def signaler_correction_ferie(request):
    """
    Permet à un utilisateur de signaler une correction de date
    """
    try:
        from mainapp.models import JourFerie, SignalementDateFerie
        
        ferie_id = request.POST.get('ferie_id')
        date_suggeree = request.POST.get('date_suggeree')
        source_info = request.POST.get('source_info')
        commentaire = request.POST.get('commentaire', '')
        
        if not all([ferie_id, date_suggeree, source_info]):
            return JsonResponse({
                'success': False, 
                'error': 'Données manquantes'
            }, status=400)
        
        # Récupérer le jour férié
        try:
            ferie = JourFerie.objects.get(pk=ferie_id)
        except JourFerie.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Jour férié non trouvé'
            }, status=404)
        
        # Convertir la date
        try:
            date_obj = datetime.strptime(date_suggeree, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({
                'success': False, 
                'error': 'Format de date invalide'
            }, status=400)
        
        # Créer le signalement
        profil = getattr(request.user, 'profilutilisateur', None)
        
        signalement = SignalementDateFerie.objects.create(
            jour_ferie=ferie,
            date_suggeree=date_obj,
            source_info=source_info,
            commentaire=commentaire,
            signale_par=profil,
            statut='EN_ATTENTE'
        )
        
        logger.info(f"Signalement créé: {signalement.id} pour {ferie.nom} par {profil}")
        
        return JsonResponse({
            'success': True,
            'message': 'Signalement enregistré avec succès',
            'signalement_id': signalement.id
        })
        
    except Exception as e:
        logger.error(f"Erreur signaler_correction_ferie: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def traiter_signalement_ferie(request):
    """
    Traite un signalement (accepter ou rejeter) - Admin uniquement
    """
    try:
        from mainapp.models import JourFerie, SignalementDateFerie
        
        # Vérifier les droits admin
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
        
        data = json.loads(request.body)
        signalement_id = data.get('signalement_id')
        action = data.get('action')  # 'accepter' ou 'rejeter'
        
        if not signalement_id or action not in ['accepter', 'rejeter']:
            return JsonResponse({
                'success': False, 
                'error': 'Données invalides'
            }, status=400)
        
        try:
            signalement = SignalementDateFerie.objects.select_related('jour_ferie').get(pk=signalement_id)
        except SignalementDateFerie.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Signalement non trouvé'
            }, status=404)
        
        with transaction.atomic():
            if action == 'accepter':
                # Modifier la date du jour férié
                ferie = signalement.jour_ferie
                
                ferie.modifier_date(
                    nouvelle_date=signalement.date_suggeree,
                    motif=f"Suite au signalement de {signalement.signale_par}. Source: {signalement.source_info}",
                    utilisateur=profil.nom_complet
                )
                
                signalement.statut = 'ACCEPTE'
                
                # Invalider le cache
                cache.delete('prochain_ferie_context')
                
                logger.info(f"Signalement {signalement_id} accepté par {profil}")
                
            else:  # rejeter
                signalement.statut = 'REJETE'
                logger.info(f"Signalement {signalement_id} rejeté par {profil}")
            
            signalement.traite_par = profil
            signalement.date_traitement = timezone.now()
            signalement.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Signalement {action}'
        })
        
    except Exception as e:
        logger.error(f"Erreur traiter_signalement_ferie: {e}")
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
    try:
        from mainapp.models import JourFerie
        
        # Vérifier les droits admin
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
        
        ferie_id = request.POST.get('ferie_id')
        nouvelle_date = request.POST.get('nouvelle_date')
        motif = request.POST.get('motif')
        source = request.POST.get('source', '')
        
        if not all([ferie_id, nouvelle_date, motif]):
            return JsonResponse({
                'success': False, 
                'error': 'Données manquantes'
            }, status=400)
        
        try:
            ferie = JourFerie.objects.get(pk=ferie_id)
        except JourFerie.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Jour férié non trouvé'
            }, status=404)
        
        # Convertir la date
        try:
            date_obj = datetime.strptime(nouvelle_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({
                'success': False, 
                'error': 'Format de date invalide'
            }, status=400)
        
        # Modifier la date
        motif_complet = motif
        if source:
            motif_complet += f" (Source: {source})"
        
        ferie.modifier_date(
            nouvelle_date=date_obj,
            motif=motif_complet,
            utilisateur=profil.nom_complet
        )
        
        # Invalider le cache
        cache.delete('prochain_ferie_context')
        
        logger.info(f"Date modifiée pour {ferie.nom}: {date_obj} par {profil}")
        
        return JsonResponse({
            'success': True,
            'message': 'Date modifiée avec succès',
            'nouvelle_date': date_obj.isoformat(),
            'cache_invalide': True
        })
        
    except Exception as e:
        logger.error(f"Erreur modifier_date_ferie: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def reinitialiser_date_ferie(request):
    """
    Réinitialise la date d'un jour férié à sa valeur calculée - Admin uniquement
    """
    try:
        from mainapp.models import JourFerie
        
        # Vérifier les droits admin
        profil = request.user.profilutilisateur
        if profil.type_profil not in ['ADMIN', 'RH']:
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
        
        data = json.loads(request.body)
        ferie_id = data.get('ferie_id')
        
        if not ferie_id:
            return JsonResponse({
                'success': False, 
                'error': 'ID du jour férié manquant'
            }, status=400)
        
        try:
            ferie = JourFerie.objects.get(pk=ferie_id)
        except JourFerie.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Jour férié non trouvé'
            }, status=404)
        
        if not ferie.date_calculee:
            return JsonResponse({
                'success': False, 
                'error': 'Ce jour férié n\'a pas de date calculée'
            }, status=400)
        
        # Réinitialiser
        ferie.reinitialiser_date(utilisateur=profil.nom_complet)
        
        # Invalider le cache
        cache.delete('prochain_ferie_context')
        
        logger.info(f"Date réinitialisée pour {ferie.nom} par {profil}")
        
        return JsonResponse({
            'success': True,
            'message': 'Date réinitialisée avec succès',
            'date': ferie.date_ferie.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur reinitialiser_date_ferie: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
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


# =============================================================================
# LISTE DES JOURS FÉRIÉS
# =============================================================================

@login_required
def jourferie_liste(request):
    """
    Liste tous les jours fériés de l'année sélectionnée
    
    URL: /interim/jours-feries/
    Template: jourferie_liste.html
    """
    from mainapp.models import JourFerie, TypeJourFerie
    
    # Année sélectionnée (par défaut: année en cours)
    annee_courante = date.today().year
    annee = request.GET.get('annee', annee_courante)
    
    try:
        annee = int(annee)
    except (ValueError, TypeError):
        annee = annee_courante
    
    # Années disponibles pour le filtre
    annees_disponibles = list(range(annee_courante - 2, annee_courante + 3))
    
    # Filtre par type
    type_filtre = request.GET.get('type', '')
    
    # Récupérer les jours fériés
    feries = JourFerie.objects.filter(
        annee=annee,
        code_pays='CI',
        statut='ACTIF'
    ).select_related('modele').order_by('date_ferie')
    
    # Appliquer le filtre par type
    if type_filtre and type_filtre in dict(TypeJourFerie.choices):
        feries = feries.filter(type_ferie=type_filtre)
    
    # Statistiques
    stats = {
        'total': feries.count(),
        'civil': feries.filter(type_ferie=TypeJourFerie.FERIE_CIVIL).count(),
        'chretien': feries.filter(type_ferie=TypeJourFerie.FERIE_CHRETIEN).count(),
        'musulman': feries.filter(type_ferie=TypeJourFerie.FERIE_MUSULMAN).count(),
        'interne': feries.filter(type_ferie=TypeJourFerie.FERIE_INTERNE).count(),
    }
    
    # Vérifier les droits admin
    est_admin = user_est_admin(request.user)
    est_superuser = request.user.is_superuser

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
    
    URL: /interim/jours-feries/<pk>/
    Template: jourferie_afficher.html
    """
    from mainapp.models import JourFerie, HistoriqueModification
    
    ferie = get_object_or_404(JourFerie, pk=pk)
    
    # Récupérer l'historique des modifications
    historique = HistoriqueModification.objects.filter(
        jour_ferie=ferie
    ).order_by('-date_action')[:10]
    
    # Vérifier si modifiable (musulman uniquement)
    est_modifiable = (
        ferie.type_ferie == 'FERIE_MUSULMAN' and
        ferie.modele and
        ferie.modele.est_modifiable
    )
    
    # Vérifier les droits admin
    est_admin = user_est_admin(request.user)
    est_superuser = request.user.is_superuser
    
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
    
    URL: /interim/jours-feries/creer/
    Template: jourferie_creer.html
    
    Seuls les admins/RH peuvent créer des jours fériés internes.
    """
    from mainapp.models import JourFerie, TypeJourFerie
    
    # Vérifier les droits
    if not user_est_admin(request.user) or not request.user.is_superuser:
        messages.error(request, "Vous n'avez pas les droits pour créer un jour férié.")
        return redirect('jourferie_liste')
    
    if request.method == 'POST':
        try:
            # Récupérer les données du formulaire
            nom = request.POST.get('nom', '').strip()
            date_ferie_str = request.POST.get('date_ferie', '')
            description = request.POST.get('description', '').strip()
            est_paye = request.POST.get('est_paye') == 'on'
            
            # Validation
            if not nom:
                raise ValidationError("Le nom du jour férié est obligatoire.")
            
            if not date_ferie_str:
                raise ValidationError("La date est obligatoire.")
            
            # Parser la date
            try:
                date_ferie = datetime.strptime(date_ferie_str, '%Y-%m-%d').date()
            except ValueError:
                raise ValidationError("Format de date invalide.")
            
            # Créer le jour férié interne
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
                
                # Invalider le cache
                invalider_cache_ferie()
                
                logger.info(f"Jour férié interne créé: {ferie.nom} ({ferie.date_ferie}) par {request.user}")
                messages.success(request, f"Le jour férié '{nom}' a été créé avec succès.")
                return redirect('jourferie_afficher', pk=ferie.pk)
        
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            logger.error(f"Erreur création jour férié: {e}")
            messages.error(request, f"Erreur lors de la création : {e}")
    
    # Années disponibles pour le formulaire
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
    
    URL: /interim/jours-feries/musulman/<pk>/modifier/
    Template: jourferiemusulman_modifier.html
    
    Seuls les fériés musulmans avec est_modifiable=True peuvent être modifiés.
    Seuls les admins/RH peuvent modifier.
    """
    from mainapp.models import JourFerie, HistoriqueModification
    
    ferie = get_object_or_404(JourFerie, pk=pk)
    
    # Vérifier les droits
    if not user_est_admin(request.user) or not request.user.is_superuser:
        messages.error(request, "Vous n'avez pas les droits pour modifier ce jour férié.")
        return redirect('jourferie_afficher', pk=pk)
    
    # Vérifier que c'est un férié musulman modifiable
    if ferie.type_ferie != 'FERIE_MUSULMAN':
        messages.error(request, "Seuls les jours fériés musulmans peuvent être modifiés.")
        return redirect('jourferie_afficher', pk=pk)
    
    if ferie.modele and not ferie.modele.est_modifiable:
        messages.error(request, "Ce jour férié n'est pas modifiable.")
        return redirect('jourferie_afficher', pk=pk)
    
    if request.method == 'POST':
        action = request.POST.get('action', 'modifier')
        
        try:
            with transaction.atomic():
                if action == 'reinitialiser':
                    # Réinitialiser à la date calculée
                    if not ferie.date_calculee:
                        raise ValidationError("Impossible de réinitialiser : pas de date calculée.")
                    
                    ferie.reinitialiser_date(
                        utilisateur=request.user.get_full_name() or request.user.username
                    )
                    
                    invalider_cache_ferie()
                    messages.success(request, f"La date de '{ferie.nom}' a été réinitialisée.")
                    
                else:
                    # Modifier la date
                    nouvelle_date_str = request.POST.get('nouvelle_date', '')
                    motif = request.POST.get('motif', '').strip()
                    source = request.POST.get('source', '').strip()
                    
                    if not nouvelle_date_str:
                        raise ValidationError("La nouvelle date est obligatoire.")
                    
                    if not motif:
                        raise ValidationError("Le motif de modification est obligatoire.")
                    
                    # Parser la date
                    try:
                        nouvelle_date = datetime.strptime(nouvelle_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        raise ValidationError("Format de date invalide.")
                    
                    # Construire le motif complet
                    motif_complet = motif
                    if source:
                        motif_complet += f" (Source: {source})"
                    
                    ferie.modifier_date(
                        nouvelle_date=nouvelle_date,
                        motif=motif_complet,
                        utilisateur=request.user.get_full_name() or request.user.username
                    )
                    
                    invalider_cache_ferie()
                    logger.info(f"Jour férié modifié: {ferie.nom} -> {nouvelle_date} par {request.user}")
                    messages.success(request, f"La date de '{ferie.nom}' a été modifiée.")
                
                return redirect('jourferie_afficher', pk=pk)
        
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            logger.error(f"Erreur modification jour férié: {e}")
            messages.error(request, f"Erreur lors de la modification : {e}")
    
    # Récupérer l'historique des modifications
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
    
    URL: /interim/jours-feries/<pk>/supprimer/
    
    Ne supprime pas réellement, mais désactive le jour férié.
    Seuls les admins/RH peuvent supprimer.
    Seuls les fériés internes ou personnalisés peuvent être supprimés.
    """
    from mainapp.models import JourFerie
    
    ferie = get_object_or_404(JourFerie, pk=pk)
    
    # Vérifier les droits
    if not user_est_admin(request.user) or not request.user.is_superuser:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Droits insuffisants"}, status=403)
        messages.error(request, "Vous n'avez pas les droits pour supprimer ce jour férié.")
        return redirect('jourferie_liste')
    
    # Vérifier que c'est un férié interne ou personnalisé
    if ferie.type_ferie != 'FERIE_INTERNE' and not ferie.est_personnalise:
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
        
        # Désactiver le jour férié
        ferie.desactiver(
            motif=motif,
            utilisateur=request.user.get_full_name() or request.user.username
        )
        
        invalider_cache_ferie()
        logger.info(f"Jour férié supprimé: {nom} par {request.user}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': f"'{nom}' a été supprimé."})
        
        messages.success(request, f"Le jour férié '{nom}' a été supprimé.")
        return redirect('jourferie_liste')
    
    except Exception as e:
        logger.error(f"Erreur suppression jour férié: {e}")
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
    
    URL: /interim/api/jours-feries/<pk>/
    """
    from mainapp.models import JourFerie
    
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
    
    return JsonResponse(data)


@login_required
@require_GET  
def api_jourferie_liste(request):
    """
    API pour récupérer la liste des jours fériés en JSON
    
    URL: /interim/api/jours-feries/
    
    Paramètres GET:
        - annee: Année (défaut: année courante)
        - type: Type de férié (optionnel)
    """
    from mainapp.models import JourFerie, TypeJourFerie
    
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
    
    return JsonResponse({'feries': data, 'annee': annee, 'count': len(data)})