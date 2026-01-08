"""
Exceptions personnalisées pour le système de gestion d'intérim
Gestion d'erreurs spécialisée pour le domaine métier

Types d'exceptions :
- Exceptions métier (business logic)
- Exceptions Kelio (synchronisation)
- Exceptions de validation
- Exceptions de workflow
"""

from django.core.exceptions import ValidationError
from typing import Dict, Any, Optional, List

# ================================================================
# EXCEPTIONS DE BASE
# ================================================================

class InterimException(Exception):
    """Exception de base pour les erreurs métier intérim"""
    
    def __init__(self, message: str, code: str = None, details: Dict[str, Any] = None):
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'exception en dictionnaire pour les réponses JSON"""
        return {
            'error': True,
            'message': self.message,
            'code': self.code,
            'details': self.details
        }
    
    def __str__(self):
        return f"{self.code}: {self.message}"

class InterimValidationError(InterimException, ValidationError):
    """Exception pour les erreurs de validation métier"""
    
    def __init__(self, message: str, field: str = None, code: str = None, details: Dict[str, Any] = None):
        self.field = field
        super().__init__(message, code, details)
        ValidationError.__init__(self, message, code)

# ================================================================
# EXCEPTIONS EMPLOYÉS
# ================================================================

class EmployeNotFoundError(InterimException):
    """Exception quand un employé n'est pas trouvé"""
    
    def __init__(self, matricule: str, message: str = None):
        self.matricule = matricule
        message = message or f"Employé avec matricule {matricule} non trouvé"
        super().__init__(message, 'EMPLOYE_NOT_FOUND', {'matricule': matricule})

class EmployeInactiveError(InterimException):
    """Exception quand un employé n'est pas actif"""
    
    def __init__(self, matricule: str, statut: str = None):
        self.matricule = matricule
        self.statut = statut
        message = f"Employé {matricule} n'est pas actif"
        if statut:
            message += f" (statut: {statut})"
        super().__init__(message, 'EMPLOYE_INACTIVE', {
            'matricule': matricule,
            'statut': statut
        })

class EmployeAlreadyExistsError(InterimException):
    """Exception quand un employé existe déjà"""
    
    def __init__(self, matricule: str, employe_id: int = None):
        self.matricule = matricule
        self.employe_id = employe_id
        message = f"Employé avec matricule {matricule} existe déjà"
        super().__init__(message, 'EMPLOYE_ALREADY_EXISTS', {
            'matricule': matricule,
            'employe_id': employe_id
        })

# ================================================================
# EXCEPTIONS DISPONIBILITÉ ET CANDIDATS
# ================================================================

class CandidatNonDisponibleError(InterimException):
    """Exception quand un candidat n'est pas disponible"""
    
    def __init__(self, candidat_matricule: str, raison: str, periode: Dict[str, Any] = None):
        self.candidat_matricule = candidat_matricule
        self.raison = raison
        self.periode = periode
        
        message = f"Candidat {candidat_matricule} non disponible: {raison}"
        details = {
            'candidat_matricule': candidat_matricule,
            'raison': raison
        }
        if periode:
            details['periode'] = periode
            
        super().__init__(message, 'CANDIDAT_NON_DISPONIBLE', details)

class ConflitDisponibiliteError(InterimException):
    """Exception pour les conflits de disponibilité"""
    
    def __init__(self, matricule: str, conflits: List[Dict[str, Any]]):
        self.matricule = matricule
        self.conflits = conflits
        
        message = f"Conflit de disponibilité pour {matricule}"
        if conflits:
            nb_conflits = len(conflits)
            message += f" ({nb_conflits} conflit{'s' if nb_conflits > 1 else ''})"
        
        super().__init__(message, 'CONFLIT_DISPONIBILITE', {
            'matricule': matricule,
            'conflits': conflits
        })

class PeriodeInvalideError(InterimValidationError):
    """Exception pour les périodes invalides"""
    
    def __init__(self, date_debut: str, date_fin: str, raison: str = None):
        self.date_debut = date_debut
        self.date_fin = date_fin
        self.raison = raison
        
        message = f"Période invalide: {date_debut} à {date_fin}"
        if raison:
            message += f" - {raison}"
        
        super().__init__(message, 'periode', 'PERIODE_INVALIDE', {
            'date_debut': date_debut,
            'date_fin': date_fin,
            'raison': raison
        })

