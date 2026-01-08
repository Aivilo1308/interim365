# Vue Ajax pour ajouter une proposition à une demande d'intérim
# À ajouter dans views.py ou views_manager_proposals.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, JsonResponse, HttpResponse, Http404
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from django.contrib import messages
from django.db.models import Q, Count, Avg, Max, Min, Sum, F, Case, When, IntegerField, Prefetch
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import datetime, timedelta

from io import BytesIO

import xlsxwriter
import calendar
import logging
import json
import logging

from mainapp.models import *

logger = logging.getLogger(__name__)

@login_required
@require_POST
def demande_interim_ajouter_proposition(request, demande_id):
    """
    Vue Ajax pour ajouter une nouvelle proposition (humaine ou automatique) 
    à une demande d'intérim existante.
    
    Paramètres:
    - demande_id : ID de la demande d'intérim
    - POST data : Formulaire avec les données de la proposition
    
    Retour JSON:
    - success : true/false
    - message : Message de succès/erreur
    - data : Données de la proposition créée (si succès)
    """
    
    try:
        # Récupération de la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        profil_utilisateur = get_object_or_404(ProfilUtilisateur, user=request.user)
        
        # Vérification des permissions
        peut_proposer, raison_permission = demande.peut_proposer_candidat(profil_utilisateur)
        if not peut_proposer:
            return JsonResponse({
                'success': False,
                'message': f'Permission refusée : {raison_permission}',
                'error_type': 'PERMISSION_DENIED'
            }, status=403)
        
        # Récupération et validation des données POST
        try:
            # Support pour JSON et form-data
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST
                
            candidat_matricule = data.get('candidat_matricule', '').strip()
            justification = data.get('justification', '').strip()
            competences_specifiques = data.get('competences_specifiques', '').strip()
            experience_pertinente = data.get('experience_pertinente', '').strip()
            type_proposition = data.get('type_proposition', 'HUMAINE')  # HUMAINE ou AUTOMATIQUE
            score_humain_ajuste = data.get('score_humain_ajuste')
            
        except (json.JSONDecodeError, KeyError) as e:
            return JsonResponse({
                'success': False,
                'message': 'Données de formulaire invalides',
                'error_type': 'INVALID_DATA',
                'details': str(e)
            }, status=400)
        
        # Validation des champs obligatoires
        if not candidat_matricule:
            return JsonResponse({
                'success': False,
                'message': 'Le matricule du candidat est obligatoire',
                'error_type': 'MISSING_CANDIDAT'
            }, status=400)
            
        if not justification:
            return JsonResponse({
                'success': False,
                'message': 'La justification de la proposition est obligatoire',
                'error_type': 'MISSING_JUSTIFICATION'
            }, status=400)
        
        # Recherche du candidat proposé
        try:
            candidat_propose = ProfilUtilisateur.objects.get(
                matricule=candidat_matricule,
                actif=True
            )
        except ProfilUtilisateur.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': f'Aucun employé actif trouvé avec le matricule : {candidat_matricule}',
                'error_type': 'CANDIDAT_NOT_FOUND'
            }, status=404)
        
        # Vérification que le candidat n'est pas déjà proposé par le même utilisateur
        proposition_existante = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=candidat_propose,
            proposant=profil_utilisateur
        ).first()
        
        if proposition_existante:
            return JsonResponse({
                'success': False,
                'message': f'Vous avez déjà proposé {candidat_propose.nom_complet} pour cette demande',
                'error_type': 'CANDIDAT_ALREADY_PROPOSED',
                'proposition_existante_id': proposition_existante.id
            }, status=409)
        
        # Vérification que le candidat peut effectuer cette mission
        if candidat_propose.statut_employe != 'ACTIF':
            return JsonResponse({
                'success': False,
                'message': f'Le candidat {candidat_propose.nom_complet} n\'est pas en statut actif ({candidat_propose.get_statut_employe_display()})',
                'error_type': 'CANDIDAT_NOT_ACTIVE'
            }, status=400)
        
        # Détermination de la source de proposition selon la hiérarchie
        source_proposition = _determiner_source_proposition(profil_utilisateur)
        
        # Calcul du bonus hiérarchique
        bonus_hierarchique = _calculer_bonus_hierarchique(profil_utilisateur)
        
        # Validation du score humain ajusté si fourni
        score_humain_valide = None
        if score_humain_ajuste:
            try:
                score_humain_valide = int(score_humain_ajuste)
                if not (0 <= score_humain_valide <= 100):
                    return JsonResponse({
                        'success': False,
                        'message': 'Le score ajusté doit être entre 0 et 100',
                        'error_type': 'INVALID_SCORE'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Score ajusté invalide',
                    'error_type': 'INVALID_SCORE_FORMAT'
                }, status=400)
        
        # Calcul du score automatique si pas de score humain fourni
        score_automatique = None
        if not score_humain_valide and type_proposition == 'AUTOMATIQUE':
            try:
                score_automatique = _calculer_score_automatique(candidat_propose, demande)
            except Exception as e:
                logger.error(f"Erreur calcul score automatique: {e}")
                score_automatique = 50  # Score par défaut
        
        # Création de la proposition dans une transaction
        try:
            with transaction.atomic():
                # Création de la proposition
                proposition = PropositionCandidat.objects.create(
                    demande_interim=demande,
                    candidat_propose=candidat_propose,
                    proposant=profil_utilisateur,
                    source_proposition=source_proposition,
                    justification=justification,
                    competences_specifiques=competences_specifiques,
                    experience_pertinente=experience_pertinente,
                    score_automatique=score_automatique,
                    score_humain_ajuste=score_humain_valide,
                    bonus_proposition_humaine=bonus_hierarchique,
                    statut='SOUMISE'
                )
                
                # Le score_final est calculé automatiquement dans le save() du modèle
                
                # Création de l'historique
                HistoriqueAction.objects.create(
                    demande=demande,
                    proposition=proposition,
                    action='PROPOSITION_CANDIDAT',
                    utilisateur=profil_utilisateur,
                    description=f"Nouvelle proposition de {candidat_propose.nom_complet} par {profil_utilisateur.nom_complet} ({source_proposition})",
                    niveau_hierarchique=profil_utilisateur.type_profil,
                    is_superuser=profil_utilisateur.is_superuser,
                    donnees_apres={
                        'candidat_id': candidat_propose.id,
                        'candidat_nom': candidat_propose.nom_complet,
                        'candidat_matricule': candidat_propose.matricule,
                        'justification': justification,
                        'source': source_proposition,
                        'score_automatique': score_automatique,
                        'score_humain_ajuste': score_humain_valide,
                        'score_final': proposition.score_final,
                        'bonus_hierarchique': bonus_hierarchique,
                        'type_proposition': type_proposition,
                        'niveau_hierarchique': profil_utilisateur.type_profil,
                        'is_superuser': profil_utilisateur.is_superuser
                    }
                )
                
                # Mise à jour du workflow de la demande
                _mettre_a_jour_workflow_demande(demande, profil_utilisateur, proposition)
                
                # Création des notifications pour les validateurs
                _creer_notifications_nouvelle_proposition(demande, proposition, profil_utilisateur)
                
                # Données de retour pour le frontend
                data_retour = {
                    'proposition_id': proposition.id,
                    'numero_proposition': proposition.numero_proposition,
                    'candidat': {
                        'id': candidat_propose.id,
                        'nom_complet': candidat_propose.nom_complet,
                        'matricule': candidat_propose.matricule,
                        'departement': candidat_propose.departement.nom if candidat_propose.departement else '',
                        'poste': candidat_propose.poste.titre if candidat_propose.poste else ''
                    },
                    'scoring': {
                        'score_automatique': score_automatique,
                        'score_humain_ajuste': score_humain_valide,
                        'bonus_hierarchique': bonus_hierarchique,
                        'score_final': proposition.score_final
                    },
                    'source_proposition': source_proposition,
                    'source_display': proposition.source_display,
                    'statut': proposition.statut,
                    'date_creation': proposition.created_at.isoformat(),
                    'justification': justification,
                    'competences_specifiques': competences_specifiques,
                    'experience_pertinente': experience_pertinente
                }
                
                logger.info(f"Nouvelle proposition créée: {proposition.numero_proposition} par {profil_utilisateur.nom_complet}")
                
                return JsonResponse({
                    'success': True,
                    'message': f'Candidat {candidat_propose.nom_complet} proposé avec succès (Score: {proposition.score_final}/100)',
                    'data': data_retour
                })
                
        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur de validation : {str(e)}',
                'error_type': 'VALIDATION_ERROR'
            }, status=400)
            
        except Exception as e:
            logger.error(f"Erreur création proposition: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Erreur lors de la création de la proposition',
                'error_type': 'CREATION_ERROR',
                'details': None
            }, status=500)
    
    except DemandeInterim.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Demande d\'intérim introuvable',
            'error_type': 'DEMANDE_NOT_FOUND'
        }, status=404)
    
    except ProfilUtilisateur.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Profil utilisateur introuvable',
            'error_type': 'USER_PROFILE_NOT_FOUND'
        }, status=404)
    
    except Exception as e:
        logger.error(f"Erreur générale dans demande_interim_ajouter_proposition: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': 'Erreur système inattendue',
            'error_type': 'SYSTEM_ERROR',
            'details': None
        }, status=500)


def _determiner_source_proposition(profil_utilisateur):
    """Détermine la source de proposition selon la hiérarchie CORRIGÉE"""
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    
    type_profil_to_source = {
        'UTILISATEUR': 'DEMANDEUR_INITIAL',
        'CHEF_EQUIPE': 'CHEF_EQUIPE',
        'RESPONSABLE': 'RESPONSABLE',
        'DIRECTEUR': 'DIRECTEUR',
        'RH': 'RH',
        'ADMIN': 'ADMIN'
    }
    
    return type_profil_to_source.get(profil_utilisateur.type_profil, 'AUTRE')


def _calculer_bonus_hierarchique(profil_utilisateur):
    """Calcule le bonus selon la hiérarchie CORRIGÉE"""
    try:
        config_scoring = ConfigurationScoring.objects.filter(
            configuration_par_defaut=True,
            actif=True
        ).first()
        
        if not config_scoring:
            # Valeurs par défaut si pas de configuration
            bonus_defaults = {
                'UTILISATEUR': 0,
                'CHEF_EQUIPE': 8,
                'RESPONSABLE': 15,
                'DIRECTEUR': 18,
                'RH': 20,
                'ADMIN': 20
            }
            return bonus_defaults.get(profil_utilisateur.type_profil, 0)
        
        if profil_utilisateur.is_superuser:
            return config_scoring.bonus_superuser
        
        bonus_map = {
            'CHEF_EQUIPE': config_scoring.bonus_chef_equipe,
            'RESPONSABLE': config_scoring.bonus_responsable,
            'DIRECTEUR': config_scoring.bonus_directeur,
            'RH': config_scoring.bonus_rh,
            'ADMIN': config_scoring.bonus_admin
        }
        
        return bonus_map.get(profil_utilisateur.type_profil, 0)
        
    except Exception as e:
        logger.error(f"Erreur calcul bonus hiérarchique: {e}")
        return 0


def _calculer_score_automatique(candidat, demande):
    """Calcule le score automatique pour un candidat"""
    try:
        # Import local pour éviter les dépendances circulaires
        from mainapp.services.scoring_service import ScoringService
        
        scoring_service = ScoringService()
        score_data = scoring_service.calculer_score_candidat(candidat, demande)
        
        return int(score_data.get('score_total', 50))
        
    except Exception as e:
        logger.error(f"Erreur calcul score automatique: {e}")
        return 50  # Score par défaut


def _mettre_a_jour_workflow_demande(demande, proposant, proposition):
    """Met à jour le workflow de la demande"""
    try:
        workflow = getattr(demande, 'workflow', None)
        if workflow:
            workflow.nb_propositions_recues += 1
            workflow.ajouter_action(
                utilisateur=proposant,
                action=f"Nouvelle proposition: {proposition.candidat_propose.nom_complet}",
                commentaire=proposition.justification,
                metadata={
                    'proposition_id': proposition.id,
                    'score_final': proposition.score_final,
                    'source': proposition.source_proposition
                }
            )
            workflow.save()
    except Exception as e:
        logger.error(f"Erreur mise à jour workflow: {e}")


def _creer_notifications_nouvelle_proposition(demande, proposition, proposant):
    """Crée les notifications pour une nouvelle proposition"""
    try:
        # Notification au demandeur si ce n'est pas lui qui propose
        if demande.demandeur != proposant:
            NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=proposant,
                demande=demande,
                proposition_liee=proposition,
                type_notification='PROPOSITION_CANDIDAT',
                urgence='NORMALE' if demande.urgence == 'NORMALE' else 'HAUTE',
                titre=f"Nouvelle proposition pour votre demande {demande.numero_demande}",
                message=f"{proposant.nom_complet} a proposé {proposition.candidat_propose.nom_complet} pour votre demande d'intérim.",
                url_action_principale=f"/interim/demande/{demande.id}/",
                texte_action_principale="Voir la demande"
            )
        
        # Notifications aux validateurs selon le niveau
        validateurs = _obtenir_validateurs_pour_demande(demande)
        for validateur in validateurs:
            if validateur != proposant:  # Ne pas notifier le proposant
                NotificationInterim.objects.create(
                    destinataire=validateur,
                    expediteur=proposant,
                    demande=demande,
                    proposition_liee=proposition,
                    type_notification='CANDIDAT_PROPOSE_VALIDATION',
                    urgence='NORMALE' if demande.urgence == 'NORMALE' else 'HAUTE',
                    titre=f"Candidat proposé pour validation - {demande.numero_demande}",
                    message=f"{proposant.nom_complet} a proposé {proposition.candidat_propose.nom_complet} (Score: {proposition.score_final}/100)",
                    url_action_principale=f"/interim/validation/{demande.id}/",
                    texte_action_principale="Valider"
                )
        
    except Exception as e:
        logger.error(f"Erreur création notifications: {e}")


def _obtenir_validateurs_pour_demande(demande):
    """Obtient la liste des validateurs potentiels pour une demande"""
    try:
        validateurs = []
        
        # Responsables N+1 du département
        if demande.poste and demande.poste.departement:
            responsables = ProfilUtilisateur.objects.filter(
                type_profil='RESPONSABLE',
                departement=demande.poste.departement,
                actif=True
            )
            validateurs.extend(responsables)
        
        # Directeurs N+2
        directeurs = ProfilUtilisateur.objects.filter(
            type_profil='DIRECTEUR',
            actif=True
        )
        validateurs.extend(directeurs)
        
        # RH et Admin
        rh_admin = ProfilUtilisateur.objects.filter(
            type_profil__in=['RH', 'ADMIN'],
            actif=True
        )
        validateurs.extend(rh_admin)
        
        return list(set(validateurs))  # Éliminer les doublons
        
    except Exception as e:
        logger.error(f"Erreur obtention validateurs: {e}")
        return []
    
@login_required
def historique_mes_propositions(request):
    """
    Affiche l'historique des propositions de candidats faites par l'utilisateur connecté
    avec filtres par date, statut, et recherche textuelle
    """
    try:
        # Récupérer le profil utilisateur
        profil_utilisateur = get_object_or_404(
            ProfilUtilisateur.objects.select_related('user', 'departement', 'site'),
            user=request.user
        )

        # Paramètres de filtrage
        filtres = {
            'date_debut': request.GET.get('date_debut', ''),
            'date_fin': request.GET.get('date_fin', ''),
            'statut': request.GET.get('statut', ''),
            'urgence': request.GET.get('urgence', ''),
            'recherche': request.GET.get('recherche', ''),
            'ordre': request.GET.get('ordre', '-created_at')
        }

        # Base queryset : toutes les propositions de l'utilisateur
        propositions = PropositionCandidat.objects.filter(
            proposant=profil_utilisateur
        ).select_related(
            'demande_interim__poste__departement',
            'demande_interim__poste__site',
            'demande_interim__motif_absence',
            'demande_interim__candidat_selectionne',
            'candidat_propose__user',
            'candidat_propose__departement',
            'candidat_propose__poste',
            'evaluateur'
        ).prefetch_related(
            'demande_interim__validations',
            'demande_interim__reponses_candidats',
            'score_candidat'
        )

        # Filtrage par dates
        if filtres['date_debut']:
            try:
                date_debut = datetime.strptime(filtres['date_debut'], '%Y-%m-%d').date()
                propositions = propositions.filter(created_at__date__gte=date_debut)
            except ValueError:
                messages.warning(request, "Format de date de début invalide")

        if filtres['date_fin']:
            try:
                date_fin = datetime.strptime(filtres['date_fin'], '%Y-%m-%d').date()
                propositions = propositions.filter(created_at__date__lte=date_fin)
            except ValueError:
                messages.warning(request, "Format de date de fin invalide")

        # Filtrage par statut de proposition
        if filtres['statut']:
            propositions = propositions.filter(statut=filtres['statut'])

        # Filtrage par urgence de la demande
        if filtres['urgence']:
            propositions = propositions.filter(demande_interim__urgence=filtres['urgence'])

        # Recherche textuelle
        if filtres['recherche']:
            recherche_terms = filtres['recherche'].strip()
            propositions = propositions.filter(
                Q(candidat_propose__user__first_name__icontains=recherche_terms) |
                Q(candidat_propose__user__last_name__icontains=recherche_terms) |
                Q(candidat_propose__matricule__icontains=recherche_terms) |
                Q(demande_interim__numero_demande__icontains=recherche_terms) |
                Q(demande_interim__poste__titre__icontains=recherche_terms) |
                Q(justification__icontains=recherche_terms) |
                Q(competences_specifiques__icontains=recherche_terms)
            )

        # Tri
        ordre_mapping = {
            '-created_at': '-created_at',
            'created_at': 'created_at',
            '-score_final': '-score_final',
            'score_final': 'score_final',
            'candidat': 'candidat_propose__user__last_name',
            '-candidat': '-candidat_propose__user__last_name',
            'demande': 'demande_interim__numero_demande',
            '-demande': '-demande_interim__numero_demande',
            'statut': 'statut',
            '-statut': '-statut'
        }
        
        ordre_choisi = ordre_mapping.get(filtres['ordre'], '-created_at')
        propositions = propositions.order_by(ordre_choisi)

        # Statistiques globales
        total_propositions = propositions.count()
        
        # Répartition par statut
        stats_statuts = propositions.values('statut').annotate(
            count=Count('id')
        ).order_by('statut')

        # Répartition par issue (candidat retenu ou non)
        propositions_retenues = propositions.filter(
            candidat_propose=F('demande_interim__candidat_selectionne')
        ).count()

        # Score moyen des propositions
        score_moyen = propositions.exclude(
            score_final__isnull=True
        ).aggregate(
            moyenne=Avg('score_final'),
            maximum=Max('score_final'),
            minimum=Min('score_final')
        )

        # Dates de première et dernière proposition
        dates_extremes = propositions.aggregate(
            premiere=Min('created_at'),
            derniere=Max('created_at')
        )

        # Pagination
        paginator = Paginator(propositions, 10)  # 10 propositions par page
        page_number = request.GET.get('page', 1)
        
        try:
            page_obj = paginator.get_page(page_number)
        except (EmptyPage):
            page_obj = paginator.get_page(1)

        # Enrichir chaque proposition avec des données contextuelles
        propositions_enrichies = []
        for proposition in page_obj:
            try:
                # Informations sur le candidat finalement sélectionné
                candidat_selectionne_info = None
                if proposition.demande_interim.candidat_selectionne:
                    candidat_selectionne = proposition.demande_interim.candidat_selectionne
                    
                    # Chercher la proposition du candidat sélectionné
                    proposition_gagnante = PropositionCandidat.objects.filter(
                        demande_interim=proposition.demande_interim,
                        candidat_propose=candidat_selectionne
                    ).first()
                    
                    # Chercher son score détaillé
                    score_gagnant = ScoreDetailCandidat.objects.filter(
                        demande_interim=proposition.demande_interim,
                        candidat=candidat_selectionne
                    ).first()

                    candidat_selectionne_info = {
                        'candidat': candidat_selectionne,
                        'proposition': proposition_gagnante,
                        'score': score_gagnant,
                        'est_ma_proposition': candidat_selectionne == proposition.candidat_propose
                    }

                # Informations sur les validations de la demande
                validations_info = proposition.demande_interim.validations.select_related(
                    'validateur'
                ).order_by('niveau_validation')

                # Statut final de la demande
                statut_final = proposition.demande_interim.statut

                # Réponse du candidat proposé (si applicable)
                reponse_candidat = ReponseCandidatInterim.objects.filter(
                    demande=proposition.demande_interim,
                    candidat=proposition.candidat_propose
                ).first()

                propositions_enrichies.append({
                    'proposition': proposition,
                    'candidat_selectionne_info': candidat_selectionne_info,
                    'validations_info': validations_info,
                    'statut_final': statut_final,
                    'reponse_candidat': reponse_candidat,
                    'duree_mission': proposition.demande_interim.duree_mission,
                    'est_urgente': proposition.demande_interim.est_urgente,
                    'peut_etre_modifiee': proposition.demande_interim.peut_etre_modifiee
                })

            except Exception as e:
                logger.error(f"Erreur enrichissement proposition {proposition.id}: {e}")
                propositions_enrichies.append({
                    'proposition': proposition,
                    'candidat_selectionne_info': None,
                    'validations_info': [],
                    'statut_final': proposition.demande_interim.statut,
                    'reponse_candidat': None,
                    'duree_mission': 0,
                    'est_urgente': False,
                    'peut_etre_modifiee': False
                })

        # Choix pour les filtres
        statuts_choix = PropositionCandidat.STATUTS_PROPOSITION
        urgences_choix = DemandeInterim.URGENCES
        
        # Taux de réussite personnel
        taux_reussite = 0
        if total_propositions > 0:
            taux_reussite = round((propositions_retenues / total_propositions) * 100, 1)

        context = {
            'profil_utilisateur': profil_utilisateur,
            'propositions_enrichies': propositions_enrichies,
            'page_obj': page_obj,
            'paginator': paginator,
            
            # Statistiques
            'total_propositions': total_propositions,
            'propositions_retenues': propositions_retenues,
            'taux_reussite': taux_reussite,
            'stats_statuts': stats_statuts,
            'score_moyen': score_moyen,
            'dates_extremes': dates_extremes,
            
            # Filtres
            'filtres': filtres,
            'statuts_choix': statuts_choix,
            'urgences_choix': urgences_choix,
            
            # Navigation
            'can_export': True,
            'page_title': 'Historique de mes propositions',
            
            # Permissions
            'permissions': True,
        }

        return render(request, 'historique_mes_propositions.html', context)

    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return render(request, 'interim/error.html', {
            'error_message': 'Votre profil utilisateur n\'a pas été trouvé.'
        })
    
    except Exception as e:
        logger.error(f"Erreur dans historique_mes_propositions pour {request.user}: {e}")
        messages.error(request, "Une erreur s'est produite lors du chargement de l'historique")
        return render(request, 'interim/error.html', {
            'error_message': 'Erreur lors du chargement de l\'historique des propositions.'
        })
    
