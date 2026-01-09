# -*- coding: utf-8 -*-
"""
Modeles Django pour le systeme de gestion d'interim - Version CORRIGEE
Hierarchie de validation : RESPONSABLE -> DIRECTEUR -> RH/ADMIN
Superutilisateurs : Droits complets automatiques

OK Hierarchie corrigee et coherente
OK Superutilisateurs avec droits complets
OK Types de validation alignes
OK Propositions humaines integrees au workflow
OK Scoring hybride (automatique + humain) 
OK Validation progressive multi-niveaux
OK Gestion complete des notifications
OK Historique detaille des actions
"""

from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.functional import cached_property
from django.conf import settings

from django.db.models import (
    Q, Count, Case, When, IntegerField, CharField, Value, F, Avg, Sum, Max, Min
)

from django.db.models.functions import Concat, Coalesce
import hashlib
import json
import uuid
import logging
from typing import Dict, Any, Tuple, Optional, Union, List
from datetime import datetime, date, timedelta

from django.contrib.auth.hashers import make_password, check_password
import base64

from utils.crypto_utils import KelioPasswordCipher

logger = logging.getLogger(__name__)

# ================================================================
# UTILITAIRES SECURISES
# ================================================================

def safe_date_operation(date1, date2, operation='subtract'):
    """Operation securisee sur les dates"""
    try:
        if date1 is None or date2 is None:
            return None
        if operation == 'subtract':
            return (date1 - date2).days
        elif operation == 'add':
            return date1 + date2
        return None
    except (TypeError, AttributeError, ValueError):
        return None

def safe_date_format(date_value, format_str='%d/%m/%Y'):
    """Formatage securise des dates"""
    try:
        if date_value is None:
            return "Non renseignee"
        return date_value.strftime(format_str)
    except (AttributeError, ValueError, TypeError):
        return "Date invalide"

def safe_datetime_format(datetime_value, format_str='%d/%m/%Y %H:%M'):
    """Formatage securise des datetime"""
    try:
        if datetime_value is None:
            return "Non renseigne"
        return datetime_value.strftime(format_str)
    except (AttributeError, ValueError, TypeError):
        return "DateTime invalide"

# ================================================================
# MIXINS ET CLASSES DE BASE
# ================================================================

class TimestampedModel(models.Model):
    """Mixin pour les modeles avec timestamps"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class ActiveModel(models.Model):
    """Mixin pour les modeles avec statut actif/inactif"""
    actif = models.BooleanField(default=True)
    
    class Meta:
        abstract = True

class KelioSyncMixin(models.Model):
    """Mixin pour les modeles synchronises avec Kelio"""
    kelio_last_sync = models.DateTimeField(null=True, blank=True)
    kelio_sync_status = models.CharField(
        max_length=20,
        choices=[
            ('JAMAIS', 'Jamais synchronise'),
            ('REUSSI', 'Synchronisation reussie'),
            ('PARTIEL', 'Synchronisation partielle'),
            ('ECHEC', 'Echec synchronisation')
        ],
        default='JAMAIS'
    )
    
    class Meta:
        abstract = True

# ================================================================
# MANAGERS OPTIMISES
# ================================================================

class ActiveManager(models.Manager):
    """Manager pour les objets actifs seulement"""
    def get_queryset(self):
        return super().get_queryset().filter(actif=True)

class BaseOptimizedManager(models.Manager):
    """Manager de base avec optimisations communes"""
    def get_queryset(self):
        return super().get_queryset()
    
    def actifs(self):
        """Filtre les objets actifs"""
        return self.filter(actif=True)

class ProfilUtilisateurManager(BaseOptimizedManager):
    """Manager optimise pour ProfilUtilisateur"""
    
    def get_queryset(self):
        return super().get_queryset().select_related('user')
    
    def with_full_relations(self):
        """Manager avec toutes les relations prechargees"""
        return self.select_related(
            'user', 'departement', 'site', 'poste', 'manager'
        ).prefetch_related(
            'competences__competence',
            'kelio_data',
            'extended_data'
        )
    
    def actifs_disponibles_interim(self):
        """Employes actifs et disponibles pour l'interim"""
        return self.with_full_relations().filter(
            actif=True,
            extended_data__disponible_interim=True,
            statut_employe='ACTIF'
        )

    def with_nom_complet(self):
        """Ajoute nom_complet calcule a la requete"""
        from django.db.models import Value, CharField
        from django.db.models.functions import Concat
        
        return self.select_related('user').annotate(
            nom_complet_calcule=Case(
                When(
                    user__isnull=False,
                    then=Concat(
                        'user__first_name',
                        Value(' '),
                        'user__last_name'
                    )
                ),
                default='matricule',
                output_field=CharField()
            )
        )

class DemandeInterimManager(BaseOptimizedManager):
    """Manager optimise pour les demandes d'interim"""
    
    def get_queryset(self):
        return super().get_queryset().select_related(
            'demandeur__user', 
            'personne_remplacee__user', 
            'poste__departement', 
            'poste__site', 
            'motif_absence'
        )
    
    def en_cours(self):
        """Demandes en cours de traitement"""
        return self.filter(
            statut__in=['SOUMISE', 'EN_VALIDATION', 'VALIDEE', 'EN_RECHERCHE', 'CANDIDAT_PROPOSE']
        )
    
    def urgentes(self):
        """Demandes urgentes"""
        return self.filter(urgence__in=['ELEVEE', 'CRITIQUE'])

# ================================================================
# MODELES DE CONFIGURATION KELIO ET SCORING
# ================================================================

class ConfigurationApiKelio(TimestampedModel, ActiveModel):
    """Configuration pour l'acces aux APIs Kelio avec mot de passe CRYPTE"""
    nom = models.CharField(max_length=100, unique=True)
    url_base = models.URLField(help_text="URL de base du service SOAP Kelio")
    username = models.CharField(max_length=100)
    
    # MODIFICATION : Champ password CRYPTE
    password_encrypted = models.CharField(
        max_length=500,  # Taille augmentée pour contenir le cryptage
        help_text="Mot de passe crypté (ne s'affiche pas en clair)",
        blank=True,
        default=""
    )
    
    timeout_seconds = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)]
    )
    
    # Services disponibles
    service_employees = models.BooleanField(default=True)
    service_absences = models.BooleanField(default=True)
    service_formations = models.BooleanField(default=False)
    service_competences = models.BooleanField(default=False)
    
    # Configuration cache
    cache_duree_defaut_minutes = models.IntegerField(default=60)
    cache_taille_max_mo = models.IntegerField(default=100)
    auto_invalidation_cache = models.BooleanField(default=True)
    
    # Instance du cipher pour cryptage/décryptage
    _cipher = KelioPasswordCipher()
    
    def save(self, *args, **kwargs):
        """Sauvegarde avec cryptage automatique du mot de passe si fourni"""
        # Note: On suppose que si password_encrypted est vide,
        # c'est qu'on n'a pas encore défini de mot de passe
        super().save(*args, **kwargs)
    
    def set_password(self, plain_password):
        """
        Crypte et stocke un mot de passe
        
        Args:
            plain_password (str): Mot de passe en clair
        """
        if not plain_password:
            self.password_encrypted = ""
            return
        
        try:
            encrypted = self._cipher.encrypt(plain_password)
            self.password_encrypted = encrypted
            logger.debug(f"Mot de passe crypté pour {self.nom}")
        except Exception as e:
            logger.error(f"Erreur cryptage mot de passe: {e}")
            raise
    
    def get_password(self):
        """
        Récupère le mot de passe décrypté
        
        Returns:
            str: Mot de passe en clair OU chaîne vide si erreur
        """
        if not self.password_encrypted:
            return ""
        
        try:
            return self._cipher.decrypt(self.password_encrypted)
        except Exception as e:
            logger.error(f"Erreur décryptage mot de passe: {e}")
            return ""
    
    def check_password(self, plain_password):
        """
        Vérifie si un mot de passe correspond
        
        Args:
            plain_password (str): Mot de passe à vérifier
            
        Returns:
            bool: True si correspond
        """
        try:
            stored_password = self.get_password()
            return stored_password == plain_password
        except Exception as e:
            logger.error(f"Erreur vérification mot de passe: {e}")
            return False
    
    @property
    def password_display(self):
        """Affichage sécurisé du mot de passe"""
        if self.password_encrypted:
            return "••••••••"
        return "Non défini"
    
    @property
    def password(self):
        """Propriété pour compatibilité avec l'ancien code"""
        return self.get_password()
    
    @password.setter
    def password(self, value):
        """Setter pour compatibilité avec l'ancien code"""
        self.set_password(value)
    
    def vider_cache(self):
        """Vide le cache associé"""
        count = self.caches.count()
        self.caches.all().delete()
        return count
    
    def __str__(self):
        return f"{self.nom} ({self.url_base})"
    
    class Meta:
        verbose_name = "Configuration API Kelio"
        verbose_name_plural = "Configurations API Kelio"

        
class ConfigurationScoring(TimestampedModel, ActiveModel):
    """Configuration des poids de scoring personnalisable par les administrateurs"""
    
    nom = models.CharField(
        max_length=100, 
        unique=True,
        help_text="Nom de la configuration (ex: 'Defaut', 'Technique', 'Commercial')"
    )
    description = models.TextField(
        blank=True,
        help_text="Description de cette configuration de scoring"
    )
    
    # Ponderations principales (doivent totaliser 1.0)
    poids_similarite_poste = models.FloatField(
        default=0.25,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Poids pour la similarite de poste (0.0 a 1.0)"
    )
    poids_competences = models.FloatField(
        default=0.25,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Poids pour les competences (0.0 a 1.0)"
    )
    poids_experience = models.FloatField(
        default=0.20,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Poids pour l'experience (0.0 a 1.0)"
    )
    poids_disponibilite = models.FloatField(
        default=0.15,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Poids pour la disponibilite (0.0 a 1.0)"
    )
    poids_proximite = models.FloatField(
        default=0.10,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Poids pour la proximite geographique (0.0 a 1.0)"
    )
    poids_anciennete = models.FloatField(
        default=0.05,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Poids pour l'anciennete (0.0 a 1.0)"
    )
    
    # Bonus speciaux selon la hierarchie CORRIGEE
    bonus_proposition_humaine = models.IntegerField(
        default=5,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus de base pour proposition humaine (0-50 points)"
    )
    bonus_experience_similaire = models.IntegerField(
        default=8,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour experience similaire (0-50 points)"
    )
    bonus_recommandation = models.IntegerField(
        default=10,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour qualite de recommandation (0-50 points)"
    )
    
    # OK BONUS HIERARCHIQUES CORRIGES
    bonus_manager_direct = models.IntegerField(
        default=12,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour proposition par manager direct (0-50 points)"
    )
    bonus_chef_equipe = models.IntegerField(
        default=8,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour proposition par chef d'equipe (0-50 points)"
    )
    bonus_responsable = models.IntegerField(
        default=15,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour proposition par RESPONSABLE (0-50 points)"
    )
    bonus_directeur = models.IntegerField(
        default=18,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour proposition par DIRECTEUR (0-50 points)"
    )
    bonus_rh = models.IntegerField(
        default=20,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour proposition par RH (0-50 points)"
    )
    bonus_admin = models.IntegerField(
        default=20,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour proposition par ADMIN (0-50 points)"
    )
    bonus_superuser = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus pour proposition par SUPERUTILISATEUR (0-50 points)"
    )
    
    # Penalites
    penalite_indisponibilite_partielle = models.IntegerField(
        default=15,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Penalite pour indisponibilite partielle (0-100 points)"
    )
    penalite_indisponibilite_totale = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Penalite pour indisponibilite totale (0-100 points)"
    )
    penalite_distance_excessive = models.IntegerField(
        default=10,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Penalite pour distance excessive (0-100 points)"
    )
    
    # Configuration et metadonnees
    configuration_par_defaut = models.BooleanField(
        default=False,
        help_text="Configuration utilisee par defaut"
    )
    
    # Restrictions d'utilisation
    pour_departements = models.ManyToManyField(
        'Departement',
        blank=True,
        help_text="Departements autorises a utiliser cette configuration"
    )
    pour_types_urgence = models.CharField(
        max_length=100,
        blank=True,
        help_text="Types d'urgence pour cette config (ex: 'NORMALE,ELEVEE')"
    )
    
    # Audit
    created_by = models.ForeignKey(
        'ProfilUtilisateur',
        on_delete=models.SET_NULL,
        null=True,
        related_name='configurations_scoring_creees'
    )
    last_used = models.DateTimeField(null=True, blank=True)
    nb_utilisations = models.IntegerField(default=0)
    
    def clean(self):
        """Validation des donnees"""
        super().clean()
        
        # Verifier que les poids totalisent 1.0 (avec tolerance)
        total_poids = (
            self.poids_similarite_poste +
            self.poids_competences +
            self.poids_experience +
            self.poids_disponibilite +
            self.poids_proximite +
            self.poids_anciennete
        )
        
        if abs(total_poids - 1.0) > 0.01:  # Tolerance de 1%
            raise ValidationError(
                f"La somme des poids doit etre egale a 1.0 (actuellement: {total_poids:.3f})"
            )
        
        # Une seule configuration par defaut
        if self.configuration_par_defaut:
            existing_default = ConfigurationScoring.objects.filter(
                configuration_par_defaut=True
            ).exclude(id=self.id)
            
            if existing_default.exists():
                raise ValidationError(
                    "Une configuration par defaut existe deja. "
                    "Desactivez-la avant d'en creer une nouvelle."
                )
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        
        # Invalider le cache des configurations
        cache.delete('scoring_configs_cache')
    
    def incrementer_utilisation(self):
        """Incremente le compteur d'utilisations"""
        self.nb_utilisations += 1
        self.last_used = timezone.now()
        self.save(update_fields=['nb_utilisations', 'last_used'])

    @classmethod
    def get_configuration_pour_demande(cls, demande):
        """
        Recupere la configuration de scoring appropriee pour une demande d'interim
        Compatible avec scoring_service.py V4.1
        """
        try:
            # 1. Rechercher une configuration specifique selon l'urgence
            if demande.urgence in ['ELEVEE', 'CRITIQUE']:
                config_urgence = cls.objects.filter(
                    actif=True,
                    pour_types_urgence__icontains=demande.urgence
                ).first()
                
                if config_urgence:
                    logger.debug(f">>> Configuration urgence trouvee pour {demande.urgence}")
                    return config_urgence
            
            # 2. Rechercher une configuration par departement
            if demande.poste and demande.poste.departement:
                config_dept = cls.objects.filter(
                    actif=True,
                    pour_departements=demande.poste.departement
                ).first()
                
                if config_dept:
                    logger.debug(f">>> Configuration departement trouvee pour {demande.poste.departement.nom}")
                    return config_dept
            
            # 3. Configuration par defaut
            config_defaut = cls.objects.filter(
                actif=True,
                configuration_par_defaut=True
            ).first()
            
            if config_defaut:
                logger.debug(">>> Configuration par defaut utilisee")
                return config_defaut
            
            # 4. Premiere configuration active disponible
            config_fallback = cls.objects.filter(actif=True).first()
            
            if config_fallback:
                logger.warning(">>> Aucune configuration defaut - Utilisation premiere config active")
                return config_fallback
            
            # 5. Aucune configuration - retourner None
            logger.warning("WARNING Aucune configuration de scoring active trouvee")
            return None
            
        except Exception as e:
            logger.error(f"ERROR Erreur recuperation configuration scoring: {e}")
            return None

    def get_poids_dict(self):
        """
        Retourne les poids sous forme de dictionnaire
        Compatible avec _ajuster_poids_selon_donnees_disponibles du scoring_service
        """
        try:
            return {
                'similarite_poste': float(self.poids_similarite_poste),
                'competences': float(self.poids_competences),
                'competences_kelio': float(self.poids_competences),  # Alias pour compatibilite V4.1
                'experience': float(self.poids_experience),
                'experience_kelio': float(self.poids_experience),    # Alias pour compatibilite V4.1
                'disponibilite': float(self.poids_disponibilite),
                'disponibilite_kelio': float(self.poids_disponibilite), # Alias pour compatibilite V4.1
                'proximite': float(self.poids_proximite),
                'anciennete': float(self.poids_anciennete)
            }
        except Exception as e:
            logger.error(f"ERROR Erreur conversion poids en dictionnaire: {e}")
            # Retourner les poids par defaut compatibles V4.1
            return {
                'similarite_poste': 0.25,
                'competences_kelio': 0.30,
                'experience_kelio': 0.20,
                'disponibilite_kelio': 0.15,
                'proximite': 0.10,
                'anciennete': 0.05
            }

    def est_compatible_urgence(self, urgence):
        """
        Verifie si cette configuration est compatible avec le niveau d'urgence
        """
        try:
            if not self.pour_types_urgence:
                return True  # Configuration universelle
            
            urgences_autorisees = [u.strip() for u in self.pour_types_urgence.split(',')]
            return urgence in urgences_autorisees
            
        except Exception as e:
            logger.error(f"ERROR Erreur verification compatibilite urgence: {e}")
            return True  # En cas d'erreur, autoriser

    def est_compatible_departement(self, departement):
        """
        Verifie si cette configuration est compatible avec le departement
        """
        try:
            if not self.pour_departements.exists():
                return True  # Configuration universelle
            
            return departement in self.pour_departements.all()
            
        except Exception as e:
            logger.error(f"ERROR Erreur verification compatibilite departement: {e}")
            return True  # En cas d'erreur, autoriser

    def calculer_bonus_hierarchique(self, source_proposition):
        """
        Calcule le bonus hierarchique selon la source de proposition
        Compatible avec _calculer_bonus_proposition du scoring_service V4.1
        """
        try:
            bonus_mapping = {
                'MANAGER_DIRECT': self.bonus_manager_direct,
                'CHEF_EQUIPE': self.bonus_chef_equipe,
                'RESPONSABLE': self.bonus_responsable,
                'DIRECTEUR': self.bonus_directeur,
                'RH': self.bonus_rh,
                'ADMIN': self.bonus_admin,
                'SUPERUSER': self.bonus_superuser,
            }
            
            return bonus_mapping.get(source_proposition, self.bonus_proposition_humaine)
            
        except Exception as e:
            logger.error(f"ERROR Erreur calcul bonus hierarchique: {e}")
            return self.bonus_proposition_humaine or 5

    @property
    def resume_configuration(self):
        """
        Retourne un resume de la configuration pour le debugging
        """
        try:
            return {
                'nom': self.nom,
                'actif': self.actif,
                'par_defaut': self.configuration_par_defaut,
                'poids_total': sum([
                    self.poids_similarite_poste,
                    self.poids_competences,
                    self.poids_experience,
                    self.poids_disponibilite,
                    self.poids_proximite,
                    self.poids_anciennete
                ]),
                'nb_departements': self.pour_departements.count(),
                'urgences': self.pour_types_urgence or 'TOUTES',
                'nb_utilisations': self.nb_utilisations,
                'derniere_utilisation': self.last_used.isoformat() if self.last_used else None
            }
        except Exception as e:
            logger.error(f"ERROR Erreur generation resume configuration: {e}")
            return {'nom': self.nom, 'erreur': str(e)}    

    def __str__(self):
        status = ">>> Actif" if self.actif else ">>> Inactif"
        default = " (Defaut)" if self.configuration_par_defaut else ""
        return f"{status} {self.nom}{default}"
    
    class Meta:
        verbose_name = "Configuration de scoring"
        verbose_name_plural = "Configurations de scoring"
        ordering = ['-configuration_par_defaut', 'nom']
        indexes = [
            models.Index(fields=['actif', 'configuration_par_defaut']),
        ]

class CacheApiKelio(TimestampedModel):
    """Cache optimise pour les reponses des APIs Kelio"""
    configuration = models.ForeignKey(
        ConfigurationApiKelio, 
        on_delete=models.CASCADE, 
        related_name='caches'
    )
    cle_cache = models.CharField(max_length=255, db_index=True)
    service_name = models.CharField(max_length=100, db_index=True)
    parametres_requete = models.JSONField()
    donnees = models.JSONField()
    
    date_expiration = models.DateTimeField(db_index=True)
    nb_acces = models.IntegerField(default=0)
    taille_donnees = models.IntegerField(default=0)
    
    @property
    def est_expire(self):
        try:
            return timezone.now() > self.date_expiration
        except (TypeError, AttributeError):
            return True
    
    def incrementer_acces(self):
        try:
            self.nb_acces += 1
            self.save(update_fields=['nb_acces'])
        except Exception:
            pass
    
    class Meta:
        unique_together = ['configuration', 'cle_cache']
        verbose_name = "Cache API Kelio"
        verbose_name_plural = "Caches API Kelio"
        ordering = ['-created_at']

