# -*- coding: utf-8 -*-
# services/manager_proposals.py
"""
Service pour la gestion des propositions manageriales de candidats
Integration complete avec le systeme de scoring et workflow
Compatible avec les modeles definis dans models.py
"""

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Q, Count, Avg, Max
from typing import Dict, List, Tuple, Optional, Any
import logging

from ..models import *

logger = logging.getLogger(__name__)

class ManagerProposalsService:
    """Service principal pour la gestion des propositions manageriales"""
    
    @classmethod
    def proposer_candidat(cls, demande: DemandeInterim, candidat: ProfilUtilisateur,
                         proposant: ProfilUtilisateur, justification: str,
                         competences_specifiques: str = "", 
                         experience_pertinente: str = "") -> Dict[str, Any]:
        """
        Permet a un manager/responsable de proposer un candidat pour une demande
        
        Args:
            demande: Demande d'interim concernee
            candidat: Candidat propose
            proposant: Utilisateur qui propose le candidat
            justification: Justification obligatoire de la proposition
            competences_specifiques: Competences specifiques du candidat
            experience_pertinente: Experience pertinente du candidat
            
        Returns:
            Dict avec success, proposition creee et informations
        """
        try:
            with transaction.atomic():
                # 1. Verifier les permissions
                peut_proposer, raison = cls._verifier_permissions_proposition(proposant, demande)
                if not peut_proposer:
                    return {
                        'success': False,
                        'error': raison,
                        'code': 'PERMISSION_DENIED'
                    }
                
                # 2. Verifier que la demande accepte encore les propositions
                if not demande.propositions_autorisees:
                    return {
                        'success': False,
                        'error': 'Les propositions ne sont plus autorisees pour cette demande',
                        'code': 'PROPOSITIONS_FERMEES'
                    }
                
                # 3. Verifier la limite de propositions par utilisateur
                nb_propositions_existantes = PropositionCandidat.objects.filter(
                    demande_interim=demande,
                    proposant=proposant
                ).count()
                
                if nb_propositions_existantes >= demande.nb_max_propositions_par_utilisateur:
                    return {
                        'success': False,
                        'error': f'Limite de {demande.nb_max_propositions_par_utilisateur} propositions atteinte',
                        'code': 'LIMITE_PROPOSITIONS'
                    }
                
                # 4. Verifier que le candidat n'a pas deja ete propose par ce proposant
                if PropositionCandidat.objects.filter(
                    demande_interim=demande,
                    candidat_propose=candidat,
                    proposant=proposant
                ).exists():
                    return {
                        'success': False,
                        'error': 'Vous avez deja propose ce candidat pour cette demande',
                        'code': 'CANDIDAT_DEJA_PROPOSE'
                    }
                
                # 5. Determiner la source de la proposition selon le role
                source_proposition = cls._determiner_source_proposition(proposant, demande)
                
                # 6. Creer la proposition
                proposition = PropositionCandidat.objects.create(
                    demande_interim=demande,
                    candidat_propose=candidat,
                    proposant=proposant,
                    source_proposition=source_proposition,
                    justification=justification,
                    competences_specifiques=competences_specifiques,
                    experience_pertinente=experience_pertinente,
                    statut='SOUMISE'
                )
                
                # 7. Calculer le score automatique avec bonus proposition humaine
                score_detail = cls._calculer_score_proposition(proposition)
                
                # 8. Creer l'historique
                HistoriqueAction.objects.create(
                    demande=demande,
                    proposition=proposition,
                    action='PROPOSITION_CANDIDAT',
                    utilisateur=proposant,
                    description=f"Proposition de {candidat.nom_complet} par {proposant.nom_complet}",
                    donnees_apres={
                        'candidat_id': candidat.id,
                        'candidat_nom': candidat.nom_complet,
                        'source_proposition': source_proposition,
                        'score_initial': score_detail.score_total,
                        'justification': justification[:200]  # Tronquer pour l'historique
                    }
                )
                
                # 9. Envoyer les notifications
                cls._envoyer_notifications_nouvelle_proposition(proposition)
                
                # 10. Mettre a jour le statut de la demande si necessaire
                if demande.statut == 'SOUMISE':
                    demande.statut = 'EN_PROPOSITION'
                    demande.save(update_fields=['statut'])
                
                logger.info(f"Proposition creee: {candidat.nom_complet} par {proposant.nom_complet} pour {demande.numero_demande}")
                
                return {
                    'success': True,
                    'proposition': proposition,
                    'score_initial': score_detail.score_total,
                    'message': f'Candidat {candidat.nom_complet} propose avec succes'
                }
                
        except Exception as e:
            logger.error(f"Erreur lors de la proposition de candidat: {e}")
            return {
                'success': False,
                'error': 'Erreur technique lors de la creation de la proposition',
                'code': 'ERREUR_TECHNIQUE'
            }
    
    @classmethod
    def evaluer_proposition(cls, proposition: PropositionCandidat, 
                           evaluateur: ProfilUtilisateur,
                           score_ajuste: Optional[int] = None,
                           commentaire: str = "",
                           decision: str = "EVALUEE") -> Dict[str, Any]:
        """
        Evalue une proposition de candidat par un validateur
        
        Args:
            proposition: Proposition a evaluer
            evaluateur: Utilisateur qui evalue
            score_ajuste: Score ajuste manuellement (optionnel)
            commentaire: Commentaire d'evaluation
            decision: Decision (EVALUEE, RETENUE, REJETEE)
            
        Returns:
            Dict avec success et informations
        """
        try:
            with transaction.atomic():
                # Verifier les permissions d'evaluation
                peut_evaluer, raison = cls._verifier_permissions_evaluation(evaluateur, proposition)
                if not peut_evaluer:
                    return {
                        'success': False,
                        'error': raison,
                        'code': 'PERMISSION_EVALUATION_DENIED'
                    }
                
                # Mettre a jour la proposition
                proposition.evaluateur = evaluateur
                proposition.commentaire_evaluation = commentaire
                proposition.date_evaluation = timezone.now()
                proposition.statut = decision
                
                # Ajuster le score si fourni
                if score_ajuste is not None:
                    proposition.score_humain_ajuste = score_ajuste
                
                proposition.save()
                
                # Mettre a jour le score detaille
                try:
                    score_detail = ScoreDetailCandidat.objects.get(
                        candidat=proposition.candidat_propose,
                        demande_interim=proposition.demande_interim,
                        proposition_humaine=proposition
                    )
                    
                    if score_ajuste is not None:
                        score_detail.score_total = min(100, score_ajuste + proposition.bonus_proposition_humaine)
                        score_detail.calcule_par = 'HUMAIN'
                        score_detail.save()
                        
                except ScoreDetailCandidat.DoesNotExist:
                    logger.warning(f"Score detaille non trouve pour proposition {proposition.id}")
                
                # Creer l'historique
                HistoriqueAction.objects.create(
                    demande=proposition.demande_interim,
                    proposition=proposition,
                    action='EVALUATION_CANDIDAT',
                    utilisateur=evaluateur,
                    description=f"Evaluation: {decision} par {evaluateur.nom_complet}",
                    donnees_apres={
                        'decision': decision,
                        'score_ajuste': score_ajuste,
                        'commentaire': commentaire,
                        'score_final': proposition.score_final
                    }
                )
                
                # Notifier le proposant
                cls._notifier_evaluation_proposition(proposition, evaluateur)
                
                logger.info(f"Proposition evaluee: {proposition.numero_proposition} - {decision}")
                
                return {
                    'success': True,
                    'proposition': proposition,
                    'nouveau_score': proposition.score_final,
                    'message': f'Proposition evaluee: {decision}'
                }
                
        except Exception as e:
            logger.error(f"Erreur lors de l'evaluation de la proposition: {e}")
            return {
                'success': False,
                'error': 'Erreur technique lors de l\'evaluation',
                'code': 'ERREUR_EVALUATION'
            }
    
    @classmethod
    def retenir_pour_validation_niveau_suivant(cls, demande: DemandeInterim,
                                              validateur: ProfilUtilisateur,
                                              propositions_retenues: List[int],
                                              nouvelle_proposition: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Retient des propositions pour le niveau de validation suivant
        Peut egalement ajouter une nouvelle proposition lors de la validation
        
        Args:
            demande: Demande d'interim
            validateur: Validateur actuel
            propositions_retenues: IDs des propositions retenues
            nouvelle_proposition: Nouvelle proposition a ajouter (optionnel)
            
        Returns:
            Dict avec success et informations
        """
        try:
            with transaction.atomic():
                propositions_validees = []
                
                # 1. Traiter les propositions existantes retenues
                for proposition_id in propositions_retenues:
                    try:
                        proposition = PropositionCandidat.objects.get(
                            id=proposition_id,
                            demande_interim=demande
                        )
                        
                        # Marquer comme retenue pour validation
                        proposition.retenir_pour_validation()
                        propositions_validees.append(proposition)
                        
                    except PropositionCandidat.DoesNotExist:
                        logger.warning(f"Proposition {proposition_id} non trouvee")
                
                # 2. Ajouter une nouvelle proposition si fournie
                nouvelle_prop_result = None
                if nouvelle_proposition:
                    candidat_id = nouvelle_proposition.get('candidat_id')
                    justification = nouvelle_proposition.get('justification', '')
                    
                    if candidat_id:
                        try:
                            candidat = ProfilUtilisateur.objects.get(id=candidat_id)
                            
                            # Creer la nouvelle proposition
                            nouvelle_prop_result = cls.proposer_candidat(
                                demande=demande,
                                candidat=candidat,
                                proposant=validateur,
                                justification=justification,
                                competences_specifiques=nouvelle_proposition.get('competences', ''),
                                experience_pertinente=nouvelle_proposition.get('experience', '')
                            )
                            
                            if nouvelle_prop_result['success']:
                                # Auto-retenir la nouvelle proposition
                                nouvelle_proposition_obj = nouvelle_prop_result['proposition']
                                nouvelle_proposition_obj.retenir_pour_validation()
                                propositions_validees.append(nouvelle_proposition_obj)
                                
                        except ProfilUtilisateur.DoesNotExist:
                            logger.warning(f"Candidat {candidat_id} non trouve")
                
                # 3. Creer la validation
                validation = ValidationDemande.objects.create(
                    demande=demande,
                    type_validation=cls._determiner_type_validation(validateur),
                    niveau_validation=demande.niveau_validation_actuel + 1,
                    validateur=validateur,
                    decision='APPROUVE',
                    commentaire=f"Validation avec {len(propositions_validees)} proposition(s) retenue(s)",
                    candidats_retenus=[{
                        'proposition_id': p.id,
                        'candidat_id': p.candidat_propose.id,
                        'candidat_nom': p.candidat_propose.nom_complet,
                        'score': p.score_final,
                        'source': p.source_proposition
                    } for p in propositions_validees]
                )
                
                # Mettre a jour le niveau de validation
                demande.niveau_validation_actuel += 1
                
                # Verifier s'il reste des niveaux de validation
                validateurs_suivants = cls._get_validateurs_niveau_suivant(demande)
                
                if validateurs_suivants.exists():
                    # Il y a encore des validateurs, continuer le workflow
                    demande.statut = 'EN_VALIDATION'
                    demande.save()
                    
                    # Notifier le niveau suivant en utilisant la fonction
                    cls._notifier_niveau_validation_suivant(demande, validation)
                    
                    return {
                        'success': True,
                        'propositions_retenues': len(propositions_validees),
                        'niveau_suivant': demande.niveau_validation_actuel,
                        'validation_finale': False,
                        'prochains_validateurs': list(validateurs_suivants.values('nom_complet', 'type_profil')),
                        'message': f'{len(propositions_validees)} proposition(s) retenue(s) pour validation niveau {demande.niveau_validation_actuel}'
                    }
                else:
                    # Validation finale - selectionner le meilleur candidat
                    return cls._finaliser_selection_candidat(demande, propositions_validees, validateur)
                    
        except Exception as e:
            logger.error(f"Erreur lors de la retention pour validation: {e}")
            return {
                'success': False,
                'error': 'Erreur lors de la validation',
                'code': 'ERREUR_VALIDATION'
            }
    
    @classmethod
    def get_candidats_tous_sources(cls, demande: DemandeInterim) -> List[Dict]:
        """
        Recupere tous les candidats (automatiques + propositions humaines) pour une demande
        avec leurs scores et informations completes
        
        Args:
            demande: Demande d'interim
            
        Returns:
            Liste des candidats avec toutes les informations
        """
        try:
            candidats_finaux = []
            
            # 1. Recuperer les propositions humaines validees
            propositions = PropositionCandidat.objects.filter(
                demande_interim=demande,
                statut__in=['EVALUEE', 'RETENUE', 'VALIDEE']
            ).select_related(
                'candidat_propose__user', 
                'candidat_propose__poste',
                'candidat_propose__site',
                'proposant__user'
            )
            
            for proposition in propositions:
                # Recuperer le score detaille
                score_detail = ScoreDetailCandidat.objects.filter(
                    candidat=proposition.candidat_propose,
                    demande_interim=demande,
                    proposition_humaine=proposition
                ).first()
                
                # Verifier la disponibilite en temps reel
                disponibilite = proposition.candidat_propose.est_disponible_pour_interim(
                    demande.date_debut, demande.date_fin
                )
                
                candidat_info = {
                    'candidat': proposition.candidat_propose,
                    'source': 'HUMAINE',
                    'proposition': proposition,
                    'score': score_detail.score_total if score_detail else proposition.score_final,
                    'score_detail': score_detail,
                    'proposant': proposition.proposant,
                    'justification': proposition.justification,
                    'competences_specifiques': proposition.competences_specifiques,
                    'experience_pertinente': proposition.experience_pertinente,
                    'date_proposition': proposition.created_at,
                    'disponibilite': disponibilite,
                    'bonus_humain': proposition.bonus_proposition_humaine,
                    'source_display': proposition.source_display,
                    'statut_proposition': proposition.statut,
                    'type_source': 'proposition_humaine'
                }
                
                candidats_finaux.append(candidat_info)
            
            # 2. Ajouter des candidats automatiques si necessaire
            # (Cette partie pourrait etre integree avec un service de selection automatique)
            
            # 3. Trier par score decroissant
            candidats_finaux.sort(key=lambda x: x['score'], reverse=True)
            
            return candidats_finaux
            
        except Exception as e:
            logger.error(f"Erreur recuperation candidats tous sources: {e}")
            return []
    
    @classmethod
    def get_propositions_pour_demande(cls, demande: DemandeInterim,
                                     statut_filtre: Optional[str] = None) -> List[PropositionCandidat]:
        """
        Recupere les propositions pour une demande avec filtres
        
        Args:
            demande: Demande d'interim
            statut_filtre: Filtre par statut (optionnel)
            
        Returns:
            Liste des propositions
        """
        try:
            propositions = PropositionCandidat.objects.filter(
                demande_interim=demande
            ).select_related(
                'candidat_propose__user',
                'candidat_propose__poste',
                'proposant__user'
            ).order_by('-created_at')
            
            if statut_filtre:
                propositions = propositions.filter(statut=statut_filtre)
            
            return list(propositions)
            
        except Exception as e:
            logger.error(f"Erreur recuperation propositions: {e}")
            return []
    
    @classmethod
    def get_statistiques_propositions(cls, demande: DemandeInterim) -> Dict[str, Any]:
        """
        Calcule les statistiques des propositions pour une demande
        
        Args:
            demande: Demande d'interim
            
        Returns:
            Dict avec les statistiques
        """
        try:
            propositions = PropositionCandidat.objects.filter(demande_interim=demande)
            
            stats = {
                'total': propositions.count(),
                'soumises': propositions.filter(statut='SOUMISE').count(),
                'evaluees': propositions.filter(statut='EVALUEE').count(),
                'retenues': propositions.filter(statut='RETENUE').count(),
                'validees': propositions.filter(statut='VALIDEE').count(),
                'rejetees': propositions.filter(statut='REJETEE').count(),
                'par_source': {},
                'score_moyen': 0,
                'proposants_uniques': 0
            }
            
            # Statistiques par source
            sources = propositions.values('source_proposition').annotate(
                count=Count('id')
            )
            
            for source in sources:
                stats['par_source'][source['source_proposition']] = source['count']
            
            # Score moyen
            scores = [p.score_final for p in propositions if p.score_final]
            if scores:
                stats['score_moyen'] = sum(scores) / len(scores)
            
            # Nombre de proposants uniques
            stats['proposants_uniques'] = propositions.values('proposant').distinct().count()
            
            return stats
            
        except Exception as e:
            logger.error(f"Erreur calcul statistiques propositions: {e}")
            return {}
    
    # ================================================================
    # METHODES PRIVEES
    # ================================================================

    # 3. NOUVELLE FONCTION - Determine qui peut valider au niveau suivant
    @classmethod
    def _get_validateurs_niveau_suivant(cls, demande):
        """
        Determine qui peut valider au niveau suivant selon la hierarchie CORRIGEE
        
        HIERARCHIE CORRECTE :
        - Niveau 0 -> Niveau 1 : RESPONSABLE (Premier niveau)
        - Niveau 1 -> Niveau 2 : DIRECTEUR (Deuxieme niveau)  
        - Niveau 2 -> Niveau 3 : RH/ADMIN (Niveau final)
        """
        niveau_suivant = demande.niveau_validation_actuel + 1
        
        if niveau_suivant == 1:
            # Premier niveau : RESPONSABLE du departement
            return ProfilUtilisateur.objects.filter(
                type_profil='RESPONSABLE',
                departement=demande.poste.departement,
                actif=True
            )
        
        elif niveau_suivant == 2:
            # Deuxieme niveau : DIRECTEUR
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
        
    @classmethod
    def _notifier_niveau_validation_suivant(demande: DemandeInterim, validation: ValidationDemande):
        """Notifie le niveau de validation suivant selon la hierarchie CORRIGEE"""
        
        try:
            niveau_suivant = demande.niveau_validation_actuel + 1
            
            # Determiner les validateurs du niveau suivant
            if niveau_suivant == 1:
                # Niveau 1 : RESPONSABLE
                validateurs_suivants = ProfilUtilisateur.objects.filter(
                    type_profil='RESPONSABLE',
                    departement=demande.poste.departement,
                    actif=True
                )
                titre_validation = "Validation Responsable (N+1)"
                message_validation = "Premiere validation requise en tant que Responsable de departement."
                
            elif niveau_suivant == 2:
                # Niveau 2 : DIRECTEUR
                validateurs_suivants = ProfilUtilisateur.objects.filter(
                    type_profil='DIRECTEUR',
                    actif=True
                )
                titre_validation = "Validation Directeur (N+2)"
                message_validation = "Deuxieme validation requise en tant que Directeur."
                
            elif niveau_suivant >= 3:
                # Niveau 3+ : RH/ADMIN
                validateurs_suivants = ProfilUtilisateur.objects.filter(
                    type_profil__in=['RH', 'ADMIN'],
                    actif=True
                )
                titre_validation = "Validation finale RH/Admin"
                message_validation = "Validation finale requise en tant que RH ou Administrateur."
                
            else:
                validateurs_suivants = ProfilUtilisateur.objects.none()
                titre_validation = "Validation inconnue"
                message_validation = "Validation requise."
            
            # Envoyer les notifications
            for validateur in validateurs_suivants:
                NotificationInterim.objects.create(
                    destinataire=validateur,
                    expediteur=validation.validateur,
                    demande=demande,
                    validation_liee=validation,
                    type_notification='DEMANDE_A_VALIDER',
                    urgence='HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE',
                    titre=f"{titre_validation} - {demande.numero_demande}",
                    message=f"{message_validation} Valide precedemment par {validation.validateur.nom_complet}.",
                    url_action_principale=f"/interim/validation/{demande.id}/",
                    texte_action_principale=f"Valider (Niveau {niveau_suivant})",
                    metadata={
                        'niveau_validation': niveau_suivant,
                        'validateur_precedent': validation.validateur.nom_complet,
                        'type_validation_actuelle': titre_validation
                    }
                )
                    
        except Exception as e:
            logger.error(f"Erreur notification niveau suivant: {e}")

    @classmethod
    def _get_type_validation_display(cls, niveau):
        """Retourne le libelle du type de validation selon le niveau"""
        if niveau == 1:
            return "Responsable (N+1)"
        elif niveau == 2:
            return "Directeur (N+2)"
        elif niveau >= 3:
            return "RH/Admin (Final)"
        else:
            return f"Niveau {niveau}"
    
    @classmethod
    def _verifier_permissions_proposition(proposant, demande):
        """
        Verifie si l'utilisateur peut proposer un candidat
        CHEF_EQUIPE peut proposer mais pas valider
        """
        # Verifier le statut du proposant
        if not proposant.actif or proposant.statut_employe != 'ACTIF':
            return False, "Utilisateur non actif"
        
        type_profil = getattr(proposant, 'type_profil', None)
        
        # Tous les managers peuvent proposer, y compris CHEF_EQUIPE
        if type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']:
            # Verifier le departement pour les niveaux inferieurs
            if type_profil in ['CHEF_EQUIPE', 'RESPONSABLE']:
                if getattr(proposant, 'departement', None) == demande.poste.departement:
                    return True, f"{type_profil} du departement"
            else:
                return True, f"{type_profil} autorise"
        
        # Verifier si c'est le manager direct
        if proposant == demande.demandeur.manager:
            return True, "Manager direct"
        
        return False, "Permissions insuffisantes pour proposer un candidat"
    
    @classmethod
    def _verifier_permissions_evaluation(cls, evaluateur: ProfilUtilisateur,
                                       proposition: PropositionCandidat) -> Tuple[bool, str]:
        """Verifie si l'utilisateur peut evaluer une proposition"""
        
        # Ne peut pas evaluer sa propre proposition
        if evaluateur == proposition.proposant:
            return False, "Impossible d'evaluer sa propre proposition"
        
        # Verifications selon le role
        if evaluateur.type_profil in ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']:
            return True, "Autorise a evaluer"
        
        # Manager direct du demandeur
        if evaluateur == proposition.demande_interim.demandeur.manager:
            return True, "Manager direct du demandeur"
        
        return False, "Permissions insuffisantes pour evaluer"
    
    @classmethod
    def _determiner_source_proposition(cls, proposant: ProfilUtilisateur, 
                                     demande: DemandeInterim) -> str:
        """Determine la source de la proposition selon le role du proposant"""
        
        if proposant == demande.demandeur:
            return 'DEMANDEUR_INITIAL'
        elif proposant == demande.demandeur.manager:
            return 'MANAGER_DIRECT'
        elif proposant.type_profil == 'CHEF_EQUIPE':
            return 'CHEF_EQUIPE'
        elif proposant.type_profil == 'RESPONSABLE':
            return 'RESPONSABLE_N1'
        elif proposant.type_profil == 'DIRECTEUR':
            return 'DIRECTEUR'
        elif proposant.type_profil == 'RH':
            return 'DRH'
        else:
            return 'AUTRE'
    
    @classmethod
    def _determiner_type_validation(cls, validateur: ProfilUtilisateur) -> str:
        """Determine le type de validation selon le validateur"""
        
        if validateur.type_profil == 'CHEF_EQUIPE':
            return 'N_PLUS_1'
        elif validateur.type_profil == 'RESPONSABLE':
            return 'N_PLUS_2'
        elif validateur.type_profil == 'DIRECTEUR':
            return 'DIRECTEUR'
        elif validateur.type_profil == 'RH':
            return 'DRH'
        else:
            return 'AUTRE'
    
    @classmethod
    def _calculer_score_proposition(cls, proposition: PropositionCandidat) -> ScoreDetailCandidat:
        """Calcule le score automatique pour une proposition avec bonus humain"""
        
        # Importer ici pour eviter les imports circulaires
        from .scoring_service import ScoringInterimService
        
        try:
            scoring_service = ScoringInterimService()
            
            # Recuperer la configuration de scoring
            config = ConfigurationScoring.get_configuration_pour_demande(proposition.demande_interim)
            
            # Calculer le score de base
            score_base = scoring_service.calculer_score_candidat(
                proposition.candidat_propose,
                proposition.demande_interim,
                config
            )
            
            # Creer le score detaille avec bonus proposition humaine
            score_detail = scoring_service.creer_score_detail(
                candidat=proposition.candidat_propose,
                demande=proposition.demande_interim,
                proposition=proposition,
                config=config
            )
            
            # Appliquer les bonus selon la source de la proposition
            if config:
                bonus = cls._calculer_bonus_selon_source(proposition, config)
                score_detail.bonus_proposition_humaine = bonus
                proposition.bonus_proposition_humaine = bonus
                proposition.save(update_fields=['bonus_proposition_humaine'])
            
            # Recalculer le score total avec bonus
            score_detail.calculer_score_total()
            score_detail.save()
            
            # Mettre a jour le score automatique dans la proposition
            proposition.score_automatique = score_detail.score_total
            proposition.save(update_fields=['score_automatique'])
            
            return score_detail
            
        except Exception as e:
            logger.error(f"Erreur calcul score proposition: {e}")
            # Creer un score par defaut en cas d'erreur
            return ScoreDetailCandidat.objects.create(
                candidat=proposition.candidat_propose,
                demande_interim=proposition.demande_interim,
                proposition_humaine=proposition,
                score_total=60,  # Score par defaut
                calcule_par='AUTOMATIQUE'
            )
    
    @classmethod
    def _calculer_bonus_selon_source(cls, proposition: PropositionCandidat,
                                   config: ConfigurationScoring) -> int:
        """Calcule le bonus selon la source de la proposition"""
        
        bonus_base = config.bonus_proposition_humaine
        
        # Bonus supplementaire selon la source
        source_bonus = {
            'MANAGER_DIRECT': config.bonus_manager_direct,
            'CHEF_EQUIPE': config.bonus_chef_equipe,
            'RESPONSABLE_N1': config.bonus_chef_equipe,
            'DIRECTEUR': config.bonus_directeur,
            'DRH': config.bonus_drh,
        }
        
        bonus_source = source_bonus.get(proposition.source_proposition, 0)
        
        return min(bonus_base + bonus_source, 50)  # Plafonner a 50 points
    
    @classmethod
    def _envoyer_notifications_nouvelle_proposition(cls, proposition: PropositionCandidat):
        """Envoie les notifications pour une nouvelle proposition selon la hierarchie CORRIGEE"""
        
        try:
            demande = proposition.demande_interim
            niveau_actuel = demande.niveau_validation_actuel
            
            # 1. Notifier le demandeur (si ce n'est pas lui qui propose)
            if proposition.proposant != demande.demandeur:
                NotificationInterim.objects.create(
                    destinataire=demande.demandeur,
                    expediteur=proposition.proposant,
                    demande=demande,
                    proposition_liee=proposition,
                    type_notification='PROPOSITION_CANDIDAT',
                    urgence='NORMALE',
                    titre=f"Nouveau candidat propose - {demande.numero_demande}",
                    message=f"{proposition.proposant.nom_complet} a propose {proposition.candidat_propose.nom_complet} "
                        f"pour votre demande d'interim.",
                    url_action_principale=f"/interim/demande/{demande.id}/",
                    texte_action_principale="Voir la proposition"
                )
            
            # 2. Notifier les validateurs selon le niveau actuel de la demande
            if niveau_actuel == 0:
                # Demande au niveau 0 : notifier les RESPONSABLES
                validateurs = ProfilUtilisateur.objects.filter(
                    type_profil='RESPONSABLE',
                    departement=demande.poste.departement,
                    actif=True
                )
                message_validateur = "Nouvelle proposition a evaluer avant validation Responsable (N+1)."
                
            elif niveau_actuel == 1:
                # Demande au niveau 1 : notifier les DIRECTEURS
                validateurs = ProfilUtilisateur.objects.filter(
                    type_profil='DIRECTEUR',
                    actif=True
                )
                message_validateur = "Nouvelle proposition a evaluer avant validation Directeur (N+2)."
                
            elif niveau_actuel >= 2:
                # Demande au niveau 2+ : notifier RH/ADMIN
                validateurs = ProfilUtilisateur.objects.filter(
                    type_profil__in=['RH', 'ADMIN'],
                    actif=True
                )
                message_validateur = "Nouvelle proposition a evaluer avant validation finale RH/Admin."
                
            else:
                validateurs = ProfilUtilisateur.objects.none()
                message_validateur = "Nouvelle proposition a evaluer."
            
            # Envoyer aux validateurs appropries
            for validateur in validateurs:
                if validateur != proposition.proposant:  # Ne pas se notifier soi-meme
                    NotificationInterim.objects.create(
                        destinataire=validateur,
                        expediteur=proposition.proposant,
                        demande=demande,
                        proposition_liee=proposition,
                        type_notification='CANDIDAT_PROPOSE_VALIDATION',
                        urgence='HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE',
                        titre=f"Evaluation requise - Nouveau candidat - {demande.numero_demande}",
                        message=f"{message_validateur} "
                            f"Candidat: {proposition.candidat_propose.nom_complet}.",
                        url_action_principale=f"/interim/validation/{demande.id}/",
                        texte_action_principale="Evaluer",
                        metadata={
                            'candidat_nom': proposition.candidat_propose.nom_complet,
                            'proposant_nom': proposition.proposant.nom_complet,
                            'score_initial': proposition.score_automatique or 0,
                            'niveau_validation': niveau_actuel
                        }
                    )
            
        except Exception as e:
            logger.error(f"Erreur envoi notifications nouvelle proposition: {e}")

    @classmethod
    def _notifier_evaluation_proposition(cls, proposition: PropositionCandidat, 
                                       evaluateur: ProfilUtilisateur):
        """Notifie le proposant de l'evaluation de sa proposition"""
        
        try:
            NotificationInterim.objects.create(
                destinataire=proposition.proposant,
                expediteur=evaluateur,
                demande=proposition.demande_interim,
                proposition_liee=proposition,
                type_notification='PROPOSITION_EVALUEE',
                urgence='NORMALE',
                titre=f"Votre proposition a ete evaluee - {proposition.get_statut_display()}",
                message=f"Votre proposition de {proposition.candidat_propose.nom_complet} "
                       f"a ete evaluee par {evaluateur.nom_complet} avec le statut: {proposition.get_statut_display()}",
                metadata={
                    'candidat_nom': proposition.candidat_propose.nom_complet,
                    'evaluateur_nom': evaluateur.nom_complet,
                    'decision': proposition.statut,
                    'score_final': proposition.score_final
                }
            )
            
        except Exception as e:
            logger.error(f"Erreur notification evaluation proposition: {e}")
    
    @classmethod
    def _notifier(cls, demande: DemandeInterim, validation: ValidationDemande):
        """Notifie le niveau de validation suivant"""
        
        try:
            validateurs_suivants = cls._identifier_validateurs_niveau_suivant(demande)
            
            for validateur in validateurs_suivants:
                NotificationInterim.objects.create(
                    destinataire=validateur,
                    expediteur=validation.validateur,
                    demande=demande,
                    validation_liee=validation,
                    type_notification='DEMANDE_A_VALIDER',
                    urgence='HAUTE' if demande.est_urgente else 'NORMALE',
                    titre=f"Validation niveau {demande.niveau_validation_actuel} requise",
                    message=f"Une demande d'interim necessite votre validation. "
                           f"{len(validation.candidats_retenus)} candidat(s) ont ete retenus par le niveau precedent.",
                    metadata={
                        'nb_candidats_retenus': len(validation.candidats_retenus),
                        'niveau_validation': demande.niveau_validation_actuel,
                        'validateur_precedent': validation.validateur.nom_complet
                    }
                )
                
        except Exception as e:
            logger.error(f"Erreur notification niveau suivant: {e}")
    
    @classmethod
    def _identifier_validateurs_pour_notification(cls, demande: DemandeInterim) -> List[ProfilUtilisateur]:
        """
        Identifie les validateurs a notifier pour une nouvelle proposition selon la hierarchie CORRIGEE
        """
        validateurs = []
        
        try:
            niveau_actuel = demande.niveau_validation_actuel
            
            # Niveau 0 : Notifier les RESPONSABLES (premier niveau de validation)
            if niveau_actuel == 0:
                responsables = ProfilUtilisateur.objects.filter(
                    type_profil='RESPONSABLE',
                    departement=demande.poste.departement,
                    actif=True
                )
                validateurs.extend(responsables)
                
            # Niveau 1 : Notifier les DIRECTEURS (deuxieme niveau de validation)
            elif niveau_actuel == 1:
                directeurs = ProfilUtilisateur.objects.filter(
                    type_profil='DIRECTEUR',
                    actif=True
                )
                validateurs.extend(directeurs)
                
            # Niveau 2+ : Notifier RH/ADMIN (validation finale)
            elif niveau_actuel >= 2:
                rh_admin = ProfilUtilisateur.objects.filter(
                    type_profil__in=['RH', 'ADMIN'],
                    actif=True
                )
                validateurs.extend(rh_admin)
            
            # Toujours inclure la DRH pour les demandes urgentes (information)
            if demande.urgence in ['ELEVEE', 'CRITIQUE']:
                drh = ProfilUtilisateur.objects.filter(
                    type_profil='RH',
                    actif=True
                )
                validateurs.extend(drh)
            
        except Exception as e:
            logger.error(f"Erreur identification validateurs: {e}")
        
        return list(set(validateurs))  # Dedoublonner
    
    @classmethod
    def _identifier_validateurs_niveau_suivant(cls, demande: DemandeInterim) -> List[ProfilUtilisateur]:
        """Identifie les validateurs pour le niveau suivant"""
        
        validateurs = []
        niveau = demande.niveau_validation_actuel
        
        try:
            if niveau == 1:  # N+1
                if demande.demandeur.manager:
                    validateurs.append(demande.demandeur.manager)
                    
            elif niveau == 2:  # N+2 ou Directeur
                directeurs = ProfilUtilisateur.objects.filter(
                    type_profil='DIRECTEUR',
                    departement=demande.poste.departement,
                    actif=True
                )
                validateurs.extend(directeurs)
                
            elif niveau >= 3:  # DRH
                drh = ProfilUtilisateur.objects.filter(
                    type_profil='RH',
                    actif=True
                )
                validateurs.extend(drh)
                
        except Exception as e:
            logger.error(f"Erreur identification validateurs niveau suivant: {e}")
        
        return validateurs
    
    @classmethod
    def _finaliser_selection_candidat(cls, demande: DemandeInterim,
                                    propositions_finales: List[PropositionCandidat],
                                    validateur_final: ProfilUtilisateur) -> Dict[str, Any]:
        """Finalise la selection du candidat retenu"""
        
        try:
            if not propositions_finales:
                return {
                    'success': False,
                    'error': 'Aucune proposition disponible pour la selection finale',
                    'code': 'AUCUNE_PROPOSITION'
                }
            
            # Selectionner le candidat avec le meilleur score
            meilleure_proposition = max(propositions_finales, key=lambda p: p.score_final)
            
            with transaction.atomic():
                # Mettre a jour la demande
                demande.candidat_selectionne = meilleure_proposition.candidat_propose
                demande.statut = 'CANDIDAT_SELECTIONNE'
                demande.date_validation = timezone.now()
                demande.save()
                
                # Marquer la proposition comme validee
                meilleure_proposition.statut = 'VALIDEE'
                meilleure_proposition.save()
                
                # Creer l'historique
                HistoriqueAction.objects.create(
                    demande=demande,
                    proposition=meilleure_proposition,
                    action='SELECTION_CANDIDAT',
                    utilisateur=validateur_final,
                    description=f"Selection finale: {meilleure_proposition.candidat_propose.nom_complet}",
                    donnees_apres={
                        'candidat_selectionne_id': meilleure_proposition.candidat_propose.id,
                        'candidat_selectionne_nom': meilleure_proposition.candidat_propose.nom_complet,
                        'score_final': meilleure_proposition.score_final,
                        'source_proposition': meilleure_proposition.source_proposition,
                        'proposant_nom': meilleure_proposition.proposant.nom_complet
                    }
                )
                
                # Notifier le candidat selectionne
                cls._notifier_candidat_selectionne(demande, meilleure_proposition)
                
                # Notifier les autres parties prenantes
                cls._notifier_selection_finale(demande, meilleure_proposition, validateur_final)
            
            return {
                'success': True,
                'candidat_selectionne': meilleure_proposition.candidat_propose,
                'proposition_retenue': meilleure_proposition,
                'score_final': meilleure_proposition.score_final,
                'message': f"Candidat {meilleure_proposition.candidat_propose.nom_complet} selectionne avec succes"
            }
            
        except Exception as e:
            logger.error(f"Erreur finalisation selection: {e}")
            return {
                'success': False,
                'error': 'Erreur lors de la finalisation de la selection',
                'code': 'ERREUR_FINALISATION'
            }
    
    @classmethod
    def _notifier_candidat_selectionne(cls, demande: DemandeInterim, 
                                     proposition: PropositionCandidat):
        """Notifie le candidat selectionne"""
        
        try:
            NotificationInterim.objects.create(
                destinataire=proposition.candidat_propose,
                demande=demande,
                proposition_liee=proposition,
                type_notification='CANDIDAT_SELECTIONNE',
                urgence='HAUTE',
                titre=f"Vous avez ete selectionne(e) pour une mission d'interim",
                message=f"Felicitations ! Vous avez ete selectionne(e) pour la mission d'interim "
                       f"au poste de {demande.poste.titre} du {demande.date_debut} au {demande.date_fin}.",
                metadata={
                    'poste_titre': demande.poste.titre,
                    'date_debut': str(demande.date_debut),
                    'date_fin': str(demande.date_fin),
                    'score_final': proposition.score_final,
                    'proposant_nom': proposition.proposant.nom_complet
                }
            )
            
        except Exception as e:
            logger.error(f"Erreur notification candidat selectionne: {e}")
    
    @classmethod
    def _notifier_selection_finale(cls, demande: DemandeInterim, 
                                  proposition: PropositionCandidat,
                                  validateur_final: ProfilUtilisateur):
        """Notifie les parties prenantes de la selection finale"""
        
        try:
            parties_prenantes = [demande.demandeur]
            
            # Ajouter le proposant si different du demandeur
            if proposition.proposant != demande.demandeur:
                parties_prenantes.append(proposition.proposant)
            
            for destinataire in parties_prenantes:
                if destinataire != validateur_final:  # Ne pas se notifier soi-meme
                    NotificationInterim.objects.create(
                        destinataire=destinataire,
                        expediteur=validateur_final,
                        demande=demande,
                        proposition_liee=proposition,
                        type_notification='VALIDATION_EFFECTUEE',
                        urgence='NORMALE',
                        titre=f"Candidat selectionne - {demande.numero_demande}",
                        message=f"Le candidat {proposition.candidat_propose.nom_complet} "
                               f"a ete selectionne pour votre demande d'interim.",
                        metadata={
                            'candidat_selectionne_nom': proposition.candidat_propose.nom_complet,
                            'validateur_final_nom': validateur_final.nom_complet,
                            'score_final': proposition.score_final
                        }
                    )
                    
        except Exception as e:
            logger.error(f"Erreur notification selection finale: {e}")

# ================================================================
# LOG DE CONFIRMATION
# ================================================================

logger.info("OK Service ManagerProposalsService cree avec succes")
logger.info(">>> Fonctionnalites principales:")
logger.info("   >>> Proposition de candidats par les managers")
logger.info("   >>> Evaluation et scoring avec bonus selon role")
logger.info("   >>> Validation multi-niveaux progressive")
logger.info("   >>> Notifications intelligentes automatiques")
logger.info("   >>> Selection finale optimisee")
logger.info("   >>> Integration complete avec les modeles existants")
print(">>> Service manager_proposals.py pret pour utilisation")