@login_required
def historique_interim(request):
    """
    Vue principale d'historique des demandes d'intérim avec gestion hiérarchique
    """
    try:
        # Récupérer le profil utilisateur
        profil_utilisateur = get_object_or_404(ProfilUtilisateur, user=request.user)
        
        # Définir les dates par défaut (3 derniers mois)
        date_fin_defaut = date.today()
        date_debut_defaut = date_fin_defaut - timedelta(days=90)
        
        # Récupérer les paramètres de filtrage
        filtres = {
            'date_debut': request.GET.get('date_debut', date_debut_defaut.strftime('%Y-%m-%d')),
            'date_fin': request.GET.get('date_fin', date_fin_defaut.strftime('%Y-%m-%d')),
            'statut': request.GET.get('statut', ''),
            'urgence': request.GET.get('urgence', ''),
            'departement': request.GET.get('departement', ''),
            'recherche': request.GET.get('recherche', '').strip(),
            'ordre': request.GET.get('ordre', '-created_at'),
        }
        
        # Construire la requête de base selon la hiérarchie
        queryset_base = construire_queryset_hierarchique(profil_utilisateur)
        
        # Appliquer les filtres de dates
        if filtres['date_debut']:
            try:
                date_debut = datetime.strptime(filtres['date_debut'], '%Y-%m-%d').date()
                queryset_base = queryset_base.filter(created_at__date__gte=date_debut)
            except ValueError:
                messages.warning(request, "Format de date de début invalide")
        
        if filtres['date_fin']:
            try:
                date_fin = datetime.strptime(filtres['date_fin'], '%Y-%m-%d').date()
                queryset_base = queryset_base.filter(created_at__date__lte=date_fin)
            except ValueError:
                messages.warning(request, "Format de date de fin invalide")
        
        # Appliquer les autres filtres
        if filtres['statut']:
            queryset_base = queryset_base.filter(statut=filtres['statut'])
        
        if filtres['urgence']:
            queryset_base = queryset_base.filter(urgence=filtres['urgence'])
        
        if filtres['departement']:
            queryset_base = queryset_base.filter(poste__departement_id=filtres['departement'])
        
        # Recherche textuelle
        if filtres['recherche']:
            termes_recherche = filtres['recherche'].split()
            q_recherche = Q()
            for terme in termes_recherche:
                q_recherche |= (
                    Q(numero_demande__icontains=terme) |
                    Q(personne_remplacee__user__first_name__icontains=terme) |
                    Q(personne_remplacee__user__last_name__icontains=terme) |
                    Q(personne_remplacee__matricule__icontains=terme) |
                    Q(candidat_selectionne__user__first_name__icontains=terme) |
                    Q(candidat_selectionne__user__last_name__icontains=terme) |
                    Q(candidat_selectionne__matricule__icontains=terme) |
                    Q(poste__titre__icontains=terme) |
                    Q(poste__site__nom__icontains=terme) |
                    Q(description_poste__icontains=terme) |
                    Q(demandeur__user__first_name__icontains=terme) |
                    Q(demandeur__user__last_name__icontains=terme)
                )
            queryset_base = queryset_base.filter(q_recherche)
        
        # Ordonner les résultats
        ordre_valides = [
            '-created_at', 'created_at', '-date_debut', 'date_debut',
            '-urgence', 'urgence', 'numero_demande', '-numero_demande',
            'statut', '-statut', 'poste', '-poste'
        ]
        ordre = filtres['ordre'] if filtres['ordre'] in ordre_valides else '-created_at'
        
        if ordre in ['poste', '-poste']:
            queryset_base = queryset_base.order_by(f"{ordre}__titre")
        else:
            queryset_base = queryset_base.order_by(ordre)
        
        # Calculer les statistiques globales
        statistiques = calculer_statistiques_historique(queryset_base, profil_utilisateur)
        
        # Enrichir les demandes avec les informations détaillées
        demandes_enrichies = []
        for demande in queryset_base:
            demande_enrichie = enrichir_demande_historique(demande)
            demandes_enrichies.append(demande_enrichie)
        
        # Pagination
        paginator = Paginator(demandes_enrichies, 10)  # 10 demandes par page
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        # Préparer les choix pour les filtres
        statuts_choix = DemandeInterim.STATUTS
        urgences_choix = DemandeInterim.URGENCES
        
        # Départements accessibles selon la hiérarchie
        departements_accessibles = obtenir_departements_accessibles(profil_utilisateur)
        
        context = {
            'page_title': 'Historique des demandes d\'intérim',
            'profil_utilisateur': profil_utilisateur,
            'demandes_enrichies': page_obj,
            'paginator': paginator,
            'page_obj': page_obj,
            'filtres': filtres,
            'statistiques': statistiques,
            'statuts_choix': statuts_choix,
            'urgences_choix': urgences_choix,
            'departements_accessibles': departements_accessibles,
            'peut_voir_tout': profil_utilisateur.type_profil in ['RH', 'ADMIN'] or profil_utilisateur.is_superuser,
            'niveau_acces': determiner_niveau_acces(profil_utilisateur),
        }
        
        return render(request, 'historique_interim.html', context)
        
    except Exception as e:
        logger.error(f"Erreur dans historique_interim: {e}")
        messages.error(request, "Une erreur s'est produite lors du chargement de l'historique")
        
        # Context minimal en cas d'erreur
        context = {
            'page_title': 'Historique des demandes d\'intérim',
            'profil_utilisateur': get_object_or_404(ProfilUtilisateur, user=request.user),
            'demandes_enrichies': [],
            'filtres': {},
            'statistiques': {},
            'error': True
        }
        return render(request, 'historique_interim.html', context)


def construire_queryset_hierarchique(profil_utilisateur):
    """
    Construit le queryset selon la hiérarchie organisationnelle
    """
    # Requête de base avec optimisations
    queryset_base = DemandeInterim.objects.select_related(
        'demandeur__user', 'personne_remplacee__user', 'candidat_selectionne__user',
        'poste__departement', 'poste__site', 'motif_absence'
    ).prefetch_related(
        'propositions_candidats__candidat_propose__user',
        'propositions_candidats__proposant__user',
        'validations__validateur__user',
        'scores_candidats'
    )
    
    # Superutilisateurs, RH et ADMIN voient tout
    if profil_utilisateur.is_superuser or profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return queryset_base.all()
    
    # DIRECTEUR : voit les demandes de ses RESPONSABLES + ses propres demandes
    elif profil_utilisateur.type_profil == 'DIRECTEUR':
        responsables_geres = ProfilUtilisateur.objects.filter(
            manager=profil_utilisateur,
            type_profil='RESPONSABLE'
        )
        
        # Chefs d'équipe sous les responsables
        chefs_equipe_geres = ProfilUtilisateur.objects.filter(
            manager__in=responsables_geres,
            type_profil='CHEF_EQUIPE'
        )
        
        # Utilisateurs sous les chefs d'équipe
        utilisateurs_geres = ProfilUtilisateur.objects.filter(
            manager__in=chefs_equipe_geres,
            type_profil='UTILISATEUR'
        )
        
        # Toutes les personnes dans sa hiérarchie
        personnes_gerees = list(responsables_geres) + list(chefs_equipe_geres) + list(utilisateurs_geres)
        
        return queryset_base.filter(
            Q(demandeur=profil_utilisateur) |  # Ses propres demandes
            Q(demandeur__in=personnes_gerees)  # Demandes de sa hiérarchie
        )
    
    # RESPONSABLE : voit les demandes de ses CHEF_EQUIPE + ses propres demandes
    elif profil_utilisateur.type_profil == 'RESPONSABLE':
        chefs_equipe_geres = ProfilUtilisateur.objects.filter(
            manager=profil_utilisateur,
            type_profil='CHEF_EQUIPE'
        )
        
        # Utilisateurs sous les chefs d'équipe
        utilisateurs_geres = ProfilUtilisateur.objects.filter(
            manager__in=chefs_equipe_geres,
            type_profil='UTILISATEUR'
        )
        
        personnes_gerees = list(chefs_equipe_geres) + list(utilisateurs_geres)
        
        return queryset_base.filter(
            Q(demandeur=profil_utilisateur) |  # Ses propres demandes
            Q(demandeur__in=personnes_gerees)  # Demandes de ses équipes
        )
    
    # CHEF_EQUIPE : voit les demandes de ses UTILISATEURS + ses propres demandes
    elif profil_utilisateur.type_profil == 'CHEF_EQUIPE':
        utilisateurs_geres = ProfilUtilisateur.objects.filter(
            manager=profil_utilisateur,
            type_profil='UTILISATEUR'
        )
        
        return queryset_base.filter(
            Q(demandeur=profil_utilisateur) |  # Ses propres demandes
            Q(demandeur__in=utilisateurs_geres)  # Demandes de son équipe
        )
    
    # UTILISATEUR : voit seulement ses propres demandes
    else:
        return queryset_base.filter(demandeur=profil_utilisateur)


def calculer_statistiques_historique(queryset, profil_utilisateur):
    """
    Calcule les statistiques pour l'historique
    """
    try:
        total_demandes = queryset.count()
        
        if total_demandes == 0:
            return {
                'total_demandes': 0,
                'demandes_terminees': 0,
                'taux_completion': 0,
                'score_moyen': {'moyenne': 0},
                'dates_extremes': {'premiere': None, 'derniere': None},
                'repartition_statuts': {},
                'repartition_urgences': {},
                'duree_moyenne_mission': 0
            }
        
        # Statistiques de base
        demandes_terminees = queryset.filter(statut='TERMINEE').count()
        taux_completion = round((demandes_terminees / total_demandes) * 100, 1) if total_demandes > 0 else 0
        
        # Score moyen des candidats sélectionnés
        score_moyen = queryset.filter(
            candidat_selectionne__isnull=False
        ).aggregate(
            moyenne=Avg('scores_candidats__score_total')
        )
        
        # Dates extrêmes
        dates_extremes = queryset.aggregate(
            premiere=Min('created_at'),
            derniere=Max('created_at')
        )
        
        # Répartition par statuts
        repartition_statuts = {}
        for statut_key, statut_label in DemandeInterim.STATUTS:
            count = queryset.filter(statut=statut_key).count()
            if count > 0:
                repartition_statuts[statut_label] = count
        
        # Répartition par urgences
        repartition_urgences = {}
        for urgence_key, urgence_label in DemandeInterim.URGENCES:
            count = queryset.filter(urgence=urgence_key).count()
            if count > 0:
                repartition_urgences[urgence_label] = count
        
        # Durée moyenne des missions
        duree_moyenne = 0
        missions_avec_dates = queryset.filter(
            date_debut__isnull=False,
            date_fin__isnull=False
        )
        if missions_avec_dates.exists():
            durees = []
            for demande in missions_avec_dates:
                duree = (demande.date_fin - demande.date_debut).days + 1
                durees.append(duree)
            duree_moyenne = round(sum(durees) / len(durees), 1) if durees else 0
        
        return {
            'total_demandes': total_demandes,
            'demandes_terminees': demandes_terminees,
            'taux_completion': taux_completion,
            'score_moyen': score_moyen or {'moyenne': 0},
            'dates_extremes': dates_extremes,
            'repartition_statuts': repartition_statuts,
            'repartition_urgences': repartition_urgences,
            'duree_moyenne_mission': duree_moyenne
        }
        
    except Exception as e:
        logger.error(f"Erreur calcul statistiques historique: {e}")
        return {
            'total_demandes': 0,
            'error': True
        }


def enrichir_demande_historique(demande):
    """
    Enrichit une demande avec toutes les informations nécessaires à l'affichage
    """
    try:
        # Informations de base
        demande_enrichie = {
            'demande': demande,
            'duree_mission': 0,
            'est_urgente': demande.urgence in ['ELEVEE', 'CRITIQUE'],
            'candidat_selectionne_info': None,
            'propositions_recues': [],
            'validations_recues': [],
            'score_gagnant': None,
            'justification_selection': '',
            'nb_propositions': 0,
            'evolution_statut': [],
        }
        
        # Calculer la durée de mission
        if demande.date_debut and demande.date_fin:
            demande_enrichie['duree_mission'] = (demande.date_fin - demande.date_debut).days + 1
        
        # Informations sur le candidat sélectionné
        if demande.candidat_selectionne:
            candidat_selectionne_info = {
                'candidat': demande.candidat_selectionne,
                'score': None,
                'proposition': None,
                'justification': '',
            }
            
            # Récupérer le score du candidat sélectionné
            try:
                score_candidat = ScoreDetailCandidat.objects.filter(
                    demande_interim=demande,
                    candidat=demande.candidat_selectionne
                ).first()
                candidat_selectionne_info['score'] = score_candidat
            except Exception:
                pass
            
            # Récupérer la proposition qui a mené à la sélection
            try:
                proposition_gagnante = PropositionCandidat.objects.filter(
                    demande_interim=demande,
                    candidat_propose=demande.candidat_selectionne,
                    statut='VALIDEE'
                ).first()
                
                if proposition_gagnante:
                    candidat_selectionne_info['proposition'] = proposition_gagnante
                    candidat_selectionne_info['justification'] = proposition_gagnante.justification
            except Exception:
                pass
            
            demande_enrichie['candidat_selectionne_info'] = candidat_selectionne_info
        
        # Toutes les propositions reçues
        try:
            propositions = demande.propositions_candidats.select_related(
                'candidat_propose__user', 'proposant__user', 'evaluateur__user'
            ).order_by('-score_final', '-created_at')
            
            demande_enrichie['propositions_recues'] = list(propositions)
            demande_enrichie['nb_propositions'] = propositions.count()
            
            # Score du candidat gagnant
            if propositions.exists():
                meilleure_proposition = propositions.first()
                demande_enrichie['score_gagnant'] = meilleure_proposition.score_final
                
        except Exception as e:
            logger.error(f"Erreur enrichissement propositions: {e}")
        
        # Historique des validations
        try:
            validations = demande.validations.select_related(
                'validateur__user'
            ).order_by('niveau_validation', 'created_at')
            
            demande_enrichie['validations_recues'] = list(validations)
        except Exception as e:
            logger.error(f"Erreur enrichissement validations: {e}")
        
        # Évolution du statut depuis l'historique des actions
        try:
            actions_statut = HistoriqueAction.objects.filter(
                demande=demande,
                action__in=['CREATION_DEMANDE', 'VALIDATION_RESPONSABLE', 'VALIDATION_DIRECTEUR', 
                           'VALIDATION_RH', 'SELECTION_CANDIDAT', 'DEBUT_MISSION', 'FIN_MISSION']
            ).select_related('utilisateur__user').order_by('created_at')
            
            evolution = []
            for action in actions_statut:
                evolution.append({
                    'date': action.created_at,
                    'action': action.get_action_display(),
                    'utilisateur': action.utilisateur.nom_complet if action.utilisateur else 'Système',
                    'description': action.description
                })
            
            demande_enrichie['evolution_statut'] = evolution
        except Exception as e:
            logger.error(f"Erreur enrichissement évolution: {e}")
        
        return demande_enrichie
        
    except Exception as e:
        logger.error(f"Erreur enrichissement demande {demande.id}: {e}")
        return {
            'demande': demande,
            'error': True
        }


def obtenir_departements_accessibles(profil_utilisateur):
    """
    Retourne les départements accessibles selon la hiérarchie
    """
    try:
        # Superutilisateurs, RH et ADMIN voient tous les départements
        if profil_utilisateur.is_superuser or profil_utilisateur.type_profil in ['RH', 'ADMIN']:
            from .models import Departement
            return Departement.objects.filter(actif=True).order_by('nom')
        
        # Autres : départements dans leur scope hiérarchique
        departements_ids = set()
        
        if profil_utilisateur.departement:
            departements_ids.add(profil_utilisateur.departement.id)
        
        # Ajouter les départements des personnes gérées
        if profil_utilisateur.type_profil in ['DIRECTEUR', 'RESPONSABLE', 'CHEF_EQUIPE']:
            personnes_gerees = ProfilUtilisateur.objects.filter(
                manager=profil_utilisateur
            ).values_list('departement', flat=True)
            
            departements_ids.update([d for d in personnes_gerees if d])
        
        from .models import Departement
        return Departement.objects.filter(
            id__in=departements_ids,
            actif=True
        ).order_by('nom')
        
    except Exception as e:
        logger.error(f"Erreur obtention départements accessibles: {e}")
        return []


def determiner_niveau_acces(profil_utilisateur):
    """
    Détermine le niveau d'accès pour l'affichage
    """
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    elif profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return 'GLOBAL'
    elif profil_utilisateur.type_profil == 'DIRECTEUR':
        return 'DIRECTEUR'
    elif profil_utilisateur.type_profil == 'RESPONSABLE':
        return 'RESPONSABLE'
    elif profil_utilisateur.type_profil == 'CHEF_EQUIPE':
        return 'CHEF_EQUIPE'
    else:
        return 'UTILISATEUR'

