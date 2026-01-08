# views_manager_proposals.py - Version complète avec toutes les vues manquantes
"""
Vues pour la gestion des propositions managériales.
Version complète intégrant toutes les vues référencées dans urls.py
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.db import transaction
from django.core.paginator import Paginator
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, Avg, Max, Min
from django.utils import timezone
from django.urls import reverse
from django.utils import timezone

from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.db.models import Q, QuerySet  # ← Ajout de QuerySet
from typing import Tuple, Optional, Dict, Any, List

from .models import *

# Import conditionnel des services
try:
    from .services.manager_proposals import ManagerProposalsService
    from .services.scoring_service import ScoringInterimService

    SERVICES_AVAILABLE = True

except ImportError:
    
    SERVICES_AVAILABLE = False
    
    # Services de fallback
    class ManagerProposalsService:
        @staticmethod
        def peut_proposer_candidat(profil, demande):
            return False, "Service non disponible"
        
        @staticmethod
        def proposer_candidat(demande, candidat, proposant, justification, **kwargs):
            return {'success': False, 'error': "Service non disponible"}
        
        @staticmethod
        def obtenir_toutes_propositions_demande(demande):
            return []
        
        @staticmethod
        def evaluer_proposition(proposition, evaluateur, score, commentaire):
            return False, "Service non disponible"
        
        @staticmethod
        def obtenir_statistiques_propositions(departement=None):
            return {
                'total_propositions': 0,
                'propositions_evaluees': 0,
                'taux_evaluation': 0
            }
    
    class ScoringInterimService:
        def calculer_score_candidat(self, candidat, demande):
            return 50

import logging

logger = logging.getLogger(__name__)

# ================================================================
# VUES POUR PROPOSER DES CANDIDATS
# ================================================================

@login_required
def proposer_candidat_view(request, demande_id):
    """Vue pour proposer un candidat à une demande d'intérim"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions via le service
        peut_proposer, raison = ManagerProposalsService.peut_proposer_candidat(profil, demande)
        if not peut_proposer:
            messages.error(request, f"Vous ne pouvez pas proposer de candidat: {raison}")
            return redirect('index')
        
        if request.method == 'POST':
            return _traiter_proposition_candidat(request, profil, demande)
        
        # GET: Afficher le formulaire
        context = _preparer_contexte_proposition(profil, demande)
        return render(request, 'interim/proposer_candidat.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')
    except Exception as e:
        logger.error(f"Erreur vue proposition candidat: {e}")
        messages.error(request, "Erreur lors du chargement de la page")
        return redirect('index')

def _traiter_proposition_candidat(request, profil, demande):
    """Traite la soumission d'une proposition de candidat"""
    try:
        candidat_id = request.POST.get('candidat_id')
        justification = request.POST.get('justification', '').strip()
        competences_specifiques = request.POST.get('competences_specifiques', '').strip()
        experience_pertinente = request.POST.get('experience_pertinente', '').strip()
        
        # Validations basiques
        if not candidat_id:
            messages.error(request, "Veuillez sélectionner un candidat")
            return redirect('proposer_candidat', demande_id=demande.id)
        
        if not justification:
            messages.error(request, "La justification est obligatoire")
            return redirect('proposer_candidat', demande_id=demande.id)
        
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        
        # Utiliser le service pour créer la proposition
        result = ManagerProposalsService.proposer_candidat(
            demande=demande,
            candidat=candidat,
            proposant=profil,
            justification=justification,
            competences_specifiques=competences_specifiques,
            experience_pertinente=experience_pertinente
        )
        
        if result.get('success'):
            messages.success(request, result.get('message', 'Candidat proposé avec succès'))
            return _redirect_after_success(profil)
        else:
            messages.error(request, result.get('error', 'Erreur lors de la proposition'))
            return redirect('proposer_candidat', demande_id=demande.id)
            
    except Exception as e:
        logger.error(f"Erreur traitement proposition: {e}")
        messages.error(request, "Erreur lors de la création de la proposition")
        return redirect('proposer_candidat', demande_id=demande.id)

def _preparer_contexte_proposition(profil, demande):
    """Prépare le contexte pour la vue de proposition"""
    
    # Rechercher les candidats disponibles
    candidats_disponibles = _rechercher_candidats_eligibles(demande)
    
    # Propositions existantes
    propositions_existantes = demande.propositions_candidats.select_related(
        'candidat_propose__user', 'proposant__user'
    ).order_by('-created_at')
    
    return {
        'demande': demande,
        'profil_utilisateur': profil,
        'candidats_disponibles': candidats_disponibles,
        'propositions_existantes': propositions_existantes,
        'peut_ajouter_proposition': len(candidats_disponibles) > 0,
        'nb_propositions_actuelles': propositions_existantes.filter(proposant=profil).count(),
        'services_available': SERVICES_AVAILABLE
    }

def _rechercher_candidats_eligibles(demande):
    """Recherche les candidats éligibles pour une demande"""
    
    # Candidats de base
    candidats_base = ProfilUtilisateur.objects.filter(
        actif=True,
        statut_employe='ACTIF'
    ).exclude(
        id=demande.personne_remplacee.id
    ).select_related(
        'user', 'poste__departement', 'site'
    )
    
    # Exclure ceux déjà proposés
    candidats_deja_proposes = demande.propositions_candidats.values_list(
        'candidat_propose_id', flat=True
    )
    candidats_base = candidats_base.exclude(id__in=candidats_deja_proposes)
    
    # Calculer les scores via le service
    scoring_service = ScoringInterimService()
    candidats_avec_scores = []
    
    for candidat in candidats_base[:50]:  # Limiter pour les performances
        score = scoring_service.calculer_score_candidat(candidat, demande)
        disponibilite = candidat.est_disponible_pour_interim(
            demande.date_debut, demande.date_fin
        )
        
        candidats_avec_scores.append({
            'candidat': candidat,
            'score': score,
            'disponibilite': disponibilite,
            'score_color': _get_score_color(score)
        })
    
    # Trier par score décroissant
    candidats_avec_scores.sort(key=lambda x: x['score'], reverse=True)
    
    return candidats_avec_scores

def _get_score_color(score):
    """Retourne la couleur selon le score"""
    if score >= 80:
        return 'success'
    elif score >= 60:
        return 'warning'
    else:
        return 'danger'

def _redirect_after_success(profil):
    """Redirection après succès selon le rôle"""
    if profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE']:
        return redirect('index_chef_equipe')
    elif profil.type_profil == 'RH':
        return redirect('index_n3_global')
    else:
        return redirect('mes_demandes')
   
# ================================================================
# API POUR LES PROPOSITIONS
# ================================================================