# ================================================================
# MODELES ORGANISATIONNELS
# ================================================================

class Departement(TimestampedModel, ActiveModel):
    """Departements de l'organisation"""
    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    code = models.CharField(
        max_length=10, 
        unique=True,
        validators=[RegexValidator(r'^[A-Z0-9]{2,10}$', 'Code departement invalide')]
    )
    
    kelio_department_key = models.IntegerField(null=True, blank=True, unique=True)
    kelio_last_sync = models.DateTimeField(null=True, blank=True)
    
    manager = models.ForeignKey(
        'ProfilUtilisateur', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='departements_geres'
    )
    
    objects = BaseOptimizedManager()
    actifs = ActiveManager()
    
    def __str__(self):
        return self.nom
    
    @property
    def status_display(self):
        return ">>> Actif" if self.actif else ">>> Inactif"
    
    @cached_property
    def employes_count(self):
        """Nombre d'employes actifs du departement (avec cache)"""
        try:
            return self.employes.filter(actif=True).count()
        except Exception:
            return 0
    
    class Meta:
        verbose_name = "Departement"
        verbose_name_plural = "Departements"
        ordering = ['nom']

class Site(TimestampedModel, ActiveModel):
    """Sites geographiques de l'organisation"""
    nom = models.CharField(max_length=100)
    adresse = models.TextField()
    ville = models.CharField(max_length=50)
    code_postal = models.CharField(
        max_length=10,
        validators=[RegexValidator(r'^\d{5}$', 'Code postal invalide')]
    )
    pays = models.CharField(max_length=50, default='Cote d\'Ivoire')
    telephone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    
    kelio_site_key = models.IntegerField(null=True, blank=True, unique=True)
    kelio_last_sync = models.DateTimeField(null=True, blank=True)
    
    responsable = models.ForeignKey(
        'ProfilUtilisateur', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='sites_geres'
    )
    
    objects = BaseOptimizedManager()
    actifs = ActiveManager()
    
    def __str__(self):
        return f"{self.nom} - {self.ville}"
    
    @property
    def adresse_complete(self):
        return f"{self.adresse}, {self.code_postal} {self.ville}, {self.pays}"
    
    @property
    def status_display(self):
        return ">>> Actif" if self.actif else ">>> Inactif"
    
    class Meta:
        verbose_name = "Site"
        verbose_name_plural = "Sites"
        ordering = ['ville', 'nom']

class Poste(TimestampedModel, ActiveModel):
    """Postes de travail disponibles"""
    titre = models.CharField(max_length=100)
    description = models.TextField()
    departement = models.ForeignKey(
        Departement, 
        on_delete=models.CASCADE, 
        related_name='postes'
    )
    site = models.ForeignKey(
        Site, 
        on_delete=models.CASCADE, 
        related_name='postes'
    )
    
    kelio_job_key = models.IntegerField(null=True, blank=True)
    
    niveau_etude_min = models.CharField(max_length=50, blank=True)
    experience_min_mois = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(600)]
    )
    permis_requis = models.BooleanField(default=False)
    
    categorie = models.CharField(max_length=50, blank=True)
    niveau_responsabilite = models.IntegerField(
        default=1, 
        choices=[(1, 'Execution'), (2, 'Maitrise'), (3, 'Cadre')],
        help_text="Niveau de responsabilite"
    )
    
    interim_autorise = models.BooleanField(default=True)
    
    objects = BaseOptimizedManager()
    actifs = ActiveManager()
    
    def __str__(self):
        return f"{self.titre} - {self.site.nom}"
    
    @property
    def niveau_responsabilite_display(self):
        niveaux = {1: ">>> Execution", 2: ">>> Maitrise", 3: ">>> Cadre"}
        return niveaux.get(self.niveau_responsabilite, ">>> Non defini")
    
    @property
    def status_display(self):
        statuts = []
        if self.actif:
            statuts.append(">>> Actif")
        else:
            statuts.append(">>> Inactif")
        
        if self.interim_autorise:
            statuts.append(">>> Interim autorise")
        
        return " | ".join(statuts)
    
    class Meta:
        verbose_name = "Poste"
        verbose_name_plural = "Postes"
        ordering = ['departement__nom', 'titre']

# ================================================================
# MODELES UTILISATEUR AVEC HIERARCHIE CORRIGEE
# ================================================================

class ProfilUtilisateur(TimestampedModel, ActiveModel, KelioSyncMixin):
    """Profil utilisateur principal avec synchronisation User Django"""
    
    # Types de profil hierarchises CORRIGES
    TYPES_PROFIL = [
        ('UTILISATEUR', 'Utilisateur standard'),
        ('CHEF_EQUIPE', 'Chef d\'equipe'),              # OK Peut proposer, ne valide pas
        ('RESPONSABLE', 'Responsable (N+1)'),           # OK Niveau 1 de validation
        ('DIRECTEUR', 'Directeur (N+2)'),               # OK Niveau 2 de validation  
        ('RH', 'RH (Final)'),                           # OK Niveau 3 de validation
        ('ADMIN', 'Administrateur (Final)'),            # OK Niveau 3 etendu
    ]
    
    STATUTS_EMPLOYE = [
        ('ACTIF', 'Actif'),
        ('CONGE', 'En conge'),
        ('FORMATION', 'En formation'),
        ('ARRET', 'Arret maladie'),
        ('SUSPENDU', 'Suspendu'),
        ('DEMISSION', 'Demission'),
        ('LICENCIE', 'Licencie'),
    ]
    
    # Relation avec User Django
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        null=True, blank=True,
        help_text="Utilisateur Django associe"
    )
    
    # Informations de base
    matricule = models.CharField(max_length=20, unique=True)
    type_profil = models.CharField(max_length=20, choices=TYPES_PROFIL, default='UTILISATEUR')
    statut_employe = models.CharField(max_length=20, choices=STATUTS_EMPLOYE, default='ACTIF')
    
    # Relations organisationnelles
    departement = models.ForeignKey(
        Departement, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='employes'
    )
    site = models.ForeignKey(
        Site, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='employes'
    )
    poste = models.ForeignKey(
        Poste, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='employes'
    )
    manager = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='equipe'
    )
    
    # Donnees Kelio
    kelio_employee_key = models.IntegerField(null=True, blank=True, unique=True)
    kelio_badge_code = models.CharField(max_length=16, blank=True)
    
    # Dates importantes
    date_embauche = models.DateField(null=True, blank=True)
    date_fin_contrat = models.DateField(null=True, blank=True)
    
    objects = ProfilUtilisateurManager()
    actifs = ActiveManager()
    
    def save(self, *args, **kwargs):
        """Sauvegarde avec synchronisation User Django"""
        # Si c'est une nouvelle instance sans user associe, ne pas creer automatiquement
        # La creation du User sera geree par le formulaire admin
        super().save(*args, **kwargs)
    
    def sync_with_user(self, commit=True):
        """Synchronise les donnees avec l'utilisateur Django associe"""
        if not self.user:
            return False
        
        try:
            # Synchroniser les informations de base
            # Note: Le prenom/nom sont geres par le formulaire admin
            # Cette methode peut etre utilisee pour d'autres synchronisations
            
            if commit:
                self.user.save()
            
            return True
        except Exception as e:
            logger.error(f"Erreur synchronisation ProfilUtilisateur/User: {e}")
            return False
    
    def set_user_password(self, raw_password, commit=True):
        """Definit le mot de passe pour l'utilisateur Django associe"""
        if not self.user:
            return False
        
        try:
            self.user.set_password(raw_password)
            if commit:
                self.user.save()
            return True
        except Exception as e:
            logger.error(f"Erreur definition mot de passe utilisateur: {e}")
            return False
    
    def check_user_password(self, raw_password):
        """Verifie le mot de passe de l'utilisateur Django associe"""
        if not self.user:
            return False
        
        try:
            return self.user.check_password(raw_password)
        except Exception:
            return False
    
    @property
    def nom_complet(self):
        """Nom complet de l'utilisateur avec gestion d'erreurs"""
        try:
            if self.user and self.user.first_name and self.user.last_name:
                return f"{self.user.first_name} {self.user.last_name}".strip()
            elif self.user and self.user.username:
                return self.user.username
            else:
                return f"Matricule {self.matricule}"
        except AttributeError:
            return f"Matricule {self.matricule}"
        
    @property
    def is_superuser(self):
        """Verifie si l'utilisateur est superuser"""
        return self.user and self.user.is_superuser
    
    def peut_proposer_candidat(self, demande):
        """Verifie si l'utilisateur peut proposer un candidat pour une demande"""
        # Superusers peuvent toujours proposer
        if self.is_superuser:
            return True, "Superutilisateur - droits complets"
        
        # Verifications selon le type de profil
        if self.type_profil in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']:
            return True, f"Autorise comme {self.type_profil}"
        
        # Utilisateurs standards peuvent proposer s'ils sont dans le departement concerne
        if self.type_profil == 'UTILISATEUR':
            if self.departement == demande.poste.departement:
                return True, "Autorise - meme departement"
            else:
                return False, "Non autorise - departement different"
        
        return False, "Type de profil non autorise a proposer"
    
    def peut_valider_niveau(self, niveau):
        """Verifie si l'utilisateur peut valider a un niveau donne"""
        # Superusers peuvent valider a tous les niveaux
        if self.is_superuser:
            return True
        
        # Mapping niveau -> type de profil requis
        niveaux_validation = {
            1: ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'],  # Niveau 1 et plus
            2: ['DIRECTEUR', 'RH', 'ADMIN'],                 # Niveau 2 et plus
            3: ['RH', 'ADMIN'],                              # Niveau 3 seulement
        }
        
        return self.type_profil in niveaux_validation.get(niveau, [])

    def est_disponible_pour_interim(self, date_debut, date_fin=None):
        """
        Version simplifiée pour la vérification de disponibilité
        Compatible avec le ScoringInterimService V4.1
        
        Args:
            date_debut: str ou datetime.date - Date de début
            date_fin: str ou datetime.date - Date de fin (optionnelle)
        
        Returns:
            dict: {'disponible': bool, 'raison': str, 'score_disponibilite': int}
        """
        try:
            from datetime import datetime, date
            
            # Conversion des dates si nécessaire
            if isinstance(date_debut, str):
                try:
                    date_debut = datetime.strptime(date_debut, '%Y-%m-%d').date()
                except ValueError:
                    date_debut = datetime.strptime(date_debut, '%d/%m/%Y').date()
            
            if date_fin and isinstance(date_fin, str):
                try:
                    date_fin = datetime.strptime(date_fin, '%Y-%m-%d').date()
                except ValueError:
                    date_fin = datetime.strptime(date_fin, '%d/%m/%Y').date()
            
            if not date_fin:
                date_fin = date_debut
            
            # Vérifications de base
            if not self.actif:
                return {
                    'disponible': False,
                    'raison': 'Employé inactif',
                    'score_disponibilite': 0
                }
            
            if self.statut_employe in ['DEMISSION', 'LICENCIE', 'SUSPENDU']:
                return {
                    'disponible': False,
                    'raison': f'Statut: {self.get_statut_employe_display()}',
                    'score_disponibilite': 0
                }
            
            # Vérification disponibilité générale
            try:
                if hasattr(self, 'extended_data') and self.extended_data:
                    if not self.extended_data.disponible_interim:
                        return {
                            'disponible': False,
                            'raison': 'Non disponible pour l\'intérim',
                            'score_disponibilite': 0
                        }
            except Exception:
                pass  # Continuer si pas de données étendues
            
            # Score de base selon le statut
            if self.statut_employe == 'ACTIF':
                score = 100
                disponible = True
                raison = 'Disponible'
            elif self.statut_employe == 'CONGE':
                score = 60
                disponible = True
                raison = 'Disponible (en congé)'
            elif self.statut_employe == 'FORMATION':
                score = 70
                disponible = True
                raison = 'Disponible (en formation)'
            else:
                score = 80
                disponible = True
                raison = 'Disponible'
            
            # Vérification rapide des conflits si les relations existent
            conflits_detectes = []
            
            try:
                # Absences
                if hasattr(self, 'absences'):
                    absences_conflictuelles = self.absences.filter(
                        date_debut__lte=date_fin,
                        date_fin__gte=date_debut
                    )
                    
                    for absence in absences_conflictuelles:
                        # Calculer le chevauchement
                        debut_conflit = max(absence.date_debut, date_debut)
                        fin_conflit = min(absence.date_fin, date_fin)
                        jours_conflit = (fin_conflit - debut_conflit).days + 1
                        jours_mission = (date_fin - date_debut).days + 1
                        pourcentage_conflit = (jours_conflit / jours_mission) * 100
                        
                        conflits_detectes.append({
                            'type': 'absence',
                            'detail': absence.type_absence,
                            'pourcentage': pourcentage_conflit,
                            'date_debut': absence.date_debut,
                            'date_fin': absence.date_fin
                        })
            except Exception:
                pass
            
            try:
                # Missions en cours
                if hasattr(self, 'selections_interim'):
                    missions_actives = self.selections_interim.filter(
                        statut='EN_COURS',
                        date_debut__lte=date_fin,
                        date_fin__gte=date_debut
                    )
                    
                    for mission in missions_actives:
                        debut_conflit = max(mission.date_debut, date_debut)
                        fin_conflit = min(mission.date_fin, date_fin)
                        jours_conflit = (fin_conflit - debut_conflit).days + 1
                        jours_mission = (date_fin - date_debut).days + 1
                        pourcentage_conflit = (jours_conflit / jours_mission) * 100
                        
                        conflits_detectes.append({
                            'type': 'mission',
                            'detail': mission.numero_demande,
                            'pourcentage': pourcentage_conflit,
                            'date_debut': mission.date_debut,
                            'date_fin': mission.date_fin
                        })
            except Exception:
                pass
            
            try:
                # Indisponibilités
                if hasattr(self, 'disponibilites'):
                    indispos = self.disponibilites.filter(
                        date_debut__lte=date_fin,
                        date_fin__gte=date_debut,
                        type_disponibilite__in=['INDISPONIBLE', 'EN_MISSION', 'CONGE', 'FORMATION']
                    )
                    
                    for indispo in indispos:
                        debut_conflit = max(indispo.date_debut, date_debut)
                        fin_conflit = min(indispo.date_fin, date_fin)
                        jours_conflit = (fin_conflit - debut_conflit).days + 1
                        jours_mission = (date_fin - date_debut).days + 1
                        pourcentage_conflit = (jours_conflit / jours_mission) * 100
                        
                        conflits_detectes.append({
                            'type': 'indisponibilité',
                            'detail': indispo.type_disponibilite,
                            'pourcentage': pourcentage_conflit,
                            'date_debut': indispo.date_debut,
                            'date_fin': indispo.date_fin
                        })
            except Exception:
                pass
            
            # Analyser les conflits et déterminer la disponibilité
            conflits_complets = [c for c in conflits_detectes if c['pourcentage'] >= 100]
            conflits_partiels = [c for c in conflits_detectes if 0 < c['pourcentage'] < 100]
            
            if conflits_complets:
                # Vérifier s'il y a des créneaux libres avant ou après
                conflit_principal = min(conflits_complets, key=lambda x: x['date_debut'])
                
                # Y a-t-il de la place avant le conflit ?
                if conflit_principal['date_debut'] > date_debut:
                    disponible = True
                    raison = f"Disponible avant le {conflit_principal['date_debut'].strftime('%d/%m/%Y')} ({conflit_principal['detail']})"
                    score = max(40, score - 30)
                else:
                    # Y a-t-il de la place après le conflit ?
                    conflit_fin = max(conflits_complets, key=lambda x: x['date_fin'])
                    if conflit_fin['date_fin'] < date_fin:
                        disponible = True
                        raison = f"Disponible après le {conflit_fin['date_fin'].strftime('%d/%m/%Y')} ({conflit_fin['detail']})"
                        score = max(40, score - 30)
                    else:
                        disponible = False
                        raison = f"Indisponible - {conflit_principal['detail']} du {conflit_principal['date_debut'].strftime('%d/%m/%Y')} au {conflit_principal['date_fin'].strftime('%d/%m/%Y')}"
                        score = 0
            
            elif conflits_partiels:
                conflit_max = max(conflits_partiels, key=lambda x: x['pourcentage'])
                
                if conflit_max['pourcentage'] < 50:
                    # Conflit mineur
                    disponible = True
                    raison = f"Disponible avec {conflit_max['detail']} partiel ({conflit_max['pourcentage']:.0f}% de conflit)"
                    score = max(60, score - 20)
                else:
                    # Conflit majeur - vérifier les créneaux
                    if conflit_max['date_debut'] > date_debut:
                        disponible = True
                        raison = f"Disponible avant le {conflit_max['date_debut'].strftime('%d/%m/%Y')} ({conflit_max['detail']})"
                        score = max(45, score - 25)
                    elif conflit_max['date_fin'] < date_fin:
                        disponible = True
                        raison = f"Disponible après le {conflit_max['date_fin'].strftime('%d/%m/%Y')} ({conflit_max['detail']})"
                        score = max(45, score - 25)
                    else:
                        disponible = False
                        raison = f"Indisponible - {conflit_max['detail']} ({conflit_max['pourcentage']:.0f}% de conflit)"
                        score = max(10, score - 40)
            
            # Assurer les bornes du score
            score = max(0, min(100, score))
            
            return {
                'disponible': disponible,
                'raison': raison,
                'score_disponibilite': score
            }
            
        except Exception as e:
            return {
                'disponible': False,
                'raison': f'Erreur: {str(e)}',
                'score_disponibilite': 0
            }

    def __str__(self):
        return f"{self.matricule} - {self.nom_complet}"
    
    class Meta:
        verbose_name = "Profil utilisateur"
        verbose_name_plural = "Profils utilisateurs"
        ordering = ['matricule']



class ProfilUtilisateurKelio(TimestampedModel):
    """Donnees specifiques a la synchronisation Kelio"""
    profil = models.OneToOneField(
        ProfilUtilisateur, 
        on_delete=models.CASCADE, 
        related_name='kelio_data'
    )
    
    kelio_employee_key = models.IntegerField(null=True, blank=True, unique=True)
    kelio_badge_code = models.CharField(max_length=16, blank=True)
    
    telephone_kelio = models.CharField(max_length=20, blank=True)
    email_kelio = models.EmailField(blank=True)
    date_embauche_kelio = models.DateField(null=True, blank=True)
    type_contrat_kelio = models.CharField(max_length=100, blank=True)
    temps_travail_kelio = models.FloatField(default=1.0)
    
    code_personnel = models.CharField(max_length=20, blank=True)
    profil_acces = models.CharField(max_length=100, blank=True)
    horaires_specifiques_autorises = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Donnees Kelio - {self.profil.nom_complet}"
    
    class Meta:
        verbose_name = "Donnees Kelio utilisateur"
        verbose_name_plural = "Donnees Kelio utilisateurs"

class ProfilUtilisateurExtended(TimestampedModel):
    """Donnees etendues du profil utilisateur"""
    profil = models.OneToOneField(
        ProfilUtilisateur, 
        on_delete=models.CASCADE, 
        related_name='extended_data'
    )
    
    telephone = models.CharField(max_length=20, blank=True)
    telephone_portable = models.CharField(max_length=20, blank=True)
    
    date_embauche = models.DateField(null=True, blank=True)
    date_fin_contrat = models.DateField(null=True, blank=True)
    type_contrat = models.CharField(max_length=100, blank=True)
    temps_travail = models.FloatField(
        default=1.0, 
        validators=[MinValueValidator(0.1), MaxValueValidator(1.0)]
    )
    
    prochaine_visite_medicale = models.DateField(null=True, blank=True)
    permis_conduire = models.CharField(max_length=50, blank=True)
    situation_handicap = models.BooleanField(default=False)
    
    coefficient = models.CharField(max_length=100, blank=True)
    niveau_classification = models.CharField(max_length=100, blank=True)
    statut_professionnel = models.CharField(max_length=100, blank=True)
    
    disponible_interim = models.BooleanField(default=True)
    rayon_deplacement_km = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(500)]
    )
    
    class Meta:
        verbose_name = "Donnees etendues utilisateur"
        verbose_name_plural = "Donnees etendues utilisateurs"