@login_required
def interim_recherche(request):
    """
    Vue de recherche avancée des demandes d'intérim avec scoring et workflow
    """
    try:
        # Récupérer le profil utilisateur
        try:
            profil_utilisateur = ProfilUtilisateur.objects.select_related('user', 'departement', 'site').get(
                user=request.user
            )
        except ProfilUtilisateur.DoesNotExist:
            messages.error(request, "Profil utilisateur non trouvé.")
            return render(request, 'interim_recherche.html', {'error': True})

        # Paramètres de recherche
        search_query = request.GET.get('q', '').strip()
        departement_id = request.GET.get('departement', '')
        site_id = request.GET.get('site', '')
        statut = request.GET.get('statut', '')
        urgence = request.GET.get('urgence', '')
        date_debut = request.GET.get('date_debut', '')
        date_fin = request.GET.get('date_fin', '')
        avec_candidat_choisi = request.GET.get('avec_candidat', '')
        score_min = request.GET.get('score_min', '')
        score_max = request.GET.get('score_max', '')
        niveau_validation = request.GET.get('niveau_validation', '')
        
        # Construction de la requête de base avec toutes les relations
        demandes_qs = DemandeInterim.objects.select_related(
            'demandeur__user',
            'personne_remplacee__user', 
            'poste__departement',
            'poste__site',
            'motif_absence',
            'candidat_selectionne__user'
        ).prefetch_related(
            Prefetch('propositions_candidats', queryset=PropositionCandidat.objects.select_related(
                'candidat_propose__user', 'proposant__user'
            ).order_by('-score_final')),
            Prefetch('validations', queryset=ValidationDemande.objects.select_related(
                'validateur__user'
            ).order_by('niveau_validation')),
            Prefetch('scores_candidats', queryset=ScoreDetailCandidat.objects.select_related(
                'candidat__user'
            ).order_by('-score_total')),
            'historique_actions__utilisateur__user'
        ).distinct()

        # Filtres selon les permissions utilisateur
        if not profil_utilisateur.is_superuser:
            if profil_utilisateur.type_profil in ['RH', 'ADMIN']:
                # RH et ADMIN voient tout
                pass
            elif profil_utilisateur.type_profil in ['DIRECTEUR']:
                # Directeurs voient leur département et sous-départements
                pass
            elif profil_utilisateur.type_profil in ['RESPONSABLE']:
                # Responsables voient leur département
                demandes_qs = demandes_qs.filter(
                    Q(poste__departement=profil_utilisateur.departement) |
                    Q(demandeur=profil_utilisateur) |
                    Q(candidat_selectionne=profil_utilisateur)
                )
            else:
                # Utilisateurs standards voient leurs demandes et celles où ils sont impliqués
                demandes_qs = demandes_qs.filter(
                    Q(demandeur=profil_utilisateur) |
                    Q(personne_remplacee=profil_utilisateur) |
                    Q(candidat_selectionne=profil_utilisateur) |
                    Q(propositions_candidats__candidat_propose=profil_utilisateur) |
                    Q(propositions_candidats__proposant=profil_utilisateur)
                )

        # Application des filtres de recherche
        if search_query:
            demandes_qs = demandes_qs.filter(
                Q(numero_demande__icontains=search_query) |
                Q(poste__titre__icontains=search_query) |
                Q(demandeur__user__first_name__icontains=search_query) |
                Q(demandeur__user__last_name__icontains=search_query) |
                Q(demandeur__matricule__icontains=search_query) |
                Q(personne_remplacee__user__first_name__icontains=search_query) |
                Q(personne_remplacee__user__last_name__icontains=search_query) |
                Q(personne_remplacee__matricule__icontains=search_query) |
                Q(candidat_selectionne__user__first_name__icontains=search_query) |
                Q(candidat_selectionne__user__last_name__icontains=search_query) |
                Q(candidat_selectionne__matricule__icontains=search_query) |
                Q(description_poste__icontains=search_query) |
                Q(instructions_particulieres__icontains=search_query) |
                Q(motif_absence__nom__icontains=search_query) |
                Q(poste__departement__nom__icontains=search_query) |
                Q(poste__site__nom__icontains=search_query)
            )

        if departement_id:
            demandes_qs = demandes_qs.filter(poste__departement_id=departement_id)

        if site_id:
            demandes_qs = demandes_qs.filter(poste__site_id=site_id)

        if statut:
            demandes_qs = demandes_qs.filter(statut=statut)

        if urgence:
            demandes_qs = demandes_qs.filter(urgence=urgence)

        if niveau_validation:
            demandes_qs = demandes_qs.filter(niveau_validation_actuel=niveau_validation)

        if avec_candidat_choisi == 'oui':
            demandes_qs = demandes_qs.filter(candidat_selectionne__isnull=False)
        elif avec_candidat_choisi == 'non':
            demandes_qs = demandes_qs.filter(candidat_selectionne__isnull=True)

        # Filtres de dates
        if date_debut:
            try:
                date_debut_parsed = datetime.strptime(date_debut, '%Y-%m-%d').date()
                demandes_qs = demandes_qs.filter(date_debut__gte=date_debut_parsed)
            except ValueError:
                messages.warning(request, "Format de date de début invalide")

        if date_fin:
            try:
                date_fin_parsed = datetime.strptime(date_fin, '%Y-%m-%d').date()
                demandes_qs = demandes_qs.filter(date_fin__lte=date_fin_parsed)
            except ValueError:
                messages.warning(request, "Format de date de fin invalide")

        # Filtres de scores (sur les candidats sélectionnés)
        if score_min:
            try:
                score_min_val = int(score_min)
                demandes_qs = demandes_qs.filter(
                    scores_candidats__candidat=models.F('candidat_selectionne'),
                    scores_candidats__score_total__gte=score_min_val
                )
            except ValueError:
                messages.warning(request, "Score minimum invalide")

        if score_max:
            try:
                score_max_val = int(score_max)
                demandes_qs = demandes_qs.filter(
                    scores_candidats__candidat=models.F('candidat_selectionne'),
                    scores_candidats__score_total__lte=score_max_val
                )
            except ValueError:
                messages.warning(request, "Score maximum invalide")

        # Tri par défaut : plus récentes en premier
        demandes_qs = demandes_qs.order_by('-created_at')

        # Statistiques de recherche avec calculs de pourcentages
        total_demandes = demandes_qs.count()
        demandes_avec_candidat = demandes_qs.filter(candidat_selectionne__isnull=False).count()
        demandes_en_cours = demandes_qs.filter(statut__in=['SOUMISE', 'EN_VALIDATION', 'EN_RECHERCHE']).count()
        demandes_terminees = demandes_qs.filter(statut='TERMINEE').count()
        demandes_urgentes = demandes_qs.filter(urgence__in=['ELEVEE', 'CRITIQUE']).count()
        demandes_refusees = demandes_qs.filter(statut='REFUSEE').count()
        demandes_annulees = demandes_qs.filter(statut='ANNULEE').count()

        # Calculs de pourcentages (éviter division par zéro)
        if total_demandes > 0:
            pct_avec_candidat = round((demandes_avec_candidat / total_demandes) * 100, 1)
            pct_en_cours = round((demandes_en_cours / total_demandes) * 100, 1)
            pct_terminees = round((demandes_terminees / total_demandes) * 100, 1)
            pct_urgentes = round((demandes_urgentes / total_demandes) * 100, 1)
            pct_refusees = round((demandes_refusees / total_demandes) * 100, 1)
            pct_annulees = round((demandes_annulees / total_demandes) * 100, 1)
            taux_succes = pct_avec_candidat
        else:
            pct_avec_candidat = pct_en_cours = pct_terminees = pct_urgentes = 0
            pct_refusees = pct_annulees = taux_succes = 0

        # Calcul du score moyen des candidats sélectionnés
        score_moyen_candidats = None
        candidats_avec_score = ScoreDetailCandidat.objects.filter(
            demande_interim__in=demandes_qs.filter(candidat_selectionne__isnull=False),
            candidat=models.F('demande_interim__candidat_selectionne')
        ).aggregate(score_moyen=Avg('score_total'))
        
        if candidats_avec_score['score_moyen']:
            score_moyen_candidats = round(candidats_avec_score['score_moyen'], 1)

        # Statistiques par département
        stats_departements = demandes_qs.values(
            'poste__departement__nom'
        ).annotate(
            count=Count('id'),
            avec_candidat=Count('candidat_selectionne'),
            score_moyen=Avg('scores_candidats__score_total')
        ).order_by('-count')[:5]

        # Statistiques temporelles (évolution sur 7 jours)
        from datetime import timedelta
        evolution_7j = []
        for i in range(7):
            date_jour = timezone.now().date() - timedelta(days=i)
            count_jour = demandes_qs.filter(created_at__date=date_jour).count()
            evolution_7j.append({
                'date': date_jour.strftime('%d/%m'),
                'count': count_jour
            })
        evolution_7j.reverse()  # Plus ancien au plus récent

        # Distribution des scores
        distribution_scores = {
            'excellent': demandes_qs.filter(
                scores_candidats__score_total__gte=80,
                candidat_selectionne__isnull=False
            ).count(),
            'bon': demandes_qs.filter(
                scores_candidats__score_total__gte=60,
                scores_candidats__score_total__lt=80,
                candidat_selectionne__isnull=False
            ).count(),
            'moyen': demandes_qs.filter(
                scores_candidats__score_total__gte=40,
                scores_candidats__score_total__lt=60,
                candidat_selectionne__isnull=False
            ).count(),
            'faible': demandes_qs.filter(
                scores_candidats__score_total__lt=40,
                candidat_selectionne__isnull=False
            ).count()
        }

        # Pagination
        page = request.GET.get('page', 1)
        paginator = Paginator(demandes_qs, 10)  # 10 demandes par page
        
        try:
            demandes = paginator.page(page)
        except PageNotAnInteger:
            demandes = paginator.page(1)
        except EmptyPage:
            demandes = paginator.page(paginator.num_pages)

        # Enrichissement des données pour chaque demande
        demandes_enrichies = []
        for demande in demandes:
            # Récupérer les détails du candidat sélectionné
            candidat_info = None
            if demande.candidat_selectionne:
                try:
                    score_detail = demande.scores_candidats.filter(
                        candidat=demande.candidat_selectionne
                    ).first()
                    
                    proposition_candidat = demande.propositions_candidats.filter(
                        candidat_propose=demande.candidat_selectionne
                    ).first()
                    
                    candidat_info = {
                        'candidat': demande.candidat_selectionne,
                        'score_detail': score_detail,
                        'proposition': proposition_candidat,
                        'score_total': score_detail.score_total if score_detail else 0
                    }
                except Exception as e:
                    logger.error(f"Erreur récupération infos candidat pour demande {demande.id}: {e}")

            # Statistiques des propositions
            nb_propositions = demande.propositions_candidats.count()
            meilleur_score = 0
            if demande.propositions_candidats.exists():
                meilleur_score = max([p.score_final for p in demande.propositions_candidats.all()])

            # Progression du workflow
            progression = {
                'niveau_actuel': demande.niveau_validation_actuel,
                'niveau_max': demande.niveaux_validation_requis,
                'pourcentage': 0
            }
            
            if demande.niveaux_validation_requis > 0:
                progression['pourcentage'] = min(100, 
                    (demande.niveau_validation_actuel / demande.niveaux_validation_requis) * 100
                )

            # Dernière action
            derniere_action = demande.historique_actions.first()

            demandes_enrichies.append({
                'demande': demande,
                'candidat_info': candidat_info,
                'nb_propositions': nb_propositions,
                'meilleur_score': meilleur_score,
                'progression': progression,
                'derniere_action': derniere_action
            })

        # Données pour les filtres
        departements = Departement.objects.filter(actif=True).order_by('nom')
        sites = Site.objects.filter(actif=True).order_by('nom')

        # Compter les demandes par statut pour les filtres
        statuts_count = {}
        for statut_code, statut_label in DemandeInterim.STATUTS:
            count = demandes_qs.filter(statut=statut_code).count()
            if count > 0:
                statuts_count[statut_code] = {'label': statut_label, 'count': count}

        context = {
            'page_title': 'Recherche de demandes d\'intérim',
            'profil_utilisateur': profil_utilisateur,
            'demandes': demandes,
            'demandes_enrichies': demandes_enrichies,
            'departements': departements,
            'sites': sites,
            'statuts_choices': DemandeInterim.STATUTS,
            'urgences_choices': DemandeInterim.URGENCES,
            'statuts_count': statuts_count,
            
            # Paramètres de recherche actuels
            'search_params': {
                'q': search_query,
                'departement': departement_id,
                'site': site_id,
                'statut': statut,
                'urgence': urgence,
                'date_debut': date_debut,
                'date_fin': date_fin,
                'avec_candidat': avec_candidat_choisi,
                'score_min': score_min,
                'score_max': score_max,
                'niveau_validation': niveau_validation,
            },
            
            # Statistiques
            'stats': {
                'total_demandes': total_demandes,
                'demandes_avec_candidat': demandes_avec_candidat,
                'demandes_en_cours': demandes_en_cours,
                'demandes_terminees': demandes_terminees,
                'demandes_urgentes': demandes_urgentes,
                'demandes_refusees': demandes_refusees,
                'demandes_annulees': demandes_annulees,
                'score_moyen_candidats': score_moyen_candidats,
                
                # Pourcentages calculés
                'pct_avec_candidat': pct_avec_candidat,
                'pct_en_cours': pct_en_cours,
                'pct_terminees': pct_terminees,
                'pct_urgentes': pct_urgentes,
                'pct_refusees': pct_refusees,
                'pct_annulees': pct_annulees,
                'taux_succes': taux_succes,
                
                # Données pour graphiques
                'evolution_7j': evolution_7j,
                'distribution_scores': distribution_scores,
                'stats_departements': list(stats_departements),
                
                # Tendances (exemple de calcul simple)
                'tendance_mois': '+12' if total_demandes > 10 else '+5',  # À adapter selon vos données réelles
                'tendance_succes': 'up' if taux_succes > 70 else 'down',
            },
            
            # Pagination
            'has_search': bool(search_query or departement_id or site_id or statut or urgence or 
                             date_debut or date_fin or avec_candidat_choisi or score_min or 
                             score_max or niveau_validation),
        }
        
        # Si c'est une requête AJAX pour l'autocomplete
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            if request.GET.get('action') == 'autocomplete':
                query = request.GET.get('term', '').strip()
                suggestions = []
                
                if len(query) >= 2:
                    # Recherche dans les numéros de demande
                    demandes_nums = DemandeInterim.objects.filter(
                        numero_demande__icontains=query
                    ).values_list('numero_demande', flat=True)[:5]
                    
                    for num in demandes_nums:
                        suggestions.append({
                            'label': f"Demande: {num}",
                            'value': num,
                            'category': 'Numéros de demande'
                        })
                    
                    # Recherche dans les noms de postes
                    postes = Poste.objects.filter(
                        titre__icontains=query, actif=True
                    ).values_list('titre', flat=True).distinct()[:5]
                    
                    for poste in postes:
                        suggestions.append({
                            'label': f"Poste: {poste}",
                            'value': poste,
                            'category': 'Postes'
                        })
                
                return JsonResponse({'suggestions': suggestions})

        return render(request, 'interim_recherche.html', context)

    except Exception as e:
        logger.error(f"Erreur dans interim_recherche: {e}")
        messages.error(request, f"Erreur lors de la recherche: {str(e)}")
        
        context = {
            'page_title': 'Recherche de demandes d\'intérim',
            'error': True,
            'error_message': str(e)
        }
        return render(request, 'interim_recherche.html', context)
    
from django.shortcuts import render
from django.db.models import Count, Avg, Sum, Q, F, Case, When, IntegerField, DecimalField, Max, Min
from django.utils import timezone
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.db.models.functions import TruncMonth, TruncWeek, Extract
from decimal import Decimal
import json

@login_required
def interim_stats(request):
    """Vue principale des statistiques d'intérim"""
    
    # Récupération des paramètres de date
    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')
    
    # Dates par défaut (3 derniers mois)
    if not date_debut:
        date_debut = (timezone.now() - timedelta(days=90)).date()
    else:
        date_debut = datetime.strptime(date_debut, '%Y-%m-%d').date()
    
    if not date_fin:
        date_fin = timezone.now().date()
    else:
        date_fin = datetime.strptime(date_fin, '%Y-%m-%d').date()
    
    # Filtrage des demandes d'intérim sur la période
    demandes = DemandeInterim.objects.filter(
        created_at__date__gte=date_debut,
        created_at__date__lte=date_fin
    )
    
    # ===== STATISTIQUES DE VOLUME =====
    
    # Nombre total d'intérims
    total_interims = demandes.count()
    
    # Évolution par mois
    interims_par_mois = demandes.annotate(
        mois=TruncMonth('created_at')
    ).values('mois').annotate(
        count=Count('id')
    ).order_by('mois')
    
    # Évolution par semaine (4 dernières semaines)
    date_4_semaines = timezone.now().date() - timedelta(weeks=4)
    interims_par_semaine = demandes.filter(
        created_at__date__gte=date_4_semaines
    ).annotate(
        semaine=TruncWeek('created_at')
    ).values('semaine').annotate(
        count=Count('id')
    ).order_by('semaine')
    
    # Durée moyenne des missions (pour les demandes avec dates définies)
    demandes_avec_duree = demandes.filter(
        date_debut__isnull=False,
        date_fin__isnull=False
    )
    
    if demandes_avec_duree.exists():
        duree_moyenne = demandes_avec_duree.aggregate(
            duree_moy=Avg(F('date_fin') - F('date_debut'))
        )['duree_moy']
        duree_moyenne_jours = duree_moyenne.days if duree_moyenne else 0
    else:
        duree_moyenne_jours = 0
    
    # Répartition par durée
    repartition_duree = demandes_avec_duree.aggregate(
        moins_1_semaine=Count('id', filter=Q(date_fin__lt=F('date_debut') + timedelta(days=7))),
        de_1_a_4_semaines=Count('id', filter=Q(
            date_fin__gte=F('date_debut') + timedelta(days=7),
            date_fin__lt=F('date_debut') + timedelta(days=28)
        )),
        de_1_a_3_mois=Count('id', filter=Q(
            date_fin__gte=F('date_debut') + timedelta(days=28),
            date_fin__lt=F('date_debut') + timedelta(days=90)
        )),
        plus_3_mois=Count('id', filter=Q(date_fin__gte=F('date_debut') + timedelta(days=90)))
    )
    
    # Nombre de renouvellements/prolongations (demandes avec statut EN_COURS ou TERMINEE)
    renouvellements = demandes.filter(
        statut__in=['EN_COURS', 'TERMINEE'],
        numero_demande__contains='RENOUV'  # Supposer un pattern de nommage
    ).count()
    
    # ===== ANALYSE DES SECTEURS/MÉTIERS =====
    
    # Top 10 des postes les plus demandés
    top_postes = demandes.values('poste__titre').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Répartition par secteur (via département)
    repartition_secteur = demandes.values('poste__departement__nom').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Évolution demande par secteur (comparaison avec période précédente)
    periode_precedente_debut = date_debut - (date_fin - date_debut)
    periode_precedente_fin = date_debut
    
    secteurs_actuels = demandes.values('poste__departement__nom').annotate(
        count_actuel=Count('id')
    )
    
    secteurs_precedents = DemandeInterim.objects.filter(
        created_at__date__gte=periode_precedente_debut,
        created_at__date__lt=periode_precedente_fin
    ).values('poste__departement__nom').annotate(
        count_precedent=Count('id')
    )
    
    # Postes difficiles à pourvoir (ratio propositions/demandes)
    postes_difficiles = demandes.values('poste__titre').annotate(
        nb_demandes=Count('id'),
        nb_propositions=Count('propositions_candidats'),
        ratio=Case(
            When(propositions_candidats__isnull=False, 
                 then=F('nb_propositions') / F('nb_demandes')),
            default=0,
            output_field=DecimalField()
        )
    ).order_by('ratio')[:10]
       
    # Top clients (via site/département)
    top_clients = demandes.values('poste__site__nom').annotate(
        volume=Count('id'),
        ca=Count('id') * 1500  # Estimation
    ).order_by('-volume')[:10]
    
    # Taux de fidélisation client (clients récurrents)
    clients_uniques = demandes.values('poste__site').distinct().count()
    clients_recurrents = demandes.values('poste__site').annotate(
        nb_demandes=Count('id')
    ).filter(nb_demandes__gt=1).count()
    
    taux_fidelisation = (clients_recurrents / clients_uniques * 100) if clients_uniques > 0 else 0
    
    # ===== GESTION DES CANDIDATS =====
    
    # Candidats actifs/disponibles
    candidats_actifs = ProfilUtilisateur.objects.filter(
        actif=True,
        statut_employe='ACTIF'
    ).count()
    
    candidats_disponibles = ProfilUtilisateur.objects.filter(
        actif=True,
        statut_employe='ACTIF',
        extended_data__disponible_interim=True
    ).count()
    
    # Taux de placement
    candidats_places = demandes.filter(
        candidat_selectionne__isnull=False
    ).values('candidat_selectionne').distinct().count()
    
    candidats_proposes = PropositionCandidat.objects.filter(
        demande_interim__in=demandes
    ).values('candidat_propose').distinct().count()
    
    taux_placement = (candidats_places / candidats_proposes * 100) if candidats_proposes > 0 else 0
    
    # Délai moyen de placement
    demandes_avec_selection = demandes.filter(
        candidat_selectionne__isnull=False,
        date_validation__isnull=False
    )
    
    if demandes_avec_selection.exists():
        delai_placement = demandes_avec_selection.aggregate(
            delai_moy=Avg(F('date_validation') - F('created_at'))
        )['delai_moy']
        delai_placement_jours = delai_placement.days if delai_placement else 0
    else:
        delai_placement_jours = 0
    
    # Candidats les plus demandés
    candidats_demandes = PropositionCandidat.objects.filter(
        demande_interim__in=demandes
    ).values(
        'candidat_propose__user__first_name',
        'candidat_propose__user__last_name',
        'candidat_propose__matricule'
    ).annotate(
        nb_propositions=Count('id')
    ).order_by('-nb_propositions')[:10]
    
    # ===== RATIOS DE PERFORMANCE CLÉS =====
    
    # Taux de conversion (demandes créées → sélections finales effectuées)
    demandes_creees = demandes.count()
    selections_finales = demandes.filter(
        candidat_selectionne__isnull=False,
        statut__in=['EN_COURS', 'TERMINEE']
    ).count()
    
    taux_conversion = (selections_finales / demandes_creees * 100) if demandes_creees > 0 else 0
    
    # Taux d'occupation (missions actives / candidats disponibles)
    missions_actives = demandes.filter(statut='EN_COURS').count()
    taux_occupation = (missions_actives / candidats_disponibles * 100) if candidats_disponibles > 0 else 0
    
    # Délai moyen entre demande et début de mission
    demandes_demarrees = demandes.filter(
        date_debut_effective__isnull=False
    )
    
    if demandes_demarrees.exists():
        delai_demande_debut = demandes_demarrees.aggregate(
            delai_moy=Avg(F('date_debut_effective') - F('created_at'))
        )['delai_moy']
        delai_demande_debut_jours = delai_demande_debut.days if delai_demande_debut else 0
    else:
        delai_demande_debut_jours = 0
    
    # ===== ANALYSE GÉOGRAPHIQUE =====
    
    # Répartition par zone géographique
    repartition_geo = demandes.values('poste__site__ville').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Performance par site
    performance_sites = demandes.values('poste__site__nom').annotate(
        count=Count('id'),
        ca=Count('id') * 1500,  # Estimation
        taux_reussite=Count('id', filter=Q(statut='TERMINEE')) * 100 / Count('id')
    ).order_by('-count')
    
    # ===== INDICATEURS QUALITÉ =====
    
    # Taux de renouvellement
    taux_renouvellement = (renouvellements / total_interims * 100) if total_interims > 0 else 0
    
    # Note satisfaction client moyenne (basée sur evaluation_mission)
    evaluations = demandes.filter(evaluation_mission__isnull=False)
    note_satisfaction = evaluations.aggregate(
        note_moy=Avg('evaluation_mission')
    )['note_moy'] or 0
    
    # Taux d'embauche définitive après interim
    # (Nécessiterait un champ spécifique ou un modèle de suivi)
    embauches_definitives = 0  # À adapter selon votre modèle
    taux_embauche_definitive = 0
    
    # Nombre de réclamations/litiges
    # Basé sur les demandes refusées ou annulées
    reclamations = demandes.filter(statut__in=['REFUSEE', 'ANNULEE']).count()
    
    # Statistiques sur les validations par niveau hiérarchique
    stats_validations = ValidationDemande.objects.filter(
        demande__in=demandes
    ).values('type_validation').annotate(
        count=Count('id'),
        delai_moyen=Avg(F('date_validation') - F('date_demande_validation'))
    ).order_by('type_validation')
    
    # Statistiques sur les propositions par type de profil
    stats_propositions = PropositionCandidat.objects.filter(
        demande_interim__in=demandes
    ).values('source_proposition').annotate(
        count=Count('id'),
        score_moyen=Avg('score_final')
    ).order_by('-count')
    
    # Préparation du contexte
    context = {
        'page_title': 'Statistiques Intérim',
        'date_debut': date_debut,
        'date_fin': date_fin,
        
        # Statistiques de volume
        'total_interims': total_interims,
        'interims_par_mois': list(interims_par_mois),
        'interims_par_semaine': list(interims_par_semaine),
        'duree_moyenne_jours': duree_moyenne_jours,
        'repartition_duree': repartition_duree,
        'renouvellements': renouvellements,
        
        # Analyse secteurs/métiers
        'top_postes': list(top_postes),
        'repartition_secteur': list(repartition_secteur),
        'postes_difficiles': list(postes_difficiles),
        
        # Performance commerciale
        'top_clients': list(top_clients),
        'taux_fidelisation': round(taux_fidelisation, 2),
        
        # Gestion candidats
        'candidats_actifs': candidats_actifs,
        'candidats_disponibles': candidats_disponibles,
        'taux_placement': round(taux_placement, 2),
        'delai_placement_jours': delai_placement_jours,
        'candidats_demandes': list(candidats_demandes),
        
        # Ratios de performance
        'taux_conversion': round(taux_conversion, 2),
        'taux_occupation': round(taux_occupation, 2),
        'delai_demande_debut_jours': delai_demande_debut_jours,
        
        # Analyse géographique
        'repartition_geo': list(repartition_geo),
        'performance_sites': list(performance_sites),
        
        # Indicateurs qualité
        'taux_renouvellement': round(taux_renouvellement, 2),
        'note_satisfaction': round(note_satisfaction, 2),
        'taux_embauche_definitive': round(taux_embauche_definitive, 2),
        'reclamations': reclamations,
        
        # Statistiques spécifiques au workflow
        'stats_validations': list(stats_validations),
        'stats_propositions': list(stats_propositions),
        
        # Données pour les graphiques (format JSON)
        'interims_mois_json': json.dumps(list(interims_par_mois), default=str),
        'repartition_secteur_json': json.dumps(list(repartition_secteur)),
        'stats_validations_json': json.dumps(list(stats_validations), default=str),
        'stats_propositions_json': json.dumps(list(stats_propositions), default=str),
        
        # Métriques calculées
        'periode_jours': (date_fin - date_debut).days,
        'demandes_par_jour': round(total_interims / max(1, (date_fin - date_debut).days), 2),
        'pourcentage_demandes_abouties': round(
            (selections_finales / max(1, total_interims)) * 100, 2
        ),
    }
    
    return render(request, 'interim_stats.html', context)

@login_required
def interim_agenda(request):
    """
    Vue principale pour l'agenda des demandes et missions d'intérim
    Affiche un calendrier avec les demandes planifiées et missions en cours
    """
    try:
        # Récupérer le profil utilisateur
        profil_utilisateur = get_object_or_404(ProfilUtilisateur, user=request.user)
        
        # Déterminer les permissions d'accès
        peut_voir_tout = (
            profil_utilisateur.is_superuser or 
            profil_utilisateur.type_profil in ['RH', 'ADMIN']
        )
        
        niveau_acces = _determiner_niveau_acces(profil_utilisateur)
        
        # Récupérer les paramètres de date depuis la requête
        aujourd_hui = date.today()
        
        # Paramètres de navigation du calendrier
        annee = int(request.GET.get('annee', aujourd_hui.year))
        mois = int(request.GET.get('mois', aujourd_hui.month))
        
        # Valider les paramètres
        if not (2020 <= annee <= 2030):
            annee = aujourd_hui.year
        if not (1 <= mois <= 12):
            mois = aujourd_hui.month
            
        # Date de référence pour le calendrier
        date_reference = date(annee, mois, 1)
        
        # Récupérer les filtres
        filtres = {
            'departement': request.GET.get('departement', ''),
            'site': request.GET.get('site', ''),
            'type_vue': request.GET.get('type_vue', 'tous'),  # 'demandes', 'missions', 'tous'
            'statut': request.GET.get('statut', ''),
            'urgence': request.GET.get('urgence', ''),
        }
        
        # Construire les queryset des demandes selon les permissions
        demandes_base = _construire_queryset_demandes(profil_utilisateur, peut_voir_tout, niveau_acces)
        
        # Appliquer les filtres
        demandes_filtrees = _appliquer_filtres_demandes(demandes_base, filtres)
        
        # Récupérer les demandes pour le mois en cours et les mois adjacents
        # (pour une meilleure vue du calendrier)
        debut_periode = date_reference.replace(day=1) - timedelta(days=7)
        fin_periode = (date_reference.replace(day=calendar.monthrange(annee, mois)[1]) + 
                      timedelta(days=7))
        
        # Demandes planifiées (avec dates de début/fin)
        demandes_planifiees = demandes_filtrees.filter(
            Q(date_debut__isnull=False) &
            (Q(date_debut__lte=fin_periode) | Q(date_fin__gte=debut_periode))
        ).select_related(
            'demandeur__user', 'personne_remplacee__user', 
            'poste__departement', 'poste__site', 'motif_absence',
            'candidat_selectionne__user'
        ).prefetch_related(
            'propositions_candidats__candidat_propose__user',
            'validations__validateur__user'
        )
        
        # Missions en cours (demandes avec candidat sélectionné)
        missions_en_cours = demandes_planifiees.filter(
            candidat_selectionne__isnull=False,
            statut__in=['EN_COURS', 'TERMINEE']
        )
        
        # Préparer les données du calendrier
        donnees_calendrier = _preparer_donnees_calendrier(
            annee, mois, demandes_planifiees, missions_en_cours, filtres['type_vue']
        )
        
        # Statistiques pour le mois
        statistiques_mois = _calculer_statistiques_mois(
            demandes_planifiees, missions_en_cours, date_reference
        )
        
        # Prochaines échéances importantes
        prochaines_echeances = _obtenir_prochaines_echeances(
            demandes_filtrees, profil_utilisateur, aujourd_hui
        )
        
        # Données pour les sélecteurs de filtres
        departements_accessibles = _obtenir_departements_accessibles(
            profil_utilisateur, peut_voir_tout
        )
        sites_accessibles = _obtenir_sites_accessibles(
            profil_utilisateur, peut_voir_tout
        )
        
        # Choix pour les formulaires
        statuts_choix = DemandeInterim.STATUTS
        urgences_choix = DemandeInterim.URGENCES
        
        # Navigation du calendrier
        navigation_calendrier = _calculer_navigation_calendrier(annee, mois)
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'peut_voir_tout': peut_voir_tout,
            'niveau_acces': niveau_acces,
            
            # ✅ CORRECTION : Données du calendrier complètes
            'donnees_calendrier': donnees_calendrier,
            'annee_actuelle': annee,
            'mois_actuel': mois,
            'nom_mois': calendar.month_name[mois],  # ✅ Ajouté
            'navigation_calendrier': navigation_calendrier,
            
            # ✅ CORRECTION : Statistiques avec structure complète
            'statistiques_mois': statistiques_mois,
            'prochaines_echeances': prochaines_echeances,
            
            # ✅ CORRECTION : Filtres complets avec valeurs par défaut
            'filtres': {
                'type_vue': filtres.get('type_vue', 'tous'),
                'departement': filtres.get('departement', ''),
                'site': filtres.get('site', ''),
                'statut': filtres.get('statut', ''),
                'urgence': filtres.get('urgence', ''),
                'date_debut': filtres.get('date_debut', ''),
                'date_fin': filtres.get('date_fin', ''),
                'recherche': filtres.get('recherche', ''),
                'ordre': filtres.get('ordre', '-created_at'),
            },
            'departements_accessibles': departements_accessibles,
            'sites_accessibles': sites_accessibles,
            'statuts_choix': statuts_choix,
            'urgences_choix': urgences_choix,
            
            # ✅ CORRECTION : Données pour le template avec valeurs sûres
            'aujourd_hui': aujourd_hui,
            'date_reference': date_reference,
            
            # ✅ AJOUT : Variables pour la compatibilité template
            'total_evenements': donnees_calendrier.get('nombre_total_evenements', 0),
            'semaines_calendrier': donnees_calendrier.get('semaines', []),
            'evenements_par_date': donnees_calendrier.get('evenements_par_date', {}),
        }
        
        return render(request, 'interim_agenda.html', context)
        
    except Exception as e:
        messages.error(
            request, 
            f"Erreur lors du chargement de l'agenda : {str(e)}"
        )
        return render(request, 'interim_agenda.html', {
            'profil_utilisateur': profil_utilisateur,
            'erreur': True,
            'message_erreur': str(e)
        })


