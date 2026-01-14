# -*- coding: utf-8 -*-
"""
Service de scoring automatique des candidats - Version 4.2 HARMONISE CORRIGÉ
Compatible avec kelio_api_simplifie.py V4.2
Integration complete avec les nouvelles API Kelio et donnees enrichies
CORRECTION: Utilisation systématique des pondérations ConfigurationScoring avec fallbacks

Version : 4.2 - Harmonisation avec Kelio API V4.2 + ConfigurationScoring + LOGGING AVANCÉ
Auteur : Systeme Django Interim
Date : 2025

NOUVEAUTÉS V4.2 - LOGGING AVANCÉ :
- ✅ Système de logging avec résumés détaillés par calcul de score
- ✅ Détection automatique d'anomalies (scores anormaux, données manquantes)
- ✅ Logs dans fichiers ET base de données (JournalLog)
- ✅ Métriques de performance intégrées
- ✅ Configuration via settings.py
"""

from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple, Optional
import math
import logging
import json
import traceback
from datetime import timedelta, date

from ..models import (
    ProfilUtilisateur, DemandeInterim, PropositionCandidat, 
    ScoreDetailCandidat, ConfigurationScoring, CompetenceUtilisateur, 
    FormationUtilisateur, AbsenceUtilisateur, DisponibiliteUtilisateur,
    # Nouveaux modeles Kelio V4.2
    ProfilUtilisateurKelio, ProfilUtilisateurExtended, CacheApiKelio, 
    ConfigurationApiKelio
)

# Import optionnel JournalLog
try:
    from ..models import JournalLog
    JOURNAL_LOG_AVAILABLE = True
except ImportError:
    JOURNAL_LOG_AVAILABLE = False

# Import des utilitaires Kelio V4.2
from .kelio_api_simplifie import (
    safe_get_attribute, safe_date_conversion, generer_cle_cache_kelio,
    KelioBaseError, KelioDataError
)

# ================================================================
# CONFIGURATION DU LOGGING AVANCÉ POUR SCORING
# ================================================================
SCORING_LOGGING_CONFIG = getattr(settings, 'SCORING_LOGGING', {
    'enabled': True,
    'log_to_db': True,
    'log_anomalies': True,
    'log_performance': True,
    'anomaly_thresholds': {
        'score_min_warning': 20,          # Score < 20 = warning
        'score_max_warning': 95,          # Score > 95 = vérifier
        'duration_warning_ms': 500,       # Calcul > 500ms = warning
        'missing_data_warning': True,     # Alerter si données Kelio manquantes
        'zero_competences_warning': True, # Alerter si aucune compétence
    }
})

# ================================================================
# CLASSE DE LOGGING AVANCÉ POUR SCORING
# ================================================================

class ScoringLogger:
    """Logger avancé pour le service de scoring avec détection d'anomalies"""
    
    def __init__(self, operation_type='SCORING'):
        self.operation_type = operation_type
        self.base_logger = logging.getLogger('scoring.service')
        self.config = SCORING_LOGGING_CONFIG
        self.start_time = None
        self.stats = {
            'candidats_scores': 0,
            'scores_calcules': [],
            'erreurs': 0,
            'warnings': 0,
            'anomalies': [],
            'kelio_data_used': 0,
            'fallback_used': 0
        }
    
    def _safe_str(self, text):
        """Convertit en string safe pour les logs"""
        try:
            if isinstance(text, str):
                return text.encode('ascii', 'ignore').decode('ascii')
            return str(text).encode('ascii', 'ignore').decode('ascii')
        except:
            return "ENCODING_ERROR"
    
    def _log(self, level, msg, extra_data=None):
        """Log avec protection"""
        try:
            safe_msg = self._safe_str(msg)
            getattr(self.base_logger, level)(safe_msg)
            
            if level == 'error':
                self.stats['erreurs'] += 1
            elif level == 'warning':
                self.stats['warnings'] += 1
            
            # Log en BDD si activé
            if self.config.get('log_to_db') and JOURNAL_LOG_AVAILABLE and level in ['error', 'warning']:
                self._log_to_db(level, safe_msg, extra_data)
        except:
            pass
    
    def _log_to_db(self, level, message, extra_data=None):
        """Log dans JournalLog"""
        try:
            severite_map = {'debug': 'DEBUG', 'info': 'INFO', 'warning': 'WARNING', 'error': 'ERROR'}
            JournalLog.objects.create(
                source='SCORING_SERVICE',
                categorie='SCORING',
                action=f'SCORING_{self.operation_type}',
                description=message[:500],
                severite=severite_map.get(level, 'INFO'),
                donnees_apres=extra_data if isinstance(extra_data, dict) else None
            )
        except:
            pass
    
    def info(self, msg, extra_data=None): self._log('info', msg, extra_data)
    def debug(self, msg, extra_data=None): self._log('debug', msg, extra_data)
    def warning(self, msg, extra_data=None): self._log('warning', msg, extra_data)
    def error(self, msg, extra_data=None): self._log('error', msg, extra_data)
    
    def start_scoring(self, demande=None, nb_candidats=0):
        """Démarre le tracking d'un calcul de scoring"""
        self.start_time = timezone.now()
        self.stats = {
            'candidats_scores': 0, 'scores_calcules': [], 'erreurs': 0,
            'warnings': 0, 'anomalies': [], 'kelio_data_used': 0, 'fallback_used': 0
        }
        
        msg = f"[SCORING-START] {self.operation_type}"
        if demande:
            msg += f" - Demande: {demande.numero_demande}"
        msg += f" - {nb_candidats} candidat(s) a scorer"
        self.info(msg)
        return self.start_time
    
    def end_scoring(self, demande=None):
        """Termine le tracking avec résumé"""
        duration_ms = (timezone.now() - self.start_time).total_seconds() * 1000 if self.start_time else 0
        
        # Calcul statistiques scores
        if self.stats['scores_calcules']:
            score_moyen = sum(self.stats['scores_calcules']) / len(self.stats['scores_calcules'])
            score_min = min(self.stats['scores_calcules'])
            score_max = max(self.stats['scores_calcules'])
        else:
            score_moyen = score_min = score_max = 0
        
        # Détection anomalies globales
        self._detect_global_anomalies(duration_ms)
        
        # Résumé
        msg = f"[SCORING-END] {self.operation_type} en {duration_ms:.0f}ms"
        msg += f" | Candidats: {self.stats['candidats_scores']}"
        msg += f" | Scores: min={score_min}, moy={score_moyen:.1f}, max={score_max}"
        msg += f" | Kelio: {self.stats['kelio_data_used']}, Fallback: {self.stats['fallback_used']}"
        
        if self.stats['anomalies']:
            msg += f" | ANOMALIES: {len(self.stats['anomalies'])}"
            self.warning(msg)
        else:
            self.info(msg)
        
        # Log résumé en BDD
        if self.config.get('log_to_db') and JOURNAL_LOG_AVAILABLE:
            self._log_resume_to_db(demande, duration_ms, score_moyen, score_min, score_max)
        
        return {
            'duration_ms': duration_ms,
            'candidats_scores': self.stats['candidats_scores'],
            'score_moyen': score_moyen,
            'anomalies': self.stats['anomalies']
        }
    
    def _detect_global_anomalies(self, duration_ms):
        """Détecte les anomalies globales"""
        thresholds = self.config.get('anomaly_thresholds', {})
        
        # Anomalie: Durée excessive
        if duration_ms >= thresholds.get('duration_warning_ms', 500):
            self._add_anomaly('WARNING', 'DUREE_ELEVEE',
                f"Calcul scoring en {duration_ms:.0f}ms (seuil: {thresholds.get('duration_warning_ms', 500)}ms)")
        
        # Anomalie: Trop de fallbacks
        if self.stats['candidats_scores'] > 0:
            fallback_rate = self.stats['fallback_used'] / self.stats['candidats_scores']
            if fallback_rate > 0.5:
                self._add_anomaly('WARNING', 'FALLBACK_ELEVE',
                    f"{fallback_rate*100:.0f}% des scores utilisent le fallback (données Kelio manquantes)")
    
    def _add_anomaly(self, severity, anomaly_type, description):
        """Ajoute une anomalie"""
        self.stats['anomalies'].append({
            'severity': severity, 'type': anomaly_type,
            'description': description, 'timestamp': timezone.now().isoformat()
        })
    
    def _log_resume_to_db(self, demande, duration_ms, score_moyen, score_min, score_max):
        """Log le résumé en BDD"""
        try:
            severite = 'INFO'
            if self.stats['anomalies']:
                severite = 'WARNING'
            
            JournalLog.objects.create(
                source='SCORING_SERVICE',
                categorie='RESUME',
                action=f'SCORING_RESUME_{self.operation_type}',
                description=f"Scoring {self.operation_type}: {self.stats['candidats_scores']} candidats | "
                           f"Scores: {score_min}-{score_max} (moy: {score_moyen:.1f}) | "
                           f"Duree: {duration_ms:.0f}ms | Anomalies: {len(self.stats['anomalies'])}",
                severite=severite,
                donnees_apres={
                    'candidats_scores': self.stats['candidats_scores'],
                    'score_moyen': score_moyen,
                    'score_min': score_min,
                    'score_max': score_max,
                    'duration_ms': duration_ms,
                    'kelio_data_used': self.stats['kelio_data_used'],
                    'fallback_used': self.stats['fallback_used'],
                    'anomalies': self.stats['anomalies'],
                    'demande_id': demande.id if demande else None
                }
            )
        except:
            pass
    
    def log_score_candidat(self, candidat, score, criteres=None, kelio_used=False):
        """Log le score d'un candidat"""
        self.stats['candidats_scores'] += 1
        self.stats['scores_calcules'].append(score)
        
        if kelio_used:
            self.stats['kelio_data_used'] += 1
        else:
            self.stats['fallback_used'] += 1
        
        # Détection anomalies individuelles
        thresholds = self.config.get('anomaly_thresholds', {})
        if score < thresholds.get('score_min_warning', 20):
            self._add_anomaly('WARNING', 'SCORE_TRES_BAS',
                f"Score très bas pour {candidat.matricule}: {score}")
        elif score > thresholds.get('score_max_warning', 95):
            self._add_anomaly('INFO', 'SCORE_TRES_HAUT',
                f"Score très élevé pour {candidat.matricule}: {score} (à vérifier)")
        
        self.debug(f"[SCORE] {candidat.matricule}: {score}/100 (Kelio: {'Oui' if kelio_used else 'Non'})")
    
    def log_kelio_data_missing(self, candidat, data_type):
        """Log les données Kelio manquantes"""
        if self.config.get('anomaly_thresholds', {}).get('missing_data_warning', True):
            self.debug(f"[KELIO-MISSING] {candidat.matricule}: données {data_type} non disponibles")

# Logger global pour compatibilité
try:
    from django.conf import settings as django_settings
    logger = django_settings.get_safe_kelio_logger()
except:
    logger = ScoringLogger('GLOBAL')