# ================================================================
# AUTRES MODELES (simplifies pour eviter les erreurs)
# ================================================================

class Competence(TimestampedModel, ActiveModel):
    """Referentiel des competences"""
    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    categorie = models.CharField(max_length=50, blank=True)
    
    kelio_skill_key = models.IntegerField(null=True, blank=True, unique=True)
    kelio_skill_abbreviation = models.CharField(max_length=10, blank=True)
    
    type_competence = models.CharField(
        max_length=20,
        choices=[
            ('TECHNIQUE', 'Technique'),
            ('TRANSVERSE', 'Transverse'),
            ('COMPORTEMENTALE', 'Comportementale'),
            ('LINGUISTIQUE', 'Linguistique'),
            ('LOGICIEL', 'Logiciel'),
        ],
        default='TECHNIQUE'
    )
    
    obsolete = models.BooleanField(default=False)
    
    objects = BaseOptimizedManager()
    actives = ActiveManager()
    
    def __str__(self):
        return self.nom
    
    class Meta:
        verbose_name = "Competence"
        verbose_name_plural = "Competences"
        ordering = ['categorie', 'nom']

class CompetenceUtilisateur(TimestampedModel):
    """Competences possedees par un utilisateur"""
    NIVEAUX_MAITRISE = [
        (1, 'Debutant'),
        (2, 'Intermediaire'),
        (3, 'Confirme'),
        (4, 'Expert'),
    ]
    
    SOURCES_DONNEE = [
        ('LOCAL', 'Saisie locale'),
        ('KELIO', 'Importe Kelio'),
        ('MIXTE', 'Mixte')
    ]
    
    utilisateur = models.ForeignKey(
        ProfilUtilisateur, 
        on_delete=models.CASCADE, 
        related_name='competences'
    )
    competence = models.ForeignKey(
        Competence, 
        on_delete=models.CASCADE, 
        related_name='competences_utilisateurs'
    )
    niveau_maitrise = models.IntegerField(
        choices=NIVEAUX_MAITRISE,
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    source_donnee = models.CharField(max_length=10, choices=SOURCES_DONNEE, default='LOCAL')
    
    kelio_skill_assignment_key = models.IntegerField(null=True, blank=True)
    kelio_level = models.CharField(max_length=50, blank=True)
    
    date_acquisition = models.DateField(null=True, blank=True)
    date_evaluation = models.DateField(null=True, blank=True)
    certifie = models.BooleanField(default=False)
    date_certification = models.DateField(null=True, blank=True)
    organisme_certificateur = models.CharField(max_length=100, blank=True)
    
    evaluateur = models.ForeignKey(
        ProfilUtilisateur, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='competences_evaluees'
    )
    commentaire = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.utilisateur.nom_complet} - {self.competence.nom} (Niveau {self.niveau_maitrise})"
    
    class Meta:
        unique_together = ['utilisateur', 'competence']
        verbose_name = "Competence utilisateur"
        verbose_name_plural = "Competences utilisateurs"
        ordering = ['-niveau_maitrise', 'competence__nom']

class MotifAbsence(TimestampedModel, ActiveModel):
    """Motifs d'absence standardises"""
    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    code = models.CharField(
        max_length=10, 
        unique=True,
        validators=[RegexValidator(r'^[A-Z0-9]{2,10}$', 'Code motif invalide')]
    )
    
    kelio_absence_type_key = models.IntegerField(null=True, blank=True, unique=True)
    kelio_abbreviation = models.CharField(max_length=5, blank=True)
    
    necessite_justificatif = models.BooleanField(default=False)
    delai_prevenance_jours = models.IntegerField(
        default=7,
        validators=[MinValueValidator(0), MaxValueValidator(365)]
    )
    duree_max_jours = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(365)]
    )
    
    categorie = models.CharField(
        max_length=20,
        choices=[
            ('MALADIE', 'Maladie'),
            ('CONGE', 'Conge'),
            ('FORMATION', 'Formation'),
            ('PERSONNEL', 'Personnel'),
            ('PROFESSIONNEL', 'Professionnel'),
        ],
        default='PERSONNEL'
    )
    
    couleur = models.CharField(
        max_length=7, 
        default='#007bff', 
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Couleur hex invalide')]
    )
    
    objects = BaseOptimizedManager()
    actifs = ActiveManager()
    
    def __str__(self):
        return self.nom
    
    class Meta:
        verbose_name = "Motif d'absence"
        verbose_name_plural = "Motifs d'absence"
        ordering = ['categorie', 'nom']

# ================================================================
# MODELES WORKFLOW - Version simplifiee
# ================================================================

class WorkflowEtape(models.Model):
    """Etapes du workflow de validation d'interim"""
    TYPES_ETAPE = [
        ('DEMANDE', 'Creation de demande'),
        ('PROPOSITION_CANDIDATS', 'Proposition de candidats'),
        ('VALIDATION_RESPONSABLE', 'Validation Responsable (N+1)'),
        ('VALIDATION_DIRECTEUR', 'Validation Directeur (N+2)'),
        ('VALIDATION_RH_ADMIN', 'Validation RH/Admin (Final)'),
        ('NOTIFICATION_CANDIDAT', 'Notification candidat'),
        ('ACCEPTATION_CANDIDAT', 'Acceptation candidat'),
        ('FINALISATION', 'Finalisation'),
    ]
    
    nom = models.CharField(max_length=100)
    type_etape = models.CharField(max_length=30, choices=TYPES_ETAPE)
    ordre = models.IntegerField()
    obligatoire = models.BooleanField(default=True)
    delai_max_heures = models.IntegerField(null=True, blank=True)
    condition_urgence = models.CharField(
        max_length=15,
        choices=[('TOUTES', 'Toutes'), ('NORMALE', 'Normale'), ('ELEVEE', 'Elevee'), ('CRITIQUE', 'Critique')],
        default='TOUTES'
    )
    permet_propositions_humaines = models.BooleanField(default=True)
    permet_ajout_nouveaux_candidats = models.BooleanField(default=True)
    actif = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['ordre']
        verbose_name = "Etape de workflow"
        verbose_name_plural = "Etapes de workflow"
    
    def __str__(self):
        return f"{self.ordre}. {self.nom}"

class DemandeInterim(TimestampedModel):
    """Demandes de remplacement temporaire"""
    STATUTS = [
        ('BROUILLON', 'Brouillon'),
        ('SOUMISE', 'Soumise'),
        ('EN_PROPOSITION', 'En recherche/proposition candidats'),
        ('EN_VALIDATION', 'En validation'),
        ('CANDIDAT_PROPOSE', 'Candidat propose'),
        ('EN_COURS', 'En cours'),
        ('TERMINEE', 'Terminee'),
        ('REFUSEE', 'Refusee'),
        ('ANNULEE', 'Annulee'),
    ]
    
    URGENCES = [
        ('NORMALE', 'Normale'),
        ('MOYENNE', 'Moyenne'),
        ('ELEVEE', 'Elevee'),
        ('CRITIQUE', 'Critique'),
    ]
    
    numero_demande = models.CharField(max_length=20, unique=True, editable=False)
    
    demandeur = models.ForeignKey(
        ProfilUtilisateur, 
        on_delete=models.CASCADE, 
        related_name='demandes_soumises'
    )
    personne_remplacee = models.ForeignKey(
        ProfilUtilisateur, 
        on_delete=models.CASCADE, 
        related_name='remplacements'
    )
    
    poste = models.ForeignKey(
        Poste, 
        on_delete=models.CASCADE, 
        related_name='demandes_interim'
    )
    date_debut = models.DateField(null=True, blank=True)
    date_fin = models.DateField(null=True, blank=True)
    
    motif_absence = models.ForeignKey(
        MotifAbsence, 
        on_delete=models.CASCADE, 
        related_name='demandes'
    )
    urgence = models.CharField(max_length=15, choices=URGENCES, default='NORMALE')
    
    description_poste = models.TextField()
    instructions_particulieres = models.TextField(blank=True)
    competences_indispensables = models.TextField(blank=True)
    
    statut = models.CharField(max_length=20, choices=STATUTS, default='BROUILLON')
    candidat_selectionne = models.ForeignKey(
        ProfilUtilisateur, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='selections_interim'
    )
    
    # Configuration workflow
    propositions_autorisees = models.BooleanField(default=True)
    nb_max_propositions_par_utilisateur = models.IntegerField(default=3)
    date_limite_propositions = models.DateTimeField(null=True, blank=True)
    
    # Niveaux de validation selon la hierarchie CORRIGEE
    niveau_validation_actuel = models.IntegerField(default=0)

    niveaux_validation_requis = models.IntegerField(
        default=3,  # OK RESPONSABLE (1) -> DIRECTEUR (2) -> RH/ADMIN (3)
        help_text="Nombre de niveaux de validation requis (3 par defaut : N+1 -> N+2 -> N+3)"
    )

    # Scoring
    poids_scoring_automatique = models.FloatField(default=0.7)
    poids_scoring_humain = models.FloatField(default=0.3)
    
    # Dates de validation
    date_validation = models.DateTimeField(null=True, blank=True)
    date_debut_effective = models.DateField(null=True, blank=True)
    date_fin_effective = models.DateField(null=True, blank=True)
    
    # Evaluation finale
    evaluation_mission = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    commentaire_final = models.TextField(blank=True)
    
    objects = DemandeInterimManager()
    
    def save(self, *args, **kwargs):
        if not self.numero_demande:
            self.numero_demande = f"INT-{timezone.now().year}-{str(uuid.uuid4())[:8].upper()}"
        
        # OK CORRECTION : Initialiser niveaux_validation_requis si non defini
        if not self.niveaux_validation_requis:
            self.niveaux_validation_requis = 3  # Valeur par defaut
        
        super().save(*args, **kwargs)
        
    def peut_proposer_candidat(self, utilisateur):
        """Verifie si un utilisateur peut proposer un candidat"""
        if not self.propositions_autorisees:
            return False, "Les propositions ne sont pas autorisees pour cette demande"
        
        if self.date_limite_propositions and timezone.now() > self.date_limite_propositions:
            return False, "La date limite de proposition est depassee"
        
        # Verifier le nombre de propositions deja faites par cet utilisateur
        nb_propositions = self.propositions_candidats.filter(
            proposant=utilisateur
        ).count()
        
        if nb_propositions >= self.nb_max_propositions_par_utilisateur:
            return False, f"Limite de {self.nb_max_propositions_par_utilisateur} propositions atteinte"
        
        # Verifier les permissions metier
        peut_proposer, raison = utilisateur.peut_proposer_candidat(self)
        return peut_proposer, raison
    
    @property
    def duree_mission(self):
        """Duree de la mission en jours"""
        if self.date_debut and self.date_fin:
            try:
                return (self.date_fin - self.date_debut).days + 1
            except (TypeError, AttributeError):
                return 0
        return 0
    
    @property
    def est_urgente(self):
        return self.urgence in ['ELEVEE', 'CRITIQUE']
    
    @property
    def peut_etre_modifiee(self):
        return self.statut in ['BROUILLON', 'SOUMISE']

    def get_niveau_validation_requis(self):
        """Determine le nombre de niveaux requis selon l'urgence"""
        if self.urgence == 'CRITIQUE':
            return 2  # DIRECTEUR -> RH (accelere)
        else:
            return 3  # RESPONSABLE -> DIRECTEUR -> RH (normal)

    def _verifier_progression_workflow_coherente(self, niveau_propose):
        """
        OK NOUVELLE FONCTION - Verifie que la progression est coherente
        """
        niveau_actuel = self.niveau_validation_actuel
        
        # Verifier que c'est bien le niveau suivant
        if niveau_propose != niveau_actuel + 1:
            return False, f"Niveau incoherent: actuel={niveau_actuel}, propose={niveau_propose}"
        
        # Verifier qu'on ne depasse pas le maximum
        if niveau_propose > self.niveaux_validation_requis:
            return False, f"Niveau superieur au maximum: {niveau_propose} > {self.niveaux_validation_requis}"
        
        return True, "Progression coherente"

    def _determiner_type_validation_corrige(self, profil_utilisateur, niveau_validation):
        """
        OK FONCTION CORRIGEE - Determine le type selon le niveau et le profil
        """
        if profil_utilisateur.is_superuser:
            return 'SUPERUSER'
        
        # OK Mapping strict niveau -> type
        mapping_niveau_type = {
            1: 'RESPONSABLE',
            2: 'DIRECTEUR',
            3: 'RH' if profil_utilisateur.type_profil == 'RH' else 'ADMIN'
        }
        
        type_attendu = mapping_niveau_type.get(niveau_validation)
        
        # Verifier la coherence
        if type_attendu and profil_utilisateur.type_profil in [type_attendu, 'ADMIN', 'RH']:
            return type_attendu
        
        # Fallback securise
        return profil_utilisateur.type_profil

    @property
    def progression_pct(self):
        """
        Calcule le pourcentage de progression du workflow de validation
        Basé sur le statut, niveau de validation et étapes franchies
        Compatible avec la logique des vues workflow
        """
        try:
            # Mapping des statuts vers pourcentages de base
            statut_progression = {
                'BROUILLON': 5,
                'SOUMISE': 15,
                'EN_PROPOSITION': 25,
                'EN_VALIDATION': 35,  # Point de départ pour validation
                'CANDIDAT_PROPOSE': 75,
                'CANDIDAT_SELECTIONNE': 75,  # Alias pour CANDIDAT_PROPOSE
                'VALIDATION_DRH_PENDING': 60,  # État intermédiaire
                'VALIDEE': 85,
                'EN_COURS': 90,
                'TERMINEE': 100,
                'REFUSEE': 0,
                'ANNULEE': 0,
            }
            
            # Progression de base selon le statut
            progression_base = statut_progression.get(self.statut, 0)
            
            # Calcul spécifique pour les états de validation
            if self.statut in ['EN_VALIDATION', 'VALIDATION_DRH_PENDING']:
                progression_finale = self._calculer_progression_validation()
            else:
                progression_finale = progression_base
            
            # Bonus selon l'urgence (workflow accéléré)
            if self.urgence in ['ELEVEE', 'CRITIQUE'] and self.statut not in ['TERMINEE', 'REFUSEE', 'ANNULEE']:
                # Petit bonus pour les urgences (max 5%)
                bonus_urgence = min(5, progression_finale * 0.05)
                progression_finale = min(100, progression_finale + bonus_urgence)
            
            # Assurer que le pourcentage reste dans les bornes
            return max(0, min(100, int(progression_finale)))
            
        except Exception as e:
            # En cas d'erreur, retourner une valeur basée sur le statut simple
            return self._progression_fallback()

    def _calculer_progression_validation(self):
        """
        Calcule la progression détaillée dans la phase de validation
        Compatible avec la hiérarchie RESPONSABLE -> DIRECTEUR -> RH/ADMIN
        """
        try:
            # Récupérer les paramètres de validation
            niveau_actuel = getattr(self, 'niveau_validation_actuel', 0) or 0
            niveaux_requis = getattr(self, 'niveaux_validation_requis', 3) or 3
            
            # Plage de progression pour la validation : 35% à 75%
            progression_min = 35
            progression_max = 75
            plage_validation = progression_max - progression_min
            
            if niveaux_requis > 0:
                # Calcul proportionnel du niveau atteint
                ratio_completion = min(1.0, niveau_actuel / niveaux_requis)
                progression_validation = progression_min + (ratio_completion * plage_validation)
                
                # Ajustements selon les validations effectives
                validations_completees = self._compter_validations_completees()
                if validations_completees > niveau_actuel:
                    # Bonus si plus de validations que le niveau actuel
                    bonus_validations = min(5, (validations_completees - niveau_actuel) * 2)
                    progression_validation += bonus_validations
                
                return min(progression_max, progression_validation)
            else:
                # Pas de niveaux définis, progression minimale
                return progression_min
        
        except Exception:
            # Fallback basé sur le statut
            if hasattr(self, 'statut'):
                if 'VALIDATION' in self.statut:
                    return 50  # Milieu de la validation
                elif 'DRH' in self.statut:
                    return 65  # Plus avancé
            return 35

    def _compter_validations_completees(self):
        """
        Compte le nombre de validations effectivement complétées
        """
        try:
            # Essayer d'accéder aux validations via la relation
            if hasattr(self, 'validations'):
                return self.validations.filter(
                    date_validation__isnull=False
                ).count()
            else:
                return 0
        except Exception:
            return 0

    def _progression_fallback(self):
        """
        Calcul de progression simplifié en cas d'erreur
        """
        try:
            # Mapping simple et sûr
            fallback_mapping = {
                'BROUILLON': 0,
                'SOUMISE': 20,
                'EN_PROPOSITION': 30,
                'EN_VALIDATION': 50,
                'VALIDATION_DRH_PENDING': 60,
                'CANDIDAT_PROPOSE': 75,
                'CANDIDAT_SELECTIONNE': 75,
                'VALIDEE': 85,
                'EN_COURS': 90,
                'TERMINEE': 100,
                'REFUSEE': 0,
                'ANNULEE': 0,
            }
            
            statut = getattr(self, 'statut', 'BROUILLON')
            return fallback_mapping.get(statut, 0)
            
        except Exception:
            return 0

    @property
    def progression_details(self):
        """
        Détails complets de la progression pour le debug et l'affichage
        Compatible avec les vues workflow
        """
        try:
            details = {
                'statut': getattr(self, 'statut', 'INCONNU'),
                'niveau_actuel': getattr(self, 'niveau_validation_actuel', 0),
                'niveaux_requis': getattr(self, 'niveaux_validation_requis', 3),
                'urgence': getattr(self, 'urgence', 'NORMALE'),
                'progression_pct': self.progression_pct,
                'progression_display': self.progression_display,
            }
            
            # Ajouter les validations si disponibles
            try:
                if hasattr(self, 'validations'):
                    validations_completees = self.validations.filter(
                        date_validation__isnull=False
                    ).count()
                    details['validations_completees'] = validations_completees
                    details['validations_restantes'] = max(0, 
                        (details['niveaux_requis'] or 3) - validations_completees
                    )
            except Exception:
                details['validations_completees'] = 0
                details['validations_restantes'] = details['niveaux_requis'] or 3
            
            # Temps écoulé
            try:
                if hasattr(self, 'created_at') and self.created_at:
                    from django.utils import timezone
                    temps_ecoule = timezone.now() - self.created_at
                    details['jours_ecoules'] = temps_ecoule.days
                    details['heures_ecoulees'] = int(temps_ecoule.total_seconds() / 3600)
            except Exception:
                details['jours_ecoules'] = 0
                details['heures_ecoulees'] = 0
            
            return details
            
        except Exception as e:
            return {
                'statut': getattr(self, 'statut', 'ERREUR'),
                'progression_pct': 0,
                'erreur': str(e)
            }

    @property
    def progression_display(self):
        """
        Affichage formaté de la progression avec barre visuelle
        Compatible avec les templates des vues workflow
        """
        try:
            pct = self.progression_pct
            
            # Créer une barre de progression textuelle
            nb_blocs = 20
            blocs_remplis = int((pct / 100) * nb_blocs)
            blocs_vides = nb_blocs - blocs_remplis
            
            barre = "█" * blocs_remplis + "░" * blocs_vides
            
            # Indicateurs visuels selon le contexte
            indicateur = self._get_indicateur_progression()
            
            return f"{indicateur} │{barre}│ {pct}%"
            
        except Exception:
            return f"Progression: {self.progression_pct}%"

    def _get_indicateur_progression(self):
        """
        Détermine l'indicateur visuel selon l'état de la demande
        """
        try:
            # Vérifier si en retard (compatible avec les vues)
            if self.est_en_retard:
                return "⚠️ EN RETARD"
            
            # Selon l'urgence
            urgence = getattr(self, 'urgence', 'NORMALE')
            if urgence == 'CRITIQUE':
                return "🔥 CRITIQUE"
            elif urgence == 'ELEVEE':
                return "⚡ URGENT"
            
            # Selon le statut
            statut = getattr(self, 'statut', '')
            if statut == 'TERMINEE':
                return "✅ TERMINÉ"
            elif statut in ['REFUSEE', 'ANNULEE']:
                return "❌ FERMÉ"
            elif 'VALIDATION' in statut:
                return "⏳ VALIDATION"
            elif 'CANDIDAT' in statut:
                return "👤 CANDIDAT"
            else:
                return "📋 EN COURS"
                
        except Exception:
            return "📊"

    @property
    def etape_actuelle_description(self):
        """
        Description textuelle de l'étape actuelle
        Compatible avec la fonction _get_etape_validation_actuelle des vues
        """
        try:
            statut = getattr(self, 'statut', '')
            
            if statut == 'BROUILLON':
                return "Demande en cours de rédaction"
            elif statut == 'SOUMISE':
                return "Demande soumise, en attente de traitement"
            elif statut == 'EN_PROPOSITION':
                return "Recherche et proposition de candidats en cours"
            elif statut == 'EN_VALIDATION':
                niveau = getattr(self, 'niveau_validation_actuel', 0)
                niveaux_requis = getattr(self, 'niveaux_validation_requis', 3)
                
                if niveau == 0:
                    return "En attente de validation initiale"
                elif niveau == 1:
                    return f"Validation Responsable (N+1) - {niveau}/{niveaux_requis}"
                elif niveau == 2:
                    return f"Validation Directeur (N+2) - {niveau}/{niveaux_requis}"
                elif niveau >= 3:
                    return f"Validation finale RH/Admin - {niveau}/{niveaux_requis}"
                else:
                    return f"Validation niveau {niveau}/{niveaux_requis}"
            elif statut == 'VALIDATION_DRH_PENDING':
                return "En attente de validation DRH"
            elif statut in ['CANDIDAT_PROPOSE', 'CANDIDAT_SELECTIONNE']:
                return "Candidat sélectionné, notification en cours"
            elif statut == 'VALIDEE':
                return "Demande validée, mission planifiée"
            elif statut == 'EN_COURS':
                return "Mission d'intérim en cours"
            elif statut == 'TERMINEE':
                return "Mission terminée avec succès"
            elif statut == 'REFUSEE':
                return "Demande refusée"
            elif statut == 'ANNULEE':
                return "Demande annulée"
            else:
                return f"Étape: {statut}"
                
        except Exception:
            return f"Étape: {getattr(self, 'statut', 'INCONNUE')}"

    @property
    def est_en_retard(self):
        """
        Détermine si la demande est en retard selon les SLA
        Compatible avec la logique des vues de monitoring
        """
        try:
            from django.utils import timezone
            from datetime import timedelta
            
            # Exclure les demandes finies
            statut = getattr(self, 'statut', '')
            if statut in ['TERMINEE', 'REFUSEE', 'ANNULEE']:
                return False
            
            # SLA selon l'urgence (en heures)
            urgence = getattr(self, 'urgence', 'NORMALE')
            sla_mapping = {
                'CRITIQUE': 4,    # 4 heures
                'ELEVEE': 24,     # 1 jour
                'MOYENNE': 72,    # 3 jours
                'NORMALE': 168,   # 1 semaine
            }
            
            sla_heures = sla_mapping.get(urgence, 168)
            
            # Calculer le temps écoulé
            if hasattr(self, 'created_at') and self.created_at:
                temps_ecoule = timezone.now() - self.created_at
                heures_ecoulees = temps_ecoule.total_seconds() / 3600
                return heures_ecoulees > sla_heures
            
            return False
            
        except Exception:
            return False

    @property
    def prochaine_etape(self):
        """
        Détermine la prochaine étape du workflow
        Compatible avec _get_prochaine_etape des vues
        """
        try:
            statut = getattr(self, 'statut', '')
            
            if statut == 'BROUILLON':
                return "Soumission de la demande"
            elif statut == 'SOUMISE':
                return "Validation N+1 (Responsable)"
            elif statut == 'EN_PROPOSITION':
                return "Évaluation des candidats"
            elif statut == 'EN_VALIDATION':
                niveau_actuel = getattr(self, 'niveau_validation_actuel', 0)
                niveaux_requis = getattr(self, 'niveaux_validation_requis', 3)
                
                if niveau_actuel < niveaux_requis:
                    prochaine_niveau = niveau_actuel + 1
                    if prochaine_niveau == 1:
                        return "Validation Responsable (N+1)"
                    elif prochaine_niveau == 2:
                        return "Validation Directeur (N+2)"
                    elif prochaine_niveau >= 3:
                        return "Validation finale RH/Admin"
                    else:
                        return f"Validation niveau {prochaine_niveau}"
                else:
                    return "Sélection finale candidat"
            elif statut == 'VALIDATION_DRH_PENDING':
                return "Validation DRH"
            elif statut in ['CANDIDAT_PROPOSE', 'CANDIDAT_SELECTIONNE']:
                return "Réponse candidat"
            elif statut == 'VALIDEE':
                return "Début de mission"
            elif statut == 'EN_COURS':
                return "Fin de mission"
            else:
                return "Workflow terminé"
                
        except Exception:
            return "Étape suivante indéterminée"

    # ================================================================
    # MÉTHODES UTILITAIRES POUR COMPATIBILITÉ AVEC LES VUES
    # ================================================================

    def get_workflow_status_for_api(self):
        """
        Retourne le statut workflow formaté pour l'API
        Compatible avec api_workflow_status dans les vues
        """
        try:
            return {
                'statut_demande': getattr(self, 'statut', ''),
                'niveau_validation_actuel': getattr(self, 'niveau_validation_actuel', 0),
                'niveaux_requis': getattr(self, 'niveaux_validation_requis', 3),
                'progression_pct': self.progression_pct,
                'etape_actuelle': self.etape_actuelle_description,
                'prochaine_etape': self.prochaine_etape,
                'candidat_selectionne': getattr(self.candidat_selectionne, 'nom_complet', None) if hasattr(self, 'candidat_selectionne') and self.candidat_selectionne else None,
                'est_en_retard': self.est_en_retard,
                'urgence': getattr(self, 'urgence', 'NORMALE'),
                'derniere_modification': self.updated_at.isoformat() if hasattr(self, 'updated_at') and self.updated_at else None
            }
        except Exception as e:
            return {
                'erreur': str(e),
                'progression_pct': 0
            }

    def __str__(self):
        return f"{self.numero_demande} - {self.poste.titre if self.poste else 'Poste non defini'}"
    
    class Meta:
        verbose_name = "Demande d'interim"
        verbose_name_plural = "Demandes d'interim"
        ordering = ['-created_at']