@login_required
@require_POST
def evaluer_proposition_ajax(request):
    """Évalue une proposition via AJAX"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        proposition_id = request.POST.get('proposition_id')
        score_ajuste = request.POST.get('score_ajuste')
        commentaire = request.POST.get('commentaire', '')
        
        proposition = get_object_or_404(PropositionCandidat, id=proposition_id)
        
        # Vérifier les permissions
        if not _peut_evaluer_propositions(profil, proposition.demande_interim):
            return JsonResponse({
                'success': False,
                'error': 'Permissions insuffisantes pour évaluer'
            })
        
        # Valider le score
        if score_ajuste:
            try:
                score_ajuste = int(score_ajuste)
                if not (0 <= score_ajuste <= 100):
                    raise ValueError()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'error': 'Score invalide (doit être entre 0 et 100)'
                })
        else:
            score_ajuste = None
        
        # Évaluer via le service
        success, message = ManagerProposalsService.evaluer_proposition(
            proposition, profil, score_ajuste, commentaire
        )
        
        if success:
            return JsonResponse({
                'success': True,
                'message': message,
                'score_final': proposition.score_final
            })
        else:
            return JsonResponse({'success': False, 'error': message})
            
    except Exception as e:
        logger.error(f"Erreur évaluation proposition: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def retenir_proposition_ajax(request):
    """Retient une proposition pour validation via AJAX"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        proposition_id = request.POST.get('proposition_id')
        
        proposition = get_object_or_404(PropositionCandidat, id=proposition_id)
        
        # Vérifier les permissions
        if not _peut_evaluer_propositions(profil, proposition.demande_interim):
            return JsonResponse({
                'success': False,
                'error': 'Permissions insuffisantes'
            })
        
        # Retenir la proposition
        proposition.statut = 'RETENUE'
        proposition.evaluateur = profil
        proposition.date_evaluation = timezone.now()
        proposition.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Proposition retenue pour validation',
            'statut': proposition.statut
        })
        
    except Exception as e:
        logger.error(f"Erreur rétention proposition: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES ADMINISTRATIVES DES PROPOSITIONS
# ================================================================

@login_required
def rapport_propositions_departement(request):
    """Rapport des propositions par département"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Vérifier les permissions
        if profil.type_profil not in ['RH', 'DIRECTEUR', 'ADMIN']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Filtres
        departement_id = request.GET.get('departement')
        periode = int(request.GET.get('periode', 30))
        
        # Date limite
        date_limite = timezone.now() - timezone.timedelta(days=periode)
        
        # Propositions par département
        query = PropositionCandidat.objects.filter(
            created_at__gte=date_limite
        ).select_related(
            'demande_interim__poste__departement',
            'proposant__user',
            'candidat_propose__user'
        )
        
        if departement_id:
            query = query.filter(demande_interim__poste__departement_id=departement_id)
        
        # Regroupement par département
        from django.db.models import Count, Avg
        stats_departements = query.values(
            'demande_interim__poste__departement__nom'
        ).annotate(
            total_propositions=Count('id'),
            score_moyen=Avg('score_final'),
            taux_validation=Count('id', filter=Q(statut__in=['VALIDEE', 'RETENUE'])) * 100.0 / Count('id')
        ).order_by('-total_propositions')
        
        # Top proposants
        top_proposants = query.values(
            'proposant__user__first_name',
            'proposant__user__last_name'
        ).annotate(
            total_propositions=Count('id'),
            score_moyen=Avg('score_final')
        ).order_by('-total_propositions')[:10]
        
        context = {
            'profil_utilisateur': profil,
            'stats_departements': stats_departements,
            'top_proposants': top_proposants,
            'periode': periode,
            'departement_id': departement_id,
            'departements': Departement.objects.filter(actif=True)
        }
        
        return render(request, 'interim/admin/rapport_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def statistiques_scoring_propositions(request):
    """Statistiques sur le scoring des propositions"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['RH', 'ADMIN']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Analyse du scoring
        propositions = PropositionCandidat.objects.filter(
            score_final__isnull=False
        ).select_related('demande_interim', 'candidat_propose')
        
        # Distribution des scores
        distribution_scores = {
            'excellent': propositions.filter(score_final__gte=90).count(),
            'bon': propositions.filter(score_final__gte=70, score_final__lt=90).count(),
            'moyen': propositions.filter(score_final__gte=50, score_final__lt=70).count(),
            'faible': propositions.filter(score_final__lt=50).count()
        }
        
        # Score moyen par source
        from django.db.models import Avg
        scores_par_source = propositions.values(
            'source_proposition'
        ).annotate(
            score_moyen=Avg('score_final'),
            count=Count('id')
        ).order_by('-score_moyen')
        
        # Efficacité des propositions (taux de sélection)
        propositions_selectionnees = propositions.filter(
            statut__in=['VALIDEE', 'RETENUE']
        ).count()
        
        taux_selection = (propositions_selectionnees / propositions.count() * 100) if propositions.count() > 0 else 0
        
        context = {
            'profil_utilisateur': profil,
            'distribution_scores': distribution_scores,
            'scores_par_source': scores_par_source,
            'taux_selection': round(taux_selection, 1),
            'total_propositions': propositions.count(),
            'services_available': SERVICES_AVAILABLE
        }
        
        return render(request, 'interim/admin/stats_scoring.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR L'EXPORT DES PROPOSITIONS
# ================================================================

@login_required
def export_propositions_excel(request):
    """Export Excel des propositions"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['RH', 'DIRECTEUR', 'ADMIN']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Pour l'instant, simulation
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename="propositions_export.xlsx"'
        response.write(b'Export Excel des propositions - A implementer')
        
        return response
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
def export_propositions_csv(request):
    """Export CSV des propositions"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['RH', 'DIRECTEUR', 'ADMIN']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="propositions_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Demande', 'Candidat', 'Proposant', 'Score', 'Statut', 'Date'])
        
        propositions = PropositionCandidat.objects.select_related(
            'demande_interim', 'candidat_propose__user', 'proposant__user'
        )[:1000]  # Limiter à 1000
        
        for prop in propositions:
            writer.writerow([
                prop.demande_interim.numero_demande,
                prop.candidat_propose.nom_complet,
                prop.proposant.nom_complet,
                prop.score_final or 0,
                prop.statut,
                prop.created_at.strftime('%Y-%m-%d')
            ])
        
        return response
        
    except Exception as e:
        logger.error(f"Erreur export CSV: {e}")
        messages.error(request, "Erreur lors de l'export")
        return redirect('historique_mes_propositions')

# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def _peut_voir_propositions(profil, demande):
    """Vérifie si l'utilisateur peut voir les propositions"""
    return (
        demande.demandeur == profil or
        profil.type_profil in ['RH', 'ADMIN'] or
        (profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR'] and
         profil.departement == demande.poste.departement)
    )

# 4. CORRECTION DANS views_manager_proposals.py - Fonction _peut_evaluer_propositions
def _peut_evaluer_propositions(profil, demande):
    """
    Vérifie si l'utilisateur peut évaluer les propositions
    CHEF_EQUIPE ne peut pas évaluer, seulement proposer
    """
    # Accès total pour superutilisateurs
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    type_profil = getattr(profil, 'type_profil', None)
    
    # CHEF_EQUIPE ne peut pas évaluer
    if type_profil == 'CHEF_EQUIPE':
        return False
    
    return (
        type_profil in ['RH', 'ADMIN', 'DIRECTEUR'] or
        (type_profil == 'RESPONSABLE' and 
         getattr(profil, 'departement', None) == demande.poste.departement)
    )

# ================================================================
# VUES DE NOTIFICATION POUR LES PROPOSITIONS
# ================================================================

@login_required
def notifications_propositions(request):
    """Notifications spécifiques aux propositions"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Notifications liées aux propositions
        notifications = NotificationInterim.objects.filter(
            destinataire=profil,
            type_notification__in=[
                'PROPOSITION_CANDIDAT',
                'CANDIDAT_PROPOSE_VALIDATION',
                'PROPOSITION_EVALUEE'
            ]
        ).select_related(
            'proposition_liee__candidat_propose__user',
            'proposition_liee__demande_interim'
        ).order_by('-created_at')[:20]
        
        context = {
            'profil_utilisateur': profil,
            'notifications': notifications
        }
        
        return render(request, 'interim/notifications_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR LES PARAMÈTRES DES PROPOSITIONS
# ================================================================

@login_required
def parametres_propositions(request):
    """Configuration des paramètres de propositions"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['RH', 'ADMIN']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Configuration du scoring
        config_scoring = ConfigurationScoring.objects.first()
        
        if request.method == 'POST':
            # Traitement des modifications
            messages.success(request, "Paramètres mis à jour")
            return redirect('parametres_propositions')
        
        context = {
            'profil_utilisateur': profil,
            'config_scoring': config_scoring
        }
        
        return render(request, 'interim/admin/parametres_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES DEBUG (POUR LE DÉVELOPPEMENT)
# ================================================================

@login_required
def debug_propositions(request):
    """Vue de debug pour les propositions (développement uniquement)"""
    try:
        if not request.user.is_superuser:
            messages.error(request, "Accès refusé")
            return redirect('index')
        
        # Informations de debug
        debug_info = {
            'services_available': SERVICES_AVAILABLE,
            'total_propositions': PropositionCandidat.objects.count(),
            'derniere_proposition': PropositionCandidat.objects.order_by('-created_at').first(),
            'configurations_scoring': ConfigurationScoring.objects.count()
        }
        
        context = {
            'debug_info': debug_info
        }
        
        return render(request, 'interim/debug/propositions.html', context)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ================================================================
# API POUR STATISTIQUES TEMPS RÉEL
# ================================================================

@login_required
def api_stats_propositions_temps_reel(request):
    """API pour statistiques des propositions en temps réel"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Statistiques selon le rôle
        if profil.type_profil == 'RH':
            # Stats globales pour RH
            stats = {
                'propositions_aujourd_hui': PropositionCandidat.objects.filter(
                    created_at__date=timezone.now().date()
                ).count(),
                'propositions_en_attente': PropositionCandidat.objects.filter(
                    statut='SOUMISE'
                ).count(),
                'propositions_evaluees_aujourd_hui': PropositionCandidat.objects.filter(
                    date_evaluation__date=timezone.now().date()
                ).count(),
                'score_moyen_jour': PropositionCandidat.objects.filter(
                    created_at__date=timezone.now().date(),
                    score_final__isnull=False
                ).aggregate(score_moyen=Avg('score_final'))['score_moyen'] or 0
            }
        else:
            # Stats départementales pour managers
            stats = {
                'mes_propositions_mois': PropositionCandidat.objects.filter(
                    proposant=profil,
                    created_at__gte=timezone.now().replace(day=1)
                ).count(),
                'propositions_departement_semaine': PropositionCandidat.objects.filter(
                    demande_interim__poste__departement=profil.departement,
                    created_at__gte=timezone.now() - timezone.timedelta(days=7)
                ).count(),
                'taux_validation_perso': _calculer_taux_validation_proposant(profil),
                'score_moyen_perso': PropositionCandidat.objects.filter(
                    proposant=profil,
                    score_final__isnull=False
                ).aggregate(score_moyen=Avg('score_final'))['score_moyen'] or 0
            }
        
        return JsonResponse({
            'success': True,
            'stats': stats,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur API stats temps réel: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

def _calculer_taux_validation_proposant(profil):
    """Calcule le taux de validation d'un proposant"""
    total = PropositionCandidat.objects.filter(proposant=profil).count()
    validees = PropositionCandidat.objects.filter(
        proposant=profil,
        statut__in=['VALIDEE', 'RETENUE']
    ).count()
    
    return round((validees / total * 100) if total > 0 else 0, 1)

# ================================================================
# VUES POUR WORKFLOW PROPOSITIONS
# ================================================================

@login_required
def workflow_propositions_demande(request, demande_id):
    """Vue du workflow des propositions pour une demande"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        if not _peut_voir_propositions(profil, demande):
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Chronologie des propositions
        propositions_chrono = demande.propositions_candidats.select_related(
            'candidat_propose__user',
            'proposant__user',
            'evaluateur__user'
        ).order_by('created_at')
        
        # Étapes du workflow
        etapes_workflow = []
        for prop in propositions_chrono:
            etapes_workflow.append({
                'type': 'proposition',
                'timestamp': prop.created_at,
                'utilisateur': prop.proposant,
                'action': f"Proposition de {prop.candidat_propose.nom_complet}",
                'statut': prop.statut,
                'score': prop.score_final
            })
            
            if prop.date_evaluation:
                etapes_workflow.append({
                    'type': 'evaluation',
                    'timestamp': prop.date_evaluation,
                    'utilisateur': prop.evaluateur,
                    'action': f"Évaluation: {prop.get_statut_display()}",
                    'statut': prop.statut,
                    'commentaire': prop.commentaire_evaluation
                })
        
        # Trier par timestamp
        etapes_workflow.sort(key=lambda x: x['timestamp'])
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil,
            'propositions': propositions_chrono,
            'etapes_workflow': etapes_workflow,
            'peut_intervenir': _peut_evaluer_propositions(profil, demande)
        }
        
        return render(request, 'interim/workflow_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR COMPARAISON DE CANDIDATS
# ================================================================

@login_required
def comparaison_candidats_proposes(request, demande_id):
    """Vue de comparaison des candidats proposés"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        if not _peut_voir_propositions(profil, demande):
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Récupérer toutes les propositions avec détails
        propositions = demande.propositions_candidats.select_related(
            'candidat_propose__user',
            'candidat_propose__poste',
            'candidat_propose__departement',
            'candidat_propose__site',
            'proposant__user'
        ).order_by('-score_final')
        
        # Enrichir avec des données de comparaison
        candidats_comparaison = []
        for prop in propositions:
            candidat = prop.candidat_propose
            
            # Compétences
            nb_competences = candidat.competences.filter(
                niveau_maitrise__gte=3
            ).count()
            
            # Formations
            nb_formations = candidat.formations.filter(
                certifiante=True
            ).count()
            
            # Expérience intérim
            missions_precedentes = candidat.selections_interim.filter(
                statut='TERMINEE'
            ).count()
            
            # Disponibilité
            disponibilite = candidat.est_disponible_pour_interim(
                demande.date_debut, demande.date_fin
            )
            
            candidats_comparaison.append({
                'proposition': prop,
                'candidat': candidat,
                'competences_count': nb_competences,
                'formations_count': nb_formations,
                'missions_precedentes': missions_precedentes,
                'disponibilite': disponibilite,
                'score_details': _get_score_details(candidat, demande)
            })
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil,
            'candidats_comparaison': candidats_comparaison,
            'peut_evaluer': _peut_evaluer_propositions(profil, demande)
        }
        
        return render(request, 'interim/comparaison_candidats.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

def _get_score_details(candidat, demande):
    """Récupère les détails de score d'un candidat"""
    try:
        score_detail = ScoreDetailCandidat.objects.filter(
            candidat=candidat,
            demande_interim=demande
        ).first()
        
        if score_detail:
            return {
                'similarite_poste': score_detail.score_similarite_poste,
                'competences': score_detail.score_competences,
                'experience': score_detail.score_experience,
                'disponibilite': score_detail.score_disponibilite,
                'proximite': score_detail.score_proximite,
                'total': score_detail.score_total
            }
    except:
        pass
    
    return {
        'similarite_poste': 0,
        'competences': 0,
        'experience': 0,
        'disponibilite': 0,
        'proximite': 0,
        'total': 0
    }

# ================================================================
# VUES POUR AIDE PROPOSITIONS
# ================================================================

@login_required
def aide_propositions_candidats(request):
    """Page d'aide pour les propositions de candidats"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Contenu d'aide selon le rôle
        if profil.type_profil == 'CHEF_EQUIPE':
            guide_role = 'chef_equipe'
        elif profil.type_profil == 'RESPONSABLE':
            guide_role = 'responsable'
        elif profil.type_profil == 'RH':
            guide_role = 'rh'
        else:
            guide_role = 'general'
        
        context = {
            'profil_utilisateur': profil,
            'guide_role': guide_role,
            'services_available': SERVICES_AVAILABLE
        }
        
        return render(request, 'interim/aide/propositions_candidats.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR HISTORIQUE PROPOSITIONS
# ================================================================

@login_required
def historique_propositions_candidat(request, candidat_id):
    """Historique des propositions d'un candidat"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        
        # Vérifier les permissions
        if not _peut_voir_historique_candidat(profil, candidat):
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Historique des propositions
        propositions = PropositionCandidat.objects.filter(
            candidat_propose=candidat
        ).select_related(
            'demande_interim__poste',
            'proposant__user',
            'evaluateur__user'
        ).order_by('-created_at')
        
        # Statistiques du candidat
        stats_candidat = {
            'total_propositions': propositions.count(),
            'propositions_validees': propositions.filter(statut='VALIDEE').count(),
            'score_moyen': propositions.aggregate(
                score_moyen=Avg('score_final')
            )['score_moyen'] or 0,
            'derniere_proposition': propositions.first()
        }
        
        context = {
            'candidat': candidat,
            'profil_utilisateur': profil,
            'propositions': propositions,
            'stats_candidat': stats_candidat
        }
        
        return render(request, 'interim/historique_propositions_candidat.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

def _peut_voir_historique_candidat(profil, candidat):
    """Vérifie si l'utilisateur peut voir l'historique du candidat"""
    return (
        profil.type_profil in ['RH', 'ADMIN'] or
        profil == candidat.manager or
        profil.departement == candidat.departement
    )

# ================================================================
# VUES POUR SCORING AVANCÉ
# ================================================================

@login_required
def details_scoring_proposition(request, proposition_id):
    """Détails du scoring d'une proposition"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        proposition = get_object_or_404(PropositionCandidat, id=proposition_id)
        
        if not _peut_voir_propositions(profil, proposition.demande_interim):
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Détails du score
        score_detail = ScoreDetailCandidat.objects.filter(
            candidat=proposition.candidat_propose,
            demande_interim=proposition.demande_interim,
            proposition_humaine=proposition
        ).first()
        
        # Configuration de scoring utilisée
        config_scoring = ConfigurationScoring.objects.first()
        
        # Comparaison avec d'autres candidats
        autres_propositions = proposition.demande_interim.propositions_candidats.exclude(
            id=proposition.id
        ).select_related('candidat_propose__user')
        
        context = {
            'proposition': proposition,
            'profil_utilisateur': profil,
            'score_detail': score_detail,
            'config_scoring': config_scoring,
            'autres_propositions': autres_propositions,
            'peut_ajuster_score': _peut_evaluer_propositions(profil, proposition.demande_interim)
        }
        
        return render(request, 'interim/details_scoring_proposition.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR VALIDATION BATCH
# ================================================================

@login_required
def validation_batch_propositions(request):
    """Validation en lot de plusieurs propositions"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['RH', 'DIRECTEUR', 'RESPONSABLE']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        if request.method == 'POST':
            return _traiter_validation_batch(request, profil)
        
        # Propositions en attente de validation
        propositions_en_attente = PropositionCandidat.objects.filter(
            statut='SOUMISE'
        ).select_related(
            'demande_interim__poste',
            'candidat_propose__user',
            'proposant__user'
        )
        
        # Filtrer selon les permissions
        if profil.type_profil != 'RH':
            propositions_en_attente = propositions_en_attente.filter(
                demande_interim__poste__departement=profil.departement
            )
        
        propositions_en_attente = propositions_en_attente.order_by('-created_at')
        
        context = {
            'profil_utilisateur': profil,
            'propositions_en_attente': propositions_en_attente
        }
        
        return render(request, 'interim/validation_batch_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

def _traiter_validation_batch(request, profil):
    """Traite la validation en lot"""
    try:
        propositions_ids = request.POST.getlist('propositions_ids')
        action = request.POST.get('action')  # 'approuver' ou 'rejeter'
        commentaire_global = request.POST.get('commentaire_global', '')
        
        if not propositions_ids:
            messages.error(request, "Aucune proposition sélectionnée")
            return redirect('validation_batch_propositions')
        
        propositions = PropositionCandidat.objects.filter(
            id__in=propositions_ids,
            statut='SOUMISE'
        )
        
        # Vérifier les permissions pour chaque proposition
        propositions_autorisees = []
        for prop in propositions:
            if _peut_evaluer_propositions(profil, prop.demande_interim):
                propositions_autorisees.append(prop)
        
        if not propositions_autorisees:
            messages.error(request, "Aucune proposition autorisée pour validation")
            return redirect('validation_batch_propositions')
        
        # Traitement en lot
        count_success = 0
        with transaction.atomic():
            for prop in propositions_autorisees:
                try:
                    if action == 'approuver':
                        prop.statut = 'EVALUEE'
                    elif action == 'rejeter':
                        prop.statut = 'REJETEE'
                    
                    prop.evaluateur = profil
                    prop.date_evaluation = timezone.now()
                    prop.commentaire_evaluation = commentaire_global
                    prop.save()
                    
                    count_success += 1
                    
                except Exception as e:
                    logger.error(f"Erreur validation proposition {prop.id}: {e}")
        
        if count_success > 0:
            action_text = "approuvées" if action == 'approuver' else "rejetées"
            messages.success(request, f"{count_success} proposition(s) {action_text}")
        else:
            messages.error(request, "Aucune proposition n'a pu être traitée")
        
        return redirect('validation_batch_propositions')
        
    except Exception as e:
        logger.error(f"Erreur validation batch: {e}")
        messages.error(request, "Erreur lors de la validation")
        return redirect('validation_batch_propositions')

# ================================================================
# VUES POUR PARAMÈTRES UTILISATEUR PROPOSITIONS
# ================================================================

@login_required
def mes_parametres_propositions(request):
    """Paramètres personnels pour les propositions"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if request.method == 'POST':
            # Sauvegarder les préférences
            messages.success(request, "Paramètres sauvegardés")
            return redirect('mes_parametres_propositions')
        
        # Récupérer les préférences actuelles
        preferences = {
            'notifications_nouvelles_demandes': True,
            'notifications_evaluations': True,
            'email_resume_hebdo': False,
            'propositions_auto_dept': True
        }
        
        context = {
            'profil_utilisateur': profil,
            'preferences': preferences
        }
        
        return render(request, 'interim/mes_parametres_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# API POUR SUGGESTIONS DE CANDIDATS
# ================================================================

@login_required
def api_suggestions_candidats_intelligentes(request, demande_id):
    """API pour suggestions intelligentes de candidats"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        peut_proposer, _ = ManagerProposalsService.peut_proposer_candidat(profil, demande)
        if not peut_proposer:
            return JsonResponse({'success': False, 'error': 'Permissions insuffisantes'})
        
        if SERVICES_AVAILABLE:
            scoring_service = ScoringInterimService()
            suggestions = scoring_service.generer_candidats_automatiques(demande, limite=10)
            
            # Enrichir avec des raisons de suggestion
            suggestions_enrichies = []
            for suggestion in suggestions:
                candidat = suggestion['candidat']
                
                raisons = []
                if candidat.poste and candidat.poste.departement == demande.poste.departement:
                    raisons.append("Même département")
                if candidat.site == demande.poste.site:
                    raisons.append("Même site")
                if suggestion['score'] >= 80:
                    raisons.append("Score élevé")
                
                suggestions_enrichies.append({
                    'candidat_id': candidat.id,
                    'nom_complet': candidat.nom_complet,
                    'matricule': candidat.matricule,
                    'poste': candidat.poste.titre if candidat.poste else '',
                    'score': suggestion['score'],
                    'disponibilite': suggestion['disponibilite'],
                    'raisons': raisons,
                    'justification_auto': suggestion['justification_auto']
                })
            
            return JsonResponse({
                'success': True,
                'suggestions': suggestions_enrichies
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Service de suggestions non disponible'
            })
        
    except Exception as e:
        logger.error(f"Erreur suggestions intelligentes: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES DE MONITORING
# ================================================================

@login_required
def monitoring_propositions_departement(request):
    """Monitoring des propositions par département"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['RH', 'DIRECTEUR']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Données de monitoring en temps réel
        from django.db.models import Count, Avg, Q
        from datetime import datetime, timedelta
        
        # Dernières 24h
        depuis_24h = timezone.now() - timedelta(hours=24)
        
        monitoring_data = []
        departements = Departement.objects.filter(actif=True)
        
        for dept in departements:
            propositions_dept = PropositionCandidat.objects.filter(
                demande_interim__poste__departement=dept
            )
            
            stats_dept = {
                'departement': dept.nom,
                'propositions_24h': propositions_dept.filter(
                    created_at__gte=depuis_24h
                ).count(),
                'propositions_total': propositions_dept.count(),
                'en_attente': propositions_dept.filter(statut='SOUMISE').count(),
                'score_moyen': propositions_dept.aggregate(
                    score=Avg('score_final')
                )['score'] or 0,
                'taux_validation': _calculer_taux_validation_departement(dept)
            }
            
            monitoring_data.append(stats_dept)
        
        # Trier par activité récente
        monitoring_data.sort(key=lambda x: x['propositions_24h'], reverse=True)
        
        context = {
            'profil_utilisateur': profil,
            'monitoring_data': monitoring_data,
            'timestamp': timezone.now()
        }
        
        return render(request, 'monitoring_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

def _calculer_taux_validation_departement(departement):
    """Calcule le taux de validation pour un département"""
    total = PropositionCandidat.objects.filter(
        demande_interim__poste__departement=departement
    ).count()
    
    validees = PropositionCandidat.objects.filter(
        demande_interim__poste__departement=departement,
        statut__in=['VALIDEE', 'RETENUE', 'EVALUEE']
    ).count()
    
    return round((validees / total * 100) if total > 0 else 0, 1)

# ================================================================
# LOG DE CONFIRMATION DU MODULE
# ================================================================

#logger.info("  Module views_manager_proposals.py chargé avec succès")

""" 
logger.info("🔧 Vues disponibles:")
logger.info("   • Proposition de candidats")
logger.info("   • Gestion des propositions")
logger.info("   • Dashboard managers")
logger.info("   • API scoring et évaluation")
logger.info("   • Validation batch")
logger.info("   • Monitoring et statistiques")
logger.info(f"   • Services disponibles: {SERVICES_AVAILABLE}")
"""

#print("  views_manager_proposals.py complet et opérationnel")

# ================================================================
# VUE D'INTÉGRATION AVEC VALIDATION (MANQUANTE)
# ================================================================

@login_required
def validation_avec_propositions(request, demande_id):
    """
    Vue de validation intégrant les propositions managériales
    Cette vue fait le pont entre les propositions et le workflow de validation
    """
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions de validation
        if not _peut_evaluer_propositions(profil, demande):
            messages.error(request, "Vous n'êtes pas autorisé à valider cette demande")
            return redirect('index')
        
        # Récupérer les propositions avec scores
        propositions = demande.propositions_candidats.select_related(
            'candidat_propose__user', 
            'candidat_propose__poste',
            'proposant__user'
        ).order_by('-score_final', '-created_at')
        
        # Workflow actuel
        workflow_info = {
            'etape_actuelle': _get_etape_validation_actuelle(demande),
            'niveau_validation': demande.niveau_validation_actuel,
            'niveaux_requis': demande.niveaux_validation_requis,
            'peut_valider': _peut_valider_niveau_actuel(profil, demande)
        }
        
        # Historique des validations
        validations_precedentes = demande.validations.select_related(
            'validateur__user'
        ).order_by('niveau_validation')
        
        # Candidats automatiques si disponible
        candidats_automatiques = []
        if SERVICES_AVAILABLE:
            try:
                from .services.scoring_service import ScoringInterimService
                scoring_service = ScoringInterimService()
                candidats_automatiques = scoring_service.generer_candidats_automatiques(
                    demande, limite=5
                )
            except Exception as e:
                logger.warning(f"Impossible de générer les candidats automatiques: {e}")
        
        if request.method == 'POST':
            return _traiter_validation_avec_propositions(request, profil, demande, propositions)
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil,
            'propositions': propositions,
            'candidats_automatiques': candidats_automatiques,
            'workflow_info': workflow_info,
            'validations_precedentes': validations_precedentes,
            'peut_ajouter_candidat': _peut_ajouter_candidat_validation(profil),
            'services_available': SERVICES_AVAILABLE
        }
        
        return render(request, 'interim/validation_avec_propositions.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')
    except Exception as e:
        logger.error(f"Erreur validation avec propositions: {e}")
        messages.error(request, "Erreur lors du chargement de la validation")
        return redirect('index')

def _traiter_validation_avec_propositions(request, profil, demande, propositions):
    """Traite la validation avec propositions"""
    try:
        action = request.POST.get('action')
        commentaire = request.POST.get('commentaire', '')
        candidats_retenus = request.POST.getlist('candidats_retenus[]')
        
        if action == 'valider_niveau_suivant':
            # Passer au niveau de validation suivant
            if SERVICES_AVAILABLE:
                from .services.manager_proposals import ManagerProposalsService
                success = ManagerProposalsService.retenir_pour_validation_niveau_suivant(
                    demande, profil, candidats_retenus
                )
            else:
                success = _valider_niveau_suivant_fallback(demande, profil, candidats_retenus, commentaire)
            
            if success:
                messages.success(request, "Validation transmise au niveau suivant")
                return redirect('interim_validation', demande.id)
            else:
                messages.error(request, "Erreur lors de la validation")
        
        elif action == 'validation_finale':
            # Validation finale et sélection du candidat
            candidat_final_id = request.POST.get('candidat_final_id')
            success = _validation_finale_candidat_fallback(demande, profil, candidat_final_id, commentaire)
            
            if success:
                messages.success(request, "Candidat sélectionné et notifié")
                return redirect('interim_validation', demande.id)
            else:
                messages.error(request, "Erreur lors de la sélection finale")
        
        elif action == 'refuser':
            # Refus de la demande
            success = _refuser_demande_validation_fallback(demande, profil, commentaire)
            
            if success:
                messages.success(request, "Demande refusée")
                return redirect('interim_validation', demande.id)
            else:
                messages.error(request, "Erreur lors du refus")
        
        return redirect('validation_avec_propositions', demande_id=demande.id)
        
    except Exception as e:
        logger.error(f"Erreur traitement validation: {e}")
        messages.error(request, "Erreur lors du traitement")
        return redirect('validation_avec_propositions', demande_id=demande.id)


def _peut_valider_niveau_actuel(profil, demande):
    """
    Vérifie si l'utilisateur peut valider au niveau actuel selon la hiérarchie
    
    NIVEAUX DE VALIDATION :
    - Niveau 1 : RESPONSABLE (N+1 du chef d'équipe)
    - Niveau 2 : DIRECTEUR (N+2)  
    - Niveau 3+ : RH/ADMIN (Validation finale)
    """
    niveau = demande.niveau_validation_actuel
    type_profil = getattr(profil, 'type_profil', None)
    
    # Accès total pour superutilisateurs
    if hasattr(profil, 'user') and profil.user.is_superuser:
        return True
    
    if type_profil == 'SUPERUSER':
        return True
    
    # CHEF_EQUIPE ne peut jamais valider
    if type_profil == 'CHEF_EQUIPE':
        return False
    
    # Niveau 1 : RESPONSABLE seulement
    if niveau == 1:
        return (type_profil == 'RESPONSABLE' and 
                getattr(profil, 'departement', None) == demande.poste.departement)
    
    # Niveau 2 : DIRECTEUR seulement  
    elif niveau == 2:
        return type_profil == 'DIRECTEUR'
    
    # Niveau 3+ : RH/ADMIN seulement
    elif niveau >= 3:
        return type_profil in ['RH', 'ADMIN']
    
    return False

# ================================================================
# API CANDIDATS DISPONIBLES (MANQUANTE)
# ================================================================

@login_required
def api_candidats_disponibles(request, demande_id):
    """API pour récupérer les candidats disponibles pour une demande"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if SERVICES_AVAILABLE:
            from .services.manager_proposals import ManagerProposalsService
            peut_proposer, _ = ManagerProposalsService.peut_proposer_candidat(profil, demande)
        else:
            peut_proposer = _peut_proposer_candidat_fallback(profil, demande)
        
        if not peut_proposer:
            return JsonResponse({'success': False, 'error': 'Permissions insuffisantes'})
        
        # Rechercher les candidats
        candidats_eligibles = _rechercher_candidats_eligibles(demande)
        
        # Formater pour JSON
        candidats_data = []
        for candidat_info in candidats_eligibles[:20]:  # Limiter à 20
            candidat = candidat_info['candidat']
            candidats_data.append({
                'id': candidat.id,
                'nom_complet': candidat.nom_complet,
                'matricule': candidat.matricule,
                'poste': candidat.poste.titre if candidat.poste else '',
                'departement': candidat.departement.nom if candidat.departement else '',
                'site': candidat.site.nom if candidat.site else '',
                'score': candidat_info['score'],
                'disponibilite': candidat_info['disponibilite'],
                'score_color': candidat_info['score_color']
            })
        
        return JsonResponse({
            'success': True,
            'candidats': candidats_data,
            'total': len(candidats_data)
        })
        
    except Exception as e:
        logger.error(f"Erreur API candidats disponibles: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_score_candidat_demande(request, candidat_id, demande_id):
    """API pour calculer le score d'un candidat pour une demande"""
    try:
        candidat = get_object_or_404(ProfilUtilisateur, id=candidat_id)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Calculer le score
        if SERVICES_AVAILABLE:
            from .services.scoring_service import ScoringInterimService
            scoring_service = ScoringInterimService()
            score = scoring_service.calculer_score_candidat(candidat, demande)
        else:
            score = _calculer_score_basique_candidat(candidat, demande)
        
        # Détails de disponibilité
        disponibilite = candidat.est_disponible_pour_interim(
            demande.date_debut, demande.date_fin
        ) if hasattr(candidat, 'est_disponible_pour_interim') else {'disponible': True, 'raisons': []}
        
        return JsonResponse({
            'success': True,
            'candidat_id': candidat.id,
            'demande_id': demande.id,
            'score': score,
            'disponibilite': disponibilite,
            'candidat_nom': candidat.nom_complet,
            'candidat_poste': candidat.poste.titre if candidat.poste else ''
        })
        
    except Exception as e:
        logger.error(f"Erreur calcul score API: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# FONCTIONS UTILITAIRES POUR LES VUES MANQUANTES
# ================================================================

def _get_etape_validation_actuelle(demande):
    """Retourne l'étape de validation actuelle"""
    if demande.statut == 'SOUMISE':
        return "En attente de validation N+1"
    elif demande.statut == 'EN_VALIDATION':
        if demande.niveau_validation_actuel == 1:
            return "Validation N+1 en cours"
        elif demande.niveau_validation_actuel == 2:
            return "Validation DRH en cours"
        else:
            return f"Validation niveau {demande.niveau_validation_actuel}"
    elif demande.statut == 'CANDIDAT_SELECTIONNE':
        return "En attente de réponse candidat"
    elif demande.statut == 'VALIDEE':
        return "Validée - Mission planifiée"
    else:
        return demande.get_statut_display()

def _peut_ajouter_candidat_validation(profil):
    """Vérifie si l'utilisateur peut ajouter un candidat lors de la validation"""
    return profil.type_profil in ['RH', 'DIRECTEUR', 'RESPONSABLE']

def _peut_proposer_candidat_fallback(profil, demande):
    """Version fallback pour vérifier les permissions de proposition"""
    return (
        profil.type_profil in ['RH', 'DIRECTEUR', 'RESPONSABLE', 'CHEF_EQUIPE'] or
        profil == demande.demandeur.manager
    )

def _calculer_score_basique_candidat(candidat, demande):
    """Calcul de score basique sans service"""
    score = 50  # Score de base
    
    # Même département
    if candidat.poste and demande.poste and candidat.poste.departement == demande.poste.departement:
        score += 20
    
    # Même site
    if candidat.site and demande.poste.site and candidat.site == demande.poste.site:
        score += 15
    
    # Employé actif
    if candidat.actif and candidat.statut_employe == 'ACTIF':
        score += 15
    
    return min(score, 100)

def _valider_niveau_suivant_fallback(demande, validateur, candidats_retenus, commentaire):
    """Fallback pour validation niveau suivant"""
    try:
        with transaction.atomic():
            # Créer la validation
            ValidationDemande.objects.create(
                demande=demande,
                type_validation=f'NIVEAU_{demande.niveau_validation_actuel + 1}',
                niveau_validation=demande.niveau_validation_actuel + 1,
                validateur=validateur,
                decision='APPROUVE',
                commentaire=commentaire,
                candidats_retenus=candidats_retenus
            )
            
            # Avancer le niveau
            demande.niveau_validation_actuel += 1
            
            if demande.niveau_validation_actuel >= demande.niveaux_validation_requis:
                demande.statut = 'VALIDATION_FINALE'
            else:
                demande.statut = 'EN_VALIDATION'
            
            demande.save()
            return True
    except Exception as e:
        logger.error(f"Erreur validation niveau suivant: {e}")
        return False

def _validation_finale_candidat_fallback(demande, validateur, candidat_final_id, commentaire):
    """Fallback pour validation finale avec sélection du candidat"""
    try:
        if not candidat_final_id:
            return False
            
        with transaction.atomic():
            candidat_final = ProfilUtilisateur.objects.get(id=candidat_final_id)
            
            # Mettre à jour la demande
            demande.candidat_selectionne = candidat_final
            demande.statut = 'CANDIDAT_SELECTIONNE'
            demande.date_validation = timezone.now()
            demande.save()
            
            # Créer la réponse candidat
            reponse, created = ReponseCandidatInterim.objects.get_or_create(
                demande=demande,
                candidat=candidat_final,
                date_limite_reponse=timezone.now() + timezone.timedelta(days=3)
            )
            
            return True
    except Exception as e:
        logger.error(f"Erreur validation finale: {e}")
        return False

def _refuser_demande_validation_fallback(demande, validateur, commentaire):
    """Fallback pour refus de demande lors de la validation"""
    try:
        with transaction.atomic():
            # Créer la validation de refus
            ValidationDemande.objects.create(
                demande=demande,
                type_validation=f'NIVEAU_{demande.niveau_validation_actuel}',
                niveau_validation=demande.niveau_validation_actuel,
                validateur=validateur,
                decision='REFUSE',
                commentaire=commentaire,
                date_validation=timezone.now()
            )
            
            # Mettre à jour la demande
            demande.statut = 'REFUSEE'
            demande.save()
            
            return True
    except Exception as e:
        logger.error(f"Erreur refus demande: {e}")
        return False

@login_required
def demande_interim_propositions_liste(request, demande_id):
    """
    Affiche la liste des propositions pour une demande d'intérim
    Accessible aux validateurs et aux personnes autorisées
    """
    try:
        # Récupération de la demande avec optimisations
        demande = get_object_or_404(
            DemandeInterim.objects.select_related(
                'demandeur__user', 
                'personne_remplacee__user',
                'poste__departement',
                'poste__site',
                'motif_absence'
            ).prefetch_related(
                'propositions_candidats__candidat_propose__user',
                'propositions_candidats__proposant__user',
                'propositions_candidats__candidat_propose__poste',
                'propositions_candidats__candidat_propose__departement',
                'validations'
            ),
            id=demande_id
        )
        
        # Récupération du profil utilisateur
        profil_utilisateur = get_user_profil(request.user)
        if not profil_utilisateur:
            messages.error(request, "Profil utilisateur non trouvé")
            return redirect('connexion')
        
        # Vérification des permissions
        peut_voir, raison = peut_voir_demande_interim(profil_utilisateur, demande)
        if not peut_voir:
            logger.warning(f"Accès refusé à {profil_utilisateur.nom_complet} pour voir les propositions de {demande.numero_demande}: {raison}")
            messages.error(request, f"Accès refusé: {raison}")
            return redirect('connexion')
        
        # Permissions détaillées
        permissions = {
            'peut_voir_scores_detailles': _peut_voir_scores_detailles(profil_utilisateur, demande),
            'peut_evaluer_propositions': _peut_evaluer_propositions(profil_utilisateur, demande),
            'peut_retenir_candidats': _peut_retenir_candidats(profil_utilisateur, demande),
            'peut_ajouter_proposition': _peut_ajouter_proposition(profil_utilisateur, demande),
            'peut_modifier_scores': _peut_modifier_scores(profil_utilisateur, demande),
            'peut_voir_justifications': _peut_voir_justifications(profil_utilisateur, demande),
        }
        
        # Filtres depuis les paramètres GET
        filtres = _extraire_filtres_propositions(request.GET)
        
        # Récupération des propositions avec filtrage
        propositions_query = demande.propositions_candidats.select_related(
            'candidat_propose__user',
            'candidat_propose__poste',
            'candidat_propose__departement',
            'candidat_propose__site',
            'proposant__user',
            'evaluateur__user'
        ).prefetch_related(
            'candidat_propose__competences__competence',
            'candidat_propose__formations',
            'score_candidat'
        )
        
        # Application des filtres
        propositions_query = _appliquer_filtres_propositions(propositions_query, filtres)
        
        # Tri des propositions
        tri = request.GET.get('tri', 'score_final')
        ordre = request.GET.get('ordre', 'desc')
        
        tri_mapping = {
            'score_final': '-score_final' if ordre == 'desc' else 'score_final',
            'nom': 'candidat_propose__user__last_name',
            'poste': 'candidat_propose__poste__titre',
            'departement': 'candidat_propose__departement__nom',
            'date_proposition': '-created_at' if ordre == 'desc' else 'created_at',
            'proposant': 'proposant__user__last_name',
            'statut': 'statut'
        }
        
        propositions_query = propositions_query.order_by(
            tri_mapping.get(tri, '-score_final')
        )
        
        # Pagination
        paginator = Paginator(propositions_query, 20)
        page = request.GET.get('page', 1)
        
        try:
            propositions = paginator.page(page)
        except PageNotAnInteger:
            propositions = paginator.page(1)
        except EmptyPage:
            propositions = paginator.page(paginator.num_pages)
        
        # Préparation des données enrichies pour chaque proposition
        propositions_enrichies = []
        for proposition in propositions:
            donnees_proposition = _enrichir_proposition_candidat(
                proposition, demande, permissions
            )
            propositions_enrichies.append(donnees_proposition)
        
        # Statistiques des propositions
        stats_propositions = _calculer_statistiques_propositions(demande, filtres)
        
        # Informations sur le niveau de validation actuel
        niveau_validation_info = _get_niveau_validation_info(demande, profil_utilisateur)
        
        # Historique récent des actions sur les propositions
        historique_recent = _get_historique_recent_propositions(demande, limit=5)
        
        # Candidats déjà retenus/rejetés
        candidats_traites = _get_candidats_traites(demande)
        
        # Configuration de scoring active
        config_scoring = _get_configuration_scoring_active(demande)
        
        # Options de tri pour le template
        options_tri = [
            ('score_final', 'Score final'),
            ('nom', 'Nom candidat'),
            ('poste', 'Poste actuel'),
            ('departement', 'Département'),
            ('date_proposition', 'Date proposition'),
            ('proposant', 'Proposé par'),
            ('statut', 'Statut')
        ]
        
        # Options de filtrage pour le template
        statuts_disponibles = PropositionCandidat.STATUTS_PROPOSITION
        sources_disponibles = PropositionCandidat.SOURCES_PROPOSITION
        departements_filtre = _get_departements_pour_filtre(demande, profil_utilisateur)
        
        # Informations contextuelles
        context = {
            'demande': demande,
            'propositions': propositions_enrichies,
            'propositions_paginator': propositions,
            'profil_utilisateur': profil_utilisateur,
            'permissions': permissions,
            'stats_propositions': stats_propositions,
            'niveau_validation_info': niveau_validation_info,
            'historique_recent': historique_recent,
            'candidats_traites': candidats_traites,
            'config_scoring': config_scoring,
            
            # Filtres et tri
            'filtres': filtres,
            'options_tri': options_tri,
            'tri_actuel': tri,
            'ordre_actuel': ordre,
            'statuts_disponibles': statuts_disponibles,
            'sources_disponibles': sources_disponibles,
            'departements_filtre': departements_filtre,
            
            # Configuration UI
            'page_title': f'Propositions - {demande.numero_demande}',
            'breadcrumb': [
                ('Dashboard', reverse('connexion')),
                ('Demandes', reverse('demande_interim_propositions_liste', args=[demande.id])),                
                ('Propositions', '')
            ],
            
            # URLs pour actions AJAX
            #'url_evaluer_proposition': reverse('ajax_evaluer_proposition'),
            #'url_retenir_proposition': reverse('ajax_retenir_proposition'), 
            #'url_ajouter_proposition': reverse('ajax_ajouter_proposition'),
            #'url_scores_details': reverse('ajax_scores_details'),
        }
        
        # Log de l'accès
        logger.info(f"Consultation propositions {demande.numero_demande} par {profil_utilisateur.nom_complet}")
        
        # Réponse AJAX pour rafraîchissement partiel
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'html': render(request, 'interim/propositions/ajax_liste_propositions.html', context).content.decode('utf-8'),
                'stats': stats_propositions,
                'nb_propositions': len(propositions_enrichies)
            })
        
        return render(request, 'demande_interim_propositions_liste.html', context)
        
    except Exception as e:
        logger.error(f"Erreur consultation propositions demande {demande_id}: {str(e)}", exc_info=True)
        messages.error(request, "Erreur lors de l'affichage des propositions")
        return redirect('connexion')


def _peut_voir_scores_detailles(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut voir les scores détaillés"""
    if profil_utilisateur.is_superuser:
        return True
    
    return profil_utilisateur.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']


def _peut_retenir_candidats(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut retenir des candidats"""
    return _peut_evaluer_propositions(profil_utilisateur, demande)


def _peut_ajouter_proposition(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut ajouter une nouvelle proposition"""
    if not demande.propositions_autorisees:
        return False
    
    peut_proposer, _ = profil_utilisateur.peut_proposer_candidat(demande)
    return peut_proposer


def _peut_modifier_scores(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut modifier les scores"""
    if profil_utilisateur.is_superuser:
        return True
    
    return profil_utilisateur.type_profil in ['RH', 'ADMIN']


def _peut_voir_justifications(profil_utilisateur, demande):
    """Vérifie si l'utilisateur peut voir les justifications détaillées"""
    if profil_utilisateur.is_superuser:
        return True
    
    return profil_utilisateur.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']


def _extraire_filtres_propositions(get_params):
    """Extrait les filtres depuis les paramètres GET"""
    return {
        'statut': get_params.get('statut', ''),
        'source': get_params.get('source', ''),
        'departement': get_params.get('departement', ''),
        'score_min': get_params.get('score_min', ''),
        'score_max': get_params.get('score_max', ''),
        'proposant': get_params.get('proposant', ''),
        'recherche': get_params.get('recherche', '').strip(),
        'date_debut': get_params.get('date_debut', ''),
        'date_fin': get_params.get('date_fin', ''),
        'avec_evaluation': get_params.get('avec_evaluation', ''),
    }


def _appliquer_filtres_propositions(queryset, filtres):
    """Applique les filtres à la requête des propositions"""
    if filtres['statut']:
        queryset = queryset.filter(statut=filtres['statut'])
    
    if filtres['source']:
        queryset = queryset.filter(source_proposition=filtres['source'])
    
    if filtres['departement']:
        queryset = queryset.filter(candidat_propose__departement_id=filtres['departement'])
    
    if filtres['score_min']:
        try:
            score_min = int(filtres['score_min'])
            queryset = queryset.filter(score_final__gte=score_min)
        except ValueError:
            pass
    
    if filtres['score_max']:
        try:
            score_max = int(filtres['score_max'])
            queryset = queryset.filter(score_final__lte=score_max)
        except ValueError:
            pass
    
    if filtres['proposant']:
        queryset = queryset.filter(
            Q(proposant__user__first_name__icontains=filtres['proposant']) |
            Q(proposant__user__last_name__icontains=filtres['proposant']) |
            Q(proposant__matricule__icontains=filtres['proposant'])
        )
    
    if filtres['recherche']:
        queryset = queryset.filter(
            Q(candidat_propose__user__first_name__icontains=filtres['recherche']) |
            Q(candidat_propose__user__last_name__icontains=filtres['recherche']) |
            Q(candidat_propose__matricule__icontains=filtres['recherche']) |
            Q(justification__icontains=filtres['recherche']) |
            Q(candidat_propose__poste__titre__icontains=filtres['recherche'])
        )
    
    if filtres['date_debut']:
        try:
            date_debut = datetime.strptime(filtres['date_debut'], '%Y-%m-%d').date()
            queryset = queryset.filter(created_at__date__gte=date_debut)
        except ValueError:
            pass
    
    if filtres['date_fin']:
        try:
            date_fin = datetime.strptime(filtres['date_fin'], '%Y-%m-%d').date()
            queryset = queryset.filter(created_at__date__lte=date_fin)
        except ValueError:
            pass
    
    if filtres['avec_evaluation']:
        if filtres['avec_evaluation'] == 'oui':
            queryset = queryset.filter(date_evaluation__isnull=False)
        elif filtres['avec_evaluation'] == 'non':
            queryset = queryset.filter(date_evaluation__isnull=True)
    
    return queryset

def _calculer_statistiques_propositions(demande, filtres):
    """Calcule les statistiques des propositions"""
    propositions_base = demande.propositions_candidats.all()
    
    # Appliquer les mêmes filtres pour les stats
    propositions_filtrees = _appliquer_filtres_propositions(propositions_base, filtres)
    
    stats = {
        'total_propositions': propositions_filtrees.count(),
        'par_statut': {},
        'par_source': {},
        'score_moyen': 0,
        'score_max': 0,
        'score_min': 0,
        'avec_evaluation': 0,
        'sans_evaluation': 0,
        'retenus': 0,
        'rejetes': 0,
    }
    
    if stats['total_propositions'] > 0:
        # Stats par statut
        for statut, libelle in PropositionCandidat.STATUTS_PROPOSITION:
            count = propositions_filtrees.filter(statut=statut).count()
            stats['par_statut'][statut] = {
                'count': count,
                'libelle': libelle,
                'pourcentage': round((count / stats['total_propositions']) * 100, 1)
            }
        
        # Stats par source
        for source, libelle in PropositionCandidat.SOURCES_PROPOSITION:
            count = propositions_filtrees.filter(source_proposition=source).count()
            if count > 0:
                stats['par_source'][source] = {
                    'count': count,
                    'libelle': libelle,
                    'pourcentage': round((count / stats['total_propositions']) * 100, 1)
                }
        
        # Stats des scores
        scores_stats = propositions_filtrees.aggregate(
            score_moyen=Avg('score_final'),
            score_max=Max('score_final'),
            score_min=Min('score_final')
        )
        
        stats.update({
            'score_moyen': round(scores_stats['score_moyen'] or 0, 1),
            'score_max': scores_stats['score_max'] or 0,
            'score_min': scores_stats['score_min'] or 0,
        })
        
        # Stats évaluations
        stats['avec_evaluation'] = propositions_filtrees.filter(date_evaluation__isnull=False).count()
        stats['sans_evaluation'] = stats['total_propositions'] - stats['avec_evaluation']
        
        # Stats retenus/rejetés
        stats['retenus'] = propositions_filtrees.filter(statut='RETENUE').count()
        stats['rejetes'] = propositions_filtrees.filter(statut='REJETEE').count()
    
    return stats


def _get_niveau_validation_info(demande, profil_utilisateur):
    """Récupère les informations sur le niveau de validation actuel"""
    niveau_actuel = demande.niveau_validation_actuel
    niveaux_requis = demande.niveaux_validation_requis
    
    niveaux_info = {
        1: {'libelle': 'Responsable (N+1)', 'icone': '👔'},
        2: {'libelle': 'Directeur (N+2)', 'icone': '🏢'},
        3: {'libelle': 'RH/Admin (Final)', 'icone': '👨‍💼'},
    }
    
    return {
        'niveau_actuel': niveau_actuel,
        'niveaux_requis': niveaux_requis,
        'niveau_info': niveaux_info.get(niveau_actuel, {}),
        'peut_valider_niveau': profil_utilisateur.peut_valider_niveau(niveau_actuel),
        'progression_pourcentage': round((niveau_actuel / niveaux_requis) * 100, 1),
    }


def _get_historique_recent_propositions(demande, limit=5):
    """Récupère l'historique récent des actions sur les propositions"""
    return HistoriqueAction.objects.filter(
        demande=demande,
        action__in=['PROPOSITION_CANDIDAT', 'EVALUATION_CANDIDAT', 'SELECTION_CANDIDAT']
    ).select_related(
        'utilisateur__user',
        'proposition__candidat_propose__user'
    ).order_by('-created_at')[:limit]


def _get_candidats_traites(demande):
    """Récupère les candidats déjà traités (retenus/rejetés)"""
    return {
        'retenus': demande.propositions_candidats.filter(statut='RETENUE').select_related('candidat_propose__user'),
        'rejetes': demande.propositions_candidats.filter(statut='REJETEE').select_related('candidat_propose__user'),
    }


def _get_configuration_scoring_active(demande):
    """Récupère la configuration de scoring active"""
    try:
        config = ConfigurationScoring.objects.filter(
            actif=True,
            configuration_par_defaut=True
        ).first()
        
        if not config:
            config = ConfigurationScoring.objects.filter(actif=True).first()
        
        return config
    except Exception:
        return None


def _get_departements_pour_filtre(demande, profil_utilisateur):
    """Récupère les départements disponibles pour le filtre"""
    from .models import Departement
    
    if profil_utilisateur.is_superuser or profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return Departement.objects.filter(actif=True).order_by('nom')
    
    # Limiter aux départements pertinents selon le profil
    departements_ids = set()
    
    # Département de l'utilisateur
    if profil_utilisateur.departement:
        departements_ids.add(profil_utilisateur.departement.id)
    
    # Département de la demande
    if demande.poste and demande.poste.departement:
        departements_ids.add(demande.poste.departement.id)
    
    return Departement.objects.filter(
        id__in=departements_ids,
        actif=True
    ).order_by('nom')


# Fonctions utilitaires pour l'enrichissement des données

def _verifier_disponibilite_candidat(candidat, demande):
    """Vérifie la disponibilité du candidat pour la période"""
    if not demande.date_debut or not demande.date_fin:
        return {'disponible': None, 'raison': 'Dates non définies'}
    
    try:
        # Vérifier les absences
        absences_periode = candidat.absences.filter(
            date_debut__lte=demande.date_fin,
            date_fin__gte=demande.date_debut
        )
        
        if absences_periode.exists():
            absence = absences_periode.first()
            return {
                'disponible': False,
                'raison': f'Absence: {absence.type_absence}',
                'details': absence
            }
        
        # CORRECTION: Vérifier les autres missions d'intérim via le bon modèle
        # Option 1: Via DemandeInterim directement
        autres_missions = DemandeInterim.objects.filter(
            candidat_selectionne=candidat,
            date_debut__lte=demande.date_fin,
            date_fin__gte=demande.date_debut,
            statut='EN_COURS'
        ).exclude(id=demande.id)
        
        if autres_missions.exists():
            mission = autres_missions.first()
            return {
                'disponible': False,
                'raison': f'Déjà en mission: {mission.poste.titre}',
                'details': mission
            }
        
        # Option 2: Via ReponseCandidatInterim (si c'est le modèle correct)
        try:
            reponses_acceptees = candidat.reponses_interim.filter(
                reponse='ACCEPTE',
                demande__date_debut__lte=demande.date_fin,
                demande__date_fin__gte=demande.date_debut,
                demande__statut='EN_COURS'
            ).exclude(demande=demande)
            
            if reponses_acceptees.exists():
                reponse = reponses_acceptees.first()
                return {
                    'disponible': False,
                    'raison': f'Mission acceptée: {reponse.demande.poste.titre}',
                    'details': reponse.demande
                }
        except Exception as e:
            logger.warning(f"Erreur vérification réponses interim: {e}")
        
        return {'disponible': True, 'raison': 'Disponible'}
        
    except Exception as e:
        logger.error(f"Erreur vérification disponibilité candidat {candidat.id}: {e}")
        return {'disponible': None, 'raison': 'Erreur de vérification'}


# AJOUT: Import nécessaire en haut du fichier utils.py
def _enrichir_proposition_candidat(proposition, demande, permissions):
    """Enrichit une proposition avec des données calculées"""
    candidat = proposition.candidat_propose
    
    # Import local pour éviter les imports circulaires
    from .models import ScoreDetailCandidat, DemandeInterim
    
    # Score détaillé si disponible
    score_detail = None
    if permissions['peut_voir_scores_detailles']:
        try:
            score_detail = ScoreDetailCandidat.objects.get(
                candidat=candidat,
                demande_interim=demande,
                proposition_humaine=proposition
            )
        except ScoreDetailCandidat.DoesNotExist:
            pass
    
    # Disponibilité du candidat
    disponibilite = _verifier_disponibilite_candidat(candidat, demande)
    
    # Compétences pertinentes
    competences_pertinentes = _get_competences_pertinentes(candidat, demande)
    
    # Historique avec ce type de poste
    experience_similaire = _get_experience_similaire(candidat, demande.poste)
    
    # Temps depuis la proposition
    temps_depuis_proposition = timezone.now() - proposition.created_at
    
    return {
        'proposition': proposition,
        'candidat': candidat,
        'score_detail': score_detail,
        'disponibilite': disponibilite,
        'competences_pertinentes': competences_pertinentes,
        'experience_similaire': experience_similaire,
        'temps_depuis_proposition_display': _format_duree(temps_depuis_proposition),
        'peut_etre_retenu': _peut_candidat_etre_retenu(proposition, permissions),
        'statut_display': _get_statut_proposition_display(proposition),
        'score_classe_css': _get_score_classe_css(proposition.score_final),
        'badges_candidat': _get_badges_candidat(candidat, demande),
    }

def _get_competences_pertinentes(candidat, demande):
    """Récupère les compétences pertinentes du candidat pour le poste"""
    # Ici, on pourrait implémenter une logique plus sophistiquée
    # pour déterminer quelles compétences sont pertinentes
    
    return candidat.competences.filter(
        niveau_maitrise__gte=2  # Intermédiaire et plus
    ).select_related('competence').order_by('-niveau_maitrise')[:5]


def _get_experience_similaire(candidat, poste_demande):
    """Détermine l'expérience similaire du candidat"""
    experience = {
        'meme_poste': False,
        'meme_departement': False,
        'niveau_similaire': False,
        'details': []
    }
    
    if candidat.poste:
        # Même poste exact
        if candidat.poste.id == poste_demande.id:
            experience['meme_poste'] = True
            experience['details'].append('Poste identique')
        
        # Même département
        elif candidat.poste.departement == poste_demande.departement:
            experience['meme_departement'] = True
            experience['details'].append(f'Même département: {poste_demande.departement.nom}')
        
        # Niveau de responsabilité similaire
        if candidat.poste.niveau_responsabilite == poste_demande.niveau_responsabilite:
            experience['niveau_similaire'] = True
            experience['details'].append(f'Niveau similaire: {poste_demande.get_niveau_responsabilite_display()}')
    
    return experience


def _format_duree(timedelta_obj):
    """Formate une durée en texte lisible"""
    total_seconds = int(timedelta_obj.total_seconds())
    
    if total_seconds < 3600:  # Moins d'1 heure
        minutes = total_seconds // 60
        return f"{minutes} min"
    elif total_seconds < 86400:  # Moins d'1 jour
        heures = total_seconds // 3600
        return f"{heures}h"
    else:  # Plus d'1 jour
        jours = total_seconds // 86400
        return f"{jours} jour{'s' if jours > 1 else ''}"


def _peut_candidat_etre_retenu(proposition, permissions):
    """Vérifie si un candidat peut être retenu"""
    if not permissions['peut_retenir_candidats']:
        return False
    
    return proposition.statut in ['SOUMISE', 'EN_EVALUATION', 'EVALUEE']


def _get_statut_proposition_display(proposition):
    """Retourne l'affichage formaté du statut avec icône"""
    statuts_display = {
        'SOUMISE': {'icone': '📝', 'classe': 'badge-primary', 'libelle': 'Soumise'},
        'EN_EVALUATION': {'icone': '⏳', 'classe': 'badge-warning', 'libelle': 'En évaluation'},
        'EVALUEE': {'icone': ' ', 'classe': 'badge-info', 'libelle': 'Évaluée'},
        'RETENUE': {'icone': '🎯', 'classe': 'badge-success', 'libelle': 'Retenue'},
        'REJETEE': {'icone': '❌', 'classe': 'badge-danger', 'libelle': 'Rejetée'},
        'VALIDEE': {'icone': '✔️', 'classe': 'badge-success', 'libelle': 'Validée'},
    }
    
    return statuts_display.get(proposition.statut, {
        'icone': '❓',
        'classe': 'badge-secondary',
        'libelle': proposition.get_statut_display()
    })


def _get_score_classe_css(score):
    """Retourne la classe CSS selon le score"""
    if score >= 80:
        return 'score-excellent'
    elif score >= 65:
        return 'score-bon'
    elif score >= 50:
        return 'score-moyen'
    else:
        return 'score-faible'


def _get_badges_candidat(candidat, demande):
    """Génère les badges d'information pour un candidat"""
    badges = []
    
    # Badge disponibilité
    if hasattr(candidat, 'extended_data') and candidat.extended_data:
        if candidat.extended_data.disponible_interim:
            badges.append({
                'texte': 'Disponible intérim',
                'classe': 'badge-success',
                'icone': ' '
            })
    
    # Badge même département
    if candidat.departement == demande.poste.departement:
        badges.append({
            'texte': 'Même département',
            'classe': 'badge-info',
            'icone': '🏢'
        })
    
    # Badge même site
    if candidat.site == demande.poste.site:
        badges.append({
            'texte': 'Même site',
            'classe': 'badge-info',
            'icone': '📍'
        })
    
    # Badge expérience
    if candidat.poste and candidat.poste.niveau_responsabilite >= demande.poste.niveau_responsabilite:
        badges.append({
            'texte': 'Niveau approprié',
            'classe': 'badge-primary',
            'icone': '⭐'
        })
    
    return badges

# ================================================================
# FONCTION GET_USER_PROFIL
# ================================================================

def get_user_profil(user: User) -> Optional['ProfilUtilisateur']:
    """
    Récupère le profil utilisateur associé à un User Django
    
    Args:
        user: Instance User Django
        
    Returns:
        ProfilUtilisateur ou None si non trouvé
        
    Example:
        profil = get_user_profil(request.user)
        if profil:
            print(f"Type: {profil.type_profil}")
    """
    if not user or not user.is_authenticated:
        logger.warning("Tentative d'accès avec utilisateur non authentifié")
        return None
    
    try:
        # Import local pour éviter les imports circulaires
        from .models import ProfilUtilisateur
        
        # Recherche avec optimisation des requêtes
        profil = ProfilUtilisateur.objects.select_related(
            'user', 
            'departement', 
            'site', 
            'poste',
            'manager'
        ).prefetch_related(
            'competences__competence',
            'kelio_data',
            'extended_data'
        ).filter(
            user=user,
            actif=True
        ).first()
        
        if not profil:
            logger.warning(f"Aucun profil actif trouvé pour l'utilisateur {user.username} (ID: {user.id})")
            return None
            
        logger.debug(f"Profil trouvé: {profil.nom_complet} - {profil.type_profil}")
        return profil
        
    except ObjectDoesNotExist:
        logger.warning(f"Profil non trouvé pour l'utilisateur {user.username}")
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du profil pour {user.username}: {str(e)}", exc_info=True)
        return None


def get_user_profil_with_cache(user: User, cache_duration_seconds: int = 300) -> Optional['ProfilUtilisateur']:
    """
    Version avec cache de get_user_profil pour optimiser les performances
    
    Args:
        user: Instance User Django
        cache_duration_seconds: Durée du cache en secondes (défaut: 5 minutes)
        
    Returns:
        ProfilUtilisateur ou None
    """
    if not user or not user.is_authenticated:
        return None
    
    try:
        from django.core.cache import cache
        
        cache_key = f"user_profil_{user.id}"
        profil = cache.get(cache_key)
        
        if profil is None:
            profil = get_user_profil(user)
            if profil:
                cache.set(cache_key, profil, cache_duration_seconds)
                logger.debug(f"Profil mis en cache pour {user.username}")
        else:
            logger.debug(f"Profil récupéré du cache pour {user.username}")
            
        return profil
        
    except Exception as e:
        logger.error(f"Erreur cache profil pour {user.username}: {str(e)}")
        # Fallback sur la version sans cache
        return get_user_profil(user)


def invalidate_user_profil_cache(user: User) -> bool:
    """
    Invalide le cache du profil utilisateur
    
    Args:
        user: Instance User Django
        
    Returns:
        bool: True si invalidation réussie
    """
    try:
        from django.core.cache import cache
        
        cache_key = f"user_profil_{user.id}"
        cache.delete(cache_key)
        logger.debug(f"Cache invalidé pour {user.username}")
        return True
        
    except Exception as e:
        logger.error(f"Erreur invalidation cache pour {user.username}: {str(e)}")
        return False


# ================================================================
# FONCTION PEUT_VOIR_DEMANDE_INTERIM
# ================================================================

def peut_voir_demande_interim(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie si un utilisateur peut voir une demande d'intérim selon la hiérarchie
    
    Règles d'accès:
    - SUPERUSER: Accès complet à toutes les demandes
    - RH/ADMIN: Accès complet à toutes les demandes
    - DIRECTEUR: Accès aux demandes de son périmètre et niveaux inférieurs
    - RESPONSABLE: Accès aux demandes de son département et équipe
    - CHEF_EQUIPE: Accès aux demandes de son équipe et département
    - UTILISATEUR: Accès aux demandes qu'il a créées ou qui le concernent
    
    Args:
        profil_utilisateur: ProfilUtilisateur qui demande l'accès
        demande: DemandeInterim à consulter
        
    Returns:
        Tuple[bool, str]: (peut_voir, raison)
        
    Example:
        peut_voir, raison = peut_voir_demande_interim(profil, demande)
        if not peut_voir:
            return HttpResponseForbidden(raison)
    """
    if not profil_utilisateur:
        return False, "Profil utilisateur non défini"
    
    if not demande:
        return False, "Demande non définie"
    
    try:
        # ================================================================
        # ACCÈS COMPLET - SUPERUSERS
        # ================================================================
        
        if profil_utilisateur.is_superuser:
            logger.debug(f"Accès superuser accordé à {profil_utilisateur.nom_complet}")
            return True, "Accès superutilisateur"
        
        # ================================================================
        # ACCÈS COMPLET - RH ET ADMIN
        # ================================================================
        
        if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            logger.debug(f"Accès {profil_utilisateur.type_profil} accordé à {profil_utilisateur.nom_complet}")
            return True, f"Accès {profil_utilisateur.type_profil} - Périmètre complet"
        
        # ================================================================
        # ACCÈS DIRECTIONNEL - DIRECTEURS
        # ================================================================
        
        if profil_utilisateur.type_profil == 'DIRECTEUR':
            # Vérifier si la demande est dans le périmètre du directeur
            acces_directionnel = _verifier_acces_directionnel(profil_utilisateur, demande)
            if acces_directionnel[0]:
                logger.debug(f"Accès directionnel accordé à {profil_utilisateur.nom_complet}")
                return True, f"Accès directeur - {acces_directionnel[1]}"
        
        # ================================================================
        # ACCÈS DÉPARTEMENTAL - RESPONSABLES
        # ================================================================
        
        if profil_utilisateur.type_profil == 'RESPONSABLE':
            acces_departemental = _verifier_acces_departemental(profil_utilisateur, demande)
            if acces_departemental[0]:
                logger.debug(f"Accès départemental accordé à {profil_utilisateur.nom_complet}")
                return True, f"Accès responsable - {acces_departemental[1]}"
        
        # ================================================================
        # ACCÈS ÉQUIPE - CHEFS D'ÉQUIPE
        # ================================================================
        
        if profil_utilisateur.type_profil == 'CHEF_EQUIPE':
            acces_equipe = _verifier_acces_equipe(profil_utilisateur, demande)
            if acces_equipe[0]:
                logger.debug(f"Accès équipe accordé à {profil_utilisateur.nom_complet}")
                return True, f"Accès chef d'équipe - {acces_equipe[1]}"
        
        # ================================================================
        # ACCÈS PERSONNEL - UTILISATEURS STANDARDS
        # ================================================================
        
        # Vérifier l'accès personnel (créateur, personne remplacée, etc.)
        acces_personnel = _verifier_acces_personnel(profil_utilisateur, demande)
        if acces_personnel[0]:
            logger.debug(f"Accès personnel accordé à {profil_utilisateur.nom_complet}")
            return True, f"Accès personnel - {acces_personnel[1]}"
        
        # ================================================================
        # ACCÈS CONTEXTUEL - CAS SPÉCIAUX
        # ================================================================
        
        # Vérifier les accès contextuels (validation, proposition, etc.)
        acces_contextuel = _verifier_acces_contextuel(profil_utilisateur, demande)
        if acces_contextuel[0]:
            logger.debug(f"Accès contextuel accordé à {profil_utilisateur.nom_complet}")
            return True, f"Accès contextuel - {acces_contextuel[1]}"
        
        # ================================================================
        # ACCÈS REFUSÉ
        # ================================================================
        
        raison_refus = f"Accès refusé - Profil {profil_utilisateur.type_profil} sans droits sur cette demande"
        logger.warning(f"Accès refusé à {profil_utilisateur.nom_complet} pour demande {demande.numero_demande}: {raison_refus}")
        return False, raison_refus
        
    except Exception as e:
        logger.error(f"Erreur vérification accès demande {demande.numero_demande} pour {profil_utilisateur.nom_complet}: {str(e)}", exc_info=True)
        return False, "Erreur de vérification des droits"


# ================================================================
# FONCTIONS AUXILIAIRES DE VÉRIFICATION D'ACCÈS
# ================================================================

def _verifier_acces_directionnel(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie l'accès directionnel pour les directeurs
    
    Critères:
    - Même site que le directeur
    - Départements sous sa responsabilité
    - Demandes de niveau élevé/critique
    """
    try:
        # Même site
        if profil_utilisateur.site and demande.poste and demande.poste.site:
            if profil_utilisateur.site == demande.poste.site:
                return True, "Même site"
        
        # Départements gérés (si le directeur est responsable de site)
        if hasattr(profil_utilisateur, 'sites_geres') and profil_utilisateur.sites_geres.exists():
            sites_geres = profil_utilisateur.sites_geres.all()
            if demande.poste and demande.poste.site in sites_geres:
                return True, "Site sous responsabilité"
        
        # Départements sous responsabilité hiérarchique
        if hasattr(profil_utilisateur, 'departements_geres') and profil_utilisateur.departements_geres.exists():
            departements_geres = profil_utilisateur.departements_geres.all()
            if demande.poste and demande.poste.departement in departements_geres:
                return True, "Département sous responsabilité"
        
        # Demandes d'urgence élevée (escalade automatique)
        if demande.urgence in ['ELEVEE', 'CRITIQUE']:
            if profil_utilisateur.site and demande.poste and demande.poste.site:
                if profil_utilisateur.site == demande.poste.site:
                    return True, "Urgence élevée - Escalade automatique"
        
        return False, "Périmètre directionnel non applicable"
        
    except Exception as e:
        logger.error(f"Erreur vérification accès directionnel: {str(e)}")
        return False, "Erreur vérification directionnelle"


def _verifier_acces_departemental(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie l'accès départemental pour les responsables
    
    Critères:
    - Même département
    - Demandes concernant son équipe
    - Validation de niveau 1
    """
    try:
        # Même département que la demande
        if profil_utilisateur.departement and demande.poste and demande.poste.departement:
            if profil_utilisateur.departement == demande.poste.departement:
                return True, "Même département"
        
        # Département géré
        if hasattr(profil_utilisateur, 'departements_geres') and profil_utilisateur.departements_geres.exists():
            departements_geres = profil_utilisateur.departements_geres.all()
            if demande.poste and demande.poste.departement in departements_geres:
                return True, "Département géré"
        
        # Demandeur dans son équipe
        if demande.demandeur and demande.demandeur.manager == profil_utilisateur:
            return True, "Demandeur dans l'équipe"
        
        # Personne remplacée dans son équipe
        if demande.personne_remplacee and demande.personne_remplacee.manager == profil_utilisateur:
            return True, "Personne remplacée dans l'équipe"
        
        # Validation de niveau 1 requise
        if demande.niveau_validation_actuel == 1 and profil_utilisateur.peut_valider_niveau(1):
            if profil_utilisateur.departement and demande.poste and demande.poste.departement:
                if profil_utilisateur.departement == demande.poste.departement:
                    return True, "Validation niveau 1 - Même département"
        
        return False, "Périmètre départemental non applicable"
        
    except Exception as e:
        logger.error(f"Erreur vérification accès départemental: {str(e)}")
        return False, "Erreur vérification départementale"


def _verifier_acces_equipe(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie l'accès équipe pour les chefs d'équipe
    
    Critères:
    - Membres de son équipe directe
    - Même département
    - Propositions de candidats
    """
    try:
        # Membres de l'équipe directe
        equipe_directe = profil_utilisateur.equipe.filter(actif=True)
        
        # Demandeur dans l'équipe
        if demande.demandeur in equipe_directe:
            return True, "Demandeur dans l'équipe directe"
        
        # Personne remplacée dans l'équipe
        if demande.personne_remplacee in equipe_directe:
            return True, "Personne remplacée dans l'équipe directe"
        
        # Même département (vision élargie pour chef d'équipe)
        if profil_utilisateur.departement and demande.poste and demande.poste.departement:
            if profil_utilisateur.departement == demande.poste.departement:
                return True, "Même département"
        
        # A proposé un candidat pour cette demande
        from .models import PropositionCandidat
        propositions = PropositionCandidat.objects.filter(
            demande_interim=demande,
            proposant=profil_utilisateur
        )
        if propositions.exists():
            return True, "A proposé un candidat"
        
        return False, "Périmètre équipe non applicable"
        
    except Exception as e:
        logger.error(f"Erreur vérification accès équipe: {str(e)}")
        return False, "Erreur vérification équipe"


def _verifier_acces_personnel(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie l'accès personnel pour tous les utilisateurs
    
    Critères:
    - Créateur de la demande
    - Personne remplacée
    - Candidat proposé
    - Manager direct des personnes concernées
    """
    try:
        # Créateur de la demande
        if demande.demandeur == profil_utilisateur:
            return True, "Créateur de la demande"
        
        # Personne à remplacer
        if demande.personne_remplacee == profil_utilisateur:
            return True, "Personne à remplacer"
        
        # Candidat sélectionné
        if demande.candidat_selectionne == profil_utilisateur:
            return True, "Candidat sélectionné"
        
        # Manager direct du demandeur
        if demande.demandeur and demande.demandeur.manager == profil_utilisateur:
            return True, "Manager du demandeur"
        
        # Manager direct de la personne remplacée
        if demande.personne_remplacee and demande.personne_remplacee.manager == profil_utilisateur:
            return True, "Manager de la personne remplacée"
        
        # Candidat proposé pour cette demande
        from .models import PropositionCandidat
        candidat_propose = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=profil_utilisateur
        ).exists()
        
        if candidat_propose:
            return True, "Candidat proposé"
        
        # A proposé quelqu'un pour cette demande
        a_propose = PropositionCandidat.objects.filter(
            demande_interim=demande,
            proposant=profil_utilisateur
        ).exists()
        
        if a_propose:
            return True, "A proposé un candidat"
        
        return False, "Aucun lien personnel avec la demande"
        
    except Exception as e:
        logger.error(f"Erreur vérification accès personnel: {str(e)}")
        return False, "Erreur vérification personnelle"


def _verifier_acces_contextuel(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie l'accès contextuel (validations, notifications, etc.)
    
    Critères:
    - Validateur assigné
    - Notifications reçues
    - Droits de validation selon le niveau
    """
    try:
        # Validateur assigné à un niveau
        from .models import ValidationDemande
        validations_assignees = ValidationDemande.objects.filter(
            demande=demande,
            validateur=profil_utilisateur
        )
        
        if validations_assignees.exists():
            return True, "Validateur assigné"
        
        # Peut valider au niveau actuel
        if profil_utilisateur.peut_valider_niveau(demande.niveau_validation_actuel):
            # Vérifier si dans le bon périmètre pour valider
            if profil_utilisateur.type_profil == 'RESPONSABLE':
                if profil_utilisateur.departement and demande.poste and demande.poste.departement:
                    if profil_utilisateur.departement == demande.poste.departement:
                        return True, "Peut valider - Même département"
            
            elif profil_utilisateur.type_profil == 'DIRECTEUR':
                if profil_utilisateur.site and demande.poste and demande.poste.site:
                    if profil_utilisateur.site == demande.poste.site:
                        return True, "Peut valider - Même site"
        
        # Notifications reçues pour cette demande
        from .models import NotificationInterim
        notifications = NotificationInterim.objects.filter(
            demande=demande,
            destinataire=profil_utilisateur,
            statut__in=['NON_LUE', 'LUE']
        )
        
        if notifications.exists():
            return True, "Notifications reçues"
        
        # Droits de consultation par délégation
        if _verifier_delegation_droits(profil_utilisateur, demande):
            return True, "Accès par délégation"
        
        return False, "Aucun contexte d'accès"
        
    except Exception as e:
        logger.error(f"Erreur vérification accès contextuel: {str(e)}")
        return False, "Erreur vérification contextuelle"


def _verifier_delegation_droits(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> bool:
    """
    Vérifie les délégations de droits (remplacements, intérims de fonction)
    
    Critères:
    - Remplacement temporaire d'un responsable
    - Délégation de signature
    - Intérim de fonction
    """
    try:
        # Ici on pourrait implémenter un système de délégation
        # Par exemple, vérifier dans une table DelegationDroits
        # ou dans les données étendues du profil
        
        # Pour l'instant, retourner False
        # Cette fonctionnalité peut être ajoutée ultérieurement
        return False
        
    except Exception as e:
        logger.error(f"Erreur vérification délégation: {str(e)}")
        return False


# ================================================================
# FONCTIONS UTILITAIRES COMPLÉMENTAIRES
# ================================================================

def peut_modifier_propositions(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie si un utilisateur peut modifier les propositions d'une demande
    
    Args:
        profil_utilisateur: ProfilUtilisateur
        demande: DemandeInterim
        
    Returns:
        Tuple[bool, str]: (peut_modifier, raison)
    """
    if not profil_utilisateur or not demande:
        return False, "Paramètres manquants"
    
    # Superusers peuvent toujours modifier
    if profil_utilisateur.is_superuser:
        return True, "Droits superutilisateur"
    
    # RH et Admin peuvent toujours modifier
    if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return True, f"Droits {profil_utilisateur.type_profil}"
    
    # Vérifier si peut voir la demande d'abord
    peut_voir, _ = peut_voir_demande_interim(profil_utilisateur, demande)
    if not peut_voir:
        return False, "Accès à la demande non autorisé"
    
    # Vérifier si les propositions sont autorisées
    if not demande.propositions_autorisees:
        return False, "Propositions fermées pour cette demande"
    
    # Vérifier la date limite
    if demande.date_limite_propositions and timezone.now() > demande.date_limite_propositions:
        return False, "Date limite de proposition dépassée"
    
    # Vérifier les permissions métier
    peut_proposer, raison = profil_utilisateur.peut_proposer_candidat(demande)
    return peut_proposer, raison


def get_demandes_accessibles(profil_utilisateur: 'ProfilUtilisateur', **filtres) -> 'QuerySet':
    """
    Récupère les demandes accessibles à un utilisateur avec filtres optionnels
    
    Args:
        profil_utilisateur: ProfilUtilisateur
        **filtres: Filtres supplémentaires (statut, urgence, etc.)
        
    Returns:
        QuerySet des demandes accessibles
    """
    if not profil_utilisateur:
        from .models import DemandeInterim
        return DemandeInterim.objects.none()
    
    try:
        from .models import DemandeInterim
        
        # Superusers et RH/Admin voient tout
        if profil_utilisateur.is_superuser or profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            queryset = DemandeInterim.objects.all()
        
        # Directeurs : périmètre directionnel
        elif profil_utilisateur.type_profil == 'DIRECTEUR':
            queryset = DemandeInterim.objects.filter(
                Q(poste__site=profil_utilisateur.site) |
                Q(urgence__in=['ELEVEE', 'CRITIQUE'])
            )
        
        # Responsables : périmètre départemental
        elif profil_utilisateur.type_profil == 'RESPONSABLE':
            queryset = DemandeInterim.objects.filter(
                Q(poste__departement=profil_utilisateur.departement) |
                Q(demandeur__manager=profil_utilisateur) |
                Q(personne_remplacee__manager=profil_utilisateur)
            )
        
        # Chefs d'équipe : équipe et département
        elif profil_utilisateur.type_profil == 'CHEF_EQUIPE':
            equipe_ids = list(profil_utilisateur.equipe.values_list('id', flat=True))
            queryset = DemandeInterim.objects.filter(
                Q(poste__departement=profil_utilisateur.departement) |
                Q(demandeur_id__in=equipe_ids) |
                Q(personne_remplacee_id__in=equipe_ids)
            )
        
        # Utilisateurs standards : accès personnel
        else:
            queryset = DemandeInterim.objects.filter(
                Q(demandeur=profil_utilisateur) |
                Q(personne_remplacee=profil_utilisateur) |
                Q(candidat_selectionne=profil_utilisateur) |
                Q(propositions_candidats__candidat_propose=profil_utilisateur) |
                Q(propositions_candidats__proposant=profil_utilisateur)
            ).distinct()
        
        # Appliquer les filtres supplémentaires
        for key, value in filtres.items():
            if value is not None:
                filter_dict = {key: value}
                queryset = queryset.filter(**filter_dict)
        
        return queryset.select_related(
            'demandeur__user',
            'personne_remplacee__user',
            'poste__departement',
            'poste__site',
            'motif_absence'
        ).order_by('-created_at')
        
    except Exception as e:
        logger.error(f"Erreur récupération demandes accessibles pour {profil_utilisateur.nom_complet}: {str(e)}")
        from .models import DemandeInterim
        return DemandeInterim.objects.none()


def log_acces_demande(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim', action: str = 'CONSULTATION'):
    """
    Enregistre l'accès à une demande pour audit
    
    Args:
        profil_utilisateur: ProfilUtilisateur qui accède
        demande: DemandeInterim consultée
        action: Type d'action (CONSULTATION, MODIFICATION, etc.)
    """
    try:
        from .models import HistoriqueAction
        
        HistoriqueAction.objects.create(
            demande=demande,
            action=action,
            utilisateur=profil_utilisateur,
            description=f"{action} par {profil_utilisateur.nom_complet}",
            niveau_hierarchique=profil_utilisateur.type_profil,
            is_superuser=profil_utilisateur.is_superuser
        )
        
        logger.info(f"Accès enregistré: {profil_utilisateur.nom_complet} - {action} - {demande.numero_demande}")
        
    except Exception as e:
        logger.error(f"Erreur enregistrement accès: {str(e)}")


# ================================================================
# FONCTIONS DE VALIDATION DES PERMISSIONS AVANCÉES
# ================================================================

def peut_escalader_demande(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie si un utilisateur peut escalader une demande au niveau supérieur
    """
    if not profil_utilisateur or not demande:
        return False, "Paramètres manquants"
    
    # Superusers peuvent escalader
    if profil_utilisateur.is_superuser:
        return True, "Droits superutilisateur"
    
    # Seuls les validateurs peuvent escalader
    if profil_utilisateur.type_profil not in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']:
        return False, "Profil non autorisé à escalader"
    
    # Vérifier si peut valider au niveau actuel
    if not profil_utilisateur.peut_valider_niveau(demande.niveau_validation_actuel):
        return False, "Niveau de validation non autorisé"
    
    # Vérifier qu'il reste des niveaux supérieurs
    if demande.niveau_validation_actuel >= demande.niveaux_validation_requis:
        return False, "Niveau maximum atteint"
    
    return True, "Escalade autorisée"


def peut_annuler_demande(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Tuple[bool, str]:
    """
    Vérifie si un utilisateur peut annuler une demande
    """
    if not profil_utilisateur or not demande:
        return False, "Paramètres manquants"
    
    # Superusers peuvent annuler
    if profil_utilisateur.is_superuser:
        return True, "Droits superutilisateur"
    
    # RH et Admin peuvent annuler
    if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return True, f"Droits {profil_utilisateur.type_profil}"
    
    # Le créateur peut annuler sa propre demande si pas encore validée
    if demande.demandeur == profil_utilisateur and demande.statut in ['BROUILLON', 'SOUMISE']:
        return True, "Créateur de la demande"
    
    # Les managers peuvent annuler les demandes de leur équipe
    if demande.demandeur and demande.demandeur.manager == profil_utilisateur:
        if demande.statut not in ['EN_COURS', 'TERMINEE']:
            return True, "Manager du demandeur"
    
    return False, "Annulation non autorisée"


# ================================================================
# LOGGING ET DEBUG
# ================================================================

def debug_permissions_demande(profil_utilisateur: 'ProfilUtilisateur', demande: 'DemandeInterim') -> Dict[str, Any]:
    """
    Fonction de debug pour analyser les permissions sur une demande
    
    Args:
        profil_utilisateur: ProfilUtilisateur
        demande: DemandeInterim
        
    Returns:
        Dict avec toutes les informations de permissions
    """
    debug_info = {
        'utilisateur': {
            'nom': profil_utilisateur.nom_complet if profil_utilisateur else 'None',
            'type_profil': profil_utilisateur.type_profil if profil_utilisateur else 'None',
            'is_superuser': profil_utilisateur.is_superuser if profil_utilisateur else False,
            'departement': profil_utilisateur.departement.nom if profil_utilisateur and profil_utilisateur.departement else 'None',
            'site': profil_utilisateur.site.nom if profil_utilisateur and profil_utilisateur.site else 'None',
        },
        'demande': {
            'numero': demande.numero_demande if demande else 'None',
            'statut': demande.statut if demande else 'None',
            'demandeur': demande.demandeur.nom_complet if demande and demande.demandeur else 'None',
            'departement': demande.poste.departement.nom if demande and demande.poste and demande.poste.departement else 'None',
            'site': demande.poste.site.nom if demande and demande.poste and demande.poste.site else 'None',
            'urgence': demande.urgence if demande else 'None',
            'niveau_validation': demande.niveau_validation_actuel if demande else 0,
        },
        'verifications': {}
    }
    
    if profil_utilisateur and demande:
        # Tester toutes les vérifications
        debug_info['verifications']['peut_voir'] = peut_voir_demande_interim(profil_utilisateur, demande)
        debug_info['verifications']['peut_modifier_propositions'] = peut_modifier_propositions(profil_utilisateur, demande)
        debug_info['verifications']['peut_escalader'] = peut_escalader_demande(profil_utilisateur, demande)
        debug_info['verifications']['peut_annuler'] = peut_annuler_demande(profil_utilisateur, demande)
        
        # Vérifications détaillées
        debug_info['verifications']['acces_directionnel'] = _verifier_acces_directionnel(profil_utilisateur, demande)
        debug_info['verifications']['acces_departemental'] = _verifier_acces_departemental(profil_utilisateur, demande)
        debug_info['verifications']['acces_equipe'] = _verifier_acces_equipe(profil_utilisateur, demande)
        debug_info['verifications']['acces_personnel'] = _verifier_acces_personnel(profil_utilisateur, demande)
        debug_info['verifications']['acces_contextuel'] = _verifier_acces_contextuel(profil_utilisateur, demande)
    
    return debug_info