# ================================================================
# EXCEPTIONS WORKFLOW
# ================================================================

class ValidationWorkflowError(InterimException):
    """Exception dans le workflow de validation"""
    
    def __init__(self, demande_numero: str, statut_actuel: str, operation: str, message: str = None):
        self.demande_numero = demande_numero
        self.statut_actuel = statut_actuel
        self.operation = operation
        
        message = message or f"Impossible de {operation} la demande {demande_numero} (statut: {statut_actuel})"
        
        super().__init__(message, 'VALIDATION_WORKFLOW_ERROR', {
            'demande_numero': demande_numero,
            'statut_actuel': statut_actuel,
            'operation': operation
        })

class PermissionValidationError(InterimException):
    """Exception pour les droits de validation insuffisants"""
    
    def __init__(self, utilisateur_matricule: str, demande_numero: str, action: str):
        self.utilisateur_matricule = utilisateur_matricule
        self.demande_numero = demande_numero
        self.action = action
        
        message = f"Utilisateur {utilisateur_matricule} non autorisé à {action} la demande {demande_numero}"
        
        super().__init__(message, 'PERMISSION_VALIDATION_ERROR', {
            'utilisateur_matricule': utilisateur_matricule,
            'demande_numero': demande_numero,
            'action': action
        })

class EtapeWorkflowInvalideError(InterimException):
    """Exception pour les étapes de workflow invalides"""
    
    def __init__(self, demande_numero: str, etape_actuelle: str, etape_demandee: str):
        self.demande_numero = demande_numero
        self.etape_actuelle = etape_actuelle
        self.etape_demandee = etape_demandee
        
        message = f"Transition invalide pour {demande_numero}: {etape_actuelle} → {etape_demandee}"
        
        super().__init__(message, 'ETAPE_WORKFLOW_INVALIDE', {
            'demande_numero': demande_numero,
            'etape_actuelle': etape_actuelle,
            'etape_demandee': etape_demandee
        })

# ================================================================
# EXCEPTIONS KELIO
# ================================================================

class KelioSyncError(InterimException):
    """Exception de base pour les erreurs de synchronisation Kelio"""
    
    def __init__(self, message: str, service: str = None, matricule: str = None, 
                 details: Dict[str, Any] = None):
        self.service = service
        self.matricule = matricule
        
        error_details = details or {}
        if service:
            error_details['service'] = service
        if matricule:
            error_details['matricule'] = matricule
            
        super().__init__(message, 'KELIO_SYNC_ERROR', error_details)

class KelioConnectionError(KelioSyncError):
    """Exception pour les erreurs de connexion Kelio"""
    
    def __init__(self, url: str = None, timeout: int = None, details: Dict[str, Any] = None):
        self.url = url
        self.timeout = timeout
        
        message = "Erreur de connexion au service Kelio"
        if url:
            message += f" ({url})"
        if timeout:
            message += f" - Timeout après {timeout}s"
        
        error_details = details or {}
        if url:
            error_details['url'] = url
        if timeout:
            error_details['timeout'] = timeout
            
        super().__init__(message, details=error_details)

class KelioServiceUnavailableError(KelioSyncError):
    """Exception quand un service Kelio n'est pas disponible"""
    
    def __init__(self, service: str, details: Dict[str, Any] = None):
        message = f"Service Kelio '{service}' non disponible"
        super().__init__(message, service=service, details=details)

class KelioDataError(KelioSyncError):
    """Exception pour les erreurs de données Kelio"""
    
    def __init__(self, message: str, data_type: str = None, matricule: str = None, 
                 details: Dict[str, Any] = None):
        self.data_type = data_type
        
        error_details = details or {}
        if data_type:
            error_details['data_type'] = data_type
            
        super().__init__(message, matricule=matricule, details=error_details)

class KelioEmployeeNotFoundError(KelioSyncError):
    """Exception quand un employé n'est pas trouvé dans Kelio"""
    
    def __init__(self, matricule: str):
        message = f"Employé {matricule} non trouvé dans Kelio"
        super().__init__(message, matricule=matricule, details={'matricule': matricule})