class ScoringInterimService:
    """
    Service principal pour le calcul de scores des candidats - Version 4.2 Harmonise
    Integration complete avec les nouvelles API Kelio V4.2 et ConfigurationScoring
    """
    
    def __init__(self, configuration_kelio=None):
        """Initialise le service avec integration Kelio V4.2"""
        self.scores_cache = {}
        self.kelio_config = configuration_kelio or ConfigurationApiKelio.objects.filter(actif=True).first()
        
        # Configuration de scoring par defaut CORRIGÉ - harmonise avec ConfigurationScoring
        self.default_weights = {
            'similarite_poste': 0.25,
            'competences': 0.25,      # CORREC: unifier les noms avec le modele
            'competences_kelio': 0.25, # Alias pour compatibilite
            'experience': 0.20,       # CORREC: unifier les noms avec le modele
            'experience_kelio': 0.20,  # Alias pour compatibilite
            'disponibilite': 0.15,    # CORREC: unifier les noms avec le modele
            'disponibilite_kelio': 0.15, # Alias pour compatibilite
            'proximite': 0.10,
            'anciennete': 0.05
        }
        
        # NOUVEAU: Configuration par défaut pour les bonus (fallback)
        self.default_bonus = {
            'bonus_proposition_humaine': 5,
            'bonus_experience_similaire': 8,
            'bonus_recommandation': 10,
            'bonus_manager_direct': 12,
            'bonus_chef_equipe': 8,
            'bonus_responsable': 15,
            'bonus_directeur': 18,
            'bonus_rh': 20,
            'bonus_admin': 20,
            'bonus_superuser': 0
        }
        
        # NOUVEAU: Configuration par défaut pour les pénalités (fallback)
        self.default_penalties = {
            'penalite_indisponibilite_partielle': 15,
            'penalite_indisponibilite_totale': 50,
            'penalite_distance_excessive': 10
        }
        
        logger.info(">>> ScoringInterimService initialise avec integration Kelio et ConfigurationScoring")
    
    def calculer_score_candidat_v41(self, candidat: ProfilUtilisateur, 
                                   demande: DemandeInterim,
                                   config: ConfigurationScoring = None,
                                   utiliser_cache: bool = True) -> int:
        """
        Calcule le score total d'un candidat pour une demande d'interim
        Version 4.2 avec integration complete des donnees Kelio, ConfigurationScoring et logging avancé
        """
        # ===== LOGGING AVANCÉ V4.2 =====
        score_logger = ScoringLogger('SCORE_CANDIDAT')
        kelio_used = False
        
        try:
            # Cache intelligent avec cle Kelio
            cache_key = self._generer_cle_cache_score(candidat, demande)
            
            if utiliser_cache and cache_key in self.scores_cache:
                logger.debug(f">>> Score trouve en cache pour {candidat.matricule}")
                return self.scores_cache[cache_key]
            
            # CORRECTION: Recuperer la configuration de scoring avec fallback
            if not config:
                config = ConfigurationScoring.get_configuration_pour_demande(demande)
            
            # Si toujours pas de configuration, utiliser le calcul basique avec poids par défaut
            if not config:
                logger.warning(f"WARNING Aucune configuration scoring trouvee pour demande {demande.id}, utilisation fallback")
                score = self._calculer_score_basique_v41(candidat, demande)
                score_logger.log_score_candidat(candidat, score, kelio_used=False)
                return score
            
            # Calcul detaille avec configuration et donnees Kelio V4.2
            scores_criteres = self._calculer_scores_criteres_v41(candidat, demande, config)
            score_final = self._calculer_score_final_v41(scores_criteres, config)
            
            # Vérifier si données Kelio utilisées
            kelio_used = any(k for k in scores_criteres.keys() if 'kelio' in k.lower() and scores_criteres[k] > 0)
            
            # CORRECTION: Bonus avec configuration ou fallback
            bonus_kelio = self._calculer_bonus_donnees_kelio(candidat, demande, config)
            score_final = min(100, score_final + bonus_kelio)
            
            # Mise en cache avec duree basee sur la configuration
            cache_duration = getattr(config, 'cache_duration_minutes', 60) * 60
            cache.set(cache_key, score_final, cache_duration)
            self.scores_cache[cache_key] = score_final
            
            # ===== LOG SCORE =====
            score_logger.log_score_candidat(candidat, score_final, criteres=scores_criteres, kelio_used=kelio_used)
            
            logger.info(f"OK Score V4.2 calcule pour {candidat.matricule}: {score_final} (config: {config.nom if config else 'fallback'})")
            return score_final
            
        except KelioBaseError as e:
            logger.error(f"ERROR Erreur Kelio lors calcul score {candidat.matricule}: {e}")
            score_logger.log_kelio_data_missing(candidat, 'KELIO_API')
            return self._calculer_score_fallback(candidat, demande)
        except Exception as e:
            logger.error(f"ERROR Erreur calcul score candidat {candidat.matricule}: {e}")
            score_logger.error(f"[EXCEPTION] {e}")
            return 50  # Score neutre par defaut
    
    def _calculer_scores_criteres_v41(self, candidat: ProfilUtilisateur, 
                                     demande: DemandeInterim,
                                     config: ConfigurationScoring) -> Dict[str, int]:
        """Calcule les scores pour chaque critere avec donnees Kelio V4.2 et ConfigurationScoring"""
        
        scores = {
            'similarite_poste': self._score_similarite_poste_v41(candidat, demande),
            'competences': self._score_competences_kelio_v41(candidat, demande),
            'competences_kelio': self._score_competences_kelio_v41(candidat, demande),  # Alias
            'experience': self._score_experience_kelio_v41(candidat, demande),
            'experience_kelio': self._score_experience_kelio_v41(candidat, demande),    # Alias
            'disponibilite': self._score_disponibilite_kelio_v41(candidat, demande),
            'disponibilite_kelio': self._score_disponibilite_kelio_v41(candidat, demande), # Alias
            'proximite': self._score_proximite_v41(candidat, demande),
            'anciennete': self._score_anciennete_v41(candidat),
            'formations_kelio': self._score_formations_kelio_v41(candidat, demande)
        }
        
        logger.debug(f">>> Scores criteres V4.2 pour {candidat.matricule}: {scores}")
        return scores
    
    def _score_competences_kelio_v41(self, candidat: ProfilUtilisateur, 
                                    demande: DemandeInterim) -> int:
        """Score base sur les competences avec donnees Kelio V4.2"""
        try:
            score_base = 30  # Score minimal
            
            # Competences avec donnees Kelio enrichies
            competences_kelio = CompetenceUtilisateur.objects.filter(
                utilisateur=candidat,
                source_donnee='KELIO'
            )
            
            if competences_kelio.exists():
                # Utiliser les niveaux Kelio pour un scoring plus precis
                niveau_moyen_kelio = 0
                bonus_certifications = 0
                bonus_recent = 0
                
                for comp in competences_kelio:
                    # Conversion niveau Kelio vers score
                    if hasattr(comp, 'kelio_level'):
                        niveau_kelio = comp.kelio_level.lower()
                        if 'expert' in niveau_kelio:
                            niveau_score = 95
                        elif 'avance' in niveau_kelio or 'confirme' in niveau_kelio:
                            niveau_score = 80
                        elif 'intermediaire' in niveau_kelio:
                            niveau_score = 65
                        elif 'debutant' in niveau_kelio:
                            niveau_score = 40
                        else:
                            niveau_score = comp.niveau_maitrise * 20  # Fallback
                        
                        niveau_moyen_kelio += niveau_score
                    
                    # Bonus certifications
                    if comp.certifie:
                        bonus_certifications += 5
                    
                    # Bonus competences recentes (evaluees recemment)
                    if comp.date_evaluation and (date.today() - comp.date_evaluation).days <= 365:
                        bonus_recent += 3
                
                # Calcul du score base sur Kelio
                if competences_kelio.count() > 0:
                    niveau_moyen_kelio = niveau_moyen_kelio / competences_kelio.count()
                    score_base = int(niveau_moyen_kelio * 0.7)  # 70% du score max base sur Kelio
                
                # Application des bonus
                score_base += min(bonus_certifications, 15)  # Max 15 points
                score_base += min(bonus_recent, 10)  # Max 10 points
                
                logger.debug(f">>> Score competences Kelio pour {candidat.matricule}: {score_base}")
            else:
                # Fallback sur les competences internes
                score_base = self._score_competences_interne(candidat)
                logger.debug(f"WARNING Fallback competences internes pour {candidat.matricule}: {score_base}")
            
            return min(score_base, 100)
            
        except Exception as e:
            logger.warning(f"WARNING Erreur score competences Kelio V4.2: {e}")
            return self._score_competences_interne(candidat)
    
    def _score_experience_kelio_v41(self, candidat: ProfilUtilisateur, 
                                   demande: DemandeInterim) -> int:
        """Score base sur l'experience avec donnees Kelio V4.2"""
        try:
            score = 40  # Base
            
            # Utiliser les donnees etendues Kelio
            if hasattr(candidat, 'extended_data') and candidat.extended_data:
                extended = candidat.extended_data
                
                # Anciennete avec donnees Kelio precises
                if extended.date_embauche:
                    anciennete_jours = (date.today() - extended.date_embauche).days
                    anciennete_annees = anciennete_jours / 365
                    score += min(anciennete_annees * 6, 30)  # Max 30 points
                
                # Coefficient et niveau de classification Kelio
                if extended.coefficient:
                    # Bonus selon le coefficient (supposant que plus eleve = plus experimente)
                    try:
                        coeff_num = float(extended.coefficient.replace(',', '.'))
                        if coeff_num >= 300:
                            score += 15
                        elif coeff_num >= 200:
                            score += 10
                        elif coeff_num >= 100:
                            score += 5
                    except:
                        pass
                
                # Statut professionnel
                if extended.statut_professionnel:
                    if 'cadre' in extended.statut_professionnel.lower():
                        score += 10
                    elif 'maitrise' in extended.statut_professionnel.lower():
                        score += 5
            
            # Experience missions interim passees (enrichi)
            missions_reussies = PropositionCandidat.objects.filter(
                candidat_propose=candidat,
                statut__in=['VALIDEE', 'TERMINEE']
            ).count()
            
            score += min(missions_reussies * 8, 25)  # Max 25 points
            
            # Bonus si donnees professionnelles Kelio disponibles
            if hasattr(candidat, 'kelio_data') and candidat.kelio_data:
                kelio_data = candidat.kelio_data
                if kelio_data.kelio_employee_key:
                    score += 5  # Bonus donnees Kelio completes
            
            # Verifier les experiences professionnelles Kelio en cache
            cache_key = generer_cle_cache_kelio('professional_experience', {'matricule': candidat.matricule})
            experiences_kelio = self._get_cached_kelio_data('professional_experience', candidat.matricule)
            
            if experiences_kelio and experiences_kelio.get('experiences_professionnelles'):
                nb_experiences = len(experiences_kelio['experiences_professionnelles'])
                score += min(nb_experiences * 3, 10)  # Max 10 points pour experiences Kelio
            
            return min(score, 100)
            
        except Exception as e:
            logger.warning(f"WARNING Erreur score experience Kelio V4.2: {e}")
            return self._score_experience_fallback(candidat, demande)
    
    def _score_disponibilite_kelio_v41(self, candidat: ProfilUtilisateur, 
                                      demande: DemandeInterim) -> int:
        """Score base sur la disponibilite avec donnees Kelio V4.2 - CORRIGE"""
        try:
            # Verifications de base
            if candidat.statut_employe != 'ACTIF':
                return 0
            
            if not candidat.actif:
                return 0
            
            score = 70  # Base pour employe actif
            
            # Verifier disponibilite interim avec donnees etendues
            if hasattr(candidat, 'extended_data') and candidat.extended_data:
                if not candidat.extended_data.disponible_interim:
                    return 20  # Score tres bas si pas disponible pour interim
            
            # Verifications avancees si dates disponibles
            if demande.date_debut and demande.date_fin:
                
                # 1. Absences en conflit (sources multiples)
                # Absences internes
                absences_internes = AbsenceUtilisateur.objects.filter(
                    utilisateur=candidat,
                    date_debut__lte=demande.date_fin,
                    date_fin__gte=demande.date_debut
                ).exists()
                
                if absences_internes:
                    score -= 30
                
                # Absences Kelio (plus precises)
                absences_kelio = self._get_cached_kelio_data('absence_requests', candidat.matricule)
                if absences_kelio and absences_kelio.get('demandes_absences'):
                    for absence in absences_kelio['demandes_absences']:
                        absence_debut = safe_date_conversion(absence.get('startDate'))
                        absence_fin = safe_date_conversion(absence.get('endDate'))
                        
                        if absence_debut and absence_fin:
                            if absence_debut <= demande.date_fin and absence_fin >= demande.date_debut:
                                statut = absence.get('requestState', '')
                                if statut in ['VALIDEE', 'APPROUVEE']:
                                    score -= 40  # Conflit confirme
                                elif statut == 'EN_ATTENTE':
                                    score -= 20  # Conflit potentiel
                
                # 2. Contrats de travail Kelio
                contrats_kelio = self._get_cached_kelio_data('labor_contracts', candidat.matricule)
                if contrats_kelio and contrats_kelio.get('contrats_travail'):
                    for contrat in contrats_kelio['contrats_travail']:
                        fin_contrat = safe_date_conversion(contrat.get('endDate'))
                        if fin_contrat and fin_contrat < demande.date_fin:
                            score -= 50  # Contrat se termine avant la fin de mission
                
                # 3. Indisponibilites declarees
                indispos = DisponibiliteUtilisateur.objects.filter(
                    utilisateur=candidat,
                    type_disponibilite='INDISPONIBLE',
                    date_debut__lte=demande.date_fin,
                    date_fin__gte=demande.date_debut
                ).exists()
                
                if indispos:
                    score -= 35
                
                # 4. Autres missions en conflit
                missions_conflit = PropositionCandidat.objects.filter(
                    candidat_propose=candidat,
                    statut__in=['VALIDEE', 'EN_COURS'],
                    demande_interim__date_debut__lte=demande.date_fin,
                    demande_interim__date_fin__gte=demande.date_debut
                ).exists()
                
                if missions_conflit:
                    score -= 50
                
                # 5. Bonus disponibilite immediate
                jours_avant = (demande.date_debut - date.today()).days
                if jours_avant <= 1:
                    score += 15  # Disponible immediatement
                elif jours_avant <= 3:
                    score += 10  # Disponible rapidement
                elif jours_avant <= 7:
                    score += 5   # Disponible a court terme
            
            # Bonus temps de travail compatible avec donnees disponibles
            try:
                if hasattr(candidat, 'extended_data') and candidat.extended_data and candidat.extended_data.temps_travail:
                    temps_travail = float(candidat.extended_data.temps_travail)
                    
                    # Estimer la duree de travail requise selon la duree de mission
                    if demande.date_debut and demande.date_fin:
                        duree_mission_jours = (demande.date_fin - demande.date_debut).days + 1
                        
                        # Pour missions courtes (< 5 jours), privilégier disponibilité immédiate
                        if duree_mission_jours <= 5:
                            if temps_travail >= 1.0:  # Temps plein
                                score += 10
                            elif temps_travail >= 0.8:  # 80% ou plus
                                score += 8
                            elif temps_travail >= 0.5:  # Mi-temps
                                score += 5
                        else:
                            # Pour missions longues, temps plein préférable
                            if temps_travail >= 1.0:  # Temps plein
                                score += 15
                            elif temps_travail >= 0.8:  # 80% ou plus
                                score += 10
                            elif temps_travail >= 0.5:  # Mi-temps
                                score += 3
                            else:
                                score -= 5  # Temps partiel trop limité
                    else:
                        # Pas de dates définies, favoriser temps plein
                        if temps_travail >= 1.0:
                            score += 10
                        elif temps_travail >= 0.8:
                            score += 5
                
            except (ValueError, TypeError, AttributeError) as e:
                logger.debug(f"Erreur calcul bonus temps travail pour {candidat.matricule}: {e}")
                # Continuer sans bonus temps de travail
            
            return max(0, min(score, 100))
            
        except Exception as e:
            logger.warning(f"WARNING Erreur score disponibilite Kelio V4.2: {e}")
            return self._score_disponibilite_fallback(candidat, demande)
    
    def _score_formations_kelio_v41(self, candidat: ProfilUtilisateur, 
                                   demande: DemandeInterim) -> int:
        """Score base sur les formations avec donnees Kelio V4.2"""
        try:
            score = 0
            
            # Formations avec source Kelio
            formations_kelio = FormationUtilisateur.objects.filter(
                utilisateur=candidat,
                source_donnee='KELIO'
            )
            
            if formations_kelio.exists():
                for formation in formations_kelio:
                    # Points selon le type de formation
                    if formation.certifiante:
                        score += 8
                    else:
                        score += 4
                    
                    # Bonus si diplome obtenu
                    if formation.diplome_obtenu:
                        score += 3
                    
                    # Bonus formations recentes
                    if formation.date_fin and (date.today() - formation.date_fin).days <= 1095:  # 3 ans
                        score += 2
            
            # Verifier formations initiales Kelio en cache
            formations_initiales = self._get_cached_kelio_data('initial_formations', candidat.matricule)
            if formations_initiales and formations_initiales.get('formations_initiales'):
                score += len(formations_initiales['formations_initiales']) * 5  # 5 points par formation initiale
            
            # Verifier historique formations Kelio en cache
            historique_formations = self._get_cached_kelio_data('training_history', candidat.matricule)
            if historique_formations and historique_formations.get('formations_historique'):
                nb_formations = len(historique_formations['formations_historique'])
                score += min(nb_formations * 3, 15)  # Max 15 points
            
            return min(score, 30)  # Score maximal pour formations
            
        except Exception as e:
            logger.warning(f"WARNING Erreur score formations Kelio V4.2: {e}")
            return 0
    
    def _score_similarite_poste_v41(self, candidat: ProfilUtilisateur, 
                                   demande: DemandeInterim) -> int:
        """Score base sur la similarite de poste avec donnees Kelio V4.2"""
        try:
            if not candidat.poste or not demande.poste:
                return 40
            
            score = 50  # Base
            
            # Meme poste exact
            if candidat.poste == demande.poste:
                return 100
            
            # Verifications avec donnees Kelio si disponibles
            if hasattr(candidat, 'kelio_data') and candidat.kelio_data:
                kelio_data = candidat.kelio_data
                
                # Utiliser les donnees organisationnelles Kelio pour comparaison plus fine
                affectations_postes = self._get_cached_kelio_data('job_assignments', candidat.matricule)
                if affectations_postes and affectations_postes.get('affectations_postes'):
                    for affectation in affectations_postes['affectations_postes']:
                        job_desc = affectation.get('jobDescription', '').lower()
                        poste_demande = demande.poste.titre.lower()
                        
                        # Comparaison textuelle des descriptions
                        if job_desc and (poste_demande in job_desc or job_desc in poste_demande):
                            score += 20
                            break
            
            # Comparaisons classiques ameliorees
            # Meme departement
            if candidat.poste.departement == demande.poste.departement:
                score += 25
            
            # Meme niveau de responsabilite
            if candidat.poste.niveau_responsabilite == demande.poste.niveau_responsabilite:
                score += 20
            
            # Meme site
            if candidat.poste.site == demande.poste.site:
                score += 15
            
            # Bonus si meme famille de metiers (approximation par mots-cles)
            candidat_titre = candidat.poste.titre.lower()
            demande_titre = demande.poste.titre.lower()
            
            mots_cles_communs = set(candidat_titre.split()) & set(demande_titre.split())
            if len(mots_cles_communs) >= 2:
                score += 10
            
            return min(score, 100)
            
        except Exception as e:
            logger.warning(f"WARNING Erreur score similarite poste V4.2: {e}")
            return 40
    
    def _score_proximite_v41(self, candidat: ProfilUtilisateur, 
                            demande: DemandeInterim) -> int:
        """Score base sur la proximite geographique avec donnees Kelio V4.2"""
        try:
            if not candidat.site or not demande.poste.site:
                return 40
            
            # Meme site = score maximum
            if candidat.site == demande.poste.site:
                return 100
            
            score = 50  # Base pour sites differents
            
            # Utiliser les donnees etendues pour le rayon de deplacement
            if hasattr(candidat, 'extended_data') and candidat.extended_data:
                rayon = candidat.extended_data.rayon_deplacement_km or 25
                
                # Bonus progressif selon le rayon
                if rayon >= 100:
                    score += 25
                elif rayon >= 75:
                    score += 20
                elif rayon >= 50:
                    score += 15
                elif rayon >= 25:
                    score += 10
                else:
                    score -= 10  # Malus si rayon tres limite
            
            # Meme ville
            if candidat.site.ville == demande.poste.site.ville:
                score += 20
            
            # Meme region (approximation par code postal)
            candidat_cp = getattr(candidat.site, 'code_postal', '')
            demande_cp = getattr(demande.poste.site, 'code_postal', '')
            
            if candidat_cp and demande_cp and candidat_cp[:2] == demande_cp[:2]:
                score += 10  # Meme departement
            
            return min(score, 90)  # Max 90 pour sites differents
            
        except Exception as e:
            logger.warning(f"WARNING Erreur score proximite V4.2: {e}")
            return 50
    
    def _score_anciennete_v41(self, candidat: ProfilUtilisateur) -> int:
        """Score base sur l'anciennete avec donnees Kelio V4.2"""
        try:
            # Utiliser les donnees Kelio si disponibles
            date_embauche = None
            
            if hasattr(candidat, 'kelio_data') and candidat.kelio_data and candidat.kelio_data.date_embauche_kelio:
                date_embauche = candidat.kelio_data.date_embauche_kelio
            elif hasattr(candidat, 'extended_data') and candidat.extended_data and candidat.extended_data.date_embauche:
                date_embauche = candidat.extended_data.date_embauche
            
            if not date_embauche:
                return 40
            
            anciennete_jours = (date.today() - date_embauche).days
            anciennete_annees = anciennete_jours / 365
            
            # Score progressif selon l'anciennete avec seuils ajustes
            if anciennete_annees >= 15:
                return 100
            elif anciennete_annees >= 10:
                return 90
            elif anciennete_annees >= 7:
                return 80
            elif anciennete_annees >= 5:
                return 70
            elif anciennete_annees >= 3:
                return 60
            elif anciennete_annees >= 2:
                return 50
            elif anciennete_annees >= 1:
                return 40
            else:
                return 25
            
        except Exception as e:
            logger.warning(f"WARNING Erreur score anciennete V4.2: {e}")
            return 40
    
    def _calculer_bonus_donnees_kelio(self, candidat: ProfilUtilisateur, 
                                     demande: DemandeInterim,
                                     config: ConfigurationScoring = None) -> int:
        """
        CORRECTION: Calcule un bonus si les donnees Kelio sont riches et recentes
        Utilise les bonus de configuration ou fallback
        """
        try:
            bonus = 0
            
            # Bonus si profil Kelio complet
            if hasattr(candidat, 'kelio_data') and candidat.kelio_data:
                kelio_data = candidat.kelio_data
                if kelio_data.kelio_employee_key:
                    bonus += 2
                if kelio_data.email_kelio:
                    bonus += 1
                if kelio_data.code_personnel:
                    bonus += 1
            
            # Bonus donnees de synchronisation recentes
            if candidat.kelio_last_sync:
                jours_sync = (timezone.now() - candidat.kelio_last_sync).days
                if jours_sync <= 7:
                    bonus += 3  # Sync tres recente
                elif jours_sync <= 30:
                    bonus += 2  # Sync recente
                elif jours_sync <= 90:
                    bonus += 1  # Sync correcte
            
            # Bonus donnees peripheriques Kelio disponibles
            services_avec_donnees = 0
            for service_type in ['skill_assignments', 'training_history', 'professional_experience']:
                if self._get_cached_kelio_data(service_type, candidat.matricule):
                    services_avec_donnees += 1
            
            bonus += min(services_avec_donnees, 3)  # Max 3 points
            
            # NOUVEAU: Appliquer les bonus de configuration si disponible
            bonus_additionnel = 0
            if config:
                # Bonus experience similaire si détecté
                if self._detecter_experience_similaire(candidat, demande):
                    bonus_additionnel += getattr(config, 'bonus_experience_similaire', self.default_bonus['bonus_experience_similaire'])
            else:
                # Fallback
                if self._detecter_experience_similaire(candidat, demande):
                    bonus_additionnel += self.default_bonus['bonus_experience_similaire']
            
            return min(bonus + bonus_additionnel, 25)  # Plafonner le bonus total
            
        except Exception as e:
            logger.debug(f"Erreur calcul bonus Kelio: {e}")
            return 0
    
    def _detecter_experience_similaire(self, candidat: ProfilUtilisateur, demande: DemandeInterim) -> bool:
        """Detecte si le candidat a une experience similaire au poste demande"""
        try:
            # Verifier poste actuel similaire
            if candidat.poste and demande.poste:
                if candidat.poste == demande.poste:
                    return True
                if candidat.poste.departement == demande.poste.departement:
                    return True
            
            # Verifier missions interim passees similaires
            missions_similaires = PropositionCandidat.objects.filter(
                candidat_propose=candidat,
                statut__in=['VALIDEE', 'TERMINEE'],
                demande_interim__poste=demande.poste
            ).exists()
            
            if missions_similaires:
                return True
            
            return False
            
        except Exception:
            return False
    
    # ================================================================
    # METHODES PRINCIPALES HARMONISES AVEC CONFIGURATIONSSCORING
    # ================================================================
    
    def _calculer_score_final_v41(self, scores_criteres: Dict[str, int],
                                 config: ConfigurationScoring) -> int:
        """
        CORRECTION: Calcule le score final pondere avec ConfigurationScoring ou fallback
        """
        
        # CORRECTION: Utiliser les poids de la configuration ou fallback
        if config:
            try:
                poids = config.get_poids_dict()
                logger.debug(f">>> Utilisation poids configuration {config.nom}: {poids}")
            except Exception as e:
                logger.warning(f"WARNING Erreur recuperation poids config {config.nom}: {e}")
                poids = self.default_weights
        else:
            poids = self.default_weights
            logger.debug(f">>> Utilisation poids par défaut: {poids}")
        
        # Ajuster les poids si certains criteres Kelio ne sont pas disponibles
        poids_ajustes = self._ajuster_poids_selon_donnees_disponibles(scores_criteres, poids)
        
        # CORRECTION: Calcul avec gestion robuste des clés manquantes
        score_pondere = 0
        for critere, poids_critere in poids_ajustes.items():
            score_critere = scores_criteres.get(critere, 0)
            if score_critere > 0:  # Ne compter que les critères avec score
                score_pondere += score_critere * poids_critere
                logger.debug(f"   {critere}: {score_critere} x {poids_critere:.3f} = {score_critere * poids_critere:.1f}")
        
        score_final = min(100, max(0, int(score_pondere)))
        logger.debug(f">>> Score final pondéré: {score_final}")
        
        return score_final
    
    def _ajuster_poids_selon_donnees_disponibles(self, scores_criteres: Dict[str, int], 
                                                poids_originaux: Dict[str, float]) -> Dict[str, float]:
        """
        CORRECTION: Ajuste les poids selon la disponibilite des donnees Kelio
        Gestion améliorée des alias et redistribution
        """
        poids_ajustes = {}
        
        # Mapping des critères principaux vers leurs alias Kelio
        criteres_mapping = {
            'competences': 'competences_kelio',
            'experience': 'experience_kelio',
            'disponibilite': 'disponibilite_kelio'
        }
        
        # Traiter chaque critère principal
        for critere_principal, critere_kelio in criteres_mapping.items():
            score_kelio = scores_criteres.get(critere_kelio, 0)
            score_principal = scores_criteres.get(critere_principal, 0)
            
            # Utiliser le critère Kelio si disponible, sinon le principal
            if score_kelio > 0:
                # Utiliser le poids Kelio ou principal selon disponibilité
                poids_kelio = poids_originaux.get(critere_kelio, 0)
                poids_principal = poids_originaux.get(critere_principal, 0)
                poids_ajustes[critere_kelio] = poids_kelio or poids_principal
            elif score_principal > 0:
                # Fallback sur critère principal
                poids_principal = poids_originaux.get(critere_principal, 0)
                poids_kelio = poids_originaux.get(critere_kelio, 0)
                poids_ajustes[critere_principal] = poids_principal or poids_kelio
        
        # Ajouter les autres critères
        autres_criteres = ['similarite_poste', 'proximite', 'anciennete', 'formations_kelio']
        for critere in autres_criteres:
            if scores_criteres.get(critere, 0) > 0:
                poids_ajustes[critere] = poids_originaux.get(critere, 0)
        
        # CORRECTION: Normaliser les poids pour qu'ils totalisent 1.0
        total_poids = sum(poids_ajustes.values())
        if total_poids > 0:
            poids_ajustes = {k: v / total_poids for k, v in poids_ajustes.items()}
        else:
            # Fallback ultime si aucun poids
            logger.warning("WARNING Aucun poids valide trouvé, utilisation équiprobable")
            nb_criteres = len([k for k, v in scores_criteres.items() if v > 0])
            if nb_criteres > 0:
                poids_uniforme = 1.0 / nb_criteres
                poids_ajustes = {k: poids_uniforme for k, v in scores_criteres.items() if v > 0}
        
        logger.debug(f">>> Poids ajustés: {poids_ajustes}")
        return poids_ajustes
    
    def creer_score_detail_v41(self, candidat: ProfilUtilisateur,
                              demande: DemandeInterim,
                              proposition: PropositionCandidat = None,
                              config: ConfigurationScoring = None) -> ScoreDetailCandidat:
        """
        CORRECTION: Cree un enregistrement detaille du score pour un candidat - Version V4.2
        Utilise ConfigurationScoring ou fallback
        """
        try:
            # CORRECTION: Recuperer ou creer la configuration
            if not config:
                config = ConfigurationScoring.get_configuration_pour_demande(demande)
            
            # Calculer les scores detailles V4.2
            scores_criteres = self._calculer_scores_criteres_v41(candidat, demande, config)
            
            # CORRECTION: Creer l'enregistrement avec metadonnees Kelio et version
            score_detail = ScoreDetailCandidat.objects.create(
                candidat=candidat,
                demande_interim=demande,
                proposition_humaine=proposition,
                score_similarite_poste=scores_criteres.get('similarite_poste', 0),
                score_competences=scores_criteres.get('competences_kelio', scores_criteres.get('competences', 0)),
                score_experience=scores_criteres.get('experience_kelio', scores_criteres.get('experience', 0)),
                score_disponibilite=scores_criteres.get('disponibilite_kelio', scores_criteres.get('disponibilite', 0)),
                score_proximite=scores_criteres.get('proximite', 0),
                score_anciennete=scores_criteres.get('anciennete', 0),
                calcule_par='HUMAIN' if proposition else 'AUTOMATIQUE_V41'
            )
            
            # CORRECTION: Appliquer les bonus selon la configuration ou fallback
            if proposition:
                score_detail.bonus_proposition_humaine = self._calculer_bonus_proposition(
                    proposition, config
                )
            
            # Bonus donnees Kelio avec configuration
            bonus_kelio = self._calculer_bonus_donnees_kelio(candidat, demande, config)
            
            # NOUVEAU: Appliquer les pénalités de configuration
            penalites = self._calculer_penalites_v41(candidat, demande, config)
            for penalite_type, valeur in penalites.items():
                setattr(score_detail, penalite_type, valeur)
            
            # Calculer le score total avec configuration
            score_detail.calculer_score_total()
            score_detail.save()
            
            # Incrémenter l'utilisation de la configuration
            if config:
                try:
                    config.incrementer_utilisation()
                except Exception as e:
                    logger.debug(f"Erreur incrementation config: {e}")
            
            logger.info(f"OK Score detail V4.2 cree pour {candidat.matricule}: {score_detail.score_total} (config: {config.nom if config else 'fallback'})")
            return score_detail
            
        except Exception as e:
            logger.error(f"ERROR Erreur creation score detail V4.2: {e}")
            raise
    
    def _calculer_penalites_v41(self, candidat: ProfilUtilisateur,
                               demande: DemandeInterim,
                               config: ConfigurationScoring = None) -> Dict[str, int]:
        """
        NOUVEAU: Calcule les pénalités selon la configuration ou fallback
        """
        penalites = {}
        
        try:
            # Récupérer les pénalités de configuration ou fallback
            if config:
                penalite_indispo_partielle = getattr(config, 'penalite_indisponibilite_partielle', 
                                                   self.default_penalties['penalite_indisponibilite_partielle'])
                penalite_indispo_totale = getattr(config, 'penalite_indisponibilite_totale',
                                                self.default_penalties['penalite_indisponibilite_totale'])
                penalite_distance = getattr(config, 'penalite_distance_excessive',
                                          self.default_penalties['penalite_distance_excessive'])
            else:
                penalite_indispo_partielle = self.default_penalties['penalite_indisponibilite_partielle']
                penalite_indispo_totale = self.default_penalties['penalite_indisponibilite_totale']
                penalite_distance = self.default_penalties['penalite_distance_excessive']
            
            # Analyser la disponibilité du candidat
            if demande.date_debut and demande.date_fin:
                disponibilite_info = candidat.est_disponible_pour_interim(demande.date_debut, demande.date_fin)
                
                if not disponibilite_info['disponible']:
                    # Indisponibilité totale
                    penalites['penalite_indisponibilite'] = penalite_indispo_totale
                elif disponibilite_info['score_disponibilite'] < 70:
                    # Indisponibilité partielle
                    penalites['penalite_indisponibilite'] = penalite_indispo_partielle
            
            # Pénalité distance si pas même site
            if candidat.site and demande.poste and demande.poste.site:
                if candidat.site != demande.poste.site:
                    # Vérifier le rayon de déplacement
                    if hasattr(candidat, 'extended_data') and candidat.extended_data:
                        rayon = candidat.extended_data.rayon_deplacement_km or 25
                        if rayon < 25:  # Rayon très limité
                            penalites['penalite_distance'] = penalite_distance
            
            return penalites
            
        except Exception as e:
            logger.warning(f"WARNING Erreur calcul penalites: {e}")
            return {}
    
    def _calculer_bonus_proposition(self, proposition: PropositionCandidat,
                                   config: ConfigurationScoring = None) -> int:
        """
        CORRECTION: Calcule le bonus pour une proposition humaine selon ConfigurationScoring
        """
        try:
            if not config:
                # Utiliser les bonus par défaut
                bonus_base = self.default_bonus['bonus_proposition_humaine']
                bonus_hierarchique = self._get_bonus_hierarchique_fallback(proposition.source_proposition)
            else:
                # Utiliser les bonus de configuration
                bonus_base = getattr(config, 'bonus_proposition_humaine', self.default_bonus['bonus_proposition_humaine'])
                bonus_hierarchique = config.calculer_bonus_hierarchique(proposition.source_proposition)
            
            # Bonus total
            bonus_total = bonus_base + bonus_hierarchique
            
            # NOUVEAU: Bonus qualité de la justification
            bonus_justification = self._evaluer_qualite_justification(proposition.justification)
            bonus_total += bonus_justification
            
            logger.debug(f">>> Bonus proposition {proposition.source_proposition}: base={bonus_base}, hierarchique={bonus_hierarchique}, justification={bonus_justification}, total={bonus_total}")
            
            return min(bonus_total, 50)  # Plafonner à 50 points
            
        except Exception as e:
            logger.warning(f"WARNING Erreur calcul bonus proposition: {e}")
            return self.default_bonus['bonus_proposition_humaine']
    
    def _get_bonus_hierarchique_fallback(self, source_proposition: str) -> int:
        """Bonus hiérarchique en cas de fallback"""
        bonus_mapping = {
            'MANAGER_DIRECT': self.default_bonus['bonus_manager_direct'],
            'CHEF_EQUIPE': self.default_bonus['bonus_chef_equipe'],
            'RESPONSABLE': self.default_bonus['bonus_responsable'],
            'DIRECTEUR': self.default_bonus['bonus_directeur'],
            'RH': self.default_bonus['bonus_rh'],
            'ADMIN': self.default_bonus['bonus_admin'],
            'SUPERUSER': self.default_bonus['bonus_superuser'],
        }
        return bonus_mapping.get(source_proposition, 0)
    
    def _evaluer_qualite_justification(self, justification: str) -> int:
        """Évalue la qualité de la justification et attribue un bonus"""
        try:
            if not justification or len(justification.strip()) < 10:
                return 0
            
            bonus = 0
            justif_lower = justification.lower()
            
            # Mots-clés positifs
            mots_cles_positifs = [
                'experience', 'competence', 'formation', 'diplome',
                'mission', 'projet', 'reussi', 'excellent', 'confirme',
                'certifie', 'qualifie', 'expert', 'maitrise'
            ]
            
            for mot in mots_cles_positifs:
                if mot in justif_lower:
                    bonus += 1
            
            # Longueur de justification (détail = qualité)
            if len(justification) > 100:
                bonus += 2
            elif len(justification) > 50:
                bonus += 1
            
            return min(bonus, 5)  # Max 5 points
            
        except Exception:
            return 0
    
    # ================================================================
    # METHODES FALLBACK ET COMPATIBILITE
    # ================================================================
    
    def _calculer_score_fallback(self, candidat: ProfilUtilisateur, demande: DemandeInterim) -> int:
        """Score de secours en cas d'erreur"""
        try:
            return self._calculer_score_basique_v41(candidat, demande)
        except:
            return 50
    
    def _calculer_score_basique_v41(self, candidat: ProfilUtilisateur, demande: DemandeInterim) -> int:
        """
        CORRECTION: Calcul de score basique avec poids par défaut
        """
        
        scores = {
            'similarite': self._score_similarite_poste_v41(candidat, demande),
            'competences': self._score_competences_interne(candidat),
            'disponibilite': self._score_disponibilite_kelio_v41(candidat, demande),
            'proximite': self._score_proximite_v41(candidat, demande),
            'anciennete': self._score_anciennete_v41(candidat)
        }
        
        # CORRECTION: Ponderation par defaut compatible avec ConfigurationScoring
        score_final = (
            scores['similarite'] * self.default_weights['similarite_poste'] +
            scores['competences'] * self.default_weights['competences'] +
            scores['disponibilite'] * self.default_weights['disponibilite'] +
            scores['proximite'] * self.default_weights['proximite'] +
            scores['anciennete'] * self.default_weights['anciennete']
        )
        
        logger.debug(f">>> Score basique V4.2 pour {candidat.matricule}: {int(score_final)}")
        return int(score_final)
    
    def _score_competences_interne(self, candidat: ProfilUtilisateur) -> int:
        """Score competences base uniquement sur les donnees internes"""
        try:
            competences = CompetenceUtilisateur.objects.filter(
                utilisateur=candidat,
                niveau_maitrise__gte=2
            )
            
            if not competences.exists():
                return 30
            
            niveau_moyen = competences.aggregate(avg=Avg('niveau_maitrise'))['avg'] or 2
            score_base = (niveau_moyen / 4) * 80
            
            # Bonus certifications
            nb_certifiees = competences.filter(certifie=True).count()
            bonus_cert = min(nb_certifiees * 5, 15)
            
            return min(int(score_base + bonus_cert), 100)
            
        except Exception as e:
            logger.warning(f"Erreur score competences interne: {e}")
            return 40
    
    def _score_experience_fallback(self, candidat: ProfilUtilisateur, demande: DemandeInterim) -> int:
        """Score experience de secours"""
        try:
            score = 40
            
            # Missions passees uniquement
            missions_reussies = PropositionCandidat.objects.filter(
                candidat_propose=candidat,
                statut__in=['VALIDEE', 'TERMINEE']
            ).count()
            
            score += min(missions_reussies * 8, 35)
            return min(score, 100)
            
        except:
            return 40
    
    def _score_disponibilite_fallback(self, candidat: ProfilUtilisateur, demande: DemandeInterim) -> int:
        """Score disponibilite de secours"""
        if candidat.statut_employe != 'ACTIF' or not candidat.actif:
            return 0
        
        score = 70
        
        # Verifications basiques uniquement
        if demande.date_debut and demande.date_fin:
            absences_conflit = AbsenceUtilisateur.objects.filter(
                utilisateur=candidat,
                date_debut__lte=demande.date_fin,
                date_fin__gte=demande.date_debut
            ).exists()
            
            if absences_conflit:
                score -= 40
        
        return max(0, min(score, 100))
    
    # ================================================================
    # METHODES GENERATION CANDIDATS AVEC CONFIGURATION
    # ================================================================
    
    def generer_candidats_automatiques_v41(self, demande: DemandeInterim,
                                          limite: int = 10,
                                          inclure_donnees_kelio: bool = True,
                                          config: ConfigurationScoring = None) -> List[Dict]:
        """
        CORRECTION: Genere une liste de candidats automatiques pour une demande - Version V4.2
        Utilise ConfigurationScoring pour les seuils et critères
        """
        try:
            logger.info(f">>> Generation candidats automatiques V4.2 pour demande {demande.id}")
            
            # CORRECTION: Récupérer la configuration ou fallback
            if not config:
                config = ConfigurationScoring.get_configuration_pour_demande(demande)
            
            # Criteres de base ameliores
            candidats_base = ProfilUtilisateur.objects.filter(
                actif=True,
                statut_employe='ACTIF'
            ).exclude(
                id=demande.personne_remplacee.id if demande.personne_remplacee else -1
            ).select_related(
                'user', 'poste__departement', 'site', 'extended_data', 'kelio_data'
            )
            
            # Filtrer par disponibilite interim si possible
            if inclure_donnees_kelio:
                try:
                    candidats_base = candidats_base.filter(
                        extended_data__disponible_interim=True
                    )
                except:
                    pass
            
            # NOUVEAU: Filtres selon la configuration
            if config and config.pour_departements.exists():
                candidats_base = candidats_base.filter(
                    poste__departement__in=config.pour_departements.all()
                )
            
            # Optimisation: limiter selon la proximite geographique d'abord
            if demande.poste and demande.poste.site:
                candidats_prioritaires = candidats_base.filter(site=demande.poste.site)
                candidats_autres = candidats_base.exclude(site=demande.poste.site)
                
                # Prendre plus de candidats du meme site
                candidats_a_evaluer = list(candidats_prioritaires[:50]) + list(candidats_autres[:50])
            else:
                candidats_a_evaluer = candidats_base[:100]
            
            candidats_scores = []
            
            # CORRECTION: Seuil minimum configurable
            seuil_minimum = 25 if not config else self._determiner_seuil_minimum(config, demande)
            
            for candidat in candidats_a_evaluer:
                try:
                    score = self.calculer_score_candidat_v41(candidat, demande, config, utiliser_cache=True)
                    
                    if score >= seuil_minimum:
                        disponibilite_info = candidat.est_disponible_pour_interim(
                            demande.date_debut, demande.date_fin
                        )
                        
                        # Justification enrichie V4.2 avec configuration
                        justification = self._generer_justification_auto_v41(candidat, demande, score, config)
                        
                        candidats_scores.append({
                            'candidat': candidat,
                            'score': score,
                            'disponibilite': disponibilite_info['disponible'],
                            'disponibilite_info': disponibilite_info,
                            'justification_auto': justification,
                            'donnees_kelio_disponibles': bool(candidat.kelio_last_sync),
                            'derniere_sync_kelio': candidat.kelio_last_sync.isoformat() if candidat.kelio_last_sync else None,
                            'version_scoring': '4.1',
                            'configuration_utilisee': config.nom if config else 'fallback'
                        })
                
                except Exception as e:
                    logger.warning(f"WARNING Erreur evaluation candidat {candidat.matricule}: {e}")
                    continue
            
            # Trier par score decroissant avec priorite aux donnees Kelio recentes
            candidats_scores.sort(key=lambda x: (
                x['score'],
                1 if x['donnees_kelio_disponibles'] else 0,
                1 if x['disponibilite'] else 0
            ), reverse=True)
            
            resultats_finaux = candidats_scores[:limite]
            
            logger.info(f"OK {len(resultats_finaux)} candidats generes automatiquement V4.2 (config: {config.nom if config else 'fallback'})")
            return resultats_finaux
            
        except Exception as e:
            logger.error(f"ERROR Erreur generation candidats automatiques V4.2: {e}")
            return []
    
    def _determiner_seuil_minimum(self, config: ConfigurationScoring, demande: DemandeInterim) -> int:
        """Détermine le seuil minimum selon la configuration et l'urgence"""
        try:
            # Seuil par défaut
            seuil = 35
            
            # Ajuster selon l'urgence
            if demande.urgence == 'CRITIQUE':
                seuil = 20  # Plus permissif en urgence
            elif demande.urgence == 'ELEVEE':
                seuil = 25
            elif demande.urgence == 'NORMALE':
                seuil = 35
            
            # Ajuster selon la configuration
            if config and config.est_compatible_urgence(demande.urgence):
                # Configuration spécialisée pour cette urgence
                if demande.urgence in ['ELEVEE', 'CRITIQUE']:
                    seuil -= 5  # Plus permissif avec config spécialisée
            
            return max(seuil, 15)  # Minimum absolu
            
        except Exception:
            return 30
    
    def _generer_justification_auto_v41(self, candidat: ProfilUtilisateur,
                                       demande: DemandeInterim, score: int,
                                       config: ConfigurationScoring = None) -> str:
        """
        CORRECTION: Genere une justification automatique enrichie V4.2 avec configuration
        """
        
        justifications = []
        
        # Similarite de poste avec donnees Kelio
        if candidat.poste and demande.poste:
            if candidat.poste == demande.poste:
                justifications.append("Poste identique")
            elif candidat.poste.departement == demande.poste.departement:
                justifications.append("Même département")
            
            if candidat.poste.site == demande.poste.site:
                justifications.append("Même site")
        
        # Competences avec donnees Kelio
        nb_competences_kelio = CompetenceUtilisateur.objects.filter(
            utilisateur=candidat,
            source_donnee='KELIO',
            niveau_maitrise__gte=3
        ).count()
        
        if nb_competences_kelio > 0:
            justifications.append(f"{nb_competences_kelio} compétence(s) Kelio confirmée(s)")
        else:
            nb_competences = CompetenceUtilisateur.objects.filter(
                utilisateur=candidat,
                niveau_maitrise__gte=3
            ).count()
            if nb_competences > 0:
                justifications.append(f"{nb_competences} compétence(s) confirmée(s)")
        
        # Experience et anciennete
        if hasattr(candidat, 'extended_data') and candidat.extended_data and candidat.extended_data.date_embauche:
            anciennete_annees = (date.today() - candidat.extended_data.date_embauche).days / 365
            if anciennete_annees >= 5:
                justifications.append(f"Ancienneté {int(anciennete_annees)} ans")
        
        # Missions interim passees
        missions_reussies = PropositionCandidat.objects.filter(
            candidat_propose=candidat,
            statut__in=['VALIDEE', 'TERMINEE']
        ).count()
        
        if missions_reussies > 0:
            justifications.append(f"{missions_reussies} mission(s) intérim réussie(s)")
        
        # Score global avec niveau V4.2 et configuration
        config_info = f" ({config.nom})" if config else " (fallback)"
        if score >= 85:
            justifications.append(f"Score de compatibilité excellent (V4.2{config_info})")
        elif score >= 70:
            justifications.append(f"Score de compatibilité élevé (V4.2{config_info})")
        elif score >= 55:
            justifications.append(f"Bonne compatibilité (V4.2{config_info})")
        
        # Donnees Kelio disponibles
        if candidat.kelio_last_sync:
            jours_sync = (timezone.now() - candidat.kelio_last_sync).days
            if jours_sync <= 7:
                justifications.append("Données Kelio récentes")
        
        # Disponibilite
        if candidat.statut_employe == 'ACTIF':
            if hasattr(candidat, 'extended_data') and candidat.extended_data and candidat.extended_data.disponible_interim:
                justifications.append("Disponible pour intérim")
            else:
                justifications.append("Employé actif")
        
        if not justifications:
            justifications.append(f"Candidat identifié automatiquement (V4.2{config_info})")
        
        return " >> ".join(justifications)
    
    # ================================================================
    # METHODES UTILITAIRES KELIO V4.2 (Maintenues)
    # ================================================================
    
    def _get_cached_kelio_data(self, service_type: str, matricule: str) -> Optional[Dict]:
        """Recupere les donnees Kelio en cache pour un service donne"""
        try:
            # Rechercher dans le cache Kelio
            parametres = {'matricule': matricule, 'service': service_type}
            cle_cache = generer_cle_cache_kelio(service_type, parametres)
            
            cache_entry = CacheApiKelio.objects.filter(
                cle_cache__startswith=service_type,
                parametres_requete__matricule=matricule,
                date_expiration__gt=timezone.now()
            ).first()
            
            if cache_entry:
                return cache_entry.donnees
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur recuperation cache Kelio {service_type}: {e}")
            return None
    
    def _generer_cle_cache_score(self, candidat: ProfilUtilisateur, demande: DemandeInterim) -> str:
        """Genere une cle de cache pour le score"""
        elements = [
            f"candidat_{candidat.id}",
            f"demande_{demande.id}",
            f"sync_{candidat.kelio_last_sync.strftime('%Y%m%d') if candidat.kelio_last_sync else 'nosync'}"
        ]
        return "_".join(elements)

