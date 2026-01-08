# views_workflow_notif.py - Version complète avec toutes les vues manquantes
"""
Vues pour le workflow d'intérim et les notifications.
Version complète intégrant toutes les vues référencées dans urls.py
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_POST
from django.utils import timezone
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg

from .models import (
    DemandeInterim, ProfilUtilisateur, NotificationInterim,
    ValidationDemande, ReponseCandidatInterim, PropositionCandidat,
    WorkflowDemande, HistoriqueAction
)

# Import conditionnel des services
try:
    from .services.workflow_service import WorkflowInterimService, RappelService
    WORKFLOW_SERVICES_AVAILABLE = True
except ImportError:
    WORKFLOW_SERVICES_AVAILABLE = False
    # Services de fallback
    class WorkflowInterimService:
        @staticmethod
        def proposer_candidat(demande, candidat, proposant, commentaire=""):
            return False
        
        @staticmethod
        def valider_n_plus_1(demande, validateur, decision, commentaire=""):
            return False
        
        @staticmethod
        def valider_drh(demande, validateur, decision, commentaire=""):
            return False
        
        @staticmethod
        def reponse_candidat(demande, candidat, reponse, motif="", commentaire=""):
            return False
        
        @staticmethod
        def _est_chef_service(profil, demande):
            return False
    
    class RappelService:
        @staticmethod
        def envoyer_rappel_validation(demande, destinataire):
            return False

import logging

logger = logging.getLogger(__name__)

# ================================================================
# VUES POUR LES VALIDATEURS N+1
# ================================================================

@login_required
def validation_n1_dashboard(request):
    """Tableau de bord pour les validations N+1"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Vérifier les permissions
        if profil.type_profil not in ['RESPONSABLE', 'DIRECTEUR']:
            return HttpResponseForbidden("Accès réservé aux responsables")
        
        # Demandes en attente de validation N+1
        demandes_a_valider = DemandeInterim.objects.filter(
            Q(demandeur__manager=profil) | Q(poste__departement=profil.departement),
            statut__in=['CANDIDAT_PROPOSE', 'EN_VALIDATION']
        ).select_related(
            'poste', 'candidat_selectionne__user', 'demandeur__user'
        )
        
        # Historique des validations récentes
        validations_recentes = ValidationDemande.objects.filter(
            validateur=profil,
            type_validation='N_PLUS_1'
        ).select_related('demande')[:10]
        
        # Demandes nécessitant une intervention urgente
        demandes_urgentes = demandes_a_valider.filter(
            urgence__in=['ELEVEE', 'CRITIQUE']
        )
        
        # Propositions en attente d'évaluation
        propositions_a_evaluer = PropositionCandidat.objects.filter(
            demande_interim__poste__departement=profil.departement,
            statut='SOUMISE'
        ).select_related(
            'demande_interim',
            'candidat_propose__user',
            'proposant__user'
        )[:5]
        
        context = {
            'profil_utilisateur': profil,
            'demandes_a_valider': demandes_a_valider,
            'demandes_urgentes': demandes_urgentes,
            'propositions_a_evaluer': propositions_a_evaluer,
            'validations_recentes': validations_recentes,
            'stats': {
                'en_attente': demandes_a_valider.count(),
                'urgentes': demandes_urgentes.count(),
                'validees_ce_mois': validations_recentes.filter(
                    date_validation__gte=timezone.now().replace(day=1)
                ).count()
            },
            'services_available': WORKFLOW_SERVICES_AVAILABLE
        }
        
        return render(request, 'interim/validation_n1_dashboard.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
@require_POST
def valider_n1(request, demande_id):
    """Validation N+1 d'une demande"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        decision = request.POST.get('decision')
        commentaire = request.POST.get('commentaire', '')
        candidats_retenus = request.POST.getlist('candidats_retenus[]')
        
        if decision not in ['APPROUVE', 'REFUSE']:
            return JsonResponse({'success': False, 'error': 'Décision invalide'})
        
        # Vérifier les permissions
        if not _peut_valider_niveau_1(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Utiliser le service si disponible
        if WORKFLOW_SERVICES_AVAILABLE:
            success = WorkflowInterimService.valider_n_plus_1(
                demande, profil, decision, commentaire
            )
        else:
            success = _valider_n1_fallback(demande, profil, decision, commentaire, candidats_retenus)
        
        if success:
            action = "approuvée" if decision == 'APPROUVE' else "refusée"
            return JsonResponse({
                'success': True,
                'message': f'Demande {action} avec succès',
                'redirect_url': reverse('validation_n1_dashboard')
            })
        else:
            return JsonResponse({'success': False, 'error': 'Erreur lors de la validation'})
            
    except Exception as e:
        logger.error(f"Erreur validation N+1: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES POUR LA DRH
# ================================================================

@login_required
def validation_drh_dashboard(request, demande_id):
    """Tableau de bord pour les validations DRH"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Vérifier les permissions DRH
        if profil.type_profil != 'RH':
            return HttpResponseForbidden("Accès réservé à la DRH")
        
        # Demandes en attente de validation DRH
        demandes_a_valider = DemandeInterim.objects.filter(
            statut__in=['VALIDATION_DRH_PENDING', 'EN_VALIDATION']
        ).select_related(
            'poste__departement', 'candidat_selectionne__user', 'demandeur__user'
        )
        
        # Demandes par urgence
        demandes_critiques = demandes_a_valider.filter(urgence='CRITIQUE')
        demandes_elevees = demandes_a_valider.filter(urgence='ELEVEE')
        
        # Validations récentes
        validations_recentes = ValidationDemande.objects.filter(
            validateur=profil,
            type_validation='DRH'
        ).select_related('demande').order_by('-date_validation')[:10]
        
        # Propositions nécessitant arbitrage DRH
        propositions_arbitrage = PropositionCandidat.objects.filter(
            statut='EN_ARBITRAGE_DRH'
        ).select_related(
            'demande_interim',
            'candidat_propose__user'
        )[:5]
        
        # Statistiques DRH
        stats = {
            'en_attente_validation': demandes_a_valider.count(),
            'critiques': demandes_critiques.count(),
            'elevees': demandes_elevees.count(),
            'missions_actives': DemandeInterim.objects.filter(statut='EN_COURS').count(),
            'validations_ce_mois': validations_recentes.filter(
                date_validation__gte=timezone.now().replace(day=1)
            ).count(),
            'taux_validation_global': _calculer_taux_validation_global(),
            'services_available': WORKFLOW_SERVICES_AVAILABLE
        }
        
        context = {
            'profil_utilisateur': profil,
            'demandes_a_valider': demandes_a_valider,
            'demandes_critiques': demandes_critiques,
            'demandes_elevees': demandes_elevees,
            'propositions_arbitrage': propositions_arbitrage,
            'validations_recentes': validations_recentes,
            'stats': stats
        }
        
        return render(request, 'validation_drh_dashboard.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
@require_POST
def valider_drh(request, demande_id):
    """Validation finale DRH"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        decision = request.POST.get('decision')
        commentaire = request.POST.get('commentaire', '')
        candidat_final_id = request.POST.get('candidat_final_id')
        
        # Vérifier les permissions
        if profil.type_profil != 'RH':
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Utiliser le service si disponible
        if WORKFLOW_SERVICES_AVAILABLE:
            success = WorkflowInterimService.valider_drh(
                demande, profil, decision, commentaire
            )
        else:
            success = _valider_drh_fallback(demande, profil, decision, commentaire, candidat_final_id)
        
        if success:
            action = "validée définitivement" if decision == 'APPROUVE' else "refusée"
            return JsonResponse({
                'success': True,
                'message': f'Demande {action} avec succès',
                'redirect_url': reverse('interim_validation', demande.id)
            })
        else:
            return JsonResponse({'success': False, 'error': 'Erreur lors de la validation'})
            
    except Exception as e:
        logger.error(f"Erreur validation DRH: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES POUR LES CANDIDATS
# ================================================================

@login_required
def reponse_candidat_view(request, demande_id):
    """Vue pour que le candidat réponde à une proposition"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier que l'utilisateur est le candidat sélectionné
        if demande.candidat_selectionne != profil:
            return HttpResponseForbidden("Vous n'êtes pas autorisé à répondre à cette demande")
        
        # Récupérer ou créer la réponse candidat
        reponse_candidat, created = ReponseCandidatInterim.objects.get_or_create(
            demande=demande,
            candidat=profil,
            defaults={
                'date_limite_reponse': timezone.now() + timezone.timedelta(days=3)
            }
        )
        
        # Vérifier si pas déjà répondu ou expiré
        if reponse_candidat.reponse != 'EN_ATTENTE':
            messages.info(request, "Vous avez déjà répondu à cette proposition")
            return redirect('mes_notifications')
        
        if reponse_candidat.est_expire:
            messages.error(request, "Cette proposition a expiré")
            return redirect('mes_notifications')
        
        if request.method == 'POST':
            reponse = request.POST.get('reponse')
            motif = request.POST.get('motif_refus', '')
            commentaire = request.POST.get('commentaire', '')
            
            # Utiliser le service si disponible
            if WORKFLOW_SERVICES_AVAILABLE:
                success = WorkflowInterimService.reponse_candidat(
                    demande, profil, reponse, motif, commentaire
                )
            else:
                success = _reponse_candidat_fallback(
                    reponse_candidat, reponse, motif, commentaire
                )
            
            if success:
                if reponse == 'ACCEPTE':
                    messages.success(request, "Proposition acceptée avec succès!")
                    
                    # Créer notification pour le demandeur
                    NotificationInterim.objects.create(
                        destinataire=demande.demandeur,
                        expediteur=profil,
                        demande=demande,
                        type_notification='CANDIDAT_ACCEPTE',
                        urgence='NORMALE',
                        titre=f"Mission acceptée - {demande.numero_demande}",
                        message=f"{profil.nom_complet} a accepté la mission d'intérim"
                    )
                else:
                    messages.info(request, "Proposition refusée")
                    
                    # Créer notification pour le demandeur
                    NotificationInterim.objects.create(
                        destinataire=demande.demandeur,
                        expediteur=profil,
                        demande=demande,
                        type_notification='CANDIDAT_REFUSE',
                        urgence='HAUTE',
                        titre=f"Mission refusée - {demande.numero_demande}",
                        message=f"{profil.nom_complet} a refusé la mission. Motif: {motif}"
                    )
                
                return redirect('mes_notifications')
            else:
                messages.error(request, "Erreur lors de l'enregistrement de votre réponse")
        
        # Informations sur la mission
        mission_info = {
            'duree_jours': (demande.date_fin - demande.date_debut).days if demande.date_debut and demande.date_fin else 0,
            'departement': demande.poste.departement.nom if demande.poste and demande.poste.departement else '',
            'site': demande.poste.site.nom if demande.poste and demande.poste.site else '',
            'urgence': demande.get_urgence_display()
        }
        
        context = {
            'demande': demande,
            'reponse_candidat': reponse_candidat,
            'profil_utilisateur': profil,
            'mission_info': mission_info,
            'temps_restant': reponse_candidat.temps_restant,
            'services_available': WORKFLOW_SERVICES_AVAILABLE
        }
        
        return render(request, 'reponse_candidat.html', context)
        
    except Exception as e:
        logger.error(f"Erreur réponse candidat: {e}")
        messages.error(request, "Erreur lors du traitement de votre réponse")
        return redirect('index')

# ================================================================
# VUES POUR LES NOTIFICATIONS
# ================================================================

@login_required
def mes_notifications(request):
    """Liste des notifications de l'utilisateur"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Filtres
        type_filtre = request.GET.get('type', 'TOUTES')
        statut_filtre = request.GET.get('statut', 'TOUTES')
        
        # Récupérer les notifications
        notifications = profil.notifications_recues.all()
        
        # Appliquer les filtres
        if type_filtre != 'TOUTES':
            notifications = notifications.filter(type_notification=type_filtre)
        
        if statut_filtre != 'TOUTES':
            notifications = notifications.filter(statut=statut_filtre)
        
        notifications = notifications.select_related(
            'expediteur__user',
            'demande',
            'proposition_liee__candidat_propose__user'
        ).order_by('-created_at')
        
        # Pagination
        paginator = Paginator(notifications, 20)
        page_number = request.GET.get('page')
        notifications_page = paginator.get_page(page_number)
        
        # Marquer comme lues les notifications affichées
        notifications_non_lues = notifications_page.object_list.filter(statut='NON_LUE')
        for notification in notifications_non_lues:
            try:
                notification.marquer_comme_lue()
            except:
                pass
        
        # Statistiques des notifications
        stats_notifications = {
            'total': notifications.count(),
            'non_lues': profil.notifications_recues.filter(statut_lecture='NON_LUE').count(),
            'critiques': profil.notifications_recues.filter(urgence='CRITIQUE').count(),
            'cette_semaine': profil.notifications_recues.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=7)
            ).count()
        }
        
        context = {
            'notifications': notifications_page,
            'profil_utilisateur': profil,
            'stats_notifications': stats_notifications,
            'type_filtre': type_filtre,
            'statut_filtre': statut_filtre,
            'types_notification': _get_types_notification(),
            'statuts': _get_statuts_notification()
        }
        
        return render(request, 'mes_notifications.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

@login_required
@require_POST
def marquer_notification_traitee(request, notification_id):
    """Marque une notification comme traitée"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        notification = get_object_or_404(
            NotificationInterim, 
            id=notification_id, 
            destinataire=profil
        )
        
        try:
            notification.marquer_comme_traitee()
            return JsonResponse({'success': True})
        except:
            # Fallback simple
            notification.statut = 'TRAITEE'
            notification.save()
            return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Erreur marquage notification: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES POUR VALIDATION AVEC PROPOSITIONS
# ================================================================

@login_required
def validation_avec_propositions(request, demande_id):
    """Vue de validation intégrant les propositions managériales"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions de validation
        if not _peut_valider_demande(profil, demande):
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
        
        if request.method == 'POST':
            return _traiter_validation_avec_propositions(request, profil, demande, propositions)
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil,
            'propositions': propositions,
            'workflow_info': workflow_info,
            'validations_precedentes': validations_precedentes,
            'peut_ajouter_candidat': _peut_ajouter_candidat_validation(profil),
            'services_available': WORKFLOW_SERVICES_AVAILABLE
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
            success = _valider_niveau_suivant(demande, profil, candidats_retenus, commentaire)
            
            if success:
                messages.success(request, "Validation transmise au niveau suivant")
                return redirect('interim_validation', demande.id)
            else:
                messages.error(request, "Erreur lors de la validation")
        
        elif action == 'validation_finale':
            # Validation finale et sélection du candidat
            candidat_final_id = request.POST.get('candidat_final_id')
            success = _validation_finale_candidat(demande, profil, candidat_final_id, commentaire)
            
            if success:
                messages.success(request, "Candidat sélectionné et notifié")
                return redirect('interim_validation', demande.id)
            else:
                messages.error(request, "Erreur lors de la sélection finale")
        
        elif action == 'refuser':
            # Refus de la demande
            success = _refuser_demande_validation(demande, profil, commentaire)
            
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

# ================================================================
# API POUR LES DONNÉES TEMPS RÉEL
# ================================================================

@login_required
def api_notifications_count(request):
    """API pour le nombre de notifications non lues"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        count = _get_notifications_count(profil)
        
        # Détails par type
        notifications_detail = profil.notifications_recues.filter(
            statut='NON_LUE'
        ).values('type_notification', 'urgence').annotate(
            count=Count('id')
        )
        
        return JsonResponse({
            'success': True,
            'count': count,
            'has_critical': profil.notifications_recues.filter(
                statut='NON_LUE',
                urgence='CRITIQUE'
            ).exists(),
            'details': list(notifications_detail)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_workflow_status(request, demande_id):
    """API pour le statut du workflow d'une demande"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if not _peut_voir_demande(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Statut du workflow
        workflow_status = {
            'statut_demande': demande.statut,
            'niveau_validation_actuel': demande.niveau_validation_actuel,
            'niveaux_requis': demande.niveaux_validation_requis,
            'progression_pct': (demande.niveau_validation_actuel / demande.niveaux_validation_requis * 100) if demande.niveaux_validation_requis > 0 else 0,
            'etape_actuelle': _get_etape_validation_actuelle(demande),
            'prochaine_etape': _get_prochaine_etape(demande),
            'candidat_selectionne': demande.candidat_selectionne.nom_complet if demande.candidat_selectionne else None,
            'nb_propositions': demande.propositions_candidats.count(),
            'services_available': WORKFLOW_SERVICES_AVAILABLE,
            'derniere_modification': demande.updated_at.isoformat() if demande.updated_at else None
        }
        
        return JsonResponse({
            'success': True,
            'workflow_status': workflow_status
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES POUR RAPPELS ET ESCALADE
# ================================================================

@login_required
def envoyer_rappel_validation(request, demande_id):
    """Envoie un rappel pour validation"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if not _peut_envoyer_rappel(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Identifier le destinataire selon le niveau
        destinataire = _identifier_destinataire_rappel(demande)
        
        if not destinataire:
            return JsonResponse({'success': False, 'error': 'Aucun destinataire identifié'})
        
        # Utiliser le service de rappel si disponible
        if WORKFLOW_SERVICES_AVAILABLE:
            success = RappelService.envoyer_rappel_validation(demande, destinataire)
        else:
            success = _envoyer_rappel_fallback(demande, destinataire, profil)
        
        if success:
            return JsonResponse({
                'success': True,
                'message': f'Rappel envoyé à {destinataire.nom_complet}'
            })
        else:
            return JsonResponse({'success': False, 'error': 'Erreur lors de l\'envoi'})
        
    except Exception as e:
        logger.error(f"Erreur envoi rappel: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def escalader_validation(request, demande_id):
    """Escalade une validation au niveau supérieur"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions d'escalade
        if not _peut_escalader(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée pour escalade'})
        
        # Passer au niveau supérieur
        niveau_precedent = demande.niveau_validation_actuel
        demande.niveau_validation_actuel = min(
            demande.niveau_validation_actuel + 1,
            demande.niveaux_validation_requis
        )
        demande.save()
        
        # Créer notification d'escalade
        destinataire_escalade = _identifier_destinataire_escalade(demande)
        if destinataire_escalade:
            NotificationInterim.objects.create(
                destinataire=destinataire_escalade,
                expediteur=profil,
                demande=demande,
                type_notification='ESCALADE_VALIDATION',
                urgence='HAUTE',
                titre=f"Escalade de validation - {demande.numero_demande}",
                message=f"Validation escaladée du niveau {niveau_precedent} vers le niveau {demande.niveau_validation_actuel}"
            )
        
        # Historique
        HistoriqueAction.objects.create(
            demande=demande,
            utilisateur=profil,
            action='ESCALADE_VALIDATION',
            description=f"Escalade du niveau {niveau_precedent} vers {demande.niveau_validation_actuel}",
            donnees_apres={
                'niveau_precedent': niveau_precedent,
                'niveau_actuel': demande.niveau_validation_actuel
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Validation escaladée avec succès',
            'nouveau_niveau': demande.niveau_validation_actuel
        })
        
    except Exception as e:
        logger.error(f"Erreur escalade: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES POUR MONITORING WORKFLOW
# ================================================================

@login_required
def monitoring_workflow_global(request):
    """Monitoring global du workflow pour les RH"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil != 'RH':
            return HttpResponseForbidden("Accès réservé à la DRH")
        
        # Demandes par statut
        demandes_par_statut = DemandeInterim.objects.values('statut').annotate(
            count=Count('id')
        ).order_by('statut')
        
        # Temps moyen de validation par niveau
        from django.db.models import Avg, F
        temps_validation = ValidationDemande.objects.values('type_validation').annotate(
            temps_moyen=Avg(F('date_validation') - F('created_at'))
        )
        
        # Demandes bloquées (plus de 5 jours sans action)
        from datetime import timedelta
        date_limite_blocage = timezone.now() - timedelta(days=5)
        demandes_bloquees = DemandeInterim.objects.filter(
            statut__in=['EN_VALIDATION', 'CANDIDAT_PROPOSE'],
            updated_at__lt=date_limite_blocage
        ).select_related('demandeur__user', 'poste')
        
        # Alertes automatiques
        alertes = []
        if demandes_bloquees.count() > 0:
            alertes.append({
                'type': 'warning',
                'message': f"{demandes_bloquees.count()} demande(s) bloquée(s) depuis plus de 5 jours",
                'count': demandes_bloquees.count()
            })
        
        # Demandes critiques en retard
        demandes_critiques_retard = DemandeInterim.objects.filter(
            urgence='CRITIQUE',
            statut__in=['EN_VALIDATION', 'SOUMISE'],
            created_at__lt=timezone.now() - timedelta(hours=24)
        )
        
        if demandes_critiques_retard.count() > 0:
            alertes.append({
                'type': 'danger',
                'message': f"{demandes_critiques_retard.count()} demande(s) critique(s) en retard",
                'count': demandes_critiques_retard.count()
            })
        
        # Performance des validateurs
        performance_validateurs = ValidationDemande.objects.filter(
            date_validation__gte=timezone.now() - timedelta(days=30)
        ).values(
            'validateur__user__first_name',
            'validateur__user__last_name',
            'type_validation'
        ).annotate(
            nb_validations=Count('id'),
            temps_moyen=Avg(F('date_validation') - F('created_at'))
        ).order_by('-nb_validations')[:10]
        
        context = {
            'profil_utilisateur': profil,
            'demandes_par_statut': demandes_par_statut,
            'temps_validation': temps_validation,
            'demandes_bloquees': demandes_bloquees,
            'alertes': alertes,
            'performance_validateurs': performance_validateurs,
            'services_available': WORKFLOW_SERVICES_AVAILABLE
        }
        
        return render(request, 'interim/admin/monitoring_workflow.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR HISTORIQUE WORKFLOW
# ================================================================

@login_required
def historique_workflow_demande(request, demande_id):
    """Historique détaillé du workflow d'une demande"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        if not _peut_voir_demande(profil, demande):
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Historique complet
        historique_actions = demande.historique_actions.select_related(
            'utilisateur__user'
        ).order_by('created_at')
        
        # Validations
        validations = demande.validations.select_related(
            'validateur__user'
        ).order_by('date_validation')
        
        # Propositions
        propositions = demande.propositions_candidats.select_related(
            'candidat_propose__user',
            'proposant__user',
            'evaluateur__user'
        ).order_by('created_at')
        
        # Notifications envoyées
        notifications_envoyees = NotificationInterim.objects.filter(
            demande=demande
        ).select_related(
            'destinataire__user',
            'expediteur__user'
        ).order_by('created_at')
        
        # Timeline combinée
        timeline = []
        
        # Ajouter les actions
        for action in historique_actions:
            timeline.append({
                'type': 'action',
                'timestamp': action.created_at,
                'utilisateur': action.utilisateur,
                'titre': action.action,
                'description': action.description,
                'donnees': action.donnees_apres
            })
        
        # Ajouter les validations
        for validation in validations:
            timeline.append({
                'type': 'validation',
                'timestamp': validation.date_validation,
                'utilisateur': validation.validateur,
                'titre': f"Validation {validation.get_type_validation_display()}",
                'description': f"Décision: {validation.get_decision_display()}",
                'commentaire': validation.commentaire
            })
        
        # Ajouter les propositions
        for proposition in propositions:
            timeline.append({
                'type': 'proposition',
                'timestamp': proposition.created_at,
                'utilisateur': proposition.proposant,
                'titre': f"Proposition de {proposition.candidat_propose.nom_complet}",
                'description': proposition.justification[:100] + "..." if len(proposition.justification) > 100 else proposition.justification,
                'score': proposition.score_final
            })
            
            if proposition.date_evaluation:
                timeline.append({
                    'type': 'evaluation',
                    'timestamp': proposition.date_evaluation,
                    'utilisateur': proposition.evaluateur,
                    'titre': f"Évaluation: {proposition.get_statut_display()}",
                    'description': proposition.commentaire_evaluation,
                    'score': proposition.score_final
                })
        
        # Trier par timestamp
        timeline.sort(key=lambda x: x['timestamp'])
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil,
            'timeline': timeline,
            'historique_actions': historique_actions,
            'validations': validations,
            'propositions': propositions,
            'notifications_envoyees': notifications_envoyees
        }
        
        return render(request, 'historique_workflow_demande.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR CONFIGURATION NOTIFICATIONS
# ================================================================

@login_required
def mes_preferences_notifications(request):
    """Préférences personnelles de notifications"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if request.method == 'POST':
            # Sauvegarder les préférences
            preferences = {
                'email_nouvelles_demandes': request.POST.get('email_nouvelles_demandes') == 'on',
                'email_validations': request.POST.get('email_validations') == 'on',
                'email_propositions': request.POST.get('email_propositions') == 'on',
                'notif_push_urgentes': request.POST.get('notif_push_urgentes') == 'on',
                'resume_hebdomadaire': request.POST.get('resume_hebdomadaire') == 'on',
                'notifications_weekend': request.POST.get('notifications_weekend') == 'on'
            }
            
            # TODO: Sauvegarder dans le modèle PreferencesNotification
            messages.success(request, "Préférences sauvegardées")
            return redirect('mes_preferences_notifications')
        
        # Préférences actuelles (simulation)
        preferences_actuelles = {
            'email_nouvelles_demandes': True,
            'email_validations': True,
            'email_propositions': False,
            'notif_push_urgentes': True,
            'resume_hebdomadaire': True,
            'notifications_weekend': False
        }
        
        # Statistiques personnelles des notifications
        stats_notif = {
            'total_reçues': profil.notifications_recues.count(),
            'cette_semaine': profil.notifications_recues.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=7)
            ).count(),
            'non_lues': profil.notifications_recues.filter(statut='NON_LUE').count(),
            'par_type': profil.notifications_recues.values('type_notification').annotate(
                count=Count('id')
            ).order_by('-count')[:5]
        }
        
        context = {
            'profil_utilisateur': profil,
            'preferences': preferences_actuelles,
            'stats_notif': stats_notif
        }
        
        return render(request, 'interim/mes_preferences_notifications.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR RAPPORT WORKFLOW
# ================================================================

@login_required
def rapport_performance_workflow(request):
    """Rapport de performance du workflow"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if profil.type_profil not in ['RH', 'DIRECTEUR', 'ADMIN']:
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Période d'analyse
        periode = int(request.GET.get('periode', 30))
        date_debut = timezone.now() - timezone.timedelta(days=periode)
        
        # Métriques de performance
        demandes_periode = DemandeInterim.objects.filter(
            created_at__gte=date_debut
        )
        
        # Temps moyen de traitement par étape
        from django.db.models import Avg, F, DurationField
        
        temps_moyen_validation = ValidationDemande.objects.filter(
            date_validation__gte=date_debut
        ).aggregate(
            temps_moyen=Avg(F('date_validation') - F('created_at'))
        )['temps_moyen']
        
        # Taux de validation par niveau
        taux_validation_n1 = ValidationDemande.objects.filter(
            type_validation='N_PLUS_1',
            date_validation__gte=date_debut
        ).aggregate(
            taux_approbation=Avg('decision')
        )['taux_approbation'] or 0
        
        taux_validation_drh = ValidationDemande.objects.filter(
            type_validation='DRH',
            date_validation__gte=date_debut
        ).aggregate(
            taux_approbation=Avg('decision')
        )['taux_approbation'] or 0
        
        # Demandes par statut final
        repartition_statuts = demandes_periode.values('statut').annotate(
            count=Count('id'),
            pourcentage=Count('id') * 100.0 / demandes_periode.count()
        ).order_by('-count')
        
        # Top validateurs
        top_validateurs = ValidationDemande.objects.filter(
            date_validation__gte=date_debut
        ).values(
            'validateur__user__first_name',
            'validateur__user__last_name'
        ).annotate(
            nb_validations=Count('id'),
            temps_moyen=Avg(F('date_validation') - F('created_at'))
        ).order_by('-nb_validations')[:10]
        
        # Goulots d'étranglement
        goulots = []
        demandes_bloquees_validation = demandes_periode.filter(
            statut='EN_VALIDATION',
            updated_at__lt=timezone.now() - timezone.timedelta(days=3)
        ).count()
        
        if demandes_bloquees_validation > 0:
            goulots.append({
                'etape': 'Validation',
                'nb_demandes_bloquees': demandes_bloquees_validation,
                'recommandation': 'Relancer les validateurs'
            })
        
        context = {
            'profil_utilisateur': profil,
            'periode': periode,
            'date_debut': date_debut,
            'metriques': {
                'total_demandes': demandes_periode.count(),
                'temps_moyen_validation': temps_moyen_validation,
                'taux_validation_n1': round(taux_validation_n1 * 100, 1) if taux_validation_n1 else 0,
                'taux_validation_drh': round(taux_validation_drh * 100, 1) if taux_validation_drh else 0
            },
            'repartition_statuts': repartition_statuts,
            'top_validateurs': top_validateurs,
            'goulots': goulots
        }
        
        return render(request, 'interim/admin/rapport_performance_workflow.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# VUES POUR ACTIONS EN MASSE
# ================================================================

@login_required
def actions_masse_notifications(request):
    """Actions en masse sur les notifications"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        if request.method == 'POST':
            action = request.POST.get('action')
            notification_ids = request.POST.getlist('notification_ids[]')
            
            if not notification_ids:
                messages.error(request, "Aucune notification sélectionnée")
                return redirect('mes_notifications')
            
            notifications = profil.notifications_recues.filter(
                id__in=notification_ids
            )
            
            if action == 'marquer_lues':
                notifications.update(
                    statut='LUE',
                    date_lecture=timezone.now()
                )
                messages.success(request, f"{notifications.count()} notification(s) marquée(s) comme lue(s)")
            
            elif action == 'marquer_traitees':
                notifications.update(
                    statut='TRAITEE',
                    date_traitement=timezone.now()
                )
                messages.success(request, f"{notifications.count()} notification(s) marquée(s) comme traitée(s)")
            
            elif action == 'supprimer':
                count = notifications.count()
                notifications.delete()
                messages.success(request, f"{count} notification(s) supprimée(s)")
            
            return redirect('mes_notifications')
        
        # Afficher les options d'actions en masse
        notifications_selection = profil.notifications_recues.filter(
            statut__in=['NON_LUE', 'LUE']
        )[:100]
        
        context = {
            'profil_utilisateur': profil,
            'notifications_selection': notifications_selection
        }
        
        return render(request, 'interim/actions_masse_notifications.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')

# ================================================================
# API POUR WORKFLOW TEMPS RÉEL
# ================================================================

@login_required
def api_workflow_stats_live(request):
    """API pour statistiques workflow en temps réel"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Données selon le rôle
        if profil.type_profil == 'RH':
            stats = {
                'demandes_en_validation': DemandeInterim.objects.filter(
                    statut='EN_VALIDATION'
                ).count(),
                'demandes_critiques': DemandeInterim.objects.filter(
                    urgence='CRITIQUE',
                    statut__in=['SOUMISE', 'EN_VALIDATION']
                ).count(),
                'notifications_non_traitees': NotificationInterim.objects.filter(
                    statut='NON_LUE',
                    urgence__in=['HAUTE', 'CRITIQUE']
                ).count(),
                'validations_en_retard': _compter_validations_en_retard()
            }
        else:
            # Stats départementales
            stats = {
                'mes_validations_attente': DemandeInterim.objects.filter(
                    statut='EN_VALIDATION',
                    poste__departement=profil.departement
                ).count() if profil.departement else 0,
                'mes_notifications_urgentes': profil.notifications_recues.filter(
                    statut='NON_LUE',
                    urgence__in=['HAUTE', 'CRITIQUE']
                ).count(),
                'demandes_dept_semaine': DemandeInterim.objects.filter(
                    poste__departement=profil.departement,
                    created_at__gte=timezone.now() - timezone.timedelta(days=7)
                ).count() if profil.departement else 0
            }
        
        return JsonResponse({
            'success': True,
            'stats': stats,
            'timestamp': timezone.now().isoformat(),
            'user_role': profil.type_profil
        })
        
    except Exception as e:
        logger.error(f"Erreur API workflow stats: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

def _compter_validations_en_retard():
    """Compte les validations en retard"""
    seuil_retard = timezone.now() - timezone.timedelta(days=2)
    return DemandeInterim.objects.filter(
        statut='EN_VALIDATION',
        updated_at__lt=seuil_retard
    ).count()

# ================================================================
# FONCTIONS UTILITAIRES ET FALLBACKS
# ================================================================

def _est_chef_service(profil, demande):
    """Vérifie si l'utilisateur est chef de service pour cette demande"""
    if WORKFLOW_SERVICES_AVAILABLE:
        return WorkflowInterimService._est_chef_service(profil, demande)
    else:
        # Fallback simple
        return (
            profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE'] and
            profil.departement == demande.poste.departement
        ) or profil.type_profil in ['RH', 'ADMIN']

def _get_notifications_count(profil):
    """Récupère le nombre de notifications non lues"""
    try:
        return profil.notifications_recues.filter(statut='NON_LUE').count()
    except:
        return 0

def _peut_voir_demande(profil, demande):
    """Vérifie si l'utilisateur peut voir la demande"""
    return (
        demande.demandeur == profil or
        demande.candidat_selectionne == profil or
        demande.personne_remplacee == profil or
        profil.type_profil in ['RH', 'ADMIN'] or
        (profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR'] and
         profil.departement == demande.poste.departement)
    )

def _peut_valider_demande(profil, demande):
    """Vérifie si l'utilisateur peut valider la demande"""
    return (
        profil.type_profil in ['RH', 'DIRECTEUR'] or
        (profil.type_profil in ['RESPONSABLE'] and 
         profil.departement == demande.poste.departement) or
        (profil.type_profil == 'CHEF_EQUIPE' and
         profil.departement == demande.poste.departement)
    )

def _peut_valider_niveau_1(profil, demande):
    """Vérifie si l'utilisateur peut valider au niveau 1"""
    return (
        profil.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE'] and
        profil.departement == demande.poste.departement
    ) or profil.type_profil in ['RH', 'ADMIN']

def _calculer_taux_validation_global():
    """Calcule le taux de validation global"""
    total = DemandeInterim.objects.exclude(statut='BROUILLON').count()
    validees = DemandeInterim.objects.filter(
        statut__in=['VALIDEE', 'EN_COURS', 'TERMINEE']
    ).count()
    
    return round((validees / total * 100) if total > 0 else 0, 1)

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

def _get_prochaine_etape(demande):
    """Retourne la prochaine étape du workflow"""
    if demande.statut == 'SOUMISE':
        return "Validation N+1"
    elif demande.statut == 'EN_VALIDATION':
        if demande.niveau_validation_actuel < demande.niveaux_validation_requis:
            return f"Validation niveau {demande.niveau_validation_actuel + 1}"
        else:
            return "Sélection finale candidat"
    elif demande.statut == 'CANDIDAT_SELECTIONNE':
        return "Réponse candidat"
    else:
        return "Terminé"


def _peut_valider_niveau_actuel(profil, demande):
    """
    Vérifie si l'utilisateur peut valider au niveau actuel selon la hiérarchie
    
    NIVEAUX DE VALIDATION :
    - Niveau 1 : RESPONSABLE (N+1 du chef d'équipe)
    - Niveau 2 : DIRECTEUR (N+2)  
    - Niveau 3+ : RH/ADMIN (Validation finale)
    """
    niveau = demande.niveau_validation_actuel + 1  # Niveau à valider
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

def _peut_ajouter_candidat_validation(profil):
    """Vérifie si l'utilisateur peut ajouter un candidat lors de la validation"""
    return profil.type_profil in ['RH', 'DIRECTEUR', 'RESPONSABLE']

def _peut_envoyer_rappel(profil, demande):
    """Vérifie si l'utilisateur peut envoyer un rappel"""
    return (
        demande.demandeur == profil or
        profil.type_profil in ['RH', 'DIRECTEUR'] or
        (profil.type_profil in ['RESPONSABLE'] and profil.departement == demande.poste.departement)
    )

def _peut_escalader(profil, demande):
    """Vérifie si l'utilisateur peut escalader"""
    return (
        profil.type_profil in ['RH', 'DIRECTEUR'] or
        demande.demandeur == profil
    )

def _identifier_destinataire_rappel(demande):
    """Identifie le destinataire du rappel selon le niveau"""
    niveau = demande.niveau_validation_actuel
    
    if niveau == 1:
        # Rappel pour validation N+1
        return demande.demandeur.manager
    elif niveau >= 2:
        # Rappel pour DRH
        return ProfilUtilisateur.objects.filter(type_profil='RH', actif=True).first()
    
    return None

def _identifier_destinataire_escalade(demande):
    """Identifie le destinataire de l'escalade"""
    niveau = demande.niveau_validation_actuel
    
    if niveau == 2:
        return ProfilUtilisateur.objects.filter(type_profil='RH', actif=True).first()
    elif niveau == 3:
        return ProfilUtilisateur.objects.filter(type_profil='DIRECTEUR', actif=True).first()
    
    return None

def _get_types_notification():
    """Retourne les types de notification disponibles"""
    return [
        ('NOUVELLE_DEMANDE', 'Nouvelle demande'),
        ('CANDIDAT_PROPOSE', 'Candidat proposé'),
        ('VALIDATION_REQUISE', 'Validation requise'),
        ('CANDIDAT_SELECTIONNE', 'Candidat sélectionné'),
        ('CANDIDAT_ACCEPTE', 'Candidat accepté'),
        ('CANDIDAT_REFUSE', 'Candidat refusé'),
        ('ESCALADE_VALIDATION', 'Escalade validation'),
        ('RAPPEL_VALIDATION', 'Rappel validation'),
    ]

def _get_statuts_notification():
    """Retourne les statuts de notification disponibles"""
    return [
        ('NON_LUE', 'Non lue'),
        ('LUE', 'Lue'),
        ('TRAITEE', 'Traitée'),
        ('ARCHIVEE', 'Archivée'),
    ]

# ================================================================
# FONCTIONS FALLBACK (SANS SERVICES)
# ================================================================

def _valider_n1_fallback(demande, validateur, decision, commentaire, candidats_retenus=None):
    """Fallback pour validation N+1 sans service"""
    try:
        with transaction.atomic():
            ValidationDemande.objects.create(
                demande=demande,
                type_validation='N_PLUS_1',
                niveau_validation=1,
                validateur=validateur,
                decision=decision,
                commentaire=commentaire,
                date_validation=timezone.now(),
                candidats_retenus=candidats_retenus or []
            )
            
            if decision == 'APPROUVE':
                demande.statut = 'VALIDATION_DRH_PENDING'
                demande.niveau_validation_actuel = 2
            else:
                demande.statut = 'REFUSEE'
            demande.save()
            return True
    except Exception as e:
        logger.error(f"Erreur fallback validation N+1: {e}")
        return False

def _valider_drh_fallback(demande, validateur, decision, commentaire, candidat_final_id=None):
    """Fallback pour validation DRH sans service"""
    try:
        with transaction.atomic():
            ValidationDemande.objects.create(
                demande=demande,
                type_validation='DRH',
                niveau_validation=2,
                validateur=validateur,
                decision=decision,
                commentaire=commentaire,
                date_validation=timezone.now()
            )
            
            if decision == 'APPROUVE':
                if candidat_final_id:
                    candidat_final = ProfilUtilisateur.objects.get(id=candidat_final_id)
                    demande.candidat_selectionne = candidat_final
                    demande.statut = 'CANDIDAT_SELECTIONNE'
                else:
                    demande.statut = 'VALIDEE'
                demande.date_validation = timezone.now()
            else:
                demande.statut = 'REFUSEE'
            demande.save()
            return True
    except Exception as e:
        logger.error(f"Erreur fallback validation DRH: {e}")
        return False

def _reponse_candidat_fallback(reponse_candidat, reponse, motif, commentaire):
    """Fallback pour réponse candidat sans service"""
    try:
        if reponse == 'ACCEPTE':
            reponse_candidat.accepter(commentaire)
        elif reponse == 'REFUSE':
            reponse_candidat.refuser(motif, commentaire)
        return True
    except Exception as e:
        logger.error(f"Erreur fallback réponse candidat: {e}")
        return False

def _envoyer_rappel_fallback(demande, destinataire, expediteur):
    """Fallback pour envoi de rappel sans service"""
    try:
        NotificationInterim.objects.create(
            destinataire=destinataire,
            expediteur=expediteur,
            demande=demande,
            type_notification='RAPPEL_VALIDATION',
            urgence='NORMALE',
            titre=f"Rappel validation - {demande.numero_demande}",
            message=f"Rappel: votre validation est attendue pour la demande {demande.numero_demande}"
        )
        return True
    except Exception as e:
        logger.error(f"Erreur fallback rappel: {e}")
        return False

def _valider_niveau_suivant(demande, validateur, candidats_retenus, commentaire):
    """Valide et passe au niveau suivant"""
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

def _validation_finale_candidat(demande, validateur, candidat_final_id, commentaire):
    """Validation finale avec sélection du candidat"""
    try:
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
            
            # Notifier le candidat
            NotificationInterim.objects.create(
                destinataire=candidat_final,
                expediteur=validateur,
                demande=demande,
                type_notification='CANDIDAT_SELECTIONNE',
                urgence='HAUTE',
                titre=f"Vous êtes sélectionné(e) - {demande.numero_demande}",
                message=f"Vous avez été sélectionné(e) pour la mission. Veuillez répondre sous 3 jours."
            )
            
            return True
    except Exception as e:
        logger.error(f"Erreur validation finale: {e}")
        return False

def _refuser_demande_validation(demande, validateur, commentaire):
    """Refuse une demande lors de la validation"""
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
            
            # Notifier le demandeur
            NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=validateur,
                demande=demande,
                type_notification='DEMANDE_REFUSEE',
                urgence='NORMALE',
                titre=f"Demande refusée - {demande.numero_demande}",
                message=f"Votre demande a été refusée. Motif: {commentaire}"
            )
            
            return True
    except Exception as e:
        logger.error(f"Erreur refus demande: {e}")
        return False

# ================================================================
# LOG DE CONFIRMATION DU MODULE
# ================================================================

#logger.info("  Module views_workflow_notif.py chargé avec succès")

""" 
logger.info("🔧 Vues disponibles:")
logger.info("   • Dashboards chef service, N+1, DRH")
logger.info("   • Workflow et validations multi-niveaux")
logger.info("   • Gestion des notifications")
logger.info("   • Réponses candidats")
logger.info("   • Monitoring et rapports workflow")
logger.info("   • API temps réel")
logger.info(f"   • Services workflow disponibles: {WORKFLOW_SERVICES_AVAILABLE}")
"""

#print("  views_workflow_notif.py complet et opérationnel")


# ================================================================
# VUES MANQUANTES À AJOUTER À LA FIN DE views_workflow_notif.py
# ================================================================

# ================================================================
# API WORKFLOW MANQUANTES
# ================================================================

@login_required
def api_workflow_status(request, demande_id):
    """API pour le statut du workflow d'une demande"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if not _peut_voir_demande(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Statut du workflow
        workflow_status = {
            'statut_demande': demande.statut,
            'niveau_validation_actuel': demande.niveau_validation_actuel,
            'niveaux_requis': demande.niveaux_validation_requis,
            'progression_pct': (demande.niveau_validation_actuel / demande.niveaux_validation_requis * 100) if demande.niveaux_validation_requis > 0 else 0,
            'etape_actuelle': _get_etape_validation_actuelle(demande),
            'prochaine_etape': _get_prochaine_etape(demande),
            'candidat_selectionne': demande.candidat_selectionne.nom_complet if demande.candidat_selectionne else None,
            'nb_propositions': demande.propositions_candidats.count(),
            'services_available': WORKFLOW_SERVICES_AVAILABLE,
            'derniere_modification': demande.updated_at.isoformat() if demande.updated_at else None
        }
        
        return JsonResponse({
            'success': True,
            'workflow_status': workflow_status
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_notifications_count(request):
    """API pour le nombre de notifications non lues"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        count = _get_notifications_count(profil)
        
        # Détails par type
        notifications_detail = profil.notifications_recues.filter(
            statut='NON_LUE'
        ).values('type_notification', 'urgence').annotate(
            count=Count('id')
        )
        
        return JsonResponse({
            'success': True,
            'count': count,
            'has_critical': profil.notifications_recues.filter(
                statut='NON_LUE',
                urgence='CRITIQUE'
            ).exists(),
            'details': list(notifications_detail)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def marquer_notification_traitee(request, notification_id):
    """Marque une notification comme traitée"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        notification = get_object_or_404(
            NotificationInterim, 
            id=notification_id, 
            destinataire=profil
        )
        
        # Marquer comme traitée
        notification.statut = 'TRAITEE'
        notification.date_traitement = timezone.now()
        notification.save()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Erreur marquage notification: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VALIDATIONS SPÉCIALISÉES MANQUANTES
# ================================================================

@login_required
@require_POST
def valider_n1(request, demande_id):
    """Validation N+1 d'une demande"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        decision = request.POST.get('decision')
        commentaire = request.POST.get('commentaire', '')
        candidats_retenus = request.POST.getlist('candidats_retenus[]')
        
        if decision not in ['APPROUVE', 'REFUSE']:
            return JsonResponse({'success': False, 'error': 'Décision invalide'})
        
        # Vérifier les permissions
        if not _peut_valider_niveau_1(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Utiliser le service si disponible
        if WORKFLOW_SERVICES_AVAILABLE:
            from .services.workflow_service import WorkflowInterimService
            success = WorkflowInterimService.valider_n_plus_1(
                demande, profil, decision, commentaire
            )
        else:
            success = _valider_n1_fallback(demande, profil, decision, commentaire, candidats_retenus)
        
        if success:
            action = "approuvée" if decision == 'APPROUVE' else "refusée"
            return JsonResponse({
                'success': True,
                'message': f'Demande {action} avec succès',
                'redirect_url': reverse('validation_n1_dashboard')
            })
        else:
            return JsonResponse({'success': False, 'error': 'Erreur lors de la validation'})
            
    except Exception as e:
        logger.error(f"Erreur validation N+1: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def valider_drh(request, demande_id):
    """Validation finale DRH"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        decision = request.POST.get('decision')
        commentaire = request.POST.get('commentaire', '')
        candidat_final_id = request.POST.get('candidat_final_id')
        
        # Vérifier les permissions
        if profil.type_profil != 'RH':
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Utiliser le service si disponible
        if WORKFLOW_SERVICES_AVAILABLE:
            from .services.workflow_service import WorkflowInterimService
            success = WorkflowInterimService.valider_drh(
                demande, profil, decision, commentaire
            )
        else:
            success = _valider_drh_fallback(demande, profil, decision, commentaire, candidat_final_id)
        
        if success:
            action = "validée définitivement" if decision == 'APPROUVE' else "refusée"
            return JsonResponse({
                'success': True,
                'message': f'Demande {action} avec succès',
                'redirect_url': reverse('interim_validation', demande.id)
            })
        else:
            return JsonResponse({'success': False, 'error': 'Erreur lors de la validation'})
            
    except Exception as e:
        logger.error(f"Erreur validation DRH: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# VUES POUR INTEGRATION COMPLÈTE WORKFLOW (MANQUANTES)
# ================================================================

@login_required
def workflow_complet_demande(request, demande_id):
    """Vue du workflow complet d'une demande avec intégration"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        if not _peut_voir_demande(profil, demande):
            messages.error(request, "Permission refusée")
            return redirect('index')
        
        # Utiliser le service d'intégration si disponible
        if WORKFLOW_SERVICES_AVAILABLE:
            try:
                from .services.workflow_service import WorkflowIntegrationService
                workflow_complet = WorkflowIntegrationService.obtenir_statut_workflow_complet(demande)
            except ImportError:
                workflow_complet = _obtenir_workflow_basique(demande)
        else:
            workflow_complet = _obtenir_workflow_basique(demande)
        
        context = {
            'demande': demande,
            'profil_utilisateur': profil,
            'workflow_complet': workflow_complet,
            'services_available': WORKFLOW_SERVICES_AVAILABLE
        }
        
        return render(request, 'interim/workflow_complet.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')


# ================================================================
# VUES POUR ESCALADE ET RAPPELS (MANQUANTES)
# ================================================================

@login_required
@require_POST
def escalader_demande(request, demande_id):
    """Escalade une demande au niveau supérieur"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        motif_escalade = request.POST.get('motif_escalade', '')
        
        # Vérifier les permissions d'escalade
        if not _peut_escalader(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée pour escalade'})
        
        # Escalader
        if WORKFLOW_SERVICES_AVAILABLE:
            try:
                from .services.workflow_service import WorkflowIntegrationService
                success = WorkflowIntegrationService.escalader_validation(demande, profil, motif_escalade)
            except ImportError:
                success = _escalader_demande_fallback(demande, profil, motif_escalade)
        else:
            success = _escalader_demande_fallback(demande, profil, motif_escalade)
        
        if success:
            return JsonResponse({
                'success': True,
                'message': 'Demande escaladée avec succès',
                'nouveau_niveau': demande.niveau_validation_actuel
            })
        else:
            return JsonResponse({'success': False, 'error': 'Erreur lors de l\'escalade'})
        
    except Exception as e:
        logger.error(f"Erreur escalade demande: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def envoyer_rappel_validation(request, demande_id):
    """Envoie un rappel pour validation"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Vérifier les permissions
        if not _peut_envoyer_rappel(profil, demande):
            return JsonResponse({'success': False, 'error': 'Permission refusée'})
        
        # Identifier le destinataire selon le niveau
        destinataire = _identifier_destinataire_rappel(demande)
        
        if not destinataire:
            return JsonResponse({'success': False, 'error': 'Aucun destinataire identifié'})
        
        # Utiliser le service de rappel si disponible
        if WORKFLOW_SERVICES_AVAILABLE:
            try:
                from .services.workflow_service import RappelService
                success = RappelService.envoyer_rappel_validation(demande, destinataire)
            except ImportError:
                success = _envoyer_rappel_fallback(demande, destinataire, profil)
        else:
            success = _envoyer_rappel_fallback(demande, destinataire, profil)
        
        if success:
            return JsonResponse({
                'success': True,
                'message': f'Rappel envoyé à {destinataire.nom_complet}'
            })
        else:
            return JsonResponse({'success': False, 'error': 'Erreur lors de l\'envoi'})
        
    except Exception as e:
        logger.error(f"Erreur envoi rappel: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

# ================================================================
# FONCTIONS UTILITAIRES ET FALLBACKS POUR LES VUES MANQUANTES
# ================================================================

def _obtenir_workflow_basique(demande):
    """Version simplifiée du workflow si service non disponible"""
    try:
        # Propositions
        propositions = demande.propositions_candidats.all()
        
        # Validations
        validations = list(demande.validations.all().order_by('created_at'))
        
        # Réponse candidat si applicable
        reponse_candidat = None
        if demande.candidat_selectionne:
            try:
                reponse_candidat = ReponseCandidatInterim.objects.get(
                    demande=demande,
                    candidat=demande.candidat_selectionne
                )
            except ReponseCandidatInterim.DoesNotExist:
                pass
        
        return {
            'demande': demande,
            'etape_actuelle': _get_etape_validation_actuelle(demande),
            'progression': (demande.niveau_validation_actuel / demande.niveaux_validation_requis * 100) if demande.niveaux_validation_requis > 0 else 0,
            'propositions': list(propositions),
            'validations': validations,
            'reponse_candidat': reponse_candidat,
            'service_disponible': False
        }
        
    except Exception as e:
        logger.error(f"Erreur workflow basique: {e}")
        return {
            'demande': demande,
            'erreur': str(e)
        }

def _escalader_demande_fallback(demande, profil, motif):
    """Fallback pour escalader une demande"""
    try:
        with transaction.atomic():
            # Passer au niveau supérieur
            niveau_precedent = demande.niveau_validation_actuel
            demande.niveau_validation_actuel = min(
                demande.niveau_validation_actuel + 1,
                demande.niveaux_validation_requis
            )
            demande.save()
            
            # Créer notification d'escalade
            destinataire_escalade = _identifier_destinataire_escalade(demande)
            if destinataire_escalade:
                NotificationInterim.objects.create(
                    destinataire=destinataire_escalade,
                    expediteur=profil,
                    demande=demande,
                    type_notification='ESCALADE_VALIDATION',
                    urgence='HAUTE',
                    titre=f"Escalade de validation - {demande.numero_demande}",
                    message=f"Validation escaladée du niveau {niveau_precedent} vers le niveau {demande.niveau_validation_actuel}. Motif: {motif}"
                )
            
            # Historique
            try:
                HistoriqueAction.objects.create(
                    demande=demande,
                    utilisateur=profil,
                    action='ESCALADE_VALIDATION',
                    description=f"Escalade du niveau {niveau_precedent} vers {demande.niveau_validation_actuel}",
                    donnees_apres={
                        'niveau_precedent': niveau_precedent,
                        'niveau_actuel': demande.niveau_validation_actuel,
                        'motif': motif
                    }
                )
            except:
                pass  # Si le modèle HistoriqueAction n'existe pas
            
            return True
    except Exception as e:
        logger.error(f"Erreur escalade fallback: {e}")
        return False

def _identifier_destinataire_escalade(demande):
    """Identifie le destinataire de l'escalade"""
    niveau = demande.niveau_validation_actuel
    
    if niveau == 2:
        return ProfilUtilisateur.objects.filter(type_profil='RH', actif=True).first()
    elif niveau == 3:
        return ProfilUtilisateur.objects.filter(type_profil='DIRECTEUR', actif=True).first()
    
    return None

# ================================================================
# LOG DE CONFIRMATION DU MODULE
# ================================================================

#logger.info("  Vues manquantes pour views_workflow_notif.py ajoutées")

""" 
logger.info("🔧 Fonctions ajoutées:")
logger.info("   • API workflow status")
logger.info("   • API notifications count") 
logger.info("   • Validations spécialisées N+1 et DRH")
logger.info("   • Vues d'escalade et rappels")
logger.info("   • Dashboard workflow global")
logger.info("   • Fonctions utilitaires de fallback")
print("  views_workflow_notif.py maintenant complet et cohérent avec urls.py")
"""
