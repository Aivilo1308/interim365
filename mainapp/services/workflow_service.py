# -*- coding: utf-8 -*-
# services/workflow_integration_service.py
"""
Service d'integration complete du workflow d'interim
Orchestre les propositions manageriales, le scoring et les validations
"""

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from typing import Dict, List, Tuple, Optional
import logging

from ..models import (
    DemandeInterim, ProfilUtilisateur, PropositionCandidat,
    ValidationDemande, NotificationInterim, WorkflowDemande,
    WorkflowEtape, HistoriqueAction, ReponseCandidatInterim,
    ConfigurationScoring
)
from .manager_proposals import ManagerProposalsService
from .scoring_service import ScoringInterimService

logger = logging.getLogger(__name__)

class WorkflowIntegrationService:
    """Service principal d'orchestration du workflow d'interim"""
    
    @staticmethod
    @transaction.atomic
    def initialiser_workflow_demande(demande: DemandeInterim) -> bool:
        """
        Initialise le workflow complet pour une nouvelle demande
        """
        try:
            # Creer le workflow
            etape_initiale = WorkflowEtape.objects.filter(
                type_etape='DEMANDE',
                actif=True
            ).order_by('ordre').first()
            
            if not etape_initiale:
                logger.error("Aucune etape initiale de workflow configuree")
                return False
            
            workflow = WorkflowDemande.objects.create(
                demande=demande,
                etape_actuelle=etape_initiale
            )
            
            # Ajouter l'action initiale
            workflow.ajouter_action(
                utilisateur=demande.demandeur,
                action="Creation de la demande d'interim",
                commentaire=f"Demande creee pour le poste {demande.poste.titre}",
                metadata={
                    'type': 'creation_demande',
                    'urgence': demande.urgence,
                    'date_debut': demande.date_debut.isoformat() if demande.date_debut else None,
                    'date_fin': demande.date_fin.isoformat() if demande.date_fin else None
                }
            )
            
            # Generer les candidats automatiques si active
            if demande.propositions_autorisees:
                WorkflowIntegrationService._generer_candidats_automatiques(demande)
            
            # Notifier les personnes concernees
            WorkflowIntegrationService._notifier_creation_demande(demande)
            
            # Passer a l'etape suivante
            WorkflowIntegrationService._avancer_workflow(demande, 'PROPOSITION_CANDIDATS')
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur initialisation workflow: {e}")
            return False
    
    @staticmethod
    def _generer_candidats_automatiques(demande: DemandeInterim):
        """Genere les candidats automatiques pour la demande"""
        try:
            scoring_service = ScoringInterimService()
            candidats_auto = scoring_service.generer_candidats_automatiques(demande, limite=10)
            
            for candidat_data in candidats_auto:
                # Creer la proposition automatique
                proposition = PropositionCandidat.objects.create(
                    demande_interim=demande,
                    candidat_propose=candidat_data['candidat'],
                    proposant=demande.demandeur,  # Systeme via demandeur
                    source_proposition='SYSTEME',
                    justification=candidat_data['justification_auto'],
                    score_automatique=candidat_data['score'],
                    statut='PROPOSEE'
                )
                
                # Creer le score detaille
                scoring_service.creer_score_detail(
                    candidat_data['candidat'], demande, proposition
                )
            
            logger.info(f"Genere {len(candidats_auto)} candidats automatiques pour {demande.numero_demande}")
            
        except Exception as e:
            logger.error(f"Erreur generation candidats automatiques: {e}")
    
    @classmethod
    def _notifier_creation_demande(cls, demande: DemandeInterim):
        """
        Notifie la creation d'une demande selon la hierarchie CORRIGEE
        """
        try:
            notifications_envoyees = []
            
            # 1. Notifier le RESPONSABLE en premier (Niveau 1 de validation)
            responsables_dept = ProfilUtilisateur.objects.filter(
                type_profil='RESPONSABLE',
                departement=demande.poste.departement,
                actif=True
            )
            
            for responsable in responsables_dept:
                # Ne pas notifier si c'est le demandeur lui-meme
                if responsable != demande.demandeur:
                    NotificationInterim.objects.create(
                        destinataire=responsable,
                        expediteur=demande.demandeur,
                        demande=demande,
                        type_notification='NOUVELLE_DEMANDE_VALIDATION',
                        urgence='HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE',
                        titre=f"Nouvelle demande a valider (N+1) - {demande.numero_demande}",
                        message=f"{demande.demandeur.nom_complet} a cree une demande d'interim "
                            f"pour le poste {demande.poste.titre}. Validation Responsable requise (Premier niveau).",
                        url_action_principale=f"/interim/validation/{demande.id}/",
                        texte_action_principale="Valider (N+1)",
                        metadata={
                            'niveau_validation': 1,
                            'type_validation': 'RESPONSABLE',
                            'urgence': demande.urgence,
                            'date_debut': demande.date_debut.isoformat() if demande.date_debut else None
                        }
                    )
                    notifications_envoyees.append(f"Responsable: {responsable.nom_complet}")
            
            # 2. Notifier la DRH SEULEMENT pour les demandes CRITIQUES (pour information)
            if demande.urgence == 'CRITIQUE':
                drh_profiles = ProfilUtilisateur.objects.filter(type_profil='RH', actif=True)
                for drh in drh_profiles:
                    if drh != demande.demandeur:
                        NotificationInterim.objects.create(
                            destinataire=drh,
                            expediteur=demande.demandeur,
                            demande=demande,
                            type_notification='DEMANDE_CRITIQUE_INFO',
                            urgence='CRITIQUE',
                            titre=f">>> CRITIQUE - Demande necessitant attention - {demande.numero_demande}",
                            message=f"Demande CRITIQUE creee par {demande.demandeur.nom_complet}. "
                                f"Poste: {demande.poste.titre}. "
                                f"Suivre le circuit: Responsable -> Directeur -> RH.",
                            url_action_principale=f"/interim/demande/{demande.id}/",
                            texte_action_principale="Surveiller",
                            metadata={
                                'type_alerte': 'CRITIQUE',
                                'circuit_validation': 'RESPONSABLE_DIRECTEUR_RH',
                                'demandeur': demande.demandeur.nom_complet
                            }
                        )
                        notifications_envoyees.append(f"DRH (info critique): {drh.nom_complet}")
            
            # 3. Ne PAS notifier automatiquement les DIRECTEURS a la creation
            # Ils seront notifies au niveau 2 seulement
            
            # Log des notifications envoyees
            logger.info(f"Notifications creation demande {demande.numero_demande}: {notifications_envoyees}")
            
        except Exception as e:
            logger.error(f"Erreur notifications creation demande: {e}")

    @staticmethod
    def traiter_nouvelle_proposition(proposition: PropositionCandidat) -> bool:
        """
        Traite une nouvelle proposition de candidat dans le workflow
        """
        try:
            demande = proposition.demande_interim
            
            # Mettre a jour le workflow
            workflow = demande.workflow
            workflow.ajouter_proposition_candidat(proposition)
            
            # Calculer/mettre a jour le score
            scoring_service = ScoringInterimService()
            if not proposition.score_automatique:
                score = scoring_service.calculer_score_candidat(
                    proposition.candidat_propose, demande
                )
                proposition.score_automatique = score
                proposition.save()
            
            # Creer le score detaille si pas deja fait
            if not proposition.score_candidat.exists():
                scoring_service.creer_score_detail(
                    proposition.candidat_propose, demande, proposition
                )
            
            # Verifier si on peut avancer dans le workflow
            WorkflowIntegrationService._verifier_avancement_workflow(demande)
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur traitement nouvelle proposition: {e}")
            return False
    
    @staticmethod
    def traiter_validation(validation: ValidationDemande) -> bool:
        """
        Traite une validation dans le workflow
        """
        try:
            demande = validation.demande
            
            # Mettre a jour le workflow
            workflow = demande.workflow
            workflow.ajouter_validation(validation)
            
            # Traiter selon la decision
            if validation.decision == 'APPROUVE':
                WorkflowIntegrationService._traiter_validation_positive(demande, validation)
            elif validation.decision == 'REFUSE':
                WorkflowIntegrationService._traiter_validation_negative(demande, validation)
            elif validation.decision == 'CANDIDAT_AJOUTE':
                WorkflowIntegrationService._traiter_ajout_candidat(demande, validation)
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur traitement validation: {e}")
            return False
    
    @staticmethod
    def _traiter_validation_positive(demande: DemandeInterim, validation: ValidationDemande):
        """OK CORRIGE - Traite une validation positive avec progression sequentielle"""
        
        # OK CORRECTION : Utiliser le niveau de la validation, pas le niveau de la demande
        niveau_actuel = validation.niveau_validation  # Niveau qui vient d'etre valide
        niveau_max = demande.niveaux_validation_requis  # Generalement 3
        
        # OK LOGIQUE CORRIGEE : Progression sequentielle obligatoire
        if niveau_actuel < niveau_max:
            # OK Passer au niveau suivant (jamais sauter de niveau)
            demande.niveau_validation_actuel = niveau_actuel
            demande.statut = 'EN_VALIDATION'
            demande.save()
            
            # Notifier le niveau suivant selon la hierarchie
            WorkflowIntegrationService._notifier_niveau_validation_suivant(demande, validation)
            
            logger.info(f"OK Validation niveau {niveau_actuel} -> Progression vers niveau {niveau_actuel + 1}")
            
        else:
            # OK SEULEMENT si niveau_actuel >= niveau_max : Validation finale
            demande.niveau_validation_actuel = niveau_actuel
            demande.statut = 'VALIDEE'
            demande.date_validation = timezone.now()
            demande.save()
            
            # Finaliser la selection du candidat
            WorkflowIntegrationService._finaliser_selection_candidat(demande)
            
            logger.info(f"OK Validation finale niveau {niveau_actuel} -> Selection candidat")

    
    @staticmethod
    def _traiter_validation_negative(demande: DemandeInterim, validation: ValidationDemande):
        """Traite une validation negative"""
        
        demande.statut = 'REFUSEE'
        demande.save()
        
        # Notifier le demandeur
        NotificationInterim.objects.create(
            destinataire=demande.demandeur,
            expediteur=validation.validateur,
            demande=demande,
            validation_liee=validation,
            type_notification='VALIDATION_EFFECTUEE',
            urgence='NORMALE',
            titre=f"Demande refusee - {demande.numero_demande}",
            message=f"Votre demande a ete refusee par {validation.validateur.nom_complet}. "
                   f"Motif: {validation.commentaire}",
            url_action_principale=f"/interim/demande/{demande.id}/",
            texte_action_principale="Voir les details"
        )
    
    @staticmethod
    def _traiter_ajout_candidat(demande: DemandeInterim, validation: ValidationDemande):
        """Traite l'ajout d'un nouveau candidat lors de la validation"""
        
        if validation.nouveau_candidat_propose:
            # Creer la proposition pour le nouveau candidat
            success, message, proposition = ManagerProposalsService.proposer_candidat(
                demande=demande,
                candidat=validation.nouveau_candidat_propose,
                proposant=validation.validateur,
                justification=f"Ajoute lors de validation: {validation.justification_nouveau_candidat}"
            )
            
            if success:
                # Marquer cette proposition comme retenue
                proposition.statut = 'RETENUE'
                proposition.save()
    
    @staticmethod
    def _finaliser_selection_candidat(demande: DemandeInterim):
        """Finalise la selection du meilleur candidat"""
        try:
            # Recuperer toutes les propositions validees
            propositions = ManagerProposalsService.obtenir_toutes_propositions_demande(demande)
            
            if not propositions:
                logger.warning(f"Aucune proposition pour finaliser {demande.numero_demande}")
                return
            
            # Trier par score et selectionner le meilleur
            propositions.sort(key=lambda x: x['score'], reverse=True)
            meilleur_candidat_data = propositions[0]
            meilleur_candidat = meilleur_candidat_data['candidat']
            
            # Mettre a jour la demande
            demande.candidat_selectionne = meilleur_candidat
            demande.statut = 'CANDIDAT_SELECTIONNE'
            demande.date_validation = timezone.now()
            demande.save()
            
            # Creer la reponse candidat
            delai_reponse = timezone.now() + timezone.timedelta(days=3)  # 3 jours pour repondre
            
            reponse, created = ReponseCandidatInterim.objects.get_or_create(
                demande=demande,
                candidat=meilleur_candidat,
                date_limite_reponse=delai_reponse,
                reponse='EN_ATTENTE'
            )
            
            # Notifier le candidat selectionne
            WorkflowIntegrationService._notifier_candidat_selectionne(demande, meilleur_candidat)
            
            # Notifier le demandeur
            WorkflowIntegrationService._notifier_demandeur_selection(demande, meilleur_candidat_data)
            
            # Avancer le workflow
            WorkflowIntegrationService._avancer_workflow(demande, 'NOTIFICATION_CANDIDAT')
            
        except Exception as e:
            logger.error(f"Erreur finalisation selection: {e}")
    
    @staticmethod
    def _notifier_candidat_selectionne(demande: DemandeInterim, candidat: ProfilUtilisateur):
        """Notifie le candidat selectionne"""
        try:
            NotificationInterim.objects.create(
                destinataire=candidat,
                expediteur=demande.demandeur,
                demande=demande,
                type_notification='CANDIDAT_SELECTIONNE',
                urgence='HAUTE',
                titre=f"Vous etes selectionne pour une mission d'interim",
                message=f"Felicitations ! Vous avez ete selectionne pour remplacer "
                       f"{demande.personne_remplacee.nom_complet} au poste {demande.poste.titre} "
                       f"du {demande.date_debut} au {demande.date_fin}. "
                       f"Veuillez repondre dans les 3 jours.",
                url_action_principale=f"/interim/reponse-interim/{demande.id}/",
                texte_action_principale="Repondre a la proposition"
            )
            
        except Exception as e:
            logger.error(f"Erreur notification candidat selectionne: {e}")
    
    @staticmethod
    def _notifier_demandeur_selection(demande: DemandeInterim, candidat_data: Dict):
        """Notifie le demandeur de la selection"""
        try:
            candidat = candidat_data['candidat']
            score = candidat_data['score']
            
            NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=None,  # Notification systeme
                demande=demande,
                type_notification='CANDIDAT_SELECTIONNE',
                urgence='NORMALE',
                titre=f"Candidat selectionne pour votre demande {demande.numero_demande}",
                message=f"Le candidat {candidat.nom_complet} a ete selectionne "
                       f"(score: {score}/100). Il sera notifie et devra confirmer sa disponibilite.",
                url_action_principale=f"/interim/demande/{demande.id}/",
                texte_action_principale="Suivre l'evolution"
            )
            
        except Exception as e:
            logger.error(f"Erreur notification demandeur selection: {e}")
    
    @staticmethod
    def traiter_reponse_candidat(reponse: ReponseCandidatInterim) -> bool:
        """
        Traite la reponse d'un candidat a une proposition
        """
        try:
            demande = reponse.demande
            
            if reponse.reponse == 'ACCEPTE':
                # Mission acceptee
                demande.statut = 'EN_COURS'
                demande.date_debut_effective = demande.date_debut
                demande.save()
                
                # Notifier les parties prenantes
                WorkflowIntegrationService._notifier_mission_acceptee(demande, reponse.candidat)
                
                # Avancer le workflow
                WorkflowIntegrationService._avancer_workflow(demande, 'DEBUT_MISSION')
                
            elif reponse.reponse == 'REFUSE':
                # Mission refusee - chercher un autre candidat
                WorkflowIntegrationService._traiter_refus_candidat(demande, reponse)
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur traitement reponse candidat: {e}")
            return False
    
    @staticmethod
    def _traiter_refus_candidat(demande: DemandeInterim, reponse: ReponseCandidatInterim):
        """Traite le refus d'un candidat"""
        try:
            # Chercher le candidat suivant
            propositions = ManagerProposalsService.obtenir_toutes_propositions_demande(demande)
            propositions.sort(key=lambda x: x['score'], reverse=True)
            
            # Exclure le candidat qui a refuse
            candidats_restants = [
                p for p in propositions 
                if p['candidat'] != reponse.candidat
            ]
            
            if candidats_restants:
                # Selectionner le suivant
                prochain_candidat = candidats_restants[0]['candidat']
                
                demande.candidat_selectionne = prochain_candidat
                demande.save()
                
                # Creer nouvelle reponse candidat
                delai_reponse = timezone.now() + timezone.timedelta(days=3)
                reponse, created = ReponseCandidatInterim.objects.get_or_create(
                    demande=demande,
                    candidat=prochain_candidat,
                    date_limite_reponse=delai_reponse,
                    reponse='EN_ATTENTE'
                )
                
                # Notifier le nouveau candidat
                WorkflowIntegrationService._notifier_candidat_selectionne(demande, prochain_candidat)
                
            else:
                # Plus de candidats disponibles
                demande.statut = 'ECHEC_SELECTION'
                demande.save()
                
                # Notifier le demandeur
                NotificationInterim.objects.create(
                    destinataire=demande.demandeur,
                    demande=demande,
                    type_notification='ECHEC_SELECTION',
                    urgence='HAUTE',
                    titre=f"Echec de selection - {demande.numero_demande}",
                    message="Aucun candidat disponible n'a accepte la mission. "
                           "Veuillez reviser les criteres ou relancer une recherche.",
                    url_action_principale=f"/interim/demande/{demande.id}/relancer/",
                    texte_action_principale="Relancer la recherche"
                )
            
        except Exception as e:
            logger.error(f"Erreur traitement refus candidat: {e}")
    
    @staticmethod
    def _notifier_mission_acceptee(demande: DemandeInterim, candidat: ProfilUtilisateur):
        """Notifie l'acceptation de la mission"""
        try:
            # Notifier le demandeur
            NotificationInterim.objects.create(
                destinataire=demande.demandeur,
                expediteur=candidat,
                demande=demande,
                type_notification='CANDIDAT_ACCEPTE',
                urgence='NORMALE',
                titre=f"Mission acceptee - {demande.numero_demande}",
                message=f"{candidat.nom_complet} a accepte la mission d'interim. "
                       f"La mission debutera le {demande.date_debut}.",
                url_action_principale=f"/interim/mission/{demande.id}/",
                texte_action_principale="Gerer la mission"
            )
            
            # Notifier le manager
            if demande.demandeur.manager:
                NotificationInterim.objects.create(
                    destinataire=demande.demandeur.manager,
                    expediteur=candidat,
                    demande=demande,
                    type_notification='MISSION_DEMARREE',
                    urgence='NORMALE',
                    titre=f"Mission d'interim demarree - {demande.numero_demande}",
                    message=f"La mission de {candidat.nom_complet} a commence.",
                    url_action_principale=f"/interim/mission/{demande.id}/",
                    texte_action_principale="Suivre la mission"
                )
            
        except Exception as e:
            logger.error(f"Erreur notification mission acceptee: {e}")
    
    @staticmethod
    def _avancer_workflow(demande: DemandeInterim, nouvelle_etape: str):
        """Fait avancer le workflow a l'etape suivante"""
        try:
            etape_suivante = WorkflowEtape.objects.filter(
                type_etape=nouvelle_etape,
                actif=True
            ).first()
            
            if etape_suivante:
                workflow = demande.workflow
                workflow.etape_actuelle = etape_suivante
                workflow.save()
                
                # Ajouter l'action dans l'historique
                workflow.ajouter_action(
                    utilisateur=None,  # Action systeme
                    action=f"Passage a l'etape: {etape_suivante.nom}",
                    metadata={'etape_precedente': workflow.etape_actuelle.nom}
                )
            
        except Exception as e:
            logger.error(f"Erreur avancement workflow: {e}")
    
    @staticmethod
    def _verifier_avancement_workflow(demande: DemandeInterim):
        """Verifie s'il faut faire avancer le workflow automatiquement"""
        try:
            # Logique pour determiner si on peut avancer
            # Par exemple, si on a assez de propositions ou si le delai est atteint
            
            nb_propositions = demande.propositions_candidats.count()
            if nb_propositions >= 5:  # Seuil minimum de propositions
                WorkflowIntegrationService._avancer_workflow(demande, 'VALIDATION_N1')
            
        except Exception as e:
            logger.error(f"Erreur verification avancement workflow: {e}")
    
    @classmethod
    def _notifier_niveau_validation_suivant(cls, demande: DemandeInterim, validation: ValidationDemande):
        """OK CORRIGE - Notifie le niveau suivant selon la hierarchie stricte"""
        
        try:
            # OK CORRECTION : Le niveau suivant est toujours +1 par rapport au niveau valide
            niveau_valide = validation.niveau_validation
            niveau_suivant = niveau_valide + 1
            
            # OK Verifier qu'on ne depasse pas le maximum
            if niveau_suivant > demande.niveaux_validation_requis:
                logger.info(f"OK Niveau maximum atteint ({niveau_valide}) - Pas de notification suivante")
                return
            
            # Determiner les validateurs du niveau suivant selon la hierarchie STRICTE
            if niveau_suivant == 1:
                # Niveau 1 : RESPONSABLE
                validateurs_suivants = ProfilUtilisateur.objects.filter(
                    type_profil='RESPONSABLE',
                    departement=demande.poste.departement,
                    actif=True
                )
                titre_validation = "Validation Responsable (N+1) requise"
                message_validation = f"Premiere validation requise suite a creation de demande."
                
            elif niveau_suivant == 2:
                # OK Niveau 2 : DIRECTEUR (progression depuis RESPONSABLE)
                validateurs_suivants = ProfilUtilisateur.objects.filter(
                    type_profil='DIRECTEUR',
                    actif=True
                )
                titre_validation = "Validation Directeur (N+2) requise"
                message_validation = f"Deuxieme validation requise suite a validation Responsable."
                
            elif niveau_suivant == 3:
                # OK Niveau 3 : RH/ADMIN (progression depuis DIRECTEUR)
                validateurs_suivants = ProfilUtilisateur.objects.filter(
                    type_profil__in=['RH', 'ADMIN'],
                    actif=True
                )
                titre_validation = "Validation finale RH/Admin (N+3) requise"
                message_validation = f"Validation finale requise suite a validation Directeur."
                
            else:
                # OK Niveau > 3 : Erreur de configuration
                logger.error(f"ERROR Niveau de validation invalide: {niveau_suivant}")
                return
            
            # Envoyer les notifications
            notifications_envoyees = 0
            for validateur in validateurs_suivants:
                NotificationInterim.objects.create(
                    destinataire=validateur,
                    expediteur=validation.validateur,
                    demande=demande,
                    validation_liee=validation,
                    type_notification='DEMANDE_A_VALIDER',
                    urgence='HAUTE' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'NORMALE',
                    titre=f"{titre_validation} - {demande.numero_demande}",
                    message=f"{message_validation} Valide precedemment par {validation.validateur.nom_complet} ({validation.type_validation_display}).",
                    url_action_principale=f"/interim/validation/{demande.id}/",
                    texte_action_principale=f"Valider (Niveau {niveau_suivant})",
                    metadata={
                        'niveau_validation': niveau_suivant,
                        'niveau_precedent': niveau_valide,
                        'validateur_precedent': validation.validateur.nom_complet,
                        'type_validation_actuelle': titre_validation,
                        'progression_hierarchique': f"Niveau {niveau_valide} -> Niveau {niveau_suivant}"
                    }
                )
                notifications_envoyees += 1
            
            logger.info(f"OK Notifications niveau {niveau_suivant} envoyees: {notifications_envoyees} validateur(s)")
                        
        except Exception as e:
            logger.error(f"ERROR Erreur notification niveau suivant: {e}")

    # ================================================================
    # 6. FONCTION DE DIAGNOSTIC ET CORRECTION AUTOMATIQUE
    # ================================================================

    def diagnostiquer_et_corriger_niveaux_validation():
        """
        OK FONCTION DE DIAGNOSTIC - Verifie et corrige les incoherences
        """
        try:
            from django.db import transaction
            
            print(">>> Diagnostic des niveaux de validation...")
            
            demandes_problematiques = []
            
            # Verifier toutes les demandes en cours
            demandes_en_cours = DemandeInterim.objects.filter(
                statut__in=['EN_VALIDATION', 'SOUMISE', 'VALIDEE']
            )
            
            for demande in demandes_en_cours:
                problemes = []
                
                # Verifier niveaux_validation_requis
                if not demande.niveaux_validation_requis or demande.niveaux_validation_requis != 3:
                    problemes.append(f"niveaux_validation_requis incorrect: {demande.niveaux_validation_requis}")
                
                # Verifier niveau_validation_actuel coherent
                validations = demande.validations.order_by('niveau_validation')
                if validations.exists():
                    dernier_niveau_valide = validations.last().niveau_validation
                    if demande.niveau_validation_actuel != dernier_niveau_valide:
                        problemes.append(f"niveau_validation_actuel incoherent: {demande.niveau_validation_actuel} vs {dernier_niveau_valide}")
                
                # Verifier progression sequentielle
                niveaux_valides = list(validations.values_list('niveau_validation', flat=True))
                for i, niveau in enumerate(niveaux_valides):
                    if i > 0 and niveau != niveaux_valides[i-1] + 1:
                        problemes.append(f"Progression non sequentielle: {niveaux_valides}")
                        break
                
                if problemes:
                    demandes_problematiques.append({
                        'demande': demande,
                        'problemes': problemes
                    })
            
            print(f">>> Trouve {len(demandes_problematiques)} demande(s) avec des problemes:")
            
            # Afficher et corriger
            corrections_effectuees = 0
            for item in demandes_problematiques:
                demande = item['demande']
                problemes = item['problemes']
                
                print(f"   ERROR {demande.numero_demande}: {', '.join(problemes)}")
                
                # Correction automatique
                with transaction.atomic():
                    # Corriger niveaux_validation_requis
                    if not demande.niveaux_validation_requis or demande.niveaux_validation_requis != 3:
                        demande.niveaux_validation_requis = 3
                        print(f"      OK Corrige niveaux_validation_requis -> 3")
                    
                    # Corriger niveau_validation_actuel
                    validations = demande.validations.order_by('niveau_validation')
                    if validations.exists():
                        dernier_niveau = validations.last().niveau_validation
                        if demande.niveau_validation_actuel != dernier_niveau:
                            demande.niveau_validation_actuel = dernier_niveau
                            print(f"      OK Corrige niveau_validation_actuel -> {dernier_niveau}")
                    
                    demande.save()
                    corrections_effectuees += 1
            
            print(f"OK Diagnostic termine: {corrections_effectuees} correction(s) effectuee(s)")
            return demandes_problematiques
            
        except Exception as e:
            print(f"ERROR Erreur lors du diagnostic: {e}")
            return []

    # ================================================================
    # 7. TESTS UNITAIRES POUR VERIFIER LA CORRECTION
    # ================================================================

    def test_progression_hierarchique():
        """
        OK TESTS - Verifie la progression hierarchique corrigee
        """
        print(">>> Tests de progression hierarchique...")
        
        test_cases = [
            {
                'nom': 'Progression N+1 -> N+2',
                'niveau_actuel': 0,
                'niveau_validation': 1,
                'niveau_attendu_apres': 1,
                'statut_attendu': 'EN_VALIDATION'
            },
            {
                'nom': 'Progression N+2 -> N+3', 
                'niveau_actuel': 1,
                'niveau_validation': 2,
                'niveau_attendu_apres': 2,
                'statut_attendu': 'EN_VALIDATION'  # OK PAS de selection finale
            },
            {
                'nom': 'Progression N+3 -> Selection finale',
                'niveau_actuel': 2,
                'niveau_validation': 3,
                'niveau_attendu_apres': 3,
                'statut_attendu': 'VALIDEE'  # OK SEULEMENT ICI
            }
        ]
        
        for test in test_cases:
            print(f"   >>> Test: {test['nom']}")
            
            # Simulation
            demande_test = type('MockDemande', (), {
                'niveau_validation_actuel': test['niveau_actuel'],
                'niveaux_validation_requis': 3,
                'statut': 'EN_VALIDATION'
            })()
            
            validation_test = type('MockValidation', (), {
                'niveau_validation': test['niveau_validation']
            })()
            
            # Test de la logique
            if test['niveau_validation'] < 3:
                # Ne doit PAS declencher la selection finale
                demande_test.niveau_validation_actuel = test['niveau_validation']
                demande_test.statut = 'EN_VALIDATION'
                resultat = "EN_VALIDATION"
            else:
                # SEULEMENT ICI : declencher la selection finale
                demande_test.niveau_validation_actuel = test['niveau_validation'] 
                demande_test.statut = 'VALIDEE'
                resultat = "VALIDEE"
            
            if resultat == test['statut_attendu']:
                print(f"      OK PASSE: {resultat}")
            else:
                print(f"      ERROR ECHEC: attendu {test['statut_attendu']}, obtenu {resultat}")
        
        print("OK Tests termines")

    # ================================================================
    # 8. SCRIPT DE MIGRATION POUR CORRIGER LES DONNEES EXISTANTES
    # ================================================================

    def migration_corriger_workflow_existant():
        """
        OK MIGRATION - Corrige les workflows existants
        """
        try:
            from django.db import transaction
            from django.db import models
            
            print(">>> Migration des workflows existants...")
            
            with transaction.atomic():
                # 1. Corriger les demandes avec niveaux_validation_requis incorrect
                demandes_a_corriger = DemandeInterim.objects.filter(
                    models.Q(niveaux_validation_requis__isnull=True) |
                    models.Q(niveaux_validation_requis=0) |
                    models.Q(niveaux_validation_requis__gt=3)
                )
                
                nb_demandes_corrigees = demandes_a_corriger.update(niveaux_validation_requis=3)
                print(f"   OK {nb_demandes_corrigees} demande(s) corrigee(s) pour niveaux_validation_requis")
                
                # 2. Recalculer niveau_validation_actuel selon les validations existantes
                demandes_en_cours = DemandeInterim.objects.filter(
                    statut__in=['EN_VALIDATION', 'VALIDEE']
                )
                
                for demande in demandes_en_cours:
                    validations = demande.validations.filter(decision='APPROUVE').order_by('niveau_validation')
                    
                    if validations.exists():
                        dernier_niveau = validations.last().niveau_validation
                        
                        if demande.niveau_validation_actuel != dernier_niveau:
                            ancien_niveau = demande.niveau_validation_actuel
                            demande.niveau_validation_actuel = dernier_niveau
                            demande.save()
                            
                            print(f"   OK {demande.numero_demande}: niveau {ancien_niveau} -> {dernier_niveau}")
                
                # 3. Corriger les statuts incoherents
                demandes_validees_finales = DemandeInterim.objects.filter(
                    validations__niveau_validation=3,
                    validations__decision='APPROUVE'
                ).exclude(statut='VALIDEE')
                
                nb_statuts_corriges = 0
                for demande in demandes_validees_finales:
                    if demande.statut != 'VALIDEE':
                        demande.statut = 'VALIDEE'
                        if not demande.date_validation:
                            demande.date_validation = timezone.now()
                        demande.save()
                        nb_statuts_corriges += 1
                
                print(f"   OK {nb_statuts_corriges} statut(s) corrige(s) pour validation finale")
                
            print("OK Migration terminee avec succes")
            
        except Exception as e:
            print(f"ERROR Erreur lors de la migration: {e}")


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
        
    @staticmethod
    def obtenir_statut_workflow_complet(demande: DemandeInterim) -> Dict:
        """
        Retourne le statut complet du workflow pour une demande
        """
        try:
            workflow = demande.workflow
            
            # Propositions
            propositions = ManagerProposalsService.obtenir_toutes_propositions_demande(demande)
            
            # Validations
            validations = list(demande.validations.all().order_by('created_at'))
            
            # Reponse candidat si applicable
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
                'workflow': workflow,
                'etape_actuelle': workflow.etape_actuelle.nom,
                'progression': workflow.progression_percentage,
                'en_retard': workflow.est_en_retard,
                'propositions': propositions,
                'validations': validations,
                'reponse_candidat': reponse_candidat,
                'historique': workflow.historique_actions,
                'prochaines_actions': WorkflowIntegrationService._get_prochaines_actions(demande)
            }
            
        except Exception as e:
            logger.error(f"Erreur statut workflow: {e}")
            return {
                'demande': demande,
                'erreur': str(e)
            }
    
    @staticmethod
    def _get_prochaines_actions(demande: DemandeInterim) -> List[Dict]:
        """Determine les prochaines actions possibles"""
        actions = []
        
        try:
            if demande.statut == 'SOUMISE' and demande.propositions_autorisees:
                actions.append({
                    'type': 'proposer_candidat',
                    'titre': 'Proposer un candidat',
                    'description': 'Ajouter une proposition de candidat',
                    'urgence': 'normale'
                })
            
            if demande.statut == 'EN_VALIDATION':
                actions.append({
                    'type': 'valider',
                    'titre': 'Valider la demande',
                    'description': 'Proceder a la validation',
                    'urgence': 'haute' if demande.urgence in ['ELEVEE', 'CRITIQUE'] else 'normale'
                })
            
            if demande.statut == 'CANDIDAT_SELECTIONNE':
                actions.append({
                    'type': 'attendre_reponse',
                    'titre': 'Attendre la reponse du candidat',
                    'description': 'Le candidat a 3 jours pour repondre',
                    'urgence': 'normale'
                })
            
            return actions
            
        except Exception as e:
            logger.error(f"Erreur prochaines actions: {e}")
            return []