# ================================================================
# SERVICE D'ANALYSE HARMONISE V4.2 AVEC CONFIGURATIONSSCORING
# ================================================================

class ScoringAnalyticsServiceV41:
    """Service d'analyse des performances du scoring - Version V4.2 Harmonise avec ConfigurationScoring"""
    
    @staticmethod
    def analyser_efficacite_scoring_v41(periode_jours: int = 90, 
                                       inclure_donnees_kelio: bool = True,
                                       configuration_id: int = None) -> Dict:
        """
        CORRECTION: Analyse l'efficacite du systeme de scoring V4.2 avec ConfigurationScoring
        """
        
        date_debut = timezone.now() - timedelta(days=periode_jours)
        
        # Demandes terminees avec evaluation
        demandes_evaluees = DemandeInterim.objects.filter(
            statut='TERMINEE',
            evaluation_mission__isnull=False,
            date_fin_effective__gte=date_debut
        )
        
        # NOUVEAU: Filtrer par configuration si spécifiée
        if configuration_id:
            try:
                config = ConfigurationScoring.objects.get(id=configuration_id)
                # Filtrer les demandes qui ont utilisé cette configuration
                # (Nécessiterait un champ dans DemandeInterim ou ScoreDetailCandidat)
            except ConfigurationScoring.DoesNotExist:
                pass
        
        total_missions = demandes_evaluees.count()
        
        if total_missions == 0:
            return {
                'version': '4.1',
                'nb_missions_analysees': 0,
                'score_moyen_selectionnes': 0,
                'evaluation_moyenne': 0,
                'taux_satisfaction': 0,
                'donnees_kelio_utilisees': 0,
                'configurations_utilisees': {},
                'recommandations': ["Pas assez de données pour l'analyse V4.2"]
            }
        
        # Analyser les scores detailles V4.2
        scores_details = ScoreDetailCandidat.objects.filter(
            demande_interim__in=demandes_evaluees
        )
        
        # NOUVEAU: Analyser l'utilisation des configurations
        configurations_stats = {}
        try:
            configs_utilisees = ConfigurationScoring.objects.filter(
                actif=True,
                nb_utilisations__gt=0,
                last_used__gte=date_debut
            )
            
            for config in configs_utilisees:
                configurations_stats[config.nom] = {
                    'utilisations': config.nb_utilisations,
                    'derniere_utilisation': config.last_used.isoformat() if config.last_used else None,
                    'par_defaut': config.configuration_par_defaut
                }
        except Exception as e:
            logger.warning(f"Erreur analyse configurations: {e}")
        
        # Calculs statistiques V4.2 avec ConfigurationScoring
        score_moyen = scores_details.aggregate(avg=Avg('score_total'))['avg'] or 0
        
        evaluation_moyenne = demandes_evaluees.aggregate(
            avg=Avg('evaluation_mission')
        )['avg'] or 0
        
        missions_satisfaisantes = demandes_evaluees.filter(
            evaluation_mission__gte=4
        ).count()
        
        taux_satisfaction = (missions_satisfaisantes / total_missions) * 100
        
        # Analyser l'impact des donnees Kelio
        missions_avec_kelio = 0
        if inclure_donnees_kelio:
            # Approximation basée sur la synchronisation Kelio récente
            missions_avec_kelio = demandes_evaluees.filter(
                candidat_selectionne__kelio_last_sync__gte=date_debut - timedelta(days=30)
            ).count()
        
        # Analyser les performances par type de score
        performance_par_critere = {
            'similarite_poste': scores_details.aggregate(avg=Avg('score_similarite_poste'))['avg'] or 0,
            'competences': scores_details.aggregate(avg=Avg('score_competences'))['avg'] or 0,
            'experience': scores_details.aggregate(avg=Avg('score_experience'))['avg'] or 0,
            'disponibilite': scores_details.aggregate(avg=Avg('score_disponibilite'))['avg'] or 0,
            'proximite': scores_details.aggregate(avg=Avg('score_proximite'))['avg'] or 0
        }
        
        return {
            'version': '4.1',
            'periode_analyse_jours': periode_jours,
            'nb_missions_analysees': total_missions,
            'score_moyen_selectionnes': round(score_moyen, 2),
            'evaluation_moyenne': round(evaluation_moyenne, 2),
            'taux_satisfaction': round(taux_satisfaction, 2),
            'missions_avec_donnees_kelio': missions_avec_kelio,
            'taux_utilisation_kelio': round((missions_avec_kelio / max(1, total_missions)) * 100, 2),
            'configurations_utilisees': configurations_stats,
            'performance_par_critere': {k: round(v, 2) for k, v in performance_par_critere.items()},
            'recommandations': ScoringAnalyticsServiceV41._generer_recommandations_v41(
                taux_satisfaction, evaluation_moyenne, missions_avec_kelio, total_missions, configurations_stats
            )
        }
    
    @staticmethod
    def _generer_recommandations_v41(taux_satisfaction: float, evaluation_moyenne: float,
                                    missions_avec_kelio: int, total_missions: int,
                                    configurations_stats: Dict) -> List[str]:
        """
        CORRECTION: Genere des recommandations d'amelioration V4.2 avec ConfigurationScoring
        """
        
        recommandations = []
        
        # Recommandations generales
        if taux_satisfaction < 70:
            recommandations.append("Taux de satisfaction faible - Réviser les critères de scoring V4.2")
        
        if evaluation_moyenne < 3.5:
            recommandations.append("Évaluations moyennes faibles - Améliorer la sélection automatique V4.2")
        
        if taux_satisfaction >= 85:
            recommandations.append("Très bon taux de satisfaction - Système V4.2 performant")
        
        # Recommandations specifiques Kelio V4.2
        taux_kelio = (missions_avec_kelio / max(1, total_missions)) * 100
        
        if taux_kelio < 30:
            recommandations.append("Peu de données Kelio utilisées - Améliorer la synchronisation V4.2")
        elif taux_kelio >= 80:
            recommandations.append("Excellente utilisation des données Kelio V4.2")
        elif taux_kelio >= 50:
            recommandations.append("Bonne utilisation des données Kelio V4.2")
        
        # NOUVEAU: Recommandations spécifiques aux configurations
        if not configurations_stats:
            recommandations.append("Aucune configuration de scoring active - Créer des configurations spécialisées")
        elif len(configurations_stats) == 1:
            recommandations.append("Une seule configuration utilisée - Diversifier avec des configs par département/urgence")
        else:
            # Analyser l'équilibre d'utilisation
            utilisations = [config['utilisations'] for config in configurations_stats.values()]
            if max(utilisations) > sum(utilisations) * 0.8:
                recommandations.append("Configuration dominante détectée - Vérifier l'équilibre d'utilisation")
        
        # Recommandations de performance avec configurations
        if evaluation_moyenne >= 4.5 and taux_satisfaction >= 90:
            if configurations_stats:
                recommandations.append("Performance exceptionnelle - Dupliquer les configurations performantes")
            else:
                recommandations.append("Performance exceptionnelle - Créer des configurations pour optimiser")
        
        return recommandations or ["Système de scoring V4.2 avec ConfigurationScoring fonctionnel"]
    
    @staticmethod
    def analyser_performance_par_configuration(periode_jours: int = 30) -> Dict:
        """
        NOUVEAU: Analyse la performance de chaque configuration de scoring
        """
        try:
            date_debut = timezone.now() - timedelta(days=periode_jours)
            
            configs = ConfigurationScoring.objects.filter(
                actif=True,
                last_used__gte=date_debut
            )
            
            resultats = {}
            
            for config in configs:
                # Approximation des demandes utilisant cette config
                # (Nécessiterait un tracking plus précis dans les demandes)
                
                stats = {
                    'nom': config.nom,
                    'utilisations': config.nb_utilisations,
                    'derniere_utilisation': config.last_used,
                    'configuration': {
                        'poids_similarite': config.poids_similarite_poste,
                        'poids_competences': config.poids_competences,
                        'poids_experience': config.poids_experience,
                        'poids_disponibilite': config.poids_disponibilite,
                        'poids_proximite': config.poids_proximite,
                        'poids_anciennete': config.poids_anciennete
                    },
                    'bonus_moyens': {
                        'manager_direct': config.bonus_manager_direct,
                        'responsable': config.bonus_responsable,
                        'directeur': config.bonus_directeur,
                        'rh': config.bonus_rh
                    },
                    'penalites': {
                        'indispo_partielle': config.penalite_indisponibilite_partielle,
                        'indispo_totale': config.penalite_indisponibilite_totale,
                        'distance': config.penalite_distance_excessive
                    },
                    'specialisation': {
                        'departements': list(config.pour_departements.values_list('nom', flat=True)),
                        'urgences': config.pour_types_urgence or 'Toutes'
                    }
                }
                
                resultats[config.nom] = stats
            
            return {
                'version': '4.1',
                'periode_jours': periode_jours,
                'configurations_analysees': len(resultats),
                'configurations': resultats,
                'recommandations': ScoringAnalyticsServiceV41._recommandations_configurations(resultats)
            }
            
        except Exception as e:
            logger.error(f"Erreur analyse performance configurations: {e}")
            return {'erreur': str(e)}
    
    @staticmethod
    def _recommandations_configurations(configurations_stats: Dict) -> List[str]:
        """Génère des recommandations basées sur l'analyse des configurations"""
        recommandations = []
        
        if not configurations_stats:
            return ["Créer au moins une configuration de scoring personnalisée"]
        
        nb_configs = len(configurations_stats)
        
        if nb_configs == 1:
            recommandations.append("Créer des configurations spécialisées par département ou urgence")
        
        # Analyser l'équilibre des poids
        for nom, stats in configurations_stats.items():
            config = stats['configuration']
            
            # Vérifier l'équilibre des pondérations
            poids_max = max(config.values())
            if poids_max > 0.5:
                recommandations.append(f"Config '{nom}': Pondération très élevée détectée ({poids_max:.1%})")
            
            # Vérifier les spécialisations
            if not stats['specialisation']['departements'] and stats['specialisation']['urgences'] == 'Toutes':
                recommandations.append(f"Config '{nom}': Spécialiser par département ou type d'urgence")
        
        return recommandations or ["Configurations de scoring bien équilibrées"]