def _determiner_niveau_acces(profil_utilisateur):
    """Détermine le niveau d'accès de l'utilisateur"""
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    elif profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return 'GLOBAL'
    elif profil_utilisateur.type_profil == 'DIRECTEUR':
        return 'DIRECTEUR'
    elif profil_utilisateur.type_profil == 'RESPONSABLE':
        return 'RESPONSABLE'
    elif profil_utilisateur.type_profil == 'CHEF_EQUIPE':
        return 'CHEF_EQUIPE'
    else:
        return 'UTILISATEUR'


def _construire_queryset_demandes(profil_utilisateur, peut_voir_tout, niveau_acces):
    """Construit le queryset de base selon les permissions"""
    if peut_voir_tout:
        return DemandeInterim.objects.all()
    
    # Construire les filtres selon le niveau d'accès
    filtres_acces = Q()
    
    if niveau_acces == 'DIRECTEUR':
        # Voir tout son département et les départements sous sa responsabilité
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    elif niveau_acces == 'RESPONSABLE':
        # Voir son département
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    elif niveau_acces == 'CHEF_EQUIPE':
        # Voir son département + ses équipes
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    else:  # UTILISATEUR
        # Voir uniquement ses propres demandes
        filtres_acces = Q(demandeur=profil_utilisateur) | Q(personne_remplacee=profil_utilisateur)
    
    return DemandeInterim.objects.filter(filtres_acces)


def _appliquer_filtres_demandes(queryset, filtres):
    """Applique les filtres sur le queryset"""
    if filtres['departement']:
        try:
            dept_id = int(filtres['departement'])
            queryset = queryset.filter(poste__departement_id=dept_id)
        except (ValueError, TypeError):
            pass
    
    if filtres['site']:
        try:
            site_id = int(filtres['site'])
            queryset = queryset.filter(poste__site_id=site_id)
        except (ValueError, TypeError):
            pass
    
    if filtres['statut']:
        queryset = queryset.filter(statut=filtres['statut'])
    
    if filtres['urgence']:
        queryset = queryset.filter(urgence=filtres['urgence'])
    
    return queryset


def _preparer_donnees_calendrier(annee, mois, demandes_planifiees, missions_en_cours, type_vue):
    """Prépare les données pour l'affichage du calendrier"""
    
    # Créer la structure du calendrier
    cal = calendar.Calendar(firstweekday=0)  # Lundi = 0
    semaines = cal.monthdayscalendar(annee, mois)
    
    # Dictionnaire pour stocker les événements par date
    evenements_par_date = {}
    
    # Ajouter les demandes selon le type de vue
    if type_vue in ['demandes', 'tous']:
        for demande in demandes_planifiees:
            # Ajouter les événements de début et fin
            if demande.date_debut:
                date_str = demande.date_debut.strftime('%Y-%m-%d')
                if date_str not in evenements_par_date:
                    evenements_par_date[date_str] = {
                        'demandes_debut': [], 
                        'demandes_fin': [], 
                        'missions_en_cours': []
                    }
                
                evenements_par_date[date_str]['demandes_debut'].append({
                    'demande': demande,
                    'type': 'debut_absence',
                    'titre': f"Début: {demande.personne_remplacee.nom_complet}",
                    'description': f"{demande.motif_absence.nom} - {demande.poste.titre}",
                    'urgence': demande.urgence,
                    'statut': demande.statut
                })
            
            if demande.date_fin:
                date_str = demande.date_fin.strftime('%Y-%m-%d')
                if date_str not in evenements_par_date:
                    evenements_par_date[date_str] = {
                        'demandes_debut': [], 
                        'demandes_fin': [], 
                        'missions_en_cours': []
                    }
                
                evenements_par_date[date_str]['demandes_fin'].append({
                    'demande': demande,
                    'type': 'fin_absence',
                    'titre': f"Fin: {demande.personne_remplacee.nom_complet}",
                    'description': f"{demande.motif_absence.nom} - {demande.poste.titre}",
                    'urgence': demande.urgence,
                    'statut': demande.statut
                })
    
    # Ajouter les missions en cours
    if type_vue in ['missions', 'tous']:
        for mission in missions_en_cours:
            if mission.candidat_selectionne and mission.date_debut and mission.date_fin:
                # Ajouter la mission pour chaque jour de la période
                date_courante = mission.date_debut
                while date_courante <= mission.date_fin:
                    if date_courante.month == mois and date_courante.year == annee:
                        date_str = date_courante.strftime('%Y-%m-%d')
                        if date_str not in evenements_par_date:
                            evenements_par_date[date_str] = {
                                'demandes_debut': [], 
                                'demandes_fin': [], 
                                'missions_en_cours': []
                            }
                        
                        # Éviter les doublons
                        mission_existe = any(
                            m['demande'].id == mission.id 
                            for m in evenements_par_date[date_str]['missions_en_cours']
                        )
                        
                        if not mission_existe:
                            evenements_par_date[date_str]['missions_en_cours'].append({
                                'demande': mission,
                                'type': 'mission_en_cours',
                                'titre': f"Mission: {mission.candidat_selectionne.nom_complet}",
                                'description': f"Remplace {mission.personne_remplacee.nom_complet} - {mission.poste.titre}",
                                'urgence': mission.urgence,
                                'statut': mission.statut,
                                'candidat': mission.candidat_selectionne
                            })
                    
                    date_courante += timedelta(days=1)
    
    # Structurer les données pour le template
    donnees_calendrier = {
        'semaines': [],
        'evenements_par_date': evenements_par_date,
        'nombre_total_evenements': sum(
            len(ev['demandes_debut']) + len(ev['demandes_fin']) + len(ev['missions_en_cours'])
            for ev in evenements_par_date.values()
        )
    }
    
    # Construire les semaines avec les événements
    for semaine in semaines:
        jours_semaine = []
        for jour in semaine:
            if jour == 0:  # Jour vide (autre mois)
                jours_semaine.append({
                    'numero': 0,
                    'date': None,
                    'est_autre_mois': True,
                    'est_aujourd_hui': False,
                    'evenements': [],
                    'nombre_evenements': 0
                })
            else:
                date_jour = date(annee, mois, jour)
                date_str = date_jour.strftime('%Y-%m-%d')
                evenements_jour = evenements_par_date.get(date_str, {
                    'demandes_debut': [], 
                    'demandes_fin': [], 
                    'missions_en_cours': []
                })
                
                nombre_evenements = (
                    len(evenements_jour['demandes_debut']) +
                    len(evenements_jour['demandes_fin']) +
                    len(evenements_jour['missions_en_cours'])
                )
                
                jours_semaine.append({
                    'numero': jour,
                    'date': date_jour,
                    'est_autre_mois': False,
                    'est_aujourd_hui': date_jour == date.today(),
                    'evenements': evenements_jour,
                    'nombre_evenements': nombre_evenements
                })
        
        donnees_calendrier['semaines'].append(jours_semaine)
    
    return donnees_calendrier


def _calculer_statistiques_mois(demandes_planifiees, missions_en_cours, date_reference):
    """Calcule les statistiques pour le mois en cours"""
    
    # Filtrer les demandes du mois
    debut_mois = date_reference.replace(day=1)
    fin_mois = date_reference.replace(day=calendar.monthrange(date_reference.year, date_reference.month)[1])
    
    demandes_mois = demandes_planifiees.filter(
        Q(date_debut__range=[debut_mois, fin_mois]) |
        Q(date_fin__range=[debut_mois, fin_mois])
    )
    
    missions_mois = missions_en_cours.filter(
        Q(date_debut__range=[debut_mois, fin_mois]) |
        Q(date_fin__range=[debut_mois, fin_mois])
    )
    
    # Calculs des statistiques
    stats = {
        'total_demandes': demandes_mois.count(),
        'total_missions': missions_mois.count(),
        'demandes_urgentes': demandes_mois.filter(urgence__in=['ELEVEE', 'CRITIQUE']).count(),
        'missions_actives': missions_mois.filter(statut='EN_COURS').count(),
        'missions_terminees': missions_mois.filter(statut='TERMINEE').count(),
        
        # Répartition par statut
        'repartition_statuts': {},
        
        # Répartition par urgence
        'repartition_urgences': {},
        
        # Départements les plus demandés
        'departements_actifs': [],
        
        # Taux de completion
        'taux_completion': 0
    }
    
    # Répartition par statuts
    for statut, libelle in DemandeInterim.STATUTS:
        count = demandes_mois.filter(statut=statut).count()
        if count > 0:
            stats['repartition_statuts'][libelle] = count
    
    # Répartition par urgences
    for urgence, libelle in DemandeInterim.URGENCES:
        count = demandes_mois.filter(urgence=urgence).count()
        if count > 0:
            stats['repartition_urgences'][libelle] = count
    
    # Départements les plus actifs
    departements_stats = demandes_mois.values(
        'poste__departement__nom'
    ).annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    stats['departements_actifs'] = [
        {'nom': dept['poste__departement__nom'], 'count': dept['count']}
        for dept in departements_stats
        if dept['poste__departement__nom']
    ]
    
    # Taux de completion
    if stats['total_demandes'] > 0:
        demandes_terminees = demandes_mois.filter(statut__in=['TERMINEE', 'EN_COURS']).count()
        stats['taux_completion'] = round((demandes_terminees / stats['total_demandes']) * 100, 1)
    
    return stats


def _obtenir_prochaines_echeances(demandes_filtrees, profil_utilisateur, aujourd_hui):
    """Obtient les prochaines échéances importantes"""
    
    # Échéances dans les 30 prochains jours
    date_limite = aujourd_hui + timedelta(days=30)
    
    echeances = []
    
    # Demandes qui démarrent bientôt
    demandes_prochaines = demandes_filtrees.filter(
        date_debut__range=[aujourd_hui, date_limite],
        statut__in=['VALIDEE', 'EN_RECHERCHE', 'CANDIDAT_PROPOSE']
    ).select_related(
        'personne_remplacee__user', 'poste__departement', 'motif_absence'
    ).order_by('date_debut')[:5]
    
    for demande in demandes_prochaines:
        jours_restants = (demande.date_debut - aujourd_hui).days
        echeances.append({
            'type': 'debut_mission',
            'date': demande.date_debut,
            'jours_restants': jours_restants,
            'titre': f"Début mission - {demande.personne_remplacee.nom_complet}",
            'description': f"{demande.motif_absence.nom} - {demande.poste.titre}",
            'urgence': demande.urgence,
            'demande': demande
        })
    
    # Missions qui se terminent bientôt
    missions_fin_prochaine = demandes_filtrees.filter(
        date_fin__range=[aujourd_hui, date_limite],
        statut='EN_COURS',
        candidat_selectionne__isnull=False
    ).select_related(
        'candidat_selectionne__user', 'personne_remplacee__user', 'poste__departement'
    ).order_by('date_fin')[:5]
    
    for mission in missions_fin_prochaine:
        jours_restants = (mission.date_fin - aujourd_hui).days
        echeances.append({
            'type': 'fin_mission',
            'date': mission.date_fin,
            'jours_restants': jours_restants,
            'titre': f"Fin mission - {mission.candidat_selectionne.nom_complet}",
            'description': f"Retour de {mission.personne_remplacee.nom_complet}",
            'urgence': mission.urgence,
            'demande': mission
        })
    
    # Demandes en attente de validation (si l'utilisateur peut valider)
    if profil_utilisateur.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'] or profil_utilisateur.is_superuser:
        demandes_validation = demandes_filtrees.filter(
            statut__in=['SOUMISE', 'EN_VALIDATION'],
            date_debut__gte=aujourd_hui
        ).select_related(
            'demandeur__user', 'personne_remplacee__user', 'poste__departement'
        ).order_by('created_at')[:3]
        
        for demande in demandes_validation:
            jours_depuis_creation = (aujourd_hui - demande.created_at.date()).days
            echeances.append({
                'type': 'validation_requise',
                'date': demande.created_at.date(),
                'jours_restants': -jours_depuis_creation,  # Négatif car c'est en retard
                'titre': f"Validation requise - {demande.personne_remplacee.nom_complet}",
                'description': f"Demandée par {demande.demandeur.nom_complet}",
                'urgence': demande.urgence,
                'demande': demande
            })
    
    # Trier les échéances par priorité et date
    echeances.sort(key=lambda x: (x['jours_restants'], x['urgence'] == 'CRITIQUE'))
    
    return echeances[:10]  # Limiter à 10 échéances


def _obtenir_departements_accessibles(profil_utilisateur, peut_voir_tout):
    """Obtient la liste des départements accessibles à l'utilisateur"""
    if peut_voir_tout:
        return Departement.objects.filter(actif=True).order_by('nom')
    elif profil_utilisateur.departement:
        return Departement.objects.filter(
            id=profil_utilisateur.departement.id
        )
    else:
        return Departement.objects.none()


def _obtenir_sites_accessibles(profil_utilisateur, peut_voir_tout):
    """Obtient la liste des sites accessibles à l'utilisateur"""
    if peut_voir_tout:
        return Site.objects.filter(actif=True).order_by('nom')
    elif profil_utilisateur.site:
        return Site.objects.filter(
            id=profil_utilisateur.site.id
        )
    else:
        return Site.objects.none()


def _calculer_navigation_calendrier(annee, mois):
    """Calcule les données de navigation du calendrier"""
    import calendar as cal
    
    # Mois précédent
    if mois == 1:
        mois_precedent = 12
        annee_precedente = annee - 1
    else:
        mois_precedent = mois - 1
        annee_precedente = annee
    
    # Mois suivant
    if mois == 12:
        mois_suivant = 1
        annee_suivante = annee + 1
    else:
        mois_suivant = mois + 1
        annee_suivante = annee
    
    return {
        'precedent': {
            'annee': annee_precedente,
            'mois': mois_precedent,
            'nom': cal.month_name[mois_precedent] if mois_precedent <= 12 else 'Mois inconnu'
        },
        'suivant': {
            'annee': annee_suivante,
            'mois': mois_suivant,
            'nom': cal.month_name[mois_suivant] if mois_suivant <= 12 else 'Mois inconnu'
        },
        'aujourd_hui': {
            'annee': date.today().year,
            'mois': date.today().month
        }
    }