class KelioParsingError(KelioSyncError):
    """Exception pour les erreurs de parsing des données Kelio"""
    
    def __init__(self, service: str, raw_data: str = None, parsing_step: str = None):
        self.raw_data = raw_data
        self.parsing_step = parsing_step
        
        message = f"Erreur de parsing des données Kelio pour le service {service}"
        if parsing_step:
            message += f" (étape: {parsing_step})"
        
        details = {}
        if parsing_step:
            details['parsing_step'] = parsing_step
        if raw_data:
            details['raw_data_length'] = len(raw_data)
            
        super().__init__(message, service=service, details=details)

# ================================================================
# EXCEPTIONS DEMANDES D'INTÉRIM
# ================================================================

class DemandeInterimError(InterimException):
    """Exception de base pour les demandes d'intérim"""
    
    def __init__(self, message: str, demande_numero: str = None, details: Dict[str, Any] = None):
        self.demande_numero = demande_numero
        
        error_details = details or {}
        if demande_numero:
            error_details['demande_numero'] = demande_numero
            
        super().__init__(message, 'DEMANDE_INTERIM_ERROR', error_details)

class DemandeNotFoundError(DemandeInterimError):
    """Exception quand une demande n'est pas trouvée"""
    
    def __init__(self, demande_id: Any):
        self.demande_id = demande_id
        message = f"Demande d'intérim {demande_id} non trouvée"
        super().__init__(message, details={'demande_id': demande_id})

class DemandeExpireeError(DemandeInterimError):
    """Exception pour une demande expirée"""
    
    def __init__(self, demande_numero: str, date_expiration: str):
        self.date_expiration = date_expiration
        message = f"Demande {demande_numero} expirée (date limite: {date_expiration})"
        super().__init__(message, demande_numero, {'date_expiration': date_expiration})

class DemandeStatutInvalideError(DemandeInterimError):
    """Exception pour un statut de demande invalide"""
    
    def __init__(self, demande_numero: str, statut_actuel: str, statuts_autorises: List[str]):
        self.statut_actuel = statut_actuel
        self.statuts_autorises = statuts_autorises
        
        message = f"Statut invalide pour {demande_numero}: {statut_actuel} (autorisés: {', '.join(statuts_autorises)})"
        
        super().__init__(message, demande_numero, {
            'statut_actuel': statut_actuel,
            'statuts_autorises': statuts_autorises
        })

# ================================================================
# EXCEPTIONS CONFIGURATION
# ================================================================

class ConfigurationError(InterimException):
    """Exception pour les erreurs de configuration"""
    
    def __init__(self, message: str, config_type: str = None, details: Dict[str, Any] = None):
        self.config_type = config_type
        
        error_details = details or {}
        if config_type:
            error_details['config_type'] = config_type
            
        super().__init__(message, 'CONFIGURATION_ERROR', error_details)

class ConfigurationKeliomanquanteError(ConfigurationError):
    """Exception quand la configuration Kelio est manquante"""
    
    def __init__(self):
        message = "Aucune configuration Kelio active trouvée"
        super().__init__(message, 'kelio')

class ParametreRequiError(ConfigurationError):
    """Exception pour un paramètre de configuration requis manquant"""
    
    def __init__(self, parametre: str, config_type: str = None):
        self.parametre = parametre
        message = f"Paramètre requis manquant: {parametre}"
        if config_type:
            message += f" (configuration: {config_type})"
        
        super().__init__(message, config_type, {'parametre': parametre})

# ================================================================
# EXCEPTIONS CACHE
# ================================================================

class CacheError(InterimException):
    """Exception pour les erreurs de cache"""
    
    def __init__(self, message: str, operation: str = None, cache_key: str = None):
        self.operation = operation
        self.cache_key = cache_key
        
        details = {}
        if operation:
            details['operation'] = operation
        if cache_key:
            details['cache_key'] = cache_key
            
        super().__init__(message, 'CACHE_ERROR', details)

class CachePleinError(CacheError):
    """Exception quand le cache est plein"""
    
    def __init__(self, taille_actuelle: int, taille_max: int):
        self.taille_actuelle = taille_actuelle
        self.taille_max = taille_max
        
        message = f"Cache plein: {taille_actuelle}MB / {taille_max}MB"
        
        super().__init__(message, 'cache_full', {
            'taille_actuelle': taille_actuelle,
            'taille_max': taille_max
        })

# ================================================================
# GESTIONNAIRE D'EXCEPTIONS GLOBAL
# ================================================================