# ================================================================
# FONCTIONS UTILITAIRES V4.2 AVEC CONFIGURATIONSSCORING
# ================================================================

def get_scoring_service_v41(configuration_kelio=None):
    """Factory function pour le service de scoring V4.2 avec ConfigurationScoring"""
    try:
        service = ScoringInterimService(configuration_kelio)
        logger.info(">>> Service de scoring V4.2 créé avec intégration Kelio et ConfigurationScoring")
        return service
    except Exception as e:
        logger.error(f"ERROR Erreur création service scoring V4.2: {e}")
        raise

def calculer_scores_pour_demande_v41(demande_id: int, 
                                    limite_candidats: int = 50,
                                    configuration_id: int = None) -> Dict:
    """
    CORRECTION: Fonction principale pour calculer les scores pour une demande V4.2
    Utilise ConfigurationScoring
    """
    try:
        demande = DemandeInterim.objects.get(id=demande_id)
        service = get_scoring_service_v41()
        
        # NOUVEAU: Utiliser configuration spécifique si fournie
        config = None
        if configuration_id:
            try:
                config = ConfigurationScoring.objects.get(id=configuration_id, actif=True)
            except ConfigurationScoring.DoesNotExist:
                logger.warning(f"Configuration {configuration_id} non trouvée, utilisation automatique")
        
        candidats_automatiques = service.generer_candidats_automatiques_v41(
            demande, limite=limite_candidats, config=config
        )
        
        # Creer les scores detailles avec configuration
        scores_detailles = []
        for candidat_data in candidats_automatiques:
            candidat = candidat_data['candidat']
            score_detail = service.creer_score_detail_v41(candidat, demande, config=config)
            scores_detailles.append(score_detail)
        
        return {
            'demande_id': demande_id,
            'version': '4.1',
            'configuration_utilisee': config.nom if config else 'automatique',
            'candidats_automatiques': candidats_automatiques,
            'scores_detailles': scores_detailles,
            'timestamp': timezone.now().isoformat(),
            'parametres': {
                'limite_candidats': limite_candidats,
                'configuration_id': configuration_id
            }
        }
        
    except Exception as e:
        logger.error(f"ERROR Erreur calcul scores demande V4.2 {demande_id}: {e}")
        return {
            'demande_id': demande_id,
            'erreur': str(e),
            'version': '4.1',
            'timestamp': timezone.now().isoformat()
        }

