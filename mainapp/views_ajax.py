# -*- coding: utf-8 -*-
"""
Views AJAX pour le système d'intérim - Support complet matricule
Compatible avec interim_validation.html et models.py corrigés
Recherche par matricule + scores détaillés + workflow
"""

import json
import logging
from datetime import datetime, timedelta, date
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Prefetch
from django.contrib.auth.models import User


from .models import (
    ProfilUtilisateur, DemandeInterim, PropositionCandidat, 
    ScoreDetailCandidat, NotificationInterim, HistoriqueAction,
    ValidationDemande, ConfigurationScoring
)


# Configuration logging
logger = logging.getLogger(__name__)


# ================================================================
# UTILITAIRES POUR LES RÉPONSES JSON
# ================================================================

def json_success(message="Succès", data=None, status=200):
    """Réponse JSON de succès standardisée"""
    response_data = {
        'success': True,
        'message': message,
        'timestamp': timezone.now().isoformat()
    }
    if data is not None:
        response_data['data'] = data
    return JsonResponse(response_data, status=status)

def json_error(message="Erreur", errors=None, status=400):
    """Réponse JSON d'erreur standardisée"""
    response_data = {
        'success': False,
        'message': message,
        'timestamp': timezone.now().isoformat()
    }
    if errors:
        response_data['errors'] = errors
    return JsonResponse(response_data, status=status)

def safe_decimal_to_float(value):
    """Conversion sécurisée Decimal vers float"""
    try:
        if isinstance(value, Decimal):
            return float(value)
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0

def safe_int(value, default=0):
    """Conversion sécurisée vers int"""
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default

# ================================================================
# SCORES AUTOMATIQUES ET DÉTAILLÉS PAR MATRICULE
# ================================================================

@login_required
@require_http_methods(["GET"])
def candidat_score_automatique_by_matricule(request, candidat_matricule, demande_id):
    """
    Score automatique d'un candidat par matricule pour une demande
    Compatible avec le template interim_validation.html
    """
    try:
        logger.info(f"Score automatique candidat matricule {candidat_matricule} pour demande {demande_id}")
        
        # Récupérer la demande
        demande = get_object_or_404(
            DemandeInterim.objects.select_related('poste__departement', 'poste__site'),
            id=demande_id
        )
        
        # Récupérer le candidat par matricule
        try:
            candidat = ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste'
            ).prefetch_related(
                'competences__competence',
                'extended_data'
            ).get(matricule=candidat_matricule, actif=True)
        except ProfilUtilisateur.DoesNotExist:
            return json_error(f"Candidat avec matricule '{candidat_matricule}' non trouvé", status=404)
        
        # Calculer le score automatique
        score_data = calculer_score_automatique(candidat, demande)
        
        # Préparer la réponse
        response_data = {
            'candidat': {
                'id': candidat.id,
                'matricule': candidat.matricule,
                'nom_complet': candidat.nom_complet,
                'poste_actuel': candidat.poste.titre if candidat.poste else None,
                'departement': candidat.departement.nom if candidat.departement else None,
                'site': candidat.site.nom if candidat.site else None
            },
            'score': {
                'score_final': score_data['score_final'],
                'score_base': score_data['score_base'],
                'bonus_total': score_data['bonus_total'],
                'penalites_total': score_data['penalites_total'],
                'classe_score': get_score_class(score_data['score_final']),
                'confiance': score_data.get('confiance', 'Moyenne')
            },
            'criteres': score_data['criteres'],
            'modificateurs': score_data['modificateurs'],
            'disponibilite': score_data['disponibilite'],
            'metadonnees': {
                'date_calcul': timezone.now().isoformat(),
                'version_algorithme': 'v4.1',
                'source_donnees': 'Automatique',
                'calcule_par': 'Système'
            }
        }
        
        return json_success("Score automatique calculé", response_data)
        
    except Exception as e:
        logger.error(f"Erreur calcul score automatique matricule {candidat_matricule}: {e}")
        return json_error(f"Erreur lors du calcul du score: {str(e)}")