class InterimExceptionHandler:
    """Gestionnaire centralisé des exceptions intérim"""
    
    @staticmethod
    def handle_exception(exception: Exception, request=None) -> Dict[str, Any]:
        """
        Gère une exception et retourne une réponse standardisée
        
        Args:
            exception: L'exception à gérer
            request: La requête Django (optionnelle)
            
        Returns:
            Dict contenant la réponse d'erreur
        """
        if isinstance(exception, InterimException):
            return exception.to_dict()
        
        # Gestion des exceptions Django standards
        elif isinstance(exception, ValidationError):
            return {
                'error': True,
                'message': str(exception),
                'code': 'VALIDATION_ERROR',
                'details': getattr(exception, 'error_dict', {})
            }
        
        # Gestion des autres exceptions
        else:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Exception non gérée: {type(exception).__name__}: {exception}")
            
            return {
                'error': True,
                'message': 'Une erreur inattendue s\'est produite',
                'code': 'UNEXPECTED_ERROR',
                'details': {
                    'exception_type': type(exception).__name__,
                    'exception_message': str(exception)
                }
            }
    
    @staticmethod
    def get_user_friendly_message(exception: Exception) -> str:
        """
        Retourne un message d'erreur convivial pour l'utilisateur
        
        Args:
            exception: L'exception à traiter
            
        Returns:
            Message d'erreur convivial
        """
        if isinstance(exception, InterimException):
            return exception.message
        
        elif isinstance(exception, ValidationError):
            return "Les données fournies ne sont pas valides"
        
        elif isinstance(exception, PermissionError):
            return "Vous n'avez pas les droits nécessaires pour cette action"
        
        else:
            return "Une erreur inattendue s'est produite. Veuillez réessayer."

# ================================================================
# FONCTIONS UTILITAIRES
# ================================================================

def raise_if_invalid_matricule(matricule: str):
    """
    Valide un matricule et lève une exception si invalide
    
    Args:
        matricule: Le matricule à valider
        
    Raises:
        InterimValidationError: Si le matricule est invalide
    """
    if not matricule:
        raise InterimValidationError("Matricule requis", field='matricule')
    
    if not matricule.strip():
        raise InterimValidationError("Matricule ne peut pas être vide", field='matricule')
    
    if len(matricule) < 3:
        raise InterimValidationError("Matricule trop court (minimum 3 caractères)", field='matricule')
    
    if len(matricule) > 20:
        raise InterimValidationError("Matricule trop long (maximum 20 caractères)", field='matricule')
    
    import re
    if not re.match(r'^[A-Z0-9]+$', matricule.upper()):
        raise InterimValidationError("Matricule doit contenir uniquement des lettres et chiffres", field='matricule')

def raise_if_invalid_date_range(date_debut, date_fin):
    """
    Valide une plage de dates et lève une exception si invalide
    
    Args:
        date_debut: Date de début
        date_fin: Date de fin
        
    Raises:
        PeriodeInvalideError: Si la plage de dates est invalide
    """
    if not date_debut or not date_fin:
        raise PeriodeInvalideError(str(date_debut), str(date_fin), "Dates de début et fin requises")
    
    if date_debut > date_fin:
        raise PeriodeInvalideError(str(date_debut), str(date_fin), "Date de début postérieure à la date de fin")
    
    from datetime import date, timedelta
    
    # Vérifier que la période n'est pas trop longue (ex: max 1 an)
    duree = date_fin - date_debut
    if duree > timedelta(days=365):
        raise PeriodeInvalideError(str(date_debut), str(date_fin), "Période trop longue (maximum 1 an)")
    
    # Vérifier que la date de début n'est pas trop dans le passé
    if date_debut < date.today() - timedelta(days=30):
        raise PeriodeInvalideError(str(date_debut), str(date_fin), "Date de début trop ancienne")

def create_business_exception(error_type: str, **kwargs) -> InterimException:
    """
    Factory pour créer des exceptions métier
    
    Args:
        error_type: Type d'erreur
        **kwargs: Paramètres spécifiques à l'exception
        
    Returns:
        Instance d'exception appropriée
    """
    exception_map = {
        'employe_not_found': EmployeNotFoundError,
        'candidat_non_disponible': CandidatNonDisponibleError,
        'validation_workflow': ValidationWorkflowError,
        'kelio_sync': KelioSyncError,
        'demande_not_found': DemandeNotFoundError,
        'configuration': ConfigurationError,
    }
    
    exception_class = exception_map.get(error_type, InterimException)
    return exception_class(**kwargs)