def tester_configuration_scoring(config_id: int, demande_test_id: int = None) -> Dict:
    """
    NOUVEAU: Teste une configuration de scoring sur une demande
    """
    try:
        config = ConfigurationScoring.objects.get(id=config_id, actif=True)
        
        if demande_test_id:
            demande = DemandeInterim.objects.get(id=demande_test_id)
        else:
            # Prendre une demande récente pour test
            demande = DemandeInterim.objects.filter(
                statut__in=['VALIDEE', 'TERMINEE']
            ).order_by('-created_at').first()
            
            if not demande:
                return {'erreur': 'Aucune demande disponible pour test'}
        
        service = get_scoring_service_v41()
        
        # Générer quelques candidats test
        candidats_test = service.generer_candidats_automatiques_v41(
            demande, limite=5, config=config
        )
        
        # Analyser les résultats
        resultats_test = {
            'configuration': {
                'nom': config.nom,
                'description': config.description,
                'poids': config.get_poids_dict(),
                'resume': config.resume_configuration
            },
            'demande_test': {
                'id': demande.id,
                'poste': demande.poste.titre if demande.poste else None,
                'urgence': demande.urgence
            },
            'candidats_generes': len(candidats_test),
            'scores_obtenus': [c['score'] for c in candidats_test],
            'score_moyen': sum(c['score'] for c in candidats_test) / len(candidats_test) if candidats_test else 0,
            'candidats_details': candidats_test[:3],  # Top 3 seulement
            'recommandations': []
        }
        
        # Générer recommandations de test
        if not candidats_test:
            resultats_test['recommandations'].append("Aucun candidat généré - Assouplir les critères")
        elif resultats_test['score_moyen'] < 40:
            resultats_test['recommandations'].append("Scores moyens faibles - Revoir les pondérations")
        elif resultats_test['score_moyen'] > 80:
            resultats_test['recommandations'].append("Excellents scores - Configuration optimisée")
        
        return resultats_test
        
    except Exception as e:
        logger.error(f"Erreur test configuration {config_id}: {e}")
        return {'erreur': str(e)}