@login_required
@require_http_methods(["GET"])
def candidat_score_details_by_matricule(request, candidat_matricule, demande_id):
    """
    Score détaillé général d'un candidat par matricule
    Utilisé par la modale de détails des scores dans interim_validation.html
    """
    try:
        logger.info(f"Score détaillé candidat matricule {candidat_matricule} pour demande {demande_id}")
        
        # Récupérer la demande
        demande = get_object_or_404(
            DemandeInterim.objects.select_related('poste__departement', 'poste__site'),
            id=demande_id
        )
        
        # Récupérer le candidat par matricule
        try:
            candidat = ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste'
            ).prefetch_related(
                'competences__competence',
                'extended_data',
                'scores_details'
            ).get(matricule=candidat_matricule, actif=True)
        except ProfilUtilisateur.DoesNotExist:
            return json_error(f"Candidat avec matricule '{candidat_matricule}' non trouvé", status=404)
        
        # Récupérer ou calculer le score détaillé
        score_detail = ScoreDetailCandidat.objects.filter(
            candidat=candidat,
            demande_interim=demande
        ).first()
        
        if not score_detail:
            # Calculer le score si pas encore fait
            score_data = calculer_score_complet(candidat, demande)
            score_detail = creer_score_detail(candidat, demande, score_data)
        
        # Préparer les données détaillées pour la modale
        response_data = {
            'candidat_nom': candidat.nom_complet,
            'candidat_matricule': candidat.matricule,
            'score_final': score_detail.score_total,
            'type_calcul': score_detail.get_calcule_par_display(),
            'confiance': determiner_confiance_score(score_detail),
            
            # Critères détaillés
            'criteres': {
                'competences': score_detail.score_competences,
                'experience': score_detail.score_experience,
                'disponibilite': score_detail.score_disponibilite,
                'proximite': score_detail.score_proximite,
                'similarite_poste': score_detail.score_similarite_poste,
                'anciennete': score_detail.score_anciennete
            },
            
            # Modificateurs
            'modificateurs': {
                'bonus': {
                    'proposition_humaine': score_detail.bonus_proposition_humaine,
                    'experience_similaire': score_detail.bonus_experience_similaire,
                    'recommandation': score_detail.bonus_recommandation,
                    'hierarchique': score_detail.bonus_hierarchique
                },
                'penalites': {
                    'indisponibilite': score_detail.penalite_indisponibilite
                }
            },
            
            # Commentaires d'évaluation
            'commentaires': recuperer_commentaires_evaluation(candidat, demande),
            
            # Métadonnées
            'metadonnees': {
                'date_calcul': score_detail.created_at.isoformat() if score_detail.created_at else None,
                'derniere_maj': score_detail.updated_at.isoformat() if score_detail.updated_at else None,
                'version_algorithme': 'v4.1',
                'source_donnees': 'Détaillé',
                'calcule_par': score_detail.get_calcule_par_display(),
                'fiabilite': determiner_fiabilite_score(score_detail),
                'duree_calcul': 'Instantané'
            }
        }
        
        return json_success("Score détaillé récupéré", response_data)
        
    except Exception as e:
        logger.error(f"Erreur récupération score détaillé matricule {candidat_matricule}: {e}")
        return json_error(f"Erreur lors de la récupération des détails: {str(e)}")