@login_required
def agenda_evenement_details(request, demande_id):
    """
    Vue AJAX pour obtenir les détails d'un événement du calendrier
    """
    try:
        profil_utilisateur = get_object_or_404(ProfilUtilisateur, user=request.user)
        
        # Récupérer la demande avec les permissions
        peut_voir_tout = (
            profil_utilisateur.is_superuser or 
            profil_utilisateur.type_profil in ['RH', 'ADMIN']
        )
        
        niveau_acces = _determiner_niveau_acces(profil_utilisateur)
        demandes_base = _construire_queryset_demandes(profil_utilisateur, peut_voir_tout, niveau_acces)
        
        demande = get_object_or_404(
            demandes_base.select_related(
                'demandeur__user', 'personne_remplacee__user',
                'poste__departement', 'poste__site', 'motif_absence',
                'candidat_selectionne__user'
            ).prefetch_related(
                'propositions_candidats__candidat_propose__user',
                'validations__validateur__user'
            ),
            id=demande_id
        )
        
        # Préparer les données de réponse
        data = {
            'numero_demande': demande.numero_demande,
            'statut': demande.get_statut_display(),
            'urgence': demande.get_urgence_display(),
            'demandeur': demande.demandeur.nom_complet,
            'personne_remplacee': demande.personne_remplacee.nom_complet,
            'motif_absence': demande.motif_absence.nom,
            'poste': demande.poste.titre,
            'departement': demande.poste.departement.nom,
            'site': demande.poste.site.nom,
            'date_debut': demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else None,
            'date_fin': demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else None,
            'duree_jours': demande.duree_mission,
            'candidat_selectionne': demande.candidat_selectionne.nom_complet if demande.candidat_selectionne else None,
            'description_poste': demande.description_poste,
            'instructions_particulieres': demande.instructions_particulieres,
            'date_creation': demande.created_at.strftime('%d/%m/%Y %H:%M'),
            
            # Propositions
            'nb_propositions': demande.propositions_candidats.count(),
            'propositions': [
                {
                    'candidat': prop.candidat_propose.nom_complet,
                    'proposant': prop.proposant.nom_complet,
                    'score': prop.score_final,
                    'date': prop.created_at.strftime('%d/%m/%Y %H:%M')
                }
                for prop in demande.propositions_candidats.all()[:5]
            ],
            
            # Validations
            'nb_validations': demande.validations.count(),
            'validations': [
                {
                    'type': val.get_type_validation_display(),
                    'validateur': val.validateur.nom_complet,
                    'decision': val.get_decision_display(),
                    'date': val.date_validation.strftime('%d/%m/%Y %H:%M') if val.date_validation else 'En attente'
                }
                for val in demande.validations.all()
            ]
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({
            'error': True,
            'message': f"Erreur lors de la récupération des détails : {str(e)}"
        }, status=500)
    
@login_required
def interim_agenda_event(request, demande_id):
    """
    Vue AJAX pour obtenir les détails complets d'un événement de l'agenda
    Retourne toutes les informations nécessaires pour le modal de détails
    """
    try:
        # Récupérer le profil utilisateur
        profil_utilisateur = get_object_or_404(ProfilUtilisateur, user=request.user)
        
        # Déterminer les permissions d'accès
        peut_voir_tout = (
            profil_utilisateur.is_superuser or 
            profil_utilisateur.type_profil in ['RH', 'ADMIN']
        )
        
        niveau_acces = _determiner_niveau_acces_agenda(profil_utilisateur)
        
        # Construire le queryset selon les permissions
        demandes_base = _construire_queryset_demandes_agenda(
            profil_utilisateur, peut_voir_tout, niveau_acces
        )
        
        # Récupérer la demande avec toutes les relations nécessaires
        demande = get_object_or_404(
            demandes_base.select_related(
                'demandeur__user', 'personne_remplacee__user',
                'poste__departement', 'poste__site', 'motif_absence',
                'candidat_selectionne__user', 'candidat_selectionne__departement',
                'candidat_selectionne__poste', 'candidat_selectionne__site'
            ).prefetch_related(
                'propositions_candidats__candidat_propose__user',
                'propositions_candidats__candidat_propose__departement',
                'propositions_candidats__proposant__user',
                'validations__validateur__user',
                'historique_actions__utilisateur__user',
                'reponses_candidats__candidat__user',
                'notifications__destinataire__user',
                'scores_candidats__candidat__user'
            ),
            id=demande_id
        )
        
        # Construire la réponse JSON avec tous les détails
        response_data = {
            # ========================================
            # INFORMATIONS GÉNÉRALES DE LA DEMANDE
            # ========================================
            'demande': {
                'id': demande.id,
                'numero_demande': demande.numero_demande,
                'statut': demande.get_statut_display(),
                'statut_code': demande.statut,
                'urgence': demande.get_urgence_display(),
                'urgence_code': demande.urgence,
                'est_urgente': demande.urgence in ['ELEVEE', 'CRITIQUE'],
                'date_creation': demande.created_at.strftime('%d/%m/%Y %H:%M'),
                'date_modification': demande.updated_at.strftime('%d/%m/%Y %H:%M'),
            },
            
            # ========================================
            # PERSONNES IMPLIQUÉES
            # ========================================
            'personnes': {
                'demandeur': {
                    'nom_complet': demande.demandeur.nom_complet,
                    'matricule': demande.demandeur.matricule,
                    'departement': demande.demandeur.departement.nom if demande.demandeur.departement else 'Non défini',
                    'poste': demande.demandeur.poste.titre if demande.demandeur.poste else 'Non défini',
                    'type_profil': demande.demandeur.get_type_profil_display(),
                },
                'personne_remplacee': {
                    'nom_complet': demande.personne_remplacee.nom_complet,
                    'matricule': demande.personne_remplacee.matricule,
                    'departement': demande.personne_remplacee.departement.nom if demande.personne_remplacee.departement else 'Non défini',
                    'poste': demande.personne_remplacee.poste.titre if demande.personne_remplacee.poste else 'Non défini',
                    'site': demande.personne_remplacee.site.nom if demande.personne_remplacee.site else 'Non défini',
                },
                'candidat_selectionne': None
            },
            
            # ========================================
            # POSTE ET LOCALISATION
            # ========================================
            'poste': {
                'titre': demande.poste.titre,
                'description': demande.description_poste,
                'departement': {
                    'nom': demande.poste.departement.nom,
                    'code': demande.poste.departement.code,
                },
                'site': {
                    'nom': demande.poste.site.nom,
                    'ville': demande.poste.site.ville,
                    'adresse_complete': demande.poste.site.adresse_complete,
                },
                'niveau_responsabilite': demande.poste.get_niveau_responsabilite_display(),
                'interim_autorise': demande.poste.interim_autorise,
                'competences_requises': demande.competences_indispensables,
                'instructions_particulieres': demande.instructions_particulieres,
            },
            
            # ========================================
            # ABSENCE ET PLANNING
            # ========================================
            'absence': {
                'motif': {
                    'nom': demande.motif_absence.nom,
                    'description': demande.motif_absence.description,
                    'categorie': demande.motif_absence.get_categorie_display(),
                    'couleur': demande.motif_absence.couleur,
                    'necessite_justificatif': demande.motif_absence.necessite_justificatif,
                },
                'periode': {
                    'date_debut': demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else None,
                    'date_fin': demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else None,
                    'duree_jours': demande.duree_mission,
                    'date_debut_effective': demande.date_debut_effective.strftime('%d/%m/%Y') if demande.date_debut_effective else None,
                    'date_fin_effective': demande.date_fin_effective.strftime('%d/%m/%Y') if demande.date_fin_effective else None,
                },
            },
            
            # ========================================
            # WORKFLOW ET VALIDATION
            # ========================================
            'workflow': _obtenir_details_workflow(demande),
            
            # ========================================
            # CANDIDAT SÉLECTIONNÉ (si applicable)
            # ========================================
            'candidat_selectionne': None,
            
            # ========================================
            # PROPOSITIONS DE CANDIDATS
            # ========================================
            'propositions': _obtenir_details_propositions(demande),
            
            # ========================================
            # VALIDATIONS EFFECTUÉES
            # ========================================
            'validations': _obtenir_details_validations(demande),
            
            # ========================================
            # HISTORIQUE DES ACTIONS
            # ========================================
            'historique': _obtenir_historique_actions(demande),
            
            # ========================================
            # RÉPONSES DES CANDIDATS
            # ========================================
            'reponses_candidats': _obtenir_reponses_candidats(demande),
            
            # ========================================
            # NOTIFICATIONS LIÉES
            # ========================================
            'notifications': _obtenir_notifications_liees(demande),
            
            # ========================================
            # STATISTIQUES ET MÉTRIQUES
            # ========================================
            'statistiques': _calculer_statistiques_demande(demande),
            
            # ========================================
            # ACTIONS DISPONIBLES POUR L'UTILISATEUR
            # ========================================
            'actions_disponibles': _determiner_actions_disponibles(demande, profil_utilisateur),
            
            # ========================================
            # MÉTADONNÉES
            # ========================================
            'metadata': {
                'peut_voir_details_complets': peut_voir_tout or _peut_voir_details_complets(demande, profil_utilisateur),
                'niveau_acces_utilisateur': niveau_acces,
                'type_profil_utilisateur': profil_utilisateur.get_type_profil_display(),
                'date_generation': timezone.now().strftime('%d/%m/%Y %H:%M:%S'),
            }
        }
        
        # Ajouter les détails du candidat sélectionné si applicable
        if demande.candidat_selectionne:
            response_data['candidat_selectionne'] = _obtenir_details_candidat_selectionne(demande)
            response_data['personnes']['candidat_selectionne'] = {
                'nom_complet': demande.candidat_selectionne.nom_complet,
                'matricule': demande.candidat_selectionne.matricule,
                'departement': demande.candidat_selectionne.departement.nom if demande.candidat_selectionne.departement else 'Non défini',
                'poste': demande.candidat_selectionne.poste.titre if demande.candidat_selectionne.poste else 'Non défini',
                'site': demande.candidat_selectionne.site.nom if demande.candidat_selectionne.site else 'Non défini',
                'type_profil': demande.candidat_selectionne.get_type_profil_display(),
            }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({
            'error': True,
            'message': f"Erreur lors de la récupération des détails : {str(e)}",
            'details': str(e) if request.user.is_superuser else None
        }, status=500)


def _determiner_niveau_acces_agenda(profil_utilisateur):
    """Détermine le niveau d'accès de l'utilisateur pour l'agenda"""
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    elif profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return 'GLOBAL'
    elif profil_utilisateur.type_profil == 'DIRECTEUR':
        return 'DIRECTEUR'
    elif profil_utilisateur.type_profil == 'RESPONSABLE':
        return 'RESPONSABLE'
    elif profil_utilisateur.type_profil == 'CHEF_EQUIPE':
        return 'CHEF_EQUIPE'
    else:
        return 'UTILISATEUR'


def _construire_queryset_demandes_agenda(profil_utilisateur, peut_voir_tout, niveau_acces):
    """Construit le queryset de base selon les permissions"""
    if peut_voir_tout:
        return DemandeInterim.objects.all()
    
    # Construire les filtres selon le niveau d'accès
    filtres_acces = Q()
    
    if niveau_acces == 'DIRECTEUR':
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    elif niveau_acces == 'RESPONSABLE':
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    elif niveau_acces == 'CHEF_EQUIPE':
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    else:  # UTILISATEUR
        filtres_acces = Q(demandeur=profil_utilisateur) | Q(personne_remplacee=profil_utilisateur)
    
    return DemandeInterim.objects.filter(filtres_acces)


def _obtenir_details_workflow(demande):
    """Obtient les détails du workflow de validation"""
    workflow_data = {
        'niveau_actuel': demande.niveau_validation_actuel,
        'niveaux_requis': demande.niveaux_validation_requis,
        'progression_pourcentage': 0,
        'etape_actuelle': '',
        'prochaine_etape': '',
        'peut_etre_valide': False,
        'en_retard': False,
        'delai_depuis_creation': (timezone.now().date() - demande.created_at.date()).days,
    }
    
    # Calculer la progression
    if demande.niveaux_validation_requis > 0:
        workflow_data['progression_pourcentage'] = round(
            (demande.niveau_validation_actuel / demande.niveaux_validation_requis) * 100, 1
        )
    
    # Déterminer l'étape actuelle et suivante
    etapes_mapping = {
        0: 'Demande soumise',
        1: 'En attente validation Responsable (N+1)',
        2: 'En attente validation Directeur (N+2)',  
        3: 'En attente validation RH/Admin (Final)',
    }
    
    workflow_data['etape_actuelle'] = etapes_mapping.get(
        demande.niveau_validation_actuel, 
        'Étape inconnue'
    )
    
    if demande.niveau_validation_actuel < demande.niveaux_validation_requis:
        workflow_data['prochaine_etape'] = etapes_mapping.get(
            demande.niveau_validation_actuel + 1, 
            'Finalisation'
        )
        workflow_data['peut_etre_valide'] = True
    else:
        workflow_data['prochaine_etape'] = 'Workflow terminé'
    
    # Vérifier si en retard (plus de 5 jours pour validation)
    if demande.statut in ['SOUMISE', 'EN_VALIDATION'] and workflow_data['delai_depuis_creation'] > 5:
        workflow_data['en_retard'] = True
    
    return workflow_data


def _obtenir_details_candidat_selectionne(demande):
    """Obtient les détails complets du candidat sélectionné"""
    candidat = demande.candidat_selectionne
    
    candidat_data = {
        'informations_generales': {
            'nom_complet': candidat.nom_complet,
            'matricule': candidat.matricule,
            'type_profil': candidat.get_type_profil_display(),
            'statut_employe': candidat.get_statut_employe_display(),
            'date_embauche': candidat.date_embauche.strftime('%d/%m/%Y') if candidat.date_embauche else None,
        },
        'poste_actuel': {
            'titre': candidat.poste.titre if candidat.poste else 'Non défini',
            'departement': candidat.departement.nom if candidat.departement else 'Non défini',
            'site': candidat.site.nom if candidat.site else 'Non défini',
        },
        'selection': {
            'date_selection': None,
            'score_obtenu': None,
            'justification_selection': '',
            'proposant_origine': None,
        },
        'mission': {
            'statut_mission': demande.statut,
            'date_debut_prevue': demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else None,
            'date_fin_prevue': demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else None,
            'duree_jours': demande.duree_mission,
            'evaluation_finale': demande.evaluation_mission,
            'commentaire_final': demande.commentaire_final,
        }
    }
    
    # Chercher la proposition qui a mené à la sélection
    proposition_gagnante = demande.propositions_candidats.filter(
        candidat_propose=candidat
    ).first()
    
    if proposition_gagnante:
        candidat_data['selection'].update({
            'score_obtenu': proposition_gagnante.score_final,
            'justification_selection': proposition_gagnante.justification,
            'proposant_origine': {
                'nom': proposition_gagnante.proposant.nom_complet,
                'type_profil': proposition_gagnante.proposant.get_type_profil_display(),
                'source': proposition_gagnante.get_source_proposition_display(),
            }
        })
    
    # Chercher les détails de score si disponibles
    score_detail = demande.scores_candidats.filter(candidat=candidat).first()
    if score_detail:
        candidat_data['scores_detailles'] = {
            'score_total': score_detail.score_total,
            'score_competences': score_detail.score_competences,
            'score_experience': score_detail.score_experience,
            'score_disponibilite': score_detail.score_disponibilite,
            'score_proximite': score_detail.score_proximite,
            'bonus_total': (
                score_detail.bonus_proposition_humaine +
                score_detail.bonus_experience_similaire +
                score_detail.bonus_recommandation +
                score_detail.bonus_hierarchique
            ),
            'penalites': score_detail.penalite_indisponibilite,
        }
    
    # Chercher la réponse du candidat
    reponse_candidat = demande.reponses_candidats.filter(candidat=candidat).first()
    if reponse_candidat:
        candidat_data['reponse'] = {
            'statut': reponse_candidat.get_reponse_display(),
            'date_reponse': reponse_candidat.date_reponse.strftime('%d/%m/%Y %H:%M') if reponse_candidat.date_reponse else None,
            'motif_refus': reponse_candidat.get_motif_refus_display() if reponse_candidat.motif_refus else None,
            'commentaire': reponse_candidat.commentaire_refus,
        }
    
    return candidat_data


def _obtenir_details_propositions(demande):
    """Obtient les détails de toutes les propositions"""
    propositions = demande.propositions_candidats.select_related(
        'candidat_propose__user', 'candidat_propose__departement',
        'proposant__user'
    ).order_by('-score_final', '-created_at')
    
    propositions_data = {
        'total': propositions.count(),
        'par_source': {},
        'par_statut': {},
        'score_moyen': 0,
        'liste': []
    }
    
    # Calculer les statistiques
    if propositions.exists():
        propositions_data['score_moyen'] = round(
            propositions.aggregate(Avg('score_final'))['score_final__avg'] or 0, 1
        )
        
        # Répartition par source
        for source, libelle in PropositionCandidat.SOURCES_PROPOSITION:
            count = propositions.filter(source_proposition=source).count()
            if count > 0:
                propositions_data['par_source'][libelle] = count
        
        # Répartition par statut
        for statut, libelle in PropositionCandidat.STATUTS_PROPOSITION:
            count = propositions.filter(statut=statut).count()
            if count > 0:
                propositions_data['par_statut'][libelle] = count
    
    # Détails de chaque proposition
    for proposition in propositions[:10]:  # Limiter à 10 pour les performances
        prop_data = {
            'id': proposition.id,
            'numero': proposition.numero_proposition,
            'candidat': {
                'nom_complet': proposition.candidat_propose.nom_complet,
                'matricule': proposition.candidat_propose.matricule,
                'departement': proposition.candidat_propose.departement.nom if proposition.candidat_propose.departement else 'Non défini',
                'poste': proposition.candidat_propose.poste.titre if proposition.candidat_propose.poste else 'Non défini',
            },
            'proposant': {
                'nom_complet': proposition.proposant.nom_complet,
                'type_profil': proposition.proposant.get_type_profil_display(),
                'source': proposition.get_source_proposition_display(),
            },
            'scores': {
                'automatique': proposition.score_automatique,
                'humain_ajuste': proposition.score_humain_ajuste,
                'bonus': proposition.bonus_proposition_humaine,
                'final': proposition.score_final,
            },
            'statut': proposition.get_statut_display(),
            'justification': proposition.justification,
            'competences_specifiques': proposition.competences_specifiques,
            'experience_pertinente': proposition.experience_pertinente,
            'date_proposition': proposition.created_at.strftime('%d/%m/%Y %H:%M'),
            'evaluateur': proposition.evaluateur.nom_complet if proposition.evaluateur else None,
            'commentaire_evaluation': proposition.commentaire_evaluation,
            'est_selectionne': proposition.candidat_propose == demande.candidat_selectionne,
        }
        
        propositions_data['liste'].append(prop_data)
    
    return propositions_data


def _obtenir_details_validations(demande):
    """Obtient les détails de toutes les validations"""
    validations = demande.validations.select_related(
        'validateur__user'
    ).order_by('niveau_validation', '-date_demande_validation')
    
    validations_data = {
        'total': validations.count(),
        'en_attente': validations.filter(date_validation__isnull=True).count(),
        'approuvees': validations.filter(decision='APPROUVE').count(),
        'refusees': validations.filter(decision='REFUSE').count(),
        'liste': []
    }
    
    for validation in validations:
        val_data = {
            'id': validation.id,
            'type': validation.get_type_validation_display(),
            'niveau': validation.niveau_validation,
            'validateur': {
                'nom_complet': validation.validateur.nom_complet,
                'type_profil': validation.validateur.get_type_profil_display(),
                'matricule': validation.validateur.matricule,
            },
            'decision': validation.get_decision_display(),
            'decision_code': validation.decision,
            'commentaire': validation.commentaire,
            'date_demande': validation.date_demande_validation.strftime('%d/%m/%Y %H:%M'),
            'date_validation': validation.date_validation.strftime('%d/%m/%Y %H:%M') if validation.date_validation else None,
            'en_attente': validation.date_validation is None,
            'delai_traitement': None,
            'candidats_retenus': validation.candidats_retenus,
            'candidats_rejetes': validation.candidats_rejetes,
            'nouveau_candidat': validation.nouveau_candidat_propose.nom_complet if validation.nouveau_candidat_propose else None,
            'justification_nouveau_candidat': validation.justification_nouveau_candidat,
        }
        
        # Calculer le délai de traitement
        if validation.date_validation:
            delai = validation.date_validation - validation.date_demande_validation
            val_data['delai_traitement'] = {
                'jours': delai.days,
                'heures': delai.seconds // 3600,
                'total_heures': round(delai.total_seconds() / 3600, 1)
            }
        
        validations_data['liste'].append(val_data)
    
    return validations_data


def _obtenir_historique_actions(demande):
    """Obtient l'historique détaillé des actions"""
    actions = demande.historique_actions.select_related(
        'utilisateur__user'
    ).order_by('-created_at')[:20]  # Dernières 20 actions
    
    historique_data = {
        'total': demande.historique_actions.count(),
        'affichees': min(20, demande.historique_actions.count()),
        'liste': []
    }
    
    for action in actions:
        action_data = {
            'id': action.id,
            'action': action.get_action_display(),
            'action_code': action.action,
            'utilisateur': action.utilisateur.nom_complet if action.utilisateur else 'Système',
            'utilisateur_type': action.utilisateur.get_type_profil_display() if action.utilisateur else 'SYSTEME',
            'description': action.description,
            'date': action.created_at.strftime('%d/%m/%Y %H:%M'),
            'niveau_validation': action.niveau_validation,
            'niveau_hierarchique': action.niveau_hierarchique,
            'is_superuser': action.is_superuser,
            'adresse_ip': action.adresse_ip,
            'donnees_avant': action.donnees_avant,
            'donnees_apres': action.donnees_apres,
        }
        
        historique_data['liste'].append(action_data)
    
    return historique_data


def _obtenir_reponses_candidats(demande):
    """Obtient les réponses des candidats contactés"""
    reponses = demande.reponses_candidats.select_related(
        'candidat__user'
    ).order_by('-date_proposition')
    
    reponses_data = {
        'total': reponses.count(),
        'acceptees': reponses.filter(reponse='ACCEPTE').count(),
        'refusees': reponses.filter(reponse='REFUSE').count(),
        'en_attente': reponses.filter(reponse='EN_ATTENTE').count(),
        'expirees': reponses.filter(reponse='EXPIRE').count(),
        'liste': []
    }
    
    for reponse in reponses:
        reponse_data = {
            'candidat': {
                'nom_complet': reponse.candidat.nom_complet,
                'matricule': reponse.candidat.matricule,
                'departement': reponse.candidat.departement.nom if reponse.candidat.departement else 'Non défini',
            },
            'reponse': reponse.get_reponse_display(),
            'reponse_code': reponse.reponse,
            'date_proposition': reponse.date_proposition.strftime('%d/%m/%Y %H:%M'),
            'date_reponse': reponse.date_reponse.strftime('%d/%m/%Y %H:%M') if reponse.date_reponse else None,
            'date_limite': reponse.date_limite_reponse.strftime('%d/%m/%Y %H:%M'),
            'motif_refus': reponse.get_motif_refus_display() if reponse.motif_refus else None,
            'commentaire': reponse.commentaire_refus,
            'salaire_propose': float(reponse.salaire_propose) if reponse.salaire_propose else None,
            'avantages_proposes': reponse.avantages_proposes,
            'nb_rappels': reponse.nb_rappels_envoyes,
            'est_expire': reponse.est_expire,
            'temps_restant': reponse.temps_restant_display,
        }
        
        reponses_data['liste'].append(reponse_data)
    
    return reponses_data


def _obtenir_notifications_liees(demande):
    """Obtient les notifications liées à la demande"""
    notifications = demande.notifications.select_related(
        'destinataire__user', 'expediteur__user'
    ).order_by('-created_at')[:10]
    
    notifications_data = {
        'total': demande.notifications.count(),
        'non_lues': demande.notifications.filter(statut='NON_LUE').count(),
        'liste': []
    }
    
    for notif in notifications:
        notif_data = {
            'type': notif.get_type_notification_display(),
            'destinataire': notif.destinataire.nom_complet,
            'expediteur': notif.expediteur.nom_complet if notif.expediteur else 'Système',
            'titre': notif.titre,
            'message': notif.message,
            'urgence': notif.get_urgence_display(),
            'statut': notif.get_statut_display(),
            'date_creation': notif.created_at.strftime('%d/%m/%Y %H:%M'),
            'date_lecture': notif.date_lecture.strftime('%d/%m/%Y %H:%M') if notif.date_lecture else None,
            'est_expiree': notif.est_expiree,
        }
        
        notifications_data['liste'].append(notif_data)
    
    return notifications_data


def _calculer_statistiques_demande(demande):
    """Calcule diverses statistiques sur la demande"""
    stats = {
        'duree_totale_processus': (timezone.now().date() - demande.created_at.date()).days,
        'temps_moyen_validation': None,
        'score_moyen_propositions': None,
        'taux_reponse_candidats': None,
        'delai_reponse_moyen': None,
    }
    
    # Temps moyen de validation
    validations_terminees = demande.validations.filter(date_validation__isnull=False)
    if validations_terminees.exists():
        delais = []
        for val in validations_terminees:
            delai = val.date_validation - val.date_demande_validation
            delais.append(delai.total_seconds() / 3600)  # En heures
        stats['temps_moyen_validation'] = round(sum(delais) / len(delais), 1)
    
    # Score moyen des propositions
    if demande.propositions_candidats.exists():
        scores = demande.propositions_candidats.aggregate(Avg('score_final'))
        stats['score_moyen_propositions'] = round(scores['score_final__avg'] or 0, 1)
    
    # Taux de réponse des candidats
    total_candidats = demande.reponses_candidats.count()
    if total_candidats > 0:
        reponses_donnees = demande.reponses_candidats.exclude(reponse='EN_ATTENTE').count()
        stats['taux_reponse_candidats'] = round((reponses_donnees / total_candidats) * 100, 1)
        
        # Délai de réponse moyen
        reponses_avec_date = demande.reponses_candidats.filter(date_reponse__isnull=False)
        if reponses_avec_date.exists():
            delais_reponse = []
            for rep in reponses_avec_date:
                delai = rep.date_reponse - rep.date_proposition
                delais_reponse.append(delai.total_seconds() / 3600)  # En heures
            stats['delai_reponse_moyen'] = round(sum(delais_reponse) / len(delais_reponse), 1)
    
    return stats


def _determiner_actions_disponibles(demande, profil_utilisateur):
    """Détermine les actions disponibles pour l'utilisateur connecté"""
    actions = {
        'peut_proposer_candidat': False,
        'peut_valider': False,
        'peut_modifier': False,
        'peut_annuler': False,
        'peut_voir_details_complets': False,
        'peut_exporter': False,
        'niveau_validation_possible': None,
    }
    
    # Vérifier les permissions générales
    actions['peut_voir_details_complets'] = _peut_voir_details_complets(demande, profil_utilisateur)
    actions['peut_exporter'] = actions['peut_voir_details_complets']
    
    # Vérifier si peut proposer un candidat
    peut_proposer, _ = demande.peut_proposer_candidat(profil_utilisateur)
    actions['peut_proposer_candidat'] = peut_proposer
    
    # Vérifier si peut valider
    if demande.statut in ['SOUMISE', 'EN_VALIDATION']:
        niveau_suivant = demande.niveau_validation_actuel + 1
        if profil_utilisateur.peut_valider_niveau(niveau_suivant):
            actions['peut_valider'] = True
            actions['niveau_validation_possible'] = niveau_suivant
    
    # Vérifier si peut modifier
    if demande.peut_etre_modifiee and (
        demande.demandeur == profil_utilisateur or
        profil_utilisateur.type_profil in ['RH', 'ADMIN'] or
        profil_utilisateur.is_superuser
    ):
        actions['peut_modifier'] = True
    
    # Vérifier si peut annuler
    if demande.statut not in ['TERMINEE', 'REFUSEE', 'ANNULEE'] and (
        demande.demandeur == profil_utilisateur or
        profil_utilisateur.type_profil in ['RH', 'ADMIN'] or
        profil_utilisateur.is_superuser
    ):
        actions['peut_annuler'] = True
    
    return actions


def _peut_voir_details_complets(demande, profil_utilisateur):
    """Vérifie si l'utilisateur peut voir tous les détails"""
    # Superusers et RH/ADMIN voient tout
    if profil_utilisateur.is_superuser or profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return True
    
    # Demandeur et personne remplacée voient tout
    if demande.demandeur == profil_utilisateur or demande.personne_remplacee == profil_utilisateur:
        return True
    
    # Candidat sélectionné voit ses détails
    if demande.candidat_selectionne == profil_utilisateur:
        return True
    
    # Hiérarchie selon département
    if profil_utilisateur.type_profil in ['DIRECTEUR', 'RESPONSABLE']:
        if profil_utilisateur.departement == demande.poste.departement:
            return True
    
    return False

@login_required
def workflow_global(request):
    """
    Vue principale pour le dashboard global des workflows
    Affiche l'avancement des workflows d'intérim avec graphiques et métriques
    """
    try:
        # Récupérer le profil utilisateur
        profil_utilisateur = get_object_or_404(ProfilUtilisateur, user=request.user)
        
        # Déterminer les permissions d'accès
        peut_voir_tout = (
            profil_utilisateur.is_superuser or 
            profil_utilisateur.type_profil in ['RH', 'ADMIN']
        )
        
        niveau_acces = _determiner_niveau_acces_workflow(profil_utilisateur)
        
        # Récupérer les paramètres de période
        aujourd_hui = date.today()
        
        # Paramètres de plage de dates (par défaut: 30 derniers jours)
        date_debut_param = request.GET.get('date_debut')
        date_fin_param = request.GET.get('date_fin')
        periode_type = request.GET.get('periode', 'mois')  # mois, trimestre, semestre, annee
        
        # Définir les dates de la période
        if date_debut_param and date_fin_param:
            try:
                date_debut = datetime.strptime(date_debut_param, '%Y-%m-%d').date()
                date_fin = datetime.strptime(date_fin_param, '%Y-%m-%d').date()
            except ValueError:
                date_debut, date_fin = _calculer_periode_defaut(periode_type, aujourd_hui)
        else:
            date_debut, date_fin = _calculer_periode_defaut(periode_type, aujourd_hui)
        
        # Récupérer les filtres additionnels
        filtres = {
            'departement': request.GET.get('departement', ''),
            'site': request.GET.get('site', ''),
            'urgence': request.GET.get('urgence', ''),
            'statut': request.GET.get('statut', ''),
            'niveau_validation': request.GET.get('niveau_validation', ''),
            'avec_retard': request.GET.get('avec_retard', '') == 'on',
        }
        
        # Construire le queryset selon les permissions
        demandes_base = _construire_queryset_workflow(profil_utilisateur, peut_voir_tout, niveau_acces)
        
        # Filtrer par période
        demandes_periode = demandes_base.filter(
            created_at__date__range=[date_debut, date_fin]
        )
        
        # Appliquer les filtres additionnels
        demandes_filtrees = _appliquer_filtres_workflow(demandes_periode, filtres)
        
        # Optimiser les requêtes avec prefetch
        demandes_filtrees = demandes_filtrees.select_related(
            'demandeur__user', 'personne_remplacee__user',
            'poste__departement', 'poste__site', 'motif_absence',
            'candidat_selectionne__user'
        ).prefetch_related(
            'validations__validateur__user',
            'propositions_candidats__candidat_propose__user',
            'historique_actions__utilisateur__user'
        )
        
        # ========================================
        # CALCULS DES MÉTRIQUES PRINCIPALES
        # ========================================
        
        # Vue d'ensemble des workflows
        vue_ensemble = _calculer_vue_ensemble(demandes_filtrees, date_debut, date_fin)
        
        # Données pour les graphiques principaux
        donnees_graphiques = _generer_donnees_graphiques(
            demandes_filtrees, date_debut, date_fin, periode_type
        )
        
        # Analyse des goulots d'étranglement
        goulots_etranglement = _analyser_goulots_etranglement(demandes_filtrees)
        
        # Performance par département/utilisateur
        performance_entites = _analyser_performance_entites(
            demandes_filtrees, profil_utilisateur, peut_voir_tout
        )
        
        # Demandes critiques nécessitant attention
        demandes_critiques = _identifier_demandes_critiques(demandes_filtrees)
        
        # Tendances et évolution
        tendances = _calculer_tendances(demandes_base, date_debut, date_fin, periode_type)
        
        # Prédictions et alertes
        predictions = _generer_predictions(demandes_base, tendances)
        
        # ========================================
        # DONNÉES POUR LES FILTRES
        # ========================================
        
        departements_accessibles = _obtenir_departements_workflow(
            profil_utilisateur, peut_voir_tout
        )
        sites_accessibles = _obtenir_sites_workflow(
            profil_utilisateur, peut_voir_tout
        )
        
        # Choix pour les formulaires
        statuts_choix = DemandeInterim.STATUTS
        urgences_choix = DemandeInterim.URGENCES
        niveaux_validation_choix = [
            (0, 'Demande soumise'),
            (1, 'Validation Responsable (N+1)'),
            (2, 'Validation Directeur (N+2)'),
            (3, 'Validation RH/Admin (Final)'),
        ]
        
        # Options de période prédéfinies
        periodes_predefinies = _obtenir_periodes_predefinies(aujourd_hui)
        
        context = {
            'profil_utilisateur': profil_utilisateur,
            'peut_voir_tout': peut_voir_tout,
            'niveau_acces': niveau_acces,
            
            # ========================================
            # PÉRIODE ET FILTRES
            # ========================================
            'date_debut': date_debut,
            'date_fin': date_fin,
            'periode_type': periode_type,
            'nombre_jours': (date_fin - date_debut).days + 1,
            
            'filtres': filtres,
            'departements_accessibles': departements_accessibles,
            'sites_accessibles': sites_accessibles,
            'statuts_choix': statuts_choix,
            'urgences_choix': urgences_choix,
            'niveaux_validation_choix': niveaux_validation_choix,
            'periodes_predefinies': periodes_predefinies,
            
            # ========================================
            # DONNÉES PRINCIPALES
            # ========================================
            'vue_ensemble': vue_ensemble,
            'donnees_graphiques': donnees_graphiques,
            'goulots_etranglement': goulots_etranglement,
            'performance_entites': performance_entites,
            'demandes_critiques': demandes_critiques,
            'tendances': tendances,
            'predictions': predictions,
            
            # ========================================
            # MÉTADONNÉES
            # ========================================
            'total_demandes_periode': demandes_filtrees.count(),
            'total_demandes_base': demandes_base.count(),
            'pourcentage_periode': round(
                (demandes_filtrees.count() / max(demandes_base.count(), 1)) * 100, 1
            ),
            'date_generation': timezone.now(),
            'peut_exporter': peut_voir_tout or profil_utilisateur.type_profil in ['DIRECTEUR', 'RESPONSABLE'],
        }
        
        return render(request, 'workflow_global.html', context)
        
    except Exception as e:
        messages.error(
            request,
            f"Erreur lors du chargement du dashboard workflow : {str(e)}"
        )
        return render(request, 'workflow_global.html', {
            'profil_utilisateur': profil_utilisateur,
            'erreur': True,
            'message_erreur': str(e)
        })


def _determiner_niveau_acces_workflow(profil_utilisateur):
    """Détermine le niveau d'accès pour le workflow"""
    if profil_utilisateur.is_superuser:
        return 'SUPERUSER'
    elif profil_utilisateur.type_profil in ['RH', 'ADMIN']:
        return 'GLOBAL'
    elif profil_utilisateur.type_profil == 'DIRECTEUR':
        return 'DIRECTEUR'
    elif profil_utilisateur.type_profil == 'RESPONSABLE':
        return 'RESPONSABLE'
    elif profil_utilisateur.type_profil == 'CHEF_EQUIPE':
        return 'CHEF_EQUIPE'
    else:
        return 'UTILISATEUR'


def _construire_queryset_workflow(profil_utilisateur, peut_voir_tout, niveau_acces):
    """Construit le queryset selon les permissions"""
    if peut_voir_tout:
        return DemandeInterim.objects.all()
    
    filtres_acces = Q()
    
    if niveau_acces == 'DIRECTEUR':
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    elif niveau_acces == 'RESPONSABLE':
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    elif niveau_acces == 'CHEF_EQUIPE':
        if profil_utilisateur.departement:
            filtres_acces = Q(poste__departement=profil_utilisateur.departement)
    
    else:  # UTILISATEUR
        filtres_acces = Q(demandeur=profil_utilisateur) | Q(personne_remplacee=profil_utilisateur)
    
    return DemandeInterim.objects.filter(filtres_acces)


def _calculer_periode_defaut(periode_type, reference_date):
    """Calcule la période par défaut selon le type"""
    if periode_type == 'semaine':
        debut = reference_date - timedelta(days=reference_date.weekday())
        fin = debut + timedelta(days=6)
    elif periode_type == 'mois':
        debut = reference_date.replace(day=1)
        if reference_date.month == 12:
            fin = date(reference_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            fin = date(reference_date.year, reference_date.month + 1, 1) - timedelta(days=1)
    elif periode_type == 'trimestre':
        quarter = (reference_date.month - 1) // 3 + 1
        debut = date(reference_date.year, (quarter - 1) * 3 + 1, 1)
        if quarter == 4:
            fin = date(reference_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            fin = date(reference_date.year, quarter * 3 + 1, 1) - timedelta(days=1)
    elif periode_type == 'semestre':
        if reference_date.month <= 6:
            debut = date(reference_date.year, 1, 1)
            fin = date(reference_date.year, 6, 30)
        else:
            debut = date(reference_date.year, 7, 1)
            fin = date(reference_date.year, 12, 31)
    elif periode_type == 'annee':
        debut = date(reference_date.year, 1, 1)
        fin = date(reference_date.year, 12, 31)
    else:  # Par défaut: 30 derniers jours
        fin = reference_date
        debut = fin - timedelta(days=29)
    
    return debut, fin


def _appliquer_filtres_workflow(queryset, filtres):
    """Applique les filtres sur le queryset"""
    if filtres['departement']:
        try:
            dept_id = int(filtres['departement'])
            queryset = queryset.filter(poste__departement_id=dept_id)
        except (ValueError, TypeError):
            pass
    
    if filtres['site']:
        try:
            site_id = int(filtres['site'])
            queryset = queryset.filter(poste__site_id=site_id)
        except (ValueError, TypeError):
            pass
    
    if filtres['urgence']:
        queryset = queryset.filter(urgence=filtres['urgence'])
    
    if filtres['statut']:
        queryset = queryset.filter(statut=filtres['statut'])
    
    if filtres['niveau_validation']:
        try:
            niveau = int(filtres['niveau_validation'])
            queryset = queryset.filter(niveau_validation_actuel=niveau)
        except (ValueError, TypeError):
            pass
    
    if filtres['avec_retard']:
        # Demandes créées il y a plus de 5 jours et toujours en validation
        date_limite = timezone.now().date() - timedelta(days=5)
        queryset = queryset.filter(
            created_at__date__lt=date_limite,
            statut__in=['SOUMISE', 'EN_VALIDATION']
        )
    
    return queryset


def _calculer_vue_ensemble(demandes, date_debut, date_fin):
    """Calcule la vue d'ensemble des workflows"""
    total = demandes.count()
    
    if total == 0:
        return {
            'total_demandes': 0,
            'repartition_etapes': {},
            'temps_moyen_traitement': 0,
            'taux_completion': 0,
            'demandes_en_retard': 0,
            'efficacite_globale': 0,
        }
    
    # Répartition par étape de workflow
    repartition_etapes = {}
    for niveau in range(4):  # 0 à 3
        count = demandes.filter(niveau_validation_actuel=niveau).count()
        if count > 0:
            etape_nom = {
                0: 'Demande soumise',
                1: 'Validation Responsable',
                2: 'Validation Directeur', 
                3: 'Validation RH/Admin'
            }.get(niveau, f'Niveau {niveau}')
            
            repartition_etapes[etape_nom] = {
                'count': count,
                'pourcentage': round((count / total) * 100, 1)
            }
    
    # Temps moyen de traitement (en jours)
    demandes_avec_temps = []
    for demande in demandes:
        if demande.statut in ['TERMINEE', 'EN_COURS']:
            if demande.date_validation:
                temps = (demande.date_validation.date() - demande.created_at.date()).days
            else:
                temps = (timezone.now().date() - demande.created_at.date()).days
            demandes_avec_temps.append(temps)
    
    temps_moyen = round(sum(demandes_avec_temps) / len(demandes_avec_temps), 1) if demandes_avec_temps else 0
    
    # Taux de completion
    demandes_terminees = demandes.filter(statut__in=['TERMINEE', 'EN_COURS']).count()
    taux_completion = round((demandes_terminees / total) * 100, 1)
    
    # Demandes en retard (plus de 5 jours)
    date_limite = timezone.now().date() - timedelta(days=5)
    demandes_en_retard = demandes.filter(
        created_at__date__lt=date_limite,
        statut__in=['SOUMISE', 'EN_VALIDATION']
    ).count()
    
    # Efficacité globale (score composite)
    efficacite = round((taux_completion * 0.6) + ((1 - (demandes_en_retard / max(total, 1))) * 40), 1)
    
    return {
        'total_demandes': total,
        'repartition_etapes': repartition_etapes,
        'temps_moyen_traitement': temps_moyen,
        'taux_completion': taux_completion,
        'demandes_en_retard': demandes_en_retard,
        'efficacite_globale': efficacite,
        'periode_jours': (date_fin - date_debut).days + 1,
    }


def _generer_donnees_graphiques(demandes, date_debut, date_fin, periode_type):
    """Génère les données pour les graphiques"""
    
    # Graphique d'évolution temporelle
    evolution_temporelle = _calculer_evolution_temporelle(demandes, date_debut, date_fin, periode_type)
    
    # Graphique répartition par étapes
    repartition_etapes = _calculer_repartition_etapes_graphique(demandes)
    
    # Graphique temps de traitement par étape
    temps_par_etape = _calculer_temps_par_etape(demandes)
    
    # Graphique performance par département
    performance_dept = _calculer_performance_departements(demandes)
    
    # Graphique urgence vs délai
    urgence_vs_delai = _calculer_urgence_vs_delai(demandes)
    
    return {
        'evolution_temporelle': evolution_temporelle,
        'repartition_etapes': repartition_etapes,
        'temps_par_etape': temps_par_etape,
        'performance_departements': performance_dept,
        'urgence_vs_delai': urgence_vs_delai,
    }


def _calculer_evolution_temporelle(demandes, date_debut, date_fin, periode_type):
    """Calcule l'évolution du nombre de demandes dans le temps - Version compatible"""
    
    # Approche compatible sans TruncDate
    donnees = {
        'labels': [],
        'datasets': {
            'total': [],
            'terminees': [],
            'en_retard': []
        }
    }
    
    try:
        if periode_type in ['semaine', 'mois']:
            # Grouper par jour
            evolution_data = demandes.extra(
                select={'date_creation': "DATE(created_at)"}
            ).values('date_creation').annotate(
                total=Count('id'),
                terminees=Count(Case(When(statut__in=['TERMINEE', 'EN_COURS'], then=1))),
                en_retard=Count(Case(
                    When(
                        created_at__lt=timezone.now() - timedelta(days=5),
                        statut__in=['SOUMISE', 'EN_VALIDATION'],
                        then=1
                    )
                ))
            ).order_by('date_creation')
            
            for item in evolution_data:
                if item['date_creation']:
                    try:
                        # Convertir la string en date si nécessaire
                        if isinstance(item['date_creation'], str):
                            from datetime import datetime
                            date_obj = datetime.strptime(item['date_creation'], '%Y-%m-%d').date()
                        else:
                            date_obj = item['date_creation']
                        
                        label = date_obj.strftime('%d/%m')
                        donnees['labels'].append(label)
                        donnees['datasets']['total'].append(item['total'])
                        donnees['datasets']['terminees'].append(item['terminees'])
                        donnees['datasets']['en_retard'].append(item['en_retard'])
                    except (ValueError, AttributeError, TypeError):
                        continue
        
        elif periode_type in ['trimestre', 'semestre']:
            # Grouper par semaine avec Extract
            evolution_data = demandes.annotate(
                annee=Extract('created_at', 'year'),
                semaine=Extract('created_at', 'week')
            ).values('annee', 'semaine').annotate(
                total=Count('id'),
                terminees=Count(Case(When(statut__in=['TERMINEE', 'EN_COURS'], then=1))),
                en_retard=Count(Case(
                    When(
                        created_at__lt=timezone.now() - timedelta(days=5),
                        statut__in=['SOUMISE', 'EN_VALIDATION'],
                        then=1
                    )
                ))
            ).order_by('annee', 'semaine')
            
            for item in evolution_data:
                label = f"S{item['semaine']}"
                donnees['labels'].append(label)
                donnees['datasets']['total'].append(item['total'])
                donnees['datasets']['terminees'].append(item['terminees'])
                donnees['datasets']['en_retard'].append(item['en_retard'])
        
        else:  # année
            # Grouper par mois avec Extract
            evolution_data = demandes.annotate(
                annee=Extract('created_at', 'year'),
                mois=Extract('created_at', 'month')
            ).values('annee', 'mois').annotate(
                total=Count('id'),
                terminees=Count(Case(When(statut__in=['TERMINEE', 'EN_COURS'], then=1))),
                en_retard=Count(Case(
                    When(
                        created_at__lt=timezone.now() - timedelta(days=5),
                        statut__in=['SOUMISE', 'EN_VALIDATION'],
                        then=1
                    )
                ))
            ).order_by('annee', 'mois')
            
            for item in evolution_data:
                try:
                    label = f"{item['mois']:02d}/{item['annee']}"
                    donnees['labels'].append(label)
                    donnees['datasets']['total'].append(item['total'])
                    donnees['datasets']['terminees'].append(item['terminees'])
                    donnees['datasets']['en_retard'].append(item['en_retard'])
                except (TypeError, ValueError):
                    continue
    
    except Exception as e:
        # Fallback : approche simple en Python
        print(f"Erreur dans l'évolution temporelle: {e}")
        donnees = _calculer_evolution_fallback(demandes, date_debut, date_fin, periode_type)
    
    return donnees


def _calculer_evolution_fallback(demandes, date_debut, date_fin, periode_type):
    """Fallback pour l'évolution temporelle - calcul en Python"""
    from collections import defaultdict
    
    donnees = {
        'labels': [],
        'datasets': {
            'total': [],
            'terminees': [],
            'en_retard': []
        }
    }
    
    # Grouper les demandes par période
    data_by_periode = defaultdict(lambda: {'total': 0, 'terminees': 0, 'en_retard': 0})
    
    for demande in demandes:
        try:
            date_creation = demande.created_at.date()
            
            # Déterminer la clé de période
            if periode_type in ['semaine', 'mois']:
                key = date_creation.strftime('%d/%m')
            elif periode_type in ['trimestre', 'semestre']:
                key = f"S{date_creation.isocalendar()[1]}"
            else:  # année
                key = date_creation.strftime('%m/%Y')
            
            # Compter les demandes
            data_by_periode[key]['total'] += 1
            
            if demande.statut in ['TERMINEE', 'EN_COURS']:
                data_by_periode[key]['terminees'] += 1
            
            # Vérifier si en retard
            if (demande.created_at.date() < timezone.now().date() - timedelta(days=5) and
                demande.statut in ['SOUMISE', 'EN_VALIDATION']):
                data_by_periode[key]['en_retard'] += 1
        
        except (AttributeError, TypeError, ValueError):
            continue
    
    # Trier et formater les données
    sorted_keys = sorted(data_by_periode.keys())
    
    for key in sorted_keys:
        data = data_by_periode[key]
        donnees['labels'].append(key)
        donnees['datasets']['total'].append(data['total'])
        donnees['datasets']['terminees'].append(data['terminees'])
        donnees['datasets']['en_retard'].append(data['en_retard'])
    
    return donnees


def _calculer_repartition_etapes_graphique(demandes):
    """Calcule la répartition des demandes par étape pour graphique en camembert"""
    
    repartition = demandes.values('niveau_validation_actuel').annotate(
        count=Count('id')
    ).order_by('niveau_validation_actuel')
    
    etapes_noms = {
        0: 'Soumise',
        1: 'Responsable',
        2: 'Directeur',
        3: 'RH/Admin'
    }
    
    donnees = {
        'labels': [],
        'data': [],
        'colors': ['#dc3545', '#ffc107', '#17a2b8', '#28a745']  # Rouge, Jaune, Bleu, Vert
    }
    
    for item in repartition:
        niveau = item['niveau_validation_actuel']
        donnees['labels'].append(etapes_noms.get(niveau, f'Niveau {niveau}'))
        donnees['data'].append(item['count'])
    
    return donnees


def _calculer_temps_par_etape(demandes):
    """Calcule le temps moyen de traitement par étape"""
    
    # Analyser les validations pour calculer les temps
    temps_par_niveau = {}
    
    for niveau in range(1, 4):  # Niveaux 1, 2, 3
        validations = ValidationDemande.objects.filter(
            demande__in=demandes,
            niveau_validation=niveau,
            date_validation__isnull=False
        )
        
        if validations.exists():
            temps_total = 0
            count = 0
            
            for validation in validations:
                temps = (validation.date_validation - validation.date_demande_validation).total_seconds() / 3600  # en heures
                temps_total += temps
                count += 1
            
            temps_moyen = round(temps_total / count, 1) if count > 0 else 0
            temps_par_niveau[niveau] = temps_moyen
    
    etapes_noms = {
        1: 'Responsable (N+1)',
        2: 'Directeur (N+2)',
        3: 'RH/Admin (Final)'
    }
    
    donnees = {
        'labels': [etapes_noms[niveau] for niveau in sorted(temps_par_niveau.keys())],
        'data': [temps_par_niveau[niveau] for niveau in sorted(temps_par_niveau.keys())],
    }
    
    return donnees


def _calculer_performance_departements(demandes):
    """Calcule la performance par département"""
    
    performance = demandes.values(
        'poste__departement__nom'
    ).annotate(
        total=Count('id'),
        terminees=Count(Case(When(statut__in=['TERMINEE', 'EN_COURS'], then=1))),
        temps_moyen=Avg(
            Case(
                When(
                    date_validation__isnull=False,
                    then=F('date_validation') - F('created_at')
                ),
                default=timezone.now() - F('created_at')
            )
        )
    ).order_by('-total')[:10]  # Top 10
    
    donnees = {
        'labels': [],
        'datasets': {
            'total': [],
            'terminees': [],
            'taux_completion': []
        }
    }
    
    for item in performance:
        if item['poste__departement__nom']:
            donnees['labels'].append(item['poste__departement__nom'][:15])  # Limiter la longueur
            donnees['datasets']['total'].append(item['total'])
            donnees['datasets']['terminees'].append(item['terminees'])
            taux = round((item['terminees'] / item['total']) * 100, 1) if item['total'] > 0 else 0
            donnees['datasets']['taux_completion'].append(taux)
    
    return donnees


def _calculer_urgence_vs_delai(demandes):
    """Analyse la relation entre urgence et délai de traitement"""
    
    urgence_stats = {}
    
    for urgence, libelle in DemandeInterim.URGENCES:
        demandes_urgence = demandes.filter(urgence=urgence)
        
        if demandes_urgence.exists():
            temps_traitement = []
            
            for demande in demandes_urgence:
                if demande.date_validation:
                    temps = (demande.date_validation.date() - demande.created_at.date()).days
                elif demande.statut not in ['REFUSEE', 'ANNULEE']:
                    temps = (timezone.now().date() - demande.created_at.date()).days
                else:
                    continue
                
                temps_traitement.append(temps)
            
            if temps_traitement:
                urgence_stats[libelle] = {
                    'count': len(temps_traitement),
                    'temps_moyen': round(sum(temps_traitement) / len(temps_traitement), 1),
                    'temps_median': sorted(temps_traitement)[len(temps_traitement) // 2]
                }
    
    donnees = {
        'labels': list(urgence_stats.keys()),
        'datasets': {
            'count': [urgence_stats[k]['count'] for k in urgence_stats.keys()],
            'temps_moyen': [urgence_stats[k]['temps_moyen'] for k in urgence_stats.keys()],
            'temps_median': [urgence_stats[k]['temps_median'] for k in urgence_stats.keys()]
        }
    }
    
    return donnees


def _analyser_goulots_etranglement(demandes):
    """Identifie les goulots d'étranglement dans les workflows"""
    
    goulots = []
    
    # Analyser les étapes avec le plus de demandes bloquées
    for niveau in range(4):
        demandes_niveau = demandes.filter(niveau_validation_actuel=niveau)
        
        if demandes_niveau.exists():
            # Demandes bloquées depuis plus de 5 jours
            date_limite = timezone.now().date() - timedelta(days=5)
            demandes_bloquees = demandes_niveau.filter(
                created_at__date__lt=date_limite,
                statut__in=['SOUMISE', 'EN_VALIDATION']
            )
            
            if demandes_bloquees.exists():
                etape_nom = {
                    0: 'Demandes soumises',
                    1: 'Validation Responsable',
                    2: 'Validation Directeur',
                    3: 'Validation RH/Admin'
                }.get(niveau, f'Niveau {niveau}')
                
                # Calculer l'âge moyen des demandes bloquées
                ages = []
                for demande in demandes_bloquees:
                    age = (timezone.now().date() - demande.created_at.date()).days
                    ages.append(age)
                
                age_moyen = round(sum(ages) / len(ages), 1) if ages else 0
                
                goulots.append({
                    'etape': etape_nom,
                    'niveau': niveau,
                    'nb_demandes_bloquees': demandes_bloquees.count(),
                    'age_moyen_jours': age_moyen,
                    'severite': _calculer_severite_goulot(demandes_bloquees.count(), age_moyen),
                    'demandes_exemple': demandes_bloquees.select_related(
                        'demandeur__user', 'poste__departement'
                    )[:3]  # Exemples
                })
    
    # Trier par sévérité
    goulots.sort(key=lambda x: x['severite'], reverse=True)
    
    return goulots


def _calculer_severite_goulot(nb_demandes, age_moyen):
    """Calcule un score de sévérité pour un goulot d'étranglement"""
    # Score basé sur le nombre de demandes et l'âge moyen
    score_nombre = min(nb_demandes * 10, 50)  # Max 50 points
    score_age = min(age_moyen * 5, 50)  # Max 50 points
    return score_nombre + score_age


def _analyser_performance_entites(demandes, profil_utilisateur, peut_voir_tout):
    """Analyse la performance par entité (département, utilisateur)"""
    
    performance = {
        'departements': [],
        'utilisateurs': [],
        'motifs_absence': []
    }
    
    # Performance par département
    if peut_voir_tout or profil_utilisateur.type_profil in ['DIRECTEUR', 'RH', 'ADMIN']:
        dept_stats = demandes.values(
            'poste__departement__nom'
        ).annotate(
            total=Count('id'),
            terminees=Count(Case(When(statut__in=['TERMINEE', 'EN_COURS'], then=1))),
            moyenne_jours=Avg(
                Case(
                    When(
                        date_validation__isnull=False,
                        then=F('date_validation__date') - F('created_at__date')
                    )
                )
            )
        ).order_by('-total')
        
        for dept in dept_stats:
            if dept['poste__departement__nom']:
                taux = round((dept['terminees'] / dept['total']) * 100, 1) if dept['total'] > 0 else 0
                performance['departements'].append({
                    'nom': dept['poste__departement__nom'],
                    'total_demandes': dept['total'],
                    'taux_completion': taux,
                    'temps_moyen': round(dept['moyenne_jours'].days if dept['moyenne_jours'] else 0, 1)
                })
    
    # Performance par motif d'absence
    motif_stats = demandes.values(
        'motif_absence__nom'
    ).annotate(
        total=Count('id'),
        terminees=Count(Case(When(statut__in=['TERMINEE', 'EN_COURS'], then=1)))
    ).order_by('-total')[:10]
    
    for motif in motif_stats:
        taux = round((motif['terminees'] / motif['total']) * 100, 1) if motif['total'] > 0 else 0
        performance['motifs_absence'].append({
            'nom': motif['motif_absence__nom'],
            'total_demandes': motif['total'],
            'taux_completion': taux
        })
    
    return performance


def _identifier_demandes_critiques(demandes):
    """Identifie les demandes nécessitant une attention immédiate"""
    
    critiques = []
    
    # Demandes urgentes en retard
    date_limite_urgente = timezone.now().date() - timedelta(days=2)
    demandes_urgentes_retard = demandes.filter(
        urgence__in=['ELEVEE', 'CRITIQUE'],
        created_at__date__lt=date_limite_urgente,
        statut__in=['SOUMISE', 'EN_VALIDATION']
    ).select_related(
        'demandeur__user', 'personne_remplacee__user', 'poste__departement'
    )
    
    for demande in demandes_urgentes_retard[:10]:
        age_jours = (timezone.now().date() - demande.created_at.date()).days
        critiques.append({
            'demande': demande,
            'type_critique': 'URGENTE_RETARD',
            'description': f"Demande {demande.get_urgence_display().lower()} en retard de {age_jours} jours",
            'severite': _calculer_severite_critique(demande, age_jours),
            'actions_suggerees': _suggerer_actions_demande(demande)
        })
    
    # Demandes avec beaucoup de propositions mais pas de sélection
    demandes_sans_selection = demandes.filter(
        candidat_selectionne__isnull=True,
        statut__in=['EN_RECHERCHE', 'CANDIDAT_PROPOSE']
    ).annotate(
        nb_propositions=Count('propositions_candidats')
    ).filter(nb_propositions__gte=3)
    
    for demande in demandes_sans_selection[:5]:
        age_jours = (timezone.now().date() - demande.created_at.date()).days
        critiques.append({
            'demande': demande,
            'type_critique': 'SANS_SELECTION',
            'description': f"{demande.nb_propositions} propositions mais aucune sélection",
            'severite': _calculer_severite_critique(demande, age_jours),
            'actions_suggerees': _suggerer_actions_demande(demande)
        })
    
    # Trier par sévérité
    critiques.sort(key=lambda x: x['severite'], reverse=True)
    
    return critiques[:15]  # Limiter à 15


def _calculer_severite_critique(demande, age_jours):
    """Calcule un score de sévérité pour une demande critique"""
    score = 0
    
    # Points pour l'urgence
    if demande.urgence == 'CRITIQUE':
        score += 50
    elif demande.urgence == 'ELEVEE':
        score += 30
    elif demande.urgence == 'MOYENNE':
        score += 15
    
    # Points pour l'âge
    score += min(age_jours * 2, 30)
    
    # Points pour le niveau de validation bloqué
    score += demande.niveau_validation_actuel * 5
    
    return score


def _suggerer_actions_demande(demande):
    """Suggère des actions pour débloquer une demande"""
    actions = []
    
    if demande.statut in ['SOUMISE', 'EN_VALIDATION']:
        niveau_suivant = demande.niveau_validation_actuel + 1
        if niveau_suivant == 1:
            actions.append("Contacter le responsable pour validation N+1")
        elif niveau_suivant == 2:
            actions.append("Escalader vers le directeur pour validation N+2")
        elif niveau_suivant == 3:
            actions.append("Transférer vers RH/Admin pour validation finale")
    
    if demande.propositions_candidats.count() == 0:
        actions.append("Rechercher et proposer des candidats")
    elif demande.candidat_selectionne is None:
        actions.append("Sélectionner un candidat parmi les propositions")
    
    return actions


def _calculer_tendances(demandes_base, date_debut, date_fin, periode_type):
    """Calcule les tendances et évolutions"""
    
    # Période de comparaison (même durée, période précédente)
    duree_jours = (date_fin - date_debut).days + 1
    date_debut_precedente = date_debut - timedelta(days=duree_jours)
    date_fin_precedente = date_debut - timedelta(days=1)
    
    demandes_periode_actuelle = demandes_base.filter(
        created_at__date__range=[date_debut, date_fin]
    )
    
    demandes_periode_precedente = demandes_base.filter(
        created_at__date__range=[date_debut_precedente, date_fin_precedente]
    )
    
    # Métriques actuelles vs précédentes
    stats_actuelles = _calculer_stats_periode(demandes_periode_actuelle)
    stats_precedentes = _calculer_stats_periode(demandes_periode_precedente)
    
    tendances = {}
    
    for metrique in ['total', 'terminees', 'temps_moyen', 'taux_completion']:
        valeur_actuelle = stats_actuelles.get(metrique, 0)
        valeur_precedente = stats_precedentes.get(metrique, 0)
        
        if valeur_precedente > 0:
            evolution = ((valeur_actuelle - valeur_precedente) / valeur_precedente) * 100
        else:
            evolution = 100 if valeur_actuelle > 0 else 0
        
        tendances[metrique] = {
            'valeur_actuelle': valeur_actuelle,
            'valeur_precedente': valeur_precedente,
            'evolution_pourcentage': round(evolution, 1),
            'tendance': 'hausse' if evolution > 5 else 'baisse' if evolution < -5 else 'stable'
        }
    
    return tendances


def _calculer_stats_periode(demandes):
    """Calcule les statistiques d'une période"""
    total = demandes.count()
    
    if total == 0:
        return {'total': 0, 'terminees': 0, 'temps_moyen': 0, 'taux_completion': 0}
    
    terminees = demandes.filter(statut__in=['TERMINEE', 'EN_COURS']).count()
    
    # Temps moyen
    temps_total = 0
    count_temps = 0
    
    for demande in demandes:
        if demande.date_validation:
            temps = (demande.date_validation.date() - demande.created_at.date()).days
            temps_total += temps
            count_temps += 1
    
    temps_moyen = round(temps_total / count_temps, 1) if count_temps > 0 else 0
    taux_completion = round((terminees / total) * 100, 1)
    
    return {
        'total': total,
        'terminees': terminees,
        'temps_moyen': temps_moyen,
        'taux_completion': taux_completion
    }


def _generer_predictions(demandes_base, tendances):
    """Génère des prédictions basées sur les tendances"""
    
    predictions = {
        'charge_travail_prevue': '',
        'goulots_potentiels': [],
        'recommandations': []
    }
    
    # Prédiction de charge de travail
    if tendances.get('total', {}).get('tendance') == 'hausse':
        evolution = tendances['total']['evolution_pourcentage']
        if evolution > 20:
            predictions['charge_travail_prevue'] = f"Forte augmentation prévue (+{evolution:.1f}%)"
        else:
            predictions['charge_travail_prevue'] = f"Augmentation modérée prévue (+{evolution:.1f}%)"
    elif tendances.get('total', {}).get('tendance') == 'baisse':
        evolution = abs(tendances['total']['evolution_pourcentage'])
        predictions['charge_travail_prevue'] = f"Diminution prévue (-{evolution:.1f}%)"
    else:
        predictions['charge_travail_prevue'] = "Charge de travail stable"
    
    # Recommandations basées sur les tendances
    if tendances.get('taux_completion', {}).get('tendance') == 'baisse':
        predictions['recommandations'].append(
            "Améliorer le processus de validation pour augmenter le taux de completion"
        )
    
    if tendances.get('temps_moyen', {}).get('tendance') == 'hausse':
        predictions['recommandations'].append(
            "Analyser les causes d'allongement des délais de traitement"
        )
    
    return predictions


def _obtenir_departements_workflow(profil_utilisateur, peut_voir_tout):
    """Obtient les départements accessibles pour les filtres"""
    if peut_voir_tout:
        return Departement.objects.filter(actif=True).order_by('nom')
    elif profil_utilisateur.departement:
        return Departement.objects.filter(id=profil_utilisateur.departement.id)
    else:
        return Departement.objects.none()


def _obtenir_sites_workflow(profil_utilisateur, peut_voir_tout):
    """Obtient les sites accessibles pour les filtres"""
    if peut_voir_tout:
        return Site.objects.filter(actif=True).order_by('nom')
    elif profil_utilisateur.site:
        return Site.objects.filter(id=profil_utilisateur.site.id)
    else:
        return Site.objects.none()


def _obtenir_periodes_predefinies(reference_date):
    """Obtient les périodes prédéfinies pour les filtres"""
    return [
        {
            'label': 'Cette semaine',
            'type': 'semaine',
            'debut': reference_date - timedelta(days=reference_date.weekday()),
            'fin': reference_date - timedelta(days=reference_date.weekday()) + timedelta(days=6)
        },
        {
            'label': 'Ce mois',
            'type': 'mois',
            'debut': reference_date.replace(day=1),
            'fin': reference_date
        },
        {
            'label': '30 derniers jours',
            'type': 'personnalise',
            'debut': reference_date - timedelta(days=29),
            'fin': reference_date
        },
        {
            'label': 'Ce trimestre',
            'type': 'trimestre',
            'debut': date(reference_date.year, ((reference_date.month - 1) // 3) * 3 + 1, 1),
            'fin': reference_date
        }
    ]


@login_required
def mes_notifications(request):
    """Liste des notifications de l'utilisateur avec filtres avancés"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Récupération des filtres
        filtres = {
            'type_notification': request.GET.get('type', ''),
            'urgence': request.GET.get('urgence', ''),
            'statut': request.GET.get('statut', ''),
            'date_debut': request.GET.get('date_debut', ''),
            'date_fin': request.GET.get('date_fin', ''),
            'recherche': request.GET.get('recherche', ''),
            'ordre': request.GET.get('ordre', '-created_at'),
            'niveau_hierarchique': request.GET.get('niveau_hierarchique', '')
        }
        
        # Construction de la requête de base
        notifications_query = NotificationInterim.objects.select_related(
            'expediteur__user',
            'destinataire__user',
            'demande__poste__departement',
            'demande__poste__site',
            'demande__personne_remplacee__user',
            'proposition_liee__candidat_propose__user',
            'proposition_liee__proposant__user',
            'validation_liee__validateur__user'
        ).prefetch_related(
            'demande__propositions_candidats__candidat_propose'
        )
        
        # Filtrer selon le niveau hiérarchique et les permissions
        if profil.is_superuser:
            # Superusers voient toutes les notifications
            notifications = notifications_query.all()
        elif profil.type_profil in ['RH', 'ADMIN']:
            # RH/ADMIN voient toutes les notifications + celles qui leur sont destinées
            notifications = notifications_query.filter(
                Q(destinataire=profil) |
                Q(destinataire__type_profil__in=['UTILISATEUR', 'CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR']) |
                Q(type_notification__in=[
                    'DEMANDE_A_VALIDER', 
                    'VALIDATION_EFFECTUEE',
                    'CANDIDAT_SELECTIONNE',
                    'MISSION_DEMARREE',
                    'MISSION_TERMINEE'
                ])
            ).distinct()
        elif profil.type_profil == 'DIRECTEUR':
            # Directeurs voient leurs notifications + celles de leur niveau et inférieurs
            notifications = notifications_query.filter(
                Q(destinataire=profil) |
                Q(destinataire__departement=profil.departement) |
                Q(destinataire__type_profil__in=['UTILISATEUR', 'CHEF_EQUIPE', 'RESPONSABLE']) |
                Q(demande__poste__departement=profil.departement)
            ).distinct()
        elif profil.type_profil == 'RESPONSABLE':
            # Responsables voient leurs notifications + celles de leur équipe
            notifications = notifications_query.filter(
                Q(destinataire=profil) |
                Q(destinataire__manager=profil) |
                Q(destinataire__departement=profil.departement, 
                  destinataire__type_profil__in=['UTILISATEUR', 'CHEF_EQUIPE']) |
                Q(demande__poste__departement=profil.departement)
            ).distinct()
        else:
            # Autres utilisateurs voient uniquement leurs notifications
            notifications = notifications_query.filter(destinataire=profil)
        
        # Application des filtres
        if filtres['type_notification']:
            notifications = notifications.filter(type_notification=filtres['type_notification'])
        
        if filtres['urgence']:
            notifications = notifications.filter(urgence=filtres['urgence'])
        
        if filtres['statut']:
            notifications = notifications.filter(statut=filtres['statut'])
        
        if filtres['niveau_hierarchique']:
            if filtres['niveau_hierarchique'] == 'EQUIPE':
                # Notifications concernant l'équipe
                notifications = notifications.filter(
                    Q(destinataire__manager=profil) |
                    Q(destinataire__departement=profil.departement)
                )
            elif filtres['niveau_hierarchique'] == 'DEPARTEMENT':
                # Notifications du département
                notifications = notifications.filter(
                    Q(demande__poste__departement=profil.departement) |
                    Q(destinataire__departement=profil.departement)
                )
            elif filtres['niveau_hierarchique'] == 'SITE':
                # Notifications du site
                notifications = notifications.filter(
                    Q(demande__poste__site=profil.site) |
                    Q(destinataire__site=profil.site)
                )
        
        # Filtres de date
        if filtres['date_debut']:
            try:
                date_debut = datetime.strptime(filtres['date_debut'], '%Y-%m-%d').date()
                notifications = notifications.filter(created_at__date__gte=date_debut)
            except ValueError:
                pass
        
        if filtres['date_fin']:
            try:
                date_fin = datetime.strptime(filtres['date_fin'], '%Y-%m-%d').date()
                notifications = notifications.filter(created_at__date__lte=date_fin)
            except ValueError:
                pass
        
        # Recherche textuelle
        if filtres['recherche']:
            recherche = filtres['recherche'].strip()
            notifications = notifications.filter(
                Q(titre__icontains=recherche) |
                Q(message__icontains=recherche) |
                Q(demande__numero_demande__icontains=recherche) |
                Q(expediteur__user__first_name__icontains=recherche) |
                Q(expediteur__user__last_name__icontains=recherche) |
                Q(expediteur__matricule__icontains=recherche) |
                Q(proposition_liee__candidat_propose__user__first_name__icontains=recherche) |
                Q(proposition_liee__candidat_propose__user__last_name__icontains=recherche)
            )
        
        # Tri
        ordre_mapping = {
            '-created_at': '-created_at',
            'created_at': 'created_at',
            '-urgence': '-urgence',
            'urgence': 'urgence',
            '-statut': '-statut',
            'statut': 'statut',
            'expediteur': 'expediteur__user__last_name',
            '-expediteur': '-expediteur__user__last_name',
            'type': 'type_notification',
            '-type': '-type_notification'
        }
        
        ordre_final = ordre_mapping.get(filtres['ordre'], '-created_at')
        notifications = notifications.order_by(ordre_final, '-created_at')
        
        # Statistiques avant pagination
        total_notifications = notifications.count()
        
        # Statistiques globales (toutes les notifications de l'utilisateur)
        stats_globales = {
            'total_personnel': profil.notifications_recues.count(),
            'non_lues_personnel': profil.notifications_recues.filter(statut_lecture='NON_LUE').count(),
            'critiques_personnel': profil.notifications_recues.filter(urgence='CRITIQUE').count(),
            'cette_semaine_personnel': profil.notifications_recues.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=7)
            ).count(),
            'total_visibles': total_notifications,
            'non_lues_visibles': notifications.filter(statut_lecture='NON_LUE').count(),
            'critiques_visibles': notifications.filter(urgence='CRITIQUE').count(),
            'cette_semaine_visibles': notifications.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=7)
            ).count()
        }
        
        # Statistiques par type pour la vue actuelle
        stats_par_type = {}
        if total_notifications > 0:
            from django.db.models import Count
            types_count = notifications.values('type_notification').annotate(
                count=Count('id')
            ).order_by('-count')
            
            for item in types_count:
                type_notif = item['type_notification']
                # Obtenir le libellé depuis les choix du modèle
                type_display = dict(NotificationInterim.TYPES_NOTIFICATION).get(type_notif, type_notif)
                stats_par_type[type_display] = item['count']
        
        # Statistiques par urgence
        stats_par_urgence = {}
        if total_notifications > 0:
            urgences_count = notifications.values('urgence').annotate(
                count=Count('id')
            ).order_by('-count')
            
            for item in urgences_count:
                urgence = item['urgence']
                urgence_display = dict(NotificationInterim.URGENCES).get(urgence, urgence)
                stats_par_urgence[urgence_display] = item['count']
        
        # Dates extrêmes
        dates_extremes = {}
        if total_notifications > 0:
            dates_agg = notifications.aggregate(
                premiere=Min('created_at'),
                derniere=Max('created_at')
            )
            dates_extremes = {
                'premiere': dates_agg['premiere'],
                'derniere': dates_agg['derniere']
            }
        
        # Enrichissement des notifications pour affichage
        notifications_enrichies = []
        for notification in notifications:
            item = {
                'notification': notification,
                'expediteur_display': _get_expediteur_display(notification),
                'est_urgente': notification.urgence in ['HAUTE', 'CRITIQUE'],
                'est_recente': (timezone.now() - notification.created_at).days <= 1,
                'temps_depuis_creation': _get_temps_depuis(notification.created_at),
                'actions_disponibles': _get_actions_notification(notification, profil),
                'contexte_demande': _get_contexte_demande(notification),
                'est_ma_notification': notification.destinataire == profil,
                'niveau_hierarchique_expediteur': notification.expediteur.type_profil if notification.expediteur else None,
                'peut_traiter': _peut_traiter_notification(notification, profil)
            }
            notifications_enrichies.append(item)
        
        # Pagination
        paginator = Paginator(notifications_enrichies, 15)
        page_number = request.GET.get('page')
        notifications_page = paginator.get_page(page_number)
        
        # Marquer comme lues les notifications personnelles affichées
        notifications_a_marquer = [
            item['notification'] for item in notifications_page.object_list
            if item['notification'].destinataire == profil and item['notification'].statut_lecture == 'NON_LUE'
        ]
        
        for notification in notifications_a_marquer:
            try:
                notification.marquer_comme_lue()
            except Exception as e:
                logger.warning(f"Impossible de marquer la notification {notification.id} comme lue: {e}")
        
        # Choix pour les filtres
        choix_filtres = {
            'types_notification': NotificationInterim.TYPES_NOTIFICATION,
            'urgences': NotificationInterim.URGENCES,
            'statuts': NotificationInterim.STATUTS,
            'niveaux_hierarchiques': [
                ('', 'Tous les niveaux'),
                ('PERSONNEL', 'Mes notifications personnelles'),
                ('EQUIPE', 'Notifications équipe'),
                ('DEPARTEMENT', 'Notifications département'),
                ('SITE', 'Notifications site'),
            ]
        }
        
        context = {
            'notifications_enrichies': notifications_page,
            'profil_utilisateur': profil,
            'stats_globales': stats_globales,
            'stats_par_type': stats_par_type,
            'stats_par_urgence': stats_par_urgence,
            'dates_extremes': dates_extremes,
            'total_notifications': total_notifications,
            'filtres': filtres,
            'choix_filtres': choix_filtres,
            'peut_voir_equipe': profil.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'] or profil.is_superuser,
            'peut_voir_departement': profil.type_profil in ['DIRECTEUR', 'RH', 'ADMIN'] or profil.is_superuser,
            'peut_voir_tout': profil.type_profil in ['RH', 'ADMIN'] or profil.is_superuser,
        }
        
        return render(request, 'mes_notifications.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        messages.error(request, "Profil utilisateur non trouvé")
        return redirect('index')
    except Exception as e:
        logger.error(f"Erreur dans mes_notifications: {e}")
        messages.error(request, "Une erreur est survenue lors du chargement des notifications")
        return redirect('index')


def _get_expediteur_display(notification):
    """Retourne l'affichage formaté de l'expéditeur"""
    if not notification.expediteur:
        return {
            'nom': 'Système',
            'type': 'SYSTEM',
            'icone': '🤖',
            'badge_class': 'system'
        }
    
    type_icons = {
        'UTILISATEUR': '👤',
        'CHEF_EQUIPE': '👷',
        'RESPONSABLE': '👔',
        'DIRECTEUR': '🏢',
        'RH': '👨‍💼',
        'ADMIN': '⚙️'
    }
    
    badge_classes = {
        'UTILISATEUR': 'user',
        'CHEF_EQUIPE': 'chef',
        'RESPONSABLE': 'responsable',
        'DIRECTEUR': 'directeur',
        'RH': 'rh',
        'ADMIN': 'admin'
    }
    
    return {
        'nom': notification.expediteur.nom_complet,
        'type': notification.expediteur.type_profil,
        'icone': type_icons.get(notification.expediteur.type_profil, '👤'),
        'badge_class': badge_classes.get(notification.expediteur.type_profil, 'user'),
        'est_superuser': notification.expediteur.is_superuser
    }


def _get_temps_depuis(date_creation):
    """Calcule le temps écoulé depuis la création"""
    try:
        delta = timezone.now() - date_creation
        
        if delta.days > 0:
            return f"Il y a {delta.days} jour{'s' if delta.days > 1 else ''}"
        elif delta.seconds > 3600:
            heures = delta.seconds // 3600
            return f"Il y a {heures} heure{'s' if heures > 1 else ''}"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"Il y a {minutes} minute{'s' if minutes > 1 else ''}"
        else:
            return "À l'instant"
    except Exception:
        return "Date inconnue"


def _get_actions_notification(notification, profil):
    """Détermine les actions disponibles pour une notification"""
    actions = []
    
    # Action principale selon le type de notification
    if notification.url_action_principale:
        actions.append({
            'url': notification.url_action_principale,
            'texte': notification.texte_action_principale or 'Voir détail',
            'type': 'primary',
            'icone': 'fas fa-eye'
        })
    elif notification.demande:
        # Fallback vers la demande
        actions.append({
            'url': f'/interim/demande/{notification.demande.id}/',
            'texte': 'Voir la demande',
            'type': 'primary',
            'icone': 'fas fa-file-alt'
        })
    
    # Action secondaire
    if notification.url_action_secondaire:
        actions.append({
            'url': notification.url_action_secondaire,
            'texte': notification.texte_action_secondaire or 'Action',
            'type': 'secondary',
            'icone': 'fas fa-external-link-alt'
        })
    
    # Action de marquage comme traitée
    if notification.statut != 'TRAITEE' and notification.destinataire == profil:
        actions.append({
            'url': f'/interim/notifications/{notification.id}/traiter/',
            'texte': 'Marquer comme traitée',
            'type': 'success',
            'icone': 'fas fa-check',
            'method': 'POST'
        })
    
    return actions


def _get_contexte_demande(notification):
    """Récupère le contexte de la demande associée"""
    if not notification.demande:
        return None
    
    demande = notification.demande
    return {
        'numero': demande.numero_demande,
        'poste': demande.poste.titre if demande.poste else 'Poste non défini',
        'site': demande.poste.site.nom if demande.poste and demande.poste.site else 'Site non défini',
        'departement': demande.poste.departement.nom if demande.poste and demande.poste.departement else 'Département non défini',
        'periode': f"{demande.date_debut.strftime('%d/%m/%Y') if demande.date_debut else '?'} - {demande.date_fin.strftime('%d/%m/%Y') if demande.date_fin else '?'}",
        'urgence': demande.urgence,
        'statut': demande.statut,
        'personne_remplacee': demande.personne_remplacee.nom_complet if demande.personne_remplacee else 'Non définie'
    }


def _peut_traiter_notification(notification, profil):
    """Vérifie si l'utilisateur peut traiter la notification"""
    # L'utilisateur peut traiter ses propres notifications
    if notification.destinataire == profil:
        return True
    
    # Les superusers peuvent traiter toutes les notifications
    if profil.is_superuser:
        return True
    
    # RH/ADMIN peuvent traiter la plupart des notifications
    if profil.type_profil in ['RH', 'ADMIN']:
        return True
    
    # Responsables/Directeurs peuvent traiter les notifications de leur niveau
    if profil.type_profil in ['RESPONSABLE', 'DIRECTEUR']:
        if notification.demande and notification.demande.poste:
            return notification.demande.poste.departement == profil.departement
    
    return False


@login_required
@require_POST
def marquer_notification_traitee(request, notification_id):
    """Marque une notification comme traitée"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        notification = get_object_or_404(NotificationInterim, id=notification_id)
        
        # Vérifier les permissions
        if not _peut_traiter_notification(notification, profil):
            return JsonResponse({
                'success': False, 
                'error': 'Vous n\'avez pas les permissions pour traiter cette notification'
            })
        
        notification.marquer_comme_traitee()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification marquée comme traitée'
        })
        
    except ProfilUtilisateur.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'error': 'Profil utilisateur non trouvé'
        })
    except Exception as e:
        logger.error(f"Erreur marquage notification: {e}")
        return JsonResponse({
            'success': False, 
            'error': 'Une erreur est survenue'
        })


@login_required
@require_POST
def marquer_toutes_notifications_lues(request):
    """Marque toutes les notifications non lues de l'utilisateur comme lues"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        notifications_non_lues = profil.notifications_recues.filter(statut='NON_LUE')
        count = notifications_non_lues.count()
        
        for notification in notifications_non_lues:
            try:
                notification.marquer_comme_lue()
            except:
                pass
        
        return JsonResponse({
            'success': True,
            'count': count,
            'message': f'{count} notification{"s" if count > 1 else ""} marquée{"s" if count > 1 else ""} comme lue{"s" if count > 1 else ""}'
        })
        
    except Exception as e:
        logger.error(f"Erreur marquage toutes notifications: {e}")
        return JsonResponse({
            'success': False, 
            'error': 'Une erreur est survenue'
        })

# ================================================================
# VUES POUR LES ACTIONS EN MASSE
# ================================================================

@login_required
def actions_masse_notifications(request):
    """Version debug pour identifier le problème"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Debug: Log des informations utilisateur
        logger.info(f"🔍 DEBUG - Utilisateur: {profil.nom_complet}, Type: {profil.type_profil}, Superuser: {profil.is_superuser}")
        
        # Vérifier les permissions (RH, Admin ou Superuser)
        if not (profil.type_profil in ['RH', 'ADMIN'] or profil.is_superuser):
            messages.error(request, "Accès non autorisé aux actions en masse")
            return redirect('notifications')
        
        # Debug: Log des paramètres de requête
        logger.info(f"🔍 DEBUG - Méthode: {request.method}")
        if request.method == 'POST':
            logger.info(f"🔍 DEBUG - POST data: {dict(request.POST)}")
        logger.info(f"🔍 DEBUG - GET params: {dict(request.GET)}")
        
        # Récupérer les notifications selon les permissions
        if profil.is_superuser or profil.type_profil in ['RH', 'ADMIN']:
            notifications_query = NotificationInterim.objects.select_related(
                'destinataire__user', 'expediteur__user', 'demande'
            )
            logger.info("🔍 DEBUG - Requête pour superuser/admin: toutes les notifications")
        else:
            notifications_query = NotificationInterim.objects.filter(
                destinataire=profil
            ).select_related('expediteur__user', 'demande')
            logger.info(f"🔍 DEBUG - Requête pour utilisateur normal: notifications pour {profil.nom_complet}")
        
        # Debug: Compter les notifications de base
        total_notifications = notifications_query.count()
        logger.info(f"🔍 DEBUG - Total notifications disponibles: {total_notifications}")
        
        # Filtres pour les actions en masse
        filtres = {
            'statut': request.GET.get('statut', ''),
            'urgence': request.GET.get('urgence', ''),
            'type_notification': request.GET.get('type', ''),
            'date_debut': request.GET.get('date_debut', ''),
            'date_fin': request.GET.get('date_fin', ''),
            'destinataire': request.GET.get('destinataire', ''),
        }
        
        logger.info(f"🔍 DEBUG - Filtres appliqués: {filtres}")
        
        # Appliquer les filtres
        notifications = notifications_query.all()
        
        if filtres['statut']:
            notifications = notifications.filter(statut=filtres['statut'])
            logger.info(f"🔍 DEBUG - Après filtre statut '{filtres['statut']}': {notifications.count()}")
        
        if filtres['urgence']:
            notifications = notifications.filter(urgence=filtres['urgence'])
            logger.info(f"🔍 DEBUG - Après filtre urgence '{filtres['urgence']}': {notifications.count()}")
            
        if filtres['type_notification']:
            notifications = notifications.filter(type_notification=filtres['type_notification'])
            logger.info(f"🔍 DEBUG - Après filtre type '{filtres['type_notification']}': {notifications.count()}")
        
        if filtres['date_debut']:
            try:
                date_debut = datetime.strptime(filtres['date_debut'], '%Y-%m-%d').date()
                notifications = notifications.filter(created_at__date__gte=date_debut)
                logger.info(f"🔍 DEBUG - Après filtre date début '{date_debut}': {notifications.count()}")
            except ValueError:
                logger.warning(f"🔍 DEBUG - Date début invalide: {filtres['date_debut']}")
        
        if filtres['date_fin']:
            try:
                date_fin = datetime.strptime(filtres['date_fin'], '%Y-%m-%d').date()
                notifications = notifications.filter(created_at__date__lte=date_fin)
                logger.info(f"🔍 DEBUG - Après filtre date fin '{date_fin}': {notifications.count()}")
            except ValueError:
                logger.warning(f"🔍 DEBUG - Date fin invalide: {filtres['date_fin']}")
        
        if filtres['destinataire']:
            notifications = notifications.filter(
                Q(destinataire__user__first_name__icontains=filtres['destinataire']) |
                Q(destinataire__user__last_name__icontains=filtres['destinataire']) |
                Q(destinataire__matricule__icontains=filtres['destinataire'])
            )
            logger.info(f"🔍 DEBUG - Après filtre destinataire '{filtres['destinataire']}': {notifications.count()}")
        
        # Debug: Afficher quelques exemples de notifications
        sample_notifications = list(notifications[:5])
        for i, notif in enumerate(sample_notifications):
            logger.info(f"🔍 DEBUG - Notification {i+1}: ID={notif.id}, Titre='{notif.titre}', Statut={notif.statut}")
        
        # Traitement des actions en masse
        if request.method == 'POST':
            action = request.POST.get('action')
            notifications_ids = request.POST.getlist('notifications_ids')
            
            logger.info(f"🔍 DEBUG - Action demandée: {action}")
            logger.info(f"🔍 DEBUG - IDs reçus (bruts): {notifications_ids}")
            logger.info(f"🔍 DEBUG - Type des IDs: {[type(id) for id in notifications_ids]}")
            logger.info(f"🔍 DEBUG - Longueur de la liste: {len(notifications_ids)}")
            
            # Vérification plus détaillée des IDs
            if not notifications_ids:
                logger.warning("🔍 DEBUG - Liste des IDs est vide")
                messages.warning(request, "⚠️ Aucune notification sélectionnée. Veuillez cocher au moins une notification avant d'effectuer une action.")
                context = _prepare_context_data_debug(notifications, profil, filtres, request)
                return render(request, 'actions_masse_notifications.html', context)
            
            # Debug: Analyser chaque ID
            valid_ids = []
            invalid_ids = []
            for notif_id in notifications_ids:
                logger.info(f"🔍 DEBUG - Traitement ID: '{notif_id}' (type: {type(notif_id)})")
                try:
                    int_id = int(notif_id)
                    valid_ids.append(int_id)
                    logger.info(f"🔍 DEBUG - ID valide: {int_id}")
                except (ValueError, TypeError) as e:
                    invalid_ids.append(notif_id)
                    logger.error(f"🔍 DEBUG - ID invalide '{notif_id}': {e}")
            
            logger.info(f"🔍 DEBUG - IDs valides: {valid_ids}")
            logger.info(f"🔍 DEBUG - IDs invalides: {invalid_ids}")
            
            if not valid_ids:
                logger.error("🔍 DEBUG - Aucun ID valide après conversion")
                messages.error(request, "❌ Aucune notification valide sélectionnée.")
                context = _prepare_context_data_debug(notifications, profil, filtres, request)
                return render(request, 'actions_masse_notifications.html', context)
            
            # Vérifier l'existence des notifications
            notifications_selectionnees = notifications.filter(id__in=valid_ids)
            count_found = notifications_selectionnees.count()
            
            logger.info(f"🔍 DEBUG - Notifications trouvées: {count_found}/{len(valid_ids)}")
            
            # Debug: Lister les notifications trouvées
            found_notifications = list(notifications_selectionnees)
            for notif in found_notifications:
                logger.info(f"🔍 DEBUG - Notification trouvée: ID={notif.id}, Titre='{notif.titre}'")
            
            if count_found == 0:
                logger.error("🔍 DEBUG - Aucune notification trouvée avec les IDs fournis")
                # Debug: Vérifier si les IDs existent dans la base mais pas dans le queryset filtré
                all_notifications_with_ids = NotificationInterim.objects.filter(id__in=valid_ids)
                if all_notifications_with_ids.exists():
                    logger.warning(f"🔍 DEBUG - Les IDs existent en base mais pas dans le queryset filtré!")
                    logger.warning(f"🔍 DEBUG - Notifications en base: {list(all_notifications_with_ids.values_list('id', 'titre'))}")
                else:
                    logger.warning(f"🔍 DEBUG - Les IDs n'existent pas du tout en base")
                
                messages.error(request, "❌ Aucune des notifications sélectionnées n'a pu être trouvée.")
                context = _prepare_context_data_debug(notifications, profil, filtres, request)
                return render(request, 'actions_masse_notifications.html', context)
            
            # Exécuter l'action
            logger.info(f"🔍 DEBUG - Exécution de l'action '{action}' sur {count_found} notifications")
            
            try:
                success_count = 0
                error_count = 0
                
                if action == 'marquer_lues':
                    for notification in notifications_selectionnees:
                        try:
                            old_status = notification.statut
                            if notification.statut_lecture == 'NON_LUE':
                                notification.marquer_comme_lue()
                                logger.info(f"🔍 DEBUG - Notification {notification.id} marquée comme lue")
                                success_count += 1
                            else:
                                logger.info(f"🔍 DEBUG - Notification {notification.id} déjà lue (statut: {old_status})")
                                success_count += 1
                        except Exception as e:
                            logger.error(f"🔍 DEBUG - Erreur marquage lecture notification {notification.id}: {e}")
                            error_count += 1
                    
                    if error_count == 0:
                        messages.success(request, f"✅ {success_count} notification(s) marquée(s) comme lue(s)")
                    else:
                        messages.warning(request, f"⚠️ {success_count} notification(s) traitée(s), {error_count} erreur(s)")
                
                elif action == 'marquer_traitees':
                    for notification in notifications_selectionnees:
                        try:
                            old_status = notification.statut
                            notification.marquer_comme_traitee()
                            logger.info(f"🔍 DEBUG - Notification {notification.id} marquée comme traitée (ancien statut: {old_status})")
                            success_count += 1
                        except Exception as e:
                            logger.error(f"🔍 DEBUG - Erreur marquage traitement notification {notification.id}: {e}")
                            error_count += 1
                    
                    if error_count == 0:
                        messages.success(request, f"✅ {success_count} notification(s) marquée(s) comme traitée(s)")
                    else:
                        messages.warning(request, f"⚠️ {success_count} notification(s) traitée(s), {error_count} erreur(s)")
                
                elif action == 'archiver':
                    updated_count = notifications_selectionnees.update(statut='ARCHIVEE')
                    logger.info(f"🔍 DEBUG - {updated_count} notifications archivées")
                    messages.success(request, f"📦 {updated_count} notification(s) archivée(s)")
                
                elif action == 'supprimer' and (profil.is_superuser or profil.type_profil == 'ADMIN'):
                    deleted_count, details = notifications_selectionnees.delete()
                    logger.info(f"🔍 DEBUG - {deleted_count} notifications supprimées: {details}")
                    messages.success(request, f"🗑️ {deleted_count} notification(s) supprimée(s) définitivement")
                
                else:
                    logger.error(f"🔍 DEBUG - Action non autorisée: {action}")
                    messages.error(request, "❌ Action non autorisée ou invalide")
                
                # Redirection avec préservation des filtres
                redirect_url = request.path
                params = []
                for key, value in filtres.items():
                    if value:
                        params.append(f"{key}={value}")
                
                if params:
                    redirect_url += "?" + "&".join(params)
                
                logger.info(f"🔍 DEBUG - Redirection vers: {redirect_url}")
                return redirect(redirect_url)
                
            except Exception as e:
                logger.error(f"🔍 DEBUG - Erreur lors de l'exécution de l'action: {e}")
                messages.error(request, f"❌ Erreur lors de l'exécution de l'action: {str(e)}")
        
        # Préparer le contexte pour l'affichage
        context = _prepare_context_data_debug(notifications, profil, filtres, request)
        logger.info(f"🔍 DEBUG - Contexte préparé avec {context['notifications'].paginator.count} notifications")
        
        return render(request, 'actions_masse_notifications.html', context)
        
    except ProfilUtilisateur.DoesNotExist:
        logger.error("🔍 DEBUG - Profil utilisateur non trouvé")
        messages.error(request, "❌ Profil utilisateur non trouvé")
        return redirect('index')
    except Exception as e:
        logger.error(f"🔍 DEBUG - Erreur générale: {e}")
        messages.error(request, f"❌ Une erreur est survenue: {str(e)}")
        return redirect('notifications')

def _prepare_context_data_debug(notifications, profil, filtres, request):
    """Version debug de la préparation du contexte"""
    try:
        logger.info("🔍 DEBUG - Préparation du contexte...")
        
        # Statistiques
        stats = {
            'total': notifications.count(),
            'non_lues': notifications.filter(statut_lecture='NON_LUE').count(),
            'lues': notifications.filter(statut_lecture='LUE').count(),
            'traitees': notifications.filter(statut='TRAITEE').count(),
            'critiques': notifications.filter(urgence='CRITIQUE').count(),
        }
        
        logger.info(f"🔍 DEBUG - Statistiques: {stats}")
        
        # Pagination
        paginator = Paginator(notifications.order_by('-created_at'), 50)
        page_number = request.GET.get('page', 1)
        notifications_page = paginator.get_page(page_number)
        
        logger.info(f"🔍 DEBUG - Pagination: page {page_number}, {len(notifications_page)} notifications sur la page")
        
        # Choix pour les filtres
        choix_filtres = {
            'statuts': NotificationInterim.STATUTS,
            'urgences': NotificationInterim.URGENCES,
            'types_notification': NotificationInterim.TYPES_NOTIFICATION,
        }
        
        # Liste des utilisateurs pour le filtre destinataire
        utilisateurs = ProfilUtilisateur.objects.select_related('user').filter(
            actif=True
        ).order_by('user__last_name', 'user__first_name')[:100]
        
        context = {
            'notifications': notifications_page,
            'profil_utilisateur': profil,
            'stats': stats,
            'filtres': filtres,
            'choix_filtres': choix_filtres,
            'utilisateurs': utilisateurs,
            'peut_supprimer': profil.is_superuser or profil.type_profil == 'ADMIN',
        }
        
        logger.info("🔍 DEBUG - Contexte préparé avec succès")
        return context
        
    except Exception as e:
        logger.error(f"🔍 DEBUG - Erreur préparation contexte: {e}")
        return {
            'notifications': [],
            'profil_utilisateur': profil,
            'stats': {'total': 0, 'non_lues': 0, 'lues': 0, 'traitees': 0, 'critiques': 0},
            'filtres': filtres,
            'choix_filtres': {'statuts': [], 'urgences': [], 'types_notification': []},
            'utilisateurs': [],
            'peut_supprimer': False,
        }

# NOUVELLE VUE AJAX : Diagnostic en temps réel
@require_http_methods(["POST"])
@login_required
@csrf_exempt
def diagnostic_selection_notifications(request):
    """Diagnostic en temps réel des sélections"""
    try:
        import json
        data = json.loads(request.body.decode('utf-8'))
        notifications_ids = data.get('notifications_ids', [])
        
        logger.info(f"🔍 DIAGNOSTIC - IDs reçus: {notifications_ids}")
        
        # Analyser les IDs
        diagnostic = {
            'ids_reçus': notifications_ids,
            'total_reçu': len(notifications_ids),
            'ids_valides': [],
            'ids_invalides': [],
            'notifications_trouvées': [],
            'notifications_manquantes': []
        }
        
        for notif_id in notifications_ids:
            try:
                int_id = int(notif_id)
                diagnostic['ids_valides'].append(int_id)
            except (ValueError, TypeError):
                diagnostic['ids_invalides'].append(notif_id)
        
        # Vérifier l'existence en base
        if diagnostic['ids_valides']:
            notifications_existantes = NotificationInterim.objects.filter(
                id__in=diagnostic['ids_valides']
            ).values_list('id', 'titre', 'statut')
            
            for notif in notifications_existantes:
                diagnostic['notifications_trouvées'].append({
                    'id': notif[0],
                    'titre': notif[1],
                    'statut': notif[2]
                })
            
            ids_trouvés = [notif[0] for notif in notifications_existantes]
            diagnostic['notifications_manquantes'] = [
                id for id in diagnostic['ids_valides'] 
                if id not in ids_trouvés
            ]
        
        logger.info(f"🔍 DIAGNOSTIC - Résultat: {diagnostic}")
        
        return JsonResponse({
            'success': True,
            'diagnostic': diagnostic,
            'message': f"Diagnostic: {len(diagnostic['notifications_trouvées'])} notifications trouvées sur {len(diagnostic['ids_valides'])} IDs valides"
        })
        
    except Exception as e:
        logger.error(f"🔍 DIAGNOSTIC - Erreur: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ================================================================
# VUES POUR LES ACTIONS INDIVIDUELLES
# ================================================================

@login_required
@require_POST
def marquer_notification_lue(request, notification_id):
    """Marque une notification comme lue"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        notification = get_object_or_404(NotificationInterim, id=notification_id)
        
        # Vérifier les permissions
        if not _peut_traiter_notification(notification, profil):
            return JsonResponse({
                'success': False, 
                'error': 'Permissions insuffisantes'
            })
        
        if notification.statut_lecture == 'NON_LUE':
            notification.marquer_comme_lue()
            return JsonResponse({
                'success': True,
                'message': 'Notification marquée comme lue'
            })
        else:
            return JsonResponse({
                'success': True,
                'message': 'Notification déjà lue'
            })
        
    except Exception as e:
        logger.error(f"Erreur marquer notification lue: {e}")
        return JsonResponse({
            'success': False, 
            'error': 'Une erreur est survenue'
        })


@login_required
@require_POST  
def archiver_notification(request, notification_id):
    """Archive une notification"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        notification = get_object_or_404(NotificationInterim, id=notification_id)
        
        # Vérifier les permissions
        if not _peut_traiter_notification(notification, profil):
            return JsonResponse({
                'success': False, 
                'error': 'Permissions insuffisantes'
            })
        
        notification.statut = 'ARCHIVEE'
        notification.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification archivée'
        })
        
    except Exception as e:
        logger.error(f"Erreur archiver notification: {e}")
        return JsonResponse({
            'success': False, 
            'error': 'Une erreur est survenue'
        })


@login_required
@require_POST
def supprimer_notification(request, notification_id):
    """Supprime une notification (admin seulement)"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        
        # Vérifier les permissions (Admin/Superuser seulement)
        if not (profil.type_profil == 'ADMIN' or profil.is_superuser):
            return JsonResponse({
                'success': False, 
                'error': 'Action non autorisée'
            })
        
        notification = get_object_or_404(NotificationInterim, id=notification_id)
        notification.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification supprimée'
        })
        
    except Exception as e:
        logger.error(f"Erreur supprimer notification: {e}")
        return JsonResponse({
            'success': False, 
            'error': 'Une erreur est survenue'
        })

# ================================================================
# VUES API POUR AJAX
# ================================================================

@login_required
def api_count_notifications_non_lues(request):
    """API pour compter les notifications non lues"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        count = profil.notifications_recues.filter(statut='NON_LUE').count()
        
        return JsonResponse({
            'success': True,
            'count': count
        })
        
    except Exception as e:
        logger.error(f"Erreur API count notifications: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors du comptage'
        })


@login_required
def api_notifications_recentes(request):
    """API pour récupérer les dernières notifications"""
    try:
        profil = ProfilUtilisateur.objects.get(user=request.user)
        limit = int(request.GET.get('limit', 5))
        
        notifications = profil.notifications_recues.select_related(
            'expediteur__user', 'demande'
        ).order_by('-created_at')[:limit]
        
        data = []
        for notification in notifications:
            data.append({
                'id': notification.id,
                'titre': notification.titre,
                'message': notification.message[:100] + '...' if len(notification.message) > 100 else notification.message,
                'urgence': notification.urgence,
                'statut': notification.statut,
                'created_at': notification.created_at.isoformat(),
                'expediteur': notification.expediteur.nom_complet if notification.expediteur else 'Système',
                'url_action': notification.url_action_principale or f'/demandes/{notification.demande.id}/' if notification.demande else '#'
            })
        
        return JsonResponse({
            'success': True,
            'notifications': data
        })
        
    except Exception as e:
        logger.error(f"Erreur API notifications récentes: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Erreur lors de la récupération'
        })