def comparer_configurations_scoring(config_ids: List[int], demande_test_id: int = None) -> Dict:
    """
    NOUVEAU: Compare plusieurs configurations de scoring
    """
    try:
        configs = ConfigurationScoring.objects.filter(id__in=config_ids, actif=True)
        
        if demande_test_id:
            demande = DemandeInterim.objects.get(id=demande_test_id)
        else:
            # Demande récente pour comparaison
            demande = DemandeInterim.objects.filter(
                statut__in=['VALIDEE', 'TERMINEE']
            ).order_by('-created_at').first()
        
        if not demande:
            return {'erreur': 'Aucune demande disponible pour comparaison'}
        
        service = get_scoring_service_v41()
        comparaison = {
            'demande_test': {
                'id': demande.id,
                'poste': demande.poste.titre if demande.poste else None,
                'urgence': demande.urgence
            },
            'configurations': {},
            'analyse_comparative': {}
        }
        
        # Tester chaque configuration
        for config in configs:
            candidats = service.generer_candidats_automatiques_v41(
                demande, limite=10, config=config
            )
            
            scores = [c['score'] for c in candidats]
            
            comparaison['configurations'][config.nom] = {
                'poids': config.get_poids_dict(),
                'candidats_generes': len(candidats),
                'scores': scores,
                'score_moyen': sum(scores) / len(scores) if scores else 0,
                'score_max': max(scores) if scores else 0,
                'candidates_top3': candidats[:3]
            }
        
        # Analyse comparative
        scores_moyens = {nom: data['score_moyen'] for nom, data in comparaison['configurations'].items()}
        
        if scores_moyens:
            meilleure_config = max(scores_moyens.items(), key=lambda x: x[1])
            comparaison['analyse_comparative'] = {
                'meilleure_configuration': meilleure_config[0],
                'meilleur_score_moyen': meilleure_config[1],
                'ecart_max': max(scores_moyens.values()) - min(scores_moyens.values()),
                'recommandation': f"Configuration '{meilleure_config[0]}' la plus performante"
            }
        
        return comparaison
        
    except Exception as e:
        logger.error(f"Erreur comparaison configurations: {e}")
        return {'erreur': str(e)}