@login_required
@require_http_methods(["GET"])
def proposition_score_details(request, proposition_id):
    """
    Score détaillé d'une proposition spécifique
    Utilisé par les boutons "Détails" des propositions dans interim_validation.html
    """
    try:
        logger.info(f"Score détaillé proposition {proposition_id}")
        
        # Récupérer la proposition
        proposition = get_object_or_404(
            PropositionCandidat.objects.select_related(
                'candidat_propose__user',
                'candidat_propose__departement',
                'candidat_propose__site',
                'candidat_propose__poste',
                'demande_interim__poste',
                'proposant__user'
            ),
            id=proposition_id
        )
        
        candidat = proposition.candidat_propose
        demande = proposition.demande_interim
        
        # Récupérer le score détaillé
        score_detail = ScoreDetailCandidat.objects.filter(
            candidat=candidat,
            demande_interim=demande,
            proposition_humaine=proposition
        ).first()
        
        if not score_detail:
            # Calculer le score si pas encore fait
            score_data = calculer_score_proposition(candidat, demande, proposition)
            score_detail = creer_score_detail(candidat, demande, score_data, proposition)
        
        # Préparer les données avec informations de proposition
        response_data = {
            'candidat_nom': candidat.nom_complet,
            'candidat_matricule': candidat.matricule,
            'score_final': proposition.score_final or score_detail.score_total,
            'type_calcul': f"Proposition {proposition.get_source_proposition_display()}",
            'confiance': 'Élevée',  # Les propositions humaines ont une confiance élevée
            
            # Critères avec boost de proposition
            'criteres': {
                'competences': score_detail.score_competences,
                'experience': score_detail.score_experience,
                'disponibilite': score_detail.score_disponibilite,
                'proximite': score_detail.score_proximite,
                'similarite_poste': score_detail.score_similarite_poste,
                'anciennete': score_detail.score_anciennete
            },
            
            # Modificateurs avec bonus hiérarchique
            'modificateurs': {
                'bonus': {
                    'proposition_humaine': proposition.bonus_proposition_humaine,
                    'experience_similaire': score_detail.bonus_experience_similaire,
                    'recommandation': score_detail.bonus_recommandation,
                    'hierarchique': score_detail.bonus_hierarchique
                },
                'penalites': {
                    'indisponibilite': score_detail.penalite_indisponibilite
                }
            },
            
            # Commentaires avec justification de proposition
            'commentaires': recuperer_commentaires_proposition(proposition),
            
            # Métadonnées spécifiques à la proposition
            'metadonnees': {
                'date_proposition': proposition.created_at.isoformat(),
                'proposant': proposition.proposant.nom_complet,
                'source_proposition': proposition.get_source_proposition_display(),
                'justification': proposition.justification,
                'version_algorithme': 'v4.1',
                'calcule_par': 'Proposition humaine',
                'fiabilite': 'Élevée'
            }
        }
        
        return json_success("Score de proposition récupéré", response_data)
        
    except Exception as e:
        logger.error(f"Erreur récupération score proposition {proposition_id}: {e}")
        return json_error(f"Erreur lors de la récupération: {str(e)}")

# ================================================================
# RECHERCHE DE CANDIDAT ALTERNATIF PAR MATRICULE
# ================================================================

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def rechercher_candidat_alternatif(request):
    """
    Recherche de candidat alternatif par matricule
    Compatible avec la fonction rechercherCandidatAlternatif() du template
    """
    try:
        # Parser les données JSON
        data = json.loads(request.body)
        matricule = data.get('matricule', '').strip()
        demande_id = data.get('demande_id')
        
        if not matricule:
            return json_error("Matricule requis")
        
        if not demande_id:
            return json_error("ID de demande requis")
        
        logger.info(f"Recherche candidat alternatif matricule: {matricule} pour demande {demande_id}")
        
        # Récupérer la demande
        try:
            demande = DemandeInterim.objects.select_related(
                'poste__departement', 'poste__site'
            ).get(id=demande_id)
        except DemandeInterim.DoesNotExist:
            return json_error("Demande non trouvée", status=404)
        
        # Rechercher le candidat par matricule
        try:
            candidat = ProfilUtilisateur.objects.select_related(
                'user', 'departement', 'site', 'poste'
            ).prefetch_related(
                'competences__competence',
                'extended_data'
            ).get(matricule=matricule, actif=True)
        except ProfilUtilisateur.DoesNotExist:
            return json_error(f"Aucun employé trouvé avec le matricule '{matricule}'")
        
        # Vérifier que ce n'est pas la personne à remplacer
        if candidat.id == demande.personne_remplacee.id:
            return json_error("Impossible de proposer la personne à remplacer comme candidat")
        
        # Vérifier qu'il n'est pas déjà proposé
        deja_propose = PropositionCandidat.objects.filter(
            demande_interim=demande,
            candidat_propose=candidat
        ).exists()
        
        if deja_propose:
            return json_error("Ce candidat a déjà été proposé pour cette demande")
        
        # Calculer le score pour cette mission
        score_data = calculer_score_automatique(candidat, demande)
        
        # Vérifier la disponibilité
        disponibilite = candidat.est_disponible_pour_interim(
            demande.date_debut, 
            demande.date_fin
        )
        
        # Préparer les informations du candidat
        employe_data = {
            'id': candidat.id,
            'matricule': candidat.matricule,
            'nom_complet': candidat.nom_complet,
            'poste_actuel': candidat.poste.titre if candidat.poste else "Poste non renseigné",
            'departement': candidat.departement.nom if candidat.departement else "Département non renseigné",
            'site': candidat.site.nom if candidat.site else "Site non renseigné",
            'anciennete': calculer_anciennete_display(candidat),
            'statut': candidat.get_statut_employe_display(),
            'type_profil': candidat.get_type_profil_display(),
            'disponibilite': disponibilite,
            'competences_principales': recuperer_competences_principales(candidat)
        }
        
        response_data = {
            'employe': employe_data,
            'score': score_data['score_final'],
            'score_details': {
                'score_base': score_data['score_base'],
                'bonus_total': score_data['bonus_total'],
                'penalites_total': score_data['penalites_total'],
                'criteres': score_data['criteres']
            },
            'disponibilite': disponibilite,
            'recommandations': generer_recommandations_candidat(candidat, demande, score_data)
        }
        
        return json_success("Candidat trouvé", response_data)
        
    except json.JSONDecodeError:
        return json_error("Format JSON invalide")
    except Exception as e:
        logger.error(f"Erreur recherche candidat alternatif: {e}")
        return json_error(f"Erreur lors de la recherche: {str(e)}")