# ================================================================
# MODELES PROPOSITIONS CANDIDATS
# ================================================================

class PropositionCandidat(TimestampedModel):
    """Propositions de candidats par les utilisateurs"""
    
    SOURCES_PROPOSITION = [
        ('DEMANDEUR_INITIAL', 'Demandeur initial'),
        ('MANAGER_DIRECT', 'Manager direct'),
        ('CHEF_EQUIPE', 'Chef d\'equipe'),
        ('RESPONSABLE', 'Responsable (N+1)'),
        ('DIRECTEUR', 'Directeur (N+2)'),
        ('RH', 'RH (Final)'),
        ('ADMIN', 'Admin (Final)'),
        ('SUPERUSER', 'Superutilisateur'),
        ('VALIDATION_ETAPE', 'Ajout lors de validation'),
        ('SYSTEME', 'Systeme automatique'),
        ('AUTRE', 'Autre'),
    ]
    
    STATUTS_PROPOSITION = [
        ('SOUMISE', 'Soumise'),
        ('EN_EVALUATION', 'En evaluation'),
        ('EVALUEE', 'Evaluee'),
        ('RETENUE', 'Retenue pour validation'),
        ('REJETEE', 'Rejetee'),
        ('VALIDEE', 'Validee'),
    ]
    
    # Identifiants
    numero_proposition = models.CharField(max_length=20, unique=True, editable=False)
    
    # Relations principales
    demande_interim = models.ForeignKey(
        DemandeInterim,
        on_delete=models.CASCADE,
        related_name='propositions_candidats'
    )
    candidat_propose = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='propositions_recues'
    )
    proposant = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='propositions_soumises'
    )
    
    # Metadonnees de la proposition
    source_proposition = models.CharField(max_length=20, choices=SOURCES_PROPOSITION)
    statut = models.CharField(max_length=15, choices=STATUTS_PROPOSITION, default='SOUMISE')
    niveau_validation_propose = models.IntegerField(
        default=1,
        help_text="Niveau de validation ou la proposition a ete faite"
    )
    
    # Justification obligatoire
    justification = models.TextField(
        help_text="Justification obligatoire de la proposition"
    )
    competences_specifiques = models.TextField(
        blank=True,
        help_text="Competences specifiques du candidat pour ce poste"
    )
    experience_pertinente = models.TextField(
        blank=True,
        help_text="Experience pertinente du candidat"
    )
    
    # OK AJOUT : Champs de scoring manquants
    score_automatique = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    score_humain_ajuste = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Score ajuste par un validateur humain"
    )
    bonus_proposition_humaine = models.IntegerField(
        default=5,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Bonus accorde selon le niveau hierarchique"
    )
    
    # OK AJOUT : Champ score_final manquant (requis par le template)
    score_final = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Score final calcule (base + bonus)"
    )
    
    # Evaluation par les validateurs
    evaluateur = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='propositions_evaluees'
    )
    commentaire_evaluation = models.TextField(blank=True)
    date_evaluation = models.DateTimeField(null=True, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.numero_proposition:
            self.numero_proposition = f"PROP-{timezone.now().year}-{str(uuid.uuid4())[:8].upper()}"
        
        # OK CALCUL AUTOMATIQUE du score_final
        self.calculer_score_final()
        
        super().save(*args, **kwargs)
    
    def calculer_score_final(self):
        """Calcule automatiquement le score final"""
        score_base = self.score_humain_ajuste or self.score_automatique or 0
        self.score_final = min(100, score_base + self.bonus_proposition_humaine)
        return self.score_final
    
    def __str__(self):
        return f"{self.numero_proposition} - {self.candidat_propose.nom_complet} propose par {self.proposant.nom_complet}"
    
    @property
    def source_display(self):
        """Affichage avec icones selon la hierarchie CORRIGEE"""
        sources = {
            'DEMANDEUR_INITIAL': '>>> Demandeur initial',
            'MANAGER_DIRECT': '>>> Manager direct',
            'CHEF_EQUIPE': '>>> Chef d\'equipe',
            'RESPONSABLE': '>>> Responsable (N+1)',
            'DIRECTEUR': '>>> Directeur (N+2)',  
            'RH': '>>> RH (Final)',
            'ADMIN': '>>> Admin (Final)',
            'SUPERUSER': '>>> Superutilisateur',
            'VALIDATION_ETAPE': '>>> Validation',
            'SYSTEME': '>>> Systeme',
            'AUTRE': '>>> Autre'
        }
        return sources.get(self.source_proposition, '>>> Non defini')
    
    def evaluer_candidat(self, evaluateur, score_ajuste=None, commentaire=""):
        """Evalue la proposition de candidat"""
        self.evaluateur = evaluateur
        self.score_humain_ajuste = score_ajuste
        self.commentaire_evaluation = commentaire
        self.date_evaluation = timezone.now()
        self.statut = 'EVALUEE'
        self.calculer_score_final()  # Recalculer apres modification
        self.save()
    
    def retenir_pour_validation(self):
        """Marque la proposition comme retenue pour validation"""
        self.statut = 'RETENUE'
        self.save()
    
    class Meta:
        verbose_name = "Proposition de candidat"
        verbose_name_plural = "Propositions de candidats"
        ordering = ['-score_final', '-created_at']  # Trier par score en premier
        unique_together = ['demande_interim', 'candidat_propose', 'proposant']
        
class ScoreDetailCandidat(TimestampedModel):
    """Details du scoring pour un candidat avec bonus hierarchiques"""
    
    candidat = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='scores_details'
    )
    demande_interim = models.ForeignKey(
        DemandeInterim,
        on_delete=models.CASCADE,
        related_name='scores_candidats'
    )
    proposition_humaine = models.ForeignKey(
        PropositionCandidat,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='score_candidat',
        help_text="Reference si c'est une proposition humaine"
    )
    
    # Scores detailles (0-100 chacun)
    score_similarite_poste = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    score_competences = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    score_disponibilite = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    score_proximite = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    score_anciennete = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    score_experience = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Bonus et penalites avec hierarchie corrigee
    bonus_proposition_humaine = models.IntegerField(default=0)
    bonus_experience_similaire = models.IntegerField(default=0)
    bonus_recommandation = models.IntegerField(default=0)
    bonus_hierarchique = models.IntegerField(
        default=0,
        help_text="Bonus selon le niveau hierarchique du proposant"
    )
    penalite_indisponibilite = models.IntegerField(default=0)
    
    # Score final
    score_total = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Metadonnees
    calcule_par = models.CharField(
        max_length=20, 
        choices=[('AUTOMATIQUE', 'Automatique'), ('HUMAIN', 'Humain')],
        default='AUTOMATIQUE'
    )
    
    def calculer_score_total(self):
        """Calcule le score total avec ponderation et bonus/penalites CORRIGES"""
        # Ponderation des criteres
        score_base = (
            self.score_similarite_poste * 0.25 +
            self.score_competences * 0.25 +
            self.score_experience * 0.20 +
            self.score_disponibilite * 0.15 +
            self.score_proximite * 0.10 +
            self.score_anciennete * 0.05
        )
        
        # Ajout des bonus et penalites avec hierarchie
        score_avec_bonus = (
            score_base + 
            self.bonus_proposition_humaine +
            self.bonus_experience_similaire +
            self.bonus_recommandation +
            self.bonus_hierarchique -
            self.penalite_indisponibilite
        )
        
        self.score_total = max(0, min(100, int(score_avec_bonus)))
        return self.score_total
    
    @property
    def est_proposition_humaine(self):
        """Verifie si c'est une proposition humaine"""
        return self.proposition_humaine is not None
    
    @property
    def proposant_display(self):
        """Affiche qui a propose le candidat"""
        if self.proposition_humaine:
            return f"Propose par {self.proposition_humaine.proposant.nom_complet}"
        return "Selection automatique"
    
    class Meta:
        verbose_name = "Score detaille candidat"
        verbose_name_plural = "Scores detailles candidats"
        unique_together = ['candidat', 'demande_interim']
        ordering = ['-score_total']

# ================================================================
# MODELES VALIDATION
# ================================================================

class ValidationDemande(TimestampedModel):
    """Validations dans le workflow d'interim avec hierarchie CORRIGEE"""
    
    TYPES_VALIDATION = [
        ('RESPONSABLE', 'Validation Responsable (N+1)'),
        ('DIRECTEUR', 'Validation Directeur (N+2)'),
        ('RH', 'Validation RH (Final)'),
        ('ADMIN', 'Validation Admin (Final)'),
        ('SUPERUSER', 'Validation Superutilisateur'),
        ('URGENCE', 'Validation d\'urgence'),
    ]
    
    DECISIONS = [
        ('APPROUVE', 'Approuve'),
        ('APPROUVE_AVEC_MODIF', 'Approuve avec modifications'),
        ('REFUSE', 'Refuse'),
        ('REPORTE', 'Reporte'),
        ('CANDIDAT_AJOUTE', 'Candidat ajoute'),
    ]
    
    demande = models.ForeignKey(
        DemandeInterim,
        on_delete=models.CASCADE,
        related_name='validations'
    )
    
    type_validation = models.CharField(max_length=20, choices=TYPES_VALIDATION)
    niveau_validation = models.IntegerField(default=1)
    validateur = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='validations_effectuees'
    )
    
    decision = models.CharField(max_length=25, choices=DECISIONS)
    commentaire = models.TextField(blank=True)
    
    date_demande_validation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True)
    
    # Candidats traites lors de cette validation
    candidats_retenus = models.JSONField(
        default=list,
        help_text="Liste des candidats retenus avec leurs scores"
    )
    candidats_rejetes = models.JSONField(
        default=list,
        help_text="Liste des candidats rejetes avec raisons"
    )
    
    # Nouveau candidat propose lors de cette validation
    nouveau_candidat_propose = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='propositions_lors_validation'
    )
    justification_nouveau_candidat = models.TextField(blank=True)
    
    def valider(self, decision, commentaire="", candidats_retenus=None, candidats_rejetes=None):
        """Effectue la validation"""
        self.decision = decision
        self.commentaire = commentaire
        self.date_validation = timezone.now()
        
        if candidats_retenus:
            self.candidats_retenus = candidats_retenus
        if candidats_rejetes:
            self.candidats_rejetes = candidats_rejetes
            
        self.save()
    
    @property
    def en_attente(self):
        """Verifie si la validation est en attente"""
        return self.date_validation is None
    
    @property
    def delai_traitement(self):
        """Calcule le delai de traitement"""
        if self.date_validation:
            return self.date_validation - self.date_demande_validation
        return timezone.now() - self.date_demande_validation
    
    @property
    def decision_display(self):
        """Affichage avec icones"""
        decisions = {
            'APPROUVE': 'OK Approuve',
            'APPROUVE_AVEC_MODIF': 'OK Approuve avec modifications',
            'REFUSE': 'ERROR Refuse',
            'REPORTE': 'WARNING Reporte',
            'CANDIDAT_AJOUTE': '>>> Candidat ajoute',
        }
        return decisions.get(self.decision, '>>> Decision inconnue')
    
    @property
    def type_validation_display(self):
        """Affichage avec icones selon la hierarchie"""
        types = {
            'RESPONSABLE': '>>> Responsable (N+1)',
            'DIRECTEUR': '>>> Directeur (N+2)',
            'RH': '>>> RH (Final)',
            'ADMIN': '>>> Admin (Final)',
            'SUPERUSER': '>>> Superutilisateur',
            'URGENCE': 'WARNING Urgence'
        }
        return types.get(self.type_validation, '>>> Type inconnu')
    
    class Meta:
        ordering = ['-date_demande_validation']
        verbose_name = "Validation de demande"
        verbose_name_plural = "Validations de demandes"
    
    def __str__(self):
        return f"{self.demande.numero_demande} - {self.type_validation_display} par {self.validateur.nom_complet}"

# ================================================================
# MODELES WORKFLOW ET HISTORIQUE
# ================================================================

class WorkflowDemande(TimestampedModel):
    """Workflow specifique a une demande d'interim avec propositions"""
    demande = models.OneToOneField(
        DemandeInterim,
        on_delete=models.CASCADE,
        related_name='workflow'
    )
    
    etape_actuelle = models.ForeignKey(
        WorkflowEtape,
        on_delete=models.CASCADE,
        related_name='workflows_en_cours'
    )
    
    date_derniere_action = models.DateTimeField(auto_now=True)
    
    # Historique des actions avec support des propositions
    historique_actions = models.JSONField(default=list)
    
    # Statistiques du workflow
    nb_propositions_recues = models.IntegerField(default=0)
    nb_candidats_evalues = models.IntegerField(default=0)
    nb_niveaux_validation_passes = models.IntegerField(default=0)
    
    def ajouter_action(self, utilisateur, action, commentaire="", metadata=None):
        """Ajoute une action a l'historique"""
        action_data = {
            'date': timezone.now().isoformat(),
            'utilisateur': {
                'id': utilisateur.id if utilisateur else None,
                'nom': utilisateur.nom_complet if utilisateur else 'Systeme',
                'type_profil': utilisateur.type_profil if utilisateur else 'SYSTEME'
            },
            'action': action,
            'commentaire': commentaire,
            'etape': self.etape_actuelle.nom,
            'metadata': metadata or {}
        }
        self.historique_actions.append(action_data)
        self.save(update_fields=['historique_actions', 'date_derniere_action'])
    
    @property
    def est_en_retard(self):
        """Verifie si l'etape actuelle est en retard"""
        if not self.etape_actuelle.delai_max_heures:
            return False
        
        delai_limite = self.date_derniere_action + timezone.timedelta(
            hours=self.etape_actuelle.delai_max_heures
        )
        return timezone.now() > delai_limite
    
    @property
    def progression_percentage(self):
        """Calcule le pourcentage de progression"""
        etapes_total = WorkflowEtape.objects.filter(actif=True).count()
        if etapes_total == 0:
            return 0
        return min(100, (self.etape_actuelle.ordre / etapes_total) * 100)
    
    class Meta:
        verbose_name = "Workflow de demande"
        verbose_name_plural = "Workflows de demandes"