def optimiser_configuration_automatique(demandes_historiques_ids: List[int] = None) -> Dict:
    """
    NOUVEAU: Propose une optimisation automatique des configurations
    basée sur l'historique des demandes
    """
    try:
        # Analyser les demandes historiques
        if demandes_historiques_ids:
            demandes = DemandeInterim.objects.filter(id__in=demandes_historiques_ids)
        else:
            # Prendre les 50 dernières demandes terminées
            demandes = DemandeInterim.objects.filter(
                statut='TERMINEE',
                evaluation_mission__isnull=False
            ).order_by('-date_fin_effective')[:50]
        
        if not demandes.exists():
            return {'erreur': 'Pas assez de données historiques pour optimisation'}
        
        # Analyser les patterns
        analyse = {
            'demandes_analysees': demandes.count(),
            'repartition_urgences': {},
            'repartition_departements': {},
            'scores_moyens_par_critere': {},
            'configurations_optimales_proposees': []
        }
        
        # Répartition des urgences
        for urgence in ['NORMALE', 'ELEVEE', 'CRITIQUE']:
            count = demandes.filter(urgence=urgence).count()
            analyse['repartition_urgences'][urgence] = {
                'count': count,
                'pourcentage': (count / demandes.count()) * 100
            }
        
        # Répartition par département
        deps_stats = {}
        for demande in demandes.select_related('poste__departement'):
            if demande.poste and demande.poste.departement:
                dept_nom = demande.poste.departement.nom
                if dept_nom not in deps_stats:
                    deps_stats[dept_nom] = 0
                deps_stats[dept_nom] += 1
        
        analyse['repartition_departements'] = deps_stats
        
        # Propositions d'optimisation
        optimisations = []
        
        # Configuration par urgence si répartition significative
        if analyse['repartition_urgences']['CRITIQUE']['pourcentage'] > 10:
            optimisations.append({
                'nom': 'Configuration Urgences Critiques',
                'description': 'Configuration spécialisée pour les urgences critiques',
                'poids_suggeres': {
                    'disponibilite': 0.35,  # Priorité disponibilité
                    'proximite': 0.20,     # Proximité importante
                    'competences': 0.20,
                    'experience': 0.15,
                    'similarite_poste': 0.10
                },
                'types_urgence': 'CRITIQUE',
                'bonus_ajustes': {
                    'manager_direct': 20,  # Bonus élevés pour validation rapide
                    'responsable': 25,
                    'directeur': 30
                }
            })
        
        # Configuration par département principal
        dept_principal = max(deps_stats.items(), key=lambda x: x[1]) if deps_stats else None
        if dept_principal and dept_principal[1] > demandes.count() * 0.3:
            optimisations.append({
                'nom': f'Configuration {dept_principal[0]}',
                'description': f'Configuration spécialisée pour le département {dept_principal[0]}',
                'poids_suggeres': {
                    'similarite_poste': 0.30,  # Important pour spécialisation
                    'competences': 0.30,
                    'experience': 0.20,
                    'disponibilite': 0.15,
                    'proximite': 0.05
                },
                'departement': dept_principal[0]
            })
        
        analyse['configurations_optimales_proposees'] = optimisations
        
        return analyse
        
    except Exception as e:
        logger.error(f"Erreur optimisation automatique: {e}")
        return {'erreur': str(e)}