# ================================================================
# ACTIONS DE WORKFLOW ET COMMUNICATION
# ================================================================

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def demander_informations(request):
    """
    Demande d'informations complémentaires
    Compatible avec la fonction demanderInfos() du template
    """
    try:
        data = json.loads(request.body)
        demande_id = data.get('demande_id')
        informations = data.get('informations', '').strip()
        
        if not demande_id or not informations:
            return json_error("ID de demande et informations requis")
        
        logger.info(f"Demande informations pour demande {demande_id}")
        
        # Récupérer la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Récupérer le profil utilisateur
        try:
            profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        except ProfilUtilisateur.DoesNotExist:
            return json_error("Profil utilisateur non trouvé")
        
        # Créer la notification de demande d'informations
        with transaction.atomic():
            # Notification au demandeur
            NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=profil_utilisateur,
                demande=demande,
                type_notification='DEMANDE_INFORMATIONS',
                urgence='NORMALE',
                titre=f"Demande d'informations - {demande.numero_demande}",
                message=f"Des informations complémentaires sont demandées pour votre demande d'intérim :\n\n{informations}",
                url_action_principale=f"/interim/demande/{demande.id}/",
                texte_action_principale="Voir la demande"
            )
            
            # Ajouter à l'historique
            HistoriqueAction.objects.create(
                demande=demande,
                action='DEMANDE_INFORMATIONS',
                utilisateur=profil_utilisateur,
                description=f"Demande d'informations complémentaires: {informations[:100]}...",
                niveau_hierarchique=profil_utilisateur.type_profil,
                is_superuser=profil_utilisateur.is_superuser,
                donnees_apres={
                    'informations_demandees': informations,
                    'demandeur': profil_utilisateur.nom_complet
                }
            )
        
        return json_success("Demande d'informations envoyée avec succès")
        
    except json.JSONDecodeError:
        return json_error("Format JSON invalide")
    except Exception as e:
        logger.error(f"Erreur demande informations: {e}")
        return json_error(f"Erreur lors de l'envoi: {str(e)}")

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def escalader_validation(request):
    """
    Escalade de validation au niveau supérieur
    Compatible avec la fonction escaladerValidation() du template
    """
    try:
        data = json.loads(request.body)
        demande_id = data.get('demande_id')
        motif = data.get('motif', '').strip()
        
        if not demande_id or not motif:
            return json_error("ID de demande et motif requis")
        
        logger.info(f"Escalade validation pour demande {demande_id}")
        
        # Récupérer la demande
        demande = get_object_or_404(DemandeInterim, id=demande_id)
        
        # Récupérer le profil utilisateur
        try:
            profil_utilisateur = ProfilUtilisateur.objects.get(user=request.user)
        except ProfilUtilisateur.DoesNotExist:
            return json_error("Profil utilisateur non trouvé")
        
        # Vérifier les permissions d'escalade
        if not profil_utilisateur.peut_valider_niveau(demande.niveau_validation_actuel + 1):
            return json_error("Vous n'avez pas les permissions pour escalader cette validation")
        
        # Déterminer le destinataire de l'escalade
        destinataire_escalade = determiner_destinataire_escalade(demande, profil_utilisateur)
        
        if not destinataire_escalade:
            return json_error("Aucun destinataire trouvé pour l'escalade")
        
        # Effectuer l'escalade
        with transaction.atomic():
            # Créer la validation d'escalade
            validation_escalade = ValidationDemande.objects.create(
                demande=demande,
                type_validation=determiner_type_validation_escalade(destinataire_escalade),
                niveau_validation=demande.niveau_validation_actuel + 1,
                validateur=profil_utilisateur,
                decision='ESCALADE',
                commentaire=f"Escalade demandée - Motif: {motif}"
            )
            
            # Notification au niveau supérieur
            NotificationInterim.objects.create(
                destinataire=destinataire_escalade,
                expediteur=profil_utilisateur,
                demande=demande,
                type_notification='ESCALADE_VALIDATION',
                urgence='HAUTE',
                titre=f"Escalade de validation - {demande.numero_demande}",
                message=f"Une demande de validation a été escaladée vers votre niveau.\n\nMotif: {motif}",
                url_action_principale=f"/interim/validation/{demande.id}/",
                texte_action_principale="Traiter la validation"
            )
            
            # Mettre à jour le niveau de validation
            demande.niveau_validation_actuel += 1
            demande.save()
            
            # Historique
            HistoriqueAction.objects.create(
                demande=demande,
                validation=validation_escalade,
                action='ESCALADE_VALIDATION',
                utilisateur=profil_utilisateur,
                description=f"Escalade vers {destinataire_escalade.nom_complet}: {motif}",
                niveau_validation=demande.niveau_validation_actuel,
                niveau_hierarchique=profil_utilisateur.type_profil,
                is_superuser=profil_utilisateur.is_superuser,
                donnees_apres={
                    'motif_escalade': motif,
                    'destinataire': destinataire_escalade.nom_complet,
                    'niveau_precedent': demande.niveau_validation_actuel - 1,
                    'niveau_actuel': demande.niveau_validation_actuel
                }
            )
        
        return json_success(f"Escalade effectuée vers {destinataire_escalade.nom_complet}")
        
    except json.JSONDecodeError:
        return json_error("Format JSON invalide")
    except Exception as e:
        logger.error(f"Erreur escalade validation: {e}")
        return json_error(f"Erreur lors de l'escalade: {str(e)}")