# ================================================================
# MODELES NOTIFICATIONS
# ================================================================

class NotificationInterim(TimestampedModel):
    """Notifications specifiques au systeme d'interim"""
    TYPES_NOTIFICATION = [
        ('NOUVELLE_DEMANDE', 'Nouvelle demande d\'interim'),
        ('DEMANDE_A_VALIDER', 'Demande a valider'),
        ('PROPOSITION_CANDIDAT', 'Nouvelle proposition de candidat'),
        ('CANDIDAT_PROPOSE_VALIDATION', 'Candidat propose pour validation'),
        ('VALIDATION_EFFECTUEE', 'Validation effectuee'),
        ('CANDIDAT_SELECTIONNE', 'Candidat selectionne'),
        ('CANDIDAT_NOTIFIE', 'Candidat notifie'),
        ('CANDIDAT_ACCEPTE', 'Candidat a accepte'),
        ('CANDIDAT_REFUSE', 'Candidat a refuse'),
        ('MISSION_DEMARREE', 'Mission demarree'),
        ('MISSION_TERMINEE', 'Mission terminee'),
        ('RAPPEL_VALIDATION', 'Rappel de validation'),
        ('RETARD_WORKFLOW', 'Retard dans le workflow'),
    ]
    
    STATUTS = [
        ('NON_LUE', 'Non lue'),
        ('LUE', 'Lue'),
        ('TRAITEE', 'Traitee'),
        ('ARCHIVEE', 'Archivee'),
    ]
    
    URGENCES = [
        ('BASSE', 'Basse'),
        ('NORMALE', 'Normale'),
        ('HAUTE', 'Haute'),
        ('CRITIQUE', 'Critique'),
    ]
    
    destinataire = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='notifications_recues'
    )
    
    expediteur = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications_envoyees'
    )
    
    demande = models.ForeignKey(
        DemandeInterim,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    
    # References optionnelles pour les propositions
    proposition_liee = models.ForeignKey(
        PropositionCandidat,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications'
    )
    validation_liee = models.ForeignKey(
        ValidationDemande,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications'
    )
    
    type_notification = models.CharField(max_length=30, choices=TYPES_NOTIFICATION)
    urgence = models.CharField(max_length=15, choices=URGENCES, default='NORMALE')
    statut = models.CharField(max_length=15, choices=STATUTS, default='NON_LUE')
    statut_lecture = models.CharField(max_length=15, choices=STATUTS, default='NON_LUE')
    
    titre = models.CharField(max_length=200)
    message = models.TextField()
    
    # URLs d'action
    url_action_principale = models.URLField(blank=True)
    url_action_secondaire = models.URLField(blank=True)
    texte_action_principale = models.CharField(max_length=100, blank=True)
    texte_action_secondaire = models.CharField(max_length=100, blank=True)
    
    # Dates
    date_lecture = models.DateTimeField(null=True, blank=True)
    date_traitement = models.DateTimeField(null=True, blank=True)
    date_expiration = models.DateTimeField(null=True, blank=True)
    
    # Suivi des rappels
    nb_rappels_envoyes = models.IntegerField(default=0)
    prochaine_date_rappel = models.DateTimeField(null=True, blank=True)
    
    # Metadonnees pour les propositions avec hierarchie
    metadata = models.JSONField(
        default=dict,
        help_text="Metadonnees supplementaires pour les notifications"
    )
    
    def marquer_comme_lue(self):
        """Marque la notification comme lue"""
        if self.statut_lecture == 'NON_LUE' or self.statut_lecture == '' or self.statut_lecture == None :
            self.statut_lecture = 'LUE'
            self.date_lecture = timezone.now()
            self.save(update_fields=['statut_lecture', 'date_lecture'])
    
    def marquer_comme_traitee(self):
        """Marque la notification comme traitee"""
        self.statut = 'TRAITEE'
        self.date_traitement = timezone.now()
        self.save(update_fields=['statut', 'date_traitement'])
    
    @property
    def est_expiree(self):
        """Verifie si la notification est expiree"""
        if not self.date_expiration:
            return False
        return timezone.now() > self.date_expiration
    
    @property
    def urgence_display(self):
        urgences = {
            'BASSE': '>>> Basse',
            'NORMALE': '>>> Normale', 
            'HAUTE': 'WARNING Haute',
            'CRITIQUE': 'ERROR Critique'
        }
        return urgences.get(self.urgence, '>>> Non definie')
    
    @property
    def type_display(self):
        """Affichage formate du type avec icones"""
        types_display = {
            'NOUVELLE_DEMANDE': '>>> Nouvelle demande',
            'DEMANDE_A_VALIDER': '>>> Demande a valider',
            'PROPOSITION_CANDIDAT': '>>> Proposition candidat',
            'CANDIDAT_PROPOSE_VALIDATION': 'OK Candidat pour validation',
            'VALIDATION_EFFECTUEE': 'OK Validation effectuee',
            'CANDIDAT_SELECTIONNE': '>>> Candidat selectionne',
            'CANDIDAT_NOTIFIE': '>>> Candidat notifie',
            'CANDIDAT_ACCEPTE': 'OK Candidat accepte',
            'CANDIDAT_REFUSE': 'ERROR Candidat refuse',
            'MISSION_DEMARREE': '>>> Mission demarree',
            'MISSION_TERMINEE': '>>> Mission terminee',
            'RAPPEL_VALIDATION': 'WARNING Rappel validation',
            'RETARD_WORKFLOW': 'ERROR Retard workflow',
        }
        return types_display.get(self.type_notification, '>>> Type inconnu')
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Notification interim"
        verbose_name_plural = "Notifications interim"
        indexes = [
            models.Index(fields=['destinataire', 'statut']),
            models.Index(fields=['demande', 'type_notification']),
        ]
    
    def __str__(self):
        return f"{self.titre} - {self.destinataire.nom_complet}"

# ================================================================
# MODELES HISTORIQUE ET AUDIT
# ================================================================

class HistoriqueAction(TimestampedModel):
    """Historique detaille des actions sur les demandes d'interim"""
    
    TYPES_ACTION = [
        ('CREATION_DEMANDE', 'Creation demande'),
        ('MODIFICATION_DEMANDE', 'Modification demande'),
        ('PROPOSITION_CANDIDAT', 'Proposition candidat'),
        ('EVALUATION_CANDIDAT', 'Evaluation candidat'),
        ('VALIDATION_RESPONSABLE', 'Validation Responsable (N+1)'),
        ('VALIDATION_DIRECTEUR', 'Validation Directeur (N+2)'),
        ('VALIDATION_RH', 'Validation RH (Final)'),
        ('VALIDATION_ADMIN', 'Validation Admin (Final)'),
        ('VALIDATION_SUPERUSER', 'Validation Superutilisateur'),
        ('SELECTION_CANDIDAT', 'Selection candidat'),
        ('NOTIFICATION_CANDIDAT', 'Notification candidat'),
        ('REPONSE_CANDIDAT', 'Reponse candidat'),
        ('DEBUT_MISSION', 'Debut mission'),
        ('FIN_MISSION', 'Fin mission'),
        ('ANNULATION', 'Annulation'),
        ('COMMENTAIRE', 'Ajout commentaire'),
    ]
    
    demande = models.ForeignKey(
        DemandeInterim,
        on_delete=models.CASCADE,
        related_name='historique_actions'
    )
    
    # References optionnelles
    proposition = models.ForeignKey(
        PropositionCandidat,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='historique'
    )
    validation = models.ForeignKey(
        ValidationDemande,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='historique'
    )
    
    action = models.CharField(max_length=25, choices=TYPES_ACTION)
    utilisateur = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.SET_NULL,
        null=True,
        related_name='actions_historique'
    )
    
    description = models.TextField()
    donnees_avant = models.JSONField(null=True, blank=True)
    donnees_apres = models.JSONField(null=True, blank=True)
    
    # Metadonnees contextuelles avec hierarchie
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    niveau_validation = models.IntegerField(null=True, blank=True)
    niveau_hierarchique = models.CharField(max_length=20, blank=True)
    is_superuser = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.demande.numero_demande} - {self.get_action_display()} par {self.utilisateur.nom_complet if self.utilisateur else 'Systeme'}"
    
    class Meta:
        verbose_name = "Historique action"
        verbose_name_plural = "Historiques actions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['demande', 'action']),
            models.Index(fields=['utilisateur', 'created_at']),
            models.Index(fields=['niveau_hierarchique', 'is_superuser']),
        ]

# ================================================================
# MODELES REPONSES CANDIDATS
# ================================================================

class ReponseCandidatInterim(TimestampedModel):
    """Reponses des candidats aux propositions d'interim"""
    REPONSES = [
        ('ACCEPTE', 'Accepte'),
        ('REFUSE', 'Refuse'),
        ('EN_ATTENTE', 'En attente de reponse'),
        ('EXPIRE', 'Expire'),
    ]
    
    MOTIFS_REFUS = [
        ('INDISPONIBLE', 'Indisponible'),
        ('COMPETENCES', 'Competences insuffisantes'),
        ('DISTANCE', 'Trop eloigne'),
        ('REMUNERATION', 'Remuneration insuffisante'),
        ('PERSONNEL', 'Raisons personnelles'),
        ('CONFLIT_HORAIRES', 'Conflit d\'horaires'),
        ('AUTRE', 'Autre'),
    ]
    
    demande = models.ForeignKey(
        DemandeInterim,
        on_delete=models.CASCADE,
        related_name='reponses_candidats'
    )
    
    candidat = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='reponses_interim'
    )
    
    reponse = models.CharField(max_length=15, choices=REPONSES, default='EN_ATTENTE')
    
    # Details en cas de refus
    motif_refus = models.CharField(
        max_length=20, 
        choices=MOTIFS_REFUS, 
        null=True, blank=True
    )
    commentaire_refus = models.TextField(blank=True)
    
    # Dates
    date_proposition = models.DateTimeField(auto_now_add=True)
    date_reponse = models.DateTimeField(null=True, blank=True)
    date_limite_reponse = models.DateTimeField()
    
    # Conditions proposees
    salaire_propose = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True
    )
    avantages_proposes = models.TextField(blank=True)
    
    # Rappels envoyes
    nb_rappels_envoyes = models.IntegerField(default=0)
    derniere_date_rappel = models.DateTimeField(null=True, blank=True)
    
    def accepter(self, commentaire=""):
        """Accepte la proposition"""
        self.reponse = 'ACCEPTE'
        self.date_reponse = timezone.now()
        if commentaire:
            self.commentaire_refus = commentaire  # Reutilise pour les commentaires
        self.save()
        
        # Mettre a jour la demande
        self.demande.candidat_selectionne = self.candidat
        self.demande.statut = 'EN_COURS'
        self.demande.save()
    
    def refuser(self, motif, commentaire=""):
        """Refuse la proposition"""
        self.reponse = 'REFUSE'
        self.motif_refus = motif
        self.commentaire_refus = commentaire
        self.date_reponse = timezone.now()
        self.save()
    
    @property
    def est_expire(self):
        """Verifie si la proposition est expiree"""
        return timezone.now() > self.date_limite_reponse and self.reponse == 'EN_ATTENTE'
    
    @property
    def temps_restant(self):
        """Temps restant pour repondre"""
        if self.reponse != 'EN_ATTENTE':
            return None
        
        temps_restant = self.date_limite_reponse - timezone.now()
        return temps_restant if temps_restant.total_seconds() > 0 else None
    
    @property
    def temps_restant_display(self):
        """Affichage du temps restant"""
        temps = self.temps_restant
        if not temps:
            return "Expire" if self.reponse == 'EN_ATTENTE' else "Termine"
        
        jours = temps.days
        heures = temps.seconds // 3600
        
        if jours > 0:
            return f"{jours} jour{'s' if jours > 1 else ''} et {heures}h"
        elif heures > 0:
            return f"{heures}h"
        else:
            minutes = (temps.seconds % 3600) // 60
            return f"{minutes}min"
    
    @property
    def reponse_display(self):
        reponses_display = {
            'ACCEPTE': 'OK Accepte',
            'REFUSE': 'ERROR Refuse',
            'EN_ATTENTE': 'WARNING En attente',
            'EXPIRE': 'WARNING Expire'
        }
        return reponses_display.get(self.reponse, '>>> Statut inconnu')
    
    class Meta:
        unique_together = ['demande', 'candidat']
        ordering = ['-date_proposition']
        verbose_name = "Reponse candidat interim"
        verbose_name_plural = "Reponses candidats interim"
    
    def __str__(self):
        return f"{self.candidat.nom_complet} - {self.demande.numero_demande} ({self.get_reponse_display()})"

# ================================================================
# MODELES COMPLEMENTAIRES (FORMATIONS, ABSENCES, DISPONIBILITES)
# ================================================================

class FormationUtilisateur(TimestampedModel):
    """Formations et diplomes d'un utilisateur"""
    
    utilisateur = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='formations'
    )
    
    kelio_formation_key = models.IntegerField(null=True, blank=True, unique=True)
    
    titre = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    type_formation = models.CharField(max_length=100, blank=True)
    organisme = models.CharField(max_length=200, blank=True)
    
    date_debut = models.DateField(null=True, blank=True)
    date_fin = models.DateField(null=True, blank=True)
    duree_jours = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(365)]
    )
    
    certifiante = models.BooleanField(default=False)
    diplome_obtenu = models.BooleanField(default=True)
    
    source_donnee = models.CharField(
        max_length=10,
        choices=[('LOCAL', 'Locale'), ('KELIO', 'Kelio')],
        default='LOCAL'
    )
    
    def __str__(self):
        return f"{self.utilisateur.nom_complet} - {self.titre}"
    
    class Meta:
        verbose_name = "Formation utilisateur"
        verbose_name_plural = "Formations utilisateurs"
        ordering = ['-date_fin', 'titre']

class AbsenceUtilisateur(TimestampedModel):
    """Absences d'un utilisateur (synchronisees depuis Kelio)"""
    
    utilisateur = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='absences'
    )
    
    kelio_absence_file_key = models.IntegerField(null=True, blank=True, unique=True)
    
    type_absence = models.CharField(max_length=100)
    date_debut = models.DateField()
    date_fin = models.DateField()
    duree_jours = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(365)]
    )
    commentaire = models.TextField(blank=True)
    
    source_donnee = models.CharField(
        max_length=10,
        choices=[('LOCAL', 'Locale'), ('KELIO', 'Kelio')],
        default='KELIO'
    )
    
    def __str__(self):
        return f"{self.utilisateur.nom_complet} - {self.type_absence} ({safe_date_format(self.date_debut)})"
    
    @property
    def est_en_cours(self):
        try:
            return self.date_debut <= date.today() <= self.date_fin
        except (TypeError, AttributeError):
            return False
    
    class Meta:
        verbose_name = "Absence utilisateur"
        verbose_name_plural = "Absences utilisateurs"
        ordering = ['-date_debut']

class DisponibiliteUtilisateur(TimestampedModel):
    """Disponibilites et indisponibilites des utilisateurs"""
    TYPES_DISPONIBILITE = [
        ('DISPONIBLE', 'Disponible'),
        ('INDISPONIBLE', 'Indisponible'),
        ('EN_MISSION', 'En mission'),
        ('CONGE', 'En conge'),
        ('FORMATION', 'En formation'),
        ('AUTRE', 'Autre'),
    ]
    
    utilisateur = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.CASCADE,
        related_name='disponibilites'
    )
    type_disponibilite = models.CharField(max_length=20, choices=TYPES_DISPONIBILITE)
    date_debut = models.DateField()
    date_fin = models.DateField()
    commentaire = models.TextField(blank=True)
    
    created_by = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.SET_NULL,
        null=True,
        related_name='disponibilites_saisies'
    )
    
    def __str__(self):
        debut_str = safe_date_format(self.date_debut)
        fin_str = safe_date_format(self.date_fin)
        return f"{self.utilisateur.nom_complet} - {self.type_disponibilite} ({debut_str} au {fin_str})"
    
    class Meta:
        verbose_name = "Disponibilite utilisateur"
        verbose_name_plural = "Disponibilites utilisateurs"
        ordering = ['-date_debut']

# ================================================================
# UTILITAIRES DE CRYPTAGE
# ================================================================

def get_encryption_key():
    """Recupere la cle de cryptage depuis les settings"""
    try:
        # Utiliser une cle depuis les settings ou generer une cle par defaut
        key = getattr(settings, 'KELIO_ENCRYPTION_KEY', None)
        if not key:
            # Generer une cle par defaut (a securiser en production)
            key = base64.urlsafe_b64encode(b'fallback_key_32_characters_long!')[:32]
        if isinstance(key, str):
            key = key.encode()
        return key
    except Exception:
        # Cle de fallback (a changer en production)
        return base64.urlsafe_b64encode(b'fallback_key_32_characters_long!')[:32]

def encrypt_password(password):
    """Crypte un mot de passe"""
    if not password:
        return ""
    try:
        # Utiliser le hachage Django comme methode de cryptage simple
        return f"[CRYPTE]{make_password(password)}"
    except Exception as e:
        logger.error(f"Erreur cryptage mot de passe: {e}")
        return make_password(password)

def decrypt_password(encrypted_password):
    """Decrypte un mot de passe (simulation)"""
    if not encrypted_password:
        return ""
    try:
        if encrypted_password.startswith('[CRYPTE]'):
            return "[CRYPTE]"  # Ne peut pas etre decrypte avec Django hashers
        return encrypted_password
    except Exception as e:
        logger.error(f"Erreur decryptage mot de passe: {e}")
        return "[CRYPTE]"

# ================================================================
# NOUVEAUX MODELES POUR LA DELEGATION ET L'ESCALADE
# ================================================================