def generer_rapport_scoring_complet_v41(demande_id: int, configuration_id: int = None) -> Dict:
    """
    CORRECTION: Genere un rapport complet de scoring pour une demande V4.2
    Avec support ConfigurationScoring
    """
    try:
        demande = DemandeInterim.objects.get(id=demande_id)
        service = get_scoring_service_v41()
        
        # Configuration à utiliser
        config = None
        if configuration_id:
            try:
                config = ConfigurationScoring.objects.get(id=configuration_id, actif=True)
            except ConfigurationScoring.DoesNotExist:
                pass
        
        if not config:
            config = ConfigurationScoring.get_configuration_pour_demande(demande)
        
        # Generer candidats et scores avec configuration
        candidats_data = service.generer_candidats_automatiques_v41(
            demande, limite=50, config=config
        )
        
        # Analyser la distribution des scores
        scores = [c['score'] for c in candidats_data]
        
        rapport = {
            'demande': {
                'id': demande.id,
                'numero': getattr(demande, 'numero_demande', f'DEMANDE-{demande.id}'),
                'poste': demande.poste.titre if demande.poste else None,
                'departement': demande.poste.departement.nom if demande.poste and demande.poste.departement else None,
                'site': demande.poste.site.nom if demande.poste and demande.poste.site else None,
                'urgence': demande.urgence,
                'date_debut': demande.date_debut.isoformat() if demande.date_debut else None,
                'date_fin': demande.date_fin.isoformat() if demande.date_fin else None
            },
            'configuration_utilisee': {
                'nom': config.nom if config else 'Fallback',
                'description': config.description if config else 'Configuration par défaut',
                'poids': config.get_poids_dict() if config else service.default_weights,
                'specialisations': {
                    'departements': list(config.pour_departements.values_list('nom', flat=True)) if config and config.pour_departements.exists() else [],
                    'urgences': config.pour_types_urgence if config else 'Toutes'
                } if config else {}
            },
            'candidats': {
                'total_evalues': len(candidats_data),
                'avec_donnees_kelio': sum(1 for c in candidats_data if c['donnees_kelio_disponibles']),
                'disponibles': sum(1 for c in candidats_data if c['disponibilite']),
                'score_moyen': sum(scores) / len(scores) if scores else 0,
                'score_max': max(scores) if scores else 0,
                'score_min': min(scores) if scores else 0,
                'mediane': sorted(scores)[len(scores)//2] if scores else 0
            },
            'distribution_scores': {
                'excellent_85_100': sum(1 for s in scores if s >= 85),
                'bon_70_84': sum(1 for s in scores if 70 <= s < 85),
                'correct_55_69': sum(1 for s in scores if 55 <= s < 70),
                'faible_0_54': sum(1 for s in scores if s < 55)
            },
            'top_candidats': candidats_data[:5],  # Top 5
            'analyse_kelio': {
                'taux_donnees_kelio': (
                    sum(1 for c in candidats_data if c['donnees_kelio_disponibles']) / 
                    max(1, len(candidats_data))
                ) * 100,
                'impact_estime': "Positif" if any(c['donnees_kelio_disponibles'] for c in candidats_data) else "Neutre",
                'candidats_avec_sync_recente': sum(1 for c in candidats_data 
                                                 if c['derniere_sync_kelio'] and 
                                                 (timezone.now() - timezone.datetime.fromisoformat(c['derniere_sync_kelio'].replace('Z', '+00:00'))).days <= 7)
            },
            'recommandations': service._generer_recommandations_rapport(candidats_data, demande, config),
            'metadata': {
                'version_scoring': '4.1',
                'timestamp_generation': timezone.now().isoformat(),
                'kelio_integration': True,
                'configuration_scoring': True,
                'parametres_utilises': {
                    'limite_candidats': 50,
                    'inclure_kelio': True,
                    'configuration_id': config.id if config else None
                }
            }
        }
        
        return rapport
        
    except Exception as e:
        logger.error(f"ERROR Erreur generation rapport scoring V4.2: {e}")
        return {'erreur': str(e)}

# ================================================================
# EXTENSION DE LA CLASSE PRINCIPALE POUR RAPPORT AVEC CONFIG
# ================================================================

# Ajout de methode a la classe principale avec support ConfigurationScoring
def _generer_recommandations_rapport(self, candidats_data: List[Dict], 
                                    demande: DemandeInterim,
                                    config: ConfigurationScoring = None) -> List[str]:
    """
    CORRECTION: Genere des recommandations pour le rapport de scoring avec ConfigurationScoring
    """
    
    recommandations = []
    
    if not candidats_data:
        recommandations.append("Aucun candidat trouvé - Élargir les critères de recherche")
        if config and config.pour_departements.exists():
            recommandations.append(f"Configuration '{config.nom}' limitée aux départements spécifiques - Vérifier compatibilité")
        return recommandations
    
    scores = [c['score'] for c in candidats_data]
    score_moyen = sum(scores) / len(scores)
    
    # Recommandations selon la qualite des candidats et configuration
    config_info = f" (Config: {config.nom})" if config else " (Fallback)"
    
    if score_moyen >= 80:
        recommandations.append(f"Excellents candidats disponibles{config_info} - Procéder à la sélection")
    elif score_moyen >= 65:
        recommandations.append(f"Bons candidats identifiés{config_info} - Entretiens recommandés")
    elif score_moyen >= 50:
        recommandations.append(f"Candidats corrects{config_info} - Vérifier disponibilités et compétences")
    else:
        recommandations.append(f"Candidats de qualité limitée{config_info} - Envisager recherche externe")
        if config:
            recommandations.append("Possibilité d'assouplir les critères de la configuration")
    
    # Recommandations spécifiques à la configuration
    if config:
        # Analyser l'adéquation configuration/demande
        if config.pour_types_urgence and demande.urgence not in config.pour_types_urgence:
            recommandations.append(f"Configuration '{config.nom}' non optimisée pour urgence '{demande.urgence}'")
        
        if config.pour_departements.exists() and demande.poste and demande.poste.departement:
            if demande.poste.departement not in config.pour_departements.all():
                recommandations.append(f"Configuration '{config.nom}' non spécialisée pour le département '{demande.poste.departement.nom}'")
        
        # Analyser les pondérations
        poids = config.get_poids_dict()
        poids_max = max(poids.values())
        critere_dominant = max(poids.items(), key=lambda x: x[1])
        
        if poids_max > 0.4:
            recommandations.append(f"Configuration dominée par '{critere_dominant[0]}' ({poids_max:.1%}) - Vérifier équilibre")
    else:
        recommandations.append("Configuration par défaut utilisée - Créer une configuration spécialisée pour de meilleurs résultats")
    
    # Recommandations specifiques Kelio
    avec_kelio = sum(1 for c in candidats_data if c['donnees_kelio_disponibles'])
    sans_kelio = len(candidats_data) - avec_kelio
    
    if sans_kelio > avec_kelio:
        recommandations.append("Synchroniser plus de profils avec Kelio pour améliorer la précision")
    
    # Recommandations de disponibilite
    disponibles = sum(1 for c in candidats_data if c['disponibilite'])
    if disponibles < len(candidats_data) * 0.5:
        recommandations.append("Peu de candidats disponibles - Vérifier les dates de mission")
        if config:
            penalite_dispo = getattr(config, 'penalite_indisponibilite_partielle', 15)
            if penalite_dispo > 20:
                recommandations.append("Pénalités de disponibilité élevées dans la configuration")
    
    # Recommandations geographiques avec configuration
    if demande.poste and demande.poste.site:
        meme_site = sum(1 for c in candidats_data 
                       if c['candidat'].site == demande.poste.site)
        if meme_site == 0:
            recommandations.append("Aucun candidat du même site - Prévoir frais de déplacement")
            if config:
                penalite_distance = getattr(config, 'penalite_distance_excessive', 10)
                if penalite_distance < 5:
                    recommandations.append("Augmenter la pénalité distance dans la configuration")
    
    return recommandations

# Ajout de la methode a la classe avec support ConfigurationScoring
ScoringInterimService._generer_recommandations_rapport = _generer_recommandations_rapport

# ================================================================
# INITIALISATION ET CONFIGURATION V4.2 AVEC CONFIGURATIONSSCORING
# ================================================================

def initialiser_scoring_service_v41():
    """
    CORRECTION: Initialise le service de scoring V4.2 avec verifications ConfigurationScoring
    """
    try:
        logger.info(">>> Initialisation ScoringInterimService V4.2 avec ConfigurationScoring")
        
        # Verifier la disponibilite des modeles Kelio et ConfigurationScoring
        verification = {
            'models_kelio_disponibles': True,
            'configuration_kelio_active': False,
            'cache_kelio_fonctionnel': False,
            'configurations_scoring_disponibles': False,
            'configuration_par_defaut': None
        }
        
        try:
            # Test des modeles Kelio
            ConfigurationApiKelio.objects.first()
            ProfilUtilisateurKelio.objects.first()
            CacheApiKelio.objects.first()
            
            # Test configuration Kelio active
            config_kelio_active = ConfigurationApiKelio.objects.filter(actif=True).first()
            verification['configuration_kelio_active'] = bool(config_kelio_active)
            
            # Test cache Kelio
            cache_entries = CacheApiKelio.objects.count()
            verification['cache_kelio_fonctionnel'] = cache_entries >= 0
            
        except Exception as e:
            logger.warning(f"WARNING Certains modeles Kelio non disponibles: {e}")
            verification['models_kelio_disponibles'] = False
        
        try:
            # Test des configurations de scoring
            configs_scoring = ConfigurationScoring.objects.filter(actif=True)
            verification['configurations_scoring_disponibles'] = configs_scoring.exists()
            
            # Test configuration par défaut
            config_defaut = configs_scoring.filter(configuration_par_defaut=True).first()
            if config_defaut:
                verification['configuration_par_defaut'] = config_defaut.nom
            elif configs_scoring.exists():
                verification['configuration_par_defaut'] = f"Première active: {configs_scoring.first().nom}"
            
        except Exception as e:
            logger.warning(f"WARNING Modeles ConfigurationScoring non disponibles: {e}")
        
        # Creer le service
        service = get_scoring_service_v41()
        
        # Statistiques d'initialisation
        stats = {
            'configurations_actives': ConfigurationScoring.objects.filter(actif=True).count() if verification['configurations_scoring_disponibles'] else 0,
            'configurations_par_defaut': ConfigurationScoring.objects.filter(actif=True, configuration_par_defaut=True).count() if verification['configurations_scoring_disponibles'] else 0,
            'kelio_configs_actives': ConfigurationApiKelio.objects.filter(actif=True).count() if verification['models_kelio_disponibles'] else 0
        }
        
        logger.info("OK ScoringInterimService V4.2 initialise avec succes")
        logger.info(f">>> Verifications: {verification}")
        logger.info(f">>> Statistiques: {stats}")
        
        return {
            'service': service,
            'verification': verification,
            'statistiques': stats,
            'status': 'READY'
        }
        
    except Exception as e:
        logger.error(f"ERROR Erreur initialisation scoring V4.2: {e}")
        return {
            'erreur': str(e),
            'status': 'ERROR'
        }

def creer_configuration_scoring_par_defaut():
    """
    NOUVEAU: Crée une configuration de scoring par défaut si aucune n'existe
    """
    try:
        # Vérifier si une configuration existe déjà
        if ConfigurationScoring.objects.filter(actif=True).exists():
            logger.info(">>> Configurations de scoring existantes détectées")
            return ConfigurationScoring.objects.filter(actif=True).first()
        
        # Créer configuration par défaut
        config_defaut = ConfigurationScoring.objects.create(
            nom="Configuration Standard",
            description="Configuration de scoring par défaut du système",
            poids_similarite_poste=0.25,
            poids_competences=0.25,
            poids_experience=0.20,
            poids_disponibilite=0.15,
            poids_proximite=0.10,
            poids_anciennete=0.05,
            bonus_proposition_humaine=5,
            bonus_experience_similaire=8,
            bonus_recommandation=10,
            bonus_manager_direct=12,
            bonus_chef_equipe=8,
            bonus_responsable=15,
            bonus_directeur=18,
            bonus_rh=20,
            bonus_admin=20,
            bonus_superuser=0,
            penalite_indisponibilite_partielle=15,
            penalite_indisponibilite_totale=50,
            penalite_distance_excessive=10,
            configuration_par_defaut=True,
            actif=True
        )
        
        logger.info(f">>> Configuration par défaut créée: {config_defaut.nom}")
        return config_defaut
        
    except Exception as e:
        logger.error(f"ERROR Erreur création configuration par défaut: {e}")
        return None

# ================================================================
# AFFICHAGE DES STATISTIQUES AU CHARGEMENT AVEC CONFIGURATIONSSCORING
# ================================================================

def afficher_statistiques_scoring_v41():
    """
    CORRECTION: Affiche les statistiques du service de scoring au demarrage avec ConfigurationScoring
    """
    try:
        logger.info(">>> =================================================")
        logger.info(">>> SCORING INTERIM SERVICE V4.2 - HARMONISE KELIO + CONFIGURATIONSSCORING")
        logger.info(">>> =================================================")
        logger.info("OK Nouvelles fonctionnalites V4.2 CORRIGEES:")
        logger.info("   >>> Integration complete avec Kelio API V4.2")
        logger.info("   >>> Utilisation systematique ConfigurationScoring avec fallbacks")
        logger.info("   >>> Scores enrichis avec donnees professionnelles Kelio")
        logger.info("   >>> Pondérations configurables par administration")
        logger.info("   >>> Bonus et pénalités personnalisables par configuration")
        logger.info("   >>> Configurations spécialisées par département/urgence")
        logger.info("   >>> Analytics enrichies avec métriques par configuration")
        logger.info("   >>> Fallback automatique si ConfigurationScoring indisponible")
        logger.info("")
        logger.info(">>> Structure de scoring V4.2:")
        logger.info("   1. Récupération ConfigurationScoring pour demande")
        logger.info("   2. Utilisation poids configurés ou fallback default_weights")
        logger.info("   3. Calcul scores avec données Kelio enrichies")
        logger.info("   4. Application bonus/pénalités de configuration")
        logger.info("   5. Score final pondéré avec normalisation")
        logger.info("")
        logger.info(">>> Criteres de scoring V4.2 (configurables):")
        logger.info("   Similarité poste: 25% (enrichi avec job_assignments)")
        logger.info("   Compétences Kelio: 25% (skill_assignments + niveaux)")
        logger.info("   Expérience Kelio: 20% (professional_experience + ancienneté)")
        logger.info("   Disponibilité Kelio: 15% (labor_contracts + absence_requests)")
        logger.info("   Proximité: 10% (géolocalisation + rayon déplacement)")
        logger.info("   Ancienneté: 5% (données embauche Kelio)")
        logger.info("")
        logger.info(">>> Fonctionnalités ConfigurationScoring:")
        logger.info("   Configurations par département et type d'urgence")
        logger.info("   Bonus hiérarchiques personnalisables")
        logger.info("   Pénalités configurables (indisponibilité, distance)")
        logger.info("   Suivi utilisation et performance par configuration")
        logger.info("   Tests et comparaisons de configurations")
        logger.info("   Optimisation automatique basée sur historique")
        logger.info(">>> =================================================")
        
        # Afficher les statistiques des configurations si disponibles
        try:
            nb_configs = ConfigurationScoring.objects.filter(actif=True).count()
            config_defaut = ConfigurationScoring.objects.filter(actif=True, configuration_par_defaut=True).first()
            
            logger.info(f">>> Configurations actives: {nb_configs}")
            if config_defaut:
                logger.info(f">>> Configuration par défaut: {config_defaut.nom}")
            else:
                logger.info(">>> Aucune configuration par défaut définie")
        
        except Exception as e:
            logger.info(f">>> ConfigurationScoring non disponible: {e}")
        
    except Exception as e:
        logger.error(f"ERROR Erreur affichage statistiques scoring V4.2: {e}")

# Afficher les statistiques au chargement du module
afficher_statistiques_scoring_v41()

# ================================================================
# FIN DU SERVICE SCORING V4.2 HARMONISE AVEC CONFIGURATIONSSCORING
# ================================================================