# ================================================================
# FONCTIONS UTILITAIRES POUR LE CALCUL DES SCORES
# ================================================================

def calculer_score_automatique(candidat, demande):
    """
    Calcule le score automatique d'un candidat pour une demande
    Version simplifiée pour les AJAX
    """
    try:
        # Configuration de scoring par défaut
        config = ConfigurationScoring.get_configuration_pour_demande(demande)
        if not config:
            # Configuration par défaut si aucune trouvée
            poids = {
                'competences': 0.25,
                'experience': 0.20,
                'disponibilite': 0.15,
                'proximite': 0.10,
                'similarite_poste': 0.25,
                'anciennete': 0.05
            }
        else:
            poids = config.get_poids_dict()
        
        # Calcul des critères de base
        criteres = {
            'competences': calculer_score_competences(candidat, demande),
            'experience': calculer_score_experience(candidat, demande),
            'disponibilite': calculer_score_disponibilite(candidat, demande),
            'proximite': calculer_score_proximite(candidat, demande),
            'similarite_poste': calculer_score_similarite_poste(candidat, demande),
            'anciennete': calculer_score_anciennete(candidat)
        }
        
        # Score de base pondéré
        score_base = sum(
            criteres[critere] * poids.get(critere, 0)
            for critere in criteres
        )
        
        # Bonus et pénalités
        bonus_total = 0
        penalites_total = 0
        
        # Disponibilité
        disponibilite = candidat.est_disponible_pour_interim(demande.date_debut, demande.date_fin)
        if not disponibilite['disponible']:
            penalites_total += 20
        
        # Score final
        score_final = max(0, min(100, score_base + bonus_total - penalites_total))
        
        return {
            'score_final': round(score_final),
            'score_base': round(score_base),
            'bonus_total': bonus_total,
            'penalites_total': penalites_total,
            'criteres': {k: round(v) for k, v in criteres.items()},
            'modificateurs': {
                'bonus': {},
                'penalites': {'indisponibilite': penalites_total}
            },
            'disponibilite': disponibilite,
            'confiance': 'Moyenne'
        }
        
    except Exception as e:
        logger.error(f"Erreur calcul score automatique: {e}")
        return {
            'score_final': 0,
            'score_base': 0,
            'bonus_total': 0,
            'penalites_total': 0,
            'criteres': {},
            'modificateurs': {'bonus': {}, 'penalites': {}},
            'disponibilite': {'disponible': False, 'raison': 'Erreur calcul'},
            'confiance': 'Faible'
        }