class DelegationTemporaire(models.Model):
    """
    Gestion des delegations temporaires de validations
    """
    STATUTS_DELEGATION = [
        ('ACTIVE', 'Active'),
        ('SUSPENDUE', 'Suspendue'),
        ('TERMINEE', 'Terminee'),
        ('ANNULEE', 'Annulee'),
    ]
    
    TYPES_DELEGATION = [
        ('COMPLETE', 'Delegation complete'),
        ('PARTIELLE', 'Delegation partielle'),
        ('URGENCE_SEULEMENT', 'Urgences seulement'),
        ('DEPARTEMENT_SPECIFIQUE', 'Departement specifique'),
    ]
    
    # Identifiants
    numero_delegation = models.CharField(max_length=20, unique=True, editable=False)
    
    # Parties impliquees
    delegant = models.ForeignKey(
        'ProfilUtilisateur',
        on_delete=models.CASCADE,
        related_name='delegations_donnees',
        help_text="Utilisateur qui delegue ses pouvoirs"
    )
    delegataire = models.ForeignKey(
        'ProfilUtilisateur',
        on_delete=models.CASCADE,
        related_name='delegations_recues',
        help_text="Utilisateur qui recoit la delegation"
    )
    
    # Configuration de la delegation
    type_delegation = models.CharField(max_length=25, choices=TYPES_DELEGATION, default='COMPLETE')
    statut = models.CharField(max_length=15, choices=STATUTS_DELEGATION, default='ACTIVE')
    
    # Periode de delegation
    date_debut = models.DateTimeField()
    date_fin = models.DateTimeField()
    
    # Restrictions et conditions
    niveau_validation_delegue = models.IntegerField(
        null=True, blank=True,
        help_text="Niveau de validation concerne (1=Responsable, 2=Directeur, 3=RH/Admin)"
    )
    departements_concernes = models.ManyToManyField(
        'Departement',
        blank=True,
        help_text="Departements concernes par la delegation"
    )
    urgences_concernees = models.CharField(
        max_length=50,
        blank=True,
        help_text="Types d'urgence concernes (ex: 'ELEVEE,CRITIQUE')"
    )
    montant_max_delegation = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Montant maximum autorise (optionnel)"
    )
    
    # Metadonnees
    raison_delegation = models.TextField(
        help_text="Raison de la delegation (conges, maladie, mission, etc.)"
    )
    instructions_specifiques = models.TextField(
        blank=True,
        help_text="Instructions specifiques pour le delegataire"
    )
    
    # Suivi et historique
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'ProfilUtilisateur',
        on_delete=models.SET_NULL,
        null=True,
        related_name='delegations_creees'
    )
    
    # Statistiques d'utilisation
    nb_validations_effectuees = models.IntegerField(default=0)
    derniere_utilisation = models.DateTimeField(null=True, blank=True)
    
    # Notifications
    notifier_delegant = models.BooleanField(
        default=True,
        help_text="Notifier le delegant des validations effectuees"
    )
    notifier_fin_delegation = models.BooleanField(
        default=True,
        help_text="Notifier la fin de delegation"
    )
    
    def save(self, *args, **kwargs):
        if not self.numero_delegation:
            self.numero_delegation = f"DEL-{timezone.now().year}-{timezone.now().strftime('%m%d%H%M%S')}"
        super().save(*args, **kwargs)
    
    def clean(self):
        """Validation des donnees"""
        super().clean()
        
        # Verifier les dates
        if self.date_debut and self.date_fin:
            if self.date_debut >= self.date_fin:
                raise ValidationError("La date de fin doit etre posterieure a la date de debut")
            
            # Verifier que la delegation n'est pas trop longue (max 1 an)
            if (self.date_fin - self.date_debut).days > 365:
                raise ValidationError("Une delegation ne peut pas depasser 1 an")
        
        # Verifier les niveaux de validation
        if self.delegant == self.delegataire:
            raise ValidationError("On ne peut pas se deleguer a soi-meme")
        
        # Verifier que le delegataire a un niveau suffisant
        if self.niveau_validation_delegue:
            niveau_delegataire = self._get_niveau_validation_profil(self.delegataire)
            if niveau_delegataire < self.niveau_validation_delegue:
                raise ValidationError(
                    f"Le delegataire n'a pas le niveau suffisant pour ce type de validation"
                )
    
    def _get_niveau_validation_profil(self, profil):
        """Retourne le niveau de validation du profil"""
        mapping = {
            'RESPONSABLE': 1,
            'DIRECTEUR': 2,
            'RH': 3,
            'ADMIN': 3
        }
        return mapping.get(profil.type_profil, 0)
    
    @property
    def est_active(self):
        """Verifie si la delegation est active"""
        now = timezone.now()
        return (
            self.statut == 'ACTIVE' and
            self.date_debut <= now <= self.date_fin
        )
    
    @property
    def duree_restante(self):
        """Calcule la duree restante de la delegation"""
        if not self.est_active:
            return timedelta(0)
        
        now = timezone.now()
        return self.date_fin - now
    
    def peut_valider_demande(self, demande):
        """Verifie si cette delegation permet de valider une demande"""
        if not self.est_active:
            return False, "Delegation inactive"
        
        # Verifier le niveau de validation
        if self.niveau_validation_delegue and demande.niveau_validation_actuel + 1 != self.niveau_validation_delegue:
            return False, "Niveau de validation non concerne"
        
        # Verifier le departement
        if self.departements_concernes.exists():
            if demande.poste.departement not in self.departements_concernes.all():
                return False, "Departement non concerne"
        
        # Verifier l'urgence
        if self.urgences_concernees:
            urgences_autorisees = [u.strip() for u in self.urgences_concernees.split(',')]
            if demande.urgence not in urgences_autorisees:
                return False, "Urgence non concernee"
        
        # Verifier le type de delegation
        if self.type_delegation == 'URGENCE_SEULEMENT' and demande.urgence == 'NORMALE':
            return False, "Delegation limitee aux urgences"
        
        return True, "Delegation autorisee"
    
    def incrementer_utilisation(self):
        """Incremente le compteur d'utilisation"""
        self.nb_validations_effectuees += 1
        self.derniere_utilisation = timezone.now()
        self.save(update_fields=['nb_validations_effectuees', 'derniere_utilisation'])
    
    def suspendre(self, raison=""):
        """Suspend la delegation"""
        self.statut = 'SUSPENDUE'
        self.save()
        
        # Logger l'action
        logger.info(f"Delegation {self.numero_delegation} suspendue: {raison}")
    
    def reactiver(self):
        """Reactive la delegation"""
        if self.date_fin > timezone.now():
            self.statut = 'ACTIVE'
            self.save()
            logger.info(f"Delegation {self.numero_delegation} reactivee")
        else:
            raise ValidationError("Impossible de reactiver une delegation expiree")
    
    def terminer(self, raison="Fin normale"):
        """Termine la delegation"""
        self.statut = 'TERMINEE'
        self.save()
        logger.info(f"Delegation {self.numero_delegation} terminee: {raison}")
    
    def __str__(self):
        return f"{self.numero_delegation} - {self.delegant.nom_complet} -> {self.delegataire.nom_complet}"
    
    class Meta:
        verbose_name = "Delegation temporaire"
        verbose_name_plural = "Delegations temporaires"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['delegant', 'statut']),
            models.Index(fields=['delegataire', 'statut']),
            models.Index(fields=['date_debut', 'date_fin']),
        ]

class RegleEscalade(models.Model):
    """
    Regles d'escalade automatique pour les demandes en retard
    """
    TYPES_DECLENCHEUR = [
        ('DELAI_VALIDATION', 'Delai de validation depasse'),
        ('DELAI_REPONSE_CANDIDAT', 'Delai de reponse candidat depasse'),
        ('WORKFLOW_BLOQUE', 'Workflow bloque'),
        ('URGENCE_NON_TRAITEE', 'Urgence non traitee'),
        ('DEMANDE_ABANDONNEE', 'Demande abandonnee'),
    ]
    
    TYPES_ACTION = [
        ('NOTIFICATION_MANAGER', 'Notifier le manager'),
        ('ESCALADE_NIVEAU_SUPERIEUR', 'Escalader au niveau superieur'),
        ('ASSIGNATION_AUTOMATIQUE', 'Assignation automatique'),
        ('NOTIFICATION_RH', 'Notifier les RH'),
        ('NOTIFICATION_ADMIN', 'Notifier les administrateurs'),
        ('SUSPENSION_DEMANDE', 'Suspendre la demande'),
    ]
    
    # Configuration de la regle
    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    active = models.BooleanField(default=True)
    
    # Conditions de declenchement
    type_declencheur = models.CharField(max_length=30, choices=TYPES_DECLENCHEUR)
    delai_declenchement_heures = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(8760)],  # Max 1 an
        help_text="Delai en heures avant declenchement"
    )
    
    # Conditions supplementaires
    urgences_concernees = models.CharField(
        max_length=50,
        blank=True,
        help_text="Types d'urgence concernes (ex: 'ELEVEE,CRITIQUE')"
    )
    departements_concernes = models.ManyToManyField(
        'Departement',
        blank=True,
        help_text="Departements concernes par cette regle"
    )
    niveaux_validation_concernes = models.CharField(
        max_length=20,
        blank=True,
        help_text="Niveaux de validation concernes (ex: '1,2')"
    )
    
    # Actions a executer
    type_action = models.CharField(max_length=30, choices=TYPES_ACTION)
    destinataires_escalade = models.ManyToManyField(
        'ProfilUtilisateur',
        blank=True,
        help_text="Destinataires specifiques pour l'escalade"
    )
    message_escalade_template = models.TextField(
        blank=True,
        help_text="Template du message d'escalade (peut contenir des variables)"
    )
    
    # Configuration avancee
    nb_max_escalades = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Nombre maximum d'escalades pour cette regle"
    )
    delai_entre_escalades_heures = models.IntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(168)],  # Max 1 semaine
        help_text="Delai entre les escalades repetees"
    )
    
    # Metadonnees
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'ProfilUtilisateur',
        on_delete=models.SET_NULL,
        null=True,
        related_name='regles_escalade_creees'
    )
    
    # Statistiques
    nb_declenchements = models.IntegerField(default=0)
    derniere_execution = models.DateTimeField(null=True, blank=True)
    
    def est_applicable_a_demande(self, demande):
        """Verifie si la regle s'applique a une demande"""
        try:
            # Verifier si active
            if not self.active:
                return False
            
            # Verifier l'urgence
            if self.urgences_concernees:
                urgences_autorisees = [u.strip() for u in self.urgences_concernees.split(',')]
                if demande.urgence not in urgences_autorisees:
                    return False
            
            # Verifier le departement
            if self.departements_concernes.exists():
                if demande.poste.departement not in self.departements_concernes.all():
                    return False
            
            # Verifier le niveau de validation
            if self.niveaux_validation_concernes:
                niveaux_autorises = [int(n.strip()) for n in self.niveaux_validation_concernes.split(',')]
                if demande.niveau_validation_actuel not in niveaux_autorises:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur verification applicabilite regle {self.nom}: {e}")
            return False
    
    def doit_etre_declenchee(self, demande):
        """Verifie si la regle doit etre declenchee pour une demande"""
        try:
            if not self.est_applicable_a_demande(demande):
                return False
            
            now = timezone.now()
            
            if self.type_declencheur == 'DELAI_VALIDATION':
                # Verifier le delai depuis la derniere action de validation
                derniere_validation = demande.validations.order_by('-created_at').first()
                if derniere_validation:
                    delai_ecoule = now - derniere_validation.created_at
                else:
                    delai_ecoule = now - demande.created_at
                
                return delai_ecoule.total_seconds() > (self.delai_declenchement_heures * 3600)
            
            elif self.type_declencheur == 'DELAI_REPONSE_CANDIDAT':
                # Verifier les reponses candidats en retard
                reponses_retard = demande.reponses_candidats.filter(
                    reponse='EN_ATTENTE',
                    date_limite_reponse__lt=now - timedelta(hours=self.delai_declenchement_heures)
                )
                return reponses_retard.exists()
            
            elif self.type_declencheur == 'WORKFLOW_BLOQUE':
                # Verifier si le workflow est bloque
                if hasattr(demande, 'workflow'):
                    delai_ecoule = now - demande.workflow.date_derniere_action
                    return delai_ecoule.total_seconds() > (self.delai_declenchement_heures * 3600)
            
            elif self.type_declencheur == 'URGENCE_NON_TRAITEE':
                # Verifier les urgences non traitees
                if demande.urgence in ['ELEVEE', 'CRITIQUE']:
                    delai_ecoule = now - demande.created_at
                    return delai_ecoule.total_seconds() > (self.delai_declenchement_heures * 3600)
            
            return False
            
        except Exception as e:
            logger.error(f"Erreur verification declenchement regle {self.nom}: {e}")
            return False
    
    def incrementer_utilisation(self):
        """Incremente le compteur d'utilisation"""
        self.nb_declenchements += 1
        self.derniere_execution = timezone.now()
        self.save(update_fields=['nb_declenchements', 'derniere_execution'])
    
    def __str__(self):
        return f"{self.nom} ({self.get_type_declencheur_display()})"
    
    class Meta:
        verbose_name = "Regle d'escalade"
        verbose_name_plural = "Regles d'escalade"
        ordering = ['nom']

class HistoriqueEscalade(models.Model):
    """
    Historique des escalades executees
    """
    STATUTS_EXECUTION = [
        ('REUSSIE', 'Reussie'),
        ('ECHEC', 'Echec'),
        ('PARTIELLE', 'Partielle'),
        ('ANNULEE', 'Annulee'),
    ]
    
    # References
    regle_escalade = models.ForeignKey(
        RegleEscalade,
        on_delete=models.CASCADE,
        related_name='historique_executions'
    )
    demande = models.ForeignKey(
        'DemandeInterim',
        on_delete=models.CASCADE,
        related_name='escalades_historique'
    )
    
    # Details de l'execution
    date_execution = models.DateTimeField(auto_now_add=True)
    statut_execution = models.CharField(max_length=15, choices=STATUTS_EXECUTION)
    
    # Destinataires effectifs
    destinataires_notifies = models.JSONField(
        default=list,
        help_text="Liste des destinataires effectivement notifies"
    )
    
    # Resultats
    actions_executees = models.JSONField(
        default=list,
        help_text="Actions effectivement executees"
    )
    erreurs_rencontrees = models.JSONField(
        default=list,
        help_text="Erreurs rencontrees pendant l'execution"
    )
    
    # Contexte
    contexte_execution = models.JSONField(
        default=dict,
        help_text="Contexte au moment de l'execution"
    )
    message_envoye = models.TextField(blank=True)
    
    # Suivi
    notification_creee = models.ForeignKey(
        'NotificationInterim',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='escalade_origine'
    )
    
    def __str__(self):
        return f"Escalade {self.regle_escalade.nom} - {self.demande.numero_demande} ({self.date_execution})"
    
    class Meta:
        verbose_name = "Historique escalade"
        verbose_name_plural = "Historiques escalades"
        ordering = ['-date_execution']

# ================================================================
# SIGNAUX POUR LA GESTION AUTOMATIQUE
# ================================================================

@receiver(post_save, sender=User)
def sync_user_to_profil(sender, instance, **kwargs):
    """Synchronise les modifications User vers ProfilUtilisateur"""
    try:
        # Chercher le profil associe
        profil = ProfilUtilisateur.objects.filter(user=instance).first()
        if profil:
            # Synchroniser les donnees si necessaire
            pass
    except Exception as e:
        logger.error(f"Erreur synchronisation User->ProfilUtilisateur: {e}")

@receiver(post_save, sender=PropositionCandidat)
def traiter_nouvelle_proposition(sender, instance, created, **kwargs):
    """Traite les nouvelles propositions de candidats avec hierarchie"""
    if created:
        # Creer l'historique avec informations hierarchiques
        HistoriqueAction.objects.create(
            demande=instance.demande_interim,
            proposition=instance,
            action='PROPOSITION_CANDIDAT',
            utilisateur=instance.proposant,
            description=f"Nouvelle proposition de {instance.candidat_propose.nom_complet} par {instance.proposant.nom_complet}",
            niveau_hierarchique=instance.proposant.type_profil,
            is_superuser=instance.proposant.is_superuser,
            donnees_apres={
                'candidat_id': instance.candidat_propose.id,
                'candidat_nom': instance.candidat_propose.nom_complet,
                'justification': instance.justification,
                'source': instance.source_proposition,
                'niveau_hierarchique': instance.proposant.type_profil,
                'is_superuser': instance.proposant.is_superuser
            }
        )

@receiver(post_save, sender=ValidationDemande)
def traiter_validation(sender, instance, created, **kwargs):
    """Traite les validations avec hierarchie corrigee"""
    if created:
        # Determiner le type d'action selon la hierarchie
        action_map = {
            'RESPONSABLE': 'VALIDATION_RESPONSABLE',
            'DIRECTEUR': 'VALIDATION_DIRECTEUR',
            'RH': 'VALIDATION_RH',
            'ADMIN': 'VALIDATION_ADMIN',
            'SUPERUSER': 'VALIDATION_SUPERUSER'
        }
        
        action = action_map.get(instance.type_validation, 'VALIDATION_RESPONSABLE')
        
        # Creer l'historique avec informations hierarchiques
        HistoriqueAction.objects.create(
            demande=instance.demande,
            validation=instance,
            action=action,
            utilisateur=instance.validateur,
            description=f"Validation {instance.type_validation_display} : {instance.decision_display}",
            niveau_validation=instance.niveau_validation,
            niveau_hierarchique=instance.validateur.type_profil,
            is_superuser=instance.validateur.is_superuser,
            donnees_apres={
                'decision': instance.decision,
                'commentaire': instance.commentaire,
                'candidats_retenus': instance.candidats_retenus,
                'candidats_rejetes': instance.candidats_rejetes,
                'type_validation': instance.type_validation,
                'niveau_hierarchique': instance.validateur.type_profil,
                'is_superuser': instance.validateur.is_superuser
            }
        )

@receiver(post_save, sender=ReponseCandidatInterim)
def traiter_reponse_candidat(sender, instance, **kwargs):
    """Traite les reponses des candidats"""
    if instance.reponse in ['ACCEPTE', 'REFUSE'] and instance.date_reponse:
        # Creer l'historique
        HistoriqueAction.objects.create(
            demande=instance.demande,
            action='REPONSE_CANDIDAT',
            utilisateur=instance.candidat,
            description=f"Candidat {instance.candidat.nom_complet} a {instance.reponse_display.lower()} la proposition",
            niveau_hierarchique=instance.candidat.type_profil,
            is_superuser=instance.candidat.is_superuser,
            donnees_apres={
                'reponse': instance.reponse,
                'motif_refus': instance.motif_refus,
                'commentaire': instance.commentaire_refus
            }
        )

# ================================================================
# UTILITAIRES POUR CREER DES UTILISATEURS COMPLETS
# ================================================================

def create_user_with_profil(username, email, first_name, last_name, password, 
                           matricule, type_profil='UTILISATEUR', **profil_kwargs):
    """Utilitaire pour creer un User et son ProfilUtilisateur associe"""
    try:
        with transaction.atomic():
            # Creer l'utilisateur Django
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password
            )
            
            # Creer le profil associe
            profil = ProfilUtilisateur.objects.create(
                user=user,
                matricule=matricule,
                type_profil=type_profil,
                **profil_kwargs
            )
            
            return user, profil
    except Exception as e:
        logger.error(f"Erreur creation User/ProfilUtilisateur: {e}")
        raise

def update_user_password_everywhere(user_or_profil, new_password):
    """Met a jour le mot de passe partout ou c'est necessaire"""
    try:
        if isinstance(user_or_profil, User):
            user = user_or_profil
            profil = getattr(user, 'profilutilisateur', None)
        else:
            profil = user_or_profil
            user = profil.user
        
        if user:
            user.set_password(new_password)
            user.save()
            
        return True
    except Exception as e:
        logger.error(f"Erreur mise a jour mot de passe global: {e}")
        return False

#-------------------------------------------------------------------
# GESTION DES JOURS FERIES
#-------------------------------------------------------------------

from dateutil.easter import easter

# Import conditionnel pour le calendrier Hijri
try:
    from hijridate import Hijri
    HIJRI_DISPONIBLE = True
except ImportError:
    HIJRI_DISPONIBLE = False


# ============================================================================
# ÉNUMÉRATIONS
# ============================================================================

class TypeJourFerie(models.TextChoices):
    """Types de jours fériés"""
    FERIE_CHRETIEN = 'FERIE_CHRETIEN', 'Férié chrétien'
    FERIE_MUSULMAN = 'FERIE_MUSULMAN', 'Férié musulman'
    FERIE_CIVIL = 'FERIE_CIVIL', 'Férié civil'
    FERIE_INTERNE = 'FERIE_INTERNE', 'Férié interne'
    FERIE_AUTRE = 'FERIE_AUTRE', 'Autre'


class MethodeCalcul(models.TextChoices):
    """Méthode de calcul de la date"""
    FIXE = 'FIXE', 'Date fixe'
    PAQUES = 'PAQUES', 'Basé sur Pâques'
    HIJRI = 'HIJRI', 'Calendrier Hijri'
    MANUEL = 'MANUEL', 'Manuel'


class StatutJourFerie(models.TextChoices):
    """Statut du jour férié"""
    ACTIF = 'ACTIF', 'Actif'
    INACTIF = 'INACTIF', 'Inactif'
    EN_ATTENTE = 'EN_ATTENTE', 'En attente'


# ============================================================================
# CONFIGURATION DES JOURS FÉRIÉS - CÔTE D'IVOIRE
# ============================================================================