def calculer_score_complet(candidat, demande):
    """Version complète du calcul de score"""
    return calculer_score_automatique(candidat, demande)

def calculer_score_proposition(candidat, demande, proposition):
    """Calcul du score avec bonus de proposition humaine"""
    score_data = calculer_score_automatique(candidat, demande)
    
    # Ajouter les bonus de proposition
    score_data['bonus_total'] += proposition.bonus_proposition_humaine
    score_data['modificateurs']['bonus']['proposition_humaine'] = proposition.bonus_proposition_humaine
    
    # Recalculer le score final
    score_data['score_final'] = max(0, min(100, 
        score_data['score_base'] + score_data['bonus_total'] - score_data['penalites_total']
    ))
    
    score_data['confiance'] = 'Élevée'
    
    return score_data

def creer_score_detail(candidat, demande, score_data, proposition=None):
    """Crée un ScoreDetailCandidat à partir des données calculées"""
    try:
        score_detail = ScoreDetailCandidat.objects.create(
            candidat=candidat,
            demande_interim=demande,
            proposition_humaine=proposition,
            score_similarite_poste=score_data['criteres'].get('similarite_poste', 0),
            score_competences=score_data['criteres'].get('competences', 0),
            score_disponibilite=score_data['criteres'].get('disponibilite', 0),
            score_proximite=score_data['criteres'].get('proximite', 0),
            score_anciennete=score_data['criteres'].get('anciennete', 0),
            score_experience=score_data['criteres'].get('experience', 0),
            bonus_proposition_humaine=score_data['modificateurs']['bonus'].get('proposition_humaine', 0),
            bonus_experience_similaire=score_data['modificateurs']['bonus'].get('experience_similaire', 0),
            bonus_recommandation=score_data['modificateurs']['bonus'].get('recommandation', 0),
            bonus_hierarchique=score_data['modificateurs']['bonus'].get('hierarchique', 0),
            penalite_indisponibilite=score_data['modificateurs']['penalites'].get('indisponibilite', 0),
            calcule_par='AUTOMATIQUE' if not proposition else 'HUMAIN'
        )
        score_detail.calculer_score_total()
        score_detail.save()
        return score_detail
    except Exception as e:
        logger.error(f"Erreur création ScoreDetailCandidat: {e}")
        return None

# ================================================================
# FONCTIONS DE CALCUL DES CRITÈRES SIMPLIFIÉES
# ================================================================

def calculer_score_competences(candidat, demande):
    """Calcul simplifié du score de compétences"""
    try:
        competences_candidat = candidat.competences.count()
        if competences_candidat == 0:
            return 0
        
        # Score basé sur le nombre de compétences (simplifié)
        score = min(100, competences_candidat * 10)
        return score
    except:
        return 0

def calculer_score_experience(candidat, demande):
    """Calcul simplifié du score d'expérience"""
    try:
        if not candidat.date_embauche:
            return 0
        
        # Ancienneté en mois
        anciennete_mois = (timezone.now().date() - candidat.date_embauche).days / 30.44
        
        # Score basé sur l'expérience
        score = min(100, anciennete_mois * 2)
        return score
    except:
        return 0

def calculer_score_disponibilite(candidat, demande):
    """Calcul du score de disponibilité"""
    try:
        disponibilite = candidat.est_disponible_pour_interim(demande.date_debut, demande.date_fin)
        return disponibilite.get('score_disponibilite', 0)
    except:
        return 0

def calculer_score_proximite(candidat, demande):
    """Calcul simplifié du score de proximité"""
    try:
        if candidat.site == demande.poste.site:
            return 100
        elif candidat.departement == demande.poste.departement:
            return 70
        else:
            return 30
    except:
        return 0

def calculer_score_similarite_poste(candidat, demande):
    """Calcul simplifié de la similarité de poste"""
    try:
        if candidat.poste and demande.poste:
            if candidat.poste.id == demande.poste.id:
                return 100
            elif candidat.poste.departement == demande.poste.departement:
                return 70
            else:
                return 30
        return 0
    except:
        return 0

def calculer_score_anciennete(candidat):
    """Calcul du score d'ancienneté"""
    try:
        if not candidat.date_embauche:
            return 0
        
        anciennete_mois = (timezone.now().date() - candidat.date_embauche).days / 30.44
        score = min(100, anciennete_mois)
        return score
    except:
        return 0

# ================================================================
# FONCTIONS UTILITAIRES POUR LES DONNÉES
# ================================================================

def get_score_class(score):
    """Retourne la classe CSS pour le score"""
    if score >= 85:
        return 'score-excellent'
    elif score >= 70:
        return 'score-good'
    elif score >= 55:
        return 'score-average'
    else:
        return 'score-poor'

def calculer_anciennete_display(candidat):
    """Calcule l'affichage de l'ancienneté"""
    try:
        if not candidat.date_embauche:
            return "Non renseignée"
        
        delta = timezone.now().date() - candidat.date_embauche
        annees = delta.days // 365
        mois = (delta.days % 365) // 30
        
        if annees > 0:
            return f"{annees} an{'s' if annees > 1 else ''} et {mois} mois"
        else:
            return f"{mois} mois"
    except:
        return "Non calculable"

def recuperer_competences_principales(candidat):
    """Récupère les compétences principales d'un candidat"""
    try:
        competences = candidat.competences.select_related('competence').order_by('-niveau_maitrise')[:5]
        return [
            {
                'nom': comp.competence.nom,
                'niveau': comp.niveau_maitrise,
                'certifie': comp.certifie
            }
            for comp in competences
        ]
    except:
        return []

def recuperer_commentaires_evaluation(candidat, demande):
    """Récupère les commentaires d'évaluation pour un candidat"""
    try:
        # Rechercher les propositions et validations liées
        propositions = PropositionCandidat.objects.filter(
            candidat_propose=candidat,
            demande_interim=demande
        ).select_related('proposant__user', 'evaluateur__user')
        
        commentaires = []
        
        for prop in propositions:
            if prop.justification:
                commentaires.append({
                    'auteur': prop.proposant.nom_complet,
                    'type': 'Justification',
                    'contenu': prop.justification,
                    'date': prop.created_at.isoformat() if prop.created_at else None,
                    'score_associe': prop.score_final
                })
            
            if prop.commentaire_evaluation:
                commentaires.append({
                    'auteur': prop.evaluateur.nom_complet if prop.evaluateur else 'Évaluateur',
                    'type': 'Évaluation',
                    'contenu': prop.commentaire_evaluation,
                    'date': prop.date_evaluation.isoformat() if prop.date_evaluation else None,
                    'score_associe': prop.score_humain_ajuste
                })
        
        return commentaires
        
    except Exception as e:
        logger.error(f"Erreur récupération commentaires: {e}")
        return []