MODELES_JOURS_FERIES_CI = [
    # Fériés civils (dates fixes)
    {
        'code': 'nouvel_an',
        'nom': "Jour de l'An",
        'type_ferie': TypeJourFerie.FERIE_CIVIL,
        'methode_calcul': MethodeCalcul.FIXE,
        'mois_fixe': 1, 'jour_fixe': 1,
        'est_modifiable': False,
    },
    {
        'code': 'fete_travail',
        'nom': "Fête du Travail",
        'type_ferie': TypeJourFerie.FERIE_CIVIL,
        'methode_calcul': MethodeCalcul.FIXE,
        'mois_fixe': 5, 'jour_fixe': 1,
        'est_modifiable': False,
    },
    {
        'code': 'fete_nationale',
        'nom': "Fête Nationale (Indépendance)",
        'type_ferie': TypeJourFerie.FERIE_CIVIL,
        'methode_calcul': MethodeCalcul.FIXE,
        'mois_fixe': 8, 'jour_fixe': 7,
        'est_modifiable': False,
    },
    {
        'code': 'journee_paix',
        'nom': "Journée Nationale de la Paix",
        'type_ferie': TypeJourFerie.FERIE_CIVIL,
        'methode_calcul': MethodeCalcul.FIXE,
        'mois_fixe': 11, 'jour_fixe': 15,
        'est_modifiable': False,
    },
    # Fériés chrétiens (dates fixes)
    {
        'code': 'assomption',
        'nom': "Assomption",
        'type_ferie': TypeJourFerie.FERIE_CHRETIEN,
        'methode_calcul': MethodeCalcul.FIXE,
        'mois_fixe': 8, 'jour_fixe': 15,
        'est_modifiable': False,
    },
    {
        'code': 'toussaint',
        'nom': "Toussaint",
        'type_ferie': TypeJourFerie.FERIE_CHRETIEN,
        'methode_calcul': MethodeCalcul.FIXE,
        'mois_fixe': 11, 'jour_fixe': 1,
        'est_modifiable': False,
    },
    {
        'code': 'noel',
        'nom': "Noël",
        'type_ferie': TypeJourFerie.FERIE_CHRETIEN,
        'methode_calcul': MethodeCalcul.FIXE,
        'mois_fixe': 12, 'jour_fixe': 25,
        'est_modifiable': False,
    },
    # Fériés chrétiens (basés sur Pâques)
    {
        'code': 'lundi_paques',
        'nom': "Lundi de Pâques",
        'type_ferie': TypeJourFerie.FERIE_CHRETIEN,
        'methode_calcul': MethodeCalcul.PAQUES,
        'decalage_paques': 1,
        'est_modifiable': False,
    },
    {
        'code': 'ascension',
        'nom': "Ascension",
        'type_ferie': TypeJourFerie.FERIE_CHRETIEN,
        'methode_calcul': MethodeCalcul.PAQUES,
        'decalage_paques': 39,
        'est_modifiable': False,
    },
    {
        'code': 'lundi_pentecote',
        'nom': "Lundi de Pentecôte",
        'type_ferie': TypeJourFerie.FERIE_CHRETIEN,
        'methode_calcul': MethodeCalcul.PAQUES,
        'decalage_paques': 50,
        'est_modifiable': False,
    },
    # Fériés musulmans (calendrier Hijri)
    {
        'code': 'aid_fitr',
        'nom': "Aïd el-Fitr (Fin du Ramadan)",
        'type_ferie': TypeJourFerie.FERIE_MUSULMAN,
        'methode_calcul': MethodeCalcul.HIJRI,
        'mois_hijri': 10, 'jour_hijri': 1,
        'est_modifiable': True,
    },
    {
        'code': 'tabaski',
        'nom': "Aïd el-Adha (Tabaski)",
        'type_ferie': TypeJourFerie.FERIE_MUSULMAN,
        'methode_calcul': MethodeCalcul.HIJRI,
        'mois_hijri': 12, 'jour_hijri': 10,
        'est_modifiable': True,
    },
    {
        'code': 'nuit_destin',
        'nom': "Lendemain de la Nuit du Destin",
        'type_ferie': TypeJourFerie.FERIE_MUSULMAN,
        'methode_calcul': MethodeCalcul.HIJRI,
        'mois_hijri': 9, 'jour_hijri': 28,
        'est_modifiable': True,
    },
    {
        'code': 'maouloud',
        'nom': "Lendemain du Maouloud",
        'type_ferie': TypeJourFerie.FERIE_MUSULMAN,
        'methode_calcul': MethodeCalcul.HIJRI,
        'mois_hijri': 3, 'jour_hijri': 13,
        'est_modifiable': True,
    },
]


# ============================================================================
# MANAGER: ModeleJourFerieManager
# ============================================================================

class ModeleJourFerieManager(models.Manager):
    """Manager pour les modèles de jours fériés"""
    
    def actifs(self, code_pays: str = 'CI'):
        """Retourne les modèles actifs pour un pays"""
        return self.filter(est_actif=True, code_pays=code_pays)
    
    def par_type(self, type_ferie: str, code_pays: str = 'CI'):
        """Retourne les modèles d'un type donné"""
        return self.actifs(code_pays).filter(type_ferie=type_ferie)
    
    @transaction.atomic
    def charger_donnees_initiales(self, code_pays: str = 'CI') -> Dict:
        """
        Charge les données initiales des modèles de jours fériés
        
        Returns:
            Dictionnaire avec 'crees', 'existants', 'erreurs'
        """
        resultats = {'crees': [], 'existants': [], 'erreurs': []}
        
        for config in MODELES_JOURS_FERIES_CI:
            try:
                modele, created = self.get_or_create(
                    code=config['code'],
                    defaults={
                        'nom': config['nom'],
                        'type_ferie': config['type_ferie'],
                        'methode_calcul': config['methode_calcul'],
                        'mois_fixe': config.get('mois_fixe'),
                        'jour_fixe': config.get('jour_fixe'),
                        'decalage_paques': config.get('decalage_paques'),
                        'mois_hijri': config.get('mois_hijri'),
                        'jour_hijri': config.get('jour_hijri'),
                        'est_modifiable': config.get('est_modifiable', False),
                        'est_systeme': True,
                        'est_actif': True,
                        'code_pays': code_pays,
                    }
                )
                if created:
                    resultats['crees'].append(modele)
                else:
                    resultats['existants'].append(modele)
            except Exception as e:
                resultats['erreurs'].append({'code': config['code'], 'erreur': str(e)})
        
        return resultats


# ============================================================================
# MODÈLE: ModeleJourFerie
# ============================================================================

class ModeleJourFerie(models.Model):
    """
    Modèles/Templates de jours fériés
    Définit les jours fériés de base avec leur méthode de calcul
    """
    
    class Meta:
        db_table = 'modeles_jours_feries'
        verbose_name = 'Modèle de jour férié'
        verbose_name_plural = 'Modèles de jours fériés'
        ordering = ['mois_fixe', 'jour_fixe', 'nom']
    
    objects = ModeleJourFerieManager()
    
    code = models.CharField(
        max_length=50, 
        unique=True,
        verbose_name="Code",
        help_text="Code unique (ex: nouvel_an, tabaski)"
    )
    
    nom = models.CharField(max_length=150, verbose_name="Nom")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    
    type_ferie = models.CharField(
        max_length=20,
        choices=TypeJourFerie.choices,
        default=TypeJourFerie.FERIE_CIVIL,
        verbose_name="Type de férié"
    )
    
    methode_calcul = models.CharField(
        max_length=20,
        choices=MethodeCalcul.choices,
        default=MethodeCalcul.FIXE,
        verbose_name="Méthode de calcul"
    )
    
    # Date fixe
    mois_fixe = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        verbose_name="Mois (date fixe)"
    )
    jour_fixe = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        verbose_name="Jour (date fixe)"
    )
    
    # Pâques
    decalage_paques = models.SmallIntegerField(
        null=True, blank=True,
        verbose_name="Décalage Pâques (jours)"
    )
    
    # Hijri
    mois_hijri = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        verbose_name="Mois Hijri"
    )
    jour_hijri = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(30)],
        verbose_name="Jour Hijri"
    )
    
    # Configuration
    est_national = models.BooleanField(default=True, verbose_name="Férié national")
    est_paye = models.BooleanField(default=True, verbose_name="Jour chômé payé")
    est_modifiable = models.BooleanField(default=False, verbose_name="Date modifiable")
    est_systeme = models.BooleanField(default=False, verbose_name="Modèle système")
    est_actif = models.BooleanField(default=True, verbose_name="Actif")
    
    code_pays = models.CharField(max_length=2, default='CI', verbose_name="Code pays")
    
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.nom} ({self.get_type_ferie_display()})"
    
    # -------------------------------------------------------------------------
    # MÉTHODES STATIQUES DE CALCUL
    # -------------------------------------------------------------------------
    
    @staticmethod
    def calculer_date_paques(annee: int) -> date:
        """Calcule la date de Pâques pour une année"""
        return easter(annee)
    
    @staticmethod
    def convertir_hijri_vers_gregorien(annee_hijri: int, mois: int, jour: int) -> Optional[date]:
        """Convertit une date Hijri en date Grégorienne"""
        if not HIJRI_DISPONIBLE:
            return None
        try:
            g = Hijri(annee_hijri, mois, jour).to_gregorian()
            return date(g.year, g.month, g.day)
        except Exception:
            return None
    
    # -------------------------------------------------------------------------
    # MÉTHODES D'INSTANCE
    # -------------------------------------------------------------------------
    
    def calculer_date(self, annee: int) -> Optional[date]:
        """
        Calcule la date du jour férié pour une année donnée
        
        Args:
            annee: Année pour laquelle calculer
            
        Returns:
            Date calculée ou None
        """
        if self.methode_calcul == MethodeCalcul.FIXE:
            if self.mois_fixe and self.jour_fixe:
                try:
                    return date(annee, self.mois_fixe, self.jour_fixe)
                except ValueError:
                    return None
        
        elif self.methode_calcul == MethodeCalcul.PAQUES:
            if self.decalage_paques is not None:
                paques = self.calculer_date_paques(annee)
                return paques + timedelta(days=self.decalage_paques)
        
        elif self.methode_calcul == MethodeCalcul.HIJRI:
            if self.mois_hijri and self.jour_hijri:
                annee_hijri_base = annee - 579
                for annee_hijri in [annee_hijri_base, annee_hijri_base + 1]:
                    resultat = self.convertir_hijri_vers_gregorien(
                        annee_hijri, self.mois_hijri, self.jour_hijri
                    )
                    if resultat and resultat.year == annee:
                        return resultat
        
        return None
    
    def generer_instance(self, annee: int, utilisateur: str = None) -> Optional['JourFerie']:
        """
        Génère une instance JourFerie pour une année
        
        Args:
            annee: Année pour laquelle générer
            utilisateur: Nom de l'utilisateur créateur
            
        Returns:
            Instance JourFerie créée ou None si existe déjà
        """
        date_calculee = self.calculer_date(annee)
        
        if not date_calculee:
            return None
        
        # Vérifier si existe déjà
        if JourFerie.objects.filter(
            modele=self,
            annee=annee,
            code_pays=self.code_pays
        ).exists():
            return None
        
        return JourFerie.objects.create(
            modele=self,
            annee=annee,
            date_ferie=date_calculee,
            date_calculee=date_calculee,
            nom=self.nom,
            type_ferie=self.type_ferie,
            statut=StatutJourFerie.ACTIF,
            est_national=self.est_national,
            est_paye=self.est_paye,
            code_pays=self.code_pays,
            cree_par=utilisateur,
        )


# ============================================================================
# MANAGER: JourFerieManager
# ============================================================================

class JourFerieManager(models.Manager):
    """Manager avec méthodes utilitaires pour les jours fériés"""
    
    # -------------------------------------------------------------------------
    # REQUÊTES DE BASE
    # -------------------------------------------------------------------------
    
    def actifs(self):
        """Retourne uniquement les jours fériés actifs"""
        return self.filter(statut=StatutJourFerie.ACTIF)
    
    def pour_annee(self, annee: int, code_pays: str = 'CI'):
        """Retourne les jours fériés actifs d'une année"""
        return self.actifs().filter(
            annee=annee,
            code_pays=code_pays
        ).order_by('date_ferie')
    
    def pour_periode(self, date_debut: date, date_fin: date, code_pays: str = 'CI'):
        """Retourne les jours fériés dans une période"""
        if date_debut > date_fin:
            date_debut, date_fin = date_fin, date_debut
        
        return self.actifs().filter(
            date_ferie__gte=date_debut,
            date_ferie__lte=date_fin,
            code_pays=code_pays
        ).order_by('date_ferie')
    
    # -------------------------------------------------------------------------
    # VÉRIFICATIONS (ex: est_jour_ferie, obtenir_nom_ferie, obtenir_ferie)
    # -------------------------------------------------------------------------
    
    def est_ferie(self, date_verif: date, code_pays: str = 'CI') -> bool:
        """
        Vérifie si une date est un jour férié
        
        Args:
            date_verif: Date à vérifier
            code_pays: Code ISO du pays
            
        Returns:
            True si la date est un jour férié
        """
        return self.actifs().filter(
            date_ferie=date_verif,
            code_pays=code_pays
        ).exists()
    
    def obtenir_ferie(self, date_verif: date, code_pays: str = 'CI') -> Optional['JourFerie']:
        """
        Retourne le jour férié pour une date ou None
        
        Args:
            date_verif: Date à vérifier
            code_pays: Code ISO du pays
            
        Returns:
            Instance JourFerie ou None
        """
        return self.actifs().filter(
            date_ferie=date_verif,
            code_pays=code_pays
        ).first()
    
    def obtenir_nom_ferie(self, date_verif: date, code_pays: str = 'CI') -> Optional[str]:
        """
        Retourne le nom du jour férié ou None
        
        Args:
            date_verif: Date à vérifier
            code_pays: Code ISO du pays
            
        Returns:
            Nom du jour férié ou None
        """
        ferie = self.obtenir_ferie(date_verif, code_pays)
        return ferie.nom if ferie else None
    
    # -------------------------------------------------------------------------
    # JOURS OUVRABLES (ex: est_jour_ouvrable, compter_jours_ouvrables, ajouter_jours_ouvrables)
    # -------------------------------------------------------------------------
    
    def est_jour_ouvrable(self, date_verif: date, code_pays: str = 'CI') -> bool:
        """
        Vérifie si une date est un jour ouvrable (ni weekend, ni férié)
        
        Args:
            date_verif: Date à vérifier
            code_pays: Code ISO du pays
            
        Returns:
            True si jour ouvrable
        """
        # Weekend (samedi=5, dimanche=6)
        if date_verif.weekday() >= 5:
            return False
        # Jour férié
        if self.est_ferie(date_verif, code_pays):
            return False
        return True
    
    def compter_jours_ouvrables(self, date_debut: date, date_fin: date, code_pays: str = 'CI') -> int:
        """
        Compte les jours ouvrables entre deux dates (incluses)
        
        Args:
            date_debut: Date de début
            date_fin: Date de fin
            code_pays: Code ISO du pays
            
        Returns:
            Nombre de jours ouvrables
        """
        if date_debut > date_fin:
            date_debut, date_fin = date_fin, date_debut
        
        compte = 0
        date_courante = date_debut
        
        while date_courante <= date_fin:
            if self.est_jour_ouvrable(date_courante, code_pays):
                compte += 1
            date_courante += timedelta(days=1)
        
        return compte
    
    def ajouter_jours_ouvrables(self, date_depart: date, nb_jours: int, code_pays: str = 'CI') -> date:
        """
        Ajoute un nombre de jours ouvrables à une date
        
        Args:
            date_depart: Date de départ
            nb_jours: Nombre de jours ouvrables à ajouter (peut être négatif)
            code_pays: Code ISO du pays
            
        Returns:
            Date résultante
        """
        date_courante = date_depart
        jours_restants = abs(nb_jours)
        direction = 1 if nb_jours >= 0 else -1
        
        while jours_restants > 0:
            date_courante += timedelta(days=direction)
            if self.est_jour_ouvrable(date_courante, code_pays):
                jours_restants -= 1
        
        return date_courante
    
    def compter_jours_feries_periode(self, date_debut: date, date_fin: date, code_pays: str = 'CI') -> int:
        """
        Compte les jours fériés dans une période
        
        Args:
            date_debut: Date de début
            date_fin: Date de fin
            code_pays: Code ISO du pays
            
        Returns:
            Nombre de jours fériés
        """
        return self.pour_periode(date_debut, date_fin, code_pays).count()
    
    # -------------------------------------------------------------------------
    # NAVIGATION (ex: prochain_jour_ferie, ferie_precedent)
    # -------------------------------------------------------------------------
    
    def prochain_ferie(self, a_partir_de: date = None, code_pays: str = 'CI') -> Optional['JourFerie']:
        """
        Retourne le prochain jour férié
        
        Args:
            a_partir_de: Date de départ (aujourd'hui par défaut)
            code_pays: Code ISO du pays
            
        Returns:
            Prochain JourFerie ou None
        """
        if a_partir_de is None:
            a_partir_de = date.today()
        
        # Chercher dans l'année courante et suivante
        ferie = self.actifs().filter(
            date_ferie__gte=a_partir_de,
            code_pays=code_pays
        ).order_by('date_ferie').first()
        
        if ferie:
            return ferie
        
        # Générer l'année suivante si nécessaire
        annee_suivante = a_partir_de.year + 1
        self.generer_annee(annee_suivante, code_pays)
        
        return self.actifs().filter(
            date_ferie__gte=a_partir_de,
            code_pays=code_pays
        ).order_by('date_ferie').first()
    
    def ferie_precedent(self, avant_le: date = None, code_pays: str = 'CI') -> Optional['JourFerie']:
        """
        Retourne le jour férié précédent
        
        Args:
            avant_le: Date de référence (aujourd'hui par défaut)
            code_pays: Code ISO du pays
            
        Returns:
            JourFerie précédent ou None
        """
        if avant_le is None:
            avant_le = date.today()
        
        return self.actifs().filter(
            date_ferie__lt=avant_le,
            code_pays=code_pays
        ).order_by('-date_ferie').first()
    
    # -------------------------------------------------------------------------
    # GÉNÉRATION (ex: generer_jours_feries_django)
    # -------------------------------------------------------------------------
    
    @transaction.atomic
    def generer_annee(self, annee: int, code_pays: str = 'CI', utilisateur: str = None, forcer: bool = False) -> Dict:
        """
        Génère tous les jours fériés pour une année
        
        Args:
            annee: Année à générer
            code_pays: Code ISO du pays
            utilisateur: Nom de l'utilisateur
            forcer: Si True, regénère (ne touche pas aux modifiés/personnalisés)
            
        Returns:
            Dictionnaire avec 'crees', 'ignores', 'erreurs'
        """
        resultats = {'crees': [], 'ignores': [], 'erreurs': []}
        
        # Récupérer les modèles actifs
        modeles = ModeleJourFerie.objects.actifs(code_pays)
        
        for modele in modeles:
            try:
                date_calculee = modele.calculer_date(annee)
                
                if not date_calculee:
                    resultats['erreurs'].append({
                        'code': modele.code,
                        'erreur': 'Date non calculable'
                    })
                    continue
                
                # Vérifier doublon par modèle
                existe_modele = self.filter(
                    modele=modele,
                    annee=annee,
                    code_pays=code_pays
                ).exists()
                
                if existe_modele:
                    resultats['ignores'].append({
                        'code': modele.code,
                        'raison': 'Modèle déjà instancié'
                    })
                    continue
                
                # Vérifier doublon par date
                existe_date = self.filter(
                    date_ferie=date_calculee,
                    code_pays=code_pays
                ).exists()
                
                if existe_date:
                    resultats['ignores'].append({
                        'code': modele.code,
                        'raison': f'Date {date_calculee} déjà utilisée'
                    })
                    continue
                
                # Créer l'instance
                instance = self.create(
                    modele=modele,
                    annee=annee,
                    date_ferie=date_calculee,
                    date_calculee=date_calculee,
                    nom=modele.nom,
                    type_ferie=modele.type_ferie,
                    statut=StatutJourFerie.ACTIF,
                    est_modifie=False,
                    est_personnalise=False,
                    est_national=modele.est_national,
                    est_paye=modele.est_paye,
                    code_pays=code_pays,
                    cree_par=utilisateur,
                )
                resultats['crees'].append(instance)
                
            except Exception as e:
                resultats['erreurs'].append({
                    'code': modele.code,
                    'erreur': str(e)
                })
        
        return resultats
    
    def creer_personnalise(
        self,
        annee: int,
        date_ferie: date,
        nom: str,
        type_ferie: str = TypeJourFerie.FERIE_INTERNE,
        description: str = None,
        est_national: bool = False,
        est_paye: bool = True,
        code_pays: str = 'CI',
        utilisateur: str = None
    ) -> 'JourFerie':
        """
        Crée un jour férié personnalisé
        
        Args:
            annee: Année
            date_ferie: Date du férié
            nom: Nom du jour férié
            type_ferie: Type (FERIE_INTERNE par défaut)
            description: Description optionnelle
            est_national: Est-ce un jour national ?
            est_paye: Est-ce un jour chômé payé ?
            code_pays: Code ISO du pays
            utilisateur: Nom de l'utilisateur créateur
            
        Returns:
            Instance JourFerie créée
            
        Raises:
            ValidationError: Si doublon détecté
        """
        # Vérifier doublon par date
        if self.filter(date_ferie=date_ferie, code_pays=code_pays).exists():
            raise ValidationError(f"Un jour férié existe déjà à la date {date_ferie}")
        
        # Vérifier doublon par nom
        if self.filter(nom=nom, annee=annee, code_pays=code_pays).exists():
            raise ValidationError(f"Un jour férié '{nom}' existe déjà pour {annee}")
        
        return self.create(
            modele=None,
            annee=annee,
            date_ferie=date_ferie,
            date_calculee=None,
            nom=nom,
            description=description,
            type_ferie=type_ferie,
            statut=StatutJourFerie.ACTIF,
            est_modifie=False,
            est_personnalise=True,
            est_national=est_national,
            est_paye=est_paye,
            code_pays=code_pays,
            cree_par=utilisateur,
        )
    
    # -------------------------------------------------------------------------
    # VÉRIFICATION ET NETTOYAGE DES DOUBLONS (ex: verifier_doublons_annee, supprimer_doublons_annee)
    # -------------------------------------------------------------------------
    
    def verifier_doublons(self, annee: int, code_pays: str = 'CI') -> Dict:
        """
        Vérifie s'il y a des doublons pour une année
        
        Args:
            annee: Année à vérifier
            code_pays: Code ISO du pays
            
        Returns:
            Dictionnaire avec les doublons par date, nom et modèle
        """
        from django.db.models import Count
        
        doublons = {
            'par_date': [],
            'par_nom': [],
            'par_modele': [],
            'a_doublons': False
        }
        
        # Par date
        dates = self.filter(annee=annee, code_pays=code_pays).values('date_ferie').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        for d in dates:
            feries = self.filter(date_ferie=d['date_ferie'], code_pays=code_pays)
            doublons['par_date'].append({
                'date': d['date_ferie'],
                'feries': list(feries.values('id', 'nom'))
            })
        
        # Par nom
        noms = self.filter(annee=annee, code_pays=code_pays).values('nom').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        for n in noms:
            feries = self.filter(nom=n['nom'], annee=annee, code_pays=code_pays)
            doublons['par_nom'].append({
                'nom': n['nom'],
                'feries': list(feries.values('id', 'date_ferie'))
            })
        
        # Par modèle
        modeles = self.filter(
            annee=annee, 
            code_pays=code_pays,
            modele__isnull=False
        ).values('modele').annotate(count=Count('id')).filter(count__gt=1)
        
        for m in modeles:
            feries = self.filter(modele_id=m['modele'], annee=annee, code_pays=code_pays)
            doublons['par_modele'].append({
                'modele_id': m['modele'],
                'feries': list(feries.values('id', 'nom', 'date_ferie'))
            })
        
        doublons['a_doublons'] = (
            len(doublons['par_date']) > 0 or
            len(doublons['par_nom']) > 0 or
            len(doublons['par_modele']) > 0
        )
        
        return doublons
    
    @transaction.atomic
    def supprimer_doublons(self, annee: int, code_pays: str = 'CI', garder: str = 'premier') -> Dict:
        """
        Supprime les doublons (garde le premier ou dernier créé)
        
        Args:
            annee: Année à nettoyer
            code_pays: Code pays
            garder: 'premier' ou 'dernier'
            
        Returns:
            Dictionnaire avec les suppressions effectuées
        """
        doublons = self.verifier_doublons(annee, code_pays)
        
        if not doublons['a_doublons']:
            return {'message': 'Aucun doublon', 'supprimes': []}
        
        supprimes = []
        
        for d in doublons['par_date']:
            feries = self.filter(
                date_ferie=d['date'],
                code_pays=code_pays
            ).order_by('date_creation')
            
            if garder == 'premier':
                a_supprimer = list(feries[1:])
            else:
                a_supprimer = list(feries[:-1])
            
            for f in a_supprimer:
                supprimes.append({'id': f.id, 'nom': f.nom})
                f.delete()
        
        return {'message': f'{len(supprimes)} supprimé(s)', 'supprimes': supprimes}
    
    # -------------------------------------------------------------------------
    # EXPORT (ex: exporter_json, exporter_fichier_json)
    # -------------------------------------------------------------------------
    
    def exporter_json(self, annee: int, code_pays: str = 'CI') -> List[Dict]:
        """
        Retourne les jours fériés au format JSON
        
        Args:
            annee: Année à exporter
            code_pays: Code ISO du pays
            
        Returns:
            Liste de dictionnaires
        """
        feries = self.pour_annee(annee, code_pays)
        
        return [
            {
                'code': f.modele.code if f.modele else None,
                'date': f.date_ferie.isoformat(),
                'nom': f.nom,
                'type_ferie': f.type_ferie,
                'est_modifiable': f.modele.est_modifiable if f.modele else True,
                'est_personnalise': f.est_personnalise,
                'jour_semaine': f.jour_semaine,
            }
            for f in feries
        ]
    
    def exporter_fichier_json(self, annee: int, fichier: str = None, code_pays: str = 'CI') -> str:
        """
        Exporte les jours fériés vers un fichier JSON
        
        Args:
            annee: Année à exporter
            fichier: Chemin du fichier (généré automatiquement si None)
            code_pays: Code ISO du pays
            
        Returns:
            Chemin du fichier créé
        """
        import json
        
        donnees = self.exporter_json(annee, code_pays)
        fichier = fichier or f"jours_feries_{code_pays.lower()}_{annee}.json"
        
        with open(fichier, 'w', encoding='utf-8') as f:
            json.dump(donnees, f, ensure_ascii=False, indent=2)
        
        return fichier
    
    # -------------------------------------------------------------------------
    # AFFICHAGE (ex: afficher_jours_feries)
    # -------------------------------------------------------------------------
    
    def afficher_console(self, annee: int, code_pays: str = 'CI'):
        """
        Affiche les jours fériés formatés dans la console
        
        Args:
            annee: Année à afficher
            code_pays: Code ISO du pays
        """
        feries = self.pour_annee(annee, code_pays)
        
        print(f"\n{'='*70}")
        print(f"  JOURS FÉRIÉS DE CÔTE D'IVOIRE - {annee}")
        print(f"{'='*70}\n")
        
        for f in feries:
            modifiable = " *" if (f.modele and f.modele.est_modifiable) else ""
            print(f"  {f.date_ferie.strftime('%d/%m/%Y')} ({f.jour_semaine:<9}) - {f.nom:<40} [{f.type_ferie}]{modifiable}")
        
        print(f"\n  Total: {feries.count()} jours fériés")
        print(f"  * = Date modifiable (fêtes islamiques)")
        print(f"{'='*70}\n")