def recuperer_commentaires_proposition(proposition):
    """Récupère les commentaires spécifiques à une proposition"""
    commentaires = []
    
    # Justification du proposant
    if proposition.justification:
        commentaires.append({
            'auteur': proposition.proposant.nom_complet,
            'type': 'Justification',
            'contenu': proposition.justification,
            'date': proposition.created_at.isoformat() if proposition.created_at else None
        })
    
    # Compétences spécifiques
    if proposition.competences_specifiques:
        commentaires.append({
            'auteur': proposition.proposant.nom_complet,
            'type': 'Compétences',
            'contenu': proposition.competences_specifiques,
            'date': proposition.created_at.isoformat() if proposition.created_at else None
        })
    
    # Expérience pertinente
    if proposition.experience_pertinente:
        commentaires.append({
            'auteur': proposition.proposant.nom_complet,
            'type': 'Expérience',
            'contenu': proposition.experience_pertinente,
            'date': proposition.created_at.isoformat() if proposition.created_at else None
        })
    
    # Commentaire d'évaluation
    if proposition.commentaire_evaluation and proposition.evaluateur:
        commentaires.append({
            'auteur': proposition.evaluateur.nom_complet,
            'type': 'Évaluation',
            'contenu': proposition.commentaire_evaluation,
            'date': proposition.date_evaluation.isoformat() if proposition.date_evaluation else None,
            'score_associe': proposition.score_humain_ajuste
        })
    
    return commentaires

def determiner_confiance_score(score_detail):
    """Détermine le niveau de confiance d'un score"""
    try:
        if score_detail.calcule_par == 'HUMAIN':
            return 'Élevée'
        elif score_detail.score_total >= 70:
            return 'Bonne'
        elif score_detail.score_total >= 40:
            return 'Moyenne'
        else:
            return 'Faible'
    except:
        return 'Inconnue'

def determiner_fiabilite_score(score_detail):
    """Détermine la fiabilité d'un score"""
    try:
        facteurs = []
        
        if score_detail.proposition_humaine:
            facteurs.append('Proposition humaine')
        
        if score_detail.candidat.competences.count() > 0:
            facteurs.append('Compétences renseignées')
        
        if score_detail.candidat.date_embauche:
            facteurs.append('Ancienneté connue')
        
        nb_facteurs = len(facteurs)
        
        if nb_facteurs >= 3:
            return 'Excellente'
        elif nb_facteurs >= 2:
            return 'Bonne'
        elif nb_facteurs >= 1:
            return 'Correcte'
        else:
            return 'Limitée'
    except:
        return 'Inconnue'

def generer_recommandations_candidat(candidat, demande, score_data):
    """Génère des recommandations pour un candidat"""
    try:
        recommandations = []
        score = score_data['score_final']
        
        if score >= 80:
            recommandations.append("Excellent candidat pour cette mission")
        elif score >= 60:
            recommandations.append("Bon candidat à considérer")
        else:
            recommandations.append("Candidat nécessitant une évaluation approfondie")
        
        # Disponibilité
        if not score_data['disponibilite']['disponible']:
            recommandations.append(f"Attention: {score_data['disponibilite']['raison']}")
        
        # Proximité
        if candidat.site != demande.poste.site:
            recommandations.append("Candidat sur un site différent")
        
        return recommandations
        
    except Exception as e:
        logger.error(f"Erreur génération recommandations: {e}")
        return ["Évaluation standard recommandée"]

def determiner_destinataire_escalade(demande, profil_utilisateur):
    """Détermine le destinataire pour une escalade"""
    try:
        # Logique d'escalade selon la hiérarchie
        if profil_utilisateur.type_profil == 'RESPONSABLE':
            # Escalader vers DIRECTEUR
            return ProfilUtilisateur.objects.filter(
                type_profil='DIRECTEUR',
                departement=demande.poste.departement,
                actif=True
            ).first()
        
        elif profil_utilisateur.type_profil == 'DIRECTEUR':
            # Escalader vers RH
            return ProfilUtilisateur.objects.filter(
                type_profil='RH',
                actif=True
            ).first()
        
        else:
            # Escalader vers ADMIN
            return ProfilUtilisateur.objects.filter(
                type_profil='ADMIN',
                actif=True
            ).first()
            
    except Exception as e:
        logger.error(f"Erreur détermination destinataire escalade: {e}")
        return None

def determiner_type_validation_escalade(destinataire):
    """Détermine le type de validation pour l'escalade"""
    try:
        mapping = {
            'RESPONSABLE': 'RESPONSABLE',
            'DIRECTEUR': 'DIRECTEUR', 
            'RH': 'RH',
            'ADMIN': 'ADMIN'
        }
        return mapping.get(destinataire.type_profil, 'RESPONSABLE')
    except:
        return 'RESPONSABLE'