# ============================================================================
# MODÈLE: JourFerie
# ============================================================================

class JourFerie(models.Model):
    """
    Instances réelles des jours fériés pour chaque année
    """
    
    class Meta:
        db_table = 'jours_feries'
        verbose_name = 'Jour férié'
        verbose_name_plural = 'Jours fériés'
        ordering = ['annee', 'date_ferie']
        indexes = [
            models.Index(fields=['date_ferie'], name='idx_date_ferie'),
            models.Index(fields=['annee'], name='idx_annee'),
            models.Index(fields=['code_pays', 'annee'], name='idx_pays_annee'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['modele', 'annee', 'code_pays'],
                name='uq_modele_annee_pays',
                condition=models.Q(modele__isnull=False)
            ),
            models.UniqueConstraint(
                fields=['date_ferie', 'code_pays'],
                name='uq_date_ferie_pays'
            ),
            models.UniqueConstraint(
                fields=['nom', 'annee', 'code_pays'],
                name='uq_nom_annee_pays'
            ),
        ]
    
    objects = JourFerieManager()
    
    modele = models.ForeignKey(
        ModeleJourFerie,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='jours_feries',
        verbose_name="Modèle"
    )
    
    annee = models.PositiveIntegerField(
        verbose_name="Année",
        validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    
    date_ferie = models.DateField(verbose_name="Date du férié")
    date_calculee = models.DateField(null=True, blank=True, verbose_name="Date calculée")
    
    nom = models.CharField(max_length=150, verbose_name="Nom")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    
    type_ferie = models.CharField(
        max_length=20,
        choices=TypeJourFerie.choices,
        default=TypeJourFerie.FERIE_CIVIL,
        verbose_name="Type"
    )
    
    statut = models.CharField(
        max_length=20,
        choices=StatutJourFerie.choices,
        default=StatutJourFerie.ACTIF,
        verbose_name="Statut"
    )
    
    est_modifie = models.BooleanField(default=False, verbose_name="Date modifiée")
    est_personnalise = models.BooleanField(default=False, verbose_name="Personnalisé")
    est_national = models.BooleanField(default=True, verbose_name="National")
    est_paye = models.BooleanField(default=True, verbose_name="Chômé payé")
    
    code_pays = models.CharField(max_length=2, default='CI', verbose_name="Code pays")
    
    cree_par = models.CharField(max_length=100, blank=True, null=True, verbose_name="Créé par")
    modifie_par = models.CharField(max_length=100, blank=True, null=True, verbose_name="Modifié par")
    
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.nom} - {self.date_ferie.strftime('%d/%m/%Y')}"
    
    # -------------------------------------------------------------------------
    # PROPRIÉTÉS
    # -------------------------------------------------------------------------
    
    @property
    def jour_semaine(self) -> str:
        """Retourne le jour de la semaine"""
        jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
        return jours[self.date_ferie.weekday()]
    
    @property
    def jour_semaine_court(self) -> str:
        """Retourne le jour abrégé"""
        jours = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
        return jours[self.date_ferie.weekday()]
    
    @property
    def est_date_modifiee(self) -> bool:
        """Vérifie si la date diffère de la calculée"""
        if self.date_calculee and self.date_ferie:
            return self.date_calculee != self.date_ferie
        return False
    
    @property
    def est_weekend(self) -> bool:
        """Vérifie si le férié tombe un weekend"""
        return self.date_ferie.weekday() >= 5
    
    @property
    def jours_avant(self) -> int:
        """Nombre de jours avant ce férié (depuis aujourd'hui)"""
        return (self.date_ferie - date.today()).days
    
    # -------------------------------------------------------------------------
    # MÉTHODES D'INSTANCE
    # -------------------------------------------------------------------------
    
    def modifier_date(self, nouvelle_date: date, motif: str = None, utilisateur: str = None):
        """
        Modifie la date du jour férié avec traçabilité
        
        Args:
            nouvelle_date: Nouvelle date
            motif: Raison de la modification
            utilisateur: Nom de l'utilisateur
            
        Raises:
            ValidationError: Si doublon détecté
        """
        ancienne_date = self.date_ferie
        
        # Vérifier doublon
        if JourFerie.objects.filter(
            date_ferie=nouvelle_date,
            code_pays=self.code_pays
        ).exclude(pk=self.pk).exists():
            raise ValidationError(f"Un jour férié existe déjà à la date {nouvelle_date}")
        
        self.date_ferie = nouvelle_date
        self.est_modifie = True
        self.modifie_par = utilisateur
        self.save()
        
        # Enregistrer dans l'historique
        HistoriqueModification.objects.create(
            jour_ferie=self,
            action=HistoriqueModification.TypeAction.MODIFICATION,
            champ_modifie='date_ferie',
            ancienne_valeur=str(ancienne_date),
            nouvelle_valeur=str(nouvelle_date),
            motif=motif,
            effectue_par=utilisateur
        )
    
    def reinitialiser_date(self, utilisateur: str = None):
        """
        Remet la date à sa valeur calculée
        
        Args:
            utilisateur: Nom de l'utilisateur
            
        Raises:
            ValidationError: Si pas de date calculée
        """
        if not self.date_calculee:
            raise ValidationError("Ce jour férié n'a pas de date calculée")
        
        if self.date_ferie == self.date_calculee:
            return
        
        ancienne_date = self.date_ferie
        self.date_ferie = self.date_calculee
        self.est_modifie = False
        self.modifie_par = utilisateur
        self.save()
        
        HistoriqueModification.objects.create(
            jour_ferie=self,
            action=HistoriqueModification.TypeAction.MODIFICATION,
            champ_modifie='date_ferie',
            ancienne_valeur=str(ancienne_date),
            nouvelle_valeur=str(self.date_calculee),
            motif='Réinitialisation à la date calculée',
            effectue_par=utilisateur
        )
    
    def desactiver(self, motif: str = None, utilisateur: str = None):
        """
        Désactive ce jour férié
        
        Args:
            motif: Raison de la désactivation
            utilisateur: Nom de l'utilisateur
        """
        self.statut = StatutJourFerie.INACTIF
        self.modifie_par = utilisateur
        self.save()
        
        HistoriqueModification.objects.create(
            jour_ferie=self,
            action=HistoriqueModification.TypeAction.SUPPRESSION,
            champ_modifie='statut',
            ancienne_valeur=StatutJourFerie.ACTIF,
            nouvelle_valeur=StatutJourFerie.INACTIF,
            motif=motif,
            effectue_par=utilisateur
        )
    
    def reactiver(self, utilisateur: str = None):
        """
        Réactive ce jour férié
        
        Args:
            utilisateur: Nom de l'utilisateur
        """
        self.statut = StatutJourFerie.ACTIF
        self.modifie_par = utilisateur
        self.save()
        
        HistoriqueModification.objects.create(
            jour_ferie=self,
            action=HistoriqueModification.TypeAction.RESTAURATION,
            champ_modifie='statut',
            ancienne_valeur=StatutJourFerie.INACTIF,
            nouvelle_valeur=StatutJourFerie.ACTIF,
            effectue_par=utilisateur
        )
    
    # -------------------------------------------------------------------------
    # VALIDATION
    # -------------------------------------------------------------------------
    
    def clean(self):
        """Validation avant sauvegarde"""
        # Doublon de date
        qs_date = JourFerie.objects.filter(
            date_ferie=self.date_ferie,
            code_pays=self.code_pays
        )
        if self.pk:
            qs_date = qs_date.exclude(pk=self.pk)
        
        if qs_date.exists():
            existant = qs_date.first()
            raise ValidationError({
                'date_ferie': f"Un jour férié existe déjà à cette date : {existant.nom}"
            })
        
        # Doublon de modèle
        if self.modele:
            qs_modele = JourFerie.objects.filter(
                modele=self.modele,
                annee=self.annee,
                code_pays=self.code_pays
            )
            if self.pk:
                qs_modele = qs_modele.exclude(pk=self.pk)
            
            if qs_modele.exists():
                raise ValidationError({
                    'modele': f"Ce modèle existe déjà pour l'année {self.annee}"
                })
        
        # Doublon de nom
        qs_nom = JourFerie.objects.filter(
            nom=self.nom,
            annee=self.annee,
            code_pays=self.code_pays
        )
        if self.pk:
            qs_nom = qs_nom.exclude(pk=self.pk)
        
        if qs_nom.exists():
            raise ValidationError({
                'nom': f"Un jour férié '{self.nom}' existe déjà pour {self.annee}"
            })
    
    def save(self, *args, **kwargs):
        self.clean()
        
        if self.date_calculee and self.date_ferie != self.date_calculee:
            self.est_modifie = True
        
        super().save(*args, **kwargs)


# ============================================================================
# MODÈLE: HistoriqueModification
# ============================================================================

class HistoriqueModification(models.Model):
    """Historique des modifications des jours fériés"""
    
    class TypeAction(models.TextChoices):
        CREATION = 'CREATION', 'Création'
        MODIFICATION = 'MODIFICATION', 'Modification'
        SUPPRESSION = 'SUPPRESSION', 'Suppression'
        RESTAURATION = 'RESTAURATION', 'Restauration'
    
    class Meta:
        db_table = 'historique_modifications_feries'
        verbose_name = 'Historique'
        verbose_name_plural = 'Historique des modifications'
        ordering = ['-date_action']
    
    jour_ferie = models.ForeignKey(
        JourFerie,
        on_delete=models.CASCADE,
        related_name='historique',
        verbose_name="Jour férié"
    )
    
    action = models.CharField(max_length=20, choices=TypeAction.choices)
    champ_modifie = models.CharField(max_length=50, blank=True, null=True)
    ancienne_valeur = models.TextField(blank=True, null=True)
    nouvelle_valeur = models.TextField(blank=True, null=True)
    motif = models.TextField(blank=True, null=True)
    effectue_par = models.CharField(max_length=100, blank=True, null=True)
    date_action = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.jour_ferie.nom}"

class SignalementDateFerie(models.Model):
    '''
    Signalements de correction de date par les utilisateurs
    Permet aux utilisateurs de proposer des corrections pour les dates des fériés musulmans
    '''
    
    class StatutSignalement(models.TextChoices):
        EN_ATTENTE = 'EN_ATTENTE', 'En attente'
        ACCEPTE = 'ACCEPTE', 'Accepté'
        REJETE = 'REJETE', 'Rejeté'
    
    class Meta:
        db_table = 'signalements_dates_feries'
        verbose_name = 'Signalement de date'
        verbose_name_plural = 'Signalements de dates'
        ordering = ['-date_signalement']
    
    jour_ferie = models.ForeignKey(
        JourFerie,
        on_delete=models.CASCADE,
        related_name='signalements',
        verbose_name="Jour férié"
    )
    
    date_suggeree = models.DateField(verbose_name="Date suggérée")
    source_info = models.CharField(max_length=255, verbose_name="Source de l'information")
    commentaire = models.TextField(blank=True, null=True, verbose_name="Commentaire")
    
    signale_par = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.SET_NULL,
        null=True,
        related_name='signalements_feries',
        verbose_name="Signalé par"
    )
    
    statut = models.CharField(
        max_length=20,
        choices=StatutSignalement.choices,
        default=StatutSignalement.EN_ATTENTE,
        verbose_name="Statut"
    )
    
    traite_par = models.ForeignKey(
        ProfilUtilisateur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='signalements_traites',
        verbose_name="Traité par"
    )
    
    date_signalement = models.DateTimeField(auto_now_add=True, verbose_name="Date du signalement")
    date_traitement = models.DateTimeField(null=True, blank=True, verbose_name="Date de traitement")
    
    def __str__(self):
        return f"Signalement {self.jour_ferie.nom} → {self.date_suggeree}"
        
'''
from .models import JourFerie, ModeleJourFerie
from datetime import date

# Charger les modèles initiaux (une seule fois)
ModeleJourFerie.objects.charger_donnees_initiales()

# Générer les fériés d'une année
resultats = JourFerie.objects.generer_annee(2026, utilisateur='admin')

# Vérifier si une date est fériée
if JourFerie.objects.est_ferie(date(2026, 12, 25)):
    print("Noël !")

# Obtenir le nom d'un férié
nom = JourFerie.objects.obtenir_nom_ferie(date(2026, 12, 25))

# Prochain jour férié
prochain = JourFerie.objects.prochain_ferie()
print(f"Prochain: {prochain.nom} dans {prochain.jours_avant} jours")

# Jours ouvrables
nb = JourFerie.objects.compter_jours_ouvrables(date(2026, 1, 1), date(2026, 1, 31))
print(f"{nb} jours ouvrables en janvier 2026")

# Ajouter des jours ouvrables
date_fin = JourFerie.objects.ajouter_jours_ouvrables(date(2026, 1, 1), 10)

# Créer un férié personnalisé
JourFerie.objects.creer_personnalise(
    annee=2026,
    date_ferie=date(2026, 3, 8),
    nom="Journée de la Femme",
    utilisateur='admin'
)

# Modifier la date d'un férié (ex: Tabaski confirmée)
tabaski = JourFerie.objects.get(modele__code='tabaski', annee=2026)
tabaski.modifier_date(date(2026, 5, 28), motif="COSIM confirmé", utilisateur='admin')

# Afficher dans la console
JourFerie.objects.afficher_console(2026)

# Exporter en JSON
JourFerie.objects.exporter_fichier_json(2026)
'''